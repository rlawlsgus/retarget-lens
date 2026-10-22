"""설치 도우미 (khumanoid/prereqs.py): what is installed, whether this PC can take what is missing, and
installs that run only when needed - against a local web server standing in for the publishers
(no test downloads anything from the internet)."""

import hashlib
import http.server
import io
import os
import sys
import threading
import types
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid import paths, prereqs, settings  # noqa: E402

RTX = [{"name": "NVIDIA GeForce RTX 4080", "driver": "600.10", "vram_gb": 16.0}]
BLENDER_CANDIDATES = settings.blender_candidates  # the real search (the pc fixture hides it)


class _Handler(http.server.BaseHTTPRequestHandler):
    """GET with Range support from a {path: bytes} dict; counts requests. drops[path]: byte counts,
    one per request, after which the connection closes short of its Content-Length. plain: paths
    whose server ignores Range (always 200). pages[path]: an HTML page sent (200) for ranged requests,
    as a captive portal or proxy would."""
    files: dict = {}
    hits: list = []
    drops: dict = {}
    plain: set = set()
    pages: dict = {}

    def do_GET(self):  # noqa: N802
        self.hits.append((self.path, self.headers.get("Range")))
        if self.path in self.pages and self.headers.get("Range"):
            page = self.pages[self.path]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        data = self.files.get(self.path)
        if data is None:
            self.send_error(404)
            return
        start = 0
        rng = None if self.path in self.plain else self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                self.send_error(416)
                return
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data) - start))
        self.end_headers()
        cut = self.drops.get(self.path)
        if cut:
            self.wfile.write(data[start:start + cut.pop(0)])
            self.close_connection = True
            return
        self.wfile.write(data[start:])

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    files, hits, drops, plain, pages = {}, [], {}, set(), {}
    handler = type("H", (_Handler,), {"files": files, "hits": hits, "drops": drops, "plain": plain, "pages": pages})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(base=f"http://127.0.0.1:{srv.server_address[1]}/", files=files, hits=hits, drops=drops,
                                plain=plain, pages=pages)
    srv.shutdown()


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A PC with none of the components: empty user folder, finders pointed at empty places."""
    monkeypatch.setenv("KHUMANOID_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setenv(settings.GMT_ENV, str(tmp_path / "nogmt"))
    monkeypatch.setenv("SMPL_MODEL_DIR", str(tmp_path / "models"))
    for k in (settings.ISAAC_ENV, "BLENDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(settings, "blender_candidates", lambda: [])
    which = settings.shutil.which  # only Blender is hidden from PATH
    monkeypatch.setattr(settings.shutil, "which", lambda cmd, *a, **k: None if cmd == "blender" else which(cmd, *a, **k))
    monkeypatch.setattr(settings, "ISAAC_DIRS", [str(tmp_path / "isaacsim")])
    monkeypatch.setattr(settings, "gmt_sibling", lambda: str(tmp_path / "gmt-sibling"))  # not this PC's ..\GMT
    monkeypatch.setattr(paths, "default_smpl_model_dir", lambda: str(tmp_path / "default-models"))  # nor models\
    monkeypatch.setattr(paths, "FROZEN", True)  # this test Python's isaacsim package does not count
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: [])
    monkeypatch.setattr(prereqs, "time", types.SimpleNamespace(sleep=lambda _s: None))  # retries without waiting
    settings.load(reload=True)
    yield tmp_path
    settings.load(reload=True)


def _touch(path, text=""):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def test_probe_decides(pc, monkeypatch):
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 100.0)
    st = {s.key: s for s in prereqs.probe_all(online=False)}
    assert st["blender"].state == "missing" and st["blender"].action == "install"
    assert st["gmt"].action == "install" and st["gmt"].license.consent
    assert st["smpl"].action == "manual"  # registration: never downloaded
    isaac = st["isaac"]
    assert isaac.action == "blocked" and "RTX" in isaac.note  # no NVIDIA GPU: not installable here
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: RTX)
    assert prereqs.probe("isaac", online=False).action == "install"
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: [{"name": "Quadro P2000", "driver": "600.1", "vram_gb": 5.0}])
    assert "RTX GPU가 필요" in prereqs.probe("isaac", online=False).note
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 1.0)  # a full disk blocks the download
    assert prereqs.probe("blender", online=False).action == "blocked"
    with pytest.raises(prereqs.SetupError, match="설치할 수 없습니다"):
        prereqs.install("blender")
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 100.0)
    monkeypatch.setattr(prereqs, "reachable", lambda url, timeout=8.0: (False, "offline"))  # offline: blocked too
    st = prereqs.probe("gmt", online=True)
    assert st.action == "blocked" and "인터넷" in st.note


def test_blender_ready_or_configured_not_downloaded(pc, monkeypatch):
    def exe(folder):
        p = pc / folder / "blender.exe"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return str(p)

    ok = exe("blender-4.5.3-windows-x64")
    settings.save(settings.Settings(blender=ok))
    st = prereqs.probe("blender", online=False)
    assert st.state == "ready" and st.action == "none" and "4.5.3" in st.detail
    assert prereqs.install("blender").action == "none"  # nothing to do, nothing fetched
    old = exe("blender-4.2.0-windows-x64")
    settings.save(settings.Settings(blender=old))  # set to another version, while a 4.5 sits in a usual place
    monkeypatch.setattr(settings, "blender_candidates", lambda: [(old, "x"), (ok, "자동 (C:\\blender)")])
    st = prereqs.probe("blender", online=False)
    assert st.state == "incompatible" and st.action == "configure" and st.target == ok
    assert prereqs.install("blender").action == "none" and settings.load(reload=True).blender == ok
    monkeypatch.setattr(settings, "blender_candidates", lambda: [])
    settings.save(settings.Settings(blender=old))
    st = prereqs.probe("blender", online=False)  # only a 4.2: incompatible, a 4.5 is installed beside it
    assert st.state == "incompatible" and st.action == "install" and "4.2.0" in st.found


def test_blender_install(pc, server, monkeypatch):
    """The newest 4.5.x from the publisher's folder, checked against its .sha256, unpacked into the
    assistant's folder - where the usual search finds it again even without the setting."""
    base, files, hits = server.base, server.files, server.hits
    zipped = _zip({"blender-4.5.10-windows-x64/blender.exe": b"exe", "blender-4.5.10-windows-x64/4.5/x.py": b"py"})
    files["/index/"] = b'<a href="blender-4.5.2-windows-x64.zip">..</a><a href="blender-4.5.10-windows-x64.zip">'
    files["/index/blender-4.5.10.sha256"] = (f"{'0' * 64}  blender-4.5.10-windows-x64.msi\n"
                                             f"{hashlib.sha256(zipped).hexdigest()}  blender-4.5.10-windows-x64.zip\n").encode()
    files["/index/blender-4.5.10-windows-x64.zip"] = zipped
    st = prereqs.install("blender", source=base + "index/")
    exe = os.path.join(prereqs.tools_dir(), "blender-4.5.10-windows-x64", "blender.exe")
    assert st.state == "ready" and settings.load(reload=True).blender == exe and os.path.isfile(exe)
    assert os.path.isfile(os.path.join(prereqs.tools_dir(), "blender-4.5.10-windows-x64", "4.5", "x.py"))
    assert not os.listdir(prereqs.downloads_dir())  # the zip is removed once unpacked
    n = len(hits)
    assert prereqs.install("blender", source=base + "index/").action == "none" and len(hits) == n  # no request
    monkeypatch.undo()  # the real usual places again (with KHUMANOID_USER_DIR still the test's)
    monkeypatch.setenv("KHUMANOID_USER_DIR", str(pc / "user"))
    assert exe in [e for e, _ in settings.blender_candidates()]


