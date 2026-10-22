"""RetLens 설치 도우미: the optional programs and files RetLens can use, whether this PC already has a
compatible copy, whether it can take one, and installing it only when it is missing.

    component  needed for                 licence                        what the assistant does
    blender    FBX files                  GPL (free to share)            download Blender 4.5 LTS (zip) from blender.org
    gmt        balance control "GMT"      Apache-2.0, model: research    after the user agrees: GMT's files from its
                                                                         GitHub repository (pinned commit, SHA-1 checked)
    isaac      physics mode (Isaac), video  NVIDIA Omniverse EULA        after the user accepts the EULA: Isaac Sim 6.1
                                                                         from NVIDIA (zip, ~10 GB, MD5 checked)
    smpl       AMASS SMPL-X files         non-commercial, registration   never downloaded: opens the site, imports the zip
                                                                         the user downloaded there

probe(key) looks first for a compatible copy (the settings, the environment variables, the usual
install places: settings.find_*). Only when none is found does it check what an install needs here
(Windows x64, GPU and driver, free disk, the publisher reachable, write access) and say whether it
can run (Status.action):

    none       a compatible copy is there: nothing to do
    configure  a compatible copy is there but the settings point elsewhere: set the path, no download
    install    missing (or an incompatible version) and installable here
    manual     must be fetched by the user (SMPL-X), then imported
    blocked    missing, and this PC cannot take it now (Status.note says why)

install(key, ...) runs only for "install" / "configure" and refuses otherwise. Nothing is ever
redistributed: files come from their publishers. Licences that need consent are passed in as
accept=True by the user's own click; Isaac's EULA is never accepted on the user's behalf.
Downloads are resumable (<file>.part), checked against the publisher's checksum before use, and
unpacked into a temporary folder that is renamed into place only when complete (an earlier copy of
the assistant's own folder is set aside whole first, and put back if that fails). install() takes
the action the user clicked (expect=) and refuses if the PC changed since the check.

Standard library only (also runs in the packaged program).
"""

from __future__ import annotations

import glob
import hashlib
import http.client
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Callable

from . import paths, settings

KEYS = ("blender", "gmt", "isaac", "smpl")
SETTING = {"blender": "blender", "gmt": "gmt_dir", "isaac": "isaac_python", "smpl": "smpl_model_dir"}  # 환경 설정 field
USER_AGENT = "RetLens-setup (+https://github.com/rlawlsgus/retarget-lens)"

# -- Blender 4.5 LTS (portable zip; the newest 4.5.x in the publisher's folder, SHA-256 from its .sha256 file)
BLENDER_INDEX = "https://download.blender.org/release/Blender4.5/"
BLENDER_FREE_GB = 1.5  # zip ~0.4 GB + unpacked ~1 GB

# -- GMT (github.com/zixuan417/humanoid-general-motion-tracking at the commit scripts/install_gmt.ps1 pins)
GMT_REPO = "zixuan417/humanoid-general-motion-tracking"
GMT_COMMIT = "2a590de25a1eb08e47491977a738549c22f16e1f"
GMT_RAW = f"https://raw.githubusercontent.com/{GMT_REPO}/{GMT_COMMIT}/"
GMT_FILES = {  # path in the repository: (git blob SHA-1, bytes)
    "LICENSE": ("74a8433393a4937a462c9bf1bca1614be89a10a5", 622),
    "README.md": ("07b1eed7fc3d46121ad5af0cd2ea6f56d8091f36", 3204),
    "assets/pretrained_checkpoints/pretrained.pt": ("aaf7e4e612ac621e9ffc4cb508ab7fa432201306", 8291216),
}
GMT_MODEL_FILES = {  # only when no G1 MuJoCo model is at hand (the installed program ships one)
    "assets/robots/g1/g1.xml": ("9b9ae627540734ea7bd2f73bd67f9f442f67962e", 26860),
    **{f"assets/robots/g1/meshes/{name}": sha for name, sha in {
        "head_link.STL": ("2ee5fba15de3ccd4c31774bc7a66de7aeefab770", 932784),
        "left_ankle_pitch_link.STL": ("69de8490184afc698f633e34bb74e65351bd4689", 71184),
        "left_ankle_roll_link.STL": ("8864e9f98103190883d1ba027aba5469925f2bca", 653384),
        "left_elbow_link.STL": ("1a96d99ba469960173129084ab6dd3bf8a732a71", 88784),
        "left_hip_pitch_link.STL": ("5b751c767ecf03b29c707b19f1faf5367e8d33d2", 181684),
        "left_hip_roll_link.STL": ("778437ffe61731915fa4cb7cf2390e9cbe738c43", 192184),
        "left_hip_yaw_link.STL": ("383093ab96ed3a099ab79f5d6ed144fc0b7067a9", 296284),
        "left_knee_link.STL": ("f2e98e54e8f1980eb62ad25c7a838044c23bbadf", 854884),
        "left_rubber_hand.STL": ("c44830f1fd519ee28750cad04d7d0adb209c265f", 2287484),
        "left_shoulder_pitch_link.STL": ("e698311fb12d3f22f018b668c40dab667c39b8d3", 176784),
        "left_shoulder_roll_link.STL": ("80bca84aca41137f8270fb35e263dcc5d9658e43", 400284),
        "left_shoulder_yaw_link.STL": ("281e699055ffafe094f52a440547eb4b64f83bfa", 249184),
        "left_wrist_pitch_link.STL": ("82cc224a8e41251d879502f9809e31d0988ec7f9", 85984),
        "left_wrist_roll_link.STL": ("f3c263a7ab3fc1e902bf2513064d4bc666c6b59f", 356184),
        "left_wrist_yaw_link.STL": ("31be4fd45fa18987b35b3386fdce2ce98c798774", 318684),
        "logo_link.STL": ("e9792098504b64b359fbffa983373e5e6fa1b50a", 243384),
        "pelvis.STL": ("691a779b9c9f4c97f48eaa9edf9eb336ca3b4411", 1060884),
        "pelvis_contour_link.STL": ("42434339abf5a0a3816f890389e3e61af3b1e03c", 1805184),
        "right_ankle_pitch_link.STL": ("e77d8a2fe1e5d56fac049833d254d6ffa4f6b350", 71184),
        "right_ankle_roll_link.STL": ("d4261dd7ccf39dd9c54cad37c1982f1d50e6fccc", 653784),
        "right_elbow_link.STL": ("f259e3812efb9985d6463c04d3e8a4b53793a699", 88784),
        "right_hip_pitch_link.STL": ("998a0a0f5c248b217cf82c5088d6d365d9654ecd", 181284),
        "right_hip_roll_link.STL": ("47b2eebdd36c7289679eebb9583c65a15514e194", 192684),
        "right_hip_yaw_link.STL": ("371856427c7cc31ae7463c83f00ef6652c72d672", 296284),
        "right_knee_link.STL": ("76d21a3d81e4e34520c5d6b3f28d7e43c1874364", 852284),
        "right_rubber_hand.STL": ("0aacffbb8168f0bb588f8cba3f37f9e2c6e0421a", 2192684),
        "right_shoulder_pitch_link.STL": ("3f5b4ed47ade68e83f617ef3fd65cb810e9b0e07", 176784),
        "right_shoulder_roll_link.STL": ("179d61753d48b3a55165b81ded2c14e84deb81c2", 401884),
        "right_shoulder_yaw_link.STL": ("2ba6076a8853edac5e3e17cffd2c256318e88d92", 249984),
        "right_wrist_pitch_link.STL": ("da194543c40df9d492abb0553c06cc614a78caae", 79584),
        "right_wrist_roll_link.STL": ("26868d2282b7e38c2ba40e00968d2c92c421fbd2", 356084),
        "right_wrist_yaw_link.STL": ("d788902867014c5984e6029fce822508579f73dc", 341484),
        "torso_link_rev_1_0.STL": ("8a759a709750ad97e1f372db0ebbff246daedcc1", 2570584),
        "waist_roll_link_rev_1_0.STL": ("a64f330c592582dc31cdf38f4d08cfff06681c5f", 85884),
        "waist_yaw_link_rev_1_0.STL": ("0fabb63d37627cb77f64c5d2a46cf25d4acc66fc", 619984),
    }.items()},
}

