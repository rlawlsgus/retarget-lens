"""Optical markers (C3D): the CMU 41-marker set's display sticks, raw-marker QC, and putting a
C3D take into the frame of the same take's solved skeleton (BVH / FBX / SMPL-X).

A C3D file has marker points only, which GMR cannot retarget. The viewers therefore drive
the robot from the same take's solved skeleton and draw the markers next to it: the solver
and retargeting results can be checked against the raw capture.
"""

from __future__ import annotations

import warnings

import numpy as np

from .motion import SkeletonMotion

PELVIS = ("LFWT", "RFWT", "LBWT", "RBWT")  # front / back waist markers
# CMU / Vicon 41-marker set (mocap.cs.cmu.edu marker placement guide): sticks between markers
_SIDE = [("SHO", "UPA"), ("UPA", "ELB"), ("ELB", "FRM"), ("FRM", "WRA"), ("FRM", "WRB"), ("WRA", "WRB"),
         ("WRA", "FIN"), ("WRB", "FIN"), ("FWT", "THI"), ("BWT", "THI"), ("THI", "KNE"), ("KNE", "SHN"),
         ("SHN", "ANK"), ("ANK", "HEE"), ("ANK", "MT5"), ("HEE", "MT5"), ("HEE", "TOE"), ("TOE", "MT5")]
MARKER_STICKS = ([("LFHD", "RFHD"), ("RFHD", "RBHD"), ("RBHD", "LBHD"), ("LBHD", "LFHD"), ("C7", "T10"),
                  ("C7", "CLAV"), ("CLAV", "STRN"), ("C7", "LSHO"), ("C7", "RSHO"), ("CLAV", "LSHO"), ("CLAV", "RSHO"),
                  ("T10", "RBAC"), ("T10", "LBWT"), ("T10", "RBWT"), ("STRN", "LFWT"), ("STRN", "RFWT"),
                  ("LFWT", "RFWT"), ("RFWT", "RBWT"), ("RBWT", "LBWT"), ("LBWT", "LFWT")]
                 + [(s + a, s + b) for s in "LR" for a, b in _SIDE])
MARKER_SET = sorted({n for pair in MARKER_STICKS for n in pair})  # the 41 placed markers
SPIKE_SPEED = 10.0  # m/s: a marker moving faster than this between two samples jumped (swap / ghost)


def placed_markers(names: list[str]) -> list[int]:
    """Indices of the physical markers. Vicon BodyBuilder files also carry model outputs
    (segment axes such as LFEM1-4, LULN2-5): when at least 20 of the CMU set are there, only
    those count; otherwise (another marker set) every point does."""
    first = _first_index([short_label(n) for n in names])
    known = sorted(first[n] for n in MARKER_SET if n in first)
    return known if len(known) >= 20 else list(range(len(names)))


def short_label(label: str) -> str:
    """'TakeoMonday:LFWT' -> 'LFWT' (Vicon prefixes labels with the subject name)."""
    return label.split(":")[-1].strip()


