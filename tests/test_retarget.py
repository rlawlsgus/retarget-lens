import os
import pickle
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens.io import load_motion  # noqa: E402
from retlens.io.bvh import bvh_rest_pose, load_bvh  # noqa: E402
from retlens.io.robot import G1_29DOF_JOINTS, load_gmr_pkl  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402
from retlens.qc import check_robot  # noqa: E402
from retlens.retarget import detect_format, qpos_to_motion, save_gmr_pkl, smooth_motion  # noqa: E402
from retlens.rotations import axis_rotation, quat_to_matrix  # noqa: E402
from retlens.synthetic import g1_motion, walking_bvh_text  # noqa: E402

NPZ_KEYS = {"fps", "joint_names", "root_pos", "root_quat_wxyz", "dof_pos"}
LAFAN1_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "lafan1_bvh")


def _need_retargeting():
    """Skip without mink / mujoco / the G1 model (GMR's solver itself is vendored in retlens/gmr)."""
    from retlens.retarget import unavailable

    why = unavailable()
    if why:
        pytest.skip(why)


def _qpos(n=5, yaw=np.pi / 2):
    """MuJoCo-style rows: root xyz, root quat wxyz (yaw about z), 29 joints."""
    q = np.zeros((n, 7 + 29))
    q[:, 0] = np.arange(n) * 0.1
    q[:, 2] = 0.79
    q[:, 3:7] = [np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)]
    q[:, 7:] = np.linspace(-0.5, 0.5, 29)
    return q


def test_qpos_to_project_npz(tmp_path):
    q = _qpos()
    m = qpos_to_motion(q, G1_29DOF_JOINTS, 30.0, "clip")
    p = tmp_path / "clip_g1.npz"
    m.save_npz(str(p))
    with np.load(p, allow_pickle=False) as d:
        assert set(d.files) == NPZ_KEYS
        assert d["root_pos"].shape == (5, 3) and d["root_quat_wxyz"].shape == (5, 4)
        assert d["dof_pos"].shape == (5, 29) and d["dof_pos"].dtype == np.float32
        assert list(d["joint_names"]) == G1_29DOF_JOINTS and float(d["fps"]) == 30.0
        # qpos quaternions are already wxyz: stored unchanged (w first)
        assert np.allclose(d["root_quat_wxyz"], q[:, 3:7], atol=1e-6)
    back = load_motion(str(p))
    assert isinstance(back, RobotMotion) and np.allclose(back.dof_pos, q[:, 7:], atol=1e-6)
    with pytest.raises(ValueError):
        qpos_to_motion(q[:, :-1], G1_29DOF_JOINTS, 30.0, "bad")


def test_gmr_pkl_is_xyzw(tmp_path):
    m = qpos_to_motion(_qpos(), G1_29DOF_JOINTS, 30.0, "clip")
    p = tmp_path / "clip.pkl"
    save_gmr_pkl(m, str(p))
    with open(p, "rb") as f:
        raw = pickle.load(f)
    assert np.allclose(raw["root_rot"], m.root_quat[:, [1, 2, 3, 0]])  # GMR layout: xyzw
    back = load_gmr_pkl(str(p))
    assert np.allclose(back.root_quat, m.root_quat) and back.joint_names == G1_29DOF_JOINTS


