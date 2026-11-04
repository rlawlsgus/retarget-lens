"""작업 세션 (retlens/app/session.py) without the window: capture, write, read and restore on a headless scene."""

import json
import os
import shutil
import socket
import sys
from dataclasses import asdict, fields, replace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import motion_labels  # noqa: E402
from retlens.app import session  # noqa: E402
from retlens.app.scene import (BALANCE, DEFAULT_URDF, PALETTE, MotionScene, SceneOptions, ViewSettings,  # noqa: E402
                               load_robot_urdf)
from retlens.motion_labels import MotionLabels, Segment  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "samples", "synthetic_g1_walk.npz")
NAME = "samples/synthetic_g1_walk"
pytestmark = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                reason="needs the GMR G1 assets and data/samples (tools/make_samples.py)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    import viser

    server = viser.ViserServer(host="127.0.0.1", port=_free_port(), verbose=False)
    sc = MotionScene(server, load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                     SceneOptions(video_dir=str(tmp_path_factory.mktemp("videos"))), log=lambda *_: None)
    yield sc
    sc.runner.shutdown()
    server.stop()


@pytest.fixture(autouse=True)
def fresh(scene):
    """Every test starts from an empty scene with the default settings (they share one viser server)."""
    colors = dict(motion_labels._colors)
    yield
    session.clear(scene)
    for f in fields(ViewSettings):
        setattr(scene.view, f.name, getattr(ViewSettings(), f.name))
    scene.set_retarget(foot_flat=False, swing_clearance_cm=0.0, self_collision=False)
    scene.set_physics(False, "test")
    scene.set_balance("harness")
    scene.set_assist(1.0)
    scene.compare.ref = scene.compare.item = None
    scene.set_compare(on=False, heading=True, tol_cm=3.0)
    scene.seek(0.0)
    motion_labels._colors.clear()
    motion_labels._colors.update(colors)


def _saved(scene, folder, name="s.retlens", carry=(), extra=None) -> tuple[str, dict]:
    """The scene captured relative to folder, written there and read back: (path, data)."""
    data = session.capture(scene, str(folder), carry)
    data.update(extra or {})
    path = session.write(str(folder / name), data)
    return path, session.read(path)


def _same(a: str, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(str(b)))


def test_round_trip_keeps_the_working_state(scene, tmp_path, monkeypatch):
    monkeypatch.setattr(scene, "_request_physics", lambda item: None)  # physics mode without its runs
    a, b = scene.add(SAMPLE), scene.add(SAMPLE)
    scene.set_offset(b, 0.5)
    scene.set_visible(a, False)
    scene.set_show_human(b, False)
    scene.set_compare(on=True, ref=b, item=a, heading=False, tol_cm=4.5)
    scene.view.spacing, scene.view.align, scene.view.speed, scene.view.loop = 2.5, False, 0.5, False
    scene.seek(2.4)
    scene.set_balance("pd")
    scene.set_physics(True, "test")
    scene.set_retarget(foot_flat=True, swing_clearance_cm=2.0)
    view = asdict(scene.view)
    path, data = _saved(scene, tmp_path, extra={"selected": 1, "analysis": {"ref": 0, "graph": "골반 높이 (m)",
                                                                            "follow_s": 10.0}})
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["format"] == "retlens-session" and raw["version"] == 1 and raw["motions"][0]["color"] == list(a.color)
    assert data["notes"] == [] and data["robot"] == scene.opts.robot
    m = data["motions"]
    assert [e["offset_s"] for e in m] == [0.0, 0.5] and [e["visible"] for e in m] == [False, True]
    assert [e["show_human"] for e in m] == [True, False] and [e["label"] for e in m] == [NAME, NAME + " (2)"]
    assert m[0]["retarget"] is None and m[0]["labels"] == {"from": "find"}  # a robot motion, no label file
    assert data["compare"] == {"on": True, "a": 1, "b": 0, "heading": False, "tol_cm": 4.5}
    assert data["view"] == view and data["time_s"] == 2.4
    assert data["physics"] == {"on": True, "balance": "pd", "assist": 1.0}
    assert data["retarget_next"] == {"foot_flat": True, "swing_clearance_cm": 2.0, "self_collision": False}

    # the window's state elsewhere, then the session opened over it (닫고 열기)
    scene.set_physics(False, "test")
    scene.set_balance("harness")
    scene.set_retarget(foot_flat=False, swing_clearance_cm=0.0)
    scene.view.spacing, scene.view.align, scene.view.speed, scene.view.loop = 1.8, True, 1.0, True
    other = scene.add(SAMPLE)
    r = session.restore(scene, data, str(tmp_path), physics_ready=lambda balance: "")
    assert r.finished and not r.cancelled and not r.failed and r.pending() == [] and r.notes == []
    assert other not in scene.items and scene.items == [r.items[0], r.items[1]]
    ra, rb = r.items[0], r.items[1]
    assert (ra.offset, ra.visible, ra.show_human, ra.color) == (0.0, False, True, a.color)
    assert (rb.offset, rb.visible, rb.show_human, rb.color) == (0.5, True, False, b.color)
    assert scene.compare_pair() == (1, 0) and not scene.compare.heading and scene.compare.tol_cm == 4.5
    assert asdict(scene.view) == view and scene.t == 2.4 and not scene.playing
    assert scene.physics_on and scene.balance == "pd"
    assert scene.retarget_settings()["foot_flat"] and scene.retarget_settings()["swing_clearance_cm"] == 2.0
    assert r.item_at(r.selected) is rb and r.item_at(r.analysis["ref"]) is ra and r.analysis["graph"] == "골반 높이 (m)"


