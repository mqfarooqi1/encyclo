"""HTTP layer, exercised through the WSGI interface rather than a live socket."""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from encarta.db import Database
from encarta.web.api import create_app


@pytest.fixture
def app(config, loaded_db):
    return create_app(config, Database(loaded_db / "content.db", loaded_db / "user.db"))


def call(app, path, method="GET", body=None):
    payload = json.dumps(body).encode() if body is not None else b""
    path, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(payload)),
        "wsgi.input": BytesIO(payload),
    }
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = raw
    return captured["status"], data, captured["headers"]


def test_health(app):
    status, data, _ = call(app, "/api/health")
    assert status == 200
    assert data["offline_capable"] is True


def test_security_headers_are_present(app):
    _, _, headers = call(app, "/api/health")
    assert "Content-Security-Policy" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    # The app must not be able to load remote code.
    assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_bootstrap_reports_capabilities_honestly(app):
    status, data, _ = call(app, "/api/bootstrap")
    assert status == 200
    assert data["capabilities"]["ai"] is False       # no provider configured in tests
    assert len(data["reading_levels"]) == 4


def test_article_endpoint(app):
    status, data, _ = call(app, "/api/article/tyrannosaurus-rex")
    assert status == 200
    assert data["title"] == "Tyrannosaurus rex"
    assert data["citations"]
    assert data["facts"]
    assert data["version"]


def test_article_alias_resolves(app):
    status, data, _ = call(app, "/api/article/t-rex")
    assert status == 200
    assert data["slug"] == "tyrannosaurus-rex"


def test_requesting_a_missing_level_falls_back_and_says_so(app):
    status, data, _ = call(app, "/api/article/solar-system?level=age6_8")
    assert status == 200
    assert data["reading_level"] in {"age6_8", "age9_12", "teen", "adult"}
    if data["reading_level"] != "age6_8":
        assert data["level_substituted"] is True


def test_unknown_article_is_404(app):
    status, _, _ = call(app, "/api/article/does-not-exist")
    assert status == 404


def test_search(app):
    status, data, _ = call(app, "/api/search?q=largest%20dinosaur")
    assert status == 200
    assert data["hits"]


def test_search_with_hostile_input_is_still_200(app):
    status, _, _ = call(app, "/api/search?q=%22%20OR%201%3D1%20--")
    assert status == 200


def test_graph_endpoint(app):
    status, data, _ = call(app, "/api/article/tyrannosaurus-rex/graph")
    assert status == 200
    assert data["nodes"] and data["edges"]


def test_timeline_endpoint(app):
    status, data, _ = call(app, "/api/timeline?limit=50")
    assert status == 200
    assert data
    assert all("start_year" in row for row in data)


def test_compare_requires_two_slugs(app):
    status, _, _ = call(app, "/api/compare?slugs=earth")
    assert status == 400
    status, data, _ = call(app, "/api/compare?slugs=earth,mars")
    assert status == 200
    assert len(data["articles"]) == 2
    assert data["rows"]


def test_quiz_questions_all_have_explanations(app):
    status, data, _ = call(app, "/api/quiz/trex-basics")
    assert status == 200
    for question in data["questions"]:
        assert question["explanation"].strip()
        assert any(o["is_correct"] for o in question["options"])


def test_bookmark_roundtrip(app):
    status, _, _ = call(app, "/api/bookmarks", "POST", {"slug": "earth"})
    assert status == 201
    _, data, _ = call(app, "/api/bookmarks")
    assert any(r["article_slug"] == "earth" for r in data)
    status, _, _ = call(app, "/api/bookmarks/earth", "DELETE")
    assert status == 200
    _, data, _ = call(app, "/api/bookmarks")
    assert not any(r["article_slug"] == "earth" for r in data)


def test_admin_dashboard_and_issues(app):
    status, data, _ = call(app, "/api/admin/dashboard")
    assert status == 200
    assert data["stats"]["articles"] > 0
    status, issues, _ = call(app, "/api/admin/issues")
    assert status == 200
    assert isinstance(issues, list)


def test_method_not_allowed(app):
    status, _, _ = call(app, "/api/health", "POST")
    assert status == 405


def test_static_path_traversal_is_blocked(app):
    status, _, _ = call(app, "/../../pyproject.toml")
    assert status in (403, 404)


def test_unknown_frontend_route_serves_the_shell(app):
    """Deep links must survive a reload."""
    status, _body, headers = call(app, "/article/earth")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
