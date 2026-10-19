"""Lay out the read-only resources of an installed RetLens (khumanoid.paths, layout "installed").

    python tools/stage_resources.py build/resources            # what the program needs
    python tools/stage_resources.py build/resources --samples  # + CMU sample motions (redistributable)

The packaging step bundles this folder as the program's resource folder (PyInstaller's
_MEIPASS). To try an installed layout from the repository without packaging:

    set KHUMANOID_LAYOUT=installed
    set KHUMANOID_RESOURCE_DIR=build\\resources
    python tools\\editor.py

Contents (see docs/packaging.md):
    configs/            physics.yaml, qc.yaml
    assets/unitree_g1/  G1 URDF (display), MJCF (retargeting), meshes, LICENSE (BSD-3, Unitree)
    data/               cmu_metadata.csv (CMU motion descriptions)
    docs/               the documents (도움말 > 사용 안내 opens retlens.md), docs/research/
    ai/retlens/         SKILL.md, the guide for AI agents (retlens-cli, the local HTTP API)
    isaac/              khumanoid/ and tools/isaac_replay.py as plain files for Isaac Sim's Python
    licenses/           third-party licence texts of what is bundled here
    samples/            (--samples) CMU BVH / C3D samples; CMU data may be redistributed
Licence-gated data (SMPL-X models, AMASS, LAFAN1) is never staged.
"""

import argparse
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from khumanoid import paths  # noqa: E402

ROBOT = "unitree_g1"
ROBOT_FILES = ("g1_custom_collision_29dof.urdf", "g1_mocap_29dof.xml", "g1_mocap_29dof_with_hands.xml", "LICENSE",
               "README.md")
SAMPLES = ("data/raw/cmu_bvh", "data/raw/cmu_c3d")  # CMU only: free to redistribute (not to sell)


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


def stage(out: str, samples: bool = False, assets_from: str | None = None) -> list[str]:
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
    # the help menu opens docs/retlens.md, which links to the other documents (not docs/internal/)
    for sub in ("", "research"):
        d = os.path.join(ROOT, "docs", sub)
        for doc in sorted(os.listdir(d)):
            if doc.endswith(".md"):
                _copy(os.path.join(d, doc), os.path.join(out, "docs", sub, doc), done)
    # Isaac Sim's own Python runs isaac_replay.py: plain sources (the program's copy is inside an archive)
    _copy_tree(os.path.join(ROOT, "khumanoid"), os.path.join(out, "isaac", "khumanoid"), done,
               keep=lambda f: f.endswith((".py", ".json")) or f == "LICENSE")
    _copy(os.path.join(ROOT, "tools", "isaac_replay.py"), os.path.join(out, "isaac", "tools", "isaac_replay.py"), done)
    lic = os.path.join(out, "licenses")
    _copy(os.path.join(ROOT, "khumanoid", "gmr", "LICENSE"), os.path.join(lic, "GMR-LICENSE.txt"), done)
    _copy(os.path.join(src, "LICENSE"), os.path.join(lic, "Unitree-G1-description-LICENSE.txt"), done)
    if samples:
        for rel in SAMPLES:
            d = os.path.join(ROOT, *rel.split("/"))
            if os.path.isdir(d):
                _copy_tree(d, os.path.join(out, "samples", os.path.basename(d)), done)
    return done


def check(out: str) -> list[str]:
    """What an installed layout over `out` would miss (empty = complete)."""
    env = {"KHUMANOID_LAYOUT": "installed", "KHUMANOID_RESOURCE_DIR": out}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        need = [paths.robot_urdf(), os.path.join(paths.robot_assets_dir(), ROBOT, "g1_mocap_29dof.xml"),
                paths.resource("configs", "physics.yaml"), paths.resource("configs", "qc.yaml"),
                paths.isaac_replay_script(), os.path.join(paths.isaac_root(), "khumanoid", "gmr", "motion_retarget.py")]
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
    return [p for p in need if not os.path.isfile(p)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="folder to (re)create")
    ap.add_argument("--samples", action="store_true", help="also copy the CMU sample motions (BVH, C3D)")
    ap.add_argument("--assets", default=None, help="GMR assets folder (default: ..\\GMR\\assets)")
    args = ap.parse_args()
    files = stage(args.out, args.samples, args.assets)
    size = sum(os.path.getsize(f) for f in files)
    print(f"staged {len(files)} files, {size / 1e6:.1f} MB -> {os.path.abspath(args.out)}")
    missing = check(os.path.abspath(args.out))
    print("complete" if not missing else "MISSING: " + ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