# -- Isaac Sim 6.1 (standalone zip, as scripts/install_isaacsim.ps1)
ISAAC_VERSION = "6.1.0"
ISAAC_ZIP = f"isaac-sim-standalone-{ISAAC_VERSION}-windows-x86_64.zip"
ISAAC_BASE = "https://downloads.isaacsim.nvidia.com/"
ISAAC_MD5 = "a07968e980072c9ca27b2166443e2d89"  # from NVIDIA's 6.1.0 download page
ISAAC_ZIP_GB, ISAAC_UNPACKED_GB = 10.5, 25.0
ISAAC_MIN_DRIVER = (595, 97)  # NVIDIA's tested driver for Isaac Sim 6.x
ISAAC_MIN_VRAM_GB, ISAAC_GOOD_VRAM_GB = 8.0, 16.0
ISAAC_EULA_URL = "https://docs.isaacsim.omniverse.nvidia.com/latest/common/NVIDIA_Omniverse_License_Agreement.html"

# -- SMPL-X (registration at smpl-x.is.tue.mpg.de; its zip holds models/smplx/SMPLX_<GENDER>.npz)
SMPL_SITE = "https://smpl-x.is.tue.mpg.de/"
SMPL_MEMBER = re.compile(r"(?:^|/)smplx/(SMPLX_(?:NEUTRAL|MALE|FEMALE)\.npz)$", re.IGNORECASE)


@dataclass
class License:
    name: str
    summary: str  # what the user agrees to, shown before the install
    url: str
    consent: bool  # the user must agree (a click) before anything is downloaded


LICENSES = {
    "blender": License("GPL v3 이상", "Blender는 자유 소프트웨어입니다. blender.org가 배포하는 그대로 받습니다.",
                       "https://www.blender.org/about/license/", False),
    "gmt": License("Apache-2.0 (코드) · 연구용 (모델)",
                   "GMT 추적 정책은 저자들이 연구 목적으로만 제공합니다(README: \"for research use only\"). 연구 목적으로만 "
                   "쓰고, 사용으로 생기는 문제는 사용자 책임이라는 데 동의해야 받습니다. 파일은 저자들의 GitHub에서 받습니다.",
                   f"https://github.com/{GMT_REPO}", True),
    "isaac": License("NVIDIA Omniverse License Agreement (EULA)",
                     "Isaac Sim은 NVIDIA의 EULA에 동의한 경우에만 받고 쓸 수 있습니다. 링크의 전문을 읽고 동의하면 NVIDIA에서 "
                     "직접 받습니다. 이 동의는 RetLens의 물리 모드 동의로도 쓰입니다.", ISAAC_EULA_URL, True),
    "smpl": License("SMPL-X 모델 라이선스 (비상업, 등록 필요)",
                    "SMPL-X 모델은 등록한 사람만 받을 수 있고 다시 배포할 수 없습니다. 사이트에서 직접 받은 zip을 가져오세요.",
                    SMPL_SITE, True),
}
NAMES = {"blender": "Blender 4.5 LTS", "gmt": "GMT 추적 정책", "isaac": f"Isaac Sim {ISAAC_VERSION[:3]}",
         "smpl": "SMPL-X 모델"}
NEEDED_FOR = {"blender": "FBX 파일 열기", "gmt": "물리 모드 균형 제어 '추적 정책 (GMT)'",
              "isaac": "물리 모드 '보조 힘 (Isaac)', 동영상 저장", "smpl": "AMASS SMPL-X 파일 열기"}


@dataclass
class Requirement:
    name: str
    ok: bool
    detail: str
    blocking: bool = True  # False: only a warning, the install can still run


@dataclass
class Status:
    key: str
    name: str
    needed_for: str
    state: str  # ready | incompatible | missing
    found: str = ""  # what is on this PC (path, version)
    detail: str = ""
    action: str = "none"  # none | configure | install | manual | blocked
    note: str = ""  # what the action does, or what blocks it
    download: str = ""  # from where, how big
    requirements: list[Requirement] = field(default_factory=list)
    license: License | None = None
    target: str = ""  # configure: the compatible copy to point the settings at

    def to_dict(self) -> dict:
        return asdict(self)


class Cancelled(Exception):
    pass


class SetupError(RuntimeError):
    pass


