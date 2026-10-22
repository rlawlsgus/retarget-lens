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
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter,
                           QPalette, QPen, QPixmap)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox,
                               QSplitter,
                               QStyle, QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QToolTip, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import cmu_labels
from .. import paths as app_paths  # "paths" is a common local name here
from .. import settings
from ..compare import MOTION_EXT, Item, library_files
from .scene import (BALANCE, GRAPH_FIXED, METRIC_DESC, METRIC_HELP, METRIC_HELP_FOOTER, RETARGET_NOTE, RETARGET_TIPS,
                    SWING_CLEARANCE_CM, MotionScene, rel)

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
BALANCE_TIPS = {
    "isaac": "Isaac Sim PhysX에서 골반 보조 힘(가상 하네스)이 균형을 대신 잡습니다(지금까지의 물리 모드). "
             "배율은 '물리 > 골반 보조 힘 (Isaac)'에서 바꿉니다",
    "pd": "MuJoCo에서 리타겟 관절각을 높은 게인의 PD로 그대로 따라갑니다. 균형 제어도 보조 힘도 없어 걷기도 대부분 "
          "1–2초 안에 넘어집니다(Isaac 보조 힘 끔과 같은 개루프 재생)",
    "gmt": "MuJoCo에서 공개된 G1 범용 추적 정책 GMT가 기준 동작과 로봇 자신의 상태를 보고 관절 목표를 냅니다"
           "(실제 로봇이 모캡을 따라 하는 방식). 보조 힘은 없습니다",
}


def webengine_sandbox_workaround() -> bool:
    """In a conda env Qt keeps QtWebEngineProcess.exe in Library/lib/qt6 and its DLLs in
    Library/bin; Chromium's sandboxed renderer cannot load them from there and crashes
    (0xC0000135). Turn the sandbox off in that layout only (a packaged build ships them side
    by side); the view shows nothing but the local scene server (ScenePage). Returns True
    when it was turned off.

    The packaged build (packaging/retlens.spec) puts a copy of QtWebEngineProcess.exe next to
    the Qt DLLs at the bundle's top and points Qt at it, so it runs sandboxed."""
    from PySide6.QtCore import QLibraryInfo

    if app_paths.FROZEN and not os.environ.get("QTWEBENGINE_DISABLE_SANDBOX"):
        top = getattr(__import__("sys"), "_MEIPASS", "")
        proc = os.path.join(top, "QtWebEngineProcess.exe")
        if os.path.isfile(proc) and os.path.isfile(os.path.join(top, "Qt6WebEngineCore.dll")):
            os.environ.setdefault("QTWEBENGINEPROCESS_PATH", proc)
            return False
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


# The repository's editor and the installed RetLens share one QSettings store. The Isaac EULA consent is
# the user's either way; the window layout, the file dialog's folder and the first-run check are per layout,
# so one program closing last no longer decides the other's layout.
LAYOUT_KEYS = ("window/geometry", "window/state", "layout/has_compare", "dialog/dir", "setup/checked")


def layout_key(key: str) -> str:
    """The QSettings key for this layout: as is in the installed program, under dev/ from the repository."""
    return key if app_paths.INSTALLED else f"dev/{key}"


def split_layout_settings(s: QSettings) -> None:
    """Once, from the repository: start the dev/ keys from the values both programs shared until now."""
    if app_paths.INSTALLED or s.value("dev/split", False, type=bool):
        return
    for k in LAYOUT_KEYS:
        if s.contains(k) and not s.contains(layout_key(k)):
            s.setValue(layout_key(k), s.value(k))
    s.setValue("dev/split", True)


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


