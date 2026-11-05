"""데이터셋 내보내기 (묶기) and 구간 잘라 내보내기: the robot motions of a capture's folders, the ones that
pass, written into one folder with their labels and a manifest, for training on them.

    ex = Exporter(batch.BatchOptions(robot="unitree_g1", physics=True), ExportOptions(cut=CutOptions()), "out")
    manifest = ex.run(["D:/mocap/s01", "D:/mocap/s02"], progress=lambda done, total, name: ..., cancel=lambda: False)

Per motion file (in the order of retlens.batch.motion_files):
  - its 일괄 처리 row (retlens.batch: cached, so a folder measured before is quick): QC, 리타게팅 점수,
    the problem spans, the QC frames that cannot be used and, with physics, the falls of the MuJoCo harness check
  - left out (with the reason, in the manifest) when it cannot be read, is for another robot, is a second file of
    the same take in the same folder (X.bvh and X.c3d: the first of TAKE_ORDER goes), or fails the criteria:
    QC worse than ExportOptions.qc, 리타게팅 점수 below min_score, falls (unless allow_falls, or cut out)
  - with cut (CutOptions): the spans to cut (QC frames that cannot be used, the chosen problem kinds, the time
    around each fall) come out and the motion falls into pieces; pieces shorter than min_piece_s are dropped,
    the rest checked by QC again (each must pass ExportOptions.qc)
  - each motion or piece written as <out>/<its folder below the inputs>/<name>.<format> (+ .labels.csv, + .json):
    the whole motion as <stem>, a piece as <stem>_<start>-<end>s (seconds of the source)

The manifest (manifest.json + manifest.csv, a line per written motion) says what went in and how: RetLens's
version, the robot (name, model digest, joint order), the retargeting settings, the criteria and cut options, every
written motion (source file and its sha256, range in the source, QC, score, labels) and every motion left out and
why. A folder exported before is cleaned of the files its manifest lists first (nothing else is removed).

Formats (FORMATS): npz (RetLens's robot motion, RobotMotion.save_npz), csv (x y z qx qy qz qw then the joints in
the robot's order, no header: the Unitree / LAFAN1 retarget layout) and pkl (GMR's, root_rot xyzw).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np

from . import __version__

EXPORT_VERSION = 1
MANIFEST, MANIFEST_CSV = "manifest.json", "manifest.csv"
FORMATS = {"npz": "RetLens npz", "csv": "csv (x y z qx qy qz qw + 관절각, 머리글 없음)", "pkl": "GMR pkl"}
# retlens.problems kinds cut by default: a foot under the floor and C3D marker gaps. Not self-collision: brief hand-
# to-hip touches would cut a walk into pieces too short to keep (자기 관통 보정 fixes those instead); not slip, swing
# foot or a joint resting at its limit, which a usable motion has here and there.
CUT_KINDS = ("penetration", "marker_gap")
QC_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}
TAKE_ORDER = (".bvh", ".fbx", ".npz", ".csv", ".pkl", ".c3d")  # one file per take and folder: the first of these
CUT_NAMES = {"qc": "QC 못 쓰는 프레임", "fall": "물리 넘어짐", "range": "범위 밖"}  # + retlens.problems.KINDS


@dataclass
class CutOptions:
    """What 구간 잘라 내기 takes out of a motion. Spans are widened by pad_s on both sides; a fall takes
    fall_before_s before it to fall_after_s after it (the replay resets there); pieces shorter than min_piece_s
    (QC's shortest usable clip) are dropped."""
    qc: bool = True  # the frames QC cannot use (NaN, beyond a joint's limit or speed, fallen pose)
    kinds: tuple[str, ...] = CUT_KINDS  # retlens.problems kinds
    falls: bool = True  # the MuJoCo harness check's falls (with physics on)
    pad_s: float = 0.1
    min_piece_s: float = 1.0
    fall_before_s: float = 1.0
    fall_after_s: float = 0.25

    def describe(self) -> str:
        from .problems import KINDS

        what = (["QC 못 쓰는 프레임"] if self.qc else []) + [KINDS[k][0] for k in self.kinds if k in KINDS] + \
            ([f"넘어짐 {self.fall_before_s:g}초 전–{self.fall_after_s:g}초 뒤"] if self.falls else [])
        return f"{', '.join(what) or '없음'} (여유 {self.pad_s:g}초, {self.min_piece_s:g}초보다 짧은 조각은 뺌)"


@dataclass
class ExportOptions:
    qc: str = "WARN"  # the worst QC let in: PASS (PASS only), WARN (PASS and WARN) or FAIL (all)
    min_score: float | None = None  # 리타게팅 점수 at least this (None: any)
    allow_falls: bool = False  # keep motions that fell in the physics check (when falls are not cut out)
    cut: CutOptions | None = None  # 문제 구간 잘라 내기
    formats: tuple[str, ...] = ("npz",)
    labels: bool = True  # each motion's labels as <name>.labels.csv
    range_s: tuple[float, float] | None = None  # one motion: only this time range of it (seconds)


# ------------------------------------------------------------------ cutting
def cut_mask(frames: int, fps: float, spans: list[tuple[float, float, str]], pad_s: float = 0.0) -> np.ndarray:
    """(T,) bool: the frames inside any of the spans (start_s, end_s, kind), each widened by pad_s. A span
    holds the frames from start to before end (retlens.problems), so a frame is cut when start <= t < end."""
    m = np.zeros(frames, dtype=bool)
    for a, b, _k in spans:
        i0 = max(0, int(np.floor((a - pad_s) * fps + 1e-6)))
        i1 = min(frames, int(np.ceil((b + pad_s) * fps - 1e-6)))
        if i1 > i0:
            m[i0:i1] = True
    return m


def kept_ranges(mask: np.ndarray, fps: float, min_s: float) -> tuple[list[tuple[int, int]], int]:
    """([(first frame, frame after the last)] of the runs not cut that last min_s or longer, frames dropped as
    too short)."""
    keep = ~np.asarray(mask, dtype=bool)
    d = np.diff(np.concatenate([[0], keep.astype(np.int8), [0]]))
    runs = list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))
    need = int(np.ceil(min_s * fps - 1e-6))
    out = [(a, b) for a, b in runs if b - a >= max(1, need)]
    return out, sum(b - a for a, b in runs) - sum(b - a for a, b in out)


