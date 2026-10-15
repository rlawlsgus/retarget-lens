"""Compare motions retargeted to the same humanoid, side by side, in the browser.

    python tools/compare_viewer.py data/raw/cmu_bvh/143_11.bvh data/raw/amass_cmu_smplx/143_11_stageii.npz
    python tools/compare_viewer.py data/raw/unitree_lafan1_g1/walk1_subject1.csv data/retargeted/lafan1/walk1_subject1_g1.npz
    -> open http://127.0.0.1:8080

Inputs (any mix, also addable from the GUI):
  human motion  .bvh, AMASS SMPL-X .npz  -> retargeted to the robot with tools/retarget.py's
                pipeline (cached in data/retargeted/cache/), shown with the source
                skeleton overlaid at robot scale
  robot motion  project .npz, Unitree .csv, GMR .pkl -> shown as is

Panels: playback (time, speed, layout side-by-side / overlay, start alignment), one
folder per motion (visibility, time offset, details), and analysis against a
reference motion (automatic time alignment on the leg joints, joint-angle plot,
per-joint RMSE, smoothness, planted-foot slip, floor penetration, QC).
The robot model is GMR's G1 URDF (meshes from ..\\GMR\\assets\\unitree_g1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import viser  # noqa: E402
import yourdfpy  # noqa: E402
from viser.extras import ViserUrdf  # noqa: E402

from khumanoid import analysis  # noqa: E402
from khumanoid.io import load_motion, urdf_joint_limits  # noqa: E402
from khumanoid.io.bvh import load_bvh  # noqa: E402
from khumanoid.io.smpl import load_amass_npz  # noqa: E402
from khumanoid.motion import RobotMotion, SkeletonMotion  # noqa: E402
from khumanoid.qc import QCConfig, check_robot  # noqa: E402
from khumanoid.retarget import ROBOT_TAGS, detect_format, retarget_file  # noqa: E402
from khumanoid.rotations import quat_mul, quat_to_matrix  # noqa: E402

PALETTE = [(230, 90, 50), (50, 125, 215), (60, 165, 90), (150, 90, 190), (215, 165, 40), (110, 110, 110),
           (0, 160, 170), (200, 70, 140)]
HUMAN_EXT = (".bvh",)
ROBOT_EXT = (".csv", ".pkl")
CACHE = os.path.join(ROOT, "data", "retargeted", "cache")


def log(msg: str) -> None:
    print(f"[compare_viewer] {msg}", flush=True)


def hexcolor(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def yaw_quat(yaw: float) -> np.ndarray:
    return np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])


def heading(q_wxyz: np.ndarray) -> float:
    x = quat_to_matrix(q_wxyz)[:, 0]  # body x axis in the world
    return float(np.arctan2(x[1], x[0]))


# --------------------------------------------------------------------------- loading
@dataclass
class Item:
    label: str
    source: str
    kind: str  # e.g. "BVH (tpose) -> G1", "Unitree csv"
    robot: RobotMotion
    human: SkeletonMotion | None = None
    info: dict = field(default_factory=dict)
    color: tuple = (110, 110, 110)
    offset: float = 0.0
    visible: bool = True
    show_human: bool = True
    metrics: dict = field(default_factory=dict)
    # display state, filled by the viewer
    handles: dict = field(default_factory=dict)


def _cache_path(path: str, robot: str, smooth: float, fps: float) -> str:
    st = os.stat(path)
    key = json.dumps([os.path.abspath(path), st.st_size, int(st.st_mtime), robot, smooth, fps])
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(CACHE, f"{stem}_{h}_{ROBOT_TAGS.get(robot, robot)}.npz")


def load_item(path: str, args) -> Item:
    """Robot motion as is, or human motion retargeted (cached) + its skeleton."""
    path = os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    name = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.basename(os.path.dirname(path))
    human_fmt = None
    if ext in HUMAN_EXT:
        human_fmt = detect_format(path)
    elif ext == ".npz":
        with np.load(path, allow_pickle=False) as d:
            keys = set(d.files)
        if "pose_body" in keys:
            human_fmt = "smplx"
        elif "dof_pos" not in keys:
            raise ValueError(f"{path}: neither a robot npz (dof_pos) nor AMASS SMPL-X (pose_body)")
    elif ext not in ROBOT_EXT:
        raise ValueError(f"unsupported file type: {path}")

    if human_fmt is None:
        robot = load_motion(path, fps=args.csv_fps)
        kind = {"robot_npz": "robot npz", "unitree_csv": "Unitree csv", "gmr_pkl": "GMR pkl"}.get(
            robot.meta.get("format"), "robot")
        info_path = os.path.splitext(path)[0] + ".json"
        info = json.load(open(info_path, encoding="utf-8")) if os.path.isfile(info_path) else {}
        return Item(label=f"{folder}/{name}", source=path, kind=kind, robot=robot, info=info)

    cached = _cache_path(path, args.robot, args.smooth, args.fps)
    if os.path.isfile(cached) and os.path.isfile(cached[:-4] + ".json"):
        robot = load_motion(cached)
        info = json.load(open(cached[:-4] + ".json", encoding="utf-8"))
        log(f"{name}: retarget from cache {os.path.relpath(cached, ROOT)}")
    else:
        log(f"{name}: retargeting ({human_fmt}) ...")
        robot, info = retarget_file(path, robot=args.robot, fmt=human_fmt, fps=args.fps, smooth_hz=args.smooth,
                                    smpl_model_dir=args.smpl_model_dir, log=None)
        os.makedirs(CACHE, exist_ok=True)
        robot.save_npz(cached)
        with open(cached[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False, default=float)
        robot = load_motion(cached)
    if human_fmt == "smplx":
        human = load_amass_npz(path, model_dir=args.smpl_model_dir, body_only=True)
    else:
        human = load_bvh(path)
    smooth = f", smooth {args.smooth:g} Hz" if args.smooth else ""
    label_fmt = {"tpose": "BVH", "lafan1": "BVH LAFAN1", "nokov": "BVH Nokov", "smplx": "SMPL-X"}[human_fmt]
    return Item(label=f"{folder}/{name}", source=path, kind=f"{label_fmt} -> GMR{smooth}", robot=robot,
                human=human, info=info)


def compute_metrics(item: Item, fk: analysis.FootKinematics | None, limits) -> None:
    m = item.robot
    out = {"duration": m.duration, "fps": m.fps, "frames": m.num_frames, **analysis.smoothness(m)}
    if fk is not None:
        out.update({k: v for k, v in analysis.foot_metrics(m, fk).items() if not k.startswith("_")})
    r = check_robot(m, QCConfig(), limits)
    out["qc"] = r.status
    out["qc_notes"] = "; ".join(r.notes)
    item.metrics = out


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
        self._build_gui()
        server.scene.set_up_direction("+z")
        server.scene.add_grid("/floor", width=40, height=40, cell_size=0.5, section_size=1.0,
                              plane_color=(235, 235, 238), plane_opacity=1.0, shadow_opacity=0.25)

    # ---------------------------------------------------------------- GUI
    def _build_gui(self) -> None:
        gui = self.server.gui
        gui.configure_theme(control_width="large")
        tabs = gui.add_tab_group()
        with tabs.add_tab("재생", icon=None):
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
            self.robot_look = gui.add_dropdown("로봇 표시", ("불투명", "반투명"), initial_value="불투명")
            self.robot_look.on_update(lambda _: self._rebuild_meshes())
            self.show_labels = gui.add_checkbox("이름표", True)
            gui.add_button("카메라 맞추기").on_click(lambda _: self.fit_camera())
        with tabs.add_tab("모션"):
            self.add_path = gui.add_text("파일 경로", "", hint="BVH / AMASS SMPL-X npz / 로봇 npz·csv·pkl")
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
        item = load_item(path, self.args)
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
            self._refresh_lists()
        log(f"added {item.label}: {item.kind}, {item.robot.num_frames} frames @ {item.robot.fps:g} fps")
        return item

    def remove(self, item: Item) -> None:
        with self.lock:
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
            vis = s.gui.add_checkbox("보이기", True)
            vis.on_update(lambda e, it=item: setattr(it, "visible", e.target.value))
            if item.human is not None:
                hv = s.gui.add_checkbox("사람 스켈레톤", True)
                hv.on_update(lambda e, it=item: setattr(it, "show_human", e.target.value))
            off = s.gui.add_number("시간 오프셋 (s)", 0.0, step=1 / 30)
            off.on_update(lambda e, it=item: self._set_offset(it, e.target.value))
            item.handles["offset_input"] = off
            s.gui.add_button("제거", color="red").on_click(lambda _, it=item: self.remove(it))

    def _item_md(self, item: Item) -> str:
        m, r = item.metrics, item.robot
        lines = [f"<span style='color:{hexcolor(item.color)}'>■</span> **{item.kind}**",
                 f"{r.num_frames} frames @ {r.fps:g} fps, {r.duration:.1f} s · QC **{m.get('qc', '?')}**"]
        res = item.info.get("ik_position_residual")
        if res:
            lines.append("IK 잔차(평균): " + ", ".join(f"{k} {v['mean_cm']} cm" for k, v in res.items()))
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
        if "human" in h:
            h["human"].visible = visible and item.show_human and bool(self.show_humans.value)
        if not visible:
            return
        local = self.t - item.offset
        inside = 0.0 <= local <= item.robot.duration
        t = np.array([np.clip(local, 0.0, item.robot.duration)])
        pos, quat = analysis.sample_root(item.robot, t)
        dof = analysis.sample_dof(item.robot, t)[0]
        qd, shift = self._display_transform(item)
        R = quat_to_matrix(qd)
        p = R @ pos[0] + shift
        h["root"].position = p
        h["root"].wxyz = quat_mul(qd, quat[0])
        h["urdf"].update_cfg(np.array([dof[i] if i is not None else 0.0 for i in h["map"]]))
        h["label"].position = p + np.array([0.0, 0.0, 0.85])
        h["label"].text = item.label if inside else f"{item.label} (범위 밖)"
        if "human" in h and h["human"].visible:
            hm = item.human
            f = int(np.clip(round(local * hm.fps), 0, hm.num_frames - 1))
            P = hm.positions[f]
            hips = hm.positions[0, 0]
            # scale about the skeleton's start point (floor level), then put that point on the robot's start
            start_r = item.robot.root_pos[0]
            Ps = item.handles["scale"] * (P - np.array([hips[0], hips[1], 0.0])) + np.array([start_r[0], start_r[1], 0.0])
            Pd = Ps @ R.T + shift
            if self.human_place.value == "로봇 옆":  # inside the robot the lines are hidden by its meshes
                Pd = Pd + np.array([0.0, 0.8, 0.0])
            b = h["bones"]
            pts = np.stack([Pd[b[:, 0]], Pd[b[:, 1]]], axis=1)
            h["human"].points = np.nan_to_num(pts)

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
            r = it.robot
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
            m = it.metrics
            legs = whole = "기준" if it is ref else "-"
            if ref is not None and it is not ref:
                joints, rmse, ov = analysis.joint_rmse(ref.robot, it.robot, ref.offset, it.offset)
                if ov > 0:
                    li = [i for i, n in enumerate(joints) if any(k in n for k in analysis.LEG_KEYS)]
                    legs, whole = f(float(np.median(rmse[li]))), f(float(np.median(rmse)))
            cols.append([f(m.get("duration")), f(m.get("acc_mean")), f(m.get("jerk_mean"), "{:.0f}"), f(m.get("vel_max")),
                         f(m.get("planted_slip_pct"), "{:.2f}"), f(m.get("penetration_pct"), "{:.2f}"),
                         f(m.get("sole_min_cm")), legs, whole, m.get("qc", "-")])
        names = ["길이 (s)", "관절 가속도 (rad/s²)", "관절 저크 (rad/s³)", "최대 관절속도 (rad/s)", "발 미끄러짐 (%)",
                 "바닥 관통 (%)", "발 최저점 (cm)", "기준 대비 다리 RMSE (°)", "기준 대비 전체 RMSE (°)", "QC"]
        head = "".join(f"<th style='color:{hexcolor(it.color)};text-align:right;padding:2px 4px'>■ {i + 1}</th>"
                       for i, it in enumerate(self.items))
        body = "".join("<tr><td style='padding:2px 4px'>" + n + "</td>" +
                       "".join(f"<td style='text-align:right;padding:2px 4px'>{c[r]}</td>" for c in cols) + "</tr>"
                       for r, n in enumerate(names))
        legend = "<br>".join(f"<span style='color:{hexcolor(it.color)}'>■ {i + 1}</span> {it.label} ({it.kind})"
                             for i, it in enumerate(self.items))
        notes = ("RMSE: 기준과 겹치는 구간의 관절별 RMSE 중앙값(시간 오프셋 반영). 발 미끄러짐: 발바닥 전체가 붙은 채 "
                 "0.3 m/s 이상으로 0.1 s 이상 움직인 프레임 비율. 바닥 관통: 발 최저점 -2 cm 아래 프레임 비율.")
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
                joints, rmse, ov = analysis.joint_rmse(ref.robot, it.robot, ref.offset, it.offset)
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
    ap.add_argument("--fps", type=float, default=30.0, help="retarget output frame rate")
    ap.add_argument("--csv-fps", type=float, default=30.0, help="frame rate of Unitree csv files")
    ap.add_argument("--smpl-model-dir", default=os.environ.get("SMPL_MODEL_DIR", os.path.join(ROOT, "models")))
    ap.add_argument("--max-shift", type=float, default=3.0, help="search range of the automatic time alignment (s)")
    ap.add_argument("--mesh-cell", type=float, default=0.004,
                    help="simplify robot meshes on this grid (m) before sending them to the browser; 0 = full detail")
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only; 0.0.0.0 to share on the LAN")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    urdf = load_robot_urdf(args.urdf, args.mesh_cell)
    server = viser.ViserServer(host=args.host, port=args.port, label="K-Humanoid motion compare")
    viewer = Viewer(server, urdf, args)

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
    while True:
        now = time.perf_counter()
        viewer.tick(now - last)
        last = now
        time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - now)))


if __name__ == "__main__":
    sys.exit(main())
