"""RetLens (Retarget Lens), the K-Humanoid desktop editor (Qt): the motion scene with
editor-style dockable panels.

    python tools/editor.py [motion files ...] [--isaac-accept-eula]

Layout (like Blender / Unity; every panel can be moved, tabbed, floated or closed and
the layout is remembered; 보기 > 레이아웃 초기화 restores this one):

    +-- menu bar / toolbar ------------------------------------+
    |                                     | 계층 (loaded motions)|
    |         scene view (3D, viser)      +---------------------+
    |                                     | 인스펙터 | 씬 설정    |
    +-------------------------------------+                     |
    | 타임라인 (transport, one track per motion, falls)          |
    | 프로젝트 (data folders) | 분석 | 콘솔                       |
    +-- status bar: physics mode, Isaac jobs, time ------------+

The 3D view is the viser scene of khumanoid/app/scene.py served on 127.0.0.1 and shown in
a Qt WebEngine view with viser's own control panel hidden; every control lives in Qt.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from html import escape

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter,
                           QPalette, QPen, QPixmap)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QStyle, QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QToolTip, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import cmu_labels
from ..compare import LIBRARY_ROOTS, MOTION_EXT, Item, library_files
from .scene import GRAPH_FIXED, METRIC_DESC, METRIC_HELP, METRIC_HELP_FOOTER, ROOT, MotionScene, rel

APP_NAME = "RetLens"  # Retarget Lens
APP_TAGLINE = "Retarget Lens · 모캡 리타게팅 검증 편집기"
EULA_URL = "https://docs.omniverse.nvidia.com/platform/latest/common/NVIDIA_Omniverse_License_Agreement.html"
HIDE_VISER_PANEL_JS = """
(() => {
  const s = document.createElement('style');
  s.textContent = '[data-testid="floating-panel"]{display:none !important}';
  (document.head || document.documentElement).appendChild(s);
})();
"""
ASSIST_LABELS = {1.0: "켬 (기본)", 0.0: "끔 (보조 없음)"}


def webengine_sandbox_workaround() -> bool:
    """In a conda env Qt keeps QtWebEngineProcess.exe in Library/lib/qt6 and its DLLs in
    Library/bin; Chromium's sandboxed renderer cannot load them from there and crashes
    (0xC0000135). Turn the sandbox off in that layout only (a packaged build ships them side
    by side); the view shows nothing but the local scene server (ScenePage). Returns True
    when it was turned off."""
    from PySide6.QtCore import QLibraryInfo

    if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX"):
        return True
    exe_dir = QLibraryInfo.path(QLibraryInfo.LibraryExecutablesPath)
    if os.name != "nt" or os.path.isfile(os.path.join(exe_dir, "Qt6WebEngineCore.dll")):
        return False
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    return True


def app_settings() -> QSettings:
    """Per-user settings (window layout, Isaac EULA consent). Carries over what was saved
    under the program's earlier name, K-Humanoid Motion Editor."""
    s = QSettings(APP_NAME, APP_NAME)
    if not s.allKeys():
        old = QSettings("K-Humanoid", "MotionEditor")
        for k in old.allKeys():
            s.setValue(k, old.value(k))
    return s


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def color_icon(rgb, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(*rgb))
    return QIcon(pm)


def dark_palette() -> QPalette:
    p = QPalette()
    base, alt, text, mid = QColor(43, 43, 46), QColor(53, 53, 57), QColor(220, 220, 224), QColor(64, 64, 70)
    for role, c in ((QPalette.Window, alt), (QPalette.WindowText, text), (QPalette.Base, base),
                    (QPalette.AlternateBase, alt), (QPalette.ToolTipBase, mid), (QPalette.ToolTipText, text),
                    (QPalette.Text, text), (QPalette.Button, mid), (QPalette.ButtonText, text),
                    (QPalette.BrightText, QColor(255, 80, 80)), (QPalette.Highlight, QColor(52, 120, 200)),
                    (QPalette.HighlightedText, QColor(255, 255, 255)), (QPalette.PlaceholderText, QColor(140, 140, 150))):
        p.setColor(role, c)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 128))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 128))
    return p


class SceneBridge(QObject):
    """Scene events (any thread) -> the Qt main thread."""
    event = Signal(str, object)
    added = Signal(object)  # Item, or an error text
    log = Signal(str)


# ------------------------------------------------------------------------------ scene view
class ScenePage(QWebEnginePage):
    """Shows only the local scene server: any other link opens in the system browser."""

    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self.base = base

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.toString().startswith(self.base):
            return True
        if is_main_frame:
            QDesktopServices.openUrl(url)
        return False


class SceneView(QWebEngineView):
    """The viser scene; viser's own floating control panel is hidden (the editor has its own).

    The scene is drawn at the screen's full resolution (viser's `fixedDpr`). Left to itself,
    viser drops to 75 % whenever fewer than ~38 frames a second are drawn, and that is always
    the case here: during playback the scene changes 30 times a second. The view then turned
    blurry at random. The page is loaded when the view is first shown (on its screen) and
    again if the window moves to a screen with another scale."""

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.scene_url = url
        self._dpr = None  # the resolution the page was loaded for
        self._screen_hooked = False
        u = QUrl(url)
        self.setPage(ScenePage(f"{u.scheme()}://{u.host()}:{u.port()}/", self))
        script = QWebEngineScript()
        script.setName("hide-viser-panel")
        script.setSourceCode(HIDE_VISER_PANEL_JS)
        script.setInjectionPoint(QWebEngineScript.DocumentReady)
        script.setWorldId(QWebEngineScript.MainWorld)
        self.page().scripts().insert(script)
        self.setAcceptDrops(False)  # file drops go to the editor window (adds the motion)
        self.setMinimumSize(320, 240)

    def showEvent(self, e):
        super().showEvent(e)
        self.match_screen()
        handle = self.window().windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(lambda _screen: self.match_screen())
            self._screen_hooked = True

    def match_screen(self) -> None:
        dpr = round(self.devicePixelRatioF(), 3)
        if dpr != self._dpr:
            self._dpr = dpr
            u = self.scene_url
            self.load(QUrl(f"{u}{'&' if '?' in u else '?'}fixedDpr={dpr:g}"))


