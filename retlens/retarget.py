"""Human mocap -> humanoid robot retargeting with GMR (General Motion Retargeting).

GMR (MIT, github.com/YanjieZe/GMR) solves per-frame differential IK with mink
on a MuJoCo robot model. Its solver and G1 configs are vendored in retlens/gmr
(without GMR's torch-importing package); the robot meshes come from
retlens.paths.robot_assets_dir() (``scripts/install_gmr.ps1`` puts them next to
the repository). mink, mujoco and scipy are imported inside functions, so
``retlens`` itself still imports without them (e.g. from Isaac Sim's Python).

Source formats:
  ``lafan1`` / ``nokov``  GMR's BVH frame convention (read with retlens.io.bvh) and IK configs.
  ``tpose``   Any BVH whose reference pose is a T-pose: CMU (cgspeed conversion,
              frame 0) and the usual Vicon / OptiTrack / Xsens / Rokoko exports
              (rest pose). GMR ships no config for these skeletons, so one is
              derived per clip: GMR's LAFAN1 task list and weights for the
              robot, with rotation offsets, per-body scales and ground height
              computed from the T-pose and the robot model.
  ``fbx``     FBX skeleton animation (read with Blender, retlens.io.fbx) with
              the same derived config: the armature's rest pose, or frame 0 when
              that is the inserted T-pose of a cgspeed CMU conversion.
  ``smplx``   AMASS SMPL / SMPL-X npz with the same derived config as ``tpose``
              (the body model's zero pose is a T-pose), so BVH and SMPL-X
              retargets of one clip are comparable. Needs the licence-gated
              body model files.
  ``smplx-gmr``  AMASS SMPL-X through GMR's own loader and smplx_to_<robot> config
              (it matches the robot toe link to the SMPL-X toe joint; on AMASS CMU
              the feet end up pitched 3-5 cm into the floor).

GMR's robot configuration is MuJoCo qpos: root xyz, root quaternion **wxyz**,
then joints in MJCF order. Only GMR's pkl files store the root as xyzw.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import pickle
import tempfile
import time
from dataclasses import dataclass, field

import numpy as np

from .motion import RobotMotion
from .rotations import matrix_to_quat, quat_normalize, quat_to_matrix

# File-name tag of each GMR robot in our outputs (<clip>_<tag>.npz).
ROBOT_TAGS = {"unitree_g1": "g1", "unitree_g1_with_hands": "g1_hands", "unitree_h1": "h1", "unitree_h1_2": "h1_2"}

# Human bodies of GMR's LAFAN1 configs. The T-pose path fills the same names.
TPOSE_BODIES = (
    "Hips", "Spine2",
    "LeftUpLeg", "LeftLeg", "LeftFootMod", "RightUpLeg", "RightLeg", "RightFootMod",
    "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
)

# Joint names of common BVH / FBX exporters (MotionBuilder / CMU cgspeed / Mixamo,
# Xsens MVN, OptiTrack Motive, Daz / Poser) and of SMPL / SMPL-X for each body.
# Right side is derived from the left. A namespace ("mixamorig:") or a prefix that
# every joint shares ("Skeleton1_") is ignored.
_LEFT_ALIASES = {
    "UpLeg": ("LeftUpLeg", "LeftUpperLeg", "LeftThigh", "LThigh", "lThigh", "left_hip"),
    "Leg": ("LeftLeg", "LeftLowerLeg", "LeftShin", "LShin", "lShin", "left_knee"),
    "Foot": ("LeftFoot", "LFoot", "lFoot", "left_ankle"),
    "Arm": ("LeftArm", "LeftUpperArm", "LUArm", "lShldr", "left_shoulder"),
    "ForeArm": ("LeftForeArm", "LeftLowerArm", "LFArm", "lForeArm", "left_elbow"),
    "Hand": ("LeftHand", "LHand", "lHand", "left_wrist"),
}


def _right_alias(name: str) -> str:
    if name.startswith("Left"):
        return "Right" + name[4:]
    if name.startswith("left_"):
        return "right_" + name[5:]
    if name.startswith("l"):
        return "r" + name[1:]  # Daz: lThigh -> rThigh
    return "R" + name[1:]  # OptiTrack: LThigh -> RThigh


def _strip_common_prefix(names: list[str]) -> list[str]:
    """Drop a namespace ("mixamorig:Hips") or a prefix every joint shares ("Skeleton1_Hips")."""
    for sep in (":", "_"):
        heads = {n.split(sep, 1)[0] for n in names}
        if len(heads) == 1 and all(sep in n for n in names):
            return [n.split(sep, 1)[1] for n in names]
    return list(names)
_HIPS_ALIASES = ("Hips", "Hip", "Pelvis", "hip", "pelvis")

# T-pose of the robot, matched to the human's reference frame one joint at a
# time: (joint to set, robot segment (from body, to body), human segment).
# Parents come first. Robots without an entry keep their zero pose.
_G1_TPOSE_CHAINS = [
    (f"{s}_{joint}", (f"{s}_{a}", f"{s}_{b}"), (f"{S}{c}", f"{S}{d}"))
    for s, S in (("left", "Left"), ("right", "Right"))
    for joint, a, b, c, d in (
        ("hip_roll_joint", "hip_roll_link", "knee_link", "UpLeg", "Leg"),
        ("knee_joint", "knee_link", "ankle_pitch_link", "Leg", "Foot"),
        ("shoulder_roll_joint", "shoulder_roll_link", "elbow_link", "Arm", "ForeArm"),
        ("elbow_joint", "elbow_link", "wrist_roll_link", "ForeArm", "Hand"),
    )
]
TPOSE_CHAINS = {"unitree_g1": _G1_TPOSE_CHAINS, "unitree_g1_with_hands": _G1_TPOSE_CHAINS}

# Then each limb is refined with its swing joints together: (joints, [(robot segment, human segment)]).
# Twist joints (hip / shoulder yaw) stay out: matching a few degrees of kink in the
# reference skeleton with them gave 75 deg twists that then skewed every frame.
_G1_TPOSE_LIMBS = [
    limb
    for s, S in (("left", "Left"), ("right", "Right"))
    for limb in (
        ([f"{s}_hip_pitch_joint", f"{s}_hip_roll_joint", f"{s}_knee_joint"],
         [((f"{s}_hip_roll_link", f"{s}_knee_link"), (f"{S}UpLeg", f"{S}Leg")),
          ((f"{s}_knee_link", f"{s}_ankle_pitch_link"), (f"{S}Leg", f"{S}Foot"))]),
        ([f"{s}_shoulder_pitch_joint", f"{s}_shoulder_roll_joint", f"{s}_elbow_joint"],
         [((f"{s}_shoulder_roll_link", f"{s}_elbow_link"), (f"{S}Arm", f"{S}ForeArm")),
          ((f"{s}_elbow_link", f"{s}_wrist_roll_link"), (f"{S}ForeArm", f"{S}Hand"))]),
    )
]
TPOSE_LIMBS = {"unitree_g1": _G1_TPOSE_LIMBS, "unitree_g1_with_hands": _G1_TPOSE_LIMBS}
# ...and the feet are levelled with the ankles: (ankle joints, foot body)
_G1_TPOSE_FEET = [([f"{s}_ankle_pitch_joint", f"{s}_ankle_roll_joint"], f"{s}_ankle_roll_link") for s in ("left", "right")]
TPOSE_FEET = {"unitree_g1": _G1_TPOSE_FEET, "unitree_g1_with_hands": _G1_TPOSE_FEET}
# ...and each elbow is turned to bend in the human's plane: the shoulder's twist joint puts the
# robot's bend axis on the human's. A straight arm in the reference pose shows no twist, so the
# human axis comes from the clip's own bends (_human_bend_axes); left at 0, CMU BVH elbows bent
# in a plane 38 deg off the human's and the hands went through the hips (retarget_quality found
# it). Knees are left out: their axes already matched in the reference (CMU BVH, 0.2 deg), and
# twisting the hips for SMPL-X pinned the ankle roll without bending the knees any truer.
# (twist joint, bend joint, robot (upper, middle, lower) bodies, human (upper, middle, lower)).
_G1_TPOSE_TWISTS = [
    (f"{s}_shoulder_yaw_joint", f"{s}_elbow_joint", (f"{s}_shoulder_roll_link", f"{s}_elbow_link", f"{s}_wrist_roll_link"),
     (f"{S}Arm", f"{S}ForeArm", f"{S}Hand"))
    for s, S in (("left", "Left"), ("right", "Right"))
]
TPOSE_TWISTS = {"unitree_g1": _G1_TPOSE_TWISTS, "unitree_g1_with_hands": _G1_TPOSE_TWISTS}
BEND_AXIS_MIN_DEG = 20.0  # frames bent at least this much show the bend axis
BEND_AXIS_MIN_FRAMES = 10
BEND_AXIS_CONSISTENCY = 0.7  # mean resultant length of the per-frame axes: lower = no steady hinge

# Robot body that sits at the human joint centre, where the IK body's origin does
# not (G1 hip_yaw_link is mid-thigh, shoulder_yaw_link mid-upper-arm). The
# difference becomes GMR's per-body position offset.
_G1_JOINT_CENTERS = {
    f"{S}{part}": f"{s}_{body}"
    for s, S in (("left", "Left"), ("right", "Right"))
    for part, body in (("UpLeg", "hip_roll_link"), ("Arm", "shoulder_roll_link"), ("Hand", "wrist_pitch_link"))
}
JOINT_CENTERS = {"unitree_g1": _G1_JOINT_CENTERS, "unitree_g1_with_hands": _G1_JOINT_CENTERS}


@contextlib.contextmanager
def _quiet():
    """GMR prints model tables and banners on import/construction; keep stdout clean."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _gmr():
    """GMR's IK solver and config tables, vendored in retlens.gmr (no torch); needs mink and mujoco."""
    try:
        with _quiet():
            from . import gmr
    except ImportError as e:
        raise ImportError(f"retargeting needs mink and mujoco ({e})") from e
    return gmr


def unavailable(robot: str = "unitree_g1") -> str | None:
    """Why retargeting cannot run here (mink / mujoco missing, no robot model), or None."""
    import importlib.util

    missing = [m for m in ("mink", "mujoco", "scipy") if importlib.util.find_spec(m) is None]
    if missing:
        return f"retargeting needs {', '.join(missing)}"
    xml = _gmr().ROBOT_XML_DICT.get(robot)
    if xml is None or not os.path.isfile(xml):
        return f"no robot model for {robot} ({xml}; scripts\\install_gmr.ps1 puts it next to the repository)"
    return None


def gmr_version() -> str:
    """'gmr@<commit>' of the vendored GMR code (retlens/gmr)."""
    from .gmr import GMR_COMMIT

    return "gmr@" + GMR_COMMIT[:12]


def robot_model(robot: str):
    import mujoco as mj

    return mj.MjModel.from_xml_path(str(_gmr().ROBOT_XML_DICT[robot]))


def robot_joint_names(model) -> list[str]:
    """Names of the non-free joints in qpos order (= GMR dof_pos columns)."""
    import mujoco as mj

    joints = [j for j in range(model.njnt) if model.jnt_type[j] != mj.mjtJoint.mjJNT_FREE]
    joints.sort(key=lambda j: model.jnt_qposadr[j])
    return [mj.mj_id2name(model, mj.mjtObj.mjOBJ_JOINT, j) for j in joints]


# --------------------------------------------------------------------------- output
def qpos_to_motion(qpos, joint_names, fps: float, name: str, source: str = "", meta=None) -> RobotMotion:
    """GMR/MuJoCo qpos rows (root xyz, root quat wxyz, joints) -> RobotMotion."""
    qpos = np.asarray(qpos, dtype=np.float64)
    if qpos.ndim != 2 or qpos.shape[1] != 7 + len(joint_names):
        raise ValueError(f"qpos shape {qpos.shape} does not match 7 + {len(joint_names)} joints")
    return RobotMotion(
        name=name,
        joint_names=list(joint_names),
        root_pos=qpos[:, :3].copy(),
        root_quat=quat_normalize(qpos[:, 3:7]),
        dof_pos=qpos[:, 7:].copy(),
        fps=float(fps),
        source=source,
        meta=dict(meta or {}),
    )


def save_gmr_pkl(motion: RobotMotion, path: str) -> None:
    """GMR's pkl layout (read by TWIST / GMT); root_rot is xyzw there."""
    with open(path, "wb") as f:
        pickle.dump({
            "fps": motion.fps,
            "root_pos": motion.root_pos,
            "root_rot": motion.root_quat[:, [1, 2, 3, 0]],
            "dof_pos": motion.dof_pos,
            "local_body_pos": None,
            "link_body_list": None,
        }, f)


# --------------------------------------------------------------------------- human input
@dataclass
class HumanClip:
    """Per-frame GMR human data: body name -> [position (3,), quaternion wxyz (4,)]."""

    frames: list
    fps: float
    fmt: str
    height_m: float | None = None
    info: dict = field(default_factory=dict)


def bvh_joint_names(path: str) -> list[str]:
    names = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            tok = line.split()
            if tok and tok[0].upper() in ("ROOT", "JOINT") and len(tok) > 1:
                names.append(tok[1])
            elif tok and tok[0].upper() == "MOTION":
                break
    return names


def detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npz":
        with np.load(path, allow_pickle=False) as d:
            keys = set(d.files)
        if "pose_body" in keys:
            return "smplx"
        raise ValueError(f"{path}: not an AMASS SMPL-X npz (no 'pose_body'; keys {sorted(keys)[:8]})")
    if ext == ".fbx":
        return "fbx"
    if ext != ".bvh":
        raise ValueError(f"unsupported input {path!r} (expected .bvh, .fbx or AMASS SMPL-X .npz)")
    names = set(bvh_joint_names(path))
    if {"LeftToe", "Spine2", "LeftUpLeg"} <= names and "LeftToeBase" not in names:
        return "lafan1"
    return "tpose"


def _resolve_bvh_bodies(names: list[str], parents: np.ndarray) -> dict[str, int]:
    """Our joint index for each body the T-pose config needs (+ the two feet)."""
    names = _strip_common_prefix(names)
    lookup = {n: i for i, n in enumerate(names)}
    idx = {}
    hips = next((lookup[a] for a in _HIPS_ALIASES if a in lookup), None)
    if hips is None:
        roots = [i for i, p in enumerate(parents) if p < 0]
        hips = roots[0]
    idx["Hips"] = hips
    for part, aliases in _LEFT_ALIASES.items():
        for side in ("Left", "Right"):
            cands = list(aliases) if side == "Left" else [_right_alias(a) for a in aliases]
            j = next((lookup[c] for c in cands if c in lookup), None)
            if j is None:
                raise ValueError(f"skeleton has no {side} {part} joint (tried {cands}); use --format or add an alias")
            idx[f"{side}{part}"] = j
    # chest = the spine joint the arm hangs from (skip a clavicle/shoulder joint)
    p = int(parents[idx["LeftArm"]])
    if any(k in names[p].lower() for k in ("shoulder", "clavicle", "collar")):
        p = int(parents[p])
    idx["Spine2"] = p
    return idx


def _resample(P: np.ndarray, R: np.ndarray, fps_in: float, fps_out: float | None):
    """Positions (T, J, 3) linearly, frames (T, J, 3, 3) by slerp."""
    T = len(P)
    if not fps_out or T < 2:
        return P, R, fps_in
    if abs(fps_in - fps_out) < 1e-3 * fps_in:  # same rate; BVH frame times are rounded (.0333333)
        return P, R, float(fps_out)
    ratio = fps_in / fps_out
    if ratio > 1 and abs(ratio - round(ratio)) < 1e-3:
        k = int(round(ratio))
        return P[::k], R[::k], float(fps_out)  # 120.0005 fps (rounded frame time) / 4 -> 30
    from scipy.spatial.transform import Rotation, Slerp

    t_in = np.arange(T) / fps_in
    t_out = np.arange(0.0, t_in[-1] + 1e-9, 1.0 / fps_out)
    P_out = np.empty((len(t_out),) + P.shape[1:])
    R_out = np.empty((len(t_out),) + R.shape[1:])
    for j in range(P.shape[1]):
        for c in range(3):
            P_out[:, j, c] = np.interp(t_out, t_in, P[:, j, c])
        R_out[:, j] = Slerp(t_in, Rotation.from_matrix(R[:, j]))(t_out).as_matrix()
    return P_out, R_out, fps_out


def load_bvh_tpose(path: str, up_axis: str = "y", ref: str | int = "auto", fps: float | None = 30.0) -> HumanClip:
    """BVH -> GMR human frames for the T-pose config, plus the reference pose.

    ref: "auto" (CMU cgspeed files: their inserted frame-0 T-pose, which is then
    dropped from the motion; anything else: the rest pose), "rest", or a frame
    index of the clip that shows a T-pose.
    """
    from .io.bvh import bvh_rest_pose, load_bvh

    m = load_bvh(path, up_axis=up_axis, with_rotations=True, drop_tpose=False)
    idx = _resolve_bvh_bodies(m.joint_names, m.parents)
    P, R = m.positions, m.rotations
    cgspeed = m.meta["cgspeed_tpose_frame0"]
    dropped = 0
    if ref == "auto":
        ref = 0 if cgspeed else "rest"
        dropped = 1 if cgspeed else 0
    if ref == "rest":
        _, ref_P, ref_R = bvh_rest_pose(path, up_axis=up_axis, scale=m.meta["unit_scale"])
    else:
        k = int(ref)
        ref_P, ref_R = P[k], R[k]
    end = m.joint_names.index("Head_end") if "Head_end" in m.joint_names else None
    height = None
    if end is not None:
        height = float(ref_P[end, 2] - min(ref_P[idx["LeftFoot"], 2], ref_P[idx["RightFoot"], 2]))
    info = {
        "reference": "rest pose" if ref == "rest" else f"frame {ref}",
        "dropped_leading_frames": dropped,
        "source_fps_note": m.meta.get("fps_note") or None,
        "unit_scale": m.meta["unit_scale"],
    }
    return _tpose_clip(m.joint_names, idx, P[dropped:], R[dropped:], m.fps, fps, ref_P, ref_R, "tpose", height, info)


def load_fbx_tpose(path: str, ref: str | int = "auto", fps: float | None = 30.0, take: str | None = None) -> HumanClip:
    """FBX -> GMR human frames for the T-pose config, plus the reference pose.

    ref: "auto" (frame 0 when it is the rest pose and the motion starts after it,
    as in cgspeed CMU conversions; it is then dropped; otherwise the armature's
    rest pose), "rest", or a frame index of the clip that shows a T-pose.
    """
    from .io.fbx import load_fbx

    m = load_fbx(path, with_rotations=True, drop_tpose=False, take=take)
    idx = _resolve_bvh_bodies(m.joint_names, m.parents)
    P, R = m.positions, m.rotations
    tpose0 = m.meta["tpose_frame0"]
    dropped = 0
    if ref == "auto":
        ref = 0 if tpose0 else "rest"
        dropped = 1 if tpose0 else 0
    ref_P, ref_R = m.meta["rest_pose"] if ref == "rest" else (P[int(ref)], R[int(ref)])
    info = {
        "reference": "rest pose" if ref == "rest" else f"frame {ref}",
        "dropped_leading_frames": dropped,
        "source_fps_note": m.meta.get("fps_note") or None,
        "unit_scale": m.meta["unit_scale"],
        "fbx_take": m.meta["take"],
        "fbx_reader": m.meta["reader"],
    }
    return _tpose_clip(m.joint_names, idx, P[dropped:], R[dropped:], m.fps, fps, ref_P, ref_R, "fbx", None, info)


def _tpose_clip(names, idx, P, R, fps_in, fps, ref_P, ref_R, fmt, height, info) -> HumanClip:
    """GMR human frames (TPOSE_BODIES) from world joint positions / frames + the reference pose."""
    P, R, fps_out = _resample(P, R, fps_in, fps)
    Q = matrix_to_quat(R)

    def body(name: str) -> str:  # FootMod -> Foot joint (in a T-pose skeleton the foot frame is usable as is)
        return name.replace("FootMod", "Foot")

    frames = [{b: [P[t, idx[body(b)]], Q[t, idx[body(b)]]] for b in TPOSE_BODIES} for t in range(len(P))]
    return HumanClip(
        frames=frames, fps=fps_out, fmt=fmt, height_m=height,
        info={
            **info,
            "source_fps": fps_in,
            "joint_map": {b: names[i] for b, i in idx.items()},
            "_ref_pose": {b: (ref_P[i], ref_R[i]) for b, i in idx.items()},
            "_hips_z": P[:, idx["Hips"], 2],
            "_feet": P[:, [idx["LeftFoot"], idx["RightFoot"]]],
        },
    )


def load_smplx_tpose(path: str, model_dir: str | None, fps: float | None = 30.0) -> HumanClip:
    """AMASS SMPL / SMPL-X npz -> GMR human frames for the T-pose config.

    The body model's zero pose is a T-pose, so the same per-clip derivation as for
    T-pose BVH applies (rotation offsets, scales, ground from that pose and the
    robot), which keeps BVH and SMPL-X retargets of a clip directly comparable.
    Joint positions and frames come from retlens.io.smpl (numpy FK of the body
    model; hands, face and the toe joints are not used).
    """
    from .io.smpl import load_amass_npz

    model_dir = model_dir or os.environ.get("SMPL_MODEL_DIR")
    if not model_dir:
        raise FileNotFoundError("SMPL-X retargeting needs the body model: pass --smpl-model-dir or set SMPL_MODEL_DIR")
    m = load_amass_npz(path, model_dir=model_dir, body_only=True, with_rotations=True)
    if m.fps <= 0:
        raise ValueError(f"{path}: no mocap frame rate in the file")
    idx = _resolve_bvh_bodies(m.joint_names, m.parents)
    ref_P, ref_R = m.meta["rest_pose"]
    info = {"reference": f"{m.meta['model_type']} zero pose ({m.meta['gender']})", "dropped_leading_frames": 0}
    return _tpose_clip(m.joint_names, idx, m.positions, m.rotations, m.fps, fps, ref_P, ref_R, "smplx", None, info)


def gmr_bvh_frames(path: str, fmt: str) -> tuple[list[dict], float, float]:
    """LAFAN1 / Nokov BVH as GMR's own loader returns it (utils/lafan1.load_bvh_file):
    {joint: [position (m, Z-up), world orientation wxyz]} per frame with the joint's axes as in
    the file, plus <Side>FootMod (the foot's position with the toe's orientation), the fixed
    human height 1.75 m and the file's frame rate. Read with retlens.io.bvh, which uses the
    same frame convention, instead of the LAFAN1 reader GMR bundles."""
    from .io.bvh import load_bvh

    toe = {"lafan1": "Toe", "nokov": "ToeBase"}.get(fmt)
    if toe is None:
        raise ValueError(f"Invalid format: {fmt}")
    m = load_bvh(path, scale=0.01, include_end_sites=False, with_rotations=True, drop_tpose=False)  # cm -> m like GMR
    q = matrix_to_quat(m.rotations)  # (T, J, 4) wxyz
    names = m.joint_names
    frames = []
    for f in range(m.num_frames):
        result = {n: [m.positions[f, j], q[f, j]] for j, n in enumerate(names)}
        for s in ("Left", "Right"):
            result[f"{s}FootMod"] = [result[f"{s}Foot"][0], result[f"{s}{toe}"][1]]
        frames.append(result)
    return frames, 1.75, float(m.meta["file_fps"])


def load_bvh_gmr(path: str, fmt: str, fps: float | None = 30.0) -> HumanClip:
    """LAFAN1 / Nokov BVH in GMR's convention (gmr_bvh_frames), nearest-frame resampling."""
    frames, height, src_fps = gmr_bvh_frames(path, fmt)
    if fps and abs(fps - src_fps) > 1e-3 * src_fps:
        n = int(len(frames) / src_fps * fps)
        frames = [frames[min(int(round(k * src_fps / fps)), len(frames) - 1)] for k in range(n)]
    elif not fps:
        fps = src_fps  # else: same rate up to the rounded frame time, keep the requested value
    return HumanClip(frames=frames, fps=fps, fmt=fmt, height_m=height, info={"source_fps": src_fps})


