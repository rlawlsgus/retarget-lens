"""K-Humanoid motion-capture data tools.

Coordinate convention used everywhere in this package (same as Isaac Sim):
right-handed, Z-up, meters, quaternions in (w, x, y, z) order.
"""

from .motion import RobotMotion, SkeletonMotion

__all__ = ["RobotMotion", "SkeletonMotion"]
