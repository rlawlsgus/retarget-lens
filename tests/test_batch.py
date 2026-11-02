"""데이터셋 일괄 처리 (retlens.batch): a row per motion file, cached per file and options, a bad file reported
without stopping the rest; and the 데이터셋 tab's table model (sorting by value, filtering)."""

import os
import shutil
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from retlens import batch  # noqa: E402

SAMPLES = os.path.join(ROOT, "data", "samples")


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A capture folder: a human BVH with a label file next to it, a robot motion, a file that is no motion."""
    from retlens import compare

    monkeypatch.setattr(compare, "CACHE", str(tmp_path / "retarget"))  # not the user's retarget cache
    folder = tmp_path / "session1"
    folder.mkdir()
    shutil.copy(os.path.join(SAMPLES, "synthetic_walk.bvh"), folder / "walk.bvh")
    shutil.copy(os.path.join(SAMPLES, "synthetic_g1_walk.npz"), folder / "robot.npz")
    (folder / "walk.labels.csv").write_text("label,start_s,end_s\n걷기,0,1\n", encoding="utf-8")
    (folder / "broken.bvh").write_text("HIERARCHY\nnot a bvh\n", encoding="utf-8")
    return folder


def test_batch_rows_cache_and_errors(session, tmp_path):
    files = batch.motion_files([str(session)])
    assert [os.path.basename(f) for f in files] == ["broken.bvh", "robot.npz", "walk.bvh"]  # the label file is no motion
    b = batch.Batch(batch.BatchOptions(), cache_dir=str(tmp_path / "batch"))
    seen = []
    rows = b.run(files, progress=lambda done, total, row: seen.append((done, total, row["name"])))
    assert seen == [(1, 3, "broken"), (2, 3, "robot"), (3, 3, "walk")]
    by = {r["name"]: r for r in rows}
    assert by["broken"]["error"] and not by["broken"]["cached"]  # reported, the others still done
    walk = by["walk"]
    assert walk["retarget_score"] is not None and walk["qc"] in ("PASS", "WARN", "FAIL") and walk["folder"] == "session1"
    assert walk["labels"] == "file" and walk["label_segments"] == 1 and walk["label_seconds"] == {"걷기": 1.0}
    assert walk["duration_s"] > 1.0 and isinstance(walk["problem_seconds"], dict) and walk["objects"] == 0
    assert by["robot"]["retarget_score"] is None and by["robot"]["labels"] is None  # a robot motion: nothing to score
    again = b.run(files)
    assert [r["cached"] for r in again] == [False, True, True]  # done rows come back at once; failures are tried again
    assert {k: v for k, v in again[2].items() if k != "cached"} == {k: v for k, v in walk.items() if k != "cached"}
    other = batch.Batch(batch.BatchOptions(swing_clearance_cm=2.0), cache_dir=str(tmp_path / "batch"))
    assert other.cached(files[2]) is None  # other corrections: another row
    stopped = b.run(files, cancel=lambda: True)
    assert stopped == []
    t = batch.totals(rows)
    assert t["motions"] == 3 and t["read"] == 2 and t["errors"] == 1 and t["labelled"] == 1
    out = batch.write_csv(rows, str(tmp_path / "table.csv"))
    with open(out, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    assert lines[0].split(",")[:4] == ["모션", "폴더", "길이 (s)", "리타게팅 점수"] and len(lines) == 4


def test_batch_physics(session, tmp_path):
    pytest.importorskip("mujoco")
    from retlens import policy_replay as pr

    if not os.path.isfile(pr.gmt_paths()["model"]):
        pytest.skip("no G1 MuJoCo model")
    b = batch.Batch(batch.BatchOptions(physics=True), cache_dir=str(tmp_path / "batch"))
    row = b.process(str(session / "walk.bvh"))
    assert row["phys_falls"] is not None and row["phys_harness_pct"] is not None and row["phys_ok"]


def test_dataset_table_sorts_and_filters():
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from retlens.app import editor

    QApplication.instance() or QApplication([])
    model = editor.BatchModel()
    proxy = editor.BatchFilter()
    proxy.setSourceModel(model)
    for r in ({"name": "a", "folder": "s1", "retarget_score": 91.0, "qc": "PASS"},
              {"name": "b", "folder": "s1", "retarget_score": 62.5, "qc": "FAIL", "worst_problem": "발 미끄러짐"},
              {"name": "c", "folder": "s2", "retarget_score": None, "qc": "WARN", "phys_falls": 2},
              {"name": "d", "folder": "s2", "error": "ValueError: bad"}):
        model.add(r)
    col = [k for k, _t, _f in batch.COLUMNS].index("retarget_score")
    proxy.sort(col, Qt.AscendingOrder)
    names = [model.rows[proxy.mapToSource(proxy.index(i, 0)).row()]["name"] for i in range(proxy.rowCount())]
    assert names[:2] == ["b", "a"]  # by value; blanks last
    assert model.data(model.index(1, col)) == "62"  # the column's format
    proxy.set(qc="FAIL")
    assert proxy.rowCount() == 1
    proxy.set(qc="", text="s2")
    assert proxy.rowCount() == 2
    proxy.set(text="미끄러짐")
    assert proxy.rowCount() == 1
    proxy.set(text="", qc="falls")
    assert proxy.rowCount() == 1
    proxy.set(qc="error")
    assert proxy.rowCount() == 1
    model.add({"name": "e", "folder": "s3", "labels": "auto", "label_segments": 4})
    labels = [k for k, _t, _f in batch.COLUMNS].index("labels")
    assert model.data(model.index(4, labels)) == "자동"  # where the labels came from, in the window's words
    proxy.set(qc="", text="자동")
    assert proxy.rowCount() == 1
