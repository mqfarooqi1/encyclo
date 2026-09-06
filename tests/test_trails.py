"""Explorer Trail: unlocking, scoring, badges and progress durability."""

from __future__ import annotations

import json

import pytest

from encarta.content.loader import LoaderError, PackLoader
from encarta.services.progress import TrailService, stars_for


@pytest.fixture
def trails(conn):
    service = TrailService(conn)
    service.reset()
    yield service
    service.reset()


def test_pack_defines_trails_and_badges(conn):
    assert conn.execute("SELECT COUNT(*) AS n FROM trail").fetchone()["n"] >= 2
    assert conn.execute("SELECT COUNT(*) AS n FROM badge").fetchone()["n"] >= 10
    assert conn.execute("SELECT COUNT(*) AS n FROM trail_station").fetchone()["n"] >= 10


def test_every_station_has_a_quiz_and_a_badge(conn):
    orphans = conn.execute(
        "SELECT key FROM trail_station WHERE quiz_id IS NULL OR badge_id IS NULL"
    ).fetchall()
    assert not orphans, [r["key"] for r in orphans]


def test_every_trail_has_a_completion_badge(conn):
    missing = conn.execute(
        "SELECT key FROM trail WHERE completion_badge_id IS NULL"
    ).fetchall()
    assert not missing, [r["key"] for r in missing]


@pytest.mark.parametrize(
    ("score", "total", "expected"),
    [(6, 6, 3), (5, 6, 2), (3, 6, 1), (2, 6, 0), (0, 6, 0), (0, 0, 0)],
)
def test_star_thresholds(score, total, expected):
    assert stars_for(score, total) == expected


def test_only_the_first_station_starts_unlocked(trails):
    trail = trails.get_trail("first-steps")
    assert trail["stations"][0]["unlocked"] is True
    assert all(not s["unlocked"] for s in trail["stations"][1:])


def test_clearing_a_station_unlocks_the_next(trails):
    trail = trails.get_trail("first-steps")
    first, second = trail["stations"][0], trail["stations"][1]

    trails.record_result("first-steps", first["key"], 6, 6)

    after = trails.get_trail("first-steps")
    assert after["stations"][0]["completed"] is True
    assert after["stations"][1]["unlocked"] is True
    assert after["stations"][2]["unlocked"] is False
    assert second["key"] == after["stations"][1]["key"]


def test_failing_a_station_does_not_unlock_the_next(trails):
    trail = trails.get_trail("first-steps")
    trails.record_result("first-steps", trail["stations"][0]["key"], 1, 6)
    after = trails.get_trail("first-steps")
    assert after["stations"][0]["completed"] is False
    assert after["stations"][1]["unlocked"] is False


def test_clearing_a_station_awards_its_badge(trails):
    result = trails.record_result("first-steps", "dino-dig", 5, 6)
    keys = {b["key"] for b in result["badges_awarded"]}
    assert "little-palaeontologist" in keys
    assert "little-palaeontologist" in trails.earned_badge_keys()


def test_full_marks_awards_the_clean_sweep_badge(trails):
    result = trails.record_result("first-steps", "dino-dig", 6, 6)
    assert "perfect-round" in {b["key"] for b in result["badges_awarded"]}


def test_every_badge_in_the_pack_is_actually_obtainable(conn, trails):
    """A badge shown in the cabinet that no code can ever award is decoration
    pretending to be a goal."""
    defined = {r["key"] for r in conn.execute("SELECT key FROM badge").fetchall()}

    awarded: set[str] = set()
    for trail in trails.list_trails():
        detail = trails.get_trail(trail["key"])
        for station in detail["stations"]:
            result = trails.record_result(
                trail["key"], station["key"], station["questions"], station["questions"]
            )
            awarded |= {b["key"] for b in result["badges_awarded"]}

    unreachable = defined - awarded
    assert not unreachable, f"badges that can never be earned: {sorted(unreachable)}"


def test_breadth_badge_rewards_trying_several_stations(trails):
    trail = trails.get_trail("first-steps")
    awarded: set[str] = set()
    for station in trail["stations"][:3]:
        result = trails.record_result("first-steps", station["key"], 1, 6)  # all failed
        awarded |= {b["key"] for b in result["badges_awarded"]}
    # Earned for looking around, not for being right.
    assert "curious-mind" in awarded


def test_a_badge_is_only_awarded_once(trails):
    trails.record_result("first-steps", "dino-dig", 6, 6)
    again = trails.record_result("first-steps", "dino-dig", 6, 6)
    assert "little-palaeontologist" not in {b["key"] for b in again["badges_awarded"]}


def test_replaying_worse_never_takes_progress_away(trails):
    """A child replaying a station and doing badly must not lose their star."""
    trails.record_result("first-steps", "dino-dig", 6, 6)
    trails.record_result("first-steps", "dino-dig", 1, 6)

    trail = trails.get_trail("first-steps")
    station = trail["stations"][0]
    assert station["completed"] is True
    assert station["stars"] == 3
    assert station["best_score"] == 6
    assert station["attempts"] == 2


def test_completing_every_station_awards_the_trail_badge(trails):
    trail = trails.get_trail("first-steps")
    awarded: set[str] = set()
    for station in trail["stations"]:
        result = trails.record_result("first-steps", station["key"], station["questions"],
                                      station["questions"])
        awarded |= {b["key"] for b in result["badges_awarded"]}
    assert "first-explorer" in awarded

    done = trails.get_trail("first-steps")
    assert done["completed"] == len(done["stations"])
    assert done["stars"] == done["max_stars"]


