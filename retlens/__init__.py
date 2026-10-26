"""RetLens: motion-capture retargeting and validation tools.

Coordinate convention used everywhere in this package (same as Isaac Sim):
right-handed, Z-up, meters, quaternions in (w, x, y, z) order.
"""

__version__ = "0.4.1"  # RetLens release version (bump before tagging v<version>)

from .motion import RobotMotion, SkeletonMotion  # noqa: E402

__all__ = ["RobotMotion", "SkeletonMotion", "__version__"]
