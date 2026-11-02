"""Runs inside Blender (``blender -b --factory-startup --python <this> -- <mode> ...``).

Not imported by retlens: retlens.io.fbx starts Blender with it.

    dump    <in.fbx> <out.npz> [take]   world joint positions / frames of the armature, and the objects
    bvh2fbx <in.bvh> <out.fbx> <scale>  BVH -> FBX (armature only, every frame baked)

Blender's FBX importer converts the file to Blender's frame (Z-up, -Y forward,
meters), which is the project frame too. Joint = bone head; joint frame = the
bone's world matrix (Blender bone axes, rest and motion alike).

Objects (props, furniture, rigid bodies) are every other mesh or empty in the file: a mesh not deformed
by the armature (the character's skinned body is left out) and an empty with no mesh under it (a
rigid-body node of a mocap export). Per frame their world matrices, once their mesh in the object's own
frame (triangulated, modifiers applied).
"""

import os
import sys

import bpy
import numpy as np

VERSION = 2  # 2: objects


def fail(msg):
    print(f"[blender_fbx] ERROR: {msg}", flush=True)
    sys.exit(2)


def armature_with_action():
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if not arms:
        fail("no armature in the file")
    animated = [o for o in arms if o.animation_data and o.animation_data.action]
    return max(animated or arms, key=lambda o: len(o.data.bones))


def to_np(m):
    return np.array([list(r) for r in m], dtype=np.float64)


def deformed_by(o, arm):
    """A mesh the armature deforms (the character's body) or one parented to it as skin."""
    return any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers) or (
        o.parent == arm and o.parent_type == "ARMATURE")


def scene_objects(arm):
    """The objects besides the character: meshes the armature does not deform, and empties with no
    mesh under them. Sorted by name."""
    out = []
    for o in bpy.context.scene.objects:
        if o == arm or (o.type == "MESH" and deformed_by(o, arm)):
            continue
        if o.type == "MESH" or (o.type == "EMPTY" and not any(c.type == "MESH" for c in o.children_recursive)):
            out.append(o)
    return sorted(out, key=lambda o: o.name)


def object_mesh(o):
    """Triangles of a mesh object in its own frame, modifiers applied: (vertices (V, 3), faces (F, 3))."""
    if o.type != "MESH":
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        v = np.array([tuple(p.co) for p in me.vertices], dtype=np.float64).reshape(-1, 3)
        f = np.array([tuple(t.vertices) for t in me.loop_triangles], dtype=np.int64).reshape(-1, 3)
    finally:
        ev.to_mesh_clear()
    return v, f


def dump(src, out, take=""):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=src, use_anim=True, anim_offset=0.0, automatic_bone_orientation=False,
                             ignore_leaf_bones=False, use_custom_props=False)
    arm = armature_with_action()
    actions = [a.name for a in bpy.data.actions]
    act = arm.animation_data.action if arm.animation_data else None
    if take:
        match = [a for a in bpy.data.actions if a.name == take or a.name.split("|")[-1] == take]
        if not match:
            fail(f"no take {take!r}; takes: {actions}")
        act = match[0]
        arm.animation_data.action = act
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    if act is not None:
        f0, f1 = (int(round(v)) for v in act.frame_range)
    else:
        f0 = f1 = scene.frame_current
    bones = list(arm.data.bones)
    names = [b.name for b in bones]
    parents = [names.index(b.parent.name) if b.parent else -1 for b in bones]
    pbones = [arm.pose.bones[n] for n in names]

    scene.frame_set(f0)
    W = to_np(arm.matrix_world)
    rest = np.stack([W @ to_np(b.matrix_local) for b in bones])
    objs = scene_objects(arm)
    meshes = [object_mesh(o) for o in objs]
    T = f1 - f0 + 1
    mats = np.empty((T, len(bones), 4, 4))
    obj_mats = np.empty((T, len(objs), 4, 4))
    for k in range(T):
        scene.frame_set(f0 + k)
        W = to_np(arm.matrix_world)
        mats[k] = [W @ to_np(pb.matrix) for pb in pbones]
        if objs:
            obj_mats[k] = [to_np(o.matrix_world) for o in objs]
    nv = np.cumsum([0] + [len(v) for v, _ in meshes])
    nf = np.cumsum([0] + [len(f) for _, f in meshes])
    np.savez(out, names=np.array(names), parents=np.array(parents), mats=mats, rest=rest, fps=fps,
             frame_start=f0, take=act.name if act is not None else "", takes=np.array(actions),
             armature=arm.name, blender=bpy.app.version_string, script_version=VERSION,
             obj_names=np.array([o.name for o in objs], dtype=str), obj_kinds=np.array([o.type.lower() for o in objs], dtype=str),
             obj_mats=obj_mats, obj_vert_start=nv, obj_face_start=nf,
             obj_verts=np.concatenate([v for v, _ in meshes]) if objs else np.zeros((0, 3)),
             obj_faces=np.concatenate([f for _, f in meshes]) if objs else np.zeros((0, 3), dtype=np.int64))
    print(f"[blender_fbx] {src}: {len(names)} bones, {len(objs)} objects, {T} frames @ {fps:g} fps -> {out}", flush=True)


def bvh2fbx(src, out, scale):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(filepath=src, global_scale=float(scale), frame_start=1, use_fps_scale=False,
                            update_scene_fps=True, update_scene_duration=True, rotate_mode="NATIVE",
                            axis_forward="-Z", axis_up="Y")
    arm = armature_with_action()
    scene = bpy.context.scene
    # bake exactly the BVH's frames (the importer only ever extends the scene range)
    scene.frame_start, scene.frame_end = (int(round(v)) for v in arm.animation_data.action.frame_range)
    for o in scene.objects:
        o.select_set(o == arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(filepath=out, use_selection=True, object_types={"ARMATURE"}, add_leaf_bones=False,
                             bake_anim=True, bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
                             bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
                             bake_anim_step=1.0, bake_anim_simplify_factor=0.0, apply_unit_scale=True,
                             axis_forward="-Z", axis_up="Y")
    print(f"[blender_fbx] {src} -> {out} ({scene.frame_end - scene.frame_start + 1} frames @ "
          f"{scene.render.fps / scene.render.fps_base:g} fps)", flush=True)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        fail(__doc__)
    mode, rest_args = args[0], args[1:]
    try:
        if mode == "dump":
            dump(*rest_args)
        elif mode == "bvh2fbx":
            bvh2fbx(*rest_args)
        else:
            fail(f"unknown mode {mode!r}")
    except SystemExit:
        raise
    except Exception as e:  # report and exit non-zero (Blender would keep running otherwise)
        import traceback

        traceback.print_exc()
        fail(f"{type(e).__name__}: {e}")
    sys.stdout.flush()
    os._exit(0)