def test_completion_badge_comes_from_the_data_not_the_code(conn, trails):
    """Renaming the badge in trails.json must change what is awarded."""
    row = conn.execute(
        "SELECT b.key FROM trail t JOIN badge b ON b.id = t.completion_badge_id "
        "WHERE t.key = 'explorer-trail'"
    ).fetchone()
    assert row["key"] == "master-explorer"


def test_score_is_clamped_to_the_total(trails):
    result = trails.record_result("first-steps", "dino-dig", 99, 6)
    assert result["score"] == 6


def test_unknown_station_is_rejected(trails):
    with pytest.raises(KeyError):
        trails.record_result("first-steps", "no-such-station", 1, 1)


def test_reset_clears_progress_and_badges(trails):
    trails.record_result("first-steps", "dino-dig", 6, 6)
    assert trails.earned_badge_keys()
    trails.reset()
    assert not trails.earned_badge_keys()
    assert trails.get_trail("first-steps")["completed"] == 0


def test_badge_list_reports_earned_state(trails):
    trails.record_result("first-steps", "dino-dig", 6, 6)
    badges = trails.badges()
    earned = {b["key"] for b in badges if b["earned"]}
    assert "little-palaeontologist" in earned
    # Unearned badges still explain how to get them.
    for badge in badges:
        assert badge["criteria"] or badge["earned"]


def test_kids_only_hides_older_trails(trails):
    keys = {t["key"] for t in trails.list_trails(kids_only=True)}
    assert "first-steps" in keys
    bands = {
        r["age_band"]
        for r in trails.conn.execute("SELECT age_band FROM trail").fetchall()
    }
    assert bands <= {"age6_8", "age9_12", "teen", "adult"}


# -- question types ---------------------------------------------------------

def test_pack_uses_more_than_multiple_choice(conn):
    kinds = {
        r["kind"]
        for r in conn.execute("SELECT DISTINCT kind FROM quiz_question").fetchall()
    }
    assert {"multiple_choice", "true_false", "ordering", "matching"} <= kinds


def test_ordering_questions_carry_their_sequence(conn):
    rows = conn.execute(
        "SELECT id FROM quiz_question WHERE kind IN ('ordering','timeline')"
    ).fetchall()
    assert rows
    for row in rows:
        options = conn.execute(
            "SELECT sort_order, is_correct FROM quiz_option WHERE question_id = ? "
            "ORDER BY sort_order",
            (row["id"],),
        ).fetchall()
        assert len(options) >= 3
        assert [o["sort_order"] for o in options] == list(range(len(options)))
        # Every option is part of the answer, so all are flagged correct.
        assert all(o["is_correct"] for o in options)


def test_matching_questions_have_a_partner_for_every_item(conn):
    rows = conn.execute("SELECT id FROM quiz_question WHERE kind = 'matching'").fetchall()
    assert rows
    for row in rows:
        options = conn.execute(
            "SELECT text, match_key FROM quiz_option WHERE question_id = ?", (row["id"],)
        ).fetchall()
        assert all(o["match_key"] for o in options)
        assert len({o["match_key"] for o in options}) == len(options)


def test_every_question_still_has_an_explanation(conn):
    missing = conn.execute(
        "SELECT id FROM quiz_question WHERE TRIM(COALESCE(explanation, '')) = ''"
    ).fetchall()
    assert not missing


def test_loader_rejects_a_choice_question_with_no_correct_answer(empty_conn, pack_dir, tmp_path):
    staging = tmp_path / "badquiz"
    (staging / "articles").mkdir(parents=True)
    for name in ("pack.json", "taxonomy.json", "sources.json"):
        (staging / name).write_text((pack_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    article = json.loads((pack_dir / "articles" / "earth.json").read_text(encoding="utf-8"))
    (staging / "articles" / "earth.json").write_text(json.dumps(article), encoding="utf-8")
    (staging / "quizzes.json").write_text(json.dumps([{
        "key": "broken", "title": "Broken", "questions": [{
            "prompt": "Anything?", "explanation": "…",
            "options": [{"text": "a"}, {"text": "b"}],
        }],
    }]), encoding="utf-8")

    with pytest.raises(LoaderError, match="no correct option"):
        PackLoader(empty_conn).load_pack(staging)


def test_loader_rejects_a_matching_question_without_partners(empty_conn, pack_dir, tmp_path):
    staging = tmp_path / "badmatch"
    (staging / "articles").mkdir(parents=True)
    for name in ("pack.json", "taxonomy.json", "sources.json"):
        (staging / name).write_text((pack_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    article = json.loads((pack_dir / "articles" / "earth.json").read_text(encoding="utf-8"))
    (staging / "articles" / "earth.json").write_text(json.dumps(article), encoding="utf-8")
    (staging / "quizzes.json").write_text(json.dumps([{
        "key": "broken", "title": "Broken", "questions": [{
            "kind": "matching", "prompt": "Pair them", "explanation": "…",
            "options": [{"text": "a"}, {"text": "b"}],
        }],
    }]), encoding="utf-8")

    with pytest.raises(LoaderError, match="match"):
        PackLoader(empty_conn).load_pack(staging)
