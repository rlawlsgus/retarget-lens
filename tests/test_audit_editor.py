"""Audit fixes in the editor window (retlens/app/editor.py) and the motion scene (retlens/app/scene.py): what a user
saw before each fix is said in the test's docstring."""

import os
import socket
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retlens import motion_labels  # noqa: E402
from retlens.app import editor  # noqa: E402
from retlens.app.scene import DEFAULT_URDF, MotionScene, SceneOptions, load_robot_urdf  # noqa: E402

APP = QApplication.instance() or QApplication([])
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "samples", "synthetic_g1_walk.npz")
needs_scene = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                 reason="needs the GMR G1 assets and data/samples (tools/make_samples.py)")


class _NoBox:
    """A message box that must not appear."""

    Warning = Information = AcceptRole = RejectRole = DestructiveRole = Yes = Ok = 0

    def __init__(self, *a):
        raise AssertionError("no message box expected")

    question = warning = staticmethod(__init__)


class _Box:
    """A message box that records its text and buttons and answers with the button named `click` (else none)."""

    Warning = Information = AcceptRole = RejectRole = DestructiveRole = 0
    shown: list = []
    click = None

    def __init__(self, *a):
        self.buttons = {}

    def setText(self, text):
        _Box.shown.append(text)

    setIcon = setWindowTitle = exec = lambda self, *a: None

    def addButton(self, text, role):
        self.buttons[text] = object()
        _Box.shown.append(f"[{text}]")
        return self.buttons[text]

    def clickedButton(self):
        return self.buttons.get(_Box.click)


class _W:
    """A widget / action stand-in that keeps what was set."""

    text, visible, enabled = "", None, None

    def setText(self, t):
        self.text = t

    def setVisible(self, v):
        self.visible = v

    def setEnabled(self, v):
        self.enabled = v

    setToolTip = blockSignals = setChecked = lambda self, *a: None
    isChecked = lambda self: False  # noqa: E731
    menuAction = lambda self: self  # noqa: E731


# ------------------------------------------------------------------------------ 로봇 모션 내보내기
def test_motion_export_never_writes_over_the_motions_own_files(tmp_path, monkeypatch):
    """The dialog started in the motion's own folder, so its defaults replaced an AMASS .npz with the robot .npz and a
    hand-made <stem>.labels.csv with the window's labels, without a question."""
    src = tmp_path / "take" / "walk_stageii.npz"
    src.parent.mkdir()
    src.write_bytes(b"x")
    it = types.SimpleNamespace(source=str(src), info={}, labels=None, label="take/walk_stageii",
                               robot=types.SimpleNamespace(fps=30.0, duration=4.0))

    def dlg(fmts=("npz",), labels=True, r=None):
        return types.SimpleNamespace(range_s=lambda: r, formats=types.SimpleNamespace(value=lambda: fmts),
                                     labels=types.SimpleNamespace(isChecked=lambda: labels))

    def check(out, d):
        return editor.EditorWindow._export_overwrites(types.SimpleNamespace(), it, str(out), "walk_stageii", d)

    assert "원본 파일을 덮어쓰게" in check(src.parent, dlg())
    assert "원본" in check(src.parent, dlg(fmts=("csv", "npz"), r=(0.0, 4.0)))  # all of it, picked as a range
    assert check(src.parent, dlg(fmts=("csv", "pkl"))) == ""  # other names than the source's
    assert check(src.parent, dlg(r=(1.0, 2.0))) == ""  # a part: walk_stageii_1.00-2.00s
    assert check(tmp_path / "elsewhere", dlg()) == ""
    c3d = types.SimpleNamespace(**{**vars(it), "source": str(tmp_path / "take" / "walk.c3d"),
                                   "info": {"solved_motion": str(tmp_path / "solved" / "walk.npz")}})
    assert "원본" in editor.EditorWindow._export_overwrites(None, c3d, str(tmp_path / "solved"), "walk", dlg())

    # the label file next to it: its columns would be lost, so it is asked (here: 취소, nothing written)
    out = tmp_path / "out"
    out.mkdir()
    lab_file = out / "walk_stageii.labels.csv"
    lab_file.write_text("label,start_frame,end_frame,fps,comment\nwalk,0,100,120,checked by hand\n", encoding="utf-8")
    it.labels = motion_labels.MotionLabels(path=str(lab_file), segments=[motion_labels.Segment("walk", 0.0, 0.8)])
    monkeypatch.setattr(editor, "QMessageBox", _Box)
    _Box.shown, _Box.click = [], None
    assert check(out, dlg()) is None
    assert any("comment" in t and "프레임 열" in t for t in _Box.shown)
    _Box.click = "덮어쓰기"
    assert check(out, dlg()) == ""
    assert check(out, dlg(labels=False)) == ""  # 라벨 함께 off: the file is not touched
    # an earlier export's labels (only the columns RetLens writes, not the ones it loaded): replaced without a question
    lab_file.write_text("track,label,name,start_s,end_s,note,color\n,walk,,0.0,0.8,,\n", encoding="utf-8")
    it.labels.path = str(tmp_path / "take" / "walk_stageii.labels.csv")
    _Box.shown, _Box.click = [], None
    assert check(out, dlg()) == "" and _Box.shown == []
    # a table of several motions under that name is never written over
    lab_file.write_text("seq,label,start_s,end_s\nother,walk,0,1\nthird,run,0,1\n", encoding="utf-8")
    assert "seq" in check(out, dlg())


