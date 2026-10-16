"""Compare motions retargeted to the same humanoid, side by side, in the browser.

    python tools/compare_viewer.py data/raw/cmu_bvh/143_11.bvh data/raw/amass_cmu_smplx/143_11_stageii.npz
    python tools/compare_viewer.py data/raw/unitree_lafan1_g1/walk1_subject1.csv data/retargeted/lafan1/walk1_subject1_g1.npz
    -> open http://127.0.0.1:8080

Inputs (any mix, also addable from the GUI):
  human motion  .bvh, .fbx (through Blender), AMASS SMPL-X .npz -> retargeted to the robot
                with tools/retarget.py's pipeline (cached in data/cache/retarget/),
                shown with the source skeleton overlaid at robot scale
  robot motion  project .npz, Unitree .csv, GMR .pkl -> shown as is; Isaac physics
                results (tools/isaac_replay.py --physics, <clip>_sim.npz) included

Panels: playback (time, speed, layout side-by-side / overlay, start alignment), one
folder per motion (visibility, time offset, details), and analysis against a
reference motion (automatic time alignment on the leg joints, joint-angle plot,
per-joint RMSE, smoothness, planted-foot slip, floor penetration, QC).
The robot model is GMR's G1 URDF (meshes from ..\\GMR\\assets\\unitree_g1).

Physics mode (button on the playback tab, or --physics): every robot motion is shown as
Isaac Sim PhysX simulated it (gravity, floor contact, joint torque limits) instead of
its joint angles. Missing results are computed in the background, one clip at a time,
by tools/isaac_replay.py --physics (khumanoid/physics_runner.py) and cached in
data/cache/physics/. Isaac Sim's EULA must be accepted for that: --isaac-accept-eula.
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import viser  # noqa: E402
import yourdfpy  # noqa: E402
from viser.extras import ViserUrdf  # noqa: E402

from khumanoid import analysis  # noqa: E402
from khumanoid.compare import Item, compute_metrics, load_item  # noqa: E402
from khumanoid.diagnosis import CAUSE_KO  # noqa: E402
from khumanoid.io import urdf_joint_limits  # noqa: E402
from khumanoid.physics_runner import PHYSICS_CONFIG, PhysicsJob, PhysicsRunner  # noqa: E402
from khumanoid.rotations import quat_mul, quat_to_matrix  # noqa: E402

PHYSICS_CACHE = os.path.join(ROOT, "data", "cache", "physics")
ASSIST_OPTIONS = {"켬 (기본)": 1.0, "끔 (--assist 0)": 0.0}

PALETTE = [(230, 90, 50), (50, 125, 215), (60, 165, 90), (150, 90, 190), (215, 165, 40), (110, 110, 110),
           (0, 160, 170), (200, 70, 140)]


def log(msg: str) -> None:
    print(f"[compare_viewer] {msg}", flush=True)


def hexcolor(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def yaw_quat(yaw: float) -> np.ndarray:
    return np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])


def heading(q_wxyz: np.ndarray) -> float:
    x = quat_to_matrix(q_wxyz)[:, 0]  # body x axis in the world
    return float(np.arctan2(x[1], x[0]))


# --------------------------------------------------------------------------- display helpers
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


# --------------------------------------------------------------------------- viewer
class Viewer:
    def __init__(self, server: viser.ViserServer, urdf: yourdfpy.URDF, args):
        self.server, self.urdf, self.args = server, urdf, args
        self.items: list[Item] = []
        self.lock = threading.RLock()
        self.t = 0.0
        self.playing = False
        self.fk = None
        try:
            self.fk = analysis.FootKinematics(args.robot)
        except Exception as e:  # GMR missing: foot metrics off, everything else works
            log(f"foot metrics disabled ({type(e).__name__}: {e})")
        self.limits = urdf_joint_limits(args.urdf)
        self._last_plot = 0.0
        self._plot_dirty = True
        self.physics_on = False
        self.runner = PhysicsRunner(PHYSICS_CACHE, physics_config=args.physics_config,
                                    accept_eula=args.isaac_accept_eula, log=log)
        self._phys_error = ""
        self._last_status = 0.0
        self._build_gui()
        self._update_phys_status(force=True)
        server.scene.set_up_direction("+z")
        server.scene.add_grid("/floor", width=40, height=40, cell_size=0.5, section_size=1.0,
                              plane_color=(235, 235, 238), plane_opacity=1.0, shadow_opacity=0.25)

    # ---------------------------------------------------------------- GUI
    def _build_gui(self) -> None:
        gui = self.server.gui
        gui.configure_theme(control_width="large")
        tabs = gui.add_tab_group()
        with tabs.add_tab("재생", icon=None):
            with gui.add_folder("물리 모드 (Isaac PhysX)"):
                self.phys_btn = gui.add_button(
                    "물리 모드 켜기",
                    hint="켜면 각 로봇 동작을 관절각대로 그리지 않고, Isaac Sim PhysX(중력·바닥 접촉·관절 토크 한계)가 "
                         "시뮬레이션한 결과로 바꿔 그립니다. 결과가 없는 클립은 Isaac을 백그라운드로 돌려 만듭니다"
                         "(짧은 클립 약 1분, data/cache/physics에 저장)")
                self.phys_btn.on_click(lambda _: self.set_physics(not self.physics_on))
                self.phys_assist = gui.add_dropdown(
                    "골반 보조 힘", tuple(ASSIST_OPTIONS), initial_value="켬 (기본)",
                    hint="균형 제어기 대신 골반을 원래 위치·자세로 당기는 가상 하네스입니다. 끄면 균형 피드백이 없어 "
                         "걷기도 대부분 1–2초 안에 넘어집니다")
                self.phys_assist.on_update(lambda _: self._physics_changed())
                gui.add_button("물리 계산 취소", hint="대기 중이거나 계산 중인 물리 실행을 멈춥니다").on_click(
                    lambda _: self.cancel_physics())
                self.phys_status = gui.add_markdown("")
            self.play_btn = gui.add_button("재생")
            self.play_btn.on_click(lambda _: self.toggle_play())
            self.time_slider = gui.add_slider("시간 (s)", min=0.0, max=1.0, step=1 / 30, initial_value=0.0)
            self.time_slider.on_update(self._on_slider)
            with gui.add_folder("이동", expand_by_default=False):
                gui.add_button("-1 프레임").on_click(lambda _: self.step(-1))
                gui.add_button("+1 프레임").on_click(lambda _: self.step(1))
                gui.add_button("처음으로").on_click(lambda _: self.seek(0.0))
            self.speed = gui.add_slider("재생 속도", min=0.1, max=2.0, step=0.05, initial_value=1.0)
            self.loop = gui.add_checkbox("반복", True)
            self.layout = gui.add_dropdown("배치", ("나란히", "겹쳐서"), initial_value="나란히")
            self.spacing = gui.add_number("간격 (m)", 1.8, min=0.3, max=5.0, step=0.1)
            self.align = gui.add_checkbox("시작 위치·방향 맞춤", True,
                                          hint="각 모션의 시작 골반을 원점, 진행 방향을 +x로 옮겨 그립니다")
            self.show_humans = gui.add_checkbox("사람 스켈레톤", True,
                                                hint="리타게팅 원본을 로봇 크기로 줄여 그립니다")
            self.human_place = gui.add_dropdown("스켈레톤 위치", ("로봇 옆", "로봇과 겹쳐서"), initial_value="로봇 옆")
            self.human_look = gui.add_dropdown(
                "사람 표시", ("막대", "몸 메시 (SMPL-X)"), initial_value="막대",
                hint="SMPL-X 입력은 몸 표면(선형 블렌드 스키닝)으로 그릴 수 있습니다. BVH / FBX는 막대만 있습니다")
            self.human_look.on_update(lambda _: self._update_human_look())
            self.robot_look = gui.add_dropdown("로봇 표시", ("불투명", "반투명"), initial_value="불투명")
            self.robot_look.on_update(lambda _: self._rebuild_meshes())
            self.show_labels = gui.add_checkbox("이름표", True)
            self.show_balance = gui.add_checkbox(
                "균형 표시", True, hint="바닥에 지지다각형(초록, 발이 닿은 발바닥 점), 질량중심 투영(파랑), ZMP(빨강)")
            gui.add_button("카메라 맞추기").on_click(lambda _: self.fit_camera())
        with tabs.add_tab("모션"):
            self.add_path = gui.add_text("파일 경로", "", hint="BVH / FBX / AMASS SMPL-X npz / 로봇 npz·csv·pkl "
                                                              "(Isaac 물리 결과 *_sim.npz 포함)")
            gui.add_button("추가").on_click(lambda _: self._add_from_gui())
            self.status = gui.add_markdown("")
            self.motion_folder = gui.add_folder("목록")
        with tabs.add_tab("분석"):
            self.ref = gui.add_dropdown("기준 모션", ("-",))
            self.ref.on_update(lambda _: self.refresh_analysis())
            gui.add_button("기준에 시간 자동 정렬", hint="다리 관절각 차이가 가장 작아지는 시간 오프셋을 찾습니다").on_click(
                lambda _: self.auto_align())
            self.joint = gui.add_dropdown("그래프 항목", ("-",))
            self.joint.on_update(lambda _: self._mark_plot())
            self.window = gui.add_number("그래프 구간 (s)", 10.0, min=0.0, step=1.0, hint="현재 시점 앞뒤로 보일 길이. 0 = 전체")
            self.window.on_update(lambda _: self._mark_plot())
            self.plot = gui.add_plotly(go.Figure(), aspect=1.1)
            self.table = gui.add_html("")
            self.rmse_plot = gui.add_plotly(go.Figure(), aspect=0.6)

    def _add_from_gui(self) -> None:
        p = self.add_path.value.strip().strip('"')
        if not p:
            return
        if not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        self.status.content = f"불러오는 중: `{os.path.basename(p)}` (리타게팅이면 수십 초)"
        try:
            self.add(p)
            self.status.content = f"추가됨: `{os.path.basename(p)}`"
        except Exception as e:
            self.status.content = f"**실패**: {type(e).__name__}: {e}"

    # ---------------------------------------------------------------- items
    def add(self, path: str) -> Item:
        a = self.args
        item = load_item(path, robot=a.robot, smooth=a.smooth, fps=a.fps, csv_fps=a.csv_fps,
                         smpl_model_dir=a.smpl_model_dir, swing_clearance=a.swing_clearance / 100.0, log=log)
        compute_metrics(item, self.fk, self.limits)
        with self.lock:
            used = {it.color for it in self.items}
            item.color = next((c for c in PALETTE if c not in used), PALETTE[len(self.items) % len(PALETTE)])
            base = item.label
            n = 2
            while any(it.label == item.label for it in self.items):
                item.label = f"{base} ({n})"
                n += 1
            self.items.append(item)
            self._build_item(item, len(self.items) - 1)
            if self.human_look.value.startswith("몸") and item.kind.startswith("SMPL-X"):
                self._add_body_mesh(item)
            self._refresh_lists()
        log(f"added {item.label}: {item.kind}, {item.robot.num_frames} frames @ {item.robot.fps:g} fps")
        self._request_physics(item)
        return item

    def _update_human_look(self) -> None:
        """Create the SMPL-X body meshes on first use (loads the body model)."""
        if self.human_look.value.startswith("몸"):
            for it in list(self.items):
                if it.kind.startswith("SMPL-X") and "mesh" not in it.handles:
                    self._add_body_mesh(it)
        self._mark_plot()

    def _add_body_mesh(self, item: Item) -> None:
        from khumanoid.io.smpl import BodyMeshRig

        try:
            rig = BodyMeshRig(item.source, model_dir=self.args.smpl_model_dir)
        except Exception as e:
            log(f"{item.label}: no body mesh ({type(e).__name__}: {e})")
            item.handles["mesh"] = None
            return
        light = tuple(int(200 + 0.2 * c) for c in item.color)
        item.handles["rig"] = rig
        item.handles["mesh"] = self.server.scene.add_mesh_simple(
            f"/m{id(item)}/body", rig.vertices(0).astype(np.float32), rig.faces, color=light, opacity=0.9)

    def remove(self, item: Item) -> None:
        with self.lock:
            for job in item.handles.get("phys_jobs", {}).values():
                if job.active and not any(job in it.handles.get("phys_jobs", {}).values()
                                          for it in self.items if it is not item):
                    self.runner.cancel(job)
            for h in item.handles.values():
                try:
                    h.remove()
                except Exception:
                    pass
            self.items.remove(item)
            for i, it in enumerate(self.items):
                it.handles["index"] = i
            self._refresh_lists()

    def _robot_mesh(self, item: Item) -> ViserUrdf:
        rgba = tuple(c / 255 for c in item.color) + ((0.45,) if self.robot_look.value == "반투명" else (1.0,))
        return ViserUrdf(self.server, self.urdf, root_node_name=f"/m{id(item)}/robot", mesh_color_override=rgba)

    def _rebuild_meshes(self) -> None:
        with self.lock:
            for it in self.items:
                it.handles["urdf"].remove()
                it.handles["urdf"] = self._robot_mesh(it)

    def fit_camera(self) -> None:
        """Look at all visible robots from the front-left, far enough for the whole row."""
        with self.lock:
            pts = np.array([it.handles["root"].position for it in self.items if it.visible])
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

    def _build_item(self, item: Item, index: int) -> None:
        s = self.server
        node = f"/m{id(item)}"
        item.handles["root"] = s.scene.add_frame(f"{node}/robot", show_axes=False)
        item.handles["urdf"] = self._robot_mesh(item)
        names = item.handles["urdf"].get_actuated_joint_names()
        col = {n: i for i, n in enumerate(item.robot.joint_names)}
        item.handles["map"] = [col.get(n) for n in names]
        missing = [n for n, i in zip(names, item.handles["map"]) if i is None]
        if missing:
            log(f"  {item.label}: {len(missing)} robot joints not in the motion, held at 0")
        item.handles["label"] = s.scene.add_label(f"{node}/label", item.label, font_screen_scale=0.9,
                                                  anchor="bottom-center")
        if item.balance is not None:
            self._add_balance_handles(item)
        if item.human is not None:
            item.handles["scale"] = human_scale(item)
            bones = np.array(item.human.bones(), dtype=int).reshape(-1, 2)
            item.handles["bones"] = bones
            dark = tuple(int(c * 0.55) for c in item.color)
            item.handles["human"] = s.scene.add_line_segments(
                f"{node}/human", np.zeros((len(bones), 2, 3)), dark, thickness=0.012)
        # transform that starts the robot at the origin facing +x (applied when "align" is on)
        q0 = item.robot.root_quat[0]
        item.handles["yaw0"] = heading(q0)
        item.handles["p0"] = item.robot.root_pos[0].copy()
        item.handles["index"] = index
        with self.motion_folder:
            f = s.gui.add_folder(item.label)
        item.handles["folder"] = f
        with f:
            s.gui.add_markdown(self._item_md(item))
            item.handles["phys_md"] = s.gui.add_markdown("")
            vis = s.gui.add_checkbox("보이기", True)
            vis.on_update(lambda e, it=item: setattr(it, "visible", e.target.value))
            if item.human is not None:
                hv = s.gui.add_checkbox("사람 스켈레톤", True)
                hv.on_update(lambda e, it=item: setattr(it, "show_human", e.target.value))
            off = s.gui.add_number("시간 오프셋 (s)", 0.0, step=1 / 30)
            off.on_update(lambda e, it=item: self._set_offset(it, e.target.value))
            item.handles["offset_input"] = off
            s.gui.add_button("제거", color="red").on_click(lambda _, it=item: self.remove(it))

    def _add_balance_handles(self, item: Item) -> None:
        """Support polygon (up to 8 edges), CoM projection and ZMP on the floor."""
        s, node = self.server, f"/m{id(item)}"
        item.handles["support"] = s.scene.add_line_segments(
            f"{node}/support", np.zeros((8, 2, 3)), (40, 170, 70), thickness=0.006)
        item.handles["com"] = s.scene.add_icosphere(f"{node}/com", radius=0.025, color=(40, 90, 220))
        item.handles["zmp"] = s.scene.add_icosphere(f"{node}/zmp", radius=0.02, color=(220, 50, 40))

    # ---------------------------------------------------------------- physics mode
    def _assist(self) -> float:
        return ASSIST_OPTIONS.get(self.phys_assist.value, 1.0)

    @staticmethod
    def _is_physics_result(item: Item) -> bool:
        return item.kind.startswith("Isaac PhysX")

    def set_physics(self, on: bool) -> None:
        self.physics_on = bool(on)
        self.phys_btn.label = "물리 모드 끄기" if self.physics_on else "물리 모드 켜기"
        try:
            self.phys_btn.color = "teal" if self.physics_on else None
        except Exception:
            pass
        self._physics_changed()

    def _physics_changed(self) -> None:
        for it in list(self.items):
            self._request_physics(it)
        self._update_phys_status(force=True)
        self.refresh_analysis()

    def _request_physics(self, item: Item) -> None:
        """Start (or find) the physics run of this motion for the current harness setting."""
        if not self.physics_on or self._is_physics_result(item):
            return
        assist = self._assist()
        jobs = item.handles.setdefault("phys_jobs", {})
        if assist in item.handles.setdefault("phys", {}) or (assist in jobs and jobs[assist].state != "failed"
                                                               and jobs[assist].state != "cancelled"):
            return
        try:
            jobs[assist] = self.runner.request(item.robot, assist, on_done=lambda j, it=item: self._physics_done(it, j))
            self._phys_error = ""
        except Exception as e:  # Isaac Sim not found
            self._phys_error = f"{type(e).__name__}: {e}"
            log(f"physics unavailable: {self._phys_error}")

    def _physics_done(self, item: Item, job: PhysicsJob) -> None:
        """Worker thread: load the simulated motion as the item's physics view."""
        if job.state != "done":
            self._update_phys_status(force=True)
            return
        try:
            phys = load_item(job.result, log=None)
            compute_metrics(phys, self.fk, self.limits)
        except Exception as e:
            job.state, job.stage, job.message = "failed", "실패", f"결과를 읽지 못함: {type(e).__name__}: {e}"
            self._update_phys_status(force=True)
            return
        with self.lock:
            if item not in self.items:
                return
            col = {n: i for i, n in enumerate(phys.robot.joint_names)}
            phys.handles["map"] = [col.get(n) for n in item.handles["urdf"].get_actuated_joint_names()]
            item.handles.setdefault("phys", {})[job.assist] = phys
            if phys.balance is not None and "support" not in item.handles:
                self._add_balance_handles(item)
        self._update_phys_status(force=True)
        self.refresh_analysis()

    def cancel_physics(self) -> None:
        for it in list(self.items):
            for job in it.handles.get("phys_jobs", {}).values():
                if job.active:
                    self.runner.cancel(job)
        self._update_phys_status(force=True)

    def _shown(self, item: Item) -> Item:
        """What is drawn and measured for this motion: its physics result in physics mode
        (once computed), else the motion itself."""
        if self.physics_on:
            phys = item.handles.get("phys", {}).get(self._assist())
            if phys is not None:
                return phys
        return item

    def _job_text(self, item: Item) -> str:
        """One-line physics state of a motion for the panels."""
        if self._is_physics_result(item):
            return "이미 물리 결과입니다"
        assist = self._assist()
        phys = item.handles.get("phys", {}).get(assist)
        if phys is not None:
            m = phys.metrics
            return (f"완료 · 넘어짐 {m.get('phys_falls', '-')} · 보조 힘 {m.get('phys_harness_pct', 0):.0f}% 체중 · "
                    f"토크 한계 초과 {m.get('phys_saturated_pct', 0):.1f}%")
        job = item.handles.get("phys_jobs", {}).get(assist)
        if job is None:
            return f"실행할 수 없음: {self._phys_error}" if self._phys_error else "아직 계산 안 함"
        if job.state == "running":
            el = time.time() - job.started
            eta = ""
            if job.progress > 0.4:
                eta = f", 약 {el / job.progress * (1 - job.progress):.0f}초 남음"
            return f"{job.stage} {100 * job.progress:.0f}% ({el:.0f}초{eta})"
        if job.state == "queued":
            return "대기 중"
        return f"{job.stage}: {job.message}" if job.message and job.message != job.stage else job.stage

    def _update_phys_status(self, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and now - self._last_status < 0.5:
            return
        self._last_status = now
        items = [it for it in list(self.items) if not self._is_physics_result(it)]
        running = sum(1 for it in items for j in it.handles.get("phys_jobs", {}).values() if j.active)
        if self.physics_on:
            head = f"**켜짐** · 골반 보조 힘 x{self._assist():g}"
        else:
            head = "**꺼짐** · 관절각대로 그리는 기구학 재생"
            if running:
                head += f" · 백그라운드 물리 계산 {running}개 진행 중"
        lines = [head]
        if self.physics_on:
            lines += [f"<span style='color:{hexcolor(it.color)}'>■</span> {it.label}: {self._job_text(it)}" for it in items]
            if self._phys_error and not items:
                lines.append(f"실행할 수 없음: {self._phys_error}")
        self.phys_status.content = "  \n".join(lines)
        for it in list(self.items):
            md = it.handles.get("phys_md")
            if md is not None:
                md.content = f"물리: {self._job_text(it)}" if (self.physics_on or it.handles.get("phys")) else ""

    def _fall_note(self, phys: Item, local: float) -> str:
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

    def _item_md(self, item: Item) -> str:
        m, r = item.metrics, item.robot
        lines = [f"<span style='color:{hexcolor(item.color)}'>■</span> **{item.kind}**",
                 f"{r.num_frames} frames @ {r.fps:g} fps, {r.duration:.1f} s · QC **{m.get('qc', '?')}**"]
        res = item.info.get("ik_position_residual")
        if res:
            lines.append("IK 잔차(평균): " + ", ".join(f"{k} {v['mean_cm']} cm" for k, v in res.items()))
        if m.get("phys_ok"):
            lines.append(f"물리: **{m['phys_ok']}** · 보조 힘 {m['phys_harness_pct']:.0f}% 체중 · 넘어짐 {m['phys_falls']}"
                         f" · 토크 한계 초과 {m['phys_saturated_pct']:.1f}%")
        lines.append(f"`{os.path.relpath(item.source, ROOT)}`")
        return "  \n".join(lines)

    def _set_offset(self, item: Item, value: float) -> None:
        item.offset = float(value)
        self._update_slider_range()
        self.refresh_analysis()

    def _refresh_lists(self) -> None:
        labels = tuple(it.label for it in self.items) or ("-",)
        cur = self.ref.value
        self.ref.options = labels
        self.ref.value = cur if cur in labels else labels[0]
        joints = analysis.common_joints(*[it.robot for it in self.items]) if self.items else []
        opts = ("골반 높이 (m)", "골반 수평속도 (m/s)") + tuple(joints)
        cur = self.joint.value
        self.joint.options = opts
        self.joint.value = cur if cur in opts else (next((j for j in opts if "left_knee" in j), opts[0]))
        self._update_slider_range()
        self.refresh_analysis()

    def _update_slider_range(self) -> None:
        end = max([it.offset + it.robot.duration for it in self.items] or [1.0])
        start = min([it.offset for it in self.items] or [0.0])
        self.time_slider.min = min(0.0, start)
        self.time_slider.max = max(end, 0.1)

    # ---------------------------------------------------------------- playback
    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_btn.label = "일시정지" if self.playing else "재생"

    def _on_slider(self, _) -> None:
        if not self._setting_slider:
            self.t = float(self.time_slider.value)
            self._mark_plot()

    _setting_slider = False

    def seek(self, t: float) -> None:
        self.t = float(np.clip(t, self.time_slider.min, self.time_slider.max))
        self._mark_plot()

    def step(self, n: int) -> None:
        self.playing = False
        self.play_btn.label = "재생"
        self.seek(self.t + n / 30.0)

    def _mark_plot(self) -> None:
        self._plot_dirty = True

    def tick(self, dt: float) -> None:
        if self.playing:
            self.t += dt * float(self.speed.value)
            if self.t > self.time_slider.max:
                if self.loop.value:
                    self.t = float(self.time_slider.min)
                else:
                    self.t = float(self.time_slider.max)
                    self.toggle_play()
            self._setting_slider = True
            self.time_slider.value = round(self.t, 4)
            self._setting_slider = False
        with self.lock:
            for item in self.items:
                self._pose(item)
        if self.physics_on or self.runner.busy():
            self._update_phys_status()
        now = time.perf_counter()
        if self._plot_dirty and (not self.playing or now - self._last_plot > 0.25):
            self._update_plot()
            self._last_plot = now
            self._plot_dirty = self.playing

    def _display_transform(self, item: Item) -> tuple[np.ndarray, np.ndarray]:
        """(yaw quaternion, translation) from motion world to display."""
        lane = 0.0 if self.layout.value == "겹쳐서" else -item.handles["index"] * float(self.spacing.value)
        if self.align.value:
            q = yaw_quat(-item.handles["yaw0"])
            p0 = item.handles["p0"]
            shift = -quat_to_matrix(q) @ np.array([p0[0], p0[1], 0.0])
        else:
            q, shift = np.array([1.0, 0, 0, 0]), np.zeros(3)
        return q, shift + np.array([0.0, lane, 0.0])

    def _pose(self, item: Item) -> None:
        h = item.handles
        visible = item.visible
        h["root"].visible = visible
        h["label"].visible = visible and bool(self.show_labels.value)
        show_h = visible and item.show_human and bool(self.show_humans.value)
        mesh = h.get("mesh") if self.human_look.value.startswith("몸") else None
        if "human" in h:
            h["human"].visible = show_h and mesh is None
        if h.get("mesh") is not None:
            h["mesh"].visible = show_h and mesh is not None
        for k in ("support", "com", "zmp"):
            if k in h and not (visible and self.show_balance.value):
                h[k].visible = False
        if not visible:
            return
        src = self._shown(item)  # the physics result in physics mode
        robot = src.robot
        local = self.t - item.offset
        inside = 0.0 <= local <= robot.duration
        t = np.array([np.clip(local, 0.0, robot.duration)])
        pos, quat = analysis.sample_root(robot, t)
        dof = analysis.sample_dof(robot, t)[0]
        qd, shift = self._display_transform(item)  # the original's start, so both views line up
        R = quat_to_matrix(qd)
        p = R @ pos[0] + shift
        h["root"].position = p
        h["root"].wxyz = quat_mul(qd, quat[0])
        jmap = src.handles.get("map", h["map"])
        h["urdf"].update_cfg(np.array([dof[i] if i is not None else 0.0 for i in jmap]))
        h["label"].position = p + np.array([0.0, 0.0, 0.85])
        text = item.label if inside else f"{item.label} (범위 밖)"
        if self.physics_on and not self._is_physics_result(item):
            if src is item:  # not computed yet: still the joint angles
                job = h.get("phys_jobs", {}).get(self._assist())
                text += (" · 물리 대기" if job is not None and job.state == "queued" else
                         f" · 물리 계산 {100 * job.progress:.0f}%" if job is not None and job.state == "running" else
                         " · 물리 실패 (기구학 표시)")
            else:
                note = self._fall_note(src, local)
                text += f" · 물리 · {note}" if note else " · 물리"
        h["label"].text = text
        if "support" in h:
            self._pose_balance(item, src.balance, local, R, shift)
        if "human" in h and show_h:
            hm = item.human
            hips = hm.positions[0, 0]
            start_r = item.robot.root_pos[0]

            def to_display(P: np.ndarray) -> np.ndarray:
                # scale about the skeleton's start point (floor level), then put that point on the robot's start
                Ps = h["scale"] * (P - np.array([hips[0], hips[1], 0.0])) + np.array([start_r[0], start_r[1], 0.0])
                Pd = Ps @ R.T + shift
                if self.human_place.value == "로봇 옆":  # inside the robot the lines are hidden by its meshes
                    Pd = Pd + np.array([0.0, 0.8, 0.0])
                return Pd

            if mesh is not None:
                rig = h["rig"]
                f = int(np.clip(round(local * rig.fps), 0, rig.num_frames - 1))
                key = (f, self.human_place.value, *np.round(R, 6).ravel(), *np.round(shift, 6))
                if h.get("mesh_key") != key:  # ~130 KB per update: only when the pose or placement changes
                    h["mesh_key"] = key
                    mesh.vertices = to_display(rig.vertices(f)).astype(np.float32)
            else:
                f = int(np.clip(round(local * hm.fps), 0, hm.num_frames - 1))
                Pd = to_display(hm.positions[f])
                b = h["bones"]
                h["human"].points = np.nan_to_num(np.stack([Pd[b[:, 0]], Pd[b[:, 1]]], axis=1))

    def _pose_balance(self, item: Item, b, local: float, R: np.ndarray, shift: np.ndarray) -> None:
        """Support polygon, CoM projection and ZMP of the frame (BalanceTrack b), on the floor, in display space."""
        h = item.handles
        show = bool(self.show_balance.value) and item.visible and b is not None
        if not show:
            for k in ("support", "com", "zmp"):
                h[k].visible = False
            return
        f = int(np.clip(round(local * b.fps), 0, len(b.com) - 1))
        hull = b.hulls[f]
        z = float(b.floor[f]) + 0.004
        for k in ("support", "com", "zmp"):
            h[k].visible = show and len(hull) > 0
        if not show or not len(hull):
            return

        def disp(xy: np.ndarray) -> np.ndarray:
            p = np.column_stack([xy, np.full(len(xy), z)])
            return p @ R.T + shift

        ring = disp(np.asarray(hull))
        edges = np.stack([ring, np.roll(ring, -1, axis=0)], 1)[:8] if len(ring) > 2 else np.stack([ring[:1], ring[-1:]], 1)
        pts = np.zeros((8, 2, 3))
        pts[:len(edges)] = edges
        pts[len(edges):] = edges[-1]  # unused segments collapse onto the last edge
        h["support"].points = pts
        h["com"].position = tuple(disp(b.com[f:f + 1, :2])[0])
        h["zmp"].position = tuple(disp(b.zmp[f:f + 1])[0])

    # ---------------------------------------------------------------- analysis
    def _ref_item(self) -> Item | None:
        return next((it for it in self.items if it.label == self.ref.value), None)

    def auto_align(self) -> None:
        ref = self._ref_item()
        if ref is None:
            return
        notes = []
        for it in self.items:
            if it is ref:
                continue
            off, rms = analysis.estimate_offset(ref.robot, it.robot, max_shift=float(self.args.max_shift))
            it.offset = ref.offset + off
            it.handles["offset_input"].value = round(it.offset, 4)
            notes.append(f"{it.label}: {it.offset:+.3f} s (다리 RMS {rms:.1f}°)")
        self._update_slider_range()
        self.refresh_analysis()
        self.status.content = "시간 정렬: " + "; ".join(notes)

    def refresh_analysis(self) -> None:
        self._update_table()
        self._update_rmse()
        self._mark_plot()

    def _update_plot(self) -> None:
        fig = go.Figure()
        key = self.joint.value
        w = float(self.window.value or 0.0)
        lo, hi = (self.t - w / 2, self.t + w / 2) if w > 0 else (-np.inf, np.inf)
        for it in self.items:
            r = self._shown(it).robot
            tt = it.offset + np.arange(r.num_frames) / r.fps
            if key.startswith("골반 높이"):
                y = r.root_pos[:, 2]
            elif key.startswith("골반 수평속도"):
                v = np.linalg.norm(np.diff(r.root_pos[:, :2], axis=0), axis=1) * r.fps
                y = np.concatenate([v[:1], v])
            elif key in r.joint_names:
                y = np.degrees(r.dof_pos[:, r.joint_names.index(key)])
            else:
                continue
            sel = (tt >= lo) & (tt <= hi)
            fig.add_trace(go.Scatter(x=tt[sel], y=y[sel], mode="lines", name=it.label,
                                     line=dict(color=hexcolor(it.color), width=1.6)))
        fig.add_vline(x=self.t, line_width=1, line_color="black")
        unit = "m" if key.startswith("골반 높이") else "m/s" if key.startswith("골반 수평속도") else "°"
        fig.update_layout(title=dict(text=f"{key} [{unit}]", font=dict(size=13)), margin=dict(l=40, r=10, t=30, b=30),
                          legend=dict(orientation="h", y=-0.2, font=dict(size=10)), xaxis_title="t (s)",
                          template="plotly_white")
        if w > 0:
            fig.update_xaxes(range=[lo, hi])
        self.plot.figure = fig

    def _update_table(self) -> None:
        """Metrics as rows, motions as columns (fits the side panel)."""
        ref = self._ref_item()

        def f(v, fmt="{:.1f}"):
            return "-" if v is None or (isinstance(v, float) and not np.isfinite(v)) else fmt.format(v)

        cols = []
        for it in self.items:
            shown = self._shown(it)
            m = shown.metrics
            legs = whole = "기준" if it is ref else "-"
            if ref is not None and it is not ref:
                joints, rmse, ov = analysis.joint_rmse(self._shown(ref).robot, shown.robot, ref.offset, it.offset)
                if ov > 0:
                    li = [i for i, n in enumerate(joints) if any(k in n for k in analysis.LEG_KEYS)]
                    legs, whole = f(float(np.median(rmse[li]))), f(float(np.median(rmse)))
            mode = (f"물리 x{shown.info['physics'].get('harness_scale', 1):g}" if self._is_physics_result(shown)
                    else "기구학")
            cols.append([mode, f(m.get("duration")), f(m.get("acc_mean")), f(m.get("jerk_mean"), "{:.0f}"), f(m.get("vel_max")),
                         f(m.get("planted_slip_pct"), "{:.2f}"), f(m.get("penetration_pct"), "{:.2f}"),
                         f(m.get("sole_min_cm")), f(m.get("swing_low_pct")), f(m.get("com_out_pct")),
                         f(m.get("zmp_out_pct")), f(m.get("static_unbalanced_pct")), legs, whole, m.get("qc", "-"),
                         f(m.get("phys_harness_pct")), m.get("phys_falls", "-"), f(m.get("phys_saturated_pct")),
                         m.get("phys_ok", "-")])
        names = ["재생 방식", "길이 (s)", "관절 가속도 (rad/s²)", "관절 저크 (rad/s³)", "최대 관절속도 (rad/s)", "발 미끄러짐 (%)",
                 "바닥 관통 (%)", "발 최저점 (cm)", "스윙 발 바닥 근접 (%)", "CoM 지지 밖 (%)", "ZMP 지지 밖 (%)",
                 "정적 불균형 (%)", "기준 대비 다리 RMSE (°)",
                 "기준 대비 전체 RMSE (°)", "QC",
                 "물리: 보조 힘 (체중 %)", "물리: 넘어짐", "물리: 토크 한계 초과 (%)", "물리 판정"]
        head = "".join(f"<th style='color:{hexcolor(it.color)};text-align:right;padding:2px 4px'>■ {i + 1}</th>"
                       for i, it in enumerate(self.items))
        body = "".join("<tr><td style='padding:2px 4px'>" + n + "</td>" +
                       "".join(f"<td style='text-align:right;padding:2px 4px'>{c[r]}</td>" for c in cols) + "</tr>"
                       for r, n in enumerate(names))
        legend = "<br>".join(f"<span style='color:{hexcolor(it.color)}'>■ {i + 1}</span> {it.label} ({it.kind})"
                             for i, it in enumerate(self.items))
        notes = ("RMSE: 기준과 겹치는 구간의 관절별 RMSE 중앙값(시간 오프셋 반영). 발 미끄러짐: 발바닥 전체가 붙은 채 "
                 "0.3 m/s 이상으로 0.1 s 이상 움직인 프레임 비율. 바닥 관통: 발 최저점 -2 cm 아래 프레임 비율. "
                 "스윙 발 바닥 근접: 가장 느린 발바닥 점까지 0.5 m/s 넘게 움직이는 발이 그때의 바닥(디딤발 높이를 따라감) "
                 "1 cm 안을 지나는 비율(물리에서 발끝이 걸림). "
                 "물리 행: Isaac PhysX 결과(물리 모드, 또는 isaac_replay.py --physics 결과 파일)만 - 골반 보조 힘 "
                 "평균(체중 대비), 넘어짐 수, 관절 토크 한계를 넘은 프레임 비율. 물리 모드에서는 다른 행도 "
                 "시뮬레이션된 동작으로 잽니다.")
        self.table.content = (f"<div style='font-size:11px'>{legend}<table style='width:100%;border-collapse:collapse;"
                              f"margin-top:4px'><tr><th></th>{head}</tr>{body}</table>"
                              f"<div style='color:#777;margin-top:4px'>{notes}</div></div>")

    def _update_rmse(self) -> None:
        ref = self._ref_item()
        fig = go.Figure()
        if ref is not None:
            for it in self.items:
                if it is ref:
                    continue
                joints, rmse, ov = analysis.joint_rmse(self._shown(ref).robot, self._shown(it).robot, ref.offset, it.offset)
                if ov <= 0:
                    continue
                fig.add_trace(go.Bar(y=[j.replace("_joint", "") for j in joints], x=rmse, orientation="h",
                                     name=it.label, marker_color=hexcolor(it.color)))
        fig.update_layout(title=dict(text=f"관절별 RMSE (°) vs {self.ref.value}", font=dict(size=13)), barmode="group",
                          margin=dict(l=130, r=10, t=30, b=30), template="plotly_white",
                          legend=dict(orientation="h", y=-0.05, font=dict(size=10)),
                          yaxis=dict(autorange="reversed", tickfont=dict(size=9)))
        self.rmse_plot.figure = fig


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


def load_robot_urdf(path: str, cell: float) -> yourdfpy.URDF:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="motion files (human ones are retargeted)")
    ap.add_argument("--robot", default="unitree_g1", help="GMR robot for retargeting (default unitree_g1)")
    ap.add_argument("--urdf", default=os.path.join(os.path.dirname(ROOT), "GMR", "assets", "unitree_g1",
                                                   "g1_custom_collision_29dof.urdf"), help="robot URDF for display")
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
    ap.add_argument("--physics", action="store_true", help="start in physics mode (same as the button)")
    ap.add_argument("--physics-config", default=PHYSICS_CONFIG, help="PhysX settings for physics mode (yaml)")
    ap.add_argument("--isaac-accept-eula", action="store_true",
                    help="you accept the NVIDIA Omniverse EULA; physics mode runs Isaac Sim with OMNI_KIT_ACCEPT_EULA=YES")
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only; 0.0.0.0 to share on the LAN")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    urdf = load_robot_urdf(args.urdf, args.mesh_cell)
    server = viser.ViserServer(host=args.host, port=args.port, label="K-Humanoid motion compare")
    viewer = Viewer(server, urdf, args)
    atexit.register(viewer.runner.shutdown)  # no Isaac process outlives the viewer
    if args.body_mesh:
        viewer.human_look.value = "몸 메시 (SMPL-X)"
    if args.physics:
        viewer.set_physics(True)

    server.initial_camera.position = (3.0, -3.0, 1.8)
    server.initial_camera.look_at = (0.0, 0.0, 0.75)
    for p in args.inputs:
        try:
            viewer.add(p)
        except Exception as e:
            log(f"could not load {p}: {type(e).__name__}: {e}")
    viewer.tick(0.0)
    viewer.fit_camera()
    log(f"open http://{'127.0.0.1' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}")
    last = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            viewer.tick(now - last)
            last = now
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - now)))
    except KeyboardInterrupt:
        viewer.runner.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
