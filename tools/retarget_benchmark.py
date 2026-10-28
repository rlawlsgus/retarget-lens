"""Retargeting quality per robot: the same human clips retargeted to each robot and scored the
same way (retlens/retarget_quality.py), so "this robot retargets well, that one does not"
comes out as one table.

    python tools/retarget_benchmark.py                                  # G1, the CMU BVH clips (public)
    python tools/retarget_benchmark.py --robot unitree_g1 --robot <another GMR robot> data/raw/cmu_bvh
    python tools/retarget_benchmark.py data/raw/cmu_bvh --foot-flat --out reports/retarget_quality/foot_flat

Inputs: human motion files or folders of them (BVH, FBX, AMASS SMPL-X npz; robot motions are
skipped), retargeted with the same settings for every robot (cached in data/cache/retarget/).
A robot takes part once retlens/retarget.py has its T-pose tables (TPOSE_LIMBS, TPOSE_FEET),
the same tables retargeting BVH / FBX / SMPL-X to it needs.

Writes <out>/summary.md (per robot: score, grades and the median of every quality metric; per
clip: score and what cost points) and <out>/results.json. Outputs of licence-gated inputs
(AMASS, LAFAN1) stay internal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from retlens import analysis, paths, retarget_quality as rq, settings  # noqa: E402
from retlens.compare import HUMAN_EXT, compute_metrics, human_format, load_item  # noqa: E402

COLUMNS = (  # (metrics key, header, format)
    ("retarget_score", "점수", "{:.0f}"), ("pose_err_deg", "자세 오차 °", "{:.1f}"),
    ("contact_mismatch_pct", "발 접촉 불일치 %", "{:.1f}"), ("joint_limit_pct", "관절 한계 %", "{:.1f}"),
    ("self_collision_pct", "자기 충돌 %", "{:.1f}"), ("planted_slip_pct", "발 미끄러짐 %", "{:.1f}"),
    ("static_unbalanced_pct", "정적 불균형 %", "{:.1f}"),
)


def fmt(v, f="{:.1f}") -> str:
    return "-" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f.format(v)


def human_files(inputs: list[str]) -> list[str]:
    """Human motion files among the inputs (folders: their files, sorted)."""
    out = []
    for p in inputs:
        files = sorted(os.path.join(p, f) for f in os.listdir(p)) if os.path.isdir(p) else [p]
        for f in files:
            if not f.lower().endswith(HUMAN_EXT + (".npz",)):
                continue
            try:
                if human_format(f) is not None:
                    out.append(os.path.abspath(f))
            except ValueError:  # an npz that is neither a robot motion nor AMASS (e.g. a body shape)
                continue
    return out


def run_robot(robot: str, files: list[str], args, log=print) -> list[dict]:
    from retlens.retarget import robot_model, unavailable

    why = unavailable(robot) or ("" if rq.supported(robot) else "no T-pose tables in retlens/retarget.py")
    if why:
        log(f"[skip] {robot}: {why}")
        return []
    model = robot_model(robot)
    fk = analysis.FootKinematics(robot, foot_bodies=rq.foot_bodies(robot))
    limits = rq.model_limits(model)
    rows = []
    for f in files:
        label = paths.rel(f).replace(os.sep, "/")
        try:
            item = load_item(f, robot=robot, smooth=args.smooth, fps=args.fps, smpl_model_dir=args.smpl_model_dir,
                             swing_clearance=args.swing_clearance / 100.0, foot_flat=args.foot_flat,
                             self_collision=args.self_collision, log=None)
            compute_metrics(item, fk, limits)
        except Exception as e:  # keep going over the set; report it
            log(f"[fail] {robot} {label}: {type(e).__name__}: {e}")
            rows.append({"robot": robot, "clip": label, "error": f"{type(e).__name__}: {e}"})
            continue
        m = item.metrics
        q = m.get("_quality") or {}
        row = {"robot": robot, "clip": label, "kind": item.kind, "duration_s": round(item.robot.duration, 2),
               **{k: m.get(k) for k, _, _ in COLUMNS}, "grade": rq.grade(m["retarget_score"]) if "retarget_score" in m else None,
               "contact_lost_pct": m.get("contact_lost_pct"), "contact_extra_pct": m.get("contact_extra_pct"),
               "pelvis_height_err_pct": m.get("pelvis_height_err_pct"), "penetration_pct": m.get("penetration_pct"),
               "qc": m.get("qc"), "details": q}
        if q.get("error"):
            row["error"] = q["error"]
        rows.append(row)
        log(f"[ok]   {robot} {label}: {fmt(row['retarget_score'], '{:.0f}')} ({row['grade']})")
    return rows


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("retarget_score") is not None]
    if not ok:
        return {"clips": len(rows), "scored": 0}
    out = {"clips": len(rows), "scored": len(ok), "score_mean": float(np.mean([r["retarget_score"] for r in ok])),
           "grades": {g: sum(r["grade"] == g for r in ok) for _, g in rq.GRADES}}
    for k, _, _ in COLUMNS[1:]:
        vals = [r[k] for r in ok if r.get(k) is not None and np.isfinite(r[k])]
        out[f"{k}_median"] = float(np.median(vals)) if vals else None
    return out


def write_report(rows: list[dict], args, out_dir: str) -> str:
    robots = list(dict.fromkeys(r["robot"] for r in rows))
    summary = {rb: summarize([r for r in rows if r["robot"] == rb]) for rb in robots}
    settings_txt = (f"smooth {args.smooth:g} Hz" + (", foot-flat" if args.foot_flat else "")
                    + (f", swing >= {args.swing_clearance:g} cm" if args.swing_clearance else "")
                    + (", self-collision" if args.self_collision else ""))
    lines = ["# 리타게팅 품질 (로봇별)", "",
             f"{dt.date.today().isoformat()} · `tools/retarget_benchmark.py` · 리타게팅 설정: {settings_txt} · "
             f"클립 {len({r['clip'] for r in rows})}개", "",
             "점수는 0–100(85 이상 좋음, 70 이상 보통)입니다. 지표와 감점 기준은 docs/manual.md의 \"리타게팅 품질 점수\"에 있습니다.",
             "", "## 로봇별 요약", "",
             "| 로봇 | 클립 | 평균 점수 | 좋음 / 보통 / 나쁨 | " + " | ".join(f"{h} (중앙값)" for _, h, _ in COLUMNS[1:]) + " |",
             "|---|---|---|---|" + "---|" * (len(COLUMNS) - 1)]
    for rb, s in summary.items():
        if not s.get("scored"):
            lines.append(f"| {rb} | {s['clips']} | - | - |" + " - |" * (len(COLUMNS) - 1))
            continue
        g = s["grades"]
        lines.append(f"| {rb} | {s['scored']} | {s['score_mean']:.1f} | {g['좋음']} / {g['보통']} / {g['나쁨']} | "
                     + " | ".join(fmt(s[f'{k}_median'], f) for k, _, f in COLUMNS[1:]) + " |")
    lines += ["", "## 클립별", "",
              "| 로봇 | 클립 | " + " | ".join(h for _, h, _ in COLUMNS) + " | 등급 | 감점 | 많이 어긋난 부위 |",
              "|---|---|" + "---|" * (len(COLUMNS) + 3)]
    for r in rows:
        if r.get("retarget_score") is None:
            lines.append(f"| {r['robot']} | {r['clip']} |" + " - |" * len(COLUMNS) + f" - | {r.get('error', '-')} | - |")
            continue
        q = r["details"]
        lost = ", ".join(f"{rq.SCORE_LABELS.get(k, k)} -{v:g}" for k, v in q.get("score_lost", {}).items()) or "-"
        worst = ", ".join(f"{n} {v:g}°" for n, v in sorted(q.get("segments_deg", {}).items(), key=lambda kv: -kv[1])[:2])
        lines.append(f"| {r['robot']} | {r['clip']} | " + " | ".join(fmt(r[k], f) for k, _, f in COLUMNS)
                     + f" | {r['grade']} | {lost} | {worst} |")
    os.makedirs(out_dir, exist_ok=True)
    md = os.path.join(out_dir, "summary.md")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump({"settings": {"smooth_hz": args.smooth, "foot_flat": args.foot_flat,
                                "swing_clearance_cm": args.swing_clearance, "self_collision": args.self_collision,
                                "fps": args.fps},
                   "summary": summary, "clips": rows}, fh, ensure_ascii=False, indent=1, default=float)
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", default=[os.path.join(ROOT, "data", "raw", "cmu_bvh")],
                    help="human motion files or folders (default: data/raw/cmu_bvh)")
    ap.add_argument("--robot", action="append", default=None, help="GMR robot (repeatable; default unitree_g1)")
    ap.add_argument("--smooth", type=float, default=6.0, metavar="HZ")
    ap.add_argument("--foot-flat", action="store_true")
    ap.add_argument("--swing-clearance", type=float, default=2.0, metavar="CM", help="default 2 (the recommended setting)")
    ap.add_argument("--self-collision", action="store_true")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--smpl-model-dir", default=None, help="for AMASS SMPL-X inputs (default: 환경 설정)")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "retarget_quality"), help="output folder")
    args = ap.parse_args(argv)
    args.smpl_model_dir = args.smpl_model_dir or settings.find_smpl().path or paths.smpl_model_dir()
    files = human_files(args.inputs)
    if not files:
        print("no human motion files (BVH / FBX / AMASS SMPL-X npz) in the inputs")
        return 1
    rows = []
    for robot in args.robot or ["unitree_g1"]:
        rows += run_robot(robot, files, args)
    if not rows:
        return 1
    print(f"wrote {write_report(rows, args, args.out)}")
    return 0 if all(r.get("retarget_score") is not None for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
