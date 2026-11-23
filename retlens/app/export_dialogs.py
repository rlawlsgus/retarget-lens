"""데이터셋 내보내기 and 로봇 모션 내보내기 dialogs (retlens.dataset): where to, which motions, what to cut out and in
which formats. The choices are remembered (QSettings "export/...")."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from .. import dataset
from ..problems import KINDS

KIND_TIPS = {
    "slip": "디딤발이 미끄러지는 구간. 쓸 만한 모션에도 조금씩 있어 보통은 두고 씁니다",
    "penetration": "발이 바닥 2 cm 아래로 들어간 구간. 물리 학습에서 바닥을 뚫는 목표가 됩니다",
    "swing_low": "내딛는 발이 바닥을 스치는 구간. 스윙 발 보정으로 먼저 고치는 것을 권합니다",
    "self_collision": "로봇 부위가 3 cm 넘게 파고든 구간. 짧게 스치는 것도 잘라 조각이 짧아지기 쉬워, 자기 관통 보정을 "
                      "먼저 권합니다",
    "joint_limit": "관절이 가동 범위 끝에 닿아 있는 구간(넘은 것은 QC 쪽). IK가 한계에 기대는 일이 흔해 많이 잘립니다",
    "marker_gap": "C3D에서 마커가 빠진 구간",
}
QC_CHOICES = (("PASS만", "PASS"), ("PASS·WARN", "WARN"), ("모두 (FAIL도)", "FAIL"))


def _get(store, key: str, default):
    """A remembered choice in the type of default (QSettings hands back strings)."""
    if store is None:
        return default
    v = store.value(f"export/{key}", None)
    if v is None:
        return default
    if isinstance(default, bool):
        return str(v).lower() in ("1", "true", "yes")
    if isinstance(default, float):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    return str(v)


def _put(store, key: str, value) -> None:
    if store is not None:
        store.setValue(f"export/{key}", int(value) if isinstance(value, bool) else value)


class FolderRow(QWidget):
    def __init__(self, start: str, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(start)
        self.edit.setPlaceholderText("내보낼 폴더")
        lay.addWidget(self.edit, 1)
        pick = QPushButton("고르기...")
        pick.clicked.connect(lambda: self._pick(title))
        lay.addWidget(pick)

    def _pick(self, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, self.edit.text() or os.path.expanduser("~"))
        if path:
            self.edit.setText(os.path.normpath(path))

    def path(self) -> str:
        return self.edit.text().strip()


class FormatRow(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes = {}
        for fmt, text in dataset.FORMATS.items():
            b = QCheckBox(fmt)
            b.setToolTip(text)
            b.setChecked(_get(store, f"format_{fmt}", fmt == "npz"))
            lay.addWidget(b)
            self.boxes[fmt] = b
        lay.addStretch(1)

    def value(self) -> tuple[str, ...]:
        return tuple(f for f, b in self.boxes.items() if b.isChecked())

    def save(self, store) -> None:
        for f, b in self.boxes.items():
            _put(store, f"format_{f}", b.isChecked())


class CutBox(QGroupBox):
    """문제 구간 잘라 내기 (retlens.dataset.CutOptions); a checkable group: off = whole motions."""

    def __init__(self, store, falls_ok: bool, falls_note: str, parent=None):
        super().__init__("문제 구간 잘라 내기", parent)
        self.setCheckable(True)
        self.setChecked(_get(store, "cut", False))
        self.setToolTip("문제가 있는 구간을 빼고 남은 부분을 조각으로 내보냅니다. 조각 이름은 <모션>_<시작>-<끝>s")
        d = dataset.CutOptions()
        grid = QGridLayout(self)
        self.qc = QCheckBox("QC가 못 쓰는 프레임 (결측, 관절 한계·속도 초과, 넘어진 자세)")
        self.qc.setChecked(_get(store, "cut_qc", d.qc))
        grid.addWidget(self.qc, 0, 0, 1, 2)
        self.kinds = {}
        for i, (k, (name, _c)) in enumerate(KINDS.items()):
            b = QCheckBox(name)
            b.setToolTip(KIND_TIPS.get(k, ""))
            b.setChecked(_get(store, f"cut_{k}", k in d.kinds))
            grid.addWidget(b, 1 + i // 2, i % 2)
            self.kinds[k] = b
        row = 1 + (len(KINDS) + 1) // 2
        self.falls = QCheckBox(f"물리 넘어짐 ({d.fall_before_s:g}초 전–{d.fall_after_s:g}초 뒤)")
        self.falls.setChecked(falls_ok and _get(store, "cut_falls", d.falls))  # no falls to cut: shown off
        self.falls.setEnabled(falls_ok)
        self.falls.setToolTip(falls_note)
        grid.addWidget(self.falls, row, 0, 1, 2)
        nums = QHBoxLayout()
        nums.addWidget(QLabel("여유"))
        self.pad = QDoubleSpinBox()
        self.pad.setRange(0.0, 2.0)
        self.pad.setSingleStep(0.05)
        self.pad.setSuffix(" s")
        self.pad.setValue(_get(store, "cut_pad", d.pad_s))
        self.pad.setToolTip("자르는 구간을 앞뒤로 이만큼 넓힙니다")
        nums.addWidget(self.pad)
        nums.addSpacing(12)
        nums.addWidget(QLabel("최소 조각"))
        self.min_piece = QDoubleSpinBox()
        self.min_piece.setRange(0.1, 60.0)
        self.min_piece.setSingleStep(0.5)
        self.min_piece.setSuffix(" s")
        self.min_piece.setValue(_get(store, "cut_min_piece", d.min_piece_s))
        self.min_piece.setToolTip("이보다 짧게 남는 조각은 버립니다(QC는 1초보다 짧은 클립을 FAIL로 봄)")
        nums.addWidget(self.min_piece)
        nums.addStretch(1)
        grid.addLayout(nums, row + 1, 0, 1, 2)

    def value(self) -> dataset.CutOptions | None:
        if not self.isChecked():
            return None
        return dataset.CutOptions(qc=self.qc.isChecked(), kinds=tuple(k for k, b in self.kinds.items() if b.isChecked()),
                                  falls=self.falls.isChecked() and self.falls.isEnabled(), pad_s=self.pad.value(),
                                  min_piece_s=self.min_piece.value())

    def save(self, store) -> None:
        _put(store, "cut", self.isChecked())
        _put(store, "cut_qc", self.qc.isChecked())
        for k, b in self.kinds.items():
            _put(store, f"cut_{k}", b.isChecked())
        if self.falls.isEnabled():  # the choice stays for when there are falls to cut
            _put(store, "cut_falls", self.falls.isChecked())
        _put(store, "cut_pad", self.pad.value())
        _put(store, "cut_min_piece", self.min_piece.value())


def _buttons(dlg: QDialog, ok_text: str) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.button(QDialogButtonBox.Cancel).setText("취소")
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    return box


class DatasetExportDialog(QDialog):
    """데이터셋 내보내기: the 데이터셋 tab's folders, with its 리타게팅 corrections, physics and 자동 라벨."""

    def __init__(self, parent, store, files: int, physics: bool, start: str):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("데이터셋 내보내기")
        lay = QVBoxLayout(self)
        intro = QLabel(f"폴더의 모션 {files}개를 리타게팅 메뉴의 보정으로 리타게팅하고 재서(일괄 처리, 계산해 둔 것은 바로), "
                       "기준을 넘는 것을 한 폴더에 로봇 모션·라벨·manifest로 모읍니다.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.folder = FolderRow(_get(store, "folder", start), "내보낼 폴더", self)
        form.addRow("내보낼 폴더", self.folder)
        self.qc = QComboBox()
        for text, key in QC_CHOICES:
            self.qc.addItem(text, key)
        self.qc.setCurrentIndex(max(0, self.qc.findData(_get(store, "qc", "WARN"))))
        self.qc.setToolTip("넣을 모션의 QC 판정. 문제 구간을 잘라 내면 조각마다 다시 판정합니다")
        form.addRow("QC", self.qc)
        self.min_score = QSpinBox()
        self.min_score.setRange(0, 100)
        self.min_score.setSpecialValueText("상관없음")
        self.min_score.setValue(int(_get(store, "min_score", 0.0)))
        self.min_score.setToolTip("리타게팅 점수가 이보다 낮은 모션은 뺍니다(0: 상관없음)")
        form.addRow("최소 리타게팅 점수", self.min_score)
        self.no_falls = QCheckBox("물리에서 넘어진 모션 빼기")
        self.no_falls.setChecked(_get(store, "no_falls", True))
        self.no_falls.setEnabled(physics)
        self.no_falls.setToolTip("물리 (MuJoCo 보조 힘)를 켠 경우. 넘어짐을 잘라 내면 모션은 넣고 그 앞뒤만 뺍니다"
                                 if physics else "데이터셋 탭에서 물리 (MuJoCo 보조 힘)를 켜면 씁니다")
        form.addRow("", self.no_falls)
        lay.addLayout(form)
        note = "넘어지기 1초 전부터 0.25초 뒤까지를 뺍니다" if physics else "데이터셋 탭에서 물리 (MuJoCo 보조 힘)를 켜면 씁니다"
        self.cut = CutBox(store, physics, note, self)
        lay.addWidget(self.cut)
        form2 = QFormLayout()
        self.formats = FormatRow(store, self)
        form2.addRow("형식", self.formats)
        self.labels = QCheckBox("라벨 함께 (<이름>.labels.csv)")
        self.labels.setChecked(_get(store, "labels", True))
        form2.addRow("", self.labels)
        lay.addLayout(form2)
        lay.addWidget(_buttons(self, "내보내기"))

    def accept(self) -> None:
        if not self.folder.path():
            QMessageBox.warning(self, "데이터셋 내보내기", "내보낼 폴더를 고르세요.")
            return
        if not self.formats.value():
            QMessageBox.warning(self, "데이터셋 내보내기", "형식을 하나 이상 고르세요.")
            return
        for key, v in (("folder", self.folder.path()), ("qc", self.qc.currentData()),
                       ("min_score", float(self.min_score.value())), ("no_falls", self.no_falls.isChecked()),
                       ("labels", self.labels.isChecked())):
            _put(self.store, key, v)
        self.cut.save(self.store)
        self.formats.save(self.store)
        super().accept()

    def values(self) -> tuple[str, dataset.ExportOptions]:
        return self.folder.path(), dataset.ExportOptions(
            qc=self.qc.currentData(), min_score=float(self.min_score.value()) or None,
            allow_falls=not (self.no_falls.isChecked() and self.no_falls.isEnabled()), cut=self.cut.value(),
            formats=self.formats.value(), labels=self.labels.isChecked())


class MotionExportDialog(QDialog):
    """로봇 모션 내보내기 of one motion: all of it, the picked label segment or a time range, problems cut out."""

    def __init__(self, parent, store, name: str, duration: float, segment=None, falls: int | None = None,
                 start: str = ""):
        """segment: (text, start_s, end_s) of the picked label segment of this motion; falls: the falls of its
        physics result (None: physics mode is not showing one)."""
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(f"로봇 모션 내보내기 - {name}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        folder = _get(store, "motion_folder", start)
        if start and folder and dataset.path_key(folder) == dataset.path_key(os.path.dirname(start)):
            folder = start  # remembered as the motion's own folder (0.10.0's default): its retlens_export instead
        self.folder = FolderRow(folder, "내보낼 폴더", self)
        form.addRow("내보낼 폴더", self.folder)
        lay.addLayout(form)
        box = QGroupBox("범위")
        g = QGridLayout(box)
        self.r_all = QRadioButton(f"전체 (0–{duration:.2f}초)")
        g.addWidget(self.r_all, 0, 0, 1, 4)
        self.r_seg = QRadioButton("고른 라벨 구간" + (f": {segment[0]} ({segment[1]:.2f}–{segment[2]:.2f}초)" if segment
                                                  else " (타임라인에서 이 모션의 구간을 고르면 씀)"))
        self.r_seg.setEnabled(segment is not None)
        g.addWidget(self.r_seg, 1, 0, 1, 4)
        self.r_range = QRadioButton("직접")
        g.addWidget(self.r_range, 2, 0)
        self._group = QButtonGroup(self)  # one of the three
        for r in (self.r_all, self.r_seg, self.r_range):
            self._group.addButton(r)
        (self.r_seg if segment is not None else self.r_all).setChecked(True)
        self.a, self.b = QDoubleSpinBox(), QDoubleSpinBox()
        for w, v in ((self.a, 0.0), (self.b, duration)):
            w.setRange(0.0, max(duration, 0.01))
            w.setDecimals(2)
            w.setSingleStep(0.1)
            w.setSuffix(" s")
            w.setValue(v)
            w.valueChanged.connect(lambda _v: self.r_range.setChecked(True))
        g.addWidget(self.a, 2, 1)
        g.addWidget(QLabel("–"), 2, 2)
        g.addWidget(self.b, 2, 3)
        lay.addWidget(box)
        self.segment, self.duration = segment, duration
        note = (f"물리 결과의 넘어짐 {falls}회" if falls is not None else
                "물리 모드에서 이 모션의 결과가 보일 때 씁니다")
        self.cut = CutBox(store, falls is not None, note, self)
        lay.addWidget(self.cut)
        form2 = QFormLayout()
        self.formats = FormatRow(store, self)
        form2.addRow("형식", self.formats)
        self.labels = QCheckBox("라벨 함께 (창에서 고친 라벨 그대로)")
        self.labels.setChecked(_get(store, "labels", True))
        form2.addRow("", self.labels)
        lay.addLayout(form2)
        lay.addWidget(_buttons(self, "내보내기"))

    def range_s(self) -> tuple[float, float] | None:
        if self.r_seg.isChecked() and self.segment is not None:
            return float(self.segment[1]), float(self.segment[2])
        if self.r_range.isChecked():
            return float(self.a.value()), float(self.b.value())
        return None

    def accept(self) -> None:
        if not self.folder.path():
            QMessageBox.warning(self, "로봇 모션 내보내기", "내보낼 폴더를 고르세요.")
            return
        if not self.formats.value():
            QMessageBox.warning(self, "로봇 모션 내보내기", "형식을 하나 이상 고르세요.")
            return
        r = self.range_s()
        if r is not None and r[1] - r[0] < 1e-3:
            QMessageBox.warning(self, "로봇 모션 내보내기", "범위의 끝이 시작보다 뒤여야 합니다.")
            return
        _put(self.store, "motion_folder", self.folder.path())
        _put(self.store, "labels", self.labels.isChecked())
        self.cut.save(self.store)
        self.formats.save(self.store)
        super().accept()


BAD_NAME = '<>:"/\\|?*'


def part_names(name: str, n: int) -> list[str]:
    """Default file names of 다른 이름으로 저장's parts: the name itself for one, <name>_01, <name>_02, ... for more."""
    return [name] if n == 1 else [f"{name}_{k + 1:0{max(2, len(str(n)))}d}" for k in range(n)]


def bad_name(n: str) -> bool:
    return not n or any(c in n for c in BAD_NAME) or n.strip(". ") == ""


def save_as_files(out: str, names, formats, labels: bool) -> list[str]:
    """The files 다른 이름으로 저장 writes into out (dataset.export_motion with names): <name>.<format>, .json (and
    .labels.csv) per part."""
    exts = [f".{f}" for f in formats] + [".json"] + ([".labels.csv"] if labels else [])
    return [os.path.join(out, b + e) for b in names for e in exts]


def _strip_ext(n: str) -> str:
    n = n.strip()
    for ext in (".npz", ".csv", ".pkl", ".json"):
        if n.lower().endswith(ext):
            n = n[: -len(ext)]
    return n.strip()


class SaveMotionAsDialog(QDialog):
    """다른 이름으로 저장 of one motion: its robot motion without the timeline's cut spans, under a new name; one file
    per part when cuts in the middle or 파일 나누기 points leave several (each part's name can be changed)."""

    def __init__(self, parent, store, label: str, duration: float, parts, cuts, start_folder: str, name: str,
                 splits=()):
        super().__init__(parent)
        self.store = store
        self.parts = list(parts)
        self.setWindowTitle(f"다른 이름으로 저장 - {label}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.folder = FolderRow(_get(store, "save_as_folder", start_folder), "저장할 폴더", self)
        form.addRow("저장할 폴더", self.folder)
        self.edit = QLineEdit(name)
        self.edit.setToolTip("확장자 없이 씁니다. 형식마다 <이름>.npz 등과 <이름>.json(어디서 잘랐는지), 라벨을 함께 쓰면 "
                             "<이름>.labels.csv를 씁니다. 여러 파일이면 <이름>_01, <이름>_02, ...")
        form.addRow("이름", self.edit)
        self.formats = FormatRow(store, self)
        form.addRow("형식", self.formats)
        self.labels = QCheckBox("라벨 함께 (창에서 고친 라벨 그대로, 파일마다 그 파일의 시작이 0초)")
        self.labels.setChecked(_get(store, "labels", True))
        form.addRow("", self.labels)
        lay.addLayout(form)
        left = sum(b - a for a, b in self.parts)
        lines = [f"남는 시간: {left:.2f}초 / {duration:.2f}초"]
        if cuts:
            lines.append("잘라낸 시간: " + ", ".join(f"{a:.2f}–{b:.2f}s" for a, b in cuts))
        if splits:
            lines.append("파일 나누기: " + ", ".join(f"{t:.2f}s" for t in splits))
        if not cuts and not splits:
            lines.append("잘라내거나 나눈 곳 없음: 모션 전체를 새 이름으로 저장합니다 "
                         "(타임라인에서 Shift+드래그로 범위를 고르고 Shift+Delete, 재생 위치에서 K로 파일 나누기)")
        info = QLabel("\n".join(lines))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = None
        if len(self.parts) > 1:
            from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

            lay.addWidget(QLabel(f"{len(self.parts)}개 파일로 저장합니다. 파일 이름 칸을 두 번 눌러 바꿀 수 있습니다"
                                 "(예: 들고 가기, 돌아오기)."))
            t = self.table = QTableWidget(len(self.parts), 4, self)
            t.setHorizontalHeaderLabels(["시작 (s)", "끝 (s)", "길이 (s)", "파일 이름"])
            t.verticalHeader().setVisible(False)
            t.setSelectionMode(QAbstractItemView.NoSelection)
            t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self._auto = [True] * len(self.parts)
            self._filling = True
            for r, (a, b) in enumerate(self.parts):
                for c, v in enumerate((a, b, b - a)):
                    cell = QTableWidgetItem(f"{v:.2f}")
                    cell.setFlags(Qt.ItemIsEnabled)
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    t.setItem(r, c, cell)
                t.setItem(r, 3, QTableWidgetItem(""))
            self._filling = False
            self._fill_names()
            t.itemChanged.connect(self._name_edited)
            self.edit.textChanged.connect(self._fill_names)
            t.setMinimumHeight(min(320, 40 + 28 * len(self.parts)))
            lay.addWidget(t)
        lay.addWidget(_buttons(self, "저장"))

    def _fill_names(self) -> None:
        """The names not changed by hand follow the 이름 box (<이름>_01, ...)."""
        self._filling = True
        for r, n in enumerate(part_names(self.name(), len(self.parts))):
            if self._auto[r]:
                self.table.item(r, 3).setText(n)
        self._filling = False

    def _name_edited(self, cell) -> None:
        if not self._filling and cell.column() == 3:
            self._auto[cell.row()] = False

    def name(self) -> str:
        return _strip_ext(self.edit.text())

    def names(self) -> list[str]:
        """One file name per part, in time order."""
        if self.table is None:
            return [self.name()]
        return [_strip_ext(self.table.item(r, 3).text()) for r in range(len(self.parts))]

    def accept(self) -> None:
        names = self.names()
        if not self.folder.path():
            QMessageBox.warning(self, "다른 이름으로 저장", "저장할 폴더를 고르세요.")
            return
        bad = next((n for n in [self.name(), *names] if bad_name(n)), None)
        if bad is not None:
            QMessageBox.warning(self, "다른 이름으로 저장", f"쓸 수 없는 이름입니다: {bad or '(빈칸)'}\n({BAD_NAME} 는 쓸 수 없음)")
            return
        seen: set[str] = set()
        for n in names:
            if n.lower() in seen:
                QMessageBox.warning(self, "다른 이름으로 저장", f"파일 이름이 겹칩니다: {n}")
                return
            seen.add(n.lower())
        if not self.formats.value():
            QMessageBox.warning(self, "다른 이름으로 저장", "형식을 하나 이상 고르세요.")
            return
        _put(self.store, "save_as_folder", self.folder.path())
        _put(self.store, "labels", self.labels.isChecked())
        self.formats.save(self.store)
        super().accept()


class SaveAllAsDialog(QDialog):
    """모두 다른 이름으로 저장: every motion on the timeline at once, each as 다른 이름으로 저장 would (its cut time left
    out, one file per part), into one folder. rows: (motion label, default name, number of files, seconds kept,
    seconds in all) per motion; a motion with nothing kept is listed and left out."""

    def __init__(self, parent, store, rows, start_folder: str, title: str = "모두 다른 이름으로 저장"):
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

        super().__init__(parent)
        self.store, self.rows = store, list(rows)
        self.setWindowTitle(f"{title} - 모션 {len(self.rows)}개")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.folder = FolderRow(_get(store, "save_as_folder", start_folder), "저장할 폴더", self)
        form.addRow("저장할 폴더", self.folder)
        self.formats = FormatRow(store, self)
        form.addRow("형식", self.formats)
        self.labels = QCheckBox("라벨 함께 (창에서 고친 라벨 그대로, 파일마다 그 파일의 시작이 0초)")
        self.labels.setChecked(_get(store, "labels", True))
        form.addRow("", self.labels)
        lay.addLayout(form)
        lay.addWidget(QLabel("모션마다 잘라낸 시간을 빼고 저장합니다. 나누기 지점이 있거나 가운데를 잘랐으면 <이름>_01, "
                             "<이름>_02, ...로 나눠 씁니다. 이름 칸을 두 번 눌러 바꿀 수 있습니다."))
        t = self.table = QTableWidget(len(self.rows), 4, self)
        t.setHorizontalHeaderLabels(["모션", "남는 시간 (s)", "파일 수", "이름"])
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for r, (label, name, n, kept, total) in enumerate(self.rows):
            cells = [label, f"{kept:.2f} / {total:.2f}", str(n) if n else "없음 (모두 잘라냄)"]
            for c, v in enumerate(cells):
                cell = QTableWidgetItem(v)
                cell.setFlags(Qt.ItemIsEnabled)
                if c:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, cell)
            cell = QTableWidgetItem(name if n else "")
            if not n:
                cell.setFlags(Qt.ItemIsEnabled)
            t.setItem(r, 3, cell)
        t.resizeColumnsToContents()
        t.setMinimumWidth(640)
        t.setMinimumHeight(min(360, 40 + 28 * len(self.rows)))
        lay.addWidget(t)
        lay.addWidget(_buttons(self, "저장"))

    def names(self) -> list[str | None]:
        """Per motion its name (its parts are <name>_01, ...), None for one with nothing to save."""
        return [_strip_ext(self.table.item(r, 3).text()) if row[2] else None for r, row in enumerate(self.rows)]

    def files(self) -> list[list[str]]:
        """Per motion the file names of its parts (part_names), [] for one with nothing to save."""
        return [part_names(n, row[2]) if n is not None else [] for n, row in zip(self.names(), self.rows)]

    def accept(self) -> None:
        if not self.folder.path():
            QMessageBox.warning(self, "모두 다른 이름으로 저장", "저장할 폴더를 고르세요.")
            return
        bad = next((n for n in self.names() if n is not None and bad_name(n)), None)
        if bad is not None:
            QMessageBox.warning(self, "모두 다른 이름으로 저장", f"쓸 수 없는 이름입니다: {bad or '(빈칸)'}\n({BAD_NAME} 는 쓸 수 없음)")
            return
        seen: set[str] = set()
        for n in (f for fs in self.files() for f in fs):
            if n.lower() in seen:
                QMessageBox.warning(self, "모두 다른 이름으로 저장", f"파일 이름이 겹칩니다: {n}\n이름 칸을 고치세요.")
                return
            seen.add(n.lower())
        if not seen:
            QMessageBox.warning(self, "모두 다른 이름으로 저장", "저장할 모션이 없습니다(모든 시간을 잘라냄).")
            return
        if not self.formats.value():
            QMessageBox.warning(self, "모두 다른 이름으로 저장", "형식을 하나 이상 고르세요.")
            return
        _put(self.store, "save_as_folder", self.folder.path())
        _put(self.store, "labels", self.labels.isChecked())
        self.formats.save(self.store)
        super().accept()


def unique_names(names: list[str]) -> list[str]:
    """Default names made apart (the same file opened twice, two folders' 01.bvh): a later one gets _2, _3, ..."""
    out, seen = [], set()
    for n in names:
        m, k = n, 2
        while m.lower() in seen:
            m, k = f"{n}_{k}", k + 1
        seen.add(m.lower())
        out.append(m)
    return out


def confirm_folder(parent, out: str, title: str) -> bool:
    """Ask before writing into a folder that already has files: an earlier export's files (its manifest) are
    replaced; files of the same names are overwritten."""
    try:
        names = os.listdir(out)
    except OSError:
        return True  # made new
    if not names:
        return True
    if dataset.MANIFEST in names:
        text = (f"{out}에 전에 내보낸 데이터셋이 있습니다. 그 manifest에 적힌 파일을 지우고 새로 씁니다. "
                "다른 파일은 그대로 둡니다.")
    else:
        text = f"{out}이(가) 비어 있지 않습니다. 이름이 같은 파일은 덮어씁니다. 계속할까요?"
    return QMessageBox.question(parent, title, text, QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok


def report(parent, title: str, text: str, folder: str, open_path) -> None:
    """The result, with a button that opens the folder."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextInteractionFlags(Qt.TextSelectableByMouse)
    opened = box.addButton("폴더 열기", QMessageBox.AcceptRole)
    box.addButton("닫기", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is opened:
        open_path(folder)


def manifest_text(m: dict) -> str:
    """'조각 7개 · 39.5초 (원본 40.1초 중) · 잘라 낸 0.5초 · 뺀 모션 1개 (QC FAIL 1)' of an export's manifest."""
    t = m["totals"]
    parts = [f"모션 {t['exported_motions']}개 → 파일 {t['clips']}개 · {t['seconds'] / 60:.1f}분"]
    if t["cut_seconds"] or t["short_seconds"]:
        parts.append(f"잘라 낸 {t['cut_seconds']:.1f}초, 짧아서 버린 {t['short_seconds']:.1f}초")
    if t["excluded"]:
        parts.append(f"뺀 것 {t['excluded']}개 ("
                     + ", ".join(f"{k} {v}" for k, v in t["excluded_by_reason"].items()) + ")")
    if m.get("stopped"):
        parts.append("멈춤 (멈춘 곳까지 manifest에 적음)")
    return "\n".join(parts)