@pytest.mark.skipif(os.name != "nt", reason="8.3 short names are Windows'")
def test_motion_export_knows_the_source_by_its_short_name(tmp_path):
    """A motion opened by its 8.3 short path (a %TEMP% path from an agent) and exported into its own folder, picked
    in the folder dialog as a long path, replaced the AMASS source without a question."""
    import ctypes

    def win_path(fn, p):
        buf = ctypes.create_unicode_buffer(32768)
        return buf.value if getattr(ctypes.windll.kernel32, fn)(p, buf, len(buf)) else ""

    folder = tmp_path / "a folder with a long name"
    folder.mkdir()
    src = folder / "walk_stageii.npz"
    src.write_bytes(b"x")
    short, long_dir = win_path("GetShortPathNameW", str(src)), win_path("GetLongPathNameW", str(folder))
    if not short or not long_dir or os.path.normcase(os.path.dirname(short)) == os.path.normcase(long_dir):
        pytest.skip("this volume makes no 8.3 names")
    it = types.SimpleNamespace(source=short, info={}, labels=None, label="walk_stageii",
                               robot=types.SimpleNamespace(fps=30.0, duration=4.0))
    dlg = types.SimpleNamespace(range_s=lambda: None, formats=types.SimpleNamespace(value=lambda: ("npz",)),
                                labels=types.SimpleNamespace(isChecked=lambda: False))
    assert "원본 파일을 덮어쓰게" in editor.EditorWindow._export_overwrites(None, it, long_dir, "walk_stageii", dlg)


def test_motion_export_starts_beside_the_motion_not_in_its_folder(tmp_path, monkeypatch):
    seen = {}

    class Dlg:
        def __init__(self, *a):
            seen["start"] = a[-1]

        def exec(self):
            return 0  # 취소

    monkeypatch.setattr(editor.export_dialogs, "MotionExportDialog", Dlg)
    src = tmp_path / "take" / "walk_stageii.npz"
    it = types.SimpleNamespace(source=str(src), info={}, labels=None, label="take/walk_stageii",
                               robot=types.SimpleNamespace(fps=30.0, duration=4.0))
    win = types.SimpleNamespace(scene=types.SimpleNamespace(shown=lambda i: i, falls=lambda i: []),
                                label_selection=lambda: None, settings=None)
    editor.EditorWindow.export_motion(win, it)
    assert os.path.dirname(seen["start"]) == str(src.parent) and seen["start"] != str(src.parent)


# ------------------------------------------------------------------------------ closing while 데이터셋 runs
def test_closing_while_the_dataset_tab_runs_waits_for_it(monkeypatch):
    """Closing during 데이터셋 내보내기 asked nothing: the worker died with the window after the previous export's files
    were deleted and before the new manifest was written."""
    from PySide6.QtGui import QCloseEvent

    asked, stops, confirms = [], [], []
    monkeypatch.setattr(editor.QMessageBox, "question", lambda *a: asked.append(a[2]) or editor.QMessageBox.Yes)
    monkeypatch.setattr(editor.work, "fingerprint", lambda scene, carry: "unchanged")
    ds = types.SimpleNamespace(_running=True, _stop=False)
    ds._request_stop = lambda: (stops.append(1), setattr(ds, "_stop", True))
    win = types.SimpleNamespace(_close_pending=False, _restore=None, session_path="s.retlens", confirm_unsaved=True,
                                _confirm_session=lambda what: confirms.append(what) or True, dataset=ds,
                                status=lambda *a: None, scene=None, _carry_list=lambda: [],
                                updates=types.SimpleNamespace(stop_for_close=lambda: False,
                                                              close_withdrawn=lambda: None))
    e = QCloseEvent()
    editor.EditorWindow.closeEvent(win, e)
    assert not e.isAccepted() and win._close_pending and stops == [1] and len(asked) == 1 and "데이터셋" in asked[0]
    editor.EditorWindow.closeEvent(win, QCloseEvent())  # 종료 again while it still runs: nothing asked again
    assert stops == [1] and len(asked) == 1 and confirms == ["종료하기"]
    ds._running = False  # stopped: closed again by the panel, the questions answered already (here an update says no)
    e = QCloseEvent()
    editor.EditorWindow.closeEvent(win, e)
    assert confirms == ["종료하기"] and len(asked) == 1 and not win._close_pending and not e.isAccepted()

    # it ended by itself while the question was up: nothing left to wait for, so it closes now (not on a later run)
    ds._running, ds._stop = True, False
    monkeypatch.setattr(editor.QMessageBox, "question", lambda *a: setattr(ds, "_running", False) or editor.QMessageBox.Yes)
    closing = []
    win.updates.stop_for_close = lambda: closing.append(1) or False
    editor.EditorWindow.closeEvent(win, QCloseEvent())
    assert closing == [1] and not win._close_pending and stops == [1]

    # the panel closes the window once it has stopped, without its result box
    later, logs = [], []
    monkeypatch.setattr(editor.QTimer, "singleShot", lambda ms, fn: later.append(fn))
    monkeypatch.setattr(editor, "QMessageBox", _NoBox)
    monkeypatch.setattr(editor.export_dialogs, "report", lambda *a: pytest.fail("no report while closing"))
    panel = types.SimpleNamespace(win=types.SimpleNamespace(_close_pending=True, close="close",
                                                            scene=types.SimpleNamespace(log=logs.append)),
                                  _end=lambda: None)
    panel._close_after = lambda what: editor.DatasetPanel._close_after(panel, what)
    editor.DatasetPanel._export_done(panel, {"stopped": True}, "out")
    assert later == ["close"] and "멈춤" in logs[-1]
    panel.win._close_pending = False
    assert not editor.DatasetPanel._close_after(panel, "끝")


