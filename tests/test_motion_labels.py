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


def test_rows_with_more_values_than_columns(tmp_path):
    """A trailing comma or a comma in a note without quotes: read, not an exception (window / API)."""
    src = _motion(tmp_path)
    p = _write(tmp_path / "a.csv", "label,start_s,end_s,note\nwalk,0,1,\nturn,1,2,left, then right\nback,2,3,x,\n")
    lab = ml.load(p, src, FPS, DUR)
    assert not lab.error and [(s.label, s.note) for s in lab.segments] == [
        ("walk", ""), ("turn", "left, then right"), ("back", "x")]  # an empty extra value is no extra
    assert any("마지막 열(note)에 이어 붙였습니다" in n for n in lab.notes)
    p = _write(tmp_path / "b.csv", "label,start_s,end_s\nwalk,0,1,,\nturn,1,2,9\n")  # no text column last: left out
    lab = ml.load(p, src, FPS, DUR)
    assert [(s.label, s.end) for s in lab.segments] == [("walk", 1.0), ("turn", 2.0)]
    assert any("1개: 넘친 값은 버렸습니다" in n for n in lab.notes)
    p = _write(tmp_path / "c.csv", "label,start_frame,end_frame\nwalk,0,inf\nturn,nan,3\nrun,-30,29\nlate,-60,-31\n")
    lab = ml.load(p, src, FPS, DUR)  # inf frames used to raise OverflowError
    assert [(s.label, s.start, s.end) for s in lab.segments] == [("run", 0.0, 1.0)]
    assert any("2개는 뺐습니다" in n for n in lab.notes) and any("1개 뺌, 1개 앞을 자름" in n for n in lab.notes)


def test_folder_tables_need_seq_and_say_when_broken(tmp_path):
    src = _motion(tmp_path)
    _motion(tmp_path, "02_02.bvh")
    table = _write(tmp_path / "motions" / "labels.csv", "label,start_s,end_s\nwalk,0,1\n")  # no seq: whose rows?
    lab = ml.load_for(src, FPS, DUR)
    assert lab is not None and "seq 열이 없습니다" in lab.error and not lab.segments  # ⚠ on the motion, not silence
    _write(table, "seq,start_s,end_s\n02_01,0,1\n")  # broken: no label column
    assert "label 열이 없습니다" in ml.load_for(src, FPS, DUR).error
    _write(table, "seq,label,start_s,end_s\n02_02,walk,0,1\n")  # fine, but not this motion's
    assert ml.load_for(src, FPS, DUR) is None
    assert ml.load(table, src, FPS, DUR, table=True) is None


def test_another_tools_labels_file_in_the_folder_is_passed_over(tmp_path):
    """labels.csv / labels.json are common names: one that is not a label table at all gives no ⚠."""
    src = _motion(tmp_path)
    foreign = _write(tmp_path / "motions" / "labels.csv", "name,age\nkim,3\n")
    assert ml.load_for(src, FPS, DUR) is None
    os.remove(foreign)
    _write(tmp_path / "motions" / "labels.json", json.dumps({"classes": ["walk", "run"], "version": 2}))
    assert ml.load_for(src, FPS, DUR) is None
    _write(tmp_path / "motions" / "labels.json", json.dumps({"segments": []}))  # a label table, empty: said
    assert "segments" in ml.load_for(src, FPS, DUR).error
    _write(tmp_path / "motions" / "02_01.labels.csv", "label,start_s,end_s\nwalk,0,1\n")
    lab = ml.load_for(src, FPS, DUR)
    assert lab.found and not ml.load(lab.path, src, FPS, DUR).found  # found next to it / picked


def test_saved_csv_reads_back_the_same(tmp_path):
    """Times are written in full: a boundary on frame k/30 rounded up would move that frame to the
    neighbouring segment when read back."""
    src = _motion(tmp_path)
    segs = [ml.Segment("ab"[k % 2], k / 30, (k + 1) / 30, track="이동", name="이름, 쉼표", note='따옴표 "x"',
                       color=(255, 0, 16)) for k in range(0, 119)]
    p = ml.save_csv(ml.MotionLabels(path="", segments=segs), str(tmp_path / "out.labels.csv"))
    back = ml.load(p, src, FPS, DUR).segments
    assert [(s.label, s.start, s.end, s.track, s.name, s.note, s.color) for s in back] == \
        [(s.label, s.start, s.end, s.track, s.name, s.note, s.color) for s in segs]


