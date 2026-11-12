"""Reading motion files, pairing a C3D with its solved motion, props and hand-object contact: the cases a file
from outside RetLens brings (non-ASCII paths, BOMs, spaces in names, empty or cut files, tables beside motions,
several armatures in one FBX). Data is made in the test; the CMU sample C3D / BVH are used when present."""

import os
import shutil
import subprocess
import sys
import textwrap

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from retlens import compare, objects, props  # noqa: E402
from retlens.io import load_motion  # noqa: E402
from retlens.io.bvh import bvh_rest_pose, load_bvh  # noqa: E402
from retlens.motion import ObjectTrack, RobotMotion, SkeletonMotion  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")
C3D = os.path.join(RAW, "cmu_c3d", "02_01.c3d")
BVH = os.path.join(RAW, "cmu_bvh", "02_01.bvh")

# a small BVH: hips, a spine and two legs, 3 frames
BVH_TEXT = textwrap.dedent("""\
    HIERARCHY
    ROOT Hips
    {
      OFFSET 0 0 0
      CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
      JOINT Spine
      {
        OFFSET 0 10 0
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
          OFFSET 0 10 0
        }
      }
      JOINT LeftUpLeg
      {
        OFFSET 10 0 0
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
          OFFSET 0 -40 0
        }
      }
    }
    MOTION
    Frames: 3
    Frame Time: 0.033333
    0 90 0 0 0 0 0 0 0 0 0 0
    1 90 0 0 0 0 0 10 0 0 0 0
    2 90 0 0 0 0 0 20 0 0 0 0
    """)


def _write(path, text: str, encoding="utf-8") -> str:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)
    return str(path)


# --------------------------------------------------------------------------- C3D: its solved motion
def test_find_take_prefers_the_solve_beside_the_c3d(tmp_path, monkeypatch):
    """Another session's take of the same name in a motion folder never beats the solve next to the C3D."""
    here, lib = tmp_path / "session2", tmp_path / "library"
    c3d = _write(here / "Take_001.c3d", "")
    local_fbx = _write(here / "Take_001.fbx", "")
    lib_bvh = _write(lib / "Take_001.bvh", "")
    monkeypatch.setattr(compare, "library_files", lambda roots=None: {"library": [lib_bvh]})
    assert compare.find_take(c3d) == os.path.abspath(local_fbx)  # an FBX beside it beats a BVH elsewhere
    local_bvh = _write(here / "Take_001.bvh", "")
    assert compare.find_take(c3d) == os.path.abspath(local_bvh)  # beside it: BVH before FBX as before
    other = _write(tmp_path / "session3" / "Take_001.c3d", "")
    assert compare.find_take(other) == os.path.abspath(lib_bvh)  # nothing beside it: the motion folders


def test_find_take_lists_the_motion_folders_only_without_a_solve_beside_it(tmp_path, monkeypatch):
    c3d = _write(tmp_path / "here" / "Take_001.c3d", "")
    local = _write(tmp_path / "here" / "Take_001.bvh", "")
    monkeypatch.setattr(compare, "library_files", lambda roots=None: pytest.fail("motion folders listed"))
    assert compare.find_take(c3d) == os.path.abspath(local)


@pytest.mark.skipif(not (os.path.isfile(C3D) and os.path.isfile(BVH)), reason="needs data/raw/cmu_c3d and cmu_bvh")
def test_c3d_gets_the_retarget_score_of_its_solve(tmp_path, monkeypatch):
    """A C3D's robot is its solved skeleton's retarget: it gets that score, quality rows and problem spans."""
    from retlens import analysis

    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "cache"))  # not the developer's retarget cache
    shutil.copy(C3D, tmp_path / "02_01.c3d")
    shutil.copy(BVH, tmp_path / "02_01.bvh")
    fk = analysis.FootKinematics("unitree_g1")
    c3d = compare.load_item(str(tmp_path / "02_01.c3d"), log=None)
    bvh = compare.load_item(str(tmp_path / "02_01.bvh"), log=None)
    assert c3d.info["solved_motion"] == os.path.abspath(tmp_path / "02_01.bvh") and c3d.human.kind == "markers"
    assert not c3d.info["c3d"].get("solved_elsewhere") and not c3d.info["c3d"].get("take_warning")
    assert compare.measured_human(c3d) is c3d.solved_human and compare.measured_human(bvh) is bvh.human
    compare.compute_metrics(c3d, fk, {})
    compare.compute_metrics(bvh, fk, {})
    assert c3d.metrics["retarget_score"] is not None and c3d.metrics["retarget_score"] == bvh.metrics["retarget_score"]
    assert c3d.metrics["pose_err_deg"] == bvh.metrics["pose_err_deg"] and "_quality" in c3d.metrics
    assert set(bvh.metrics["_problems"]) <= set(c3d.metrics["_problems"])  # its own: marker gaps
    assert os.listdir(tmp_path / "cache")


