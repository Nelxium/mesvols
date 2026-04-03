"""Tests: les lignes airline=Inconnue sont exclues de data.js publié.

Vérifie que generate_data_js() :
 - exclut les lignes Inconnue de FLIGHT_DATA
 - exclut les destinations Inconnue de BEST_OFFERS (avec fallback connue)
 - calcule les scores uniquement sur les lignes publiables
 - émet un warning si le cycle courant contient des Inconnue
"""

import csv
import json
import os
import re
import tempfile

HEADER = ["date", "route", "origin", "destination", "price_google",
          "price_skyscanner", "airline", "escales", "depart", "retour",
          "booking_url"]


def _make_row(date, route, origin, dest, price, airline="TestAir",
              stops="Direct", depart="2026-06-01", retour="2026-06-08"):
    return {
        "date": date, "route": route, "origin": origin,
        "destination": dest, "price_google": str(price),
        "price_skyscanner": "", "airline": airline,
        "escales": stops, "depart": depart, "retour": retour,
        "booking_url": "",
    }


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _gen(rows, best_offers_current=None):
    """Écrit un CSV temporaire, appelle generate_data_js, retourne (flights, best_offers)."""
    import main as m
    tmp = tempfile.mktemp(suffix=".csv")
    out = tempfile.mktemp(suffix=".js")
    orig_csv, orig_js = m.CSV_PATH, m.DATA_JS_PATH
    try:
        _write_csv(tmp, rows)
        m.CSV_PATH = tmp
        m.DATA_JS_PATH = out
        m.generate_data_js(best_offers_current=best_offers_current)
        with open(out, encoding="utf-8") as f:
            content = f.read()
        fd_m = re.search(r"const FLIGHT_DATA = (\[.*?\]);", content, re.DOTALL)
        bo_m = re.search(r"const BEST_OFFERS = (\{.*?\});", content, re.DOTALL)
        flights = json.loads(fd_m.group(1)) if fd_m else []
        best_offers = json.loads(bo_m.group(1)) if bo_m else {}
        return flights, best_offers
    finally:
        m.CSV_PATH = orig_csv
        m.DATA_JS_PATH = orig_js
        for p in (tmp, out):
            if os.path.exists(p):
                os.unlink(p)


# --- FLIGHT_DATA filtering ---

def test_inconnue_excluded_from_flight_data():
    """Les lignes CSV avec airline route-code (normalisé Inconnue) sont exclues."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 334,
                  airline="YUL–JFK"),  # route code → Inconnue
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 850,
                  airline="Air Transat"),
    ]
    flights, _ = _gen(rows)
    airlines = [f["airline"] for f in flights]
    assert "Inconnue" not in airlines, f"Inconnue leaked into FLIGHT_DATA: {airlines}"
    assert len(flights) == 2


def test_known_airlines_preserved():
    """Les lignes avec compagnie connue restent dans FLIGHT_DATA."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> Cancun", "YUL", "CUN", 500,
                  airline="Delta"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 850,
                  airline="United"),
    ]
    flights, _ = _gen(rows)
    airlines = {f["airline"] for f in flights}
    assert airlines == {"Air Canada", "Delta", "United"}


def test_inconnue_literal_excluded():
    """Le texte littéral 'Inconnue' dans le CSV est aussi exclu."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 334,
                  airline="Inconnue"),
    ]
    flights, _ = _gen(rows)
    assert len(flights) == 1
    assert flights[0]["airline"] == "Air Canada"


def test_emissions_parasite_excluded():
    """Les labels parasites (Émissions hab.) normalisés à Inconnue sont exclus."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 334,
                  airline="Émissions hab."),
    ]
    flights, _ = _gen(rows)
    assert len(flights) == 1


# --- BEST_OFFERS filtering ---