def test_a_close_waiting_for_the_dataset_tab_asks_again_after_changes(monkeypatch):
    """종료 during a 데이터셋 run closed the window once the run stopped without asking about the edits made while it
    waited, and nothing took that close back."""
    from PySide6.QtGui import QCloseEvent

    fp, answer, confirms, withdrawn, closing = {"v": "a"}, {"ok": True}, [], [], []
    monkeypatch.setattr(editor.work, "fingerprint", lambda scene, carry: fp["v"])
    monkeypatch.setattr(editor.QMessageBox, "question", lambda *a: editor.QMessageBox.Yes)
    ds = types.SimpleNamespace(_running=True, _stop=False)
    ds._request_stop = lambda: setattr(ds, "_stop", True)
    win = types.SimpleNamespace(_close_pending=False, _restore=None, session_path="s.retlens", confirm_unsaved=True,
                                _confirm_session=lambda what: confirms.append(what) or answer["ok"], dataset=ds,
                                status=lambda *a: None, scene=None, _carry_list=lambda: [],
                                updates=types.SimpleNamespace(stop_for_close=lambda: closing.append(1) or False,
                                                              close_withdrawn=lambda: withdrawn.append(1)))
    editor.EditorWindow.closeEvent(win, QCloseEvent())
    assert win._close_pending and confirms == ["종료하기"]
    fp["v"] = "b"  # a label edited while the window waited
    ds._running, answer["ok"] = False, False  # the run stopped (the panel closes the window again); 취소 this time
    e = QCloseEvent()
    editor.EditorWindow.closeEvent(win, e)
    assert confirms == ["종료하기"] * 2 and not e.isAccepted() and not win._close_pending
    assert withdrawn == [1] and closing == []  # what was armed for that close (an update's restart) is undone too

    ds._running, ds._stop, answer["ok"] = True, False, True  # 종료 again, then nothing changes while it waits
    editor.EditorWindow.closeEvent(win, QCloseEvent())
    assert win._close_pending and confirms == ["종료하기"] * 3
    ds._running = False
    editor.EditorWindow.closeEvent(win, QCloseEvent())
    assert confirms == ["종료하기"] * 3 and closing == [1]  # not asked again: on to the last checks


def test_an_update_restart_waits_for_the_dataset_tab(monkeypatch, tmp_path):
    """지금 다시 시작, 제거 and 설치된 RetLens로 다시 열기 during a 데이터셋 run: the window only put its close off, but that
    was read as 취소, so RetLens did not come back, was not uninstalled, or the installed copy never started, though
    the window then closed anyway."""
    from PySide6.QtWidgets import QWidget

    from retlens import install
    from retlens.app import update_ui

    class Armed:
        def __init__(self, **job):
            self.job, self.proc = dict(job), types.SimpleNamespace(poll=lambda: None)

        def set(self, **changes):
            self.job.update(changes)

        def cancel(self):
            self.set(cancelled=True)

    class Win(QWidget):
        defer = True  # closeEvent put the close off (the 데이터셋 tab runs); False: a question answered 취소

        def __init__(self):
            super().__init__()
            self.messages, self._close_pending = [], False
            self.scene = types.SimpleNamespace(items=[1], jobs_busy=lambda: False, log=lambda m: None)

        def status(self, text, ms=0):
            self.messages.append(text)

        def close(self):
            self._close_pending = self.defer
            return False

    monkeypatch.setattr(install, "HARD_EXIT", False)
    monkeypatch.setattr(install, "AFTER_EXIT", [])
    monkeypatch.setattr(install, "install_dir", lambda: str(tmp_path / "RetLens"))
    monkeypatch.setattr(install, "is_installed", lambda: True)
    monkeypatch.setattr(install, "processes_in", lambda d: [])
    monkeypatch.setattr(install, "arm_swap", lambda staged, version, relaunch, relaunch_args=None: Armed(
        action="swap", staged=staged, to=version, relaunch=relaunch))
    monkeypatch.setattr(install, "arm_uninstall", lambda purge: Armed(action="uninstall"))
    monkeypatch.setattr(update_ui, "_confirm_uninstall", lambda parent: False)
    win = Win()
    ctl = update_ui.UpdateController(win)
    ctl.apply(types.SimpleNamespace(version="9.9.9"), "staged.zip", now=True)
    assert ctl.armed.job["relaunch"] is True and install.HARD_EXIT and "데이터셋" in win.messages[-1]
    ctl.close_withdrawn()  # that close taken back: applied at quit, as after 취소
    assert ctl.armed.job["relaunch"] is False and "창을 닫지 않았습니다" in win.messages[-1]

    ctl.uninstall()
    un = ctl.armed
    assert un.job["action"] == "uninstall" and not un.job.get("cancelled") and install.HARD_EXIT
    ctl.close_withdrawn()
    assert un.job.get("cancelled") and ctl.armed is None and not install.HARD_EXIT
    win.defer = False  # 취소 at once: undone at once
    ctl.uninstall()
    assert ctl.armed is None and not install.HARD_EXIT and "제거하지 않았습니다" in win.messages[-1]

    win.defer = True
    ctl._launch_installed_after_close()
    assert len(install.AFTER_EXIT) == 1 and "설치된 RetLens" in win.messages[-1]
    ctl.close_withdrawn()
    assert install.AFTER_EXIT == []
    ctl.close_withdrawn()  # nothing armed any more: nothing happens


