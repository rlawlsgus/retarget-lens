"""Retargeted robot-motion readers and URDF joint-limit parsing."""

from __future__ import annotations

import os
import pickle
import re
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
    meta = {"format": "robot_npz"}
    ident = {k: str(d[f"robot_{k}"]) for k in ("name", "digest") if f"robot_{k}" in d.files}
    if ident:  # which robot the motion is for (files written before 0.9 do not say)
        meta["robot_ident"] = ident
    return RobotMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=[str(n) for n in d["joint_names"]],
        root_pos=d["root_pos"].astype(np.float64),
        root_quat=quat_normalize(d["root_quat_wxyz"].astype(np.float64)),
        dof_pos=d["dof_pos"].astype(np.float64),
        fps=float(d["fps"]),
        source=os.path.abspath(path),
        meta=meta,
    )


def load_unitree_csv(path: str, fps: float = 30.0, joint_names: list[str] | None = None) -> RobotMotion:
    """Unitree retargeted csv: x y z qx qy qz qw, then joint angles (no header)."""
    import warnings

    name = os.path.basename(path)
    not_robot = f"{name}: Unitree 로봇 csv가 아닙니다 (줄마다 숫자만 8개 이상: 루트 x y z, 쿼터니언 x y z w, 관절각)"
    try:
        with warnings.catch_warnings():  # an empty file: numpy warns, then the shape check below says what is wrong
            warnings.simplefilter("ignore", UserWarning)
            a = np.loadtxt(path, delimiter=",", dtype=np.float64, ndmin=2)
    except ValueError as e:
        msg = str(e)
        cut = re.search(r"number of columns changed from (\d+) to (\d+) at row (\d+)", msg)  # numpy: rows from 1
        if cut:  # a robot csv whose later row is short: cut off while it was written or copied
            raise ValueError(f"{name}: {_csv_line(path, int(cut[3]) - 1)}번째 줄의 열이 {cut[2]}개로 앞 줄들({cut[1]}개)과 "
                             f"다릅니다. 파일이 중간에 잘렸을 수 있음") from e
        bad = re.search(r"could not convert string (.*) to \S+ at row (\d+), column (\d+)", msg)  # rows from 0
        if bad and int(bad[2]) > 0:  # the first row is numbers: a broken row further down, not another kind of table
            raise ValueError(f"{name}: {_csv_line(path, int(bad[2]))}번째 줄 {bad[3]}번째 칸({bad[1]})을 숫자로 읽지 "
                             f"못했습니다. 파일이 잘렸거나 손상되었을 수 있음") from e
        raise ValueError(f"{not_robot}; 머리글이나 글자가 있음") from e  # a header or words: another kind of table
    if a.ndim != 2 or a.shape[0] == 0 or a.shape[1] < 8:
        raise ValueError(not_robot if a.size else f"{os.path.basename(path)}: 빈 csv입니다")
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


def _csv_line(path: str, row: int) -> int:
    """The file's line number (from 1) of np.loadtxt's data row `row` (from 0): its rows skip empty lines and lines
    that start with '#' (np.savetxt's header=); a line of spaces is a row."""
    left = row
    try:
        with open(path, "rb") as f:
            for n, line in enumerate(f, 1):
                if line.rstrip(b"\r\n").split(b"#", 1)[0]:
                    if left == 0:
                        return n
                    left -= 1
    except OSError:
        pass
    return row + 1


def load_gmr_pkl(path: str, joint_names: list[str] | None = None) -> RobotMotion:
    """GMR (General Motion Retargeting) output pickle.

    Only open pickles you produced yourselves: unpickling runs arbitrary code.
    """
    with open(path, "rb") as f:
        try:  # anything else (text, an empty or cut file, another pickle): a clear ValueError, not the unpickler's
            d = pickle.load(f)
            dof = np.asarray(d["dof_pos"], dtype=np.float64)
            q_xyzw = np.asarray(d["root_rot"], dtype=np.float64)
            root_pos = np.asarray(d["root_pos"], dtype=np.float64)
            fps = float(d.get("fps", 30.0))
            if dof.ndim != 2 or q_xyzw.shape != (len(dof), 4) or root_pos.shape != (len(dof), 3):
                raise ValueError(f"shapes dof_pos {dof.shape}, root_rot {q_xyzw.shape}, root_pos {root_pos.shape}")
        except OSError:
            raise
        except Exception as e:
            raise ValueError(f"{os.path.basename(path)}: GMR pkl 모션 파일이 아닙니다 (비었거나 잘렸거나 다른 형식: "
                             f"dof_pos / root_rot / root_pos 배열이 필요)") from e
    return RobotMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=_names_for(dof.shape[1], joint_names),
        root_pos=root_pos,
        root_quat=quat_normalize(q_xyzw[:, [3, 0, 1, 2]]),
        dof_pos=dof,
        fps=fps,
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
