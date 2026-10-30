"""Automatic labels (retlens/autolabel): movement tracks from a skeleton, named by a rule file."""

import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import autolabel, motion_labels  # noqa: E402
from retlens.autolabel import body, rules, segment, signals  # noqa: E402
from retlens.io.bvh import load_bvh  # noqa: E402
from retlens.motion import SkeletonMotion  # noqa: E402
from retlens.synthetic import walking_bvh_text  # noqa: E402

FPS = 30.0
SMPL = ["pelvis", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot",
        "right_foot", "spine3", "head", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist",
        "right_wrist"]


def _reach(seconds=4.0):
    """Standing still; the left arm rises forward to horizontal over 1.0-1.5 s, stays to 2.5 s and comes
    down by 3.0 s. Joint positions (m, Z up, facing +X) under SMPL names, no body model."""
    T = int(seconds * FPS)
    t = np.arange(T) / FPS
    ramp = lambda a, b: np.clip((t - a) / (b - a), 0, 1)
    up = 0.5 - 0.5 * np.cos(np.pi * ramp(1.0, 1.5))
    down = 0.5 - 0.5 * np.cos(np.pi * ramp(2.5, 3.0))
    th = (np.pi / 2) * (up - down)
    j = {"pelvis": (0, 0, 0.95), "left_hip": (0, 0.09, 0.9), "right_hip": (0, -0.09, 0.9),
         "left_knee": (0, 0.09, 0.49), "right_knee": (0, -0.09, 0.49), "left_ankle": (0, 0.09, 0.08),
         "right_ankle": (0, -0.09, 0.08), "left_foot": (0.13, 0.09, 0.03), "right_foot": (0.13, -0.09, 0.03),
         "spine3": (0, 0, 1.35), "head": (0, 0, 1.6), "left_shoulder": (0, 0.18, 1.45), "right_shoulder": (0, -0.18, 1.45),
         "right_elbow": (0, -0.18, 1.17), "right_wrist": (0, -0.18, 0.92)}
    P = np.zeros((T, len(SMPL), 3))
    for i, n in enumerate(SMPL):
        if n in j:
            P[:, i] = j[n]
    arm = np.stack([np.sin(th), np.zeros(T), -np.cos(th)], -1)
    sh = np.array(j["left_shoulder"])
    P[:, SMPL.index("left_elbow")] = sh + 0.28 * arm
    P[:, SMPL.index("left_wrist")] = sh + 0.53 * arm
    return SkeletonMotion(name="reach", joint_names=SMPL, parents=np.full(len(SMPL), -1), positions=P, fps=FPS)


RULES = {"name": "시험", "tracks": [
    {"track": "동작", "rules": [
        {"label": "걷기", "when": {"걸음": "걸음 중"}},
        {"label": "뻗기", "name": "손 뻗기", "when": [{"왼손": "뻗기"}, {"오른손": "뻗기"}], "color": "#ff0000"},
        {"label": "작업", "when": {"손": "작업"}},
        {"label": "서기"}]},
    {"track": "왼손", "axis": "왼손", "skip": ["휴지"]}]}


def _at(lab, track, t):
    return next((s.label for s in lab.segments if s.track == track and s.start <= t < s.end), None)


def test_a_reach_is_found_and_named_by_the_rules():
    lab = autolabel.label_motion(_reach(), RULES)
    assert not lab.error and lab.auto == "시험" and lab.tracks == ["동작", "왼손"]
    assert [_at(lab, "동작", t) for t in (0.5, 1.25, 2.0, 3.6)] == ["서기", "뻗기", "작업", "서기"]
    assert [_at(lab, "왼손", t) for t in (0.5, 1.25, 2.0, 2.75, 3.6)] == [None, "뻗기", "작업", "되돌리기", None]
    reach = next(s for s in lab.segments if s.label == "뻗기")
    assert reach.name == "손 뻗기" and reach.color == (255, 0, 0)
    assert 0.8 <= reach.start <= 1.05 and 1.3 <= reach.end <= 1.6  # from where the hand starts moving
    assert any("뼈 길이로 추정" in n for n in lab.notes)
    assert max(s.end for s in lab.segments if s.track == "동작") == pytest.approx(4.0)
    clipped = autolabel.label_motion(_reach(), RULES, duration=2.0)
    assert max(s.end for s in clipped.segments) <= 2.0


def test_a_walking_bvh_runs_through_the_engine(tmp_path):
    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=4.0))
    human = load_bvh(str(p))
    idx = body.joint_index(human)
    assert human.joint_names[idx["l_foot"]] == "LeftToe" and human.joint_names[idx["spine3"]] == "Spine1"
    lab = autolabel.label_motion(human, {"tracks": [{"axis": "이동"}, {"track": "자세", "axis": "자세"}]})
    assert not lab.error and lab.segments
    assert lab.segments[0].start == 0 and max(s.end for s in lab.segments) == pytest.approx(human.duration, abs=0.1)


def test_joint_names_of_other_skeletons():
    names = ["mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase",
             "mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase",
             "mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2", "mixamorig:Neck", "mixamorig:Head",
             "mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand",
             "mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"]
    parents = [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20]
    sk = SkeletonMotion("m", names, np.array(parents), np.zeros((2, len(names), 3)), 30.0)
    idx = body.joint_index(sk)
    assert names[idx["spine3"]] == "mixamorig:Spine2" and names[idx["r_foot"]] == "mixamorig:RightToeBase"
    no_toes = [n for n in names if "Toe" not in n]  # the ankle has no child: prepare puts a toe point on the sole
    keep = [names.index(n) for n in no_toes]
    remap = {o: i for i, o in enumerate(keep)}
    sk = SkeletonMotion("m", no_toes, np.array([remap.get(parents[o], -1) for o in keep]),
                        np.zeros((2, len(no_toes), 3)), 30.0)
    idx = body.joint_index(sk)
    assert idx["l_foot"] == idx["l_ankle"] and no_toes[idx["r_foot"]] == "mixamorig:RightFoot"
    markers = SkeletonMotion("c3d", ["A", "B"], np.array([-1, -1]), np.zeros((2, 2, 3)), 30.0, kind="markers")
    lab = autolabel.label_motion(markers, RULES)
    assert "마커" in lab.error and not lab.segments