def test_download_resumes_and_checks(tmp_path, server):
    base, files = server.base, server.files
    data = os.urandom(3 << 20)
    files["/big.bin"] = data
    dest = str(tmp_path / "big.bin")
    with open(dest + ".part", "wb") as f:
        f.write(data[: 1 << 20])  # a download cut off earlier
    seen = []
    prereqs.download(base + "big.bin", dest, sha256=hashlib.sha256(data).hexdigest(),
                     progress=lambda stage, d, t: seen.append((d, t)))
    assert open(dest, "rb").read() == data and not os.path.exists(dest + ".part")
    assert seen[0][0] > (1 << 20) and seen[-2][0] == len(data)  # went on from the first MB
    bad = str(tmp_path / "bad.bin")
    with pytest.raises(prereqs.SetupError, match="체크섬"):
        prereqs.download(base + "big.bin", bad, sha256="0" * 64)
    assert not os.path.exists(bad) and not os.path.exists(bad + ".part")
    stop = threading.Event()
    stop.set()
    with pytest.raises(prereqs.Cancelled):
        prereqs.download(base + "big.bin", str(tmp_path / "c.bin"), cancel=stop)
    with pytest.raises(prereqs.SetupError, match="404"):
        prereqs.download(base + "nothing", str(tmp_path / "n.bin"))


