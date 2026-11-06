"""RetLens on this PC: install it (Start menu, "installed apps"), update it from GitHub Releases, uninstall it.

No Qt here (retlens/app/update_ui.py is the window side, retlens-cli update the command line), and only the
standard library. Everything happens per user, without administrator rights:

    program     %LOCALAPPDATA%\\Programs\\RetLens\\        (FOLDERID_UserProgramFiles\\RetLens; RetLens.exe,
                                                         retlens-cli.exe, retlens-update.exe, _internal\\,
                                                         retlens-install.json = our id, version, source)
    shortcuts   Start menu\\Programs\\RetLens.lnk (always), Desktop\\RetLens.lnk (when asked)
    registry    HKCU\\...\\Uninstall\\RetLens ("installed apps": version, uninstall command)
    user data   %LOCALAPPDATA%\\RetLens (unchanged by install / update: settings, caches, tools, sessions) with
                updater\\ (helper copies, job files, logs), downloads\\, update_result.json / update_started.json

A copy unzipped anywhere else is "portable". It can install itself (copy its files, register, start the installed
one after its window has closed). An update downloads RetLens-<ver>-win64.zip from the latest release (checking its
SHA-256 against the release's digest and .sha256 file), unpacks it next to the install folder
(RetLens.update-<ver>\\) and checks it against its build manifest (_internal\\retlens-build.json) and by running its
retlens-cli.exe version. The running program cannot replace its own folder, so retlens/update_helper.py
(retlens-update.exe, started from a copy in updater\\) swaps the folders once RetLens has exited, starts the new
version and swaps back if it does not come up. The new version deletes the old folder after it has started.

Every network request goes to GitHub only (redirects to other hosts or to http are refused), and nothing is
deleted outside RetLens's own folders. Install / update / uninstall work only in the packaged program
(paths.FROZEN); from the source tree only the check works.

Test overrides (honoured only from the source tree or with RETLENS_TEST=1): RETLENS_INSTALL_DIR,
RETLENS_START_MENU_DIR, RETLENS_DESKTOP_DIR, RETLENS_NO_REGISTRY=1, RETLENS_UPDATE_API (localhost only).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Callable

from . import __version__, paths
from . import update_helper as helper

REPO = "rlawlsgus/retarget-lens"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
GITHUB_HOSTS = frozenset({"api.github.com", "github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com"})
USER_AGENT = f"RetLens/{__version__} (+https://github.com/{REPO})"
APP = "RetLens"
AUMID = "RetLens.Editor"  # the window's AppUserModelID (retlens/app/editor.py run()); the shortcut carries it too
TAG_RE = re.compile(r"^v(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
ASSET_RE = re.compile(r"^RetLens-(\d{1,4}\.\d{1,4}\.\d{1,4})-win64\.zip$")
SHA_LINE_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)\s*$")
SHIPPED = ("RetLens.exe", "retlens-cli.exe", "retlens-update.exe", "_internal")
MARKER, STAMP, MANIFEST = helper.MARKER, helper.STAMP, helper.MANIFEST
UNINSTALL_KEY = helper.UNINSTALL_KEY
CHECK_EVERY_S = 20 * 3600  # the automatic check at start-up, at most this often
NEED_MARGIN = 1.15  # free space: what a step needs, plus 15 %
WINDOWS_BAD_NAME = re.compile(r'(^|/)(CON|PRN|AUX|NUL|COM\d|LPT\d)(\.[^/]*)?(/|$)|[<>"|?*\x00-\x1f]|[ .](/|$)', re.I)

Progress = Callable[[str, float, float], None]  # (stage, done, total)


# What runs once the window has closed (retlens/app/runtime.py main): start the installed copy, ... HARD_EXIT: an
# armed helper waits for this process, so it ends with os._exit (a stray thread must not keep it alive).
AFTER_EXIT: list[Callable[[], None]] = []
HARD_EXIT = False


def run_after_exit() -> None:
    while AFTER_EXIT:
        fn = AFTER_EXIT.pop(0)
        try:
            fn()
        except Exception as e:
            print(f"[RetLens] after exit: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


class UpdateError(RuntimeError):
    """A failure to show the user as it is (Korean text)."""


class Busy(UpdateError):
    """Another RetLens is updating, or programs hold the install folder."""


# ------------------------------------------------------------------ versions
def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """'0.9.1' or 'v0.9.1' -> (0, 9, 1); anything else -> None."""
    m = TAG_RE.match(text if (text or "").startswith("v") else f"v{text or ''}")
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(candidate: str | None, than: str | None) -> bool:
    a, b = parse_version(candidate), parse_version(than)
    return a is not None and (b is None or a > b)


# ------------------------------------------------------------------ where things are
def _testing() -> bool:
    return not paths.FROZEN or os.environ.get("RETLENS_TEST") == "1"


def _override(name: str) -> str | None:
    v = os.environ.get(name)
    return os.path.abspath(v) if v and _testing() else None


FOLDERID = {"UserProgramFiles": "{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}",
            "Programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",  # Start menu\Programs
            "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
            "LocalAppData": "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}",
            "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        u = uuid.UUID(text)
        return cls(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def known_folder(name: str) -> str | None:
    """A Windows known folder where it really is (redirected to OneDrive, a network share, ...)."""
    if os.name != "nt":
        return None
    try:
        out = ctypes.c_wchar_p()
        g = _GUID.of(FOLDERID[name])
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path or None
    except Exception:
        pass
    return None


def install_dir() -> str:
    """Where RetLens installs: %LOCALAPPDATA%\\Programs\\RetLens."""
    o = _override("RETLENS_INSTALL_DIR")
    if o:
        return o
    base = known_folder("UserProgramFiles")
    if not base:
        local = known_folder("LocalAppData") or os.environ.get("LOCALAPPDATA") or \
            os.path.join(os.path.expanduser("~"), "AppData", "Local")
        base = os.path.join(local, "Programs")
    return os.path.join(base, APP)


def start_menu_dir() -> str:
    return _override("RETLENS_START_MENU_DIR") or known_folder("Programs") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "Microsoft", "Windows", "Start Menu", "Programs")


def desktop_dir() -> str:
    return _override("RETLENS_DESKTOP_DIR") or known_folder("Desktop") or os.path.join(os.path.expanduser("~"), "Desktop")


def shortcut_paths() -> dict[str, str]:
    return {"start_menu": os.path.join(start_menu_dir(), f"{APP}.lnk"),
            "desktop": os.path.join(desktop_dir(), f"{APP}.lnk")}


def program_dir() -> str | None:
    """The folder of the running packaged program (None from the source tree)."""
    return os.path.dirname(os.path.realpath(sys.executable)) if paths.FROZEN else None


def same_path(a: str | None, b: str | None) -> bool:
    return helper.same_path(a, b)


def is_installed() -> bool:
    """This program runs from the install folder."""
    return paths.FROZEN and same_path(program_dir(), install_dir())


def is_portable() -> bool:
    return paths.FROZEN and not is_installed()


def updater_dir() -> str:
    return os.path.join(paths.user_dir(), "updater")


def downloads_dir() -> str:
    return os.path.join(paths.user_dir(), "downloads")


def result_path() -> str:
    return os.path.join(paths.user_dir(), "update_result.json")


def started_path() -> str:
    return os.path.join(paths.user_dir(), "update_started.json")


def journal_path() -> str:
    return os.path.join(paths.user_dir(), "update_pending.json")


def neutral_cwd() -> str:
    """A working folder for spawned programs that is never a program folder (a process's working folder keeps
    that folder from being renamed)."""
    for d in (paths.user_dir(), os.path.expanduser("~"), tempfile.gettempdir()):
        if d and os.path.isdir(d):
            return d
    return os.getcwd()


# ------------------------------------------------------------------ builds on disk
def read_manifest(folder: str) -> dict | None:
    return helper.read_json(os.path.join(folder, MANIFEST))


def folder_version(folder: str | None) -> str | None:
    """The version of the RetLens build in a folder (from its manifest, without running it)."""
    if not folder:
        return None
    v = (read_manifest(folder) or {}).get("version")
    return str(v) if parse_version(str(v or "")) else None


def read_marker(folder: str) -> dict | None:
    m = helper.read_json(os.path.join(folder, MARKER))
    return m if m and m.get("product") == APP else None


def installed_info() -> dict | None:
    """The installed RetLens (the install folder holding a build): {dir, version, id, source}."""
    d = install_dir()
    if not os.path.isfile(os.path.join(d, "RetLens.exe")):
        return None
    marker = read_marker(d) or {}
    return {"dir": d, "version": folder_version(d), "id": marker.get("id"), "source": marker.get("source")}


def running_version() -> str:
    return __version__


def staged_dir(version: str) -> str:
    return os.path.join(os.path.dirname(install_dir()), f"{APP}.update-{version}")


def staged_ready(version: str, sha256: str | None = None) -> str | None:
    """The staged build of this version when it is complete and verified (and, given a sha256, made from that
    release zip)."""
    d = staged_dir(version)
    stamp = helper.read_json(os.path.join(d, STAMP))
    if not stamp or stamp.get("version") != version:
        return None
    if sha256 and stamp.get("sha256") and stamp.get("sha256") != sha256:
        return None
    return d if helper.check_folder(d, version) is None else None


# ------------------------------------------------------------------ processes
def clean_env() -> dict:
    return helper.clean_env()


def spawn(exe: str, args: list[str] | None = None, cwd: str | None = None) -> subprocess.Popen:
    """Start a program on its own: clean environment, a neutral working folder, its own process group (out of our
    job object when allowed), no inherited handles."""
    proc = helper.start(exe, list(args or []), cwd or neutral_cwd())
    if proc is None:
        raise UpdateError(f"{os.path.basename(exe)}을(를) 시작하지 못했습니다")
    return proc


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong), ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260)]


def parent_pids() -> dict[int, int]:
    """{pid: parent pid} of every process (a Toolhelp snapshot)."""
    if os.name != "nt":
        return {}
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return {}
    out = {}
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
        while ok:
            out[int(e.th32ProcessID)] = int(e.th32ParentProcessID)
            ok = k32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(ctypes.c_void_p(snap))
    return out


def own_descendants() -> set[int]:
    """This process and everything it started (its QtWebEngineProcess renderers, ...)."""
    parents = parent_pids()
    me = os.getpid()
    mine = {me}
    for pid in parents:
        chain, p, steps = [], pid, 0
        while p and p not in mine and steps < 64:  # bounded: a reused pid cannot loop forever
            chain.append(p)
            p, steps = parents.get(p, 0), steps + 1
        if p in mine:
            mine.update(chain)
    return mine


def processes_in(folder: str) -> list[tuple[int, str]]:
    """(pid, image path) of the other processes running a program from inside folder (RetLens windows,
    retlens-cli, ...). This process and its own children (the window's QtWebEngineProcess) are not counted."""
    if os.name != "nt" or not os.path.isdir(folder):
        return []
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    arr = (ctypes.c_ulong * 16384)()
    needed = ctypes.c_ulong()
    if not k32.K32EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    out = []
    root = os.path.normcase(os.path.realpath(folder)).rstrip("\\/") + os.sep
    mine = own_descendants()
    for pid in arr[: needed.value // ctypes.sizeof(ctypes.c_ulong)]:
        if not pid or pid in mine:
            continue
        h = k32.OpenProcess(helper.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            if k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(size)):
                image = buf.value
                if os.path.normcase(os.path.realpath(image)).startswith(root):
                    out.append((int(pid), image))
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    return out


def describe_processes(procs: list[tuple[int, str]]) -> str:
    """'RetLens 창 1개, retlens-cli 1개' of processes_in()."""
    names: dict[str, int] = {}
    for _pid, image in procs:
        base = os.path.basename(image).lower()
        label = {"retlens.exe": "RetLens 창", "retlens-cli.exe": "retlens-cli", "qtwebengineprocess.exe": "RetLens 화면 프로세스"
                 }.get(base, os.path.basename(image))
        names[label] = names.get(label, 0) + 1
    return ", ".join(f"{k} {v}개" for k, v in names.items())


def elevated() -> bool:
    """Running as administrator (a per-user install made by an elevated program ends up owned by the
    administrators, so it is refused)."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def free_bytes(path: str) -> int:
    p = os.path.abspath(path)
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 1 << 62


def need_space(path: str, need: int, what: str) -> None:
    have = free_bytes(path)
    need = int(need * NEED_MARGIN)
    if have < need:
        raise UpdateError(f"{what}에 쓸 공간이 부족합니다: {need / 1e9:.1f} GB 필요, {have / 1e9:.1f} GB 남음 ({path})")


def check_can_change() -> None:
    """Install / update / uninstall only in the packaged program and not as administrator."""
    if not paths.FROZEN and not _testing():
        raise UpdateError("설치판에서만 씁니다")
    if elevated():
        raise UpdateError("관리자 권한으로 실행 중에는 설치·업데이트·제거하지 않습니다. RetLens를 보통으로 실행하세요")


@contextmanager
def update_lock(timeout_s: float = 0.0):
    """The lock every RetLens and the helper take around downloading, staging, swapping and cleaning up."""
    try:
        m = helper.Mutex(timeout_s)
    except (OSError, TimeoutError):
        raise Busy("다른 RetLens가 업데이트하고 있습니다. 끝난 뒤 다시 시도하세요") from None
    try:
        yield
    finally:
        m.release()


# ------------------------------------------------------------------ the release
@dataclass
class Release:
    version: str
    tag: str
    name: str = ""
    notes: str = ""
    page: str = RELEASES_PAGE
    asset_name: str = ""
    asset_url: str = ""
    size: int = 0
    sha256: str | None = None  # required for a download (UpdateError otherwise)
    published: str = ""
    local_zip: str | None = None  # "받은 zip으로 업데이트": the user's file

    def to_dict(self) -> dict:
        return asdict(self)


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    """Redirects only to https on GitHub's hosts (and, for tests, back to the same localhost server)."""

    def __init__(self, extra_hosts: frozenset = frozenset()):
        super().__init__()
        self.extra = extra_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not url_allowed(newurl, self.extra):
            raise urllib.error.HTTPError(newurl, 403, "redirect to a host that is not allowed", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def url_allowed(url: str, extra_hosts: frozenset = frozenset()) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.username or u.password:
        return False
    if host in extra_hosts:
        return u.scheme in ("http", "https")
    return u.scheme == "https" and host in GITHUB_HOSTS and (u.port in (None, 443))


def api_url() -> tuple[str, frozenset]:
    """(the latest-release URL, extra allowed hosts): GitHub, or a localhost test server (RETLENS_UPDATE_API)."""
    o = os.environ.get("RETLENS_UPDATE_API")
    if o and _testing():
        host = (urllib.parse.urlsplit(o).hostname or "").lower()
        if host in ("127.0.0.1", "localhost"):
            return o, frozenset({host})
    return API_LATEST, frozenset()


def opener(extra_hosts: frozenset = frozenset()) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_GitHubOnly(extra_hosts))


def _get(url: str, extra: frozenset, headers: dict | None = None, timeout: float = 10.0, limit: int = 1 << 21):
    """(status, headers, body bytes) of a GET through the GitHub-only opener; HTTP errors return their status."""
    if not url_allowed(url, extra):
        raise UpdateError(f"허용되지 않은 주소입니다: {urllib.parse.urlsplit(url).hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
                                               **(headers or {})})
    try:
        with opener(extra).open(req, timeout=timeout) as r:
            return r.status, r.headers, r.read(limit + 1)[:limit]
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        if "407" in str(reason):
            raise UpdateError("프록시가 로그인을 요구해 GitHub에 연결하지 못했습니다. 릴리즈 페이지에서 zip을 받아 "
                              "'받은 zip으로 업데이트'를 쓰세요") from None
        raise UpdateError(f"GitHub에 연결하지 못했습니다 ({type(reason).__name__}). 인터넷 연결을 확인하거나, 릴리즈 "
                          "페이지에서 zip을 받아 '받은 zip으로 업데이트'를 쓰세요") from None


def _rate_limited(status: int, headers) -> UpdateError | None:
    if status in (403, 429) and headers is not None and headers.get("X-RateLimit-Remaining") == "0":
        try:
            reset = time.strftime("%H:%M", time.localtime(int(headers.get("X-RateLimit-Reset", "0"))))
        except ValueError:
            reset = "잠시 뒤"
        return UpdateError(f"GitHub 요청 한도에 걸렸습니다(같은 네트워크에서 많이 확인함). {reset} 이후에 다시 확인하세요")
    return None


def parse_sha256_file(text: str, asset_name: str) -> str | None:
    """The hash of a '<64 hex>  <file name>' line naming this asset (package_release.ps1's format)."""
    for line in text.splitlines():
        m = SHA_LINE_RE.match(line.strip())
        if m and m.group(2) == asset_name:
            return m.group(1).lower()
    return None


def release_from_json(data: dict, sha_text: str | None = None, extra: frozenset = frozenset()) -> Release | None:
    """The release's version and Windows zip (None: not a usable release: draft, prerelease, other tag or no zip).
    sha256 from the asset's digest and/or the .sha256 asset's text (sha_text); both must agree."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    v = parse_version(tag) and tag[1:]
    if not v or not TAG_RE.match(tag):
        return None
    name = f"RetLens-{v}-win64.zip"
    assets = {a.get("name"): a for a in data.get("assets") or [] if isinstance(a, dict)}
    a = assets.get(name)
    if a is None:
        return None
    url = str(a.get("browser_download_url") or "")
    want = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
    if url != want and not (extra and url_allowed(url, extra)):
        return None
    digest = None
    m = re.fullmatch(r"sha256:([0-9a-f]{64})", str(a.get("digest") or ""))
    if m:
        digest = m.group(1)
    side = parse_sha256_file(sha_text, name) if sha_text else None
    if digest and side and digest != side:
        raise UpdateError("릴리즈의 체크섬 두 개(digest와 .sha256 파일)가 서로 달라 업데이트하지 않습니다")
    return Release(version=v, tag=tag, name=str(data.get("name") or tag), notes=str(data.get("body") or ""),
                   page=str(data.get("html_url") or RELEASES_PAGE) if url_allowed(str(data.get("html_url") or ""), extra)
                   else RELEASES_PAGE, asset_name=name, asset_url=url, size=int(a.get("size") or 0),
                   sha256=digest or side, published=str(data.get("published_at") or ""))


@dataclass
class Check:
    """What the latest-release check found."""
    current: str
    latest: Release | None = None
    newer: bool = False
    installed_version: str | None = None
    etag: str | None = None
    not_modified: bool = False
    error: str | None = None
    cached: dict | None = field(default=None, repr=False)  # GitHub's answer, reused on 304

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("cached", None)
        d["latest"] = self.latest.to_dict() if self.latest else None
        return d


def check_latest(etag: str | None = None, cached: dict | None = None, timeout: float = 10.0) -> Check:
    """The latest release on GitHub and whether it is newer than this program (and the installed one, from a
    portable copy). etag + cached: the previous answer, reused on 304 (which does not count against the limit)."""
    current = running_version()
    inst = installed_info() if is_portable() else None
    base = max([v for v in (current, (inst or {}).get("version")) if parse_version(v)], key=parse_version)
    res = Check(current=current, installed_version=(inst or {}).get("version"))
    url, extra = api_url()
    try:
        status, headers, body = _get(url, extra, {"If-None-Match": etag} if etag and cached else None, timeout)
        if status == 304 and cached:
            data = cached
            res.not_modified, res.etag = True, etag
        elif status == 200:
            data = json.loads(body.decode("utf-8"))
            res.etag = headers.get("ETag") if headers is not None else None
        else:
            err = _rate_limited(status, headers)
            if err:
                raise err
            if status == 404:
                raise UpdateError("공개된 릴리즈가 없습니다")
            raise UpdateError(f"GitHub가 HTTP {status}로 답했습니다")
        sha_text = None
        assets = {a.get("name"): a for a in data.get("assets") or [] if isinstance(a, dict)}
        tag = str(data.get("tag_name") or "")
        side = assets.get(f"RetLens-{tag[1:]}-win64.zip.sha256") if tag.startswith("v") else None
        if side and url_allowed(str(side.get("browser_download_url") or ""), extra):
            st, _h, txt = _get(side["browser_download_url"], extra, {"Accept": "application/octet-stream"}, timeout,
                               limit=1024)
            if st == 200:
                sha_text = txt.decode("ascii", "replace")
        res.latest = release_from_json(data, sha_text, extra)
        res.cached = data
        if res.latest is not None:
            res.newer = is_newer(res.latest.version, base)
    except UpdateError as e:
        res.error = str(e)
    except (ValueError, KeyError, TypeError) as e:
        res.error = f"GitHub의 답을 읽지 못했습니다 ({type(e).__name__})"
    return res


def release_from_zip(path: str, check: Check | None = None) -> Release:
    """A RetLens-<ver>-win64.zip the user downloaded (proxy, offline): its version from the name, its hash from the
    latest release when that is the same version, else from a .sha256 next to it (None: unchecked)."""
    name = os.path.basename(path)
    m = ASSET_RE.match(name)
    if not m:
        raise UpdateError(f"RetLens 릴리즈 zip 이름이 아닙니다 (RetLens-<버전>-win64.zip): {name}")
    v = m.group(1)
    sha = None
    if check is not None and check.latest is not None and check.latest.version == v:
        sha = check.latest.sha256
    side = path + ".sha256"
    if sha is None and os.path.isfile(side):
        try:
            with open(side, encoding="ascii", errors="replace") as f:
                sha = parse_sha256_file(f.read(2048), name)
        except OSError:
            pass
    return Release(version=v, tag=f"v{v}", name=name, asset_name=name, size=os.path.getsize(path), sha256=sha,
                   local_zip=os.path.abspath(path))


# ------------------------------------------------------------------ download and stage
def _long(p: str) -> str:
    """A path Windows accepts beyond 260 characters."""
    if os.name != "nt":
        return p
    p = os.path.abspath(p)
    return p if p.startswith("\\\\?\\") else ("\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p)


def download(rel: Release, progress: Progress | None = None, cancel: threading.Event | None = None) -> str:
    """The release's zip in downloads\\ (resumable), its SHA-256 checked. A local zip is checked in place."""
    from . import prereqs

    progress = progress or (lambda *_: None)
    if rel.local_zip:
        if rel.sha256:
            progress("확인 중", 0, 0)
            if not prereqs._check(rel.local_zip, rel.sha256, None, None, cancel):
                raise UpdateError(f"{os.path.basename(rel.local_zip)}의 체크섬이 릴리즈 값과 다릅니다")
        return rel.local_zip
    if not rel.sha256 or not re.fullmatch(r"[0-9a-f]{64}", rel.sha256):
        raise UpdateError("이 릴리즈에는 체크섬이 없어 업데이트하지 않습니다")
    _url, extra = api_url()
    if not url_allowed(rel.asset_url, extra):
        raise UpdateError("릴리즈 파일 주소가 GitHub가 아닙니다")
    os.makedirs(downloads_dir(), exist_ok=True)
    need_space(downloads_dir(), rel.size, "받을 폴더")
    dest = os.path.join(downloads_dir(), rel.asset_name)
    try:
        return prereqs.download(rel.asset_url, dest, sha256=rel.sha256, progress=progress, cancel=cancel,
                                stage=f"RetLens {rel.version} 받는 중", opener=opener(extra))
    except prereqs.Cancelled:
        raise
    except prereqs.SetupError as e:
        raise UpdateError(str(e)) from None


def _zip_members(z: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """(entry, path inside RetLens/) of a release zip: one top folder RetLens/, safe names only."""
    from . import prereqs

    out = []
    for m in prereqs._safe_members(z):
        name = m.filename.replace("\\", "/")
        if not name.startswith("RetLens/"):
            raise UpdateError(f"RetLens 릴리즈 zip이 아닙니다 (RetLens/ 밖의 항목: {m.filename})")
        rel = name[len("RetLens/"):]
        if not rel:
            continue
        if WINDOWS_BAD_NAME.search(rel.rstrip("/")):
            raise UpdateError(f"zip에 Windows에서 쓸 수 없는 이름이 있습니다: {m.filename}")
        if (m.external_attr >> 16) & 0o170000 == 0o120000:  # a symbolic link entry
            raise UpdateError(f"zip에 링크 항목이 있습니다: {m.filename}")
        out.append((m, rel))
    return out


def extract(zip_path: str, dest: str, progress: Progress | None = None, cancel: threading.Event | None = None) -> int:
    """The zip's RetLens/ contents straight into dest (file times as in the zip); bytes written."""
    from . import prereqs

    progress = progress or (lambda *_: None)
    with zipfile.ZipFile(zip_path) as z:
        members = _zip_members(z)
        total = sum(m.file_size for m, _r in members)
        need_space(dest, total, "설치 폴더")
        done = 0
        for m, rel in members:
            if cancel is not None and cancel.is_set():
                raise prereqs.Cancelled()
            target = os.path.join(dest, *rel.rstrip("/").split("/"))
            if m.is_dir():
                os.makedirs(_long(target), exist_ok=True)
                continue
            os.makedirs(_long(os.path.dirname(target)), exist_ok=True)
            with z.open(m) as src, open(_long(target), "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            try:
                t = time.mktime(m.date_time + (0, 0, -1))
                os.utime(_long(target), (t, t))
            except (OverflowError, ValueError, OSError):
                pass
            done += m.file_size
            progress("푸는 중", done, total)
    return total


def verify_build(folder: str, version: str, run_check: bool = True) -> None:
    """The folder holds the whole build of this version (manifest, every file by size) and its retlens-cli.exe runs
    and says so (proves an antivirus did not quarantine it)."""
    why = helper.check_folder(folder, version)
    if why:
        raise UpdateError(f"받은 RetLens {version}이(가) 온전하지 않습니다: {why}")
    for f in SHIPPED[:2]:
        if not os.path.isfile(os.path.join(folder, f)):
            raise UpdateError(f"받은 RetLens {version}에 {f}이(가) 없습니다")
    if run_check and os.name == "nt":
        cli = os.path.join(folder, "retlens-cli.exe")
        try:
            out = subprocess.run([cli, "version"], cwd=tempfile.gettempdir(), env=clean_env(), capture_output=True,
                                 timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            said = json.loads(out.stdout.decode("utf-8", "replace").strip().splitlines()[-1]).get("version")
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as e:
            raise UpdateError(f"받은 RetLens {version}의 retlens-cli.exe가 실행되지 않습니다 ({type(e).__name__}). "
                              "백신 프로그램이 막았는지 확인하세요") from None
        if said != version:
            raise UpdateError(f"받은 RetLens의 버전이 {said}입니다({version}이어야 함)")


def stage(rel: Release, zip_path: str, progress: Progress | None = None, cancel: threading.Event | None = None,
          run_check: bool = True) -> str:
    """Unpack and verify the release next to the install folder (RetLens.update-<ver>); its path. A verified one
    already there is reused."""
    ready = staged_ready(rel.version, rel.sha256)
    if ready:
        return ready
    final = staged_dir(rel.version)
    part = final + ".partial"
    os.makedirs(os.path.dirname(final), exist_ok=True)
    for p in (part, final):
        if os.path.exists(p):
            _remove_tree(p)
    try:
        extract(zip_path, part, progress, cancel)
        (progress or (lambda *_: None))("확인 중", 0, 0)
        verify_build(part, rel.version, run_check)
        helper.write_json(os.path.join(part, STAMP), {"version": rel.version, "sha256": rel.sha256,
                                                      "time": time.time()})
        # an antivirus scanning the retlens-cli.exe just run may hold it a moment
        if not helper.retry(lambda: os.rename(part, final), "rename staging", 30.0):
            raise UpdateError(f"받은 새 버전 폴더를 쓰는 프로그램이 있어 마치지 못했습니다: {part}")
    except BaseException:
        _remove_tree(part)
        raise
    return final


def _remove_tree(path: str) -> bool:
    """Delete one of our own folders (never through a junction); True when it is gone."""
    if not os.path.lexists(path):
        return True
    if helper.is_reparse_point(path):
        try:
            os.rmdir(path)  # the link only
        except OSError:
            return False
        return True
    shutil.rmtree(_long(path), ignore_errors=True)
    return not os.path.exists(path)


# ------------------------------------------------------------------ install (from a portable copy, or staged)
def _copy_build(src: str, dest: str, progress: Progress | None, cancel: threading.Event | None) -> None:
    """Copy the files the source's manifest lists (only those: never the user's own files in that folder)."""
    from . import prereqs

    files = helper.manifest_files(src)
    if not files:
        raise UpdateError("이 RetLens 폴더에 빌드 목록(retlens-build.json)이 없어 설치할 수 없습니다")
    total = sum(files.values())
    need_space(dest, total, "설치 폴더")
    done = 0
    for rel, size in files.items():
        if cancel is not None and cancel.is_set():
            raise prereqs.Cancelled()
        s, d = os.path.join(src, rel), os.path.join(dest, rel)
        os.makedirs(_long(os.path.dirname(d)), exist_ok=True)
        shutil.copy2(_long(s), _long(d))
        done += size
        progress and progress("복사하는 중", done, total)
    shutil.copy2(_long(os.path.join(src, MANIFEST)), _long(os.path.join(dest, MANIFEST)))


def place(new: str, version: str, source: str | None = None) -> dict:
    """Put a complete build folder (same volume) in the install folder's place, from a program that does not run
    from there: an existing install must not be in use; the user's entries in it move over; the old copy goes."""
    target = install_dir()
    if same_path(new, target):
        raise UpdateError("설치할 폴더와 설치 위치가 같습니다")
    old_marker = read_marker(target) if os.path.isdir(target) else None
    if os.path.isdir(target) and os.listdir(target) and not os.path.isfile(os.path.join(target, "RetLens.exe")):
        raise UpdateError(f"설치 위치({target})에 RetLens가 아닌 파일이 있어 설치하지 않았습니다")
    if os.path.isdir(target):
        procs = processes_in(target)
        if procs:
            raise Busy(f"설치된 RetLens가 실행 중입니다({describe_processes(procs)}). 닫은 뒤 다시 시도하세요")
    marker = {"product": APP, "id": (old_marker or {}).get("id") or uuid.uuid4().hex, "version": version,
              "installed": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source}
    helper.write_json(os.path.join(new, MARKER), marker)
    try:
        os.remove(os.path.join(new, STAMP))
    except OSError:
        pass
    old = None
    if os.path.isdir(target):
        old = os.path.join(os.path.dirname(target), helper.stamp_name(f"{APP}.old-"))
        if not helper.retry(lambda: os.rename(target, old), "rename install -> old", 15.0):
            raise Busy("설치된 RetLens 폴더를 쓰는 프로그램이 있습니다(탐색기 창 등). 닫은 뒤 다시 시도하세요")
    if not helper.retry(lambda: os.rename(new, target), "rename new -> install", 15.0):
        if old:
            helper.retry(lambda: os.rename(old, target), "put the old install back", 120.0)
        raise UpdateError("새 폴더를 설치 위치에 넣지 못했습니다")
    kept = helper.move_extras(old, target) if old else []
    if old and not kept:
        threading.Thread(target=remove_old_copy, args=(old,), daemon=True).start()
    return {"dir": target, "version": version, "id": marker["id"], "old": old, "kept_in_old": kept}


def install_from_folder(src: str, progress: Progress | None = None, cancel: threading.Event | None = None,
                        desktop: bool = False) -> dict:
    """Install the build in src (this portable copy's folder) and register it."""
    check_can_change()
    version = folder_version(src)
    if not version:
        raise UpdateError("이 RetLens 폴더의 버전을 알 수 없어 설치할 수 없습니다")
    target = install_dir()
    if same_path(src, target) or helper.inside(src, target) or helper.inside(target, src):
        raise UpdateError("이 RetLens는 이미 설치 위치에서 실행 중입니다")
    with update_lock():
        tmp = os.path.join(os.path.dirname(target), f"{APP}.install-{os.getpid()}")
        if os.path.exists(tmp):
            _remove_tree(tmp)
        os.makedirs(tmp)
        try:
            _copy_build(src, tmp, progress, cancel)
            why = helper.check_folder(tmp, version)
            if why:
                raise UpdateError(f"복사한 파일을 확인하지 못했습니다: {why}")
            info = place(tmp, version, source=os.path.realpath(src))
        except BaseException:
            _remove_tree(tmp)
            raise
    info["registration"] = register(info["dir"], version, info["id"], desktop=desktop)
    return info


def install_staged(staged: str, version: str, desktop: bool | None = None) -> dict:
    """From a portable copy: the downloaded new version becomes the install (no helper: the install folder is not
    ours)."""
    check_can_change()
    with update_lock():
        info = place(staged, version, source=None)
    info["registration"] = register(info["dir"], version, info["id"], desktop=desktop)
    return info


def remove_old_copy(path: str) -> bool:
    """Delete an old RetLens folder: only what a build ships; a folder that still holds anything else is kept."""
    name = os.path.basename(path)
    if not name.startswith(f"{APP}.") or helper.is_reparse_point(path) or not os.path.isdir(path):
        return False
    return helper.remove_build(path)


# ------------------------------------------------------------------ shortcuts and "installed apps"
def _vcall(obj, index: int, argtypes: tuple, *args):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])
    return fn(obj, *args)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("val", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
IID_IPersistFile = "{0000010b-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}"
PKEY_AppUserModel_ID = ("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", 5)


def _shell_link():
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 2)  # apartment; already initialised (Qt) is fine
    link = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(_GUID.of(CLSID_ShellLink)), None, 1, ctypes.byref(_GUID.of(IID_IShellLinkW)),
                                ctypes.byref(link))
    if hr != 0 or not link:
        raise OSError(f"CoCreateInstance(ShellLink) failed: {hr & 0xFFFFFFFF:#x}")
    return link


def _query(obj, iid: str):
    out = ctypes.c_void_p()
    _vcall(obj, 0, (ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_GUID.of(iid)),
           ctypes.byref(out))
    return out


def _release(obj) -> None:
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(obj)


def create_shortcut(lnk: str, target: str, workdir: str = "", description: str = "", aumid: str | None = AUMID) -> None:
    """A .lnk to target (its icon), with this working folder and AppUserModelID."""
    if os.name != "nt":
        raise OSError("Windows only")
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    link = _shell_link()
    store = persist = None
    try:
        w = ctypes.c_wchar_p
        _vcall(link, 20, (w,), target)  # SetPath
        _vcall(link, 9, (w,), workdir)  # SetWorkingDirectory
        _vcall(link, 7, (w,), description)  # SetDescription
        _vcall(link, 17, (w, ctypes.c_int), target, 0)  # SetIconLocation
        if aumid:
            store = _query(link, IID_IPropertyStore)
            key = _PROPERTYKEY(_GUID.of(PKEY_AppUserModel_ID[0]), PKEY_AppUserModel_ID[1])
            var = _PROPVARIANT(31, 0, 0, 0, aumid, None)  # VT_LPWSTR
            _vcall(store, 6, (ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)), ctypes.byref(key),
                   ctypes.byref(var))  # SetValue
            _vcall(store, 7, ())  # Commit
        persist = _query(link, IID_IPersistFile)
        _vcall(persist, 6, (w, ctypes.c_int), lnk, 1)  # Save
    finally:
        for o in (store, persist, link):
            _release(o)


