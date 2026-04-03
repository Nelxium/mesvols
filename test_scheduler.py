"""Tests pour scheduler.py — logique pure de selection dry-run."""

from datetime import datetime, timezone, timedelta

from scheduler import (
    select_routes, _backoff_multiplier, _get_route_config,
    load_state, apply_dry_run,
    MAX_BATCH_SIZE, DEFAULT_PRIORITY, DEFAULT_INTERVAL_MIN,
)

# Helpers
NOW = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)

SAMPLE_ROUTES = [
    ("YUL", "CDG", "Montreal -> Paris"),
    ("YUL", "CUN", "Montreal -> Cancun"),
    ("YUL", "JFK", "Montreal -> New York"),
    ("YUL", "NRT", "Montreal -> Tokyo Narita"),
    ("YUL", "HNL", "Montreal -> Hawai"),
]


def _iso(dt):
    return dt.isoformat()


# --- Backoff ---

def test_backoff_zero_failures():
    assert _backoff_multiplier(0) == 1


def test_backoff_one_failure():
    assert _backoff_multiplier(1) == 2


def test_backoff_three_failures():
    assert _backoff_multiplier(3) == 8


def test_backoff_capped():
    """Le backoff plafonne a MAX_BACKOFF_MULT (8)."""
    assert _backoff_multiplier(10) == 8
    assert _backoff_multiplier(100) == 8


# --- Route config ---

def test_route_config_known():
    prio, interval = _get_route_config("YUL", "CDG")
    assert prio == 1
    assert interval == 360


def test_route_config_unknown():
    """Route inconnue → defaults."""
    prio, interval = _get_route_config("YYZ", "LAX")
    assert prio == DEFAULT_PRIORITY
    assert interval == DEFAULT_INTERVAL_MIN


# --- Selection : etat vide (premiere execution) ---

def test_empty_state_all_eligible():
    """Sans etat, toutes les routes sont eligibles."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW)
    eligible = [c for c in result if c["eligible"]]
    assert len(eligible) == len(SAMPLE_ROUTES)


def test_empty_state_batch_size_respected():
    """Meme si toutes sont eligibles, le batch limite la selection."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW, batch_size=2)
    selected = [c for c in result if c["selected"]]
    assert len(selected) == 2


def test_empty_state_priority_order():
    """A staleness egale (toutes jamais lancees), la priorite decide."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW, batch_size=2)
    selected = [c for c in result if c["selected"]]
    # CDG prio=1 et CUN/JFK prio=2 (CUN avant JFK alphabetiquement)
    assert selected[0]["key"] == "YUL-CDG"
    assert selected[1]["key"] in ("YUL-CUN", "YUL-JFK")


def test_empty_state_deterministic():
    """Deux appels identiques donnent le meme resultat."""
    r1 = select_routes(SAMPLE_ROUTES, {}, NOW)
    r2 = select_routes(SAMPLE_ROUTES, {}, NOW)
    assert [c["key"] for c in r1] == [c["key"] for c in r2]
    assert [c["selected"] for c in r1] == [c["selected"] for c in r2]


# --- Selection : routes recentes vs stales ---

def test_stale_route_favored():
    """Une route stale est selectionnee avant une route recente."""
    recent = NOW - timedelta(minutes=30)
    old = NOW - timedelta(hours=24)
    # Toutes les routes ont un etat recent sauf NRT qui est stale
    state = {}
    for o, d, _ in SAMPLE_ROUTES:
        key = f"{o}-{d}"
        state[key] = {"last_attempt": _iso(recent), "last_success": _iso(recent),
                       "consecutive_failures": 0}
    # NRT est la seule route stale (24h vs interval 12h)
    state["YUL-NRT"]["last_attempt"] = _iso(old)
    state["YUL-NRT"]["last_success"] = _iso(old)

    result = select_routes(SAMPLE_ROUTES, state, NOW, batch_size=1)
    selected = [c for c in result if c["selected"]]
    assert len(selected) == 1
    assert selected[0]["key"] == "YUL-NRT"


def test_recently_run_not_eligible():
    """Une route lancee il y a 1h avec interval 6h n'est pas eligible."""
    recent = NOW - timedelta(hours=1)
    state = {
        "YUL-CDG": {"last_attempt": _iso(recent), "last_success": _iso(recent),
                     "consecutive_failures": 0},
    }
    routes = [("YUL", "CDG", "Montreal -> Paris")]
    result = select_routes(routes, state, NOW)
    assert not result[0]["eligible"]
    assert not result[0]["selected"]