def test_gmt_install_needs_consent(pc, server, monkeypatch):
    base, files = server.base, server.files
    fake = {"LICENSE": b"Apache", "assets/pretrained_checkpoints/pretrained.pt": b"policy",
            "assets/robots/g1/g1.xml": b"<mujoco/>"}
    for rel, data in fake.items():
        files["/" + rel] = data
    table = {rel: (_blob(data), len(data)) for rel, data in fake.items()}
    monkeypatch.setattr(prereqs, "GMT_FILES", {k: v for k, v in table.items() if not k.endswith("g1.xml")})
    monkeypatch.setattr(prereqs, "GMT_MODEL_FILES", {k: v for k, v in table.items() if k.endswith("g1.xml")})
    with pytest.raises(prereqs.SetupError, match="동의"):
        prereqs.install("gmt", source=base)
    st = prereqs.install("gmt", accept=True, source=base)
    dest = os.path.join(paths.user_dir(), settings.GMT_INSTALL)
    assert st.state == "ready" and settings.load(reload=True).gmt_dir == dest
    assert open(os.path.join(dest, "assets", "pretrained_checkpoints", "pretrained.pt"), "rb").read() == b"policy"
    assert os.path.isfile(os.path.join(dest, "GMT_COMMIT.txt"))
    files["/LICENSE"] = b"tampered"  # a changed file on the server never replaces a verified one
    os.remove(os.path.join(dest, "LICENSE"))
    settings.save(settings.Settings())
    with pytest.raises(prereqs.SetupError, match="체크섬"):
        prereqs.install_gmt(base=base)


def test_isaac_install_needs_eula(pc, server, monkeypatch):
    base, files = server.base, server.files
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: RTX)
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 100.0)
    zipped = _zip({"python.bat": b"@echo off", "isaac-sim.bat": b"", "VERSION": b"6.1.0+release.1\n"})
    files["/" + prereqs.ISAAC_ZIP] = zipped
    dl = str(pc / "dl")
    with pytest.raises(prereqs.SetupError, match="EULA"):
        prereqs.install("isaac", source=base, download_dir=dl, md5=hashlib.md5(zipped).hexdigest())
    st = prereqs.install("isaac", accept=True, source=base, download_dir=dl, md5=hashlib.md5(zipped).hexdigest())
    launcher = os.path.join(settings.ISAAC_DIRS[0], settings.ISAAC_LAUNCHER)
    assert st.state == "ready" and settings.load(reload=True).isaac_python == launcher
    assert "6.1.0" in st.detail


