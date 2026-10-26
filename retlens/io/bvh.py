"""BVH reader with vectorised forward kinematics.

BVH is the common export of Vicon Shogun, OptiTrack Motive, Xsens MVN,
Rokoko, MotionBuilder, and is the format of CMU Mocap / LAFAN1.
"""

from __future__ import annotations

import json
import os
import re

import numpy as np

from ..motion import SkeletonMotion
from ..rotations import axis_rotation, rot_to_z_up, to_z_up

# Candidate unit scales -> meters: meters, centimeters, inches, and the CMU
# "cgspeed" BVH convention (inches / 0.45).
_UNIT_CANDIDATES = (1.0, 0.01, 0.0254, 0.0254 / 0.45)


class _Joint:
    __slots__ = ("name", "parent", "offset", "channels", "is_end")

    def __init__(self, name: str, parent: int, is_end: bool = False):
        self.name = name
        self.parent = parent
        self.offset = np.zeros(3)
        self.channels: list[str] = []
        self.is_end = is_end


def _parse(text: str):
    tokens = text.split()
    i = 0
    joints: list[_Joint] = []
    stack: list[int] = []

    def take() -> str:
        nonlocal i
        tok = tokens[i]
        i += 1
        return tok

    if take().upper() != "HIERARCHY":
        raise ValueError("not a BVH file (missing HIERARCHY)")

    while i < len(tokens):
        tok = take()
        up = tok.upper()
        if up in ("ROOT", "JOINT"):
            name = take()
            joints.append(_Joint(name, stack[-1] if stack else -1))
        elif up == "END":
            take()  # "Site"
            parent = stack[-1]
            joints.append(_Joint(f"{joints[parent].name}_end", parent, is_end=True))
        elif tok == "{":
            stack.append(len(joints) - 1)
        elif tok == "}":
            stack.pop()
        elif up == "OFFSET":
            joints[stack[-1]].offset = np.array([float(take()) for _ in range(3)])
        elif up == "CHANNELS":
            n = int(take())
            joints[stack[-1]].channels = [take() for _ in range(n)]
        elif up == "MOTION":
            break
        else:
            raise ValueError(f"unexpected BVH token {tok!r}")

    take()  # "Frames:"
    n_frames = int(take())
    take()  # "Frame"
    take()  # "Time:"
    frame_time = float(take())
    n_channels = sum(len(j.channels) for j in joints)
    values = np.asarray(tokens[i : i + n_frames * n_channels], dtype=np.float64)
    if values.size != n_frames * n_channels:
        raise ValueError(
            f"BVH motion block truncated: expected {n_frames * n_channels} values, got {values.size}"
        )
    return joints, frame_time, values.reshape(n_frames, n_channels)


