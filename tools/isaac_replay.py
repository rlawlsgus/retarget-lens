"""Replay human mocap and/or retargeted robot motion in Isaac Sim for validation.

Run with Isaac Sim's Python, or plain `python` inside the activated k-humanoid env:

    C:\\isaacsim\\python.bat tools\\isaac_replay.py --human data\\samples\\synthetic_walk_glitch.bvh
    C:\\isaacsim\\python.bat tools\\isaac_replay.py --robot-motion data\\samples\\synthetic_g1_walk.npz
    C:\\isaacsim\\python.bat tools\\isaac_replay.py --human clip.bvh --robot-motion clip_g1.npz

Human motion is drawn as a stick figure (joints = spheres, bones = cylinders) and
turns red on frames that QC hard-flags. Robot motion is replayed kinematically
(teleported every frame, gravity off) on the robot articulation; the default
robot is the Unitree G1 from the Isaac Sim asset library, a stand-in until the
LG humanoid asset arrives (--robot-usd).

Headless batch check: replays every frame once, measures the robot's foot soles
in the simulator, checks joint limits read from the robot asset, saves a few
snapshots and writes <check-out>/<clip>_sim_check.json:

    C:\\isaacsim\\python.bat tools\\isaac_replay.py --robot-motion clip.npz --headless --check-out reports\\sim

Video (implies --headless; MP4 needs ffmpeg on PATH, otherwise a GIF is written):

    python tools\\isaac_replay.py --human clip.bvh --robot-motion clip_g1.npz --video reports\\videos\\clip.mp4
    python tools\\isaac_replay.py --human long.bvh --robot-motion long_g1.npz --video long.mp4 --start 30 --end 45
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

# Asset-library locations tried for the default robot (the layout changed across releases).
G1_ASSET_CANDIDATES = [
    "/Isaac/Robots_Multiphysics/Unitree/G1/g1.usda",
    "/Isaac/Robots_Multiphysics/Unitree/G1/g1.usd",
    "/Isaac/Robots/Unitree/G1/g1.usda",
    "/Isaac/Robots/Unitree/G1/g1.usd",
]


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--human", help="human motion: .bvh / .c3d / AMASS .npz")
    ap.add_argument("--robot-motion", help="robot motion: project .npz / Unitree .csv / GMR .pkl")
    ap.add_argument("--robot-usd", default=None, help="robot USD file (default: Unitree G1 from the asset library)")
    ap.add_argument("--robot-offset", type=float, nargs=3, default=[0.0, 1.2, 0.0],
                    help="xyz offset of the robot when shown next to the human (m)")
    ap.add_argument("--up-axis", default=None, help="up axis of the human file (BVH default y, C3D default z)")
    ap.add_argument("--smpl-model-dir", default=None, help="SMPL/SMPL-X model folder for AMASS npz")
    ap.add_argument("--csv-fps", type=float, default=30.0, help="frame rate of Unitree csv files")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed")
    ap.add_argument("--no-loop", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no window: replay every frame once, then exit")
    ap.add_argument("--check-out", default=None, help="folder for the sim-check JSON + snapshots")
    ap.add_argument("--snapshots", type=int, default=4, help="number of evenly spaced snapshots (check mode)")
    ap.add_argument("--stride", type=int, default=1, help="check mode: evaluate every n-th frame")
    ap.add_argument("--quit-after", type=float, default=0.0, help="GUI: close after N seconds (smoke tests)")
    ap.add_argument("--qc-config", default=os.path.join(ROOT, "configs", "qc.yaml"), help="QC thresholds (yaml)")
    ap.add_argument("--video", default=None, help="record the replay to this .mp4 (or .gif); implies --headless")
    ap.add_argument("--video-fps", type=float, default=30.0, help="frame rate of --video")
    ap.add_argument("--start", type=float, default=0.0, help="check/video mode: first second to replay")
    ap.add_argument("--end", type=float, default=None, help="check/video mode: last second to replay")
    args, _ = ap.parse_known_args()
    if not args.human and not args.robot_motion:
        ap.error("give --human and/or --robot-motion")
    if args.video:
        args.headless = True
        if not args.check_out:  # keep the check JSON / snapshots next to the video, not in reports/sim_check
            args.check_out = os.path.dirname(os.path.abspath(args.video))
    if args.headless and not args.check_out:
        args.check_out = os.path.join(ROOT, "reports", "sim_check")
    return args


args = parse_args()

# The k-humanoid env has its own torch (GMR needs it). isaacsim/__init__ imports
# torch whenever it can find one, and the env's torch pulls in the env's numpy
# before Kit starts; Kit's import hook then serves numpy submodules and scipy
# from its own bundle on top of it and numpy.fft fails to load (DLL error),
# taking the core prims extensions down. Hide torch for that one import only:
# once Kit runs, its import hook resolves torch to Isaac's bundled copy
# (omni.isaac.ml_archive), as it does in an env without torch.
_env_torch_hidden = "torch" not in sys.modules
if _env_torch_hidden:
    sys.modules["torch"] = None
from isaacsim import SimulationApp  # noqa: E402

if _env_torch_hidden:
    del sys.modules["torch"]

simulation_app = SimulationApp({"headless": args.headless, "width": 1600, "height": 900})

import carb  # noqa: E402
import isaacsim.core.experimental.utils.app as app_utils  # noqa: E402
import isaacsim.core.experimental.utils.stage as stage_utils  # noqa: E402
import numpy as np  # noqa: E402
import omni.client  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.experimental.prims import Articulation, RigidPrim, XformPrim  # noqa: E402
from isaacsim.core.utils.viewports import set_camera_view  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, Vt  # noqa: E402

from khumanoid.io import load_motion  # noqa: E402
from khumanoid.motion import RobotMotion, SkeletonMotion  # noqa: E402
from khumanoid.qc import QCConfig, _sustained, check_motion  # noqa: E402
from khumanoid.rotations import matrix_to_quat, quat_from_two_vectors, quat_to_matrix  # noqa: E402

COLORS = {
    "joint": (0.15, 0.45, 0.95),
    "bone": (0.75, 0.75, 0.78),
    "bad": (0.95, 0.15, 0.1),
    "marker": (0.1, 0.8, 0.4),
}


def log(msg: str) -> None:
    print(f"[isaac_replay] {msg}", flush=True)


# --------------------------------------------------------------------------- scene
def make_material(stage, path: str, rgb) -> UsdShade.Material:
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def build_scene(stage) -> None:
    """Lights, a visual-only floor (no collider: replay must show penetration, not
    resolve it) with a 1 m grid, and a zero-gravity physics scene."""
    UsdGeom.Xform.Define(stage, "/World")
    UsdLux.DomeLight.Define(stage, "/World/DomeLight").CreateIntensityAttr(500.0)
    sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
    sun.CreateIntensityAttr(1500.0)
    UsdGeom.Xformable(sun).AddRotateXYZOp().Set(Gf.Vec3f(-40, 0, 30))

    s = 30.0
    floor = UsdGeom.Mesh.Define(stage, "/World/Floor")
    floor.CreatePointsAttr([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)])
    floor.CreateFaceVertexCountsAttr([4])
    floor.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    UsdShade.MaterialBindingAPI.Apply(floor.GetPrim()).Bind(
        make_material(stage, "/World/Looks/Floor", (0.16, 0.17, 0.19)))
    pts, counts = [], []
    for v in np.arange(-10, 10.01, 1.0):
        pts += [(v, -10, 0.002), (v, 10, 0.002), (-10, v, 0.002), (10, v, 0.002)]
        counts += [2, 2]
    grid = UsdGeom.BasisCurves.Define(stage, "/World/FloorGrid")
    grid.CreateTypeAttr(UsdGeom.Tokens.linear)
    grid.CreatePointsAttr(pts)
    grid.CreateCurveVertexCountsAttr(counts)
    grid.CreateWidthsAttr([0.008] * len(pts))
    grid.CreateDisplayColorAttr([(0.6, 0.6, 0.65)])

    scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    scene.CreateGravityMagnitudeAttr(0.0)  # kinematic replay


def look_at_quat(eye, target) -> np.ndarray:
    """wxyz orientation of a USD camera (looks down -Z, +Y up) at eye looking at target."""
    f = np.asarray(target, float) - np.asarray(eye, float)
    f /= np.linalg.norm(f)
    z = -f
    x = np.cross([0.0, 0.0, 1.0], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return matrix_to_quat(np.stack([x, y, z], axis=1))


# --------------------------------------------------------------------------- human
class SkeletonViz:
    """Stick figure as one PointInstancer: protos 0/1 = joint ok/bad, 2/3 = bone ok/bad."""

    def __init__(self, stage, path: str, motion: SkeletonMotion, bad_frames: np.ndarray):
        self.m = motion
        self.bad = bad_frames
        self.bones = np.array(motion.bones(), dtype=int).reshape(-1, 2)
        markers = motion.kind == "markers"
        self.joint_r = 0.012 if markers else 0.03
        self.bone_r = 0.015

        self.inst = UsdGeom.PointInstancer.Define(stage, path)
        protos = []
        for name, is_sphere, color in (
            ("JointOk", True, COLORS["marker" if markers else "joint"]),
            ("JointBad", True, COLORS["bad"]),
            ("BoneOk", False, COLORS["bone"]),
            ("BoneBad", False, COLORS["bad"]),
        ):
            p = f"{path}/Protos/{name}"
            if is_sphere:
                g = UsdGeom.Sphere.Define(stage, p)
                g.CreateRadiusAttr(1.0)
            else:
                g = UsdGeom.Cylinder.Define(stage, p)
                g.CreateRadiusAttr(1.0)
                g.CreateHeightAttr(1.0)
                g.CreateAxisAttr(UsdGeom.Tokens.z)
            UsdShade.MaterialBindingAPI.Apply(g.GetPrim()).Bind(make_material(stage, f"{path}/Looks/{name}", color))
            protos.append(Sdf.Path(p))
        self.inst.CreatePrototypesRel().SetTargets(protos)
        self.pos_attr = self.inst.CreatePositionsAttr()
        self.rot_attr = self.inst.CreateOrientationsAttr()
        self.scale_attr = self.inst.CreateScalesAttr()
        self.idx_attr = self.inst.CreateProtoIndicesAttr()

    def root_position(self, f: int) -> np.ndarray:
        p = self.m.positions[f]
        p = p[np.isfinite(p).all(-1)]
        return p.mean(0) if len(p) else np.zeros(3)

    def update(self, f: int) -> None:
        P = self.m.positions[f]
        ok = np.isfinite(P).all(-1)
        P = np.where(ok[:, None], P, 0.0)
        bad = bool(self.bad[f])
        J = len(P)
        pos = [P]
        rot = [np.tile([1.0, 0, 0, 0], (J, 1))]
        scl = [np.repeat(np.where(ok, self.joint_r, 0.0)[:, None], 3, axis=1)]
        idx = [np.full(J, 1 if bad else 0)]
        if len(self.bones):
            a, b = P[self.bones[:, 0]], P[self.bones[:, 1]]
            d = b - a
            length = np.linalg.norm(d, axis=-1)
            valid = ok[self.bones[:, 0]] & ok[self.bones[:, 1]] & (length > 1e-6)
            pos.append((a + b) / 2)
            up = np.tile([0.0, 0, 1], (len(d), 1))
            rot.append(quat_from_two_vectors(up, np.where(valid[:, None], d, up)))
            scl.append(np.stack([np.full_like(length, self.bone_r)] * 2 + [length], -1) * valid[:, None])
            idx.append(np.full(len(d), 3 if bad else 2))
        pos, rot, scl, idx = map(np.concatenate, (pos, rot, scl, idx))
        self.pos_attr.Set(Vt.Vec3fArray.FromNumpy(pos.astype(np.float32)))
        self.rot_attr.Set(Vt.QuathArray([Gf.Quath(*map(float, q)) for q in rot]))
        self.scale_attr.Set(Vt.Vec3fArray.FromNumpy(scl.astype(np.float32)))
        self.idx_attr.Set(Vt.IntArray.FromNumpy(idx.astype(np.int32)))


# --------------------------------------------------------------------------- robot
def resolve_robot_usd(path: str | None) -> str:
    if path:
        return os.path.abspath(path) if os.path.exists(path) else path
    from isaacsim.storage.native import get_assets_root_path

    root = get_assets_root_path()
    if root is None:
        raise RuntimeError("Isaac Sim asset library unreachable (offline?). Pass --robot-usd.")
    for rel in G1_ASSET_CANDIDATES:
        result, _ = omni.client.stat(root + rel)
        if result == omni.client.Result.OK:
            return root + rel
    raise RuntimeError(f"G1 not found in the asset library under {root}; pass --robot-usd")


class RobotReplay:
    """Teleports an articulation through a RobotMotion and measures its feet."""

    PATH = "/World/Robot"

    def __init__(self, stage, motion: RobotMotion, usd_path: str, offset):
        self.m = motion
        self.offset = np.asarray(offset, dtype=float)
        stage_utils.add_reference_to_stage(usd_path=usd_path, path=self.PATH)
        XformPrim(self.PATH).set_world_poses(positions=[(motion.root_pos[0] + self.offset).tolist()])
        self.art = Articulation(self.PATH)
        try:
            self.art.set_enabled_self_collisions(False)
        except Exception as e:  # not fatal: only matters if the motion self-intersects
            log(f"could not disable self-collisions: {e}")

        # feet: links named *ankle_roll* (G1/H1-2), else *foot* / *ankle*
        names = self.art.link_names
        paths = self.art.link_paths[0]
        feet = []
        for key in ("ankle_roll", "foot", "ankle"):
            feet = [i for i, n in enumerate(names) if key in n.lower()]
            if feet:
                break
        self.foot_names = [names[i] for i in feet]
        self.foot_paths = [paths[i] for i in feet]
        self.foot_corners = [self._local_corners(stage, p) for p in self.foot_paths]
        # bottom face of each foot box (link frame z-up when the foot is flat, as on the G1)
        self.foot_bottoms = [c[np.isclose(c[:, 2], c[:, 2].min())] for c in self.foot_corners]
        self.feet = RigidPrim(self.foot_paths) if self.foot_paths else None
        log(f"robot: {usd_path}\n               feet: {self.foot_names}")

    @staticmethod
    def _local_corners(stage, path: str) -> np.ndarray:
        """8 corners of the link's geometry bound in the link frame (sole estimate)."""
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        rng = cache.ComputeUntransformedBound(stage.GetPrimAtPath(path)).ComputeAlignedRange()
        if rng.IsEmpty():
            return np.zeros((1, 3))
        lo, hi = np.array(rng.GetMin()), np.array(rng.GetMax())
        return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])

    def start(self) -> None:
        """Call after the timeline is playing (tensor backend available)."""
        dof_names = self.art.dof_names
        self.q = np.zeros(len(dof_names))
        index = {n: i for i, n in enumerate(dof_names)}
        self.src, self.dst = [], []
        for i, n in enumerate(self.m.joint_names):
            if n in index:
                self.src.append(i)
                self.dst.append(index[n])
        missing = [n for n in self.m.joint_names if n not in index]
        unused = [n for n in dof_names if n not in set(self.m.joint_names)]
        log(f"robot DoF {len(dof_names)}, motion joints {len(self.m.joint_names)}, matched {len(self.src)}")
        if missing:
            log(f"  motion joints not in robot (ignored): {missing}")
        if unused:
            log(f"  robot DoFs not in motion (held at 0): {unused}")
        lo, hi = (a.numpy()[0] for a in self.art.get_dof_limits())
        self.limits = {n: (float(lo[i]), float(hi[i]), float("inf")) for n, i in index.items()}

    def apply(self, f: int) -> None:
        q = self.q.copy()
        q[self.dst] = self.m.dof_pos[f, self.src]
        q = q[None]
        self.art.set_world_poses(positions=(self.m.root_pos[f] + self.offset)[None],
                                 orientations=self.m.root_quat[f][None])
        self.art.set_dof_positions(q)
        self.art.set_dof_position_targets(q)
        self.art.set_dof_velocities(np.zeros_like(q))
        self.art.set_velocities(np.zeros((1, 3)), np.zeros((1, 3)))

    def sole_heights(self):
        """Per foot: lowest point and highest bottom-face corner (world z, offset removed;
        the latter is small only when the whole sole is down), and foot positions."""
        pos, quat = (a.numpy() for a in self.feet.get_world_poses())
        rot = [quat_to_matrix(q) for q in quat]
        z = [np.min((c @ r.T + p)[:, 2]) for c, p, r in zip(self.foot_corners, pos, rot)]
        flat = [np.max((c @ r.T + p)[:, 2]) for c, p, r in zip(self.foot_bottoms, pos, rot)]
        return np.array(z) - self.offset[2], np.array(flat) - self.offset[2], pos - self.offset


