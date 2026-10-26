"""AMASS-style SMPL / SMPL+H / SMPL-X parameter files -> joint positions.

Pure numpy skeleton FK (no torch); :func:`body_mesh_rig` adds linear-blend
skinning data for drawing the body surface. Joint locations need the
body-model file (e.g. SMPLX_NEUTRAL.npz), which is licence-gated: register at
https://smpl-x.is.tue.mpg.de (SMPL-X) or https://mano.is.tue.mpg.de (SMPL+H)
and point ``model_dir`` / $SMPL_MODEL_DIR at the folder holding
``smplx/`` and/or ``smplh/`` sub-folders (the layout AMASS and the
``smplx`` python package use).
"""

from __future__ import annotations

import os

import numpy as np

from ..motion import SkeletonMotion
from ..rotations import Y_UP_TO_Z_UP, axis_angle_to_matrix

BODY_JOINTS = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot", "neck",
    "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist",
]
_FINGERS = [f"{f}{i}" for f in ("index", "middle", "pinky", "ring", "thumb") for i in (1, 2, 3)]
HAND_JOINTS_L = [f"left_{f}" for f in _FINGERS]
HAND_JOINTS_R = [f"right_{f}" for f in _FINGERS]

JOINT_NAMES = {
    "smpl": BODY_JOINTS + ["left_hand", "right_hand"],
    "smplh": BODY_JOINTS + HAND_JOINTS_L + HAND_JOINTS_R,
    "smplx": BODY_JOINTS + ["jaw", "left_eye", "right_eye"] + HAND_JOINTS_L + HAND_JOINTS_R,
}


def _detect_model_type(n_pose_params: int) -> str:
    return {72: "smpl", 156: "smplh", 165: "smplx"}.get(n_pose_params) or (
        "smplx" if n_pose_params > 156 else "smplh"
    )


def _find_model_file(model_dir: str, model_type: str, gender: str) -> str:
    gender = gender.lower() if gender else "neutral"
    names = [f"{model_type.upper()}_{gender.upper()}.npz", f"{model_type}_{gender}.npz", "model.npz"]
    folders = [
        os.path.join(model_dir, model_type, gender),
        os.path.join(model_dir, model_type),
        os.path.join(model_dir, model_type.upper()),
        model_dir,
    ]
    for d in folders:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    if gender != "neutral":
        return _find_model_file(model_dir, model_type, "neutral")
    raise FileNotFoundError(
        f"no {model_type} model for gender '{gender}' under {model_dir!r} "
        f"(looked for {names[0]} in {model_type}/[{gender}/])"
    )


