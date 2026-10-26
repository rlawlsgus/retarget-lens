"""Retargeting quality: how faithfully a robot reproduces the human motion it was retargeted
from, and how much of it the robot's body allows. Measured the same way for every robot, so
robots (and retargeting settings) compare on the same clips (tools/retarget_benchmark.py).

Robot-independent by construction:
- pose: angles between matching limb segments (thigh, shin, upper arm, forearm; trunk =
  pelvis to the middle of the shoulders), so the robot's size and proportions do not count,
  only whether its limbs point where the human's do;
- feet: whether each foot is on the floor when the human's is, both judged from the ankle
  with thresholds in leg lengths;
- pelvis height as a fraction of each one's standing height (squats as deep);
- the robot's own limits: joints pinned at their range limits, body parts going through
  each other (MuJoCo collision of the robot model's collision geoms).

A robot takes part through the tables retlens/retarget.py already needs to retarget to it
(TPOSE_LIMBS: robot segment <-> human segment, TPOSE_FEET). score() folds these and the
existing foot / balance metrics into 0-100 (SCORE_RULES).
"""

from __future__ import annotations

import numpy as np

from .motion import RobotMotion, SkeletonMotion

SEGMENT_KO = {"UpLeg": "허벅지", "Leg": "정강이", "Arm": "위팔", "ForeArm": "아래팔"}
CONTACT_SPEED = 0.4  # leg lengths / s: an ankle slower than this...
CONTACT_HEIGHT = 0.08  # leg lengths: ...and this close to its floor is on the floor
LIMIT_MARGIN = np.radians(1.0)  # a joint this close to a range limit is pinned there
# m: body parts deeper into each other than this collide. The collision geoms are convex hulls of
# the link meshes, larger than the links: G1's torso / shoulder hulls overlap up to 1.7 cm in
# ordinary poses and hands brushing the hips read 2-3 cm.
COLLISION_DEPTH = 0.03

# 리타게팅 점수 = 100 - penalties. Each rule: (metric key, value with no penalty, value with the
# full penalty, full penalty). Linear in between; nan (not measured) costs nothing.
SCORE_RULES = (
    ("pose_err_deg", 8.0, 25.0, 30.0),  # limbs pointing elsewhere than the human's
    ("contact_mismatch_pct", 5.0, 30.0, 20.0),  # feet on / off the floor at other times
    ("self_collision_pct", 5.0, 50.0, 15.0),
    ("joint_limit_pct", 5.0, 50.0, 10.0),
    ("planted_slip_pct", 1.0, 10.0, 10.0),
    ("static_unbalanced_pct", 2.0, 20.0, 10.0),
    ("penetration_pct", 0.0, 10.0, 5.0),
)
GRADES = ((85.0, "좋음"), (70.0, "보통"), (0.0, "나쁨"))
SCORE_LABELS = {"pose_err_deg": "자세 재현", "contact_mismatch_pct": "발 접촉", "self_collision_pct": "자기 충돌",
                "joint_limit_pct": "관절 한계", "planted_slip_pct": "발 미끄러짐", "static_unbalanced_pct": "정적 불균형",
                "penetration_pct": "바닥 관통"}


def segments(robot: str) -> list[tuple[str, tuple[str, str], tuple[str, str]]]:
    """(name, robot (from body, to body), human (from role, to role)) of the robot's limbs."""
    from .retarget import TPOSE_LIMBS

    out = []
    for _, pairs in TPOSE_LIMBS.get(robot, []):
        for rseg, hseg in pairs:
            side = "왼" if hseg[0].startswith("Left") else "오른"
            out.append((f"{side} {SEGMENT_KO.get(hseg[0][4:] if side == '왼' else hseg[0][5:], hseg[0])}", rseg, hseg))
    return out


def supported(robot: str) -> bool:
    return bool(segments(robot))


def foot_bodies(robot: str) -> tuple[str, ...]:
    """The robot's foot bodies (left, right), for analysis.FootKinematics."""
    from .retarget import TPOSE_FEET

    return tuple(body for _, body in TPOSE_FEET.get(robot, []))


