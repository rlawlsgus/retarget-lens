"""retlens-cli: RetLens without a window, for scripts and AI agents. Every command prints one
JSON object on stdout (progress goes to stderr); exit code 0 = ok, 1 = error ({"error": ...}).

    retlens-cli info                        # version, file locations, 환경 점검
    retlens-cli library --query walk        # motion files (with CMU descriptions)
    retlens-cli inspect FILE [FILE ...]     # load (retarget if needed): QC, metrics, C3D QC
    retlens-cli metrics FILE [FILE ...] [--ref 0]   # the 분석 table (RMSE vs ref)
    retlens-cli compare A B [--tol 3] [--no-heading] [--align]   # 겹쳐 비교 numbers
    retlens-cli align REF FILE [FILE ...]   # 기준에 시간 자동 정렬
    retlens-cli retarget FILE --out OUT.npz # save the robot motion (+ .json)
      (commands that open motions take --smooth HZ, --foot-flat, --swing-clearance CM and --self-collision
       for human ones)
    retlens-cli c3d-qc FILE.c3d             # raw marker QC only (no retargeting)
    retlens-cli physics FILE [--assist 1]   # Isaac PhysX check (needs the EULA accepted)
    retlens-cli video FILE --out X.mp4 [--physics]
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


def _scene(args):
    from retlens.app import api_core

    if not 0.0 <= args.swing_clearance <= 10.0:
        raise ValueError("--swing-clearance must be 0 (off) to 10 cm")
    return api_core.headless_scene(log=_log, smooth=args.smooth, foot_flat=args.foot_flat,
                                   swing_clearance_cm=args.swing_clearance, self_collision=args.self_collision)


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
    if c == "c3d-qc":
        from retlens.io.c3d import load_c3d
        from retlens.markers import marker_qc

        return api_core.jsonable({os.path.basename(f): marker_qc(load_c3d(f)) for f in args.files})
    if c == "retarget":
        from retlens.compare import load_item

        item = load_item(args.file, smooth=args.smooth, swing_clearance=args.swing_clearance / 100.0,
                         foot_flat=args.foot_flat, self_collision=args.self_collision, smpl_model_dir=_smpl(), log=_log)
        item.robot.save_npz(args.out)
        with open(os.path.splitext(args.out)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(api_core.jsonable(item.info), f, ensure_ascii=False, indent=1)
        return {"out": os.path.abspath(args.out), "frames": item.robot.num_frames, "fps": item.robot.fps,
                "kind": item.kind}

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
            if args.align:
                scene.auto_align(a)
            return api_core.compare(scene, a, b, heading=not args.no_heading, tol_cm=args.tol)
        if c in ("physics", "video"):
            if not (api_core.eula_accepted() or args.isaac_accept_eula):
                raise PermissionError("Isaac Sim needs the NVIDIA Omniverse EULA accepted by the user: open RetLens and "
                                      "turn physics mode on once (or the user passes --isaac-accept-eula themselves)")
            scene.runner.accept_eula = True
            (item,) = _open(scene, [args.file])
            if c == "physics":
                scene.set_assist(args.assist)
                scene.set_physics(True, "cli")
                _log("waiting for Isaac (about a minute for a short clip)")
                done = api_core.wait_jobs(scene, args.timeout)
                return {"finished": done, **api_core.item_info(scene, item)}
            scene.set_physics(bool(args.physics), "cli")
            if args.physics:
                api_core.wait_jobs(scene, args.timeout)
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


def _smpl():
    from retlens import paths, settings

    return settings.find_smpl().path or paths.smpl_model_dir()


def _retarget_options(p) -> None:
    """How human motions are retargeted (as RetLens's 리타게팅 menu; robot motions load as they are)."""
    p.add_argument("--smooth", type=float, default=6.0, metavar="HZ", help="smoothing (0 = off; default 6)")
    p.add_argument("--foot-flat", action="store_true",
                   help="디딤발 평평 보정: feet standing still flat on the floor, through legs and pelvis height "
                        "(heel-standing retargets)")
    p.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                   help="스윙 발 보정: swing feet at least CM off the floor (0 = off; 2 recommended)")
    p.add_argument("--self-collision", action="store_true",
                   help="자기 관통 보정: robot parts that go through each other pushed apart (hands into hips)")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="retlens-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pretty", action="store_true", help="indented JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="version, file locations, environment check")
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
    p = sub.add_parser("c3d-qc", help="raw marker QC of C3D files")
    p.add_argument("files", nargs="+")
    for name in ("physics", "video"):
        p = sub.add_parser(name, help="Isaac Sim " + ("physics check" if name == "physics" else "recording"))
        p.add_argument("file")
        _retarget_options(p)
        p.add_argument("--timeout", type=float, default=1200.0)
        p.add_argument("--isaac-accept-eula", action="store_true",
                       help="only when the user accepted the NVIDIA Omniverse EULA (never on their behalf)")
        if name == "physics":
            p.add_argument("--assist", type=float, default=1.0, help="pelvis harness scale (0 = none)")
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
    args = parser().parse_args(argv)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # stdout carries the JSON only: banners and prints (viser, GMR) go to stderr
    try:
        out, code = run(args), 0
    except Exception as e:
        out, code = {"error": f"{type(e).__name__}: {e}"}, 1
    finally:
        sys.stdout = real_stdout
    from retlens.app.api_core import jsonable

    text = json.dumps(jsonable(out), ensure_ascii=False, indent=1 if args.pretty else None)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
