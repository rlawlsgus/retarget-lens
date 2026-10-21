"""Balance on / off: replay a robot motion in MuJoCo with and without a closed-loop tracking policy.

The Isaac physics replay (tools/isaac_replay.py --physics) follows the clip with stiff joint PD and
nothing that keeps the balance, so with the harness off it falls even on clean data. A robot that
imitates mocap for real runs a tracking policy instead: it reads the reference and its own IMU /
joint state and bends the reference to stay up. This module runs both on the same model:

    controller "pd"   open loop, like --assist 0: stiff PD on the reference angles and velocities
                      (configs/physics.yaml gains, position servos integrated implicitly), no balance
    controller "gmt"  GMT (General Motion Tracking, Chen et al. 2025; Apache-2.0, the authors provide
                      the model for research use only; scripts/install_gmt.ps1): a pretrained general
                      tracker for the G1 that sees 20 reference frames up to 1.9 s ahead, at 50 Hz,
                      with its own PD (kp 40-150) as on the robot

Both use GMT's G1 model (the 29-DoF G1 with the wrists fixed: 23 DoF; 4 contact spheres per foot) at
1 kHz, start in the clip's first pose and count falls with configs/physics.yaml's rules (tilt, pelvis
height, drop below the clip; not the 0.5 m root distance, which a tracker drifting along its own path
would trip). After a fall the robot restarts in the clip's pose at that time.

The GMT part is a numpy port of the authors' sim2sim.py / utils/motion_lib.py (commit 2a590de):
same observation layout and scales, same velocity estimate (finite difference + 19-frame box filter
with zero padding), same action scaling and torque PD. One deliberate difference: at the end of the
clip the reference holds the last frame instead of looping back to the start.
"""

from __future__ import annotations

import collections
import json
import os
import re
from dataclasses import dataclass, field

import numpy as np

from . import paths, settings
from .motion import RobotMotion

# ---------------------------------------------------------------------------------- GMT constants
GMT_DOFS = ["left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint", "left_knee_joint",
            "left_ankle_pitch_joint", "left_ankle_roll_joint",
            "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint", "right_knee_joint",
            "right_ankle_pitch_joint", "right_ankle_roll_joint",
            "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
            "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint", "left_elbow_joint",
            "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint", "right_elbow_joint"]
GMT_KP = np.array([100, 100, 100, 150, 40, 40, 100, 100, 100, 150, 40, 40, 150, 150, 150,
                   40, 40, 40, 40, 40, 40, 40, 40], dtype=np.float64)
GMT_KD = np.array([2, 2, 2, 4, 2, 2, 2, 2, 2, 4, 2, 2, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5], dtype=np.float64)
GMT_DEFAULT = np.array([-0.2, 0.0, 0.0, 0.4, -0.2, 0.0, -0.2, 0.0, 0.0, 0.4, -0.2, 0.0, 0.0, 0.0, 0.0,
                        0.0, 0.4, 0.0, 1.2, 0.0, -0.4, 0.0, 1.2])
TORQUE_LIMIT = np.array([88, 139, 88, 139, 50, 50, 88, 139, 88, 139, 50, 50, 88, 50, 50,
                         25, 25, 25, 25, 25, 25, 25, 25], dtype=np.float64)
TAR_STEPS = np.array([1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95])
SIM_DT = 0.001
DECIMATION = 20  # policy at 50 Hz
CONTROL_DT = SIM_DT * DECIMATION
ACTION_SCALE = 0.5
HISTORY = 20
N_PROPRIO = 3 + 2 + 3 * len(GMT_DOFS)
ANG_VEL_SCALE, DOF_VEL_SCALE = 0.25, 0.05
ZERO_VEL_OBS = [4, 5, 10, 11]  # ankle velocities are hidden from the policy
SMOOTH_FRAMES = 19

# bodies whose pelvis-relative positions measure tracking (local key-body error)
KEY_BODIES = ["torso_link", "left_knee_link", "right_knee_link", "left_ankle_roll_link", "right_ankle_roll_link",
              "left_elbow_link", "right_elbow_link", "left_rubber_hand", "right_rubber_hand"]
