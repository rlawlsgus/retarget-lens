"""작업 세션: the window's working state in one file (.retlens, UTF-8 JSON) and back. No widgets
here: the window, the HTTP API and the tests use it alike.

    data = session.capture(scene, "D:/work")          # the window adds "selected" and "analysis"
    session.write("D:/work/today.retlens", data)
    data = session.read("D:/work/today.retlens")      # SessionError when it is not a session
    r = session.restore(scene, data, "D:/work")       # or Restore(data, base).run(scene, ...) in a worker

A session records the open motions (where the file is, the corrections it was retargeted with,
colour, time offset, visibility, skeleton on/off, where its labels come from or the labels
themselves) and the scene's settings (scene settings, overlay comparison, playhead, camera,
physics mode, the 리타게팅 menu). Motion files are never copied, only located: by a path relative
to the session's folder and an absolute one (portable / resolve), so a folder holding both can
move. Motions that could not be opened stay in the file (Restore.carry, capture's carry), so a
missing drive never shrinks a session. Every motion reference in the file is an index into
"motions"; readers ignore keys they do not know and take defaults for missing ones.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, fields
from typing import Callable

from .. import __version__, motion_labels, paths
from ..compare import Item
from ..motion_labels import MotionLabels, Segment
from .scene import BALANCE, PALETTE, MotionScene, ViewSettings

FORMAT = "retlens-session"
VERSION = 1
EXT = ".retlens"
EXTS = (EXT, ".retlens.json")  # what opening accepts
MODES = ("replace", "add")  # 닫고 열기 / 함께 열기
ASSIST = (1.0, 0.0)  # the Isaac harness scales the 물리 menu offers (editor.ASSIST_LABELS)
SPACING = (0.3, 5.0)  # the 간격 box's range: a value outside it would disagree with the box
SWING_MAX_CM = 10.0  # MotionScene.set_retarget's range
TOL_CM = (0.5, 50.0)  # the 비교 tab's 허용 오차 box (outside it the box would change it back: a dirty session)
OFFSET_S = (-600.0, 600.0)  # the inspector's 시간 오프셋 box
AUTO_OFF = "auto-off"  # mujoco_ready's reason for a mode it does not turn on by itself (not "unusable")
MAX_BYTES = 64 * 1024 * 1024  # larger is no session (labels inline make a session a few MB at most)
BAD_ENTRY = "세션 파일의 항목이 잘못됨"
LABEL_KINDS = ("find", "none", "file", "auto", "edited")
WHY = "작업 세션"  # set_physics's reason in the log


class SessionError(Exception):
    """The file is not a work session or cannot be read; the message is for the user (Korean)."""


def is_session_file(path: str) -> bool:
    return str(path).lower().endswith(EXTS)


# ---------------------------------------------------------------- values as read
_TRUE, _FALSE = ("true", "1", "yes", "on"), ("false", "0", "no", "off", "")


def _bool(v, default: bool) -> bool:
    """JSON true / false (also 1 / 0 and their text); anything else is the default (bool("false") is True)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in _TRUE + _FALSE:
        return v.strip().lower() in _TRUE
    return default


def _float(v, default, lo: float | None = None, hi: float | None = None):
    """A finite number clamped to [lo, hi]; anything else (text, nan, inf, true) is the default."""
    if isinstance(v, bool):
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    if lo is not None:
        f = max(lo, f)
    if hi is not None:
        f = min(hi, f)
    return f


def _index(v, n: int) -> int | None:
    """A motion reference: an index into "motions", else None."""
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < n else None


def _str(v, default: str = "") -> str:
    return v if isinstance(v, str) else default


def _vec3(v) -> list | None:
    if isinstance(v, (list, tuple)) and len(v) == 3:
        out = [_float(x, None) for x in v]
        if None not in out:
            return out
    return None


def _color(v) -> tuple | None:
    """A motion's colour: one of the scene's PALETTE, as the tuple scene.add compares (JSON gives a list,
    which never equals a tuple: the colour would look free and two motions could share it)."""
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(
            isinstance(c, (int, float)) and not isinstance(c, bool) and float(c).is_integer() for c in v):
        c = tuple(int(x) for x in v)
        return c if c in PALETTE else None
    return None


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in c)


def _rgb(v) -> tuple | None:
    """'#rrggbb' -> (r, g, b); anything else None."""
    if isinstance(v, str) and len(v) == 7 and v[0] == "#":
        try:
            return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- paths (so a folder can move)
def portable(path: str, base_dir: str | None) -> dict:
    """{"abs": absolute path, "rel": relative to base_dir with '/'}. "rel" is left out without a base and where
    there is none (another drive, a UNC share: os.path.relpath raises)."""
    ref = {"abs": os.path.abspath(path)}
    if base_dir:
        try:
            ref["rel"] = os.path.relpath(ref["abs"], os.path.abspath(base_dir)).replace(os.sep, "/")
        except ValueError:
            pass
    return ref


def _ref(v) -> dict | None:
    """A file reference as read: {"abs"?, "rel"?} (a plain path string is taken too); None when it has neither."""
    if isinstance(v, str) and v:
        v = {"abs": v} if os.path.isabs(v) else {"rel": v}
    if not isinstance(v, dict):
        return None
    out = {}
    if isinstance(v.get("abs"), str) and os.path.isabs(v["abs"]):
        out["abs"] = v["abs"]
    if isinstance(v.get("rel"), str) and v["rel"]:
        out["rel"] = v["rel"]
    return out or None


