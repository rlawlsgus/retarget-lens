"""Retargeted robot-motion readers and URDF joint-limit parsing."""

from __future__ import annotations

import os
import pickle
import xml.etree.ElementTree as ET

import numpy as np

from ..motion import RobotMotion
from ..rotations import quat_normalize

# Joint order of Unitree's LAFAN1_Retargeting_Dataset csv files (Hugging Face),
# which is also the MJCF joint order GMR uses for the G1.
G1_29DOF_JOINTS = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint", "left_knee_joint",
    "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint", "right_knee_joint",
    "right_ankle_pitch_joint", "right_ankle_roll_joint",
    "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint", "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint",
    "right_elbow_joint", "right_wrist_roll_joint", "right_wrist_pitch_joint", "right_wrist_yaw_joint",
]
H1_19DOF_JOINTS = [
    "left_hip_yaw_joint", "left_hip_roll_joint", "left_hip_pitch_joint", "left_knee_joint",
    "left_ankle_joint",
    "right_hip_yaw_joint", "right_hip_roll_joint", "right_hip_pitch_joint", "right_knee_joint",
    "right_ankle_joint",
    "torso_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint",
    "right_elbow_joint",
]
_DEFAULT_NAMES_BY_DOF = {29: G1_29DOF_JOINTS, 19: H1_19DOF_JOINTS}


def _names_for(n_dof: int, joint_names: list[str] | None) -> list[str]:
    if joint_names is not None:
        if len(joint_names) != n_dof:
            raise ValueError(f"{len(joint_names)} joint names given for {n_dof} DoF")
        return list(joint_names)
    return list(_DEFAULT_NAMES_BY_DOF.get(n_dof, [f"dof_{i}" for i in range(n_dof)]))


def load_robot_npz(path: str) -> RobotMotion:
    """The project's canonical robot-motion file (see RobotMotion.save_npz)."""
    d = np.load(path, allow_pickle=False)
    return RobotMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=[str(n) for n in d["joint_names"]],
        root_pos=d["root_pos"].astype(np.float64),
        root_quat=quat_normalize(d["root_quat_wxyz"].astype(np.float64)),
        dof_pos=d["dof_pos"].astype(np.float64),
        fps=float(d["fps"]),
        source=os.path.abspath(path),
        meta={"format": "robot_npz"},
    )


def load_unitree_csv(path: str, fps: float = 30.0, joint_names: list[str] | None = None) -> RobotMotion:
    """Unitree retargeted csv: x y z qx qy qz qw, then joint angles (no header)."""
    a = np.loadtxt(path, delimiter=",", dtype=np.float64, ndmin=2)
    q_xyzw = a[:, 3:7]
    return RobotMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=_names_for(a.shape[1] - 7, joint_names),
        root_pos=a[:, :3],
        root_quat=quat_normalize(q_xyzw[:, [3, 0, 1, 2]]),
        dof_pos=a[:, 7:],
        fps=fps,
        source=os.path.abspath(path),
        meta={"format": "unitree_csv"},
    )


def load_gmr_pkl(path: str, joint_names: list[str] | None = None) -> RobotMotion:
    """GMR (General Motion Retargeting) output pickle.

    Only open pickles you produced yourselves: unpickling runs arbitrary code.
    """
    with open(path, "rb") as f:
        d = pickle.load(f)
    dof = np.asarray(d["dof_pos"], dtype=np.float64)
    q_xyzw = np.asarray(d["root_rot"], dtype=np.float64)
    return RobotMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=_names_for(dof.shape[1], joint_names),
        root_pos=np.asarray(d["root_pos"], dtype=np.float64),
        root_quat=quat_normalize(q_xyzw[:, [3, 0, 1, 2]]),
        dof_pos=dof,
        fps=float(d.get("fps", 30.0)),
        source=os.path.abspath(path),
        meta={"format": "gmr_pkl"},
    )


def urdf_joint_limits(urdf_path: str) -> dict[str, tuple[float, float, float]]:
    """name -> (lower, upper, max_velocity) for revolute/prismatic joints."""
    limits = {}
    for j in ET.parse(urdf_path).getroot().iter("joint"):
        if j.get("type") not in ("revolute", "prismatic"):
            continue
        lim = j.find("limit")
        if lim is None:
            continue
        limits[j.get("name")] = (
            float(lim.get("lower", "-inf")),
            float(lim.get("upper", "inf")),
            float(lim.get("velocity", "inf")),
        )
    return limits