class _GuiInvoker(QObject):
    """Runs a callable on the GUI thread for another thread and waits for it (the AI API)."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.BlockingQueuedConnection)

    @staticmethod
    def _run(box: dict) -> None:
        try:
            box["result"] = box["fn"]()
        except Exception as e:  # handed back to the caller
            box["error"] = e


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
            text = sc.job_text(it) if (sc.physics_on or it.handles.get("phys") or sc.is_sim_result(it)) else ""
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
        m.addAction("겹쳐 비교: 기준(A)으로", lambda: self.win.start_compare(ref=it))
        m.addAction("겹쳐 비교: 대상(B)으로", lambda: self.win.start_compare(item=it))
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

        lay.addWidget(self._section("물리"))
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
        if sc.is_sim_result(it):
            text = sc.job_text(it)
        else:  # this mode's state, then what the other modes gave (they are kept: switching back is instant)
            text = (f"균형 제어: {sc.mode_label()}\n{sc.job_text(it)}" if sc.physics_on
                    else "물리 모드가 꺼져 있습니다(툴바나 물리 메뉴에서 켭니다).")
            others = [(m, r) for m, r in sc.results_overview(it) if not (sc.physics_on and m == sc.mode_label())]
            if others:
                text += "\n\n계산해 둔 다른 결과:\n" + "\n".join(f"· {m}: {r}" for m, r in others)
        self.phys.setText(text)
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
        it, sc = items[i], self.win.scene
        why = "판정" if sc.is_policy_result(sc.shown(it)) else "1차 원인"  # MuJoCo: the fall rule, not a diagnosis
        for ft, cause in sc.falls(it):
            if abs(self._x(it.offset + ft) - pos.x()) < 6:
                return f"{it.label}: 넘어짐 {ft:.2f}s" + (f" · {why} {cause}" if cause else "")
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
        self._fixed_roots = list(roots) if roots else None  # --library; else the 환경 설정 folders
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

    @property
    def roots(self) -> list[str]:
        return self._fixed_roots or settings.library_dirs()

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
            self.files.setItem(r, 2, QTableWidgetItem(rel(os.path.dirname(p)).replace(os.sep, "/")))
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


# ------------------------------------------------------------------------------ overlay comparison
REGION_COLORS = {"전체 (부위 평균)": QColor(235, 235, 240), "몸통·머리": QColor(160, 160, 175), "왼팔": QColor(90, 170, 255),
                 "오른팔": QColor(255, 120, 90), "왼다리": QColor(80, 205, 140), "오른다리": QColor(235, 195, 60)}
COMPARE_HELP = [
    ("맞춤", "대상(B)의 골반을 기준(A)의 골반 위치로 옮깁니다. '골반 위치 + 방향'이면 골반이 향한 방향(수직축 회전)도 "
           "A에 맞춥니다. 걸어간 경로·방향의 차이는 빠지고 자세의 차이만 남습니다."),
    ("색", "A는 회색 반투명으로 그립니다. B는 A와의 거리가 허용 오차를 넘는 부위만 그리고, 노랑(허용 오차) → 주황(2배) → "
          "빨강(3배 이상)으로 칠합니다. 회색만 보이는 곳은 두 모션이 겹치는 곳이고, 색이 칠해진 B 부위 옆의 회색이 A가 있던 자리입니다."),
    ("부위 차이", "로봇 부품(고정 관절로 붙은 링크 묶음, G1은 30개)마다 중심과 바깥쪽 점 12개를 두 자세에서 비교한 평균 거리(cm)."),
    ("그래프·표", "둘이 함께 재생되는 구간의 시간에 따른 차이입니다. '전체'는 부품 평균, 부위별 선은 그 부위에서 가장 많이 벗어난 "
               "부품입니다. 표는 부위별 평균·최대·최대 시각·허용 오차를 넘은 시간 비율이고, 행을 두 번 클릭하면 그 시각으로 갑니다."),
    ("시간·물리", "모션별 시간 오프셋과 물리 모드(시뮬레이션 결과)를 그대로 따릅니다. 분석 탭의 '기준에 시간 자동 정렬'로 "
               "시간을 먼저 맞추면 비교가 정확해집니다."),
]


def compare_help_html() -> str:
    rows = "".join(f"<tr><td style='padding-right:12px' nowrap><b>{escape(n)}</b></td><td>{escape(d)}</td></tr>"
                   for n, d in COMPARE_HELP)
    return f"<table width='560' cellspacing='0' cellpadding='3'>{rows}</table>"


class DiffLegend(QWidget):
    """Colour key of the overlay comparison: grey ghost = overlapping, yellow -> red = how far B is off."""

    def __init__(self):
        super().__init__()
        self.tol = 3.0
        self.setMinimumSize(420, 26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_tol(self, tol: float) -> None:
        self.tol = tol
        self.update()

    def paintEvent(self, _):
        from PySide6.QtGui import QLinearGradient

        from .scene import DIFF_COLORS, GHOST_COLOR

        p = QPainter(self)
        p.setPen(self.palette().color(QPalette.Text))
        fm = p.fontMetrics()
        h = self.height()
        x = 0
        ghost = QColor(*GHOST_COLOR)
        ghost.setAlpha(120)
        p.fillRect(QRectF(x, 5, 16, h - 10), ghost)
        x += 20
        text = f"겹침 (A, {self.tol:g} cm 이내)"
        p.drawText(QPointF(x, h / 2 + fm.ascent() / 2 - 1), text)
        x += fm.horizontalAdvance(text) + 14
        w = 150
        g = QLinearGradient(x, 0, x + w, 0)
        for stop, c in zip((0.0, 0.5, 1.0), DIFF_COLORS):
            g.setColorAt(stop, QColor(*c))
        p.fillRect(QRectF(x, 5, w, h - 10), g)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        p.setPen(QColor(20, 20, 20))
        for frac, k in ((0.02, 1), (0.5, 2), (0.98, 3)):
            label = f"{k * self.tol:g}" + ("+" if k == 3 else "")
            tw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(QPointF(x + frac * w - frac * tw, h / 2 + p.fontMetrics().ascent() / 2 - 1), label)
        p.setPen(self.palette().color(QPalette.Text))
        p.setFont(self.font())
        p.drawText(QPointF(x + w + 6, h / 2 + fm.ascent() / 2 - 1), "cm 벗어남 (B)")


class ComparePanel(QWidget):
    """겹쳐 비교 (overlay comparison): B on A's pelvis, A a translucent ghost, B's parts that are
    off by more than the tolerance coloured; the difference over time and per body region."""

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.toggle = QPushButton("겹쳐 보기")
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet("QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }")
        self.toggle.setToolTip("켜면 대상(B)을 기준(A)의 골반 위치에 겹쳐 그립니다 (단축키 O)")
        self.toggle.toggled.connect(self._toggled)
        bar.addWidget(self.toggle)
        bar.addWidget(QLabel("기준 A"))
        self.ref = QComboBox()
        self.ref.setToolTip("회색 반투명으로 그릴 모션")
        bar.addWidget(self.ref, 1)
        swap = QToolButton()
        swap.setText("⇄")
        swap.setToolTip("A와 B 바꾸기")
        swap.clicked.connect(self._swap)
        bar.addWidget(swap)
        bar.addWidget(QLabel("대상 B"))
        self.item = QComboBox()
        self.item.setToolTip("A의 골반 위치로 옮겨, 벗어난 부위만 색칠해 그릴 모션")
        bar.addWidget(self.item, 1)
        for combo in (self.ref, self.item):
            combo.currentIndexChanged.connect(lambda _: self._pair_changed())
        bar.addWidget(QLabel("맞춤"))
        self.align = QComboBox()
        self.align.addItems(["골반 위치 + 방향", "골반 위치만"])
        self.align.currentIndexChanged.connect(lambda i: self.win.scene.set_compare(heading=(i == 0)))
        bar.addWidget(self.align)
        bar.addWidget(QLabel("허용 오차"))
        self.tol = QDoubleSpinBox()
        self.tol.setRange(0.5, 50.0)
        self.tol.setSingleStep(0.5)
        self.tol.setValue(self.win.scene.compare.tol_cm)
        self.tol.setSuffix(" cm")
        self.tol.setToolTip("이보다 적게 벗어난 B 부위는 그리지 않습니다(A의 회색만 보임)")
        self.tol.valueChanged.connect(lambda v: self.win.scene.set_compare(tol_cm=v))
        bar.addWidget(self.tol)
        bar.addWidget(help_button("보는 법", compare_help_html()))
        lay.addLayout(bar)
        row = QHBoxLayout()
        self.legend = DiffLegend()
        row.addWidget(self.legend)
        self.now = QLabel()
        row.addWidget(self.now, 1)
        lay.addLayout(row)
        split = QSplitter()
        self.plot = LinePlot()
        self.plot.setToolTip("끌기: 시간축 이동 · 휠: 확대/축소 · 두 번 클릭: 전체 구간")
        self.plot.follow_requested.connect(self._full_view)
        split.addWidget(self.plot)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["부위", "평균 (cm)", "최대 (cm)", "최대 시각 (s)", "허용 오차 넘음 (%)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setToolTip("행을 두 번 클릭하면 그 부위가 가장 많이 벗어난 시각으로 갑니다")
        self.table.cellDoubleClicked.connect(self._seek_row)
        split.addWidget(self.table)
        split.setSizes([620, 480])
        lay.addWidget(split, 1)
        self._filling = False
        self._now_text = None

    def showing(self) -> bool:
        return self.isVisible() and not self.visibleRegion().isEmpty()

    # ---------------------------------------------------------------- state
    def _combo_item(self, combo: QComboBox) -> Item | None:
        key = combo.currentData()
        return self.win.item_by_id(key) if key is not None else None

    def _toggled(self, on: bool) -> None:
        if not self._filling:
            self.win.start_compare(on=on)

    def _pair_changed(self) -> None:
        if self._filling:
            return
        a, b = self._combo_item(self.ref), self._combo_item(self.item)
        if a is not None and a is b:  # keep them different: move B to another motion
            b = next((it for it in self.win.scene.items if it is not a), None)
        self.win.scene.set_compare(ref=a, item=b)

    def _swap(self) -> None:
        c = self.win.scene.compare
        self.win.scene.set_compare(ref=c.item, item=c.ref)

    def refresh(self) -> None:
        """Controls follow the scene's comparison; the graph and table are rebuilt."""
        sc, c = self.win.scene, self.win.scene.compare
        self._filling = True
        for combo, cur in ((self.ref, c.ref), (self.item, c.item)):
            combo.clear()
            for it in sc.items:
                combo.addItem(color_icon(it.color), it.label, id(it))
            i = combo.findData(id(cur)) if cur is not None else -1
            combo.setCurrentIndex(i if i >= 0 else (1 if combo is self.item and combo.count() > 1 else 0))
        self.toggle.setChecked(sc.compare_pair() is not None)
        self.align.setCurrentIndex(0 if c.heading else 1)
        if abs(self.tol.value() - c.tol_cm) > 1e-9:
            self.tol.setValue(c.tol_cm)
        self._filling = False
        self.legend.set_tol(c.tol_cm)
        self.rebuild()

    def rebuild(self) -> None:
        sc = self.win.scene
        s = sc.compare_series() if sc.compare_pair() is not None else None
        self.table.setRowCount(0)
        if s is None or not len(s["t"]):
            self.plot.set_data([], "겹쳐 보기를 켜면 B − A 부위 차이(cm)가 시간에 따라 나옵니다"
                               if s is None else "두 모션이 함께 재생되는 구간이 없습니다 (시간 오프셋 확인)")
            self.plot.set_view(*sc.time_range(), sc.t)
            return
        t, tol = s["t"], sc.compare.tol_cm
        series = [("전체 (부위 평균)", REGION_COLORS["전체 (부위 평균)"], t, s["mean"])]
        series += [(r, REGION_COLORS.get(r, QColor(200, 200, 200)), t, v) for r, v in s["regions"].items()]
        series.append((f"허용 오차 {tol:g} cm", QColor(130, 130, 140), t, np.full(len(t), tol)))
        self.plot.set_data(series, "B − A 부위 차이 (cm), 골반 맞춤")
        self._full_view()
        rows = sc.compare_table()
        self.table.setRowCount(len(rows))
        for r, vals in enumerate(rows):
            for col, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if col == 0:
                    cell.setIcon(color_icon(REGION_COLORS.get(v, QColor(200, 200, 200)).getRgb()[:3]))
                else:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, cell)
        self.table.resizeColumnsToContents()

    def _full_view(self) -> None:
        s = self.win.scene.compare_series()
        if s is not None and len(s["t"]) > 1:
            self.plot.set_view(float(s["t"][0]), float(s["t"][-1]), self.win.scene.t)

    def _seek_row(self, row: int, _col: int) -> None:
        cell = self.table.item(row, 3)
        if cell is not None:
            self.win.scene.set_playing(False)
            self.win.scene.seek(float(cell.text()))

    def update_live(self) -> None:
        """Playhead and the drawn frame's numbers (GUI timer); skipped while off screen."""
        if not self.showing():
            return
        sc = self.win.scene
        self.plot.set_view(self.plot.x0, self.plot.x1, sc.t)
        now = sc.compare_now
        if sc.compare_pair() is None:
            text = "꺼짐: 툴바의 '겹쳐 비교'(O)나 이 탭의 '겹쳐 보기'로 켭니다. 계층 패널 우클릭으로 A·B를 고를 수도 있습니다."
        elif now is None:
            text = "지금 시각에는 A나 B가 보이지 않습니다(숨김)."
        else:
            worst = now["worst"]
            text = (f"지금 {sc.t:.2f} s · 평균 {now['mean']:.1f} cm · 허용 오차 넘은 부품 {now['over']}/{now['parts']}"
                    + (f" · 가장 큰 차이: {worst} {now['regions'][worst]:.1f} cm" if worst else ""))
        if text != self._now_text:
            self._now_text = text
            self.now.setText(text)


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


