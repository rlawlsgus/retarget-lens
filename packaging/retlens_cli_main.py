"""Entry point of the packaged retlens-cli.exe (console; the same commands as tools/retlens_cli.py)."""

import sys

from retlens_cli import main

if __name__ == "__main__":
    sys.exit(main())
