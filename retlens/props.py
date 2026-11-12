"""Props exported apart from the people: a mocap system's rigid bodies written to a file of their own per take
(Vicon Shogun / MotionBuilder: <take>_Prop.fbx beside <take>_M1.fbx and <take>_M2.fbx, often in a folder of
their own such as Prop_Raw). attach() finds that file for an FBX motion, reads its nodes
(retlens.io.fbx.read_props) and puts the props on the motion's frames as its objects, so the window draws them
with the robot and retlens.objects measures the hands against them, as for objects inside the motion's own FBX.

Finding (find_props). A prop file is an FBX whose name ends with a prop word: _Prop, _Props, _Prop2, _Prop_1
(a whole _part; "carry_proper" is not one). Its take is the name before that. A person FBX takes the prop files of
its own name; when there are none, those of its name without the last _part (pick_010_M1 -> pick_010; a number
is not dropped: jump_002). Searched: the person's folder, one and two folders up, and the prop folders (a name
with a prop word as a part: Prop_Raw, props) right under those. When the same file name turns up in several
folders (Prop_Raw, Prop_Clean), the one whose other name parts match the person's folders (Takes_Clean -> Prop_Clean)
is used, else the nearest; the others are reported as skipped. A file that holds a person's skeleton is skipped,
not used. Motion lists (library, batch) leave out a prop file in a prop folder, or next to its take's people
(<take>.fbx, or <take>_<actor>.fbx with an actor-like part: M1, A2, P01, actor3), see is_prop_file.

Nodes (prop_nodes). The file's bones, empties and meshes, minus: end sites (a leaf bone named ..._End, ...End,
...Nub that stays rigid on its parent), grouping nodes (an empty, or a bone named like its whole prop, that has
children, never moves and has no markers or meshes of its own). A bone's prop is the subject it belongs to: the
part of its name before the last ":" ("Ball_1:root" -> Ball_1), or its own name when its children are named
"<it>:..." (a subject node), else the armature (in Blender's made-up "Armature" or one with several roots, the
bone's chain root). An empty or mesh under a prop node belongs to that prop (markers); one on its own is a prop of
its own full name. A prop of one segment is named after the prop ("Ball_1"), one of several "<prop>:<segment>"
("Bat_1:tip"), linked to the segment it hangs from; a marker is "<prop>:<marker>". A mesh on a node (skinned to
that bone, or a child of that bone or empty) takes the node's place, under the node's name.

Timing: both files keep the capture's clock: Blender places keys at frame = time x round(fps) (the importer's
integer rate, so 119.88 Hz files do not drift), and each motion frame takes the props' pose at its own time
(positions interpolated, rotations blended and re-orthonormalised; held outside the props' range, and the share of
motion frames inside that range is reported as overlap_pct when something moves). A file with several takes
(animation stacks) is read on the one whose name (a "|" part of it) equals the motion's take name, else the file's
first. Units: the motion's unit factor (the same capture).

Shapes, for a node without a mesh, from the first that applies:
- a shape file next to the data (SHAPE_FILES; nearest folder first from the prop file, then from the motion),
  YAML or JSON, lengths in cm, in the prop node's own frame (the FBX node's axes):
      Ball:  {shape: sphere, diameter: 7.4}
      Box:   {shape: box, size: [40, 30, 25], offset: [0, 0, 12.5]}
      Bat:   {shape: cylinder, diameter: 6, length: 84, axis: x, offset: [42, 0, 0]}
      Chair: {mesh: chair.obj, unit: m, rotate: [90, 0, 0]}     # obj / stl / ply / glb / gltf / off, next to it
  keyed by the prop's name ("Ball_1"), that name without its number ("Ball") or without a "Take:" namespace (these
  for the prop's first node only), and "<prop>:<segment>" for any segment ("Bat:tip");
- for the first node of a prop with "ball" in its name: a sphere BALL_DIAMETER_CM across (the default);
- else none: the node is drawn as its axes with a small dot and measured at its origin.
ObjectTrack.shape says which was used ("" only for a node without a shape).
"""

from __future__ import annotations

import functools
import json
import os
import re
import time

