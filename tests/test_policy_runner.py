"""Background MuJoCo runs for 균형 제어 (khumanoid/policy_runner.py): the worker thread, the queue,
cancelling and the result cache with a stand-in for the simulation (no MuJoCo or GMT needed), and -
with GMT installed (scripts/install_gmt.ps1) - that the runner gives what policy_replay.run gives."""

import json
import os
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import paths, policy_replay as pr, policy_runner  # noqa: E402
from khumanoid.policy_runner import Cancelled, PolicyRunner  # noqa: E402
from khumanoid.synthetic import g1_motion  # noqa: E402


class FakeSim:
    """policy_replay.run's stand-in: the reference resampled at 50 Hz, a fall at 0.2 s for "pd". With
    gate set, each run waits for gate.set() and keeps calling progress (so a cancel can stop it)."""

    def __init__(self, gate: threading.Event | None = None, fail: bool = False):
        self.gate, self.fail = gate, fail
        self.calls: list[str] = []
        self.threads: set[str] = set()

    def __call__(self, motion, controller, progress):
        self.calls.append(controller)
        self.threads.add(threading.current_thread().name)
        progress(0, 10)
        while self.gate is not None and not self.gate.wait(0.01):
            progress(1, 10)
        if self.fail:
            raise ValueError("broken policy")
        n = int(round(motion.duration * 50)) + 1
        idx = np.clip(np.round(np.arange(n) / 50 * motion.fps).astype(int), 0, motion.num_frames - 1)
        col = [motion.joint_names.index(j) for j in pr.GMT_DOFS]
        falls = [0.2] if controller == "pd" else []
        metrics = {"controller": controller, "falls": len(falls), "fall_times_s": falls,
                   "fall_causes": ["tilt"] * len(falls), "hold_falls": 0, "hold_fall_times_s": [],
                   "body_error_cm": 9.0 if controller == "pd" else 4.0, "torque_saturated_ratio": 0.1}
        return pr.Result(controller, np.arange(n) / 50, motion.root_pos[idx], motion.root_quat[idx],
                         motion.dof_pos[idx][:, col], metrics)


@pytest.fixture
def gmt_root(tmp_path):
    """A GMT folder with stand-in files: what problem() looks for."""
    root = tmp_path / "GMT"
    for rel in (pr.gmt_paths(str(root))["model"], pr.gmt_paths(str(root))["policy"]):
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        with open(rel, "w") as f:
            f.write("stand-in")
    return str(root)


def _runner(tmp_path, gmt_root, sim, **kw) -> PolicyRunner:
    cfg = tmp_path / "physics.yaml"
    if not cfg.exists():
        cfg.write_text("pd: []\nfall: {tilt_error_deg: 60}\n", encoding="utf-8")
    return PolicyRunner(str(tmp_path / "cache"), physics_config=str(cfg), gmt_root=gmt_root, simulate=sim, **kw)


def _wait(job, timeout=30.0):
    end = time.time() + timeout
    while job.active and time.time() < end:
        time.sleep(0.01)
    return job


def test_runs_in_the_background_and_caches(tmp_path, gmt_root):
    from khumanoid.compare import load_item

    m = g1_motion(seconds=1.0)
    gate = threading.Event()
    sim = FakeSim(gate)
    runner = _runner(tmp_path, gmt_root, sim)
    seen = []
    t0 = time.time()
    job = runner.request(m, "pd", info={"label": "synthetic/walk", "kind": "robot npz"}, on_done=seen.append)
    assert time.time() - t0 < 1.0 and job.active  # request() does not wait for the run
    assert runner.request(m, "pd", on_done=seen.append) is job  # one run per motion and controller
    end = time.time() + 10
    while job.progress == 0 and time.time() < end:
        time.sleep(0.01)
    assert job.state == "running" and runner.busy() and 0 < job.progress < 1 and job.stage == "시뮬레이션"
    gate.set()
    _wait(job)
    assert job.state == "done" and job.progress == 1.0 and seen == [job, job] and not runner.busy()
    assert sim.threads == {"policy-runner"} and sim.calls == ["pd"]  # on the worker thread, once
    assert os.path.dirname(job.result) == str(tmp_path / "cache") and job.result.endswith("_pd_sim.npz")
    with open(job.result[:-4] + ".json", encoding="utf-8") as f:
        info = json.load(f)
    assert info["label"] == "synthetic/walk" and info["policy_replay"]["falls"] == 1
    item = load_item(job.result, log=None)  # the same files as tools/policy_replay.py writes
    assert item.kind.startswith("MuJoCo 재생") and item.robot.fps == 50 and len(item.robot.joint_names) == 29

    # the cache: a new runner (next start of RetLens) finds the result without simulating
    sim2 = FakeSim()
    again = _runner(tmp_path, gmt_root, sim2)
    late = []
    hit = again.request(m, "pd", on_done=late.append)
    assert hit.state == "done" and hit.stage.startswith("완료") and hit.result == job.result and late == [hit]
    assert again.cached(m, "pd") == job.result and sim2.calls == []
    for r in (runner, again):
        r.shutdown()


