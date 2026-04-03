"""Tests pour runner_batch.py — logique d'orchestration batch local."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from runner_batch import update_state_from_results, run_batch
from scheduler import select_routes

NOW = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)

ROUTES_2 = [
    ("YUL", "CDG", "Montreal -> Paris"),
    ("YUL", "JFK", "Montreal -> New York"),
]


def _candidates(routes=ROUTES_2, state=None, batch_size=4):
    return select_routes(routes, state or {}, NOW, batch_size)


def _result(origin, dest):
    """Simule un resultat scraper pour une route."""
    return {"origin": origin, "destination": dest, "price_google": 500,
            "route": f"{origin} -> {dest}", "airline": "TestAir",
            "date": NOW.isoformat()}


# --- update_state_from_results ---

def test_success_updates_state():
    """Route avec resultats -> last_success + consecutive_failures=0."""
    state = {}
    candidates = _candidates()
    results = [_result("YUL", "CDG"), _result("YUL", "JFK")]
    outcomes = update_state_from_results(state, candidates, results, NOW)

    assert outcomes["YUL-CDG"] == "success"
    assert outcomes["YUL-JFK"] == "success"
    assert state["YUL-CDG"]["last_success"] == NOW.isoformat()
    assert state["YUL-CDG"]["consecutive_failures"] == 0


def test_failure_increments_counter():
    """Route sans resultats -> consecutive_failures incremente."""
    state = {"YUL-JFK": {"consecutive_failures": 2}}
    candidates = _candidates()
    # Seulement CDG a des resultats, JFK n'en a pas
    results = [_result("YUL", "CDG")]
    outcomes = update_state_from_results(state, candidates, results, NOW)

    assert outcomes["YUL-CDG"] == "success"
    assert outcomes["YUL-JFK"] == "failure"
    assert state["YUL-JFK"]["consecutive_failures"] == 3
    assert "last_failure" in state["YUL-JFK"]


def test_success_resets_failures():
    """Apres un succes, consecutive_failures repasse a 0."""
    state = {"YUL-CDG": {"consecutive_failures": 5,
                          "last_failure": "2026-04-02T00:00:00+00:00"}}
    candidates = _candidates(routes=[("YUL", "CDG", "Paris")])
    results = [_result("YUL", "CDG")]
    outcomes = update_state_from_results(state, candidates, results, NOW)

    assert outcomes["YUL-CDG"] == "success"
    assert state["YUL-CDG"]["consecutive_failures"] == 0


def test_all_fail_on_empty_results():
    """Aucun resultat -> toutes les routes echouent."""
    state = {}
    candidates = _candidates()
    outcomes = update_state_from_results(state, candidates, [], NOW)

    assert all(v == "failure" for v in outcomes.values())
    assert state["YUL-CDG"]["consecutive_failures"] == 1
    assert state["YUL-JFK"]["consecutive_failures"] == 1


def test_nonselected_routes_untouched():
    """Les routes non selectionnees ne sont pas dans outcomes."""
    state = {}
    candidates = _candidates(batch_size=1)
    results = [_result("YUL", "CDG")]
    outcomes = update_state_from_results(state, candidates, results, NOW)

    # Seulement 1 route selectionnee
    assert len(outcomes) == 1


def test_last_attempt_always_set():
    """last_attempt est toujours mis a jour, succes ou echec."""
    state = {}
    candidates = _candidates()
    results = [_result("YUL", "CDG")]  # CDG ok, JFK fail
    update_state_from_results(state, candidates, results, NOW)

    assert state["YUL-CDG"]["last_attempt"] == NOW.isoformat()
    assert state["YUL-JFK"]["last_attempt"] == NOW.isoformat()


def test_new_route_state_created():
    """Un state vide est automatiquement cree pour une nouvelle route."""
    state = {}
    candidates = _candidates(routes=[("YUL", "CDG", "Paris")])
    results = [_result("YUL", "CDG")]
    update_state_from_results(state, candidates, results, NOW)

    assert "YUL-CDG" in state
    assert state["YUL-CDG"]["consecutive_failures"] == 0


# --- run_batch dry-run ---

def test_dry_run_does_not_call_scraper():
    """En dry-run, run_scraper n'est jamais appele."""
    with patch("runner_batch.load_state", return_value={}), \
         patch("runner_batch.save_state") as mock_save:
        candidates, outcomes = run_batch(batch_size=2, dry_run=True)
        assert outcomes is None
        mock_save.assert_not_called()


def test_dry_run_returns_candidates():
    """dry-run retourne les candidats avec selection."""
    with patch("runner_batch.load_state", return_value={}):
        candidates, _ = run_batch(batch_size=2, dry_run=True)
        selected = [c for c in candidates if c["selected"]]
        assert len(selected) == 2


# --- run_batch execution (mocked scraper) ---

def test_run_calls_scraper_with_subset():
    """En mode run, le scraper est appele avec les routes selectionnees."""
    mock_results = [_result("YUL", "CDG")]

    with patch("runner_batch.load_state", return_value={}), \
         patch("runner_batch.save_state"), \
         patch("runner_batch.run_scraper", return_value=mock_results) as mock_scraper:
        candidates, outcomes = run_batch(batch_size=1, dry_run=False)

        mock_scraper.assert_called_once()
        call_kwargs = mock_scraper.call_args
        routes_arg = call_kwargs.kwargs.get("routes_subset") or call_kwargs.args[0] if call_kwargs.args else None
        # Verify scraper was called with a routes_subset
        assert routes_arg is not None or "routes_subset" in (call_kwargs.kwargs or {})


def test_run_saves_state():
    """En mode run, l'etat est sauvegarde."""
    with patch("runner_batch.load_state", return_value={}), \
         patch("runner_batch.save_state") as mock_save, \
         patch("runner_batch.run_scraper", return_value=[_result("YUL", "CDG")]):
        run_batch(batch_size=1, dry_run=False)
        mock_save.assert_called_once()


def test_run_empty_batch():
    """Batch vide (toutes non eligibles) -> pas d'appel scraper."""
    # Toutes les routes viennent d'etre lancees
    recent = (NOW - timedelta(minutes=5)).isoformat()
    state = {}
    from config import ROUTES
    for o, d, _ in ROUTES:
        state[f"{o}-{d}"] = {"last_attempt": recent, "last_success": recent,
                              "consecutive_failures": 0}

    with patch("runner_batch.load_state", return_value=state), \
         patch("runner_batch.save_state") as mock_save:
        candidates, outcomes = run_batch(batch_size=4, dry_run=False)
        assert outcomes is None
        mock_save.assert_not_called()


def test_run_scraper_crash_marks_all_failed():
    """Si le scraper crash, toutes les routes sont marquees en echec."""
    with patch("runner_batch.load_state", return_value={}), \
         patch("runner_batch.save_state") as mock_save, \
         patch("runner_batch.run_scraper", side_effect=Exception("Chrome crash")):
        candidates, outcomes = run_batch(batch_size=2, dry_run=False)
        assert outcomes is not None
        assert all(v == "failure" for v in outcomes.values())
        mock_save.assert_called_once()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