def test_a_file_of_another_motion_is_not_taken_whole(tmp_path):
    src = _motion(tmp_path)
    other = _write(tmp_path / "x.csv", "seq,label,start_s,end_s\nCMU/02/02_03_stageii.npz,walk,0,1\n")
    lab = ml.load(other, src, FPS, DUR)
    assert "이 모션(02_01)의 행이 없습니다" in lab.error and not lab.segments
    same = _write(tmp_path / "y.csv", "seq,label,start_s,end_s\nCMU/02/02_01_stageii.npz,walk,0,1\n,turn,1,2\n")
    lab = ml.load(same, src, FPS, DUR)  # the AMASS fit of the same take; rows without seq belong to it too
    assert not lab.error and [s.label for s in lab.segments] == ["walk", "turn"]
    _write(tmp_path / "motions" / "labels.csv", "seq,label,start_s,end_s\nCMU/02/02_01_stageii.npz,walk,0,1\n")
    assert [s.label for s in ml.load_for(src, FPS, DUR).segments] == ["walk"]  # a labeller's table next to BVHs


def test_a_c3d_finds_its_solved_motions_folder_table(tmp_path):
    solved = _write(tmp_path / "solved" / "take1.bvh", "HIERARCHY")
    c3d = _write(tmp_path / "markers" / "take1.c3d", "x")
    _write(tmp_path / "solved" / "labels.csv", "seq,label,start_s,end_s\ntake1,reach,0,1\ntake2,walk,0,1\n")
    assert ml.load_for(c3d, FPS, DUR) is None
    lab = ml.load_for(c3d, FPS, DUR, also=[solved])
    assert [s.label for s in lab.segments] == ["reach"]
    # a C3D named unlike its solved motion: its rows are found by the solved motion's name
    other = _write(tmp_path / "markers" / "session3_take1.c3d", "x")
    assert [s.label for s in ml.load_for(other, FPS, DUR, also=[solved]).segments] == ["reach"]
    table = str(tmp_path / "solved" / "labels.csv")
    assert "이 모션(session3_take1)의 행이 없습니다" in ml.load(table, other, FPS, DUR).error  # picked by hand
    assert [s.label for s in ml.load(table, other, FPS, DUR, also=[solved]).segments] == ["reach"]


def test_at_matches_a_plain_scan(monkeypatch):
    """at() looks segments up by start (every frame, every motion); the same answer as looking at all of them."""
    import random

    rnd = random.Random(1)
    segs = []
    for track in ("이동", "왼손", ""):
        t = 0.0
        for _ in range(300):
            a = t + rnd.choice([0.0, 0.0, 0.2, -0.3])  # gaps and overlaps
            b = a + rnd.uniform(0.05, 1.5)
            segs.append(ml.Segment(rnd.choice("abc"), max(0.0, a), b, track=track))
            t = b
    segs.sort(key=lambda s: (s.track, s.start))
    lab = ml.MotionLabels(path="", segments=segs)

    def scan(t):
        now = {}
        for s in sorted(segs, key=lambda s: s.start):
            if s.start <= t < s.end:
                now[s.track] = s
        return [now[k] for k in lab.tracks if k in now]

    for t in [rnd.uniform(-1, 400) for _ in range(2000)] + [s.start for s in segs[:50]] + [s.end for s in segs[:50]]:
        assert lab.at(t) == scan(t), t
    lab.segments = segs[:10]  # a new list: looked up again
    assert lab.tracks == [segs[0].track]


def _lab(*rows, path="x.labels.csv"):
    """Labels from (track, label, start, end) rows, back to back like a labeller's table."""
    return ml.MotionLabels(path=path, segments=[ml.Segment(label=lb, start=a, end=b, track=t) for t, lb, a, b in rows])