# ------------------------------------------------------------------------------ hierarchy
class HierarchyPanel(QTreeWidget):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setHeaderLabels(["이름", "종류", "물리"])
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemSelectionChanged.connect(self._selected)
        self.itemChanged.connect(self._changed)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._filling = False

    def rebuild(self) -> None:
        self._filling = True
        sel = self.win.selected
        self.clear()
        for it in self.win.scene.items:
            row = QTreeWidgetItem([it.label, it.kind, ""])
            row.setIcon(0, color_icon(it.color))
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked if it.visible else Qt.Unchecked)
            row.setData(0, Qt.UserRole, id(it))
            row.setToolTip(0, rel(it.source))
            self.addTopLevelItem(row)
            if it is sel:
                row.setSelected(True)
        self._filling = False
        self.refresh()

    def refresh(self) -> None:
        sc = self.win.scene
        self._filling = True  # the visibility check follows the scene (e.g. the inspector's 보이기)
        for i in range(self.topLevelItemCount()):
            row = self.topLevelItem(i)
            it = self.win.item_by_id(row.data(0, Qt.UserRole))
            if it is None:
                continue
            state = Qt.Checked if it.visible else Qt.Unchecked
            if row.checkState(0) != state:
                row.setCheckState(0, state)
            text = sc.job_text(it) if (sc.physics_on or it.handles.get("phys") or sc.is_physics_result(it)) else ""
            row.setText(2, text.split(" · ")[0] if text else "")
            row.setToolTip(2, text)
        self._filling = False

    def select(self, item: Item | None) -> None:
        self._filling = True
        for i in range(self.topLevelItemCount()):
            row = self.topLevelItem(i)
            row.setSelected(item is not None and row.data(0, Qt.UserRole) == id(item))
        self._filling = False

    def _selected(self) -> None:
        if self._filling:
            return
        rows = self.selectedItems()
        self.win.select(self.win.item_by_id(rows[0].data(0, Qt.UserRole)) if rows else None)

    def _changed(self, row: QTreeWidgetItem, col: int) -> None:
        if self._filling or col != 0:
            return
        it = self.win.item_by_id(row.data(0, Qt.UserRole))
        if it is not None:
            self.win.scene.set_visible(it, row.checkState(0) == Qt.Checked)

    def _menu(self, pos) -> None:
        row = self.itemAt(pos)
        it = self.win.item_by_id(row.data(0, Qt.UserRole)) if row else None
        if it is None:
            return
        self.win.select(it)
        m = QMenu(self)
        m.addAction("동영상 저장", lambda: self.win.save_video(it))
        if self.win.scene.video_file(it):
            m.addAction("저장된 동영상 열기", lambda: self.win.open_path(self.win.scene.video_file(it)))
        m.addAction("파일 위치 열기", lambda: self.win.open_path(os.path.dirname(it.source)))
        m.addSeparator()
        m.addAction("제거", lambda: self.win.remove(it))
        m.exec(self.viewport().mapToGlobal(pos))


# ------------------------------------------------------------------------------ inspector
class InspectorPanel(QScrollArea):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.item: Item | None = None
        self._build_empty()

    def _clear(self) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        self.setWidget(w)
        return lay

    def _build_empty(self) -> None:
        lay = self._clear()
        hint = QLabel("선택한 모션이 없습니다.\n\n계층 패널이나 타임라인에서 모션을 고르면 여기에 속성과 지표가 나옵니다. "
                      "모션은 프로젝트 패널에서 두 번 클릭하거나, 파일 > 열기, 또는 탐색기에서 끌어다 놓아 추가합니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay.addWidget(hint)

    def show_item(self, item: Item | None) -> None:
        self.item = item
        if item is None:
            self._build_empty()
            return
        sc = self.win.scene
        lay = self._clear()
        title = QLabel(f"<span style='color:rgb{tuple(item.color)}'>■</span> <b>{item.label}</b>")
        title.setTextFormat(Qt.RichText)
        f = title.font()
        f.setPointSize(f.pointSize() + 2)
        title.setFont(f)
        lay.addWidget(title)
        desc = cmu_labels.label_for(item.source)
        if desc:
            d = QLabel(f"CMU: {desc}")
            d.setStyleSheet("color: gray")
            lay.addWidget(d)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for k, v in sc.item_facts(item):
            if k == "파일":  # let long paths wrap at the separators
                v = v.replace("\\", "/").replace("/", "/​")
            lab = QLabel(v)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(f"{k}", lab)
        lay.addLayout(form)

        lay.addWidget(self._section("표시"))
        self.vis = QCheckBox("보이기")
        self.vis.setChecked(item.visible)
        self.vis.toggled.connect(lambda on: sc.set_visible(item, on))
        lay.addWidget(self.vis)
        self.hv = None
        if item.human is not None:
            self.hv = QCheckBox("사람 스켈레톤")
            self.hv.setChecked(item.show_human)
            self.hv.toggled.connect(lambda on: sc.set_show_human(item, on))
            lay.addWidget(self.hv)
        row = QHBoxLayout()
        row.addWidget(QLabel("시간 오프셋 (s)"))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-600.0, 600.0)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(1 / 30)
        self.offset.setValue(item.offset)
        self.offset.valueChanged.connect(lambda v: sc.set_offset(item, v))
        row.addWidget(self.offset)
        lay.addLayout(row)

        lay.addWidget(self._section("물리 (Isaac PhysX)"))
        self.phys = QLabel()
        self.phys.setWordWrap(True)
        lay.addWidget(self.phys)

        lay.addWidget(self._section("동영상"))
        vrow = QHBoxLayout()
        b = QPushButton("동영상 저장")
        b.setToolTip("Isaac Sim에서 사람(원본이 있으면)과 로봇을 나란히 녹화해 MP4로 저장합니다. "
                     "물리 모드가 켜져 있으면 물리 시뮬레이션 결과를 녹화합니다")
        b.clicked.connect(lambda: self.win.save_video(item))
        vrow.addWidget(b)
        self.open_video = QPushButton("열기")
        self.open_video.clicked.connect(lambda: self.win.open_path(sc.video_file(item)))
        vrow.addWidget(self.open_video)
        self.open_folder = QPushButton("폴더")
        self.open_folder.clicked.connect(lambda: self.win.open_path(os.path.dirname(sc.video_file(item) or "")))
        vrow.addWidget(self.open_folder)
        lay.addLayout(vrow)
        self.video = QLabel()
        self.video.setWordWrap(True)
        self.video.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.video)

        lay.addWidget(self._section("지표"))
        self.metrics = QTableWidget(0, 2)
        self.metrics.setHorizontalHeaderLabels(["지표", "값"])
        self.metrics.verticalHeader().setVisible(False)
        self.metrics.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.metrics.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics.setMinimumHeight(260)
        lay.addWidget(self.metrics)

        rm = QPushButton("제거")
        rm.setStyleSheet("color: rgb(230,90,80)")
        rm.clicked.connect(lambda: self.win.remove(item))
        lay.addWidget(rm)
        self.refresh()

    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        lab.setStyleSheet("margin-top: 10px; border-bottom: 1px solid rgba(128,128,128,0.4)")
        return lab

    def refresh(self, metrics: bool = True) -> None:
        """metrics=False: only the status lines (job progress), not the metric table."""
        it, sc = self.item, self.win.scene
        if it is None or it not in sc.items:
            return
        self.phys.setText(sc.job_text(it) if (sc.physics_on or it.handles.get("phys") or sc.is_physics_result(it))
                          else "물리 모드가 꺼져 있습니다(툴바나 물리 메뉴에서 켭니다).")
        self.video.setText(sc.video_text(it) or "아직 저장한 동영상이 없습니다.")
        has = sc.video_file(it) is not None
        self.open_video.setEnabled(has)
        self.open_folder.setEnabled(has)
        if abs(self.offset.value() - it.offset) > 1e-6:
            self.offset.blockSignals(True)
            self.offset.setValue(it.offset)
            self.offset.blockSignals(False)
        for box, value in ((self.vis, it.visible), (self.hv, it.show_human)):  # same switches as the hierarchy's
            if box is not None and box.isChecked() != value:
                box.blockSignals(True)
                box.setChecked(value)
                box.blockSignals(False)
        if not metrics:
            return
        names, cols = sc.metric_table(self.win.analysis.ref_item())
        vals = next((v for c, v in cols if c is it), None)
        if vals is None:
            return
        self.metrics.setRowCount(len(names))
        for r, (n, v) in enumerate(zip(names, vals)):
            label = QTableWidgetItem(n)
            label.setToolTip(metric_tip(n))
            self.metrics.setItem(r, 0, label)
            cell = QTableWidgetItem(short_text(str(v), 22))
            cell.setToolTip(str(v))  # full text, also when the column is too narrow and Qt elides it
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.metrics.setItem(r, 1, cell)