class _Dropped(Exception):
    """A response that ended before its Content-Length (resumed like a dropped connection)."""


Progress = Callable[[str, float, float], None]  # (stage, done, total); total 0 = unknown


# ------------------------------------------------------------------------------ this PC
def tools_dir() -> str:
    return os.path.join(paths.user_dir(), settings.TOOLS)


def downloads_dir() -> str:
    return os.path.join(paths.user_dir(), "downloads")


def _run(cmd: list[str], timeout: float = 20.0) -> str | None:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                             encoding="utf-8", errors="replace")
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def windows() -> tuple[bool, str, int]:
    """(Windows x64, its name, build number)."""
    if os.name != "nt":
        return False, platform.system(), 0
    build = sys.getwindowsversion().build
    name = ("Windows 11" if build >= 22000 else "Windows 10") + f" (빌드 {build})"
    return platform.machine().upper() in ("AMD64", "X86_64"), name, build


def nvidia_gpus() -> list[dict]:
    """[{name, driver, vram_gb}] from nvidia-smi ([] without an NVIDIA driver)."""
    out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            try:
                gpus.append({"name": parts[0], "driver": parts[1], "vram_gb": round(float(parts[2]) / 1024, 1)})
            except ValueError:
                continue
    return gpus


def free_gb(path: str) -> float:
    """Free space (GB) on the drive that holds path (or would: its nearest existing folder)."""
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    try:
        return shutil.disk_usage(p).free / 1e9
    except OSError:
        return 0.0


def writable(path: str) -> bool:
    """Whether this user can make the folder (or write into it when it exists), tried for real
    (settings._writable: on Windows os.access says yes to every folder). Nothing is left behind."""
    return settings._writable(path)


def _drive(path: str) -> str:
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def _request(url: str, headers: dict | None = None, method: str = "GET"):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, method=method)