def test_unknown_keys_and_a_newer_version(scene, tmp_path):
    raw = {"format": "retlens-session", "version": 2, "app_version": "9.9.0", "future": {"x": 1},
           "motions": [{"file": session.portable(SAMPLE, str(tmp_path)), "label": "w", "future_key": [1, 2],
                        "labels": {"from": "telepathy"}}]}
    path = tmp_path / "new.retlens"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = session.read(str(path))
    assert data["notes"][0] == "더 새 RetLens(9.9.0)에서 저장한 작업 세션입니다. 아는 항목만 엽니다"
    assert "future" not in data and data["motions"][0]["labels"] == {"from": "find"}  # a kind it does not know
    assert data["motions"][0]["future_key"] == [1, 2]  # kept with its entry: written back if it is carried
    r = session.restore(scene, data, str(tmp_path))
    assert len(scene.items) == 1 and not r.failed and r.notes[0].startswith("더 새 RetLens")


def test_bad_files_raise_and_change_nothing(scene, tmp_path):
    it = scene.add(SAMPLE)
    cases = {"broken.retlens": "{", "list.retlens": "[1, 2]", "other.retlens": '{"format": "x", "version": 1}',
             "noversion.retlens": '{"format": "retlens-session"}',
             "textversion.retlens": '{"format": "retlens-session", "version": "1"}'}
    for name, text in cases.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "binary.retlens").write_bytes(b"\xff\xfe\x00\x81garbage")
    for name, msg in (("broken.retlens", "작업 세션 파일을 읽지 못했습니다: broken.retlens"),
                      ("list.retlens", "RetLens 작업 세션 파일이 아닙니다: list.retlens"),
                      ("other.retlens", "RetLens 작업 세션 파일이 아닙니다"),
                      ("noversion.retlens", "버전 정보"), ("textversion.retlens", "버전 정보"),
                      ("binary.retlens", "읽지 못했습니다"), ("missing.retlens", "읽지 못했습니다")):
        with pytest.raises(session.SessionError, match=msg):
            session.read(str(tmp_path / name))
    assert scene.items == [it] and it.offset == 0.0
    bom = tmp_path / "bom.retlens"  # Notepad's BOM is fine
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"format": "retlens-session", "version": 1}).encode())
    assert session.read(str(bom))["motions"] == []


def test_relative_paths_follow_a_moved_folder(scene, tmp_path):
    a = tmp_path / "a"
    (a / "data").mkdir(parents=True)
    scene.add(shutil.copy(SAMPLE, a / "data" / "walk.npz"))
    path, data = _saved(scene, a)
    assert data["motions"][0]["file"] == {"abs": str(a / "data" / "walk.npz"), "rel": "data/walk.npz"}
    session.clear(scene)
    b = tmp_path / "b"
    os.replace(a, b)  # the whole folder moved: the absolute paths in it are stale
    data = session.read(str(b / "s.retlens"))
    r = session.restore(scene, data, str(b))
    assert not r.failed and _same(r.items[0].source, b / "data" / "walk.npz")
    shutil.copytree(b, tmp_path / "c")  # a copy: inside its folder the relative path wins, so it opens its own files
    assert _same(session.resolve(data["motions"][0]["file"], str(tmp_path / "c")), tmp_path / "c" / "data" / "walk.npz")


