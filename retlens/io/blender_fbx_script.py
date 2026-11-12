"""Runs inside Blender (``blender -b --factory-startup --python <this> -- <mode> ...``).

Not imported by retlens: retlens.io.fbx starts Blender with it.

    dump    <in.fbx> <out.npz> [take]   world joint positions / frames of the armature, and the objects
    props   <in.fbx> <out.npz> [take]   every node of a props-only file (a mocap system's rigid bodies)
    bvh2fbx <in.bvh> <out.fbx> <scale>  BVH -> FBX (armature only, every frame baked)

Blender's FBX importer converts the file to Blender's frame (Z-up, -Y forward,
meters), which is the project frame too. Joint = bone head; joint frame = the
bone's world matrix (Blender bone axes, rest and motion alike).

Objects (props, furniture, rigid bodies) are every other mesh or empty in the file: a mesh no armature
deforms (the characters' skinned bodies are left out) and an empty with no mesh or armature under it (a
rigid-body node of a mocap export; not the root null an armature hangs on). Per frame their world matrices,
once their mesh in the object's own frame (triangulated, modifiers applied). The bones of the file's other
armatures (a second actor, or a prop written as a skeleton) are dumped too (xb_*: name, armature, parent,
child count, whether the armature is animated, world matrices per frame); retlens.io.fbx decides what they are.

A file without an armature (a prop exported apart, as animated empties or meshes) dumps no bones and its
objects over the frames their actions cover.

props: a file of props exported apart from the people (Vicon Shogun / MotionBuilder: per prop a null with
one or more segment bones, "Ball_1" > "Ball_1:root"; or animated empties and meshes). Every node is dumped
raw over the frames the chosen take's actions cover (retlens.props decides what makes a prop): each bone of
every armature, each empty, each mesh, with its parent node (a bone or an empty; something on an armature
object, not on a bone, has none but the armature as its group), its child count and whether a mesh hangs below
it. A mesh the armature deforms rides rigidly on the bone that weighs most on it. key_fps is the integer rate
the importer placed the keys at (frame number / key_fps = file time).
"""

import os
import sys

import bpy
import numpy as np

VERSION = 3  # 2: objects; 3: an armature's root null is no object, the other armatures' bones (xb_*)
PROPS_VERSION = 3  # 2: every empty, parents across bones / empties, takes, key_fps; 3: take slots, armature children


def fail(msg):
    print(f"[blender_fbx] ERROR: {msg}", flush=True)
    sys.exit(2)


def armature_with_action(required=True):
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if not arms:
        if not required:
            return None
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
    """The objects besides the character: meshes no armature of the file deforms, and empties with no
    mesh or armature under them (an armature's root null, e.g. "reference": its motion is in the armature's
    own world matrix). Sorted by name."""
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    out = []
    for o in bpy.context.scene.objects:
        if o == arm or (o.type == "MESH" and any(deformed_by(o, a) for a in arms)):
            continue
        if o.type == "MESH" or (o.type == "EMPTY" and not any(c.type in ("MESH", "ARMATURE")
                                                              for c in o.children_recursive)):
            out.append(o)
    return sorted(out, key=lambda o: o.name)


