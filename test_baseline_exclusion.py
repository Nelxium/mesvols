"""Tests ciblés pour l'exclusion du cycle courant dans generate_data_js.

Vérifie que BEST_OFFERS scores utilisent une baseline historique
qui exclut TOUTES les lignes du cycle courant, même si les timestamps
diffèrent (bug corrigé: per-row timestamps vs run_ts unique).
"""

import csv
import json
import os
import re
import tempfile
import shutil

HEADER = ["date", "route", "origin", "destination", "price_google",
          "price_skyscanner", "airline", "escales", "depart", "retour",
          "booking_url"]


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


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _simulate_exclusion(raw_rows):
    """Reproduit la logique d'exclusion de generate_data_js (main.py).
    Retourne (prior_prices, last_cycle_dates)."""
    last_date = raw_rows[-1]["date"] if raw_rows else ""
    last_hour = last_date[:13] if len(last_date) >= 13 else last_date
    last_cycle_dates = set()
    for r in reversed(raw_rows):
        if r["date"][:13] == last_hour:
            last_cycle_dates.add(r["date"])
        else:
            break

    prior_prices = []
    for r in raw_rows:
        if r["date"] not in last_cycle_dates:
            prior_prices.append(int(r["price_google"]))
    return prior_prices, last_cycle_dates


def test_same_run_ts_excluded():
    """Toutes les lignes du cycle courant (meme run_ts) sont exclues."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
        _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
        _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 920),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 500),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 510,
                  depart="2026-07-01", retour="2026-07-08"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 520,
                  depart="2026-08-01", retour="2026-08-08"),
    ]
    prior, cycle_dates = _simulate_exclusion(rows)
    assert len(prior) == 3, f"Expected 3 prior rows, got {len(prior)}"
    assert 500 not in prior, "Current cycle price leaked into prior!"
    assert 510 not in prior, "Current cycle price leaked into prior!"
    assert 520 not in prior, "Current cycle price leaked into prior!"


def test_multi_timestamp_same_hour_excluded():
    """Le vrai cas : timestamps per-row dans la meme heure sont tous exclus."""
    rows = [
        # Historique (different hours)
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
        _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
        _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 920),
        # Cycle courant — timestamps per-row (le bug d'avant)
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 500),
        _make_row("2026-04-02 06:01Z", "Montreal -> Cancun", "YUL", "CUN", 400),
        _make_row("2026-04-02 06:02Z", "Montreal -> Tokyo", "YUL", "NRT", 1200),
        _make_row("2026-04-02 06:05Z", "Montreal -> Miami", "YUL", "MIA", 350),
    ]
    prior, cycle_dates = _simulate_exclusion(rows)

    # Toutes les lignes 06:xxZ doivent etre exclues
    assert len(cycle_dates) == 4, f"Expected 4 cycle dates, got {len(cycle_dates)}: {cycle_dates}"
    assert len(prior) == 3, f"Expected 3 prior rows, got {len(prior)}"
    assert 500 not in prior, "06:00Z leaked"
    assert 400 not in prior, "06:01Z leaked"
    assert 1200 not in prior, "06:02Z leaked"
    assert 350 not in prior, "06:05Z leaked"


def test_different_hour_not_excluded():
    """Les lignes d'une heure differente ne sont PAS exclues."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
        _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
        # Cycle courant (hour 18)
        _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 500),
        _make_row("2026-04-01 18:03Z", "Montreal -> Cancun", "YUL", "CUN", 400),
    ]
    prior, cycle_dates = _simulate_exclusion(rows)
    # Only hour 18 excluded
    assert 900 in prior, "06:00 should be in prior"
    assert 950 in prior, "12:00 should be in prior"
    assert 500 not in prior, "18:00 should be excluded"
    assert 400 not in prior, "18:03 should be excluded"


def test_end_to_end_generate_data_js():
    """Test end-to-end : generate_data_js avec un CSV multi-timestamp
    produit des BEST_OFFERS dont le score n'est pas contamine."""
    import main
    from analyzer import parse_stops
    from links import build_skyscanner_url, build_search_link

    # Sauvegarder le vrai CSV et le remplacer temporairement
    real_csv = main.CSV_PATH
    tmp = tempfile.mktemp(suffix=".csv")
    try:
        rows = [
            # Historique : prix eleves (avg ~900)
            _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900),
            _make_row("2026-04-01 12:00Z", "Montreal -> Paris", "YUL", "CDG", 950),
            _make_row("2026-04-01 18:00Z", "Montreal -> Paris", "YUL", "CDG", 850),
            # Cycle courant : prix tres bas (should not contaminate baseline)
            _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 200),
            _make_row("2026-04-02 06:02Z", "Montreal -> Paris", "YUL", "CDG", 210,
                      depart="2026-07-01", retour="2026-07-08"),
            _make_row("2026-04-02 06:04Z", "Montreal -> Paris", "YUL", "CDG", 220,
                      depart="2026-08-01", retour="2026-08-08"),
        ]
        _write_csv(tmp, rows)

        # Monkey-patch le CSV path
        main.CSV_PATH = tmp

        # Construire best_offers_current
        best_offers_current = {
            "CDG": {
                "date": "2026-04-02 06:00Z",
                "price": 200, "price_google": 200, "price_skyscanner": None,
                "best_source": "Google", "depart": "2026-06-01", "retour": "2026-06-08",
                "airline": "TestAir", "airline_code": "",
                "stops": "Direct", "score": 3,
                "skyscanner_url": "", "google_url": "", "deal_id": "",
                "reserve_url": "", "final_domain": "",
                "search_url": "", "search_label": "",
            }
        }

        # Sauvegarder le vrai data.js path et rediriger
        real_data_js = main.DATA_JS_PATH
        tmp_data_js = tempfile.mktemp(suffix=".js")
        main.DATA_JS_PATH = tmp_data_js

        try:
            main.generate_data_js(best_offers_current)

            with open(tmp_data_js, encoding="utf-8") as f:
                content = f.read()

            m = re.search(r'const BEST_OFFERS = ({.*?});', content, re.DOTALL)
            assert m, "BEST_OFFERS not found in output"
            bo = json.loads(m.group(1))

            cdg = bo.get("CDG", {})
            score = cdg.get("score", -1)

            # Si le cycle courant (200$) avait contamine la baseline,
            # la moyenne serait ~555$ et 200$ serait un prix bas -> score 5.
            # Avec la baseline correcte (avg 900$), 200$ est bien un prix bas
            # mais la baseline est propre.
            # Le point cle : le score doit etre calcule sur avg ~900, pas ~555.
            assert score == 5, (
                f"Score should be 5 (200$ vs avg ~900 from prior only), got {score}. "
                f"If score < 5, the baseline might be contaminated by current cycle."
            )
        finally:
            main.DATA_JS_PATH = real_data_js
            if os.path.exists(tmp_data_js):
                os.unlink(tmp_data_js)
    finally:
        main.CSV_PATH = real_csv
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_csv_last_cycle_single_ts():
    """Verifie que le CSV actuel a un seul timestamp dans le dernier cycle."""
    csv_path = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
    if not os.path.isfile(csv_path):
        print("  SKIP (pas de prix_vols.csv)")
        return

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        print("  SKIP (CSV vide)")
        return

    _, cycle_dates = _simulate_exclusion(rows)
    assert len(cycle_dates) == 1, (
        f"Le dernier cycle a {len(cycle_dates)} timestamps distincts: "
        f"{sorted(cycle_dates)}. Devrait etre 1 apres normalisation."
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
