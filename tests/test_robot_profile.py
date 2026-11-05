"""Any humanoid as the robot (retlens/robot_profile.py): its legs, arms, joint roles, joint centres
and flex senses found in the model, not in tables of link names. Checked on the built-in G1 (the
parts must be the ones its hand-written GMR config names) and on a made-up robot built here that
differs from the G1 where retargeting used to depend on it: no left / right words in its names,
joint axes off the body origins, a symmetric elbow range, a wrist that turns yaw -> roll -> pitch,
no waist pitch. That robot is then retargeted, drawn from its MJCF and cached by its digest."""

import json
import os

import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CMU_02_01 = os.path.join(ROOT, "data", "raw", "cmu_bvh", "02_01.bvh")


def _need():
    from retlens.retarget import unavailable

    why = unavailable()
    if why:
        pytest.skip(why)


def toybot(path: str, elbow_range: float = 2.2, wrists: bool = True, toes: bool = False, box_feet: bool = False,
           unnamed_hands: bool = False, backwards: bool = False, knee_ref: float = 0.0) -> str:
    """A small humanoid written as MJCF: 1.0 m pelvis, 3-joint hips (the roll axis's anchor 3 cm
    off its body), knees, 2-joint ankles with four sole spheres, a yaw / roll waist, 3-joint
    shoulders, elbows straight at 0 with a symmetric range (+ bends the forearm backwards),
    wrists yaw (inside the forearm) -> roll -> pitch and a fixed hand. Bodies are named b0, b1, ...
    Variants: no wrists (the hand fixed to the forearm), jointed toes (their spheres 0.5 mm below
    the heel's), one box per sole, hands without names, everything turned to face -x, a knee
    with a reference angle."""
    import mujoco as mj

    spec = mj.MjSpec()
    spec.modelname = "toybot"
    n = [0]

    def body(parent, pos):
        b = parent.add_body(name=f"b{n[0]}", pos=pos)
        n[0] += 1
        return b

    def hinge(b, axis, rng=(-2.0, 2.0), pos=(0, 0, 0)):
        b.add_joint(name=f"q{n[0]}", type=mj.mjtJoint.mjJNT_HINGE, axis=axis, range=rng, pos=pos)

    def capsule(b, a, z):
        b.add_geom(type=mj.mjtGeom.mjGEOM_CAPSULE, size=[0.03, 0, 0], fromto=[0, 0, a, 0, 0, z])

    spec.compiler.autolimits = True
    spec.compiler.degree = False  # the ranges below are radians
    spec.compiler.boundmass, spec.compiler.boundinertia = 0.05, 1e-5  # joint holders have no geometry of their own
    base = spec.worldbody.add_body(name="base", pos=[0, 0, 1.0])
    base.add_freejoint()
    base.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.08, 0.12, 0.05])
    pelvis = base.add_body(name="turned", quat=[0, 0, 0, 1]) if backwards else base
    for s in (1.0, -1.0):
        a = body(pelvis, [0, 0.1 * s, -0.05])
        hinge(a, [0, 1, 0], (-2.4, 0.9))  # hip flexion
        r = body(a, [0.03, 0, 0])  # 3 cm ahead of the hip centre: its axis runs through the centre all the same
        hinge(r, [1, 0, 0], (-0.5, 0.5), pos=(-0.03, 0, 0))
        y = body(r, [-0.03, 0, -0.15])
        hinge(y, [0, 0, 1], (-1.0, 1.0), pos=(0, 0, 0.15))
        capsule(y, 0.1, -0.2)
        k = body(y, [0, 0, -0.25])
        hinge(k, [0, 1, 0], (0.0, 2.4))
        if knee_ref:
            k.joints[0].ref = knee_ref
        capsule(k, -0.05, -0.35)
        ap = body(k, [0, 0, -0.4])
        hinge(ap, [0, 1, 0], (-0.8, 0.5))
        foot = body(ap, [0, 0, 0])
        hinge(foot, [1, 0, 0], (-0.3, 0.3))
        if box_feet:  # bottom where the spheres' is
            foot.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.08, 0.05, 0.01], pos=[0.025, 0, -0.07])
        else:
            toe = None
            if toes:
                toe = body(foot, [0.07, 0, 0])
                hinge(toe, [0, 1, 0], (-0.5, 0.5))
            for x in (0.1, -0.05):
                for yy in (0.04, -0.04):
                    if toe is not None and x > 0:
                        toe.add_geom(type=mj.mjtGeom.mjGEOM_SPHERE, size=[0.02, 0, 0], pos=[x - 0.07, yy, -0.0605])
                    else:
                        foot.add_geom(type=mj.mjtGeom.mjGEOM_SPHERE, size=[0.02, 0, 0], pos=[x, yy, -0.06])
    waist = body(pelvis, [0, 0, 0.1])
    hinge(waist, [0, 0, 1], (-1.0, 1.0))
    chest = body(waist, [0, 0, 0.1])
    hinge(chest, [1, 0, 0], (-0.4, 0.4))
    chest.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.08, 0.14, 0.15], pos=[0, 0, 0.15])
    for s in (1.0, -1.0):
        p = body(chest, [0, 0.2 * s, 0.3])
        hinge(p, [0, 1, 0], (-3.0, 2.0))
        r = body(p, [0, 0.03 * s, 0])
        hinge(r, [1, 0, 0], (-0.3, 3.0) if s > 0 else (-3.0, 0.3))
        y = body(r, [0, 0, -0.12])
        hinge(y, [0, 0, 1], (-1.5, 1.5), pos=(0, 0, 0.12))
        capsule(y, 0.0, -0.15)
        e = body(y, [0, 0, -0.15])
        hinge(e, [0, 1, 0], (-elbow_range, elbow_range))
        if wrists:
            wy = body(e, [0, 0, -0.12])  # inside the forearm
            hinge(wy, [0, 0, 1], (-1.5, 1.5))
            capsule(wy, 0.1, -0.05)
            wr = body(wy, [0, 0, -0.1])
            hinge(wr, [1, 0, 0], (-1.0, 1.0))
            wp = body(wr, [0, 0, -0.03])
            hinge(wp, [0, 1, 0], (-1.0, 1.0))
            last, at = wp, -0.07
        else:
            capsule(e, 0.0, -0.22)
            last, at = e, -0.25
        hand = last.add_body(pos=[0, 0, at]) if unnamed_hands else body(last, [0, 0, at])  # fixed: the hand
        hand.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.03, 0.01, 0.05])
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec.to_xml())
    return path