def test_a_session_moved_alone_finds_its_files_by_absolute_path(scene, tmp_path):
    d, s1, s2 = tmp_path / "d", tmp_path / "s1", tmp_path / "s2" / "x"
    for p in (d, s1, s2):
        p.mkdir(parents=True)
    src = shutil.copy(SAMPLE, d / "walk.npz")
    scene.add(src)
    path, data = _saved(scene, s1)
    assert data["motions"][0]["file"]["rel"] == "../d/walk.npz"
    session.clear(scene)
    os.replace(path, s2 / "s.retlens")
    data = session.read(str(s2 / "s.retlens"))
    ref = data["motions"][0]["file"]
    assert _same(session.resolve(ref, str(s2)), src)
    (tmp_path / "s2" / "d").mkdir()  # where '../d' points now: tried only after the absolute path
    shutil.copy(SAMPLE, tmp_path / "s2" / "d" / "walk.npz")
    assert _same(session.resolve(ref, str(s2)), src)
    r = session.restore(scene, data, str(s2))
    assert not r.failed and _same(r.items[0].source, src)
    session.clear(scene)
    os.remove(src)
    assert _same(session.resolve(ref, str(s2)), tmp_path / "s2" / "d" / "walk.npz")  # then the relative one


def test_another_drive_has_no_relative_path(scene, tmp_path, monkeypatch):
    scene.add(SAMPLE)

    def other_drive(*_a, **_k):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(session.os.path, "relpath", other_drive)
    assert session.portable(SAMPLE, str(tmp_path)) == {"abs": os.path.abspath(SAMPLE)}
    data = session.capture(scene, str(tmp_path))
    monkeypatch.undo()
    assert data["motions"][0]["file"] == {"abs": os.path.abspath(SAMPLE)}
    data = session.read(session.write(str(tmp_path / "s.retlens"), data))
    r = session.restore(scene, data, str(tmp_path))
    assert not r.failed and _same(r.items[0].source, SAMPLE)


def test_save_as_rebases_the_entries_kept(scene, tmp_path):
    old, new = tmp_path / "old", tmp_path / "new" / "deeper"
    (old / "data").mkdir(parents=True)
    new.mkdir(parents=True)
    src = shutil.copy(SAMPLE, old / "data" / "walk.npz")
    (old / "data" / "hand.csv").write_text("label,start_s,end_s\nstand,0,1\n", encoding="utf-8")
    entry = {"file": session.portable(src, str(old)), "label": "x", "future_key": 1,
             "labels": {"from": "file", "file": {"rel": "data/hand.csv"}}}
    moved = session.rebase_entry(entry, str(old), str(new))
    assert moved["file"] == {"abs": os.path.abspath(src), "rel": "../../old/data/walk.npz"}
    assert moved["labels"]["file"] == {"abs": str(old / "data" / "hand.csv"), "rel": "../../old/data/hand.csv"}
    assert moved["future_key"] == 1 and entry["file"]["rel"] == "data/walk.npz"  # the entry itself is left alone
    gone = session.rebase_entry({"file": {"rel": "data/gone.npz"}}, str(old), str(new))  # missing: where it would be
    assert gone["file"] == {"abs": str(old / "data" / "gone.npz"), "rel": "../../old/data/gone.npz"}
    # kept entries are held absolute (Restore.carry) and written relative to where the session goes
    kept = session.rebase_entry(entry, str(old), None)
    assert kept["file"] == {"abs": os.path.abspath(src)}
    scene.add(SAMPLE)
    data = session.capture(scene, str(new), carry=[kept])
    assert len(data["motions"]) == 2 and data["motions"][1]["file"]["rel"] == "../../old/data/walk.npz"
    assert data["motions"][1]["labels"]["file"]["rel"] == "../../old/data/hand.csv"


