"""retlens.crashdump: a native crash leaves a minidump and a line in the log."""

import os
import subprocess
import sys

import pytest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows minidumps")

CRASH = r"""
import faulthandler, sys
sys.path.insert(0, sys.argv[1])
from retlens import crashdump
log = open(sys.argv[3], "a", encoding="utf-8", buffering=1)
faulthandler.enable(log)
assert crashdump.install(sys.argv[2], log)
assert not crashdump.install(sys.argv[2], log)  # once
import ctypes
ctypes.c_int.from_address(8).value  # a real access violation (faulthandler._sigsegv only raises SIGSEGV)
"""


def test_a_native_crash_leaves_a_dump_and_a_log_line(tmp_path):
    folder, log = tmp_path / "logs", tmp_path / "run.log"
    for i in range(4):  # older dumps: the newest KEEP stay, this run's included
        folder.mkdir(exist_ok=True)
        (folder / f"retlens-crash-2026010{i}-000000-1.dmp").write_bytes(b"x")
    r = subprocess.run([sys.executable, "-I", "-c", CRASH, REPO, str(folder), str(log)], capture_output=True,
                       timeout=120)
    assert r.returncode != 0
    from retlens import crashdump

    found = crashdump.dumps(str(folder))
    assert len(found) == crashdump.KEEP
    new = found[-1]
    assert "retlens-crash-2026010" not in os.path.basename(new) and os.path.getsize(new) > 10_000
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "[crash] access violation (0xC0000005)" in text and new in text
    assert "Windows fatal exception: access violation" in text  # faulthandler still prints the Python stacks
    assert text.index("[crash]") < text.index("Windows fatal exception")  # the dump first