@pytest.fixture
def toy(tmp_path):
    pytest.importorskip("mujoco")
    return toybot(str(tmp_path / "toybot.xml"))


def test_g1_parts_are_the_ones_its_gmr_config_names():
    """Found in the G1's model: the 14 IK bodies of GMR's hand-written G1 config, knees flexing +,
    elbows - (straight at +1.57), the hip / shoulder yaw as twists, the waist able to pitch."""
    _need()
    from retlens import robot_profile as rp
    from retlens.gmr import IK_CONFIG_DICT

    prof = rp.load("unitree_g1")
    with open(IK_CONFIG_DICT["bvh_lafan1"]["unitree_g1"], encoding="utf-8") as f:
        cfg = json.load(f)
    assert {e[0]: body for body, e in cfg["ik_match_table1"].items()} == prof.task_bodies()
    p = prof.parts
    assert all(p.legs[s].flex_sign == 1 and p.arms[s].flex_sign == -1 for s in rp.SIDES)
    assert 1.3 < p.arms["left"].straight < 1.7  # arm straightest about 80 deg from its zero pose (forearm forward)
    assert [prof.joint(j) for j in p.legs["left"].proximal if p.legs["left"].twist[j]] == ["left_hip_yaw_joint"]
    assert prof.joint(p.arms["right"].twist_joint) == "right_shoulder_yaw_joint"
    assert p.waist_pitch and prof.hands() == {"left": "left_rubber_hand", "right": "right_rubber_hand"}
    assert p.standing_height == pytest.approx(0.79, abs=0.01) and 1.2 < p.top_height < 1.4