def test_cache_key(tmp_path, gmt_root):
    m = g1_motion(seconds=1.0)
    runner = _runner(tmp_path, gmt_root, FakeSim())
    k = runner.key(m, "pd")
    assert runner.key(m, "pd") == k and runner.key(m, "gmt") != k  # per controller
    m2 = g1_motion(seconds=1.0)
    m2.dof_pos = m2.dof_pos.copy()
    m2.dof_pos[5, 3] += 0.01
    assert runner.key(m2, "pd") != k  # the motion's content
    cfg = tmp_path / "physics.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "# other gains\n", encoding="utf-8")
    assert runner.key(m, "pd") != k  # configs/physics.yaml (PD gains, fall rules)
    k_cfg, k_gmt = runner.key(m, "pd"), runner.key(m, "gmt")
    with open(pr.gmt_paths(gmt_root)["policy"], "w") as f:
        f.write("another checkpoint")
    assert runner.key(m, "pd") == k_cfg and runner.key(m, "gmt") != k_gmt  # the policy file: GMT only
    short = _runner(tmp_path, gmt_root, FakeSim(), hold_s=0.0)
    assert short.key(m, "pd") != k_cfg  # the hold after the clip
    for r in (runner, short):
        r.shutdown()


def test_cancel_queued_and_running(tmp_path, gmt_root):
    gate = threading.Event()
    sim = FakeSim(gate)
    runner = _runner(tmp_path, gmt_root, sim)
    a, b = g1_motion(seconds=1.0), g1_motion(seconds=1.5)
    done = []
    ja = runner.request(a, "pd", on_done=done.append)
    jb = runner.request(b, "pd", on_done=done.append)
    end = time.time() + 10
    while ja.state != "running" and time.time() < end:
        time.sleep(0.01)
    assert jb.state == "queued"  # one clip at a time
    runner.cancel(jb)
    assert jb.state == "cancelled" and done == [jb]
    runner.cancel(ja)  # running: stops at its next progress call
    _wait(ja)
    assert ja.state == "cancelled" and ja.result is None and not os.path.exists(ja.out_npz)
    gate.set()
    jc = _wait(runner.request(a, "pd"))  # a cancelled run can be asked for again, and the worker still runs
    assert jc is not ja and jc.state == "done"
    runner.shutdown()


def test_failure_keeps_the_worker(tmp_path, gmt_root):
    runner = _runner(tmp_path, gmt_root, FakeSim(fail=True))
    job = _wait(runner.request(g1_motion(seconds=1.0), "pd"))
    assert job.state == "failed" and "broken policy" in job.message and not os.path.exists(job.out_npz)
    runner._simulate = FakeSim()
    assert _wait(runner.request(g1_motion(seconds=1.0), "pd")).state == "done"  # a failed run is retried
    runner.shutdown()


def test_problem(tmp_path, gmt_root, monkeypatch):
    pytest.importorskip("mujoco")
    assert policy_runner.problem("pd", gmt_root) == ""
    assert "install_gmt.ps1" in policy_runner.problem("pd", str(tmp_path / "nowhere"))
    assert "알 수 없는" in policy_runner.problem("lqr", gmt_root)
    os.remove(pr.gmt_paths(gmt_root)["policy"])
    assert policy_runner.problem("pd", gmt_root) == "" and "추적 정책" in policy_runner.problem("gmt", gmt_root)
    runner = _runner(tmp_path, gmt_root, FakeSim())
    with pytest.raises(RuntimeError, match="추적 정책"):
        runner.request(g1_motion(seconds=1.0), "gmt")
    runner.shutdown()
    monkeypatch.setattr(paths, "FROZEN", True)  # the installed program: no PyTorch, no GMT next to it
    assert "설치판" in policy_runner.problem("gmt", gmt_root)
    assert "설치판" in policy_runner.problem("pd", str(tmp_path / "nowhere"))


def test_progress_raises_once_cancelled(tmp_path, gmt_root):
    """The default simulation stops through policy_replay.run's progress calls (every 0.5 s simulated)."""
    calls = []

    def sim(motion, controller, progress):
        for k in range(0, 1000, 25):
            calls.append(k)
            progress(k, 1000)
            if k == 50:
                runner.cancel(next(iter(runner.jobs.values())))
        raise AssertionError("not cancelled")

    runner = _runner(tmp_path, gmt_root, sim)
    job = _wait(runner.request(g1_motion(seconds=1.0), "pd"))
    assert job.state == "cancelled" and calls == [0, 25, 50, 75]
    # cancelled after the worker took it from the queue, before it started: it never runs
    late = policy_runner.PolicyJob(key="x", name="x", controller="pd", out_npz=str(tmp_path / "x_sim.npz"))
    runner.cancel(late)
    assert late.cancel_requested and late.state == "queued"
    with pytest.raises(Cancelled):
        runner._run(late)
    runner.shutdown()


def test_runner_matches_policy_replay():
    """With GMT: the runner's MuJoCo run is policy_replay.run's (tools/policy_replay.py), number for number."""
    pytest.importorskip("torch")
    pytest.importorskip("mujoco")
    try:
        files = pr.gmt_files()
    except FileNotFoundError as e:
        pytest.skip(str(e))
    import tempfile

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    import policy_replay as tool

    m = tool.gmt_sample("squat")
    with tempfile.TemporaryDirectory() as d:
        runner = PolicyRunner(d, hold_s=0.5)
        for c in pr.CONTROLLERS:
            job = _wait(runner.request(m, c), timeout=300)
            assert job.state == "done", job.message
            with open(job.result[:-4] + ".json", encoding="utf-8") as f:
                got = json.load(f)["policy_replay"]
            want = pr.run(pr.G1Sim(files["model"], c, policy_path=files["policy"]), pr.Reference.from_motion(m),
                          hold_s=0.5).metrics
            assert got == json.loads(json.dumps(want)), c
        runner.shutdown()
