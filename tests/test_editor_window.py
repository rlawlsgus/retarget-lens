"""The editor window as a whole (retlens/app/editor.py), offscreen: no widget opens as a window of its own.

A widget made visible before it has a parent opens as a small top-level window for a moment; that window takes the
focus, and the right-click menu of 계층 / 타임라인 that selected the motion closed at once (0.11.0: the inspector's
자동 라벨 button and its 편집됨 line)."""

import json
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu, QWidget  # noqa: E402

from retlens import motion_labels  # noqa: E402
from retlens.app.scene import DEFAULT_URDF  # noqa: E402

APP = QApplication.instance() or QApplication([])
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "samples", "synthetic_g1_walk.npz")
pytestmark = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                reason="needs the GMR G1 assets and data/samples (tools/make_samples.py)")


class _Stray(QObject):
    """Widgets shown as windows that are not the main window, a menu, a dialog or a tooltip."""

    def __init__(self):
        super().__init__()
        self.found = []

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow() \
                and not isinstance(obj, (QMainWindow, QMenu, QDialog)) and type(obj).__name__ != "QTipLabel":
            self.found.append((type(obj).__name__, str(getattr(obj, "text", lambda: "")())[:40]))
        return False


def test_selecting_motions_opens_no_stray_window(tmp_path, monkeypatch):
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod
    from retlens.synthetic import walking_bvh_text

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")  # no local API here
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    watch = _Stray()
    win = None
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
        APP.installEventFilter(watch)
        bvh = tmp_path / "walk.bvh"
        bvh.write_text(walking_bvh_text(seconds=3.0))
        rules = tmp_path / "r.yaml"
        rules.write_text("name: t\ntracks:\n  - track: 동작\n    rules:\n      - {label: 서기}\n", encoding="utf-8")
        human, robot = sc.add(str(bvh)), sc.add(SAMPLE)
        assert not sc.auto_label(human, str(rules)).error
        for it in (human, robot, human):  # a human motion shows 자동 라벨, a robot one does not
            win.select(it)
            APP.processEvents()
        lab = human.labels
        new, seg = motion_labels.relabeled(lab, lab.segments[0], "걷기")
        win.edit_labels(human, lab, (new, seg), "라벨 바꾸기", before=lab.segments[0])  # 편집됨 shows
        for it in (robot, human):
            win.select(it)
            APP.processEvents()
        assert watch.found == []
    finally:
        APP.removeEventFilter(watch)
        if win is not None:  # gone before the interpreter ends (not close(): it asks about the unsaved label edit)
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_a_session_keeps_the_dataset_tab(tmp_path, monkeypatch):
    """The 데이터셋 tab's folders, options, filter and sort go into the work session; opening it fills the rows from
    the batch cache (nothing is computed), and a folder that is gone is kept and said."""
    import shutil
    import time

    import viser

    from retlens import batch
    from retlens.app import editor
    from retlens.app import scene as scmod

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    data_dir, gone = tmp_path / "shoot", tmp_path / "gone"
    data_dir.mkdir()
    gone.mkdir()
    for name in ("a_walk.npz", "b_walk.npz", "c_walk.npz"):
        shutil.copy(SAMPLE, data_dir / name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    win = None

    def wait(cond, what):
        end = time.time() + 60
        while not cond():
            APP.processEvents()
            assert time.time() < end, what
            time.sleep(0.02)

    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup, win.confirm_unsaved = False, False
        ds = win.dataset
        ds.add_folders([str(data_dir), str(gone)])
        files = batch.motion_files([str(data_dir)])
        batch.Batch(ds.options()).run(files[:2])  # two of the three computed: in the cache
        ds.find.setText("walk")
        ds.qc.setCurrentIndex(ds.qc.findData("PASS"))
        keys = [k for k, _t, _f in batch.COLUMNS]
        ds.table.sortByColumn(keys.index("duration_s"), Qt.DescendingOrder)
        path = str(tmp_path / "work.retlens")
        assert win.save_session(path, interactive=False)
        saved = json.loads(open(path, encoding="utf-8").read())["dataset"]
        assert [f["rel"] for f in saved["folders"]] == ["shoot", "gone"] and saved["sort"] == "duration_s"
        assert saved["descending"] and saved["find"] == "walk" and saved["qc"] == "PASS" and saved["physics"] is False
        assert not win._session_dirty()
        ds.physics.setChecked(True)  # an option of the tab is a change of the session
        assert win._session_dirty()
        ds.physics.setChecked(False)

        ds._clear()
        ds.find.setText("")
        assert win._session_dirty()  # 비우기 changed the session
        shutil.rmtree(gone)
        assert win.open_session(path, mode="replace", interactive=False)[0] == 409  # asks first
        assert win.open_session(path, mode="replace", interactive=False, discard=True) == (0, "")
        wait(lambda: win._restore is None and ds.model.rows, "the session opened and the rows came from the cache")
        assert ds.folders == [str(data_dir), str(gone)]  # the missing one kept: a save does not lose it
        assert any("데이터셋 폴더를 찾지 못했습니다" in n for n in win._last_restore["notes"])
        assert len(ds.model.rows) == 2 and ds._total == 3 and "계산해 둔 결과 2 / 3" in ds.summary.text()
        assert ds.find.text() == "walk" and ds.qc.currentData() == "PASS"
        head = ds.table.horizontalHeader()
        assert head.sortIndicatorSection() == keys.index("duration_s") and head.sortIndicatorOrder() == Qt.DescendingOrder
        assert not win._session_dirty()
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_cut_the_idle_end_and_save_as(tmp_path, monkeypatch):
    """Timeline 시간 잘라내기 then 다른 이름으로 저장: the cut drawn and in the menus, the file of the new name without it."""
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod
    from retlens.io.robot import load_robot_npz

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    win = None
    out = tmp_path / "out"

    class Dlg:  # 다른 이름으로 저장 answered: this folder, this name, npz with labels
        seen = {}

        def __init__(self, parent, store, label, duration, kept, cuts, start, name, splits=()):
            Dlg.seen.update(kept=kept, cuts=cuts, name=name, splits=splits)
            self.folder = type("F", (), {"path": lambda _s: str(out)})()
            self.formats = type("F", (), {"value": lambda _s: ("npz",)})()
            self.labels = type("L", (), {"isChecked": lambda _s: True})()

        def exec(self):
            return QDialog.Accepted

        def names(self):
            return ["walk_idle_cut"] if len(Dlg.seen["kept"]) == 1 else [f"leg{k}" for k in range(len(Dlg.seen["kept"]))]

    monkeypatch.setattr(editor.export_dialogs, "SaveMotionAsDialog", Dlg)
    monkeypatch.setattr(editor.export_dialogs, "report", lambda *a: pytest.fail("no folder window after 다른 이름으로 저장"))
    shown = []
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        monkeypatch.setattr(win, "show_in_folder", shown.append)
        win.show()
        APP.processEvents()
        assert win.a_save_as.shortcut().toString() == "Ctrl+Alt+S"
        it = sc.add(SAMPLE)
        win.select(it)
        APP.processEvents()
        dur = it.robot.duration
        sc.seek(it.offset + dur - 0.5)
        win.cut_playhead(it, to_end=True)
        APP.processEvents()
        assert sc.cut_spans(it) and abs(sum(b - a for a, b in sc.kept_spans(it)) - (dur - 0.5)) < 1.5 / it.robot.fps
        win.timeline.tracks.grab()  # drawn with the cut
        m = QMenu()
        win.motion_menu(m, it)
        sub = next(a.menu() for a in m.actions() if a.menu() is not None and a.text().startswith("시간 잘라내기"))
        assert "(1곳)" in next(a.text() for a in m.actions() if a.menu() is sub)
        assert any(a.text() == "잘라낸 시간 모두 취소" and a.isEnabled() for a in sub.actions())
        win.save_motion_as(it)
        assert Dlg.seen["cuts"] == sc.cut_spans(it) and Dlg.seen["name"].endswith("_trim")
        back = load_robot_npz(str(out / "walk_idle_cut.npz"))
        assert back.num_frames == len(range(*[round(x * it.robot.fps) for x in sc.kept_spans(it)[0]]))
        assert it.info["saved_as"] == os.path.abspath(str(out / "walk_idle_cut.npz"))
        m = QMenu()
        win.motion_menu(m, it)  # 파일 위치 열기: where it was saved, the original next to it
        acts = {a.text(): a for a in m.actions()}
        acts["파일 위치 열기 (다른 이름으로 저장한 곳)"].trigger()
        acts["원본 파일 위치 열기"].trigger()
        assert shown == [it.info["saved_as"], it.source]
        assert win.a_undo.text() == f"되돌리기: 재생 위치부터 끝까지 잘라내기 ({it.label})"
        win.label_undo()
        assert sc.cut_spans(it) == ()
        # Shift+drag a range in the middle (no labels needed), cut it; split at the playhead (K): three files
        tr, fps = win.timeline.tracks, it.robot.fps
        row = next(r for r in tr._rows() if r[0] is it)
        y = row[1] + tr.ROW_H // 2
        x = lambda t: int(round(tr._x(it.offset + t)))  # noqa: E731
        QTest.mousePress(tr, Qt.LeftButton, Qt.ShiftModifier, QPoint(x(0.6), y))
        QTest.mouseMove(tr, QPoint(x(0.9), y))
        QTest.mouseRelease(tr, Qt.LeftButton, Qt.ShiftModifier, QPoint(x(0.9), y))
        rng = win.time_range
        assert rng is not None and rng[0] is it and 0.5 < rng[1] < rng[2] < 1.0 and win.a_cut_seg.isEnabled()
        tr.grab()  # drawn with the range
        win.a_cut_seg.trigger()
        assert win.time_range is None and len(sc.cut_spans(it)) == 1 and sc.cut_spans(it)[0][0] == rng[1]
        sc.seek(it.offset + round(1.5 * fps) / fps)
        win.a_split_file.trigger()
        assert sc.split_points(it) == (round(round(1.5 * fps) / fps, 6),) and len(sc.parts(it)) == 3
        tr.grab()  # drawn with the split
        assert "파일 나누기" in tr._cut_tip(QPointF(tr._x(it.offset + 1.5), y))
        m = QMenu()
        win.motion_menu(m, it)
        sub = next(a.menu() for a in m.actions() if a.menu() is not None and a.text().startswith("시간 잘라내기"))
        assert any(a.text().startswith("나누기 모두 빼기") for a in sub.actions())
        out2 = tmp_path / "legs"
        out = out2
        win.save_motion_as(it)
        assert Dlg.seen["splits"] == sc.split_points(it) and len(Dlg.seen["kept"]) == 3
        assert sorted(p.name for p in out2.glob("*.npz")) == ["leg0.npz", "leg1.npz", "leg2.npz"]
        assert load_robot_npz(str(out2 / "leg1.npz")).num_frames == round(1.5 * fps) - round(rng[2] * fps)
        win.label_undo()
        assert sc.split_points(it) == () and sc.cut_spans(it)
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_ctrl_z_undoes_closing_a_motion(tmp_path, monkeypatch):
    """되돌리기 in the window: a closed motion comes back selected; Ctrl+Shift+Z is 다시 실행 too; the menu says what
    each would do."""
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    win = None
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
        a, b = sc.add(SAMPLE), sc.add(SAMPLE)
        APP.processEvents()
        win.select(b)
        win.inspector.offset.setValue(0.4)  # the inspector's box
        asked = []
        monkeypatch.setattr(editor.QMessageBox, "question", lambda *a: asked.append(a[2]) or editor.QMessageBox.Yes)
        win.remove(b)
        assert asked and "제거할까요" in asked[0]
        APP.processEvents()
        assert win.selected is None and win.a_undo.text() == f"되돌리기: 모션 닫기 ({b.label})" and win.a_undo.isEnabled()
        win.a_undo.trigger()
        APP.processEvents()
        assert sc.items == [a, b] and win.selected is b and b.offset == 0.4
        assert win.a_redo.text() == f"다시 실행: 모션 닫기 ({b.label})"
        assert "Ctrl+Shift+Z" in [k.toString() for k in win.a_redo.shortcuts()]
        win.a_undo.trigger()  # the offset typed in the box
        APP.processEvents()
        assert b.offset == 0.0 and win.inspector.offset.value() == 0.0
        win.a_redo.trigger()
        win.a_redo.trigger()
        APP.processEvents()
        assert sc.items == [a] and win.a_redo.text() == "다시 실행" and not win.a_redo.isEnabled()
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_drag_a_bar_end_to_trim_and_save_all(tmp_path, monkeypatch):
    """트리밍: a motion bar's end dragged in on the timeline cuts that much (an undo step); 모두 다른 이름으로 저장
    writes every motion without its cut time into one folder, the same file opened twice under two names, and
    파일 위치 열기 then opens each one's file."""
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod
    from retlens.io.robot import load_robot_npz

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    out = tmp_path / "all"
    seen = {}

    class Dlg:  # 모두 다른 이름으로 저장 answered as it comes: this folder, npz with labels
        def __init__(self, parent, store, rows, start, title=""):
            seen["rows"] = rows
            self.folder = type("F", (), {"path": lambda _s: str(out)})()
            self.formats = type("F", (), {"value": lambda _s: ("npz",)})()
            self.labels = type("L", (), {"isChecked": lambda _s: True})()

        def exec(self):
            return QDialog.Accepted

        def files(self):
            return [editor.export_dialogs.part_names(r[1], r[2]) for r in seen["rows"]]

    monkeypatch.setattr(editor.export_dialogs, "SaveAllAsDialog", Dlg)
    win = None
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
        a, b = sc.add(SAMPLE), sc.add(SAMPLE)
        APP.processEvents()
        tr, fps, dur = win.timeline.tracks, a.robot.fps, a.robot.duration
        row = next(r for r in tr._rows() if r[0] is a)
        y = row[1] + tr.ROW_H // 2
        x_end = int(round(tr._x(a.offset + dur)))
        assert tr.trim_edge_at(QPointF(x_end, y)) == (a, "end")
        assert tr.trim_edge_at(QPointF(int(round(tr._x(a.offset))) + 1, y)) == (a, "start")
        target = int(round(tr._x(a.offset + dur - 0.5)))
        QTest.mousePress(tr, Qt.LeftButton, Qt.NoModifier, QPoint(x_end, y))
        QTest.mouseMove(tr, QPoint(x_end - 20, y))
        QTest.mouseMove(tr, QPoint(target, y))
        assert tr._trim is not None and tr._trim["cuts"] and sc.cut_spans(a) == ()  # only shown while dragged
        tr.grab()  # drawn with the preview
        QTest.mouseRelease(tr, Qt.LeftButton, Qt.NoModifier, QPoint(target, y))
        (s0, e0), = sc.cut_spans(a)
        assert abs(s0 - (dur - 0.5)) < 2.0 / fps and e0 == round(dur, 6) and win.selected is a
        assert win.a_undo.text() == f"되돌리기: 끝 트리밍 ({a.label})"
        win.save_all_as()
        for _ in range(600):
            APP.processEvents()
            if not win._saving_all:
                break
            QTest.qWait(20)
        assert not win._saving_all
        (la, na, nfa, kept_a, _), (lb, nb, _, _, _) = seen["rows"]
        assert (la, lb) == (a.label, b.label) and na.endswith("_trim") and nb != na and nfa == 1
        assert sorted(p.name for p in out.glob("*.npz")) == sorted([na + ".npz", nb + ".npz"])
        assert load_robot_npz(str(out / f"{na}.npz")).num_frames == round(s0 * fps)
        assert load_robot_npz(str(out / f"{nb}.npz")).num_frames == b.robot.num_frames
        assert a.info["saved_as"] == os.path.abspath(str(out / f"{na}.npz"))
        assert b.info["saved_as"] == os.path.abspath(str(out / f"{nb}.npz"))
        m = QMenu()
        win.motion_menu(m, a)
        assert win.a_save_all_as in m.actions()
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_the_save_all_dialog_names(tmp_path, monkeypatch):
    """모두 다른 이름으로 저장's table: default names made apart, parts named <name>_01.., a motion with nothing kept
    left out; names that would make the same file are refused."""
    from retlens.app import export_dialogs as ed

    assert ed.unique_names(["walk", "Walk", "run", "walk"]) == ["walk", "Walk_2", "run", "walk_3"]
    warned = []
    monkeypatch.setattr(ed.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    store = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    rows = [("a", "walk_trim", 1, 2.0, 3.0), ("b", "walk", 2, 2.5, 3.0), ("c", "idle", 0, 0.0, 1.0)]
    dlg = ed.SaveAllAsDialog(None, store, rows, str(tmp_path / "out"))
    assert dlg.files() == [["walk_trim"], ["walk_01", "walk_02"], []]
    assert not dlg.table.item(2, 3).flags() & Qt.ItemIsEditable
    dlg.table.item(1, 3).setText("walk_trim")  # two parts: walk_trim_01, _02, apart from a's walk_trim
    dlg.accept()
    assert not warned and dlg.result() == QDialog.Accepted
    dlg2 = ed.SaveAllAsDialog(None, store, rows[:2], str(tmp_path / "out"))
    dlg2.table.item(0, 3).setText("x_01")
    dlg2.table.item(1, 3).setText("x")  # x_01, x_02: x_01 twice
    dlg2.accept()
    assert warned and "x_01" in warned[0] and dlg2.result() != QDialog.Accepted


def test_select_several_delete_and_reorder(tmp_path, monkeypatch):
    """Ctrl+click several motions (timeline names, the 계층 list follows); Delete asks first and closes them all as
    one 되돌리기 step; a name dragged down the timeline moves the motion there (the 3D view's lanes follow)."""
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    win = None
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
        a, b, c = sc.add(SAMPLE), sc.add(SAMPLE), sc.add(SAMPLE)
        APP.processEvents()
        tr = win.timeline.tracks
        name_y = lambda it: next(r[1] for r in tr._rows() if r[0] is it) + tr.ROW_H // 2  # noqa: E731
        QTest.mouseClick(tr, Qt.LeftButton, Qt.NoModifier, QPoint(20, name_y(a)))
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ControlModifier, QPoint(20, name_y(c)))
        assert win.selected is c and win.selected_items() == [a, c]
        hier = {win.item_by_id(win.hierarchy.topLevelItem(i).data(0, Qt.UserRole))
                for i in range(win.hierarchy.topLevelItemCount()) if win.hierarchy.topLevelItem(i).isSelected()}
        assert hier == {a, c} and win.a_remove.text() == "선택한 모션 2개 제거"
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ControlModifier, QPoint(20, name_y(c)))  # Ctrl+click again: out
        assert win.selected_items() == [a] and win.selected is a
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ControlModifier, QPoint(20, name_y(b)))
        assert win.selected_items() == [a, b]
        m = QMenu()
        win.motion_menu(m, a)
        assert any(x.text() == "선택한 모션 2개 제거" for x in m.actions())
        asked = []
        answer = [editor.QMessageBox.No]
        monkeypatch.setattr(editor.QMessageBox, "question", lambda *x: asked.append(x[2]) or answer[0])
        win.a_remove.trigger()  # Delete: asked first; No keeps them
        assert asked and "모션 2개를 제거할까요" in asked[0] and sc.items == [a, b, c]
        answer[0] = editor.QMessageBox.Yes
        win.a_remove.trigger()
        APP.processEvents()
        assert sc.items == [c] and win.selected is None and win.selected_items() == []
        win.label_undo()  # both back, one step
        APP.processEvents()
        assert sc.items == [a, b, c]
        # drag a's name below c: a goes last; the 3D view's lanes follow the list
        QTest.mousePress(tr, Qt.LeftButton, Qt.NoModifier, QPoint(20, name_y(a)))
        QTest.mouseMove(tr, QPoint(20, name_y(a) + 10))
        last = next(r for r in tr._rows() if r[0] is c)
        QTest.mouseMove(tr, QPoint(20, last[1] + last[2] - 2))
        assert tr._move["to"] == 2
        tr.grab()  # drawn with the drop line
        QTest.mouseRelease(tr, Qt.LeftButton, Qt.NoModifier, QPoint(20, last[1] + last[2] - 2))
        APP.processEvents()
        assert sc.items == [b, c, a] and [it.handles["index"] for it in sc.items] == [0, 1, 2]
        assert [win.item_by_id(win.hierarchy.topLevelItem(i).data(0, Qt.UserRole))
                for i in range(win.hierarchy.topLevelItemCount())] == [b, c, a]
        assert win.a_undo.text() == f"되돌리기: 순서 바꾸기 ({a.label})"
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()