def test_made_up_robot_parts_come_from_its_geometry(toy):
    """No names to go by: the legs are the chains down to the lowest geometry, the arms the other
    chains leaving the trunk sideways; the hip centre is where the hip axes meet (the roll axis's
    body is 3 cm off it); the elbow with its symmetric range flexes - (that brings the hand
    forward); the wrist yaw inside the forearm is a twist of the wrist group; the waist cannot
    pitch, so the chest's orientation weighs less."""
    from retlens import robot_profile as rp

    prof = rp.load(toy)
    p = prof.parts
    data = rp._zero_data(prof.model())
    for s, sign in (("left", 1), ("right", -1)):
        leg, arm = p.legs[s], p.arms[s]
        assert len(leg.proximal) == 3 and len(leg.distal) == 2 and len(arm.proximal) == 3 and len(arm.distal) == 3
        np.testing.assert_allclose(leg.centres["proximal"].world(data), [0, 0.1 * sign, -0.05], atol=1e-6)
        np.testing.assert_allclose(leg.centres["distal"].world(data), [0, 0.1 * sign, -0.85], atol=1e-6)
        assert leg.flex_sign == 1 and arm.flex_sign == -1 and arm.straight == pytest.approx(0, abs=0.02)
        assert arm.twist[arm.distal[0]] and not arm.twist[arm.distal[1]]  # the wrist's yaw, its roll
        assert prof.joint(arm.twist_joint) == prof.joint(arm.proximal[2])
        assert prof.body(arm.end_body) != prof.body(arm.tip_body)  # moving wrist body, fixed hand below it
        assert leg.distal_roll == leg.distal[1]
    assert not p.waist_pitch and prof.task_tables()[0][prof.body(p.chest)][2] == rp.SPINE_ROT_NO_PITCH
    assert p.standing_height == pytest.approx(0.93, abs=1e-3) and p.ankle_height == pytest.approx(0.08, abs=1e-3)
    assert len(set(prof.task_bodies().values())) == 14


def test_a_model_without_legs_says_so(tmp_path):
    pytest.importorskip("mujoco")
    import mujoco as mj

    from retlens import robot_profile as rp

    spec = mj.MjSpec()
    b = spec.worldbody.add_body(name="box", pos=[0, 0, 0.5])
    b.add_freejoint()
    b.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.1, 0.1, 0.1])
    path = tmp_path / "box.xml"
    path.write_text(spec.to_xml(), encoding="utf-8")
    with pytest.raises(rp.RobotError, match="foot"):
        rp.load(str(path)).parts


def test_g1_urdf_loads_as_a_robot():
    """A URDF is converted with MuJoCo: a free joint on its base, its fixed links kept."""
    _need()
    from retlens import paths, robot_profile as rp

    prof = rp.load(paths.robot_urdf())
    assert prof.task_bodies() == rp.load("unitree_g1").task_bodies()
    assert prof.joint_names() == rp.load("unitree_g1").joint_names()


def test_rescale_keeps_directions_at_the_robots_lengths():
    """Each segment keeps its direction at its ratio's length; the hips / shoulders go to the
    robot's place, turned with the human pelvis / chest; rotations stay."""
    from retlens.retarget import rescale_frame
    from retlens.rotations import matrix_to_quat

    q0 = np.array([1.0, 0, 0, 0])
    turn = matrix_to_quat(np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]]))  # 90 deg about z
    fr = {"Hips": [np.array([1.0, 2, 1]), turn], "LeftUpLeg": [np.array([1.0, 2.1, 0.95]), q0],
          "LeftLeg": [np.array([1.0, 2.1, 0.55]), q0], "LeftFootMod": [np.array([1.1, 2.1, 0.15]), q0]}
    out = rescale_frame(fr, {"LeftLeg": 0.5, "LeftFootMod": 2.0}, {"LeftUpLeg": ("Hips", [0.0, 0.2, 0.0])})
    np.testing.assert_allclose(out["LeftUpLeg"][0], [1.0 - 0.2, 2, 1])  # the offset turned with the pelvis
    np.testing.assert_allclose(out["LeftLeg"][0], out["LeftUpLeg"][0] + [0, 0, -0.2])
    np.testing.assert_allclose(out["LeftFootMod"][0], out["LeftLeg"][0] + [0.2, 0, -0.8])
    assert out["LeftFootMod"][1] is q0 and fr["LeftLeg"][0][2] == 0.55  # rotations kept, input untouched


@pytest.mark.skipif(not os.path.isfile(CMU_02_01), reason="needs data/raw/cmu_bvh (tools/fetch_samples.py cmu)")
def test_made_up_robot_retargets_a_walk(toy):
    """CMU walk 02_01 on the made-up robot: limbs pointing like the human's (pose error a few
    degrees), hands and feet where the IK was asked to put them, the identity of the model in
    the motion and its cache entry keyed by the model's digest."""
    _need()
    from retlens import compare, retarget_quality
    from retlens.io import load_bvh
    from retlens.retarget import profile, retarget_file

    m, info = retarget_file(CMU_02_01, robot=toy, fps=30.0, smooth_hz=6.0, log=None)
    assert m.joint_names == profile(toy).joint_names() and info["robot_ident"]["name"] == "toybot"
    assert info["robot_parts"]["elbow_flex_sign"] == {"left": -1, "right": -1}
    r = info["ik_position_residual"]
    assert r["hands"]["mean_cm"] < 4 and r["feet"]["mean_cm"] < 3
    q = retarget_quality.measure(load_bvh(CMU_02_01), m, toy, profile(toy).model())
    assert q["pose_err_deg"] < 8, q["_segments_deg"]
    a = compare.cache_path(CMU_02_01, toy, 6.0, 30.0)
    with open(toy, "a", encoding="utf-8") as f:  # a comment changes nothing MuJoCo reads: the same robot
        f.write("\n<!-- a note -->\n")
    assert compare.cache_path(CMU_02_01, toy, 6.0, 30.0) == a
    toybot(toy, elbow_range=2.0)  # an edited model (a joint range) is another robot to the cache
    assert compare.cache_path(CMU_02_01, toy, 6.0, 30.0) != a


