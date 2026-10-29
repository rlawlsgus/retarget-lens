"""Signals -> movement tracks: what the body does, frame by frame, with no project's label names.

Within a track the segments do not overlap and cover the whole motion; tracks overlap each other
(reaching while walking). The tracks and their values (the words rule files use):

    이동      정지 / 발 옮기기 / 걷기 / 계단 오르기 / 계단 내리기 / 달리기 / 점프 / 제자리 회전 / 매달림
    회전      방향 전환 / 없음 (turns while walking too)
    자세      선 자세 / 허리 굽힘 / 쪼그림 / 앉음 / 무릎 꿇기 / 네발 자세 / 누움 / 거꾸로, and the changes
              between them ("선 자세→앉음")
    자세전환  앉기 / 일어서기 / 낮추기 / 높이기 / 없음 (the kind of each 자세 change)
    왼손, 오른손  휴지 / 뻗기 / 작업 / 되돌리기 (rest / moving out / held out / moving back)
    손        the two hands together: 뻗기 > 되돌리기 > 작업 > 휴지
    양손      들기 / 없음 (holding something with both hands)
    걸음      걸음 중 / 없음 (from a foot's lift to the last strike of steps that follow each other)

Boundaries sit on physical events: a step on the frames a foot leaves and touches the floor, a
jump, posture change or reach where the speed has dropped below a fraction (onset_frac) of its peak.
The thresholds (DEFAULTS) come from definitions of the movements, the biomechanics and ergonomics
literature and body proportions, not from fitting labelled data; a rule file may override them.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.ndimage import uniform_filter1d

FPS = 30.0
POSTURE_RANK = {"선 자세": 0, "허리 굽힘": 1, "쪼그림": 2, "앉음": 2, "무릎 꿇기": 3, "네발 자세": 4, "누움": 5,
                "거꾸로": 6}
HAND_ORDER = ["뻗기", "되돌리기", "작업", "휴지"]  # the 손 track: the first of these either hand is doing
VALUES = {  # the values each track can have (rule files are checked against these)
    "이동": ["정지", "발 옮기기", "걷기", "계단 오르기", "계단 내리기", "달리기", "점프", "제자리 회전", "매달림"],
    "회전": ["방향 전환", "없음"],
    "자세": list(POSTURE_RANK),  # and "A→B"
    "자세전환": ["앉기", "일어서기", "낮추기", "높이기", "없음"],
    "왼손": HAND_ORDER, "오른손": HAND_ORDER, "손": HAND_ORDER,
    "양손": ["들기", "없음"],
    "걸음": ["걸음 중", "없음"],
}

DEFAULTS = {  # lengths m, times s, angles deg
    "contact": {
        "still_speed": 0.3,  # heel or toe slower than this = the foot stands (a swinging foot passes 1 m/s walking)
        "min_frames": 2,  # shorter stands / lifts are noise
        "ground_height": 0.02,  # a foot point this close to the floor touches it (flight while running)
        "air_height": 0.05,  # at a jump's top both feet above this count as in the air even when they slow down
        "apex_gap": 0.13,  # ... for gaps up to this long
    },
    "step": {
        "min_swing": 0.1,  # time a foot is in the air: the swing phase of human steps
        "max_swing": 1.2,
        "min_disp": 0.1,  # moved at least this far (less than half a foot length is shuffling)
        "min_rise": 0.1,  # or this high (stair step 0.15-0.18 m)
    },
    "gait": {
        "min_steps": 3,  # walking = at least 3 alternating steps
        "max_pause": 0.5,  # the next step lifts within this after the last strike: the same walk
        "min_speed": 0.2,  # mean horizontal pelvis speed of a walk; slower = stepping in place (발 옮기기)
        "run_flight": 0.067,  # both feet off for at least this between steps: a running step (2 frames @ 30 fps)
        "stair_rise": 0.1,  # a walking step that rises or falls this much is a stair step
    },
    "jump": {
        "min_flight": 0.1,  # shortest time in the air
        "leap_flight": 0.25,  # off one foot onto the other: a jump only when longer than this (running flight is shorter)
        "max_flight": 1.0,  # people stay under 1 s in the air jumping; longer = hanging
        "hang_height": 0.15,  # hanging: both feet this high above the floor, both arms over the head
        "onset_frac": 0.05,  # boundaries: vertical pelvis speed below this fraction of its peak (5% movement onset)
        "quiet": 0.1,  # ... for at least this long
        "window": 1.0,  # searched before take-off and after landing
    },
    "turn": {  # El-Gohary et al. 2014 (yaw rate of a pelvis sensor)
        "rate_peak": 15,  # peak yaw rate in the turn (deg/s)
        "rate_edge": 5,  # start / end: yaw rate below this (deg/s)
        "merge_gap": 0.05,  # shorter breaks between turns the same way are joined
        "min_dur": 0.5,
        "max_dur": 10.0,
        "min_angle": 45,  # turned at least this much
    },
    "posture": {
        "bend_trunk": 20,  # trunk 20 deg or more from vertical = bent (the first bend band of ergonomic scores)
        "lie_trunk": 60,  # 60 deg or more = closer to lying (their deepest band)
        "squat_knee": 60,  # both knees bent 60 deg or more
        "low_pelvis": 0.75,  # pelvis height ratio of a 60 deg knee bend on a two-segment leg: (1 + cos 60)/2
        "floor_pelvis": 0.54,  # knee height / hip height standing (0.285H / 0.530H): lower = floor-level posture
        "sit_behind": 0.5,  # pelvis behind the ankles by half a thigh or more = sitting on something
        "floor_contact": 0.15,  # a knee or wrist joint centre lower than this touches the floor
        "inverted": 0.1,  # head this much below the pelvis = upside down
        "min_state": 0.3,  # shorter postures and holds join their neighbours
        "min_rate": 0.1,  # posture change rate (1/s) below this = holding; 10% of a sit / stand peak (about 1/s)
        "rate_smooth": 0.5,  # change rate averaged over this (one walking step)
    },
    "hand": {
        "arm_raise": 45,  # upper arm 45 deg or more from the trunk = arm held out (the 45-90 deg band of arm scores)
        "floor_zone": 0.285,  # wrist height / stature below knee height = floor level
        "high_zone": 0.818,  # shoulder height or higher = high
        "below_pelvis": 0.05,  # a floor-level hand is at least 5% of stature below the pelvis (not a hand resting while seated on the floor)
        "min_ext": 0.3,  # shortest time held out (not the arm swing of running)
        "min_gap": 0.2,
        "peak_min": 0.3,  # slower hand movements get no reach / return boundaries (m/s, relative to the pelvis)
        "onset_frac": 0.05,  # hand speed below 5% of its peak = start / end of the movement (reaching kinematics)
        "quiet": 0.1,
        "window": 1.0,
    },
    "carry": {
        "front": 0.05,  # both wrists this far in front of the chest
        "min_h": 0.285,  # between knee
        "max_h": 0.818,  # and shoulder height (/ stature)
        "min_width": 0.15,  # hands at least an object's width apart (not hands clasped)
        "max_std": 0.02,  # std of the hands' distance over std_window: nearly constant holding a rigid object
        "std_window": 0.5,
        "min_dur": 0.5,
    },
}


def params(overrides: dict | None = None) -> dict:
    """DEFAULTS with a rule file's overrides ({group: {name: value}}); unknown names and values that
    are not finite numbers of at least 0 are an error."""
    out = copy.deepcopy(DEFAULTS)
    if overrides is None:
        return out
    if not isinstance(overrides, dict):
        raise ValueError("params는 {묶음: {이름: 값}} 표여야 합니다 (예: {gait: {max_pause: 0.5}})")
    for group, vals in overrides.items():
        if group not in out:
            raise ValueError(f"params: 모르는 묶음 '{group}' (있는 것: {', '.join(out)})")
        if not isinstance(vals, dict):
            raise ValueError(f"params.{group}: {{이름: 값}} 표여야 합니다")
        for k, v in vals.items():
            if k not in out[group]:
                raise ValueError(f"params.{group}: 모르는 값 '{k}' (있는 것: {', '.join(out[group])})")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError(f"params.{group}.{k}: 0 이상의 숫자여야 합니다 (받은 값: {v!r})")
            out[group][k] = v
    return out


def runs(mask):
    """[(s, e)) of the True runs."""
    m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]])
    d = np.diff(m.astype(np.int8))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def drop_short(mask, n):
    out = np.asarray(mask, dtype=bool).copy()
    for s, e in runs(out):
        if e - s < n:
            out[s:e] = False
    return out


def fill_gaps(mask, n, allow=None):
    """Fill False gaps shorter than n frames between Trues; with allow, only gaps that are allow throughout."""
    out = np.asarray(mask, dtype=bool).copy()
    T = len(out)
    for s, e in runs(~out):
        if s == 0 or e == T or e - s >= n:
            continue
        if allow is None or allow[s:e].all():
            out[s:e] = True
    return out


def sec(x):
    return max(1, int(round(x * FPS)))


def labels_to_segments(lab):
    """[(label, start, end exclusive)] of the runs of equal labels."""
    lab = np.asarray(lab, dtype=object)
    if len(lab) == 0:
        return []
    b = np.concatenate([[0], np.where(lab[1:] != lab[:-1])[0] + 1, [len(lab)]])
    return [(lab[b[i]], int(b[i]), int(b[i + 1])) for i in range(len(b) - 1)]


def smooth_labels(lab, min_sec, keep=()):
    """Label runs shorter than min_sec take their longer neighbour's label (labels in keep stay)."""
    lab = np.asarray(lab, dtype=object).copy()
    n = int(round(min_sec * FPS))
    for _ in range(3):
        b = np.concatenate([[0], np.where(lab[1:] != lab[:-1])[0] + 1, [len(lab)]])
        segs = [(b[i], b[i + 1]) for i in range(len(b) - 1)]
        changed = False
        for i, (s, e) in enumerate(segs):
            if e - s >= n or lab[s] in keep:
                continue
            left = segs[i - 1] if i > 0 else None
            right = segs[i + 1] if i + 1 < len(segs) else None
            cand = [x for x in (left, right) if x is not None]
            if not cand:
                continue
            best = max(cand, key=lambda x: x[1] - x[0])
            lab[s:e] = lab[best[0]]
            changed = True
        if not changed:
            break
    return lab


