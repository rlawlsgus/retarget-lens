"""데이터셋 일괄 처리 rows (retlens.batch), as an audit found them: a C3D's row follows the solved motion it is made
from (key, objects, take warning), the reader's warnings and joints without a torque limit reach the row and the CSV,
a folder's label table edits no row but its labels, a label file saved during a measurement is not lost, and the
folder listing skips exported robot copies and stays fast next to prop files."""

import os
import shutil
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens import batch, compare  # noqa: E402
from retlens.synthetic import g1_motion  # noqa: E402

C3D = os.path.join(ROOT, "data", "raw", "cmu_c3d", "02_01.c3d")
BVH = os.path.join(ROOT, "data", "raw", "cmu_bvh", "02_01.bvh")
OTHER_BVH = os.path.join(ROOT, "data", "raw", "cmu_bvh", "02_03.bvh")  # another take of that subject


def _runner(tmp_path, **opts):
    return batch.Batch(batch.BatchOptions(**opts), cache_dir=str(tmp_path / "batch"))


def _robot(path, seconds=2.0, fps=30.0) -> str:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    g1_motion(seconds=seconds, fps=fps).save_npz(str(path))
    return str(path)


def _same(a, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# ---------------------------------------------------------------- a C3D's row and its solve
def test_c3d_key_follows_its_solve(tmp_path, monkeypatch):
    s, lib = tmp_path / "s", tmp_path / "lib"
    s.mkdir()
    lib.mkdir()
    c3d = s / "pick_010.c3d"
    c3d.write_bytes(b"markers")  # the key reads no C3D content
    (lib / "pick_010.bvh").write_bytes(b"a take of that name in a motion folder")
    monkeypatch.setattr(compare, "library_files", lambda roots=None: {"lib": [str(lib / "pick_010.bvh")]})
    b = _runner(tmp_path)
    assert _same(b.solved_motion(str(c3d)), lib / "pick_010.bvh")
    assert _same(compare.find_take(str(c3d)), lib / "pick_010.bvh")  # as compare.load_item picks it
    keys = [b.key(str(c3d))]
    (s / "pick_010.fbx").write_bytes(b"the solve")  # the take's own solve put beside it (as the log says)
    assert _same(b.solved_motion(str(c3d)), s / "pick_010.fbx")
    keys.append(b.key(str(c3d)))
    (s / "props.yaml").write_text("Ball_1: {shape: sphere, diameter: 24}\n", encoding="utf-8")  # the FBX solve's prop
    keys.append(b.key(str(c3d)))
    (s / "pick_010.bvh").write_bytes(b"a BVH solve")  # a BVH beats the FBX
    assert _same(b.solved_motion(str(c3d)), s / "pick_010.bvh")
    assert _same(compare.find_take(str(c3d)), s / "pick_010.bvh")
    keys.append(b.key(str(c3d)))
    (s / "pick_010.bvh").write_bytes(b"the BVH solve exported again")
    keys.append(b.key(str(c3d)))
    (s / "pick_010.labels.csv").write_text("label,start_s,end_s\nreach,0,1\n", encoding="utf-8")
    keys.append(b.key(str(c3d)))
    assert len(set(keys)) == len(keys)  # each change makes the row again
    (s / "labels.csv").write_text("seq,label,start_s,end_s\npick_010,reach,0,1\n", encoding="utf-8")
    assert b.key(str(c3d)) == keys[-1]  # a folder table is read for the cached row instead


def test_c3d_solves_of_one_folder_are_found_as_find_take_finds_them(tmp_path, monkeypatch):
    s, lib = tmp_path / "s", tmp_path / "lib"
    s.mkdir()
    lib.mkdir()
    for n in ("pick_010.c3d", "pick_010_poses.npz", "pick_010_stageii.npz", "pick_011.c3d", "pick_011.fbx",
              "pick_011.bvh", "Pick_0100.C3D", "pick_0100.FBX", "lift_7.c3d", "walk.bvh"):
        (s / n).write_bytes(b"")
    (lib / "lift_7.bvh").write_bytes(b"")
    (lib / "lift_7.fbx").write_bytes(b"")
    monkeypatch.setattr(compare, "library_files", lambda roots=None: {"lib": [str(lib / "lift_7.fbx"),
                                                                              str(lib / "lift_7.bvh")]})
    listed = []
    real = os.listdir
    monkeypatch.setattr(os, "listdir", lambda p=".": listed.append(p) or real(p))
    b = _runner(tmp_path)
    c3ds = [str(s / n) for n in ("pick_010.c3d", "pick_011.c3d", "Pick_0100.C3D", "lift_7.c3d")]
    got = [b.solved_motion(p) for p in c3ds]
    assert listed == []  # the C3D's folder is not listed for each of its C3Ds
    want = [s / "pick_010_poses.npz", s / "pick_011.bvh", s / "pick_0100.FBX", lib / "lift_7.bvh"]
    assert all(_same(g, w) for g, w in zip(got, want))
    assert all(_same(g, compare.find_take(p)) for g, p in zip(got, c3ds))  # as compare.load_item picks them
    (s / "lift_7.bvh").write_bytes(b"")  # one put beside it
    assert _same(b.solved_motion(c3ds[3]), s / "lift_7.bvh")


def _item(path, solve_objects=(), warnings=(), props=(), c3d=None, solved=None, markers=True):
    """A loaded motion as compare.load_item gives it: a C3D (markers, its solved skeleton) or a skeleton motion."""
    def skel(kind, objs=(), warns=(), prop_report=()):
        return types.SimpleNamespace(kind=kind, objects=[types.SimpleNamespace(name=n) for n in objs],
                                     meta={"warnings": list(warns), "props": list(prop_report)})

    solve = skel("skeleton", solve_objects, warnings, props)
    info = {"c3d": c3d or {}, "solved_motion": solved} if markers else {}
    return compare.Item(label="s/x", source=str(path), kind="C3D 마커 + BVH -> GMR" if markers else "FBX -> GMR",
                        robot=g1_motion(seconds=1.0, fps=30.0), human=skel("markers") if markers else solve,
                        info=info, solved_human=solve if markers else None)


def test_c3d_row_says_its_solve_objects_and_warnings(tmp_path, monkeypatch):
    s = tmp_path / "s"
    s.mkdir()
    c3d = s / "pick_010.c3d"
    c3d.write_bytes(b"markers")
    elsewhere = str(tmp_path / "lib" / "pick_010.fbx")
    warn = "마커 골반이 솔버 결과(pick_010.fbx)의 골반과 평균 25 cm 떨어져 있어 다른 촬영일 수 있습니다"
    item = _item(c3d, solve_objects=["Ball_1"], warnings=["다른 사람의 뼈대 ActorB는 읽지 않음"],
                 c3d={"take_warning": warn, "solved_elsewhere": True}, solved=elsewhere)
    monkeypatch.setattr(compare, "library_files", lambda roots=None: {})
    monkeypatch.setattr(batch.Batch, "load_item", lambda self, path: item)
    monkeypatch.setattr(compare, "compute_metrics", lambda it, fk, limits: setattr(
        it, "metrics", {"qc": "WARN", "hand_obj_reach_pct": 44.2, "phys_torque_limits_missing": 3}))
    b = _runner(tmp_path)
    row = b.process(str(c3d))
    assert row["objects"] == 1 and row["object_names"] == ["Ball_1"]  # the solve's, as its hand-object numbers
    assert row["hand_obj_reach_pct"] == 44.2 and batch.totals([row])["with_objects"] == 1
    assert row["take_warning"] == warn and row["solved_elsewhere"] is True and row["solved_motion"] == elsewhere
    assert row["file_warnings"] == "다른 사람의 뼈대 ActorB는 읽지 않음" and row["phys_torque_limits_missing"] == 3
    assert ("take_warning", "촬영 주의", "{}") in batch.COLUMNS and ("file_warnings", "파일 주의", "{}") in batch.COLUMNS
    out = batch.write_csv([row], str(tmp_path / "rows.csv"))
    with open(out, encoding="utf-8-sig") as f:
        text = f.read()
    assert "촬영 주의" in text and "파일 주의" in text and "25 cm" in text and "ActorB" in text

    plain = _item(s / "walk.fbx", solve_objects=["Box"], warnings=["w1", "w2"], markers=False)
    (s / "walk.fbx").write_bytes(b"fbx")
    monkeypatch.setattr(batch.Batch, "load_item", lambda self, path: plain)
    row = b.process(str(s / "walk.fbx"))
    assert row["objects"] == 1 and row["file_warnings"] == "w1; w2"
    assert row["take_warning"] is None and row["solved_motion"] is None and row["solved_elsewhere"] is None

    broken = _item(c3d, props=[{"file": str(s / "pick_010_Prop.fbx"), "error": "읽지 못함"}], solved=elsewhere)
    monkeypatch.setattr(batch.Batch, "load_item", lambda self, path: broken)
    rows = [_runner(tmp_path / "other").process(str(c3d)) for _ in range(2)]
    assert rows[0]["props_error"] == "pick_010_Prop.fbx: 읽지 못함" and not rows[1]["cached"]  # the solve's prop file


def test_physics_row_says_joints_without_torque_limit(tmp_path, monkeypatch):
    from retlens import policy_replay as pr

    class Run:
        metrics = {"falls": 0, "torque_saturated_ratio": 0.0, "consistent": True, "issues": [],
                   "harness_force_per_body_weight": {"mean": 0.1}, "torque_limits_missing": 29}

    monkeypatch.setattr(pr, "run", lambda *a, **k: Run())
    phys = _runner(tmp_path, physics=True)
    phys._sim = object()  # the harness sim, not made here
    assert phys._physics(g1_motion(seconds=1.0))["phys_torque_limits_missing"] == 29
    Run.metrics = {**Run.metrics, "torque_limits_missing": 0}
    assert phys._physics(g1_motion(seconds=1.0))["phys_torque_limits_missing"] is None


@pytest.mark.skipif(not all(os.path.isfile(p) for p in (C3D, BVH, OTHER_BVH)),
                    reason="needs data/raw/cmu_c3d and data/raw/cmu_bvh (CMU 02_01, 02_03)")
def test_c3d_row_is_made_again_when_its_solve_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "retarget"))  # not the user's retarget cache
    s = tmp_path / "s"
    s.mkdir()
    c3d = str(s / "pick_010.c3d")
    shutil.copy(C3D, c3d)
    shutil.copy(OTHER_BVH, s / "pick_010.bvh")  # a solve of another take under this take's name
    b = _runner(tmp_path)
    wrong = b.process(c3d)
    assert not wrong.get("error") and wrong["kind"].startswith("C3D")
    assert _same(wrong["solved_motion"], s / "pick_010.bvh") and wrong["solved_elsewhere"] is None
    assert wrong["take_warning"]  # its markers are far from that solve's pelvis
    assert _runner(tmp_path).process(c3d)["cached"]
    shutil.copy(BVH, s / "pick_010.bvh")  # the take's own solve exported over it
    right = _runner(tmp_path).process(c3d)
    assert not right["cached"] and right["take_warning"] is None and right["duration_s"] != wrong["duration_s"]