# ------------------------------------------------------------------------------ scene settings
class SceneSettingsPanel(QScrollArea):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        w = QWidget()
        form = QFormLayout(w)
        sc, v = win.scene, win.scene.view

        def combo(options, current, apply):
            c = QComboBox()
            c.addItems(options)
            c.setCurrentText(current)
            c.currentTextChanged.connect(apply)
            return c

        def check(text, value, apply):
            c = QCheckBox(text)
            c.setChecked(value)
            c.toggled.connect(apply)
            return c

        form.addRow("배치", combo(["나란히", "겹쳐서"], "나란히" if v.side_by_side else "겹쳐서",
                                lambda t: setattr(v, "side_by_side", t == "나란히")))
        sp = QDoubleSpinBox()
        sp.setRange(0.3, 5.0)
        sp.setSingleStep(0.1)
        sp.setValue(v.spacing)
        sp.valueChanged.connect(lambda x: setattr(v, "spacing", float(x)))
        form.addRow("간격 (m)", sp)
        form.addRow(check("시작 위치·방향 맞춤", v.align, lambda on: setattr(v, "align", on)))
        form.addRow(check("사람 스켈레톤", v.show_humans, lambda on: setattr(v, "show_humans", on)))
        form.addRow("스켈레톤 위치", combo(["로봇 옆", "로봇과 겹쳐서"], "로봇 옆" if v.human_beside else "로봇과 겹쳐서",
                                     lambda t: setattr(v, "human_beside", t == "로봇 옆")))
        form.addRow("사람 표시", combo(["막대", "몸 메시 (SMPL-X)"], "몸 메시 (SMPL-X)" if v.body_mesh else "막대",
                                   lambda t: self._set(body_mesh=t.startswith("몸"))))
        form.addRow("로봇 표시", combo(["불투명", "반투명"], "반투명" if v.robot_translucent else "불투명",
                                   lambda t: self._set(robot_translucent=t == "반투명")))
        form.addRow(check("이름표", v.show_labels, lambda on: setattr(v, "show_labels", on)))
        form.addRow(check("균형 표시 (지지다각형·CoM·ZMP)", v.show_balance, lambda on: setattr(v, "show_balance", on)))
        cam = QPushButton("카메라 맞추기")
        cam.clicked.connect(sc.fit_camera)
        form.addRow(cam)
        self.setWidget(w)

    def _set(self, **kw) -> None:
        for k, val in kw.items():
            setattr(self.win.scene.view, k, val)
        self.win.scene.view_changed(*kw)


# ------------------------------------------------------------------------------ timeline
class TimelineTracks(QWidget):
    """Ruler, one bar per motion (its offset and length, falls in red) and the playhead."""
    NAME_W, RULER_H, ROW_H = 150, 22, 20

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setMinimumHeight(self.RULER_H + self.ROW_H)
        self.setMouseTracking(True)
        self._drag = False

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(600, self.RULER_H + self.ROW_H * max(1, len(self.win.scene.items)) + 4)

    def _span(self) -> tuple[float, float]:
        lo, hi = self.win.scene.time_range()
        return lo, max(hi, lo + 0.1)

    def _x(self, t: float) -> float:
        lo, hi = self._span()
        w = max(1, self.width() - self.NAME_W - 10)
        return self.NAME_W + (t - lo) / (hi - lo) * w

    def _t(self, x: float) -> float:
        lo, hi = self._span()
        w = max(1, self.width() - self.NAME_W - 10)
        return lo + (x - self.NAME_W) / w * (hi - lo)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.Base))
        text, grid = pal.color(QPalette.Text), pal.color(QPalette.Mid)
        lo, hi = self._span()
        step = next(s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120) if (hi - lo) / s <= 14)
        p.setPen(text)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        t = np.ceil(lo / step) * step
        while t <= hi + 1e-9:
            x = self._x(t)
            p.setPen(grid)
            p.drawLine(int(x), self.RULER_H - 6, int(x), self.height())
            p.setPen(text)
            p.drawText(int(x) + 3, self.RULER_H - 8, f"{t:g}s")
            t += step
        sc, sel = self.win.scene, self.win.selected
        for i, it in enumerate(list(sc.items)):
            y = self.RULER_H + i * self.ROW_H
            if it is sel:
                p.fillRect(0, y, self.width(), self.ROW_H, pal.color(QPalette.Highlight).darker(250))
            p.setPen(text)
            p.drawText(QRectF(6, y, self.NAME_W - 10, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft, it.label)
            dur = sc.shown(it).robot.duration
            c = QColor(*it.color)
            c.setAlpha(200 if it.visible else 70)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(self._x(it.offset), y + 4, max(2.0, self._x(it.offset + dur) - self._x(it.offset)),
                                     self.ROW_H - 8), 3, 3)
            p.setBrush(QColor(230, 40, 40))
            for ft, _cause in sc.falls(it):
                x = self._x(it.offset + ft)
                p.drawPolygon([QPointF(x - 4, y + 2), QPointF(x + 4, y + 2), QPointF(x, y + 9)])
        x = self._x(sc.t)
        p.setPen(QPen(QColor(255, 150, 40), 2))
        p.drawLine(int(x), 0, int(x), self.height())

    def mousePressEvent(self, e):
        if e.position().x() < self.NAME_W:  # click a name: select that motion
            i = int((e.position().y() - self.RULER_H) // self.ROW_H)
            items = self.win.scene.items
            if 0 <= i < len(items):
                self.win.select(items[i])
            return
        self._drag = True
        self.win.scene.set_playing(False)
        self.win.scene.seek(self._t(e.position().x()))

    def mouseMoveEvent(self, e):
        if self._drag:
            self.win.scene.seek(self._t(e.position().x()))
        else:
            ft = self._fall_at(e.position())
            self.setToolTip(ft or "")

    def mouseReleaseEvent(self, _):
        self._drag = False

    def _fall_at(self, pos) -> str:
        i = int((pos.y() - self.RULER_H) // self.ROW_H)
        items = self.win.scene.items
        if not 0 <= i < len(items):
            return ""
        it = items[i]
        for ft, cause in self.win.scene.falls(it):
            if abs(self._x(it.offset + ft) - pos.x()) < 6:
                return f"{it.label}: 넘어짐 {ft:.2f}s" + (f" · 1차 원인 {cause}" if cause else "")
        return ""


class TimelinePanel(QWidget):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        sc = win.scene
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        bar = QHBoxLayout()
        st = self.style()
        for icon, tip, fn in ((QStyle.SP_MediaSkipBackward, "처음으로 (Home)", lambda: sc.seek(0.0)),
                              (QStyle.SP_MediaSeekBackward, "이전 프레임 (←)", lambda: sc.step(-1))):
            b = QPushButton(st.standardIcon(icon), "")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.play = QPushButton(st.standardIcon(QStyle.SP_MediaPlay), "")
        self.play.setToolTip("재생 / 일시정지 (Space)")
        self.play.clicked.connect(sc.toggle_play)
        bar.addWidget(self.play)
        b = QPushButton(st.standardIcon(QStyle.SP_MediaSeekForward), "")
        b.setToolTip("다음 프레임 (→)")
        b.clicked.connect(lambda: sc.step(1))
        bar.addWidget(b)
        self.time = QLabel()
        self.time.setMinimumWidth(190)
        bar.addWidget(self.time)
        bar.addStretch(1)
        bar.addWidget(QLabel("속도"))
        speed = QDoubleSpinBox()
        speed.setRange(0.05, 4.0)
        speed.setSingleStep(0.05)
        speed.setValue(sc.view.speed)
        speed.setSuffix("x")
        speed.valueChanged.connect(lambda v: setattr(sc.view, "speed", float(v)))
        bar.addWidget(speed)
        loop = QCheckBox("반복")
        loop.setChecked(sc.view.loop)
        loop.toggled.connect(lambda on: setattr(sc.view, "loop", on))
        bar.addWidget(loop)
        lay.addLayout(bar)
        self.tracks = TimelineTracks(win)
        lay.addWidget(self.tracks, 1)
        self._last = (None, None)

    def refresh(self) -> None:
        sc = self.win.scene
        lo, hi = sc.time_range()
        fps = 30.0
        self.time.setText(f"{sc.t:6.2f} / {hi:.2f} s   (frame {int(round(sc.t * fps))})")
        self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause if sc.playing else QStyle.SP_MediaPlay))
        self.tracks.update()

    def relayout(self) -> None:
        self.tracks.updateGeometry()
        self.tracks.setMinimumHeight(self.tracks.sizeHint().height())