def reachable(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Whether the publisher answers (a one-byte request); (False, why) offline or blocked."""
    try:
        with urllib.request.urlopen(_request(url, {"Range": "bytes=0-0"}), timeout=timeout) as r:
            return r.status < 400, ""
    except urllib.error.HTTPError as e:
        return e.code < 400, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:  # a bad reply: not reachable
        return False, str(getattr(e, "reason", e)) or type(e).__name__


def _host(url: str) -> str:
    return url.split("/")[2] if "://" in url else url


def _net_requirement(url: str) -> Requirement:
    ok, why = reachable(url)
    return Requirement("인터넷", ok, f"{_host(url)}에 연결됨" if ok else f"{_host(url)}에 연결할 수 없음 ({why})")


def _disk_requirement(folder: str, need_gb: float, what: str) -> Requirement:
    have = free_gb(folder)
    return Requirement(f"디스크 ({what})", have >= need_gb, f"{_drive(folder).upper() or folder} 여유 {have:.1f} GB / "
                                                            f"필요 {need_gb:.1f} GB")


def _write_requirement(folder: str) -> Requirement:
    ok = writable(folder)
    return Requirement("쓰기 권한", ok, f"{folder}에 쓸 수 있음" if ok else f"{folder}에 쓸 수 없음")


def _decide(st: Status, reqs: list[Requirement], manual: bool = False) -> Status:
    st.requirements = reqs
    bad = [r for r in reqs if r.blocking and not r.ok]
    if manual:
        st.action, st.note = "manual", "사이트에서 직접 받아 가져와야 합니다(자동으로 받을 수 없음)"
    elif bad:
        st.action = "blocked"
        st.note = "지금 이 PC에는 설치할 수 없습니다: " + "; ".join(f"{r.name} - {r.detail}" for r in bad)
    else:
        st.action = "install"
        warn = [r for r in reqs if not r.ok]
        st.note = "설치할 수 있습니다" + (" (주의: " + "; ".join(f"{r.name} - {r.detail}" for r in warn) + ")" if warn else "")
    return st


# ------------------------------------------------------------------------------ Blender
def blender_version(exe: str) -> str:
    """'4.5.14' from the path, else from `blender --version` ('' when unknown)."""
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", settings._blender_version(exe))
    if m:
        return m.group(1)
    out = _run([exe, "--version"], timeout=60)
    m = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", out or "")
    return m.group(1) if m else ""


def _blender_ok(version: str) -> bool:
    return version == settings.BLENDER_VERSION or version.startswith(settings.BLENDER_VERSION + ".")


def _probe_blender(s: settings.Settings, online: bool, **_) -> Status:
    st = Status("blender", NAMES["blender"], NEEDED_FOR["blender"], "missing", license=LICENSES["blender"])
    found = settings.find_blender(s)
    seen = []
    if found.path:
        v = blender_version(found.path)
        seen.append(f"{found.path} (Blender {v or '버전 모름'}, {found.source})")
        if _blender_ok(v):
            st.state, st.found, st.detail = "ready", found.path, f"Blender {v} · {found.source}"
            st.note = "호환되는 Blender가 있어 설치하지 않습니다"
            return st
    else:
        st.detail = found.problem
    # the setting / variable may point at another version while a 4.5 sits in a usual place
    for exe, where in settings.blender_candidates():
        if found.path and os.path.normcase(exe) == os.path.normcase(found.path):
            continue
        v = blender_version(exe)
        if _blender_ok(v):
            st.state, st.found, st.target = "incompatible", seen[0] if seen else "", exe
            st.action, st.detail = "configure", f"Blender {v} · {where}"
            st.note = f"호환되는 Blender {v}가 이미 있어 받지 않고 그것으로 설정합니다 ({exe})"
            return st
        seen.append(f"{exe} (Blender {v or '버전 모름'}, {where})")
    if seen:
        st.state, st.found = "incompatible", "; ".join(seen)
        st.detail = f"Blender {settings.BLENDER_VERSION}가 아닙니다(FBX 읽기는 4.5 LTS로 확인했습니다)"
    ok, name, _ = windows()
    reqs = [Requirement("운영체제", ok, f"{name}, {platform.machine()}" + ("" if ok else ": Windows 64비트가 필요합니다"))]
    reqs += [_disk_requirement(tools_dir(), BLENDER_FREE_GB, "설치 폴더"), _write_requirement(tools_dir())]
    if online:
        reqs.append(_net_requirement(BLENDER_INDEX))
    st.download = f"blender.org 공식 zip (약 400 MB) → {tools_dir()}"
    return _decide(st, reqs)


def _wait(seconds: float, cancel: threading.Event | None) -> None:
    """Back off before a retry; a cancel ends the wait (and the install) at once."""
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise Cancelled()


def _fetch_text(url: str, retries: int = 3, cancel: threading.Event | None = None) -> str:
    """A small text file (an index page, a checksum list), retried; network trouble as SetupError."""
    for attempt in range(retries + 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            with urllib.request.urlopen(_request(url), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise SetupError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if attempt == retries:
                raise SetupError(f"{url}: {getattr(e, 'reason', e)}") from None
        _wait(min(2 ** attempt, 8), cancel)
    raise SetupError(url)


def blender_release(index: str = BLENDER_INDEX, cancel: threading.Event | None = None) -> tuple[str, str, str]:
    """(version, zip url, sha256) of the newest Blender 4.5.x for Windows x64 in the publisher's folder."""
    html = _fetch_text(index, cancel=cancel)
    patch = sorted({int(n) for n in re.findall(r"blender-4\.5\.(\d+)-windows-x64\.zip", html)})
    if not patch:
        raise SetupError(f"{index}에서 Blender 4.5 Windows zip을 찾지 못했습니다")
    version = f"4.5.{patch[-1]}"
    name = f"blender-{version}-windows-x64.zip"
    sums = _fetch_text(index + f"blender-{version}.sha256", cancel=cancel)
    m = re.search(r"^([0-9a-f]{64})\s+\*?" + re.escape(name) + r"\s*$", sums, re.MULTILINE | re.IGNORECASE)
    if not m:
        raise SetupError(f"blender-{version}.sha256에 {name}의 SHA-256이 없습니다")
    return version, index + name, m.group(1).lower()


# ------------------------------------------------------------------------------ GMT
def git_blob_sha1(path: str) -> str:
    h = hashlib.sha1()
    h.update(f"blob {os.path.getsize(path)}\0".encode())
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gmt_policy_ok(path: str) -> tuple[bool, str]:
    """The policy file is the pinned one, or at least a GMT policy this program can run (the same
    network code, other weights)."""
    if git_blob_sha1(path) == GMT_FILES["assets/pretrained_checkpoints/pretrained.pt"][0]:
        return True, f"확인된 버전 (GMT {GMT_COMMIT[:7]})"
    from .gmt_policy import problem

    bad = problem(path)
    return (False, bad) if bad else (True, "다른 체크포인트 (같은 신경망 코드라 쓸 수 있음)")


def _gmt_folder_ok(folder: str) -> tuple[bool, str]:
    policy = os.path.join(folder, settings.GMT_POLICY)
    if not os.path.isfile(policy):
        return False, f"{policy}에 없습니다"
    ok, why = _gmt_policy_ok(policy)
    if not ok:
        return False, why
    if not os.path.isfile(settings.gmt_model(folder)):
        return False, f"G1 MuJoCo 모델이 없습니다 ({os.path.join(folder, settings.GMT_MODEL)})"
    return True, why


def _probe_gmt(s: settings.Settings, online: bool, **_) -> Status:
    st = Status("gmt", NAMES["gmt"], NEEDED_FOR["gmt"], "missing", license=LICENSES["gmt"])
    folder, source = settings._gmt_place(s)
    ok, why = _gmt_folder_ok(folder)
    if ok:
        st.state, st.found, st.detail = "ready", folder, f"{why} · {source}"
        st.note = "추적 정책이 있어 설치하지 않습니다"
        return st
    st.detail = why
    if os.path.isfile(os.path.join(folder, settings.GMT_POLICY)):
        st.state, st.found = "incompatible", folder
    # the setting / variable may point at a moved or broken folder while a good copy sits elsewhere
    for other, where in settings.gmt_places(s):
        if os.path.normcase(os.path.abspath(other)) == os.path.normcase(os.path.abspath(folder)):
            continue
        good, how = _gmt_folder_ok(other)
        if good:
            st.target, st.action = other, "configure"
            st.note = f"쓸 수 있는 GMT가 이미 있어 받지 않고 그것으로 설정합니다 ({other}, {where}: {how})"
            return st
    dest = os.path.join(paths.user_dir(), settings.GMT_INSTALL)
    files = _gmt_wanted()
    size = sum(n for _, n in files.values()) / 1e6
    import importlib.util

    reqs = [Requirement("MuJoCo", importlib.util.find_spec("mujoco") is not None, "추적 정책을 돌리는 시뮬레이터")]
    reqs += [_disk_requirement(dest, size / 1e3 + 0.05, "설치 폴더"), _write_requirement(dest)]
    if online:
        reqs.append(_net_requirement(GMT_RAW + "LICENSE"))
    st.download = f"GitHub {GMT_REPO}@{GMT_COMMIT[:7]}, {len(files)}개 파일 {size:.0f} MB → {dest}"
    return _decide(st, reqs)


def _gmt_wanted() -> dict:
    """GMT's files for <user data>\\gmt: the policy and its licence, plus the G1 model and meshes
    unless the program ships its own model (the installed program does; the repository does not).
    Never judged by what an earlier <user data>\\gmt holds: the new folder replaces it whole."""
    files = dict(GMT_FILES)
    if not settings.bundled_gmt_model():
        files.update(GMT_MODEL_FILES)
    return files


# ------------------------------------------------------------------------------ Isaac Sim
def _isaac_ok(version: str) -> bool:
    return version.startswith(ISAAC_VERSION[:3] + ".") or version == ISAAC_VERSION[:3]


def isaac_target() -> str | None:
    """Where a new Isaac Sim goes: C:\\isaacsim, or C:\\isaacsim-6.1.0 when that is taken - an
    existing folder is never replaced (an older Isaac, the user's extensions); an empty one is
    free. None: both taken."""
    base = settings.ISAAC_DIRS[0]
    for d in (base, f"{base}-{ISAAC_VERSION}"):
        if not os.path.exists(d) or (os.path.isdir(d) and not os.listdir(d)):
            return d
    return None


def _driver_tuple(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in text.split("."))
    except ValueError:
        return (0,)


_ISAAC_PROBE = ("import importlib.util as u, importlib.metadata as m\n"
                "if u.find_spec('isaacsim') is None:\n    print('<absent>')\n"
                "else:\n    try:\n        print(m.version('isaacsim'))\n    except Exception:\n        print('<unknown>')\n")


def isaac_version(launcher: str) -> str | None:
    """'6.1.0-rc.26' of an Isaac Sim launcher: the VERSION file next to python.bat, or the isaacsim
    package of a Python environment (pip install). '' when it cannot be told; None when the launcher
    is a Python that cannot import isaacsim at all (or does not run) - no Isaac Sim."""
    if os.path.basename(launcher).lower() == settings.ISAAC_LAUNCHER:
        return settings._isaac_version(launcher)
    if not paths.FROZEN and os.path.normcase(os.path.abspath(launcher)) == os.path.normcase(sys.executable):
        import importlib.metadata
        import importlib.util

        if importlib.util.find_spec("isaacsim") is None:
            return None
        try:
            return importlib.metadata.version("isaacsim")
        except Exception:  # isaacsim imported from a path, not installed as a distribution
            return ""
    out = (_run([launcher, "-c", _ISAAC_PROBE], timeout=60) or "").strip()
    last = out.splitlines()[-1].strip() if out else "<absent>"
    return None if last == "<absent>" else "" if last == "<unknown>" else last


def isaac_candidates(s: settings.Settings) -> list[tuple[str, str]]:
    """(launcher, where) of every Isaac Sim in the usual places: KHUMANOID_ISAAC_PYTHON (also when a
    stale setting hides it), this Python's isaacsim (dev), the install folders (C:\\isaacsim and the
    assistant's C:\\isaacsim-<version>)."""
    out = []
    env = os.environ.get(settings.ISAAC_ENV, "")
    if env and os.path.isfile(settings._isaac_launcher(env)):
        out.append((settings._isaac_launcher(env), f"환경변수 {settings.ISAAC_ENV}"))
    if not paths.FROZEN:
        import importlib.util

        if importlib.util.find_spec("isaacsim") is not None:
            out.append((sys.executable, "자동 (이 파이썬 환경)"))
    for folder in settings.isaac_dirs():
        launcher = os.path.join(folder, settings.ISAAC_LAUNCHER)
        if os.path.isfile(launcher):
            out.append((launcher, f"자동 ({folder})"))
    return out


def _probe_isaac(s: settings.Settings, online: bool, download_dir: str | None = None) -> Status:
    st = Status("isaac", NAMES["isaac"], NEEDED_FOR["isaac"], "missing", license=LICENSES["isaac"])
    found = settings.find_isaac(s)
    seen = []
    if found.path:
        v = isaac_version(found.path)
        # a launcher the user chose (or the dev env's own isaacsim) whose version cannot be read is trusted,
        # as long as it is an Isaac Sim at all (a Python that cannot import isaacsim is not)
        trusted = found.source in ("설정", f"환경변수 {settings.ISAAC_ENV}") or found.source.startswith("자동 (이 파이썬")
        if v is not None and (_isaac_ok(v) or (not v and trusted)):
            st.state, st.found = "ready", found.path
            st.detail = " · ".join(x for x in (f"Isaac Sim {v}" if v else "버전 확인 불가(사용자가 지정)", found.source) if x)
            st.note = "Isaac Sim이 있어 설치하지 않습니다"
            return st
        st.state, st.found = "incompatible", found.path
        seen.append(found.path)
        st.detail = (f"{found.source}의 {found.path}는 isaacsim을 불러올 수 없는 파이썬입니다" if v is None else
                     f"Isaac Sim {v or '버전 모름'}: RetLens는 {ISAAC_VERSION[:3]}로 확인했습니다")
    else:
        st.detail = found.problem
    # the setting / variable may point at a moved or older Isaac while a 6.1 sits in a usual place
    for launcher, where in isaac_candidates(s):
        if any(os.path.normcase(launcher) == os.path.normcase(x) for x in seen):
            continue
        v = isaac_version(launcher)
        if v is not None and _isaac_ok(v):
            st.target, st.action = launcher, "configure"
            st.note = f"호환되는 Isaac Sim {v}가 이미 있어 받지 않고 그것으로 설정합니다 ({launcher}, {where})"
            return st
    target = isaac_target()
    dl = download_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    zip_path = os.path.join(dl, ISAAC_ZIP)
    ok, name, build = windows()
    reqs = [Requirement("운영체제", ok, name + ("" if ok else ": Windows 64비트가 필요합니다")),
            Requirement("Windows 11", build >= 22000, "NVIDIA는 Windows 11에서 시험했습니다(10에서도 대개 동작)", False)]
    gpus = nvidia_gpus()
    rtx = [g for g in gpus if "RTX" in g["name"].upper()]
    if not gpus:
        reqs.append(Requirement("GPU", False, "NVIDIA GPU·드라이버를 찾지 못했습니다(nvidia-smi 없음). RTX GPU가 필요합니다"))
    elif not rtx:
        reqs.append(Requirement("GPU", False, f"{', '.join(g['name'] for g in gpus)}: RTX GPU가 필요합니다"))
    else:
        g = max(rtx, key=lambda x: x["vram_gb"])
        reqs.append(Requirement("GPU", g["vram_gb"] >= ISAAC_MIN_VRAM_GB,
                                f"{g['name']}, VRAM {g['vram_gb']:.0f} GB (최소 {ISAAC_MIN_VRAM_GB:.0f} GB)"))
        if g["vram_gb"] < ISAAC_GOOD_VRAM_GB:
            reqs.append(Requirement("VRAM 권장", False, f"공식 권장 {ISAAC_GOOD_VRAM_GB:.0f} GB (로봇 하나 장면은 8 GB로 됨)",
                                    False))
        drv = _driver_tuple(g["driver"])
        reqs.append(Requirement("드라이버", drv >= ISAAC_MIN_DRIVER,
                                f"{g['driver']} (시험한 버전 {'.'.join(map(str, ISAAC_MIN_DRIVER))} 이상 권장)", False))
    if target is None:
        base = settings.ISAAC_DIRS[0]
        reqs.append(Requirement("설치 폴더", False, f"{base}와 {base}-{ISAAC_VERSION}이 이미 있습니다. 기존 설치를 지우지 않으므로 "
                                                f"둘 중 하나를 비우거나 지운 뒤 다시 점검하세요"))
        target = base
    # a complete zip already in Downloads (zipfile reads its directory at the end: a cut-off download
    # has none) is used if its MD5 matches. Then only the unpacked size must fit; fetching it again
    # (another build under that name), the network and the download folder only warn.
    have_zip = os.path.isfile(zip_path) and zipfile.is_zipfile(zip_path)
    if have_zip:
        reqs.append(_disk_requirement(target, ISAAC_UNPACKED_GB, "설치"))
        again = _disk_requirement(dl, ISAAC_ZIP_GB + (ISAAC_UNPACKED_GB if _drive(dl) == _drive(target) else 0),
                                  "zip을 다시 받아야 할 때")
        again.blocking = False
        reqs.append(again)
    elif _drive(dl) == _drive(target):
        reqs.append(_disk_requirement(target, ISAAC_ZIP_GB + ISAAC_UNPACKED_GB, "받기 + 설치"))
    else:
        reqs += [_disk_requirement(dl, ISAAC_ZIP_GB, "받기"), _disk_requirement(target, ISAAC_UNPACKED_GB, "설치")]
    w = _write_requirement(dl)
    w.blocking = not have_zip
    reqs += [_write_requirement(target), w]
    if online:
        net = _net_requirement(ISAAC_BASE + ISAAC_ZIP)
        net.blocking = not have_zip
        reqs.append(net)
    st.download = (f"NVIDIA 공식 zip (약 {ISAAC_ZIP_GB:.0f} GB" +
                   (", 다운로드 폴더에 받아 둔 zip은 MD5가 맞으면 사용" if have_zip else "") +
                   f") → {target} (새 폴더, 기존 설치는 건드리지 않음), 풀면 약 {ISAAC_UNPACKED_GB:.0f} GB")
    st.target = target
    return _decide(st, reqs)


# ------------------------------------------------------------------------------ SMPL-X
def smpl_places(s: settings.Settings) -> list[tuple[str, str]]:
    """Every folder SMPL-X models are looked for in (the default one also without SMPL_MODEL_DIR)."""
    out = [(s.smpl_model_dir, "설정"), (os.environ.get("SMPL_MODEL_DIR", ""), "환경변수 SMPL_MODEL_DIR"),
           (paths.default_smpl_model_dir(), "기본 위치")]
    return [(settings.smpl_root(p), how) for p, how in out if p]


def smpl_import_dir() -> str:
    """Where imported SMPL-X models go (the folder holding smplx\\): SMPL_MODEL_DIR or the default."""
    return settings.smpl_root(paths.smpl_model_dir())


def _probe_smpl(s: settings.Settings, online: bool, **_) -> Status:
    st = Status("smpl", NAMES["smpl"], NEEDED_FOR["smpl"], "missing", license=LICENSES["smpl"])
    found = settings.find_smpl(s)
    if found.path:
        st.state, st.found, st.detail = "ready", found.path, f"{found.detail} · {found.source}"
        st.note = "SMPL-X 모델이 있어 가져올 필요가 없습니다"
        return st
    st.detail = found.problem
    # the setting / variable may point at a moved folder while the models sit in the usual one
    for folder, where in smpl_places(s):
        have = settings._smpl_files(folder)
        if "NEUTRAL" in have:
            st.target, st.action = folder, "configure"
            st.note = f"SMPL-X 모델이 이미 있어 그 폴더로 설정합니다 ({folder}, {where}: SMPLX {', '.join(have)})"
            return st
    folder = smpl_import_dir()
    st.download = f"{SMPL_SITE}에서 등록 후 'SMPL-X v1.1 (NPZ+PKL)' zip을 받아 가져오기 → {folder}"
    return _decide(st, [_disk_requirement(folder, 1.0, "모델 폴더"), _write_requirement(folder)], manual=True)


# ------------------------------------------------------------------------------ probe
def probe(key: str, s: settings.Settings | None = None, online: bool = True, **kw) -> Status:
    """What this PC has for the component and what to do about it (see the module docstring).
    online=False skips the publisher check (faster; the install itself still needs the network).
    kw: download_dir for Isaac (where its zip goes; default the user's Downloads)."""
    s = s or settings.load(reload=True)
    fn = {"blender": _probe_blender, "gmt": _probe_gmt, "isaac": _probe_isaac, "smpl": _probe_smpl}.get(key)
    if fn is None:
        raise KeyError(f"unknown component {key!r} ({', '.join(KEYS)})")
    return fn(s, online, **kw)


def probe_all(s: settings.Settings | None = None, online: bool = True) -> list[Status]:
    s = s or settings.load(reload=True)
    return [probe(k, s, online) for k in KEYS]


# ------------------------------------------------------------------------------ download / unpack
def _check(path: str, sha256: str | None, md5: str | None, git_sha1: str | None,
           cancel: threading.Event | None = None) -> bool:
    if git_sha1:
        return git_blob_sha1(path) == git_sha1
    h = hashlib.sha256() if sha256 else hashlib.md5() if md5 else None
    if h is None:
        return True
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            if cancel is not None and cancel.is_set():  # hashing 10 GB takes a while
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest().lower() == (sha256 or md5).lower()


def download(url: str, dest: str, *, sha256: str | None = None, md5: str | None = None, git_sha1: str | None = None,
             progress: Progress | None = None, cancel: threading.Event | None = None, stage: str = "받는 중",
             retries: int = 4) -> str:
    """url -> dest, resuming <dest>.part, verified before it gets its name. A file already at dest that
    passes the check is reused. Cancel keeps the .part for the next try. Retries back off and give up
    after `retries` tries in a row that brought the file no further than it ever was."""
    progress = progress or (lambda *_: None)
    part = dest + ".part"
    if os.path.isfile(dest) and _check(dest, sha256, md5, git_sha1, cancel):
        if os.path.isfile(part):  # an earlier, interrupted try: the file is complete now
            try:
                os.remove(part)
            except OSError:
                pass
        return dest
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    attempt = 0
    best = os.path.getsize(part) if os.path.isfile(part) else 0  # the most of the file ever held
    while True:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        done = have
        try:
            req = _request(url, {"Range": f"bytes={have}-"} if have else None)
            with urllib.request.urlopen(req, timeout=60) as r:
                length = r.headers.get("Content-Length")
                if have and r.status != 206:  # the server ignored the range
                    kind = (r.headers.get("Content-Type") or "").lower()
                    if kind.startswith("text/html") or (length is not None and int(length) < have):
                        # a proxy or captive-portal page, not the file: keep what is in the .part
                        raise _Dropped(f"HTTP {r.status} {kind or ''} {length or '?'} bytes instead of the file")
                    have = done = 0  # the whole file again: start over
                total = have + int(length) if length else 0
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        progress(stage, done, total)
            if total and done < total:  # the server closed early: what came stays in the .part, ask for the rest
                raise _Dropped(f"{done} of {total} bytes")
            break
        except urllib.error.HTTPError as e:
            if e.code == 416 and have:  # asked past the end: the .part is complete (or broken; the check decides)
                break
            if e.code < 500 or attempt >= retries:
                raise SetupError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException, ValueError, _Dropped) as e:
            if done > best:  # further than ever: a long download with occasional drops goes on
                attempt = 0
            elif attempt >= retries:  # (a server that ignores Range and drops at the same place ends here)
                raise SetupError(f"{url}: {getattr(e, 'reason', e)} (받은 부분은 남겨 두어 다음에 이어 받습니다)") from None
        best = max(best, done)
        attempt += 1
        _wait(min(2 ** attempt, 15), cancel)
    progress("확인 중", 0, 0)
    if not _check(part, sha256, md5, git_sha1, cancel):
        os.remove(part)
        raise SetupError(f"{os.path.basename(dest)}: 받은 파일의 체크섬이 배포처 값과 다릅니다(지웠습니다, 다시 시도하세요)")
    os.replace(part, dest)
    return dest


