"""The window side of install / update / uninstall (retlens/install.py does the work).

    UpdateController(win)   one per window: start-up tasks (finish what an update left, show its result, register,
                            clean up), the first-start install offer of a portable copy, the automatic check and its
                            status-bar button, the 도움말 menu's actions, the restart that applies an update
    UpdateDialog            도움말 > 업데이트 확인...: versions, release notes, download + check with progress,
                            "지금 다시 시작" / "종료할 때 업데이트", 릴리즈 페이지, 받은 zip으로 업데이트
    uninstall_main()        RetLens.exe --uninstall ("installed apps" > 제거), before the editor starts
(The offer to go back after a just-updated RetLens fails to start is retlens.install.offer_rollback: no Qt.)

Work runs in threads; results come back through Qt signals.
"""

from __future__ import annotations

import os
import threading
import time
from html import escape

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QTextBrowser, QToolButton, QVBoxLayout)

from .. import install, paths, settings

APP = "RetLens"


def _settings_store():
    from PySide6.QtCore import QSettings

    return QSettings(APP, APP)


def _open_url(url: QUrl) -> None:
    if url.scheme() in ("http", "https"):  # release notes may hold links: nothing else is opened
        QDesktopServices.openUrl(url)


class _Signals(QObject):
    checked = Signal(object)  # install.Check
    progress = Signal(str, float, float)  # stage, done, total
    done = Signal(object, object)  # value, error (exception or None)


def _run(fn, sig: _Signals, cancel: threading.Event | None = None) -> threading.Thread:
    def work():
        try:
            sig.done.emit(fn(), None)
        except BaseException as e:  # noqa: BLE001 - every failure is shown
            sig.done.emit(None, e)

    t = threading.Thread(target=work, daemon=True, name="retlens-update")
    t.start()
    return t


def _error_text(e: BaseException) -> str:
    from .. import prereqs

    if isinstance(e, prereqs.Cancelled):
        return "취소했습니다"
    if isinstance(e, (install.UpdateError, prereqs.SetupError)):
        return str(e)
    return f"{type(e).__name__}: {e}"


