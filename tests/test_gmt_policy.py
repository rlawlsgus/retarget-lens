"""GMT's tracking policy in numpy (khumanoid/gmt_policy.py): same output as the TorchScript module,
and the file reader refuses anything but tensors and module objects."""

import os
import pickle
import sys
import zipfile

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from khumanoid import gmt_policy, policy_replay as pr  # noqa: E402


def _policy_file() -> str:
    path = pr.gmt_paths()["policy"]
    if not os.path.isfile(path):
        pytest.skip(f"needs GMT's pretrained.pt ({path}; scripts/install_gmt.ps1)")
    return path


def test_matches_torchscript():
    path = _policy_file()
    torch = pytest.importorskip("torch")
    net = torch.jit.load(path, map_location="cpu").eval()
    ours = gmt_policy.GMTPolicy(path)
    mean, std = ours.p["normalizer._mean"], ours.p["normalizer._std"]
    rng = np.random.default_rng(0)
    obs = (mean + std * rng.normal(size=(64, gmt_policy.OBS_DIM)) * 1.5).astype(np.float32)  # around the data
    obs[:4] = 0.0  # and edge cases: all zero, very large
    obs[4] *= 50.0
    with torch.no_grad():
        want = net(torch.from_numpy(obs)).numpy()
    got = ours.forward(obs)
    assert got.dtype == np.float32 and got.shape == (64, gmt_policy.ACTION_DIM)
    assert np.allclose(got, want, rtol=1e-4, atol=1e-4), np.abs(got - want).max()
    assert np.allclose(ours(obs[7]), want[7], rtol=1e-4, atol=1e-4)  # one observation, as the sim calls it
    params = gmt_policy.load_params(path)  # every tensor, named as torch names them
    for name, t in list(net.named_parameters()) + list(net.named_buffers()):
        assert np.array_equal(params[name], t.detach().numpy()), name


def test_refuses_other_files(tmp_path):
    bad = tmp_path / "x.pt"
    bad.write_bytes(b"not a zip")
    with pytest.raises(gmt_policy.PolicyFileError):
        gmt_policy.GMTPolicy(str(bad))

    # a pickle that would call os.system on load: the reader must refuse to build it
    class Evil:
        def __reduce__(self):
            return os.system, ("echo pwned",)

    evil = tmp_path / "evil.pt"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("m/data.pkl", pickle.dumps(Evil(), protocol=2))
        z.writestr("m/byteorder", "little")
    with pytest.raises(gmt_policy.PolicyFileError, match="unexpected object"):
        gmt_policy.load_params(str(evil))

    # a well-formed archive of some other network (an empty __torch__.Net): its code is not the one this
    # port reproduces, and its tensors would not have the shapes either
    wrong = tmp_path / "wrong.pt"
    with zipfile.ZipFile(wrong, "w") as z:
        z.writestr("m/data.pkl", b"\x80\x02c__torch__\nNet\nq\x00)\x81}b.")
        z.writestr("m/byteorder", "little")
    with pytest.raises(gmt_policy.PolicyFileError, match="network code"):
        gmt_policy.GMTPolicy(str(wrong))
    assert gmt_policy.problem(str(wrong)).startswith("쓸 수 없는") and "없습니다" in gmt_policy.problem(str(tmp_path / "x"))

    # a tensor whose size / stride reach past its one-float storage: refused, never read out of bounds
    storage = (b"(X\x07\x00\x00\x00storageq\x00ctorch\nFloatStorage\nq\x01X\x01\x00\x00\x000q\x02X\x03\x00\x00\x00cpuq\x03"
               b"K\x01tq\x04Q")
    big = (b"\x80\x02c__torch__\nNet\nq\x00)\x81}X\x01\x00\x00\x00wctorch._utils\n_rebuild_tensor_v2\n(" + storage +
           b"K\x00J\x00\x00\x10\x00\x85K\x01\x85\x89ccollections\nOrderedDict\n)RtRsb.")  # w = rebuild(...)
    oob = tmp_path / "oob.pt"
    with zipfile.ZipFile(oob, "w") as z:
        z.writestr("m/data.pkl", big)
        z.writestr("m/byteorder", "little")
        z.writestr("m/data/0", np.float32(1).tobytes())
    with pytest.raises(gmt_policy.PolicyFileError, match="past its storage"):
        gmt_policy.load_params(str(oob))

    def one_tensor(name, storage_part, stride):
        p = tmp_path / name
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("m/data.pkl", b"\x80\x02c__torch__\nNet\nq\x00)\x81}X\x01\x00\x00\x00wctorch._utils\n"
                                     b"_rebuild_tensor_v2\n(" + storage_part + b"K\x00J\x00\x00\x10\x00\x85" + stride +
                                     b"\x89ccollections\nOrderedDict\n)RtRsb.")
            z.writestr("m/data/0", np.float32(1).tobytes())
        return str(p)

    # a broadcast (stride 0) view would make a million floats out of one: refused before the copy
    with pytest.raises(gmt_policy.PolicyFileError, match="bad tensor layout"):
        gmt_policy.load_params(one_tensor("zero.pt", storage, b"K\x00\x85"))
    # something other than the archive's storage passed as the storage (here an OrderedDict)
    with pytest.raises(gmt_policy.PolicyFileError, match="not a storage"):
        gmt_policy.load_params(one_tensor("fake.pt", b"ccollections\nOrderedDict\n)R", b"K\x01\x85"))
    # a module that contains itself (the pickle memo makes that legal): refused, no endless recursion
    loop = tmp_path / "loop.pt"
    with zipfile.ZipFile(loop, "w") as z:
        z.writestr("m/data.pkl", b"\x80\x02c__torch__\nNet\nq\x00)\x81q\x01}X\x02\x00\x00\x00meh\x01sb.")
    with pytest.raises(gmt_policy.PolicyFileError, match="loops"):
        gmt_policy.load_params(str(loop))


