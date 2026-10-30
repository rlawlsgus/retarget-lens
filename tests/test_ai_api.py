"""The AI interfaces: retlens-cli (tools/retlens_cli.py) and the window's local HTTP API
(retlens/app/api_server.py), plus the guide (SKILL.md) staying in step with the metrics."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens.app.scene import DEFAULT_URDF, METRIC_ROWS  # noqa: E402

SAMPLE = os.path.join(ROOT, "data", "samples", "synthetic_g1_walk.npz")
SKILL = os.path.join(ROOT, ".claude", "skills", "retlens", "SKILL.md")
needs_sample = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                  reason="needs the G1 assets and data/samples (tools/make_samples.py)")


def _cli(*args, tmp_path):
    env = dict(os.environ, RETLENS_USER_DIR=str(tmp_path / "user"))
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "retlens_cli.py"), *args], env=env,
                         capture_output=True, timeout=300, cwd=ROOT)
    text = out.stdout.decode("utf-8").strip().splitlines()
    assert len(text) <= 1, text[:3]  # stdout is the JSON and nothing else
    return out.returncode, json.loads(text[-1]) if text else None


def test_cli_info_and_errors(tmp_path):
    code, out = _cli("info", tmp_path=tmp_path)
    assert code == 0 and out["app"] == "RetLens" and {c["key"] for c in out["checks"]} >= {"robot", "isaac", "blender"}
    code, out = _cli("inspect", str(tmp_path / "missing.bvh"), tmp_path=tmp_path)
    assert code == 1 and "error" in out  # JSON even when it fails
    code, out = _cli("api", tmp_path=tmp_path)
    assert code == 1 and "not running" in out["error"]
    code, out = _cli("setup", "--offline", tmp_path=tmp_path)  # 설치 도우미's check: one status per component
    assert code == 0 and [c["key"] for c in out["components"]] == ["blender", "gmt", "isaac", "smpl"]
    assert all(c["action"] in ("none", "configure", "install", "manual", "blocked") for c in out["components"])


def test_cli_autolabel_out_and_exit_codes(tmp_path):
    """autolabel --out: every CSV inside --out, named as RetLens looks for it; a motion labelled with
    nothing gets a header-only CSV, one that fails removes an earlier run's; the exit code says failures."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import retlens_cli
    from retlens.synthetic import walking_bvh_text

    names = retlens_cli._label_csv_names
    out = str(tmp_path / "out")
    share = [r"\\nas\mocap\s01\take.bvh", r"\\nas\archive\s01\take.bvh"]  # other shares: no common folder
    got = names(share, out)
    assert all(os.path.commonpath([p, out]) == out and p.endswith("take.labels.csv") for p in got.values())
    assert len(set(got.values())) == 2
    same = [str(tmp_path / "t" / "X.c3d"), str(tmp_path / "t" / "X.bvh")]  # same name, same folder
    got = names(same, out)
    assert {os.path.relpath(p, out) for p in got.values()} == {os.path.join("c3d", "X.labels.csv"),
                                                              os.path.join("bvh", "X.labels.csv")}

    bvh = tmp_path / "walk.bvh"
    bvh.write_text(walking_bvh_text(seconds=2.0))
    rules = tmp_path / "r.yaml"
    rules.write_text("rules:\n  - {label: 물구나무, when: {자세: 거꾸로}}\n", encoding="utf-8")  # nobody is upside down
    code, res = _cli("autolabel", str(bvh), "--rules", str(rules), "--out", out, tmp_path=tmp_path)
    csv_path = res["motions"][0]["csv"]
    assert code == 0 and res["motions"][0]["labels"]["count"] == 0
    with open(csv_path, encoding="utf-8-sig") as f:
        assert f.read().strip() == "track,label,name,start_s,end_s,note,color"  # this run's answer: nothing
    missing = str(tmp_path / "walk2.bvh")
    os.makedirs(os.path.join(out), exist_ok=True)
    stale = os.path.join(out, "walk2.labels.csv")
    with open(stale, "w", encoding="utf-8") as f:
        f.write("label,start_s,end_s\nold,0,1\n")
    code, res = _cli("autolabel", str(bvh), missing, "--rules", str(rules), "--out", out, tmp_path=tmp_path)
    assert code == 2 and res["motions"][1]["labels"]["error"] and res["motions"][1]["csv_removed"] == stale
    assert not os.path.exists(stale)
    code, res = _cli("autolabel", missing, "--rules", str(rules), tmp_path=tmp_path)
    assert code == 1 and res["motions"][0]["labels"]["error"]


