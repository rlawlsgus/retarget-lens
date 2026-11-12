"""retlens-cli: RetLens without a window, for scripts and AI agents. Every command prints one
JSON object on stdout (progress goes to stderr; --pretty, before or after the command, indents it);
exit code 0 = ok, 1 = error ({"error": ...}, also for a mistyped command or option);
autolabel / summary / batch / export / c3d-qc: 1 = no motion done, 2 = some not (their rows say why;
batch / export: also a physics check that failed).

    retlens-cli info                        # version, file locations, 환경 점검
    retlens-cli version                     # just the version (fast: nothing else is loaded)
    retlens-cli update                      # 업데이트 확인: the latest GitHub release vs this one (check only)
    retlens-cli robot [MODEL.xml|.urdf]     # the robot's parts as retargeting finds them (default: 환경 설정)
    retlens-cli library --query walk        # motion files (with CMU descriptions)
    retlens-cli inspect FILE [FILE ...]     # load (retarget if needed): QC, metrics, C3D QC
    retlens-cli metrics FILE [FILE ...] [--ref 0]   # the 분석 table (RMSE vs ref)
    retlens-cli compare A B [--tol 3] [--no-heading] [--align]   # 겹쳐 비교 numbers
    retlens-cli align REF FILE [FILE ...]   # 기준에 시간 자동 정렬
    retlens-cli retarget FILE --out OUT.npz # save the robot motion (+ .json)
      (commands that open motions take --robot MODEL (unitree_g1 or an MJCF / URDF; default 환경 설정),
       --smooth HZ, --foot-flat, --swing-clearance CM and --self-collision for human ones)
    retlens-cli autolabel FILE [FILE ...] [--rules R.yaml] [--out DIR]   # 자동 라벨 by a rule file (no retargeting)
    retlens-cli summary FILE|DIR ... [--rules R.yaml] [--csv OUT.csv]   # 데이터셋 요약: length, label time, objects
    retlens-cli batch FILE|DIR ... [--physics] [--rules R.yaml] [--csv OUT.csv]   # 일괄 처리: retarget + measure each
    retlens-cli export FILE|DIR ... --out DIR [--qc WARN] [--physics] [--cut] [--formats npz,csv,pkl]
                                            # 데이터셋 내보내기: the motions that pass, in pieces with --cut, + manifest
    retlens-cli c3d-qc FILE.c3d [...]       # raw marker QC only (no retargeting), by file name
    retlens-cli physics FILE [--balance harness]   # physics check: MuJoCo with the pelvis harness (seconds);
                                            # --balance pd / gmt (MuJoCo), isaac [--assist 1] (needs the EULA accepted)
    retlens-cli video FILE --out X.mp4 [--physics [--balance B]]   # Isaac recording (needs the EULA accepted)
    retlens-cli setup [--offline]           # 설치 도우미: what is here, what is missing, what can be installed
    retlens-cli setup --install blender     # install one, only when needed (gmt / isaac: --accept-license)
    retlens-cli api                         # the running RetLens window's HTTP API (url, token)
    retlens-cli install-skill [--project DIR]   # copy the AI guide (SKILL.md) for Claude Code

retlens-cli.exe sits next to RetLens.exe; from the source tree run python tools\retlens_cli.py <command>.
Guide for AI agents: install-skill copies it (SKILL.md) where Claude Code finds it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))


def _log(msg) -> None:
    print(f"[retlens-cli] {msg}", file=sys.stderr, flush=True)


def _err(e: BaseException) -> str:
    """'<type>: <why>' of an exception, a path in it as it is (the str() of a KeyError, or of an OSError that names
    its file, gives it quoted with its backslashes doubled)."""
    why = e
    if isinstance(e, KeyError) and e.args:
        why = e.args[0]
    elif isinstance(e, OSError) and e.filename is not None and e.strerror:
        why = f"{e.strerror}: {e.filename}" + (f" -> {e.filename2}" if e.filename2 is not None else "")
    return f"{type(e).__name__}: {why}"


def _check_swing(args) -> None:
    if not 0.0 <= args.swing_clearance <= 10.0:
        raise ValueError("--swing-clearance must be 0 (off) to 10 cm")


def _scene(args):
    from retlens.app import api_core

    _check_swing(args)
    extra = {"robot": args.robot} if getattr(args, "robot", None) else {}
    return api_core.headless_scene(log=_log, smooth=args.smooth, foot_flat=args.foot_flat,
                                   swing_clearance_cm=args.swing_clearance, self_collision=args.self_collision, **extra)


def _open(scene, files: list[str]):
    items = []
    for f in files:
        _log(f"opening {f}")
        items.append(scene.add(f))
    return items


def skill_source() -> str:
    from retlens import paths

    for p in (paths.resource("ai", "retlens", "SKILL.md"),
              os.path.join(paths.REPO_ROOT, ".claude", "skills", "retlens", "SKILL.md")):
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("SKILL.md not found (installed: <program>\\_internal\\ai\\retlens; repository: "
                            ".claude\\skills\\retlens)")


def run(args) -> dict:
    from retlens.app import api_core

    c = args.cmd
    if c == "info":
        from retlens import __version__, paths

        return {"app": "RetLens", "version": __version__, "api_version": api_core.API_VERSION,
                "locations": dict(paths.describe()),
                "isaac_eula_accepted": api_core.eula_accepted(), **api_core.checks()}
    if c == "update":  # 업데이트 확인 only: installing happens in the window (도움말 > 업데이트 확인)
        from retlens import install

        chk = install.check_latest()
        out = {**chk.to_dict(), "installed": install.is_installed(), "portable": install.is_portable(),
               "install_dir": install.install_dir(), "releases_page": install.RELEASES_PAGE}
        return _Exit(out, 1) if chk.error else out
    if c == "robot":  # what retargeting finds in a robot model (no motion needed)
        from retlens import settings
        from retlens.robot_profile import load as load_robot

        return {"robot": load_robot(args.model or settings.robot_spec()).describe()}
    if c == "library":
        return api_core.library(args.query, args.limit)
    if c == "api":
        from retlens.app.api_server import discovery

        d = discovery()
        if d is None:
            raise RuntimeError("RetLens is not running with its API on (환경 설정 > AI용 로컬 API)")
        return d
    if c == "setup":
        from retlens import prereqs

        if not args.install:
            return {"components": [st.to_dict() for st in prereqs.probe_all(online=not args.offline)]}
        last = [0.0]

        def progress(stage, done, total):
            if time.time() - last[0] > 2.0 or (total and done >= total):
                last[0] = time.time()
                _log(f"{stage} {done / 1e6:.0f}/{total / 1e6:.0f} MB" if total else stage)

        st = prereqs.install(args.install, accept=args.accept_license, source=args.source, progress=progress)
        return {"installed": args.install, **st.to_dict()}
    if c == "install-skill":
        src = skill_source()
        base = args.project or os.path.expanduser("~")
        dst = os.path.join(base, ".claude", "skills", "retlens", "SKILL.md")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return {"installed": dst, "from": src}
    if c == "c3d-qc":  # {file name (its path when two have that name): QC or {"error"}}; 1 = all failed, 2 = some
        from retlens.dataset import path_key
        from retlens.io.c3d import load_c3d
        from retlens.markers import marker_qc

        files = list({path_key(f): f for f in args.files}.values())  # each file once, however it is spelled
        names = [os.path.basename(f).lower() for f in files]
        out, failed = {}, 0
        for f, n in zip(files, names):
            key = os.path.basename(f) if names.count(n) == 1 else os.path.abspath(f)
            try:
                out[key] = marker_qc(load_c3d(f))
            except Exception as e:  # one bad file never loses the others' results
                failed += 1
                out[key] = {"error": _err(e)}
        out = api_core.jsonable(out)
        return _Exit(out, 1) if failed and failed == len(files) else _Exit(out, 2) if failed else out
    if c == "autolabel":
        return autolabel(args)
    if c == "summary":
        return summary(args)
    if c == "batch":
        return batch(args)
    if c == "export":
        return export(args)
    if c == "retarget":
        from retlens import settings
        from retlens.compare import load_item
        from retlens.dataset import path_key

        _check_swing(args)
        out, ext = os.path.abspath(args.out), os.path.splitext(args.out)[1].lower()
        if ext and ext != ".npz":
            raise ValueError(f"--out must be a .npz file (csv / pkl: use export --formats): {args.out}")
        out = os.path.splitext(out)[0] + ".npz"  # the name numpy writes (it adds .npz to any other ending, .NPZ too)
        if not os.path.exists(args.file):
            raise FileNotFoundError(f"없는 파일: {args.file}")
        if path_key(out) == path_key(args.file):  # however either is spelled (8.3 short name, mapped drive)
            raise ValueError(f"--out is the motion file itself: {out}")
        os.makedirs(os.path.dirname(out), exist_ok=True)  # before retargeting, as export does
        item = load_item(args.file, robot=args.robot or settings.robot_spec(), smooth=args.smooth,
                         swing_clearance=args.swing_clearance / 100.0,
                         foot_flat=args.foot_flat, self_collision=args.self_collision, smpl_model_dir=_smpl(), log=_log)
        item.robot.save_npz(out)
        with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(api_core.jsonable(item.info), f, ensure_ascii=False, indent=1)
        return {"out": out, "frames": item.robot.num_frames, "fps": item.robot.fps, "kind": item.kind}

    named = {"inspect": lambda: args.files, "metrics": lambda: args.files, "align": lambda: [args.ref, *args.files],
             "compare": lambda: [args.a, args.b], "physics": lambda: [args.file], "video": lambda: [args.file]}
    missing = [p for p in named.get(c, list)() if not os.path.exists(p)]
    if missing:  # said before the 3D scene starts (seconds)
        raise FileNotFoundError(f"없는 파일: {', '.join(missing)}")
    scene = _scene(args)
    try:
        if c == "inspect":
            return {"motions": [api_core.item_info(scene, it) for it in _open(scene, args.files)]}
        if c == "metrics":
            items = _open(scene, args.files)
            ref = api_core.find_item(scene, args.ref) if args.ref is not None else items[0]
            return api_core.metrics_table(scene, ref)
        if c == "align":
            items = _open(scene, [args.ref, *args.files])
            return api_core.align(scene, items[0])
        if c == "compare":
            a, b = _open(scene, [args.a, args.b])
            notes = scene.auto_align(a) if args.align else None
            out = api_core.compare(scene, a, b, heading=not args.no_heading, tol_cm=args.tol)
            return {**out, "align_notes": notes} if notes is not None else out
        if c in ("physics", "video"):
            isaac = c == "video" or args.balance == "isaac"  # videos are Isaac recordings
            if isaac:
                if not (api_core.eula_accepted() or args.isaac_accept_eula):
                    raise PermissionError("Isaac Sim needs the NVIDIA Omniverse EULA accepted by the user: open RetLens "
                                          "and accept it once (or the user passes --isaac-accept-eula themselves)")
                scene.runner.accept_eula = True
            # a recording without physics needs Isaac only: its robot, not the MuJoCo balance modes
            mode = args.balance if c == "physics" or args.physics else "isaac"
            why = scene.balance_problem(mode) if c == "physics" or args.physics else scene.robot_physics_problem("isaac")
            if why:
                raise RuntimeError(f"{mode}: {why}")
            scene.set_balance(args.balance)
            (item,) = _open(scene, [args.file])
            if c == "physics":
                scene.set_assist(args.assist)
                scene.set_physics(True, "cli")
                _log("waiting for Isaac (about a minute for a short clip)" if args.balance == "isaac"
                     else "waiting for MuJoCo (a few seconds per clip)")
                done = api_core.wait_jobs(scene, args.timeout)
                why = _physics_failed(scene, item, done, args.timeout)
                out = {"finished": done, **api_core.item_info(scene, item)}
                return _Exit({**out, "error": why}, 1) if why else out
            scene.set_physics(bool(args.physics), "cli")
            if args.physics:
                why = _physics_failed(scene, item, api_core.wait_jobs(scene, args.timeout), args.timeout)
                if why:  # never a recording of the motion as it is, passed off as the simulated one
                    raise RuntimeError(why)
            if args.out:
                scene.opts.video_dir = os.path.dirname(os.path.abspath(args.out)) or "."
            job = scene.save_video(item)
            done = api_core.wait_jobs(scene, args.timeout)
            result = job.result
            if result and args.out and os.path.abspath(result) != os.path.abspath(args.out):
                shutil.copy2(result, args.out)
                result = os.path.abspath(args.out)
            return {"finished": done, "state": job.state, "video": result, "message": job.message or None}
        raise ValueError(f"unknown command {c}")
    finally:
        scene.shutdown()
        scene.server.stop()


def _physics_failed(scene, item, done: bool, timeout: float) -> str | None:
    """Why the physics run of item gave no result (None: it did, or item is a simulated motion already)."""
    if not done:
        return f"physics did not finish within {timeout:g} s"
    if scene.is_sim_result(item):
        return None
    job = item.handles.get("phys_jobs", {}).get(scene.phys_key)
    end = time.time() + 30.0  # a finished run's result is read on the worker right after the job ends
    while job is not None and job.state == "done" and scene.shown(item) is item and time.time() < end:
        time.sleep(0.1)
    if scene.shown(item) is not item:
        return None
    said = job.message if job is not None and job.state != "done" else ""
    return "physics failed: " + (said or scene.phys_error or "no result")


def _smpl():
    from retlens import paths, settings

    return settings.find_smpl().path or paths.smpl_model_dir()


def batch(args) -> dict:
    """데이터셋 일괄 처리 (retlens.batch): every motion retargeted with the given corrections and measured, a row
    each (cached: a run again, or after a stop, skips what is done); --physics adds the MuJoCo harness check,
    --rules 자동 라벨 for motions without a label file. --csv writes the table. Exit code 1 when no motion
    could be read, 2 when some could not or their physics check failed (phys_error)."""
    from retlens import batch as bt
    from retlens.app import api_core

    if args.rules:
        from retlens import autolabel

        autolabel.check_rules(args.rules)  # a broken rule file stops here, not once per motion
    _check_swing(args)
    from retlens import settings

    opts = bt.BatchOptions(robot=args.robot or settings.robot_spec(), smooth=args.smooth, smpl_model_dir=_smpl(),
                           foot_flat=args.foot_flat,
                           swing_clearance_cm=args.swing_clearance, self_collision=args.self_collision,
                           physics=args.physics, rules=args.rules)
    files = bt.motion_files(args.inputs)
    rows = bt.Batch(opts).run(files, progress=lambda done, total, row: _log(
        f"{done}/{total} {row['name']}: " + (f"error {row['error']}" if row.get("error") else
                                            f"{row.get('qc')}, score {row.get('retarget_score')}"
                                            + (" (cached)" if row.get("cached") else ""))))
    out = {**bt.totals(rows), "options": api_core.jsonable(vars(opts)), "rows": api_core.jsonable(rows)}
    if args.csv:
        out["csv"] = bt.write_csv(rows, args.csv)
    errors = sum(bool(r.get("error")) for r in rows)
    return _Exit(out, 1) if rows and errors == len(rows) else _Exit(out, 2) if errors or out["phys_errors"] else out


def export(args) -> dict:
    """데이터셋 내보내기 (retlens.dataset): the motions under the inputs through 일괄 처리 (cached), the ones that pass
    --qc / --min-score / falls written into --out with their labels and manifest.json / manifest.csv. --cut takes
    out the QC frames that cannot be used, the --cut-kinds problem spans and the time around each fall (--physics),
    leaving pieces of --min-piece seconds or more; --range START END exports that time range of one motion. Exit
    code 1 when no motion could be read, 2 when some could not or their physics check failed (with --allow-falls
    they are written, phys_error in their clips)."""
    from retlens import batch as bt
    from retlens import dataset, settings
    from retlens.app import api_core
    from retlens.problems import KINDS

    if args.rules:
        from retlens import autolabel

        autolabel.check_rules(args.rules)
    _check_swing(args)
    kinds = tuple(k.strip() for k in args.cut_kinds.split(",") if k.strip())
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise ValueError(f"unknown --cut-kinds {', '.join(bad)} (one of {', '.join(KINDS)})")
    cut = dataset.CutOptions(qc=not args.no_cut_qc, kinds=kinds, falls=not args.no_cut_falls, pad_s=args.pad,
                             min_piece_s=args.min_piece) if args.cut else None
    opts = dataset.ExportOptions(qc=args.qc, min_score=args.min_score, allow_falls=args.allow_falls, cut=cut,
                                 formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
                                 labels=not args.no_labels, range_s=tuple(args.range) if args.range else None)
    bopts = bt.BatchOptions(robot=args.robot or settings.robot_spec(), smooth=args.smooth, smpl_model_dir=_smpl(),
                            foot_flat=args.foot_flat, swing_clearance_cm=args.swing_clearance,
                            self_collision=args.self_collision, physics=args.physics, rules=args.rules)
    m = dataset.Exporter(bopts, opts, args.out, log=_log).run(
        args.inputs, progress=lambda done, total, name: _log(f"{done}/{total} {name}"))
    out = {"out": os.path.abspath(args.out), "manifest": os.path.join(os.path.abspath(args.out), dataset.MANIFEST),
           "totals": m["totals"], "excluded": m["excluded"],
           "clips": [{**{k: c.get(k) for k in ("files", "source", "start_s", "end_s", "duration_s", "qc", "labels")},
                      **{k: c[k] for k in ("phys_error", "file_warnings") if c.get(k)}} for c in m["clips"]]}
    errors = sum(e["reason"].startswith(("읽지 못함", "내보내기 실패", "물리 검사 실패")) for e in m["excluded"])
    unchecked = m["totals"].get("phys_errors") or 0  # let in by --allow-falls although physics could not say
    out = api_core.jsonable(out)
    return _Exit(out, 1) if errors and errors == m["totals"]["motions"] else _Exit(out, 2) if errors or unchecked else out


def summary(args) -> dict:
    """데이터셋 요약 without retargeting: every motion's length, its labels (the label file next to it, or
    자동 라벨 by --rules) and the objects captured with it (FBX); totals per folder and per label (seconds of
    each track's segments, clipped to the motion). --csv writes one row per motion. C3D files are left out
    (their take's solved file counts), and so is every other file of a take in the same folder (X.bvh + X.fbx:
    the one export takes counts, the first of TAKE_ORDER that can be read, the objects of the take's FBX with it;
    "same_take" in their row), and an FBX of fewer than 8 joints (a prop file: "not_counted"). "warnings": what
    the file's reader left out (a second person's skeleton in an FBX). Folders are named from the inputs' common
    parent (day1/s01). Exit code 1 when no motion could be read, 2 when some could not."""
    import csv

    from retlens import autolabel as al
    from retlens import dataset, motion_labels
    from retlens.compare import human_format, load_skeleton
    from retlens.io import load_motion

    rules = args.rules
    if rules:
        al.check_rules(rules)
    from retlens.batch import motion_files

    listed, seen, real = [], set(), {}
    for f in motion_files(args.inputs):  # each file once, however it is spelled
        k = None if f.lower().endswith(".c3d") else dataset.path_key(f, real)
        if k is not None and k not in seen:
            seen.add(k)
            listed.append(os.path.abspath(f))
    files, same = dataset.pick_takes(listed)  # one file per take and folder, as export takes it
    takes = {f: [f] for f in files}  # the take's files in TAKE_ORDER: the first that can be read counts
    for f in sorted(same, key=dataset.take_rank):
        takes[same[f]].append(f)
    names = dataset.relative_folders(listed, args.inputs)

    def folder_of(f):
        rel = names[f].replace("\\", "/")
        return os.path.basename(os.path.dirname(os.path.abspath(f))) if rel == "." else rel

    rows_of, total, per_folder, per_label, failed, counted = {}, 0.0, {}, {}, 0, 0
    for take in takes.values():
        used = None  # the take's file counted
        for f in take:
            row = rows_of[f] = {"file": os.path.abspath(f), "folder": folder_of(f)}
            if used is not None:
                row["same_take"] = os.path.abspath(used)
                continue
            _log(f"reading {f}")
            try:
                if not os.path.exists(f):
                    raise FileNotFoundError("없는 파일·폴더입니다")
                human = load_skeleton(f, smpl_model_dir=_smpl()) if human_format(f) else None
                if human is not None and f.lower().endswith(".fbx") and len(human.joint_names) < 8:
                    row["not_counted"] = f"관절이 {len(human.joint_names)}개뿐인 FBX(물체 파일): 모션으로 세지 않음"
                    continue
                fps, dur = (human.fps, human.duration) if human else (lambda m: (m.fps, m.duration))(load_motion(f))
                lab = al.label_motion(human, rules, dur) if rules and human else motion_labels.load_for(f, fps, dur)
                if lab is not None and lab.error:
                    row["labels_error"] = lab.error
                    lab = None
            except Exception as e:  # the take's next file is tried
                failed += 1
                row["error"] = _err(e)
                continue
            used = f
            secs = {}
            for s in lab.segments if lab is not None else []:
                key = f"{s.track}: {s.label}" if s.track else s.label
                secs[key] = secs.get(key, 0.0) + max(0.0, min(s.end, dur) - max(s.start, 0.0))
            objs = list(human.objects) if human else []
            for o in take:  # the take's objects come with its FBX (X.bvh counted, X.fbx not)
                if o != f and o.lower().endswith(".fbx") and not rows_of.get(o, {}).get("error"):
                    _log(f"reading {o} (objects of the same take)")
                    try:
                        extra = load_skeleton(o, smpl_model_dir=_smpl()).objects
                    except Exception as e:
                        row["same_take_error"] = f"{os.path.basename(o)}: {_err(e)}"
                        continue
                    objs += [ob for ob in extra if ob.name not in {x.name for x in objs}]
            row.update({"duration_s": round(dur, 3),
                        "labels": ("auto" if lab.auto else "file") if lab is not None else None,
                        "label_seconds": {k: round(v, 3) for k, v in secs.items()},
                        "objects": [o.name for o in objs], "moving_objects": sum(o.moves for o in objs),
                        "warnings": (list(human.meta.get("warnings") or []) or None) if human else None})
            counted += 1
            total += dur
            fo = per_folder.setdefault(row["folder"], {"motions": 0, "seconds": 0.0, "labelled": 0, "with_objects": 0})
            fo["motions"] += 1
            fo["seconds"] += dur
            fo["labelled"] += lab is not None
            fo["with_objects"] += bool(objs)
            for k, v in secs.items():
                pl = per_label.setdefault(k, {"seconds": 0.0, "segments": 0})
                pl["seconds"] += v
                pl["segments"] += sum(1 for s in lab.segments if (f"{s.track}: {s.label}" if s.track else s.label) == k)
    rows = [rows_of[f] for f in listed]  # in the order found
    out = {"motions": counted, "failed": failed, "total_s": round(total, 2), "total_h": round(total / 3600, 3),
           "rules": rules or None,
           "per_folder": {k: {**v, "seconds": round(v["seconds"], 2)} for k, v in sorted(per_folder.items())},
           "per_label": {k: {**v, "seconds": round(v["seconds"], 2),
                             "share_pct": round(100 * v["seconds"] / total, 1) if total else 0.0}
                         for k, v in sorted(per_label.items(), key=lambda kv: -kv[1]["seconds"])},
           "files": rows}
    if args.csv:
        labels = list(out["per_label"])
        os.makedirs(os.path.dirname(os.path.abspath(args.csv)) or ".", exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel reads the Korean labels
            w = csv.writer(fh)
            w.writerow(["file", "folder", "duration_s", "labels", "objects", "moving_objects", "error", "warnings",
                        *labels])
            for r in rows:
                if r.get("same_take") or r.get("not_counted"):  # not motions of their own (in the JSON's files)
                    continue
                w.writerow([r["file"], r["folder"], r.get("duration_s", ""), r.get("labels") or "",
                            ";".join(r.get("objects", [])), r.get("moving_objects", ""), r.get("error", ""),
                            "; ".join(r.get("warnings") or []), *[r.get("label_seconds", {}).get(k, 0.0) for k in labels]])
        out["csv"] = os.path.abspath(args.csv)
    if not out["motions"] and failed:
        out = _Exit(out, 1)
    elif failed:
        out = _Exit(out, 2)
    return out


def autolabel(args) -> dict:
    """자동 라벨 of human motions by a rule file, from their skeletons alone (no retargeting); with --out
    each motion's segments also go to <out>/.../<stem>.labels.csv (put one next to its motion and RetLens
    shows it). A motion labelled with no segments gets a CSV of the header only; one that could not be
    labelled gets none, and a CSV of an earlier run at its place is removed (csv_removed), so <out> holds
    only this run's labels. Exit code 1 when no motion could be labelled, 2 when some could not."""
    from retlens import autolabel as al
    from retlens import motion_labels
    from retlens.compare import find_take, load_skeleton

    rules = args.rules or al.rules_file()
    if not rules:
        raise ValueError(f"no rule file: pass --rules, set 자동 라벨 규칙 in RetLens or ${al.ENV} "
                         f"(an example: {al.EXAMPLE})")
    checked = al.check_rules(rules)  # a broken rule file stops here, not once per motion
    csv_for = _label_csv_names(args.files, args.out) if args.out else {}
    out = []
    for f in args.files:
        _log(f"labelling {f}")
        row = {"file": os.path.abspath(f)}
        try:
            src = f
            if f.lower().endswith(".c3d"):
                src = find_take(f)
                if src is None:
                    raise ValueError("C3D에는 마커만 있습니다. 같은 촬영의 BVH·FBX·AMASS가 같은 폴더에 있어야 합니다")
                row["solved_motion"] = src
            lab = al.label_motion(load_skeleton(src, smpl_model_dir=_smpl(), props=False), rules)
        except Exception as e:
            lab = motion_labels.MotionLabels(path=rules, error=_err(e),
                                             auto=checked["name"] or os.path.splitext(os.path.basename(rules))[0])
        row["labels"] = lab.summary(segments=not args.summary)
        if args.out:
            path = csv_for[f]
            if not lab.error:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                row["csv"] = motion_labels.save_csv(lab, path)
            elif os.path.isfile(path):  # an earlier run's labels would pass for this run's
                os.remove(path)
                row["csv_removed"] = path
        out.append(row)
    failed = sum(bool(r["labels"]["error"]) for r in out)
    return _Exit({"rules": os.path.abspath(rules), "motions": out},
                 1 if out and failed == len(out) else 2 if failed else 0)


