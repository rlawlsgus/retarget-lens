"""What RetLens needs to know about a humanoid robot, worked out from its MuJoCo model.

Retargeting, the foot and self-collision fixes, the quality score and the drawing used to take
the robot's parts from tables written by hand for the Unitree G1 (link names, which joint bends
the elbow, where the joint centres are). A robot is now any MJCF (or URDF, converted to MJCF
with MuJoCo) with a floating base; :func:`load` reads it and :func:`derive` finds its parts:

- the root (the body with the free joint), the two legs (the chains down to the bodies with
  the lowest collision geometry, one per side), the two arms (the other chains that leave the
  trunk sideways), the chest (where the arms meet) and the waist joints below it;
- in each limb the bend joint (knee / elbow: the hinge across the limb half way along it), the
  joints before it (hip / shoulder) and after it (ankle / wrist), and which of them twist the
  limb about itself;
- joint centres as points, where the joint axes meet (body origins can sit centimetres off
  them), and which way the knee and elbow flex (the sign that brings the foot back / the hand
  forward), so a symmetric joint range needs no guessing;
- the feet (sole geometry, its up direction) and the hands (the last moving body of the arm).

Robot frame: MuJoCo's z up; the robot faces +x with its left at +y at the zero pose (checked:
the knees must bend the feet backwards). The parts become GMR's task table (the LAFAN1 task list and
weights of GMR's G1 config, with this robot's bodies), the T-pose chains and the centres the
derived IK config uses (retlens.retarget), and the leg / hand / foot bodies of the fixes and
metrics.

A robot is named by a registry key (``unitree_g1``: the model RetLens ships) or by the path of
its model file; nothing about a user's robot is stored in the program. Its identity in caches,
motion files and sessions is :attr:`RobotProfile.ident`: the model's name and a digest of the
model file.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field

import numpy as np

BUILTIN = "unitree_g1"  # the robot RetLens ships, and the default

# Human bodies of GMR's LAFAN1 task list, and its weights (pos, rot) in the two IK stages,
# from GMR's bvh_lafan1_to_g1.json: stage 1 matches orientations (feet also by position),
# stage 2 positions. The robot side is filled from the robot's parts.
TASK_WEIGHTS = {
    "Hips": ((0, 10), (100, 5)),
    "UpLeg": ((0, 10), (10, 5)),
    "Leg": ((0, 10), (10, 5)),
    "FootMod": ((50, 10), (50, 10)),
    "Spine2": ((0, 100), (0, 10)),
    "Arm": ((0, 100), (5, 100)),
    "ForeArm": ((0, 10), (10, 5)),
    "Hand": ((0, 10), (10, 5)),
}
# A waist that cannot pitch cannot follow the chest's pitch except by tipping the pelvis: the
# chest's orientation weight drops to this in stage 1 (the pelvis keeps the human's).
SPINE_ROT_NO_PITCH = 10

SIDES = ("left", "right")
HUMAN_SIDE = {"left": "Left", "right": "Right"}

TWIST_COS = 0.8  # |cos(axis, limb)| above this: the joint turns the limb about itself
MAX_WRIST = 3  # joints after the elbow that are the wrist (more: a finger chain, left out)
MIDLINE = 0.02  # m: a body this close to the robot's middle plane is on the midline
LATERAL = 0.03  # m: a limb starts this far to the side


class RobotError(ValueError):
    """The model cannot be used as a humanoid robot here (with the reason)."""


# --------------------------------------------------------------------------- parts
@dataclass
class Point:
    """A point fixed in a body: world position = xpos[body] + xmat[body] @ local."""

    body: int
    local: np.ndarray

    def world(self, data) -> np.ndarray:
        return data.xpos[self.body] + data.xmat[self.body].reshape(3, 3) @ self.local


@dataclass
class Limb:
    """One leg or arm: hinge joints proximal -> distal, split at the bend joint."""

    side: str  # "left" / "right"
    kind: str  # "leg" / "arm"
    root_body: int  # first body of the limb (its parent is on the trunk)
    end_body: int  # foot body / last moving body of the arm
    proximal: list  # hip / shoulder joints (ids), proximal -> distal
    bend: int  # knee / elbow joint id
    distal: list  # ankle / wrist joints
    twist: dict  # joint id -> True when it turns the limb about itself
    flex_sign: float  # +1 / -1: the sign of the bend joint that flexes the limb
    straight: float  # bend joint angle with the limb straightest
    centres: dict  # "proximal" / "bend" / "distal" -> Point
    abduction: int | None  # the proximal joint whose axis is most along the robot's forward axis
    twist_joint: int | None  # the proximal joint that turns the upper segment about itself
    upper_body: int  # body of the last proximal joint (thigh / upper arm)
    lower_body: int  # body of the bend joint (shank / forearm)
    tip_body: int  # the limb's last body, fixed ones included (hand / foot sole holder)
    distal_roll: int | None = None  # the distal joint whose axis is most along the robot's forward axis (ankle roll)

    @property
    def joints(self) -> list:
        return [*self.proximal, self.bend, *self.distal]


@dataclass
class Parts:
    root: int  # body with the free joint
    chest: int  # body the arms hang from (== root when the robot has no waist)
    waist: list  # hinge joints between root and chest
    waist_pitch: bool  # one of them pitches the trunk (axis along the robot's left)
    legs: dict  # side -> Limb
    arms: dict  # side -> Limb
    foot_up: dict  # side -> (3,) the sole's up direction in the foot body's frame
    sole_geoms: dict  # side -> [geom ids] the colliding geoms that touch the floor at the zero pose
    sole_points: dict  # side -> [(geom, point in its frame, radius)] standing for them (sole_world)
    sole_local: dict  # side -> (P, 3) those points (centres) in the foot body's frame at the zero pose
    ankle_height: float  # m: ankle centre above the sole at the zero pose
    standing_height: float  # m: root body origin above the soles at the zero pose
    top_height: float  # m: highest geometry above the soles at the zero pose
    leg_length: float  # m: hip centre -> ankle centre, straight leg
    region: dict = field(default_factory=dict)  # body -> (side, "leg" / "arm", "upper" / "lower"); trunk bodies absent
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- geometry
def _lines_point(anchors, axes) -> np.ndarray:
    """The point closest to every line (anchor, unit axis), least squares. For parallel
    lines the one nearest the anchors' mean."""
    A, b = np.zeros((3, 3)), np.zeros(3)
    for a, u in zip(anchors, axes):
        u = np.asarray(u, float) / max(np.linalg.norm(u), 1e-12)
        P = np.eye(3) - np.outer(u, u)
        A += P
        b += P @ np.asarray(a, float)
    m = np.mean(anchors, axis=0)
    # regularise towards the anchors' mean along directions no line constrains
    A += 1e-6 * np.eye(3)
    b += 1e-6 * m
    return np.linalg.solve(A, b)


