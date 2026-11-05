"""RetLens (Retarget Lens), the desktop editor (Qt): the motion scene with
editor-style dockable panels.

    python tools/editor.py [motion files ...] [--isaac-accept-eula]

Layout (like Blender / Unity; every panel can be moved, tabbed, floated or closed and
the layout is remembered; 보기 > 레이아웃 초기화 restores this one):

    +-- menu bar / toolbar (열기 · 물리 모드 ▾ · 겹쳐 비교 · 카메라) --+
    |                                     | 계층 (motions, score)|
    |         scene view (3D, viser)      +---------------------+
    |                                     | 인스펙터 | 씬 설정    |
    +-------------------------------------+                     |
    | 타임라인 (transport, problems, one track per motion, labels)|
    | 프로젝트 (data folders) | 분석 | 비교 | 데이터셋 (콘솔: 보기)   |
    +-- status bar: only what needs attention (jobs, physics, 환경 ⚠) +

The 3D view is the viser scene of retlens/app/scene.py served on 127.0.0.1 and shown in
a Qt WebEngine view with viser's own control panel hidden; every control lives in Qt.
"""

from __future__ import annotations

import math
import os
import socket
import threading
import time
from html import escape

import numpy as np
from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QPoint, QPointF, QRect, QRectF,
                            QSettings, QSortFilterProxyModel, Qt, QThread, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QDesktopServices, QFont, QFontMetrics, QIcon,
                           QKeySequence, QPainter, QPalette, QPen, QPixmap)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox,
                               QSplitter,
                               QStyle, QStyledItemDelegate, QTableView, QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QToolTip, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import autolabel, batch, cmu_labels, dataset, motion_labels, problems
from . import export_dialogs
from . import session as work
from .. import paths as app_paths  # "paths" is a common local name here
from .. import settings
from ..compare import MOTION_EXT, Item, library_files
from .scene import (BALANCE, GRAPH_FIXED, METRIC_DESC, METRIC_HELP, METRIC_HELP_FOOTER, PROBLEM_NAMES, RETARGET_NOTE,
                    RETARGET_TIPS, SWING_CLEARANCE_CM, MotionScene, rel, retarget_text)

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
    "harness": "MuJoCo에서 리타겟 관절각을 높은 게인의 PD로 따라가고, 골반 보조 힘(가상 하네스)이 균형을 대신 잡습니다"
               "(기본). 보조 힘이 체중의 몇 %인지가 그 동작이 발만으로 균형을 잡기 얼마나 어려운지 보여 줍니다. "
               "따로 설치할 것이 없고 클립 하나에 몇 초면 끝납니다",
    "pd": "MuJoCo에서 리타겟 관절각을 높은 게인의 PD로 그대로 따라갑니다. 균형 제어도 보조 힘도 없어 걷기도 대부분 "
          "1–2초 안에 넘어집니다(보조 힘 (MuJoCo)에서 보조 힘만 뺀 개루프 재생)",
    "gmt": "MuJoCo에서 공개된 G1 범용 추적 정책 GMT가 기준 동작과 로봇 자신의 상태를 보고 관절 목표를 냅니다"
           "(실제 로봇이 모캡을 따라 하는 방식). 보조 힘은 없습니다",
    "isaac": "Isaac Sim PhysX에서 골반 보조 힘(가상 하네스)이 균형을 대신 잡습니다(0.6.0까지의 기본 물리 모드). "
             "Isaac Sim 설치와 NVIDIA EULA 동의가 필요합니다. 배율은 '물리 > 골반 보조 힘 (Isaac)'에서 바꿉니다",
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
    """Per-user settings (window layout, Isaac EULA consent)."""
    return QSettings(APP_NAME, APP_NAME)


# The repository's editor and the installed RetLens share one QSettings store. The Isaac EULA consent is
# the user's either way; the window layout, the file dialog's folder and the first-run check are per layout,
# so one program closing last no longer decides the other's layout.
LAYOUT_KEYS = ("window/geometry", "window/state", "layout/has_compare", "layout/has_dataset", "layout/tidy_v1",
               "dialog/dir", "setup/checked")


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


class _PassShortcuts(QObject):
    """Lets the window's one-key shortcuts (Space, N, P, O, F, S, ...) through a focused number box, which would
    otherwise take them; digits, arrows, Home / End and Ctrl+ keys (its own undo, copy) stay the box's."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ShortcutOverride and (e.key() == Qt.Key_Space or Qt.Key_A <= e.key() <= Qt.Key_Z) \
                and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            e.ignore()
            return True
        return False


class _SceneUndoKeys(QObject):
    """The 3D view (Chromium) takes Ctrl+Z / Ctrl+Y as its own editing keys; it has no text to edit, so they go
    to the window's 되돌리기 / 다시 실행 (label edits) instead."""

    def __init__(self, view: QWidget):
        super().__init__(view)
        self.view = view

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ShortcutOverride and isinstance(obj, QWidget) and \
                (obj is self.view or self.view.isAncestorOf(obj)) and \
                (e.matches(QKeySequence.Undo) or e.matches(QKeySequence.Redo)):
            e.ignore()
            return True
        return False


_pass_filter: _PassShortcuts | None = None


def pass_shortcuts(box: QWidget) -> QWidget:
    global _pass_filter
    if _pass_filter is None:
        _pass_filter = _PassShortcuts()
    box.installEventFilter(_pass_filter)
    return box


SECTION_CSS = "margin-top: 10px; border-bottom: 1px solid rgba(128,128,128,0.4)"


def section_label(text: str) -> QLabel:
    """A bold section heading with a line under it (인스펙터, 씬 설정)."""
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    lab.setStyleSheet(SECTION_CSS)
    return lab


class Fold(QWidget):
    """A section that opens and closes from its heading (▸ / ▾); whether it is open is kept by key in `opened`
    (the caller saves it). `extra` sits on the heading's right, visible while closed too."""

    def __init__(self, title: str, key: str, opened: set, extra: QWidget | None = None, on_toggle=None, tip: str = ""):
        super().__init__()
        self.key, self.opened, self.on_toggle = key, opened, on_toggle
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(2)
        head = QWidget()
        head.setObjectName("fold_head")
        head.setStyleSheet("#fold_head { border-bottom: 1px solid rgba(128,128,128,0.4) }")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 2)
        self.button = QToolButton()
        self.button.setText(title)
        self.button.setToolTip(tip)
        self.button.setCheckable(True)
        self.button.setAutoRaise(True)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.button.setStyleSheet("QToolButton { text-align: left; font-weight: bold; border: none; padding: 1px }")
        hl.addWidget(self.button, 1)
        if extra is not None:
            hl.addWidget(extra)
        lay.addWidget(head)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 2, 0, 0)
        lay.addWidget(self.body)
        on = key in opened
        self.button.setChecked(on)
        self._show(on)
        self.button.toggled.connect(self._toggled)

    def is_open(self) -> bool:
        return self.button.isChecked()

    def set_title(self, title: str) -> None:
        if self.button.text() != title:
            self.button.setText(title)

    def _show(self, on: bool) -> None:
        self.button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)

    def _toggled(self, on: bool) -> None:
        self._show(on)
        (self.opened.add if on else self.opened.discard)(self.key)
        if self.on_toggle is not None:
            self.on_toggle(on)


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
    labelled = Signal(object)  # (job, item, automatic labels) made off the GUI thread
    log = Signal(str)
    gui = Signal(object)  # a callable a worker thread hands to the GUI thread (EditorWindow._run_on_gui)


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
QC_COLORS = {"FAIL": QColor(230, 90, 80), "WARN": QColor(230, 160, 60)}


def score_text(it: Item) -> str:
    """'78 WARN': the retargeting score and QC of a motion (QC alone for a robot motion)."""
    m = it.metrics
    score = m.get("retarget_score")
    qc = str(m.get("qc") or "")
    return f"{score:.0f} {qc}".strip() if isinstance(score, (int, float)) else qc


class HierarchyPanel(QTreeWidget):
    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setHeaderLabels(["이름", "점수", "물리"])
        self.headerItem().setToolTip(1, "리타게팅 점수(0–100)와 QC. 마우스를 올리면 감점 이유가 나옵니다")
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemSelectionChanged.connect(self._selected)
        self.itemChanged.connect(self._changed)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2):
            self.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.setColumnHidden(2, True)  # while no motion has physics
        self._filling = False

    def rebuild(self) -> None:
        self._filling = True
        sel = self.win.selected
        self.clear()
        for it in self.win.scene.items:
            row = QTreeWidgetItem([it.label, "", ""])
            row.setIcon(0, color_icon(it.color))
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked if it.visible else Qt.Unchecked)
            row.setData(0, Qt.UserRole, id(it))
            row.setToolTip(0, f"{rel(it.source)}\n{it.kind}")
            self.addTopLevelItem(row)
            if it is sel:
                row.setSelected(True)
        self._filling = False
        self.refresh()

    def refresh(self) -> None:
        sc = self.win.scene
        self._filling = True  # the visibility check follows the scene (e.g. the API)
        phys_any = False
        for i in range(self.topLevelItemCount()):
            row = self.topLevelItem(i)
            it = self.win.item_by_id(row.data(0, Qt.UserRole))
            if it is None:
                continue
            state = Qt.Checked if it.visible else Qt.Unchecked
            if row.checkState(0) != state:
                row.setCheckState(0, state)
            score = score_text(it)
            if row.text(1) != score:  # 다시 리타게팅 changes it
                row.setText(1, score)
                row.setForeground(1, QBrush(QC_COLORS.get(it.metrics.get("qc"), self.palette().color(QPalette.Text))))
                facts = dict(sc.item_facts(it))
                notes = it.metrics.get("qc_notes")
                row.setToolTip(1, "\n".join(x for x in (facts.get("리타게팅 점수"), f"QC: {notes}" if notes else "") if x))
            has_phys = sc.physics_on or bool(it.handles.get("phys")) or sc.is_sim_result(it)
            phys_any |= has_phys
            text = sc.job_text(it) if has_phys else ""
            row.setText(2, text.split(" · ")[0] if text else "")
            row.setToolTip(2, text)
        if self.isColumnHidden(2) == phys_any:
            self.setColumnHidden(2, not phys_any)
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
        self.win.motion_menu(m, it)
        m.exec(self.viewport().mapToGlobal(pos))