# ------------------------------------------------------------------------------ Delete
def test_delete_in_a_list_panel_does_not_close_the_motion():
    """Delete with the focus in the 데이터셋 table or the 프로젝트 file list closed the motion selected in the scene."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMainWindow, QTableWidget, QTreeWidget, QVBoxLayout, QWidget

    win = QMainWindow()
    fired = []
    a = QAction("remove", win)
    a.setShortcut(QKeySequence("Delete"))
    a.setShortcutContext(Qt.ApplicationShortcut)
    a.triggered.connect(lambda _=False: fired.append(1))
    win.addAction(a)
    central = QWidget()
    lay = QVBoxLayout(central)
    panel = QWidget()
    table = QTableWidget(3, 2)
    QVBoxLayout(panel).addWidget(table)
    lay.addWidget(panel)
    tree = QTreeWidget()  # e.g. the 계층 panel: Delete closes the motion there
    lay.addWidget(tree)
    win.setCentralWidget(central)
    keep = editor._ListDeleteKey([panel], win)
    APP.installEventFilter(keep)
    try:
        win.show()
        APP.processEvents()
        win.activateWindow()
        table.setFocus()
        APP.processEvents()
        QTest.keyClick(table, Qt.Key_Delete)
        APP.processEvents()
        assert fired == []
        tree.setFocus()
        APP.processEvents()
        QTest.keyClick(tree, Qt.Key_Delete)
        APP.processEvents()
        assert fired == [1]
        table.setFocus()
        a.trigger()  # the menu entry works from anywhere
        assert fired == [1, 1]
    finally:
        APP.removeEventFilter(keep)
        win.close()


# ------------------------------------------------------------------------------ opening files
def test_a_dropped_folder_goes_to_the_dataset_tab_and_other_files_are_named(tmp_path):
    """Dropping a capture folder or a README did nothing and said nothing."""
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    folder = tmp_path / "session1"
    folder.mkdir()
    readme = tmp_path / "README.md"
    readme.write_text("x")
    added, opened, statuses, shown = [], [], [], []
    dock = types.SimpleNamespace(show=lambda: shown.append("show"), raise_=lambda: shown.append("raise"))
    win = types.SimpleNamespace(_pending_labels={}, scene=types.SimpleNamespace(items=[]), selected=None,
                                dataset=types.SimpleNamespace(add_folders=added.extend), docks={"dataset": dock},
                                status=lambda *a: statuses.append(a[0]), add_paths=opened.extend,
                                attach_label_files=lambda files: None)
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(readme))])
    editor.EditorWindow.dropEvent(win, QDropEvent(QPointF(5, 5), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier))
    assert [os.path.normcase(os.path.abspath(f)) for f in added] == [os.path.normcase(str(folder))]
    assert opened == [] and shown == ["show", "raise"]
    assert "데이터셋 탭" in statuses[-1] and "README.md" in statuses[-1]


def test_a_takes_prop_file_is_not_opened_as_a_motion(tmp_path):
    """A take's prop FBX opened with its person's FBX was drawn with that motion and still gave '모션을 열지 못했습니다';
    alone it ran Blender first."""
    take = tmp_path / "take"
    (take / "props").mkdir(parents=True)
    person = take / "jump_002_A1.fbx"
    person.write_bytes(b"")
    prop = take / "props" / "jump_002_Prop.fbx"
    prop.write_bytes(b"")
    logs = []
    win = types.SimpleNamespace(_pending_labels={editor._path_key(str(prop)): ["x.labels.csv"]},
                                scene=types.SimpleNamespace(log=logs.append))
    paths, note = editor.EditorWindow._without_props(win, [str(person), str(prop)])
    assert paths == [str(person)] and "jump_002_Prop.fbx" in note and "함께 그립니다" in note
    assert win._pending_labels == {} and logs
    paths, note = editor.EditorWindow._without_props(win, [str(prop)])
    assert paths == [] and "물체만 든 FBX" in note
    plain = [str(tmp_path / "walk.fbx"), str(tmp_path / "a.bvh")]
    (tmp_path / "walk.fbx").write_bytes(b"")
    assert editor.EditorWindow._without_props(win, plain) == (plain, "")


def test_an_unused_prop_copy_is_named_as_one(tmp_path):
    """A prop file opened with its person while a copy of the same name sat in the other prop folder was said to be
    drawn with the person's motion, though the person drew the other copy."""
    shoot = tmp_path / "shoot"
    for d in ("Takes_Clean", "Prop_Raw", "Prop_Clean"):
        (shoot / d).mkdir(parents=True)
    person = shoot / "Takes_Clean" / "pick_010_M1.fbx"
    raw, clean = shoot / "Prop_Raw" / "pick_010_Prop.fbx", shoot / "Prop_Clean" / "pick_010_Prop.fbx"
    for f in (person, raw, clean):
        f.write_bytes(b"")
    win = types.SimpleNamespace(_pending_labels={}, scene=types.SimpleNamespace(log=lambda m: None))
    paths, note = editor.EditorWindow._without_props(win, [str(person), str(raw)])
    assert paths == [str(person)] and "그리지 않습니다" in note and "Prop_Clean" in note and "함께 그립니다" not in note
    paths, note = editor.EditorWindow._without_props(win, [str(person), str(clean)])
    assert paths == [str(person)] and "함께 그립니다" in note and "그리지 않습니다" not in note


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