def _goes_up(rel: str) -> bool:
    return rel.replace("\\", "/").split("/", 1)[0] == ".."


def _candidates(ref, base_dir: str | None) -> list[str]:
    """Where a reference may be, in the order tried. base_dir/rel first when it stays inside base_dir (the data
    sits with the session, and the two may have moved together); otherwise abs first, then rel: a rel full of
    '..' is fragile, and would open a copied project's files rather than the originals."""
    ref = _ref(ref)
    if ref is None:
        return []
    rel, ab = ref.get("rel"), ref.get("abs")
    r = os.path.normpath(os.path.join(base_dir, rel)) if rel and base_dir else None
    a = os.path.normpath(ab) if ab else None
    order = [r, a] if r and not _goes_up(rel) else [a, r]
    return list(dict.fromkeys(p for p in order if p))


def resolve(ref, base_dir: str | None, folder: bool = False) -> str | None:
    """The file (folder=True: folder) a reference points to that exists now, by _candidates' order; None when
    none does."""
    exists = os.path.isdir if folder else os.path.isfile
    return next((os.path.abspath(p) for p in _candidates(ref, base_dir) if exists(p)), None)


def ref_text(ref) -> str:
    """For messages: the absolute path, else the relative one."""
    ref = _ref(ref) or {}
    return ref.get("abs") or ref.get("rel") or "?"


def _rebase_ref(ref, old_base: str | None, new_base: str | None) -> dict | None:
    if ref is None:
        return None
    path = resolve(ref, old_base) or next(iter(_candidates(ref, old_base)), None)
    return portable(path, new_base) if path else _ref(ref)


def rebase_entry(entry: dict, old_base: str | None, new_base: str | None) -> dict:
    """A motion entry with its file and label references (file, labels.file / rules, labels.origin.file / rules)
    made relative to new_base: each is found from old_base (else taken where it would be), then portable(). With
    new_base None they are absolute only (how unopened entries are kept: Restore.carry); with old_base None they
    are found by their absolute path (capture does so with the kept ones)."""
    e = dict(entry)
    e["file"] = _rebase_ref(entry.get("file"), old_base, new_base)
    lab = entry.get("labels")
    if isinstance(lab, dict):
        lab = dict(lab)
        for k in ("file", "rules"):
            if lab.get(k) is not None:
                lab[k] = _rebase_ref(lab[k], old_base, new_base)
        if isinstance(lab.get("origin"), dict):
            lab["origin"] = dict(lab["origin"])
            for k in ("file", "rules"):
                if lab["origin"].get(k) is not None:
                    lab["origin"][k] = _rebase_ref(lab["origin"][k], old_base, new_base)
        e["labels"] = lab
    return e


# ---------------------------------------------------------------- labels in the session
def _segment_state(s: Segment) -> dict:
    """{"label", "start_s", "end_s", "track"?, "name"?, "note"?, "color"?: "#rrggbb"}: times in full (json
    writes floats at round-trip precision, so a boundary on frame k/30 reads back the same)."""
    d = {"label": s.label, "start_s": float(s.start), "end_s": float(s.end)}
    for k in ("track", "name", "note"):
        if getattr(s, k):
            d[k] = getattr(s, k)
    if s.color:
        d["color"] = _hex(s.color)
    return d


def _segment(d: dict) -> Segment:
    return Segment(label=d["label"], start=d["start_s"], end=d["end_s"], track=d.get("track", ""),
                   name=d.get("name", ""), note=d.get("note", ""), color=_rgb(d.get("color")))


def labels_state(item: Item, base_dir: str | None) -> dict:
    """Where the motion's labels come from, as the session keeps it:
    {"from": "find"}: found next to the motion, or none there: opening looks again, as opening a motion does;
    {"from": "none"}: taken off although a label file is next to the motion: they stay off;
    {"from": "file", "file": ref}: a file picked by hand, read again;
    {"from": "auto", "rules": ref, "name", "segments", "notes"}: 자동 라벨 as they are (opening does not run the
    rules; 다시 읽기 does);
    {"from": "edited", "origin": {"from": "file" | "find" | "auto" | "none", "file"?, "rules"?, "name"?},
    "segments", "notes"}: changed in RetLens and not saved to a file, so the session may be the only place they
    exist ("none": made in RetLens on a motion that had none)."""
    lab = item.labels
    if lab is None:  # taken off, or none there: whether opening it would find labels (as MotionScene does)
        solved = item.info.get("solved_motion")
        try:
            there = motion_labels.load_for(item.source, item.robot.fps, item.robot.duration,
                                           also=[solved] if solved else ()) is not None
        except Exception:  # noqa: BLE001  (a broken file next to it: it would be found, with its error)
            there = True
        return {"from": "none" if there else "find"}
    if getattr(lab, "edited", False):
        if lab.auto:
            origin = {"from": "auto", "rules": portable(lab.path, base_dir) if lab.path else None, "name": lab.auto}
        elif lab.found or lab.path:
            origin = {"from": "find" if lab.found else "file"}
            if lab.path:
                origin["file"] = portable(lab.path, base_dir)
        else:
            origin = {"from": "none"}
        return {"from": "edited", "origin": origin, "segments": [_segment_state(s) for s in lab.segments],
                "notes": list(lab.notes)}
    if lab.auto:
        return {"from": "auto", "rules": portable(lab.path, base_dir) if lab.path else None, "name": lab.auto,
                "segments": [_segment_state(s) for s in lab.segments], "notes": list(lab.notes)}
    if lab.found or not lab.path:  # not lab.path: looking next to the motion failed (its error)
        return {"from": "find"}
    return {"from": "file", "file": portable(lab.path, base_dir)}


