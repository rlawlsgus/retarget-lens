"""FBX skeletal animation reader (through Blender's FBX importer).

FBX is the native export of MotionBuilder, Vicon Shogun, OptiTrack Motive, Xsens
MVN, Rokoko and of Blender / game-engine pipelines (Mixamo, the CMU-to-FBX
conversions). The format is proprietary; Blender's importer (pre/post rotations,
pivots, rotation orders, units, axes, takes) is the reader here: Blender runs
headless with blender_fbx_script.py and dumps the armature's world joint
matrices per frame (about 2 s per clip). Dumps are cached in data/cache/fbx/.

Blender is found through $BLENDER, then C:\\blender\\*\\blender.exe, then PATH
(see requirements.md). The ufbx Python binding was tried first and dropped: its
0.0.5 wheel crashes and returns wrong parents on plain node access.

The armature's rest pose is the "rest" pose of the clip. Blender and most mocap
exporters write the skeleton's T-pose there; when a file does not, retargeting
can take a frame of the clip instead (``--ref``).
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess

import numpy as np

from ..motion import SkeletonMotion
from .bvh import cmu_capture_fps

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CACHE_DIR = os.path.join(ROOT, "data", "cache", "fbx")
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_fbx_script.py")
SCRIPT_VERSION = 1  # = blender_fbx_script.VERSION; bump to invalidate cached dumps

# Extra factors to meters: files whose numbers are 100x off (centimetre values in a
# meter scene, e.g. a BVH imported into Blender at scale 1) or in inches.
_SCALES = tuple(b * 10.0 ** k for b in (1.0, 0.0254) for k in range(-4, 3))
# cgspeed CMU BVHs (and conversions of them) claim 120 Hz for every trial.
_CGSPEED_FPS = 120.0


def find_blender() -> str:
    cands = [os.environ.get("BLENDER", "")]
    cands += sorted(glob.glob(r"C:\blender\*\blender.exe"), reverse=True)
    cands.append(shutil.which("blender") or "")
    for c in cands:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError("FBX needs Blender 4.5 LTS: unzip it to C:\\blender or set BLENDER=<path to blender.exe> "
                            "(see requirements.md)")


def run_blender(*args: str, timeout: float = 1800) -> str:
    """Run blender_fbx_script.py in a headless Blender; returns its log, raises on failure."""
    cmd = [find_blender(), "-b", "--factory-startup", "--python-exit-code", "2", "--python", SCRIPT, "--", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    log = "\n".join(line for line in (r.stdout + r.stderr).splitlines() if "[blender_fbx]" in line or "Error" in line)
    if r.returncode != 0:
        raise RuntimeError(f"Blender failed ({r.returncode}) on {args}:\n{log or r.stdout[-2000:] + r.stderr[-2000:]}")
    return log


def _file_key(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _orthonormal(M: np.ndarray) -> np.ndarray:
    """Rotation part of (..., 3, 3) matrices that may carry scale."""
    U, _, Vt = np.linalg.svd(M)
    D = np.ones(M.shape[:-1])
    D[..., -1] = np.sign(np.linalg.det(U @ Vt))
    return (U * D[..., None, :]) @ Vt


def read_fbx(path: str, take: str | None = None, cache: bool = True) -> dict:
    """Raw armature animation of an FBX file in Blender's frame (Z-up, file scale).

    Returns joint (bone) names, parents, world positions (T, J, 3) and frames
    (T, J, 3, 3), the rest pose of the same, the frame rate and the takes.
    """
    path = os.path.abspath(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    tag = f"{stem}-{_file_key(path)}-v{SCRIPT_VERSION}" + (f"-{take}" if take else "")
    out = os.path.join(CACHE_DIR, tag + ".npz")
    if not (cache and os.path.isfile(out)):
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = out[:-4] + ".tmp.npz"
        run_blender("dump", path, tmp, *( [take] if take else []))
        os.replace(tmp, out)
    with np.load(out, allow_pickle=False) as d:
        mats, rest = d["mats"], d["rest"]
        return {
            "names": [str(n) for n in d["names"]],
            "parents": d["parents"].astype(int),
            "positions": mats[..., :3, 3],
            "frames": _orthonormal(mats[..., :3, :3]),
            "rest_positions": rest[:, :3, 3],
            "rest_frames": _orthonormal(rest[:, :3, :3]),
            "fps": float(d["fps"]),
            "take": str(d["take"]),
            "takes": [str(t) for t in d["takes"]],
            "reader": f"Blender {d['blender']} FBX importer",
            "cache": out,
        }


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
    meta["rest_pose"] = (positions (J, 3), frames (J, 3, 3)) in the same frame.
    """
    raw = read_fbx(path, take=take)
    stem = os.path.splitext(os.path.basename(path))[0]
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
    return SkeletonMotion(
        name=stem,
        joint_names=raw["names"],
        parents=raw["parents"],
        positions=pos,
        fps=fps_out,
        source=os.path.abspath(path),
        kind="skeleton",
        meta={"format": "fbx", "unit_scale": s, "ground_offset_m": ground_offset, "tpose_frame0": tpose0,
              "dropped_frames": dropped, "file_fps": file_fps, "fps_note": fps_note, "take": raw["take"],
              "takes": raw["takes"], "reader": raw["reader"], "rest_pose": (rest_pos, raw["rest_frames"])},
        rotations=raw["frames"][dropped:] if with_rotations else None,
    )


def bvh_to_fbx(bvh: str, out: str, scale: float | str = "auto") -> str:
    """Convert a BVH to FBX with Blender (armature only, every frame baked).

    scale: BVH units -> meters ("auto": the same guess as khumanoid.io.load_bvh),
    so the FBX is human-sized. The BVH's frame rate is kept as is (cgspeed CMU
    files keep their 120 Hz claim, as other conversions of them do).
    """
    if scale == "auto":
        from .bvh import load_bvh

        scale = load_bvh(bvh, drop_tpose=False, fps=1.0).meta["unit_scale"]
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    run_blender("bvh2fbx", os.path.abspath(bvh), os.path.abspath(out), repr(float(scale)))
    return out
