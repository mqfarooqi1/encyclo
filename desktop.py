#!/usr/bin/env python3
"""Launch Modern Encarta as a desktop application.

    python desktop.py

Builds the library on first run, starts the local server and opens a browser.
This is also the entry point the packaged executable runs.

It exists as a top-level script rather than pointing the packager straight at
`encarta/app.py` because a bundler executes its entry script as `__main__`,
outside any package, where that module's relative imports have nothing to
resolve against. Importing the package by name works in both cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Running from a checkout: make src/ importable without installing.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from encarta.app import main

if __name__ == "__main__":
    raise SystemExit(main())
