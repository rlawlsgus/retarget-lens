"""Regression tests for problems a whole-program check found in physics, the updater and the launch scripts."""

import glob
import http.client
import os
import sys
import types

import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from retlens import analysis, install, physics_runner, stability  # noqa: E402
from retlens import policy_replay as pr  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402

SHA = "ab" * 32


# ------------------------------------------------------------------ updater
def test_a_zip_the_browser_renamed_still_updates(tmp_path):
    z = tmp_path / "RetLens-1.2.3-win64 (1).zip"
    z.write_bytes(b"zip")
    (tmp_path / "RetLens-1.2.3-win64.zip.sha256").write_text(f"{SHA}  RetLens-1.2.3-win64.zip\n")
    rel = install.release_from_zip(str(z))
    assert rel.version == "1.2.3" and rel.sha256 == SHA
    assert rel.asset_name == "RetLens-1.2.3-win64.zip" and rel.local_zip == str(z)
    with pytest.raises(install.UpdateError):
        install.release_from_zip(str(tmp_path / "RetLens-1.2.3-win64 copy.zip"))


def test_a_broken_http_answer_is_an_update_error(monkeypatch):
    def fail(*_a, **_k):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(install, "opener", lambda *_: types.SimpleNamespace(open=fail))
    with pytest.raises(install.UpdateError, match="IncompleteRead"):
        install._get(install.API_LATEST, frozenset())


# ------------------------------------------------------------------ Isaac runner
def test_cancel_a_job_the_worker_has_taken_but_not_started(tmp_path):
    runner = physics_runner.PhysicsRunner(str(tmp_path), command=[sys.executable])
    try:
        job = physics_runner.PhysicsJob(key="k", name="clip", assist=1.0, out_dir=str(tmp_path))
        runner.jobs[job.key] = job  # taken off the queue by the worker, not running yet
        runner.cancel(job)  # used to raise "not in deque" and run anyway
        assert job.state == "cancelled"
        runner._run(job)
        assert job.proc is None and job.state == "cancelled"
        late = physics_runner.PhysicsJob(key="k2", name="clip2", assist=1.0, out_dir=str(tmp_path))
        runner.jobs[late.key] = late
        runner.shutdown()
        assert late.state == "cancelled"
    finally:
        runner.shutdown()


def test_a_cancelled_job_stays_cancelled_when_the_isaac_lookup_then_fails(tmp_path, monkeypatch):
    """The worker took the job and looks Isaac up; the job is cancelled meanwhile (here: the program closes) and
    the lookup fails. The job stays cancelled, as its callbacks were told, rather than turning into a failure."""
    logs, seen = [], []
    runner = physics_runner.PhysicsRunner(str(tmp_path), log=logs.append, robot_usd="")

    def lookup():
        runner.shutdown()
        raise FileNotFoundError("Isaac Sim not found")

    monkeypatch.setattr(physics_runner, "isaac_command", lookup)
    m = RobotMotion("clip", ["a"], np.zeros((5, 3)), np.tile([1.0, 0, 0, 0], (5, 1)), np.zeros((5, 1)), 30.0)
    job = runner.request(m, 1.0, on_done=lambda j: seen.append(j.state))
    runner._worker.join(10)
    assert not runner._worker.is_alive()
    assert (job.state, job.stage, job.message) == ("cancelled", "취소됨", "취소됨") and seen == ["cancelled"]
    assert not any("failed" in s for s in logs)


# ------------------------------------------------------------------ MuJoCo physics
def test_reference_needs_two_frames_and_a_frame_rate():
    with pytest.raises(ValueError, match="2프레임"):
        pr.Reference(np.zeros((1, 3)), [[0, 0, 0, 1]], np.zeros((1, 3)), 30)
    with pytest.raises(ValueError, match="2프레임"):
        pr.Reference(np.zeros((5, 3)), np.tile([0, 0, 0, 1.0], (5, 1)), np.zeros((5, 3)), 0)


def test_missing_g1_joints_do_not_blame_gmt():
    m = RobotMotion(name="other", joint_names=["a"], root_pos=np.zeros((3, 3)), root_quat=np.tile([1.0, 0, 0, 0], (3, 1)),
                    dof_pos=np.zeros((3, 1)), fps=30)
    with pytest.raises(ValueError) as e:
        pr.Reference.from_motion(m)
    assert "GMT" not in str(e.value) and "G1" in str(e.value)