def _quiet_before(a, t, lo, thr, q):
    """Back from t to lo, the first place where a stays below thr for q frames: the end of that quiet
    stretch (where the movement starts)."""
    cnt = 0
    for i in range(t, lo - 1, -1):
        cnt = cnt + 1 if a[i] < thr else 0
        if cnt >= q:
            return i + q
    return lo


def _quiet_after(a, t, hi, thr, q):
    """Forward from t to hi, the first place where a stays below thr for q frames (where the movement ends)."""
    cnt = 0
    for i in range(t, hi):
        cnt = cnt + 1 if a[i] < thr else 0
        if cnt >= q:
            return i - q + 1
    return hi


# ---------------------------------------------------------------- stance, steps, flight
def stance(f, c):
    """Per foot: standing when the heel or the toe is slower than still_speed. Height is not looked at (stairs, platforms)."""
    n = c["min_frames"]
    out = {}
    for s in ("l", "r"):
        st = (f[f"heel_v_{s}"] < c["still_speed"]) | (f[f"toe_v_{s}"] < c["still_speed"])
        st = fill_gaps(st, n)  # a lift of a frame or two is noise
        st = ~fill_gaps(~st, n)  # and so is a stand that short
        out[s] = st
    return out


def find_steps(f, st, c):
    """Steps: a foot leaves (lift) and stands again (strike) after a human swing time, moved."""
    T = len(st["l"])
    out = []
    for s in ("l", "r"):
        for a, b in runs(~st[s]):
            d = (b - a) / FPS
            if a == 0 or b == T or d < c["min_swing"] or d > c["max_swing"]:
                continue
            dx = f[f"foot_x_{s}"][b] - f[f"foot_x_{s}"][a - 1]
            dy = f[f"foot_y_{s}"][b] - f[f"foot_y_{s}"][a - 1]
            dz = f[f"foot_z_{s}"][b] - f[f"foot_z_{s}"][a - 1]
            disp = float(np.hypot(dx, dy))
            if disp < c["min_disp"] and abs(dz) < c["min_rise"]:
                continue
            out.append({"foot": s, "lift": int(a), "strike": int(b), "disp": disp, "rise": float(dz)})
    return sorted(out, key=lambda x: x["lift"])


