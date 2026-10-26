"""Small numpy rotation helpers. Quaternions are (w, x, y, z)."""

from __future__ import annotations

import numpy as np

_AXES = {"x": 0, "y": 1, "z": 2}


def axis_rotation(axis: str, angle: np.ndarray) -> np.ndarray:
    """Rotation matrices about a principal axis. angle: (...,) radians -> (..., 3, 3)."""
    angle = np.asarray(angle, dtype=np.float64)
    c, s = np.cos(angle), np.sin(angle)
    one, zero = np.ones_like(c), np.zeros_like(c)
    i = _AXES[axis.lower()]
    if i == 0:
        rows = [[one, zero, zero], [zero, c, -s], [zero, s, c]]
    elif i == 1:
        rows = [[c, zero, s], [zero, one, zero], [-s, zero, c]]
    else:
        rows = [[c, -s, zero], [s, c, zero], [zero, zero, one]]
    return np.stack([np.stack(r, axis=-1) for r in rows], axis=-2)


def axis_angle_to_matrix(aa: np.ndarray) -> np.ndarray:
    """Rodrigues formula. aa: (..., 3) axis * angle -> (..., 3, 3)."""
    aa = np.asarray(aa, dtype=np.float64)
    theta = np.linalg.norm(aa, axis=-1, keepdims=True)
    small = theta < 1e-8
    axis = aa / np.where(small, 1.0, theta)
    x, y, z = axis[..., 0], axis[..., 1], axis[..., 2]
    zero = np.zeros_like(x)
    k = np.stack(
        [np.stack([zero, -z, y], -1), np.stack([z, zero, -x], -1), np.stack([-y, x, zero], -1)], -2
    )
    t = theta[..., None]
    eye = np.broadcast_to(np.eye(3), k.shape)
    rot = eye + np.sin(t) * k + (1.0 - np.cos(t)) * (k @ k)
    return np.where(small[..., None], eye, rot)


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    q = quat_normalize(q)
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack(
        [
            np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
            np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
            np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
        ],
        -2,
    )


def matrix_to_quat(m: np.ndarray) -> np.ndarray:
    """(..., 3, 3) -> (..., 4) wxyz, w >= 0."""
    m = np.asarray(m, dtype=np.float64)
    tr = m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2]
    cands = np.stack(
        [
            1.0 + tr,
            1.0 + m[..., 0, 0] - m[..., 1, 1] - m[..., 2, 2],
            1.0 - m[..., 0, 0] + m[..., 1, 1] - m[..., 2, 2],
            1.0 - m[..., 0, 0] - m[..., 1, 1] + m[..., 2, 2],
        ],
        -1,
    )
    best = np.argmax(cands, axis=-1)
    q = np.empty(m.shape[:-2] + (4,))
    s = np.sqrt(np.maximum(np.take_along_axis(cands, best[..., None], -1)[..., 0], 1e-12)) * 2.0
    # w largest
    b = best == 0
    q[b] = np.stack(
        [0.25 * s[b], (m[b][:, 2, 1] - m[b][:, 1, 2]) / s[b], (m[b][:, 0, 2] - m[b][:, 2, 0]) / s[b],
         (m[b][:, 1, 0] - m[b][:, 0, 1]) / s[b]], -1)
    b = best == 1
    q[b] = np.stack(
        [(m[b][:, 2, 1] - m[b][:, 1, 2]) / s[b], 0.25 * s[b], (m[b][:, 0, 1] + m[b][:, 1, 0]) / s[b],
         (m[b][:, 0, 2] + m[b][:, 2, 0]) / s[b]], -1)
    b = best == 2
    q[b] = np.stack(
        [(m[b][:, 0, 2] - m[b][:, 2, 0]) / s[b], (m[b][:, 0, 1] + m[b][:, 1, 0]) / s[b], 0.25 * s[b],
         (m[b][:, 1, 2] + m[b][:, 2, 1]) / s[b]], -1)
    b = best == 3
    q[b] = np.stack(
        [(m[b][:, 1, 0] - m[b][:, 0, 1]) / s[b], (m[b][:, 0, 2] + m[b][:, 2, 0]) / s[b],
         (m[b][:, 1, 2] + m[b][:, 2, 1]) / s[b], 0.25 * s[b]], -1)
    q = quat_normalize(q)
    return np.where(q[..., :1] < 0, -q, q)


def quat_normalize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=np.float64)
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    aw, ax, ay, az = np.moveaxis(np.asarray(a, dtype=np.float64), -1, 0)
    bw, bx, by, bz = np.moveaxis(np.asarray(b, dtype=np.float64), -1, 0)
    return np.stack(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        -1,
    )


def quat_from_two_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest-arc rotation taking unit-ish vector a onto b. (..., 3) -> (..., 4)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-12)
    w = 1.0 + np.sum(a * b, axis=-1, keepdims=True)
    xyz = np.cross(a, b)
    # anti-parallel: rotate 180 deg about any axis orthogonal to a
    anti = w[..., 0] < 1e-8
    if np.any(anti):
        ortho = np.cross(a[anti], np.array([1.0, 0.0, 0.0]))
        bad = np.linalg.norm(ortho, axis=-1) < 1e-6
        ortho[bad] = np.cross(a[anti][bad], np.array([0.0, 1.0, 0.0]))
        xyz[anti] = ortho
        w[anti] = 0.0
    return quat_normalize(np.concatenate([w, xyz], -1))


# Rotation that maps a Y-up frame into the Z-up frame used by Isaac Sim (+90 deg about X).
Y_UP_TO_Z_UP = axis_rotation("x", np.pi / 2)


def to_z_up(points: np.ndarray, up_axis: str) -> np.ndarray:
    """Re-express (..., 3) points given in a Y-up or Z-up frame in the Z-up frame."""
    up_axis = up_axis.lower()
    if up_axis == "z":
        return points
    if up_axis == "y":
        return points @ Y_UP_TO_Z_UP.T
    raise ValueError(f"unsupported up axis: {up_axis!r} (expected 'y' or 'z')")


def rot_to_z_up(frames: np.ndarray, up_axis: str) -> np.ndarray:
    """Re-express (..., 3, 3) local-to-world frames in the Z-up world.

    Only the world side changes (left multiply); the frame's own axes stay the
    file's, which is the convention GMR's BVH loaders use too.
    """
    up_axis = up_axis.lower()
    if up_axis == "z":
        return frames
    if up_axis == "y":
        return Y_UP_TO_Z_UP @ frames
    raise ValueError(f"unsupported up axis: {up_axis!r} (expected 'y' or 'z')")
