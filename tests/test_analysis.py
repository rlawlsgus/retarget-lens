import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import analysis  # noqa: E402
from khumanoid.motion import RobotMotion  # noqa: E402
from khumanoid.synthetic import g1_motion  # noqa: E402


def _shifted(m: RobotMotion, seconds: float) -> RobotMotion:
    """Same motion starting `seconds` later in its own clip (frames dropped from the front)."""
    k = int(round(seconds * m.fps))
    return RobotMotion(m.name + "_late", m.joint_names, m.root_pos[k:], m.root_quat[k:], m.dof_pos[k:], m.fps)


def test_sampling_and_rmse():
    m = g1_motion(seconds=4.0, fps=30.0)
    t = np.array([0.0, 1.0 / 30, 0.5 / 30, 100.0])
    q = analysis.sample_dof(m, t)
    assert np.allclose(q[0], m.dof_pos[0]) and np.allclose(q[1], m.dof_pos[1])
    assert np.allclose(q[2], 0.5 * (m.dof_pos[0] + m.dof_pos[1]))
    assert np.allclose(q[3], m.dof_pos[-1])  # clamped
    pos, quat = analysis.sample_root(m, t)
    assert np.allclose(np.linalg.norm(quat, axis=1), 1.0) and np.allclose(pos[0], m.root_pos[0])
    joints, rmse, ov = analysis.joint_rmse(m, m)
    assert joints == m.joint_names and np.allclose(rmse, 0.0) and ov == pytest.approx(m.duration - 1 / 30)
    # no overlap -> NaN, 0 s
    _, rmse, ov = analysis.joint_rmse(m, m, 0.0, 10.0)
    assert ov == 0.0 and np.isnan(rmse).all()


def test_estimate_offset_recovers_shift():
    m = g1_motion(seconds=6.0, fps=30.0)
    late = _shifted(m, 0.5)  # its frame 0 is m's frame at 0.5 s -> display offset +0.5 s lines them up
    off, rms = analysis.estimate_offset(m, late, max_shift=1.0)
    assert off == pytest.approx(0.5, abs=1 / 30) and rms < 0.5
    joints, rmse, _ = analysis.joint_rmse(m, late, 0.0, off)
    assert np.nanmax(rmse) < 0.5


def test_common_joints_and_smoothness():
    m = g1_motion(seconds=2.0, fps=30.0)
    sub = RobotMotion("sub", m.joint_names[:5], m.root_pos, m.root_quat, m.dof_pos[:, :5], m.fps)
    assert analysis.common_joints(m, sub) == m.joint_names[:5]
    s = analysis.smoothness(m)
    assert set(s) == {"acc_mean", "jerk_mean", "vel_p99", "vel_max"} and s["vel_max"] >= s["vel_p99"] > 0
    noisy = RobotMotion("n", m.joint_names, m.root_pos, m.root_quat,
                        m.dof_pos + np.random.default_rng(0).normal(0, 0.02, m.dof_pos.shape), m.fps)
    assert analysis.smoothness(noisy)["acc_mean"] > 3 * s["acc_mean"]


def test_foot_metrics_with_gmr_model():
    pytest.importorskip("general_motion_retargeting")
    fk = analysis.FootKinematics("unitree_g1")
    m = g1_motion(seconds=1.0, fps=30.0)
    r = fk.run(m)
    assert r["sole"].shape == (30, 2) and r["foot"].shape == (30, 2, 3)
    assert np.all(r["flat"] >= r["sole"])  # highest contact point is above the lowest
    stand = RobotMotion("stand", m.joint_names, np.tile([0.0, 0.0, 0.793], (30, 1)), np.tile([1.0, 0, 0, 0], (30, 1)),
                        np.zeros((30, 29)), 30.0)  # G1 zero pose with the pelvis at its standing height
    fm = analysis.foot_metrics(stand, fk)
    assert abs(fm["sole_min_cm"]) < 1.0 and fm["planted_slip_pct"] == 0.0 and fm["penetration_pct"] == 0.0
    assert fm["swing_low_pct"] == 0.0  # standing still: no swing frames
    # a foot dragged forward along the floor (pelvis slides at 1 m/s, nothing lifts) = every swing frame low
    drag = RobotMotion("drag", m.joint_names, np.column_stack([np.arange(30) / 30.0, np.zeros(30), np.full(30, 0.793)]),
                       np.tile([1.0, 0, 0, 0], (30, 1)), np.zeros((30, 29)), 30.0)
    assert analysis.foot_metrics(drag, fk)["swing_low_pct"] == 100.0