def read_shortcut(lnk: str) -> str | None:
    """The target of a .lnk (None when it cannot be read)."""
    if os.name != "nt" or not os.path.isfile(lnk):
        return None
    link = persist = None
    try:
        link = _shell_link()
        persist = _query(link, IID_IPersistFile)
        _vcall(persist, 5, (ctypes.c_wchar_p, ctypes.c_ulong), lnk, 0)  # Load
        buf = ctypes.create_unicode_buffer(32768)
        _vcall(link, 3, (ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong), buf, len(buf), None,
               0x4)  # GetPath, SLGP_RAWPATH
        return buf.value or None
    except OSError:
        return None
    finally:
        for o in (persist, link):
            _release(o)


def _registry_enabled() -> bool:
    return os.name == "nt" and not (os.environ.get("RETLENS_NO_REGISTRY") and _testing())


def write_uninstall_entry(install: str, version: str, install_id: str) -> None:
    import winreg

    exe = os.path.join(install, "RetLens.exe")
    size_kb = sum((read_manifest(install) or {}).get("files", {}).values()) // 1024
    values = {"DisplayName": APP, "DisplayVersion": version, "Publisher": APP, "InstallLocation": install,
              "DisplayIcon": f"{exe},0", "UninstallString": f'"{exe}" --uninstall',
              "URLInfoAbout": f"https://github.com/{REPO}", "InstallDate": time.strftime("%Y%m%d"),
              "RetLensInstallId": install_id}
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name, v in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, v)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(min(size_kb, 0xFFFFFFFF)))