# ------------------------------------------------------------------------------ inspector
class InspectorPanel(QScrollArea):
    """The selected motion: a summary (what it is, its score, QC and problems), then sections that fold (세부 정보,
    보정, 지표; open or closed as last left), 라벨, and 물리 / 동영상 only when there is something to say."""
    SUMMARY = ("종류", "파일", "길이", "QC", "리타게팅 점수", "다시 리타게팅", "물체", "손–물체", "C3D 마커",
               "마커 QC")  # item_facts rows

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.item: Item | None = None
        self._labels_shown = None
        self._selecting = False
        self._open = set(win.settings.value("inspector/open", [], type=list) or [])  # the folds left open
        self._build_empty()

    def _clear(self) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        self.setWidget(w)  # the old widgets go: nothing may point at them
        self._seg_model = self._seg_table = self._save_labels = None
        return lay

    def _build_empty(self) -> None:
        lay = self._clear()
        hint = QLabel("선택한 모션이 없습니다.\n\n계층 패널이나 타임라인에서 모션을 고르면 여기에 점수와 문제가 나옵니다. "
                      "모션은 파일 > 열기 (Ctrl+O), 프로젝트 패널에서 두 번 클릭, 또는 탐색기에서 끌어다 놓아 추가합니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay.addWidget(hint)

    def _fold(self, title: str, key: str, extra: QWidget | None = None, tip: str = "", on_toggle=None) -> Fold:
        def toggled(on: bool) -> None:
            self.win.settings.setValue("inspector/open", sorted(self._open))
            if on_toggle is not None:
                on_toggle(on)

        return Fold(title, key, self._open, extra, toggled, tip)

    @staticmethod
    def _value(text: str, tip: str = "") -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setToolTip(tip)
        return lab

    def show_item(self, item: Item | None) -> None:
        scroll = self.verticalScrollBar().value() if item is not None and item is self.item else None
        self.item = item
        if item is None:
            self._build_empty()
            return
        sc = self.win.scene
        lay = self._clear()
        title = QLabel(f"<span style='color:rgb{tuple(item.color)}'>■</span> <b>{escape(item.label)}</b>")
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
        details = []
        for k, v in sc.item_facts(item):
            if k not in self.SUMMARY:
                details.append((k, v))
                continue
            tip = ""
            if k == "파일":  # let long paths wrap at the separators
                v = v.replace("\\", "/").replace("/", "/​")
            elif k == "종류":  # 'FBX -> GMR, foot-flat': the corrections stay, the smoothing goes to the tip
                v, tip = ", ".join(x for x in (p.strip() for p in v.split(",")) if not x.startswith("smooth")), v
            lab = self._value(v, tip)
            notes = item.metrics.get("qc_notes")
            if k == "QC" and notes and v != "PASS":  # why it is not PASS
                lab.setTextFormat(Qt.RichText)
                lab.setText(f"{escape(v)}<br><span style='color:gray'>{escape(notes)}</span>")
            form.addRow(k, lab)
        self.problem_lab = self._value("")
        form.addRow("문제 구간", self.problem_lab)
        lay.addLayout(form)

        row = QHBoxLayout()  # this motion's display: its skeleton, its start on the shared timeline
        self.hv = None
        if item.human is not None:
            self.hv = QCheckBox("사람 스켈레톤")
            self.hv.setToolTip("이 모션의 사람 스켈레톤 (모든 모션: 씬 설정)")
            self.hv.setChecked(item.show_human)
            self.hv.toggled.connect(lambda on: sc.set_show_human(item, on))
            row.addWidget(self.hv)
        row.addStretch(1)
        self.offset_label = QLabel("시간 오프셋 (s)")
        row.addWidget(self.offset_label)
        self.offset = pass_shortcuts(QDoubleSpinBox())
        self.offset.setRange(-600.0, 600.0)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(1 / 30)
        self.offset.setValue(item.offset)
        self.offset.setToolTip("공통 시간축에서 이 모션이 시작하는 시각. 분석 탭의 '기준에 시간 자동 정렬'로도 맞춥니다")
        self.offset.valueChanged.connect(lambda v: sc.set_offset(item, v))
        row.addWidget(self.offset)
        lay.addLayout(row)

        if details:  # what the summary leaves out
            fold = self._fold(f"세부 정보 ({len(details)})", "details")
            dform = QFormLayout()
            dform.setLabelAlignment(Qt.AlignLeft)
            for k, v in details:
                dform.addRow(k, self._value(v))
            fold.body_layout.addLayout(dform)
            lay.addWidget(fold)

        if item.retarget:  # 이 모션의 보정: retarget this one again, or find the corrections that score best
            r = item.retarget
            swing_cm = r.get("swing_clearance_cm") or SWING_CLEARANCE_CM
            now = (bool(r.get("foot_flat")), r.get("swing_clearance_cm", 0) > 0, bool(r.get("self_collision")))
            rec = QPushButton("추천 보정 찾기")
            rec.setToolTip("보정 조합 8가지로 이 모션을 리타게팅해 리타게팅 점수가 가장 높은 조합을 보여 주고, 고르면 "
                           "그 보정으로 바꿉니다. 처음에는 리타게팅 8번이라 몇 분 걸리고, 다음부터는 바로 나옵니다")
            rec.clicked.connect(lambda: self.win.recommend_retarget(item))
            text = retarget_text(now[0], r.get("swing_clearance_cm", 0.0), now[2])
            fold = self._fold(f"보정: {'없음' if text == '보정 없음' else text}", "retarget", rec,
                              "이 모션만 다른 보정으로 다시 리타게팅합니다. 새로 여는 모션의 보정은 리타게팅 메뉴에서 정합니다")
            boxes = []
            for label, on, tip in (("디딤발 평평", now[0], RETARGET_TIPS["foot_flat"]),
                                   (f"스윙 발 보정 ({swing_cm:g} cm)", now[1], RETARGET_TIPS["swing"]),
                                   ("자기 관통 보정", now[2], RETARGET_TIPS["self_collision"])):
                b = QCheckBox(label)
                b.setToolTip(tip)
                b.setChecked(on)
                fold.body_layout.addWidget(b)
                boxes.append(b)
            again = QPushButton("다시 리타게팅")
            again.setToolTip("위 보정으로 이 모션만 다시 리타게팅해 같은 자리에 바꿔 넣습니다(이름·색·오프셋·라벨 유지). "
                             "전후 점수는 위 '다시 리타게팅' 줄에 나옵니다. 리타게팅 메뉴의 설정은 바뀌지 않습니다")
            again.setEnabled(False)  # until a box differs from how it was retargeted
            for b in boxes:
                b.toggled.connect(lambda _on: again.setEnabled(tuple(x.isChecked() for x in boxes) != now))
            again.clicked.connect(lambda: self.win.retarget_item(item, boxes[0].isChecked(),
                                                                 swing_cm if boxes[1].isChecked() else 0.0,
                                                                 boxes[2].isChecked()))
            fold.body_layout.addWidget(again)
            lay.addWidget(fold)

        lay.addWidget(section_label("라벨"))
        self._build_labels(lay, item)

        self.phys_box = QWidget()  # shown while physics mode is on, or results were computed
        pl = QVBoxLayout(self.phys_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(section_label("물리"))
        self.phys = self._value("")
        pl.addWidget(self.phys)
        self.falls = QTableWidget(0, 3)  # the shown result's falls: a click goes to where its first cause started
        self.falls.setHorizontalHeaderLabels(["넘어짐 (s)", "1차 원인", "시작 (s)"])
        self.falls.verticalHeader().setVisible(False)
        self.falls.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.falls.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.falls.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.falls.setToolTip("누르면 그 넘어짐의 1차 원인이 시작된 곳으로 갑니다 (행에 마우스를 올리면 근거)")
        self.falls.cellClicked.connect(self._fall_clicked)
        self._falls_key = None
        pl.addWidget(self.falls)
        lay.addWidget(self.phys_box)

        self.video_box = QWidget()  # shown once a video was asked for (파일 menu, Ctrl+E, right-click)
        vl = QVBoxLayout(self.video_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(section_label("동영상"))
        self.video = QLabel()
        self.video.setWordWrap(True)
        self.video.setTextFormat(Qt.RichText)
        self.video.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.video.linkActivated.connect(lambda link: self.win.open_path(
            sc.video_file(item) if link == "file" else os.path.dirname(sc.video_file(item) or "")))
        vl.addWidget(self.video)
        lay.addWidget(self.video_box)

        self.metrics_fold = self._fold("지표", "metrics", help_button("지표 설명", metric_help_html(), icon_only=True),
                                       on_toggle=lambda on: on and self.refresh())
        self.metrics = QTableWidget(0, 2)
        self.metrics.setHorizontalHeaderLabels(["지표", "값"])
        self.metrics.verticalHeader().setVisible(False)
        self.metrics.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.metrics.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # as tall as its rows: the panel scrolls
        self.metrics_fold.body_layout.addWidget(self.metrics)
        lay.addWidget(self.metrics_fold)
        self.refresh()
        if scroll is not None:  # rebuilt for the same motion (labels changed): stay where the user was
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def _build_labels(self, lay: QVBoxLayout, item: Item) -> None:
        """Where the motion's labels come from (or '라벨 없음', the how-to on hover), load / automatic labels /
        rule file, the rest under ⋯ (the right-click menu's 라벨 entries), and its segments (a click goes to the
        segment's start)."""
        # read once (other threads replace them); refresh() rebuilds when they change (menu, API, drop)
        self._labels_shown = lab = item.labels
        self._labels_info = info = self._value("")
        self._labels_edited = edited = self._value("편집됨 (저장 안 함) · 라벨 CSV로 저장...으로 남깁니다")
        edited.setStyleSheet("color: rgb(230,150,60)")
        self._show_labels_info(item, lab)
        lay.addWidget(info)
        lay.addWidget(edited)
        segs = lab.segments if lab is not None else []
        rules = autolabel.rules_file()
        row = QHBoxLayout()
        load = QPushButton("불러오기...")
        load.setToolTip("CSV·JSON 라벨 파일을 골라 이 모션에 붙입니다(파일은 바꾸지 않음)")
        load.clicked.connect(lambda: self.win.load_labels_dialog(item))
        row.addWidget(load)
        auto = QPushButton("자동 라벨")
        auto.setToolTip("규칙 파일대로 이 모션의 사람 동작을 보고 라벨을 붙입니다"
                        + (f"\n규칙: {rules}" if rules else "\n(규칙 파일을 먼저 고릅니다)"))
        auto.clicked.connect(lambda: self.win.auto_label(item))
        auto.setVisible(self.win.scene.has_skeleton(item))  # a robot motion has no person to label
        row.addWidget(auto)
        pick = QPushButton("규칙 파일...")
        pick.setToolTip("자동 라벨에 쓸 규칙 파일(YAML·JSON)을 고릅니다" + (f"\n지금: {rules}" if rules else ""))
        pick.clicked.connect(lambda: self.win.pick_label_rules(item if self.win.scene.has_skeleton(item) else None))
        row.addWidget(pick)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("다시 읽기, 빼기, CSV로 저장, 라벨 파일 열기, 열린 모션 모두 자동 라벨")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        menu = QMenu(more)
        menu.aboutToShow.connect(lambda: (menu.clear(), self.win.add_label_actions(menu, item)))
        more.setMenu(menu)
        row.addWidget(more)
        row.addStretch(1)
        lay.addLayout(row)
        edit = QHBoxLayout()  # editing: the picked segment (timeline or the list below)
        for text, tip, fn in (
                ("＋ 구간", "재생 위치의 빈칸에 구간을 더합니다 (고른 구간의 트랙, 트랙이 없으면 새 트랙)",
                 lambda: self.win.label_add_here(item)),
                ("나누기", "고른 구간을 재생 위치에서 둘로 나눕니다 (S)", self.win.label_split),
                ("삭제", "고른 구간을 지웁니다 (타임라인이나 이 표에서 Delete)", self.win.label_delete),
                ("↶", "되돌리기 (Ctrl+Z)", lambda: self.win.label_undo()),
                ("↷", "다시 실행 (Ctrl+Y)", lambda: self.win.label_undo(redo=True))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            edit.addWidget(b)
        edit.addStretch(1)
        self._save_labels = save = QPushButton("라벨 CSV로 저장...")
        save.setToolTip("지금 라벨을 CSV로 저장합니다. 모션 옆에 <이름>.labels.csv로 두면 열 때 붙습니다")
        save.clicked.connect(lambda: self.win.save_labels_dialog(item))
        edit.addWidget(save)
        lay.addLayout(edit)
        self._show_labels_info(item, lab)
        self._seg_model = None
        if not segs:
            return
        multi = len(lab.tracks) > 1 or bool(lab.tracks[0])
        table = QTableView()
        # rows are made as they scroll into view: a long take has thousands
        model = SegmentModel(item, segs, multi, table,
                             on_edit=lambda seg, field, value: self.win.edit_segment(item, item.labels, seg, field, value))
        table.setModel(model)
        table.setItemDelegate(SegmentDelegate(model, self.win.scene.label_names, table))
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.horizontalHeader().setSectionResizeMode(len(model.heads) - 3, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.DoubleClicked)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setMinimumHeight(min(220, 26 + 22 * len(segs)))
        table.setToolTip("누르면 그 구간을 고르고 처음으로 갑니다. 두 번 누르면 라벨·시간을 고칩니다. 우클릭: 편집")
        table.clicked.connect(lambda i: self._segment_clicked(model.segs[i.row()]))
        table.selectionModel().currentRowChanged.connect(  # Up / Down: the picked segment follows (no seek)
            lambda cur, _prev: cur.isValid() and not self._selecting and self.win.set_label_selection(
                self.item, model.segs[cur.row()]))
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos: self._segment_menu(table, model, pos))
        self._seg_table, self._seg_model = table, model
        lay.addWidget(table)
        self.select_segment(self.win.label_selection()[2] if self.win.label_selection() is not None else None)

    def _show_labels_info(self, item: Item, lab) -> None:
        if lab is None:
            self._labels_info.setText("라벨 없음")
            self._labels_info.setToolTip(labels_text(item, None))
            self._labels_info.setStyleSheet("color: gray")
        else:
            self._labels_info.setText(labels_text(item, lab))
            self._labels_info.setToolTip("")
            self._labels_info.setStyleSheet("color: rgb(230,150,60)" if lab.error else "")
        dirty = lab is not None and lab.edited
        self._labels_edited.setVisible(dirty)
        save = getattr(self, "_save_labels", None)
        if save is not None:
            save.setEnabled(lab is not None and (bool(lab.segments) or dirty))
            f = save.font()
            f.setBold(dirty)
            save.setFont(f)

    def _segment_clicked(self, seg) -> None:
        it = self.item
        self.win.set_label_selection(it, seg)
        self.win.scene.set_playing(False)
        self.win.scene.seek(it.offset + seg.start)

    def _segment_menu(self, table, model, pos) -> None:
        index = table.indexAt(pos)
        if not index.isValid():
            return
        seg = model.segs[index.row()]
        self.win.set_label_selection(self.item, seg)
        m = QMenu(self)
        self.win.label_menu(m, self.item, seg)
        m.exec(table.viewport().mapToGlobal(pos))

    def select_segment(self, seg) -> None:
        """The picked segment selected (and scrolled to) in the list."""
        model = getattr(self, "_seg_model", None)
        if model is None:
            return
        row = next((k for k, s in enumerate(model.segs) if s is seg), None) if seg is not None else None
        sm = self._seg_table.selectionModel()
        if row is None:
            sm.clearSelection()
            return
        index = model.index(row, 0)
        if not sm.isRowSelected(row, QModelIndex()):
            self._selecting = True  # not a pick by the user (currentRowChanged)
            try:
                self._seg_table.selectRow(row)
            finally:
                self._selecting = False
        self._seg_table.scrollTo(index)

    def _labels_changed_in_place(self, it: Item) -> bool:
        """New labels on the shown motion (an edit, undo): the list and the lines updated where they are, so the
        list keeps its scroll; False when the panel has to be built again (labels came or went, tracks changed)."""
        lab, old, model = it.labels, self._labels_shown, getattr(self, "_seg_model", None)
        if model is None or lab is None or old is None or not lab.segments:
            return False
        if (len(lab.tracks) > 1 or bool(lab.tracks[0])) != model.multi:
            return False
        self._labels_shown = lab
        scroll = self._seg_table.verticalScrollBar().value()
        model.set_segments(lab.segments)
        self._seg_table.verticalScrollBar().setValue(scroll)
        self._show_labels_info(it, lab)
        sel = self.win.label_selection()
        self.select_segment(sel[2] if sel is not None else None)
        return True

    def _fill_falls(self, it: Item) -> None:
        """The falls of what is shown (physics mode, or a result file): time, first cause, where it started."""
        sc = self.win.scene
        shown = sc.shown(it)
        details = sc.fall_details(shown) if shown is not it or sc.is_sim_result(it) else []
        key = (id(shown), id(shown.info), len(details))
        if key == self._falls_key:
            return
        self._falls_key = key
        self.falls.setRowCount(len(details))
        for r, d in enumerate(details):
            cause = d["cause_ko"] or ("분석 실패" if d["why_none"].startswith("원인 분석 실패") else d["why_none"] or
                                      (f"판정: {d['rule_ko']}" if d["rule_ko"] else "-"))
            onset = d["onset_s"]
            for c, text in enumerate((f"{d['time_s']:.2f}" + (" (끝난 뒤)" if d["after_clip"] else ""), cause,
                                      f"{onset:.2f}" if onset is not None else "-")):
                cell = QTableWidgetItem(text)
                cell.setToolTip(sc.fall_tip(shown, d))
                cell.setData(Qt.UserRole, onset if onset is not None else d["time_s"])
                if c != 1:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.falls.setItem(r, c, cell)
        self.falls.setVisible(bool(details))
        self.falls.setFixedHeight(self.falls.horizontalHeader().height() + 2
                                  + sum(self.falls.rowHeight(r) for r in range(min(len(details), 8))))

    def _fall_clicked(self, row: int, _col: int) -> None:
        cell, it = self.falls.item(row, 0), self.item
        if cell is not None and it is not None:
            self.win.scene.set_playing(False)
            self.win.scene.seek(it.offset + float(cell.data(Qt.UserRole)))

    def refresh(self, metrics: bool = True) -> None:
        """metrics=False: only the status lines (job progress), not the problems and the metric table."""
        it, sc = self.item, self.win.scene
        if it is None or it not in sc.items:
            return
        if it.labels is not self._labels_shown:  # edited, loaded, reloaded or removed (menu, API, a dropped file)
            if not self._labels_changed_in_place(it):
                self.show_item(it)
                return
        overview = sc.results_overview(it)
        sim = sc.is_sim_result(it)
        self.phys_box.setVisible(sim or sc.physics_on or bool(overview))
        if sim:
            text = sc.job_text(it)
        else:  # this mode's state, then what the other modes gave (they are kept: switching back is instant)
            lines = [f"{sc.mode_label()}: {sc.job_text(it)}"] if sc.physics_on else []
            others = [(m, r) for m, r in overview if not (sc.physics_on and m == sc.mode_label())]
            if others:
                lines.append(("계산해 둔 다른 결과:" if sc.physics_on else "계산해 둔 결과 (물리 모드를 켜면 그립니다):")
                             + "".join(f"\n· {m}: {r}" for m, r in others))
            text = "\n".join(lines)
        if self.phys.text() != text:
            self.phys.setText(text)
        self._fill_falls(it)
        video, file = sc.video_text(it), sc.video_file(it)
        self.video_box.setVisible(bool(video))
        html = (f"동영상 저장됨: <a href='file'>{escape(os.path.basename(file))}</a> · <a href='folder'>폴더</a>"
                if file else escape(video))
        if self.video.text() != html:
            self.video.setText(html)
        show_offset = len(sc.items) > 1 or abs(it.offset) > 1e-9  # one motion at 0 s: nothing to move
        self.offset_label.setVisible(show_offset)
        self.offset.setVisible(show_offset)
        if abs(self.offset.value() - it.offset) > 1e-6:
            self.offset.blockSignals(True)
            self.offset.setValue(it.offset)
            self.offset.blockSignals(False)
        if self.hv is not None and self.hv.isChecked() != it.show_human:  # the API can change it
            self.hv.blockSignals(True)
            self.hv.setChecked(it.show_human)
            self.hv.blockSignals(False)
        if not metrics:
            return
        probs = sc.problems(it)  # of what is shown: physics mode has its own
        kinds = [k for k in PROBLEM_NAMES if probs.get(k)]
        self.problem_lab.setText(" · ".join(f"{PROBLEM_NAMES[k]} {len(probs[k])}" for k in kinds) or "없음")
        self.problem_lab.setToolTip("\n".join(
            [f"{PROBLEM_NAMES[k]}: {len(probs[k])}구간 · {sum(b - a for a, b in probs[k]):.1f}초" for k in kinds]
            + ["N / Shift+N 또는 타임라인의 '문제 ▶'로 다음 / 이전 문제로 갑니다"]))
        if not self.metrics_fold.is_open():  # nothing to fill while it is folded
            return
        names, cols = sc.metric_table(self.win.analysis.ref_item())
        vals = next((v for c, v in cols if c is it), None)
        if vals is None:
            return
        rows = [(n, str(v)) for n, v in zip(names, vals) if str(v) not in ("-", "")]  # what this motion has
        self.metrics.setRowCount(len(rows))
        for r, (n, v) in enumerate(rows):
            label = QTableWidgetItem(n)
            label.setToolTip(metric_tip(n))
            self.metrics.setItem(r, 0, label)
            cell = QTableWidgetItem(short_text(v, 22))
            cell.setToolTip(v)  # full text, also when the column is too narrow and Qt elides it
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.metrics.setItem(r, 1, cell)
        self.metrics.setFixedHeight(self.metrics.horizontalHeader().height() + 2
                                    + sum(self.metrics.rowHeight(r) for r in range(len(rows))))


# ------------------------------------------------------------------------------ scene settings
class SceneSettingsPanel(QScrollArea):
    """How every motion is drawn, in groups: 배치, 사람, 표시, 물체. Rows that cannot apply are off or hidden:
    간격 only side by side, the skeleton's place only with skeletons, SMPL-X and 물체 only when such a motion is
    open (refresh)."""

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        sc, v = win.scene, win.scene.view

        def combo(options, current, apply):
            c = QComboBox()
            c.addItems(options)
            c.setCurrentText(current)
            c.currentTextChanged.connect(apply)
            return c

        def check(text, value, apply, tip=""):
            c = QCheckBox(text)
            c.setChecked(value)
            c.setToolTip(tip)
            c.toggled.connect(apply)
            return c

        def group(title):
            lay.addWidget(section_label(title))
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignLeft)
            lay.addLayout(form)
            return form

        form = group("모션 배치")
        self.spacing = pass_shortcuts(QDoubleSpinBox())
        self.spacing.setRange(0.3, 5.0)
        self.spacing.setSingleStep(0.1)
        self.spacing.setValue(v.spacing)
        self.spacing.setSuffix(" m")
        self.spacing.valueChanged.connect(lambda x: setattr(v, "spacing", float(x)))
        self.spacing.setEnabled(v.side_by_side)

        def side(text):
            v.side_by_side = text == "나란히"
            self.spacing.setEnabled(v.side_by_side)

        form.addRow("배치", combo(["나란히", "겹쳐서"], "나란히" if v.side_by_side else "겹쳐서", side))
        form.addRow("간격", self.spacing)
        form.addRow(check("시작 위치·방향 맞춤", v.align, lambda on: setattr(v, "align", on),
                          "모션마다 시작 위치와 방향을 맞춰 나란히 놓습니다"))

        form = group("사람")
        self.beside = combo(["로봇 옆", "로봇과 겹쳐서"], "로봇 옆" if v.human_beside else "로봇과 겹쳐서",
                            lambda t: setattr(v, "human_beside", t == "로봇 옆"))
        self.beside.setEnabled(v.show_humans)

        def humans(on):
            v.show_humans = on
            self.beside.setEnabled(on)

        form.addRow(check("사람 스켈레톤 (모두)", v.show_humans, humans, "모션 하나만 끄려면 인스펙터에서"))
        form.addRow("스켈레톤 위치", self.beside)
        self.body_mesh = check("SMPL-X 몸 메시", v.body_mesh, lambda on: self._set(body_mesh=on),
                               "AMASS SMPL-X 모션의 사람을 막대 대신 몸 표면으로 그립니다(SMPL-X 모델 필요)")
        form.addRow(self.body_mesh)

        form = group("표시")
        form.addRow(check("로봇 반투명", v.robot_translucent, lambda on: self._set(robot_translucent=on)))
        form.addRow(check("이름표", v.show_labels, lambda on: setattr(v, "show_labels", on)))
        form.addRow(check("지금 구간 라벨", v.show_label_now, lambda on: setattr(v, "show_label_now", on),
                          "라벨 파일이 있는 모션은 재생 중인 구간의 라벨을 로봇 이름표 아래에 띄웁니다(라벨이 없는 시간에는 안 보임)"))
        form.addRow(check("균형 표시", v.show_balance, lambda on: setattr(v, "show_balance", on),
                          "바닥에 지지다각형(초록), CoM 투영(파랑), ZMP(빨강)를 그립니다"))

        self.objects_box = QWidget()  # FBX props and furniture: only when an open motion has them
        ol = QVBoxLayout(self.objects_box)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(section_label("물체"))
        self.paths = check("물체 궤적", v.show_object_paths, lambda on: setattr(v, "show_object_paths", on),
                           "움직이는 물체가 클립 동안 지나간 길")
        self.paths.setEnabled(v.show_objects)

        def objects(on):
            v.show_objects = on
            self.paths.setEnabled(on)

        ol.addWidget(check("물체", v.show_objects, objects,
                           "FBX에 사람과 함께 담긴 물체(소품·가구)를 로봇 쪽에 그립니다. 위치는 사람 스켈레톤처럼 로봇 크기에 "
                           "맞춰 옮기고, 물체 크기는 실제 그대로입니다"))
        ol.addWidget(self.paths)
        lay.addWidget(self.objects_box)
        self.setWidget(w)
        self.refresh()

    def refresh(self) -> None:
        """Show the rows that apply to the open motions."""
        items, v = list(self.win.scene.items), self.win.scene.view
        self.body_mesh.setVisible(v.body_mesh or any(it.kind.startswith("SMPL-X") for it in items))
        self.objects_box.setVisible(any(it.human is not None and it.human.objects for it in items))

    def _set(self, **kw) -> None:
        for k, val in kw.items():
            setattr(self.win.scene.view, k, val)
        self.win.scene.view_changed(*kw)


# ------------------------------------------------------------------------------ timeline
RULER_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200, 1800, 3600)
SPEEDS = (0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 4.0)  # the timeline's playback speeds (the API may set any other)


def ruler_step(span: float) -> float:
    """Seconds between the timeline's ticks: at most 14 of them, however long the motions are."""
    need = span / 14
    return next((s for s in RULER_STEPS if s >= need), 3600 * math.ceil(need / 3600))


class _Same:
    """Equal only to itself wrapping the same object, which it keeps alive (unlike id())."""
    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return isinstance(other, _Same) and other.obj is self.obj

    def __hash__(self):
        return id(self.obj)


class TimelineTracks(QWidget):
    """Ruler, one bar per motion (its offset and length, falls in red), its labelled segments in
    lanes under the bar (one lane per label track, retlens.motion_labels) and the playhead. A
    motion without labels is the plain bar. All but the playhead and the outline of the segments
    being played is drawn once into a picture (_layer) and redrawn only when it changes: long
    motions have thousands of segments, and the timeline is refreshed every frame."""
    NAME_W, RULER_H, ROW_H, LANE_H = 150, 22, 20, 18

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.setMinimumHeight(self.RULER_H + self.ROW_H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)  # Esc stops dragging a segment's edge; Delete deletes the picked segment
        self._drag = False
        self._edge: dict | None = None  # dragging the picked segment's start or end (label editing)
        self._no_menu = 0.0  # when a right press cancelled a drag: its menu (right after) does not open
        self._layer: tuple | None = None  # (_layer_key(), QPixmap)

    def sizeHint(self):
        from PySide6.QtCore import QSize

        rows = self._rows()
        return QSize(600, (rows[-1][1] + rows[-1][2] if rows else self.RULER_H + self.ROW_H) + 4)

    def _rows(self) -> list[tuple]:
        """(motion, top, height, label tracks, labels) per row: a motion with labels is taller by its
        lanes. The labels are the ones the row was laid out with: motions get new labels from other
        threads (opening, the API) while this draws, so everything after reads them from here."""
        out, y = [], self.RULER_H
        for it in list(self.win.scene.items):
            labels = it.labels
            tracks = labels.tracks if labels is not None else []
            h = self.ROW_H + self.LANE_H * len(tracks)
            out.append((it, y, h, tracks, labels))
            y += h
        return out

    def _row_at(self, y: float):
        if y < self._ruler_top() + self.RULER_H:  # the ruler stays over the rows scrolled under it
            return None
        return next((r for r in self._rows() if r[1] <= y < r[1] + r[2]), None)

    def _ruler_top(self) -> int:
        """Where the ruler is drawn: the top of the part in view (in TimelinePanel's scroll area the
        rows scroll and the ruler stays)."""
        return max(0, -self.y())

    def _seg_rect(self, it: Item, y: int, lane: dict, s, span, dur: float) -> QRectF | None:
        """Where a segment is drawn: clipped to what plays (a physics result may be shorter); None past
        its end or in no lane of the row."""
        k = lane.get(s.track)
        if s.start >= dur or k is None:
            return None
        x0, x1 = self._x(it.offset + s.start, span), self._x(it.offset + min(s.end, dur), span)
        return QRectF(x0, y + self.ROW_H - 1 + k * self.LANE_H, max(1.0, x1 - x0), self.LANE_H - 3)

    def _segments(self, it: Item, labels, y: int, tracks: list[str], span=None):
        """(segment, rect) of a motion's labels as drawn."""
        span = span or self._span()
        dur = self.win.scene.shown(it).robot.duration
        lane = {t: k for k, t in enumerate(tracks)}
        for s in labels.segments:
            r = self._seg_rect(it, y, lane, s, span, dur)
            if r is not None:
                yield s, r

    def segment_at(self, pos):
        """(motion, segment) under the mouse (within a pixel of a thin one), or None. Looked up by
        time, not by going through the segments: it runs on every mouse move."""
        hit = self.hit_at(pos)
        return (hit[0], hit[2]) if hit is not None else None

    def hit_at(self, pos):
        """(motion, its labels as drawn, segment) under the mouse, or None."""
        row = self._row_at(pos.y())
        if row is None or not row[3] or pos.x() < self.NAME_W:
            return None
        it, y, _h, tracks, labels = row
        k = int((pos.y() - (y + self.ROW_H - 1)) // self.LANE_H)
        if not 0 <= k < len(tracks):
            return None
        lo, hi = self._span()
        px = (hi - lo) / max(1, self.width() - self.NAME_W - 10)  # seconds per pixel
        dur = self.win.scene.shown(it).robot.duration  # drawn up to what plays
        t = self._t(pos.x()) - it.offset
        for local in (t, t - px, t + px):
            if 0.0 <= local < dur:
                hit = next((s for s in labels.at(local) if s.track == tracks[k]), None)
                if hit is not None:
                    return it, labels, hit
        return None

    def lane_at(self, pos):
        """(motion, track) of the label lane under the mouse, or None (the motion's bar, the ruler)."""
        row = self._row_at(pos.y())
        if row is None or not row[3]:
            return None
        k = int((pos.y() - (row[1] + self.ROW_H - 1)) // self.LANE_H)
        return (row[0], row[3][k]) if 0 <= k < len(row[3]) else None

    def _selection(self):
        """The window's picked segment (motion, labels, segment), or None (a test's stand-in window has none)."""
        fn = getattr(self.win, "label_selection", None)
        return fn() if fn is not None else None

    def _selected_rect(self, rows=None, seg=None) -> QRectF | None:
        sel = self._selection()
        if sel is None:
            return None
        it = sel[0]
        row = next((r for r in (rows if rows is not None else self._rows()) if r[0] is it), None)
        if row is None or not row[3]:
            return None
        return self._seg_rect(it, row[1], {t: k for k, t in enumerate(row[3])}, seg or sel[2], self._span(),
                              self.win.scene.shown(it).robot.duration)

    def edge_at(self, pos) -> str | None:
        """'start' / 'end' when the mouse is on an edge of the picked segment (4 px), else None."""
        r = self._selected_rect()
        if r is None or not r.top() - 2 <= pos.y() <= r.bottom() + 2:
            return None
        x = pos.x()
        if abs(x - r.left()) <= 4 and abs(x - r.left()) <= abs(x - r.right()):
            return "start"
        return "end" if abs(x - r.right()) <= 4 else None

    def _span(self) -> tuple[float, float]:
        lo, hi = self.win.scene.time_range()
        return lo, max(hi, lo + 0.1)

    def _x(self, t: float, span=None) -> float:
        lo, hi = span or self._span()
        w = max(1, self.width() - self.NAME_W - 10)
        return self.NAME_W + (t - lo) / (hi - lo) * w

    def _t(self, x: float) -> float:
        lo, hi = self._span()
        w = max(1, self.width() - self.NAME_W - 10)
        return lo + (x - self.NAME_W) / w * (hi - lo)

    def _layer_key(self, rows: list | None = None) -> tuple:
        """Everything the picture under the playhead depends on (rows: as _rows() laid them out).
        Motions and labels are compared as objects, not by id(): a freed label set's id can come
        back for the next one, which would look unchanged."""
        sc, sel, pal = self.win.scene, self.win.selected, self.palette()
        rows = tuple((_Same(it), it.label, _Same(labels), it.offset, it.visible, it.color, sc.shown(it).robot.duration,
                      it is sel, tuple(sc.falls(it)), _Same(sc.shown(it).metrics.get("_problems"))) for it, _y, _h, _tracks, labels in
                     (rows if rows is not None else self._rows()))
        return (self.width(), self.height(), self.devicePixelRatioF(), self._span(), rows, sc.view.show_problems,
                pal.color(QPalette.Base).rgba(), pal.color(QPalette.Text).rgba(), self.font().key())

    def view_key(self) -> tuple:
        """What is drawn: TimelinePanel.refresh repaints only when this changes."""
        sel, ed = self._selection(), self._edge
        return (self._layer_key(), self.win.scene.t, _Same(sel[2]) if sel is not None else None,
                (ed["preview"].start, ed["preview"].end) if ed is not None and ed.get("preview") is not None else None)

    def paintEvent(self, _):
        rows = self._rows()
        key = self._layer_key(rows)
        if self._layer is None or self._layer[0] != key:
            dpr = self.devicePixelRatioF()
            pm = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            lp = QPainter(pm)
            try:
                self._paint_layer(lp, key[3], rows)
            finally:  # a painter left open on the pixmap kills the process when the pixmap goes
                lp.end()
            self._layer = (key, pm)
        p = QPainter(self)
        p.drawPixmap(0, 0, self._layer[1])
        p.setRenderHint(QPainter.Antialiasing)
        sc, span = self.win.scene, key[3]
        p.setPen(QPen(self.palette().color(QPalette.Text), 1.5))
        p.setBrush(Qt.NoBrush)
        for it, y, _h, tracks, labels in rows:  # the segment being played in each lane: outlined
            if tracks:
                lane, dur = {t: k for k, t in enumerate(tracks)}, sc.shown(it).robot.duration
                for s in labels.at(sc.t - it.offset):
                    r = self._seg_rect(it, y, lane, s, span, dur)
                    if r is not None:
                        p.drawRect(r.adjusted(1, 1, -1, -1))
        self._paint_selection(p, rows)
        self._paint_ruler(p, span)
        x = self._x(sc.t, span)
        p.setPen(QPen(QColor(255, 150, 40), 2))
        p.drawLine(int(x), 0, int(x), self.height())

    def _paint_selection(self, p: QPainter, rows) -> None:
        """The picked segment outlined with handles on its edges; while an edge is dragged, where it would go."""
        ed = self._edge
        preview = ed.get("preview") if ed is not None else None
        r = self._selected_rect(rows, preview)
        if r is None:
            return
        hl = self.palette().color(QPalette.Highlight).lighter(140)
        if preview is not None:
            fill = QColor(hl)
            fill.setAlpha(70)
            p.fillRect(r, fill)
        p.setPen(QPen(hl, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        for x in (r.left(), r.right()):
            p.fillRect(QRectF(x - 2, r.top() - 1, 4, r.height() + 2), hl)

    def _ruler_ticks(self, span):
        lo, hi = span
        step = ruler_step(hi - lo)
        t = np.ceil(lo / step) * step
        while t <= hi + 1e-9:
            yield t, self._x(t, span)
            t += step

    def _paint_ruler(self, p: QPainter, span) -> None:
        """The time ruler at the top of the part in view (the rows under it scroll, it does not)."""
        pal, top = self.palette(), self._ruler_top()
        p.fillRect(0, top, self.width(), self.RULER_H, pal.color(QPalette.Base))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        for t, x in self._ruler_ticks(span):
            p.setPen(pal.color(QPalette.Mid))
            p.drawLine(int(x), top + self.RULER_H - 6, int(x), top + self.RULER_H)
            p.setPen(pal.color(QPalette.Text))
            p.drawText(int(x) + 3, top + self.RULER_H - 8, f"{t:g}s")

    def _paint_layer(self, p: QPainter, span, rows: list | None = None) -> None:
        rows = rows if rows is not None else self._rows()
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.Base))
        text, grid = pal.color(QPalette.Text), pal.color(QPalette.Mid)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        p.setPen(grid)
        for _t, x in self._ruler_ticks(span):  # the grid; the ruler's numbers are drawn over it in view
            p.drawLine(int(x), self.RULER_H - 6, int(x), self.height())
        sc, sel = self.win.scene, self.win.selected
        for it, y, h, tracks, labels in rows:
            if it is sel:
                p.fillRect(0, y, self.width(), h, pal.color(QPalette.Highlight).darker(250))
            broken = labels is not None and bool(labels.error)  # its label file could not be used: say so
            p.setPen(QColor(230, 150, 60) if broken else text)
            p.drawText(QRectF(6, y, self.NAME_W - 10, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                       f"⚠ {it.label}" if broken else f"{it.label} *" if getattr(labels, "edited", False) else it.label)
            dur = sc.shown(it).robot.duration
            c = QColor(*it.color)
            c.setAlpha(200 if it.visible else 70)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            x0, x1 = self._x(it.offset, span), self._x(it.offset + dur, span)
            p.drawRoundedRect(QRectF(x0, y + 4, max(2.0, x1 - x0), self.ROW_H - 8), 3, 3)
            if tracks:
                self._paint_labels(p, it, labels, y, tracks, small, span)
            if sc.view.show_problems:  # problem spans as thin strips along the bottom of the bar (retlens.problems)
                p.setPen(Qt.NoPen)
                for kind, sp in sc.problems(it).items():
                    if kind in problems.KINDS:
                        c = QColor(*problems.KINDS[kind][1])
                        c.setAlpha(235 if it.visible else 90)
                        p.setBrush(c)
                        for a, b in sp:
                            xa, xb = self._x(it.offset + a, span), self._x(it.offset + min(b, dur), span)
                            p.drawRect(QRectF(xa, y + self.ROW_H - 7, max(2.0, xb - xa), 3))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(230, 40, 40))
            for ft, _cause in sc.falls(it):
                x = self._x(it.offset + ft, span)
                p.drawPolygon([QPointF(x - 4, y + 2), QPointF(x + 4, y + 2), QPointF(x, y + 9)])

    def _paint_labels(self, p: QPainter, it: Item, labels, y: int, tracks: list[str], font: QFont, span) -> None:
        """The motion's segments, one lane per track: label colors, the label written in when it fits
        (the segment being played is outlined over this by paintEvent)."""
        pal = self.palette()
        if len(tracks) > 1 or tracks[0]:  # track names under the motion's name
            p.setPen(pal.color(QPalette.PlaceholderText))
            for k, tr in enumerate(tracks):
                p.drawText(QRectF(16, y + self.ROW_H - 1 + k * self.LANE_H, self.NAME_W - 20, self.LANE_H - 3),
                           Qt.AlignVCenter | Qt.AlignLeft, tr or "-")
        fm = QFontMetrics(font)
        gap = QPen(pal.color(QPalette.Base), 1)  # a thin gap between neighbouring segments
        for s, r in self._segments(it, labels, y, tracks, span):
            c = QColor(*motion_labels.color_for(s))
            c.setAlpha(230 if it.visible else 80)
            p.setPen(gap)
            p.setBrush(c)
            p.drawRect(r)
            if r.width() > 18:
                light = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140
                p.setPen(QColor(25, 25, 25) if light else QColor(245, 245, 245))
                p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft,
                           fm.elidedText(s.label, Qt.ElideRight, int(r.width()) - 6))

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton and self._edge is not None:  # cancels dragging an edge
            self._edge, self._no_menu = None, time.monotonic()
            self.update()
            return
        if e.button() != Qt.LeftButton:  # the right button opens the menu (contextMenuEvent)
            return
        if e.position().x() < self.NAME_W:  # click a name: select that motion
            row = self._row_at(e.position().y())
            if row is not None:
                self.win.select(row[0])
            return
        which = self.edge_at(e.position())
        if which is not None:  # on the picked segment's edge: drag it (a click without moving still seeks)
            it, lab, seg = self._selection()
            self._edge = {"item": it, "labels": lab, "seg": seg, "which": which, "x": e.position().x(), "moved": False}
            self.win.scene.set_playing(False)
            return
        self._pick(e.position())
        self._drag = True
        self.win.scene.set_playing(False)
        self.win.scene.seek(self._t(e.position().x()))

    def _pick(self, pos) -> None:
        pick = getattr(self.win, "set_label_selection", None)
        if pick is not None:
            hit = self.hit_at(pos)
            pick(hit[0] if hit is not None else None, hit[2] if hit is not None else None)

    def _drag_edge(self, e) -> None:
        """The edge follows the mouse on frames, stopping at the neighbours (a neighbour sharing the edge moves
        with it; Alt: not) and snapping to the playhead within 5 px."""
        ed, x = self._edge, e.position().x()
        if not ed["moved"] and abs(x - ed["x"]) < 3:
            return
        ed["moved"] = True
        it, seg, sc = ed["item"], ed["seg"], self.win.scene
        t = (sc.t if abs(self._x(sc.t) - x) <= 5 else self._t(x)) - it.offset
        start, end = (t, seg.end) if ed["which"] == "start" else (seg.start, t)
        new, s = motion_labels.with_bounds(ed["labels"], seg, start, end, it.robot.fps, it.robot.duration,
                                           together=not e.modifiers() & Qt.AltModifier)
        ed["new"], ed["preview"] = new, s
        v = s.start if ed["which"] == "start" else s.end
        QToolTip.showText(e.globalPosition().toPoint(), f"{'시작' if ed['which'] == 'start' else '끝'} {v:.3f} s · 프레임 "
                          f"{int(round(v * it.robot.fps))} · 길이 {s.duration:.2f} s", self)
        self.update()

    def mouseDoubleClickEvent(self, e):
        hit = self.segment_at(e.position())
        if hit is not None:  # to the segment's start
            self.win.scene.set_playing(False)
            self.win.scene.seek(hit[0].offset + hit[1].start)

    def mouseMoveEvent(self, e):
        if self._edge is not None:
            self._drag_edge(e)
        elif self._drag:
            self.win.scene.seek(self._t(e.position().x()))
        else:
            edge = self.edge_at(e.position()) is not None
            if edge != (self.cursor().shape() == Qt.SizeHorCursor):
                self.setCursor(Qt.SizeHorCursor) if edge else self.unsetCursor()
            self.setToolTip(self._fall_at(e.position()) or self._label_tip(e.position()))

    def mouseReleaseEvent(self, e):
        self._drag = False
        ed, self._edge = self._edge, None
        if ed is None:
            return
        if not ed["moved"]:  # a click on the edge: seek there, like a click anywhere
            self.win.scene.seek(self._t(e.position().x()))
        elif ed.get("new") is not None and ed["new"] is not ed["labels"]:
            self.win.edit_labels(ed["item"], ed["labels"], (ed["new"], ed["preview"]),
                                 "구간 시작 옮기기" if ed["which"] == "start" else "구간 끝 옮기기", before=ed["seg"])
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._edge is not None:
            self._edge = None
            self.update()
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        if time.monotonic() - self._no_menu < 1.0:
            self._no_menu = 0.0
            return
        row = self._row_at(e.pos().y())
        m = QMenu(self)
        if row is not None:
            it, win = row[0], self.win
            hit = self.hit_at(e.pos()) if e.pos().x() >= self.NAME_W else None
            lane = self.lane_at(e.pos())
            if hit is not None and hasattr(win, "label_menu"):  # a segment: its edits first
                win.set_label_selection(hit[0], hit[2])
                win.label_menu(m, hit[0], hit[2])
                m.addSeparator()
            else:
                win.select(it)
                if lane is not None and e.pos().x() >= self.NAME_W and hasattr(win, "label_add"):  # a gap in a lane
                    t = self._t(e.pos().x()) - it.offset
                    m.addAction(f"여기에 구간 추가... ({lane[1] or '라벨'} {t:.2f} s)", lambda: win.label_add(it, lane[1], t))
                    m.addSeparator()
            win.motion_menu(m, it)
        elif getattr(self.win, "a_show_problems", None) is not None:  # the ruler or below the rows
            m.addAction(self.win.a_show_problems)
        if not m.isEmpty():
            m.exec(e.globalPos())

    def _label_tip(self, pos) -> str:
        hit = self.segment_at(pos)
        if hit is not None:
            return segment_text(*hit)
        row = self._row_at(pos.y())
        labels = row[4] if row is not None else None
        if pos.x() < self.NAME_W and labels is not None and labels.error:
            return f"라벨 파일을 쓰지 못함: {labels.error}"
        return ""

    def _fall_at(self, pos) -> str:
        row = self._row_at(pos.y())
        if row is None or pos.y() > row[1] + self.ROW_H:  # falls are marked on the motion's bar
            return ""
        it, sc = row[0], self.win.scene
        for ft, cause in sc.falls(it):
            if abs(self._x(it.offset + ft) - pos.x()) < 6:  # its first cause with the numbers (MuJoCo: and the rule)
                tip = getattr(sc, "fall_tip_at", None)
                return f"{it.label}: " + (tip(it, ft) if tip is not None else f"넘어짐 {ft:.2f}s · {cause}")
        if sc.view.show_problems:  # the problem strips under the mouse
            lo, hi = self._span()
            px = (hi - lo) / max(1, self.width() - self.NAME_W - 10)
            t = self._t(pos.x()) - it.offset
            here = [f"{PROBLEM_NAMES[k]} {a:.2f}–{b:.2f}s" for k, sp in sc.problems(it).items() if k in problems.KINDS
                    for a, b in sp if a - 2 * px <= t <= b + 2 * px]
            if here:
                return f"{it.label}: " + ", ".join(here) + "  (N / Shift+N: 다음 / 이전 문제)"
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

        def tool(tip, fn, icon=None, text=""):
            b = QToolButton()
            if icon is not None:
                b.setIcon(st.standardIcon(icon))
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        tool("처음으로 (Home)", lambda: sc.seek(0.0), QStyle.SP_MediaSkipBackward)
        tool("이전 프레임 (←)", lambda: sc.step(-1), QStyle.SP_MediaSeekBackward)
        self.play = tool("재생 / 일시정지 (Space)", sc.toggle_play, QStyle.SP_MediaPlay)
        tool("다음 프레임 (→)", lambda: sc.step(1), QStyle.SP_MediaSeekForward)
        bar.addSpacing(6)
        # problem spans (retlens.problems): the window's goto_problem, looked up when clicked
        tool("이전 문제로 (Shift+N)", lambda: self.win.goto_problem(-1), text="◀ 문제")
        tool("다음 문제로 (N): 발 미끄러짐·바닥 관통·스윙 발 바닥 근접·자기 충돌·관절 한계·마커 공백·넘어짐",
             lambda: self.win.goto_problem(1), text="문제 ▶")
        bar.addSpacing(6)
        self.time = QLabel()
        self.time.setMinimumWidth(110)
        bar.addWidget(self.time)
        self.now = QLabel()  # the selected motion's label(s) at the playhead
        self.now.setToolTip("고른 모션의 지금 구간 라벨")
        self.now.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bar.addWidget(self.now, 1)
        self.speed = QComboBox()  # follows the scene (the API sets it too)
        self.speed.setToolTip("재생 속도")
        for v in SPEEDS:
            self.speed.addItem(f"{v:g}x", v)
        self.speed.activated.connect(lambda i: setattr(sc.view, "speed", float(self.speed.itemData(i))))
        bar.addWidget(self.speed)
        self.loop = QCheckBox("반복")
        self.loop.setChecked(sc.view.loop)
        self.loop.toggled.connect(lambda on: setattr(sc.view, "loop", on))
        bar.addWidget(self.loop)
        lay.addLayout(bar)
        # 유형별 재생: the segments of one label, one after another (MotionScene.play_segments); shown while
        # an open motion has labels
        self.seg_row = QWidget()
        seg = QHBoxLayout(self.seg_row)
        seg.setContentsMargins(0, 0, 0, 0)
        seg.addWidget(QLabel("라벨 구간"))
        self.seg_box = QComboBox()
        self.seg_box.setMinimumWidth(160)
        self.seg_box.setToolTip("열린 모션들의 라벨(라벨 파일·자동 라벨)을 '트랙: 라벨'별로 모은 목록. 고르면 그 구간들만 "
                                "차례로 봅니다")
        self.seg_box.activated.connect(lambda _i: self._seg_restart())
        seg.addWidget(self.seg_box, 1)
        self.seg_prev = QToolButton()
        self.seg_prev.setText("◀")
        self.seg_prev.setToolTip("이전 라벨 구간")
        self.seg_prev.clicked.connect(lambda: self._seg_step(-1))
        self.seg_next = QToolButton()
        self.seg_next.setText("▶")
        self.seg_next.setToolTip("다음 라벨 구간")
        self.seg_next.clicked.connect(lambda: self._seg_step(1))
        self.seg_play = QPushButton("이어 재생")
        self.seg_play.setCheckable(True)
        self.seg_play.setToolTip("고른 라벨의 구간을 처음부터 끝까지 차례로 재생합니다(반복이 켜져 있으면 다시 처음으로)")
        self.seg_play.toggled.connect(self._seg_toggle)
        self.seg_solo = QCheckBox("그 모션만")
        self.seg_solo.setToolTip("구간을 보는 동안 그 구간의 모션만 보이게 합니다(끝나면 원래대로)")
        self.seg_solo.toggled.connect(lambda _on: self._seg_restart(keep=True))
        self.seg_info = QLabel()
        self.seg_info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for w in (self.seg_prev, self.seg_next, self.seg_play, self.seg_solo):
            seg.addWidget(w)
        seg.addWidget(self.seg_info, 1)
        self.seg_row.setVisible(False)
        lay.addWidget(self.seg_row)
        self._cat_key = None  # what the label list was built from
        self._speed = None  # the speed the box shows
        self.tracks = TimelineTracks(win)
        # label lanes make the rows taller: they scroll, instead of the timeline pushing the 3D view smaller
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.tracks)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(TimelineTracks.RULER_H + 2 * TimelineTracks.ROW_H + 4)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self.tracks.update())  # the ruler stays on top
        lay.addWidget(self.scroll, 1)
        self._view = None  # tracks.view_key() last drawn
        self._playing = None  # the play button's icon shows this

    def refresh(self) -> None:
        """Called every GUI tick (EditorWindow._tick): widgets are touched only when what they show changed."""
        sc = self.win.scene
        lo, hi = sc.time_range()
        text = f"{sc.t:6.2f} / {hi:.2f} s"
        it = self.win.selected
        if self.time.text() != text:
            self.time.setText(text)
        tip = (f"{it.label}: 프레임 {int(round((sc.t - it.offset) * it.robot.fps))}" if it is not None
               else "모션을 고르면 그 모션의 프레임이 나옵니다")
        if self.time.toolTip() != tip:  # the selected motion's own frame (its offset and fps)
            self.time.setToolTip(tip)
        if self._speed != sc.view.speed:  # the API may set a speed the list does not have
            self._speed = sc.view.speed
            i = self.speed.findData(sc.view.speed)
            if i < 0:
                self.speed.addItem(f"{sc.view.speed:g}x", sc.view.speed)
                i = self.speed.count() - 1
            self.speed.setCurrentIndex(i)
        if self.loop.isChecked() != sc.view.loop:
            self.loop.blockSignals(True)
            self.loop.setChecked(sc.view.loop)
            self.loop.blockSignals(False)
        now = ""
        labels = it.labels if it is not None else None  # read once: other threads replace it
        if labels is not None and labels.segments:
            local = sc.t - it.offset
            now = ("(범위 밖)" if not 0.0 <= local <= sc.shown(it).robot.duration else
                   labels.text_at(local) or "(라벨 없는 구간)")
        if self.now.text() != now:
            self.now.setText(now)
        if self._playing != sc.playing:  # setIcon repaints the button and lays out the bar again
            self._playing = sc.playing
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause if sc.playing else QStyle.SP_MediaPlay))
        view = self.tracks.view_key()
        if view != self._view:  # refreshed every frame: repainted only when something moved or changed
            self._view = view
            self.tracks.update()
        self._seg_refresh()

    # ---------------------------------------------------------------- 유형별 재생
    def _seg_key(self) -> str | None:
        return self.seg_box.currentData()

    def _seg_refresh(self) -> None:
        sc = self.win.scene
        key = tuple((_Same(it), _Same(it.labels)) for it in list(sc.items))  # objects: labels are replaced, not changed
        if key != self._cat_key:  # the motions or their labels changed: the list again (not every frame)
            self._cat_key = key
            cur = self._seg_key()
            self.seg_box.blockSignals(True)
            self.seg_box.clear()
            for c in sc.label_catalog():
                self.seg_box.addItem(f"{c['key']} · {c['segments']}개", c["key"])
                self.seg_box.setItemData(self.seg_box.count() - 1, f"구간 {c['segments']}개 · {c['seconds']:.0f}초 · "
                                         f"모션 {len(c['motions'])}개", Qt.ToolTipRole)
            i = self.seg_box.findData(cur)
            self.seg_box.setCurrentIndex(max(i, 0))
            self.seg_box.blockSignals(False)
            self.seg_row.setVisible(self.seg_box.count() > 0)
        on = self._seg_key() is not None
        for w in (self.seg_prev, self.seg_next, self.seg_play, self.seg_solo):
            if w.isEnabled() != on:
                w.setEnabled(on)
        st = sc.playlist_state()
        if self.seg_play.isChecked() != (st is not None):
            self.seg_play.blockSignals(True)
            self.seg_play.setChecked(st is not None)
            self.seg_play.blockSignals(False)
        text = "" if st is None else f"{st['index'] + 1}/{st['count']} · {st['id']} {st['start_s']:.2f}–{st['end_s']:.2f}s"
        if self.seg_info.text() != text:
            self.seg_info.setText(text)

    def _seg_toggle(self, on: bool) -> None:
        sc = self.win.scene
        if not on:
            sc.stop_segments()
            sc.set_playing(False)
            return
        key = self._seg_key()
        if key is None or not sc.play_segments(key, solo=self.seg_solo.isChecked()):
            self.seg_play.setChecked(False)

    def _seg_step(self, direction: int) -> None:
        sc = self.win.scene
        if sc.playlist is None or sc.playlist["key"] != self._seg_key():
            key = self._seg_key()
            if key is None or not sc.play_segments(key, solo=self.seg_solo.isChecked(), play=False):
                return
            if direction < 0:
                sc.step_segment(-1)  # from the first one back round to the last
            return
        sc.step_segment(direction)

    def _seg_restart(self, keep: bool = False) -> None:
        """Another label (or solo turned on / off) while segments play: play that one from its first segment
        (keep: the same position)."""
        sc = self.win.scene
        st = sc.playlist_state()
        if st is None:
            return
        playing, index = sc.playing, st["index"]
        if sc.play_segments(self._seg_key(), solo=self.seg_solo.isChecked(), play=playing) and keep:
            sc.step_segment(index)

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
        self.search.setPlaceholderText("이름·동작 검색 (예: 143_11, walk)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_files)
        top.addWidget(self.search, 1)
        add = QPushButton("추가")
        add.setToolTip("선택한 파일을 씬에 추가 (두 번 클릭이나 끌어다 놓기도 됨). 다른 폴더의 파일은 파일 > 열기 (Ctrl+O)")
        add.clicked.connect(self._add_selected)
        top.addWidget(add)
        again = QToolButton()
        again.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        again.setToolTip("폴더 다시 읽기 (모션 폴더는 환경 설정에서 정합니다)")
        again.setAutoRaise(True)
        again.clicked.connect(self.reload)
        top.addWidget(again)
        lay.addLayout(top)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["폴더", "파일"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self._fill_files)
        self.tree.currentItemChanged.connect(lambda cur, _prev: cur is not None and self.win.settings.setValue(
            layout_key("project/folder"), cur.data(0, Qt.UserRole)))
        split.addWidget(self.tree)
        self.files = QTableWidget(0, 3)
        self.files.setHorizontalHeaderLabels(["이름", "설명", "폴더"])
        self.files.horizontalHeaderItem(1).setToolTip("CMU 동작 설명 (CMU 모션이 아니면 숨김)")
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
        last = self.win.settings.value(layout_key("project/folder"), "")  # where the user was last time
        start = nodes.get(last) or nodes.get("data/raw/cmu_bvh") or next(iter(nodes.values()), None)
        if start is not None:
            self.tree.blockSignals(True)  # keep the remembered folder: this is not the user's pick
            self.tree.setCurrentItem(start)
            self.tree.blockSignals(False)
        self._fill_files()

    def _paths_in(self, key: str) -> list[str]:
        return [p for folder, ps in self._library.items() if folder == key or folder.startswith(key + "/") for p in ps]

    def _fill_files(self) -> None:
        q = self.search.text().strip().lower()
        cap = 500 if q else 2000
        if q:
            all_paths = [p for ps in self._library.values() for p in ps]
            hits = [p for p in all_paths if q in os.path.basename(p).lower() or q in cmu_labels.label_for(p).lower()]
            hits.sort(key=lambda p: not os.path.basename(p).lower().startswith(q))
            found = hits
        else:
            cur = self.tree.currentItem()
            found = self._paths_in(cur.data(0, Qt.UserRole)) if cur else []
        paths = found[:cap]
        self.search.setToolTip(f"{len(found)}개 중 {cap}개만 보입니다. 더 좁혀 검색하세요" if len(found) > cap else "")
        self.files.setRowCount(len(paths))
        descs, folders = [], set()
        for r, p in enumerate(paths):
            name = QTableWidgetItem(os.path.basename(p))
            name.setData(Qt.UserRole, p)
            name.setToolTip(rel(p))
            self.files.setItem(r, 0, name)
            descs.append(cmu_labels.label_for(p))
            self.files.setItem(r, 1, QTableWidgetItem(descs[-1]))
            folder = rel(os.path.dirname(p)).replace(os.sep, "/")
            folders.add(folder)
            self.files.setItem(r, 2, QTableWidgetItem(folder))
        self.files.setColumnHidden(1, not any(descs))  # only CMU motions have descriptions
        head = self.files.horizontalHeader()  # the widest visible column takes the room
        head.setSectionResizeMode(0, QHeaderView.Interactive if any(descs) else QHeaderView.Stretch)
        self.files.setColumnHidden(2, len(folders) <= 1)  # all from the folder picked on the left
        self.files.resizeColumnToContents(0)

    def _add_row(self, r: int) -> None:
        it = self.files.item(r, 0)
        if it is not None:
            self.win.add_paths([it.data(Qt.UserRole)])

    def _add_selected(self) -> None:
        rows = sorted({i.row() for i in self.files.selectedIndexes()})
        self.win.add_paths([self.files.item(r, 0).data(Qt.UserRole) for r in rows])


# ------------------------------------------------------------------------------ analysis
FOLLOW_SPANS = (("따라가기 끔", 0.0), ("5초 따라가기", 5.0), ("10초 따라가기", 10.0), ("30초 따라가기", 30.0),
                ("전체 보기", -1.0))  # 분석 graph: seconds shown around the playhead


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
        self.align_btn = QPushButton("기준에 시간 자동 정렬")
        self.align_btn.setToolTip("다른 모션들의 시간 오프셋을 다리 관절각 차이가 가장 작아지게 맞춥니다")
        self.align_btn.clicked.connect(self._align)
        bar.addWidget(self.align_btn)
        bar.addWidget(QLabel("그래프"))
        self.key = QComboBox()
        self.key.currentIndexChanged.connect(lambda _: self.rebuild_chart())
        bar.addWidget(self.key, 1)
        self.follow = QComboBox()  # how much of the timeline the graph shows around the playhead (0: off)
        for text, span in FOLLOW_SPANS:
            self.follow.addItem(text, span)
        self.follow.setCurrentIndex(self.follow.findData(10.0))
        self.follow.setToolTip("그래프가 재생 위치를 가운데에 두고 따라가며 보일 길이. 그래프를 끌거나 휠로 확대·축소하면 "
                               "'따라가기 끔'이 되고, 두 번 클릭하면 다시 따라갑니다")
        self.follow.currentIndexChanged.connect(lambda _: self.update_view(force=True))
        self._follow_last = 10.0  # what double-clicking the graph goes back to
        bar.addWidget(self.follow)
        bar.addWidget(help_button("지표 설명", metric_help_html()))
        lay.addLayout(bar)
        split = QSplitter()
        self.plot = LinePlot()
        self.plot.panned.connect(self._stop_following)
        self.plot.follow_requested.connect(lambda: self.follow.setCurrentIndex(self.follow.findData(self._follow_last)))
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

    def _stop_following(self) -> None:
        span = self.follow.currentData()
        if span != 0.0:
            self._follow_last = span
            self.follow.setCurrentIndex(self.follow.findData(0.0))

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
        self.align_btn.setEnabled(len(sc.items) > 1)
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
        stems = [it.label.split("/")[-1] for it, _v in cols]  # '02_01'; the folder too when two share a name
        for c, (it, vals) in enumerate(cols):
            head = QTableWidgetItem(f"■ {short_text(stems[c] if stems.count(stems[c]) == 1 else it.label, 16)}")
            head.setForeground(QBrush(QColor(*it.color)))
            head.setToolTip(f"{it.label} ({it.kind})")
            self.table.setHorizontalHeaderItem(c, head)
            for r, v in enumerate(vals):
                cell = QTableWidgetItem(short_text(str(v)))
                cell.setToolTip(str(v))  # full text, also when the column is too narrow and Qt elides it
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, cell)
        for r, n in enumerate(names):  # rows that say nothing here: no motion has the value, all kinematic, no reference
            vals = {str(v[r]) for _it, v in cols}
            self.table.setRowHidden(r, vals <= {"-", ""} or (n == "재생 방식" and vals == {"기구학"})
                                    or ("RMSE" in n and len(cols) < 2))
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
        span = self.follow.currentData()
        if span:  # following: the span around the playhead (-1: the whole timeline)
            lo, hi = (sc.t - span / 2, sc.t + span / 2) if span > 0 else sc.time_range()
        else:  # where the user dragged / zoomed to
            lo, hi = self.plot.x0, self.plot.x1
        self.plot.set_view(lo, hi, sc.t)