# ------------------------------------------------------------------ the dialog
class UpdateDialog(QDialog):
    """도움말 > 업데이트 확인: one per window (UpdateController.dialog); hiding it keeps a download going."""

    def __init__(self, ctl: "UpdateController"):
        super().__init__(ctl.win)
        self.ctl, self.win = ctl, ctl.win
        self.setWindowTitle(f"{APP} 업데이트")
        self.resize(720, 560)
        self.check: install.Check | None = None
        self.release: install.Release | None = None
        self.staged: str | None = None
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.sig = _Signals()
        self.sig.progress.connect(self._progress)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.RichText)
        lay.addWidget(self.head)
        self.notes = QTextBrowser()
        self.notes.setOpenLinks(False)
        self.notes.anchorClicked.connect(_open_url)
        lay.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.state = QLabel()
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.b_page = QPushButton("릴리즈 페이지")
        self.b_page.setToolTip("GitHub 릴리즈 페이지를 브라우저로 엽니다")
        self.b_page.clicked.connect(lambda: _open_url(QUrl((self.release.page if self.release else install.RELEASES_PAGE))))
        row.addWidget(self.b_page)
        self.b_zip = QPushButton("받은 zip으로 업데이트...")
        self.b_zip.setToolTip("브라우저로 받은 RetLens-<버전>-win64.zip으로 업데이트합니다(프록시·사내망에서 직접 받지 못할 때)")
        self.b_zip.clicked.connect(self._from_zip)
        row.addWidget(self.b_zip)
        row.addStretch(1)
        self.b_again = QPushButton("다시 확인")
        self.b_again.clicked.connect(lambda: self.start_check(force=True))
        row.addWidget(self.b_again)
        self.b_main = QPushButton("업데이트")
        self.b_main.setDefault(True)
        self.b_main.clicked.connect(self._main_action)
        row.addWidget(self.b_main)
        self.b_later = QPushButton("종료할 때 업데이트")
        self.b_later.setToolTip("지금은 계속 쓰고, RetLens를 끌 때 바꿉니다(다시 열지 않음)")
        self.b_later.clicked.connect(lambda: self.ctl.apply(self.release, self.staged, now=False, dialog=self))
        self.b_later.setVisible(False)
        row.addWidget(self.b_later)
        self.b_cancel = QPushButton("취소")
        self.b_cancel.clicked.connect(self._cancel)
        self.b_cancel.setVisible(False)
        row.addWidget(self.b_cancel)
        close = QPushButton("닫기")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        lay.addLayout(row)
        self._show_head()

    # ---------------------------------------------------------- views
    def _where(self) -> str:
        if not paths.FROZEN:
            return "저장소에서 실행 중 (업데이트는 git으로 받습니다)"
        if install.is_installed():
            return f"설치됨: {escape(install.install_dir())}"
        inst = install.installed_info()
        extra = f" · 설치된 RetLens {inst['version']}도 있음" if inst and inst.get("version") else ""
        return f"설치하지 않고 실행 중: {escape(install.program_dir() or '')}{extra}"

    def _show_head(self, text: str = "") -> None:
        latest = self.check.latest.version if self.check and self.check.latest else "?"
        self.head.setText(f"<b>지금 버전</b> {install.running_version()} &nbsp; <b>최신 버전</b> {latest}<br>"
                          f"<span style='color:gray'>{self._where()}</span>" + (f"<br>{text}" if text else ""))

    def _busy(self, on: bool) -> None:
        self.bar.setVisible(on)
        self.b_cancel.setVisible(on)
        for b in (self.b_main, self.b_again, self.b_zip):
            b.setEnabled(not on)
        if on:
            self.bar.setRange(0, 0)
            self.b_later.setVisible(False)

    def _progress(self, stage: str, done: float, total: float) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * done / total))
            self.bar.setFormat(f"{stage} {done / 1e6:.0f} / {total / 1e6:.0f} MB")
        else:
            self.bar.setRange(0, 0)
            self.bar.setFormat(stage)
        self.state.setText(stage)

    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _cancel(self) -> None:
        self.cancel.set()
        self.state.setText("취소하는 중...")

    # ---------------------------------------------------------- check
    def start_check(self, force: bool = False) -> None:
        if self.running():
            return
        cached = self.ctl.last_check
        if cached is not None and not force:
            self._checked(cached)
            return
        self._busy(True)
        self.state.setText("GitHub에서 최신 릴리즈를 확인하는 중...")
        sig = _Signals()
        sig.done.connect(lambda chk, err: (self._busy(False), self._checked(chk)))
        self.worker = _run(lambda: self.ctl.check(force=True), sig)
        self._keep = sig

    def _checked(self, chk: install.Check | None) -> None:
        self.check = chk
        self.release = chk.latest if chk else None
        self._show_head()
        if chk is None or chk.error:
            self.state.setText(f"<span style='color:#e66'>확인하지 못했습니다: {escape(chk.error if chk else '?')}</span>")
            self.state.setTextFormat(Qt.RichText)
            self.notes.setMarkdown("")
            self.b_main.setEnabled(False)
            return
        self.state.setTextFormat(Qt.AutoText)
        rel = chk.latest
        if rel is None:
            self.notes.setMarkdown("")
            self.state.setText("내려받을 수 있는 릴리즈(RetLens-<버전>-win64.zip)가 아직 없습니다.")
            self.b_main.setEnabled(False)
            return
        self.notes.setMarkdown(f"## {rel.name}\n\n{rel.notes}")
        if not chk.newer:
            inst = chk.installed_version
            if install.is_portable() and inst and install.is_newer(inst, install.running_version()):
                self.state.setText(f"이 PC에 설치된 RetLens {inst}이(가) 최신입니다. 시작 메뉴의 RetLens를 쓰세요. "
                                   f"(지금 연 것은 설치하지 않은 {install.running_version()})")
            else:
                self.state.setText("최신 버전을 쓰고 있습니다.")
            self.b_main.setEnabled(False)
            self.b_main.setText("업데이트")
            return
        self.staged = install.staged_ready(rel.version, rel.sha256) if paths.FROZEN else None
        self._offer(rel)

    def _offer(self, rel: install.Release) -> None:
        if not paths.FROZEN:
            self.state.setText(f"새 버전 {rel.version}이 있습니다. 저장소에서는 git pull로 받습니다.")
            self.b_main.setEnabled(False)
            return
        installed = install.is_installed()
        if self.staged:
            self.state.setText(f"RetLens {rel.version}을 받아 확인해 두었습니다.")
            self.b_main.setText("지금 다시 시작" if installed else "설치하고 다시 시작")
            self.b_later.setVisible(installed)
        else:
            size = f" ({rel.size / 1e6:.0f} MB)" if rel.size else ""
            self.state.setText(f"새 버전 {rel.version}이 있습니다{size}." + ("" if installed else
                               " 설치하지 않고 실행 중이라, 받은 새 버전은 이 PC에 설치됩니다(시작 메뉴)."))
            self.b_main.setText("업데이트")
        self.b_main.setEnabled(True)

    # ---------------------------------------------------------- download and stage
    def _main_action(self) -> None:
        if self.release is None:
            return
        if self.staged:
            self.ctl.apply(self.release, self.staged, now=True, dialog=self)
            return
        self._download(self.release)

    def _download(self, rel: install.Release) -> None:
        try:
            install.check_can_change()
        except install.UpdateError as e:
            QMessageBox.warning(self, f"{APP} 업데이트", str(e))
            return
        self.cancel.clear()
        self._busy(True)

        def work():
            with install.update_lock(timeout_s=1.0):
                z = install.download(rel, progress=lambda *a: self.sig.progress.emit(*a), cancel=self.cancel)
                return install.stage(rel, z, progress=lambda *a: self.sig.progress.emit(*a), cancel=self.cancel)

        sig = _Signals()
        sig.done.connect(lambda staged, err: self._staged(rel, staged, err))
        self.worker = _run(work, sig)
        self._keep = sig

    def _staged(self, rel: install.Release, staged: str | None, err: BaseException | None) -> None:
        self._busy(False)
        if err is not None:
            self.state.setText(f"업데이트하지 못했습니다: {_error_text(err)}")
            self.b_main.setEnabled(True)
            return
        self.staged = staged
        self.release = rel
        self._offer(rel)
        self.show()
        self.raise_()

    def _from_zip(self) -> None:
        if not paths.FROZEN:
            QMessageBox.information(self, f"{APP} 업데이트", "설치판에서만 씁니다.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "RetLens 릴리즈 zip", os.path.expanduser("~/Downloads"),
                                              "RetLens zip (RetLens-*-win64.zip)")
        if not path:
            return
        try:
            rel = install.release_from_zip(path, self.check)
        except install.UpdateError as e:
            QMessageBox.warning(self, f"{APP} 업데이트", str(e))
            return
        if not install.is_newer(rel.version, install.running_version()) and QMessageBox.question(
                self, f"{APP} 업데이트", f"{rel.version}은(는) 지금 버전({install.running_version()})보다 새 버전이 아닙니다. "
                "그래도 이것으로 바꿀까요?") != QMessageBox.Yes:
            return
        if not rel.sha256 and QMessageBox.question(
                self, f"{APP} 업데이트", "이 zip의 체크섬을 확인할 수 없습니다(GitHub에 연결되지 않고, 옆에 .sha256 파일도 "
                "없음). 받은 곳을 믿을 수 있을 때만 계속하세요. 계속할까요?") != QMessageBox.Yes:
            return
        self.release = rel
        self.notes.setMarkdown(f"## {escape(os.path.basename(path))}\n\n받은 파일로 업데이트합니다.")
        self._download(rel)

    def closeEvent(self, e):
        self.hide()  # a running download goes on (the window's closeEvent asks)
        e.ignore()


