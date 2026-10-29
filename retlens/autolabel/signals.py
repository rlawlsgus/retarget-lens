"""Per-frame movement signals at 30 fps, from body joint positions.

Heights are above a floor found per motion, lengths are divided by the body's own sizes (stature,
arm, thigh), so the thresholds in segment.DEFAULTS hold for any body. Reading files is kept apart
(retlens.autolabel.body), so every check goes through the same function.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d

FPS = 30.0
UP = np.array([0.0, 0.0, 1.0])
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


def _angle(a, b):
    cos = (a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def _floor(sole_l, sole_r, spd_l, spd_r):
    """The floor: the most common sole height (1 cm bins) over the frames where a foot is nearly still."""
    cand = np.concatenate([sole_l[spd_l < 0.2], sole_r[spd_r < 0.2]])
    if len(cand) < 10:
        return float(np.percentile(np.minimum(sole_l, sole_r), 5))
    lo = np.percentile(cand, 1)
    hist, edges = np.histogram(cand, bins=np.arange(lo - 0.005, cand.max() + 0.02, 0.01))
    k = int(np.argmax(hist))
    sel = cand[(cand >= edges[k]) & (cand < edges[k + 1])]
    return float(np.median(sel))


def support_velocity(P, dims, low=0.03, min_speed=0.2):
    """Horizontal speed of what the feet stand on: the median horizontal speed of the foot points
    near the floor. 0 on the ground, the belt speed on a treadmill (foot points spend most of
    the time on the support, so their median is its speed)."""
    vs, hs = [], []
    for s in ("l", "r"):
        for name, off in ((f"{s}_ankle", dims["h_ankle"]), (f"{s}_foot", dims["h_toe"])):
            x = P[name]
            hs.append(x[:, 2] - off)
            vs.append(_vel(x, 0.1)[:, :2])
    h = np.concatenate(hs)
    v = np.concatenate(vs)
    m = h < np.percentile(h, 5) + low
    if m.sum() < 10:
        return np.zeros(2)
    belt = np.median(v[m], axis=0)
    return belt if np.linalg.norm(belt) >= min_speed else np.zeros(2)


def from_joints(P, dims):
    """P: {joint: (T, 3)} world positions at 30 fps (Z up, m). Returns (dict of (T,) arrays, floor
    height, support velocity). On a moving support (treadmill) the signals are computed in a frame
    that moves with it: the standing foot stays put and the body moves on."""
    belt = support_velocity(P, dims)
    if belt.any():
        t = np.arange(len(P["pelvis"])) / FPS
        P = {k: np.concatenate([v[:, :2] - belt[None, :] * t[:, None], v[:, 2:]], axis=1) for k, v in P.items()}
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
    floor = _floor(np.minimum(raw["l"][0], raw["l"][1]), np.minimum(raw["r"][0], raw["r"][1]),
                   np.minimum(raw["l"][2], raw["l"][3]), np.minimum(raw["r"][2], raw["r"][3]))

    pel = jp("pelvis")
    v_pel = _vel(pel, 0.33)
    left = jp("l_hip") - jp("r_hip")
    fwd = np.cross(left, UP)
    fwd[:, 2] = 0
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-9
    yaw = np.unwrap(np.arctan2(fwd[:, 1], fwd[:, 0]))

    f = {
        "pelvis_x": pel[:, 0], "pelvis_y": pel[:, 1],
        "pelvis_h": (pel[:, 2] - floor) / dims["pelvis_h"],  # 1.0 = the pelvis (hip joint) height standing
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
        heel_h, toe_h, heel_v, toe_v, mid = raw[s]
        f[f"heel_h_{s}"] = heel_h - floor
        f[f"toe_h_{s}"] = toe_h - floor
        f[f"heel_v_{s}"] = heel_v
        f[f"toe_v_{s}"] = toe_v
        f[f"foot_x_{s}"], f[f"foot_y_{s}"], f[f"foot_z_{s}"] = mid[:, 0], mid[:, 1], mid[:, 2] - floor
        hip, knee, ank = jp(f"{s}_hip"), jp(f"{s}_knee"), jp(f"{s}_ankle")
        f[f"knee_flex_{s}"] = 180.0 - _angle(hip - knee, ank - knee)  # 0 = straight knee
        f[f"knee_h_{s}"] = knee[:, 2] - floor
        sh, el, w = jp(f"{s}_shoulder"), jp(f"{s}_elbow"), jp(f"{s}_wrist")
        # upper-arm elevation: the upper arm (shoulder -> elbow) against the trunk's down direction (chest -> pelvis)
        f[f"arm_elev_{s}"] = _angle(el - sh, pel - jp("spine3"))
        f[f"hand_h_{s}"] = (w[:, 2] - floor) / S  # 0 = floor, 1 = stature
        f[f"hand_below_pelvis_{s}"] = (pel[:, 2] - w[:, 2]) / S
        f[f"hand_fwd_{s}"] = ((w - jp("spine3"))[:, :2] * fwd[:, :2]).sum(1)
        f[f"hand_v_{s}"] = np.linalg.norm(_vel(w - pel, 0.1), axis=1)  # wrist speed relative to the pelvis
        f[f"hand_wv_{s}"] = np.linalg.norm(_vel(w, 0.1), axis=1)  # wrist speed in the world
    f["hands_dist"] = np.linalg.norm(jp("l_wrist") - jp("r_wrist"), axis=1)
    return {k: np.asarray(v, dtype=np.float32) for k, v in f.items()}, floor