def test_body_sizes_from_bone_lengths():
    P = {k: v for k, v in zip(["l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle"],
                              np.zeros((6, 50, 3)))}
    P["l_knee"][:, 2] = P["r_knee"][:, 2] = -0.4
    P["l_ankle"][:, 2] = P["r_ankle"][:, 2] = -0.82
    for k in ("l_foot", "r_foot", "pelvis", "l_shoulder", "r_shoulder", "l_elbow", "r_elbow", "l_wrist", "r_wrist"):
        P[k] = np.zeros((50, 3))
    P["l_foot"][:, 2] = P["r_foot"][:, 2] = -0.82 - 0.04  # flat, still feet: toe joint 4 cm below the ankle
    dims, notes = body.dims_from_motion(P)
    assert dims["stature"] == pytest.approx(0.82 / body.LEG) and dims["thigh"] == pytest.approx(0.4)
    assert dims["h_ankle"] == pytest.approx(body.ANKLE * dims["stature"])
    assert dims["h_toe"] == pytest.approx(dims["h_ankle"] - 0.04)


def _tracks(**kw):
    """Movement tracks at rest, with the given ones."""
    T = len(next(iter(kw.values())))
    rest = {"이동": "정지", "자세": "선 자세", "왼손": "휴지", "오른손": "휴지", "손": "휴지"}
    tr = {k: np.full(T, rest.get(k, "없음"), dtype=object) for k in segment.VALUES}
    tr.update({k: np.array(v, dtype=object) for k, v in kw.items()})
    return tr


def test_first_rule_that_holds_any_of_all_of():
    rs = rules.check({"rules": [
        {"label": "carry", "when": {"양손": "들기", "걸음": "걸음 중"}},
        {"label": "reach", "when": [{"왼손": "뻗기"}, {"오른손": "뻗기"}]},
        {"label": "rest"}]})
    tr = _tracks(양손=["들기", "들기", "없음", "없음", "없음"], 걸음=["걸음 중", "없음", "없음", "없음", "없음"],
                 왼손=["뻗기", "뻗기", "휴지", "휴지", "휴지"], 오른손=["휴지", "휴지", "휴지", "뻗기", "휴지"])
    got = [(lab, s, e) for _, lab, s, e, _ in rules.apply(rs, tr, [])]
    assert got == [("carry", 0, 1), ("reach", 1, 2), ("rest", 2, 3), ("reach", 3, 4), ("rest", 4, 5)]
    no_rest = rules.check({"rules": [{"label": "reach", "when": {"왼손": "뻗기"}}]})
    assert [(s, e) for _, _, s, e, _ in rules.apply(no_rest, tr, [])] == [(0, 2)]  # the rest stays unlabelled


def test_then_within_and_min_seg():
    T = 60
    kind = np.full(T, "없음", dtype=object)
    kind[10:20] = "낮추기"  # crouch, reach 10 frames (0.33 s) after it ends
    kind[30:35] = "낮추기"  # a crouch with no reach after it
    hand = np.full(T, "휴지", dtype=object)
    hand[28:30] = "작업"  # 8 frames after the first crouch ends; before the second one starts
    hand[30:40] = "뻗기"
    rs = rules.check({"rules": [{"label": "reach", "when": {"자세전환": "낮추기"}, "then": {"손": ["작업"]}, "within": 0.5},
                                {"label": "x"}]})
    got = [(lab, s, e) for _, lab, s, e, _ in rules.apply(rs, _tracks(자세전환=kind, 손=hand), [])]
    assert got == [("x", 0, 10), ("reach", 10, 20), ("x", 20, 60)]
    rs = rules.check({"rules": [{"label": "a", "when": {"손": "뻗기"}}, {"label": "b"}], "min_seg": 0.5})
    hand = np.full(T, "휴지", dtype=object)
    hand[20:25] = "뻗기"  # 5 frames < 0.5 s: joins its longer neighbour
    assert [lab for _, lab, *_ in rules.apply(rs, _tracks(손=hand), [])] == ["b"]


def test_approach_relabels_the_last_steps():
    T = 90
    loco = np.full(T, "걷기", dtype=object)
    loco[60:] = "정지"
    hand = np.full(T, "휴지", dtype=object)
    hand[62:] = "뻗기"
    steps = [{"lift": x, "strike": x + 10} for x in (5, 20, 35, 50)]
    rs = rules.check({"rules": [{"label": "walk", "when": {"이동": "걷기"}}, {"label": "reach", "when": {"손": "뻗기"}},
                                {"label": "stand"}],
                      "approach": {"from": ["walk"], "to": ["reach"], "label": "approach", "steps": 2}})
    got = [(lab, s, e) for _, lab, s, e, _ in rules.apply(rs, _tracks(이동=loco, 손=hand), steps)]
    assert got == [("walk", 0, 35), ("approach", 35, 60), ("stand", 60, 62), ("reach", 62, 90)]