def test_opening_files_counts_and_can_be_cancelled(tmp_path, monkeypatch):
    """Opening several files showed no count, and 작업 취소 stayed off; a missing file said
    'FileNotFoundError: [Errno 2] ...'."""
    emitted, statuses = [], []
    win = types.SimpleNamespace(_loading=0, _load_total=0, _load_done=0, _load_cancelled=0, _pending_labels={},
                                _load_cancel=threading.Event(), _without_props=lambda p: (p, ""),
                                status=lambda *a: statuses.append(a[0]), _refresh_status=lambda: None,
                                bridge=types.SimpleNamespace(added=types.SimpleNamespace(emit=emitted.append)),
                                scene=types.SimpleNamespace(add=lambda p: pytest.fail("a cancelled file is opened"),
                                                            log=lambda m: None))
    win._load_cancel.set()  # 작업 취소 before they started
    editor.EditorWindow.add_paths(win, [str(tmp_path / "a.bvh"), str(tmp_path / "b.bvh")])
    assert _wait(lambda: len(emitted) == 2) and [w for _p, w in emitted] == [None, None]
    assert win._loading == 2 and win._load_total == 2
    monkeypatch.setattr(editor, "QMessageBox", _NoBox)
    for x in emitted:
        editor.EditorWindow._on_added(win, x)
    assert win._loading == 0 and win._load_total == win._load_done == 0 and "열지 않은 파일 2개" in statuses[-1]

    emitted.clear()
    win._load_cancel = threading.Event()
    editor.EditorWindow.add_paths(win, [str(tmp_path / "nope.bvh")])
    assert _wait(lambda: len(emitted) == 1) and emitted[0][1] == "nope.bvh: 파일이 없습니다"


def test_a_motion_the_api_opened_is_not_one_of_the_files_opening(tmp_path, monkeypatch):
    """/api/open hands its motions to the window too: each took one off the window's count, so 열기 n/m and 작업 취소
    went away while the window's own files were still opening."""
    from retlens.compare import Item

    monkeypatch.setattr(editor, "QMessageBox", _NoBox)
    win = types.SimpleNamespace(_loading=2, _load_total=2, _load_done=0, _load_cancelled=0, _pending_labels={},
                                status=lambda *a: None, _refresh_status=lambda: None, select=lambda it: None,
                                scene=types.SimpleNamespace(items=[], fit_camera=lambda: None))

    def item(name):
        return Item(label=name, source=str(tmp_path / f"{name}.bvh"), kind="BVH", robot=types.SimpleNamespace())

    editor.EditorWindow._on_added(win, item("api"))  # POST /api/open
    assert win._loading == 2 and win._load_done == 0
    editor.EditorWindow._on_added(win, (str(tmp_path / "a.bvh"), item("a")))  # one of add_paths' files
    assert win._loading == 1 and win._load_done == 1 and win._load_total == 2


def test_the_status_bar_shows_files_opening():
    sc = types.SimpleNamespace(physics_on=False, physics_status=lambda: "", items=[], jobs_summary=lambda: "",
                               balance="harness", assist=1.0)
    win = types.SimpleNamespace(scene=sc, _loading=2, _load_done=1, _load_total=3, _restore=None, a_assist={},
                                a_balance={}, _sync_retarget=lambda: None)
    for k in ("st_physics", "st_jobs", "st_cancel", "a_cancel", "a_session_save", "a_session_save_as", "a_physics",
              "m_assist"):
        setattr(win, k, _W())
    editor.EditorWindow._refresh_status(win)
    assert win.st_jobs.text == "작업: 열기 1/3" and win.a_cancel.enabled and win.st_cancel.visible
    win._loading = 0
    editor.EditorWindow._refresh_status(win)
    assert not win.a_cancel.enabled


def test_a_splash_shows_while_the_window_is_made():
    """Several seconds passed after the start with no window and no splash."""
    from PySide6.QtWidgets import QMainWindow

    splash, say = editor._splash(os.path.join(os.path.dirname(editor.__file__), "icon.png"), False, "0.0")
    try:
        assert splash.isVisible() and "로봇 모델" in splash.message()
        say("창을 여는 중...")
        assert splash.message() == "창을 여는 중..."
        win = QMainWindow()
        win.show()
        splash.finish(win)
        assert not splash.isVisible()
        win.close()
    finally:
        splash.close()


def test_open_errors_read_as_korean_messages(tmp_path, monkeypatch):
    """'모션을 열지 못했습니다' showed raw English exceptions and the file name twice; a broken FBX offered 환경 설정
    because its text said Blender."""
    p = str(tmp_path / "nope.bvh")
    assert editor._open_error(p, FileNotFoundError(2, "No such file or directory", p)) == "nope.bvh: 파일이 없습니다"
    fbx = str(tmp_path / "a.fbx")
    no_blender = FileNotFoundError("FBX를 읽으려면 Blender 4.5 LTS가 필요합니다. '파일 > 환경 설정'에서 고르세요")
    assert editor._open_error(fbx, no_blender) == f"a.fbx: {no_blender}"
    prop = ValueError("x_Prop.fbx: 관절이 1개뿐이라 사람 골격으로 리타게팅할 수 없습니다")
    assert editor._open_error(str(tmp_path / "x_Prop.fbx"), prop) == str(prop)
    assert editor._open_error(str(tmp_path / "a.npz"), KeyError("pose_body")) == "a.npz: KeyError: 'pose_body'"

    monkeypatch.setattr(editor, "QMessageBox", _Box)
    _Box.shown, _Box.click = [], None
    win = types.SimpleNamespace(_loading=1, _load_done=0, _load_total=1, _load_cancelled=0, _pending_labels={},
                                status=lambda *a: None, _refresh_status=lambda: None, open_settings=lambda: None,
                                scene=types.SimpleNamespace(log=lambda m: None))
    bad = "a.fbx: RuntimeError: Blender failed (2): ASCII FBX files are not supported"  # the file, not the setup
    editor.EditorWindow._on_added(win, (fbx, bad))
    assert "[환경 설정 열기]" not in _Box.shown and "[닫기]" in _Box.shown
    _Box.shown = []
    win._loading = 1
    editor.EditorWindow._on_added(win, (fbx, editor._open_error(fbx, no_blender)))
    assert "[환경 설정 열기]" in _Box.shown