def test_smpl_import(pc):
    good = pc / "models_smplx_v1_1.zip"
    good.write_bytes(_zip({"models/smplx/SMPLX_NEUTRAL.npz": b"n", "models/smplx/SMPLX_MALE.npz": b"m",
                           "models/smplx/SMPLX_NEUTRAL.pkl": b"p", "models/readme.txt": b"r"}))
    with pytest.raises(prereqs.SetupError, match="zip"):
        prereqs.install("smpl")
    st = prereqs.install("smpl", source=str(good))
    assert st.state == "ready" and sorted(os.listdir(pc / "models" / "smplx")) == ["SMPLX_MALE.npz", "SMPLX_NEUTRAL.npz"]
    assert prereqs.install("smpl", source=str(good)).action == "none"  # already there: nothing imported again
    wrong = pc / "wrong.zip"
    wrong.write_bytes(_zip({"smplh/SMPLH_MALE.npz": b"x"}))
    with pytest.raises(prereqs.SetupError, match="SMPLX_NEUTRAL"):
        prereqs.import_smpl(str(wrong))
    evil = pc / "evil.zip"
    evil.write_bytes(_zip({"../../smplx/SMPLX_NEUTRAL.npz": b"x"}))
    with pytest.raises(prereqs.SetupError, match="위험한 경로"):
        prereqs.import_smpl(str(evil))
    settings.save(settings.Settings(smpl_model_dir=str(pc / "moved")))  # a stale setting, the models still here
    st = prereqs.import_smpl(str(good))
    assert st.state == "ready" and settings.load(reload=True).smpl_model_dir == str(pc / "models")
    assert sorted(os.listdir(pc / "models" / "smplx")) == ["SMPLX_MALE.npz", "SMPLX_NEUTRAL.npz"]  # nothing unpacked


def test_stale_settings_are_repointed_not_reinstalled(pc, monkeypatch):
    """A setting pointing at a moved or old copy while a compatible one sits in a usual place:
    configure (the setting is changed), nothing is downloaded and no licence is asked again."""
    from khumanoid import gmt_policy

    monkeypatch.setattr(gmt_policy, "problem", lambda path: "")  # stand-in policy files
    good = pc / "gmt-sibling"
    _touch(good / settings.GMT_POLICY)
    _touch(good / settings.GMT_MODEL)
    settings.save(settings.Settings(gmt_dir=str(pc / "moved-gmt")))
    st = prereqs.probe("gmt", online=False)
    assert st.action == "configure" and st.target == str(good)
    assert prereqs.install("gmt").state == "ready" and settings.load(reload=True).gmt_dir == str(good)  # no accept=

    models = pc / "default-models"
    _touch(models / "smplx" / "SMPLX_NEUTRAL.npz")
    settings.save(settings.Settings(smpl_model_dir=str(pc / "moved-models")))
    st = prereqs.probe("smpl", online=False)
    assert st.action == "configure" and st.target == str(models)
    assert prereqs.install("smpl").state == "ready" and settings.load(reload=True).smpl_model_dir == str(models)

    old, new = pc / "isaacsim", pc / f"isaacsim-{prereqs.ISAAC_VERSION}"
    _touch(old / settings.ISAAC_LAUNCHER)
    _touch(old / "VERSION", "5.0.0+release.1\n")
    launcher = _touch(new / settings.ISAAC_LAUNCHER)
    _touch(new / "VERSION", "6.1.0+release.1\n")
    settings.save(settings.Settings(isaac_python=str(old)))  # an older Isaac Sim, while a 6.1 is beside it
    st = prereqs.probe("isaac", online=False)
    assert st.state == "incompatible" and st.action == "configure" and st.target == launcher
    assert prereqs.install("isaac").state == "ready" and settings.load(reload=True).isaac_python == launcher
    settings.save(settings.Settings())
    assert settings.find_isaac().path == str(old / settings.ISAAC_LAUNCHER)  # C:\isaacsim first without a setting
    os.remove(old / settings.ISAAC_LAUNCHER)
    assert settings.find_isaac().path == launcher  # the assistant's C:\isaacsim-6.1.0 is a usual place too

    monkeypatch.setattr(settings, "blender_candidates", BLENDER_CANDIDATES)  # the real search, in empty places
    monkeypatch.setattr(settings, "BLENDER_GLOB", str(pc / "noblender" / "*" / "blender.exe"))
    for k in ("ProgramFiles", "ProgramW6432"):
        monkeypatch.setenv(k, str(pc / "pf"))
    on_path = _touch(pc / "bin" / "blender-4.5.1-windows-x64" / "blender.exe")
    monkeypatch.setattr(settings.shutil, "which", lambda cmd, *a, **k: on_path if cmd == "blender" else None)
    settings.save(settings.Settings(blender=str(pc / "moved" / "blender.exe")))
    st = prereqs.probe("blender", online=False)
    assert st.action == "configure" and st.target == on_path
    unfinished = _touch(prereqs.tools_dir() + os.sep + "blender-4.5.9-windows-x64.partial" + os.sep + "blender.exe")
    assert unfinished not in [e for e, _ in settings.blender_candidates()]  # an unpack cut short is no Blender
    assert prereqs.probe("blender", online=False).target == on_path


