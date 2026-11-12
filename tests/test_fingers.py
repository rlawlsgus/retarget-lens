"""Fingers (retlens.fingers, retlens.robot_profile._fingers): a robot hand with jointed fingers follows the person's."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import fingers  # noqa: E402
from retlens.motion import RobotMotion, SkeletonMotion  # noqa: E402


def _hands_robot():
    from retlens.robot_profile import RobotError, load

    try:
        return load("unitree_g1_with_hands")
    except RobotError as e:
        pytest.skip(str(e))
    except ImportError as e:  # no MuJoCo
        pytest.skip(str(e))


def test_robot_fingers_and_closing_signs():
    prof = _hands_robot()
    model = prof.model()
    for side in ("left", "right"):
        fs = prof.parts.fingers[side]
        assert [f.kind for f in fs] == ["thumb", "index", "middle"]
        for f in fs:
            for j, c in zip(f.joints, f.close):
                lo, hi = model.jnt_range[j]
                if c:  # the closing side is the side the joint's range opens to
                    assert (hi if c > 0 else -lo) > 0.5, (prof.joint(j), c, lo, hi)
        assert fs[0].close[0] == 0  # the thumb's base turns about the thumb: not a closing joint
    assert prof.has_fingers() and "right_hand_index_1_joint" in prof.finger_joints()
    from retlens.robot_profile import load

    assert not load("unitree_g1").has_fingers()


def test_spread_keeps_sums():
    v = np.array([[0.1, 0.3, 0.2]])
    assert np.allclose(fingers.spread(v, 2), [[0.1 + 0.15, 0.15 + 0.2]])
    assert np.allclose(fingers.spread(v, 3), v) and np.allclose(fingers.spread(v, 1), [[0.6]])
    assert np.allclose(fingers.spread(np.array([[0.4]]), 2), [[0.2, 0.2]])


BODY = [("Hips", None, (0, 0, 1.0)), ("LeftUpLeg", "Hips", (0, 0.1, 0.95)), ("LeftLeg", "LeftUpLeg", (0, 0.1, 0.5)),
        ("LeftFoot", "LeftLeg", (0, 0.1, 0.08)), ("RightUpLeg", "Hips", (0, -0.1, 0.95)),
        ("RightLeg", "RightUpLeg", (0, -0.1, 0.5)), ("RightFoot", "RightLeg", (0, -0.1, 0.08)),
        ("Spine2", "Hips", (0, 0, 1.4)), ("LeftArm", "Spine2", (0, 0.2, 1.4)), ("LeftForeArm", "LeftArm", (0, 0.45, 1.4)),
        ("LeftHand", "LeftForeArm", (0, 0.7, 1.4)), ("RightArm", "Spine2", (0, -0.2, 1.4)),
        ("RightForeArm", "RightArm", (0, -0.45, 1.4)), ("RightHand", "RightForeArm", (0, -0.7, 1.4))]


def _person(bend_deg: float) -> SkeletonMotion:
    """A T-posed person whose right index finger (Mixamo names) bends bend_deg at its middle joint in frame 1."""
    names = [n for n, _, _ in BODY] + ["RightHandIndex1", "RightHandIndex2", "RightHandIndex3", "RightHandIndex3_end"]
    parents = [names.index(p) if p else -1 for _, p, _ in BODY] + [13, 14, 15, 16]
    rest = np.array([p for _, _, p in BODY] + [(0, -0.78, 1.4), (0, -0.82, 1.4), (0, -0.85, 1.4), (0, -0.87, 1.4)], float)
    bent = rest.copy()
    a = np.radians(bend_deg)
    pip = rest[15]
    for k in (16, 17):  # the segments past the middle joint turn about x at it (towards -z, the palm)
        d = rest[k] - pip
        bent[k] = pip + np.array([0.0, d[1] * np.cos(a), d[1] * np.sin(a)])
    return SkeletonMotion(name="p", joint_names=names, parents=np.array(parents), positions=np.stack([rest, bent]),
                          fps=30.0, source="p.fbx", meta={"format": "fbx", "rest_pose": (rest, None)})


def test_human_fingers_by_name():
    # 3ds Max Biped's ring end site is "Finger032_End": its "Finger0" must not make the ring a thumb
    from retlens.fingers import _kind

    assert _kind(["l finger3", "l finger31", "l finger32", "l finger032_end"]) == "ring"
    assert _kind(["l finger0", "l finger01"]) == "thumb" and _kind(["lefthandpinky1"]) == "pinky"
    assert _kind(["l finger1", "l finger11", "l finger12"]) == "index"
    hands = fingers.human_fingers(_person(0))
    assert list(hands) == ["right"] and list(hands["right"]["fingers"]) == ["index"]
    assert len(hands["right"]["fingers"]["index"]) == 4  # three joints and the end site


def test_retarget_fingers_bends_the_robot_index():
    prof = _hands_robot()
    names = prof.joint_names()
    m = RobotMotion(name="r", joint_names=names, root_pos=np.zeros((2, 3)), root_quat=np.tile([1.0, 0, 0, 0], (2, 1)),
                    dof_pos=np.zeros((2, len(names))), fps=30.0)
    out, info = fingers.retarget_fingers(m, _person(30.0), prof)
    q = np.degrees(out.dof_pos)
    i0, i1 = names.index("right_hand_index_0_joint"), names.index("right_hand_index_1_joint")
    # the human index bends 0 / 30 / 0 deg (base, middle, end joint) -> the robot's two joints 15 / 15, closing (+)
    assert np.allclose(q[0, [i0, i1]], 0, atol=1e-6) and np.allclose(q[1, [i0, i1]], 15.0, atol=0.5)
    m0 = names.index("right_hand_middle_1_joint")
    assert info["fingers"]["right"]["middle"]["from"] == "index" and np.isclose(q[1, m0], 15.0, atol=0.5)
    assert any("thumb" in n for n in info["notes"]) and any("left" in n for n in info["notes"])
    assert np.allclose(q[:, [i for i, n in enumerate(names) if "hand" not in n]], 0)  # the body is left as it was
    out, info = fingers.retarget_fingers(m, _person(170.0), prof)  # past the joint range: clipped to it
    lo, hi = prof.model().jnt_range[prof.model().joint("right_hand_index_1_joint").id]
    assert np.degrees(out.dof_pos[1, i1]) <= np.degrees(hi) + 1e-6


def _toy_xml(names=None) -> str:
    """A primitive humanoid with flat five-finger hands: palms down, fingers along the arms, a thumb in front lying in
    the palm plane, a spread joint on each index (the open, flat zero pose of Inspire / Shadow-like hands)."""
    names = names or {k: k for k in ("thumb", "index", "middle", "ring", "pinky")}

    def finger(side, kind, x, lo, hi, axis="1 0 0", d=(0, 0.035, 0), base=None, spread=False):
        s = 1 if side == "l" else -1
        d = (d[0], s * d[1], d[2])
        n = f"{side}_{names[kind]}"
        dx = " ".join(f"{v:g}" for v in d)
        head, tail = "", ""
        pos = " ".join(f"{v:g}" for v in (base or (x, s * 0.1, 0)))
        if spread:
            head, tail, pos = (f'<body name="{n}_spr" pos="{pos}"><joint name="{n}_spr_joint" axis="0 0 1" '
                               f'range="-0.3 0.3"/>'), "</body>", "0 0 0"
        for k in range(3):
            head += (f'<body name="{n}_{k}" pos="{pos if k == 0 else dx}"><joint name="{n}_{k}_joint" axis="{axis}" '
                     f'range="{lo} {hi}"/><geom type="capsule" fromto="0 0 0 {dx}" size="0.008"/>')
            tail += "</body>"
        return head + tail

    def arm(side):
        s = 1 if side == "l" else -1
        lo, hi = (-1.5, 0.1) if side == "l" else (-0.1, 1.5)
        hand = (finger(side, "index", 0.03, lo, hi, spread=True) + finger(side, "middle", 0.01, lo, hi)
                + finger(side, "ring", -0.01, lo, hi) + finger(side, "pinky", -0.03, lo, hi)
                + finger(side, "thumb", 0, -0.1, 1.2, axis="0 1 0", d=(0.035, 0, 0), base=(0.045, s * 0.03, 0)))
        joint = '<joint name="{0}" axis="{1}" range="-2.5 2.5"/>'
        return (f'<body name="{side}_sh_p" pos="0 {s * 0.2} 0.12">{joint.format(side + "_sh_p_joint", "0 1 0")}'
                f'<body name="{side}_sh_r">{joint.format(side + "_sh_r_joint", "1 0 0")}'
                f'<body name="{side}_sh_y">{joint.format(side + "_sh_y_joint", "0 1 0")}'
                f'<geom type="capsule" fromto="0 0 0 0 {s * 0.25} 0" size="0.03"/>'
                f'<body name="{side}_elbow" pos="0 {s * 0.25} 0">{joint.format(side + "_elbow_joint", "0 0 1")}'
                f'<geom type="capsule" fromto="0 0 0 0 {s * 0.22} 0" size="0.025"/>'
                f'<body name="{side}_wr_r" pos="0 {s * 0.22} 0">{joint.format(side + "_wr_r_joint", "0 1 0")}'
                f'<body name="{side}_wr_p">{joint.format(side + "_wr_p_joint", "0 0 1")}'
                f'<body name="{side}_hand"><geom type="box" pos="0 {s * 0.05} 0" size="0.045 0.05 0.008"/>{hand}'
                + "</body>" * 7)

    def leg(side):
        s = 1 if side == "l" else -1
        joint = '<joint name="{0}" axis="{1}" range="{2}"/>'
        return (f'<body name="{side}_hp" pos="0 {s * 0.1} -0.05">{joint.format(side + "_hp_joint", "0 1 0", "-2 2")}'
                f'<body name="{side}_hr">{joint.format(side + "_hr_joint", "1 0 0", "-1 1")}'
                f'<body name="{side}_hy">{joint.format(side + "_hy_joint", "0 0 1", "-1 1")}'
                f'<geom type="capsule" fromto="0 0 0 0 0 -0.4" size="0.04"/>'
                f'<body name="{side}_knee" pos="0 0 -0.4">{joint.format(side + "_knee_joint", "0 1 0", "0 2.5")}'
                f'<geom type="capsule" fromto="0 0 0 0 0 -0.4" size="0.035"/>'
                f'<body name="{side}_ap" pos="0 0 -0.4">{joint.format(side + "_ap_joint", "0 1 0", "-1 1")}'
                f'<body name="{side}_ar">{joint.format(side + "_ar_joint", "1 0 0", "-0.5 0.5")}'
                f'<geom type="box" pos="0.04 0 -0.04" size="0.1 0.04 0.02"/>' + "</body>" * 6)

    return (f'<mujoco model="toy_hands"><compiler angle="radian"/><worldbody><body name="pelvis" pos="0 0 0.95">'
            f'<freejoint/><geom type="box" size="0.08 0.13 0.06"/>{leg("l")}{leg("r")}'
            f'<body name="torso" pos="0 0 0.25"><joint name="waist_joint" axis="0 0 1" range="-1 1"/>'
            f'<geom type="box" size="0.08 0.15 0.15"/>{arm("l")}{arm("r")}</body></body></worldbody></mujoco>')


def _toy(tmp_path, names=None):
    pytest.importorskip("mujoco")
    from retlens.robot_profile import load

    path = tmp_path / ("toy_unnamed.xml" if names else "toy.xml")
    path.write_text(_toy_xml(names), encoding="utf-8")
    return load(str(path))


def test_flat_five_finger_hand_closes_and_leaves_spreads(tmp_path):
    prof = _toy(tmp_path)
    fs = {f.kind: f for f in prof.parts.fingers["left"]}
    assert list(fs) == ["thumb", "index", "middle", "ring", "pinky"]
    assert fs["index"].close == [0, -1, -1, -1]  # the spread joint is left alone; the rest close (palm down: -x turn)
    assert all(fs[k].close == [-1, -1, -1] for k in ("middle", "ring", "pinky")) and fs["thumb"].close == [1, 1, 1]
    assert {f.kind: f.close for f in prof.parts.fingers["right"]}["middle"] == [1, 1, 1]  # the mirrored hand
    # with no names: the thumb is the finger whose base is nearest the hand, the others in order from it
    unnamed = _toy(tmp_path, names={"thumb": "f0", "index": "f1", "middle": "f2", "ring": "f3", "pinky": "f4"})
    kinds = {f.kind: prof_name for f in unnamed.parts.fingers["left"] for prof_name in [unnamed.joint(f.joints[0])]}
    assert kinds["thumb"].startswith("l_f0") and kinds["index"].startswith("l_f1") and kinds["pinky"].startswith("l_f4")


def _hand_person(index_mcp=0.0, index_side=0.0, thumb_base=0.0) -> SkeletonMotion:
    """A T-posed person, palms down, left fingers fanned out from the hand (knuckles 8-12 deg off the fingers); frame 1
    turns the left index's first joint towards the palm (index_mcp deg) and sideways in the palm (index_side deg), and
    the thumb's base away from the palm (thumb_base deg, negative: towards it)."""
    names = [n for n, _, _ in BODY]
    parents = [names.index(p) if p else -1 for _, p, _ in BODY]
    rest = [np.array(p, float) for _, _, p in BODY]
    hand = np.array(BODY[10][2], float)  # LeftHand
    chains = {}
    for kind, x, fan in (("Index", 0.03, 10), ("Middle", 0.01, 3), ("Ring", -0.01, -3), ("Pinky", -0.03, -10)):
        base = hand + [x, 0.08, 0]
        d = np.array([np.sin(np.radians(fan)), np.cos(np.radians(fan)), 0.0])
        chains[kind] = [base + d * s for s in (0, 0.04, 0.07, 0.09)]
    t0 = hand + [0.035, 0.02, -0.01]
    chains["Thumb"] = [t0 + np.array([0.7, 0.7, 0]) * s for s in (0, 0.035, 0.065, 0.085)]
    for kind, pts in chains.items():
        for k, p in enumerate(pts):
            names.append(f"LeftHand{kind}{k + 1}" if k < 3 else f"LeftHand{kind}3_end")
            parents.append(10 if k == 0 else len(names) - 2)
            rest.append(p)
    rest = np.array(rest)
    moved = rest.copy()
    from scipy.spatial.transform import Rotation

    idx = names.index("LeftHandIndex1")
    turn = Rotation.from_euler("zx", [-index_side, -index_mcp], degrees=True).as_matrix()  # down: towards the palm
    for k in range(idx + 1, idx + 4):
        moved[k] = rest[idx] + turn @ (rest[k] - rest[idx])
    th = names.index("LeftHandThumb1")
    up = Rotation.from_rotvec(np.radians(thumb_base) * np.array([-0.7, 0.7, 0])).as_matrix()  # about the thumb's side axis
    for k in range(th + 1, th + 4):
        moved[k] = rest[th] + up @ (rest[k] - rest[th])
    return SkeletonMotion(name="p", joint_names=names, parents=np.array(parents), positions=np.stack([rest, moved]),
                          fps=30.0, source="p.fbx", meta={"format": "fbx", "rest_pose": (rest, None)})


