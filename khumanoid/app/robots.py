"""Every robot (and the per-motion overlays) drawn with a handful of shared viser nodes.

viser's ViserUrdf gives each robot a tree of ~40 frames and moves them one by one: about
80 property updates per robot per frame, ~10 ms of Python each, so seven robots cap a
viewer at ~13 updates per second. Here
- each rigid part of the URDF (links joined by fixed joints merged) is one batched mesh
  with one instance per robot, in that robot's colour;
- forward kinematics runs in numpy for all robots at once;
- a node's rotations and positions go out in one message;
- the skeletons, support polygons and CoM / ZMP marks of all motions are shared nodes too.
A frame then costs ~35 messages however many motions are shown.
"""

from __future__ import annotations

import collections
import warnings

import numpy as np

from ..rotations import axis_angle_to_matrix, matrix_to_quat


def set_props(handle, **props) -> None:
    """Several properties of a scene node in one message (viser 1.1 sends one per property).
    Falls back to plain attribute setting if viser's internals differ."""
    try:
        from viser import _messages

        impl = handle._impl
        for k, v in props.items():
            setattr(impl.props, k, v)
        impl.api._queue_scene_message(_messages.SceneNodeUpdateMessage(impl.name, dict(props)))
    except (AttributeError, TypeError, ImportError):
        for k, v in props.items():
            setattr(handle, k, v)


def _quiet_remove(handle) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        handle.remove()


