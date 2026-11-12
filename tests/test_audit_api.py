"""The local HTTP API's parameters, motion ids, /api/open and saving where a file cannot be made
(retlens/app/api_server.py, api_core.py, session.py, motion_labels.py)."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens import motion_labels  # noqa: E402
from retlens.app import api_core, session  # noqa: E402
from retlens.app.api_server import ApiBackend, ApiError, _flag, _int, _num, _path_list, _without_props  # noqa: E402
from retlens.app.scene import DEFAULT_URDF  # noqa: E402

SAMPLES = os.path.join(ROOT, "data", "samples")
NPZ = os.path.join(SAMPLES, "synthetic_g1_walk.npz")
CSV = os.path.join(SAMPLES, "synthetic_g1_walk_unitree.csv")
needs_samples = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(NPZ) and os.path.isfile(CSV)),
                                   reason="needs the G1 assets and data/samples (tools/make_samples.py)")


def _api(scene=None, window=None):
    api = ApiBackend.__new__(ApiBackend)  # the endpoints without the routes' scene
    api.scene, api.window, api.on_gui = scene, window, lambda fn: fn()
    return api


def _code(fn, *a):
    with pytest.raises(ApiError) as e:
        fn(*a)
    return e.value.code


# ---------------------------------------------------------------- parameters
def test_flags_numbers_and_paths_are_read_strictly():
    assert [_flag({"x": v}, "x") for v in (True, False, 1, 0, "false", "TRUE", "off", "yes")] == \
        [True, False, True, False, False, True, False, True]
    assert _flag({}, "x", "d") == "d" and _flag({"x": None}, "x", True) is True  # left out / null: the default
    for bad in ("yes please", 2, [True], {}):
        assert _code(_flag, {"x": bad}, "x") == 400
    assert _num({"x": "1.5"}, "x") == 1.5 and _num({}, "x", 3.0) == 3.0
    for bad in ("abc", float("nan"), float("inf"), True, [1]):
        assert _code(_num, {"x": bad}, "x") == 400
    with pytest.raises(ApiError, match="'tol_cm' must be 0.5 to 50, not -5"):
        _num({"tol_cm": -5}, "tol_cm", 3.0, *session.TOL_CM)
    assert _int({"n": "7"}, "n") == 7 and _int({"n": 2.0}, "n") == 2
    for bad in ("abc", 1.5, True, -1):
        assert _code(_int, {"n": bad}, "n", None, 0) == 400
    assert _path_list("D:\\mocap", "folders") == ["D:\\mocap"]  # one path, not its letters
    assert _path_list(["a", "b"], "paths") == ["a", "b"]
    for bad in ("", [], [""], [1], 5, {"a": 1}):
        assert _code(_path_list, bad, "paths") == 400


class _Scene:
    """What the endpoints below touch of a MotionScene, recording what they change."""

    def __init__(self):
        self.items, self.t, self.playing, self.view = [], 0.0, False, SimpleNamespace(speed=1.0, loop=True)
        self.balance, self.assist, self.physics_on, self.runs, self.calls = "isaac", 1.0, True, [], []
        self.compare = SimpleNamespace(tol_cm=3.0)

    def set_visible(self, it, v):
        self.calls.append(("visible", v))

    def set_offset(self, it, v):
        self.calls.append(("offset", v))

    def set_show_human(self, it, v):
        self.calls.append(("show_human", v))

    def seek(self, t):
        self.calls.append(("seek", t))

    def set_playing(self, on):
        self.calls.append(("play", on))

    def time_range(self):
        return 0.0, 8.0

    def set_compare(self, **kw):
        self.calls.append(("compare", kw))

    def step_segment(self, direction):
        return None

    # physics: a run is asked of the mode on at each change, once per mode (MotionScene._physics_changed)
    def _changed(self):
        key = self.assist if self.balance == "isaac" else self.balance
        if self.physics_on and key not in self.runs:
            self.runs.append(key)

    def set_assist(self, a):
        self.assist = a
        self._changed()

    def set_balance(self, m):
        self.balance = m
        self._changed()

    def set_physics(self, on, why=""):
        self.physics_on = on
        self._changed()

    def balance_problem(self, m):
        return ""

    def mode_label(self):
        return self.balance

    def job_text(self, it):
        return ""


def _items(*sources):
    return [SimpleNamespace(label=f"samples/{os.path.splitext(os.path.basename(s))[0]}" + (f" ({k + 1})" if k else ""),
                            source=s, offset=0.0) for k, s in enumerate(sources)]


def test_item_and_playback_values(monkeypatch):
    sc = _Scene()
    sc.items = _items(NPZ)
    api = _api(sc)
    monkeypatch.setattr(api_core, "item_info", lambda scene, it, metrics=True: {"id": it.label})
    api.item({"id": 0, "visible": "false", "show_human": 0})  # a query string's "false" hides it
    assert sc.calls == [("visible", False), ("show_human", False)]
    sc.calls.clear()
    for bad in ({"offset_s": float("nan")}, {"offset_s": "abc"}, {"offset_s": 1e9}, {"visible": "maybe"}):
        assert _code(api.item, {"id": 0, "visible": True, **bad}) == 400
    assert sc.calls == []  # nothing applied when one value is wrong
    for bad in ({"speed": -4}, {"speed": 0}, {"speed": "x"}, {"time_s": float("nan")}, {"time_s": "x"},
                {"problem": "x"}, {"problem": 0}, {"play": "x"}):
        assert _code(api.playback, {"time_s": 1.0, **bad}) == 400
    assert sc.calls == [] and sc.view.speed == 1.0
    out = api.playback({"speed": "0.5", "loop": "false", "time_s": "2", "play": "true"})
    assert out["speed"] == 0.5 and sc.view.loop is False and sc.calls == [("seek", 2.0), ("play", True)]


def test_compare_physics_library_and_segments_answer_400(monkeypatch):
    sc = _Scene()
    sc.items = _items(NPZ, CSV)
    api = _api(sc)
    for bad in ({"tol_cm": -5}, {"tol_cm": "abc"}, {"tol_cm": 0.1}, {"heading": "x"}):
        assert _code(api.compare, {"a": 0, "b": 1, **bad}) == 400
    assert api.compare({"on": "false"}) == {"compare": "off"}
    for bad in ({"balance": ["x"]}, {"balance": "nope"}, {"assist": "abc"}, {"assist": -1}, {"on": "x"}):
        assert _code(api.physics, {"on": False, **bad}) == 400
    assert _code(api.segments, {"step": "x"}) == 400
    route = ApiBackend(sc).routes[("GET", "/api/library")]
    assert _code(route, {"limit": "abc"}) == 400


def test_physics_starts_only_the_mode_asked_for():
    """Isaac on, then {"on", "balance": "harness", "assist"}: no Isaac run at the new scale on the way."""
    sc = _Scene()
    api = _api(sc)
    out = api.physics({"on": True, "balance": "harness", "assist": 0.5})
    assert sc.runs == ["harness"] and out["assist"] == 0.5 and out["balance"] == "harness"
    sc.runs.clear()
    api.physics({"on": False, "balance": "pd"})  # off with another mode: nothing starts
    assert sc.runs == [] and sc.balance == "pd" and not sc.physics_on
    sc.balance = "isaac"
    api._eula = lambda: None
    api.physics({"on": "true", "assist": "0"})  # Isaac at another scale: that one run
    assert sc.runs == [0.0]


# ---------------------------------------------------------------- motion ids
def test_a_path_names_its_own_motion():
    a, b, c = (os.path.join(SAMPLES, n) for n in ("synthetic_g1_walk.npz", "synthetic_walk.bvh",
                                                   "synthetic_g1_walk_unitree.csv"))
    sc = SimpleNamespace(items=_items(a, b, c))
    find = api_core.find_item
    assert find(sc, c) is sc.items[2] and find(sc, b) is sc.items[1]
    assert find(sc, c.replace("\\", "/")) is sc.items[2]  # any slashes
    assert find(sc, c.upper() if os.name == "nt" else c) is sc.items[2]  # Windows paths have no case
    assert find(sc, "synthetic_walk.bvh") is sc.items[1] and find(sc, "2") is sc.items[2]
    assert find(sc, sc.items[1].label) is sc.items[1]
    for other in (os.path.abspath(os.path.join(os.sep, "nowhere", "other.bvh")), os.path.abspath("x.bvh")):
        with pytest.raises(KeyError):
            find(sc, other)  # an absolute path of no open motion: none, never the first
    api = _api(sc)
    with pytest.raises(ApiError) as e:
        api._item("bogus")
    assert e.value.code == 404 and str(e.value).startswith("no motion 'bogus'")  # not in quotes
    sc.items = _items(a, a)  # the same file twice: which one?
    with pytest.raises(api_core.AmbiguousItem):
        find(sc, "synthetic_g1_walk.npz")
    assert _code(api._item, a) == 409
    assert find(sc, sc.items[1].label) is sc.items[1] and find(sc, 1) is sc.items[1]


# ---------------------------------------------------------------- /api/open
def test_open_checks_every_file_first_and_reports_failures(tmp_path, monkeypatch):
    sc = _Scene()
    added = []

    def add(f):
        if "broken" in f:
            raise ValueError(f"unsupported file type: {f}")
        if "tool" in f:
            raise RuntimeError("Blender not found")
        added.append(f)
        return SimpleNamespace(label=os.path.basename(f))

    sc.add = add
    monkeypatch.setattr(api_core, "item_info", lambda scene, it, metrics=True: {"id": it.label})
    api = _api(sc)
    good, broken, tool = (tmp_path / n for n in ("good.bvh", "broken.bvh", "tool.fbx"))
    for p in (good, broken, tool):
        p.write_text("x")
    sess = tmp_path / "w.retlens"
    sess.write_text("{}")
    lab = tmp_path / "good.labels.csv"
    lab.write_text("label,start_s,end_s\nwalk,0,1\n")
    with pytest.raises(ApiError) as e:
        api.open({"paths": str(tmp_path / "x.bvh")})  # one string: one path
    assert e.value.code == 404 and str(tmp_path / "x.bvh") in str(e.value)
    assert _code(api.open, {"paths": [str(good), str(good) + ".nope"]}) == 404
    assert _code(api.open, {"paths": [str(good), str(sess)]}) == 422
    with pytest.raises(ApiError, match="/api/labels"):
        api.open({"paths": [str(good), str(lab)]})
    assert _code(api.open, {"paths": [str(good), 5]}) == 400
    assert added == []  # none of those opened anything
    out = api.open({"paths": [str(good), str(broken)]})
    assert [m["id"] for m in out["opened"]] == ["good.bvh"] and out["failed"][0]["path"] == str(broken)
    assert "unsupported file type" in out["failed"][0]["error"]
    assert _code(api.open, {"path": str(broken)}) == 422
    assert _code(api.open, {"paths": [str(tool)]}) == 500


# ---------------------------------------------------------------- /api/batch
def test_batch_takes_one_folder_as_one(tmp_path):
    got = {}
    panel = SimpleNamespace(folders=[], _running=False, model=SimpleNamespace(rows=[]), _request_stop=lambda: None,
                            add_folders=lambda fs: got.setdefault("folders", list(fs)),
                            physics=SimpleNamespace(setChecked=lambda v: got.setdefault("physics", v)),
                            auto=SimpleNamespace(setChecked=lambda v: got.setdefault("auto", v)),
                            run=lambda: got.setdefault("ran", True))
    dock = SimpleNamespace(show=lambda: None, raise_=lambda: None)
    api = _api(_Scene(), SimpleNamespace(dataset=panel, docks={"dataset": dock}))
    assert _code(api.batch, {"folders": "zq"}) == 404  # not "z" and "q"
    assert _code(api.batch, {"folders": [str(tmp_path), str(tmp_path / "gone")]}) == 404
    assert _code(api.batch, {"folders": 5}) == 400
    assert _code(api.batch, {"folders": [str(tmp_path)], "physics": "x"}) == 400
    assert got == {}  # nothing started
    api.batch({"folders": str(tmp_path), "physics": "false", "auto_labels": 1})
    assert got == {"folders": [str(tmp_path)], "physics": False, "auto": True, "ran": True}


# ---------------------------------------------------------------- saving
def _refusing(monkeypatch, folder):
    """os.open as in a folder that refuses new files (C:\\): PermissionError, while os.access calls it writable.
    tempfile.mkstemp tried another name after each, about 2**31 times; after 50 this raises something else, so
    a return of that loop fails the test instead of hanging it."""
    real, calls = os.open, []

    def fake(path, *a, **kw):
        if os.path.dirname(os.path.abspath(path)) != str(folder):
            return real(path, *a, **kw)
        calls.append(path)
        if len(calls) > 50:
            raise RuntimeError("tried again and again")
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "open", fake)
    return calls


def test_saving_where_no_file_can_be_made_raises(tmp_path, monkeypatch):
    assert os.access(tmp_path, os.W_OK)
    calls = _refusing(monkeypatch, tmp_path)
    with pytest.raises(PermissionError):
        session.write(str(tmp_path / "s.retlens"), {"motions": []})
    lab = motion_labels.MotionLabels(path="", segments=[motion_labels.Segment("walk", 0.0, 1.0)])
    with pytest.raises(PermissionError):
        motion_labels.save_csv(lab, str(tmp_path / "x.labels.csv"))
    monkeypatch.undo()
    assert len(calls) == 2 and os.listdir(tmp_path) == []


def test_a_label_added_at_no_time_is_refused():
    """A NaN time (the API's JSON takes it) is under no segment: it added one over the whole track, on the others."""
    lab = motion_labels.MotionLabels(path="", segments=[motion_labels.Segment("walk", 0.0, 1.0),
                                                        motion_labels.Segment("run", 1.0, 2.0)])
    for t in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            motion_labels.added(lab, "", t, 30.0, 2.0, "x")


def test_a_taken_temporary_name_is_tried_again(tmp_path, monkeypatch):
    real, calls = os.open, []

    def fake(path, *a, **kw):
        calls.append(path)
        if len(calls) == 1:
            raise FileExistsError(17, "File exists", path)
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "open", fake)
    lab = motion_labels.MotionLabels(path="", segments=[motion_labels.Segment("walk", 0.0, 1.0)])
    path = motion_labels.save_csv(lab, str(tmp_path / "x.labels.csv"))
    monkeypatch.undo()
    assert len(calls) == 2 and os.listdir(tmp_path) == ["x.labels.csv"]
    assert [s.label for s in motion_labels.load(path, "x.bvh", 30.0).segments] == ["walk"]


