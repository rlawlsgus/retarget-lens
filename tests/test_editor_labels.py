"""The editor's side of labels (retlens/app/editor.py): which motion a dropped label file goes to, and
a timeline that repaints only when something changed and scrolls instead of growing."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWebEngineWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retlens import motion_labels  # noqa: E402
from retlens.app import editor  # noqa: E402
from retlens.app.scene import ViewSettings  # noqa: E402
from retlens.compare import Item  # noqa: E402

APP = QApplication.instance() or QApplication([])


def test_a_dropped_label_file_finds_its_own_motion():
    pick = editor._motion_for_label
    a, b = os.path.abspath("D:/cmu/02_01.bvh"), os.path.abspath("D:/other/02_01.bvh")
    assert pick("D:/other/02_01.labels.csv", [a, b]) == b  # the same name twice: the one in the label's folder
    assert pick("D:/x/02_01.labels.csv", [a, b], prefer=b) == b  # else the selected one
    assert pick("D:/x/02_01.labels.csv", [a, b]) == a  # else the first
    fit = os.path.abspath("D:/amass/02_01_stageii.npz")
    assert pick("D:/x/02_01_subtask.csv", [fit]) == fit  # the AMASS fit of the take
    assert pick("D:/x/02_01_stageii.labels.csv", [a, fit]) == fit  # its exact name first
    assert pick("D:/x/16_17.labels.csv", [a, b]) is None
    assert editor._path_key("D:/cmu/02_01.bvh") == editor._path_key("d:\\cmu\\02_01.bvh")


def test_drop_open_and_attach(tmp_path, monkeypatch):
    """A label file dropped with its motion goes to that file once it has opened, not to another
    motion of the same name that opens first; if the file does not open, the label file is dropped."""
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    for d in ("a", "b"):
        os.makedirs(tmp_path / d)
        (tmp_path / d / "02_01.bvh").write_text("HIERARCHY")
    lab = tmp_path / "a" / "02_01.labels.csv"
    lab.write_text("label,start_s,end_s\nwalk,0,1\n", encoding="utf-8")
    attached, opened, alone = [], [], []
    win = types.SimpleNamespace(
        _pending_labels={}, _loading=0, _load_done=0, _load_total=0, _load_cancelled=0, _refresh_status=lambda: None,
        selected=None,
        scene=types.SimpleNamespace(items=[], set_labels=lambda it, p: attached.append((it, p)), fit_camera=lambda: None,
                                    log=lambda m: None),
        status=lambda *a: None, select=lambda it: None, _show_labels_result=lambda it, lab: None,
        add_paths=lambda paths: opened.extend(paths), attach_label_files=lambda files: alone.extend(files),
        open_settings=lambda: None)

    class Box:  # the "could not open" message box, without a window
        Warning = AcceptRole = RejectRole = 0
        __init__ = setIcon = setWindowTitle = setText = exec = lambda self, *a: None
        addButton = clickedButton = lambda self, *a: None

    monkeypatch.setattr(editor, "QMessageBox", Box)

    def drop(*files):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
        editor.EditorWindow.dropEvent(win, QDropEvent(QPointF(5, 5), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier))

    def item(d):
        return Item(label=f"{d}/02_01", source=str(tmp_path / d / "02_01.bvh"), kind="BVH", robot=_Robot(3.0))

    drop(tmp_path / "a" / "02_01.bvh", lab)
    assert [os.path.normcase(p) for p in opened] == [os.path.normcase(str(tmp_path / "a" / "02_01.bvh"))] and not alone
    other, mine = item("b"), item("a")
    editor.EditorWindow._on_added(win, other)  # a motion of the same name from elsewhere finishes first
    assert attached == []
    editor.EditorWindow._on_added(win, mine)
    assert len(attached) == 1 and attached[0][0] is mine and os.path.samefile(attached[0][1], lab)
    assert win._pending_labels == {}

    attached.clear()
    drop(tmp_path / "a" / "02_01.bvh", lab)
    editor.EditorWindow._on_added(win, (opened[-1], "02_01.bvh: ValueError: broken"))  # it did not open
    assert win._pending_labels == {}
    editor.EditorWindow._on_added(win, item("a"))  # opened later on its own: no stale label file
    assert attached == []

    # two of its label files, or one of another name, with one motion while another is selected:
    # all wait for that motion (none goes to the selected one); opening it picks the one opening would
    win.selected = item("b")
    sub = tmp_path / "a" / "02_01_subtask.csv"
    sub.write_text("label,start_s,end_s\nreach,0,1\n", encoding="utf-8")
    seg = tmp_path / "a" / "segments.csv"
    seg.write_text("label,start_s,end_s\nidle,0,1\n", encoding="utf-8")
    drop(tmp_path / "a" / "02_01.bvh", sub, lab, seg)
    assert alone == [] and len(next(iter(win._pending_labels.values()))) == 3
    editor.EditorWindow._on_added(win, item("a"))
    assert len(attached) == 1 and os.path.samefile(attached[0][1], lab)  # <stem>.labels.csv comes first
    attached.clear()
    drop(tmp_path / "a" / "02_01.bvh", seg)
    editor.EditorWindow._on_added(win, item("a"))
    assert alone == [] and len(attached) == 1 and os.path.samefile(attached[0][1], seg)


class _Robot:
    def __init__(self, duration):
        self.duration, self.fps = duration, 30.0


class _Scene:
    def __init__(self, items):
        self.items, self.t, self.playing, self.view = items, 0.0, False, ViewSettings()

    def time_range(self):
        return 0.0, max(it.offset + it.robot.duration for it in self.items)

    shown = staticmethod(lambda it: it)
    falls = staticmethod(lambda it: [])
    problems = staticmethod(lambda it: {})
    is_policy_result = staticmethod(lambda it: False)
    toggle_play = seek = step = set_playing = staticmethod(lambda *a: None)
    playlist = None
    label_catalog = staticmethod(lambda: [])
    playlist_state = staticmethod(lambda: None)


def _item(name, tracks):
    it = Item(label=name, source=f"{name}.bvh", kind="robot", robot=_Robot(240.0))
    segs = [motion_labels.Segment("ab"[i % 2], i * 0.25, (i + 1) * 0.25, track=t) for t in tracks for i in range(960)]
    it.labels = motion_labels.MotionLabels(path="x.csv", segments=segs) if tracks else None
    return it


def test_the_timeline_repaints_on_change_and_scrolls(monkeypatch):
    items = [_item(f"m{k}", ["이동", "왼손", "오른손"]) for k in range(6)] + [_item("plain", [])]
    win = types.SimpleNamespace(scene=_Scene(items), selected=items[0])
    panel = editor.TimelinePanel(win)
    panel.resize(1200, 160)
    panel.relayout()
    panel.show()
    APP.processEvents()
    painted = []
    monkeypatch.setattr(panel.tracks, "update", lambda: painted.append(win.scene.t))
    panel.refresh()
    panel.refresh()  # nothing changed: no repaint
    win.scene.t = 3.0
    panel.refresh()
    panel.refresh()
    assert painted == [0.0, 3.0]
    # 6 motions x 3 lanes would be 6 * (20 + 54) px: the lanes scroll, the panel does not grow
    assert panel.tracks.minimumHeight() > 400 and panel.minimumSizeHint().height() < 150
    assert panel.scroll.verticalScrollBar().maximum() > 0
    layer = panel.tracks.grab()  # draws the label layer once
    first = panel.tracks._layer[1]
    win.scene.t = 100.0
    panel.tracks.grab()
    assert panel.tracks._layer[1] is first  # the playhead moved: the labels were not drawn again
    assert not layer.isNull() and panel.now.text() == "이동: a · 왼손: a · 오른손: a"
    panel.refresh()
    assert panel.now.text().startswith("이동: a")
    win.scene.t = 300.0
    panel.refresh()
    assert panel.now.text() == "(범위 밖)"

    # hover: found by time in the lane under the mouse (it runs on every mouse move)
    from PySide6.QtCore import QPointF

    tr = panel.tracks
    it, y, _h, tracks, _labels = tr._rows()[1]
    lane_y = y + tr.ROW_H - 1 + tracks.index("왼손") * tr.LANE_H + 5
    hit = tr.segment_at(QPointF(tr._x(it.offset + 10.1), lane_y))
    assert hit is not None and hit[0] is it and hit[1].track == "왼손" and hit[1].start == 10.0
    assert tr.segment_at(QPointF(tr._x(it.offset + 10.1), y + 5)) is None  # on the motion's bar, not a lane
    assert tr.segment_at(QPointF(20, lane_y)) is None  # the names column
    # scrolled down: the ruler stays at the top of what is in view, over the rows under it
    panel.scroll.verticalScrollBar().setValue(120)
    APP.processEvents()
    top = tr._ruler_top()
    assert top == 120 and tr._row_at(top + 5) is None and tr._row_at(top + tr.RULER_H + 5) is not None
    assert not tr.grab().isNull()


def test_long_timelines_and_a_failed_paint_do_not_crash():
    """Over 28 min the ruler's step table ran out (StopIteration), and the painter it left open on the
    layer picture aborted the process on the next paint."""
    assert editor.ruler_step(1680) == 120 and editor.ruler_step(40 * 60) == 300 and editor.ruler_step(1e5) == 7200
    it = _item("long", ["이동"])
    it.robot = _Robot(40 * 60.0)
    win = types.SimpleNamespace(scene=_Scene([it]), selected=it)
    panel = editor.TimelinePanel(win)
    panel.resize(1200, 160)
    tr = panel.tracks
    assert not tr.grab().isNull()

    def broken(*a):
        raise RuntimeError("paint failed")

    tr._layer, tr._paint_layer = None, broken
    for _ in range(2):  # the error is reported; the painter was closed, so the next paint does not abort
        try:
            tr.grab()
        except RuntimeError:
            pass


def test_the_layer_key_holds_the_labels_themselves():
    """Equal-looking but different label sets (or one at a freed one's address) draw again."""
    a, b = motion_labels.MotionLabels(path="x.csv"), motion_labels.MotionLabels(path="x.csv")
    assert a == b and editor._Same(a) != editor._Same(b) and editor._Same(a) == editor._Same(a)
    it = _item("m", ["이동"])
    win = types.SimpleNamespace(scene=_Scene([it]), selected=it)
    tr = editor.TimelinePanel(win).tracks
    key = tr._layer_key()
    assert key[4][0][2].obj is it.labels
    it.labels = motion_labels.MotionLabels(path="x.csv", segments=list(it.labels.segments))
    assert tr._layer_key() != key


class _Swapping:
    """A motion whose labels another thread replaces between any two reads (opening, the API): each
    read gets the other label set, with other tracks."""

    def __init__(self, a, b):
        self._labs, self._n = (a, b), 0
        self.label, self.source, self.offset, self.visible, self.color = "swap", "swap.bvh", 0.0, True, (90, 90, 90)
        self.robot, self.metrics = _Robot(240.0), {}

    @property
    def labels(self):
        self._n += 1
        return self._labs[self._n % 2]


def test_labels_replaced_while_the_timeline_draws():
    """It used to read a motion's labels several times per paint: lanes from one set, segments from the
    next -> KeyError in paintEvent (seen when the API put automatic labels on while the window drew)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainter, QPixmap

    file_labels, auto_labels = _item("a", [""]).labels, _item("b", ["동작", "이동"]).labels
    swap = _Swapping(file_labels, auto_labels)
    win = types.SimpleNamespace(scene=_Scene([swap]), selected=swap)
    panel = editor.TimelinePanel(win)
    panel.resize(1200, 200)
    tr = panel.tracks
    for _ in range(4):  # both orders
        pm = QPixmap(1200, 200)
        p = QPainter(pm)
        tr._paint_layer(p, tr._span())
        p.end()
        panel.refresh()
        for y in range(tr.RULER_H, 120, 5):
            tr.segment_at(QPointF(400, y))
            tr._label_tip(QPointF(20, y))


def test_the_inspectors_segment_list_is_made_as_it_is_shown():
    from PySide6.QtCore import Qt

    it = _item("long", ["이동", "왼손"])
    m = editor.SegmentModel(it, it.labels.segments, multi=True)
    assert m.rowCount() == 1920 and m.columnCount() == 4 and m.heads[0] == "트랙"
    idx = m.index(961, 0)
    assert m.data(idx) == "왼손" and m.data(m.index(961, 1)) == "b" and m.data(m.index(961, 3)) == "0.500"
    assert m.data(m.index(961, 1), Qt.DecorationRole) is m.data(m.index(963, 1), Qt.DecorationRole)  # one icon per color
    assert "0.25 – 0.50 s" in m.data(idx, Qt.ToolTipRole)


def test_the_timeline_shows_only_what_applies():
    """The 라벨 구간 row is there only while an open motion has labels, and the speed box follows the scene (the
    API sets speeds the list does not have)."""
    plain = _item("plain", [])
    win = types.SimpleNamespace(scene=_Scene([plain]), selected=plain)
    panel = editor.TimelinePanel(win)
    panel.show()
    panel.refresh()
    APP.processEvents()
    assert not panel.seg_row.isVisible() and panel.speed.currentData() == 1.0
    labelled = _item("labelled", ["이동"])
    win.scene.items.append(labelled)
    win.scene.label_catalog = lambda: [{"key": "이동: a", "segments": 480, "seconds": 120.0, "motions": ["labelled"]}]
    win.scene.view.speed, win.scene.view.loop = 0.3, False
    panel.refresh()
    APP.processEvents()
    assert panel.seg_row.isVisible() and panel.seg_box.currentData() == "이동: a"
    assert panel.speed.currentText() == "0.3x" and not panel.loop.isChecked()
    win.scene.view.speed = 2.0
    panel.refresh()
    assert panel.speed.currentData() == 2.0 and panel.speed.findData(0.3) >= 0  # added once, kept


def test_number_boxes_let_the_window_shortcuts_through():
    """A focused number box (시간 오프셋, 허용 오차, 간격) would take Space and the letter shortcuts; digits stay its."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDoubleSpinBox, QMainWindow

    win = QMainWindow()
    fired = []
    for key in ("Space", "N"):
        a = QAction(key, win)
        a.setShortcut(QKeySequence(key))
        a.setShortcutContext(Qt.ApplicationShortcut)
        a.triggered.connect(lambda _=False, k=key: fired.append(k))
        win.addAction(a)
    box = editor.pass_shortcuts(QDoubleSpinBox())
    box.setRange(-10, 10)
    win.setCentralWidget(box)
    win.show()
    APP.processEvents()
    win.activateWindow()
    box.setFocus()
    APP.processEvents()
    QTest.keyClick(box, Qt.Key_Space)
    QTest.keyClick(box, Qt.Key_N)
    box.lineEdit().selectAll()
    QTest.keyClicks(box, "2.5")
    APP.processEvents()
    assert fired == ["Space", "N"] and box.value() == 2.5
    win.close()


def test_dragging_the_picked_segments_edge():
    """라벨 편집 in the timeline: a press on the picked segment's end and a drag give one edit on release, on frames,
    stopping before the next segment's end (the edge it shares moves with it); Esc gives none; the picture under
    the playhead is not drawn again while dragging."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    it = _item("m", ["이동"])  # back to back 0.25 s segments
    seg = it.labels.segments[3]  # 0.75 - 1.0
    edits = []

    class Win(types.SimpleNamespace):
        def label_selection(self):
            return (it, it.labels, seg) if self.picked else None

        def set_label_selection(self, item, s):
            self.picked = s is seg

        def edit_labels(self, item, base, result, what, before=None):
            edits.append((base, result, what, before))
            return True

        def select(self, item):
            pass

    win = Win(scene=_Scene([it]), selected=it, picked=True)
    tracks = editor.TimelineTracks(win)
    tracks.resize(1200, 120)
    tracks.show()
    APP.processEvents()
    tracks.grab()
    layer = tracks._layer[1]
    r = tracks._selected_rect()
    edge = QPoint(int(round(r.right())), int(r.center().y()))
    assert tracks.edge_at(edge) == "end"
    QTest.mousePress(tracks, Qt.LeftButton, Qt.NoModifier, edge)
    for dx in (2, 10, 40):
        QTest.mouseMove(tracks, edge + QPoint(dx, 0))
    tracks.grab()
    assert tracks._layer[1] is layer  # the preview is drawn over the picture
    QTest.mouseRelease(tracks, Qt.LeftButton, Qt.NoModifier, edge + QPoint(40, 0))
    assert len(edits) == 1
    base, (new, s), what, before = edits[0]
    assert base is it.labels and before is seg and what == "구간 끝 옮기기"
    assert s.start == seg.start and seg.end < s.end <= 1.25 - 1 / 30 + 1e-9  # the next keeps a frame
    assert new.segments[4].start == s.end and it.labels.segments[4].start == 1.0  # the neighbour followed; old intact
    QTest.mousePress(tracks, Qt.LeftButton, Qt.NoModifier, edge)
    QTest.mouseMove(tracks, edge + QPoint(30, 0))
    QTest.keyClick(tracks, Qt.Key_Escape)
    QTest.mouseRelease(tracks, Qt.LeftButton, Qt.NoModifier, edge + QPoint(30, 0))
    assert len(edits) == 1  # cancelled



def test_the_label_pick_dialog_offers_the_definitions():
    """라벨 바꾸기 / 구간 추가: every label offered, the current one picked, and under the list what the label
    definition says of the label shown (or that it is not defined); a typed new label is taken as it is."""
    class Sc:
        def label_names(self, track, item=None):
            return ["집기", "놓기", "쓰기"]

        def label_definitions(self, item=None):
            return ({"작업": [{"label": "집기", "name": "물건 집기", "color": None},
                             {"label": "놓기", "name": "", "color": None}]}, ["C:/x/defs.yaml"])

    d = editor.LabelPickDialog(None, "라벨 바꾸기", "새 라벨:", Sc(), "작업", "쓰기")
    assert [d.box.itemText(i) for i in range(d.box.count())] == ["집기", "놓기", "쓰기"]
    assert d.box.currentText() == "쓰기" and "없는 라벨" in d.hint.text()
    d.box.setCurrentIndex(0)
    assert "작업 트랙 · 물건 집기" in d.hint.text() and d.label() == "집기"
    d.box.setEditText("  새 이름 ")
    assert d.label() == "새 이름"
    d.box.setEditText("")
    assert d.label() is None and "비었습니다" in d.hint.text()
    d.deleteLater()


def test_enter_in_the_label_pick_list():
    """Enter in the filtered list with no row picked: the one label holding the text goes into the box; a label typed
    in full is taken at once. (ASCII labels: QTest cannot type Hangul on the offscreen platform.)"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    class Sc:
        def label_names(self, track, item=None):
            return ["pick", "place", "write"]

        def label_definitions(self, item=None):
            return ({"work": [{"label": n, "name": "", "color": None} for n in ("pick", "place", "write")]}, ["d.yaml"])

    d = editor.LabelPickDialog(None, "rename", "new label:", Sc(), "work", "pick")
    d.show()
    pop = d.box.completer().popup()
    d.box.setEditText("")
    QTest.keyClicks(d.box.lineEdit(), "pla")
    QTest.keyClick(pop, Qt.Key_Return)
    assert d.box.currentText() == "place" and d.result() == 0  # put in the box, not taken yet
    d.box.setEditText("")
    QTest.keyClicks(d.box.lineEdit(), "WRITE")
    QTest.keyClick(pop, Qt.Key_Return)
    assert d.result() == 1 and d.label() == "write"  # typed in full (any case): taken
    d.deleteLater()
