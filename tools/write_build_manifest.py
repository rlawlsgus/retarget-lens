"""Write dist/RetLens/_internal/retlens-build.json: the build's version and every file with its size.

RetLens checks a downloaded update against it before using it, copies exactly these files when a portable copy
installs itself, and reads the version of a RetLens folder from it without running anything (retlens/install.py).

    python tools/write_build_manifest.py dist/RetLens
"""

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

SKIP = {"_internal/retlens-build.json", "retlens-install.json", ".retlens-staged.json"}


def main(folder: str) -> int:
    from retlens import __version__

    folder = os.path.abspath(folder)
    files = {}
    for root, _dirs, names in os.walk(folder):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), folder).replace("\\", "/")
            if rel not in SKIP:
                files[rel] = os.path.getsize(os.path.join(root, n))
    for need in ("RetLens.exe", "retlens-cli.exe", "retlens-update.exe"):
        if need not in files:
            print(f"{need} is missing in {folder}")
            return 1
    out = os.path.join(folder, "_internal", "retlens-build.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"product": "RetLens", "version": __version__, "files": dict(sorted(files.items()))}, f, indent=0)
    print(f"{out}: version {__version__}, {len(files)} files, {sum(files.values()) / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "RetLens")))
