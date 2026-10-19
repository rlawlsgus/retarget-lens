"""환경 설정 (khumanoid/settings.py): saved values, finding Isaac Sim / Blender / SMPL-X, the check."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import paths, settings  # noqa: E402
from khumanoid.physics_runner import isaac_command  # noqa: E402


@pytest.fixture
def user(tmp_path, monkeypatch):
    """Settings in a temporary user folder, no tool environment variables."""
    monkeypatch.setenv("KHUMANOID_USER_DIR", str(tmp_path / "user"))
    for k in (settings.ISAAC_ENV, "BLENDER", "SMPL_MODEL_DIR"):
        monkeypatch.delenv(k, raising=False)
    settings.load(reload=True)
    yield tmp_path
    settings.load(reload=True)


def _file(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def test_save_and_load(user):
    assert settings.load() == settings.Settings()  # no file yet
    s = settings.Settings(blender="C:/b/blender.exe", library_dirs=["D:/motions", "  "])
    settings.save(s)
    assert os.path.isfile(settings.settings_path()) and settings.settings_path().startswith(str(user))
    again = settings.load(reload=True)
    assert again.blender == "C:/b/blender.exe" and again.library_dirs == ["D:/motions"]  # blank entries dropped
    with open(settings.settings_path(), "w", encoding="utf-8") as f:
        f.write("{broken")
    assert settings.load(reload=True) == settings.Settings()  # a broken file: defaults, no crash


def test_find_isaac(user, monkeypatch):
    inst = user / "isaac"
    launcher = _file(inst / settings.ISAAC_LAUNCHER)
    _file(inst / "VERSION", "6.1.0-rc.26+release.1\n")
    f = settings.find_isaac(settings.Settings(isaac_python=str(inst)))  # the folder is enough
    assert f.path == launcher and f.source == "설정" and f.detail == "Isaac Sim 6.1.0-rc.26"
    f = settings.find_isaac(settings.Settings(isaac_python=str(user / "nowhere")))
    assert f.path is None and "설정" in f.problem
    monkeypatch.setenv(settings.ISAAC_ENV, launcher)
    assert settings.find_isaac(settings.Settings()).source.startswith("환경변수")
    other = _file(user / "other" / settings.ISAAC_LAUNCHER)
    assert settings.find_isaac(settings.Settings(isaac_python=other)).path == other  # the setting wins
    settings.save(settings.Settings(isaac_python=other))
    assert isaac_command() == [other]  # physics jobs use it


def test_find_blender_and_smpl(user):
    exe = _file(user / "blender-4.5.14-windows-x64" / "blender.exe")
    f = settings.find_blender(settings.Settings(blender=os.path.dirname(exe)))
    assert f.path == exe and f.detail == "Blender 4.5.14"
    assert settings.find_blender(settings.Settings(blender=str(user / "x.exe"))).path is None
    models = user / "models"
    _file(models / "smplx" / "SMPLX_NEUTRAL.npz")
    _file(models / "smplx" / "SMPLX_MALE.npz")
    f = settings.find_smpl(settings.Settings(smpl_model_dir=str(models / "smplx")))  # the smplx folder itself is fine
    assert f.path == str(models) and f.detail == "SMPLX NEUTRAL, MALE"
    f = settings.find_smpl(settings.Settings(smpl_model_dir=str(user / "empty")))
    assert f.path is None and "SMPLX_NEUTRAL" in f.problem


def test_folders_and_check(user):
    extra = str(user / "my_motions")
    s = settings.Settings(library_dirs=[extra, extra.upper() if os.name == "nt" else extra], video_dir=str(user / "a" / "b"))
    libs = settings.library_dirs(s)
    assert libs[:len(paths.library_roots())] == [os.path.abspath(p) for p in paths.library_roots()]
    assert libs.count(os.path.abspath(extra)) == 1 and len(libs) == len(paths.library_roots()) + 1
    assert settings.video_dir(s) == str(user / "a" / "b")
    assert settings._writable(str(user / "a" / "b")) and not os.path.exists(user / "a")  # checked, not created
    checks = {c.key: c for c in settings.check_all(s)}
    assert set(checks) == {"robot", "gmr", "isaac", "blender", "smpl", "robot_usd", "video", "library"}
    assert checks["robot"].required and not checks["isaac"].required
    assert checks["video"].ok and checks["robot_usd"].ok  # empty robot USD: the asset library's G1


def test_robot_usd_option(user):
    from khumanoid.motion import RobotMotion
    from khumanoid.physics_runner import PhysicsRunner

    assert settings.find_robot_usd(settings.Settings()).path == ""  # default: NVIDIA's asset library
    usd = _file(user / "g1" / "g1.usda", "#usda 1.0\n")
    assert settings.find_robot_usd(settings.Settings(robot_usd=usd)).source == "설정 (로컬 파일)"
    assert settings.find_robot_usd(settings.Settings(robot_usd="omniverse://nucleus/G1/g1.usd")).path.startswith("omniverse")
    bad = settings.find_robot_usd(settings.Settings(robot_usd=str(user / "g1.txt")))
    assert bad.path is None and bad.problem
    import numpy as np

    m = RobotMotion(name="clip", joint_names=["a"], fps=30.0, root_pos=np.zeros((3, 3)),
                    root_quat=np.tile([1.0, 0, 0, 0], (3, 1)), dof_pos=np.zeros((3, 1)))
    runner = PhysicsRunner(str(user / "cache"), command=["python"])
    try:
        default_key = runner.key(m, 1.0)
        assert runner._robot_args() == []
        settings.save(settings.Settings(robot_usd=usd))
        assert runner._robot_args() == ["--robot-usd", usd]  # read from 환경 설정 at each request
        assert runner.key(m, 1.0) != default_key  # another robot asset: results kept apart
        settings.save(settings.Settings())
        assert runner.key(m, 1.0) == default_key  # back to the default: the earlier results again
    finally:
        runner.shutdown()