# --- Backoff apres echec ---

def test_backoff_delays_eligibility():
    """Apres 2 echecs, l'intervalle est multiplie par 4."""
    # CDG interval=360min, 2 failures → effective=1440min (24h)
    # last_attempt il y a 12h → pas encore eligible
    twelve_hours_ago = NOW - timedelta(hours=12)
    state = {
        "YUL-CDG": {"last_attempt": _iso(twelve_hours_ago),
                     "last_success": None,
                     "consecutive_failures": 2},
    }
    routes = [("YUL", "CDG", "Montreal -> Paris")]
    result = select_routes(routes, state, NOW)
    assert result[0]["backoff_mult"] == 4
    assert not result[0]["eligible"]


def test_backoff_recovery():
    """Apres suffisamment de temps, une route en backoff redevient eligible."""
    # CDG interval=360min, 2 failures → effective=1440min (24h)
    # last_attempt il y a 25h → eligible
    long_ago = NOW - timedelta(hours=25)
    state = {
        "YUL-CDG": {"last_attempt": _iso(long_ago),
                     "last_success": None,
                     "consecutive_failures": 2},
    }
    routes = [("YUL", "CDG", "Montreal -> Paris")]
    result = select_routes(routes, state, NOW)
    assert result[0]["eligible"]
    assert result[0]["selected"]


# --- apply_dry_run ---

def test_apply_dry_run_updates_state():
    """apply_dry_run met a jour last_attempt/last_success et reset les failures."""
    # CDG interval=360min, 0 failures → eligible si last_attempt > 6h ago
    long_ago = NOW - timedelta(hours=12)
    state = {
        "YUL-CDG": {"last_attempt": _iso(long_ago),
                     "last_success": _iso(long_ago),
                     "consecutive_failures": 0},
    }
    routes = [("YUL", "CDG", "Montreal -> Paris")]
    result = select_routes(routes, state, NOW)
    assert result[0]["selected"], "CDG should be eligible and selected"
    new_state = apply_dry_run(state, result, NOW)
    assert new_state["YUL-CDG"]["last_attempt"] == NOW.isoformat()
    assert new_state["YUL-CDG"]["last_success"] == NOW.isoformat()
    assert new_state["YUL-CDG"]["consecutive_failures"] == 0


def test_apply_dry_run_creates_new_entry():
    """apply_dry_run cree une entree pour une route sans etat."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW, batch_size=1)
    new_state = apply_dry_run({}, result, NOW)
    selected_key = [c["key"] for c in result if c["selected"]][0]
    assert selected_key in new_state
    assert new_state[selected_key]["consecutive_failures"] == 0


# --- load_state ---

def test_load_state_missing_file(tmp_path):
    """Fichier absent → dict vide."""
    s = load_state(str(tmp_path / "nonexistent.json"))
    assert s == {}


def test_load_state_invalid_json(tmp_path):
    """JSON invalide → dict vide."""
    p = tmp_path / "bad.json"
    p.write_text("not json")
    s = load_state(str(p))
    assert s == {}


# --- Chaque route a une explication ---

def test_all_routes_have_reason():
    """Chaque route retournee a une raison non vide."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW, batch_size=2)
    for c in result:
        assert c["reason"], f"{c['key']} has empty reason"


# --- Batch size 0 ---

def test_batch_size_zero():
    """Batch size 0 → aucune selection."""
    result = select_routes(SAMPLE_ROUTES, {}, NOW, batch_size=0)
    selected = [c for c in result if c["selected"]]
    assert len(selected) == 0


if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith("test_")]
    passed = failed = 0
    for name in sorted(tests):
        fn = globals()[name]
        try:
            import inspect
            sig = inspect.signature(fn)
            if "tmp_path" in sig.parameters:
                import tempfile, pathlib
                with tempfile.TemporaryDirectory() as td:
                    fn(pathlib.Path(td))
            else:
                fn()
            passed += 1
            print(f"  OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