def load_smplx_gmr(path: str, model_dir: str | None, fps: float | None = 30.0) -> HumanClip:
    """AMASS SMPL-X npz through GMR's own loader (body model: <model_dir>/smplx/SMPLX_<GENDER>.npz).

    Development comparison only (``--format smplx-gmr``): it needs the GMR checkout's
    utils/smpl.py, the ``smplx`` package (MPI non-commercial licence) and torch, none of which
    the packaged program ships. The default SMPL-X path (``smplx``) uses retlens.io.smpl."""
    model_dir = model_dir or os.environ.get("SMPL_MODEL_DIR")
    if not model_dir or not os.path.isdir(os.path.join(model_dir, "smplx")):
        raise FileNotFoundError(
            "SMPL-X retargeting needs the SMPL-X body model (licence-gated, https://smpl-x.is.tue.mpg.de): "
            "pass --smpl-model-dir or set SMPL_MODEL_DIR to the folder holding smplx/SMPLX_NEUTRAL.npz")
    try:
        with _quiet():
            import smplx
            import torch
            from general_motion_retargeting.utils.smpl import get_smplx_data_offline_fast
    except ImportError as e:
        raise ImportError("--format smplx-gmr is a development path: it needs the GMR checkout "
                          "(scripts\\install_gmr.ps1), smplx and torch; use the default smplx format") from e

    data = dict(np.load(path, allow_pickle=True))
    gender = data.get("gender", "neutral")
    gender = gender.item() if hasattr(gender, "item") else gender
    gender = (gender.decode() if isinstance(gender, bytes) else str(gender)).lower()
    betas = np.asarray(data["betas"], dtype=np.float32).reshape(-1)
    # GMR's load_smplx_file builds the model with smplx's default 10 shape coefficients;
    # AMASS SMPL-X files carry 16, so build it to match the file (smplx caps it at what
    # the model file has).
    with _quiet():
        body_model = smplx.create(model_dir, "smplx", gender=gender, use_pca=False, num_betas=len(betas), ext="npz")
    nb = body_model.num_betas
    # Frame rate: GMR interpolates onto a grid that is not exactly tgt_fps and reports
    # a rate that differs from the sample spacing (02_01: 29.74 reported, 29.47 actual).
    # For integer ratios (AMASS 120 -> 30) take every k-th frame instead, like the BVH
    # path, so both retargets share the same time base.
    src_fps = float(np.asarray(data["mocap_frame_rate"]))
    n_src = len(data["pose_body"])
    ratio = src_fps / fps if fps else 1.0
    stride = int(round(ratio)) if ratio > 1 and abs(ratio - round(ratio)) < 1e-3 else 1
    for key in ("root_orient", "pose_body", "trans"):
        data[key] = np.asarray(data[key])[::stride]
    data["mocap_frame_rate"] = np.array(src_fps / stride)
    n = len(data["pose_body"])

    def tensor(x):
        return torch.tensor(np.asarray(x, dtype=np.float32))

    with torch.no_grad():
        output = body_model(
            betas=tensor(betas[:nb]).view(1, -1),
            global_orient=tensor(data["root_orient"]),
            body_pose=tensor(data["pose_body"]),
            transl=tensor(data["trans"]),
            left_hand_pose=torch.zeros(n, 45), right_hand_pose=torch.zeros(n, 45),
            jaw_pose=torch.zeros(n, 3), leye_pose=torch.zeros(n, 3), reye_pose=torch.zeros(n, 3),
            expression=torch.zeros(n, body_model.num_expression_coeffs),
            return_full_pose=True,
        )
        cur_fps = src_fps / stride
        interpolate = bool(fps) and fps < cur_fps * (1 - 1e-3)  # non-integer downsampling only
        with _quiet():
            frames, _ = get_smplx_data_offline_fast(data, body_model, output, tgt_fps=fps if interpolate else cur_fps)
    # GMR's interpolation grid is linspace(0, n - 1, n // int(src / tgt)): use its true spacing
    fps_out = (len(frames) - 1) / ((n - 1) / cur_fps) if interpolate and len(frames) > 1 else cur_fps
    height = 1.66 + 0.1 * float(betas[0])  # GMR's estimate, matched by its smplx IK config
    return HumanClip(frames=frames, fps=float(fps_out), fmt="smplx", height_m=height,
                     info={"source_fps": src_fps, "source_frames": n_src, "stride": stride, "gender": gender,
                           "num_betas_file": int(len(betas)), "num_betas_model": int(nb)})


# --------------------------------------------------------------------------- T-pose config
def _facing_frame(ref_pose: dict) -> np.ndarray:
    """World frame of the human's reference pose with robot axes: x fwd, y left, z up."""
    left = ref_pose["LeftUpLeg"][0] - ref_pose["RightUpLeg"][0]
    left[2] = 0.0
    left /= np.linalg.norm(left)
    up = np.array([0.0, 0.0, 1.0])
    return np.stack([np.cross(left, up), left, up], axis=1)


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    c = np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12)
    return float(np.arccos(np.clip(c, -1.0, 1.0)))


def _human_bend_axes(robot: str, clip: HumanClip) -> dict[str, tuple[np.ndarray | None, dict]]:
    """Bend axis of each elbow / knee (TPOSE_TWISTS) in the reference pose, world coordinates.

    For a hinge, upper x lower segment stays fixed in the upper segment's own frame, so the
    clip's bent frames (>= BEND_AXIS_MIN_DEG) give it: their axes in that frame, averaged
    weighted by sin(bend), then carried into the reference pose. {twist joint: (axis, info)};
    axis None when the clip hardly bends the limb or the axis wanders (no steady hinge)."""
    ref = clip.info["_ref_pose"]
    out = {}
    for twist, _, _, (a, b, c) in TPOSE_TWISTS.get(robot, []):
        key = [n + "Mod" if n.endswith("Foot") else n for n in (a, b, c)]  # a leg's: clip frames carry <Side>FootMod
        P = np.array([[fr[k][0] for k in key] for fr in clip.frames], dtype=np.float64)
        Ra = quat_to_matrix(np.array([fr[a][1] for fr in clip.frames], dtype=np.float64))
        u, f = P[:, 1] - P[:, 0], P[:, 2] - P[:, 1]
        n = np.cross(u, f)
        sin = np.linalg.norm(n, axis=1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(f, axis=1), 1e-12)
        bend = np.degrees(np.arctan2(sin, np.einsum("ij,ij->i", u, f) / np.maximum(
            np.linalg.norm(u, axis=1) * np.linalg.norm(f, axis=1), 1e-12)))
        bent = np.isfinite(bend) & (bend >= BEND_AXIS_MIN_DEG)
        info = {"bent_frames": int(bent.sum())}
        if bent.sum() < BEND_AXIS_MIN_FRAMES:
            out[twist] = (None, info)
            continue
        local = np.einsum("tji,tj->ti", Ra[bent], n[bent] / np.linalg.norm(n[bent], axis=1, keepdims=True))  # R^T n
        mean = (local * sin[bent, None]).sum(0) / sin[bent].sum()
        info["consistency"] = round(float(np.linalg.norm(mean)), 3)
        if info["consistency"] < BEND_AXIS_CONSISTENCY:
            out[twist] = (None, info)
            continue
        out[twist] = (ref[a][1] @ (mean / np.linalg.norm(mean)), info)
    return out


def _robot_bend_axis(model, data, q: np.ndarray, bend_joint: int, bodies: tuple[int, int, int]) -> np.ndarray:
    """The robot limb's bend axis (upper x lower segment) with the bend joint flexed 1 rad from
    q: towards the farther end of its range (elbows and knees bend much further than they
    overextend), so the axis has the human's sense."""
    import mujoco as mj

    adr = model.jnt_qposadr[bend_joint]
    lo, hi = model.jnt_range[bend_joint] if model.jnt_limited[bend_joint] else (-np.pi, np.pi)
    q0 = q[adr]
    q[adr] = np.clip(q0 + (1.0 if hi - q0 >= q0 - lo else -1.0), lo, hi)
    data.qpos[:] = q
    mj.mj_kinematics(model, data)
    x0, x1, x2 = (data.xpos[b].copy() for b in bodies)
    q[adr] = q0
    return np.cross(x1 - x0, x2 - x1)


def _robot_tpose(model, robot: str, ref_pose: dict, face: np.ndarray, bend_axes: dict | None = None):
    """Robot qpos (root at origin, identity) whose limbs point like the human's and whose
    elbows / knees bend about the human's axes (bend_axes: twist joint -> world axis)."""
    import mujoco as mj

    data = mj.MjData(model)
    q = model.qpos0.copy()
    q[:3], q[3:7] = 0.0, [1.0, 0.0, 0.0, 0.0]
    chosen = {}
    for joint, (rb0, rb1), (h0, h1) in TPOSE_CHAINS.get(robot, []):
        j = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, joint)
        b0 = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, rb0)
        b1 = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, rb1)
        target = face.T @ (ref_pose[h1][0] - ref_pose[h0][0])
        lo, hi = model.jnt_range[j] if model.jnt_limited[j] else (-np.pi, np.pi)
        best = (np.inf, 0.0)
        for v in np.linspace(lo, hi, 721):
            q[model.jnt_qposadr[j]] = v
            data.qpos[:] = q
            mj.mj_kinematics(model, data)
            best = min(best, (_angle(data.xpos[b1] - data.xpos[b0], target), v))
        q[model.jnt_qposadr[j]] = best[1]
        chosen[joint] = {"rad": round(float(best[1]), 4), "residual_deg": round(float(np.degrees(best[0])), 1)}

    # Twist each limb about itself so its bend axis matches the human's (the limb directions
    # stay: the twist joint turns about the upper segment). Limbs the clip hardly bends keep 0.
    twists = []
    for twist, bend, rbodies, _ in TPOSE_TWISTS.get(robot, []):
        axis = (bend_axes or {}).get(twist)
        if axis is None:
            continue
        jt = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, twist)
        jb = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, bend)
        bodies = tuple(mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, n) for n in rbodies)
        target = face.T @ axis
        lo, hi = model.jnt_range[jt] if model.jnt_limited[jt] else (-np.pi, np.pi)
        best = (np.inf, 0.0)
        for v in np.linspace(lo, hi, 721):
            q[model.jnt_qposadr[jt]] = v
            best = min(best, (_angle(_robot_bend_axis(model, data, q, jb, bodies), target), v))
        q[model.jnt_qposadr[jt]] = best[1]
        chosen[twist] = {"rad": round(float(best[1]), 4)}
        twists.append((twist, jb, bodies, target))

    # Refine each limb with all its joints at once: one axis per joint cannot follow a
    # limb that also points forward (SMPL-X zero pose: arms forward and down, knees
    # slightly bent). A small pull towards the 1-D solution keeps the free twist at 0,
    # unless the limb's bend axis is known: then its twist joint joins in and the axis is
    # matched too (on its own the twist cannot reach an axis tilted off the robot's limb).
    from scipy.optimize import minimize

    def body(name):
        return mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)

    refined = {}
    for joints, segments in TPOSE_LIMBS.get(robot, []):
        hinge = next(((t, jb, bodies, target) for t, jb, bodies, target in twists
                      if mj.mj_id2name(model, mj.mjtObj.mjOBJ_JOINT, jb) in joints), None)
        names = list(joints) + ([hinge[0]] if hinge else [])
        ids = [mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in names]
        adr = [model.jnt_qposadr[j] for j in ids]
        bounds = [tuple(model.jnt_range[j]) if model.jnt_limited[j] else (-np.pi, np.pi) for j in ids]
        segs = [(body(r0), body(r1), face.T @ (ref_pose[h1][0] - ref_pose[h0][0])) for (r0, r1), (h0, h1) in segments]
        x0 = q[adr].copy()

        def cost(x):
            q[adr] = x
            data.qpos[:] = q
            mj.mj_kinematics(model, data)
            c = 0.0
            for b0, b1, target in segs:
                v = data.xpos[b1] - data.xpos[b0]
                c += 1.0 - np.dot(v, target) / max(np.linalg.norm(v) * np.linalg.norm(target), 1e-12)
            if hinge:
                n = _robot_bend_axis(model, data, q, hinge[1], hinge[2])
                c += 1.0 - np.dot(n, hinge[3]) / max(np.linalg.norm(n) * np.linalg.norm(hinge[3]), 1e-12)
            return c + 0.02 * float(np.sum((x - x0) ** 2))

        res = minimize(cost, x0, method="L-BFGS-B", bounds=bounds)
        q[adr] = res.x
        cost(res.x)
        data.qpos[:] = q  # the bend-axis term left data at the flexed pose
        mj.mj_kinematics(model, data)
        for (r0, r1), (h0, h1) in segments:
            target = face.T @ (ref_pose[h1][0] - ref_pose[h0][0])
            refined[f"{r0}->{r1}"] = round(float(np.degrees(_angle(data.xpos[body(r1)] - data.xpos[body(r0)], target))), 1)
        for n, v in zip(names, res.x):
            chosen[n] = {"rad": round(float(v), 4)}

    # The reference skeletons stand flat-footed (cgspeed T-pose frame, SMPL-X zero pose),
    # so level the robot's feet with the ankles; otherwise the foot would copy the
    # shin's tilt into every frame's foot target.
    for joints, foot in TPOSE_FEET.get(robot, []):
        ids = [mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in joints]
        adr = [model.jnt_qposadr[j] for j in ids]
        bounds = [tuple(model.jnt_range[j]) if model.jnt_limited[j] else (-np.pi, np.pi) for j in ids]
        fb = body(foot)

        def tilt(x):
            q[adr] = x
            data.qpos[:] = q
            mj.mj_kinematics(model, data)
            return 1.0 - float(data.xmat[fb].reshape(3, 3)[2, 2])

        res = minimize(tilt, q[adr].copy(), method="L-BFGS-B", bounds=bounds)
        q[adr] = res.x
        refined[f"{foot} tilt"] = round(float(np.degrees(np.arccos(np.clip(1.0 - tilt(res.x), -1, 1)))), 1)
        for n, v in zip(joints, res.x):
            chosen[n] = {"rad": round(float(v), 4)}
    for twist, jb, bodies, target in twists:  # after the refinement moved the limbs a little
        refined[f"{twist} bend axis"] = round(float(np.degrees(_angle(_robot_bend_axis(model, data, q, jb, bodies), target))), 1)
    if refined:
        chosen["segment_residual_deg"] = refined
    data.qpos[:] = q
    mj.mj_kinematics(model, data)
    return data, chosen


def _sole_height(model, data, body: str) -> float:
    """Height of the body origin above its lowest collision geometry (ankle above sole)."""
    import mujoco as mj

    b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, body)
    lows = []
    for g in range(model.ngeom):
        if model.geom_bodyid[g] != b or (model.geom_contype[g] == 0 and model.geom_conaffinity[g] == 0):
            continue
        c, h = model.geom_aabb[g, :3], model.geom_aabb[g, 3:]
        corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * h + c
        lows.append(float((corners @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g])[:, 2].min()))
    return float(data.xpos[b][2] - min(lows)) if lows else 0.0


