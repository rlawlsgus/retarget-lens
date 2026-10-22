"""GMT's tracking policy (pretrained.pt) in numpy, without PyTorch.

The authors ship the policy as a TorchScript archive (a zip: data.pkl + tensor files). This
module reads the weights straight from that zip - a restricted unpickler that only builds plain
objects and numpy arrays, so a file from the internet cannot run code - and evaluates the network
the archive's code describes (GMT commit 2a590de, "HardwareRefNN"):

    obs (2154) = motion targets (20 frames x 30) | proprioception (74) | history (20 x 74)
    normalise:  (obs - mean) / (std + 1e-4)
    motion encoder:   per frame Linear(30, 60) + SiLU, then over the 20 frames Conv1d(60, 40, 6, stride 2)
                      + SiLU, Conv1d(40, 20, 4, stride 2) + SiLU, flatten, Linear(60, 128)
    history encoder:  the same shape with 74 -> 30 -> 20 -> 10 channels, Linear(30, 64)
    actor:  [proprio, first motion frame, motion latent, history latent] (296)
            Linear 1024, SiLU, Linear 1024, SiLU, Linear 512, SiLU, Linear 256, LayerNorm, SiLU, Linear 23

All in float32 like the TorchScript module; it matches torch.jit's output to float rounding
(tests/test_gmt_policy.py). The installed RetLens has no PyTorch, so this is what runs there.
"""

from __future__ import annotations

import collections
import hashlib
import io
import os
import pickle
import zipfile

import numpy as np

OBS_DIM = 2154
ACTION_DIM = 23
FRAMES = 20  # reference frames / history steps the encoders see
MIMIC_DIM, PROP_DIM = 30, 74  # per reference frame / per proprioception step
NORM_EPS = 1e-4  # the archive's constant: (obs - mean) / (std + eps)
LN_EPS = 1e-5  # torch.layer_norm's default (the archive calls it without eps)
CONV_STRIDE = 2

# parameter name -> shape the network above needs (the check that a file is this policy)
SHAPES = {
    "normalizer._mean": (OBS_DIM,), "normalizer._std": (OBS_DIM,),
    "motion_encoder.encoder.0.weight": (60, MIMIC_DIM), "motion_encoder.encoder.0.bias": (60,),
    "motion_encoder.conv_layers.0.weight": (40, 60, 6), "motion_encoder.conv_layers.0.bias": (40,),
    "motion_encoder.conv_layers.2.weight": (20, 40, 4), "motion_encoder.conv_layers.2.bias": (20,),
    "motion_encoder.linear_output.weight": (128, 60), "motion_encoder.linear_output.bias": (128,),
    "history_encoder.encoder.0.weight": (30, PROP_DIM), "history_encoder.encoder.0.bias": (30,),
    "history_encoder.conv_layers.0.weight": (20, 30, 6), "history_encoder.conv_layers.0.bias": (20,),
    "history_encoder.conv_layers.2.weight": (10, 20, 4), "history_encoder.conv_layers.2.bias": (10,),
    "history_encoder.linear_output.weight": (64, 30), "history_encoder.linear_output.bias": (64,),
    "actor_backbone.0.weight": (1024, 296), "actor_backbone.0.bias": (1024,),
    "actor_backbone.2.weight": (1024, 1024), "actor_backbone.2.bias": (1024,),
    "actor_backbone.4.weight": (512, 1024), "actor_backbone.4.bias": (512,),
    "actor_backbone.6.weight": (256, 512), "actor_backbone.6.bias": (256,),
    "actor_backbone.7.weight": (256,), "actor_backbone.7.bias": (256,),
    "actor_backbone.9.weight": (ACTION_DIM, 256), "actor_backbone.9.bias": (ACTION_DIM,),
}

# code_fingerprint of archives whose forward pass this port reproduces (checked against torch.jit):
# the same network code with other weights is fine, other code (clipping, eps, layout) is refused
KNOWN_CODE = {"a41022b9e8a514d8ef53b105be24265480193ffb216319b54e1792ce089fd1f5": "GMT 2a590de (HardwareRefNN)"}