# ------------------------------------------------------------------------------ overlay comparison
REGION_COLORS = {"전체 (부위 평균)": QColor(235, 235, 240), "몸통·머리": QColor(160, 160, 175), "왼팔": QColor(90, 170, 255),
                 "오른팔": QColor(255, 120, 90), "왼다리": QColor(80, 205, 140), "오른다리": QColor(235, 195, 60)}
COMPARE_HELP = [
    ("맞춤", "대상(B)의 골반을 기준(A)의 골반 위치로 옮깁니다. '방향도 맞춤'을 켜면 골반이 향한 방향(수직축 회전)도 "
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
        self.toggle = QPushButton("겹쳐 비교")
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet("QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }")
        self.toggle.setToolTip("켜면 대상(B)을 기준(A)의 골반 위치에 겹쳐 그립니다 (O). 모션이 둘 이상 있어야 합니다")
        self.toggle.toggled.connect(self._toggled)
        bar.addWidget(self.toggle)
        bar.addWidget(QLabel("기준 A"))
        self.ref = QComboBox()
        self.ref.setToolTip("회색 반투명으로 그릴 모션")
        bar.addWidget(self.ref, 1)
        self.swap = QToolButton()
        self.swap.setText("⇄")
        self.swap.setToolTip("A와 B 바꾸기")
        self.swap.clicked.connect(self._swap)
        bar.addWidget(self.swap)
        bar.addWidget(QLabel("대상 B"))
        self.item = QComboBox()
        self.item.setToolTip("A의 골반 위치로 옮겨, 벗어난 부위만 색칠해 그릴 모션")
        bar.addWidget(self.item, 1)
        for combo in (self.ref, self.item):
            combo.currentIndexChanged.connect(lambda _: self._pair_changed())
        self.heading = QCheckBox("방향도 맞춤")
        self.heading.setToolTip("B의 골반을 A의 골반 위치로 옮기면서, 골반이 향한 방향(수직축 회전)도 A에 맞춥니다. "
                                "끄면 위치만 맞춥니다")
        self.heading.toggled.connect(lambda on: self._filling or self.win.scene.set_compare(heading=on))
        bar.addWidget(self.heading)
        bar.addWidget(QLabel("허용 오차"))
        self.tol = pass_shortcuts(QDoubleSpinBox())
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
        self.table.setHorizontalHeaderLabels(["부위", "평균 (cm)", "최대 (cm)", "최대 시각 (s)", "넘음 (%)"])
        self.table.horizontalHeaderItem(4).setToolTip("허용 오차를 넘은 시간 비율")
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
        self.heading.setChecked(c.heading)
        if abs(self.tol.value() - c.tol_cm) > 1e-9:
            self.tol.setValue(c.tol_cm)
        self._filling = False
        two = len(sc.items) > 1  # a pair to compare
        for w in (self.toggle, self.ref, self.swap, self.item):
            w.setEnabled(two)
        self.legend.set_tol(c.tol_cm)
        self.legend.setVisible(sc.compare_pair() is not None)
        self.rebuild()

    def rebuild(self) -> None:
        sc = self.win.scene
        s = sc.compare_series() if sc.compare_pair() is not None else None
        self.table.setRowCount(0)
        if s is None or not len(s["t"]):
            self.plot.set_data([], "" if s is None else "두 모션이 함께 재생되는 구간이 없습니다 (시간 오프셋 확인)")
            self.plot.set_view(*sc.time_range(), sc.t)
            return
        t, tol = s["t"], sc.compare.tol_cm
        series = [("전체 (부위 평균)", REGION_COLORS["전체 (부위 평균)"], t, s["mean"])]
        series += [(r, REGION_COLORS.get(r, QColor(200, 200, 200)), t, v) for r, v in s["regions"].items()]
        series.append((f"허용 오차 {tol:g} cm", QColor(130, 130, 140), t, np.full(len(t), tol)))
        self.plot.set_data(series, "B − A 부위 차이 (cm)")
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
            text = ("꺼짐: '겹쳐 비교'(O)로 켭니다. A·B는 위에서 고르거나 계층 패널 우클릭으로 정합니다."
                    if len(sc.items) > 1 else "겹쳐 비교에는 모션이 둘 이상 있어야 합니다.")
        elif now is None:
            text = "지금 시각에는 A나 B가 보이지 않습니다(숨김)."
        else:
            worst = now["worst"]
            text = (f"지금 평균 {now['mean']:.1f} cm · 허용 오차 넘은 부품 {now['over']}/{now['parts']}"
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


def help_button(text: str, html: str, icon_only: bool = False) -> QToolButton:
    """A '?' button that shows `html` on hover, and on click (no hover delay, stays longer); icon_only: just the
    '?', its text as the tip's heading."""
    b = QToolButton()
    b.setText(text)
    b.setIcon(b.style().standardIcon(QStyle.SP_MessageBoxQuestion))
    b.setToolButtonStyle(Qt.ToolButtonIconOnly if icon_only else Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    if icon_only:
        html = f"<b>{escape(text)}</b><br>{html}"
    b.setToolTip(html)
    b.clicked.connect(lambda: QToolTip.showText(b.mapToGlobal(QPoint(0, b.height())), html, b, QRect(), 60000))
    return b


# ------------------------------------------------------------------------------ dataset (일괄 처리)
LABEL_SOURCES = {"file": "파일", "auto": "자동"}  # where a row's labels came from (retlens.batch)
# the 데이터셋 table's columns (retlens.batch.COLUMNS): shown at first, shown once a row has a value, the rest from
# the header's right-click menu (the user's picks are kept)
BATCH_SHOWN = ("name", "folder", "duration_s", "retarget_score", "qc", "main_loss", "problems_s", "worst_problem")
BATCH_WHEN_FILLED = ("objects", "hand_obj_reach_pct", "labels", "label_segments", "phys_falls", "phys_first_cause",
                     "phys_harness_pct", "phys_ok", "error")


class BatchModel(QAbstractTableModel):
    """The rows of a 일괄 처리 run (retlens.batch), one per motion file; sorted by value (Qt.UserRole)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(batch.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return batch.COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[index.row()]
        key, _title, fmt = batch.COLUMNS[index.column()]
        if role == Qt.DisplayRole:
            return LABEL_SOURCES.get(r.get(key), r.get(key)) if key == "labels" else batch.cell(r, key, fmt)
        if role == Qt.UserRole:  # sorting: numbers as numbers, blanks last
            v = r.get(key)
            return (1, 0.0, "") if v is None or v == "" else (0, float(v), "") if isinstance(v, (int, float)) else (0, 0.0, str(v))
        if role == Qt.ToolTipRole:
            return "\n".join(x for x in (r.get("file"), r.get("error"), r.get("qc_notes"), r.get("phys_ok"),
                                         r.get("phys_error"),
                                         f"넘어짐 원인: {r['phys_fall_causes']}" if r.get("phys_fall_causes") else "") if x)
        if role == Qt.ForegroundRole:
            if r.get("error"):
                return QBrush(QC_COLORS["FAIL"])
            if key == "qc" and r.get("qc") in QC_COLORS:
                return QBrush(QC_COLORS[r["qc"]])
        if role == Qt.TextAlignmentRole and fmt != "{}":
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def add(self, row: dict) -> None:
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.rows = []
        self.endResetModel()


class BatchFilter(QSortFilterProxyModel):
    """The table's filter: words to find in the motion's name, folder, QC, worst problem, cost or error, and a
    QC / error choice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text, self.qc = "", ""
        self.setSortRole(Qt.UserRole)

    def set(self, text: str | None = None, qc: str | None = None) -> None:
        self.text = self.text if text is None else text.strip().lower()
        self.qc = self.qc if qc is None else qc
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        r = self.sourceModel().rows[source_row]
        if self.qc == "error" and not r.get("error") or self.qc in ("FAIL", "WARN", "PASS") and r.get("qc") != self.qc:
            return False
        if self.qc == "falls" and not r.get("phys_falls"):
            return False
        if self.text:
            hay = " ".join(str(r.get(k) or "") for k in ("name", "folder", "qc", "worst_problem", "main_loss", "error",
                                                         "labels", "kind", "phys_first_cause")).lower() + " " + \
                LABEL_SOURCES.get(r.get("labels"), "")
            return all(w in hay for w in self.text.split())
        return True

    def lessThan(self, a, b):
        return self.sourceModel().data(a, Qt.UserRole) < self.sourceModel().data(b, Qt.UserRole)


class DatasetPanel(QWidget):
    """데이터셋 일괄 처리: folders of motions retargeted (with the 리타게팅 menu's corrections) and measured in the
    background, a row each in a table to sort and filter, the worst first if wanted; a double click opens a
    motion. Rows are cached (retlens.batch): a stopped run, or the same folders again, pick up where they were.
    The filter row and the progress show once there is something to filter or to wait for."""

    def __init__(self, win: "EditorWindow"):
        super().__init__()
        self.win = win
        self.folders: list[str] = []
        self._stop = False
        self._running = False
        self._filled: set[str] = set()  # columns some row has a value in
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        add = QPushButton("폴더 추가...")
        add.setToolTip("촬영 세션 폴더를 고릅니다. 그 아래의 모션 파일을 모두 처리합니다(여러 폴더를 더할 수 있음)")
        add.clicked.connect(self._add_folder)
        top.addWidget(add)
        self.where = QLabel()
        self.where.setStyleSheet("color: gray")
        self.where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.where, 1)
        self.physics = QCheckBox("물리 (MuJoCo 보조 힘)")
        self.physics.setToolTip("모션마다 MuJoCo 골반 보조 힘 검사도 돌립니다(클립당 1–3초 더)")
        top.addWidget(self.physics)
        self.auto = QCheckBox("자동 라벨")
        self.auto.setToolTip("라벨 파일이 없는 모션은 규칙 파일대로 자동 라벨을 붙여 셉니다(규칙 파일: ⋯ 메뉴나 인스펙터)")
        top.addWidget(self.auto)
        self.start = QPushButton("시작")
        self.start.setToolTip("폴더의 모션을 리타게팅 메뉴의 보정으로 리타게팅하고 잽니다. 처음 리타게팅하는 모션은 하나에 "
                              "수십 초, 계산해 둔 것은 바로 나옵니다")
        self.start.clicked.connect(self.run)
        top.addWidget(self.start)
        self.export_btn = QPushButton("내보내기...")
        self.export_btn.setToolTip("기준을 넘는 모션을 한 폴더에 로봇 모션·라벨·manifest로 모읍니다(문제 구간을 잘라 낼 수 있음)")
        self.export_btn.clicked.connect(self.export)
        top.addWidget(self.export_btn)
        self.stop = QPushButton("멈춤")  # in 시작's place while it runs
        self.stop.setToolTip("지금 모션이 끝나면 멈춥니다. 다시 시작하면 남은 것부터 합니다")
        self.stop.setVisible(False)
        self.stop.clicked.connect(self._request_stop)
        top.addWidget(self.stop)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setMaximumWidth(200)
        self.progress.setVisible(False)
        top.addWidget(self.progress)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("자동 라벨 규칙 파일, CSV로 저장, 비우기")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        menu = QMenu(more)
        menu.addAction("자동 라벨 규칙 파일...", lambda: self.win.pick_label_rules())
        menu.addSeparator()
        self.a_csv = menu.addAction("CSV로 저장...", self._save_csv)
        self.a_clear = menu.addAction("비우기", self._clear)
        self.a_clear.setToolTip("폴더 목록과 표를 비웁니다(계산해 둔 결과는 남아, 다시 돌리면 바로 나옵니다)")
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(lambda: (self.a_csv.setEnabled(bool(self.model.rows)),
                                          self.a_clear.setEnabled(not self._running and bool(self.folders or self.model.rows))))
        more.setMenu(menu)
        top.addWidget(more)
        lay.addLayout(top)
        self.filter_row = QWidget()  # once there are rows
        mid = QHBoxLayout(self.filter_row)
        mid.setContentsMargins(0, 0, 0, 0)
        self.find = QLineEdit()
        self.find.setPlaceholderText("거르기: 이름·폴더·QC·문제·감점·오류 (띄어 쓰면 모두)")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(lambda t: self.proxy.set(text=t))
        mid.addWidget(self.find, 1)
        self.qc = QComboBox()
        for text, key in (("전체", ""), ("QC FAIL", "FAIL"), ("QC WARN", "WARN"), ("QC PASS", "PASS"),
                          ("물리 넘어짐", "falls"), ("오류", "error")):
            self.qc.addItem(text, key)
        self.qc.currentIndexChanged.connect(lambda _i: self.proxy.set(qc=self.qc.currentData()))
        mid.addWidget(self.qc)
        self.filter_row.setVisible(False)
        lay.addWidget(self.filter_row)
        self.model = BatchModel(self)
        self.proxy = BatchFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)  # the files' order until a header is clicked (Qt starts descending)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(self._columns_menu)
        self.table.setToolTip("머리글을 눌러 정렬합니다(점수 낮은 순, 문제 긴 순 등). 두 번 누르면 그 모션을 엽니다. "
                              "머리글 우클릭: 보일 열")
        self.table.doubleClicked.connect(self._open)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        lay.addWidget(self.table, 1)
        self.summary = QLabel()
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.summary)
        self._picked = self._saved_columns()
        self._apply_columns()
        self.add_folders([])
        self._show_totals()

    # ------------------------------------------------------------ columns
    def _saved_columns(self) -> dict[str, bool]:
        """The columns the user turned on or off (the header's menu), by key."""
        raw = self.win.settings.value("dataset/columns", "") if hasattr(self.win, "settings") else ""
        out = {}
        for part in str(raw or "").split(","):
            key, _, on = part.partition("=")
            if key:
                out[key] = on == "1"
        return out

    def _apply_columns(self) -> None:
        for c, (key, _t, _f) in enumerate(batch.COLUMNS):
            shown = self._picked.get(key, key in BATCH_SHOWN or (key in BATCH_WHEN_FILLED and key in self._filled))
            if self.table.isColumnHidden(c) == shown:
                self.table.setColumnHidden(c, not shown)

    def _columns_menu(self, pos) -> None:
        m = QMenu(self)
        for c, (key, title, _f) in enumerate(batch.COLUMNS):
            a = m.addAction(title)
            a.setCheckable(True)
            a.setChecked(not self.table.isColumnHidden(c))
            a.toggled.connect(lambda on, k=key: self._pick_column(k, on))
        m.addSeparator()
        m.addAction("처음 열로", lambda: self._pick_column(None, False))
        m.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _pick_column(self, key: str | None, on: bool) -> None:
        if key is None:  # back to the defaults
            self._picked = {}
        else:
            self._picked[key] = on
        if hasattr(self.win, "settings"):
            self.win.settings.setValue("dataset/columns", ",".join(f"{k}={int(v)}" for k, v in self._picked.items()))
        self._apply_columns()

    # ------------------------------------------------------------ actions
    def _add_folder(self) -> None:
        start = self.folders[-1] if self.folders else os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "모션 폴더 고르기", start)
        if path:
            self.add_folders([path])

    def add_folders(self, folders: list[str]) -> None:
        for f in folders:
            f = os.path.abspath(f)
            if f not in self.folders:
                self.folders.append(f)
        self.where.setText(" · ".join(os.path.basename(f) or f for f in self.folders) or "폴더를 더하세요")
        self.where.setToolTip("\n".join(self.folders))
        if not self.model.rows and not self._running:
            self._show_totals()

    def _clear(self) -> None:
        if self._running:
            return
        self.folders = []
        self.model.clear()
        self._filled = set()
        self.add_folders([])
        self.progress.reset()
        self.filter_row.setVisible(False)
        self._apply_columns()
        self._show_totals()

    def _request_stop(self) -> None:
        self._stop = True
        self.stop.setEnabled(False)
        self.win.status("일괄 처리: 지금 모션이 끝나면 멈춥니다")

    def options(self) -> batch.BatchOptions:
        o = self.win.scene.opts
        rules = autolabel.rules_file() if self.auto.isChecked() else None
        return batch.BatchOptions(robot=o.robot, smooth=o.smooth, fps=o.fps, csv_fps=o.csv_fps,
                                  smpl_model_dir=o.smpl_model_dir, foot_flat=o.foot_flat,
                                  swing_clearance_cm=o.swing_clearance_cm, self_collision=o.self_collision,
                                  physics=self.physics.isChecked(), rules=rules or None)

    def run(self) -> None:
        """Process the folders in the background; rows come in as they are done."""
        if self._running:
            return
        files = batch.motion_files(self.folders)
        if not files:
            self.win.status("일괄 처리: 모션 파일이 없습니다(폴더를 더하세요)", 5000)
            return
        opts = self.options()
        if self.auto.isChecked() and not opts.rules:
            self.win.status("일괄 처리: 자동 라벨 규칙 파일이 없습니다(⋯ > 자동 라벨 규칙 파일...). 라벨 파일만 셉니다", 8000)
        self.model.clear()
        self._filled = set()
        self._begin(len(files))
        self._apply_columns()
        self._show_totals()
        runner = batch.Batch(opts, log=self.win.scene.log)

        def progress(done, total, row):
            self.win.bridge.gui.emit(lambda: self._row_done(done, total, row))

        def work():
            try:
                runner.run(files, progress=progress, cancel=lambda: self._stop)
            finally:
                self.win.bridge.gui.emit(self._finished)

        threading.Thread(target=work, daemon=True, name="batch").start()

    def _begin(self, total: int, what: str = "") -> None:
        """시작 / 내보내기 make way for 멈춤 and the progress."""
        self._stop, self._running, self._total = False, True, total
        self.start.setVisible(False)
        self.export_btn.setEnabled(False)
        self.stop.setEnabled(True)
        self.stop.setVisible(True)
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress.setFormat(f"{what}%v / {total}")
        self.progress.setVisible(True)

    def _end(self) -> None:
        self._running = False
        self.start.setVisible(True)
        self.export_btn.setEnabled(True)
        self.stop.setVisible(False)
        self.progress.setVisible(False)

    def export(self) -> None:
        """데이터셋 내보내기 (retlens.dataset) of the folders with this tab's options, in the background."""
        if self._running:
            return
        files = batch.motion_files(self.folders)
        if not files:
            self.win.status("데이터셋 내보내기: 모션 파일이 없습니다(폴더를 더하세요)", 5000)
            return
        start = os.path.join(os.path.dirname(self.folders[0]), "dataset_export")
        dlg = export_dialogs.DatasetExportDialog(self, getattr(self.win, "settings", None), len(files),
                                                 self.physics.isChecked(), start)
        if dlg.exec() != QDialog.Accepted:
            return
        out, eopts = dlg.values()
        if not export_dialogs.confirm_folder(self, out, "데이터셋 내보내기"):
            return
        try:
            exporter = dataset.Exporter(self.options(), eopts, out, log=self.win.scene.log)
        except Exception as e:
            QMessageBox.warning(self, "데이터셋 내보내기", f"{type(e).__name__}: {e}")
            return
        self._begin(len(files), "내보내기 ")
        folders = list(self.folders)

        def progress(done, total, name):
            self.win.bridge.gui.emit(lambda: self.progress.setValue(done))

        def work():
            result = None
            try:
                result = exporter.run(folders, progress=progress, cancel=lambda: self._stop)
            except Exception as e:  # shown, never lost in the thread
                result = {"error": f"{type(e).__name__}: {e}"}
            finally:
                self.win.bridge.gui.emit(lambda: self._export_done(result, out))

        threading.Thread(target=work, daemon=True, name="export").start()

    def _export_done(self, m: dict | None, out: str) -> None:
        self._end()
        if not m or m.get("error"):
            QMessageBox.warning(self, "데이터셋 내보내기", f"내보내지 못했습니다: {(m or {}).get('error', '?')}")
            return
        text = export_dialogs.manifest_text(m)
        self.win.status(f"데이터셋 내보내기 {'멈춤' if m.get('stopped') else '끝'}: {text.splitlines()[0]}", 10000)
        export_dialogs.report(self, "데이터셋 내보내기",
                              f"{out}\n\n{text}\n\n뺀 것과 이유는 manifest.json의 excluded에 있습니다.",
                              out, self.win.open_path)

    def _row_done(self, done: int, total: int, row: dict) -> None:
        self.model.add(row)
        self.progress.setValue(done)
        filled = {k for k in BATCH_WHEN_FILLED  # a count of 0 says nothing, except 0 falls
                  if row.get(k) not in (None, "") and (row.get(k) != 0 or k == "phys_falls")}
        if not filled <= self._filled:
            self._filled |= filled
            self._apply_columns()
        self.filter_row.setVisible(True)
        self._show_totals()
        if done == 1:
            self.table.resizeColumnsToContents()

    def _finished(self) -> None:
        self._end()
        self._show_totals()
        t = batch.totals(self.model.rows)
        self.win.status(f"일괄 처리 {'멈춤' if self._stop else '끝'}: 모션 {t['read']}개 · 오류 {t['errors']}개", 8000)

    _total = 0  # files of the last run

    def _show_totals(self) -> None:
        if not self.model.rows:
            self.summary.setText("" if self._running else
                                 "폴더 추가...로 촬영 폴더를 고르고 시작을 누릅니다." if not self.folders else
                                 "시작을 누르면 폴더의 모션을 리타게팅하고 재서 한 줄씩 모읍니다.")
            return
        t = batch.totals(self.model.rows)
        parts = [f"모션 {t['read']}개", f"{t['total_s'] / 60:.1f}분", f"QC FAIL {t['qc_fail']}", f"WARN {t['qc_warn']}"]
        n = len(self.model.rows)
        if n < self._total:  # still running, or stopped: how far it got
            parts.insert(0, f"{n} / {self._total} 처리" + ("" if self._running else " (멈춤, 다시 시작하면 남은 것부터)"))
        if self.physics.isChecked():
            parts.append(f"물리 넘어짐 있는 모션 {t['with_falls']}")
        parts += [f"{name} {t[k]}" for k, name in (("labelled", "라벨 있음"), ("with_objects", "물체 있음"),
                                                   ("errors", "오류")) if t[k]]
        self.summary.setText(" · ".join(parts))

    def _row(self, index) -> dict:
        return self.model.rows[self.proxy.mapToSource(index).row()]

    def _open(self, index) -> None:
        row = self._row(index)
        if row.get("file"):
            self.win.add_paths([row["file"]])

    def _row_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = self._row(index)
        if not row.get("file"):
            return
        m = QMenu(self)
        m.addAction("열기", lambda: self.win.add_paths([row["file"]]))
        m.addAction("파일 위치 열기", lambda: self.win.open_path(os.path.dirname(row["file"])))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _save_csv(self) -> None:
        if not self.model.rows:
            self.win.status("저장할 표가 없습니다", 4000)
            return
        start = os.path.join(self.folders[0] if self.folders else os.path.expanduser("~"), "retlens_batch.csv")
        path, _ = QFileDialog.getSaveFileName(self, "일괄 처리 표 저장", start, "CSV (*.csv)")
        if path:
            self.win.status(f"저장함: {batch.write_csv(self.model.rows, path)}", 6000)


