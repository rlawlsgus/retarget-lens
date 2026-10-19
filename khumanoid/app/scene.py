"""The motion scene shared by the viewers: loaded motions, playback, physics / video
jobs, analysis data and their 3D drawing in a viser scene. No widgets here; a front end
(tools/compare_viewer.py in the browser, khumanoid/app/editor.py on the desktop) binds
its controls to the attributes and methods below and listens for changes:

    scene = MotionScene(server, load_robot_urdf(urdf), SceneOptions(...))
    scene.listen(lambda event, payload: ...)   # "items", "item", "status", "time", "log"
    scene.add("data/raw/cmu_bvh/02_01.bvh")
    scene.tick(dt)                              # advance playback and pose everything

Listeners can be called from worker threads (physics / video jobs finishing); a GUI
toolkit that needs its own thread has to marshal them (the Qt editor uses a signal).
"""

from __future__ import annotations

import os
import re
import threading
import time
import warnings
from dataclasses import astuple, dataclass, replace
from typing import Callable

import numpy as np

from .. import analysis
from ..compare import Item, compute_metrics, load_item
from ..diagnosis import CAUSE_KO
from ..io import urdf_joint_limits
from ..physics_runner import PHYSICS_CONFIG, PhysicsJob, PhysicsRunner
from ..rotations import quat_mul, quat_to_matrix
from .robots import OverlayBatch, RobotBatch

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEFAULT_URDF = os.path.join(os.path.dirname(ROOT), "GMR", "assets", "unitree_g1", "g1_custom_collision_29dof.urdf")
PHYSICS_CACHE = os.path.join(ROOT, "data", "cache", "physics")
VIDEO_DIR = os.path.join(ROOT, "reports", "videos", "viewer")
PALETTE = [(230, 90, 50), (50, 125, 215), (60, 165, 90), (150, 90, 190), (215, 165, 40), (110, 110, 110),
           (0, 160, 170), (200, 70, 140)]
GRAPH_FIXED = ("골반 높이 (m)", "골반 수평속도 (m/s)")
METRIC_ROWS = [  # (label, metrics key, format)
    ("길이 (s)", "duration", "{:.1f}"), ("관절 가속도 (rad/s²)", "acc_mean", "{:.1f}"),
    ("관절 저크 (rad/s³)", "jerk_mean", "{:.0f}"), ("최대 관절속도 (rad/s)", "vel_max", "{:.1f}"),
    ("발 미끄러짐 (%)", "planted_slip_pct", "{:.2f}"), ("바닥 관통 (%)", "penetration_pct", "{:.2f}"),
    ("발 최저점 (cm)", "sole_min_cm", "{:.1f}"), ("스윙 발 바닥 근접 (%)", "swing_low_pct", "{:.1f}"),
    ("CoM 지지 밖 (%)", "com_out_pct", "{:.1f}"), ("ZMP 지지 밖 (%)", "zmp_out_pct", "{:.1f}"),
    ("정적 불균형 (%)", "static_unbalanced_pct", "{:.1f}"), ("QC", "qc", "{}"),
    ("물리: 보조 힘 (체중 %)", "phys_harness_pct", "{:.1f}"), ("물리: 넘어짐", "phys_falls", "{}"),
    ("물리: 토크 한계 초과 (%)", "phys_saturated_pct", "{:.1f}"), ("물리 판정", "phys_ok", "{}"),
]
METRIC_NOTES = (
    "RMSE: 기준과 겹치는 구간의 관절별 RMSE 중앙값(시간 오프셋 반영). 발 미끄러짐: 발바닥 전체가 붙은 채 0.3 m/s 이상으로 "
    "0.1 s 이상 움직인 프레임 비율. 바닥 관통: 발 최저점 -2 cm 아래 프레임 비율. 스윙 발 바닥 근접: 가장 느린 발바닥 점까지 "
    "0.5 m/s 넘게 움직이는 발이 그때의 바닥(디딤발 높이를 따라감) 1 cm 안을 지나는 비율(물리에서 발끝이 걸림). 물리 행: "
    "Isaac PhysX 결과(물리 모드, 또는 isaac_replay.py --physics 결과 파일)만 - 골반 보조 힘 평균(체중 대비), 넘어짐 수, "
    "관절 토크 한계를 넘은 프레임 비율. 물리 모드에서는 다른 행도 시뮬레이션된 동작으로 잽니다.")
