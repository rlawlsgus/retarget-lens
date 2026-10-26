"""RetLens (Retarget Lens), the desktop motion editor (Qt): scene view, hierarchy,
inspector, project browser, timeline, analysis and console in dockable panels. See
retlens/app/editor.py.

    python tools/editor.py
    python tools/editor.py data/raw/cmu_bvh/02_01.bvh data/raw/amass_cmu_smplx/CMU/143/143_11_stageii.npz
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from retlens.app.runtime import main  # noqa: E402  (log file + error dialogs when installed / windowless)

if __name__ == "__main__":
    sys.exit(main())
