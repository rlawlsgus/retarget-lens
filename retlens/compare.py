"""Load motions of any supported format onto one robot, for comparison.

Shared by tools/compare_viewer.py (interactive) and tools/compare_report.py (batch).
Human motions (BVH, FBX, AMASS SMPL-X npz) are retargeted with retlens.retarget
and cached in data/cache/retarget/; robot motions (project npz, Unitree csv, GMR
pkl) are loaded as they are.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
from dataclasses import dataclass, field

import numpy as np

from . import analysis, objects, paths, problems
from .io import load_motion, npz_keys
from .io.bvh import load_bvh
from .io.fbx import load_fbx
from .io.smpl import load_amass_npz
from .motion import RobotMotion, SkeletonMotion
from .motion_labels import is_label_name
from .qc import QCConfig, add_balance_flags, check_robot

ROOT = paths.REPO_ROOT
CACHE = paths.cache_dir("retarget")  # dev: data/cache/retarget (not data/retargeted: QC reports scan that)
HUMAN_EXT = (".bvh", ".fbx")
ROBOT_EXT = (".csv", ".pkl")
MARKER_EXT = (".c3d",)  # raw optical markers: shown on the same take's retargeted robot
# bump when retargeting output changes for the same input and settings (invalidates the cache)
PIPELINE_VERSION = 9  # 2: CMU 60 Hz BVH timing; 3: SMPL-X via the derived T-pose config; 4: elbow / knee twist;
# 5: feet levelled from the clip's stance, foot-flat through legs and pelvis height; 6: the robot's
# parts from its model (robot_profile: joint centres, flex signs), any robot; 9: BVH names with spaces and a BOM,
# classic Biped chest / bare root bone, interpolated LAFAN1 / Nokov above the source fps, mesh / round sole points
MOTION_EXT = HUMAN_EXT + ROBOT_EXT + (".npz",) + MARKER_EXT
# folders the viewer lists motions from (dev: data/raw, data/samples, data/retargeted,
# data/uploads, reports; installed: see retlens.paths); uploads land in UPLOADS
LIBRARY_ROOTS = tuple(paths.library_roots())
UPLOADS = paths.uploads_dir()


def is_motion_file(path: str, entry: os.DirEntry | None = None) -> bool:
    """A file the viewer can open: motion extensions, minus AMASS body-shape files
    (*_stagei.npz), label files (*.labels.csv, retlens.motion_labels), anything under a cache
    folder, report tables (only the physics results *_sim.npz count under the repository's
    reports/) and .csv tables that are not a Unitree robot csv (a header or words: batch tables,
    dataset manifests, metadata; see _robot_csv). entry: the file's os.scandir entry when the
    caller lists a folder (its size and time come with the listing)."""
    rel = paths.rel(path, ROOT).replace(os.sep, "/").lower()
    name = os.path.basename(rel)
    if (not name.endswith(MOTION_EXT) or name.endswith("_stagei.npz") or is_label_name(name)
            or "/cache/" in f"/{rel}"):
        return False
    if name.endswith(".fbx"):
        from .props import is_prop_file

        if is_prop_file(path):  # props of a take, drawn with its people (retlens.props)
            return False
    if name.endswith(".csv") and not _robot_csv(path, entry):
        return False
    return not rel.startswith("reports/") or name.endswith("_sim.npz")


def _robot_csv(path: str, entry: os.DirEntry | None = None) -> bool:
    """A Unitree robot csv by its first line: no header, at least 8 numbers (root x y z, quaternion, a joint)."""
    try:
        st = os.stat(path) if entry is None else entry.stat()
    except OSError:
        return False
    return _numeric_first_line(os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=None)  # per csv version: a folder of thousands of csvs is read once, not per listing
def _numeric_first_line(path: str, stamp: int, size: int) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    for line in head.splitlines():
        line = line.split(b"#", 1)[0].strip()  # '#' comments, as np.loadtxt skips them (np.savetxt's header=)
        if line:
            cells = line.split(b",")
            try:
                return len(cells) >= 8 and all(np.isfinite(float(c)) for c in cells)
            except ValueError:
                return False
    return False


def library_files(roots=None) -> dict[str, list[str]]:
    """{folder ('/'-separated, relative to the repository in the dev layout): sorted motion file
    paths} for the viewer's picker. roots: absolute, or relative to the repository."""
    out: dict[str, list[str]] = {}
    for root in LIBRARY_ROOTS if roots is None else roots:
        top = os.path.normpath(root if os.path.isabs(root) else os.path.join(ROOT, root))
        for d, files in _walk(top):
            found = [e.path for e in files if is_motion_file(e.path, e)]
            if found:
                out[paths.rel(d, ROOT).replace(os.sep, "/")] = found
    return out


