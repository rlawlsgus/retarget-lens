"""데이터셋 일괄 처리 (retlens.batch): a row per motion file, cached per file and options, a bad file reported
without stopping the rest; and the 데이터셋 tab's table model (sorting by value, filtering)."""

import os
import shutil
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from retlens import batch  # noqa: E402
from retlens.synthetic import g1_motion  # noqa: E402

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
    # where, for 데이터셋 내보내기 to cut out: spans per problem kind (seconds as in problem_seconds), QC's bad frames
    assert set(walk["problem_spans"]) == {k for k, s in walk["problem_seconds"].items() if s > 0}
    assert isinstance(walk["qc_bad_spans"], list) and "phys_fall_times_s" not in walk  # physics off
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
    assert t["first_fall_causes"] == {}
    out = batch.write_csv(rows, str(tmp_path / "table.csv"))
    with open(out, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    assert lines[0].split(",")[:4] == ["모션", "폴더", "길이 (s)", "리타게팅 점수"] and len(lines) == 4
    header = lines[0].split(",")
    assert header.index("첫 넘어짐 원인") == header.index("물리 넘어짐") + 1


def test_batch_key_and_fall_causes(session, tmp_path, monkeypatch):
    """Physics rows are made again when the MuJoCo results change meaning (policy_replay.RESULT_VERSION), the
    other rows are not; totals count the rows per first fall cause."""
    from retlens import policy_replay as pr

    path = str(session / "walk.bvh")
    plain = batch.Batch(batch.BatchOptions(), cache_dir=str(tmp_path / "batch"))
    phys = batch.Batch(batch.BatchOptions(physics=True), cache_dir=str(tmp_path / "batch"))
    k_plain, k_phys = plain.key(path), phys.key(path)
    assert k_plain != k_phys
    monkeypatch.setattr(pr, "RESULT_VERSION", pr.RESULT_VERSION + 1)
    assert plain.key(path) == k_plain and phys.key(path) != k_phys

    class Falls:  # policy_replay.run's result for a clip with two falls (no MuJoCo needed)
        metrics = {"falls": 2, "torque_saturated_ratio": 0.1, "consistent": False, "issues": ["2 fall(s)"],
                   "harness_force_per_body_weight": {"mean": 0.2}, "first_fall_cause": "toe_catch",
                   "fall_diagnosis": [{"primary_cause": "toe_catch"}, {"primary_cause": "support_exit"}]}

    monkeypatch.setattr(pr, "run", lambda *a, **k: Falls())
    phys._sim = object()  # the harness sim, not made here
    row = phys._physics(g1_motion(seconds=1.0))
    assert row["phys_falls"] == 2 and row["phys_first_cause"] == "발끝 걸림" and row["phys_ok"] == "넘어짐 2회"
    assert row["phys_fall_causes"] == "발끝 걸림 1 · 지지면 이탈 1"
    rows = [{"phys_falls": 3, "phys_first_cause": "지지면 이탈"}, {"phys_falls": 1, "phys_first_cause": "발끝 걸림"},
            {"phys_falls": 2, "phys_first_cause": "지지면 이탈"}, {"phys_falls": 0, "phys_first_cause": None},
            {"error": "ValueError: bad", "phys_first_cause": "토크 포화"}]
    t = batch.totals(rows)
    assert t["first_fall_causes"] == {"지지면 이탈": 2, "발끝 걸림": 1} and t["with_falls"] == 3


def test_batch_physics(session, tmp_path):
    pytest.importorskip("mujoco")
    from retlens import policy_replay as pr

    if not os.path.isfile(pr.gmt_paths()["model"]):
        pytest.skip("no G1 MuJoCo model")
    b = batch.Batch(batch.BatchOptions(physics=True), cache_dir=str(tmp_path / "batch"))
    row = b.process(str(session / "walk.bvh"))
    assert row["phys_falls"] is not None and row["phys_harness_pct"] is not None and row["phys_ok"]
    assert "phys_first_cause" in row and "phys_fall_causes" in row  # the first fall's cause (None: no fall)
    assert (row["phys_first_cause"] is None) == (row["phys_falls"] == 0)


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


def test_dataset_table_qc_sorts_worst_first():
    """A click on the QC header: FAIL, WARN, PASS (by rank, not alphabetically); the next click PASS first."""
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTableView

    from retlens.app import editor

    QApplication.instance() or QApplication([])
    model, proxy = editor.BatchModel(), editor.BatchFilter()
    proxy.setSourceModel(model)
    for name, qc in (("a", "WARN"), ("b", "PASS"), ("c", "FAIL"), ("d", "PASS"), ("e", "WARN")):
        model.add({"name": name, "folder": "s", "qc": qc})
    view = QTableView()
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.sortByColumn(-1, Qt.AscendingOrder)  # as the 데이터셋 tab starts
    view.resize(900, 300)
    view.show()
    col = [k for k, _t, _f in batch.COLUMNS].index("qc")
    head = view.horizontalHeader()

    def order():
        return [model.rows[proxy.mapToSource(proxy.index(i, 0)).row()]["qc"] for i in range(proxy.rowCount())]

    QTest.mouseClick(head.viewport(), Qt.LeftButton, pos=QPoint(head.sectionViewportPosition(col) + 5, 5))
    assert order() == ["FAIL", "WARN", "WARN", "PASS", "PASS"]
    QTest.mouseClick(head.viewport(), Qt.LeftButton, pos=QPoint(head.sectionViewportPosition(col) + 5, 5))
    assert order() == ["PASS", "PASS", "WARN", "WARN", "FAIL"]
    other = [k for k, _t, _f in batch.COLUMNS].index("name")  # another column sorted in between
    for _ in range(2):
        QTest.mouseClick(head.viewport(), Qt.LeftButton, pos=QPoint(head.sectionViewportPosition(other) + 5, 5))
        QTest.mouseClick(head.viewport(), Qt.LeftButton, pos=QPoint(head.sectionViewportPosition(col) + 5, 5))
        assert order() == ["FAIL", "WARN", "WARN", "PASS", "PASS"]
    view.close()


def test_a_saved_part_is_measured_as_its_source(session, tmp_path):
    """다른 이름으로 저장한 로봇 모션 (npz + json naming its source and where in it): its row is that part of the source,
    retargeted as the json says: 리타게팅 점수, 주된 감점, 자동 라벨 of what it holds; a json naming no human motion (an
    older save named the retarget cache) leaves it a robot motion's row."""
    from retlens import dataset

    walk = str(session / "walk.bvh")
    b = batch.Batch(batch.BatchOptions(), cache_dir=str(tmp_path / "batch"))
    full = b.load_item(walk)
    out = tmp_path / "saved"
    out.mkdir()
    dur = full.robot.duration
    res = dataset.export_motion(full.robot, str(out), "walk_part", removed=[(0.0, 0.5), (dur - 0.4, dur)],
                                exact_name=True, source=walk, info={"retarget": full.retarget, "saved_as": True})
    (piece,) = res["pieces"]
    npz = str(out / "walk_part.npz")
    origin = batch.export_origin(npz)
    assert origin["source"] == os.path.abspath(walk) and origin["start_s"] == piece["start_s"] == 0.5
    item = b.load_item(npz)
    assert item.human is not None and item.robot.num_frames == piece["frames"]
    assert abs(item.human.duration - item.robot.duration) < 2.0 / item.human.fps
    row = b.process(npz)
    assert row.get("error") is None and row["retarget_score"] is not None and "저장한 것" in row["kind"]
    assert row["duration_s"] == pytest.approx(piece["duration_s"], abs=1e-3) and row["name"] == "walk_part"
    assert b.process(npz)["cached"]
    import json
    js = out / "walk_part.json"
    j = json.loads(js.read_text(encoding="utf-8"))
    # the source relative to the json's folder (shared without absolute paths), from any working folder
    j["source"] = os.path.relpath(walk, str(out)).replace("\\", "/")
    js.write_text(json.dumps(j), encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert batch.export_origin(npz)["source"] == os.path.abspath(walk)
    finally:
        os.chdir(cwd)
    # an older save: the json names the retarget cache, not the person's file
    j["source"] = full.robot.source
    js.write_text(json.dumps(j), encoding="utf-8")
    assert batch.export_origin(npz) is None
    row = b.process(npz)  # the json is in the key: a new row
    assert not row["cached"] and row["retarget_score"] is None
