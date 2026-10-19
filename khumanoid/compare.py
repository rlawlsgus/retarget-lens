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

from . import analysis, paths
from .io import load_motion
from .io.bvh import load_bvh
from .io.fbx import load_fbx
from .io.smpl import load_amass_npz
from .motion import RobotMotion, SkeletonMotion
from .qc import QCConfig, add_balance_flags, check_robot

ROOT = paths.REPO_ROOT
CACHE = paths.cache_dir("retarget")  # dev: data/cache/retarget (not data/retargeted: QC reports scan that)
HUMAN_EXT = (".bvh", ".fbx")
ROBOT_EXT = (".csv", ".pkl")
MARKER_EXT = (".c3d",)  # raw optical markers: shown on the same take's retargeted robot
# bump when retargeting output changes for the same input and settings (invalidates the cache)
PIPELINE_VERSION = 3  # 2: CMU 60 Hz BVH timing; 3: SMPL-X via the derived T-pose config
MOTION_EXT = HUMAN_EXT + ROBOT_EXT + (".npz",) + MARKER_EXT
# folders the viewer lists motions from (dev: data/raw, data/samples, data/retargeted,
# data/uploads, reports; installed: see khumanoid.paths); uploads land in UPLOADS
LIBRARY_ROOTS = tuple(paths.library_roots())
UPLOADS = paths.uploads_dir()


def is_motion_file(path: str) -> bool:
    """A file the viewer can open: motion extensions, minus AMASS body-shape files
    (*_stagei.npz), anything under a cache folder, and report tables (only the
    physics results *_sim.npz count under the repository's reports/)."""
    rel = paths.rel(path, ROOT).replace(os.sep, "/").lower()
    name = os.path.basename(rel)
    if not name.endswith(MOTION_EXT) or name.endswith("_stagei.npz") or "/cache/" in f"/{rel}":
        return False
    return not rel.startswith("reports/") or name.endswith("_sim.npz")


def library_files(roots=None) -> dict[str, list[str]]:
    """{folder ('/'-separated, relative to the repository in the dev layout): sorted motion file
    paths} for the viewer's picker. roots: absolute, or relative to the repository."""
    out: dict[str, list[str]] = {}
    for root in LIBRARY_ROOTS if roots is None else roots:
        top = os.path.normpath(root if os.path.isabs(root) else os.path.join(ROOT, root))
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x.lower() != "cache")
            found = [os.path.join(d, f) for f in sorted(files) if is_motion_file(os.path.join(d, f))]
            if found:
                out[paths.rel(d, ROOT).replace(os.sep, "/")] = found
    return out


def save_upload(name: str, content: bytes, folder: str = UPLOADS) -> str:
    """Store a file picked in the browser under its own name (name_2, ... when a different
    file already has it; the same content reuses the earlier copy)."""
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(name) or "upload")
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem) or "upload"
    for n in range(1, 1000):
        path = os.path.join(folder, f"{stem}{'' if n == 1 else f'_{n}'}{ext.lower()}")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(content)
            return path
        with open(path, "rb") as f:
            if f.read() == content:
                return path
    raise RuntimeError(f"too many uploads named {name}")


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
    if path.lower().endswith(MARKER_EXT):
        return _load_marker_item(path, log=log, robot=robot, smooth=smooth, fps=fps, csv_fps=csv_fps,
                                 smpl_model_dir=smpl_model_dir, swing_clearance=swing_clearance)
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
        log(f"{name}: retarget from cache {paths.rel(cached)}")
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


def find_take(path: str, files: list[str] | None = None) -> str | None:
    """The same take's solved motion for a marker file: same name as BVH (first), FBX, or AMASS
    SMPL-X (<name>_stageii.npz / _poses.npz), from the library folders and the file's own folder.
    FBX converted from BVH (cmu_fbx_from_bvh) comes last."""
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    if files is None:
        files = [f for fs in library_files().values() for f in fs]
        here = os.path.dirname(os.path.abspath(path))
        files += [os.path.join(here, f) for f in os.listdir(here)]
    best = None
    for f in files:
        s, ext = os.path.splitext(os.path.basename(f).lower())
        rank = ({".bvh": 0, ".fbx": 1}.get(ext) if s == stem else
                2 if ext == ".npz" and s in (f"{stem}_stageii", f"{stem}_poses") else None)
        if rank is None:
            continue
        rank += 3 * ("from_bvh" in f.replace(os.sep, "/").lower())
        if best is None or rank < best[0]:
            best = (rank, os.path.abspath(f))
    return best[1] if best else None


def _load_marker_item(path: str, log, **opts) -> Item:
    """A C3D take: the robot from the same take's solved skeleton (retargeted, cached), the
    markers as its human part, turned into that skeleton's frame; marker QC in info['c3d']."""
    from .io.c3d import load_c3d
    from .markers import align_to_skeleton, marker_qc, marker_skeleton

    name = os.path.splitext(os.path.basename(path))[0]
    raw = load_c3d(path)
    match = find_take(path)
    if match is None:
        raise ValueError(f"{os.path.basename(path)}: C3D에는 마커만 있어 그대로는 로봇에 옮길 수 없습니다. 같은 촬영의 "
                         f"솔버 결과({name}.bvh / {name}.fbx / {name}_stageii.npz)를 data/raw 아래나 같은 폴더에 두면, "
                         f"그것을 리타게팅한 로봇 옆에 마커를 그립니다.")
    log(f"{name}: markers on the robot retargeted from {paths.rel(match)}")
    base = load_item(match, log=log, **opts)
    markers, fit = align_to_skeleton(marker_skeleton(raw), base.human)
    info = {**base.info, "c3d": {**marker_qc(raw), **fit}, "solved_motion": match}  # absolute path
    return Item(label=f"{os.path.basename(os.path.dirname(path))}/{name}", source=path,
                kind=f"C3D 마커 + {base.kind}", robot=base.robot, human=markers, info=info)


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
