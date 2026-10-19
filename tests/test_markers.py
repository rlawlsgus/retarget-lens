"""C3D marker helpers (khumanoid/markers.py) and finding a marker take's solved motion."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid.compare import find_take  # noqa: E402
from khumanoid.markers import (MARKER_SET, align_to_skeleton, marker_qc, marker_skeleton,  # noqa: E402
                               placed_markers)
from khumanoid.motion import SkeletonMotion  # noqa: E402

C3D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw", "cmu_c3d", "02_01.c3d")


def _walk(n=240, fps=120.0, yaw_deg=0.0):
    """A pelvis walking +x with the CMU marker set around it (subject-prefixed labels), turned by yaw."""
    rng = np.random.default_rng(1)
    names = list(MARKER_SET)
    local = rng.uniform(-0.3, 0.3, (len(names), 3)) + [0.0, 0.0, 0.0]
    side = {"LFWT": (0.08, 0.13), "RFWT": (0.08, -0.13), "LBWT": (-0.08, 0.1), "RBWT": (-0.08, -0.1)}
    for k, (x, y) in side.items():
        local[names.index(k)] = (x, y, 0.0)
    t = np.arange(n) / fps
    root = np.stack([1.2 * t, np.zeros(n), np.full(n, 0.95)], 1)
    P = root[:, None] + local[None]
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    m = SkeletonMotion(name="walk", joint_names=[f"Subj:{x}" for x in names] + ["Subj:LFEM1"],
                       parents=np.full(len(names) + 1, -1), positions=np.concatenate([P @ R.T, P[:, :1] @ R.T], 1),
                       fps=fps, kind="markers")
    r60 = root[::2]  # the solved skeleton at 60 Hz
    skel = SkeletonMotion(name="walk", joint_names=["Hips", "LeftUpLeg", "RightUpLeg"], parents=np.array([-1, 0, 0]),
                          positions=np.stack([r60, r60 + [0, 0.1, -0.05], r60 + [0, -0.1, -0.05]], 1), fps=fps / 2)
    return m, skel


def test_marker_skeleton_and_alignment():
    m, skel = _walk(yaw_deg=90.0)  # markers recorded in a frame turned 90 deg from the skeleton's
    assert len(placed_markers(m.joint_names)) == len(MARKER_SET)  # the model output LFEM1 is not a marker
    ms = marker_skeleton(m)
    assert ms.joint_names[0] == "pelvis" and ms.joint_names[1] == MARKER_SET[0] and len(ms.meta["bones"]) > 40
    assert 0 not in ms.meta["dots"] and len(ms.meta["dots"]) == len(MARKER_SET)
    out, fit = align_to_skeleton(ms, skel)
    assert fit["yaw_deg"] == pytest.approx(-90.0, abs=0.5) and fit["residual_cm"] < 2.0
    k = np.clip(np.round(np.arange(240) / 2).astype(int), 0, skel.num_frames - 1)
    assert np.allclose(out.positions[:, 0, :2], skel.positions[k, 0, :2], atol=0.02)


def test_marker_qc_gaps_and_jumps():
    m, _ = _walk()
    P = m.positions.copy()
    j = m.joint_names.index("Subj:LFIN")
    P[50:62, j] = np.nan  # a 0.1 s gap
    P[100, m.joint_names.index("Subj:RTOE")] += [0.5, 0, 0]  # a 0.5 m jump for one sample
    m.positions = P
    qc = marker_qc(m)
    assert qc["markers"] == len(MARKER_SET) and qc["points"] == len(MARKER_SET) + 1
    assert qc["most_missing"][0][0] == "LFIN" and qc["longest_gap_s"] == pytest.approx(0.1)
    assert qc["spike_frames"] == 2 and qc["spike_markers"] == ["RTOE"]


def test_find_take_prefers_bvh():
    files = ["d/cmu_fbx_from_bvh/02_01.fbx", "d/amass/CMU/02/02_01_stageii.npz", "d/cmu_fbx/02_01.fbx", "d/cmu_bvh/02_01.bvh",
             "d/cmu_bvh/02_011.bvh"]
    assert find_take("x/02_01.c3d", files).endswith(os.path.join("cmu_bvh", "02_01.bvh"))
    assert find_take("x/02_01.c3d", files[:3]).endswith(os.path.join("cmu_fbx", "02_01.fbx"))
    assert find_take("x/02_01.c3d", files[:2]).endswith("02_01_stageii.npz")
    assert find_take("x/99_99.c3d", files) is None


@pytest.mark.skipif(not os.path.isfile(C3D), reason="needs data/raw/cmu_c3d (CMU sample C3D)")
def test_cmu_c3d_sample():
    from khumanoid.io import load_c3d

    m = load_c3d(C3D)
    assert m.fps == 120.0 and m.num_frames == 343 and len(m.joint_names) == 41
    assert m.joint_names[0].startswith("TakeoMonday:") and 0.0 < np.nanmin(m.positions[..., 2]) < 0.05  # z up, metres
    assert marker_qc(m)["missing_pct"] == 0.0