OTHER_BVH = os.path.join(RAW, "cmu_bvh", "02_03.bvh")


@pytest.mark.skipif(not (os.path.isfile(C3D) and os.path.isfile(BVH) and os.path.isfile(OTHER_BVH)),
                    reason="needs data/raw/cmu_c3d and cmu_bvh")
def test_take_warning_for_another_takes_solve_only():
    """Another take's solve sits far from the pelvis markers; a solve whose root is off the marker centre sits up to
    ~11 cm off on its own take, which is no warning while the lengths agree."""
    from retlens.io.c3d import load_c3d
    from retlens.markers import align_to_skeleton, marker_skeleton

    markers = marker_skeleton(load_c3d(C3D))
    for solve, other in ((BVH, False), (OTHER_BVH, True)):
        skel = compare.load_skeleton(solve)
        _, fit = align_to_skeleton(markers, skel)
        warning = compare._take_warning(fit["residual_cm"], markers.duration, skel.duration, solve)
        assert bool(warning) == other, (solve, fit["residual_cm"], warning)
    assert compare._take_warning(10.9, 9.68, 9.63, "143_13.fbx") is None  # CMU 143_13's own FBX solve
    assert "다른 촬영" in compare._take_warning(25.0, 9.7, 9.7, "x.fbx")
    assert "길이도 달라" in compare._take_warning(12.0, 9.7, 4.8, "x.fbx")
    assert compare._take_warning(float("nan"), 9.7, 4.8, "x.fbx") is None


@pytest.mark.skipif(not os.path.isfile(C3D), reason="needs data/raw/cmu_c3d (CMU sample C3D)")
def test_c3d_in_a_korean_folder(tmp_path, monkeypatch):
    from retlens.io import c3d

    made = []
    real = c3d._ascii_temp_dir
    monkeypatch.setattr(c3d, "_ascii_temp_dir", lambda: made.append(real()) or made[-1])
    path = tmp_path / "모션 캡처" / "걷기 01.c3d"
    os.makedirs(path.parent)
    shutil.copy(C3D, path)
    m = load_motion(str(path))
    assert m.num_frames == 343 and m.name == "걷기 01" and m.source == os.path.abspath(path)
    assert made and not os.path.exists(made[0])  # read from an ASCII copy, which is gone again
    ascii_path = tmp_path / "plain" / "02_01.c3d"
    os.makedirs(ascii_path.parent)
    shutil.copy(C3D, ascii_path)
    assert load_motion(str(ascii_path)).num_frames == 343
    if str(ascii_path).isascii():
        assert len(made) == 1  # an ASCII path is read in place


def test_broken_c3d_says_so(tmp_path):
    pytest.importorskip("ezc3d")
    bad = _write(tmp_path / "bad.c3d", "not a c3d file\n" * 20)
    with pytest.raises(ValueError, match="C3D 파일을 읽지 못했습니다"):
        load_motion(bad)
    with pytest.raises(FileNotFoundError):
        load_motion(str(tmp_path / "missing.c3d"))


# --------------------------------------------------------------------------- what the motion lists show
def test_tables_beside_motions_are_not_motions(tmp_path):
    robot = _write(tmp_path / "walk.csv", ",".join(["0.1"] * 36) + "\n" + ",".join(["0.2"] * 36) + "\n")
    batch = _write(tmp_path / "retlens_batch.csv", "모션,결과\n02_01,PASS\n", encoding="utf-8-sig")
    meta = _write(tmp_path / "metadata.csv", "file_name,description\n02_01.fbx,walk\n")
    _write(tmp_path / "export" / "manifest.json", "{}")
    manifest = _write(tmp_path / "export" / "manifest.csv", "file,seconds\nclips/02_01.npz,2.8\n", encoding="utf-8-sig")
    assert compare.is_motion_file(robot)
    assert not any(compare.is_motion_file(p) for p in (batch, meta, manifest))
    assert compare.library_files([str(tmp_path)]) == {compare.paths.rel(str(tmp_path), compare.ROOT).replace(os.sep, "/"):
                                                      [robot]}