# ------------------------------------------------------------------------------ project browser
class ProjectPanel(QWidget):
    """Data folders on the left, motion files (with CMU descriptions) on the right."""

    def __init__(self, win: "EditorWindow", roots):
        super().__init__()
        self.win = win
        self.roots = list(roots or LIBRARY_ROOTS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 검색 (예: 143_11) 또는 동작 설명 검색 (예: walk, dance)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_files)
        top.addWidget(self.search, 1)
        for text, tip, fn in (("추가", "선택한 파일을 씬에 추가 (두 번 클릭도 됨)", self._add_selected),
                              ("파일 열기...", "PC의 아무 폴더에서 모션 파일 열기", win.open_dialog),
                              ("새로고침", "폴더를 다시 읽기", self.reload)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["폴더", "파일"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self._fill_files)
        split.addWidget(self.tree)
        self.files = QTableWidget(0, 3)
        self.files.setHorizontalHeaderLabels(["이름", "동작 (CMU 설명)", "폴더"])
        self.files.verticalHeader().setVisible(False)
        self.files.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.files.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.files.cellDoubleClicked.connect(lambda r, c: self._add_row(r))
        self.files.setDragEnabled(True)
        split.addWidget(self.files)
        split.setSizes([260, 700])
        lay.addWidget(split, 1)
        self._library: dict[str, list[str]] = {}
        self.reload()

    def reload(self) -> None:
        self._library = library_files(self.roots)
        self.tree.clear()
        nodes: dict[str, QTreeWidgetItem] = {}
        for folder, paths in self._library.items():
            parts = folder.split("/")
            parent = None
            for k in range(1, len(parts) + 1):
                key = "/".join(parts[:k])
                if key not in nodes:
                    node = QTreeWidgetItem([parts[k - 1], ""])
                    node.setData(0, Qt.UserRole, key)
                    (parent.addChild(node) if parent else self.tree.addTopLevelItem(node))
                    nodes[key] = node
                parent = nodes[key]
            nodes[folder].setText(1, str(len(paths)))
        for key, node in nodes.items():
            if key.count("/") <= 1:
                node.setExpanded(True)
        start = nodes.get("data/raw/cmu_bvh") or next(iter(nodes.values()), None)
        if start is not None:
            self.tree.setCurrentItem(start)
        self._fill_files()

    def _paths_in(self, key: str) -> list[str]:
        return [p for folder, ps in self._library.items() if folder == key or folder.startswith(key + "/") for p in ps]

    def _fill_files(self) -> None:
        q = self.search.text().strip().lower()
        if q:
            all_paths = [p for ps in self._library.values() for p in ps]
            hits = [p for p in all_paths if q in os.path.basename(p).lower() or q in cmu_labels.label_for(p).lower()]
            hits.sort(key=lambda p: not os.path.basename(p).lower().startswith(q))
            paths = hits[:500]
        else:
            cur = self.tree.currentItem()
            paths = self._paths_in(cur.data(0, Qt.UserRole)) if cur else []
            paths = paths[:2000]
        self.files.setRowCount(len(paths))
        for r, p in enumerate(paths):
            name = QTableWidgetItem(os.path.basename(p))
            name.setData(Qt.UserRole, p)
            name.setToolTip(rel(p))
            self.files.setItem(r, 0, name)
            self.files.setItem(r, 1, QTableWidgetItem(cmu_labels.label_for(p)))
            self.files.setItem(r, 2, QTableWidgetItem(os.path.relpath(os.path.dirname(p), ROOT).replace(os.sep, "/")))
        self.files.resizeColumnToContents(0)

    def _add_row(self, r: int) -> None:
        it = self.files.item(r, 0)
        if it is not None:
            self.win.add_paths([it.data(Qt.UserRole)])

    def _add_selected(self) -> None:
        rows = sorted({i.row() for i in self.files.selectedIndexes()})
        self.win.add_paths([self.files.item(r, 0).data(Qt.UserRole) for r in rows])


# ------------------------------------------------------------------------------ analysis
def nice_step(span: float, max_ticks: int = 8) -> float:
    raw = max(span, 1e-9) / max_ticks
    mag = 10 ** np.floor(np.log10(raw))
    return float(next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw))