def _closest_on_line(anchor, axis, p0, p1) -> np.ndarray:
    """Point of the line (anchor, axis) nearest the line p0 -> p1."""
    u = np.asarray(axis, float) / max(np.linalg.norm(axis), 1e-12)
    d = np.asarray(p1, float) - np.asarray(p0, float)
    n = np.linalg.norm(d)
    if n < 1e-9:
        return np.asarray(anchor, float) + u * float(np.dot(np.asarray(p0) - anchor, u))
    d = d / n
    w = np.asarray(anchor, float) - np.asarray(p0, float)
    a, b, c = 1.0, float(u @ d), 1.0
    dd, e = float(u @ w), float(d @ w)
    den = a * c - b * b
    if abs(den) < 1e-9:  # parallel: any point; take the anchor's foot on the limb line
        return np.asarray(anchor, float)
    s = (b * e - c * dd) / den
    return np.asarray(anchor, float) + s * u


def _local(data, body: int, world: np.ndarray) -> Point:
    R = data.xmat[body].reshape(3, 3)
    return Point(body, R.T @ (np.asarray(world, float) - data.xpos[body]))


# --------------------------------------------------------------------------- model loading
def _mj():
    import mujoco as mj

    return mj


def _is_urdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".urdf"


def _urdf_spec(path: str):
    """A URDF parsed by MuJoCo with its visual meshes and fixed links kept: MuJoCo's URDF
    defaults drop both while parsing, so the compiler settings go into the file's text (after
    any <mujoco> block of its own, so they win); meshes resolve from the file's folder unless
    the file names its own mesh folder."""
    mj = _mj()
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    folder = os.path.dirname(os.path.abspath(path))
    own = re.search(r"<compiler\b[^>]*\bmeshdir\s*=\s*\"([^\"]*)\"", re.sub(r"(?s)<!--.*?-->", "", text))
    if own:  # the file says where its meshes are (relative to the file: read from text, made absolute)
        d = own.group(1) if os.path.isabs(own.group(1)) else os.path.join(folder, own.group(1))
        tag = (f'<mujoco><compiler discardvisual="false" fusestatic="false" '
               f'meshdir="{d.replace(os.sep, "/").rstrip("/")}/"/></mujoco>')
    else:  # mesh file names relative to the file's folder ("../meshes/x.STL")
        tag = (f'<mujoco><compiler discardvisual="false" fusestatic="false" strippath="false" '
               f'meshdir="{folder.replace(os.sep, "/").rstrip("/")}/"/></mujoco>')
    end = text.rfind("</robot>")
    if end < 0:
        raise RobotError(f"{path}: not a URDF (no <robot> element)")
    return mj.MjSpec.from_string(text[:end] + tag + text[end:])


def kinematic_spec(path: str):
    """MjSpec of the robot for kinematics: equality constraints off (a weld holding the
    torso to the world, as some vendor models ship, would hang the robot in physics), every
    body and joint named (tables are keyed by name), and for a URDF a free joint on its base,
    visual meshes kept and fixed links kept as bodies."""
    mj = _mj()
    if _is_urdf(path):
        spec = _urdf_spec(path)
        base = spec.worldbody.first_body()
        if base is None:
            raise RobotError(f"{path}: no links")
        if not any(j.type == mj.mjtJoint.mjJNT_FREE for j in base.joints):
            base.add_freejoint()
    else:
        spec = mj.MjSpec.from_file(path)
    for eq in spec.equalities:
        eq.active = False
    for kind, prefix in ((mj.mjtObj.mjOBJ_BODY, "_body"), (mj.mjtObj.mjOBJ_JOINT, "_joint")):
        for i, e in enumerate(spec.worldbody.find_all(kind)):
            if not e.name:
                e.name = f"{prefix}{i}"
    # a body with neither geometry nor inertial (a joint holder, a dummy link) would stop MuJoCo
    # from compiling; kinematics does not care, the CoM hardly
    if not spec.compiler.boundmass:
        spec.compiler.boundmass = 1e-5
    if not spec.compiler.boundinertia:
        spec.compiler.boundinertia = 1e-9
    return spec


