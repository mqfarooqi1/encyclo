"""Build the standalone desktop application.

    python scripts/build_app.py

Produces one self-contained executable in `dist/`. It needs no Python, no
installer and no network: the content packs and SQL migrations are bundled
inside, and the database is built on the machine it runs on the first time it
is opened.

Why one file rather than a directory: the download is a single thing a person
can move to their desktop and double-click. It costs a second or two of
extraction on each launch, which is the right trade for an application opened
occasionally rather than a server started constantly.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "ModernEncarta"


def _data_args() -> list[str]:
    """Files that must travel inside the bundle.

    `--add-data` uses os.pathsep between source and destination, which differs
    between Windows and everywhere else; PyInstaller accepts ':' on all
    platforms since 6.0, but the native separator is safer across versions.
    """
    sep = ";" if sys.platform == "win32" else ":"
    pairs = [
        (ROOT / "content", "content"),
        (ROOT / "src" / "encarta" / "db" / "migrations", "encarta/db/migrations"),
        (ROOT / "src" / "encarta" / "web" / "static", "encarta/web/static"),
    ]
    args: list[str] = []
    for source, dest in pairs:
        if not source.exists():
            raise SystemExit(f"missing bundle input: {source}")
        args += ["--add-data", f"{source}{sep}{dest}"]
    return args


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed. Run:  python -m pip install --user pyinstaller"
        ) from None

    packs = ROOT / "content" / "packs"
    found = sorted(p.name for p in packs.glob("*") if (p / "pack.json").is_file())
    if not found:
        raise SystemExit(f"No content packs in {packs} - nothing to ship")
    print(f"bundling content packs: {', '.join(found)}")

    for stale in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    icon = ROOT / "site" / "favicon.ico"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", NAME,
        # A console window is deliberate, not an oversight: the first run takes
        # about twenty seconds, and this is where it reports progress. Hiding it
        # would leave someone staring at nothing wondering if it had crashed.
        "--console",
        "--noconfirm",
        "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "src"),
        *_data_args(),
        # Several modules are imported lazily inside functions, so static
        # analysis cannot see them. Collecting the package wholesale is both
        # simpler and safer than listing them and discovering a missing one
        # only when a feature is used.
        "--collect-submodules", "encarta",
        # Nothing in this application draws a window or does numerical work;
        # excluding these keeps the download small.
        "--exclude-module", "tkinter",
        "--exclude-module", "numpy",
        "--exclude-module", "pytest",
        "--exclude-module", "PIL",
    ]
    if icon.is_file():
        command += ["--icon", str(icon)]
    command.append(str(ROOT / "desktop.py"))

    print("running PyInstaller ...")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    built = next((ROOT / "dist").glob(f"{NAME}*"), None)
    if built is None:
        raise SystemExit("PyInstaller reported success but produced no executable")
    print(f"\nbuilt {built}  ({built.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
