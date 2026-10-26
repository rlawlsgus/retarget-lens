# PyInstaller spec of RetLens: a windowed one-folder build, dist\RetLens\RetLens.exe.
# Build with scripts\build_retlens.ps1 (stages the resources first).
#
# Layout (retlens.paths, "installed"): everything below lands in dist\RetLens\_internal
# (sys._MEIPASS = the resource folder):
#   configs/ assets/ data/ docs/ isaac/ licenses/ [samples/]   staged by tools/stage_resources.py
#   retlens/io/blender_fbx_script.py, cmu_frame_rates.json      read next to their modules
#   retlens/gmr/ik_configs/*.json                               vendored GMR IK configs
#   viser/client/build/                                           the 3D view's web client
# Left out: torch, smplx and GMR's own package (development only), Isaac Sim (installed by
# the user), licence-gated data (never staged).

import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is set by PyInstaller)
RES = os.environ.get("RETLENS_RESOURCES", os.path.join(ROOT, "build", "resources"))
if not os.path.isfile(os.path.join(RES, "assets", "unitree_g1", "g1_mocap_29dof.xml")):
    raise SystemExit(f"stage the resources first: python tools/stage_resources.py {RES}")

datas = []
for d, _dirs, files in os.walk(RES):  # the staged resource folder becomes the bundle's top
    rel = os.path.relpath(d, RES)
    datas += [(os.path.join(d, f), "." if rel == "." else rel) for f in files]
datas += [(os.path.join(ROOT, "retlens", "io", f), "retlens/io")
          for f in ("blender_fbx_script.py", "cmu_frame_rates.json")]
datas += [(p, "retlens/gmr/ik_configs") for p in glob.glob(os.path.join(ROOT, "retlens", "gmr", "ik_configs", "*.json"))]
datas += [(os.path.join(ROOT, "retlens", "gmr", "LICENSE"), "retlens/gmr")]
datas += [(os.path.join(ROOT, "retlens", "app", "icon.png"), "retlens/app")]  # window icon (tools/make_icon.py)
# viser's prebuilt web client only: with client/src present, viser would try to rebuild it with Node
datas += collect_data_files("viser", includes=["client/build/**"])
datas += collect_data_files("trimesh")

hiddenimports = ["daqp"] + collect_submodules("qpsolvers.solvers")  # qpsolvers finds solvers by trying imports

# QtWebEngineProcess.exe also next to the Qt DLLs (the bundle's top): there the sandboxed renderer
# finds them (retlens.app.editor.webengine_sandbox_workaround points Qt at this copy)
from PySide6.QtCore import QLibraryInfo  # noqa: E402

binaries = [(os.path.join(QLibraryInfo.path(QLibraryInfo.LibraryExecutablesPath), "QtWebEngineProcess.exe"), ".")]

excludes = [
    "torch", "smplx", "general_motion_retargeting",  # development-only paths
    "isaacsim", "omni", "carb", "pxr",  # Isaac Sim runs as its own program
    # GMR solves with daqp; the other QP solvers in the env are left out (osqp's native backend is
    # not picked up, and its import then fails with a RuntimeError that stops mink loading)
    "osqp", "proxsuite", "scs",
    "cv2", "OpenGL", "cryptography",  # optional: viser falls back to imageio; mujoco EGL/OSMesa; pyopenssl
    "tkinter", "matplotlib", "pandas", "plotly", "IPython", "jupyter", "notebook", "pytest",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "retlens_main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RetLens",
    console=False,  # a window program: output goes to the log file (retlens.app.runtime)
    icon=os.path.join(ROOT, "packaging", "retlens.ico"),  # from packaging/retlens_icon.svg (tools/make_icon.py)
    disable_windowed_traceback=False,
    upx=False,
)

# retlens-cli.exe: the same program without a window, for scripts and AI agents (JSON on stdout)
cli = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "retlens_cli_main.py")],
    pathex=[ROOT, os.path.join(ROOT, "tools")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    [],
    exclude_binaries=True,
    name="retlens-cli",
    console=True,
    icon=os.path.join(ROOT, "packaging", "retlens.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, cli_exe, cli.binaries, cli.datas, name="RetLens", upx=False)  # noqa: F821