# Human feet standing flat (_canonical_feet): ankle slower than this, the foot's up direction
# turning slower than this (not rolling over heel or toe), ankle this close to the floor (not on
# tiptoe), pelvis at least this share of its reference height above it (not kneeling or
# sitting), held this long. The floor is the one tracked under the still ankles, but never more
# than FOOT_STANCE_FLOOR_DRIFT above the clip's lowest still ankles: clips drift that much (CMU
# 02_01's floor rises ~4 cm), while stance on tiptoe (ankles 14 cm up) or on a stool rung (31 cm)
# would otherwise raise the floor with it and pass as standing flat.
FOOT_STANCE_SPEED = 0.25  # m/s
FOOT_STANCE_TURN_DEG_S = 40.0
FOOT_STANCE_HEIGHT = 0.03  # m
FOOT_STANCE_FLOOR_DRIFT = 0.05  # m
FOOT_STANCE_HIPS = 0.6
FOOT_STANCE_HOLD_S = 0.15
# A foot keeps its reference rotation with less stance than this (a jog); when fewer than
# FOOT_STANCE_KEEP of its stance frames lie within 15 deg of their median direction, or they
# spread more than FOOT_STANCE_SPREAD_DEG about it (median), i.e. there is no one flat stance;
# or when the correction would exceed FOOT_STANCE_MAX_TURN_DEG.
FOOT_STANCE_MIN_S = 0.4
FOOT_STANCE_KEEP = 0.5
FOOT_STANCE_SPREAD_DEG = 10.0
FOOT_STANCE_MAX_TURN_DEG = 90.0  # references caught mid-step need 60-78 deg; clips standing flat 4-16


def _rot_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest rotation matrix taking direction a to direction b (not opposite)."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    s, c = float(np.linalg.norm(v)), float(np.dot(a, b))
    if s < 1e-12:
        return np.eye(3)
    K = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return np.eye(3) + K + K @ K * ((1.0 - c) / s ** 2)


def _canonical_feet(clip: HumanClip, robot_up: dict | None = None) -> tuple[dict, dict]:
    """Foot rotations for the reference pose from how the feet stand in the clip itself:
    ({"LeftFoot": R, "RightFoot": R}, report).

    The robot foot's rotation offset maps the human foot frame of the reference pose onto the
    robot's T-pose foot, which _robot_tpose levels: the reference foot is what "flat" means.
    A reference foot tilted against how the person really stands (the T-pose feet of CMU
    subject 143, toe-up 4-16 deg in every standing frame; a reference frame caught mid-step)
    tilts every frame's foot target by as much. A foot planted and still on the floor stands
    flat, so world up in the foot's own axes (R^T e_z, the same whatever the heading) over the
    clip's stance frames is that foot's own up. Each reference foot gets the smallest world
    tilt that turns this direction onto the robot T-pose foot's up, ``robot_up``
    {"Left" / "Right": world direction}, default vertical (an ankle at its limit can leave the
    T-pose foot tilted when the reference leg is mid-step); its heading (toe-out) stays.
    Stance and fallbacks: the FOOT_STANCE_* constants."""
    from .analysis import floor_track
    from .qc import _sustained

    ref = clip.info["_ref_pose"]
    face = _facing_frame(ref)
    fps = clip.fps
    sides = ("Left", "Right")
    feet = {f"{s}Foot": np.asarray(ref[f"{s}Foot"][1], dtype=np.float64) for s in sides}
    P = np.asarray(clip.info["_feet"], dtype=np.float64)  # ankles (T, 2, 3)
    T = len(P)
    if T < 3:
        return feet, {s: {"stance_frames": 0, "used": "reference (too little stance)"} for s in sides}
    R = np.stack([quat_to_matrix(np.array([fr[f"{s}FootMod"][1] for fr in clip.frames], dtype=np.float64))
                  for s in sides], 1)
    up = R[..., 2, :]  # (T, 2, 3)
    v = np.gradient(P, axis=0) * fps
    n = min(max(1, int(round(fps / 30.0))), T - 1)  # turn rate over ~1/30 s whatever the frame rate
    turn = np.degrees(np.arccos(np.clip(np.einsum("tki,tki->tk", up[n:], up[:-n]), -1.0, 1.0))) * fps / n
    turn = np.concatenate([turn, np.repeat(turn[-1:], n - 1, axis=0)])  # (T - 1, 2)
    turn = np.maximum(np.concatenate([turn[:1], turn]), np.concatenate([turn, turn[-1:]]))  # either side of a frame
    hspeed = np.linalg.norm(v[..., :2], axis=-1)
    still = hspeed < FOOT_STANCE_SPEED
    lowest = float(np.percentile(P[..., 2][still] if still.any() else P[..., 2], 2))
    floor = np.minimum(floor_track(P[..., 2], hspeed, fps), lowest + FOOT_STANCE_FLOOR_DRIFT)
    hips_ref = float(ref["Hips"][0][2] - min(ref["LeftFoot"][0][2], ref["RightFoot"][0][2]))
    upright = np.asarray(clip.info["_hips_z"]) - floor > FOOT_STANCE_HIPS * hips_ref
    stance = ((np.linalg.norm(v, axis=-1) < FOOT_STANCE_SPEED) & (turn < FOOT_STANCE_TURN_DEG_S)
              & (P[..., 2] - floor[:, None] < FOOT_STANCE_HEIGHT) & upright[:, None])
    hold = max(1, int(round(FOOT_STANCE_HOLD_S * fps)))

    def pitch_roll(d: np.ndarray) -> np.ndarray:
        d = face.T @ d  # facing axes: x forward, y left
        return np.degrees([np.arctan2(d[0], d[2]), np.arctan2(d[1], d[2])])

    report = {}
    for k, s in enumerate(sides):
        st = _sustained(stance[:, k], hold)
        r = report[s] = {"stance_frames": int(st.sum())}
        if st.sum() < max(5, round(FOOT_STANCE_MIN_S * fps)):
            r["used"] = "reference (too little stance)"
            continue
        w = up[st, k]
        m = np.median(w, axis=0)
        m /= np.linalg.norm(m)
        keep = np.degrees(np.arccos(np.clip(w @ m, -1.0, 1.0))) < 15.0  # outliers out, then again
        if keep.any():
            m = np.median(w[keep], axis=0)
            m /= np.linalg.norm(m)
        spread = np.degrees(np.arccos(np.clip(w @ m, -1.0, 1.0)))  # over every stance frame
        r["spread_deg"] = {"p50": round(float(np.median(spread)), 2), "p90": round(float(np.percentile(spread, 90)), 2)}
        r["kept"] = round(float(keep.mean()), 2)
        a = feet[f"{s}Foot"] @ m  # the stance foot's up placed in the reference foot (world)
        u = np.asarray((robot_up or {}).get(s, (0.0, 0.0, 1.0)), dtype=np.float64)
        u = u / np.linalg.norm(u)
        tilt = float(np.degrees(_angle(a, u)))
        # how the robot foot would stand with the reference foot as is: + toe_up = toe up,
        # + roll = left edge up
        toe_up, roll = pitch_roll(a) - pitch_roll(u)
        r["reference_vs_stance_deg"] = {"toe_up": round(float(toe_up), 2), "roll": round(float(roll), 2),
                                        "total": round(tilt, 2)}
        if r["kept"] < FOOT_STANCE_KEEP or r["spread_deg"]["p50"] > FOOT_STANCE_SPREAD_DEG:
            r["used"] = "reference (stance frames disagree)"
        elif tilt > FOOT_STANCE_MAX_TURN_DEG:
            r["used"] = "reference (correction too large)"
        else:
            feet[f"{s}Foot"] = _rot_between(a, u) @ feet[f"{s}Foot"]
            r["used"] = "stance"
    return feet, report


def derive_tpose_config(robot: str, clip: HumanClip) -> tuple[dict, float, dict]:
    """GMR IK config for a T-pose BVH clip: (config, ground offset, info).

    Starts from GMR's LAFAN1 config of the robot (task list + weights) and replaces
    - rotation offsets: human frame at the reference T-pose -> robot body frame in
      the robot posed the same way (limb directions matched joint by joint, each limb
      twisted so its elbow / knee bends about the human's axis, from the clip's bends);
      the feet are levelled as the human feet stand flat in the clip (_canonical_feet),
      not as they happen to be in the reference pose;
    - scale table: robot / human root-to-ankle distance for the legs and root,
      root-to-wrist distance for the torso and arms, in those poses;
    - ground: a constant shift so the scaled feet stand at the robot's ankle
      height in the lowest 5 % of frames.
    """
    gmr = _gmr()
    try:
        base_path = gmr.IK_CONFIG_DICT["bvh_lafan1"][robot]
    except KeyError:
        raise ValueError(f"GMR has no LAFAN1 task list for {robot!r}; T-pose BVH needs one") from None
    with open(base_path, encoding="utf-8") as f:
        cfg = json.load(f)
    model = robot_model(robot)
    ref = clip.info["_ref_pose"]
    face = _facing_frame(ref)
    bend_axes = _human_bend_axes(robot, clip)
    data, chosen = _robot_tpose(model, robot, ref, face, {k: a for k, (a, _) in bend_axes.items() if a is not None})

    import mujoco as mj

    def body_pose(name):
        b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)
        return data.xpos[b].copy(), data.xmat[b].reshape(3, 3).copy()

    robot_of = {e[0]: frame for frame, e in cfg["ik_match_table1"].items()}  # human body -> robot body
    # the reference feet as the clip's feet stand, onto the robot T-pose feet (_robot_tpose and the
    # bend axes read no foot rotation, so only the foot offsets below change)
    feet, foot_report = _canonical_feet(clip, {s: face @ body_pose(robot_of[f"{s}FootMod"])[1][:, 2]
                                               for s in ("Left", "Right")})
    ref = {**ref, **{b: (ref[b][0], R) for b, R in feet.items()}}
    root_r = body_pose(cfg["robot_root_name"])[0]
    root_h = ref["Hips"][0]

    def ref_human(b):
        return ref[b.replace("FootMod", "Foot")]

    offsets, pos_offsets = {}, {}
    centers = JOINT_CENTERS.get(robot, {})
    for hb in TPOSE_BODIES:
        if hb not in robot_of:
            raise ValueError(f"{base_path}: no robot body for human body {hb}")
        pr, Rr = body_pose(robot_of[hb])
        offsets[hb] = matrix_to_quat(ref_human(hb)[1].T @ face @ Rr)
        # GMR adds R_target @ offset to the human joint position: body origin relative to the joint centre
        pos_offsets[hb] = Rr.T @ (pr - body_pose(centers[hb])[0]) if hb in centers else np.zeros(3)

    # One scale per region, like GMR's own tables: robot body origins are not at
    # the human joints (G1 hip_yaw_link sits mid-thigh), so per-body ratios would
    # distort the pose. Legs: root-to-ankle ratio; arms: root-to-wrist ratio.
    def region_scale(end: str) -> float:
        r = [np.linalg.norm(body_pose(robot_of[f"{s}{end}"])[0] - root_r)
             / max(np.linalg.norm(ref_human(f"{s}{end}")[0] - root_h), 1e-6) for s in ("Left", "Right")]
        return float(np.clip(np.mean(r), 0.3, 1.5))

    s_leg, s_arm = region_scale("FootMod"), region_scale("Hand")
    lower = {"Hips", "LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftFootMod", "RightFootMod"}
    scales = {hb: s_leg if hb in lower else s_arm for hb in TPOSE_BODIES}

    for table in ("ik_match_table1", "ik_match_table2"):
        for frame, e in cfg[table].items():
            e[3] = [round(float(v), 4) for v in pos_offsets[e[0]]]
            e[4] = [round(float(v), 6) for v in offsets[e[0]]]
    cfg["human_root_name"] = "Hips"
    cfg["ground_height"] = 0.0
    cfg["human_scale_table"] = {k: round(v, 4) for k, v in scales.items()}

    # ground: GMR scales positions about the root -> scaled foot height per frame
    hips_z, feet = clip.info["_hips_z"], clip.info["_feet"]
    s_root, s_feet = scales["Hips"], np.array([scales["LeftFootMod"], scales["RightFootMod"]])
    foot_z = s_root * hips_z[:, None] + s_feet[None] * (feet[..., 2] - hips_z[:, None])
    stance = float(np.percentile(foot_z.min(axis=1), 5))
    ankle_h = _sole_height(model, data, robot_of["LeftFootMod"])
    ground = stance - ankle_h
    info = {
        "base_config": os.path.basename(str(base_path)),
        "robot_tpose": chosen,
        "bend_axes": {k: info for k, (_, info) in bend_axes.items()},  # human elbow / knee axes from the clip
        "foot_reference": foot_report,  # foot levelling from the clip's stance (_canonical_feet)
        "scales": cfg["human_scale_table"],
        "ground_offset_m": round(ground, 4),
        "robot_ankle_height_m": round(ankle_h, 4),
    }
    return cfg, ground, info