def _segments_read(v, notes: list, name: str) -> list[dict]:
    out, bad = [], 0
    for d in v if isinstance(v, list) else ():
        label = d.get("label") if isinstance(d, dict) else None
        start = _float(d.get("start_s"), None) if isinstance(d, dict) else None
        end = _float(d.get("end_s"), None) if isinstance(d, dict) else None
        if not (isinstance(label, str) and label and start is not None and end is not None and end > start):
            bad += 1
            continue
        s = {"label": label, "start_s": start, "end_s": end}
        for k in ("track", "name", "note"):
            if isinstance(d.get(k), str) and d[k]:
                s[k] = d[k]
        if _rgb(d.get("color")):
            s["color"] = _hex(_rgb(d["color"]))
        out.append(s)
    if bad:
        notes.append(f"{name}: 잘못된 라벨 구간 {bad}개는 뺐습니다")
    return out


def _labels_read(v, notes: list, name: str) -> dict:
    """A labels state as read; a kind it does not know (or a broken one) looks next to the motion ("find")."""
    if not isinstance(v, dict) or v.get("from") not in LABEL_KINDS:
        return {"from": "find"}
    kind = v["from"]
    if kind == "file":
        ref = _ref(v.get("file"))
        return {"from": "file", "file": ref} if ref else {"from": "find"}
    if kind == "auto":
        return {"from": "auto", "rules": _ref(v.get("rules")), "name": _str(v.get("name")) or "규칙",
                "segments": _segments_read(v.get("segments"), notes, name), "notes": _notes(v.get("notes"))}
    if kind == "edited":
        o = v.get("origin") if isinstance(v.get("origin"), dict) else {}
        origin = {"from": o.get("from") if o.get("from") in ("file", "find", "auto", "none") else "none"}
        if origin["from"] in ("file", "find") and _ref(o.get("file")):
            origin["file"] = _ref(o.get("file"))
        elif origin["from"] == "file":
            origin = {"from": "none"}
        if origin["from"] == "auto":
            origin.update(rules=_ref(o.get("rules")), name=_str(o.get("name")) or "규칙")
        return {"from": "edited", "origin": origin, "segments": _segments_read(v.get("segments"), notes, name),
                "notes": _notes(v.get("notes"))}
    return {"from": kind}


def _notes(v) -> list[str]:
    return [n for n in v if isinstance(n, str)] if isinstance(v, list) else []


def _where(ref, base_dir: str | None) -> str:
    """A label / rule file's path for MotionLabels: where it is now, else where it was."""
    if not ref:
        return ""
    return resolve(ref, base_dir) or next(iter(_candidates(ref, base_dir)), "")


def _apply_labels(scene: MotionScene, item: Item, state: dict, base_dir: str | None, name: str) -> list[str]:
    """Put a labels state on a loaded motion (before it is shown: no events). "find" looks next to the motion as
    opening it does (scene.add leaves that to its prepare)."""
    kind, notes = state.get("from", "find"), []
    if kind == "find":
        scene._find_labels(item)
    elif kind == "none":
        item.labels = None
    elif kind == "file":
        path = resolve(state["file"], base_dir)
        if path is None:  # read anyway: the inspector, the timeline's ⚠ and the report show the error
            path = _where(state["file"], base_dir) or ref_text(state["file"])
            notes.append(f"{name}: 라벨 파일 없음: {path}")
        solved = item.info.get("solved_motion")
        item.labels = motion_labels.load(path, item.source, item.robot.fps, item.robot.duration,
                                         also=[solved] if solved else ())
    elif kind in ("auto", "edited"):
        segs = [_segment(d) for d in state.get("segments", ())]
        for s in segs:
            motion_labels.color_for(s)  # as reading a label file does
        if kind == "auto":
            item.labels = MotionLabels(path=_where(state.get("rules"), base_dir), segments=segs,
                                       notes=list(state.get("notes", ())), auto=state.get("name") or "규칙")
        else:
            o = state.get("origin") or {"from": "none"}
            auto = o["from"] == "auto"
            item.labels = MotionLabels(path=_where(o.get("rules") if auto else o.get("file"), base_dir), segments=segs,
                                       notes=list(state.get("notes", ())), auto=(o.get("name") or "규칙") if auto else "",
                                       found=o["from"] == "find", edited=True)
    if kind != "find":
        lab = item.labels
        scene.log(f"  {name}: labels from the work session ({kind}): "
                  + ("-" if lab is None else lab.error or f"{len(lab.segments)} segments"))
    return notes


# ---------------------------------------------------------------- capture
def _solo_visible(scene: MotionScene) -> dict:
    """{id(item): visibility before} while 유형별 재생 shows one motion at a time (solo); its snapshot is the
    truth only then (without solo it goes stale as visibility changes)."""
    pl = scene.playlist
    return pl["visible"] if pl is not None and pl.get("solo") else {}


