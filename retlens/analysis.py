"""Compare robot motions: time alignment, joint differences, smoothness, foot contact.

Used by tools/compare_viewer.py. Everything here is numpy except the foot
metrics, which run MuJoCo forward kinematics on GMR's robot model (imported
lazily, like retlens.retarget).

Time convention: every motion has a display offset ``o`` (seconds); at global
time T it shows its own local time ``T - o``. ``estimate_offset`` returns the
offset that best lines a motion up with a reference.
"""

from __future__ import annotations

import numpy as np

from . import stability
from .motion import RobotMotion
from .rotations import quat_normalize

# legs carry the gait and are the least ambiguous joints (arm twist differs between retargeters)
LEG_KEYS = ("hip", "knee", "ankle")
PLANTED_HEIGHT = 0.025  # m: every sole contact point below this = foot planted flat
SLIDE_SPEED = 0.3  # m/s
SLIDE_MIN_DURATION = 0.1  # s
SWING_SPEED = 0.5  # m/s: a foot whose slowest sole point moves this fast is in swing
SWING_CLEARANCE = 0.01  # m: a swing foot this close to the floor (floor_track) catches it in physics
BALANCE_MIN_DURATION = 0.1  # s: a point outside the support this long counts as "sustained"


def common_joints(*motions: RobotMotion) -> list[str]:
    names = list(motions[0].joint_names)
    for m in motions[1:]:
        keep = set(m.joint_names)
        names = [n for n in names if n in keep]
    return names


def sample_dof(m: RobotMotion, t: np.ndarray, joints: list[str] | None = None) -> np.ndarray:
    """Joint angles at local times t (s), linear interpolation, clamped to the clip."""
    idx = [m.joint_names.index(n) for n in joints] if joints else list(range(len(m.joint_names)))
    f = np.clip(np.asarray(t, dtype=np.float64) * m.fps, 0, m.num_frames - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, m.num_frames - 1)
    a = (f - i0)[:, None]
    return (1 - a) * m.dof_pos[i0][:, idx] + a * m.dof_pos[i1][:, idx]