# ---------------------------------------------------------------- labels and the cache
def test_folder_table_edit_makes_no_row_again_but_its_labels_follow(tmp_path, monkeypatch):
    s = tmp_path / "s"
    a, b_ = _robot(s / "a.npz"), _robot(s / "b.npz")
    table = s / "labels.csv"
    table.write_text("seq,label,start_s,end_s\na,walk,0,1\n", encoding="utf-8")
    measured = []
    real = batch.Batch._measure
    monkeypatch.setattr(batch.Batch, "_measure", lambda self, path: measured.append(os.path.basename(path)) or
                        real(self, path))
    b = _runner(tmp_path)
    rows = b.run([a, b_])
    assert [r["labels"] for r in rows] == ["file", None] and measured == ["a.npz", "b.npz"]
    assert rows[0]["label_seconds"] == {"walk": 1.0}
    table.write_text("seq,label,start_s,end_s\na,walk,0,1\nb,turn,0.5,1.5\nb,walk,1.5,9\n", encoding="utf-8")
    rows = b.run([a, b_])
    assert [r["cached"] for r in rows] == [True, True] and measured == ["a.npz", "b.npz"]  # nothing measured again
    assert rows[1]["labels"] == "file" and rows[1]["label_segments"] == 2
    assert rows[1]["label_seconds"] == {"turn": 1.0, "walk": 0.5}  # cut at the motion's end, as measured
    table.write_text("seq,label,start_s,end_s\nb,turn,0.5,1.5\n", encoding="utf-8")
    row = b.process(a)
    assert row["cached"] and row["labels"] is None and row["label_segments"] is None and "label_seconds" not in row
    rules = tmp_path / "r.yaml"
    rules.write_text("rules:\n  - {label: x}\n", encoding="utf-8")
    auto = _runner(tmp_path, rules=str(rules))
    table.write_text("seq,label,start_s,end_s\na,walk,0,1\n", encoding="utf-8")
    assert not auto.process(a)["cached"] and auto.process(a)["cached"]
    table.write_text("seq,label,start_s,end_s\nb,turn,0.5,1.5\n", encoding="utf-8")
    measured.clear()
    row = auto.process(a)  # its rows went: 자동 라벨 by the rule file would need the motion
    assert not row["cached"] and measured == ["a.npz"] and row["labels"] is None


