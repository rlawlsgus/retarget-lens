"""Props exported apart from the people (retlens.props): finding a take's prop files (and leaving them out of motion
lists), the props in a file, timing, shapes, and the Blender reader of props-only FBX (skipped without Blender)."""

import os
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import props  # noqa: E402
from retlens.motion import SkeletonMotion  # noqa: E402


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"Kaydara FBX Binary  \x00")
    return str(path)


def _norm(files):
    return sorted(os.path.normcase(str(f)) for f in files)


def test_prop_files_shogun_layout(tmp_path):
    """Actors in their folders, props in a folder of their own; listed motions leave the props out."""
    m1 = _touch(tmp_path / "Takes_Raw" / "M1" / "pick_010_M1.fbx")
    m2 = _touch(tmp_path / "Takes_Raw" / "M2" / "pick_010_M2.fbx")
    prop = _touch(tmp_path / "Prop_Raw" / "pick_010_Prop.fbx")
    prop2 = _touch(tmp_path / "Prop_Raw" / "pick_010_Prop_2.fbx")
    ball = _touch(tmp_path / "Prop_Raw" / "pick_010_Ball.fbx")  # not named as a prop: not one
    other = [_touch(tmp_path / "Prop_Raw" / n) for n in ("pick_011_Prop.fbx", "pick_0100_Prop.fbx",
                                                         "pick_010_M1_x_Prop.fbx")]
    assert _norm(props.prop_files(m1)) == _norm([prop, prop2]) == _norm(props.prop_files(m2))
    assert all(props.is_prop_file(f) for f in [prop, prop2] + other)  # named as props in a prop folder: not motions
    assert not props.is_prop_file(m1) and not props.is_prop_file(ball) and props.prop_files(prop) == []
    from retlens.compare import is_motion_file

    assert not is_motion_file(prop) and is_motion_file(ball) and is_motion_file(m1)
    assert props.take_names(m1) == ["pick_010_m1", "pick_010"]
    assert props.take_names(str(tmp_path / "jump_002.fbx")) == ["jump_002"]  # a number is not an actor


def test_prop_files_flat_and_tricky_names(tmp_path):
    flat = tmp_path / "flat"
    a = _touch(flat / "lift_7_M1.fbx")
    p = _touch(flat / "lift_7_Prop.fbx")
    single = _touch(flat / "jump_002.fbx")  # one actor, the take is the whole name
    sp = _touch(flat / "jump_002_Props.fbx")
    assert props.is_prop_file(p) and props.is_prop_file(sp)
    assert _norm(props.prop_files(a)) == _norm([p]) and _norm(props.prop_files(single)) == _norm([sp])
    # names that only start with "prop", and a person carrying a prop: people, not prop files
    hoi = tmp_path / "hoi"
    carry, box = _touch(hoi / "carry_prop.fbx"), _touch(hoi / "carry_box.fbx")
    proper, fast = _touch(hoi / "walk_proper.fbx"), _touch(hoi / "walk_fast.fbx")
    assert not props.is_prop_file(carry) and not props.is_prop_file(proper)  # listed: "box" is no actor
    assert props.prop_files(fast) == []  # "proper" is no prop word
    assert _norm(props.prop_files(box)) == _norm([carry])  # named as carry's prop: read, and skipped if a person
    # the full name first: pick_001_slow does not take pick_001's ball when it has its own
    takes = tmp_path / "takes"
    slow = _touch(takes / "pick_001_slow.fbx")
    own, base = _touch(takes / "pick_001_slow_Prop.fbx"), _touch(takes / "pick_001_Prop.fbx")
    assert _norm(props.prop_files(slow)) == _norm([own]) and props.take_names(slow) == ["pick_001_slow", "pick_001"]
    assert base


def test_prop_files_people_in_a_prop_named_folder(tmp_path):
    """A folder named with props that holds the people: the other actor is never a prop; "property" is no prop word."""
    s = tmp_path / "session_with_props"
    m1, m2 = _touch(s / "pick_010_M1.fbx"), _touch(s / "pick_010_M2.fbx")
    p = _touch(s / "pick_010_Prop.fbx")
    assert _norm(props.prop_files(m1)) == _norm([p]) and not props.is_prop_file(m2)
    q = tmp_path / "property"
    a, b = _touch(q / "lift_010_A.fbx"), _touch(q / "lift_010_B.fbx")
    assert props.prop_files(a) == [] and not props.is_prop_folder(str(q)) and props.is_prop_folder("Prop_Raw")
    assert b