def airborne(f, st, c):
    """Frames with neither foot standing. A gap where the feet slow down at a jump's top is filled
    only while both feet are more than air_height above the floor."""
    air = ~st["l"] & ~st["r"]
    low = lambda s: np.minimum(f[f"heel_h_{s}"], f[f"toe_h_{s}"])
    high = (low("l") > c["air_height"]) & (low("r") > c["air_height"])
    return fill_gaps(air, sec(c["apex_gap"]), allow=high)


def walking(steps, T, max_pause):
    """걸음 중: from the first lift to the last strike of steps whose next one lifts within
    max_pause after the previous strike (any steps: walking, running, stepping in place)."""
    m = np.zeros(T, dtype=bool)
    cur = None
    for s in sorted(steps, key=lambda x: x["lift"]):
        if cur and s["lift"] - cur[1] <= sec(max_pause):
            cur[1] = max(cur[1], s["strike"])
        else:
            if cur:
                m[cur[0]:cur[1]] = True
            cur = [s["lift"], s["strike"]]
    if cur:
        m[cur[0]:cur[1]] = True
    return m


# ---------------------------------------------------------------- 이동
def locomotion(f, st, steps, air, cfg):
    T = len(f["speed"])
    g, jc, tc = cfg["gait"], cfg["jump"], cfg["turn"]
    lab = np.full(T, "정지", dtype=object)
    attrs = []

    # steps belong to one walk when the next lifts within max_pause after the last strike
    bouts, cur = [], []
    for s in steps:
        if cur and s["lift"] - max(x["strike"] for x in cur) > sec(g["max_pause"]):
            bouts.append(cur)
            cur = []
        cur.append(s)
    if cur:
        bouts.append(cur)

    gait_bouts = []
    for b in bouts:
        a, e = b[0]["lift"], max(x["strike"] for x in b)
        feet = {x["foot"] for x in b}
        prog = float(f["speed"][a:e].mean()) if e > a else 0.0
        if len(b) >= g["min_steps"] and len(feet) == 2 and prog >= g["min_speed"]:
            gait_bouts.append(b)
        else:
            lab[a:e] = "발 옮기기"
            attrs.append(("이동", "발 옮기기", a, e, {"steps": len(b)}))

    # a step with run_flight or more in the air is a running step. In the air = neither foot standing and
    # all four heel / toe points above ground_height (not the moment both feet move in a fast walk's double support)
    nfl = sec(g["run_flight"])
    gh = cfg["contact"]["ground_height"]
    off_ground = np.ones(T, dtype=bool)
    for s_ in ("l", "r"):
        off_ground &= (f[f"heel_h_{s_}"] > gh) & (f[f"toe_h_{s_}"] > gh)
    flight = air & off_ground
    for b in gait_bouts:
        kinds = []
        for x in b:
            lo = max(0, x["lift"] - sec(0.1))
            fl = max((e - s for s, e in runs(flight[lo:x["strike"]])), default=0)
            if fl >= nfl:
                kinds.append("달리기")
            else:
                # walking steps that rise or fall a stair step are stairs
                kinds.append("계단 오르기" if x["rise"] >= g["stair_rise"] else
                             ("계단 내리기" if x["rise"] <= -g["stair_rise"] else "걷기"))
        # a single step unlike both neighbours follows them
        for i in range(1, len(kinds) - 1):
            if kinds[i - 1] == kinds[i + 1] != kinds[i]:
                kinds[i] = kinds[i - 1]
        i = 0
        while i < len(b):
            j = i
            while j + 1 < len(b) and kinds[j + 1] == kinds[i]:
                j += 1
            s = b[i]["lift"] if i == 0 else (b[i - 1]["strike"] + b[i]["lift"]) // 2
            e = max(x["strike"] for x in b[:j + 1]) if j == len(b) - 1 else (b[j]["strike"] + b[j + 1]["lift"]) // 2
            if e > s:
                lab[s:e] = kinds[i]
                part = b[i:j + 1]
                v = f["v_fwd"][s:e] / (f["speed"][s:e] + 1e-6)
                cos = float(np.median(v))
                attrs.append(("이동", kinds[i], s, e, {
                    "steps": len(part),
                    "cadence_spm": round(60.0 * len(part) / ((e - s) / FPS), 1),
                    "speed": round(float(f["speed"][s:e].mean()), 2),
                    "dir": "fwd" if cos >= 0.707 else ("back" if cos <= -0.707 else "side"),
                    "rise_m": round(sum(x["rise"] for x in part), 2),
                }))
            i = j + 1

    # jumps: flights taking off or landing on both feet, off and onto the same foot (hop), or long ones.
    # A short flight from one foot to the other is running
    av = np.abs(f["pelvis_vz"])
    W, q = sec(jc["window"]), sec(jc["quiet"])
    hang = np.zeros(T, dtype=bool)
    for a, e in runs(air):
        d = (e - a) / FPS
        if d < jc["min_flight"]:
            continue
        if d > jc["max_flight"]:
            hang[a:e] = True
            continue
        k = sec(0.1)
        take = {s for s in ("l", "r") if st[s][max(0, a - k):a].any()}
        land = {s for s in ("l", "r") if st[s][e:min(T, e + k)].any()}
        if not (len(take) == 2 or len(land) == 2 or (take == land and len(take) == 1) or d >= jc["leap_flight"]):
            continue
        lo, hi = max(0, a - W), min(T, e + W)
        thr_pre = jc["onset_frac"] * av[lo:a + 1].max()
        thr_post = jc["onset_frac"] * av[e - 1:hi].max()
        s0 = _quiet_before(av, a, lo, thr_pre, q)
        e0 = _quiet_after(av, e, hi, thr_post, q)
        lab[s0:e0] = "점프"
        kind = "hop" if take == land and len(take) == 1 else ("two_foot" if len(take) == 2 else "leap")
        attrs.append(("이동", "점프", s0, e0, {"flight_s": round(d, 2), "kind": kind, "takeoff": int(a),
                                             "landing": int(e)}))

    # hanging: people do not stay a second in the air jumping; both feet up and both arms over the head
    low = lambda s: np.minimum(f[f"heel_h_{s}"], f[f"toe_h_{s}"])
    floating = (low("l") > jc["hang_height"]) & (low("r") > jc["hang_height"]) & \
               (f["arm_elev_l"] >= 90) & (f["arm_elev_r"] >= 90)
    hang |= floating
    for a, e in runs(hang):
        if (e - a) / FPS >= jc["max_flight"]:
            lab[a:e] = "매달림"

    # turns (El-Gohary et al. 2014): runs of yaw rate at least rate_edge one way with a peak of at least
    # rate_peak, joined over breaks shorter than merge_gap, min_dur..max_dur long, turning at least min_angle
    turn = np.full(T, "없음", dtype=object)
    yaw, rate = f["yaw"], f["yaw_rate"]
    for sgn in (1, -1):
        act = fill_gaps(sgn * rate >= tc["rate_edge"], max(1, int(tc["merge_gap"] * FPS)))
        for a, e in runs(act):
            ang = float(yaw[e - 1] - yaw[a])
            d = (e - a) / FPS
            if abs(ang) < tc["min_angle"] or (sgn * rate[a:e]).max() < tc["rate_peak"] or \
                    not tc["min_dur"] <= d <= tc["max_dur"]:
                continue
            turn[a:e] = "방향 전환"
            inplace = float(f["speed"][a:e].mean()) < g["min_speed"]
            attrs.append(("회전", "방향 전환", a, e, {"angle": round(ang, 1), "in_place": inplace}))
            if inplace:
                m = np.isin(lab[a:e], ["정지", "발 옮기기"])
                lab[a:e][m] = "제자리 회전"
    return lab, turn, attrs