def test_session_save_errors_are_answered(tmp_path, monkeypatch):
    """Headless: the write's error is a 500 that says it. In the window: save_session without its message box
    (interactive=False), its error text in the answer; a session being opened: 409."""
    def refuse(path, data):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(session, "write", refuse)
    monkeypatch.setattr(session, "capture", lambda scene, base: {})
    target = str(tmp_path / "s.retlens")
    with pytest.raises(ApiError) as e:
        _api(_Scene()).session({"save": target})
    assert e.value.code == 500 and "Permission denied" in str(e.value)
    asked = []

    def save_session(path, interactive=True):  # as EditorWindow.save_session: its reason in _last_save_error
        asked.append(interactive)
        if w._restore is not None:
            w._last_save_error = "작업 세션을 여는 중에는 저장할 수 없습니다"
            return False
        w._last_save_error = "PermissionError: denied"
        return False

    w = SimpleNamespace(session_path=None, _restore=None, _last_save_error="old", save_session=save_session)
    api = _api(_Scene(), w)
    with pytest.raises(ApiError) as e:
        api.session({"save": target})
    assert e.value.code == 500 and "PermissionError: denied" in str(e.value) and asked == [False]
    w._restore = object()  # a session being opened: 409, not a 500 "could not write"
    assert _code(api.session, {"save": target}) == 409


