"""Synthetic motions for tests and for smoke-testing the Isaac Sim replay
without real mocap. Not meant to look natural."""

from __future__ import annotations

import numpy as np

from .io.robot import G1_29DOF_JOINTS
from .motion import RobotMotion

# name, parent, offset (cm, Y-up, character faces +Z, left = +X)
_SKELETON = [
    ("Hips", None, (0, 0, 0)),
    ("LeftUpLeg", "Hips", (9, -5, 0)),
    ("LeftLeg", "LeftUpLeg", (0, -42, 0)),
    ("LeftFoot", "LeftLeg", (0, -42, 0)),
    ("LeftToe", "LeftFoot", (0, -6, 12)),
    ("RightUpLeg", "Hips", (-9, -5, 0)),
    ("RightLeg", "RightUpLeg", (0, -42, 0)),
    ("RightFoot", "RightLeg", (0, -42, 0)),
    ("RightToe", "RightFoot", (0, -6, 12)),
    ("Spine", "Hips", (0, 10, 0)),
    ("Spine1", "Spine", (0, 20, 0)),
    ("Neck", "Spine1", (0, 20, 0)),
    ("Head", "Neck", (0, 10, 0)),
    ("LeftShoulder", "Spine1", (5, 18, 0)),
    ("LeftArm", "LeftShoulder", (12, 0, 0)),
    ("LeftForeArm", "LeftArm", (28, 0, 0)),
    ("LeftHand", "LeftForeArm", (25, 0, 0)),
    ("RightShoulder", "Spine1", (-5, 18, 0)),
    ("RightArm", "RightShoulder", (-12, 0, 0)),
    ("RightForeArm", "RightArm", (-28, 0, 0)),
    ("RightHand", "RightForeArm", (-25, 0, 0)),
]
_END_SITES = {"LeftToe": (0, 0, 5), "RightToe": (0, 0, 5), "Head": (0, 15, 0),
              "LeftHand": (8, 0, 0), "RightHand": (-8, 0, 0)}
_ROT = "Zrotation Xrotation Yrotation"


def walking_bvh_text(seconds: float = 6.0, fps: float = 60.0, speed_cm_s: float = 110.0) -> str:
    """A crude walk cycle as BVH text (cm, Y-up)."""
    children: dict[str, list[str]] = {}
    for name, parent, _ in _SKELETON:
        children.setdefault(parent, []).append(name)
    offsets = {n: o for n, _, o in _SKELETON}
    order: list[str] = []
    lines = ["HIERARCHY"]

    def emit(name: str, depth: int) -> None:
        ind = "  " * depth
        root = depth == 0
        lines.append(f"{ind}{'ROOT' if root else 'JOINT'} {name}")
        lines.append(f"{ind}{{")
        lines.append(f"{ind}  OFFSET {' '.join(f'{v:.4f}' for v in offsets[name])}")
        ch = f"6 Xposition Yposition Zposition {_ROT}" if root else f"3 {_ROT}"
        lines.append(f"{ind}  CHANNELS {ch}")
        order.append(name)
        for c in children.get(name, []):
            emit(c, depth + 1)
        if name in _END_SITES:
            lines.extend([f"{ind}  End Site", f"{ind}  {{",
                          f"{ind}    OFFSET {' '.join(f'{v:.4f}' for v in _END_SITES[name])}", f"{ind}  }}"])
        lines.append(f"{ind}}}")

    emit("Hips", 0)
    n = int(seconds * fps)
    t = np.arange(n) / fps
    phase = 2 * np.pi * 0.9 * t  # ~0.9 strides per second
    rot = {name: np.zeros((n, 3)) for name in order}  # (z, x, y) degrees per channel order
    rot["LeftUpLeg"][:, 1] = -25 * np.sin(phase)
    rot["RightUpLeg"][:, 1] = 25 * np.sin(phase)
    rot["LeftLeg"][:, 1] = 35 * np.clip(np.sin(phase + 1.2), 0, None)
    rot["RightLeg"][:, 1] = 35 * np.clip(np.sin(phase + 1.2 + np.pi), 0, None)
    rot["LeftArm"][:, 0] = -75  # arms down from T-pose
    rot["RightArm"][:, 0] = 75
    rot["LeftArm"][:, 1] = 20 * np.sin(phase)
    rot["RightArm"][:, 1] = -20 * np.sin(phase)
    rot["LeftForeArm"][:, 2] = -20
    rot["RightForeArm"][:, 2] = 20
    hips = np.stack([np.zeros(n), 95 - 2 * np.abs(np.sin(phase)), speed_cm_s * t], -1)

    lines += ["MOTION", f"Frames: {n}", f"Frame Time: {1.0 / fps:.8f}"]
    for i in range(n):
        vals = list(hips[i])
        for name in order:
            vals += list(rot[name][i])
        lines.append(" ".join(f"{v:.4f}" for v in vals))
    return "\n".join(lines) + "\n"


def g1_motion(seconds: float = 6.0, fps: float = 50.0, speed: float = 1.1) -> RobotMotion:
    """Small sinusoidal G1 (29-DoF) motion within joint limits. It walks like the
    synthetic BVH walker (towards -Y at the same speed), so the two read as a
    human clip and its retarget when replayed side by side."""
    n = int(seconds * fps)
    t = np.arange(n) / fps
    phase = 2 * np.pi * 0.9 * t
    q = np.zeros((n, len(G1_29DOF_JOINTS)))
    idx = {name: i for i, name in enumerate(G1_29DOF_JOINTS)}
    q[:, idx["left_hip_pitch_joint"]] = -0.1 - 0.35 * np.sin(phase)
    q[:, idx["right_hip_pitch_joint"]] = -0.1 + 0.35 * np.sin(phase)
    q[:, idx["left_knee_joint"]] = 0.3 + 0.4 * np.clip(np.sin(phase + 1.2), 0, None)
    q[:, idx["right_knee_joint"]] = 0.3 + 0.4 * np.clip(np.sin(phase + 1.2 + np.pi), 0, None)
    q[:, idx["left_ankle_pitch_joint"]] = -0.2
    q[:, idx["right_ankle_pitch_joint"]] = -0.2
    q[:, idx["left_shoulder_pitch_joint"]] = 0.3 * np.sin(phase)
    q[:, idx["right_shoulder_pitch_joint"]] = -0.3 * np.sin(phase)
    q[:, idx["left_shoulder_roll_joint"]] = 0.2
    q[:, idx["right_shoulder_roll_joint"]] = -0.2
    q[:, idx["left_elbow_joint"]] = 0.9
    q[:, idx["right_elbow_joint"]] = 0.9
    q[:, idx["waist_yaw_joint"]] = 0.1 * np.sin(phase)
    root_pos = np.stack([np.zeros(n), -speed * t, 0.76 + 0.01 * np.abs(np.sin(phase))], -1)
    root_quat = np.tile([np.cos(-np.pi / 4), 0.0, 0.0, np.sin(-np.pi / 4)], (n, 1))  # yaw -90: face -Y
    return RobotMotion("synthetic_g1_walk", list(G1_29DOF_JOINTS), root_pos, root_quat, q, fps,
                       meta={"format": "synthetic"})
