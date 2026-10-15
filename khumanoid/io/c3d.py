"""C3D (raw optical-marker) reader, via ezc3d."""

from __future__ import annotations

import os

import numpy as np

from ..motion import SkeletonMotion
from ..rotations import to_z_up

_UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254}


def load_c3d(path: str, up_axis: str = "z") -> SkeletonMotion:
    """Load marker trajectories. Occluded/missing samples become NaN.

    Vicon writes Z-up C3D; OptiTrack Motive defaults to Y-up, so pass
    ``up_axis="y"`` for those.
    """
    import ezc3d  # optional dependency (conda-forge::ezc3d)

    c = ezc3d.c3d(path)
    pts = np.asarray(c["data"]["points"], dtype=np.float64)  # (4, M, T)
    xyz = np.transpose(pts[:3], (2, 1, 0))  # (T, M, 3)
    params = c["parameters"]["POINT"]
    unit = str(params.get("UNITS", {}).get("value", ["mm"])[0]).strip().lower()
    xyz = xyz * _UNITS.get(unit, 0.001)

    meta_points = c["data"].get("meta_points", {})
    residuals = meta_points.get("residuals")
    if residuals is not None:
        res = np.asarray(residuals, dtype=np.float64)[0].T  # (T, M)
        xyz[res < 0] = np.nan
    xyz[np.all(xyz == 0, axis=-1)] = np.nan  # some exporters write zeros for gaps

    labels = [str(s) for s in params.get("LABELS", {}).get("value", [])]
    labels += [f"marker_{i}" for i in range(len(labels), xyz.shape[1])]
    fps = float(params.get("RATE", {}).get("value", [0.0])[0])

    return SkeletonMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=labels[: xyz.shape[1]],
        parents=np.full(xyz.shape[1], -1, dtype=int),
        positions=to_z_up(xyz, up_axis),
        fps=fps,
        source=os.path.abspath(path),
        kind="markers",
        meta={"format": "c3d", "units": unit, "up_axis": up_axis},
    )
