"""Lay out the read-only resources of an installed RetLens (retlens.paths, layout "installed").

    python tools/stage_resources.py build/resources            # what the program needs
    python tools/stage_resources.py build/resources --samples  # + CMU sample motions (redistributable)

The packaging step bundles this folder as the program's resource folder (PyInstaller's
_MEIPASS). To try an installed layout from the repository without packaging:

    set RETLENS_LAYOUT=installed
    set RETLENS_RESOURCE_DIR=build\\resources
    python tools\\editor.py

Contents:
    configs/            physics.yaml, qc.yaml
    assets/unitree_g1/  G1 URDF (display), MJCF (retargeting), meshes, LICENSE (BSD-3, Unitree)
    assets/gmt_g1/      g1.xml: GMT's 23-DoF G1 MuJoCo model on those meshes (physics mode "없음 (MuJoCo)"),
                        when GMT is installed (scripts\\install_gmt.ps1); its tracking policy is not staged
    data/            cmu_metadata.csv (CMU motion descriptions)
    docs/               manual.md (도움말 > 사용 설명서), cmu_motion_labels.md, images/
    ai/retlens/         SKILL.md, the guide for AI agents (retlens-cli, the local HTTP API)
    isaac/              retlens/ and tools/isaac_replay.py as plain files for Isaac Sim's Python
    licenses/           third-party licence texts of what is bundled here
    samples/            (--samples) CMU BVH / C3D samples; CMU data may be redistributed
Licence-gated data (SMPL-X models, AMASS, LAFAN1) is never staged.
"""

import argparse
import filecmp
import os
import re
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens import paths  # noqa: E402

ROBOT = "unitree_g1"
ROBOT_FILES = ("g1_custom_collision_29dof.urdf", "g1_mocap_29dof.xml", "g1_mocap_29dof_with_hands.xml", "LICENSE",
               "README.md")
SAMPLES = ("data/raw/cmu_bvh", "data/raw/cmu_c3d")  # CMU only: free to redistribute (not to sell)
DOCS = ("manual.md", "cmu_motion_labels.md")  # 도움말 > 사용 설명서, CMU 동작 목록
BUNDLED_MODEL = ("assets", "gmt_g1", "g1.xml")  # = retlens.settings.BUNDLED_G1_MODEL


def _copy(src: str, dst: str, done: list) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    done.append(dst)


def _copy_tree(src: str, dst: str, done: list, keep=lambda name: True) -> None:
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if keep(f):
                _copy(os.path.join(d, f), os.path.join(dst, os.path.relpath(os.path.join(d, f), src)), done)