def model_digest(path: str) -> str:
    """sha1 (12 hex) of the model as MuJoCo reads it (files it includes too): a changed model
    is a different robot to the caches. Without MuJoCo, of the file's bytes."""
    h = hashlib.sha1()
    try:
        h.update(kinematic_spec(path).to_xml().encode("utf-8"))
    except ImportError:
        with open(path, "rb") as f:
            h.update(f.read())
    except Exception as e:  # MuJoCo cannot read it: the file's bytes still name it
        with open(path, "rb") as f:
            h.update(f.read())
        h.update(f"unreadable: {type(e).__name__}".encode())
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------- derivation
def _zero_data(model):
    """MjData at the zero pose with the root at the origin, upright."""
    mj = _mj()
    data = mj.MjData(model)
    q = model.qpos0.copy()
    for j in range(model.njnt):
        if model.jnt_type[j] == mj.mjtJoint.mjJNT_FREE:
            a = model.jnt_qposadr[j]
            q[a:a + 3] = 0.0
            q[a + 3:a + 7] = (1.0, 0.0, 0.0, 0.0)
    data.qpos[:] = q
    mj.mj_kinematics(model, data)
    return data


def _collides(model, g: int) -> bool:
    return bool(model.geom_contype[g] or model.geom_conaffinity[g])


def _geom_low(model, data, g: int) -> float:
    """Lowest world z of a geom (its bounding box corners)."""
    c, h = model.geom_aabb[g, :3], model.geom_aabb[g, 3:]
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * h + c
    return float((corners @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g])[:, 2].min())


def _geom_high(model, data, g: int) -> float:
    c, h = model.geom_aabb[g, :3], model.geom_aabb[g, 3:]
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * h + c
    return float((corners @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g])[:, 2].max())


FOOT_BAND = 0.005  # m: bodies whose colliding geometry is this close to the lowest at the zero pose stand on it
SOLE_BAND = 0.015  # m: the foot's colliding geometry this close to the lowest is sole


