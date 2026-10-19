"""tools/stage_resources.py: the installed program's resource folder is complete and holds no
licence-gated data."""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

ASSETS = os.path.join(os.path.dirname(ROOT), "GMR", "assets", "unitree_g1")


@pytest.mark.skipif(not os.path.isdir(ASSETS), reason="needs the GMR checkout's G1 assets (scripts/install_gmr.ps1)")
def test_stage_resources(tmp_path):
    import stage_resources

    out = tmp_path / "resources"
    files = stage_resources.stage(str(out), samples=True)
    assert stage_resources.check(str(out)) == []  # an installed layout over it finds everything
    rel = {os.path.relpath(f, out).replace(os.sep, "/") for f in files}
    assert {"configs/physics.yaml", "assets/unitree_g1/g1_mocap_29dof.xml", "assets/unitree_g1/LICENSE",
            "isaac/tools/isaac_replay.py", "isaac/khumanoid/gmr/motion_retarget.py", "licenses/GMR-LICENSE.txt",
            "ai/retlens/SKILL.md", "docs/retlens.md", "docs/pipeline.md", "docs/cmu_motion_labels.md",
            "docs/research/mocap_survey.md"} <= rel
    assert not any(r.startswith("docs/internal/") for r in rel)  # internal project documents stay out
    assert any(r.startswith("assets/unitree_g1/meshes/") for r in rel)
    # never shipped: body models (SMPLX_*.npz / .pkl), AMASS / LAFAN1 data
    assert not any(r.endswith((".npz", ".pkl")) for r in rel)
    assert not any(k in r.lower() for r in rel for k in ("amass", "lafan1_bvh", "unitree_lafan1", "stageii"))
    assert not any("__pycache__" in r for r in rel)