def test_settings_are_offered_only_for_a_missing_tool_or_model(tmp_path, monkeypatch):
    """A README opened with 모든 파일 (*) offered '환경 설정 열기': the format message names AMASS SMPL-X."""
    import numpy as np

    from retlens import compare

    monkeypatch.setattr(editor, "QMessageBox", _Box)
    win = types.SimpleNamespace(_loading=1, _load_done=0, _load_total=1, _load_cancelled=0, _pending_labels={},
                                status=lambda *a: None, _refresh_status=lambda: None, open_settings=lambda: None,
                                scene=types.SimpleNamespace(log=lambda m: None))

    def offered(path, e):
        _Box.shown, _Box.click, win._loading = [], None, 1
        editor.EditorWindow._on_added(win, (path, editor._open_error(path, e)))
        return "[환경 설정 열기]" in _Box.shown

    readme, odd = tmp_path / "README.md", tmp_path / "walk_smplx.npz"  # a file's own name does not count either
    readme.write_text("x")
    np.savez(odd, x=np.zeros(2))
    for f in (readme, odd):
        with pytest.raises(ValueError) as e:
            compare.human_format(str(f))
        assert not offered(str(f), e.value)
    amass = str(tmp_path / "walk_stageii.npz")
    assert offered(amass, FileNotFoundError("SMPL-X retargeting needs the body model: pass --smpl-model-dir or set "
                                            "SMPL_MODEL_DIR"))


# ------------------------------------------------------------------------------ 추천 보정, 데이터셋 totals, sessions
def test_no_recommendation_for_a_motion_without_scores(monkeypatch):
    """추천 보정 찾기 on a C3D ran 8 retargets and then crashed formatting a score of None."""
    monkeypatch.setattr(editor, "QMessageBox", _NoBox)
    statuses = []
    win = types.SimpleNamespace(status=lambda *a: statuses.append(a[0]))
    item = types.SimpleNamespace(label="c3d/02_01", retarget={"foot_flat": False}, metrics={})
    ranked = [{"text": "보정 없음", "score": None, "foot_flat": False, "swing_clearance_cm": 0.0, "self_collision": False}]
    editor.EditorWindow._offer_recommendation(win, item, ranked * 8)
    assert "추천할 수 없습니다" in statuses[-1]
    assert editor._score(item) == "-" and editor._score(types.SimpleNamespace(metrics={"retarget_score": 87.4})) == "87"


def test_physics_errors_show_in_the_dataset_tab(monkeypatch):
    assert "phys_error" in editor.BATCH_WHEN_FILLED
    t = {"motions": 3, "read": 3, "errors": 0, "total_s": 60.0, "qc_fail": 0, "qc_warn": 1, "with_falls": 0,
         "labelled": 0, "with_objects": 0}
    panel = types.SimpleNamespace(model=types.SimpleNamespace(rows=[{}, {}, {}]), _running=False, folders=["x"],
                                  _total=3, physics=types.SimpleNamespace(isChecked=lambda: True), summary=_W())
    monkeypatch.setattr(editor.batch, "totals", lambda rows: t)
    editor.DatasetPanel._show_totals(panel)  # totals from before phys_errors was counted
    assert "물리 오류" not in panel.summary.text
    t["phys_errors"] = 2
    editor.DatasetPanel._show_totals(panel)
    assert "물리 오류 2" in panel.summary.text


def test_a_failed_save_over_the_api_opens_no_dialog(tmp_path, monkeypatch):
    """A session save from the API that failed opened a modal box, and the request waited for someone to close it."""
    monkeypatch.setattr(editor, "QMessageBox", _NoBox)

    def write(path, data):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(editor.work, "write", write)
    win = types.SimpleNamespace(_restore=None, session_path=None, status=lambda *a: None, capture_session=lambda b: {},
                                _session_base=lambda p: None, save_session_as=lambda: pytest.fail("no file dialog"))
    assert editor.EditorWindow.save_session(win, str(tmp_path / "ro.retlens"), interactive=False) is False
    assert win._last_save_error.startswith("PermissionError")
    assert editor.EditorWindow.save_session(win, None, interactive=False) is False and win._last_save_error
    win._restore = object()  # a session opening
    assert editor.EditorWindow.save_session(win, str(tmp_path / "x.retlens"), interactive=False) is False
    assert "여는 중" in win._last_save_error


def test_a_session_motion_opened_by_hand_is_no_longer_unresolved(tmp_path):
    """A session motion that did not open stayed 'unresolved' after it was opened by hand, so the next save wrote it
    twice."""
    walk, robot = str(tmp_path / "walk.bvh"), str(tmp_path / "robot.csv")
    win = types.SimpleNamespace(_carry=[{"label": "robot", "file": {"abs": robot}},
                                        {"label": "robot (2)", "file": {"abs": robot}},
                                        {"label": "walk", "file": {"abs": walk}}], _restore_last=None)
    opened = types.SimpleNamespace(source=robot)
    titles = []
    win.scene = types.SimpleNamespace(items=[opened])
    win._carry_list = lambda: win._carry
    win._update_title = lambda: titles.append(1)
    editor.EditorWindow._drop_carried(win, opened)
    assert [e["label"] for e in win._carry] == ["robot (2)", "walk"] and titles  # one entry per motion opened
    win._restore_last = types.SimpleNamespace(finished=False)  # a session opening: its own motions are left alone
    editor.EditorWindow._drop_carried(win, opened)
    assert len(win._carry) == 2
    win._restore_last.finished = True
    editor.EditorWindow._drop_carried(win, types.SimpleNamespace(source=walk))  # removed again already: kept
    assert len(win._carry) == 2


