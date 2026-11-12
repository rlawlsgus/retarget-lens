"""Objects captured with a human motion (FBX props and furniture, retlens.motion.ObjectTrack) next to its
retarget: where they sit in the robot's world, and how well the robot's hands meet them.

The robot motion is the human's scaled (GMR scales positions), so an object's path is mapped the same
way: scaled about the skeleton's start point on the floor and put on the robot's start (human_to_robot).
Its shape keeps its real size: a box does not shrink for a smaller robot. The mapping is fitted from
the pelvis paths (human_scale), so it is approximate where the retarget's root wanders off the human's.

Hand-object contact (hand_object_metrics): a human hand touches an object when its palm point or one of its
finger bases is within CONTACT_M of the object's surface (points spread over its mesh; a bare node: its origin),
so a ball held in the fingers counts as well as one in the palm. For every frame and hand where the human touches
an object, the robot's same hand (its palm point) is measured against that same object. It reaches the object
when its palm point is within CONTACT_M plus the human's own palm offset: how much farther the human's palm point
is from the object than the hand point that touches it, both mapped to the robot like the object. A palm grip
gets no allowance; a ball held in the fingers sits that far past the palm for a robot that copies the hand exactly.

    hand_obj_contact_s   seconds with a human hand on an object
    hand_obj_reach_pct   of those (frame, hand) pairs, the share where the robot hand reaches the object too
    hand_obj_err_cm      their mean robot hand - object distance (cm)

The human palm point: the hand joint moved halfway to the mean of its child joints (finger bases) when it has
any, else the hand joint (a wrist). The robot's: its hand body (the arm's last body) moved halfway to the mean of
its fingers' first bodies when it has jointed fingers (that body sits at the wrist), else the hand body itself
(the G1's rubber hand).
"""

from __future__ import annotations

import numpy as np

from .motion import ObjectTrack, RobotMotion, SkeletonMotion

CONTACT_M = 0.06  # palm point to surface: a hand on the object
MAX_POINTS = 1500  # surface points per object for the distances (a subset of a dense mesh's vertices)


def human_scale(h: SkeletonMotion, r: RobotMotion) -> float:
    """Uniform scale that puts the source skeleton on the robot (GMR scales positions): fitted from the
    pelvis paths when the clip travels, else the ratio of pelvis heights."""
    hips = next((i for i, n in enumerate(h.joint_names) if n.lower() in ("hips", "pelvis", "hip")), 0)
    tr = np.arange(r.num_frames) / r.fps
    hp = h.positions[np.clip(np.round(tr * h.fps).astype(int), 0, h.num_frames - 1), hips]
    dh = hp[:, :2] - hp[:1, :2]
    dr = r.root_pos[:, :2] - r.root_pos[:1, :2]
    if np.nanmax(np.linalg.norm(dh, axis=1)) > 0.5:
        return float(np.nansum(dh * dr) / max(np.nansum(dh * dh), 1e-9))
    return float(np.nanmean(r.root_pos[:, 2]) / max(np.nanmean(hp[:, 2]), 1e-6))


def anchor(h: SkeletonMotion) -> np.ndarray:
    """The skeleton's first seen root position (the point the mapping scales about, at floor level)."""
    root = h.positions[:, 0]
    ok = np.isfinite(root).all(axis=1)
    return root[int(np.argmax(ok))].copy() if ok.any() else np.zeros(3)


def human_to_robot(P: np.ndarray, scale: float, hips: np.ndarray, robot_start: np.ndarray) -> np.ndarray:
    """Points of the human motion's world in the robot's world (scale about the skeleton's start on the
    floor, then that point on the robot's start)."""
    return scale * (P - np.array([hips[0], hips[1], 0.0])) + np.array([robot_start[0], robot_start[1], 0.0])


def hand_points(h: SkeletonMotion) -> list[np.ndarray]:
    """Left and right (T, 1 + K, 3): the palm point of the skeleton (see the module notes), then the hand joint's
    K child joints (finger bases)."""
    from .retarget import _resolve_bvh_bodies

    idx = _resolve_bvh_bodies(h.joint_names, h.parents)
    out = []
    for side in ("Left", "Right"):
        j = idx[f"{side}Hand"]
        kids = [k for k, p in enumerate(h.parents) if p == j]
        P = h.positions[:, j]
        if kids:
            P = P + 0.5 * (np.nanmean(h.positions[:, kids], axis=1) - P)
        out.append(np.concatenate([P[:, None], h.positions[:, kids]], axis=1))
    return out


def palm_points(h: SkeletonMotion) -> np.ndarray:
    """(T, 2, 3) left and right palm points of the skeleton (see the module notes)."""
    return np.stack([P[:, 0] for P in hand_points(h)], axis=1)


def robot_hands(r: RobotMotion, fk) -> np.ndarray:
    """(T, 2, 3) the robot's palm points (see the module notes) through FK (an analysis.FootKinematics: its
    MuJoCo model and robot)."""
    from .robot_profile import SIDES

    mj, model, data = fk.mj, fk.model, fk.data
    parts = fk.profile.parts
    bodies = [parts.arms[s].tip_body for s in SIDES]
    fingers = [sorted({f.root_body for f in (parts.fingers or {}).get(s, [])}) for s in SIDES]
    col = {n: i for i, n in enumerate(r.joint_names)}
    idx = [col.get(n) for n in fk.joint_names]
    q = model.qpos0.copy()
    out = np.zeros((r.num_frames, 2, 3))
    for t in range(r.num_frames):
        q[:3], q[3:7] = r.root_pos[t], r.root_quat[t]
        q[7:] = [r.dof_pos[t, i] if i is not None else 0.0 for i in idx]
        data.qpos[:] = q
        mj.mj_kinematics(model, data)
        for s in range(2):
            p = data.xpos[bodies[s]]
            out[t, s] = p + 0.5 * (data.xpos[fingers[s]].mean(axis=0) - p) if fingers[s] else p
    return out