def test_session_save_matches_the_window(tmp_path, monkeypatch):
    """The window's own save_session, as the API calls it: no message box, its reason in _last_save_error."""
    qt = pytest.importorskip("PySide6.QtCore")
    if qt.QCoreApplication.instance() is not None and "PySide6.QtWebEngineWidgets" not in sys.modules:
        pytest.skip("Qt WebEngine (the editor's) cannot load after another test's QApplication")
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from retlens.app import editor

    def refuse(path, data):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(editor.QMessageBox, "warning", lambda *a, **kw: pytest.fail("a message box"))
    monkeypatch.setattr(session, "write", refuse)
    shown = []
    w = SimpleNamespace(_restore=None, session_path=None, _last_save_error="", status=lambda *a: shown.append(a[0]),
                        capture_session=lambda base: {}, _session_base=lambda path: str(tmp_path))
    w.save_session = lambda path=None, interactive=True: editor.EditorWindow.save_session(w, path, interactive)
    api = _api(_Scene(), w)
    target = str(tmp_path / "s.retlens")
    with pytest.raises(ApiError) as e:
        api.session({"save": target})
    assert e.value.code == 500 and "PermissionError" in str(e.value) and shown
    w._restore = object()
    assert _code(api.session, {"save": target}) == 409


# ---------------------------------------------------------------- the command line
def test_a_scene_that_cannot_be_built_stops_its_server(tmp_path, monkeypatch):
    """headless_scene stops its viser server when the robot cannot load: left running, viser's exit message
    printed on stdout after the command line's JSON."""
    import viser

    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    stopped = []

    class Server:
        def __init__(self, *a, **kw):
            pass

        def stop(self):
            stopped.append(True)

    def broken(*a, **kw):
        raise RuntimeError("no robot model file")

    monkeypatch.setattr(viser, "ViserServer", Server)
    monkeypatch.setattr(api_core, "load_robot_drawing", broken)
    with pytest.raises(RuntimeError):
        api_core.headless_scene()
    assert stopped == [True]


