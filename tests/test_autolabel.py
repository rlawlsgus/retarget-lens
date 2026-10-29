"""Automatic labels (retlens/autolabel): movement tracks from a skeleton, named by a rule file."""

import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import autolabel, motion_labels  # noqa: E402
from retlens.autolabel import body, rules, segment  # noqa: E402
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
    no_toes = [n for n in names if "Toe" not in n]  # the ankle has no child: nothing to stand for the toe
    keep = [names.index(n) for n in no_toes]
    remap = {o: i for i, o in enumerate(keep)}
    sk = SkeletonMotion("m", no_toes, np.array([remap.get(parents[o], -1) for o in keep]),
                        np.zeros((2, len(no_toes), 3)), 30.0)
    with pytest.raises(ValueError, match="발끝"):
        body.joint_index(sk)
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
    assert names[files[2]] == os.path.join(out, "rub002", "take.c3d.labels.csv")
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
