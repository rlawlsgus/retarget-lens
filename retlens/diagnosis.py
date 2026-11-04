"""First cause of a fall in a physics replay (tools/isaac_replay.py --physics, and the MuJoCo
replays of retlens/policy_replay.py: harness, no controller, GMT).

A fall alone says little about the motion data: an open-loop replay has no balance
controller, so what matters is what went wrong first. For each fall the frames just
before it (``window``) are scanned for these conditions, each a per-frame mask computed
from what the replay recorded (FallSignals; diagnose_falls):

  toe_catch          a foot touches the floor while the clip has it swinging
  foot_slip          a foot on the floor slides while the clip has it standing
  self_collision     left/right feet or knees closer than a threshold (a distance proxy
                     in both engines: Isaac runs with self-collision off, and MuJoCo uses
                     the same proxy so the two read alike)
  torque_saturation  a joint drive needs more than its effort limit (x ratio)
  support_exit       CoM projection (or, without the harness, the ZMP) outside the
                     feet's support polygon
  harness_spike      the pelvis harness pulls with a large share of body weight

A condition starts ("onset") at the first frame of the window where it holds for
``min_frames`` frames in a row. One that already holds when the window opens is
"chronic"; its ``active_since_s`` is found by following that run back (gaps of up to
two frames, never past the previous reset).

Primary cause:
  1. the earliest onset among the conditions that start inside the window (a new
     event triggers the fall; a chronic one such as an ankle that is always near its
     limit, or a CoM the harness has been holding outside the feet, did not);
  2. if only chronic conditions are there, the one active the longest;
  3. harness_spike only when nothing else is found: the harness pulls hard because the
     robot has already left the clip's pose, so it is a consequence.
Ties follow CAUSES order.

MuJoCo (retlens/policy_replay.py) records the same signals once per 50 Hz control tick,
before the fall check (the fall tick holds the fallen state, as Isaac's frame does):
sole points of GMT's 4 contact spheres per foot (a narrower support polygon than the
Isaac feet's box corners), the model's exact CoM, GMT's torque-limit table and the
demand of the last 1 ms step. Its causes are comparable in kind, not one to one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

import numpy as np

CAUSES = ("toe_catch", "foot_slip", "self_collision", "torque_saturation", "support_exit", "harness_spike")
SYMPTOMS = ("harness_spike",)
CAUSE_KO = {"toe_catch": "발끝 걸림", "foot_slip": "발 미끄러짐", "self_collision": "자기충돌 근접",
            "torque_saturation": "토크 포화", "support_exit": "지지면 이탈", "harness_spike": "보조 힘 급증",
            "undetermined": "미상"}  # report / viewer labels
FOOT_KO = {"left": "왼발", "right": "오른발"}  # a foot link's name (left_ankle_roll_link) in the viewer's words


def onset(mask: np.ndarray, start: int, stop: int, min_frames: int = 2) -> int | None:
    """First frame in [start, stop] where ``mask`` holds for ``min_frames`` frames in a row
    (a run cut short by ``stop`` counts)."""
    run = 0
    for i in range(max(start, 0), min(stop, len(mask) - 1) + 1):
        run = run + 1 if mask[i] else 0
        if run >= min_frames or (run and i == stop):
            return i - run + 1
    return None


def active_since(mask: np.ndarray, frame: int, earliest: int = 0, max_gap: int = 2) -> int:
    """Start of the run of ``mask`` that holds at ``frame``, followed back over gaps of up to
    ``max_gap`` frames, never before ``earliest``."""
    i = frame
    gap = 0
    j = frame - 1
    while j >= max(earliest, 0):
        if mask[j]:
            i, gap = j, 0
        else:
            gap += 1
            if gap > max_gap:
                break
        j -= 1
    return i


def diagnose_fall(conditions: dict[str, np.ndarray], evidence: dict[str, Callable[[int, int, int], dict]],
                  fall: int, start: int, fps: float, min_frames: int = 2, earliest: int = 0,
                  chronic_needs_run: bool = False) -> dict:
    """conditions: cause -> (T,) bool mask; evidence: cause -> f(onset, start, fall) -> dict of
    numbers (values at the onset, peaks in the window). fall / start / earliest: frame indices
    (earliest = where the robot was last (re)started)."""
    cands = []
    for name, mask in conditions.items():
        mask = np.asarray(mask, bool)
        i = onset(mask, start, fall, min_frames)
        if i is None:
            continue
        # already on when the window opens; chronic_needs_run (MuJoCo): only when its qualifying run starts there, so a
        # one-frame blip at the start does not hide a run that begins later (Isaac keeps the first frame's say)
        chronic = bool(mask[start]) and (not chronic_needs_run or i == start)
        since = active_since(mask, start, earliest) if chronic else i
        cands.append({
            "cause": name,
            "onset_s": round(i / fps, 3),
            "lead_s": round((fall - i) / fps, 3),
            "active_at_window_start": chronic,
            "active_since_s": round(since / fps, 3),
            "evidence": evidence[name](i, start, fall) if name in evidence else {},
        })
    rank = {c: k for k, c in enumerate(CAUSES)}
    cands.sort(key=lambda c: (c["active_at_window_start"], c["onset_s"], rank.get(c["cause"], len(rank))))
    new = [c for c in cands if not c["active_at_window_start"] and c["cause"] not in SYMPTOMS]
    chronic = sorted((c for c in cands if c["active_at_window_start"] and c["cause"] not in SYMPTOMS),
                     key=lambda c: (c["active_since_s"], rank.get(c["cause"], len(rank))))
    primary = (new or chronic or cands or [None])[0]
    return {
        "fall_time_s": round(fall / fps, 3),
        "window_s": [round(start / fps, 3), round(fall / fps, 3)],
        "primary_cause": primary["cause"] if primary else "undetermined",
        "primary_onset_s": (primary["active_since_s"] if primary["active_at_window_start"] else primary["onset_s"])
        if primary else None,
        "primary_evidence": primary["evidence"] if primary else {},
        "candidates": cands,
    }


@dataclass
class FallSignals:
    """What a physics replay recorded, one row per frame (T frames), for diagnose_falls."""
    fps: float
    feet: list  # foot link names, in the order of the feet axis below
    ref_soles: np.ndarray  # (T, feet, C, 3) sole points of the clip (the reference pose)
    soles: np.ndarray  # (T, feet, C, 3) sole points of the simulation
    foot_force: np.ndarray  # (T, feet) foot contact force, N (NaN: unknown)
    weight: float  # body weight, N
    tau_ratio: np.ndarray  # (T, joints) drive demand / torque limit
    joint_names: list
    sim_track: object  # stability.BalanceTrack of the simulation
    distances: dict  # {"feet", "knees"}: (T,) m between the left and right link origins (inf: unknown)
    harness: np.ndarray | None = None  # (T,) harness force / body weight (None: no harness)
    assist: float = 0.0  # harness scale (0: off)
    ref_track: object = None  # the clip's BalanceTrack: did the clip itself have its CoM outside the feet


def diagnose_falls(sig: FallSignals, cfg: dict, fall_frames: list[int], settle: int = 3,
                   min_frames: int | None = None, chronic_needs_run: bool = False) -> list[dict]:
    """diagnose_fall for every fall frame in order, with the conditions of the module docstring and
    the thresholds of configs/physics.yaml "diagnosis" (``cfg``). settle: frames after a (re)start
    while the robot settles on the floor (no window reaches before prev fall + settle); min_frames:
    run length of a condition (default: cfg "min_frames", 2). Falls at or past the last frame end
    the list."""
    from .analysis import floor_track, slowest_sole_speed

    d = cfg
    fps = sig.fps
    if not fall_frames:
        return []
    ref_sp, SP = sig.ref_soles, sig.soles
    T = len(SP)
    feet = sig.feet
    ref_low = ref_sp[..., 2].min(-1)
    ref_speed = slowest_sole_speed(ref_sp, fps)
    ref_clear = ref_low - floor_track(ref_low, ref_speed, fps)[:, None]
    sim_low = SP[..., 2].min(-1)
    sim_speed = slowest_sole_speed(SP, fps)
    ff = np.nan_to_num(sig.foot_force, nan=0.0)
    weight = sig.weight
    contact_h = float(d.get("contact_height_m", 0.005))
    on_floor = (sim_low < contact_h) | (ff > float(d.get("contact_force_bw", 0.05)) * weight)
    # the clip's foot swings (fast and off the floor: a touchdown at 0.6 m/s is not a swing)
    toe = on_floor & (ref_speed > float(d.get("swing_speed_mps", 0.5))) & (ref_clear > contact_h)
    slip_v = float(d.get("slip_speed_mps", 0.3))
    slip = on_floor & (sim_speed > slip_v) & (ref_speed < slip_v)
    dist = sig.distances
    selfc = np.minimum(dist["feet"], dist["knees"]) < float(d.get("self_distance_m", 0.09))
    tau_ratio, joint_names = sig.tau_ratio, sig.joint_names
    tmax, targ = tau_ratio.max(1), tau_ratio.argmax(1)
    torque = tmax > float(d.get("torque_ratio", 1.5))
    sim_track, ref_track, assist = sig.sim_track, sig.ref_track, sig.assist
    harness = np.zeros(T) if sig.harness is None else sig.harness
    cm = np.nan_to_num(sim_track.com_margin, nan=0.0)
    zm = np.nan_to_num(sim_track.zmp_margin, nan=0.0)
    exit_ = cm < -float(d.get("com_outside_m", 0.03))
    if assist <= 0:  # with the harness on, the ZMP includes its pull and leaves the feet all the time
        exit_ |= zm < -float(d.get("zmp_outside_m", 0.05))
    exit_ &= sim_track.supported
    spike = harness > float(d.get("harness_bw", 0.5)) if assist > 0 else np.zeros(T, bool)

    def r(x, k=2):
        return None if x is None or not np.isfinite(x) else round(float(x), k)

    def toe_ev(i, a, b):
        ks = np.flatnonzero(toe[i])
        return {"feet": [feet[k] for k in ks],
                "clip_foot_speed_mps": [r(ref_speed[i, k]) for k in ks],
                "clip_clearance_cm": [r(100 * ref_clear[i, k], 1) for k in ks],
                "sim_sole_height_cm": [r(100 * sim_low[i, k], 1) for k in ks],
                "contact_force_n": [r(ff[i, k], 0) for k in ks]}

    def slip_ev(i, a, b):
        ks = np.flatnonzero(slip[i])
        return {"feet": [feet[k] for k in ks], "sim_foot_speed_mps": [r(sim_speed[i, k]) for k in ks],
                "peak_speed_in_window_mps": r(sim_speed[a:b + 1].max())}

    def self_ev(i, a, b):
        return {"feet_distance_m": r(dist["feet"][i], 3), "knees_distance_m": r(dist["knees"][i], 3),
                "min_in_window_m": r(min(dist["feet"][a:b + 1].min(), dist["knees"][a:b + 1].min()), 3)}

    def torque_ev(i, a, b):
        w = a + int(np.argmax(tmax[a:b + 1]))
        return {"joint": joint_names[targ[i]], "demand_per_limit": r(tmax[i]),
                "peak_joint": joint_names[targ[w]], "peak_demand_per_limit": r(tmax[w]), "peak_s": r(w / fps, 3)}

    def exit_ev(i, a, b):
        ev = {"com_margin_cm": r(100 * sim_track.com_margin[i], 1), "zmp_margin_cm": r(100 * sim_track.zmp_margin[i], 1),
              "feet_on_floor": int(sim_track.phase[i]),
              "min_com_margin_in_window_cm": r(100 * np.nanmin(sim_track.com_margin[a:b + 1]), 1)
              if np.isfinite(sim_track.com_margin[a:b + 1]).any() else None}
        if ref_track is not None and i < len(ref_track.com_margin):
            ev["clip_com_margin_cm"] = r(100 * ref_track.com_margin[i], 1)  # < 0: the clip's own CoM was outside too
        return ev

    def harness_ev(i, a, b):
        return {"harness_per_body_weight": r(harness[i]), "peak_in_window": r(harness[a:b + 1].max())}

    conditions = {"toe_catch": toe.any(1), "foot_slip": slip.any(1), "self_collision": selfc,
                  "torque_saturation": torque, "support_exit": exit_}
    evidence = {"toe_catch": toe_ev, "foot_slip": slip_ev, "self_collision": self_ev,
                "torque_saturation": torque_ev, "support_exit": exit_ev}
    if assist > 0:
        conditions["harness_spike"] = spike
        evidence["harness_spike"] = harness_ev
    window = max(1, int(round(float(d.get("window_s", 0.75)) * fps)))
    if min_frames is None:
        min_frames = int(d.get("min_frames", 2))
    out, prev = [], 0
    for fr in fall_frames:
        if fr >= T:
            break
        start = min(max(prev + settle, fr - window), fr)
        out.append(diagnose_fall(conditions, evidence, fr, start, fps, min_frames,
                                 earliest=min(prev + settle, fr), chronic_needs_run=chronic_needs_run))
        prev = fr
    return out


# ------------------------------------------------------------------------------- text
def cause_counts(diags: list[dict]) -> list[tuple[str, int]]:
    """[(cause id, falls)] of these diagnoses' primary causes, the most common first (ties in CAUSES
    order, 'undetermined' last)."""
    rank = {c: k for k, c in enumerate(CAUSES)}
    n = Counter(d.get("primary_cause") or "undetermined" for d in diags)
    return sorted(n.items(), key=lambda kv: (-kv[1], rank.get(kv[0], len(rank)), kv[0]))


def cause_counts_text(diags: list[dict], top: int | None = None) -> str:
    """Falls per primary cause in Korean, e.g. '지지면 이탈 6 · 발끝 걸림 2'; with ``top``, the rest as
    '외 1회' (falls, not causes). '' without diagnoses."""
    counts = cause_counts(diags)
    shown = counts if top is None else counts[:top]
    text = " · ".join(f"{CAUSE_KO.get(c, c)} {n}" for c, n in shown)
    rest = sum(n for _c, n in counts[len(shown):])
    return f"{text} 외 {rest}회" if rest else text


def causes_text(diags: list[dict], show: int = 3) -> str:
    """First cause of each fall, e.g. '발끝 걸림 1.467s (넘어짐 2.067s)'; beyond ``show`` falls, a count
    per cause ('; 외 지지면 이탈 2, 발 미끄러짐 1'). '-' without diagnoses. An undetermined fall has no
    onset: '미상 (넘어짐 3.0s)'."""
    out = []
    for d in diags[:show]:
        name = CAUSE_KO.get(d["primary_cause"], d["primary_cause"])
        onset = d.get("primary_onset_s")
        out.append(f"{name} {onset}s (넘어짐 {d['fall_time_s']}s)" if onset is not None
                   else f"{name} (넘어짐 {d['fall_time_s']}s)")
    if len(diags) > show:
        out.append("외 " + ", ".join(f"{CAUSE_KO.get(c, c)} {n}" for c, n in cause_counts(diags[show:])))
    return "; ".join(out) or "-"


def foot_ko(name: str) -> str:
    """'왼발' / '오른발' for a foot link's name (FOOT_KO), else the name."""
    low = str(name).lower()
    return next((ko for side, ko in FOOT_KO.items() if side in low), str(name))


