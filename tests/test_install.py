"""Install / update / uninstall (retlens/install.py, retlens/update_helper.py): release parsing and what is trusted,
the GitHub-only redirect rule, staging a release zip and checking it against its manifest, installing a portable
copy (shortcut, carried-over user files), the helper's swap with its health check and undo, a held folder, uninstall
and recovery; all in temporary folders, without the registry, against a local test server."""

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from retlens import install  # noqa: E402
from retlens import update_helper as helper  # noqa: E402

WIN = os.name == "nt"
needs_windows = pytest.mark.skipif(not WIN, reason="Windows only")


@pytest.fixture
def places(tmp_path, monkeypatch):
    """Install folder, Start menu, desktop and user folder in tmp; no registry."""
    root = tmp_path / "Programs"
    root.mkdir()
    monkeypatch.setenv("RETLENS_INSTALL_DIR", str(root / "RetLens"))
    monkeypatch.setenv("RETLENS_START_MENU_DIR", str(tmp_path / "StartMenu"))
    monkeypatch.setenv("RETLENS_DESKTOP_DIR", str(tmp_path / "Desktop"))
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setenv("RETLENS_NO_REGISTRY", "1")
    monkeypatch.setenv("RETLENS_UPDATE_NO_UI", "1")
    (tmp_path / "user").mkdir()
    return tmp_path


