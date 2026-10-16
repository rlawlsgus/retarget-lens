"""Background PhysX runs of robot motions, cached by content.

The physics is tools/isaac_replay.py --physics run as its own process. Isaac Sim is
a separate install (tens of GB, an NVIDIA RTX GPU, its own EULA) that the viewer
(and later the packaged program) calls rather than bundles, so this module only
finds it, runs one clip at a time in a worker thread, reports progress and keeps
the results:

    runner = PhysicsRunner(cache_dir)
    job = runner.request(motion, assist=1.0, on_done=lambda job: ...)
    job.state, job.stage, job.progress   # "running", "시뮬레이션", 0.4
    job.result                           # <cache>/<clip>_<key>_a1/<clip>_sim.npz once done

Results are keyed by the motion's arrays, the physics config, the harness scale and
CACHE_VERSION, so the same clip comes back instantly next time.

Finding Isaac Sim (first match):
  1. the KHUMANOID_ISAAC_PYTHON environment variable (python.bat / python.sh of a
     standalone install, or any interpreter that can import isaacsim)
  2. this interpreter, when it can import isaacsim (the k-humanoid dev env);
     never in a frozen (packaged) build, where sys.executable is the program itself
  3. the standalone install folders in ISAAC_DIRS (C:\\isaacsim)

The Isaac EULA is never accepted here: pass accept_eula=True only after the user
accepted it (viewer --isaac-accept-eula); otherwise a run fails with that message.
"""

from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .motion import RobotMotion

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPLAY_SCRIPT = os.path.join(ROOT, "tools", "isaac_replay.py")
PHYSICS_CONFIG = os.path.join(ROOT, "configs", "physics.yaml")
CACHE_VERSION = 1  # bump when isaac_replay's physics output changes meaning
ISAAC_ENV = "KHUMANOID_ISAAC_PYTHON"
ISAAC_DIRS = [r"C:\isaacsim"] if os.name == "nt" else [os.path.expanduser("~/isaacsim")]

# stage name in the "[isaac_replay] progress <stage> i/n" lines -> (label, start, end of the overall bar)
STAGES = {"reference": ("기준 자세 기록", 0.25, 0.35), "simulate": ("시뮬레이션", 0.35, 0.95)}
STARTING = ("Isaac 시작 중", 0.0, 0.25)
PROGRESS_RE = re.compile(r"\[isaac_replay\] progress (\w+) (\d+)/(\d+)")


def isaac_command() -> list[str]:
    """Command prefix that runs a Python script with Isaac Sim importable."""
    p = os.environ.get(ISAAC_ENV)
    if p:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"{ISAAC_ENV}={p}: no such file")
        return [p]
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("isaacsim") is not None:
        return [sys.executable]
    for d in ISAAC_DIRS:
        launcher = os.path.join(d, "python.bat" if os.name == "nt" else "python.sh")
        if os.path.isfile(launcher):
            return [launcher]
    raise FileNotFoundError(f"Isaac Sim을 찾지 못했습니다. 설치 폴더의 python.bat 경로를 환경변수 {ISAAC_ENV}에 넣어 주세요")


def motion_key(motion: RobotMotion, assist: float, config_text: str = "") -> str:
    """Content hash of what a physics run depends on."""
    h = hashlib.sha1()
    h.update(json.dumps([CACHE_VERSION, list(motion.joint_names), float(motion.fps), float(assist)]).encode())
    for a in (motion.root_pos, motion.root_quat, motion.dof_pos):
        h.update(np.ascontiguousarray(a, dtype=np.float32).tobytes())
    h.update(config_text.encode())
    return h.hexdigest()[:12]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "clip"


@dataclass
class PhysicsJob:
    key: str
    name: str
    assist: float
    out_dir: str
    state: str = "queued"  # queued | running | done | failed | cancelled
    stage: str = "대기"
    progress: float = 0.0  # 0..1 over the whole run (start-up included)
    message: str = ""
    result: str | None = None  # <out_dir>/<name>_sim.npz
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