def test_first_joint_bends_in_the_palm_frame():
    """The first joint's bend: a turn towards the palm counts in full (knuckles fanned out at rest), a sideways turn
    and a thumb opening away from the palm do not."""
    frames = np.array([0.0, 1.0])
    for mcp, side, want in ((30.0, 0.0, 30.0), (0.0, 15.0, 0.0), (45.0, 10.0, 45.0)):
        h = _hand_person(index_mcp=mcp, index_side=side)
        hands = fingers.human_fingers(h)
        bend = np.degrees(fingers.finger_bends(h, hands["left"], frames, h.meta["rest_pose"][0])["index"])
        assert np.allclose(bend[0], 0, atol=1e-6) and abs(bend[1, 0] - want) < 2.0, (mcp, side, bend[1])
    h = _hand_person(thumb_base=-20.0)  # away from the palm (up): no closing
    hands = fingers.human_fingers(h)
    assert list(hands["left"]["fingers"]) == ["index", "middle", "ring", "pinky", "thumb"]
    thumb = np.degrees(fingers.finger_bends(h, hands["left"], frames, h.meta["rest_pose"][0])["thumb"])
    assert thumb[1, 0] < 1.0
    h = _hand_person(thumb_base=20.0)  # towards the palm (down): closes
    thumb = np.degrees(fingers.finger_bends(h, fingers.human_fingers(h)["left"], frames, h.meta["rest_pose"][0])["thumb"])
    assert thumb[1, 0] > 5.0


