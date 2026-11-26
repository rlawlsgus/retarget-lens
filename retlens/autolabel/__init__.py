"""Automatic labels: what the body does in a human motion, named by a rule file.

    from retlens import autolabel
    labels = autolabel.label_motion(item.human, r"D:\\rules\\subtask.yaml", duration=item.robot.duration)

body.py takes the joints and body sizes from the motion, signals.py turns them into per-frame
signals and segment.py into movement tracks (이동, 자세, 손, 양손, ...); rules.py names the
frames with a rule file's labels. The result is a motion_labels.MotionLabels, drawn on the
timeline like labels read from a file. Which rule file: the 자동 라벨 규칙 setting
(Settings.label_rules), else $RETLENS_LABEL_RULES; RetLens ships only an example
(configs/label_rules_example.yaml).

A rule file with a labeler (rules.py notes) hands the motion to a project's own function instead:
RetLens loads the motion, calls the function and shows, edits, saves and exports what it returns like
any automatic labels (labeler_function, _label_by_labeler). rules_stamp is what such labels depend on,
for the dataset cache.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import sys
import threading
import traceback

import numpy as np

from .. import __version__, motion_labels, paths
from ..motion import SkeletonMotion
from . import body, rules, segment, signals

_LABELERS: dict[tuple, object] = {}  # (file, mtime_ns, size, function) -> the function, until the file changes
_LABELER_LOCK = threading.Lock()  # the window labels in the background: one import of a file at a time
STAMP_MAX_FILES = 5000  # files of a labeler's folder in its stamp (a folder beyond this: the first ones by path)

ENV = "RETLENS_LABEL_RULES"
EXAMPLE = paths.resource("configs", "label_rules_example.yaml")


def rules_file() -> str:
    """The rule file to use: the setting, else the environment variable ('' when neither is set)."""
    from .. import settings

    return settings.load().label_rules or os.environ.get(ENV, "")


def check_rules(rule_file: str | dict) -> dict:
    """The rules, checked (rules.RuleError / OSError when they cannot be used): before labelling
    anything, so a broken rule file changes no motion's labels."""
    return rules.load(rule_file) if isinstance(rule_file, str) else rules.check(rule_file)


def label_motion(human: SkeletonMotion, rule_file: str | dict, duration: float | None = None) -> motion_labels.MotionLabels:
    """The motion's labels by the rules (a file, or its contents as a dict); duration (s) clips them.
    Never raises: what cannot be done (no skeleton, a broken rule file, too short) comes back as
    the labels' error."""
    path = rule_file if isinstance(rule_file, str) else ""
    stem = os.path.splitext(os.path.basename(path))[0]
    rs = {}
    try:
        rs = check_rules(rule_file)
        return _label(human, rs, path, stem, duration)
    except (OSError, ValueError) as e:  # what the rules or the skeleton say is wrong, in their words
        msg = str(e)
    except Exception as e:  # noqa: BLE001 - anything else: still an answer, not a crash
        msg = f"자동 라벨 계산 중 오류: {type(e).__name__}: {e}"
    return motion_labels.MotionLabels(path=path, error=msg, auto=rs.get("name") or stem or "규칙")


def labeler_function(spec: dict):
    """A labeler's function (rules.check's labeler {file, function}), imported from its file; imported again when
    the file changes. ValueError when the file does not import or has no such function."""
    f = spec["file"]
    st = os.stat(f)
    key = (os.path.normcase(f), st.st_mtime_ns, st.st_size, spec["function"])
    with _LABELER_LOCK:
        fn = _LABELERS.get(key)
        if fn is not None:
            return fn
        name = "retlens_labeler_" + hashlib.sha1(key[0].encode("utf-8")).hexdigest()[:12]
        try:
            sp = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(sp)
            sys.modules[name] = mod  # the module's own lookups (dataclasses, pickle) find it
            sp.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001 - the file's own error, in its words
            sys.modules.pop(name, None)
            raise ValueError(f"라벨러 파일을 불러오지 못함 ({os.path.basename(f)}{_where(e, f)}): "
                             f"{type(e).__name__}: {e}") from e
        fn = getattr(mod, spec["function"], None)
        if not callable(fn):
            raise ValueError(f"라벨러 파일 {os.path.basename(f)}에 함수 {spec['function']}가 없습니다")
        for k in [k for k in _LABELERS if k[0] == key[0]]:  # the file's older versions
            del _LABELERS[k]
        _LABELERS[key] = fn
        return fn


def _where(e: BaseException, file: str) -> str:
    """':<line>' of the last frame of e in the labeler's folder (where its own code failed), '' when none."""
    folder = os.path.normcase(os.path.dirname(os.path.abspath(file)))
    frames = [fr for fr in traceback.extract_tb(e.__traceback__)
              if os.path.normcase(os.path.abspath(fr.filename)).startswith(folder)]
    return f" {os.path.basename(frames[-1].filename)}:{frames[-1].lineno}" if frames else ""


