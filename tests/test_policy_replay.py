"""Balance on / off in MuJoCo (retlens/policy_replay.py, tools/policy_replay.py): the numpy port of
GMT's reference sampling, and - with GMT installed (scripts/install_gmt.ps1) - that the tracking
policy keeps the G1 up where the open-loop PD replay falls, and that every fall gets its first cause."""

import json
import os
import sys

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from retlens import policy_replay as pr  # noqa: E402


def _gmt():
    pytest.importorskip("mujoco")  # the policy itself runs in numpy (retlens/gmt_policy.py)
    try:
        return pr.gmt_files()
    except FileNotFoundError as e:
        pytest.skip(str(e))


def test_quaternion_helpers_match_scipy():
    rng = np.random.default_rng(0)
    a, b = R.random(50, random_state=1), R.random(50, random_state=2)
    qa, qb = a.as_quat(), b.as_quat()  # scipy is xyzw, like GMT
    assert np.allclose(np.abs(np.sum(pr.quat_mul(qa, qb) * (a * b).as_quat(), axis=1)), 1.0)
    v = rng.normal(size=(50, 3))
    assert np.allclose(pr.quat_rotate_inverse(qa, v), a.inv().apply(v))
    d = (b * a.inv())
    assert np.allclose(pr.quat_to_exp_map(pr.quat_mul(qb, pr.quat_conj(qa))), d.as_rotvec(), atol=1e-9)
    assert np.allclose(pr.slerp(qa, qb, np.zeros(50)), qa) and np.allclose(np.abs(np.sum(pr.slerp(qa, qb, np.ones(50)) * qb, 1)), 1)
    roll, pitch = pr.roll_pitch_xyzw(qa)
    eul = a.as_euler("xyz")  # extrinsic xyz = GMT's roll / pitch / yaw convention
    assert np.allclose(roll, eul[:, 0]) and np.allclose(pitch, eul[:, 1])
    assert np.allclose(pr.matrix_xyzw(qa), a.as_matrix())  # the harness's orientation spring
    small = d.as_rotvec()
    keep = np.linalg.norm(small, axis=1) < np.pi - 1e-3
    assert np.allclose(pr.log_rot(pr.matrix_xyzw(qb) @ np.swapaxes(pr.matrix_xyzw(qa), -1, -2))[keep], small[keep],
                       atol=1e-6)


def test_harness_holds_up_the_open_loop_replay():
    """The pelvis harness (tools/isaac_replay.py's, in MuJoCo): where the open-loop PD replay falls, it holds
    the robot up and says how hard it pulls; standing still it hardly pulls."""
    files = _gmt()
    import policy_replay as tool

    ref = pr.Reference.from_motion(tool.gmt_sample("squat"))
    pd = pr.run(pr.G1Sim(files["model"], "pd"), ref, hold_s=0.5).metrics
    sim = pr.G1Sim(files["model"], "harness")
    m = pr.run(sim, ref, hold_s=0.5).metrics
    assert pd["falls"] >= 1 and "harness_force_per_body_weight" not in pd
    assert m["falls"] == 0 and 0.0 < m["harness_force_per_body_weight"]["mean"] < 0.5
    assert m["robot_mass_kg"] > 30 and isinstance(m["consistent"], bool) and isinstance(m["issues"], list)
    robot = sim.model.geom_bodyid != 0  # the robot's parts pass through each other, as in the Isaac replay
    assert set(sim.model.geom_contype[robot & (sim.model.geom_contype != 0)]) <= {2}

    n, fps = 60, 30.0  # standing in the default pose
    pos = np.tile([0.0, 0.0, 0.793], (n, 1))
    still = pr.Reference(pos, np.tile([0.0, 0.0, 0.0, 1.0], (n, 1)), np.tile(pr.GMT_DEFAULT, (n, 1)), fps)
    v, w = still.harness_velocity([0.5, still.length + 1.0])
    assert not np.any(v) and not np.any(w)
    stand = pr.run(pr.G1Sim(files["model"], "harness"), still, hold_s=0.0).metrics
    assert stand["falls"] == 0 and stand["harness_force_per_body_weight"]["mean"] < 0.05


