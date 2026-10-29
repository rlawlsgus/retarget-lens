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
    start_frame, end_frame      frames, end inclusive, at the row's fps column (else the motion's fps)
    track (or axis)             optional: each track is drawn in its own lane (e.g. 이동 / 왼손 / 오른손)
    name, object, note          optional: shown with the segment
    color                       optional: #rrggbb (else every label gets its own color for the session)
    seq                         optional: in a table of several motions, the motion a row belongs to,
                                matched by file name without extension ("CMU/02/02_01_stageii.npz")
UTF-8 (with or without BOM) or CP949 (Excel's Korean CSV). Segment tables of a labeller with these
columns (seq, track, label, start_s, end_s, ...) read as they are.

JSON: {"fps": 30, "segments": [{"label": .., "start_s": .., "end_s": .., "track"?: ..}, ..]} or just the list.
"""

from __future__ import annotations

import csv
import io
import json
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
    opens anyway); notes: what was skipped or clipped."""
    path: str
    segments: list[Segment] = field(default_factory=list)
    error: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def tracks(self) -> list[str]:
        return list(dict.fromkeys(s.track for s in self.segments))

    def at(self, t: float) -> list[Segment]:
        """The segment under motion time t in each track (in track order; none where unlabelled)."""
        now = {}
        for s in self.segments:
            if s.start <= t < s.end:
                now[s.track] = s
        return [now[k] for k in self.tracks if k in now]

    def text_at(self, t: float) -> str:
        """'reach', or '이동: 걷기 · 왼손: 뻗기' with tracks; '' where nothing is labelled."""
        return " · ".join(f"{s.track}: {s.label}" if s.track else s.label for s in self.at(t))

    def summary(self, t: float | None = None, segments: bool = True) -> dict:
        """JSON-ready: the file, its tracks, the segments under time t, and (segments=True) all of them."""
        out = {"file": self.path, "error": self.error or None, "tracks": self.tracks, "count": len(self.segments),
               "notes": self.notes}
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
    if is_label_name(path):
        return True
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".csv":
            with open(path, "rb") as f:
                head = _decode(f.readline())
            return "label" in [c.strip().lower() for c in next(csv.reader([head]), [])]
        if ext == ".json":
            with open(path, "rb") as f:
                d = json.loads(_decode(f.read()))
            segs = d.get("segments") if isinstance(d, dict) else d
            return isinstance(segs, list) and bool(segs) and isinstance(segs[0], dict) and "label" in segs[0]
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
    motion), in the order they are tried."""
    out = []
    for p in (source, *also):
        if p:
            stem = os.path.splitext(p)[0]
            out += [stem + s for s in SUFFIXES]
    return out + [os.path.join(os.path.dirname(source), n) for n in FOLDER_TABLES]


def load_for(source: str, fps: float, duration: float | None = None, also=()) -> MotionLabels | None:
    """The labels of a motion from the first label file next to it; None when there is none (a
    folder table counts only when it has rows for this motion)."""
    for p in candidates(source, also):
        if not os.path.isfile(p):
            continue
        table = os.path.basename(p).lower() in FOLDER_TABLES
        lab = load(p, source, fps, duration, table=table)
        if table and not lab.segments:
            continue
        return lab
    return None


# ---------------------------------------------------------------- reading
def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949")


def _read(path: str) -> tuple[list[dict], float | None]:
    """Rows (lower-case column names, stripped text) and the file's fps (JSON only)."""
    with open(path, "rb") as f:
        text = _decode(f.read())
    if path.lower().endswith(".json"):
        d = json.loads(text)
        segs = d.get("segments", []) if isinstance(d, dict) else d
        if not isinstance(segs, list) or not all(isinstance(s, dict) for s in segs):
            raise ValueError("segments는 {label, start_s, end_s} 목록이어야 합니다")
        rows = [{str(k).strip().lower(): "" if v is None else str(v).strip() for k, v in s.items()} for s in segs]
        return rows, float(d["fps"]) if isinstance(d, dict) and d.get("fps") else None
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader], None