# --------------------------------------------------------------------------- timeline
class Clock:
    """Shared time base for clips with different frame rates."""

    def __init__(self, human: SkeletonMotion | None, robot: RobotMotion | None):
        clips = [c for c in (human, robot) if c is not None]
        self.fps = max(c.fps for c in clips)
        self.duration = max(c.duration for c in clips)
        self.num_frames = max(1, int(round(self.duration * self.fps)))
        self.human, self.robot = human, robot

    def frame_of(self, clip, master_frame: int) -> int:
        return min(int(master_frame / self.fps * clip.fps), clip.num_frames - 1)


def load_qc_config(path: str) -> QCConfig:
    """Same thresholds as tools/qc_report.py (configs/qc.yaml)."""
    if not path or not os.path.isfile(path):
        return QCConfig()
    import yaml

    with open(path, encoding="utf-8") as f:
        return QCConfig.from_dict((yaml.safe_load(f) or {}).get("thresholds"))


def main() -> int:
    qc_cfg = load_qc_config(args.qc_config)
    human = robot_motion = None
    human_qc = robot_qc = None
    if args.human:
        human = load_motion(args.human, up_axis=args.up_axis, model_dir=args.smpl_model_dir)
        if isinstance(human, RobotMotion):
            raise SystemExit("--human got a robot motion file; use --robot-motion")
        human_qc = check_motion(human, qc_cfg)
        log(f"human: {human.name}  {human.num_frames} frames @ {human.fps:g} fps, "
            f"{len(human.joint_names)} {'markers' if human.kind == 'markers' else 'joints'}, "
            f"QC {human_qc.status} ({'; '.join(human_qc.notes) or 'ok'})")
    if args.robot_motion:
        robot_motion = load_motion(args.robot_motion, fps=args.csv_fps)
        if not isinstance(robot_motion, RobotMotion):
            raise SystemExit("--robot-motion got a human motion file; use --human")
        log(f"robot motion: {robot_motion.name}  {robot_motion.num_frames} frames @ {robot_motion.fps:g} fps")

    stage_utils.create_new_stage()
    stage_utils.set_stage_units(meters_per_unit=1.0)
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    build_scene(stage)

    skel = None
    if human is not None:
        skel = SkeletonViz(stage, "/World/Human", human, human_qc.hard_mask())
    robot = None
    if robot_motion is not None:
        offset = args.robot_offset if human is not None else [0.0, 0.0, 0.0]
        robot = RobotReplay(stage, robot_motion, resolve_robot_usd(args.robot_usd), offset)

    app_utils.play()
    simulation_app.update()
    if robot is not None:
        robot.start()
        robot_qc = check_motion(robot_motion, qc_cfg, robot.limits)
        log(f"robot QC (limits from the robot asset): {robot_qc.status} ({'; '.join(robot_qc.notes) or 'ok'})")

    clock = Clock(human, robot_motion)
    bad = np.zeros(clock.num_frames, dtype=bool)
    for clip, res in ((human, human_qc), (robot_motion, robot_qc)):
        if clip is not None and res is not None:
            mask = res.hard_mask()
            bad |= np.array([mask[clock.frame_of(clip, f)] for f in range(clock.num_frames)])

    def show(f: int) -> None:
        if skel is not None:
            skel.update(clock.frame_of(human, f))
        if robot is not None:
            robot.apply(clock.frame_of(robot_motion, f))

    def focus(f: int) -> np.ndarray:
        """Camera target: the human, the robot, or the midpoint of both."""
        pts = []
        if skel is not None:
            pts.append(skel.root_position(clock.frame_of(human, f)))
        if robot is not None:
            pts.append(robot_motion.root_pos[clock.frame_of(robot_motion, f)] + robot.offset)
        return np.mean(pts, axis=0)

    if args.headless:
        return run_check(clock, show, focus, robot, human_qc, robot_qc, bad, qc_cfg)
    return run_gui(clock, show, focus, bad, human_qc, robot_qc)


