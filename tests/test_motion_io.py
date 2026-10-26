import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens.io import load_motion  # noqa: E402
from retlens.io.bvh import load_bvh  # noqa: E402
from retlens.io.robot import G1_29DOF_JOINTS, urdf_joint_limits  # noqa: E402
from retlens.io.smpl import load_amass_npz  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402
from retlens.qc import check_robot, check_skeleton  # noqa: E402
from retlens.rotations import (  # noqa: E402
    axis_angle_to_matrix,
    axis_rotation,
    matrix_to_quat,
    quat_from_two_vectors,
    quat_to_matrix,
)
from retlens.synthetic import g1_motion, walking_bvh_text  # noqa: E402

SIMPLE_BVH = """HIERARCHY
ROOT Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT Chest
  {
    OFFSET 0 50 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    End Site
    {
      OFFSET 0 0 30
    }
  }
}
MOTION
Frames: 2
Frame Time: 0.01
0 100 0 0 0 0 0 0 0
10 100 0 0 0 0 0 0 90
"""


def test_rotations_roundtrip():
    rng = np.random.default_rng(0)
    aa = rng.normal(size=(100, 3))
    m = axis_angle_to_matrix(aa)
    assert np.allclose(quat_to_matrix(matrix_to_quat(m)), m, atol=1e-9)
    assert np.allclose(axis_angle_to_matrix(np.array([0, 0, 0.7])), axis_rotation("z", 0.7))
    # bone orientation helper: +Z rotated onto arbitrary (incl. anti-parallel) directions
    dirs = np.concatenate([rng.normal(size=(50, 3)), [[0, 0, -1.0], [0, 0, 1.0]]])
    q = quat_from_two_vectors(np.tile([0.0, 0, 1], (len(dirs), 1)), dirs)
    z = quat_to_matrix(q)[..., 2]
    assert np.allclose(z, dirs / np.linalg.norm(dirs, axis=-1, keepdims=True), atol=1e-9)


def test_bvh_fk_and_axes(tmp_path):
    p = tmp_path / "simple.bvh"
    p.write_text(SIMPLE_BVH)
    m = load_bvh(str(p), scale=0.01)
    assert m.joint_names == ["Hips", "Chest", "Chest_end"]
    assert list(m.parents) == [-1, 0, 1]
    assert m.fps == pytest.approx(100)
    # frame 0, Y-up (x, y, z) -> Z-up (x, -z, y)
    assert np.allclose(m.positions[0, 0], [0, 0, 1.0])
    assert np.allclose(m.positions[0, 1], [0, 0, 1.5])
    assert np.allclose(m.positions[0, 2], [0, -0.3, 1.5])
    # frame 1: root moved +10cm X; Chest rotated 90 deg about Y, so the end
    # site offset (0,0,30) becomes (30,0,0) in Y-up -> (0.3, 0, 0) in Z-up.
    assert np.allclose(m.positions[1, 0], [0.1, 0, 1.0])
    assert np.allclose(m.positions[1, 2], [0.4, 0, 1.5], atol=1e-9)


def test_bvh_auto_scale_and_qc(tmp_path):
    p = tmp_path / "walk.bvh"
    p.write_text(walking_bvh_text(seconds=4.0, fps=60))
    m = load_motion(str(p))
    assert m.meta["unit_scale"] == 0.01
    height = m.positions[0, :, 2].max() - m.positions[0, :, 2].min()
    assert 1.5 < height < 1.9
    r = check_skeleton(m)
    assert r.status in ("PASS", "WARN")
    assert r.valid_s == pytest.approx(4.0, abs=0.2)

    # break it: NaNs over 20% of frames and one teleport
    bad = m.positions.copy()
    bad[10:58] = np.nan
    bad[100:, 0] += 1.0
    m.positions = bad
    r = check_skeleton(m)
    assert r.flags["nan"][10:58].all()
    assert r.flags["spike"][100]
    assert r.status == "FAIL" and r.valid_s == 0.0


def test_robot_roundtrip_and_limits(tmp_path):
    m = g1_motion(seconds=2.0)
    p = tmp_path / "g1.npz"
    m.save_npz(str(p))
    m2 = load_motion(str(p))
    assert isinstance(m2, RobotMotion) and m2.joint_names == G1_29DOF_JOINTS
    assert np.allclose(m2.dof_pos, m.dof_pos, atol=1e-6)

    csv = tmp_path / "g1.csv"
    q_xyzw = m.root_quat[:, [1, 2, 3, 0]]
    np.savetxt(csv, np.concatenate([m.root_pos, q_xyzw, m.dof_pos], 1), delimiter=",")
    m3 = load_motion(str(csv), fps=50.0)
    assert m3.joint_names == G1_29DOF_JOINTS and np.allclose(m3.root_quat, m.root_quat)

    urdf = tmp_path / "r.urdf"
    urdf.write_text(
        '<robot name="r"><joint name="left_elbow_joint" type="revolute">'
        '<limit lower="-1.0" upper="0.5" velocity="20" effort="1"/></joint></robot>'
    )
    lim = urdf_joint_limits(str(urdf))
    assert lim["left_elbow_joint"] == (-1.0, 0.5, 20.0)
    r = check_robot(m, limits=lim)  # elbow held at 0.9 rad > 0.5 upper limit
    assert r.flags["joint_limit"].all() and r.status == "FAIL"
    assert check_robot(m).status == "PASS"


def test_amass_fk_with_toy_model(tmp_path):
    # 3-joint chain, 3 vertices that coincide with the joints
    v = np.array([[0, 0, 1.0], [0, 0, 1.5], [0, 0, 2.0]])
    model_dir = tmp_path / "models" / "smplh"
    model_dir.mkdir(parents=True)
    np.savez(model_dir / "SMPLH_NEUTRAL.npz", v_template=v, shapedirs=np.zeros((3, 3, 16)),
             J_regressor=np.eye(3), kintree_table=np.array([[2**32 - 1, 0, 1], [0, 1, 2]]))
    poses = np.zeros((2, 156))
    poses[1, 3:6] = [np.pi / 2, 0, 0]  # joint 1 rotated 90 deg about X
    trans = np.array([[0, 0, 0], [1.0, 0, 0]])
    clip = tmp_path / "clip.npz"
    np.savez(clip, poses=poses, trans=trans, betas=np.zeros(16), mocap_framerate=120.0, gender="neutral")
    m = load_amass_npz(str(clip), model_dir=str(tmp_path / "models"))
    assert m.fps == 120.0
    assert np.allclose(m.positions[0, :3], v)
    assert np.allclose(m.positions[1, 2], [1.0, -0.5, 1.5])