def test_csv_listing_reads_each_file_once_and_skips_comments(tmp_path, monkeypatch):
    """np.savetxt(header=...) writes the header as a '#' comment, which the robot csv reader skips: still listed.
    The first-line check is kept per file version, so a folder of thousands of csvs is not read again per listing."""
    rows = np.zeros((3, 36))
    rows[:, 6] = 1.0
    commented = tmp_path / "walk_header.csv"
    np.savetxt(commented, rows, delimiter=",", header=",".join(["x", "y", "z", "qx", "qy", "qz", "qw"] + ["j"] * 29))
    inline = _write(tmp_path / "walk_note.csv", "\n# exported\n" + ",".join(["0"] * 36) + "  # first frame\n")
    words = _write(tmp_path / "table.csv", "# notes\nname,seconds,a,b,c,d,e,f\n")
    _write(tmp_path / "sub" / "cache" / "hidden.csv", ",".join(["0"] * 8) + "\n")
    assert compare.is_motion_file(str(commented)) and load_motion(str(commented)).num_frames == 3
    assert compare.is_motion_file(inline) and not compare.is_motion_file(words)
    listed = compare.library_files([str(tmp_path)])
    assert list(listed.values()) == [[str(commented), inline]]  # cache folders are not entered
    assert compare._numeric_first_line.cache_info().maxsize is None  # no eviction: a big folder never thrashes
    monkeypatch.setattr(compare, "open", lambda *a, **k: pytest.fail("csv read again"), raising=False)
    monkeypatch.setattr(os, "stat", lambda *a, **k: pytest.fail("stat per csv"))  # the listing's entries carry it
    assert compare.library_files([str(tmp_path)]) == listed


# --------------------------------------------------------------------------- odd files: clear messages
def test_bvh_names_with_spaces_bom_and_compact_braces(tmp_path):
    ref = load_bvh(_write(tmp_path / "plain.bvh", BVH_TEXT))
    spaced = load_bvh(_write(tmp_path / "spaced.bvh", BVH_TEXT.replace("ROOT Hips", "ROOT Bip001 Pelvis")
                             .replace("JOINT LeftUpLeg", "JOINT Bip001 L Thigh")))
    assert spaced.joint_names == ["Bip001 Pelvis", "Spine", "Spine_end", "Bip001 L Thigh", "Bip001 L Thigh_end"]
    assert ref.joint_names == ["Hips", "Spine", "Spine_end", "LeftUpLeg", "LeftUpLeg_end"]
    assert np.allclose(spaced.positions, ref.positions)
    bom = _write(tmp_path / "bom.bvh", BVH_TEXT, encoding="utf-8-sig")
    assert np.allclose(load_bvh(bom).positions, ref.positions) and bvh_rest_pose(bom)[0] == ref.joint_names
    compact = BVH_TEXT.replace("ROOT Hips\n{", "ROOT Hips {").replace("JOINT Spine\n  {", "JOINT Spine {")
    assert load_bvh(_write(tmp_path / "compact.bvh", compact)).joint_names == ref.joint_names
    worded = load_bvh(_write(tmp_path / "worded.bvh", BVH_TEXT.replace("ROOT Hips", "ROOT Bip001 Root")
                             .replace("JOINT Spine", "JOINT Spine End Joint")))  # BVH words inside a name
    assert worded.joint_names[:3] == ["Bip001 Root", "Spine End Joint", "Spine End Joint_end"]
    one_line = BVH_TEXT.replace("JOINT Spine\n  {\n    OFFSET", "JOINT Spine { OFFSET")  # more after the name
    assert one_line != BVH_TEXT and load_bvh(_write(tmp_path / "one_line.bvh", one_line)).joint_names == ref.joint_names