@pytest.mark.parametrize("data, why", [
    ({"rules": [{"label": "x", "when": {"팔": "뻗기"}}]}, "모르는 트랙 '팔'"),
    ({"rules": [{"label": "x", "when": {"이동": "걷는 중"}}]}, "이동에 '걷는 중' 값은 없습니다"),
    ({"rules": [{"when": {"이동": "걷기"}}]}, "label이 있어야"),
    ({"rules": [{"label": "x", "then": {"손": "뻗기"}, "within": 1}]}, "셋 다"),
    ({"rules": [{"label": "x", "colour": "#fff"}]}, "모르는 항목 colour"),
    ({"rules": [{"label": "x", "color": "red"}]}, "#rrggbb"),
    ({"rules": [{"label": "x"}], "approach": {"from": ["y"], "to": ["x"], "label": "z"}}, "규칙에 없는 라벨 y"),
    ({"tracks": [{"track": "a", "rules": [{"label": "x"}]}, {"track": "a", "axis": "이동"}]}, "겹칩니다"),
    ({"params": {"gait": {"max_pauses": 1}}, "rules": [{"label": "x"}]}, "모르는 값 'max_pauses'"),
    ({"tracks": [{"axis": "손", "skip": ["쉼"]}]}, "손에 '쉼' 값은 없습니다"),
    ([1, 2], "맨 위"),
    # values that used to pass the check and fail later, or fail with Python's own words
    ({"params": [1], "rules": [{"label": "x"}]}, "params는"),
    ({"params": {"gait": {"max_pause": "abc"}}, "rules": [{"label": "x"}]}, "max_pause: 0 이상의 숫자"),
    ({"params": {"gait": {"max_pause": float("inf")}}, "rules": [{"label": "x"}]}, "max_pause: 0 이상의 숫자"),
    ({"params": {"gait": 3}, "rules": [{"label": "x"}]}, "params.gait"),
    ({"rules": [{"label": "x", "when": {"손": "뻗기"}, "then": {"손": "작업"}, "within": float("inf")}]}, "within"),
    ({"rules": [{"label": "x", "when": {"손": "뻗기"}, "then": {"손": "작업"}, "within": float("nan")}]}, "within"),
    ({"rules": [{"label": "x", "when": {"손": "뻗기"}, "then": {"손": "작업"}, "within": None}]}, "within"),
    ({"rules": [{"label": "x"}], "min_seg": "abc"}, "min_seg"),
    ({"rules": [{"label": "x"}], "min_seg": -1}, "min_seg"),
    ({"rules": [{"label": "x"}], "approach": {"from": ["x"], "to": ["x"], "label": "y", "steps": 0}}, "steps"),
    ({"rules": [{"label": "x"}], "approach": {"from": ["x"], "to": ["x"], "label": "y", "steps": 1.5}}, "steps"),
    ({"rules": [{"label": "x"}], "approach": {"from": ["x"], "to": ["x"], "label": "y", "max_gap": float("nan")}},
     "max_gap"),
    ({"rules": [{"label": "x"}], "approach": {"from": [], "to": ["x"], "label": "y"}}, "from"),
    ({"tracks": [{"axis": "손", "rules": [{"label": "x"}]}]}, "axis 레인에는 rules"),
    ({"tracks": [{"rules": [{"label": "x"}], "skip": ["휴지"]}]}, "skip은 axis 레인에만"),
    ({"tracks": [{"track": ["a"], "rules": [{"label": "x"}]}]}, "track"),
])
def test_rule_files_say_what_is_wrong(data, why):
    with pytest.raises(rules.RuleError, match=why):
        rules.check(data)


def test_a_label_given_as_text_where_a_list_goes():
    rs = rules.check({"rules": [{"label": "걷기", "when": {"걸음": "걸음 중"}}, {"label": "손", "when": {"손": "뻗기"}}],
                      "approach": {"from": "걷기", "to": "손", "label": "접근"}})
    assert rs["tracks"][0]["approach"]["from"] == ["걷기"]


def test_a_labels_name_and_color_come_from_any_of_its_rules():
    rs = rules.check({"rules": [{"label": "reach", "color": "#ff0000", "when": {"왼손": "뻗기"}},
                                {"label": "reach", "name": "손 뻗기", "when": {"오른손": "뻗기"}}, {"label": "rest"}]})
    tr = _tracks(왼손=["뻗기", "휴지", "휴지"], 오른손=["휴지", "뻗기", "휴지"])
    got = {lab: meta for _, lab, _, _, meta in rules.apply(rs, tr, [])}
    assert got["reach"] == {"name": "손 뻗기", "color": "#ff0000"}


def test_rule_files_in_cp949_and_parse_errors_without_their_text(tmp_path):
    p = tmp_path / "excel.yaml"
    p.write_bytes("rules:\n  - {label: 서기}\n".encode("cp949"))
    assert rules.load(str(p))["tracks"][0]["rules"][0]["label"] == "서기"
    p = tmp_path / "secret.yaml"
    p.write_text("rules:\n  - {label: secret_label_A, when: {이동: [걷기\n", encoding="utf-8")
    with pytest.raises(rules.RuleError) as e:
        rules.load(str(p))
    assert "secret_label_A" not in str(e.value) and "행" in str(e.value)  # where, not what (private rules)
    p = tmp_path / "secret.json"
    p.write_text('{"rules": [{"label": "secret_label_A",}]}', encoding="utf-8")
    with pytest.raises(rules.RuleError) as e:
        rules.load(str(p))
    assert "secret_label_A" not in str(e.value) and "JSON" in str(e.value)


def test_too_short_and_unexpected_failures_come_back_as_the_error(monkeypatch):
    for frames in (1, 2, 3, 4):  # 120 fps: under a 30 fps frame
        short = _reach()
        short.positions, short.fps = short.positions[:frames], 120.0
        lab = autolabel.label_motion(short, RULES)
        assert "너무 짧습니다" in lab.error and not lab.segments, frames
    short.positions = _reach().positions[:9]  # 9 frames at 120 fps: 3 at 30 fps, enough to run
    assert not autolabel.label_motion(short, RULES).error

    def broken(*a):
        raise IndexError("deep inside")

    monkeypatch.setattr(segment, "tracks", broken)
    lab = autolabel.label_motion(_reach(), RULES)  # never raises (window, API, CLI and scripts alike)
    assert lab.error == "자동 라벨 계산 중 오류: IndexError: deep inside" and lab.auto == "시험"