def _safe_members(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    out = []
    for m in z.infolist():
        name = m.filename.replace("\\", "/")
        if name.startswith("/") or ":" in name or ".." in name.split("/"):
            raise SetupError(f"zip에 위험한 경로가 있습니다: {m.filename}")
        out.append(m)
    return out


def _place(tmp: str, dest: str, replace: bool, keep_tmp: bool = False) -> None:
    """Move a finished tmp folder to dest. An existing dest is replaced only when replace (the
    assistant's own folders); an empty one is fine; anything else is never touched. A replaced dest
    is first renamed to <dest>.old in one step (that fails while a file in it is open, leaving it
    whole) and deleted only once the new folder is in place; on failure it is put back. keep_tmp:
    leave tmp for the next try (GMT's verified downloads) instead of deleting it."""
    old = None
    try:
        if os.path.exists(dest):
            if os.path.isdir(dest) and not os.listdir(dest):
                os.rmdir(dest)
            elif replace:
                old = dest + ".old"
                shutil.rmtree(old, ignore_errors=True)
                os.replace(dest, old)
            else:
                raise SetupError(f"{dest}이(가) 이미 있어 덮어쓰지 않았습니다")
        os.replace(tmp, dest)
    except (OSError, SetupError) as e:
        if old is not None and not os.path.exists(dest) and os.path.isdir(old):
            try:
                os.replace(old, dest)  # the earlier copy back where it was
            except OSError:
                pass
        if not keep_tmp:  # e.g. a 25 GB .partial
            shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(e, SetupError):
            raise
        raise SetupError(f"{dest}에 옮기지 못했습니다(프로그램이 쓰고 있는지 확인하세요): {e}") from None
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def unpack(zip_path: str, dest: str, progress: Progress | None = None, cancel: threading.Event | None = None,
           only: Callable[[str], str | None] | None = None, replace: bool = False) -> str:
    """zip -> dest via dest.partial (moved into place when every file is out, _place). only(name)
    maps a member to its path under dest, or None to skip it."""
    progress = progress or (lambda *_: None)
    tmp = dest + ".partial"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        with zipfile.ZipFile(zip_path) as z:
            members = _safe_members(z)
            total = sum(m.file_size for m in members) or 1
            done = 0
            for m in members:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                rel = only(m.filename) if only else m.filename
                if rel is None or m.is_dir():
                    continue
                out = os.path.join(tmp, *rel.replace("\\", "/").split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with z.open(m) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)
                done += m.file_size
                progress("푸는 중", done, total)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SetupError(f"{os.path.basename(zip_path)}를 {tmp}에 풀지 못했습니다: {e}") from None
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _place(tmp, dest, replace)
    return dest


def _save(**changes) -> None:
    s = settings.load(reload=True)
    for k, v in changes.items():
        setattr(s, k, v)
    settings.save(s)


# ------------------------------------------------------------------------------ install
def install(key: str, *, accept: bool = False, progress: Progress | None = None, cancel: threading.Event | None = None,
            source: str | None = None, expect: str | None = None, **opts) -> Status:
    """Install (or point the settings at) the component, only when probe says it is needed and
    possible; returns the new status. accept: the user agreed to its licence (needed for GMT and
    Isaac). source: a different publisher URL (tests, mirrors) or, for SMPL-X, the zip or folder.
    expect: the action the user saw and clicked; if this PC changed since (a copy moved or
    deleted), nothing is done and the user is told to check again."""
    st = probe(key, online=False, **({"download_dir": opts["download_dir"]} if opts.get("download_dir") else {}))
    if expect is not None and st.action != expect:
        raise SetupError(f"{st.name}: 점검한 뒤 이 PC의 상태가 바뀌었습니다({expect} → {st.action}). 다시 점검한 뒤 고르세요")
    if st.action == "none":
        return st
    if st.action == "configure":  # a compatible copy is already here: point the settings at it, fetch nothing
        _save(**{SETTING[key]: st.target})
        return probe(key, online=False)
    if key == "smpl":
        if not source:
            raise SetupError("SMPL-X 모델은 사이트에서 받은 zip(또는 그 압축을 푼 폴더)을 골라 가져와야 합니다")
        return import_smpl(source, progress)
    if st.action != "install":
        raise SetupError(st.note or f"{st.name}: 설치할 수 없습니다")
    lic = LICENSES[key]
    if lic.consent and not accept:
        raise SetupError(f"{st.name}: {lic.name}에 동의해야 설치합니다")
    if key == "blender":
        return install_blender(progress, cancel, index=source or BLENDER_INDEX)
    if key == "gmt":
        return install_gmt(progress, cancel, base=source or GMT_RAW)
    return install_isaac(progress, cancel, base=source or ISAAC_BASE, target=st.target, **opts)


def install_blender(progress=None, cancel=None, index: str = BLENDER_INDEX) -> Status:
    progress = progress or (lambda *_: None)
    progress("최신 4.5 확인 중", 0, 0)
    version, url, sha = blender_release(index, cancel)
    zip_path = download(url, os.path.join(downloads_dir(), url.rsplit("/", 1)[1]), sha256=sha, progress=progress,
                        cancel=cancel)
    folder = os.path.join(tools_dir(), f"blender-{version}-windows-x64")
    top = f"blender-{version}-windows-x64/"
    unpack(zip_path, folder, progress, cancel, replace=True,  # the assistant's own folder (a broken earlier try)
           only=lambda n: n.replace("\\", "/")[len(top):] if n.replace("\\", "/").startswith(top) else n)
    exe = os.path.join(folder, "blender.exe")
    if not os.path.isfile(exe):
        raise SetupError(f"{zip_path}를 풀었지만 blender.exe가 없습니다")
    _save(blender=exe)
    os.remove(zip_path)  # unpacked: the 400 MB zip is not needed again
    for stale in glob.glob(os.path.join(downloads_dir(), "blender-4.5.*-windows-x64.zip.part")):  # an older patch's
        try:                                                                                   # cut-off download
            os.remove(stale)
        except OSError:
            pass
    return probe("blender", online=False)


def install_gmt(progress=None, cancel=None, base: str = GMT_RAW) -> Status:
    """GMT's files into <user data>\\gmt.partial (each verified; kept across tries so a retry fetches
    only what is missing), moved to <user data>\\gmt once all are there."""
    progress = progress or (lambda *_: None)
    dest = os.path.join(paths.user_dir(), settings.GMT_INSTALL)
    tmp = dest + ".partial"
    files = _gmt_wanted()
    total = sum(n for _, n in files.values())
    done = 0
    for rel, (sha, size) in files.items():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        def each(stage, d, _t, before=done):  # one file's bytes as part of all of them
            if stage == "받는 중":
                progress(stage, before + d, total)

        download(base + rel, os.path.join(tmp, *rel.split("/")), git_sha1=sha, cancel=cancel, progress=each)
        done += size
        progress("받는 중", done, total)
    with open(os.path.join(tmp, "GMT_COMMIT.txt"), "w", encoding="ascii") as f:
        f.write(f"repo: https://github.com/{GMT_REPO}\ncommit: {GMT_COMMIT}\n"
                "license: Apache-2.0 (LICENSE); README: the provided model is for research use only\n"
                "installed_by: RetLens setup assistant (khumanoid/prereqs.py)\n")
    _place(tmp, dest, replace=True, keep_tmp=True)  # the assistant's own folder; on failure the files stay
    _save(gmt_dir=dest)
    return probe("gmt", online=False)


def install_isaac(progress=None, cancel=None, base: str = ISAAC_BASE, download_dir: str | None = None,
                  target: str | None = None, md5: str = ISAAC_MD5) -> Status:
    progress = progress or (lambda *_: None)
    target = target or isaac_target()
    if target is None or (os.path.exists(target) and os.listdir(target)):
        raise SetupError(f"{target or settings.ISAAC_DIRS[0]}이(가) 이미 있어 설치하지 않습니다(기존 설치는 지우지 않음)")
    dl = download_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    zip_path = download(base + ISAAC_ZIP, os.path.join(dl, ISAAC_ZIP), md5=md5, progress=progress, cancel=cancel)
    unpack(zip_path, target, progress, cancel, replace=False)  # never over an existing Isaac Sim
    launcher = os.path.join(target, settings.ISAAC_LAUNCHER)
    if not os.path.isfile(launcher):
        raise SetupError(f"{zip_path}를 풀었지만 {settings.ISAAC_LAUNCHER}가 없습니다")
    post = os.path.join(target, "post_install.bat")
    if os.path.isfile(post):  # links the GUI examples; needs admin or developer mode, optional
        progress("마무리 중", 0, 0)
        _run(["cmd.exe", "/c", post], timeout=300)
    _save(isaac_python=launcher)
    return probe("isaac", online=False, download_dir=dl)


def import_smpl(source: str, progress: Progress | None = None) -> Status:
    """SMPL-X model files from the zip the user downloaded (models/smplx/SMPLX_*.npz) or a folder
    holding them, into smpl_import_dir() (where it is found without a setting)."""
    progress = progress or (lambda *_: None)
    if os.path.isdir(source):
        folder = settings.smpl_root(os.path.normpath(source))  # the smplx folder itself: its parent is the model folder
        if not settings._smpl_files(folder):
            raise SetupError(f"{source}에 smplx\\SMPLX_NEUTRAL.npz 등이 없습니다")
        _save(smpl_model_dir=folder)
        return probe("smpl", online=False)
    if not zipfile.is_zipfile(source):
        raise SetupError(f"{source}는 zip 파일이 아닙니다")
    with zipfile.ZipFile(source) as z:
        names = [m.filename for m in _safe_members(z)]
    picked = {n: SMPL_MEMBER.search(n.replace("\\", "/")) for n in names}
    picked = {n: m.group(1) for n, m in picked.items() if m}
    if not any(v.upper() == "SMPLX_NEUTRAL.NPZ" for v in picked.values()):
        raise SetupError("zip에 smplx/SMPLX_NEUTRAL.npz가 없습니다. 사이트의 'SMPL-X v1.1 (NPZ+PKL)' zip인지 확인하세요")
    folder = smpl_import_dir()
    dest = os.path.join(folder, "smplx")
    if "NEUTRAL" in settings._smpl_files(folder):  # the models are already there: use them, import nothing
        _save(smpl_model_dir=folder)
        return probe("smpl", online=False)
    if os.path.isdir(dest) and os.listdir(dest):
        raise SetupError(f"{dest}에 다른 파일이 있습니다. 그 폴더를 비우거나 환경 설정에서 다른 폴더를 지정하세요")
    unpack(source, dest, progress, only=lambda n: picked.get(n))
    _save(smpl_model_dir=folder)  # explicit: a stale setting must not hide the imported models
    return probe("smpl", online=False)
