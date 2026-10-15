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