def cut_spans(duration: float, cut: CutOptions, qc_bad=(), problems: dict | None = None, falls=()) -> list:
    """[(start_s, end_s, kind)] to take out of a motion by the cut options: QC frames that cannot be used ("qc"),
    the problem kinds asked for, and the time around each fall inside the motion ("fall")."""
    out = [(a, b, "qc") for a, b in qc_bad] if cut.qc else []
    for k in cut.kinds:
        out += [(a, b, k) for a, b in (problems or {}).get(k, ())]
    if cut.falls:
        out += [(t - cut.fall_before_s, t + cut.fall_after_s, "fall") for t in falls if 0.0 <= t <= duration]
    return sorted(out)


def qc_bad_spans(robot, limits) -> list[tuple[float, float]]:
    """Where QC's hard flags hold (frames it cannot use: NaN, a joint beyond its limit or speed, fallen pose),
    every frame counted (retlens.problems.spans without the shortest-run filter)."""
    from .problems import spans
    from .qc import QCConfig, check_robot

    return spans(check_robot(robot, QCConfig(), limits).hard_mask(), robot.fps, min_s=0.0)


def pieces(frames: int, fps: float, cut: CutOptions | None, spans: list, range_s=None) -> dict:
    """{"ranges": [(i0, i1)], "cut_s": seconds taken out by the spans (and range), "short_s": seconds dropped as
    pieces too short, "by_kind": {kind: seconds}} of a motion of `frames` frames."""
    spans = list(spans) if cut is not None else []
    cut_by = cut_mask(frames, fps, spans, cut.pad_s if cut is not None else 0.0)
    outside = np.zeros(frames, dtype=bool)
    lo, hi = 0.0, frames / fps
    if range_s is not None:  # the range itself is exact (no pad)
        lo, hi = max(0.0, float(range_s[0])), min(frames / fps, float(range_s[1]))
        if hi <= lo:
            raise ValueError(f"시간 범위가 비었습니다: {range_s[0]:g}–{range_s[1]:g}초 (모션 길이 {frames / fps:.2f}초)")
        outside = cut_mask(frames, fps, [(-1.0, lo, "range"), (hi, frames / fps + 1.0, "range")])
    ranges, short = kept_ranges(cut_by | outside, fps, cut.min_piece_s if cut is not None else 0.0)
    by_kind: dict[str, float] = {}
    for a, b, k in spans:  # seconds per kind inside the range (before the pad; overlaps counted in each)
        by_kind[k] = round(by_kind.get(k, 0.0) + max(0.0, min(b, hi) - max(a, lo)), 3)
    return {"ranges": ranges, "cut_s": round(int((cut_by & ~outside).sum()) / fps, 3), "short_s": round(short / fps, 3),
            "by_kind": {k: v for k, v in by_kind.items() if v > 0}}