def test_smooth_motion(tmp_path):
    clean = g1_motion(seconds=4.0, fps=30.0)  # constant root orientation, elbows held at 0.9 rad
    rng = np.random.default_rng(0)
    noisy = RobotMotion(clean.name, clean.joint_names, clean.root_pos + rng.normal(0, 0.005, clean.root_pos.shape),
                        clean.root_quat.copy(), clean.dof_pos + rng.normal(0, 0.03, clean.dof_pos.shape), clean.fps)
    noisy.root_quat[1::2] *= -1  # same rotations, alternating quaternion sign
    elbows = [G1_29DOF_JOINTS.index(n) for n in ("left_elbow_joint", "right_elbow_joint")]
    lo, hi = np.full(29, -np.inf), np.full(29, np.inf)
    hi[elbows] = 0.9
    s = smooth_motion(noisy, 6.0, limits=(lo, hi))

    def acc(q):
        return np.abs(np.diff(q, 2, axis=0)).mean()

    def rms(a, b):
        return np.sqrt(((a - b) ** 2).mean())

    assert acc(s.dof_pos) < 0.3 * acc(noisy.dof_pos)
    # back towards the clean signal (white noise keeps ~40 % of its power below 6 Hz at 30 fps)
    assert rms(s.dof_pos, clean.dof_pos) < 0.75 * rms(noisy.dof_pos, clean.dof_pos)
    assert s.dof_pos[:, elbows].max() <= 0.9  # clipped into the joint range
    assert np.allclose(quat_to_matrix(s.root_quat), quat_to_matrix(clean.root_quat), atol=1e-6)  # sign flips undone
    assert s.dof_pos.shape == clean.dof_pos.shape and s.joint_names == clean.joint_names and s.fps == 30.0
    assert s.meta["smoothing"]["cutoff_hz"] == 6.0
    p = tmp_path / "s.npz"
    s.save_npz(str(p))
    with np.load(p, allow_pickle=False) as d:
        assert set(d.files) == NPZ_KEYS
    assert smooth_motion(noisy, 0.0) is noisy
    short = RobotMotion("s", clean.joint_names, clean.root_pos[:3], clean.root_quat[:3], clean.dof_pos[:3], 30.0)
    assert smooth_motion(short, 6.0) is short  # too short to filter: returned as is
    with pytest.raises(ValueError):
        smooth_motion(noisy, 15.0)  # Nyquist at 30 fps


def test_bvh_rotations_match_positions(tmp_path):
    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=1.0, fps=30))
    m = load_bvh(str(p), with_rotations=True)
    assert m.rotations.shape == m.positions.shape[:2] + (3, 3)
    assert np.allclose(m.rotations @ np.swapaxes(m.rotations, -1, -2), np.eye(3), atol=1e-9)
    # child = parent + R_parent @ offset: frames keep the file's own axes (offset in file
    # axes, metres), only the world side is Z-up
    i, j = m.joint_names.index("LeftUpLeg"), m.joint_names.index("LeftLeg")
    off = np.array([0, -0.42, 0])
    assert np.allclose(m.positions[:, j], m.positions[:, i] + m.rotations[:, i] @ off, atol=1e-9)
    names, rest_p, rest_r = bvh_rest_pose(str(p))
    assert names == m.joint_names and np.allclose(rest_r, axis_rotation("x", np.pi / 2))  # Y-up -> Z-up only
    a = names.index("LeftHand")
    assert rest_p[a, 0] > 0.5 and abs(rest_p[a, 2] - rest_p[names.index("LeftArm"), 2]) < 1e-9  # T-pose arm


def _cmu_like_bvh(frames):
    joints = ["Hips", "LHipJoint", "RHipJoint", "LowerBack"]
    lines = ["HIERARCHY", "ROOT Hips", "{", "  OFFSET 0 0 0",
             "  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation"]
    for name in joints[1:]:
        lines += [f"  JOINT {name}", "  {", "    OFFSET 0 1 0", "    CHANNELS 3 Zrotation Yrotation Xrotation",
                  "    End Site", "    {", "      OFFSET 0 1 0", "    }", "  }"]
    lines += ["}", "MOTION", f"Frames: {len(frames)}", "Frame Time: .0083333"]
    return "\n".join(lines + [" ".join(map(str, f)) for f in frames]) + "\n"