def test_versioned_prop_folders(tmp_path):
    m = _touch(tmp_path / "Takes_Clean" / "M1" / "take_003_M1.fbx")
    m_raw = _touch(tmp_path / "Takes_Raw" / "M1" / "take_003_M1.fbx")
    raw = _touch(tmp_path / "Prop_Raw" / "take_003_Prop.fbx")
    clean = _touch(tmp_path / "Prop_Clean" / "take_003_Prop.fbx")
    files, skipped = props.find_props(m)
    assert _norm(files) == _norm([clean]) and _norm([s["file"] for s in skipped]) == _norm([raw])
    # the folder whose name matches wins over the one listed first (Prop_Clean comes before Prop_Raw)
    files, skipped = props.find_props(m_raw)
    assert _norm(files) == _norm([raw]) and _norm([s["file"] for s in skipped]) == _norm([clean])


def test_resample_holds_and_interpolates():
    t_src = np.array([0.1, 0.2, 0.3])
    mats = np.tile(np.eye(4), (3, 1, 1))
    mats[:, :3, 3] = [[0, 0, 0], [1, 0, 0], [3, 0, 0]]
    from scipy.spatial.transform import Rotation

    mats[:, :3, :3] = Rotation.from_euler("z", [[0], [90], [90]], degrees=True).as_matrix()
    P, R = props.resample_pose(mats, t_src, np.array([0.0, 0.15, 0.25, 0.5]))
    assert np.allclose(P[:, 0], [0, 0.5, 2, 3])  # held before / after
    assert np.allclose(np.einsum("tij,tik->tjk", R, R), np.eye(3), atol=1e-9)
    assert np.isclose(Rotation.from_matrix(R[1]).as_euler("xyz", degrees=True)[2], 45, atol=1e-6)
    assert props.key_rate(119.88) == 120 and props.key_rate(29.97) == 30


def _human(frames=31, fps=30.0, start=0, source="person.fbx"):
    return SkeletonMotion(name="p", joint_names=["Hips"], parents=np.array([-1]), positions=np.zeros((frames, 1, 3)),
                          fps=fps, source=source, meta={"format": "fbx", "frame_start": start, "dropped_frames": 0,
                                                        "file_fps": fps, "unit_scale": 1.0, "ground_offset_m": 0.0})


def _node(name, kind, mats, group="", parent=-1, verts=None, faces=None, bind="", children=0, below_mesh=False):
    return dict(name=name, kind=kind, group=group, parent=parent, bind=bind, children=children, below_mesh=below_mesh,
                mats=mats, vertices=np.zeros((0, 3)) if verts is None else verts,
                faces=np.zeros((0, 3), np.int64) if faces is None else faces)


def _dump(objs, frames=121, fps=120.0, start=1, takes=None, take=""):
    return {"fps": fps, "key_fps": round(fps), "frame_start": start, "objects": objs, "takes": takes or [], "take": take,
            "reader": "test", "cache": ""}


def _moving(x0, vx, frames=121, fps=120.0, start=1):
    t = (start + np.arange(frames)) / fps
    M = np.tile(np.eye(4), (frames, 1, 1))
    M[:, 0, 3] = x0 + vx * t
    M[:, 2, 3] = 1.0
    return M


def _still(frames=121):
    return np.tile(np.eye(4), (frames, 1, 1))


TRI = (np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0.0]]), np.array([[0, 1, 2]]))