def evidence_text(cause: str, ev: dict | None, assist: float | None = None) -> str:
    """One Korean line of a cause's evidence (diagnose_fall's "evidence" / "primary_evidence"), e.g.
    '왼발 · 원본 발 속도 0.90 m/s · 원본 발 높이 3.0 cm · 시뮬 발 높이 0.2 cm · 접촉력 310 N'. ''
    when there is nothing to say. assist: the run's harness scale, if known; support_exit then leaves
    out the ZMP when the harness was on (its pull moves the ZMP, so the diagnosis does not use it)."""
    ev = ev or {}

    def num(v, fmt):
        return None if v is None else fmt.format(v if v else 0.0)  # a rounded -0.0 reads 0.0

    def per_foot(keys):  # one segment per foot: keys = [(evidence list, format)]
        segs = []
        for k, foot in enumerate(ev.get("feet") or []):
            parts = [foot_ko(foot)]
            for key, fmt in keys:
                vals = ev.get(key) or []
                v = num(vals[k], fmt) if k < len(vals) else None
                if v is not None:
                    parts.append(v)
            segs.append(" · ".join(parts))
        return " / ".join(segs)

    if cause == "toe_catch":
        return per_foot([("clip_foot_speed_mps", "원본 발 속도 {:.2f} m/s"), ("clip_clearance_cm", "원본 발 높이 {:.1f} cm"),
                         ("sim_sole_height_cm", "시뮬 발 높이 {:.1f} cm"), ("contact_force_n", "접촉력 {:.0f} N")])
    if cause == "foot_slip":
        text = per_foot([("sim_foot_speed_mps", "미끄러진 속도 {:.2f} m/s")])
        peak = num(ev.get("peak_speed_in_window_mps"), "구간 최대 {:.2f} m/s")
        return f"{text} ({peak})" if text and peak else text or peak or ""
    if cause == "self_collision":
        cm = {k: None if ev.get(k) is None else 100 * ev[k]
              for k in ("feet_distance_m", "knees_distance_m", "min_in_window_m")}
        parts = [num(cm["feet_distance_m"], "두 발 사이 {:.0f} cm"), num(cm["knees_distance_m"], "두 무릎 사이 {:.0f} cm"),
                 num(cm["min_in_window_m"], "구간 최소 {:.0f} cm")]
        return " · ".join(p for p in parts if p)
    if cause == "torque_saturation":
        if ev.get("joint") is None or ev.get("demand_per_limit") is None:
            return ""
        text = f"{ev['joint']} 요구 토크 한계의 {ev['demand_per_limit']:.1f}배"
        if ev.get("peak_demand_per_limit") is not None:
            at = f", {ev['peak_s']:.2f}s" if ev.get("peak_s") is not None else ""
            peak = ev.get("peak_joint")
            joint = f"{peak} " if peak and peak != ev["joint"] else ""
            text += f" (구간 최대 {joint}{ev['peak_demand_per_limit']:.1f}배{at})"
        return text
    if cause == "support_exit":
        parts = []
        cm, zm, clip = ev.get("com_margin_cm"), ev.get("zmp_margin_cm"), ev.get("clip_com_margin_cm")
        if cm is not None:
            parts.append(num(-cm, "CoM 지지면 밖 {:.1f} cm") if cm < 0 else num(cm, "CoM 지지면 안 {:.1f} cm"))
        # the ZMP when it is further out than the CoM (without the harness it counts too)
        if zm is not None and zm < 0 and (cm is None or zm < cm) and (assist is None or assist <= 0):
            parts.append(num(-zm, "ZMP 지지면 밖 {:.1f} cm"))
        if clip is not None:
            parts.append(num(-clip, "원본도 밖 {:.1f} cm (데이터 자체)") if clip < 0 else num(clip, "원본은 안 {:.1f} cm"))
        return " · ".join(parts)
    if cause == "harness_spike":
        h, peak = ev.get("harness_per_body_weight"), ev.get("peak_in_window")
        if h is None:
            return ""
        return f"보조 힘 체중의 {100 * h:.0f}%" + (f" (구간 최대 {100 * peak:.0f}%)" if peak is not None else "")
    return ""