def test_cgspeed_tpose_frame_is_dropped(tmp_path):
    tpose = [0, 17, 0] + [0] * 12
    moving = [0, 17, 0] + [5, -80, 3, 10, 2, 1, -9, 4, 2, 7, 1, 3]
    p = tmp_path / "01_01.bvh"
    p.write_text(_cmu_like_bvh([tpose, moving, moving]))
    m = load_bvh(str(p))
    assert m.num_frames == 2 and m.meta["dropped_frames"] == 1 and m.meta["cgspeed_tpose_frame0"]
    assert load_bvh(str(p), drop_tpose=False).num_frames == 3
    q = tmp_path / "plain.bvh"  # no T-pose in frame 0: nothing dropped
    q.write_text(_cmu_like_bvh([moving, moving]))
    assert load_bvh(str(q)).num_frames == 2


def test_cmu_60hz_trials_get_their_true_rate(tmp_path):
    from retlens.io.bvh import cmu_capture_fps

    assert cmu_capture_fps("143_11") == (60.0, "AMASS / C3D header")
    assert cmu_capture_fps("02_01") == (None, "")  # 120 Hz subject
    assert cmu_capture_fps("walk1_subject1") == (None, "")
    tpose = [0, 17, 0] + [0] * 12
    moving = [0, 17, 0] + [5, -80, 3, 10, 2, 1, -9, 4, 2, 7, 1, 3]
    p = tmp_path / "143_11.bvh"  # cgspeed signature + a 60 Hz CMU trial name
    p.write_text(_cmu_like_bvh([tpose, moving, moving]))
    m = load_bvh(str(p))
    assert m.fps == 60.0 and m.meta["file_fps"] == pytest.approx(120.0, rel=1e-3) and "60" in m.meta["fps_note"]
    assert load_bvh(str(p), fps=100.0).fps == 100.0
    q = tmp_path / "143_11_copy.bvh"  # same content, not a CMU trial name: the file's rate stands
    q.write_text(_cmu_like_bvh([tpose, moving, moving]))
    assert load_bvh(str(q)).fps == pytest.approx(120.0, rel=1e-3)


def test_smpl_joint_names_map_to_tpose_bodies():
    from retlens.io.smpl import BODY_JOINTS
    from retlens.retarget import _resolve_bvh_bodies

    parents = np.array([-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19])  # SMPL body tree
    idx = _resolve_bvh_bodies(BODY_JOINTS, parents)
    name = {k: BODY_JOINTS[v] for k, v in idx.items()}
    assert name["Hips"] == "pelvis" and name["Spine2"] == "spine3"  # chest = parent of the collar
    assert name["LeftUpLeg"] == "left_hip" and name["RightLeg"] == "right_knee" and name["LeftFoot"] == "left_ankle"
    assert name["RightArm"] == "right_shoulder" and name["LeftForeArm"] == "left_elbow" and name["RightHand"] == "right_wrist"


def test_bend_axes_come_from_the_clip():
    """The human elbow axes the T-pose config twists the robot's arms to: found in the upper
    arm's own frame however it turns, carried into the reference pose. An arm the clip hardly
    bends, or bends about a wandering axis, gives none."""
    from scipy.spatial.transform import Rotation

    from retlens.retarget import TPOSE_BODIES, HumanClip, _human_bend_axes
    from retlens.rotations import matrix_to_quat

    T = 60
    hinge = np.array([0.0, np.sin(0.6), np.cos(0.6)])  # across the upper arm (its x axis), in its frame
    upper = Rotation.random(T, random_state=1).as_matrix()  # the upper arm turning about freely
    wander = np.random.default_rng(2).uniform(0, 2 * np.pi, T)
    ref_R = Rotation.from_euler("zx", [30, 80], degrees=True).as_matrix()

    def clip(left_bend, right_axes):
        frames = [{b: [np.zeros(3), np.array([1.0, 0.0, 0.0, 0.0])] for b in TPOSE_BODIES} for _ in range(T)]
        for side, axes, bend in (("Left", np.tile(hinge, (T, 1)), left_bend), ("Right", right_axes, np.full(T, 60.0))):
            for t in range(T):
                pb = upper[t] @ [0.3, 0.0, 0.0]
                fore = Rotation.from_rotvec(axes[t] * np.radians(bend[t])).as_matrix() @ [0.25, 0.0, 0.0]
                frames[t][f"{side}Arm"] = [np.zeros(3), matrix_to_quat(upper[t])]
                frames[t][f"{side}ForeArm"][0] = pb
                frames[t][f"{side}Hand"][0] = pb + upper[t] @ fore
        ref = {f"{s}Arm": (np.zeros(3), ref_R) for s in ("Left", "Right")}
        return HumanClip(frames=frames, fps=30.0, fmt="tpose", info={"_ref_pose": ref})

    found = _human_bend_axes("unitree_g1", clip(np.linspace(0, 110, T), np.stack([0 * wander, np.sin(wander),
                                                                                    np.cos(wander)], 1)))
    axis, info = found["left_shoulder_yaw_joint"]
    assert np.degrees(np.arccos(np.clip(axis @ (ref_R @ hinge), -1, 1))) < 0.5 and info["consistency"] > 0.99
    assert found["right_shoulder_yaw_joint"][0] is None and found["right_shoulder_yaw_joint"][1]["consistency"] < 0.7
    straight = _human_bend_axes("unitree_g1", clip(np.linspace(0, 10, T), np.tile(hinge, (T, 1))))
    assert straight["left_shoulder_yaw_joint"][0] is None and straight["left_shoulder_yaw_joint"][1]["bent_frames"] < 10
    assert straight["right_shoulder_yaw_joint"][0] is not None


