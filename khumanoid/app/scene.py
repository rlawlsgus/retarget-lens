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

from .. import analysis, paths, policy_runner, settings
from ..compare import Item, compute_metrics, load_item
from ..diagnosis import CAUSE_KO
from ..io import urdf_joint_limits
from ..physics_runner import PHYSICS_CONFIG, PhysicsJob, PhysicsRunner
from ..rotations import quat_mul, quat_to_matrix
from .robots import REGIONS, OverlayBatch, RobotBatch, align_on_pelvis, set_props

ROOT = paths.REPO_ROOT
DEFAULT_URDF = paths.robot_urdf()  # dev: ..\GMR\assets\unitree_g1\...; installed: shipped with the program
PHYSICS_CACHE = paths.cache_dir("physics")
POLICY_CACHE = paths.cache_dir("policy")
VIDEO_DIR = paths.video_dir()
# 균형 제어 in physics mode: Isaac PhysX with the pelvis harness (its scale: MotionScene.assist), or
# MuJoCo with no controller / with GMT's tracking policy (khumanoid/policy_runner.py)
BALANCE = {"isaac": "보조 힘 (Isaac)", "pd": "없음 (MuJoCo)", "gmt": "추적 정책 (GMT)"}
BALANCE_TAG = {"pd": "MuJoCo 제어 없음", "gmt": "GMT"}  # in the robots' labels
# 리타게팅 보정 (MotionScene.set_retarget) as the front ends offer it
SWING_CLEARANCE_CM = 2.0  # the recommended swing clearance (docs/pipeline.md)
RETARGET_NOTE = "다음에 여는 사람 모션부터 적용됩니다. 이미 연 모션은 그대로라, 같은 파일을 다시 열면 보정 전후를 나란히 봅니다"
RETARGET_TIPS = {
    "foot_flat": "서 있는 발의 발바닥을 바닥과 평평하게 맞춥니다(발목 pitch·roll만, 움직이는 발은 그대로). CMU 143번처럼 "
                 "발끝이 들린 채 뒤꿈치로만 서는 리타겟용이고, 뒤꿈치가 0.5–2 cm 뜰 수 있습니다",
    "swing": f"바닥을 스치는 스윙 발을 바닥에서 {SWING_CLEARANCE_CM:g} cm 이상 띄웁니다(권장 설정). 물리에서 발끝이 걸려 "
             "넘어지는 것을 줄입니다",
}
FALL_RULE_KO = {"tilt": "기울어짐", "low": "골반 낮음", "drop": "원본보다 낮음"}  # policy_replay's fall rules
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
    ("물리: 몸 위치 오차 (cm)", "phys_body_error_cm", "{:.1f}"),
    ("물리: 토크 한계 초과 (%)", "phys_saturated_pct", "{:.1f}"), ("물리 판정", "phys_ok", "{}"),
]
METRIC_NOTES = (
    "RMSE: 기준과 겹치는 구간의 관절별 RMSE 중앙값(시간 오프셋 반영). 발 미끄러짐: 발바닥 전체가 붙은 채 0.3 m/s 이상으로 "
    "0.1 s 이상 움직인 프레임 비율. 바닥 관통: 발 최저점 -2 cm 아래 프레임 비율. 스윙 발 바닥 근접: 가장 느린 발바닥 점까지 "
    "0.5 m/s 넘게 움직이는 발이 그때의 바닥(디딤발 높이를 따라감) 1 cm 안을 지나는 비율(물리에서 발끝이 걸림). 물리 행: "
    "시뮬레이션 결과(물리 모드, 또는 isaac_replay.py --physics / policy_replay.py 결과 파일)만 - 골반 보조 힘 평균(체중 대비, "
    "MuJoCo는 0), 넘어짐 수, 몸 위치 오차(MuJoCo만), 관절 토크 한계를 넘은 비율. 물리 모드에서는 다른 행도 시뮬레이션된 "
    "동작으로 잽니다.")
# Every row of metric_table, by topic, with what it measures (the editor shows these on hover).
METRIC_HELP = [
    ("기본", [
        ("재생 방식", "기구학 = 리타게팅 결과를 그대로 재생합니다. 물리 x1 = Isaac PhysX로 시뮬레이션한 결과이고, "
                   "x 뒤 숫자는 골반 보조 힘 배율입니다(x0 = 보조 없음). MuJoCo · 없음 / GMT = MuJoCo에서 제어기 없이(개루프 PD) "
                   "또는 GMT 추적 정책으로 보조 힘 없이 시뮬레이션한 결과입니다."),
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
        ("QC", "검증 결과: PASS / WARN / FAIL (docs/pipeline.md의 \"검증(QC) 기준\")."),
    ]),
    ("물리 (시뮬레이션 결과에만)", [
        ("물리: 보조 힘 (체중 %)", "골반을 받쳐 준 보조 힘의 평균, 체중 대비. MuJoCo(균형 제어 없음·GMT)는 보조 힘이 없어 0입니다."),
        ("물리: 넘어짐", "시뮬레이션에서 넘어진 횟수(클립 안). 넘어지면 그 시각의 원본 자세로 다시 시작해 셉니다."),
        ("물리: 몸 위치 오차 (cm)", "MuJoCo 결과만: 골반 기준 몸통·무릎·발목·팔꿈치·손 위치가 원본과 다른 정도의 평균. "
                              "추적 정책은 관절을 바꿔서라도 몸을 원본 자리에 두려 하므로, 관절 RMSE보다 이 값이 따라간 정도를 잘 보여 줍니다."),
        ("물리: 토크 한계 초과 (%)", "관절 토크가 모터 한계를 넘은 비율(Isaac은 프레임, MuJoCo는 1 ms 스텝)."),
        ("물리 판정", "통과, 또는 걸린 기준들(넘어짐, 보조 힘 과다, 토크 한계 초과 등; MuJoCo는 넘어짐만). 칸에는 첫 항목만 나옵니다."),
    ]),
]
METRIC_HELP_FOOTER = "물리 모드에서는 물리 행 말고 다른 행도 시뮬레이션된 동작으로 잽니다."
METRIC_DESC = {name: desc for _, rows in METRIC_HELP for name, desc in rows}