def model_limits(model) -> dict[str, tuple[float, float, float]]:
    """Joint limits of a robot model in retlens.io.urdf_joint_limits's form (no velocity limits)."""
    from .retarget import robot_joint_names, robot_joint_ranges

    lo, hi = robot_joint_ranges(model)
    return {n: (float(a), float(b), float("inf")) for n, a, b in zip(robot_joint_names(model), lo, hi)}


class _RobotFK:
    """MuJoCo FK of a robot model over a motion: body positions / frames and self-collisions."""

    def __init__(self, model):
        import mujoco as mj

        from .retarget import robot_joint_names, robot_joint_ranges

        self.mj, self.model = mj, model
        self.data = mj.MjData(model)
        self.joint_names = robot_joint_names(model)
        self.lo, self.hi = robot_joint_ranges(model)
        # a copy where every robot collision geom collides with every other (the floor and the
        # visual-only geoms stay out); MuJoCo itself skips parent-child pairs
        self.cmodel = model.__copy__()
        robot_geom = (model.geom_bodyid > 0) & ((model.geom_contype > 0) | (model.geom_conaffinity > 0))
        self.cmodel.geom_contype[:] = np.where(robot_geom, 1, 0)
        self.cmodel.geom_conaffinity[:] = np.where(robot_geom, 1, 0)
        self.cdata = mj.MjData(self.cmodel)
        self.parent = model.body_parentid

    def body(self, name: str) -> int:
        b = self.mj.mj_name2id(self.model, self.mj.mjtObj.mjOBJ_BODY, name)
        if b < 0:
            raise KeyError(f"robot model has no body {name!r}")
        return b

    def qpos(self, m: RobotMotion) -> np.ndarray:
        col = {n: i for i, n in enumerate(m.joint_names)}
        idx = [col.get(n) for n in self.joint_names]
        q = np.tile(self.model.qpos0, (m.num_frames, 1))
        q[:, :3], q[:, 3:7] = m.root_pos, m.root_quat
        for k, i in enumerate(idx):
            if i is not None:
                q[:, 7 + k] = m.dof_pos[:, i]
        return q

    def run(self, m: RobotMotion, bodies: list[int]) -> tuple[np.ndarray, np.ndarray, list[set]]:
        """Positions (T, B, 3) and frames (T, B, 3, 3) of the bodies, and per frame the
        colliding body pairs (not parent / child or siblings: those touch by design)."""
        mj, model, data, cm, cd = self.mj, self.model, self.data, self.cmodel, self.cdata
        Q = self.qpos(m)
        T = len(Q)
        pos, rot = np.zeros((T, len(bodies), 3)), np.zeros((T, len(bodies), 3, 3))
        hits = []
        for t in range(T):
            data.qpos[:] = Q[t]
            mj.mj_kinematics(model, data)
            pos[t] = data.xpos[bodies]
            rot[t] = data.xmat[bodies].reshape(-1, 3, 3)
            cd.qpos[:] = Q[t]
            mj.mj_kinematics(cm, cd)
            mj.mj_collision(cm, cd)
            pairs = set()
            for c in cd.contact[:cd.ncon]:
                if c.dist > -COLLISION_DEPTH:
                    continue
                a, b = sorted((int(cm.geom_bodyid[c.geom1]), int(cm.geom_bodyid[c.geom2])))
                if self.parent[a] == self.parent[b] or self.parent[b] == a or self.parent[a] == b:
                    continue
                pairs.add((a, b))
            hits.append(pairs)
        return pos, rot, hits

    def name(self, b: int) -> str:
        return self.mj.mj_id2name(self.model, self.mj.mjtObj.mjOBJ_BODY, b)


def _human_at(h: SkeletonMotion, joints: list[int], T: int, fps: float) -> np.ndarray:
    """(T, J, 3) human joint positions at the robot's frame times (the viewers' pairing)."""
    f = np.clip(np.arange(T) / fps * h.fps, 0, h.num_frames - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, h.num_frames - 1)
    w = (f - i0)[:, None, None]
    return (1 - w) * h.positions[i0][:, joints] + w * h.positions[i1][:, joints]


