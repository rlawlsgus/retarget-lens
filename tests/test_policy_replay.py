"""Balance on / off in MuJoCo (khumanoid/policy_replay.py, tools/policy_replay.py): the numpy port of
GMT's reference sampling, and - with GMT installed (scripts/install_gmt.ps1) - that the tracking
policy keeps the G1 up where the open-loop PD replay falls."""

import os
import sys

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from khumanoid import policy_replay as pr  # noqa: E402


def _gmt():
    pytest.importorskip("mujoco")  # the policy itself runs in numpy (khumanoid/gmt_policy.py)
    try:
        return pr.gmt_files()
    except FileNotFoundError as e:
        pytest.skip(str(e))


def test_quaternion_helpers_match_scipy():
    rng = np.random.default_rng(0)
    a, b = R.random(50, random_state=1), R.random(50, random_state=2)
    qa, qb = a.as_quat(), b.as_quat()  # scipy is xyzw, like GMT
    assert np.allclose(np.abs(np.sum(pr.quat_mul(qa, qb) * (a * b).as_quat(), axis=1)), 1.0)
    v = rng.normal(size=(50, 3))
    assert np.allclose(pr.quat_rotate_inverse(qa, v), a.inv().apply(v))
    d = (b * a.inv())
    assert np.allclose(pr.quat_to_exp_map(pr.quat_mul(qb, pr.quat_conj(qa))), d.as_rotvec(), atol=1e-9)
    assert np.allclose(pr.slerp(qa, qb, np.zeros(50)), qa) and np.allclose(np.abs(np.sum(pr.slerp(qa, qb, np.ones(50)) * qb, 1)), 1)
    roll, pitch = pr.roll_pitch_xyzw(qa)
    eul = a.as_euler("xyz")  # extrinsic xyz = GMT's roll / pitch / yaw convention
    assert np.allclose(roll, eul[:, 0]) and np.allclose(pitch, eul[:, 1])


def test_reference_sampling():
    n, fps = 90, 30.0
    pos = np.stack([np.arange(n) / fps, np.zeros(n), np.full(n, 0.78)], axis=1)  # 1 m/s forward
    rot = np.tile([0.0, 0.0, 0.0, 1.0], (n, 1))
    dof = np.tile(pr.GMT_DEFAULT, (n, 1))
    ref = pr.Reference(pos, rot, dof, fps)
    assert np.allclose(ref.root_vel[20:-20, 0], 1.0)  # finite difference, box-filtered
    assert ref.root_vel[0, 0] < 0.6  # GMT's zero padding fades the ends
    p, q, v, w, _, dv = ref.frame([ref.length + 5.0])  # past the end: holds the last frame, standing still
    assert np.allclose(p[0], pos[-1]) and np.allclose(q[0], rot[-1])
    assert not np.any(v) and not np.any(w) and not np.any(dv) and not np.any(ref.pd_velocity([ref.length + 1.0]))
    v0, _, _ = ref.start_velocities(0.0)  # a restart moves at the clip's real speed, not the faded estimate
    assert np.isclose(v0[0], 1.0) and not np.any(ref.start_velocities(ref.length + 0.5)[0])
    obs = ref.mimic_obs(0)
    assert obs.shape == (600,)  # 20 future frames x (z, roll, pitch, lin vel 3, yaw rate, 23 DoF)
    assert np.isclose(obs[0], 0.78) and np.isclose(obs[3], ref.root_vel[0, 0])  # first target: 0.02 s ahead


def test_gmt_port_matches_the_authors_closed_loop():
    """From GMT's own start (keyframe 'home') on its walk_stand example, the authors' sim2sim.py
    reaches this root position after 1 s (checked 2026-10-21, MuJoCo 3.11, CPU); our port matched it
    exactly, joint for joint, up to 3 s."""
    files = _gmt()
    import policy_replay as tool

    m = tool.gmt_sample("walk_stand")
    xyzw = np.concatenate([m.root_quat[:, 1:], m.root_quat[:, :1]], axis=1)
    ref = pr.Reference(m.root_pos, xyzw, m.dof_pos, m.fps, loop=True)
    sim = pr.G1Sim(files["model"], "gmt", policy_path=files["policy"])
    pr.run(sim, ref, home=True, duration_s=1.0)
    assert np.allclose(sim.data.qpos[:3], [0.173, -0.172, 0.777], atol=5e-3)


def test_gmt_balances_where_open_loop_pd_falls(tmp_path):
    files = _gmt()
    import policy_replay as tool
    from khumanoid.compare import load_item

    m = tool.gmt_sample("squat")
    ref = pr.Reference.from_motion(m)
    out = {}
    for c in pr.CONTROLLERS:
        res = pr.run(pr.G1Sim(files["model"], c, policy_path=files["policy"]), ref, hold_s=0.5)
        out[c] = res.metrics
        path = pr.save_result(res, str(tmp_path / f"squat_{c}_sim.npz"), m.joint_names,
                              {"label": "gmt_samples/squat", "controller_label": pr.LABELS[c]})
        item = load_item(path)
        assert item.kind.startswith("MuJoCo 재생") and item.robot.num_frames == len(res.times)
    assert out["gmt"]["falls"] == 0 and out["gmt"]["body_error_cm"] < 5.0
    assert out["pd"]["falls"] >= 1  # no balance feedback: even the authors' clean example falls
    assert out["pd"]["joint_rmse_deg"] < out["gmt"]["joint_rmse_deg"]  # the policy bends the joints to stay up
    assert tool.write_summary(str(tmp_path)).endswith("summary.md")