def test_feet_level_as_the_clip_stands_not_as_the_reference():
    """The T-pose config's robot foot is flat where the clip's feet stand flat: a reference foot
    10 deg off how the person stands (CMU 143's T-pose feet), or tilted another 15 deg, makes no
    difference. Feet that never stand still keep the reference."""
    from scipy.spatial.transform import Rotation

    from retlens.retarget import HumanClip, _canonical_feet
    from retlens.rotations import matrix_to_quat

    T, up = 60, np.array([0.0, 0.0, 1.0])
    base = Rotation.from_euler("xyz", [90, 0, 90], degrees=True).as_matrix()  # some joint axis convention
    stand = Rotation.from_euler("y", 10, degrees=True).as_matrix() @ base  # the feet as they stand in the clip
    ref = {"Hips": (np.array([0.0, 0.0, 0.95]), np.eye(3)),
           "LeftUpLeg": (np.array([0.0, 0.1, 0.9]), np.eye(3)), "RightUpLeg": (np.array([0.0, -0.1, 0.9]), np.eye(3)),
           "LeftFoot": (np.array([0.0, 0.1, 0.08]), base), "RightFoot": (np.array([0.0, -0.1, 0.08]), base)}
    ankles = np.tile([ref["LeftFoot"][0], ref["RightFoot"][0]], (T, 1, 1))
    frames = [{f"{s}FootMod": [ankles[t, k], matrix_to_quat(stand)] for k, s in enumerate(("Left", "Right"))}
              for t in range(T)]
    clip = HumanClip(frames=frames, fps=30.0, fmt="tpose", info={"_ref_pose": ref, "_feet": ankles,
                                                                 "_hips_z": np.full(T, 0.95)})
    feet, report = _canonical_feet(clip)
    for s in ("Left", "Right"):
        assert report[s]["used"] == "stance" and report[s]["stance_frames"] == T
        assert report[s]["reference_vs_stance_deg"]["total"] == pytest.approx(10.0, abs=0.01)
        # the robot foot's up axis when standing as in the clip (GMR target: R_human @ R_ref'^T @ level robot foot)
        assert np.allclose(stand @ feet[f"{s}Foot"].T @ up, up, atol=1e-9)
        assert np.allclose(feet[f"{s}Foot"] @ [1.0, 0.0, 0.0], base @ [1.0, 0.0, 0.0], atol=0.2)  # a tilt, not a turn
    clip.info["_ref_pose"] = {**ref, "LeftFoot": (ref["LeftFoot"][0],
                                                  Rotation.from_euler("x", 15, degrees=True).as_matrix() @ base)}
    feet2, _ = _canonical_feet(clip)
    assert np.allclose(stand @ feet2["LeftFoot"].T @ up, up, atol=1e-9)

    clip.info["_ref_pose"] = ref
    clip.info["_feet"] = ankles + np.arange(T)[:, None, None] * np.array([1.0 / 30.0, 0.0, 0.0])  # 1 m/s, never still
    feet3, report = _canonical_feet(clip)
    assert report["Left"]["used"].startswith("reference") and np.array_equal(feet3["LeftFoot"], base)

    # standing 1 s each on the heel, the outer edge and the inner edge: no one flat stance -> the reference
    T = 90
    tilts = [Rotation.from_euler(ax, d, degrees=True).as_matrix() @ base for ax, d in (("y", -20), ("x", 20), ("x", -20))]
    ankles = np.tile([ref["LeftFoot"][0], ref["RightFoot"][0]], (T, 1, 1))
    frames = [{f"{s}FootMod": [ankles[t, k], matrix_to_quat(tilts[t // 30])] for k, s in enumerate(("Left", "Right"))}
              for t in range(T)]
    clip = HumanClip(frames=frames, fps=30.0, fmt="tpose", info={"_ref_pose": ref, "_feet": ankles,
                                                                 "_hips_z": np.full(T, 0.95)})
    feet4, report = _canonical_feet(clip)
    assert report["Left"]["used"] == "reference (stance frames disagree)" and np.array_equal(feet4["LeftFoot"], base)

    # on tiptoe (ankles 14 cm up) for most of the clip after a little flat standing: not taken for flat
    T = 90
    lift = np.where(np.arange(T) < 20, 0.0, 0.14)
    ankles = np.tile([ref["LeftFoot"][0], ref["RightFoot"][0]], (T, 1, 1)) + lift[:, None, None] * up
    toe = Rotation.from_euler("y", 50, degrees=True).as_matrix() @ stand  # heel up 50 deg
    frames = [{f"{s}FootMod": [ankles[t, k], matrix_to_quat(stand if t < 20 else toe)]
               for k, s in enumerate(("Left", "Right"))} for t in range(T)]
    clip = HumanClip(frames=frames, fps=30.0, fmt="tpose", info={"_ref_pose": ref, "_feet": ankles,
                                                                 "_hips_z": 0.95 + lift})
    feet5, report = _canonical_feet(clip)
    assert report["Left"]["stance_frames"] < 25 and np.allclose(stand @ feet5["LeftFoot"].T @ up, up, atol=1e-9)


def test_tpose_config_levels_the_robot_foot_as_the_clip_stands(tmp_path):
    """End to end through derive_tpose_config: a reference foot 10 deg off how the clip's foot
    stands still gives a level GMR foot target on those frames."""
    _need_retargeting()
    from scipy.spatial.transform import Rotation

    from retlens.retarget import derive_tpose_config, load_bvh_tpose

    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=1.0, fps=30))
    clip = load_bvh_tpose(str(p), fps=30.0)
    T = 30  # standing still in frame 0's pose for 1 s
    clip.frames = [dict(clip.frames[0]) for _ in range(T)]
    clip.info["_feet"] = np.repeat(clip.info["_feet"][:1], T, 0)
    clip.info["_hips_z"] = np.repeat(clip.info["_hips_z"][:1], T, 0)
    pos, R = clip.info["_ref_pose"]["RightFoot"]
    clip.info["_ref_pose"] = {**clip.info["_ref_pose"],
                              "RightFoot": (pos, Rotation.from_euler("y", 10, degrees=True).as_matrix() @ R)}
    cfg, _, info = derive_tpose_config("unitree_g1", clip)
    assert info["foot_reference"]["Right"]["used"] == "stance"
    assert info["foot_reference"]["Right"]["reference_vs_stance_deg"]["total"] == pytest.approx(10.0, abs=0.5)
    off = next(e[4] for e in cfg["ik_match_table1"].values() if e[0] == "RightFootMod")
    target = quat_to_matrix(np.asarray(clip.frames[0]["RightFootMod"][1])) @ quat_to_matrix(np.asarray(off))
    assert np.degrees(np.arccos(np.clip(target[2, 2], -1, 1))) < 1.0  # level (10 deg off without the levelling)


CMU_02_03 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "cmu_bvh", "02_03.bvh")


@pytest.mark.skipif(not os.path.isfile(CMU_02_03), reason="needs data/raw/cmu_bvh (tools/fetch_samples.py cmu)")
def test_cmu_elbows_bend_like_the_human():
    """CMU jog 02_03: with the twist set from the clip's own elbow bends, the robot's forearms
    point where the human's do (they were 39 deg off: elbows bending in a plane turned 38 deg)."""
    _need_retargeting()
    from retlens import retarget_quality
    from retlens.retarget import retarget_file, robot_model

    m, info = retarget_file(CMU_02_03, fps=30.0, smooth_hz=6.0, log=None)
    residual = info["robot_tpose"]["segment_residual_deg"]
    assert residual["left_shoulder_yaw_joint bend axis"] < 2 and residual["right_shoulder_yaw_joint bend axis"] < 2
    assert all(v["consistency"] > 0.9 for v in info["bend_axes"].values())
    seg = retarget_quality.measure(load_bvh(CMU_02_03), m, "unitree_g1", robot_model("unitree_g1"))["_segments_deg"]
    assert seg["왼 아래팔"] < 15 and seg["오른 아래팔"] < 15


AMASS_02_01 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "amass_cmu_smplx", "CMU",
                           "02", "02_01_stageii.npz")
