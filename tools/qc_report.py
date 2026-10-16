"""Run QC over motion files and tally valid hours against the dataset target.

Runs without Isaac Sim:

    python tools/qc_report.py data/raw --out reports/qc --target-hours 5
    python tools/qc_report.py data/retargeted --urdf assets/robot.urdf

Writes <out>.csv (one row per clip) and <out>.md (summary).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from khumanoid.io import MOTION_EXTENSIONS, load_motion, urdf_joint_limits  # noqa: E402
from khumanoid.qc import QCConfig, add_balance_flags, check_motion  # noqa: E402


def iter_files(paths: list[str]):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, _, files in os.walk(p):
            for f in sorted(files):
                if f.lower().endswith(MOTION_EXTENSIONS):
                    yield os.path.join(root, f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="motion files or folders (searched recursively)")
    ap.add_argument("--out", default=None, help="output prefix (default reports/qc_<timestamp>)")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "configs", "qc.yaml"))
    ap.add_argument("--target-hours", type=float, default=None, help="overrides config target_hours")
    ap.add_argument("--urdf", default=None, help="robot URDF for joint-limit checks on robot motions")
    ap.add_argument("--up-axis", default=None, help="up axis for BVH/C3D (default: per-format)")
    ap.add_argument("--smpl-model-dir", default=None, help="SMPL/SMPL-X model folder for AMASS npz")
    ap.add_argument("--balance", action="store_true",
                    help="robot motions: CoM / ZMP against the feet's support polygon and the soft flag "
                         "static_unbalanced (needs GMR's robot model; --robot)")
    ap.add_argument("--robot", default="unitree_g1", help="GMR robot model for --balance")
    args = ap.parse_args()

    cfg_all = {}
    if args.config and os.path.isfile(args.config):
        with open(args.config, encoding="utf-8") as f:
            cfg_all = yaml.safe_load(f) or {}
    cfg = QCConfig.from_dict(cfg_all.get("thresholds"))
    target_h = args.target_hours if args.target_hours is not None else float(cfg_all.get("target_hours", 5.0))
    limits = urdf_joint_limits(args.urdf) if args.urdf else None
    fk = None
    if args.balance:
        from khumanoid.analysis import FootKinematics

        fk = FootKinematics(args.robot)

    rows = []
    for path in iter_files(args.paths):
        try:
            m = load_motion(path, up_axis=args.up_axis, model_dir=args.smpl_model_dir)
            r = check_motion(m, cfg, limits)
            if fk is not None and r.kind == "robot":
                from khumanoid.analysis import balance

                _, bs, static = balance(m, fk, cfg)
                add_balance_flags(r, static, cfg, {
                    "com_outside_ratio": bs["com"]["outside_ratio"], "zmp_outside_ratio": bs["zmp"]["outside_ratio"],
                    "zmp_margin_p5_m": bs["zmp"]["margin_m"]["p5"], "no_support_ratio": bs["support_phase_ratio"]["none"]})
            row = r.row()
        except Exception as e:  # keep going: one broken file must not stop the ledger
            row = {"name": os.path.basename(path), "source": os.path.abspath(path), "status": "ERROR",
                   "duration_s": 0.0, "valid_s": 0.0, "notes": f"{type(e).__name__}: {e}"}
            if os.environ.get("KH_DEBUG"):
                traceback.print_exc()
        rows.append(row)
        print(f"[{row['status']:5}] {row.get('duration_s', 0):8.1f}s  valid {row.get('valid_s', 0):8.1f}s  {path}")

    if not rows:
        print("no motion files found")
        return 1

    df = pd.DataFrame(rows)
    out = args.out or os.path.join("reports", f"qc_{dt.datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    df.to_csv(out + ".csv", index=False, encoding="utf-8-sig")

    if "kind" not in df:
        df["kind"] = "?"
    df["kind"] = df["kind"].fillna("?")  # load errors have no kind
    summary = ["| kind | clips | PASS | WARN | FAIL/ERROR | total h | valid h |", "|---|---|---|---|---|---|---|"]
    for kind, g in df.groupby("kind"):
        st = g["status"].value_counts()
        summary.append(
            f"| {kind} | {len(g)} | {st.get('PASS', 0)} | {st.get('WARN', 0)} | "
            f"{st.get('FAIL', 0) + st.get('ERROR', 0)} | {g['duration_s'].sum() / 3600:.3f} | "
            f"{g['valid_s'].sum() / 3600:.3f} |"
        )
    valid_h = df.loc[df["kind"] != "robot", "valid_s"].sum() / 3600
    summary += ["", f"**Valid human-motion hours: {valid_h:.3f} h / target {target_h:g} h "
                    f"({100 * valid_h / target_h if target_h else 0:.1f}%)**"]

    lines = [f"# Mocap QC report ({dt.datetime.now():%Y-%m-%d %H:%M})", ""] + summary + [""]
    bad = df[df["status"].isin(["FAIL", "ERROR", "WARN"])]
    if len(bad):
        lines += ["## Clips needing attention", "", "| status | clip | notes |", "|---|---|---|"]
        lines += [f"| {r.status} | {r.name} | {r.notes if isinstance(r.notes, str) else ''} |" for r in bad.itertuples()]
    with open(out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(summary))
    print(f"\nwrote {out}.csv and {out}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