def sample_root(m: RobotMotion, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Root position and wxyz quaternion at local times t (lerp / nlerp, clamped)."""
    f = np.clip(np.asarray(t, dtype=np.float64) * m.fps, 0, m.num_frames - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, m.num_frames - 1)
    a = (f - i0)[:, None]
    q0, q1 = m.root_quat[i0], m.root_quat[i1]
    q1 = np.where(np.sum(q0 * q1, axis=1, keepdims=True) < 0, -q1, q1)
    return (1 - a) * m.root_pos[i0] + a * m.root_pos[i1], quat_normalize((1 - a) * q0 + a * q1)


def overlap(ref: RobotMotion, other: RobotMotion, offset_ref: float = 0.0, offset_other: float = 0.0,
            fps: float | None = None) -> np.ndarray:
    """Global times (s) where both motions have data, on the reference frame grid."""
    fps = fps or ref.fps
    start = max(offset_ref, offset_other)
    end = min(offset_ref + (ref.num_frames - 1) / ref.fps, offset_other + (other.num_frames - 1) / other.fps)
    if end <= start:
        return np.zeros(0)
    return np.arange(start, end + 1e-9, 1.0 / fps)


def joint_rmse(ref: RobotMotion, other: RobotMotion, offset_ref: float = 0.0, offset_other: float = 0.0,
               joints: list[str] | None = None) -> tuple[list[str], np.ndarray, float]:
    """Per-joint RMSE in degrees over the overlap. Returns (joints, rmse_deg, overlap_s)."""
    joints = joints or common_joints(ref, other)
    T = overlap(ref, other, offset_ref, offset_other)
    if len(T) < 2:
        return joints, np.full(len(joints), np.nan), 0.0
    d = sample_dof(ref, T - offset_ref, joints) - sample_dof(other, T - offset_other, joints)
    return joints, np.degrees(np.sqrt((d ** 2).mean(0))), float(T[-1] - T[0])


def estimate_offset(ref: RobotMotion, other: RobotMotion, max_shift: float = 3.0,
                    joints: list[str] | None = None, min_overlap: float = 1.0) -> tuple[float, float]:
    """Display offset (s) for ``other`` (reference at offset 0) that minimises the mean
    squared leg-joint difference. Returns (offset, rms_deg at that offset)."""
    joints = joints or [n for n in common_joints(ref, other) if any(k in n for k in LEG_KEYS)]
    if not joints:
        joints = common_joints(ref, other)
    step = 1.0 / ref.fps
    best = (np.inf, 0.0)
    for s in np.arange(-max_shift, max_shift + 1e-9, step):
        T = overlap(ref, other, 0.0, s)
        if len(T) < 2 or T[-1] - T[0] < min_overlap:
            continue
        d = sample_dof(ref, T, joints) - sample_dof(other, T - s, joints)
        best = min(best, (float((d ** 2).mean()), float(s)))
    if not np.isfinite(best[0]):
        return 0.0, float("nan")
    return round(best[1], 4), float(np.degrees(np.sqrt(best[0])))


def smoothness(m: RobotMotion) -> dict:
    """Joint velocity / acceleration / jerk statistics (rad/s, rad/s^2, rad/s^3)."""
    q, fps = m.dof_pos, m.fps
    if m.num_frames < 4:
        return {}
    vel = np.abs(np.diff(q, axis=0)) * fps
    return {
        "acc_mean": float((np.abs(np.diff(q, 2, axis=0)) * fps ** 2).mean()),
        "jerk_mean": float((np.abs(np.diff(q, 3, axis=0)) * fps ** 3).mean()),
        "vel_p99": float(np.percentile(vel, 99)),
        "vel_max": float(vel.max()),
    }


def _sustained(mask: np.ndarray, n: int) -> np.ndarray:
    from .qc import _sustained as sustained

    return sustained(mask, n)


class FootKinematics:
    """MuJoCo FK of GMR's robot model: per-frame sole heights and foot positions."""

    def __init__(self, robot: str = "unitree_g1", foot_bodies=("left_ankle_roll_link", "right_ankle_roll_link")):
        import mujoco as mj

        from .retarget import robot_joint_names, robot_model

        self.mj = mj
        self.model = robot_model(robot)
        self.data = mj.MjData(self.model)
        self.joint_names = robot_joint_names(self.model)
        self.feet = [mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_BODY, b) for b in foot_bodies]
        self.soles = [[g for g in range(self.model.ngeom) if self.model.geom_bodyid[g] == b
                       and (self.model.geom_contype[g] or self.model.geom_conaffinity[g])] for b in self.feet]

    def run(self, m: RobotMotion) -> dict:
        """{"sole": (T,2) lowest contact point, "flat": (T,2) highest contact point, "foot": (T,2,3),
        "points": (T,2,G,3) bottom of every sole contact sphere, "com": (T,3) whole-body CoM}."""
        mj, model, data = self.mj, self.model, self.data
        col = {n: i for i, n in enumerate(m.joint_names)}
        idx = [col.get(n) for n in self.joint_names]
        T = m.num_frames
        G = max(1, max(len(g) for g in self.soles))
        sole, flat, foot = np.zeros((T, 2)), np.zeros((T, 2)), np.zeros((T, 2, 3))
        points, com = np.zeros((T, 2, G, 3)), np.zeros((T, 3))
        q = model.qpos0.copy()
        for t in range(T):
            q[:3], q[3:7] = m.root_pos[t], m.root_quat[t]
            q[7:] = [m.dof_pos[t, i] if i is not None else 0.0 for i in idx]
            data.qpos[:] = q
            mj.mj_kinematics(model, data)
            mj.mj_comPos(model, data)
            com[t] = data.subtree_com[0]  # the world body's subtree = the whole robot
            for k, (b, geoms) in enumerate(zip(self.feet, self.soles)):
                foot[t, k] = data.xpos[b]
                pts = [data.geom_xpos[g] - [0.0, 0.0, model.geom_size[g][0]] for g in geoms] or [data.xpos[b]]
                points[t, k] = pts + [pts[-1]] * (G - len(pts))
                sole[t, k], flat[t, k] = min(p[2] for p in pts), max(p[2] for p in pts)
        return {"sole": sole, "flat": flat, "foot": foot, "points": points, "com": com}


def slowest_sole_speed(points: np.ndarray, fps: float) -> np.ndarray:
    """(T, feet) horizontal speed of each foot's slowest sole contact point (m/s): ~0 for
    a foot on the floor, also while it rolls over the heel or toe."""
    s = np.linalg.norm(np.diff(points[..., :2], axis=0), axis=-1).min(-1) * fps
    return np.concatenate([s[:1], s])


