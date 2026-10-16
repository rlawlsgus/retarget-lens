"""Load motions of any supported format onto one robot, for comparison.

Shared by tools/compare_viewer.py (interactive) and tools/compare_report.py (batch).
Human motions (BVH, AMASS SMPL-X npz) are retargeted with khumanoid.retarget and
cached in data/cache/retarget/; robot motions (project npz, Unitree csv, GMR pkl)
are loaded as they are.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import numpy as np

from . import analysis
from .io import load_motion
from .io.bvh import load_bvh
from .io.smpl import load_amass_npz
from .motion import RobotMotion, SkeletonMotion
from .qc import QCConfig, check_robot

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CACHE = os.path.join(ROOT, "data", "cache", "retarget")  # not under data/retargeted: QC reports scan that
HUMAN_EXT = (".bvh",)
ROBOT_EXT = (".csv", ".pkl")
# bump when retargeting output changes for the same input and settings (invalidates the cache)
PIPELINE_VERSION = 3  # 2: CMU 60 Hz BVH timing; 3: SMPL-X via the derived T-pose config


@dataclass
class Item:
    label: str
    source: str
    kind: str  # e.g. "BVH -> GMR, smooth 6 Hz", "Unitree csv"
    robot: RobotMotion
    human: SkeletonMotion | None = None
    info: dict = field(default_factory=dict)
    color: tuple = (110, 110, 110)
    offset: float = 0.0  # display time offset (s), see khumanoid.analysis
    visible: bool = True
    show_human: bool = True
    metrics: dict = field(default_factory=dict)
    handles: dict = field(default_factory=dict)  # viewer state


def human_format(path: str) -> str | None:
    """'tpose' / 'lafan1' / 'smplx' for human motion files, None for robot motion files."""
    from .retarget import detect_format

    ext = os.path.splitext(path)[1].lower()
    if ext in HUMAN_EXT:
        return detect_format(path)
    if ext == ".npz":
        with np.load(path, allow_pickle=False) as d:
            keys = set(d.files)
        if "pose_body" in keys:
            return "smplx"
        if "dof_pos" in keys:
            return None
        raise ValueError(f"{path}: neither a robot npz (dof_pos) nor AMASS SMPL-X (pose_body)")
    if ext in ROBOT_EXT:
        return None
    raise ValueError(f"unsupported file type: {path}")


def cache_path(path: str, robot: str, smooth: float, fps: float) -> str:
    from .retarget import ROBOT_TAGS

    st = os.stat(path)
    key = json.dumps([os.path.abspath(path), st.st_size, int(st.st_mtime), robot, smooth, fps, PIPELINE_VERSION])
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(CACHE, f"{stem}_{h}_{ROBOT_TAGS.get(robot, robot)}.npz")


def load_item(path: str, robot: str = "unitree_g1", smooth: float = 6.0, fps: float = 30.0,
              csv_fps: float = 30.0, smpl_model_dir: str | None = None, log=print) -> Item:
    """Robot motion as is, or human motion retargeted (cached) plus its skeleton."""
    log = log or (lambda *_: None)
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.basename(os.path.dirname(path))
    fmt = human_format(path)
    if fmt is None:
        m = load_motion(path, fps=csv_fps)
        kind = {"robot_npz": "robot npz", "unitree_csv": "Unitree csv", "gmr_pkl": "GMR pkl"}.get(
            m.meta.get("format"), "robot")
        info_path = os.path.splitext(path)[0] + ".json"
        info = {}
        if os.path.isfile(info_path):
            with open(info_path, encoding="utf-8") as f:
                info = json.load(f)
        return Item(label=f"{folder}/{name}", source=path, kind=kind, robot=m, info=info)

    from .retarget import retarget_file

    cached = cache_path(path, robot, smooth, fps)
    if os.path.isfile(cached) and os.path.isfile(cached[:-4] + ".json"):
        m = load_motion(cached)
        with open(cached[:-4] + ".json", encoding="utf-8") as f:
            info = json.load(f)
        log(f"{name}: retarget from cache {os.path.relpath(cached, ROOT)}")
    else:
        log(f"{name}: retargeting ({fmt}) ...")
        m, info = retarget_file(path, robot=robot, fmt=fmt, fps=fps, smooth_hz=smooth,
                                smpl_model_dir=smpl_model_dir, log=None)
        os.makedirs(CACHE, exist_ok=True)
        m.save_npz(cached)
        with open(cached[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False, default=float)
        m = load_motion(cached)
    if fmt == "smplx":
        human = load_amass_npz(path, model_dir=smpl_model_dir or os.environ.get("SMPL_MODEL_DIR"), body_only=True)
    else:
        human = load_bvh(path)
    label_fmt = {"tpose": "BVH", "lafan1": "BVH LAFAN1", "nokov": "BVH Nokov", "smplx": "SMPL-X"}[fmt]
    smooth_txt = f", smooth {smooth:g} Hz" if smooth else ""
    return Item(label=f"{folder}/{name}", source=path, kind=f"{label_fmt} -> GMR{smooth_txt}", robot=m,
                human=human, info=info)


def compute_metrics(item: Item, fk: analysis.FootKinematics | None, limits) -> None:
    """Smoothness, foot contact (needs fk) and QC with the given joint limits into item.metrics."""
    m = item.robot
    out = {"duration": m.duration, "fps": m.fps, "frames": m.num_frames, **analysis.smoothness(m)}
    if fk is not None:
        out.update({k: v for k, v in analysis.foot_metrics(m, fk).items() if not k.startswith("_")})
    r = check_robot(m, QCConfig(), limits)
    out["qc"] = r.status
    out["qc_notes"] = "; ".join(r.notes)
    item.metrics = out
