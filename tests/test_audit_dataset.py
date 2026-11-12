"""데이터셋 내보내기, 일괄 처리 and retlens-cli, as an audit found them: an export never writes over or removes the
motions and label files it reads, checks its inputs before it removes an earlier export, reads nothing of its own
folder and leaves a manifest when interrupted; csv files are at 30 fps; batch rows follow their label files and the
physics config, a failed physics check is counted and tried again; summary counts a take once; the CLI answers every
failure (a mistyped command line, a physics run that failed, one bad C3D among several) with JSON."""

import csv
import json
import os
import shutil
import subprocess
import sys
import types

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from retlens import batch, dataset, paths  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402
from retlens.synthetic import g1_motion, walking_bvh_text  # noqa: E402

CLI = os.path.join(ROOT, "tools", "retlens_cli.py")
C3D = os.path.join(ROOT, "data", "raw", "cmu_c3d")
SAMPLE = os.path.join(ROOT, "data", "samples", "synthetic_g1_walk.npz")


def _cli(tmp_path, *args):
    env = dict(os.environ, RETLENS_USER_DIR=str(tmp_path / "user"))
    out = subprocess.run([sys.executable, CLI, *args], env=env, capture_output=True, timeout=300, cwd=ROOT)
    text = out.stdout.decode("utf-8").strip()
    return out.returncode, (json.loads(text) if text else None), text


def _robot(path, seconds=2.0, fps=30.0) -> str:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    g1_motion(seconds=seconds, fps=fps).save_npz(str(path))
    return str(path)


def _runner(tmp_path, **opts):
    return batch.Batch(batch.BatchOptions(**opts), cache_dir=str(tmp_path / "batch"))


def _files(folder) -> list[str]:
    return sorted(os.path.relpath(os.path.join(r, f), folder).replace("\\", "/") for r, _d, fs in os.walk(folder)
                  for f in fs)


def _same(a, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# ---------------------------------------------------------------- 데이터셋 내보내기
def test_export_never_writes_over_its_sources(tmp_path):
    sess = tmp_path / "mocap" / "sess"
    src = _robot(sess / "walk.npz")
    lab = sess / "walk.labels.csv"
    lab.write_text("label,start_s,end_s,annotator\nwalk,0,1,someone\n", encoding="utf-8")
    before = {p: open(p, "rb").read() for p in (src, str(lab))}
    opts = dataset.ExportOptions(qc="FAIL", formats=("npz", "csv"))
    for inputs, out in (([str(sess)], tmp_path / "mocap"), ([src], sess)):  # the parent folder; a file's own folder
        ex = dataset.Exporter(batch.BatchOptions(), opts, str(out), runner=_runner(tmp_path))
        with pytest.raises(ValueError, match="원본 폴더"):
            ex.run(inputs)
    assert {p: open(p, "rb").read() for p in before} == before
    assert _files(tmp_path / "mocap") == ["sess/walk.labels.csv", "sess/walk.npz"]  # nothing written, nothing removed
    code, out, _ = _cli(tmp_path, "export", str(sess), "--out", str(tmp_path / "mocap"))
    assert code == 1 and "원본 폴더" in out["error"]


def test_export_never_writes_into_another_source_folder(tmp_path):
    """--out one of the input folders: s2's motions would go to <s1>/s2, where s1 holds motions of its own."""
    m = tmp_path / "m"
    nested = _robot(m / "s1" / "s2" / "b.npz", seconds=1.5)
    _robot(m / "s1" / "a.npz")
    _robot(m / "s2" / "b.npz")
    before = open(nested, "rb").read()
    ex = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL"), str(m / "s1"), runner=_runner(tmp_path))
    with pytest.raises(ValueError, match="원본 폴더"):
        ex.run([str(m / "s1"), str(m / "s2")])
    assert open(nested, "rb").read() == before and _files(m) == ["s1/a.npz", "s1/s2/b.npz", "s2/b.npz"]


def test_clean_previous_keeps_the_sources(tmp_path):
    """A manifest that lists a source file (an export of an older version into the sources' folder): kept."""
    out = tmp_path / "ds"
    out.mkdir()
    (out / "a.npz").write_bytes(b"source")
    (out / "a.labels.csv").write_text("label,start_s,end_s\nx,0,1\n", encoding="utf-8")
    (out / "a.json").write_text("{}", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"retlens_export": 1, "clips": [
        {"files": ["a.npz"], "labels": "a.labels.csv", "info": "a.json"}]}), encoding="utf-8")
    removed = dataset.clean_previous(str(out), keep=[str(out / "a.npz"), str(out / "a.labels.csv")])
    assert sorted(os.path.basename(p) for p in removed) == ["a.json", "manifest.json"]
    assert (out / "a.npz").read_bytes() == b"source" and (out / "a.labels.csv").is_file()


