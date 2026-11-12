"""Format-dispatching motion loader."""

from __future__ import annotations

import os

import numpy as np

from ..motion import RobotMotion, SkeletonMotion
from .bvh import load_bvh
from .c3d import load_c3d
from .fbx import load_fbx
from .robot import load_gmr_pkl, load_robot_npz, load_unitree_csv, urdf_joint_limits
from .smpl import load_amass_npz

MOTION_EXTENSIONS = (".bvh", ".fbx", ".c3d", ".npz", ".csv", ".pkl")

__all__ = [
    "MOTION_EXTENSIONS",
    "load_amass_npz",
    "load_bvh",
    "load_c3d",
    "load_fbx",
    "load_gmr_pkl",
    "load_motion",
    "load_robot_npz",
    "load_unitree_csv",
    "npz_keys",
    "urdf_joint_limits",
]


def load_motion(path: str, **kwargs) -> SkeletonMotion | RobotMotion:
    """Load any supported motion file.

    .bvh / .fbx -> human skeleton (FBX through Blender), .c3d -> markers, .npz ->
    AMASS SMPL params or the project robot npz (decided by its keys), .csv ->
    Unitree retargeted robot motion, .pkl -> GMR robot motion. Extra kwargs go to
    the specific loader.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bvh":
        return load_bvh(path, **_pick(kwargs, "up_axis", "scale", "include_end_sites", "ground"))
    if ext == ".fbx":
        return load_fbx(path, **_pick(kwargs, "scale", "ground", "take"))
    if ext == ".c3d":
        return load_c3d(path, **_pick(kwargs, "up_axis"))
    if ext == ".npz":
        keys = npz_keys(path)
        if "dof_pos" in keys:
            return load_robot_npz(path)
        if "poses" in keys:
            return load_amass_npz(path, **_pick(kwargs, "model_dir", "gender", "body_only"))
        raise ValueError(f"{os.path.basename(path)}: 모르는 npz 구성입니다 (로봇 npz도 AMASS도 아님, 배열: "
                         f"{', '.join(sorted(keys)) or '없음'})")
    if ext == ".csv":
        return load_unitree_csv(path, **_pick(kwargs, "fps", "joint_names"))
    if ext == ".pkl":
        return load_gmr_pkl(path, **_pick(kwargs, "joint_names"))
    raise ValueError(f"{os.path.basename(path)}: 지원하지 않는 모션 파일 형식입니다 ({ext or '확장자 없음'})")


def npz_keys(path: str) -> set[str]:
    """The array names in a .npz file. ValueError when it is not one (empty, cut short, or another kind of file)
    instead of numpy's advice to unpickle it."""
    try:
        d = np.load(path, allow_pickle=False)
    except FileNotFoundError:
        raise
    except Exception as e:  # not a zip (numpy then tries a pickle), a broken zip, an empty file
        raise ValueError(f"{os.path.basename(path)}: 올바른 .npz 모션 파일이 아닙니다 (비었거나 잘렸거나 다른 형식)") from e
    if not hasattr(d, "files"):  # a single .npy array under an .npz name
        raise ValueError(f"{os.path.basename(path)}: 올바른 .npz 모션 파일이 아닙니다 (배열 하나뿐인 .npy 형식)")
    with d:
        return set(d.files)


def _pick(kwargs: dict, *names: str) -> dict:
    return {k: kwargs[k] for k in names if kwargs.get(k) is not None}