def test_isaac_never_replaces_a_folder(pc, server, monkeypatch):
    """An older Isaac Sim (or anything) in C:\\isaacsim stays: 6.1 goes into C:\\isaacsim-6.1.0; with
    both taken the install is blocked, and install_isaac itself refuses a non-empty target."""
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: RTX)
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 100.0)  # 35 GB needed: not this test PC's business
    old = pc / "isaacsim"
    _touch(old / settings.ISAAC_LAUNCHER, "old")
    _touch(old / "VERSION", "5.0.0+release.1\n")
    _touch(old / "my_extension" / "ext.py", "mine")
    st = prereqs.probe("isaac", online=False)
    new = str(pc / f"isaacsim-{prereqs.ISAAC_VERSION}")
    assert st.state == "incompatible" and st.action == "install" and st.target == new
    zipped = _zip({"python.bat": b"@echo off", "VERSION": b"6.1.0+release.1\n"})
    server.files["/" + prereqs.ISAAC_ZIP] = zipped
    md5 = hashlib.md5(zipped).hexdigest()
    st = prereqs.install("isaac", accept=True, source=server.base, download_dir=str(pc / "dl"), md5=md5)
    assert st.state == "ready" and settings.load(reload=True).isaac_python == os.path.join(new, settings.ISAAC_LAUNCHER)
    assert open(old / settings.ISAAC_LAUNCHER).read() == "old" and os.path.isfile(old / "my_extension" / "ext.py")
    with pytest.raises(prereqs.SetupError, match="이미 있어"):
        prereqs.install_isaac(base=server.base, download_dir=str(pc / "dl"), target=str(old), md5=md5)
    assert open(old / settings.ISAAC_LAUNCHER).read() == "old"
    os.remove(os.path.join(new, settings.ISAAC_LAUNCHER))  # both folders taken, neither a 6.1
    settings.save(settings.Settings())
    st = prereqs.probe("isaac", online=False)
    assert st.action == "blocked" and "설치 폴더" in st.note and prereqs.isaac_target() is None


def test_download_survives_dropped_connections(tmp_path, server, monkeypatch):
    """A response cut short of its Content-Length is resumed from what came; drops that each make
    progress never use up the retries; a server that sends nothing gives up after them."""
    monkeypatch.setattr(prereqs, "time", types.SimpleNamespace(sleep=lambda _s: None))
    data = os.urandom(4 << 20)
    server.files["/big.bin"] = data
    server.drops["/big.bin"] = [512 << 10] * 7  # more drops than retries (4), each one 512 KB further
    dest = str(tmp_path / "big.bin")
    prereqs.download(server.base + "big.bin", dest, sha256=hashlib.sha256(data).hexdigest())
    assert open(dest, "rb").read() == data
    ranges = [r for p, r in server.hits if p == "/big.bin"]
    assert len(ranges) == 8 and ranges[0] is None and ranges[1] == f"bytes={512 << 10}-"
    server.files["/empty.bin"] = data
    server.drops["/empty.bin"] = [0] * 10  # headers, then nothing: no progress at all
    with pytest.raises(prereqs.SetupError, match="이어 받습니다"):
        prereqs.download(server.base + "empty.bin", str(tmp_path / "empty.bin"), retries=2)
    assert len([p for p, _ in server.hits if p == "/empty.bin"]) == 3


