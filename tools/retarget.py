"""Retarget human mocap to a humanoid robot with GMR and save the project robot npz.

    python tools/retarget.py data/raw/cmu_bvh/02_01.bvh            # -> data/retargeted/02_01_g1.npz
    python tools/retarget.py data/raw/cmu_bvh                       # every motion in the folder (not *_stagei.npz)
    python tools/retarget.py data/raw/cmu_bvh --smooth 6            # + 6 Hz zero-phase low-pass (recommended)
    python tools/retarget.py data/raw/cmu_bvh --smooth 6 --swing-clearance 2     # + swing feet >= 2 cm off the floor
    python tools/retarget.py data/raw/cmu_bvh/143_11.bvh --smooth 6 --foot-flat --swing-clearance 2  # + flat stance soles
    python tools/retarget.py data/raw/lafan1_bvh --out-dir data/retargeted/lafan1_bvh
    python tools/retarget.py clip_stageii.npz --smpl-model-dir models   # AMASS SMPL-X
    python tools/retarget.py data/raw/cmu_fbx --smooth 6           # FBX (needs Blender)

Input formats (--format auto picks one):
  tpose    BVH with a T-pose reference: CMU cgspeed files (their inserted frame-0
           T-pose, dropped from the output) and most Vicon / OptiTrack / Xsens /
           Rokoko exports (rest pose; or --ref <frame>). The GMR config is
           derived from that T-pose; see retlens/retarget.py.
  fbx      FBX skeleton animation, read through Blender's importer. T-pose
           reference: the armature's rest pose (frame 0 for cgspeed CMU
           conversions, or --ref <frame>); config derived as for tpose.
  lafan1   LAFAN1-skeleton BVH, GMR's own loader and config. (nokov: --format nokov)
  smplx    AMASS SMPL-X npz, config derived from the body model's zero (T-)pose
           exactly like tpose BVH; needs the SMPL-X body model (--smpl-model-dir
           or $SMPL_MODEL_DIR -> folder with smplx/SMPLX_NEUTRAL.npz).
  smplx-gmr  the same files through GMR's own SMPL-X loader and config.

Writes per clip:
  <clip>_<robot>.npz   RobotMotion.save_npz: fps, joint_names, root_pos,
                       root_quat_wxyz, dof_pos (MJCF joint order)
  <clip>_<robot>.json  provenance: source, licence note, GMR commit, derived IK
                       config, scales, IK position residuals, what smoothing /
                       foot-flat / swing clearance changed
  <clip>_<robot>.pkl   with --pkl: GMR's own layout (root_rot xyzw) for TWIST/GMT
Inputs that share a clip name (one take in two folders, or as .bvh and .fbx) are named by
their path below the folder they share instead: <folder>_<clip>_<ext>_<robot>.npz. So is an
input whose <clip>_<robot>.npz an earlier run wrote from another file (the json's source),
for a dataset retargeted folder by folder into one --out-dir; no run replaces it.
Licences follow the source clip: outputs of CC BY-NC-ND sources (LAFAN1) are
derivatives and stay internal (see data/raw/*/SOURCE.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens.batch import motion_files  # noqa: E402
from retlens.io import npz_keys  # noqa: E402
from retlens.retarget import profile, retarget_file, save_gmr_pkl  # noqa: E402

INPUT_EXTENSIONS = (".bvh", ".fbx", ".npz")


def _key(path: str) -> str:
    """One spelling per file (case, 8.3 short names and links resolved)."""
    return os.path.normcase(os.path.realpath(path))


def iter_inputs(paths: list[str]):
    """(path, found in a folder) of every input once. In folders only the motions the viewer and the batch would list
    (batch.motion_files: no AMASS *_stagei.npz shape files, label files, cache folders, prop-only FBX or prop files a
    person FBX of the inputs draws with it) that this tool reads (.bvh / .fbx / .npz)."""
    keep = {_key(f) for f in motion_files(paths)} if any(os.path.isdir(p) for p in paths) else set()
    seen = set()
    for p in paths:
        if os.path.isfile(p):
            found = [(p, False)]
        elif os.path.isdir(p):
            found = [(f, True) for f in motion_files([p]) if f.lower().endswith(INPUT_EXTENSIONS) and _key(f) in keep]
        else:
            found = []
        for path, in_folder in found:
            key = _key(path)
            if key not in seen:
                seen.add(key)
                yield path, in_folder


def output_stems(files: list[str]) -> list[str]:
    """The output name (before _<robot>) of each input: its file name without the extension; inputs that share one
    (a take in two folders, or as .bvh and .fbx) get their path below the folder they share, with the extension
    (subjA_walk_bvh), so none skips or overwrites another."""
    stems = [os.path.splitext(os.path.basename(f))[0] for f in files]
    groups: dict = {}
    for i, s in enumerate(stems):
        groups.setdefault(s.lower(), []).append(i)
    out = list(stems)
    for group in groups.values():
        if len(group) < 2:
            continue
        full = [os.path.abspath(files[i]) for i in group]
        try:
            common = os.path.commonpath([os.path.dirname(p) for p in full])
        except ValueError:  # on different drives
            common = ""
        for i, p in zip(group, full):
            rel = os.path.relpath(p, common) if common else os.path.splitdrive(p)[1]
            out[i] = re.sub(r"[\\/.:]+", "_", rel).strip("_")
    return out


def made_from(base: str) -> str | None:
    """The input an earlier run wrote <base>.npz from (its json's "source"), None when that does not say."""
    try:
        with open(base + ".json", encoding="utf-8") as f:
            src = json.load(f).get("source")
    except (OSError, ValueError, AttributeError):  # no json, not json, or not an object
        return None
    return src if isinstance(src, str) and src else None


def output_base(out_dir: str, path: str, stem: str, tag: str, taken: set) -> str | None:
    """Where an input's outputs go: <out_dir>/<stem>_<tag>, unless an earlier run wrote that name from another file
    (one take retargeted folder by folder into one --out-dir): then the first name with more of the input's path
    (subjA_walk_bvh, then <its parent>_subjA_walk_bvh, ...) that is free. An earlier run's output of this very file
    under any of those names, or its clip name alone, is used again (skipped, or redone with --overwrite), so no take
    is made twice and none replaces another's. A source that is gone (the folder moved, another drive letter) is this
    file when its folder and file names are this file's; an output whose json does not say its source, or names a
    file that is gone, counts as this file's (as before). taken: the names given to the inputs before it in this run.
    None: every name is another file's."""
    comps = [c for c in re.split(r"[\\/]+", os.path.splitdrive(os.path.abspath(path))[1]) if c]
    plain = os.path.splitext(comps[-1])[0]
    longer = [re.sub(r"[\\/.:]+", "_", "_".join(comps[-k:])).strip("_") for k in range(2, len(comps) + 1)]
    names = list(dict.fromkeys([stem, *longer]))
    me = _key(path)

    def base(n):
        return os.path.join(out_dir, f"{n}_{tag}")

    def free(b):
        return _key(b) not in taken

    def tail(p):  # the folder and file name
        return [os.path.normcase(c) for c in re.split(r"[\\/]+", p) if c][-2:]

    def mine(src):
        return _key(src) == me if os.path.exists(src) else tail(src) == tail(os.path.abspath(path))

    for n in dict.fromkeys([*names, plain]):  # this file's own output from an earlier run
        src = made_from(base(n)) if os.path.exists(base(n) + ".npz") else None
        if src and mine(src) and free(base(n)):
            return base(n)
    for n in names:
        b = base(n)
        src = made_from(b) if os.path.exists(b + ".npz") else None
        if free(b) and (src is None or not os.path.exists(src) or _key(src) == me):
            return b
    return None


def source_note(path: str) -> str | None:
    """Relative path of the SOURCE.md (licence record) next to or above the clip, if any."""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(3):
        p = os.path.join(d, "SOURCE.md")
        if os.path.isfile(p):
            return os.path.relpath(p, ROOT)
        d = os.path.dirname(d)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="BVH / FBX / AMASS SMPL-X npz files or folders (searched recursively)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data", "retargeted"))
    ap.add_argument("--robot", default="unitree_g1",
                    help="the robot: unitree_g1 (default, 29 DoF) or the path of any humanoid's MJCF / URDF")
    ap.add_argument("--format", default="auto", choices=["auto", "tpose", "fbx", "lafan1", "nokov", "smplx", "smplx-gmr"])
    ap.add_argument("--fps", type=float, default=30.0, help="output frame rate (0 = keep the source rate)")
    ap.add_argument("--ref", default="auto", help="T-pose reference for --format tpose / fbx: auto | rest | <frame>")
    ap.add_argument("--up-axis", default="y", help="BVH up axis (default y)")
    ap.add_argument("--smpl-model-dir", default=None, help="SMPL-X model folder (holds smplx/)")
    ap.add_argument("--smooth", type=float, default=0.0, metavar="HZ",
                    help="zero-phase low-pass of the result at HZ (recommended 6; default off)")
    ap.add_argument("--foot-flat", action="store_true",
                    help="stand feet that stand still flat on the floor (both legs and the pelvis height), "
                         "after smoothing; for retargets that stand on their heels (CMU subject 143). Default off")
    ap.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                    help="lift swing feet to at least CM above the floor, after smoothing (recommended 2; default off)")
    ap.add_argument("--self-collision", action="store_true",
                    help="push apart robot parts that go through each other (hands into the hips), last. Default off")
    ap.add_argument("--velocity-limit", action="store_true",
                    help="GMR's IK velocity limit (3 pi rad/s per 2 ms IK iteration: lags fast motions, "
                         "CMU 143_11 up to 34 deg off; default off)")
    ap.add_argument("--pkl", action="store_true", help="also write GMR's pkl (root_rot xyzw)")
    ap.add_argument("--overwrite", action="store_true",
                    help="redo clips whose npz already exists (another input's output is never replaced)")
    args = ap.parse_args()

    ref = args.ref if args.ref in ("auto", "rest") else int(args.ref)
    tag = profile(args.robot).tag  # skips existing outputs of this model only (the tag carries its digest)
    os.makedirs(args.out_dir, exist_ok=True)
    inputs = list(iter_inputs(args.inputs))
    if not inputs:
        print("no .bvh / .fbx / .npz inputs found")
        return 1
    files = [p for p, _ in inputs]
    ok = skipped = failed = 0
    taken = set()
    for (path, in_folder), stem in zip(inputs, output_stems(files)):
        base = output_base(args.out_dir, path, stem, tag, taken)
        if base is None:
            print(f"[skip] {path}: every output name for it in {args.out_dir} is another input's")
            skipped += 1
            continue
        taken.add(_key(base))
        if os.path.exists(base + ".npz") and not args.overwrite:
            print(f"[skip] {base}.npz exists (--overwrite to redo)")
            skipped += 1
            continue
        if in_folder and path.lower().endswith(".npz"):
            try:
                human = "pose_body" in npz_keys(path)
            except (OSError, ValueError) as e:  # cut short, empty or no npz at all: a motion that does not read
                failed += 1
                print(f"[FAIL] {path}: {type(e).__name__}: {e}")
                continue
            if not human:  # a robot npz (an earlier run's output) or another table
                print(f"[skip] {path}: not an AMASS SMPL-X motion")
                skipped += 1
                continue
        try:
            motion, info = retarget_file(path, robot=args.robot, fmt=args.format, fps=args.fps or None,
                                         up_axis=args.up_axis, ref=ref, smpl_model_dir=args.smpl_model_dir,
                                         velocity_limit=args.velocity_limit, smooth_hz=args.smooth,
                                         swing_clearance=args.swing_clearance / 100.0, foot_flat=args.foot_flat,
                                         self_collision=args.self_collision)
        except Exception as e:  # keep going over a folder; report at the end
            failed += 1
            print(f"[FAIL] {path}: {type(e).__name__}: {e}")
            if os.environ.get("RETLENS_DEBUG"):
                traceback.print_exc()
            continue
        motion.save_npz(base + ".npz")
        info["license_note"] = source_note(path)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False, default=float)
        if args.pkl:
            save_gmr_pkl(motion, base + ".pkl")
        r = info["ik_position_residual"]
        smooth = f", smoothed {args.smooth:g} Hz" if info["smoothing"] else ""
        if info.get("foot_flat"):
            ff = info["foot_flat"]
            pitch = " / ".join(f"{s} {p['before']} -> {p['after']}" for s, p in ff["stance_pitch_deg"].items()
                               if p["before"] is not None)
            smooth += (f", stance soles flattened in {ff['frames_changed']} frames"
                       + (f" (pitch {pitch} deg, pelvis lowered max {ff['root_drop_cm']['max']} cm)" if pitch else ""))
        if info.get("swing_clearance"):
            sc = info["swing_clearance"]
            smooth += (f", moving feet lifted in {sc['frames_changed']} frames (shortfall max {sc['shortfall_cm']['max']}"
                       f" cm, leg joints {sc['leg_joint_change_deg']['rmse']} deg rms)")
        if info.get("self_collision"):
            sp = info["self_collision"]
            smooth += (f", self-collisions pushed apart in {sp['frames_changed']} frames (deeper than 3 cm "
                       f"{sp['frames_deeper_than_3cm']['before']} -> {sp['frames_deeper_than_3cm']['after']} frames)")
        print(f"[ok]   {base}.npz  {motion.num_frames} frames @ {motion.fps:g} fps, {info['ik_seconds']}s IK{smooth}, "
              f"residual feet {r.get('feet', {}).get('mean_cm', '-')} cm / hands {r.get('hands', {}).get('mean_cm', '-')} cm")
        ok += 1
    print(f"done: {ok} ok, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
