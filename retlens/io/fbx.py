"""FBX skeletal animation reader (through Blender's FBX importer).

FBX is the native export of MotionBuilder, Vicon Shogun, OptiTrack Motive, Xsens
MVN, Rokoko, 3ds Max (Biped) and of Blender / game-engine pipelines (Mixamo, the
CMU-to-FBX conversions). The format is proprietary; Blender's importer (pre/post rotations,
pivots, rotation orders, units, axes, takes) is the reader here: Blender runs
headless with blender_fbx_script.py and dumps the armature's world joint
matrices per frame (about 2 s per clip). Dumps are cached in data/cache/fbx/.

Blender is found through RetLens's 환경 설정, then $BLENDER, then
C:\\blender\\*\\blender.exe, then PATH (retlens.settings.find_blender).
The ufbx Python binding was tried first and dropped: its 0.0.5 wheel crashes and returns
wrong parents on plain node access.

The armature's rest pose is the "rest" pose of the clip. Blender and most mocap
exporters write the skeleton's T-pose there; when a file does not, retargeting
can take a frame of the clip instead (``--ref``).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import threading

import numpy as np

from .. import paths
from ..motion import ObjectTrack, SkeletonMotion
from .bvh import cmu_capture_fps

CACHE_DIR = paths.cache_dir("fbx")  # dev: data/cache/fbx
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_fbx_script.py")  # Blender runs this file
SCRIPT_VERSION = 3  # = blender_fbx_script.VERSION; bump to invalidate cached dumps
PROPS_VERSION = 3  # = blender_fbx_script.PROPS_VERSION (read_props)
_DUMP_LOCKS: dict[str, threading.Lock] = {}  # one Blender run per dump at a time in this process
_DUMP_LOCKS_GUARD = threading.Lock()

# Extra factors to meters: files whose numbers are 100x off (centimetre values in a
# meter scene, e.g. a BVH imported into Blender at scale 1) or in inches.
_SCALES = tuple(b * 10.0 ** k for b in (1.0, 0.0254) for k in range(-4, 3))
# cgspeed CMU BVHs (and conversions of them) claim 120 Hz for every trial.
_CGSPEED_FPS = 120.0


def find_blender() -> str:
    """blender.exe: 환경 설정, then $BLENDER, then C:\\blender\\*\\blender.exe, then PATH."""
    from .. import settings

    found = settings.find_blender(settings.load(reload=True))
    if found.path is None:
        raise FileNotFoundError(f"FBX를 읽으려면 Blender 4.5 LTS가 필요합니다: {found.problem}. RetLens의 '파일 > 환경 설정'에서 "
                                "blender.exe를 지정하거나, C:\\blender에 풀거나, BLENDER=<blender.exe 경로>를 설정하세요")
    return found.path


def run_blender(*args: str, timeout: float = 1800) -> str:
    """Run blender_fbx_script.py in a headless Blender; returns its log, raises on failure (ValueError saying what
    is wrong with the file when the importer says so: ASCII FBX, empty, damaged)."""
    cmd = [find_blender(), "-b", "--factory-startup", "--python-exit-code", "2", "--python", SCRIPT, "--", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console flash
    log = "\n".join(line for line in (r.stdout + r.stderr).splitlines() if "[blender_fbx]" in line or "Error" in line)
    if r.returncode != 0:
        raise _blender_error(args, r.returncode, log or r.stdout[-2000:] + r.stderr[-2000:])
    return log


def _blender_error(args: tuple, code: int, log: str) -> Exception:
    """The error of a failed Blender run on args (mode, input, ...): the importer's known complaints about the
    input file as a short ValueError, else Blender's log (each line once) without the cache file paths."""
    src = args[1] if len(args) > 1 else ""
    name = os.path.basename(src) or "?"
    if "ASCII FBX files are not supported" in log:
        try:
            empty = os.path.getsize(src) == 0
        except OSError:
            empty = False
        return ValueError(f"{name}: 빈 파일입니다" if empty else
                          f"{name}: ASCII FBX는 읽지 못합니다. 만든 프로그램에서 바이너리 FBX로 다시 내보내세요")
    if any(k in log for k in ("Couldn't open file", "failed to read", "Invalid FBX", "Not an FBX")):
        return ValueError(f"{name}: FBX 파일이 손상되었거나 잘렸습니다")
    lines = []
    for line in log.splitlines():
        for a in args[2:]:  # the cache's temporary output file
            line = line.replace(a, os.path.basename(a))
        if line.strip() and line not in lines:
            lines.append(line)
    return RuntimeError(f"{name}: Blender로 처리하지 못했습니다 (종료 코드 {code}, {args[0] if args else '?'}):\n"
                        + "\n".join(lines))