def read_uninstall_entry() -> dict | None:
    if not _registry_enabled():
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            out = {}
            for name in ("DisplayVersion", "InstallLocation", "RetLensInstallId", "UninstallString"):
                try:
                    out[name] = winreg.QueryValueEx(k, name)[0]
                except FileNotFoundError:
                    pass
            return out
    except OSError:
        return None


def register(install: str, version: str, install_id: str, desktop: bool | None = None) -> dict:
    """Start-menu shortcut, desktop shortcut (desktop=True: make it; None: keep one that is there) and the "installed
    apps" entry. A failed piece is reported, not fatal."""
    exe = os.path.join(install, "RetLens.exe")
    out: dict = {"errors": []}
    work = os.path.join(known_folder("Documents") or os.path.expanduser("~"), APP)
    try:
        os.makedirs(work, exist_ok=True)
    except OSError:
        work = ""  # a working folder is a nicety: the shortcut works without it
    lnks = shortcut_paths()
    for key in ("start_menu", "desktop"):
        lnk = lnks[key]
        if key == "desktop" and not (desktop or (desktop is None and points_to_retlens(lnk))):
            continue
        try:
            create_shortcut(lnk, exe, work, "RetLens: 모션캡처 리타게팅과 검증")
            out[key] = lnk
        except OSError as e:
            out["errors"].append(f"{key}: {e}")
    if _registry_enabled():
        try:
            write_uninstall_entry(install, version, install_id)
            out["registry"] = True
        except OSError as e:
            out["errors"].append(f"registry: {e}")
    return out