def test_made_up_robot_is_drawn_from_its_mjcf(toy):
    """No URDF: the window draws the robot from its MJCF, and the drawing's links follow
    MuJoCo's bodies for any joint values (anchors off the body origins included)."""
    import mujoco as mj

    from retlens import robot_profile as rp
    from retlens.app.mjcf_draw import MjcfDrawing
    from retlens.app.robots import RobotBatch

    model = rp.load(toy).model()
    draw = MjcfDrawing(model)
    rb = RobotBatch(None, draw)
    assert rb.joint_names == rp.load(toy).joint_names() and len(rb.meshes) > 10
    rng = np.random.default_rng(0)
    q = rng.uniform(-0.5, 0.5, len(rb.joint_names))
    T = rb.forward(np.eye(4)[None], q[None])[:, 0]
    data = mj.MjData(model)
    data.qpos[:] = model.qpos0
    data.qpos[3:7] = [1, 0, 0, 0]
    data.qpos[:3] = 0
    data.qpos[7:] = q
    mj.mj_kinematics(model, data)
    for i, link in enumerate(rb.links):
        b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, link)
        if b >= 0:
            np.testing.assert_allclose(T[i, :3, 3], data.xpos[b], atol=1e-9)
            np.testing.assert_allclose(T[i, :3, :3], data.xmat[b].reshape(3, 3), atol=1e-9)


def test_variants_the_review_found(tmp_path):
    """Robots unlike the G1 in other ways: an arm that ends at its elbow (the hand fixed to the
    forearm is its IK body); jointed toes whose spheres are a hair below the heel's (the foot is
    still the body above both, the toe joint no ankle joint); one box per sole (its four bottom
    corners are the sole points); hands without names (named for the tables); a model facing
    -x (refused: its knees would bend the feet forwards)."""
    pytest.importorskip("mujoco")
    from retlens import robot_profile as rp

    p = rp.load(toybot(str(tmp_path / "nowrist.xml"), wrists=False))
    arm = p.parts.arms["left"]
    assert not arm.distal and arm.flex_sign == -1 and p.task_bodies()["LeftHand"] == p.body(arm.tip_body)
    assert len(set(p.task_bodies().values())) == 14

    p = rp.load(toybot(str(tmp_path / "toes.xml"), toes=True))
    leg = p.parts.legs["left"]
    assert len(leg.distal) == 2 and p.body(leg.end_body) == p.body(int(p.model().jnt_bodyid[leg.distal[1]]))
    assert len(p.parts.sole_points["left"]) == 4  # heel and toe spheres
    data = rp._zero_data(p.model())
    np.testing.assert_allclose(leg.centres["distal"].world(data), [0, 0.1, -0.85], atol=1e-6)

    p = rp.load(toybot(str(tmp_path / "box.xml"), box_feet=True))
    pts = p.parts.sole_points["left"]
    assert len(pts) == 4 and all(r == 0 for _, _, r in pts)
    data = rp._zero_data(p.model())
    np.testing.assert_allclose(rp.sole_world(data, pts)[:, 2], -0.93, atol=1e-6)

    p = rp.load(toybot(str(tmp_path / "unnamed.xml"), unnamed_hands=True))
    assert all(isinstance(n, str) and n for n in p.hands().values())

    with pytest.raises(rp.RobotError, match="face"):
        rp.load(toybot(str(tmp_path / "back.xml"), backwards=True)).parts


def test_box_feet_stand_balanced(tmp_path):
    """A robot standing still on box soles is balanced: its four corners make the support
    polygon (one point per geom made every standing frame unbalanced)."""
    _need()
    from retlens import analysis
    from retlens import robot_profile as rp
    from retlens.motion import RobotMotion

    path = toybot(str(tmp_path / "box.xml"), box_feet=True)
    prof = rp.load(path)
    T = 60
    m = RobotMotion("still", prof.joint_names(), np.tile([0.0, 0.0, prof.parts.standing_height], (T, 1)),
                    np.tile([1.0, 0, 0, 0], (T, 1)), np.zeros((T, len(prof.joint_names()))), 30.0)
    f = analysis.foot_metrics(m, analysis.FootKinematics(path))
    assert f["static_unbalanced_pct"] == 0 and f["penetration_pct"] == 0 and abs(f["sole_min_cm"]) < 0.1