def _forward_kinematics(joints: list[_Joint], data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World joint positions (T, J, 3) and joint frames (T, J, 3, 3), file units/axes."""
    n_frames = data.shape[0]
    glob_rot = np.zeros((n_frames, len(joints), 3, 3))
    glob_pos = np.zeros((n_frames, len(joints), 3))
    col = 0
    for j, joint in enumerate(joints):
        local_rot = np.broadcast_to(np.eye(3), (n_frames, 3, 3)).copy()
        local_pos = np.broadcast_to(joint.offset, (n_frames, 3)).copy()
        has_pos = False
        pos_vals = np.zeros((n_frames, 3))
        for ch in joint.channels:
            axis, kind = ch[0].lower(), ch[1:].lower()
            v = data[:, col]
            col += 1
            if kind == "rotation":
                # Channels are listed outer-to-inner, i.e. intrinsic order.
                local_rot = local_rot @ axis_rotation(axis, np.deg2rad(v))
            elif kind == "position":
                has_pos = True
                pos_vals[:, "xyz".index(axis)] = v
            else:
                raise ValueError(f"unknown BVH channel {ch!r}")
        if has_pos:
            # Position channels carry the full local translation (the OFFSET is
            # the rest value of the same quantity), so they replace it.
            local_pos = pos_vals
        if joint.parent < 0:
            glob_rot[:, j] = local_rot
            glob_pos[:, j] = local_pos
        else:
            p = joint.parent
            glob_rot[:, j] = glob_rot[:, p] @ local_rot
            glob_pos[:, j] = glob_pos[:, p] + np.einsum("tij,tj->ti", glob_rot[:, p], local_pos)
    return glob_pos, glob_rot


def _rest_data(joints: list[_Joint]) -> np.ndarray:
    """One frame of channel values that reproduces the rest pose (all rotations 0;
    position channels set to the OFFSET they replace)."""
    vals = []
    for joint in joints:
        for ch in joint.channels:
            axis, kind = ch[0].lower(), ch[1:].lower()
            vals.append(joint.offset["xyz".index(axis)] if kind == "position" else 0.0)
    return np.array([vals], dtype=np.float64)


def _cgspeed_tpose(joints: list[_Joint], data: np.ndarray) -> bool:
    """CMU mocap in the cgspeed BVH conversion: frame 0 is a T-pose the converter
    inserted (almost every rotation exactly 0), not capture data."""
    if not {"LHipJoint", "RHipJoint", "LowerBack"} <= {j.name for j in joints} or len(data) < 2:
        return False
    rot = [c for c, ch in enumerate(ch for j in joints for ch in j.channels) if ch.lower().endswith("rotation")]
    return bool(np.mean(data[0, rot] == 0) > 0.8 and np.mean(data[1, rot] == 0) < 0.8)


_CMU_RATES: dict | None = None


def cmu_capture_fps(stem: str) -> tuple[float | None, str]:
    """True capture rate of a CMU trial named like "143_11", and where it comes from.

    The cgspeed BVH conversion writes 120 fps into every file, but 20 subjects were
    (partly) captured at 60 Hz. cmu_frame_rates.json (tools/cmu_frame_rates.py, from
    AMASS's C3D-header rates) lists them. None = a 120 Hz subject or not a CMU name.
    """
    global _CMU_RATES
    m = re.fullmatch(r"(\d+)_(\d+)", stem)
    if not m:
        return None, ""
    if _CMU_RATES is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cmu_frame_rates.json")
        try:
            with open(path, encoding="utf-8") as f:
                _CMU_RATES = json.load(f)
        except OSError:
            _CMU_RATES = {}
    subject = _CMU_RATES.get("subjects", {}).get(str(int(m.group(1))))
    if subject is None:
        return None, ""
    if stem in subject["trials"]:
        return float(subject["trials"][stem]), "AMASS / C3D header"
    return float(subject["majority_fps"]), f"most trials of CMU subject {int(m.group(1))} (this one is not in AMASS)"


def _auto_scale(positions_raw: np.ndarray) -> float:
    """Pick the unit scale that makes the performer's height closest to 1.7 m."""
    frame0 = positions_raw[0]
    extent = float(np.max(np.ptp(frame0, axis=0)))
    if extent <= 0:
        return 1.0
    return min(_UNIT_CANDIDATES, key=lambda s: abs(np.log(extent * s / 1.7)))


def _kept(joints: list[_Joint], include_end_sites: bool) -> tuple[list[int], list[str], np.ndarray]:
    keep = [j for j, jt in enumerate(joints) if include_end_sites or not jt.is_end]
    remap = {old: new for new, old in enumerate(keep)}
    names = [joints[j].name for j in keep]
    parents = np.array(
        [remap.get(joints[j].parent, -1) if joints[j].parent >= 0 else -1 for j in keep], dtype=int
    )
    return keep, names, parents


def load_bvh(
    path: str,
    up_axis: str = "y",
    scale: float | str = "auto",
    include_end_sites: bool = True,
    ground: bool = False,
    with_rotations: bool = False,
    drop_tpose: bool | str = "auto",
    fps: float | str = "auto",
) -> SkeletonMotion:
    """Load a BVH file as world-space joint positions (Z-up, meters).

    Args:
        up_axis: up axis of the file ("y" for almost every BVH exporter).
        scale: multiplier to meters, or "auto" to guess from body height.
        include_end_sites: keep "End Site" leaves (head top, toe tips, fingertips).
        ground: shift vertically so the lowest point over the clip sits on z=0.
            Off by default: capture-volume floors are calibrated to 0, and QC
            needs the original height to detect floor penetration / floating.
        with_rotations: also fill ``SkeletonMotion.rotations`` with the world
            joint frames (needed for retargeting; end sites get their parent's).
        drop_tpose: drop frame 0 when it is the T-pose the CMU cgspeed converter
            inserted ("auto"), always (True) or never (False). Left in, the jump
            from it to the first captured frame is a 100 m/s QC spike.
        fps: frame rate. "auto" = the file's frame time, except cgspeed CMU files
            of 60 Hz trials (see :func:`cmu_capture_fps`), which say 120.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        joints, frame_time, data = _parse(f.read())
    tpose0 = _cgspeed_tpose(joints, data)
    file_fps = 1.0 / frame_time if frame_time > 0 else 0.0
    fps_out, fps_note = file_fps, ""
    if fps != "auto" and fps is not None:
        fps_out, fps_note = float(fps), "given by the caller"
    elif tpose0:
        true_fps, why = cmu_capture_fps(os.path.splitext(os.path.basename(path))[0])
        if true_fps and abs(true_fps - file_fps) > 1.0:
            fps_out = true_fps
            fps_note = f"cgspeed CMU file says {file_fps:.0f} fps; captured at {true_fps:g} fps ({why})"
    dropped = 1 if (drop_tpose is True or (drop_tpose == "auto" and tpose0)) and len(data) > 1 else 0
    data = data[dropped:]
    raw, raw_rot = _forward_kinematics(joints, data)
    s = _auto_scale(raw) if scale == "auto" else float(scale)
    pos = to_z_up(raw * s, up_axis)

    keep, names, parents = _kept(joints, include_end_sites)
    pos = pos[:, keep]
    ground_offset = 0.0
    if ground and np.isfinite(pos).any():
        ground_offset = float(np.nanmin(pos[..., 2]))
        pos = pos.copy()
        pos[..., 2] -= ground_offset

    return SkeletonMotion(
        name=os.path.splitext(os.path.basename(path))[0],
        joint_names=names,
        parents=parents,
        positions=pos,
        fps=fps_out,
        source=os.path.abspath(path),
        kind="skeleton",
        meta={"format": "bvh", "unit_scale": s, "up_axis": up_axis, "ground_offset_m": ground_offset,
              "cgspeed_tpose_frame0": tpose0, "dropped_frames": dropped, "file_fps": file_fps,
              "fps_note": fps_note},
        rotations=rot_to_z_up(raw_rot[:, keep], up_axis) if with_rotations else None,
    )


def bvh_rest_pose(
    path: str, up_axis: str = "y", scale: float | str = "auto", include_end_sites: bool = True
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """The skeleton with every rotation channel at 0 (what OFFSETs describe).

    Returns joint names, positions (J, 3) and world joint frames (J, 3, 3), Z-up
    meters, same joint order as :func:`load_bvh`. ``scale="auto"`` guesses from
    the first motion frame, like load_bvh, so both agree.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        joints, _, data = _parse(f.read())
    s = _auto_scale(_forward_kinematics(joints, data[:1])[0]) if scale == "auto" else float(scale)
    raw, raw_rot = _forward_kinematics(joints, _rest_data(joints))
    keep, names, _ = _kept(joints, include_end_sites)
    return names, to_z_up(raw[0] * s, up_axis)[keep], rot_to_z_up(raw_rot[0], up_axis)[keep]