class SegmentModel(QAbstractTableModel):
    """The inspector's list of a motion's segments: track (with several), label, start, end. With on_edit, the
    label, start and end can be edited: on_edit(segment, field, value) is called once the editor has closed
    (the edit replaces the labels, which resets this list)."""

    def __init__(self, it: Item, segs: list, multi: bool, parent=None, on_edit=None):
        super().__init__(parent)
        self.it, self.segs, self.multi, self.on_edit = it, segs, multi, on_edit
        self.heads = (["트랙"] if multi else []) + ["라벨", "시작 (s)", "끝 (s)"]
        self._icons: dict[tuple, QIcon] = {}

    def set_segments(self, segs: list) -> None:
        self.beginResetModel()
        self.segs = segs
        self.endResetModel()

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemIsEditable if self.on_edit is not None and index.column() >= self.multi else f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or self.on_edit is None:
            return False
        seg, field = self.segs[index.row()], ("label", "start", "end")[index.column() - self.multi]
        QTimer.singleShot(0, lambda: self.on_edit(seg, field, value))  # not inside the editor's commit
        return True

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.segs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.heads)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.heads[section] if role == Qt.DisplayRole and orientation == Qt.Horizontal else None

    def data(self, index, role=Qt.DisplayRole):
        s = self.segs[index.row()]
        c = index.column() - self.multi  # -1 track, 0 label, 1 start, 2 end
        if role == Qt.DisplayRole:
            return (s.track, s.label, f"{s.start:.3f}", f"{s.end:.3f}")[c + 1]
        if role == Qt.EditRole:
            return (s.track, s.label, s.start, s.end)[c + 1]
        if role == Qt.ToolTipRole:
            return segment_text(self.it, s)
        if role == Qt.DecorationRole and c == 0:
            rgb = motion_labels.color_for(s)
            if rgb not in self._icons:
                self._icons[rgb] = color_icon(rgb)
            return self._icons[rgb]
        if role == Qt.TextAlignmentRole and c >= 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class SegmentDelegate(QStyledItemDelegate):
    """Editors of the segment list: a label from the ones in use (or a new one), a time on the motion's frames."""

    def __init__(self, model: SegmentModel, names, parent=None):
        super().__init__(parent)
        self.model, self.names = model, names

    def createEditor(self, parent, option, index):
        if index.column() - self.model.multi == 0:
            box = QComboBox(parent)
            box.setEditable(True)
            box.addItems(self.names(self.model.segs[index.row()].track))
            return box
        spin = QDoubleSpinBox(parent)
        spin.setDecimals(3)
        spin.setRange(0.0, 1e6)
        spin.setSingleStep(1.0 / max(self.model.it.robot.fps, 1.0))
        return spin

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole)
        if isinstance(editor, QComboBox):
            editor.setEditText(str(value))
        else:
            editor.setValue(float(value))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText() if isinstance(editor, QComboBox) else editor.value(), Qt.EditRole)


