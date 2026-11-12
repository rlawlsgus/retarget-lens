"""데이터셋 일괄 처리: every motion file of a capture session (or several) retargeted, measured and summed up
in one row each, for a table to sort and filter (RetLens's 데이터셋 tab, retlens-cli batch).

    b = Batch(BatchOptions(physics=True, rules="my.rules.yaml"))
    rows = b.run(files, progress=lambda done, total, row: ..., cancel=lambda: False)

Per file: the retarget (cached like any retarget) with the corrections of the options, QC, 리타게팅 점수 and
what cost it the most, the foot / balance / quality metrics, the problem spans (retlens.problems: seconds per
kind), the objects captured with it (FBX; a C3D: its solved motion's) and how well the robot's hands meet them,
what the file's reader left out (file_warnings), a C3D's solved motion and its take warning, its labels (the label
file next to it, else 자동 라벨 by the options' rule file) and, with physics on, the MuJoCo harness check
(falls, the first fall's cause and the falls per cause (retlens/diagnosis.py), harness force, verdict). A file
that cannot be read gives a row with "error".

Rows are cached per file (path, size, modification time), a C3D's solved motion (compare.find_take: which file,
its size and modification time, its props), its label files (size, modification time) and options (retarget
corrections, physics with policy_replay.RESULT_VERSION, configs/physics.yaml's content and the G1 MuJoCo model file,
the rule file and its modification time), so a run that was stopped or a folder run again skips what is done. A
folder's label table (labels.csv / labels.json) is not in the key: a cached row's labels are read again from the
label files, so editing one row of the table does not make every row of the folder again. A row whose physics
check failed (phys_error) is not cached: it is tried again next time.
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

BATCH_VERSION = 4  # bump when a row's meaning changes (old cached rows are then computed again)
# 2: rows keep where the problems are (problem_spans, qc_bad_spans, phys_fall_times_s) for retlens.dataset
# 3: a C3D's solved motion is the one next to it (compare.find_take); label files and physics config in the key
# 4: a C3D's solved motion in the key and its objects in the row; take_warning, solved_motion, solved_elsewhere,
#    file_warnings, phys_torque_limits_missing; folder label tables read again for a cached row (not in the key)

EXPORT_FOLDER = "retlens_export"  # the window's default folder for 로봇 모션 내보내기, below the motion's own folder

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
    ("phys_harness_pct", "보조 힘 (%)", "{:.0f}"), ("phys_ok", "물리 판정", "{}"), ("phys_error", "물리 오류", "{}"),
    ("kind", "종류", "{}"), ("error", "오류", "{}"), ("take_warning", "촬영 주의", "{}"), ("file_warnings", "파일 주의", "{}"),
    ("props_error", "물체 파일 오류", "{}"), ("file", "파일", "{}"),
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
    """Files as given; folders give the motion files under them (label files and SMPL-X shape files left out, and
    prop files a person FBX of the inputs draws with it: retlens.props.find_props). retlens_export folders below a
    folder are left out (robot copies of its motions: each take would count twice); one given is read."""
    from .compare import _walk, is_motion_file

    out, found = [], set()
    for p in inputs:
        if os.path.isdir(p):
            for root, entries in _walk(p):  # the listing's own file times: no stat call per csv
                below = os.path.relpath(root, p).split(os.sep)
                if any(part.lower() == EXPORT_FOLDER for part in below):
                    continue
                new = [e.path for e in entries if is_motion_file(e.path, e)]
                out += new
                found |= set(new)
        else:
            out.append(p)
    return _without_props(out, found)


def _without_props(files: list[str], found: set) -> list[str]:
    """files without those of `found` (found in folders, not given) that a person FBX of files uses as its props: a
    prop file one folder above its people, or next to a take variant (pick_001_slow.fbx + pick_001_Prop.fbx), which
    retlens.props.is_prop_file leaves in folder listings."""
    from .props import find_props, prop_head, take_names

    def key(f):
        return os.path.normcase(os.path.abspath(f))

    def head(f):
        return prop_head(os.path.splitext(os.path.basename(f))[0])

    fbx = [f for f in files if f.lower().endswith(".fbx")]
    named = {key(f) for f in fbx if f in found and head(f) is not None}
    if not named:
        return files
    heads = {head(f) for f in fbx if key(f) in named}
    # find_props only for people of those takes (it gives prop files named after one of the person's take_names):
    # each call lists the folders again, so asking every person of a large folder took minutes
    used = {key(p) for f in fbx if key(f) not in named and heads.intersection(take_names(f))
            for p in find_props(f)[0]}  # a prop file has no props
    return [f for f in files if key(f) not in (named & used)]


class Batch:
    def __init__(self, opts: BatchOptions | None = None, cache_dir: str | None = None, fk=None, limits=None,
                 log: Callable | None = None):
        """fk / limits: an analysis.FootKinematics and the robot's joint limits to reuse (made on first use)."""
        self.opts = opts or BatchOptions()
        self.cache_dir = cache_dir or paths.cache_dir("batch")
        self._fk, self._limits = fk, limits
        self.log = log or (lambda *_: None)
        self._sim = None  # the MuJoCo harness sim, made once
        self._last = None  # (path, item, labels) of the motion measured last (retlens.dataset writes it next)
        self._library = None  # the motion folders' files by name (compare.library_files), listed once: C3D solves

    # ------------------------------------------------------------ cache
    def key(self, path: str) -> str:
        st = os.stat(path)
        o = asdict(self.opts)
        rules = o.pop("rules")
        o.pop("smpl_model_dir")
        rule_id = [os.path.abspath(rules), os.path.getmtime(rules)] if rules and os.path.isfile(rules) else rules
        # the retargeting pipeline and the robot model's content: a row made by another pipeline or an
        # edited model is made again (as the retarget cache would retarget)
        from .compare import PIPELINE_VERSION
        from .robot_profile import load as load_robot

        prof = load_robot(self.opts.robot)
        o["robot"] = prof.digest
        if o["physics"]:  # MuJoCo results that change meaning, an edited physics config (gains, fall rules) or
            # another G1 model make the physics rows again (only those)
            from . import policy_replay as pr

            ids = [pr.RESULT_VERSION, _content_id(paths.resource("configs", "physics.yaml"))]
            if prof.builtin:  # the G1 runs on GMT's model (another robot: its digest above)
                from .physics_runner import _file_id

                model = pr.gmt_paths()["model"]
                ids.append(_file_id(model) if os.path.isfile(model) else None)
            o["physics"] = ids
        if prof.has_fingers():  # rows of robots whose fingers follow the person's (retlens.fingers)
            from .fingers import VERSION as FINGERS

            o["fingers"] = FINGERS
        parts = [BATCH_VERSION, PIPELINE_VERSION, os.path.abspath(path), st.st_size, st.st_mtime_ns, o, rule_id]
        from .compare import MARKER_EXT
        from .motion_labels import FOLDER_TABLES, candidates
        from .props import signature

        solve = None
        if path.lower().endswith(MARKER_EXT):  # a C3D's row is made from its solved motion: another solve (one put
            # beside it), or the same one exported again, makes it again
            solve = self.solved_motion(path)
            parts.append([solve, *_stat(solve)] if solve else None)
        # the label files next to it (and to a C3D's solve) (labels()): adding or editing one makes the row again. A
        # folder table is left out: a cached row reads its labels again (_labels_now), and one edited row of the table
        # would make every row of the folder again (the physics check too)
        labels = [[p, *_stat(p)] for p in candidates(path, also=[solve] if solve else ())
                  if os.path.basename(p).lower() not in FOLDER_TABLES and os.path.isfile(p)]
        if labels:
            parts.append(labels)
        for f in (path, solve):  # props of the take in a file of their own (retlens.props): only when there are
            if f and f.lower().endswith(".fbx"):  # some, so other files keep their rows
                props = signature(f)
                if props:
                    parts.append(props)
        raw = json.dumps(parts, sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def solved_motion(self, path: str) -> str | None:
        """The solved motion a C3D's row is made from (compare.find_take, as compare.load_item picks it): the one
        beside it, else from the motion folders (listed once by this Batch). Beside it only the names find_take takes
        are looked for (case does not matter in Windows file names): a folder of many takes is not listed per C3D."""
        from .compare import find_take, library_files

        base = os.path.splitext(os.path.abspath(path))[0]
        # in a folder listing's order (two AMASS fits: _poses first, as find_take finds them in a listing)
        beside = [f for f in (base + e for e in (".bvh", ".fbx", "_poses.npz", "_stageii.npz")) if os.path.isfile(f)]
        solve = find_take(path, beside)
        if solve is None:  # find_take prefers the C3D's own folder: only when nothing is there, the library
            if self._library is None:
                self._library = _by_name(f for fs in library_files().values() for f in fs)
            stem = os.path.basename(base).lower()
            solve = find_take(path, [f for _i, f in sorted(x for n in (stem, f"{stem}_stageii", f"{stem}_poses")
                                                            for x in self._library.get(n, ()))])
        return solve

    def _cache_file(self, path: str) -> str:
        stem = os.path.splitext(os.path.basename(path))[0][:48]
        return os.path.join(self.cache_dir, f"{stem}-{self.key(path)}.json")

    def cached(self, path: str) -> dict | None:
        """The row of this file and these options from the cache (labels read again: _labels_now); None if none."""
        try:
            cache = self._cache_file(path)
        except (OSError, ValueError):
            return None
        return self._from_cache(path, cache)

    def _from_cache(self, path: str, cache: str) -> dict | None:
        try:
            with open(cache, encoding="utf-8") as f:
                row = json.load(f)
        except (OSError, ValueError):
            return None
        return self._labels_now(path, row)

    def _labels_now(self, path: str, row: dict) -> dict | None:
        """A cached row with its labels read again from the label files (a folder table is not in the key); None when
        only the motion can give them (자동 라벨, now that the folder table has no rows for it)."""
        from . import motion_labels

        fps, dur = row.get("fps"), row.get("duration_s")
        if not fps or dur is None:
            return row
        dur = round(dur * fps) / fps  # frames / fps, as measured (duration_s is rounded)
        solved = row.get("solved_motion")
        lab = motion_labels.load_for(path, fps, dur, also=[solved] if solved else ())
        if lab is not None and not lab.error:
            source = "file"
        elif row.get("labels") == "auto":  # still no label file: its 자동 라벨 stand (the rule file is in the key)
            return row
        elif row.get("labels") == "file" and self.opts.rules:  # the table's rows for it went: 자동 라벨 now
            return None
        else:
            lab, source = None, None
        return {**{k: v for k, v in row.items() if k != "label_seconds"}, **_label_fields(lab, source, dur)}

    # ------------------------------------------------------------ one file
    def _tools(self):
        if self._fk is None:
            from .analysis import FootKinematics

            self._fk = FootKinematics(self.opts.robot)
        if self._limits is None:  # the robot's own limits (its URDF's where it has one, as the window's)
            from .robot_profile import load as load_robot

            self._limits = load_robot(self.opts.robot).limits()
        return self._fk, self._limits

    def process(self, path: str) -> dict:
        """The row of one file: from the cache when this file and these options were done before. The cache file is
        named before the file is measured: a label file saved meanwhile makes the row again next time."""
        try:
            cache = self._cache_file(path)
        except (OSError, ValueError):  # e.g. a file that is gone: its row is an error, not kept
            cache = None
        row = self._from_cache(path, cache) if cache else None
        if row is not None:
            return {**row, "cached": True}
        t0 = time.time()
        try:
            row = self._measure(path)
        except Exception as e:  # one bad file never stops the batch
            row = {"error": f"{type(e).__name__}: {e}"}
        row = {"file": os.path.abspath(path), "folder": os.path.basename(os.path.dirname(os.path.abspath(path))),
               "name": os.path.splitext(os.path.basename(path))[0], **row, "seconds_taken": round(time.time() - t0, 2)}
        failed = any(k in row for k in ("error", "phys_error", "phys_diagnosis_error", "props_error"))
        if cache and not failed:  # failures are tried again next time (a missing Blender, a file being written, a
            # physics check, a fall diagnosis or a prop file that failed)
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False)
        return {**row, "cached": False}

    def load_item(self, path: str):
        """The motion as the options make it (a human one retargeted with their corrections; cached)."""
        from .compare import load_item

        o = self.opts
        return load_item(path, robot=o.robot, smooth=o.smooth, fps=o.fps, csv_fps=o.csv_fps, smpl_model_dir=o.smpl_model_dir,
                         swing_clearance=o.swing_clearance_cm / 100.0, foot_flat=o.foot_flat,
                         self_collision=o.self_collision, log=None)

    def labels(self, path: str, item):
        """(labels, "file" | "auto" | None): the label file next to the motion, else 자동 라벨 by the options'
        rule file (a human skeleton only)."""
        from . import motion_labels

        solved = item.info.get("solved_motion")
        lab = motion_labels.load_for(path, item.robot.fps, item.robot.duration, also=[solved] if solved else ())
        if lab is not None and not lab.error:
            return lab, "file"
        if self.opts.rules and item.human is not None and item.human.kind == "skeleton":
            from . import autolabel

            lab = autolabel.label_motion(item.human, self.opts.rules, item.robot.duration)
            if not lab.error:
                return lab, "auto"
        return None, None

    def item_and_labels(self, path: str):
        """(motion, labels) of a file: the ones just measured when it was the last, else loaded (cached)."""
        last = self._last
        if last is not None and os.path.normcase(last[0]) == os.path.normcase(os.path.abspath(path)):
            return last[1], last[2]
        item = self.load_item(path)
        return item, self.labels(path, item)[0]

    def _measure(self, path: str) -> dict:
        from .compare import compute_metrics, file_warnings, measured_human
        from .dataset import qc_bad_spans
        from .problems import KINDS
        from .retarget_quality import SCORE_LABELS

        if not os.path.exists(path):
            raise FileNotFoundError("없는 파일·폴더입니다")
        fk, limits = self._tools()
        item = self.load_item(path)
        compute_metrics(item, fk, limits)
        m = item.metrics
        lost = (m.get("_quality") or {}).get("score_lost") or {}
        worst = max(lost.items(), key=lambda kv: kv[1])[0] if lost else None
        probs = {k: round(sum(b - a for a, b in sp), 2) for k, sp in (m.get("_problems") or {}).items()}
        longest = max(probs.items(), key=lambda kv: kv[1])[0] if probs else None
        h = measured_human(item)  # a C3D: its solved skeleton's objects, which its hand-object numbers measure
        objs = h.objects if h is not None else []
        prop_errors = [f"{os.path.basename(e['file'])}: {e['error']}"  # (a broken shape file is in the cache key)
                       for e in (h.meta.get("props") or [] if h is not None else []) if e.get("error")]
        c3d = item.info.get("c3d") or {}
        tlm = m.get("phys_torque_limits_missing")  # a MuJoCo result's joints without a torque limit (not judged)
        row = {"kind": item.kind, "duration_s": round(item.robot.duration, 3), "fps": item.robot.fps,
               # where (retlens.dataset cuts these out): problem spans by kind, QC frames it cannot use
               "problem_spans": {k: [list(s) for s in sp] for k, sp in (m.get("_problems") or {}).items()},
               "qc_bad_spans": [list(s) for s in qc_bad_spans(item.robot, limits)],
               "retarget_score": m.get("retarget_score"), "grade": m.get("retarget_grade"),
               "qc": m.get("qc"), "qc_notes": m.get("qc_notes") or "",
               "main_loss": SCORE_LABELS.get(worst, worst) if worst else None, "score_lost": lost,
               "problems_s": round(sum(probs.values()), 2), "problem_seconds": probs,
               "worst_problem": KINDS[longest][0] if longest in KINDS else None,
               "objects": len(objs), "object_names": [ob.name for ob in objs], "retarget": item.retarget or None,
               # a C3D: the solve its robot is retargeted from, not beside it (found in a motion folder), likely
               # another take (its markers far from the solve's pelvis)
               "solved_motion": item.info.get("solved_motion"), "solved_elsewhere": c3d.get("solved_elsewhere") or None,
               "take_warning": c3d.get("take_warning") or None,
               # what the file's reader left out (e.g. a second person's skeleton in an FBX: compare.file_warnings)
               "file_warnings": "; ".join(file_warnings(item)) or None,
               "phys_torque_limits_missing": int(tlm) if tlm else None}
        if prop_errors:  # a prop file that could not be read: the row is made again next time (process)
            row["props_error"] = "; ".join(prop_errors)
        for k in ("pose_err_deg", "contact_mismatch_pct", "joint_limit_pct", "self_collision_pct", "planted_slip_pct",
                  "penetration_pct", "swing_low_pct", "static_unbalanced_pct", "hand_obj_reach_pct", "hand_obj_err_cm",
                  "hand_obj_contact_s"):
            v = m.get(k)
            row[k] = None if v is None or v != v else round(float(v), 3)  # NaN -> None (JSON)
        lab, source = self.labels(path, item)
        row.update(_label_fields(lab, source, item.robot.duration))
        if self.opts.physics:
            row.update(self._physics(item.robot))
        self._last = (os.path.abspath(path), item, lab)
        return row

    def _physics(self, robot) -> dict:
        """The MuJoCo harness check (retlens.policy_replay "harness") of the retarget."""
        from . import policy_replay as pr
        from .robot_profile import load as load_robot

        g1 = load_robot(self.opts.robot).builtin
        if self._sim is None:  # what is missing, said as the window says it (the G1's MuJoCo model: install GMT)
            from .policy_runner import problem

            why = problem("harness", robot=self.opts.robot)
            if why:
                return {"phys_error": why}
        try:
            if self._sim is None:  # the G1 on GMT's model; another robot on its own (policy_replay.RobotSim)
                self._sim = pr.G1Sim(pr.gmt_paths()["model"], "harness") if g1 else pr.RobotSim(self.opts.robot, "harness")
            ref = pr.Reference.from_motion(robot, joints=None if g1 else self._sim.joint_names)
            m = pr.run(self._sim, ref, hold_s=1.0).metrics
        except Exception as e:
            return {"phys_error": f"{type(e).__name__}: {e}"}
        from .compare import _issue_ko
        from .diagnosis import CAUSE_KO, cause_counts_text

        if m.get("fall_diagnosis_error"):
            self.log(f"MuJoCo fall diagnosis failed: {m['fall_diagnosis_error']}")
        pull = (m.get("harness_force_per_body_weight") or {}).get("mean")
        first = m.get("first_fall_cause")
        missing = m.get("torque_limits_missing")  # joints given 1000 N m: their torque saturation is not judged
        return {"phys_falls": m["falls"], "phys_fall_times_s": list(m.get("fall_times_s") or []),
                "phys_harness_pct": None if pull is None else round(100 * pull, 1),
                "phys_saturated_pct": round(100 * m["torque_saturated_ratio"], 1),
                "phys_torque_limits_missing": int(missing) if missing else None,
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
    rows per first fall cause, {Korean cause: rows}, the most common first), physics checks that failed, labelled."""
    ok = [r for r in rows if not r.get("error")]
    first = Counter(r["phys_first_cause"] for r in ok if r.get("phys_first_cause"))
    return {"motions": len(rows), "read": len(ok), "errors": len(rows) - len(ok),
            "total_s": round(sum(r.get("duration_s") or 0.0 for r in ok), 2),
            "qc_fail": sum(r.get("qc") == "FAIL" for r in ok), "qc_warn": sum(r.get("qc") == "WARN" for r in ok),
            "with_falls": sum(bool(r.get("phys_falls")) for r in ok), "first_fall_causes": dict(first.most_common()),
            "phys_errors": sum(bool(r.get("phys_error")) for r in ok),
            "labelled": sum(bool(r.get("labels")) for r in ok), "with_objects": sum(bool(r.get("objects")) for r in ok)}


def _label_fields(lab, source: str | None, duration: float) -> dict:
    """A row's labels: where they came from ("file" / "auto" / None), how many segments and, with labels, the seconds
    per label ("track: label" on a track; segments cut at the motion's end)."""
    out = {"labels": source, "label_segments": len(lab.segments) if source else None}
    if source:
        secs: dict[str, float] = {}
        for s in lab.segments:
            key = f"{s.track}: {s.label}" if s.track else s.label
            secs[key] = round(secs.get(key, 0.0) + max(0.0, min(s.end, duration) - s.start), 3)
        out["label_seconds"] = secs
    return out


def _by_name(files) -> dict:
    """{lower-case file name without its extension: [(place in the listing, path)]} of files."""
    out: dict = {}
    for i, f in enumerate(files):
        out.setdefault(os.path.splitext(os.path.basename(f).lower())[0], []).append((i, f))
    return out


def _stat(path: str) -> list:
    """[size, modification time (ns)] of a file, [None, None] when it is gone."""
    try:
        st = os.stat(path)
    except OSError:
        return [None, None]
    return [st.st_size, st.st_mtime_ns]


def _content_id(path: str) -> str | None:
    """sha1 of a file's bytes (None when it cannot be read)."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


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