# ------------------------------------------------------------------------------ the scene
def test_finger_bend_reference_is_said_per_joint():
    """A 3ds Max Biped hand said '굽힘 기준: 기본 자세' though most of its joints used the clip's most open frame."""
    def row(**kw):
        fg = {"fingers": {"left": {"index": {"from": "index", "max_deg": [40.0]}}}, **kw}
        return dict(MotionScene.finger_rows(fg))["손가락"]

    assert row(rest="rest pose").endswith("(굽힘 기준: 기본 자세)")
    assert row(rest="clip").endswith("(굽힘 기준: 클립에서 가장 편 자세)")
    assert row(rest="mixed", rest_joints={"rest": 5, "clip": 25}).endswith("(굽힘 기준: 기본 자세 5 · 클립 25 마디)")


def test_a_body_only_motion_on_a_robot_with_hands_is_its_own():
    """A 29-joint G1 motion opened with the G1-with-hands robot was reported as possibly another robot's."""
    body, fingers = [f"j{i}" for i in range(29)], [f"f{i}" for i in range(14)]
    prof = types.SimpleNamespace(joint_names=lambda: body + fingers, finger_joints=lambda: set(fingers),
                                 ident={"name": "hands", "digest": "d"}, name="hands")
    logs = []
    fake = types.SimpleNamespace(robot_profile=prof, log=logs.append)
    item = types.SimpleNamespace(robot=types.SimpleNamespace(joint_names=list(body), meta={}), info={}, label="walk")
    MotionScene._check_robot(fake, item)
    assert "robot_mismatch" not in item.info and not logs
    item.robot.joint_names = body[:10]  # a motion of another robot still says so
    MotionScene._check_robot(fake, item)
    assert item.info["robot_mismatch"] == "관절 29개 중 10개만 이름이 맞음"

    def no_hands():
        raise ValueError("hands not found")

    prof.finger_joints = no_hands  # the hands could not be told apart: the check still runs, over every joint
    item.info.clear()
    MotionScene._check_robot(fake, item)
    assert item.info["robot_mismatch"] == "관절 43개 중 10개만 이름이 맞음"


def test_refused_retarget_settings_change_nothing():
    """POST /api/retarget {foot_flat: true, swing_clearance_cm: 50} answered 400 but had switched 디딤발 평평 on for
    every motion opened next."""
    events = []
    fake = types.SimpleNamespace(opts=SceneOptions(), log=lambda m: None, emit=events.append)
    fake.retarget_settings = lambda: MotionScene.retarget_settings(fake)
    before = fake.retarget_settings()
    for bad in (50.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="0 \\(off\\) to 10"):
            MotionScene.set_retarget(fake, foot_flat=not before["foot_flat"], swing_clearance_cm=bad,
                                     self_collision=not before["self_collision"])
        assert fake.retarget_settings() == before and not events
    after = MotionScene.set_retarget(fake, foot_flat=True, swing_clearance_cm=2.0)
    assert after["foot_flat"] and after["swing_clearance_cm"] == 2.0 and events == ["status"]


def test_a_c3d_shows_the_objects_its_numbers_are_measured_against():
    """A C3D whose solve carries a prop showed 물체 닿음 numbers but no object rows: the rows read the markers."""
    from retlens.compare import Item

    ball = types.SimpleNamespace(name="Ball_1", moves=True, source="solve.fbx", shape=None)
    it = Item(label="02_01", source="02_01.c3d", kind="C3D", robot=None,
              human=types.SimpleNamespace(objects=[], meta={}),  # the markers
              solved_human=types.SimpleNamespace(objects=[ball], meta={}),
              metrics={"hand_obj_contact_s": 2.87, "hand_obj_reach_pct": 2.3, "hand_obj_err_cm": 4.0})
    rows = dict(MotionScene.object_rows(it))
    assert rows["물체"] == "Ball_1 (움직임)" and "2.87초" in rows["손–물체"]
    it.solved_human = None  # no solve: the motion's own skeleton, as before
    assert MotionScene.object_rows(it) == []


def test_a_physics_result_says_when_torque_saturation_is_not_judged():
    """A robot without joint torque limits showed '토크 한계 초과 0.0%' as if it had been judged."""
    m = {"phys_falls": 0, "phys_body_error_cm": 2.0, "phys_saturated_pct": 0.0}
    res = types.SimpleNamespace(metrics=m, info={"policy_replay": {"controller": "harness"}})
    assert "토크 한계 없는" not in MotionScene.result_text(None, res)
    m["phys_torque_limits_missing"] = 29
    assert MotionScene.result_text(None, res).endswith("토크 한계 초과 0.0% · 토크 한계 없는 관절 29개(토크 포화 판정 안 함)")


def test_take_and_file_warnings_show_in_the_inspector_summary():
    """The C3D take warning (주의) and the FBX 파일 주의 went into the closed 세부 정보 fold."""
    assert {"주의", "파일 주의"} <= set(editor.InspectorPanel.SUMMARY) >= set(editor.InspectorPanel.WARN_ROWS)
    assert {"take_warning", "file_warnings"} <= set(editor.BATCH_WHEN_FILLED)