ODD_FILES = [
    ("empty.bvh", "", "비었습니다"),
    ("header_only.bvh", BVH_TEXT[:BVH_TEXT.index("MOTION")], "MOTION 부분이 없음"),
    ("no_frames.bvh", BVH_TEXT[:BVH_TEXT.index("Frames")], "잘렸습니다"),
    ("cut_number.bvh", BVH_TEXT.rstrip()[:-6] + " -", "숫자"),
    ("cut_block.bvh", BVH_TEXT.rsplit("\n", 2)[0], "동작 부분이 잘렸습니다"),
    ("empty.csv", "", "빈 csv"),
    ("header.csv", "x,y,z,qx,qy,qz,qw,j1\n0,0,0,0,0,0,1,0\n", "Unitree 로봇 csv가 아닙니다"),
    ("short.csv", "1,2,3\n", "Unitree 로봇 csv가 아닙니다"),
    ("cut_row.csv", "0,0,0,0,0,0,1,0\n0,0,0,0,0,0,1,0\n0,0,0,0\n", "3번째 줄의 열이 4개로 .*잘렸을 수 있음"),
    ("cut_cell.csv", "0,0,0,0,0,0,1,0\n0,0,0,0,0,0,1,-\n", "2번째 줄 8번째 칸.*숫자로 읽지 못했습니다"),
    ("cut_row_header.csv", "# x,y,z\n0,0,0,0,0,0,1,0\n\n0,0,0,0\n", "4번째 줄의 열이 4개로"),  # the file's own lines
    ("cut_cell_header.csv", "# x,y,z\n\n0,0,0,0,0,0,1,0\n0,0,x,0,0,0,1,0\n", "4번째 줄 3번째 칸"),
    ("notzip.npz", "this is not a zip", "올바른 .npz"),
    ("empty.npz", "", "올바른 .npz"),
    ("text.pkl", "this is not a pickle\n", "GMR pkl 모션 파일이 아닙니다"),
    ("empty.pkl", "", "GMR pkl 모션 파일이 아닙니다"),
]


@pytest.mark.parametrize("name, text, match", ODD_FILES, ids=[c[0] for c in ODD_FILES])
def test_odd_files_give_clear_errors(tmp_path, name, text, match):
    path = _write(tmp_path / name, text)
    with pytest.raises(ValueError, match=match):
        load_motion(path)
    with pytest.raises(ValueError, match=match):
        compare.load_item(path, log=None)


def test_unsupported_file_type_message(tmp_path):
    with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
        compare.human_format(_write(tmp_path / "README.md", "# x"))


def test_other_pickles_are_not_gmr_motions(tmp_path):
    import pickle

    flat = {"dof_pos": [1.0, 2.0], "root_rot": [0, 0, 0, 1], "root_pos": [0, 0, 1]}  # one frame, not (T, n) arrays
    for i, obj in enumerate(({"something": 1}, [1, 2, 3], flat)):
        path = tmp_path / f"other_{i}.pkl"
        path.write_bytes(pickle.dumps(obj))
        with pytest.raises(ValueError, match="GMR pkl 모션 파일이 아닙니다"):
            load_motion(str(path))
    with pytest.raises(FileNotFoundError):
        load_motion(str(tmp_path / "missing.pkl"))


def test_unitree_csv_still_loads(tmp_path):
    rows = np.zeros((4, 36))
    rows[:, 6] = 1.0  # qw
    rows[:, 2] = 0.75
    path = tmp_path / "walk.csv"
    np.savetxt(path, rows, delimiter=",")
    m = load_motion(str(path))
    assert m.num_frames == 4 and m.dof_pos.shape == (4, 29) and np.allclose(m.root_quat[:, 0], 1.0)


# --------------------------------------------------------------------------- props
def test_shape_files_with_bom_or_korean_ansi(tmp_path):
    bom = _write(tmp_path / "a" / "props.json", '{"Ball": {"shape": "sphere", "diameter": 7.4}}', encoding="utf-8-sig")
    assert props.load_shapes(bom) == {"ball": {"shape": "sphere", "diameter": 7.4}}
    ansi = _write(tmp_path / "b" / "props.yaml", "# 공 크기\nBall: {shape: sphere, diameter: 8}\n", encoding="cp949")
    assert props.load_shapes(ansi) == {"ball": {"shape": "sphere", "diameter": 8}}


