"""Problem spans (retlens.problems): per-frame flags as time spans, and the metrics carrying them."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import problems  # noqa: E402


def test_spans():
    fps = 10.0
    m = np.zeros(40, bool)
    m[5:10] = True  # 0.5-1.0 s
    m[11:15] = True  # a 1-frame gap: bridged into the run before
    m[30] = True  # one frame (0.1 s): kept (>= 0.05 s)
    assert problems.spans(m, fps) == [(0.5, 1.5), (3.0, 3.1)]
    assert problems.spans(m, fps, bridge_s=0.0) == [(0.5, 1.0), (1.1, 1.5), (3.0, 3.1)]
    assert problems.spans(m, fps, min_s=0.2) == [(0.5, 1.5)]
    assert problems.spans(np.zeros(5, bool), fps) == [] and problems.spans(np.ones(3, bool), 0.0) == []
    assert problems.spans(np.ones(10, bool), fps) == [(0.0, 1.0)]  # to the end


def test_problem_spans_by_kind():
    fps = 30.0
    slip = np.zeros(60, bool)
    slip[30:45] = True
    gap = np.zeros(120, bool)  # markers at 120 Hz: their own rate
    gap[:12] = True
    out = problems.problem_spans({"slip": slip, "penetration": np.zeros(60, bool), "marker_gap": (gap, 120.0),
                                  "unknown": slip}, fps)
    assert out == {"slip": [(1.0, 1.5)], "marker_gap": [(0.0, 0.1)]}  # kinds without a span, and others, left out
    assert list(problems.KINDS) == ["slip", "penetration", "swing_low", "self_collision", "joint_limit", "marker_gap"]