def test_a_treadmill_foot_is_still_on_the_belt():
    """Feet standing on a belt move with it: the toe joint's height is found in the belt's frame."""
    h = _reach()
    t = np.arange(len(h.positions)) / FPS
    for name in ("left_ankle", "right_ankle", "left_foot", "right_foot"):
        h.positions[:, SMPL.index(name), 0] -= 1.0 * t  # 1 m/s backwards
    P, dims, notes = body.prepare(h)
    assert not any("멈춰 있는 순간이 없어" in n for n in notes)
    assert dims["h_toe"] == pytest.approx(dims["h_ankle"] - 0.05, abs=1e-6)


def test_cli_label_files_do_not_overwrite_each_other(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    import retlens_cli

    files = [str(tmp_path / "rub001" / "take.bvh"), str(tmp_path / "rub002" / "take.bvh"),
             str(tmp_path / "rub002" / "take.c3d"), str(tmp_path / "rub002" / "other.bvh")]
    out = str(tmp_path / "out")
    names = retlens_cli._label_csv_names(files, out)
    assert len(set(names.values())) == 4
    assert names[files[0]] == os.path.join(out, "rub001", "take.labels.csv")
    assert names[files[1]] == os.path.join(out, "rub002", "bvh", "take.labels.csv")  # X.bvh and X.c3d in one folder
    assert names[files[2]] == os.path.join(out, "rub002", "c3d", "take.labels.csv")
    assert names[files[3]] == os.path.join(out, "other.labels.csv")
    for f in files[:2]:  # two real motions of the same name: two label files
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as fh:
            fh.write(walking_bvh_text(seconds=1.0))
    rules_file = tmp_path / "r.yaml"
    rules_file.write_text("rules:\n  - {label: x}\n", encoding="utf-8")
    res = retlens_cli.autolabel(types.SimpleNamespace(files=files[:2], rules=str(rules_file), out=out, summary=True))
    assert [os.path.isfile(r["csv"]) for r in res["motions"]] == [True, True]
    assert res["motions"][0]["csv"] != res["motions"][1]["csv"]


def test_rule_files_on_disk_and_the_example(tmp_path):
    ex = rules.load(autolabel.EXAMPLE)
    assert ex["name"] and [t["track"] for t in ex["tracks"]][:1] == ["동작"]
    assert rules.check({"rules": [{"label": "x", "when": {"자세": "선 자세→앉음"}}]})  # posture changes are values too
    p = tmp_path / "r.yaml"
    p.write_text("rules:\n  - {label: x, when: {이동: [걷기\n", encoding="utf-8")
    lab = autolabel.label_motion(_reach(), str(p))
    assert lab.error.startswith("읽지 못함") and lab.auto == "r" and lab.path == str(p)
    p = tmp_path / "r.json"
    p.write_text('{"rules": [{"label": "서기"}]}', encoding="utf-8")
    lab = autolabel.label_motion(_reach(), str(p))
    assert [s.label for s in lab.segments] == ["서기"] and lab.auto == "r"


def test_labels_save_and_read_back(tmp_path):
    lab = autolabel.label_motion(_reach(), RULES)
    p = motion_labels.save_csv(lab, str(tmp_path / "reach.labels.csv"))
    back = motion_labels.load(p, str(tmp_path / "reach.bvh"), 30.0)
    assert not back.error and [(s.track, s.label, round(s.start, 3), round(s.end, 3), s.color) for s in back.segments] == \
        [(s.track, s.label, round(s.start, 3), round(s.end, 3), s.color) for s in lab.segments]
    assert lab.summary(segments=False)["auto"] == "시험" and back.summary()["auto"] is None


# ---------------------------------------------------------------- synthetic bodies for the movement tracks
G = 9.81


def _ik(a, c, l1, l2, bend):
    """Middle joint of a two-link chain from a to c (T, 3), bent toward the direction bend."""
    d = c - a
    L = np.minimum(np.linalg.norm(d, axis=1, keepdims=True), l1 + l2 - 1e-6)
    u = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-12)
    x = (l1 ** 2 - l2 ** 2 + L ** 2) / (2 * L)
    bend = np.asarray(bend, float)
    perp = bend - (u @ bend)[:, None] * u
    perp /= np.linalg.norm(perp, axis=1, keepdims=True) + 1e-12
    return a + x * u + np.sqrt(np.maximum(l1 ** 2 - x ** 2, 0)) * perp


def _joints(pelvis, ank_l, ank_r, trunk=(0, 0, 1), wrists=None, knees=None, bend=(1, 0, 0)):
    """(T, 17, 3) SMPL-named joints (m, Z up, facing +X) from pelvis and ankle tracks: thigh and shank 0.41 m
    (stature 1.67 m), knees bent toward `bend` (or given), feet flat ahead of the ankles, the trunk along
    `trunk`, arms hanging relaxed (elbows a little bent) unless wrists = (left, right) are given."""
    T = len(pelvis)
    up = np.asarray(trunk, float) / np.linalg.norm(trunk)
    side = np.array([0.0, 1.0, 0.0])
    J = {"pelvis": pelvis, "left_ankle": ank_l, "right_ankle": ank_r, "spine3": pelvis + 0.40 * up,
         "head": pelvis + 0.65 * up}
    for i, (s, sgn, ank) in enumerate((("left", 1, ank_l), ("right", -1, ank_r))):
        J[f"{s}_hip"] = pelvis + sgn * 0.09 * side - 0.05 * up
        J[f"{s}_knee"] = knees[i] if knees is not None else _ik(J[f"{s}_hip"], ank, 0.41, 0.41, bend)
        J[f"{s}_foot"] = ank + (0.13, 0, -0.05)
        sh = J["spine3"] + 0.10 * up + sgn * 0.18 * side
        w = wrists[i] if wrists is not None else sh - 0.50 * up + (0.08, 0, 0)
        J[f"{s}_shoulder"], J[f"{s}_wrist"] = sh, np.broadcast_to(w, (T, 3)).astype(float)
        J[f"{s}_elbow"] = _ik(sh, J[f"{s}_wrist"], 0.28, 0.25, (-1, 0, 0))
    return np.stack([np.broadcast_to(J[n], (T, 3)) for n in SMPL], 1).astype(float)


