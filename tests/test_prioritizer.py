import pytest
from src.tasks.prioritizer import Prioritizer, TaskScore


@pytest.fixture
def p():
    return Prioritizer()


def test_urgent_important_gets_high_score(p):
    score = p.score(
        "Fix production outage",
        "Server is down, users cannot access the site",
        due_in_hours=2,
    )
    assert score.urgency > 0.8
    assert score.importance > 0.7
    assert score.quadrant == "do_now"


def test_not_urgent_not_important_gets_low(p):
    score = p.score(
        "Reorganize browser bookmarks",
        "Sort bookmarks into folders someday",
        due_in_hours=None,
    )
    assert score.urgency < 0.4
    assert score.quadrant == "eliminate"


def test_due_soon_boosts_urgency(p):
    soon = p.score("Meeting prep", "", due_in_hours=1)
    later = p.score("Meeting prep", "", due_in_hours=72)
    assert soon.urgency > later.urgency


def test_overdue_is_max_urgency(p):
    score = p.score("Overdue report", "", due_in_hours=-1)
    assert score.urgency == 1.0


def test_score_list_sorted_by_priority(p):
    tasks = [
        {"title": "Archive emails", "description": "Low priority task"},
        {"title": "Fix production outage", "description": "Critical", "due_in_hours": 1},
        {"title": "Prepare board report", "description": "For board meeting"},
    ]
    scored = p.score_list(tasks)
    assert scored[0]["title"] == "Fix production outage"


def test_quadrant_schedule(p):
    # Not urgent but important
    score = p.score("Write long-term strategy document", "For board review next quarter")
    assert score.quadrant in ("schedule", "do_now")  # importance keywords present


def test_score_returns_dataclass(p):
    score = p.score("Some task")
    assert isinstance(score, TaskScore)
    assert 0.0 <= score.urgency <= 1.0
    assert 0.0 <= score.importance <= 1.0
    assert 0.0 <= score.priority <= 1.0
    assert score.quadrant in ("do_now", "schedule", "delegate", "eliminate")