# --------------------------------------------------------------------------- hand-object contact
def _person_with_fingers(T: int, fps: float) -> SkeletonMotion:
    """A standing skeleton whose hands have two finger bases 9 cm past the wrist."""
    spec = [("Hips", None, (0, 0, 0.9)), ("LeftUpLeg", "Hips", (0.1, 0, 0.9)), ("LeftLeg", "LeftUpLeg", (0.1, 0, 0.5)),
            ("LeftFoot", "LeftLeg", (0.1, 0, 0.1)), ("RightUpLeg", "Hips", (-0.1, 0, 0.9)),
            ("RightLeg", "RightUpLeg", (-0.1, 0, 0.5)), ("RightFoot", "RightLeg", (-0.1, 0, 0.1)),
            ("Spine2", "Hips", (0, 0, 1.3)), ("LeftArm", "Spine2", (0.2, 0, 1.4)), ("LeftForeArm", "LeftArm", (0.45, 0, 1.4)),
            ("LeftHand", "LeftForeArm", (0.7, 0, 1.4)), ("LeftHandIndex1", "LeftHand", (0.79, 0.01, 1.4)),
            ("LeftHandThumb1", "LeftHand", (0.76, 0.04, 1.4)), ("RightArm", "Spine2", (-0.2, 0, 1.4)),
            ("RightForeArm", "RightArm", (-0.45, 0, 1.4)), ("RightHand", "RightForeArm", (-0.7, 0, 1.4))]
    names = [n for n, _, _ in spec]
    P = np.tile(np.array([p for _, _, p in spec], float), (T, 1, 1))
    return SkeletonMotion("person", names, np.array([names.index(p) if p else -1 for _, p, _ in spec]), P, fps)


def test_a_ball_held_in_the_fingers_counts_as_contact(monkeypatch):
    """A fingertip grip: the node sits 4 cm past the index base but ~9 cm from the palm point."""
    T, fps = 20, 20.0
    h = _person_with_fingers(T, fps)
    node = ObjectTrack("Ball_1", positions=np.tile([0.83, 0.01, 1.4], (T, 1)), rotations=np.tile(np.eye(3), (T, 1, 1)),
                       vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), int), kind="bone")
    h.objects = [node]
    palm = objects.palm_points(h)[0, 0]
    assert np.linalg.norm(palm - node.positions[0]) > objects.CONTACT_M  # the palm point alone would miss it
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.75], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=fps)
    mapped = objects.human_to_robot(node.positions, objects.human_scale(h, r), objects.anchor(h), r.root_pos[0])
    robot = np.zeros((T, 2, 3))
    robot[:, 0] = mapped - [0.03, 0.0, 0.0]
    robot[:, 1] = [-1.0, 0.0, 1.0]
    monkeypatch.setattr(objects, "robot_hands", lambda r, fk: robot)
    m = objects.hand_object_metrics(h, r, fk=None)
    assert m["hand_obj_contact_s"] == pytest.approx(T / fps) and m["hand_obj_reach_pct"] == pytest.approx(100.0)
    assert m["hand_obj_err_cm"] == pytest.approx(3.0, abs=0.1)


def test_a_fingertip_grip_copied_exactly_reaches_the_ball(monkeypatch):
    """The robot is measured at its palm point. For a ball held in the fingers the person's palm point is ~9 cm off,
    so a robot whose palm point lands where the person's maps is that far off too: it still reaches the ball. The
    allowance is the person's palm offset, not more."""
    T, fps = 20, 20.0
    h = _person_with_fingers(T, fps)
    h.objects = [ObjectTrack("Ball_1", positions=np.tile([0.83, 0.01, 1.4], (T, 1)),
                             rotations=np.tile(np.eye(3), (T, 1, 1)), vertices=np.zeros((0, 3)),
                             faces=np.zeros((0, 3), int), kind="bone")]
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.7], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=fps)
    scale, hips = objects.human_scale(h, r), objects.anchor(h)
    palm = objects.palm_points(h)
    exact = np.stack([objects.human_to_robot(palm[:, s], scale, hips, r.root_pos[0]) for s in range(2)], axis=1)
    off = 100 * np.linalg.norm(exact[0, 0] - objects.human_to_robot(h.objects[0].positions, scale, hips,
                                                                      r.root_pos[0])[0])
    assert off > 100 * objects.CONTACT_M  # the palm point alone is out of contact range
    for shift, reach in ((0.0, 100.0), (0.02, 100.0), (0.08, 0.0)):
        monkeypatch.setattr(objects, "robot_hands", lambda r, fk: exact + [0.0, 0.0, shift])
        m = objects.hand_object_metrics(h, r, fk=None)
        assert m["hand_obj_reach_pct"] == pytest.approx(reach), shift
    assert m["hand_obj_err_cm"] > off  # still the robot hand's distance itself


