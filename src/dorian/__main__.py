"""Enable `python -m dorian ...` as an alias for the `dorian` console script."""

from __future__ import annotations

import sys

from dorian.cli import main

if __name__ == "__main__":
    sys.exit(main())