def _sole_points(model, data, geoms, floor: float) -> list:
    """Points that stand for the soles: (geom, point in the geom's frame, radius) whose bottom
    (point - radius, world z) is near the floor at the zero pose. A sphere is its centre; a
    capsule its two end centres; a box or cylinder its bottom corners / rim; a mesh the lowest
    of its vertices towards eight directions (the outline of where it stands)."""
    mj = _mj()
    out = []
    for g in geoms:
        t, s = model.geom_type[g], model.geom_size[g]
        R, c = data.geom_xmat[g].reshape(3, 3), data.geom_xpos[g]
        if t == mj.mjtGeom.mjGEOM_SPHERE:
            cand = [(np.zeros(3), float(s[0]))]
        elif t == mj.mjtGeom.mjGEOM_CAPSULE:
            cand = [(np.array([0.0, 0.0, z]), float(s[0])) for z in (-s[1], s[1])]
        elif t == mj.mjtGeom.mjGEOM_BOX:
            cand = [(np.array([x, y, z]) * s[:3], 0.0) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        elif t == mj.mjtGeom.mjGEOM_CYLINDER:
            cand = [(np.array([s[0] * np.cos(a), s[0] * np.sin(a), z]), 0.0)
                    for a in np.linspace(0, 2 * np.pi, 8, endpoint=False) for z in (-s[1], s[1])]
        elif t == mj.mjtGeom.mjGEOM_MESH:
            m = model.geom_dataid[g]
            v = model.mesh_vert[model.mesh_vertadr[m]:model.mesh_vertadr[m] + model.mesh_vertnum[m]].astype(float)
            w = v @ R.T + c
            near = w[:, 2] < w[:, 2].min() + SOLE_BAND
            vs, ws = v[near], w[near]
            pick = {int(np.argmax(ws[:, :2] @ [np.cos(a), np.sin(a)])) for a in np.linspace(0, 2 * np.pi, 8, endpoint=False)}
            cand = [(vs[i], 0.0) for i in sorted(pick)]
        else:  # ellipsoid and the rest: the bounding box's corners
            h = model.geom_aabb[g, 3:]
            cand = [(model.geom_aabb[g, :3] + np.array([x, y, z]) * h, 0.0) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        out += [(g, p, r) for p, r in cand if (R @ p + c)[2] - r < floor + SOLE_BAND]
    return out


def sole_world(data, points) -> np.ndarray:
    """(N, 3) the bottoms of sole points (robot_profile._sole_points) at the posed data."""
    if not points:
        return np.zeros((0, 3))
    return np.array([data.geom_xpos[g] + data.geom_xmat[g].reshape(3, 3) @ p - (0.0, 0.0, r) for g, p, r in points])


def derive(model) -> Parts:
    """The robot's parts from its kinematic model (see the module docstring). Raises
    RobotError naming what could not be found."""
    mj = _mj()
    data = _zero_data(model)
    nb = model.nbody
    parent = model.body_parentid
    children = {b: [] for b in range(nb)}
    for b in range(1, nb):
        children[parent[b]].append(b)
    free = [j for j in range(model.njnt) if model.jnt_type[j] == mj.mjtJoint.mjJNT_FREE]
    if len(free) != 1:
        raise RobotError(f"the robot needs exactly one floating base (free joint); the model has {len(free)}")
    root = int(model.jnt_bodyid[free[0]])
    if model.jnt_qposadr[free[0]] != 0:
        raise RobotError("the free joint must come first in the model (qpos 0..6)")
    bad = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_JOINT, j) for j in range(model.njnt)
           if j != free[0] and model.jnt_type[j] != mj.mjtJoint.mjJNT_HINGE]
    if bad:
        raise RobotError(f"only hinge joints are supported besides the base; found {', '.join(bad[:5])}")
    body_joints = {b: [] for b in range(nb)}
    for j in range(model.njnt):
        if j != free[0]:
            body_joints[int(model.jnt_bodyid[j])].append(j)

    def path_to(b):  # bodies root -> b (b included, root excluded)
        out = []
        while b != root and b > 0:
            out.append(b)
            b = parent[b]
        if b != root:
            raise RobotError("a limb is not attached to the floating base")
        return out[::-1]

    def subtree(b):
        out, stack = [], [b]
        while stack:
            x = stack.pop()
            out.append(x)
            stack.extend(children[x])
        return out

    def hinges(bodies):
        return [j for b in bodies for j in sorted(body_joints[b])]

    # feet: the colliding geometry lowest at the zero pose, one body per side
    low = {}
    for g in range(model.ngeom):
        b = int(model.geom_bodyid[g])
        if b == 0 or not _collides(model, g):
            continue
        low.setdefault(b, []).append((_geom_low(model, data, g), g))
    if not low:
        raise RobotError("the model has no collision geometry: the feet cannot be found")
    floor = min(z for gs in low.values() for z, _ in gs)
    feet, sole_geoms = {}, {}
    for side, sgn in (("left", 1.0), ("right", -1.0)):
        lows = [b for b, gs in low.items() if sgn * data.xpos[b][1] > LATERAL and min(z for z, _ in gs) < floor + FOOT_BAND]
        if not lows:
            raise RobotError(f"no {side} foot: nothing collides near the floor on the {side} (+y is left)")
        # the foot holds every sole on its side: the deepest body above them all (a jointed toe
        # and the heel share the foot), up to the nearest body with a joint
        common = path_to(lows[0])
        for b in lows[1:]:
            p = path_to(b)
            k = 0
            while k < min(len(common), len(p)) and common[k] == p[k]:
                k += 1
            common = common[:k]
        if not common:
            raise RobotError(f"the {side} soles are not on one leg")
        b = common[-1]
        while parent[b] != root and not body_joints[b] and parent[b] > 0:
            b = parent[b]
        feet[side] = b
        sole_geoms[side] = [g for x in subtree(b) for z, g in low.get(x, []) if z < floor + SOLE_BAND]
    sole_points = {s: _sole_points(model, data, sole_geoms[s], floor) for s in feet}
    R_f = {s: data.xmat[feet[s]].reshape(3, 3) for s in feet}
    sole_local = {s: np.array([R_f[s].T @ (data.geom_xpos[g] + data.geom_xmat[g].reshape(3, 3) @ p - data.xpos[feet[s]])
                               for g, p, _ in sole_points[s]]).reshape(-1, 3) for s in feet}

    # limbs: bodies that leave the midline sideways with at least two hinges below them
    def lateral(b):
        return abs(data.xpos[b][1]) > LATERAL and abs(data.xpos[parent[b]][1]) < MIDLINE + 1e-9 + 0.5 * abs(data.xpos[b][1])

    leg_roots = {}
    for side, f in feet.items():
        p = path_to(f)
        start = next((b for b in p if lateral(b)), p[0])
        leg_roots[side] = start
    leg_bodies = set(x for s in leg_roots.values() for x in subtree(s))
    cand = []
    for b in range(1, nb):
        if b in leg_bodies or b == root or not lateral(b):
            continue
        if parent[b] in leg_bodies:
            continue
        tree = subtree(b)
        n = len(hinges(tree))
        if n >= 3:
            cand.append((b, n, float(data.xpos[b][2])))
    arm_roots = {}
    for side, sgn in (("left", 1.0), ("right", -1.0)):
        cs = [c for c in cand if sgn * data.xpos[c[0]][1] > 0]
        # the arm: most joints, then highest; nested candidates (a hand inside the arm) lose
        cs = [c for c in cs if not any(o[0] != c[0] and c[0] in subtree(o[0]) for o in cs)]
        if not cs:
            raise RobotError(f"no {side} arm: no chain of 3+ joints leaves the trunk on the {side}")
        arm_roots[side] = max(cs, key=lambda c: (c[1], c[2]))[0]

    # chest: the deepest common ancestor of the two arms
    pl, pr = path_to(arm_roots["left"]), path_to(arm_roots["right"])
    common = [a for a, b in zip(pl, pr) if a == b]
    chest = common[-1] if common else root
    waist = hinges(path_to(chest)) if chest != root else []

    notes = []
    legs, arms = {}, {}
    for side in SIDES:
        legs[side] = _limb(model, data, side, "leg", leg_roots[side], feet[side], path_to, children, body_joints, notes)
        arms[side] = _limb(model, data, side, "arm", arm_roots[side], None, path_to, children, body_joints, notes)

    # the robot must face +x with its left at +y (MuJoCo / URDF convention); check it on the legs
    hip_y = {s: legs[s].centres["proximal"].world(data)[1] for s in SIDES}
    if not hip_y["left"] > hip_y["right"]:
        raise RobotError("the left leg is not at +y: the model's base frame does not face +x")

    def axis_world(j):
        return data.xaxis[j]

    waist_pitch = any(abs(axis_world(j)[1]) > TWIST_COS for j in waist)
    foot_up = {s: data.xmat[feet[s]].reshape(3, 3).T @ np.array([0.0, 0.0, 1.0]) for s in SIDES}
    ankle_h = float(np.mean([legs[s].centres["distal"].world(data)[2] for s in SIDES]) - floor)
    tops = [_geom_high(model, data, g) for g in range(model.ngeom) if model.geom_bodyid[g] != 0]
    top = (max(tops) if tops else float(data.xpos[chest][2])) - floor
    leg_len = float(np.mean([np.linalg.norm(legs[s].centres["proximal"].world(data)
                                            - legs[s].centres["distal"].world(data)) for s in SIDES]))
    if not waist:
        notes.append("no waist joints: the chest is the root body")
    elif not waist_pitch:
        notes.append("the waist cannot pitch: the chest follows the human chest only in yaw / roll")
    region = {}
    for limbs in (legs, arms):
        for side, limb in limbs.items():
            for b in subtree(limb.root_body):
                x, lower = b, False
                while x != limb.root_body and x > 0:
                    if x == limb.lower_body:
                        lower = True
                        break
                    x = parent[x]
                region[b] = (side, limb.kind, "lower" if lower or b == limb.lower_body else "upper")
    return Parts(root=root, chest=chest, waist=waist, waist_pitch=waist_pitch, legs=legs, arms=arms,
                 foot_up=foot_up, sole_geoms=sole_geoms, sole_points=sole_points, sole_local=sole_local,
                 ankle_height=ankle_h,
                 standing_height=float(data.xpos[root][2] - floor), top_height=float(top),
                 leg_length=leg_len, region=region, notes=notes)