def rel(path: str) -> str:
    """For display: relative to the repository when inside it (dev layout), else absolute."""
    return paths.rel(path)


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
    foot_flat: bool = False
    swing_clearance_cm: float = 0.0
    fps: float = 30.0
    csv_fps: float = 30.0
    smpl_model_dir: str | None = None
    max_shift: float = 3.0
    physics_config: str = PHYSICS_CONFIG
    isaac_accept_eula: bool = False
    video_dir: str = VIDEO_DIR
    library: list | None = None
    balance: str = "isaac"  # 균형 제어 in physics mode (BALANCE)


def add_scene_arguments(ap) -> None:
    """Command-line options shared by the browser viewer and the desktop editor."""
    ap.add_argument("inputs", nargs="*", help="motion files (human ones are retargeted)")
    ap.add_argument("--robot", default="unitree_g1", help="GMR robot for retargeting (default unitree_g1)")
    ap.add_argument("--urdf", default=DEFAULT_URDF, help="robot URDF for display")
    ap.add_argument("--smooth", type=float, default=6.0, help="smoothing for retargeted inputs (Hz, 0 = off)")
    ap.add_argument("--foot-flat", action="store_true",
                    help="retargeted inputs: turn the soles of feet standing still parallel to the floor "
                         "(for retargets that stand on their heels, CMU subject 143)")
    ap.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM",
                    help="lift swing feet of retargeted inputs to at least CM off the floor (0 = off; 2 recommended)")
    ap.add_argument("--fps", type=float, default=30.0, help="retarget output frame rate")
    ap.add_argument("--csv-fps", type=float, default=30.0, help="frame rate of Unitree csv files")
    ap.add_argument("--smpl-model-dir", default=None,
                    help="folder holding smplx/SMPLX_*.npz (default: 환경 설정, $SMPL_MODEL_DIR, models/ in the repository)")
    ap.add_argument("--max-shift", type=float, default=3.0, help="search range of the automatic time alignment (s)")
    ap.add_argument("--mesh-cell", type=float, default=0.004,
                    help="simplify robot meshes on this grid (m) before sending them to the browser; 0 = full detail")
    ap.add_argument("--body-mesh", action="store_true", help="draw SMPL-X inputs as body meshes from the start")
    ap.add_argument("--library", action="append", default=None, metavar="DIR",
                    help="folder to list in the motion picker (repeatable; default: data/raw, data/samples, "
                         "data/retargeted, data/uploads, reports and the 환경 설정 folders)")
    ap.add_argument("--physics", action="store_true", help="start in physics mode")
    ap.add_argument("--balance", choices=tuple(BALANCE), default="isaac",
                    help="physics mode's balance control: isaac = Isaac PhysX with the pelvis harness (default), "
                         "pd = MuJoCo with no controller, gmt = MuJoCo with GMT's tracking policy")
    ap.add_argument("--video-dir", default=None, help="where \"동영상 저장\" writes its MP4s (default: 환경 설정, "
                                                      "else reports/videos/viewer)")
    ap.add_argument("--physics-config", default=PHYSICS_CONFIG, help="PhysX settings for physics mode (yaml)")
    ap.add_argument("--isaac-accept-eula", action="store_true",
                    help="you accept the NVIDIA Omniverse EULA; physics mode runs Isaac Sim with OMNI_KIT_ACCEPT_EULA=YES")


def scene_options(args) -> SceneOptions:
    """Options from the command line; what it leaves out comes from 환경 설정 (khumanoid.settings)."""
    s = settings.load()
    smpl = args.smpl_model_dir or settings.find_smpl(s).path or paths.smpl_model_dir()
    return SceneOptions(robot=args.robot, urdf=args.urdf, smooth=args.smooth, foot_flat=getattr(args, "foot_flat", False),
                        swing_clearance_cm=args.swing_clearance, fps=args.fps, csv_fps=args.csv_fps, smpl_model_dir=smpl, max_shift=args.max_shift,
                        physics_config=args.physics_config, isaac_accept_eula=args.isaac_accept_eula,
                        video_dir=args.video_dir or settings.video_dir(s), library=args.library,
                        balance=getattr(args, "balance", "isaac"))


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