def fake_build(folder, version, extra: dict | None = None):
    """A folder shaped like a RetLens build with its manifest."""
    files = {"RetLens.exe": b"MZ-retlens", "retlens-cli.exe": b"MZ-cli", "retlens-update.exe": b"MZ-upd",
             "_internal/python312.dll": b"x" * 2048, "_internal/docs/manual.md": "설명서".encode("utf-8"),
             **(extra or {})}
    for rel, data in files.items():
        p = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    manifest = {"product": "RetLens", "version": version, "files": {rel: len(data) for rel, data in files.items()}}
    with open(os.path.join(folder, "_internal", "retlens-build.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return str(folder)


def release_zip(path, build_dir, top="RetLens/"):
    with zipfile.ZipFile(path, "w") as z:
        for r, _d, fs in os.walk(build_dir):
            for f in fs:
                full = os.path.join(r, f)
                z.write(full, top + os.path.relpath(full, build_dir).replace("\\", "/"))
    return str(path)


# ------------------------------------------------------------------ versions, release JSON, hosts
def test_versions():
    assert install.parse_version("v0.9.1") == (0, 9, 1) and install.parse_version("0.10.0") == (0, 10, 0)
    for bad in ("v0.9", "0.9.1-rc1", "v1.2.3.4", "", None, "v99999.0.0"):
        assert install.parse_version(bad) is None
    assert install.is_newer("0.10.0", "0.9.9") and not install.is_newer("0.9.0", "0.9.0")
    assert not install.is_newer("0.8.0", "0.9.0") and not install.is_newer("garbage", "0.9.0")


SHA = "c7265ee16d19118748dbd8e775c5defb7d0ddedcf42d76c14c73b70709a8ce22"


def release_json(tag="v0.9.1", digest=f"sha256:{SHA}", **kw):
    name = f"RetLens-{tag[1:]}-win64.zip"
    return {"tag_name": tag, "name": f"RetLens {tag[1:]}", "body": "## 바뀐 점", "draft": False, "prerelease": False,
            "html_url": f"https://github.com/{install.REPO}/releases/tag/{tag}",
            "assets": [{"name": name, "size": 466, "digest": digest,
                        "browser_download_url": f"https://github.com/{install.REPO}/releases/download/{tag}/{name}"},
                       {"name": name + ".sha256", "size": 90,
                        "browser_download_url": f"https://github.com/{install.REPO}/releases/download/{tag}/{name}.sha256"}],
            **kw}


def test_release_json_and_what_is_trusted():
    rel = install.release_from_json(release_json())
    assert rel.version == "0.9.1" and rel.sha256 == SHA and rel.asset_name == "RetLens-0.9.1-win64.zip"
    assert rel.asset_url.endswith("/releases/download/v0.9.1/RetLens-0.9.1-win64.zip")
    same = f"{SHA}  RetLens-0.9.1-win64.zip\n"
    assert install.release_from_json(release_json(), same).sha256 == SHA  # digest and .sha256 agree
    with pytest.raises(install.UpdateError):  # they differ: refused
        install.release_from_json(release_json(), "0" * 64 + "  RetLens-0.9.1-win64.zip\n")
    assert install.release_from_json(release_json(digest=None), same).sha256 == SHA  # .sha256 alone
    assert install.release_from_json(release_json(digest=None), "0" * 64 + "  other.zip").sha256 is None  # wrong name
    assert install.release_from_json(release_json(digest="md5:abc")).sha256 is None
    assert install.release_from_json(release_json(prerelease=True)) is None
    assert install.release_from_json(release_json(draft=True)) is None
    assert install.release_from_json(release_json(tag="v0.9.1-rc1")) is None
    moved = release_json()
    moved["assets"][0]["browser_download_url"] = "https://evil.example/RetLens-0.9.1-win64.zip"
    assert install.release_from_json(moved) is None  # only the exact GitHub release URL
    with pytest.raises(install.UpdateError):  # no checksum: no download
        install.download(install.Release(version="0.9.1", tag="v0.9.1", asset_url=rel.asset_url))


def test_only_github_hosts():
    ok = ["https://github.com/x", "https://api.github.com/repos", "https://objects.githubusercontent.com/a",
          "https://release-assets.githubusercontent.com/a"]
    bad = ["http://github.com/x", "https://github.com.evil.io/x", "https://evil.githubusercontent.com/x",
           "https://user:pw@github.com/x", "https://github.com:8443/x", "ftp://github.com/x", "file:///C:/x"]
    assert all(install.url_allowed(u) for u in ok)
    assert not any(install.url_allowed(u) for u in bad)
    assert install.url_allowed("http://127.0.0.1:1234/x", frozenset({"127.0.0.1"}))


class _Server(http.server.ThreadingHTTPServer):
    routes: dict = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        route = self.server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        status, headers, body = route(self) if callable(route) else route
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server(monkeypatch):
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.routes = {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("RETLENS_UPDATE_API", base + "/latest")
    yield srv, base
    srv.shutdown()


def test_check_latest_newer_etag_rate_limit_and_redirects(server, places):
    srv, base = server
    data = release_json(tag="v99.0.0")
    for a in data["assets"]:  # the test server stands in for GitHub
        a["browser_download_url"] = base + "/dl/" + a["name"]
    body = json.dumps(data).encode()
    srv.routes["/latest"] = (200, {"ETag": '"abc"', "Content-Type": "application/json"}, body)
    srv.routes["/dl/RetLens-99.0.0-win64.zip.sha256"] = (200, {}, f"{SHA}  RetLens-99.0.0-win64.zip\n".encode())
    chk = install.check_latest()
    assert chk.error is None and chk.newer and chk.latest.version == "99.0.0" and chk.latest.sha256 == SHA
    assert chk.etag == '"abc"'
    srv.routes["/latest"] = lambda h: (304, {}, b"") if h.headers.get("If-None-Match") == '"abc"' else (500, {}, b"")
    again = install.check_latest(etag=chk.etag, cached=chk.cached)
    assert again.not_modified and again.latest.version == "99.0.0"
    srv.routes["/latest"] = (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 600)}, b"")
    assert "한도" in install.check_latest().error
    srv.routes["/latest"] = (302, {"Location": "https://evil.example/latest"}, b"")
    assert install.check_latest().error  # a redirect off GitHub is refused
    srv.routes["/latest"] = (200, {}, json.dumps(release_json(tag="v0.0.1")).encode())
    old = install.check_latest()
    assert old.error is None and not old.newer  # older than this program: nothing to do


# ------------------------------------------------------------------ staging
def test_stage_checks_the_zip_against_its_manifest(places, tmp_path):
    build = fake_build(tmp_path / "build", "9.9.9")
    z = release_zip(tmp_path / "RetLens-9.9.9-win64.zip", build)
    rel = install.Release(version="9.9.9", tag="v9.9.9", sha256="0" * 64)
    seen = []
    staged = install.stage(rel, z, progress=lambda *a: seen.append(a), run_check=False)
    assert os.path.basename(staged) == "RetLens.update-9.9.9" and os.path.isfile(os.path.join(staged, "RetLens.exe"))
    assert install.staged_ready("9.9.9") == staged and seen and seen[-1][0] == "확인 중"
    assert install.stage(rel, z, run_check=False) == staged  # reused
    shutil.rmtree(staged)
    with zipfile.ZipFile(tmp_path / "bad.zip", "w") as zf:
        zf.writestr("RetLens/../evil.txt", b"x")
    with pytest.raises(Exception):
        install.stage(rel, str(tmp_path / "bad.zip"), run_check=False)
    with zipfile.ZipFile(tmp_path / "top.zip", "w") as zf:
        zf.writestr("Other/RetLens.exe", b"x")
    with pytest.raises(install.UpdateError):
        install.stage(rel, str(tmp_path / "top.zip"), run_check=False)
    short = tmp_path / "short"
    shutil.copytree(build, short)
    with open(short / "_internal" / "python312.dll", "wb") as f:
        f.write(b"cut")  # a file that is not the size the manifest says
    with pytest.raises(install.UpdateError, match="크기"):
        install.stage(rel, release_zip(tmp_path / "short.zip", short), run_check=False)
    assert not os.path.exists(install.staged_dir("9.9.9") + ".partial")  # nothing half-made left


# ------------------------------------------------------------------ install from a portable copy
@needs_windows
def test_install_from_a_portable_copy(places, tmp_path):
    portable = fake_build(tmp_path / "Downloads" / "RetLens", "1.0.0")
    os.makedirs(os.path.join(portable, "my_notes"))  # the user's own folder there: not copied
    info = install.install_from_folder(portable, desktop=True)
    target = install.install_dir()
    assert info["dir"] == target and info["version"] == "1.0.0" and not os.path.exists(os.path.join(target, "my_notes"))
    marker = install.read_marker(target)
    assert marker["id"] == info["id"] and marker["source"] == os.path.realpath(portable)
    lnk = install.shortcut_paths()
    assert install.same_path(install.read_shortcut(lnk["start_menu"]), os.path.join(target, "RetLens.exe"))
    assert os.path.isfile(lnk["desktop"]) and info["registration"]["errors"] == []
    # a newer portable copy replaces it: the id stays, files the user put in the program folder come along
    os.makedirs(os.path.join(target, "GMT", "assets"))
    newer = fake_build(tmp_path / "Downloads2" / "RetLens", "1.1.0")
    info2 = install.install_from_folder(newer)
    assert info2["id"] == info["id"] and install.folder_version(target) == "1.1.0"
    assert os.path.isdir(os.path.join(target, "GMT", "assets"))
    deadline = time.time() + 10
    while time.time() < deadline and any(n.startswith("RetLens.old-") for n in os.listdir(os.path.dirname(target))):
        time.sleep(0.1)
    assert not any(n.startswith("RetLens.old-") for n in os.listdir(os.path.dirname(target)))  # old copy deleted
    with pytest.raises(install.UpdateError):  # never into itself
        install.install_from_folder(target)


@needs_windows
def test_install_refuses_a_foreign_folder(places, tmp_path):
    target = install.install_dir()
    os.makedirs(target)
    with open(os.path.join(target, "something.txt"), "w") as f:
        f.write("not ours")
    with pytest.raises(install.UpdateError, match="RetLens가 아닌"):
        install.install_from_folder(fake_build(tmp_path / "p", "1.0.0"))
    assert os.path.isfile(os.path.join(target, "something.txt"))


# ------------------------------------------------------------------ the helper
def run_helper(job: dict, tmp_path, parent: subprocess.Popen | None = None, timeout: float = 120) -> dict:
    job = {"result": str(tmp_path / "user" / "update_result.json"), "journal": str(tmp_path / "user" / "pending.json"),
           "started_marker": str(tmp_path / "user" / "update_started.json"), "log": str(tmp_path / "user" / "upd.log"),
           "ready": str(tmp_path / "user" / "ready"), "workdir": str(tmp_path / "user"), "wait_s": 60,
           "parent_pid": parent.pid if parent else None, "retry_s": 2.0, **job}
    path = tmp_path / "user" / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=ROOT)
    p = subprocess.run([sys.executable, "-m", "retlens.update_helper", str(path)], env=env, timeout=timeout,
                       cwd=str(tmp_path), capture_output=True)
    res = helper.read_json(job["result"]) or {}
    res["_code"] = p.returncode
    res["_log"] = open(job["log"], encoding="utf-8").read() if os.path.isfile(job["log"]) else ""
    return res


