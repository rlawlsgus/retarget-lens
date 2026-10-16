"""Human mocap -> humanoid robot retargeting with GMR (General Motion Retargeting).

GMR (MIT, github.com/YanjieZe/GMR) solves per-frame differential IK with mink
on a MuJoCo robot model. Install it with ``scripts/install_gmr.ps1``. GMR,
mujoco and scipy are imported inside functions, so ``khumanoid`` itself still
imports without them (e.g. from Isaac Sim's Python).

Source formats:
  ``lafan1`` / ``nokov``  GMR's own BVH loaders and IK configs, unchanged.
  ``tpose``   Any BVH whose reference pose is a T-pose: CMU (cgspeed conversion,
              frame 0) and the usual Vicon / OptiTrack / Xsens / Rokoko exports
              (rest pose). GMR ships no config for these skeletons, so one is
              derived per clip: GMR's LAFAN1 task list and weights for the
              robot, with rotation offsets, per-body scales and ground height
              computed from the T-pose and the robot model.
  ``fbx``     FBX skeleton animation (read with Blender, khumanoid.io.fbx) with
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
    try:
        with _quiet():
            import general_motion_retargeting as gmr
    except ImportError as e:
        raise ImportError("GMR is not installed. Run: powershell -File scripts\\install_gmr.ps1") from e
    return gmr


def gmr_version() -> str:
    """'gmr@<commit>' from the GMR_COMMIT.txt that install_gmr.ps1 writes."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(_gmr().__file__)))
    try:
        with open(os.path.join(root, "GMR_COMMIT.txt"), encoding="ascii") as f:
            for line in f:
                if line.startswith("commit:"):
                    return "gmr@" + line.split(":", 1)[1].strip()[:12]
    except OSError:
        pass
    return "gmr@unknown"


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
    Joint positions and frames come from khumanoid.io.smpl (numpy FK of the body
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


def load_bvh_gmr(path: str, fmt: str, fps: float | None = 30.0) -> HumanClip:
    """LAFAN1 / Nokov BVH through GMR's own loader (nearest-frame resampling)."""
    _gmr()
    from general_motion_retargeting.utils.lafan1 import load_bvh_file

    from .io.bvh import _parse

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        _, frame_time, _ = _parse(f.read())
    src_fps = 1.0 / frame_time
    with _quiet():
        frames, height = load_bvh_file(path, format=fmt)
    if fps and abs(fps - src_fps) > 1e-3 * src_fps:
        n = int(len(frames) / src_fps * fps)
        frames = [frames[min(int(round(k * src_fps / fps)), len(frames) - 1)] for k in range(n)]
    elif not fps:
        fps = src_fps  # else: same rate up to the rounded frame time, keep the requested value
    return HumanClip(frames=frames, fps=fps, fmt=fmt, height_m=height, info={"source_fps": src_fps})


def load_smplx_gmr(path: str, model_dir: str | None, fps: float | None = 30.0) -> HumanClip:
    """AMASS SMPL-X npz through GMR (body model: <model_dir>/smplx/SMPLX_<GENDER>.npz)."""
    model_dir = model_dir or os.environ.get("SMPL_MODEL_DIR")
    if not model_dir or not os.path.isdir(os.path.join(model_dir, "smplx")):
        raise FileNotFoundError(
            "SMPL-X retargeting needs the SMPL-X body model (licence-gated, https://smpl-x.is.tue.mpg.de): "
            "pass --smpl-model-dir or set SMPL_MODEL_DIR to the folder holding smplx/SMPLX_NEUTRAL.npz")
    _gmr()
    import smplx
    import torch
    from general_motion_retargeting.utils.smpl import get_smplx_data_offline_fast

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


def _robot_tpose(model, robot: str, ref_pose: dict, face: np.ndarray):
    """Robot qpos (root at origin, identity) whose limbs point like the human's."""
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

    # Refine each limb with all its joints at once: one axis per joint cannot follow a
    # limb that also points forward (SMPL-X zero pose: arms forward and down, knees
    # slightly bent). A small pull towards the 1-D solution keeps the free twist at 0.
    from scipy.optimize import minimize

    def body(name):
        return mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)

    refined = {}
    for joints, segments in TPOSE_LIMBS.get(robot, []):
        ids = [mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in joints]
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
            return c + 0.02 * float(np.sum((x - x0) ** 2))

        res = minimize(cost, x0, method="L-BFGS-B", bounds=bounds)
        q[adr] = res.x
        cost(res.x)
        for (r0, r1), (h0, h1) in segments:
            target = face.T @ (ref_pose[h1][0] - ref_pose[h0][0])
            refined[f"{r0}->{r1}"] = round(float(np.degrees(_angle(data.xpos[body(r1)] - data.xpos[body(r0)], target))), 1)
        for n, v in zip(joints, res.x):
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