def floor_track(sole: np.ndarray, speed: np.ndarray, fps: float, still: float = SLIDE_SPEED) -> np.ndarray:
    """(T,) floor height under the robot through a clip: the lower of the feet standing
    still (slowest sole point below ``still`` m/s), interpolated between such frames and
    median-filtered over ~0.3 s. Retargets drift (CMU 02_01's floor rises ~4 cm), so a
    single clip-wide floor level misjudges how close a moving foot comes to it."""
    from scipy.ndimage import median_filter

    T = len(sole)
    standing = speed < still
    ts = np.flatnonzero(standing.any(1))
    if not len(ts):
        return np.full(T, float(np.percentile(sole, 5)))
    floor = np.interp(np.arange(T), ts, [sole[t, standing[t]].min() for t in ts])
    return median_filter(floor, size=max(3, int(0.3 * fps) | 1), mode="nearest")


def balance(m: RobotMotion, fk: FootKinematics, cfg=None, r: dict | None = None):
    """(BalanceTrack, summary dict, static_unbalanced flag) of a robot motion, from MuJoCo FK of
    the robot model (CoM, sole points) with the floor tracked through the clip. ``cfg`` is a
    retlens.qc.QCConfig (support / balance thresholds); ``r`` a precomputed fk.run(m)."""
    from .qc import QCConfig

    cfg = cfg or QCConfig()
    r = r if r is not None else fk.run(m)
    floor = floor_track(r["sole"], slowest_sole_speed(r["points"], m.fps), m.fps)
    track = stability.balance_track(r["com"], r["points"], m.fps, floor, cfg.support_contact_height)
    static = stability.static_unbalanced(track, cfg.balance_tolerance, cfg.static_max_speed, cfg.static_min_duration)
    return track, stability.summarize(track, cfg.balance_tolerance, BALANCE_MIN_DURATION, static=static), static


def foot_metrics(m: RobotMotion, fk: FootKinematics) -> dict:
    """Planted-foot slip (% frames), mean planted-foot speed, penetration (% frames < -2 cm),
    moving feet within 1 cm of the floor (% of moving-foot frames)."""
    r = fk.run(m)
    if m.num_frames < 2:
        return {}
    hs = np.linalg.norm(np.diff(r["foot"][:, :, :2], axis=0), axis=-1) * m.fps
    planted = r["flat"][1:] < PLANTED_HEIGHT
    n = max(1, int(round(SLIDE_MIN_DURATION * m.fps)))
    slide = np.stack([_sustained(planted[:, k] & (hs[:, k] > SLIDE_SPEED), n) for k in range(2)], 1).any(1)
    lowest = r["sole"].min(1)
    # moving feet skimming the floor: in physics they catch it and the robot stumbles (the
    # SMPL-X / FBX retargets of CMU 02_01 that fall in Isaac do this 2-3x as often as the BVH one).
    # Moving = even the foot's slowest sole point slides (a heel rising over the toe is not);
    # height above the floor tracked through the clip (floor_track).
    speed = slowest_sole_speed(r["points"], m.fps)
    swing = speed > SWING_SPEED
    floor = floor_track(r["sole"], speed, m.fps)
    rel = r["sole"] - floor[:, None]
    low_swing = float(100 * (swing & (rel < SWING_CLEARANCE)).sum() / max(swing.sum(), 1))
    # balance: CoM projection and cart-table ZMP against the feet's support polygon
    bal, bs, static = balance(m, fk, r=r)
    sustained = next(k for k in bs["zmp"] if k.startswith("outside_ratio(>"))
    return {
        "planted_slip_pct": float(100 * slide.mean()),
        "planted_speed": float(hs[planted].mean()) if planted.any() else float("nan"),
        "penetration_pct": float(100 * (lowest < -0.02).mean()),
        "sole_min_cm": float(100 * lowest.min()),
        "swing_low_pct": low_swing,
        "com_out_pct": 100 * bs["com"]["outside_ratio"],
        "zmp_out_pct": 100 * bs["zmp"]["outside_ratio"],
        "zmp_out_sustained_pct": 100 * bs["zmp"][sustained],
        "zmp_margin_p5_cm": None if bs["zmp"]["margin_m"]["p5"] is None else 100 * bs["zmp"]["margin_m"]["p5"],
        "static_unbalanced_pct": 100 * bs["static_unbalanced_ratio"],
        "no_support_pct": 100 * bs["support_phase_ratio"]["none"],
        "_flat": r["flat"],
        "_sole": r["sole"],
        "_balance": bal,
        "_static_unbalanced": static,
    }