import numpy as np

from .motion import ObjectTrack, SkeletonMotion

SHAPE_FILES = ("props.yaml", "props.yml", "props.json")
BALL_DIAMETER_CM = 10.0
SHAPES = ("sphere", "box", "cylinder")
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001}
MESH_EXT = (".obj", ".stl", ".ply", ".glb", ".gltf", ".off")
PROP_WORD = re.compile(r"props?\d*")
ACTOR_WORD = re.compile(r"(?!v\d)[a-z]{1,3}\d{1,3}|actor\d*")
STATIC_M, STATIC_DEG = 0.001, 0.1  # a node that moves less than this over the take never moves


class PersonSkeleton(ValueError):
    """A prop file that holds a person's skeleton (a misnamed file next to the take): not used as props."""


# --------------------------------------------------------------------------- names and folders
@functools.lru_cache(maxsize=512)
def _listing(folder: str, stamp: int) -> tuple[tuple[str, bool], ...]:
    try:
        with os.scandir(folder) as it:
            return tuple(sorted((e.name, e.is_dir()) for e in it))
    except OSError:
        return ()


RECENT_NS = 2_000_000_000  # a folder changed this recently is listed again every time (_entries)


def _entries(folder: str) -> tuple[tuple[str, bool], ...]:
    """(name, is a folder) of a folder's entries, read again when the folder changes. Windows moves file times on in
    clock ticks (about 16 ms): a second file made in the same tick leaves the folder's time as it was, so a folder
    changed in the last RECENT_NS is not taken from the cache."""
    try:
        stamp = os.stat(folder).st_mtime_ns
    except OSError:
        return ()
    key = os.path.normcase(os.path.abspath(folder))
    if time.time_ns() - stamp < RECENT_NS:
        return _listing.__wrapped__(key, stamp)
    return _listing(key, stamp)


def _fbx_stems(folder: str) -> list[tuple[str, str]]:
    """(lower-case stem, path) of the FBX files in a folder."""
    return [(n[:-4].lower(), os.path.join(folder, n)) for n, d in _entries(folder) if not d and n.lower().endswith(".fbx")]


def _subfolders(folder: str) -> list[str]:
    return [os.path.join(folder, n) for n, d in _entries(folder) if d]


def _words(name: str) -> list[str]:
    return [t for t in re.split(r"[_\s.\-]+", name.lower()) if t]


def is_prop_folder(folder: str) -> bool:
    """A folder named with a prop word as a part (Prop_Raw, props, Props2; not "property")."""
    return any(PROP_WORD.fullmatch(t) for t in _words(os.path.basename(os.path.normpath(folder))))


def is_actor_word(part: str) -> bool:
    return bool(ACTOR_WORD.fullmatch(part.lower()))


def prop_head(stem: str) -> str | None:
    """The take of a file name that ends with a prop word (pick_010_Prop, pick_010_Prop_2 -> pick_010), lower
    case; None for other names. File names are split at "_" only."""
    parts = stem.lower().split("_")
    if len(parts) >= 2 and PROP_WORD.fullmatch(parts[-1]):
        return "_".join(parts[:-1])
    if len(parts) >= 3 and parts[-1].isdigit() and PROP_WORD.fullmatch(parts[-2]):
        return "_".join(parts[:-2])
    return None


def take_names(path: str) -> list[str]:
    """The takes a person file may belong to, tried in order (lower case): its own name, then that name without
    its last _part when that part is not a number."""
    stem = os.path.splitext(os.path.basename(path))[0]
    out = [stem.lower()]
    head, sep, last = stem.rpartition("_")
    if sep and head and not last.isdigit():
        out.append(head.lower())
    return out


def _search_folders(path: str) -> list[str]:
    """The person's folder, one and two up, and the prop folders right under each."""
    ups = [os.path.dirname(os.path.abspath(path))]
    for _ in range(2):
        up = os.path.dirname(ups[-1])
        if up == ups[-1]:
            break
        ups.append(up)
    out, seen = [], set()
    for u in ups:
        for folder in [u] + [f for f in _subfolders(u) if is_prop_folder(f)]:
            key = os.path.normcase(folder)
            if key not in seen:
                seen.add(key)
                out.append(folder)
    return out


