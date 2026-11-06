"""The program's user settings (RetLens 환경 설정) and the check of what each feature needs.

Kept as JSON in the user data folder (paths.user_dir()/settings.json: data/settings.json in
the repository, %LOCALAPPDATA%\\RetLens\\settings.json when installed), so the editor, the
browser viewer and the command-line tools read the same values without Qt.

An empty value means "find it". Each external tool is looked up in this order:

    tool        setting          environment variable      usual places
    Isaac Sim   isaac_python     RETLENS_ISAAC_PYTHON    this Python when it can import isaacsim
                                                           (the dev env, never a packaged build), C:\\isaacsim
    Blender     blender          BLENDER                   C:\\blender\\*, <user data>\\tools\\blender-*,
                                                           Program Files\\Blender Foundation\\*, PATH
    SMPL-X      smpl_model_dir   SMPL_MODEL_DIR            paths.smpl_model_dir()
    GMT         gmt_dir          RETLENS_GMT_DIR         <user data>\\gmt, ..\\GMT next to the repository

The setup assistant (retlens/prereqs.py, 설치 도우미) installs into those usual places.
Standard library only (Isaac Sim's Python imports retlens too).
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shutil
import sys
import threading
from dataclasses import asdict, dataclass, field, fields

from . import paths

ISAAC_ENV = "RETLENS_ISAAC_PYTHON"
ISAAC_DIRS = [r"C:\isaacsim"] if os.name == "nt" else [os.path.expanduser("~/isaacsim")]
ISAAC_LAUNCHER = "python.bat" if os.name == "nt" else "python.sh"
BLENDER_GLOB = r"C:\blender\*\blender.exe"
BLENDER_VERSION = "4.5"  # the FBX reader is tested with Blender 4.5 LTS
TOOLS = "tools"  # <user data>\tools: programs the setup assistant unpacked (Blender)
GMT_INSTALL = "gmt"  # <user data>\gmt: GMT files the setup assistant downloaded
SMPLX_GENDERS = ("NEUTRAL", "MALE", "FEMALE")
GMT_ENV = "RETLENS_GMT_DIR"
GMT_MODEL = os.path.join("assets", "robots", "g1", "g1.xml")  # GMT's 23-DoF G1 (both MuJoCo controllers)
GMT_POLICY = os.path.join("assets", "pretrained_checkpoints", "pretrained.pt")  # the tracking policy
# the same G1 model staged into the program's resources (tools/stage_resources.py; meshes from assets/unitree_g1):
# the installed program has no GMT folder, but its "없음 (MuJoCo)" balance mode needs only this model
BUNDLED_G1_MODEL = ("assets", "gmt_g1", "g1.xml")
URLS = {"isaac": "https://docs.isaacsim.omniverse.nvidia.com/latest/installation/download.html",
        "blender": "https://www.blender.org/download/lts/4-5/",
        "smpl": "https://smpl-x.is.tue.mpg.de/",
        "gmt": "https://github.com/zixuan417/humanoid-general-motion-tracking"}


@dataclass
class Settings:
    isaac_python: str = ""  # python.bat of an Isaac Sim install (or its folder)
    blender: str = ""  # blender.exe (Blender 4.5 LTS)
    smpl_model_dir: str = ""  # folder holding smplx/SMPLX_*.npz
    video_dir: str = ""  # where 동영상 저장 writes
    library_dirs: list[str] = field(default_factory=list)  # motion folders besides the defaults
    robot_model: str = ""  # the robot: its MJCF / URDF (any humanoid, retlens.robot_profile); empty = Unitree G1
    robot_usd: str = ""  # robot USD for Isaac (local file or URL); empty = G1 from NVIDIA's asset library
    gmt_dir: str = ""  # GMT folder (assets\pretrained_checkpoints\pretrained.pt); empty = the usual places
    api_enabled: bool = True  # the window's local HTTP API for AI agents (127.0.0.1 + token, retlens/app/api_server.py)
    api_port: int = 8765
    label_rules: str = ""  # 자동 라벨 rule file (retlens.autolabel); empty = $RETLENS_LABEL_RULES
    check_updates: bool = True  # 시작할 때 업데이트 확인 (retlens.install, the packaged program only)


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
    data = {}
    try:  # keys this version does not know (a newer RetLens wrote them) are kept, not dropped
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict):
            data = {k: v for k, v in old.items() if k not in {fl.name for fl in fields(Settings)}}
    except (OSError, ValueError):
        pass
    data.update(asdict(s))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
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


def isaac_dirs() -> list[str]:
    """The usual install folders: C:\\isaacsim, then C:\\isaacsim-<version> (where the setup assistant
    installs when C:\\isaacsim is taken), newest first; never an unfinished unpack (.partial)."""
    out = []
    for d in ISAAC_DIRS:
        out.append(d)
        out += sorted((p for p in glob.glob(d + "-*") if os.path.isdir(p) and not p.endswith((".partial", ".old"))), reverse=True)
    return out


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
    for d in isaac_dirs():
        p = os.path.join(d, ISAAC_LAUNCHER)
        if os.path.isfile(p):
            v = _isaac_version(p)
            return Found(p, f"자동 ({d})", f"Isaac Sim {v}" if v else "")
    return Found(None, problem=f"Isaac Sim을 찾지 못했습니다 ({' / '.join(ISAAC_DIRS)}에 없음)")


# ------------------------------------------------------------------------------ Blender
def _blender_version(exe: str) -> str:
    """'Blender 4.5.14' from the folder name (portable zips: blender-4.5.14-windows-x64; the
    installer: Blender Foundation\\Blender 4.5), '' when the path does not say."""
    m = re.search(r"blender[- ](\d+\.\d+(?:\.\d+)?)", exe.replace("\\", "/"), re.IGNORECASE)
    return f"Blender {m.group(1)}" if m else ""


def _version_key(exe: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", _blender_version(exe))
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def blender_candidates() -> list[tuple[str, str]]:
    """(blender.exe, where) in the usual places, newest version first within each place."""
    pf = [os.environ.get(v) for v in ("ProgramFiles", "ProgramW6432")]
    places = [(BLENDER_GLOB, r"자동 (C:\blender)"),
              (os.path.join(paths.user_dir(), TOOLS, "blender-*", "blender.exe"), "자동 (설치 도우미)")]
    places += [(os.path.join(p, "Blender Foundation", "*", "blender.exe"), "자동 (Program Files)") for p in pf if p]
    out, seen = [], set()
    for pattern, where in places:
        for exe in sorted(glob.glob(pattern), key=_version_key, reverse=True):
            folder = os.path.basename(os.path.dirname(exe)).lower()
            if folder.endswith((".partial", ".old")):  # the setup assistant's unfinished unpack / replaced copy
                continue
            if os.path.isfile(exe) and os.path.normcase(exe) not in seen:
                seen.add(os.path.normcase(exe))
                out.append((exe, where))
    path = shutil.which("blender")
    if path and os.path.normcase(path) not in seen:
        out.append((path, "자동 (PATH)"))
    return out


def find_blender(s: Settings | None = None) -> Found:
    s = s or load()
    for value, source in ((s.blender, "설정"), (os.environ.get("BLENDER", ""), "환경변수 BLENDER")):
        if value:
            exe = os.path.join(value, "blender.exe") if os.path.isdir(value) else value
            if os.path.isfile(exe):
                return Found(exe, source, _blender_version(exe))
            return Found(None, source, problem=f"{source}의 {value}에 blender.exe가 없습니다")
    found = blender_candidates()  # a 4.5 first, wherever it is (PATH included)
    best = next((c for c in found if _blender_version(c[0]).startswith(f"Blender {BLENDER_VERSION}")), None)
    # then one whose path does not tell its version (a PATH shim, Steam's ...\common\Blender) - it may be a
    # 4.5 - before one whose path says it is another version
    best = best or next((c for c in found if not _blender_version(c[0])), None)
    if best or found:
        exe, where = best or found[0]
        return Found(exe, where, _blender_version(exe))
    return Found(None, problem=r"Blender를 찾지 못했습니다 (C:\blender, 설치 도우미 폴더, Program Files, PATH에 없음)")


# ------------------------------------------------------------------------------ SMPL-X
def _smpl_files(folder: str) -> list[str]:
    return [g for g in SMPLX_GENDERS if os.path.isfile(os.path.join(folder, "smplx", f"SMPLX_{g}.npz"))]


def smpl_root(value: str) -> str:
    """The model folder (the one holding smplx\\) for a path that may name the smplx folder itself."""
    p = os.path.normpath(value)
    return os.path.dirname(p) if os.path.basename(p).lower() == "smplx" else value


def find_smpl(s: Settings | None = None) -> Found:
    s = s or load()
    for value, source in ((s.smpl_model_dir, "설정"), (os.environ.get("SMPL_MODEL_DIR", ""), "환경변수 SMPL_MODEL_DIR"),
                          (paths.smpl_model_dir(), "기본 위치")):
        if not value:
            continue
        folder = smpl_root(value)
        have = _smpl_files(folder)
        if have:
            return Found(folder, source, "SMPLX " + ", ".join(have))
        if source != "기본 위치":
            return Found(None, source, problem=f"{source}의 {value}에 smplx/SMPLX_NEUTRAL.npz 등이 없습니다")
    return Found(None, problem=f"SMPL-X 모델이 없습니다 ({paths.smpl_model_dir()}\\smplx\\SMPLX_*.npz)")


# ------------------------------------------------------------------------------ GMT
def _gmt_place(s: Settings | None = None) -> tuple[str, str]:
    """(folder, how it was chosen): the setting, $RETLENS_GMT_DIR, <user data>\\gmt when the setup
    assistant put the policy there, else ..\\GMT next to the repository (scripts\\install_gmt.ps1)."""
    s = s or load()
    if s.gmt_dir:
        return s.gmt_dir, "설정"
    if os.environ.get(GMT_ENV):
        return os.environ[GMT_ENV], f"환경변수 {GMT_ENV}"
    own = os.path.join(paths.user_dir(), GMT_INSTALL)
    if os.path.isfile(os.path.join(own, GMT_POLICY)) and os.path.isfile(gmt_model(own)):
        return own, "자동 (설치 도우미)"
    return gmt_sibling(), SIBLING


SIBLING = "자동 (프로그램 옆)" if paths.INSTALLED else "자동 (저장소 옆)"


def gmt_sibling() -> str:
    """GMT next to the repository (..\\GMT, where scripts\\install_gmt.ps1 puts it) or next to the
    installed program's folder."""
    return os.path.join(os.path.dirname(paths.REPO_ROOT), "GMT")


