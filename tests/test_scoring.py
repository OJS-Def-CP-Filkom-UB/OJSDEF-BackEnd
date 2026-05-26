from app.workers.scoring import _compute_score, _risk_level


def test_perfect_score():
    assert _compute_score(0, 0, 0, 0) == 100.0


def test_one_critical():
    assert _compute_score(1, 0, 0, 0) == 70.0


def test_critical_risk():
    assert _risk_level(20) == "critical"


def test_low_risk():
    assert _risk_level(90) == "low"
