"""Write synthetic sample motions to data/samples/ for smoke-testing the
QC report and the Isaac Sim replay before real capture data exists.

    python tools/make_samples.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from khumanoid.synthetic import g1_motion, walking_bvh_text  # noqa: E402


def main() -> None:
    out = os.path.join(ROOT, "data", "samples")
    os.makedirs(out, exist_ok=True)

    with open(os.path.join(out, "synthetic_walk.bvh"), "w", encoding="utf-8") as f:
        f.write(walking_bvh_text(seconds=8.0, fps=60.0))

    # same clip with a 0.3 s marker-swap style glitch, to see QC flags in the viewer
    lines = walking_bvh_text(seconds=8.0, fps=60.0).splitlines()
    start = lines.index("MOTION") + 3
    for i in range(start + 200, start + 218):
        vals = lines[i].split()
        vals[0] = f"{float(vals[0]) + 80.0:.4f}"  # hips jump 80 cm sideways
        lines[i] = " ".join(vals)
    with open(os.path.join(out, "synthetic_walk_glitch.bvh"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    robot = g1_motion(seconds=8.0, fps=50.0)
    robot.save_npz(os.path.join(out, "synthetic_g1_walk.npz"))
    robot = g1_motion(seconds=8.0, fps=30.0)  # Unitree csv files carry no fps; they are 30 fps
    q_xyzw = robot.root_quat[:, [1, 2, 3, 0]]
    np.savetxt(os.path.join(out, "synthetic_g1_walk_unitree.csv"),
               np.concatenate([robot.root_pos, q_xyzw, robot.dof_pos], 1), delimiter=",", fmt="%.6f")
    print(f"wrote samples to {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