class RobotBatch:
    def __init__(self, server, urdf, root: str = "/robots"):
        """urdf: a yourdfpy URDF with its visual scene graph (meshes loaded)."""
        self.server, self.urdf, self.root = server, urdf, root
        self.joint_names: list[str] = list(urdf.actuated_joint_names)  # cfg column order
        self._build_kinematics()
        self._build_meshes()
        self.handles: list = []
        self.colors: list[tuple] = []
        self.opacity = 1.0
        self._scales = None

    # ---------------------------------------------------------------- model
    def _build_kinematics(self) -> None:
        u = self.urdf
        children = collections.defaultdict(list)
        for j in u.joint_map.values():
            children[j.parent].append(j)
        base = u.base_link
        self.links = [base]
        self._joints = []  # (parent link index, child link index, kind, origin 4x4, axis, q column, mimic)
        index = {base: 0}
        self.rigid_root = {0: (0, np.eye(4))}  # link -> (link it moves with, fixed transform from that link)
        queue = collections.deque([base])
        col = {n: i for i, n in enumerate(self.joint_names)}
        while queue:
            link = queue.popleft()
            for j in children[link]:
                index[j.child] = c = len(self.links)
                self.links.append(j.child)
                origin = np.eye(4) if j.origin is None else np.asarray(j.origin, dtype=np.float64)
                axis = np.array([1.0, 0.0, 0.0]) if j.axis is None else np.asarray(j.axis, dtype=np.float64)
                axis = axis / max(np.linalg.norm(axis), 1e-12)
                mimic = None
                if getattr(j, "mimic", None) is not None and j.mimic.joint in col:
                    mimic = (col[j.mimic.joint], float(j.mimic.multiplier or 1.0), float(j.mimic.offset or 0.0))
                kind = j.type if j.type in ("revolute", "continuous", "prismatic") else "fixed"
                if kind != "fixed" and col.get(j.name, -1) < 0 and mimic is None:
                    kind = "fixed"  # a joint the model never moves
                p = index[link]
                self._joints.append((p, c, kind, origin, axis, col.get(j.name, -1), mimic))
                if kind == "fixed":
                    root, T = self.rigid_root[p]
                    self.rigid_root[c] = (root, T @ origin)
                else:
                    self.rigid_root[c] = (c, np.eye(4))
                queue.append(j.child)
        self.link_index = index
        # rotating joints, for one Rodrigues call per frame
        self._rot = [k for k, jt in enumerate(self._joints) if jt[2] in ("revolute", "continuous")]
        self._rot_axes = np.array([self._joints[k][4] for k in self._rot]).reshape(-1, 3)
        self._rot_slot = {k: s for s, k in enumerate(self._rot)}

    def _build_meshes(self) -> None:
        """Visual meshes merged per rigid part, in the frame of the part's moving link."""
        scene = self.urdf.scene
        parents = scene.graph.transforms.parents
        parts: dict[int, list] = collections.defaultdict(list)
        for name, mesh in scene.geometry.items():
            link = parents.get(name)
            if link not in self.link_index:
                continue
            root, T_root_link = self.rigid_root[self.link_index[link]]
            m = mesh.copy()
            m.apply_transform(T_root_link @ self.urdf.get_transform(name, link))
            parts[root].append(m)
        self.meshes = []  # (moving link index, vertices float32, faces uint32)
        for root, ms in parts.items():
            v, f, n = [], [], 0
            for m in ms:
                v.append(np.asarray(m.vertices, np.float32))
                f.append(np.asarray(m.faces, np.int64) + n)
                n += len(m.vertices)
            self.meshes.append((root, np.concatenate(v), np.concatenate(f).astype(np.uint32)))

    # ---------------------------------------------------------------- instances
    def set_instances(self, colors: list[tuple], opacity: float = 1.0) -> None:
        """One instance per robot, in this order. Instances start hidden (scale 0) until the
        next update() poses them.

        Existing nodes are resized in place: re-creating them would send every mesh to the
        browser again, and a batched mesh being re-created can be drawn once before its
        instances exist (Chromium then logs 'glDrawElementsInstanced: Vertex shader input
        type does not match ...')."""
        colors = [tuple(int(c) for c in rgb) for rgb in colors]
        opacity = float(opacity)
        if colors == self.colors and opacity == self.opacity and (self.handles or not colors):
            return
        n = len(colors)
        props = dict(batched_wxyzs=np.tile([1.0, 0.0, 0.0, 0.0], (n, 1)).astype(np.float32),
                     batched_positions=np.zeros((n, 3), np.float32), batched_scales=np.zeros(n, np.float32),
                     batched_colors=np.array(colors, dtype=np.uint8).reshape(n, 3))
        opac = np.full(n, opacity, np.float32) if opacity < 1.0 else None
        if n and self.handles and (opac is None) == (self.opacity >= 1.0):
            if opac is not None:
                props["batched_opacities"] = opac
            for h in self.handles:
                set_props(h, **props)
        else:
            self.remove()
            if n:
                self.handles = [
                    self.server.scene.add_batched_meshes_simple(
                        f"{self.root}/mesh{i}", v, f, batched_opacities=opac, lod="off", **props)
                    for i, (_, v, f) in enumerate(self.meshes)]
        self.colors, self.opacity = colors, opacity
        self._scales = None

    def remove(self) -> None:
        for h in self.handles:
            _quiet_remove(h)
        self.handles, self.colors = [], []

    # ---------------------------------------------------------------- per frame
    def forward(self, T_base: np.ndarray, cfg: np.ndarray) -> np.ndarray:
        """World transforms (links, N, 4, 4) of every link of N robots, given their base
        transforms (N, 4, 4) and joint values (N, len(joint_names))."""
        n = len(T_base)
        T = np.empty((len(self.links), n, 4, 4))
        T[0] = T_base

        def value(k):
            _, _, _, _, _, q_col, mimic = self._joints[k]
            return cfg[:, mimic[0]] * mimic[1] + mimic[2] if mimic is not None else cfg[:, q_col]

        if self._rot:  # all joint rotations of all robots at once: (N, joints, 3, 3)
            q = np.stack([value(k) for k in self._rot], axis=1)
            R = axis_angle_to_matrix(self._rot_axes[None] * q[..., None])
        for k, (parent, child, kind, origin, axis, _q_col, _mimic) in enumerate(self._joints):
            A = T[parent] @ origin
            if kind == "prismatic":
                A[:, :3, 3] += (A[:, :3, :3] @ axis) * value(k)[:, None]
            elif kind != "fixed":
                A[:, :3, :3] = A[:, :3, :3] @ R[:, self._rot_slot[k]]
            T[child] = A
        return T

    def update(self, T_base: np.ndarray, cfg: np.ndarray, visible: np.ndarray) -> np.ndarray:
        """Pose every robot; returns the link transforms. Hidden robots are scaled to zero."""
        if not self.handles or len(T_base) != len(self.colors):
            return np.empty((len(self.links), 0, 4, 4))
        T = self.forward(T_base, cfg)
        scales = np.where(visible, 1.0, 0.0).astype(np.float32)
        set_scales = self._scales is None or not np.array_equal(scales, self._scales)
        self._scales = scales
        M = T[[li for li, _, _ in self.meshes]]  # (meshes, N, 4, 4)
        quats = matrix_to_quat(M[..., :3, :3].reshape(-1, 3, 3)).reshape(len(self.meshes), -1, 4).astype(np.float32)
        positions = M[..., :3, 3].astype(np.float32)
        for k, h in enumerate(self.handles):
            props = dict(batched_wxyzs=quats[k], batched_positions=positions[k])
            if set_scales:
                props["batched_scales"] = scales
            set_props(h, **props)
        return T


