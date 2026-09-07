"""Desktop entry point: the thing a packaged build runs when double-clicked.

The command line assumes someone who knows to run `setup` before `serve`. A
person who has downloaded an application does not, and should not have to. So
this does the whole job in one step:

    build the library if it is not there yet  ->  serve  ->  open the browser

The first run takes about twenty seconds because it builds a 13,703-article
database and a full-text index. That is a long time to look at nothing, so it
reports progress and says why it is waiting. Every later run starts instantly.

Nothing here touches the network.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import sys
import threading
import time
import webbrowser
from wsgiref.simple_server import WSGIServer

from .config import Config, is_frozen
from .db import Database, connect
from .db.migrate import migrate_all
from .logging_setup import setup_logging

log = logging.getLogger("encarta.app")

BANNER = r"""
   __  __         _                 ___                 _
  |  \/  |___  __| |___ _ _ _ _    | __|_ _  __ __ _ _ _| |_ __ _
  | |\/| / _ \/ _` / -_) '_| ' \   | _|| ' \/ _/ _` | '_|  _/ _` |
  |_|  |_\___/\__,_\___|_| |_||_|  |___|_||_\__\__,_|_|  \__\__,_|

  An offline encyclopaedia that shows its sources.
"""


def _free_port(host: str, preferred: int) -> int:
    """Return `preferred` if it is free, otherwise any free port.

    A second copy of the app, or anything else already on 8000, must not make
    the application fail to start with a stack trace.
    """
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise SystemExit("No free port available on 127.0.0.1")


def _needs_build(config: Config) -> bool:
    if not config.content_db.exists():
        return True
    try:
        conn = connect(config.content_db, config.user_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM article WHERE status = 'published'"
            ).fetchone()
            return not row or row["n"] == 0
        finally:
            conn.close()
    except Exception:
        # An unreadable or half-written database is a reason to rebuild, not to
        # crash on startup in front of someone who just opened the app.
        return True


def _build(config: Config) -> None:
    """First-run setup, narrated. Content is bundled; nothing is downloaded."""
    from .content.loader import PackLoader
    from .services import FactChecker, QualityService, SearchIndexer

    print("  Setting up for the first time. This happens once.\n", flush=True)
    config.ensure_dirs()
    conn = connect(config.content_db, config.user_db)
    try:
        print("  [1/4] Preparing the database", flush=True)
        migrate_all(conn, config.user_db)

        print("  [2/4] Loading articles (this is the slow part)", flush=True)
        packs = sorted(
            p for p in (config.content_dir / "packs").glob("*") if (p / "pack.json").is_file()
        )
        if not packs:
            raise SystemExit(f"No content packs found in {config.content_dir / 'packs'}")
        loader = PackLoader(conn, strict=False)
        total = 0
        for pack in packs:
            report = loader.load_pack(pack)
            total += report.total_articles
            print(f"        {pack.name}: {report.total_articles:,} articles", flush=True)

        print("  [3/4] Building the search index", flush=True)
        SearchIndexer(conn).rebuild()

        print("  [4/4] Scoring quality and checking sources", flush=True)
        QualityService(conn).score_all()
        FactChecker(conn).run()
        print(f"\n  Ready: {total} articles.\n", flush=True)
    finally:
        conn.close()


def _serve(config: Config, host: str, port: int) -> WSGIServer:
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    from .web.api import create_app

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("%s - %s", self.address_string(), fmt % args)

    db = Database(config.content_db, config.user_db)
    return make_server(host, port, create_app(config, db), ThreadingWSGIServer, QuietHandler)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    no_browser = "--no-browser" in argv

    config = Config.load()
    # The screen belongs to the progress messages below; the detail goes to the
    # log file. A person who opened an application should not have to read
    # migration records to find out whether it is working.
    setup_logging(config.log_level, config.data_dir, console_level="WARNING")

    print(BANNER)
    print(f"  Your library and notes:  {config.data_dir}")
    if is_frozen():
        print("  Everything runs on this machine. No account, no internet, no tracking.")
    print()

    try:
        if _needs_build(config):
            _build(config)
    except Exception as exc:      # the last line of defence before a blank window
        log.exception("first-run setup failed")
        print(f"\n  Setup failed: {exc}\n", flush=True)
        print("  The application cannot start. Details are in:")
        print(f"    {config.data_dir / 'encarta.log'}")
        _wait_for_exit()
        return 1

    host = config.host
    port = _free_port(host, config.port)
    url = f"http://{host}:{port}"

    try:
        server = _serve(config, host, port)
    except Exception as exc:
        log.exception("could not start the server")
        print(f"\n  Could not start the server: {exc}\n", flush=True)
        _wait_for_exit()
        return 1

    count = Database(config.content_db, config.user_db).scalar(
        "SELECT COUNT(*) AS n FROM article WHERE status='published'"
    )
    print(f"  {count:,} articles ready at  {url}", flush=True)
    print("  Close this window to stop the encyclopaedia.\n", flush=True)

    if not no_browser:
        # Give the server a moment to accept connections before the browser asks.
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        server.server_close()
    return 0


def _wait_for_exit() -> None:
    """Keep a double-clicked window open long enough to read the error.

    Without this the window vanishes instantly and the person is left with an
    app that appears to do nothing at all.
    """
    if not sys.stdin or not sys.stdin.isatty():
        time.sleep(20)
        return
    with contextlib.suppress(EOFError, KeyboardInterrupt):
        input("  Press Enter to close. ")


if __name__ == "__main__":
    raise SystemExit(main())
