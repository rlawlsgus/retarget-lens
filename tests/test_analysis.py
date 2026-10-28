import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import analysis  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402
from retlens.synthetic import g1_motion  # noqa: E402


def _need_retargeting():
    """Skip without mink / mujoco / the G1 model (GMR's solver itself is vendored in retlens/gmr)."""
    from retlens.retarget import unavailable

    why = unavailable()
    if why:
        pytest.skip(why)


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
    _need_retargeting()
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
    _need_retargeting()
    from retlens.retarget import ensure_swing_clearance

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


def _on_floor(fk, joints: list[str], dof: np.ndarray, x: np.ndarray | None = None) -> RobotMotion:
    """G1 at these joint angles, pelvis upright at x (default 0) and lowered until the lowest sole point is on the floor."""
    T = len(dof)
    root = np.column_stack([np.zeros(T) if x is None else x, np.zeros(T), np.full(T, 0.793)])
    probe = RobotMotion("probe", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)
    root[:, 2] -= fk.run(probe)["sole"].min()
    return RobotMotion("m", joints, root, np.tile([1.0, 0, 0, 0], (T, 1)), dof, 30.0)


def _knees_bent(joints: list[str], T: int) -> np.ndarray:
    """Hips -0.3, knees 0.6, ankles -0.3 rad: soles flat, legs bent like a standing retarget's
    (a straight leg cannot lower its foot a few mm without a large knee bend)."""
    dof = np.zeros((T, 29))
    for s in ("left", "right"):
        dof[:, joints.index(f"{s}_hip_pitch_joint")] = -0.3
        dof[:, joints.index(f"{s}_knee_joint")] = 0.6
        dof[:, joints.index(f"{s}_ankle_pitch_joint")] = -0.3
    return dof


def test_foot_flat_stands_tilted_stance_soles_flat_on_the_floor():
    _need_retargeting()
    from retlens.retarget import _FeetFK, flatten_stance_feet, robot_joint_ranges, robot_model

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    lp, lr = joints.index("left_ankle_pitch_joint"), joints.index("left_ankle_roll_joint")
    rp, rr = joints.index("right_ankle_pitch_joint"), joints.index("right_ankle_roll_joint")
    legs = [i for i, n in enumerate(joints) if any(k in n for k in ("hip", "knee", "ankle"))]
    others = [i for i in range(29) if i not in legs]
    lo, hi = robot_joint_ranges(robot_model("unitree_g1"))
    T = 45

    # standing still: left foot toe-up 12 deg and rolled 5 deg (on its heel edge, 0.7 cm above the
    # right foot's toe), right foot toe-down 8 deg (heel-off) and rolled 4 deg
    dof = _knees_bent(joints, T)
    dof[:, lp] += np.radians(-12.0)  # negative ankle pitch = toe up
    dof[:, lr] = np.radians(5.0)
    dof[:, rp] += np.radians(8.0)
    dof[:, rr] = np.radians(4.0)
    stand = _on_floor(fk, joints, dof)
    out, info = flatten_stance_feet(stand)
    assert info["stance_pct"] == {"left": 100.0, "right": 100.0}
    assert info["stance_pitch_deg"]["left"]["before"] == pytest.approx(12.0, abs=0.5)
    assert abs(info["stance_pitch_deg"]["left"]["after"]) < 0.5
    # toe down: pitch kept (flattening it would lift the toe off the floor), roll levelled
    assert info["stance_pitch_deg"]["right"]["after"] == pytest.approx(info["stance_pitch_deg"]["right"]["before"], abs=0.5)
    R = _FeetFK(out, "unitree_g1").poses(out.dof_pos)[1]
    assert np.degrees(np.abs(np.arcsin(R[:, 1, 2, 1]))).max() < 1.0  # right foot's roll 4 deg -> about level
    r0, r1 = fk.run(stand), fk.run(out)
    assert np.all(r1["flat"][:, 0] - r1["sole"][:, 0] < 2e-3)  # every left sole point at one height...
    assert np.all(np.abs(r1["sole"]) < 2e-3)  # ...and both feet on the floor: no heel lifted, the high foot lowered
    assert info["two_feet_height_diff_cm"]["before"]["max"] > 0.6 > 0.1 > info["two_feet_height_diff_cm"]["after"]["max"]
    assert np.abs(r1["foot"][..., :2] - r0["foot"][..., :2]).max() < 1e-3  # ankles stay where they stand
    assert 0.5 < info["root_drop_cm"]["max"] < 3.0  # the pelvis came down to let the foot down
    assert np.allclose(out.root_pos[:, :2], stand.root_pos[:, :2]) and np.array_equal(out.root_quat, stand.root_quat)
    assert np.array_equal(out.dof_pos[:, others], stand.dof_pos[:, others])  # arms / waist untouched
    assert np.all(out.dof_pos >= lo - 1e-9) and np.all(out.dof_pos <= hi + 1e-9)

    # both feet tiptoe (30 deg toe-down, the ankle's limit): beyond max_tilt_deg, left alone
    dof = _knees_bent(joints, T)
    dof[:, [lp, rp]] = hi[lp]
    tiptoe = _on_floor(fk, joints, dof)
    same, info = flatten_stance_feet(tiptoe)
    assert info["frames_changed"] == 0 and info["too_tilted_frames"] == 2 * T
    assert np.array_equal(same.dof_pos, tiptoe.dof_pos) and np.array_equal(same.root_pos, tiptoe.root_pos)

    # legs spread 20 deg (soles rolled ~18 deg): the ankle rolls stop short of their 15 deg limit,
    # the rest is taken by the legs and pelvis as far as holding the joints near their angles allows
    dof = _knees_bent(joints, T)
    dof[:, joints.index("left_hip_roll_joint")], dof[:, joints.index("right_hip_roll_joint")] = np.radians([20.0, -20.0])
    spread = _on_floor(fk, joints, dof)
    out, info = flatten_stance_feet(spread)
    assert info["stance_tilt_deg"]["before"]["max"] > 15.0 and info["stance_tilt_deg"]["after"]["max"] < 5.0
    assert info["joint_limit_frames"] == 0 and np.abs(out.dof_pos[:, [lr, rr]]).max() < hi[lr] - np.radians(1.0)
    assert np.all(out.dof_pos >= lo - 1e-9) and np.all(out.dof_pos <= hi + 1e-9)