def test_swing_clearance_lifts_only_skimming_swing_feet():
    pytest.importorskip("general_motion_retargeting")
    from khumanoid.retarget import ensure_swing_clearance

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    T = 45
    stand = RobotMotion("stand", joints, np.tile([0.0, 0.0, 0.793], (T, 1)), np.tile([1.0, 0, 0, 0], (T, 1)),
                        np.zeros((T, 29)), 30.0)
    same, info = ensure_swing_clearance(stand, clearance=0.02)
    assert info["frames_changed"] == 0 and np.array_equal(same.dof_pos, stand.dof_pos)

    # knees a little bent, both feet dragged along the floor at 1 m/s between 0.25 s stands
    dof = np.zeros((T, 29))
    for side in ("left", "right"):
        dof[:, joints.index(f"{side}_hip_pitch_joint")] = -0.3
        dof[:, joints.index(f"{side}_knee_joint")] = 0.6
        dof[:, joints.index(f"{side}_ankle_pitch_joint")] = -0.3
    x = np.concatenate([np.zeros(8), np.linspace(0, 1.0, 31)[1:], np.ones(7)])
    root = np.column_stack([x, np.zeros(T), np.full(T, 0.793)])
    probe = RobotMotion("probe", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)
    root[:, 2] -= fk.run(probe)["sole"].min()  # soles on the floor
    drag = RobotMotion("drag", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)
    out, info = ensure_swing_clearance(drag, clearance=0.02)
    assert info["fast_foot_min_clearance_cm"]["before"] < 0.1 and info["fast_foot_min_clearance_cm"]["after"] >= 1.8
    assert info["leg_joint_change_deg"]["max"] <= 20.0 + 1e-6
    sole0, sole1 = fk.run(drag)["sole"], fk.run(out)["sole"]
    assert np.all(sole1[12:34] - sole0[12:34] > 0.018)  # while sliding fast: lifted to ~2 cm
    assert np.allclose(sole1[:6], sole0[:6]) and np.allclose(sole1[-5:], sole0[-5:])  # standing still: untouched
    assert np.array_equal(out.root_pos, drag.root_pos)
    legs = [i for i, n in enumerate(joints) if any(k in n for k in ("hip", "knee", "ankle"))]
    others = [i for i in range(29) if i not in legs]
    assert np.array_equal(out.dof_pos[:, others], drag.dof_pos[:, others])  # arms / waist untouched


FBX_02_01 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "retargeted", "cmu_fbx_smooth6",
                         "02_01_g1.npz")


@pytest.mark.skipif(not os.path.isfile(FBX_02_01), reason="needs the FBX retarget of CMU 02_01 (README)")
def test_swing_clearance_on_fbx_walk():
    """The HF FBX retarget of 02_01 drags its toes at toe-off (mid-swing minimum below the floor level)."""
    pytest.importorskip("general_motion_retargeting")
    from khumanoid.io import load_motion
    from khumanoid.retarget import ensure_swing_clearance

    m = load_motion(FBX_02_01)
    out, info = ensure_swing_clearance(m, clearance=0.02)
    assert info["fast_foot_min_clearance_cm"]["before"] < 0.0 < 1.0 <= info["fast_foot_min_clearance_cm"]["after"]
    fk = analysis.FootKinematics("unitree_g1")
    before, after = analysis.foot_metrics(m, fk), analysis.foot_metrics(out, fk)
    assert after["swing_low_pct"] < before["swing_low_pct"] / 1.5
    assert after["penetration_pct"] <= before["penetration_pct"] and after["planted_slip_pct"] <= before["planted_slip_pct"]
    assert info["leg_joint_change_deg"]["rmse"] < 3.0 and info["leg_joint_change_deg"]["max"] <= 20.0 + 1e-6
