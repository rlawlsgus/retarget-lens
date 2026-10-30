"""Labelled time segments of a motion (actions, subtasks), drawn on the timeline.

A motion may have labels or not, and nothing else depends on them: without a label file it
plays as it always did. Labels come from a file next to the motion, found when it is opened,
or one picked in the window (인스펙터 > 라벨, the timeline's right-click menu, dropping the
file on the window). Tried in this order:

    <stem>.labels.csv  <stem>.labels.json  <stem>_labels.csv  <stem>_labels.json  <stem>_subtask.csv
    labels.csv / labels.json in the same folder: a table of several motions, rows picked by seq

CSV: one row per segment, with a header
    label                       the segment's label (required)
    start_s, end_s              seconds from the motion's first frame, end exclusive; or
    start_frame, end_frame      frames, end inclusive, at the row's fps column, else the fps the motion
                                plays at in RetLens (a retargeted human motion: usually 30, not its file's)
    track (or axis)             optional: each track is drawn in its own lane (e.g. 이동 / 왼손 / 오른손)
    name, object, note          optional: shown with the segment
    color                       optional: #rrggbb (else every label gets its own color for the session)
    seq                         optional: in a table of several motions, the motion a row belongs to,
                                matched by file name without extension ("CMU/02/02_01_stageii.npz"),
                                else as the same take (02_01_stageii / 02_01_poses is 02_01).
                                A folder table needs it; a file whose seq is another motion is an error
A C3D motion also finds the label files of its solved motion (sidecars, and that folder's table).
UTF-8 (with or without BOM) or CP949 (Excel's Korean CSV). Segment tables of a labeller with these
columns (seq, track, label, start_s, end_s, ...) read as they are.

JSON: {"fps": 30, "segments": [{"label": .., "start_s": .., "end_s": .., "track"?: ..}, ..]} or just the list.
"""

from __future__ import annotations

import bisect
import csv
import io
import json
import math
import os
from dataclasses import dataclass, field

SUFFIXES = (".labels.csv", ".labels.json", "_labels.csv", "_labels.json", "_subtask.csv")
FOLDER_TABLES = ("labels.csv", "labels.json")
# distinct on the timeline's dark and light backgrounds (Okabe-Ito first); a label keeps its color for the session
PALETTE = [(86, 180, 233), (230, 159, 0), (0, 158, 115), (240, 228, 66), (204, 121, 167), (213, 94, 0),
           (0, 114, 178), (160, 150, 255), (170, 215, 110), (255, 140, 140), (110, 205, 200), (205, 170, 120)]
_colors: dict[str, tuple] = {}


@dataclass
class Segment:
    label: str
    start: float  # s from the motion's first frame
    end: float  # s, exclusive
    track: str = ""
    name: str = ""  # a longer name of the label (e.g. 준비 자세·손 뻗기 for reach)
    note: str = ""  # object / note columns
    color: tuple | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class MotionLabels:
    """The segments of one motion from one file. error: the file could not be used (the motion
    opens anyway); notes: what was skipped or clipped. auto: made by retlens.autolabel with the
    rule file at path (the rules' name), '' for labels read from a label file. found: found next
    to the motion (load_for), not picked: reading them again looks again."""
    path: str
    segments: list[Segment] = field(default_factory=list)
    error: str = ""
    notes: list[str] = field(default_factory=list)
    auto: str = ""
    found: bool = False

    @property
    def tracks(self) -> list[str]:
        return list(self._index())

    def _index(self) -> dict:
        """{track: (starts, segments by start, any overlap)} in track order. Built again only when
        the segment list changes: at() runs every frame for every motion (3D tag, timeline)."""
        key = (id(self.segments), len(self.segments))
        if getattr(self, "_idx_key", None) != key:
            by: dict[str, list[Segment]] = {}
            for s in self.segments:
                by.setdefault(s.track, []).append(s)
            idx = {}
            for track, segs in by.items():
                segs = sorted(segs, key=lambda s: s.start)  # stable: equal starts keep the file's order
                idx[track] = ([s.start for s in segs], segs, any(b.start < a.end for a, b in zip(segs, segs[1:])))
            self._idx, self._idx_key = idx, key
        return self._idx

    def at(self, t: float) -> list[Segment]:
        """The segment under motion time t in each track (in track order; none where unlabelled).
        Where segments of a track overlap, the one that starts last."""
        out = []
        for starts, segs, overlap in self._index().values():
            i = bisect.bisect_right(starts, t) - 1
            for s in (reversed(segs[:i + 1]) if overlap else segs[i:i + 1]) if i >= 0 else ():
                if t < s.end:
                    out.append(s)
                    break
        return out

    def text_at(self, t: float, sep: str = " · ") -> str:
        """'reach', or '이동: 걷기 · 왼손: 뻗기' with tracks (sep between them); '' where nothing is labelled."""
        return sep.join(f"{s.track}: {s.label}" if s.track else s.label for s in self.at(t))

    def summary(self, t: float | None = None, segments: bool = True) -> dict:
        """JSON-ready: the file, its tracks, the segments under time t, and (segments=True) all of them."""
        out = {"file": self.path, "auto": self.auto or None, "error": self.error or None, "tracks": self.tracks,
               "count": len(self.segments), "notes": self.notes}
        if t is not None:
            out["now"] = [{"track": s.track, "label": s.label} for s in self.at(t)]
        if segments:
            out["segments"] = [{"label": s.label, "name": s.name or None, "track": s.track, "start_s": round(s.start, 4),
                                "end_s": round(s.end, 4), "note": s.note or None} for s in self.segments]
        return out