def points_to_retlens(lnk: str, folder: str | None = None) -> bool:
    """The shortcut opens a RetLens build (inside folder when given): ours to re-point or delete. A RetLens.lnk the
    user made for something else is left alone."""
    target = read_shortcut(lnk)
    if not target or os.path.basename(target).lower() != "retlens.exe":
        return False
    d = os.path.dirname(target)
    if folder is not None:
        return same_path(d, folder)
    return os.path.isfile(os.path.join(d, MANIFEST)) or same_path(d, install_dir())


def registration_ok() -> bool:
    """The Start-menu shortcut points here and the "installed apps" entry has this version."""
    exe = os.path.join(install_dir(), "RetLens.exe")
    if not same_path(read_shortcut(shortcut_paths()["start_menu"]), exe):
        return False
    if _registry_enabled():
        e = read_uninstall_entry() or {}
        return e.get("DisplayVersion") == running_version() and same_path(e.get("InstallLocation"), install_dir())
    return True


def ensure_registration() -> dict | None:
    """Run from the installed program at start-up: re-register when the shortcut or entry is missing or old."""
    if not is_installed() or registration_ok():
        return None
    marker = read_marker(install_dir()) or {}
    install_id = marker.get("id") or uuid.uuid4().hex
    if not marker:
        helper.write_json(os.path.join(install_dir(), MARKER), {"product": APP, "id": install_id,
                                                               "version": running_version(), "source": None})
    return register(install_dir(), running_version(), install_id, desktop=None)


