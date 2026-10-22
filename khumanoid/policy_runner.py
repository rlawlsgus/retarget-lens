"""Background MuJoCo runs for 균형 제어 in RetLens's physics mode (khumanoid/app/scene.py): a robot
motion replayed with no controller ("pd": open-loop stiff PD) or followed by GMT's tracking policy
("gmt"), both khumanoid/policy_replay.py, the same runs as tools/policy_replay.py.

    runner = PolicyRunner(cache_dir)
    job = runner.request(motion, "gmt", on_done=lambda job: ...)
    job.state, job.stage, job.progress   # "running", "시뮬레이션", 0.4
    job.result                           # the simulated npz (+ json), once done

MuJoCo at 1 kHz is quick (CMU 143_11, 10.9 s: about 2 s open loop, 4 s with the policy), so unlike
the Isaac runs nothing starts a process: one worker thread runs one clip at a time, and a cancel
stops it within 0.5 s of simulated time.

Results are keyed by the motion's arrays, the controller, configs/physics.yaml (PD gains, fall
rules), the GMT files, the hold after the clip and CACHE_VERSION, and saved as tools/policy_replay.py
saves them, so compare.load_item opens both (kind "MuJoCo 재생 · ...", info["policy_replay"]).
The policy runs in numpy (khumanoid/gmt_policy.py), so the installed program runs it too once GMT's
files are there (설치 도우미, khumanoid/prereqs.py).
"""

from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import paths, settings
from . import policy_replay as pr
from .motion import RobotMotion
from .physics_runner import PHYSICS_CONFIG, _file_id, _safe

CACHE_VERSION = 2  # bump when policy_replay's results change meaning (2: the policy in numpy, not torch)
HOLD_S = 1.0  # stand on the last pose this long after the clip, as tools/policy_replay.py does
MODEL_TEXT = "GMT G1 (23 DoF, wrists fixed), MuJoCo 1 kHz"


class Cancelled(Exception):
    pass


def _complete(npz: str) -> bool:
    """A finished result: the json is written after the npz."""
    return os.path.isfile(npz) and os.path.isfile(npz[:-4] + ".json")


def problem(controller: str, gmt_root: str | None = None) -> str:
    """'' when this controller can run here, else why not (menus show it, request() raises it)."""
    if controller not in pr.CONTROLLERS:
        return f"알 수 없는 제어기: {controller}"
    if importlib.util.find_spec("mujoco") is None:
        return "MuJoCo(mujoco 패키지)가 없습니다"
    root = gmt_root or settings.gmt_dir()
    files = pr.gmt_paths(root)
    get = ("'파일 > 설치 도우미'에서 GMT를 받으세요(연구용 라이선스 동의 필요)" if paths.INSTALLED else
           "설치 도우미나 scripts\\install_gmt.ps1로 받으세요")
    if not os.path.isfile(files["model"]):
        return f"GMT의 G1 MuJoCo 모델이 없습니다({root}). {get}"
    if controller == "gmt":
        if not os.path.isfile(files["policy"]):
            return f"GMT 추적 정책이 없습니다({files['policy']}). {get}"
        from .gmt_policy import problem as policy_problem

        bad = policy_problem(files["policy"])  # another network than the one the numpy port reproduces
        if bad:
            return f"{bad}. {get}"
    return ""


@dataclass
class PolicyJob:
    key: str
    name: str
    controller: str  # pd | gmt
    out_npz: str  # the result (+ .json next to it)
    kind: str = "policy"
    state: str = "queued"  # queued | running | done | failed | cancelled
    stage: str = "대기"
    progress: float = 0.0
    message: str = ""
    result: str | None = None
    started: float = 0.0
    finished: float = 0.0
    callbacks: list = field(default_factory=list)
    motion: RobotMotion | None = None  # the input, until the run starts
    info: dict = field(default_factory=dict)  # written into the result's json
    cancel_requested: bool = False

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")


