"""Entry point of the packaged RetLens.exe (PyInstaller, packaging/retlens.spec)."""

import sys

from retlens.app.runtime import main

if __name__ == "__main__":
    sys.exit(main())