def test_export_motion_refuses_its_source(tmp_path):
    from retlens.io.robot import load_robot_npz

    src = _robot(tmp_path / "walk.npz")
    with pytest.raises(ValueError, match="원본 파일"):  # robot.source: the file it was read from
        dataset.export_motion(load_robot_npz(src), str(tmp_path), "walk")
    amass = tmp_path / "a" / "01_01_stageii.npz"  # a human source whose name the robot motion keeps
    amass.parent.mkdir()
    amass.write_bytes(b"not touched")
    with pytest.raises(ValueError, match="원본 파일"):
        dataset.export_motion(g1_motion(seconds=1.0), str(amass.parent), "01_01_stageii", source=str(amass))
    assert amass.read_bytes() == b"not touched" and _files(amass.parent) == ["01_01_stageii.npz"]
    res = dataset.export_motion(g1_motion(seconds=1.0), str(amass.parent), "01_01_stageii", source=str(amass),
                                formats=("csv",))
    assert [os.path.basename(f) for f in res["pieces"][0]["files"]] == ["01_01_stageii.csv"]


def test_export_checks_inputs_first_and_leaves_a_manifest_when_interrupted(tmp_path):
    s01, s02 = tmp_path / "cap" / "s01", tmp_path / "cap" / "s02"
    _robot(s01 / "a.npz")
    _robot(s02 / "b.npz")
    out, runner = tmp_path / "ds", _runner(tmp_path)
    inputs = [str(s01), str(s02)]

    def export(inputs, formats=("npz",), **kw):
        return dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL", formats=formats), str(out),
                                runner=runner).run(inputs, **kw)

    assert export(inputs)["totals"]["clips"] == 2
    written = _files(out)
    with pytest.raises(ValueError, match="없는 파일"):  # a mistyped input: the dataset stays as it was
        export([str(tmp_path / "cap" / "s0l")])
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="모션 파일이 없습니다"):
        export([str(tmp_path / "empty")])
    assert _files(out) == written

    def stop(done, total, name):  # Ctrl+C after the first motion
        if done == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        export(inputs, formats=("npz", "csv"), progress=stop)
    with open(out / "manifest.json", encoding="utf-8") as f:
        m = json.load(f)
    assert m["stopped"] and [c["files"] for c in m["clips"]] == [["s01/a.npz", "s01/a.csv"]]
    m = export(inputs)  # the interrupted run's files are listed, so they go
    listed = {p for c in m["clips"] for p in c["files"] + [c["info"]]} | {"manifest.json", "manifest.csv"}
    assert set(_files(out)) == listed and "s01/a.csv" not in listed


def test_export_below_the_inputs_reads_none_of_its_own_files(tmp_path):
    s = tmp_path / "s01"
    _robot(s / "a.npz")
    out, runner = s / "dataset", _runner(tmp_path)
    for _ in range(2):
        m = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL", formats=("npz", "csv")), str(out),
                             runner=runner).run([str(s)])
        assert m["totals"]["motions"] == 1 and m["totals"]["clips"] == 1 and m["excluded"] == []
        assert [c["files"] for c in m["clips"]] == [["s01/a.npz", "s01/a.csv"]]
    shutil.copy(s / "a.npz", out / "stray.npz")  # left in the dataset folder: not a motion of the capture
    m = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL"), str(out), runner=runner).run([str(s)])
    assert m["totals"]["motions"] == 1 and m["excluded"] == []