def test_urdf_keeps_visual_meshes():
    """A URDF read for a robot keeps its visual meshes (MuJoCo's URDF defaults drop them while
    parsing): the head is visual only on the G1, so its height matches the MJCF's."""
    _need()
    from retlens import paths, robot_profile as rp

    prof = rp.load(paths.robot_urdf())
    m = prof.model()
    assert sum(1 for g in range(m.ngeom) if not m.geom_contype[g] and not m.geom_conaffinity[g]) > 20
    assert prof.parts.top_height == pytest.approx(rp.load("unitree_g1").parts.top_height, abs=0.02)


def test_drawing_follows_a_reference_angle(tmp_path):
    """A knee with a reference angle turns by q - ref in MuJoCo; the MJCF drawing too."""
    import mujoco as mj

    from retlens import robot_profile as rp
    from retlens.app.mjcf_draw import MjcfDrawing
    from retlens.app.robots import RobotBatch

    path = toybot(str(tmp_path / "ref.xml"), knee_ref=0.4)
    model = rp.load(path).model()
    rb = RobotBatch(None, MjcfDrawing(model))
    q = model.qpos0[7:].copy()
    q[rb.joint_names.index(rp.load(path).leg_joints("left")[3])] += 0.3
    T = rb.forward(np.eye(4)[None], q[None])[:, 0]
    data = mj.MjData(model)
    data.qpos[:] = model.qpos0
    data.qpos[:3], data.qpos[3:7], data.qpos[7:] = 0, [1, 0, 0, 0], q
    mj.mj_kinematics(model, data)
    for i, link in enumerate(rb.links):
        b = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, link)
        if b >= 0:
            np.testing.assert_allclose(T[i, :3, 3], data.xpos[b], atol=1e-9)


def test_made_up_robot_in_mujoco_physics(tmp_path):
    """Another robot's MuJoCo physics (policy_replay.RobotSim): its own model with the G1's gains of
    the same role times its mass over the G1's, its own torque limits; standing still on the harness
    it does not fall and tracks within a centimetre, with no controller it runs too. The runner
    offers harness / pd for it, not GMT, keys results by its model, and the result reopens with its
    joints."""
    _need()
    import threading

    from retlens import compare, policy_replay as pr, policy_runner
    from retlens import robot_profile as rp
    from retlens.motion import RobotMotion

    path = toybot(str(tmp_path / "toy.xml"))
    prof = rp.load(path)
    names = prof.joint_names()
    sim = pr.RobotSim(path, "harness")
    assert sim.joint_names == names and sim.gain_scale == pytest.approx(sim.mass / pr.G1_MASS)
    knee = names.index(prof.leg_joints("left")[3])
    assert sim.pd_kp[knee] == pytest.approx(1500.0 * sim.gain_scale)
    T = 45
    m = RobotMotion("still", names, np.tile([0.0, 0.0, prof.parts.standing_height], (T, 1)),
                    np.tile([1.0, 0, 0, 0], (T, 1)), np.zeros((T, len(names))), 30.0)
    res = pr.run(sim, pr.Reference.from_motion(m, joints=names), hold_s=0.2)
    assert res.metrics["falls"] == 0 and res.metrics["body_error_cm"] < 1.0 and res.joint_names == names
    assert pr.run(pr.RobotSim(path, "pd"), pr.Reference.from_motion(m, joints=names), hold_s=0.2).metrics["clip_s"] > 1
    with pytest.raises(ValueError, match="G1"):
        pr.RobotSim(path, "gmt")

    runner = policy_runner.PolicyRunner(str(tmp_path / "cache"), robot=path)
    try:
        assert runner.problem("harness") == runner.problem("pd") == "" and "G1" in runner.problem("gmt")
        assert runner.key(m, "harness") != policy_runner.PolicyRunner(str(tmp_path / "c2")).key(m, "harness")
        done = threading.Event()
        job = runner.request(m, "harness", on_done=lambda j: done.set())
        assert done.wait(120) and job.state == "done", job.message
        assert compare.load_item(job.result, log=None).robot.joint_names == names
    finally:
        runner.shutdown()