class OverlayBatch:
    """Skeleton sticks, support polygons and CoM / ZMP marks of all motions in four nodes."""
    SUPPORT_EDGES = 8

    def __init__(self, server, root: str = "/overlays"):
        self.server, self.root = server, root
        self.layout = None
        self.handles: dict = {}

    def sync(self, bones: list[int], colors: list[tuple]) -> None:
        """Lay out for this many skeleton bones (0 = no skeleton) and colours, one per motion.
        Existing nodes are resized in place (see RobotBatch.set_instances)."""
        layout = (tuple(bones), tuple(tuple(c) for c in colors))
        if layout == self.layout:
            return
        n, nb, sc = len(bones), sum(bones), self.server.scene
        if not n or ("human" in self.handles) != (nb > 0):
            self.remove()
        self.layout = layout
        if not n:
            return
        fresh = not self.handles
        if nb:
            dark = np.concatenate([np.tile(np.array([int(c * 0.55) for c in col], np.uint8), (k, 2, 1))
                                   for k, col in zip(bones, colors) if k])
            pts = np.zeros((nb, 2, 3), np.float32)
            if fresh:
                self.handles["human"] = sc.add_line_segments(f"{self.root}/humans", pts, dark, thickness=0.012)
            else:
                set_props(self.handles["human"], points=pts, colors=dark)
        edges = np.zeros((self.SUPPORT_EDGES * n, 2, 3), np.float32)
        if fresh:
            self.handles["support"] = sc.add_line_segments(f"{self.root}/support", edges, (40, 170, 70), thickness=0.006)
        else:
            set_props(self.handles["support"], points=edges)
        import trimesh

        for key, radius, rgb in (("com", 0.025, (40, 90, 220)), ("zmp", 0.02, (220, 50, 40))):
            props = dict(batched_wxyzs=np.tile([1.0, 0, 0, 0], (n, 1)).astype(np.float32),
                         batched_positions=np.zeros((n, 3), np.float32), batched_scales=np.zeros(n, np.float32),
                         batched_colors=np.tile(np.array(rgb, np.uint8), (n, 1)))
            if fresh:
                ball = trimesh.creation.icosphere(subdivisions=2, radius=radius)
                self.handles[key] = sc.add_batched_meshes_simple(
                    f"{self.root}/{key}", np.asarray(ball.vertices, np.float32), np.asarray(ball.faces, np.uint32),
                    lod="off", cast_shadow=False, **props)
            else:
                set_props(self.handles[key], **props)

    def update(self, humans: list, balance: list) -> None:
        """humans: per motion (bones, 2, 3) points or None (hidden); balance: per motion
        (support edges (8, 2, 3), com (3,), zmp (3,)) or None."""
        if self.layout is None or not self.handles:
            return
        bones = self.layout[0]
        if "human" in self.handles:
            pts = np.concatenate([(h if h is not None else np.zeros((k, 2, 3)))
                                  for h, k in zip(humans, bones) if k]).astype(np.float32)
            set_props(self.handles["human"], points=pts)
        n = len(bones)
        edges = np.zeros((self.SUPPORT_EDGES * n, 2, 3), np.float32)
        com, zmp = np.zeros((n, 3), np.float32), np.zeros((n, 3), np.float32)
        shown = np.zeros(n, np.float32)
        for i, b in enumerate(balance):
            if b is not None:
                edges[i * self.SUPPORT_EDGES:(i + 1) * self.SUPPORT_EDGES] = b[0]
                com[i], zmp[i], shown[i] = b[1], b[2], 1.0
        set_props(self.handles["support"], points=edges)
        set_props(self.handles["com"], batched_positions=com, batched_scales=shown)
        set_props(self.handles["zmp"], batched_positions=zmp, batched_scales=shown)

    def remove(self) -> None:
        for h in self.handles.values():
            _quiet_remove(h)
        self.handles, self.layout = {}, None