def _angle(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angle (deg) between vectors along the last axis; nan where either is ~0 or missing."""
    na, nb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.einsum("...i,...i->...", a, b) / (na * nb)
    c = np.where((na > 1e-4) & (nb > 1e-4), c, np.nan)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def _floor(z: np.ndarray, fps: float, window_s: float = 2.0) -> np.ndarray:
    """(T,) the floor under the feet: lowest ankle within a moving window (retargets and
    captures drift by a few cm over a clip), smoothed."""
    from scipy.ndimage import median_filter, minimum_filter1d

    n = max(3, int(window_s * fps) | 1)
    low = minimum_filter1d(np.nan_to_num(z.min(1), nan=np.nanmin(z)), n, mode="nearest")
    return median_filter(low, size=n, mode="nearest")


def contacts(ankles: np.ndarray, leg: float, fps: float) -> np.ndarray:
    """(T, 2) bool: ankle on the floor = slower than CONTACT_SPEED and lower than
    CONTACT_HEIGHT above its floor, both in leg lengths."""
    speed = np.linalg.norm(np.diff(ankles[..., :2], axis=0), axis=-1) * fps
    speed = np.concatenate([speed[:1], speed])
    height = ankles[..., 2] - _floor(ankles[..., 2], fps)[:, None]
    return (speed < CONTACT_SPEED * leg) & (height < CONTACT_HEIGHT * leg)


def measure(human: SkeletonMotion, m: RobotMotion, robot: str, model) -> dict:
    """Quality numbers of one retarget: human skeleton (as loaded; the robot follows it frame
    for frame) against the robot motion. Keys without a leading underscore are metrics."""
    from .retarget import _resolve_bvh_bodies

    segs = segments(robot)
    if not segs or human.kind != "skeleton" or m.num_frames < 4:
        return {}
    roles = _resolve_bvh_bodies(human.joint_names, human.parents)
    fk = _RobotFK(model)
    names = sorted({b for _, rseg, _ in segs for b in rseg})
    bodies = [fk.body(n) for n in names] + [fk.body(fk.name(1))]  # + the root (pelvis)
    pos, _, hits = fk.run(m, bodies)
    T = m.num_frames
    col = {n: i for i, n in enumerate(names)}
    role_names = sorted({r for _, _, hseg in segs for r in hseg} | {"Hips"})
    H = _human_at(human, [roles[r] for r in role_names], T, m.fps)
    hcol = {r: i for i, r in enumerate(role_names)}

    # pose: matching segments should point the same way
    per_seg = {}
    for name, (ra, rb), (ha, hb) in segs:
        per_seg[name] = _angle(pos[:, col[rb]] - pos[:, col[ra]], H[:, hcol[hb]] - H[:, hcol[ha]])
    # trunk: pelvis to the middle of the shoulders (the upper arms' upper ends) on both. Like for
    # like: the torso link's own axis against the human spine carried the reference pose's spine
    # tilt (CMU subject 143: 8 deg) into every frame.
    shoulders = [(ra, ha) for _, (ra, _rb), (ha, _hb) in segs if ha in ("LeftArm", "RightArm")]
    if len(shoulders) == 2:
        per_seg["몸통"] = _angle(pos[:, [col[r] for r, _ in shoulders]].mean(1) - pos[:, -1],
                                H[:, [hcol[h] for _, h in shoulders]].mean(1) - H[:, hcol["Hips"]])
    err = np.stack(list(per_seg.values()), 1)  # (T, S)

    # feet: on the floor at the same times; ankle = the shin segment's lower end
    shins = [(rb, hb) for _, (ra, rb), (ha, hb) in segs if hb.endswith("Foot")]
    up_r = {rb: ra for _, (ra, rb), _ in segs}
    up_h = {hb: ha for _, _, (ha, hb) in segs}
    ankle_r = [col[rb] for rb, _ in shins]
    ankle_h = [hcol[hb] for _, hb in shins]
    # leg length = thigh + shin of the first leg, the unit of the contact thresholds
    rb0, hb0 = shins[0]
    knee_r, knee_h = up_r[rb0], up_h[hb0]
    hip_r, hip_h = up_r[knee_r], up_h[knee_h]
    leg_r = float(np.nanmedian(np.linalg.norm(pos[:, col[knee_r]] - pos[:, col[hip_r]], axis=-1)
                               + np.linalg.norm(pos[:, col[rb0]] - pos[:, col[knee_r]], axis=-1)))
    leg_h = float(np.nanmedian(np.linalg.norm(H[:, hcol[knee_h]] - H[:, hcol[hip_h]], axis=-1)
                               + np.linalg.norm(H[:, hcol[hb0]] - H[:, hcol[knee_h]], axis=-1)))
    c_r = contacts(pos[:, ankle_r], leg_r, m.fps)
    c_h = contacts(H[:, ankle_h], leg_h, m.fps)
    lost = c_h & ~c_r  # the human stands on it, the robot's is up (or sliding)
    extra = c_r & ~c_h  # the robot's foot stays down while the human's moves

    # pelvis height as a fraction of standing height (above each one's ankle floor)
    pel_r = pos[:, -1, 2] - _floor(pos[:, ankle_r, 2], m.fps)
    pel_h = H[:, hcol["Hips"], 2] - _floor(H[:, ankle_h, 2], m.fps)
    frac_r = pel_r / max(float(np.nanpercentile(pel_r, 95)), 1e-6)
    frac_h = pel_h / max(float(np.nanpercentile(pel_h, 95)), 1e-6)

    # the robot's own limits
    q = m.dof_pos
    jcol = {n: i for i, n in enumerate(m.joint_names)}
    at_limit = np.zeros(q.shape, dtype=bool)
    for k, n in enumerate(fk.joint_names):
        i = jcol.get(n)
        if i is not None and np.isfinite(fk.lo[k]) and np.isfinite(fk.hi[k]):
            at_limit[:, i] = (q[:, i] <= fk.lo[k] + LIMIT_MARGIN) | (q[:, i] >= fk.hi[k] - LIMIT_MARGIN)
    pinned = {m.joint_names[i]: round(100 * float(at_limit[:, i].mean()), 1)
              for i in np.argsort(-at_limit.mean(0))[:3] if at_limit[:, i].any()}
    pair_count: dict = {}
    for pairs in hits:
        for p in pairs:
            pair_count[p] = pair_count.get(p, 0) + 1
    worst_pairs = {f"{fk.name(a)} / {fk.name(b)}": round(100 * n / T, 1)
                   for (a, b), n in sorted(pair_count.items(), key=lambda kv: -kv[1])[:3]}

    return {
        "pose_err_deg": float(np.nanmean(err)),
        "pose_err_p95_deg": float(np.nanpercentile(err, 95)),
        "contact_mismatch_pct": float(100 * (c_r != c_h).mean()),
        "contact_lost_pct": float(100 * lost.mean()),
        "contact_extra_pct": float(100 * extra.mean()),
        "pelvis_height_err_pct": float(100 * np.nanmean(np.abs(frac_r - frac_h))),
        "joint_limit_pct": float(100 * at_limit.any(1).mean()),
        "self_collision_pct": float(100 * np.mean([bool(p) for p in hits])),
        "_segments_deg": {k: round(float(np.nanmean(v)), 1) for k, v in per_seg.items()},
        "_pinned_joints_pct": pinned,
        "_collision_pairs_pct": worst_pairs,
        "_leg_length_m": {"robot": round(leg_r, 3), "human": round(leg_h, 3)},
    }


def score(metrics: dict) -> tuple[float, list[tuple[str, float]]]:
    """리타게팅 점수 0-100 from the quality and foot / balance metrics (SCORE_RULES), and what
    cost points (metric key, points), largest first."""
    lost = []
    for key, ok, bad, full in SCORE_RULES:
        v = metrics.get(key)
        if v is None or not np.isfinite(v):
            continue
        p = full * float(np.clip((v - ok) / (bad - ok), 0.0, 1.0))
        if p > 0.05:
            lost.append((key, round(p, 1)))
    lost.sort(key=lambda kv: -kv[1])
    return max(0.0, 100.0 - sum(p for _, p in lost)), lost


def grade(s: float) -> str:
    """좋음 / 보통 / 나쁨 of the score as shown (whole points: 84.6 shows as 85 and is 좋음)."""
    s = round(s)
    return next(g for lo, g in GRADES if s >= lo)
