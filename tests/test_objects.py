"""Objects captured with a human motion: read from FBX (through Blender; a small file the test builds), and
the hand-object contact numbers of retlens.objects. The FBX test skips when Blender is missing."""

import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import objects  # noqa: E402
from retlens.motion import ObjectTrack, RobotMotion, SkeletonMotion  # noqa: E402

# Blender builds the scene of a capture with props: a human-sized armature with a skinned body mesh (not an
# object), a 20 cm cube carried 1 m along +x over frames 1-11, a rigid-body empty that rises 0.5 m, and a
# table top that stays. Exported as FBX the way mocap tools write it (centimetres, Y-up).
BUILD = textwrap.dedent("""
    import sys, bpy
    out = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.render.fps = 1, 11, 10
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm = bpy.context.object
    bpy.ops.object.mode_set(mode="EDIT")
    b0 = arm.data.edit_bones[0]; b0.name = "Hips"; b0.head, b0.tail = (0, 0, 0.9), (0, 0, 1.2)
    b1 = arm.data.edit_bones.new("Chest"); b1.head, b1.tail, b1.parent = (0, 0, 1.2), (0, 0, 1.5), b0
    b2 = arm.data.edit_bones.new("Head"); b2.head, b2.tail, b2.parent = (0, 0, 1.5), (0, 0, 1.7), b1
    b3 = arm.data.edit_bones.new("HeadTop"); b3.head, b3.tail, b3.parent = (0, 0, 1.7), (0, 0, 1.75), b2
    b4 = arm.data.edit_bones.new("Leg"); b4.head, b4.tail, b4.parent = (0.1, 0, 0.9), (0.1, 0, 0.05), b0
    b5 = arm.data.edit_bones.new("Foot"); b5.head, b5.tail, b5.parent = (0.1, 0, 0.05), (0.1, -0.15, 0.0), b4
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.location = (0, 0, 0); arm.keyframe_insert("location", frame=1)
    arm.location = (0.3, 0, 0); arm.keyframe_insert("location", frame=11)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=1.6, location=(0, 0, 0.8))
    body = bpy.context.object; body.name = "Body"
    body.parent = arm
    mod = body.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0.5, 0, 1.0))
    box = bpy.context.object; box.name = "Box"
    box.keyframe_insert("location", frame=1)
    box.location = (1.5, 0, 1.0); box.keyframe_insert("location", frame=11)
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 1, 0.5))
    node = bpy.context.object; node.name = "RigidBody1"
    node.keyframe_insert("location", frame=1)
    node.location = (0, 1, 1.0); node.keyframe_insert("location", frame=11)
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(1, -1, 0.7))
    bpy.context.object.name = "TableTop"
    bpy.ops.export_scene.fbx(filepath=out, object_types={"ARMATURE", "MESH", "EMPTY"}, bake_anim=True,
                             bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False, add_leaf_bones=False,
                             apply_unit_scale=True, global_scale=100.0, axis_forward="-Z", axis_up="Y")
""")


def _blender() -> str | None:
    from retlens.io.fbx import find_blender

    try:
        return find_blender()
    except FileNotFoundError:
        return None


@pytest.mark.skipif(_blender() is None, reason="Blender not found")
def test_fbx_objects(tmp_path, monkeypatch):
    from retlens.io import fbx

    monkeypatch.setattr(fbx, "CACHE_DIR", str(tmp_path / "cache"))
    script, out = tmp_path / "build.py", tmp_path / "props.fbx"
    script.write_text(BUILD, encoding="utf-8")
    subprocess.run([_blender(), "-b", "--factory-startup", "--python", str(script), "--", str(out)], check=True,
                   capture_output=True, timeout=300)
    m = fbx.load_fbx(str(out))
    assert m.num_frames == 11 and set(m.joint_names) == {"Hips", "Chest", "Head", "HeadTop", "Leg", "Foot"}
    hips = m.joint_names.index("Hips")
    assert np.allclose(m.positions[-1, hips], [0.3, 0.0, 0.9], atol=0.02)  # meters, Z-up, whatever the file's units
    by = {o.name: o for o in m.objects}
    assert set(by) == {"Box", "RigidBody1", "TableTop"}  # the skinned body is the person, not an object
    box, node, top = by["Box"], by["RigidBody1"], by["TableTop"]
    assert box.kind == "mesh" and node.kind == "empty" and top.kind == "mesh"
    assert np.allclose(box.positions[0], [0.5, 0.0, 1.0], atol=0.02) and np.allclose(box.positions[-1], [1.5, 0.0, 1.0], atol=0.02)
    assert np.allclose(np.ptp(box.world_vertices(5), axis=0), 0.2, atol=0.01)  # the cube at its real size
    assert np.allclose(node.positions[-1], [0.0, 1.0, 1.0], atol=0.02) and len(node.vertices) == 0
    assert box.moves and node.moves and not top.moves
    assert np.allclose(top.world_vertices(0)[:, 2], 0.7, atol=0.01)


