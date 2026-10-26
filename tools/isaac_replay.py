"""Replay human mocap and/or retargeted robot motion in Isaac Sim for validation.

Run with Isaac Sim's Python, or plain `python` inside the activated retlens env:

    C:\\isaacsim\\python.bat tools\\isaac_replay.py --human data\\samples\\synthetic_walk_glitch.bvh
    C:\\isaacsim\\python.bat tools\\isaac_replay.py --robot-motion data\\samples\\synthetic_g1_walk.npz
    C:\\isaacsim\\python.bat tools\\isaac_replay.py --human clip.bvh --robot-motion clip_g1.npz

Human motion is drawn as a stick figure (joints = spheres, bones = cylinders) and
turns red on frames that QC hard-flags. Robot motion is replayed kinematically
(teleported every frame, gravity off) on the robot articulation; the default
robot is the Unitree G1 from the Isaac Sim asset library (another robot: --robot-usd).

Headless batch check: replays every frame once, measures the robot's foot soles
in the simulator, checks joint limits read from the robot asset, saves a few
snapshots and writes <check-out>/<clip>_sim_check.json:

    C:\\isaacsim\\python.bat tools\\isaac_replay.py --robot-motion clip.npz --headless --check-out reports\\sim

Video (implies --headless; MP4 needs ffmpeg on PATH, otherwise a GIF is written):

    python tools\\isaac_replay.py --human clip.bvh --robot-motion clip_g1.npz --video reports\\videos\\clip.mp4
    python tools\\isaac_replay.py --human long.bvh --robot-motion long_g1.npz --video long.mp4 --start 30 --end 45

Physics (--physics, headless): instead of teleporting, PhysX simulates the robot
with gravity on a floor with friction; its joint drives (PD, configs/physics.yaml)
track the clip and a virtual harness on the pelvis pulls toward the clip's root
(--assist scales it, 0 = off: falls are reset to the clip and counted). Writes
<check-out>/<clip>_sim.npz (the simulated motion, a project robot npz that
tools/compare_viewer.py shows next to the original) and <clip>_sim.json (harness
force, tracking error, torque saturation, falls, feet under physics):

    python tools\\isaac_replay.py --robot-motion clip_g1.npz --physics --check-out reports\\physics
    python tools\\isaac_replay.py --robot-motion clip_g1.npz --physics --assist 0 --video reports\\physics\\clip.mp4
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
    ap.add_argument("--start", type=float, default=0.0, help="check/video/physics mode: first second to replay")
    ap.add_argument("--end", type=float, default=None, help="check/video/physics mode: last second to replay")
    ap.add_argument("--physics", action="store_true",
                    help="simulate the robot with PhysX (gravity, floor contact, PD tracking) instead of teleporting")
    ap.add_argument("--physics-config", default=os.path.join(ROOT, "configs", "physics.yaml"))
    ap.add_argument("--assist", type=float, default=1.0,
                    help="physics: scale of the pelvis harness gains (0 = no harness)")
    ap.add_argument("--no-reset", action="store_true", help="physics: stop at the first fall instead of resetting")
    ap.add_argument("--progress", action="store_true", help="print progress lines (for the viewer's background runs)")
    args, _ = ap.parse_known_args()
    if not args.human and not args.robot_motion:
        ap.error("give --human and/or --robot-motion")
    if args.physics:
        if not args.robot_motion:
            ap.error("--physics needs --robot-motion")
        args.headless = True
        if not args.check_out and not args.video:
            args.check_out = os.path.join(ROOT, "reports", "physics")
    if args.video:
        args.headless = True
        if not args.check_out:  # keep the check JSON / snapshots next to the video, not in reports/sim_check
            args.check_out = os.path.dirname(os.path.abspath(args.video))
    if args.headless and not args.check_out:
        args.check_out = os.path.join(ROOT, "reports", "sim_check")
    return args


args = parse_args()

# The retlens env has its own torch (GMR needs it). isaacsim/__init__ imports
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

from retlens.io import load_motion  # noqa: E402
from retlens.motion import RobotMotion, SkeletonMotion  # noqa: E402
from retlens.qc import QCConfig, _sustained, add_balance_flags, check_motion  # noqa: E402
from retlens.rotations import matrix_to_quat, quat_from_two_vectors, quat_to_matrix  # noqa: E402

COLORS = {
    "joint": (0.15, 0.45, 0.95),
    "bone": (0.75, 0.75, 0.78),
    "bad": (0.95, 0.15, 0.1),
    "marker": (0.1, 0.8, 0.4),
}


def log(msg: str) -> None:
    print(f"[isaac_replay] {msg}", flush=True)


def progress(stage: str, done: int, total: int) -> None:
    """--progress: machine-readable "[isaac_replay] progress <stage> <done>/<total>" lines,
    about 50 per stage (read by retlens/physics_runner.py)."""
    if args.progress and (done % max(1, total // 50) == 0 or done == total - 1):
        log(f"progress {stage} {done + 1}/{total}")


# --------------------------------------------------------------------------- scene
def make_material(stage, path: str, rgb) -> UsdShade.Material:
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def build_scene(stage, physics: dict | None = None) -> None:
    """Lights, a floor with a 1 m grid and the physics scene. Kinematic replay: the
    floor is visual only (replay must show penetration, not resolve it) and gravity
    is off. Physics (``physics`` = configs/physics.yaml "sim"): a static floor
    collider with friction and gravity on."""
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
    if physics is None:
        scene.CreateGravityMagnitudeAttr(0.0)  # kinematic replay
        return
    scene.CreateGravityMagnitudeAttr(9.81)
    # static box collider under the visual floor (top face at z = 0)
    box = UsdGeom.Cube.Define(stage, "/World/FloorCollider")
    box.CreateSizeAttr(1.0)
    xf = UsdGeom.Xformable(box)
    xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.05))
    xf.AddScaleOp().Set(Gf.Vec3f(60.0, 60.0, 0.1))
    box.CreatePurposeAttr(UsdGeom.Tokens.guide)  # not rendered
    UsdPhysics.CollisionAPI.Apply(box.GetPrim())
    mat = UsdShade.Material.Define(stage, "/World/Looks/FloorPhysics")
    pm = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
    pm.CreateStaticFrictionAttr(float(physics.get("static_friction", 1.0)))
    pm.CreateDynamicFrictionAttr(float(physics.get("dynamic_friction", 0.8)))
    pm.CreateRestitutionAttr(0.0)
    UsdShade.MaterialBindingAPI.Apply(box.GetPrim()).Bind(
        mat, UsdShade.Tokens.weakerThanDescendants, "physics")


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
    FLOOR = "/World/FloorCollider"  # see build_scene

    def __init__(self, stage, motion: RobotMotion, usd_path: str, offset, contacts: bool = False):
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
        if self.foot_corners:
            c = self.foot_corners[0]
            log(f"foot box (link frame, m): x {c[:, 0].min():.3f}..{c[:, 0].max():.3f}, "
                f"z {c[:, 2].min():.3f}..{c[:, 2].max():.3f}")
        # bottom face of each foot box (link frame z-up when the foot is flat, as on the G1)
        self.foot_bottoms = [c[np.isclose(c[:, 2], c[:, 2].min())] for c in self.foot_corners]
        self.feet = None
        self.contacts = False
        if self.foot_paths and contacts:
            try:  # contact view against the floor collider (set up before the simulation starts)
                self.feet = RigidPrim(self.foot_paths, contact_filter_paths=[self.FLOOR])
                self.feet.set_enabled_contact_tracking(True)
                self.contacts = True
            except Exception as e:
                log(f"foot contact forces unavailable: {e}")
        if self.foot_paths and self.feet is None:
            self.feet = RigidPrim(self.foot_paths)
        root = [p for n, p in zip(names, paths) if n == "pelvis"] or [paths[0]]
        self.root_link = RigidPrim(root[0])
        self.link_names = list(names)
        self.links = RigidPrim(list(paths))  # every link: world poses for the whole-body CoM
        log(f"robot: {usd_path}\n               feet: {self.foot_names}")

    @staticmethod
    def _local_corners(stage, path: str) -> np.ndarray:
        """8 corners of the link's collision geometry bound in the link frame (sole
        estimate). Falls back to the visual geometry when the link has no collider;
        on the Isaac G1 the visual foot box reaches 1.7 cm below the collision shapes."""
        prim = stage.GetPrimAtPath(path)
        purposes = [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.guide, UsdGeom.Tokens.proxy]
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), purposes)
        colliders = [p for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies())
                     if p.HasAPI(UsdPhysics.CollisionAPI) and p.IsA(UsdGeom.Boundable)]
        rng = Gf.Range3d()
        for c in colliders:
            rng.UnionWith(cache.ComputeRelativeBound(c, prim).ComputeAlignedRange())
        if rng.IsEmpty():
            cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), purposes[:2])
            rng = cache.ComputeUntransformedBound(prim).ComputeAlignedRange()
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
        # link masses and CoMs (link frame) from the robot asset, for the whole-body CoM
        self.link_masses = np.asarray(self.art.get_link_masses().numpy()[0], float)
        self.link_coms = np.asarray(self.art.get_link_coms()[0].numpy()[0], float)
        log(f"robot mass {self.link_masses.sum():.2f} kg over {len(self.link_masses)} links (from the asset)")

    def link_poses(self) -> tuple[np.ndarray, np.ndarray]:
        """World positions (L, 3, offset removed) and orientations (L, 4 wxyz) of every link."""
        pos, quat = (np.asarray(a.numpy(), float) for a in self.links.get_world_poses())
        return pos - self.offset, quat

    def sole_points(self) -> np.ndarray:
        """(feet, C, 3) bottom-face corners of the foot collision boxes, world, offset removed."""
        pos, quat = (np.asarray(a.numpy(), float) for a in self.feet.get_world_poses())
        return np.stack([c @ quat_to_matrix(q).T + p - self.offset for c, p, q in zip(self.foot_bottoms, pos, quat)])

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


def load_physics_config(path: str) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for key in ("sim", "assist", "fall", "report", "diagnosis"):
        cfg.setdefault(key, {})
    cfg.setdefault("pd", [{"pattern": ".*", "stiffness": 100.0, "damping": 5.0}])
    return cfg


def main() -> int:
    qc_cfg = load_qc_config(args.qc_config)
    phys_cfg = load_physics_config(args.physics_config) if args.physics else None
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
    build_scene(stage, phys_cfg["sim"] if phys_cfg else None)

    skel = None
    if human is not None:
        skel = SkeletonViz(stage, "/World/Human", human, human_qc.hard_mask())
    robot = None
    if robot_motion is not None:
        offset = args.robot_offset if human is not None else [0.0, 0.0, 0.0]
        robot = RobotReplay(stage, robot_motion, resolve_robot_usd(args.robot_usd), offset, contacts=args.physics)

    substeps = 1
    if args.physics:
        from isaacsim.core.simulation_manager import SimulationManager

        substeps = max(1, int(round(float(phys_cfg["sim"].get("physics_hz", 240)) / robot_motion.fps)))
        # physics advances only through SimulationManager.step (app updates just render)
        carb.settings.get_settings().set_bool("/app/player/playSimulations", False)
        SimulationManager.set_physics_dt(1.0 / (robot_motion.fps * substeps))

    app_utils.play()
    simulation_app.update()
    if args.physics:  # with playSimulations off, playing the timeline does not start physics
        SimulationManager.initialize_physics()
        simulation_app.update()
    if robot is not None:
        robot.start()
        robot_qc = check_motion(robot_motion, qc_cfg, robot.limits)
        log(f"robot QC (limits from the robot asset): {robot_qc.status} ({'; '.join(robot_qc.notes) or 'ok'})")
    if args.physics:
        return run_physics(robot, human, skel, human_qc, robot_qc, qc_cfg, phys_cfg, substeps)

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
                               capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console from a windowless run
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


class SnapCamera:
    """RTX camera looking at a point from the front-right, for snapshots / video."""

    def __init__(self):
        from isaacsim.sensors.experimental.rtx import CameraSensor, RtxCamera

        self.cam = RtxCamera("/World/SnapCam")
        self.sensor = CameraSensor(self.cam, resolution=(540, 960), annotators=["rgb"])
        # ~60 deg horizontal FOV like the GUI viewport camera (USD attrs: focal length and
        # aperture share units, only their ratio matters)
        usd_cam = UsdGeom.Camera(omni.usd.get_context().get_stage().GetPrimAtPath("/World/SnapCam"))
        usd_cam.GetFocalLengthAttr().Set(18.0)
        usd_cam.GetHorizontalApertureAttr().Set(20.955)
        usd_cam.GetVerticalApertureAttr().Set(20.955 * 540 / 960)

    def capture(self, c: np.ndarray, min_updates: int):
        """Aim at c and grab an RGB image (the annotator lags the stage by a few
        updates; the very first capture also waits for the renderer)."""
        eye = c + [3.5, -3.5, 1.4]
        self.cam.set_world_poses(positions=[eye.tolist()], orientations=[look_at_quat(eye, c + [0, 0, -0.1]).tolist()])
        for i in range(120):
            simulation_app.update()
            data, _ = self.sensor.get_data("rgb")
            if i >= min_updates - 1 and data is not None and data.size:
                return data.numpy()[..., :3]
        return None


def foot_summary(rf: np.ndarray, z: np.ndarray, flat: np.ndarray, xy: np.ndarray, fps: float,
                 foot_names: list[str], qc_cfg: QCConfig) -> dict:
    """Robot feet measured in the simulator, one sample per robot frame rf: lowest
    sole point z, highest bottom-face corner flat, foot xy (per foot)."""
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
    return {
        "feet": foot_names,
        "robot_frames": int(len(rf)),
        "sole_min_z_m": round(float(z.min()), 4),
        "penetration_ratio(<-2cm)": round(float((lowest < -0.02).mean()), 4),
        "both_feet_airborne_ratio(>5cm)": round(float((lowest > 0.05).mean()), 4),
        f"foot_skating_ratio(flat sole<2.5cm, >{qc_cfg.skate_speed:g}m/s for >={qc_cfg.skate_min_duration:g}s)":
            round(float(skating.any(1).mean()), 4) if len(skating) else 0.0,
        "planted_foot_mean_speed_mps": round(float(hspeed[planted].mean()), 3) if planted.any() else None,
    }


def balance_of(robot, link_pos: np.ndarray, link_quat: np.ndarray, soles: np.ndarray, fps: float,
               qc_cfg: QCConfig, floor=None, breaks: list[int] | None = None):
    """(BalanceTrack, static_unbalanced flag, JSON summary) from recorded link poses (T, L, ...)
    and sole points (T, feet, C, 3). Masses / link CoMs are the robot asset's. The floor is
    tracked through the clip (retargets drift) unless given (physics: the real floor, 0).
    ``breaks``: frames where a physics replay restarted the robot (ZMP per piece)."""
    from retlens import stability
    from retlens.analysis import BALANCE_MIN_DURATION, floor_track, slowest_sole_speed

    com = stability.com_from_links(link_pos, link_quat, robot.link_coms, robot.link_masses)
    if floor is None:
        floor = floor_track(soles[..., 2].min(-1), slowest_sole_speed(soles, fps), fps)
    track = stability.balance_track(com, soles, fps, floor, qc_cfg.support_contact_height, breaks=breaks)
    static = stability.static_unbalanced(track, qc_cfg.balance_tolerance, qc_cfg.static_max_speed,
                                         qc_cfg.static_min_duration)
    summary = stability.summarize(track, qc_cfg.balance_tolerance, BALANCE_MIN_DURATION, static=static)
    summary["mass_kg"] = round(float(robot.link_masses.sum()), 2)
    summary["model"] = "CoM from the robot asset's link masses; ZMP cart-table (angular momentum ignored)"
    return track, static, summary


def run_check(clock: Clock, show, focus, robot, human_qc, robot_qc, bad: np.ndarray, qc_cfg: QCConfig) -> int:
    from PIL import Image

    out = os.path.abspath(args.check_out)
    os.makedirs(out, exist_ok=True)
    name = (human_qc or robot_qc).name
    snap = SnapCamera()
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
    video_tmp = tempfile.TemporaryDirectory(prefix="retlens_video_") if args.video else None
    n_video = 0

    def capture(f: int, min_updates: int):
        return snap.capture(focus(f), min_updates)

    soles, flats, feet_xy, robot_frames, link_pos, link_quat, sole_pts = [], [], [], [], [], [], []
    t0 = time.perf_counter()
    frames = sorted(set(range(f0, f1, max(args.stride, 1))) | snap_frames | video_frames)
    for k, f in enumerate(frames):
        progress("render" if args.video else "replay", k, len(frames))
        show(f)
        simulation_app.update()
        if robot is not None and robot.feet is not None:
            z, flat, p = robot.sole_heights()
            soles.append(z)
            flats.append(flat)
            feet_xy.append(p[:, :2])
            robot_frames.append(clock.frame_of(robot.m, f))
            lp, lq = robot.link_poses()
            link_pos.append(lp)
            link_quat.append(lq)
            sole_pts.append(robot.sole_points())
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
    if soles:
        # one sample per robot frame: the clock runs at the faster clip's rate, so a
        # 30 fps robot next to a 120 fps human repeats each pose 4 times
        rf = np.array(robot_frames)
        keep = np.concatenate([[True], np.diff(rf) != 0])
        rf, z, flat, xy = rf[keep], np.array(soles)[keep], np.array(flats)[keep], np.array(feet_xy)[keep]
        summary["robot_sim"] = foot_summary(rf, z, flat, xy, robot.m.fps, robot.foot_names, qc_cfg)
        # balance: whole-body CoM (asset masses) and cart-table ZMP against the feet's support
        step = int(np.median(np.diff(rf))) if len(rf) > 1 else 1
        _, static, bal = balance_of(robot, np.array(link_pos)[keep], np.array(link_quat)[keep],
                                    np.array(sole_pts)[keep], robot.m.fps / max(step, 1), qc_cfg)
        bal["robot_frames"] = int(len(rf))
        summary["robot_balance"] = bal
        if robot_qc is not None:
            flag = np.zeros(robot_qc.num_frames, dtype=bool)
            flag[rf] = static
            add_balance_flags(robot_qc, flag, qc_cfg)
    if robot_qc is not None:
        summary["robot_qc"] = robot_qc.row()
    path = os.path.join(out, f"{name}_sim_check.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    log(f"wrote {path}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str), flush=True)
    return 0


# --------------------------------------------------------------------------- physics
def _log_rot(D: np.ndarray) -> np.ndarray:
    """Rotation vectors (..., 3) of rotation matrices (..., 3, 3) (angles below pi)."""
    ang = np.arccos(np.clip((np.trace(D, axis1=-2, axis2=-1) - 1) / 2, -1.0, 1.0))
    v = np.stack([D[..., 2, 1] - D[..., 1, 2], D[..., 0, 2] - D[..., 2, 0], D[..., 1, 0] - D[..., 0, 1]], -1)
    s = np.sin(ang)
    small = s < 1e-6
    return v * np.where(small, 0.5, ang / (2 * np.where(small, 1.0, s)))[..., None]


def _nlerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    b = -b if np.dot(a, b) < 0 else b
    q = (1 - t) * a + t * b
    return q / np.linalg.norm(q)


def _stats(x: np.ndarray, digits: int = 3) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {"mean": None, "p95": None, "max": None}
    return {"mean": round(float(x.mean()), digits), "p95": round(float(np.percentile(x, 95)), digits),
            "max": round(float(x.max()), digits)}


def fall_diagnosis(d: dict, fps: float, fall_frames: list[int], robot, ref_sp: np.ndarray, SP: np.ndarray,
                   LP: np.ndarray, FF: np.ndarray, weight: float, tau_ratio: np.ndarray, joint_names: list[str],
                   sim_track, harness: np.ndarray, assist: float, ref_track=None) -> list[dict]:
    """First cause of every fall (retlens/diagnosis.py). ref_sp / SP: (T, feet, C, 3) sole points
    of the clip (reference pass) and of the simulation; LP (T, L, 3) simulated link positions;
    FF (T, feet) foot contact forces (NaN if unavailable); tau_ratio (T, joints) drive demand / limit.
    ref_track: the clip's BalanceTrack, so support_exit evidence shows whether the clip itself
    had the CoM outside its feet at that moment (a data issue) or only the simulation did."""
    from retlens.analysis import floor_track, slowest_sole_speed
    from retlens.diagnosis import diagnose_fall

    if not fall_frames:
        return []
    T = len(SP)
    feet = robot.foot_names
    ref_low = ref_sp[..., 2].min(-1)
    ref_speed = slowest_sole_speed(ref_sp, fps)
    ref_clear = ref_low - floor_track(ref_low, ref_speed, fps)[:, None]
    sim_low = SP[..., 2].min(-1)
    sim_speed = slowest_sole_speed(SP, fps)
    ff = np.nan_to_num(FF, nan=0.0)
    contact_h = float(d.get("contact_height_m", 0.005))
    on_floor = (sim_low < contact_h) | (ff > float(d.get("contact_force_bw", 0.05)) * weight)
    # the clip's foot swings (fast and off the floor: a touchdown at 0.6 m/s is not a swing)
    toe = on_floor & (ref_speed > float(d.get("swing_speed_mps", 0.5))) & (ref_clear > contact_h)
    slip_v = float(d.get("slip_speed_mps", 0.3))
    slip = on_floor & (sim_speed > slip_v) & (ref_speed < slip_v)
    idx = {n: i for i, n in enumerate(robot.link_names)}
    pairs = {"feet": [idx[f] for f in feet[:2]] if len(feet) >= 2 else [],
             "knees": [i for n, i in idx.items() if "knee" in n.lower()][:2]}
    dist = {k: np.linalg.norm(LP[:, v[0]] - LP[:, v[1]], axis=1) if len(v) == 2 else np.full(T, np.inf)
            for k, v in pairs.items()}
    selfc = np.minimum(dist["feet"], dist["knees"]) < float(d.get("self_distance_m", 0.09))
    tmax, targ = tau_ratio.max(1), tau_ratio.argmax(1)
    torque = tmax > float(d.get("torque_ratio", 1.5))
    cm = np.nan_to_num(sim_track.com_margin, nan=0.0)
    zm = np.nan_to_num(sim_track.zmp_margin, nan=0.0)
    exit_ = cm < -float(d.get("com_outside_m", 0.03))
    if assist <= 0:  # with the harness on, the ZMP includes its pull and leaves the feet all the time
        exit_ |= zm < -float(d.get("zmp_outside_m", 0.05))
    exit_ &= sim_track.supported
    spike = harness > float(d.get("harness_bw", 0.5)) if assist > 0 else np.zeros(T, bool)

    def r(x, k=2):
        return None if x is None or not np.isfinite(x) else round(float(x), k)

    def toe_ev(i, a, b):
        ks = np.flatnonzero(toe[i])
        return {"feet": [feet[k] for k in ks],
                "clip_foot_speed_mps": [r(ref_speed[i, k]) for k in ks],
                "clip_clearance_cm": [r(100 * ref_clear[i, k], 1) for k in ks],
                "sim_sole_height_cm": [r(100 * sim_low[i, k], 1) for k in ks],
                "contact_force_n": [r(ff[i, k], 0) for k in ks]}

    def slip_ev(i, a, b):
        ks = np.flatnonzero(slip[i])
        return {"feet": [feet[k] for k in ks], "sim_foot_speed_mps": [r(sim_speed[i, k]) for k in ks],
                "peak_speed_in_window_mps": r(sim_speed[a:b + 1].max())}

    def self_ev(i, a, b):
        return {"feet_distance_m": r(dist["feet"][i], 3), "knees_distance_m": r(dist["knees"][i], 3),
                "min_in_window_m": r(min(dist["feet"][a:b + 1].min(), dist["knees"][a:b + 1].min()), 3)}

    def torque_ev(i, a, b):
        w = a + int(np.argmax(tmax[a:b + 1]))
        return {"joint": joint_names[targ[i]], "demand_per_limit": r(tmax[i]),
                "peak_joint": joint_names[targ[w]], "peak_demand_per_limit": r(tmax[w]), "peak_s": r(w / fps, 3)}

    def exit_ev(i, a, b):
        ev = {"com_margin_cm": r(100 * sim_track.com_margin[i], 1), "zmp_margin_cm": r(100 * sim_track.zmp_margin[i], 1),
              "feet_on_floor": int(sim_track.phase[i]),
              "min_com_margin_in_window_cm": r(100 * np.nanmin(sim_track.com_margin[a:b + 1]), 1)
              if np.isfinite(sim_track.com_margin[a:b + 1]).any() else None}
        if ref_track is not None and i < len(ref_track.com_margin):
            ev["clip_com_margin_cm"] = r(100 * ref_track.com_margin[i], 1)  # < 0: the clip's own CoM was outside too
        return ev

    def harness_ev(i, a, b):
        return {"harness_per_body_weight": r(harness[i]), "peak_in_window": r(harness[a:b + 1].max())}

    conditions = {"toe_catch": toe.any(1), "foot_slip": slip.any(1), "self_collision": selfc,
                  "torque_saturation": torque, "support_exit": exit_}
    evidence = {"toe_catch": toe_ev, "foot_slip": slip_ev, "self_collision": self_ev,
                "torque_saturation": torque_ev, "support_exit": exit_ev}
    if assist > 0:
        conditions["harness_spike"] = spike
        evidence["harness_spike"] = harness_ev
    window = max(1, int(round(float(d.get("window_s", 0.75)) * fps)))
    settle = 3  # frames after a (re)start, while the robot settles on the floor
    out, prev = [], 0
    for fr in fall_frames:
        if fr >= T:
            break
        start = min(max(prev + settle, fr - window), fr)
        out.append(diagnose_fall(conditions, evidence, fr, start, fps, int(d.get("min_frames", 2)),
                                 earliest=min(prev + settle, fr)))
        prev = fr
    return out


def run_physics(robot, human, skel, human_qc, robot_qc, qc_cfg: QCConfig, cfg: dict, substeps: int) -> int:
    """PhysX tracking of the robot motion (see the module docstring); writes <clip>_sim.npz / .json."""
    import re

    from PIL import Image
    from isaacsim.core.simulation_manager import SimulationManager

    from dataclasses import replace

    m = robot.m
    f0 = min(max(int(round(args.start * m.fps)), 0), m.num_frames - 1)
    f1 = m.num_frames if args.end is None else min(m.num_frames, int(round(args.end * m.fps)) + 1)
    f1 = max(f1, f0 + 1)
    if (f0, f1) != (0, m.num_frames):  # --start / --end: simulate that segment only (times below are segment times)
        m = robot.m = replace(m, root_pos=m.root_pos[f0:f1], root_quat=m.root_quat[f0:f1], dof_pos=m.dof_pos[f0:f1])
        log(f"physics segment: frames {f0}..{f1 - 1} ({f0 / m.fps:.2f}-{(f1 - 1) / m.fps:.2f} s of the clip)")
    seg_start = f0 / m.fps
    fps, n = m.fps, m.num_frames
    out = os.path.abspath(args.check_out)
    os.makedirs(out, exist_ok=True)
    art, off = robot.art, robot.offset
    dof_names = art.dof_names
    D = len(dof_names)

    # reference in the asset's DoF order, plus velocities
    q_ref = np.zeros((n, D))
    q_ref[:, robot.dst] = m.dof_pos[:, robot.src]
    qd_ref = np.gradient(q_ref, 1.0 / fps, axis=0) if n > 1 else np.zeros_like(q_ref)
    p_ref = m.root_pos + off
    quat_ref = m.root_quat.copy()
    for i in range(1, n):
        if np.dot(quat_ref[i], quat_ref[i - 1]) < 0:
            quat_ref[i] *= -1
    R_ref = quat_to_matrix(quat_ref)
    v_ref = np.gradient(p_ref, 1.0 / fps, axis=0) if n > 1 else np.zeros_like(p_ref)
    w_ref = np.zeros((n, 3))
    if n > 1:
        w_ref[:-1] = _log_rot(R_ref[1:] @ np.swapaxes(R_ref[:-1], -1, -2)) * fps
        w_ref[-1] = w_ref[-2]

    # joint drives
    kp, kd = np.zeros(D), np.zeros(D)
    for i, dn in enumerate(dof_names):
        for g in cfg["pd"]:
            if re.fullmatch(g["pattern"], dn):
                kp[i], kd[i] = float(g["stiffness"]), float(g["damping"])
                break
    art.set_dof_gains(stiffnesses=kp[None], dampings=kd[None])
    sim = cfg["sim"]
    try:
        art.set_solver_iteration_counts(position_counts=[int(sim.get("solver_position_iterations", 8))],
                                        velocity_counts=[int(sim.get("solver_velocity_iterations", 2))])
    except Exception as e:
        log(f"solver iteration counts not set: {e}")
    max_eff = np.asarray(art.get_dof_max_efforts().numpy()[0], float)
    mass = float(np.asarray(art.get_link_masses().numpy()[0]).sum())
    weight = mass * 9.81

    # pelvis harness
    scale = max(float(args.assist), 0.0)
    wn = 2 * np.pi * float(cfg["assist"].get("pos_hz", 2.0))
    kp_lin, kd_lin = scale * mass * wn ** 2, scale * 2 * mass * wn
    kp_rot = scale * float(cfg["assist"].get("rot_stiffness", 300.0))
    kd_rot = scale * float(cfg["assist"].get("rot_damping", 30.0))
    axes = np.array([1.0, 1.0, 1.0 if cfg["assist"].get("vertical", False) else 0.0])  # harness force axes
    fall = cfg["fall"]
    log(f"physics: {fps * substeps:g} Hz ({substeps} steps per frame), mass {mass:.1f} kg, harness x{scale:g}, "
        f"{len(q_ref)} frames")

    def root_state():
        p, q = (np.asarray(a.numpy()[0], float) for a in art.get_world_poses())
        v, w = (np.asarray(a.numpy()[0], float) for a in art.get_velocities())
        return p, q, v, w

    def place(f: int, dz: float) -> None:
        art.set_world_poses(positions=(p_ref[f] + [0.0, 0.0, dz])[None], orientations=quat_ref[f][None])
        art.set_dof_positions(q_ref[f][None])
        art.set_dof_position_targets(q_ref[f][None])
        art.set_dof_velocities(qd_ref[f][None])
        art.set_dof_velocity_targets(qd_ref[f][None])
        art.set_velocities(v_ref[f][None], w_ref[f][None])

    def reset(f: int) -> float:
        """(Re)start from the clip's frame f, lifted so that no sole is below the floor."""
        place(f, 0.05)
        SimulationManager.step(steps=1)
        z, _, _ = robot.sole_heights()
        lift = max(0.0, 0.002 - (float(z.min()) - 0.05))
        place(f, lift)
        return lift

    def reference_pass() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Link poses and sole points of the clip's own frames: the robot is put in each
        frame's pose 0.5 m up (no contact) and stepped once so PhysX moves its links."""
        lp, lq, sp = [], [], []
        up = np.array([0.0, 0.0, 0.5])
        zero = np.zeros((1, D))
        for f in range(n):
            progress("reference", f, n)
            art.set_world_poses(positions=(p_ref[f] + up)[None], orientations=quat_ref[f][None])
            art.set_dof_positions(q_ref[f][None])
            art.set_dof_position_targets(q_ref[f][None])
            art.set_dof_velocities(zero)
            art.set_dof_velocity_targets(zero)
            art.set_velocities(np.zeros((1, 3)), np.zeros((1, 3)))
            SimulationManager.step(steps=1)
            a, b = robot.link_poses()
            lp.append(a - up)
            lq.append(b)
            sp.append(robot.sole_points() - up)
        return np.array(lp), np.array(lq), np.array(sp)

    # recording
    rec = {k: [] for k in ("p", "q", "dof", "f_mean", "f_max", "t_mean", "tau", "support", "z", "flat", "xy",
                           "lp", "lq", "sp", "ff")}

    def record(f: int, forces: list, torques: list) -> tuple:
        p, q, _, _ = root_state()
        dof = np.asarray(art.get_dof_positions().numpy()[0], float)
        dofv = np.asarray(art.get_dof_velocities().numpy()[0], float)
        rec["p"].append(p)
        rec["q"].append(q)
        rec["dof"].append(dof)
        rec["f_mean"].append(float(np.mean(forces)) if forces else 0.0)
        rec["f_max"].append(float(np.max(forces)) if forces else 0.0)
        rec["t_mean"].append(float(np.mean(torques)) if torques else 0.0)
        rec["tau"].append(kp * (q_ref[f] - dof) + kd * (qd_ref[f] - dofv))  # drive demand before clipping
        support = np.nan
        forces_z = np.full(len(robot.foot_names), np.nan)
        if robot.contacts:
            try:
                impulse_to_force = SimulationManager.get_physics_dt()  # the view returns impulses by default
                forces_z = np.abs(np.asarray(robot.feet.get_net_contact_forces(dt=impulse_to_force).numpy())[:, 2])
                support = float(forces_z.sum()) / weight
            except Exception as e:
                log(f"foot contact forces unavailable: {type(e).__name__}: {e}")
                robot.contacts = False
        rec["support"].append(abs(support))
        rec["ff"].append(forces_z)
        z, flat, pos = robot.sole_heights()
        rec["z"].append(z)
        rec["flat"].append(flat)
        rec["xy"].append(pos[:, :2])
        lp, lq = robot.link_poses()
        rec["lp"].append(lp)
        rec["lq"].append(lq)
        rec["sp"].append(robot.sole_points())
        return p, q

    snap = SnapCamera() if (args.video or args.snapshots > 0) else None
    every = max(1, int(round(fps / args.video_fps))) if args.video else 0
    snap_frames = set(np.linspace(0, n - 1, max(args.snapshots, 0)).astype(int).tolist())
    video_tmp = tempfile.TemporaryDirectory(prefix="retlens_video_") if args.video else None
    n_video, snapshots = 0, []

    def focus(f: int, p: np.ndarray) -> np.ndarray:
        pts = [p]
        if skel is not None:
            pts.append(skel.root_position(min(int((f / fps + seg_start) * human.fps), human.num_frames - 1)))
        return np.mean(pts, axis=0)

    def show(f: int, p: np.ndarray, fallen: bool) -> None:
        nonlocal n_video
        if snap is None or not (f in snap_frames or (every and f % every == 0) or fallen):
            return
        if skel is not None:
            skel.update(min(int((f / fps + seg_start) * human.fps), human.num_frames - 1))
        img = snap.capture(focus(f, p), 4 if snapshots or n_video else 9)
        if img is None:
            return
        if f in snap_frames or fallen:
            path = os.path.join(out, f"{m.name}_sim_f{f:06d}.png")
            Image.fromarray(img).save(path)
            snapshots.append(path)
        if every and f % every == 0:
            label = f"PhysX, harness x{scale:g}" + ("  FALL" if fallen else "")
            video_frame(img, f, f / fps, f"{m.name}  [{label}]", fallen).save(
                os.path.join(video_tmp.name, f"f{n_video:05d}.png"))
            n_video += 1

    t0 = time.perf_counter()
    ref_lp, ref_lq, ref_sp = reference_pass()
    log(f"reference pass: {n} frames in {time.perf_counter() - t0:.1f}s")
    t0 = time.perf_counter()
    lifts = [reset(0)]
    # retargets often leave the feet a little in the floor: the robot starts that much
    # higher, and the harness keeps that height (not the clip's) as its target
    p_ref[:, 2] += lifts[0]
    falls: list[float] = []
    fall_frames: list[int] = []
    p, q = record(0, [], [])
    show(0, p, False)
    for f in range(n - 1):
        progress("simulate", f, n - 1)
        forces, torques = [], []
        vt = (q_ref[f + 1] - q_ref[f]) * fps
        for s in range(substeps):
            a = s / substeps
            art.set_dof_position_targets((q_ref[f] + a * (q_ref[f + 1] - q_ref[f]))[None])
            art.set_dof_velocity_targets(vt[None])
            if scale > 0:
                p, q, v, w = root_state()
                pt = p_ref[f] + a * (p_ref[f + 1] - p_ref[f])
                Rt = quat_to_matrix(_nlerp(quat_ref[f], quat_ref[f + 1], a))
                F = axes * (kp_lin * (pt - p) + kd_lin * (v_ref[f] - v))
                T = kp_rot * _log_rot(Rt @ quat_to_matrix(q).T) + kd_rot * (w_ref[f] - w)
                robot.root_link.apply_forces_and_torques_at_pos(F[None], T[None])
                forces.append(float(np.linalg.norm(F)))
                torques.append(float(np.linalg.norm(T)))
            SimulationManager.step(steps=1)
        p, q = record(f + 1, forces, torques)
        tilt = np.degrees(np.linalg.norm(_log_rot(quat_to_matrix(q) @ R_ref[f + 1].T)))
        fallen = (np.linalg.norm(p - p_ref[f + 1]) > float(fall.get("root_error_m", 0.5))
                  or tilt > float(fall.get("tilt_error_deg", 60.0))
                  or p[2] - off[2] < float(fall.get("min_pelvis_height_m", 0.3))
                  or p_ref[f + 1, 2] - p[2] > float(fall.get("drop_m", 0.25)))
        show(f + 1, p, fallen)
        if fallen:
            falls.append(round((f + 1) / fps, 3))
            fall_frames.append(f + 1)
            log(f"fall at {(f + 1) / fps:.2f}s")
            if args.no_reset:
                break
            lifts.append(reset(f + 1))
        if f % 300 == 0:
            log(f"frame {f}/{n - 1}")
    log(f"simulated {len(rec['p'])} frames in {time.perf_counter() - t0:.1f}s")

    # results
    T = len(rec["p"])
    P, Q, DOF = np.array(rec["p"]), np.array(rec["q"]), np.array(rec["dof"])
    sim_dof = m.dof_pos[:T].copy()
    sim_dof[:, robot.src] = DOF[:, robot.dst]
    sim_motion = RobotMotion(name=f"{m.name}_sim", joint_names=list(m.joint_names), root_pos=P - off,
                             root_quat=Q, dof_pos=sim_dof, fps=fps, source=os.path.abspath(args.robot_motion))
    base = os.path.join(out, f"{m.name}_sim")
    sim_motion.save_npz(base + ".npz")

    err = np.degrees(np.abs(DOF[:, robot.dst] - q_ref[:T, robot.dst]))
    rmse = np.sqrt((err ** 2).mean(0))
    names = [dof_names[i] for i in robot.dst]
    worst = np.argsort(-rmse)[:5]
    root_err = np.linalg.norm((P - p_ref[:T])[:, :2], axis=1)
    height_err = P[:, 2] - p_ref[:T, 2]  # < 0: the clip floats above where the robot can stand
    rot_err = np.degrees(np.linalg.norm(_log_rot(quat_to_matrix(Q) @ np.swapaxes(R_ref[:T], -1, -2)), axis=-1))
    harness = np.array(rec["f_mean"]) / weight
    flag = float(cfg["report"].get("assist_flag_ratio", 0.2))
    # only the clip's joints: DoFs it does not drive (G1 fingers, held at 0) have tiny effort limits
    tau_ratio = np.abs(np.array(rec["tau"]))[:, robot.dst] / np.maximum(max_eff[robot.dst], 1e-6)
    saturated = (tau_ratio > 1.0).any(1)
    peak = tau_ratio.max(0)
    top_tau = [robot.dst[i] for i in np.argsort(-peak)[:5]]
    peak = dict(zip(robot.dst, peak))
    flagged = float((harness > flag).mean()) if scale > 0 else 0.0
    verdict = []
    if falls:
        verdict.append(f"{len(falls)} fall(s)")
    if flagged > float(cfg["report"].get("max_flagged_ratio", 0.05)):
        verdict.append(f"harness > {flag:.0%} body weight in {flagged:.1%} of frames")
    if saturated.mean() > float(cfg["report"].get("max_saturated_ratio", 0.05)):
        verdict.append(f"torque limits exceeded in {saturated.mean():.1%} of frames")
    support = np.array(rec["support"], float)
    # balance of the clip (reference pass, floor tracked) and of the simulated robot (floor at z = 0)
    ref_track, _, ref_bal = balance_of(robot, ref_lp, ref_lq, ref_sp, fps, qc_cfg)
    LP, SP = np.array(rec["lp"]), np.array(rec["sp"])
    sim_track, _, sim_bal = balance_of(robot, LP, np.array(rec["lq"]), SP, fps, qc_cfg, floor=np.zeros(T),
                                       breaks=[fr + 1 for fr in fall_frames])  # the robot was reset after each fall
    diagnoses = fall_diagnosis(cfg["diagnosis"], fps, fall_frames, robot, ref_sp[:T], SP, LP, np.array(rec["ff"]),
                               weight, tau_ratio, names, sim_track, harness, scale, ref_track)
    physics = {
        "engine": "PhysX via Isaac Sim (isaacsim.core.simulation_manager)",
        "physics_hz": round(fps * substeps, 3),
        "harness_scale": scale,
        "robot_mass_kg": round(mass, 2),
        "consistent": not verdict,
        "issues": verdict,
        "falls": len(falls),
        "fall_times_s": falls[:50],
        "first_fall_cause": diagnoses[0]["primary_cause"] if diagnoses else None,
        "fall_diagnosis": diagnoses[:20],
        "balance": sim_bal,
        "start_lift_m": [round(x, 4) for x in lifts[:20]],
        "simulated_frames": T,
        "harness_force_per_body_weight": _stats(harness),
        "harness_force_max_per_body_weight": _stats(np.array(rec["f_max"]) / weight),
        "harness_torque_nm": _stats(rec["t_mean"], 1),
        f"harness_flagged_ratio(>{flag:.0%} body weight)": round(flagged, 4),
        "feet_support_per_body_weight": _stats(support) if np.isfinite(support).any() else None,
        "tracking": {
            "joint_rmse_deg_median": round(float(np.median(rmse)), 2),
            "joint_rmse_deg_max": round(float(rmse.max()), 2),
            "worst_joints_deg": {names[i]: round(float(rmse[i]), 1) for i in worst},
            "root_position_error_m": _stats(root_err),  # horizontal
            "root_height_error_m": {"mean": round(float(height_err.mean()), 3),
                                    "min": round(float(height_err.min()), 3), "max": round(float(height_err.max()), 3)},
            "root_rotation_error_deg": _stats(rot_err, 1),
        },
        "torque": {
            "saturated_frame_ratio": round(float(saturated.mean()), 4),
            "peak_demand_per_limit": {dof_names[i]: round(float(peak[i]), 2) for i in top_tau},
        },
        "gains": cfg["pd"],
        "assist": cfg["assist"],
    }
    rf = np.arange(T)
    summary = {"clip": m.name, "reference_motion": os.path.abspath(args.robot_motion),
               "simulated_motion": base + ".npz", "fps": fps, "duration_s": round(n / fps, 3),
               "replayed_s": [round(seg_start, 3), round(seg_start + (n - 1) / fps, 3)],  # fall / onset times count from replayed_s[0]
               "physics": physics,
               "robot_sim": foot_summary(rf, np.array(rec["z"]), np.array(rec["flat"]), np.array(rec["xy"]), fps,
                                         robot.foot_names, qc_cfg),
               "snapshots": snapshots}
    summary["reference_balance"] = ref_bal
    if robot_qc is not None:
        summary["reference_robot_qc"] = robot_qc.row()
    if human_qc is not None:
        summary["human_qc"] = human_qc.row()
    if video_tmp is not None:
        summary["video"] = encode_video(video_tmp.name, n_video, fps / every, os.path.abspath(args.video))
        video_tmp.cleanup()
    with open(base + ".json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    log(f"wrote {base}.npz / .json  ->  {'consistent' if not verdict else '; '.join(verdict)}")
    print(json.dumps({k: summary[k] for k in ("clip", "physics", "robot_sim")}, indent=2, ensure_ascii=False,
                     default=str), flush=True)
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
        # fast shutdown ends the process inside close(): hand it the status, or a failed run exits 0
        simulation_app.close(exit_code=code)
    sys.exit(code)