def test_gmt_install_is_all_or_nothing(pc, server, monkeypatch):
    """Files go into gmt.partial (kept across tries); the gmt folder appears only when all are there,
    and a retry fetches only what is missing."""
    fake = {"LICENSE": b"Apache", "assets/pretrained_checkpoints/pretrained.pt": b"policy",
            "assets/robots/g1/g1.xml": b"<mujoco/>"}
    table = {rel: (_blob(data), len(data)) for rel, data in fake.items()}
    monkeypatch.setattr(prereqs, "GMT_FILES", {k: v for k, v in table.items() if not k.endswith("g1.xml")})
    monkeypatch.setattr(prereqs, "GMT_MODEL_FILES", {k: v for k, v in table.items() if k.endswith("g1.xml")})
    for rel in ("LICENSE", "assets/pretrained_checkpoints/pretrained.pt"):
        server.files["/" + rel] = fake[rel]  # the model is missing on the server for now
    dest = os.path.join(paths.user_dir(), settings.GMT_INSTALL)
    with pytest.raises(prereqs.SetupError, match="404"):
        prereqs.install_gmt(base=server.base)
    assert not os.path.exists(dest) and settings.load(reload=True).gmt_dir == ""
    assert os.path.isfile(os.path.join(dest + ".partial", "LICENSE"))
    server.files["/assets/robots/g1/g1.xml"] = fake["assets/robots/g1/g1.xml"]
    server.hits.clear()
    assert prereqs.install_gmt(base=server.base).state == "ready"
    assert [p for p, _ in server.hits] == ["/assets/robots/g1/g1.xml"]  # the two verified files were kept
    assert os.path.isfile(os.path.join(dest, settings.GMT_MODEL)) and not os.path.exists(dest + ".partial")


