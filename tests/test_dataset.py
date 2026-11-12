"""데이터셋 내보내기 (retlens.dataset): problem spans cut out on whole frames, pieces too short dropped, labels cut
with them; a folder's motions that pass written with a manifest, the rest listed with the reason; an earlier export
replaced; the CLI and the dialogs."""

import csv
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from retlens import batch, dataset, motion_labels  # noqa: E402
from retlens.io.robot import load_robot_npz  # noqa: E402
from retlens.synthetic import g1_motion  # noqa: E402

SAMPLES = os.path.join(ROOT, "data", "samples")
needs_samples = pytest.mark.skipif(not os.path.isfile(os.path.join(SAMPLES, "synthetic_walk.bvh")),
                                   reason="needs data/samples (tools/make_samples.py)")


def test_pieces_on_whole_frames():
    fps, T = 10.0, 50
    cut = dataset.CutOptions(pad_s=0.1, min_piece_s=0.5)
    spans = [(1.0, 1.2, "qc")]  # frames 10, 11; with the pad 9-12
    p = dataset.pieces(T, fps, cut, spans)
    assert p["ranges"] == [(0, 9), (13, 50)] and p["cut_s"] == 0.4 and p["short_s"] == 0.0
    assert p["by_kind"] == {"qc": 0.2}
    long = dataset.CutOptions(pad_s=0.1, min_piece_s=1.0)
    p = dataset.pieces(T, fps, long, spans)
    assert p["ranges"] == [(13, 50)] and p["short_s"] == 0.9  # 0.9 s before the cut: too short
    assert dataset.pieces(T, fps, None, spans)["ranges"] == [(0, 50)]  # no cut: the whole motion, spans or not
    p = dataset.pieces(T, fps, None, [], range_s=(2.0, 4.0))
    assert p["ranges"] == [(20, 40)] and p["cut_s"] == 0.0  # a range is exact; what is outside it is not "cut"
    p = dataset.pieces(T, fps, cut, spans, range_s=(0.5, 3.0))
    assert p["ranges"] == [(13, 30)] and p["short_s"] == 0.4  # 0.5-0.9 s left before the cut: shorter than 0.5 s
    with pytest.raises(ValueError):
        dataset.pieces(T, fps, None, [], range_s=(3.0, 3.0))


def test_cut_spans_follow_the_options():
    probs = {"slip": [(1.0, 1.5)], "penetration": [(2.0, 2.2)], "self_collision": [(3.0, 3.1)]}
    spans = dataset.cut_spans(10.0, dataset.CutOptions(), qc_bad=[(0.0, 0.1)], problems=probs, falls=[5.0, 12.0])
    assert spans == [(0.0, 0.1, "qc"), (2.0, 2.2, "penetration"), (4.0, 5.25, "fall")]  # the fall after the end: none
    only = dataset.cut_spans(10.0, dataset.CutOptions(qc=False, kinds=("slip",), falls=False), qc_bad=[(0.0, 0.1)],
                             problems=probs, falls=[5.0])
    assert only == [(1.0, 1.5, "slip")]
    assert "바닥 관통" in dataset.CutOptions().describe() and "자기 충돌" not in dataset.CutOptions().describe()


def test_labels_are_cut_and_moved():
    lab = motion_labels.MotionLabels("x", [motion_labels.Segment("걷기", 0.0, 2.0, "이동"),
                                           motion_labels.Segment("서기", 2.0, 5.0, "이동"),
                                           motion_labels.Segment("뻗기", 4.5, 4.8, "손")])
    part = dataset.slice_labels(lab, 1.5, 4.0)
    assert [(s.label, round(s.start, 3), round(s.end, 3), s.track) for s in part.segments] == \
        [("걷기", 0.0, 0.5, "이동"), ("서기", 0.5, 2.5, "이동")]
    assert dataset.label_seconds(part) == {"이동: 걷기": 0.5, "이동: 서기": 2.0}


