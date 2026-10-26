"""First cause of a fall in a physics replay (tools/isaac_replay.py --physics).

A fall alone says little about the motion data: an open-loop replay has no balance
controller, so what matters is what went wrong first. For each fall the frames just
before it (``window``) are scanned for these conditions, each a per-frame mask the
replay computes from its own records:

  toe_catch          a foot touches the floor while the clip has it swinging
  foot_slip          a foot on the floor slides while the clip has it standing
  self_collision     left/right feet or knees closer than a threshold (proxy: the
                     replay runs with self-collision off)
  torque_saturation  a joint drive needs more than its effort limit (x ratio)
  support_exit       CoM projection (or, without the harness, the ZMP) outside the
                     feet's support polygon
  harness_spike      the pelvis harness pulls with a large share of body weight

A condition starts ("onset") at the first frame of the window where it holds for
``min_frames`` frames in a row. One that already holds when the window opens is
"chronic"; its ``active_since_s`` is found by following that run back (gaps of up to
two frames, never past the previous reset).

Primary cause:
  1. the earliest onset among the conditions that start inside the window (a new
     event triggers the fall; a chronic one such as an ankle that is always near its
     limit, or a CoM the harness has been holding outside the feet, did not);
  2. if only chronic conditions are there, the one active the longest;
  3. harness_spike only when nothing else is found: the harness pulls hard because the
     robot has already left the clip's pose, so it is a consequence.
Ties follow CAUSES order.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

CAUSES = ("toe_catch", "foot_slip", "self_collision", "torque_saturation", "support_exit", "harness_spike")
SYMPTOMS = ("harness_spike",)
CAUSE_KO = {"toe_catch": "발끝 걸림", "foot_slip": "발 미끄러짐", "self_collision": "자기충돌 근접",
            "torque_saturation": "토크 포화", "support_exit": "지지면 이탈", "harness_spike": "보조 힘 급증",
            "undetermined": "미상"}  # report / viewer labels


def onset(mask: np.ndarray, start: int, stop: int, min_frames: int = 2) -> int | None:
    """First frame in [start, stop] where ``mask`` holds for ``min_frames`` frames in a row
    (a run cut short by ``stop`` counts)."""
    run = 0
    for i in range(max(start, 0), min(stop, len(mask) - 1) + 1):
        run = run + 1 if mask[i] else 0
        if run >= min_frames or (run and i == stop):
            return i - run + 1
    return None


def active_since(mask: np.ndarray, frame: int, earliest: int = 0, max_gap: int = 2) -> int:
    """Start of the run of ``mask`` that holds at ``frame``, followed back over gaps of up to
    ``max_gap`` frames, never before ``earliest``."""
    i = frame
    gap = 0
    j = frame - 1
    while j >= max(earliest, 0):
        if mask[j]:
            i, gap = j, 0
        else:
            gap += 1
            if gap > max_gap:
                break
        j -= 1
    return i


def diagnose_fall(conditions: dict[str, np.ndarray], evidence: dict[str, Callable[[int, int, int], dict]],
                  fall: int, start: int, fps: float, min_frames: int = 2, earliest: int = 0) -> dict:
    """conditions: cause -> (T,) bool mask; evidence: cause -> f(onset, start, fall) -> dict of
    numbers (values at the onset, peaks in the window). fall / start / earliest: frame indices
    (earliest = where the robot was last (re)started)."""
    cands = []
    for name, mask in conditions.items():
        mask = np.asarray(mask, bool)
        i = onset(mask, start, fall, min_frames)
        if i is None:
            continue
        chronic = bool(mask[start])
        since = active_since(mask, start, earliest) if chronic else i
        cands.append({
            "cause": name,
            "onset_s": round(i / fps, 3),
            "lead_s": round((fall - i) / fps, 3),
            "active_at_window_start": chronic,
            "active_since_s": round(since / fps, 3),
            "evidence": evidence[name](i, start, fall) if name in evidence else {},
        })
    rank = {c: k for k, c in enumerate(CAUSES)}
    cands.sort(key=lambda c: (c["active_at_window_start"], c["onset_s"], rank.get(c["cause"], len(rank))))
    new = [c for c in cands if not c["active_at_window_start"] and c["cause"] not in SYMPTOMS]
    chronic = sorted((c for c in cands if c["active_at_window_start"] and c["cause"] not in SYMPTOMS),
                     key=lambda c: (c["active_since_s"], rank.get(c["cause"], len(rank))))
    primary = (new or chronic or cands or [None])[0]
    return {
        "fall_time_s": round(fall / fps, 3),
        "window_s": [round(start / fps, 3), round(fall / fps, 3)],
        "primary_cause": primary["cause"] if primary else "undetermined",
        "primary_onset_s": (primary["active_since_s"] if primary["active_at_window_start"] else primary["onset_s"])
        if primary else None,
        "primary_evidence": primary["evidence"] if primary else {},
        "candidates": cands,
    }