def test_prop_tracks_timing_names_and_shapes(monkeypatch):
    import retlens.io.fbx as fbx

    objs = [_node("Ball_1:root", "bone", _moving(0, 2), "Ball_1"),
            _node("Bat_1:root", "bone", _moving(1, 0), "Bat_1"),
            _node("Bat_1:tip", "bone", _moving(1.8, 0), "Bat_1", parent=1),
            _node("Bat_1:tip_End", "bone", _moving(1.9, 0), "Bat_1", parent=2),  # an end site: dropped
            _node("Marker", "empty", _still()),
            _node("Plate", "mesh", _still(), verts=TRI[0], faces=TRI[1])]
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: _dump(objs))
    shapes = {"bat": {"shape": "cylinder", "diameter": 6, "length": 80, "axis": "x", "offset": [40, 0, 0]},
              "bat:tip": {"shape": "sphere", "diameter": 4}, "marker": {"shape": "pyramid"}}
    info = {}
    tracks = props.prop_tracks("p_Prop.fbx", _human(), offset=2, shapes=shapes, shapes_dir="", info=info)
    by = {t.name: t for t in tracks}
    assert list(by) == ["Ball_1", "Bat_1:root", "Bat_1:tip", "Marker", "Plate"]
    ball = by["Ball_1"]
    # the motion's frame i is at i / 30 s, the props' first frame (number 1) at 1 / 120 s: held before it
    assert ball.positions.shape == (31, 3)
    assert np.allclose(ball.positions[:, 0], 2 * np.maximum(np.arange(31) / 30.0, 1 / 120))
    assert ball.shape == "구 지름 10 cm (기본값)" and np.isclose(np.linalg.norm(ball.vertices, axis=1).max(), 0.05)
    assert by["Bat_1:tip"].parent == 2 + 1 and by["Bat_1:root"].parent == -1  # into the motion's whole list
    root = by["Bat_1:root"]
    assert root.shape.startswith("원기둥") and np.allclose(root.vertices[:, 0].min(), 0, atol=1e-6)
    assert np.isclose(root.vertices[:, 0].max(), 0.8) and np.isclose(np.ptp(root.vertices[:, 1]), 0.06, atol=1e-3)
    assert by["Bat_1:tip"].shape.startswith("구 지름 4 cm") and by["Bat_1:tip"].group == "Bat_1"
    assert by["Marker"].shape.startswith("모양 파일 오류") and len(by["Marker"].vertices) == 0
    assert by["Plate"].shape == "파일의 메시" and len(by["Plate"].faces) == 1
    assert all(t.source.endswith("p_Prop.fbx") for t in tracks) and info["overlap_pct"] == 100.0


def test_prop_nodes_groups_markers_meshes_and_people():
    """Grouping nulls, markers on a prop bone, a mesh skinned to the ball bone, Blender's made-up "Armature"."""
    objs = [_node("Props", "empty", _still(), children=2),  # a static grouping null: dropped
            _node("Ball_4:root", "bone", _moving(0, 1), "Ball_4"),
            _node("Ball_4_Marker1", "empty", _moving(0.05, 1), "Ball_4", parent=1),
            _node("Ball_4_geo", "mesh", _moving(0, 1), "Ball_4", parent=1, verts=TRI[0], faces=TRI[1],
                  bind="rigid on bone Ball_4:root"),
            _node("Ball_9", "bone", _moving(2, 0), "Armature"),  # top-level LimbNodes of two props
            _node("Bat_2", "bone", _moving(3, 0), "Armature"),
            _node("Bat_2_tip", "bone", _moving(3.5, 0), "Armature", parent=5),
            _node("Holder", "empty", _moving(0, 1), children=1, below_mesh=True),
            _node("Holder_geo", "mesh", _moving(0, 1), parent=7, verts=TRI[0], faces=TRI[1])]  # stands in for it
    nodes = props.prop_nodes(_dump(objs))
    names = {nd["name"]: nd for nd in nodes}
    assert set(names) == {"Ball_4", "Ball_4:Ball_4_Marker1", "Ball_9", "Bat_2:Bat_2", "Bat_2:Bat_2_tip", "Holder"}
    assert names["Holder"]["mesh"] == 8
    ball = names["Ball_4"]  # the mesh stands in for its bone: one ball, drawn with the file's mesh
    assert ball["mesh"] == 3 and ball["first"] and ball["single"]
    assert nodes[names["Ball_4:Ball_4_Marker1"]["parent"]]["name"] == "Ball_4"
    assert names["Ball_9"]["prop"] == "Ball_9" and names["Bat_2:Bat_2_tip"]["prop"] == "Bat_2"
    person = [_node(n, "bone", _still(), "Bip001", parent=p) for n, p in
              [("Hips", -1), ("LeftUpLeg", 0), ("LeftLeg", 1), ("LeftFoot", 2), ("RightUpLeg", 0), ("RightLeg", 4),
               ("RightFoot", 5), ("Spine2", 0), ("LeftArm", 7), ("LeftForeArm", 8), ("LeftHand", 9), ("RightArm", 7),
               ("RightForeArm", 11), ("RightHand", 12)]]
    with pytest.raises(props.PersonSkeleton, match="사람 골격"):
        props.prop_nodes(_dump(person))