# Every row of metric_table, by topic, with what it measures (the editor shows these on hover).
METRIC_HELP = [
    ("기본", [
        ("재생 방식", "기구학 = 리타게팅 결과를 그대로 재생합니다. 물리 x1 = Isaac PhysX로 시뮬레이션한 결과이고, "
                   "x 뒤 숫자는 골반 보조 힘 배율입니다(x0 = 보조 없음)."),
        ("길이 (s)", "모션 길이."),
    ]),
    ("매끄러움 (클수록 떨림)", [
        ("관절 가속도 (rad/s²)", "모든 관절 각가속도 크기의 평균."),
        ("관절 저크 (rad/s³)", "각가속도 변화율 크기의 평균. 떨림에 가장 민감합니다."),
        ("최대 관절속도 (rad/s)", "가장 빨리 움직인 관절의 속도."),
    ]),
    ("발·바닥", [
        ("발 미끄러짐 (%)", "발바닥 전체가 바닥에 붙은 채 0.3 m/s 이상으로 0.1 s 이상 움직인 프레임 비율."),
        ("바닥 관통 (%)", "발 최저점이 바닥 아래 2 cm보다 깊은 프레임 비율."),
        ("발 최저점 (cm)", "클립 전체에서 발이 가장 낮게 내려간 높이. 음수면 바닥 아래입니다."),
        ("스윙 발 바닥 근접 (%)", "0.5 m/s 넘게 움직이는 발이 바닥(디딤발 높이를 따라감) 1 cm 안을 지나는 비율. "
                             "높으면 물리에서 발끝이 걸려 비틀거립니다."),
    ]),
    ("균형 (발이 닿은 프레임 기준)", [
        ("CoM 지지 밖 (%)", "질량중심(CoM)의 바닥 투영이 지지다각형 밖인 비율. 걷는 중에는 정상 동작도 높게 나옵니다."),
        ("ZMP 지지 밖 (%)", "ZMP가 지지다각형 밖인 비율."),
        ("정적 불균형 (%)", "몸이 거의 멈춰 있는데(CoM < 0.1 m/s) CoM 투영이 지지다각형 밖 2 cm 넘게 0.2 s 이상 있는 "
                         "프레임 비율. 5%를 넘으면 QC가 WARN입니다."),
    ]),
    ("기준 모션과 비교", [
        ("기준 대비 다리 RMSE (°)", "기준과 겹치는 구간(시간 오프셋 반영)에서 다리 관절별 RMSE의 중앙값."),
        ("기준 대비 전체 RMSE (°)", "같은 방식으로 모든 관절의 RMSE 중앙값."),
        ("QC", "검증 결과: PASS / WARN / FAIL (README의 \"검증(QC) 기준\")."),
    ]),
    ("물리 (Isaac PhysX 결과에만)", [
        ("물리: 보조 힘 (체중 %)", "골반을 받쳐 준 보조 힘의 평균, 체중 대비."),
        ("물리: 넘어짐", "시뮬레이션에서 넘어진 횟수."),
        ("물리: 토크 한계 초과 (%)", "관절 토크가 모터 한계를 넘은 프레임 비율."),
        ("물리 판정", "통과, 또는 걸린 기준들(넘어짐, 보조 힘 과다, 토크 한계 초과 등). 칸에는 첫 항목만 나옵니다."),
    ]),
]
METRIC_HELP_FOOTER = "물리 모드에서는 물리 행 말고 다른 행도 시뮬레이션된 동작으로 잽니다."
METRIC_DESC = {name: desc for _, rows in METRIC_HELP for name, desc in rows}


def rel(path: str) -> str:
    """Path relative to the project when inside it."""
    r = os.path.relpath(os.path.abspath(path), ROOT)
    return path if r.startswith("..") else r


def _quiet_remove(handle) -> None:
    """remove() without viser's "already removed node" warnings: ViserUrdf.remove() removes
    each link frame before the link frames nested in it."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Attempted to remove already removed node")
        handle.remove()


def hexcolor(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def yaw_quat(yaw: float) -> np.ndarray:
    return np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])


def heading(q_wxyz: np.ndarray) -> float:
    x = quat_to_matrix(q_wxyz)[:, 0]  # body x axis in the world
    return float(np.arctan2(x[1], x[0]))


def human_scale(item: Item) -> float:
    """Uniform scale that puts the source skeleton on the robot (GMR scales positions)."""
    h, r = item.human, item.robot
    hips = next((i for i, n in enumerate(h.joint_names) if n.lower() in ("hips", "pelvis", "hip")), 0)
    tr = np.arange(r.num_frames) / r.fps
    hp = h.positions[np.clip(np.round(tr * h.fps).astype(int), 0, h.num_frames - 1), hips]
    dh = hp[:, :2] - hp[:1, :2]
    dr = r.root_pos[:, :2] - r.root_pos[:1, :2]
    if np.nanmax(np.linalg.norm(dh, axis=1)) > 0.5:
        return float(np.nansum(dh * dr) / max(np.nansum(dh * dh), 1e-9))
    return float(np.nanmean(r.root_pos[:, 2]) / max(np.nanmean(hp[:, 2]), 1e-6))


def decimate(mesh, cell: float):
    """Vertex clustering on a cell-sized grid: enough detail for a viewer, far fewer
    bytes to send per robot (the G1 STLs are 18.5 MB)."""
    import trimesh

    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    _, inv = np.unique(np.floor(v / cell).astype(np.int64), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    counts = np.bincount(inv)
    nv = np.zeros((counts.size, 3))
    np.add.at(nv, inv, v)
    nv /= counts[:, None]
    nf = inv[f]
    nf = nf[(nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])]
    _, first = np.unique(np.sort(nf, axis=1), axis=0, return_index=True)
    return trimesh.Trimesh(nv, nf[np.sort(first)], process=False)


def load_robot_urdf(path: str, cell: float = 0.004, log: Callable = print):
    """The robot URDF with meshes simplified on a cell-sized grid (0 = full detail)."""
    import yourdfpy

    urdf = yourdfpy.URDF.load(path, build_scene_graph=True, load_meshes=True, build_collision_scene_graph=False,
                              load_collision_meshes=False)
    if cell > 0:
        geo = urdf.scene.geometry
        before = sum(len(g.faces) for g in geo.values())
        for k in list(geo):
            geo[k] = decimate(geo[k], cell)
        after = sum(len(g.faces) for g in geo.values())
        log(f"robot meshes simplified for display: {before} -> {after} triangles ({cell * 1000:g} mm grid)")
    return urdf


@dataclass
class SceneOptions:
    """How motions are loaded and where jobs write (the viewers' command-line options)."""
    robot: str = "unitree_g1"
    urdf: str = DEFAULT_URDF
    smooth: float = 6.0
    swing_clearance_cm: float = 0.0
    fps: float = 30.0
    csv_fps: float = 30.0
    smpl_model_dir: str | None = None
    max_shift: float = 3.0
    physics_config: str = PHYSICS_CONFIG
    isaac_accept_eula: bool = False
    video_dir: str = VIDEO_DIR
    library: list | None = None


def add_scene_arguments(ap) -> None:
    """Command-line options shared by the browser viewer and the desktop editor."""
    ap.add_argument("inputs", nargs="*", help="motion files (human ones are retargeted)")
    ap.add_argument("--robot", default="unitree_g1", help="GMR robot for retargeting (default unitree_g1)")
    ap.add_argument("--urdf", default=DEFAULT_URDF, help="robot URDF for display")
    ap.add_argument("--smooth", type=float, default=6.0, help="smoothing for retargeted inputs (Hz, 0 = off)")
    ap.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                    help="lift swing feet of retargeted inputs to at least CM off the floor (0 = off; 2.5 recommended)")
    ap.add_argument("--fps", type=float, default=30.0, help="retarget output frame rate")
    ap.add_argument("--csv-fps", type=float, default=30.0, help="frame rate of Unitree csv files")
    ap.add_argument("--smpl-model-dir", default=os.environ.get("SMPL_MODEL_DIR", os.path.join(ROOT, "models")))
    ap.add_argument("--max-shift", type=float, default=3.0, help="search range of the automatic time alignment (s)")
    ap.add_argument("--mesh-cell", type=float, default=0.004,
                    help="simplify robot meshes on this grid (m) before sending them to the browser; 0 = full detail")
    ap.add_argument("--body-mesh", action="store_true", help="draw SMPL-X inputs as body meshes from the start")
    ap.add_argument("--library", action="append", default=None, metavar="DIR",
                    help="folder to list in the motion picker (repeatable; default: data/raw, data/samples, "
                         "data/retargeted, data/uploads, reports)")
    ap.add_argument("--physics", action="store_true", help="start in physics mode")
    ap.add_argument("--video-dir", default=VIDEO_DIR, help="where \"동영상 저장\" writes its MP4s")
    ap.add_argument("--physics-config", default=PHYSICS_CONFIG, help="PhysX settings for physics mode (yaml)")
    ap.add_argument("--isaac-accept-eula", action="store_true",
                    help="you accept the NVIDIA Omniverse EULA; physics mode runs Isaac Sim with OMNI_KIT_ACCEPT_EULA=YES")


