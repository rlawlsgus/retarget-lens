"""The local HTTP API of a running RetLens, for AI agents and scripts.

    GET  /api/help                      every endpoint with its parameters
    GET  /api/status                    time, playback, physics, compare, open motions
    GET  /api/checks                    환경 점검
    GET  /api/library?query=walk        motion files in the motion folders
    POST /api/open      {"paths": [..]}                      load (retarget when needed), shown in the window; all
                                                             checked first (404 / 422: nothing opened), then
                                                             "failed": the ones that did not load (error if none did)
    POST /api/retarget  {"foot_flat"?, "swing_clearance_cm"?, "self_collision"?}   리타게팅 보정 for the human motions opened
                                                             next (open ones keep theirs: reopen to compare)
                        {"id", corrections...}  this motion retargeted again with them (the others: its own), in
                                                its place; {"id", "recommend": true}: the 8 combinations ranked by
                                                리타게팅 점수 (slow the first time: 8 retargets)
    POST /api/remove    {"id": .., "discard_edits"?}   409 when its labels have unsaved edits, unless discard_edits
    GET  /api/motion?id=..              one motion: QC, metrics, C3D QC, physics state
    POST /api/item      {"id", "visible"?, "offset_s"?, "show_human"?}
    POST /api/labels    {"id", "path"?}  labelled segments on the timeline: load this file / "path": null takes
                                         them off / no "path" reads the motion's label file again
                        {"id", "auto": true, "rules"?}  label the motion by a rule file (the 자동 라벨 setting
                                         when "rules" is left out; retlens.autolabel). 422 when it cannot
                                         (robot motion, broken rules): the motion keeps its labels. Replacing
                                         labels with unsaved edits (path, null, reload, auto): 409 unless
                                         "discard_edits": true
                        {"id", "edit": "bounds" | "rename" | "split" | "delete" | "merge" | "add" | "undo" | "redo",
                         "index"?, "expect"?: {"label", "start_s"}, ...}   label editing: bounds {"start_s"?,
                         "end_s"?}, rename {"label"}, split {"time_s"}, merge {"with": "next" | "prev"}, add {"track",
                         "time_s", "label"}; index into labels.segments (409 when "expect" no longer matches);
                         times in motion seconds, on frames. The reply's "segment": the edited / new segment's index
                        {"id", "save": true | "D:/x/02_01.labels.csv", "overwrite"?}   save the labels to a CSV
                         (true: <name>.labels.csv next to the motion); 409 over an existing file unless overwrite,
                         and always over a table of several motions or a file that is not a label file
    POST /api/playback  {"play"?, "time_s"?, "speed"?, "loop"?, "problem"?: 1 | -1, "id"?}   "problem": go to the
                                         next / previous problem start (of motion "id", else every visible one)
    GET  /api/segments                  유형별 재생: every 'track: label' of the open motions (segments, seconds)
    POST /api/segments  {"key", "solo"?, "play"?} | {"step": 1 | -1} | {"stop": true}   play one label's segments
                                         one after another (solo: only that segment's motion shown)
    GET  /api/session                   작업 세션: the file open, unsaved changes?, opening progress, what did
                                         not open
    POST /api/session   {"save": true | "C:/x.retlens", "overwrite"?}  save the window's work (409 over another
                                         file unless overwrite, or while one is being opened; 500 with the
                                         reason when it cannot be written; true: the file open)
                        {"open": "C:/x.retlens", "mode"?: "replace" | "add", "discard_changes"?}  open one
                                         (returns at once: GET until "restoring" is null); mode is needed while
                                         motions are open; replace with unsaved changes: 409 unless discard_changes
    GET  /api/batch                     데이터셋 일괄 처리 in the window: running?, totals, its rows so far
    POST /api/batch     {"folders", "physics"?, "auto_labels"?} | {"stop": true}   start (with the 리타게팅 menu's
                                         corrections) / stop after the current motion (retlens.batch); folders:
                                         a list of folders or motion files (or one), 404 when one is not there
    GET  /api/metrics?ref=..            the 분석 table (RMSE against ref)
    POST /api/align     {"ref"}         기준에 시간 자동 정렬
    POST /api/compare   {"a", "b", "heading"?, "tol_cm"?} / {"on": false}   겹쳐 비교 (+ its numbers, and offsets_s:
                                                                         the two motions' time offsets)
    POST /api/physics   {"on", "assist"?, "balance"?}       물리 모드; balance harness | pd | gmt (MuJoCo: pelvis
                                                             harness / no controller / GMT) | isaac (Isaac's harness,
                                                             x assist; needs the EULA accepted in the window)
    POST /api/video     {"id"}          동영상 저장 (queued; see /api/jobs)
    GET  /api/jobs                      physics (Isaac, MuJoCo) and video jobs
    POST /api/camera    {"fit": true}   카메라 맞추기
    POST /api/screenshot {"path"?}      a PNG of the window (default in the user's logs folder)

Safety: it listens on 127.0.0.1 only; every request needs the token (header
"Authorization: Bearer <token>" or "X-RetLens-Token"); requests a web browser makes (they carry
an Origin header) are refused, so web pages cannot drive it. The URL and token of the running
window are in <user data>\\api.json (discovery()); the token changes at every start.
Responses are JSON: {"ok": true, ...} or {"ok": false, "error": "..."} with an HTTP error code.
A motion "id" is its label, index, file name or absolute path (409 when a file name or path is several open
motions). true / false parameters also take 1 / 0 and their text ("false"); anything else, a number that is
not one or out of range (offset_s, speed, tol_cm, ...) is a 400 naming the parameter. A parameter repeated in
the query string (?paths=a&paths=b) is a list: right for paths and folders, a 400 (or 404 for an id) elsewhere.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .. import motion_labels, paths
from ..batch import totals as batch_totals
from . import api_core
from . import session as work
from .scene import BALANCE, SWING_MAX_CM

DEFAULT_PORT = 8765
SPEED = (0.01, 16.0)  # playback speeds the API takes (the timeline's list has 0.1-4x; it adds others it is given)


def discovery_path() -> str:
    return os.path.join(paths.user_dir(), "api.json")


def discovery() -> dict | None:
    """URL and token of the running RetLens's API (None when it is not running)."""
    try:
        with open(discovery_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if _alive(d.get("pid")) else None  # else a file left by a crashed run


def _alive(pid) -> bool:
    """Whether the process that wrote a discovery file still runs (assumed so off Windows)."""
    if not pid or os.name != "nt":
        return True
    import ctypes

    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


class ApiError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


# Parameters as given (JSON body, or a query string's text): a wrong type or value is the caller's 400 naming the
# parameter, never a 500 or a silently different value (bool("false") is True). Left out or null: default.
def _flag(q: dict, key: str, default=None):
    """true / false, 1 / 0 or their text ("false", "no", "off", ...)."""
    if q.get(key) is None:
        return default
    v = work._bool(q[key], None)
    if v is None:
        raise ApiError(f"'{key}' must be true or false", 400)
    return v


def _num(q: dict, key: str, default=None, lo: float | None = None, hi: float | None = None):
    """A finite number (or its text) in [lo, hi]."""
    v = q.get(key)
    if v is None:
        return default
    try:
        f = float("nan") if isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        f = float("nan")
    if not math.isfinite(f):
        raise ApiError(f"'{key}' must be a number", 400)
    if (lo is not None and f < lo) or (hi is not None and f > hi):
        span = (f"{lo:g} to {hi:g}" if lo is not None and hi is not None else
                f"at least {lo:g}" if lo is not None else f"at most {hi:g}")
        raise ApiError(f"'{key}' must be {span}, not {f:g}", 400)
    return f


def _int(q: dict, key: str, default=None, lo: int | None = None) -> int | None:
    """A whole number (or its text), at least lo."""
    v = q.get(key)
    if v is None:
        return default
    try:
        n = None if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()) else int(v)
    except (TypeError, ValueError):
        n = None
    if n is None or (lo is not None and n < lo):
        raise ApiError(f"'{key}' must be a whole number{'' if lo is None else f' of at least {lo}'}", 400)
    return n


