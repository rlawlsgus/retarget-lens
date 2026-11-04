"""First cause of a fall (retlens/diagnosis.py): diagnose_falls on synthetic FallSignals, the Korean text
helpers, and that tools/isaac_replay.py's fall_diagnosis, now a wrapper of diagnose_falls, gives exactly
what its own body gave before (that source read from git: isaac_replay.py imports Isaac Sim, so neither
version can be imported here; both are compiled out of their files)."""

import ast
import glob
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens import stability  # noqa: E402
from retlens.diagnosis import (CAUSES, FallSignals, cause_counts, cause_counts_text, causes_text,  # noqa: E402
                               diagnose_falls, evidence_text, foot_ko)

FEET = ["left_ankle_roll_link", "right_ankle_roll_link"]
# the last commit whose isaac_replay.fall_diagnosis had its own body (RetLens 0.4.1 to 0.7.0)
OLD_COMMIT = "718d5f7c8771eaab6543ab3388d1eb6ee8a52d2d"


# ------------------------------------------------------------------------------ synthetic signals
def _feet(T: int, z: float = 0.0) -> np.ndarray:
    """(T, 2, 4, 3) sole corners of two feet standing at y = +-0.1 (8 x 3 cm boxes around x = 0)."""
    c = np.array([[0.08, 0.03], [0.08, -0.03], [-0.08, 0.03], [-0.08, -0.03]])
    out = np.zeros((T, 2, 4, 3))
    for k, y in enumerate((0.1, -0.1)):
        out[:, k, :, 0] = c[:, 0]
        out[:, k, :, 1] = y + c[:, 1]
    out[..., 2] = z
    return out


def _track(T: int, fps: float, com_margin=0.05, zmp_margin=0.05, phase=2) -> stability.BalanceTrack:
    """A BalanceTrack with the margins given (m; scalars or (T,) arrays)."""
    cm = np.broadcast_to(np.asarray(com_margin, float), (T,)).copy()
    zm = np.broadcast_to(np.asarray(zmp_margin, float), (T,)).copy()
    ph = np.broadcast_to(np.asarray(phase), (T,)).copy()
    com = np.tile([0.0, 0.0, 0.7], (T, 1))
    return stability.BalanceTrack(fps, com, com[:, :2].copy(), np.zeros(T), ph, np.ones((T, 2), bool), [], cm, zm)


def _quiet(T: int = 100, fps: float = 50.0, **kw) -> FallSignals:
    """Standing still with nothing wrong: every condition off."""
    w = 340.0
    args = dict(fps=fps, feet=list(FEET), ref_soles=_feet(T), soles=_feet(T), foot_force=np.full((T, 2), w / 2),
                weight=w, tau_ratio=np.full((T, 4), 0.3), joint_names=["hip", "knee", "ankle_pitch", "ankle_roll"],
                sim_track=_track(T, fps), distances={"feet": np.full(T, 0.2), "knees": np.full(T, 0.2)},
                harness=np.full(T, 0.1), assist=0.0, ref_track=_track(T, fps))
    args.update(kw)
    return FallSignals(**args)


def _swing(sp: np.ndarray, foot: int, a: int, b: int, fps: float, speed: float = 1.0, height: float = 0.03):
    """The foot moves forward at ``speed`` and up to ``height`` over frames [a, b)."""
    n = b - a
    sp[a:b, foot, :, 0] += speed * np.arange(1, n + 1)[:, None] / fps
    sp[b:, foot, :, 0] += speed * n / fps
    sp[a:b, foot, :, 2] += height * np.sin(np.pi * (np.arange(n) + 0.5) / n)[:, None]


def test_quiet_signals_have_no_cause():
    d = diagnose_falls(_quiet(), {}, [60])
    assert len(d) == 1 and d[0]["primary_cause"] == "undetermined" and d[0]["primary_onset_s"] is None
    assert d[0]["candidates"] == [] and d[0]["fall_time_s"] == 1.2 and d[0]["window_s"] == [0.44, 1.2]  # 38 frames back
    assert diagnose_falls(_quiet(), {}, []) == []