def test_csv_is_written_at_30_fps(tmp_path):
    from retlens.io.robot import load_unitree_csv

    m = g1_motion(seconds=4.0, fps=50.0)  # 200 frames, 3.98 s from the first to the last
    npz, csv_path = dataset.write_motion(m, str(tmp_path / "w"), ("npz", "csv"))
    back = load_unitree_csv(csv_path, fps=30.0)  # robot csv files are read at 30 fps
    assert back.num_frames == 120 and back.dof_pos.shape[1] == 29
    rows = np.loadtxt(csv_path, delimiter=",")
    assert np.allclose(rows[::3, :3], m.root_pos[::5], atol=1e-5)  # every 3rd frame at 30 = every 5th at 50
    assert np.allclose(rows[::3, 7:], m.dof_pos[::5], atol=1e-5)
    q = rows[:, 3:7] / np.linalg.norm(rows[:, 3:7], axis=1, keepdims=True)
    assert np.allclose(np.abs(np.sum(q[::3] * m.root_quat[::5][:, [1, 2, 3, 0]], axis=1)), 1.0, atol=1e-5)
    m30 = g1_motion(seconds=1.0, fps=30.0)
    rows = np.loadtxt(dataset.write_motion(m30, str(tmp_path / "v"), ("csv",))[0], delimiter=",")
    assert rows.shape == (30, 36) and np.allclose(rows[:, :3], m30.root_pos, atol=1e-6)  # 30 fps: as it is
    assert "30 fps" in dataset.FORMATS["csv"]


# ---------------------------------------------------------------- 일괄 처리
def test_batch_rows_follow_label_files_and_physics_config(tmp_path, monkeypatch):
    path = _robot(tmp_path / "s" / "walk.npz")
    b = _runner(tmp_path)
    assert b.process(path)["labels"] is None
    lab = tmp_path / "s" / "walk.labels.csv"
    lab.write_text("label,start_s,end_s\nwalk,0,1\n", encoding="utf-8")
    row = b.process(path)  # a label file added: the row is made again
    assert not row["cached"] and row["labels"] == "file" and row["label_segments"] == 1
    assert b.process(path)["cached"]
    lab.write_text("label,start_s,end_s\nwalk,0,1\nturn,1,1.5\n", encoding="utf-8")
    row = b.process(path)
    assert not row["cached"] and row["label_segments"] == 2

    cfg = tmp_path / "physics.yaml"
    real = paths.resource
    shutil.copy(real("configs", "physics.yaml"), cfg)
    monkeypatch.setattr(paths, "resource", lambda *a: str(cfg) if a == ("configs", "physics.yaml") else real(*a))
    phys = _runner(tmp_path, physics=True)
    k_plain, k_phys = b.key(path), phys.key(path)
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert phys.key(path) != k_phys and b.key(path) == k_plain  # only the physics rows are made again


def test_batch_physics_failure_is_counted_and_tried_again(tmp_path, monkeypatch):
    m = g1_motion(seconds=1.0, fps=30.0)
    keep = [i for i, n in enumerate(m.joint_names) if n != "left_knee_joint"]
    knee = RobotMotion("knee", [m.joint_names[i] for i in keep], m.root_pos, m.root_quat, m.dof_pos[:, keep], m.fps)
    assert _runner(tmp_path, physics=True)._physics(knee)["phys_error"]  # whichever part is missing, it is said
    assert ("phys_error", "물리 오류", "{}") in batch.COLUMNS

    path = _robot(tmp_path / "s" / "walk.npz")
    phys = _runner(tmp_path, physics=True)
    monkeypatch.setattr(batch.Batch, "_physics", lambda self, robot: {"phys_error": "ValueError: no"})
    rows = [phys.process(path), phys.process(path)]
    assert [r["cached"] for r in rows] == [False, False]  # not kept: tried again next time
    t = batch.totals(rows)
    assert t["phys_errors"] == 2 and t["errors"] == 0

    knee_path = str(tmp_path / "k" / "knee.npz")
    os.makedirs(os.path.dirname(knee_path))
    knee.save_npz(knee_path)
    code, out, _ = _cli(tmp_path, "batch", knee_path, "--physics")
    assert code == 2 and out["phys_errors"] == 1 and out["rows"][0]["phys_error"]


