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
        _pending_labels={}, _loading=0, selected=None,
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
    is_policy_result = staticmethod(lambda it: False)
    toggle_play = seek = step = set_playing = staticmethod(lambda *a: None)


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


class _Swapping:
    """A motion whose labels another thread replaces between any two reads (opening, the API): each
    read gets the other label set, with other tracks."""

    def __init__(self, a, b):
        self._labs, self._n = (a, b), 0
        self.label, self.source, self.offset, self.visible, self.color = "swap", "swap.bvh", 0.0, True, (90, 90, 90)
        self.robot = _Robot(240.0)

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
    assert m.data(idx) == "왼손" and m.data(m.index(961, 1)) == "b" and m.data(m.index(961, 3)) == "0.50"
    assert m.data(m.index(961, 1), Qt.DecorationRole) is m.data(m.index(963, 1), Qt.DecorationRole)  # one icon per color
    assert "0.25 – 0.50 s" in m.data(idx, Qt.ToolTipRole)