def staged_for(tmp_path, version, name="RetLens.update-9.9.9", exe: str | None = None):
    """A staged build; exe: a real program (System32) copied in as its RetLens.exe, the manifest updated."""
    d = fake_build(tmp_path / "Programs" / name, version)
    if exe:
        shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", exe), os.path.join(d, "RetLens.exe"))
        m = helper.read_json(os.path.join(d, helper.MANIFEST))
        m["files"]["RetLens.exe"] = os.path.getsize(os.path.join(d, "RetLens.exe"))
        helper.write_json(os.path.join(d, helper.MANIFEST), m)
    helper.write_json(os.path.join(d, helper.STAMP), {"version": version})
    return d


@needs_windows
def test_helper_swaps_after_the_parent_exits_and_keeps_user_files(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    os.makedirs(os.path.join(install_dir, "GMT"))
    staged = staged_for(tmp_path, "9.9.9")
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                      "relaunch": False}, tmp_path, parent)
    assert res["ok"], res
    assert install.folder_version(install_dir) == "9.9.9" and os.path.isdir(os.path.join(install_dir, "GMT"))
    assert os.path.isdir(res["old"]) and install.folder_version(res["old"]) == "1.0.0" and not os.path.exists(staged)
    assert "waiting for RetLens to exit" in res["_log"] and not os.path.exists(tmp_path / "user" / "pending.json")