# --------------------------------------------------------------------------- IK
def run_gmr(clip: HumanClip, robot: str, src_human: str, config: dict | None = None,
            ground_offset: float = 0.0, velocity_limit: bool = False, warmup: int = 50,
            log=print) -> tuple[np.ndarray, dict]:
    """Retarget every frame. Returns qpos (T, 7 + D) and the position targets of the
    bodies GMR tracks by position ({"bodies": [(human, robot body)], "targets": (T, B, 3)}),
    for :func:`position_residuals`."""
    gmr = _gmr()
    tmp = None
    if config is not None:  # GMR reads its config from IK_CONFIG_DICT[src][robot]
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="gmr_cfg_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f)
        gmr.IK_CONFIG_DICT.setdefault(src_human, {})[robot] = tmp
    try:
        with _quiet():
            ret = gmr.GeneralMotionRetargeting(
                src_human=src_human, tgt_robot=robot,
                actual_human_height=None if config is not None else clip.height_m,
                verbose=False, use_velocity_limit=velocity_limit)
    finally:
        if tmp:
            os.remove(tmp)
            del gmr.IK_CONFIG_DICT[src_human][robot]
    ret.set_ground_offset(ground_offset)
    bodies = [(h, frame) for frame, (h, pw, *_rest) in ret.ik_match_table2.items() if pw > 0]

    def copy_frame(fr):
        return {k: [np.array(v[0], dtype=np.float64), np.array(v[1], dtype=np.float64)] for k, v in fr.items()}

    # Start from the first frame's root target: differential IK cannot swing the
    # floating base around from the default heading (a clip starting ~180 deg away
    # stays tens of degrees off), then converge the limbs on frame 0 so the clip
    # does not start with a jump.
    ret.update_targets(copy_frame(clip.frames[0]))
    root_pos, root_quat = ret.scaled_human_data[ret.human_root_name]
    q = ret.configuration.q.copy()
    q[:3], q[3:7] = root_pos, quat_normalize(np.asarray(root_quat))
    ret.configuration.update(q)
    with _quiet():
        for _ in range(warmup):
            ret.retarget(copy_frame(clip.frames[0]))
    qpos, targets = [], []
    t0 = time.perf_counter()
    for i, fr in enumerate(clip.frames):
        with _quiet():
            qpos.append(ret.retarget(copy_frame(fr)))
        targets.append([ret.scaled_human_data[h][0] for h, _ in bodies])
        if log and (i + 1) % 300 == 0:
            log(f"  {i + 1}/{len(clip.frames)} frames ({(i + 1) / (time.perf_counter() - t0):.0f} fps)")
    return np.array(qpos), {"bodies": bodies, "targets": np.array(targets)}


def position_residuals(model, qpos: np.ndarray, track: dict) -> dict:
    """Distance between tracked robot bodies (MuJoCo FK of qpos) and GMR's position
    targets, worst body per group and frame: {group: {mean_cm, p95_cm, max_cm}}."""
    import mujoco as mj

    data = mj.MjData(model)
    ids = [mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, b) for _, b in track["bodies"]]
    err = np.zeros((len(qpos), len(ids)))
    for t, q in enumerate(qpos):
        data.qpos[:] = q
        mj.mj_kinematics(model, data)
        err[t] = np.linalg.norm(data.xpos[ids] - track["targets"][t], axis=1)
    groups = {"pelvis": ["Hips", "pelvis"], "feet": ["Foot", "foot", "ankle"], "hands": ["Hand", "hand", "wrist"]}
    resid = {}
    for g, keys in groups.items():
        cols = [k for k, (h, _) in enumerate(track["bodies"]) if any(s in h for s in keys)]
        if cols:
            e = err[:, cols].max(axis=1)
            resid[g] = {"mean_cm": round(100 * float(e.mean()), 2), "p95_cm": round(100 * float(np.percentile(e, 95)), 2),
                        "max_cm": round(100 * float(e.max()), 2)}
    return resid


def robot_joint_ranges(model) -> tuple[np.ndarray, np.ndarray]:
    """Lower / upper limits of the non-free joints in qpos order (±inf if unlimited)."""
    import mujoco as mj

    ids = [mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in robot_joint_names(model)]
    lo = np.array([model.jnt_range[j][0] if model.jnt_limited[j] else -np.inf for j in ids])
    hi = np.array([model.jnt_range[j][1] if model.jnt_limited[j] else np.inf for j in ids])
    return lo, hi


def smooth_motion(m: RobotMotion, cutoff_hz: float, order: int = 4, limits=None) -> RobotMotion:
    """Zero-phase Butterworth low-pass (filtfilt) of joints, root position and root
    orientation; joints are clipped back into ``limits`` (lo, hi) afterwards.

    GMR solves every frame on its own, so its output carries frame-to-frame jitter
    that a low-pass removes without lag. Quaternions are made sign-continuous,
    filtered per component and renormalised (fine for the small per-frame steps
    of mocap). 6 Hz was chosen by comparing cut-offs on CMU clips.
    """
    from scipy.signal import butter, filtfilt

    if cutoff_hz <= 0 or m.num_frames < 4:
        return m
    if cutoff_hz >= 0.5 * m.fps:
        raise ValueError(f"cutoff {cutoff_hz} Hz must be below Nyquist ({0.5 * m.fps:g} Hz at {m.fps:g} fps)")
    b, a = butter(order, cutoff_hz / (0.5 * m.fps))
    padlen = min(3 * max(len(a), len(b)), m.num_frames - 1)

    def lowpass(x):
        return filtfilt(b, a, x, axis=0, padlen=padlen)

    quat = m.root_quat.copy()
    flip = np.cumsum(np.concatenate([[0], (np.sum(quat[1:] * quat[:-1], axis=1) < 0).astype(int)])) % 2 == 1
    quat[flip] *= -1
    dof = lowpass(m.dof_pos)
    if limits is not None:
        dof = np.clip(dof, limits[0], limits[1])
    return RobotMotion(
        name=m.name, joint_names=list(m.joint_names), root_pos=lowpass(m.root_pos),
        root_quat=quat_normalize(lowpass(quat)), dof_pos=dof, fps=m.fps, source=m.source,
        meta={**m.meta, "smoothing": {"filter": "butterworth, zero-phase (filtfilt)", "order": order,
                                      "cutoff_hz": cutoff_hz}},
    )


# Legs for the foot post-processing (ensure_swing_clearance, flatten_stance_feet):
# (foot body, leg joints hip -> ankle, the last two being ankle pitch and roll).
_G1_LEGS = [(f"{s}_ankle_roll_link",
             [f"{s}_{j}_joint" for j in ("hip_pitch", "hip_roll", "hip_yaw", "knee", "ankle_pitch", "ankle_roll")])
            for s in ("left", "right")]
SWING_LEGS = {"unitree_g1": _G1_LEGS, "unitree_g1_with_hands": _G1_LEGS}


