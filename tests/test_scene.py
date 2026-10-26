"""The shared motion scene (retlens/app/scene.py) without any front end."""

import os
import socket
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens.app.scene import DEFAULT_URDF, MotionScene, SceneOptions, load_robot_urdf  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "samples", "synthetic_g1_walk.npz")
pytestmark = pytest.mark.skipif(not (os.path.isfile(DEFAULT_URDF) and os.path.isfile(SAMPLE)),
                                reason="needs the GMR G1 assets and data/samples (tools/make_samples.py)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    import viser

    server = viser.ViserServer(host="127.0.0.1", port=_free_port(), verbose=False)
    sc = MotionScene(server, load_robot_urdf(DEFAULT_URDF, 0.02, log=lambda *_: None),
                     SceneOptions(video_dir=str(tmp_path_factory.mktemp("videos"))), log=lambda *_: None)
    yield sc
    sc.runner.shutdown()
    server.stop()


def test_add_play_measure_remove(scene):
    events = []
    scene.listen(lambda e, p: events.append(e))
    a = scene.add(SAMPLE)
    b = scene.add(SAMPLE)
    assert b.label.endswith("(2)") and a.color != b.color and "items" in events
    lo, hi = scene.time_range()
    assert lo == 0.0 and abs(hi - a.robot.duration) < 1e-6

    scene.set_offset(b, 0.5)
    assert scene.time_range()[1] == pytest.approx(b.robot.duration + 0.5)
    scene.set_playing(True)
    scene.tick(0.2)
    assert scene.t == pytest.approx(0.2)
    scene.view.side_by_side = True
    scene.tick(0.0)
    ya, yb = a.handles["pos"][1], b.handles["pos"][1]
    assert yb - ya == pytest.approx(-scene.view.spacing, abs=1e-6)  # second lane
    assert len(scene.robots.handles) == len(scene.robots.meshes) and scene.robots.colors == [a.color, b.color]
    assert set(scene.overlays.handles) == {"support", "com", "zmp"}  # robot npz inputs have no skeleton
    assert list(scene.overlays.handles["com"].batched_scales) == [1.0, 1.0]  # both show their CoM
    scene.set_visible(a, False)
    scene.tick(0.0)
    assert scene.robots._scales[:, 0].max() == 0.0 and scene.robots._scales[:, 1].min() == 1.0  # hidden robot scaled away
    scene.set_visible(a, True)

    keys = scene.graph_keys()
    assert keys[0].startswith("골반 높이") and any("knee" in k for k in keys)
    series = scene.series(keys[0])
    assert len(series) == 2 and np.allclose(series[1][1][0], 0.5)  # b's time axis starts at its offset
    names, cols = scene.metric_table(a)
    assert len(names) == len(cols[0][1]) and cols[0][1][0] == "기구학" and cols[0][1][names.index("기준 대비 다리 RMSE (°)")] == "기준"
    assert dict(scene.item_facts(a))["QC"] in ("PASS", "WARN", "FAIL")
    assert cols[0][1][names.index("리타게팅 점수")] == "-"  # a robot motion: no human to compare with

    scene.view.robot_translucent = True
    scene.view_changed("robot_translucent")
    scene.tick(0.0)
    scene.remove(a)
    assert scene.items == [b] and b.handles["index"] == 0 and scene.robots.colors == [b.color]
    scene.remove(b)
    assert scene.items == [] and scene.robots.handles == []


def test_retarget_settings_apply_to_motions_opened_next(scene, tmp_path, monkeypatch):
    """리타게팅 보정 (RetLens's 리타게팅 menu, the viewer's checkboxes, /api/retarget): human
    motions opened after a change are retargeted with it, each setting in its own cache entry;
    the motions already open keep how they were made."""
    from retlens import compare

    monkeypatch.setattr(compare, "CACHE", str(tmp_path))  # not the user's retarget cache
    bvh = os.path.join(os.path.dirname(SAMPLE), "synthetic_walk.bvh")
    off = {"smooth_hz": 6.0, "foot_flat": False, "swing_clearance_cm": 0.0}
    assert scene.retarget_settings() == off
    plain = scene.add(bvh)
    events = []
    scene.listen(lambda e, p: events.append(e))
    assert scene.set_retarget(foot_flat=True, swing_clearance_cm=2.0) == {**off, "foot_flat": True, "swing_clearance_cm": 2.0}
    assert "status" in events  # front ends redraw their controls
    flat = scene.add(bvh)
    try:
        assert plain.retarget == off and plain.info["foot_flat"] is None and "foot-flat" not in plain.kind
        assert flat.retarget == scene.retarget_settings() and isinstance(flat.info["foot_flat"], dict)
        assert flat.kind.endswith("smooth 6 Hz, foot-flat, swing >= 2 cm") and flat.label.endswith("(2)")
        assert len([f for f in os.listdir(tmp_path) if f.endswith(".npz")]) == 2  # one cache entry per setting
        assert "디딤발 평평" in dict(scene.item_facts(flat)) and "디딤발 평평" not in dict(scene.item_facts(plain))
        names, cols = scene.metric_table(None)  # 리타게팅 점수: human inputs only
        row = names.index("리타게팅 점수")
        assert all(v[row] == it.metrics["retarget_grade"] != "-" for it, v in cols)
        assert "리타게팅 점수" in dict(scene.item_facts(plain)) and "많이 어긋난 부위" in dict(scene.item_facts(plain))
        with pytest.raises(ValueError):
            scene.set_retarget(swing_clearance_cm=-1.0)
        assert scene.set_retarget(foot_flat=False)["swing_clearance_cm"] == 2.0  # each setting on its own
    finally:
        scene.set_retarget(foot_flat=False, swing_clearance_cm=0.0)
        scene.remove(plain)
        scene.remove(flat)


def test_overlay_comparison(scene):
    """겹쳐 비교: B on A's pelvis, A a ghost, only B's parts beyond the tolerance drawn and coloured."""
    from retlens.app.robots import REGIONS
    from retlens.app.scene import GHOST_COLOR, diff_colors

    assert set(scene.robots.part_regions) == set(REGIONS)  # every G1 part has a body region
    assert diff_colors(np.array([3.0, 9.0, 30.0]), 3.0).tolist() == [[245, 205, 40], [220, 40, 35], [220, 40, 35]]
    scene.view.robot_translucent = False
    a = scene.add(SAMPLE)
    b = scene.add(SAMPLE)
    scene.set_compare(on=True, ref=a, item=b, tol_cm=3.0)
    assert scene.compare_pair() == (0, 1) and scene.compare_role(b) == "B"
    assert scene.robots.colors[0] == GHOST_COLOR and scene.robots._opac == (0.3, 1.0)
    scene.seek(0.6)
    scene.tick(0.0)
    now = scene.compare_now
    assert now["mean"] < 1e-6 and now["over"] == 0  # the same motion: nothing differs
    assert scene.robots._scales[:, 1].max() == 0.0 and scene.robots._scales[:, 0].min() == 1.0  # B hidden, A ghost
    assert "비교 기준" in a.handles["label_text"] and "비교 대상" in b.handles["label_text"]

    scene.set_offset(b, 0.4)  # same motion 0.4 s later: limbs differ, the pelvis is put on A's
    scene.tick(0.0)
    now = scene.compare_now
    assert now["over"] > 0 and now["worst"] in REGIONS
    pelvis = scene.robots.part_names.index(scene.robots.links[0])
    assert scene.robots._scales[pelvis, 1] == 0.0  # the pelvis itself lines up
    shown = scene.robots._scales[:, 1] > 0
    assert (scene.robots._sent_colors[shown, 1] != np.array(b.color, np.uint8)).any(axis=-1).all()  # painted
    s = scene.compare_series()
    assert len(s["t"]) and s["t"][0] == pytest.approx(0.4) and s["parts"].shape[1] == len(scene.robots.meshes)
    assert s["mean"].max() > 0.5 and set(s["regions"]) == set(REGIONS)
    rows = scene.compare_table()
    assert rows[0][0].startswith("전체") and len(rows) == 1 + len(REGIONS)

    scene.set_compare(on=False)
    scene.tick(0.0)
    assert scene.robots._opac is None and scene.robots._sent_colors is None and scene.compare_now is None
    assert scene.robots.colors == [a.color, b.color]
    scene.remove(a)
    scene.remove(b)


def test_balance_modes(scene, tmp_path):
    """균형 제어 in physics mode: MuJoCo runs (here a stand-in simulation) in the background, shown,
    measured and labelled per mode; every mode's result is kept, so switching back is instant."""
    import time

    from retlens import policy_replay as pr
    from retlens.policy_runner import PolicyRunner

    root = tmp_path / "GMT"
    for p in pr.gmt_paths(str(root)).values():
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("stand-in")
    calls = []

    def sim(motion, controller, progress):  # the reference at 50 Hz; "pd" falls twice
        calls.append(controller)
        progress(0, 1)
        n = int(round(motion.duration * 50)) + 1
        idx = np.clip(np.round(np.arange(n) / 50 * motion.fps).astype(int), 0, motion.num_frames - 1)
        col = [motion.joint_names.index(j) for j in pr.GMT_DOFS]
        falls = [0.5, 1.5] if controller == "pd" else []
        return pr.Result(controller, np.arange(n) / 50, motion.root_pos[idx], motion.root_quat[idx],
                         motion.dof_pos[idx][:, col],
                         {"controller": controller, "falls": len(falls), "fall_times_s": falls,
                          "fall_causes": ["tilt", "drop"][:len(falls)], "hold_falls": 0, "hold_fall_times_s": [],
                          "body_error_cm": 9.0 if controller == "pd" else 4.0, "torque_saturated_ratio": 0.2})

    def wait(item, key):
        end = time.time() + 30
        while key not in item.handles.get("phys", {}) and time.time() < end:
            time.sleep(0.02)
        return item.handles["phys"][key]

    old = scene.policy
    scene.policy = PolicyRunner(str(tmp_path / "policy"), gmt_root=str(root), simulate=sim, log=lambda *_: None)
    scene.policy.problem = lambda controller: ""  # the stand-in needs neither MuJoCo nor PyTorch
    try:
        a = scene.add(SAMPLE)
        scene.set_balance("pd")
        assert scene.phys_key == "pd" and scene.mode_label() == "없음 (MuJoCo)" and scene.balance_problem("pd") == ""
        scene.set_physics(True, "test")  # no Isaac needed
        pd = wait(a, "pd")
        assert scene.shown(a) is pd and scene.is_policy_result(pd) and not scene.runner.busy()
        assert scene.falls(a) == [(0.5, "기울어짐"), (1.5, "원본보다 낮음")]
        assert scene.job_text(a) == "완료 · 넘어짐 2 · 몸 위치 오차 9.0 cm · 토크 한계 초과 20.0%"
        assert scene.physics_status() == "물리 모드: 없음 (MuJoCo) · 넘어짐 2회 · 몸 위치 오차 9.0 cm"
        names, cols = scene.metric_table(None)
        vals = dict(zip(names, cols[0][1]))
        assert vals["재생 방식"] == "MuJoCo · 없음" and vals["물리: 넘어짐"] == "2" and vals["물리: 몸 위치 오차 (cm)"] == "9.0"
        assert vals["물리 판정"] == "넘어짐 2회" and vals["물리: 보조 힘 (체중 %)"] == "0.0"
        scene.seek(0.6)
        scene.tick(0.0)
        assert a.handles["label_text"].endswith(" · MuJoCo 제어 없음 · 넘어짐 2회 · 몸 오차 9.0 cm · 넘어짐 0.50s · 기울어짐")

        scene.set_balance("gmt")
        gmt = wait(a, "gmt")
        scene.tick(0.0)
        assert scene.shown(a) is gmt and scene.falls(a) == [] and " · GMT · 넘어짐 0회 · 몸 오차 4.0 cm" in a.handles["label_text"]
        scene.set_balance("pd")  # kept: no new run
        assert scene.shown(a) is pd and calls == ["pd", "gmt"]
        assert [m for m, _ in scene.results_overview(a)] == ["없음 (MuJoCo)", "추적 정책 (GMT)"]
        b = scene.add(SAMPLE)  # added while physics mode is on: computed in the current mode (same motion: cached)
        assert wait(b, "pd") is not pd and calls == ["pd", "gmt"]
        scene.set_physics(False, "test")
        assert scene.shown(a) is a and scene.physics_status() == "물리 모드: 꺼짐"
    finally:
        scene.set_physics(False, "test")
        scene.set_balance("isaac")
        for it in list(scene.items):
            scene.remove(it)
        scene.policy.shutdown()
        scene.policy = old


def test_batched_kinematics_match_the_urdf(scene):
    """RobotBatch's numpy forward kinematics against yourdfpy, link by link."""
    urdf, rb = scene.urdf, scene.robots
    rng = np.random.default_rng(0)
    cfg = rng.uniform(-0.8, 0.8, (3, len(rb.joint_names)))
    T_base = np.tile(np.eye(4), (3, 1, 1))
    T_base[1, :3, 3] = [0.3, -1.0, 0.8]
    T = rb.forward(T_base, cfg)
    for k in range(3):
        urdf.update_cfg(cfg[k])
        for li, link in enumerate(rb.links):
            ref = T_base[k] @ urdf.get_transform(link, urdf.base_link)
            assert np.allclose(T[li, k], ref, atol=1e-9), link
