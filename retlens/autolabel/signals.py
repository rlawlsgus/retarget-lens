"""Per-frame movement signals at 30 fps, from body joint positions.

Heights are above what the feet stand on, lengths are divided by the body's own sizes (stature,
arm, thigh), so the thresholds in segment.DEFAULTS hold for any body. The floor is found per
motion (where still feet stand most); a foot's support moves to another level (a stair, a
platform) where it stands on it carrying the body, and each heel and toe point is measured
against its own height while its foot stands on the floor. On a treadmill the signals are
taken in the belt's frame where, and only where, a belt runs. Reading files is kept apart
(retlens.autolabel.body), so every check goes through the same function.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

FPS = 30.0
UP = np.array([0.0, 0.0, 1.0])
STILL = 0.2  # a foot slower than this (m/s) stands still: the floor and the support levels are where feet stand
LEVEL_STEP = 0.05  # a support this much above or below a foot's last one is another level (half the lowest stair
#                    rise; less is the spread of the sole estimated from joint centres)
CARRIED = 0.75  # the pelvis at least this ratio of its standing height above a support: the leg stands on it
#                 (a 60 deg knee bend, segment low_pelvis), not a foot resting on a stool's rung
BELT_WINDOW = 2.0  # a moving support is looked for over this (s): a few steps
# the joints the signals use, by their SMPL names (retlens.autolabel.body maps other skeletons onto them)
JOINTS = ["pelvis", "l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle", "l_foot", "r_foot", "spine3", "head",
          "l_shoulder", "r_shoulder", "l_elbow", "r_elbow", "l_wrist", "r_wrist"]
DIMS = ["stature", "arm", "pelvis_h", "h_ankle", "h_toe", "thigh"]  # m, see body.dims_from_model


def resample(x, fps_in, fps_out):
    """Linear interpolation along the time axis (axis 0) to fps_out."""
    n = x.shape[0]
    if n < 2:
        return x
    t_in = np.arange(n) / fps_in
    t_out = np.arange(0, t_in[-1] + 1e-9, 1.0 / fps_out)
    flat = x.reshape(n, -1)
    out = np.empty((len(t_out), flat.shape[1]))
    for k in range(flat.shape[1]):
        out[:, k] = np.interp(t_out, t_in, flat[:, k])
    return out.reshape((len(t_out),) + x.shape[1:])


def _smooth(x, sec):
    n = max(1, int(round(sec * FPS)))
    return uniform_filter1d(x, size=n, axis=0, mode="nearest") if n > 1 else x


def _vel(x, sec):
    return np.gradient(_smooth(x, sec), 1.0 / FPS, axis=0)


def _to_segment(p, a, b):
    """Distance from points p to the segments a-b, per frame."""
    ab = b - a
    t = np.clip(((p - a) * ab).sum(-1) / ((ab * ab).sum(-1) + 1e-12), 0, 1)
    return np.linalg.norm(p - a - t[:, None] * ab, axis=-1)


def _angle(a, b):
    cos = (a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def _runs(mask):
    m = np.diff(np.concatenate([[0], np.asarray(mask, dtype=np.int8), [0]]))
    return zip(np.where(m == 1)[0], np.where(m == -1)[0])


def _floor(soles, still):
    """The floor: the height (1 cm bins) where the soles are most often while a foot is nearly still;
    of the bins holding half as many as the most, the lowest (a stool's rung or a platform is above it)."""
    cand = np.concatenate([x[m] for x, m in zip(soles, still)])
    if len(cand) < 10:
        return float(np.percentile(np.minimum.reduce(soles), 5))
    lo = np.percentile(cand, 1)
    hist, edges = np.histogram(cand, bins=np.arange(lo - 0.005, cand.max() + 0.02, 0.01))
    k = int(np.argmax(hist >= 0.5 * hist.max()))
    sel = cand[(cand >= edges[k]) & (cand < edges[k + 1])]
    return float(np.median(sel))


def _levels(sole, still, pel_z, pelvis_h):
    """Per foot, the height (m, above the floor) of what it stands on, per frame. It starts at the
    floor and moves to another level where the foot stands still LEVEL_STEP or more above or below
    its last one, carrying the body (pelvis CARRIED above it), stepped onto while the other foot
    stands on its own level (stairs, a platform; not a foot on a stool's rung, not feet stopping in
    the air hanging). Before a foot's first such stand its level is that stand's."""
    T = len(pel_z)
    cur = {"l": 0.0, "r": 0.0}
    marks = {s: ([0], [0.0]) for s in ("l", "r")}
    first = {}
    for a, b, s in sorted((a, b, s) for s in ("l", "r") for a, b in _runs(still[s]) if b - a >= 3):
        o = "r" if s == "l" else "l"
        m = (a + b) // 2  # a still foot keeps its height: its middle frame stands for the stand
        h = float(sole[s][m])
        if pel_z[m] - h < CARRIED * pelvis_h:
            continue
        if a > 0:
            k = slice(max(0, a - 3), a)
            if not (still[o][k] & (np.abs(sole[o][k] - cur[o]) < LEVEL_STEP)).any():
                continue
        if abs(h - cur[s]) >= LEVEL_STEP:
            cur[s] = h
            marks[s][0].append(a)
            marks[s][1].append(h)
        first.setdefault(s, cur[s])
    out = {}
    for s in ("l", "r"):
        starts, vals = marks[s][0], list(marks[s][1])
        vals[0] = first.get(s, 0.0)
        out[s] = np.asarray(vals)[np.searchsorted(starts, np.arange(T), side="right") - 1]
    return out


def support_velocity(P, dims, low=0.03, min_speed=0.2):
    """(T, 2): per frame the horizontal velocity of what the feet stand on, 0 on the ground and the
    belt's on a treadmill. Foot points near the floor move with their support, so over BELT_WINDOW
    the median of their velocities is its velocity. It is taken as a belt only where it is
    min_speed or more and the pelvis keeps its place (moves at under half that speed), for at least
    BELT_WINDOW: on the ground the body moves past its standing feet, on a belt the standing feet
    move past the body."""
    hs, vs = [], []
    for s in ("l", "r"):
        for name, off in ((f"{s}_ankle", dims["h_ankle"]), (f"{s}_foot", dims["h_toe"])):
            x = P[name]
            hs.append(x[:, 2] - off)
            vs.append(_vel(x, 0.1)[:, :2])
    h, v = np.stack(hs, 1), np.stack(vs, 1)  # (T, 4), (T, 4, 2)
    T = len(h)
    out = np.zeros((T, 2))
    n = int(round(BELT_WINDOW * FPS))
    m = h < np.percentile(h, 5) + low
    has = m.any(1)
    if T < n or has.sum() < 10:
        return out
    # per frame the median velocity of the low points (1 to 4 of them)
    cnt = m.sum(1)
    srt = np.sort(np.where(m[..., None], v, np.inf), axis=1)
    lo_i, hi_i = np.maximum(cnt - 1, 0) // 2, np.maximum(cnt, 1) // 2
    pick = lambda i: np.take_along_axis(srt, np.broadcast_to(i[:, None, None], (T, 1, 2)), axis=1)[:, 0]
    per = np.where(has[:, None], (pick(lo_i) + pick(np.minimum(hi_i, 3))) / 2, 0.0)
    k = np.where(has)[0]
    per = np.stack([np.interp(np.arange(T), k, per[k, i]) for i in range(2)], 1)
    fast = np.linalg.norm(per, axis=1) >= min_speed
    if not (uniform_filter1d(fast.astype(float), n, mode="nearest") >= 0.5).any():
        return out  # the low points are mostly still in every window: no moving support anywhere
    belt = median_filter(per, size=(n, 1), mode="nearest")
    pel = uniform_filter1d(_vel(P["pelvis"], 0.33)[:, :2], n, axis=0, mode="nearest")
    spd = np.linalg.norm(belt, axis=1)
    ok = (spd >= min_speed) & (np.linalg.norm(pel, axis=1) < 0.5 * spd) & \
         (uniform_filter1d(has.astype(float), n, mode="nearest") >= 0.25)
    for a, b in _runs(ok):
        if b - a >= n:
            out[a:b] = belt[a:b]
    return out


def support_shift(belt):
    """(T, 2) how far the support has moved since the first frame (the belt velocity integrated)."""
    return np.concatenate([np.zeros((1, 2)), np.cumsum(belt[:-1], axis=0) / FPS]) if len(belt) else belt


def from_joints(P, dims):
    """P: {joint: (T, 3)} world positions at 30 fps (Z up, m). Returns (dict of (T,) arrays, floor
    height, support velocity (T, 2)). On a moving support (treadmill) the signals are computed in a
    frame that moves with it: the standing foot stays put and the body moves on."""
    belt = support_velocity(P, dims)
    if belt.any():
        shift = support_shift(belt)
        P = {k: np.concatenate([v[:, :2] - shift, v[:, 2:]], axis=1) for k, v in P.items()}
    f, floor = _from_joints(P, dims)
    return f, floor, belt


def _from_joints(P, dims):
    jp = P.__getitem__
    S = dims["stature"]

    # feet: the heel side (the ankle joint lowered to the sole) and the toe; a foot stands when either is still
    raw = {}
    for s in ("l", "r"):
        ank, toe = jp(f"{s}_ankle"), jp(f"{s}_foot")
        raw[s] = (ank[:, 2] - dims["h_ankle"], toe[:, 2] - dims["h_toe"],
                  np.linalg.norm(_vel(ank, 0.1), axis=1), np.linalg.norm(_vel(toe, 0.1), axis=1),
                  (ank + toe) / 2)
    still = {s: np.minimum(raw[s][2], raw[s][3]) < STILL for s in ("l", "r")}
    sole = {s: np.minimum(raw[s][0], raw[s][1]) for s in ("l", "r")}
    floor = _floor([sole["l"], sole["r"]], [still["l"], still["r"]])
    # each heel and toe point above its own height while its foot stands still on the floor (closer than a
    # stair rise): soles estimated from joint centres are a few cm off, differently for each point, and that
    # must not read as a lifted foot
    near = {s: still[s] & (np.abs(sole[s] - floor) < 2 * LEVEL_STEP) for s in ("l", "r")}
    cal = {s: [x - (float(np.median(x[near[s]])) if near[s].sum() >= 10 else floor) for x in raw[s][:2]]
           for s in ("l", "r")}
    pel = jp("pelvis")
    level = _levels({s: np.minimum(*cal[s]) for s in ("l", "r")}, still, pel[:, 2] - floor, dims["pelvis_h"])
    ground = floor + np.minimum(level["l"], level["r"])  # the floor under the body: the lower foot's support
    v_pel = _vel(pel, 0.33)
    left = jp("l_hip") - jp("r_hip")
    fwd = np.cross(left, UP)
    fwd[:, 2] = 0
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-9
    yaw = np.unwrap(np.arctan2(fwd[:, 1], fwd[:, 0]))

    f = {
        "pelvis_x": pel[:, 0], "pelvis_y": pel[:, 1],
        "pelvis_h": (pel[:, 2] - ground) / dims["pelvis_h"],  # 1.0 = the pelvis (hip joint) height standing
        "pelvis_z": pel[:, 2] - floor,  # m above the motion's floor (continuous across levels)
        "pelvis_vz": v_pel[:, 2],
        "speed": np.linalg.norm(v_pel[:, :2], axis=1),
        "v_fwd": (v_pel[:, :2] * fwd[:, :2]).sum(1),
        "yaw": np.degrees(yaw),
        "yaw_rate": np.degrees(np.gradient(_smooth(yaw, 0.33), 1.0 / FPS)),
        # trunk bend: the pelvis -> chest (spine3) line's angle from vertical (1.3 deg standing at rest)
        "trunk": _angle(jp("spine3") - pel, np.broadcast_to(UP, pel.shape)),
        "head_rel": jp("head")[:, 2] - pel[:, 2],
    }
    feet_mid = (jp("l_ankle") + jp("r_ankle")) / 2
    # how far the pelvis is behind the middle of the ankles / thigh length (about 1 on a chair, near 0 squatting)
    f["pelvis_behind"] = -((pel - feet_mid)[:, :2] * fwd[:, :2]).sum(1) / dims["thigh"]
    for s in ("l", "r"):
        _, _, heel_v, toe_v, mid = raw[s]
        f[f"heel_h_{s}"] = cal[s][0] - level[s]  # m above its standing height on the level the foot last stood on
        f[f"toe_h_{s}"] = cal[s][1] - level[s]
        f[f"heel_v_{s}"] = heel_v
        f[f"toe_v_{s}"] = toe_v
        f[f"foot_x_{s}"], f[f"foot_y_{s}"], f[f"foot_z_{s}"] = mid[:, 0], mid[:, 1], mid[:, 2] - floor
        f[f"support_{s}"] = level[s]  # m: the level this foot stands on, above the floor
        hip, knee, ank = jp(f"{s}_hip"), jp(f"{s}_knee"), jp(f"{s}_ankle")
        f[f"knee_flex_{s}"] = 180.0 - _angle(hip - knee, ank - knee)  # 0 = straight knee
        f[f"knee_h_{s}"] = knee[:, 2] - ground
        sh, el, w = jp(f"{s}_shoulder"), jp(f"{s}_elbow"), jp(f"{s}_wrist")
        # upper-arm elevation: the upper arm (shoulder -> elbow) against the trunk's down direction (chest -> pelvis)
        f[f"arm_elev_{s}"] = _angle(el - sh, pel - jp("spine3"))
        # how far the forearm (elbow -> wrist) points to the front: 0 hanging, 1 level and straight ahead
        f[f"forearm_fwd_{s}"] = ((w - el)[:, :2] * fwd[:, :2]).sum(1) / (np.linalg.norm(w - el, axis=1) + 1e-9)
        f[f"hand_h_{s}"] = (w[:, 2] - ground) / S  # 0 = floor, 1 = stature
        f[f"hand_below_pelvis_{s}"] = (pel[:, 2] - w[:, 2]) / S
        f[f"hand_fwd_{s}"] = ((w - jp("spine3"))[:, :2] * fwd[:, :2]).sum(1)
        # wrist to the nearer front half of a thigh (mid-thigh to knee): a hand resting on the lap or a knee
        f[f"hand_lap_{s}"] = np.minimum(*[_to_segment(w, (jp(f"{o}_hip") + jp(f"{o}_knee")) / 2, jp(f"{o}_knee"))
                                          for o in ("l", "r")]) / S
        f[f"hand_v_{s}"] = np.linalg.norm(_vel(w - pel, 0.1), axis=1)  # wrist speed relative to the pelvis
        f[f"hand_wv_{s}"] = np.linalg.norm(_vel(w, 0.1), axis=1)  # wrist speed in the world
    f["hands_dist"] = np.linalg.norm(jp("l_wrist") - jp("r_wrist"), axis=1)
    return {k: np.asarray(v, dtype=np.float32) for k, v in f.items()}, floor