def test_takes_and_folders(tmp_path):
    s1, s2 = tmp_path / "mocap" / "s01", tmp_path / "mocap" / "s02" / "day2"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)
    files = [str(s1 / n) for n in ("a.c3d", "a.bvh", "a_stageii.npz", "b.fbx")] + [str(s2 / "a.bvh")]
    keep, same = dataset.pick_takes(files)
    assert [os.path.basename(f) for f in keep] == ["a.bvh", "b.fbx", "a.bvh"]  # one file per take and folder
    assert same == {files[0]: files[1], files[2]: files[1]}
    out = tmp_path / "out"
    folders = dataset.output_folders(keep, [str(s1), str(tmp_path / "mocap" / "s02")], str(out))
    assert folders[keep[0]] == str(out / "s01") and folders[keep[2]] == str(out / "s02" / "day2")
    one = dataset.output_folders([files[1]], [files[1]], str(out))  # a file given: straight into <out>
    assert one[files[1]] == str(out)


def test_export_motion_cuts_bad_frames_and_reads_back(tmp_path):
    m = g1_motion(seconds=6.0, fps=50.0)
    m.dof_pos[100:110] = np.nan  # 2.0-2.2 s cannot be used
    m.meta["robot_ident"] = {"name": "unitree_g1", "digest": "abc"}
    lab = motion_labels.MotionLabels("x", [motion_labels.Segment("걷기", 0.0, 6.0)])
    bad = dataset.qc_bad_spans(m, None)
    assert bad == [(2.0, 2.2)]
    res = dataset.export_motion(m, str(tmp_path), "walk", labels=lab, cut=dataset.CutOptions(), qc_bad=bad,
                                formats=("npz", "csv", "pkl"), info={"kind": "test"})
    names = [p["name"] for p in res["pieces"]]
    assert names == ["walk_0.00-1.90s", "walk_2.30-6.00s"] and res["cut_s"] == 0.4
    first = res["pieces"][0]
    assert [os.path.basename(f) for f in first["files"]] == ["walk_0.00-1.90s.npz", "walk_0.00-1.90s.csv",
                                                             "walk_0.00-1.90s.pkl"]
    back = load_robot_npz(first["files"][0])
    assert back.num_frames == 95 and np.allclose(back.dof_pos, m.dof_pos[:95])
    assert back.meta["robot_ident"] == {"name": "unitree_g1", "digest": "abc"}
    rows = np.loadtxt(first["files"][1], delimiter=",")  # the csv at 30 fps (read at 30): every 3rd = every 5th at 50
    assert rows.shape == (57, 7 + 29) and np.allclose(rows[::3, 3:7], m.root_quat[:95:5][:, [1, 2, 3, 0]], atol=1e-6)
    second = res["pieces"][1]
    found = motion_labels.load_for(second["files"][0], 50.0, second["duration_s"])  # RetLens finds them by the npz
    assert found is not None and [(s.label, round(s.start, 3), round(s.end, 3)) for s in found.segments] == \
        [("걷기", 0.0, 3.7)]
    with open(second["info"], encoding="utf-8") as f:
        info = json.load(f)
    assert info["source_start_s"] == 2.3 and info["kind"] == "test" and info["qc"] == "PASS"
    whole = dataset.export_motion(m, str(tmp_path / "whole"), "walk")  # no cut: one file, the motion's name
    assert [p["name"] for p in whole["pieces"]] == ["walk"] and whole["pieces"][0]["qc"] == "WARN"  # 10 of 300 bad


@pytest.fixture
def capture(tmp_path, monkeypatch):
    """Two capture folders: a human BVH with labels, a robot motion, a broken file, a motion of another robot."""
    from retlens import compare
    from retlens.motion import RobotMotion

    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "retarget"))  # not the user's retarget cache
    s1, s2 = tmp_path / "mocap" / "s01", tmp_path / "mocap" / "s02"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)
    shutil.copy(os.path.join(SAMPLES, "synthetic_walk.bvh"), s1 / "walk.bvh")
    (s1 / "walk.labels.csv").write_text("track,label,start_s,end_s\n이동,걷기,0,1\n이동,서기,1,2.5\n", encoding="utf-8")
    shutil.copy(os.path.join(SAMPLES, "synthetic_g1_walk.npz"), s2 / "robot.npz")
    (s2 / "broken.bvh").write_text("HIERARCHY\nnot a bvh\n", encoding="utf-8")
    n = 60
    RobotMotion("arm", ["a", "b", "c"], np.zeros((n, 3)), np.tile([1.0, 0, 0, 0], (n, 1)), np.zeros((n, 3)),
                30.0).save_npz(str(s2 / "arm.npz"))
    return tmp_path / "mocap"


