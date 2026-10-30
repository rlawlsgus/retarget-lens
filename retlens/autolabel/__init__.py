"""Automatic labels: what the body does in a human motion, named by a rule file.

    from retlens import autolabel
    labels = autolabel.label_motion(item.human, r"D:\\rules\\subtask.yaml", duration=item.robot.duration)

body.py takes the joints and body sizes from the motion, signals.py turns them into per-frame
signals and segment.py into movement tracks (이동, 자세, 손, 양손, ...); rules.py names the
frames with a rule file's labels. The result is a motion_labels.MotionLabels, drawn on the
timeline like labels read from a file. Which rule file: the 자동 라벨 규칙 setting
(Settings.label_rules), else $RETLENS_LABEL_RULES; RetLens ships only an example
(configs/label_rules_example.yaml).
"""

from __future__ import annotations

import os

import numpy as np

from .. import motion_labels, paths
from ..motion import SkeletonMotion
from . import body, rules, segment, signals

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


def _label(human, rs: dict, path: str, stem: str, duration: float | None) -> motion_labels.MotionLabels:
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
