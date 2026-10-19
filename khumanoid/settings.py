"""The program's user settings (RetLens 환경 설정) and the check of what each feature needs.

Kept as JSON in the user data folder (paths.user_dir()/settings.json: data/settings.json in
the repository, %LOCALAPPDATA%\\RetLens\\settings.json when installed), so the editor, the
browser viewer and the command-line tools read the same values without Qt.

An empty value means "find it". Each external tool is looked up in this order:

    tool        setting          environment variable      usual places
    Isaac Sim   isaac_python     KHUMANOID_ISAAC_PYTHON    this Python when it can import isaacsim
                                                           (the dev env, never a packaged build), C:\\isaacsim
    Blender     blender          BLENDER                   C:\\blender\\*\\blender.exe, PATH
    SMPL-X      smpl_model_dir   SMPL_MODEL_DIR            paths.smpl_model_dir()

Standard library only (Isaac Sim's Python imports khumanoid too).
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields

from . import paths

ISAAC_ENV = "KHUMANOID_ISAAC_PYTHON"
ISAAC_DIRS = [r"C:\isaacsim"] if os.name == "nt" else [os.path.expanduser("~/isaacsim")]
ISAAC_LAUNCHER = "python.bat" if os.name == "nt" else "python.sh"
BLENDER_GLOB = r"C:\blender\*\blender.exe"
SMPLX_GENDERS = ("NEUTRAL", "MALE", "FEMALE")
URLS = {"isaac": "https://docs.isaacsim.omniverse.nvidia.com/latest/installation/download.html",
        "blender": "https://www.blender.org/download/lts/4-5/",
        "smpl": "https://smpl-x.is.tue.mpg.de/"}


@dataclass
class Settings:
    isaac_python: str = ""  # python.bat of an Isaac Sim install (or its folder)
    blender: str = ""  # blender.exe (Blender 4.5 LTS)
    smpl_model_dir: str = ""  # folder holding smplx/SMPLX_*.npz
    video_dir: str = ""  # where 동영상 저장 writes
    library_dirs: list[str] = field(default_factory=list)  # motion folders besides the defaults
    robot_usd: str = ""  # robot USD for Isaac (local file or URL); empty = G1 from NVIDIA's asset library
    api_enabled: bool = True  # the window's local HTTP API for AI agents (127.0.0.1 + token, khumanoid/app/api_server.py)
    api_port: int = 8765


def settings_path() -> str:
    return os.path.join(paths.user_dir(), "settings.json")


_current: Settings | None = None


def load(reload: bool = False) -> Settings:
    """The saved settings (cached; defaults when there is no file or it is broken)."""
    global _current
    if _current is None or reload:
        s = Settings()
        try:
            with open(settings_path(), encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(Settings)}
            s = Settings(**{k: v for k, v in data.items() if k in names})
            s.library_dirs = [str(d) for d in (s.library_dirs or []) if str(d).strip()]
        except (OSError, ValueError, TypeError):
            pass
        _current = s
    return _current


def save(s: Settings) -> None:
    global _current
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    _current = s


@dataclass
class Found:
    """Where a tool was found: path (None when not found), how (setting / env var / auto),
    what it is (version, files), and what is wrong when the given place does not work."""
    path: str | None
    source: str = ""
    detail: str = ""
    problem: str = ""


# ------------------------------------------------------------------------------ Isaac Sim
def _isaac_launcher(p: str) -> str:
    """python.bat from a launcher path or an install folder."""
    return os.path.join(p, ISAAC_LAUNCHER) if os.path.isdir(p) else p


def _isaac_version(launcher: str) -> str:
    try:
        with open(os.path.join(os.path.dirname(launcher), "VERSION"), encoding="utf-8") as f:
            return f.readline().strip().split("+")[0]
    except OSError:
        return ""


def find_isaac(s: Settings | None = None) -> Found:
    s = s or load()
    for value, source in ((s.isaac_python, "설정"), (os.environ.get(ISAAC_ENV, ""), f"환경변수 {ISAAC_ENV}")):
        if value:
            p = _isaac_launcher(value)
            if os.path.isfile(p):
                v = _isaac_version(p)
                return Found(p, source, f"Isaac Sim {v}" if v else "")
            return Found(None, source, problem=f"{source}의 {value}에 {ISAAC_LAUNCHER}가 없습니다")
    if not paths.FROZEN and importlib.util.find_spec("isaacsim") is not None:
        return Found(sys.executable, "자동 (이 파이썬 환경)", "isaacsim 패키지")
    for d in ISAAC_DIRS:
        p = os.path.join(d, ISAAC_LAUNCHER)
        if os.path.isfile(p):
            v = _isaac_version(p)
            return Found(p, f"자동 ({d})", f"Isaac Sim {v}" if v else "")
    return Found(None, problem=f"Isaac Sim을 찾지 못했습니다 ({' / '.join(ISAAC_DIRS)}에 없음)")


# ------------------------------------------------------------------------------ Blender
def _blender_version(exe: str) -> str:
    m = re.search(r"blender-(\d+\.\d+(?:\.\d+)?)", exe.replace("\\", "/"), re.IGNORECASE)
    return f"Blender {m.group(1)}" if m else ""


def find_blender(s: Settings | None = None) -> Found:
    s = s or load()
    for value, source in ((s.blender, "설정"), (os.environ.get("BLENDER", ""), "환경변수 BLENDER")):
        if value:
            exe = os.path.join(value, "blender.exe") if os.path.isdir(value) else value
            if os.path.isfile(exe):
                return Found(exe, source, _blender_version(exe))
            return Found(None, source, problem=f"{source}의 {value}에 blender.exe가 없습니다")
    for exe in sorted(glob.glob(BLENDER_GLOB), reverse=True):
        if os.path.isfile(exe):
            return Found(exe, r"자동 (C:\blender)", _blender_version(exe))
    exe = shutil.which("blender")
    if exe:
        return Found(exe, "자동 (PATH)", _blender_version(exe))
    return Found(None, problem=r"Blender를 찾지 못했습니다 (C:\blender\*\blender.exe, PATH에 없음)")


# ------------------------------------------------------------------------------ SMPL-X
def _smpl_files(folder: str) -> list[str]:
    return [g for g in SMPLX_GENDERS if os.path.isfile(os.path.join(folder, "smplx", f"SMPLX_{g}.npz"))]


def find_smpl(s: Settings | None = None) -> Found:
    s = s or load()
    for value, source in ((s.smpl_model_dir, "설정"), (os.environ.get("SMPL_MODEL_DIR", ""), "환경변수 SMPL_MODEL_DIR"),
                          (paths.smpl_model_dir(), "기본 위치")):
        if not value:
            continue
        folder = os.path.dirname(value) if os.path.basename(os.path.normpath(value)).lower() == "smplx" else value
        have = _smpl_files(folder)
        if have:
            return Found(folder, source, "SMPLX " + ", ".join(have))
        if source != "기본 위치":
            return Found(None, source, problem=f"{source}의 {value}에 smplx/SMPLX_NEUTRAL.npz 등이 없습니다")
    return Found(None, problem=f"SMPL-X 모델이 없습니다 ({paths.smpl_model_dir()}\\smplx\\SMPLX_*.npz)")


# ------------------------------------------------------------------------------ robot USD
USD_EXT = (".usd", ".usda", ".usdc", ".usdz")


def find_robot_usd(s: Settings | None = None) -> Found:
    """The robot USD Isaac loads: a chosen local file / URL, or (empty) Unitree G1 from NVIDIA's
    asset library, which Isaac downloads on use (internet needed)."""
    s = s or load()
    v = s.robot_usd.strip().strip('"')
    if not v:
        return Found("", "기본 (NVIDIA 에셋 서버)", "Isaac Sim 에셋 라이브러리의 Unitree G1, 인터넷 필요")
    if "://" in v:
        return Found(v, "설정 (URL)", "Isaac이 이 주소에서 읽음")
    if os.path.isfile(v) and v.lower().endswith(USD_EXT):
        return Found(v, "설정 (로컬 파일)", "오프라인에서도 동작 (참조하는 파일도 함께 있어야 함)")
    return Found(None, "설정", problem=f"설정의 {v}가 USD 파일(.usd/.usda/.usdc/.usdz)이 아니거나 없습니다")


# ------------------------------------------------------------------------------ folders
def video_dir(s: Settings | None = None) -> str:
    s = s or load()
    return s.video_dir or paths.video_dir()


def library_dirs(s: Settings | None = None) -> list[str]:
    """The motion folders listed in the project panel: the defaults, then the user's."""
    s = s or load()
    out: list[str] = []
    for d in [*paths.library_roots(), *s.library_dirs]:
        d = os.path.abspath(d)
        if os.path.normcase(d) not in {os.path.normcase(x) for x in out}:
            out.append(d)
    return out