def _body(*a, **kw):
    return SkeletonMotion("synth", SMPL, np.full(len(SMPL), -1), _joints(*a, **kw), FPS)


def _feet(t, contacts, side, lift=0.1, belt=0.0):
    """An ankle track (T, 3): standing at (x, z) over each contact (x, z, t0, t1[, belt]), carried back by a
    belt (m/s) meanwhile, swinging in a raised arc between contacts; still before the first and after the last."""
    out = np.zeros((len(t), 3))
    out[:, 1] = side
    cs = sorted(contacts, key=lambda c: c[2])
    end = []
    for i, c in enumerate(cs):
        x, z, t0, t1 = c[:4]
        v = c[4] if len(c) > 4 else belt
        m = (t >= t0) & (t <= t1)
        out[m, 0], out[m, 2] = x - v * (t[m] - t0), z + 0.08
        end.append(x - v * (t1 - t0))
        if i + 1 < len(cs):
            x2, z2, s0 = cs[i + 1][:3]
            m = (t > t1) & (t < s0)
            u = (t[m] - t1) / (s0 - t1)
            out[m, 0] = end[-1] + (x2 - end[-1]) * (0.5 - 0.5 * np.cos(np.pi * u))
            out[m, 2] = 0.08 + z + (z2 - z) * u + lift * np.sin(np.pi * u)
    m = t < cs[0][2]
    out[m, 0], out[m, 2] = cs[0][0], cs[0][1] + 0.08
    m = t > cs[-1][3]
    out[m, 0], out[m, 2] = end[-1], cs[-1][1] + 0.08
    return out


def _engine(h, overrides=None):
    P, dims, _ = body.prepare(h)
    f, _, _ = signals.from_joints(P, dims)
    return segment.tracks(f, dims, segment.params(overrides))[0]


def _share(lab, values, a=0.0, b=None):
    """Fraction of the frames from a to b (s) whose label is one of values."""
    x = lab[int(a * FPS):None if b is None else int(b * FPS)]
    return float(np.isin(x, [values] if isinstance(values, str) else values).mean())


def _run(flights, v=3.5, stance=0.12, start=0.0, end=None, slide=0.0):
    """Running: a stance of `stance` s and then each flight in turn (s), feet alternating; the pelvis falls
    freely in the flights and dips 3 cm in the stances. Cut to start..end (s)."""
    t0s = np.concatenate([[0.0], np.cumsum([stance + d for d in flights])])
    end = t0s[-1] if end is None else end
    t = np.arange(start, end, 1 / FPS)
    feet = {0: [], 1: []}
    for k, t0 in enumerate(t0s):
        feet[k % 2].append((v * (t0 + stance / 2), 0.0, t0, t0 + stance, -slide))
    z = np.full(len(t), 0.95)
    for t0, d in zip(t0s, flights):
        m = (t >= t0) & (t < t0 + stance)
        z[m] = 0.95 - 0.03 * np.sin(np.pi * (t[m] - t0) / stance)
        tau = t - t0 - stance
        m = (tau >= 0) & (tau < d)
        z[m] = 0.95 + G * d / 2 * tau[m] - G / 2 * tau[m] ** 2
    pel = np.stack([v * t, np.zeros(len(t)), z], 1)
    return _body(pel, _feet(t, feet[0], 0.09, lift=0.25), _feet(t, feet[1], -0.09, lift=0.25))


def _walk(n, swing, pause, step=0.3, start=0.5, rest=1.0, belt=0.0, standing=None):
    """Walking n alternating steps (left first) of `step` m ahead of the other foot, each swing `swing` s and
    `pause` s between a strike and the next lift; the pelvis over the feet. standing: seconds still first."""
    lead = standing or 0.0
    T = int((lead + start + n * (swing + pause) + rest) * FPS)
    t = np.arange(T) / FPS
    feet = {0: [(0.0, 0.0, -1.0, lead + start, 0.0)], 1: [(0.0, 0.0, -1.0, lead + start + swing + pause, 0.0)]}
    x = {0: 0.0, 1: 0.0}
    for i in range(n):
        s = i % 2
        lift = lead + start + i * (swing + pause)
        x[s] = x[1 - s] + step if belt == 0 else step
        nxt = lead + start + (i + 2) * (swing + pause)
        feet[s].append((x[s], 0.0, lift + swing, nxt if i + 2 < n else t[-1] + 1, belt))
    ank_l, ank_r = _feet(t, feet[0], 0.09, belt=belt), _feet(t, feet[1], -0.09, belt=belt)
    pel = np.stack([(ank_l[:, 0] + ank_r[:, 0]) / 2, np.zeros(T), np.full(T, 0.95)], 1)
    return _body(pel, ank_l, ank_r)


