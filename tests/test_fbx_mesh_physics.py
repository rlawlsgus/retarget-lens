"""FBX reading (through Blender), skeleton-name handling, SMPL-X body mesh and the
physics-result labels. Tests that need Blender, the downloaded clips or the
licence-gated body model skip when those are missing."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from khumanoid.compare import Item, _issue_ko, compute_metrics  # noqa: E402
from khumanoid.retarget import _resolve_bvh_bodies, detect_format  # noqa: E402
from khumanoid.synthetic import g1_motion  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")
MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")


def _blender() -> bool:
    from khumanoid.io.fbx import find_blender

    try:
        find_blender()
        return True
    except FileNotFoundError:
        return False


def _chain(spec):
    """[(name, parent name)] -> names, parents."""
    names = [n for n, _ in spec]
    return names, np.array([names.index(p) if p else -1 for _, p in spec])


def test_daz_mixamo_and_motive_skeletons_resolve():
    daz = [("hip", None), ("abdomen", "hip"), ("chest", "abdomen"), ("neck", "chest"), ("head", "neck")]
    daz += [(f"{s}Collar", "chest") for s in "lr"] + [(f"{s}Shldr", f"{s}Collar") for s in "lr"]
    daz += [(f"{s}ForeArm", f"{s}Shldr") for s in "lr"] + [(f"{s}Hand", f"{s}ForeArm") for s in "lr"]
    daz += [(f"{s}Buttock", "hip") for s in "lr"] + [(f"{s}Thigh", f"{s}Buttock") for s in "lr"]
    daz += [(f"{s}Shin", f"{s}Thigh") for s in "lr"] + [(f"{s}Foot", f"{s}Shin") for s in "lr"]
    names, parents = _chain(daz)
    idx = _resolve_bvh_bodies(names, parents)
    assert names[idx["Hips"]] == "hip" and names[idx["Spine2"]] == "chest"
    assert names[idx["LeftUpLeg"]] == "lThigh" and names[idx["RightHand"]] == "rHand"

    mixamo = [("Hips", None), ("Spine", "Hips"), ("Spine1", "Spine"), ("Spine2", "Spine1")]
    for S in ("Left", "Right"):
        mixamo += [(f"{S}Shoulder", "Spine2"), (f"{S}Arm", f"{S}Shoulder"), (f"{S}ForeArm", f"{S}Arm"),
                   (f"{S}Hand", f"{S}ForeArm"), (f"{S}UpLeg", "Hips"), (f"{S}Leg", f"{S}UpLeg"),
                   (f"{S}Foot", f"{S}Leg")]
    names, parents = _chain([("mixamorig:" + n, p and "mixamorig:" + p) for n, p in mixamo])
    idx = _resolve_bvh_bodies(names, parents)
    assert names[idx["Spine2"]] == "mixamorig:Spine2" and names[idx["LeftFoot"]] == "mixamorig:LeftFoot"

    motive = [("Hip", None), ("Ab", "Hip"), ("Chest", "Ab")]
    for s in "LR":
        motive += [(f"{s}Shoulder", "Chest"), (f"{s}UArm", f"{s}Shoulder"), (f"{s}FArm", f"{s}UArm"),
                   (f"{s}Hand", f"{s}FArm"), (f"{s}Thigh", "Hip"), (f"{s}Shin", f"{s}Thigh"), (f"{s}Foot", f"{s}Shin")]
    names, parents = _chain([("Skeleton1_" + n, p and "Skeleton1_" + p) for n, p in motive])
    idx = _resolve_bvh_bodies(names, parents)
    assert names[idx["Spine2"]] == "Skeleton1_Chest" and names[idx["RightArm"]] == "Skeleton1_RUArm"


def test_fbx_is_its_own_format(tmp_path):
    p = tmp_path / "clip.fbx"
    p.write_bytes(b"Kaydara FBX Binary  \x00")
    assert detect_format(str(p)) == "fbx"


@pytest.mark.skipif(not (_blender() and os.path.isfile(os.path.join(RAW, "cmu_fbx_from_bvh", "02_03.fbx"))),
                    reason="needs Blender (docs/setup.md) and data/raw/cmu_fbx_from_bvh")
def test_fbx_round_trip_matches_bvh():
    """BVH -> FBX (Blender) -> load_fbx gives the BVH's joints back (Z-up meters, same frames)."""
    from khumanoid.io.bvh import load_bvh
    from khumanoid.io.fbx import load_fbx

    b = load_bvh(os.path.join(RAW, "cmu_bvh", "02_03.bvh"), include_end_sites=False)
    f = load_fbx(os.path.join(RAW, "cmu_fbx_from_bvh", "02_03.fbx"))
    # BVH frame times are rounded (0.008333 s -> 120.0005 fps); the FBX keeps a whole 120
    assert abs(f.fps - b.fps) < 1e-3 * b.fps and f.num_frames == b.num_frames and f.meta["tpose_frame0"]
    common = [n for n in b.joint_names if n in f.joint_names]
    assert len(common) == len(b.joint_names)
    d = b.positions[:, [b.joint_names.index(n) for n in common]] - f.positions[:, [f.joint_names.index(n) for n in common]]
    assert np.abs(d).max() < 1e-3