def _other_words(folder: str) -> set[str]:
    return {t for t in _words(os.path.basename(os.path.normpath(folder))) if not PROP_WORD.fullmatch(t)}


def find_props(path: str) -> tuple[list[str], list[dict]]:
    """(prop files of an FBX motion's take, files skipped as another copy [{"file", "skipped"}]): module notes."""
    if not path.lower().endswith(".fbx") or is_prop_file(path):
        return [], []
    me = os.path.normcase(os.path.abspath(path))
    folders = _search_folders(path)
    found: list[str] = []
    for take in take_names(path):
        found = [f for folder in folders for s, f in _fbx_stems(folder)
                 if prop_head(s) == take and os.path.normcase(f) != me]
        if found:
            break
    mine = set()
    folder = os.path.dirname(me)
    for _ in range(3):
        mine |= _other_words(folder)
        folder = os.path.dirname(folder)
    by_name: dict[str, list[str]] = {}
    for f in found:
        by_name.setdefault(os.path.basename(f).lower(), []).append(f)
    files, skipped = [], []
    for name in sorted(by_name):
        group = by_name[name]
        best = max(group, key=lambda f: (bool(_other_words(os.path.dirname(f)) & mine), -group.index(f)))
        files.append(best)
        skipped += [{"file": os.path.abspath(f), "skipped": f"같은 이름의 {os.path.basename(os.path.dirname(best))} 파일을 씀"}
                    for f in group if f is not best]
    return files, skipped


def prop_files(path: str) -> list[str]:
    """The prop files of an FBX motion's take (find_props)."""
    return find_props(path)[0]


def is_prop_file(path: str) -> bool:
    """A prop file left out of motion lists (library, batch): named as a prop and in a prop folder, or next to its
    take's people (<take>.fbx, or <take>_<actor>.fbx with an actor-like part)."""
    stem, ext = os.path.splitext(os.path.basename(path))
    s = stem.lower()
    head = prop_head(s)
    if ext.lower() != ".fbx" or head is None:
        return False
    folder = os.path.dirname(os.path.abspath(path))
    if is_prop_folder(folder):
        return True
    return any(o != s and (o == head or (o.startswith(head + "_") and is_actor_word(o[len(head) + 1:])))
               for o, _f in _fbx_stems(folder))


# --------------------------------------------------------------------------- shapes
def shape_file(*paths: str) -> str | None:
    """The nearest shape file (SHAPE_FILES) from each path's folder up two levels, in the order given."""
    for p in paths:
        folder = os.path.dirname(os.path.abspath(p))
        for _ in range(3):
            names = {n.lower(): n for n, d in _entries(folder) if not d}
            for want in SHAPE_FILES:
                if want in names:
                    return os.path.join(folder, names[want])
            up = os.path.dirname(folder)
            if up == folder:
                break
            folder = up
    return None


@functools.lru_cache(maxsize=16)
def _read_shapes(path: str, stamp: int) -> dict:
    with open(path, "rb") as f:
        raw = f.read()
    # UTF-8 with or without a BOM, else the Korean ANSI code page (Notepad, PowerShell 5.1), as label files are read
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")
    if path.lower().endswith(".json"):
        data = json.loads(text)
    else:
        import yaml

        data = yaml.safe_load(text)
    if isinstance(data, dict) and isinstance(data.get("props"), dict):
        data = data["props"]
    if not isinstance(data, dict):
        raise ValueError("이름: 모양 형식의 표가 아닙니다")
    return {str(k).lower(): v for k, v in data.items()}


def load_shapes(path: str) -> dict:
    """{name (lower case): spec} of a shape file (ValueError / OSError when it cannot be read)."""
    return _read_shapes(os.path.abspath(path), os.stat(path).st_mtime_ns)


def _base(name: str) -> str:
    """A name without its number: Ball_1 -> Ball, Box02 -> Box."""
    return re.sub(r"[_\s.-]*\d+$", "", name) or name