def surface_points(o: ObjectTrack) -> np.ndarray:
    """Points on the object's surface in its own frame: MAX_POINTS spread by area (a table top has
    vertices at its corners only) plus up to as many vertices; its origin when it has no mesh."""
    v = o.vertices
    if not len(v):
        return np.zeros((1, 3))
    if len(v) > MAX_POINTS:
        v = v[np.linspace(0, len(v) - 1, MAX_POINTS).astype(int)]
    if len(o.faces):
        import trimesh

        mesh = trimesh.Trimesh(o.vertices, o.faces, process=False)
        if mesh.area > 0:
            v = np.concatenate([v, trimesh.sample.sample_surface(mesh, MAX_POINTS, seed=0)[0]])
    return v


def describe(o: ObjectTrack) -> dict:
    """An object for the API / CLI: name, kind, whether it moves, its vertex count; for a prop from a file of its
    own (retlens.props) that file, the prop it belongs to, its parent segment and where its shape came from."""
    out = {"name": o.name, "kind": o.kind, "moves": o.moves, "vertices": int(len(o.vertices))}
    if o.source:
        out.update(file=o.source, group=o.group or None, parent=o.parent if o.parent >= 0 else None,
                   shape=o.shape or None)
    return out


def hand_object_metrics(h: SkeletonMotion, r: RobotMotion, fk) -> dict:
    """The contact numbers of the module notes, and "_objects": per object its name, kind, whether it
    moves, the seconds a human hand touches it and the robot hand's mean distance meanwhile."""
    if not h.objects:
        return {}
    from scipy.spatial import cKDTree

    scale, hips, start = human_scale(h, r), anchor(h), r.root_pos[0]
    T = r.num_frames
    hf = np.clip(np.round(np.arange(T) / r.fps * h.fps).astype(int), 0, h.num_frames - 1)  # human frame per robot frame
    hp = [P[hf] for P in hand_points(h)]  # per side (T, 1 + K, 3): palm point, finger bases
    rp = robot_hands(r, fk)
    dh = np.full((T, 2, len(h.objects)), np.inf)  # human hand (nearest of its points) -> object surface
    slack = np.zeros((T, 2, len(h.objects)))  # human palm point minus that nearest point, mapped to the robot's size
    dr = np.full((T, 2, len(h.objects)), np.inf)  # robot hand -> the same object, mapped to the robot's world
    for k, o in enumerate(h.objects):
        v = surface_points(o)
        v = v[np.isfinite(v).all(axis=1)]  # a broken (NaN) vertex is no surface point (cKDTree refuses it)
        if not len(v):
            continue  # no surface known: never touched
        tree = cKDTree(v)  # the surface in the object's frame: hands are moved into it per frame
        f = np.minimum(hf, len(o.positions) - 1)
        R, at = o.rotations[f], o.positions[f]
        for s in range(2):
            local = _object_frame(hp[s], R, at)
            d = _surface_distance(tree, local)  # (T, 1 + K); a point not seen (NaN) does not count
            dh[:, s, k] = d.min(axis=1)
            # the hand mapped like the object (human_to_robot): relative to it scaled, the object at its real size
            dm = _surface_distance(tree, scale * local)
            with np.errstate(invalid="ignore"):  # no point seen: inf - inf, no allowance (below)
                slack[:, s, k] = dm[:, 0] - dm.min(axis=1)
            robot = _object_frame(rp[:, s, None], R, human_to_robot(at, scale, hips, start))
            dr[:, s, k] = _surface_distance(tree, robot)[:, 0]
    slack[~np.isfinite(slack)] = 0.0  # palm point not seen: no allowance
    near = dh.min(axis=2)  # (T, 2)
    which = dh.argmin(axis=2)
    touch = near < CONTACT_M
    robot_d = np.take_along_axis(dr, which[..., None], axis=2)[..., 0]
    reach = robot_d < CONTACT_M + np.take_along_axis(slack, which[..., None], axis=2)[..., 0]
    per = []
    for k, o in enumerate(h.objects):
        on = touch & (which == k)
        per.append({**describe(o), "contact_s": round(float(on.any(axis=1).sum() / r.fps), 2),
                    "robot_distance_cm": round(100 * float(robot_d[on].mean()), 1) if on.any() else None})
    out = {"hand_obj_contact_s": round(float(touch.any(axis=1).sum() / r.fps), 2), "_objects": per}
    if touch.any():
        out["hand_obj_reach_pct"] = round(100 * float(reach[touch].mean()), 1)
        out["hand_obj_err_cm"] = round(100 * float(robot_d[touch].mean()), 1)
    return out


def _object_frame(X: np.ndarray, R: np.ndarray, at: np.ndarray) -> np.ndarray:
    """Points X (T, P, 3) in the frame of an object with rotations R (T, 3, 3) and origin `at` (T, 3)."""
    return np.einsum("tji,tpj->tpi", R, X - at[:, None])


def _surface_distance(tree, X: np.ndarray) -> np.ndarray:
    """(T, P) distances of points X (T, P, 3), in an object's frame, to its surface points (a cKDTree of them); inf
    where a point or the object's pose is not known (NaN)."""
    ok = np.isfinite(X).all(axis=2)
    d = np.full(ok.shape, np.inf)
    if ok.any():
        d[ok] = tree.query(X[ok])[0]
    return d