def test_motion_files_leave_out_props_of_listed_people(tmp_path):
    cap = tmp_path / "cap"
    (cap / "lift_007" / "actor1").mkdir(parents=True)
    layout = [cap / "lift_007" / "lift_007_Prop.fbx",  # a prop file one folder above its people
              cap / "lift_007" / "actor1" / "lift_007_actor1.fbx",
              cap / "pick_001_slow.fbx", cap / "pick_001_Prop.fbx"]  # next to a variant of the take
    for p in layout:
        p.write_bytes(b"")
    got = [os.path.basename(f) for f in batch.motion_files([str(cap)])]
    assert got == ["pick_001_slow.fbx", "lift_007_actor1.fbx"]
    assert batch.motion_files([str(layout[0])]) == [str(layout[0])]  # a file given is kept as given


# ---------------------------------------------------------------- retlens-cli
def test_cli_summary_counts_a_take_once_and_names_folders_from_the_inputs(tmp_path):
    a, b = tmp_path / "dayA" / "s1", tmp_path / "dayB" / "s1"
    dataset.write_motion(g1_motion(seconds=2.0, fps=30.0), str(a / "walk"), ("npz", "csv"))  # one take, two files
    _robot(b / "run.npz", seconds=3.0)
    code, out, _ = _cli(tmp_path, "summary", str(tmp_path / "dayA"), str(tmp_path / "dayB"), "--csv",
                        str(tmp_path / "s.csv"))
    assert code == 0 and out["motions"] == 2 and out["total_s"] == pytest.approx(5.0, abs=0.1)
    assert set(out["per_folder"]) == {"dayA/s1", "dayB/s1"}
    same = [r for r in out["files"] if r.get("same_take")]
    assert [os.path.basename(r["file"]) for r in same] == ["walk.csv"] and same[0]["same_take"].endswith("walk.npz")
    with open(tmp_path / "s.csv", encoding="utf-8-sig") as f:
        assert len(f.read().splitlines()) == 3  # a row per motion counted


def test_cli_usage_errors_and_pretty_anywhere(tmp_path):
    code, out, _ = _cli(tmp_path, "batch", str(tmp_path), "--phisics")
    assert code == 1 and "--phisics" in out["error"]  # not argparse's exit 2 (batch's "some failed")
    code, out, _ = _cli(tmp_path, "export", str(tmp_path))
    assert code == 1 and "--out" in out["error"]
    code, out, _ = _cli(tmp_path)
    assert code == 1 and out["error"]
    for bad in ("-1", "20", "nan"):  # refused before anything loads
        code, out, _ = _cli(tmp_path, "inspect", "a.bvh", "--smooth", bad)
        assert code == 1 and "--smooth" in out["error"], bad
    code, out, text = _cli(tmp_path, "api", "--pretty")
    assert code == 1 and "not running" in out["error"] and "\n" in text  # indented, after the command
    code, out, text = _cli(tmp_path, "version", "--pretty")
    assert code == 0 and out["app"] == "RetLens" and "\n" in text
    import retlens_cli

    assert retlens_cli.parser().parse_args(["inspect", "a.bvh", "--smooth", "0"]).smooth == 0.0  # off


def test_cli_retarget_out(tmp_path):
    src = _robot(tmp_path / "r" / "walk.npz")
    code, out, _ = _cli(tmp_path, "retarget", src, "--out", str(tmp_path / "o" / "walk.csv"))
    assert code == 1 and ".npz" in out["error"] and not (tmp_path / "o").exists()
    code, out, _ = _cli(tmp_path, "retarget", src, "--out", str(tmp_path / "o" / "new" / "noext"))
    assert code == 0 and _same(out["out"], tmp_path / "o" / "new" / "noext.npz") and os.path.isfile(out["out"])
    assert (tmp_path / "o" / "new" / "noext.json").is_file()
    code, out, _ = _cli(tmp_path, "retarget", src, "--out", str(tmp_path / "o" / "up.NPZ"))  # numpy adds .npz to .NPZ
    assert code == 0 and out["out"].endswith("up.npz") and os.path.isfile(out["out"])
    assert not os.path.exists(str(tmp_path / "o" / "up.NPZ.npz"))
    code, out, _ = _cli(tmp_path, "retarget", src, "--out", str(tmp_path / "o" / "x.npz"), "--swing-clearance", "50")
    assert code == 1 and "--swing-clearance" in out["error"]
    code, out, _ = _cli(tmp_path, "retarget", src, "--out", src)
    assert code == 1 and "itself" in out["error"]