def derive_tpose_config(robot: str, clip: HumanClip) -> tuple[dict, float, dict]:
    """GMR IK config for a T-pose BVH clip: (config, ground offset, info).

    Starts from GMR's LAFAN1 config of the robot (task list + weights) and replaces
    - rotation offsets: human frame at the reference T-pose -> robot body frame in
      the robot posed the same way (limb directions matched joint by joint);
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
    data, chosen = _robot_tpose(model, robot, ref, face)

    import mujoco as mj

    def body_pose(name):
        b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, name)
        return data.xpos[b].copy(), data.xmat[b].reshape(3, 3).copy()

    robot_of = {e[0]: frame for frame, e in cfg["ik_match_table1"].items()}  # human body -> robot body
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
    of mocap). See README "리타게팅" for how 6 Hz was chosen.
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


# Swing legs for ensure_swing_clearance: (foot body, leg joints hip -> ankle).
_G1_LEGS = [(f"{s}_ankle_roll_link",
             [f"{s}_{j}_joint" for j in ("hip_pitch", "hip_roll", "hip_yaw", "knee", "ankle_pitch", "ankle_roll")])
            for s in ("left", "right")]
SWING_LEGS = {"unitree_g1": _G1_LEGS, "unitree_g1_with_hands": _G1_LEGS}


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

    legs = SWING_LEGS.get(robot)
    T = m.num_frames
    if not legs or clearance <= 0 or T < 4:
        return m, {}
    model = robot_model(robot)
    data = mj.MjData(model)
    names = robot_joint_names(model)
    col = {n: i for i, n in enumerate(m.joint_names)}
    jid = {n: mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n) for n in names}
    lo, hi = robot_joint_ranges(model)
    rng = {n: (lo[i], hi[i]) for i, n in enumerate(names)}
    feet = []
    for body, joints in legs:
        b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, body)
        soles = [g for g in range(model.ngeom) if model.geom_bodyid[g] == b
                 and (model.geom_contype[g] or model.geom_conaffinity[g])]
        if b < 0 or not soles or any(j not in col for j in joints):
            return m, {}
        feet.append((b, soles, joints))
    G = max(len(f[1]) for f in feet)

    def set_pose(dof_row: np.ndarray, t: int) -> None:
        q = model.qpos0.copy()
        q[:3], q[3:7] = m.root_pos[t], m.root_quat[t]
        for n in names:
            if n in col:
                q[model.jnt_qposadr[jid[n]]] = dof_row[col[n]]
        data.qpos[:] = q

    def sole_points(dof: np.ndarray) -> np.ndarray:
        P = np.full((T, len(feet), G, 3), np.inf)
        for t in range(T):
            set_pose(dof[t], t)
            mj.mj_kinematics(model, data)
            for k, (_, soles, _) in enumerate(feet):
                P[t, k, :len(soles)] = [data.geom_xpos[g] - [0.0, 0.0, model.geom_size[g][0]] for g in soles]
        return P

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


def retarget_file(path: str, robot: str = "unitree_g1", fmt: str = "auto", fps: float | None = 30.0,
                  up_axis: str = "y", ref: str | int = "auto", smpl_model_dir: str | None = None,
                  velocity_limit: bool = False, smooth_hz: float = 0.0, swing_clearance: float = 0.0,
                  log=print) -> tuple[RobotMotion, dict]:
    """Retarget one human motion file. Returns the robot motion and a provenance dict.

    smooth_hz > 0 low-passes the result (:func:`smooth_motion`); 6 Hz is the tested
    setting. swing_clearance > 0 (meters) then lifts swing feet that skim the floor
    (:func:`ensure_swing_clearance`). velocity_limit is GMR's own option; it caps
    each IK iteration, not the per-frame change, and left the output unchanged on LAFAN1.
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
    clearance = None
    if swing_clearance:
        motion, clearance = ensure_swing_clearance(motion, robot, clearance=swing_clearance)
        if clearance:
            clearance["ik_position_residual_before"] = resid
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
        "swing_clearance": clearance,
        "ik_seconds": round(elapsed, 1),
        "root_quat": "wxyz",
    }
    if config is not None:
        info["ik_config"] = config
    motion.meta = {"format": "retarget", **info}
    return motion, info
