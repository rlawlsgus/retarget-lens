"""retlens/app/runtime.py: a windowless (packaged) run logs to a file and reports uncaught
errors, from the GUI thread and from other threads."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

CODE = r"""
import sys, threading
sys.path.insert(0, sys.argv[1])
from retlens.app import runtime
path = runtime.setup_logging()
print("hello from print")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
shown = []
runtime._show_error = lambda summary, details: shown.append(summary)  # no modal dialog in a test
runtime.install_error_hooks()
runtime._bridge.error.disconnect()
runtime._bridge.error.connect(lambda s, d: shown.append(s))

def boom():
    raise ValueError("gui thread boom")

def worker():
    raise KeyError("worker boom")

QTimer.singleShot(50, boom)
QTimer.singleShot(100, lambda: threading.Thread(target=worker, name="w1").start())
QTimer.singleShot(600, app.quit)
app.exec()
sys.__stdout__.write(repr((path, shown)) + "\n")
"""


def test_log_file_and_error_hooks(tmp_path):
    pytest.importorskip("PySide6")
    env = dict(os.environ, RETLENS_LAYOUT="installed", RETLENS_USER_DIR=str(tmp_path / "user"),
               QT_QPA_PLATFORM="offscreen")
    logs = tmp_path / "user" / "logs"
    logs.mkdir(parents=True)
    for k in range(25):  # old logs: only the newest are kept
        (logs / f"retlens-20200101-0000{k:02d}.log").write_text("old")
    out = subprocess.run([sys.executable, "-c", CODE, ROOT], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    path, shown = eval(out.stdout.strip().splitlines()[-1])
    assert path and path.startswith(str(logs)) and os.path.isfile(path)
    text = open(path, encoding="utf-8").read()
    assert "hello from print" in text and "started; layout installed" in text
    assert "ValueError: gui thread boom" in text and "KeyError: 'worker boom'" in text and "in thread w1" in text
    assert shown == ["ValueError: gui thread boom", "KeyError: 'worker boom'"]  # both reached the GUI thread
    assert len(list(logs.glob("retlens-*.log"))) <= 20