def _text(q: dict, key: str, default=None):
    """Text (a query string's value, or a JSON string)."""
    v = q.get(key)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(f"'{key}' must be text", 400)
    return v


def _path_list(v, key: str) -> list[str]:
    """Paths: a list of them, or one (a single string is one path, not a list of its letters)."""
    if isinstance(v, str) and v:
        return [v]
    if isinstance(v, list) and v and all(isinstance(p, str) and p for p in v):
        return list(v)
    raise ApiError(f"'{key}' must be a list of paths", 400)


def _without_props(files: list[str]) -> tuple[list[str], list[dict]]:
    """(the files without a take's prop FBX files (retlens.props), [{path, why}] of those left out), as the window's
    open does: a prop file opened with its person's FBX is drawn with that motion, one alone has no person; a copy
    of it the person does not use (find_props' skipped: another file of the same name is drawn) says so."""
    from .. import props

    key = api_core.path_key
    fbx = [f for f in files if f.lower().endswith(".fbx")]
    if not fbx:
        return files, []
    try:
        is_prop = {f: props.is_prop_file(f) for f in fbx}
        used, copies = set(), {}
        for f in fbx:
            if not is_prop[f]:
                found, skipped = props.find_props(f)
                used |= {key(x) for x in found}
                copies.update({key(s["file"]): s["skipped"] for s in skipped})
    except Exception as e:  # noqa: BLE001  a folder that cannot be read: opened as given
        print(f"[api] prop files not checked: {type(e).__name__}: {e}", flush=True)
        return files, []
    left = []
    for f in fbx:
        k = key(f)
        if k in used:  # drawn by one of the people (another may skip it as a copy)
            left.append({"path": f, "why": "drawn with the person's motion of the same take (a prop file)"})
        elif k in copies:  # drawn nowhere: the person draws the other file of its name
            left.append({"path": f, "why": "another copy of this take's prop file is drawn with the person's motion "
                                           f"({copies[k]})"})
        elif is_prop[f]:
            left.append({"path": f, "why": "a prop-only FBX: open the person's FBX of the same take to see it"})
    gone = {s["path"] for s in left}
    return [f for f in files if f not in gone], left