def test_cli_prints_only_json_when_the_robot_is_missing(tmp_path):
    from retlens.synthetic import walking_bvh_text

    (tmp_path / "a.bvh").write_text(walking_bvh_text(1.0), encoding="utf-8")  # the motion is there: the robot is not
    env = dict(os.environ, RETLENS_USER_DIR=str(tmp_path / "user"))
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "retlens_cli.py"), "inspect",
                          str(tmp_path / "a.bvh"), "--robot", str(tmp_path / "missing.xml")],
                         env=env, capture_output=True, timeout=300, cwd=ROOT)
    lines = out.stdout.decode("utf-8").strip().splitlines()
    assert out.returncode == 1 and len(lines) == 1 and "error" in json.loads(lines[0]), lines


# ---------------------------------------------------------------- over HTTP, on a headless scene
def _call(url, token, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 method="POST" if body is not None else "GET")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@needs_samples
def test_http_ids_open_and_compare(tmp_path, monkeypatch):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    from urllib.parse import quote

    from retlens.app.api_server import ApiServer

    scene = api_core.headless_scene(mesh_cell=0.02)
    srv = ApiServer(ApiBackend(scene), port=0, write_discovery=False).start()
    u, t = srv.url, srv.token
    try:
        code, out = _call(f"{u}/api/open", t, {"paths": [NPZ, CSV, CSV + ".nope"]})
        assert code == 404 and _call(f"{u}/api/status", t)[1]["motions"] == []  # nothing opened
        code, out = _call(f"{u}/api/open", t, {"paths": [NPZ, CSV]})
        assert code == 200 and len(out["opened"]) == 2 and out["failed"] == []
        a, b = (m["id"] for m in out["opened"])
        assert _call(f"{u}/api/motion?id={quote(CSV)}", t)[1]["id"] == b
        assert _call(f"{u}/api/motion?id={quote(CSV.replace(os.sep, '/'))}", t)[1]["id"] == b
        code, out = _call(f"{u}/api/motion?id={quote(os.path.join(os.path.dirname(CSV), 'other.bvh'))}", t)
        assert code == 404 and out["error"].startswith("no motion ")
        code, out = _call(f"{u}/api/compare", t, {"a": a, "b": b, "tol_cm": 2})
        assert code == 200 and out["tol_cm"] == 2.0 and out["offsets_s"] == {"a": 0.0, "b": 0.0}
        assert _call(f"{u}/api/compare", t, {"a": a, "b": b, "tol_cm": -5})[0] == 400
        assert _call(f"{u}/api/status", t)[1]["compare"]["tol_cm"] == 2.0  # the one that was used
        code, out = _call(f"{u}/api/item?visible=false", t, {"id": b})  # a query string's text
        assert code == 200 and out["visible"] is False
        assert _call(f"{u}/api/item", t, {"id": b, "offset_s": "abc"})[0] == 400
        code, out = _call(f"{u}/api/remove", t, {"id": CSV})  # by its path: that one, not the first
        assert code == 200 and out["removed"] == b
        assert [m["id"] for m in _call(f"{u}/api/status", t)[1]["motions"]] == [a]
        _call(f"{u}/api/open", t, {"paths": NPZ})
        assert _call(f"{u}/api/motion?id=synthetic_g1_walk.npz", t)[0] == 409  # the same file twice
    finally:
        srv.stop()
        scene.runner.shutdown()
        scene.server.stop()