def test_reference_sampling():
    n, fps = 90, 30.0
    pos = np.stack([np.arange(n) / fps, np.zeros(n), np.full(n, 0.78)], axis=1)  # 1 m/s forward
    rot = np.tile([0.0, 0.0, 0.0, 1.0], (n, 1))
    dof = np.tile(pr.GMT_DEFAULT, (n, 1))
    ref = pr.Reference(pos, rot, dof, fps)
    assert np.allclose(ref.root_vel[20:-20, 0], 1.0)  # finite difference, box-filtered
    assert ref.root_vel[0, 0] < 0.6  # GMT's zero padding fades the ends
    p, q, v, w, _, dv = ref.frame([ref.length + 5.0])  # past the end: holds the last frame, standing still
    assert np.allclose(p[0], pos[-1]) and np.allclose(q[0], rot[-1])
    assert not np.any(v) and not np.any(w) and not np.any(dv) and not np.any(ref.pd_velocity([ref.length + 1.0]))
    v0, _, _ = ref.start_velocities(0.0)  # a restart moves at the clip's real speed, not the faded estimate
    assert np.isclose(v0[0], 1.0) and not np.any(ref.start_velocities(ref.length + 0.5)[0])
    obs = ref.mimic_obs(0)
    assert obs.shape == (600,)  # 20 future frames x (z, roll, pitch, lin vel 3, yaw rate, 23 DoF)
    assert np.isclose(obs[0], 0.78) and np.isclose(obs[3], ref.root_vel[0, 0])  # first target: 0.02 s ahead


def test_gmt_port_matches_the_authors_closed_loop():
    """From GMT's own start (keyframe 'home') on its walk_stand example, the authors' sim2sim.py
    reaches this root position after 1 s (checked 2026-10-21, MuJoCo 3.11, CPU); our port matched it
    exactly, joint for joint, up to 3 s."""
    files = _gmt()
    import policy_replay as tool

    m = tool.gmt_sample("walk_stand")
    xyzw = np.concatenate([m.root_quat[:, 1:], m.root_quat[:, :1]], axis=1)
    ref = pr.Reference(m.root_pos, xyzw, m.dof_pos, m.fps, loop=True)
    sim = pr.G1Sim(files["model"], "gmt", policy_path=files["policy"])
    pr.run(sim, ref, home=True, duration_s=1.0)
    assert np.allclose(sim.data.qpos[:3], [0.173, -0.172, 0.777], atol=5e-3)


def test_gmt_balances_where_open_loop_pd_falls(tmp_path):
    files = _gmt()
    import policy_replay as tool
    from retlens.compare import load_item

    m = tool.gmt_sample("squat")
    ref = pr.Reference.from_motion(m)
    out = {}
    for c in pr.CONTROLLERS:
        res = pr.run(pr.G1Sim(files["model"], c, policy_path=files["policy"]), ref, hold_s=0.5)
        out[c] = res.metrics
        path = pr.save_result(res, str(tmp_path / f"squat_{c}_sim.npz"), m.joint_names,
                              {"label": "gmt_samples/squat", "controller_label": pr.LABELS[c]})
        item = load_item(path)
        assert item.kind.startswith("MuJoCo 재생") and item.robot.num_frames == len(res.times)
    assert out["gmt"]["falls"] == 0 and out["gmt"]["body_error_cm"] < 5.0
    assert out["pd"]["falls"] >= 1  # no balance feedback: even the authors' clean example falls
    assert out["pd"]["joint_rmse_deg"] < out["gmt"]["joint_rmse_deg"]  # the policy bends the joints to stay up
    summary = tool.write_summary(str(tmp_path))
    with open(summary, encoding="utf-8") as f:
        text = f.read()
    assert summary.endswith("summary.md") and "| 넘어짐 원인 |" in text