class _FeetFK:
    """GMR's robot model posed at the frames of a motion, for the foot post-processing.
    ``feet``: (body id, sole contact geoms, leg joints) per leg of SWING_LEGS; empty when the
    robot model or the motion lacks one of them."""

    def __init__(self, m: RobotMotion, robot: str):
        import mujoco as mj

        self.mj, self.m = mj, m
        self.model = model = robot_model(robot)
        self.data = mj.MjData(model)
        self.names = robot_joint_names(model)
        self.col = {n: i for i, n in enumerate(m.joint_names)}
        self.jid = {n: mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in self.names}
        lo, hi = robot_joint_ranges(model)
        self.rng = {n: (lo[i], hi[i]) for i, n in enumerate(self.names)}
        self.feet = []
        for body, joints in SWING_LEGS.get(robot, []):
            b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, body)
            soles = [g for g in range(model.ngeom) if model.geom_bodyid[g] == b
                     and (model.geom_contype[g] or model.geom_conaffinity[g])]
            if b < 0 or not soles or any(j not in self.col for j in joints):
                self.feet = []
                break
            self.feet.append((b, soles, joints))
        self.G = max((len(f[1]) for f in self.feet), default=0)

    def set_pose(self, dof_row: np.ndarray, t: int) -> None:
        model, m = self.model, self.m
        q = model.qpos0.copy()
        q[:3], q[3:7] = m.root_pos[t], m.root_quat[t]
        for n in self.names:
            if n in self.col:
                q[model.jnt_qposadr[self.jid[n]]] = dof_row[self.col[n]]
        self.data.qpos[:] = q

    def poses(self, dof: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Bottom of every sole contact sphere (T, feet, G, 3; inf-padded) and foot body
        rotations (T, feet, 3, 3) with the joints ``dof``."""
        model, data = self.model, self.data
        T = self.m.num_frames
        P = np.full((T, len(self.feet), self.G, 3), np.inf)
        R = np.zeros((T, len(self.feet), 3, 3))
        for t in range(T):
            self.set_pose(dof[t], t)
            self.mj.mj_kinematics(model, data)
            for k, (b, soles, _) in enumerate(self.feet):
                P[t, k, :len(soles)] = [data.geom_xpos[g] - [0.0, 0.0, model.geom_size[g][0]] for g in soles]
                R[t, k] = data.xmat[b].reshape(3, 3)
        return P, R


def _rot_err(R_target: np.ndarray, R: np.ndarray) -> np.ndarray:
    """World-frame rotation vector taking R to R_target (small-angle form)."""
    D = R_target @ R.T
    return 0.5 * np.array([D[2, 1] - D[1, 2], D[0, 2] - D[2, 0], D[1, 0] - D[0, 1]])


def ensure_swing_clearance(m: RobotMotion, robot: str = "unitree_g1", clearance: float = 0.02, slow: float = 0.3,
                           fast: float = 1.0, rot_weight: float = 0.2,
                           max_change_deg: float = 20.0) -> tuple[RobotMotion, dict]:
    """Lift moving feet that skim the floor; returns the motion and a summary.

    The floor under the robot is tracked through the clip (``analysis.floor_track``: the
    lower of the feet standing still, i.e. whose slowest sole contact point moves slower
    than ``slow`` m/s horizontally, interpolated between those frames). A clip whose
    floor drifts (CMU 02_01 rises ~4 cm) keeps a local reference this way. A moving foot must
    keep every sole point above that floor by a margin that grows with its speed: 0 at
    ``slow``, ``clearance`` from ``fast`` m/s on. A foot sliding fast close to the floor
    catches it in physics; one slowing down into touch-down may come close.

    Shortfalls are taken up by the moving foot's leg (feet standing still are never
    changed). Weighted damped least squares on its six joints lifts the sole points
    that are too low, keeps the foot's horizontal position, and keeps its orientation
    only softly (``rot_weight``). No joint moves more than ``max_change_deg``: a foot
    that reaches below the floor on a nearly straight leg (late touch-down in the clip)
    would need the knee bent by tens of degrees, so it is lifted only partly and the
    rest is reported. The joint changes are smoothed over time.

    Why: retargets of one walk differ here. On CMU 02_01 the SMPL-X retarget swings with
    less knee flexion (heel 0.8 cm above the floor before touch-down) and the FBX retarget
    toes off pointing 71 deg down (toe 0.6 cm). Kinematic replay shows nothing wrong, but
    in PhysX both catch the floor, stumble, and the SMPL-X one falls.
    """
    import mujoco as mj
    from scipy.ndimage import gaussian_filter1d, maximum_filter1d

    from .analysis import floor_track, slowest_sole_speed

    T = m.num_frames
    if not SWING_LEGS.get(robot) or clearance <= 0 or T < 4:
        return m, {}
    fk = _FeetFK(m, robot)
    if not fk.feet:
        return m, {}
    model, data, col, jid, rng, feet, set_pose = fk.model, fk.data, fk.col, fk.jid, fk.rng, fk.feet, fk.set_pose

    def sole_points(dof: np.ndarray) -> np.ndarray:
        return fk.poses(dof)[0]

    P = sole_points(m.dof_pos)
    low = P[..., 2].min(-1)  # (T, feet)
    speed = slowest_sole_speed(P, m.fps)
    still = speed < slow
    floor = floor_track(low, speed, m.fps, still=slow)
    margin = clearance * np.clip((speed - slow) / (fast - slow), 0.0, 1.0)
    margin = np.stack([gaussian_filter1d(maximum_filter1d(margin[:, k], size=3), 1.0) for k in range(len(feet))], 1)
    margin[still] = 0.0
    need = floor[:, None] + margin  # required height of every sole point (T, feet)
    short = np.where(still, 0.0, np.maximum(need - low, 0.0))

    dof = m.dof_pos.copy()
    lam = 1e-4
    cap = np.radians(max_change_deg)
    for t in np.flatnonzero((short > 1e-3).any(1)):
        for k, (body, soles, joints) in enumerate(feet):
            if short[t, k] <= 1e-3:
                continue
            set_pose(dof[t], t)
            mj.mj_kinematics(model, data)
            xy0 = data.xpos[body][:2].copy()
            R0 = data.xmat[body].reshape(3, 3).copy()
            dofs = [model.jnt_dofadr[jid[j]] for j in joints]
            for _ in range(8):
                set_pose(dof[t], t)
                mj.mj_kinematics(model, data)
                mj.mj_comPos(model, data)
                rows, errs, w = [], [], []
                jacp, jacr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
                for g in soles:
                    z = data.geom_xpos[g][2] - model.geom_size[g][0]
                    if z < need[t, k] - 1e-4:
                        mj.mj_jac(model, data, jacp, jacr, data.geom_xpos[g], body)
                        rows.append(jacp[2, dofs].copy())
                        errs.append(need[t, k] - z)
                        w.append(1.0)
                if not rows:
                    break
                mj.mj_jacBody(model, data, jacp, jacr, body)
                rows += list(jacp[:2, dofs]) + list(jacr[:, dofs])
                errs += list(xy0 - data.xpos[body][:2]) + list(_rot_err(R0, data.xmat[body].reshape(3, 3)))
                w += [1.0, 1.0] + [rot_weight] * 3
                J, e, W = np.array(rows), np.array(errs), np.array(w)
                dq = np.linalg.solve(J.T @ (W[:, None] * J) + lam * np.eye(len(dofs)), J.T @ (W * e))
                dq = np.clip(dq, -0.05, 0.05)  # small steps: the active sole points change as the foot moves
                for j, d in zip(joints, dq):
                    q0 = m.dof_pos[t, col[j]]
                    dof[t, col[j]] = np.clip(np.clip(dof[t, col[j]] + d, q0 - cap, q0 + cap), *rng[j])

    leg_joints = [j for _, _, joints in feet for j in joints]
    leg_cols = [col[j] for j in leg_joints]
    delta = gaussian_filter1d(dof[:, leg_cols] - m.dof_pos[:, leg_cols], 1.0, axis=0)
    n_leg = len(feet[0][2])
    for k in range(len(feet)):  # the smoothing must not reach a foot standing still
        delta[still[:, k], k * n_leg:(k + 1) * n_leg] = 0.0
    dof[:, leg_cols] = np.clip(m.dof_pos[:, leg_cols] + delta, [rng[j][0] for j in leg_joints],
                               [rng[j][1] for j in leg_joints])
    after = sole_points(dof)[..., 2].min(-1)
    moving = speed >= fast
    changed = (np.abs(dof[:, leg_cols] - m.dof_pos[:, leg_cols]) > np.radians(0.1)).any(1)
    change = np.degrees(np.abs(dof[:, leg_cols] - m.dof_pos[:, leg_cols]))

    def fast_min(z: np.ndarray) -> float | None:
        return round(100 * float((z - floor[:, None])[moving].min()), 2) if moving.any() else None

    info = {
        "clearance_cm": round(100 * clearance, 2),
        "speed_for_full_clearance_mps": fast,
        "frames_changed": int(changed.sum()),
        "shortfall_cm": {"mean": round(100 * float(short[short > 1e-3].mean()), 2) if (short > 1e-3).any() else 0.0,
                         "max": round(100 * float(short.max()), 2)},
        "remaining_shortfall_cm_max": round(100 * float(np.where(still, 0.0, np.maximum(need - after, 0.0)).max()), 2),
        "leg_joint_change_deg": {"rmse": round(float(np.sqrt((change ** 2).mean())), 2),
                                 "max": round(float(change.max()), 2)},
        "fast_foot_min_clearance_cm": {"before": fast_min(low), "after": fast_min(after)},
        "floor_drift_cm": round(100 * float(floor.max() - floor.min()), 2),
    }
    out = RobotMotion(name=m.name, joint_names=list(m.joint_names), root_pos=m.root_pos.copy(),
                      root_quat=m.root_quat.copy(), dof_pos=dof, fps=m.fps, source=m.source,
                      meta={**m.meta, "swing_clearance": info})
    return out, info


def flatten_stance_feet(m: RobotMotion, robot: str = "unitree_g1", still: float = 0.2, contact: float = 0.03,
                        min_duration: float = 0.1, max_tilt_deg: float = 25.0, blend: float = 0.15,
                        floor_min: float = 0.0, joint_sigma_deg: float = 5.0, root_sigma: float = 0.05,
                        max_root_drop: float = 0.06, max_root_rise: float = 0.005,
                        roll_comfort_deg: float = 2.0, iters: int = 12) -> tuple[RobotMotion, dict]:
    """Stand the feet that stand still flat on the floor with both legs and the pelvis height;
    returns the motion and a summary.

    A foot stands still when every sole contact point moves slower than ``still`` m/s and
    the lowest one is within ``contact`` of the floor tracked through the clip
    (``analysis.floor_track``, never below ``floor_min``, the ground the retarget stands on:
    a foot sinking through it would otherwise drag the other standing foot down with it), for
    at least ``min_duration``. On those frames its sole is turned parallel to the floor and
    lowered onto it, keeping the ankle's horizontal position and the foot's heading; a foot
    sunk below the floor is raised by at most ``max_root_rise`` (more would need knee and
    ankle changes a deep crouch cannot make: the solver then twisted and slid the foot
    instead, 12 deg and 1 cm on CMU 143_13). A foot standing on its forefoot (toe down:
    heel-off, tiptoe) only has its roll levelled and keeps its pitch. Stance frames tilted
    more than ``max_tilt_deg`` (kneeling on the toes) are left alone. The correction fades in
    and out over ``blend`` s inside each stance, so a foot landing toe-up rolls flat like a
    heel strike and is back to its own angle when it lifts off.

    Per frame a bounded least-squares IK (Gauss-Newton) moves the 12 leg joints and the root
    height: the stance foot's sole points to their levelled heights on the floor, its ankle
    xy and heading kept; every other foot kept where it was in the world (a swing foot makes
    up for the root moving); joints held near their own angles (``joint_sigma_deg``; the
    root height ``root_sigma`` m costs as much), within their ranges, the root between
    ``max_root_drop`` below and ``max_root_rise`` above its own height. An ankle roll that
    would end within ``roll_comfort_deg`` of its limit (G1: +-15 deg) is pulled back, so
    hip roll, knee and pelvis take the rest. Arms, waist, root xy and orientation are not
    touched. The changes are smoothed over time.

    Why: the retargets of CMU subject 143 (BVH, FBX and AMASS SMPL-X alike) stand with the
    feet pitched toe-up 4-16 deg, on the heel edge only. The support polygon then is a line
    behind the ankles, so standing still reads as unbalanced (static_unbalanced 22-39 %),
    and the physics replay stands on its heels. Most of that tilt was the T-pose foot
    reference (_canonical_feet levels it now); what is left changes within a clip (the
    143 BVH feet read 7-14 deg more toe-up standing upright than crouched). The ankle-only
    version of this pass levelled the sole about the ankle: the heel came off the floor
    0.5-1.9 cm, the floor tracked from those soles rose and pulled slow swing feet to it
    (143_28 swing_low 3.7 -> 17 %), the ankle roll stopped at its limit, and a foot standing
    higher than the other (FBX 143_13, 2.3-2.9 cm) could not be lowered.
    """
    import mujoco as mj
    from scipy.ndimage import gaussian_filter1d
    from scipy.optimize import lsq_linear
    from scipy.spatial.transform import Rotation

    from .analysis import floor_track, slowest_sole_speed
    from .qc import _sustained

    T = m.num_frames
    if not SWING_LEGS.get(robot) or T < 4:
        return m, {}
    fk = _FeetFK(m, robot)
    if not fk.feet or any(len(soles) < 3 for _, soles, _ in fk.feet):
        return m, {}
    model, data, feet = fk.model, fk.data, fk.feet
    F = len(feet)
    # sole plane in the foot body frame: normal pointing into the foot, forward axis heel -> toe
    axes = []
    for _, soles, _ in feet:
        c = model.geom_pos[soles]
        vt = np.linalg.svd(c - c.mean(0))[2]
        normal = vt[2] if vt[2] @ c.mean(0) < 0 else -vt[2]
        fwd = vt[0] if (c @ vt[0]).max() > -(c @ vt[0]).min() else -vt[0]
        axes.append((normal, fwd))
    sole_pos = [model.geom_pos[soles].copy() for _, soles, _ in feet]
    sole_rad = [model.geom_size[soles, 0].copy() for _, soles, _ in feet]

    def angles(R: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(T, feet) sole tilt from horizontal and pitch (+ toe up), degrees."""
        n = np.stack([R[:, k] @ axes[k][0] for k in range(F)], 1)
        f = np.stack([R[:, k] @ axes[k][1] for k in range(F)], 1)
        return np.degrees(np.arccos(np.clip(n[..., 2], -1, 1))), np.degrees(np.arcsin(np.clip(f[..., 2], -1, 1)))

    P, R = fk.poses(m.dof_pos)
    low = P[..., 2].min(-1)
    floor = np.maximum(floor_track(low, slowest_sole_speed(P, m.fps), m.fps), floor_min)
    fastest = np.linalg.norm(np.diff(P, axis=0), axis=-1).max(-1) * m.fps
    fastest = np.concatenate([fastest[:1], fastest])
    tilt, pitch = angles(R)
    n_min = max(1, int(round(min_duration * m.fps)))
    planted = (fastest < still) & (low - floor[:, None] < contact)
    planted = np.stack([_sustained(planted[:, k], n_min) for k in range(F)], 1)
    stance = planted & (tilt <= max_tilt_deg)

    # weight: 1 inside a stance, ramping down towards the frames outside it (not at the clip's ends)
    ramp = max(1, int(round(blend * m.fps)))
    w = np.zeros((T, F))
    for k in range(F):
        edges = np.flatnonzero(np.diff(np.concatenate([[0], stance[:, k].astype(int), [0]])))
        for a, b in zip(edges[::2], edges[1::2]):
            t = np.arange(a, b)
            d = np.minimum(t - a + 1 if a > 0 else np.inf, b - t if b < T else np.inf)
            w[a:b, k] = np.minimum(1.0, d / (ramp + 1))

    # unknowns: the leg joints (hip -> ankle, per foot), then the root height
    leg_joints = [j for _, _, joints in feet for j in joints]
    of_foot = [[leg_joints.index(j) for j in joints] for _, _, joints in feet]
    cols = [fk.col[j] for j in leg_joints]
    adr = np.array([model.jnt_qposadr[fk.jid[j]] for j in leg_joints])
    V = [model.jnt_dofadr[fk.jid[j]] for j in leg_joints] + [2]  # root z: free joint dof 2
    nJ = len(leg_joints)
    lo = np.array([fk.rng[j][0] for j in leg_joints])
    hi = np.array([fk.rng[j][1] for j in leg_joints])
    margin = np.radians(1.5)
    sigma = np.concatenate([np.full(nJ, np.radians(joint_sigma_deg)), [root_sigma]])
    s_pos, s_rot, s_sole, s_yaw = 1e-3, np.radians(0.5), 2e-3, np.radians(1.0)  # task tolerances
    rolls = [i for i, j in enumerate(leg_joints) if j.endswith("ankle_roll_joint")]
    comfort, s_comfort = np.radians(roll_comfort_deg), np.radians(1.0)
    up = np.array([0.0, 0.0, 1.0])

    delta = np.zeros((T, nJ + 1))
    limited = np.zeros((T, F), dtype=bool)
    jacp, jacr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
    qvel = np.zeros(model.nv)
    for t in np.flatnonzero((w > 0).any(1)):
        fk.set_pose(m.dof_pos[t], t)
        q0 = data.qpos.copy()
        mj.mj_kinematics(model, data)
        targets = []  # per foot: (position, rotation) of the foot body
        for k, (body, _, _) in enumerate(feet):
            p0, R0 = data.xpos[body].copy(), data.xmat[body].reshape(3, 3).copy()
            if w[t, k] <= 0:
                targets.append((p0, R0))
                continue
            f0 = R0 @ axes[k][1]
            # level: the sole normal up (toe down: only the roll levelled) and the heel -> toe
            # axis keeping its heading
            n1 = up if f0[2] >= 0 else (up - f0[2] * f0) / np.linalg.norm(up - f0[2] * f0)
            f1 = f0 if f0[2] < 0 else f0 - f0[2] * up
            f1 = f1 - (f1 @ n1) * n1
            f1 /= np.linalg.norm(f1)
            nb, fb = axes[k]
            R1 = np.stack([f1, np.cross(n1, f1), n1], 1) @ np.stack([fb, np.cross(nb, fb), nb], 1).T
            fz = min(floor[t], low[t, k] + max_root_rise)  # a sunk foot comes up only so far
            p1 = np.array([p0[0], p0[1], fz - ((sole_pos[k] @ R1.T)[:, 2] - sole_rad[k]).min()])
            rv = Rotation.from_matrix(R1 @ R0.T).as_rotvec() * w[t, k]
            targets.append((p0 + w[t, k] * (p1 - p0), Rotation.from_rotvec(rv).as_matrix() @ R0))
        q = q0.copy()
        lo_b, hi_b = np.minimum(lo + margin, q0[adr]), np.maximum(hi - margin, q0[adr])  # never pushed into a limit
        for _ in range(iters):
            data.qpos[:] = q
            mj.mj_kinematics(model, data)
            mj.mj_comPos(model, data)
            rows, errs = [], []
            for k, (body, _, _) in enumerate(feet):
                mj.mj_jacBody(model, data, jacp, jacr, body)
                Jp, Jr = jacp[:, V], jacr[:, V]
                pb, Rb = data.xpos[body], data.xmat[body].reshape(3, 3)
                p1, R1 = targets[k]
                if w[t, k] <= 0:  # any other foot stays where it is
                    rows += [Jp / s_pos, Jr / s_rot]
                    errs += [(p1 - pb) / s_pos, _rot_err(R1, Rb) / s_rot]
                    continue
                rows += [Jp[:2] / s_pos, Jr[2:3] / s_yaw]  # ankle xy, heading
                errs += [(p1[:2] - pb[:2]) / s_pos, _rot_err(R1, Rb)[2:3] / s_yaw]
                z1 = p1[2] + (sole_pos[k] @ R1.T)[:, 2]  # sole point heights of the levelled foot on the floor
                for g, c in enumerate(sole_pos[k]):
                    o = Rb @ c
                    rows.append(((Jp[2] + Jr[0] * o[1] - Jr[1] * o[0]) / s_sole)[None])  # z of (Jp + Jr x o)
                    errs.append(np.array([(z1[g] - pb[2] - o[2]) / s_sole]))
            dev = np.concatenate([q[adr] - q0[adr], [q[2] - q0[2]]])
            rows.append(np.diag(1.0 / sigma))
            errs.append(-dev / sigma)
            for i in rolls:  # an ankle roll near its limit hands over to hip, knee and pelvis
                qc = np.clip(q[adr[i]], lo[i] + comfort, hi[i] - comfort)
                if abs(q[adr[i]] - qc) > 1e-9:
                    r = np.zeros(nJ + 1)
                    r[i] = 1.0 / s_comfort
                    rows.append(r[None])
                    errs.append(np.array([(qc - q[adr[i]]) / s_comfort]))
            lb = np.minimum(np.concatenate([lo_b - q[adr], [-max_root_drop - dev[-1]]]), 0.0)
            ub = np.maximum(np.concatenate([hi_b - q[adr], [max_root_rise - dev[-1]]]), 0.0)
            A, free, dx = np.vstack(rows), ub > lb, np.zeros(nJ + 1)  # a column its bounds pin stays put
            if free.any():
                dx[free] = lsq_linear(A[:, free], np.concatenate(errs), bounds=(lb[free], ub[free]), method="bvls").x
            dx = np.clip(dx, -0.1, 0.1)
            qvel[:] = 0.0
            qvel[V] = dx
            mj.mj_integratePos(model, q, qvel, 1.0)
            if np.abs(dx).max() < 1e-6:
                break
        at = (q[adr] <= lo_b + 1e-5) | (q[adr] >= hi_b - 1e-5)
        limited[t] = [bool(at[i].any()) for i in of_foot]
        delta[t] = np.concatenate([q[adr] - q0[adr], [q[2] - q0[2]]])

    delta = gaussian_filter1d(delta, 1.0, axis=0)
    dof = m.dof_pos.copy()
    dof[:, cols] = np.where(delta[:, :nJ] != 0.0, np.clip(m.dof_pos[:, cols] + delta[:, :nJ], lo, hi),
                            m.dof_pos[:, cols])  # frames far from a stance stay exactly as they were
    root = m.root_pos.copy()
    root[:, 2] += delta[:, -1]
    out = RobotMotion(name=m.name, joint_names=list(m.joint_names), root_pos=root,
                      root_quat=m.root_quat.copy(), dof_pos=dof, fps=m.fps, source=m.source, meta=dict(m.meta))

    P1, R1 = _FeetFK(out, robot).poses(dof)
    tilt1, pitch1 = angles(R1)
    low1 = P1[..., 2].min(-1)
    change = np.degrees(np.abs(dof[:, cols] - m.dof_pos[:, cols]))
    lift = (low1 - low)[w > 0]
    both = stance.all(1)
    sides = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_BODY, body).split("_")[0] for body, _, _ in feet]

    def dist(x: np.ndarray) -> dict | None:
        return {"median": round(float(np.median(x)), 2), "p95": round(float(np.percentile(x, 95)), 2),
                "max": round(float(x.max()), 2)} if len(x) else None

    def median(x: np.ndarray) -> float | None:
        return round(float(np.median(x)), 2) if len(x) else None

    info = {
        "still_speed_mps": still,
        "contact_cm": round(100 * contact, 2),
        "max_tilt_deg": max_tilt_deg,
        "blend_s": blend,
        "frames_changed": int(((change > 0.1).any(1) | (np.abs(delta[:, -1]) > 1e-3)).sum()),
        "stance_pct": {s: round(100 * float(stance[:, k].mean()), 1) for k, s in enumerate(sides)},
        # medians over the stance frames, + = toe up
        "stance_pitch_deg": {s: {"before": median(pitch[stance[:, k], k]), "after": median(pitch1[stance[:, k], k])}
                             for k, s in enumerate(sides)},
        "stance_tilt_deg": {"before": dist(tilt[stance]), "after": dist(tilt1[stance])},
        "too_tilted_frames": int((planted & ~stance).sum()),
        "joint_limit_frames": int(limited.any(1).sum()),
        "leg_change_deg": {"rmse": round(float(np.sqrt((change ** 2).mean())), 2), "max": round(float(change.max()), 2)},
        # lowest sole point, after - before (the ankle-only pass lifted heels 0.5-1.9 cm)
        "sole_lift_cm": {"mean": round(100 * float(lift.mean()), 2) if len(lift) else 0.0,
                         "max": round(100 * float(lift.max()), 2) if len(lift) else 0.0},
        "root_drop_cm": {"mean": round(-100 * float(delta[(w > 0).any(1), -1].mean()), 2) if (w > 0).any() else 0.0,
                         "max": round(max(0.0, -100 * float(delta[:, -1].min())), 2)},
        # both feet standing: height difference of their lowest sole points
        "two_feet_height_diff_cm": {"before": dist(100 * np.abs(low[both, 0] - low[both, 1])) if F == 2 else None,
                                    "after": dist(100 * np.abs(low1[both, 0] - low1[both, 1])) if F == 2 else None},
    }
    out.meta = {**m.meta, "foot_flat": info}
    return out, info