def shape_keys(prop: str, segment: str, first: bool, single: bool) -> list[str]:
    """Names a shape file may give a prop node under, most specific first (module notes)."""
    bare = prop.rsplit(":", 1)[-1]  # "Take:Ball_1" -> "Ball_1"
    props = list(dict.fromkeys([prop, _base(prop), bare, _base(bare)]))
    keys = [] if single else [f"{p}:{segment}" for p in props]
    if first:
        keys += props
    return list(dict.fromkeys(keys))


def _vec(spec: dict, key: str, n: int) -> np.ndarray:
    v = spec.get(key)
    try:
        v = np.asarray(v, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        v = np.zeros(0)
    if v.shape != (n,) or not np.isfinite(v).all():
        raise ValueError(f"{key}는 숫자 {n}개여야 합니다")
    return v


def _positive(spec: dict, key: str) -> float:
    v = spec.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
        raise ValueError(f"{key}(cm)는 0보다 큰 숫자여야 합니다")
    return float(v)


def make_shape(spec, base_dir: str) -> tuple[np.ndarray, np.ndarray, str]:
    """(vertices (V, 3) m, faces (F, 3), short description) of a shape spec (module notes). ValueError says what
    is wrong with it."""
    import trimesh

    if not isinstance(spec, dict):
        raise ValueError("모양은 {shape: ..., ...} 형식이어야 합니다")
    unknown = set(spec) - {"shape", "diameter", "size", "length", "axis", "offset", "rotate", "mesh", "unit"}
    if unknown:
        raise ValueError(f"모르는 항목: {', '.join(sorted(map(str, unknown)))}")
    if "mesh" in spec:
        f = os.path.join(base_dir, str(spec["mesh"]))
        if not os.path.isfile(f):
            raise ValueError(f"메시 파일이 없습니다: {spec['mesh']}")
        if not f.lower().endswith(MESH_EXT):
            raise ValueError(f"메시 파일은 {', '.join(MESH_EXT)} 중 하나여야 합니다")
        unit = str(spec.get("unit", "m")).lower()
        if unit not in UNITS:
            raise ValueError("unit은 m, cm, mm 중 하나여야 합니다")
        mesh = trimesh.load(f, force="mesh")
        if not len(mesh.faces):
            raise ValueError(f"메시에 면이 없습니다: {spec['mesh']}")
        V, F = np.asarray(mesh.vertices, float) * UNITS[unit], np.asarray(mesh.faces, np.int64)
        text = f"메시 {os.path.basename(f)}"
    else:
        kind = str(spec.get("shape", "")).lower()
        if kind not in SHAPES:
            raise ValueError(f"shape는 {', '.join(SHAPES)} 중 하나여야 합니다(또는 mesh)")
        if kind == "sphere":
            d = _positive(spec, "diameter")
            m = trimesh.creation.icosphere(subdivisions=2, radius=d / 200.0)
            text = f"구 지름 {d:g} cm"
        elif kind == "box":
            size = _vec(spec, "size", 3)
            if not (size > 0).all():
                raise ValueError("size(cm)는 0보다 큰 숫자 3개여야 합니다")
            m = trimesh.creation.box(extents=size / 100.0)
            text = "상자 " + "×".join(f"{x:g}" for x in size) + " cm"
        else:
            d, length = _positive(spec, "diameter"), _positive(spec, "length")
            axis = str(spec.get("axis", "z")).lower()
            if axis not in ("x", "y", "z"):
                raise ValueError("axis는 x, y, z 중 하나여야 합니다")
            m = trimesh.creation.cylinder(radius=d / 200.0, height=length / 100.0, sections=24)
            if axis != "z":  # trimesh's cylinder runs along z
                turn = {"x": ([0, 1, 0], np.pi / 2), "y": ([1, 0, 0], -np.pi / 2)}[axis]
                m.apply_transform(trimesh.transformations.rotation_matrix(turn[1], turn[0]))
            text = f"원기둥 지름 {d:g} cm, 길이 {length:g} cm ({axis}축)"
        V, F = np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)
    if "rotate" in spec:
        from scipy.spatial.transform import Rotation

        V = V @ Rotation.from_euler("xyz", _vec(spec, "rotate", 3), degrees=True).as_matrix().T
    if "offset" in spec:
        V = V + _vec(spec, "offset", 3) / 100.0
    return V, F, text