def test_a_jump_needs_the_feet_off_and_the_pelvis_falling():
    T = int(5 * FPS)
    t = np.arange(T) / FPS
    d = 0.4
    tau = t - 1.5
    rise = np.where((tau >= 0) & (tau <= d), G * d / 2 * tau - G / 2 * tau ** 2, 0.0)
    feet = lambda y: np.stack([np.zeros(T), np.full(T, y), 0.08 + rise], 1)
    loco = _engine(_body(np.stack([np.zeros(T), np.zeros(T), 0.95 + rise], 1), feet(0.09), feet(-0.09)))["이동"]
    assert loco[int(1.7 * FPS)] == "점프" and _share(loco, "정지", 0, 1.0) == 1 and _share(loco, "정지", 3.0) == 1
    jump = segment.runs(loco == "점프")
    assert len(jump) == 1 and jump[0][0] >= 1.0 * FPS and jump[0][1] <= 2.4 * FPS  # not widened by a second each side
    # seated, the feet lifted off the floor and kicked (0.5 s, then 1.5 s): the pelvis rests on the seat
    lift = np.zeros(T)
    for a, b in ((1.0, 1.5), (2.5, 4.0)):
        u = np.clip((t - a) / (b - a), 0, 1)
        lift += np.where((t > a) & (t < b), 0.25 * np.sin(np.pi * u), 0.0)
    kick = lambda y, ph: np.stack([0.35 + 0.1 * np.sin(2 * np.pi * 2 * t + ph) * (lift > 0), np.full(T, y), 0.08 + lift], 1)
    seated = _body(np.tile([-0.1, 0.0, 0.6], (T, 1)), kick(0.09, 0), kick(-0.09, np.pi))
    assert not np.isin(_engine(seated)["이동"], ["점프", "매달림", "달리기"]).any()


def test_lying_flat_is_lying_and_legs_in_the_air_are_not_hanging():
    T = int(4 * FPS)
    t = np.arange(T) / FPS
    kick = lambda ph: np.where((t > 1) & (t < 3), 0.3 * (0.5 - 0.5 * np.cos(2 * np.pi * (t - 1) + ph)), 0.0)
    legs = lambda y, ph: np.stack([np.full(T, 0.82), np.full(T, y), 0.08 + kick(ph)], 1)
    arms = (np.array([0.0, 0.3, 0.04]), np.array([0.0, -0.3, 0.04]))  # on the floor along the body
    lying = _body(np.tile([0.0, 0.0, 0.12], (T, 1)), legs(0.09, 0), legs(-0.09, np.pi / 2), trunk=(-1, 0, 0),
                  wrists=arms, bend=(0, 0, 1))
    tr = _engine(lying)
    assert _share(tr["자세"], "누움") > 0.8 and not (tr["자세"] == "네발 자세").any()
    assert not np.isin(tr["이동"], ["점프", "매달림"]).any()
    lab = autolabel.label_motion(lying, autolabel.EXAMPLE)
    assert _at(lab, "동작", 2.0) == "누워 있기"  # lying is not 'standing' in the example rules
    # on hands and knees: the thighs hold the pelvis up over the knees
    knees = (np.tile([0.05, 0.09, 0.06], (T, 1)), np.tile([0.05, -0.09, 0.06], (T, 1)))
    fours = _body(np.tile([0.0, 0.0, 0.5], (T, 1)), np.tile([0.45, 0.09, 0.08], (T, 1)), np.tile([0.45, -0.09, 0.08], (T, 1)),
                  trunk=(-1, 0, 0), wrists=(np.array([-0.5, 0.2, 0.04]), np.array([-0.5, -0.2, 0.04])), knees=knees)
    assert _share(_engine(fours)["자세"], "네발 자세") > 0.8


def test_short_runs_are_running_and_a_leap_stands_out_of_the_run():
    # 1.25 s of a bounding run (0.3 s flights): steps cut by the clip's ends count, strides are not leaps
    loco = _engine(_run([0.3] * 6, start=0.9, end=2.15))["이동"]
    assert _share(loco, "달리기") > 0.7 and not (loco == "점프").any()
    # one 0.6 s flight among them is a leap
    loco = _engine(_run([0.3, 0.3, 0.3, 0.6, 0.3, 0.3, 0.3], start=0.5))["이동"]
    leap, stride = 4 * 0.12 + 3 * 0.3 + 0.3, 6 * 0.12 + 4 * 0.3 + 0.6 + 0.15  # the middles of the long and a later flight
    assert loco[int((leap - 0.5) * FPS)] == "점프" and loco[int((stride - 0.5) * FPS)] == "달리기"


def test_a_slow_walk_with_long_double_support_is_walking():
    loco = _engine(_walk(7, swing=0.4, pause=0.7))["이동"]  # 0.27 m/s, 0.7 s between a strike and the next lift
    assert _share(loco, "걷기", 1.0, 7.5) > 0.9 and not (loco == "발 옮기기").any()


def test_stairs_up_to_a_platform_and_knees_raised_in_place():
    T = int(7 * FPS)
    t = np.arange(T) / FPS
    ank_l = _feet(t, [(0.0, 0.0, -1, 1.0), (0.3, 0.17, 1.4, 2.0), (0.9, 0.51, 2.4, 3.0), (1.2, 0.51, 3.4, 9)], 0.09)
    ank_r = _feet(t, [(0.0, 0.0, -1, 1.5), (0.6, 0.34, 1.9, 2.5), (1.2, 0.51, 2.9, 9)], -0.09)
    pel = np.stack([(ank_l[:, 0] + ank_r[:, 0]) / 2, np.zeros(T), 0.95 + (ank_l[:, 2] + ank_r[:, 2]) / 2 - 0.08], 1)
    tr = _engine(_body(pel, ank_l, ank_r))  # most of the standing is on the platform, the walk starts below it
    assert (tr["이동"] == "계단 오르기").any() and not (tr["자세"] == "무릎 꿇기").any()
    # knees raised high in turn and held, the feet put back where they were: not stairs, not a walk
    T = int(8.5 * FPS)
    t = np.arange(T) / FPS
    feet = {0: np.tile([0.0, 0.09, 0.08], (T, 1)), 1: np.tile([0.0, -0.09, 0.08], (T, 1))}
    for k in range(6):
        a = 1.0 + 1.2 * k
        up = np.clip((t - a) / 0.3, 0, 1) - np.clip((t - a - 0.6) / 0.3, 0, 1)
        feet[k % 2][:, 0] += 0.15 * up
        feet[k % 2][:, 2] += 0.4 * up
    loco = _engine(_body(np.tile([0.0, 0.0, 0.95], (T, 1)), feet[0], feet[1]))["이동"]
    assert set(loco) <= {"정지", "발 옮기기"} and (loco == "발 옮기기").any()


