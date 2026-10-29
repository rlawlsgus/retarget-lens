"""Labelled time segments of a motion (retlens/motion_labels.py): a motion may have a label file or
not; the ones it has are read whatever their time columns, tracks or encoding, and a broken one is
reported instead of stopping the motion."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import motion_labels as ml  # noqa: E402

FPS, DUR = 30.0, 4.0  # the motion the labels are for: 120 frames @ 30 fps


def _write(path, text, encoding="utf-8"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)
    return str(path)


def _motion(tmp_path, name="02_01.bvh"):
    return _write(tmp_path / "motions" / name, "HIERARCHY")


def test_a_motion_without_labels_has_none(tmp_path):
    src = _motion(tmp_path)
    _write(tmp_path / "motions" / "02_03.labels.csv", "label,start_s,end_s\nwalk,0,1\n")  # another motion's
    assert ml.load_for(src, FPS, DUR) is None


def test_sidecar_in_seconds(tmp_path):
    src = _motion(tmp_path)
    _write(tmp_path / "motions" / "02_01.labels.csv",
           "label,name,start_s,end_s\nidle,대기,0,0.5\nwalk,걷기,0.5,2.5\nreach,손 뻗기,3.0,4.0\n")
    lab = ml.load_for(src, FPS, DUR)
    assert lab.path.endswith("02_01.labels.csv") and not lab.error and not lab.notes
    assert [(s.label, s.start, s.end, s.name) for s in lab.segments] == [
        ("idle", 0.0, 0.5, "대기"), ("walk", 0.5, 2.5, "걷기"), ("reach", 3.0, 4.0, "손 뻗기")]
    assert lab.tracks == [""]
    assert [s.label for s in lab.at(1.0)] == ["walk"] and lab.at(2.7) == []  # a gap stays unlabelled
    assert lab.at(0.5)[0].label == "walk"  # end exclusive
    assert lab.text_at(1.0) == "walk" and lab.text_at(2.7) == ""  # what the 3D view shows over the robot
    js = lab.summary(t=3.5)
    assert js["now"] == [{"track": "", "label": "reach"}] and js["count"] == 3 and len(js["segments"]) == 3
    assert "segments" not in lab.summary(segments=False)


def test_frames_end_inclusive_at_the_rows_or_the_motions_fps(tmp_path):
    src = _motion(tmp_path)
    p = _write(tmp_path / "a.csv", "label,start_frame,end_frame,fps\nwalk,0,59,30\nturn,120,239,60\n")
    assert [(s.start, s.end) for s in ml.load(p, src, FPS, DUR).segments] == [(0.0, 2.0), (2.0, 4.0)]
    p = _write(tmp_path / "b.csv", "label,start_frame,end_frame\nwalk,30,59\n")  # no fps: the motion's
    assert [(s.start, s.end) for s in ml.load(p, src, FPS, DUR).segments] == [(1.0, 2.0)]


def test_a_labellers_table_of_many_motions_with_tracks(tmp_path):
    """A batch output: seq names the motion, track splits lanes, start_s wins over the frame columns."""
    src = _motion(tmp_path, "02_01_stageii.npz")
    table = ("seq,subset,track,label,start_frame,end_frame,start_s,end_s,dur_s,src_fps,src_start_frame,src_end_frame,attrs\n"
             "CMU/02/02_01_stageii.npz,CMU,이동,정지,0,14,0.0,0.5,0.5,120.0,0,59,\n"
             "CMU/02/02_01_stageii.npz,CMU,이동,걷기,15,89,0.5,3.0,2.5,120.0,60,359,\"{\"\"steps\"\": 4}\"\n"
             "CMU/02/02_01_stageii.npz,CMU,왼손,뻗기,30,44,1.0,1.5,0.5,120.0,120,179,\n"
             "CMU/02/02_02_stageii.npz,CMU,이동,달리기,0,29,0.0,1.0,1.0,120.0,0,119,\n")
    _write(tmp_path / "motions" / "labels.csv", table)  # a folder table: rows picked by seq
    lab = ml.load_for(src, FPS, DUR)
    assert lab is not None and lab.tracks == ["이동", "왼손"]
    assert [(s.track, s.label) for s in lab.segments] == [("이동", "정지"), ("이동", "걷기"), ("왼손", "뻗기")]
    assert [(s.track, s.label) for s in lab.at(1.2)] == [("이동", "걷기"), ("왼손", "뻗기")]
    assert lab.text_at(1.2) == "이동: 걷기 · 왼손: 뻗기" and lab.text_at(3.5) == ""
    other = _motion(tmp_path, "05_01_stageii.npz")
    assert ml.load_for(other, FPS, DUR) is None  # a folder table without this motion is not its label file
    picked = ml.load(str(tmp_path / "motions" / "labels.csv"), other, FPS, DUR)  # picked by hand: says why
    assert not picked.segments and "05_01_stageii" in picked.error


def test_the_same_name_in_two_folders_goes_by_path(tmp_path):
    src = _write(tmp_path / "KIT" / "3" / "walk_01.npz", "x")
    p = _write(tmp_path / "t.csv", "seq,label,start_s,end_s\nCMU/1/walk_01.npz,a,0,1\nKIT/3/walk_01.npz,b,0,1\n")
    lab = ml.load(p, src, FPS, DUR)
    assert [s.label for s in lab.segments] == ["b"] and "2개" in lab.notes[0]


def test_json(tmp_path):
    src = _motion(tmp_path)
    _write(tmp_path / "motions" / "02_01.labels.json", json.dumps(
        {"fps": 60, "segments": [{"label": "carry", "start_frame": 0, "end_frame": 119, "track": "양손"},
                                 {"label": "place", "start_s": 2.0, "end_s": 3.0, "track": "양손", "color": "#ff0000"}]}))
    lab = ml.load_for(src, FPS, DUR)
    assert [(s.label, s.start, s.end) for s in lab.segments] == [("carry", 0.0, 2.0), ("place", 2.0, 3.0)]
    assert ml.color_for(lab.segments[1]) == (255, 0, 0)


def test_broken_files_say_why(tmp_path):
    src = _motion(tmp_path)
    cases = {"label 열이 없습니다": "start_s,end_s\n0,1\n", "시간 열이 없습니다": "label,begin\nwalk,0\n",
             "빈 파일": "", "읽지 못함": "{not json"}
    for i, (why, text) in enumerate(cases.items()):
        p = _write(tmp_path / f"bad{i}{'.json' if why == '읽지 못함' else '.csv'}", text)
        lab = ml.load(p, src, FPS, DUR)
        assert why in lab.error and not lab.segments, (why, lab.error)
    p = _write(tmp_path / "rows.csv", "label,start_s,end_s\nwalk,0,1\n,1,2\nturn,2,x\nback,3,2.5\n")
    lab = ml.load(p, src, FPS, DUR)
    assert [s.label for s in lab.segments] == ["walk"] and "3개" in lab.notes[0]  # bad rows skipped, said so


def test_cp949_and_bom(tmp_path):
    src = _motion(tmp_path)
    p = _write(tmp_path / "excel.csv", "label,start_s,end_s\n걷기,0,1\n", encoding="cp949")
    assert ml.load(p, src, FPS, DUR).segments[0].label == "걷기"
    p = _write(tmp_path / "bom.csv", "\ufefflabel,start_s,end_s\n잡기,0,1\n")
    assert ml.load(p, src, FPS, DUR).segments[0].label == "잡기"


def test_clipped_to_the_motion_and_overlaps_noted(tmp_path):
    src = _motion(tmp_path)
    p = _write(tmp_path / "c.csv", "label,start_s,end_s\na,0,2\nb,1.5,3\nc,3,4.0333\nd,3.5,6\ne,5,6\n")
    lab = ml.load(p, src, FPS, DUR)
    assert [(s.label, s.end) for s in lab.segments] == [("a", 2.0), ("b", 3.0), ("c", 4.0), ("d", 4.0)]
    clip = next(n for n in lab.notes if "모션 길이" in n)
    assert "1개 뺌" in clip and "1개 끝을 자름" in clip  # e dropped; d cut; c's one-frame rounding is quiet
    assert any("겹치는 구간 2곳" in n for n in lab.notes)  # a/b and c/d


def test_which_file_is_found_and_what_counts_as_a_label_file(tmp_path):
    src = _motion(tmp_path)
    sub = _write(tmp_path / "motions" / "02_01_subtask.csv", "label,start_s,end_s\nreach,0,1\n")
    assert ml.load_for(src, FPS, DUR).path == os.path.abspath(sub)
    first = _write(tmp_path / "motions" / "02_01.labels.csv", "label,start_s,end_s\nwalk,0,1\n")
    assert ml.load_for(src, FPS, DUR).path == os.path.abspath(first)  # .labels.csv before _subtask.csv
    c3d = _write(tmp_path / "markers" / "02_01.c3d", "x")  # a C3D: also next to its solved motion
    assert ml.load_for(c3d, FPS, DUR, also=[src]).path == os.path.abspath(first)

    assert ml.stem_of("x/02_01.labels.csv") == "02_01" and ml.stem_of("02_01_subtask.csv") == "02_01"
    assert ml.stem_of("walk.csv") == "walk"
    plain = _write(tmp_path / "plain.csv", "Label,Start_s,End_s\nwalk,0,1\n")
    unitree = _write(tmp_path / "walk.csv", "0.1,0.2,0.3\n0.1,0.2,0.3\n")
    assert ml.is_label_file(sub) and ml.is_label_file(plain) and not ml.is_label_file(unitree)
    assert not ml.is_label_file(str(tmp_path / "missing.csv"))


def test_each_label_keeps_its_own_color(monkeypatch):
    monkeypatch.setattr(ml, "_colors", {})
    segs = [ml.Segment(x, 0, 1) for x in ("walk", "reach", "walk", "grasp")]
    cols = [ml.color_for(s) for s in segs]
    assert cols[0] == cols[2] and len({cols[0], cols[1], cols[3]}) == 3


@pytest.mark.parametrize("name", ["02_01.labels.csv", "02_01_labels.json", "02_01_subtask.csv", "labels.csv"])
def test_label_names(name):
    assert ml.is_label_name(f"C:/data/{name}")