CONTROLLERS = ("pd", "gmt")
LABELS = {"pd": "제어기 없음 (PD 재생)", "gmt": "추적 정책 (GMT)"}


def gmt_dir() -> str:
    return settings.gmt_dir()


def gmt_paths(root: str | None = None) -> dict:
    """{"policy", "model"}: where GMT's files are (whether or not they are there). The model falls back to
    the copy staged into the program's resources when the GMT folder has none (the installed program)."""
    root = root or gmt_dir()
    model = os.path.join(root, settings.GMT_MODEL)
    bundled = paths.resource(*settings.BUNDLED_G1_MODEL)
    if not os.path.isfile(model) and os.path.isfile(bundled):
        model = bundled
    return {"policy": os.path.join(root, settings.GMT_POLICY), "model": model}


def gmt_files(root: str | None = None) -> dict:
    out = gmt_paths(root)
    missing = [p for p in out.values() if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(f"GMT not found ({', '.join(missing)}): run scripts\\install_gmt.ps1 "
                                "or set KHUMANOID_GMT_DIR")
    return out


# ---------------------------------------------------------------------------- quaternions (xyzw)
def quat_mul(a, b):
    x1, y1, z1, w1 = np.moveaxis(a, -1, 0)
    x2, y2, z2, w2 = np.moveaxis(b, -1, 0)
    return np.stack([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                     w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2], axis=-1)


def quat_conj(q):
    return np.concatenate([-q[..., :3], q[..., 3:]], axis=-1)


def quat_to_exp_map(q):
    """GMT's torch_utils.quat_to_exp_map: angle = wrap(2 acos w), axis = xyz / sin(theta/2)."""
    w = np.clip(q[..., 3], -1.0, 1.0)
    sin_t = np.sqrt(np.maximum(1.0 - w * w, 0.0))
    angle = 2.0 * np.arccos(w)
    angle = np.arctan2(np.sin(angle), np.cos(angle))
    ok = np.abs(sin_t) > 1e-5
    axis = np.where(ok[..., None], q[..., :3] / np.where(ok, sin_t, 1.0)[..., None], [0.0, 0.0, 1.0])
    return np.where(ok, angle, 0.0)[..., None] * axis


def slerp(q0, q1, t):
    """GMT's torch_utils.slerp (t per row)."""
    cos_h = np.sum(q0 * q1, axis=-1)
    q1 = np.where((cos_h < 0)[..., None], -q1, q1)
    cos_h = np.abs(cos_h)[..., None]
    half = np.arccos(np.clip(cos_h, -1.0, 1.0))
    sin_h = np.sqrt(np.maximum(1.0 - cos_h * cos_h, 0.0))
    t = t[..., None]
    with np.errstate(divide="ignore", invalid="ignore"):
        q = (np.sin((1 - t) * half) * q0 + np.sin(t * half) * q1) / sin_h
    q = np.where(np.abs(sin_h) < 0.001, 0.5 * q0 + 0.5 * q1, q)
    return np.where(np.abs(cos_h) >= 1, q0, q)


def quat_rotate_inverse(q, v):
    """World vector -> the frame of q (xyzw), as GMT's sim2sim.quat_rotate_inverse."""
    qv, w = q[..., :3], q[..., 3:4]
    return v * (2.0 * w ** 2 - 1.0) - np.cross(qv, v) * w * 2.0 + qv * np.sum(qv * v, axis=-1, keepdims=True) * 2.0


def roll_pitch_xyzw(q):
    x, y, z, w = np.moveaxis(q, -1, 0)
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    return roll, pitch


def rpy_wxyz(q):
    """GMT's sim2sim.quatToEuler (the IMU quaternion is wxyz)."""
    w, x, y, z = q
    roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    sinp = 2 * (w * y - z * x)
    pitch = np.copysign(np.pi / 2, sinp) if abs(sinp) >= 1 else np.arcsin(sinp)
    yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return np.array([roll, pitch, yaw])


def _box_smooth(x: np.ndarray) -> np.ndarray:
    """torch conv1d with a 19-tap box and padding='same' (zeros past both ends)."""
    from scipy.ndimage import uniform_filter1d

    return uniform_filter1d(x, size=SMOOTH_FRAMES, axis=0, mode="constant", cval=0.0)


# ------------------------------------------------------------------------------------ reference
class Reference:
    """One clip as GMT's MotionLib sees it (root xyzw, 23 DoF), sampled at any time."""

    def __init__(self, root_pos, root_rot_xyzw, dof_pos, fps: float, loop: bool = False):
        self.fps = float(fps)
        self.root_pos = np.asarray(root_pos, dtype=np.float64)
        self.root_rot = np.asarray(root_rot_xyzw, dtype=np.float64)
        self.dof_pos = np.asarray(dof_pos, dtype=np.float64)
        self.loop = loop
        n = len(self.root_pos)
        self.num_frames = n
        self.length = (n - 1) / self.fps
        vel = np.zeros_like(self.root_pos)
        vel[:-1] = self.fps * (self.root_pos[1:] - self.root_pos[:-1])
        vel[-1] = vel[-2]
        self.root_vel = _box_smooth(vel)
        ang = np.zeros_like(self.root_pos)
        ang[:-1] = self.fps * quat_to_exp_map(quat_mul(self.root_rot[1:], quat_conj(self.root_rot[:-1])))
        ang[-1] = ang[-2]
        self.root_ang_vel = _box_smooth(ang)
        dvel = np.zeros_like(self.dof_pos)
        dvel[:-1] = self.fps * (self.dof_pos[1:] - self.dof_pos[:-1])
        dvel[-1] = dvel[-2]
        self.dof_vel = _box_smooth(dvel)
        # the zero padding above fades GMT's velocity estimates near both ends (that is what the policy
        # was trained on); a restart's physical velocities use the mean of the taps inside the clip
        inside = _box_smooth(np.ones((n, 1)))
        self.start_vel = (self.root_vel / inside, self.root_ang_vel / inside, self.dof_vel / inside)
        # the PD replay's velocity target: the derivative of its own interpolated position target
        self.dof_vel_fd = np.zeros_like(self.dof_pos)
        self.dof_vel_fd[:-1] = dvel[:-1]

    @classmethod
    def from_motion(cls, m: RobotMotion, loop: bool = False) -> "Reference":
        col = {n: i for i, n in enumerate(m.joint_names)}
        missing = [n for n in GMT_DOFS if n not in col]
        if missing:
            raise ValueError(f"{m.name}: the motion lacks {', '.join(missing)} (GMT needs the G1 joints)")
        dof = m.dof_pos[:, [col[n] for n in GMT_DOFS]]
        xyzw = np.concatenate([m.root_quat[:, 1:4], m.root_quat[:, :1]], axis=1)
        return cls(m.root_pos, xyzw, dof, m.fps, loop=loop)

    def _index(self, times):
        """Frame index, blend and 'past the end' mask (GMT's _calc_frame_blend; looping as GMT, or holding)."""
        t = np.atleast_1d(np.asarray(times, dtype=np.float64))
        if self.loop and self.length > 0:
            t = t - np.floor(t / self.length) * self.length
        phase = np.clip(t / self.length, 0.0, 1.0) if self.length > 0 else np.zeros_like(t)
        f0 = (phase * (self.num_frames - 1)).astype(np.int64)
        b = phase * (self.num_frames - 1) - f0
        past = (t > self.length) if not self.loop else np.zeros(t.shape, dtype=bool)
        return f0, np.minimum(f0 + 1, self.num_frames - 1), b, past

    def frame(self, times):
        """root_pos, root_rot, root_vel, root_ang_vel, dof_pos, dof_vel at the given times (s). Past the end
        of a non-looping clip: the last pose, standing still."""
        f0, f1, b, past = self._index(times)
        still = past[:, None]
        b = b[:, None]
        return ((1 - b) * self.root_pos[f0] + b * self.root_pos[f1],
                slerp(self.root_rot[f0], self.root_rot[f1], b[:, 0]),
                np.where(still, 0.0, self.root_vel[f0]), np.where(still, 0.0, self.root_ang_vel[f0]),
                (1 - b) * self.dof_pos[f0] + b * self.dof_pos[f1], np.where(still, 0.0, self.dof_vel[f0]))

    def start_velocities(self, t: float):
        """Root linear / angular and joint velocities to restart the robot with at time t."""
        f0, _, _, past = self._index([t])
        if past[0]:
            return np.zeros(3), np.zeros(3), np.zeros(self.dof_pos.shape[1])
        return tuple(v[f0[0]] for v in self.start_vel)

    def pd_velocity(self, times):
        """The PD replay's joint velocity targets: the slope of the interpolated joint targets (0 when held)."""
        f0, _, _, past = self._index(times)
        return np.where(past[:, None], 0.0, self.dof_vel_fd[f0])

    def mimic_obs(self, step: int) -> np.ndarray:
        """GMT's _get_mimic_obs: 20 future frames x (root z, roll, pitch, local lin vel, local yaw rate, 23 DoF)."""
        pos, rot, vel, ang, dof, _ = self.frame((step + TAR_STEPS) * CONTROL_DT)
        roll, pitch = roll_pitch_xyzw(rot)
        lin = quat_rotate_inverse(rot, vel)
        yaw_rate = quat_rotate_inverse(rot, ang)[:, 2:3]
        return np.concatenate([pos[:, 2:3], roll[:, None], pitch[:, None], lin, yaw_rate, dof], axis=1).reshape(-1)


# -------------------------------------------------------------------------------------- sim setup
def pd_gains(config_path: str | None = None):
    """configs/physics.yaml's stiff drive gains (first matching pattern) for GMT's 23 joints."""
    import yaml

    with open(config_path or paths.resource("configs", "physics.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    kp, kd = np.zeros(len(GMT_DOFS)), np.zeros(len(GMT_DOFS))
    for i, n in enumerate(GMT_DOFS):
        for rule in cfg["pd"]:
            if re.fullmatch(rule["pattern"], n):
                kp[i], kd[i] = rule["stiffness"], rule["damping"]
                break
    return kp, kd, cfg.get("fall", {})


@dataclass
class Result:
    controller: str
    times: np.ndarray  # (N,) s, 50 Hz
    root_pos: np.ndarray  # (N, 3)
    root_quat: np.ndarray  # (N, 4) wxyz
    dof_pos: np.ndarray  # (N, 23)
    metrics: dict = field(default_factory=dict)


class G1Sim:
    """GMT's G1 model in MuJoCo, driven either by GMT or by open-loop stiff PD."""

    def __init__(self, model_path: str, controller: str, policy_path: str | None = None,
                 physics_config: str | None = None):
        import mujoco

        self.mj = mujoco
        if controller not in CONTROLLERS:
            raise ValueError(f"controller must be one of {CONTROLLERS}")
        self.controller = controller
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.model.opt.timestep = SIM_DT
        names = [self.model.joint(self.model.jnt_qposadr.size - len(GMT_DOFS) + i).name for i in range(len(GMT_DOFS))]
        if names != GMT_DOFS:
            raise ValueError(f"unexpected joint order in {model_path}: {names}")
        self.pd_kp, self.pd_kd, self.fall_cfg = pd_gains(physics_config)
        if controller == "pd":
            # stiff servos as MuJoCo position actuators (kv integrated implicitly): explicit torque PD
            # with kd 20-40 on light links is unstable at 1 kHz
            m = self.model
            m.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
            for a in range(m.nu):
                m.actuator_gaintype[a] = mujoco.mjtGain.mjGAIN_FIXED
                m.actuator_gainprm[a, 0] = self.pd_kp[a]
                m.actuator_biastype[a] = mujoco.mjtBias.mjBIAS_AFFINE
                m.actuator_biasprm[a, :3] = [0.0, -self.pd_kp[a], -self.pd_kd[a]]
                m.actuator_forcelimited[a] = 1
                m.actuator_forcerange[a] = [-TORQUE_LIMIT[a], TORQUE_LIMIT[a]]
                m.actuator_ctrllimited[a] = 0
        self.data = mujoco.MjData(self.model)
        self.ref_data = mujoco.MjData(self.model)
        self.dof_q = self.model.jnt_qposadr[-len(GMT_DOFS):]
        self.dof_v = self.model.jnt_dofadr[-len(GMT_DOFS):]
        self.key_bodies = [self.model.body(n).id for n in KEY_BODIES]
        self.pelvis = self.model.body("pelvis").id
        self.feet = [g for g in range(self.model.ngeom)
                     if self.model.body(self.model.geom_bodyid[g]).name.endswith("ankle_roll_link")
                     and self.model.geom_type[g] == mujoco.mjtGeom.mjGEOM_SPHERE]
        self.policy = None
        if controller == "gmt":
            import torch

            self.torch = torch
            self.policy = torch.jit.load(policy_path, map_location="cpu")
            self.policy.eval()

    # -- state
    def set_pose(self, data, pos, rot_xyzw, dof, vel=None, ang_vel=None, dof_vel=None, lift: bool = False):
        mj = self.mj
        data.qpos[:3] = pos
        data.qpos[3:7] = [rot_xyzw[3], rot_xyzw[0], rot_xyzw[1], rot_xyzw[2]]
        data.qpos[self.dof_q] = dof
        data.qvel[:] = 0.0
        if vel is not None:
            data.qvel[:3] = vel
            data.qvel[3:6] = quat_rotate_inverse(rot_xyzw[None], ang_vel[None])[0]  # free joint: local angular
            data.qvel[self.dof_v] = dof_vel
        mj.mj_forward(self.model, data)
        if lift:  # start with the soles on the floor, not in it (as the Isaac replay does)
            low = min(data.geom_xpos[g][2] - self.model.geom_size[g][0] for g in self.feet)
            if low < 0.0:
                data.qpos[2] -= low - 0.001
                mj.mj_forward(self.model, data)

    def reset_to(self, ref: Reference, t: float):
        pos, rot, _, _, dof, _ = (a[0] for a in ref.frame([t]))
        vel, ang, dvel = ref.start_velocities(t)
        self.mj.mj_resetData(self.model, self.data)
        self.set_pose(self.data, pos, rot, dof, vel, ang, dvel, lift=True)
        self.last_action = np.zeros(len(GMT_DOFS))
        self.history = collections.deque([np.zeros(N_PROPRIO) for _ in range(HISTORY)], maxlen=HISTORY)

    def reset_home(self):
        """GMT's own start: keyframe 'home' (standing, 1 m up) and one step."""
        self.mj.mj_resetDataKeyframe(self.model, self.data, 0)
        self.mj.mj_step(self.model, self.data)
        self.last_action = np.zeros(len(GMT_DOFS))
        self.history = collections.deque([np.zeros(N_PROPRIO) for _ in range(HISTORY)], maxlen=HISTORY)

    # -- control
    def policy_target(self, ref: Reference, step: int):
        d = self.data
        dof_pos = d.qpos.astype(np.float32)[-len(GMT_DOFS):]
        dof_vel = d.qvel.astype(np.float32)[-len(GMT_DOFS):]
        quat = d.sensor("orientation").data.astype(np.float32)
        ang_vel = d.sensor("angular-velocity").data.astype(np.float32)
        obs_vel = dof_vel.copy()
        obs_vel[ZERO_VEL_OBS] = 0.0
        prop = np.concatenate([ang_vel * ANG_VEL_SCALE, rpy_wxyz(quat)[:2], (dof_pos - GMT_DEFAULT),
                               obs_vel * DOF_VEL_SCALE, self.last_action])
        obs = np.concatenate([ref.mimic_obs(step), prop, np.array(self.history).reshape(-1)])
        with self.torch.no_grad():
            raw = self.policy(self.torch.from_numpy(obs).float().unsqueeze(0)).numpy().squeeze()
        self.last_action = raw.copy()
        self.history.append(prop)
        return np.clip(raw, -10.0, 10.0) * ACTION_SCALE + GMT_DEFAULT

    def apply(self, target, ref_dof_vel=None) -> bool:
        """Joint drives for one 1 ms step; True when a joint asks for more than its torque limit."""
        d = self.data
        q, qd = d.qpos[self.dof_q], d.qvel[self.dof_v]
        if self.controller == "gmt":
            tau = (target - q.astype(np.float32)) * GMT_KP - qd.astype(np.float32) * GMT_KD
            d.ctrl[:] = np.clip(tau, -TORQUE_LIMIT, TORQUE_LIMIT)
        else:  # position servo: ctrl = q* + kd/kp qd*, force = kp (ctrl - q) - kd qd = kp (q* - q) + kd (qd* - qd)
            d.ctrl[:] = target + self.pd_kd / self.pd_kp * ref_dof_vel
            tau = self.pd_kp * (target - q) + self.pd_kd * (ref_dof_vel - qd)
        return bool(np.any(np.abs(tau) > TORQUE_LIMIT))

    # -- measures
    def _local_bodies(self, data):
        xpos = data.xpos[self.key_bodies] - data.xpos[self.pelvis]
        q = data.qpos[3:7]
        yaw = np.arctan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
        c, s = np.cos(-yaw), np.sin(-yaw)
        return xpos @ np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])

    def fallen(self, ref_pos, ref_rot) -> str | None:
        cfg = self.fall_cfg
        d = self.data
        z = d.qpos[2]
        up = d.xmat[self.pelvis].reshape(3, 3)[:, 2]
        x, y, zq, w = ref_rot
        ref_up = np.array([2 * (x * zq + w * y), 2 * (y * zq - w * x), 1 - 2 * (x * x + y * y)])
        tilt = np.degrees(np.arccos(np.clip(up @ ref_up, -1.0, 1.0)))
        if tilt > cfg.get("tilt_error_deg", 60.0):
            return "tilt"
        low = cfg.get("min_pelvis_height_m", 0.3)
        if z < low <= ref_pos[2]:  # not while the clip itself lies or crawls that low
            return "low"
        if z < ref_pos[2] - cfg.get("drop_m", 0.25):
            return "drop"
        return None


def run(sim: G1Sim, ref: Reference, hold_s: float = 1.0, grace_s: float = 0.5, home: bool = False,
        duration_s: float | None = None, progress=None) -> Result:
    """Simulate the clip, then hold_s on its last pose. A fall restarts from the clip at that time (and is
    not checked again for grace_s). Falls and torque limits in the hold are reported apart from the clip's."""
    mj = sim.mj
    total = duration_s if duration_s is not None else ref.length + hold_s
    n_ctrl = int(round(total / CONTROL_DT))
    if home:
        sim.reset_home()
    else:
        sim.reset_to(ref, 0.0)
    times, roots, quats, dofs = [], [], [], []
    joint_err, body_err, height_err, tilt_err, corr = [], [], [], [], []
    falls, causes, hold_falls, drift_at_fall = [], [], [], []
    sat = {True: 0, False: 0}  # steps over a torque limit, in the clip / in the hold
    steps = {True: 0, False: 0}
    last_reset = 0.0
    step_t = np.arange(DECIMATION) * SIM_DT
    for k in range(n_ctrl):
        t = k * CONTROL_DT
        in_clip = t <= ref.length
        pos, rot, vel, ang, dof, dvel = ref.frame([t])
        pos, rot, dof = pos[0], rot[0], dof[0]
        if not home and t - last_reset >= grace_s:
            cause = sim.fallen(pos, rot)
            if cause:
                if in_clip:
                    falls.append(round(t, 3))
                    causes.append(cause)
                else:
                    hold_falls.append(round(t, 3))
                drift_at_fall.append(float(np.linalg.norm(sim.data.qpos[:2] - pos[:2])))
                sim.reset_to(ref, t)
                last_reset = t
        # the state the controller sees at this tick (50 Hz)
        d = sim.data
        times.append(t)
        roots.append(d.qpos[:3].copy())
        quats.append(d.qpos[3:7].copy())
        dofs.append(d.qpos[sim.dof_q].copy())
        if in_clip:
            sim.set_pose(sim.ref_data, pos, rot, dof)
            joint_err.append(d.qpos[sim.dof_q] - dof)
            body_err.append(np.linalg.norm(sim._local_bodies(d) - sim._local_bodies(sim.ref_data), axis=1).mean())
            height_err.append(d.qpos[2] - pos[2])
            up = d.xmat[sim.pelvis].reshape(3, 3)[:, 2]
            ref_up = sim.ref_data.xmat[sim.pelvis].reshape(3, 3)[:, 2]
            tilt_err.append(np.degrees(np.arccos(np.clip(up @ ref_up, -1.0, 1.0))))
        if sim.controller == "gmt":
            target = sim.policy_target(ref, k)
            if in_clip:
                corr.append(target - dof)
            for _ in range(DECIMATION):
                sat[in_clip] += sim.apply(target)
                steps[in_clip] += 1
                mj.mj_step(sim.model, sim.data)
        else:
            dof_s = ref.frame(t + step_t)[4]
            dvel_s = ref.pd_velocity(t + step_t)
            for i in range(DECIMATION):
                sat[in_clip] += sim.apply(dof_s[i], dvel_s[i])
                steps[in_clip] += 1
                mj.mj_step(sim.model, sim.data)
        if progress and k % 25 == 0:  # every 0.5 s simulated (RetLens's runner cancels from here)
            progress(k, n_ctrl)
    je = np.degrees(np.array(joint_err)) if joint_err else np.zeros((0, len(GMT_DOFS)))
    legs = slice(0, 12)
    end_pos = ref.frame([min(total, ref.length)])[0][0]
    final_drift = float(np.linalg.norm(sim.data.qpos[:2] - end_pos[:2]))
    metrics = {
        "controller": sim.controller,
        "simulated_s": round(total, 3),
        "clip_s": round(ref.length, 3),
        "falls": len(falls),  # inside the clip
        "fall_times_s": falls,
        "fall_causes": causes,
        "first_fall_s": falls[0] if falls else None,
        "hold_falls": len(hold_falls),  # standing on the last pose after the clip
        "hold_fall_times_s": hold_falls,
        "joint_rmse_deg": round(float(np.sqrt(np.mean(je ** 2))), 2) if je.size else None,
        "leg_joint_rmse_deg": round(float(np.sqrt(np.mean(je[:, legs] ** 2))), 2) if je.size else None,
        "body_error_cm": round(100 * float(np.mean(body_err)), 2) if body_err else None,
        "pelvis_height_error_cm": round(100 * float(np.mean(np.abs(height_err))), 2) if height_err else None,
        "tilt_error_deg": round(float(np.mean(tilt_err)), 2) if tilt_err else None,
        # a restart puts the robot back on the clip's root, so the end drift only means something without falls
        "root_drift_m": round(final_drift, 3) if not falls and not hold_falls else None,
        "root_drift_max_m": round(max(drift_at_fall + [final_drift]), 3),
        "policy_correction_deg": round(float(np.degrees(np.mean(np.abs(corr)))), 2) if corr else None,
        "torque_saturated_ratio": round(sat[True] / max(steps[True], 1), 4),
        "hold_torque_saturated_ratio": round(sat[False] / steps[False], 4) if steps[False] else None,
    }
    return Result(sim.controller, np.array(times), np.array(roots), np.array(quats), np.array(dofs), metrics)


def result_motion(res: Result, name: str, joint_names: list[str]) -> RobotMotion:
    """The simulated motion in the project's robot npz layout (joints GMT does not drive stay 0)."""
    col = {n: i for i, n in enumerate(joint_names)}
    dof = np.zeros((len(res.times), len(joint_names)))
    for j, n in enumerate(GMT_DOFS):
        if n in col:
            dof[:, col[n]] = res.dof_pos[:, j]
    return RobotMotion(name=name, joint_names=list(joint_names), root_pos=res.root_pos, root_quat=res.root_quat,
                       dof_pos=dof, fps=1.0 / CONTROL_DT, source="policy_replay")


def save_result(res: Result, out_npz: str, joint_names: list[str], info: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_npz)), exist_ok=True)
    name = os.path.splitext(os.path.basename(out_npz))[0]
    result_motion(res, name, joint_names).save_npz(out_npz)
    with open(os.path.splitext(out_npz)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({**info, "policy_replay": res.metrics}, f, ensure_ascii=False, indent=1)
    return out_npz
