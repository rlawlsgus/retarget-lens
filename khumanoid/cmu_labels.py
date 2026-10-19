"""CMU mocap trial descriptions ("143_11" -> "Walk And Pick up Box") for file browsers.

Read once from the metadata.csv of the Hugging Face CMU FBX set (data/raw/cmu_fbx,
tools/fetch_samples.py cmu_fbx); empty when that file is missing. Full list with
lengths: docs/cmu_motion_labels.md (tools/cmu_motion_index.py).
"""

from __future__ import annotations

import csv
import functools
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
METADATA = os.path.join(ROOT, "data", "raw", "cmu_fbx", "metadata.csv")
TRIAL_RE = re.compile(r"^(\d{1,3}_\d{1,3})(?:_|\.|$)")


@functools.lru_cache(maxsize=1)
def labels(path: str = METADATA) -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].lower().endswith(".fbx"):
                out[row[0][:-4]] = row[1].strip()
    return out


def trial_of(path: str) -> str | None:
    """'143_11' for 143_11.bvh, 143_11_stageii.npz, 143_11_g1.npz; None otherwise."""
    m = TRIAL_RE.match(os.path.basename(path))
    return m.group(1) if m else None


def label_for(path: str) -> str:
    t = trial_of(path)
    return labels().get(t, "") if t else ""
