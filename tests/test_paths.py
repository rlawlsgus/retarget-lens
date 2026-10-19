"""Program files vs user files (khumanoid/paths.py): the repository layout stays as it was, and
an installed build writes only to per-user folders."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import paths  # noqa: E402

REPO = paths.REPO_ROOT


def test_dev_layout_keeps_the_repository_folders():
    if paths.INSTALLED or any(os.environ.get(k) for k in ("KHUMANOID_USER_DIR", "KHUMANOID_DOCS_DIR",
                                                           "KHUMANOID_RESOURCE_DIR")):
        return  # this check is about a plain repository run
    j = lambda *p: os.path.join(REPO, *p)  # noqa: E731
    assert paths.cache_dir("retarget") == j("data", "cache", "retarget")
    assert paths.cache_dir("physics") == j("data", "cache", "physics")
    assert paths.uploads_dir() == j("data", "uploads")
    assert paths.video_dir() == j("reports", "videos", "viewer")
    assert paths.library_roots() == [j("data", "raw"), j("data", "samples"), j("data", "retargeted"), j("data", "uploads"),
                                     j("reports")]
    assert paths.robot_urdf() == os.path.join(os.path.dirname(REPO), "GMR", "assets", "unitree_g1",
                                              "g1_custom_collision_29dof.urdf")
    assert paths.isaac_replay_script() == j("tools", "isaac_replay.py") and paths.resource("configs") == j("configs")


def test_rel_never_raises():
    assert paths.rel(os.path.join(REPO, "data", "x.bvh"), REPO) == os.path.join("data", "x.bvh")
    other = ("Z:" if not REPO.upper().startswith("Z") else "Y:") + os.sep + os.path.join("elsewhere", "a.bvh")
    assert paths.rel(other, REPO) == os.path.abspath(other)  # another drive: relpath would raise on Windows
    assert paths.rel(os.path.join(os.path.dirname(REPO), "b.bvh"), REPO).endswith("b.bvh")  # outside: absolute


def test_installed_layout_writes_only_to_user_folders(tmp_path):
    local, docs, res = tmp_path / "local", tmp_path / "docs", tmp_path / "program"
    env = {k: v for k, v in os.environ.items() if k not in ("SMPL_MODEL_DIR", "KHUMANOID_USER_DIR")}
    env.update(KHUMANOID_LAYOUT="installed", LOCALAPPDATA=str(local), KHUMANOID_DOCS_DIR=str(docs),
               KHUMANOID_RESOURCE_DIR=str(res), PYTHONPATH=REPO)
    code = (
        "import json\n"
        "from khumanoid import paths, compare, physics_runner, cmu_labels\n"
        "from khumanoid.io import fbx\n"
        "from khumanoid.app import scene\n"
        "print(json.dumps({'layout': paths.LAYOUT, 'retarget': compare.CACHE, 'uploads': compare.UPLOADS,\n"
        "  'fbx': fbx.CACHE_DIR, 'physics': scene.PHYSICS_CACHE, 'videos': scene.VIDEO_DIR, 'logs': paths.logs_dir(),\n"
        "  'library': list(compare.LIBRARY_ROOTS), 'urdf': scene.DEFAULT_URDF, 'smpl': paths.smpl_model_dir(),\n"
        "  'labels': cmu_labels.METADATA, 'replay': physics_runner.REPLAY_SCRIPT, 'physics_cfg': physics_runner.PHYSICS_CONFIG,\n"
        "  'qc_cfg': physics_runner.QC_CONFIG, 'isaac_root': paths.isaac_root()}))\n")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    d = json.loads(out.stdout.strip().splitlines()[-1])
    user = os.path.join(str(local), "RetLens")
    assert d["layout"] == "installed"
    for k in ("retarget", "uploads", "fbx", "physics", "logs", "smpl"):  # written by the program: per-user folder
        assert d[k].startswith(user + os.sep), (k, d[k])
    assert d["videos"].startswith(str(docs) + os.sep)
    for k, v in d.items():  # nothing is written into the program folder or the repository
        if k in ("retarget", "uploads", "fbx", "physics", "logs", "videos"):
            assert not v.startswith(str(res)) and not v.startswith(REPO + os.sep), (k, v)
    assert d["library"] == [os.path.join(str(docs), "motions"), os.path.join(str(res), "samples"),
                            os.path.join(user, "uploads")]
    for k, parts in (("urdf", ("assets", "unitree_g1", "g1_custom_collision_29dof.urdf")),
                     ("labels", ("data", "cmu_metadata.csv")), ("replay", ("isaac", "tools", "isaac_replay.py")),
                     ("physics_cfg", ("configs", "physics.yaml")), ("qc_cfg", ("configs", "qc.yaml")),
                     ("isaac_root", ("isaac",))):
        assert d[k] == os.path.join(str(res), *parts), (k, d[k])  # read-only files shipped with the program
