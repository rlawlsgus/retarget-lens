"""Where RetLens reads the files it ships with and writes the user's files.

Two layouts, chosen once per process:

``dev`` (running from this repository; the default when not frozen)
    Everything stays where it always was: caches in data/cache/, videos in
    reports/videos/viewer/, motion folders data/raw, data/samples, ..., the robot model in
    the GMR checkout next to the repository (..\\GMR), SMPL-X models in models/.

``installed`` (a packaged build: sys.frozen, or RETLENS_LAYOUT=installed)
    Program files are read-only (C:\\Program Files\\RetLens), so the program writes only
    to per-user folders:

    - resources (read only): the bundle folder (PyInstaller's sys._MEIPASS)
        configs/physics.yaml, configs/qc.yaml, assets/unitree_g1/ (robot model),
        data/cmu_metadata.csv (CMU motion labels), docs/ (help menu), samples/,
        isaac/ (retlens/ and tools/isaac_replay.py as plain files for Isaac's Python)
    - user data: %LOCALAPPDATA%\\RetLens  (cache/retarget, cache/fbx, cache/physics,
        uploads/, logs/, models/ for the SMPL-X body model)
    - documents: Documents\\RetLens  (videos/, motions/)

Overrides (both layouts): RETLENS_RESOURCE_DIR, RETLENS_USER_DIR, RETLENS_DOCS_DIR,
SMPL_MODEL_DIR. Pure standard library: Isaac Sim's Python imports retlens too.
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APP_NAME = "RetLens"
ROBOT_URDF_NAME = os.path.join("unitree_g1", "g1_custom_collision_29dof.urdf")
FROZEN = bool(getattr(sys, "frozen", False))
LAYOUT = "installed" if FROZEN or os.environ.get("RETLENS_LAYOUT", "").lower() == "installed" else "dev"
INSTALLED = LAYOUT == "installed"


def _documents() -> str:
    """The user's Documents folder (its real place when Windows moved it, e.g. to OneDrive)."""
    if os.name == "nt":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                            ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")  # FOLDERID_Documents
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def resource_dir() -> str:
    """Read-only files shipped with the program."""
    env = os.environ.get("RETLENS_RESOURCE_DIR")
    if env:
        return os.path.abspath(env)
    if FROZEN:
        return os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return REPO_ROOT


def resource(*parts: str) -> str:
    return os.path.join(resource_dir(), *parts)


def user_dir() -> str:
    """Per-user writable data (caches, uploads, logs)."""
    env = os.environ.get("RETLENS_USER_DIR")
    if env:
        return os.path.abspath(env)
    if not INSTALLED:
        return os.path.join(REPO_ROOT, "data")
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, APP_NAME)


def documents_dir() -> str:
    """Where files the user keeps go (videos, their motion files)."""
    env = os.environ.get("RETLENS_DOCS_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.join(REPO_ROOT, "reports") if not INSTALLED else os.path.join(_documents(), APP_NAME)


def cache_dir(kind: str) -> str:
    """retarget | fbx | physics | policy. Not under data/retargeted in the repository: QC reports scan that."""
    return os.path.join(user_dir(), "cache", kind)


def uploads_dir() -> str:
    return os.path.join(user_dir(), "uploads")


def logs_dir() -> str:
    return os.path.join(user_dir(), "logs")


def video_dir() -> str:
    return os.path.join(documents_dir(), "videos", "viewer") if not INSTALLED else os.path.join(documents_dir(), "videos")


def library_roots() -> list[str]:
    """Folders listed in the motion picker (the project panel), absolute."""
    if not INSTALLED:
        return [os.path.join(REPO_ROOT, *p.split("/")) for p in
                ("data/raw", "data/samples", "data/retargeted", "data/uploads", "reports")]
    return [os.path.join(documents_dir(), "motions"), resource("samples"), uploads_dir()]


def robot_assets_dir() -> str:
    """Robot models and meshes (GMR's assets/: unitree_g1/ with the URDF the viewers draw and the
    MJCF retargeting solves on). Dev: the GMR checkout next to the repository; installed: the
    program's assets/ folder."""
    if not INSTALLED and not os.environ.get("RETLENS_RESOURCE_DIR"):
        return os.path.join(os.path.dirname(REPO_ROOT), "GMR", "assets")
    return resource("assets")


def robot_urdf() -> str:
    """The robot model shown in the viewers (Unitree G1 from GMR's assets)."""
    return os.path.join(robot_assets_dir(), ROBOT_URDF_NAME)


def smpl_model_dir() -> str:
    """Folder holding smplx/SMPLX_*.npz (licence-gated: each user downloads it)."""
    return os.environ.get("SMPL_MODEL_DIR") or default_smpl_model_dir()


def default_smpl_model_dir() -> str:
    """Where SMPL-X models go without SMPL_MODEL_DIR: models\\ in the repository, <user data>\\models installed."""
    return os.path.join(REPO_ROOT, "models") if not INSTALLED else os.path.join(user_dir(), "models")


def cmu_metadata() -> str:
    """CMU trial descriptions (data/raw/cmu_fbx/metadata.csv in the repository)."""
    if not INSTALLED:
        return os.path.join(REPO_ROOT, "data", "raw", "cmu_fbx", "metadata.csv")
    return resource("data", "cmu_metadata.csv")


def doc(*parts: str) -> str:
    """docs/manual.md, docs/cmu_motion_labels.md (the repository's docs/ in dev)."""
    return resource(*parts)


def isaac_root() -> str:
    """Folder Isaac Sim's Python runs tools/isaac_replay.py from: it holds retlens/ and tools/
    as plain files (the packaged program's own copy is inside an archive Isaac cannot import)."""
    return REPO_ROOT if not INSTALLED else resource("isaac")


def isaac_replay_script() -> str:
    return os.path.join(isaac_root(), "tools", "isaac_replay.py")


def rel(path: str, base: str | None = None) -> str:
    """Path relative to `base` when inside it, else absolute. Without a base: relative to the
    repository in the dev layout, absolute when installed. Never raises (relpath fails across
    Windows drives)."""
    p = os.path.abspath(path)
    if base is None:
        if INSTALLED:
            return p
        base = REPO_ROOT
    try:
        r = os.path.relpath(p, base)
    except ValueError:
        return p
    return p if r.startswith("..") else r


def describe() -> list[tuple[str, str]]:
    """(name, path) of every location, for the about box / logs / tests."""
    return [("배치", LAYOUT), ("프로그램 파일", resource_dir()), ("사용자 데이터", user_dir()),
            ("문서", documents_dir()), ("리타겟 캐시", cache_dir("retarget")), ("물리 캐시", cache_dir("physics")),
            ("MuJoCo 캐시", cache_dir("policy")),
            ("FBX 캐시", cache_dir("fbx")), ("동영상", video_dir()), ("로봇 모델", robot_urdf()),
            ("SMPL-X 모델", smpl_model_dir()), ("Isaac 실행 폴더", isaac_root()),
            ("모션 폴더", "; ".join(library_roots()))]