# Self-collision repair (separate_self_collisions): bodies whose visual mesh collides there too.
# The G1 model's hands collide with nothing and its feet only through four 5 mm sole spheres,
# so a hand inside a thigh or feet through each other went unseen.
SELF_MESHES = {robot: ("left_rubber_hand", "right_rubber_hand", "left_ankle_roll_link", "right_ankle_roll_link")
               for robot in ("unitree_g1", "unitree_g1_with_hands")}
SELF_HANDS = {robot: names[:2] for robot, names in SELF_MESHES.items()}
# The trunk and a shoulder link: their hulls overlap up to ~2.3 cm in ordinary poses, so an
# upper arm in the torso counts only deeper than this.
SELF_SHOULDER_DEPTH = 0.025


class _SelfCollisionModel:
    """GMR's robot model where every robot collision geom collides with every other, the hand and
    foot meshes (SELF_MESHES) included (MuJoCo collides their convex hulls), posed at the frames
    of a motion."""

    def __init__(self, m: RobotMotion, robot: str):
        import mujoco as mj

        self.mj = mj
        # compiled with those meshes colliding: MuJoCo builds the convex hull of a mesh only
        # for geoms that collide when the model is compiled
        spec = mj.MjSpec.from_file(str(_gmr().ROBOT_XML_DICT[robot]))
        for name in SELF_MESHES.get(robot, ()):
            body = spec.body(name)
            for g in body.geoms if body is not None else ():
                if g.type == mj.mjtGeom.mjGEOM_MESH:
                    g.contype, g.conaffinity = 1, 1
        self.model = model = spec.compile()
        robot_geom = (model.geom_bodyid > 0) & ((model.geom_contype > 0) | (model.geom_conaffinity > 0))
        model.geom_contype[:] = np.where(robot_geom, 1, 0)
        model.geom_conaffinity[:] = np.where(robot_geom, 1, 0)
        self.data = mj.MjData(model)
        self.m = m
        self.names = robot_joint_names(model)
        self.col = {n: i for i, n in enumerate(m.joint_names)}
        jid = {n: mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in self.names}
        self.qadr = {n: model.jnt_qposadr[jid[n]] for n in self.names}
        self.dadr = {n: model.jnt_dofadr[jid[n]] for n in self.names}
        lo, hi = robot_joint_ranges(model)
        self.rng = {n: (lo[i], hi[i]) for i, n in enumerate(self.names)}
        self.body = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_BODY, b) for b in range(model.nbody)]
        of_body = {}
        for n in self.names:
            of_body.setdefault(int(model.jnt_bodyid[jid[n]]), []).append(n)
        self.ancestors, self.chain = [], []  # per body: bodies above it; hinge joints from it to the root
        for b in range(model.nbody):
            up, js, x = set(), set(), b
            while x > 0:
                js.update(of_body.get(x, ()))
                x = int(model.body_parentid[x])
                up.add(x)
            self.ancestors.append(up)
            self.chain.append(js)

    def pose(self, dof_row: np.ndarray, t: int) -> None:
        q = self.model.qpos0.copy()
        q[:3], q[3:7] = self.m.root_pos[t], self.m.root_quat[t]
        for n in self.names:
            if n in self.col:
                q[self.qadr[n]] = dof_row[self.col[n]]
        self.data.qpos[:] = q
        self.mj.mj_kinematics(self.model, self.data)

    def contacts(self, depth: float) -> list:
        """Robot-robot contacts deeper than ``depth`` at the posed frame, (body 1, body 2, point,
        normal from 1 to 2, distance). Left out, as they touch by design: siblings, bodies of one
        limb (a hand and its wrist), the trunk with a hip link, and the trunk with a shoulder link
        unless deeper than SELF_SHOULDER_DEPTH. The trunk against a forearm, hand, knee or foot counts."""
        model, data = self.model, self.data
        self.mj.mj_collision(model, data)
        out = []
        for c in data.contact[:data.ncon]:
            if c.dist > -depth:
                continue
            b1, b2 = int(model.geom_bodyid[c.geom1]), int(model.geom_bodyid[c.geom2])
            if model.body_parentid[b1] == model.body_parentid[b2]:
                continue
            if b1 in self.ancestors[b2] or b2 in self.ancestors[b1]:
                top, low = (b1, b2) if b1 in self.ancestors[b2] else (b2, b1)
                if self.part(top) != "trunk":
                    continue
                if not any(k in self.body[low] for k in ("elbow", "wrist", "hand", "knee", "ankle")) and (
                        "shoulder" not in self.body[low] or c.dist > -max(depth, SELF_SHOULDER_DEPTH)):
                    continue
            out.append((b1, b2, c.pos.copy(), c.frame[:3].copy(), float(c.dist)))
        return out

    def part(self, b: int) -> str:
        n = self.body[b]
        if any(k in n for k in ("shoulder", "elbow", "wrist", "hand")):
            return "arm"
        return "leg" if any(k in n for k in ("hip", "knee", "ankle")) else "trunk"