class _Exit(dict):
    """A command's JSON with its own exit code (autolabel: some or all motions failed)."""

    def __init__(self, out: dict, code: int):
        super().__init__(out)
        self.code = code


def _label_csv_names(files: list[str], out: str) -> dict[str, str]:
    """<out>/<stem>.labels.csv per motion, always named so RetLens finds it next to its motion. Motions
    of the same name (AMASS: 0000_treadmill_norm_stageii in every subject's folder) keep their folders
    below <out>, from where their paths part (on other drives or shares: from the drive); the same name in
    the same folder (X.c3d and X.bvh) goes one folder further down, by extension (<out>/c3d/X.labels.csv).
    Every path is inside <out>, and none is a label file of a motion: raises when <out> is a motion's folder
    (its hand-made <stem>.labels.csv) or holds another motion of that name, before anything is written."""
    from retlens import motion_labels
    from retlens.compare import is_motion_file
    from retlens.dataset import _folder_below, path_key

    root = os.path.abspath(out)
    real: dict = {}  # each folder resolved once: a label file however its path is spelled
    theirs = {path_key(p, real) for f in files for p in motion_labels.candidates(f)}
    listed: dict[str, dict[str, list[str]]] = {}  # {folder: {lower-case stem: its files}}
    by: dict[str, list[str]] = {}
    for f in dict.fromkeys(files):
        by.setdefault(os.path.splitext(os.path.basename(f))[0].lower(), []).append(f)
    names = {}
    for group in by.values():
        dirs = [os.path.dirname(os.path.abspath(f)) for f in group]
        try:
            base = os.path.commonpath(dirs) if len(group) > 1 else ""
        except ValueError:  # on different drives or shares: C:\..., \\nas\share\...
            base = None
        for f, d in zip(group, dirs):
            stem, ext = os.path.splitext(os.path.basename(f))
            sub = _folder_below(d) if base is None else os.path.relpath(d, base) if base else "."
            if sum(os.path.normcase(x) == os.path.normcase(d) for x in dirs) > 1:
                sub = os.path.join(sub, ext.lstrip(".").lower() or "_")
            path = os.path.abspath(os.path.join(root, sub, f"{stem}.labels.csv"))
            if os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) != os.path.normcase(root):
                raise ValueError(f"--out 밖에 쓰게 됩니다: {path}")  # a guard: label files next to motions are the user's
            folder = os.path.dirname(path)
            if folder not in listed:  # each folder listed once, by stem (a few thousand motions into one <out>)
                listed[folder] = {}
                for n in os.listdir(folder) if os.path.isdir(folder) else []:
                    listed[folder].setdefault(os.path.splitext(n)[0].lower(), []).append(n)
            beside = [n for n in listed[folder].get(stem.lower(), ()) if is_motion_file(os.path.join(folder, n))]
            if path_key(path, real) in theirs or beside:
                raise ValueError(f"--out이 모션 폴더라 모션의 라벨 파일을 덮어쓰게 됩니다: {path} (모션이 없는 폴더를 고르세요)")
            names[f] = path
    return names


