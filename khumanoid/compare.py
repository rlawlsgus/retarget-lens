"""Load motions of any supported format onto one robot, for comparison.

Shared by tools/compare_viewer.py (interactive) and tools/compare_report.py (batch).
Human motions (BVH, FBX, AMASS SMPL-X npz) are retargeted with khumanoid.retarget
and cached in data/cache/retarget/; robot motions (project npz, Unitree csv, GMR
pkl) are loaded as they are.
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
from .io.fbx import load_fbx
from .io.smpl import load_amass_npz
from .motion import RobotMotion, SkeletonMotion
from .qc import QCConfig, add_balance_flags, check_robot

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CACHE = os.path.join(ROOT, "data", "cache", "retarget")  # not under data/retargeted: QC reports scan that
HUMAN_EXT = (".bvh", ".fbx")
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
    balance: object = None  # khumanoid.stability.BalanceTrack (CoM / ZMP / support), set by compute_metrics
    handles: dict = field(default_factory=dict)  # viewer state


def human_format(path: str) -> str | None:
    """'tpose' / 'fbx' / 'lafan1' / 'smplx' for human motion files, None for robot motion files."""
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


def cache_path(path: str, robot: str, smooth: float, fps: float, swing_clearance: float = 0.0) -> str:
    from .retarget import ROBOT_TAGS

    st = os.stat(path)
    key = [os.path.abspath(path), st.st_size, int(st.st_mtime), robot, smooth, fps, PIPELINE_VERSION]
    if swing_clearance:  # appended only when on, so earlier cache entries stay valid
        key.append(["swing_clearance", swing_clearance])
    key = json.dumps(key)
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(CACHE, f"{stem}_{h}_{ROBOT_TAGS.get(robot, robot)}.npz")


def load_item(path: str, robot: str = "unitree_g1", smooth: float = 6.0, fps: float = 30.0,
              csv_fps: float = 30.0, smpl_model_dir: str | None = None, swing_clearance: float = 0.0,
              log=print) -> Item:
    """Robot motion as is, or human motion retargeted (cached) plus its skeleton.
    swing_clearance (m) > 0 lifts skimming swing feet after retargeting."""
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
        if "physics" in info:  # tools/isaac_replay.py --physics result
            kind = f"Isaac PhysX sim, harness x{info['physics'].get('harness_scale', 1):g}"
        return Item(label=f"{folder}/{name}", source=path, kind=kind, robot=m, info=info)

    from .retarget import retarget_file

    cached = cache_path(path, robot, smooth, fps, swing_clearance)
    if os.path.isfile(cached) and os.path.isfile(cached[:-4] + ".json"):
        m = load_motion(cached)
        with open(cached[:-4] + ".json", encoding="utf-8") as f:
            info = json.load(f)
        log(f"{name}: retarget from cache {os.path.relpath(cached, ROOT)}")
    else:
        log(f"{name}: retargeting ({fmt}) ...")
        m, info = retarget_file(path, robot=robot, fmt=fmt, fps=fps, smooth_hz=smooth,
                                swing_clearance=swing_clearance, smpl_model_dir=smpl_model_dir, log=None)
        os.makedirs(CACHE, exist_ok=True)
        m.save_npz(cached)
        with open(cached[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False, default=float)
        m = load_motion(cached)
    if fmt == "smplx":
        human = load_amass_npz(path, model_dir=smpl_model_dir or os.environ.get("SMPL_MODEL_DIR"), body_only=True)
    elif fmt == "fbx":
        human = load_fbx(path)
    else:
        human = load_bvh(path)
    label_fmt = {"tpose": "BVH", "fbx": "FBX", "lafan1": "BVH LAFAN1", "nokov": "BVH Nokov", "smplx": "SMPL-X"}[fmt]
    smooth_txt = f", smooth {smooth:g} Hz" if smooth else ""
    if swing_clearance:
        smooth_txt += f", swing >= {100 * swing_clearance:g} cm"
    return Item(label=f"{folder}/{name}", source=path, kind=f"{label_fmt} -> GMR{smooth_txt}", robot=m,
                human=human, info=info)


def compute_metrics(item: Item, fk: analysis.FootKinematics | None, limits) -> None:
    """Smoothness, foot contact (needs fk) and QC with the given joint limits into item.metrics."""
    m = item.robot
    out = {"duration": m.duration, "fps": m.fps, "frames": m.num_frames, **analysis.smoothness(m)}
    fm = analysis.foot_metrics(m, fk) if fk is not None else {}
    out.update({k: v for k, v in fm.items() if not k.startswith("_")})
    item.balance = fm.get("_balance")
    r = check_robot(m, QCConfig(), limits)
    if "_static_unbalanced" in fm:
        add_balance_flags(r, fm["_static_unbalanced"])
    out["qc"] = r.status
    out["qc_notes"] = "; ".join(r.notes)
    phys = item.info.get("physics")
    if phys:  # from the Isaac run's json
        harness = (phys.get("harness_force_per_body_weight") or {}).get("mean")
        saturated = (phys.get("torque") or {}).get("saturated_frame_ratio")
        out["phys_harness_pct"] = float("nan") if harness is None else 100 * harness
        out["phys_falls"] = phys.get("falls")
        out["phys_saturated_pct"] = float("nan") if saturated is None else 100 * saturated
        out["phys_ok"] = "통과" if phys.get("consistent") else "; ".join(map(_issue_ko, phys.get("issues", []))) or "?"
    item.metrics = out


def _issue_ko(text: str) -> str:
    """Korean label of an issue string written by tools/isaac_replay.py --physics."""
    import re

    m = re.match(r"(\d+) fall", text)
    if m:
        return f"넘어짐 {m.group(1)}회"
    m = re.match(r"harness > (\S+) body weight in (\S+) of frames", text)
    if m:
        return f"보조 힘 > 체중 {m.group(1)}: 프레임 {m.group(2)}"
    m = re.match(r"torque limits exceeded in (\S+) of frames", text)
    if m:
        return f"토크 한계 초과: 프레임 {m.group(1)}"
    return text