def test_the_shipped_g1_by_path_is_the_built_in_robot(tmp_path):
    """Started with --robot <the shipped G1 file>, OK in 환경 설정 always said the robot changes on restart."""
    from retlens import paths

    other = str(tmp_path / "my_robot.xml")
    assert editor.same_robot_spec("", "unitree_g1") and editor.same_robot_spec(other, other)
    assert not editor.same_robot_spec("unitree_g1", other)
    assert not editor.same_robot_spec("unitree_g1", "unitree_g1_with_hands")
    g1, hands = (os.path.join(paths.robot_assets_dir(), "unitree_g1", f) for f in
                 ("g1_mocap_29dof.xml", "g1_mocap_29dof_with_hands.xml"))
    if not (os.path.isfile(g1) and os.path.isfile(hands)):
        pytest.skip("needs the GMR G1 assets")
    assert editor.same_robot_spec("unitree_g1_with_hands", hands) and editor.same_robot_spec(hands, hands)
    assert editor.same_robot_spec("", g1) and editor.same_robot_spec(g1, "unitree_g1")
    assert not editor.same_robot_spec(g1, hands)


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


@needs_scene
def test_retargeting_again_keeps_the_comparison(scene, monkeypatch):
    """Retargeting a motion of the overlay comparison again switched the comparison off; with an id the API took swing
    clearances outside 0-10 cm."""
    from retlens.compare import compute_metrics, load_item

    events = []
    scene.listen(lambda e, p: events.append((e, p)))
    a = scene.add(SAMPLE)
    b = scene.add(SAMPLE)
    assert ("items", a) in events  # the motion just opened rides with its event
    calls = []

    def again(item, ff, sw, scol):  # a retarget without GMR
        calls.append(sw)
        new = load_item(SAMPLE, log=None)
        compute_metrics(new, scene.fk, scene.limits)
        new.retarget = {"foot_flat": ff, "swing_clearance_cm": sw, "self_collision": scol}
        return new

    monkeypatch.setattr(scene, "_load_with", again)
    a.retarget = {"foot_flat": False, "swing_clearance_cm": 0.0, "self_collision": False}
    try:
        scene.set_compare(on=True, ref=a, item=b)
        events.clear()
        new = scene.retarget_again(a, swing_clearance_cm=2.0)
        c = scene.compare
        assert c.on and c.ref is new and c.item is b and scene.compare_pair() == (0, 1)
        assert ("compare", None) in events
        for bad in (50.0, -5.0, float("nan")):
            with pytest.raises(ValueError):
                scene.retarget_again(new, swing_clearance_cm=bad)
        assert calls == [2.0]
        scene.set_compare(on=False)
        newer = scene.retarget_again(new, swing_clearance_cm=0.0)  # off stays off, the pair follows
        assert not scene.compare.on and scene.compare.ref is newer
    finally:
        scene.set_compare(on=False)
        for it in list(scene.items):
            scene.remove(it)


@needs_scene
def test_playing_backwards_or_at_a_nan_speed(scene):
    """A negative speed played past the start forever; a NaN time broke the scene's frame."""
    a = scene.add(SAMPLE)
    loop, speed = scene.view.loop, scene.view.speed
    try:
        lo, hi = scene.time_range()
        scene.view.loop = False
        scene.seek(0.5)
        scene.view.speed = -4.0
        scene.set_playing(True)
        scene.tick(1.0)
        assert scene.t == lo and not scene.playing
        scene.view.loop = True
        scene.seek(0.5)
        scene.set_playing(True)
        scene.tick(1.0)
        assert scene.t == pytest.approx(hi) and scene.playing
        t = scene.t
        scene.view.speed = float("nan")
        scene.tick(0.1)
        assert scene.t == t
        scene.seek(float("nan"))
        scene.seek(float("inf"))
        assert scene.t == t
    finally:
        scene.set_playing(False)
        scene.view.loop, scene.view.speed = loop, speed
        scene.remove(a)


@needs_scene
def test_playing_on_when_the_start_moves_later(scene):
    """A motion starting before 0 set back to 0 while playing before 0 jumped the playhead to the end (or stopped it
    at the start)."""
    a, b = scene.add(SAMPLE), scene.add(SAMPLE)
    loop, speed = scene.view.loop, scene.view.speed
    try:
        scene.view.speed = 1.0
        for on in (True, False):
            scene.view.loop = on
            scene.set_offset(b, -3.0)
            scene.seek(-2.0)
            scene.set_playing(True)
            scene.set_offset(b, 0.0)  # the timeline starts at 0 now
            scene.tick(0.1)
            assert scene.t == pytest.approx(-1.9) and scene.playing
    finally:
        scene.set_playing(False)
        scene.view.loop, scene.view.speed = loop, speed
        scene.remove(a)
        scene.remove(b)


@needs_scene
def test_a_video_of_a_failed_mujoco_run_says_it_failed(scene, monkeypatch, tmp_path):
    """동영상 저장 after a failed MuJoCo run said the result was not there yet, to save again when it finishes."""
    from retlens.physics_runner import PhysicsJob

    a = scene.add(SAMPLE)
    monkeypatch.setattr(scene, "physics_on", True)  # without starting a run
    monkeypatch.setattr(scene, "balance", "harness")
    try:
        job = PhysicsJob(key="k", name="n", assist=1.0, out_dir=str(tmp_path), kind="policy", state="failed",
                         stage="실패", message="ValueError: the motion lacks left_knee_joint")
        a.handles["phys_jobs"] = {scene.phys_key: job}
        with pytest.raises(RuntimeError, match="실패해 녹화할 수 없습니다: ValueError: the motion lacks"):
            scene.save_video(a)
        job.state = "cancelled"
        with pytest.raises(RuntimeError, match="취소"):
            scene.save_video(a)
        job.state = "queued"  # still to come: save again later
        with pytest.raises(RuntimeError, match="아직 없습니다"):
            scene.save_video(a)
        job.state = "failed"
    finally:
        scene.remove(a)