def _smooth_hz(text: str) -> float:
    """--smooth: 0 (off) or a cutoff below 15 Hz (half the 30 fps of the retargeted motion)."""
    try:
        hz = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text}") from None
    if not (hz == 0.0 or 0.0 < hz < 15.0):
        raise argparse.ArgumentTypeError(f"{text}: must be 0 (off) or above 0 and below 15 Hz (half of 30 fps)")
    return hz


def _retarget_options(p) -> None:
    """How human motions are retargeted (as RetLens's 리타게팅 menu; robot motions load as they are)."""
    p.add_argument("--robot", default=None, metavar="MODEL",
                   help="the robot: unitree_g1 or any humanoid's MJCF / URDF path (default: 환경 설정 > 로봇 모델, "
                        "else unitree_g1)")
    p.add_argument("--smooth", type=_smooth_hz, default=6.0, metavar="HZ",
                   help="smoothing cutoff below 15 Hz (0 = off; default 6)")
    p.add_argument("--foot-flat", action="store_true",
                   help="디딤발 평평 보정: feet standing still flat on the floor, through legs and pelvis height "
                        "(heel-standing retargets)")
    p.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                   help="스윙 발 보정: swing feet at least CM off the floor (0 = off; 2 recommended)")
    p.add_argument("--self-collision", action="store_true",
                   help="자기 관통 보정: robot parts that go through each other pushed apart (hands into hips)")