class ApiBackend:
    """The endpoints, on a MotionScene. on_gui(fn) runs fn on the window's GUI thread and returns
    its result (screenshots); window hooks (EditorWindow) are optional, so the API also runs on a
    headless scene (tests)."""

    def __init__(self, scene, window=None, on_gui: Callable | None = None):
        self.scene, self.window = scene, window
        self.on_gui = on_gui or (lambda fn: fn())
        g, p = "GET", "POST"
        self.routes: dict[tuple[str, str], Callable[[dict], dict]] = {
            (g, "/api/help"): self.help, (g, "/api/status"): lambda q: api_core.status(self.scene),
            (g, "/api/checks"): lambda q: api_core.checks(),
            (g, "/api/library"): lambda q: api_core.library(_text(q, "query"), _int(q, "limit", 200, lo=0)),
            (p, "/api/open"): self.open, (p, "/api/retarget"): self.retarget, (p, "/api/remove"): self.remove,
            (g, "/api/motion"): self.motion,
            (p, "/api/item"): self.item, (p, "/api/labels"): self.labels, (p, "/api/playback"): self.playback,
            (g, "/api/segments"): self.segments, (p, "/api/segments"): self.segments,
            (g, "/api/batch"): self.batch, (p, "/api/batch"): self.batch,
            (g, "/api/session"): self.session, (p, "/api/session"): self.session,
            (g, "/api/metrics"): self.metrics,
            (p, "/api/align"): self.align, (p, "/api/compare"): self.compare, (p, "/api/physics"): self.physics,
            (p, "/api/video"): self.video, (g, "/api/jobs"): self.jobs, (p, "/api/camera"): self.camera,
            (p, "/api/screenshot"): self.screenshot,
        }

    # ---------------------------------------------------------------- helpers
    def _item(self, key):
        if key is None:
            raise ApiError("give the motion's id (label like 'cmu_bvh/02_01', index, file name or path)")
        try:
            return api_core.find_item(self.scene, key)
        except KeyError as e:  # its message, not str(e): that is the repr, in quotes
            raise ApiError(str(e.args[0]) if e.args else str(e),
                           409 if isinstance(e, api_core.AmbiguousItem) else 404) from None

    def help(self, q: dict) -> dict:
        from . import api_server

        return {"doc": api_server.__doc__, "endpoints": sorted(f"{m} {p}" for m, p in self.routes)}

    # ---------------------------------------------------------------- motions
    def open(self, q: dict) -> dict:
        """Every file checked first (nothing opens when one is missing or is no motion); then each one opened,
        those that fail to load listed in "failed" (an error only when none opened)."""
        if not (q.get("paths") or q.get("path")):
            raise ApiError("give 'paths': [file, ...]")
        files = _path_list(q["paths"], "paths") if q.get("paths") else _path_list(q["path"], "path")
        missing = [f for f in files if not os.path.isfile(f)]
        if missing:
            raise ApiError(f"no such file: {', '.join(missing)} (nothing opened)", 404)
        for f in files:
            if work.is_session_file(f):
                raise ApiError(f"{f} is a work session: open it with POST /api/session {{\"open\": path}} "
                               "(nothing opened)", 422)
            if motion_labels.is_label_file(f):
                raise ApiError(f"{f} is a label file, not a motion: put it on an open motion with POST /api/labels "
                               "{\"id\", \"path\"} (nothing opened)", 422)
        files, skipped = _without_props(files)
        if not files:
            raise ApiError("; ".join(f"{s['path']}: {s['why']}" for s in skipped) + " (nothing opened)", 422)
        out, failed = [], []
        for f in files:
            try:
                item = self.scene.add(f)  # retargets when needed (seconds on a cache miss)
            except Exception as e:  # a broken file, a missing tool (Blender): the others still open
                print(f"[api] could not open {f}: {type(e).__name__}: {e}", flush=True)
                failed.append((f, e))
                continue
            if self.window is not None:
                self.window.bridge.added.emit(item)  # the window selects it, fits the camera
            out.append(api_core.item_info(self.scene, item))
        if not out:  # a file it cannot read (ValueError: not a motion) is the caller's; anything else is a 500
            raise ApiError("; ".join(f"{f}: {type(e).__name__}: {e}" for f, e in failed),
                           422 if all(isinstance(e, ValueError) for _, e in failed) else 500)
        res = {"opened": out, "failed": [{"path": f, "error": f"{type(e).__name__}: {e}"} for f, e in failed]}
        if skipped:
            res["skipped"] = skipped
        return res

    def retarget(self, q: dict) -> dict:
        # all checked before any is applied: a refused request leaves the corrections as they were
        ff, scol, recommend = _flag(q, "foot_flat"), _flag(q, "self_collision"), _flag(q, "recommend", False)
        swing = _num(q, "swing_clearance_cm", None, 0.0, SWING_MAX_CM)  # 0: off
        if q.get("id") is not None:  # this motion only: again with other corrections, or the ranking of them all
            item = self._item(q["id"])
            try:
                if recommend:
                    return {"id": item.label, "score": item.metrics.get("retarget_score"),
                            "ranking": self.scene.recommend_retarget(item)}
                new = self.scene.retarget_again(item, foot_flat=ff, swing_clearance_cm=swing, self_collision=scol)
            except (TypeError, ValueError) as e:
                raise ApiError(str(e), 422) from None
            return {"id": new.label, "retarget": new.retarget, "score_before": item.metrics.get("retarget_score"),
                    "score": new.metrics.get("retarget_score")}
        try:
            r = self.scene.set_retarget(foot_flat=ff, swing_clearance_cm=swing, self_collision=scol)
        except (TypeError, ValueError) as e:
            raise ApiError(str(e)) from None
        return {"retarget": r, "note": "applies to the human motions opened next; open ones keep theirs"}

    def remove(self, q: dict) -> dict:
        item = self._item(q.get("id"))
        if self.scene.labels_dirty(item) and not _flag(q, "discard_edits", False):
            raise ApiError(f"{item.label}: its labels have unsaved edits: save them ({{\"save\": true}} on /api/labels) "
                           "or give \"discard_edits\": true", 409)
        self.scene.remove(item)
        return {"removed": item.label}

    def motion(self, q: dict) -> dict:
        return api_core.item_info(self.scene, self._item(q.get("id")))

    def item(self, q: dict) -> dict:
        item = self._item(q.get("id"))
        visible, show_human = _flag(q, "visible"), _flag(q, "show_human")  # all checked before any is applied
        offset = _num(q, "offset_s", None, *work.OFFSET_S)  # the inspector's 시간 오프셋 box
        if visible is not None:
            self.scene.set_visible(item, visible)
        if offset is not None:
            self.scene.set_offset(item, offset)
        if show_human is not None:
            self.scene.set_show_human(item, show_human)
        return api_core.item_info(self.scene, item, metrics=False)

    def labels(self, q: dict) -> dict:
        item = self._item(q.get("id"))
        if "edit" in q or "save" in q:
            if sum(k in q for k in ("edit", "save", "path", "auto")) > 1:
                raise ApiError("give one of 'edit', 'save', 'path' or \"auto\"", 400)
            return self._label_edit(item, q) if "edit" in q else self._label_save(item, q)
        if self.scene.labels_dirty(item) and not _flag(q, "discard_edits", False):
            raise ApiError(f"{item.label}: its labels have unsaved edits that this would replace: save them first "
                           "({\"save\": true}) or give \"discard_edits\": true (undo brings them back)", 409)
        for key in ("path", "rules"):
            if q.get(key) is not None and not isinstance(q[key], str):
                raise ApiError(f"'{key}' must be a file path (string) or null", 400)
        auto = _flag(q, "auto", False)
        if auto and "path" in q:
            raise ApiError("give \"auto\": true (labels by a rule file) or 'path' (a label file), not both", 400)
        if "rules" in q and not auto:
            raise ApiError("'rules' goes with \"auto\": true", 400)
        if auto:
            if q.get("rules") and not os.path.isfile(q["rules"]):
                raise ApiError(f"no such file: {q['rules']}", 404)
            lab = self.scene.auto_label(item, q.get("rules") or None)
        elif "path" not in q:
            lab = self.scene.reload_labels(item)
        elif q["path"] and not os.path.isfile(q["path"]):
            raise ApiError(f"no such file: {q['path']}", 404)
        else:
            lab = self.scene.set_labels(item, q["path"] or None)
        if lab is not None and lab.auto and lab.error and lab is not item.labels:  # not put on: the motion kept its labels
            raise ApiError(f"자동 라벨을 붙이지 못했습니다 (라벨은 그대로): {lab.error}", 422)
        return {"id": item.label, "labels": api_core.item_info(self.scene, item)["labels"]}

    def _label_edit(self, item, q: dict) -> dict:
        """One label edit (motion_labels), as the window's: one undo step of the motion."""
        sc, op = self.scene, q.get("edit")
        if op in ("undo", "redo"):
            done = sc.undo_labels(item, redo=op == "redo")
            if done is None:
                raise ApiError(f"nothing to {op}", 409)
            lab = item.labels
            seg = done[1]
            index = next((i for i, s in enumerate(lab.segments) if s is seg), None) if lab is not None else None
            return {"id": item.label, "done": done[0], "segment": index,
                    "labels": api_core.item_info(sc, item)["labels"]}
        base, fps, dur = item.labels, item.robot.fps, item.robot.duration
        seg = None
        if op != "add":
            if base is None or not isinstance(q.get("index"), int) or not 0 <= q["index"] < len(base.segments):
                raise ApiError("'index' must be the index of one of the motion's labels.segments", 404)
            seg = base.segments[q["index"]]
            exp = q.get("expect")
            if isinstance(exp, dict) and (exp.get("label", seg.label) != seg.label or
                                          abs(_num(exp, "start_s", seg.start) - seg.start) > 1e-4):
                raise ApiError("the segment at 'index' is not the one expected: the labels changed, read them again", 409)
        try:
            if op == "bounds":
                result = motion_labels.with_bounds(base, seg, float(q.get("start_s", seg.start)),
                                                   float(q.get("end_s", seg.end)), fps, dur)
            elif op == "rename":
                name = str(q.get("label", ""))
                result = motion_labels.relabeled(base, seg, name, sc.label_definition(name.strip(), seg.track, item))
            elif op == "split":
                result = motion_labels.split(base, seg, float(q["time_s"]), fps)
            elif op == "delete":
                result = motion_labels.removed(base, seg)
            elif op == "merge":
                result = motion_labels.merged(base, seg, -1 if q.get("with") == "prev" else 1)
            elif op == "add":
                track, name = str(q.get("track") or ""), str(q.get("label") or motion_labels.NEW_LABEL)
                result = motion_labels.added(base, track, float(q["time_s"]), fps, dur, name,
                                             sc.label_definition(name.strip(), track, item))
            else:
                raise ApiError("'edit' must be bounds, rename, split, delete, merge, add, undo or redo", 400)
        except (KeyError, TypeError) as e:
            raise ApiError(f"missing or wrong parameter for {op}: {e}", 400)
        except ValueError as e:
            raise ApiError(str(e), 422)
        new, sel = result
        what = {"bounds": "구간 시간 고치기", "rename": "라벨 바꾸기", "split": "구간 나누기", "delete": "구간 삭제",
                "merge": "구간 합치기", "add": "구간 추가"}[op]
        if not sc.edit_labels(item, base, new, what, before=seg, after=sel):
            raise ApiError("the labels changed meanwhile: read them again", 409)
        index = next((i for i, s in enumerate(new.segments) if s is sel), None) if sel is not None else None
        return {"id": item.label, "segment": index, "labels": api_core.item_info(sc, item)["labels"]}

    def _label_save(self, item, q: dict) -> dict:
        base, target = item.labels, q.get("save")
        if base is None:
            raise ApiError(f"{item.label}: no labels to save", 409)
        if work._bool(target, None) is True:  # true, 1 or their text (no absolute .csv path reads as one)
            target = os.path.splitext(item.source)[0] + ".labels.csv"
        if not isinstance(target, str) or not target.lower().endswith(".csv") or not os.path.isabs(target):
            raise ApiError("'save' must be true or an absolute path ending in .csv", 400)
        if not os.path.isdir(os.path.dirname(target)):
            raise ApiError(f"no such folder: {os.path.dirname(target)}", 404)
        solved = item.info.get("solved_motion")
        why = motion_labels.overwrite_problem(target, item.source, [solved] if solved else ())
        if why:
            raise ApiError(f"not saved over {target}: {why}", 409)
        if os.path.exists(target) and not _flag(q, "overwrite", False):
            raise ApiError(f"{target} exists: give \"overwrite\": true to replace it (what it would lose: "
                           f"{'; '.join(motion_labels.overwrite_losses(target, base)) or 'nothing noted'})", 409)
        try:
            motion_labels.save_csv(base, target)
        except OSError as e:
            raise ApiError(f"could not write {target}: {e}", 500)
        self.scene.labels_saved(item, base, target)
        return {"id": item.label, "saved": os.path.abspath(target), "labels": api_core.item_info(self.scene, item)["labels"]}

    def playback(self, q: dict) -> dict:
        sc = self.scene
        # all checked before any is applied (a negative speed would play back past the start for ever)
        speed, loop, t = _num(q, "speed", None, *SPEED), _flag(q, "loop"), _num(q, "time_s")
        problem, play = _int(q, "problem"), _flag(q, "play")
        if problem is not None and problem not in (1, -1):
            raise ApiError("'problem' must be 1 (next) or -1 (previous)", 400)
        target = self._item(q["id"]) if problem is not None and q.get("id") is not None else None
        if speed is not None:
            sc.view.speed = speed
        if loop is not None:
            sc.view.loop = loop
        if t is not None:
            sc.seek(t)
        out = {}
        if problem is not None:  # 다음 / 이전 문제로: +1 / -1, of one motion ("id") or every visible one
            stop = sc.next_problem(problem, target)
            out["problem"] = None if stop is None else {"time_s": stop[0], "kind": stop[1], "id": stop[2].label,
                                                        "motion_time_s": stop[0] - stop[2].offset}
        if play is not None:
            sc.set_playing(play)
        return {"time_s": sc.t, "playing": sc.playing, "speed": sc.view.speed, "time_range_s": list(sc.time_range()),
                **out}

    def segments(self, q: dict) -> dict:
        """유형별 재생: the labels of the open motions; {"key", "solo"?, "play"?} plays that label's segments one
        after another, {"step": 1 | -1} moves through them, {"stop": true} ends it."""
        sc = self.scene
        if _flag(q, "stop", False):
            sc.stop_segments()
            sc.set_playing(False)
        elif q.get("key") is not None:
            solo, play = _flag(q, "solo", False), _flag(q, "play", True)
            if not sc.play_segments(str(q["key"]), solo=solo, play=play):
                raise ApiError(f"no segment labelled {q['key']!r} in the open motions", 404)
        elif q.get("step") is not None:
            if sc.step_segment(_int(q, "step")) is None:
                raise ApiError("no label segments are being played: start with {\"key\": ...}", 409)
        return {"labels": sc.label_catalog(), "playing": sc.playlist_state(), "time_s": sc.t}

    def batch(self, q: dict) -> dict:
        """데이터셋 일괄 처리 in the window's 데이터셋 tab: {"folders", "physics"?, "auto_labels"?} starts it (the
        tab's folders replaced), {"stop": true} stops it after the current motion; GET: its rows so far."""
        if self.window is None:
            raise ApiError("일괄 처리 needs the RetLens window (retlens-cli batch runs it without one)", 409)
        panel = self.window.dataset

        def start():
            panel.folders = []
            panel.add_folders(folders)
            panel.physics.setChecked(physics)
            panel.auto.setChecked(auto)
            self.window.docks["dataset"].show()
            self.window.docks["dataset"].raise_()
            panel.run()

        if _flag(q, "stop", False):
            self.on_gui(panel._request_stop)
        elif q.get("folders"):
            # one string is one folder, not a list of its letters (a path's backslash alone is the drive's root)
            folders = _path_list(q["folders"], "folders")
            physics, auto = _flag(q, "physics", False), _flag(q, "auto_labels", False)
            missing = [f for f in folders if not os.path.exists(f)]
            if missing:
                raise ApiError(f"no such folder or file: {', '.join(missing)}", 404)
            if panel._running:
                raise ApiError("일괄 처리 is already running: {\"stop\": true} first", 409)
            self.on_gui(start)
        rows = list(panel.model.rows)
        return {"running": panel._running, "folders": list(panel.folders), **batch_totals(rows),
                "rows": api_core.jsonable(rows)}

    def session(self, q: dict) -> dict:
        """작업 세션 (retlens/app/session.py): save / open, in the window (headless: in this scene, synchronously)."""
        from . import session as work

        w = self.window
        if q.get("save") is not None:
            target = q["save"]
            if work._bool(target, None) is True:  # true, 1 or their text (no absolute path reads as one)
                target = w.session_path if w is not None else None
                if not target:
                    raise ApiError("no work session file is open: give a path (\"save\": \"C:/x.retlens\")", 409)
            elif not isinstance(target, str) or not os.path.isabs(target):
                raise ApiError("'save' must be true or an absolute path", 400)
            else:
                if not target.lower().endswith(work.EXTS):
                    target += work.EXT
                same = w is not None and w.session_path and \
                    api_core.path_key(target) == api_core.path_key(w.session_path)  # however written (8.3 names)
                if os.path.exists(target) and not same and not _flag(q, "overwrite", False):
                    raise ApiError(f"{target} exists: give \"overwrite\": true to replace it", 409)
            if not os.path.isdir(os.path.dirname(os.path.abspath(target))):
                raise ApiError(f"no such folder: {os.path.dirname(target)}", 404)
            if w is None:
                try:
                    path = work.write(target, work.capture(self.scene, os.path.dirname(os.path.abspath(target))))
                except OSError as e:
                    raise ApiError(f"could not write {target}: {e}", 500) from None
            else:
                def save():  # on the GUI thread, without the message box (it would wait for a click, and this request)
                    if w._restore is not None:  # a work session being opened: not now (save_session says the same)
                        return None, ""
                    return w.save_session(target, interactive=False), w._last_save_error

                ok, why = self.on_gui(save) or (False, "")  # nothing back: the window is closing
                if ok is None:
                    raise ApiError("not saved: a work session is being opened (GET /api/session until \"restoring\" "
                                   "is null)", 409)
                if not ok:
                    raise ApiError(f"could not write {target}: {why or 'not saved'}", 500)
                path = w.session_path
            return {"saved": os.path.abspath(path), "motions": len(self.scene.items)}
        if q.get("open") is not None:
            path, mode = q["open"], q.get("mode")
            if not isinstance(path, str) or not os.path.isfile(path):
                raise ApiError(f"no such file: {path}", 404)
            if mode is not None and mode not in work.MODES:
                raise ApiError(f"'mode' must be one of {', '.join(work.MODES)}", 400)
            if w is None:
                if self.scene.items and mode is None:
                    raise ApiError("motions are open: give mode replace or add", 409)
                if (mode or "replace") == "replace" and not _flag(q, "discard_changes", False) and \
                        any(self.scene.labels_dirty(it) for it in self.scene.items):
                    raise ApiError("labels have unsaved edits: save them first or give discard_changes", 409)
                try:
                    data = work.read(path)
                except work.SessionError as e:
                    raise ApiError(str(e), 400)
                r = work.restore(self.scene, data, os.path.dirname(os.path.abspath(path)), mode or "replace",
                                 physics_ready=work.mujoco_ready(self.scene))
                return {"opened": [it.label for it in r.items.values()], "failed": [
                    {"label": work.entry_label(e), "error": why} for e, why in r.failed], "notes": r.notes}
            discard = _flag(q, "discard_changes", False)
            code, why = self.on_gui(lambda: w.open_session(path, mode, interactive=False, discard=discard))
            if code:
                raise ApiError(why, code)
        return self._session_state()

    def _session_state(self) -> dict:
        from . import session as work

        w = self.window
        if w is None:
            return {"path": None, "dirty": None, "restoring": None, "unresolved": [], "autosave": work.autosave_info()}
        r = w._restore
        return {"path": w.session_path, "dirty": w._session_dirty() if w.session_path else None,
                "restoring": {"done": r.done, "total": r.total, "current": r.current} if r is not None else None,
                "unresolved": [{"label": work.entry_label(e), "file": work.ref_text(e.get("file"))} for e in w._carry_list()],
                "last_open": w._last_restore, "autosave": work.autosave_info(), "recent": w._recent()}

    # ---------------------------------------------------------------- analysis
    def metrics(self, q: dict) -> dict:
        ref = self._item(q["ref"]) if q.get("ref") is not None else None
        return api_core.metrics_table(self.scene, ref)

    def align(self, q: dict) -> dict:
        return api_core.align(self.scene, self._item(q.get("ref")))

    def compare(self, q: dict) -> dict:
        if _flag(q, "on", True) is False:
            self.scene.set_compare(on=False)
            return {"compare": "off"}
        a, b = self._item(q.get("a")), self._item(q.get("b"))
        if a is b:
            raise ApiError("a and b must be different motions")
        heading, tol = _flag(q, "heading", True), _num(q, "tol_cm", 3.0, *work.TOL_CM)  # the 비교 tab's 허용 오차 box
        out = api_core.compare(self.scene, a, b, heading=heading, tol_cm=tol)
        if self.window is not None:
            self.on_gui(lambda: self.window.docks["compare"].raise_())
        return out

    # ---------------------------------------------------------------- Isaac
    def _eula(self) -> None:
        ok = self.window._eula if self.window is not None else api_core.eula_accepted()
        if not ok:
            raise ApiError("Isaac Sim needs the NVIDIA Omniverse EULA accepted by the user: ask them to turn physics "
                           "mode on once in the RetLens window and accept it there", 403)

    def physics(self, q: dict) -> dict:
        on, assist = _flag(q, "on", True), _num(q, "assist", None, lo=0.0)
        balance = q.get("balance", self.scene.balance)
        if not isinstance(balance, str) or balance not in BALANCE:
            raise ApiError(f"balance must be one of {', '.join(BALANCE)}")
        why = self.scene.balance_problem(balance) if on or "balance" in q else ""  # turning off always works
        if why:
            raise ApiError(f"{BALANCE[balance]}: {why}", 409)
        if on and balance == "isaac":
            self._eula()
        # only the mode asked for may start a run: assist is set as it is (set_assist would start an Isaac run x the
        # new scale while balance is still isaac), and physics goes off before balance changes
        if assist is not None:
            self.scene.assist = assist
        if not on:
            self.scene.set_physics(False, "api")
        if balance != self.scene.balance:
            self.scene.set_balance(balance)
        if on:
            self.scene.set_physics(True, "api")
        return {"physics": on, "balance": self.scene.balance, "mode": self.scene.mode_label(),
                "assist": self.scene.assist,
                "motions": {it.label: self.scene.job_text(it) for it in list(self.scene.items)}}

    def video(self, q: dict) -> dict:
        self._eula()
        item = self._item(q.get("id"))
        try:
            job = self.scene.save_video(item)
        except Exception as e:  # Isaac Sim not found
            raise ApiError(f"{type(e).__name__}: {e}", 409) from None
        return {"id": item.label, "state": job.state, "video": job.result, "note": "poll GET /api/jobs"}

    def jobs(self, q: dict) -> dict:
        out = []
        for it in list(self.scene.items):
            for key, job in it.handles.get("phys_jobs", {}).items():  # key: the harness scale, or the MuJoCo controller
                mode = {"kind": "mujoco", "balance": key} if job.kind == "policy" else {"kind": "physics", "assist": key}
                out.append({"id": it.label, **mode, "state": job.state, "stage": job.stage,
                            "progress": job.progress, "result": job.result, "message": job.message or None})
            job = it.handles.get("video_job")
            if job is not None:
                out.append({"id": it.label, "kind": "video", "state": job.state, "stage": job.stage,
                            "progress": job.progress, "result": job.result, "message": job.message or None})
        return {"busy": self.scene.jobs_busy(), "jobs": out}

    # ---------------------------------------------------------------- view
    def camera(self, q: dict) -> dict:
        if _flag(q, "fit", True):
            self.scene.fit_camera()
        return {"camera": "fitted"}

    def screenshot(self, q: dict) -> dict:
        if self.window is None:
            raise ApiError("no window (headless)", 409)
        path = _text(q, "path") or os.path.join(paths.logs_dir(), f"screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        def grab():
            w = self.window
            w.raise_()
            g = w.frameGeometry()
            screen = w.screen() or w.windowHandle().screen()
            return screen.grabWindow(0, g.x() - screen.geometry().x(), g.y() - screen.geometry().y(),
                                     g.width(), g.height()).save(path)

        if not self.on_gui(grab):
            raise ApiError("could not save the screenshot", 500)
        return {"path": os.path.abspath(path)}


class _Handler(BaseHTTPRequestHandler):
    server_version = "RetLens-API"

    def log_message(self, fmt, *a):  # requests go to the app log, briefly
        print(f"[api] {self.address_string()} {fmt % a}", flush=True)

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(api_core.jsonable(body), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        srv: ApiServer = self.server.api  # type: ignore[attr-defined]
        if self.headers.get("Origin"):  # a web page: never
            return self._reply(403, {"ok": False, "error": "requests from web pages are not accepted"})
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("X-RetLens-Token", "")
        if not secrets.compare_digest(token, srv.token):
            return self._reply(401, {"ok": False, "error": "missing or wrong token (see api.json: retlens-cli api)"})
        url = urlparse(self.path)
        fn = srv.backend.routes.get((method, url.path.rstrip("/") or "/"))
        if fn is None:
            return self._reply(404, {"ok": False, "error": f"no endpoint {method} {url.path}; GET /api/help lists them"})
        # a key given more than once is a list (?paths=a&paths=b, as clients write one), not its last value alone
        q = {k: (v if len(v) > 1 else v[0]) for k, v in parse_qs(url.query).items()}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except ValueError:
                return self._reply(400, {"ok": False, "error": "the body is not JSON"})
            if not isinstance(body, dict):
                return self._reply(400, {"ok": False, "error": "the body must be a JSON object"})
            q.update(body)
        try:
            out = fn(q)
        except ApiError as e:
            return self._reply(e.code, {"ok": False, "error": str(e)})
        except Exception as e:
            import traceback

            traceback.print_exc()
            return self._reply(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        self._reply(200, {"ok": True, **(out or {})})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class _ExclusiveServer(ThreadingHTTPServer):
    """One server per port. HTTPServer sets SO_REUSEADDR, which on Windows lets a second RetLens bind
    the same port too: its requests then reach the first window, which rejects the second's token."""

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ApiServer:
    """Serves ApiBackend on 127.0.0.1 (port; another free one when taken) in a daemon thread
    and writes the discovery file."""

    def __init__(self, backend: ApiBackend, port: int = DEFAULT_PORT, write_discovery: bool = True):
        self.backend, self.token = backend, secrets.token_urlsafe(24)
        try:
            self.httpd = _ExclusiveServer(("127.0.0.1", port), _Handler)
        except OSError:  # taken (another RetLens window, or another program)
            self.httpd = _ExclusiveServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.api = self
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._write = write_discovery
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="retlens-api", daemon=True)

    def start(self) -> "ApiServer":
        self._thread.start()
        self._previous = None
        if self._write:
            # another RetLens window may own the file: this one takes over, and hands it back on stop()
            prev = discovery()
            self._previous = prev if prev is not None and prev.get("pid") != os.getpid() else None
            os.makedirs(os.path.dirname(discovery_path()), exist_ok=True)
            with open(discovery_path(), "w", encoding="utf-8") as f:
                json.dump({"url": self.url, "port": self.port, "token": self.token, "pid": os.getpid(),
                           "api_version": api_core.API_VERSION, "started": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._write:
            d = discovery()
            if d is not None and d.get("token") == self.token:
                prev = getattr(self, "_previous", None)
                try:
                    if prev is not None and _alive(prev.get("pid")):  # the earlier window still runs: point at it again
                        with open(discovery_path(), "w", encoding="utf-8") as f:
                            json.dump(prev, f)
                    else:
                        os.remove(discovery_path())
                except OSError:
                    pass
