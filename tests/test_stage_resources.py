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
    assert not any(r.endswith(".pt") for r in rel)  # GMT's tracking policy is research-use only: never shipped


GMT_MODEL = os.path.join(os.path.dirname(ROOT), "GMT", "assets", "robots", "g1", "g1.xml")


@pytest.mark.skipif(not (os.path.isdir(ASSETS) and os.path.isfile(GMT_MODEL)),
                    reason="needs the GMR G1 assets and GMT (scripts/install_gmt.ps1)")
def test_installed_layout_runs_the_mujoco_balance_mode(tmp_path, monkeypatch):
    """GMT's G1 MuJoCo model is staged onto the shipped G1 meshes, so the installed program's
    "없음 (MuJoCo)" balance mode works without a GMT folder; the tracking policy stays out."""
    mujoco = pytest.importorskip("mujoco")
    import stage_resources

    from khumanoid import policy_replay, policy_runner

    out = tmp_path / "resources"
    rel = {os.path.relpath(f, out).replace(os.sep, "/") for f in stage_resources.stage(str(out))}
    assert {"assets/gmt_g1/g1.xml", "licenses/GMT-LICENSE.txt"} <= rel
    model = mujoco.MjModel.from_xml_path(str(out / "assets" / "gmt_g1" / "g1.xml"))
    assert model.nu == len(policy_replay.GMT_DOFS)
    monkeypatch.setenv("KHUMANOID_RESOURCE_DIR", str(out))  # the resource folder an installed program reads
    monkeypatch.setenv("KHUMANOID_GMT_DIR", str(tmp_path / "no_gmt"))  # as on a user's PC
    assert os.path.samefile(policy_replay.gmt_paths()["model"], out / "assets" / "gmt_g1" / "g1.xml")
    assert policy_runner.problem("pd") == ""
    assert policy_runner.problem("gmt") != ""  # no policy file here (and no PyTorch in the real build)
    # same model, same meshes: the open-loop replay comes out exactly as on GMT's own copy
    from khumanoid.synthetic import g1_motion

    ref = policy_replay.Reference.from_motion(g1_motion(seconds=1.5, fps=30.0))
    runs = [policy_replay.run(policy_replay.G1Sim(m, "pd"), ref, hold_s=0.0)
            for m in (str(out / "assets" / "gmt_g1" / "g1.xml"), GMT_MODEL)]
    assert runs[0].metrics == runs[1].metrics and (runs[0].dof_pos == runs[1].dof_pos).all()