def test_toe_catch_onset_and_evidence():
    """The clip swings its left foot up 3 cm at 1 m/s while the simulated foot stays on the floor."""
    T, fps = 100, 50.0
    ref = _feet(T)
    _swing(ref, 0, 40, 60, fps)
    d = diagnose_falls(_quiet(T, fps, ref_soles=ref), {}, [65])[0]
    assert d["primary_cause"] == "toe_catch" and not d["candidates"][0]["active_at_window_start"]
    assert 0.8 <= d["primary_onset_s"] <= 0.86  # once the clip's foot is 5 mm up (the first frames are a touchdown)
    ev = d["primary_evidence"]
    assert ev["feet"] == ["left_ankle_roll_link"] and ev["clip_foot_speed_mps"] == [1.0]
    assert ev["sim_sole_height_cm"] == [0.0] and ev["contact_force_n"] == [170.0]
    assert evidence_text("toe_catch", ev).startswith("왼발 · 원본 발 속도 1.00 m/s · 원본 발 높이 ")
    assert evidence_text("toe_catch", ev).endswith(" · 시뮬 발 높이 0.0 cm · 접촉력 170 N")


def test_support_exit_zmp_counts_only_without_the_harness():
    T, fps = 100, 50.0
    zmp_out = np.where((np.arange(T) >= 50) & (np.arange(T) < 70), -0.1, 0.05)
    track = _track(T, fps, com_margin=0.02, zmp_margin=zmp_out)
    d = diagnose_falls(_quiet(T, fps, sim_track=track, assist=0.0), {}, [70])[0]
    assert d["primary_cause"] == "support_exit" and d["primary_onset_s"] == 1.0
    assert d["primary_evidence"]["clip_com_margin_cm"] == 5.0
    assert evidence_text("support_exit", d["primary_evidence"]) == \
        "CoM 지지면 안 2.0 cm · ZMP 지지면 밖 10.0 cm · 원본은 안 5.0 cm"
    on = diagnose_falls(_quiet(T, fps, sim_track=track, assist=1.0), {}, [70])[0]
    assert on["primary_cause"] == "undetermined"  # the harness's pull moves the ZMP: only the CoM counts
    com_out = _track(T, fps, com_margin=np.where(np.arange(T) >= 55, -0.05, 0.02))
    clip_out = _track(T, fps, com_margin=-0.097)
    d = diagnose_falls(_quiet(T, fps, sim_track=com_out, assist=1.0, ref_track=clip_out), {}, [70])[0]
    assert d["primary_cause"] == "support_exit" and d["primary_onset_s"] == 1.1
    assert evidence_text("support_exit", d["primary_evidence"], assist=1.0) == \
        "CoM 지지면 밖 5.0 cm · 원본도 밖 9.7 cm (데이터 자체)"
    no_floor = _track(T, fps, com_margin=-0.05, phase=0)  # nothing on the floor: no support to leave
    assert diagnose_falls(_quiet(T, fps, sim_track=no_floor), {}, [70])[0]["primary_cause"] == "undetermined"


def test_self_collision_torque_and_chronic_ranking():
    T, fps = 100, 50.0
    knees = np.full(T, 0.2)
    knees[58:66] = 0.07
    tau = np.full((T, 4), 0.3)
    tau[:, 2] = 2.0  # the ankle over its limit all along: chronic
    tau[62:64, 1] = 3.0
    d = diagnose_falls(_quiet(T, fps, distances={"feet": np.full(T, 0.2), "knees": knees}, tau_ratio=tau), {}, [70])[0]
    cands = {c["cause"]: c for c in d["candidates"]}
    assert d["primary_cause"] == "self_collision" and d["primary_onset_s"] == 1.16  # new beats chronic
    assert cands["torque_saturation"]["active_at_window_start"] and cands["torque_saturation"]["active_since_s"] == 0.06
    assert evidence_text("self_collision", d["primary_evidence"]) == "두 발 사이 20 cm · 두 무릎 사이 7 cm · 구간 최소 7 cm"
    ev = cands["torque_saturation"]["evidence"]
    assert ev["joint"] == "ankle_pitch" and ev["peak_joint"] == "knee" and ev["peak_demand_per_limit"] == 3.0
    assert evidence_text("torque_saturation", ev) == "ankle_pitch 요구 토크 한계의 2.0배 (구간 최대 knee 3.0배, 1.24s)"
    only = diagnose_falls(_quiet(T, fps, tau_ratio=tau), {}, [70])[0]  # chronic only: the one active the longest
    assert only["primary_cause"] == "torque_saturation" and only["primary_onset_s"] == 0.06