def test_two_entries_of_one_file_keep_names_and_colours(scene, tmp_path):
    a, b = scene.add(SAMPLE), scene.add(SAMPLE)
    a.color, b.color = PALETTE[4], PALETTE[2]
    _, data = _saved(scene, tmp_path)
    assert [e["color"] for e in data["motions"]] == [PALETTE[4], PALETTE[2]]  # tuples again, as scene.add compares
    assert all(type(e["color"]) is tuple for e in data["motions"])
    r = session.restore(scene, data, str(tmp_path))
    assert [it.label for it in scene.items] == [NAME, NAME + " (2)"]
    assert [it.color for it in scene.items] == [PALETTE[4], PALETTE[2]]
    r = session.restore(scene, data, str(tmp_path), mode="add")  # 함께 열기: the colours are taken, so others
    assert len(scene.items) == 4 and len({it.color for it in scene.items}) == 4
    assert [it.label for it in r.items.values()] == [NAME + " (3)", NAME + " (4)"]


def test_a_missing_file_fails_alone(scene, tmp_path):
    gone = shutil.copy(SAMPLE, tmp_path / "gone.npz")
    for p in (SAMPLE, gone, SAMPLE):
        scene.add(p)
    _, data = _saved(scene, tmp_path)
    session.clear(scene)
    os.remove(gone)
    data["motions"].append({"file": None, "label": "?"})  # a malformed entry
    r = session.restore(scene, data, str(tmp_path))
    assert sorted(r.items) == [0, 2] and len(scene.items) == 2
    (e1, why1), (e3, why3) = r.failed
    assert why1 == f"파일 없음: {os.path.abspath(gone)}" and e1 is data["motions"][1]
    assert why3 == session.BAD_ENTRY
    kept = r.carry()  # what the window keeps and writes back
    assert kept[0]["file"] == {"abs": os.path.abspath(gone)} and kept[1]["file"] is None


def test_time_is_applied_after_loading_and_clamped(scene, tmp_path):
    a = scene.add(SAMPLE)
    scene.set_offset(a, 0.5)
    end = a.robot.duration + 0.5
    _, data = _saved(scene, tmp_path)
    data["time_s"] = end - 0.2  # beyond an empty scene's range (0-1 s): kept only because it comes after loading
    session.restore(scene, data, str(tmp_path))
    assert scene.t == pytest.approx(end - 0.2) and not scene.playing
    data["time_s"] = 1e6
    session.restore(scene, data, str(tmp_path))
    assert scene.t == scene.time_range()[1] == pytest.approx(end)
    data["time_s"] = -3.0
    session.restore(scene, data, str(tmp_path))
    assert scene.t == 0.0


def test_a_comparison_with_a_failed_motion_stays_off(scene, tmp_path):
    a, b = scene.add(SAMPLE), scene.add(shutil.copy(SAMPLE, tmp_path / "gone.npz"))
    scene.set_compare(on=True, ref=a, item=b)
    _, data = _saved(scene, tmp_path)
    assert data["compare"]["on"] and (data["compare"]["a"], data["compare"]["b"]) == (0, 1)
    session.clear(scene)
    os.remove(tmp_path / "gone.npz")
    r = session.restore(scene, data, str(tmp_path))
    assert not scene.compare.on and scene.compare_pair() is None and len(scene.items) == 1
    assert any(n.startswith("겹쳐 비교: ") and "gone" in n and "끈 채로" in n for n in r.notes)


def test_corrections_go_to_the_load(scene, tmp_path, monkeypatch):
    """A motion's own corrections (not the 리타게팅 menu's) reach load_item; the ones it replaced come back."""
    from retlens.app import scene as scene_module

    real, calls = scene_module.load_item, []

    def recording(path, **kw):  # a robot npz as if it were a retargeted human motion
        calls.append(kw)
        item = real(path, **kw)
        item.retarget = {"smooth_hz": kw["smooth"], "foot_flat": kw["foot_flat"],
                         "swing_clearance_cm": round(100 * kw["swing_clearance"], 3), "self_collision": kw["self_collision"]}
        return item

    monkeypatch.setattr(scene_module, "load_item", recording)
    own = {"smooth_hz": 4.0, "foot_flat": True, "swing_clearance_cm": 2.0, "self_collision": True}
    it = scene.add(SAMPLE, retarget=own)
    it.info["previous_retarget"] = {"foot_flat": False, "swing_clearance_cm": 0.0, "self_collision": False, "score": 71.2}
    _, data = _saved(scene, tmp_path)
    assert data["motions"][0]["retarget"] == own and data["motions"][0]["previous_retarget"]["score"] == 71.2
    calls.clear()
    r = session.restore(scene, data, str(tmp_path))  # the 리타게팅 menu is off: the entry's own are used
    kw = calls[0]
    assert (kw["smooth"], kw["foot_flat"], kw["swing_clearance"], kw["self_collision"]) == (4.0, True, 0.02, True)
    assert r.items[0].retarget == own and r.items[0].info["previous_retarget"]["score"] == 71.2