def test_foot_flat_holds_the_swing_foot_while_the_pelvis_drops():
    """One foot stands toe-up, the other leg swings above the floor: the standing foot is
    levelled with the pelvis coming down, and the swing foot keeps its place in the world."""
    _need_retargeting()
    from retlens.retarget import flatten_stance_feet

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    T = 45
    dof = _knees_bent(joints, T)
    dof[:, joints.index("left_ankle_pitch_joint")] += np.radians(-10.0)
    t = np.arange(T) / 30.0
    dof[:, joints.index("right_hip_pitch_joint")] = -0.6 + 0.25 * np.sin(2 * np.pi * t)  # right leg bent more (foot
    dof[:, joints.index("right_knee_joint")] = 1.2  # ~8 cm up) and swinging back and forth
    dof[:, joints.index("right_ankle_pitch_joint")] = -0.6
    m = _on_floor(fk, joints, dof)
    out, info = flatten_stance_feet(m)
    assert info["stance_pct"]["left"] == 100.0 and info["stance_pct"]["right"] == 0.0
    r0, r1 = fk.run(m), fk.run(out)
    assert np.all(r1["flat"][:, 0] - r1["sole"][:, 0] < 2e-3) and np.abs(r1["sole"][:, 0]).max() < 2e-3
    assert info["root_drop_cm"]["max"] > 0.5
    assert np.abs(r1["foot"][:, 1] - r0["foot"][:, 1]).max() < 1e-3  # the swing foot made up for the pelvis


def test_self_collision_repair_moves_only_the_arms_and_free_legs():
    """Hands hanging into the hip housings come out with the shoulders and elbows alone; knees
    touching come apart through the swinging leg's hip, and are left (reported) while both feet stand."""
    _need_retargeting()
    from retlens.retarget import _SelfCollisionModel, separate_self_collisions

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    arms = [i for i, n in enumerate(joints) if "shoulder" in n or "elbow" in n]
    T = 30

    def deepest(m):
        S = _SelfCollisionModel(m, "unitree_g1")
        out = []
        for t in range(m.num_frames):
            S.pose(m.dof_pos[t], t)
            out.append(min((c[4] for c in S.contacts(0.0)), default=0.0))
        return -np.array(out)

    dof = _knees_bent(joints, T)
    dof[:, [joints.index("left_elbow_joint"), joints.index("right_elbow_joint")]] = 1.2  # forearms forward, hands in the hips
    m = _on_floor(fk, joints, dof)
    assert deepest(m).min() > 0.04  # ~5 cm: the hand meshes count (the G1 model's own hands collide with nothing)
    out, info = separate_self_collisions(m)
    assert deepest(out).max() < 0.0155 and info["frames_deeper_than_target"] == {"before": T, "after": 0}
    moved = np.flatnonzero(np.abs(out.dof_pos - m.dof_pos).max(0) > 1e-9)
    assert set(moved) <= set(arms) and not any("wrist" in joints[i] for i in moved)
    assert np.array_equal(out.root_pos, m.root_pos) and np.array_equal(out.root_quat, m.root_quat)
    assert info["joint_change_deg"]["max"] <= 25.0 + 1e-6

    # knees pressed together (hips adducted 0.25 rad), arms held out of the way
    dof = _knees_bent(joints, T)
    for s, sign in (("left", -1), ("right", 1)):
        dof[:, joints.index(f"{s}_hip_roll_joint")] = sign * 0.25
        dof[:, joints.index(f"{s}_shoulder_roll_joint")] = -sign * 0.3
    both = _on_floor(fk, joints, dof)
    same, info = separate_self_collisions(both)  # both feet standing: no leg may move
    assert np.array_equal(same.dof_pos, both.dof_pos) and info["unresolved_pairs"]["left_knee_link / right_knee_link"] == T
    t = np.arange(T) / 30.0
    dof[:, joints.index("right_hip_pitch_joint")] = -0.6 + 0.25 * np.sin(2 * np.pi * t)  # right leg swinging
    dof[:, joints.index("right_knee_joint")] = 1.2
    dof[:, joints.index("right_ankle_pitch_joint")] = -0.6
    swing = _on_floor(fk, joints, dof)
    out, info = separate_self_collisions(swing)
    deep = info["frames_deeper_than_target"]
    assert deep["after"] < deep["before"] / 2 and info["frames_made_deeper"] == 0
    # whatever is left is reported, in frames
    assert max(info["unresolved_pairs"].values(), default=0) <= deep["after"] and info["joint_change_deg"]["max"] <= 10.0 + 1e-6
    moved = {joints[i] for i in np.flatnonzero(np.abs(out.dof_pos - swing.dof_pos).max(0) > 1e-9)}
    assert moved <= {"right_hip_roll_joint", "right_hip_yaw_joint"} and moved
    assert np.abs(fk.run(out)["foot"][:, 0] - fk.run(swing)["foot"][:, 0]).max() < 1e-9  # the standing foot stays