SMPLX_MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")


@pytest.mark.skipif(not (os.path.isfile(AMASS_02_01) and os.path.isfile(os.path.join(SMPLX_MODELS, "smplx",
                                                                                     "SMPLX_NEUTRAL.npz"))),
                    reason="needs licence-gated AMASS CMU 02_01 and the SMPL-X body model")
def test_retarget_amass_smplx_matches_bvh_time_base():
    """SMPL-X through the derived T-pose config: G1 npz at exactly 30 fps, same length as the BVH of the clip."""
    _need_retargeting()
    from retlens.retarget import retarget_file

    m, info = retarget_file(AMASS_02_01, fps=30.0, smooth_hz=6.0, smpl_model_dir=SMPLX_MODELS, log=None)
    assert info["source_format"] == "smplx" and m.fps == 30.0 and m.num_frames == 86  # 343 frames @ 120 Hz
    assert m.joint_names == G1_29DOF_JOINTS and np.all(np.isfinite(m.dof_pos))
    assert info["ik_position_residual"]["feet"]["mean_cm"] < 5.0
    assert 0.6 < np.median(m.root_pos[:, 2]) < 0.85


def test_detect_format(tmp_path):
    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=0.5, fps=30))
    assert detect_format(str(p)) == "tpose"
    lafan = tmp_path / "lafan.bvh"
    lafan.write_text(walking_bvh_text(seconds=0.5, fps=30).replace("Spine1", "Spine2"))
    assert detect_format(str(lafan)) == "lafan1"
    smplx = tmp_path / "clip.npz"
    np.savez(smplx, pose_body=np.zeros((2, 63)), root_orient=np.zeros((2, 3)), trans=np.zeros((2, 3)))
    assert detect_format(str(smplx)) == "smplx"