# ------------------------------------------------------------------ the helper
def helper_command(job_path: str) -> tuple[list[str], dict | None]:
    """How to start retlens-update for a job: a copy of the packaged helper in updater\\, or this Python running
    retlens/update_helper.py from the source tree (tests)."""
    if paths.FROZEN:
        src = os.path.join(program_dir() or "", "retlens-update.exe")
        if not os.path.isfile(src):
            raise UpdateError("업데이트 도구(retlens-update.exe)가 없습니다. 릴리즈 페이지에서 새로 받아 설치하세요")
        dst = os.path.join(updater_dir(), f"retlens-update-{os.getpid()}-{uuid.uuid4().hex[:6]}.exe")
        os.makedirs(updater_dir(), exist_ok=True)
        shutil.copy2(src, dst)
        return [dst, job_path], None
    env = dict(clean_env(), PYTHONPATH=paths.REPO_ROOT)
    return [sys.executable, "-m", "retlens.update_helper", job_path], env


class Armed:
    """A helper waiting for this program to exit (job file it re-reads then)."""

    def __init__(self, job_path: str, job: dict, proc: subprocess.Popen):
        self.job_path, self.job, self.proc = job_path, job, proc

    def set(self, **changes) -> None:
        self.job.update(changes)
        helper.write_json(self.job_path, self.job)

    def cancel(self) -> None:
        self.set(cancelled=True)

    @property
    def relaunch(self) -> bool:
        return bool(self.job.get("relaunch"))


