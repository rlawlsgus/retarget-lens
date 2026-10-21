"""What RetLens tells an AI (or any script): the motion scene as plain JSON-ready dicts.

Shared by the command line (tools/retlens_cli.py, retlens-cli.exe) and the local HTTP API of
a running RetLens (khumanoid/app/api_server.py). Both work on a MotionScene, the same object
the window draws, so every number matches what the window shows. The guide for AI agents is
.claude/skills/retlens/SKILL.md.

Motions are named by their label ("cmu_bvh/02_01": folder/file name, unique in a scene); an
index (0, 1, ...) or a file name also works (find_item).
"""

from __future__ import annotations

import math
import os
import time

import numpy as np

from .. import cmu_labels, paths, settings
from ..compare import Item, library_files
from .scene import METRIC_DESC, METRIC_ROWS, MotionScene, SceneOptions, load_robot_urdf

API_VERSION = 1
APP = "RetLens"  # QSettings organisation / application (the editor's settings, Isaac EULA consent)
# metric keys (Item.metrics) -> the table label (METRIC_ROWS) and what it measures (METRIC_HELP)
METRIC_INFO = {key: {"label": label, "description": METRIC_DESC.get(label, "")} for label, key, _ in METRIC_ROWS}


def jsonable(v):
    """numpy / nan / tuples -> JSON values (nan and inf -> None)."""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, np.ndarray):
        return jsonable(v.tolist())
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def headless_scene(log=None, mesh_cell: float = 0.004, **opts) -> MotionScene:
    """A MotionScene without a window (the command line): its viser server only listens on
    127.0.0.1 and nothing connects; motions, metrics, comparisons and Isaac jobs work as in
    the window. Paths and tools come from 환경 설정; opts are more SceneOptions (smooth,
    foot_flat, swing_clearance_cm)."""
    import socket

    import viser

    log = log or (lambda *_: None)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = viser.ViserServer(host="127.0.0.1", port=port, verbose=False)
    s = settings.load()
    opts = SceneOptions(smpl_model_dir=settings.find_smpl(s).path or paths.smpl_model_dir(), video_dir=settings.video_dir(s),
                        **opts)
    return MotionScene(server, load_robot_urdf(paths.robot_urdf(), mesh_cell, log=log), opts, log=log)


def find_item(scene: MotionScene, key) -> Item:
    """A motion by label ("cmu_bvh/02_01"), index (0 / "0") or file name ("02_01.bvh")."""
    items = list(scene.items)
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        i = int(key)
        if 0 <= i < len(items):
            return items[i]
    for it in items:
        if key in (it.label, os.path.basename(it.source), os.path.abspath(str(key)) if isinstance(key, str) else None,
                   it.source):
            return it
    raise KeyError(f"no motion {key!r}; open ones: {[it.label for it in items]}")


def item_info(scene: MotionScene, item: Item, metrics: bool = True) -> dict:
    """One motion: what it is, its timing, QC, and (metrics=True) every measured value."""
    r, m = item.robot, item.metrics
    out = {
        "id": item.label, "index": scene.items.index(item) if item in scene.items else None, "kind": item.kind,
        "source": item.source, "cmu_description": cmu_labels.label_for(item.source) or None,
        "frames": r.num_frames, "fps": r.fps, "duration_s": r.duration, "offset_s": item.offset,
        "visible": item.visible, "color": list(item.color), "qc": m.get("qc"), "qc_notes": m.get("qc_notes") or "",
        "ik_position_residual": item.info.get("ik_position_residual"),
        "retarget": item.retarget or None,  # human inputs: smooth_hz, foot_flat, swing_clearance_cm
    }
    if item.info.get("foot_flat"):
        ff = item.info["foot_flat"]
        out["foot_flat"] = {k: ff.get(k) for k in ("frames_changed", "stance_pitch_deg", "sole_lift_cm",
                                                   "ankle_change_deg")}
    if item.info.get("c3d"):
        out["c3d"] = item.info["c3d"]
        out["solved_motion"] = item.info.get("solved_motion")
    if metrics:
        out["metrics"] = {k: v for k, v in m.items() if not k.startswith("_") and k not in ("qc", "qc_notes")}
    if scene.physics_on or item.handles.get("phys"):
        shown = scene.shown(item)
        out["physics"] = {"state": scene.job_text(item), "balance": scene.balance, "mode": scene.mode_label(),
                          "assist": scene.assist,
                          "result_ready": shown is not item,
                          "falls": [{"time_s": t, "cause": c} for t, c in scene.falls(item)]}
        if shown is not item:
            out["physics"]["metrics"] = {k: v for k, v in shown.metrics.items() if k.startswith("phys_")}
    return jsonable(out)