def test_labels_found_taken_off_and_picked(scene, tmp_path):
    src = shutil.copy(SAMPLE, tmp_path / "walk.npz")
    (tmp_path / "walk.labels.csv").write_text("label,start_s,end_s\nidle,0,0.5\nwalk,0.5,1.0\n", encoding="utf-8")
    (tmp_path / "other").mkdir()
    picked_csv = tmp_path / "other" / "picked.csv"
    picked_csv.write_text("label,start_s,end_s\nstand,0,1\n", encoding="utf-8")
    scene.add(src)  # found next to it
    scene.set_labels(scene.add(src), None)  # taken off although the file is there
    scene.set_labels(scene.add(src), str(picked_csv))  # picked by hand
    scene.add(SAMPLE)  # none, and no label file to find
    _, data = _saved(scene, tmp_path)
    assert [e["labels"]["from"] for e in data["motions"]] == ["find", "none", "file", "find"]
    assert data["motions"][2]["labels"]["file"]["rel"] == "other/picked.csv"
    r = session.restore(scene, data, str(tmp_path))
    found, off, picked, plain = (r.items[i] for i in range(4))
    assert found.labels.found and [s.label for s in found.labels.segments] == ["idle", "walk"]
    assert off.labels is None and plain.labels is None
    assert not picked.labels.found and _same(picked.labels.path, picked_csv)
    assert [s.label for s in picked.labels.segments] == ["stand"] and r.notes == []
    os.remove(picked_csv)  # gone: the error shows on the motion (inspector, timeline) and in the notes
    r = session.restore(scene, data, str(tmp_path))
    assert r.items[2].labels.error and not r.failed and any("라벨 파일 없음" in n for n in r.notes)


def test_auto_labels_open_as_they_were_without_the_rules(scene, tmp_path, monkeypatch):
    from retlens import autolabel

    rules = tmp_path / "r.yaml"
    rules.write_text("name: 시험\nrules:\n  - {label: 서기}\n", encoding="utf-8")
    it = scene.add(SAMPLE)
    it.labels = MotionLabels(path=str(rules), segments=[Segment("서기", 0.0, 1.0, track="자세"),
                                                        Segment("걷기", 1.0, 2.5, track="이동")],
                             notes=["규칙 메모"], auto="시험")
    _, data = _saved(scene, tmp_path)
    state = data["motions"][0]["labels"]
    assert state["from"] == "auto" and state["name"] == "시험" and state["rules"]["rel"] == "r.yaml"

    def never(*_a, **_k):
        raise AssertionError("opening a session must not run the rules")

    monkeypatch.setattr(scene, "make_auto_labels", never)
    monkeypatch.setattr(autolabel, "label_motion", never)
    r = session.restore(scene, data, str(tmp_path))
    lab = r.items[0].labels
    assert lab.auto == "시험" and _same(lab.path, rules) and lab.notes == ["규칙 메모"] and not lab.edited
    assert [(s.label, s.start, s.end, s.track) for s in lab.segments] == [("서기", 0.0, 1.0, "자세"),
                                                                         ("걷기", 1.0, 2.5, "이동")]


def test_edited_labels_come_back_exactly(scene, tmp_path):
    hand = tmp_path / "hand.csv"
    hand.write_text("label,start_s,end_s\nstand,0,1\n", encoding="utf-8")
    frames = (1, 2, 3, 7, 68)
    segs = [Segment(f"s{k}", k / 30, (k + 7) / 30, track="이동", name="긴 이름" if k == 1 else "",
                    note="메모" if k == 2 else "", color=(10, 20, 30) if k == 3 else None) for k in frames]
    a, b, c = scene.add(SAMPLE), scene.add(SAMPLE), scene.add(SAMPLE)
    a.labels = MotionLabels(path=str(hand), segments=segs, notes=["n"], edited=True)
    b.labels = MotionLabels(path=str(hand), segments=[Segment("a", 1 / 3, 2 / 3)], found=True, edited=True)
    c.labels = MotionLabels(path="", segments=[Segment("b", 0.1, 0.2)], edited=True)  # made in RetLens from nothing
    _, data = _saved(scene, tmp_path)
    assert data["motions"][0]["labels"]["origin"] == {"from": "file", "file": {"abs": str(hand), "rel": "hand.csv"}}
    assert data["motions"][2]["labels"]["origin"] == {"from": "none"}
    r = session.restore(scene, data, str(tmp_path))
    lab = r.items[0].labels
    assert lab.edited and not lab.found and not lab.auto and _same(lab.path, hand) and lab.notes == ["n"]
    assert [(s.start, s.end) for s in lab.segments] == [(k / 30, (k + 7) / 30) for k in frames]  # exact, not rounded
    assert lab.segments[0].name == "긴 이름" and lab.segments[1].note == "메모" and lab.segments[2].color == (10, 20, 30)
    assert r.items[1].labels.found and r.items[1].labels.edited and r.items[1].labels.segments[0].end == 2 / 3
    assert r.items[2].labels.path == "" and r.items[2].labels.edited and not r.items[2].labels.found