def _first_index(names: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, n in enumerate(names):
        out.setdefault(n, i)
    return out


def _nanmean(a: np.ndarray, axis: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN rows stay NaN
        return np.nanmean(a, axis=axis)


def marker_skeleton(m: SkeletonMotion) -> SkeletonMotion:
    """Markers ready to draw next to a robot: joint 0 is a virtual 'pelvis' (the centre of the
    pelvis markers: the anchor the viewers put on the robot), then every marker with the
    subject prefix dropped. meta['bones'] holds the marker-set sticks, meta['dots'] the points to
    draw (the placed markers, see placed_markers)."""
    names = [short_label(n) for n in m.joint_names]
    first = _first_index(names)
    pel = [first[k] for k in PELVIS if k in first]
    centre = _nanmean(m.positions[:, pel] if pel else m.positions, axis=1)
    bones = [(first[a] + 1, first[b] + 1) for a, b in MARKER_STICKS if a in first and b in first]
    dots = [j + 1 for j in placed_markers(m.joint_names)]
    return SkeletonMotion(name=m.name, joint_names=["pelvis"] + names, parents=np.full(len(names) + 1, -1, dtype=int),
                          positions=np.concatenate([centre[:, None], m.positions], axis=1), fps=m.fps, source=m.source,
                          kind="markers", meta={**m.meta, "bones": bones, "dots": dots, "labels": list(m.joint_names)})


def marker_qc(m: SkeletonMotion) -> dict:
    """Raw-marker QC of a load_c3d() result over the placed markers: how much is missing, the
    longest gap, and jumps (faster than SPIKE_SPEED between two samples: label swaps or ghost
    points). "points" counts everything in the file, model outputs included."""
    keep = placed_markers(m.joint_names)
    P = m.positions[:, keep]
    names = [short_label(m.joint_names[j]) for j in keep]
    miss = np.isnan(P[..., 0])
    used = ~miss.all(axis=0)  # points that appear at all (C3D files can carry empty slots)
    longest = np.zeros(P.shape[1], dtype=int)
    for j in np.flatnonzero(used):
        run = best = 0
        for v in miss[:, j]:
            run = run + 1 if v else 0
            best = max(best, run)
        longest[j] = best
    with np.errstate(invalid="ignore"):
        speed = np.linalg.norm(np.diff(P, axis=0), axis=-1) * m.fps
    spikes = np.nan_to_num(speed, nan=0.0) > SPIKE_SPEED
    per = 100.0 * miss.mean(axis=0)
    order = [j for j in np.argsort(-per) if used[j] and per[j] > 0][:3]
    g = int(np.argmax(longest))
    return {
        "points": int(m.positions.shape[1]), "markers": int(used.sum()), "fps": float(m.fps), "frames": int(m.num_frames),
        "missing_pct": float(100.0 * miss[:, used].mean()) if used.any() else 100.0,
        "most_missing": [(names[j], round(float(per[j]), 1)) for j in order],
        "longest_gap_s": float(longest[g] / m.fps) if m.fps else 0.0, "longest_gap_marker": names[g] if longest[g] else "",
        "spike_frames": int(spikes.any(axis=1).sum()),
        "spike_markers": [names[j] for j in np.argsort(-spikes.sum(axis=0))[:3] if spikes[:, j].any()],
    }


def _hip_pair(skel: SkeletonMotion) -> tuple[int, int] | None:
    """(left hip, right hip) joints of a solved skeleton (BVH LeftUpLeg, SMPL-X left_hip, ...)."""
    for keys in (("upleg",), ("femur",), ("thigh",), ("hip",)):
        left = [i for i in skel.find_joints(*keys) if skel.joint_names[i].lower().startswith(("left", "l_", "l"))
                and "hipjoint" not in skel.joint_names[i].lower()]
        right = [i for i in skel.find_joints(*keys) if skel.joint_names[i].lower().startswith(("right", "r_", "r"))
                 and "hipjoint" not in skel.joint_names[i].lower()]
        if left and right:
            return left[0], right[0]
    return None


def align_to_skeleton(markers: SkeletonMotion, skel: SkeletonMotion) -> tuple[SkeletonMotion, dict]:
    """Turn (about the vertical) and shift markers from marker_skeleton() into the solved
    skeleton's world, from the pelvis: the markers' left-right waist axis onto the skeleton's
    left-right hip axis, and the pelvis-marker centre onto its root, over the whole take.
    (CMU: our BVH world is the C3D world turned by -90 deg.) Returns the moved markers and
    {"yaw_deg", "shift_m", "residual_cm"} (mean pelvis distance after the fit)."""
    first = _first_index(markers.joint_names)
    hips = _hip_pair(skel)
    t = np.arange(markers.num_frames) / markers.fps
    k = np.clip(np.round(t * skel.fps).astype(int), 0, skel.num_frames - 1)  # skeleton frame at each marker time
    P = markers.positions
    root = skel.positions[k, 0]
    if hips is not None and all(n in first for n in PELVIS):
        lr_m = (P[:, first["LFWT"]] + P[:, first["LBWT"]] - P[:, first["RFWT"]] - P[:, first["RBWT"]])[:, :2] / 2
        lr_s = (skel.positions[k, hips[0]] - skel.positions[k, hips[1]])[:, :2]
        d = np.arctan2(lr_s[:, 1], lr_s[:, 0]) - np.arctan2(lr_m[:, 1], lr_m[:, 0])
        ok = np.isfinite(d)
        yaw = float(np.arctan2(np.sin(d[ok]).mean(), np.cos(d[ok]).mean())) if ok.any() else 0.0
    else:  # no waist markers / hips: line up the walked paths instead
        a, b = P[:, 0, :2] - np.nanmean(P[:, 0, :2], 0), root[:, :2] - root[:, :2].mean(0)
        ok = np.isfinite(a).all(1)
        cross = a[ok, 0] * b[ok, 1] - a[ok, 1] * b[ok, 0]
        yaw = float(np.arctan2(cross.sum(), (a[ok] * b[ok]).sum())) if ok.any() else 0.0
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    Q = P @ R.T
    shift = np.zeros(3)
    off = root[:, :2] - Q[:, 0, :2]
    if np.isfinite(off).any():
        shift[:2] = _nanmean(off, axis=0)
    Q = Q + shift
    resid = np.linalg.norm(Q[:, 0, :2] - root[:, :2], axis=1)
    out = SkeletonMotion(name=markers.name, joint_names=markers.joint_names, parents=markers.parents, positions=Q,
                         fps=markers.fps, source=markers.source, kind=markers.kind, meta=dict(markers.meta))
    return out, {"yaw_deg": float(np.degrees(yaw)), "shift_m": shift.tolist(),
                 "residual_cm": float(100.0 * np.nanmean(resid)) if np.isfinite(resid).any() else float("nan")}