def status(scene: MotionScene) -> dict:
    """The scene at a glance."""
    lo, hi = scene.time_range()
    c = scene.compare
    pair = scene.compare_pair()
    return jsonable({
        "app": "RetLens", "api_version": API_VERSION, "layout": paths.LAYOUT,
        "time_s": scene.t, "playing": scene.playing, "speed": scene.view.speed, "time_range_s": [lo, hi],
        "physics": {"on": scene.physics_on, "balance": scene.balance, "mode": scene.mode_label(),
                    "assist": scene.assist, "jobs": scene.jobs_summary() or None, "error": scene.phys_error or None},
        "compare": {"on": pair is not None, "a": c.ref.label if pair else None, "b": c.item.label if pair else None,
                    "heading": c.heading, "tol_cm": c.tol_cm},
        "retarget": scene.retarget_settings(),  # for the human motions opened next
        "motions": [item_info(scene, it, metrics=False) for it in list(scene.items)],
    })


def metrics_table(scene: MotionScene, ref: Item | None = None) -> dict:
    """The analysis table: per motion, every row of the window's 분석 table (RMSE against
    `ref`), plus what each row measures."""
    names, cols = scene.metric_table(ref)
    return jsonable({
        "reference": ref.label if ref else None, "rows": names,
        "motions": [{"id": it.label, "values": dict(zip(names, vals))} for it, vals in cols],
        "row_help": {n: METRIC_DESC.get(n, "") for n in names},
    })


def compare(scene: MotionScene, a: Item, b: Item, heading: bool = True, tol_cm: float = 3.0, worst: int = 5) -> dict:
    """겹쳐 비교 of B on A's pelvis (turns it on in the scene): per body region the mean / max
    deviation (cm), when the max happens and how much of the time it is beyond tol_cm, plus
    the moments where the whole body differs most."""
    scene.set_compare(on=True, ref=a, item=b, heading=heading, tol_cm=tol_cm)
    s = scene.compare_series()
    out = {"a": a.label, "b": b.label, "heading": heading, "tol_cm": tol_cm, "frames": 0, "regions": [],
           "worst_moments": []}
    if s is None or not len(s["t"]):
        out["note"] = "the two motions never play at the same time (check their time offsets)"
        return jsonable(out)
    out["frames"] = len(s["t"])
    out["shared_time_s"] = [float(s["t"][0]), float(s["t"][-1])]
    out["regions"] = [{"region": r, "mean_cm": float(mean), "max_cm": float(mx), "max_at_s": float(at),
                       "beyond_tol_pct": float(pct)}
                      for r, mean, mx, at, pct in scene.compare_table()]
    order = np.argsort(-s["mean"])
    picked = []
    for k in order:  # the largest, at least 0.5 s apart
        if all(abs(s["t"][k] - s["t"][j]) >= 0.5 for j in picked):
            picked.append(int(k))
        if len(picked) >= worst:
            break
    out["worst_moments"] = [{"time_s": float(s["t"][k]), "mean_cm": float(s["mean"][k]),
                             "by_region_cm": {r: float(v[k]) for r, v in s["regions"].items()}} for k in picked]
    return jsonable(out)


def align(scene: MotionScene, ref: Item) -> dict:
    """기준에 시간 자동 정렬: every other motion's offset that best matches its legs to ref's."""
    notes = scene.auto_align(ref)
    return jsonable({"reference": ref.label, "notes": notes,
                     "offsets_s": {it.label: it.offset for it in list(scene.items)}})


def library(query: str | None = None, limit: int = 200) -> dict:
    """Motion files in the motion folders (환경 설정), with CMU descriptions; `query` matches
    file names and descriptions (e.g. "143_11", "walk")."""
    q = (query or "").strip().lower()
    files = []
    for folder, ps in library_files(settings.library_dirs()).items():
        for p in ps:
            label = cmu_labels.label_for(p)
            if q and q not in os.path.basename(p).lower() and q not in label.lower():
                continue
            files.append({"path": p, "folder": folder, "name": os.path.basename(p), "cmu_description": label or None})
    return {"query": query, "count": len(files), "files": files[:limit], "truncated": len(files) > limit}


def checks() -> dict:
    """환경 점검: what each feature needs and whether it is there."""
    from dataclasses import asdict

    return {"checks": [asdict(c) for c in settings.check_all()]}


def eula_accepted() -> bool:
    """Whether the user accepted NVIDIA's Isaac Sim licence in RetLens (needed for physics and
    videos). Only the user can accept it; tools never do it for them."""
    try:
        from PySide6.QtCore import QSettings

        return QSettings(APP, APP).value("isaac/eula_accepted", False, type=bool)
    except Exception:
        return False


def wait_jobs(scene: MotionScene, timeout_s: float = 900.0, poll_s: float = 1.0) -> bool:
    """Block until the Isaac and MuJoCo jobs are done (True) or the timeout passes (False)."""
    end = time.time() + timeout_s
    time.sleep(0.2)
    while time.time() < end:
        if not scene.jobs_busy():
            return True
        time.sleep(poll_s)
    return False