def separate_self_collisions(m: RobotMotion, robot: str = "unitree_g1", target: float = 0.015,
                             arm_cap_deg: float = 25.0, leg_cap_deg: float = 10.0, smooth_s: float = 0.1,
                             spread_s: float = 0.1, leg_fade_s: float = 0.2, rounds: int = 8,
                             iters: int = 12) -> tuple[RobotMotion, dict]:
    """Push apart robot parts that go through each other; returns the motion and a summary.

    Every frame is checked with MuJoCo collision on the robot model where all collision
    geoms collide (as retarget_quality measures self-collision), the hand and foot meshes too
    (_SelfCollisionModel). For each contact deeper than ``target`` a damped least-squares step
    moves the two bodies apart along the contact normal, with only the joints allowed for that pair:
    - an arm (or hand) against anything: that arm's shoulder and elbow joints (both arms when
      they touch each other); not the wrists, which 23-DoF consumers (GMT's G1) fix, so a
      separation made with them would be undone there;
    - leg against leg: hip roll and yaw (ankle roll too for the feet) of a leg whose foot is
      not standing (slowest sole point slower than 0.3 m/s within 3 cm of the floor);
    - nothing else moves: not the root, the waist, or a standing foot's leg.
    Each joint stays within ``arm_cap_deg`` / ``leg_cap_deg`` of its own angle and its range.
    The changes are spread over +-``spread_s`` (keeping the largest), smoothed over
    ``smooth_s``, faded out over ``leg_fade_s`` towards a standing foot, then the clip is
    checked again; frames still too deep get up to ``rounds`` rounds. Afterwards
    - a moving foot never ends lower than it was or than 2 cm above the floor, whichever is
      lower (swing clearance runs before this pass): that leg's change is scaled back there;
    - frames the spreading left deeper than they were (fast, twisted motion) get their own
      pose back, tapered, and are counted in ``frames_made_deeper``.
    What stays deeper than the target is reported per pair, in frames (``unresolved_pairs``):
    knees touching with both feet down, a thigh in the torso, a joint at its cap.
    ``target`` 1.5 cm leaves the convex hulls touching a little (they are larger than the
    links); 0 gives a reference physics replays with self-collision on can follow without the
    limbs pushing on each other.

    Why: hands and wrists went 1-4 cm (up to 7.5) into the hip housings in 80-90 % of
    colliding frames, real overlaps of the link meshes; in physics with self-collision off (the
    Isaac replay) the limbs pass through each other, with it on stiff PD tracking jams.
    """
    from scipy.ndimage import distance_transform_edt, gaussian_filter1d, maximum_filter1d, minimum_filter1d

    from .analysis import SLIDE_SPEED, floor_track, slowest_sole_speed

    T = m.num_frames
    if T < 2:
        return m, {}
    t0 = time.perf_counter()
    S = _SelfCollisionModel(m, robot)
    mj = S.mj
    legs = [joints for _, joints in SWING_LEGS.get(robot, [])]
    sides = [joints[0].split("_")[0] for joints in legs]
    standing = np.zeros((T, len(legs)), dtype=bool)
    fk = _FeetFK(m, robot)
    if fk.feet:
        P = fk.poses(m.dof_pos)[0]
        low, speed = P[..., 2].min(-1), slowest_sole_speed(P, m.fps)
        floor = floor_track(low, speed, m.fps)
        standing = (speed < SLIDE_SPEED) & (low - floor[:, None] < 0.03)
        lowest_ok = np.minimum(low, floor[:, None] + 0.02)  # a moving foot ends no lower than this
    nfade = max(1.0, leg_fade_s * m.fps + 1)
    leg_w = np.stack([np.clip(distance_transform_edt(~standing[:, k]) / nfade, 0, 1) if standing[:, k].any()
                      else np.ones(T) for k in range(len(legs))], 1)
    leg_cols = [[S.col[j] for j in joints if j in S.col] for joints in legs]
    cap = np.array([np.radians(leg_cap_deg if any(k in n for k in ("hip", "knee", "ankle")) else arm_cap_deg)
                    for n in m.joint_names])
    lo = np.array([S.rng.get(n, (-np.inf, np.inf))[0] for n in m.joint_names])
    hi = np.array([S.rng.get(n, (-np.inf, np.inf))[1] for n in m.joint_names])
    q0, dof = m.dof_pos, m.dof_pos.copy()
    jacp1, jacp2, jacr = np.zeros((3, S.model.nv)), np.zeros((3, S.model.nv)), np.zeros((3, S.model.nv))
    spread = int(round(spread_s * m.fps))
    deep = -target - 5e-4  # deeper than the target (by more than the solver's 0.5 mm landing)

    def allowed(b1: int, b2: int, free: list[str]) -> list[str]:
        both, out = S.body[b1] + S.body[b2], []
        for j in S.chain[b1] ^ S.chain[b2]:  # the joints that move one body against the other
            if j not in S.col:
                continue
            if any(k in j for k in ("shoulder", "elbow")):
                out.append(j)
            elif S.part(b1) == S.part(b2) == "leg" and j.split("_")[0] in free and (
                    "hip_roll" in j or "hip_yaw" in j or ("ankle_roll" in j and both.count("ankle") == 2)):
                out.append(j)
        return out

    def deepest(d: np.ndarray) -> np.ndarray:
        out = np.zeros(T)
        for t in range(T):
            S.pose(d[t], t)
            out[t] = min((c[4] for c in S.contacts(0.0)), default=0.0)
        return out

    def sole_heights(d: np.ndarray, frames: np.ndarray) -> np.ndarray:
        out = np.empty((len(frames), len(fk.feet)))
        for i, t in enumerate(frames):
            fk.set_pose(d[t], t)
            mj.mj_kinematics(fk.model, fk.data)
            for k, (_, soles, _) in enumerate(fk.feet):
                out[i, k] = min(fk.data.geom_xpos[g][2] - fk.model.geom_size[g][0] for g in soles)
        return out

    worst = before = deepest(dof)
    done = 0
    for _ in range(rounds):
        todo = np.flatnonzero(worst < deep)
        if not len(todo):
            break
        done += 1
        new = dof.copy()
        for t in todo:
            free = [s for k, s in enumerate(sides) if not standing[t, k]]
            row = dof[t].copy()
            for _ in range(iters):
                S.pose(row, t)
                cs = S.contacts(0.999 * target)
                if not cs:
                    break
                mj.mj_comPos(S.model, S.data)
                rows, used = [], set()
                for b1, b2, p, n, dist in cs:
                    js = allowed(b1, b2, free)
                    if not js:
                        continue
                    mj.mj_jac(S.model, S.data, jacp1, jacr, p, b1)
                    mj.mj_jac(S.model, S.data, jacp2, jacr, p, b2)
                    rows.append((n @ (jacp2 - jacp1), -target - dist, set(js)))
                    used.update(js)
                if not rows:
                    break
                js = sorted(used)
                A = np.array([[g[S.dadr[j]] if j in ok else 0.0 for j in js] for g, _, ok in rows])
                e = np.array([x for _, x, _ in rows])
                dq = np.clip(A.T @ np.linalg.solve(A @ A.T + 1e-3 * np.eye(len(e)), e), -0.05, 0.05)
                for j, d in zip(js, dq):
                    c = S.col[j]
                    row[c] = np.clip(np.clip(row[c] + d, q0[t, c] - cap[c], q0[t, c] + cap[c]), *S.rng[j])
            new[t] = row
        delta = new - dof  # spread each change (keeping the largest) so smoothing leaves the peak
        delta = (maximum_filter1d(np.maximum(delta, 0.0), 2 * spread + 1, axis=0)
                 + minimum_filter1d(np.minimum(delta, 0.0), 2 * spread + 1, axis=0))
        delta = gaussian_filter1d(delta, smooth_s * m.fps, axis=0)
        for k, cols in enumerate(leg_cols):  # never a standing foot's leg, fading in and out around it
            delta[:, cols] *= leg_w[:, k, None]
        dof = np.clip(np.clip(dof + delta, q0 - cap, q0 + cap), lo, hi)
        worst = deepest(dof)

    # a moving foot may not end lower than lowest_ok: scale that leg's change back where it would
    held = np.zeros(T, dtype=bool)
    if done and fk.feet:
        scale = np.ones((T, len(legs)))
        for k, cols in enumerate(leg_cols):
            bad = np.flatnonzero(sole_heights(dof, np.arange(T))[:, k] < lowest_ok[:, k] - 1e-3)
            for s in (0.75, 0.5, 0.25, 0.0):
                if not len(bad):
                    break
                trial = dof.copy()
                trial[np.ix_(bad, cols)] = q0[np.ix_(bad, cols)] + s * (dof - q0)[np.ix_(bad, cols)]
                scale[bad, k] = s
                bad = bad[sole_heights(trial, bad)[:, k] < lowest_ok[bad, k] - 1e-3]
            scale[:, k] = gaussian_filter1d(minimum_filter1d(scale[:, k], 7), 1.5)
            held |= scale[:, k] < 1.0 - 1e-6
            dof[:, cols] = q0[:, cols] + scale[:, k, None] * (dof - q0)[:, cols]
        if held.any():
            worst = deepest(dof)
    # frames the spreading left deeper than they were get their own pose back (tapered)
    for _ in range(3):
        worse = (worst < deep) & (worst < np.minimum(before, -target) - 0.01)
        if not worse.any():
            break
        keep = 1.0 - np.clip(2.0 * gaussian_filter1d(maximum_filter1d(worse.astype(float), 2 * spread + 1),
                                                     smooth_s * m.fps), 0.0, 1.0)
        dof = q0 + (dof - q0) * keep[:, None]
        worst = deepest(dof)
    unresolved: dict = {}  # pairs still deeper than the target, in frames
    for t in np.flatnonzero(worst < deep):
        S.pose(dof[t], t)
        for key in {" / ".join(sorted((S.body[b1], S.body[b2]))) for b1, b2, *_ in S.contacts(-deep)}:
            unresolved[key] = unresolved.get(key, 0) + 1

    change = np.degrees(np.abs(dof - q0))
    changed = (change > 0.1).any(1)
    info = {
        "target_cm": round(100 * target, 2),
        "rounds": done,
        "frames_changed": int(changed.sum()),
        # frames with robot parts (hands and feet included) deeper in each other than the target / than 3 cm
        "frames_deeper_than_target": {"before": int((before < deep).sum()), "after": int((worst < deep).sum())},
        "frames_deeper_than_3cm": {"before": int((before < -0.03).sum()), "after": int((worst < -0.03).sum())},
        "deepest_cm": {"before": round(max(0.0, -100 * float(before.min())), 2),
                       "after": round(max(0.0, -100 * float(worst.min())), 2)},
        "frames_made_deeper": int(((worst < before - 0.01) & (worst < deep)).sum()),
        "frames_leg_held_by_floor": int(held.sum()),
        "joint_change_deg": {"max": round(float(change.max()), 2),
                             "rms_changed_frames": round(float(np.sqrt((change[changed] ** 2).mean())), 2)
                             if changed.any() else 0.0},
        "unresolved_pairs": dict(sorted(unresolved.items(), key=lambda kv: -kv[1])[:5]),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    out = RobotMotion(name=m.name, joint_names=list(m.joint_names), root_pos=m.root_pos.copy(),
                      root_quat=m.root_quat.copy(), dof_pos=dof, fps=m.fps, source=m.source,
                      meta={**m.meta, "self_collision": info})
    return out, info


def retarget_file(path: str, robot: str = "unitree_g1", fmt: str = "auto", fps: float | None = 30.0,
                  up_axis: str = "y", ref: str | int = "auto", smpl_model_dir: str | None = None,
                  velocity_limit: bool = False, smooth_hz: float = 0.0, swing_clearance: float = 0.0,
                  foot_flat: bool = False, self_collision: bool = False, log=print) -> tuple[RobotMotion, dict]:
    """Retarget one human motion file. Returns the robot motion and a provenance dict.

    smooth_hz > 0 low-passes the result (:func:`smooth_motion`); 6 Hz is the tested
    setting. foot_flat then stands feet that stand still flat on the floor with the legs and
    pelvis height (:func:`flatten_stance_feet`), swing_clearance > 0 (meters) lifts swing feet that
    skim the floor (:func:`ensure_swing_clearance`), and self_collision pushes apart robot parts
    that go through each other, last (:func:`separate_self_collisions`). velocity_limit is GMR's own option: joint
    speeds of 3 pi rad/s over each IK iteration's model timestep (2 ms), not over the frame, so
    the IK falls behind fast motions (CMU 143_11: up to 34 deg, mean 1.1 deg off). It did nothing
    until 2026-10-28: the vendored GMR passed its limits to mink in the wrong argument.
    """
    log = log or (lambda *_: None)
    fmt = detect_format(path) if fmt == "auto" else fmt
    config, ground, cfg_info = None, 0.0, {}
    if fmt in ("tpose", "fbx", "smplx"):
        if fmt == "tpose":
            clip = load_bvh_tpose(path, up_axis=up_axis, ref=ref, fps=fps)
        elif fmt == "fbx":
            clip = load_fbx_tpose(path, ref=ref, fps=fps)
        else:
            clip = load_smplx_tpose(path, smpl_model_dir, fps=fps)
        config, ground, cfg_info = derive_tpose_config(robot, clip)
        src_human = f"{fmt}_derived"
    elif fmt in ("lafan1", "nokov"):
        clip = load_bvh_gmr(path, fmt, fps=fps)
        src_human = f"bvh_{fmt}"
    elif fmt == "smplx-gmr":
        clip = load_smplx_gmr(path, smpl_model_dir, fps=fps)
        src_human = "smplx"
    else:
        raise ValueError(f"unknown format {fmt!r}")
    log(f"{os.path.basename(path)}: {fmt}, {len(clip.frames)} frames @ {clip.fps:g} fps -> {robot}")
    t0 = time.perf_counter()
    qpos, track = run_gmr(clip, robot, src_human, config, ground, velocity_limit, log=log)
    elapsed = time.perf_counter() - t0

    name = os.path.splitext(os.path.basename(path))[0]
    model = robot_model(robot)
    joints = robot_joint_names(model)
    motion = qpos_to_motion(qpos, joints, clip.fps, name, os.path.abspath(path))
    resid = position_residuals(model, qpos, track)
    smoothing = None
    if smooth_hz:
        motion = smooth_motion(motion, smooth_hz, limits=robot_joint_ranges(model))
        smoothing = {**motion.meta["smoothing"], "ik_position_residual_before": resid}
        resid = position_residuals(model, np.concatenate([motion.root_pos, motion.root_quat, motion.dof_pos], 1), track)
    flat = None
    if foot_flat:
        motion, flat = flatten_stance_feet(motion, robot)
        if flat:
            flat["ik_position_residual_before"] = resid
            resid = position_residuals(model, np.concatenate([motion.root_pos, motion.root_quat, motion.dof_pos], 1),
                                       track)
    clearance = None
    if swing_clearance:
        motion, clearance = ensure_swing_clearance(motion, robot, clearance=swing_clearance)
        if clearance:
            clearance["ik_position_residual_before"] = resid
            resid = position_residuals(model, np.concatenate([motion.root_pos, motion.root_quat, motion.dof_pos], 1),
                                       track)
    separation = None
    if self_collision:  # last: it keeps standing legs still and moving feet off the floor, which a later pass could undo
        motion, separation = separate_self_collisions(motion, robot)
        if separation:
            separation["ik_position_residual_before"] = resid
            resid = position_residuals(model, np.concatenate([motion.root_pos, motion.root_quat, motion.dof_pos], 1),
                                       track)
    info = {
        "source": os.path.abspath(path),
        "source_format": fmt,
        "robot": robot,
        "retargeter": gmr_version(),
        "fps": clip.fps,
        "frames": len(qpos),
        "human_height_m": None if clip.height_m is None else round(clip.height_m, 3),
        **{k: v for k, v in clip.info.items() if not k.startswith("_")},
        **cfg_info,
        "ik_position_residual": resid,
        "smoothing": smoothing,
        "foot_flat": flat,
        "swing_clearance": clearance,
        "self_collision": separation,
        "ik_seconds": round(elapsed, 1),
        "root_quat": "wxyz",
    }
    if config is not None:
        info["ik_config"] = config
    motion.meta = {"format": "retarget", **info}
    return motion, info
