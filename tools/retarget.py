"""Retarget human mocap to a humanoid robot with GMR and save the project robot npz.

    python tools/retarget.py data/raw/cmu_bvh/02_01.bvh            # -> data/retargeted/02_01_g1.npz
    python tools/retarget.py data/raw/cmu_bvh                       # every .bvh / .npz in the folder
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
Licences follow the source clip: outputs of CC BY-NC-ND sources (LAFAN1) are
derivatives and stay internal (see data/raw/*/SOURCE.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens.retarget import ROBOT_TAGS, retarget_file, save_gmr_pkl  # noqa: E402

INPUT_EXTENSIONS = (".bvh", ".fbx", ".npz")


def iter_inputs(paths: list[str]):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, _, files in os.walk(p):
            for f in sorted(files):
                if f.lower().endswith(INPUT_EXTENSIONS):
                    yield os.path.join(root, f)


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
    ap.add_argument("--robot", default="unitree_g1", help="GMR robot name (default unitree_g1, 29 DoF)")
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
    ap.add_argument("--overwrite", action="store_true", help="redo clips whose npz already exists")
    args = ap.parse_args()

    ref = args.ref if args.ref in ("auto", "rest") else int(args.ref)
    tag = ROBOT_TAGS.get(args.robot, args.robot)
    os.makedirs(args.out_dir, exist_ok=True)
    files = list(iter_inputs(args.inputs))
    if not files:
        print("no .bvh / .fbx / .npz inputs found")
        return 1
    failed = 0
    for path in files:
        base = os.path.join(args.out_dir, f"{os.path.splitext(os.path.basename(path))[0]}_{tag}")
        if os.path.exists(base + ".npz") and not args.overwrite:
            print(f"[skip] {base}.npz exists (--overwrite to redo)")
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
    print(f"done: {len(files) - failed} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