def dataset_cut_kinds() -> tuple[str, ...]:
    from retlens.dataset import CUT_KINDS

    return CUT_KINDS


class _Usage(Exception):
    """A mistyped command line (argparse's error): printed as {"error": ...} with exit code 1."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit 2 with no JSON, the code batch / export use for "some failed"
        self.print_usage(sys.stderr)
        raise _Usage(f"{self.prog}: {message}")


def parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="retlens-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pretty", action="store_true", help="indented JSON (before or after the command)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="version, file locations, environment check")
    sub.add_parser("version", help="the version only (fast)")
    sub.add_parser("update", help="업데이트 확인: is there a newer release on GitHub (check only, installs nothing)")
    p = sub.add_parser("robot", help="the robot's parts as retargeting finds them (legs, arms, joint roles, size)")
    p.add_argument("model", nargs="?", default=None,
                   help="unitree_g1 or an MJCF / URDF path (default: 환경 설정 > 로봇 모델, else unitree_g1)")
    p = sub.add_parser("library", help="motion files in the motion folders")
    p.add_argument("--query", default=None)
    p.add_argument("--limit", type=int, default=200)
    p = sub.add_parser("inspect", help="load motions: QC, metrics, C3D QC")
    p.add_argument("files", nargs="+")
    _retarget_options(p)
    p = sub.add_parser("metrics", help="the analysis table")
    p.add_argument("files", nargs="+")
    p.add_argument("--ref", default=None, help="reference motion (index or label; default the first)")
    _retarget_options(p)
    p = sub.add_parser("compare", help="overlay comparison of B on A's pelvis")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--tol", type=float, default=3.0, help="tolerance (cm)")
    p.add_argument("--no-heading", action="store_true", help="match the pelvis position only, not its heading")
    p.add_argument("--align", action="store_true", help="time-align B to A first")
    _retarget_options(p)
    p = sub.add_parser("align", help="time offsets that match every motion to REF")
    p.add_argument("ref")
    p.add_argument("files", nargs="+")
    _retarget_options(p)
    p = sub.add_parser("retarget", help="retarget one human motion and save the robot motion")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    _retarget_options(p)
    p = sub.add_parser("autolabel", help="자동 라벨: label human motions by a rule file (no retargeting)")
    p.add_argument("files", nargs="+")
    p.add_argument("--rules", default=None, help="rule file (default: the 자동 라벨 규칙 setting / $RETLENS_LABEL_RULES)")
    p.add_argument("--out", default=None,
                   help="folder for <stem>.labels.csv of each motion (same names: their folders below it; "
                        "a motion that fails: an earlier run's CSV there is removed)")
    p.add_argument("--summary", action="store_true", help="counts and tracks only, not every segment")
    p = sub.add_parser("batch", help="데이터셋 일괄 처리: retarget and measure every motion of folders, a row each (cached)")
    p.add_argument("inputs", nargs="+", help="motion files or folders (searched below)")
    _retarget_options(p)
    p.add_argument("--physics", action="store_true", help="also the MuJoCo harness check of each (1-3 s per clip)")
    p.add_argument("--rules", default=None, help="자동 라벨 by this rule file for motions without a label file")
    p.add_argument("--csv", default=None, help="also write the table here")
    p = sub.add_parser("export", help="데이터셋 내보내기: the motions that pass into one folder (+ pieces, labels, manifest)")
    p.add_argument("inputs", nargs="+", help="motion files or folders (searched below)")
    p.add_argument("--out", required=True, help="the dataset folder (an earlier export there is replaced)")
    _retarget_options(p)
    p.add_argument("--physics", action="store_true", help="also the MuJoCo harness check: motions that fall are left "
                   "out (or, with --cut, the time around each fall is cut out)")
    p.add_argument("--rules", default=None, help="자동 라벨 by this rule file for motions without a label file")
    p.add_argument("--qc", choices=("PASS", "WARN", "FAIL"), default="WARN",
                   help="the worst QC let in (with --cut / --range: of each piece): PASS, WARN (default) or FAIL (all)")
    p.add_argument("--min-score", type=float, default=None, help="리타게팅 점수 at least this")
    p.add_argument("--allow-falls", action="store_true", help="keep motions that fell in the physics check")
    p.add_argument("--cut", action="store_true", help="문제 구간 잘라 내기: cut problems out, keep the pieces")
    p.add_argument("--cut-kinds", default=",".join(dataset_cut_kinds()), metavar="K,K",
                   help="problem kinds --cut takes out (default %(default)s; also slip, swing_low, self_collision, "
                        "joint_limit; '' for none)")
    p.add_argument("--no-cut-qc", action="store_true", help="--cut leaves the frames QC cannot use")
    p.add_argument("--no-cut-falls", action="store_true", help="--cut leaves the falls")
    p.add_argument("--pad", type=float, default=0.1, metavar="S", help="--cut widens every span by S (default 0.1)")
    p.add_argument("--min-piece", type=float, default=1.0, metavar="S", help="--cut drops pieces shorter (default 1)")
    p.add_argument("--range", nargs=2, type=float, default=None, metavar=("START", "END"),
                   help="one motion: export only this time range (seconds)")
    p.add_argument("--formats", default="npz", help="npz (default), csv (x y z qx qy qz qw + joints), pkl (GMR); comma")
    p.add_argument("--no-labels", action="store_true", help="without the motions' labels")
    p = sub.add_parser("summary", help="데이터셋 요약: length, label time and objects of motions (no retargeting)")
    p.add_argument("inputs", nargs="+", help="motion files or folders (searched below)")
    p.add_argument("--rules", default=None, help="자동 라벨 by this rule file instead of the label files next to the motions")
    p.add_argument("--csv", default=None, help="also write one row per motion here")
    p = sub.add_parser("c3d-qc", help="raw marker QC of C3D files")
    p.add_argument("files", nargs="+")
    for name in ("physics", "video"):
        p = sub.add_parser(name, help="physics check (MuJoCo, or Isaac PhysX)" if name == "physics"
                           else "Isaac Sim recording")
        p.add_argument("file")
        _retarget_options(p)
        p.add_argument("--timeout", type=float, default=1200.0)
        p.add_argument("--isaac-accept-eula", action="store_true",
                       help="only when the user accepted the NVIDIA Omniverse EULA (never on their behalf)")
        p.add_argument("--balance", choices=("harness", "pd", "gmt", "isaac"), default="harness",  # scene.BALANCE
                       help="balance control: harness = MuJoCo with the pelvis harness (default), pd = MuJoCo with no "
                            "controller, gmt = MuJoCo with GMT's policy, isaac = Isaac PhysX with the harness"
                            + ("" if name == "physics" else " (with --physics)"))
        if name == "physics":
            p.add_argument("--assist", type=float, default=1.0, help="isaac: pelvis harness scale (0 = none)")
        else:
            p.add_argument("--out", default=None, help="the .mp4 to write (default: the video folder)")
            p.add_argument("--physics", action="store_true", help="record the simulated motion")
    p = sub.add_parser("setup", help="setup assistant: optional programs here / missing / installable (JSON)")
    p.add_argument("--offline", action="store_true", help="skip the publishers' reachability check")
    p.add_argument("--install", choices=("blender", "gmt", "isaac", "smpl"), default=None,
                   help="install it, only when it is missing and this PC can take it")
    p.add_argument("--accept-license", action="store_true",
                   help="the user agreed to its licence (GMT research-only, NVIDIA EULA) - never on their behalf")
    p.add_argument("--source", default=None, help="SMPL-X: the zip from smpl-x.is.tue.mpg.de (or its folder)")
    sub.add_parser("api", help="url and token of the running RetLens window's HTTP API")
    p = sub.add_parser("install-skill", help="copy the AI guide (SKILL.md) to Claude Code's skills folder")
    p.add_argument("--project", default=None, help="a project folder (default: your user folder, ~/.claude/skills)")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pretty = "--pretty" in argv  # before or after the command
    argv = [a for a in argv if a != "--pretty"]
    if argv == ["version"]:  # nothing heavy
        from retlens import __version__

        text = json.dumps({"app": "RetLens", "version": __version__}, indent=1 if pretty else None)
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
        sys.stdout.flush()
        return 0
    try:
        args = parser().parse_args(argv)
    except _Usage as e:
        sys.stdout.buffer.write((json.dumps({"error": str(e)}, ensure_ascii=False, indent=1 if pretty else None)
                                 + "\n").encode("utf-8"))
        sys.stdout.flush()
        return 1
    pretty = pretty or args.pretty
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # stdout carries the JSON only: banners and prints (viser, GMR) go to stderr
    try:
        out = run(args)
        code = getattr(out, "code", 0)
    except Exception as e:
        out, code = {"error": _err(e)}, 1
    finally:
        sys.stdout = real_stdout
    from retlens.app.api_core import jsonable

    text = json.dumps(jsonable(out), ensure_ascii=False, indent=1 if pretty else None)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
