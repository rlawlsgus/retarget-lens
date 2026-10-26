"""Balance of a robot motion: whole-body CoM, ZMP and the support polygon of the feet.

Numpy only (scipy is used for smoothing when present), so Isaac Sim's Python, the
MuJoCo-based viewer / reports and the tests share one implementation. Inputs are
per-frame world quantities; the floor is a height per frame because retargets
drift (CMU 02_01 rises 4-5 cm, see analysis.floor_track).

  CoM      sum_i m_i (p_i + R_i c_i) / M over the robot links, with link masses and
           local CoMs from the robot asset (Isaac Articulation.get_link_masses /
           get_link_coms) or the MJCF.
  ZMP      cart-table model: zmp_xy = com_xy - (com_z - floor) / (g + com_z'') * com_xy''.
           Centroidal angular momentum is ignored; the CoM is low-passed before the
           double derivative (mocap frame rates amplify noise).
  support  convex hull of the sole contact points within ``contact_height`` of the floor.
           phase 2 = both feet, 1 = one foot, 0 = none (flight, lying, hands only):
           frames without support are left out of the margins and counted apart.
  margin   signed distance to the support boundary in the floor plane: + inside, - outside (m).

The CoM projection may leave the support in dynamic motion (a walking CoM passes
ahead of the stance foot); the ZMP should not, for a motion the robot can balance
on its feet alone. Neither proves balance: that is the controller's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .rotations import quat_to_matrix

G = 9.81


# --------------------------------------------------------------------------- geometry
def convex_hull(points: np.ndarray) -> np.ndarray:
    """Counter-clockwise convex hull of (N, 2) points (Andrew's monotone chain).
    Returns (K, 2): K = 1 for a point, 2 for a segment."""
    pts = np.unique(np.round(np.asarray(points, float).reshape(-1, 2), 6), axis=0)
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    hull = np.array(lower[:-1] + upper[:-1])
    return hull if len(hull) >= 2 else pts[:1]


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = 0.0 if not ab.any() else float(np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def signed_margin(point: np.ndarray, hull: np.ndarray) -> float:
    """Distance from a 2D point to the boundary of a ccw convex polygon: + inside, - outside.
    A point / segment hull (one corner or one edge on the floor) has no inside."""
    p = np.asarray(point, float)[:2]
    n = len(hull)
    if n == 0 or not np.isfinite(p).all():
        return float("nan")
    if n == 1:
        return -float(np.linalg.norm(p - hull[0]))
    if n == 2:
        return -_segment_distance(p, hull[0], hull[1])
    edges = np.roll(hull, -1, axis=0) - hull
    rel = p - hull
    lengths = np.linalg.norm(edges, axis=1)
    inside_dist = (edges[:, 0] * rel[:, 1] - edges[:, 1] * rel[:, 0]) / np.maximum(lengths, 1e-12)
    if (inside_dist >= 0).all():
        return float(inside_dist.min())
    return -min(_segment_distance(p, hull[i], hull[(i + 1) % n]) for i in range(n))


# --------------------------------------------------------------------------- dynamics
def com_from_links(link_pos: np.ndarray, link_quat: np.ndarray, com_local: np.ndarray,
                   masses: np.ndarray) -> np.ndarray:
    """Whole-body CoM (T, 3) from link world poses (T, L, 3) / (T, L, 4 wxyz), link-frame
    CoM offsets (L, 3) and masses (L,)."""
    R = quat_to_matrix(link_quat)
    world = link_pos + np.einsum("tlij,lj->tli", R, com_local)
    return np.einsum("tli,l->ti", world, masses) / masses.sum()


def lowpass(x: np.ndarray, fps: float, cutoff_hz: float = 6.0) -> np.ndarray:
    """Zero-phase low-pass along time (axis 0); a centred moving average without scipy."""
    x = np.asarray(x, float)
    if len(x) < 8 or cutoff_hz <= 0 or cutoff_hz >= 0.5 * fps:
        return x
    try:
        from scipy.signal import butter, filtfilt

        b, a = butter(2, cutoff_hz / (0.5 * fps))
        return filtfilt(b, a, x, axis=0, padlen=min(9, len(x) - 1))
    except ImportError:
        k = max(1, int(round(fps / cutoff_hz / 2)))
        kernel = np.ones(2 * k + 1) / (2 * k + 1)
        pad = np.concatenate([np.repeat(x[:1], k, 0), x, np.repeat(x[-1:], k, 0)])
        return np.stack([np.convolve(pad[:, i], kernel, mode="valid") for i in range(x.shape[1])], 1)


def zmp_cart_table(com: np.ndarray, fps: float, floor: np.ndarray | float = 0.0,
                   cutoff_hz: float = 6.0, breaks: list[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """ZMP (T, 2) on the floor and the CoM acceleration (T, 3) of a CoM trajectory.
    ``breaks``: frames where the trajectory restarts (a physics replay resetting the robot
    after a fall); each piece is filtered and differentiated on its own."""
    floor = np.broadcast_to(floor, (len(com),))
    if breaks:
        cuts = [0] + sorted(b for b in set(breaks) if 0 < b < len(com)) + [len(com)]
        parts = [zmp_cart_table(com[a:b], fps, floor[a:b], cutoff_hz) for a, b in zip(cuts[:-1], cuts[1:]) if b > a]
        return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
    c = lowpass(com, fps, cutoff_hz)
    dt = 1.0 / fps
    acc = np.gradient(np.gradient(c, dt, axis=0), dt, axis=0) if len(c) >= 3 else np.zeros_like(c)
    height = c[:, 2] - np.broadcast_to(floor, (len(c),))
    denom = np.maximum(G + acc[:, 2], 1.0)  # free fall (a_z = -g) has no ZMP; keep it finite
    return c[:, :2] - (height / denom)[:, None] * acc[:, :2], acc


def support_polygons(corners: np.ndarray, floor: np.ndarray | float = 0.0,
                     contact_height: float = 0.02) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
    """corners: (T, feet, C, 3) sole contact points. Returns per-frame hulls, the
    support phase (T,) (number of feet with a point on the floor) and the per-foot
    contact (T, feet)."""
    floor = np.broadcast_to(floor, (len(corners),))
    on = corners[..., 2] - floor[:, None, None] < contact_height  # (T, F, C)
    hulls = [convex_hull(corners[t][on[t]][:, :2]) if on[t].any() else np.zeros((0, 2)) for t in range(len(corners))]
    contact = on.any(-1)
    return hulls, contact.sum(-1), contact


# --------------------------------------------------------------------------- track + metrics
@dataclass
class BalanceTrack:
    fps: float
    com: np.ndarray  # (T, 3)
    zmp: np.ndarray  # (T, 2)
    floor: np.ndarray  # (T,)
    phase: np.ndarray  # (T,) 0 / 1 / 2 feet on the floor
    contact: np.ndarray  # (T, feet)
    hulls: list = field(repr=False)
    com_margin: np.ndarray = None  # (T,) NaN without support
    zmp_margin: np.ndarray = None

    @property
    def supported(self) -> np.ndarray:
        return self.phase > 0


def balance_track(com: np.ndarray, corners: np.ndarray, fps: float, floor: np.ndarray | float = 0.0,
                  contact_height: float = 0.02, cutoff_hz: float = 6.0, breaks: list[int] | None = None) -> BalanceTrack:
    floor = np.array(np.broadcast_to(floor, (len(com),)), dtype=float)
    zmp, _ = zmp_cart_table(com, fps, floor, cutoff_hz, breaks)
    hulls, phase, contact = support_polygons(corners, floor, contact_height)
    cm = np.array([signed_margin(com[t, :2], h) if len(h) else np.nan for t, h in enumerate(hulls)])
    zm = np.array([signed_margin(zmp[t], h) if len(h) else np.nan for t, h in enumerate(hulls)])
    return BalanceTrack(fps, com, zmp, floor, phase, contact, hulls, cm, zm)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
    return list(zip(edges[::2], edges[1::2]))


def outside_flag(margin: np.ndarray, fps: float, tolerance: float = 0.02, min_duration: float = 0.1) -> np.ndarray:
    """Frames where a point stays more than ``tolerance`` outside the support for at
    least ``min_duration`` (frames without support never count)."""
    out = np.nan_to_num(margin, nan=0.0) < -tolerance
    n = max(1, int(round(min_duration * fps)))
    flag = np.zeros_like(out)
    for a, b in _runs(out):
        if b - a >= n:
            flag[a:b] = True
    return flag


def static_unbalanced(track: BalanceTrack, tolerance: float = 0.02, max_speed: float = 0.1,
                      min_duration: float = 0.2) -> np.ndarray:
    """Frames where the body is nearly still (CoM slower than ``max_speed`` m/s) and its CoM
    projection lies more than ``tolerance`` outside the support, for ``min_duration``.
    No dynamics or approximation is involved: a robot standing like this falls over (or
    rests on something the clip does not show). A walking CoM leaving the stance foot
    moves too fast to count."""
    c = lowpass(track.com, track.fps)
    speed = np.linalg.norm(np.gradient(c[:, :2], 1.0 / track.fps, axis=0), axis=1) if len(c) >= 2 else np.zeros(len(c))
    out = (np.nan_to_num(track.com_margin, nan=0.0) < -tolerance) & (speed < max_speed)
    n = max(1, int(round(min_duration * track.fps)))
    flag = np.zeros_like(out)
    for a, b in _runs(out):
        if b - a >= n:
            flag[a:b] = True
    return flag


def summarize(track: BalanceTrack, tolerance: float = 0.02, min_duration: float = 0.1,
              frame_offset: int = 0, static: np.ndarray | None = None) -> dict:
    """JSON-ready balance summary. Ratios are over supported frames; times in seconds.
    ``static``: a static_unbalanced flag computed with other settings (default: defaults)."""
    fps, sup = track.fps, track.supported
    n_sup = max(int(sup.sum()), 1)
    static = static_unbalanced(track, tolerance) if static is None else static
    out = {
        "support_phase_ratio": {"double": round(float((track.phase >= 2).mean()), 4),
                                "single": round(float((track.phase == 1).mean()), 4),
                                "none": round(float((track.phase == 0).mean()), 4)},
        "outside_tolerance_m": tolerance,
        "static_unbalanced_ratio": round(float(static.sum() / n_sup), 4),
        "static_unbalanced_first_s": round((int(np.argmax(static)) + frame_offset) / fps, 3) if static.any() else None,
    }
    for key, margin in (("com", track.com_margin), ("zmp", track.zmp_margin)):
        m = margin[sup]
        flag = outside_flag(margin, fps, tolerance, min_duration)
        entry = {
            "margin_m": {"min": None, "p5": None, "median": None},
            "outside_ratio": round(float((np.nan_to_num(margin, nan=0.0) < 0).sum() / n_sup), 4),
            f"outside_ratio(>{tolerance * 100:g}cm for >={min_duration:g}s)": round(float(flag.sum() / n_sup), 4),
            "worst_time_s": None,
            "longest_outside_s": None,
        }
        if len(m) and np.isfinite(m).any():
            entry["margin_m"] = {"min": round(float(np.nanmin(m)), 4), "p5": round(float(np.nanpercentile(m, 5)), 4),
                                 "median": round(float(np.nanmedian(m)), 4)}
            entry["worst_time_s"] = round((int(np.nanargmin(margin)) + frame_offset) / fps, 3)
        runs = _runs(np.nan_to_num(margin, nan=0.0) < 0)
        if runs:
            a, b = max(runs, key=lambda r: r[1] - r[0])
            entry["longest_outside_s"] = [round((a + frame_offset) / fps, 3), round((b - 1 + frame_offset) / fps, 3)]
        out[key] = entry
    return out