def item_state(item: Item, base_dir: str | None, visible: bool | None = None) -> dict:
    """One open motion as a session entry. visible: its own visibility when the view shows another for now (solo)."""
    e = {"file": portable(item.source, base_dir), "label": item.label, "kind": item.kind,
         "retarget": dict(item.retarget) if item.retarget else None,  # None: a robot motion, opened as it is
         "color": tuple(int(c) for c in item.color), "offset_s": float(item.offset),
         "visible": bool(item.visible if visible is None else visible), "show_human": bool(item.show_human),
         "labels": labels_state(item, base_dir)}
    prev = item.info.get("previous_retarget")
    if prev:
        e["previous_retarget"] = dict(prev)
    return e


def _pair(scene: MotionScene, items: list) -> tuple[int, int] | None:
    """The overlay comparison's A and B as indices, on or off (the panel keeps them while off)."""
    c = scene.compare
    if c.ref is None or c.item is None or c.ref is c.item:
        return None
    try:
        return items.index(c.ref), items.index(c.item)
    except ValueError:
        return None


def _reported(camera) -> bool:
    """The client has sent its camera (viser's camera properties assert until it has)."""
    try:
        return camera.update_timestamp > 0
    except AssertionError:
        return False


def camera_now(scene: MotionScene) -> dict | None:
    """{"position", "look_at", "fov"} of the first client that has sent its camera; None without one."""
    for client in list(scene.server.get_clients().values()):
        cam = client.camera
        if _reported(cam):
            return {"position": [float(x) for x in cam.position], "look_at": [float(x) for x in cam.look_at],
                    "fov": float(cam.fov)}
    return None


def capture(scene: MotionScene, base_dir: str | None, carry=()) -> dict:
    """The scene's working state as a session (write() it): the open motions in order, then `carry` (entries
    that were not opened, as Restore.carry gives them; made relative to base_dir here), the overlay comparison,
    scene settings, playhead, camera, physics mode, the 리타게팅 menu and the label colours. The window adds
    "selected" (an index into motions) and "analysis"."""
    with scene.lock:
        items = list(scene.items)
    solo = _solo_visible(scene)
    c = scene.compare
    compare = {"on": scene.compare_pair() is not None, "heading": bool(c.heading), "tol_cm": float(c.tol_cm)}
    pair = _pair(scene, items)
    if pair is not None:
        compare["a"], compare["b"] = pair
    prof = scene.robot_profile
    data = {"format": FORMAT, "version": VERSION, "app_version": __version__,
            "robot": prof.key if prof.builtin else prof.name, "robot_ident": prof.ident,
            "motions": [item_state(it, base_dir, solo.get(id(it), it.visible)) for it in items]
            + [rebase_entry(e, None, base_dir) for e in carry],
            "compare": compare, "view": asdict(scene.view), "time_s": float(scene.t),
            "physics": {"on": bool(scene.physics_on), "balance": scene.balance, "assist": float(scene.assist)},
            "retarget_next": {k: v for k, v in scene.retarget_settings().items() if k != "smooth_hz"},
            "label_colors": {k: _hex(v) for k, v in dict(motion_labels._colors).items()}}
    cam = camera_now(scene)
    if cam is not None:
        data["camera"] = cam
    return data


def fingerprint(scene: MotionScene, carry=()) -> tuple:
    """What a save would change, cheaply, for the title's unsaved mark (compare two with ==): per motion its file,
    corrections, offset, own visibility, skeleton, colour and labels (the MotionLabels objects themselves, not
    their id, which a new object may reuse: an edit replaces them, and == compares their fields, so labels read
    again unchanged are no change), the view without the speed, the comparison's pair / heading / tolerance,
    the 균형 제어 and assist, the 리타게팅 menu and the kept entries. Left out: time, selection, camera, speed and
    the physics / comparison on-off switches (P and O are flipped all the time)."""
    with scene.lock:
        items = list(scene.items)
    solo = _solo_visible(scene)
    c = scene.compare
    return (tuple((it.source, tuple(sorted(it.retarget.items())), it.offset, solo.get(id(it), it.visible),
                   it.show_human, tuple(it.color), it.labels) for it in items),
            tuple(getattr(scene.view, f.name) for f in fields(ViewSettings) if f.name != "speed"),
            _pair(scene, items), c.heading, c.tol_cm, scene.balance, scene.assist,
            tuple(sorted(scene.retarget_settings().items())), len(carry))


