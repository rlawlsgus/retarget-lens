"""The viewer's motion picker: which files are listed, and how browser uploads are stored."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import compare  # noqa: E402
from khumanoid.compare import is_motion_file, library_files, save_upload  # noqa: E402


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def test_motion_files_are_listed_by_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "ROOT", str(tmp_path))
    keep = [_touch(tmp_path / "data/raw/cmu_bvh/02_01.bvh"), _touch(tmp_path / "data/raw/cmu_fbx/02_01.fbx"),
            _touch(tmp_path / "data/raw/amass/CMU/02/02_01_stageii.npz"),
            _touch(tmp_path / "data/raw/unitree/walk.csv"), _touch(tmp_path / "data/retargeted/smooth6/02_01_g1.npz"),
            _touch(tmp_path / "reports/physics/smooth6/02_01_g1_sim.npz")]
    skip = [_touch(tmp_path / "data/raw/amass/CMU/02/neutral_stagei.npz"),  # body shape, not a motion
            _touch(tmp_path / "data/raw/cmu_bvh/SOURCE.md"), _touch(tmp_path / "data/retargeted/smooth6/02_01_g1.json"),
            _touch(tmp_path / "data/retargeted/cache/old_g1.npz"), _touch(tmp_path / "reports/qc_real.csv")]
    for p in keep:
        assert is_motion_file(p), p
    for p in skip:
        assert not is_motion_file(p), p
    lib = library_files(("data/raw", "data/retargeted", "reports", "data/missing"))
    assert list(lib) == ["data/raw/amass/CMU/02", "data/raw/cmu_bvh", "data/raw/cmu_fbx", "data/raw/unitree",
                         "data/retargeted/smooth6", "reports/physics/smooth6"]
    assert sorted(p for v in lib.values() for p in v) == sorted(keep)


def test_uploads_keep_their_name_and_reuse_identical_files(tmp_path):
    a = save_upload("02_01.bvh", b"HIERARCHY a", folder=str(tmp_path))
    assert os.path.basename(a) == "02_01.bvh"
    assert save_upload("02_01.bvh", b"HIERARCHY a", folder=str(tmp_path)) == a  # same file again
    b = save_upload("02_01.BVH", b"HIERARCHY b", folder=str(tmp_path))  # same name, other content
    assert os.path.basename(b) == "02_01_2.bvh"
    c = save_upload("../../evil name.fbx", b"x", folder=str(tmp_path))  # no path tricks
    assert os.path.dirname(c) == str(tmp_path) and os.path.basename(c) == "evil_name.fbx"