_STORAGE_DTYPES = {"FloatStorage": np.float32, "DoubleStorage": np.float64, "HalfStorage": np.float16,
                   "LongStorage": np.int64, "IntStorage": np.int32, "ShortStorage": np.int16,
                   "CharStorage": np.int8, "ByteStorage": np.uint8, "BoolStorage": np.bool_}


class PolicyFileError(ValueError):
    """The file is not GMT's TorchScript policy (or not one this port knows)."""


class _Object:
    """A pickled TorchScript module: its attributes land in __dict__ (submodules, tensors)."""


class _StorageType:
    def __init__(self, name: str):
        self.dtype = _STORAGE_DTYPES[name]


class _Storage:
    """A tensor storage as persistent_load read it from the archive. Only persistent_load makes these
    (find_class never hands the class out), so a pickle cannot pass anything else as a storage."""
    __slots__ = ("arr",)

    def __init__(self, arr: np.ndarray):
        self.arr = arr


def _rebuild_tensor(storage, offset, size, stride, *_):
    """The tensor view torch would make - after checking it stays inside its storage (a crafted file
    must not make as_strided read past the buffer, or ask for more elements than the file holds)."""
    if not isinstance(storage, _Storage):
        raise PolicyFileError(f"tensor storage is not a storage from the archive ({type(storage).__name__})")
    buf = storage.arr
    size, stride = tuple(int(n) for n in size), tuple(int(n) for n in stride)
    offset = int(offset)
    if (len(size) != len(stride) or offset < 0 or any(n < 0 for n in size) or any(s < 0 for s in stride)
            or any(s == 0 for n, s in zip(size, stride) if n > 1)):  # no broadcast (stride 0) views in a policy
        raise PolicyFileError(f"bad tensor layout (offset {offset}, size {size}, stride {stride})")
    if 0 in size:
        return np.zeros(size, dtype=buf.dtype)
    last = offset + sum((n - 1) * s for n, s in zip(size, stride))
    numel = int(np.prod(size, dtype=np.int64))
    if last >= buf.size or numel > buf.size:
        raise PolicyFileError(f"tensor reaches past its storage ({max(last + 1, numel)} > {buf.size})")
    item = buf.itemsize
    return np.lib.stride_tricks.as_strided(buf[offset:], shape=size, strides=tuple(s * item for s in stride)).copy()


class _Unpickler(pickle.Unpickler):
    """Only what a TorchScript data.pkl holds: module objects, tensors, OrderedDict. Anything
    else (functions, other classes) is refused instead of imported."""

    def __init__(self, data: bytes, archive: zipfile.ZipFile, prefix: str, folder: str):
        super().__init__(io.BytesIO(data))
        self.archive, self.prefix, self.folder = archive, prefix, folder

    def find_class(self, module, name):
        if module == "torch._utils" and name == "_rebuild_tensor_v2":
            return _rebuild_tensor
        if module == "torch" and name in _STORAGE_DTYPES:
            return _StorageType(name)
        if module == "collections" and name == "OrderedDict":
            return collections.OrderedDict
        if module.startswith("__torch__"):
            return type(name, (_Object,), {})
        raise PolicyFileError(f"unexpected object in the policy file: {module}.{name}")

    def persistent_load(self, pid):
        kind, storage_type, key, _location, numel = pid
        if kind != "storage" or not isinstance(storage_type, _StorageType):
            raise PolicyFileError(f"unexpected storage reference {pid!r}")
        data = self.archive.read(f"{self.prefix}{self.folder}/{key}")
        arr = np.frombuffer(data, dtype=storage_type.dtype)
        if arr.size < numel:
            raise PolicyFileError(f"storage {key} is short ({arr.size} < {numel})")
        return _Storage(arr)


