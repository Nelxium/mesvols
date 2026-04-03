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
    """find_deals doit lire le champ 'escales' du scraper, pas 'stops'.
    On appelle find_deals() avec un result qui a 'escales' mais pas 'stops'.
    Si find_deals regressait a lire 'stops', le vol serait classe Direct a tort."""
    import os
    import csv
    import tempfile
    import analyzer as _ana

    # Creer un CSV historique minimal pour que find_deals ait assez de datapoints
    tmp = tempfile.mktemp(suffix=".csv")
    fields = ["date", "route", "origin", "destination", "price_google",
              "price_skyscanner", "airline", "escales", "depart", "retour", "booking_url"]
    hist_rows = [
        {"date": f"2026-03-{20+i} 12:00Z", "route": "Montreal -> Paris", "origin": "YUL",
         "destination": "CDG", "price_google": str(800 + i * 10), "price_skyscanner": "",
         "airline": "Air Canada", "escales": "1 escale(s)", "depart": "2026-06-01",
         "retour": "2026-06-08", "booking_url": ""}
        for i in range(5)
    ]
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in hist_rows:
            w.writerow(r)

    # Monkey-patch le CSV path
    original = _ana.CSV_FILE
    _ana.CSV_FILE = tmp
    try:
        # Result du scraper : "escales" = "2 escale(s)", pas de champ "stops"
        result = {
            "route": "Montreal -> Paris",
            "price_google": 500,
            "escales": "2 escale(s)",
            "origin": "YUL",
            "destination": "CDG",
            "depart": "2026-06-01",
            "retour": "2026-06-08",
            "airline": "Air Canada",
        }
        deals = _ana.find_deals([result])
        # Le vol est un deal (500 vs avg ~830)
        assert len(deals) >= 1, f"Should detect a deal, got {len(deals)}"
        deal = deals[0]
        # Le point cle : num_stops doit etre 2, pas 0 (Direct)
        assert deal.get("num_stops") == 2, (
            f"num_stops should be 2 from 'escales', got {deal.get('num_stops')}. "
            f"If 0, find_deals is still reading 'stops' instead of 'escales'."
        )
    finally:
        _ana.CSV_FILE = original
        os.unlink(tmp)


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
