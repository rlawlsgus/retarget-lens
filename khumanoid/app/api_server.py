"""The local HTTP API of a running RetLens, for AI agents and scripts.

    GET  /api/help                      every endpoint with its parameters
    GET  /api/status                    time, playback, physics, compare, open motions
    GET  /api/checks                    환경 점검
    GET  /api/library?query=walk        motion files in the motion folders
    POST /api/open      {"paths": [..]}                      load (retarget when needed), shown in the window
    POST /api/retarget  {"foot_flat"?, "swing_clearance_cm"?}   리타게팅 보정 for the human motions opened
                                                             next (open ones keep theirs: reopen to compare)
    POST /api/remove    {"id": ..}
    GET  /api/motion?id=..              one motion: QC, metrics, C3D QC, physics state
    POST /api/item      {"id", "visible"?, "offset_s"?, "show_human"?}
    POST /api/playback  {"play"?, "time_s"?, "speed"?, "loop"?}
    GET  /api/metrics?ref=..            the 분석 table (RMSE against ref)
    POST /api/align     {"ref"}         기준에 시간 자동 정렬
    POST /api/compare   {"a", "b", "heading"?, "tol_cm"?} / {"on": false}   겹쳐 비교 (+ its numbers)
    POST /api/physics   {"on", "assist"?, "balance"?}       물리 모드; balance isaac (needs the EULA accepted in
                                                             the window) | pd | gmt (MuJoCo: no controller / GMT)
    POST /api/video     {"id"}          동영상 저장 (queued; see /api/jobs)
    GET  /api/jobs                      physics (Isaac, MuJoCo) and video jobs
    POST /api/camera    {"fit": true}   카메라 맞추기
    POST /api/screenshot {"path"?}      a PNG of the window (default in the user's logs folder)

Safety: it listens on 127.0.0.1 only; every request needs the token (header
"Authorization: Bearer <token>" or "X-RetLens-Token"); requests a web browser makes (they carry
an Origin header) are refused, so web pages cannot drive it. The URL and token of the running
window are in <user data>\\api.json (discovery()); the token changes at every start.
Responses are JSON: {"ok": true, ...} or {"ok": false, "error": "..."} with an HTTP error code.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .. import paths
from . import api_core
from .scene import BALANCE

DEFAULT_PORT = 8765


def discovery_path() -> str:
    return os.path.join(paths.user_dir(), "api.json")


def discovery() -> dict | None:
    """URL and token of the running RetLens's API (None when it is not running)."""
    try:
        with open(discovery_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if _alive(d.get("pid")) else None  # else a file left by a crashed run


def _alive(pid) -> bool:
    """Whether the process that wrote a discovery file still runs (assumed so off Windows)."""
    if not pid or os.name != "nt":
        return True
    import ctypes

    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


class ApiError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


class ApiBackend:
    """The endpoints, on a MotionScene. on_gui(fn) runs fn on the window's GUI thread and returns
    its result (screenshots); window hooks (EditorWindow) are optional, so the API also runs on a
    headless scene (tests)."""

    def __init__(self, scene, window=None, on_gui: Callable | None = None):
        self.scene, self.window = scene, window
        self.on_gui = on_gui or (lambda fn: fn())
        g, p = "GET", "POST"
        self.routes: dict[tuple[str, str], Callable[[dict], dict]] = {
            (g, "/api/help"): self.help, (g, "/api/status"): lambda q: api_core.status(self.scene),
            (g, "/api/checks"): lambda q: api_core.checks(),
            (g, "/api/library"): lambda q: api_core.library(q.get("query"), int(q.get("limit", 200))),
            (p, "/api/open"): self.open, (p, "/api/retarget"): self.retarget, (p, "/api/remove"): self.remove,
            (g, "/api/motion"): self.motion,
            (p, "/api/item"): self.item, (p, "/api/playback"): self.playback, (g, "/api/metrics"): self.metrics,
            (p, "/api/align"): self.align, (p, "/api/compare"): self.compare, (p, "/api/physics"): self.physics,
            (p, "/api/video"): self.video, (g, "/api/jobs"): self.jobs, (p, "/api/camera"): self.camera,
            (p, "/api/screenshot"): self.screenshot,
        }

    # ---------------------------------------------------------------- helpers
    def _item(self, key):
        if key is None:
            raise ApiError("give the motion's id (label like 'cmu_bvh/02_01', index or file name)")
        try:
            return api_core.find_item(self.scene, key)
        except KeyError as e:
            raise ApiError(str(e), 404) from None

    def help(self, q: dict) -> dict:
        from . import api_server

        return {"doc": api_server.__doc__, "endpoints": sorted(f"{m} {p}" for m, p in self.routes)}

    # ---------------------------------------------------------------- motions
    def open(self, q: dict) -> dict:
        files = q.get("paths") or ([q["path"]] if q.get("path") else [])
        if not files:
            raise ApiError("give 'paths': [file, ...]")
        out = []
        for f in files:
            if not os.path.isfile(f):
                raise ApiError(f"no such file: {f}", 404)
            item = self.scene.add(f)  # retargets when needed (seconds on a cache miss)
            if self.window is not None:
                self.window.bridge.added.emit(item)  # the window selects it, fits the camera
            out.append(api_core.item_info(self.scene, item))
        return {"opened": out}

    def retarget(self, q: dict) -> dict:
        try:
            swing = None if q.get("swing_clearance_cm") is None else float(q["swing_clearance_cm"])
            r = self.scene.set_retarget(foot_flat=None if "foot_flat" not in q else bool(q["foot_flat"]),
                                        swing_clearance_cm=swing)
        except (TypeError, ValueError) as e:
            raise ApiError(str(e)) from None
        return {"retarget": r, "note": "applies to the human motions opened next; open ones keep theirs"}

    def remove(self, q: dict) -> dict:
        item = self._item(q.get("id"))
        self.scene.remove(item)
        return {"removed": item.label}

    def motion(self, q: dict) -> dict:
        return api_core.item_info(self.scene, self._item(q.get("id")))

    def item(self, q: dict) -> dict:
        item = self._item(q.get("id"))
        if "visible" in q:
            self.scene.set_visible(item, bool(q["visible"]))
        if "offset_s" in q:
            self.scene.set_offset(item, float(q["offset_s"]))
        if "show_human" in q:
            self.scene.set_show_human(item, bool(q["show_human"]))
        return api_core.item_info(self.scene, item, metrics=False)

    def playback(self, q: dict) -> dict:
        sc = self.scene
        if "speed" in q:
            sc.view.speed = float(q["speed"])
        if "loop" in q:
            sc.view.loop = bool(q["loop"])
        if "time_s" in q:
            sc.seek(float(q["time_s"]))
        if "play" in q:
            sc.set_playing(bool(q["play"]))
        return {"time_s": sc.t, "playing": sc.playing, "speed": sc.view.speed, "time_range_s": list(sc.time_range())}

    # ---------------------------------------------------------------- analysis
    def metrics(self, q: dict) -> dict:
        ref = self._item(q["ref"]) if q.get("ref") is not None else None
        return api_core.metrics_table(self.scene, ref)

    def align(self, q: dict) -> dict:
        return api_core.align(self.scene, self._item(q.get("ref")))

    def compare(self, q: dict) -> dict:
        if q.get("on") is False:
            self.scene.set_compare(on=False)
            return {"compare": "off"}
        a, b = self._item(q.get("a")), self._item(q.get("b"))
        if a is b:
            raise ApiError("a and b must be different motions")
        out = api_core.compare(self.scene, a, b, heading=bool(q.get("heading", True)), tol_cm=float(q.get("tol_cm", 3.0)))
        if self.window is not None:
            self.on_gui(lambda: self.window.docks["compare"].raise_())
        return out

    # ---------------------------------------------------------------- Isaac
    def _eula(self) -> None:
        ok = self.window._eula if self.window is not None else api_core.eula_accepted()
        if not ok:
            raise ApiError("Isaac Sim needs the NVIDIA Omniverse EULA accepted by the user: ask them to turn physics "
                           "mode on once in the RetLens window and accept it there", 403)

    def physics(self, q: dict) -> dict:
        on = bool(q.get("on", True))
        balance = q.get("balance", self.scene.balance)
        if balance not in BALANCE:
            raise ApiError(f"balance must be one of {', '.join(BALANCE)}")
        why = self.scene.balance_problem(balance) if on or "balance" in q else ""  # turning off always works
        if why:
            raise ApiError(f"{BALANCE[balance]}: {why}", 409)
        if on and balance == "isaac":
            self._eula()
        if "assist" in q:
            self.scene.set_assist(float(q["assist"]))
        if balance != self.scene.balance:
            self.scene.set_balance(balance)
        self.scene.set_physics(on, "api")
        return {"physics": on, "balance": self.scene.balance, "mode": self.scene.mode_label(),
                "assist": self.scene.assist,
                "motions": {it.label: self.scene.job_text(it) for it in list(self.scene.items)}}

    def video(self, q: dict) -> dict:
        self._eula()
        item = self._item(q.get("id"))
        try:
            job = self.scene.save_video(item)
        except Exception as e:  # Isaac Sim not found
            raise ApiError(f"{type(e).__name__}: {e}", 409) from None
        return {"id": item.label, "state": job.state, "video": job.result, "note": "poll GET /api/jobs"}

    def jobs(self, q: dict) -> dict:
        out = []
        for it in list(self.scene.items):
            for key, job in it.handles.get("phys_jobs", {}).items():  # key: the harness scale, or the MuJoCo controller
                mode = {"kind": "mujoco", "balance": key} if job.kind == "policy" else {"kind": "physics", "assist": key}
                out.append({"id": it.label, **mode, "state": job.state, "stage": job.stage,
                            "progress": job.progress, "result": job.result, "message": job.message or None})
            job = it.handles.get("video_job")
            if job is not None:
                out.append({"id": it.label, "kind": "video", "state": job.state, "stage": job.stage,
                            "progress": job.progress, "result": job.result, "message": job.message or None})
        return {"busy": self.scene.jobs_busy(), "jobs": out}

    # ---------------------------------------------------------------- view
    def camera(self, q: dict) -> dict:
        if q.get("fit", True):
            self.scene.fit_camera()
        return {"camera": "fitted"}

    def screenshot(self, q: dict) -> dict:
        if self.window is None:
            raise ApiError("no window (headless)", 409)
        path = q.get("path") or os.path.join(paths.logs_dir(), f"screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        def grab():
            w = self.window
            w.raise_()
            g = w.frameGeometry()
            screen = w.screen() or w.windowHandle().screen()
            return screen.grabWindow(0, g.x() - screen.geometry().x(), g.y() - screen.geometry().y(),
                                     g.width(), g.height()).save(path)

        if not self.on_gui(grab):
            raise ApiError("could not save the screenshot", 500)
        return {"path": os.path.abspath(path)}


class _Handler(BaseHTTPRequestHandler):
    server_version = "RetLens-API"

    def log_message(self, fmt, *a):  # requests go to the app log, briefly
        print(f"[api] {self.address_string()} {fmt % a}", flush=True)

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(api_core.jsonable(body), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        srv: ApiServer = self.server.api  # type: ignore[attr-defined]
        if self.headers.get("Origin"):  # a web page: never
            return self._reply(403, {"ok": False, "error": "requests from web pages are not accepted"})
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("X-RetLens-Token", "")
        if not secrets.compare_digest(token, srv.token):
            return self._reply(401, {"ok": False, "error": "missing or wrong token (see api.json: retlens-cli api)"})
        url = urlparse(self.path)
        fn = srv.backend.routes.get((method, url.path.rstrip("/") or "/"))
        if fn is None:
            return self._reply(404, {"ok": False, "error": f"no endpoint {method} {url.path}; GET /api/help lists them"})
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except ValueError:
                return self._reply(400, {"ok": False, "error": "the body is not JSON"})
            if not isinstance(body, dict):
                return self._reply(400, {"ok": False, "error": "the body must be a JSON object"})
            q.update(body)
        try:
            out = fn(q)
        except ApiError as e:
            return self._reply(e.code, {"ok": False, "error": str(e)})
        except Exception as e:
            import traceback

            traceback.print_exc()
            return self._reply(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        self._reply(200, {"ok": True, **(out or {})})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class _ExclusiveServer(ThreadingHTTPServer):
    """One server per port. HTTPServer sets SO_REUSEADDR, which on Windows lets a second RetLens bind
    the same port too: its requests then reach the first window, which rejects the second's token."""

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ApiServer:
    """Serves ApiBackend on 127.0.0.1 (port; another free one when taken) in a daemon thread
    and writes the discovery file."""

    def __init__(self, backend: ApiBackend, port: int = DEFAULT_PORT, write_discovery: bool = True):
        self.backend, self.token = backend, secrets.token_urlsafe(24)
        try:
            self.httpd = _ExclusiveServer(("127.0.0.1", port), _Handler)
        except OSError:  # taken (another RetLens window, or another program)
            self.httpd = _ExclusiveServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.api = self
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._write = write_discovery
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="retlens-api", daemon=True)

    def start(self) -> "ApiServer":
        self._thread.start()
        self._previous = None
        if self._write:
            # another RetLens window may own the file: this one takes over, and hands it back on stop()
            prev = discovery()
            self._previous = prev if prev is not None and prev.get("pid") != os.getpid() else None
            os.makedirs(os.path.dirname(discovery_path()), exist_ok=True)
            with open(discovery_path(), "w", encoding="utf-8") as f:
                json.dump({"url": self.url, "port": self.port, "token": self.token, "pid": os.getpid(),
                           "api_version": api_core.API_VERSION, "started": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._write:
            d = discovery()
            if d is not None and d.get("token") == self.token:
                prev = getattr(self, "_previous", None)
                try:
                    if prev is not None and _alive(prev.get("pid")):  # the earlier window still runs: point at it again
                        with open(discovery_path(), "w", encoding="utf-8") as f:
                            json.dump(prev, f)
                    else:
                        os.remove(discovery_path())
                except OSError:
                    pass