@pytest.mark.skipif(not (_blender() and os.path.isfile(os.path.join(RAW, "cmu_fbx", "143_11.fbx"))),
                    reason="needs Blender and data/raw/cmu_fbx (tools/fetch_samples.py)")
def test_cmu_fbx_conversion_keeps_cgspeed_time_base_fixed():
    """The Hugging Face CMU FBX of a 60 Hz trial plays 2x fast like its cgspeed source; load_fbx corrects it."""
    from khumanoid.io.fbx import load_fbx

    f = load_fbx(os.path.join(RAW, "cmu_fbx", "143_11.fbx"))
    assert f.meta["file_fps"] == 30.0 and f.fps == 15.0 and f.meta["dropped_frames"] == 1
    assert abs(f.duration - 657 / 60) < 0.1  # AMASS / BVH: 657 frames @ 60 Hz
    height = f.positions[0, :, 2].max() - f.positions[0, :, 2].min()
    assert 1.0 < height < 2.0  # the file's centimetre numbers in a meter scene were rescaled


AMASS = os.path.join(RAW, "amass_cmu_smplx", "CMU", "02", "02_01_stageii.npz")


@pytest.mark.skipif(not (os.path.isfile(AMASS) and os.path.isfile(os.path.join(MODELS, "smplx", "SMPLX_NEUTRAL.npz"))),
                    reason="needs licence-gated AMASS CMU 02_01 and the SMPL-X body model")
def test_smplx_body_mesh_wraps_the_skeleton():
    from khumanoid.io.smpl import BodyMeshRig

    rig = BodyMeshRig(AMASS, MODELS)
    assert rig.faces.shape[1] == 3 and rig.weights.shape == (len(rig.rest), len(rig.motion.joint_names))
    for f in (0, rig.num_frames // 2):
        V, J = rig.vertices(f), rig.motion.positions[f]
        assert V[:, 2].min() < J[:, 2].min() and V[:, 2].max() > J[:, 2].max()  # skin around the joints
        assert np.linalg.norm(V.mean(0)[:2] - J[0, :2]) < 0.2  # body centred on the pelvis


def test_physics_result_metrics_and_labels():
    item = Item(label="sim", source="x_sim.npz", kind="Isaac PhysX sim", robot=g1_motion(seconds=1.0), info={
        "physics": {"consistent": False, "falls": 2, "issues": ["2 fall(s)",
                                                                "harness > 20% body weight in 48.8% of frames",
                                                                "torque limits exceeded in 3.5% of frames"],
                    "harness_force_per_body_weight": {"mean": 0.19}, "torque": {"saturated_frame_ratio": 0.035}}})
    compute_metrics(item, None, None)
    m = item.metrics
    assert m["phys_falls"] == 2 and abs(m["phys_harness_pct"] - 19.0) < 1e-9 and abs(m["phys_saturated_pct"] - 3.5) < 1e-9
    assert m["phys_ok"] == "넘어짐 2회; 보조 힘 > 체중 20%: 프레임 48.8%; 토크 한계 초과: 프레임 3.5%"
    assert _issue_ko("something else") == "something else"


def test_physics_report_fall_cause_column():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    from physics_report import causes

    def fall(cause, onset, t):
        return {"primary_cause": cause, "primary_onset_s": onset, "fall_time_s": t}

    assert causes({}) == "-"
    p = {"fall_diagnosis": [fall("toe_catch", 1.467, 2.067)]}
    assert causes(p) == "발끝 걸림 1.467s (넘어짐 2.067s)"
    p = {"fall_diagnosis": [fall("support_exit", 0.4, 1.0)] * 3 + [fall("foot_slip", 5, 6)] + [fall("support_exit", 7, 8)] * 2}
    assert causes(p).endswith("; 외 지지면 이탈 2, 발 미끄러짐 1")