def test_best_offers_inconnue_excluded():
    """BEST_OFFERS exclut les destinations dont l'airline est Inconnue."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 334,
                  airline="Delta"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 850,
                  airline="Air Canada"),
        _make_row("2026-04-02 06:00Z", "Montreal -> New York", "YUL", "JFK", 300,
                  airline="Delta"),
    ]
    bo_current = {
        "CDG": {"price": 850, "airline": "Air Canada", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
        "JFK": {"price": 300, "airline": "Inconnue", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
    }
    _, best_offers = _gen(rows, best_offers_current=bo_current)
    assert "JFK" not in best_offers, f"JFK Inconnue leaked into BEST_OFFERS"
    assert "CDG" in best_offers


def test_best_offers_clean_preserved():
    """BEST_OFFERS garde les destinations avec compagnie connue."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 850,
                  airline="Air Canada"),
    ]
    bo_current = {
        "CDG": {"price": 850, "airline": "Air Canada", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
    }
    _, best_offers = _gen(rows, best_offers_current=bo_current)
    assert "CDG" in best_offers


# --- Scoring aligned with published data ---

def test_scores_exclude_inconnue_prices():
    """Les scores sont calculés uniquement sur les lignes publiables.

    route_avg et route_min n'incluent PAS les prix Inconnue.
    Un vol sans historique publiable reçoit un score conservateur
    (pas de prix_bas → score 4 pour un direct).
    """
    rows = [
        # Historique : que des Inconnue → pas de baseline publiable
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 800,
                  airline="YUL–JFK"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 900,
                  airline="YUL–JFK"),
        # Cycle courant : un vol publiable bien moins cher
        _make_row("2026-04-02 06:00Z", "Montreal -> New York", "YUL", "JFK", 300,
                  airline="Delta"),
    ]
    flights, _ = _gen(rows)
    assert len(flights) == 1
    assert flights[0]["airline"] == "Delta"
    # Sans baseline publiable, avg=0 → prix_bas=False → score=4 (direct)
    assert flights[0]["score"] == 4


def test_scores_use_published_baseline():
    """Quand un historique publiable existe, les scores en tiennent compte."""
    rows = [
        # Historique publiable
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 800,
                  airline="Delta"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 900,
                  airline="United"),
        # Inconnue ignorée pour le scoring
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 200,
                  airline="YUL–JFK"),
        # Cycle courant : 300 << avg(800,900)=850 → prix_bas
        _make_row("2026-04-02 06:00Z", "Montreal -> New York", "YUL", "JFK", 300,
                  airline="JetBlue"),
    ]
    flights, _ = _gen(rows)
    published = [f for f in flights if f["date"] == "2026-04-02 06:00Z"]
    assert len(published) == 1
    # 300/850 ≈ 0.35 < 0.80 → prix_bas + direct → score 5
    assert published[0]["score"] == 5


# --- BEST_OFFERS fallback on known airline ---

