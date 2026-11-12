"""Regressions of the retargeting / robot / settings / fingers review: a robot with mesh feet, the robot digest and
the built-in G1 named by its file, the stdout redirect of overlapping retargets, clips too short to smooth, 3ds Max
Biped's classic layout, LAFAN1 upsampling, Nokov on the G1 with hands, hand-edited settings.json, the fingers'
reference report and tools/retarget.py over folders."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from retlens import robot_profile as rp  # noqa: E402
from retlens import settings  # noqa: E402
from retlens.motion import RobotMotion, SkeletonMotion  # noqa: E402
from retlens.synthetic import walking_bvh_text  # noqa: E402


def _need_retargeting():
    from retlens.retarget import unavailable

    why = unavailable()
    if why:
        pytest.skip(why)


def _need_hands():
    try:
        prof = rp.load("unitree_g1_with_hands")
        prof.parts
    except (rp.RobotError, ImportError) as e:
        pytest.skip(str(e))
    return prof


# --------------------------------------------------------------------------- robot profile
def _mesh_feet_robot(path: str) -> str:
    """The test robot of test_robot_profile with each sole a sheared slab mesh (bottom at -0.93 m like the box sole
    it replaces): its inertia frame is tilted, so its bounding box corners reach 2 cm below its lowest vertex."""
    import mujoco as mj

    from test_robot_profile import toybot

    spec = mj.MjSpec.from_file(toybot(path, box_feet=True))
    v = [c for z, dx in ((0.0, 0.0), (0.05, 0.1)) for x in (-0.08, 0.13) for y in (-0.05, 0.05) for c in (x + dx, y, z)]
    spec.add_mesh(name="sole", uservert=v)
    for g in spec.geoms:
        if g.type == mj.mjtGeom.mjGEOM_BOX and abs(g.size[2] - 0.01) < 1e-9:  # the sole boxes
            g.type, g.meshname, g.pos = mj.mjtGeom.mjGEOM_MESH, "sole", [0.0, 0.0, -0.08]
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec.to_xml())
    return path


def test_mesh_feet_have_sole_points(tmp_path):
    """A robot whose feet collide through meshes (URDF / CAD exports): the floor is its lowest vertex, not a corner
    of the mesh's tilted bounding box, so each foot gets sole points (none before: the foot metrics read 0 % and the
    physics failed with a numpy error)."""
    mj = pytest.importorskip("mujoco")
    path = _mesh_feet_robot(str(tmp_path / "meshfeet.xml"))
    prof = rp.load(path)
    model = prof.model()
    data = rp._zero_data(model)
    mesh = [g for g in range(model.ngeom) if model.geom_type[g] == mj.mjtGeom.mjGEOM_MESH]
    assert len(mesh) == 2 and all(rp._geom_low(model, data, g) == pytest.approx(-0.93, abs=1e-6) for g in mesh)
    p = prof.parts
    for s in rp.SIDES:
        assert len(p.sole_points[s]) >= 3
        np.testing.assert_allclose(rp.sole_world(data, p.sole_points[s])[:, 2], -0.93, atol=1e-6)
    assert p.standing_height == pytest.approx(0.93, abs=1e-3)


def test_geom_bounds_are_exact_for_tilted_round_shapes():
    """A tilted sphere, capsule or cylinder is bounded by its surface, not by its bounding box's corners (which reach
    below it: the floor came out under every sole point of such a foot)."""
    mj = pytest.importorskip("mujoco")
    model = mj.MjModel.from_xml_string(
        "<mujoco><worldbody><body pos='0 0 1' euler='25 -35 10'>"
        "<geom type='sphere' size='0.03'/><geom type='capsule' size='0.02 0.07' pos='0.2 0 0'/>"
        "<geom type='cylinder' size='0.05 0.04' pos='-0.2 0 0'/></body></worldbody></mujoco>")
    data = mj.MjData(model)
    mj.mj_kinematics(model, data)
    a = np.linspace(0, 2 * np.pi, 721)
    for g in range(model.ngeom):
        R, c, (r, h, _) = data.geom_xmat[g].reshape(3, 3), data.geom_xpos[g], model.geom_size[g]
        t = model.geom_type[g]
        if t == mj.mjtGeom.mjGEOM_SPHERE:  # a unit sphere sampled densely
            u, v = np.meshgrid(a, np.linspace(0, np.pi, 361))
            pts = r * np.stack([np.sin(v) * np.cos(u), np.sin(v) * np.sin(u), np.cos(v)], -1).reshape(-1, 3)
        elif t == mj.mjtGeom.mjGEOM_CAPSULE:
            u, v = np.meshgrid(a, np.linspace(0, np.pi, 361))
            ball = r * np.stack([np.sin(v) * np.cos(u), np.sin(v) * np.sin(u), np.cos(v)], -1).reshape(-1, 3)
            pts = np.concatenate([ball + (0, 0, h), ball - (0, 0, h)])
        else:  # the cylinder's two rims
            rim = np.stack([r * np.cos(a), r * np.sin(a), np.zeros_like(a)], -1)
            pts = np.concatenate([rim + (0, 0, h), rim - (0, 0, h)])
        z = (pts @ R.T + c)[:, 2]
        assert rp._geom_low(model, data, g) == pytest.approx(z.min(), abs=1e-5)
        assert rp._geom_high(model, data, g) == pytest.approx(z.max(), abs=1e-5)


def test_feet_without_sole_points_say_so(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    from test_robot_profile import toybot

    monkeypatch.setattr(rp, "_sole_points", lambda *a: [])
    with pytest.raises(rp.RobotError, match="sole points"):
        rp.derive(rp.load(toybot(str(tmp_path / "toy.xml"))).model())


def test_digest_does_not_depend_on_the_robot_loaded_first():
    """The digest of a built-in model is the same whichever robot the process loaded before it (MuJoCo writes
    meshes' content_type only for meshes it decodes first): the caches and same_robot see one robot."""
    _need_hands()
    code = ("import sys; sys.path.insert(0, {root!r}); from retlens import robot_profile as rp; "
            "[rp.load(k).digest for k in {first!r}]; print(rp.load('unitree_g1').digest, "
            "rp.model_digest(rp.load('unitree_g1').mjcf))")
    out = []
    for first in ([], ["unitree_g1_with_hands"]):
        r = subprocess.run([sys.executable, "-c", code.format(root=ROOT, first=first)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-1500:]
        out.append(r.stdout.split())
    assert out[0][0] == out[0][1] == out[1][0] == out[1][1]


def test_same_robot_takes_a_builtin_whatever_its_digest():
    g1 = {"name": "Unitree G1", "digest": "0a4325c74f4e", "key": "unitree_g1"}
    assert rp.same_robot({"name": "Unitree G1", "digest": "e177d72e50b8", "key": "unitree_g1"}, g1)  # saved before
    assert rp.same_robot({"name": "Unitree G1", "digest": "c1e89134d70f"}, g1)  # no key recorded: by its name
    assert not rp.same_robot({"name": "Unitree G1 (hands)", "digest": "a7e0c50729e3", "key": "unitree_g1_with_hands"}, g1)
    other = {"name": "Unitree G1", "digest": "111111111111", "key": "my_g1.xml"}  # a user's file named like it
    assert not rp.same_robot(other, g1) and not rp.same_robot(other, {**other, "digest": "222222222222"})
    assert rp.same_robot(other, dict(other)) and rp.same_robot(None, g1)


def test_same_robot_takes_a_shipped_file_recorded_by_its_path():
    """Until 2026-11-11 a G1 file RetLens ships, chosen by its path (찾아보기...), was recorded as a robot of its own
    (the model's name in it, the file's name as key): motions and sessions saved so are the built-in model's, not
    another robot's (they were flagged as "g1_mocap의 모션")."""
    g1 = {"name": "Unitree G1", "digest": "0a4325c74f4e", "key": "unitree_g1"}
    hands = {"name": "Unitree G1 (hands)", "digest": "1fec08117ba9", "key": "unitree_g1_with_hands"}
    old_g1 = {"name": "g1_mocap", "digest": "e177d72e50b8", "key": "g1_mocap_29dof.xml"}
    old_hands = {"name": "g1_29dof_with_hands_scene", "digest": "fd811d4ab411", "key": "g1_mocap_29dof_with_hands.xml"}
    for old, mine, other in ((old_g1, g1, hands), (old_hands, hands, g1)):
        npz = {k: old[k] for k in ("name", "digest")}  # what a robot npz records
        assert rp.same_robot(old, mine) and rp.same_robot(npz, mine) and rp.same_robot(mine, npz)
        assert rp.same_robot(npz, {**old, "digest": "c1e89134d70f"})  # the digest then depended on the load order
        assert not rp.same_robot(old, other) and not rp.same_robot(npz, other)
    # a user's own file: another model under the shipped file's name, or the shipped model's name in another file
    assert not rp.same_robot({"name": "my_bot", "digest": "111111111111", "key": "g1_mocap_29dof.xml"}, g1)
    assert not rp.same_robot({"name": "g1_mocap", "digest": "111111111111", "key": "my_g1.xml"}, g1)
    assert not rp.same_robot({"name": ["g1_mocap"], "digest": "1", "key": ["unitree_g1"]}, g1)  # a session edited by hand

    _need_hands()  # the names are the shipped files' own, and match their profiles now
    from retlens import paths

    for key, (xml, _, _) in rp.BUILTIN_FILES.items():
        with open(os.path.join(paths.robot_assets_dir(), "unitree_g1", xml), encoding="utf-8") as f:
            name = re.search(r"<mujoco\b[^>]*\bmodel\s*=\s*\"([^\"]+)\"", f.read(4096)).group(1)
        assert rp._LEGACY_NAMES[name] == key
        now = rp.load(key).ident
        assert rp.same_robot({"name": name, "digest": "e177d72e50b8", "key": xml}, now)
        assert rp.same_robot({"name": name, "digest": "e177d72e50b8"}, now)


def test_robot_without_torque_limits_says_so(tmp_path):
    """Joints with no torque limit of their own (actuatorfrcrange, a URDF's effort) nor a motor's: the physics assumes
    1000 N m there and judges no torque saturation, and the robot's notes (retlens-cli robot, the API) say on how many
    joints (was: only the result json's model text). The built-in G1's physics has its own torque table."""
    mj = pytest.importorskip("mujoco")
    from test_robot_profile import toybot

    path = toybot(str(tmp_path / "toy.xml"))
    n = rp.load(path).model().njnt - 1
    assert f"torque limits missing on {n} joints" in " ".join(rp.load(path).describe()["notes"])
    spec = mj.MjSpec.from_file(path)
    hinges = [j for j in spec.worldbody.find_all(mj.mjtObj.mjOBJ_JOINT) if j.type == mj.mjtJoint.mjJNT_HINGE]
    for j in hinges[2:]:  # their own limit
        j.actfrclimited, j.actfrcrange = mj.mjtLimited.mjLIMITED_TRUE, [-50.0, 50.0]
    spec.add_actuator(name="m0", target=hinges[0].name, trntype=mj.mjtTrn.mjTRN_JOINT, gear=[100, 0, 0, 0, 0, 0],
                      ctrllimited=mj.mjtLimited.mjLIMITED_TRUE, ctrlrange=[-1.0, 1.0])  # a motor of 100 N m
    one = str(tmp_path / "one.xml")
    with open(one, "w", encoding="utf-8") as f:
        f.write(spec.to_xml())
    notes = " ".join(rp.load(one).describe()["notes"])
    assert "torque limits missing on 1 joint " in notes
    hinges[1].actfrclimited, hinges[1].actfrcrange = mj.mjtLimited.mjLIMITED_TRUE, [-20.0, 20.0]
    every = str(tmp_path / "every.xml")
    with open(every, "w", encoding="utf-8") as f:
        f.write(spec.to_xml())
    assert "torque limits" not in " ".join(rp.load(every).describe()["notes"])
    try:
        g1 = rp.load("unitree_g1")
        notes = g1.parts.notes
    except (rp.RobotError, ImportError) as e:
        pytest.skip(str(e))
    assert not any("torque limits" in x for x in notes)


def test_the_shipped_g1_file_is_the_builtin_g1():
    """Browsing to the G1 model RetLens ships (환경 설정 > 로봇 모델 찾아보기...) chooses the built-in G1: its key, GMR's
    tuned configs, NVIDIA's USD and GMT, not a robot of its own."""
    _need_hands()
    from retlens import paths

    folder = os.path.join(paths.robot_assets_dir(), "unitree_g1")
    for key, (xml, name, _) in rp.BUILTIN_FILES.items():
        path = os.path.join(folder, xml)
        assert rp.canonical(path) == key and rp.is_builtin(path)
        if os.name == "nt":  # the same file however it is spelled
            assert rp.canonical(path.upper()) == key
        prof = rp.load(path)
        assert prof.key == key and prof.builtin and prof.name == name and prof is rp.load(key)
        s = settings.Settings(robot_model=f'"{path}"')
        assert settings.robot_spec(s) == key and settings.find_robot_usd(s).path is not None
    assert rp.canonical(None) == "unitree_g1" and rp.canonical("elsewhere/g1_mocap_29dof.xml") == "elsewhere/g1_mocap_29dof.xml"


def test_hands_model_has_the_g1_velocity_limits():
    """QC of the G1 with hands holds its body joints to the G1 URDF's velocity limits (was 25 rad/s for all, no URDF);
    it is still drawn from its MJCF (the URDF has no fingers), whose finger joints keep their own ranges."""
    hands = _need_hands()
    g1 = rp.load("unitree_g1")
    assert hands.urdf is None and hands.limits_urdf
    lim, ref = hands.limits(), g1.limits()
    body = [n for n in lim if n in ref]
    assert len(body) == len(ref) and all(lim[n] == ref[n] for n in body)
    assert all(np.isfinite(lim[n][2]) for n in body)
    fingers = hands.finger_joints()
    assert fingers and all(lim[n][2] == np.inf and np.isfinite(lim[n][1]) for n in fingers)


# --------------------------------------------------------------------------- retargeting
def test_quiet_survives_overlapping_threads():
    """Two retargets quieting stdout at once (two motions opened together, a batch beside the window) leave the real
    stdout in place, whatever order they finish in."""
    from retlens.retarget import _quiet

    real = sys.stdout
    a_in, b_in, a_out = threading.Event(), threading.Event(), threading.Event()

    def a():
        with _quiet():
            a_in.set()
            b_in.wait(5)
        a_out.set()

    def b():
        a_in.wait(5)
        with _quiet():
            b_in.set()
            a_out.wait(5)

    ts = [threading.Thread(target=a), threading.Thread(target=b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert sys.stdout is real


def _walk(tmp_path, name: str, seconds: float, fps: float = 30.0) -> str:
    p = tmp_path / name
    p.write_text(walking_bvh_text(seconds=seconds, fps=fps))
    return str(p)


def test_clips_too_short_to_smooth_and_odd_cutoffs(tmp_path, monkeypatch):
    """A clip of under 4 frames retargets unsmoothed (was KeyError: 'smoothing'), as does a cutoff <= 0; a cutoff at
    or above Nyquist stops before the IK."""
    _need_retargeting()
    from retlens import retarget

    path = _walk(tmp_path, "short.bvh", 0.1)  # 3 frames at 30 fps
    m, info = retarget.retarget_file(path, fps=30.0, smooth_hz=6.0, log=None)
    assert m.num_frames == 3 and info["smoothing"] is None and any("부드럽게" in n for n in info["notes"])
    m, info = retarget.retarget_file(path, fps=30.0, smooth_hz=-1.0, log=None)
    assert m.num_frames == 3 and info["smoothing"] is None

    def no_ik(*a, **k):
        raise AssertionError("the IK ran")

    monkeypatch.setattr(retarget, "run_gmr", no_ik)
    with pytest.raises(ValueError, match="Nyquist"):
        retarget.retarget_file(path, fps=30.0, smooth_hz=20.0, log=None)


def _biped(bare_root: bool):
    """3ds Max Biped's classic layout: clavicles under 'Bip001 Neck', optionally the 'Bip001' centre-of-mass bone."""
    body = {"Pelvis": None, "Spine": "Pelvis", "Spine1": "Spine", "Spine2": "Spine1", "Neck": "Spine2", "Head": "Neck"}
    for s in "LR":
        body.update({f"{s} Clavicle": "Neck", f"{s} UpperArm": f"{s} Clavicle", f"{s} Forearm": f"{s} UpperArm",
                     f"{s} Hand": f"{s} Forearm", f"{s} Thigh": "Pelvis", f"{s} Calf": f"{s} Thigh",
                     f"{s} Foot": f"{s} Calf", f"{s} Toe0": f"{s} Foot"})
    keys = list(body)
    names = [f"Bip001 {k}" for k in keys]
    parents = [keys.index(body[k]) if body[k] else -1 for k in keys]
    if bare_root:
        names, parents = ["Bip001"] + names, [-1] + [p + 1 if p >= 0 else 0 for p in parents]
    return names, np.array(parents)


def test_biped_classic_layout_resolves():
    """The chest is the spine joint the clavicles' neck hangs from (was the neck: the robot torso nodded with the
    head), and a bare 'Bip001' bone does not stop the prefix from being stripped (was: no Left UpLeg joint)."""
    from retlens.autolabel.body import joint_index
    from retlens.retarget import _resolve_bvh_bodies, _strip_common_prefix

    assert _strip_common_prefix(["Bip001", "Bip001 Pelvis", "Bip001 L Thigh"]) == ["Bip001", "Pelvis", "L Thigh"]
    assert _strip_common_prefix(["mixamorig:Hips", "mixamorig:Spine"]) == ["Hips", "Spine"]
    assert _strip_common_prefix(["pelvis", "left_hip", "spine3"]) == ["pelvis", "left_hip", "spine3"]
    for bare in (False, True):
        names, parents = _biped(bare)
        idx = _resolve_bvh_bodies(names, parents)
        assert names[idx["Hips"]] == "Bip001 Pelvis" and names[idx["Spine2"]] == "Bip001 Spine2"
        assert names[idx["LeftUpLeg"]] == "Bip001 L Thigh" and names[idx["RightArm"]] == "Bip001 R UpperArm"
        h = SkeletonMotion("b", names, parents, np.zeros((2, len(names), 3)), 30.0)
        assert names[joint_index(h)["spine3"]] == "Bip001 Spine2"
    # layouts whose shoulders hang from the chest keep it (Mixamo / CMU, SMPL-X)
    names = ["Hips", "Spine", "Spine2", "Neck", "LeftShoulder", "LeftArm"]
    assert _resolve_chest(names, [-1, 0, 1, 2, 2, 4], "LeftArm") == "Spine2"
    names = ["pelvis", "spine3", "neck", "left_collar", "left_shoulder"]
    assert _resolve_chest(names, [-1, 0, 1, 1, 3], "left_shoulder") == "spine3"


def _resolve_chest(names, parents, arm):
    from retlens.retarget import _arm_chest

    return names[_arm_chest(names, np.array(parents), names.index(arm))]


def test_lafan1_upsampling_interpolates(tmp_path):
    """A LAFAN1 BVH (30 fps) asked for at 60 fps: every other frame lies between its neighbours (was a repeat of
    one: stair-stepped motion); the source frames stay; a lower rate still picks frames."""
    pytest.importorskip("scipy")
    from retlens.retarget import load_bvh_gmr

    p = tmp_path / "lafan.bvh"
    p.write_text(walking_bvh_text(seconds=1.0, fps=30).replace("Spine1", "Spine2"))
    src = load_bvh_gmr(str(p), "lafan1", fps=30.0).frames
    up = load_bvh_gmr(str(p), "lafan1", fps=60.0)
    assert up.fps == 60.0 and len(up.frames) == 2 * len(src) - 1
    for k in ("Hips", "LeftFootMod", "RightHand"):
        P = np.array([fr[k][0] for fr in up.frames])
        np.testing.assert_allclose(P[::2], [fr[k][0] for fr in src], atol=1e-9)
        np.testing.assert_allclose(P[1::2], (P[:-1:2] + P[2::2]) / 2, atol=1e-9)
        Q, S = np.array([fr[k][1] for fr in up.frames]), np.array([fr[k][1] for fr in src])
        assert np.all(np.abs(np.einsum("ij,ij->i", Q[::2], S)) > 1 - 1e-9)  # the same rotations (q ~ -q)
    assert np.all(np.linalg.norm(np.diff([fr["Hips"][0] for fr in up.frames], axis=0), axis=1) > 1e-4)
    down = load_bvh_gmr(str(p), "lafan1", fps=15.0)
    assert len(down.frames) >= 14 and all(np.array_equal(a["Hips"][0], b["Hips"][0])
                                          for a, b in zip(down.frames, src[::2]))


def test_nokov_retargets_to_the_g1_with_hands(tmp_path):
    """--format nokov with unitree_g1_with_hands (was KeyError: 'unitree_g1_with_hands'); a GMR config that does not
    exist for a built-in says so."""
    _need_retargeting()
    _need_hands()
    from retlens.retarget import retarget_file, run_gmr

    p = tmp_path / "nokov.bvh"
    p.write_text(walking_bvh_text(seconds=0.5, fps=30).replace("Spine1", "Spine2").replace("Toe", "ToeBase"))
    m, info = retarget_file(str(p), robot="unitree_g1_with_hands", fmt="nokov", log=None)
    assert m.num_frames == 15 and np.isfinite(m.dof_pos).all() and info["robot"] == "unitree_g1_with_hands"
    with pytest.raises(ValueError, match="bvh_xsens"):
        run_gmr(None, "unitree_g1_with_hands", "bvh_xsens")


# --------------------------------------------------------------------------- settings
@pytest.fixture
def user(tmp_path, monkeypatch):
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "user"))
    os.makedirs(tmp_path / "user")
    settings.load(reload=True)
    yield tmp_path / "user"
    monkeypatch.setenv("RETLENS_USER_DIR", str(tmp_path / "after"))
    settings.load(reload=True)


def _write(text: str, encoding: str = "utf-8"):
    with open(settings.settings_path(), "w", encoding=encoding) as f:
        f.write(text)


def test_settings_with_a_byte_order_mark(user):
    """A settings.json saved with a UTF-8 BOM (Notepad, PowerShell 5.1) is read, and a save keeps what it held."""
    _write(json.dumps({"robot_model": "unitree_g1_with_hands", "library_dirs": ["D:\\mocap"], "api_port": 9001,
                       "future_x": 42}), "utf-8-sig")
    s = settings.load(reload=True)
    assert (s.robot_model, s.library_dirs, s.api_port) == ("unitree_g1_with_hands", ["D:\\mocap"], 9001)
    settings.save(s)
    with open(settings.settings_path(), encoding="utf-8") as f:
        data = json.load(f)
    assert data["robot_model"] == "unitree_g1_with_hands" and data["future_x"] == 42
    assert "settings" not in {c.key for c in settings.check_all()}


@pytest.mark.parametrize("text", ["null", "[]", '"x"', "5"])
def test_settings_that_are_not_an_object(user, text):
    _write(text)
    assert settings.load(reload=True) == settings.Settings()
    assert settings.robot_spec() == "unitree_g1"
    assert "settings" in {c.key for c in settings.check_all()}  # no crash, and it is said


def test_settings_values_of_the_wrong_type(user, capsys):
    """Hand-edited values of the wrong type keep their defaults (said once), instead of stopping the editor and the
    CLI; one folder written as a string is a list of one (was split into characters, the drive root among them)."""
    _write(json.dumps({"robot_model": None, "video_dir": 5, "check_updates": "false", "api_port": "abc",
                       "library_dirs": "D:\\mocap", "blender": "C:\\b\\blender.exe"}))
    s = settings.load(reload=True)
    assert s.robot_model == "" and s.video_dir == "" and s.check_updates is True and s.api_port == 8765
    assert s.library_dirs == ["D:\\mocap"] and s.blender == "C:\\b\\blender.exe"
    assert settings.robot_spec() == "unitree_g1"
    checks = {c.key: c for c in settings.check_all()}
    assert not checks["settings"].ok and "robot_model" in checks["settings"].detail
    assert "robot_model" in capsys.readouterr().err
    settings.load(reload=True)
    assert "robot_model" not in capsys.readouterr().err  # once
    _write(json.dumps({"library_dirs": ["relative\\dir", 3, "C:\\abs"], "api_port": 80}))
    s = settings.load(reload=True)
    assert s.library_dirs == ["relative\\dir", "C:\\abs"] and s.api_port == 8765
    assert os.path.abspath("relative\\dir") not in settings.library_dirs(s)
    assert os.path.abspath("C:\\abs") in settings.library_dirs(s)


def test_unreadable_settings_are_kept_aside_on_save(user):
    """A settings.json that does not parse (a trailing comma) gives defaults; the next save moves it to
    settings.json.broken rather than overwriting the user's values, and the check names that file."""
    text = '{"blender": "C:\\\\keep\\\\blender.exe",}'
    _write(text)
    s = settings.load(reload=True)
    assert s == settings.Settings()
    c = next(c for c in settings.check_all() if c.key == "settings")
    assert not c.ok and not c.required and ".broken" in c.hint
    settings.save(s)
    broken = settings.settings_path() + ".broken"
    with open(broken, encoding="utf-8") as f:
        assert f.read() == text
    c = next(c for c in settings.check_all() if c.key == "settings")  # right after the save: no stale "defaults"
    assert c.path == broken and broken in c.hint and "기본값" not in c.detail
    assert settings.load(reload=True) == settings.Settings()  # the new file reads
    c = next(c for c in settings.check_all() if c.key == "settings")
    assert c.path == broken and broken in c.hint


def test_settings_check_clears_once_saved(user):
    """A save writes every value with its type: the row about wrong-typed values goes with the file it was about."""
    _write(json.dumps({"robot_model": None, "blender": "C:\\b\\blender.exe"}))
    s = settings.load(reload=True)
    assert "settings" in {c.key for c in settings.check_all()}
    settings.save(s)
    assert "settings" not in {c.key for c in settings.check_all()}
    assert settings.load(reload=True).blender == "C:\\b\\blender.exe"
    assert "settings" not in {c.key for c in settings.check_all()}


def test_video_check_hints_only_when_not_ok(user, tmp_path, monkeypatch):
    """The video folder check says how to fix it only when the folder cannot be written to, like every other check
    (`info` and the API carried "쓸 수 있는 폴더를 지정하세요" beside ok: true)."""
    s = settings.Settings(video_dir=str(tmp_path / "videos"))
    c = next(c for c in settings.check_all(s) if c.key == "video")
    assert c.ok and c.hint == ""
    monkeypatch.setattr(settings, "_writable", lambda folder: False)
    c = next(c for c in settings.check_all(s) if c.key == "video")
    assert not c.ok and c.hint == "쓸 수 있는 폴더를 지정하세요"


# --------------------------------------------------------------------------- fingers
def test_finger_reference_is_reported_per_joint():
    """Where the bends count from: the rest pose where it is straight, the clip's most open pose where it is curled
    (3ds Max Biped) or there is none; reported as "rest pose" / "clip" / "mixed" with the counts."""
    from scipy.spatial.transform import Rotation

    from retlens import fingers
    from test_fingers import _hand_person, _person

    h = _hand_person()
    hands = fingers.human_fingers(h)
    rest = h.meta["rest_pose"][0].copy()
    used = {}
    fingers.finger_bends(h, hands["left"], np.array([0.0, 1.0]), rest, used)
    n = used["rest"]
    assert n > 0 and "clip" not in used
    i2 = h.joint_names.index("LeftHandIndex2")
    turn = Rotation.from_euler("x", -45, degrees=True).as_matrix()  # the index curled at rest
    for k in (i2 + 1, i2 + 2):
        rest[k] = rest[i2] + turn @ (rest[k] - rest[i2])
    used = {}
    fingers.finger_bends(h, hands["left"], np.array([0.0, 1.0]), rest, used)
    assert used == {"rest": n - 1, "clip": 1}
    used = {}
    fingers.finger_bends(h, hands["left"], np.array([0.0, 1.0]), None, used)
    assert used == {"clip": n}

    prof = _need_hands()
    names = prof.joint_names()
    m = RobotMotion(name="r", joint_names=names, root_pos=np.zeros((2, 3)), root_quat=np.tile([1.0, 0, 0, 0], (2, 1)),
                    dof_pos=np.zeros((2, len(names))), fps=30.0)
    person = _person(30.0)
    _, info = fingers.retarget_fingers(m, person, prof)
    assert info["rest"] == "rest pose" and info["rest_joints"]["clip"] == 0 and info["version"] == fingers.VERSION
    rest = person.meta["rest_pose"][0].copy()
    pip = person.joint_names.index("RightHandIndex2")
    rest[pip + 1:pip + 3] = rest[pip] + (rest[pip + 1:pip + 3] - rest[pip]) @ turn.T  # curled at its middle joint
    person.meta["rest_pose"] = (rest, None)
    _, info = fingers.retarget_fingers(m, person, prof)
    assert info["rest"] == "mixed" and info["rest_joints"]["rest"] > 0 and info["rest_joints"]["clip"] > 0
    person.meta.pop("rest_pose")
    _, info = fingers.retarget_fingers(m, person, prof)
    assert info["rest"] == "clip" and info["rest_joints"]["rest"] == 0


# --------------------------------------------------------------------------- tools/retarget.py
def _tool():
    spec = importlib.util.spec_from_file_location("retarget_tool", os.path.join(ROOT, "tools", "retarget.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tool_names_inputs_that_share_a_name(tmp_path):
    """One take in two folders, or as .bvh and .fbx: each gets its own output (was: the second skipped or
    overwriting the first, counted ok); other names stay <clip>."""
    tool = _tool()
    a = [str(tmp_path / "a" / "subjA" / "walk.bvh"), str(tmp_path / "a" / "subjB" / "walk.bvh"),
         str(tmp_path / "b" / "run.bvh"), str(tmp_path / "b" / "run.fbx"), str(tmp_path / "c" / "jump.bvh")]
    assert tool.output_stems(a) == ["subjA_walk_bvh", "subjB_walk_bvh", "run_bvh", "run_fbx", "jump"]


def test_tool_folder_inputs_are_motions_only(tmp_path, monkeypatch, capsys):
    """In a folder: AMASS *_stagei.npz shape files and cache folders are not inputs (each was a [FAIL]); an .npz
    that is no AMASS motion (an earlier output) is skipped and counted so; a file given twice runs once."""
    tool = _tool()
    d = tmp_path / "in"
    os.makedirs(d / "cache")
    walk = d / "walk.bvh"
    walk.write_text(walking_bvh_text(seconds=0.2, fps=30))
    (d / "cache" / "x.bvh").write_text("")
    np.savez(d / "neutral_stagei.npz", betas=np.zeros(16))
    robot = RobotMotion(name="r", joint_names=["j"], root_pos=np.zeros((2, 3)), root_quat=np.tile([1.0, 0, 0, 0], (2, 1)),
                        dof_pos=np.zeros((2, 1)), fps=30.0)
    robot.save_npz(str(d / "old_g1.npz"))
    found = list(tool.iter_inputs([str(d), str(walk)]))
    assert sorted(os.path.basename(p) for p, _ in found) == ["old_g1.npz", "walk.bvh"]
    assert all(in_folder for _, in_folder in found)

    _need_retargeting()
    os.remove(walk)
    monkeypatch.setattr(sys, "argv", ["retarget.py", str(d), "--out-dir", str(tmp_path / "out")])
    assert tool.main() == 0
    out = capsys.readouterr().out
    assert "not an AMASS SMPL-X motion" in out and "done: 0 ok, 1 skipped, 0 failed" in out


def _fake_retarget(tool, monkeypatch, calls: list):
    """tools/retarget.py without the robot or the IK: each input becomes a 2-frame robot motion."""
    def retarget_file(path, **_):
        calls.append(os.path.abspath(path))
        m = RobotMotion(name="r", joint_names=["j"], root_pos=np.zeros((2, 3)), root_quat=np.tile([1.0, 0, 0, 0], (2, 1)),
                        dof_pos=np.zeros((2, 1)), fps=30.0)
        return m, {"source": os.path.abspath(path), "ik_position_residual": {}, "smoothing": None, "ik_seconds": 0.0}

    monkeypatch.setattr(tool, "retarget_file", retarget_file)
    monkeypatch.setattr(tool, "profile", lambda robot: SimpleNamespace(tag="g1"))


def test_tool_fails_an_npz_that_does_not_read(tmp_path, monkeypatch, capsys):
    """In a folder, an AMASS npz cut short (an interrupted copy) or empty is a [FAIL] and the run exits 1 (was skipped
    as "not an AMASS SMPL-X motion", exit 0); a readable npz without pose_body is still skipped."""
    tool = _tool()
    calls = []
    _fake_retarget(tool, monkeypatch, calls)
    d = tmp_path / "in" / "S1"
    os.makedirs(d)
    np.savez(d / "walk_stageii.npz", pose_body=np.zeros((30, 63)), trans=np.zeros((30, 3)), betas=np.zeros(16))
    data = (d / "walk_stageii.npz").read_bytes()
    (d / "walk_stageii.npz").write_bytes(data[:len(data) // 2])
    (d / "empty_stageii.npz").write_bytes(b"")
    np.savez(d / "table.npz", x=np.zeros(3))
    monkeypatch.setattr(sys, "argv", ["retarget.py", str(tmp_path / "in"), "--out-dir", str(tmp_path / "out")])
    assert tool.main() == 1
    out = capsys.readouterr().out
    assert out.count("[FAIL]") == 2 and "walk_stageii.npz: ValueError" in out and "empty_stageii.npz: ValueError" in out
    assert "table.npz: not an AMASS SMPL-X motion" in out and "done: 0 ok, 1 skipped, 2 failed" in out and not calls


def test_tool_keeps_takes_of_one_name_apart_across_runs(tmp_path, monkeypatch, capsys):
    """A dataset retargeted folder by folder into one --out-dir: a take whose <clip>_<robot>.npz an earlier run wrote
    from another file gets its folder's name (was: skipped as existing, or replaced with --overwrite); a later run
    over both folders finds each take's output where it is (was: subject B's take made a second time)."""
    tool = _tool()
    calls = []
    _fake_retarget(tool, monkeypatch, calls)
    root, out = tmp_path / "in", tmp_path / "out"
    a, b = root / "subjA" / "walk.bvh", root / "subjB" / "walk.bvh"
    for p in (a, b):
        os.makedirs(p.parent)
        p.write_text(walking_bvh_text(seconds=0.2, fps=30))

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["retarget.py", *args, "--out-dir", str(out)])
        code = tool.main()
        return code, capsys.readouterr().out

    def source(name):
        with open(out / f"{name}.json", encoding="utf-8") as f:
            return os.path.normcase(json.load(f)["source"])

    assert run(str(b.parent))[0] == 0 and calls == [str(b)]
    code, text = run(str(a.parent))
    assert code == 0 and "done: 1 ok, 0 skipped" in text and calls[-1] == str(a)
    assert source("walk_g1") == os.path.normcase(str(b)) and source("subjA_walk_bvh_g1") == os.path.normcase(str(a))
    code, text = run(str(a.parent), "--overwrite")  # redoes subject A's own output only
    assert code == 0 and calls[-1] == str(a) and source("walk_g1") == os.path.normcase(str(b))
    del calls[:]
    code, text = run(str(root))
    assert code == 0 and "done: 0 ok, 2 skipped, 0 failed" in text and not calls
    code, text = run(str(root), "--overwrite")
    assert code == 0 and sorted(calls) == [str(a), str(b)]
    assert sorted(f for f in os.listdir(out) if f.endswith(".npz")) == ["subjA_walk_bvh_g1.npz", "walk_g1.npz"]
    assert source("walk_g1") == os.path.normcase(str(b)) and source("subjA_walk_bvh_g1") == os.path.normcase(str(a))

    # the dataset moved (another drive letter, a renamed folder above it): its jsons name files that are gone, and
    # each take still finds its own output by its folder and file name (none is made again under a longer name)
    moved = tmp_path / "moved"
    os.rename(root, moved)
    del calls[:]
    code, text = run(str(moved / "subjA"))
    assert code == 0 and "done: 0 ok, 1 skipped, 0 failed" in text and "subjA_walk_bvh_g1.npz exists" in text
    code, text = run(str(moved))
    assert code == 0 and "done: 0 ok, 2 skipped, 0 failed" in text and not calls
    code, text = run(str(moved / "subjB"), "--overwrite")
    assert code == 0 and calls == [str(moved / "subjB" / "walk.bvh")]
    assert sorted(f for f in os.listdir(out) if f.endswith(".npz")) == ["subjA_walk_bvh_g1.npz", "walk_g1.npz"]
    assert source("walk_g1") == os.path.normcase(str(moved / "subjB" / "walk.bvh"))


def test_tool_folder_leaves_out_a_takes_prop_file(tmp_path):
    """A prop FBX one folder above the people who use it (props.find_props) is no input of a folder, as in the batch,
    the window and the API (was: Blender ran on the prop-only file and the run failed)."""
    tool = _tool()
    day = tmp_path / "day"
    os.makedirs(day / "s1")
    for p in ("pick_010_Prop.fbx", os.path.join("s1", "pick_010.fbx")):
        (day / p).write_bytes(b"")
    assert [os.path.relpath(p, day) for p, _ in tool.iter_inputs([str(day)])] == [os.path.join("s1", "pick_010.fbx")]
    # given as a file it is read all the same
    assert [p for p, _ in tool.iter_inputs([str(day / "pick_010_Prop.fbx")])] == [str(day / "pick_010_Prop.fbx")]