def _walk(obj, name: str, out: dict, seen: set | None = None) -> None:
    seen = set() if seen is None else seen
    if id(obj) in seen or len(seen) > 10000:  # a module that contains itself (pickle memo), or absurdly many
        raise PolicyFileError(f"the module tree loops or is too large (at {name or 'the root'})")
    seen.add(id(obj))
    for k, v in vars(obj).items():
        path = f"{name}.{k}" if name else k
        if isinstance(v, np.ndarray):
            out[path] = v
        elif isinstance(v, _Object):
            _walk(v, path, out, seen)


def _prefix(archive: zipfile.ZipFile, path: str) -> str:
    pkl = [n for n in archive.namelist() if n.endswith("/data.pkl") and n.count("/") == 1]
    if len(pkl) != 1:
        raise PolicyFileError(f"{path}: no data.pkl at the top of the archive")
    return pkl[0][: -len("data.pkl")]


def code_fingerprint(path: str) -> str:
    """SHA-256 of the archive's TorchScript code and constants (not the weights): what the network
    computes. The .debug_pkl records are left out: they only map code to source lines for error
    messages and hold the exporter's file paths, so the same network saved elsewhere has other ones.
    This port reproduces only the code it was checked against (KNOWN_CODE)."""
    try:
        with zipfile.ZipFile(path) as archive:
            prefix = _prefix(archive, path)
            names = sorted(n for n in archive.namelist()
                           if (n.startswith(prefix + "code/") or n.startswith(prefix + "constants"))
                           and not n.endswith(".debug_pkl"))
            h = hashlib.sha256()
            for n in names:
                h.update(n[len(prefix):].encode() + b"\0")
                h.update(archive.read(n))
    except PolicyFileError:
        raise
    except Exception as e:  # not a zip, truncated, encrypted, unknown compression, corrupt deflate
        raise PolicyFileError(f"{path}: not a readable TorchScript archive ({type(e).__name__}: {e})") from None
    return h.hexdigest()


def load_params(path: str) -> dict[str, np.ndarray]:
    """{parameter name: array} of a TorchScript archive (names as torch's named_parameters / buffers)."""
    try:
        with zipfile.ZipFile(path) as archive:
            prefix = _prefix(archive, path)
            if prefix + "byteorder" in archive.namelist():  # older archives have none: little-endian, as torch reads them
                if archive.read(prefix + "byteorder").strip() != b"little":
                    raise PolicyFileError(f"{path}: tensors are not little-endian")
            root = _Unpickler(archive.read(prefix + "data.pkl"), archive, prefix, "data").load()
        if not isinstance(root, _Object):
            raise PolicyFileError(f"{path}: data.pkl does not hold a module")
        out: dict[str, np.ndarray] = {}
        _walk(root, "", out)
    except PolicyFileError:
        raise
    except Exception as e:  # truncated or malformed archive / pickle, missing storage entries
        raise PolicyFileError(f"{path}: unreadable policy file ({type(e).__name__}: {e})") from None
    return out


def _silu(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):  # exp(-x) -> inf for very negative x: x * 0 = -0, as torch gives
        return x / (np.float32(1.0) + np.exp(-x))


