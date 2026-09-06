"""A small, dependency-free WSGI application.

Written to the WSGI spec rather than against a framework, so the app runs on the
stdlib server during development and under any production WSGI server (waitress,
gunicorn) without code changes -- and adds no third-party attack surface to
something intended to run on a child's machine.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The app ships everything it needs and talks to nothing else. This CSP is the
# enforcement of that promise: no remote scripts, no remote fonts, no beacons.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "media-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

SECURITY_HEADERS = [
    ("Content-Security-Policy", _CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=(), interest-cohort=()"),
]


class HttpError(Exception):
    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


@dataclass(slots=True)
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes
    params: dict[str, str]

    def get(self, key: str, default: str | None = None) -> str | None:
        values = self.query.get(key)
        return values[0] if values else default

    def get_int(self, key: str, default: int, *, low: int = 0, high: int = 1000) -> int:
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return max(low, min(high, int(raw)))
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw.lower() in ("1", "true", "yes", "on")

    def get_list(self, key: str) -> list[str]:
        return [v for raw in self.query.get(key, []) for v in raw.split(",") if v]

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(400, "Request body is not valid JSON") from exc
        if not isinstance(data, dict):
            raise HttpError(400, "Request body must be a JSON object")
        return data


@dataclass(slots=True)
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: list[tuple[str, str]] | None = None

    @classmethod
    def json(cls, data: Any, status: int = 200, *, cache: int = 0) -> Response:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        headers = [("Cache-Control", f"private, max-age={cache}" if cache else "no-store")]
        return cls(status=status, body=payload, headers=headers)

    @classmethod
    def text(cls, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> Response:
        return cls(status=status, body=text.encode("utf-8"), content_type=content_type)


_STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content", 304: "Not Modified",
    400: "Bad Request", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 413: "Payload Too Large",
    422: "Unprocessable Entity", 500: "Internal Server Error",
    503: "Service Unavailable",
}

Handler = Callable[[Request], Response]


class Router:
    """Pattern router. `{name}` captures one path segment."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile(
            "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$"
        )
        self._routes.append((method.upper(), regex, handler))

    def route(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self.add(method, pattern, fn)
            return fn

        return decorator

    def get(self, pattern: str) -> Callable[[Handler], Handler]:
        return self.route("GET", pattern)

    def post(self, pattern: str) -> Callable[[Handler], Handler]:
        return self.route("POST", pattern)

    def delete(self, pattern: str) -> Callable[[Handler], Handler]:
        return self.route("DELETE", pattern)

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str]] | None:
        allowed = False
        for route_method, regex, handler in self._routes:
            match = regex.match(path)
            if not match:
                continue
            if route_method != method.upper():
                allowed = True
                continue
            return handler, match.groupdict()
        if allowed:
            raise HttpError(405, f"{method} is not allowed on {path}")
        return None


# 2 MB ceiling on request bodies; nothing this app accepts is anywhere near it.
MAX_BODY = 2 * 1024 * 1024


class WSGIApp:
    def __init__(self, router: Router, static_dir: Path = STATIC_DIR) -> None:
        self.router = router
        self.static_dir = static_dir

    def __call__(
        self, environ: dict[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        try:
            response = self._handle(environ)
        except HttpError as exc:
            response = Response.json(
                {"error": exc.message, "status": exc.status, "detail": exc.detail},
                status=exc.status,
            )
        except Exception:
            log.error("unhandled error\n%s", traceback.format_exc())
            response = Response.json(
                {"error": "Internal server error", "status": 500}, status=500
            )

        status_line = f"{response.status} {_STATUS_TEXT.get(response.status, 'Unknown')}"
        headers = [
            ("Content-Type", response.content_type),
            ("Content-Length", str(len(response.body))),
            *SECURITY_HEADERS,
            *(response.headers or []),
        ]
        start_response(status_line, headers)
        return [response.body]

    def _handle(self, environ: dict[str, Any]) -> Response:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/") or "/"

        if path.startswith("/api/"):
            return self._handle_api(environ, method, path)

        static = self._serve_static(path)
        if static is not None:
            return static

        # Unknown non-API path: hand back the shell so the client-side router
        # can render it (deep links such as /article/earth work on reload).
        index = self.static_dir / "index.html"
        if index.is_file():
            return Response(
                body=index.read_bytes(),
                content_type="text/html; charset=utf-8",
                headers=[("Cache-Control", "no-cache")],
            )
        raise HttpError(404, "Not found")

    def _handle_api(self, environ: dict[str, Any], method: str, path: str) -> Response:
        resolved = self.router.resolve(method, path)
        if resolved is None:
            raise HttpError(404, f"No API route for {path}")
        handler, params = resolved

        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            raise HttpError(413, "Request body too large")
        body = environ["wsgi.input"].read(length) if length else b""

        request = Request(
            method=method,
            path=path,
            query=parse_qs(environ.get("QUERY_STRING", "")),
            headers={
                k[5:].replace("_", "-").lower(): v
                for k, v in environ.items()
                if k.startswith("HTTP_")
            },
            body=body,
            params=params,
        )
        return handler(request)

    def _serve_static(self, path: str) -> Response | None:
        rel = path.lstrip("/") or "index.html"
        candidate = (self.static_dir / rel).resolve()
        # Path traversal guard: the resolved file must stay inside static_dir.
        try:
            candidate.relative_to(self.static_dir.resolve())
        except ValueError:
            raise HttpError(403, "Forbidden") from None
        if not candidate.is_file():
            return None
        content_type, _ = mimetypes.guess_type(candidate.name)
        # Hashed asset names are not used yet, so keep caching conservative.
        cache = "public, max-age=3600" if candidate.suffix in {".woff2", ".png", ".svg"} else "no-cache"
        return Response(
            body=candidate.read_bytes(),
            content_type=content_type or "application/octet-stream",
            headers=[("Cache-Control", cache)],
        )