def test_numbered_fingers_and_a_slightly_bent_back_rest():
    # numbered from 1 (a finger5 exists): finger1 is the thumb
    from retlens.fingers import HUMAN_WORDS_1, _kind

    assert _kind(["leftfinger1_1"], HUMAN_WORDS_1) == "thumb" and _kind(["leftfinger5_1"], HUMAN_WORDS_1) == "pinky"
    # middle joints 1 deg bent back at rest and in the clip, only the first joints flex: still towards the palm
    h = _hand_person(index_mcp=30.0)
    names = h.joint_names
    for kind in ("Index", "Middle", "Ring", "Pinky"):
        i2 = names.index(f"LeftHand{kind}2")
        for X in (h.positions[0], h.positions[1], h.meta["rest_pose"][0]):
            for k in (i2, i2 + 1):  # lift the segments past the middle joint by 1 deg (backwards, up)
                d = X[k] - X[i2 - 1]
                X[k] = X[i2 - 1] + np.array([d[0], d[1], d[2] + np.linalg.norm(d) * np.radians(1.0)])
    bend = np.degrees(fingers.finger_bends(h, fingers.human_fingers(h)["left"], np.array([0.0, 1.0]),
                                           h.meta["rest_pose"][0])["index"])
    assert abs(bend[1, 0] - 30.0) < 2.5


