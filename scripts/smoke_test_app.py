"""Prove a built executable actually works, before it is offered to anyone.

    python scripts/smoke_test_app.py dist/ModernEncarta.exe

Runs the real binary against a throwaway data directory: it builds the whole
database from the bundled content packs, starts the server, and must answer
correctly on the API. Anything less would only prove the file exists.

This is the check that would have caught the packaged build importing its own
entry module incorrectly - a fault invisible to the unit tests, because they
never run the bundle.

Two details are load-bearing, and both were learned the hard way:

* The child's output goes to a **file**, never to a pipe. A one-file build
  writes progress for the whole cold build; nobody is draining a pipe during
  that, and once its buffer fills the application blocks mid-build.
* Shutting down kills the whole process **tree**. A one-file build is a
  bootloader that unpacks itself and runs the real application as a child, so
  terminating the process you launched leaves the application running - holding
  the port, and the pipe, indefinitely.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
BUILD_TIMEOUT = 420          # a cold build indexes 13,703 articles
POLL_SECONDS = 2
IS_WINDOWS = platform.system() == "Windows"


def say(message: str = "") -> None:
    # Unbuffered: CI shows output as it happens, not in one lump at the end.
    print(message, flush=True)


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as response:
        return json.loads(response.read())


def _launch(binary: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen:
    """Start the application with its output going to a file, not a pipe."""
    kwargs: dict = {}
    if IS_WINDOWS:
        # Its own process group, so the whole tree can be signalled later.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    handle = log_path.open("w", encoding="utf-8", errors="replace")
    return subprocess.Popen(
        [str(binary), "--no-browser"], env=env,
        stdout=handle, stderr=subprocess.STDOUT, **kwargs,
    )


def _stop(process: subprocess.Popen) -> None:
    """Stop the application and every process it spawned."""
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True, check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_for_server(process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + BUILD_TIMEOUT
    announced = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            say(_tail(log_path))
            raise SystemExit(
                f"the application exited with code {process.returncode} before serving"
            )
        try:
            if _get("/api/health").get("status") == "ok":
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            if not announced:
                say("  building the library on first run, this takes a while ...")
                announced = True
        time.sleep(POLL_SECONDS)
    say(_tail(log_path))
    raise SystemExit(f"no response from {BASE} within {BUILD_TIMEOUT}s")


def _tail(log_path: Path, limit: int = 3000) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n--- application output ---\n" + text[-limit:] if text.strip() else ""


def _check(label: str, condition: bool, detail: str = "") -> None:
    say(f"  {'ok  ' if condition else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not condition:
        raise SystemExit(f"smoke test failed: {label}")


def _run_checks() -> None:
    health = _get("/api/health")
    _check("serves /api/health", health.get("status") == "ok")
    _check("reports itself offline-capable", health.get("offline_capable") is True)
    _check("makes no network calls", health.get("network_allowed") is False)

    home = _get("/api/home")
    articles = home["stats"]["articles"]
    _check("built a real library", articles > 1000, f"{articles:,} articles")
    _check("has a daily discovery", bool(home.get("discovery")))
    _check("has featured articles", len(home.get("featured") or []) > 0)

    hits = _get("/api/search?q=moon&limit=3")["hits"]
    _check("search returns results", len(hits) > 0)
    _check("search ranks the authored article first", hits[0]["title"] == "The Moon",
           f"got {hits[0]['title']!r}")

    space = _get("/api/category/space?limit=3")
    _check("category browse is paged", space["total"] > len(space["articles"]),
           f"{space['total']:,} in Space")

    kids = _get("/api/search?q=moondial&kids=1")["hits"]
    _check("Kids Mode excludes imported articles", len(kids) == 0)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: smoke_test_app.py <path to built executable>")
    binary = Path(argv[1]).resolve()
    if not binary.is_file():
        raise SystemExit(f"no such file: {binary}")
    if not IS_WINDOWS:
        binary.chmod(0o755)

    with tempfile.TemporaryDirectory(prefix="encarta-smoke-") as workdir:
        data_dir = Path(workdir)
        log_path = data_dir / "app-output.log"
        env = {
            **os.environ,
            "ENCARTA_DATA_DIR": str(data_dir),   # never touch a real user's library
            "ENCARTA_PORT": str(PORT),
            "ENCARTA_ALLOW_NETWORK": "0",        # must build with no network at all
        }
        say(f"running {binary.name} against a temporary library ...")
        process = _launch(binary, env, log_path)
        try:
            _wait_for_server(process, log_path)
            _run_checks()
            say(f"\nall checks passed against {binary.name}")
            return 0
        finally:
            _stop(process)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