def test_prop_nodes_subjects_end_sites_namespaces():
    # Blender's made-up Armature: a still subject LimbNode "Ball_1" over the moving "Ball_1:root": the root carries it
    objs = [_node("Ball_1", "bone", _still(), "Armature"), _node("Ball_1:root", "bone", _moving(0, 1), "Armature", 0)]
    nodes = props.prop_nodes(_dump(objs))
    assert [(nd["name"], nd["index"], nd["first"]) for nd in nodes] == [("Ball_1", 1, True)]
    # a leaf named ...End that turns on its own is a segment, not an end site
    from scipy.spatial.transform import Rotation

    turn = _moving(0, 0)
    turn[:, :3, :3] = Rotation.from_euler("z", np.linspace(0, 90, len(turn))[:, None], degrees=True).as_matrix()
    objs = [_node("Nunchaku_1:Handle", "bone", _moving(0, 0), "Nunchaku_1"),
            _node("Nunchaku_1:End", "bone", turn, "Nunchaku_1", 0)]
    assert [nd["name"] for nd in props.prop_nodes(_dump(objs))] == ["Nunchaku_1:Handle", "Nunchaku_1:End"]
    # a namespaced null on its own keeps its whole name (and its shape keys drop the namespace)
    objs = [_node("Take:Ball_7", "empty", _moving(0, 1)), _node("Take:Box_1", "empty", _moving(1, 1))]
    nodes = props.prop_nodes(_dump(objs))
    assert [(nd["name"], nd["prop"]) for nd in nodes] == [("Take:Ball_7", "Take:Ball_7"), ("Take:Box_1", "Take:Box_1")]
    assert props.pick_take(["pick_7|BaseLayer", "pick_7_retake|BaseLayer"], "pick_7_retake|BaseLayer",
                           ["pick_7_m1", "pick_7"]) == "pick_7|BaseLayer"
    assert props.pick_take(["Box_1|aaa", "Box_1|pick_7"], "Box_1|aaa", ["pick_7"]) == "Box_1|pick_7"
    assert props.pick_take(["a", "b"], "a", ["pick_7"]) is None


def test_prop_tracks_mesh_on_ball_gets_no_default(monkeypatch):
    import retlens.io.fbx as fbx

    objs = [_node("Ball_1:root", "bone", _moving(0, 1), "Ball_1"),
            _node("Ball_1_geo", "mesh", _moving(0, 1), "Ball_1", parent=0, verts=TRI[0], faces=TRI[1],
                  bind="rigid on bone Ball_1:root")]
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: _dump(objs))
    tracks = props.prop_tracks("p_Prop.fbx", _human())
    assert [(t.name, len(t.faces), t.shape) for t in tracks] == [("Ball_1", 1, "파일의 메시 Ball_1_geo (뼈에 고정)")]


def test_overlap_and_ntsc_timing(monkeypatch):
    import retlens.io.fbx as fbx

    # 119.88 Hz props: Blender keyed them at 120 frames a second, so frame k is k / 120 s, not k / 119.88 s
    ntsc = _dump([_node("Ball_1:root", "bone", _moving(0, 1, frames=1201, fps=120.0, start=0), "Ball_1")],
                 frames=1201, fps=119.88, start=0)
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: ntsc)
    ball = props.prop_tracks("p_Prop.fbx", _human(frames=301))[0]
    assert np.allclose(ball.positions[:, 0], np.arange(301) / 30.0, atol=1e-9)
    late = _dump([_node("Ball_1:root", "bone", _moving(0, 1, start=2000), "Ball_1")], start=2000)
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: late)
    info = {}
    props.prop_tracks("p_Prop.fbx", _human(), info=info)
    assert info["overlap_pct"] == 0.0
    still = _dump([_node("Table_1", "empty", _still(frames=1))], frames=1)  # props that never move: no overlap to tell
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: still)
    info = {}
    props.prop_tracks("p_Prop.fbx", _human(), info=info)
    assert info["overlap_pct"] is None


