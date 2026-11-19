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
    monkeypatch.setattr(editor.export_dialogs, "report", lambda *a: None)
    try:
        win = editor.EditorWindow(sc, f"http://127.0.0.1:{port}")
        win.auto_setup = False
        win.show()
        APP.processEvents()
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
        assert win.a_undo.text() == "되돌리기: 재생 위치부터 끝까지 잘라내기"
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