def test_edits_give_new_labels_and_never_change_the_old():
    """An edit returns new labels (edited) sharing the segments it did not touch; the old labels and segments stay
    as they were, so undo is just putting the old object back."""
    lab = _lab(("이동", "걷기", 0.0, 1.0), ("이동", "서기", 1.0, 2.0), ("손", "뻗기", 0.5, 1.5))
    before = [(s.label, s.start, s.end) for s in lab.segments]
    walk, stand, reach = lab.segments
    new, seg = ml.with_bounds(lab, walk, 0.0, 1.4, FPS, DUR)  # the end both share: the neighbour's start moves too
    assert new is not lab and new.edited and not lab.edited
    assert (seg.start, seg.end) == (0.0, pytest.approx(1.4)) and new.segments[1].start == pytest.approx(1.4)
    assert new.segments[2] is reach and [(s.label, s.start, s.end) for s in lab.segments] == before
    detached, seg = ml.with_bounds(lab, walk, 0.0, 0.8, FPS, DUR, together=False)  # shrinking alone leaves a gap
    assert seg.end == pytest.approx(0.8) and detached.segments[1] is stand
    grown, seg = ml.with_bounds(lab, walk, 0.0, 9.0, FPS, DUR, together=False)  # stops at the neighbour
    assert seg.end == pytest.approx(1.0)
    _same, seg = ml.with_bounds(lab, walk, 0.0, 1.0, FPS, DUR)
    assert _same is lab and seg is walk  # nothing changed
    snapped, seg = ml.with_bounds(lab, stand, 1.0, 1.511, FPS, DUR, together=False)
    assert seg.end == pytest.approx(round(1.511 * FPS) / FPS)  # on a frame
    tiny, seg = ml.with_bounds(lab, walk, 0.99, 1.0, FPS, DUR)
    assert seg.end - seg.start == pytest.approx(1 / FPS)  # at least a frame


def test_rename_split_merge_remove_add():
    lab = _lab(("이동", "걷기", 0.0, 1.0), ("이동", "서기", 1.0, 2.0))
    walk, stand = lab.segments
    lab.segments[1].color = (1, 2, 3)
    renamed, seg = ml.relabeled(lab, walk, " 서기 ")
    assert seg.label == "서기" and seg.color == (1, 2, 3)  # looks like the label it took
    with pytest.raises(ValueError):
        ml.relabeled(lab, walk, "  ")
    halves, first = ml.split(lab, walk, 0.51, FPS)
    assert [(s.start, s.end) for s in halves.segments[:2]] == [(0.0, pytest.approx(0.5)), (pytest.approx(0.5), 1.0)]
    assert first is halves.segments[0]
    with pytest.raises(ValueError):
        ml.split(lab, walk, 1.0, FPS)  # on the edge: nothing to cut
    one, seg = ml.merged(lab, walk, 1)
    assert len(one.segments) == 1 and (seg.label, seg.start, seg.end) == ("걷기", 0.0, 2.0)
    with pytest.raises(ValueError):
        ml.merged(lab, walk, -1)  # nothing before
    gone, seg = ml.removed(lab, stand)
    assert seg is None and gone.segments == [walk]
    filled, seg = ml.added(gone, "이동", 1.5, FPS, DUR, "뛰기")  # the gap stand left, up to the motion's end
    assert (seg.track, seg.label, seg.start, seg.end) == ("이동", "뛰기", 1.0, DUR) and filled.segments[-1] is seg
    with pytest.raises(ValueError):
        ml.added(lab, "이동", 0.5, FPS, DUR)  # a segment is there already
    fresh, seg = ml.added(None, "", 1.0, FPS, DUR, "대기")  # a motion without labels: its first one, the whole motion
    assert fresh.edited and fresh.path == "" and (seg.start, seg.end) == (0.0, DUR)
    broken = ml.MotionLabels(path="b.labels.csv", error="label 열이 없습니다")
    again, _seg = ml.added(broken, "", 1.0, FPS, DUR, "대기")
    assert again.path == "b.labels.csv" and not again.error  # starts again where the broken file was
    other_track, seg = ml.added(lab, "손", 0.5, FPS, DUR, "뻗기")
    assert other_track.tracks == ["이동", "손"] and (seg.start, seg.end) == (0.0, DUR)
    assert ml.index_of(lab, stand) == 1
    twin = ml.Segment(label="걷기", start=0.0, end=1.0, track="이동")
    with pytest.raises(ValueError):
        ml.index_of(lab, twin)  # alike is not the same segment