def _person(T: int, fps: float, hand: np.ndarray) -> SkeletonMotion:
    """A standing skeleton with the joints the retarget's name lookup needs; its left hand at `hand` (T, 3)."""
    spec = [("Hips", None, (0, 0, 0.9)), ("LeftUpLeg", "Hips", (0.1, 0, 0.9)), ("LeftLeg", "LeftUpLeg", (0.1, 0, 0.5)),
            ("LeftFoot", "LeftLeg", (0.1, 0, 0.1)), ("RightUpLeg", "Hips", (-0.1, 0, 0.9)),
            ("RightLeg", "RightUpLeg", (-0.1, 0, 0.5)), ("RightFoot", "RightLeg", (-0.1, 0, 0.1)),
            ("Spine2", "Hips", (0, 0, 1.3)), ("LeftArm", "Spine2", (0.2, 0, 1.4)), ("LeftForeArm", "LeftArm", (0.45, 0, 1.4)),
            ("LeftHand", "LeftForeArm", (0.7, 0, 1.4)), ("RightArm", "Spine2", (-0.2, 0, 1.4)),
            ("RightForeArm", "RightArm", (-0.45, 0, 1.4)), ("RightHand", "RightForeArm", (-0.7, 0, 1.4))]
    names = [n for n, _, _ in spec]
    P = np.tile(np.array([p for _, _, p in spec], float), (T, 1, 1))
    P[:, names.index("LeftHand")] = hand
    return SkeletonMotion("person", names, np.array([names.index(p) if p else -1 for _, p, _ in spec]), P, fps)


def test_hand_object_contact(monkeypatch):
    T, fps = 40, 20.0
    hand = np.tile([0.7, 0.0, 1.4], (T, 1))
    hand[20:, 0] = 0.4  # the left hand leaves the box half way
    p = hand.copy()  # before that the box sits right at the hand; then it stays where it was
    p[20:] = p[19]
    p[:, 0] += 0.06  # its centre 6 cm past the palm: the near face is 1 cm away
    box = ObjectTrack("box", positions=p, rotations=np.tile(np.eye(3), (T, 1, 1)),
                      vertices=np.array([[x, y, z] for x in (-0.05, 0.05) for y in (-0.05, 0.05) for z in (-0.05, 0.05)]),
                      faces=np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                                      [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]))
    h = _person(T, fps, hand)
    h.objects = [box]
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.75], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=fps)
    scale, hips, start = objects.human_scale(h, r), objects.anchor(h), r.root_pos[0]
    assert np.isclose(scale, 0.75 / 0.9)  # a clip that does not travel: the pelvis height ratio
    mapped = objects.human_to_robot(p, scale, hips, start)  # the box's path in the robot's world
    robot = np.zeros((T, 2, 3))
    robot[:, 0] = mapped - [0.06, 0.0, 0.0]  # the robot's left hand at the box like the person's...
    robot[10:20, 0] += [0.0, 0.0, 0.2]  # ...except for 10 frames, 20 cm above it
    robot[:, 1] = [-1.0, 0.0, 1.0]
    monkeypatch.setattr(objects, "robot_hands", lambda r, fk: robot)
    m = objects.hand_object_metrics(h, r, fk=None)
    assert m["hand_obj_contact_s"] == pytest.approx(20 / fps)  # the first 20 frames
    assert m["hand_obj_reach_pct"] == pytest.approx(50.0)  # robot within 6 cm in 10 of them
    assert 6.0 < m["hand_obj_err_cm"] < 10.0  # half at ~1 cm, half ~15 cm above the box's top
    (o,) = m["_objects"]
    assert o["name"] == "box" and not o["moves"] and o["contact_s"] == pytest.approx(1.0)  # held still, then left


def test_surface_points_cover_faces():
    """A table top has vertices at its corners only; the contact test needs points across its faces."""
    top = ObjectTrack("top", positions=np.zeros((1, 3)), rotations=np.eye(3)[None],
                      vertices=np.array([[-0.6, -0.4, 0.0], [0.6, -0.4, 0.0], [0.6, 0.4, 0.0], [-0.6, 0.4, 0.0]]),
                      faces=np.array([[0, 1, 2], [0, 2, 3]]))
    pts = objects.surface_points(top)
    assert len(pts) > 1000 and np.linalg.norm(pts, axis=1).min() < 0.05  # some near the middle of the top
    assert len(objects.surface_points(ObjectTrack("node", np.zeros((1, 3)), np.eye(3)[None], np.zeros((0, 3)),
                                                  np.zeros((0, 3), int), kind="empty"))) == 1