def test_ranges_selected_saves_dataset_rows_and_documents(tmp_path, monkeypatch):
    """Shift+click a range of names (Ctrl+Shift: added); Ctrl+Alt+S with several selected saves those; a save
    writes the cuts it was given, not ones made since, and never over another open motion's file; the 데이터셋
    table opens and copies the picked rows; a built RetLens opens its documents from a copy in the user folder."""
    import viser

    from retlens.app import editor
    from retlens.app import scene as scmod

    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"api_enabled": False}), encoding="utf-8")
    monkeypatch.setenv("RETLENS_USER_DIR", str(user))
    monkeypatch.setattr(editor, "app_settings", lambda: QSettings(str(tmp_path / "layout.ini"), QSettings.IniFormat))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    sc = scmod.MotionScene(server, scmod.load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                           scmod.SceneOptions(video_dir=str(tmp_path / "videos")), log=lambda *_: None)
    win = None
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
        items = [sc.add(SAMPLE) for _ in range(4)]
        APP.processEvents()
        tr = win.timeline.tracks
        name_y = lambda it: next(r[1] for r in tr._rows() if r[0] is it) + tr.ROW_H // 2  # noqa: E731
        QTest.mouseClick(tr, Qt.LeftButton, Qt.NoModifier, QPoint(20, name_y(items[1])))
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ShiftModifier, QPoint(20, name_y(items[3])))
        assert win.selected is items[1] and win.selected_items() == items[1:]
        QTest.mouseClick(tr, Qt.LeftButton, Qt.NoModifier, QPoint(20, name_y(items[3])))
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ShiftModifier, QPoint(20, name_y(items[2])))
        assert win.selected_items() == items[2:]
        QTest.mouseClick(tr, Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier, QPoint(20, name_y(items[0])))
        assert win.selected_items() == items  # added: 0..3 (from the main one, 3)
        win.select(items[0], many=items[:2])
        asked = []
        monkeypatch.setattr(win, "save_all_as", lambda its=None: asked.append(its))
        win.a_save_as.trigger()  # Ctrl+Alt+S with two selected: those two
        assert asked == [items[:2]] and win.a_save_as.text() == "선택한 모션 2개 다른 이름으로 저장..."
        # what a save writes: the cuts it was given (the dialog's), not the ones made since
        a = items[0]
        trim = ((round(round((a.robot.duration - 0.5) * a.robot.fps) / a.robot.fps, 6), round(a.robot.duration, 6)),), ()
        sc.cut_time(a, 0.0, 0.4)
        res = win._write_saved_as(a, str(tmp_path / "out"), ["a_saved"], ("npz",), False, trim, None)
        (piece,) = res["pieces"]
        assert piece["start_s"] == 0.0 and piece["frames"] == round(trim[0][0][0] * a.robot.fps)
        assert sc.trim_saved[a] == trim and sc.trim_unsaved(a)  # the cut made since is not saved
        assert win._owner_of([items[1].source]) is items[0]  # every open motion's own file (the same file here)
        # the 데이터셋 table: Enter opens the picked rows, Ctrl+C copies them for Excel
        ds = win.dataset
        rows = [{"file": SAMPLE, "name": f"r{k}", "folder": "f", "qc": "PASS", "retarget_score": 90 - k} for k in range(3)]
        ds.model.set_rows(rows)
        APP.processEvents()
        from PySide6.QtCore import QItemSelectionModel
        for r in (0, 2):  # as Ctrl+click picks them
            ds.table.selectionModel().select(ds.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        assert [r["name"] for r in ds.selected_rows()] == ["r0", "r2"]
        opened = []
        monkeypatch.setattr(win, "add_paths", lambda paths: opened.append(list(paths)))
        ds.open_selected()
        assert opened == [[SAMPLE, SAMPLE]]
        ds.copy_selected()
        lines = QApplication.clipboard().text().splitlines()
        assert lines[0].split("\t")[0] == "모션" and [ln.split("\t")[0] for ln in lines[1:]] == ["r0", "r2"]
        # documents: a built RetLens opens a copy in the user folder
        docs = tmp_path / "prog" / "docs"
        (docs / "images").mkdir(parents=True)
        (docs / "manual.md").write_text("# m", encoding="utf-8")
        (docs / "images" / "a.png").write_bytes(b"x")
        monkeypatch.setattr(editor.app_paths, "doc", lambda *p: str(tmp_path / "prog" / os.path.join(*p)))
        monkeypatch.setattr(editor.app_paths, "user_dir", lambda: str(user))
        monkeypatch.setattr(editor.sys, "frozen", True, raising=False)
        shown = []
        monkeypatch.setattr(win, "open_path", shown.append)
        win.open_doc("manual.md")
        from retlens import __version__
        assert shown == [str(user / "docs" / __version__ / "manual.md")] and (user / "docs" / __version__ / "images" / "a.png").is_file()
    finally:
        if win is not None:
            win.hide()
            win.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            APP.processEvents()
        sc.runner.shutdown()
        server.stop()