def _file_key(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _orthonormal(M: np.ndarray) -> np.ndarray:
    """Rotation part of (..., 3, 3) matrices that may carry scale."""
    if M.size == 0:
        return np.array(M, dtype=np.float64)
    U, _, Vt = np.linalg.svd(M)
    D = np.ones(M.shape[:-1])
    D[..., -1] = np.sign(np.linalg.det(U @ Vt))
    return (U * D[..., None, :]) @ Vt


def _dumped(mode: str, path: str, version: int, take: str | None, cache: bool) -> str:
    """The cached Blender dump of `path` (made when missing)."""
    path = os.path.abspath(path)
    if os.path.getsize(path) == 0:  # (Blender would call it an ASCII FBX)
        raise ValueError(f"{os.path.basename(path)}: 빈 파일입니다")
    stem = os.path.splitext(os.path.basename(path))[0][:48]  # the file key tells files apart; long names hit MAX_PATH
    tag = (f"{stem}-{_file_key(path)}-{'props-' if mode == 'props' else ''}v{version}"
           + (f"-{hashlib.sha1(take.encode()).hexdigest()[:8]}" if take else ""))
    out = os.path.join(CACHE_DIR, tag + ".npz")
    if cache and os.path.isfile(out):
        return out
    with _DUMP_LOCKS_GUARD:
        lock = _DUMP_LOCKS.setdefault(os.path.normcase(out), threading.Lock())
    with lock:  # two motions of a take open together share its prop file: one Blender run, the other waits
        if cache and os.path.isfile(out):
            return out
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=tag[:40] + ".", suffix=".tmp.npz")  # own file per run
        os.close(fd)
        try:
            run_blender(mode, path, tmp, *([take] if take else []))
            try:
                os.replace(tmp, out)
            except OSError:  # another process wrote it meanwhile (or has it open): use theirs
                if not os.path.isfile(out):
                    raise
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return out


def _dumped_objects(d) -> list[dict]:
    objects = []
    if "obj_names" not in d:
        return objects
    vs, fs = d["obj_vert_start"], d["obj_face_start"]
    for i, name in enumerate(d["obj_names"]):
        o = {"name": str(name), "kind": str(d["obj_kinds"][i]), "mats": d["obj_mats"][:, i],
             "vertices": d["obj_verts"][vs[i]:vs[i + 1]], "faces": d["obj_faces"][fs[i]:fs[i + 1]]}
        if "obj_groups" in d:  # read_props
            o.update(group=str(d["obj_groups"][i]), parent=int(d["obj_parents"][i]), bind=str(d["obj_binds"][i]),
                     children=int(d["obj_children"][i]), below_mesh=bool(d["obj_below_mesh"][i]))
        objects.append(o)
    return objects