def segment_text(it: Item, s: motion_labels.Segment) -> str:
    """Hover text of a labelled segment: its label, time and frames (at the motion's fps), track and note."""
    f0, f1 = int(round(s.start * it.robot.fps)), int(round(s.end * it.robot.fps)) - 1
    lines = [s.label + (f" · {s.name}" if s.name else ""),
             f"{s.start:.2f} – {s.end:.2f} s ({s.duration:.2f} s) · 프레임 {f0} – {max(f0, f1)}"]
    extra = " · ".join(x for x in (f"트랙 {s.track}" if s.track else "", s.note) if x)
    return "\n".join(lines + ([extra] if extra else []))


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _pick_label_file(files: list[str], source: str) -> str:
    """Of the label files dropped with one motion, the one opening it would pick (its own names
    first, in motion_labels' order), else the first dropped."""
    order = {_path_key(p): i for i, p in enumerate(motion_labels.candidates(source))}
    return min(files, key=lambda f: order.get(_path_key(f), len(order)))


def _motion_for_label(label: str, motions: list[str], prefer: str | None = None) -> str | None:
    """The motion file a label file is named after (02_01.labels.csv -> 02_01.bvh, else the same take
    02_01_stageii.npz); of several, the one in the label file's folder, else `prefer`, else the first."""
    stem = motion_labels.stem_of(label).lower()
    name = lambda m: os.path.splitext(os.path.basename(m))[0].lower()
    named = [m for m in motions if name(m) == stem] or \
        [m for m in motions if motion_labels.same_take(name(m)) == motion_labels.same_take(stem)]
    here = [m for m in named if _path_key(os.path.dirname(m)) == _path_key(os.path.dirname(label))]
    chosen = [m for m in named if prefer is not None and _path_key(m) == _path_key(prefer)]
    pick = here or chosen or named
    return pick[0] if pick else None


def labels_text(it: Item, lab=None) -> str:
    """The inspector's line about a motion's labels (lab: as read once by the caller; None: none)."""
    if lab is None:
        stem = os.path.splitext(os.path.basename(it.source))[0]
        return (f"라벨 파일이 없습니다. 모션 옆에 {stem}.labels.csv 같은 파일을 두면 열 때 붙고, 아래 '불러오기'나 "
                "타임라인 우클릭으로 아무 라벨 파일이나 붙일 수 있습니다. '자동 라벨'은 규칙 파일대로 사람 동작을 보고 붙이고, "
                "'＋ 구간'으로 직접 만들 수도 있습니다.")
    head = rel(lab.path).replace("\\", "/") if lab.path else ("새로 만든 라벨" if lab.edited else "라벨")
    if lab.auto:
        head = f"자동 라벨 · {lab.auto}" + (" · 편집함" if lab.edited else "") + (f"\n규칙 파일 {head}" if lab.path else "")
        if lab.error:
            return f"{head}\n자동 라벨을 붙이지 못함: {lab.error}"
    if lab.error:
        return f"{head}\n라벨 파일을 쓰지 못함: {lab.error}"
    tracks = [t for t in lab.tracks if t]
    text = f"{head}\n구간 {len(lab.segments)}개" + (f" · 트랙 {len(tracks)}개 ({', '.join(tracks)})" if tracks else "")
    return text + "".join(f"\n· {'불러올 때: ' if lab.edited else ''}{n}" for n in lab.notes)


def short_text(v: str, limit: int = 18) -> str:
    """'넘어짐 1회; 보조 힘 > 체중 20%: 프레임 62.8%; ...' -> '넘어짐 1회 외 2' for narrow table cells."""
    parts = [p.strip() for p in v.split(";") if p.strip()]
    s = parts[0] + (f" 외 {len(parts) - 1}" if len(parts) > 1 else "") if parts else v
    return s if len(s) <= limit else s[:limit - 1] + "…"


# ------------------------------------------------------------------------------ settings
OK_COLOR, WARN_COLOR, BAD_COLOR = "#5cb85c", "#e0a030", "#e05050"


