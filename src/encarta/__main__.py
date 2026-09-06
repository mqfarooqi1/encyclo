"""Command line entry point.

    python -m encarta setup      # migrate, load the core pack, index, score
    python -m encarta serve      # run the app
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config
from .content.loader import LoaderError, PackLoader, read_pack_articles
from .content.validate import ContentValidator, has_errors
from .db import Database, connect
from .db.migrate import migrate_all
from .logging_setup import setup_logging
from .services import FactChecker, QualityService, SearchIndexer

log = logging.getLogger("encarta")


def _packs(config: Config, name: str | None) -> list[Path]:
    root = config.content_dir / "packs"
    if name:
        path = root / name
        if not path.is_dir():
            raise SystemExit(f"No content pack at {path}")
        return [path]
    return sorted(p for p in root.glob("*") if (p / "pack.json").is_file())


def cmd_migrate(config: Config, _: argparse.Namespace) -> int:
    config.ensure_dirs()
    conn = connect(config.content_db, config.user_db)
    result = migrate_all(conn, config.user_db)
    for schema, applied in result.items():
        print(f"{schema}: {len(applied)} migration(s) applied" + (
            f" -> {', '.join(applied)}" if applied else " (already current)"))
    conn.close()
    return 0


def cmd_load(config: Config, args: argparse.Namespace) -> int:
    config.ensure_dirs()
    conn = connect(config.content_db, config.user_db)
    migrate_all(conn, config.user_db)
    loader = PackLoader(conn, strict=not args.force)
    exit_code = 0
    for pack in _packs(config, args.pack):
        try:
            report = loader.load_pack(pack)
        except LoaderError as exc:
            print(f"FAILED {pack.name}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        print(report.summary())
        warnings = [f for f in report.findings if f.severity == "warning"]
        errors = [f for f in report.findings if f.severity == "error"]
        for finding in errors[:10] + warnings[:10]:
            print(f"  {finding}")
        if len(warnings) + len(errors) > 20:
            print(f"  ... and {len(warnings) + len(errors) - 20} more findings")
    conn.close()
    return exit_code


def cmd_validate(config: Config, args: argparse.Namespace) -> int:
    exit_code = 0
    from .content.loader import read_pack_json

    for pack in _packs(config, args.pack):
        taxonomy = read_pack_json(pack / "taxonomy.json", {})
        sources = read_pack_json(pack / "sources.json", [])
        media = read_pack_json(pack / "media.json", [])
        labelled = read_pack_articles(pack)
        articles = [art for _, art in labelled]

        validator = ContentValidator(
            known_sources={s["uid"] for s in sources},
            known_media={m["uid"] for m in media},
            known_slugs={a.get("slug", "") for a in articles},
            known_types={t["key"] for t in taxonomy.get("types", [])},
            known_categories={c["key"] for c in taxonomy.get("categories", [])},
        )
        findings = []
        for label, art in labelled:
            findings.extend(validator.validate_article(art, where=label))

        by_severity = {"error": 0, "warning": 0, "info": 0}
        for finding in findings:
            by_severity[finding.severity] += 1
            if finding.severity != "info" or args.verbose:
                print(f"  {finding}")
        print(
            f"{pack.name}: {len(articles)} articles | "
            f"{by_severity['error']} errors, {by_severity['warning']} warnings, "
            f"{by_severity['info']} info"
        )
        if has_errors(findings):
            exit_code = 1
    return exit_code


def cmd_import_wikipedia(config: Config, args: argparse.Namespace) -> int:
    """Import openly licensed reference text to scale the library.

    Requires network access, which the application otherwise never uses.
    """
    from .content.loader import read_pack_articles
    from .pipeline.wikipedia import PLAN, WikipediaImporter

    if not config.allow_network:
        print(
            "This needs network access, which is off by default.\n"
            "Re-run with:  ENCARTA_ALLOW_NETWORK=1 python run.py import-wikipedia\n"
            "(on Windows PowerShell:  $env:ENCARTA_ALLOW_NETWORK=1)",
            file=sys.stderr,
        )
        return 1

    # Hand-written articles always win: never overwrite authored text with an
    # imported extract of the same subject.
    core = config.content_dir / "packs" / "core"
    existing = {art.get("slug", "") for _, art in read_pack_articles(core)} if core.is_dir() else set()

    out_dir = config.content_dir / "packs" / args.pack
    plan = PLAN
    if args.subjects:
        wanted = {s.strip().lower() for s in args.subjects.split(",")}
        plan = tuple(s for s in PLAN if s.category.lower() in wanted)
        if not plan:
            print(f"no subjects matched {args.subjects!r}", file=sys.stderr)
            return 1

    importer = WikipediaImporter(config, exclude_slugs=existing)
    report = importer.run(out_dir, plan=plan, limit=args.limit)
    print(report.summary())
    if report.errors:
        print(f"{len(report.errors)} non-fatal errors, first few:")
        for message in report.errors[:5]:
            print(f"  {message}")
    print(f"\nwrote {out_dir}")
    print("Now run:  python run.py load && python run.py index && python run.py score")
    return 0


def cmd_index(config: Config, _: argparse.Namespace) -> int:
    conn = connect(config.content_db, config.user_db)
    count = SearchIndexer(conn).rebuild()
    print(f"indexed {count} articles")
    conn.close()
    return 0


def cmd_score(config: Config, _: argparse.Namespace) -> int:
    conn = connect(config.content_db, config.user_db)
    result = QualityService(conn).score_all()
    print(
        f"scored {result['scored']} articles | average {result['average']} "
        f"| range {result['lowest']}-{result['highest']}"
    )
    conn.close()
    return 0


def cmd_check(config: Config, _: argparse.Namespace) -> int:
    conn = connect(config.content_db, config.user_db)
    counts = FactChecker(conn).run()
    total = sum(counts.values())
    print(f"fact-check complete: {total} open issue(s)")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        if count:
            print(f"  {kind:22} {count}")
    conn.close()
    return 0


def cmd_setup(config: Config, args: argparse.Namespace) -> int:
    """Everything needed to go from empty to a running encyclopaedia."""
    for step, fn in (
        ("migrate", cmd_migrate),
        ("load", cmd_load),
        ("index", cmd_index),
        ("score", cmd_score),
        ("check", cmd_check),
    ):
        print(f"\n== {step} ==")
        code = fn(config, args)
        if code != 0 and step == "load":
            return code
    print("\nSetup complete. Run:  python -m encarta serve")
    return 0


def cmd_stats(config: Config, _: argparse.Namespace) -> int:
    from .repositories import DiscoveryRepository

    conn = connect(config.content_db, config.user_db)
    stats = DiscoveryRepository(conn).stats()
    width = max(len(k) for k in stats) if stats else 10
    for key, value in stats.items():
        print(f"{key:<{width}}  {value}")
    conn.close()
    return 0


def cmd_serve(config: Config, args: argparse.Namespace) -> int:
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    from .web.api import create_app

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, format: str, *log_args: object) -> None:
            log.debug("%s - %s", self.address_string(), format % log_args)

    if not config.content_db.exists():
        print("No content database found. Run:  python -m encarta setup", file=sys.stderr)
        return 1

    db = Database(config.content_db, config.user_db)
    app = create_app(config, db)
    host, port = args.host or config.host, args.port or config.port

    with make_server(host, port, app, ThreadingWSGIServer, QuietHandler) as httpd:
        count = db.scalar("SELECT COUNT(*) AS n FROM article WHERE status='published'")
        print(f"\n  Modern Encarta -- {count} articles, offline-first")
        print(f"  http://{host}:{port}\n")
        print(f"  AI: {config.ai_provider}   Network: {'on' if config.allow_network else 'off'}")
        print("  Ctrl+C to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="encarta", description="Modern Encarta - offline-first educational encyclopaedia"
    )
    parser.add_argument("--data-dir", type=Path, help="override the data directory")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create or upgrade the database schema")

    load = sub.add_parser("load", help="load content packs into the database")
    load.add_argument("pack", nargs="?", help="pack directory name (default: all)")
    load.add_argument("--force", action="store_true",
                      help="load despite validation errors (records them as issues)")

    validate = sub.add_parser("validate", help="validate content packs without loading")
    validate.add_argument("pack", nargs="?")
    validate.add_argument("-v", "--verbose", action="store_true", help="include info findings")

    wiki = sub.add_parser(
        "import-wikipedia",
        help="import openly licensed reference articles (needs ENCARTA_ALLOW_NETWORK=1)",
    )
    wiki.add_argument("--pack", default="wikipedia", help="pack directory name to write")
    wiki.add_argument("--limit", type=int, default=None, help="cap the number of articles")
    wiki.add_argument("--subjects", default=None,
                      help="comma-separated Wikipedia categories to restrict the harvest to")

    sub.add_parser("index", help="rebuild the full-text search index")
    sub.add_parser("score", help="recompute article quality scores")
    sub.add_parser("check", help="run automated fact and integrity checks")
    sub.add_parser("stats", help="print database statistics")

    setup = sub.add_parser("setup", help="migrate, load, index, score and check in one step")
    setup.add_argument("pack", nargs="?")
    setup.add_argument("--force", action="store_true")
    setup.add_argument("-v", "--verbose", action="store_true")

    serve = sub.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    return parser


COMMANDS = {
    "migrate": cmd_migrate,
    "load": cmd_load,
    "validate": cmd_validate,
    "import-wikipedia": cmd_import_wikipedia,
    "index": cmd_index,
    "score": cmd_score,
    "check": cmd_check,
    "stats": cmd_stats,
    "setup": cmd_setup,
    "serve": cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(args.data_dir)
    setup_logging(args.log_level or config.log_level, config.data_dir)
    try:
        return COMMANDS[args.command](config, args)
    except LoaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