@needs_windows
def test_helper_undoes_a_version_that_does_not_start(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    staged = staged_for(tmp_path, "9.9.9", exe="whoami.exe")  # exits at once without saying it started
    res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                      "relaunch": True, "health_timeout_s": 20}, tmp_path)
    assert not res["ok"] and res.get("undone") and res["health"] == "exited"
    assert install.folder_version(install_dir) == "1.0.0"  # the old version is back
    # one that does say it started stays
    staged = staged_for(tmp_path, "9.9.9", name="RetLens.update-9.9.9b", exe="whoami.exe")
    helper.write_json(str(tmp_path / "user" / "update_started.json"), {"version": "9.9.9"})
    res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                      "relaunch": True, "health_timeout_s": 20}, tmp_path)
    assert res["ok"] and res["health"] == "ok" and install.folder_version(install_dir) == "9.9.9"


@needs_windows
def test_helper_leaves_everything_when_the_folder_is_held(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    staged = staged_for(tmp_path, "9.9.9")
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=install_dir)  # cwd holds it
    try:
        res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                          "relaunch": False}, tmp_path)
    finally:
        holder.kill()
        holder.wait()
    assert not res["ok"] and "바꾸지 못했습니다" in res["error"]
    assert install.folder_version(install_dir) == "1.0.0" and install.staged_ready("9.9.9") == staged


@needs_windows
def test_helper_refuses_a_staged_folder_that_does_not_check_out(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    staged = staged_for(tmp_path, "9.9.9")
    os.remove(os.path.join(staged, "_internal", "python312.dll"))
    res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                      "relaunch": False}, tmp_path)
    assert not res["ok"] and "온전하지" in res["error"] and install.folder_version(install_dir) == "1.0.0"