def same_robot_spec(a: str, b: str) -> bool:
    """Do two robot specs (registry key or model path) name the same model file?"""
    def norm(s):
        return s if not s or s in ("unitree_g1", "unitree_g1_with_hands") else os.path.normcase(os.path.abspath(s))

    return norm(a or "unitree_g1") == norm(b or "unitree_g1")


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
        ("robot", "로봇 모델", "로봇 모델 MJCF / URDF (*.xml *.urdf);;모든 파일 (*)", "robot_model"),
        ("isaac", "Isaac Sim", "Isaac Sim python.bat (python.bat);;모든 파일 (*)", "isaac_python"),
        ("blender", "Blender 4.5", "blender.exe (blender.exe);;모든 파일 (*)", "blender"),
        ("smpl", "SMPL-X 모델 폴더", None, "smpl_model_dir"),
        ("gmt", "GMT 폴더", None, "gmt_dir"),
        ("robot_usd", "로봇 USD (선택)", "USD (*.usd *.usda *.usdc *.usdz);;모든 파일 (*)", "robot_usd"),
        ("video", "동영상 저장 폴더", None, "video_dir"),
    ]
    TIPS = {"robot": "리타게팅하고 보여 주는 로봇입니다. 아무 휴머노이드의 MJCF(.xml)나 URDF(.urdf)를 고르면 다리·팔·발과 "
                     "관절 역할을 모델에서 찾습니다(떠 있는 몸통, 다리 둘, 팔 둘이 있어야 함). 비우면 내장 Unitree G1. "
                     "바꾸면 다시 시작할 때 적용됩니다.",
            "isaac": "동영상 저장과 물리 모드의 '보조 힘 (Isaac)'에 씁니다. 설치 폴더(python.bat이 있는 곳)나 python.bat을 "
                     "고르세요.",
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
        self.fetch: dict[str, QPushButton] = {}  # 받는 곳: shown while that one is missing
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
                self.fetch[key] = get
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
        rows = [("gmr", "리타게팅 (GMR)")]
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
                                 api_port=int(self.api_port.value()),
                                 label_rules=settings.load().label_rules)  # picked in 인스펙터 > 라벨, kept as it is

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
            if key == "robot":
                self.edits[key].setPlaceholderText("비우면 내장 Unitree G1")
            elif key == "robot_usd":
                self.edits[key].setPlaceholderText("비우면 NVIDIA 에셋 서버의 Unitree G1 (인터넷 필요)")
            else:
                self.edits[key].setPlaceholderText(f"자동: {found_auto[key]}" if found_auto[key] else "자동: 찾지 못함")
            self.status[key].setText(check_html(checks[key]))
            if key in self.fetch:
                self.fetch[key].setVisible(not checks[key].ok)
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
        if not same_robot_spec(settings.robot_spec(), self.win.scene.opts.robot):
            robot = settings.find_robot()
            QMessageBox.information(self.win, APP_NAME, "로봇 모델은 RetLens를 다시 시작하면 바뀝니다." + (
                "" if robot.path else f"\n\n지금 이 모델은 쓸 수 없습니다: {robot.problem}\n"
                                      "그대로 두면 다음 시작 때 내장 G1로 시작합니다."))

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
    """설치 도우미 (retlens/prereqs.py): per optional component, what this PC has, whether it is
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
        self.bridge.labelled.connect(self._on_labelled)
        self.bridge.gui.connect(self._run_on_gui)
        self._label_jobs: dict[Item, dict] = {}  # 자동 라벨 being made off the GUI thread: each motion's latest request
        self.bridge.log.connect(self._append_log)
        scene.listen(lambda e, p: self.bridge.event.emit(e, p))
        base_log = scene.log
        scene.log = lambda msg: (base_log(msg), self.bridge.log.emit(str(msg)))  # also to the console panel
        scene.runner.log = scene.log  # Isaac job messages too
        self._eula = accept_eula or self.settings.value("isaac/eula_accepted", False, type=bool)
        scene.runner.accept_eula = self._eula
        self._loading = 0
        self._pending_labels: dict[str, list[str]] = {}  # label files dropped with their motion, by that file (_path_key)
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        self.view = SceneView(url)
        self.setCentralWidget(self.view)
        QApplication.instance().installEventFilter(_SceneUndoKeys(self.view))
        self.hierarchy = HierarchyPanel(self)
        self.inspector = InspectorPanel(self)
        self.scene_settings = SceneSettingsPanel(self)
        self.timeline = TimelinePanel(self)
        self.project = ProjectPanel(self, library)
        self.analysis = AnalysisPanel(self)
        self.compare_panel = ComparePanel(self)
        self.dataset = DatasetPanel(self)
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
            if not self.settings.value(layout_key("layout/has_dataset"), False, type=bool):  # saved before 데이터셋
                self.tabifyDockWidget(self.docks["compare"], self.docks["dataset"])
            if not self.settings.value(layout_key("layout/tidy_v1"), False, type=bool):  # saved before 콘솔 was hidden
                for key in self.DEFAULT_HIDDEN:
                    self.docks[key].hide()
        self.settings.setValue(layout_key("layout/has_compare"), True)
        self.settings.setValue(layout_key("layout/has_dataset"), True)
        self.settings.setValue(layout_key("layout/tidy_v1"), True)

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
        data = self._dock("dataset", "데이터셋", self.dataset, B)
        con = self._dock("console", "콘솔", self.console, B)
        self.splitDockWidget(tl, proj, Qt.Vertical)
        self.tabifyDockWidget(proj, ana)
        self.tabifyDockWidget(ana, cmp)
        self.tabifyDockWidget(cmp, data)
        self.tabifyDockWidget(data, con)
        proj.raise_()
        for key in self.DEFAULT_HIDDEN:  # 보기 menu shows them
            self.docks[key].hide()
        self.resizeDocks([hier, insp], [160, 580], Qt.Vertical)
        self.resizeDocks([hier], [420], Qt.Horizontal)
        self.resizeDocks([tl, proj], [110, 260], Qt.Vertical)

    DEFAULT_HIDDEN = ("console",)  # docks the default layout keeps closed (보기 opens them)

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
        self.a_batch = act("폴더 일괄 처리...", lambda: (self.docks["dataset"].show(), self.docks["dataset"].raise_(),
                                                    self.dataset._add_folder()),
                           tip="촬영 세션 폴더의 모션을 모두 리타게팅·측정해 데이터셋 탭의 표에 모읍니다")
        self.a_export = act("데이터셋 내보내기...", lambda: (self.docks["dataset"].show(), self.docks["dataset"].raise_(),
                                                       self.dataset.export() if self.dataset.folders else
                                                       self.dataset._add_folder()),
                            tip="데이터셋 탭의 폴더에서 기준을 넘는 모션을 한 폴더에 로봇 모션·라벨·manifest로 모읍니다")
        self.a_quit = act("종료", self.close, "Ctrl+Q")
        self.a_remove = act("선택한 모션 제거", self.delete_selected, "Delete",
                            tip="고른 모션을 닫습니다 (타임라인이나 구간 표에서 라벨 구간을 골랐으면 그 구간을 지움)")
        # label editing: the picked segment of the selected motion (MotionScene.edit_labels)
        self.a_undo = act("되돌리기", lambda: self.label_undo(), "Ctrl+Z", tip="고른 모션의 마지막 라벨 편집을 되돌립니다")
        self.a_redo = act("다시 실행", lambda: self.label_undo(redo=True), "Ctrl+Y")
        self.a_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.a_rename = act("라벨 바꾸기...", self.label_rename, "F2")
        self.a_split = act("재생 위치에서 나누기", self.label_split, "S")
        self.a_add_seg = act("재생 위치에 구간 추가...", lambda: self.label_add_here(self.selected),
                             tip="재생 위치의 라벨 없는 빈칸을 채우는 구간을 더합니다")
        self.a_merge_prev = act("이전 구간과 합치기", lambda: self.label_merge(-1))
        self.a_merge_next = act("다음 구간과 합치기", lambda: self.label_merge(1))
        self.a_start_here = act("구간 시작을 재생 위치로", lambda: self.label_edge_here("start"), "[",
                                tip="←/→(1/30초씩)로 재생 위치를 옮긴 뒤 누릅니다. 더 세밀하게는 구간 표에서 숫자로 고칩니다")
        self.a_end_here = act("구간 끝을 재생 위치로", lambda: self.label_edge_here("end"), "]")
        self.a_delete_seg = act("라벨 구간 삭제", self.label_delete, tip="Delete (타임라인이나 구간 표에서)")
        self.a_save_labels = act("라벨 CSV로 저장...", lambda: self.selected is not None and
                                 self.save_labels_dialog(self.selected))
        self.a_remove_all = act("모두 제거...", self.remove_all)
        for a in (self.a_video, self.a_remove, self.a_remove_all):  # select() / the items event turn them on
            a.setEnabled(False)
        self.a_play = act("재생 / 일시정지", sc.toggle_play, "Space", QStyle.SP_MediaPlay)
        self.a_home = act("처음으로", lambda: sc.seek(0.0), "Home", QStyle.SP_MediaSkipBackward)
        self.a_prev = act("이전 프레임", lambda: sc.step(-1), "Left", QStyle.SP_MediaSeekBackward)
        self.a_next = act("다음 프레임", lambda: sc.step(1), "Right", QStyle.SP_MediaSeekForward)
        self.a_next_problem = act("다음 문제로", lambda: self.goto_problem(1), "N",
                                  tip="고른 모션(없으면 보이는 모든 모션)의 다음 문제 시작으로 (N)")
        self.a_prev_problem = act("이전 문제로", lambda: self.goto_problem(-1), "Shift+N",
                                  tip="고른 모션(없으면 보이는 모든 모션)의 이전 문제 시작으로 (Shift+N)")
        self.a_show_problems = act("타임라인에 문제 구간 표시", lambda on: setattr(sc.view, "show_problems", on), checkable=True,
                                   tip="모션 막대 아래쪽에 문제 구간을 색 띠로 그립니다(마우스를 올리면 종류와 시각)")
        self.a_show_problems.setChecked(sc.view.show_problems)
        self.a_physics = act("물리 모드", self.set_physics, "P", checkable=True,
                             tip="로봇을 물리 시뮬레이션 결과로 그립니다 (P). ▾에서 균형 제어를 고릅니다")
        self.a_cancel = act("작업 취소", lambda: self.cancel_all(), icon=QStyle.SP_BrowserStop,
                            tip="대기 중이거나 돌고 있는 물리 계산(Isaac·MuJoCo)과 동영상 녹화, 여는 중인 작업 세션을 멈춥니다")
        self.a_session_open = act("작업 세션 열기...", self.open_session_dialog, "Ctrl+Shift+O")
        self.a_session_save = act("작업 세션 저장", lambda: self.save_session(), "Ctrl+S",
                                  tip="열린 모션(보정·시간 오프셋·보이기·라벨과 고친 라벨), 겹쳐 비교, 씬 설정, 물리 모드, "
                                      "재생 위치를 파일 하나(.retlens)에 저장합니다. 모션 파일은 복사하지 않고 위치만 적습니다")
        self.a_session_save_as = act("작업 세션 다른 이름으로 저장...", lambda: self.save_session_as(), "Ctrl+Shift+S")
        self.a_session_new = act("새 작업 세션", self.new_session, "Ctrl+N", tip="열린 모션을 모두 닫고 새로 시작합니다")
        self.a_cancel.setEnabled(False)  # while jobs run (_refresh_status)
        self.a_compare = act("겹쳐 비교", lambda on: self.start_compare(on=on), "O", checkable=True,
                             tip="대상(B)을 기준(A)의 골반에 겹쳐, 벗어난 부위만 색칠합니다 (O). A·B는 비교 탭이나 "
                                 "계층 우클릭에서 고릅니다")
        self.a_fit = act("카메라 맞추기", sc.fit_camera, "F", tip="보이는 모션이 모두 들어오게 카메라를 옮깁니다 (F)")
        self.a_reset = act("레이아웃 초기화", self.reset_layout)
        self.a_browser = act("브라우저에서 씬 열기", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.a_readme = act("사용 설명서", lambda: self.open_path(app_paths.doc("docs", "manual.md")))
        self.a_labels = act("CMU 동작 목록", lambda: self.open_path(app_paths.doc("docs", "cmu_motion_labels.md")))
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
        self.a_self_collision = act("자기 관통 보정", lambda on: self.set_retarget(self_collision=on), checkable=True,
                                    tip=f"{RETARGET_TIPS['self_collision']}. {RETARGET_NOTE}")
        self._sync_retarget()

        tb = QToolBar("도구 모음", self)
        tb.setObjectName("toolbar_main")
        tb.setMovable(True)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        mb = self.menuBar()
        m = mb.addMenu("파일(&F)")
        m.setToolTipsVisible(True)
        self.m_recent = QMenu("최근 작업 세션", self)
        self.m_recent.aboutToShow.connect(lambda: self._fill_recent_menu(self.m_recent))
        for a in (self.a_open, self.a_batch, self.a_export, None, self.a_session_new, self.a_session_open, self.m_recent,
                  self.a_session_save, self.a_session_save_as, None, self.a_video, self.a_video_dir, self.a_folders, None,
                  self.a_settings, self.a_setup, None, self.a_quit):
            m.addSeparator() if a is None else m.addMenu(a) if isinstance(a, QMenu) else m.addAction(a)
        m = mb.addMenu("편집(&E)")
        m.setToolTipsVisible(True)
        for a in (self.a_undo, self.a_redo, None, self.a_rename, self.a_split, self.a_add_seg, self.a_merge_prev,
                  self.a_merge_next, self.a_start_here, self.a_end_here, self.a_delete_seg, self.a_save_labels, None,
                  self.a_remove, self.a_remove_all):
            m.addSeparator() if a is None else m.addAction(a)
        self._refresh_label_actions()
        m = mb.addMenu("보기(&V)")
        for d in self.docks.values():
            m.addAction(d.toggleViewAction())
        m.addAction(tb.toggleViewAction())
        m.addSeparator()
        for a in (self.a_compare, self.a_fit, self.a_reset, self.a_browser):
            m.addAction(a)
        m = mb.addMenu("재생(&P)")
        m.setToolTipsVisible(True)
        for a in (self.a_play, self.a_home, self.a_prev, self.a_next, None, self.a_next_problem, self.a_prev_problem,
                  self.a_show_problems):
            m.addAction(a) if a is not None else m.addSeparator()
        # 리타게팅 보정 of the human motions opened next (open ones keep theirs: reopen to compare)
        m = mb.addMenu("리타게팅(&R)")
        m.setToolTipsVisible(True)
        m.addSection("새로 여는 모션에 적용")  # an open motion: 인스펙터 > 보정
        m.addAction(self.a_foot_flat)
        m.addAction(self.a_swing)
        m.addAction(self.a_self_collision)
        m = mb.addMenu("물리(&S)")
        m.setToolTipsVisible(True)
        m.addAction(self.a_physics)
        # 균형 제어: what keeps the simulated robot up. A mode whose files are not here yet (GMT before the
        # setup assistant fetched it) says so in its label and tip; picking it explains and offers the assistant.
        # The same menu drops down from the toolbar's 물리 모드 button
        sub = self.m_balance = m.addMenu("균형 제어")
        sub.setToolTipsVisible(True)
        grp = QActionGroup(self)
        self.a_balance = {}
        for key, label in BALANCE.items():
            a = QAction(label, self, checkable=True)
            a.setChecked(key == sc.balance)
            a.triggered.connect(lambda _=False, k=key: self.set_balance(k))
            grp.addAction(a)
            sub.addAction(a)
            self.a_balance[key] = a
        self._refresh_balance_entries()
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

        # the toolbar: what is used all the time; playback is the timeline's, the rest is in the menus
        self.physics_btn = QToolButton()  # 물리 모드, and its 균형 제어 from the ▾
        self.physics_btn.setDefaultAction(self.a_physics)
        self.physics_btn.setMenu(self.m_balance)
        self.physics_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.physics_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_open, None, self.physics_btn, self.a_compare, self.a_fit):
            tb.addSeparator() if a is None else tb.addWidget(a) if isinstance(a, QWidget) else tb.addAction(a)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _build_status(self) -> None:
        """Permanent items show only when they matter: running jobs (with ✕ to cancel), physics mode while it is
        on, 환경 ⚠ when something is missing, the AI API when it failed to start."""
        sb = self.statusBar()
        self.st_jobs = QLabel()
        self.st_cancel = QToolButton()
        self.st_cancel.setDefaultAction(self.a_cancel)
        self.st_cancel.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.st_cancel.setAutoRaise(True)
        self.st_physics = QLabel()
        self.st_env = QToolButton()  # what is missing; opens 환경 설정
        self.st_env.setAutoRaise(True)
        self.st_env.clicked.connect(lambda: self.open_settings())
        self.st_api = QLabel()  # the AI API (retlens/app/api_server.py), when it could not start
        for w in (self.st_jobs, self.st_cancel, self.st_physics, self.st_env, self.st_api):
            if isinstance(w, QLabel):
                w.setContentsMargins(8, 0, 8, 0)
            w.hide()
            sb.addPermanentWidget(w)

    # ---------------------------------------------------------------- 환경 설정
    auto_setup = True  # open 환경 설정 on the first start when something is missing (off for smoke tests)

    def _refresh_env(self, checks: list | None = None) -> list:
        checks = checks if checks is not None else settings.check_all()
        missing = [c for c in checks if not c.ok]
        self.st_env.setVisible(bool(missing))
        if missing:
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
        self._refresh_api_status()  # turned off: a failure from before no longer matters
        if not quiet:
            self.status("환경 설정을 저장했습니다", 4000)

    # ---------------------------------------------------------------- AI API
    api = None
    _api_port_asked = None
    _api_error = ""  # why the API did not start (the status bar says so)

    def _start_api(self) -> None:
        """The local HTTP API for AI agents (retlens/app/api_server.py), when 환경 설정 has it on."""
        from .api_server import ApiBackend, ApiServer, discovery_path

        s = settings.load()
        self._api_port_asked, self._api_error = s.api_port, ""
        if not s.api_enabled:
            self._refresh_api_status()
            return
        try:
            self.api = ApiServer(ApiBackend(self.scene, self, on_gui=self._gui_call), s.api_port).start()
            self.scene.log(f"AI용 로컬 API: {self.api.url} (토큰: {discovery_path()})")
        except Exception as e:
            self.api = None
            self._api_error = f"{type(e).__name__}: {e}"
            self.scene.log(f"AI용 로컬 API를 열지 못함: {self._api_error}")
        self._refresh_api_status()

    def _stop_api(self) -> None:
        if self.api is not None:
            self.api.stop()
            self.api = None

    def _refresh_api_status(self) -> None:
        """Only a failure shows: the running API's address is in 환경 설정 > AI 연동."""
        self.st_api.setVisible(bool(self._api_error) and self.api is None and settings.load().api_enabled)
        self.st_api.setText("API 시작 실패")
        self.st_api.setToolTip(f"AI용 로컬 API를 열지 못했습니다: {self._api_error}\n(환경 설정 > AI 연동에서 포트를 바꿉니다)")

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
        for key, d in self.docks.items():
            d.setVisible(key not in self.DEFAULT_HIDDEN)

    # ---------------------------------------------------------------- selection / items
    def item_by_id(self, key) -> Item | None:
        return next((it for it in self.scene.items if id(it) == key), None)

    def select(self, item: Item | None) -> None:
        if self.label_sel is not None and self.label_sel[0] is not item:
            self.label_sel = None
        self.selected = item
        self.hierarchy.select(item)
        self.inspector.show_item(item)
        self.docks["inspector"].raise_()
        self.timeline.tracks.update()
        self.a_video.setEnabled(item is not None)
        self.a_remove.setEnabled(item is not None)
        self._refresh_label_actions()

    def remove(self, item: Item | None) -> None:
        if item is not None and self._confirm_discard_labels([item], "제거하면"):
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
        items = list(self.scene.items)
        if not items:
            return
        if any(self.scene.labels_dirty(it) for it in items):  # its question says it all
            if not self._confirm_discard_labels(items, "모두 제거하면"):
                return
        elif QMessageBox.question(self, "모두 제거", f"열린 모션 {len(items)}개를 모두 제거할까요?\n"
                                                    "(파일은 그대로입니다)") != QMessageBox.Yes:
            return
        for it in items:
            self.scene.remove(it)

    # ---------------------------------------------------------------- label editing (retlens.motion_labels)
    # A segment is picked in the timeline or the inspector's list; the edits act on it, each one undo step of its
    # motion (MotionScene.edit_labels). Edited labels stay in the window until 라벨 CSV로 저장.
    label_sel = None  # (motion, segment) picked
    _sel_cache = None  # (labels, segment, segment is in them): label_selection runs on every paint
    confirm_unsaved = True  # ask before unsaved label edits go (off for smoke tests)

    def label_selection(self):
        """(motion, its labels, segment) picked, while that segment is still one of the selected motion's."""
        sel = self.label_sel
        if sel is None or sel[0] is not self.selected or sel[0] not in self.scene.items:
            return None
        it, seg = sel
        lab = it.labels
        if lab is None:
            return None
        cache = self._sel_cache
        if cache is None or cache[0] is not lab or cache[1] is not seg:
            self._sel_cache = cache = (lab, seg, any(s is seg for s in lab.segments))
        return (it, lab, seg) if cache[2] else None

    def set_label_selection(self, item: Item | None, seg) -> None:
        if item is not None and item is not self.selected:
            self.select(item)
        self.label_sel = (item, seg) if item is not None and seg is not None else None
        self.timeline.tracks.update()
        self.inspector.select_segment(seg if self.label_sel is not None else None)
        self._refresh_label_actions()

    def edit_labels(self, item: Item, base, result, what: str, before=None) -> bool:
        """Put an edit's result (new labels, segment to pick) on the motion as one undo step."""
        new, seg = result
        if not self.scene.edit_labels(item, base, new, what, before=before, after=seg):
            self.status("라벨이 그사이 다른 곳(API·자동 라벨·다시 리타게팅)에서 바뀌어 이 편집은 하지 않았습니다", 8000)
            return False
        if new is not base:
            self._pick_after_edit(item, seg)
            self.status(f"{item.label}: {what} (Ctrl+Z 되돌리기)", 5000)
        return True

    def _pick_after_edit(self, item: Item, seg) -> None:
        """The segment an edit (or undo) leaves picked; the labels event that came first saw the old one."""
        self.label_sel = (item, seg) if seg is not None else None
        self.timeline.tracks.update()
        self.inspector.select_segment(seg)
        self._refresh_label_actions()

    def _edit_picked(self, what: str, make) -> None:
        """make(motion, labels, segment) -> (new labels, segment) on the picked segment; what is wrong goes to the
        status bar."""
        sel = self.label_selection()
        if sel is None:
            self.status("고른 라벨 구간이 없습니다 (타임라인이나 인스펙터의 구간 표에서 구간을 누릅니다)", 6000)
            return
        it, lab, seg = sel
        try:
            result = make(it, lab, seg)
        except ValueError as e:
            self.status(str(e), 6000)
            return
        if result is not None:
            self.edit_labels(it, lab, result, what, before=seg)

    def _ask_label(self, title: str, text: str, track: str, current: str = "") -> str | None:
        names = self.scene.label_names(track)
        if current and current not in names:
            names.insert(0, current)
        label, ok = QInputDialog.getItem(self, title, text, names or [motion_labels.NEW_LABEL],
                                         names.index(current) if current in names else 0, True)
        return label.strip() if ok and label.strip() else None

    def label_rename(self) -> None:
        sel = self.label_selection()
        if sel is None:
            self._edit_picked("라벨 바꾸기", None)
            return
        label = self._ask_label("라벨 바꾸기", f"{sel[2].label} ({sel[2].start:.2f}–{sel[2].end:.2f} s)의 새 라벨:",
                                sel[2].track, sel[2].label)
        if label is not None:
            self._edit_picked("라벨 바꾸기", lambda it, lab, seg: motion_labels.relabeled(lab, seg, label))

    def label_split(self) -> None:
        self._edit_picked("구간 나누기", lambda it, lab, seg: motion_labels.split(lab, seg, self.scene.t - it.offset,
                                                                             it.robot.fps))

    def label_merge(self, direction: int) -> None:
        self._edit_picked("구간 합치기", lambda it, lab, seg: motion_labels.merged(lab, seg, direction))

    def label_delete(self) -> None:
        self._edit_picked("구간 삭제", lambda it, lab, seg: motion_labels.removed(lab, seg))

    def label_edge_here(self, which: str) -> None:
        """The picked segment's start or end to the playhead (with Left / Right: frame by frame)."""
        def make(it, lab, seg):
            t = self.scene.t - it.offset
            if (which == "start" and t >= seg.end) or (which == "end" and t <= seg.start):
                raise ValueError(f"재생 위치가 구간의 {'끝' if which == 'start' else '시작'}보다 "
                                 f"{'뒤' if which == 'start' else '앞'}에 있습니다")
            return motion_labels.with_bounds(lab, seg, t if which == "start" else seg.start,
                                             t if which == "end" else seg.end, it.robot.fps, it.robot.duration)
        self._edit_picked("구간 시작을 재생 위치로" if which == "start" else "구간 끝을 재생 위치로", make)

    def edit_segment(self, item: Item, base, seg, field: str, value) -> None:
        """An edit typed in the inspector's segment list (a cell left as it was: nothing)."""
        if field != "label" and abs(float(value) - (seg.start if field == "start" else seg.end)) < 1e-3:
            return
        try:
            if field == "label":
                result = motion_labels.relabeled(base, seg, str(value))
            else:
                start, end = (float(value), seg.end) if field == "start" else (seg.start, float(value))
                result = motion_labels.with_bounds(base, seg, start, end, item.robot.fps, item.robot.duration)
        except ValueError as e:
            self.status(str(e), 6000)
            return
        self.edit_labels(item, base, result, "라벨 바꾸기" if field == "label" else "구간 시간 고치기", before=seg)

    def label_add(self, item: Item, track: str, t: float) -> None:
        """A segment in the unlabelled gap under motion time t on a track; its label is asked first."""
        base = item.labels
        label = self._ask_label("구간 추가", f"{track or '라벨'} 트랙, {t:.2f} s의 빈칸에 붙일 라벨:", track)
        if label is None:
            return
        try:
            result = motion_labels.added(base, track, t, item.robot.fps, item.robot.duration, label)
        except ValueError as e:
            self.status(str(e), 6000)
            return
        self.edit_labels(item, base, result, "구간 추가")

    def label_add_here(self, item: Item | None) -> None:
        """구간 추가 at the playhead: on the picked segment's track, the only track, else a track to name."""
        if item is None:
            return
        sel, lab = self.label_selection(), item.labels
        tracks = lab.tracks if lab is not None and not lab.error else []
        if sel is not None and sel[0] is item:
            self.label_add(item, sel[2].track, self.scene.t - item.offset)
        elif len(tracks) == 1:
            self.label_add(item, tracks[0], self.scene.t - item.offset)
        else:
            self.label_new_track(item)

    def label_new_track(self, item: Item) -> None:
        """A label track (or the motion's first labels): its name and the first segment's label, filling the gap
        under the playhead."""
        lab = item.labels
        d = QDialog(self)
        d.setWindowTitle(f"새 라벨 트랙 - {item.label}")
        form = QFormLayout(d)
        track = QComboBox()
        track.setEditable(True)
        track.addItems(dict.fromkeys(["", *[t for it in self.scene.items if it.labels is not None for t in it.labels.tracks]]))
        track.setToolTip("비워 두면 이름 없는 트랙 (트랙이 하나일 때 흔함)")
        form.addRow("트랙", track)
        label = QComboBox()
        label.setEditable(True)
        label.addItems(self.scene.label_names() or [motion_labels.NEW_LABEL])
        form.addRow("첫 구간 라벨", label)
        t = self.scene.t - item.offset
        form.addRow(QLabel(f"재생 위치({t:.2f} s)의 빈칸을 채웁니다. 그 뒤 끝을 끌거나 나눠서 다듬습니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        form.addRow(buttons)
        if d.exec() != QDialog.Accepted:
            return
        try:
            result = motion_labels.added(lab, track.currentText().strip(), t, item.robot.fps, item.robot.duration,
                                         label.currentText())
        except ValueError as e:
            self.status(str(e), 6000)
            return
        self.edit_labels(item, lab, result, "라벨 트랙 추가")

    def label_undo(self, redo: bool = False) -> None:
        item = self.selected
        done = self.scene.undo_labels(item, redo=redo) if item is not None else None
        if done is None:
            self.status(f"{'다시 실행할' if redo else '되돌릴'} 라벨 편집이 없습니다"
                        + ("" if item is not None else " (모션을 고르세요)"), 4000)
            return
        what, seg = done
        self._pick_after_edit(item, seg)
        self.status(f"{item.label}: {'다시 실행' if redo else '되돌림'} · {what}", 5000)

    def delete_selected(self) -> None:
        """Delete: the picked label segment while the timeline or the segment list has the focus, else the
        selected motion."""
        fw = QApplication.focusWidget()
        here = fw is not None and (fw is self.timeline.tracks or self.inspector.isAncestorOf(fw))
        if here and self.label_selection() is not None:
            self.label_delete()
        else:
            self.remove(self.selected)

    def label_menu(self, m: QMenu, it: Item, seg) -> None:
        """A picked segment's entries (timeline and segment list right-click)."""
        for a in (self.a_rename, self.a_split, self.a_merge_prev, self.a_merge_next, self.a_start_here, self.a_end_here,
                  self.a_delete_seg):
            m.addAction(a)

    def _refresh_label_actions(self) -> None:
        undo, redo = self.scene.label_undo_text(self.selected)
        self.a_undo.setText(f"되돌리기: {undo}" if undo else "되돌리기")
        self.a_redo.setText(f"다시 실행: {redo}" if redo else "다시 실행")
        self.a_undo.setEnabled(undo is not None)
        self.a_redo.setEnabled(redo is not None)
        picked = self.label_selection() is not None
        for a in (self.a_rename, self.a_split, self.a_merge_prev, self.a_merge_next, self.a_start_here, self.a_end_here,
                  self.a_delete_seg):
            a.setEnabled(picked)
        self.a_add_seg.setEnabled(self.selected is not None)
        lab = self.selected.labels if self.selected is not None else None
        self.a_save_labels.setEnabled(lab is not None and (bool(lab.segments) or lab.edited))

    def _confirm_discard_labels(self, items: list[Item], action: str) -> bool:
        """Unsaved label edits on these motions: save them (each to a CSV), let them go, or not do it at all."""
        dirty = [it for it in items if self.scene.labels_dirty(it)]
        if not dirty or not self.confirm_unsaved:
            return True
        names = ", ".join(it.label for it in dirty[:5]) + (f" 외 {len(dirty) - 5}개" if len(dirty) > 5 else "")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("저장하지 않은 라벨 편집")
        box.setText(f"{names}의 라벨을 고친 내용이 아직 저장되지 않았습니다. {action} 고친 내용이 사라집니다.")
        save = box.addButton("저장...", QMessageBox.AcceptRole)
        drop = box.addButton("저장하지 않음", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return all(self.save_labels_dialog(it) for it in dirty)
        return box.clickedButton() is drop

    def motion_menu(self, m: QMenu, it: Item) -> None:
        """A motion's right-click menu (계층, 타임라인)."""
        m.addAction("동영상 저장", lambda: self.save_video(it))
        if self.scene.video_file(it):
            m.addAction("저장된 동영상 열기", lambda: self.open_path(self.scene.video_file(it)))
        m.addAction("파일 위치 열기", lambda: self.open_path(os.path.dirname(it.source)))
        m.addAction("로봇 모션 내보내기...", lambda: self.export_motion(it))
        m.addSeparator()
        self.add_label_actions(m.addMenu("라벨"), it)
        m.addSeparator()
        m.addAction("겹쳐 비교: 기준(A)으로", lambda: self.start_compare(ref=it))
        m.addAction("겹쳐 비교: 대상(B)으로", lambda: self.start_compare(item=it))
        m.addSeparator()
        m.addAction("제거", lambda: self.remove(it))

    def export_motion(self, it: Item) -> None:
        """로봇 모션 내보내기 (retlens.dataset.export_motion): this motion's robot motion, or a range of it, with problems
        cut out, its labels (as in the window) and a .json each."""
        sc = self.scene
        sel = self.label_selection()
        seg = sel[2] if sel is not None and sel[0] is it else None
        shown = sc.shown(it)
        falls = [t for t, _c in sc.falls(it) if t <= it.robot.duration] if shown is not it else None
        stem = os.path.splitext(os.path.basename(it.source))[0]
        dlg = export_dialogs.MotionExportDialog(
            self, self.settings, it.label, it.robot.duration,
            (f"{seg.track}: {seg.label}" if seg.track else seg.label, seg.start, seg.end) if seg is not None else None,
            None if falls is None else len(falls), os.path.dirname(it.source))
        if dlg.exec() != QDialog.Accepted:
            return
        out = dlg.folder.path()
        if not export_dialogs.confirm_folder(self, out, "로봇 모션 내보내기"):
            return
        try:
            res = dataset.export_motion(
                it.robot, out, stem, labels=it.labels if dlg.labels.isChecked() else None, cut=dlg.cut.value(),
                qc_bad=dataset.qc_bad_spans(it.robot, sc.limits), problems=it.metrics.get("_problems") or {},
                falls=falls or [], range_s=dlg.range_s(), formats=dlg.formats.value(), limits=sc.limits,
                info={"retarget": it.retarget or None, "kind": it.kind, "source_sha256": dataset.sha256(it.source)})
        except Exception as e:
            QMessageBox.warning(self, "로봇 모션 내보내기", f"{type(e).__name__}: {e}")
            return
        n = len(res["pieces"])
        secs = sum(p["duration_s"] for p in res["pieces"])
        text = f"파일 {n}개 · {secs:.1f}초"
        if res["cut_s"] or res["short_s"]:
            text += f"\n잘라 낸 {res['cut_s']:.1f}초, 짧아서 버린 {res['short_s']:.1f}초"
        if res["pieces"]:
            text += "\n\n" + "\n".join(os.path.basename(p["files"][0]) for p in res["pieces"][:12])
            text += f"\n외 {n - 12}개" if n > 12 else ""
        self.status(f"로봇 모션 내보내기: {it.label} → {out} ({n}개)", 8000)
        export_dialogs.report(self, "로봇 모션 내보내기", f"{out}\n\n{text}", out, self.open_path)

    # ---------------------------------------------------------------- labels (retlens.motion_labels)
    def add_label_actions(self, m: QMenu, it: Item) -> None:
        """라벨 entries of a motion (the right-click menu's 라벨, the inspector's ⋯)."""
        sc, lab = self.scene, it.labels
        m.addAction("라벨 불러오기...", lambda: self.load_labels_dialog(it))
        if lab is not None and lab.path:
            m.addAction("라벨 다시 읽기", lambda: self.reload_labels(it))
            m.addAction("규칙 파일 열기" if lab.auto else "라벨 파일 열기", lambda: self.open_path(lab.path))
        else:  # its own label file may have been put next to it since
            m.addAction("라벨 파일 다시 찾기", lambda: self.reload_labels(it))
        if lab is not None:
            m.addAction("라벨 빼기", lambda: sc.set_labels(it, None))
        if sc.has_skeleton(it):
            m.addAction("자동 라벨 붙이기", lambda: self.auto_label(it))
        if len(sc.items) > 1:
            m.addAction("열린 모션 모두 자동 라벨", self.auto_label_all)
        m.addAction("자동 라벨 규칙 파일 고르기...", lambda: self.pick_label_rules(it if sc.has_skeleton(it) else None))
        m.addSeparator()
        m.addAction("새 라벨 트랙...", lambda: self.label_new_track(it))
        if lab is not None and (lab.segments or lab.edited):
            m.addAction("라벨 CSV로 저장...", lambda: self.save_labels_dialog(it))

    def reload_labels(self, it: Item) -> None:
        """다시 읽기: the label file, or the automatic labels made again (a failure is said, labels kept)."""
        lab = it.labels
        if lab is not None and lab.auto:  # made again off the GUI thread
            self.auto_label(it, lab.path or None)
            return
        self._show_labels_result(it, self.scene.reload_labels(it))

    def pick_label_rules(self, it: Item | None = None) -> str:
        """Pick the 자동 라벨 rule file (kept in the settings); labels `it` with it when given. The
        dialog starts at the current file, else the user's documents: a project's rules belong
        outside this repository (configs/ holds only the example)."""
        cur = autolabel.rules_file()
        start = cur if cur else app_paths.documents_dir()
        path, _ = QFileDialog.getOpenFileName(self, f"자동 라벨 규칙 파일 (예시: {os.path.normpath(autolabel.EXAMPLE)})",
                                              start, "규칙 파일 (*.yaml *.yml *.json);;모든 파일 (*)")
        if not path:
            return ""
        s = settings.load(reload=True)
        s.label_rules = os.path.normpath(path)
        settings.save(s)
        self.status(f"자동 라벨 규칙: {s.label_rules}", 8000)
        if it is not None:
            self.auto_label(it, s.label_rules)
        return s.label_rules

    def auto_label(self, it: Item, rules: str | None = None) -> None:
        """Label the motion by the rule file (picked first when none is set or it is gone)."""
        rules = rules or autolabel.rules_file()
        if not rules or not os.path.isfile(rules):
            if rules:
                QMessageBox.warning(self, "자동 라벨", f"규칙 파일이 없습니다:\n{rules}\n\n다른 파일을 고르세요.")
            self.pick_label_rules(it)  # labels it once a file is picked
            return
        self._label_off_gui([it], rules)

    def auto_label_all(self) -> None:
        rules = autolabel.rules_file()
        if not rules or not os.path.isfile(rules):
            rules = self.pick_label_rules()
            if not rules:
                return
        try:  # a broken rule file: said once, and no motion's labels change
            autolabel.check_rules(rules)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "자동 라벨", f"규칙 파일을 쓸 수 없습니다. 라벨은 그대로입니다.\n\n{rules}\n{e}")
            return
        human = [it for it in self.scene.items if self.scene.has_skeleton(it)]  # robot motions keep their labels
        if human:
            self._label_off_gui(human, rules, skipped=len(self.scene.items) - len(human))

    def _label_off_gui(self, items: list[Item], rules: str, skipped: int | None = None) -> None:
        """Make the motions' automatic labels in a worker (an AMASS take or a C3D's solved take takes a
        second or more to load) and put each on its motion on the GUI thread (_on_labelled), unless it
        was removed or labelled again meanwhile. skipped: 모두 자동 라벨, said at the end with the
        robot motions it left as they were; None: one motion, said as any labels are."""
        job = {"items": items, "done": [], "skipped": skipped, "base": {it: it.labels for it in items}}
        for it in items:
            self._label_jobs[it] = job  # a later request for the motion wins over this one
        self.status(f"자동 라벨 계산 중: {items[0].label}" + (f" 외 {len(items) - 1}개" if len(items) > 1 else ""))

        def work():
            for it in items:
                self.bridge.labelled.emit((job, it, self.scene.make_auto_labels(it, rules)))

        threading.Thread(target=work, daemon=True, name="auto-label").start()

    def _on_labelled(self, payload) -> None:
        job, it, lab = payload
        job["done"].append((it, lab))
        if self._label_jobs.get(it) is job:
            del self._label_jobs[it]
            if self.scene.labels_dirty(it) and it.labels is not job["base"].get(it):  # edited meanwhile: kept
                self.status(f"{it.label}: 자동 라벨을 계산하는 동안 라벨을 고쳐, 계산 결과는 붙이지 않았습니다", 8000)
            elif any(x is it for x in self.scene.items):
                self.scene.put_auto_labels(it, lab)
                if job["skipped"] is None:
                    self._show_labels_result(it, lab)
        if job["skipped"] is None or len(job["done"]) < len(job["items"]):
            return
        bad = [f"{x.label}: {lb.error}" for x, lb in job["done"] if lb.error]
        n, skipped = len(job["done"]) - len(bad), job["skipped"]
        self.status(f"자동 라벨: 모션 {n}개" + (f", 붙이지 못한 모션 {len(bad)}개" if bad else "")
                    + (f", 사람 골격이 없는 로봇 모션 {skipped}개는 그대로" if skipped else ""), 10000)
        if bad:
            QMessageBox.warning(self, "자동 라벨", "자동 라벨을 붙이지 못한 모션은 라벨이 그대로입니다.\n\n" + "\n".join(bad[:10])
                                + (f"\n… 외 {len(bad) - 10}개" if len(bad) > 10 else ""))

    def save_labels_dialog(self, it: Item) -> bool:
        """Save the motion's labels to a CSV (next to it as <name>.labels.csv: opened with it next time). Never
        over a table of several motions or another kind of file; over the file they came from only when the user
        says so. True when saved."""
        base = it.labels
        if base is None:
            self.status(f"{it.label}: 저장할 라벨이 없습니다", 4000)
            return False
        stem = os.path.splitext(os.path.basename(it.source))[0]
        start = os.path.join(os.path.dirname(it.source), f"{stem}.labels.csv")
        path, _ = QFileDialog.getSaveFileName(self, f"라벨 저장 - {it.label}", start, "라벨 CSV (*.csv)",
                                              options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return False
        if not path.lower().endswith(".csv"):
            path += ".csv"
        solved = it.info.get("solved_motion")
        why = motion_labels.overwrite_problem(path, it.source, [solved] if solved else ())
        if why:
            QMessageBox.warning(self, "라벨 저장", f"이 파일에는 저장하지 않습니다:\n{path}\n\n{why}\n\n다른 이름을 고르세요.")
            return False
        if os.path.exists(path):
            loaded = bool(base.path) and not base.auto and not base.error and _path_key(path) == _path_key(base.path)
            losses = motion_labels.overwrite_losses(path, base)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("라벨 덮어쓰기")
            box.setText(("이 모션이 불러온 라벨 파일입니다" if loaded else "이미 있는 파일입니다") + f":\n{path}\n\n"
                        "지금 라벨로 덮어쓸까요? 원래 내용은 되돌릴 수 없습니다 (Ctrl+Z는 창 안의 라벨만 되돌립니다)."
                        + ("\n\n덮어쓰면 잃는 것:\n" + "\n".join(f"· {x}" for x in losses) if losses else ""))
            yes = box.addButton("덮어쓰기", QMessageBox.AcceptRole)
            box.addButton("취소", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return False
        try:
            motion_labels.save_csv(base, path)
        except OSError as e:
            QMessageBox.warning(self, "라벨 저장", f"저장하지 못했습니다 (엑셀 등에서 열려 있으면 닫고 다시 하세요):\n{e}")
            return False
        self.scene.labels_saved(it, base, path)
        first = next((p for p in motion_labels.candidates(it.source, [solved] if solved else ())
                      if os.path.isfile(p) and os.path.basename(p).lower() not in motion_labels.FOLDER_TABLES), None)
        note = (f" · 다음에 열 때는 {os.path.basename(first)}이(가) 먼저 붙습니다"
                if first is not None and _path_key(first) != _path_key(path) else "")
        self.status(f"라벨 저장: {path}{note}", 12000)
        return True

    def load_labels_dialog(self, it: Item) -> None:
        lab = it.labels
        start = os.path.dirname(lab.path if lab is not None and lab.path and not lab.auto else it.source)
        path, _ = QFileDialog.getOpenFileName(self, f"라벨 파일 - {it.label}", start,
                                              "라벨 파일 (*.csv *.json);;모든 파일 (*)")
        if path:
            self._show_labels_result(it, self.scene.set_labels(it, path))

    def attach_label_files(self, files: list[str]) -> None:
        """Dropped label files: each onto the open motion it is named after (02_01.labels.csv ->
        02_01; of several, the one in the label file's folder, else the selected one, else the
        first), else onto the selected motion."""
        for f in files:
            by_source = {_path_key(x.source): x for x in self.scene.items}
            motion = _motion_for_label(f, [x.source for x in self.scene.items],
                                       self.selected.source if self.selected is not None else None)
            it = by_source[_path_key(motion)] if motion is not None else self.selected
            if it is None:
                self.status(f"라벨을 붙일 모션이 없습니다: {os.path.basename(f)} (모션을 먼저 열거나 고르세요)", 10000)
                continue
            self._show_labels_result(it, self.scene.set_labels(it, f))

    def _show_labels_result(self, it: Item, lab) -> None:
        self.select(it)
        if lab is not None and lab.auto and lab.error:
            QMessageBox.warning(self, "자동 라벨", f"{it.label}에 자동 라벨을 붙이지 못했습니다. 라벨은 그대로입니다.\n\n"
                                                f"{lab.error}\n\n규칙 파일 형식은 사용 설명서의 '자동 라벨'에 있습니다.")
        elif lab is not None and lab.error:
            QMessageBox.warning(self, "라벨", f"{os.path.basename(lab.path)}을(를) {it.label}에 붙이지 못했습니다.\n\n"
                                            f"{lab.error}\n\n열 이름과 형식은 사용 설명서의 '구간 라벨'에 있습니다.")
        elif lab is not None and lab.auto:
            self.status(f"자동 라벨: {it.label}에 구간 {len(lab.segments)}개 ({lab.auto})", 8000)
        elif lab is not None:
            self.status(f"라벨: {it.label}에 구간 {len(lab.segments)}개 ({os.path.basename(lab.path)})", 8000)

    @staticmethod
    def _run_on_gui(fn) -> None:
        fn()

    # ---------------------------------------------------------------- 이 모션의 보정 (B1)
    def retarget_item(self, item: Item, foot_flat: bool, swing_clearance_cm: float, self_collision: bool) -> None:
        """다시 리타게팅 with these corrections in the background; the new motion takes the old one's place."""
        if item.handles.get("ui_busy"):
            return
        item.handles["ui_busy"] = True
        self.status(f"{item.label}: 다시 리타게팅 중 ({retarget_text(foot_flat, swing_clearance_cm, self_collision)}; "
                    "처음 쓰는 보정이면 수십 초)")

        def work():
            try:
                new = self.scene.retarget_again(item, foot_flat, swing_clearance_cm, self_collision)
                done = lambda: (self.select(new), self.status(  # noqa: E731
                    f"{new.label}: 다시 리타게팅함 · 점수 {item.metrics.get('retarget_score', 0):.0f} → "
                    f"{new.metrics.get('retarget_score', 0):.0f}", 10000))
            except Exception as e:
                item.handles.pop("ui_busy", None)
                done = lambda e=e: self.status(f"{item.label}: 다시 리타게팅하지 못함 ({type(e).__name__}: {e})", 10000)  # noqa: E731
            self.bridge.gui.emit(done)

        threading.Thread(target=work, daemon=True, name="retarget-again").start()

    def recommend_retarget(self, item: Item) -> None:
        """추천 보정: the 8 combinations of corrections in the background, ranked by score; offers the best."""
        if item.handles.get("ui_busy"):
            return
        item.handles["ui_busy"] = True

        def progress(done, total, text):
            self.bridge.gui.emit(lambda: self.status(f"{item.label}: 추천 보정 찾는 중 {done}/{total}"
                                                     + (f" ({text})" if text else "")))

        def work():
            try:
                ranked = self.scene.recommend_retarget(item, progress)
                done = lambda: self._offer_recommendation(item, ranked)  # noqa: E731
            except Exception as e:
                done = lambda e=e: self.status(f"{item.label}: 추천 보정을 찾지 못함 ({type(e).__name__}: {e})", 10000)  # noqa: E731
            item.handles.pop("ui_busy", None)
            self.bridge.gui.emit(done)

        threading.Thread(target=work, daemon=True, name="recommend-retarget").start()

    def _offer_recommendation(self, item: Item, ranked: list[dict]) -> None:
        r = item.retarget
        now = retarget_text(r.get("foot_flat", False), r.get("swing_clearance_cm", 0.0), r.get("self_collision", False))
        best = ranked[0]
        lines = "\n".join(f"{c['score']:.0f}점  {c['text']}" if c["score"] is not None else f"-  {c['text']}" for c in ranked)
        box = QMessageBox(self)
        box.setWindowTitle("추천 보정")
        box.setText(f"{item.label}\n\n지금: {now} · {item.metrics.get('retarget_score', 0):.0f}점\n"
                    f"추천: {best['text']} · {best['score']:.0f}점\n\n보정 조합별 리타게팅 점수:\n{lines}")
        apply = box.addButton("추천 보정으로 다시 리타게팅", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        if best["text"] == now:
            apply.setEnabled(False)
        box.exec()
        if box.clickedButton() is apply and item in self.scene.items:
            self.retarget_item(item, best["foot_flat"], best["swing_clearance_cm"], best["self_collision"])

    def goto_problem(self, direction: int) -> None:
        """다음 / 이전 문제로: the selected motion's problems, or every visible motion's when none is selected."""
        stop = self.scene.next_problem(direction, self.selected)
        if stop is None:
            self.status(f"{'다음' if direction > 0 else '이전'} 문제가 없습니다"
                        + (f" ({self.selected.label})" if self.selected is not None else ""), 4000)
        else:
            t, kind, it = stop
            self.status(f"{it.label}: {PROBLEM_NAMES.get(kind, kind)} {t - it.offset:.2f}s", 6000)

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
                    self.bridge.added.emit((p, f"{os.path.basename(p)}: {type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True, name="add-motion").start()

    def _on_added(self, result) -> None:
        self._loading = max(0, self._loading - 1)
        if isinstance(result, Item):
            self.status(f"추가됨: {result.label}", 5000)
            self.select(result)
            pending = self._pending_labels.pop(_path_key(result.source), None)
            if pending:  # dropped together with this very file
                f = _pick_label_file(pending, result.source)
                self._show_labels_result(result, self.scene.set_labels(result, f))
                if len(pending) > 1:  # a motion shows one label file
                    self.status(f"라벨 파일 {len(pending)}개를 함께 놓아 {os.path.basename(f)}만 {result.label}에 붙였습니다", 10000)
            if len(self.scene.items) == 1 or self._loading == 0:
                self.scene.fit_camera()
        else:
            path, result = result  # (the file, why it did not open)
            self._pending_labels.pop(_path_key(path), None)  # its label file goes nowhere else
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
            files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
            sessions = [f for f in files if work.is_session_file(f)]
            if sessions:  # a work session: that, alone; after the drop (its questions would hold up Explorer)
                if len(files) > 1:
                    self.status("작업 세션 파일과 함께 놓은 다른 파일은 열지 않았습니다", 8000)
                QTimer.singleShot(0, lambda p=sessions[0]: self.open_session(p))
                return
            labels = [f for f in files if motion_labels.is_label_file(f)]  # before motions: a label table is a .csv
            paths = [f for f in files if f not in labels and f.lower().endswith(MOTION_EXT)]
            alone, opened = [], [x.source for x in self.scene.items]
            for f in labels:  # dropped with its motion: attached to that file once it has loaded (_on_added)
                motion = _motion_for_label(f, paths)
                if motion is None and len(paths) == 1 and _motion_for_label(f, opened) is None:
                    motion = paths[0]  # named after no motion, dropped with one: for that one
                if motion is not None:
                    self._pending_labels.setdefault(_path_key(motion), []).append(f)
                else:
                    alone.append(f)
            self.attach_label_files(alone)
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
                                     (f"스윙 발 {r['swing_clearance_cm']:g} cm", r["swing_clearance_cm"] > 0),
                                     ("자기 관통", r["self_collision"])) if yes]
        self.status(f"리타게팅 보정: {', '.join(on) or '끔'}. {RETARGET_NOTE}", 10000)

    def _sync_retarget(self) -> None:
        """The 리타게팅 menu shows the scene's settings (the API can change them too)."""
        o = self.scene.opts
        if o.swing_clearance_cm > 0 and o.swing_clearance_cm != self._swing_cm:
            self._swing_cm = o.swing_clearance_cm
            self.a_swing.setText(f"스윙 발 보정 ({self._swing_cm:g} cm)")
        for a, on in ((self.a_foot_flat, o.foot_flat), (self.a_swing, o.swing_clearance_cm > 0),
                      (self.a_self_collision, o.self_collision)):
            if a.isChecked() != on:
                a.blockSignals(True)
                a.setChecked(on)
                a.blockSignals(False)

    def _refresh_balance_entries(self) -> None:
        """Labels and tips of the 균형 제어 menu: '(설치 필요)' on a mode that cannot run yet."""
        for key, label in BALANCE.items():
            why = self.scene.balance_problem(key)
            tip = f"아직 쓸 수 없음: {why}" if why else BALANCE_TIPS[key]
            a = self.a_balance[key]
            a.setText(label + (" (설치 필요)" if why else ""))
            a.setToolTip(tip)
            a.setStatusTip(tip)

    def _balance_ready(self, mode: str) -> bool:
        """What the mode needs is there (Isaac: installed and its EULA accepted; MuJoCo: the G1 model, and
        GMT's policy for GMT);
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
            self.a_remove_all.setEnabled(bool(self.scene.items))
            self._refresh_label_actions()
            self.hierarchy.rebuild()
            self.analysis.refresh_lists()
            self.scene_settings.refresh()
            self.timeline.relayout()
            self.refresh_analysis()
        elif event in ("item", "status"):
            if event == "item":
                self.timeline.relayout()  # labels may have added or removed lanes
            self.hierarchy.refresh()
            self.refresh_analysis()  # the inspector too
            self._refresh_status()
        elif event == "labels":  # edited, loaded or taken off: only what shows labels
            self.timeline.relayout()
            self.inspector.refresh(metrics=False)
            self._refresh_label_actions()
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
        self.st_physics.setVisible(sc.physics_on)
        self.st_physics.setText(sc.physics_status())
        self.st_physics.setToolTip("\n".join(f"{it.label}: {sc.job_text(it)}" for it in list(sc.items)
                                             if not sc.is_sim_result(it)) if sc.physics_on else "")
        jobs = sc.jobs_summary()
        r = self._restore
        if r is not None:  # a work session opening
            jobs = " · ".join(x for x in (f"작업 세션 {r.done}/{r.total}", jobs) if x)
        self.st_jobs.setText(f"작업: {jobs}")
        for w in (self.st_jobs, self.st_cancel):
            w.setVisible(bool(jobs))
        self.a_cancel.setEnabled(bool(jobs))
        for a in (self.a_session_save, self.a_session_save_as):
            a.setEnabled(r is None)
        if self.a_physics.isChecked() != sc.physics_on:
            self.a_physics.blockSignals(True)
            self.a_physics.setChecked(sc.physics_on)
            self.a_physics.blockSignals(False)
        self.a_physics.setToolTip(f"물리 모드 (P) · 균형 제어: {BALANCE.get(sc.balance, sc.balance)}. ▾에서 바꿉니다")
        for val, a in self.a_assist.items():
            a.setChecked(val == sc.assist)
        self.m_assist.menuAction().setVisible(sc.balance == "isaac")  # Isaac's own setting
        for key, a in self.a_balance.items():
            a.setChecked(key == sc.balance)
        self._sync_retarget()

    def _refresh_all(self) -> None:
        self.hierarchy.rebuild()
        self.analysis.refresh_lists()
        self.scene_settings.refresh()
        self.a_remove_all.setEnabled(bool(self.scene.items))
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
        if self._play_icon != sc.playing:
            self._play_icon = sc.playing
            self.a_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause if sc.playing else QStyle.SP_MediaPlay))
        self.analysis.update_view()  # follows the playhead; skipped when the 분석 tab is not on screen
        self.compare_panel.update_live()
        if sc.jobs_busy() and int(now * 2) != int(prev * 2):  # job progress, twice a second
            self.hierarchy.refresh()
            self.inspector.refresh(metrics=False)
            self._refresh_status()
        if int(now) != int(prev):  # once a second: the title's *, 자동 저장 every AUTOSAVE_S
            self._update_title()
            if time.time() - self._autosave_at > self.AUTOSAVE_S:
                self._autosave_at = time.time()
                self.autosave()

    _play_icon = None

    # ---------------------------------------------------------------- 작업 세션 (retlens/app/session.py)
    # The window's work in one file: the open motions (corrections, time offset, visibility, labels with unsaved
    # edits), the comparison, scene settings, physics mode, the playhead. Opening one runs in a worker (motions
    # retarget); 자동 저장 keeps the last work (on close, and every 2 minutes) for 최근 작업 세션 > 마지막 작업.
    session_path: str | None = None  # the session file open (None: untitled)
    _session_clean = None  # session.fingerprint when it was last saved / opened (None: changed)
    _restore = None  # the session.Restore running
    _restore_cancel = False
    _autosave_fp = None
    _autosave_at = 0.0
    AUTOSAVE_S = 120.0
    RECENT_MAX = 8

    def _carry_list(self) -> list:
        return getattr(self, "_carry", [])

    def _session_dirty(self) -> bool:
        if self._restore is not None:
            return False
        return work.fingerprint(self.scene, self._carry_list()) != self._session_clean

    def _update_title(self) -> None:
        name = os.path.basename(self.session_path) if self.session_path else ""
        title = f"{name}[*] - {APP_NAME}" if name else APP_NAME
        if self.windowTitle() != title:
            self.setWindowTitle(title)
        self.setWindowModified(bool(name) and self._session_dirty())

    def _session_base(self, path: str | None) -> str | None:
        return os.path.dirname(os.path.abspath(path)) if path else None

    def capture_session(self, base_dir: str | None) -> dict:
        """The session to write: the scene's (session.capture) and the window's own fields."""
        data = work.capture(self.scene, base_dir, self._carry_list())
        items = list(self.scene.items)
        data["selected"] = items.index(self.selected) if self.selected in items else None
        ref = self.analysis.ref_item()
        data["analysis"] = {"ref": items.index(ref) if ref in items else None, "graph": self.analysis.key.currentText(),
                            "follow_s": self.analysis.follow.currentData()}
        return data

    def save_session(self, path: str | None = None) -> bool:
        """작업 세션 저장 (untitled: 다른 이름으로). Unsaved label edits go into the session file (not to CSVs)."""
        if self._restore is not None:
            self.status("작업 세션을 여는 중에는 저장할 수 없습니다", 5000)
            return False
        path = path or self.session_path
        if path is None:
            return self.save_session_as()
        try:
            path = work.write(path, self.capture_session(self._session_base(path)))
        except OSError as e:
            QMessageBox.warning(self, "작업 세션 저장", f"저장하지 못했습니다:\n{path}\n\n{e}")
            return False
        self.session_path = path
        self._session_clean = work.fingerprint(self.scene, self._carry_list())
        self._recent_add(path)
        self._update_title()
        self.status(f"작업 세션 저장: {path}", 8000)
        return True

    def save_session_as(self) -> bool:
        start = self.session_path or os.path.join(
            self.settings.value(layout_key("session/dir"), "") or os.path.join(app_paths.documents_dir(), "sessions"),
            f"세션_{time.strftime('%Y%m%d_%H%M')}{work.EXT}")
        os.makedirs(os.path.dirname(start), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "작업 세션 저장", start, f"RetLens 작업 세션 (*{work.EXT})")
        if not path:
            return False
        if not path.lower().endswith(work.EXTS):
            path += work.EXT
        self.settings.setValue(layout_key("session/dir"), os.path.dirname(path))
        return self.save_session(path)

    def _confirm_session(self, action: str) -> bool:
        """A session file open with changes: save them, let them go, or not do it."""
        if not self.session_path or not self._session_dirty() or not self.confirm_unsaved:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("작업 세션")
        box.setText(f"'{os.path.basename(self.session_path)}'에 저장하지 않은 변경이 있습니다. {action} 전에 저장할까요?")
        save = box.addButton("저장", QMessageBox.AcceptRole)
        drop = box.addButton("저장 안 함", QMessageBox.DestructiveRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save_session()
        return box.clickedButton() is drop

    def autosave(self, force: bool = False) -> None:
        """자동 저장 (user folder sessions\autosave.retlens): the work as it is, kept until other work replaces it
        (the one before stays as autosave.1). Skipped while a session opens, for an empty window, for smoke runs."""
        if self._restore is not None or not self.confirm_unsaved or not (self.scene.items or self._carry_list()):
            return
        fp = work.fingerprint(self.scene, self._carry_list())
        if not force and fp == self._autosave_fp:
            return
        base = self._session_base(self.session_path)
        try:
            work.write_autosave(self.capture_session(base), self._session_dirty(), self.session_path, self._work)
            self._autosave_fp, self._autosave_at = fp, time.time()
        except OSError as e:  # never in the way of closing
            self.scene.log(f"자동 저장 못 함: {type(e).__name__}: {e}")

    _work = None  # this work's token (session.write_autosave keeps another work's autosave as autosave.1)

    def _new_work(self) -> None:
        self._work = os.urandom(6).hex()

    def open_session_dialog(self) -> None:
        start = self.settings.value(layout_key("session/dir"), "") or os.path.join(app_paths.documents_dir(), "sessions")
        path, _ = QFileDialog.getOpenFileName(self, "작업 세션 열기", start,
                                              f"RetLens 작업 세션 (*{work.EXT} *.retlens.json);;모든 파일 (*)")
        if path:
            self.settings.setValue(layout_key("session/dir"), os.path.dirname(path))
            self.open_session(path)

    def open_session(self, path: str, mode: str | None = None, interactive: bool = True, discard: bool = False,
                     autosave_of: dict | None = None) -> tuple[int, str]:
        """Open a session: (0, '') when it started, else (HTTP-like code, why). mode replace (닫고 열기) / add
        (함께 열기); asked when motions are open (interactive), else needed. autosave_of: reopening 자동 저장
        (its session file becomes the title, its unsaved state comes back)."""
        try:
            data = work.read(path)
        except work.SessionError as e:
            if interactive:
                QMessageBox.warning(self, "작업 세션 열기", str(e))
            return 400, str(e)
        if self._restore is not None:
            if interactive:
                self.status("작업 세션을 여는 중입니다. 끝나거나 취소한 뒤 다시 하세요", 6000)
            return 409, "a work session is being opened"
        if self.scene.items and mode is None:
            if not interactive:
                return 409, "motions are open: give mode replace or add"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("작업 세션 열기")
            jobs = self.scene.jobs_summary()
            box.setText(f"열린 모션 {len(self.scene.items)}개를 어떻게 할까요?")
            box.setInformativeText("함께 열기는 세션의 모션만 더하고, 씬 설정·물리 모드·겹쳐 비교는 지금 것을 둡니다."
                                   + (f"\n닫고 열면 실행 중인 작업({jobs})은 취소됩니다." if jobs else ""))
            replace = box.addButton("닫고 열기", QMessageBox.AcceptRole)
            add = box.addButton("함께 열기", QMessageBox.AcceptRole)
            box.addButton("취소", QMessageBox.RejectRole)
            box.exec()
            mode = "replace" if box.clickedButton() is replace else "add" if box.clickedButton() is add else None
            if mode is None:
                return 499, "cancelled"
        mode = mode or "replace"
        if mode == "replace":
            if interactive and not self._confirm_session("다른 작업 세션을 열기"):
                return 499, "cancelled"
            if interactive and not self.session_path and \
                    not self._confirm_discard_labels(list(self.scene.items), "다른 작업 세션을 열면"):
                return 499, "cancelled"
            if not interactive and not discard and (self.session_path and self._session_dirty()):
                return 409, "the open work session has unsaved changes: save it first or give discard_changes"
            if not interactive and not discard and not self.session_path and \
                    any(self.scene.labels_dirty(it) for it in self.scene.items):
                return 409, "labels have unsaved edits: save them first or give discard_changes"
            self.autosave(force=True)  # the work it replaces stays as 마지막 작업
        # relative paths start at the session file's folder; an autosave's at the folder of the session it was of
        base = self._session_base(autosave_of.get("session_path")) if autosave_of is not None else self._session_base(path)
        r = work.Restore(data, base, mode)
        self._restore, self._restore_cancel = r, False
        if mode == "replace":
            self.label_sel, self._carry = None, []
            self.session_path = (autosave_of or {}).get("session_path") if autosave_of is not None else path
            if self.session_path and not os.path.isfile(self.session_path):
                self.session_path = None
            self._new_work()
        self._restore_title = os.path.basename(path)
        self._restore_interactive = interactive
        self._restore_autosave = autosave_of
        ready = (self._physics_ready_gui if interactive else work.mujoco_ready(self.scene))

        def progress(done, total, label):
            self.bridge.gui.emit(lambda: self._restore_progress(r, done, total, label))

        def run():
            try:
                r.run(self.scene, cancelled=lambda: self._restore_cancel or r is not self._restore,
                      progress=progress, physics_ready=ready)
            except Exception as e:  # noqa: BLE001  said at the end; what opened stays
                r.notes.append(f"작업 세션을 다 열지 못했습니다: {type(e).__name__}: {e}")
            finally:
                self.bridge.gui.emit(lambda: self._finish_restore(r))

        threading.Thread(target=run, daemon=True, name="session-open").start()
        self.status(f"작업 세션 여는 중: {os.path.basename(path)}")
        self._refresh_status()
        return 0, ""

    def _physics_ready_gui(self, balance: str) -> str:
        """session.Restore's physics_ready for a session the user opens: what that 균형 제어 needs, asked on the
        GUI thread (the Isaac EULA, the setup assistant); '' when it may be turned on."""
        return "" if self._gui_call(lambda: self._balance_ready(balance)) else "필요한 것이 없거나 동의하지 않음"

    _restore_seen = None

    def _restore_progress(self, r, done: int, total: int, label: str) -> None:
        if r is not self._restore:
            return
        if self._restore_seen is not r:  # the first call: the session's scene settings are in the scene now
            self._restore_seen = r
            self._settings_from_scene()
        self.status(f"작업 세션 여는 중 {done}/{total}" + (f": {label} (처음 리타게팅하는 사람 모션이면 수십 초)" if label else ""))
        self._refresh_status()

    def _settings_from_scene(self) -> None:
        """The panels that keep their own copy of the scene's settings, from the scene again (a session put them)."""
        old = self.scene_settings
        self.scene_settings = SceneSettingsPanel(self)
        self.docks["scene"].setWidget(self.scene_settings)
        old.deleteLater()
        self.a_show_problems.setChecked(self.scene.view.show_problems)
        self._refresh_status()
        self.compare_panel.refresh()

    def _finish_restore(self, r) -> None:
        if r is not self._restore:
            return
        self._restore = None
        self._settings_from_scene()
        if r.mode == "replace":
            sel = r.item_at(r.selected) or (self.scene.items[-1] if self.scene.items else None)
            self.select(sel)
            a = r.analysis or {}
            ref = r.item_at(a.get("ref"))
            if ref is not None:
                self.analysis.ref.setCurrentIndex(self.analysis.ref.findData(id(ref)))
            if a.get("graph") and self.analysis.key.findText(a["graph"]) >= 0:
                self.analysis.key.setCurrentText(a["graph"])
            i = self.analysis.follow.findData(a.get("follow_s"))
            if i >= 0:
                self.analysis.follow.setCurrentIndex(i)
            if not r.data.get("camera"):
                self.scene.fit_camera()
        self._carry = self._carry_list() + r.carry()
        auto = self._restore_autosave
        if r.mode == "replace":
            dirty = (bool(auto.get("dirty")) if auto is not None else False) or not self._restored_as_saved(r)
            self._session_clean = None if dirty else work.fingerprint(self.scene, self._carry_list())
            self._autosave_fp = work.fingerprint(self.scene, self._carry_list())
            if r.cancelled:  # part of it: saving must not write that part over the session file
                self.session_path, self._session_clean = None, None
        if auto is None and r.mode == "replace" and self.session_path:
            self._recent_add(self.session_path)
        self._remember_restore(r)
        self._update_title()
        self._refresh_status()
        n = len(r.items)
        more = len(r.failed) + (len(r.pending()) if r.cancelled else 0)
        self.status(f"작업 세션을 {'열었습니다' if not r.cancelled else '여는 중에 멈췄습니다'}: {self._restore_title} · "
                    f"모션 {n}개" + (f" · 열지 못함 {more}개" if more else "")
                    + (f" · 알림 {len(r.notes)}개 (콘솔)" if r.notes and not self._restore_interactive else ""), 15000)
        if self._restore_interactive and (r.failed or r.notes or (r.cancelled and r.pending())):
            self._restore_report(r)

    def _restored_as_saved(self, r) -> bool:
        """Nothing changed while the session opened (it takes minutes; the motions show as they load): the motions
        are the ones it opened, each as its entry says and not edited since, the scene settings as saved."""
        sc = self.scene
        if r.mode != "replace" or {id(it) for it in sc.items} != {id(it) for it in r.items.values()}:
            return False
        for i, it in r.items.items():
            e = r.entries[i]
            if it in sc.label_history or abs(it.offset - e.get("offset_s", 0.0)) > 1e-9 or \
                    it.visible != e.get("visible", True) or it.show_human != e.get("show_human", True):
                return False
        view = r.data.get("view") or {}
        return all(getattr(sc.view, k) == v for k, v in view.items() if k != "speed" and hasattr(sc.view, k))

    _last_restore: dict | None = None  # what the last opening said (GET /api/session)

    def _remember_restore(self, r) -> None:
        self._last_restore = {"file": self._restore_title, "mode": r.mode, "cancelled": r.cancelled,
                              "opened": [it.label for it in r.items.values()],
                              "failed": [{"label": work.entry_label(e), "error": why} for e, why in r.failed],
                              "not_opened": [work.entry_label(e) for e in r.pending()] if r.cancelled else [],
                              "notes": list(r.notes)}
        for n in r.notes:
            self.scene.log(f"작업 세션: {n}")
        for e, why in r.failed:
            self.scene.log(f"작업 세션: 열지 못함 {work.entry_label(e)}: {why}")

    def _abandon_restore(self) -> None:
        """Stop the session being opened and keep the motions it has not opened in the work (written back on save);
        a replace stopped half way is untitled (a save cannot write a part over its file)."""
        r = self._restore
        if r is None:
            return
        self._restore_cancel, self._restore = True, None  # the worker stops after the motion it is on
        self._carry = self._carry_list() + r.carry()
        if r.mode == "replace":
            self.session_path, self._session_clean = None, None
        self._update_title()
        self._refresh_status()

    def _restore_report(self, r) -> None:
        """What did not open (kept in the session file) and what to know."""
        lines = [f"· {work.entry_label(e)}: {why}" for e, why in r.failed[:15]]
        if len(r.failed) > 15:
            lines.append(f"… 외 {len(r.failed) - 15}개")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information if not r.failed else QMessageBox.Warning)
        box.setWindowTitle("작업 세션 열기")
        text = ""
        if r.failed:
            text += f"열지 못한 모션 {len(r.failed)}개 (세션 파일에는 그대로 남겨 둡니다):\n" + "\n".join(lines)
        if r.cancelled and r.pending():
            text += ("\n\n" if text else "") + (f"멈춰서 열지 않은 모션 {len(r.pending())}개는 작업에 남겨 두었습니다"
                                                "(저장하면 함께 저장됨). 세션 파일 자체는 그대로이니, 처음부터 다시 열 수도 "
                                                "있습니다.")
        if r.notes:
            text += ("\n\n" if text else "") + "\n".join(f"· {n}" for n in r.notes[:12])
        box.setText(text)
        drop = box.addButton("열지 못한 모션을 세션에서 빼기", QMessageBox.DestructiveRole) if r.failed else None
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if drop is not None and box.clickedButton() is drop:  # as r.carry() wrote them (absolute)
            gone = [work.rebase_entry(x, r.base_dir, None).get("file") for x, _ in r.failed]
            self._carry = [e for e in self._carry_list() if e.get("file") not in gone]
            self._update_title()

    def new_session(self) -> None:
        """새 작업 세션: the open motions closed (asked when the session or labels have unsaved changes)."""
        if self._restore is not None:
            if self.confirm_unsaved and QMessageBox.question(self, "새 작업 세션", "작업 세션을 여는 중입니다. 멈추고 새로 "
                                                             "시작할까요? (지금까지의 작업은 자동 저장에 남습니다)") != QMessageBox.Yes:
                return
            self._abandon_restore()
        if not self._confirm_session("새 작업 세션을 시작하기"):
            return
        if not self.session_path and not self._confirm_discard_labels(list(self.scene.items), "새 작업 세션을 시작하면"):
            return
        self.autosave(force=True)
        work.clear(self.scene)
        self.session_path, self._carry, self.label_sel = None, [], None
        self._session_clean = work.fingerprint(self.scene, [])
        self._new_work()
        self._update_title()

    def cancel_all(self) -> None:
        """작업 취소: physics and video jobs, and a session being opened (after the motion it is on)."""
        self.scene.cancel_jobs()
        if self._restore is not None:
            self._restore_cancel = True
            self.status("작업 세션 열기를 멈추는 중 (지금 모션이 끝나면)", 6000)

    def _recent(self) -> list[str]:
        v = self.settings.value(layout_key("session/recent"), [])
        return [p for p in ([v] if isinstance(v, str) else v or []) if isinstance(p, str) and p]

    def _recent_add(self, path: str) -> None:
        path = os.path.abspath(path)
        keep = [p for p in self._recent() if _path_key(p) != _path_key(path)]
        self.settings.setValue(layout_key("session/recent"), [path, *keep][:self.RECENT_MAX])

    def _fill_recent_menu(self, m: QMenu) -> None:
        m.clear()
        for p in self._recent():
            a = m.addAction(f"{os.path.basename(p)} — {os.path.dirname(p)}", lambda p=p: self.open_session(p))
            if not os.path.isfile(p):
                a.setEnabled(False)
                a.setText(a.text() + " (없음)")
        if self._recent():
            m.addSeparator()
        for n, what in ((0, "마지막 작업"), (1, "그 전 작업")):
            info = work.autosave_info(n)
            if info is not None:
                when = str(info["saved_at"]).replace("T", " ")[5:16]
                m.addAction(f"{what} (자동 저장 · {when} · 모션 {info['motions']}개)",
                            lambda info=info: self.open_session(info["path"], autosave_of=info))
        m.addSeparator()
        a = m.addAction("시작할 때 마지막 작업 열기")
        a.setCheckable(True)
        a.setChecked(self.settings.value(layout_key("session/restore_on_start"), False, type=bool))
        a.toggled.connect(lambda on: self.settings.setValue(layout_key("session/restore_on_start"), on))
        m.addAction("목록 지우기", lambda: self.settings.setValue(layout_key("session/recent"), []))

    def open_startup(self, inputs: list[str], options: bool = False) -> None:
        """The command line's files: a session among them opens as it was saved, without questions (only that: other
        files are left out); none and 시작할 때 마지막 작업 열기 on: the last work (자동 저장), unless options
        (--physics, the corrections) were given, which it would replace."""
        sessions = [p for p in inputs if work.is_session_file(p)]
        motions = [p for p in inputs if not work.is_session_file(p)]
        if sessions:
            self.open_session(sessions[0], mode="replace", interactive=False, discard=True)
            if len(inputs) > 1:
                self.scene.log(f"작업 세션 {os.path.basename(sessions[0])}만 엽니다 (함께 준 다른 파일은 열지 않음)")
            return
        if not motions and not options and self.confirm_unsaved and \
                self.settings.value(layout_key("session/restore_on_start"), False, type=bool):
            info = work.autosave_info(0)
            if info is not None:
                self.open_session(info["path"], mode="replace", interactive=False, autosave_of=info)
        elif not motions:
            if work.autosave_info(0) is not None:
                self.status("지난 작업은 파일 > 최근 작업 세션 > 마지막 작업으로 엽니다", 10000)
        if motions:
            self.add_paths(motions)

    def _about(self) -> None:
        from . import runtime

        rows = [*app_paths.describe(), ("로그 파일", runtime.log_path() or "콘솔 (저장소에서 실행)")]
        where = "".join(f"<tr><td style='padding-right:10px'>{escape(k)}</td><td>{escape(v)}</td></tr>"
                        for k, v in rows)
        from .. import __version__

        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME} {__version__}</b><br>{APP_TAGLINE}<br><br>"
                                          f"씬: viser ({self.url})<br>물리: MuJoCo (기본), NVIDIA Isaac Sim (PhysX, 선택)<br>"
                                          f"녹화: NVIDIA Isaac Sim<br>"
                                          f"균형 제어 (MuJoCo): GMT 추적 정책 (Apache-2.0, 공개 모델은 연구용)<br><br>"
                                          f"<b>파일 위치</b><table>{where}</table>")

    def closeEvent(self, e):
        if self._restore is not None and self.confirm_unsaved and QMessageBox.question(
                self, "작업 세션", "작업 세션을 여는 중입니다. 지금 끄면 아직 열지 않은 모션은 열지 않고, 지금까지의 "
                                 "작업은 자동 저장에 남깁니다. 끌까요?") != QMessageBox.Yes:
            e.ignore()
            return
        if self._restore is None and not self._confirm_session("종료하기"):  # a session file with changes
            e.ignore()
            return
        # untitled work: unsaved label edits asked about (a session file holds its edits; 저장 안 함 let them go)
        if not self.session_path and self._restore is None and \
                not self._confirm_discard_labels(list(self.scene.items), "종료하면"):
            e.ignore()
            return
        setup = self._setup
        if setup is not None and setup.running:  # an install in the (maybe hidden) 설치 도우미
            name = setup.prereqs.NAMES[setup.running]
            if QMessageBox.question(self, "설치 중", f"{name}을(를) 설치하고 있습니다. 종료하면 설치가 멈춥니다"
                                    "(받던 파일은 다음에 이어 받습니다). 종료할까요?") != QMessageBox.Yes:
                e.ignore()
                return
            setup.cancel.set()
            setup.worker.join(timeout=15)  # downloads and unpacks stop at the next chunk / file and clean up
        self._abandon_restore()  # closing is certain now: what has not opened stays in the work, which is kept
        self.autosave(force=True)
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

    from .scene import add_scene_arguments, load_robot_drawing, scene_options

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

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RetLens.Editor")
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
    opts = scene_options(args)
    try:
        if not args.robot and opts.robot != "unitree_g1":  # 환경 설정's robot: one that no longer loads falls back to the G1
            from ..robot_profile import load as load_robot

            try:
                load_robot(opts.robot).parts
            except Exception as e:
                log(f"robot model {opts.robot} unusable ({type(e).__name__}: {e}); starting with the built-in G1")
                QMessageBox.warning(None, APP_NAME, "환경 설정의 로봇 모델을 쓸 수 없어 내장 Unitree G1로 시작합니다.\n\n"
                                    f"{opts.robot}\n{type(e).__name__}: {e}\n\n"
                                    "파일 > 환경 설정 > 로봇 모델에서 고치거나 비우세요.")
                opts.robot = "unitree_g1"
        urdf = load_robot_drawing(opts.robot, opts.urdf, args.mesh_cell, log=log)
    except Exception as e:  # without the robot model nothing can be shown: say why instead of vanishing
        robot = next(c for c in settings.check_all() if c.key == "robot")
        QMessageBox.critical(None, APP_NAME, f"로봇 모델을 불러오지 못해 시작할 수 없습니다.\n\n{opts.urdf or opts.robot}\n"
                                             f"{type(e).__name__}: {e}\n\n{robot.hint}")
        return 1
    server = viser.ViserServer(host="127.0.0.1", port=port, label=APP_NAME, verbose=False)
    scene = MotionScene(server, urdf, opts, log=log)
    if args.body_mesh:
        scene.view.body_mesh = True
    server.initial_camera.position = (3.0, -3.0, 1.8)
    server.initial_camera.look_at = (0.0, 0.0, 0.75)
    url = f"http://127.0.0.1:{port}/?hideViserLogo"
    win = EditorWindow(scene, url, args.library, accept_eula=args.isaac_accept_eula)
    win.auto_setup = args.quit_after <= 0  # smoke tests must not stop at the first-start 환경 설정
    win.confirm_unsaved = args.quit_after <= 0  # nor at a question about unsaved label edits
    win.show()
    if args.physics:
        win.a_physics.setChecked(True)
    win._session_clean = work.fingerprint(scene, [])  # an empty untitled window is not "changed"
    win._new_work()
    win.open_startup(args.inputs, options=bool(args.physics or args.foot_flat or args.swing_clearance
                                               or args.self_collision or args.body_mesh))
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