def test_harness_spike_only_with_the_harness_and_only_alone():
    T, fps = 100, 50.0
    pull = np.full(T, 0.1)
    pull[50:] = 0.7
    d = diagnose_falls(_quiet(T, fps, harness=pull, assist=1.0), {}, [70])[0]
    assert d["primary_cause"] == "harness_spike" and d["primary_onset_s"] == 1.0
    assert evidence_text("harness_spike", d["primary_evidence"]) == "보조 힘 체중의 70% (구간 최대 70%)"
    tau = np.full((T, 4), 0.3)
    tau[60:, 0] = 2.0  # later than the pull, still the cause: the pull is a consequence
    d = diagnose_falls(_quiet(T, fps, harness=pull, assist=1.0, tau_ratio=tau), {}, [70])[0]
    assert d["primary_cause"] == "torque_saturation" and {c["cause"] for c in d["candidates"]} >= {"harness_spike"}
    assert diagnose_falls(_quiet(T, fps, harness=pull, assist=0.0), {}, [70])[0]["primary_cause"] == "undetermined"
    assert diagnose_falls(_quiet(T, fps, harness=None, assist=1.0), {}, [70])[0]["primary_cause"] == "undetermined"


def test_windows_settle_and_end():
    """A window never reaches back before the previous restart + settle; a fall at or past the last
    frame ends the list; min_frames comes from the config unless given."""
    T, fps = 100, 50.0
    slip_sim = _feet(T)
    _swing(slip_sim, 1, 36, 40, fps, speed=1.0, height=0.0)  # the right foot slides on the floor, frames 36-39
    sig = _quiet(T, fps, soles=slip_sim)
    first, second = diagnose_falls(sig, {}, [40, 44, T, T + 5])
    assert first["primary_cause"] == "foot_slip" and first["primary_onset_s"] == 0.72
    assert second["window_s"] == [43 / fps, 44 / fps] and second["primary_cause"] == "undetermined"
    assert diagnose_falls(sig, {}, [40, 44], settle=5)[1]["window_s"] == [0.88, 0.88]
    assert len(diagnose_falls(sig, {}, [40, 99])) == 2
    two = np.full((T, 4), 0.3)
    two[30:32, 0] = 2.0  # two frames over the limit, well before the fall
    assert diagnose_falls(_quiet(T, fps, tau_ratio=two), {}, [40])[0]["primary_cause"] == "torque_saturation"
    assert diagnose_falls(_quiet(T, fps, tau_ratio=two), {"min_frames": 3}, [40])[0]["primary_cause"] == "undetermined"
    assert diagnose_falls(_quiet(T, fps, tau_ratio=two), {}, [40], min_frames=3)[0]["primary_cause"] == "undetermined"
    nan_force = _quiet(T, fps, foot_force=np.full((T, 2), np.nan))  # forces unknown: the sole height decides
    assert diagnose_falls(nan_force, {}, [60])[0]["primary_cause"] == "undetermined"


# ------------------------------------------------------------------------------------------- text
def _d(cause, onset, t):
    return {"primary_cause": cause, "primary_onset_s": onset, "fall_time_s": t}