def gmt_places(s: Settings | None = None) -> list[tuple[str, str]]:
    """Every place GMT is looked for, in order (the setup assistant falls back along them)."""
    s = s or load()
    out = [(s.gmt_dir, "설정"), (os.environ.get(GMT_ENV, ""), f"환경변수 {GMT_ENV}"),
           (os.path.join(paths.user_dir(), GMT_INSTALL), "자동 (설치 도우미)"),
           (gmt_sibling(), SIBLING)]
    return [(p, how) for p, how in out if p]


def gmt_dir(s: Settings | None = None) -> str:
    """Where GMT (General Motion Tracking) is looked for (_gmt_place)."""
    return _gmt_place(s)[0]


def gmt_model(folder: str) -> str:
    """GMT's G1 MuJoCo model: the GMT folder's, else the copy shipped in the program's resources
    when there is one (the folder's path otherwise, missing)."""
    own = os.path.join(folder, GMT_MODEL)
    bundled = bundled_gmt_model()
    return bundled if not os.path.isfile(own) and bundled else own


def bundled_gmt_model() -> str:
    """The G1 MuJoCo model shipped in the program's resources, '' when there is none (the repository)."""
    p = paths.resource(*BUNDLED_G1_MODEL)
    return p if os.path.isfile(p) else ""


