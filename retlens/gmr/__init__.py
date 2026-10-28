"""The parts of GMR (General Motion Retargeting) that RetLens's retargeting uses, vendored.

Source: github.com/YanjieZe/GMR @ bb1bbe40774794fceb2a7c579a3464a28e68c844 (MIT, LICENSE in
this folder; Yanjie Ze et al.):
- motion_retarget.py: the per-frame differential IK (mink on MuJoCo), unchanged except that
  solve_ik gets the IK limits as ``limits=`` (GMR passed them 6th, which mink >= 1.x takes as
  safety_break: mink rebuilt the configuration limit on every solve and dropped the velocity
  limit; same output, IK 22-39 % faster);
- params.py: robot model and IK-config tables, Unitree G1 only, asset path from retlens.paths;
- ik_configs/*_to_g1.json: the G1 IK configs, unchanged.

GMR's own package imports torch (its kinematics model), the MuJoCo viewer and imageio on
import, none of which retargeting needs; this copy needs only mink, mujoco, scipy and rich.
That keeps torch (~700 MB with MKL) out of the packaged program. LAFAN1 / Nokov BVH files are
read with retlens.io.bvh in GMR's frame convention instead of GMR's bundled LAFAN1 reader.
The robot meshes (assets/unitree_g1, Unitree, BSD-3) are not copied into the repository:
retlens.paths.robot_assets_dir() finds them (the GMR checkout, or the installed program).
"""

GMR_REPO = "https://github.com/YanjieZe/GMR"
GMR_COMMIT = "bb1bbe40774794fceb2a7c579a3464a28e68c844"

from .params import ASSET_ROOT, IK_CONFIG_DICT, IK_CONFIG_ROOT, ROBOT_BASE_DICT, ROBOT_XML_DICT  # noqa: E402
from .motion_retarget import GeneralMotionRetargeting  # noqa: E402

__all__ = ["ASSET_ROOT", "IK_CONFIG_DICT", "IK_CONFIG_ROOT", "ROBOT_BASE_DICT", "ROBOT_XML_DICT",
           "GeneralMotionRetargeting", "GMR_COMMIT", "GMR_REPO"]