def shape_mesh_files(path: str) -> list[str]:
    """The mesh files a shape file's specs name (for result caches); [] when it cannot be read."""
    try:
        shapes = load_shapes(path)
    except Exception:
        return []
    return sorted({os.path.join(os.path.dirname(os.path.abspath(path)), str(s["mesh"])) for s in shapes.values()
                   if isinstance(s, dict) and "mesh" in s})


# --------------------------------------------------------------------------- timing
def _orthonormal(M: np.ndarray) -> np.ndarray:
    U, _, Vt = np.linalg.svd(M)
    D = np.ones(M.shape[:-1])
    D[..., -1] = np.sign(np.linalg.det(U @ Vt))
    return (U * D[..., None, :]) @ Vt


def resample_pose(mats: np.ndarray, t_src: np.ndarray, t_dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Positions (T', 3) and rotations (T', 3, 3) of world matrices (T, 4, 4) sampled at times t_src, at times t_dst:
    positions linear, rotations blended and made orthonormal again; held outside t_src."""
    P, R = mats[:, :3, 3], _orthonormal(mats[:, :3, :3])
    if len(t_src) < 2:
        return np.repeat(P[:1], len(t_dst), 0), np.repeat(R[:1], len(t_dst), 0)
    x = np.clip(t_dst, t_src[0], t_src[-1])
    i = np.clip(np.searchsorted(t_src, x, side="right") - 1, 0, len(t_src) - 2)
    w = ((x - t_src[i]) / np.maximum(t_src[i + 1] - t_src[i], 1e-12))[:, None]
    P_out = (1 - w) * P[i] + w * P[i + 1]
    R_out = _orthonormal((1 - w[..., None]) * R[i] + w[..., None] * R[i + 1])
    return P_out, R_out


def key_rate(fps: float) -> float:
    """The rate Blender's importer placed an FBX's keys at: its integer scene rate."""
    return float(max(1, round(fps)))


def motion_times(human: SkeletonMotion) -> np.ndarray:
    """The capture time (s) of each frame of an FBX motion: (first frame number + dropped frames + i) / key rate."""
    m = human.meta
    rate = key_rate(float(m.get("file_fps") or human.fps))
    return (int(m.get("frame_start", 0)) + int(m.get("dropped_frames", 0)) + np.arange(human.num_frames)) / rate


def _still(mats: np.ndarray) -> bool:
    """World matrices (T, 4, 4) that never move (less than STATIC_M / STATIC_DEG from the first)."""
    P, R = mats[:, :3, 3], _orthonormal(mats[:, :3, :3])
    turn = np.einsum("ij,tij->t", R[0], R)
    return bool(np.nanmax(np.linalg.norm(P - P[0], axis=1)) < STATIC_M
                and np.nanmin(turn) > 1 + 2 * np.cos(np.radians(STATIC_DEG)))


def _rigid_on(child: np.ndarray, parent: np.ndarray) -> bool:
    """A node that keeps its place on its parent over the take."""
    rel = np.linalg.inv(parent) @ child
    return _still(rel)


def _end_name(name: str) -> bool:
    seg = name.rsplit(":", 1)[-1]
    low = seg.lower()
    return seg.endswith(("End", "Nub")) or low.endswith(("_end", " end", "_nub", " nub", "end site")) or low in ("end", "nub")


# --------------------------------------------------------------------------- tracks
def is_person(names: list[str], parents) -> bool:
    """Bones that make a person's skeleton: 8 or more, with the body parts the retarget finds by name."""
    if len(names) < 8:
        return False
    from .retarget import _resolve_bvh_bodies

    try:
        _resolve_bvh_bodies(list(names), np.asarray(parents, dtype=int))
    except ValueError:
        return False
    return True


def prop_nodes(raw: dict) -> list[dict]:
    """The props of a read_props dump (module notes): per node kept {"index", "name", "prop", "segment", "kind",
    "parent" (index into this list, -1), "first" (the prop's first node), "single", "mesh" (index of the raw node
    whose mesh it is, -1), "bind"}. PersonSkeleton when the file holds a person's skeleton."""
    objs = raw["objects"]
    n = len(objs)
    kids = [[] for _ in range(n)]
    for i, o in enumerate(objs):
        if 0 <= o["parent"] < n:
            kids[o["parent"]].append(i)
    # a person's skeleton is not a prop (a misnamed file next to the take)
    for group in sorted({o["group"] for o in objs if o["kind"] == "bone"}):
        bones = [i for i, o in enumerate(objs) if o["kind"] == "bone" and o["group"] == group]
        pos = {b: k for k, b in enumerate(bones)}
        if is_person([objs[b]["name"] for b in bones], [pos.get(objs[b]["parent"], -1) for b in bones]):
            raise PersonSkeleton(f"사람 골격({group}, 관절 {len(bones)}개)이라 물체로 쓰지 않음")

    def subject(i: int) -> bool:  # a bone whose child bones are named "<it>:..." (a subject node, Ball_1 > Ball_1:root)
        o = objs[i]
        return o["kind"] == "bone" and any(objs[k]["kind"] == "bone" and objs[k]["name"].startswith(o["name"] + ":")
                                           for k in kids[i])

    keep = [True] * n
    for i, o in enumerate(objs):
        par = o["parent"]
        if o["kind"] == "bone" and not any(objs[k]["kind"] == "bone" for k in kids[i]) and _end_name(o["name"]) \
                and (par < 0 or _rigid_on(o["mats"], objs[par]["mats"])):
            keep[i] = False  # an end site: where the last segment ends
        elif o["kind"] in ("empty", "bone") and kids[i] and _still(o["mats"]) and (o["kind"] == "empty" or subject(i)) \
                and not any(objs[k]["kind"] in ("mesh", "empty") for k in kids[i]):
            keep[i] = False  # a grouping node: holds other props, never moves, no markers or meshes of its own
        elif o["kind"] == "empty" and o.get("children") and not kids[i] and _still(o["mats"]):
            keep[i] = False  # groups armatures (whose bones are tracks of their own) and never moves

    def up(i: int) -> int:
        p = objs[i]["parent"]
        while 0 <= p and not keep[p]:
            p = objs[p]["parent"]
        return p if 0 <= p < n else -1

    parent = [up(i) for i in range(n)]
    # a mesh on a node (skinned to that bone, or a child of that bone or empty) takes the node's place
    stand_in = {}
    for i, o in enumerate(objs):
        if keep[i] and o["kind"] == "mesh" and parent[i] >= 0 and objs[parent[i]]["kind"] != "mesh":
            stand_in.setdefault(parent[i], i)
    for node in stand_in:
        keep[node] = False
    owner = {mesh: node for node, mesh in stand_in.items()}

    def host(i: int) -> int:  # where the hierarchy now has node i: its stand-in mesh, else itself
        return stand_in.get(i, i)

    roots_of: dict[str, list[int]] = {}
    for i, o in enumerate(objs):
        if o["kind"] == "bone" and o["parent"] < 0:
            roots_of.setdefault(o["group"], []).append(i)

    def chain_root(i: int) -> int:
        while objs[i]["parent"] >= 0 and objs[objs[i]["parent"]]["kind"] == "bone":
            i = objs[i]["parent"]
        return i

    prop: dict[int, str] = {}

    def prop_of(i: int) -> str:  # i: an original node index (a stand-in mesh is asked for by its node)
        if i in prop:
            return prop[i]
        o = objs[i]
        if o["kind"] == "bone":
            if subject(i):
                p = o["name"]
            elif ":" in o["name"]:
                p = o["name"].rsplit(":", 1)[0]
            elif o["group"] in ("", "Armature") or len(roots_of.get(o["group"], [])) > 1:
                p = objs[chain_root(i)]["name"]
            else:
                p = o["group"]
        else:
            par = parent[i]
            p = prop_of(par) if par >= 0 else o["name"]
        prop[i] = p
        return p

    order = [i for i in range(n) if keep[i]]
    index = {i: k for k, i in enumerate(order)}
    nodes = []
    for i in order:
        src = owner.get(i, i)  # the node a stand-in mesh replaces
        par = parent[src]
        nodes.append({"index": i, "prop": prop_of(src), "segment": objs[src]["name"].rsplit(":", 1)[-1],
                      "kind": objs[src]["kind"], "parent": index.get(host(par), -1) if par >= 0 else -1,
                      "mesh": i if objs[i]["kind"] == "mesh" else -1, "bind": objs[i].get("bind", ""),
                      "own_mesh": objs[i]["kind"] == "mesh" and i not in owner})
    for nd in nodes:
        nd["first"] = nd["parent"] < 0 or nodes[nd["parent"]]["prop"] != nd["prop"]
    count: dict[str, int] = {}  # segments: a prop's bones and its first node (markers on it do not count)
    for nd in nodes:
        if nd["kind"] == "bone" or nd["first"]:
            count[nd["prop"]] = count.get(nd["prop"], 0) + 1
    for nd in nodes:
        nd["single"] = count.get(nd["prop"], 0) <= 1
        if nd["own_mesh"] and not nd["first"]:  # a mesh hanging on a prop: one of its parts
            nd["name"] = f"{nd['prop']}:{objs[nd['index']]['name']}"
        elif nd["own_mesh"]:  # a mesh prop of its own
            nd["name"] = objs[nd["index"]]["name"]
        elif nd["kind"] == "bone" or nd["first"]:  # a segment
            nd["name"] = nd["prop"] if nd["single"] else f"{nd['prop']}:{nd['segment']}"
        else:  # a marker on the prop
            nd["name"] = f"{nd['prop']}:{nd['segment']}"
    return nodes


def pick_take(takes: list[str], current: str, wants: list[str]) -> str | None:
    """The take (animation stack) of a prop file to read for a motion: one whose name, or a "|" part of it, equals
    one of the motion's take names (wants, in order), the one already read first; None when none does."""
    def parts(t: str) -> list[str]:
        return [t.lower()] + [p.strip().lower() for p in t.split("|")]

    for w in wants:
        if current and w in parts(current):
            return current
        for t in takes:
            if w in parts(t):
                return t
    return None


def prop_tracks(path: str, human: SkeletonMotion, offset: int = 0, shapes: dict | None = None,
                shapes_dir: str = "", info: dict | None = None) -> list[ObjectTrack]:
    """The props of a prop file as objects on the motion's frames (module notes). offset: how many objects the
    motion has before these (parents point into the motion's whole list). shapes: a shape file's table. info (filled
    when given): take, takes, overlap_pct."""
    from .io.fbx import read_props

    raw = read_props(path)
    if len(raw["takes"]) > 1:  # read the take named like the motion's, when there is one
        pick = pick_take(raw["takes"], raw["take"], take_names(human.source) if human.source else [])
        if pick and pick != raw["take"]:
            raw = read_props(path, take=pick)
    objs = raw["objects"]
    frames = len(objs[0]["mats"]) if objs else 0
    t_src = (raw["frame_start"] + np.arange(frames)) / key_rate(raw.get("key_fps") or raw["fps"])
    t_dst = motion_times(human)
    moving = frames > 1 and any(not _still(o["mats"]) for o in objs)
    if info is not None:
        step = 1.0 / key_rate(raw.get("key_fps") or raw["fps"])  # within a prop frame of its range counts as inside
        info.update(take=raw.get("take") or None, takes=raw["takes"] if len(raw["takes"]) > 1 else None,
                    overlap_pct=round(100 * float(np.mean((t_dst >= t_src[0] - step) & (t_dst <= t_src[-1] + step))), 1)
                    if moving else None)  # (props that never move are the same at any time)
    s = float(human.meta.get("unit_scale", 1.0))
    ground = float(human.meta.get("ground_offset_m", 0.0))
    out = []
    for nd in prop_nodes(raw):
        o = objs[nd["index"]]
        P, R = resample_pose(o["mats"], t_src, t_dst)
        V, F, shape = node_shape(nd, o, s, shapes, shapes_dir)
        out.append(ObjectTrack(name=nd["name"], kind=nd["kind"], positions=P * s - [0.0, 0.0, ground], rotations=R,
                               vertices=V, faces=F, source=os.path.abspath(path), group=nd["prop"],
                               parent=offset + nd["parent"] if nd["parent"] >= 0 else -1, shape=shape))
    return out


def node_shape(nd: dict, o: dict, s: float, shapes: dict | None, shapes_dir: str) -> tuple[np.ndarray, np.ndarray, str]:
    """(vertices (V, 3) m, faces, ObjectTrack.shape) of a prop node of prop_nodes (module notes, Shapes); o: its raw
    node, s: the motion's unit factor."""
    V, F, shape = np.asarray(o["vertices"], float), np.asarray(o["faces"], np.int64), ""
    if len(F):  # the file's own mesh, in the node's frame at its world scale
        V = V * np.linalg.norm(o["mats"][0, :3, :3], axis=0) * s
        shape = "파일의 메시" + (f" {o['name']}" if o["name"] != nd["name"] else "") + (" (뼈에 고정)" if nd["bind"] else "")
        return V, F, shape
    keys = shape_keys(nd["prop"], nd["segment"], nd["first"], nd["single"])
    spec = next((shapes[k.lower()] for k in keys if shapes and k.lower() in shapes), None)
    if spec is not None:
        try:
            V, F, text = make_shape(spec, shapes_dir)
            shape = text + " (모양 파일)"
        except Exception as e:
            shape = f"모양 파일 오류: {e}"
            V, F = np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    if not len(F) and nd["first"] and "ball" in nd["prop"].lower():
        V, F, _ = make_shape({"shape": "sphere", "diameter": BALL_DIAMETER_CM}, "")
        shape = (shape + "; " if shape else "") + f"구 지름 {BALL_DIAMETER_CM:g} cm (기본값)"
    return V, F, shape


def attach(human: SkeletonMotion, files: list[str] | None = None) -> SkeletonMotion:
    """Add the prop files' props (find_props of the motion's FBX, or `files`) to an FBX motion's objects. What was
    read goes to human.meta["props"]: [{"file", "objects" | "error" | "skipped", "shapes", "shapes_error", "take",
    "takes", "overlap_pct"}]."""
    if human.meta.get("format") != "fbx" or not human.source:
        return human
    skipped = []
    if files is None:
        files, skipped = find_props(human.source)
    report = []
    for f in files:
        entry = {"file": os.path.abspath(f)}
        shapes, sdir, sfile = None, "", shape_file(f, human.source)
        if sfile:
            entry["shapes"] = sfile
            try:
                shapes, sdir = load_shapes(sfile), os.path.dirname(sfile)
            except Exception as e:
                entry["shapes_error"] = f"{type(e).__name__}: {e}"
        info: dict = {}
        try:
            tracks = prop_tracks(f, human, offset=len(human.objects), shapes=shapes, shapes_dir=sdir, info=info)
        except PersonSkeleton as e:  # a person's file named like a prop: not an error to try again
            entry["skipped"] = str(e)
        except Exception as e:  # the motion still opens without them
            entry["error"] = f"{type(e).__name__}: {e}"
        else:
            human.objects.extend(tracks)
            entry["objects"] = [t.name for t in tracks]
            entry.update({k: v for k, v in info.items() if v is not None})
        report.append(entry)
    report += skipped
    if report:
        human.meta["props"] = report
    return human


def signature(path: str) -> list | None:
    """What the props drawn with a motion depend on (its prop files, their shape files and the meshes those name, and
    the motion's own shape file), for result caches; None when it has none."""
    files = prop_files(path)
    own = shape_file(path)  # shapes of props written as skeletons inside the motion's FBX (retlens.io.fbx)
    if not files and not own:
        return None
    deps = list(files)
    for sf in sorted({x for x in [*(shape_file(f, path) for f in files), own] if x}):
        deps += [sf] + shape_mesh_files(sf)
    sig = []
    for f in deps:
        try:
            st = os.stat(f)
            sig.append([os.path.abspath(f), st.st_size, st.st_mtime_ns])
        except OSError:
            sig.append([os.path.abspath(f), None, None])
    return sig