class LinePlot(QWidget):
    """Light, fast curve plot (QPainter): drag to pan the time axis, wheel to zoom,
    double-click to ask for following the playhead again. matplotlib took ~100 ms a
    redraw on the GUI thread, which stalled the window (and the 3D view) while playing."""
    panned = Signal()  # the user moved / zoomed the view
    follow_requested = Signal()
    L, R, T, B = 52, 10, 22, 24  # margins

    def __init__(self):
        super().__init__()
        self.series: list[tuple[str, QColor, np.ndarray, np.ndarray]] = []
        self.title = ""
        self.x0, self.x1 = 0.0, 1.0
        self.head = 0.0
        self._ylim = (0.0, 1.0)
        self._drag = None
        self.setMinimumSize(240, 140)
        self.setToolTip("끌기: 시간축 이동 · 휠: 확대/축소 · 두 번 클릭: 타임라인 따라가기")

    def set_data(self, series, title: str) -> None:
        self.series, self.title = series, title
        ys = [y[np.isfinite(y)] for _, _, _, y in series if len(y)]
        ys = [y for y in ys if len(y)]
        lo, hi = (min(float(y.min()) for y in ys), max(float(y.max()) for y in ys)) if ys else (0.0, 1.0)
        pad = 0.06 * max(hi - lo, 1e-3)
        self._ylim = (lo - pad, hi + pad)
        self.update()

    def set_view(self, x0: float, x1: float, head: float) -> None:
        self.x0, self.x1, self.head = float(x0), float(max(x1, x0 + 1e-3)), float(head)
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(self.L, self.T, max(1, self.width() - self.L - self.R), max(1, self.height() - self.T - self.B))

    def paintEvent(self, _):
        p = QPainter(self)
        pal = self.palette()
        text, grid = pal.color(QPalette.Text), pal.color(QPalette.Mid)
        p.fillRect(self.rect(), pal.color(QPalette.Window))
        r = self._plot_rect()
        p.fillRect(r, pal.color(QPalette.Base))
        y0, y1 = self._ylim
        sx = r.width() / (self.x1 - self.x0)
        sy = r.height() / (y1 - y0)

        def X(t):
            return r.left() + (t - self.x0) * sx

        def Y(v):
            return r.bottom() - (v - y0) * sy

        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        for v in np.arange(np.ceil(self.x0 / (s := nice_step(self.x1 - self.x0))) * s, self.x1 + 1e-9, s):
            x = X(v)
            p.setPen(QPen(grid, 1, Qt.DotLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(text)
            p.drawText(QRectF(x - 30, r.bottom() + 2, 60, self.B - 4), Qt.AlignHCenter | Qt.AlignTop, f"{v:g}")
        for v in np.arange(np.ceil(y0 / (s := nice_step(y1 - y0, 5))) * s, y1 + 1e-9, s):
            y = Y(v)
            p.setPen(QPen(grid, 1, Qt.DotLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(text)
            p.drawText(QRectF(0, y - 8, self.L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:.3g}")
        p.drawText(QRectF(r.left(), 2, r.width(), self.T - 4), Qt.AlignHCenter | Qt.AlignVCenter, self.title)
        p.save()
        p.setClipRect(r)
        p.setRenderHint(QPainter.Antialiasing)
        for _, color, tt, y in self.series:
            if len(tt) < 2:
                continue
            i0, i1 = np.searchsorted(tt, [self.x0, self.x1])
            i0, i1 = max(0, i0 - 1), min(len(tt), i1 + 1)
            step = max(1, (i1 - i0) // max(1, int(r.width())))  # about one point per pixel
            xs, ys = X(tt[i0:i1:step]), Y(y[i0:i1:step])
            ok = np.isfinite(ys)
            p.setPen(QPen(color, 1.6))
            p.drawPolyline([QPointF(a, b) for a, b in zip(xs[ok], ys[ok])])
        p.setPen(QPen(QColor(255, 150, 40), 1.4, Qt.DashLine))
        hx = X(self.head)
        p.drawLine(QPointF(hx, r.top()), QPointF(hx, r.bottom()))
        p.restore()
        p.setPen(grid)
        p.drawRect(r)
        if self.series:  # legend, top right
            fm = p.fontMetrics()
            w = max(fm.horizontalAdvance(n) for n, *_ in self.series) + 26
            h = fm.height() * len(self.series) + 6
            box = QRectF(r.right() - w - 4, r.top() + 4, w, h)
            bg = pal.color(QPalette.Base)
            bg.setAlpha(200)
            p.fillRect(box, bg)
            for k, (name, color, *_rest) in enumerate(self.series):
                yy = box.top() + 3 + k * fm.height() + fm.height() / 2
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(box.left() + 4, yy), QPointF(box.left() + 18, yy))
                p.setPen(text)
                p.drawText(QPointF(box.left() + 22, yy + fm.ascent() / 2 - 1), name)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position().x(), self.x0, self.x1)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        x, a, b = self._drag
        dx = (e.position().x() - x) / self._plot_rect().width() * (b - a)
        if abs(e.position().x() - x) > 2:
            self.panned.emit()
            self.set_view(a - dx, b - dx, self.head)

    def mouseReleaseEvent(self, _):
        self._drag = None

    def mouseDoubleClickEvent(self, _):
        self.follow_requested.emit()

    def wheelEvent(self, e):
        r = self._plot_rect()
        factor = 0.8 if e.angleDelta().y() > 0 else 1.25
        t = self.x0 + (e.position().x() - r.left()) / r.width() * (self.x1 - self.x0)
        self.panned.emit()
        self.set_view(t - (t - self.x0) * factor, t + (self.x1 - t) * factor, self.head)


class AnalysisPanel(QWidget):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("기준"))
        self.ref = QComboBox()
        self.ref.currentIndexChanged.connect(lambda _: self.win.refresh_analysis())
        bar.addWidget(self.ref, 1)
        b = QPushButton("기준에 시간 자동 정렬")
        b.setToolTip("다리 관절각 차이가 가장 작아지는 시간 오프셋을 찾습니다")
        b.clicked.connect(self._align)
        bar.addWidget(b)
        bar.addWidget(QLabel("그래프"))
        self.key = QComboBox()
        self.key.currentIndexChanged.connect(lambda _: self.rebuild_chart())
        bar.addWidget(self.key, 1)
        self.follow = QPushButton("타임라인 따라가기")
        self.follow.setCheckable(True)
        self.follow.setChecked(True)
        self.follow.setStyleSheet("QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }")
        self.follow.setToolTip("켜 두면 타임라인을 재생하거나 옮길 때 그래프가 현재 시점을 가운데에 두고 따라 움직입니다. "
                               "그래프를 끌거나 휠로 확대·축소하면 꺼지고, 그래프를 두 번 클릭하면 다시 켜집니다")
        self.follow.toggled.connect(lambda _: self.update_view(force=True))
        bar.addWidget(self.follow)
        bar.addWidget(QLabel("구간"))
        self.window = QDoubleSpinBox()
        self.window.setRange(0.0, 600.0)
        self.window.setValue(10.0)
        self.window.setSuffix(" s")
        self.window.setToolTip("따라가기를 켰을 때 현재 시점 앞뒤로 보일 길이. 0 = 전체")
        self.window.valueChanged.connect(lambda _: self.update_view(force=True))
        bar.addWidget(self.window)
        bar.addWidget(help_button("지표 설명", metric_help_html()))
        lay.addLayout(bar)
        split = QSplitter()
        self.plot = LinePlot()
        self.plot.panned.connect(lambda: self.follow.setChecked(False))
        self.plot.follow_requested.connect(lambda: self.follow.setChecked(True))
        split.addWidget(self.plot)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setMaximumSectionSize(150)  # long verdicts are shortened, full text in tooltips
        rl.addWidget(self.table, 1)
        split.addWidget(right)
        split.setSizes([600, 500])
        lay.addWidget(split, 1)
        self._shown_t = None

    def showing(self) -> bool:
        """On screen (not behind another tab, not closed): only then is the chart redrawn."""
        return self.isVisible() and not self.visibleRegion().isEmpty()

    def ref_item(self) -> Item | None:
        key = self.ref.currentData()
        return self.win.item_by_id(key) if key is not None else None

    def refresh_lists(self) -> None:
        sc = self.win.scene
        cur_ref, cur_key = self.ref.currentData(), self.key.currentText()
        self.ref.blockSignals(True)
        self.ref.clear()
        for it in sc.items:
            self.ref.addItem(color_icon(it.color), it.label, id(it))
        i = self.ref.findData(cur_ref)
        self.ref.setCurrentIndex(i if i >= 0 else 0)
        self.ref.blockSignals(False)
        keys = sc.graph_keys()
        self.key.blockSignals(True)
        self.key.clear()
        self.key.addItems(keys)
        self.key.setCurrentText(cur_key if cur_key in keys else next((k for k in keys if "left_knee" in k), keys[0]))
        self.key.blockSignals(False)

    def _align(self) -> None:
        ref = self.ref_item()
        if ref is not None:
            notes = self.win.scene.auto_align(ref)
            self.win.status("시간 정렬: " + "; ".join(notes), 8000)

    def update_table(self) -> None:
        names, cols = self.win.scene.metric_table(self.ref_item())
        self.table.clear()
        self.table.setRowCount(len(names))
        self.table.setColumnCount(len(cols))
        self.table.setVerticalHeaderLabels(names)
        for r, n in enumerate(names):  # what each row measures, on hover
            self.table.verticalHeaderItem(r).setToolTip(metric_tip(n))
        for c, (it, vals) in enumerate(cols):
            head = QTableWidgetItem(f"■ {c + 1}")
            head.setForeground(QBrush(QColor(*it.color)))
            head.setToolTip(f"{it.label} ({it.kind})")
            self.table.setHorizontalHeaderItem(c, head)
            for r, v in enumerate(vals):
                cell = QTableWidgetItem(short_text(str(v)))
                cell.setToolTip(str(v))  # full text, also when the column is too narrow and Qt elides it
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, cell)
        self.table.resizeColumnsToContents()

    # ---------------------------------------------------------------- chart
    def rebuild_chart(self) -> None:
        """New curves (each motion in full; following only moves the x range)."""
        key = self.key.currentText()
        if not key:
            return
        series = [(it.label, QColor(*it.color), tt, y) for it, tt, y in self.win.scene.series(key, 0.0) if len(tt)]
        self.plot.set_data(series, key if key in GRAPH_FIXED else f"{key} [°]")
        self.update_view(force=True)

    def update_view(self, force: bool = False) -> None:
        """Move the playhead, and the time range too while following; skipped while off screen."""
        if not (force or self.showing()):
            return
        sc = self.win.scene
        if not force and sc.t == self._shown_t:
            return
        self._shown_t = sc.t
        if self.follow.isChecked():
            w = float(self.window.value())
            lo, hi = (sc.t - w / 2, sc.t + w / 2) if w > 0 else sc.time_range()
        else:  # where the user dragged / zoomed to
            lo, hi = self.plot.x0, self.plot.x1
        self.plot.set_view(lo, hi, sc.t)


def metric_tip(name: str) -> str:
    """Hover text of one metric row: its name and what it measures."""
    desc = METRIC_DESC.get(name)
    if not desc:
        return ""
    width = " width='360'" if len(desc) > 30 else ""  # long ones wrap at a readable width
    return f"<table{width}><tr><td><b>{escape(name)}</b><br>{escape(desc)}</td></tr></table>"


def metric_help_html() -> str:
    """Every metric by topic, as a two-column table (the analysis panel's help button)."""
    rows = []
    for section, items in METRIC_HELP:
        rows.append(f"<tr><td colspan='2' style='padding-top:8px; color:#7fb2ff'><b>{escape(section)}</b></td></tr>")
        rows += [f"<tr><td style='padding-right:12px' nowrap><b>{escape(n)}</b></td><td>{escape(d)}</td></tr>"
                 for n, d in items]
    return (f"<table width='620' cellspacing='0' cellpadding='2'>{''.join(rows)}</table>"
            f"<p style='color:#a0a0a8'>{escape(METRIC_HELP_FOOTER)} 표의 행 이름에 마우스를 올려도 설명이 나옵니다.</p>")


def help_button(text: str, html: str) -> QToolButton:
    """A '?' button that shows `html` on hover, and on click (no hover delay, stays longer)."""
    b = QToolButton()
    b.setText(text)
    b.setIcon(b.style().standardIcon(QStyle.SP_MessageBoxQuestion))
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    b.setToolTip(html)
    b.clicked.connect(lambda: QToolTip.showText(b.mapToGlobal(QPoint(0, b.height())), html, b, QRect(), 60000))
    return b


def short_text(v: str, limit: int = 18) -> str:
    """'넘어짐 1회; 보조 힘 > 체중 20%: 프레임 62.8%; ...' -> '넘어짐 1회 외 2' for narrow table cells."""
    parts = [p.strip() for p in v.split(";") if p.strip()]
    s = parts[0] + (f" 외 {len(parts) - 1}" if len(parts) > 1 else "") if parts else v
    return s if len(s) <= limit else s[:limit - 1] + "…"


# ------------------------------------------------------------------------------ main window
class EditorWindow(QMainWindow):
    def __init__(self, scene: MotionScene, url: str, library=None, accept_eula: bool = False):
        super().__init__()
        self.scene, self.url = scene, url
        self.selected: Item | None = None
        self.settings = app_settings()
        self.bridge = SceneBridge()
        self.bridge.event.connect(self._on_scene)
        self.bridge.added.connect(self._on_added)
        self.bridge.log.connect(self._append_log)
        scene.listen(lambda e, p: self.bridge.event.emit(e, p))
        base_log = scene.log
        scene.log = lambda msg: (base_log(msg), self.bridge.log.emit(str(msg)))  # also to the console panel
        scene.runner.log = scene.log  # Isaac job messages too
        self._eula = accept_eula or self.settings.value("isaac/eula_accepted", False, type=bool)
        scene.runner.accept_eula = self._eula
        self._loading = 0
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        self.view = SceneView(url)
        self.setCentralWidget(self.view)
        self.hierarchy = HierarchyPanel(self)
        self.inspector = InspectorPanel(self)
        self.scene_settings = SceneSettingsPanel(self)
        self.timeline = TimelinePanel(self)
        self.project = ProjectPanel(self, library)
        self.analysis = AnalysisPanel(self)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        self.console.setFont(QFont("Consolas", 9))
        self.docks: dict[str, QDockWidget] = {}
        self._build_docks()
        self._build_actions()
        self._build_status()
        self._default_state = self.saveState()
        geo, state = self.settings.value("window/geometry"), self.settings.value("window/state")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1600, 960)
        if state is not None:
            self.restoreState(state)

        # The scene is posed on its own thread at 30 Hz, so the window (and the embedded 3D view,
        # which Qt composites on this thread) never waits for it; the timer below only refreshes
        # the panels.
        self._ticking = True
        self._ticker = threading.Thread(target=self._tick_loop, name="scene-tick", daemon=True)
        self._ticker.start()
        self._last_ui = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        self._refresh_all()

    def _tick_loop(self, hz: float = 30.0) -> None:
        last = time.perf_counter()
        while self._ticking:
            now = time.perf_counter()
            try:
                self.scene.tick(now - last)
            except Exception as e:  # keep playing; report once per kind
                self.bridge.log.emit(f"scene tick failed: {type(e).__name__}: {e}")
            last = now
            time.sleep(max(0.002, 1.0 / hz - (time.perf_counter() - now)))

    # ---------------------------------------------------------------- layout
    def _dock(self, key: str, title: str, widget: QWidget, area) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(f"dock_{key}")  # saveState / restoreState need stable names
        d.setWidget(widget)
        self.addDockWidget(area, d)
        self.docks[key] = d
        return d

    def _build_docks(self) -> None:
        R, B = Qt.RightDockWidgetArea, Qt.BottomDockWidgetArea
        hier = self._dock("hierarchy", "계층", self.hierarchy, R)
        insp = self._dock("inspector", "인스펙터", self.inspector, R)
        sset = self._dock("scene", "씬 설정", self.scene_settings, R)
        self.splitDockWidget(hier, insp, Qt.Vertical)
        self.tabifyDockWidget(insp, sset)
        insp.raise_()
        tl = self._dock("timeline", "타임라인", self.timeline, B)
        proj = self._dock("project", "프로젝트", self.project, B)
        ana = self._dock("analysis", "분석", self.analysis, B)
        con = self._dock("console", "콘솔", self.console, B)
        self.splitDockWidget(tl, proj, Qt.Vertical)
        self.tabifyDockWidget(proj, ana)
        self.tabifyDockWidget(ana, con)
        proj.raise_()
        self.resizeDocks([hier, insp], [220, 520], Qt.Vertical)
        self.resizeDocks([hier], [420], Qt.Horizontal)
        self.resizeDocks([tl, proj], [110, 260], Qt.Vertical)

    def _build_actions(self) -> None:
        st, sc = self.style(), self.scene

        def act(text, fn, shortcut=None, icon=None, checkable=False, tip=None):
            a = QAction(text, self)
            if icon is not None:
                a.setIcon(st.standardIcon(icon))
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.ApplicationShortcut)
            a.setCheckable(checkable)
            if tip:
                a.setToolTip(tip)
                a.setStatusTip(tip)
            (a.toggled if checkable else a.triggered).connect(fn)
            return a

        self.a_open = act("열기...", self.open_dialog, "Ctrl+O", QStyle.SP_DialogOpenButton,
                          tip="모션 파일 열기 (BVH / FBX / AMASS SMPL-X npz / 로봇 npz·csv·pkl)")
        self.a_video = act("선택한 모션 동영상 저장", lambda: self.save_video(self.selected), "Ctrl+E",
                           QStyle.SP_DialogSaveButton, tip="선택한 모션을 Isaac Sim으로 녹화해 MP4로 저장")
        self.a_video_dir = act("동영상 폴더 열기", lambda: self.open_path(sc.opts.video_dir))
        self.a_quit = act("종료", self.close, "Ctrl+Q")
        self.a_remove = act("선택한 모션 제거", lambda: self.remove(self.selected), "Delete")
        self.a_remove_all = act("모두 제거", self.remove_all)
        self.a_play = act("재생 / 일시정지", sc.toggle_play, "Space", QStyle.SP_MediaPlay)
        self.a_home = act("처음으로", lambda: sc.seek(0.0), "Home", QStyle.SP_MediaSkipBackward)
        self.a_prev = act("이전 프레임", lambda: sc.step(-1), "Left", QStyle.SP_MediaSeekBackward)
        self.a_next = act("다음 프레임", lambda: sc.step(1), "Right", QStyle.SP_MediaSeekForward)
        self.a_physics = act("물리 모드 (Isaac PhysX)", self.set_physics, "P", QStyle.SP_ComputerIcon, checkable=True,
                             tip="켜면 각 로봇을 Isaac Sim PhysX가 시뮬레이션한 결과로 바꿔 그립니다(결과가 없으면 "
                                 "백그라운드에서 계산, 짧은 클립 약 1분)")
        self.a_cancel = act("Isaac 작업 취소", sc.cancel_jobs, icon=QStyle.SP_BrowserStop,
                            tip="대기 중이거나 돌고 있는 물리 계산과 동영상 녹화를 멈춥니다")
        self.a_fit = act("카메라 맞추기", sc.fit_camera, "F", QStyle.SP_DesktopIcon)
        self.a_reset = act("레이아웃 초기화", self.reset_layout)
        self.a_browser = act("브라우저에서 씬 열기", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.a_readme = act("README 열기", lambda: self.open_path(os.path.join(ROOT, "README.md")))
        self.a_labels = act("CMU 동작 라벨 목록", lambda: self.open_path(os.path.join(ROOT, "docs", "cmu_motion_labels.md")))
        self.a_about = act("정보", self._about)

        mb = self.menuBar()
        m = mb.addMenu("파일(&F)")
        for a in (self.a_open, None, self.a_video, self.a_video_dir, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("편집(&E)")
        m.addAction(self.a_remove)
        m.addAction(self.a_remove_all)
        m = mb.addMenu("보기(&V)")
        for d in self.docks.values():
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        for a in (self.a_fit, self.a_reset, self.a_browser):
            m.addAction(a)
        m = mb.addMenu("재생(&P)")
        for a in (self.a_play, self.a_home, self.a_prev, self.a_next):
            m.addAction(a)
        m = mb.addMenu("물리(&S)")
        m.addAction(self.a_physics)
        sub = m.addMenu("골반 보조 힘")
        grp = QActionGroup(self)
        self.a_assist = {}
        for val, label in ASSIST_LABELS.items():
            a = QAction(label, self, checkable=True)
            a.setChecked(val == sc.assist)
            a.triggered.connect(lambda _=False, v=val: sc.set_assist(v))
            grp.addAction(a)
            sub.addAction(a)
            self.a_assist[val] = a
        m.addAction(self.a_cancel)
        m = mb.addMenu("도움말(&H)")
        for a in (self.a_readme, self.a_labels, self.a_about):
            m.addAction(a)

        tb = QToolBar("도구", self)
        tb.setObjectName("toolbar_main")
        tb.setMovable(True)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_open, None, self.a_home, self.a_prev, self.a_play, self.a_next, None, self.a_physics,
                  self.a_cancel, None, self.a_fit, self.a_video):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.st_physics = QLabel()
        self.st_jobs = QLabel()
        self.st_time = QLabel()
        for w in (self.st_jobs, self.st_physics, self.st_time):
            w.setContentsMargins(8, 0, 8, 0)
            sb.addPermanentWidget(w)

    def reset_layout(self) -> None:
        self.restoreState(self._default_state)
        for d in self.docks.values():
            d.show()

    # ---------------------------------------------------------------- selection / items
    def item_by_id(self, key) -> Item | None:
        return next((it for it in self.scene.items if id(it) == key), None)

    def select(self, item: Item | None) -> None:
        self.selected = item
        self.hierarchy.select(item)
        self.inspector.show_item(item)
        self.docks["inspector"].raise_()
        self.timeline.tracks.update()
        self.a_video.setEnabled(item is not None)
        self.a_remove.setEnabled(item is not None)

    def remove(self, item: Item | None) -> None:
        if item is not None:
            self.scene.remove(item)

    def remove_all(self) -> None:
        for it in list(self.scene.items):
            self.scene.remove(it)

    def add_paths(self, paths: list[str]) -> None:
        """Load motion files in the background (retargeting can take tens of seconds)."""
        paths = [p for p in paths if p]
        if not paths:
            return
        self._loading += len(paths)
        self.status(f"불러오는 중: {', '.join(os.path.basename(p) for p in paths)} (처음 리타게팅하는 사람 모션이면 수십 초)")

        def work():
            for p in paths:
                try:
                    self.bridge.added.emit(self.scene.add(p))
                except Exception as e:
                    self.bridge.added.emit(f"{os.path.basename(p)}: {type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True, name="add-motion").start()

    def _on_added(self, result) -> None:
        self._loading = max(0, self._loading - 1)
        if isinstance(result, Item):
            self.status(f"추가됨: {result.label}", 5000)
            self.select(result)
            if len(self.scene.items) == 1 or self._loading == 0:
                self.scene.fit_camera()
        else:
            self.status(f"열지 못함: {result}", 10000)
            QMessageBox.warning(self, "모션을 열지 못했습니다", str(result))

    def open_dialog(self) -> None:
        pats = " ".join(f"*{e}" for e in MOTION_EXT)
        paths, _ = QFileDialog.getOpenFileNames(self, "모션 파일 열기", self.settings.value("dialog/dir", ROOT),
                                                f"모션 파일 ({pats});;모든 파일 (*)")
        if paths:
            self.settings.setValue("dialog/dir", os.path.dirname(paths[0]))
            self.add_paths(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(MOTION_EXT)]
        else:  # rows dragged from the project panel
            paths = [self.project.files.item(i.row(), 0).data(Qt.UserRole) for i in self.project.files.selectedIndexes()
                     if i.column() == 0]
        self.add_paths(paths)

    # ---------------------------------------------------------------- physics / video
    def _ensure_eula(self) -> bool:
        """Isaac Sim runs only after the user accepted NVIDIA's license (asked once)."""
        if self._eula:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Isaac Sim 라이선스 동의")
        box.setIcon(QMessageBox.Question)
        box.setTextFormat(Qt.RichText)
        box.setText("물리 계산과 동영상 녹화는 PC에 설치된 NVIDIA Isaac Sim을 실행합니다.<br>"
                    f"계속하려면 <a href='{EULA_URL}'>NVIDIA Omniverse License Agreement</a>에 동의해야 합니다.<br><br>"
                    "동의하십니까? (한 번 동의하면 다시 묻지 않습니다)")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("동의")
        box.button(QMessageBox.No).setText("취소")
        if box.exec() != QMessageBox.Yes:
            return False
        self._eula = True
        self.settings.setValue("isaac/eula_accepted", True)
        self.scene.runner.accept_eula = True
        return True

    def set_physics(self, on: bool) -> None:
        if on and not self._ensure_eula():
            self.a_physics.blockSignals(True)
            self.a_physics.setChecked(False)
            self.a_physics.blockSignals(False)
            return
        self.scene.set_physics(on, "editor")

    def save_video(self, item: Item | None) -> None:
        if item is None or not self._ensure_eula():
            return
        try:
            job = self.scene.save_video(item)
        except Exception as e:  # Isaac Sim not found
            QMessageBox.warning(self, "동영상을 저장할 수 없습니다", f"{type(e).__name__}: {e}")
            return
        self.status(f"동영상 {'대기열에 추가' if job.active else '이미 있음'}: {item.label}", 6000)

    @staticmethod
    def open_path(path: str | None) -> None:
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

    # ---------------------------------------------------------------- refresh
    def status(self, text: str, ms: int = 0) -> None:
        self.statusBar().showMessage(text, ms)

    def _append_log(self, text: str) -> None:
        self.console.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def _on_scene(self, event: str, payload) -> None:
        if event == "items":
            if self.selected is not None and self.selected not in self.scene.items:
                self.select(None)
            self.hierarchy.rebuild()
            self.analysis.refresh_lists()
            self.timeline.relayout()
            self.refresh_analysis()
        elif event in ("item", "status"):
            self.hierarchy.refresh()
            self.inspector.refresh()
            self.refresh_analysis()
            self._refresh_status()
        elif event == "log":
            self._append_log(str(payload))
        self.timeline.refresh()

    def refresh_analysis(self) -> None:
        self.analysis.update_table()
        self.analysis.rebuild_chart()
        self.inspector.refresh()

    def _refresh_status(self) -> None:
        sc = self.scene
        self.st_physics.setText(f"물리 모드: {'켜짐 (보조 힘 x' + format(sc.assist, 'g') + ')' if sc.physics_on else '꺼짐'}")
        jobs = sc.jobs_summary()
        self.st_jobs.setText(f"Isaac 작업: {jobs}" if jobs else "Isaac 작업 없음")
        if self.a_physics.isChecked() != sc.physics_on:
            self.a_physics.blockSignals(True)
            self.a_physics.setChecked(sc.physics_on)
            self.a_physics.blockSignals(False)
        for val, a in self.a_assist.items():
            a.setChecked(val == sc.assist)

    def _refresh_all(self) -> None:
        self.hierarchy.rebuild()
        self.analysis.refresh_lists()
        self.refresh_analysis()
        self._refresh_status()
        self.timeline.refresh()

    def _tick(self) -> None:
        """Panel refresh (the scene itself is posed on the scene-tick thread)."""
        now = time.perf_counter()
        prev, self._last_ui = self._last_ui, now
        sc = self.scene
        self.timeline.refresh()
        self.st_time.setText(f"t = {sc.t:.2f} s")
        if self._play_icon != sc.playing:
            self._play_icon = sc.playing
            self.a_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause if sc.playing else QStyle.SP_MediaPlay))
        self.analysis.update_view()  # follows the playhead; skipped when the 분석 tab is not on screen
        if sc.runner.busy() and int(now * 2) != int(prev * 2):  # job progress, twice a second
            self.hierarchy.refresh()
            self.inspector.refresh(metrics=False)
            self._refresh_status()

    _play_icon = None

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b><br>{APP_TAGLINE}<br>K-Humanoid 프로젝트<br><br>"
                                          f"씬: viser ({self.url})<br>물리·녹화: NVIDIA Isaac Sim (PhysX)")

    def closeEvent(self, e):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.timer.stop()
        self._ticking = False
        self._ticker.join(timeout=1.0)
        self.scene.runner.shutdown()
        super().closeEvent(e)


