"""How RetLens starts and fails: the log file, error dialogs, the entry point.

A packaged RetLens is a windowed program: there is no console, so print(), rich, tqdm and
tracebacks would vanish (sys.stdout is None). Installed (or console-less) runs therefore write
them to %LOCALAPPDATA%\\RetLens\\logs\\retlens-<time>.log (the newest 20 are kept), crashes of
the interpreter included (faulthandler). Errors nobody caught show a dialog with the details
and a button to the log folder; one that happens before Qt is up still gets a Windows message
box. Running from the repository keeps everything on the console as before.

    from retlens.app.runtime import main
    sys.exit(main())
"""

from __future__ import annotations

import faulthandler
import glob
import os
import sys
import threading
import time
import traceback

from .. import paths

APP_NAME = "RetLens"
KEEP_LOGS = 20
_log_file = None
_log_path: str | None = None
_shown: set[str] = set()
_dialog_open = False
_bridge = None


def log_path() -> str | None:
    return _log_path


def setup_logging(force: bool = False) -> str | None:
    """Send stdout / stderr to a new log file when installed or without a console (force=True:
    always); returns its path, or None when the console stays."""
    global _log_file, _log_path
    if _log_path is not None:
        return _log_path
    if not (force or paths.INSTALLED or sys.stdout is None or sys.stderr is None):
        return None
    folder = paths.logs_dir()
    try:
        os.makedirs(folder, exist_ok=True)
        for old in sorted(glob.glob(os.path.join(folder, "retlens-*.log")))[:-(KEEP_LOGS - 1)]:
            try:
                os.remove(old)
            except OSError:
                pass
        path = os.path.join(folder, f"retlens-{time.strftime('%Y%m%d-%H%M%S')}.log")
        _log_file = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None
    sys.stdout = sys.stderr = _log_file
    faulthandler.enable(_log_file)  # access violations etc. land in the log too
    _log_path = path
    print(f"[{APP_NAME}] {time.strftime('%Y-%m-%d %H:%M:%S')} started; layout {paths.LAYOUT}; "
          f"python {sys.version.split()[0]}; frozen {paths.FROZEN}", flush=True)
    return path


def _message_box(title: str, text: str) -> None:
    """A message without Qt (it may be what failed to load)."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841 (keeps the app alive)
        QMessageBox.critical(None, title, text)
        return
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # MB_ICONERROR
        except Exception:
            pass


def _show_error(summary: str, details: str) -> None:
    """The dialog for an uncaught error (GUI thread only; once per distinct error)."""
    global _dialog_open
    if _dialog_open or summary in _shown:
        return
    _shown.add(summary)
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(f"{APP_NAME} 오류")
    box.setText("예기치 못한 오류가 났습니다. 하던 작업은 계속할 수 있지만, 같은 문제가 반복되면 로그 파일을 함께 알려 주세요.")
    box.setInformativeText(summary + (f"\n\n로그: {_log_path}" if _log_path else ""))
    box.setDetailedText(details)
    folder = box.addButton("로그 폴더 열기", QMessageBox.ActionRole) if _log_path else None
    box.addButton("닫기", QMessageBox.RejectRole)
    _dialog_open = True
    try:
        box.exec()
    finally:
        _dialog_open = False
    if folder is not None and box.clickedButton() is folder:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(_log_path)))


def install_error_hooks() -> None:
    """Uncaught errors (GUI thread or any other) are logged, then shown in a dialog. Call
    after QApplication exists, from the GUI thread."""
    global _bridge
    from PySide6.QtCore import QObject, Signal

    class _Bridge(QObject):
        error = Signal(str, str)

    _bridge = _Bridge()
    _bridge.error.connect(_show_error)  # queued onto the GUI thread when emitted elsewhere

    def report(exc_type, exc, tb, where: str = "") -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        print(f"[{APP_NAME}] uncaught error{where}:\n{details}", file=sys.stderr, flush=True)
        try:
            _bridge.error.emit(f"{exc_type.__name__}: {exc}", details)
        except Exception:
            pass

    sys.excepthook = lambda t, e, tb: report(t, e, tb)
    threading.excepthook = lambda a: report(a.exc_type, a.exc_value, a.exc_traceback,
                                            f" in thread {a.thread.name if a.thread else '?'}")


def main(argv=None) -> int:
    """Entry point of RetLens (packaged exe and tools/editor.py)."""
    setup_logging()
    try:
        from .editor import run

        return run(argv)
    except SystemExit:
        raise
    except BaseException as e:  # a failure before the window could show it
        details = traceback.format_exc()
        print(f"[{APP_NAME}] failed to start:\n{details}", file=sys.stderr, flush=True)
        _message_box(f"{APP_NAME} 시작 실패", f"{APP_NAME}를 시작하지 못했습니다.\n\n{type(e).__name__}: {e}"
                     + (f"\n\n자세한 내용은 로그 파일에 있습니다:\n{_log_path}" if _log_path else ""))
        return 1
