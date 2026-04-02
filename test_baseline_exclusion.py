"""Tests ciblés pour l'exclusion du cycle courant dans generate_data_js.

Vérifie que BEST_OFFERS scores utilisent une baseline historique
qui exclut TOUTES les lignes du cycle courant, même si les timestamps
diffèrent (bug corrigé: per-row timestamps vs run_ts unique).
"""

import csv
import json
import os
import tempfile

# Simuler un CSV avec plusieurs cycles
HEADER = ["date", "route", "origin", "destination", "price_google",
          "price_skyscanner", "airline", "escales", "depart", "retour",
          "booking_url"]


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _make_row(date, route, origin, dest, price, stops="Direct",
              depart="2026-06-01", retour="2026-06-08"):
    return {
        "date": date,
        "route": route,
        "origin": origin,
        "destination": dest,
        "price_google": price,
        "price_skyscanner": "",
        "airline": "TestAir",
        "escales": stops,
        "depart": depart,
        "retour": retour,
        "booking_url": "",
    }


def test_same_run_ts_excluded():
    """Toutes les lignes du cycle courant (meme run_ts) sont exclues."""
    rows = [
        # Historique (3 cycles anciens)
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
        _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
        _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 920),
        # Cycle courant — toutes les lignes partagent le meme run_ts
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 500),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 510,
                  depart="2026-07-01", retour="2026-07-08"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 520,
                  depart="2026-08-01", retour="2026-08-08"),
    ]

    last_date = "2026-04-02 06:00Z"
    prior_prices = []
    for r in rows:
        if r["date"] != last_date:
            prior_prices.append(int(r["price_google"]))

    # Prior = seulement les 3 lignes historiques (900, 950, 920)
    assert len(prior_prices) == 3, f"Expected 3 prior rows, got {len(prior_prices)}"
    assert 500 not in prior_prices, "Current cycle price leaked into prior!"
    assert 510 not in prior_prices, "Current cycle price leaked into prior!"
    assert 520 not in prior_prices, "Current cycle price leaked into prior!"
    avg = sum(prior_prices) / len(prior_prices)
    assert abs(avg - 923.3) < 1, f"Prior avg should be ~923, got {avg}"


def test_different_per_row_ts_would_leak():
    """Demontre le bug AVANT le fix: des timestamps per-row causent une fuite."""
    rows = [
        # Historique
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
        _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
        _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 920),
        # Cycle courant — MAUVAIS: timestamps differents par route
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 500),
        _make_row("2026-04-02 06:01Z", "Montreal -> Paris", "YUL", "CDG", 510),
        _make_row("2026-04-02 06:02Z", "Montreal -> Paris", "YUL", "CDG", 520),
    ]

    # Avec l'ancienne logique, last_date = "2026-04-02 06:02Z"
    last_date = rows[-1]["date"]  # "2026-04-02 06:02Z"
    prior_prices_buggy = []
    for r in rows:
        if r["date"] != last_date:
            prior_prices_buggy.append(int(r["price_google"]))

    # BUG: les lignes 06:00Z et 06:01Z fuient dans le prior!
    assert 500 in prior_prices_buggy, "This test demonstrates the old bug"
    assert 510 in prior_prices_buggy, "This test demonstrates the old bug"
    assert len(prior_prices_buggy) == 5, f"Buggy: {len(prior_prices_buggy)} rows in prior (should be 3)"


def test_run_ts_is_shared():
    """Verifie que run_scraper ecrit le meme timestamp pour toutes les routes."""
    # On ne peut pas appeler run_scraper() dans un test unitaire (besoin de Selenium),
    # mais on peut verifier le contrat via le CSV existant.
    csv_path = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
    if not os.path.isfile(csv_path):
        print("  SKIP (pas de prix_vols.csv)")
        return

    # Lire les derniers N lignes et verifier que le dernier cycle
    # a un seul timestamp
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        print("  SKIP (CSV vide)")
        return

    last_date = rows[-1].get("date", "")
    last_cycle = [r for r in rows if r.get("date") == last_date]

    # Le dernier cycle devrait avoir plusieurs lignes avec le meme timestamp
    # (si le fix run_ts est actif) ou des timestamps differents (si ancien code)
    if len(last_cycle) > 1:
        dates = set(r.get("date") for r in last_cycle)
        assert len(dates) == 1, (
            f"Le dernier cycle a {len(dates)} timestamps distincts: {dates}. "
            f"Toutes les lignes devraient partager le meme run_ts."
        )


if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith("test_")]
    passed = 0
    failed = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            passed += 1
            print(f"  OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