# ------------------------------------------------------------------------------ settings
OK_COLOR, WARN_COLOR, BAD_COLOR = "#5cb85c", "#e0a030", "#e05050"


def check_html(c: settings.Check) -> str:
    """One line of a check: ✓ what was found, or ⚠/✗ what is missing, what it is for and how to fix it."""
    if c.ok:
        what = c.detail or c.path
        return f"<span style='color:{OK_COLOR}'>✓</span> {escape(what)}" + (
            f" <span style='color:gray'>({escape(c.path)})</span>" if c.path and c.detail and c.key != "library" else "")
    color, mark = (BAD_COLOR, "✗") if c.required else (WARN_COLOR, "⚠")
    text = f"<span style='color:{color}'>{mark} {escape(c.detail or '없음')}</span>"
    if c.needed_for:
        text += f"<br><span style='color:gray'>쓸 수 없는 기능: {escape(c.needed_for)}</span>"
    if c.hint:
        text += f"<br><span style='color:gray'>{escape(c.hint)}</span>"
    return text


class SettingsDialog(QDialog):
    """환경 설정: where the external programs and the folders are, each checked as it is typed.
    Empty fields mean "find it" (environment variables, the usual install places)."""
    ROWS = [  # key, label, picks a file (filter) or a folder (None), settings field
        ("isaac", "Isaac Sim", "Isaac Sim python.bat (python.bat);;모든 파일 (*)", "isaac_python"),
        ("blender", "Blender 4.5", "blender.exe (blender.exe);;모든 파일 (*)", "blender"),
        ("smpl", "SMPL-X 모델 폴더", None, "smpl_model_dir"),
        ("gmt", "GMT 폴더", None, "gmt_dir"),
        ("robot_usd", "로봇 USD (선택)", "USD (*.usd *.usda *.usdc *.usdz);;모든 파일 (*)", "robot_usd"),
        ("video", "동영상 저장 폴더", None, "video_dir"),
    ]
    TIPS = {"isaac": "물리 모드와 동영상 저장에 씁니다. 설치 폴더(python.bat이 있는 곳)나 python.bat을 고르세요.",
            "robot_usd": "Isaac이 시뮬레이션·녹화에 쓰는 로봇 USD입니다. 비우면 NVIDIA 에셋 서버의 Unitree G1을 받아 씁니다"
                         "(인터넷 필요). 오프라인이면 로컬에 둔 G1 USD(참조 파일 포함)나 사내 Nucleus 주소를 지정하세요. "
                         "바꾸면 물리 결과를 따로 계산합니다.",
            "blender": "FBX 파일을 읽을 때 씁니다. blender.exe를 고르세요.",
            "smpl": "AMASS SMPL-X 파일을 열 때 씁니다. smplx\\SMPLX_NEUTRAL.npz가 들어 있는 폴더를 고르세요.",
            "gmt": "물리 모드의 균형 제어 '추적 정책 (GMT)'에 씁니다. assets\\pretrained_checkpoints\\pretrained.pt가 있는 "
                   "GMT 폴더를 고르세요(설치 도우미가 받으면 자동으로 채워짐).",
            "video": "'동영상 저장'이 MP4를 쓰는 폴더입니다."}

    def __init__(self, win: "EditorWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(f"{APP_NAME} 환경 설정")
        self.resize(900, 700)
        s = settings.load(reload=True)
        self._loaded = settings.load(reload=True)  # what the fields started from (_merge_saved)
        lay = QVBoxLayout(self)
        intro = QLabel("비워 두면 자동으로 찾습니다(환경변수, 기본 설치 위치). 찾지 못한 항목은 그 기능만 쓸 수 없고, "
                       "나머지는 그대로 동작합니다.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        box = QGroupBox("외부 프로그램과 폴더")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.edits: dict[str, QLineEdit] = {}
        self.status: dict[str, QLabel] = {}
        for r, (key, label, filt, field_name) in enumerate(self.ROWS):
            name = QLabel(f"<b>{label}</b>")
            name.setToolTip(self.TIPS[key])
            edit = QLineEdit(getattr(s, field_name))
            edit.setClearButtonEnabled(True)
            edit.setToolTip(self.TIPS[key])
            edit.textChanged.connect(lambda _=None: self._schedule())
            browse = QPushButton("찾아보기...")
            browse.clicked.connect(lambda _=False, k=key, f=filt: self._browse(k, f))
            grid.addWidget(name, 2 * r, 0)
            grid.addWidget(edit, 2 * r, 1)
            grid.addWidget(browse, 2 * r, 2)
            url = settings.URLS.get(key)
            if url:
                get = QPushButton("받는 곳")
                get.setToolTip(url)
                get.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
                grid.addWidget(get, 2 * r, 3)
            st = QLabel()
            st.setWordWrap(True)
            st.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(st, 2 * r + 1, 1, 1, 3)
            self.edits[key], self.status[key] = edit, st
        lay.addWidget(box)

        libbox = QGroupBox("모션 폴더 (프로젝트 패널에 나오는 폴더)")
        lv = QHBoxLayout(libbox)
        self.libs = QListWidget()
        self.libs.setToolTip("회색은 기본 폴더(항상 나옴), 흰색은 추가한 폴더")
        lv.addWidget(self.libs, 1)
        col = QVBoxLayout()
        for text, fn in (("추가...", self._add_lib), ("제거", self._remove_lib)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        lv.addLayout(col)
        self.lib_status = QLabel()
        self._extra_libs = list(s.library_dirs)
        lay.addWidget(libbox, 1)
        lay.addWidget(self.lib_status)

        ai = QGroupBox("AI 연동")
        ag = QGridLayout(ai)
        ag.setColumnStretch(2, 1)
        self.api_on = QCheckBox("AI용 로컬 API 켜기")
        self.api_on.setChecked(s.api_enabled)
        self.api_on.setToolTip("Claude 같은 AI나 스크립트가 이 창을 조작합니다(모션 열기, 재생, 겹쳐 비교, 물리, 지표, 스크린샷). "
                               "127.0.0.1에서만, 실행할 때마다 바뀌는 토큰이 있어야 받습니다")
        ag.addWidget(self.api_on, 0, 0)
        ag.addWidget(QLabel("포트"), 0, 1, Qt.AlignRight)
        self.api_port = QSpinBox()
        self.api_port.setRange(1024, 65535)
        self.api_port.setValue(int(s.api_port))
        self.api_port.setToolTip("쓰고 있으면 빈 포트를 고릅니다. 실제 주소와 토큰은 api.json에 있습니다")
        ag.addWidget(self.api_port, 0, 2, Qt.AlignLeft)
        api = getattr(win, "api", None)
        from .api_server import discovery_path

        info = QLabel(f"{'실행 중: ' + api.url if api else '꺼짐'} · 주소·토큰 파일: {escape(discovery_path())}<br>"
                      "<span style='color:gray'>명령줄: retlens-cli (창 없이 리타게팅·QC·지표·비교·물리). "
                      "AI 사용 안내는 스킬(SKILL.md)에 있습니다.</span>")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ag.addWidget(info, 1, 0, 1, 3)
        guide = QPushButton("AI 가이드 열기")
        guide.clicked.connect(lambda: self.win.open_path(self.win.skill_path()))
        skill = QPushButton("Claude Code에 스킬 설치")
        skill.setToolTip("SKILL.md를 사용자 폴더의 .claude\\skills\\retlens에 복사합니다. 그러면 Claude Code가 RetLens를 다룰 때 이 안내를 씁니다")
        skill.clicked.connect(self.win.install_skill)
        ag.addWidget(guide, 0, 3)
        ag.addWidget(skill, 1, 3)
        lay.addWidget(ai)

        prog = QGroupBox("프로그램")
        pf = QGridLayout(prog)
        pf.setColumnStretch(1, 1)
        self.prog_status: dict[str, QLabel] = {}
        rows = [("robot", "로봇 모델"), ("gmr", "리타게팅 (GMR)")]
        for r, (key, label) in enumerate(rows):
            pf.addWidget(QLabel(f"<b>{label}</b>"), r, 0)
            st = QLabel()
            st.setWordWrap(True)
            pf.addWidget(st, r, 1, 1, 2)
            self.prog_status[key] = st
        pf.addWidget(QLabel("<b>사용자 데이터</b>"), len(rows), 0)
        data = QLabel(f"{escape(app_paths.user_dir())} <span style='color:gray'>(캐시·업로드·로그, 설정 파일)</span>")
        data.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pf.addWidget(data, len(rows), 1)
        open_data = QPushButton("열기")
        open_data.clicked.connect(lambda: self.win.open_path(app_paths.user_dir()))
        pf.addWidget(open_data, len(rows), 2)
        lay.addWidget(prog)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        again = buttons.addButton("다시 점검", QDialogButtonBox.ResetRole)
        again.clicked.connect(self.refresh)
        setup = buttons.addButton("설치 도우미...", QDialogButtonBox.ResetRole)
        setup.setToolTip("빠진 프로그램이 이 PC에 설치될 수 있는지 보고, 필요할 때만 설치합니다")
        setup.clicked.connect(self._open_setup)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def current(self) -> settings.Settings:
        """The settings as filled in (not saved yet)."""
        vals = {f: self.edits[k].text().strip().strip('"') for k, _, _, f in self.ROWS}
        return settings.Settings(**vals, library_dirs=list(self._extra_libs), api_enabled=self.api_on.isChecked(),
                                 api_port=int(self.api_port.value()))

    def _schedule(self) -> None:
        self._timer.start(250)  # check once typing pauses

    def refresh(self) -> None:
        s = self.current()
        checks = {c.key: c for c in settings.check_all(s)}
        auto = settings.Settings(library_dirs=s.library_dirs)  # what is found with the field left empty
        found_auto = {"isaac": settings.find_isaac(auto).path, "blender": settings.find_blender(auto).path,
                      "smpl": settings.find_smpl(auto).path, "gmt": settings.find_gmt(auto).path,
                      "video": settings.video_dir(auto)}
        for key, _, _, _ in self.ROWS:
            if key == "robot_usd":
                self.edits[key].setPlaceholderText("비우면 NVIDIA 에셋 서버의 Unitree G1 (인터넷 필요)")
            else:
                self.edits[key].setPlaceholderText(f"자동: {found_auto[key]}" if found_auto[key] else "자동: 찾지 못함")
            self.status[key].setText(check_html(checks[key]))
        for key, st in self.prog_status.items():
            st.setText(check_html(checks[key]))
        self.libs.clear()
        defaults = app_paths.library_roots()
        for d in settings.library_dirs(s):
            is_default = any(os.path.normcase(d) == os.path.normcase(os.path.abspath(x)) for x in defaults)
            row = QListWidgetItem(d + ("  (기본)" if is_default else "") + ("" if os.path.isdir(d) else "  - 없음"))
            row.setData(Qt.UserRole, d)
            if is_default:
                row.setForeground(QBrush(QColor(140, 140, 150)))
                row.setFlags(row.flags() & ~Qt.ItemIsSelectable)
            self.libs.addItem(row)
        self.lib_status.setText(check_html(checks["library"]))

    def _browse(self, key: str, filt: str | None) -> None:
        hint = self.edits[key].placeholderText()
        cur = self.edits[key].text().strip() or (hint[len("자동: "):] if hint.startswith("자동: ") else "")
        start = cur if os.path.isdir(cur) else os.path.dirname(cur) if cur else app_paths.documents_dir()
        if filt is None:
            path = QFileDialog.getExistingDirectory(self, "폴더 고르기", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "파일 고르기", start, filt)
        if path:
            self.edits[key].setText(os.path.normpath(path))

    def _add_lib(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "모션 폴더 추가", app_paths.documents_dir())
        if path and os.path.normcase(os.path.normpath(path)) not in {os.path.normcase(d) for d in self._extra_libs}:
            self._extra_libs.append(os.path.normpath(path))
            self.refresh()

    def _remove_lib(self) -> None:
        for row in self.libs.selectedItems():
            d = row.data(Qt.UserRole)
            self._extra_libs = [x for x in self._extra_libs if os.path.normcase(x) != os.path.normcase(d)]
        self.refresh()

    def accept(self) -> None:
        self._merge_saved(typed_wins=True)  # an install that finished in the background keeps the path it saved
        settings.save(self.current())
        self.win.apply_settings()
        super().accept()

    def _merge_saved(self, typed_wins: bool) -> None:
        """The paths the setup assistant saves (prereqs.SETTING) that changed on disk since this window
        read them replace what the fields show - except, with typed_wins, a field the user has typed in."""
        from ..prereqs import SETTING

        disk = settings.load(reload=True)
        for key, _, _, f in self.ROWS:
            if f in SETTING.values() and getattr(disk, f) != getattr(self._loaded, f):
                if not typed_wins or self.edits[key].text().strip().strip('"') == getattr(self._loaded, f):
                    self.edits[key].setText(getattr(disk, f))
                setattr(self._loaded, f, getattr(disk, f))

    def _open_setup(self) -> None:
        """The assistant works on the saved settings and saves what it installs. Nothing typed here is
        saved by opening it; afterwards the paths it set show here (the other fields stay as typed)."""
        self.win.open_setup()
        self._merge_saved(typed_wins=False)
        self.refresh()


class _SetupSignals(QObject):
    probed = Signal(object)  # list[prereqs.Status]
    progress = Signal(str, str, float, float)  # key, stage, done, total
    finished = Signal(str, object)  # key, Status or the exception


class SetupAssistant(QDialog):
    """설치 도우미 (khumanoid/prereqs.py): per optional component, what this PC has, whether it is
    needed and whether this PC can take it; the install button is on only when an install is needed
    and possible. Checks and installs run in the background; one install at a time."""
    STATE = {"ready": ("✓", OK_COLOR, "있음"), "incompatible": ("⚠", WARN_COLOR, "맞지 않는 버전"),
             "missing": ("✗", WARN_COLOR, "없음")}
    BUTTON = {"install": "설치", "configure": "이것으로 설정", "manual": "zip 가져오기..."}

    def __init__(self, win: "EditorWindow"):
        super().__init__(win)
        from .. import prereqs

        self.win, self.prereqs = win, prereqs
        self.setWindowTitle(f"{APP_NAME} 설치 도우미")
        self.resize(900, 720)
        self.sig = _SetupSignals()
        self.sig.probed.connect(self._show)
        self.sig.progress.connect(self._progress)
        self.sig.finished.connect(self._finished)
        self.status: dict = {}
        self.running: str | None = None
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        lay = QVBoxLayout(self)
        intro = QLabel("RetLens가 쓸 수 있는 외부 프로그램과 파일입니다. 먼저 이 PC에 호환되는 것이 있는지 찾고, 없을 때만 "
                       "이 PC에 설치할 수 있는지(GPU·드라이버·디스크·인터넷·쓰기 권한) 확인합니다. 설치는 필요하고 가능할 때만 "
                       "켜지며, 파일은 각 배포처에서 직접 받고 체크섬을 확인합니다. 동의가 필요한 라이선스는 설치 전에 묻습니다.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        body = QWidget()
        rows = QVBoxLayout(body)
        self.ui: dict[str, dict] = {}
        for key in prereqs.KEYS:  # per component: the whole report, then a line of progress and buttons
            box = QGroupBox(f"{prereqs.NAMES[key]} · {prereqs.NEEDED_FOR[key]}")
            v = QVBoxLayout(box)
            text = QLabel("점검 중...")
            text.setWordWrap(True)
            text.setTextFormat(Qt.RichText)
            text.setOpenExternalLinks(True)
            text.setTextInteractionFlags(Qt.TextBrowserInteraction)
            text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            v.addWidget(text)
            line = QHBoxLayout()
            bar = QProgressBar()
            bar.setVisible(False)
            stop = QPushButton("취소")
            stop.setVisible(False)
            stop.clicked.connect(self.cancel.set)
            site = QPushButton("배포처 열기")
            site.setToolTip(prereqs.LICENSES[key].url)
            site.clicked.connect(lambda _=False, k=key: QDesktopServices.openUrl(QUrl(self.prereqs.LICENSES[k].url)))
            act = QPushButton("설치")
            act.setEnabled(False)
            act.clicked.connect(lambda _=False, k=key: self._act(k))
            line.addWidget(bar, 1)
            line.addWidget(stop)
            line.addStretch(0)
            line.addWidget(site)
            line.addWidget(act)
            v.addLayout(line)
            rows.addWidget(box)
            self.ui[key] = {"text": text, "act": act, "bar": bar, "stop": stop}
        rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("닫기")
        self.again = buttons.addButton("다시 점검", QDialogButtonBox.ResetRole)
        self.again.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.refresh()

    # -- checks
    def refresh(self) -> None:
        if self.running:
            return
        for u in self.ui.values():
            u["act"].setEnabled(False)
        self.again.setEnabled(False)

        def work():
            try:
                self.sig.probed.emit(self.prereqs.probe_all(online=True))
            except Exception as e:  # never leave the dialog at "점검 중"
                self.sig.probed.emit(e)

        threading.Thread(target=work, name="setup-probe", daemon=True).start()

    def _html(self, st) -> str:
        mark, color, word = self.STATE[st.state]
        out = f"<span style='color:{color}'><b>{mark} {word}</b></span>"
        if st.found:
            out += f" {escape(st.found)}"
        if st.detail:
            out += f"<br><span style='color:gray'>{escape(st.detail)}</span>"
        if st.action != "none":
            out += f"<br><b>{escape(st.note)}</b>"
            if st.download:
                out += f"<br><span style='color:gray'>받는 곳: {escape(st.download)}</span>"
            if st.requirements:
                marks = []
                for r in st.requirements:
                    c, m = (OK_COLOR, "✓") if r.ok else ((BAD_COLOR, "✗") if r.blocking else (WARN_COLOR, "⚠"))
                    marks.append(f"<span style='color:{c}'>{m}</span> {escape(r.name)}: {escape(r.detail)}")
                out += "<br>" + "<br>".join(marks)
            lic = st.license
            if lic is not None:
                out += (f"<br><span style='color:gray'>라이선스: <a href='{escape(lic.url)}'>{escape(lic.name)}</a>"
                        + (" (설치 전에 동의를 묻습니다)" if lic.consent and st.action == "install" else "") + "</span>")
        else:
            out += f"<br><span style='color:gray'>{escape(st.note)}</span>"
        return out

    def _show(self, result) -> None:
        self.again.setEnabled(True)
        if isinstance(result, Exception):
            for u in self.ui.values():
                u["text"].setText(f"<span style='color:{BAD_COLOR}'>점검 실패: {escape(str(result))}</span>")
            return
        for st in result:
            self._show_one(st)

    def _show_one(self, st) -> None:
        self.status[st.key] = st
        u = self.ui[st.key]
        u["text"].setText(self._html(st))
        label = self.BUTTON.get(st.action)
        u["act"].setText(label or ("설치 필요 없음" if st.action == "none" else "설치할 수 없음"))
        u["act"].setEnabled(bool(label) and not self.running)
        u["act"].setToolTip(st.note)

    # -- installs
    def _consent(self, st) -> bool:
        lic = st.license
        box = QMessageBox(self)
        box.setWindowTitle(f"{st.name} 설치")
        box.setIcon(QMessageBox.Question)
        box.setTextFormat(Qt.RichText)
        text = (f"<b>{escape(st.name)}</b>을(를) 설치합니다.<br>{escape(st.download)}<br><br>"
                f"라이선스: <a href='{escape(lic.url)}'>{escape(lic.name)}</a><br>{escape(lic.summary)}")
        if st.key == "isaac":
            text += (f"<br><br><a href='{escape(self.prereqs.ISAAC_EULA_URL)}'>NVIDIA Omniverse License Agreement</a> 전문을 "
                     "읽고 동의하는 경우에만 진행하세요.")
        box.setText(text + "<br><br>" + ("동의하고 설치하시겠습니까?" if lic.consent else "설치하시겠습니까?"))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("동의하고 설치" if lic.consent else "설치")
        box.button(QMessageBox.No).setText("취소")
        return box.exec() == QMessageBox.Yes

    def _act(self, key: str) -> None:
        st = self.status.get(key)
        if st is None or self.running:
            return
        source = None
        if st.action == "manual":  # SMPL-X: the zip the user downloaded from the site
            path, _ = QFileDialog.getOpenFileName(self, "SMPL-X zip 고르기 (smpl-x.is.tue.mpg.de에서 받은 파일)",
                                                  os.path.join(os.path.expanduser("~"), "Downloads"), "zip (*.zip)")
            if not path:
                return
            source = path
        elif st.action == "install" and not self._consent(st):
            return
        if key == "isaac" and st.action == "install":  # the same consent the physics mode asks for
            self.win.accept_isaac_eula()
        self.running = key
        self.cancel.clear()
        for k, u in self.ui.items():
            u["act"].setEnabled(False)
        u = self.ui[key]
        u["bar"].setVisible(True)
        u["bar"].setRange(0, 0)
        u["stop"].setVisible(st.action == "install")
        self.again.setEnabled(False)

        def work():
            try:  # accept only after the consent box above; expect: refuse if the PC changed since the check
                out = self.prereqs.install(key, accept=st.action == "install", expect=st.action, source=source,
                                           cancel=self.cancel,
                                           progress=lambda stage, d, t: self.sig.progress.emit(key, stage, d, t))
            except Exception as e:  # SetupError, Cancelled, network: shown, never fatal
                out = e
            self.sig.finished.emit(key, out)

        self.worker = threading.Thread(target=work, name=f"setup-{key}", daemon=True)
        self.worker.start()

    def _progress(self, key: str, stage: str, done: float, total: float) -> None:
        bar = self.ui[key]["bar"]
        if total > 0:
            bar.setRange(0, 1000)
            bar.setValue(int(1000 * min(done / total, 1.0)))
            unit = 1e9 if total > 2e9 else 1e6
            bar.setFormat(f"{stage} {done / unit:.1f} / {total / unit:.1f} {'GB' if unit == 1e9 else 'MB'}")
        else:
            bar.setRange(0, 0)
            bar.setFormat(stage)

    def _finished(self, key: str, result) -> None:
        self.running = None
        u = self.ui[key]
        u["bar"].setVisible(False)
        u["stop"].setVisible(False)
        if isinstance(result, self.prereqs.Cancelled):
            self.win.status(f"{self.prereqs.NAMES[key]} 설치를 취소했습니다(받던 파일은 다음에 이어 받습니다)", 8000)
        elif isinstance(result, Exception):
            QMessageBox.warning(self, "설치하지 못했습니다", f"{self.prereqs.NAMES[key]}: {type(result).__name__}: {result}")
        else:
            self.win.apply_settings(quiet=True)  # the new paths take effect at once (menus, checks)
            self.win.status(f"{self.prereqs.NAMES[key]}: {result.note}", 10000)
        self.refresh()

    def reject(self) -> None:
        """Closing hides the window; a running install goes on (or stops, if the user says so) and the
        same window, reopened from the menu, still shows it - so it can never be started twice."""
        if self.running and not self.cancel.is_set():
            box = QMessageBox(self)
            box.setWindowTitle("설치 중")
            box.setText(f"{self.prereqs.NAMES[self.running]}을(를) 설치하고 있습니다.")
            keep = box.addButton("계속 설치 (창만 닫기)", QMessageBox.AcceptRole)
            stop = box.addButton("설치 멈추기", QMessageBox.DestructiveRole)
            box.addButton("취소", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is stop:
                self.cancel.set()
            elif box.clickedButton() is not keep:
                return
        super().reject()


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
        self.compare_panel = ComparePanel(self)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        self.console.setFont(QFont("Consolas", 9))
        self.docks: dict[str, QDockWidget] = {}
        self._build_docks()
        self._build_actions()
        self._build_status()
        self._default_state = self.saveState()
        split_layout_settings(self.settings)
        geo, state = self.settings.value(layout_key("window/geometry")), self.settings.value(layout_key("window/state"))
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1600, 960)
        if state is not None:
            self.restoreState(state)
            if not self.settings.value(layout_key("layout/has_compare"), False, type=bool):  # saved before the 비교 tab
                self.tabifyDockWidget(self.docks["analysis"], self.docks["compare"])
        self.settings.setValue(layout_key("layout/has_compare"), True)

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
        QTimer.singleShot(0, self._startup_check)  # once the window is up (환경 점검)
        self._invoker = _GuiInvoker()  # API request threads -> this thread
        self._start_api()

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
        cmp = self._dock("compare", "비교", self.compare_panel, B)
        con = self._dock("console", "콘솔", self.console, B)
        self.splitDockWidget(tl, proj, Qt.Vertical)
        self.tabifyDockWidget(proj, ana)
        self.tabifyDockWidget(ana, cmp)
        self.tabifyDockWidget(cmp, con)
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
        self.a_physics = act("물리 모드", self.set_physics, "P", QStyle.SP_ComputerIcon, checkable=True,
                             tip="켜면 각 로봇을 시뮬레이션한 결과로 바꿔 그립니다. 균형 제어에 따라 Isaac Sim PhysX"
                                 "(골반 보조 힘, 짧은 클립 약 1분) 또는 MuJoCo(제어기 없음 / GMT 추적 정책, 클립당 몇 초)로 "
                                 "백그라운드에서 계산합니다")
        self.a_cancel = act("작업 취소", sc.cancel_jobs, icon=QStyle.SP_BrowserStop,
                            tip="대기 중이거나 돌고 있는 물리 계산(Isaac·MuJoCo)과 동영상 녹화를 멈춥니다")
        self.a_compare = act("겹쳐 비교", lambda on: self.start_compare(on=on), "O", QStyle.SP_FileDialogContentsView,
                             checkable=True, tip="대상(B)을 기준(A)의 골반 위치에 겹쳐 그리고, A에서 벗어난 B의 부위만 색칠합니다 "
                                                 "(A·B는 '비교' 탭이나 계층 패널 우클릭에서 고름)")
        self.a_fit = act("카메라 맞추기", sc.fit_camera, "F", QStyle.SP_DesktopIcon)
        self.a_reset = act("레이아웃 초기화", self.reset_layout)
        self.a_browser = act("브라우저에서 씬 열기", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.a_readme = act("사용 안내", lambda: self.open_path(app_paths.doc("docs", "retlens.md")))
        self.a_labels = act("CMU 동작 라벨 목록", lambda: self.open_path(app_paths.doc("docs", "cmu_motion_labels.md")))
        self.a_folders = act("데이터 폴더 열기", lambda: self.open_path(app_paths.user_dir()),
                             tip="캐시·업로드·로그가 있는 폴더 (설치판: %LOCALAPPDATA%\\RetLens)")
        self.a_setup = act("설치 도우미...", lambda: self.open_setup(), icon=QStyle.SP_DriveNetIcon,
                           tip="Blender·GMT·Isaac Sim·SMPL-X가 이 PC에 있는지 보고, 없고 설치할 수 있을 때만 설치합니다")
        self.a_settings = act("환경 설정...", lambda: self.open_settings(), "Ctrl+,", QStyle.SP_FileDialogDetailedView,
                              tip="Isaac Sim·Blender·SMPL-X 모델·모션 폴더·동영상 폴더 위치와 점검")
        self.a_about = act("정보", self._about)
        self.a_foot_flat = act("디딤발 평평 보정", lambda on: self.set_retarget(foot_flat=on), checkable=True,
                               tip=f"{RETARGET_TIPS['foot_flat']}. {RETARGET_NOTE}")
        self._swing_cm = sc.opts.swing_clearance_cm or SWING_CLEARANCE_CM  # the command line's height, if given
        self.a_swing = act(f"스윙 발 보정 ({self._swing_cm:g} cm)",
                           lambda on: self.set_retarget(swing_clearance_cm=self._swing_cm if on else 0.0),
                           checkable=True, tip=f"{RETARGET_TIPS['swing']}. {RETARGET_NOTE}")
        self._sync_retarget()

        mb = self.menuBar()
        m = mb.addMenu("파일(&F)")
        for a in (self.a_open, None, self.a_video, self.a_video_dir, self.a_folders, None, self.a_settings, self.a_setup, None,
                  self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("편집(&E)")
        m.addAction(self.a_remove)
        m.addAction(self.a_remove_all)
        m = mb.addMenu("보기(&V)")
        for d in self.docks.values():
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        for a in (self.a_compare, self.a_fit, self.a_reset, self.a_browser):
            m.addAction(a)
        m = mb.addMenu("재생(&P)")
        for a in (self.a_play, self.a_home, self.a_prev, self.a_next):
            m.addAction(a)
        # 리타게팅 보정 of the human motions opened next (open ones keep theirs: reopen to compare)
        m = mb.addMenu("리타게팅(&R)")
        m.setToolTipsVisible(True)
        m.addAction(self.a_foot_flat)
        m.addAction(self.a_swing)
        m = mb.addMenu("물리(&S)")
        m.addAction(self.a_physics)
        # 균형 제어: what keeps the simulated robot up. A mode whose files are not here yet (GMT before the
        # setup assistant fetched it) says so in its label and tip; picking it explains and offers the assistant
        sub = m.addMenu("균형 제어")
        sub.setToolTipsVisible(True)
        grp = QActionGroup(self)
        self.a_balance = {}
        self.balance_box = QComboBox()
        self.balance_box.setToolTip("물리 모드의 균형 제어 (물리 메뉴에도 있음). 고르면 물리 모드를 켭니다")
        for key, label in BALANCE.items():
            a = QAction(label, self, checkable=True)
            a.setChecked(key == sc.balance)
            a.triggered.connect(lambda _=False, k=key: self.set_balance(k))
            grp.addAction(a)
            sub.addAction(a)
            self.a_balance[key] = a
            self.balance_box.addItem(label, key)
        self._refresh_balance_entries()
        self.balance_box.setCurrentIndex(self.balance_box.findData(sc.balance))
        self.balance_box.activated.connect(lambda i: self.set_balance(self.balance_box.itemData(i)))
        self.m_assist = m.addMenu("골반 보조 힘 (Isaac)")
        grp = QActionGroup(self)
        self.a_assist = {}
        for val, label in ASSIST_LABELS.items():
            a = QAction(label, self, checkable=True)
            a.setChecked(val == sc.assist)
            a.triggered.connect(lambda _=False, v=val: sc.set_assist(v))
            grp.addAction(a)
            self.m_assist.addAction(a)
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
                  self.balance_box, self.a_cancel, None, self.a_compare, self.a_fit, self.a_video):
            tb.addSeparator() if a is None else tb.addWidget(a) if isinstance(a, QWidget) else tb.addAction(a)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.st_env = QToolButton()  # 환경 점검 at a glance; opens 환경 설정
        self.st_env.setAutoRaise(True)
        self.st_env.clicked.connect(lambda: self.open_settings())
        sb.addPermanentWidget(self.st_env)
        self.st_api = QLabel("API")  # the AI API's port (khumanoid/app/api_server.py)
        self.st_api.setContentsMargins(8, 0, 8, 0)
        sb.addPermanentWidget(self.st_api)
        self.st_physics = QLabel()
        self.st_jobs = QLabel()
        self.st_time = QLabel()
        for w in (self.st_jobs, self.st_physics, self.st_time):
            w.setContentsMargins(8, 0, 8, 0)
            sb.addPermanentWidget(w)

    # ---------------------------------------------------------------- 환경 설정
    auto_setup = True  # open 환경 설정 on the first start when something is missing (off for smoke tests)

    def _refresh_env(self, checks: list | None = None) -> list:
        checks = checks if checks is not None else settings.check_all()
        missing = [c for c in checks if not c.ok]
        if not missing:
            self.st_env.setText("환경 ✓")
            self.st_env.setToolTip("모든 기능을 쓸 수 있습니다 (눌러서 환경 설정)")
        else:
            self.st_env.setText(f"환경 ⚠ {len(missing)}")
            self.st_env.setToolTip("쓸 수 없는 기능이 있습니다 (눌러서 환경 설정):\n" + "\n".join(
                f"- {c.name}: {c.needed_for}" for c in missing))
        return checks

    def _startup_check(self) -> None:
        checks = self._refresh_env()
        for c in checks:
            if not c.ok:
                self.scene.log(f"환경 점검: {c.name} 없음 - {c.detail} ({c.needed_for} 사용 불가)")
        first = not self.settings.value(layout_key("setup/checked"), False, type=bool)
        self.settings.setValue(layout_key("setup/checked"), True)
        if first and self.auto_setup and any(not c.ok for c in checks):
            self.open_settings()

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

    _setup: "SetupAssistant | None" = None

    def open_setup(self) -> None:
        """One 설치 도우미 per window, reused: an install keeps running while it is closed and shows
        again when it is reopened."""
        if self._setup is None:
            self._setup = SetupAssistant(self)
        else:
            self._setup.refresh()
        self._setup.exec()

    def apply_settings(self, quiet: bool = False) -> None:
        """Saved 환경 설정 take effect now (scene folders, project panel, the status bar, 균형 제어)."""
        s = settings.load(reload=True)
        self.scene.apply_settings(s)
        self.project.reload()
        self._refresh_env()
        self._refresh_balance_entries()
        if bool(self.api) != s.api_enabled or (self.api is not None and self.api.port != s.api_port
                                               and self._api_port_asked != s.api_port):
            self._stop_api()
            self._start_api()
        if not quiet:
            self.status("환경 설정을 저장했습니다", 4000)

    # ---------------------------------------------------------------- AI API
    api = None
    _api_port_asked = None

    def _start_api(self) -> None:
        """The local HTTP API for AI agents (khumanoid/app/api_server.py), when 환경 설정 has it on."""
        from .api_server import ApiBackend, ApiServer, discovery_path

        s = settings.load()
        self._api_port_asked = s.api_port
        if not s.api_enabled:
            self._refresh_api_status()
            return
        try:
            self.api = ApiServer(ApiBackend(self.scene, self, on_gui=self._gui_call), s.api_port).start()
            self.scene.log(f"AI용 로컬 API: {self.api.url} (토큰: {discovery_path()})")
        except Exception as e:
            self.api = None
            self.scene.log(f"AI용 로컬 API를 열지 못함: {type(e).__name__}: {e}")
        self._refresh_api_status()

    def _stop_api(self) -> None:
        if self.api is not None:
            self.api.stop()
            self.api = None

    def _refresh_api_status(self) -> None:
        if self.api is not None:
            self.st_api.setText(f"API :{self.api.port}")
            self.st_api.setToolTip(f"AI용 로컬 API가 {self.api.url}에서 동작 중입니다 (토큰 필요, 환경 설정에서 끔)")
        else:
            self.st_api.setText("API 꺼짐")
            self.st_api.setToolTip("AI용 로컬 API가 꺼져 있습니다 (환경 설정 > AI 연동)")

    def _gui_call(self, fn):
        """Run fn on the GUI thread and return its result (from the API's request threads)."""
        if QThread.currentThread() is self.thread():
            return fn()
        box = {"fn": fn}
        self._invoker.call.emit(box)  # blocking queued: returns once the GUI thread ran it
        if "error" in box:
            raise box["error"]
        return box.get("result")

    @staticmethod
    def skill_path() -> str:
        """The AI guide: the installed program's ai\\retlens\\SKILL.md, or the repository's
        .claude\\skills\\retlens\\SKILL.md ("" when neither is there)."""
        for p in (app_paths.resource("ai", "retlens", "SKILL.md"),
                  os.path.join(app_paths.REPO_ROOT, ".claude", "skills", "retlens", "SKILL.md")):
            if os.path.isfile(p):
                return p
        return ""

    def install_skill(self) -> None:
        """Copy SKILL.md into the user's Claude Code skills folder (~/.claude/skills/retlens)."""
        import shutil

        src = self.skill_path()
        if not src:
            QMessageBox.warning(self, "AI 가이드", "SKILL.md를 찾지 못했습니다.")
            return
        dst = os.path.join(os.path.expanduser("~"), ".claude", "skills", "retlens", "SKILL.md")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        QMessageBox.information(self, "AI 가이드", f"스킬을 설치했습니다:\n{dst}\n\nClaude Code에서 RetLens 작업을 하면 이 안내를 씁니다.")

    def need(self, key: str, what: str) -> bool:
        """True when what `key` stands for is there; otherwise say what is missing and offer 환경 설정."""
        c = next((c for c in settings.check_all() if c.key == key), None)
        if c is None or c.ok:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"{c.name} 필요")
        box.setTextFormat(Qt.RichText)
        box.setText(f"{escape(what)}에는 <b>{escape(c.name)}</b>이(가) 필요합니다.<br><br>{escape(c.detail)}<br>"
                    f"{escape(c.hint)}")
        from ..prereqs import KEYS

        setup = box.addButton("설치 도우미 열기", QMessageBox.AcceptRole) if key in KEYS else None
        go = box.addButton("환경 설정 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            self.open_settings()
        elif setup is not None and box.clickedButton() is setup:
            self.open_setup()
        return False

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

    def start_compare(self, on: bool = True, ref: Item | None = None, item: Item | None = None) -> None:
        """Turn the overlay comparison on (A and B from the 비교 tab unless given; B defaults to
        the selected motion) or off."""
        sc = self.scene
        if on:
            items = sc.items
            p = self.compare_panel
            a = ref or (sc.compare.ref if sc.compare.ref in items else p._combo_item(p.ref))
            b = item or (self.selected if self.selected in items and self.selected is not a and ref is None
                         else sc.compare.item if sc.compare.item in items else p._combo_item(p.item))
            if a is None or a is b:
                a = next((it for it in items if it is not b), None)
            if b is None or b is a:
                b = next((it for it in items if it is not a), None)
            sc.set_compare(on=True, ref=a, item=b)
            self.docks["compare"].raise_()
        else:
            sc.set_compare(on=False)

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
                    import traceback

                    traceback.print_exc()  # the whole story goes to the console / log file
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
            self.scene.log(f"failed to open: {result}")  # into the console panel and the log file
            text = str(result)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("모션을 열지 못했습니다")
            box.setText(text)
            go = None
            if any(k in text for k in ("Blender", "SMPL", "smplx", "GMR", "general_motion_retargeting", "환경 설정")):
                go = box.addButton("환경 설정 열기", QMessageBox.AcceptRole)  # a missing tool / model: say where to set it
            box.addButton("닫기", QMessageBox.RejectRole)
            box.exec()
            if go is not None and box.clickedButton() is go:
                self.open_settings()

    def open_dialog(self) -> None:
        pats = " ".join(f"*{e}" for e in MOTION_EXT)
        start = self.settings.value(layout_key("dialog/dir"), "") or next(
            (d for d in app_paths.library_roots() if os.path.isdir(d)), app_paths.documents_dir())
        paths, _ = QFileDialog.getOpenFileNames(self, "모션 파일 열기", start,
                                                f"모션 파일 ({pats});;모든 파일 (*)")
        if paths:
            self.settings.setValue(layout_key("dialog/dir"), os.path.dirname(paths[0]))
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
    def accept_isaac_eula(self) -> None:
        """The user accepted NVIDIA's license (here or in the setup assistant's Isaac install)."""
        self._eula = True
        self.settings.setValue("isaac/eula_accepted", True)
        self.scene.runner.accept_eula = True

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
        self.accept_isaac_eula()
        return True

    def set_physics(self, on: bool) -> None:
        if on and not self._balance_ready(self.scene.balance):
            self.a_physics.blockSignals(True)
            self.a_physics.setChecked(False)
            self.a_physics.blockSignals(False)
            return
        self.scene.set_physics(on, "editor")

    def set_balance(self, mode: str) -> None:
        """균형 제어 from the menu or the toolbar; turns physics mode on when it is off."""
        sc = self.scene
        if (mode != sc.balance or not sc.physics_on) and self._balance_ready(mode):
            sc.set_balance(mode)
            if not sc.physics_on:
                sc.set_physics(True, "균형 제어")
        self._refresh_status()  # the menu and the box show the scene's mode (also when refused)

    def set_retarget(self, **kw) -> None:
        """리타게팅 menu: the scene's settings for the human motions opened next."""
        r = self.scene.set_retarget(**kw)
        on = [name for name, yes in (("디딤발 평평", r["foot_flat"]),
                                     (f"스윙 발 {r['swing_clearance_cm']:g} cm", r["swing_clearance_cm"] > 0)) if yes]
        self.status(f"리타게팅 보정: {', '.join(on) or '끔'}. {RETARGET_NOTE}", 10000)

    def _sync_retarget(self) -> None:
        """The 리타게팅 menu shows the scene's settings (the API can change them too)."""
        o = self.scene.opts
        if o.swing_clearance_cm > 0 and o.swing_clearance_cm != self._swing_cm:
            self._swing_cm = o.swing_clearance_cm
            self.a_swing.setText(f"스윙 발 보정 ({self._swing_cm:g} cm)")
        for a, on in ((self.a_foot_flat, o.foot_flat), (self.a_swing, o.swing_clearance_cm > 0)):
            if a.isChecked() != on:
                a.blockSignals(True)
                a.setChecked(on)
                a.blockSignals(False)

    def _refresh_balance_entries(self) -> None:
        """Labels and tips of the 균형 제어 menu and box: '(설치 필요)' on a mode that cannot run yet."""
        for i, (key, label) in enumerate(BALANCE.items()):
            why = self.scene.balance_problem(key)
            tip = f"아직 쓸 수 없음: {why}" if why else BALANCE_TIPS[key]
            text = label + (" (설치 필요)" if why else "")
            a = self.a_balance[key]
            a.setText(text)
            a.setToolTip(tip)
            a.setStatusTip(tip)
            self.balance_box.setItemText(i, text)
            self.balance_box.setItemData(i, tip, Qt.ToolTipRole)

    def _balance_ready(self, mode: str) -> bool:
        """What the mode needs is there (Isaac: installed and its EULA accepted; MuJoCo: GMT's files);
        otherwise say what is missing and offer the setup assistant."""
        if mode == "isaac":
            return self.need("isaac", "물리 모드 (보조 힘, Isaac)") and self._ensure_eula()
        why = self.scene.balance_problem(mode)
        if not why:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("균형 제어")
        box.setText(f"'{BALANCE[mode]}'을(를) 아직 쓸 수 없습니다.\n\n{why}")
        go = box.addButton("설치 도우미 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            self.open_setup()
        return False

    def save_video(self, item: Item | None) -> None:
        if item is None or not self.need("isaac", "동영상 저장") or not self._ensure_eula():
            return
        try:
            job = self.scene.save_video(item)
        except Exception as e:  # Isaac Sim not found, the MuJoCo result not there yet
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
        if event in ("items", "item", "status", "compare"):
            self.compare_panel.refresh()
            on = self.scene.compare_pair() is not None
            if self.a_compare.isChecked() != on:
                self.a_compare.blockSignals(True)
                self.a_compare.setChecked(on)
                self.a_compare.blockSignals(False)
        self.timeline.refresh()

    def refresh_analysis(self) -> None:
        self.analysis.update_table()
        self.analysis.rebuild_chart()
        self.inspector.refresh()

    def _refresh_status(self) -> None:
        sc = self.scene
        self.st_physics.setText(sc.physics_status())
        self.st_physics.setToolTip("\n".join(f"{it.label}: {sc.job_text(it)}" for it in list(sc.items)
                                             if not sc.is_sim_result(it)) if sc.physics_on else "")
        jobs = sc.jobs_summary()
        self.st_jobs.setText(f"작업: {jobs}" if jobs else "작업 없음")
        if self.a_physics.isChecked() != sc.physics_on:
            self.a_physics.blockSignals(True)
            self.a_physics.setChecked(sc.physics_on)
            self.a_physics.blockSignals(False)
        for val, a in self.a_assist.items():
            a.setChecked(val == sc.assist)
        self.m_assist.setEnabled(sc.balance == "isaac")
        for key, a in self.a_balance.items():
            a.setChecked(key == sc.balance)
        i = self.balance_box.findData(sc.balance)
        if self.balance_box.currentIndex() != i:
            self.balance_box.blockSignals(True)
            self.balance_box.setCurrentIndex(i)
            self.balance_box.blockSignals(False)
        self._sync_retarget()

    def _refresh_all(self) -> None:
        self.hierarchy.rebuild()
        self.analysis.refresh_lists()
        self.refresh_analysis()
        self._refresh_status()
        self.compare_panel.refresh()
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
        self.compare_panel.update_live()
        if sc.jobs_busy() and int(now * 2) != int(prev * 2):  # job progress, twice a second
            self.hierarchy.refresh()
            self.inspector.refresh(metrics=False)
            self._refresh_status()

    _play_icon = None

    def _about(self) -> None:
        from . import runtime

        rows = [*app_paths.describe(), ("로그 파일", runtime.log_path() or "콘솔 (저장소에서 실행)")]
        where = "".join(f"<tr><td style='padding-right:10px'>{escape(k)}</td><td>{escape(v)}</td></tr>"
                        for k, v in rows)
        from .. import __version__

        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME} {__version__}</b><br>{APP_TAGLINE}<br>K-Humanoid 프로젝트<br><br>"
                                          f"씬: viser ({self.url})<br>물리·녹화: NVIDIA Isaac Sim (PhysX)<br>"
                                          f"균형 제어 (MuJoCo): GMT 추적 정책 (Apache-2.0, 공개 모델은 연구용)<br><br>"
                                          f"<b>파일 위치</b><table>{where}</table>")

    def closeEvent(self, e):
        setup = self._setup
        if setup is not None and setup.running:  # an install in the (maybe hidden) 설치 도우미
            name = setup.prereqs.NAMES[setup.running]
            if QMessageBox.question(self, "설치 중", f"{name}을(를) 설치하고 있습니다. 종료하면 설치가 멈춥니다"
                                    "(받던 파일은 다음에 이어 받습니다). 종료할까요?") != QMessageBox.Yes:
                e.ignore()
                return
            setup.cancel.set()
            setup.worker.join(timeout=15)  # downloads and unpacks stop at the next chunk / file and clean up
        self.settings.setValue(layout_key("window/geometry"), self.saveGeometry())
        self.settings.setValue(layout_key("window/state"), self.saveState())
        self.timer.stop()
        self._stop_api()
        self._ticking = False
        self._ticker.join(timeout=1.0)
        self.scene.shutdown()
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

    from . import runtime

    no_sandbox = webengine_sandbox_workaround()  # before QApplication / the first web view
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if os.name == "nt":  # its own taskbar entry and icon (not python.exe's) when run from the repository
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KHumanoid.RetLens")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    from .. import __version__

    app.setApplicationVersion(__version__)
    icon =os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")  # tools/make_icon.py
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    app.setStyle("Fusion")
    if not args.light:
        app.setPalette(dark_palette())
    runtime.install_error_hooks()  # uncaught errors: log + dialog

    def log(msg: str) -> None:
        print(f"[editor] {msg}", flush=True)

    if runtime.log_path():
        log(f"log file: {runtime.log_path()}")
    if no_sandbox:
        log("scene view: Chromium sandbox off (conda Qt layout); it only shows the local scene server")
    port = args.port or free_port()
    try:
        urdf = load_robot_urdf(args.urdf, args.mesh_cell, log=log)
    except Exception as e:  # without the robot model nothing can be shown: say why instead of vanishing
        robot = next(c for c in settings.check_all() if c.key == "robot")
        QMessageBox.critical(None, APP_NAME, f"로봇 모델을 불러오지 못해 시작할 수 없습니다.\n\n{args.urdf}\n"
                                             f"{type(e).__name__}: {e}\n\n{robot.hint}")
        return 1
    server = viser.ViserServer(host="127.0.0.1", port=port, label=APP_NAME, verbose=False)
    scene = MotionScene(server, urdf, scene_options(args), log=log)
    if args.body_mesh:
        scene.view.body_mesh = True
    server.initial_camera.position = (3.0, -3.0, 1.8)
    server.initial_camera.look_at = (0.0, 0.0, 0.75)
    url = f"http://127.0.0.1:{port}/?hideViserLogo"
    win = EditorWindow(scene, url, args.library, accept_eula=args.isaac_accept_eula)
    win.auto_setup = args.quit_after <= 0  # smoke tests must not stop at the first-start 환경 설정
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
    scene.shutdown()
    server.stop()
    return code