def test_label_colours_are_kept(scene, tmp_path):
    motion_labels._colors.clear()
    motion_labels._colors.update({"걷기": (1, 2, 3), "서기": (4, 5, 6)})
    scene.add(SAMPLE)
    path, data = _saved(scene, tmp_path)
    assert data["label_colors"] == {"걷기": "#010203", "서기": "#040506"}
    with open(path, encoding="utf-8") as f:
        assert '"걷기"' in f.read()  # Korean as it is
    motion_labels._colors.clear()
    motion_labels._colors["다른"] = (9, 9, 9)
    session.restore(scene, data, str(tmp_path))
    assert motion_labels._colors == {"걷기": (1, 2, 3), "서기": (4, 5, 6)}


def test_capture_during_label_playback(scene, tmp_path):
    a, b = scene.add(SAMPLE), scene.add(SAMPLE)
    scene.set_offset(b, 1.0)
    for it in (a, b):
        it.labels = MotionLabels(path="x.csv", segments=[Segment("걷기", 0.0, 0.5)])
    before = session.fingerprint(scene)
    assert scene.play_segments("걷기", solo=True, play=False) == 2
    assert a.visible and not b.visible  # solo: only the motion being played
    assert [e["visible"] for e in session.capture(scene, str(tmp_path))["motions"]] == [True, True]  # their own
    assert session.fingerprint(scene) == before
    scene.stop_segments()
    scene.play_segments("걷기", solo=False, play=False)
    scene.set_visible(a, False)  # without solo the playlist's snapshot is stale: the real visibility counts
    assert [e["visible"] for e in session.capture(scene, str(tmp_path))["motions"]] == [False, True]
    assert session.fingerprint(scene) != before


def test_fingerprint(scene, monkeypatch):
    monkeypatch.setattr(scene, "_request_physics", lambda item: None)
    a, b = scene.add(SAMPLE), scene.add(SAMPLE)
    a.labels = MotionLabels(path="x.csv", segments=[Segment("걷기", 0.0, 1.0)])
    scene.set_compare(on=False, ref=a, item=b)
    fp = lambda: session.fingerprint(scene)  # noqa: E731
    base = fp()
    # not changes: the playhead, speed, camera, and the physics / comparison switches
    scene.seek(1.5)
    scene.view.speed = 2.0
    scene.server.initial_camera.position = (5.0, 5.0, 5.0)
    scene.set_physics(True, "test")
    scene.set_compare(on=True)
    a.labels = replace(a.labels)  # replaced by an equal copy
    assert scene.compare_pair() == (0, 1) and fp() == base
    scene.set_physics(False, "test")
    scene.set_compare(on=False)

    def changes(do, undo):
        do()
        assert fp() != base
        undo()
        assert fp() == base

    color = a.color
    labels = a.labels
    changes(lambda: scene.set_offset(a, 0.3), lambda: scene.set_offset(a, 0.0))
    changes(lambda: setattr(a, "color", PALETTE[6]), lambda: setattr(a, "color", color))
    changes(lambda: scene.set_visible(b, False), lambda: scene.set_visible(b, True))
    changes(lambda: scene.set_show_human(b, False), lambda: scene.set_show_human(b, True))
    changes(lambda: setattr(scene.view, "align", False), lambda: setattr(scene.view, "align", True))
    changes(lambda: scene.set_compare(tol_cm=5.0), lambda: scene.set_compare(tol_cm=3.0))
    changes(lambda: scene.set_compare(ref=b, item=a), lambda: scene.set_compare(ref=a, item=b))
    changes(lambda: scene.set_balance("pd"), lambda: scene.set_balance("harness"))
    changes(lambda: scene.set_assist(0.0), lambda: scene.set_assist(1.0))
    changes(lambda: scene.set_retarget(foot_flat=True), lambda: scene.set_retarget(foot_flat=False))
    changes(lambda: setattr(a, "labels", MotionLabels(path="x.csv", segments=[Segment("서기", 0.0, 1.0)])),
            lambda: setattr(a, "labels", labels))
    changes(lambda: setattr(a, "labels", replace(labels, edited=True)), lambda: setattr(a, "labels", labels))
    assert session.fingerprint(scene, [{"file": None}]) != base  # an entry kept from the last open