def _rest_joints(model_path: str, betas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = np.load(model_path, allow_pickle=True)
    v = m["v_template"].astype(np.float64)
    shapedirs = m["shapedirs"].astype(np.float64)
    n = min(len(betas), shapedirs.shape[-1])
    v = v + shapedirs[..., :n] @ betas[:n]
    jreg = m["J_regressor"]
    if jreg.dtype == object:  # scipy sparse pickled into the npz
        jreg = jreg.item().toarray()
    joints = np.asarray(jreg, dtype=np.float64) @ v
    parents = m["kintree_table"][0].astype(int).copy()
    parents[0] = -1
    return joints, parents


def load_amass_npz(
    path: str,
    model_dir: str | None = None,
    gender: str | None = None,
    body_only: bool = False,
    with_rotations: bool = False,
) -> SkeletonMotion:
    """Load an AMASS-style npz (poses / trans / betas / framerate).

    with_rotations also fills ``SkeletonMotion.rotations`` (world joint frames; the
    joints' own axes are the body model's Y-up axes) and ``meta["rest_pose"]``:
    the zero pose (a T-pose for SMPL/SMPL-X) of this subject's shape, stood up in
    the Z-up world, as (positions (J, 3), frames (J, 3, 3)) — the retargeting
    reference pose.
    """
    d = np.load(path, allow_pickle=True)
    if "poses" not in d:
        raise ValueError(f"{path}: no 'poses' array (not an AMASS-style SMPL file)")
    poses = d["poses"].astype(np.float64)
    trans = d["trans"].astype(np.float64)
    betas = d["betas"].astype(np.float64).reshape(-1) if "betas" in d else np.zeros(10)
    fps = float(d.get("mocap_framerate", d.get("mocap_frame_rate", 0.0)) or 0.0)
    if gender is None:
        g = d.get("gender", "neutral")
        gender = str(g.item() if hasattr(g, "item") else g)
        gender = gender.decode() if isinstance(gender, bytes) else gender
    model_type = _detect_model_type(poses.shape[1])

    model_dir = model_dir or os.environ.get("SMPL_MODEL_DIR")
    if not model_dir:
        raise FileNotFoundError(
            "SMPL body-model files are required to compute joints from AMASS npz. "
            "Pass --smpl-model-dir or set SMPL_MODEL_DIR (see retlens/io/smpl.py)."
        )
    rest, parents = _rest_joints(_find_model_file(model_dir, model_type, gender), betas)

    n_j = min(len(parents), poses.shape[1] // 3)
    rest, parents = rest[:n_j], parents[:n_j]
    rot = axis_angle_to_matrix(poses[:, : n_j * 3].reshape(len(poses), n_j, 3))

    T = len(poses)
    g_rot = np.zeros((T, n_j, 3, 3))
    g_pos = np.zeros((T, n_j, 3))
    g_rot[:, 0] = rot[:, 0]
    g_pos[:, 0] = rest[0] + trans
    for j in range(1, n_j):
        p = parents[j]
        g_rot[:, j] = g_rot[:, p] @ rot[:, j]
        g_pos[:, j] = g_pos[:, p] + np.einsum("tij,j->ti", g_rot[:, p], rest[j] - rest[p])

    names = JOINT_NAMES.get(model_type, [])[:n_j]
    names += [f"joint_{i}" for i in range(len(names), n_j)]
    if body_only:
        g_pos, g_rot, rest, parents, names = g_pos[:, :22], g_rot[:, :22], rest[:22], parents[:22], names[:22]

    meta = {"format": "amass_npz", "model_type": model_type, "gender": gender}
    if with_rotations:
        n = len(names)
        meta["rest_pose"] = ((rest - rest[0]) @ Y_UP_TO_Z_UP.T, np.broadcast_to(Y_UP_TO_Z_UP, (n, 3, 3)).copy())
    return SkeletonMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=names,
        parents=parents,
        positions=g_pos,  # AMASS is already Z-up, meters
        fps=fps,
        source=os.path.abspath(path),
        kind="skeleton",
        meta=meta,
        rotations=g_rot if with_rotations else None,
    )


class BodyMeshRig:
    """Body surface of an AMASS clip by linear blend skinning (no pose correctives).

    ``vertices(f)`` -> (V, 3) world vertices of frame f (Z-up, meters), the same
    world as :func:`load_amass_npz`. ``faces`` (F, 3).
    """

    def __init__(self, path: str, model_dir: str | None = None, gender: str | None = None):
        self.motion = load_amass_npz(path, model_dir=model_dir, gender=gender, with_rotations=True)
        d = np.load(path, allow_pickle=True)
        betas = d["betas"].astype(np.float64).reshape(-1) if "betas" in d else np.zeros(10)
        model_dir = model_dir or os.environ.get("SMPL_MODEL_DIR")
        m = np.load(_find_model_file(model_dir, self.motion.meta["model_type"], self.motion.meta["gender"]),
                    allow_pickle=True)
        v = m["v_template"].astype(np.float64)
        shapedirs = m["shapedirs"].astype(np.float64)
        n = min(len(betas), shapedirs.shape[-1])
        self.rest = v + shapedirs[..., :n] @ betas[:n]
        self.faces = np.asarray(m["f"], dtype=np.int32)
        J = len(self.motion.joint_names)
        self.weights = np.asarray(m["weights"], dtype=np.float64)[:, :J]
        self.rest_joints, _ = _rest_joints(_find_model_file(model_dir, self.motion.meta["model_type"],
                                                            self.motion.meta["gender"]), betas)
        self.rest_joints = self.rest_joints[:J]
        self.fps = self.motion.fps
        self.num_frames = self.motion.num_frames

    def vertices(self, f: int) -> np.ndarray:
        G = self.motion.rotations[f]  # (J, 3, 3) world joint rotations
        p = self.motion.positions[f]  # (J, 3) world joint positions
        A = np.concatenate([G, (p - np.einsum("jab,jb->ja", G, self.rest_joints))[..., None]], -1)  # (J, 3, 4)
        B = (self.weights @ A.reshape(len(A), 12)).reshape(-1, 3, 4)
        return np.einsum("vab,vb->va", B[..., :3], self.rest) + B[..., 3]