class PolicyRunner:
    def __init__(self, cache_dir: str, physics_config: str = PHYSICS_CONFIG, hold_s: float = HOLD_S,
                 gmt_root: str | None = None, log: Callable | None = None,
                 simulate: Callable | None = None):
        """gmt_root: the GMT folder (None: settings.gmt_dir() at each request). simulate(motion,
        controller, progress) -> policy_replay.Result runs one clip (tests pass a stand-in);
        progress(k, n) raises Cancelled once the job is cancelled."""
        self.cache_dir, self.physics_config, self.hold_s = cache_dir, physics_config, float(hold_s)
        self.gmt_root = gmt_root
        self.log = log or (lambda *_: None)
        self._simulate = simulate or self._simulate_mujoco
        self.jobs: dict[str, PolicyJob] = {}
        self._queue: collections.deque[PolicyJob] = collections.deque()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._sims: dict[tuple, pr.G1Sim] = {}  # per controller and files: the policy loads once (worker only)
        self._worker = threading.Thread(target=self._loop, name="policy-runner", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ public
    def problem(self, controller: str) -> str:
        return problem(controller, self.gmt_root)

    def files(self) -> dict:
        return pr.gmt_paths(self.gmt_root)

    def key(self, motion: RobotMotion, controller: str) -> str:
        """Content hash of what a run depends on."""
        files = self.files()
        try:
            with open(self.physics_config, encoding="utf-8") as f:
                config = f.read()
        except OSError:
            config = ""
        h = hashlib.sha1()
        ids = [_file_id(files["model"]) if os.path.isfile(files["model"]) else None,
               _file_id(files["policy"]) if controller == "gmt" and os.path.isfile(files["policy"]) else None]
        h.update(json.dumps([CACHE_VERSION, controller, list(motion.joint_names), float(motion.fps), self.hold_s,
                             ids]).encode())
        for a in (motion.root_pos, motion.root_quat, motion.dof_pos):
            h.update(np.ascontiguousarray(a, dtype=np.float32).tobytes())
        h.update(config.encode())
        return h.hexdigest()[:12]

    def out_path(self, motion: RobotMotion, controller: str, key: str | None = None) -> str:
        key = key or self.key(motion, controller)
        return os.path.join(self.cache_dir, f"{_safe(motion.name)}_{key}_{controller}_sim.npz")

    def cached(self, motion: RobotMotion, controller: str) -> str | None:
        """Path of the simulated motion if this run was done before."""
        npz = self.out_path(motion, controller)
        return npz if _complete(npz) else None

    def request(self, motion: RobotMotion, controller: str, info: dict | None = None,
                on_done: Callable[[PolicyJob], None] | None = None) -> PolicyJob:
        """The run of this motion with this controller: finished at once when cached, else queued
        (or the one already queued / running). on_done(job) runs on the worker thread when the job
        ends (done, failed or cancelled); at once when cached. Raises when the controller cannot
        run here (problem())."""
        why = self.problem(controller)
        if why:
            raise RuntimeError(why)
        key = self.key(motion, controller)
        out = self.out_path(motion, controller, key)
        job = PolicyJob(key=key, name=_safe(motion.name), controller=controller, out_npz=out, info=dict(info or {}))
        with self._lock:
            old = self.jobs.get(key)
            if old is not None and old.active:
                if on_done:
                    old.callbacks.append(on_done)
                return old
            self.jobs[key] = job
            hit = _complete(out)
            if hit:
                job.state, job.stage, job.progress, job.result = "done", "완료 (이미 있음)", 1.0, out
            else:
                os.makedirs(self.cache_dir, exist_ok=True)
                job.motion = motion
                if on_done:
                    job.callbacks.append(on_done)
                self._queue.append(job)
                self._wake.set()
        if hit:
            if on_done:
                on_done(job)
        else:
            self.log(f"MuJoCo queued: {job.name} ({controller})")
        return job

    def cancel(self, job: PolicyJob) -> None:
        with self._lock:
            if not job.active:
                return
            job.cancel_requested = True  # a running job stops at its next progress call
            queued = job in self._queue
            if queued:
                self._queue.remove(job)
        if queued:
            self._finish(job, "cancelled", "취소됨")

    def busy(self) -> bool:
        with self._lock:
            return any(j.active for j in self.jobs.values())

    def shutdown(self) -> None:
        """Stop the worker (call on exit); a running clip stops at its next progress call."""
        with self._lock:
            self._closed = True
            queued = list(self._queue)
            self._queue.clear()
            for job in self.jobs.values():
                job.cancel_requested = True
        for job in queued:
            self._finish(job, "cancelled", "취소됨")
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
                except Cancelled:
                    self._finish(job, "cancelled", "취소됨")
                except Exception as e:  # never let one clip kill the worker
                    self._finish(job, "failed", f"{type(e).__name__}: {e}")

    def _run(self, job: PolicyJob) -> None:
        with self._lock:
            if job.state != "queued":
                return
            if job.cancel_requested:  # cancelled after the worker took it from the queue
                raise Cancelled()
            job.state, job.started = "running", time.time()
            loaded = any(k[0] == job.controller for k in self._sims)
            job.stage = "추적 정책 불러오기" if job.controller == "gmt" and not loaded else "준비"
        motion, job.motion = job.motion, None
        self.log(f"MuJoCo running: {job.name} ({job.controller})")

        def progress(k: int, n: int) -> None:
            if job.cancel_requested or self._closed:
                raise Cancelled()
            job.stage, job.progress = "시뮬레이션", 0.05 + 0.9 * k / max(n, 1)

        res = self._simulate(motion, job.controller, progress)
        if job.cancel_requested:
            raise Cancelled()
        job.stage, job.progress = "결과 저장", 0.96
        files = self.files()
        pr.save_result(res, job.out_npz, motion.joint_names, {
            **job.info, "controller_label": pr.LABELS[job.controller], "model": MODEL_TEXT,
            "gmt_files": {"model": files["model"], **({"policy": files["policy"]} if job.controller == "gmt" else {})},
            "physics_config": self.physics_config, "made_by": "RetLens 물리 모드 (khumanoid/policy_runner.py)"})
        job.result = job.out_npz
        self._finish(job, "done", "완료")

    def _simulate_mujoco(self, motion: RobotMotion, controller: str, progress) -> pr.Result:
        files = self.files()
        k = (controller, files["model"], files["policy"] if controller == "gmt" else "", self.physics_config)
        sim = self._sims.get(k)
        if sim is None:
            sim = self._sims[k] = pr.G1Sim(files["model"], controller, policy_path=files["policy"],
                                           physics_config=self.physics_config)
        return pr.run(sim, pr.Reference.from_motion(motion), hold_s=self.hold_s, progress=progress)

    def _finish(self, job: PolicyJob, state: str, message: str) -> None:
        with self._lock:
            job.state, job.message, job.finished, job.motion = state, message, time.time(), None
            if state == "done":
                job.stage, job.progress = "완료", 1.0
            else:
                job.stage = {"failed": "실패", "cancelled": "취소됨"}[state]
            callbacks, job.callbacks = job.callbacks, []
        self.log(f"MuJoCo {state}: {job.name} ({job.controller}) {message if state != 'done' else job.result}".rstrip())
        for cb in callbacks:
            try:
                cb(job)
            except Exception as e:
                self.log(f"MuJoCo callback failed: {type(e).__name__}: {e}")
