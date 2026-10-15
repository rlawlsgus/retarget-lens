"""Format-dispatching motion loader."""

from __future__ import annotations

import os

import numpy as np

from ..motion import RobotMotion, SkeletonMotion
from .bvh import load_bvh
from .c3d import load_c3d
from .robot import load_gmr_pkl, load_robot_npz, load_unitree_csv, urdf_joint_limits
from .smpl import load_amass_npz

MOTION_EXTENSIONS = (".bvh", ".c3d", ".npz", ".csv", ".pkl")

__all__ = [
    "MOTION_EXTENSIONS",
    "load_amass_npz",
    "load_bvh",
    "load_c3d",
    "load_gmr_pkl",
    "load_motion",
    "load_robot_npz",
    "load_unitree_csv",
    "urdf_joint_limits",
]


def load_motion(path: str, **kwargs) -> SkeletonMotion | RobotMotion:
    """Load any supported motion file.

    .bvh -> human skeleton, .c3d -> markers, .npz -> AMASS SMPL params or the
    project robot npz (decided by its keys), .csv -> Unitree retargeted robot
    motion, .pkl -> GMR robot motion. Extra kwargs go to the specific loader.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bvh":
        return load_bvh(path, **_pick(kwargs, "up_axis", "scale", "include_end_sites", "ground"))
    if ext == ".c3d":
        return load_c3d(path, **_pick(kwargs, "up_axis"))
    if ext == ".npz":
        with np.load(path, allow_pickle=False) as d:
            keys = set(d.files)
        if "dof_pos" in keys:
            return load_robot_npz(path)
        if "poses" in keys:
            return load_amass_npz(path, **_pick(kwargs, "model_dir", "gender", "body_only"))
        raise ValueError(f"{path}: unrecognised npz layout (keys: {sorted(keys)})")
    if ext == ".csv":
        return load_unitree_csv(path, **_pick(kwargs, "fps", "joint_names"))
    if ext == ".pkl":
        return load_gmr_pkl(path, **_pick(kwargs, "joint_names"))
    raise ValueError(f"unsupported motion file type: {ext}")


def _pick(kwargs: dict, *names: str) -> dict:
    return {k: kwargs[k] for k in names if kwargs.get(k) is not None}