def test_label_file_saved_while_measuring_makes_the_row_again(tmp_path, monkeypatch):
    path = _robot(tmp_path / "s" / "walk.npz")
    real = batch.Batch.labels

    def labels_then_save(self, p, item):  # the window saves the label file while the row is being made
        out = real(self, p, item)
        (tmp_path / "s" / "walk.labels.csv").write_text("label,start_s,end_s\nwalk,0,1\n", encoding="utf-8")
        return out

    monkeypatch.setattr(batch.Batch, "labels", labels_then_save)
    b = _runner(tmp_path)
    assert b.process(path)["labels"] is None
    monkeypatch.setattr(batch.Batch, "labels", real)
    row = b.process(path)
    assert not row["cached"] and row["labels"] == "file" and row["label_segments"] == 1
    assert b.process(path)["cached"]


# ---------------------------------------------------------------- folder listing
def test_motion_files_skip_retlens_export_folders(tmp_path):
    s = tmp_path / "day1"
    _robot(s / "walk.npz")
    _robot(s / "retlens_export" / "walk.npz")  # 로봇 모션 내보내기's default folder: a robot copy of walk
    _robot(s / "sub" / "RetLens_Export" / "run.npz")
    _robot(s / "sub" / "run.npz")
    got = [os.path.relpath(f, s).replace("\\", "/") for f in batch.motion_files([str(s)])]
    assert got == ["walk.npz", "sub/run.npz"]
    assert [os.path.basename(f) for f in batch.motion_files([str(s / "retlens_export")])] == ["walk.npz"]  # given: read


def test_motion_files_ask_find_props_only_for_people_of_listed_props(tmp_path, monkeypatch):
    from retlens import props

    s = tmp_path / "session"
    s.mkdir()
    for i in range(200):
        (s / f"walk_{i:03d}_A.fbx").write_bytes(b"")
    for n in ("lift_7_Prop.fbx", "pick_010_slow.fbx", "pick_010_Prop.fbx"):  # a prop of no take; one next to a variant
        (s / n).write_bytes(b"")
    asked = []
    real = props.find_props
    monkeypatch.setattr(props, "find_props", lambda p: asked.append(os.path.basename(p)) or real(p))
    got = {os.path.basename(f) for f in batch.motion_files([str(s)])}
    assert asked == ["pick_010_slow.fbx"]  # not every person of the folder (each call lists the folders again)
    assert "pick_010_Prop.fbx" not in got and {"pick_010_slow.fbx", "lift_7_Prop.fbx", "walk_000_A.fbx"} <= got
    assert len(got) == 202
