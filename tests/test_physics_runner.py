"""Background physics runs (retlens/physics_runner.py) with a stand-in for
tools/isaac_replay.py, so no Isaac Sim is needed."""

import os
import sys
import textwrap
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import physics_runner  # noqa: E402
from retlens.physics_runner import PhysicsRunner, isaac_command  # noqa: E402
from retlens.synthetic import g1_motion  # noqa: E402

FAKE_REPLAY = textwrap.dedent("""
    import argparse, json, os, sys, time
    import numpy as np
    ap = argparse.ArgumentParser()
    for k in ("--robot-motion", "--check-out", "--assist", "--video", "--human"):
        ap.add_argument(k)
    ap.add_argument("--physics", action="store_true")
    a, _ = ap.parse_known_args()
    mode = os.environ.get("FAKE_REPLAY_MODE", "ok")
    print("Starting kit application", flush=True)
    if mode == "eula":
        sys.exit("Unable to bootstrap inner kit kernel: EULA not accepted. Set OMNI_KIT_ACCEPT_EULA=YES")
    print("eula env " + os.environ.get("OMNI_KIT_ACCEPT_EULA", "-"), flush=True)
    for i in range(10):
        print(f"[isaac_replay] progress simulate {i + 1}/10", flush=True)
        time.sleep(0.5 if mode == "slow" else 0.0)
    print("[isaac_replay] simulated 10 frames in 0.1s", flush=True)
    if a.video:
        os.makedirs(os.path.dirname(a.video), exist_ok=True)
        with open(a.video, "w") as f:
            json.dump({"human": a.human, "physics": a.physics, "assist": a.assist}, f)
        sys.exit(0)
    name = os.path.splitext(os.path.basename(a.robot_motion))[0]
    base = os.path.join(a.check_out, name + "_sim")
    np.savez(base + ".npz", **dict(np.load(a.robot_motion)))
    with open(base + ".json", "w") as f:
        json.dump({"physics": {"harness_scale": float(a.assist), "falls": 0}}, f)
""")


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "fake_replay.py"
    script.write_text(FAKE_REPLAY, encoding="utf-8")
    return str(script)


def _runner(tmp_path, fake, **kw) -> PhysicsRunner:
    cfg = tmp_path / "physics.yaml"
    if not cfg.exists():
        cfg.write_text("sim: {physics_hz: 240}\n", encoding="utf-8")
    return PhysicsRunner(str(tmp_path / "cache"), physics_config=str(cfg), script=fake, command=[sys.executable], **kw)


def _wait(job, timeout=60.0):
    end = time.time() + timeout
    while job.active and time.time() < end:
        time.sleep(0.05)
    return job


def test_run_progress_and_cache(tmp_path, fake):
    m = g1_motion(seconds=0.5)
    runner = _runner(tmp_path, fake)
    seen = []
    job = runner.request(m, 1.0, on_done=seen.append)
    assert runner.request(m, 1.0) is job  # the queued / running job is shared
    _wait(job)
    assert job.state == "done" and job.progress == 1.0 and seen == [job]
    assert job.result.endswith("_sim.npz") and os.path.isfile(job.result)
    assert np.allclose(np.load(job.result)["dof_pos"], m.dof_pos, atol=1e-6)
    assert any("progress simulate 10/10" in ln for ln in job.log_tail)
    assert os.path.isfile(os.path.join(job.out_dir, "run.log"))
    runner.shutdown()

    again = _runner(tmp_path, fake)  # a new session finds it on disk
    hit = []
    j2 = again.request(m, 1.0, on_done=hit.append)
    assert j2.state == "done" and j2.result == job.result and hit == [j2] and j2.stage == "완료 (이미 있음)"
    again.shutdown()


def test_video_jobs_share_the_queue(tmp_path, fake):
    import json

    m = g1_motion(seconds=0.5)
    human = tmp_path / "walk.bvh"
    human.write_text("HIERARCHY", encoding="utf-8")
    runner = _runner(tmp_path, fake)
    phys = runner.request(m, 1.0)
    kin = runner.request_video(m, str(tmp_path / "videos" / "walk_kin.mp4"), human=str(human))
    sim = runner.request_video(m, str(tmp_path / "videos" / "walk_phys.mp4"), human=str(human), physics=True, assist=0.0)
    assert kin.key != sim.key and kin.kind == "video"
    assert kin.key == runner.video_key(m, str(human)) and sim.key == runner.video_key(m, str(human), True, 0.0)
    for job in (phys, kin, sim):
        _wait(job)
    assert phys.state == kin.state == sim.state == "done"
    assert phys.finished <= kin.started and kin.finished <= sim.started  # one Isaac at a time, in order
    with open(kin.result) as f:
        assert json.load(f) == {"human": str(human), "physics": False, "assist": None}
    with open(sim.result) as f:
        assert json.load(f) == {"human": str(human), "physics": True, "assist": "0"}
    again = runner.request_video(m, str(tmp_path / "videos" / "walk_kin.mp4"), human=str(human))
    assert again is kin  # the same video is not rendered twice
    runner.shutdown()


def test_key_follows_motion_harness_and_config(tmp_path, fake):
    m = g1_motion(seconds=0.5)
    runner = _runner(tmp_path, fake)
    k = runner.key(m, 1.0)
    assert runner.key(m, 0.0) != k
    m2 = g1_motion(seconds=0.5)
    m2.dof_pos[3, 0] += 0.01
    assert runner.key(m2, 1.0) != k
    (tmp_path / "physics.yaml").write_text("sim: {physics_hz: 120}\n", encoding="utf-8")
    assert runner.key(m, 1.0) != k
    runner.shutdown()


def test_eula_is_only_accepted_when_asked(tmp_path, fake, monkeypatch):
    m = g1_motion(seconds=0.5)
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)
    monkeypatch.setenv("FAKE_REPLAY_MODE", "eula")
    runner = _runner(tmp_path, fake)
    job = _wait(runner.request(m, 1.0))
    assert job.state == "failed" and "EULA" in job.message and job.result is None
    runner.shutdown()

    monkeypatch.setenv("FAKE_REPLAY_MODE", "ok")
    runner = _runner(tmp_path, fake, accept_eula=True)
    job = _wait(runner.request(m, 1.0))  # a failed job is retried on the next request
    assert job.state == "done" and any(ln == "eula env YES" for ln in job.log_tail)
    runner.shutdown()


def test_cancel_stops_the_process(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("FAKE_REPLAY_MODE", "slow")
    runner = _runner(tmp_path, fake)
    a = runner.request(g1_motion(seconds=0.5), 1.0)
    b = runner.request(g1_motion(seconds=0.5), 0.0)  # queued behind a
    end = time.time() + 30
    while (a.state != "running" or a.progress <= physics_runner.STARTING[2]) and time.time() < end:
        time.sleep(0.05)
    assert b.state == "queued"
    runner.cancel(b)
    assert b.state == "cancelled"
    runner.cancel(a)
    _wait(a, 10)
    assert a.state == "cancelled" and a.result is None
    assert not runner.busy()
    runner.shutdown()


def test_isaac_command_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))  # no saved 환경 설정 in the way
    monkeypatch.setenv(physics_runner.ISAAC_ENV, str(tmp_path / "missing.bat"))
    with pytest.raises(FileNotFoundError):
        isaac_command()
    launcher = tmp_path / "python.bat"
    launcher.write_text("", encoding="utf-8")
    monkeypatch.setenv(physics_runner.ISAAC_ENV, str(launcher))
    assert isaac_command() == [str(launcher)]