def _linear(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    return x @ w.T + b


def _conv1d(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(batch, in, length) -> (batch, out, length'), stride 2, no padding."""
    k = w.shape[2]
    n = (x.shape[2] - k) // CONV_STRIDE + 1
    s = x.strides
    win = np.lib.stride_tricks.as_strided(x, shape=(x.shape[0], x.shape[1], n, k),
                                          strides=(s[0], s[1], s[2] * CONV_STRIDE, s[2]))
    return np.einsum("bcnk,ock->bon", win, w, optimize=True) + b[None, :, None]


def _layer_norm(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    mean = x.mean(-1, keepdims=True)
    var = ((x - mean) ** 2).mean(-1, keepdims=True)
    return (x - mean) / np.sqrt(var + np.float32(LN_EPS)) * w + b


class GMTPolicy:
    """policy(obs) -> raw action (23,), like the TorchScript module called on one observation."""

    def __init__(self, path: str):
        code = code_fingerprint(path)
        if code not in KNOWN_CODE:
            raise PolicyFileError(f"{path}: its network code is not the one this port reproduces (GMT 2a590de); "
                                  "it could compute something else (observation clipping, eps, layout)")
        p = load_params(path)
        bad = [f"{k} {p[k].shape if k in p else 'missing'} (expected {s})" for k, s in SHAPES.items()
               if k not in p or p[k].shape != s]
        if bad:
            raise PolicyFileError(f"{path}: not the GMT policy this port knows: {'; '.join(bad[:4])}")
        self.p = {k: np.ascontiguousarray(p[k], dtype=np.float32) for k in SHAPES}
        self.path = path

    def _encoder(self, name: str, x: np.ndarray) -> np.ndarray:
        p, batch = self.p, x.shape[0]
        h = _silu(_linear(x.reshape(batch * FRAMES, -1), p[f"{name}.encoder.0.weight"], p[f"{name}.encoder.0.bias"]))
        h = np.ascontiguousarray(h.reshape(batch, FRAMES, -1).transpose(0, 2, 1))
        h = _silu(_conv1d(h, p[f"{name}.conv_layers.0.weight"], p[f"{name}.conv_layers.0.bias"]))
        h = _silu(_conv1d(np.ascontiguousarray(h), p[f"{name}.conv_layers.2.weight"], p[f"{name}.conv_layers.2.bias"]))
        return _linear(h.reshape(batch, -1), p[f"{name}.linear_output.weight"], p[f"{name}.linear_output.bias"])

    def forward(self, obs: np.ndarray) -> np.ndarray:
        """(batch, 2154) -> (batch, 23), float32."""
        p = self.p
        x = (np.asarray(obs, dtype=np.float32) - p["normalizer._mean"]) / (p["normalizer._std"] + np.float32(NORM_EPS))
        mimic = x[:, : FRAMES * MIMIC_DIM]
        prop = x[:, FRAMES * MIMIC_DIM: FRAMES * MIMIC_DIM + PROP_DIM]
        hist = x[:, FRAMES * MIMIC_DIM + PROP_DIM:]
        h = np.concatenate([prop, mimic[:, :MIMIC_DIM], self._encoder("motion_encoder", mimic),
                            self._encoder("history_encoder", hist)], axis=1)
        a = "actor_backbone"
        h = _silu(_linear(h, p[f"{a}.0.weight"], p[f"{a}.0.bias"]))
        h = _silu(_linear(h, p[f"{a}.2.weight"], p[f"{a}.2.bias"]))
        h = _silu(_linear(h, p[f"{a}.4.weight"], p[f"{a}.4.bias"]))
        h = _silu(_layer_norm(_linear(h, p[f"{a}.6.weight"], p[f"{a}.6.bias"]), p[f"{a}.7.weight"], p[f"{a}.7.bias"]))
        return _linear(h, p[f"{a}.9.weight"], p[f"{a}.9.bias"])

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        obs = np.asarray(obs, dtype=np.float32)
        if obs.shape[-1] != OBS_DIM:
            raise ValueError(f"GMT observation must have {OBS_DIM} values, got {obs.shape}")
        return self.forward(obs.reshape(1, OBS_DIM))[0]


_checked: dict = {}


def problem(path: str) -> str:
    """'' when path is a GMT policy this port runs, else why not (cached per file version: menus and
    checks call it often). Never raises: whatever is wrong with the file is the answer."""
    try:
        st = os.stat(path)
    except OSError:
        return f"{path}이(가) 없습니다"
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if key not in _checked:
        try:
            GMTPolicy(path)
            _checked[key] = ""
        except PolicyFileError as e:
            _checked[key] = f"쓸 수 없는 정책 파일: {e}"
        except Exception as e:  # MemoryError and the like: still not a policy RetLens can run
            _checked[key] = f"쓸 수 없는 정책 파일: {path}: {type(e).__name__}: {e}"
    return _checked[key]
