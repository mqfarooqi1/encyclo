#!/usr/bin/env python3
"""Build a distributable archive of the application.

    python scripts/build_release.py

Produces dist/modern-encarta-<version>.zip containing everything needed to run
the app — source, content packs and documentation — and nothing that should not
be redistributed: no database, no personal data, no environment file, no caches.

The archive is what a download link should point at. Attach it to a GitHub
release; the site's fallback link to the repository zipball works without one.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

# Everything the application needs to run from a clean unpack.
INCLUDE_DIRS = ("src", "content", "docs", "scripts", "tests")
INCLUDE_FILES = ("run.py", "pyproject.toml", "README.md", "LICENSE", ".env.example")

# Never shipped: generated state, personal data, secrets, tooling caches.
EXCLUDE_PARTS = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".git", ".venv", "venv", "data", "dist", "node_modules", ".claude",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}
EXCLUDE_NAMES = {".env", ".DS_Store", "Thumbs.db"}


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def wanted(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_NAMES:
        return False
    return path.is_file()


def collect() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        candidate = ROOT / name
        if candidate.is_file():
            files.append(candidate)
    for directory in INCLUDE_DIRS:
        base = ROOT / directory
        if not base.is_dir():
            continue
        files.extend(p for p in sorted(base.rglob("*")) if wanted(p))
    return files


def content_summary() -> dict[str, int]:
    """Counts for the release notes, read from the content pack rather than
    hardcoded, so they cannot drift."""
    pack = ROOT / "content" / "packs" / "core"
    articles = list((pack / "articles").glob("*.json"))
    quizzes = json.loads((pack / "quizzes.json").read_text(encoding="utf-8"))
    sources = json.loads((pack / "sources.json").read_text(encoding="utf-8"))
    trails = json.loads((pack / "trails.json").read_text(encoding="utf-8"))
    levels = 0
    for path in articles:
        levels += len(json.loads(path.read_text(encoding="utf-8")).get("content", {}))
    return {
        "articles": len(articles),
        "reading_levels": levels,
        "sources": len(sources),
        "quizzes": len(quizzes),
        "questions": sum(len(q.get("questions", [])) for q in quizzes),
        "trails": len(trails.get("trails", [])),
        "badges": len(trails.get("badges", [])),
    }


def main() -> int:
    release = version()
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"modern-encarta-{release}.zip"

    files = collect()
    if not files:
        print("nothing to package", file=sys.stderr)
        return 1

    root_name = f"modern-encarta-{release}"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, Path(root_name) / path.relative_to(ROOT))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )

    summary = content_summary()
    print(f"built {archive.relative_to(ROOT)}")
    print(f"  {len(files)} files, {archive.stat().st_size / 1_000_000:.2f} MB")
    print(f"  sha256 {digest}")
    print("  contents: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