def test_text_helpers():
    diags = ([_d("support_exit", 0.4, 1.0)] * 6 + [_d("toe_catch", 1.5, 2.0)] * 2 + [_d("foot_slip", 3, 4)]
             + [_d("undetermined", None, 5.0)])
    assert cause_counts(diags) == [("support_exit", 6), ("toe_catch", 2), ("foot_slip", 1), ("undetermined", 1)]
    tie = [_d("support_exit", 1, 2), _d("torque_saturation", 1, 2), _d("toe_catch", 1, 2)]
    assert [c for c, _n in cause_counts(tie)] == ["toe_catch", "torque_saturation", "support_exit"]  # CAUSES order
    assert cause_counts_text(diags) == "지지면 이탈 6 · 발끝 걸림 2 · 발 미끄러짐 1 · 미상 1"
    assert cause_counts_text(diags, top=2) == "지지면 이탈 6 · 발끝 걸림 2 외 2회"
    assert cause_counts_text(diags[:6], top=2) == "지지면 이탈 6" and cause_counts_text([]) == ""
    assert causes_text([]) == "-"
    assert causes_text([_d("toe_catch", 1.467, 2.067)]) == "발끝 걸림 1.467s (넘어짐 2.067s)"
    assert causes_text([_d("undetermined", None, 3.0)]) == "미상 (넘어짐 3.0s)"  # was '미상 Nones'
    assert causes_text(diags).endswith("; 외 지지면 이탈 3, 발끝 걸림 2, 발 미끄러짐 1, 미상 1")
    assert foot_ko("left_ankle_roll_link") == "왼발" and foot_ko("right_foot") == "오른발" and foot_ko("pelvis") == "pelvis"
    slip = {"feet": ["right_ankle_roll_link"], "sim_foot_speed_mps": [0.45], "peak_speed_in_window_mps": 0.8}
    assert evidence_text("foot_slip", slip) == "오른발 · 미끄러진 속도 0.45 m/s (구간 최대 0.80 m/s)"
    two = {"feet": FEET, "clip_foot_speed_mps": [0.9, 0.6], "clip_clearance_cm": [3.0, None],
           "sim_sole_height_cm": [0.2, -0.0], "contact_force_n": [310.0, 40.0]}
    assert evidence_text("toe_catch", two) == ("왼발 · 원본 발 속도 0.90 m/s · 원본 발 높이 3.0 cm · 시뮬 발 높이 0.2 cm · "
                                               "접촉력 310 N / 오른발 · 원본 발 속도 0.60 m/s · 시뮬 발 높이 0.0 cm · 접촉력 40 N")
    ex = {"com_margin_cm": -3.0, "zmp_margin_cm": -12.0, "clip_com_margin_cm": 2.1}
    assert evidence_text("support_exit", ex) == "CoM 지지면 밖 3.0 cm · ZMP 지지면 밖 12.0 cm · 원본은 안 2.1 cm"
    assert evidence_text("support_exit", ex, assist=1.0) == "CoM 지지면 밖 3.0 cm · 원본은 안 2.1 cm"
    assert evidence_text("harness_spike", {"harness_per_body_weight": 0.62}) == "보조 힘 체중의 62%"
    assert evidence_text("undetermined", {}) == "" and evidence_text("toe_catch", None) == ""
    assert evidence_text("torque_saturation", {"joint": "left_knee_joint", "demand_per_limit": 1.8}) == \
        "left_knee_joint 요구 토크 한계의 1.8배"


# ----------------------------------------------------------------- Isaac: the wrapper == the old body
def _git() -> str | None:
    found = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "GitHubDesktop", "app-*", "resources", "app",
                                   "git", "cmd", "git.exe"))  # this project's git (GitHub Desktop's)
    return sorted(found)[-1] if found else shutil.which("git")


def _function(text: str, name: str):
    """The module-level function ``name`` of a source text, compiled on its own (numpy as np)."""
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"np": np}
    exec(compile(ast.get_source_segment(text, node), f"<{name}>", "exec"), ns)
    return ns[name]


