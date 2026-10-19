"""The AI interfaces: retlens-cli (tools/retlens_cli.py) and the window's local HTTP API
(khumanoid/app/api_server.py), plus the guide (SKILL.md) staying in step with the metrics."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from khumanoid.app.scene import DEFAULT_URDF, METRIC_ROWS  # noqa: E402

SAMPLE = os.path.join(ROOT, "data", "samples", "synthetic_g1_walk.npz")
SKILL = os.path.join(ROOT, ".claude", "skills", "retlens", "SKILL.md")
needs_sample = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                  reason="needs the G1 assets and data/samples (tools/make_samples.py)")


def _cli(*args, tmp_path):
    env = dict(os.environ, KHUMANOID_USER_DIR=str(tmp_path / "user"))
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


@needs_sample
def test_cli_inspect_metrics_compare(tmp_path):
    code, out = _cli("inspect", SAMPLE, tmp_path=tmp_path)
    m = out["motions"][0]
    assert code == 0 and m["qc"] in ("PASS", "WARN", "FAIL") and m["frames"] > 0 and "acc_mean" in m["metrics"]
    code, out = _cli("compare", SAMPLE, SAMPLE, "--tol", "2", tmp_path=tmp_path)
    assert code == 0 and out["frames"] > 0 and out["tol_cm"] == 2.0
    assert out["regions"][0]["region"].startswith("전체") and all(r["max_cm"] < 1e-6 for r in out["regions"])
    code, out = _cli("metrics", SAMPLE, SAMPLE, tmp_path=tmp_path)
    assert code == 0 and "기준 대비 다리 RMSE (°)" in out["rows"] and len(out["motions"]) == 2


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
    monkeypatch.setenv("KHUMANOID_USER_DIR", str(tmp_path / "user"))
    from khumanoid.app import api_core
    from khumanoid.app.api_server import ApiBackend, ApiServer

    scene = api_core.headless_scene(mesh_cell=0.02)
    srv = ApiServer(ApiBackend(scene), port=0, write_discovery=False).start()
    u, t = srv.url, srv.token
    try:
        assert _call(f"{u}/api/status")[0] == 401  # no token
        assert _call(f"{u}/api/status", "wrong")[0] == 401
        assert _call(f"{u}/api/status", t, headers={"Origin": "http://evil.example"})[0] == 403  # a web page
        code, st = _call(f"{u}/api/status", t)
        assert code == 200 and st["ok"] and st["motions"] == []
        code, out = _call(f"{u}/api/open", t, {"paths": [SAMPLE, SAMPLE]})
        assert code == 200 and len(out["opened"]) == 2
        a, b = (m["id"] for m in out["opened"])
        assert a != b  # labels stay unique
        assert _call(f"{u}/api/open", t, {"paths": [str(tmp_path / "x.bvh")]})[0] == 404
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