def find_gmt(s: Settings | None = None) -> Found:
    """GMT's tracking policy (physics mode's 균형 제어 "추적 정책 (GMT)") and the G1 MuJoCo model
    (also "없음 (MuJoCo)"). Found when the policy is there; the model may be the program's own copy."""
    folder, source = _gmt_place(s)
    policy = os.path.join(folder, GMT_POLICY)
    model = os.path.isfile(gmt_model(folder))
    if not os.path.isfile(policy):
        return Found(None, source, problem=f"GMT 추적 정책이 없습니다 ({policy})" +
                     ("" if model else ", G1 MuJoCo 모델도 없음"))
    if not model:
        return Found(None, source, problem=f"G1 MuJoCo 모델이 없습니다 ({os.path.join(folder, GMT_MODEL)})")
    try:  # a policy file this program cannot run (another network) is no policy for it
        from .gmt_policy import problem as policy_problem

        bad = policy_problem(policy)
    except ImportError:  # numpy missing (only in a bare Python): leave the check to the run
        bad = ""
    if bad:
        return Found(None, source, problem=bad)
    return Found(folder, source, "추적 정책, G1 MuJoCo 모델" +
                 ("" if os.path.isfile(os.path.join(folder, GMT_MODEL)) else " (프로그램에 들어 있는 것)"))