def test_retarget_bvh_to_g1(tmp_path):
    """End to end through GMR: synthetic T-pose walker (faces and walks -Y) -> G1 npz."""
    _need_retargeting()
    from retlens.retarget import retarget_file

    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=2.0, fps=60))
    m, info = retarget_file(str(p), robot="unitree_g1", fps=30.0, log=None)
    assert m.joint_names == G1_29DOF_JOINTS and m.fps == 30.0
    assert m.dof_pos.shape == (60, 29) and m.root_pos.shape == (60, 3) and m.root_quat.shape == (60, 4)
    assert np.all(np.isfinite(m.dof_pos)) and np.allclose(np.linalg.norm(m.root_quat, axis=1), 1.0)
    assert info["source_format"] == "tpose" and info["reference"] == "rest pose"
    assert info["ik_position_residual"]["feet"]["mean_cm"] < 5.0
    # wxyz, not xyzw: the pelvis x axis points where the walker goes (-Y), and it moves that way
    fwd = quat_to_matrix(m.root_quat)[:, :, 0]
    assert np.all(fwd[:, 1] < -0.9)
    assert m.root_pos[-1, 1] - m.root_pos[0, 1] < -1.0
    assert 0.6 < np.median(m.root_pos[:, 2]) < 0.85  # G1 pelvis stands at ~0.79 m
    assert check_robot(m).status != "FAIL"
    out = tmp_path / "walk_g1.npz"
    m.save_npz(str(out))
    back = load_motion(str(out))
    assert np.allclose(quat_to_matrix(back.root_quat), quat_to_matrix(m.root_quat), atol=1e-5)
    assert info["smoothing"] is None