# ---------------------------------------------------------------- second review
def test_retarget_is_refused_whole():
    """A swing out of range, NaN, text or true: a 400 naming it, and no correction switched on meanwhile (foot_flat
    was set before the swing was checked)."""
    sc = _Scene()
    sc.items = _items(NPZ)
    sc.items[0].metrics = {}
    sc.set_retarget = lambda **kw: sc.calls.append(("set", kw)) or kw
    sc.retarget_again = lambda it, **kw: sc.calls.append(("again", kw)) or SimpleNamespace(
        label=it.label, retarget=kw, metrics={})
    api = _api(sc)
    for bad in (50, -1, float("nan"), "abc", True, ["1", "2"]):
        for q in ({}, {"id": 0}):
            with pytest.raises(ApiError, match="'swing_clearance_cm'") as e:
                api.retarget({**q, "foot_flat": True, "self_collision": True, "swing_clearance_cm": bad})
            assert e.value.code == 400
    assert _code(api.retarget, {"foot_flat": "maybe", "swing_clearance_cm": 2}) == 400
    assert sc.calls == []
    api.retarget({"foot_flat": "true", "swing_clearance_cm": "2.5", "self_collision": 0})
    api.retarget({"id": 0, "swing_clearance_cm": "0"})
    assert sc.calls == [("set", {"foot_flat": True, "swing_clearance_cm": 2.5, "self_collision": False}),
                        ("again", {"foot_flat": None, "swing_clearance_cm": 0.0, "self_collision": None})]