# ---------------------------------------------------------------- write / read
def write(path: str, data: dict) -> str:
    """Write a session atomically (a temporary file in the same folder, then os.replace: a crash or a full disk
    never leaves half a file) as UTF-8 JSON with the Korean as it is. Returns the absolute path; raises OSError."""
    from .api_core import jsonable  # here: api_core may import this module

    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    body = {k: v for k, v in data.items() if k not in ("format", "version", "app_version", "saved_at", "notes")}
    out = {"format": FORMAT, "version": VERSION, "app_version": __version__,
           "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **body}
    text = json.dumps(jsonable(out), ensure_ascii=False, indent=1) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def read(path: str) -> dict:
    """A session file, checked (parse); SessionError when it cannot be read or is not a session. Nothing else
    happens, so a caller changes nothing when this raises."""
    name = os.path.basename(path)
    try:
        if os.path.getsize(path) > MAX_BYTES:
            raise SessionError(f"RetLens 작업 세션 파일이 아닙니다: {name} (너무 큼)")
        with open(path, encoding="utf-8-sig") as f:  # Notepad may have added a BOM
            raw = json.load(f)
    except OSError as e:
        raise SessionError(f"작업 세션 파일을 읽지 못했습니다: {name} ({e.strerror or type(e).__name__})") from e
    except (ValueError, RecursionError) as e:  # not JSON, not UTF-8
        raise SessionError(f"작업 세션 파일을 읽지 못했습니다: {name} ({e})") from e
    return parse(raw, name)


def parse(raw, name: str = "") -> dict:
    """A session's JSON as loaded -> the data restore takes: every value checked and converted (true / false,
    numbers clamped to what the window offers, colours to PALETTE tuples, indices in range), defaults for what
    is missing, unknown keys left out (an entry keeps its own, so one carried over is written back with them).
    "notes": what reading changed or will not use (not written back). SessionError when it is not a session."""
    what = f": {name}" if name else ""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise SessionError(f"RetLens 작업 세션 파일이 아닙니다{what}")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SessionError(f"작업 세션 파일을 읽지 못했습니다{what} (버전 정보가 없거나 잘못됨)")
    notes: list[str] = []
    app_version = _str(raw.get("app_version"))
    if version > VERSION:
        notes.append(f"더 새 RetLens({app_version or f'세션 버전 {version}'})에서 저장한 작업 세션입니다. 아는 항목만 엽니다")
    motions = [_entry(m, notes) for m in (raw.get("motions") if isinstance(raw.get("motions"), list) else ())]
    n = len(motions)
    out = {"format": FORMAT, "version": version, "app_version": app_version, "saved_at": _str(raw.get("saved_at")),
           "robot": _str(raw.get("robot")),
           "robot_ident": raw.get("robot_ident") if isinstance(raw.get("robot_ident"), dict) else None,
           "motions": motions, "selected": _index(raw.get("selected"), n),
           "compare": _compare_read(raw.get("compare"), n), "view": _view_read(raw.get("view")),
           "time_s": _float(raw.get("time_s"), 0.0), "camera": _camera_read(raw.get("camera")),
           "physics": _physics_read(raw.get("physics"), notes),
           "retarget_next": _retarget_next_read(raw.get("retarget_next")), "analysis": _analysis_read(raw.get("analysis"), n),
           "label_colors": _label_colors_read(raw.get("label_colors"))}
    if "dirty" in raw:  # 자동 저장 only
        out["dirty"] = _bool(raw["dirty"], False)
    if "session_path" in raw:
        out["session_path"] = _str(raw["session_path"]) or None
    out["notes"] = notes
    return out


def _entry(v, notes: list) -> dict:
    """One motion entry, checked; a malformed one has file None (BAD_ENTRY when opened, kept like any other)."""
    raw = v if isinstance(v, dict) else {}
    file = _ref(raw.get("file"))
    name = _str(raw.get("label")) or (os.path.splitext(os.path.basename(ref_text(file)))[0] if file else "?")
    e = {**raw, "file": file, "label": name, "kind": _str(raw.get("kind")),
         "retarget": _retarget_read(raw.get("retarget")), "color": _color(raw.get("color")),
         "offset_s": _float(raw.get("offset_s"), 0.0, *OFFSET_S),
         "visible": _bool(raw.get("visible"), True), "show_human": _bool(raw.get("show_human"), True),
         "labels": _labels_read(raw.get("labels"), notes, name)}
    prev = raw.get("previous_retarget")
    e.pop("previous_retarget", None)
    if isinstance(prev, dict):
        e["previous_retarget"] = {"foot_flat": _bool(prev.get("foot_flat"), False),
                                  "swing_clearance_cm": _float(prev.get("swing_clearance_cm"), 0.0, 0.0, SWING_MAX_CM),
                                  "self_collision": _bool(prev.get("self_collision"), False),
                                  "score": _float(prev.get("score"), None)}
    return e


def _retarget_read(v) -> dict | None:
    """A motion's corrections ({smooth_hz, foot_flat, swing_clearance_cm, self_collision}, those given: scene.add
    takes the 리타게팅 menu's for the rest); None: a robot motion (opened as it is)."""
    if not isinstance(v, dict):
        return None
    out = {}
    smooth = _float(v.get("smooth_hz"), None, 0.0)
    if smooth is not None:
        out["smooth_hz"] = smooth
    for k in ("foot_flat", "self_collision"):
        if k in v:
            out[k] = _bool(v[k], False)
    if "swing_clearance_cm" in v:
        out["swing_clearance_cm"] = _float(v["swing_clearance_cm"], 0.0, 0.0, SWING_MAX_CM)
    return out or None


def _view_read(v) -> dict:
    raw, out = v if isinstance(v, dict) else {}, asdict(ViewSettings())
    for f in fields(ViewSettings):
        if f.name not in raw:
            continue
        default = out[f.name]
        if isinstance(default, bool):
            out[f.name] = _bool(raw[f.name], default)
        elif f.name == "spacing":
            out[f.name] = _float(raw[f.name], default, *SPACING)
        elif f.name == "speed":
            s = _float(raw[f.name], default)
            out[f.name] = s if s > 0 else default
        else:
            out[f.name] = _float(raw[f.name], default)
    return out


def _compare_read(v, n: int) -> dict:
    raw = v if isinstance(v, dict) else {}
    out = {"on": _bool(raw.get("on"), False), "heading": _bool(raw.get("heading"), True),
           "tol_cm": _float(raw.get("tol_cm"), 3.0, *TOL_CM)}
    a, b = _index(raw.get("a"), n), _index(raw.get("b"), n)
    if a is not None and b is not None and a != b:
        out["a"], out["b"] = a, b
    return out


def _camera_read(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    pos, at = _vec3(v.get("position")), _vec3(v.get("look_at"))
    if pos is None or at is None or pos == at:
        return None
    out = {"position": pos, "look_at": at}
    fov = _float(v.get("fov"), None)
    if fov is not None and 0.0 < fov < math.pi:
        out["fov"] = fov
    return out


def _physics_read(v, notes: list) -> dict:
    raw = v if isinstance(v, dict) else {}
    balance = raw.get("balance", "harness")
    if not (isinstance(balance, str) and balance in BALANCE):
        notes.append(f"균형 제어 '{balance}'을(를) 몰라 {BALANCE['harness']}(으)로 엽니다")
        balance = "harness"
    assist = _float(raw.get("assist"), 1.0)
    return {"on": _bool(raw.get("on"), False), "balance": balance, "assist": assist if assist in ASSIST else 1.0}


def _retarget_next_read(v) -> dict:
    raw = v if isinstance(v, dict) else {}
    return {"foot_flat": _bool(raw.get("foot_flat"), False),
            "swing_clearance_cm": _float(raw.get("swing_clearance_cm"), 0.0, 0.0, SWING_MAX_CM),
            "self_collision": _bool(raw.get("self_collision"), False)}


def _analysis_read(v, n: int) -> dict | None:
    """The 분석 tab as the window saved it: "ref" (an index into motions) checked, "graph" text, "follow_s"."""
    if not isinstance(v, dict):
        return None
    out = {**v, "ref": _index(v.get("ref"), n)}
    if "graph" in v:
        out["graph"] = _str(v["graph"])
    if "follow_s" in v:
        out["follow_s"] = _float(v["follow_s"], 10.0)
    return out


def _label_colors_read(v) -> dict:
    if not isinstance(v, dict):
        return {}
    return {k: _hex(_rgb(c)) for k, c in v.items() if isinstance(k, str) and _rgb(c)}


# ---------------------------------------------------------------- restore
def entry_label(entry) -> str:
    return (_str(entry.get("label")) or "?") if isinstance(entry, dict) else "?"


def clear(scene: MotionScene) -> None:
    """닫고 열기's first step: label playback and playback stopped, the overlay comparison off, every motion
    removed (with its jobs)."""
    scene.stop_segments()
    if scene.playing:
        scene.set_playing(False)
    if scene.compare.on:
        scene.set_compare(on=False)
    for it in list(scene.items):
        scene.remove(it)
    with scene.lock:  # the pair would keep the removed motions (and their arrays) alive
        scene.compare.ref = scene.compare.item = None


def mujoco_ready(scene: MotionScene) -> Callable[[str], str]:
    """physics_ready for a restore nobody watches (start-up, the API): MuJoCo 보조 힘 / 없음 when they can run
    here; GMT and Isaac stay off (heavy jobs at once, the Isaac EULA)."""
    return lambda b: scene.balance_problem(b) if b in ("harness", "pd") else AUTO_OFF


def apply_before(scene: MotionScene, data: dict, physics_ready: Callable[[str], str] | None = None) -> list[str]:
    """닫고 열기, before the motions load (so scene.add already honours it): scene settings, the 리타게팅 menu, the
    comparison's heading and tolerance, the physics mode and the label colours. physics_ready(balance) -> '' when
    that 균형 제어 may be turned on now, else why not (the window may ask for what is missing first; on the GUI
    thread, so it marshals). Without it physics stays off. Returns notes."""
    notes = []
    view = data.get("view") or {}
    for f in fields(ViewSettings):
        if f.name in view:
            setattr(scene.view, f.name, view[f.name])
    scene.view_changed("robot_translucent", "body_mesh")
    try:
        scene.set_retarget(**(data.get("retarget_next") or {}))
    except (TypeError, ValueError) as e:
        notes.append(f"리타게팅 보정: {e}")
    c = data.get("compare") or {}
    scene.set_compare(heading=c.get("heading", True), tol_cm=c.get("tol_cm", 3.0))
    phys = data.get("physics") or {}
    b = phys.get("balance", "harness")
    if scene.physics_on:
        scene.set_physics(False, WHY)
    if scene.assist != phys.get("assist", 1.0):
        scene.set_assist(phys.get("assist", 1.0))
    if scene.balance != b:
        scene.set_balance(b)  # off too, so the 물리 menu shows the saved mode
    if phys.get("on"):
        why = physics_ready(b) if physics_ready is not None else None
        if why == "":
            scene.set_physics(True, WHY)
        elif why is None:
            notes.append(f"물리 모드는 끈 채로 열었습니다 (저장할 때는 {BALANCE[b]} 켜짐)")
        elif why == AUTO_OFF:
            notes.append(f"물리 모드: {BALANCE[b]}은(는) 자동으로 켜지 않아 끈 채로 열었습니다 (P로 켭니다)")
        else:
            notes.append(f"물리 모드: {BALANCE[b]}을(를) 쓸 수 없어 끈 채로 열었습니다 ({why})")
    colors = {k: _rgb(v) for k, v in (data.get("label_colors") or {}).items() if _rgb(v)}
    motion_labels._colors.clear()  # each label as it was coloured then; new ones go on from there
    motion_labels._colors.update(colors)
    return notes


def apply_item_state(scene: MotionScene, item: Item, entry: dict, base_dir: str | None) -> list[str]:
    """An entry's state on its loaded motion: time offset, visibility, skeleton on/off, the corrections it
    replaced (info["previous_retarget"]) and its labels. Only assigns, no events: it is scene.add's prepare,
    before the motion is shown (on one already shown, emit "item" after). Returns notes."""
    item.offset = float(entry.get("offset_s", 0.0))
    item.visible = bool(entry.get("visible", True))
    item.show_human = bool(entry.get("show_human", True))
    if entry.get("previous_retarget"):
        item.info["previous_retarget"] = dict(entry["previous_retarget"])
    return _apply_labels(scene, item, entry.get("labels") or {"from": "find"}, base_dir, entry_label(entry))


class _Cancelled(Exception):
    pass


CANCELLED = "cancelled"  # load_entry's reason when the restore was cancelled while the motion loaded


def load_entry(scene: MotionScene, entry: dict, base_dir: str | None,
               cancelled: Callable[[], bool] | None = None) -> tuple[Item | None, str, list[str]]:
    """Open one motion of a session: (item, '', notes), or (None, why not, notes) - never raises. Its file is found
    by resolve; it is retargeted with its own corrections, gets its colour when free, and its state before it is
    shown (apply_item_state). cancelled() true once it has loaded: it is not shown at all (CANCELLED)."""
    notes: list[str] = []
    ref = entry.get("file") if isinstance(entry, dict) else None
    if not ref:
        return None, BAD_ENTRY, notes
    path = resolve(ref, base_dir)
    if path is None:
        return None, f"파일 없음: {ref_text(ref)}", notes

    def prepare(it):
        if cancelled is not None and cancelled():
            raise _Cancelled
        notes.extend(apply_item_state(scene, it, entry, base_dir))

    try:
        item = scene.add(path, retarget=entry.get("retarget"), color=entry.get("color"), prepare=prepare)
    except _Cancelled:
        return None, CANCELLED, notes
    except Exception as e:  # a broken file, Blender or the SMPL-X model missing: the others still open
        return None, f"{os.path.basename(path)}: {type(e).__name__}: {e}", notes
    return item, "", notes


def set_camera(scene: MotionScene, cam: dict) -> None:
    """The view's camera there: server.initial_camera (a client that connects later, 뷰 초기화) and every client
    that has sent its camera (one that has not would assert)."""
    pos, at, fov = tuple(cam["position"]), tuple(cam["look_at"]), cam.get("fov")
    ic = scene.server.initial_camera
    ic.position, ic.look_at = pos, at
    if fov:
        ic.fov = fov
    for client in list(scene.server.get_clients().values()):
        if _reported(client.camera):
            client.camera.position = pos  # moves look_at along: set after
            client.camera.look_at = at
            if fov:
                client.camera.fov = fov


def apply_after(scene: MotionScene, data: dict, items: dict) -> list[str]:
    """닫고 열기, after the motions loaded (items: entry index -> Item): the comparison's pair from the indices,
    the playhead (paused; seek clamps it to the motions now open) and the camera when the session has one (else
    the caller fits it). Returns notes."""
    notes = []
    motions = data.get("motions") or []
    loaded = lambda i: items.get(i) if i is not None and items.get(i) in scene.items else None  # noqa: E731
    c = data.get("compare") or {}
    a, b = loaded(c.get("a")), loaded(c.get("b"))
    if a is not None and b is not None and a is not b:
        scene.set_compare(on=bool(c.get("on")), ref=a, item=b)
    elif c.get("on"):
        lost = [entry_label(motions[i]) for i in (c.get("a"), c.get("b"))
                if isinstance(i, int) and 0 <= i < len(motions) and loaded(i) is None]
        notes.append(f"겹쳐 비교: {', '.join(lost)}을(를) 열지 못해 끈 채로 열었습니다" if lost else
                     "겹쳐 비교: 비교할 두 모션이 없어 끈 채로 열었습니다")
    if scene.playing:
        scene.set_playing(False)
    scene.seek(_float(data.get("time_s"), 0.0))
    if data.get("camera"):
        try:
            set_camera(scene, data["camera"])
        except (ValueError, KeyError, TypeError) as e:  # look_at on the position: the camera stays
            notes.append(f"카메라: {e}")
    return notes


class Restore:
    """One opening of a session, sequential (labels "x (2)" and colours come out as they were). Make it on any
    thread, run() it on a worker; meanwhile the attributes tell how far it is (the window's status line, a
    save during it):

        items      {entry index: Item} opened (one the user removed since is still listed: item_at checks)
        failed     [(entry, why)]: not opened ("파일 없음: ..." / BAD_ENTRY / the load's error)
        pending()  entries not opened because the restore was cancelled (and while it runs, the rest)
        notes      what the user should know (version, physics left off, a comparison that could not be made)
        selected, analysis: the window's own fields, indices into the entries (item_at)
    """

    def __init__(self, data: dict, base_dir: str | None, mode: str = "replace"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.data, self.base_dir, self.mode = data, base_dir, mode
        self.entries: list[dict] = list(data.get("motions") or [])
        self.items: dict[int, Item] = {}
        self.failed: list[tuple[dict, str]] = []
        self.notes: list[str] = list(data.get("notes") or [])
        self.current = ""  # the label of the motion being opened
        self.cancelled = False
        self.finished = False
        self.scene: MotionScene | None = None
        self._next = 0  # the entry being opened, or the next one

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def done(self) -> int:
        return len(self.items) + len(self.failed)

    @property
    def selected(self) -> int | None:
        return self.data.get("selected")

    @property
    def analysis(self) -> dict | None:
        return self.data.get("analysis")

    def pending(self) -> list[dict]:
        return self.entries[self._next:]

    def item_at(self, index: int | None) -> Item | None:
        """The motion opened for this entry index, if it is still open."""
        it = self.items.get(index) if index is not None else None
        return it if it is not None and self.scene is not None and it in self.scene.items else None

    def carry(self) -> list[dict]:
        """The entries not opened (failed, then pending), absolute (rebase_entry to None): the window keeps them
        and capture writes them back on every save."""
        return [rebase_entry(e, self.base_dir, None) for e in [*(e for e, _ in self.failed), *self.pending()]]

    def run(self, scene: MotionScene, cancelled: Callable[[], bool] = lambda: False,
            progress: Callable[[int, int, str], None] | None = None,
            physics_ready: Callable[[str], str] | None = None) -> Restore:
        """replace: clear the scene, apply_before, open every entry, apply_after. add: open the entries only (the
        window's settings stay). cancelled() is asked before each motion and after it: a motion that finished
        opening after a cancel is removed again (a stale restore leaves nothing behind) and apply_after is
        skipped. progress(done, total, label) before each motion and at the end (label '')."""
        self.scene = scene
        try:
            if cancelled():  # stopped before it began: the scene stays as it is
                self.cancelled = True
                return self
            robot, ident, prof = self.data.get("robot"), self.data.get("robot_ident"), scene.robot_profile
            from ..robot_profile import same_robot

            other = not same_robot(ident, prof.ident) if ident else bool(robot) and robot != (
                prof.key if prof.builtin else prof.name)
            if other:
                self.notes.append(f"다른 로봇({robot})으로 저장한 작업 세션입니다. 지금 로봇({prof.name})으로 엽니다")
            if self.mode == "replace":
                clear(scene)
                self.notes += apply_before(scene, self.data, physics_ready)
            for i, entry in enumerate(self.entries):
                if cancelled():
                    self.cancelled = True
                    break
                self.current = entry_label(entry)
                if progress is not None:
                    progress(self.done, self.total, self.current)
                item, err, notes = load_entry(scene, entry, self.base_dir, cancelled)
                if err == CANCELLED:  # cancelled while it loaded: never shown, still to open
                    self.cancelled = True
                    break
                if item is not None and cancelled():
                    scene.remove(item)
                    self.cancelled = True
                    break
                self.notes += notes
                if item is None:
                    self.failed.append((entry, err))
                else:
                    self.items[i] = item
                self._next = i + 1
            self.current = ""
            if self.mode == "replace" and not self.cancelled:
                self.notes += apply_after(scene, self.data, self.items)
            if progress is not None:
                progress(self.done, self.total, "")
        finally:
            self.finished = True
        return self


def restore(scene: MotionScene, data: dict, base_dir: str | None, mode: str = "replace",
            cancelled: Callable[[], bool] = lambda: False, progress: Callable[[int, int, str], None] | None = None,
            physics_ready: Callable[[str], str] | None = None) -> Restore:
    """Open a session (read / parse) in the scene, on this thread: Restore(data, base_dir, mode).run(...).
    base_dir: the session file's folder (relative paths start there)."""
    return Restore(data, base_dir, mode).run(scene, cancelled, progress, physics_ready)


# ---------------------------------------------------------------- 자동 저장
def autosave_path(n: int = 0) -> str:
    """user_dir()/sessions/autosave.retlens; n=1: the one before it (autosave.1.retlens)."""
    return os.path.join(paths.user_dir(), "sessions", f"autosave{f'.{n}' if n else ''}{EXT}")


def _work_of(path: str):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f).get("work")
    except (OSError, ValueError, AttributeError):
        return None


def write_autosave(data: dict, dirty: bool, session_path: str | None = None, work: str | None = None) -> str:
    """자동 저장: data (capture) to autosave_path() with "dirty" (unsaved changes then: reopening it marks the window
    so, a clean one opens clean) and "session_path" (the session file that was open; None: untitled). When the
    autosave there holds other work (another `work` token, which the window makes anew each time it opens or
    clears a session; None: always), it is kept as autosave.1.retlens first, so forcing an autosave before
    닫고 열기 / 새 작업 세션 and closing later never loses the work they replaced; the same work overwrites its
    own. Raises OSError."""
    path = autosave_path()
    if os.path.isfile(path) and (work is None or _work_of(path) != work):
        os.replace(path, autosave_path(1))
    return write(path, {**data, "dirty": bool(dirty), "session_path": session_path, "work": work})


def autosave_info(n: int = 0) -> dict | None:
    """For the 최근 작업 세션 menu: {"path", "saved_at", "motions", "dirty", "session_path"} of the autosave (n=1:
    the one before); None when there is none or it cannot be read."""
    path = autosave_path(n)
    if not os.path.isfile(path):
        return None
    try:
        d = read(path)
    except SessionError:
        return None
    return {"path": path, "saved_at": d["saved_at"], "motions": len(d["motions"]), "dirty": d.get("dirty", False),
            "session_path": d.get("session_path")}
