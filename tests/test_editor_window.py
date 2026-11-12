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

from PySide6.QtCore import QEvent, QObject, QSettings  # noqa: E402
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