def test_cancelling_removes_the_motion_that_finished_loading(scene, tmp_path, monkeypatch):
    from retlens.app import scene as scene_module

    scene.add(SAMPLE)
    scene.add(SAMPLE)
    _, data = _saved(scene, tmp_path)
    session.clear(scene)
    real, cancel = scene_module.load_item, []

    def loading(*a, **k):
        item = real(*a, **k)
        cancel.append(True)  # cancelled while this motion was loading
        return item

    monkeypatch.setattr(scene_module, "load_item", loading)
    steps = []
    r = session.restore(scene, data, str(tmp_path), cancelled=lambda: bool(cancel),
                        progress=lambda done, total, label: steps.append((done, total, label)))
    assert r.cancelled and r.finished and r.items == {} and scene.items == [] and len(cancel) == 1  # 2nd never began
    assert r.pending() == data["motions"] and steps[0] == (0, 2, NAME)
    assert [e["file"] for e in r.carry()] == [{"abs": os.path.abspath(SAMPLE)}] * 2


def test_values_are_converted_and_clamped():
    raw = {"format": "retlens-session", "version": 1, "motions": [
        {"file": {"abs": os.path.abspath(SAMPLE)}, "color": [60, 165, 90], "offset_s": "nan", "visible": "false",
         "show_human": 0, "retarget": {"smooth_hz": -3, "foot_flat": "true", "swing_clearance_cm": 50,
                                       "self_collision": "no"}},
        {"file": os.path.abspath(SAMPLE), "color": [1, 2, 3], "offset_s": float("inf"), "visible": "maybe",
         "labels": {"from": "edited", "segments": [{"label": "a", "start_s": 0.5, "end_s": 0.2}, {"label": "b",
                                                    "start_s": "0.1", "end_s": 0.4, "color": "red"}]}}],
        "view": {"spacing": 99, "speed": -1, "align": "false", "show_humans": "maybe", "loop": 0},
        "compare": {"on": 1, "a": 0, "b": 0, "tol_cm": 0, "heading": "x"},
        "physics": {"on": True, "balance": "warp", "assist": 0.5},
        "retarget_next": {"swing_clearance_cm": -4, "foot_flat": 1}, "time_s": "soon", "selected": 7,
        "camera": {"position": [1, 2], "look_at": [0, 0, 0]}, "label_colors": {"걷기": "#0A0B0C", "bad": "red"}}
    d = session.parse(raw)
    m0, m1 = d["motions"]
    assert m0["color"] == (60, 165, 90) and type(m0["color"]) is tuple and m1["color"] is None  # PALETTE only
    assert (m0["offset_s"], m0["visible"], m0["show_human"]) == (0.0, False, False)
    assert (m1["offset_s"], m1["visible"], m1["file"]) == (0.0, True, {"abs": os.path.abspath(SAMPLE)})
    assert m0["retarget"] == {"smooth_hz": 0.0, "foot_flat": True, "swing_clearance_cm": 10.0, "self_collision": False}
    assert m1["labels"] == {"from": "edited", "origin": {"from": "none"}, "notes": [],
                            "segments": [{"label": "b", "start_s": 0.1, "end_s": 0.4}]}
    v = d["view"]
    assert (v["spacing"], v["speed"], v["align"], v["show_humans"], v["loop"]) == (5.0, 1.0, False, True, False)
    assert session.parse({**raw, "view": {"spacing": 0.01}})["view"]["spacing"] == 0.3
    assert d["compare"] == {"on": True, "heading": True, "tol_cm": 0.5}  # A and B the same motion: no pair
    assert d["physics"] == {"on": True, "balance": "harness", "assist": 1.0}
    assert d["retarget_next"] == {"foot_flat": True, "swing_clearance_cm": 0.0, "self_collision": False}
    assert (d["time_s"], d["selected"], d["camera"]) == (0.0, None, None)
    assert d["label_colors"] == {"걷기": "#0a0b0c"} and "dirty" not in d
    assert any("'warp'" in n and BALANCE["harness"] in n for n in d["notes"])
    assert any("잘못된 라벨 구간 1개" in n for n in d["notes"])