def test_curled_rest_is_not_taken_as_straight():
    """3ds Max Biped binds its fingers relaxed (middle joints ~45 deg): the clip opening the hand reads 0, the relaxed
    hand reads its curl (not 0 as it would against the curled rest)."""
    from scipy.spatial.transform import Rotation

    h = _hand_person()
    names = h.joint_names
    i2 = names.index("LeftHandIndex2")
    rest = h.meta["rest_pose"][0].copy()
    turn = Rotation.from_euler("x", -45, degrees=True).as_matrix()  # towards the palm (down)
    for k in (i2 + 1, i2 + 2):
        rest[k] = rest[i2] + turn @ (rest[k] - rest[i2])
    h.positions[1] = rest  # frame 0 open (as built), frame 1 relaxed like the rest
    h.meta["rest_pose"] = (rest, None)
    bend = np.degrees(fingers.finger_bends(h, fingers.human_fingers(h)["left"], np.array([0.0, 1.0]), rest)["index"])
    assert bend[0, 1] < 3.0 and 40.0 < bend[1, 1] < 46.0, bend


def test_finger_base_on_the_hand_joint():
    """CMU BVH: LeftFingerBase and LThumb sit on LeftHand (offset 0): their own joint is not measured, the rest is."""
    names = [n for n, _, _ in BODY] + ["LeftFingerBase", "LeftHandIndex1", "LeftHandIndex1_end", "LThumb", "LThumb_end"]
    parents = [names.index(p) if p else -1 for _, p, _ in BODY] + [10, 14, 15, 10, 17]
    hand = np.array(BODY[10][2], float)
    rest = np.array([p for _, _, p in BODY] + [hand, hand + [0, 0.08, 0], hand + [0, 0.14, 0], hand,
                                               hand + [0.04, 0.03, 0]], float)
    bent = rest.copy()
    bent[16] = rest[15] + [0, 0.06 * np.cos(np.radians(40)), -0.06 * np.sin(np.radians(40))]
    h = SkeletonMotion(name="cmu", joint_names=names, parents=np.array(parents), positions=np.stack([rest, bent]),
                       fps=30.0, source="cmu.bvh", meta={"format": "bvh", "rest_pose": (rest, None)})
    hands = fingers.human_fingers(h)
    assert set(hands["left"]["fingers"]) == {"index", "thumb"}
    bends = fingers.finger_bends(h, hands["left"], np.array([0.0, 1.0]), rest)
    assert bends["thumb"].shape[1] == 0 and bends["index"].shape[1] == 1
    assert abs(np.degrees(bends["index"][1, 0]) - 40.0) < 1.0


def test_robot_without_fingers_is_left_alone():
    from retlens.robot_profile import RobotError, load

    try:
        prof = load("unitree_g1")
    except (RobotError, ImportError) as e:
        pytest.skip(str(e))
    names = prof.joint_names()
    m = RobotMotion(name="r", joint_names=names, root_pos=np.zeros((2, 3)), root_quat=np.tile([1.0, 0, 0, 0], (2, 1)),
                    dof_pos=np.zeros((2, len(names))), fps=30.0)
    out, info = fingers.retarget_fingers(m, _person(30.0), prof)
    assert out is m and info is None
