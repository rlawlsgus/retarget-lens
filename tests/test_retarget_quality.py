"""Retargeting quality (khumanoid/retarget_quality.py) and the per-robot benchmark
(tools/retarget_benchmark.py)."""

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from khumanoid import retarget_quality as rq  # noqa: E402
from khumanoid.motion import RobotMotion  # noqa: E402

BVH = os.path.join(ROOT, "data", "samples", "synthetic_walk.bvh")


def test_score_rules():
    assert rq.score({}) == (100.0, [])  # nothing measured, nothing lost
    s, lost = rq.score({"pose_err_deg": 25.0, "self_collision_pct": 5.0, "joint_limit_pct": float("nan")})
    assert s == 70.0 and lost == [("pose_err_deg", 30.0)]  # at the 'bad' end: the full 30; at 'ok': nothing
    s, _ = rq.score({"pose_err_deg": 16.5, "contact_mismatch_pct": 100.0})
    assert s == pytest.approx(100 - 15 - 20)  # halfway: half the points; capped at the full penalty
    assert [rq.grade(x) for x in (95, 85, 84.6, 84.4, 70, 69.6, 10)] == ["좋음", "좋음", "좋음", "보통", "보통", "보통", "나쁨"]
    for s in np.arange(60.0, 100.0, 0.05):  # the grade goes with the score as shown ("85 (좋음)", never "85 (보통)")
        assert rq.grade(s) == rq.grade(float(f"{s:.0f}"))
    assert set(rq.SCORE_LABELS) == {k for k, *_ in rq.SCORE_RULES}


@pytest.fixture(scope="module")
def g1():
    pytest.importorskip("mujoco")
    from khumanoid.retarget import robot_model, unavailable

    if unavailable("unitree_g1"):
        pytest.skip(unavailable("unitree_g1"))
    return robot_model("unitree_g1")


def test_self_collision(g1):
    """The upper arm pressed into the torso is a collision; the zero pose has none."""
    fk = rq._RobotFK(g1)
    q = np.zeros((2, len(fk.joint_names)))
    i = fk.joint_names.index("left_shoulder_roll_joint")
    q[1, i] = fk.lo[i]  # the arm across the chest, as far as the joint goes
    m = RobotMotion("t", fk.joint_names, np.tile([0.0, 0.0, 0.8], (2, 1)), np.tile([1.0, 0, 0, 0], (2, 1)), q, 30.0)
    _, _, hits = fk.run(m, [1])
    assert hits[0] == set()
    assert any("torso_link" in (fk.name(a), fk.name(b)) for a, b in hits[1])


@pytest.mark.skipif(not os.path.isfile(BVH), reason="needs data/samples (tools/make_samples.py)")
def test_measure_a_retarget(g1, tmp_path, monkeypatch):
    """A retarget scores against its own human skeleton; the same skeleton played 0.3 s off
    points elsewhere (the pose error measures fidelity), and a robot without the T-pose tables
    is not measured."""
    from khumanoid import analysis, compare

    monkeypatch.setattr(compare, "CACHE", str(tmp_path))  # not the user's retarget cache
    item = compare.load_item(BVH, smooth=6.0, log=None)
    compare.compute_metrics(item, analysis.FootKinematics(), rq.model_limits(g1))
    m = item.metrics
    assert 0 <= m["retarget_score"] <= 100 and m["retarget_grade"].endswith(f"({rq.grade(m['retarget_score'])})")
    assert m["pose_err_deg"] < 15 and 0 <= m["contact_mismatch_pct"] <= 100
    assert set(m["_quality"]["segments_deg"]) == {"왼 허벅지", "왼 정강이", "왼 위팔", "왼 아래팔", "오른 허벅지", "오른 정강이",
                                                  "오른 위팔", "오른 아래팔", "몸통"}
    h = item.human
    late = type(h)(name=h.name, joint_names=h.joint_names, parents=h.parents, fps=h.fps,
                   positions=np.roll(h.positions, int(0.3 * h.fps), axis=0))
    assert rq.measure(late, item.robot, "unitree_g1", g1)["pose_err_deg"] > m["pose_err_deg"] + 3
    assert rq.measure(h, item.robot, "some_other_robot", g1) == {}


@pytest.mark.skipif(not os.path.isfile(BVH), reason="needs data/samples (tools/make_samples.py)")
def test_benchmark_report(g1, tmp_path, monkeypatch):
    """tools/retarget_benchmark.py: per-robot summary and per-clip rows; a robot it cannot
    measure is skipped, not scored."""
    import retarget_benchmark

    from khumanoid import compare

    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "cache"))
    out = tmp_path / "report"
    code = retarget_benchmark.main([BVH, os.path.join(ROOT, "data", "samples", "synthetic_g1_walk.npz"),
                                    "--robot", "unitree_g1", "--robot", "no_such_robot", "--out", str(out)])
    assert code == 0
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [c["clip"] for c in res["clips"]] == ["data/samples/synthetic_walk.bvh"]  # the robot npz is no human motion
    assert set(res["summary"]) == {"unitree_g1"} and res["summary"]["unitree_g1"]["scored"] == 1
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "| unitree_g1 | 1 |" in md and "synthetic_walk.bvh" in md