MOTORS = """<mujoco><worldbody><body><joint name="a" type="hinge"/><joint name="b" type="hinge"/>
<joint name="c" type="hinge"/><joint name="d" type="hinge"/><geom size=".1"/><body><joint name="e" type="hinge"/>
<joint name="f" type="hinge"/><joint name="g" type="hinge"/><geom size=".1"/></body></body></worldbody><actuator>
<motor joint="a" ctrlrange="-88 88" gear="2"/><general joint="b" forcerange="-50 50" forcelimited="true"/>
<position joint="c" kp="100"/><motor joint="d" gear="10" forcerange="-5 5"/>
<position joint="e" kp="1000" gear="20" forcerange="-4 4"/><motor joint="f" ctrlrange="-1 1"/>
<motor joint="g" gear="50" ctrlrange="-1 1" forcerange="-2 2"/></actuator></mujoco>"""


def test_torque_limits_also_come_from_the_motors():
    """What MuJoCo can put on the joint: the force range times the gear, a motor's control range times its gain and
    gear, the smaller of the two; a position servo without a force range, and a normalized -1..1 command (the G1
    mocap model's placeholder motors, which made a copy of that model limp at 1 N m), give none."""
    import mujoco

    model = mujoco.MjModel.from_xml_string(MOTORS)
    lim = pr._motor_limits(model)
    assert lim == {"a": pytest.approx(176.0), "b": pytest.approx(50.0), "d": pytest.approx(50.0),
                   "e": pytest.approx(80.0), "g": pytest.approx(50.0)}
    data = mujoco.MjData(model)  # MuJoCo's own torque at a saturated command agrees
    data.ctrl[:] = 1e6
    mujoco.mj_forward(model, data)
    for name, tau in lim.items():
        assert abs(data.qfrc_actuator[model.joint(name).dofadr[0]]) == pytest.approx(tau)


def _toybot(tmp_path):
    pytest.importorskip("mujoco")
    from test_robot_profile import toybot

    return toybot(str(tmp_path / "toy.xml"))


def test_a_joints_own_torque_limit_wins_over_its_motors(tmp_path):
    """The joint's own limit (actuatorfrcrange, URDF effort) is the robot's; a motor's only counts for a joint without
    one. Joints with neither get 1000 N m and are counted in the result (torque saturation is not judged there)."""
    from retlens import robot_profile

    path = _toybot(tmp_path)
    names = robot_profile.load(path).joint_names()
    a, b = names[:2]
    with open(path, encoding="utf-8") as f:
        xml = f.read()
    assert f'<joint name="{a}"' in xml
    xml = xml.replace(f'<joint name="{a}"', f'<joint name="{a}" actuatorfrcrange="-40 40"', 1)
    motors = (f'<motor joint="{a}" ctrlrange="-10 10"/><motor joint="{b}" gear="10" forcerange="-5 5"/>'
              + "".join(f'<motor joint="{n}" ctrlrange="-1 1"/>' for n in names[2:]))
    assert "<actuator" not in xml and xml.count("</mujoco>") == 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml.replace("</mujoco>", f"<actuator>{motors}</actuator></mujoco>"))
    sim = pr.RobotSim(path, "pd")
    lim = dict(zip(sim.joint_names, sim.tau_lim))
    assert lim[a] == pytest.approx(40.0) and lim[b] == pytest.approx(50.0)
    assert sim.no_torque_limit == names[2:] and all(lim[n] == 1000.0 for n in names[2:])
    T = 10
    m = RobotMotion("still", names, np.tile([0.0, 0.0, 1.0], (T, 1)), np.tile([1.0, 0, 0, 0], (T, 1)),
                    np.zeros((T, len(names))), 30.0)
    metrics = pr.run(sim, pr.Reference.from_motion(m, joints=names), hold_s=0.0).metrics
    assert metrics["torque_limits_missing"] == len(names) - 2
    assert pr.RESULT_VERSION >= 4  # results cached with the old limits are made again