GHOST_COLOR = (200, 206, 218)  # the reference motion in an overlay comparison
DIFF_COLORS = ((245, 205, 40), (240, 130, 30), (220, 40, 35))  # at 1x, 2x, 3x the tolerance


@dataclass
class CompareSettings:
    """겹쳐 비교: motion B is drawn on motion A's pelvis (moved there, and turned to A's pelvis
    heading when `heading`). A is a translucent ghost; of B only the parts more than tol_cm
    away from A's are drawn, coloured yellow (tol) -> orange (2 tol) -> red (3 tol and more).
    The pair's skeletons and balance marks are hidden meanwhile."""
    on: bool = False
    ref: Item | None = None  # A
    item: Item | None = None  # B
    heading: bool = True
    tol_cm: float = 3.0
    ghost_opacity: float = 0.3

    def key(self) -> tuple:
        return self.on, id(self.ref), id(self.item), self.heading, self.tol_cm, self.ghost_opacity


def diff_colors(d_cm: np.ndarray, tol_cm: float) -> np.ndarray:
    """(n,) deviations (cm) -> (n, 3) uint8: yellow at the tolerance, orange at 2x, red from 3x."""
    x = np.clip((np.asarray(d_cm, dtype=np.float64) - tol_cm) / max(2.0 * tol_cm, 1e-6), 0.0, 1.0)[:, None]
    lo, mid, hi = (np.array(c, dtype=np.float64) for c in DIFF_COLORS)
    c = np.where(x < 0.5, lo + (mid - lo) * (x / 0.5), mid + (hi - mid) * ((x - 0.5) / 0.5))
    return np.round(c).astype(np.uint8)


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
        self.balance = self.opts.balance if self.opts.balance in BALANCE else "isaac"
        self._phys_errors: dict = {}  # per phys_key: why its runs cannot start
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
        self.policy = policy_runner.PolicyRunner(POLICY_CACHE, physics_config=self.opts.physics_config, log=self.log)
        self.robots = RobotBatch(server, urdf)  # every robot's meshes, posed together each tick
        self.overlays = OverlayBatch(server)  # skeletons, support polygons, CoM / ZMP of all motions
        self.compare = CompareSettings()
        self.compare_now: dict | None = None  # the drawn frame's difference (set by tick)
        self._compare_cache: tuple = (None, None)
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
                         foot_flat=o.foot_flat, log=self.log)
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
                    self._cancel(job)
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
            if item in (self.compare.ref, self.compare.item):
                self.compare.on = False
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
        """Robot meshes and overlays: one instance per motion, in list order, in its colour
        (the reference of an overlay comparison as a translucent ghost)."""
        colors = [it.color for it in self.items]
        base = 0.45 if self.view.robot_translucent else 1.0
        opacities = None
        pair = self.compare_pair()
        if pair is not None:
            colors[pair[0]] = GHOST_COLOR
            opacities = [base] * len(colors)
            opacities[pair[0]] = min(base, self.compare.ghost_opacity)
        self.robots.set_instances(colors, base, opacities)
        self.overlays.sync([len(it.handles.get("bones", ())) for it in self.items], [it.color for it in self.items])

    # ---------------------------------------------------------------- overlay comparison
    def compare_pair(self) -> tuple[int, int] | None:
        """(index of A, index of B) while an overlay comparison is on."""
        c = self.compare
        if not c.on or c.ref is None or c.item is None or c.ref is c.item:
            return None
        try:
            return self.items.index(c.ref), self.items.index(c.item)
        except ValueError:
            return None

    def compare_role(self, item: Item) -> str | None:
        pair = self.compare_pair()
        if pair is None:
            return None
        return "A" if item is self.items[pair[0]] else "B" if item is self.items[pair[1]] else None

    def set_compare(self, on: bool | None = None, ref: Item | None = None, item: Item | None = None,
                    heading: bool | None = None, tol_cm: float | None = None) -> None:
        """Change the overlay comparison; arguments left None stay as they are. Turning it on
        without a valid pair picks one (A: the first motion, B: the first other one)."""
        with self.lock:
            c = self.compare
            if ref is not None:
                c.ref = ref
            if item is not None:
                c.item = item
            if heading is not None:
                c.heading = bool(heading)
            if tol_cm is not None:
                c.tol_cm = max(0.1, float(tol_cm))
            if on is not None:
                c.on = bool(on)
            if c.on:
                if c.ref not in self.items:
                    c.ref = self.items[0] if self.items else None
                if c.item not in self.items or c.item is c.ref:
                    c.item = next((it for it in self.items if it is not c.ref), None)
                if c.ref is None or c.item is None:
                    c.on = False
                    self.log("겹쳐 비교: 모션이 두 개 이상 있어야 합니다")
            self._sync_robots()
        self.emit("compare")

    def _compare_frame(self, T_base: np.ndarray, cfg: np.ndarray, visible: np.ndarray, pair) -> None:
        """Draw the frame with B on A's pelvis and B's parts that differ coloured."""
        a, b = pair
        c = self.compare
        T_base = T_base.copy()
        T_base[b] = align_on_pelvis(T_base[a], T_base[b], c.heading)
        T = self.robots.forward(T_base, cfg)
        dev = self.robots.part_deviation(T[:, [a]], T[:, [b]])[0] * 100.0  # cm per part
        n, K = len(T_base), len(dev)
        part_visible = np.ones((K, n), bool)
        part_visible[:, b] = dev > c.tol_cm
        colors = np.broadcast_to(np.array(self.robots.colors, np.uint8)[None], (K, n, 3)).copy()
        colors[:, b] = diff_colors(dev, c.tol_cm)
        self.robots.send(T, visible, part_visible, colors)
        regions = {r: float(max(d for d, g in zip(dev, self.robots.part_regions) if g == r))
                   for r in REGIONS if r in self.robots.part_regions}
        worst = max(regions, key=regions.get) if regions else None
        self.compare_now = {"mean": float(dev.mean()), "regions": regions, "worst": worst,
                            "over": int((dev > c.tol_cm).sum()), "parts": K}
        lab = self.items[b].handles.get("label")
        if lab is not None:  # above A's label, where B is drawn
            lab.position = T_base[a][:3, 3] + np.array([0.0, 0.0, 1.05])

    def _poses_at(self, item: Item, src: Item, local: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Base transforms (F, 4, 4) in display space and robot-model joint values (F, joints)
        of a motion at local times, as _pose draws them."""
        pos, quat = analysis.sample_root(src.robot, local)
        dof = analysis.sample_dof(src.robot, local)
        qd, shift = self._display_transform(item)
        R = quat_to_matrix(qd)
        T = np.tile(np.eye(4), (len(local), 1, 1))
        T[:, :3, :3] = R @ quat_to_matrix(quat)
        T[:, :3, 3] = pos @ R.T + shift
        jmap = src.handles.get("map", item.handles["map"])
        cfg = np.stack([dof[:, i] if i is not None else np.zeros(len(local)) for i in jmap], axis=1)
        return T, cfg

    def compare_series(self, fps: float = 30.0) -> dict | None:
        """The comparison over the whole stretch where both motions play (B on A's pelvis as
        drawn): {"t": (F,) timeline s, "parts": (F, parts) cm, "mean": (F,) cm, "regions":
        {region: (F,) cm, the region's largest part}}; None without a comparison. Cached."""
        pair = self.compare_pair()
        if pair is None:
            return None
        A, B = self.items[pair[0]], self.items[pair[1]]
        sa, sb = self.shown(A), self.shown(B)
        key = (id(A), id(B), A.offset, B.offset, self.compare.heading, id(sa), id(sb), self.view.align, fps)
        if self._compare_cache[0] == key:
            return self._compare_cache[1]
        lo = max(A.offset, B.offset)
        hi = min(A.offset + sa.robot.duration, B.offset + sb.robot.duration)
        t = np.arange(lo, hi, 1.0 / fps) if hi > lo else np.zeros(0)
        out = {"t": t, "parts": np.zeros((len(t), len(self.robots.meshes))), "mean": np.zeros(len(t)),
               "regions": {}}
        if len(t):
            TA, ca = self._poses_at(A, sa, t - A.offset)
            TB, cb = self._poses_at(B, sb, t - B.offset)
            TB = align_on_pelvis(TA, TB, self.compare.heading)
            dev = self.robots.part_deviation(self.robots.forward(TA, ca), self.robots.forward(TB, cb)) * 100.0
            out["parts"], out["mean"] = dev, dev.mean(1)
            for r in REGIONS:
                idx = [k for k, g in enumerate(self.robots.part_regions) if g == r]
                if idx:
                    out["regions"][r] = dev[:, idx].max(1)
        self._compare_cache = (key, out)
        return out

    def compare_table(self) -> list[tuple[str, str, str, str, str]]:
        """Per region over the shared stretch: (region, mean cm, max cm, time of the max, % of
        frames beyond the tolerance)."""
        s = self.compare_series()
        if s is None or not len(s["t"]):
            return []
        tol = self.compare.tol_cm
        rows = [("전체 (부위 평균)", s["mean"])] + list(s["regions"].items())
        return [(name, f"{v.mean():.1f}", f"{v.max():.1f}", f"{s['t'][int(np.argmax(v))]:.2f}",
                 f"{100 * float((v > tol).mean()):.0f}") for name, v in rows]

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
            hm = item.human
            item.handles["scale"] = human_scale(item)
            bones = hm.meta.get("bones", []) if hm.kind == "markers" else hm.bones()
            item.handles["bones"] = np.array(bones, dtype=int).reshape(-1, 2)
            root = hm.positions[:, 0]
            ok = np.isfinite(root).all(axis=1)
            item.handles["anchor"] = root[int(np.argmax(ok))].copy() if ok.any() else np.zeros(3)  # first seen pelvis
            if hm.kind == "markers":  # C3D: every placed marker as a dot, besides the marker-set sticks
                item.handles["dots"] = np.array(hm.meta.get("dots") or range(1, len(hm.joint_names)), dtype=int)
                item.handles["markers"] = s.scene.add_point_cloud(
                    f"{node}/markers", np.zeros((1, 3), np.float32), np.array(item.color, np.uint8), point_size=0.022,
                    point_shape="circle", precision="float32", point_shading="flat")
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

    def apply_settings(self, s: settings.Settings) -> None:
        """Saved 환경 설정 take effect at once: the SMPL-X model folder and the video folder.
        Isaac Sim and Blender are looked up when a job / an FBX needs them."""
        self.opts.smpl_model_dir = settings.find_smpl(s).path or self.opts.smpl_model_dir
        self.opts.video_dir = settings.video_dir(s)
        self.emit("status")

    def retarget_settings(self) -> dict:
        """How human motions opened from now on are retargeted (each motion keeps its own, Item.retarget)."""
        o = self.opts
        return {"smooth_hz": o.smooth, "foot_flat": o.foot_flat, "swing_clearance_cm": o.swing_clearance_cm}

    def set_retarget(self, foot_flat: bool | None = None, swing_clearance_cm: float | None = None) -> dict:
        """리타게팅 보정 for the human motions opened from now on: 디딤발 평평 (foot_flat) and
        스윙 발 보정 (swing_clearance_cm, 0 = off). Open motions keep how they were made, so opening
        the same file again shows the two side by side."""
        if foot_flat is not None:
            self.opts.foot_flat = bool(foot_flat)
        if swing_clearance_cm is not None:
            if not 0.0 <= float(swing_clearance_cm) <= 10.0:
                raise ValueError("swing_clearance_cm must be 0 (off) to 10")
            self.opts.swing_clearance_cm = float(swing_clearance_cm)
        r = self.retarget_settings()
        self.log(f"retarget settings for motions opened next: foot-flat {'on' if r['foot_flat'] else 'off'}, "
                 f"swing clearance {r['swing_clearance_cm']:g} cm")
        self.emit("status")
        return r

    # ---------------------------------------------------------------- playback
    def time_range(self) -> tuple[float, float]:
        end = max([it.offset + self.shown(it).robot.duration for it in self.items] or [1.0])  # MuJoCo: + the hold
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
        key = (self.t, self.physics_on, self.phys_key, self._version, astuple(self.view), self.compare.key(),
               tuple((id(it), it.visible, it.show_human, it.offset) for it in self.items))
        now = time.perf_counter()
        if key == self._drawn_key and not (self.jobs_busy() and now - self._drawn_at > 0.5):
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
            pair = self.compare_pair()
            if pair is not None and visible[pair[0]] and visible[pair[1]]:
                self._compare_frame(T_base, cfg, visible, pair)
            else:
                self.robots.update(T_base, cfg, visible)
                self.compare_now = None
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
        role = self.compare_role(item)
        self._set_visible(item, "label", visible and bool(v.show_labels))
        # in an overlay comparison the two robots are the picture: their skeletons, bodies and balance stay hidden
        show_h = visible and item.show_human and bool(v.show_humans) and role is None
        mesh = h.get("mesh") if v.body_mesh else None
        self._set_visible(item, "mesh", show_h and mesh is not None)
        self._set_visible(item, "markers", show_h)
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
        elif self.is_policy_result(item):
            note = self.fall_note(item, local)
            text += " · MuJoCo 재생 결과" + (f" · {note}" if note else "")
        elif self.physics_on:
            if src is item:  # not computed yet: still the joint angles
                job = h.get("phys_jobs", {}).get(self.phys_key)
                text += (" · 물리 대기" if job is not None and job.state == "queued" else
                         f" · 물리 계산 {100 * job.progress:.0f}%" if job is not None and job.state == "running" else
                         " · 물리 실패 (기구학 표시)")
            else:
                note = self.fall_note(src, local)
                text += self._result_tag(src) + (f" · {note}" if note else "")
        if role is not None:
            text += " · 비교 기준 (반투명)" if role == "A" else " · 비교 대상 (벗어난 부위만 색칠)"
        if h.get("label_text") != text:  # one message less per robot per frame
            h["label"].text = h["label_text"] = text
        balance = self._pose_balance(item, src.balance, local, R, shift) if role is None else None
        sticks = None
        if "bones" in h and show_h:
            hm = item.human
            hips = h["anchor"]
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
                sticks = np.stack([Pd[b[:, 0]], Pd[b[:, 1]]], axis=1)
                seen = Pd[np.isfinite(Pd).all(axis=1)]
                bad = ~np.isfinite(sticks).all(axis=(1, 2))
                if bad.any():  # a missing marker / joint: no stick (one to the origin would cross the scene)
                    sticks[bad] = seen[0] if len(seen) else 0.0
                if "markers" in h:  # placed markers only (not the virtual pelvis); occluded ones are left out
                    dots = Pd[h["dots"]]
                    dots = dots[np.isfinite(dots).all(axis=1)]
                    set_props(h["markers"], points=(dots if len(dots) else seen[:1] if len(seen) else
                                                    np.zeros((1, 3))).astype(np.float32))
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
        """An Isaac PhysX result file (tools/isaac_replay.py --physics)."""
        return item.kind.startswith("Isaac PhysX")

    @staticmethod
    def is_policy_result(item: Item) -> bool:
        """A MuJoCo balance on / off result (tools/policy_replay.py): already simulated too."""
        return "policy_replay" in item.info

    def is_sim_result(self, item: Item) -> bool:
        return self.is_physics_result(item) or self.is_policy_result(item)

    def set_physics(self, on: bool, why: str = "button") -> None:
        self.log(f"physics mode {'on' if on else 'off'} ({why})")
        self.physics_on = bool(on)
        self._physics_changed()

    def set_assist(self, assist: float) -> None:
        self.assist = float(assist)
        self._physics_changed()

    def set_balance(self, mode: str) -> None:
        """균형 제어 (BALANCE): Isaac with the harness, or MuJoCo with no controller / GMT. Each
        motion keeps the results of every mode, so switching back is instant."""
        if mode not in BALANCE:
            raise ValueError(f"balance must be one of {tuple(BALANCE)}")
        self.log(f"balance control: {BALANCE[mode]}")
        self.balance = mode
        self._physics_changed()

    @property
    def phys_key(self):
        """Which result physics mode shows: the harness scale (Isaac) or the MuJoCo controller."""
        return self.assist if self.balance == "isaac" else self.balance

    @staticmethod
    def key_label(key) -> str:
        return f"보조 힘 x{key:g} (Isaac)" if not isinstance(key, str) else BALANCE[key]

    def mode_label(self) -> str:
        """'보조 힘 x1 (Isaac)', '없음 (MuJoCo)', '추적 정책 (GMT)'."""
        return self.key_label(self.phys_key)

    @property
    def phys_error(self) -> str:
        """Why the current mode's runs cannot start ('' when they can)."""
        return self._phys_errors.get(self.phys_key, "")

    def balance_problem(self, mode: str) -> str:
        """'' when this 균형 제어 can run here, else why not (Isaac: checked when a run starts)."""
        return "" if mode == "isaac" else self.policy.problem(mode)

    def _physics_changed(self) -> None:
        for it in list(self.items):
            self._request_physics(it)
        self.emit("status")

    def _request_physics(self, item: Item) -> None:
        """Start (or find) the physics run of this motion for the current mode (harness setting or
        MuJoCo controller)."""
        if not self.physics_on or self.is_sim_result(item):
            return
        key = self.phys_key
        jobs = item.handles.setdefault("phys_jobs", {})
        if key in item.handles.setdefault("phys", {}) or (key in jobs and jobs[key].state not in
                                                            ("failed", "cancelled")):
            return
        done = lambda j, it=item, k=key: self._physics_done(it, j, k)  # noqa: E731
        try:
            if self.balance == "isaac":
                jobs[key] = self.runner.request(item.robot, key, on_done=done)
            else:
                jobs[key] = self.policy.request(item.robot, key, on_done=done, info={
                    "label": item.label, "kind": item.kind, "source": item.source, **item.retarget})
            self._phys_errors.pop(key, None)
        except Exception as e:  # Isaac Sim / GMT not found
            self._phys_errors[key] = f"{type(e).__name__}: {e}" if self.balance == "isaac" else str(e)
            self.log(f"physics unavailable ({self.key_label(key)}): {self._phys_errors[key]}")
        self.emit("status")

    def _physics_done(self, item: Item, job, key) -> None:
        """Worker thread: load the simulated motion as the item's physics view for this mode."""
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
                    item.handles.setdefault("phys", {})[key] = phys
                self.emit("item", item)
        self.emit("status")

    def _cancel(self, job) -> None:
        (self.policy if job.kind == "policy" else self.runner).cancel(job)

    def cancel_jobs(self) -> None:
        """Stop every queued or running job (Isaac physics runs and videos, MuJoCo runs)."""
        for it in list(self.items):
            for job in [*it.handles.get("phys_jobs", {}).values(), it.handles.get("video_job")]:
                if job is not None and job.active:
                    self._cancel(job)
        self.emit("status")

    def jobs_busy(self) -> bool:
        return self.runner.busy() or self.policy.busy()

    def shutdown(self) -> None:
        """Stop the job workers and any running Isaac process (call on exit)."""
        self.policy.shutdown()
        self.runner.shutdown()

    def shown(self, item: Item) -> Item:
        """What is drawn and measured for this motion: its physics result in physics mode
        (once computed), else the motion itself."""
        if self.physics_on:
            phys = item.handles.get("phys", {}).get(self.phys_key)
            if phys is not None:
                return phys
        return item

    def result_text(self, phys: Item) -> str:
        """'넘어짐 0 · 몸 위치 오차 4.5 cm · ...' of a simulated motion."""
        m = phys.metrics
        pol = phys.info.get("policy_replay")
        if pol:
            hold = f" (+{pol['hold_falls']} 끝난 뒤)" if pol.get("hold_falls") else ""
            err = f"{m['phys_body_error_cm']:.1f}" if m.get("phys_body_error_cm") is not None else "-"
            return (f"넘어짐 {m.get('phys_falls', '-')}{hold} · 몸 위치 오차 {err} cm · "
                    f"토크 한계 초과 {m.get('phys_saturated_pct', 0):.1f}%")
        return (f"넘어짐 {m.get('phys_falls', '-')} · 보조 힘 {m.get('phys_harness_pct', 0):.0f}% 체중 · "
                f"토크 한계 초과 {m.get('phys_saturated_pct', 0):.1f}%")

    def _result_tag(self, phys: Item) -> str:
        """The label's part for a computed physics result."""
        pol = phys.info.get("policy_replay")
        if not pol:
            return " · 물리"
        err = phys.metrics.get("phys_body_error_cm")
        return (f" · {BALANCE_TAG.get(pol.get('controller'), 'MuJoCo')} · 넘어짐 {pol.get('falls', '-')}회"
                + (f" · 몸 오차 {err:.1f} cm" if err is not None else ""))

    def results_overview(self, item: Item) -> list[tuple[str, str]]:
        """(mode, result) for every physics mode computed for this motion so far, Isaac first."""
        phys = item.handles.get("phys", {})
        keys = sorted(phys, key=lambda k: (isinstance(k, str), list(BALANCE).index(k) if isinstance(k, str) else -k))
        return [(self.key_label(k), self.result_text(phys[k])) for k in keys]

    def physics_status(self) -> str:
        """Physics mode at a glance (status bars): the mode, and the falls / body error of the
        motions computed in it."""
        if not self.physics_on:
            return "물리 모드: 꺼짐"
        text = f"물리 모드: {self.mode_label()}"
        done = [p for it in list(self.items) if not self.is_sim_result(it)
                and (p := it.handles.get("phys", {}).get(self.phys_key)) is not None]
        if done:
            falls = sum(p.metrics.get("phys_falls") or 0 for p in done)
            text += f" · 넘어짐 {falls}회"
            errs = [p.metrics["phys_body_error_cm"] for p in done if p.metrics.get("phys_body_error_cm") is not None]
            if errs:
                text += f" · 몸 위치 오차 {np.mean(errs):.1f} cm"
            if len(done) > 1:
                text += f" (모션 {len(done)}개 합·평균)"
        return text

    def job_text(self, item: Item) -> str:
        """One-line physics state of a motion."""
        if self.is_physics_result(item):
            return "이미 물리 결과입니다"
        if self.is_policy_result(item):
            m = item.info["policy_replay"]
            return (f"MuJoCo 재생 결과 ({item.info.get('controller_label') or m.get('controller')}) · 넘어짐 "
                    f"{m.get('falls', '-')} · 몸 위치 오차 {m.get('body_error_cm', '-')} cm")
        phys = item.handles.get("phys", {}).get(self.phys_key)
        if phys is not None:
            return f"완료 · {self.result_text(phys)}"
        job = item.handles.get("phys_jobs", {}).get(self.phys_key)
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
        """'물리 계산 1개 · MuJoCo 계산 1개 · 동영상 2개' for the jobs queued or running, '' when idle."""
        jobs = [j for it in list(self.items) for j in it.handles.get("phys_jobs", {}).values() if j.active]
        phys = sum(1 for j in jobs if j.kind != "policy")
        mujoco = len(jobs) - phys
        vids = sum(1 for it in list(self.items) if (j := it.handles.get("video_job")) is not None and j.active)
        parts = ([f"물리 계산 {phys}개"] if phys else []) + ([f"MuJoCo 계산 {mujoco}개"] if mujoco else []) \
            + ([f"동영상 {vids}개"] if vids else [])
        return " · ".join(parts)

    def fall_note(self, phys: Item, local: float) -> str:
        """'넘어짐 2.07s · 발끝 걸림 1.47s부터' from the first cause's onset until shortly after the fall
        (MuJoCo results: '넘어짐 2.07s · 기울어짐', the rule that called it a fall)."""
        if "policy_replay" in phys.info:
            for t, rule in self.falls_of(phys):
                if t <= local <= t + 0.5:
                    return f"넘어짐 {t:.2f}s · {rule}"
            return ""
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
        return self.falls_of(self.shown(item))

    @staticmethod
    def falls_of(src: Item) -> list[tuple[float, str]]:
        pol = src.info.get("policy_replay")
        if pol:  # MuJoCo: the fall rule, and the falls while holding the last pose after the clip
            rules = pol.get("fall_causes") or []
            return [(t, FALL_RULE_KO.get(r, r)) for t, r in zip(pol.get("fall_times_s") or [], rules)] \
                + [(t, "클립이 끝난 뒤") for t in pol.get("hold_fall_times_s") or []]
        p = src.info.get("physics", {})
        diag = {round(d.get("fall_time_s", 0.0), 3): d.get("primary_cause") for d in p.get("fall_diagnosis") or []}
        return [(t, CAUSE_KO.get(diag.get(round(t, 3)), "")) for t in p.get("fall_times_s") or []]

    # ---------------------------------------------------------------- video
    def save_video(self, item: Item) -> PhysicsJob:
        """Queue an Isaac recording of this motion (its physics result in physics mode; with a
        MuJoCo 균형 제어, Isaac replays the MuJoCo result as it is); raises when Isaac Sim is not
        found, or when the MuJoCo result is not there yet."""
        physics = self.physics_on and not self.is_sim_result(item)
        robot, mode, what = item.robot, "kinematic", "kinematic"
        if physics and self.balance != "isaac":
            shown = self.shown(item)
            if shown is item:
                raise RuntimeError(f"{BALANCE[self.balance]} 결과가 아직 없습니다. 계산이 끝나면 다시 저장하세요")
            robot, mode, what, physics = shown.robot, f"mujoco_{self.balance}", f"MuJoCo {self.balance}", False
        elif physics:
            mode = what = f"physics_x{self.assist:g}"
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.label).strip("_") or "motion"
        path = os.path.join(self.opts.video_dir, f"{stem}_{mode}.mp4")
        human = item.source if item.human is not None else None
        if item.info.get("solved_motion"):  # C3D: Isaac draws a human in its file's own frame, so use the solved skeleton
            human = item.info["solved_motion"]
        motion = replace(robot, name=stem)  # the video caption shows this name, not the cache file's
        job = self.runner.request_video(motion, path, human=human, physics=physics, assist=self.assist,
                                        smpl_model_dir=self.opts.smpl_model_dir,
                                        on_done=lambda j, it=item: self._video_done(it, j))
        item.handles["video_job"] = job
        self.log(f"video {'queued' if job.active else 'exists'}: {item.label} ({what})")
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
        ff = item.info.get("foot_flat")
        if ff:  # retargeted with 디딤발 평평 보정 (khumanoid.retarget.flatten_stance_feet)
            side = {"left": "왼", "right": "오"}
            pitch = ", ".join(f"{side.get(s, s)} {p['before']:g}° → {p['after']:g}°"
                              for s, p in ff.get("stance_pitch_deg", {}).items() if p.get("before") is not None)
            n = ff.get("frames_changed", 0)
            rows.append(("디딤발 평평", "켬 · 바뀐 프레임 없음" if not n else
                         f"{n}프레임 고침" + (f" · 디딤 중 발 pitch {pitch}" if pitch else "")
                         + f" · 뒤꿈치 뜸 평균 {ff['sole_lift_cm']['mean']:g} / 최대 {ff['sole_lift_cm']['max']:g} cm"))
        c3d = item.info.get("c3d")
        if c3d:  # raw markers drawn on the robot of the same take's solved skeleton
            extra = (f" (파일에는 Vicon 모델 계산값까지 점 {c3d['points']}개)" if c3d["points"] != c3d["markers"] else "")
            rows.append(("C3D 마커", f"{c3d['markers']}개{extra}, {c3d['fps']:g} Hz, {c3d['frames']} frames"))
            worst = ", ".join(f"{n} {p}%" for n, p in c3d.get("most_missing", []))
            text = f"빠짐 {c3d['missing_pct']:.1f}%" + (f" ({worst})" if worst else "")
            if c3d.get("longest_gap_marker"):
                text += f" · 가장 긴 공백 {c3d['longest_gap_s']:.2f} s ({c3d['longest_gap_marker']})"
            text += (f" · 튐 {c3d['spike_frames']}프레임 ({', '.join(c3d['spike_markers'])})" if c3d.get("spike_frames")
                     else " · 튐 없음")
            rows.append(("마커 QC", text))
            solved = rel(item.info.get("solved_motion", "?")).replace(os.sep, "/")
            rows.append(("로봇 동작", f"{solved} 리타겟 · 마커를 그 좌표로 {c3d['yaw_deg']:.0f}° 돌려 "
                                    f"맞춤 (골반 잔차 {c3d['residual_cm']:.1f} cm)"))
        if m.get("phys_ok"):
            rows.append(("물리 결과", f"{m['phys_ok']} · {self.result_text(item)}"))
        if self.is_physics_result(item):
            ref = item.info.get("reference_motion")
            rows.append(("참고", "이미 Isaac 물리 결과인 파일이라 물리 모드를 켜고 꺼도 그대로이고, 로봇 관절각만 있어 사람 "
                                 "스켈레톤이 없습니다. 사람과 나란히 보려면 원본 사람 모션을 추가하고 물리 모드를 켜세요."
                                 + (f" 원래 로봇 동작: {rel(ref)}" if ref else "")))
        if self.is_policy_result(item):
            p = item.info["policy_replay"]
            rows.append(("참고", f"MuJoCo에서 시뮬레이션한 동작입니다"
                                 f"({item.info.get('controller_label') or p.get('controller')}, 보조 힘 없음, 넘어짐 "
                                 f"{p.get('falls', '-')}). 물리 모드를 켜도 Isaac으로 다시 계산하지 않습니다. 원본: "
                                 f"{rel(item.info['source']) if item.info.get('source') else '-'}"))
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
                    else f"MuJoCo · {'GMT' if shown.info['policy_replay'].get('controller') == 'gmt' else '없음'}"
                    if self.is_policy_result(shown)
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