# ------------------------------------------------------------------------------ the robot
ROBOT_EXT = (".xml", ".urdf")


def robot_spec(s: Settings | None = None) -> str:
    """The robot to retarget to and show: the chosen MJCF / URDF, else the built-in Unitree G1."""
    s = s or load()
    return s.robot_model.strip().strip('"') or "unitree_g1"


def find_robot(s: Settings | None = None) -> Found:
    """The robot model in use and whether its legs, arms and feet can be found in it."""
    s = s or load()
    spec = robot_spec(s)
    try:
        from .robot_profile import RobotError, load as load_robot

        prof = load_robot(spec)
    except Exception as e:  # RobotError (no file, wrong type) or an import problem
        return Found(None, "설정", problem=str(e))
    source = "기본" if prof.builtin else "설정"
    if importlib.util.find_spec("mujoco") is None:  # the parts need MuJoCo: report the file only
        return Found(prof.mjcf, source, prof.name)
    try:
        parts = prof.parts
    except RobotError as e:
        return Found(None, source, problem=f"{prof.name}: {e}")
    except Exception as e:  # MuJoCo cannot compile it
        return Found(None, source, problem=f"{prof.name}: MuJoCo가 읽지 못함 ({type(e).__name__}: {e})")
    return Found(prof.mjcf, source, f"{prof.name}, {prof.model().nq - 7} DoF, 키 {parts.top_height:.2f} m")


# ------------------------------------------------------------------------------ robot USD
USD_EXT = (".usd", ".usda", ".usdc", ".usdz")