def _pose_blend(a, b, t, t0, t1):
    w = np.clip((t - t0) / (t1 - t0), 0, 1)[:, None, None]
    return (1 - w) * a + w * b


def test_a_high_stool_is_sitting_and_hands_on_the_lap_hold_nothing():
    T = int(7 * FPS)
    t = np.arange(T) / FPS
    one = lambda v: np.tile(v, (T, 1)).astype(float)
    stand = _joints(one([0.0, 0, 0.95]), one([0.0, 0.09, 0.08]), one([0.0, -0.09, 0.08]))
    hip = lambda y: np.array([-0.1, y, 0.83])
    knees = (one(hip(0.09) + (0.41, 0, 0)), one(hip(-0.09) + (0.41, 0, 0)))  # thighs level on the seat
    seat = _joints(one([-0.1, 0, 0.88]), one(hip(0.09) + (0.41, 0, -0.41)), one(hip(-0.09) + (0.41, 0, -0.41)),
                   knees=knees, wrists=(np.array([0.2, 0.12, 0.95]), np.array([0.2, -0.12, 0.95])))
    h = SkeletonMotion("stool", SMPL, np.full(len(SMPL), -1), _pose_blend(stand, seat, t, 2.5, 3.5), FPS)
    tr = _engine(h)  # feet on a rung 0.34 m up, pelvis 0.94 of its standing height
    assert _share(tr["자세"], "앉음", 4.5, 6.5) > 0.9
    assert _share(tr["양손"], "없음", 4.0) == 1 and _share(tr["손"], "휴지", 4.5, 6.5) == 1
    assert _at(autolabel.label_motion(h, autolabel.EXAMPLE), "동작", 5.0) == "앉아 있기"


def test_holding_needs_forearms_ahead_and_the_hands_abreast():
    T = int(4 * FPS)
    t = np.arange(T) / FPS
    one = lambda v: np.tile(v, (T, 1)).astype(float)
    still = (one([0.0, 0, 0.95]), one([0.0, 0.09, 0.08]), one([0.0, -0.09, 0.08]))
    assert _share(_engine(_body(*still))["양손"], "없음") == 1  # relaxed arms hanging at the sides
    box = (np.array([0.3, 0.17, 1.15]), np.array([0.3, -0.17, 1.15]))
    assert _share(_engine(_body(*still, wrists=box))["양손"], "들기", 1.0, 3.0) == 1
    swing = 0.1 * np.sin(2 * np.pi * t)[:, None] * [1, 0, 0]  # forearms ahead, swinging in turn as in a run
    arms = (np.array([0.3, 0.2, 1.15]) + swing, np.array([0.3, -0.2, 1.15]) - swing)
    assert _share(_engine(_body(*still, wrists=arms))["양손"], "없음") == 1


def test_a_treadmill_belt_is_found_where_it_runs_and_not_in_short_runs():
    # 3 s standing on a stopped belt, then walking on it at 1.2 m/s: feet carried back, the pelvis in place
    h = _walk(12, swing=0.4, pause=0.15, step=0.33, start=0.0, standing=3.0, belt=1.2)
    P, dims, _ = body.prepare(h)
    belt = signals.support_velocity(P, dims)
    assert not belt[:int(2 * FPS)].any() and belt[int(6 * FPS), 0] == pytest.approx(-1.2, abs=0.15)
    loco = _engine(h)["이동"]
    assert not np.isin(loco, ["매달림", "점프"]).any() and _share(loco, "걷기", 4.0, 8.0) > 0.7
    assert any("트레드밀" in n for n in autolabel.label_motion(h, RULES).notes)
    # running over the ground for 3 s with the standing feet slipping 0.3 m/s: the body passes the feet
    P, dims, _ = body.prepare(_run([0.15] * 11, slide=0.3))
    assert not signals.support_velocity(P, dims).any()


def test_a_skeleton_without_toes_is_labelled_like_one_with_toes(tmp_path):
    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=6.0))
    human = load_bvh(str(p))
    keep = [i for i, n in enumerate(human.joint_names) if "Toe" not in n]
    remap = {o: i for i, o in enumerate(keep)}
    toeless = SkeletonMotion("walk", [human.joint_names[i] for i in keep],
                             np.array([remap.get(int(human.parents[i]), -1) for i in keep]), human.positions[:, keep],
                             human.fps)
    lab = autolabel.label_motion(toeless, {"tracks": [{"axis": "이동"}]})
    assert not lab.error and any("발끝 관절이 없어" in n for n in lab.notes)
    a, b = _engine(human)["이동"], _engine(toeless)["이동"]
    assert (a == b).mean() > 0.9


def test_a_trunk_near_the_bend_threshold_does_not_flicker():
    trunk = np.array([10, 21, 17, 19, 14, 16, 22, 18], float)  # bent from 20 deg, straight again under 15
    assert segment.hysteresis(trunk, 20, 15).tolist() == [False, True, True, True, False, False, True, True]


