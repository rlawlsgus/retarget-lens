"""Compare motions retargeted to the same humanoid, side by side, in the browser.

    python tools/compare_viewer.py data/raw/cmu_bvh/143_11.bvh data/raw/amass_cmu_smplx/143_11_stageii.npz
    python tools/compare_viewer.py data/raw/unitree_lafan1_g1/walk1_subject1.csv data/retargeted/lafan1_bvh/walk1_subject1_g1.npz
    -> open http://127.0.0.1:8080

The desktop editor (tools/editor.py) shows the same scene with editor-style panels;
both are front ends of retlens/app/scene.py.

Inputs (any mix, also addable from the GUI):
  human motion  .bvh, .fbx (through Blender), AMASS SMPL-X .npz -> retargeted to the robot
                with tools/retarget.py's pipeline (cached in data/cache/retarget/),
                shown with the source skeleton overlaid at robot scale
  robot motion  project .npz, Unitree .csv, GMR .pkl -> shown as is; Isaac physics
                results (tools/isaac_replay.py --physics, <clip>_sim.npz) included

Panels: playback (time, speed, layout side-by-side / overlay, start alignment), one
folder per motion (visibility, time offset, details, video), and analysis against a
reference motion (automatic time alignment on the leg joints, joint-angle plot,
per-joint RMSE, smoothness, planted-foot slip, floor penetration, QC).
The robot model is GMR's G1 URDF (meshes from ..\\GMR\\assets\\unitree_g1).

Physics mode (button on the playback tab, or --physics): every robot motion is shown as
simulated (gravity, floor contact, joint torque limits) instead of its joint angles. The
"균형 제어" dropdown (or --balance) picks the simulation: Isaac Sim PhysX with the pelvis
harness (tools/isaac_replay.py --physics via retlens/physics_runner.py, cache
data/cache/physics/; Isaac Sim's EULA must be accepted: --isaac-accept-eula), or MuJoCo
with no controller / the GMT tracking policy (retlens/policy_runner.py, cache
data/cache/policy/). Missing results are computed in the background, one clip at a time.

리타게팅 보정 (motion tab, or --foot-flat / --swing-clearance): 디딤발 평평 보정 and 스윙 발 보정
for the human motions added next; motions already shown keep theirs, so adding the same file
again shows before and after side by side.
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import plotly.graph_objects as go  # noqa: E402
import viser  # noqa: E402

from retlens.app.scene import (BALANCE, METRIC_NOTES, RETARGET_NOTE, RETARGET_TIPS,  # noqa: E402
                                 SWING_CLEARANCE_CM, MotionScene, add_scene_arguments, hexcolor, load_robot_urdf,
                                 scene_options)
from retlens import paths, settings  # noqa: E402
from retlens.compare import MOTION_EXT, Item, library_files, save_upload  # noqa: E402

ASSIST_OPTIONS = {"켬 (기본)": 1.0, "끔 (--assist 0)": 0.0}


def log(msg: str) -> None:
    print(f"[compare_viewer] {msg}", flush=True)


class Viewer:
    """viser control panel bound to a MotionScene."""

    def __init__(self, server: viser.ViserServer, scene: MotionScene, library: list | None = None):
        self.server, self.scene = server, scene
        self.library_roots = library or settings.library_dirs()  # the defaults + RetLens 환경 설정 folders
        self._last_plot = 0.0
        self._plot_dirty = True
        self._last_status = 0.0
        self._setting_slider = False
        self._folders: dict[int, object] = {}  # id(item) -> its folder in "목록"
        self._build_gui()
        scene.listen(self._on_scene)
        self._update_status(force=True)

    # ---------------------------------------------------------------- GUI
    def _build_gui(self) -> None:
        gui, sc = self.server.gui, self.scene
        gui.configure_theme(control_width="large")
        tabs = gui.add_tab_group()
        with tabs.add_tab("재생", icon=None):
            with gui.add_folder("물리 모드"):
                self.phys_btn = gui.add_button(
                    "물리 모드 켜기",
                    hint="켜면 각 로봇 동작을 관절각대로 그리지 않고, 아래 '균형 제어'로 고른 물리 시뮬레이션 결과로 바꿔 "
                         "그립니다(중력·바닥 접촉·관절 토크 한계). 결과가 없는 클립은 백그라운드로 돌려 만듭니다"
                         "(Isaac은 짧은 클립 약 1분, MuJoCo는 몇 초)")
                self.phys_btn.on_click(lambda e: sc.set_physics(
                    not sc.physics_on, f"button, client {getattr(e.client, 'client_id', '?')}"))
                self.balance_names = {self._balance_name(k): k for k in BALANCE}
                self.phys_balance = gui.add_dropdown(
                    "균형 제어", tuple(self.balance_names), initial_value=self._balance_name(sc.balance),
                    hint="보조 힘 (Isaac): 골반 가상 하네스로 버팀. 없음 (MuJoCo): 균형 제어 없이 관절각만 따라감(대개 1–2초 "
                         "안에 넘어짐). 추적 정책 (GMT): 실제 로봇처럼 균형을 잡는 공개 G1 추적 정책. 고르면 물리 모드가 켜집니다")
                self.phys_balance.on_update(lambda _: self._on_balance())
                self.phys_balance_note = gui.add_markdown("")  # why a picked mode cannot run here
                self.phys_assist = gui.add_dropdown(
                    "골반 보조 힘", tuple(ASSIST_OPTIONS), initial_value="켬 (기본)",
                    hint="균형 제어기 대신 골반을 원래 위치·자세로 당기는 가상 하네스입니다. 끄면 균형 피드백이 없어 "
                         "걷기도 대부분 1–2초 안에 넘어집니다")
                self.phys_assist.on_update(lambda _: sc.set_assist(ASSIST_OPTIONS.get(self.phys_assist.value, 1.0)))
                self.phys_assist.disabled = sc.balance != "isaac"
                gui.add_button("작업 취소", hint="대기 중이거나 돌고 있는 물리 계산(Isaac·MuJoCo)과 동영상 녹화를 멈춥니다").on_click(
                    lambda _: sc.cancel_jobs())
                self.phys_status = gui.add_markdown("")
            self.play_btn = gui.add_button("재생")
            self.play_btn.on_click(lambda _: sc.toggle_play())
            self.time_slider = gui.add_slider("시간 (s)", min=0.0, max=1.0, step=1 / 30, initial_value=0.0)
            self.time_slider.on_update(self._on_slider)
            with gui.add_folder("이동", expand_by_default=False):
                gui.add_button("-1 프레임").on_click(lambda _: sc.step(-1))
                gui.add_button("+1 프레임").on_click(lambda _: sc.step(1))
                gui.add_button("처음으로").on_click(lambda _: sc.seek(0.0))
            v = sc.view
            self.speed = gui.add_slider("재생 속도", min=0.1, max=2.0, step=0.05, initial_value=v.speed)
            self.speed.on_update(lambda _: setattr(v, "speed", float(self.speed.value)))
            self.loop = gui.add_checkbox("반복", v.loop)
            self.loop.on_update(lambda _: setattr(v, "loop", bool(self.loop.value)))
            self.layout = gui.add_dropdown("배치", ("나란히", "겹쳐서"), initial_value="나란히")
            self.layout.on_update(lambda _: setattr(v, "side_by_side", self.layout.value == "나란히"))
            self.spacing = gui.add_number("간격 (m)", v.spacing, min=0.3, max=5.0, step=0.1)
            self.spacing.on_update(lambda _: setattr(v, "spacing", float(self.spacing.value)))
            self.align = gui.add_checkbox("시작 위치·방향 맞춤", v.align,
                                          hint="각 모션의 시작 골반을 원점, 진행 방향을 +x로 옮겨 그립니다")
            self.align.on_update(lambda _: setattr(v, "align", bool(self.align.value)))
            self.show_humans = gui.add_checkbox("사람 스켈레톤", v.show_humans,
                                                hint="리타게팅 원본을 로봇 크기로 줄여 그립니다")
            self.show_humans.on_update(lambda _: setattr(v, "show_humans", bool(self.show_humans.value)))
            self.human_place = gui.add_dropdown("스켈레톤 위치", ("로봇 옆", "로봇과 겹쳐서"), initial_value="로봇 옆")
            self.human_place.on_update(lambda _: setattr(v, "human_beside", self.human_place.value == "로봇 옆"))
            self.human_look = gui.add_dropdown(
                "사람 표시", ("막대", "몸 메시 (SMPL-X)"), initial_value="막대",
                hint="SMPL-X 입력은 몸 표면(선형 블렌드 스키닝)으로 그릴 수 있습니다. BVH / FBX는 막대만 있습니다")
            self.human_look.on_update(lambda _: self._set_view(body_mesh=self.human_look.value.startswith("몸")))
            self.robot_look = gui.add_dropdown("로봇 표시", ("불투명", "반투명"), initial_value="불투명")
            self.robot_look.on_update(lambda _: self._set_view(robot_translucent=self.robot_look.value == "반투명"))
            self.show_labels = gui.add_checkbox("이름표", v.show_labels)
            self.show_labels.on_update(lambda _: setattr(v, "show_labels", bool(self.show_labels.value)))
            self.show_balance = gui.add_checkbox(
                "균형 표시", v.show_balance, hint="바닥에 지지다각형(초록, 발이 닿은 발바닥 점), 질량중심 투영(파랑), ZMP(빨강)")
            self.show_balance.on_update(lambda _: setattr(v, "show_balance", bool(self.show_balance.value)))
            gui.add_button("카메라 맞추기").on_click(lambda _: sc.fit_camera())
        with tabs.add_tab("모션"):
            with gui.add_folder("모션 고르기"):
                self.lib_folder = gui.add_dropdown("폴더", ("-",), hint="data/raw(원본), data/retargeted(로봇), "
                                                   "data/uploads(내 PC에서 연 파일), reports(물리 결과) 아래의 모션 파일")
                self.lib_folder.on_update(lambda _: self._refresh_files())
                self.lib_search = gui.add_text("이름 검색", "", hint="이름 일부(예: 143_11)를 넣으면 모든 폴더에서 찾습니다. "
                                                                 "같은 촬영의 BVH·FBX·SMPL-X를 한 번에 찾을 때 편합니다")
                self.lib_search.on_update(lambda _: self._refresh_files())
                self.lib_file = gui.add_dropdown("파일", ("-",))
                gui.add_button("선택한 파일 추가").on_click(lambda _: self._add_from_library())
                gui.add_button("목록 새로고침", color="gray", hint="새로 생긴 파일을 다시 찾습니다").on_click(
                    lambda _: self._refresh_library())
                self.upload = gui.add_upload_button(
                    "파일 열기 (내 PC)", mime_type=",".join(MOTION_EXT),
                    hint="BVH / FBX / AMASS SMPL-X npz / 로봇 npz·csv·pkl. 고른 파일은 data/uploads에 복사해 엽니다")
                self.upload.on_upload(lambda _: self._add_upload())
            with gui.add_folder("경로 직접 입력", expand_by_default=False):
                self.add_path = gui.add_text("파일 경로", "", hint="BVH / FBX / AMASS SMPL-X npz / 로봇 npz·csv·pkl "
                                                                  "(Isaac 물리 결과 *_sim.npz 포함)")
                gui.add_button("경로로 추가").on_click(lambda _: self._add_from_gui())
            with gui.add_folder("리타게팅 보정", expand_by_default=False):
                self.foot_flat = gui.add_checkbox("디딤발 평평 보정", sc.opts.foot_flat,
                                                  hint=f"{RETARGET_TIPS['foot_flat']}. {RETARGET_NOTE}")
                self.foot_flat.on_update(lambda _: self._on_retarget())
                self._swing_cm = sc.opts.swing_clearance_cm or SWING_CLEARANCE_CM  # the command line's height, if given
                self.swing = gui.add_checkbox(f"스윙 발 보정 ({self._swing_cm:g} cm)", sc.opts.swing_clearance_cm > 0,
                                              hint=f"{RETARGET_TIPS['swing']}. {RETARGET_NOTE}")
                self.swing.on_update(lambda _: self._on_retarget())
            self.status = gui.add_markdown("")
            self.motion_folder = gui.add_folder("목록")
        self._library: dict[str, list[str]] = {}
        self._lib_options: dict[str, str] = {}
        self._refresh_library()
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

    def _set_view(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.scene.view, k, v)
        self.scene.view_changed(*kw)
        self._mark_plot()

    # ---------------------------------------------------------------- scene events
    def _on_scene(self, event: str, payload) -> None:
        if event == "items":
            self._sync_item_folders()
            self._refresh_lists()
        elif event == "item":
            self._update_slider_range()
            self.refresh_analysis()
            item = payload
            if isinstance(item, Item) and "ui_offset" in item.handles:
                box = item.handles["ui_offset"]
                if abs(float(box.value) - item.offset) > 1e-6:  # e.g. auto-aligned; equal values stop the echo
                    box.value = round(item.offset, 4)
            self._update_status(force=True)
        elif event == "status":
            self._update_status(force=True)
            self.refresh_analysis()
            self._sync_retarget()
        elif event == "time":
            self.play_btn.label = "일시정지" if self.scene.playing else "재생"

    # ---------------------------------------------------------------- adding motions
    def _add_from_gui(self) -> None:
        p = self.add_path.value.strip().strip('"')
        if not p:
            return
        if not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        self._add_path(p)

    def _add_path(self, p: str) -> None:
        self.status.content = f"불러오는 중: `{os.path.basename(p)}` (처음 리타게팅하는 사람 모션이면 수십 초)"
        try:
            self.scene.add(p)
            self.status.content = f"추가됨: `{os.path.basename(p)}`"
        except Exception as e:
            self.status.content = f"**실패**: {type(e).__name__}: {e}"

    def _refresh_library(self) -> None:
        """Rescan the library folders (keeps the current folder choice when it still exists)."""
        self._library = library_files(self.library_roots)
        opts = tuple(f"{d}  ({len(v)})" for d, v in self._library.items()) or ("-",)
        cur = self.lib_folder.value
        self.lib_folder.options = opts
        if cur in opts:
            self.lib_folder.value = cur
        else:  # start where the original captures are
            self.lib_folder.value = next((o for o in opts if o.startswith("data/raw/cmu_bvh")), opts[0])
        self._refresh_files()

    def _refresh_files(self) -> None:
        q = self.lib_search.value.strip().lower()
        if q:  # every folder, shown with its folder; names that start with the query first (05_02 before 105_02)
            hits = [p for v in self._library.values() for p in v if q in os.path.basename(p).lower()]
            hits = sorted(hits, key=lambda p: not os.path.basename(p).lower().startswith(q))[:300]
            self._lib_options = {paths.rel(p).replace(os.sep, "/"): p for p in hits}
        else:
            folder = self.lib_folder.value.rsplit("  (", 1)[0]
            self._lib_options = {os.path.basename(p): p for p in self._library.get(folder, [])}
        opts = tuple(self._lib_options) or (("찾은 파일 없음",) if q else ("-",))
        self.lib_file.options = opts
        self.lib_file.value = opts[0]

    def _add_from_library(self) -> None:
        p = self._lib_options.get(self.lib_file.value)
        if p:
            self._add_path(p)

    def _add_upload(self) -> None:
        f = self.upload.value
        if f is None:
            return
        if not f.name.lower().endswith(MOTION_EXT):
            self.status.content = f"**열 수 없는 형식**: `{f.name}` (BVH / FBX / npz / csv / pkl)"
            return
        path = save_upload(f.name, f.content)
        self._add_path(path)
        self._refresh_library()

    # ---------------------------------------------------------------- per-motion folders
    def _sync_item_folders(self) -> None:
        """One folder per motion: build the new ones, drop the ones of removed motions."""
        items = list(self.scene.items)
        for it in items:
            if "ui_folder" not in it.handles:
                self._build_item_folder(it)
        live = {id(it) for it in items}
        for key, f in list(self._folders.items()):
            if key not in live:
                f.remove()
                del self._folders[key]

    def _build_item_folder(self, item: Item) -> None:
        s, sc = self.server, self.scene
        with self.motion_folder:
            f = s.gui.add_folder(item.label)
        item.handles["ui_folder"] = f
        self._folders[id(item)] = f
        with f:
            s.gui.add_markdown(self._item_md(item))
            item.handles["ui_phys_md"] = s.gui.add_markdown("")
            s.gui.add_button(
                "동영상 저장", hint="Isaac Sim에서 사람(원본이 있으면)과 로봇을 나란히 녹화해 MP4로 저장합니다. "
                                 "물리 모드가 켜져 있으면 물리 시뮬레이션 결과를 녹화합니다").on_click(
                lambda _, it=item: self.save_video(it))
            item.handles["ui_video_md"] = s.gui.add_markdown("")
            dl = s.gui.add_button("동영상 내려받기", color="green", visible=False,
                                  hint="저장된 동영상을 이 브라우저로 내려받습니다")
            dl.on_click(lambda e, it=item: self._download_video(it, e.client))
            item.handles["ui_video_dl"] = dl
            vis = s.gui.add_checkbox("보이기", True)
            vis.on_update(lambda e, it=item: sc.set_visible(it, e.target.value))
            if item.human is not None:
                hv = s.gui.add_checkbox("사람 스켈레톤", True)
                hv.on_update(lambda e, it=item: sc.set_show_human(it, e.target.value))
            off = s.gui.add_number("시간 오프셋 (s)", 0.0, step=1 / 30)
            off.on_update(lambda e, it=item: sc.set_offset(it, e.target.value))
            item.handles["ui_offset"] = off
            s.gui.add_button("제거", color="red").on_click(lambda _, it=item: sc.remove(it))

    def _item_md(self, item: Item) -> str:
        rows = dict(self.scene.item_facts(item))
        lines = [f"<span style='color:{hexcolor(item.color)}'>■</span> **{item.kind}**",
                 f"{rows['길이']} · QC **{rows['QC']}**"]
        for k in ("IK 잔차(평균)", "디딤발 평평", "물리 결과", "참고"):
            if k in rows:
                lines.append(f"{k}: {rows[k]}")
        lines.append(f"`{rows['파일']}`")
        return "  \n".join(lines)

    def _balance_name(self, mode: str) -> str:
        """The dropdown entry: the mode's name, marked when it cannot run here (picking it shows why
        under the dropdown)."""
        return BALANCE[mode] + (" - 쓸 수 없음" if self.scene.balance_problem(mode) else "")

    def _on_balance(self) -> None:
        if getattr(self, "_reverting", False):
            return
        sc = self.scene
        mode = self.balance_names.get(self.phys_balance.value, "isaac")
        why = sc.balance_problem(mode)
        if why:
            self.phys_balance_note.content = f"**{BALANCE[mode]}**를 쓸 수 없습니다: {why}"
            self._reverting = True
            try:
                self.phys_balance.value = self._balance_name(sc.balance)  # back to the mode in use
            finally:
                self._reverting = False
            return
        self.phys_balance_note.content = ""
        sc.set_balance(mode)
        self.phys_assist.disabled = mode != "isaac"
        if not sc.physics_on:
            sc.set_physics(True, f"balance {mode}")

    def _on_retarget(self) -> None:
        """리타게팅 보정 checkboxes: the scene's settings for the human motions opened next."""
        if getattr(self, "_syncing", False):
            return
        r = self.scene.set_retarget(foot_flat=bool(self.foot_flat.value),
                                    swing_clearance_cm=self._swing_cm if self.swing.value else 0.0)
        on = [name for name, yes in (("디딤발 평평", r["foot_flat"]),
                                     (f"스윙 발 {r['swing_clearance_cm']:g} cm", r["swing_clearance_cm"] > 0)) if yes]
        self.status.content = f"리타게팅 보정: **{', '.join(on) or '끔'}**. {RETARGET_NOTE}"

    def _sync_retarget(self) -> None:
        """The checkboxes show the scene's settings (the editor window or the API can change them)."""
        o = self.scene.opts
        if o.swing_clearance_cm > 0 and o.swing_clearance_cm != self._swing_cm:
            self._swing_cm = o.swing_clearance_cm
            self.swing.label = f"스윙 발 보정 ({self._swing_cm:g} cm)"
        self._syncing = True
        try:
            for box, on in ((self.foot_flat, o.foot_flat), (self.swing, o.swing_clearance_cm > 0)):
                if bool(box.value) != on:
                    box.value = on
        finally:
            self._syncing = False

    def save_video(self, item: Item) -> None:
        try:
            job = self.scene.save_video(item)
        except Exception as e:  # Isaac Sim not found
            item.handles["ui_video_md"].content = f"동영상: **실행할 수 없음** ({type(e).__name__}: {e})"
            return
        physics = self.scene.physics_on and not self.scene.is_sim_result(item)
        self.status.content = (f"동영상 {'대기열에 추가' if job.active else '이미 있음'}: {item.label} "
                               f"({self.scene.mode_label() if physics else '기구학'})")

    def _download_video(self, item: Item, client) -> None:
        path = self.scene.video_file(item)
        if not path or not os.path.isfile(path) or client is None:
            return
        with open(path, "rb") as f:
            client.send_file_download(os.path.basename(path), f.read())

    def _update_status(self, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and now - self._last_status < 0.5:
            return
        self._last_status = now
        sc = self.scene
        self.phys_btn.label = "물리 모드 끄기" if sc.physics_on else "물리 모드 켜기"
        try:
            self.phys_btn.color = "teal" if sc.physics_on else None
        except Exception:
            pass
        jobs = sc.jobs_summary()
        head = (f"**켜짐** · {sc.mode_label()}" if sc.physics_on else "**꺼짐** · 관절각대로 그리는 기구학 재생") \
            + (f" · 작업 {jobs} 대기·진행 중" if jobs else "")
        lines = [head]
        items = [it for it in list(sc.items) if not sc.is_sim_result(it)]
        if sc.physics_on:
            lines += [f"<span style='color:{hexcolor(it.color)}'>■</span> {it.label}: {sc.job_text(it)}" for it in items]
            if sc.phys_error and not items:
                lines.append(f"실행할 수 없음: {sc.phys_error}")
        self.phys_status.content = "  \n".join(lines)
        for it in list(sc.items):
            if "ui_phys_md" in it.handles:
                it.handles["ui_phys_md"].content = (f"물리: {sc.job_text(it)}" if (sc.physics_on or it.handles.get("phys"))
                                                    else "")
            if "ui_video_md" in it.handles:
                text = sc.video_text(it)
                it.handles["ui_video_md"].content = text.replace("저장됨: ", "저장됨: `") + "`" if "저장됨" in text else text
                it.handles["ui_video_dl"].visible = sc.video_file(it) is not None

    # ---------------------------------------------------------------- analysis
    def _ref_item(self) -> Item | None:
        return next((it for it in self.scene.items if it.label == self.ref.value), None)

    def auto_align(self) -> None:
        ref = self._ref_item()
        if ref is None:
            return
        notes = self.scene.auto_align(ref)
        self._update_slider_range()
        self.refresh_analysis()
        self.status.content = "시간 정렬: " + "; ".join(notes)

    def refresh_analysis(self) -> None:
        self._update_table()
        self._update_rmse()
        self._mark_plot()

    def _refresh_lists(self) -> None:
        labels = tuple(it.label for it in self.scene.items) or ("-",)
        cur = self.ref.value
        self.ref.options = labels
        self.ref.value = cur if cur in labels else labels[0]
        opts = tuple(self.scene.graph_keys())
        cur = self.joint.value
        self.joint.options = opts
        self.joint.value = cur if cur in opts else (next((j for j in opts if "left_knee" in j), opts[0]))
        self._update_slider_range()
        self.refresh_analysis()

    def _update_slider_range(self) -> None:
        lo, hi = self.scene.time_range()
        self.time_slider.min, self.time_slider.max = lo, hi

    def _mark_plot(self) -> None:
        self._plot_dirty = True

    def _update_plot(self) -> None:
        fig = go.Figure()
        key = self.joint.value
        w = float(self.window.value or 0.0)
        for it, tt, y in self.scene.series(key, w):
            fig.add_trace(go.Scatter(x=tt, y=y, mode="lines", name=it.label, line=dict(color=hexcolor(it.color), width=1.6)))
        t = self.scene.t
        fig.add_vline(x=t, line_width=1, line_color="black")
        unit = "m" if key.startswith("골반 높이") else "m/s" if key.startswith("골반 수평속도") else "°"
        fig.update_layout(title=dict(text=f"{key} [{unit}]", font=dict(size=13)), margin=dict(l=40, r=10, t=30, b=30),
                          legend=dict(orientation="h", y=-0.2, font=dict(size=10)), xaxis_title="t (s)",
                          template="plotly_white")
        if w > 0:
            fig.update_xaxes(range=[t - w / 2, t + w / 2])
        self.plot.figure = fig

    def _update_table(self) -> None:
        """Metrics as rows, motions as columns (fits the side panel)."""
        names, cols = self.scene.metric_table(self._ref_item())
        items = [it for it, _ in cols]
        head = "".join(f"<th style='color:{hexcolor(it.color)};text-align:right;padding:2px 4px'>■ {i + 1}</th>"
                       for i, it in enumerate(items))
        body = "".join("<tr><td style='padding:2px 4px'>" + n + "</td>" +
                       "".join(f"<td style='text-align:right;padding:2px 4px'>{v[r]}</td>" for _, v in cols) + "</tr>"
                       for r, n in enumerate(names))
        legend = "<br>".join(f"<span style='color:{hexcolor(it.color)}'>■ {i + 1}</span> {it.label} ({it.kind})"
                             for i, it in enumerate(items))
        self.table.content = (f"<div style='font-size:11px'>{legend}<table style='width:100%;border-collapse:collapse;"
                              f"margin-top:4px'><tr><th></th>{head}</tr>{body}</table>"
                              f"<div style='color:#777;margin-top:4px'>{METRIC_NOTES}</div></div>")

    def _update_rmse(self) -> None:
        ref = self._ref_item()
        fig = go.Figure()
        if ref is not None:
            for it, joints, rmse in self.scene.joint_rmse(ref):
                fig.add_trace(go.Bar(y=[j.replace("_joint", "") for j in joints], x=rmse, orientation="h",
                                     name=it.label, marker_color=hexcolor(it.color)))
        fig.update_layout(title=dict(text=f"관절별 RMSE (°) vs {self.ref.value}", font=dict(size=13)), barmode="group",
                          margin=dict(l=130, r=10, t=30, b=30), template="plotly_white",
                          legend=dict(orientation="h", y=-0.05, font=dict(size=10)),
                          yaxis=dict(autorange="reversed", tickfont=dict(size=9)))
        self.rmse_plot.figure = fig

    # ---------------------------------------------------------------- playback
    def _on_slider(self, _) -> None:
        if not self._setting_slider:
            self.scene.seek(float(self.time_slider.value))
            self._mark_plot()

    def tick(self, dt: float) -> None:
        sc = self.scene
        sc.tick(dt)
        if sc.playing:
            self._setting_slider = True
            self.time_slider.value = round(sc.t, 4)
            self._setting_slider = False
        if sc.physics_on or sc.jobs_busy():
            self._update_status()
        now = time.perf_counter()
        if self._plot_dirty and (not sc.playing or now - self._last_plot > 0.25):
            self._update_plot()
            self._last_plot = now
            self._plot_dirty = sc.playing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scene_arguments(ap)
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only; 0.0.0.0 to share on the LAN")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    urdf = load_robot_urdf(args.urdf, args.mesh_cell, log=log)
    server = viser.ViserServer(host=args.host, port=args.port, label="RetLens motion compare")
    scene = MotionScene(server, urdf, scene_options(args), log=log)
    viewer = Viewer(server, scene, args.library)
    atexit.register(scene.shutdown)  # no Isaac process outlives the viewer
    server.on_client_connect(lambda c: log(f"client {c.client_id} connected"))
    server.on_client_disconnect(lambda c: log(f"client {c.client_id} disconnected"))
    if args.body_mesh:
        scene.view.body_mesh = True
        viewer.human_look.value = "몸 메시 (SMPL-X)"
    if args.physics:
        scene.set_physics(True, "--physics")

    server.initial_camera.position = (3.0, -3.0, 1.8)
    server.initial_camera.look_at = (0.0, 0.0, 0.75)
    for p in args.inputs:
        try:
            scene.add(p)
        except Exception as e:
            log(f"could not load {p}: {type(e).__name__}: {e}")
    viewer.tick(0.0)
    scene.fit_camera()
    log(f"open http://{'127.0.0.1' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}")
    last = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            viewer.tick(now - last)
            last = now
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - now)))
    except KeyboardInterrupt:
        scene.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