# --------------------------------------------------------------------------- GUI
def run_gui(clock: Clock, show, focus, bad: np.ndarray, human_qc, robot_qc) -> int:
    import omni.ui as ui

    st = {"t": 0.0, "playing": True, "follow": True, "seeking": False}
    bad_idx = np.flatnonzero(bad)

    def seek(frame: int) -> None:
        st["t"] = min(max(frame, 0), clock.num_frames - 1) / clock.fps

    def jump_bad(direction: int) -> None:
        cur = int(st["t"] * clock.fps)
        cand = bad_idx[bad_idx > cur] if direction > 0 else bad_idx[bad_idx < cur]
        if len(cand):
            st["playing"] = False
            seek(int(cand[0] if direction > 0 else cand[-1]))

    def toggle() -> None:
        st["playing"] = not st["playing"]

    window = ui.Window("Mocap Replay", width=520, height=230)
    with window.frame:
        with ui.VStack(spacing=6, height=0):
            summary = []
            if human_qc is not None:
                summary.append(f"human QC {human_qc.status}: {human_qc.valid_s:.1f}/{human_qc.duration_s:.1f}s valid")
            if robot_qc is not None:
                summary.append(f"robot QC {robot_qc.status}: {robot_qc.valid_s:.1f}/{robot_qc.duration_s:.1f}s valid")
            ui.Label("  |  ".join(summary), word_wrap=True)
            info = ui.Label("")
            slider = ui.IntSlider(min=0, max=clock.num_frames - 1)

            def on_slider(model):
                if not st["seeking"]:
                    st["playing"] = False
                    seek(model.get_value_as_int())

            slider.model.add_value_changed_fn(on_slider)
            with ui.HStack(height=26, spacing=4):
                ui.Button("Play / Pause", clicked_fn=toggle)
                ui.Button("-1", width=40, clicked_fn=lambda: (st.update(playing=False), seek(int(st["t"] * clock.fps) - 1)))
                ui.Button("+1", width=40, clicked_fn=lambda: (st.update(playing=False), seek(int(st["t"] * clock.fps) + 1)))
                ui.Button("< bad", width=60, clicked_fn=lambda: jump_bad(-1))
                ui.Button("bad >", width=60, clicked_fn=lambda: jump_bad(1))
            with ui.HStack(height=22, spacing=6):
                ui.Label("speed", width=40)
                speed = ui.FloatDrag(min=0.05, max=4.0, step=0.01, width=60)
                speed.model.set_value(args.speed)
                ui.Label("follow camera", width=90)
                follow = ui.CheckBox(width=20)
                follow.model.set_value(True)
                follow.model.add_value_changed_fn(lambda m: st.update(follow=m.get_value_as_bool()))

    c0 = focus(0)
    set_camera_view(eye=(c0 + [3.5, -3.5, 1.4]).tolist(), target=(c0 + [0, 0, -0.1]).tolist(),
                    camera_prim_path="/OmniverseKit_Persp")
    log("GUI running. Red stick figure = QC-flagged frame. Close the window to quit.")

    last = started = time.perf_counter()
    while simulation_app.is_running():
        now = time.perf_counter()
        if args.quit_after and now - started > args.quit_after:
            break
        if st["playing"]:
            st["t"] += (now - last) * speed.model.get_value_as_float()
            if st["t"] >= clock.duration:
                if args.no_loop:
                    st["t"], st["playing"] = clock.duration - 1.0 / clock.fps, False
                else:
                    st["t"] = 0.0
        last = now
        f = min(int(st["t"] * clock.fps), clock.num_frames - 1)
        show(f)
        if st["follow"]:
            c = focus(f)
            set_camera_view(eye=(c + [3.5, -3.5, 1.4]).tolist(), target=(c + [0, 0, -0.1]).tolist(),
                            camera_prim_path="/OmniverseKit_Persp")
        st["seeking"] = True
        slider.model.set_value(f)
        st["seeking"] = False
        info.text = (f"frame {f}/{clock.num_frames - 1}   t={f / clock.fps:7.2f}s   "
                     f"{'BAD (QC flag)' if bad[f] else 'ok'}   {len(bad_idx)} bad frames")
        simulation_app.update()
    return 0