def test_saving_edits_is_safe(tmp_path, monkeypatch):
    """A header-only CSV reads back as labels without segments; files of other kinds or other motions are never
    overwritten; a write that fails leaves the old file."""
    src = _motion(tmp_path)
    empty = ml.save_csv(ml.MotionLabels(path=""), str(tmp_path / "motions" / "02_01.labels.csv"))
    back = ml.load(empty, src, FPS, DUR)
    assert back.error == "" and back.segments == []
    table = _write(tmp_path / "motions" / "labels.csv", "seq,label,start_s,end_s\n02_01,a,0,1\n02_03,b,0,1\n")
    assert "여러 모션" in ml.overwrite_problem(table)
    assert "여러 모션" in ml.overwrite_problem(_write(tmp_path / "t.csv", "seq,label,start_s,end_s\na,x,0,1\nb,y,0,1\n"))
    assert "라벨 파일이 아닙니다" in ml.overwrite_problem(_write(tmp_path / "walk.csv", "time,q0,q1\n0,0,0\n"))
    assert "JSON" in ml.overwrite_problem(_write(tmp_path / "a.labels.json", "[]"))
    assert ml.overwrite_problem(empty) == "" and ml.overwrite_problem(str(tmp_path / "new.labels.csv")) == ""
    framed = _write(tmp_path / "f.labels.csv", "label,start_frame,end_frame,who\na,0,9,me\n")
    losses = ml.overwrite_losses(framed)
    assert any("who" in x for x in losses) and any("프레임" in x for x in losses)
    old = open(empty, encoding="utf-8-sig").read()

    class Broken:
        def writerow(self, row):
            raise OSError("disk full")

    monkeypatch.setattr(ml.csv, "writer", lambda f: Broken())
    with pytest.raises(OSError):
        ml.save_csv(_lab(("", "a", 0.0, 1.0)), empty)
    assert open(empty, encoding="utf-8-sig").read() == old  # untouched
    assert not [p for p in os.listdir(os.path.dirname(empty)) if p.endswith(".tmp")]  # no temporary file left


def test_saving_never_takes_another_motions_table(tmp_path):
    """A file of another motion's rows (one seq), or a folder table's name even when new, is never written; a file of
    this motion's rows is (its seq column is said to go); both edges of a segment moved at once land where asked."""
    src = _motion(tmp_path)
    other = _write(tmp_path / "motions" / "02_01.labels.csv", "seq,label,start_s,end_s\n02_02,a,0,1\n")
    assert "다른 모션" in ml.overwrite_problem(other, src) and ml.overwrite_problem(other)  # no motion given: refused
    mine = _write(tmp_path / "motions" / "x.labels.csv", "seq,label,start_s,end_s\n02_01,a,0,1\n")
    assert ml.overwrite_problem(mine, src) == "" and any("seq" in x for x in ml.overwrite_losses(mine))
    assert ml.overwrite_problem(str(tmp_path / "new" / "labels.csv"), src)  # would be read for the whole folder
    assert ml.overwrite_problem(str(tmp_path / "new.labels.json"), src)
    lab = _lab(("", "a", 1.0, 2.0))
    seg = lab.segments[0]
    _new, s = ml.with_bounds(lab, seg, 3.0, 4.0, FPS, DUR)
    assert (s.start, s.end) == (3.0, 4.0)
    same, s = ml.with_bounds(lab, seg, 1.0002, 2.0, FPS, DUR)  # given back rounded: not an edit
    assert same is lab and s is seg