def slice_motion(m, i0: int, i1: int):
    """Frames i0 to before i1 of a robot motion, as a motion of its own (meta: where it was in the source)."""
    from .motion import RobotMotion

    meta = {**m.meta, "source_start_s": round(i0 / m.fps, 4), "source_end_s": round(i1 / m.fps, 4)}
    return RobotMotion(name=m.name, joint_names=list(m.joint_names), root_pos=m.root_pos[i0:i1].copy(),
                       root_quat=m.root_quat[i0:i1].copy(), dof_pos=m.dof_pos[i0:i1].copy(), fps=m.fps,
                       source=m.source, meta=meta)


def slice_labels(lab, start: float, end: float, path: str = ""):
    """The segments of labels inside [start, end), cut at its ends and moved to start at 0."""
    from .motion_labels import MotionLabels, Segment

    segs = []
    for s in lab.segments if lab is not None else []:
        a, b = max(s.start, start), min(s.end, end)
        if b - a > 1e-6:
            segs.append(Segment(s.label, a - start, b - start, s.track, s.name, s.note, s.color))
    return MotionLabels(path=path, segments=segs)


def label_seconds(lab) -> dict[str, float]:
    """{"track: label" (or the label): seconds} of labels."""
    out: dict[str, float] = {}
    for s in lab.segments if lab is not None else []:
        key = f"{s.track}: {s.label}" if s.track else s.label
        out[key] = round(out.get(key, 0.0) + max(0.0, s.end - s.start), 3)
    return out


def write_motion(m, base: str, formats=("npz",)) -> list[str]:
    """The motion as <base>.<format> for each format; the files written."""
    os.makedirs(os.path.dirname(os.path.abspath(base)) or ".", exist_ok=True)
    out = []
    for fmt in formats:
        path = f"{base}.{fmt}"
        if fmt == "npz":
            m.save_npz(path)
        elif fmt == "csv":  # x y z qx qy qz qw, joints (the Unitree / LAFAN1 retarget csv)
            q = np.asarray(m.root_quat)[:, [1, 2, 3, 0]]
            np.savetxt(path, np.hstack([m.root_pos, q, m.dof_pos]), delimiter=",", fmt="%.6f")
        elif fmt == "pkl":
            from .retarget import save_gmr_pkl

            save_gmr_pkl(m, path)
        else:
            raise ValueError(f"모르는 형식: {fmt} (npz, csv, pkl)")
        out.append(os.path.abspath(path))
    return out


def piece_name(stem: str, i0: int, i1: int, frames: int, fps: float) -> str:
    """<stem> for the whole motion, <stem>_<start>-<end>s for a piece of it."""
    return stem if (i0, i1) == (0, frames) else f"{stem}_{i0 / fps:.2f}-{i1 / fps:.2f}s"


def sha256(path: str) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


# ------------------------------------------------------------------ file layout
def _folder_below(d: str) -> str:
    """A folder as a relative path, its drive or network share a folder of its own:
    C:\\mocap\\s01 -> C\\mocap\\s01, \\\\nas\\mocap\\s01 -> nas_mocap\\s01."""
    drive, rest = os.path.splitdrive(d)
    drive = drive.replace(":", "").strip("\\/").replace("\\", "_").replace("/", "_")
    return os.path.join(drive, rest.lstrip("\\/"))