def other_bones(arm):
    """The bones of the file's other armatures (a second actor, a prop written as a skeleton: "Ball_1" >
    "Ball_1:root"), armature by armature (sorted by name): (armature, bone) pairs."""
    others = sorted((o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o != arm), key=lambda o: o.name)
    return [(o, b) for o in others for b in o.data.bones]


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
    arm = armature_with_action(required=False)
    actions = [a.name for a in bpy.data.actions]
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    if arm is not None:
        act = arm.animation_data.action if arm.animation_data else None
        if take:
            match = [a for a in bpy.data.actions if a.name == take or a.name.split("|")[-1] == take]
            if not match:
                fail(f"no take {take!r}; takes: {actions}")
            act = match[0]
            arm.animation_data.action = act
        ranges = [act.frame_range] if act is not None else []
    else:  # props only: the frames every animated object's action covers
        if take:
            fail("a take can only be chosen in a file with an armature")
        animated = [o for o in scene.objects if o.animation_data and o.animation_data.action]
        act = animated[0].animation_data.action if animated else None
        ranges = [o.animation_data.action.frame_range for o in animated]
    if ranges:
        f0, f1 = int(round(min(r[0] for r in ranges))), int(round(max(r[1] for r in ranges)))
    else:
        f0 = f1 = scene.frame_current
    bones = list(arm.data.bones) if arm is not None else []
    names = [b.name for b in bones]
    parents = [names.index(b.parent.name) if b.parent else -1 for b in bones]
    pbones = [arm.pose.bones[n] for n in names]

    scene.frame_set(f0)
    W = to_np(arm.matrix_world) if arm is not None else np.eye(4)
    rest = np.stack([W @ to_np(b.matrix_local) for b in bones]) if bones else np.zeros((0, 4, 4))
    objs = scene_objects(arm)
    meshes = [object_mesh(o) for o in objs]
    xbones = other_bones(arm)  # the other armatures: retlens.io.fbx makes props of them or warns of a second person
    xkey = {(o.name, b.name): i for i, (o, b) in enumerate(xbones)}
    xpose = [(o, o.pose.bones[b.name]) for o, b in xbones]
    T = f1 - f0 + 1
    mats = np.empty((T, len(bones), 4, 4))
    obj_mats = np.empty((T, len(objs), 4, 4))
    xb_mats = np.empty((T, len(xbones), 4, 4))
    for k in range(T):
        scene.frame_set(f0 + k)
        if bones:
            W = to_np(arm.matrix_world)
            mats[k] = [W @ to_np(pb.matrix) for pb in pbones]
        if objs:
            obj_mats[k] = [to_np(o.matrix_world) for o in objs]
        if xbones:
            xb_mats[k] = [to_np(o.matrix_world) @ to_np(pb.matrix) for o, pb in xpose]
    nv = np.cumsum([0] + [len(v) for v, _ in meshes])
    nf = np.cumsum([0] + [len(f) for _, f in meshes])
    np.savez(out, names=np.array(names, dtype=str), parents=np.array(parents, dtype=np.int64), mats=mats, rest=rest,
             fps=fps, frame_start=f0, take=act.name if act is not None else "", takes=np.array(actions, dtype=str),
             armature=arm.name if arm is not None else "", blender=bpy.app.version_string, script_version=VERSION,
             obj_names=np.array([o.name for o in objs], dtype=str), obj_kinds=np.array([o.type.lower() for o in objs], dtype=str),
             obj_mats=obj_mats, obj_vert_start=nv, obj_face_start=nf,
             obj_verts=np.concatenate([v for v, _ in meshes]) if objs else np.zeros((0, 3)),
             obj_faces=np.concatenate([f for _, f in meshes]) if objs else np.zeros((0, 3), dtype=np.int64),
             xb_names=np.array([b.name for _, b in xbones], dtype=str),
             xb_groups=np.array([o.name for o, _ in xbones], dtype=str),
             xb_parents=np.array([xkey[(o.name, b.parent.name)] if b.parent else -1 for o, b in xbones], dtype=np.int64),
             xb_children=np.array([len(b.children) for _, b in xbones], dtype=np.int64),
             xb_animated=np.array([bool(o.animation_data and o.animation_data.action) for o, _ in xbones], dtype=bool),
             xb_mats=xb_mats)
    print(f"[blender_fbx] {src}: {len(names)} bones, {len(objs)} objects, {len(xbones)} bones of other armatures, "
          f"{T} frames @ {fps:g} fps -> {out}", flush=True)


def mesh_rest(o):
    """Triangles of a mesh's own data (no modifiers: the shape before an armature deforms it)."""
    me = o.data
    me.calc_loop_triangles()
    v = np.array([tuple(p.co) for p in me.vertices], dtype=np.float64).reshape(-1, 3)
    f = np.array([tuple(t.vertices) for t in me.loop_triangles], dtype=np.int64).reshape(-1, 3)
    return v, f


def dominant_bone(o, arm):
    """The bone of `arm` whose vertex group weighs most on mesh `o` (None when none does)."""
    names = {b.name for b in arm.data.bones}
    groups = {g.index: g.name for g in o.vertex_groups if g.name in names}
    total = {}
    for v in o.data.vertices:
        for g in v.groups:
            if g.group in groups:
                total[groups[g.group]] = total.get(groups[g.group], 0.0) + g.weight
    return max(total, key=total.get) if total else None


def stack_of(action_name, objs):
    """The take of an imported action: its name without the object's. Blender's importer names actions
    "object|stack" (or "object|stack|layer" when the layer is named apart), and a stack name may hold "|" itself
    (Blender's own exports: "object|action"), so the take is everything after the object's name."""
    owner = max((o.name for o in objs if action_name.startswith(o.name + "|")), key=len, default="")
    return action_name[len(owner) + 1:] if owner else action_name