def _limb(model, data, side, kind, start, end, path_to, children, body_joints, notes) -> Limb:
    """One limb from its first body; `end` the foot body (legs) or None (arms: followed down
    the longest chain to the last moving body, stopping where fingers branch)."""
    mj = _mj()
    name = f"{side} {kind}"

    def hinge_count(b):
        n, stack = 0, [b]
        while stack:
            x = stack.pop()
            n += len(body_joints[x])
            stack.extend(children[x])
        return n

    if end is None:  # arm: down the chain that moves, until it branches into fingers
        b = start
        while True:
            moving = [c for c in children[b] if hinge_count(c) > 0]
            if len(moving) >= 2:  # a palm with fingers: the hand ends here
                tip = b
                break
            if not moving:  # the last moving body; a hand / palm body may be fixed below it
                tip = b
                fixed = [c for c in children[b] if not body_joints[c]]
                while fixed:
                    tip = max(fixed, key=lambda c: len(children[c]) + float(np.linalg.norm(data.xpos[c] - data.xpos[tip])))
                    fixed = [c for c in children[tip] if not body_joints[c]]
                break
            b = moving[0]
        chain = path_to(b)
    else:
        chain = path_to(end)
        tip = end
    i0 = chain.index(start) if start in chain else 0
    chain = chain[i0:]
    joints = [j for b in chain for j in sorted(body_joints[b])]
    if len(joints) < 3:
        raise RobotError(f"the {name} has {len(joints)} joints; at least 3 (e.g. hip, knee, ankle) are needed")
    end_body = int(model.jnt_bodyid[joints[-1]])

    def anchors(js):
        return [data.xanchor[j].copy() for j in js], [data.xaxis[j].copy() for j in js]

    def end_point(body):
        """The limb's far end as a point of its last body: the body's origin, or, when that sits
        on the last joint (an arm ending at its elbow), the farthest point of its geometry."""
        p = data.xpos[body].copy()
        if np.linalg.norm(p - data.xanchor[joints[-1]]) < 0.03:
            pts, fixed = [p], [body]
            for x in fixed:
                fixed.extend(c for c in children[x] if not body_joints[c])
            for g in range(model.ngeom):
                if int(model.geom_bodyid[g]) in fixed:
                    R, c = data.geom_xmat[g].reshape(3, 3), data.geom_xpos[g]
                    if model.geom_type[g] in (mj.mjtGeom.mjGEOM_CAPSULE, mj.mjtGeom.mjGEOM_CYLINDER):
                        pts += [c + R @ (0.0, 0.0, z) for z in (-model.geom_size[g][1], model.geom_size[g][1])]
                    else:
                        pts.append(c.copy())
            p = max(pts, key=lambda x: float(np.linalg.norm(x - data.xanchor[joints[0]])))
        return _local(data, body, p)

    # the bend joint: across the limb, about half way along it (an arm may end at its elbow)
    end_pt = end_point(tip if kind == "arm" else end)
    S = data.xanchor[joints[0]].copy()
    E = end_pt.world(data)
    d = E - S
    L = float(np.linalg.norm(d))
    if L < 1e-3:
        raise RobotError(f"the {name} has no length at the zero pose")
    best = None
    for k, j in enumerate(joints[1:] if kind == "arm" else joints[1:-1], start=1):
        a, u = data.xanchor[j], data.xaxis[j]
        if abs(float(u @ d)) / L > 0.5:  # along the limb
            continue
        t = float((a - S) @ d) / (L * L)
        if 0.2 <= t <= 0.85:
            score = abs(t - 0.5)
            if best is None or score < best[0]:
                best = (score, k)
    if best is None:
        raise RobotError(f"the {name} has no joint that bends it half way along (knee / elbow)")
    kb = best[1]
    bend = joints[kb]
    proximal, distal = joints[:kb], joints[kb + 1:]
    if not proximal:
        raise RobotError(f"the {name} has no joint above its {'knee' if kind == 'leg' else 'elbow'}")
    if kind == "arm" and len(distal) > MAX_WRIST:  # a finger chain past the wrist: the hand ends at the wrist
        notes.append(f"{name}: {len(distal) - MAX_WRIST} joint(s) past the wrist (a finger?) left out of the arm")
        distal = distal[:MAX_WRIST]
        joints = [*proximal, bend, *distal]
        end_body = tip = int(model.jnt_bodyid[distal[-1]])
        end_pt = end_point(tip)

    # straighten the limb with the bend joint, then tell twists from swings
    adr = model.jnt_qposadr[bend]
    lo, hi = model.jnt_range[bend] if model.jnt_limited[bend] else (-np.pi, np.pi)
    q0 = data.qpos.copy()
    best_d, straight = -1.0, float(q0[adr])
    for v in np.linspace(lo, hi, 181):
        data.qpos[adr] = v
        mj.mj_kinematics(model, data)
        dist = float(np.linalg.norm(end_pt.world(data) - data.xanchor[joints[0]]))
        if dist > best_d + 1e-9:
            best_d, straight = dist, float(v)
    data.qpos[adr] = straight
    mj.mj_kinematics(model, data)
    a_p, u_p = anchors(proximal)
    a_d, u_d = anchors(distal) if distal else ([], [])
    c_prox = _lines_point(a_p, u_p) if len(proximal) > 1 else a_p[0].copy()
    E = end_pt.world(data)
    if len(distal) >= 2:
        nt = [(a, u) for a, u in zip(a_d, u_d) if abs(float(u @ (E - c_prox))) / max(np.linalg.norm(E - c_prox), 1e-9) < TWIST_COS]
        if len(nt) >= 2:
            c_dist = _lines_point([a for a, _ in nt], [u for _, u in nt])
        elif nt:
            c_dist = _closest_on_line(nt[0][0], nt[0][1], c_prox, E)
        else:
            c_dist = a_d[-1].copy()
    elif distal:
        c_dist = _closest_on_line(a_d[0], u_d[0], c_prox, E)
    else:
        c_dist = E.copy()  # no wrist: the arm's far end
    limb_dir = c_dist - c_prox
    limb_dir /= max(np.linalg.norm(limb_dir), 1e-9)
    twist = {j: abs(float(data.xaxis[j] @ limb_dir)) > TWIST_COS for j in joints}
    twist[bend] = False
    c_bend = _closest_on_line(data.xanchor[bend], data.xaxis[bend], c_prox, c_dist)
    # proximal centre: where the hip / shoulder axes meet (twists included: they pass through it)
    if len(proximal) == 1:
        c_prox = _closest_on_line(a_p[0], u_p[0], c_prox, c_bend)

    # flex sign: knees flex bringing the ankle back (-x), elbows bringing the hand forward (+x)
    want = -1.0 if kind == "leg" else 1.0
    data.qpos[adr] = straight
    mj.mj_kinematics(model, data)
    p0 = c_dist.copy()
    pt = _local(data, int(model.jnt_bodyid[distal[0]]) if distal else end_body, p0)
    signs = []
    for s in (1.0, -1.0):
        v = np.clip(straight + s * 0.3, lo, hi)
        data.qpos[adr] = v
        mj.mj_kinematics(model, data)
        signs.append((float((pt.world(data) - p0)[0]) * want, s, abs(v - straight)))
    usable = [x for x in signs if x[2] > 1e-3]
    if not usable:
        raise RobotError(f"the {name}'s bend joint cannot move from straight")
    room = {s: (hi - straight if s > 0 else straight - lo) for s in (1.0, -1.0)}
    if max(abs(x[0]) for x in usable) < 0.01:  # neither way moves it forward / back (an elbow bending up / down)
        flex = 1.0 if room[1.0] >= room[-1.0] else -1.0
        notes.append(f"{name}: flex sense from the joint range ({flex:+.0f})")
    else:
        flex = max(usable)[1]
        if room[flex] < room[-flex] * 0.5:
            if kind == "leg" and room[flex] < 0.3 * room[-flex] and room[-flex] > 0.5:
                raise RobotError(f"the {side} knee bends the foot forwards: the model does not face +x "
                                 "(MuJoCo / URDF robots face x, with y to their left and z up)")
            notes.append(f"{name}: flexes towards the shorter side of its range ({flex:+.0f}); check the model")

    # back to the zero pose for the stored points
    data.qpos[:] = q0
    mj.mj_kinematics(model, data)
    # points fixed in bodies: the hip / shoulder centre in the trunk, the knee / elbow centre in
    # the shank / forearm, the ankle / wrist centre in the body after the first wrist / ankle joint
    data.qpos[adr] = straight
    mj.mj_kinematics(model, data)
    trunk = int(model.body_parentid[start])
    cen = {
        "proximal": _local(data, trunk, c_prox),
        "bend": _local(data, int(model.jnt_bodyid[bend]), c_bend),
        "distal": _local(data, int(model.jnt_bodyid[distal[0]]) if distal else end_body, c_dist),
    }
    data.qpos[:] = q0
    mj.mj_kinematics(model, data)

    swing = [j for j in proximal if not twist[j]]
    abduction = max(swing, key=lambda j: abs(float(data.xaxis[j][0])), default=None) if swing else None
    tw = [j for j in proximal if twist[j]]
    rolls = [j for j in distal if not twist[j]]
    roll = max(rolls, key=lambda j: abs(float(data.xaxis[j][0])), default=None)
    if roll is not None and abs(float(data.xaxis[roll][0])) < 0.7:
        roll = None
    return Limb(side=side, kind=kind, root_body=start, end_body=end_body if kind == "arm" else end,
                proximal=proximal, bend=bend, distal=distal, twist=twist, flex_sign=float(flex),
                straight=straight, centres=cen, abduction=abduction, twist_joint=tw[-1] if tw else None,
                upper_body=int(model.jnt_bodyid[proximal[-1]]), lower_body=int(model.jnt_bodyid[bend]),
                tip_body=int(tip), distal_roll=roll)