def _rewrite(src, dst, drop=(), replace=None):
    """A copy of a TorchScript archive with entries left out or replaced (names without the top folder)."""
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst, "w") as b:
        for info in a.infolist():
            name = info.filename.split("/", 1)[1]
            if name not in drop:
                b.writestr(info.filename, (replace or {}).get(name) or a.read(info))
    return str(dst)


def test_malformed_policy_is_reported_not_raised(tmp_path):
    """problem() answers for any file (the menus, the settings check and the setup assistant call it
    at start-up): the authors' network with broken parts is refused with a reason, never an exception."""
    path = _policy_file()
    # no byteorder record (archives from older torch): little-endian, as torch reads it
    assert gmt_policy.problem(_rewrite(path, tmp_path / "old.pt", drop=("byteorder",))) == ""
    looped = _rewrite(path, tmp_path / "loop.pt",
                      replace={"data.pkl": b"\x80\x02c__torch__\nNet\nq\x00)\x81q\x01}X\x02\x00\x00\x00meh\x01sb."})
    assert "loops" in gmt_policy.problem(looped)
    no_data = _rewrite(path, tmp_path / "nodata.pt", drop=tuple(f"data/{i}" for i in range(3)))
    assert gmt_policy.problem(no_data).startswith("쓸 수 없는 정책 파일")


def test_other_weights_of_the_same_network():
    """A checkpoint of the same network trained or saved elsewhere (other weights, other exporter
    paths in the debug records) runs; its code fingerprint is the authors'."""
    path = _policy_file()
    torch = pytest.importorskip("torch")
    import tempfile

    net = torch.jit.load(path, map_location="cpu").eval()
    with torch.no_grad():
        for p in net.parameters():
            if p.is_floating_point():
                p.mul_(1.01)
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "retrained.pt")
        torch.jit.save(net, out)
        assert gmt_policy.code_fingerprint(out) in gmt_policy.KNOWN_CODE and gmt_policy.problem(out) == ""
        ours = gmt_policy.GMTPolicy(out)
        obs = np.zeros((2, gmt_policy.OBS_DIM), dtype=np.float32)
        with torch.no_grad():
            want = net(torch.from_numpy(obs)).numpy()
        assert np.allclose(ours.forward(obs), want, rtol=1e-4, atol=1e-4)
