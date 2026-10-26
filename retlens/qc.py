"""Frame-level quality checks used to decide how many seconds of a clip are valid.

A frame is *hard*-flagged when the data at that frame is unusable (NaN, pops,
floor penetration, sustained floating, robot joint-limit violations, fall).
Foot skating and robot static imbalance (add_balance_flags) are *soft* flags:
reported, and only affect the clip status.

    valid_seconds = (#frames without a hard flag) / fps     (0 for FAIL clips)
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field, fields

import numpy as np

from .motion import RobotMotion, SkeletonMotion
from .rotations import quat_to_matrix

HARD_FLAGS_HUMAN = ("nan", "spike", "penetration", "floating", "missing_markers")
HARD_FLAGS_ROBOT = ("nan", "joint_limit", "joint_velocity", "fallen")


@dataclass
class QCConfig:
    # human
    max_joint_speed: float = 15.0  # m/s. Faster = marker swap / solver pop
    max_glitch_duration: float = 1.0  # s. Frames between two pops this close are bad too
    penetration_depth: float = 0.03  # m below z=0
    float_height: float = 0.15  # m: lowest joint of the body above the floor
    float_min_duration: float = 0.5  # s. Shorter airborne phases are jumps
    contact_height: float = 0.02  # m above the foot joint's own lowest height
    skate_speed: float = 0.3  # m/s horizontal speed of a foot in contact
    skate_min_duration: float = 0.1  # s. Shorter = heel strike / toe-off, not a slide
    max_missing_markers: float = 0.10  # fraction of markers missing in a frame
    floor_offset_tol: float = 0.05  # m. Larger = floor calibration problem
    # robot
    joint_limit_margin: float = 0.01  # rad tolerated beyond the URDF limit (IK rests on limits)
    default_max_joint_velocity: float = 25.0  # rad/s when the URDF gives none
    max_root_tilt_deg: float = 75.0
    min_root_height: float = 0.25  # m
    # robot balance (needs the robot model: retlens.stability; soft flag, see add_balance_flags)
    support_contact_height: float = 0.02  # m: sole points this close to the floor support the robot
    balance_tolerance: float = 0.02  # m outside the support polygon before it counts
    static_max_speed: float = 0.1  # m/s: CoM slower than this = standing still
    static_min_duration: float = 0.2  # s
    max_static_unbalanced_ratio: float = 0.05  # more -> clip WARN
    # clip verdict
    min_duration: float = 1.0  # s
    pass_hard_ratio: float = 0.02
    warn_hard_ratio: float = 0.10
    max_skate_ratio: float = 0.15

    @classmethod
    def from_dict(cls, d: dict | None) -> "QCConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class QCResult:
    name: str
    source: str
    kind: str
    fps: float
    num_frames: int
    duration_s: float
    valid_s: float
    status: str  # PASS | WARN | FAIL
    metrics: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    flags: dict = field(default_factory=dict, repr=False)  # name -> (T,) bool

    def hard_mask(self) -> np.ndarray:
        hard = HARD_FLAGS_ROBOT if self.kind == "robot" else HARD_FLAGS_HUMAN
        m = np.zeros(self.num_frames, dtype=bool)
        for k in hard:
            if k in self.flags:
                m |= self.flags[k]
        return m

    def row(self) -> dict:
        d = asdict(self)
        d.pop("flags")
        metrics = d.pop("metrics")
        d["notes"] = "; ".join(d["notes"])
        d.update({f"m_{k}": v for k, v in metrics.items()})
        return d


def _sustained(mask: np.ndarray, min_len: int) -> np.ndarray:
    """Keep only runs of True that are at least min_len long."""
    out = np.zeros_like(mask)
    start = None
    for i, v in enumerate(np.append(mask, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out[start:i] = True
            start = None
    return out


def _frame_speed(pos: np.ndarray, fps: float) -> np.ndarray:
    """(T, J, 3) -> (T, J) speed, backward difference, first frame copies second."""
    v = np.linalg.norm(np.diff(pos, axis=0), axis=-1) * fps
    return np.concatenate([v[:1], v], axis=0) if len(v) else np.zeros(pos.shape[:2])


def _verdict(res: QCResult, cfg: QCConfig, hard: np.ndarray, skate_ratio: float, extra_warn: bool):
    hard_ratio = float(hard.mean()) if hard.size else 1.0
    res.metrics["hard_ratio"] = round(hard_ratio, 4)
    if hard_ratio > cfg.pass_hard_ratio:
        worst = [k for k, v in res.flags.items() if k != "skating" and v.any()]
        res.notes.append(f"{100 * hard_ratio:.1f}% frames bad ({', '.join(worst)})")
    if skate_ratio > cfg.max_skate_ratio:
        res.notes.append(f"foot skating in {100 * skate_ratio:.0f}% of frames")
    if res.duration_s < cfg.min_duration:
        res.notes.append(f"shorter than {cfg.min_duration}s")
        res.status = "FAIL"
    elif hard_ratio > cfg.warn_hard_ratio:
        res.status = "FAIL"
    elif hard_ratio > cfg.pass_hard_ratio or skate_ratio > cfg.max_skate_ratio or extra_warn:
        res.status = "WARN"
    else:
        res.status = "PASS"
    res.valid_s = 0.0 if res.status == "FAIL" else float((~hard).sum() / res.fps)


def check_skeleton(m: SkeletonMotion, cfg: QCConfig | None = None) -> QCResult:
    cfg = cfg or QCConfig()
    T = m.num_frames
    res = QCResult(m.name, m.source, m.kind, m.fps, T, m.duration, 0.0, "FAIL")
    if T == 0 or m.fps <= 0:
        res.notes.append("empty clip or unknown frame rate")
        return res
    pos = m.positions
    finite = np.isfinite(pos).all(-1)  # (T, J)

    if m.kind == "markers":
        missing = 1.0 - finite.mean(-1)
        res.flags["missing_markers"] = missing > cfg.max_missing_markers
        res.flags["nan"] = ~finite.any(-1)
        res.metrics["mean_missing_markers"] = round(float(missing.mean()), 4)
    else:
        res.flags["nan"] = ~finite.all(-1)

    speed = _frame_speed(pos, m.fps)
    speed = np.where(np.isfinite(speed), speed, 0.0)
    spike = (speed > cfg.max_joint_speed).any(-1)
    # a pop followed by a pop back shortly after (marker swap, solver flip):
    # the frames in between are displaced too, so flag the whole segment
    idx = np.flatnonzero(spike)
    gap = int(round(cfg.max_glitch_duration * m.fps))
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= gap:
            spike[a:b] = True
    res.flags["spike"] = spike
    res.metrics["max_joint_speed"] = round(float(speed.max()), 3)

    skate_ratio = 0.0
    extra_warn = False
    feet = [i for i in m.find_joints("toe", "foot", "ankle", "heel") if not m.joint_names[i].endswith("_end")]
    feet = feet or m.find_joints("toe", "foot", "ankle", "heel")
    if feet:
        fz = np.where(np.isfinite(pos[:, feet, 2]), pos[:, feet, 2], np.nan)
        with warnings.catch_warnings():  # all-NaN frames are already flagged as "nan"
            warnings.simplefilter("ignore", RuntimeWarning)
            lowest = np.nanmin(fz, axis=1)
            own_floor = np.nanpercentile(fz, 1, axis=0)
        lowest = np.where(np.isfinite(lowest), lowest, 0.0)
        floor = float(np.percentile(lowest, 1))
        res.metrics["floor_offset_m"] = round(floor, 4)
        if abs(floor) > cfg.floor_offset_tol:
            res.notes.append(f"floor offset {floor:+.3f} m (calibration / grounding?)")
            extra_warn = True
        res.flags["penetration"] = lowest < -cfg.penetration_depth
        # floating: the whole body is off the floor (lying or crawling people lift
        # their feet; markers count too, so this works for C3D)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            body_low = np.nanmin(np.where(finite, pos[..., 2], np.nan), axis=1)
        body_low = np.where(np.isfinite(body_low), body_low, 0.0)
        res.flags["floating"] = _sustained(
            body_low > cfg.float_height, max(1, int(round(cfg.float_min_duration * m.fps)))
        )
        # foot skating: a foot joint at its own ground level that keeps sliding
        # horizontally for skate_min_duration (shorter runs are heel strike / toe-off)
        contact = fz < own_floor + cfg.contact_height
        hspeed = _frame_speed(pos[:, feet, :2], m.fps)
        slide = contact & (hspeed > cfg.skate_speed)
        n_min = max(1, int(round(cfg.skate_min_duration * m.fps)))
        skating = np.stack([_sustained(slide[:, j], n_min) for j in range(slide.shape[1])], 1).any(-1)
        res.flags["skating"] = skating
        skate_ratio = float(skating.mean())
        res.metrics["skate_ratio"] = round(skate_ratio, 4)
    else:
        res.notes.append("no foot joints/markers found: ground checks skipped")

    bones = m.bones()
    if bones:
        p, c = np.array(bones).T
        lengths = np.linalg.norm(pos[:, c] - pos[:, p], axis=-1)
        cv = np.nanstd(lengths, 0) / np.maximum(np.nanmean(lengths, 0), 1e-6)
        res.metrics["max_bone_length_cv"] = round(float(np.nanmax(cv)), 4)

    for k, v in res.flags.items():
        res.metrics[f"{k}_ratio"] = round(float(v.mean()), 4)
    _verdict(res, cfg, res.hard_mask(), skate_ratio, extra_warn)
    return res


def check_robot(
    m: RobotMotion,
    cfg: QCConfig | None = None,
    limits: dict[str, tuple[float, float, float]] | None = None,
) -> QCResult:
    """limits: joint name -> (lower, upper, max_velocity), e.g. from urdf_joint_limits()."""
    cfg = cfg or QCConfig()
    T = m.num_frames
    res = QCResult(m.name, m.source, "robot", m.fps, T, m.duration, 0.0, "FAIL")
    if T == 0 or m.fps <= 0:
        res.notes.append("empty clip or unknown frame rate")
        return res
    q = m.dof_pos
    res.flags["nan"] = ~(
        np.isfinite(q).all(-1) & np.isfinite(m.root_pos).all(-1) & np.isfinite(m.root_quat).all(-1)
    )

    vel_lim = np.full(q.shape[1], cfg.default_max_joint_velocity)
    lim_violation = np.zeros(T, dtype=bool)
    worst = {}
    if limits:
        missing = [n for n in m.joint_names if n not in limits]
        if missing:
            res.notes.append(f"{len(missing)} joints without URDF limits")
        for i, n in enumerate(m.joint_names):
            if n not in limits:
                continue
            lo, hi, vmax = limits[n]
            over = np.maximum(q[:, i] - (hi + cfg.joint_limit_margin), 0) + np.maximum(
                (lo - cfg.joint_limit_margin) - q[:, i], 0
            )
            if (over > 0).any():
                worst[n] = round(float(over.max()), 4)
            lim_violation |= over > 0
            if np.isfinite(vmax) and vmax > 0:
                vel_lim[i] = vmax
    else:
        res.notes.append("no joint limits given: limit check skipped")
    res.flags["joint_limit"] = lim_violation
    if worst:
        res.metrics["worst_limit_excess_rad"] = dict(sorted(worst.items(), key=lambda kv: -kv[1])[:5])

    dq = np.abs(np.diff(q, axis=0)) * m.fps
    dq = np.concatenate([dq[:1], dq], 0) if len(dq) else np.zeros_like(q)
    res.flags["joint_velocity"] = (dq > vel_lim).any(-1)
    res.metrics["max_joint_velocity"] = round(float(np.nanmax(dq)), 3) if dq.size else 0.0

    up = quat_to_matrix(m.root_quat)[:, :, 2]  # body z-axis in world
    tilt = np.degrees(np.arccos(np.clip(up[:, 2], -1, 1)))
    res.flags["fallen"] = (tilt > cfg.max_root_tilt_deg) | (m.root_pos[:, 2] < cfg.min_root_height)
    res.metrics["max_root_tilt_deg"] = round(float(np.nanmax(tilt)), 2)

    for k, v in res.flags.items():
        res.metrics[f"{k}_ratio"] = round(float(v.mean()), 4)
    _verdict(res, cfg, res.hard_mask(), 0.0, False)
    return res


def add_balance_flags(res: QCResult, static_unbalanced: np.ndarray, cfg: QCConfig | None = None,
                      metrics: dict | None = None) -> QCResult:
    """Add the soft flag ``static_unbalanced`` (retlens.stability.static_unbalanced: standing
    still with the CoM outside the feet's support polygon) to a robot QC result.

    Soft, not hard: it does not reduce valid time, only turns PASS into WARN above
    ``max_static_unbalanced_ratio``. The support polygon only knows the feet, so a
    clip that rests a hand on a table or kneels is flagged as well. On clean CMU /
    LAFAN1 / Unitree retargets it is 0-1 %; CMU subject 143 (feet pitched toe-up by
    the retarget, standing on the heels) 22-39 %; LAFAN1 fall-and-get-up 12 %.
    ZMP leaving the support is reported (metrics) but not flagged: with the
    cart-table model even Unitree's official retargets of LAFAN1 dance / run show it
    in 58-67 % of frames, so it does not separate good data from bad.
    """
    cfg = cfg or QCConfig()
    flag = np.asarray(static_unbalanced, dtype=bool)
    if flag.shape != (res.num_frames,):
        raise ValueError(f"balance flag has {flag.shape}, clip has {res.num_frames} frames")
    res.flags["static_unbalanced"] = flag
    ratio = float(flag.mean()) if flag.size else 0.0
    res.metrics["static_unbalanced_ratio"] = round(ratio, 4)
    res.metrics.update(metrics or {})
    if ratio > cfg.max_static_unbalanced_ratio:
        res.notes.append(f"standing with the CoM outside the feet in {100 * ratio:.0f}% of frames")
        if res.status == "PASS":
            res.status = "WARN"
    return res


def check_motion(m, cfg: QCConfig | None = None, limits=None) -> QCResult:
    if isinstance(m, RobotMotion):
        return check_robot(m, cfg, limits)
    return check_skeleton(m, cfg)