def test_foot_flat_leaves_moving_feet_alone():
    _need_retargeting()
    from retlens.retarget import flatten_stance_feet

    fk = analysis.FootKinematics("unitree_g1")
    joints = g1_motion(seconds=1.0, fps=30.0).joint_names
    lp = joints.index("left_ankle_pitch_joint")
    # both feet toe-up 10 deg: still for 0.5 s, then sliding at 1 m/s
    T = 45
    dof = _knees_bent(joints, T)
    dof[:, [lp, joints.index("right_ankle_pitch_joint")]] += np.radians(-10.0)
    m = _on_floor(fk, joints, dof, x=np.concatenate([np.zeros(15), np.linspace(0, 1.0, 31)[1:]]))
    out, info = flatten_stance_feet(m)
    assert info["stance_pct"] == {"left": pytest.approx(100 * 15 / T, abs=0.1), "right": pytest.approx(100 * 15 / T, abs=0.1)}
    # moving: untouched once the stance's smoothed fade-out is over (0.13 s), barely before
    assert np.array_equal(out.dof_pos[19:], m.dof_pos[19:]) and np.array_equal(out.root_pos[19:], m.root_pos[19:])
    assert np.abs(out.dof_pos[15:] - m.dof_pos[15:]).max() < np.radians(1.0)
    r0, r1 = fk.run(m), fk.run(out)
    assert np.all(r1["flat"][:11] - r1["sole"][:11] < 4e-3)  # standing: flat...
    assert np.abs(r1["sole"][:11] - r0["sole"][:11]).max() < 1e-3  # ...on the floor, heels not lifted
    # fading out over the last 0.15 s of the stance, no jump into the slide
    pitch = np.degrees(out.dof_pos[:, lp])
    assert np.all(np.diff(pitch[10:16]) < -0.5) and np.abs(np.diff(pitch)).max() <= 2.0
    assert np.abs(np.diff(out.root_pos[:, 2])).max() < 0.004


FBX_02_01 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "cmu_fbx", "02_01.fbx")


@pytest.mark.skipif(not os.path.isfile(FBX_02_01), reason="needs data/raw/cmu_fbx (tools/fetch_samples.py cmu_fbx)")
def test_swing_clearance_on_fbx_walk():
    """The HF FBX retarget of 02_01 drags its toes at toe-off (mid-swing minimum below the floor level)."""
    _need_retargeting()
    from retlens.compare import load_item
    from retlens.retarget import ensure_swing_clearance
    from retlens.settings import find_blender

    if not find_blender().path:
        pytest.skip("needs Blender 4.5")
    m = load_item(FBX_02_01, smooth=6.0, log=lambda *_: None).robot  # smoothed, no swing lift (cached)
    out, info = ensure_swing_clearance(m, clearance=0.02)
    assert info["fast_foot_min_clearance_cm"]["before"] < 0.0 < 1.0 <= info["fast_foot_min_clearance_cm"]["after"]
    fk = analysis.FootKinematics("unitree_g1")
    before, after = analysis.foot_metrics(m, fk), analysis.foot_metrics(out, fk)
    assert after["swing_low_pct"] < before["swing_low_pct"] / 1.5
    assert after["penetration_pct"] <= before["penetration_pct"] and after["planted_slip_pct"] <= before["planted_slip_pct"]
    assert info["leg_joint_change_deg"]["rmse"] < 3.0 and info["leg_joint_change_deg"]["max"] <= 20.0 + 1e-6