def test_a_copy_of_the_g1_model_keeps_its_joint_torque_limits(tmp_path):
    """GMR's G1 MJCF run as another robot (a copy the user edited, say): its motors' -1..1 placeholders are no torque
    limit, the joints' 5..139 N m are."""
    pytest.importorskip("mujoco")
    from retlens import paths, robot_profile

    src = os.path.join(paths.robot_assets_dir(), "unitree_g1", "g1_mocap_29dof.xml")
    if not os.path.isfile(src):
        pytest.skip("the G1 model is not here")
    with open(src, encoding="utf-8") as f:
        xml = f.read()
    meshes = os.path.join(os.path.dirname(src), "meshes").replace("\\", "/")
    xml = xml.replace('meshdir="meshes"', f'meshdir="{meshes}"', 1)
    copy = str(tmp_path / "g1_copy.xml")
    with open(copy, "w", encoding="utf-8") as f:
        f.write(xml)
    assert not robot_profile.is_builtin(copy)
    assert pr._motor_limits(robot_profile.load(copy).model()) == {}
    sim = pr.RobotSim(copy, "harness")
    lim = dict(zip(sim.joint_names, sim.tau_lim))
    assert sim.no_torque_limit == [] and float(sim.tau_lim.min()) == 5.0 and float(sim.tau_lim.max()) == 139.0
    assert (lim["left_knee_joint"], lim["left_hip_pitch_joint"], lim["left_ankle_pitch_joint"]) == (139.0, 88.0, 50.0)


def test_robot_without_sole_points_is_refused(tmp_path, monkeypatch):
    """robot_profile refuses a robot whose feet have no sole points before the physics would stand it on them."""
    from retlens import robot_profile

    path = _toybot(tmp_path)  # a new path: load() makes its parts anew
    monkeypatch.setattr(robot_profile, "_sole_points", lambda *a: [])
    with pytest.raises(robot_profile.RobotError, match="sole points"):
        pr.RobotSim(path, "harness")


# ------------------------------------------------------------------ NaN samples
def test_one_nan_frame_does_not_blank_the_balance_and_smoothness_numbers():
    T = 300
    t = np.arange(T) / 30
    com = np.stack([0.02 * np.sin(t), 0.01 * np.cos(t), 0.7 + 0 * t], 1)
    corners = np.zeros((T, 2, 4, 3))
    corners[:, 0, :, :2] = [[-.1, .05], [.1, .05], [.1, .15], [-.1, .15]]
    corners[:, 1, :, :2] = [[-.1, -.15], [.1, -.15], [.1, -.05], [-.1, -.05]]
    clean = stability.summarize(stability.balance_track(com, corners, 30))
    com[100, 2] = np.nan
    assert np.isnan(stability.lowpass(com, 30)).any(1).sum() == 1
    dirty = stability.summarize(stability.balance_track(com, corners, 30))
    assert dirty["zmp"]["margin_m"]["p5"] == pytest.approx(clean["zmp"]["margin_m"]["p5"], abs=1e-3)
    q = np.tile(np.sin(t)[:, None], (1, 4))
    q[100, 2] = np.nan
    m = RobotMotion(name="x", joint_names=list("abcd"), root_pos=np.zeros((T, 3)),
                    root_quat=np.tile([1.0, 0, 0, 0], (T, 1)), dof_pos=q, fps=30)
    s = analysis.smoothness(m)
    assert all(np.isfinite(v) for v in s.values())


# ------------------------------------------------------------------ launch scripts
def test_windows_scripts_are_ascii():
    """cmd.exe and Windows PowerShell 5.1 read BOM-less files in the local code page: Korean text there comes out
    garbled, and in editor.bat a ')' inside the text broke the whole if block. PowerShell reads UTF-8 with a BOM;
    cmd.exe does not (the BOM turns '@echo off' into an unknown command), so a .bat must be plain ASCII."""
    for p in glob.glob(os.path.join(ROOT, "scripts", "*.bat")) + glob.glob(os.path.join(ROOT, "scripts", "*.ps1")):
        with open(p, "rb") as f:
            raw = f.read()
        if p.lower().endswith(".ps1") and raw.startswith(b"\xef\xbb\xbf"):
            continue  # PowerShell 5.1 reads UTF-8 with a BOM correctly
        assert raw.isascii(), os.path.basename(p)