def test_autolabel_out_is_never_a_motion_folder(tmp_path):
    import retlens_cli

    m = tmp_path / "m"
    m.mkdir()
    (m / "walk.bvh").write_text(walking_bvh_text(seconds=1.0))
    mine = "label,start_s,end_s,annotator\nreach,0,1,someone\n"
    (m / "walk.labels.csv").write_text(mine, encoding="utf-8")
    (m / "broken.bvh").write_text("HIERARCHY\nnot a bvh\n", encoding="utf-8")
    (m / "broken.labels.csv").write_text(mine, encoding="utf-8")
    with pytest.raises(ValueError, match="모션 폴더"):
        retlens_cli._label_csv_names([str(m / "walk.bvh")], str(m))
    other = tmp_path / "other"
    other.mkdir()
    (other / "walk.fbx").write_bytes(b"")  # another motion of that name: the CSV would be its labels
    with pytest.raises(ValueError, match="모션 폴더"):
        retlens_cli._label_csv_names([str(m / "walk.bvh")], str(other))
    got = retlens_cli._label_csv_names([str(m / "walk.bvh")], str(tmp_path / "labels"))
    assert _same(got[str(m / "walk.bvh")], tmp_path / "labels" / "walk.labels.csv")
    rules = tmp_path / "r.yaml"
    rules.write_text("rules:\n  - {label: x}\n", encoding="utf-8")
    code, out, _ = _cli(tmp_path, "autolabel", str(m / "walk.bvh"), str(m / "broken.bvh"), "--rules", str(rules),
                        "--out", str(m))
    assert code == 1 and "모션 폴더" in out["error"]
    assert [(m / n).read_text(encoding="utf-8") for n in ("walk.labels.csv", "broken.labels.csv")] == [mine, mine]


def test_cli_physics_failure_is_an_error():
    import retlens_cli

    class Scene:
        phys_key, phys_error = "harness", ""

        def __init__(self, sim=False, phys=None):
            self.sim, self.phys = sim, phys

        def is_sim_result(self, item):
            return self.sim

        def shown(self, item):
            return self.phys or item

    def item(state, message):
        return types.SimpleNamespace(handles={"phys_jobs": {"harness": types.SimpleNamespace(state=state,
                                                                                              message=message)}})

    failed = item("failed", "IndexError: index -2 is out of bounds")
    assert retlens_cli._physics_failed(Scene(), failed, True, 60) == "physics failed: IndexError: index -2 is out of bounds"
    assert "60 s" in retlens_cli._physics_failed(Scene(), failed, False, 60)  # a timeout is no success either
    assert retlens_cli._physics_failed(Scene(sim=True), types.SimpleNamespace(handles={}), True, 60) is None
    assert retlens_cli._physics_failed(Scene(phys=object()), item("done", "완료"), True, 60) is None
    s = Scene()
    s.phys_error = "GMT의 G1 MuJoCo 모델이 없습니다"
    assert retlens_cli._physics_failed(s, types.SimpleNamespace(handles={}), True, 60).endswith("모델이 없습니다")


@pytest.mark.skipif(not all(os.path.isfile(os.path.join(C3D, n)) for n in ("02_01.c3d", "02_03.c3d")),
                    reason="needs data/raw/cmu_c3d (CMU sample C3D)")
def test_cli_c3d_qc_keeps_every_file(tmp_path):
    other = tmp_path / "c" / "02_01.c3d"  # another take under the same name
    other.parent.mkdir()
    shutil.copy(os.path.join(C3D, "02_03.c3d"), other)
    bad = tmp_path / "c" / "bad.c3d"
    bad.write_text("not a c3d", encoding="utf-8")
    code, ref, _ = _cli(tmp_path, "c3d-qc", os.path.join(C3D, "02_03.c3d"))
    code2, out, _ = _cli(tmp_path, "c3d-qc", os.path.join(C3D, "02_01.c3d"), str(other))
    assert code == code2 == 0 and len(out) == 2 and all(os.path.isabs(k) for k in out)  # by path when names clash
    mine = next(v for k, v in out.items() if _same(k, other))
    assert mine == ref["02_03.c3d"]
    code, out, _ = _cli(tmp_path, "c3d-qc", os.path.join(C3D, "02_03.c3d"), str(bad))
    assert code == 2 and out["bad.c3d"]["error"] and out["02_03.c3d"] == ref["02_03.c3d"]
    code, out, _ = _cli(tmp_path, "c3d-qc", str(bad))
    assert code == 1 and out["bad.c3d"]["error"]


