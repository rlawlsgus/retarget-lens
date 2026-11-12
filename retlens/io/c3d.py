"""C3D (raw optical-marker) reader, via ezc3d."""

from __future__ import annotations

import os
import shutil
import tempfile

import numpy as np

from ..motion import SkeletonMotion
from ..rotations import to_z_up

_UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254}


def _ascii_temp_dir() -> str:
    """A new temporary folder whose path is plain ASCII (the user's %TEMP% under a Korean user name is not)."""
    bases = (tempfile.gettempdir(), os.environ.get("PUBLIC"),
             os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp"))
    for base in bases:
        if base and base.isascii() and os.path.isdir(base):
            try:
                return tempfile.mkdtemp(prefix="retlens_c3d_", dir=base)
            except OSError:  # not writable here: try the next
                continue
    raise OSError("C3D를 읽을 임시 폴더(영문 경로)를 만들지 못했습니다")


def _read(path: str):
    """ezc3d's reading of a C3D file. ezc3d opens the path as narrow characters, so a path with Korean (or other
    non-ASCII) letters cannot be opened on Windows: such a file is read from a copy in an ASCII temporary folder."""
    import ezc3d  # optional dependency (conda-forge::ezc3d)

    if not os.path.isfile(path):
        raise FileNotFoundError(2, "No such file or directory", path)
    tmp = None
    try:
        src = path
        if not os.path.abspath(path).isascii():
            tmp = _ascii_temp_dir()
            src = os.path.join(tmp, "take.c3d")
            shutil.copyfile(path, src)  # (a failed copy still removes the folder below)
        try:
            return ezc3d.c3d(src)
        except (OSError, RuntimeError, ValueError) as e:  # ezc3d: "could not be opened" / a bad header or block
            raise ValueError(f"{os.path.basename(path)}: C3D 파일을 읽지 못했습니다 (손상되었거나 C3D 파일이 아님)") from e
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def load_c3d(path: str, up_axis: str = "z") -> SkeletonMotion:
    """Load marker trajectories. Occluded/missing samples become NaN.

    Vicon writes Z-up C3D; OptiTrack Motive defaults to Y-up, so pass
    ``up_axis="y"`` for those.
    """
    c = _read(path)
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