@needs_samples
def test_exporter_writes_what_passes_and_says_why_not(capture, tmp_path):
    out = tmp_path / "dataset"
    out.mkdir()
    (out / "notes.txt").write_text("mine", encoding="utf-8")  # a file of the user's: never removed
    inputs = [str(capture / "s01"), str(capture / "s02")]
    runner = batch.Batch(batch.BatchOptions(), cache_dir=str(tmp_path / "batch"))
    seen = []
    ex = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL", formats=("npz", "csv")), str(out),
                          runner=runner)
    m = ex.run(inputs, progress=lambda done, total, name: seen.append((done, total, name)))
    assert [s[2] for s in seen] == ["walk", "arm", "broken", "robot"] and seen[-1][:2] == (4, 4)
    by = {os.path.basename(c["source"]): c for c in m["clips"]}
    assert set(by) == {"walk.bvh", "robot.npz"}
    walk = by["walk.bvh"]
    assert walk["files"] == ["s01/walk.npz", "s01/walk.csv"] and walk["session"] == "s01"
    assert walk["labels"] == "s01/walk.labels.csv" and walk["label_seconds"] == {"이동: 걷기": 1.0, "이동: 서기": 1.5}
    assert walk["source_sha256"] == dataset.sha256(str(capture / "s01" / "walk.bvh")) and walk["retarget_score"]
    why = {os.path.basename(e["source"]): e["reason"] for e in m["excluded"]}
    assert why["broken.bvh"].startswith("읽지 못함") and why["arm.npz"].startswith("다른 로봇의 모션")
    assert m["robot"]["key"] == "unitree_g1" and len(m["joint_names"]) == 29
    assert m["fps"] == [30.0, 50.0]  # the retarget at 30, the robot file at its own 50: both said
    assert m["totals"]["clips"] == 2 and m["totals"]["excluded"] == 2 and m["cut"] is None
    with open(out / "manifest.json", encoding="utf-8") as f:
        assert json.load(f)["totals"] == m["totals"]
    with open(out / "manifest.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert sorted(r["file"] for r in rows) == ["s01/walk.npz", "s02/robot.npz"]
    assert load_robot_npz(str(out / "s01" / "walk.npz")).meta["robot_ident"]["digest"] == m["robot"]["digest"]

    # again with other settings: the first export's files go (its manifest lists them), the user's file stays
    strict = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL", min_score=101.0), str(out),
                              runner=runner)
    m2 = strict.run(inputs)
    assert m2["previous_files_removed"] >= 6
    assert [c["files"] for c in m2["clips"]] == [["s02/robot.npz"]]  # a robot motion has no score to hold it back
    assert not (out / "s01" / "walk.npz").exists() and not (out / "s02" / "robot.csv").exists()
    assert (out / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert any(e["reason"].startswith("리타게팅 점수") for e in m2["excluded"])
    stopped = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(), str(out), runner=runner)
    m3 = stopped.run(inputs, cancel=lambda: True)
    assert m3["stopped"] and m3["clips"] == []
    with pytest.raises(ValueError):
        dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(formats=("bvh",)), str(out))
    with pytest.raises(ValueError):  # a range is for one motion
        dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(range_s=(0.0, 1.0)), str(out),
                         runner=runner).run(inputs)


CMU_143_11 = os.path.join(ROOT, "data", "raw", "cmu_bvh", "143_11.bvh")


@pytest.mark.skipif(not os.path.isfile(CMU_143_11), reason="needs data/raw/cmu_bvh (CMU 143_11)")
def test_pieces_get_the_balance_check(tmp_path, monkeypatch):
    """CMU 143_11 is QC WARN for standing with the CoM outside the feet only: its pieces too, as inspect says."""
    from retlens import compare

    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "retarget"))  # not the user's retarget cache
    runner = batch.Batch(batch.BatchOptions(), cache_dir=str(tmp_path / "batch"))
    assert runner.process(CMU_143_11)["qc"] == "WARN"
    for opts in (dataset.ExportOptions(cut=dataset.CutOptions(), qc="PASS"),
                 dataset.ExportOptions(range_s=(0.0, 10.0), qc="PASS")):
        m = dataset.Exporter(batch.BatchOptions(), opts, str(tmp_path / "out"), runner=runner).run([CMU_143_11])
        assert m["clips"] == [] and any("CoM outside the feet" in e["reason"] for e in m["excluded"])
    m = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(), str(tmp_path / "out"), runner=runner).run(
        [CMU_143_11])
    assert [c["qc"] for c in m["clips"]] == ["WARN"]  # the manifest's QC is the row's
    with open(tmp_path / "out" / m["clips"][0]["info"], encoding="utf-8") as f:
        assert json.load(f)["qc"] == "WARN"


