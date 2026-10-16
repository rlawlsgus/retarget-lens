"""Write docs/cmu_motion_labels.md: the CMU mocap trial labels, what of it is on this PC,
and representative trials per motion type, for picking clips in the viewer.

Labels are the CMU database's own trial descriptions, as listed in the metadata.csv of
the Hugging Face CMU FBX set (data/raw/cmu_fbx, tools/fetch_samples.py cmu_fbx).
Lengths come from the local AMASS SMPL-X files (mocap_frame_rate), or the local BVH.
Only labels, lengths and file presence are written, no motion data.

    python tools/cmu_motion_index.py
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "cmu_motion_labels.md")
METADATA = os.path.join(ROOT, "data", "raw", "cmu_fbx", "metadata.csv")
AMASS = os.path.join(ROOT, "data", "raw", "amass_cmu_smplx", "CMU")
BVH = os.path.join(ROOT, "data", "raw", "cmu_bvh")
FBX = os.path.join(ROOT, "data", "raw", "cmu_fbx")

# (motion type, note, [(trial, short Korean note)]); picked from the labels, about 10 s where possible
PICKS = [
    ("걷기", "", [("02_01", "BVH·FBX·SMPL-X 모두 있음"), ("91_57", ""), ("132_46", "느리게"), ("136_03", "뒤로 걷기"),
                ("120_08", "살금살금, 과장된 연기")]),
    ("달리기·조깅", "", [("02_03", "BVH·FBX·SMPL-X 모두 있음"), ("111_23", ""), ("77_10", "조심스럽게")]),
    ("점프·한 발 뛰기", "", [("124_11", "두 발 점프"), ("141_06", "점프하며 비틀기"), ("75_12", "상자 위로 점프"),
                         ("131_03", "출발-한 발 뛰기-정지")]),
    ("방향 전환", "", [("16_17", "BVH·FBX만 있음(AMASS에 없음)"), ("83_36", "걷다 왼쪽 90°"), ("47_01", "걷다 뒤돌아 돌아옴")]),
    ("춤", "", [("05_02", "발레"), ("93_08", "찰스턴"), ("60_10", "살사(2인 중 1명)"), ("141_12", "트위스트")]),
    ("스포츠", "", [("06_12", "농구 드리블"), ("124_04", "농구 자유투"), ("124_07", "야구 스윙"), ("10_01", "축구 킥"),
                 ("79_92", "프리스비")]),
    ("격투·발차기", "", [("141_14", "펀치와 킥"), ("135_04", "앞차기")]),
    ("집안일·물체 다루기", "가정 내 이동·조작 과제와 가장 가깝습니다",
     [("143_11", "상자 들기 (BVH·FBX·SMPL-X)"), ("143_13", "빨래바구니 들기 (BVH·FBX·SMPL-X)"),
      ("143_28", "빗자루질 (BVH·FBX·SMPL-X)"), ("143_26", "창문 닦기"), ("82_07", "무거운 물체 밀기"),
      ("70_05", "여행가방 들고 걷기"), ("113_26", "들고 걷기"), ("106_25", "청소"), ("13_09", "음료 마시기"),
      ("143_20", "받고 던지기")]),
    ("앉기·일어서기", "", [("141_17", "스툴에 앉기"), ("113_15", "의자에 앉았다 일어서기"), ("143_18", "앉았다 일어서기")]),
    ("계단·사다리·기기", "", [("83_32", "계단 오르기"), ("143_37", "사다리 오르내리기"), ("133_01", "걷다 기기")]),
    ("균형", "", [("49_18", "한 발로 서기"), ("132_09", "팔 벌리고 균형 잡으며 걷기")]),
    ("운동·스트레칭", "", [("13_30", "팔벌려뛰기·스쿼트·조깅"), ("114_12", "스트레칭"), ("111_38", "요가")]),
    ("흉내·제스처", "", [("79_53", "개 흉내"), ("143_34", "치킨 댄스"), ("141_16", "손 흔들기")]),
    ("바닥에서 일어나기", "바닥에 눕거나 손을 짚는 동작이라 발만 지지로 보는 현재 균형·물리 판정에는 맞지 않습니다",
     [("140_04", "옆으로 누웠다 일어나기"), ("139_16", "바닥에서 일어나기")]),
    ("아크로바틱", "구르기·손 짚기·공중 동작이라 G1 리타게팅과 물리 재생이 크게 어긋납니다",
     [("90_03", "옆돌기"), ("90_15", "앞 손짚고 돌기"), ("90_28", "브레이크댄스")]),
]


def load_labels(path: str) -> dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0].lower().endswith(".fbx"):
                out[row[0][:-4]] = row[1].strip()
    return out


def amass_lengths(folder: str) -> dict[str, float]:
    out = {}
    if not os.path.isdir(folder):
        return out
    for subject in sorted(os.listdir(folder)):
        d = os.path.join(folder, subject)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.endswith("_stageii.npz"):
                with np.load(os.path.join(d, name)) as z:
                    out[name[: -len("_stageii.npz")]] = len(z["trans"]) / float(z["mocap_frame_rate"])
    return out


def trial_key(t: str):
    s, _, n = t.partition("_")
    return (int(s) if s.isdigit() else 999, int(n) if n.isdigit() else 999, t)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    labels = load_labels(METADATA)
    seconds = amass_lengths(AMASS)
    bvh = {f[:-4] for f in os.listdir(BVH) if f.endswith(".bvh")} if os.path.isdir(BVH) else set()
    fbx = {f[:-4] for f in os.listdir(FBX) if f.endswith(".fbx")} if os.path.isdir(FBX) else set()
    from khumanoid.io.bvh import load_bvh

    for t in sorted(bvh - set(seconds)):  # BVH-only trials: length from the BVH (60 Hz subjects fixed)
        m = load_bvh(os.path.join(BVH, t + ".bvh"))
        seconds[t] = m.num_frames / m.fps

    def have(t: str) -> str:
        return " ".join(k for k, ok in (("SMPL-X", t in seconds and os.path.isfile(
            os.path.join(AMASS, t.split("_")[0], f"{t}_stageii.npz"))), ("BVH", t in bvh), ("FBX", t in fbx)) if ok) or "-"

    def sec(t: str) -> str:
        return f"{seconds[t]:.1f}" if t in seconds else "-"

    trials = sorted(labels, key=trial_key)
    local_amass = sum(1 for t in trials if "SMPL-X" in have(t))
    lines = [
        "# CMU 모캡 동작 라벨",
        "",
        f"`python tools/cmu_motion_index.py`로 만든 파일입니다({dt.date.today().isoformat()}). 손으로 고치지 말고 스크립트를 다시 돌리세요.",
        "",
        "- **라벨:** CMU Graphics Lab Motion Capture Database의 시도별 설명입니다. Hugging Face CMU FBX 세트의 "
        "`metadata.csv`(`data/raw/cmu_fbx/`)에서 가져왔습니다. 설명은 영어 원문 그대로입니다.",
        f"- **이 PC에 있는 것:** CMU {len(trials)}개 시도 중 AMASS SMPL-X {local_amass}개"
        f"(`data/raw/amass_cmu_smplx/CMU`, AMASS 라이선스라 내부 검증 전용), BVH {len(bvh)}개, FBX {len(fbx)}개입니다.",
        "- **길이:** AMASS 파일의 실제 촬영 속도로 계산했습니다. AMASS에 없고 BVH만 있으면 BVH에서 계산했습니다.",
        "- **뷰어에서 열기:** `tools/compare_viewer.py`의 \"모션\" 탭 \"이름 검색\"에 번호(예: `143_11`)를 넣고 파일을 고릅니다. "
        "SMPL-X는 \"사람 표시: 몸 메시\"로 몸 표면까지 볼 수 있습니다. 처음 여는 사람 모션은 리타게팅에 수십 초가 걸립니다.",
        "",
        "## 동작 종류별 대표 시도",
        "",
        "가능하면 10초 안팎의 짧은 시도를 골랐습니다.",
        "",
    ]
    for kind, note, picks in PICKS:
        lines += [f"### {kind}", ""]
        if note:
            lines += [note, ""]
        lines += ["| 번호 | CMU 설명 | 메모 | 길이 (s) | 있는 형식 |", "|---|---|---|---|---|"]
        for t, memo in picks:
            lines.append(f"| `{t}` | {labels.get(t, '?')} | {memo} | {sec(t)} | {have(t)} |")
        lines.append("")
    lines += ["## 전체 목록 (피험자별)", ""]
    by_subject = collections.defaultdict(list)
    for t in trials:
        by_subject[t.split("_")[0]].append(t)
    for s, ts in sorted(by_subject.items(), key=lambda kv: trial_key(kv[0] + "_0")):
        lines += [f"### 피험자 {s}", "", "| 번호 | CMU 설명 | 길이 (s) | 있는 형식 |", "|---|---|---|---|"]
        lines += [f"| `{t}` | {labels[t].replace('|', '/')} | {sec(t)} | {have(t)} |" for t in ts]
        lines.append("")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"wrote {args.out}: {len(trials)} trials, {local_amass} with AMASS SMPL-X here, "
          f"{sum(len(p) for _, _, p in PICKS)} picks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