def output_folders(files: list[str], inputs: list[str], out: str) -> dict[str, str]:
    """{file: the folder under <out> it goes to}: its folder below the inputs' common parent (a folder given keeps
    its own name: D:\\mocap\\s01 -> <out>\\s01\\...; a file given goes to <out>), from the drive on when the
    inputs are on different drives. Every folder is inside <out>."""
    root = os.path.abspath(out)
    parents = [os.path.dirname(os.path.abspath(p)) for p in inputs] or [os.path.dirname(os.path.abspath(f)) for f in files]
    try:
        base = os.path.commonpath(parents)
    except ValueError:  # other drives or shares
        base = None
    folders = {}
    for f in files:
        d = os.path.dirname(os.path.abspath(f))
        try:
            rel = os.path.relpath(d, base) if base is not None else _folder_below(d)
        except ValueError:
            rel = _folder_below(d)
        if rel.startswith(".."):  # a file outside every input given (it cannot be, but never write outside <out>)
            rel = _folder_below(d)
        path = os.path.normpath(os.path.join(root, rel))
        if os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) != os.path.normcase(root):
            raise ValueError(f"내보낼 폴더 밖에 쓰게 됩니다: {path}")
        folders[f] = path
    return folders


def pick_takes(files: list[str]) -> tuple[list[str], dict[str, str]]:
    """(files to export, {file left out: the file of the same take exported}): of the files of one take in one
    folder (X.bvh, X.fbx, X_stageii.npz, X.c3d) the first of TAKE_ORDER goes."""
    from .motion_labels import same_take

    groups: dict[tuple, list[str]] = {}
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        groups.setdefault((os.path.normcase(os.path.dirname(os.path.abspath(f))), same_take(stem).lower()), []).append(f)

    def rank(f):
        ext = os.path.splitext(f)[1].lower()
        return TAKE_ORDER.index(ext) if ext in TAKE_ORDER else len(TAKE_ORDER)

    dropped = {}
    for group in groups.values():
        first = min(group, key=rank)
        for f in group:
            if f != first:
                dropped[f] = first
    keep = [f for f in files if f not in dropped]
    return keep, dropped


