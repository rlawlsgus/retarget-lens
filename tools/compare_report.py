"""Batch comparison of motions on the same robot: a markdown table per group.

    # one group: the first file is the reference
    python tools/compare_report.py data/raw/cmu_bvh/02_01.bvh data/raw/amass_cmu_smplx/CMU/02/02_01_stageii.npz
    # several groups (-g per group) in one report
    python tools/compare_report.py -g a.bvh a_stageii.npz -g b.bvh b_stageii.npz --out reports/compare_bvh_smplx.md

Inputs and retargeting are the same as tools/compare_viewer.py (human files are
retargeted with --smooth, cached in data/cache/retarget/). For every motion other
than the reference: the time offset that best aligns it (leg joints), the per-joint
RMSE at that offset, plus smoothness, planted-foot slip, floor penetration, IK
position residuals and QC (joint limits from --urdf).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from khumanoid import analysis  # noqa: E402
from khumanoid.compare import compute_metrics, load_item  # noqa: E402
from khumanoid.io import urdf_joint_limits  # noqa: E402


def fmt(v, f="{:.1f}") -> str:
    return "-" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f.format(v)


def report_group(paths: list[str], args, fk, limits) -> list[str]:
    items = [load_item(p, robot=args.robot, smooth=args.smooth, fps=args.fps, csv_fps=args.csv_fps,
                       smpl_model_dir=args.smpl_model_dir, swing_clearance=args.swing_clearance / 100.0, log=None)
             for p in paths]
    for it in items:
        compute_metrics(it, fk, limits)
    ref = items[0]
    lines = [f"### {ref.label} (기준)", "",
             "| 모션 | 종류 | 길이 s | 시간 오프셋 s | 다리 RMSE° | 전체 RMSE° | 차이 큰 관절 (°) | 가속도 | 저크 | "
             "최대속도 | 발 미끄러짐 % | 관통 % | 발 최저점 cm | 스윙 근접 % | IK 발/손 cm | QC |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        m = it.metrics
        off = legs = whole = worst = "-"
        if it is not ref:
            o, _ = analysis.estimate_offset(ref.robot, it.robot, max_shift=args.max_shift)
            joints, rmse, ov = analysis.joint_rmse(ref.robot, it.robot, 0.0, o)
            if ov > 0:
                li = [i for i, n in enumerate(joints) if any(k in n for k in analysis.LEG_KEYS)]
                off, legs, whole = f"{o:+.3f}", fmt(float(np.median(rmse[li]))), fmt(float(np.median(rmse)))
                top = np.argsort(-rmse)[:3]
                worst = ", ".join(f"{joints[i].replace('_joint', '')} {rmse[i]:.0f}" for i in top)
        res = it.info.get("ik_position_residual") or {}
        ik = (f"{res['feet']['mean_cm']:.1f} / {res['hands']['mean_cm']:.1f}"
              if "feet" in res and "hands" in res else "-")
        lines.append(f"| {it.label} | {it.kind} | {fmt(m['duration'], '{:.2f}')} | {off} | {legs} | {whole} | {worst} | "
                     f"{fmt(m.get('acc_mean'))} | {fmt(m.get('jerk_mean'), '{:.0f}')} | {fmt(m.get('vel_max'))} | "
                     f"{fmt(m.get('planted_slip_pct'), '{:.2f}')} | {fmt(m.get('penetration_pct'), '{:.2f}')} | "
                     f"{fmt(m.get('sole_min_cm'))} | {fmt(m.get('swing_low_pct'), '{:.0f}')} | {ik} | {m.get('qc')} |")
    return lines + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="one group of motion files (the first is the reference)")
    ap.add_argument("-g", "--group", nargs="+", action="append", default=[], help="another group (repeatable)")
    ap.add_argument("--out", default=None, help="write the markdown here (default: print only)")
    ap.add_argument("--robot", default="unitree_g1")
    ap.add_argument("--urdf", default=os.path.join(os.path.dirname(ROOT), "GMR", "assets", "unitree_g1",
                                                   "g1_custom_collision_29dof.urdf"))
    ap.add_argument("--smooth", type=float, default=6.0, help="smoothing for retargeted inputs (Hz, 0 = off)")
    ap.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                    help="lift swing feet of retargeted inputs to at least CM off the floor (0 = off)")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--csv-fps", type=float, default=30.0)
    ap.add_argument("--smpl-model-dir", default=os.environ.get("SMPL_MODEL_DIR", os.path.join(ROOT, "models")))
    ap.add_argument("--max-shift", type=float, default=3.0, help="search range of the time alignment (s)")
    args = ap.parse_args()
    groups = ([args.inputs] if args.inputs else []) + args.group
    if not groups or any(len(g) < 2 for g in groups):
        ap.error("each group needs a reference and at least one more motion")

    fk = None
    try:
        fk = analysis.FootKinematics(args.robot)
    except Exception as e:
        print(f"foot metrics disabled ({type(e).__name__}: {e})")
    limits = urdf_joint_limits(args.urdf) if os.path.isfile(args.urdf) else None
    clearance = f", 스윙 발 높이 >= {args.swing_clearance:g} cm" if args.swing_clearance else ""
    lines = [f"# 모션 비교 ({dt.datetime.now():%Y-%m-%d %H:%M}, 로봇 {args.robot}, 사람 입력 평활화 {args.smooth:g} Hz"
             f"{clearance})", "",
             "시간 오프셋: 기준에 맞추는 표시 오프셋(다리 관절각 차이 최소). RMSE: 그 오프셋에서 관절별 RMSE의 중앙값. "
             "가속도 rad/s², 저크 rad/s³, 최대속도 rad/s. 발 미끄러짐: 발바닥 전체가 붙은 채 0.3 m/s 이상으로 0.1 s 이상 "
             "움직인 프레임 비율. 관통: 발 최저점 -2 cm 아래 프레임 비율. 스윙 근접: 가장 느린 발바닥 점까지 0.5 m/s "
             "넘게 움직이는 발이 그때의 바닥(디딤발 높이를 따라감) 1 cm 안을 지나는 비율(Isaac 물리 재생에서 발끝이 걸려 "
             "비틀거리는 원인, `--swing-clearance`로 보정).", ""]
    for g in groups:
        lines += report_group(g, args, fk, limits)
        print("\n".join(lines[-(len(g) + 4):]), flush=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