def run(argv=None) -> int:
    import argparse
    import sys

    import viser

    from .scene import add_scene_arguments, load_robot_urdf, scene_options

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scene_arguments(ap)
    ap.add_argument("--port", type=int, default=0, help="port of the embedded scene server (0 = any free port)")
    ap.add_argument("--light", action="store_true", help="light theme (default: dark, like most editors)")
    ap.add_argument("--screenshot", default=None, help="save a window screenshot here after --quit-after seconds")
    ap.add_argument("--quit-after", type=float, default=0.0, help="close after N seconds (smoke tests)")
    args = ap.parse_args(argv)

    no_sandbox = webengine_sandbox_workaround()  # before QApplication / the first web view
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    if not args.light:
        app.setPalette(dark_palette())

    def log(msg: str) -> None:
        print(f"[editor] {msg}", flush=True)

    if no_sandbox:
        log("scene view: Chromium sandbox off (conda Qt layout); it only shows the local scene server")
    port = args.port or free_port()
    urdf = load_robot_urdf(args.urdf, args.mesh_cell, log=log)
    server = viser.ViserServer(host="127.0.0.1", port=port, label=APP_NAME, verbose=False)
    scene = MotionScene(server, urdf, scene_options(args), log=log)
    if args.body_mesh:
        scene.view.body_mesh = True
    server.initial_camera.position = (3.0, -3.0, 1.8)
    server.initial_camera.look_at = (0.0, 0.0, 0.75)
    url = f"http://127.0.0.1:{port}/?hideViserLogo"
    win = EditorWindow(scene, url, args.library, accept_eula=args.isaac_accept_eula)
    win.show()
    if args.physics:
        win.a_physics.setChecked(True)
    win.add_paths(args.inputs)
    win.view.loadFinished.connect(lambda ok: scene.log(
        f"scene view {'loaded' if ok else 'FAILED to load'}: {win.view.url().toString()}"))
    if args.quit_after > 0:
        if args.screenshot:  # keep the window on top so the screen capture shows it, 3D view included
            win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            win.show()

        def finish():
            if args.screenshot:
                win.raise_()
                win.activateWindow()
                g = win.frameGeometry()
                app.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height()).save(args.screenshot)
            win.close()

        QTimer.singleShot(int(args.quit_after * 1000), finish)
    code = app.exec()
    scene.runner.shutdown()
    server.stop()
    return code
