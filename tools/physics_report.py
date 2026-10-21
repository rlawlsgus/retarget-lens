"""Table of Isaac physics results (tools/isaac_replay.py --physics) as markdown.

    python tools/physics_report.py reports/physics --out reports/physics/summary.md

Reads every <clip>_sim.json under the given folders. One row per simulated clip:
harness force (share of body weight the virtual pelvis harness carried), falls,
how closely the drives tracked the clip, drive demand above the effort limits,
and the feet under physics.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from khumanoid.compare import _issue_ko  # noqa: E402
from khumanoid.diagnosis import CAUSE_KO  # noqa: E402


def pct(v) -> str:
    return "-" if v is None else f"{100 * v:.0f}"


def causes(p: dict, show: int = 3) -> str:
    """First cause of each fall (khumanoid/diagnosis.py), e.g. "발끝 걸림 1.47s (넘어짐 2.07s)";
    beyond ``show`` falls, a count per cause."""
    diag = p.get("fall_diagnosis") or []
    out = [f"{CAUSE_KO.get(d['primary_cause'], d['primary_cause'])} {d['primary_onset_s']}s (넘어짐 {d['fall_time_s']}s)"
           for d in diag[:show]]
    if len(diag) > show:
        rest = Counter(CAUSE_KO.get(d["primary_cause"], d["primary_cause"]) for d in diag[show:])
        out.append("외 " + ", ".join(f"{k} {v}" for k, v in rest.most_common()))
    return "; ".join(out) or "-"


def row(path: str, root: str) -> str:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    p, t, feet = d["physics"], d["physics"]["tracking"], d.get("robot_sim", {})
    harness = p.get("harness_force_per_body_weight") or {}
    flagged = next((v for k, v in p.items() if k.startswith("harness_flagged_ratio")), None)
    support = (p.get("feet_support_per_body_weight") or {}).get("mean")
    worst = ", ".join(f"{k.replace('_joint', '')} {v:.0f}" for k, v in list(t["worst_joints_deg"].items())[:2])
    peak = ", ".join(f"{k.replace('_joint', '')} {v:.1f}x" for k, v in list(p["torque"]["peak_demand_per_limit"].items())[:2])
    skate = next((v for k, v in feet.items() if k.startswith("foot_skating")), None)
    verdict = "통과" if p.get("consistent") else "; ".join(_issue_ko(i) for i in p.get("issues", []))
    src = os.path.relpath(os.path.dirname(path), root).replace("\\", "/")
    h = t.get("root_height_error_m") or {}
    height = f"{100 * h['mean']:+.1f} ({100 * h['min']:+.1f}..{100 * h['max']:+.1f})" if h else "-"
    return (f"| {src} | {d['clip']} | {d.get('duration_s', 0):.1f} | x{p.get('harness_scale', 1):g} | {p['falls']} | "
            f"{pct(harness.get('mean'))} / {pct(harness.get('p95'))} | {pct(flagged)} | {pct(support)} | "
            f"{t['joint_rmse_deg_median']:.1f} ({worst}) | {100 * t['root_position_error_m']['mean']:.1f} | {height} | "
            f"{t['root_rotation_error_deg']['mean']:.1f} | {pct(p['torque']['saturated_frame_ratio'])} ({peak}) | "
            f"{100 * feet.get('sole_min_z_m', float('nan')):.1f} | {pct(skate)} | {causes(p)} | {verdict} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="folders searched recursively for *_sim.json")
    ap.add_argument("--out", default=None, help="write the markdown here (default: print only)")
    args = ap.parse_args()
    files = sorted({f for d in args.folders for f in glob.glob(os.path.join(d, "**", "*_sim.json"), recursive=True)})

    def isaac(f: str) -> bool:  # tools/policy_replay.py writes *_sim.json too (MuJoCo, no "physics" block)
        with open(f, encoding="utf-8") as fh:
            return "physics" in json.load(fh)

    files = [f for f in files if isaac(f)]
    if not files:
        print("no Isaac *_sim.json found")
        return 1
    root = os.path.commonpath([os.path.abspath(d) for d in args.folders])
    lines = [
        f"# Isaac 물리 재생 결과 ({dt.datetime.now():%Y-%m-%d %H:%M})", "",
        "PhysX, 중력·마찰 바닥, 관절 PD(configs/physics.yaml)로 리타겟 모션을 따라가게 한 결과. "
        "보조 힘: 골반 가상 하네스(수평 위치·자세만)가 낸 힘 / 체중(평균 / 95%). 보조>20%: 하네스가 체중 20%를 넘게 "
        "낸 프레임 비율. 발 지지: 발 접촉력 수직 성분 / 체중(평균). 추종: 관절 RMSE 중앙값(°, 큰 관절). "
        "골반 오차: 수평 cm, 높이차 cm(시뮬 - 원본, 평균(최소..최대); 음수면 원본이 바닥 위로 떠 있음), 방향 °. "
        "한계 초과: PD 요구 토크가 관절 토크 한계를 넘은 프레임 비율(괄호: 최대 요구/한계; 수 배면 토크 부족보다 "
        "관절이 막힌 것 - 접촉·자세 불일치). 발 최저점(cm, 발 충돌 상자 기준), 미끄러짐 %. 넘어짐 원인: 넘어지기 "
        "직전 0.75 s에서 처음 시작된 조건과 그 시각(khumanoid/diagnosis.py, 근거 수치는 json의 fall_diagnosis).", "",
        "| 리타겟 | 클립 | 길이 s | 하네스 | 넘어짐 | 보조 힘 % | 보조>20% | 발 지지 % | 추종 RMSE° | 골반 수평 cm | "
        "골반 높이차 cm | 골반 ° | 한계 초과 % | 발 최저점 cm | 미끄러짐 % | 넘어짐 원인 | 판정 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [row(f, root) for f in files]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