def test_attach_reads_shape_file_and_reports(tmp_path, monkeypatch):
    import retlens.io.fbx as fbx

    person = _touch(tmp_path / "people" / "take_1_M1.fbx")
    prop = _touch(tmp_path / "props" / "take_1_Prop.fbx")
    (tmp_path / "props.yaml").write_text("props:\n  Ball: {shape: sphere, diameter: 7.4}\n"
                                         "  Crate: {mesh: crate.obj, unit: cm}\n", encoding="utf-8")
    import trimesh

    trimesh.creation.box(extents=[10, 20, 30]).export(str(tmp_path / "crate.obj"))
    objs = [_node("Ball_1:root", "bone", _moving(0, 2), "Ball_1"), _node("Crate_2", "empty", _moving(1, 0))]
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: _dump(objs))
    h = props.attach(_human(source=person))
    assert [o.name for o in h.objects] == ["Ball_1", "Crate_2"]
    assert h.objects[0].shape == "구 지름 7.4 cm (모양 파일)" and h.objects[1].shape == "메시 crate.obj (모양 파일)"
    assert np.allclose(np.ptp(h.objects[1].vertices, axis=0), [0.1, 0.2, 0.3])
    rep = h.meta["props"][0]
    assert os.path.normcase(rep["file"]) == os.path.normcase(prop) and rep["objects"] == ["Ball_1", "Crate_2"]
    assert os.path.normcase(rep["shapes"]) == os.path.normcase(str(tmp_path / "props.yaml"))
    sig = props.signature(person)
    assert [os.path.basename(s[0]) for s in sig] == ["take_1_Prop.fbx", "props.yaml", "crate.obj"]

    def broken(path, take=None, cache=True):
        raise RuntimeError("Blender failed")

    monkeypatch.setattr(fbx, "read_props", broken)
    h = props.attach(_human(source=person))
    assert h.objects == [] and "Blender failed" in h.meta["props"][0]["error"]
    names = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot", "Spine2", "LeftArm",
             "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
    parents = [-1, 0, 1, 2, 0, 4, 5, 0, 7, 8, 9, 7, 11, 12]
    person_dump = _dump([_node(n, "bone", _still(), "Body", parent=p) for n, p in zip(names, parents)])
    monkeypatch.setattr(fbx, "read_props", lambda path, take=None, cache=True: person_dump)
    h2 = props.attach(_human(source=person))  # a person's file named as a prop: skipped (not an error to retry)
    assert h2.objects == [] and "사람 골격" in h2.meta["props"][0]["skipped"] and "error" not in h2.meta["props"][0]
    from retlens.app.scene import MotionScene
    from retlens.compare import Item

    rows = MotionScene.object_rows(Item(label="x", source=person, kind="FBX", robot=None, human=h, info={}))
    assert rows and rows[0][0] == "물체 파일" and "읽지 못함" in rows[0][1]  # shown without objects of its own
    bvh = _human(source=person)
    bvh.meta["format"] = "bvh"
    assert props.attach(bvh).objects == [] and "props" not in bvh.meta


def test_shapes(tmp_path):
    V, F, text = props.make_shape({"shape": "box", "size": [40, 30, 20], "offset": [0, 0, 10]}, "")
    assert np.allclose(V.min(0), [-0.2, -0.15, 0]) and np.allclose(V.max(0), [0.2, 0.15, 0.2]) and "상자" in text
    V, _, _ = props.make_shape({"shape": "cylinder", "diameter": 10, "length": 50, "axis": "y", "rotate": [0, 0, 90]}, "")
    assert np.isclose(np.ptp(V[:, 0]), 0.5, atol=1e-6)  # along y, then turned 90 deg about z: along x
    for bad in ({"shape": "sphere"}, {"shape": "box", "size": [1, 2]}, {"shape": "box"},
                {"shape": "cylinder", "diameter": 3, "length": 4, "axis": "w"},
                {"mesh": "missing.obj"}, {"shape": "sphere", "diameter": 5, "colour": "red"}, "sphere"):
        with pytest.raises(ValueError):
            props.make_shape(bad, str(tmp_path))
    assert props.shape_keys("Bat_2", "tip", first=False, single=False) == ["Bat_2:tip", "Bat:tip"]
    assert props.shape_keys("Bat_2", "root", first=True, single=False) == ["Bat_2:root", "Bat:root", "Bat_2", "Bat"]
    assert props.shape_keys("Take:Ball_1", "root", first=True, single=True) == ["Take:Ball_1", "Take:Ball", "Ball_1",
                                                                                "Ball"]


# --------------------------------------------------------------------------- with Blender
def _blender():
    from retlens.io.fbx import find_blender

    try:
        return find_blender()
    except FileNotFoundError:
        return None


