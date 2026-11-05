"""Objects captured with a human motion (FBX props and furniture, retlens.motion.ObjectTrack) next to its
retarget: where they sit in the robot's world, and how well the robot's hands meet them.

The robot motion is the human's scaled (GMR scales positions), so an object's path is mapped the same
way: scaled about the skeleton's start point on the floor and put on the robot's start (human_to_robot).
Its shape keeps its real size: a box does not shrink for a smaller robot. The mapping is fitted from
the pelvis paths (human_scale), so it is approximate where the retarget's root wanders off the human's.

Hand-object contact (hand_object_metrics): a hand touches an object when its palm point is within
CONTACT_M of the object's surface (points spread over its mesh; a bare node: its origin). For every frame and
hand where the human touches an object, the robot's same hand is measured against that same object:

    hand_obj_contact_s   seconds with a human hand on an object
    hand_obj_reach_pct   of those (frame, hand) pairs, the share where the robot hand is within CONTACT_M too
    hand_obj_err_cm      their mean robot hand - object distance (cm)

The palm point: the hand joint moved halfway to the mean of its child joints (finger bases) when it has
any, else the hand joint (a wrist). The robot's: the rubber hand body of the G1.
"""

from __future__ import annotations

import numpy as np

from .motion import ObjectTrack, RobotMotion, SkeletonMotion

CONTACT_M = 0.06  # palm point to surface: a hand on the object
MAX_POINTS = 1500  # surface points per object for the distances (a subset of a dense mesh's vertices)
CHUNK = 256  # frames per distance batch


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


def palm_points(h: SkeletonMotion) -> np.ndarray:
    """(T, 2, 3) left and right palm points of the skeleton (see the module notes)."""
    from .retarget import _resolve_bvh_bodies

    idx = _resolve_bvh_bodies(h.joint_names, h.parents)
    out = []
    for side in ("Left", "Right"):
        j = idx[f"{side}Hand"]
        kids = [k for k, p in enumerate(h.parents) if p == j]
        P = h.positions[:, j]
        if kids:
            P = P + 0.5 * (np.nanmean(h.positions[:, kids], axis=1) - P)
        out.append(P)
    return np.stack(out, axis=1)


def robot_hands(r: RobotMotion, fk) -> np.ndarray:
    """(T, 2, 3) the robot's hand bodies (the arms' last bodies, robot_profile) through FK (an
    analysis.FootKinematics: its MuJoCo model and robot)."""
    from .robot_profile import SIDES

    mj, model, data = fk.mj, fk.model, fk.data
    bodies = [fk.profile.parts.arms[s].tip_body for s in SIDES]
    col = {n: i for i, n in enumerate(r.joint_names)}
    idx = [col.get(n) for n in fk.joint_names]
    q = model.qpos0.copy()
    out = np.zeros((r.num_frames, 2, 3))
    for t in range(r.num_frames):
        q[:3], q[3:7] = r.root_pos[t], r.root_quat[t]
        q[7:] = [r.dof_pos[t, i] if i is not None else 0.0 for i in idx]
        data.qpos[:] = q
        mj.mj_kinematics(model, data)
        out[t] = data.xpos[bodies]
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


def hand_object_metrics(h: SkeletonMotion, r: RobotMotion, fk) -> dict:
    """The contact numbers of the module notes, and "_objects": per object its name, kind, whether it
    moves, the seconds a human hand touches it and the robot hand's mean distance meanwhile."""
    if not h.objects:
        return {}
    scale, hips, start = human_scale(h, r), anchor(h), r.root_pos[0]
    T = r.num_frames
    hf = np.clip(np.round(np.arange(T) / r.fps * h.fps).astype(int), 0, h.num_frames - 1)  # human frame per robot frame
    hp = palm_points(h)[hf]  # (T, 2, 3)
    rp = robot_hands(r, fk)
    pts = [surface_points(o) for o in h.objects]
    dh = np.full((T, 2, len(pts)), np.inf)  # human palm -> object surface
    dr = np.full((T, 2, len(pts)), np.inf)  # robot hand -> the same object, mapped to the robot's world
    for k, (o, v) in enumerate(zip(h.objects, pts)):
        for a in range(0, T, CHUNK):  # (frames, V, 3) at a time: long clips stay small in memory
            b = min(T, a + CHUNK)
            f = np.minimum(hf[a:b], len(o.positions) - 1)
            spin = np.einsum("vj,tij->tvi", v, o.rotations[f])  # the surface about the object's origin
            Vh = spin + o.positions[f][:, None]
            Vr = spin + human_to_robot(o.positions[f], scale, hips, start)[:, None]
            for s in range(2):
                dh[a:b, s, k] = np.linalg.norm(Vh - hp[a:b, s, None], axis=2).min(axis=1)
                dr[a:b, s, k] = np.linalg.norm(Vr - rp[a:b, s, None], axis=2).min(axis=1)
    near = np.nan_to_num(dh, nan=np.inf).min(axis=2)  # (T, 2)
    which = np.nan_to_num(dh, nan=np.inf).argmin(axis=2)
    touch = near < CONTACT_M
    robot_d = np.take_along_axis(dr, which[..., None], axis=2)[..., 0]
    per = []
    for k, o in enumerate(h.objects):
        on = touch & (which == k)
        per.append({"name": o.name, "kind": o.kind, "moves": o.moves, "vertices": int(len(o.vertices)),
                    "contact_s": round(float(on.any(axis=1).sum() / r.fps), 2),
                    "robot_distance_cm": round(100 * float(robot_d[on].mean()), 1) if on.any() else None})
    out = {"hand_obj_contact_s": round(float(touch.any(axis=1).sum() / r.fps), 2), "_objects": per}
    if touch.any():
        out["hand_obj_reach_pct"] = round(100 * float((robot_d[touch] < CONTACT_M).mean()), 1)
        out["hand_obj_err_cm"] = round(100 * float(robot_d[touch].mean()), 1)
    return out