@needs_windows
def test_helper_uninstall_checks_the_id_and_purges_only_what_it_is_given(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    helper.write_json(os.path.join(install_dir, helper.MARKER), {"product": "RetLens", "id": "abc"})
    lnk = tmp_path / "StartMenu" / "RetLens.lnk"
    lnk.parent.mkdir()
    lnk.write_bytes(b"lnk")
    user = tmp_path / "user"
    (user / "cache").mkdir()
    (user / "models").mkdir()  # not in the purge list: stays
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("keep")
    job = {"action": "uninstall", "install": install_dir, "install_id": "wrong", "shortcuts": [str(lnk)],
           "purge": [str(user / "cache"), str(outside)], "user_dir": str(user)}
    res = run_helper(job, tmp_path)
    assert not res["ok"] and os.path.isdir(install_dir)  # not our install id: untouched
    res = run_helper({**job, "install_id": "abc"}, tmp_path)
    assert res["ok"] and not os.path.exists(install_dir) and not lnk.exists()
    assert not (user / "cache").exists() and (user / "models").exists() and outside.read_text() == "keep"


@needs_windows
def test_recovery_finishes_a_cut_off_swap(places, tmp_path):
    install_dir = str(tmp_path / "Programs" / "RetLens")
    staged = staged_for(tmp_path, "9.9.9")
    old = fake_build(tmp_path / "Programs" / "RetLens.old-x", "1.0.0")
    os.makedirs(os.path.join(old, "GMT"))
    journal = tmp_path / "user" / "pending.json"
    journal.write_text(json.dumps({"install": install_dir, "old": old, "staged": staged, "to": "9.9.9",
                                   "phase": "old-moved"}), encoding="utf-8")
    res = run_helper({"action": "recover", "journal": str(journal)}, tmp_path)
    assert res["ok"] and res["recovered"] == "forward" and install.folder_version(install_dir) == "9.9.9"
    assert os.path.isdir(os.path.join(install_dir, "GMT")) and not journal.exists()


# ------------------------------------------------------------------ bits
def test_clean_env_drops_another_bundles_paths(monkeypatch):
    monkeypatch.setenv("QTWEBENGINEPROCESS_PATH", r"C:\portable\_internal\QtWebEngineProcess.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\portable")
    monkeypatch.setenv("QT_PLUGIN_PATH", "x")
    env = install.clean_env()
    assert "QTWEBENGINEPROCESS_PATH" not in env and "_PYI_APPLICATION_HOME_DIR" not in env and "QT_PLUGIN_PATH" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and env.get("PATH") == os.environ.get("PATH")


def test_remove_old_copy_keeps_a_folder_with_user_files(tmp_path):
    old = fake_build(tmp_path / "RetLens.old-1", "1.0.0")
    assert install.remove_old_copy(old) and not os.path.exists(old)
    kept = fake_build(tmp_path / "RetLens.old-2", "1.0.0")
    os.makedirs(os.path.join(kept, "GMT"))
    assert not install.remove_old_copy(kept) and os.path.isdir(os.path.join(kept, "GMT"))
    assert not os.path.exists(os.path.join(kept, "_internal"))  # the build itself went
    assert not install.remove_old_copy(str(tmp_path))  # not one of ours


def test_settings_save_keeps_keys_it_does_not_know(tmp_path, monkeypatch):
    from retlens import settings

    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"blender": "x", "future_option": 3}), encoding="utf-8")
    s = settings.load(reload=True)
    assert s.check_updates is True
    s.check_updates = False
    settings.save(s)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["future_option"] == 3 and data["check_updates"] is False
    settings.load(reload=True)


def test_purge_list_is_empty_when_the_user_folder_was_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path))
    assert install.uninstall_purge_list() == []


def test_release_from_a_downloaded_zip(tmp_path):
    z = tmp_path / "RetLens-1.2.3-win64.zip"
    z.write_bytes(b"zip")
    (tmp_path / "RetLens-1.2.3-win64.zip.sha256").write_text(f"{SHA}  RetLens-1.2.3-win64.zip\n")
    rel = install.release_from_zip(str(z))
    assert rel.version == "1.2.3" and rel.sha256 == SHA and rel.local_zip == str(z)
    with pytest.raises(install.UpdateError):
        install.release_from_zip(str(tmp_path / "something.zip"))


