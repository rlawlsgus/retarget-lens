"""A robot drawn from its MuJoCo model, for RobotBatch (which otherwise takes a yourdfpy URDF).

RobotBatch reads a handful of things from a URDF: the actuated joint names (its cfg columns),
the joints (parent / child link, origin, axis, type), the base link and the visual meshes with
their links. :class:`MjcfDrawing` provides the same from a compiled MjModel, so a robot given
only as an MJCF (or a URDF MuJoCo converted) is drawn from the very model it is retargeted
with:

- every body of the floating base's subtree is a link; a body's pose relative to its parent is
  the joint origin; a hinge with an anchor off the body origin, or a body with several hinges,
  becomes a short chain of virtual links (rotation about the anchor);
- per body, its visual geoms (the ones that collide with nothing, MJCF's usual visual class),
  or its collision geoms when it has no visual one; meshes come from the model's own vertex
  tables, primitives (box, sphere, capsule, cylinder, ellipsoid) are tessellated;
- a joint with a reference angle (MJCF ``ref``, qpos0) turns by q - ref, as in MuJoCo: drawn as
  its own mimic with that offset.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

import numpy as np


@dataclass
class _Mimic:
    joint: str
    multiplier: float = 1.0
    offset: float = 0.0


@dataclass
class _Joint:
    name: str
    parent: str
    child: str
    origin: np.ndarray  # 4x4
    axis: np.ndarray | None
    type: str  # "revolute" / "fixed"
    mimic: object = None


class _Graph:
    def __init__(self, parents: dict):
        self.transforms = type("T", (), {"parents": parents})()


class _Scene:
    def __init__(self, geometry: dict, parents: dict):
        self.geometry = geometry
        self.graph = _Graph(parents)


def _pose(pos, quat) -> np.ndarray:
    from ..rotations import quat_to_matrix

    T = np.eye(4)
    T[:3, :3] = quat_to_matrix(np.asarray(quat, dtype=np.float64))
    T[:3, 3] = pos
    return T


def _translate(p) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = p
    return T


def _geom_mesh(model, g: int):
    """The geom as a trimesh in its own frame, or None (planes, height fields)."""
    import mujoco as mj
    import trimesh

    t = model.geom_type[g]
    s = model.geom_size[g]
    if t == mj.mjtGeom.mjGEOM_MESH:
        m = model.geom_dataid[g]
        v0, nv = model.mesh_vertadr[m], model.mesh_vertnum[m]
        f0, nf = model.mesh_faceadr[m], model.mesh_facenum[m]
        return trimesh.Trimesh(model.mesh_vert[v0:v0 + nv].copy(), model.mesh_face[f0:f0 + nf].copy(), process=False)
    if t == mj.mjtGeom.mjGEOM_BOX:
        return trimesh.creation.box(extents=2 * s[:3])
    if t == mj.mjtGeom.mjGEOM_SPHERE:
        return trimesh.creation.icosphere(subdivisions=2, radius=float(s[0]))
    if t == mj.mjtGeom.mjGEOM_CAPSULE:
        return trimesh.creation.capsule(height=2 * float(s[1]), radius=float(s[0]), count=[12, 12])
    if t == mj.mjtGeom.mjGEOM_CYLINDER:
        return trimesh.creation.cylinder(radius=float(s[0]), height=2 * float(s[1]), sections=16)
    if t == mj.mjtGeom.mjGEOM_ELLIPSOID:
        m = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        m.apply_scale(s[:3])
        return m
    return None


class MjcfDrawing:
    """yourdfpy-like view of a compiled MjModel (see the module docstring)."""

    def __init__(self, model):
        import mujoco as mj

        def name(kind, i, fallback):
            return mj.mj_id2name(model, kind, i) or fallback

        free = [j for j in range(model.njnt) if model.jnt_type[j] == mj.mjtJoint.mjJNT_FREE]
        root = int(model.jnt_bodyid[free[0]]) if free else 1
        hinges = [j for j in range(model.njnt) if model.jnt_type[j] in (mj.mjtJoint.mjJNT_HINGE, mj.mjtJoint.mjJNT_SLIDE)]
        hinges.sort(key=lambda j: model.jnt_qposadr[j])
        self.actuated_joint_names = [name(mj.mjtObj.mjOBJ_JOINT, j, f"joint{j}") for j in hinges]
        body = {b: name(mj.mjtObj.mjOBJ_BODY, b, f"body{b}") for b in range(model.nbody)}
        self.base_link = body[root]
        children = collections.defaultdict(list)
        for b in range(1, model.nbody):
            children[int(model.body_parentid[b])].append(b)
        self.joint_map: dict = {}
        keep = set()
        stack = [root]
        while stack:
            b = stack.pop()
            keep.add(b)
            stack.extend(children[b])
        for b in sorted(keep - {root}):
            parent = body[int(model.body_parentid[b])]
            T = _pose(model.body_pos[b], model.body_quat[b])
            js = [j for j in range(model.jnt_bodyid.size) if model.jnt_bodyid[j] == b
                  and model.jnt_type[j] in (mj.mjtJoint.mjJNT_HINGE, mj.mjtJoint.mjJNT_SLIDE)]
            if not js:
                self.joint_map[f"{body[b]}__fixed"] = _Joint(f"{body[b]}__fixed", parent, body[b], T, None, "fixed")
                continue
            link, origin = parent, T
            for k, j in enumerate(js):
                jn = name(mj.mjtObj.mjOBJ_JOINT, j, f"joint{j}")
                p = np.asarray(model.jnt_pos[j], dtype=np.float64)
                kind = "revolute" if model.jnt_type[j] == mj.mjtJoint.mjJNT_HINGE else "prismatic"
                last = k == len(js) - 1
                ref = float(model.qpos0[model.jnt_qposadr[j]])
                mimic = _Mimic(jn, 1.0, -ref) if abs(ref) > 1e-12 else None  # turns by q - ref
                if np.linalg.norm(p) < 1e-9 and last:
                    self.joint_map[jn] = _Joint(jn, link, body[b], origin, np.asarray(model.jnt_axis[j], float), kind, mimic)
                    break
                # rotation about the anchor p (child frame): origin @ T(p) @ R(q) @ T(-p)
                v = f"{body[b]}__{jn}"
                self.joint_map[jn] = _Joint(jn, link, v, origin @ _translate(p), np.asarray(model.jnt_axis[j], float), kind,
                                            mimic)
                link, origin = v, _translate(-p)
                if last:
                    self.joint_map[f"{v}__back"] = _Joint(f"{v}__back", link, body[b], origin, None, "fixed")
        # visual geometry
        geoms = [g for g in range(model.ngeom) if int(model.geom_bodyid[g]) in keep]
        visual = {g for g in geoms if not model.geom_contype[g] and not model.geom_conaffinity[g]}
        with_visual = {int(model.geom_bodyid[g]) for g in visual}
        draw = [g for g in geoms if g in visual or int(model.geom_bodyid[g]) not in with_visual]
        geometry, parents, self._T = {}, {}, {}
        for g in draw:
            mesh = _geom_mesh(model, g)
            if mesh is None or not len(mesh.faces):
                continue
            n = f"geom{g}"
            geometry[n] = mesh
            parents[n] = body[int(model.geom_bodyid[g])]
            self._T[n] = _pose(model.geom_pos[g], model.geom_quat[g])
        self.scene = _Scene(geometry, parents)

    def get_transform(self, frame_to: str, frame_from: str) -> np.ndarray:
        """Pose of geometry node `frame_to` in its link `frame_from` (the only use RobotBatch has)."""
        return self._T[frame_to]
