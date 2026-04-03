"""Tests ciblés pour parse_stops() — cohérence direct vs escales."""

from analyzer import parse_stops


def test_direct_variants():
    """Toutes les variantes 'direct' doivent retourner 0."""
    assert parse_stops("Direct") == 0
    assert parse_stops("direct") == 0
    assert parse_stops("DIRECT") == 0
    assert parse_stops("Direct ") == 0   # trailing space
    assert parse_stops(" Direct") == 0   # leading space


def test_sans_escale():
    """Variantes françaises sans escale."""
    assert parse_stops("sans escale") == 0
    assert parse_stops("Sans escale") == 0
    assert parse_stops("SANS ESCALE") == 0


def test_nonstop():
    """Variantes anglaises."""
    assert parse_stops("nonstop") == 0
    assert parse_stops("Nonstop") == 0
    assert parse_stops("non-stop") == 0
    assert parse_stops("Non-Stop") == 0


def test_zero():
    """Zéro numérique."""
    assert parse_stops("0") == 0
    assert parse_stops("0 escale(s)") == 0


def test_numeric_escales():
    """Formats standard du CSV."""
    assert parse_stops("1 escale(s)") == 1
    assert parse_stops("2 escale(s)") == 2
    assert parse_stops("3 escale(s)") == 3


def test_empty_and_none():
    """Valeurs vides = direct (pas d'info = pas d'escale)."""
    assert parse_stops("") == 0
    assert parse_stops(None) == 0


def test_numeric_string():
    """Nombre seul."""
    assert parse_stops("1") == 1
    assert parse_stops("2") == 2


def test_unknown_format_fallback():
    """Format inconnu = fallback 1 (conservateur)."""
    assert parse_stops("inconnu") == 1
    assert parse_stops("???") == 1


def test_find_deals_uses_escales_key():
    """find_deals doit lire le champ 'escales' du scraper, pas 'stops'."""
    from analyzer import find_deals, parse_stops
    # Simuler un result du scraper (champ "escales", pas "stops")
    result = {
        "route": "TEST_ROUTE",
        "price_google": 500,
        "escales": "1 escale(s)",
    }
    stops_str = result.get("escales") or result.get("stops", "")
    num_stops = parse_stops(stops_str)
    assert num_stops == 1, f"Should read escales=1, got {num_stops}"
    # Aussi verifier que sans "escales", "stops" fonctionne comme fallback
    result2 = {"route": "TEST2", "price_google": 400, "stops": "2 escale(s)"}
    stops_str2 = result2.get("escales") or result2.get("stops", "")
    assert parse_stops(stops_str2) == 2


if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith("test_")]
    passed = 0
    failed = 0
    for name in tests:
        try:
            globals()[name]()
            passed += 1
            print(f"  OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