# ------------------------------------------------------------------ the controller
class UpdateController(QObject):
    """Install / update for one EditorWindow."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.dialog: UpdateDialog | None = None
        self.last_check: install.Check | None = None
        self.armed: install.Armed | None = None
        self.sig = _Signals()
        self.sig.checked.connect(self._auto_checked)
        self.button = QToolButton()  # status bar: "업데이트 0.9.1" once a newer release is known
        self.button.setAutoRaise(True)
        self.button.clicked.connect(lambda: self.open_dialog(force=False))
        self.button.hide()
        self._install_worker: threading.Thread | None = None

    # ---------------------------------------------------------- start-up
    def startup(self, offer: bool = True, check: bool = True) -> bool:
        """After the window is up: finish an interrupted update, tell the helper this version started, show the update's
        result once the helper has written it, register and clean up (in the background), then the install offer
        (offer) and the automatic check (check). True when it went on to install or to open the installed copy (this
        window is closing)."""
        if not paths.FROZEN:
            return False
        try:
            install.recover()
        except Exception as e:
            self.win.scene.log(f"업데이트 복구 실패: {type(e).__name__}: {e}")
        install.mark_started()  # the helper's health check is waiting for this; it writes its result after
        self._poll_result(90)

        def background():
            try:
                reg = install.ensure_registration()
                if reg and reg.get("errors"):
                    self.win.scene.log(f"바로 가기·설치 정보 갱신 실패: {'; '.join(reg['errors'])}")
                kept = install.cleanup(self.win.scene.log, lock_timeout_s=300.0)
                for p in kept:
                    self.win.scene.log(f"이전 버전 폴더에 다른 파일이 있어 남겨 두었습니다: {p}")
            except Exception as e:
                self.win.scene.log(f"업데이트 정리 실패: {type(e).__name__}: {e}")

        threading.Thread(target=background, daemon=True, name="retlens-cleanup").start()
        if install.is_installed():
            QTimer.singleShot(1500, self._offer_portable_delete)
        elif offer and getattr(self.win, "auto_setup", True):
            if self._offer_install():
                return True  # installing (or opening the installed copy): that one does the rest
        if check and getattr(self.win, "auto_setup", True) and settings.load().check_updates:
            QTimer.singleShot(4000, self._auto_check)
        return False

    def _poll_result(self, tries: int) -> None:
        """Show the update's result once the helper has written it (right after it sees this version started)."""
        res = install.take_result()
        if res:
            self._show_result(res)
        elif tries > 0:
            QTimer.singleShot(1000, lambda: self._poll_result(tries - 1))

    def _show_result(self, res: dict) -> None:
        if res.get("action") == "swap":
            if res.get("ok"):
                self.win.status(f"RetLens {res.get('to')}(으)로 업데이트했습니다", 15000)
                self.win.scene.log(f"업데이트: {res.get('from')} → {res.get('to')}")
                if res.get("kept_in_old"):
                    self.win.scene.log(f"이전 폴더에서 옮기지 못한 파일: {', '.join(res['kept_in_old'])}")
            else:
                QMessageBox.warning(self.win, f"{APP} 업데이트",
                                    f"업데이트를 마치지 못했습니다.\n\n{res.get('error', '')}"
                                    + (f"\n\n기록: {res.get('log')}" if res.get("log") else ""))
        elif res.get("action") == "recover":
            self.win.scene.log(f"끊긴 업데이트를 마무리했습니다: {res}")

    def _offer_portable_delete(self) -> None:
        src = install.portable_source_to_offer()
        if not src:
            return
        box = QMessageBox(self.win)
        box.setWindowTitle(f"{APP} 설치")
        box.setText(f"설치에 쓴 폴더가 남아 있습니다.\n{src}\n\n이제 시작 메뉴의 RetLens를 쓰면 되므로 지워도 됩니다. 지울까요?")
        yes = box.addButton("지우기", QMessageBox.AcceptRole)
        box.addButton("남겨 두기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            ok = install.delete_portable_source(src)
            self.win.status("설치에 쓴 폴더를 지웠습니다" if ok else f"일부를 지우지 못했습니다: {src}", 8000)
        else:
            install.forget_portable_source()

    # ---------------------------------------------------------- install (portable)
    def _offer_install(self) -> bool:
        """The first start of a portable copy: offer to install (or to open the installed one). True when it went on
        to install."""
        store = _settings_store()
        inst = install.installed_info()
        if inst and inst.get("version"):
            if store.value("install/ignore_installed", "") == inst["version"]:
                return False
            box = QMessageBox(self.win)
            box.setWindowTitle(f"{APP} 설치")
            newer = install.is_newer(install.running_version(), inst["version"])
            box.setText(f"이 PC에 RetLens {inst['version']}이(가) 설치되어 있습니다(시작 메뉴).\n"
                        f"지금 연 것은 설치하지 않은 {install.running_version()}입니다.")
            open_btn = box.addButton("설치된 RetLens 열기", QMessageBox.AcceptRole)
            up_btn = box.addButton(f"설치된 것을 {install.running_version()}(으)로 바꾸기", QMessageBox.ActionRole) \
                if newer else None
            box.addButton("이것으로 계속", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._launch_installed_after_close()
                return not self.win.isVisible()
            if up_btn is not None and box.clickedButton() is up_btn:
                self.install_portable(ask=False)
                return not self.win.isVisible()
            store.setValue("install/ignore_installed", inst["version"])
            return False
        if store.value("install/never_ask", False, type=bool):
            return False
        box = QMessageBox(self.win)
        box.setWindowTitle(f"{APP} 설치")
        box.setText("RetLens를 이 PC에 설치할까요?\n\n시작 메뉴에서 바로 열 수 있고, 새 버전이 나오면 도움말 > 업데이트 "
                    "확인으로 바꿀 수 있습니다. 관리자 권한은 필요 없습니다(사용자 폴더에 설치).")
        desk = QCheckBox("바탕 화면에도 바로 가기 만들기")
        box.setCheckBox(desk)
        yes = box.addButton("설치", QMessageBox.AcceptRole)
        box.addButton("나중에", QMessageBox.RejectRole)
        never = box.addButton("다시 묻지 않음", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is never:
            store.setValue("install/never_ask", True)
            self.win.status("설치는 도움말 > RetLens 설치...에서 언제든 할 수 있습니다", 8000)
        if box.clickedButton() is yes:
            self.install_portable(ask=False, desktop=desk.isChecked())
            return not self.win.isVisible()
        return False

    def install_portable(self, ask: bool = True, desktop: bool = False) -> None:
        """도움말 > RetLens 설치: copy this copy into the install folder, register it, then offer to reopen from there."""
        if not install.is_portable():
            QMessageBox.information(self.win, f"{APP} 설치", "이미 설치된 RetLens입니다." if paths.FROZEN else
                                    "설치판(zip을 푼 RetLens.exe)에서만 씁니다.")
            return
        if self._install_worker is not None and self._install_worker.is_alive():
            return
        if ask:
            inst = install.installed_info()
            older = ""
            if inst and inst.get("version") and not install.is_newer(install.running_version(), inst["version"]):
                older = (f"\n\n이미 설치된 RetLens {inst['version']}이(가) 이것({install.running_version()})과 같거나 "
                         "더 새 버전입니다. 설치하면 그것을 이 버전으로 바꿉니다.")
            box = QMessageBox(self.win)
            box.setWindowTitle(f"{APP} 설치")
            box.setText(f"RetLens {install.running_version()}을(를) 이 PC에 설치합니다.\n\n설치 위치: {install.install_dir()}\n"
                        "시작 메뉴에 바로 가기를 만들고, Windows '설치된 앱'에 등록합니다." + older)
            desk = QCheckBox("바탕 화면에도 바로 가기 만들기")
            box.setCheckBox(desk)
            yes = box.addButton("설치", QMessageBox.AcceptRole)
            box.addButton("취소", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return
            desktop = desk.isChecked()
        try:
            install.check_can_change()
        except install.UpdateError as e:
            QMessageBox.warning(self.win, f"{APP} 설치", str(e))
            return
        dlg = QDialog(self.win)
        dlg.setWindowTitle(f"{APP} 설치")
        lay = QVBoxLayout(dlg)
        label = QLabel(f"{install.install_dir()}에 복사하는 중...")
        lay.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        lay.addWidget(bar)
        cancel = self._install_cancel = threading.Event()
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.rejected.connect(cancel.set)
        dlg.rejected.connect(cancel.set)  # Esc / the title bar's X stop it too
        lay.addWidget(bb)
        sig = _Signals()

        def prog(stage, done, total):
            if total:
                bar.setRange(0, 1000)
                bar.setValue(int(1000 * done / total))
                bar.setFormat(f"{stage} {done / 1e6:.0f} / {total / 1e6:.0f} MB")

        sig.progress.connect(prog)

        def finished(info, err):
            dlg.accept()
            if err is not None:
                QMessageBox.warning(self.win, f"{APP} 설치", f"설치하지 못했습니다: {_error_text(err)}")
                return
            warn = info.get("registration", {}).get("errors")
            text = f"RetLens {info['version']}을(를) 설치했습니다.\n{info['dir']}"
            if warn:
                text += f"\n\n일부를 등록하지 못했습니다: {'; '.join(warn)}"
            box = QMessageBox(self.win)
            box.setWindowTitle(f"{APP} 설치")
            box.setText(text + "\n\n이 창을 닫고 설치된 RetLens로 다시 열까요? 열린 작업은 그대로 이어서 엽니다.")
            again = box.addButton("다시 열기", QMessageBox.AcceptRole)
            box.addButton("나중에", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is again:
                self._launch_installed_after_close()

        sig.done.connect(finished)
        src = install.program_dir()
        self._install_worker = _run(lambda: install.install_from_folder(
            src, progress=lambda *a: sig.progress.emit(*a), cancel=cancel, desktop=desktop), sig)
        self._keep_install = sig
        dlg.exec()

    def _launch_installed_after_close(self) -> None:
        """Close this window (its usual questions); once it has, start the installed copy with the work resumed."""
        exe = os.path.join(install.install_dir(), "RetLens.exe")
        if self.win.scene.items:
            args = ["--resume-autosave"]
        else:  # nothing open yet: what this copy was started with (still opening in the background)
            args = [p for p in getattr(self.win, "startup_inputs", []) if os.path.exists(p)]
        install.AFTER_EXIT.append(lambda: install.spawn(exe, args))
        if not self.win.close():
            install.AFTER_EXIT.clear()
            self.win.status("창을 닫지 않아 설치된 RetLens를 열지 않았습니다", 8000)

    # ---------------------------------------------------------- checking
    def check(self, force: bool = False) -> install.Check:
        """The latest release (ETag-cached between checks)."""
        store = _settings_store()
        prev = self.last_check
        chk = install.check_latest(etag=store.value("update/etag", "") or None if prev else None,
                                   cached=prev.cached if prev else None)
        if not chk.error:
            store.setValue("update/last_check", time.time())
            if chk.etag:
                store.setValue("update/etag", chk.etag)
        self.last_check = chk
        return chk

    def _auto_check(self) -> None:
        store = _settings_store()
        try:
            last = float(store.value("update/last_check", 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last < install.CHECK_EVERY_S and not store.value("update/newer", ""):
            return

        def work():
            try:
                self.sig.checked.emit(self.check())
            except Exception as e:
                self.win.scene.log(f"업데이트 확인 실패: {type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True, name="retlens-update-check").start()

    def _auto_checked(self, chk: install.Check) -> None:
        store = _settings_store()
        if chk.error:
            self.win.scene.log(f"업데이트 확인: {chk.error}")
            return
        if chk.newer and chk.latest is not None:
            store.setValue("update/newer", chk.latest.version)
            if store.value("update/skip", "") == chk.latest.version:
                return
            self.button.setText(f"업데이트 {chk.latest.version}")
            self.button.setToolTip(f"새 버전 RetLens {chk.latest.version}이 있습니다. 눌러서 보기")
            self.button.show()
            self.win.status(f"새 버전 RetLens {chk.latest.version}이 있습니다 (도움말 > 업데이트 확인)", 15000)
        else:
            store.setValue("update/newer", "")
            self.button.hide()

    def open_dialog(self, force: bool = True) -> None:
        """도움말 > 업데이트 확인 (force: ask GitHub again; cheap with the ETag), the status-bar button (what is known)."""
        if self.dialog is None:
            self.dialog = UpdateDialog(self)
        d = self.dialog
        # opened from a modal dialog (환경 설정): only a modal window on top of it takes input
        d.setWindowModality(Qt.ApplicationModal if QApplication.activeModalWidget() not in (None, d) else Qt.NonModal)
        d.show()
        d.raise_()
        d.activateWindow()
        d.start_check(force=force)

    # ---------------------------------------------------------- applying
    def _blockers(self) -> list[str]:
        """What a restart would stop."""
        win, out = self.win, []
        if win.scene.jobs_busy():
            out.append("물리·동영상 작업")
        if getattr(win, "dataset", None) is not None and win.dataset._running:
            out.append("데이터셋 일괄 처리·내보내기")
        setup = getattr(win, "_setup", None)
        if setup is not None and setup.running:
            out.append("설치 도우미의 설치")
        return out

    def apply(self, rel: install.Release, staged: str, now: bool, dialog: QDialog | None = None) -> None:
        """Put the staged version in place: from the installed program through the helper (now: restart; else when
        RetLens quits); from a portable copy by installing it, then reopening from the install."""
        parent = dialog or self.win
        if not install.is_installed():
            try:
                info = install.install_staged(staged, rel.version)
            except install.UpdateError as e:
                QMessageBox.warning(parent, f"{APP} 업데이트", str(e))
                return
            if dialog is not None:
                dialog.hide()
            self.win.status(f"RetLens {rel.version}을(를) 설치했습니다: {info['dir']}", 10000)
            self._launch_installed_after_close()
            return
        procs = install.processes_in(install.install_dir())
        if procs:
            QMessageBox.warning(parent, f"{APP} 업데이트", f"다른 RetLens가 실행 중입니다({install.describe_processes(procs)}). "
                                "그것을 모두 닫은 뒤 다시 누르세요.")
            return
        busy = self._blockers()
        if now and busy and QMessageBox.question(
                parent, f"{APP} 업데이트", f"{', '.join(busy)}이(가) 진행 중입니다. 지금 다시 시작하면 멈춥니다. 다시 시작할까요?"
                ) != QMessageBox.Yes:
            return
        args = ["--resume-autosave"] if self.win.scene.items else []
        a = self.armed
        if a is not None and a.job.get("action") == "swap" and a.job.get("staged") == staged and \
                a.job.get("to") == rel.version and a.proc.poll() is None:
            a.set(relaunch=now, relaunch_args=args)  # the helper already waiting: tell it what to do now
        else:
            try:
                new = install.arm_swap(staged, rel.version, relaunch=now, relaunch_args=args)
            except install.UpdateError as e:
                QMessageBox.warning(parent, f"{APP} 업데이트", str(e))
                return
            if a is not None:
                a.cancel()  # an earlier one (another version) stands down
            self.armed = new
        install.HARD_EXIT = True
        if dialog is not None:
            dialog.hide()
        if not now:
            self.win.status(f"RetLens를 끌 때 {rel.version}(으)로 업데이트합니다", 10000)
            return
        if not self.win.close():  # a question in closeEvent answered 취소: keep working, apply at quit
            self.armed.set(relaunch=False)
            self.win.status(f"창을 닫지 않았습니다. RetLens를 끌 때 {rel.version}(으)로 업데이트합니다", 10000)

    def busy(self) -> bool:
        d = self.dialog
        return bool(d is not None and d.running()) or bool(self._install_worker and self._install_worker.is_alive())

    def stop_for_close(self) -> bool:
        """closeEvent: a download or install in progress; False keeps the window open."""
        if not self.busy():
            return True
        if QMessageBox.question(self.win, f"{APP} 업데이트", "업데이트를 받거나 설치하는 중입니다. 끄면 멈춥니다(받은 부분은 "
                                "다음에 이어 받습니다). 끌까요?") != QMessageBox.Yes:
            return False
        if self.dialog is not None:
            self.dialog.cancel.set()
            if self.dialog.worker is not None:
                self.dialog.worker.join(timeout=15)
        cancel = getattr(self, "_install_cancel", None)
        if cancel is not None and self._install_worker is not None:
            cancel.set()
            self._install_worker.join(timeout=30)  # the copy stops at the next file and removes what it made
        return True

    # ---------------------------------------------------------- uninstall
    def uninstall(self) -> None:
        """도움말 > RetLens 제거."""
        if not install.is_installed():
            QMessageBox.information(self.win, f"{APP} 제거", "설치된 RetLens에서만 제거합니다.")
            return
        purge = _confirm_uninstall(self.win)
        if purge is None:
            return
        earlier = self.armed
        try:
            self.armed = install.arm_uninstall(purge)
        except install.UpdateError as e:
            QMessageBox.warning(self.win, f"{APP} 제거", str(e))
            return
        if earlier is not None:
            earlier.cancel()  # an update waiting for the exit has nothing left to update
        install.HARD_EXIT = True
        if not self.win.close():
            self.armed.cancel()
            self.armed = None
            install.HARD_EXIT = False
            self.win.status("창을 닫지 않아 제거하지 않았습니다", 8000)


def _confirm_uninstall(parent) -> bool | None:
    """The uninstall question: None = cancel, else whether to delete the settings and caches too."""
    purge_list = install.uninstall_purge_list()
    box = QMessageBox(parent)
    box.setWindowTitle(f"{APP} 제거")
    box.setIcon(QMessageBox.Question)
    box.setText(f"RetLens를 이 PC에서 제거할까요?\n\n지우는 것: 프로그램 폴더({install.install_dir()}), 시작 메뉴·바탕 화면 "
                "바로 가기, Windows '설치된 앱' 항목\n남는 것: 문서\\RetLens(동영상, 모션), 설치 도우미가 받은 Blender·GMT·"
                "SMPL-X 모델, Isaac Sim")
    purge = QCheckBox("설정·캐시·로그·자동 저장도 지우기" + ("" if purge_list else " (사용자 폴더를 바꿔 쓰는 중이라 안 됨)"))
    purge.setEnabled(bool(purge_list))
    box.setCheckBox(purge)
    yes = box.addButton("제거", QMessageBox.DestructiveRole)
    box.addButton("취소", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not yes:
        return None
    return purge.isChecked() and bool(purge_list)


def uninstall_main() -> int:
    """RetLens.exe --uninstall (Windows "설치된 앱" > 제거): ask, arm the helper, exit (it removes the program)."""
    app = QApplication.instance() or QApplication([])  # noqa: F841 (keeps the app)
    if not install.is_installed():
        QMessageBox.information(None, f"{APP} 제거", f"이 RetLens는 설치된 것이 아닙니다({install.program_dir()}).\n"
                                "설치하지 않은 RetLens는 폴더를 지우면 됩니다.")
        return 1
    procs = install.processes_in(install.install_dir())
    if procs:
        QMessageBox.warning(None, f"{APP} 제거", f"RetLens가 실행 중입니다({install.describe_processes(procs)}). 닫은 뒤 다시 "
                            "제거하세요.")
        return 1
    purge = _confirm_uninstall(None)
    if purge is None:
        return 0
    try:
        install.arm_uninstall(purge)
    except install.UpdateError as e:
        QMessageBox.warning(None, f"{APP} 제거", str(e))
        return 1
    install.HARD_EXIT = True
    return 0