def test_a_repeated_query_parameter_is_a_list(tmp_path, monkeypatch):
    """?paths=a&paths=b (how clients put a list in a query string) opens both, not b alone; a repeated flag or text
    is a 400."""
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    from urllib.parse import urlencode

    from retlens.app.api_server import ApiServer

    sc = _Scene()
    sc.add = lambda f: sc.items.append(SimpleNamespace(label=os.path.basename(f), source=f, offset=0.0)) or sc.items[-1]
    monkeypatch.setattr(api_core, "item_info", lambda scene, it, metrics=True: {"id": it.label})
    a, b = str(tmp_path / "a.bvh"), str(tmp_path / "b.bvh")
    for p in (a, b):
        with open(p, "w") as f:
            f.write("x")
    srv = ApiServer(ApiBackend(sc), port=0, write_discovery=False).start()
    u, t = srv.url, srv.token
    try:
        code, out = _call(f"{u}/api/open?{urlencode([('paths', a), ('paths', b)])}", t, {})
        assert code == 200 and [m["id"] for m in out["opened"]] == ["a.bvh", "b.bvh"]
        code, out = _call(f"{u}/api/open?{urlencode([('paths', a)])}", t, {})  # given once: one path
        assert code == 200 and [it.source for it in sc.items] == [a, b, a]
        assert _call(f"{u}/api/item?visible=true&visible=false", t, {"id": 0})[0] == 400
        assert _call(f"{u}/api/library?query=a&query=b", t)[0] == 400
        assert _call(f"{u}/api/motion?id=0&id=1", t)[0] == 404
    finally:
        srv.stop()