def test_hand_contact_ignores_points_not_seen(monkeypatch):
    """An object pose that is NaN in some frames: those are no touches. A finger base not seen: no touch through it.
    A palm point not seen (the hand joint missing): the finger base still touches, with no allowance for the robot."""
    T, fps = 25, 20.0
    h = _person_with_fingers(T, fps)
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.7], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=fps)
    scale, hips = objects.human_scale(h, r), objects.anchor(h)
    exact = objects.human_to_robot(objects.palm_points(h)[:, 0], scale, hips, r.root_pos[0])  # all seen yet
    h.positions[:5, h.joint_names.index("LeftHand")] = np.nan  # frames 0-4: palm point not seen
    h.positions[5:10, h.joint_names.index("LeftHandIndex1")] = np.nan  # frames 5-9: the touching finger not seen
    pos = np.tile([0.83, 0.01, 1.4], (T, 1))
    pos[20:] = np.nan  # frames 20-24: the ball not seen
    h.objects = [ObjectTrack("Ball_1", positions=pos, rotations=np.tile(np.eye(3), (T, 1, 1)),
                             vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), int), kind="bone")]
    robot = np.zeros((T, 2, 3))
    robot[:, 0] = exact
    robot[:, 1] = [-1.0, 0.0, 1.0]
    monkeypatch.setattr(objects, "robot_hands", lambda r, fk: robot)
    m = objects.hand_object_metrics(h, r, fk=None)
    assert m["hand_obj_contact_s"] == pytest.approx(15 / fps)  # frames 0-4 and 10-19
    assert m["hand_obj_reach_pct"] == pytest.approx(100 * 10 / 15, abs=0.1)  # not in frames 0-4: no allowance


def test_a_broken_mesh_vertex_is_no_surface_point(monkeypatch):
    """A NaN vertex (a broken mesh file) is left out of that object's surface; the other objects still count."""
    T, fps = 10, 20.0
    h = _person_with_fingers(T, fps)
    still = dict(rotations=np.tile(np.eye(3), (T, 1, 1)), faces=np.zeros((0, 3), int))
    h.objects = [ObjectTrack("Ball_1", positions=np.tile([0.83, 0.01, 1.4], (T, 1)), vertices=np.zeros((0, 3)),
                             kind="bone", **still),
                 ObjectTrack("half", positions=np.tile([-0.75, 0.0, 1.4], (T, 1)),
                             vertices=np.array([[np.nan, 0.0, 0.0], [0.0, 0.0, 0.0]]), kind="mesh", **still),
                 ObjectTrack("none", positions=np.zeros((T, 3)), vertices=np.full((2, 3), np.nan), kind="mesh", **still)]
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.7], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=fps)
    monkeypatch.setattr(objects, "robot_hands", lambda r, fk: np.zeros((T, 2, 3)))
    m = objects.hand_object_metrics(h, r, fk=None)
    assert [o["contact_s"] for o in m["_objects"]] == [T / fps, T / fps, 0.0]  # left: the ball, right: "half"


def test_policy_result_without_torque_limits_says_so():
    """A MuJoCo result (retlens.policy_replay) for a robot with joints that have no torque limit: their count goes into
    the metrics, so the window and the batch rows can say the saturation is not judged there."""
    T = 10
    r = RobotMotion("g1", ["j"], root_pos=np.tile([0.0, 0.0, 0.75], (T, 1)), root_quat=np.tile([1.0, 0, 0, 0], (T, 1)),
                    dof_pos=np.zeros((T, 1)), fps=30.0)
    for missing, want in ((29, 29), (0, None)):
        item = compare.Item(label="sim", source="sim.npz", kind="MuJoCo", robot=r,
                            info={"policy_replay": {"falls": 0, "torque_saturated_ratio": 0.0,
                                                    "torque_limits_missing": missing}})
        compare.compute_metrics(item, None, {})
        assert item.metrics.get("phys_torque_limits_missing") == want and item.metrics["phys_saturated_pct"] == 0.0