# ---------------------------------------------------------------- 자세
def posture_state(f, dims, pc):
    ph, trunk = f["pelvis_h"], f["trunk"]
    kf_min = np.minimum(f["knee_flex_l"], f["knee_flex_r"])
    kh = np.minimum(f["knee_h_l"], f["knee_h_r"])
    hands_low = np.maximum(f["hand_h_l"], f["hand_h_r"]) * dims["stature"] < pc["floor_contact"]
    floor_level = ph < pc["floor_pelvis"]
    inverted = f["head_rel"] < -pc["inverted"]
    crawl = (trunk >= pc["lie_trunk"]) & hands_low & (kh < pc["floor_contact"])
    lie = floor_level & (trunk >= pc["lie_trunk"]) & ~crawl
    kneel = (kh < pc["floor_contact"]) & ~crawl & ~lie
    sit = ((ph < pc["low_pelvis"]) & (f["pelvis_behind"] >= pc["sit_behind"])) | \
          (floor_level & (trunk < pc["lie_trunk"]))
    squat = (ph < pc["low_pelvis"]) & (kf_min >= pc["squat_knee"])
    bend = trunk >= pc["bend_trunk"]
    st = np.select([inverted, crawl, lie, kneel, sit, squat, bend],
                   ["거꾸로", "네발 자세", "누움", "무릎 꿇기", "앉음", "쪼그림", "허리 굽힘"], "선 자세").astype(object)
    return smooth_labels(st, pc["min_state"])


