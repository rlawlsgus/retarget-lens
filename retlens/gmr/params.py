# Vendored from GMR (github.com/YanjieZe/GMR @ bb1bbe40774794fceb2a7c579a3464a28e68c844,
# general_motion_retargeting/params.py, MIT, see LICENSE in this folder). Changed here:
# - only the Unitree G1 entries (the robot RetLens ships);
# - ASSET_ROOT comes from retlens.paths: the GMR checkout's assets/ next to the repository
#   when developing, the program's own assets/ folder when installed.

import pathlib

from ..paths import robot_assets_dir

HERE = pathlib.Path(__file__).parent
IK_CONFIG_ROOT = HERE / "ik_configs"
ASSET_ROOT = pathlib.Path(robot_assets_dir())

ROBOT_XML_DICT = {
    "unitree_g1": ASSET_ROOT / "unitree_g1" / "g1_mocap_29dof.xml",
    "unitree_g1_with_hands": ASSET_ROOT / "unitree_g1" / "g1_mocap_29dof_with_hands.xml",
}

IK_CONFIG_DICT = {
    # offline data
    "smplx": {
        "unitree_g1": IK_CONFIG_ROOT / "smplx_to_g1.json",
        "unitree_g1_with_hands": IK_CONFIG_ROOT / "smplx_to_g1.json",
    },
    "bvh_lafan1": {
        "unitree_g1": IK_CONFIG_ROOT / "bvh_lafan1_to_g1.json",
        "unitree_g1_with_hands": IK_CONFIG_ROOT / "bvh_lafan1_to_g1.json",
    },
    "bvh_nokov": {
        "unitree_g1": IK_CONFIG_ROOT / "bvh_nokov_to_g1.json",
    },
    "bvh_xsens": {
        "unitree_g1": IK_CONFIG_ROOT / "bvh_xsens_to_g1.json",
    },
    "fbx": {
        "unitree_g1": IK_CONFIG_ROOT / "fbx_to_g1.json",
        "unitree_g1_with_hands": IK_CONFIG_ROOT / "fbx_to_g1.json",
    },
    "fbx_offline": {
        "unitree_g1": IK_CONFIG_ROOT / "fbx_offline_to_g1.json",
    },
    "xrobot": {
        "unitree_g1": IK_CONFIG_ROOT / "xrobot_to_g1.json",
    },
    "xsens_mvn": {
        "unitree_g1": IK_CONFIG_ROOT / "xsens_mvn_to_g1.json",
    },
}

ROBOT_BASE_DICT = {
    "unitree_g1": "pelvis",
    "unitree_g1_with_hands": "pelvis",
}