def _stage_g1_mujoco(out: str, gmt_from: str | None, done: list) -> bool:
    """GMT's 23-DoF G1 MuJoCo model (Apache-2.0, from Unitree's BSD-3 description) for the "없음 (MuJoCo)"
    balance mode, pointed at the G1 meshes staged above. Its meshes are byte-identical to GMR's; when a
    mesh is missing or differs the model is left out (the mode then says why). The tracking policy is
    not staged: the installed program has no PyTorch, and GMT gives the model for research use only."""
    from retlens import settings

    root = gmt_from or settings.gmt_dir()
    xml = os.path.join(root, settings.GMT_MODEL)
    if not os.path.isfile(xml):
        print(f"note: GMT not found ({xml}): the installed program's MuJoCo balance mode stays off")
        return False
    with open(xml, encoding="utf-8") as f:
        text = f.read()
    meshes = os.path.join(out, "assets", ROBOT, "meshes")
    for name in sorted(set(re.findall(r'file="([^"]+)"', text))):
        a, b = os.path.join(os.path.dirname(xml), "meshes", name), os.path.join(meshes, name)
        if not (os.path.isfile(b) and filecmp.cmp(a, b, shallow=False)):
            print(f"note: GMT's mesh {name} is not among the staged G1 meshes: MuJoCo balance mode left out")
            return False
    text, n = re.subn(r'meshdir="meshes"', f'meshdir="../{ROBOT}/meshes"', text)
    if n != 1:
        print("note: unexpected meshdir in GMT's g1.xml: MuJoCo balance mode left out")
        return False
    dst = os.path.join(out, *BUNDLED_MODEL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    done.append(dst)
    _copy(os.path.join(root, "LICENSE"), os.path.join(out, "licenses", "GMT-LICENSE.txt"), done)
    return True


def stage(out: str, samples: bool = False, assets_from: str | None = None, gmt_from: str | None = None) -> list[str]:
    """Copy the resources into `out` (made fresh); returns the files written."""
    out = os.path.abspath(out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    done: list[str] = []
    for name in ("physics.yaml", "qc.yaml"):
        _copy(os.path.join(ROOT, "configs", name), os.path.join(out, "configs", name), done)
    src = os.path.join(assets_from or os.path.join(os.path.dirname(ROOT), "GMR", "assets"), ROBOT)
    missing = [f for f in ROBOT_FILES if not os.path.isfile(os.path.join(src, f))]
    if missing or not os.path.isdir(os.path.join(src, "meshes")):
        raise FileNotFoundError(f"robot assets incomplete in {src} (missing {missing or 'meshes/'}); "
                                "run scripts\\install_gmr.ps1 or pass --assets")
    for f in ROBOT_FILES:
        _copy(os.path.join(src, f), os.path.join(out, "assets", ROBOT, f), done)
    _copy_tree(os.path.join(src, "meshes"), os.path.join(out, "assets", ROBOT, "meshes"), done)
    meta = os.path.join(ROOT, "data", "raw", "cmu_fbx", "metadata.csv")
    if os.path.isfile(meta):
        _copy(meta, os.path.join(out, "data", "cmu_metadata.csv"), done)
    # the guide for AI agents (Claude Code skill): RetLens > 환경 설정 > AI 연동 installs it
    _copy(os.path.join(ROOT, ".claude", "skills", "retlens", "SKILL.md"), os.path.join(out, "ai", "retlens", "SKILL.md"), done)
    # the help menu's documents, and the pictures the manual shows (not the README-only ones)
    docs = os.path.join(ROOT, "docs")
    for doc in DOCS:
        _copy(os.path.join(docs, doc), os.path.join(out, "docs", doc), done)
    with open(os.path.join(docs, "manual.md"), encoding="utf-8") as f:
        pictures = sorted(set(re.findall(r"images/([\w.-]+\.(?:png|gif))", f.read())))
    for name in pictures:
        _copy(os.path.join(docs, "images", name), os.path.join(out, "docs", "images", name), done)
    # Isaac Sim's own Python runs isaac_replay.py: plain sources (the program's copy is inside an archive)
    _copy_tree(os.path.join(ROOT, "retlens"), os.path.join(out, "isaac", "retlens"), done,
               keep=lambda f: f.endswith((".py", ".json")) or f == "LICENSE")
    _copy(os.path.join(ROOT, "tools", "isaac_replay.py"), os.path.join(out, "isaac", "tools", "isaac_replay.py"), done)
    lic = os.path.join(out, "licenses")
    _copy(os.path.join(ROOT, "retlens", "gmr", "LICENSE"), os.path.join(lic, "GMR-LICENSE.txt"), done)
    _copy(os.path.join(src, "LICENSE"), os.path.join(lic, "Unitree-G1-description-LICENSE.txt"), done)
    _stage_g1_mujoco(out, gmt_from, done)
    if samples:
        bvh_dir = os.path.join(ROOT, "data", "raw", "cmu_bvh")
        takes = {os.path.splitext(f)[0] for f in os.listdir(bvh_dir)} if os.path.isdir(bvh_dir) else set()
        for rel in SAMPLES:
            d = os.path.join(ROOT, *rel.split("/"))
            if os.path.isdir(d):  # a C3D opens with its take's BVH (markers next to its retarget): ship pairs only
                _copy_tree(d, os.path.join(out, "samples", os.path.basename(d)), done,
                           keep=lambda f: not f.lower().endswith(".c3d") or os.path.splitext(f)[0] in takes)
    return done


def check(out: str) -> list[str]:
    """What an installed layout over `out` would miss (empty = complete)."""
    env = {"RETLENS_LAYOUT": "installed", "RETLENS_RESOURCE_DIR": out}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        need = [paths.robot_urdf(), os.path.join(paths.robot_assets_dir(), ROBOT, "g1_mocap_29dof.xml"),
                paths.resource("configs", "physics.yaml"), paths.resource("configs", "qc.yaml"),
                paths.isaac_replay_script(), os.path.join(paths.isaac_root(), "retlens", "gmr", "motion_retarget.py")]
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
    return [p for p in need if not os.path.isfile(p)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="folder to (re)create")
    ap.add_argument("--samples", action="store_true", help="also copy the CMU sample motions (BVH, C3D)")
    ap.add_argument("--assets", default=None, help="GMR assets folder (default: ..\\GMR\\assets)")
    ap.add_argument("--gmt", default=None, help="GMT folder for its G1 MuJoCo model (default: ..\\GMT or RETLENS_GMT_DIR)")
    args = ap.parse_args()
    files = stage(args.out, args.samples, args.assets, args.gmt)
    size = sum(os.path.getsize(f) for f in files)
    print(f"staged {len(files)} files, {size / 1e6:.1f} MB -> {os.path.abspath(args.out)}")
    missing = check(os.path.abspath(args.out))
    print("complete" if not missing else "MISSING: " + ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