def color_for(seg: Segment) -> tuple:
    """The segment's color: its own, else the label's (the next palette color the first time it is seen)."""
    if seg.color:
        return seg.color
    c = _colors.get(seg.label)
    if c is None:
        c = _colors[seg.label] = PALETTE[len(_colors) % len(PALETTE)]
    return c


# ---------------------------------------------------------------- finding
def is_label_name(path: str) -> bool:
    """Named like a label file (the motion folders list these as labels, not as Unitree csv motions)."""
    name = os.path.basename(path).lower()
    return name.endswith(SUFFIXES) or name in FOLDER_TABLES


def is_label_file(path: str) -> bool:
    """A label file by its name, or a .csv whose header has a label column, or a .json of segments."""
    return is_label_name(path) or _looks_like_labels(path, ("label",))


TABLE_COLUMNS = ("label", "seq", "start_s", "end_s", "start_frame", "end_frame")


def _looks_like_labels(path: str, columns=TABLE_COLUMNS) -> bool:
    """A .csv whose header, or a .json whose (first) segment, has one of these columns. A folder's
    labels.csv / labels.json can be another tool's file: only one that looks like a label table is
    read (and its faults shown)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".csv":
            with open(path, "rb") as f:
                head = _decode(f.readline())
            return any(c.strip().lower() in columns for c in next(csv.reader([head]), []))
        if ext == ".json":
            with open(path, "rb") as f:
                d = json.loads(_decode(f.read()))
            if isinstance(d, dict) and "segments" in d and columns is TABLE_COLUMNS:
                return True
            segs = d.get("segments") if isinstance(d, dict) else d
            return isinstance(segs, list) and bool(segs) and isinstance(segs[0], dict) and \
                any(str(k).strip().lower() in columns for k in segs[0])
    except (OSError, ValueError):
        pass
    return False


def stem_of(path: str) -> str:
    """The motion name a label file is for: 02_01.labels.csv, 02_01_subtask.csv -> 02_01."""
    name = os.path.basename(path)
    for s in SUFFIXES:
        if name.lower().endswith(s):
            return name[:-len(s)]
    return os.path.splitext(name)[0]


def candidates(source: str, also=()) -> list[str]:
    """Label files that would belong to the motion file `source` (and `also`: e.g. a C3D's solved
    motion, whose folder's table counts too), in the order they are tried."""
    files = [p for p in (source, *also) if p]
    out = [os.path.splitext(p)[0] + s for p in files for s in SUFFIXES]
    folders = dict.fromkeys(os.path.dirname(os.path.abspath(p)) for p in files)
    return out + [os.path.join(d, n) for d in folders for n in FOLDER_TABLES]


def load_for(source: str, fps: float, duration: float | None = None, also=()) -> MotionLabels | None:
    """The labels of a motion from the first label file next to it; None when there is none. A
    folder table counts when it has rows for this motion, or when it is a label table that cannot
    be used at all (the motion then shows why, instead of looking unlabelled); a labels.csv /
    labels.json of another kind is passed over."""
    for p in candidates(source, also):
        if not os.path.isfile(p):
            continue
        table = os.path.basename(p).lower() in FOLDER_TABLES
        if table and not _looks_like_labels(p):
            continue
        lab = load(p, source, fps, duration, table=table, also=[a for a in also if a])
        if lab is not None:
            lab.found = True
            return lab
    return None


# ---------------------------------------------------------------- reading
def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949")


TEXT_COLUMNS = ("note", "name", "object")  # a comma typed into these without quotes runs on into extra values


def _read(path: str) -> tuple[list[dict], float | None, list[str]]:
    """Rows (lower-case column names, stripped text), the file's fps (JSON only) and notes on what
    was off. A CSV row with more values than the header has (a trailing comma, a comma in a note
    without quotes) keeps its columns: the extra values join the last column when that is a text
    column, else they are left out."""
    with open(path, "rb") as f:
        text = _decode(f.read())
    if path.lower().endswith(".json"):
        d = json.loads(text)
        segs = d.get("segments", []) if isinstance(d, dict) else d
        if not isinstance(segs, list) or not all(isinstance(s, dict) for s in segs):
            raise ValueError("segments는 {label, start_s, end_s} 목록이어야 합니다")
        rows = [{str(k).strip().lower(): "" if v is None else str(v).strip() for k, v in s.items()} for s in segs]
        return rows, float(d["fps"]) if isinstance(d, dict) and d.get("fps") else None, []
    reader = csv.reader(io.StringIO(text))
    head = [c.strip().lower() for c in next(reader, [])]
    rows, joined, dropped = [], 0, 0
    for vals in reader:
        if not any(v.strip() for v in vals):
            continue  # a blank line
        extra = vals[len(head):]
        r = {k: (vals[i].strip() if i < len(vals) else "") for i, k in enumerate(head) if k}
        if any(v.strip() for v in extra):
            if head and head[-1] in TEXT_COLUMNS:
                r[head[-1]] = ",".join([vals[len(head) - 1], *extra]).strip()
                joined += 1
            else:
                dropped += 1
        rows.append(r)
    notes = []
    if joined:
        notes.append(f"값이 열 이름보다 많은 행 {joined}개: 넘친 값은 마지막 열({head[-1]})에 이어 붙였습니다 "
                     "(쉼표가 든 값은 따옴표로 감싸세요)")
    if dropped:
        notes.append(f"값이 열 이름보다 많은 행 {dropped}개: 넘친 값은 버렸습니다 (쉼표가 든 값은 따옴표로 감싸세요)")
    return rows, None, notes


def _color(text: str) -> tuple | None:
    t = text.strip().lstrip("#")
    if len(t) != 6:
        return None
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


SOLVER_ENDINGS = ("_stageii", "_poses")  # AMASS names a take's fit <take>_stageii.npz: the same motion as <take>.bvh


def same_take(stem: str) -> str:
    """02_01_stageii -> 02_01: the take an AMASS fit is of."""
    for e in SOLVER_ENDINGS:
        if stem.endswith(e):
            return stem[:-len(e)]
    return stem


def _pick_seq(rows: list[dict], sources: list[str], table: bool) -> tuple[list[dict] | None, str, str]:
    """(this motion's rows, error, note) of a table that names its motion per row (seq): rows whose
    seq is the file name without extension of the motion (sources: its file, then for a C3D its
    solved motion's), else the same take (02_01_stageii.npz is 02_01.bvh). A file of one motion
    that is not this one is an error, so is a folder table without seq. None for the rows: a
    folder table without this motion (not its label file)."""
    seqs = list(dict.fromkeys(r.get("seq", "") for r in rows if r.get("seq")))
    if not seqs:
        if table:
            return [], ("seq 열이 없습니다. 폴더의 labels.csv는 여러 모션의 표라 행마다 seq(모션 파일 이름)가 "
                        "있어야 합니다. 한 모션의 라벨이면 <모션 이름>.labels.csv로 두세요"), ""
        return rows, "", ""
    srcs = [os.path.abspath(p).replace("\\", "/").lower() for p in sources if p]
    stems = [os.path.splitext(os.path.basename(s))[0] for s in srcs]
    stem = stems[0]
    name = lambda s: os.path.splitext(os.path.basename(s.replace("\\", "/")))[0].lower()
    takes = {same_take(x) for x in stems}
    match = [s for s in seqs if name(s) in stems] or [s for s in seqs if same_take(name(s)) in takes]
    if len(match) > 1:  # the same file name in several folders: the one whose path ends like the motion's
        tail = [s for s in match if any(p.endswith("/" + s.replace("\\", "/").lower().lstrip("/")) for p in srcs)]
        match = tail + [s for s in match if s not in tail]
    if not match:
        if table:
            return None, "", ""
        return [], (f"이 모션({stem})의 행이 없습니다. seq 열의 모션 {len(seqs)}개: " + ", ".join(seqs[:3])
                    + (" …" if len(seqs) > 3 else "") + ". 다른 모션의 라벨을 붙이려면 seq 열을 지우세요"), ""
    if len(seqs) == 1 and not table:
        return rows, "", ""  # a file of this motion: rows without seq belong to it too
    note = f"seq가 같은 이름인 모션이 {len(match)}개라 {match[0]}의 행을 씁니다" if len(match) > 1 else ""
    return [r for r in rows if r.get("seq") == match[0]], "", note


def load(path: str, source: str, fps: float, duration: float | None = None, table: bool = False,
         also=()) -> MotionLabels | None:
    """Read a label file for the motion file `source`: its fps reads frame columns, its duration
    clips the segments. table: a folder table, whose rows must name the motion (seq); None when it
    has none for this motion. also: other names the motion goes by in seq (a C3D's solved
    motion). Never raises: what is wrong with the file is the labels' error (a label file never
    stops a motion from opening, nor the window or the API)."""
    try:
        return _load(path, [source, *also], fps, duration, table)
    except Exception as e:  # noqa: BLE001
        return MotionLabels(path=os.path.abspath(path), error=f"읽지 못함: {type(e).__name__}: {e}")


def _load(path: str, sources: list[str], fps: float, duration: float | None, table: bool) -> MotionLabels | None:
    lab = MotionLabels(path=os.path.abspath(path))
    rows, file_fps, lab.notes = _read(path)
    keys = set().union(*rows) if rows else set()
    if "label" not in keys:
        empty = " (segments 목록이 없거나 비었음)" if path.lower().endswith(".json") else " (빈 파일)"
        lab.error = "label 열이 없습니다" + (f" (열: {', '.join(sorted(keys))})" if keys else empty)
        return lab
    by_s, by_f = {"start_s", "end_s"} <= keys, {"start_frame", "end_frame"} <= keys
    if not (by_s or by_f):
        lab.error = "시간 열이 없습니다: start_s·end_s(초) 또는 start_frame·end_frame(프레임)이 있어야 합니다"
        return lab
    rows, lab.error, note = _pick_seq(rows, sources, table)
    if rows is None:
        return None
    if note:
        lab.notes.append(note)
    skipped, segs = 0, []
    for r in rows:
        try:
            if by_s and r.get("start_s") and r.get("end_s"):
                start, end = float(r["start_s"]), float(r["end_s"])
            else:
                f = float(r.get("fps") or file_fps or fps)
                if not f > 0:
                    raise ValueError(f"fps {f}")
                start, end = int(float(r["start_frame"])) / f, (int(float(r["end_frame"])) + 1) / f
        except (KeyError, ValueError, OverflowError):  # inf frames: OverflowError
            skipped += 1
            continue
        label = r.get("label", "")
        if not label or not (math.isfinite(start) and math.isfinite(end)) or not end > start:
            skipped += 1
            continue
        obj = r.get("object", "")
        segs.append(Segment(label=label, start=start, end=end, track=r.get("track") or r.get("axis") or "",
                            name=r.get("name", "") if r.get("name", "") != label else "",
                            note=" · ".join(x for x in (f"물체 {obj}" if obj else "", r.get("note", "")) if x),
                            color=_color(r.get("color", ""))))
    if skipped:
        lab.notes.append(f"시간이나 라벨이 비었거나 끝이 시작보다 빠른 행 {skipped}개는 뺐습니다")
    early = [s for s in segs if s.end <= 0]
    segs = [s for s in segs if s.end > 0]
    cut = sum(s.start < 0 for s in segs)
    for s in segs:
        s.start = max(s.start, 0.0)
    if early or cut:
        lab.notes.append("모션 시작(0 s) 전 구간: " + ", ".join(
            x for x in (f"{len(early)}개 뺌" if early else "", f"{cut}개 앞을 자름" if cut else "") if x))
    if duration is not None and segs:
        tol = 2.0 / max(fps, 1.0)  # rounding of the last frame
        after = [s for s in segs if s.start >= duration]
        segs = [s for s in segs if s.start < duration]
        long = sum(s.end > duration + tol for s in segs)
        for s in segs:
            s.end = min(s.end, duration)
        if after or long:
            lab.notes.append(f"모션 길이({duration:.2f} s)를 넘는 구간: " + ", ".join(
                x for x in (f"{len(after)}개 뺌" if after else "", f"{long}개 끝을 자름" if long else "") if x))
    order = {t: i for i, t in enumerate(dict.fromkeys(s.track for s in segs))}
    segs.sort(key=lambda s: (order[s.track], s.start))
    overlaps = sum(a.track == b.track and b.start < a.end - 1e-6 for a, b in zip(segs, segs[1:]))
    if overlaps:
        lab.notes.append(f"같은 트랙에서 겹치는 구간 {overlaps}곳 (나중 구간이 위에 그려짐)")
    for s in segs:
        color_for(s)  # colors in the order the labels first appear
    lab.segments = segs
    return lab


def save_csv(lab: MotionLabels, path: str) -> str:
    """Write the segments as a label file (UTF-8 with BOM, so Excel reads the Korean); it reads back
    with load to the same segments. Times are written in full: rounded, a boundary on frame k/30
    (2.2666...) could read back after its frame (2.2667) and move it to the neighbour."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track", "label", "name", "start_s", "end_s", "note", "color"])
        for s in lab.segments:
            w.writerow([s.track, s.label, s.name, repr(float(s.start)), repr(float(s.end)), s.note,
                        "#%02x%02x%02x" % s.color if s.color else ""])
    return path