# --------------------------------------------------------------------------- the profile
@dataclass
class RobotProfile:
    """A robot RetLens can retarget to (see the module docstring)."""

    key: str  # registry key or the model's absolute path
    name: str  # display name
    tag: str  # short file-name tag: <clip>_<tag>.npz
    mjcf: str  # the model file (MJCF, or the user's URDF)
    urdf: str | None  # a URDF to draw, when there is one
    digest: str
    builtin: bool
    _model: object = None
    _parts: Parts | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def ident(self) -> dict:
        """What motion files, caches and sessions record about the robot."""
        return {"name": self.name, "digest": self.digest, "key": self.key if self.builtin else os.path.basename(self.mjcf)}

    def spec(self):
        return kinematic_spec(self.mjcf)

    def model(self):
        """The kinematic MjModel (equality constraints off). Shared: callers make their own MjData."""
        with self._lock:
            if self._model is None:
                self._model = self.spec().compile()
            return self._model

    def new_model(self):
        """A fresh MjModel, for callers that change it (collision flags, ...)."""
        return self.spec().compile()

    @property
    def parts(self) -> Parts:
        with self._lock:
            if self._parts is None:
                m = self._model if self._model is not None else None
            else:
                return self._parts
        model = m if m is not None else self.model()
        p = derive(model)
        with self._lock:
            self._parts = p
        return p

    # names, for the tables of the solver and the fixes
    def body(self, b: int) -> str:
        mj = _mj()
        return mj.mj_id2name(self.model(), mj.mjtObj.mjOBJ_BODY, b)

    def joint(self, j: int) -> str:
        mj = _mj()
        return mj.mj_id2name(self.model(), mj.mjtObj.mjOBJ_JOINT, j)

    def joint_names(self) -> list[str]:
        """Names of the hinge joints in qpos order (= RobotMotion.joint_names)."""
        mj = _mj()
        model = self.model()
        js = [j for j in range(model.njnt) if model.jnt_type[j] != mj.mjtJoint.mjJNT_FREE]
        js.sort(key=lambda j: model.jnt_qposadr[j])
        return [mj.mj_id2name(model, mj.mjtObj.mjOBJ_JOINT, j) for j in js]

    def limits(self, urdf: str | None = None) -> dict[str, tuple[float, float, float]]:
        """Joint limits name -> (lower, upper, max velocity) for QC: the model's ranges, with the
        URDF's (``urdf`` or the robot's own) where it has the joint (velocity limits are only in
        URDFs; MJCF has none, inf)."""
        mj = _mj()
        model = self.model()
        out = {}
        for n in self.joint_names():
            j = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, n)
            lo, hi = model.jnt_range[j] if model.jnt_limited[j] else (-np.inf, np.inf)
            out[n] = (float(lo), float(hi), float("inf"))
        path = urdf or self.urdf
        if path and os.path.isfile(path):
            from .io import urdf_joint_limits

            try:
                u = urdf_joint_limits(path)
            except Exception:  # a broken URDF: the model's ranges are enough
                u = {}
            out.update({k: v for k, v in u.items() if k in out})
        return out

    def task_bodies(self) -> dict[str, str]:
        """Human body (GMR LAFAN1 names) -> robot body of its IK task."""
        p = self.parts
        out = {"Hips": self.body(p.root)}
        if p.chest != p.root:
            out["Spine2"] = self.body(p.chest)
        for side in SIDES:
            S = HUMAN_SIDE[side]
            leg, arm = p.legs[side], p.arms[side]
            out[f"{S}UpLeg"] = self.body(leg.upper_body)
            out[f"{S}Leg"] = self.body(leg.lower_body)
            out[f"{S}FootMod"] = self.body(leg.end_body)
            out[f"{S}Arm"] = self.body(arm.upper_body)
            out[f"{S}ForeArm"] = self.body(arm.lower_body)
            hand = arm.end_body if arm.distal else arm.tip_body  # no wrist: a hand body fixed to the forearm
            if hand != arm.lower_body:  # else the forearm's own task places the hand
                out[f"{S}Hand"] = self.body(hand)
        return out

    def task_tables(self) -> tuple[dict, dict]:
        """GMR's ik_match_table1 / 2 with zero offsets (the derived config fills them):
        {robot body: [human body, pos weight, rot weight, [0, 0, 0], [1, 0, 0, 0]]}."""
        t1, t2 = {}, {}
        for human, robot in self.task_bodies().items():
            part = re.sub(r"^(Left|Right)", "", human)
            (p1, r1), (p2, r2) = TASK_WEIGHTS[part]
            if part == "Spine2" and not self.parts.waist_pitch:
                r1 = min(r1, SPINE_ROT_NO_PITCH)
            if robot in t1:
                raise RobotError(f"two human bodies map to the robot body {robot}")
            t1[robot] = [human, p1, r1, [0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]
            t2[robot] = [human, p2, r2, [0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]
        return t1, t2

    def feet(self) -> dict[str, str]:
        return {s: self.body(self.parts.legs[s].end_body) for s in SIDES}

    def hands(self) -> dict[str, str]:
        """side -> the arm's last body (a palm / hand body fixed below the wrist included)."""
        return {s: self.body(self.parts.arms[s].tip_body) for s in SIDES}

    def leg_joints(self, side: str) -> list[str]:
        """Hip ... ankle joint names of one leg, proximal -> distal."""
        return [self.joint(j) for j in self.parts.legs[side].joints]

    def describe(self) -> dict:
        """The parts by name, for logs and `retlens-cli robot`."""
        p = self.parts
        m = self.model()

        def limb(l: Limb):
            return {
                "proximal": [self.joint(j) + ("*" if l.twist[j] else "") for j in l.proximal],
                "bend": self.joint(l.bend), "flex_sign": int(l.flex_sign),
                "distal": [self.joint(j) + ("*" if l.twist[j] else "") for j in l.distal],
                "end": self.body(l.end_body), "tip": self.body(l.tip_body),
            }

        return {
            "name": self.name, "model": self.mjcf, "digest": self.digest, "dof": m.nq - 7,
            "root": self.body(p.root), "chest": self.body(p.chest),
            "waist": [self.joint(j) for j in p.waist], "waist_pitch": p.waist_pitch,
            "legs": {s: limb(p.legs[s]) for s in SIDES}, "arms": {s: limb(p.arms[s]) for s in SIDES},
            "standing_height_m": round(p.standing_height, 3), "height_m": round(p.top_height, 3),
            "leg_length_m": round(p.leg_length, 3), "ankle_height_m": round(p.ankle_height, 3),
            "tasks": self.task_bodies(), "notes": list(p.notes),
        }


# --------------------------------------------------------------------------- registry
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def _builtin(key: str) -> RobotProfile:
    from . import paths

    root = paths.robot_assets_dir()
    files = {
        "unitree_g1": ("g1_mocap_29dof.xml", "Unitree G1", "g1"),
        "unitree_g1_with_hands": ("g1_mocap_29dof_with_hands.xml", "Unitree G1 (hands)", "g1_hands"),
    }
    if key not in files:
        raise RobotError(f"unknown robot {key!r}: give the path of its MJCF or URDF, or one of {', '.join(files)}")
    xml, name, tag = files[key]
    path = os.path.join(root, "unitree_g1", xml)
    if not os.path.isfile(path):
        raise RobotError(f"no robot model for {key} ({path}; scripts\\install_gmr.ps1 puts it next to the repository)")
    urdf = paths.robot_urdf() if key == "unitree_g1" else None
    return RobotProfile(key=key, name=name, tag=tag, mjcf=path, urdf=urdf if urdf and os.path.isfile(urdf) else None,
                        digest=model_digest(path), builtin=True)


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s[:24] or "robot"


def _from_file(path: str) -> RobotProfile:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise RobotError(f"no robot model file {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".xml", ".mjcf", ".urdf"):
        raise RobotError(f"{path}: a robot is an MJCF (.xml) or a URDF (.urdf)")
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        head = open(path, encoding="utf-8", errors="replace").read(4096)
        m = re.search(r"<(?:mujoco|robot)\b[^>]*\b(?:model|name)\s*=\s*\"([^\"]+)\"", head)
        if m:
            name = m.group(1)
    except OSError:
        pass
    digest = model_digest(path)
    urdf = path if ext == ".urdf" else None
    return RobotProfile(key=path, name=name, tag=f"{_slug(name)}_{digest[:6]}", mjcf=path, urdf=urdf,
                        digest=digest, builtin=False)


def is_builtin(spec: str | None) -> bool:
    return not spec or spec in ("unitree_g1", "unitree_g1_with_hands")


def load(spec: str | None = None) -> RobotProfile:
    """The robot named by a registry key or a model path (None / '' = the built-in G1).
    Cached per key and file state; the parts are derived on first use."""
    spec = spec or BUILTIN
    if is_builtin(spec):
        k = (spec,)
        builder = lambda: _builtin(spec)  # noqa: E731
    else:
        p = os.path.abspath(spec)
        try:
            st = os.stat(p)
            k = (p, st.st_mtime_ns, st.st_size)
        except OSError:
            k = (p,)
        builder = lambda: _from_file(p)  # noqa: E731
    with _CACHE_LOCK:
        prof = _CACHE.get(k)
    if prof is None:
        prof = builder()
        with _CACHE_LOCK:
            prof = _CACHE.setdefault(k, prof)
    return prof


def same_robot(a: dict | None, b: dict | None) -> bool:
    """Do two recorded robot identities (RobotProfile.ident) name the same model? Unknown
    (None) matches anything: motions from before identities were recorded."""
    if not a or not b:
        return True
    return a.get("digest") == b.get("digest") or (a.get("name") == b.get("name") and not a.get("digest"))