def scene_options(args) -> SceneOptions:
    return SceneOptions(robot=args.robot, urdf=args.urdf, smooth=args.smooth, swing_clearance_cm=args.swing_clearance,
                        fps=args.fps, csv_fps=args.csv_fps, smpl_model_dir=args.smpl_model_dir, max_shift=args.max_shift,
                        physics_config=args.physics_config, isaac_accept_eula=args.isaac_accept_eula,
                        video_dir=args.video_dir, library=args.library)


@dataclass
class ViewSettings:
    """What the 3D view shows; front ends edit these and call MotionScene.view_changed()."""
    side_by_side: bool = True
    spacing: float = 1.8
    align: bool = True
    show_humans: bool = True
    human_beside: bool = True  # skeleton next to the robot, not inside it
    body_mesh: bool = False  # SMPL-X inputs as a body surface instead of sticks
    robot_translucent: bool = False
    show_labels: bool = True
    show_balance: bool = True
    speed: float = 1.0
    loop: bool = True


@dataclass
class StatusLine:
    item: Item | None
    text: str


class MotionScene:
    def __init__(self, server, urdf, opts: SceneOptions | None = None, log: Callable | None = None):
        self.server, self.urdf = server, urdf
        self.opts = opts or SceneOptions()
        self.log = log or (lambda msg: print(f"[scene] {msg}", flush=True))
        self.view = ViewSettings()
        self.items: list[Item] = []
        self.lock = threading.RLock()
        self.t = 0.0
        self.playing = False
        self.physics_on = False
        self.assist = 1.0
        self.phys_error = ""
        self._version = 0  # bumped by every event; with the time and settings it decides redraws
        self._drawn_key, self._drawn_at = None, 0.0
        self._listeners: list[Callable[[str, object], None]] = []
        self.fk = None
        try:
            self.fk = analysis.FootKinematics(self.opts.robot)
        except Exception as e:  # GMR missing: foot metrics off, everything else works
            self.log(f"foot metrics disabled ({type(e).__name__}: {e})")
        self.limits = urdf_joint_limits(self.opts.urdf)
        self.runner = PhysicsRunner(PHYSICS_CACHE, physics_config=self.opts.physics_config,
                                    accept_eula=self.opts.isaac_accept_eula, log=self.log)
        self.robots = RobotBatch(server, urdf)  # every robot's meshes, posed together each tick
        self.overlays = OverlayBatch(server)  # skeletons, support polygons, CoM / ZMP of all motions
        server.scene.set_up_direction("+z")
        server.scene.add_grid("/floor", width=40, height=40, cell_size=0.5, section_size=1.0,
                              plane_color=(235, 235, 238), plane_opacity=1.0, shadow_opacity=0.25)

    # ---------------------------------------------------------------- events
    def listen(self, fn: Callable[[str, object], None]) -> None:
        """fn(event, payload): "items" (added / removed / reordered), "item" (one item's
        state, payload the item), "status" (physics / video jobs), "log" (payload text)."""
        self._listeners.append(fn)

    def emit(self, event: str, payload=None) -> None:
        self._version += 1  # something may look different: the next tick redraws
        if event == "log":
            self.log(payload)
        for fn in list(self._listeners):
            try:
                fn(event, payload)
            except Exception as e:  # a broken listener must not stop the scene
                print(f"[scene] listener failed on {event}: {type(e).__name__}: {e}", flush=True)

    # ---------------------------------------------------------------- items
    def add(self, path: str) -> Item:
        """Load (retarget when needed) and show a motion file; raises on failure."""
        o = self.opts
        item = load_item(path, robot=o.robot, smooth=o.smooth, fps=o.fps, csv_fps=o.csv_fps,
                         smpl_model_dir=o.smpl_model_dir, swing_clearance=o.swing_clearance_cm / 100.0,
                         log=self.log)
        compute_metrics(item, self.fk, self.limits)
        with self.lock:
            used = {it.color for it in self.items}
            item.color = next((c for c in PALETTE if c not in used), PALETTE[len(self.items) % len(PALETTE)])
            base, n = item.label, 2
            while any(it.label == item.label for it in self.items):
                item.label = f"{base} ({n})"
                n += 1
            self.items.append(item)
            self._build_item(item, len(self.items) - 1)
            if self.view.body_mesh and item.kind.startswith("SMPL-X"):
                self._add_body_mesh(item)
            self._sync_robots()
        self.log(f"added {item.label}: {item.kind}, {item.robot.num_frames} frames @ {item.robot.fps:g} fps")
        self.emit("items")
        self._request_physics(item)
        return item

    def remove(self, item: Item) -> None:
        with self.lock:
            if item not in self.items:
                return
            jobs = [*item.handles.get("phys_jobs", {}).values(), item.handles.get("video_job")]
            for job in jobs:
                if job is not None and job.active and not any(
                        job in [*it.handles.get("phys_jobs", {}).values(), it.handles.get("video_job")]
                        for it in self.items if it is not item):
                    self.runner.cancel(job)
            for k, h in reversed(list(item.handles.items())):  # children (robot meshes) before their parent frame
                if k.startswith("ui_"):  # front-end widgets: the front end removes them
                    continue
                try:
                    _quiet_remove(h)
                except Exception:
                    pass
            self.items.remove(item)
            for i, it in enumerate(self.items):
                it.handles["index"] = i
            self._sync_robots()
        self.emit("items")

    def set_offset(self, item: Item, value: float) -> None:
        item.offset = float(value)
        self.emit("item", item)

    def set_visible(self, item: Item, value: bool) -> None:
        item.visible = bool(value)
        self.emit("item", item)

    def set_show_human(self, item: Item, value: bool) -> None:
        item.show_human = bool(value)
        self.emit("item", item)

    def _sync_robots(self) -> None:
        """Robot meshes and overlays: one instance per motion, in list order, in its colour."""
        self.robots.set_instances([it.color for it in self.items], 0.45 if self.view.robot_translucent else 1.0)
        self.overlays.sync([len(it.handles.get("bones", ())) for it in self.items], [it.color for it in self.items])

    def _joint_map(self, motion) -> list:
        """Column of each robot-model joint in a motion's dof_pos (None = held at 0)."""
        col = {n: i for i, n in enumerate(motion.joint_names)}
        return [col.get(n) for n in self.robots.joint_names]

    def _build_item(self, item: Item, index: int) -> None:
        s = self.server
        node = f"/m{id(item)}"
        names = self.robots.joint_names
        item.handles["map"] = self._joint_map(item.robot)
        item.handles["pos"] = np.zeros(3)  # where its pelvis is drawn (camera fitting)
        missing = [n for n, i in zip(names, item.handles["map"]) if i is None]
        if missing:
            self.log(f"  {item.label}: {len(missing)} robot joints not in the motion, held at 0")
        item.handles["label"] = s.scene.add_label(f"{node}/label", item.label, font_screen_scale=0.9,
                                                  anchor="bottom-center")
        if item.human is not None:  # drawn by the shared skeleton node (OverlayBatch)
            item.handles["scale"] = human_scale(item)
            item.handles["bones"] = np.array(item.human.bones(), dtype=int).reshape(-1, 2)
        # transform that starts the robot at the origin facing +x (applied when "align" is on)
        item.handles["yaw0"] = heading(item.robot.root_quat[0])
        item.handles["p0"] = item.robot.root_pos[0].copy()
        item.handles["index"] = index

    def _add_body_mesh(self, item: Item) -> None:
        from ..io.smpl import BodyMeshRig

        try:
            rig = BodyMeshRig(item.source, model_dir=self.opts.smpl_model_dir)
        except Exception as e:
            self.log(f"{item.label}: no body mesh ({type(e).__name__}: {e})")
            item.handles["mesh"] = None
            return
        light = tuple(int(200 + 0.2 * c) for c in item.color)
        item.handles["rig"] = rig
        item.handles["mesh"] = self.server.scene.add_mesh_simple(
            f"/m{id(item)}/body", rig.vertices(0).astype(np.float32), rig.faces, color=light, opacity=0.9)

    def view_changed(self, *names: str) -> None:
        """Apply ViewSettings fields that need scene work (meshes); the rest act on the next tick."""
        with self.lock:
            if "robot_translucent" in names:
                self._sync_robots()
            if "body_mesh" in names and self.view.body_mesh:  # loads the body model on first use
                for it in self.items:
                    if it.kind.startswith("SMPL-X") and "mesh" not in it.handles:
                        self._add_body_mesh(it)

    # ---------------------------------------------------------------- playback
    def time_range(self) -> tuple[float, float]:
        end = max([it.offset + it.robot.duration for it in self.items] or [1.0])
        start = min([it.offset for it in self.items] or [0.0])
        return min(0.0, start), max(end, 0.1)

    def set_playing(self, on: bool) -> None:
        self.playing = bool(on)
        self.emit("time")

    def toggle_play(self) -> None:
        self.set_playing(not self.playing)

    def seek(self, t: float) -> None:
        lo, hi = self.time_range()
        self.t = float(np.clip(t, lo, hi))
        self.emit("time")

    def step(self, n: int) -> None:
        self.playing = False
        self.seek(self.t + n / 30.0)

    def tick(self, dt: float) -> None:
        """Advance playback by dt seconds (wall time) and pose every motion. Nothing is sent
        when nothing changed (paused and untouched), so an idle scene costs nothing."""
        if self.playing:
            lo, hi = self.time_range()
            self.t += dt * float(self.view.speed)
            if self.t > hi:
                if self.view.loop:
                    self.t = lo
                else:
                    self.t, self.playing = hi, False
                    self.emit("time")
        key = (self.t, self.physics_on, self.assist, self._version, astuple(self.view),
               tuple((id(it), it.visible, it.show_human, it.offset) for it in self.items))
        now = time.perf_counter()
        if key == self._drawn_key and not (self.runner.busy() and now - self._drawn_at > 0.5):
            return  # labels still show job progress twice a second
        self._drawn_key, self._drawn_at = key, now
        # one atomic group per frame: the client applies the frame at once, and viser wakes its
        # network thread once instead of once per message
        with self.lock, self.server.atomic():
            n = len(self.items)
            T_base = np.tile(np.eye(4), (n, 1, 1))
            cfg = np.zeros((n, len(self.robots.joint_names)))
            visible = np.zeros(n, bool)
            humans, balance = [None] * n, [None] * n
            for i, item in enumerate(self.items):
                pose = self._pose(item)
                if pose is not None:
                    T_base[i], cfg[i], humans[i], balance[i] = pose
                    visible[i] = True
            self.robots.update(T_base, cfg, visible)
            self.overlays.update(humans, balance)

    def fit_camera(self) -> None:
        """Look at all visible robots from the front-left, far enough for the whole row."""
        with self.lock:
            pts = np.array([it.handles["pos"] for it in self.items if it.visible])
        if not len(pts):
            return
        cx, cy = pts[:, :2].mean(0)
        extent = float(np.ptp(pts[:, :2], axis=0).max()) if len(pts) > 1 else 0.0
        d = 2.8 + 0.6 * extent
        position = np.array([cx + 0.8 * d, cy - 0.8 * d, 1.2 + 0.2 * d])
        look_at = np.array([cx, cy, 0.75])
        self.server.initial_camera.position = tuple(position)
        self.server.initial_camera.look_at = tuple(look_at)
        for client in self.server.get_clients().values():
            client.camera.position = tuple(position)
            client.camera.look_at = tuple(look_at)

    # ---------------------------------------------------------------- drawing
    def _display_transform(self, item: Item) -> tuple[np.ndarray, np.ndarray]:
        """(yaw quaternion, translation) from motion world to display."""
        lane = -item.handles["index"] * float(self.view.spacing) if self.view.side_by_side else 0.0
        if self.view.align:
            q = yaw_quat(-item.handles["yaw0"])
            p0 = item.handles["p0"]
            shift = -quat_to_matrix(q) @ np.array([p0[0], p0[1], 0.0])
        else:
            q, shift = np.array([1.0, 0, 0, 0]), np.zeros(3)
        return q, shift + np.array([0.0, lane, 0.0])

    @staticmethod
    def _set_visible(item: Item, key: str, on: bool) -> None:
        """Visibility of a per-motion node, sent only when it changes."""
        h = item.handles
        if h.get(key) is not None and h.get(f"{key}_visible") != on:
            h[key].visible = h[f"{key}_visible"] = on

    def _pose(self, item: Item):
        """Move this motion's label (and body mesh); returns (robot base transform, joint
        values, skeleton sticks or None, (support edges, CoM, ZMP) or None) for the shared
        nodes, or None when the motion is hidden."""
        h, v = item.handles, self.view
        visible = item.visible
        self._set_visible(item, "label", visible and bool(v.show_labels))
        show_h = visible and item.show_human and bool(v.show_humans)
        mesh = h.get("mesh") if v.body_mesh else None
        self._set_visible(item, "mesh", show_h and mesh is not None)
        if not visible:
            return None
        src = self.shown(item)  # the physics result in physics mode
        robot = src.robot
        local = self.t - item.offset
        inside = 0.0 <= local <= robot.duration
        t = np.array([np.clip(local, 0.0, robot.duration)])
        pos, quat = analysis.sample_root(robot, t)
        dof = analysis.sample_dof(robot, t)[0]
        qd, shift = self._display_transform(item)  # the original's start, so both views line up
        R = quat_to_matrix(qd)
        p = R @ pos[0] + shift
        h["pos"] = p
        T_base = np.eye(4)
        T_base[:3, :3] = quat_to_matrix(quat_mul(qd, quat[0]))
        T_base[:3, 3] = p
        jmap = src.handles.get("map", h["map"])
        cfg = np.array([dof[i] if i is not None else 0.0 for i in jmap])
        h["label"].position = p + np.array([0.0, 0.0, 0.85])
        text = item.label if inside else f"{item.label} (범위 밖)"
        if self.is_physics_result(item):
            note = self.fall_note(item, local)
            text += " · 물리 결과 파일" + (f" · {note}" if note else "")
        elif self.physics_on:
            if src is item:  # not computed yet: still the joint angles
                job = h.get("phys_jobs", {}).get(self.assist)
                text += (" · 물리 대기" if job is not None and job.state == "queued" else
                         f" · 물리 계산 {100 * job.progress:.0f}%" if job is not None and job.state == "running" else
                         " · 물리 실패 (기구학 표시)")
            else:
                note = self.fall_note(src, local)
                text += f" · 물리 · {note}" if note else " · 물리"
        if h.get("label_text") != text:  # one message less per robot per frame
            h["label"].text = h["label_text"] = text
        balance = self._pose_balance(item, src.balance, local, R, shift)
        sticks = None
        if "bones" in h and show_h:
            hm = item.human
            hips = hm.positions[0, 0]
            start_r = item.robot.root_pos[0]

            def to_display(P: np.ndarray) -> np.ndarray:
                # scale about the skeleton's start point (floor level), then put that point on the robot's start
                Ps = h["scale"] * (P - np.array([hips[0], hips[1], 0.0])) + np.array([start_r[0], start_r[1], 0.0])
                Pd = Ps @ R.T + shift
                if v.human_beside:  # inside the robot the lines are hidden by its meshes
                    Pd = Pd + np.array([0.0, 0.8, 0.0])
                return Pd

            if mesh is not None:
                rig = h["rig"]
                f = int(np.clip(round(local * rig.fps), 0, rig.num_frames - 1))
                key = (f, v.human_beside, *np.round(R, 6).ravel(), *np.round(shift, 6))
                if h.get("mesh_key") != key:  # ~130 KB per update: only when the pose or placement changes
                    h["mesh_key"] = key
                    mesh.vertices = to_display(rig.vertices(f)).astype(np.float32)
            else:
                f = int(np.clip(round(local * hm.fps), 0, hm.num_frames - 1))
                Pd = to_display(hm.positions[f])
                b = h["bones"]
                sticks = np.nan_to_num(np.stack([Pd[b[:, 0]], Pd[b[:, 1]]], axis=1))
        return T_base, cfg, sticks, balance

    def _pose_balance(self, item: Item, b, local: float, R: np.ndarray, shift: np.ndarray):
        """Support polygon (8 edges), CoM projection and ZMP of the frame (BalanceTrack b), on
        the floor, in display space; None when not shown."""
        if not (self.view.show_balance and item.visible and b is not None):
            return None
        f = int(np.clip(round(local * b.fps), 0, len(b.com) - 1))
        hull = b.hulls[f]
        if not len(hull):
            return None
        z = float(b.floor[f]) + 0.004

        def disp(xy: np.ndarray) -> np.ndarray:
            p = np.column_stack([xy, np.full(len(xy), z)])
            return p @ R.T + shift

        ring = disp(np.asarray(hull))
        edges = np.stack([ring, np.roll(ring, -1, axis=0)], 1)[:8] if len(ring) > 2 else np.stack([ring[:1], ring[-1:]], 1)
        pts = np.zeros((8, 2, 3))
        pts[:len(edges)] = edges
        pts[len(edges):] = edges[-1]  # unused segments collapse onto the last edge
        return pts, disp(b.com[f:f + 1, :2])[0], disp(b.zmp[f:f + 1])[0]

    # ---------------------------------------------------------------- physics mode
    @staticmethod
    def is_physics_result(item: Item) -> bool:
        return item.kind.startswith("Isaac PhysX")

    def set_physics(self, on: bool, why: str = "button") -> None:
        self.log(f"physics mode {'on' if on else 'off'} ({why})")
        self.physics_on = bool(on)
        self._physics_changed()

    def set_assist(self, assist: float) -> None:
        self.assist = float(assist)
        self._physics_changed()

    def _physics_changed(self) -> None:
        for it in list(self.items):
            self._request_physics(it)
        self.emit("status")

    def _request_physics(self, item: Item) -> None:
        """Start (or find) the physics run of this motion for the current harness setting."""
        if not self.physics_on or self.is_physics_result(item):
            return
        assist = self.assist
        jobs = item.handles.setdefault("phys_jobs", {})
        if assist in item.handles.setdefault("phys", {}) or (assist in jobs and jobs[assist].state not in
                                                               ("failed", "cancelled")):
            return
        try:
            jobs[assist] = self.runner.request(item.robot, assist, on_done=lambda j, it=item: self._physics_done(it, j))
            self.phys_error = ""
        except Exception as e:  # Isaac Sim not found
            self.phys_error = f"{type(e).__name__}: {e}"
            self.log(f"physics unavailable: {self.phys_error}")
        self.emit("status")

    def _physics_done(self, item: Item, job: PhysicsJob) -> None:
        """Worker thread: load the simulated motion as the item's physics view."""
        if job.state == "done":
            try:
                phys = load_item(job.result, log=None)
                compute_metrics(phys, self.fk, self.limits)
            except Exception as e:
                job.state, job.stage, job.message = "failed", "실패", f"결과를 읽지 못함: {type(e).__name__}: {e}"
            else:
                with self.lock:
                    if item not in self.items:
                        return
                    phys.handles["map"] = self._joint_map(phys.robot)
                    item.handles.setdefault("phys", {})[job.assist] = phys
                self.emit("item", item)
        self.emit("status")

    def cancel_jobs(self) -> None:
        """Stop every queued or running Isaac job (physics runs and videos)."""
        for it in list(self.items):
            for job in [*it.handles.get("phys_jobs", {}).values(), it.handles.get("video_job")]:
                if job is not None and job.active:
                    self.runner.cancel(job)
        self.emit("status")

    def shown(self, item: Item) -> Item:
        """What is drawn and measured for this motion: its physics result in physics mode
        (once computed), else the motion itself."""
        if self.physics_on:
            phys = item.handles.get("phys", {}).get(self.assist)
            if phys is not None:
                return phys
        return item

    def job_text(self, item: Item) -> str:
        """One-line physics state of a motion."""
        if self.is_physics_result(item):
            return "이미 물리 결과입니다"
        phys = item.handles.get("phys", {}).get(self.assist)
        if phys is not None:
            m = phys.metrics
            return (f"완료 · 넘어짐 {m.get('phys_falls', '-')} · 보조 힘 {m.get('phys_harness_pct', 0):.0f}% 체중 · "
                    f"토크 한계 초과 {m.get('phys_saturated_pct', 0):.1f}%")
        job = item.handles.get("phys_jobs", {}).get(self.assist)
        if job is None:
            return f"실행할 수 없음: {self.phys_error}" if self.phys_error else "아직 계산 안 함"
        if job.state == "running":
            el = time.time() - job.started
            eta = f", 약 {el / job.progress * (1 - job.progress):.0f}초 남음" if job.progress > 0.4 else ""
            return f"{job.stage} {100 * job.progress:.0f}% ({el:.0f}초{eta})"
        if job.state == "queued":
            return "대기 중"
        return f"{job.stage}: {job.message}" if job.message and job.message != job.stage else job.stage

    def jobs_summary(self) -> str:
        """'물리 계산 1개 · 동영상 2개' for the jobs queued or running, '' when idle."""
        phys = sum(1 for it in list(self.items) for j in it.handles.get("phys_jobs", {}).values() if j.active)
        vids = sum(1 for it in list(self.items) if (j := it.handles.get("video_job")) is not None and j.active)
        parts = ([f"물리 계산 {phys}개"] if phys else []) + ([f"동영상 {vids}개"] if vids else [])
        return " · ".join(parts)

    def fall_note(self, phys: Item, local: float) -> str:
        """'넘어짐 2.07s · 발끝 걸림 1.47s부터' from the first cause's onset until shortly after the fall."""
        for d in (phys.info.get("physics", {}).get("fall_diagnosis") or []):
            t, onset = d.get("fall_time_s", 0.0), d.get("primary_onset_s")
            start = onset if onset is not None else t
            if start <= local <= t + 0.5:
                cause = CAUSE_KO.get(d.get("primary_cause"), d.get("primary_cause") or "미상")
                return f"넘어짐 {t:.2f}s · {cause} {start:.2f}s부터"
        for t in phys.info.get("physics", {}).get("fall_times_s") or []:
            if t <= local <= t + 0.5:
                return f"넘어짐 {t:.2f}s"
        return ""

    def falls(self, item: Item) -> list[tuple[float, str]]:
        """(time, first cause) of each fall in what is shown for this motion."""
        src = self.shown(item)
        p = src.info.get("physics", {})
        diag = {round(d.get("fall_time_s", 0.0), 3): d.get("primary_cause") for d in p.get("fall_diagnosis") or []}
        return [(t, CAUSE_KO.get(diag.get(round(t, 3)), "")) for t in p.get("fall_times_s") or []]

    # ---------------------------------------------------------------- video
    def save_video(self, item: Item) -> PhysicsJob:
        """Queue an Isaac recording of this motion (its physics result in physics mode);
        raises when Isaac Sim is not found."""
        physics = self.physics_on and not self.is_physics_result(item)
        mode = f"physics_x{self.assist:g}" if physics else "kinematic"
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.label).strip("_") or "motion"
        path = os.path.join(self.opts.video_dir, f"{stem}_{mode}.mp4")
        human = item.source if item.human is not None else None
        motion = replace(item.robot, name=stem)  # the video caption shows this name, not the cache file's
        job = self.runner.request_video(motion, path, human=human, physics=physics, assist=self.assist,
                                        smpl_model_dir=self.opts.smpl_model_dir,
                                        on_done=lambda j, it=item: self._video_done(it, j))
        item.handles["video_job"] = job
        self.log(f"video {'queued' if job.active else 'exists'}: {item.label} "
                 f"({'physics x' + format(self.assist, 'g') if physics else 'kinematic'})")
        self.emit("item", item)
        self.emit("status")
        return job

    def _video_done(self, item: Item, job: PhysicsJob) -> None:
        self.emit("item", item)
        self.emit("status")

    def video_text(self, item: Item) -> str:
        job = item.handles.get("video_job")
        if job is None:
            return ""
        if job.state == "done":
            return f"동영상 저장됨: {rel(job.result)}"
        if job.state == "running":
            return f"동영상: {job.stage} {100 * job.progress:.0f}% ({time.time() - job.started:.0f}초)"
        if job.state == "queued":
            return "동영상: 대기 중 (Isaac 작업은 한 번에 하나씩 돕니다)"
        return f"동영상: {job.stage}" + (f": {job.message}" if job.message and job.message != job.stage else "")

    def video_file(self, item: Item) -> str | None:
        job = item.handles.get("video_job")
        return job.result if job is not None and job.state == "done" and job.result else None

    # ---------------------------------------------------------------- describing items
    def item_facts(self, item: Item) -> list[tuple[str, str]]:
        """(label, value) rows about a motion, for inspectors."""
        m, r = item.metrics, item.robot
        rows = [("종류", item.kind), ("파일", rel(item.source)),
                ("길이", f"{r.num_frames} frames @ {r.fps:g} fps, {r.duration:.1f} s"), ("QC", str(m.get("qc", "?")))]
        res = item.info.get("ik_position_residual")
        if res:
            rows.append(("IK 잔차(평균)", ", ".join(f"{k} {v['mean_cm']} cm" for k, v in res.items())))
        if m.get("phys_ok"):
            rows.append(("물리 결과", f"{m['phys_ok']} · 보조 힘 {m['phys_harness_pct']:.0f}% 체중 · 넘어짐 "
                                    f"{m['phys_falls']} · 토크 한계 초과 {m['phys_saturated_pct']:.1f}%"))
        if self.is_physics_result(item):
            ref = item.info.get("reference_motion")
            rows.append(("참고", "이미 Isaac 물리 결과인 파일이라 물리 모드를 켜고 꺼도 그대로이고, 로봇 관절각만 있어 사람 "
                                 "스켈레톤이 없습니다. 사람과 나란히 보려면 원본 사람 모션을 추가하고 물리 모드를 켜세요."
                                 + (f" 원래 로봇 동작: {rel(ref)}" if ref else "")))
        return rows

    # ---------------------------------------------------------------- analysis
    def graph_keys(self) -> list[str]:
        joints = analysis.common_joints(*[it.robot for it in self.items]) if self.items else []
        return list(GRAPH_FIXED) + list(joints)

    def series(self, key: str, window: float = 0.0) -> list[tuple[Item, np.ndarray, np.ndarray]]:
        """(item, time, value) per motion for a graph key, around the current time when window > 0."""
        lo, hi = (self.t - window / 2, self.t + window / 2) if window > 0 else (-np.inf, np.inf)
        out = []
        for it in list(self.items):
            r = self.shown(it).robot
            tt = it.offset + np.arange(r.num_frames) / r.fps
            if key == GRAPH_FIXED[0]:
                y = r.root_pos[:, 2]
            elif key == GRAPH_FIXED[1]:
                v = np.linalg.norm(np.diff(r.root_pos[:, :2], axis=0), axis=1) * r.fps
                y = np.concatenate([v[:1], v])
            elif key in r.joint_names:
                y = np.degrees(r.dof_pos[:, r.joint_names.index(key)])
            else:
                continue
            sel = (tt >= lo) & (tt <= hi)
            out.append((it, tt[sel], y[sel]))
        return out

    def metric_table(self, ref: Item | None) -> tuple[list[str], list[tuple[Item, list[str]]]]:
        """Row labels and, per motion, its formatted values (physics results in physics mode)."""

        def f(v, fmt):
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                return "-"
            return fmt.format(v)

        names = ["재생 방식"] + [r[0] for r in METRIC_ROWS[:11]] + ["기준 대비 다리 RMSE (°)", "기준 대비 전체 RMSE (°)"] \
            + [r[0] for r in METRIC_ROWS[11:]]
        cols = []
        for it in list(self.items):
            shown = self.shown(it)
            m = shown.metrics
            legs = whole = "기준" if it is ref else "-"
            if ref is not None and it is not ref:
                joints, rmse, ov = analysis.joint_rmse(self.shown(ref).robot, shown.robot, ref.offset, it.offset)
                if ov > 0:
                    li = [i for i, n in enumerate(joints) if any(k in n for k in analysis.LEG_KEYS)]
                    legs, whole = f(float(np.median(rmse[li])), "{:.1f}"), f(float(np.median(rmse)), "{:.1f}")
            mode = (f"물리 x{shown.info['physics'].get('harness_scale', 1):g}" if self.is_physics_result(shown)
                    else "기구학")
            vals = [mode] + [f(m.get(k), fmt) for _, k, fmt in METRIC_ROWS[:11]] + [legs, whole] \
                + [f(m.get(k), fmt) for _, k, fmt in METRIC_ROWS[11:]]
            cols.append((it, vals))
        return names, cols

    def joint_rmse(self, ref: Item) -> list[tuple[Item, list[str], np.ndarray]]:
        out = []
        for it in list(self.items):
            if it is ref:
                continue
            joints, rmse, ov = analysis.joint_rmse(self.shown(ref).robot, self.shown(it).robot, ref.offset, it.offset)
            if ov > 0:
                out.append((it, list(joints), rmse))
        return out

    def auto_align(self, ref: Item) -> list[str]:
        """Time offsets that best match every motion's legs to the reference's."""
        notes = []
        for it in list(self.items):
            if it is ref:
                continue
            off, rms = analysis.estimate_offset(ref.robot, it.robot, max_shift=float(self.opts.max_shift))
            it.offset = ref.offset + off
            notes.append(f"{it.label}: {it.offset:+.3f} s (다리 RMS {rms:.1f}°)")
            self.emit("item", it)
        return notes