def _writable(folder: str) -> bool:
    """The folder, or the nearest folder above it that exists (it is made on first use), can be
    written to. Nothing is created here: the settings window checks paths while they are typed."""
    p = os.path.abspath(folder)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent
    return os.access(p, os.W_OK)


# ------------------------------------------------------------------------------ the check
@dataclass
class Check:
    key: str
    name: str
    ok: bool
    required: bool  # the program cannot run without it
    path: str = ""
    detail: str = ""
    needed_for: str = ""
    hint: str = ""
    url: str = ""


def check_all(s: Settings | None = None) -> list[Check]:
    """What each feature needs and whether it is there, for the settings window and startup."""
    s = s or load()
    out = []
    urdf = paths.robot_urdf()
    out.append(Check("robot", "로봇 모델 (Unitree G1)", os.path.isfile(urdf), True, urdf, "",
                     "모든 화면", "설치가 깨졌습니다. 프로그램을 다시 설치하세요" if paths.INSTALLED else
                     "저장소 옆에 GMR이 있어야 합니다 (scripts\\install_gmr.ps1)"))
    libs = [m for m in ("mink", "mujoco") if importlib.util.find_spec(m) is None]
    mjcf = os.path.join(paths.robot_assets_dir(), "unitree_g1", "g1_mocap_29dof.xml")
    gmr = not libs and os.path.isfile(mjcf)  # GMR's solver itself ships in khumanoid/gmr
    out.append(Check("gmr", "리타게팅 (GMR)", gmr, False, mjcf, "GMR(내장), mink, MuJoCo, G1 MJCF" if gmr else
                     (f"{', '.join(libs)} 없음" if libs else "G1 MJCF 없음"),
                     "사람 모션(BVH·FBX·SMPL-X·C3D) 열기", "" if gmr else
                     "설치가 깨졌습니다. 프로그램을 다시 설치하세요" if paths.INSTALLED else "scripts\\install_gmr.ps1을 실행하세요"))
    for key, name, found, needed_for, hint in (
            ("isaac", "Isaac Sim", find_isaac(s), "물리 모드, 동영상 저장",
             "NVIDIA Isaac Sim을 설치하고 설치 폴더(python.bat이 있는 곳)를 지정하세요. NVIDIA RTX GPU가 필요합니다"),
            ("blender", "Blender 4.5", find_blender(s), "FBX 파일 열기",
             "Blender 4.5 LTS를 설치(또는 압축 해제)하고 blender.exe를 지정하세요"),
            ("smpl", "SMPL-X 모델", find_smpl(s), "AMASS SMPL-X 파일 열기",
             "smpl-x.is.tue.mpg.de에서 등록 후 SMPL-X 모델(npz)을 받아, smplx\\SMPLX_NEUTRAL.npz가 들어 있는 폴더를 지정하세요")):
        detail = " · ".join(x for x in (found.detail, found.source) if x) if found.path else found.problem
        out.append(Check(key, name, found.path is not None, False, found.path or "", detail,
                         needed_for, "" if found.path else hint, URLS[key]))
    usd = find_robot_usd(s)
    out.append(Check("robot_usd", "로봇 USD (Isaac)", usd.path is not None, False, usd.path or "",
                     " · ".join(x for x in (usd.detail, usd.source) if x) if usd.path is not None else usd.problem,
                     "물리 모드, 동영상 저장", "" if usd.path is not None else
                     "USD 파일을 고르거나 칸을 비워 NVIDIA 에셋 서버의 G1을 쓰세요"))
    vd = video_dir(s)
    out.append(Check("video", "동영상 저장 폴더", _writable(vd), False, vd, "", "동영상 저장",
                     "쓸 수 있는 폴더를 지정하세요"))
    libs = library_dirs(s)
    have = [d for d in libs if os.path.isdir(d)]
    out.append(Check("library", "모션 폴더", bool(have), False, "; ".join(libs), f"{len(have)}/{len(libs)}개 있음",
                     "프로젝트 패널 목록", "" if have else "모션 파일이 있는 폴더를 추가하세요 (열기 메뉴로 아무 파일이나 열 수도 있음)"))
    return out