def test_retarget_smoothed(tmp_path):
    """--smooth 6: same output format, joints inside the MJCF limits, residuals before/after recorded."""
    _need_retargeting()
    from retlens.retarget import retarget_file, robot_joint_ranges, robot_model

    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=2.0, fps=60))
    m, info = retarget_file(str(p), robot="unitree_g1", fps=30.0, smooth_hz=6.0, log=None)
    assert m.joint_names == G1_29DOF_JOINTS and m.dof_pos.shape == (60, 29) and m.fps == 30.0
    lo, hi = robot_joint_ranges(robot_model("unitree_g1"))
    assert np.all(m.dof_pos >= lo - 1e-9) and np.all(m.dof_pos <= hi + 1e-9)
    assert np.allclose(np.linalg.norm(m.root_quat, axis=1), 1.0)
    sm = info["smoothing"]
    assert sm["cutoff_hz"] == 6.0 and "feet" in sm["ik_position_residual_before"]
    assert info["ik_position_residual"]["feet"]["mean_cm"] < 5.0


def test_vendored_gmr_needs_no_torch():
    """retlens/gmr: GMR's solver without GMR's package import (torch, MuJoCo viewer, imageio)."""
    import subprocess

    _need_retargeting()
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    code = ("import sys; from retlens import retarget; g = retarget._gmr(); "
            "print(g.GeneralMotionRetargeting.__module__, 'torch' in sys.modules, 'general_motion_retargeting' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.split() == ["retlens.gmr.motion_retarget", "False", "False"]


@pytest.mark.skipif(not os.path.isdir(LAFAN1_DIR), reason="needs data/raw/lafan1_bvh (internal LAFAN1 samples)")
def test_lafan1_frames_match_gmr_loader(tmp_path):
    """gmr_bvh_frames (retlens.io.bvh) gives what GMR's own LAFAN1 reader gives, to rounding."""
    gmr_lafan1 = pytest.importorskip("general_motion_retargeting.utils.lafan1")
    from retlens.retarget import gmr_bvh_frames

    with open(os.path.join(LAFAN1_DIR, "dance1_subject1.bvh"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith("Frames:"))
    clip = tmp_path / "dance_60.bvh"
    clip.write_text("\n".join(lines[:i] + ["Frames: 60", lines[i + 1]] + lines[i + 2:i + 62]) + "\n")
    ours, height, fps = gmr_bvh_frames(str(clip), "lafan1")
    theirs, their_height = gmr_lafan1.load_bvh_file(str(clip), format="lafan1")
    assert len(ours) == len(theirs) == 60 and height == their_height and fps == pytest.approx(30.0, abs=1e-3)
    for a, b in zip(ours, theirs):
        assert set(a) == set(b)
        for k in a:
            assert np.allclose(a[k][0], b[k][0], atol=1e-9), k
            q, r = np.asarray(a[k][1]), np.asarray(b[k][1])
            assert min(np.abs(q - r).max(), np.abs(q + r).max()) < 1e-9, k  # same rotation (q ~ -q)