@pytest.mark.skipif(not os.path.isfile(SAMPLE), reason="needs data/samples (tools/make_samples.py)")
def test_cli_compare_align_says_the_offsets(tmp_path):
    code, out, _ = _cli(tmp_path, "compare", SAMPLE, SAMPLE, "--align")
    assert code == 0 and isinstance(out["align_notes"], list) and len(out["align_notes"]) == 1


# ---------------------------------------------------------------- a second look
def _other_spelling(how: str, folder, tmp_path) -> str:
    """Another path of the same existing folder: its 8.3 short name, or a junction to it."""
    if how == "short":
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetShortPathNameW(str(folder), buf, 1024)
        if not buf.value or os.path.normcase(buf.value) == os.path.normcase(str(folder)):
            pytest.skip("this volume makes no 8.3 short names")
        return buf.value
    import _winapi

    link = tmp_path / "link"
    _winapi.CreateJunction(str(folder), str(link))
    return str(link)


@pytest.mark.skipif(sys.platform != "win32", reason="8.3 short names and junctions are Windows paths")
@pytest.mark.parametrize("how", ["short", "junction"])
def test_export_knows_a_folder_however_it_is_spelled(tmp_path, how):
    mocap = tmp_path / "mocap folder"
    sess = mocap / "session one"
    src = _robot(sess / "walk.npz")
    lab = sess / "walk.labels.csv"
    lab.write_text("label,start_s,end_s,annotator\nwalk,0,1,someone\n", encoding="utf-8")
    before = {p: open(p, "rb").read() for p in (src, str(lab))}
    alias = _other_spelling(how, mocap, tmp_path)
    try:
        other = os.path.join(alias, "session one")
        opts = dataset.ExportOptions(qc="FAIL", formats=("npz", "csv"))
        for inputs, out in (([other], str(mocap)), ([str(sess)], alias), ([os.path.join(other, "walk.npz")], str(sess))):
            ex = dataset.Exporter(batch.BatchOptions(), opts, out, runner=_runner(tmp_path))
            with pytest.raises(ValueError, match="원본 폴더"):
                ex.run(inputs)
        with pytest.raises(ValueError, match="원본 파일"):  # export_motion's own check
            dataset.export_motion(g1_motion(seconds=1.0), other, "walk", source=src)
        (mocap / "manifest.json").write_text(json.dumps({"retlens_export": 1, "clips": [
            {"files": ["session one/walk.npz"], "labels": "session one/walk.labels.csv"}]}), encoding="utf-8")
        removed = dataset.clean_previous(str(mocap), keep=[os.path.join(other, "walk.npz"),
                                                            os.path.join(other, "walk.labels.csv")])
        assert [os.path.basename(p) for p in removed] == ["manifest.json"]
        code, out, _ = _cli(tmp_path, "retarget", os.path.join(other, "walk.npz"), "--out", src)
        assert code == 1 and "itself" in out["error"]
        assert {p: open(p, "rb").read() for p in before} == before
        assert _files(sess) == ["walk.labels.csv", "walk.npz"]
    finally:
        if how == "junction":
            os.rmdir(alias)  # the junction only


def test_export_motion_knows_a_source_opened_through_a_file_link(tmp_path, monkeypatch):
    """A motion opened as cap/walk_stageii.npz, a file symlink (made here by realpath: Windows needs a privilege for
    one): writing cap/walk_stageii.npz would go through it, over the file it points at."""
    target = tmp_path / "real" / "walk_stageii.npz"
    link = tmp_path / "cap" / "walk_stageii.npz"
    resolve = os.path.realpath

    def realpath(p, *a, **kw):
        same = os.path.normcase(os.path.abspath(p)) == os.path.normcase(str(link))
        return str(target) if same else resolve(p, *a, **kw)

    monkeypatch.setattr(os.path, "realpath", realpath)
    with pytest.raises(ValueError, match="원본 파일"):
        dataset.export_motion(g1_motion(seconds=1.0), str(link.parent), "walk_stageii", source=str(link))
    assert not link.parent.exists()