def _isaac_inputs(seed: int, T: int = 150, fps: float = 30.0, assist: float = 1.0, nan_forces: bool = False):
    """fall_diagnosis's arguments for a made-up Isaac run where every condition shows up, some chronic."""
    rng = np.random.default_rng(seed)
    links = ["pelvis", "left_hip_pitch_link", "left_knee_link", FEET[0], "right_hip_pitch_link", "right_knee_link", FEET[1]]
    robot = SimpleNamespace(foot_names=list(FEET), link_names=links)
    ref = _feet(T) + rng.normal(0, 1e-4, (T, 2, 4, 3))
    for foot, (a, b) in ((0, (20, 34)), (1, (50, 64)), (0, (80, 94)), (1, (112, 126))):
        _swing(ref, foot, a, b, fps, speed=1.2, height=0.05)
    sim = _feet(T) + rng.normal(0, 1e-4, (T, 2, 4, 3))
    _swing(sim, 0, 80, 94, fps, speed=1.2, height=0.05)  # follows the clip's third swing, not its first
    _swing(sim, 1, 50, 64, fps, speed=1.2, height=0.05)
    _swing(sim, 1, 98, 104, fps, speed=0.8, height=0.0)  # slides while the clip's right foot stands
    sim[140:143, :, :, 2] += 0.05  # both feet off the floor: no support
    LP = rng.normal(0, 0.01, (T, 7, 3))
    LP[:, 3, 1], LP[:, 6, 1] = 0.1, -0.1
    LP[:, 2, 1], LP[:, 5, 1] = 0.1, -0.1
    LP[86:96, 3, 1], LP[86:96, 6, 1] = 0.03, -0.03  # the feet 6 cm apart
    FF = np.abs(rng.normal(150, 30, (T, 2)))
    FF[::7] = np.nan
    if nan_forces:
        FF[:] = np.nan
    tau = np.abs(rng.normal(0.4, 0.2, (T, 5)))
    tau[5:60, 2] = 1.8  # chronic for the first fall
    tau[118:124, 4] = 3.0
    falls = [45, 75, 100, 146, T + 3]
    com = np.stack([0.02 * np.sin(np.arange(T) / 9.0), np.zeros(T), np.full(T, 0.68)], 1)
    com[30:50, 0] += 0.12  # out over the toes
    com[130:146, 1] += 0.2
    sim_track = stability.balance_track(com, sim, fps, np.zeros(T), 0.02, breaks=[f + 1 for f in falls])
    ref_com = com + rng.normal(0, 0.01, com.shape)
    ref_track = stability.balance_track(ref_com, ref, fps, 0.0, 0.02)
    harness = np.abs(rng.normal(0.2, 0.05, T))
    harness[66:76] = 0.8
    harness[138:] = 0.9
    names = ["waist", "left_hip_pitch_joint", "left_ankle_pitch_joint", "right_knee_joint", "right_ankle_roll_joint"]
    args = [{"min_frames": 2, "window_s": 0.75}, fps, falls, robot, ref, sim, LP, FF, 340.0, tau, names, sim_track,
            harness, assist, ref_track]
    return args


def test_isaac_fall_diagnosis_wrapper_matches_the_old_body():
    git = _git()
    if not git:
        pytest.skip("git not found")
    try:
        old_text = subprocess.run([git, "show", f"{OLD_COMMIT}:tools/isaac_replay.py"], cwd=ROOT, capture_output=True,
                                  text=True, encoding="utf-8", check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError) as e:
        pytest.skip(f"the old source is not in this checkout: {e}")
    with open(os.path.join(ROOT, "tools", "isaac_replay.py"), encoding="utf-8") as f:
        new_text = f.read()
    old, new = _function(old_text, "fall_diagnosis"), _function(new_text, "fall_diagnosis")
    assert "diagnose_falls" in new_text and "diagnose_falls" not in old_text  # really the two versions
    seen, chronic, outcomes = set(), 0, set()
    for seed, assist, nan_forces in ((0, 1.0, False), (1, 0.0, False), (2, 1.0, True), (3, 0.0, True), (4, 0.5, False)):
        args = _isaac_inputs(seed, assist=assist, nan_forces=nan_forces)
        want, got = old(*args), new(*args)
        assert got == want, (seed, assist)
        assert len(got) == 4  # the fall past the end is dropped
        for d in got:
            outcomes.add(d["primary_cause"])
            for c in d["candidates"]:
                seen.add(c["cause"])
                chronic += c["active_at_window_start"]
        close = list(args)
        close[2] = [3, 10, 12, 149, 150]  # falls back to back, and at the last frame
        close[11] = stability.balance_track(args[11].com, args[5], 30.0, 0.0, 0.02, breaks=[4, 11, 13])
        assert new(*close) == old(*close)
        assert new(*close)[0]["primary_cause"] == "undetermined"
        empty = list(args)
        empty[2] = []
        assert new(*empty) == old(*empty) == []
    assert seen == set(CAUSES) and chronic > 0 and len(outcomes) >= 3  # the comparison covered every condition


def test_a_blip_at_the_window_start_is_not_a_condition_already_on():
    """MuJoCo (chronic_needs_run): a condition counts as already on only when its run starts with the window, so a
    one-frame blip there does not hide the run that begins later; Isaac keeps the first frame's say."""
    from retlens.diagnosis import diagnose_fall

    blip = np.zeros(40, bool)
    blip[10] = True
    blip[20:26] = True  # the window opens at 10; the run that counts starts at 20
    late = np.zeros(40, bool)
    late[22:30] = True
    for needs_run, primary in ((False, "support_exit"), (True, "torque_saturation")):
        d = diagnose_fall({"torque_saturation": blip, "support_exit": late}, {}, fall=30, start=10, fps=50.0,
                          min_frames=3, chronic_needs_run=needs_run)
        assert d["primary_cause"] == primary

