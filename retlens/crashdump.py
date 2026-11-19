"""Crash dumps (Windows): when RetLens dies of a native error the Python traceback alone cannot explain (heap
corruption, an access violation inside Qt / MuJoCo / numpy), a minidump is written next to the logs.

faulthandler (retlens.app.runtime) prints where each Python thread was, which is all a log can say: the code that
broke the memory is usually native and ran earlier. The minidump has the native stacks of every thread and the
loaded modules, so a debugger (WinDbg, Visual Studio) shows which library it was. The log gets one line with the
dump's path and the module the error happened in.

    install(folder, log_file)   # once, after faulthandler.enable(log_file): this handler then runs first

How: a vectored exception handler (AddVectoredExceptionHandler, as faulthandler uses) sees the error before the
process ends, writes the dump with dbghelp's MiniDumpWriteDump and lets the error go on (faulthandler prints its
traceback, Windows ends the process). Only the errors that end a process are dumped (FATAL), and only the first
one: a handled first-chance access violation would make one needless dump at most. The newest KEEP dumps are kept.
Nothing happens on other systems."""

from __future__ import annotations

import glob
import os
import sys
import time

FATAL = {
    0xC0000005: "access violation",
    0xC0000374: "heap corruption",
    0xC000001D: "illegal instruction",
    0xC0000096: "privileged instruction",
    0xC0000409: "stack buffer overrun",
    0xC0000094: "integer divide by zero",
    0xC0000420: "assertion failure",
}
KEEP = 3  # dumps are tens of MB
PREFIX = "retlens-crash-"
# MiniDumpWithHandleData | WithUnloadedModules | WithIndirectlyReferencedMemory | WithProcessThreadData |
# WithThreadInfo: native stacks with the memory they point at, small enough to keep a few
DUMP_TYPE = 0x4 | 0x20 | 0x40 | 0x100 | 0x1000

_state: dict = {}  # the handler, the folder, the log file: alive as long as the process


def dumps(folder: str) -> list[str]:
    """The crash dumps in folder, oldest first."""
    return sorted(glob.glob(os.path.join(folder, PREFIX + "*.dmp")))


def install(folder: str, log_file=None) -> bool:
    """Write a minidump into folder when the process dies of a native error; True when the handler is in."""
    if sys.platform != "win32" or _state:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        os.makedirs(folder, exist_ok=True)
        for old in dumps(folder)[:-(KEEP - 1)]:  # room for this run's
            try:
                os.remove(old)
            except OSError:
                pass
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        dbghelp = ctypes.WinDLL("dbghelp")

        class EXCEPTION_RECORD(ctypes.Structure):
            _fields_ = [("ExceptionCode", wintypes.DWORD), ("ExceptionFlags", wintypes.DWORD),
                        ("ExceptionRecord", ctypes.c_void_p), ("ExceptionAddress", ctypes.c_void_p),
                        ("NumberParameters", wintypes.DWORD), ("ExceptionInformation", ctypes.c_size_t * 15)]

        class EXCEPTION_POINTERS(ctypes.Structure):
            _fields_ = [("ExceptionRecord", ctypes.POINTER(EXCEPTION_RECORD)), ("ContextRecord", ctypes.c_void_p)]

        class MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
            _pack_ = 4  # dbghelp.h declares it inside pshpack4.h
            _fields_ = [("ThreadId", wintypes.DWORD), ("ExceptionPointers", ctypes.c_void_p),
                        ("ClientPointers", wintypes.BOOL)]

        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetModuleHandleExW.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE)]
        k32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        k32.AddVectoredExceptionHandler.restype = ctypes.c_void_p
        k32.AddVectoredExceptionHandler.argtypes = [wintypes.ULONG, ctypes.c_void_p]
        dbghelp.MiniDumpWriteDump.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        dbghelp.MiniDumpWriteDump.restype = wintypes.BOOL
        INVALID = ctypes.c_void_p(-1).value
        GENERIC_WRITE, CREATE_ALWAYS, NORMAL = 0x40000000, 2, 0x80
        FROM_ADDRESS, UNCHANGED_REFCOUNT = 0x4, 0x2
        CONTINUE_SEARCH = 0

        def module_of(addr) -> str:
            h = wintypes.HMODULE()
            if not addr or not k32.GetModuleHandleExW(FROM_ADDRESS | UNCHANGED_REFCOUNT, addr, ctypes.byref(h)):
                return "?"
            buf = ctypes.create_unicode_buffer(520)
            k32.GetModuleFileNameW(h, buf, 520)
            return buf.value or "?"

        def say(text: str) -> None:
            f = _state.get("log")
            try:
                if f is not None:
                    f.write(text + "\n")
                    f.flush()
                else:
                    sys.__stderr__.write(text + "\n")
            except Exception:
                pass

        @ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(EXCEPTION_POINTERS))
        def handler(info):
            try:
                rec = info.contents.ExceptionRecord.contents
                code = rec.ExceptionCode & 0xFFFFFFFF
                if code not in FATAL or _state.get("done"):
                    return CONTINUE_SEARCH
                _state["done"] = True
                where = module_of(rec.ExceptionAddress)
                path = os.path.join(folder, f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.dmp")
                h = k32.CreateFileW(path, GENERIC_WRITE, 0, None, CREATE_ALWAYS, NORMAL, None)
                ok = False
                if h and h != INVALID:
                    mei = MINIDUMP_EXCEPTION_INFORMATION(k32.GetCurrentThreadId(), ctypes.cast(info, ctypes.c_void_p), False)
                    ok = bool(dbghelp.MiniDumpWriteDump(k32.GetCurrentProcess(), k32.GetCurrentProcessId(), h, DUMP_TYPE,
                                                        ctypes.byref(mei), None, None))
                    k32.CloseHandle(h)
                say(f"[crash] {FATAL[code]} (0x{code:08X}) in {where}; "
                    + (f"crash dump: {path}" if ok else "crash dump could not be written"))
            except Exception:
                pass
            return CONTINUE_SEARCH

        _state.update(handler=handler, folder=folder, log=log_file)
        if not k32.AddVectoredExceptionHandler(1, ctypes.cast(handler, ctypes.c_void_p)):  # 1: before faulthandler's
            _state.clear()
            return False
        return True
    except Exception:
        _state.clear()
        return False