def test_export_allow_falls_keeps_the_physics_error_and_file_warnings(tmp_path, monkeypatch):
    path = _robot(tmp_path / "cap" / "walk.npz")
    measured = batch.Batch.process
    monkeypatch.setattr(batch.Batch, "_physics", lambda self, robot: {"phys_error": "ValueError: no model"})
    monkeypatch.setattr(batch.Batch, "process",
                        lambda self, p: {**measured(self, p), "file_warnings": "두 번째 사람의 골격을 읽지 않음"})
    runner = _runner(tmp_path, physics=True)

    def export(**kw):
        return dataset.Exporter(batch.BatchOptions(physics=True), dataset.ExportOptions(qc="FAIL", **kw),
                                str(tmp_path / "ds"), runner=runner).run([path])

    m = export()
    assert m["clips"] == [] and m["excluded"][0]["reason"].startswith("물리 검사 실패")
    for kw in ({"allow_falls": True}, {"allow_falls": True, "cut": dataset.CutOptions(qc=False, kinds=())}):  # falls
        m = export(**kw)
        assert m["totals"]["phys_errors"] == 1 and len(m["clips"]) == 1, kw  # let in, and said
        clip = m["clips"][0]
        assert clip["phys_error"] == "ValueError: no model" and clip["file_warnings"].startswith("두 번째")
        with open(tmp_path / "ds" / clip["info"], encoding="utf-8") as f:
            assert json.load(f)["phys_error"] == "ValueError: no model"
        with open(tmp_path / "ds" / "manifest.csv", encoding="utf-8-sig") as f:
            row = next(csv.DictReader(f))
        assert row["phys_error"] == "ValueError: no model" and row["file_warnings"].startswith("두 번째")
    env = dict(os.environ, RETLENS_USER_DIR=str(tmp_path / "user"), RETLENS_GMT_DIR=str(tmp_path / "no_gmt"))
    res = subprocess.run([sys.executable, CLI, "export", path, "--out", str(tmp_path / "cli"), "--physics", "--qc",
                          "FAIL", "--allow-falls"], env=env, capture_output=True, timeout=300, cwd=ROOT)
    out = json.loads(res.stdout.decode("utf-8"))
    assert res.returncode == 2 and out["totals"]["phys_errors"] == 1 and out["clips"][0]["phys_error"]


def test_a_take_is_counted_by_its_first_file_that_can_be_read(tmp_path):
    s = tmp_path / "s01"
    s.mkdir()
    (s / "pick_010.bvh").write_text("HIERARCHY\nnot a bvh\n", encoding="utf-8")  # first of the take: broken
    _robot(s / "pick_010.npz", seconds=2.0)
    dataset.write_motion(g1_motion(seconds=1.0, fps=30.0), str(s / "pick_010"), ("csv",))
    _robot(s / "pick_011.npz", seconds=3.0)
    code, out, _ = _cli(tmp_path, "summary", str(s))
    rows = {os.path.basename(r["file"]): r for r in out["files"]}
    assert code == 2 and out["motions"] == 2 and out["failed"] == 1
    assert out["total_s"] == pytest.approx(5.0, abs=0.1) and rows["pick_010.npz"]["duration_s"] == pytest.approx(2.0, abs=0.1)
    assert rows["pick_010.bvh"]["error"] and os.path.basename(rows["pick_010.csv"]["same_take"]) == "pick_010.npz"
    m = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL"), str(tmp_path / "ds"),
                         runner=_runner(tmp_path)).run([str(s)])
    assert sorted(os.path.basename(c["source"]) for c in m["clips"]) == ["pick_010.npz", "pick_011.npz"]
    why = {os.path.basename(e["source"]): e["reason"] for e in m["excluded"]}
    assert why["pick_010.bvh"].startswith("읽지 못함") and why["pick_010.csv"] == "같은 촬영: pick_010.npz로 내보냄"