MAKE_PROPS = r"""
import bpy, sys
out_arm, out_empty = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = 120
# a prop as a skeleton (Shogun): an armature with a root and a tip segment, the root moving 1 m along x
arm = bpy.data.objects.new("Bat_1", bpy.data.armatures.new("Bat_1"))
sc.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
root = arm.data.edit_bones.new("Bat_1:root"); root.head = (0, 0, 0); root.tail = (0, 0.1, 0)
tip = arm.data.edit_bones.new("Bat_1:tip"); tip.head = (0, 0.8, 0); tip.tail = (0, 0.9, 0); tip.parent = root
bpy.ops.object.mode_set(mode="POSE")
pb = arm.pose.bones["Bat_1:root"]
for f, x in ((1, 0.0), (121, 1.0)):
    pb.location = (x, 0, 0); pb.keyframe_insert("location", frame=f)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.fbx(filepath=out_arm, object_types={"ARMATURE"}, add_leaf_bones=False, bake_anim=True,
                         bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = 120
# a prop as an animated null with two takes: "aaa" still at z = 5, "pick_7" rising 0.5 m
e = bpy.data.objects.new("Box_1", None)
sc.collection.objects.link(e)
e.animation_data_create()
for act_name, keys in (("aaa", ((1, 5.0), (61, 5.0))), ("pick_7", ((1, 0.0), (61, 0.5)))):
    act = bpy.data.actions.new(act_name)
    e.animation_data.action = act
    for f, z in keys:
        e.location = (0, 0, z); e.keyframe_insert("location", frame=f)
e.animation_data.action = bpy.data.actions["aaa"]
bpy.ops.export_scene.fbx(filepath=out_empty, object_types={"EMPTY"}, bake_anim=True, bake_anim_use_all_actions=True,
                         bake_anim_use_nla_strips=False)
"""


@pytest.mark.skipif(_blender() is None, reason="needs Blender")
def test_read_props_through_blender(tmp_path, monkeypatch):
    import retlens.io.fbx as fbx

    monkeypatch.setattr(fbx, "CACHE_DIR", str(tmp_path / "cache"))
    arm_fbx, empty_fbx = str(tmp_path / "t_Prop.fbx"), str(tmp_path / "pick_7_Prop.fbx")
    script = tmp_path / "make.py"
    script.write_text(MAKE_PROPS, encoding="utf-8")
    subprocess.run([_blender(), "-b", "--factory-startup", "--python-exit-code", "2", "--python", str(script), "--",
                    arm_fbx, empty_fbx], check=True, capture_output=True, timeout=600)
    raw = fbx.read_props(arm_fbx)
    objs = {o["name"]: o for o in raw["objects"]}
    assert {"Bat_1:root", "Bat_1:tip"} <= set(objs) and raw["fps"] == 120 and raw["key_fps"] == 120
    assert objs["Bat_1:tip"]["parent"] == raw["objects"].index(objs["Bat_1:root"])
    root = objs["Bat_1:root"]["mats"]
    assert np.isclose(np.ptp(root[:, :3, 3], axis=0).max(), 1.0, atol=0.02)  # the 1 m it moves
    tip = objs["Bat_1:tip"]["mats"]
    assert np.allclose(np.linalg.norm(tip[:, :3, 3] - root[:, :3, 3], axis=1), 0.8, atol=0.02)  # rigid with the root
    assert [t.name for t in props.prop_tracks(arm_fbx, _human(source=str(tmp_path / "t_M1.fbx")))] == \
        ["Bat_1:root", "Bat_1:tip"]
    raw = fbx.read_props(empty_fbx)
    assert len(raw["takes"]) == 2, raw["takes"]
    for take in raw["takes"]:  # switching takes really reads that take (Blender 4.4+ action slots)
        z = [o for o in fbx.read_props(empty_fbx, take=take)["objects"] if o["name"] == "Box_1"][0]["mats"][:, 2, 3]
        assert (np.isclose(np.ptp(z), 0.5, atol=0.02) if "pick_7" in take else np.allclose(z, 5.0, atol=0.02)), take
    info = {}
    box = props.prop_tracks(empty_fbx, _human(frames=61, source=str(tmp_path / "pick_7_M1.fbx")), info=info)
    assert "pick_7" in info["take"] and np.isclose(np.ptp(box[0].positions[:, 2]), 0.5, atol=0.02)  # the moving take
    with pytest.raises(ValueError, match="골격"):  # a props-only file opened as a person
        fbx.load_fbx(empty_fbx)