# --------------------------------------------------------------------------- headless check
def video_frame(img: np.ndarray, f: int, t: float, name: str, bad: bool):
    """Video frame with a caption: clip, time, what is shown, QC flag."""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.fromarray(img)
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    legend = []
    if args.human:
        legend.append("stick figure: human mocap")
    if args.robot_motion:
        legend.append(f"robot: {os.path.basename(args.robot_motion)}")
    lines = [(f"{name}   t = {t:5.2f} s   frame {f}", (20, 20, 20)), ("   |   ".join(legend), (20, 20, 20))]
    if bad:
        lines.append(("QC flag", (220, 30, 20)))
    for i, (text, color) in enumerate(lines):
        draw.text((14, 10 + 28 * i), text, fill=color, font=font, stroke_width=2, stroke_fill=(255, 255, 255))
    return im


def encode_video(frame_dir: str, n: int, fps: float, path: str) -> str | None:
    """f%05d.png frames -> H.264 MP4 with ffmpeg; a GIF when ffmpeg is missing or fails."""
    from PIL import Image

    if n == 0:
        log("video: no frames captured")
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if path.lower().endswith(".mp4"):
        if ffmpeg:
            r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", f"{fps:g}",
                                "-i", os.path.join(frame_dir, "f%05d.png"),
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", path],
                               capture_output=True, text=True)
            if r.returncode == 0:
                log(f"wrote {path} ({n} frames @ {fps:g} fps)")
                return path
            log(f"ffmpeg failed: {r.stderr.strip()[:300]}")
        log("no usable ffmpeg on PATH: writing a GIF instead")
        path = os.path.splitext(path)[0] + ".gif"
    frames = []
    for i in range(n):
        im = Image.open(os.path.join(frame_dir, f"f{i:05d}.png"))
        frames.append(im.resize((im.width * 2 // 3, im.height * 2 // 3)).convert("P", palette=Image.ADAPTIVE))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(round(1000 / fps)), loop=0)
    log(f"wrote {path} ({n} frames)")
    return path


def run_check(clock: Clock, show, focus, robot, human_qc, robot_qc, bad: np.ndarray, qc_cfg: QCConfig) -> int:
    from PIL import Image
    from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera

    out = os.path.abspath(args.check_out)
    os.makedirs(out, exist_ok=True)
    name = (human_qc or robot_qc).name

    cam = RtxCamera("/World/SnapCam")
    sensor = CameraSensor(cam, resolution=(540, 960), annotators=["rgb"])
    # ~60 deg horizontal FOV like the GUI viewport camera (USD attrs: focal length and
    # aperture share units, only their ratio matters)
    usd_cam = UsdGeom.Camera(omni.usd.get_context().get_stage().GetPrimAtPath("/World/SnapCam"))
    usd_cam.GetFocalLengthAttr().Set(18.0)
    usd_cam.GetHorizontalApertureAttr().Set(20.955)
    usd_cam.GetVerticalApertureAttr().Set(20.955 * 540 / 960)
    # replay range (--start / --end, seconds)
    f0 = min(max(int(round(args.start * clock.fps)), 0), clock.num_frames - 1)
    f1 = clock.num_frames if args.end is None else min(clock.num_frames, int(round(args.end * clock.fps)) + 1)
    f1 = max(f1, f0 + 1)
    snap_frames = set(np.linspace(f0, f1 - 1, max(args.snapshots, 0)).astype(int).tolist())
    # plus the middle of the first few QC-flagged segments, so reviewers see what failed
    edges = np.flatnonzero(np.diff(np.concatenate([[0], bad.astype(int), [0]])))
    segments = [(s, e) for s, e in zip(edges[::2], edges[1::2]) if f0 <= (s + e - 1) // 2 < f1]
    for start, end in segments[:3]:
        snap_frames.add(int((start + end - 1) // 2))
    snapshots = []
    video_frames = set()
    if args.video:
        t = np.arange(f0 / clock.fps, (f1 - 1) / clock.fps + 1e-9, 1.0 / args.video_fps)
        video_frames = set(np.clip(np.round(t * clock.fps).astype(int), f0, f1 - 1).tolist())
    video_tmp = tempfile.TemporaryDirectory(prefix="kh_video_") if args.video else None
    n_video = 0

    def capture(f: int, min_updates: int):
        """Aim the camera at frame f and grab an RGB image (the annotator lags the stage
        by a few updates; the very first capture also waits for the renderer)."""
        c = focus(f)
        eye = c + [3.5, -3.5, 1.4]
        cam.set_world_poses(positions=[eye.tolist()], orientations=[look_at_quat(eye, c + [0, 0, -0.1]).tolist()])
        for i in range(120):
            simulation_app.update()
            data, _ = sensor.get_data("rgb")
            if i >= min_updates - 1 and data is not None and data.size:
                return data.numpy()[..., :3]
        return None

    soles, flats, feet_xy, robot_frames = [], [], [], []
    t0 = time.perf_counter()
    frames = sorted(set(range(f0, f1, max(args.stride, 1))) | snap_frames | video_frames)
    for k, f in enumerate(frames):
        show(f)
        simulation_app.update()
        if robot is not None and robot.feet is not None:
            z, flat, p = robot.sole_heights()
            soles.append(z)
            flats.append(flat)
            feet_xy.append(p[:, :2])
            robot_frames.append(clock.frame_of(robot.m, f))
        img = None
        if f in snap_frames:
            img = capture(f, 9)
            if img is not None:
                p = os.path.join(out, f"{name}_f{f:06d}.png")
                Image.fromarray(img).save(p)
                snapshots.append(p)
        if f in video_frames:
            if img is None:
                img = capture(f, 4)
            if img is not None:
                video_frame(img, f, f / clock.fps, name, bad[f]).save(os.path.join(video_tmp.name, f"f{n_video:05d}.png"))
                n_video += 1
        if k % 500 == 0:
            log(f"frame {f}/{clock.num_frames - 1}")
    log(f"replayed {len(frames)} frames in {time.perf_counter() - t0:.1f}s")

    summary = {"clip": name, "frames": clock.num_frames, "fps": clock.fps, "duration_s": clock.duration,
               "replayed_s": [round(f0 / clock.fps, 3), round((f1 - 1) / clock.fps, 3)],
               "bad_frames": int(bad.sum()), "snapshots": snapshots}
    if video_tmp is not None:
        summary["video"] = encode_video(video_tmp.name, n_video, args.video_fps, os.path.abspath(args.video))
        video_tmp.cleanup()
    if human_qc is not None:
        summary["human_qc"] = human_qc.row()
    if robot_qc is not None:
        summary["robot_qc"] = robot_qc.row()
    if soles:
        # one sample per robot frame: the clock runs at the faster clip's rate, so a
        # 30 fps robot next to a 120 fps human repeats each pose 4 times
        rf = np.array(robot_frames)
        keep = np.concatenate([[True], np.diff(rf) != 0])
        rf, z, flat, xy = rf[keep], np.array(soles)[keep], np.array(flats)[keep], np.array(feet_xy)[keep]
        fps = robot.m.fps
        lowest = z.min(1)
        dt = np.maximum(np.diff(rf), 1) / fps
        hspeed = np.linalg.norm(np.diff(xy, axis=0), axis=-1) / dt[:, None]
        # same idea as the human QC: a foot planted flat (whole sole within 2.5 cm of the
        # floor; the lowest point alone also catches toe scuff in swing) that keeps
        # sliding faster than skate_speed for skate_min_duration
        slide = (flat[1:] < 0.025) & (hspeed > qc_cfg.skate_speed)
        step = int(np.median(np.diff(rf))) if len(rf) > 1 else 1
        n_min = max(1, int(round(qc_cfg.skate_min_duration * fps / max(step, 1))))
        skating = np.stack([_sustained(slide[:, i], n_min) for i in range(slide.shape[1])], 1) if len(slide) else slide
        planted = flat[1:] < 0.025
        summary["robot_sim"] = {
            "feet": robot.foot_names,
            "robot_frames": int(len(rf)),
            "sole_min_z_m": round(float(z.min()), 4),
            "penetration_ratio(<-2cm)": round(float((lowest < -0.02).mean()), 4),
            "both_feet_airborne_ratio(>5cm)": round(float((lowest > 0.05).mean()), 4),
            f"foot_skating_ratio(flat sole<2.5cm, >{qc_cfg.skate_speed:g}m/s for >={qc_cfg.skate_min_duration:g}s)":
                round(float(skating.any(1).mean()), 4) if len(skating) else 0.0,
            "planted_foot_mean_speed_mps": round(float(hspeed[planted].mean()), 3) if planted.any() else None,
        }
    path = os.path.join(out, f"{name}_sim_check.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    log(f"wrote {path}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if e.code not in (0, None) and not isinstance(e.code, int):
            log(str(e.code))
    except Exception:
        import traceback

        traceback.print_exc()
        carb.log_error("isaac_replay failed")
    finally:
        try:
            app_utils.stop()
        except Exception:
            pass
        simulation_app.close()
    sys.exit(code)