def test_update_dialog_and_status_button(tmp_path, monkeypatch):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtCore = pytest.importorskip("PySide6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from retlens.app import update_ui

    store = QtCore.QSettings(str(tmp_path / "retlens.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(update_ui, "_settings_store", lambda: store)

    class Win(QtWidgets.QWidget):
        auto_setup = True

        def __init__(self):
            super().__init__()
            self.logs, self.messages = [], []
            self.scene = type("S", (), {"log": self.logs.append, "items": [], "jobs_busy": lambda s: False})()

        def status(self, text, ms=0):
            self.messages.append(text)

    win = Win()
    ctl = update_ui.UpdateController(win)
    rel = install.Release(version="99.0.0", tag="v99.0.0", name="RetLens 99.0.0", notes="* 새 기능", sha256=SHA,
                          size=466_000_000)
    chk = install.Check(current="0.9.0", latest=rel, newer=True)
    ctl._auto_checked(chk)
    assert ctl.button.text() == "업데이트 99.0.0" and not ctl.button.isHidden() and "99.0.0" in win.messages[-1]
    ctl.last_check = chk
    ctl.open_dialog(force=False)  # the status-bar button: what is known (the menu asks GitHub again)
    d = ctl.dialog
    assert "99.0.0" in d.head.text() and d.b_main.text() == "업데이트" and "새 기능" in d.notes.toPlainText()
    assert not d.b_main.isEnabled()  # from the source tree: git, not this updater
    ctl._auto_checked(install.Check(current="0.9.0", latest=rel, newer=False))
    assert ctl.button.isHidden()
    d.hide()
    app.processEvents()


def test_the_automatic_check_asks_github_at_most_once_a_day(tmp_path, monkeypatch):
    """At start-up only, at most once in CHECK_EVERY_S even when a newer version is known (its button shows from what
    was stored), never while GitHub's request limit lasts; a stored newer version this program has reached is
    forgotten. 업데이트 확인 (manual) is not held back."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtCore = pytest.importorskip("PySide6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from retlens.app import update_ui

    store = QtCore.QSettings(str(tmp_path / "retlens.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(update_ui, "_settings_store", lambda: store)
    monkeypatch.setattr(install, "running_version", lambda: "1.0.0")
    asked = []
    monkeypatch.setattr(install, "check_latest", lambda **kw: asked.append(1) or install.Check(current="1.0.0"))

    class Win(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.scene = type("S", (), {"log": lambda s, m: None, "items": []})()

        def status(self, text, ms=0):
            pass

    ctl = update_ui.UpdateController(Win())
    started = []
    from types import SimpleNamespace

    monkeypatch.setattr(update_ui, "threading", SimpleNamespace(  # only this module's threads
        Thread=lambda target, **kw: SimpleNamespace(start=lambda: started.append(target))))
    store.setValue("update/last_check", time.time() - 60)
    store.setValue("update/newer", "2.0.0")
    ctl._auto_check()
    assert not started and ctl.button.text() == "업데이트 2.0.0" and not ctl.button.isHidden()  # known: no request
    store.setValue("update/newer", "1.0.0")  # updated to it since
    ctl._auto_check()
    assert not started and store.value("update/newer") == ""
    store.setValue("update/last_check", time.time() - install.CHECK_EVERY_S - 1)
    store.setValue("update/retry_at", time.time() + 600)  # GitHub's limit
    ctl._auto_check()
    assert not started
    store.setValue("update/retry_at", 0)
    ctl._auto_check()
    assert len(started) == 1
    limited = install.Check(current="1.0.0", error="한도", retry_at=time.time() + 900)
    monkeypatch.setattr(install, "check_latest", lambda **kw: limited)
    ctl.check(force=True)  # a manual check that hit the limit holds the automatic one back
    assert float(store.value("update/retry_at")) == pytest.approx(limited.retry_at)
    rel = install.Release(version="3.0.0", tag="v3.0.0", name="RetLens 3.0.0", notes="", sha256=SHA, size=1)
    monkeypatch.setattr(install, "check_latest", lambda **kw: install.Check(current="1.0.0", latest=rel, newer=True))
    ctl.check(force=True)  # 업데이트 확인 found it: the next start shows its button without asking again
    assert store.value("update/newer") == "3.0.0"


# ------------------------------------------------------------------ after the review
@needs_windows
def test_own_children_are_not_other_retlens():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        time.sleep(0.5)
        assert child.pid in install.own_descendants()
        assert child.pid not in [pid for pid, _ in install.processes_in(os.path.dirname(sys.executable))]
    finally:
        child.kill()
        child.wait()


@needs_windows
def test_a_new_version_that_cannot_start_is_undone(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    staged = staged_for(tmp_path, "9.9.9")  # its RetLens.exe is not a program at all
    res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                      "relaunch": True, "health_timeout_s": 30}, tmp_path)
    assert not res["ok"] and res.get("undone") and res["health"] == "exited"
    assert install.folder_version(install_dir) == "1.0.0"


@needs_windows
def test_a_failed_undo_keeps_the_journal_for_recovery(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    staged = staged_for(tmp_path, "9.9.9", exe="PING.EXE")  # runs ~2 s, then exits without saying it started
    journal = tmp_path / "user" / "pending.json"
    holder = {}

    def hold_old():  # once the old folder exists, keep it busy so it cannot be put back
        deadline = time.time() + 20
        while time.time() < deadline:
            olds = [n for n in os.listdir(tmp_path / "Programs") if n.startswith("RetLens.old-")]
            if olds:
                holder["p"] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                               cwd=str(tmp_path / "Programs" / olds[0]))
                return
            time.sleep(0.05)

    t = threading.Thread(target=hold_old)
    t.start()
    try:
        res = run_helper({"action": "swap", "install": install_dir, "staged": staged, "from": "1.0.0", "to": "9.9.9",
                          "relaunch": True, "relaunch_args": ["-n", "3", "127.0.0.1"], "health_timeout_s": 30,
                          "putback_s": 2.0}, tmp_path)
    finally:
        t.join()
        if "p" in holder:
            holder["p"].kill()
            holder["p"].wait()
    assert not res["ok"] and "되돌리지도 못했습니다" in res["error"]
    assert journal.exists()  # the next start / sign-in puts the old version back
    res2 = run_helper({"action": "recover", "journal": str(journal)}, tmp_path)
    assert res2["ok"] and res2["recovered"] == "back" and install.folder_version(install_dir) == "1.0.0"


@needs_windows
def test_uninstall_keeps_files_that_are_not_retlens(places, tmp_path):
    install_dir = fake_build(tmp_path / "Programs" / "RetLens", "1.0.0")
    helper.write_json(os.path.join(install_dir, helper.MARKER), {"product": "RetLens", "id": "abc"})
    os.makedirs(os.path.join(install_dir, "GMT", "assets"))
    res = run_helper({"action": "uninstall", "install": install_dir, "install_id": "abc", "shortcuts": [],
                      "purge": [], "user_dir": str(tmp_path / "user")}, tmp_path)
    assert res["ok"] and not os.path.exists(install_dir) and res["leftover"]
    assert os.path.isdir(os.path.join(res["leftover"], "GMT", "assets"))
    assert not os.path.exists(os.path.join(res["leftover"], "_internal"))


def test_staged_copy_is_reused_only_for_the_same_release(places, tmp_path):
    build = fake_build(tmp_path / "build", "9.9.9")
    z = release_zip(tmp_path / "RetLens-9.9.9-win64.zip", build)
    staged = install.stage(install.Release(version="9.9.9", tag="v9.9.9", sha256="a" * 64), z, run_check=False)
    assert install.staged_ready("9.9.9", "a" * 64) == staged and install.staged_ready("9.9.9") == staged
    assert install.staged_ready("9.9.9", "b" * 64) is None  # another zip of the same number: unpacked again


@needs_windows
def test_only_shortcuts_to_retlens_are_ours(places, tmp_path):
    build = fake_build(tmp_path / "b" / "RetLens", "1.0.0")
    mine, other = str(tmp_path / "mine.lnk"), str(tmp_path / "other.lnk")
    install.create_shortcut(mine, os.path.join(build, "RetLens.exe"))
    install.create_shortcut(other, os.path.join(os.environ["SystemRoot"], "System32", "whoami.exe"))
    assert install.points_to_retlens(mine) and install.points_to_retlens(mine, build)
    assert not install.points_to_retlens(mine, str(tmp_path)) and not install.points_to_retlens(other)


def test_cli_version_is_fast_with_global_options(tmp_path):
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "retlens_cli.py"), "--pretty", "version"],
                         capture_output=True, timeout=120, cwd=ROOT)
    assert out.returncode == 0 and json.loads(out.stdout.decode())["version"] == install.running_version()