def test_labels_auto_and_save_take_flag_text(tmp_path, monkeypatch):
    """"auto" and "save" take true as every true / false parameter does (/api/help): 1 and their text."""
    lab = motion_labels.MotionLabels(path="", segments=[motion_labels.Segment("walk", 0.0, 1.0)])
    sc = _Scene()
    sc.items = [SimpleNamespace(label="t/walk", source=str(tmp_path / "walk.bvh"), labels=lab, info={}, offset=0.0)]
    sc.labels_dirty = lambda it: False
    sc.auto_label = lambda it, rules: sc.calls.append(("auto", rules))
    sc.reload_labels = lambda it: sc.calls.append(("reload",))
    sc.labels_saved = lambda it, base, path: sc.calls.append(("saved", path))
    monkeypatch.setattr(api_core, "item_info", lambda scene, it, metrics=True: {"labels": None})
    api = _api(sc)
    for v in (True, "true", 1, "1"):
        api.labels({"id": 0, "auto": v})
    assert sc.calls == [("auto", None)] * 4
    sc.calls.clear()
    api.labels({"id": 0, "auto": "false"})  # as false: the motion's label file read again
    assert sc.calls == [("reload",)]
    assert _code(api.labels, {"id": 0, "auto": "maybe"}) == 400
    out = api.labels({"id": 0, "save": "true"})  # <name>.labels.csv next to the motion
    assert out["saved"] == str(tmp_path / "walk.labels.csv") and (tmp_path / "walk.labels.csv").is_file()
    for bad in ("false", 0, "relative.csv"):
        assert _code(api.labels, {"id": 0, "save": bad}) == 400
    asked, sess = [], str(tmp_path / "s.retlens")
    w = SimpleNamespace(session_path=sess, _restore=None, _last_save_error="",
                        save_session=lambda path, interactive=True: asked.append(path) or True)
    for v in ("true", 1):
        assert _api(sc, w).session({"save": v})["saved"] == sess
    assert asked == [sess, sess]
    assert _code(_api(sc).session, {"save": "1"}) == 409  # headless: no session file is open (not a 400)


def test_an_unused_copy_is_not_said_to_be_drawn(tmp_path):
    """Takes_Clean's person draws Prop_Clean's file: Prop_Raw's file of the same name, opened with it, is drawn
    nowhere and says so; with Takes_Raw's person opened too, it is that one's."""
    shoot = tmp_path / "shoot"
    files = {}
    for sub, name in (("Takes_Clean", "pick_010_M1.fbx"), ("Takes_Raw", "pick_010_M2.fbx"),
                      ("Prop_Raw", "pick_010_Prop.fbx"), ("Prop_Clean", "pick_010_Prop.fbx")):
        (shoot / sub).mkdir(parents=True)
        (shoot / sub / name).write_bytes(b"")
        files[sub] = str(shoot / sub / name)
    person, raw, clean = files["Takes_Clean"], files["Prop_Raw"], files["Prop_Clean"]
    opened, left = _without_props([person, raw])
    assert opened == [person] and [s["path"] for s in left] == [raw]
    assert left[0]["why"].startswith("another copy") and "Prop_Clean" in left[0]["why"]
    assert _without_props([person, clean])[1][0]["why"].startswith("drawn with the person's motion")
    opened, left = _without_props([person, files["Takes_Raw"], raw])
    assert opened == [person, files["Takes_Raw"]] and left[0]["why"].startswith("drawn with the person's motion")


