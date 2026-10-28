"""Background Isaac Sim runs of robot motions: PhysX simulation and videos.

Both are tools/isaac_replay.py run as its own process. Isaac Sim is a separate
install (tens of GB, an NVIDIA RTX GPU, its own EULA) that the viewer (and later the
packaged program) calls rather than bundles, so this module only finds it, runs one
job at a time in a worker thread (one Isaac on the GPU), reports progress and keeps
the results:

    runner = PhysicsRunner(cache_dir)
    job = runner.request(motion, assist=1.0, on_done=lambda job: ...)     # --physics
    job = runner.request_video(motion, "videos/02_01.mp4", human="02_01.bvh")  # --video
    job.state, job.stage, job.progress   # "running", "시뮬레이션", 0.4
    job.result                           # the simulated npz / the video, once done

Physics results are keyed by the motion's arrays, the physics config, the harness
scale and CACHE_VERSION, so the same clip comes back instantly next time; a video
that already exists is returned as is.

Finding Isaac Sim (first match, retlens.settings.find_isaac):
  1. the 환경 설정 value (python.bat / python.sh of a standalone install, or its folder)
  2. the RETLENS_ISAAC_PYTHON environment variable (same, or any interpreter that can
     import isaacsim)
  3. this interpreter, when it can import isaacsim (the retlens dev env);
     never in a frozen (packaged) build, where sys.executable is the program itself
  4. the standalone install folders (settings.isaac_dirs(): C:\\isaacsim, C:\\isaacsim-<version>)

The Isaac EULA is never accepted here: pass accept_eula=True only after the user
accepted it (viewer --isaac-accept-eula); otherwise a run fails with that message.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import paths
from .motion import RobotMotion
from .settings import ISAAC_DIRS, ISAAC_ENV  # noqa: F401  (re-exported: where Isaac Sim is looked for)

# Isaac's Python runs isaac_replay.py from a folder of plain source files (the repository, or
# the installed program's isaac/ folder); configs are passed explicitly, so it never relies on
# its own folder holding them
REPLAY_SCRIPT = paths.isaac_replay_script()
PHYSICS_CONFIG = paths.resource("configs", "physics.yaml")
QC_CONFIG = paths.resource("configs", "qc.yaml")
CACHE_VERSION = 1  # bump when isaac_replay's physics output changes meaning

# stage name in the "[isaac_replay] progress <stage> i/n" lines -> (label, start, end of the overall bar)
STAGES = {"reference": ("기준 자세 기록", 0.25, 0.35), "simulate": ("시뮬레이션", 0.35, 0.95),
          "render": ("렌더링", 0.25, 0.95), "replay": ("재생", 0.25, 0.95)}
STARTING = ("Isaac 시작 중", 0.0, 0.25)
PROGRESS_RE = re.compile(r"\[isaac_replay\] progress (\w+) (\d+)/(\d+)")


def isaac_command() -> list[str]:
    """Command prefix that runs a Python script with Isaac Sim importable (settings.find_isaac:
    환경 설정, then $RETLENS_ISAAC_PYTHON, then this interpreter in the dev env, then C:\\isaacsim)."""
    from . import settings

    found = settings.find_isaac(settings.load(reload=True))
    if found.path is None:
        raise FileNotFoundError(f"{found.problem}. RetLens의 '파일 > 환경 설정'에서 Isaac Sim 설치 폴더를 지정하거나, "
                                f"python.bat 경로를 환경변수 {ISAAC_ENV}에 넣어 주세요")
    return [found.path]


def motion_key(motion: RobotMotion, assist: float, config_text: str = "") -> str:
    """Content hash of what a physics run depends on."""
    h = hashlib.sha1()
    h.update(json.dumps([CACHE_VERSION, list(motion.joint_names), float(motion.fps), float(assist)]).encode())
    for a in (motion.root_pos, motion.root_quat, motion.dof_pos):
        h.update(np.ascontiguousarray(a, dtype=np.float32).tobytes())
    h.update(config_text.encode())
    return h.hexdigest()[:12]


def _file_id(path: str | None) -> list:
    if not path:
        return []
    st = os.stat(path)
    return [os.path.abspath(path), st.st_size, int(st.st_mtime)]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "clip"


@dataclass
class PhysicsJob:
    key: str
    name: str
    assist: float
    out_dir: str  # working folder: the input npz, run.log, the check / sim json
    kind: str = "physics"  # physics | video
    args: list = field(default_factory=list)  # isaac_replay arguments
    outputs: list = field(default_factory=list)  # first existing one is the result
    state: str = "queued"  # queued | running | done | failed | cancelled
    stage: str = "대기"
    progress: float = 0.0  # 0..1 over the whole run (start-up included)
    message: str = ""
    result: str | None = None
    started: float = 0.0
    finished: float = 0.0
    log_tail: collections.deque = field(default_factory=lambda: collections.deque(maxlen=40))
    callbacks: list = field(default_factory=list)
    proc: subprocess.Popen | None = None

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")

    @property
    def input_path(self) -> str:
        return os.path.join(self.out_dir, f"{self.name}.npz")

    def found(self) -> str | None:
        """The finished output, if it is there (a physics result also needs its json)."""
        for p in self.outputs:
            if os.path.isfile(p) and (self.kind != "physics" or os.path.isfile(p[:-4] + ".json")):
                return p
        return None


class PhysicsRunner:
    def __init__(self, cache_dir: str, physics_config: str = PHYSICS_CONFIG, script: str = REPLAY_SCRIPT,
                 command: list[str] | None = None, accept_eula: bool = False, log: Callable | None = None,
                 robot_usd: str | None = None):
        """command: interpreter prefix (default isaac_command(), looked up on the first run).
        robot_usd: the robot's USD (a local file or a URL); None = the 환경 설정 value at each
        request, where empty means Unitree G1 from NVIDIA's asset library (needs internet)."""
        self.cache_dir, self.physics_config, self.script = cache_dir, physics_config, script
        self.command, self.accept_eula = command, accept_eula
        self._robot_usd = robot_usd
        self.log = log or (lambda *_: None)
        self.jobs: dict[str, PhysicsJob] = {}
        self._queue: collections.deque[PhysicsJob] = collections.deque()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._worker = threading.Thread(target=self._loop, name="physics-runner", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ public
    def robot_usd(self) -> str:
        """The robot USD Isaac loads ("" = the asset library's G1)."""
        if self._robot_usd is not None:
            return self._robot_usd
        from . import settings

        return settings.load(reload=True).robot_usd.strip().strip('"')

    def _usd_text(self) -> str:
        """Part of the result keys: another robot asset gives other results. Empty for the
        default asset, so results computed before this option keep their keys."""
        usd = self.robot_usd()
        if not usd:
            return ""
        return "\n# robot_usd " + json.dumps(_file_id(usd) if os.path.isfile(usd) else usd)

    def _robot_args(self) -> list[str]:
        usd = self.robot_usd()
        return ["--robot-usd", usd] if usd else []

    def _config_text(self) -> str:
        try:
            with open(self.physics_config, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        return text + self._usd_text()

    def key(self, motion: RobotMotion, assist: float) -> str:
        return motion_key(motion, assist, self._config_text())

    def out_dir(self, motion: RobotMotion, assist: float) -> str:
        return os.path.join(self.cache_dir, f"{_safe(motion.name)}_{self.key(motion, assist)}_a{assist:g}")

    def cached(self, motion: RobotMotion, assist: float) -> str | None:
        """Path of the simulated motion if this run was done before."""
        npz = os.path.join(self.out_dir(motion, assist), f"{_safe(motion.name)}_sim.npz")
        return npz if os.path.isfile(npz) and os.path.isfile(npz[:-4] + ".json") else None

    def request(self, motion: RobotMotion, assist: float = 1.0,
                on_done: Callable[[PhysicsJob], None] | None = None) -> PhysicsJob:
        """The physics job for this motion and harness scale: finished at once when cached,
        else queued (or the one already queued / running). on_done(job) runs on the worker
        thread when the job ends (done, failed or cancelled); at once when cached."""
        name = _safe(motion.name)
        out_dir = self.out_dir(motion, assist)
        job = PhysicsJob(key=self.key(motion, assist), name=name, assist=float(assist), out_dir=out_dir,
                         outputs=[os.path.join(out_dir, f"{name}_sim.npz")])
        job.args = ["--robot-motion", job.input_path, "--physics", "--assist", f"{assist:g}",
                    "--physics-config", self.physics_config, "--qc-config", QC_CONFIG, "--check-out", out_dir,
                    "--snapshots", "0", *self._robot_args()]
        return self._submit(job, motion, on_done)

    def video_key(self, motion: RobotMotion, human: str | None = None, physics: bool = False,
                  assist: float = 1.0) -> str:
        """Content hash of what a recording depends on: the motion, the human file, and the
        physics config and harness (physics) or the robot asset."""
        cfg = self._config_text() if physics else self._usd_text()
        return hashlib.sha1(json.dumps([motion_key(motion, assist if physics else -1.0, cfg), _file_id(human),
                                        "video", physics]).encode()).hexdigest()[:12]

    def request_video(self, motion: RobotMotion, video: str, human: str | None = None, physics: bool = False,
                      assist: float = 1.0, smpl_model_dir: str | None = None,
                      on_done: Callable[[PhysicsJob], None] | None = None) -> PhysicsJob:
        """Record the motion (with the human file next to it, if given) like
        `isaac_replay.py --human ... --robot-motion ... --video` (--physics: as simulated).
        video: the .mp4 to write (a .gif next to it when ffmpeg is missing); returned as is
        when it already exists, so a path should name what it holds (video_key)."""
        key = self.video_key(motion, human, physics, assist)
        name = _safe(motion.name)
        out_dir = os.path.join(self.cache_dir, f"video_{name}_{key}")
        base = os.path.splitext(os.path.abspath(video))[0]
        job = PhysicsJob(key=key, name=name, assist=float(assist), out_dir=out_dir, kind="video",
                         outputs=[base + ".mp4", base + ".gif"])
        # a huge stride: replay only the frames the video needs (a 120 fps human otherwise steps 4x as many)
        job.args = ["--robot-motion", job.input_path, "--video", base + ".mp4", "--check-out", out_dir,
                    "--qc-config", QC_CONFIG, "--snapshots", "0", "--stride", "1000000", *self._robot_args()]
        if human:
            job.args += ["--human", os.path.abspath(human)]
            if smpl_model_dir:
                job.args += ["--smpl-model-dir", smpl_model_dir]
        if physics:
            job.args += ["--physics", "--assist", f"{assist:g}", "--physics-config", self.physics_config]
        return self._submit(job, motion, on_done)

    def cancel(self, job: PhysicsJob) -> None:
        with self._lock:
            if job.state == "queued":
                self._queue.remove(job)
                self._finish(job, "cancelled", "취소됨")
            elif job.state == "running" and job.proc is not None:
                job.state = "cancelled"  # the worker sees the exit and keeps this state
                _kill_tree(job.proc)

    def busy(self) -> bool:
        with self._lock:
            return any(j.active for j in self.jobs.values())

    def shutdown(self) -> None:
        """Stop the worker and any running Isaac process (call on exit)."""
        with self._lock:
            self._closed = True
            for job in list(self._queue):
                self.cancel(job)
            for job in self.jobs.values():
                if job.state == "running":
                    self.cancel(job)
        self._wake.set()

    # ------------------------------------------------------------ worker
    def _submit(self, job: PhysicsJob, motion: RobotMotion, on_done) -> PhysicsJob:
        with self._lock:
            old = self.jobs.get(job.key)
            if old is not None and old.active:
                if on_done:
                    old.callbacks.append(on_done)
                return old
            if old is not None and old.state == "done" and old.result and os.path.isfile(old.result):
                if on_done:
                    on_done(old)
                return old
            self.jobs[job.key] = job
            hit = job.found()
            if hit:
                job.state, job.stage, job.progress, job.result = "done", "완료 (이미 있음)", 1.0, hit
                if on_done:
                    on_done(job)
                return job
            os.makedirs(job.out_dir, exist_ok=True)
            motion.save_npz(job.input_path)
            if on_done:
                job.callbacks.append(on_done)
            self._queue.append(job)
            self._wake.set()
            self.log(f"{job.kind} queued: {job.name}" + (f" (harness x{job.assist:g})" if job.kind == "physics" else ""))
            return job

    def _loop(self) -> None:
        while not self._closed:
            self._wake.wait(0.5)
            self._wake.clear()
            while not self._closed:
                with self._lock:
                    job = self._queue.popleft() if self._queue else None
                if job is None:
                    break
                try:
                    self._run(job)
                except Exception as e:  # never let one clip kill the worker
                    self._finish(job, "failed", f"{type(e).__name__}: {e}")

    def _run(self, job: PhysicsJob) -> None:
        cmd = (self.command or isaac_command()) + [self.script] + job.args + ["--progress"]
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if self.accept_eula:
            env["OMNI_KIT_ACCEPT_EULA"] = "YES"
        with self._lock:
            if job.state != "queued":
                return
            job.state, job.started = "running", time.time()
            job.stage, job.progress = STARTING[0], STARTING[1]
            job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        env=env, cwd=paths.isaac_root(), text=True, encoding="utf-8", errors="replace",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log(f"{job.kind} running: {job.name}")
        with open(os.path.join(job.out_dir, "run.log"), "w", encoding="utf-8") as logf:
            for line in job.proc.stdout:
                logf.write(line)
                line = line.rstrip()
                if line:
                    job.log_tail.append(line)
                self._parse(job, line)
        code = job.proc.wait()
        if job.state == "cancelled":
            self._finish(job, "cancelled", "취소됨")
            return
        hit = job.found() if code == 0 else None
        if hit:
            job.result = hit
            self._finish(job, "done", "완료")
        else:
            self._finish(job, "failed", _failure(code, job.log_tail))

    def _parse(self, job: PhysicsJob, line: str) -> None:
        if not line.startswith("[isaac_replay]"):
            if job.stage == STARTING[0]:  # start-up: creep toward the end of its share
                job.progress = min(STARTING[2] - 0.01, job.progress + 0.0005)
            return
        m = PROGRESS_RE.search(line)
        if m and m.group(1) in STAGES:
            label, a, b = STAGES[m.group(1)]
            job.stage, job.progress = label, a + (b - a) * int(m.group(2)) / max(int(m.group(3)), 1)
        elif "simulated " in line or "replayed " in line:
            job.stage, job.progress = ("영상 인코딩" if job.kind == "video" else "결과 저장"), 0.96

    def _finish(self, job: PhysicsJob, state: str, message: str) -> None:
        with self._lock:
            job.state, job.message, job.finished, job.proc = state, message, time.time(), None
            if state == "done":
                job.stage, job.progress = "완료", 1.0
            else:
                job.stage = {"failed": "실패", "cancelled": "취소됨"}[state]
            callbacks, job.callbacks = job.callbacks, []
        self.log(f"{job.kind} {state}: {job.name} {message if state != 'done' else job.result}".rstrip())
        for cb in callbacks:
            try:
                cb(job)
            except Exception as e:
                self.log(f"{job.kind} callback failed: {type(e).__name__}: {e}")


def _failure(code: int, tail) -> str:
    text = "\n".join(tail)
    if "EULA not accepted" in text:
        return "Isaac Sim EULA에 동의하지 않은 상태입니다(물리 모드를 켜고 동의 창에서 동의하세요)"
    last = next((ln for ln in reversed(tail) if "Error" in ln or "error" in ln), tail[-1] if tail else "")
    return f"종료 코드 {code}: {last[-200:]}"


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and its children (python.bat -> python -> Kit on Windows)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.kill()
