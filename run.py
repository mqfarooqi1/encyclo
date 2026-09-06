#!/usr/bin/env python3
"""Run Modern Encarta without installing it.

    python run.py setup     # build the database from the content packs
    python run.py serve     # start the application

Equivalent to `python -m encarta ...` once the package is installed; this
wrapper just puts src/ on the path so the project runs from a clean checkout
with nothing but a Python interpreter.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from encarta.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