def read_fbx(path: str, take: str | None = None, cache: bool = True) -> dict:
    """Raw armature animation of an FBX file in Blender's frame (Z-up, file scale).

    Returns joint (bone) names, parents, world positions (T, J, 3) and frames
    (T, J, 3, 3), the rest pose of the same, the frame rate, the first frame's number and the takes,
    the objects: [{"name", "kind", "mats" (T, 4, 4) world matrices, "vertices", "faces"} (mesh in
    its own frame)], the armature read ("armature") and the bones of the file's other armatures
    ("other_bones": [{"name", "kind" "bone", "group" (its armature), "parent" (index in the list, -1),
    "children", "animated", "mats" (T, 4, 4)}]). A file without an armature gives no joints.
    """
    out = _dumped("dump", path, SCRIPT_VERSION, take, cache)
    with np.load(out, allow_pickle=False) as d:
        mats, rest = d["mats"], d["rest"]
        other = []
        if "xb_names" in d:
            xm = d["xb_mats"]
            other = [{"name": str(n), "kind": "bone", "group": str(d["xb_groups"][i]), "parent": int(d["xb_parents"][i]),
                      "children": int(d["xb_children"][i]), "animated": bool(d["xb_animated"][i]), "bind": "",
                      "below_mesh": False, "mats": xm[:, i], "vertices": np.zeros((0, 3)),
                      "faces": np.zeros((0, 3), dtype=np.int64)} for i, n in enumerate(d["xb_names"])]
        return {
            "names": [str(n) for n in d["names"]],
            "parents": d["parents"].astype(int),
            "positions": mats[..., :3, 3],
            "frames": _orthonormal(mats[..., :3, :3]),
            "rest_positions": rest[:, :3, 3],
            "rest_frames": _orthonormal(rest[:, :3, :3]),
            "fps": float(d["fps"]),
            "frame_start": int(d["frame_start"]),
            "take": str(d["take"]),
            "takes": [str(t) for t in d["takes"]],
            "reader": f"Blender {d['blender']} FBX importer",
            "cache": out,
            "objects": _dumped_objects(d),
            "armature": str(d["armature"]) if "armature" in d else "",
            "other_bones": other,
        }


def read_props(path: str, take: str | None = None, cache: bool = True) -> dict:
    """Every node of a props-only FBX (blender_fbx_script dump_props), raw, in Blender's frame (Z-up, file scale):
    {"fps", "key_fps" (frame number / key_fps = file time), "frame_start", "take" (the stack sampled), "takes",
    "objects": [{"name", "kind" ("bone" | "empty" | "mesh"), "group" (a bone's armature, or the armature a node
    hangs on), "parent" (index in objects, -1), "bind", "children", "below_mesh", "mats" (T, 4, 4), "vertices",
    "faces"}]}. take: the animation stack to sample (default: the file's first)."""
    out = _dumped("props", path, PROPS_VERSION, take, cache)
    with np.load(out, allow_pickle=False) as d:
        return {"fps": float(d["fps"]), "key_fps": float(d["key_fps"]), "frame_start": int(d["frame_start"]),
                "objects": _dumped_objects(d), "take": str(d["take"]), "takes": [str(t) for t in d["takes"]],
                "reader": f"Blender {d['blender']} FBX importer", "cache": out}


def _auto_scale(rest_positions: np.ndarray) -> float:
    """Factor that makes the rest-pose extent (~ height / arm span) plausible."""
    extent = float(np.max(np.ptp(rest_positions, axis=0)))
    if extent <= 0 or 1.0 <= extent <= 2.4:
        return 1.0
    return min(_SCALES, key=lambda s: abs(np.log(extent * s / 1.7)))