def arm(job: dict, ready_timeout_s: float = 15.0) -> Armed:
    """Write the job and start the helper; return once it says it is waiting (else UpdateError, nothing done)."""
    os.makedirs(updater_dir(), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_path = os.path.join(updater_dir(), f"job-{stamp}-{os.getpid()}.json")
    ready = job_path + ".ready"
    job = {"parent_pid": os.getpid(), "ready": ready, "result": result_path(), "journal": journal_path(),
           "started_marker": started_path(), "log": os.path.join(updater_dir(), f"update-{stamp}.log"),
           "workdir": neutral_cwd(), "wait_s": None, **job}
    helper.write_json(job_path, job)
    try:
        cmd, env = helper_command(job_path)
    except OSError as e:
        raise UpdateError(f"업데이트 도구를 준비하지 못했습니다: {e}") from None
    if paths.FROZEN:
        job["recover_command"] = f'"{cmd[0]}" "{job_path}" --recover'
        helper.write_json(job_path, job)
    try:
        if env is None:
            proc = spawn(cmd[0], cmd[1:], cwd=updater_dir())
        else:
            proc = subprocess.Popen(cmd, cwd=updater_dir(), env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except OSError as e:
        raise UpdateError(f"업데이트 도구를 시작하지 못했습니다: {e}") from None
    end = time.time() + ready_timeout_s
    while time.time() < end:
        if os.path.isfile(ready):
            return Armed(job_path, job, proc)
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    try:
        helper.write_json(job_path, {**job, "cancelled": True})
        proc.kill()
    except OSError:
        pass
    raise UpdateError("업데이트 도구가 응답하지 않습니다(백신 프로그램이 막았을 수 있습니다). 릴리즈 페이지에서 받아 설치하세요")


def arm_swap(staged: str, version: str, relaunch: bool, relaunch_args: list[str] | None = None) -> Armed:
    """The installed program: replace it with the staged build once it has exited."""
    check_can_change()
    if not is_installed() and paths.FROZEN:
        raise UpdateError("설치된 RetLens에서만 이렇게 업데이트합니다")
    marker = read_marker(install_dir()) or {}
    helper.write_json(os.path.join(staged, MARKER), {"product": APP, "id": marker.get("id") or uuid.uuid4().hex,
                                                     "version": version, "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                     "source": marker.get("source")})
    for p in (started_path(), result_path()):
        try:
            os.remove(p)
        except OSError:
            pass
    return arm({"action": "swap", "install": install_dir(), "staged": staged, "from": running_version(),
                "to": version, "relaunch": relaunch, "relaunch_args": list(relaunch_args or []),
                "health_timeout_s": 120})


def uninstall_purge_list() -> list[str]:
    """What '설정·캐시·로그도 지우기' deletes: an explicit list in the default user folder (empty when the user folder
    was moved by RETLENS_USER_DIR). Never Documents\\RetLens, uploads\\, models\\, tools\\ or gmt\\."""
    default = os.path.join(known_folder("LocalAppData") or os.environ.get("LOCALAPPDATA", ""), APP)
    if os.environ.get("RETLENS_USER_DIR") or not same_path(paths.user_dir(), default):
        return []
    u = paths.user_dir()
    names = ("settings.json", "api.json", "update_result.json", "update_started.json", "update_pending.json",
             "cache", "logs", "downloads", "sessions")  # (updater\ holds the running helper: it stays)
    return [os.path.join(u, n) for n in names if os.path.lexists(os.path.join(u, n))]


def arm_uninstall(purge: bool) -> Armed:
    check_can_change()
    marker = read_marker(install_dir())
    if not marker or not is_installed():
        raise UpdateError("설치된 RetLens에서만 제거합니다")
    procs = processes_in(install_dir())
    if procs:
        raise Busy(f"다른 RetLens가 실행 중입니다({describe_processes(procs)}). 닫은 뒤 다시 시도하세요")
    return arm({"action": "uninstall", "install": install_dir(), "install_id": marker.get("id"),
                "shortcuts": [p for p in shortcut_paths().values() if points_to_retlens(p, install_dir())],
                "purge": uninstall_purge_list() if purge else [],
                "purge_settings": bool(purge), "user_dir": paths.user_dir()})


# ------------------------------------------------------------------ start-up
def recover() -> dict | None:
    """A swap cut off earlier (the journal is there and no helper holds the lock): finish or undo it now."""
    j = helper.read_json(journal_path())
    if not j:
        return None
    try:
        with update_lock():
            job = helper.Job.__new__(helper.Job)
            dict.__init__(job, {"journal": journal_path()})
            job.path = journal_path()
            return helper.run_recover(job)
    except Busy:
        return None


def take_result() -> dict | None:
    """The helper's result for this program to show once (and forget). A result about another install folder is
    left alone."""
    r = helper.read_json(result_path())
    if not r:
        return None
    if r.get("install") and paths.FROZEN and not same_path(r.get("install"), install_dir()):
        return None
    try:
        os.remove(result_path())
    except OSError:
        pass
    return r


def mark_started() -> None:
    """This version's window is up (the helper's health check, and the signal that the old copy may go)."""
    helper.write_json(started_path(), {"version": running_version(), "pid": os.getpid(), "time": time.time(),
                                       "install": program_dir()})


def cleanup(log: Callable[[str], None] = lambda *_: None, lock_timeout_s: float = 0.0) -> list[str]:
    """Leftovers next to the install folder (old copies once this version runs installed, unverified or older
    staging, failed copies), old downloads and helper copies; the folders kept (with the user's files in them)."""
    kept: list[str] = []
    if not paths.FROZEN:
        return kept
    parent = os.path.dirname(install_dir())
    try:
        with update_lock(lock_timeout_s):  # a helper still checking this version's start holds it
            names = os.listdir(parent) if os.path.isdir(parent) else []
            for name in names:
                p = os.path.join(parent, name)
                if not name.startswith(f"{APP}.") or helper.is_reparse_point(p) or not os.path.isdir(p):
                    continue
                if name.startswith((f"{APP}.old-", f"{APP}.failed-", f"{APP}.uninstall-")):
                    if not is_installed():
                        continue  # only the installed program judges its own old copies
                    if not remove_old_copy(p):
                        kept.append(p)
                elif name.startswith(f"{APP}.update-"):
                    v = name[len(f"{APP}.update-"):]
                    if name.endswith(".partial") or not is_newer(v, running_version()) or staged_ready(v) is None:
                        _remove_tree(p)
                elif name.startswith(f"{APP}.install-"):
                    pid = name.rsplit("-", 1)[-1]
                    if not pid.isdigit() or int(pid) != os.getpid():
                        _remove_tree(p)
            d = downloads_dir()
            for name in os.listdir(d) if os.path.isdir(d) else []:
                m = re.match(r"^RetLens-(\d+\.\d+\.\d+)-win64\.zip(\.part)?$", name)
                if m and not is_newer(m.group(1), running_version()):
                    try:
                        os.remove(os.path.join(d, name))
                    except OSError:
                        pass
            u = updater_dir()
            for name in os.listdir(u) if os.path.isdir(u) else []:
                p = os.path.join(u, name)
                try:
                    if time.time() - os.path.getmtime(p) > 7 * 86400 or (
                            name.startswith("retlens-update-") and name.endswith(".exe")
                            and not name.startswith(f"retlens-update-{os.getpid()}-")):
                        os.remove(p)  # a helper copy still running is in use and stays
                except OSError:
                    pass
    except Busy:
        log("업데이트 정리: 다른 RetLens가 업데이트 중이라 다음에 합니다")
    return kept


def portable_source_to_offer() -> str | None:
    """The portable folder this install was made from, when it is safe to offer deleting it: it still holds a RetLens
    build and nothing else, and is not in the temp folder (a zip viewer's)."""
    if not is_installed():
        return None
    src = (read_marker(install_dir()) or {}).get("source")
    if not src or not os.path.isdir(src) or same_path(src, install_dir()) or helper.inside(src, tempfile.gettempdir()):
        return None
    try:
        names = set(os.listdir(src))
    except OSError:
        return None
    if not {"RetLens.exe", "_internal"} <= names or names - set(helper.SHIPPED):
        return None
    if processes_in(src):  # that copy is still open
        return None
    return src


def forget_portable_source() -> None:
    m = read_marker(install_dir())
    if m and m.get("source"):
        m["source"] = None
        helper.write_json(os.path.join(install_dir(), MARKER), m)


def delete_portable_source(src: str) -> bool:
    """Delete the portable folder offered by portable_source_to_offer (its build entries, then the folder)."""
    if src != portable_source_to_offer():
        return False
    for entry in helper.SHIPPED:
        p = os.path.join(src, entry)
        if os.path.isdir(p) and not helper.is_reparse_point(p):
            shutil.rmtree(_long(p), ignore_errors=True)
        elif os.path.lexists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    try:
        os.rmdir(src)
    except OSError:
        pass
    forget_portable_source()
    return not os.path.exists(src)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def rollback_candidate() -> tuple[str, str] | None:
    """(old copy, its version) when this installed version came in by an update and has not started yet (its start
    failed): the newest complete RetLens.old-* next to the install folder."""
    if not is_installed():
        return None
    if (helper.read_json(started_path()) or {}).get("version") == running_version():
        return None
    parent = os.path.dirname(install_dir())
    try:
        olds = [os.path.join(parent, n) for n in os.listdir(parent) if n.startswith(f"{APP}.old-")]
    except OSError:
        return None
    for p in sorted(olds, key=lambda q: os.path.getmtime(q), reverse=True):
        v = folder_version(p)
        if v and v != running_version() and not helper.is_reparse_point(p) and helper.check_folder(p, v) is None:
            return p, v
    return None


def arm_rollback(old: str, version: str) -> Armed:
    """Swap the old copy back in (as an update to it) once this program has exited, and start it."""
    check_can_change()
    marker = read_marker(install_dir()) or {}
    helper.write_json(os.path.join(old, STAMP), {"version": version, "rollback": True, "time": time.time()})
    helper.write_json(os.path.join(old, MARKER), {**marker, "product": APP, "version": version})
    return arm({"action": "swap", "install": install_dir(), "staged": old, "from": running_version(), "to": version,
                "relaunch": True, "relaunch_args": [], "health_timeout_s": 60})


def offer_rollback() -> bool:
    """A RetLens that came in by an update failed to start: offer the previous version (True when armed). A plain
    Windows message box: Qt may be what failed. Nothing is offered while the helper that started this version still
    holds the update lock: it puts the previous version back by itself when this process exits."""
    try:
        cand = rollback_candidate()
    except Exception:
        return False
    if not cand:
        return False
    try:
        with update_lock():
            pass
    except Busy:
        return False
    old, version = cand
    if helper.message(f"방금 업데이트한 RetLens {running_version()}이(가) 시작하지 못했습니다.\n\n이전 버전 {version}"
                      "(으)로 되돌릴까요?", helper.MB_YESNO | helper.MB_ICONERROR) != helper.IDYES:
        return False
    try:
        arm_rollback(old, version)
    except Exception as e:
        helper.message(f"되돌리지 못했습니다: {e}", helper.MB_OK | helper.MB_ICONERROR)
        return False
    global HARD_EXIT
    HARD_EXIT = True
    return True
