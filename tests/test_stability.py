"""Balance metrics (khumanoid.stability), the static-imbalance QC flag and fall diagnosis."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import stability  # noqa: E402
from khumanoid.diagnosis import diagnose_fall, onset  # noqa: E402
from khumanoid.motion import RobotMotion  # noqa: E402
from khumanoid.qc import QCResult, add_balance_flags  # noqa: E402
from khumanoid.synthetic import g1_motion  # noqa: E402


def test_hull_and_signed_margin():
    square = stability.convex_hull([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5], [0.2, 0.7]])
    assert len(square) == 4
    assert np.isclose(stability.signed_margin([0.5, 0.5], square), 0.5)
    assert np.isclose(stability.signed_margin([0.9, 0.5], square), 0.1)
    assert np.isclose(stability.signed_margin([1.5, 0.5], square), -0.5)
    assert np.isclose(stability.signed_margin([2.0, 2.0], square), -np.sqrt(2))
    segment = stability.convex_hull([[0, 0], [1, 0]])  # one edge on the floor: no inside
    assert len(segment) == 2 and np.isclose(stability.signed_margin([0.5, 0.2], segment), -0.2)
    assert np.isclose(stability.signed_margin([3, 4], stability.convex_hull([[0, 0]])), -5.0)


def test_com_from_links():
    pos = np.array([[[0.0, 0, 0], [1.0, 0, 0]]])
    quat = np.tile([1.0, 0, 0, 0], (1, 2, 1))
    com = stability.com_from_links(pos, quat, np.zeros((2, 3)), np.array([1.0, 3.0]))
    assert np.allclose(com, [[0.75, 0, 0]])
    yaw90 = np.array([[[np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)]] * 2])  # local +x -> world +y
    com = stability.com_from_links(pos, yaw90, np.array([[0.1, 0, 0], [0.1, 0, 0]]), np.array([1.0, 1.0]))
    assert np.allclose(com, [[0.5, 0.1, 0]])


def test_zmp_cart_table_matches_the_analytic_value():
    fps, A, w, h = 100.0, 0.05, 2 * np.pi * 0.5, 0.8
    t = np.arange(0, 6, 1 / fps)
    com = np.stack([A * np.sin(w * t), np.zeros_like(t), np.full_like(t, h)], 1)
    zmp, acc = stability.zmp_cart_table(com, fps, 0.0, cutoff_hz=6.0)
    mid = slice(100, 500)  # away from the filter's ends
    assert np.allclose(acc[mid, 0], -A * w ** 2 * np.sin(w * t[mid]), atol=0.01)
    assert np.allclose(zmp[mid, 0], A * np.sin(w * t[mid]) * (1 + h * w ** 2 / 9.81), atol=0.003)


def test_zmp_is_not_differentiated_across_a_reset():
    # a physics replay teleports the robot back to the clip after a fall: a 1 m jump in the CoM
    fps, T = 30.0, 60
    com = np.zeros((T, 3))
    com[:, 2] = 0.7
    com[30:, 0] = 1.0
    jumpy, _ = stability.zmp_cart_table(com, fps)
    split, acc = stability.zmp_cart_table(com, fps, breaks=[30])
    assert np.abs(jumpy[:, 0] - com[:, 0]).max() > 0.5  # the jump looks like a huge acceleration
    assert np.allclose(split[:, 0], com[:, 0]) and np.allclose(acc, 0.0)


def _feet(T: int, dx: float = 0.0) -> np.ndarray:
    """(T, 2, 4, 3) sole corners of two 20 x 8 cm feet on the floor, 20 cm apart."""
    foot = np.array([[-0.05, -0.04, 0], [0.15, -0.04, 0], [0.15, 0.04, 0], [-0.05, 0.04, 0]])
    two = np.stack([foot + [dx, 0.1, 0], foot + [dx, -0.1, 0]])
    return np.repeat(two[None], T, 0)


def test_balance_track_and_static_imbalance():
    fps, T = 30.0, 60
    inside = np.tile([0.05, 0.0, 0.7], (T, 1))  # standing over the middle of the feet
    tr = stability.balance_track(inside, _feet(T), fps)
    assert (tr.phase == 2).all() and np.nanmin(tr.com_margin) > 0.05 and np.nanmin(tr.zmp_margin) > 0.05
    assert not stability.static_unbalanced(tr).any()

    ahead = np.tile([0.40, 0.0, 0.7], (T, 1))  # standing still with the CoM 25 cm ahead of the toes
    tr = stability.balance_track(ahead, _feet(T), fps)
    s = stability.summarize(tr)
    assert np.isclose(np.nanmax(tr.com_margin), -0.25) and s["com"]["outside_ratio"] == 1.0
    assert stability.static_unbalanced(tr).all() and s["static_unbalanced_ratio"] == 1.0

    walk = np.column_stack([np.linspace(0, 1.2, T), np.zeros(T), np.full(T, 0.7)])  # passes over the feet at 0.6 m/s
    tr = stability.balance_track(walk, _feet(T), fps)
    assert (np.nan_to_num(tr.com_margin) < 0).any() and not stability.static_unbalanced(tr).any()

    lifted = _feet(T)
    lifted[20:30, :, :, 2] = 0.1  # both feet off the floor: no support, not counted
    tr = stability.balance_track(inside, lifted, fps)
    assert (tr.phase[20:30] == 0).all() and np.isnan(tr.com_margin[20:30]).all()
    assert stability.summarize(tr)["support_phase_ratio"]["none"] == pytest.approx(10 / T, abs=1e-4)


def test_static_imbalance_is_a_soft_qc_flag():
    res = QCResult("clip", "", "robot", 30.0, 100, 3.3, 3.3, "PASS")
    flag = np.zeros(100, bool)
    flag[:20] = True
    add_balance_flags(res, flag)
    assert res.status == "WARN" and res.valid_s == 3.3 and not res.hard_mask().any()
    assert res.metrics["static_unbalanced_ratio"] == 0.2


def test_fall_diagnosis_picks_the_first_new_cause():
    T = 40
    toe, torque, exit_ = np.zeros(T, bool), np.zeros(T, bool), np.zeros(T, bool)
    toe[20:24] = True
    torque[22:30] = True
    exit_[:] = True  # active before the window opened: chronic, not the trigger
    conditions = {"toe_catch": toe, "torque_saturation": torque, "support_exit": exit_}
    evidence = {"toe_catch": lambda i, a, b: {"frame": i}}
    d = diagnose_fall(conditions, evidence, fall=30, start=10, fps=30.0)
    assert d["primary_cause"] == "toe_catch" and d["primary_onset_s"] == round(20 / 30, 3)
    assert d["primary_evidence"] == {"frame": 20}
    assert [c["cause"] for c in d["candidates"]] == ["toe_catch", "torque_saturation", "support_exit"]
    d = diagnose_fall({"torque_saturation": torque, "support_exit": exit_}, {}, fall=30, start=10, fps=30.0)
    assert d["primary_cause"] == "torque_saturation"
    assert diagnose_fall({}, {}, fall=30, start=10, fps=30.0)["primary_cause"] == "undetermined"
    # a harness spike is a consequence: a chronic cause wins, dated from where its run began
    harness = np.zeros(T, bool)
    harness[25:31] = True
    lean = np.zeros(T, bool)
    lean[5:31] = True
    d = diagnose_fall({"harness_spike": harness, "support_exit": lean}, {}, fall=30, start=10, fps=30.0, earliest=3)
    assert d["primary_cause"] == "support_exit" and d["primary_onset_s"] == round(5 / 30, 3)
    assert diagnose_fall({"harness_spike": harness}, {}, fall=30, start=10, fps=30.0)["primary_cause"] == "harness_spike"
    one = np.zeros(T, bool)
    one[15] = True  # a single frame is noise ...
    assert onset(one, 10, 30) is None
    one[30] = True  # ... unless it is the fall frame itself
    assert onset(one, 10, 30) == 30


def test_g1_standing_flat_vs_on_the_heels():
    pytest.importorskip("general_motion_retargeting")
    from khumanoid import analysis

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    T = 30

    def stand(ankle_pitch: float) -> RobotMotion:
        dof = np.zeros((T, 29))
        for s in ("left", "right"):
            dof[:, joints.index(f"{s}_ankle_pitch_joint")] = ankle_pitch
        root = np.tile([0.0, 0.0, 0.793], (T, 1))
        m = RobotMotion("stand", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)
        root[:, 2] -= fk.run(m)["sole"].min()  # lowest sole point on the floor
        return RobotMotion("stand", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)

    track, s, static = analysis.balance(stand(0.0), fk)
    assert (track.phase == 2).all() and s["com"]["margin_m"]["min"] > 0.02 and not static.any()
    # feet tipped 0.35 rad: one edge of each sole on the floor, CoM well off it (like CMU subject 143's retargets)
    track, s, static = analysis.balance(stand(0.35), fk)
    assert s["com"]["margin_m"]["min"] < -0.02 and static.all()