def test_robot_palm_point_of_a_hand_with_fingers():
    """The rubber-hand G1 is measured at its hand body; the G1 with hands at its palm, not its wrist link."""
    from retlens import analysis
    from retlens.robot_profile import RobotError

    out = {}
    for robot in ("unitree_g1", "unitree_g1_with_hands"):
        try:
            fk = analysis.FootKinematics(robot)
        except (RobotError, ImportError) as e:
            pytest.skip(str(e))
        r = RobotMotion("zero", fk.joint_names, root_pos=np.array([[0.0, 0.0, 0.8]]),
                        root_quat=np.array([[1.0, 0.0, 0.0, 0.0]]), dof_pos=np.zeros((1, len(fk.joint_names))), fps=30.0)
        palm = objects.robot_hands(r, fk)[0]
        tips = fk.data.xpos[[fk.profile.parts.arms[s].tip_body for s in ("left", "right")]]
        out[robot] = 100 * np.linalg.norm(palm - tips, axis=1)
    assert np.allclose(out["unitree_g1"], 0.0)  # no jointed fingers: the hand body itself
    assert np.all((out["unitree_g1_with_hands"] > 3.0) & (out["unitree_g1_with_hands"] < 8.0))  # into the palm


# --------------------------------------------------------------------------- FBX: several armatures, bad files
def _blender() -> str | None:
    from retlens.io.fbx import find_blender

    try:
        return find_blender()
    except FileNotFoundError:
        return None


# Blender builds a take with a root null ("reference") over the first actor, a second actor, and a ball written as a
# one-bone armature ("Ball_1" > "Ball_1:root") that rises 0.5 m.
BUILD = textwrap.dedent("""
    import sys, bpy
    out = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.render.fps = 1, 11, 10
    SPEC = [("Hips", None, (0, 0, 0.9)), ("LeftUpLeg", "Hips", (0.1, 0, 0.9)), ("LeftLeg", "LeftUpLeg", (0.1, 0, 0.5)),
            ("LeftFoot", "LeftLeg", (0.1, 0, 0.1)), ("RightUpLeg", "Hips", (-0.1, 0, 0.9)),
            ("RightLeg", "RightUpLeg", (-0.1, 0, 0.5)), ("RightFoot", "RightLeg", (-0.1, 0, 0.1)),
            ("Spine2", "Hips", (0, 0, 1.3)), ("LeftArm", "Spine2", (0.2, 0, 1.4)), ("LeftForeArm", "LeftArm", (0.45, 0, 1.4)),
            ("LeftHand", "LeftForeArm", (0.7, 0, 1.4)), ("RightArm", "Spine2", (-0.2, 0, 1.4)),
            ("RightForeArm", "RightArm", (-0.45, 0, 1.4)), ("RightHand", "RightForeArm", (-0.7, 0, 1.4))]

    def armature(name, bones, dx):
        bpy.ops.object.armature_add(location=(0, 0, 0))
        arm = bpy.context.object
        arm.name = arm.data.name = name
        bpy.ops.object.mode_set(mode="EDIT")
        eb = arm.data.edit_bones
        eb.remove(eb[0])
        for n, p, h in bones:
            b = eb.new(n)
            b.head, b.tail = h, (h[0], h[1], h[2] + 0.05)
            if p:
                b.parent = eb[p]
        bpy.ops.object.mode_set(mode="OBJECT")
        arm.location = (dx, 0, 0); arm.keyframe_insert("location", frame=1)
        arm.location = (dx + 0.3, 0, 0); arm.keyframe_insert("location", frame=11)
        return arm

    a = armature("ActorA", SPEC + [("Head", "Spine2", (0, 0, 1.6))], 0.0)
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    ref = bpy.context.object
    ref.name = "reference"
    a.parent = ref
    armature("ActorB", SPEC, 2.0)
    ball = armature("Ball_1", [("Ball_1:root", None, (0, 0, 0))], 0.7)
    ball.animation_data_clear()
    ball.location = (0.8, 0, 1.4)
    pb = ball.pose.bones["Ball_1:root"]
    pb.location = (0, 0, 0); pb.keyframe_insert("location", frame=1)
    pb.location = (0, 0.5, 0); pb.keyframe_insert("location", frame=11)
    bpy.ops.export_scene.fbx(filepath=out, object_types={"ARMATURE", "EMPTY"}, bake_anim=True,
                             bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False, add_leaf_bones=False,
                             apply_unit_scale=True, axis_forward="-Z", axis_up="Y")
""")