def test_every_fall_gets_its_first_cause(monkeypatch):
    """The diagnosis lines up with the falls and their rules (in the clip and in the hold), the recording
    changes nothing else, and a diagnosis that fails leaves the run and its rules as they were."""
    files = _gmt()
    import policy_replay as tool
    from retlens import diagnosis

    ref = pr.Reference.from_motion(tool.gmt_sample("squat"))
    m = pr.run(pr.G1Sim(files["model"], "pd"), ref, hold_s=0.5).metrics
    diags, hold = m["fall_diagnosis"], m["hold_fall_diagnosis"]
    assert m["falls"] >= 1 and len(diags) == m["falls"] and "fall_diagnosis_error" not in m
    assert [d["fall_time_s"] for d in diags] == m["fall_times_s"] and [d["rule"] for d in diags] == m["fall_causes"]
    assert [d["fall_time_s"] for d in hold] == m["hold_fall_times_s"]
    assert [d["rule"] for d in hold] == m["hold_fall_causes"]
    assert m["first_fall_cause"] == diags[0]["primary_cause"]
    assert all(d["primary_cause"] in diagnosis.CAUSES + ("undetermined",) for d in diags + hold)
    assert all(d["primary_cause"] != "harness_spike" for d in diags)  # no harness in "pd"
    assert json.loads(json.dumps(m)) == m  # plain json: save_result writes it as it is

    def rest(x):
        return {k: v for k, v in x.items()
                if k not in ("first_fall_cause", "fall_diagnosis", "hold_fall_diagnosis", "fall_diagnosis_error")}

    with monkeypatch.context() as mp:
        mp.setattr(pr.FallProbe, "sample", lambda self, *a, **k: None)  # nothing recorded
        bare = pr.run(pr.G1Sim(files["model"], "pd"), ref, hold_s=0.5).metrics
    assert rest(bare) == rest(m)  # the falls, their times and every other number are the run's own
    assert bare["fall_diagnosis"] == [] and bare["first_fall_cause"] is None and bare["fall_diagnosis_error"]

    def broken(*a, **k):
        raise ValueError("broken diagnosis")

    monkeypatch.setattr(diagnosis, "diagnose_falls", broken)
    failed = pr.run(pr.G1Sim(files["model"], "pd"), ref, hold_s=0.5).metrics
    assert failed["fall_diagnosis_error"] == "ValueError: broken diagnosis" and rest(failed) == rest(m)
    assert failed["fall_diagnosis"] == [] and failed["hold_fall_diagnosis"] == [] and failed["first_fall_cause"] is None


def test_fall_probe_samples_each_tick(monkeypatch):
    """The probe: per tick 2 feet x 4 sole points and the feet's floor forces (which carry the robot's weight
    while it stands in the harness, which pulls sideways only), and the signals diagnose_falls takes."""
    files = _gmt()
    probes = []

    class Keep(pr.FallProbe):
        def __init__(self, sim):
            super().__init__(sim)
            probes.append(self)

    monkeypatch.setattr(pr, "FallProbe", Keep)
    n, fps = 60, 30.0
    still = pr.Reference(np.tile([0.0, 0.0, 0.793], (n, 1)), np.tile([0.0, 0.0, 0.0, 1.0], (n, 1)),
                         np.tile(pr.GMT_DEFAULT, (n, 1)), fps)
    sim = pr.G1Sim(files["model"], "harness")
    m = pr.run(sim, still, hold_s=0.5).metrics
    assert m["falls"] == 0 and m["fall_diagnosis"] == [] and m["first_fall_cause"] is None
    assert m["hold_fall_causes"] == [] and "fall_diagnosis_error" not in m
    rec = {k: np.array(v) for k, v in probes[-1].rec.items()}
    T = int(round((still.length + 0.5) / pr.CONTROL_DT))
    assert rec["soles"].shape == rec["ref_soles"].shape == (T, 2, 4, 3) and rec["force"].shape == (T, 2)
    assert np.allclose(rec["force"][10:].sum(1), sim.weight, rtol=0.1)
    assert np.abs(rec["soles"][10:, ..., 2]).max() < 0.01  # standing: the sole points on the floor
    centres = rec["soles"].mean(2)  # (T, 2, 3): the feet's ankle links lie above these, mirrored
    assert np.allclose(rec["feet_m"][10:], np.linalg.norm(centres[10:, 0] - centres[10:, 1], axis=1), atol=0.03)
    sig = probes[-1].signals([])
    assert sig.assist == 1.0 and sig.harness.shape == (T,) and sig.tau_ratio.shape == (T, len(pr.GMT_DOFS))
    assert np.isfinite(sig.sim_track.com_margin[10:]).all() and sig.ref_track is not None
    pd = pr.G1Sim(files["model"], "pd")
    pr.run(pd, still, duration_s=0.2)
    sig = probes[-1].signals([3])
    assert sig.assist == 0.0 and sig.harness is None and len(sig.soles) == 10
    made = len(probes)
    assert pr.run(pd, still, home=True, duration_s=0.1).metrics["fall_diagnosis"] == [] and len(probes) == made