def find_robot_usd(s: Settings | None = None) -> Found:
    """The robot USD Isaac loads: a chosen local file / URL, or (empty) Unitree G1 from NVIDIA's
    asset library, which Isaac downloads on use (internet needed)."""
    s = s or load()
    v = s.robot_usd.strip().strip('"')
    if not v:
        if robot_spec(s) != "unitree_g1":  # NVIDIA's G1 would replay another robot's motions
            return Found(None, "설정", problem="G1이 아닌 로봇은 그 로봇의 USD를 골라야 Isaac에서 돌릴 수 있습니다")
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
    written to - tried for real: on Windows os.access says yes to every folder, whatever its
    permissions. A test file (or, above a folder still to be made, a test folder) is made and
    removed at once; the folder itself is not created (the settings window checks while typing)."""
    p = os.path.abspath(folder)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent
    probe = os.path.join(p, f".retlens-write-test-{os.getpid()}-{threading.get_ident()}")
    try:
        if os.path.normcase(p) == os.path.normcase(os.path.abspath(folder)):  # it exists: a file goes in it
            with open(probe, "wb"):
                pass
            os.remove(probe)
        else:  # it would be made under p: a folder must be allowed there
            os.mkdir(probe)
            os.rmdir(probe)
        return True
    except OSError:
        return False


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
    robot = find_robot(s)
    custom = robot_spec(s) != "unitree_g1"
    out.append(Check("robot", "로봇 모델", robot.path is not None, True, robot.path or "",
                     " · ".join(x for x in (robot.detail, robot.source) if x) if robot.path else robot.problem,
                     "모든 화면", "" if robot.path else
                     "환경 설정의 로봇 모델에서 MJCF(.xml) / URDF(.urdf)를 다시 고르거나 칸을 비워 G1을 쓰세요" if custom else
                     "설치가 깨졌습니다. 프로그램을 다시 설치하세요" if paths.INSTALLED else
                     "저장소 옆에 GMR이 있어야 합니다 (scripts\\install_gmr.ps1)"))
    libs = [m for m in ("mink", "mujoco") if importlib.util.find_spec(m) is None]
    gmr = not libs and robot.path is not None  # GMR's solver itself ships in retlens/gmr
    out.append(Check("gmr", "리타게팅 (GMR)", gmr, False, robot.path or "", "GMR(내장), mink, MuJoCo, 로봇 모델" if gmr else
                     (f"{', '.join(libs)} 없음" if libs else "로봇 모델 없음"),
                     "사람 모션(BVH·FBX·SMPL-X·C3D) 열기", "" if gmr else
                     "로봇 모델을 확인하세요" if custom else
                     "설치가 깨졌습니다. 프로그램을 다시 설치하세요" if paths.INSTALLED else "scripts\\install_gmr.ps1을 실행하세요"))
    for key, name, found, needed_for, hint in (
            ("isaac", "Isaac Sim", find_isaac(s), "물리 모드 '보조 힘 (Isaac)', 동영상 저장",
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
                     "물리 모드 '보조 힘 (Isaac)', 동영상 저장", "" if usd.path is not None else
                     "이 로봇의 USD 파일을 고르세요" if custom else
                     "USD 파일을 고르거나 칸을 비워 NVIDIA 에셋 서버의 G1을 쓰세요"))
    gmt = find_gmt(s)  # the policy runs in numpy (retlens/gmt_policy.py): no PyTorch needed
    mujoco = importlib.util.find_spec("mujoco") is not None
    ok = gmt.path is not None and mujoco
    detail = ("mujoco 없음" if not mujoco else " · ".join(x for x in (gmt.detail, gmt.source) if x)) \
        if gmt.path else gmt.problem
    out.append(Check("gmt", "추적 정책 (GMT)", ok, False, gmt.path or "", detail, "물리 모드 균형 제어: 추적 정책 (GMT)",
                     "" if ok else "설치 도우미에서 받으세요(연구용 라이선스 동의 필요)" + (
                         "" if paths.INSTALLED else ", 또는 scripts\\install_gmt.ps1"), URLS["gmt"]))
    vd = video_dir(s)
    out.append(Check("video", "동영상 저장 폴더", _writable(vd), False, vd, "", "동영상 저장",
                     "쓸 수 있는 폴더를 지정하세요"))
    libs = library_dirs(s)
    have = [d for d in libs if os.path.isdir(d)]
    out.append(Check("library", "모션 폴더", bool(have), False, "; ".join(libs), f"{len(have)}/{len(libs)}개 있음",
                     "프로젝트 패널 목록", "" if have else "모션 파일이 있는 폴더를 추가하세요 (열기 메뉴로 아무 파일이나 열 수도 있음)"))
    rules = s.label_rules or os.environ.get("RETLENS_LABEL_RULES", "")  # = retlens.autolabel.ENV
    if rules:  # only once one is set: a rule file that was moved or deleted since
        ok = os.path.isfile(rules)
        out.append(Check("label_rules", "자동 라벨 규칙 파일", ok, False, rules, "" if ok else "파일이 없습니다",
                         "자동 라벨", "" if ok else "인스펙터 > 라벨 > 규칙 파일...에서 다시 고르세요"))
    return out
