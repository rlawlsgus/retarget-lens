"""retlens-update: finishes an update, or an uninstall, after RetLens has exited.

A running RetLens holds its own program folder (RetLens.exe, the DLLs in _internal), so it cannot replace or delete
it. This helper does that from outside: RetLens copies it to %LOCALAPPDATA%\\RetLens\\updater\\ and starts it with one
argument, a JSON job file (every path is in the JSON: nothing is quoted on a command line or put into a script).

    retlens-update.exe <job.json>            (built from this file: PyInstaller onefile, windowed)
    python -m retlens.update_helper <job.json>   (from the source tree, tests)

It uses the standard library only and imports nothing from retlens, so it runs on its own. It works like this:

  1. Opens a handle to RetLens (the parent) at once, writes the job's "ready" file and waits for the parent to exit.
     RetLens closes its window only after that file appears.
  2. Reads the job again: the parent may have cancelled it or changed "relaunch" ("종료할 때 업데이트" keeps the
     helper waiting until the user quits, with no relaunch).
  3. Takes the update lock (named mutex Local\\RetLens-Update) that every RetLens window also takes while it
     downloads, stages or cleans up.
  4. swap: checks the staged folder against its stamp and the build manifest (every file, by size), writes a journal
     and an HKCU RunOnce recovery entry, renames the install folder to RetLens.old-<stamp> (retrying: another
     program may still hold a file; after a minute it asks), renames the staged folder into its place (putting the
     old one back if that fails), and moves files the user had put into the old folder (anything the build does not
     ship, e.g. GMT next to RetLens.exe) into the new one. It then starts the new RetLens and waits for it to write
     update_started.json. If it exits first, the swap is undone and the old version starts again.
     uninstall: checks that the folder is RetLens's own (its retlens-install.json id), renames it first (nothing is
     touched when that fails), then removes the shortcuts, the "installed apps" entry and the folder.
     recover: (the RunOnce entry, at the next sign-in) finishes or undoes a swap that was cut off.
  5. Writes update_result.json for RetLens's next start and a log next to it.

Nothing is deleted outside the folders the job names, and only after checking what they are.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

MUTEX_NAME = "Local\\RetLens-Update"
RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
RUNONCE_VALUE = "RetLensUpdateRecover"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\RetLens"
QSETTINGS_KEY = r"Software\RetLens"
SHIPPED = ("RetLens.exe", "retlens-cli.exe", "retlens-update.exe", "_internal", "retlens-install.json",
           ".retlens-staged.json")
STAMP = ".retlens-staged.json"
MARKER = "retlens-install.json"
MANIFEST = os.path.join("_internal", "retlens-build.json")
TITLE = "RetLens 업데이트"

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_ABANDONED = 0x0, 0x102, 0x80
INFINITE = 0xFFFFFFFF
MB_OK, MB_RETRYCANCEL, MB_YESNO = 0x0, 0x5, 0x4
MB_ICONWARNING, MB_ICONINFORMATION, MB_ICONERROR = 0x30, 0x40, 0x10
MB_TOPMOST, MB_SETFOREGROUND = 0x40000, 0x10000
IDRETRY, IDYES = 4, 6
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
ENV_DROP_PREFIXES = ("QTWEBENGINE", "_PYI_", "_MEIPASS")  # (RETLENS_TEST* passes: test sandboxes need it)
ENV_DROP = ("QTWEBENGINEPROCESS_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")


# ------------------------------------------------------------------ small things
class Job(dict):
    """The job file's contents (and where it is)."""

    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            super().__init__(json.load(f))
        self.path = path

    def reload(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.update(json.load(f))
        except (OSError, ValueError):
            pass


_log_path: str | None = None


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    if _log_path:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def write_json(path: str | None, data: dict) -> None:
    """ASCII JSON (Korean text escaped), written whole: a reader never sees half a file."""
    if not path:
        return
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        log(f"could not write {path}: {e}")


def read_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def message(text: str, flags: int = MB_OK | MB_ICONWARNING) -> int:
    """A Windows message box (the helper has no window of its own); 0 when there is no desktop."""
    if os.name != "nt" or os.environ.get("RETLENS_UPDATE_NO_UI"):
        log(f"message (no UI): {text}")
        return 0
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags | MB_TOPMOST | MB_SETFOREGROUND)
    except Exception:
        return 0