def test_physics_comes_back_on_only_when_it_may(scene, tmp_path, monkeypatch):
    monkeypatch.setattr(scene, "_request_physics", lambda item: None)
    scene.add(SAMPLE)
    scene.set_balance("gmt")
    scene.set_physics(True, "test")
    _, data = _saved(scene, tmp_path)
    r = session.restore(scene, data, str(tmp_path))  # nobody to ask: off, the mode kept for the 물리 menu
    assert not scene.physics_on and scene.balance == "gmt" and any(n.startswith("물리 모드") for n in r.notes)
    r = session.restore(scene, data, str(tmp_path), physics_ready=session.mujoco_ready(scene))
    assert not scene.physics_on and any("자동으로 켜지 않아" in n for n in r.notes)  # GMT: heavy, not unasked
    r = session.restore(scene, data, str(tmp_path), physics_ready=lambda b: "GMT 정책 파일 없음")
    assert not scene.physics_on and any(BALANCE["gmt"] in n and "GMT 정책 파일 없음" in n for n in r.notes)
    session.restore(scene, data, str(tmp_path), physics_ready=lambda b: "")
    assert scene.physics_on and scene.balance == "gmt"


def test_adding_a_session_keeps_the_window_settings(scene, tmp_path):
    scene.add(SAMPLE)
    _, data = _saved(scene, tmp_path)
    data["view"]["align"] = False
    data["time_s"] = 3.0
    scene.add(SAMPLE)
    before = list(scene.items)
    scene.seek(1.0)
    r = session.restore(scene, data, str(tmp_path), mode="add")
    assert scene.items == [*before, r.items[0]] and scene.view.align and scene.t == 1.0 and r.notes == []


def test_autosave_rotates_and_keeps_dirty(scene, tmp_path, monkeypatch):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    assert session.autosave_path() == str(tmp_path / "user" / "sessions" / "autosave.retlens")
    assert session.autosave_path(1).endswith("autosave.1.retlens") and session.autosave_info() is None
    scene.add(SAMPLE)
    session.write_autosave(session.capture(scene, None), dirty=True, session_path="D:/x.retlens", work="w1")
    info = session.autosave_info()
    assert info["dirty"] and info["session_path"] == "D:/x.retlens" and info["motions"] == 1
    assert not os.path.exists(session.autosave_path(1))
    scene.add(SAMPLE)
    session.write_autosave(session.capture(scene, None), dirty=False, work="w1")  # the same work: overwritten
    assert not os.path.exists(session.autosave_path(1)) and session.autosave_info()["motions"] == 2
    session.clear(scene)
    session.write_autosave(session.capture(scene, None), dirty=False, work="w2")  # other work: the last one kept
    assert session.autosave_info(1)["motions"] == 2 and session.autosave_info()["motions"] == 0
    d = session.read(session.autosave_path())
    assert d["dirty"] is False and d["session_path"] is None


def test_writing_is_atomic(scene, tmp_path, monkeypatch):
    path = session.write(str(tmp_path / "s.retlens"), {"motions": []})
    assert os.listdir(tmp_path) == ["s.retlens"] and session.is_session_file(path)
    assert session.is_session_file("x.RETLENS.json") and not session.is_session_file("x.json")
    scene.add(SAMPLE)

    def full_disk(*_a):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(session.os, "replace", full_disk)
    with pytest.raises(OSError):
        session.write(path, session.capture(scene, str(tmp_path)))
    monkeypatch.undo()
    assert os.listdir(tmp_path) == ["s.retlens"] and session.read(path)["motions"] == []  # the old one, no temp left


def test_a_restore_cancelled_before_it_starts_leaves_the_scene(scene):
    a = scene.add(SAMPLE)
    data = session.parse({"format": session.FORMAT, "version": 1, "motions": []})
    r = session.Restore(data, None, "replace").run(scene, cancelled=lambda: True)
    assert r.cancelled and scene.items == [a]