@pytest.mark.skipif(_blender() is None, reason="Blender not found")
def test_fbx_root_null_second_actor_and_prop_armature(tmp_path, monkeypatch):
    from retlens.io import fbx

    monkeypatch.setattr(fbx, "CACHE_DIR", str(tmp_path / "cache"))
    script, out = tmp_path / "build.py", tmp_path / "take.fbx"
    script.write_text(BUILD, encoding="utf-8")
    subprocess.run([_blender(), "-b", "--factory-startup", "--python", str(script), "--", str(out)], check=True,
                   capture_output=True, timeout=300)
    m = fbx.load_fbx(str(out))
    assert len(m.joint_names) == 15 and "Head" in m.joint_names  # ActorA: the animated armature with most bones
    by = {o.name: o for o in m.objects}
    assert set(by) == {"Ball_1"}  # not the root null, not the other actor
    ball = by["Ball_1"]
    assert ball.kind == "bone" and ball.moves and len(ball.faces) and "기본값" in ball.shape  # a ball's default sphere
    assert np.ptp(ball.positions, axis=0).max() == pytest.approx(0.5, abs=0.05)
    (warning,) = m.meta["warnings"]
    assert "ActorB" in warning and "ActorA" in warning

    half = tmp_path / "half.fbx"
    half.write_bytes(out.read_bytes()[: out.stat().st_size // 2])
    with pytest.raises(ValueError, match="손상되었거나 잘렸습니다"):
        fbx.load_fbx(str(half))
    ascii_fbx = _write(tmp_path / "ascii.fbx", "; FBX 7.3.0 project file\nFBXHeaderExtension:  {\n}\n")
    with pytest.raises(ValueError, match="ASCII FBX"):
        fbx.load_fbx(ascii_fbx)


def test_empty_fbx_says_so_without_blender(tmp_path, monkeypatch):
    from retlens.io import fbx

    monkeypatch.setattr(fbx, "run_blender", lambda *a, **k: pytest.fail("Blender run for an empty file"))
    monkeypatch.setattr(fbx, "CACHE_DIR", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="빈 파일"):
        fbx.load_fbx(_write(tmp_path / "empty.fbx", ""))


def _bone(name, group, parent, mats, animated=True):
    return {"name": name, "kind": "bone", "group": group, "parent": parent, "children": 0, "animated": animated,
            "bind": "", "below_mesh": False, "mats": mats, "vertices": np.zeros((0, 3)),
            "faces": np.zeros((0, 3), np.int64)}


def test_other_armatures_of_an_fbx(tmp_path):
    """Another person: a warning only. A small animated rig: props. A big animated rig that is no person (a face rig):
    a warning, no objects for the hands to touch. A still rig: nothing."""
    from retlens.io import fbx

    T = 11
    still = np.tile(np.eye(4), (T, 1, 1))
    rise = still.copy()
    rise[:, 2, 3] = np.linspace(1.0, 1.5, T)
    names = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot", "Spine2", "LeftArm",
             "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
    parents = [-1, 0, 1, 2, 0, 4, 5, 0, 7, 8, 9, 7, 11, 12]
    bones = [_bone(n, "ActorB", p, still, animated=False) for n, p in zip(names, parents)]
    bones.append(_bone("Ball_1:root", "Ball_1", -1, rise))
    face = len(bones)
    bones += [_bone(f"brow_{i}", "FaceRig", face if i else -1, rise) for i in range(9)]
    bones.append(_bone("cam", "CameraRig", -1, still, animated=False))
    path = tmp_path / "take.fbx"
    path.write_bytes(b"x")
    _write(tmp_path / "props.yaml", "Ball: {shape: sphere, diameter: 8}\n")
    raw = {"other_bones": bones, "armature": "ActorA", "names": names + ["Head"]}
    objs, warnings = fbx._other_armatures(raw, str(path), 1.0, 1, 0.25, 2)
    assert [o.name for o in objs] == ["Ball_1"] and objs[0].parent == -1 and objs[0].group == "Ball_1"
    assert np.allclose(objs[0].positions[:, 2], np.linspace(1.0, 1.5, T)[1:] - 0.25)  # frame 0 dropped, grounded
    assert "모양 파일" in objs[0].shape and len(objs[0].faces)
    people, rigs = warnings
    assert "ActorB" in people and "ActorA" in people and "FaceRig" in rigs and "CameraRig" not in " ".join(warnings)
    # the batch rows of this FBX depend on that shape file too
    assert [os.path.basename(s[0]) for s in props.signature(str(path))] == ["props.yaml"]