def test_posture_change_kinds():
    k = segment.transition_kind
    assert [k("선 자세", "앉음"), k("앉음", "선 자세"), k("누움", "선 자세"), k("네발 자세", "허리 굽힘")] == ["앉기"] + ["일어서기"] * 3
    assert [k("선 자세", "쪼그림"), k("쪼그림", "선 자세"), k("무릎 꿇기", "선 자세"), k("허리 굽힘", "선 자세")] == \
        ["낮추기", "높이기", "높이기", "높이기"]


def test_steps_group_into_walks():
    g = segment.params()["gait"]
    step = lambda foot, lift, strike, dx=0.3: {"foot": foot, "lift": lift, "strike": strike, "dx": dx, "dy": 0.0}
    slow = [step("lr"[i % 2], 33 * i, 33 * i + 12) for i in range(3000)]  # 0.7 s between a strike and the next lift
    assert [len(b) for b in segment.bouts(slow, g)] == [3000]
    same_foot = [step("l", 0, 12), step("l", 33, 45)]
    back = [step("l", 0, 12), step("r", 33, 45, dx=-0.3)]
    assert len(segment.bouts(same_foot, g)) == 2 and len(segment.bouts(back, g)) == 2
    assert len(segment.bouts([step("l", 0, 12), step("l", 20, 32)], g)) == 1  # within max_pause: the same walk


def test_body_model_sizes_read_the_model_once(tmp_path):
    rng = np.random.default_rng(0)
    v = rng.normal(size=(30, 3)) * 0.3
    v[:, 1] = np.linspace(0, 1.7, 30)
    path = str(tmp_path / "model.npz")
    np.savez(path, v_template=v, shapedirs=rng.normal(size=(30, 3, 16)) * 0.01,
             J_regressor=np.abs(rng.normal(size=(22, 30))))
    body._model.cache_clear()
    a = body.dims_from_model(path, np.zeros(10))
    b = body.dims_from_model(path, np.ones(16))
    assert body._model.cache_info().misses == 1 and a["stature"] != b["stature"]


def test_rule_file_mistakes_are_errors(tmp_path):
    """Keys written twice, lane keys at the top next to tracks, numbers too big to apply: errors, not
    rules that silently do something else. A YAML error names no text of the file (rules may be private)."""
    def load(text, ext=".yaml"):
        p = tmp_path / f"r{ext}"
        p.write_text(text, encoding="utf-8")
        return rules.load(str(p))

    with pytest.raises(rules.RuleError, match="두 번"):
        load("tracks:\n  - {track: a, rules: [{label: x}]}\ntracks:\n  - {track: b, rules: [{label: y}]}\n")
    with pytest.raises(rules.RuleError, match="두 번"):
        load("rules:\n  - label: x\n    when: {왼손: 뻗기}\n    when: {오른손: 뻗기}\n")
    with pytest.raises(rules.RuleError, match="두 번"):
        load('{"rules": [{"label": "x"}], "rules": []}', ".json")
    with pytest.raises(rules.RuleError, match="맨 위"):
        rules.check({"tracks": [{"track": "a", "rules": [{"label": "x"}]}], "min_seg": 0.3})
    for bad in ({"rules": [{"label": "x"}], "min_seg": 1e308},
                {"rules": [{"label": "x", "when": {"이동": "걷기"}, "then": {"손": "뻗기"}, "within": 1e9}]},
                {"rules": [{"label": "x"}], "params": {"gait": {"max_pause": 1e308}}}):
        with pytest.raises(rules.RuleError):
            rules.check(bad)
    with pytest.raises(rules.RuleError, match="자세"):
        rules.check({"rules": [{"label": "x", "when": {"자세": "선 자세→선 자세"}}]})  # never happens
    assert rules.check({"rules": [{"label": 0}]})["tracks"][0]["rules"][0]["label"] == "0"
    with pytest.raises(rules.RuleError) as e:
        load("rules:\n  - {label: *secret_name_A7}\n")
    assert "secret_name_A7" not in str(e.value) and "2행" in str(e.value)


def test_min_seg_keeps_unlabelled_frames_and_within_zero_and_shared_colors():
    """min_seg merges labelled pieces only: unlabelled frames neither swallow a short label nor get
    filled. within 0 looks only while when holds. A label's color holds in every lane."""
    T = 60
    loco = np.full(T, "정지", dtype=object)
    loco[10:16] = "점프"  # 0.2 s between unlabelled stretches: kept
    loco[30:45] = "걷기"
    loco[47:60] = "걷기"  # a 2-frame unlabelled gap between walks: not filled
    rs = rules.check({"rules": [{"label": "jump", "when": {"이동": "점프"}}, {"label": "walk", "when": {"이동": "걷기"}}],
                      "min_seg": 0.3})
    got = [(lab, s, e) for _, lab, s, e, _ in rules.apply(rs, _tracks(이동=loco), [])]
    assert got == [("jump", 10, 16), ("walk", 30, 45), ("walk", 47, 60)]
    kind = np.full(T, "없음", dtype=object)
    kind[10:20] = "낮추기"
    hand = np.full(T, "휴지", dtype=object)
    hand[20:30] = "뻗기"  # starts on the first frame after the crouch
    rs = rules.check({"rules": [{"label": "reach", "when": {"자세전환": "낮추기"}, "then": {"손": "뻗기"}, "within": 0}]})
    assert rules.apply(rs, _tracks(자세전환=kind, 손=hand), []) == []
    rs = rules.check({"tracks": [{"track": "a", "axis": "이동"},
                                 {"track": "b", "rules": [{"label": "걷기", "when": {"이동": "걷기"}, "color": "#ff0000"}]},
                                 {"track": "c", "rules": [{"label": "걷기", "when": {"이동": "걷기"}}]}]})
    colors = {lane: m.get("color") for lane, lab, s, e, m in rules.apply(rs, _tracks(이동=loco), []) if lab == "걷기"}
    assert colors == {"a": "#ff0000", "b": "#ff0000", "c": "#ff0000"}