def test_manifest_gives_the_csv_its_own_rate(tmp_path):
    src = _robot(tmp_path / "cap" / "walk.npz", seconds=4.0, fps=50.0)  # 200 frames at 50 fps
    for formats, fps in ((("csv",), 30.0), (("npz", "csv"), 50.0)):
        m = dataset.Exporter(batch.BatchOptions(), dataset.ExportOptions(qc="FAIL", formats=formats),
                             str(tmp_path / "ds"), runner=_runner(tmp_path)).run([src])
        clip = m["clips"][0]
        rows = len(np.loadtxt(tmp_path / "ds" / "walk.csv", delimiter=","))
        assert m["csv_fps"] == 30.0 and clip["csv_fps"] == 30.0 and clip["csv_frames"] == rows == 120
        assert clip["fps"] == 50.0 and clip["frames"] == 200
        with open(tmp_path / "ds" / "manifest.csv", encoding="utf-8-sig") as f:
            row = next(csv.DictReader(f))
        assert float(row["fps"]) == fps and int(row["frames"]) == (rows if fps == 30.0 else 200), formats
        with open(tmp_path / "ds" / "walk.json", encoding="utf-8") as f:
            assert json.load(f)["csv_frames"] == rows


def test_summary_rows_say_what_the_reader_left_out(tmp_path, monkeypatch):
    import retlens_cli
    from retlens import compare

    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "walk.bvh").write_text(walking_bvh_text(seconds=1.0))
    read = compare.load_skeleton

    def load(path, *a, **kw):  # as an FBX of two people gives it (retlens.io.fbx)
        human = read(path, *a, **kw)
        human.meta["warnings"] = ["두 번째 사람의 골격을 읽지 않음"]
        return human

    monkeypatch.setattr(compare, "load_skeleton", load)
    monkeypatch.setattr(retlens_cli, "_smpl", lambda: None)
    out = retlens_cli.summary(retlens_cli.parser().parse_args(["summary", str(tmp_path / "m"), "--csv",
                                                                str(tmp_path / "s.csv")]))
    assert out["files"][0]["warnings"] == ["두 번째 사람의 골격을 읽지 않음"]
    with open(tmp_path / "s.csv", encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f))["warnings"] == "두 번째 사람의 골격을 읽지 않음"


def test_label_csv_names_take_linear_time(tmp_path):
    import time

    import retlens_cli

    n, out = 2000, tmp_path / "labels"
    out.mkdir()
    files = [str(tmp_path / "caps" / f"s{i // 50:03d}" / f"take_{i:05d}.bvh") for i in range(n)]
    for i in range(n):  # an earlier run's CSVs
        (out / f"take_{i:05d}.labels.csv").write_bytes(b"")
    t = time.perf_counter()
    names = retlens_cli._label_csv_names(files, str(out))
    assert len(names) == n and time.perf_counter() - t < 2.0  # each name looked up, not the whole listing per motion
    (out / "TAKE_00007.FBX").write_bytes(b"")  # a motion of that name, in other case
    with pytest.raises(ValueError, match="모션 폴더"):
        retlens_cli._label_csv_names(files[:10], str(out))


def test_cli_says_a_missing_file_before_the_scene(tmp_path, monkeypatch):
    import retlens_cli

    missing = str(tmp_path / "work" / "missing.bvh")
    monkeypatch.setattr(retlens_cli, "_scene", lambda args: pytest.fail("the 3D scene started"))
    for argv in (["inspect", missing], ["metrics", missing], ["compare", missing, missing], ["align", missing, missing],
                 ["physics", missing], ["video", missing]):
        with pytest.raises(FileNotFoundError, match="없는 파일") as e:
            retlens_cli.run(retlens_cli.parser().parse_args(argv))
        assert missing in str(e.value), argv
    assert retlens_cli._err(FileNotFoundError(2, "No such file or directory", missing)) == \
        f"FileNotFoundError: No such file or directory: {missing}"  # the path as it is, not its repr
    code, out, _ = _cli(tmp_path, "retarget", missing, "--out", str(tmp_path / "o" / "x.npz"))
    assert code == 1 and missing in out["error"] and not (tmp_path / "o").exists()


def test_policy_runner_sim_follows_the_config_content(tmp_path):
    from retlens import policy_runner
    from retlens.physics_runner import PHYSICS_CONFIG

    cfg = tmp_path / "physics.yaml"
    shutil.copy(PHYSICS_CONFIG, cfg)
    r = policy_runner.PolicyRunner(str(tmp_path / "cache"), physics_config=str(cfg), simulate=lambda *a: None)
    try:
        k = r._sim_key("harness")
        assert r._sim_key("harness") == k
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        assert r._sim_key("harness") != k  # an edited config builds a new sim (its gains and fall rules)
    finally:
        r.shutdown()