def _frame0_is_rest(frames: np.ndarray, rest_frames: np.ndarray, tol_deg: float = 1.0) -> bool:
    """Frame 0 is the rest pose (the T-pose cgspeed inserts) and frame 1 is not."""
    if len(frames) < 2:
        return False

    def same(k: int) -> float:
        rel = np.einsum("jba,jbc->jac", rest_frames, frames[k])  # rest^T @ frame
        cos = np.clip((np.trace(rel, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
        return float(np.mean(np.degrees(np.arccos(cos)) < tol_deg))

    return same(0) > 0.9 and same(1) < 0.5


def load_fbx(
    path: str,
    scale: float | str = "auto",
    ground: bool = False,
    with_rotations: bool = False,
    drop_tpose: bool | str = "auto",
    fps: float | str = "auto",
    take: str | None = None,
) -> SkeletonMotion:
    """Load an FBX skeleton animation as world joint positions (Z-up, meters).

    Args:
        scale: multiplier to meters, or "auto" (1, unless the rest pose is not
            human-sized; then the power of ten / inch factor that makes it so).
        ground: shift vertically so the lowest point over the clip sits on z=0.
        with_rotations: also fill ``rotations`` with the world joint frames.
        drop_tpose: drop frame 0 when it is the rest pose and the motion starts at
            frame 1 (cgspeed CMU lineage): "auto", True or False.
        fps: frame rate. "auto" = the file's, except conversions of cgspeed CMU
            BVHs of 60 Hz trials, which keep cgspeed's 120 Hz time base.
        take: take (animation stack / action) name; default the armature's own.
    meta["rest_pose"] = (positions (J, 3), frames (J, 3, 3)) in the same frame. A file of several armatures
    shows the animated one with the most bones; the others are props (_other_armatures) or, when a person's,
    left out with meta["warnings"] saying so.
    """
    raw = read_fbx(path, take=take)
    stem = os.path.splitext(os.path.basename(path))[0]
    if not raw["names"]:
        raise ValueError(f"{os.path.basename(path)}: FBX에 골격(armature)이 없습니다. 물체만 든 파일이면 같은 촬영의 사람 "
                         "모션 FBX를 여세요. 이름이 규칙에 맞으면 함께 그립니다(사용 설명서 '따로 받은 물체 FBX')")
    tpose0 = _frame0_is_rest(raw["frames"], raw["rest_frames"])
    file_fps = raw["fps"]
    if abs(file_fps - round(file_fps)) < 1e-4 * file_fps:  # 120.0048 from a rounded BVH frame time
        file_fps = float(round(file_fps))
    fps_out, fps_note = file_fps, ""
    if fps != "auto" and fps is not None:
        fps_out, fps_note = float(fps), "given by the caller"
    elif tpose0:
        true_fps, why = cmu_capture_fps(stem)
        if true_fps and abs(true_fps - _CGSPEED_FPS) > 1.0:
            fps_out = file_fps * true_fps / _CGSPEED_FPS
            fps_note = (f"conversion of a cgspeed CMU BVH: its time base assumes {_CGSPEED_FPS:.0f} Hz but the trial "
                        f"was captured at {true_fps:g} Hz ({why}), so the file's {file_fps:g} fps are {fps_out:g} fps")
    dropped = 1 if (drop_tpose is True or (drop_tpose == "auto" and tpose0)) and len(raw["positions"]) > 1 else 0

    s = _auto_scale(raw["rest_positions"]) if scale == "auto" else float(scale)
    pos = raw["positions"][dropped:] * s
    rest_pos = raw["rest_positions"] * s
    ground_offset = 0.0
    if ground and np.isfinite(pos).any():
        ground_offset = float(np.nanmin(pos[..., 2]))
        pos = pos - [0.0, 0.0, ground_offset]
        rest_pos = rest_pos - [0.0, 0.0, ground_offset]
    objects = [_object_track(o, s, dropped, ground_offset) for o in raw.get("objects", [])]
    extra, warnings = _other_armatures(raw, path, s, dropped, ground_offset, len(objects))
    objects += extra
    meta_extra = {"warnings": warnings} if warnings else {}
    return SkeletonMotion(
        name=stem,
        joint_names=raw["names"],
        parents=raw["parents"],
        positions=pos,
        fps=fps_out,
        source=os.path.abspath(path),
        kind="skeleton",
        meta={"format": "fbx", "unit_scale": s, "ground_offset_m": ground_offset, "tpose_frame0": tpose0,
              "dropped_frames": dropped, "file_fps": file_fps, "frame_start": raw["frame_start"],
              "fps_note": fps_note, "take": raw["take"],
              "takes": raw["takes"], "reader": raw["reader"], "rest_pose": (rest_pos, raw["rest_frames"]), **meta_extra},
        rotations=raw["frames"][dropped:] if with_rotations else None,
        objects=objects,
    )


def _other_armatures(raw: dict, path: str, s: float, dropped: int, ground_offset: float,
                     offset: int) -> tuple[list[ObjectTrack], list[str]]:
    """(objects, warnings) of the file's other armatures (read_fbx "other_bones"). Another person's skeleton is not
    read: a warning says which one is shown. An animated armature of fewer than 8 bones that is not a person (a prop a
    mocap system wrote as a skeleton: "Ball_1" > "Ball_1:root") gives props, its bones made objects as retlens.props
    makes those of a prop file (end sites and grouping nodes left out, shapes from a shape file or a ball's default);
    a bigger one is left out with a warning (a face or helper rig, or a person named in a way the retarget does not
    know: its bones are no objects for the hands to touch)."""
    bones = raw.get("other_bones") or []
    if not bones:
        return [], []
    from .. import props

    groups: dict[str, list[int]] = {}
    for i, b in enumerate(bones):
        groups.setdefault(b["group"], []).append(i)
    people, rigs, keep = [], [], []
    for g, idx in groups.items():
        pos = {b: k for k, b in enumerate(idx)}
        if props.is_person([bones[i]["name"] for i in idx], [pos.get(bones[i]["parent"], -1) for i in idx]):
            people.append(f"{g}(관절 {len(idx)}개)")
        elif not bones[idx[0]]["animated"]:  # a still helper rig (camera, face) is no prop
            continue
        elif len(idx) >= 8:  # many bones not named like a person's (a face or helper rig): no props of it either
            rigs.append(f"{g}(관절 {len(idx)}개)")
        else:
            keep += idx
    warnings = []
    if people:
        warnings.append(f"이 파일에는 사람 골격이 {len(people) + 1}개 있어 {raw.get('armature') or '첫 골격'}"
                        f"(관절 {len(raw['names'])}개)만 엽니다. 열지 않은 골격: {', '.join(people)}")
    if rigs:
        warnings.append(f"사람 골격으로도 물체로도 보지 않아 열지 않은 골격: {', '.join(rigs)}")
    if not keep:
        return [], warnings
    pos = {b: k for k, b in enumerate(keep)}
    objs = [{**bones[i], "parent": pos.get(bones[i]["parent"], -1), "mats": bones[i]["mats"][dropped:]} for i in keep]
    shapes, sdir, sfile = None, "", props.shape_file(path)
    if sfile:
        try:
            shapes, sdir = props.load_shapes(sfile), os.path.dirname(sfile)
        except Exception as e:  # the props still show, without its shapes
            warnings.append(f"물체 모양 파일 {os.path.basename(sfile)}을(를) 읽지 못함: {type(e).__name__}: {e}")
    out = []
    for nd in props.prop_nodes({"objects": objs}):
        o = objs[nd["index"]]
        M = o["mats"]
        V, F, shape = props.node_shape(nd, o, s, shapes, sdir)
        out.append(ObjectTrack(name=nd["name"], kind=nd["kind"], positions=M[:, :3, 3] * s - [0.0, 0.0, ground_offset],
                               rotations=_orthonormal(M[:, :3, :3]), vertices=V, faces=F, source=os.path.abspath(path),
                               group=nd["prop"], parent=offset + nd["parent"] if nd["parent"] >= 0 else -1, shape=shape))
    return out, warnings


def _object_track(o: dict, s: float, dropped: int, ground_offset: float) -> ObjectTrack:
    """An object of read_fbx in the skeleton's units and frames: its world matrices split into origin and
    rotation, its mesh scaled by its (first frame's) world scale, all times the skeleton's unit factor."""
    M = o["mats"][dropped:]
    scale = np.linalg.norm(M[0, :3, :3], axis=0)  # column norms: the object's own axis scales
    return ObjectTrack(name=o["name"], kind=o["kind"], positions=M[:, :3, 3] * s - [0.0, 0.0, ground_offset],
                       rotations=_orthonormal(M[:, :3, :3]), vertices=o["vertices"] * scale * s,
                       faces=np.asarray(o["faces"], dtype=np.int64))


def bvh_to_fbx(bvh: str, out: str, scale: float | str = "auto") -> str:
    """Convert a BVH to FBX with Blender (armature only, every frame baked).

    scale: BVH units -> meters ("auto": the same guess as retlens.io.load_bvh),
    so the FBX is human-sized. The BVH's frame rate is kept as is (cgspeed CMU
    files keep their 120 Hz claim, as other conversions of them do).
    """
    if scale == "auto":
        from .bvh import load_bvh

        scale = load_bvh(bvh, drop_tpose=False, fps=1.0).meta["unit_scale"]
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    run_blender("bvh2fbx", os.path.abspath(bvh), os.path.abspath(out), repr(float(scale)))
    return out