@pytest.mark.skipif(os.name != "nt", reason="8.3 short names are Windows'")
def test_a_short_path_names_the_file_of_its_long_path(tmp_path):
    """C:\\Users\\ABCDEF~1\\... (Python's and PowerShell's TEMP) and the long path (the file dialog's) are one file:
    as a motion id, and as the open work session saved again."""
    import ctypes

    buf, folders = ctypes.create_unicode_buffer(1024), []
    for fn in (ctypes.windll.kernel32.GetLongPathNameW, ctypes.windll.kernel32.GetShortPathNameW):
        n = fn(str(tmp_path), buf, 1024)
        folders.append(buf.value if 0 < n < 1024 else "")
    if not folders[1] or folders[1].lower() == folders[0].lower():
        pytest.skip("no 8.3 short folder names here")
    (tmp_path / "walk.bvh").write_text("x")
    (tmp_path / "work.retlens").write_text("{}")
    long_, short = (os.path.join(d, "walk.bvh") for d in folders)
    for opened, asked in ((long_, short), (short, long_)):
        sc = SimpleNamespace(items=_items(opened))
        assert api_core.find_item(sc, asked) is sc.items[0]
    long_, short = (os.path.join(d, "work.retlens") for d in folders)
    asked = []
    w = SimpleNamespace(session_path=long_, _restore=None, _last_save_error="",
                        save_session=lambda path, interactive=True: asked.append(path) or True)
    _api(_Scene(), w).session({"save": short})  # the file open: saved, not "exists: give overwrite"
    assert asked == [short]


def test_a_path_id_is_quoted_as_sent():
    """The id in a 404 / 409 as the caller sent it (its repr doubled a path's backslashes)."""
    api = _api(SimpleNamespace(items=_items(NPZ, NPZ)))
    other = "C:\\nowhere\\other.bvh"
    with pytest.raises(ApiError) as e:
        api._item(other)
    assert e.value.code == 404 and str(e.value).startswith(f"no motion '{other}';")
    with pytest.raises(ApiError) as e:
        api._item(NPZ)
    assert e.value.code == 409 and str(e.value).startswith(f"'{NPZ}' is several open motions")


def test_a_session_saved_before_its_robot_model_changed():
    """Same robot name, another model digest (the model file changed, or an older RetLens): said so, not 'saved
    with another robot (MyBot), opened with MyBot'."""
    ident = {"name": "MyBot", "digest": "new", "key": "my_bot.xml"}
    scene = SimpleNamespace(robot_profile=SimpleNamespace(name="MyBot", builtin=False, key="my_bot", ident=ident),
                            items=[])

    def notes(robot, saved):
        return session.Restore({"robot": robot, "robot_ident": saved, "motions": []}, None, "add").run(scene).notes

    old = notes("MyBot", {**ident, "digest": "old"})
    assert len(old) == 1 and old[0].startswith("MyBot의 모델 파일이 바뀐 뒤") and "다른 로봇" not in old[0]
    assert notes("MyBot", ident) == []
    other = "다른 로봇(OtherBot)으로 저장한 작업 세션입니다. 지금 로봇(MyBot)으로 엽니다"
    assert notes("OtherBot", {"name": "OtherBot", "digest": "x", "key": "other.xml"}) == [other]
    assert notes("OtherBot", None) == [other]  # a session from before identities: by its name


def test_a_c3d_reports_the_objects_its_numbers_are_measured_on(tmp_path):
    """A C3D's hand-object numbers come from its solved skeleton's objects: so do its objects and prop files (its
    human part, the markers, has none)."""
    solved = SimpleNamespace(objects=["Ball_1"], meta={"props": [{"file": "pick_7_Prop.fbx", "objects": 1}]})
    item = SimpleNamespace(label="t/walk", kind="C3D", source=str(tmp_path / "walk.c3d"), offset=0.0, visible=True,
                           color=(1.0, 0.0, 0.0), robot=SimpleNamespace(num_frames=3, fps=30.0, duration=0.1),
                           metrics={"qc": "PASS", "_objects": [{"name": "Ball_1"}]}, info={}, retarget={},
                           labels=None, handles={}, human=SimpleNamespace(objects=[], meta={}), solved_human=solved)
    sc = SimpleNamespace(items=[item], t=0.0, physics_on=False, problems=lambda it: {}, is_sim_result=lambda it: False)
    out = api_core.item_info(sc, item, metrics=False)
    assert out["objects"] == [{"name": "Ball_1"}] and out["prop_files"] == solved.meta["props"]
    item.solved_human = None  # any other motion: its own skeleton's
    out = api_core.item_info(sc, item, metrics=False)
    assert out["objects"] is None and "prop_files" not in out