@needs_sample
def test_cli_inspect_metrics_compare(tmp_path):
    code, out = _cli("inspect", SAMPLE, "--foot-flat", tmp_path=tmp_path)  # robot motions ignore 리타게팅 보정
    m = out["motions"][0]
    assert code == 0 and m["qc"] in ("PASS", "WARN", "FAIL") and m["frames"] > 0 and "acc_mean" in m["metrics"]
    assert m["retarget"] is None
    code, out = _cli("compare", SAMPLE, SAMPLE, "--tol", "2", tmp_path=tmp_path)
    assert code == 0 and out["frames"] > 0 and out["tol_cm"] == 2.0
    assert out["regions"][0]["region"].startswith("전체") and all(r["max_cm"] < 1e-6 for r in out["regions"])
    code, out = _cli("metrics", SAMPLE, SAMPLE, tmp_path=tmp_path)
    assert code == 0 and "기준 대비 다리 RMSE (°)" in out["rows"] and len(out["motions"]) == 2


def test_cli_retarget_options():
    """Every command that opens motions takes the 리타게팅 보정 options (as the window's menu)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import retlens_cli

    for cmd in (["inspect", "a.bvh"], ["metrics", "a.bvh"], ["compare", "a.bvh", "b.bvh"], ["align", "a.bvh", "b.bvh"],
                ["retarget", "a.bvh", "--out", "a.npz"], ["physics", "a.bvh"], ["video", "a.bvh"]):
        a = retlens_cli.parser().parse_args([*cmd, "--foot-flat", "--swing-clearance", "2"])
        assert a.foot_flat is True and a.swing_clearance == 2.0 and a.smooth == 6.0, cmd
    with pytest.raises(ValueError):  # refused before any scene starts
        retlens_cli._scene(retlens_cli.parser().parse_args(["inspect", "a.bvh", "--swing-clearance", "50"]))


def _call(url, token=None, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method="POST" if body is not None else "GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@needs_sample
def test_http_api(tmp_path, monkeypatch):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    from retlens.app import api_core
    from retlens.app.api_server import ApiBackend, ApiServer

    scene = api_core.headless_scene(mesh_cell=0.02)
    srv = ApiServer(ApiBackend(scene), port=0, write_discovery=False).start()
    u, t = srv.url, srv.token
    try:
        assert _call(f"{u}/api/status")[0] == 401  # no token
        assert _call(f"{u}/api/status", "wrong")[0] == 401
        assert _call(f"{u}/api/status", t, headers={"Origin": "http://evil.example"})[0] == 403  # a web page
        code, st = _call(f"{u}/api/status", t)
        assert code == 200 and st["ok"] and st["motions"] == [] and st["retarget"]["foot_flat"] is False
        code, out = _call(f"{u}/api/retarget", t, {"foot_flat": True})  # 리타게팅 보정 for motions opened next
        assert code == 200 and out["retarget"]["foot_flat"] is True and out["retarget"]["swing_clearance_cm"] == 0.0
        assert _call(f"{u}/api/status", t)[1]["retarget"]["foot_flat"] is True
        assert _call(f"{u}/api/retarget", t, {"swing_clearance_cm": 50})[0] == 400
        assert _call(f"{u}/api/retarget", t, {"foot_flat": False})[1]["retarget"]["foot_flat"] is False
        out = _call(f"{u}/api/retarget", t, {"self_collision": True})[1]["retarget"]
        assert out["self_collision"] is True and out["foot_flat"] is False
        assert _call(f"{u}/api/retarget", t, {"self_collision": False})[1]["retarget"]["self_collision"] is False
        code, out = _call(f"{u}/api/open", t, {"paths": [SAMPLE, SAMPLE]})
        assert code == 200 and len(out["opened"]) == 2
        assert out["opened"][0]["retarget"] is None  # a robot motion: loaded as it is
        a, b = (m["id"] for m in out["opened"])
        assert a != b  # labels stay unique
        assert _call(f"{u}/api/open", t, {"paths": [str(tmp_path / "x.bvh")]})[0] == 404
        # labels: a hand-written table with more values than columns is read, not a 500
        typed = tmp_path / "typed.csv"
        typed.write_text("label,start_s,end_s,note\nidle,0,0.5,\nwalk,0.5,1,left, then right\n", encoding="utf-8")
        code, out = _call(f"{u}/api/labels", t, {"id": a, "path": str(typed)})
        assert code == 200 and [s["label"] for s in out["labels"]["segments"]] == ["idle", "walk"]
        assert out["labels"]["segments"][1]["note"] == "left, then right" and out["labels"]["notes"]
        assert _call(f"{u}/api/labels", t, {"id": a, "path": 5})[0] == 400
        assert _call(f"{u}/api/labels", t, {"id": a, "path": str(tmp_path / "none.csv")})[0] == 404
        rules = tmp_path / "rules.yaml"
        rules.write_text("rules:\n  - {label: x}\n", encoding="utf-8")
        code, out = _call(f"{u}/api/labels", t, {"id": a, "auto": True, "rules": str(rules)})
        assert code == 422 and "로봇 모션" in out["error"]  # no skeleton: said, and its labels stay
        assert [s["label"] for s in _call(f"{u}/api/motion?id={a}", t)[1]["labels"]["segments"]] == ["idle", "walk"]
        assert _call(f"{u}/api/labels", t, {"id": a, "auto": "false"})[0] == 400
        assert _call(f"{u}/api/labels", t, {"id": a, "auto": True, "path": str(typed)})[0] == 400
        assert _call(f"{u}/api/labels", t, {"id": a, "rules": str(rules)})[0] == 400
        assert _call(f"{u}/api/labels", t, {"id": a, "path": None})[1]["labels"] is None
        code, out = _call(f"{u}/api/item", t, {"id": b, "offset_s": 0.25, "visible": False})
        assert code == 200 and out["offset_s"] == 0.25 and out["visible"] is False
        code, out = _call(f"{u}/api/playback", t, {"time_s": 0.5, "play": False})
        assert code == 200 and out["time_s"] == 0.5
        code, out = _call(f"{u}/api/metrics?ref={a}", t)
        assert code == 200 and out["reference"] == a and len(out["motions"]) == 2
        code, out = _call(f"{u}/api/compare", t, {"a": a, "b": b, "tol_cm": 3})
        assert code == 200 and out["frames"] > 0 and out["regions"][0]["mean_cm"] > 0  # B is 0.25 s later
        assert _call(f"{u}/api/status", t)[1]["compare"]["on"] is True
        code, out = _call(f"{u}/api/align", t, {"ref": a})
        assert code == 200 and abs(out["offsets_s"][b]) < 0.05  # the same motion: back in step
        assert _call(f"{u}/api/motion?id=nope", t)[0] == 404
        assert _call(f"{u}/api/nothing", t)[0] == 404
        assert _call(f"{u}/api/screenshot", t, {})[0] == 409  # headless: no window
        code, out = _call(f"{u}/api/help", t)
        assert code == 200 and "POST /api/compare" in out["endpoints"]
        assert _call(f"{u}/api/remove", t, {"id": b})[1]["removed"] == b
    finally:
        srv.stop()
        scene.runner.shutdown()
        scene.server.stop()


def test_second_window_gets_its_own_port():
    """A second RetLens must not share the first one's API port (Windows SO_REUSEADDR allowed it, and
    then its requests reached the first window, which rejected its token)."""
    from retlens.app.api_server import ApiServer

    first = ApiServer(None, port=0, write_discovery=False)
    second = ApiServer(None, port=first.port, write_discovery=False)
    try:
        assert second.port != first.port
    finally:
        first.httpd.server_close()
        second.httpd.server_close()


def test_discovery_file_goes_back_to_the_other_window(tmp_path, monkeypatch):
    """The window opened last owns api.json; closing it points the file back at the earlier window
    (still running) instead of deleting it."""
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    from retlens.app.api_server import ApiServer, discovery, discovery_path

    os.makedirs(os.path.dirname(discovery_path()))
    earlier = {"url": "http://127.0.0.1:8765", "port": 8765, "token": "earlier", "pid": os.getppid()}  # a live process
    with open(discovery_path(), "w", encoding="utf-8") as f:
        json.dump(earlier, f)
    srv = ApiServer(None, port=0).start()
    assert discovery()["token"] == srv.token
    srv.stop()
    assert discovery() == earlier
    srv = ApiServer(None, port=0).start()  # alone this time (its predecessor's file is back, but say it closed)
    srv._previous = None
    srv.stop()
    assert discovery() is None and not os.path.exists(discovery_path())


def test_physics_off_always_works():
    """Turning physics off must not depend on whether the current 균형 제어 can run here."""
    from types import SimpleNamespace

    from retlens.app.api_server import ApiBackend, ApiError

    calls = []
    scene = SimpleNamespace(balance="gmt", assist=1.0, items=[], balance_problem=lambda m: "no PyTorch",
                            set_physics=lambda on, why: calls.append(on), mode_label=lambda: "추적 정책 (GMT)",
                            job_text=lambda it: "")
    api = ApiBackend.__new__(ApiBackend)
    api.scene = scene
    assert api.physics({"on": False})["physics"] is False and calls == [False]
    with pytest.raises(ApiError):
        api.physics({"on": True})


def test_skill_covers_every_metric():
    """The AI guide explains every metric the tools report (keys and table names)."""
    text = open(SKILL, encoding="utf-8").read()
    assert text.startswith("---\nname: retlens\ndescription: ")  # Claude Code skill front matter
    for label, key, _ in METRIC_ROWS:
        if key != "qc":
            assert f"`{key}`" in text, key
        assert label in text, label
    for cmd in ("info", "library", "inspect", "metrics", "compare", "align", "retarget", "c3d-qc", "physics", "video",
                "api", "install-skill"):
        assert f"`{cmd}" in text, cmd
