"""K-Humanoid motion-capture data tools.

Coordinate convention used everywhere in this package (same as Isaac Sim):
right-handed, Z-up, meters, quaternions in (w, x, y, z) order.
"""

__version__ = "0.2.0"  # RetLens release version (docs/release.md: bump before tagging v<version>)

from .motion import RobotMotion, SkeletonMotion  # noqa: E402

__all__ = ["RobotMotion", "SkeletonMotion", "__version__"]