def _walk(top: str):
    """(folder, its files as os.DirEntry) like os.walk: top-down, names sorted, symlinked folders and cache
    folders not entered. The entries carry each file's size and time from the listing (no stat call per file)."""
    try:
        with os.scandir(top) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return
    files, dirs = [], []
    for e in entries:
        try:
            is_dir = e.is_dir()
        except OSError:
            is_dir = False
        (dirs if is_dir else files).append(e)
    yield top, files
    for e in dirs:
        if e.name.lower() != "cache" and not e.is_symlink():
            yield from _walk(e.path)


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


@dataclass(eq=False)  # one loaded motion: compared by identity (field equality would compare its arrays)
class Item:
    label: str
    source: str
    kind: str  # e.g. "BVH -> GMR, smooth 6 Hz", "Unitree csv"
    robot: RobotMotion
    human: SkeletonMotion | None = None
    info: dict = field(default_factory=dict)
    color: tuple = (110, 110, 110)
    offset: float = 0.0  # display time offset (s), see retlens.analysis
    visible: bool = True
    show_human: bool = True
    metrics: dict = field(default_factory=dict)
    balance: object = None  # retlens.stability.BalanceTrack (CoM / ZMP / support), set by compute_metrics
    handles: dict = field(default_factory=dict)  # viewer state
    retarget: dict = field(default_factory=dict)  # human inputs: the settings it was retargeted with
    labels: object = None  # retlens.motion_labels.MotionLabels: labelled time segments; None = no label file
    solved_human: SkeletonMotion | None = None  # C3D: the solved skeleton its robot was retargeted from (human = markers)


def measured_human(item: Item) -> SkeletonMotion | None:
    """The skeleton an item's numbers are measured against: its human skeleton, or for a C3D (human = markers) the
    solved skeleton its robot was retargeted from, whose objects and props its hand-object numbers use too."""
    return item.solved_human if item.solved_human is not None else item.human


def file_warnings(item: Item) -> list[str]:
    """What the motion file's reader left out (meta['warnings'], e.g. another person's skeleton in an FBX); for a
    C3D, its solved skeleton's."""
    h = measured_human(item)
    return list(h.meta.get("warnings") or []) if h is not None else []


def human_format(path: str) -> str | None:
    """'tpose' / 'fbx' / 'lafan1' / 'smplx' for human motion files, None for robot motion files."""
    from .retarget import detect_format

    ext = os.path.splitext(path)[1].lower()
    if ext in HUMAN_EXT:
        return detect_format(path)
    if ext == ".npz":
        keys = npz_keys(path)
        if "pose_body" in keys:
            return "smplx"
        if "dof_pos" in keys:
            return None
        raise ValueError(f"{os.path.basename(path)}: 로봇 npz(dof_pos)도 AMASS SMPL-X(pose_body)도 아닌 npz입니다")
    if ext in ROBOT_EXT:
        return None
    raise ValueError(f"{os.path.basename(path)}: 지원하지 않는 파일 형식입니다 (BVH / FBX / AMASS SMPL-X npz / C3D / "
                     "로봇 npz·csv·pkl)")


def cache_path(path: str, robot: str, smooth: float, fps: float, swing_clearance: float = 0.0,
               foot_flat: bool = False, self_collision: bool = False) -> str:
    """Where the retarget of `path` to `robot` (registry key or model path) with these settings
    is cached: keyed by the robot model's digest too, so an edited model retargets again."""
    from .robot_profile import load

    prof = load(robot)
    st = os.stat(path)
    key = [os.path.abspath(path), st.st_size, int(st.st_mtime), prof.digest, smooth, fps, PIPELINE_VERSION]
    if swing_clearance:  # appended only when on, so earlier cache entries stay valid
        key.append(["swing_clearance", swing_clearance])
    if foot_flat:
        key.append(["foot_flat", True])
    if self_collision:
        key.append(["self_collision", True])
    if prof.has_fingers():  # its fingers follow the person's (retlens.fingers): only robots with jointed fingers
        from .fingers import VERSION as FINGERS

        key.append(["fingers", FINGERS])
    key = json.dumps(key)
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(CACHE, f"{stem}_{h}_{prof.tag}.npz")


