"""Unified in-memory motion containers.

Every loader in :mod:`retlens.io` returns one of these, already converted to
Isaac Sim conventions (Z-up, meters, wxyz quaternions).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


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
        """Write the project's canonical robot-motion file."""
        np.savez_compressed(
            path,
            fps=np.float64(self.fps),
            joint_names=np.array(self.joint_names),
            root_pos=self.root_pos.astype(np.float32),
            root_quat_wxyz=self.root_quat.astype(np.float32),
            dof_pos=self.dof_pos.astype(np.float32),
        )