def rules_stamp(path: str) -> list:
    """What labels by this rule file depend on, for caches: the file (path, modified time), and for a labeler
    file a digest of every file in the labeler's folder and below (path, size, modified time; __pycache__ and
    hidden folders left out), so editing its code or data labels again."""
    out = [os.path.abspath(path), os.path.getmtime(path)]
    try:
        rs = rules.load(path)
    except (OSError, ValueError):
        return out
    if not rs.get("labeler"):
        return out
    folder = os.path.dirname(rs["labeler"]["file"])
    items = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for n in sorted(files):
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append(f"{os.path.relpath(p, folder)}|{st.st_size}|{st.st_mtime_ns}")
            if len(items) >= STAMP_MAX_FILES:
                break
        if len(items) >= STAMP_MAX_FILES:
            break
    return out + [hashlib.sha1("\n".join(items).encode("utf-8")).hexdigest()]


def _label_by_labeler(human, rs: dict, path: str, stem: str, duration: float | None) -> motion_labels.MotionLabels:
    """The labeler's segments as MotionLabels: names and colors from the rule file's label list, clipped to
    duration; a label the list does not have is kept and named in notes."""
    spec = rs["labeler"]
    fn = labeler_function(spec)
    tracks = {t["track"]: [d["label"] for d in t["labels"]] for t in rs["tracks"]}
    context = {"rules": path, "duration": duration, "fps": segment.FPS, "version": __version__, "tracks": tracks}
    try:
        out = fn(human, context)
    except Exception as e:  # noqa: BLE001 - the labeler's error, in its words
        raise ValueError(f"라벨러 오류 ({os.path.basename(spec['file'])}{_where(e, spec['file'])}): "
                         f"{type(e).__name__}: {e}") from e
    notes = []
    if isinstance(out, dict):
        notes = [str(x) for x in (out.get("notes") or [])]
        out = out.get("segments")
    if not isinstance(out, (list, tuple)):
        raise ValueError(f"라벨러가 돌려준 값이 구간 목록이 아닙니다 ({type(out).__name__})")
    meta = {(t, d["label"]): d for t, ds in rules.defined_labels(rs).items() for d in ds}
    segs, undefined, dropped = [], set(), 0
    for i, x in enumerate(out):
        try:
            if isinstance(x, dict):
                track, label, start, end = x.get("track", ""), x["label"], float(x["start"]), float(x["end"])
                name, note = str(x.get("name") or ""), str(x.get("note") or "")
            else:
                track, label, start, end = x[0], x[1], float(x[2]), float(x[3])
                name, note = (str(x[4]) if len(x) > 4 and x[4] else ""), ""
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ValueError(f"라벨러가 돌려준 구간 {i + 1}번째를 읽지 못함 ({type(e).__name__}: {e}): "
                             "(트랙, 라벨, 시작 s, 끝 s)나 {track, label, start, end}여야 합니다") from e
        track, label = str(track or ""), str(label or "").strip()
        if not label or not (math.isfinite(start) and math.isfinite(end)) or not end > start:
            dropped += 1
            continue
        if duration is not None:
            if start >= duration:
                continue
            end = min(end, duration)
        d = meta.get((track, label))
        if d is None:
            undefined.add(f"{track}: {label}" if track else label)
        d = d or {}
        segs.append(motion_labels.Segment(label, max(start, 0.0), end, track=track, name=name or d.get("name") or "",
                                          note=note, color=motion_labels._color(d.get("color") or "")))
    if dropped:
        notes.append(f"라벨이 비었거나 끝이 시작보다 늦지 않은 구간 {dropped}개는 뺐습니다")
    if undefined:
        shown = sorted(undefined)
        notes.append(f"규칙 파일 tracks에 없는 라벨 {len(shown)}개: " + ", ".join(shown[:5]) + (" …" if len(shown) > 5 else ""))
    return motion_labels.MotionLabels(path=path, segments=segs, notes=notes, auto=rs["name"] or stem or "라벨러")


def _label(human, rs: dict, path: str, stem: str, duration: float | None) -> motion_labels.MotionLabels:
    if rs.get("labeler"):
        return _label_by_labeler(human, rs, path, stem, duration)
    P, dims, notes = body.prepare(human)
    f, _, belt = signals.from_joints(P, dims)
    on = np.flatnonzero(np.linalg.norm(belt, axis=1))  # frames on a moving support
    if len(on):
        notes.append(f"움직이는 바닥(트레드밀, {np.median(np.linalg.norm(belt[on], axis=1)):.2f} m/s) 위로 보고 계산함 "
                     f"({on[0] / segment.FPS:.1f}-{(on[-1] + 1) / segment.FPS:.1f} s)")
    tracks, steps = segment.tracks(f, dims, rs["params"])
    segs = []
    for lane, label, s, e, rule in rules.apply(rs, tracks, steps):
        start, end = s / segment.FPS, e / segment.FPS
        if duration is not None:
            if start >= duration:
                continue
            end = min(end, duration)
        segs.append(motion_labels.Segment(label, start, end, track=lane, name=rule.get("name") or "",
                                          color=motion_labels._color(rule.get("color") or "")))
    return motion_labels.MotionLabels(path=path, segments=segs, notes=notes, auto=rs["name"] or stem or "규칙")