def _color(text: str) -> tuple | None:
    t = text.strip().lstrip("#")
    if len(t) != 6:
        return None
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _pick_seq(rows: list[dict], source: str, table: bool) -> tuple[list[dict], str, str]:
    """(this motion's rows, error, note) of a table that names its motion per row (seq). A file with
    one motion in it is taken whole: its name already ties it to the motion."""
    seqs = list(dict.fromkeys(r.get("seq", "") for r in rows if r.get("seq")))
    if not seqs or (len(seqs) == 1 and not table):
        return rows, "", ""
    src = os.path.abspath(source).replace("\\", "/").lower()
    stem = os.path.splitext(os.path.basename(src))[0]
    match = [s for s in seqs if os.path.splitext(os.path.basename(s.replace("\\", "/")))[0].lower() == stem]
    if len(match) > 1:  # the same file name in several folders: the one whose path ends like the motion's
        tail = [s for s in match if src.endswith("/" + s.replace("\\", "/").lower().lstrip("/"))]
        match = tail + [s for s in match if s not in tail]
    if not match:
        return [], "" if table else (f"이 모션({stem})의 행이 없습니다. seq 열의 모션 {len(seqs)}개: "
                                     + ", ".join(seqs[:3]) + (" …" if len(seqs) > 3 else "")), ""
    note = f"seq가 같은 이름인 모션이 {len(match)}개라 {match[0]}의 행을 씁니다" if len(match) > 1 else ""
    return [r for r in rows if r.get("seq") == match[0]], "", note


def load(path: str, source: str, fps: float, duration: float | None = None, table: bool = False) -> MotionLabels:
    """Read a label file for the motion file `source`: its fps reads frame columns, its duration
    clips the segments. table: a folder table, whose rows must name the motion (seq)."""
    lab = MotionLabels(path=os.path.abspath(path))
    try:
        rows, file_fps = _read(path)
    except (OSError, ValueError, csv.Error) as e:
        lab.error = f"읽지 못함: {type(e).__name__}: {e}"
        return lab
    keys = set().union(*rows) if rows else set()
    if "label" not in keys:
        lab.error = "label 열이 없습니다" + (f" (열: {', '.join(sorted(keys))})" if keys else " (빈 파일)")
        return lab
    by_s, by_f = {"start_s", "end_s"} <= keys, {"start_frame", "end_frame"} <= keys
    if not (by_s or by_f):
        lab.error = "시간 열이 없습니다: start_s·end_s(초) 또는 start_frame·end_frame(프레임)이 있어야 합니다"
        return lab
    rows, lab.error, note = _pick_seq(rows, source, table)
    if note:
        lab.notes.append(note)
    skipped, segs = 0, []
    for r in rows:
        try:
            if by_s and r.get("start_s") and r.get("end_s"):
                start, end = float(r["start_s"]), float(r["end_s"])
            else:
                f = float(r.get("fps") or file_fps or fps)
                start, end = int(float(r["start_frame"])) / f, (int(float(r["end_frame"])) + 1) / f
        except (KeyError, ValueError, ZeroDivisionError):
            skipped += 1
            continue
        label = r.get("label", "")
        if not label or not end > start:
            skipped += 1
            continue
        obj = r.get("object", "")
        segs.append(Segment(label=label, start=start, end=end, track=r.get("track") or r.get("axis") or "",
                            name=r.get("name", "") if r.get("name", "") != label else "",
                            note=" · ".join(x for x in (f"물체 {obj}" if obj else "", r.get("note", "")) if x),
                            color=_color(r.get("color", ""))))
    if skipped:
        lab.notes.append(f"시간이나 라벨이 비었거나 끝이 시작보다 빠른 행 {skipped}개는 뺐습니다")
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