def same_path(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def inside(path: str | None, folder: str | None) -> bool:
    """path is strictly inside folder (both resolved)."""
    if not path or not folder:
        return False
    p, f = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    return p != f and p.startswith(f.rstrip("\\/") + os.sep)


def is_reparse_point(path: str) -> bool:
    try:
        return bool(os.lstat(path).st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def clean_env() -> dict:
    """This environment without what belongs to one frozen program (PyInstaller's and Qt WebEngine's paths), so a
    RetLens started from here uses its own bundle."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ENV_DROP and not k.upper().startswith(ENV_DROP_PREFIXES)}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start(exe: str, args: list[str], cwd: str) -> subprocess.Popen | None:
    """Start a program on its own (new process group, out of RetLens's job if allowed)."""
    base = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    cwd = cwd if cwd and os.path.isdir(cwd) else os.path.expanduser("~")
    for flags in (base | breakaway, base):
        try:
            return subprocess.Popen([exe, *args], cwd=cwd, env=clean_env(), creationflags=flags, close_fds=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"start {exe} (flags {flags:#x}) failed: {e}")
    return None


# ------------------------------------------------------------------ Windows objects
class Mutex:
    """The update lock shared with every RetLens (retlens.install.update_lock)."""

    def __init__(self, timeout_s: float):
        self.handle = None
        if os.name != "nt":
            return
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        self.handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle:
            raise OSError("CreateMutexW failed")
        r = k32.WaitForSingleObject(ctypes.c_void_p(self.handle), int(timeout_s * 1000))
        if r not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            k32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None
            raise TimeoutError("another RetLens update is running")

    def release(self) -> None:
        if self.handle:
            k32 = ctypes.windll.kernel32
            k32.ReleaseMutex(ctypes.c_void_p(self.handle))
            k32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def open_process(pid: int | None):
    if os.name != "nt" or not pid:
        return None
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    return h or None


def wait_process(handle, timeout_s: float | None) -> bool:
    """True when the process has exited (or there was none to wait for)."""
    if handle is None:
        return True
    ms = INFINITE if timeout_s is None else int(max(0.0, timeout_s) * 1000)
    return ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(handle), ms) == WAIT_OBJECT_0


def close_handle(handle) -> None:
    if handle is not None and os.name == "nt":
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def set_runonce(command: str | None) -> None:
    """The recovery entry run at the next sign-in (None removes it)."""
    if os.name != "nt" or os.environ.get("RETLENS_NO_REGISTRY"):
        return
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUNONCE_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if command:
                winreg.SetValueEx(k, RUNONCE_VALUE, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(k, RUNONCE_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as e:
        log(f"RunOnce: {e}")


# ------------------------------------------------------------------ folders
def retry(fn, what: str, seconds: float, ask: str | None = None) -> bool:
    """fn() until it works or `seconds` pass; then, with ask, a retry / cancel box. True when it worked."""
    while True:
        end = time.time() + seconds
        delay = 0.25
        while True:
            try:
                fn()
                return True
            except OSError as e:
                last = e
            if time.time() >= end:
                break
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
        log(f"{what} failed: {last}")
        if not ask or message(f"{ask}\n\n({last})", MB_RETRYCANCEL | MB_ICONWARNING) != IDRETRY:
            return False


def manifest_files(folder: str) -> dict[str, int] | None:
    """{relative path: size} of the build manifest in a RetLens folder (None: no usable manifest)."""
    data = read_json(os.path.join(folder, MANIFEST))
    files = (data or {}).get("files")
    if not isinstance(files, dict) or not files:
        return None
    return {str(k): int(v) for k, v in files.items()}


def check_folder(folder: str, version: str | None = None) -> str | None:
    """Why the folder is not a complete RetLens build (None: it is): every manifest file there with its size, the
    manifest of this version."""
    data = read_json(os.path.join(folder, MANIFEST))
    if data is None:
        return "빌드 목록(retlens-build.json)이 없습니다"
    if version and str(data.get("version")) != version:
        return f"빌드 버전이 {data.get('version')}입니다({version}이어야 함)"
    files = manifest_files(folder) or {}
    for rel, size in files.items():
        p = os.path.join(folder, rel)
        try:
            if os.path.getsize(p) != size:
                return f"{rel}의 크기가 다릅니다"
        except OSError:
            return f"{rel}이(가) 없습니다"
    return None


def extras(old: str, new: str) -> list[str]:
    """Top-level entries of the old folder that the build does not ship and the new folder does not have."""
    try:
        names = os.listdir(old)
    except OSError:
        return []
    return [n for n in names if n not in SHIPPED and not os.path.exists(os.path.join(new, n))]


def move_extras(old: str, new: str) -> list[str]:
    """Move the user's own entries (see extras) from old to new; the names that could not be moved."""
    left = []
    for n in extras(old, new):
        try:
            os.replace(os.path.join(old, n), os.path.join(new, n))
            log(f"kept {n} (moved into the new folder)")
        except OSError as e:
            left.append(n)
            log(f"could not move {n}: {e}")
    return left


def remove_build(path: str) -> bool:
    """Delete a RetLens folder of ours: what a build ships (never through a junction), then the folder if that
    leaves it empty. A folder that still holds the user's own files is kept. True when it is gone."""
    if not os.path.isdir(path) or is_reparse_point(path):
        return not os.path.lexists(path)
    for entry in SHIPPED:
        e = os.path.join(path, entry)
        if is_reparse_point(e):
            try:
                os.rmdir(e)
            except OSError:
                pass
        elif os.path.isdir(e):
            shutil.rmtree(e, ignore_errors=True)
        elif os.path.lexists(e):
            try:
                os.remove(e)
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        log(f"kept {path} (it holds other files)")
        return False
    return True


def stamp_name(prefix: str) -> str:
    return f"{prefix}{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ actions
BUSY = ("RetLens 프로그램 폴더의 파일을 다른 프로그램이 쓰고 있습니다. 다른 RetLens 창, retlens-cli, 그 폴더를 연 "
        "탐색기 창을 닫고 '다시 시도'를 누르세요. '취소'를 누르면 지금은 업데이트하지 않습니다.")


def swap(job: Job) -> dict:
    """Put the staged build in the install folder's place (see the module text); the result for RetLens."""
    install, staged = job["install"], job["staged"]
    old = os.path.join(os.path.dirname(install), stamp_name("RetLens.old-"))
    result = {"action": "swap", "from": job.get("from"), "to": job.get("to"), "install": install, "ok": False}
    why = check_folder(staged, job.get("to"))
    stamp = read_json(os.path.join(staged, STAMP))
    if why is None and (stamp is None or stamp.get("version") != job.get("to")):
        why = "검증 표시(.retlens-staged.json)가 없거나 버전이 다릅니다"
    if why:
        result["error"] = f"받아 둔 새 버전이 온전하지 않습니다: {why}"
        return result
    if not os.path.isdir(install):
        result["error"] = f"설치 폴더가 없습니다: {install}"
        return result
    journal = job.get("journal")
    write_json(journal, {"install": install, "old": old, "staged": staged, "to": job.get("to"),
                         "from": job.get("from"), "phase": "start", "time": time.time()})
    if job.get("recover_command"):
        set_runonce(job["recover_command"])
    wait = float(job.get("retry_s", 60.0))  # how long a held file is waited out before asking
    if not retry(lambda: os.rename(install, old), "rename install -> old", wait, BUSY):
        result["error"] = "프로그램 폴더를 쓰는 프로그램이 있어 바꾸지 못했습니다"
        _end_journal(journal)
        return result
    write_json(journal, {"install": install, "old": old, "staged": staged, "to": job.get("to"),
                         "from": job.get("from"), "phase": "old-moved", "time": time.time()})
    if not retry(lambda: os.rename(staged, install), "rename staged -> install", wait):
        put_back = retry(lambda: os.rename(old, install), "put the old folder back", float(job.get("putback_s", 600.0)),
                         "이전 버전을 제자리에 돌려놓지 못했습니다. 프로그램 폴더를 쓰는 프로그램을 닫고 '다시 시도'를 누르세요.")
        result["error"] = "새 버전을 제자리에 넣지 못해 이전 버전으로 돌려놓았습니다" if put_back else \
            f"새 버전을 넣지 못했고 이전 버전도 돌려놓지 못했습니다. {old} 폴더 이름을 {os.path.basename(install)}로 바꾸세요"
        if put_back:
            _end_journal(journal)
        return result
    left = move_extras(old, install)
    write_json(journal, {"install": install, "old": old, "staged": staged, "to": job.get("to"),
                         "from": job.get("from"), "phase": "swapped", "time": time.time()})
    result.update(ok=True, old=old, kept_in_old=left)
    return result


def _end_journal(journal: str | None) -> None:
    if journal:
        try:
            os.remove(journal)
        except OSError:
            pass
    set_runonce(None)


def undo_swap(job: Job, result: dict) -> bool:
    """The new version did not start: put the old one back (the user's entries moved back with it)."""
    install, old = job["install"], result.get("old")
    if not old or not os.path.isdir(old):
        return False
    failed = os.path.join(os.path.dirname(install), stamp_name("RetLens.failed-"))
    if not retry(lambda: os.rename(install, failed), "rename new -> failed", float(job.get("retry_s", 60.0)), BUSY):
        return False
    for n in extras(failed, old):
        try:
            os.replace(os.path.join(failed, n), os.path.join(old, n))
        except OSError as e:
            log(f"could not move {n} back: {e}")
    return retry(lambda: os.rename(old, install), "put the old folder back", float(job.get("putback_s", 600.0)),
                 "이전 버전을 제자리에 돌려놓지 못했습니다. 프로그램 폴더를 쓰는 프로그램을 닫고 '다시 시도'를 누르세요.")


def health(job: Job, proc: subprocess.Popen | None) -> str:
    """'ok' when the new RetLens wrote update_started.json for this version, 'exited' when it quit first,
    'unknown' after the wait (a slow start is not a failure)."""
    marker, to = job.get("started_marker"), job.get("to")
    end = time.time() + float(job.get("health_timeout_s", 120))
    while time.time() < end:
        data = read_json(marker)
        if data and data.get("version") == to:
            return "ok"
        if proc is not None and proc.poll() is not None:
            time.sleep(1.0)  # its marker may land just as it exits
            data = read_json(marker)
            return "ok" if data and data.get("version") == to else "exited"
        time.sleep(0.5)
    return "unknown"


def run_swap(job: Job) -> dict:
    result = swap(job)
    install = job["install"]
    exe = os.path.join(install, "RetLens.exe")
    relaunch = bool(job.get("relaunch"))
    if result.get("ok"):
        if relaunch:
            proc = start(exe, list(job.get("relaunch_args") or []), job.get("workdir") or "")
            state = health(job, proc) if proc is not None else "exited"  # could not even be started: the same
            result["health"] = state
            log(f"new version health: {state}")
            if state == "exited":
                if undo_swap(job, result):
                    result.update(ok=False, error="새 버전이 시작하지 못해 이전 버전으로 되돌렸습니다", undone=True)
                    start(exe, [], job.get("workdir") or "")
                else:  # the journal and the RunOnce entry stay: the next start (or sign-in) puts the old one back
                    result.update(ok=False, error="새 버전이 시작하지 못했고, 이전 버전으로 되돌리지도 못했습니다. "
                                                  "다시 로그인하면 되돌립니다")
                    message(result["error"], MB_OK | MB_ICONERROR)
                    return result
        _end_journal(job.get("journal"))
    elif relaunch and os.path.isfile(exe):
        start(exe, [], job.get("workdir") or "")  # the old version, as it was
    return result


def run_uninstall(job: Job) -> dict:
    install = job["install"]
    result = {"action": "uninstall", "install": install, "ok": False}
    marker = read_json(os.path.join(install, MARKER))
    if (not os.path.isdir(install) or is_reparse_point(install) or not marker or marker.get("product") != "RetLens"
            or marker.get("id") != job.get("install_id") or not os.path.isfile(os.path.join(install, "RetLens.exe"))):
        result["error"] = "RetLens 설치 폴더가 아니어서 지우지 않았습니다"
        message(f"{install}\n\n{result['error']}.", MB_OK | MB_ICONERROR)
        return result
    gone = os.path.join(os.path.dirname(install), stamp_name("RetLens.uninstall-"))
    if not retry(lambda: os.rename(install, gone), "rename install -> uninstall", float(job.get("retry_s", 30.0)),
                 BUSY):
        result["error"] = "프로그램 폴더를 쓰는 프로그램이 있어 제거하지 못했습니다"
        return result
    for lnk in job.get("shortcuts") or []:
        try:
            if lnk.lower().endswith(".lnk") and os.path.isfile(lnk):
                os.remove(lnk)
        except OSError as e:
            log(f"shortcut {lnk}: {e}")
    remove_uninstall_entry(install, job.get("install_id"))
    left = not remove_build(gone)
    for name in os.listdir(os.path.dirname(install)) if os.path.isdir(os.path.dirname(install)) else []:
        if name.startswith(("RetLens.old-", "RetLens.update-", "RetLens.failed-", "RetLens.install-",
                            "RetLens.uninstall-")):
            remove_build(os.path.join(os.path.dirname(install), name))
    for p in job.get("purge") or []:  # the user's data, when asked: an explicit list made by RetLens
        try:
            if is_reparse_point(p) or not inside(p, job.get("user_dir")):
                log(f"purge {p}: not inside {job.get('user_dir')}, kept")
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
        except OSError as e:
            log(f"purge {p}: {e}")
    if job.get("purge_settings"):
        delete_registry_tree(QSETTINGS_KEY)
    result.update(ok=True, leftover=gone if left else None)
    if not os.environ.get("RETLENS_UPDATE_NO_UI"):
        message("RetLens를 제거했습니다." + (f"\n\n지우지 않고 남긴 파일이 있습니다(RetLens 것이 아닌 파일): {gone}"
                                         if left else ""), MB_OK | MB_ICONINFORMATION)
    return result


def remove_uninstall_entry(install: str, install_id: str | None) -> None:
    if os.name != "nt" or os.environ.get("RETLENS_NO_REGISTRY"):
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            where = winreg.QueryValueEx(k, "InstallLocation")[0]
            try:
                their_id = winreg.QueryValueEx(k, "RetLensInstallId")[0]
            except FileNotFoundError:
                their_id = None
        if os.path.normcase(os.path.abspath(where)) != os.path.normcase(os.path.abspath(install)) or \
                (install_id and their_id and their_id != install_id):
            log("uninstall entry belongs to another install: kept")
            return
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"uninstall entry: {e}")


def delete_registry_tree(sub: str) -> None:
    if os.name != "nt" or os.environ.get("RETLENS_NO_REGISTRY"):
        return
    import winreg

    def rm(key_path: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        child = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    rm(f"{key_path}\\{child}")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            log(f"registry {key_path}: {e}")

    rm(sub)


def run_recover(job: Job) -> dict:
    """Finish or undo a swap that was cut off (power loss, a crash between the renames)."""
    j = read_json(job.get("journal"))
    result = {"action": "recover", "ok": True}
    if not j:
        set_runonce(None)
        return result
    install, old, staged = j.get("install"), j.get("old"), j.get("staged")
    if install and not os.path.exists(install):
        if staged and os.path.isdir(staged) and check_folder(staged, j.get("to")) is None:
            ok = retry(lambda: os.rename(staged, install), "recover: staged -> install", 120.0)
            if ok and old:
                move_extras(old, install)
            result.update(ok=ok, recovered="forward")
        elif old and os.path.isdir(old):
            result.update(ok=retry(lambda: os.rename(old, install), "recover: old -> install", 120.0),
                          recovered="back")
    if result["ok"]:
        _end_journal(job.get("journal"))
    else:
        message("RetLens 업데이트를 마치지 못했습니다. RetLens 폴더를 확인하세요.", MB_OK | MB_ICONERROR)
    return result


ACTIONS = {"swap": run_swap, "uninstall": run_uninstall, "recover": run_recover}


def main(argv: list[str] | None = None) -> int:
    global _log_path
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        message("RetLens가 업데이트할 때 쓰는 도구입니다. 직접 실행하지 않습니다.", MB_OK | MB_ICONINFORMATION)
        return 2
    try:
        job = Job(argv[0])
    except (OSError, ValueError) as e:
        message(f"업데이트 작업 파일을 읽지 못했습니다: {e}", MB_OK | MB_ICONERROR)
        return 2
    if "--recover" in argv[1:]:
        job["action"] = "recover"
    _log_path = job.get("log")
    try:
        os.chdir(os.path.dirname(os.path.abspath(job.path)))  # never inside a program folder
    except OSError:
        pass
    log(f"helper {job.get('action')} for RetLens {job.get('from')} -> {job.get('to')} (pid {os.getpid()})")
    action = ACTIONS.get(job.get("action"))
    if action is None:
        log(f"unknown action {job.get('action')}")
        return 2
    parent = open_process(job.get("parent_pid")) if job.get("action") != "recover" else None
    write_json(job.get("ready"), {"pid": os.getpid(), "time": time.time()})
    if parent is not None:
        log("waiting for RetLens to exit")
        wait_process(parent, job.get("wait_s"))  # None: until the user quits (종료할 때 업데이트)
        close_handle(parent)
    job.reload()
    if job.get("cancelled"):
        log("cancelled by RetLens")
        return 0
    try:
        lock = Mutex(timeout_s=600.0)
    except (OSError, TimeoutError) as e:
        result = {"action": job.get("action"), "ok": False, "error": f"다른 업데이트가 진행 중입니다 ({e})"}
        write_json(job.get("result"), {**result, "time": time.time()})
        exe = os.path.join(job.get("install") or "", "RetLens.exe")
        if job.get("action") == "swap" and job.get("relaunch") and os.path.isfile(exe):
            start(exe, [], job.get("workdir") or "")  # the version that was there, as promised
        return 1
    try:
        result = action(job)
    except Exception as e:  # never die silently: the next RetLens start shows it
        log(f"failed: {type(e).__name__}: {e}")
        result = {"action": job.get("action"), "ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        lock.release()
    if not (job.get("action") == "uninstall" and result.get("ok") and job.get("purge_settings")):
        write_json(job.get("result"), {**result, "time": time.time(), "log": _log_path})
    log(f"done: {json.dumps(result, ensure_ascii=True)}")
    if not result.get("ok") and job.get("action") == "swap" and not job.get("relaunch"):
        message(f"RetLens 업데이트를 마치지 못했습니다.\n\n{result.get('error', '')}", MB_OK | MB_ICONWARNING)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