def test_writable_is_tried_for_real(tmp_path, monkeypatch):
    """os.access says yes to every folder on Windows: writable() makes and removes a test entry."""
    there = tmp_path / "here"
    there.mkdir()
    assert prereqs.writable(str(there)) and prereqs.writable(str(tmp_path / "new" / "deeper"))
    assert os.listdir(there) == [] and not os.path.exists(tmp_path / "new")  # nothing left, nothing made

    def denied(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(settings, "open", denied, raising=False)  # a file in an existing folder refused
    assert not prereqs.writable(str(there)) and prereqs.writable(str(tmp_path / "new"))
    assert not settings._writable(str(there))  # the settings window's check (동영상 저장 폴더) is the same test
    monkeypatch.setattr(settings.os, "mkdir", denied)  # a new folder refused
    try:
        assert not prereqs.writable(str(tmp_path / "new"))
    finally:
        monkeypatch.undo()


def test_download_never_loops_or_wipes(tmp_path, server, monkeypatch):
    """A server that ignores Range and drops at the same place gives up after the retries (restarting
    from zero is not progress); an HTML page answering a resume leaves the .part alone; a cancel ends
    the back-off at once; a leftover .part goes once the file is complete."""
    monkeypatch.setattr(prereqs, "time", types.SimpleNamespace(sleep=lambda _s: None))
    data = os.urandom(2 << 20)
    server.files["/plain.bin"] = data
    server.plain.add("/plain.bin")
    server.drops["/plain.bin"] = [256 << 10] * 50
    with pytest.raises(prereqs.SetupError):
        prereqs.download(server.base + "plain.bin", str(tmp_path / "plain.bin"), retries=3)
    assert len([p for p, _ in server.hits if p == "/plain.bin"]) == 4  # 1 with progress + 3 that got no further

    server.files["/portal.bin"] = data
    server.pages["/portal.bin"] = b"<html>sign in to the hotel wifi</html>"
    dest = str(tmp_path / "portal.bin")
    with open(dest + ".part", "wb") as f:
        f.write(data[: 1 << 20])
    with pytest.raises(prereqs.SetupError):
        prereqs.download(server.base + "portal.bin", dest, retries=1)
    assert open(dest + ".part", "rb").read() == data[: 1 << 20]  # the received MB survived the page
    server.pages.clear()
    prereqs.download(server.base + "portal.bin", dest, sha256=hashlib.sha256(data).hexdigest())
    assert open(dest, "rb").read() == data and not os.path.exists(dest + ".part")

    with open(dest + ".part", "wb") as f:  # a cut-off earlier try next to the complete file
        f.write(b"x")
    prereqs.download(server.base + "portal.bin", dest, sha256=hashlib.sha256(data).hexdigest())
    assert not os.path.exists(dest + ".part")

    stop = threading.Event()
    monkeypatch.setattr(prereqs, "time", types.SimpleNamespace(sleep=lambda _s: pytest.fail("cancel must wait")))
    threading.Timer(0.3, stop.set).start()
    t0 = __import__("time").time()
    with pytest.raises(prereqs.Cancelled):
        prereqs.download("http://127.0.0.1:9/nothing", str(tmp_path / "n.bin"), cancel=stop)  # refused at once
    assert __import__("time").time() - t0 < 3  # not 2+4+8+15 s of back-off


def test_place_keeps_the_old_folder_whole(tmp_path, monkeypatch):
    """Replacing the assistant's own folder: if the old one cannot be moved (a file in use) or the new
    one cannot be put in place, the old one stays complete; GMT's downloads stay for the next try."""
    dest, tmp = tmp_path / "gmt", tmp_path / "gmt.partial"
    for name in ("a.txt", "b.txt", "c.txt"):
        _touch(dest / name, "old")
    _touch(tmp / "new.txt", "new")
    real = os.replace

    def locked(src, dst):
        if str(src) == str(dest):
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(prereqs.os, "replace", locked)
    with pytest.raises(prereqs.SetupError, match="옮기지 못했습니다"):
        prereqs._place(str(tmp), str(dest), replace=True, keep_tmp=True)
    assert sorted(os.listdir(dest)) == ["a.txt", "b.txt", "c.txt"] and os.path.isfile(tmp / "new.txt")

    def stuck(src, dst):
        if str(src) == str(tmp):
            raise PermissionError("antivirus")
        return real(src, dst)

    monkeypatch.setattr(prereqs.os, "replace", stuck)
    with pytest.raises(prereqs.SetupError):
        prereqs._place(str(tmp), str(dest), replace=True)
    assert sorted(os.listdir(dest)) == ["a.txt", "b.txt", "c.txt"] and not os.path.exists(tmp)  # put back
    monkeypatch.setattr(prereqs.os, "replace", real)
    _touch(tmp / "new.txt", "new")
    prereqs._place(str(tmp), str(dest), replace=True)
    assert os.listdir(dest) == ["new.txt"] and not os.path.exists(str(dest) + ".old")


def test_gmt_reinstall_keeps_the_model(pc, server, monkeypatch):
    """Reinstalling over the assistant's own gmt folder (here: its policy went bad) fetches the whole
    set again, G1 model included, since the new folder replaces the old one."""
    fake = {"LICENSE": b"Apache", "assets/pretrained_checkpoints/pretrained.pt": b"policy",
            "assets/robots/g1/g1.xml": b"<mujoco/>"}
    table = {rel: (_blob(data), len(data)) for rel, data in fake.items()}
    monkeypatch.setattr(prereqs, "GMT_FILES", {k: v for k, v in table.items() if not k.endswith("g1.xml")})
    monkeypatch.setattr(prereqs, "GMT_MODEL_FILES", {k: v for k, v in table.items() if k.endswith("g1.xml")})
    for rel, data in fake.items():
        server.files["/" + rel] = data
    assert prereqs.install("gmt", accept=True, source=server.base).state == "ready"
    dest = os.path.join(paths.user_dir(), settings.GMT_INSTALL)
    with open(os.path.join(dest, settings.GMT_POLICY), "wb") as f:
        f.write(b"broken")
    assert prereqs.probe("gmt", online=False).action == "install"
    assert prereqs.install("gmt", accept=True, source=server.base).state == "ready"
    assert open(os.path.join(dest, settings.GMT_MODEL), "rb").read() == b"<mujoco/>"


def test_isaac_probe_edge_cases(pc, server, monkeypatch):
    """A Python that cannot import isaacsim is no Isaac Sim (even from the settings); a valid
    KHUMANOID_ISAAC_PYTHON is offered when the setting is stale; an empty C:\\isaacsim is free;
    a complete zip in Downloads needs only the unpacked size, a broken one counts as none."""
    monkeypatch.setattr(prereqs, "nvidia_gpus", lambda: RTX)
    venv = _touch(pc / "venv" / "python.exe")
    monkeypatch.setattr(prereqs, "_run", lambda cmd, timeout=20.0: "<absent>\n" if cmd[0] == venv else None)
    settings.save(settings.Settings(isaac_python=venv))
    st = prereqs.probe("isaac", online=False)
    assert st.state == "incompatible" and "isaacsim" in st.detail and st.action != "none"
    good = _touch(pc / "isaacsim" / settings.ISAAC_LAUNCHER)
    _touch(pc / "isaacsim" / "VERSION", "6.1.0+release.1\n")
    assert prereqs.probe("isaac", online=False).target == good  # configure to the real one

    elsewhere = _touch(pc / "D" / "isaac" / settings.ISAAC_LAUNCHER)
    _touch(pc / "D" / "isaac" / "VERSION", "6.1.0+release.1\n")
    monkeypatch.setenv(settings.ISAAC_ENV, str(pc / "D" / "isaac"))
    settings.save(settings.Settings(isaac_python=str(pc / "moved")))
    st = prereqs.probe("isaac", online=False)
    assert st.action == "configure" and st.target == elsewhere  # the variable the user set comes first
    monkeypatch.delenv(settings.ISAAC_ENV)

    import shutil

    shutil.rmtree(pc / "isaacsim")
    os.makedirs(pc / "isaacsim")  # emptied, as the blocked note says
    settings.save(settings.Settings())
    assert prereqs.isaac_target() == str(pc / "isaacsim")

    dl = pc / "dl"
    monkeypatch.setattr(prereqs, "free_gb", lambda _p: 30.0)  # room to unpack (25), not to fetch too (35.5)
    assert prereqs.probe("isaac", online=False, download_dir=str(dl)).action == "blocked"
    zip_path = dl / prereqs.ISAAC_ZIP
    _touch(zip_path, "a download cut off: no zip directory at the end")
    assert prereqs.probe("isaac", online=False, download_dir=str(dl)).action == "blocked"
    zip_path.write_bytes(_zip({"python.bat": b"", "VERSION": b"6.1.0\n"}))
    st = prereqs.probe("isaac", online=False, download_dir=str(dl))
    assert st.action == "install" and "다시 받아야" in st.note  # a warning: only if its MD5 is wrong


def test_install_refuses_when_the_pc_changed(pc):
    """The action the user clicked must still be the right one: a copy that vanished since the check
    turns 'configure' into an install, which then needs the consent box (and a new check)."""
    assert prereqs.probe("blender", online=False).action == "install"
    with pytest.raises(prereqs.SetupError, match="바뀌었습니다"):
        prereqs.install("blender", expect="configure")


def test_smpl_import_into_a_folder_named_smplx(pc, monkeypatch):
    models = pc / "mine" / "models"
    monkeypatch.setenv("SMPL_MODEL_DIR", str(models / "smplx"))  # the smplx folder itself
    good = pc / "smplx.zip"
    good.write_bytes(_zip({"models/smplx/SMPLX_NEUTRAL.npz": b"n"}))
    st = prereqs.install("smpl", source=str(good))
    assert st.state == "ready" and os.path.isfile(models / "smplx" / "SMPLX_NEUTRAL.npz")
    assert not os.path.exists(models / "smplx" / "smplx")


def test_blender_on_path_beats_another_version(pc, monkeypatch):
    """No setting: a Blender whose path names no version (a PATH shim, Steam) is tried before one
    whose path says it is another version (Program Files\\Blender Foundation\\Blender 5.1)."""
    pf = _touch(pc / "pf" / "Blender Foundation" / "Blender 5.1" / "blender.exe")
    shim = _touch(pc / "steam" / "common" / "Blender" / "blender.exe")
    monkeypatch.setattr(settings, "blender_candidates", lambda: [(pf, "자동 (Program Files)"), (shim, "자동 (PATH)")])
    assert settings.find_blender().path == shim