def dump_props(src, out, take=""):
    """Every node of a props-only file, raw: which ones make a prop is decided in retlens.props. take: the
    animation stack to sample (default: the one the importer assigned, the file's first)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=src, use_anim=True, anim_offset=0.0, automatic_bone_orientation=False,
                             ignore_leaf_bones=False, use_custom_props=False)
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    objs = sorted(scene.objects, key=lambda o: o.name)
    stacks = sorted({stack_of(a.name, objs) for a in bpy.data.actions})
    if take:  # every object on that stack's action (the importer links only the first stack it finds); objects the
        # stack does not key lose the other stack's action, so they hold their rest pose
        found = False
        for o in objs:
            acts = [a for a in bpy.data.actions if a.name == f"{o.name}|{take}"]
            if acts:
                ad = o.animation_data or o.animation_data_create()
                ad.action = acts[0]
                slots = getattr(acts[0], "slots", None)
                if slots is not None and len(slots) and hasattr(ad, "action_slot"):  # Blender 4.4+: a slot too
                    ad.action_slot = slots[0]
                found = True
            elif o.animation_data is not None and o.animation_data.action is not None:
                o.animation_data.action = None
        if not found:
            fail(f"no take {take!r}; takes: {stacks}")
    animated = [o for o in objs if o.animation_data and o.animation_data.action]
    chosen = take or (stack_of(animated[0].animation_data.action.name, objs) if animated else "")
    ranges = [o.animation_data.action.frame_range for o in animated]
    if ranges:
        f0, f1 = int(round(min(r[0] for r in ranges))), int(round(max(r[1] for r in ranges)))
    else:
        f0 = f1 = scene.frame_current
    scene.frame_set(f0)
    none = (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    tracks = []  # dicts: key, name, kind, group, parent (key or None), get (-> 4x4 now), mesh, bind, children, below_mesh
    for arm in (o for o in objs if o.type == "ARMATURE"):
        for b in arm.data.bones:
            pb = arm.pose.bones[b.name]
            tracks.append(dict(key=("bone", arm.name, b.name), name=b.name, kind="bone", group=arm.name,
                               parent=("bone", arm.name, b.parent.name) if b.parent else None,
                               get=(lambda arm=arm, pb=pb: to_np(arm.matrix_world) @ to_np(pb.matrix)), mesh=none,
                               bind="", children=len(b.children), below_mesh=False))
    def parent_key(o):
        p = o.parent
        if p is None:
            return None, ""
        if p.type == "ARMATURE":  # on a bone (rides it); on the armature object it does not follow the bones
            if o.parent_type == "BONE" and o.parent_bone:
                return ("bone", p.name, o.parent_bone), p.name
            return None, p.name
        return ("obj", p.name), ""

    for o in objs:
        if o.type == "EMPTY":
            parent, group = parent_key(o)
            tracks.append(dict(key=("obj", o.name), name=o.name, kind="empty", group=group, parent=parent,
                               get=(lambda o=o: to_np(o.matrix_world)), mesh=none, bind="", children=len(o.children),
                               below_mesh=any(c.type == "MESH" for c in o.children_recursive)))
        elif o.type == "MESH":
            arm = next((m.object for m in o.modifiers if m.type == "ARMATURE" and m.object is not None), None)
            bone = dominant_bone(o, arm) if arm is not None else None
            if bone is not None:  # skinned: rides the bone that weighs most on it, rigidly
                pb = arm.pose.bones[bone]
                bind = np.linalg.inv(to_np(arm.matrix_world) @ to_np(arm.data.bones[bone].matrix_local)) @ to_np(o.matrix_world)
                tracks.append(dict(key=("obj", o.name), name=o.name, kind="mesh", group=arm.name,
                                   parent=("bone", arm.name, bone),
                                   get=(lambda arm=arm, pb=pb, bind=bind: to_np(arm.matrix_world) @ to_np(pb.matrix) @ bind),
                                   mesh=mesh_rest(o), bind=f"rigid on bone {bone}", children=len(o.children),
                                   below_mesh=False))
            else:
                parent, group = parent_key(o)
                tracks.append(dict(key=("obj", o.name), name=o.name, kind="mesh", group=group, parent=parent,
                                   get=(lambda o=o: to_np(o.matrix_world)), mesh=object_mesh(o), bind="",
                                   children=len(o.children), below_mesh=False))
    index = {t["key"]: i for i, t in enumerate(tracks)}
    parents = [index.get(t["parent"], -1) if t["parent"] else -1 for t in tracks]
    T = f1 - f0 + 1
    mats = np.empty((T, len(tracks), 4, 4))
    for k in range(T):
        scene.frame_set(f0 + k)
        if tracks:
            mats[k] = [t["get"]() for t in tracks]
    meshes = [t["mesh"] for t in tracks]
    nv = np.cumsum([0] + [len(v) for v, _ in meshes])
    nf = np.cumsum([0] + [len(f) for _, f in meshes])
    col = lambda k, dtype=str: np.array([t[k] for t in tracks], dtype=dtype)  # noqa: E731
    np.savez(out, fps=fps, key_fps=scene.render.fps, frame_start=f0, blender=bpy.app.version_string,
             script_version=PROPS_VERSION, take=chosen, takes=np.array(stacks, dtype=str),
             obj_names=col("name"), obj_kinds=col("kind"), obj_groups=col("group"),
             obj_parents=np.array(parents, dtype=np.int64), obj_binds=col("bind"),
             obj_children=col("children", np.int64), obj_below_mesh=col("below_mesh", bool),
             obj_mats=mats, obj_vert_start=nv, obj_face_start=nf,
             obj_verts=np.concatenate([v for v, _ in meshes]) if tracks else np.zeros((0, 3)),
             obj_faces=np.concatenate([f for _, f in meshes]) if tracks else np.zeros((0, 3), dtype=np.int64))
    print(f"[blender_fbx] {src}: {len(tracks)} prop nodes, take {chosen!r} of {stacks}, {T} frames @ {fps:g} fps "
          f"-> {out}", flush=True)


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
        elif mode == "props":
            dump_props(*rest_args)
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
