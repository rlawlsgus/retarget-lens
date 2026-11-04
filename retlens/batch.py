"""데이터셋 일괄 처리: every motion file of a capture session (or several) retargeted, measured and summed up
in one row each, for a table to sort and filter (RetLens's 데이터셋 tab, retlens-cli batch).

    b = Batch(BatchOptions(physics=True, rules="my.rules.yaml"))
    rows = b.run(files, progress=lambda done, total, row: ..., cancel=lambda: False)

Per file: the retarget (cached like any retarget) with the corrections of the options, QC, 리타게팅 점수 and
what cost it the most, the foot / balance / quality metrics, the problem spans (retlens.problems: seconds per
kind), the objects captured with it (FBX) and how well the robot's hands meet them, its labels (the label
file next to it, else 자동 라벨 by the options' rule file) and, with physics on, the MuJoCo harness check
(falls, the first fall's cause and the falls per cause (retlens/diagnosis.py), harness force, verdict). A file
that cannot be read gives a row with "error".

Rows are cached per file (path, size, modification time) and options (retarget corrections, physics with
policy_replay.RESULT_VERSION, the rule file and its modification time), so a run that was stopped or a folder
run again skips what is done.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable

from . import paths

BATCH_VERSION = 1  # bump when a row's meaning changes (old cached rows are then computed again)

# (key, column title, format) of the table and the CSV, in order
COLUMNS = [
    ("name", "모션", "{}"), ("folder", "폴더", "{}"), ("duration_s", "길이 (s)", "{:.1f}"),
    ("retarget_score", "리타게팅 점수", "{:.0f}"), ("qc", "QC", "{}"), ("main_loss", "주된 감점", "{}"),
    ("problems_s", "문제 구간 (s)", "{:.1f}"), ("worst_problem", "가장 긴 문제", "{}"),
    ("pose_err_deg", "자세 오차 (°)", "{:.1f}"), ("contact_mismatch_pct", "발 접촉 불일치 (%)", "{:.1f}"),
    ("planted_slip_pct", "발 미끄러짐 (%)", "{:.1f}"), ("swing_low_pct", "스윙 발 근접 (%)", "{:.1f}"),
    ("self_collision_pct", "자기 충돌 (%)", "{:.1f}"), ("joint_limit_pct", "관절 한계 (%)", "{:.1f}"),
    ("objects", "물체", "{}"), ("hand_obj_reach_pct", "물체 닿음 (%)", "{:.0f}"),
    ("labels", "라벨", "{}"), ("label_segments", "라벨 구간", "{}"),
    ("phys_falls", "물리 넘어짐", "{}"), ("phys_first_cause", "첫 넘어짐 원인", "{}"),
    ("phys_harness_pct", "보조 힘 (%)", "{:.0f}"), ("phys_ok", "물리 판정", "{}"),
    ("kind", "종류", "{}"), ("error", "오류", "{}"), ("file", "파일", "{}"),
]


@dataclass
class BatchOptions:
    robot: str = "unitree_g1"
    smooth: float = 6.0
    fps: float = 30.0
    csv_fps: float = 30.0
    smpl_model_dir: str | None = None
    foot_flat: bool = False
    swing_clearance_cm: float = 0.0
    self_collision: bool = False
    physics: bool = False  # the MuJoCo harness check of every retarget (1-3 s per clip)
    rules: str | None = None  # 자동 라벨 rule file for motions without a label file next to them


def motion_files(inputs: list[str]) -> list[str]:
    """Files as given; folders give the motion files under them (label files and SMPL-X shape files left out)."""
    from .compare import is_motion_file

    out = []
    for p in inputs:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                out += [os.path.join(root, f) for f in sorted(files) if is_motion_file(os.path.join(root, f))]
        else:
            out.append(p)
    return out


class Batch:
    def __init__(self, opts: BatchOptions | None = None, cache_dir: str | None = None, fk=None, limits=None,
                 log: Callable | None = None):
        """fk / limits: an analysis.FootKinematics and the robot's joint limits to reuse (made on first use)."""
        self.opts = opts or BatchOptions()
        self.cache_dir = cache_dir or paths.cache_dir("batch")
        self._fk, self._limits = fk, limits
        self.log = log or (lambda *_: None)
        self._sim = None  # the MuJoCo harness sim, made once

    # ------------------------------------------------------------ cache
    def key(self, path: str) -> str:
        st = os.stat(path)
        o = asdict(self.opts)
        rules = o.pop("rules")
        o.pop("smpl_model_dir")
        if o["physics"]:  # MuJoCo results that change meaning make the physics rows again (only those)
            from .policy_replay import RESULT_VERSION

            o["physics"] = RESULT_VERSION
        rule_id = [os.path.abspath(rules), os.path.getmtime(rules)] if rules and os.path.isfile(rules) else rules
        raw = json.dumps([BATCH_VERSION, os.path.abspath(path), st.st_size, st.st_mtime_ns, o, rule_id], sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def _cache_file(self, path: str) -> str:
        stem = os.path.splitext(os.path.basename(path))[0][:48]
        return os.path.join(self.cache_dir, f"{stem}-{self.key(path)}.json")

    def cached(self, path: str) -> dict | None:
        try:
            with open(self._cache_file(path), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------ one file
    def _tools(self):
        if self._fk is None:
            from .analysis import FootKinematics

            self._fk = FootKinematics(self.opts.robot)
        if self._limits is None:
            from .io import urdf_joint_limits

            self._limits = urdf_joint_limits(paths.robot_urdf())
        return self._fk, self._limits

    def process(self, path: str) -> dict:
        """The row of one file: from the cache when this file and these options were done before."""
        row = self.cached(path)
        if row is not None:
            return {**row, "cached": True}
        t0 = time.time()
        try:
            row = self._measure(path)
        except Exception as e:  # one bad file never stops the batch
            row = {"error": f"{type(e).__name__}: {e}"}
        row = {"file": os.path.abspath(path), "folder": os.path.basename(os.path.dirname(os.path.abspath(path))),
               "name": os.path.splitext(os.path.basename(path))[0], **row, "seconds_taken": round(time.time() - t0, 2)}
        if "error" not in row and "phys_diagnosis_error" not in row:  # failures are tried again next time (a missing
            # Blender, a file being written, a fall diagnosis that failed)
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_file(path), "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False)
        return {**row, "cached": False}

    def _measure(self, path: str) -> dict:
        from . import motion_labels
        from .compare import compute_metrics, load_item
        from .problems import KINDS
        from .retarget_quality import SCORE_LABELS

        o = self.opts
        fk, limits = self._tools()
        item = load_item(path, robot=o.robot, smooth=o.smooth, fps=o.fps, csv_fps=o.csv_fps, smpl_model_dir=o.smpl_model_dir,
                         swing_clearance=o.swing_clearance_cm / 100.0, foot_flat=o.foot_flat,
                         self_collision=o.self_collision, log=None)
        compute_metrics(item, fk, limits)
        m = item.metrics
        lost = (m.get("_quality") or {}).get("score_lost") or {}
        worst = max(lost.items(), key=lambda kv: kv[1])[0] if lost else None
        probs = {k: round(sum(b - a for a, b in sp), 2) for k, sp in (m.get("_problems") or {}).items()}
        longest = max(probs.items(), key=lambda kv: kv[1])[0] if probs else None
        objs = item.human.objects if item.human is not None else []
        row = {"kind": item.kind, "duration_s": round(item.robot.duration, 3), "fps": item.robot.fps,
               "retarget_score": m.get("retarget_score"), "grade": m.get("retarget_grade"),
               "qc": m.get("qc"), "qc_notes": m.get("qc_notes") or "",
               "main_loss": SCORE_LABELS.get(worst, worst) if worst else None, "score_lost": lost,
               "problems_s": round(sum(probs.values()), 2), "problem_seconds": probs,
               "worst_problem": KINDS[longest][0] if longest in KINDS else None,
               "objects": len(objs), "object_names": [ob.name for ob in objs], "retarget": item.retarget or None}
        for k in ("pose_err_deg", "contact_mismatch_pct", "joint_limit_pct", "self_collision_pct", "planted_slip_pct",
                  "penetration_pct", "swing_low_pct", "static_unbalanced_pct", "hand_obj_reach_pct", "hand_obj_err_cm",
                  "hand_obj_contact_s"):
            v = m.get(k)
            row[k] = None if v is None or v != v else round(float(v), 3)  # NaN -> None (JSON)
        solved = item.info.get("solved_motion")
        lab = motion_labels.load_for(path, item.robot.fps, item.robot.duration, also=[solved] if solved else ())
        source = "file" if lab is not None and not lab.error else None
        if source is None and o.rules and item.human is not None and item.human.kind == "skeleton":
            from . import autolabel

            lab = autolabel.label_motion(item.human, o.rules, item.robot.duration)
            source = "auto" if not lab.error else None
        row["labels"], row["label_segments"] = source, len(lab.segments) if source else None
        if source:
            secs: dict[str, float] = {}
            for s in lab.segments:
                key = f"{s.track}: {s.label}" if s.track else s.label
                secs[key] = round(secs.get(key, 0.0) + max(0.0, min(s.end, item.robot.duration) - s.start), 3)
            row["label_seconds"] = secs
        if o.physics:
            row.update(self._physics(item.robot))
        return row

    def _physics(self, robot) -> dict:
        """The MuJoCo harness check (retlens.policy_replay "harness") of the retarget."""
        from . import policy_replay as pr

        try:
            if self._sim is None:
                self._sim = pr.G1Sim(pr.gmt_paths()["model"], "harness")
            m = pr.run(self._sim, pr.Reference.from_motion(robot), hold_s=1.0).metrics
        except Exception as e:
            return {"phys_error": f"{type(e).__name__}: {e}"}
        from .compare import _issue_ko
        from .diagnosis import CAUSE_KO, cause_counts_text

        if m.get("fall_diagnosis_error"):
            self.log(f"MuJoCo fall diagnosis failed: {m['fall_diagnosis_error']}")
        pull = (m.get("harness_force_per_body_weight") or {}).get("mean")
        first = m.get("first_fall_cause")
        return {"phys_falls": m["falls"], "phys_harness_pct": None if pull is None else round(100 * pull, 1),
                "phys_saturated_pct": round(100 * m["torque_saturated_ratio"], 1),
                "phys_ok": "통과" if m.get("consistent") else "; ".join(map(_issue_ko, m.get("issues", []))),
                # the falls inside the clip: the first one's cause, and how many per cause
                "phys_first_cause": CAUSE_KO.get(first, first) if first else None,
                "phys_fall_causes": cause_counts_text(m.get("fall_diagnosis") or []) or None,
                **({"phys_diagnosis_error": m["fall_diagnosis_error"]} if m.get("fall_diagnosis_error") else {})}

    # ------------------------------------------------------------ many files
    def run(self, files: list[str], progress: Callable[[int, int, dict], None] | None = None,
            cancel: Callable[[], bool] | None = None) -> list[dict]:
        """Rows of these files in order; progress(done, total, row) after each, cancel() checked before each
        (a stopped run returns the rows done so far; running it again picks up from the cache)."""
        rows = []
        for k, f in enumerate(files):
            if cancel is not None and cancel():
                break
            row = self.process(f)
            rows.append(row)
            if progress is not None:
                progress(k + 1, len(files), row)
        return rows


def totals(rows: list[dict]) -> dict:
    """Counts and seconds of the rows: all, readable, with errors, QC FAIL / WARN, physics falls (and the
    rows per first fall cause, {Korean cause: rows}, the most common first), labelled."""
    ok = [r for r in rows if not r.get("error")]
    first = Counter(r["phys_first_cause"] for r in ok if r.get("phys_first_cause"))
    return {"motions": len(rows), "read": len(ok), "errors": len(rows) - len(ok),
            "total_s": round(sum(r.get("duration_s") or 0.0 for r in ok), 2),
            "qc_fail": sum(r.get("qc") == "FAIL" for r in ok), "qc_warn": sum(r.get("qc") == "WARN" for r in ok),
            "with_falls": sum(bool(r.get("phys_falls")) for r in ok), "first_fall_causes": dict(first.most_common()),
            "labelled": sum(bool(r.get("labels")) for r in ok), "with_objects": sum(bool(r.get("objects")) for r in ok)}


def cell(row: dict, key: str, fmt: str) -> str:
    v = row.get(key)
    if v is None or v == "":
        return ""
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def write_csv(rows: list[dict], path: str) -> str:
    """One line per row with the table's columns (UTF-8 with BOM: Excel reads the Korean)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([title for _k, title, _f in COLUMNS])
        for r in rows:
            w.writerow([cell(r, k, fmt) for k, _t, fmt in COLUMNS])
    return os.path.abspath(path)
