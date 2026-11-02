"""Where in a motion its problems are: the per-frame flags behind the metrics (foot slip, floor penetration,
swing foot skimming the floor, self-collision, joint at its limit, C3D marker gaps) as time spans, so the
timeline can mark them and the front ends can step from one to the next.

    spans(mask, fps)          [(start_s, end_s)] of the runs where mask holds (short gaps bridged)
    problem_spans(flags, fps) {kind: spans} for the kinds in KINDS that have any

Falls are not here: they come from the physics results (MotionScene.falls) and are marked apart.
"""

from __future__ import annotations

import numpy as np

# kind: (Korean name, timeline colour); the order is the drawing / listing order
KINDS = {
    "slip": ("발 미끄러짐", (240, 200, 40)),
    "penetration": ("바닥 관통", (165, 90, 230)),
    "swing_low": ("스윙 발 바닥 근접", (245, 140, 40)),
    "self_collision": ("자기 충돌", (225, 70, 170)),
    "joint_limit": ("관절 한계", (40, 175, 225)),
    "marker_gap": ("마커 공백", (160, 160, 160)),
}
BRIDGE_S = 0.1  # gaps up to this long inside a run are bridged (one span, not a dozen)
MIN_S = 0.05  # runs shorter than this are dropped (a frame of noise)


def spans(mask: np.ndarray, fps: float, bridge_s: float = BRIDGE_S, min_s: float = MIN_S) -> list[tuple[float, float]]:
    """Time spans (start, end in seconds; end = the frame after the run) where a per-frame mask holds."""
    m = np.asarray(mask, dtype=bool).ravel()
    if not m.any() or fps <= 0:
        return []
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    runs = list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
    gap = int(round(bridge_s * fps))
    merged = [list(runs[0])]
    for a, b in runs[1:]:
        if a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(round(a / fps, 4), round(b / fps, 4)) for a, b in merged if (b - a) / fps >= min_s]


def problem_spans(flags: dict, fps: float) -> dict[str, list[tuple[float, float]]]:
    """{kind: spans} of per-frame flags {kind: mask} (kinds of KINDS; a mask may carry its own fps as
    (mask, fps)); kinds without a span are left out."""
    out = {}
    for kind in KINDS:
        f = flags.get(kind)
        if f is None:
            continue
        mask, rate = f if isinstance(f, tuple) else (f, fps)
        s = spans(mask, rate)
        if s:
            out[kind] = s
    return out