def clean_previous(out: str) -> list[str]:
    """Remove the files an earlier export into <out> wrote (as its manifest lists them, inside <out> only), so
    pieces of other settings do not stay; the files removed."""
    root = os.path.abspath(out)
    try:
        with open(os.path.join(root, MANIFEST), encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(old, dict) or "retlens_export" not in old:
        return []
    listed = [os.path.join(root, MANIFEST), os.path.join(root, MANIFEST_CSV)]
    for c in old.get("clips") or []:
        listed += [os.path.join(root, p) for p in (c.get("files") or []) + [c.get("labels"), c.get("info")] if p]
    removed = []
    for p in listed:
        p = os.path.normpath(p)
        if os.path.commonpath([os.path.normcase(p), os.path.normcase(root)]) != os.path.normcase(root):
            continue
        if os.path.isfile(p):
            os.remove(p)
            removed.append(p)
    return removed


# ------------------------------------------------------------------ one motion
def export_motion(robot, out_dir: str, stem: str, *, labels=None, cut: CutOptions | None = None, qc_bad=(),
                  problems: dict | None = None, falls=(), range_s=None, formats=("npz",), info: dict | None = None,
                  limits=None, qc: str = "FAIL") -> dict:
    """구간 잘라 내보내기 of one robot motion into out_dir: the whole motion (or range_s of it), with cut the spans
    taken out and the rest in pieces; each piece kept when its QC is no worse than `qc`. info goes into each
    piece's <name>.json. Returns {"pieces": [...], "dropped": [...], "cut_s", "short_s", "by_kind"}."""
    from .motion_labels import save_csv
    from .qc import QCConfig, check_robot

    T, fps = robot.num_frames, robot.fps
    spans = cut_spans(robot.duration, cut, qc_bad, problems, falls) if cut is not None else []
    plan = pieces(T, fps, cut, spans, range_s)
    written, dropped = [], []
    for i0, i1 in plan["ranges"]:
        part = slice_motion(robot, i0, i1)
        name = piece_name(stem, i0, i1, T, fps)
        part.name = name
        r = check_robot(part, QCConfig(), limits)
        entry = {"name": name, "start_s": round(i0 / fps, 4), "end_s": round(i1 / fps, 4),
                 "duration_s": round((i1 - i0) / fps, 4), "frames": i1 - i0, "fps": fps, "qc": r.status,
                 "qc_notes": "; ".join(r.notes)}
        if QC_RANK.get(r.status, 2) > QC_RANK.get(qc, 2):
            dropped.append({**entry, "reason": f"QC {r.status}" + (f" ({entry['qc_notes']})" if r.notes else "")})
            continue
        base = os.path.join(out_dir, name)
        entry["files"] = write_motion(part, base, formats)
        if labels is not None:
            lab = slice_labels(labels, i0 / fps, i1 / fps, base + ".labels.csv")
            if lab.segments:
                entry["labels"] = save_csv(lab, base + ".labels.csv")
                entry["label_seconds"] = label_seconds(lab)
        entry["info"] = base + ".json"
        with open(entry["info"], "w", encoding="utf-8") as f:
            json.dump({"retlens": __version__, "name": name, "source": robot.source,
                       "source_start_s": entry["start_s"], "source_end_s": entry["end_s"], "fps": fps,
                       "frames": entry["frames"], "joint_names": list(robot.joint_names),
                       "robot": robot.meta.get("robot_ident"), "qc": r.status,
                       "cut": asdict(cut) if cut is not None else None, "range_s": list(range_s) if range_s else None,
                       **(info or {})}, f, ensure_ascii=False, indent=1, default=_json_default)
        written.append(entry)
    return {"pieces": written, "dropped": dropped, "cut_s": plan["cut_s"], "short_s": plan["short_s"],
            "by_kind": plan["by_kind"]}


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ------------------------------------------------------------------ many motions
class Exporter:
    """데이터셋 내보내기: the motions of folders through retlens.batch, the ones that pass written into <out>."""

    def __init__(self, batch_opts, opts: ExportOptions | None = None, out: str = ".", runner=None,
                 log: Callable | None = None):
        from .batch import Batch

        self.bopts = batch_opts
        self.opts = opts or ExportOptions()
        self.out = os.path.abspath(out)
        self.batch = runner or Batch(batch_opts, log=log)
        self.log = log or (lambda *_: None)
        bad = [f for f in self.opts.formats if f not in FORMATS]
        if bad or not self.opts.formats:
            raise ValueError(f"형식은 {', '.join(FORMATS)} 중에서 고릅니다: {', '.join(bad) or '없음'}")
        if self.opts.qc not in QC_RANK:
            raise ValueError(f"QC 기준은 PASS, WARN, FAIL 중 하나입니다: {self.opts.qc}")

    def _reject(self, row: dict) -> str | None:
        """Why a motion's row keeps it out (None: it goes on)."""
        o = self.opts
        if row.get("error"):
            return f"읽지 못함: {row['error']}"
        if o.min_score is not None and (row.get("retarget_score") is not None) and row["retarget_score"] < o.min_score:
            return f"리타게팅 점수 {row['retarget_score']:.0f} < {o.min_score:g}"
        if o.cut is None and o.range_s is None and QC_RANK.get(row.get("qc"), 2) > QC_RANK[o.qc]:  # else: per piece
            return f"QC {row.get('qc')}" + (f" ({row['qc_notes']})" if row.get("qc_notes") else "")
        cut_falls = o.cut is not None and o.cut.falls
        if row.get("phys_falls") and not o.allow_falls and not cut_falls:
            return f"물리 넘어짐 {row['phys_falls']}회"
        if row.get("phys_error") and not o.allow_falls:  # physics was asked for and could not say
            return f"물리 검사 실패: {row['phys_error']}"
        return None

    def run(self, inputs: list[str], progress: Callable[[int, int, str], None] | None = None,
            cancel: Callable[[], bool] | None = None) -> dict:
        """Export the motions under inputs (files or folders) into <out>; returns the manifest (also written as
        manifest.json and manifest.csv). progress(done, total, name) after each motion, cancel() before each (a
        stopped run writes the manifest of what it did, "stopped": true)."""
        from .batch import motion_files
        from .robot_profile import load as load_robot

        o = self.opts
        files = list(dict.fromkeys(os.path.abspath(f) for f in motion_files(inputs)))  # a folder and one inside it
        if o.range_s is not None and len(files) != 1:
            raise ValueError("시간 범위는 모션 하나에만 씁니다")
        prof = load_robot(self.bopts.robot)
        joints = prof.joint_names()
        os.makedirs(self.out, exist_ok=True)
        removed = clean_previous(self.out)
        keep, same = pick_takes(files)
        folders = output_folders(keep, inputs, self.out)
        clips, excluded, stopped, t0 = [], [], False, time.time()
        totals = {"source_s": 0.0, "cut_s": 0.0, "short_s": 0.0, "cut_by_kind": {}}
        for k, f in enumerate(files):
            if cancel is not None and cancel():
                stopped = True
                break
            name = os.path.splitext(os.path.basename(f))[0]
            try:
                if f in same:
                    excluded.append({"source": os.path.abspath(f), "reason": f"같은 촬영: {os.path.basename(same[f])}로 내보냄"})
                    continue
                row = self.batch.process(f)
                why = self._reject(row)
                if why:
                    excluded.append({"source": os.path.abspath(f), "reason": why})
                    continue
                item, lab = self.batch.item_and_labels(f)
                if list(item.robot.joint_names) != list(joints):
                    excluded.append({"source": os.path.abspath(f),
                                     "reason": f"다른 로봇의 모션 (관절 {len(item.robot.joint_names)}개, 이 로봇은 {len(joints)}개)"})
                    continue
                done = self._export_one(f, row, item, lab, folders[f])
                for e in done["dropped"]:
                    excluded.append({"source": os.path.abspath(f), "piece": e["name"], "reason": e["reason"]})
                if not done["pieces"]:
                    if not done["dropped"]:
                        excluded.append({"source": os.path.abspath(f),
                                         "reason": f"남은 조각 없음 ({o.cut.min_piece_s:g}초보다 짧음)" if o.cut else "빈 모션"})
                    continue
                clips += done["pieces"]
                totals["source_s"] += item.robot.duration
                totals["cut_s"] += done["cut_s"]
                totals["short_s"] += done["short_s"]
                for kind, s in done["by_kind"].items():
                    totals["cut_by_kind"][kind] = round(totals["cut_by_kind"].get(kind, 0.0) + s, 3)
            except Exception as e:  # one bad motion never stops the export
                excluded.append({"source": os.path.abspath(f), "reason": f"내보내기 실패: {type(e).__name__}: {e}"})
            finally:
                if progress is not None:
                    progress(k + 1, len(files), name)
        manifest = self._manifest(inputs, prof, clips, excluded, totals, stopped, removed, len(files), time.time() - t0)
        self._write_manifest(manifest)
        return manifest

    def _export_one(self, path: str, row: dict, item, lab, folder: str) -> dict:
        o = self.opts
        stem = os.path.splitext(os.path.basename(path))[0]
        sha = sha256(path)
        info = {"retarget": item.retarget or None, "kind": item.kind, "source_sha256": sha,
                "source_qc": row.get("qc"), "retarget_score": row.get("retarget_score"),
                "phys_falls": row.get("phys_falls")}
        per_piece = o.cut is not None or o.range_s is not None  # the whole motion was judged by its row
        res = export_motion(item.robot, folder, stem, labels=lab if o.labels else None, cut=o.cut,
                            qc_bad=row.get("qc_bad_spans") or [], problems=row.get("problem_spans") or {},
                            falls=row.get("phys_fall_times_s") or [], range_s=o.range_s, formats=o.formats, info=info,
                            limits=self.batch._tools()[1], qc=o.qc if per_piece else "FAIL")

        def rel(p):
            return os.path.relpath(p, self.out).replace("\\", "/") if p else None

        session = os.path.relpath(folder, self.out).replace("\\", "/")
        for e in res["pieces"]:
            e.update({"files": [rel(p) for p in e["files"]], "labels": rel(e.get("labels")), "info": rel(e.get("info")),
                      "source": os.path.abspath(path), "source_sha256": sha, "session": "" if session == "." else session,
                      "source_qc": row.get("qc"), "retarget_score": row.get("retarget_score"),
                      "phys_falls": row.get("phys_falls"), "objects": row.get("object_names") or [],
                      "kind": row.get("kind")})
        return res

    def _manifest(self, inputs, prof, clips, excluded, totals, stopped, removed, n_files, seconds) -> dict:
        o, b = self.opts, self.bopts
        reasons: dict[str, int] = {}
        for e in excluded:
            key = e["reason"].split(" (")[0].split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
        out_s = sum(c["duration_s"] for c in clips)
        rates = sorted({c["fps"] for c in clips})
        return {
            "retlens_export": EXPORT_VERSION, "retlens": __version__,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "stopped": stopped,
            "inputs": [os.path.abspath(p) for p in inputs],
            "robot": prof.ident, "joint_names": prof.joint_names(),
            "fps": rates[0] if len(rates) == 1 else rates or None,  # a list when the motions differ
            "retarget": {"smooth_hz": b.smooth, "fps": b.fps, "foot_flat": b.foot_flat,
                         "swing_clearance_cm": b.swing_clearance_cm, "self_collision": b.self_collision},
            "physics": b.physics, "label_rules": b.rules,
            "criteria": {"qc": o.qc, "min_score": o.min_score, "allow_falls": o.allow_falls},
            "cut": asdict(o.cut) if o.cut is not None else None,
            "cut_text": o.cut.describe() if o.cut is not None else None,
            "range_s": list(o.range_s) if o.range_s else None,
            "formats": list(o.formats), "format_notes": {f: FORMATS[f] for f in o.formats},
            "totals": {"motions": n_files, "exported_motions": len({c["source"] for c in clips}), "clips": len(clips),
                       "seconds": round(out_s, 3), "source_seconds": round(totals["source_s"], 3),
                       "cut_seconds": round(totals["cut_s"], 3), "short_seconds": round(totals["short_s"], 3),
                       "cut_by_kind": totals["cut_by_kind"], "excluded": len(excluded), "excluded_by_reason": reasons,
                       "seconds_taken": round(seconds, 1)},
            "previous_files_removed": len(removed),
            "clips": clips, "excluded": excluded,
        }

    def _write_manifest(self, manifest: dict) -> None:
        with open(os.path.join(self.out, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1, default=_json_default)
        write_manifest_csv(manifest, os.path.join(self.out, MANIFEST_CSV))


MANIFEST_COLUMNS = [("file", "파일"), ("session", "폴더"), ("duration_s", "길이 (s)"), ("frames", "프레임"),
                    ("fps", "fps"), ("start_s", "원본 시작 (s)"), ("end_s", "원본 끝 (s)"), ("qc", "QC"),
                    ("source_qc", "원본 QC"), ("retarget_score", "리타게팅 점수"), ("phys_falls", "원본 물리 넘어짐"),
                    ("labels", "라벨 파일"), ("label_names", "라벨"),
                    ("objects", "물체"), ("source", "원본 파일"), ("source_sha256", "원본 sha256")]


def write_manifest_csv(manifest: dict, path: str) -> str:
    """A line per written motion (UTF-8 with BOM: Excel reads the Korean)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([k for k, _t in MANIFEST_COLUMNS])
        for c in manifest["clips"]:
            row = {**c, "file": (c.get("files") or [""])[0], "label_names": "; ".join(c.get("label_seconds") or {}),
                   "objects": "; ".join(c.get("objects") or [])}
            w.writerow(["" if row.get(k) is None else row.get(k) for k, _t in MANIFEST_COLUMNS])
    return path