def posture(f, dims, pc):
    """Holding = the posture change rate below min_rate for min_state or longer; the rest is movement.
    A movement is named by the holds before and after (A→B). When they are the same (bend and
    straighten) it is split at the deepest posture X into A→X and X→A; when X is the same too
    (the pelvis bobbing while running) it is no change."""
    st = posture_state(f, dims, pc)
    T = len(st)
    lab = st.copy()
    attrs = []
    # change rate: of the pelvis height ratio (1/s) or of the trunk angle (90 deg as 1), whichever is larger,
    # averaged over rate_smooth (one step) so the pelvis going up and down with every step is gone
    n = sec(pc["rate_smooth"])
    pv = np.maximum(np.abs(np.gradient(uniform_filter1d(f["pelvis_h"], n), 1 / FPS)),
                    np.abs(np.gradient(uniform_filter1d(f["trunk"], n), 1 / FPS)) / 90.0)
    hold = drop_short(pv < pc["min_rate"], sec(pc["min_state"]))
    rank = lambda x: POSTURE_RANK.get(x, 0)
    for a, b in runs(~hold):
        A = st[a - 1] if a > 0 else st[a]
        B = st[b] if b < T else st[b - 1]
        if A != B:
            parts = [(A, B, a, b)]
        else:
            seg = st[a:b]
            X = max(seg, key=lambda x: abs(rank(x) - rank(A)))
            if X == A:
                continue
            idx = np.where(seg == X)[0]
            k = a + int((idx[0] + idx[-1]) // 2)
            parts = [(A, X, a, k), (X, A, k, b)]
        for A_, B_, x, y in parts:
            if y - x < 2:
                continue
            name = f"{A_}→{B_}"
            lab[x:y] = name
            attrs.append(("자세", name, x, y, {"from": A_, "to": B_, "kind": transition_kind(A_, B_)}))
    return lab, attrs


def transition_kind(A, B):
    up = {"선 자세", "허리 굽힘"}
    if B == "앉음" and A in up:
        return "앉기"
    if A in ("앉음", "누움", "네발 자세", "무릎 꿇기", "쪼그림", "거꾸로") and B in up:
        return "일어서기"
    return "낮추기" if POSTURE_RANK.get(B, 0) > POSTURE_RANK.get(A, 0) else "높이기"


# ---------------------------------------------------------------- 손
def hand(f, dims, s, hc, track):
    """One hand. Held out = the upper arm arm_raise deg or more from the trunk, or the hand at floor
    level below the pelvis. The movement into held out = 뻗기, while held out = 작업, the movement out = 되돌리기."""
    T = len(f["speed"])
    v = f[f"hand_v_{s}"]
    ext = (f[f"arm_elev_{s}"] >= hc["arm_raise"]) | \
          ((f[f"hand_h_{s}"] < hc["floor_zone"]) & (f[f"hand_below_pelvis_{s}"] > hc["below_pelvis"]))
    ext = drop_short(fill_gaps(ext, sec(hc["min_gap"])), sec(hc["min_ext"]))
    lab = np.full(T, "휴지", dtype=object)
    attrs = []
    W, q = sec(hc["window"]), sec(hc["quiet"])
    prev_end = 0
    rr = runs(ext)
    for i, (a, b) in enumerate(rr):
        nxt = rr[i + 1][0] if i + 1 < len(rr) else T
        # 뻗기: from the hand speed peak around entering, back to where the hand was still
        lo, hi = max(prev_end, a - W), min(b, a + W // 2)
        p1 = lo + int(np.argmax(v[lo:hi])) if hi > lo else a
        r_on, r_off = a, a
        if v[p1] >= hc["peak_min"]:
            thr = hc["onset_frac"] * v[p1]
            r_on = _quiet_before(v, p1, lo, thr, q)
            r_off = max(min(_quiet_after(v, p1, b, thr, q), _local_min_after(v, p1, b, 0.5 * v[p1])), min(a + 1, b))
        # 되돌리기: the peak around leaving
        lo2, hi2 = max(r_off, b - W // 2), min(nxt, b + W)
        p2 = lo2 + int(np.argmax(v[lo2:hi2])) if hi2 > lo2 else b
        t_on, t_off = b, b
        if b < T and v[p2] >= hc["peak_min"]:
            thr = hc["onset_frac"] * v[p2]
            t_on = min(max(_quiet_before(v, p2, r_off, thr, q), _local_min_before(v, p2, r_off, 0.5 * v[p2])),
                       max(b - 1, r_off))
            t_off = _quiet_after(v, p2, hi2, thr, q)
        if t_on <= r_off:  # straight back without holding: split at the slowest point between the two peaks
            m = p1 + int(np.argmin(v[p1:max(p2, p1 + 1)]))
            r_off = t_on = m
        zone_h = float(np.median(f[f"hand_h_{s}"][r_off:t_on])) if t_on > r_off else float(f[f"hand_h_{s}"][r_off])
        zone = "바닥" if zone_h < hc["floor_zone"] else ("높음" if zone_h >= hc["high_zone"] else "중간")
        for name, x, y in (("뻗기", r_on, r_off), ("작업", r_off, t_on), ("되돌리기", t_on, t_off)):
            if y > x:
                lab[x:y] = name
                attrs.append((track, name, x, y, {"zone": zone}))
        prev_end = max(t_off, b)
    return lab, attrs


def _local_min_after(v, p, hi, below):
    for i in range(p + 1, hi - 1):
        if v[i] <= v[i - 1] and v[i] <= v[i + 1] and v[i] < below:
            return i
    return hi


def _local_min_before(v, p, lo, below):
    for i in range(p - 1, lo, -1):
        if v[i] <= v[i - 1] and v[i] <= v[i + 1] and v[i] < below:
            return i
    return lo


def carry(f, dims, cc):
    """Both hands holding: in front of the body, between knee and shoulder height, at least an
    object's width apart and that distance steady (a rigid object held with both hands)."""
    d = f["hands_dist"]
    n = sec(cc["std_window"])
    m1 = uniform_filter1d(d, n, mode="nearest")
    sd = np.sqrt(np.maximum(uniform_filter1d(d * d, n, mode="nearest") - m1 * m1, 0))
    h_ok = lambda s: (f[f"hand_h_{s}"] >= cc["min_h"]) & (f[f"hand_h_{s}"] < cc["max_h"])
    m = (f["hand_fwd_l"] > cc["front"]) & (f["hand_fwd_r"] > cc["front"]) & h_ok("l") & h_ok("r") & \
        (d >= cc["min_width"]) & (sd < cc["max_std"])
    m = drop_short(fill_gaps(m, sec(0.2)), sec(cc["min_dur"]))
    return np.where(m, "들기", "없음").astype(object)


# ---------------------------------------------------------------- all tracks
def tracks(f, dims, cfg):
    """{track: (T,) labels} for every track in VALUES, and the steps ({foot, lift, strike, ...})."""
    st = stance(f, cfg["contact"])
    steps = find_steps(f, st, cfg["step"])
    air = airborne(f, st, cfg["contact"])
    loco, turn, _ = locomotion(f, st, steps, air, cfg)
    post, pa = posture(f, dims, cfg["posture"])
    hl, _ = hand(f, dims, "l", cfg["hand"], "왼손")
    hr, _ = hand(f, dims, "r", cfg["hand"], "오른손")
    T = len(loco)
    kind = np.full(T, "없음", dtype=object)
    for _, name, s, e, d in pa:
        kind[s:e][post[s:e] == name] = d["kind"]
    rank = {x: i for i, x in enumerate(HAND_ORDER)}
    both = np.array([a if rank[a] <= rank[b] else b for a, b in zip(hl, hr)], dtype=object)
    out = {"이동": loco, "회전": turn, "자세": post, "자세전환": kind, "왼손": hl, "오른손": hr, "손": both,
           "양손": carry(f, dims, cfg["carry"]),
           "걸음": np.where(walking(steps, T, cfg["gait"]["max_pause"]), "걸음 중", "없음").astype(object)}
    return out, steps