@needs_samples
def test_cli_export(capture, tmp_path):
    env = dict(os.environ, RETLENS_USER_DIR=str(tmp_path / "user"))
    out = tmp_path / "cli_out"
    res = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "retlens_cli.py"), "export",
                          str(capture / "s01" / "walk.bvh"), "--out", str(out), "--robot", "unitree_g1",
                          "--range", "0.5", "2.0", "--formats", "npz,pkl"], env=env, capture_output=True, timeout=300,
                         cwd=ROOT)
    lines = res.stdout.decode("utf-8").strip().splitlines()
    assert res.returncode == 0 and len(lines) == 1, res.stderr.decode("utf-8", "replace")[-2000:]
    d = json.loads(lines[0])
    assert [c["files"] for c in d["clips"]] == [["walk_0.50-2.00s.npz", "walk_0.50-2.00s.pkl"]]
    assert d["clips"][0]["start_s"] == 0.5 and d["clips"][0]["end_s"] == 2.0
    assert (out / "walk_0.50-2.00s.labels.csv").is_file() and (out / "manifest.json").is_file()
    bad = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "retlens_cli.py"), "export", str(capture),
                          "--out", str(out), "--cut", "--cut-kinds", "nope"], env=env, capture_output=True, timeout=300,
                         cwd=ROOT)
    assert bad.returncode == 1 and "nope" in json.loads(bad.stdout.decode("utf-8"))["error"]


def test_export_dialogs(tmp_path):
    QtCore = pytest.importorskip("PySide6.QtCore")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from retlens.app import export_dialogs as ed

    store = QtCore.QSettings(str(tmp_path / "retlens.ini"), QtCore.QSettings.IniFormat)  # never the user's registry
    dlg = ed.DatasetExportDialog(None, store, files=4, physics=False, start=str(tmp_path / "out"))
    out, opts = dlg.values()
    assert out == str(tmp_path / "out") and opts.qc == "WARN" and opts.cut is None and opts.formats == ("npz",)
    assert opts.allow_falls and not dlg.cut.falls.isEnabled()  # no physics: nothing about falls
    dlg.cut.setChecked(True)
    dlg.formats.boxes["csv"].setChecked(True)
    dlg.min_score.setValue(80)
    dlg.accept()
    again = ed.DatasetExportDialog(None, store, files=4, physics=True, start="elsewhere")
    out, opts = again.values()  # remembered
    assert out == str(tmp_path / "out") and opts.formats == ("npz", "csv") and opts.min_score == 80.0
    assert opts.cut is not None and opts.cut.kinds == dataset.CUT_KINDS and opts.cut.falls and not opts.allow_falls
    one = ed.MotionExportDialog(None, store, "s01/walk", 6.0, segment=("이동: 걷기", 1.0, 2.5), falls=None,
                                start=str(tmp_path))
    assert one.range_s() == (1.0, 2.5)  # the picked segment first
    one.r_all.setChecked(True)
    assert one.range_s() is None
    one.b.setValue(3.0)  # typing a time picks 직접
    assert one.range_s() == (0.0, 3.0) and not one.cut.falls.isEnabled()
    src = tmp_path / "s01"
    store.setValue("export/motion_folder", str(src))  # remembered by 0.10.0, whose default was the motion's own folder
    moved = ed.MotionExportDialog(None, store, "s01/walk", 6.0, start=str(src / "retlens_export"))
    assert moved.folder.path() == str(src / "retlens_export")  # never offered beside the source again
    store.setValue("export/motion_folder", str(tmp_path / "picked"))
    kept = ed.MotionExportDialog(None, store, "s01/walk", 6.0, start=str(src / "retlens_export"))
    assert kept.folder.path() == str(tmp_path / "picked")  # any other remembered folder stays
    assert ed.manifest_text({"totals": {"exported_motions": 2, "clips": 3, "seconds": 90.0, "cut_seconds": 1.0,
                                        "short_seconds": 0.5, "excluded": 1, "excluded_by_reason": {"QC FAIL": 1}}}) \
        .startswith("모션 2개 → 파일 3개 · 1.5분")
    app.processEvents()