def load_item(path: str, robot: str = "unitree_g1", smooth: float = 6.0, fps: float = 30.0,
              csv_fps: float = 30.0, smpl_model_dir: str | None = None, swing_clearance: float = 0.0,
              foot_flat: bool = False, self_collision: bool = False, log=print) -> Item:
    """Robot motion as is, or human motion retargeted (cached) plus its skeleton.
    foot_flat stands feet that stand still flat on the floor (legs and pelvis height), swing_clearance
    (m) > 0 lifts skimming swing feet and self_collision pushes apart robot parts that go through
    each other, after retargeting (retlens.retarget.retarget_file)."""
    log = log or (lambda *_: None)
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.basename(os.path.dirname(path))
    if path.lower().endswith(MARKER_EXT):
        return _load_marker_item(path, log=log, robot=robot, smooth=smooth, fps=fps, csv_fps=csv_fps,
                                 smpl_model_dir=smpl_model_dir, swing_clearance=swing_clearance, foot_flat=foot_flat,
                                 self_collision=self_collision)
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
        elif "policy_replay" in info:  # tools/policy_replay.py result (balance on / off in MuJoCo)
            kind = f"MuJoCo 재생 · {info.get('controller_label') or info['policy_replay'].get('controller', '')}"
        return Item(label=f"{folder}/{name}", source=path, kind=kind, robot=m, info=info)

    from .retarget import retarget_file

    cached = cache_path(path, robot, smooth, fps, swing_clearance, foot_flat, self_collision)
    if os.path.isfile(cached) and os.path.isfile(cached[:-4] + ".json"):
        m = load_motion(cached)
        with open(cached[:-4] + ".json", encoding="utf-8") as f:
            info = json.load(f)
        log(f"{name}: retarget from cache {paths.rel(cached)}")
    else:
        log(f"{name}: retargeting ({fmt}) ...")
        m, info = retarget_file(path, robot=robot, fmt=fmt, fps=fps, smooth_hz=smooth, foot_flat=foot_flat,
                                swing_clearance=swing_clearance, self_collision=self_collision,
                                smpl_model_dir=smpl_model_dir, log=None)
        os.makedirs(CACHE, exist_ok=True)
        m.save_npz(cached)
        with open(cached[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False, default=float)
        m = load_motion(cached)
    human = load_skeleton(path, fmt, smpl_model_dir)
    for w in human.meta.get("warnings") or []:  # e.g. a second person's skeleton in the FBX, not read (retlens.io.fbx)
        log(f"{name}: {w}")
    for e in human.meta.get("props") or []:  # the take's prop files (retlens.props): say why one is not drawn
        if e.get("error"):
            log(f"{name}: 물체 파일 {os.path.basename(e['file'])}을(를) 읽지 못함: {e['error']}")
        elif e.get("overlap_pct") is not None and e["overlap_pct"] < 50:
            log(f"{name}: 물체 파일 {os.path.basename(e['file'])}의 시간이 모션과 {e['overlap_pct']:g}%만 겹침")
    label_fmt = {"tpose": "BVH", "fbx": "FBX", "lafan1": "BVH LAFAN1", "nokov": "BVH Nokov", "smplx": "SMPL-X"}[fmt]
    smooth_txt = f", smooth {smooth:g} Hz" if smooth else ""
    if foot_flat:
        smooth_txt += ", foot-flat"
    if swing_clearance:
        smooth_txt += f", swing >= {100 * swing_clearance:g} cm"
    if self_collision:
        smooth_txt += ", self-collision"
    return Item(label=f"{folder}/{name}", source=path, kind=f"{label_fmt} -> GMR{smooth_txt}", robot=m,
                human=human, info=info, retarget={"smooth_hz": smooth, "foot_flat": bool(foot_flat),
                                                  "swing_clearance_cm": round(100 * swing_clearance, 3),
                                                  "self_collision": bool(self_collision)})


def load_skeleton(path: str, fmt: str | None = None, smpl_model_dir: str | None = None,
                  props: bool = True) -> SkeletonMotion:
    """The human skeleton of a BVH / FBX / AMASS SMPL-X file, as drawn next to its robot. props: an FBX also gets
    the props its take has in a file of their own (retlens.props) among its objects."""
    fmt = fmt or human_format(path)
    if fmt == "smplx":
        return load_amass_npz(path, model_dir=smpl_model_dir or os.environ.get("SMPL_MODEL_DIR"), body_only=True)
    if fmt == "fbx":
        human = load_fbx(path)
        if props:
            from . import props as prop_files

            prop_files.attach(human)
        return human
    if fmt is None:
        raise ValueError(f"{os.path.basename(path)}: 사람 모션 파일이 아닙니다")
    return load_bvh(path)


def find_take(path: str, files: list[str] | None = None) -> str | None:
    """The same take's solved motion for a marker file: same name as BVH (first), FBX, or AMASS
    SMPL-X (<name>_stageii.npz / _poses.npz), from the file's own folder first, else the library
    folders (another session's take of the same name there never beats the one beside the C3D).
    FBX converted from BVH (cmu_fbx_from_bvh) comes last."""
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    here = os.path.dirname(os.path.abspath(path))
    if files is None:
        local = find_take(path, [os.path.join(here, f) for f in os.listdir(here)])
        if local is not None:  # one beside the C3D always wins: the motion folders need not be listed
            return local
        files = [f for fs in library_files().values() for f in fs]
    here = os.path.normcase(here)
    best = None
    for f in files:
        s, ext = os.path.splitext(os.path.basename(f).lower())
        rank = ({".bvh": 0, ".fbx": 1}.get(ext) if s == stem else
                2 if ext == ".npz" and s in (f"{stem}_stageii", f"{stem}_poses") else None)
        if rank is None:
            continue
        rank += 3 * ("from_bvh" in f.replace(os.sep, "/").lower())
        key = (os.path.normcase(os.path.dirname(os.path.abspath(f))) != here, rank)
        if best is None or key < best[0]:
            best = (key, os.path.abspath(f))
    return best[1] if best else None


# C3D pelvis markers this far (mean) from the solved skeleton's root: likely another take. A solve whose root is not
# at the pelvis-marker centre sits up to ~11 cm off on its own take (CMU FBX, the subject turning), another take's
# >= 25 cm; between 10 and 20 cm it is another take only when the lengths differ too (own takes: the same length)
TAKE_RESIDUAL_CM = 20.0
TAKE_LENGTH_RESIDUAL_CM = 10.0
TAKE_LENGTH_TOL = 0.05  # solve / markers length ratio this far from 1: not the same recording


def _take_warning(residual_cm: float, markers_s: float, solve_s: float, solve: str) -> str | None:
    """Why the solve found for a C3D is likely another take (TAKE_RESIDUAL_CM ...), or None."""
    if not np.isfinite(residual_cm):
        return None
    where = f"마커 골반이 솔버 결과({os.path.basename(solve)})의 골반과 평균 {residual_cm:.0f} cm 떨어져 있"
    if residual_cm > TAKE_RESIDUAL_CM:
        return f"{where}어 다른 촬영일 수 있습니다"
    if residual_cm > TAKE_LENGTH_RESIDUAL_CM and abs(solve_s / max(markers_s, 1e-6) - 1) > TAKE_LENGTH_TOL:
        return f"{where}고 길이도 달라(마커 {markers_s:.1f}초, 솔버 결과 {solve_s:.1f}초) 다른 촬영일 수 있습니다"
    return None


def _load_marker_item(path: str, log, **opts) -> Item:
    """A C3D take: the robot from the same take's solved skeleton (retargeted, cached; kept as
    solved_human, which its metrics measure against), the markers as its human part, turned into that
    skeleton's frame; marker QC in info['c3d'], with "solved_elsewhere" when the solve is not beside the
    C3D and "take_warning" when the markers' pelvis is far from the solve's (likely another take)."""
    from .io.c3d import load_c3d
    from .markers import align_to_skeleton, marker_qc, marker_skeleton

    name = os.path.splitext(os.path.basename(path))[0]
    raw = load_c3d(path)
    match = find_take(path)
    if match is None:
        raise ValueError(f"{os.path.basename(path)}: C3D에는 마커만 있어 그대로는 로봇에 옮길 수 없습니다. 같은 촬영의 "
                         f"솔버 결과({name}.bvh / {name}.fbx / {name}_stageii.npz)를 C3D와 같은 폴더에 두면, "
                         f"그것을 리타게팅한 로봇 옆에 마커를 그립니다.")
    log(f"{name}: markers on the robot retargeted from {paths.rel(match)}")
    base = load_item(match, log=log, **opts)
    markers, fit = align_to_skeleton(marker_skeleton(raw), base.human)
    c3d = {**marker_qc(raw), **fit}
    if os.path.normcase(os.path.dirname(match)) != os.path.normcase(os.path.dirname(path)):
        c3d["solved_elsewhere"] = True  # not beside the C3D: found in a motion folder by its name
        log(f"{name}: C3D 폴더에 같은 이름의 솔버 결과가 없어 모션 폴더의 {paths.rel(match)}을(를) 씁니다")
    warning = _take_warning(fit["residual_cm"], markers.duration, base.human.duration, match)
    if warning:
        c3d["take_warning"] = warning
        log(f"{name}: {warning}")
    info = {**base.info, "c3d": c3d, "solved_motion": match}  # absolute path
    return Item(label=f"{os.path.basename(os.path.dirname(path))}/{name}", source=path,
                kind=f"C3D 마커 + {base.kind}", robot=base.robot, human=markers, info=info, retarget=base.retarget,
                solved_human=base.human)


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
    flags = dict(fm.get("_frames", {}))
    human = measured_human(item)  # C3D: measured against its solved skeleton
    if fk is not None and human is not None and item.retarget:  # retargeted here: how well (retarget_quality)
        q = _retarget_quality(item, fk, out, human)
        flags.update(q.pop("_frames", {}))
        out.update(q)
        if human.objects:  # props captured with the person: does the robot's hand meet them (retlens.objects)
            try:
                out.update(objects.hand_object_metrics(human, m, fk))
            except Exception as e:  # a skeleton without hands to match: no contact numbers, the rest still works
                out["_objects"] = {"error": f"{type(e).__name__}: {e}"}
    if item.human is not None and item.human.kind == "markers":  # C3D: frames where a placed marker is missing
        P = item.human.positions[:, item.human.meta.get("dots") or slice(1, None)]  # not the virtual pelvis
        ok = np.isfinite(P).all(axis=2)
        flags["marker_gap"] = (~ok[:, ok.any(axis=0)].all(axis=1), item.human.fps)  # markers never seen do not count
    out["_problems"] = problems.problem_spans(flags, m.fps)  # where on the timeline (retlens.problems)
    from .diagnosis import cause_counts_text  # 물리: 넘어짐 원인 (falls per first cause, in the clip)

    phys = item.info.get("physics")
    if phys:  # from the Isaac run's json
        harness = (phys.get("harness_force_per_body_weight") or {}).get("mean")
        saturated = (phys.get("torque") or {}).get("saturated_frame_ratio")
        out["phys_harness_pct"] = float("nan") if harness is None else 100 * harness
        out["phys_falls"] = phys.get("falls")
        out["phys_saturated_pct"] = float("nan") if saturated is None else 100 * saturated
        out["phys_ok"] = "통과" if phys.get("consistent") else "; ".join(map(_issue_ko, phys.get("issues", []))) or "?"
        diags = phys.get("fall_diagnosis") or []  # the run keeps the first 20
        causes = cause_counts_text(diags)
        if causes and (phys.get("falls") or 0) > len(diags):
            causes += f" (앞 {len(diags)}회)"
        out["phys_fall_causes"] = causes or None
    pol = item.info.get("policy_replay")
    if pol:  # MuJoCo (tools/policy_replay.py, RetLens's 균형 제어): the harness, or none
        out["phys_harness_pct"] = 0.0
        out["phys_falls"] = pol.get("falls")
        out["phys_saturated_pct"] = 100 * pol.get("torque_saturated_ratio", float("nan"))
        if pol.get("torque_limits_missing"):  # joints the robot gives no torque limit (1000 N m): saturation not judged
            out["phys_torque_limits_missing"] = int(pol["torque_limits_missing"])
        out["phys_body_error_cm"] = pol.get("body_error_cm")
        out["phys_ok"] = "통과" if not pol.get("falls") else f"넘어짐 {pol['falls']}회"
        out["phys_fall_causes"] = cause_counts_text(pol.get("fall_diagnosis") or []) or None  # falls in the clip
        if pol.get("controller") == "harness":
            harness = (pol.get("harness_force_per_body_weight") or {}).get("mean")
            out["phys_harness_pct"] = float("nan") if harness is None else 100 * harness
            out["phys_ok"] = "통과" if pol.get("consistent") else "; ".join(map(_issue_ko, pol.get("issues", []))) or "?"
    item.metrics = out


def _retarget_quality(item: Item, fk: analysis.FootKinematics, metrics: dict,
                      human: SkeletonMotion | None = None) -> dict:
    """Quality numbers of a retarget against its human skeleton (default item.human), the 리타게팅 점수
    over them and the foot / balance metrics, and the details (``_quality``) inspectors show."""
    from . import retarget_quality as rq

    try:
        q = rq.measure(item.human if human is None else human, item.robot, fk.robot, fk.model)
    except Exception as e:  # a skeleton without the limbs to match: no score, the rest still works
        return {"_quality": {"error": f"{type(e).__name__}: {e}"}}
    if not q:
        return {}
    s, lost = rq.score({**metrics, **q})
    frames = q.pop("_frames", {})
    details = {k[1:]: v for k, v in q.items() if k.startswith("_")}
    return {**{k: v for k, v in q.items() if not k.startswith("_")}, "retarget_score": round(s, 1),
            "retarget_grade": f"{s:.0f} ({rq.grade(s)})", "_quality": {**details, "score_lost": dict(lost)},
            "_frames": frames}


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