class PhysicsRunner:
    def __init__(self, cache_dir: str, physics_config: str = PHYSICS_CONFIG, script: str = REPLAY_SCRIPT,
                 command: list[str] | None = None, accept_eula: bool = False, log: Callable | None = None):
        """command: interpreter prefix (default isaac_command(), looked up on the first run)."""
        self.cache_dir, self.physics_config, self.script = cache_dir, physics_config, script
        self.command, self.accept_eula = command, accept_eula
        self.log = log or (lambda *_: None)
        self.jobs: dict[str, PhysicsJob] = {}
        self._queue: collections.deque[PhysicsJob] = collections.deque()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._worker = threading.Thread(target=self._loop, name="physics-runner", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ public
    def key(self, motion: RobotMotion, assist: float) -> str:
        try:
            with open(self.physics_config, encoding="utf-8") as f:
                cfg = f.read()
        except OSError:
            cfg = ""
        return motion_key(motion, assist, cfg)

    def out_dir(self, motion: RobotMotion, assist: float) -> str:
        return os.path.join(self.cache_dir, f"{_safe(motion.name)}_{self.key(motion, assist)}_a{assist:g}")

    def cached(self, motion: RobotMotion, assist: float) -> str | None:
        """Path of the simulated motion if this run was done before."""
        d = self.out_dir(motion, assist)
        npz = os.path.join(d, f"{_safe(motion.name)}_sim.npz")
        return npz if os.path.isfile(npz) and os.path.isfile(npz[:-4] + ".json") else None

    def request(self, motion: RobotMotion, assist: float = 1.0,
                on_done: Callable[[PhysicsJob], None] | None = None) -> PhysicsJob:
        """The job for this motion and harness scale: finished at once when cached, else
        queued (or the one already queued / running). on_done(job) runs on the worker
        thread when the job ends (done, failed or cancelled); at once when cached."""
        key = self.key(motion, assist)
        with self._lock:
            job = self.jobs.get(key)
            if job is not None and (job.active or job.state == "done"):
                if job.active:
                    if on_done:
                        job.callbacks.append(on_done)
                    return job
                if job.result and os.path.isfile(job.result):
                    if on_done:
                        on_done(job)
                    return job
            name = _safe(motion.name)
            job = PhysicsJob(key=key, name=name, assist=float(assist), out_dir=self.out_dir(motion, assist))
            self.jobs[key] = job
            hit = self.cached(motion, assist)
            if hit:
                job.state, job.stage, job.progress, job.result = "done", "완료 (캐시)", 1.0, hit
                if on_done:
                    on_done(job)
                return job
            os.makedirs(job.out_dir, exist_ok=True)
            motion.save_npz(job.input_path)
            if on_done:
                job.callbacks.append(on_done)
            self._queue.append(job)
            self._wake.set()
            self.log(f"physics queued: {name} (harness x{assist:g})")
            return job

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
        cmd = (self.command or isaac_command()) + [
            self.script, "--robot-motion", job.input_path, "--physics", "--assist", f"{job.assist:g}",
            "--physics-config", self.physics_config, "--check-out", job.out_dir, "--snapshots", "0", "--progress"]
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if self.accept_eula:
            env["OMNI_KIT_ACCEPT_EULA"] = "YES"
        with self._lock:
            if job.state != "queued":
                return
            job.state, job.started = "running", time.time()
            job.stage, job.progress = STARTING[0], STARTING[1]
            job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        env=env, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log(f"physics running: {job.name} (harness x{job.assist:g})")
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
        npz = os.path.join(job.out_dir, f"{job.name}_sim.npz")
        if code == 0 and os.path.isfile(npz) and os.path.isfile(npz[:-4] + ".json"):
            job.result = npz
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
        elif "simulated " in line:
            job.stage, job.progress = "결과 저장", 0.96

    def _finish(self, job: PhysicsJob, state: str, message: str) -> None:
        with self._lock:
            job.state, job.message, job.finished, job.proc = state, message, time.time(), None
            if state == "done":
                job.stage, job.progress = "완료", 1.0
            else:
                job.stage = {"failed": "실패", "cancelled": "취소됨"}[state]
            callbacks, job.callbacks = job.callbacks, []
        self.log(f"physics {state}: {job.name} {message if state != 'done' else ''}".rstrip())
        for cb in callbacks:
            try:
                cb(job)
            except Exception as e:
                self.log(f"physics callback failed: {type(e).__name__}: {e}")


def _failure(code: int, tail) -> str:
    text = "\n".join(tail)
    if "EULA not accepted" in text:
        return "Isaac Sim EULA에 동의하지 않은 상태입니다(뷰어를 --isaac-accept-eula로 실행)"
    last = next((ln for ln in reversed(tail) if "Error" in ln or "error" in ln), tail[-1] if tail else "")
    return f"종료 코드 {code}: {last[-200:]}"


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and its children (python.bat -> python -> Kit on Windows)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