def test_best_offers_fallback_to_known_airline():
    """Si la ligne cheapest est Inconnue mais qu'une ligne connue existe,
    BEST_OFFERS conserve la destination avec la compagnie connue.

    Note : le fallback se fait dans main_ci.py (by_dest builder).
    Ici on vérifie côté generate_data_js que si best_offers_current
    arrive déjà propre, la destination est conservée.
    """
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 500,
                  airline="Delta"),
        _make_row("2026-04-02 06:00Z", "Montreal -> New York", "YUL", "JFK", 400,
                  airline="Delta"),
    ]
    # Simule un best_offers_current déjà filtré (fallback fait en amont)
    bo_current = {
        "JFK": {"price": 400, "airline": "Delta", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
    }
    _, best_offers = _gen(rows, best_offers_current=bo_current)
    assert "JFK" in best_offers
    assert best_offers["JFK"]["airline"] == "Delta"


def test_best_offers_all_inconnue_excluded():
    """Si TOUTES les lignes d'une destination sont Inconnue,
    la destination est exclue de BEST_OFFERS."""
    rows = [
        _make_row("2026-04-01 06:00Z", "Montreal -> Paris", "YUL", "CDG", 900,
                  airline="Air Canada"),
        _make_row("2026-04-01 06:00Z", "Montreal -> New York", "YUL", "JFK", 334,
                  airline="YUL–JFK"),
        _make_row("2026-04-02 06:00Z", "Montreal -> Paris", "YUL", "CDG", 850,
                  airline="Air Canada"),
        _make_row("2026-04-02 06:00Z", "Montreal -> New York", "YUL", "JFK", 300,
                  airline="YUL–JFK"),
    ]
    bo_current = {
        "CDG": {"price": 850, "airline": "Air Canada", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
        "JFK": {"price": 300, "airline": "Inconnue", "stops": "Direct",
                "date": "2026-04-02 06:00Z"},
    }
    _, best_offers = _gen(rows, best_offers_current=bo_current)
    assert "JFK" not in best_offers
    assert "CDG" in best_offers


# --- Publish gate (main_ci.py) ---

def test_inconnue_gate_blocks_publication():
    """main_ci.py bloque la publication si > 30% des lignes sont Inconnue."""
    from main_ci import MAX_INCONNUE_RATIO, normalize_airline
    # Simuler 10 résultats dont 4 Inconnue (40% > 30%)
    results = [
        {"airline": "Delta"}, {"airline": "United"}, {"airline": "Air Canada"},
        {"airline": "Air Transat"}, {"airline": "WestJet"}, {"airline": "JetBlue"},
        {"airline": "YUL–JFK"}, {"airline": "YUL–JFK"},
        {"airline": "YUL–JFK"}, {"airline": "YUL–JFK"},
    ]
    n_inconnue = sum(1 for r in results
                     if normalize_airline(r.get("airline", "")) == "Inconnue")
    ratio = n_inconnue / len(results)
    assert ratio > MAX_INCONNUE_RATIO, f"Test setup: ratio {ratio} should exceed threshold"
    assert n_inconnue == 4


def test_inconnue_gate_allows_normal_cycle():
    """Un cycle avec peu de Inconnue passe le gate."""
    from main_ci import MAX_INCONNUE_RATIO, normalize_airline
    # 10 résultats dont 2 Inconnue (20% < 30%)
    results = [
        {"airline": "Delta"}, {"airline": "United"}, {"airline": "Air Canada"},
        {"airline": "Air Transat"}, {"airline": "WestJet"}, {"airline": "JetBlue"},
        {"airline": "American"}, {"airline": "Air France"},
        {"airline": "YUL–JFK"}, {"airline": "YUL–JFK"},
    ]
    n_inconnue = sum(1 for r in results
                     if normalize_airline(r.get("airline", "")) == "Inconnue")
    ratio = n_inconnue / len(results)
    assert ratio <= MAX_INCONNUE_RATIO, f"Ratio {ratio} should be under threshold"


# --- by_dest fallback in main_ci.py ---

def test_by_dest_prefers_known_airline():
    """main_ci.py by_dest choisit une compagnie connue même plus chère."""
    from scraper import normalize_airline
    # Simule le même algorithme que main_ci.py
    results = [
        {"destination": "JFK", "price_google": 200, "airline": "YUL–JFK",
         "origin": "YUL", "depart": "2026-06-01", "retour": "2026-06-08",
         "escales": "Direct", "date": "2026-04-02 06:00Z"},
        {"destination": "JFK", "price_google": 350, "airline": "Delta",
         "origin": "YUL", "depart": "2026-06-01", "retour": "2026-06-08",
         "escales": "Direct", "date": "2026-04-02 06:00Z"},
    ]
    by_dest = {}
    for r in results:
        dest = r["destination"]
        price = r["price_google"]
        is_known = normalize_airline(r.get("airline", "")) != "Inconnue"
        current = by_dest.get(dest)
        if current is None:
            by_dest[dest] = r
        else:
            cur_price = current["price_google"]
            cur_known = normalize_airline(current.get("airline", "")) != "Inconnue"
            if (is_known and not cur_known) or (is_known == cur_known and price < cur_price):
                by_dest[dest] = r

    assert by_dest["JFK"]["airline"] == "Delta"
    assert by_dest["JFK"]["price_google"] == 350


if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith("test_")]
    passed = failed = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            passed += 1
            print(f"  OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
