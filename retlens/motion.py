"""Unified in-memory motion containers.

Every loader in :mod:`retlens.io` returns one of these, already converted to
Isaac Sim conventions (Z-up, meters, wxyz quaternions).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ObjectTrack:
    """A rigid object moving with a human motion (a prop, a piece of furniture, a rigid-body node):
    its pose per frame of that motion and its shape in its own frame."""

    name: str
    positions: np.ndarray  # (T, 3) meters, Z-up: the object's origin
    rotations: np.ndarray  # (T, 3, 3) its frame in the world
    vertices: np.ndarray  # (V, 3) meters, in its own frame (scale applied); empty for a bare node
    faces: np.ndarray  # (F, 3) int
    kind: str = "mesh"  # "mesh" | "empty" | "bone" (a segment of a prop exported as a skeleton)
    # props from a file of their own (retlens.props): that file, the prop a segment belongs to, the parent
    # segment's index in the motion's objects (-1: none), and where the drawn shape came from ("파일의 메시",
    # "... (모양 파일)", "... (기본값)", "모양 파일 오류: ..."; "" = no shape)
    source: str = ""
    group: str = ""
    parent: int = -1
    shape: str = ""

    def world_vertices(self, frame: int) -> np.ndarray:
        return self.vertices @ self.rotations[frame].T + self.positions[frame]

    @property
    def moves(self) -> bool:
        """Whether it moves during the clip (more than 1 cm or 2 degrees)."""
        p, R = self.positions, self.rotations
        turn = np.einsum("ij,tij->t", R[0], R)  # trace(R0^T R_t)
        return bool(np.nanmax(np.linalg.norm(p - p[0], axis=1)) > 0.01
                    or np.nanmin(turn) < 1 + 2 * np.cos(np.radians(2.0)))


@dataclass
class SkeletonMotion:
    """Human motion as world-space joint (or marker) positions.

    Raw optical markers are stored the same way with every parent set to -1,
    so they render as a point cloud without bones. Missing samples are NaN.
    """

    name: str
    joint_names: list[str]
    parents: np.ndarray  # (J,) int, -1 for roots / unconnected points
    positions: np.ndarray  # (T, J, 3) float, meters, Z-up
    fps: float
    source: str = ""
    kind: str = "skeleton"  # "skeleton" | "markers"
    meta: dict = field(default_factory=dict)
    # (T, J, 3, 3) joint frames in the world (Z-up), only when the loader was
    # asked for them (BVH with_rotations=True). Joint-local axes are the file's.
    rotations: np.ndarray | None = None
    # props and furniture captured with the person (FBX), on the same frames
    objects: list[ObjectTrack] = field(default_factory=list)

    @property
    def num_frames(self) -> int:
        return int(self.positions.shape[0])

    @property
    def duration(self) -> float:
        return self.num_frames / self.fps if self.fps > 0 else 0.0

    def bones(self) -> list[tuple[int, int]]:
        return [(int(p), j) for j, p in enumerate(self.parents) if p >= 0]

    def find_joints(self, *keywords: str) -> list[int]:
        """Indices of joints whose lower-cased name contains any keyword."""
        keys = [k.lower() for k in keywords]
        return [i for i, n in enumerate(self.joint_names) if any(k in n.lower() for k in keys)]


@dataclass
class RobotMotion:
    """Retargeted robot motion: floating-base pose + joint positions."""

    name: str
    joint_names: list[str]
    root_pos: np.ndarray  # (T, 3) meters, Z-up
    root_quat: np.ndarray  # (T, 4) wxyz
    dof_pos: np.ndarray  # (T, D) radians (or meters for prismatic joints)
    fps: float
    source: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def num_frames(self) -> int:
        return int(self.dof_pos.shape[0])

    @property
    def duration(self) -> float:
        return self.num_frames / self.fps if self.fps > 0 else 0.0

    def save_npz(self, path: str) -> None:
        """Write the project's canonical robot-motion file (with the robot's name and model digest
        when known: meta["robot_ident"], retlens.robot_profile.RobotProfile.ident)."""
        ident = self.meta.get("robot_ident") or {}
        extra = {f"robot_{k}": np.array(str(ident[k])) for k in ("name", "digest") if ident.get(k)}
        np.savez_compressed(
            path,
            fps=np.float64(self.fps),
            joint_names=np.array(self.joint_names),
            root_pos=self.root_pos.astype(np.float32),
            root_quat_wxyz=self.root_quat.astype(np.float32),
            dof_pos=self.dof_pos.astype(np.float32),
            **extra,
        )
