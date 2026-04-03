"""Tests pour validate_data_js — publication contract gate."""

import json
import os
import tempfile

from main_ci import validate_data_js

LU = "2026-04-03 12:00Z"


def _good_fd(dests=("CDG", "CUN", "NRT", "HND", "PUJ")):
    """Genere un FLIGHT_DATA valide avec les destinations specifiees."""
    return json.dumps([
        {"destination": d, "route": f"Montreal -> {d}", "price": 500 + i * 100,
         "date": LU, "stops": "Direct", "depart": "2026-06-01", "retour": "2026-06-08"}
        for i, d in enumerate(dests)
    ])


def _good_bo(dests=("CDG", "CUN", "NRT", "HND", "PUJ")):
    """Genere un BEST_OFFERS valide avec les destinations specifiees."""
    return json.dumps({
        d: {"price": 500 + i * 100, "date": LU, "search_url": "https://..."}
        for i, d in enumerate(dests)
    })


def _write_js(path, flight_data=None, best_offers=None, last_update=LU):
    if flight_data is None:
        flight_data = _good_fd()
    if best_offers is None:
        best_offers = _good_bo()
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"const FLIGHT_DATA = {flight_data};\n\n")
        f.write(f"const BEST_OFFERS = {best_offers};\n\n")
        f.write(f'const LAST_UPDATE = "{last_update}";\n')


def _tmp():
    return tempfile.mktemp(suffix=".js")


# --- Tests de base (existants, adaptes) ---

def test_valid_data_js():
    """Un data.js complet et coherent passe sans erreur."""
    p = _tmp()
    _write_js(p)
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok, f"Should pass: {errs}"
    finally:
        os.unlink(p)


def test_missing_file():
    """Fichier introuvable = erreur."""
    ok, errs, _ = validate_data_js("/tmp/nonexistent_data.js")
    assert not ok
    assert any("introuvable" in e for e in errs)


def test_empty_flight_data():
    """FLIGHT_DATA vide = erreur."""
    p = _tmp()
    _write_js(p, flight_data="[]")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("FLIGHT_DATA" in e for e in errs)
    finally:
        os.unlink(p)


def test_empty_best_offers():
    """BEST_OFFERS vide = erreur."""
    p = _tmp()
    _write_js(p, best_offers="{}")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("BEST_OFFERS vide" in e for e in errs)
    finally:
        os.unlink(p)


def test_bo_zero_price():
    """Un prix a 0 dans BEST_OFFERS = erreur."""
    p = _tmp()
    bo = json.dumps({
        "CDG": {"price": 0}, "CUN": {"price": 400},
        "NRT": {"price": 1500}, "HND": {"price": 1500}, "PUJ": {"price": 600},
    })
    _write_js(p, best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("price invalide" in e for e in errs)
    finally:
        os.unlink(p)


def test_low_destination_coverage():
    """Moins de 50% des destinations dans BEST_OFFERS = erreur."""
    p = _tmp()
    bo = json.dumps({"CDG": {"price": 750}, "CUN": {"price": 400},
                      "NRT": {"price": 1500}})
    _write_js(p, flight_data=_good_fd(("CDG", "CUN", "NRT")), best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("destinations" in e.lower() for e in errs)
    finally:
        os.unlink(p)


def test_bad_last_update_format():
    """LAST_UPDATE avec format invalide = erreur."""
    p = _tmp()
    _write_js(p, last_update="invalid-date")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("LAST_UPDATE" in e for e in errs)
    finally:
        os.unlink(p)


def test_empty_last_update():
    """LAST_UPDATE vide = erreur."""
    p = _tmp()
    _write_js(p, last_update="")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("LAST_UPDATE" in e for e in errs)
    finally:
        os.unlink(p)


def test_warnings_not_blocking():
    """Les warnings (date incoherente, search_url vide) ne bloquent pas."""
    p = _tmp()
    bo = json.dumps({
        "CDG": {"price": 750, "date": "2026-04-02 06:00Z", "search_url": ""},
        "CUN": {"price": 400, "date": LU, "search_url": "https://..."},
        "NRT": {"price": 1500, "date": LU, "search_url": "https://..."},
        "HND": {"price": 1500, "date": LU, "search_url": "https://..."},
        "PUJ": {"price": 600, "date": LU, "search_url": "https://..."},
    })
    _write_js(p, best_offers=bo)
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok, f"Warnings should not block: {errs}"
        assert len(warns) >= 1
    finally:
        os.unlink(p)


def test_real_data_js():
    """Le data.js reel du repo doit passer la validation."""
    real_path = os.path.join(os.path.dirname(__file__), "data.js")
    if not os.path.isfile(real_path):
        print("  SKIP (pas de data.js)")
        return
    ok, errs, warns = validate_data_js(real_path)
    assert ok, f"Real data.js failed validation: {errs}"


# --- Nouveaux tests : parsing FLIGHT_DATA ---

def test_fd_malformed_json():
    """FLIGHT_DATA textuellement non-vide mais JSON invalide = erreur."""
    p = _tmp()
    _write_js(p, flight_data='[{"broken: true}]')
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("JSON invalide" in e for e in errs)
    finally:
        os.unlink(p)


def test_fd_missing_required_fields():
    """FLIGHT_DATA entrees sans champs requis = erreur."""
    p = _tmp()
    fd = json.dumps([
        {"destination": "CDG", "route": "a", "price": 500},  # manque date
        {"destination": "CUN", "price": 400, "date": LU},     # manque route
        {"route": "b", "price": 300, "date": LU},             # manque destination
    ])
    _write_js(p, flight_data=fd)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("entrees invalides" in e for e in errs)
    finally:
        os.unlink(p)


def test_fd_zero_price():
    """FLIGHT_DATA avec price <= 0 = erreur."""
    p = _tmp()
    fd = json.dumps([
        {"destination": "CDG", "route": "a", "price": 0, "date": LU},
        {"destination": "CUN", "route": "b", "price": -50, "date": LU},
    ])
    _write_js(p, flight_data=fd)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("entrees invalides" in e for e in errs)
    finally:
        os.unlink(p)


# --- Nouveau test : coherence FLIGHT_DATA ↔ BEST_OFFERS ---

def test_fd_dest_missing_from_bo():
    """Destination dans FLIGHT_DATA du cycle courant mais absente de BEST_OFFERS = erreur."""
    p = _tmp()
    # FLIGHT_DATA a CDG, CUN, NRT, HND, PUJ — mais BEST_OFFERS n'a pas CUN
    fd = _good_fd(("CDG", "CUN", "NRT", "HND", "PUJ"))
    bo = _good_bo(("CDG", "NRT", "HND", "PUJ"))  # CUN manquant
    _write_js(p, flight_data=fd, best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("CUN" in e for e in errs), f"Should mention CUN: {errs}"
        assert any("absentes de BEST_OFFERS" in e for e in errs)
    finally:
        os.unlink(p)


def test_fd_dest_coherent():
    """Toutes les destinations du cycle courant dans BEST_OFFERS = OK."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    _write_js(p, flight_data=_good_fd(dests), best_offers=_good_bo(dests))
    try:
        ok, errs, _ = validate_data_js(p)
        assert ok, f"Should pass: {errs}"
    finally:
        os.unlink(p)


# --- Tests ajustement final : LAST_UPDATE strict + cycle courant non-vide ---

def test_last_update_suffix_garbage():
    """LAST_UPDATE avec suffixe garbage = erreur."""
    p = _tmp()
    _write_js(p, last_update="2026-04-03 04:34 garbage")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok, f"Should fail with suffix garbage: {errs}"
        assert any("LAST_UPDATE" in e for e in errs)
    finally:
        os.unlink(p)


def test_last_update_with_z_suffix():
    """LAST_UPDATE avec suffixe Z valide = OK."""
    p = _tmp()
    ts = "2026-04-03 04:34Z"
    _write_js(p, flight_data=_good_fd(), best_offers=_good_bo(), last_update=ts)
    # Rewrite with matching timestamps in FD
    fd = json.dumps([
        {"destination": d, "route": f"Montreal -> {d}", "price": 500 + i * 100,
         "date": ts, "stops": "Direct", "depart": "2026-06-01", "retour": "2026-06-08"}
        for i, d in enumerate(("CDG", "CUN", "NRT", "HND", "PUJ"))
    ])
    _write_js(p, flight_data=fd, best_offers=_good_bo(), last_update=ts)
    try:
        ok, errs, _ = validate_data_js(p)
        assert ok, f"Should pass with Z suffix: {errs}"
    finally:
        os.unlink(p)


def test_zero_fd_rows_at_last_update():
    """Aucune ligne FLIGHT_DATA dans le cycle courant = erreur."""
    p = _tmp()
    fd = json.dumps([
        {"destination": "CDG", "route": "a", "price": 500, "date": "2026-04-02 12:00Z"},
        {"destination": "CUN", "route": "b", "price": 400, "date": "2026-04-02 12:00Z"},
    ])
    bo = _good_bo(("CDG", "CUN", "NRT", "HND", "PUJ"))
    _write_js(p, flight_data=fd, best_offers=bo, last_update="2026-04-03 12:00Z")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok, f"Should fail with zero current-cycle rows: {errs}"
        assert any("Aucune entree FLIGHT_DATA" in e for e in errs)
    finally:
        os.unlink(p)


# --- Tests alignement producteur : prefix horaire + coherence bidirectionnelle ---

def test_per_row_timestamps_same_hour_pass():
    """Cycle courant avec timestamps per-row dans la meme heure = OK."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    # Timestamps differents mais meme heure que LAST_UPDATE
    fd = json.dumps([
        {"destination": d, "route": f"Montreal -> {d}", "price": 500 + i * 100,
         "date": f"2026-04-03 12:{i:02d}Z", "stops": "Direct",
         "depart": "2026-06-01", "retour": "2026-06-08"}
        for i, d in enumerate(dests)
    ])
    # LAST_UPDATE = derniere ligne = 12:04Z
    _write_js(p, flight_data=fd, best_offers=_good_bo(dests), last_update="2026-04-03 12:04Z")
    try:
        ok, errs, _ = validate_data_js(p)
        assert ok, f"Per-row timestamps in same hour should pass: {errs}"
    finally:
        os.unlink(p)


def test_bo_dest_missing_from_fd_current():
    """Destination dans BEST_OFFERS mais absente de FLIGHT_DATA courant = erreur."""
    p = _tmp()
    # FD courant a CDG, CUN, NRT, HND — mais BO a aussi PUJ
    fd = _good_fd(("CDG", "CUN", "NRT", "HND"))
    bo = _good_bo(("CDG", "CUN", "NRT", "HND", "PUJ"))
    _write_js(p, flight_data=fd, best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok, f"Should fail with BO dest missing from FD: {errs}"
        assert any("PUJ" in e for e in errs)
        assert any("absentes de FLIGHT_DATA" in e for e in errs)
    finally:
        os.unlink(p)


def test_bidirectional_coherent():
    """FD courant et BO ont exactement les memes destinations = OK."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    _write_js(p, flight_data=_good_fd(dests), best_offers=_good_bo(dests))
    try:
        ok, errs, _ = validate_data_js(p)
        assert ok, f"Bidirectional coherent should pass: {errs}"
    finally:
        os.unlink(p)


# --- Tests qualite airline dans le gate ---

def test_bo_route_code_airline_blocked():
    """BEST_OFFERS avec airline = code route (YUL-JFK) = erreur."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 500 + i * 100, "date": LU, "search_url": "https://...",
              "airline": "Air Canada" if d != "CDG" else "YUL\u2013JFK"}
          for i, d in enumerate(dests)}
    _write_js(p, flight_data=_good_fd(dests), best_offers=json.dumps(bo))
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok, f"Route-code airline should block: {errs}"
        assert any("Airlines non normalisees" in e for e in errs)
    finally:
        os.unlink(p)


def test_bo_concatenated_airline_blocked():
    """BEST_OFFERS avec airline concatenee = erreur."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 500 + i * 100, "date": LU, "search_url": "https://...",
              "airline": "Air FranceDelta" if d == "CDG" else "United"}
          for i, d in enumerate(dests)}
    _write_js(p, flight_data=_good_fd(dests), best_offers=json.dumps(bo))
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok, f"Concatenated airline should block: {errs}"
        assert any("Airlines non normalisees" in e for e in errs)
    finally:
        os.unlink(p)


def test_bo_clean_airlines_pass():
    """BEST_OFFERS avec airlines propres = OK."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    _write_js(p, flight_data=_good_fd(dests), best_offers=_good_bo(dests))
    try:
        ok, errs, _ = validate_data_js(p)
        assert ok, f"Clean airlines should pass: {errs}"
    finally:
        os.unlink(p)


# --- Tests prix aberrants (warnings, non-bloquants) ---

def test_price_suspect_bo_warning():
    """Prix < 50 ou > 15000 dans BEST_OFFERS = warning (pas bloquant)."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 500 + i * 100, "date": LU, "search_url": "https://..."}
          for i, d in enumerate(dests)}
    bo["CDG"]["price"] = 10  # suspect bas
    _write_js(p, flight_data=_good_fd(dests), best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok, f"Price warning should not block: {errs}"
        assert any("suspect" in w.lower() for w in warns), f"Should warn: {warns}"
    finally:
        os.unlink(p)


def test_price_normal_no_warning():
    """Prix normaux = pas de warning prix."""
    p = _tmp()
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    _write_js(p, flight_data=_good_fd(dests), best_offers=_good_bo(dests))
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok
        price_warns = [w for w in warns if "suspect" in w.lower()]
        assert not price_warns, f"Should have no price warnings: {price_warns}"
    finally:
        os.unlink(p)


# --- Tests route-aware price warnings ---

def _fd_with_history(dest, route, prior_prices, current_price,
                     prior_date="2026-04-02 10:00Z", origin="YUL",
                     airline="TestAir"):
    """Genere un FLIGHT_DATA avec historique + cycle courant pour une route."""
    entries = []
    for i, p in enumerate(prior_prices):
        entries.append({
            "origin": origin, "destination": dest, "route": route,
            "price": p, "airline": airline,
            "date": prior_date, "stops": "Direct",
            "depart": "2026-06-01", "retour": "2026-06-08",
        })
    # Cycle courant
    entries.append({
        "origin": origin, "destination": dest, "route": route,
        "price": current_price, "airline": airline,
        "date": LU, "stops": "Direct",
        "depart": "2026-06-01", "retour": "2026-06-08",
    })
    return entries


def test_route_aware_warns_on_very_low_price():
    """Prix BEST_OFFERS très bas vs moyenne route = warning W-PRICE-ROUTE."""
    # Historique CDG: avg ~900, BO price 100 → ratio 0.11 < 0.30
    fd_entries = _fd_with_history("CDG", "Montreal -> Paris",
                                 [800, 900, 1000], 850)
    # Ajouter les 4 autres destinations pour passer la couverture BO
    for d in ("CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["CDG"]["price"] = 100  # suspicieusement bas

    p = _tmp()
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert len(route_warns) == 1, f"Expected 1 route warning, got: {route_warns}"
        assert "CDG" in route_warns[0]
        assert "tres bas" in route_warns[0]
        assert ok, f"Route warning should not block: {errs}"
    finally:
        os.unlink(p)


def test_route_aware_warns_on_very_high_price():
    """Prix BEST_OFFERS très haut vs moyenne route = warning W-PRICE-ROUTE."""
    # Historique JFK: avg ~350, BO price 2000 → ratio 5.7 > 3.0
    fd_entries = _fd_with_history("JFK", "Montreal -> New York",
                                 [300, 350, 400], 350)
    for d in ("CDG", "CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ", "JFK")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["JFK"]["price"] = 2000  # suspicieusement haut

    p = _tmp()
    # FD needs all BO dests for coherence
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert len(route_warns) == 1, f"Expected 1 route warning, got: {route_warns}"
        assert "JFK" in route_warns[0]
        assert "tres haut" in route_warns[0]
    finally:
        os.unlink(p)


def test_route_aware_no_warn_insufficient_history():
    """Route avec < 3 points historiques = pas de warning route-aware."""
    # Seulement 2 points historiques pour CDG
    fd_entries = []
    fd_entries.append({"origin": "YUL", "destination": "CDG",
                       "route": "Montreal -> Paris", "airline": "Air Canada",
                       "price": 900, "date": "2026-04-02 10:00Z",
                       "stops": "Direct", "depart": "2026-06-01",
                       "retour": "2026-06-08"})
    fd_entries.append({"origin": "YUL", "destination": "CDG",
                       "route": "Montreal -> Paris", "airline": "Air Transat",
                       "price": 1000, "date": "2026-04-02 10:00Z",
                       "stops": "Direct", "depart": "2026-07-01",
                       "retour": "2026-07-08"})
    # Current cycle
    fd_entries.append({"origin": "YUL", "destination": "CDG",
                       "route": "Montreal -> Paris", "airline": "Air Canada",
                       "price": 100, "date": LU, "stops": "Direct",
                       "depart": "2026-06-01", "retour": "2026-06-08"})
    # Other dests for coverage
    for d in ("CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["CDG"]["price"] = 100  # Would be suspicious, but not enough history

    p = _tmp()
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert not route_warns, f"Should not warn with < 3 datapoints: {route_warns}"
    finally:
        os.unlink(p)


def test_route_aware_excludes_current_cycle():
    """La baseline route-aware exclut le cycle courant."""
    # Prior: avg=900. Current: 100 (same LU hour).
    # If current leaks into baseline, avg would drop, masking the warning.
    fd_entries = _fd_with_history("CDG", "Montreal -> Paris",
                                 [800, 900, 1000], 100)
    for d in ("CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["CDG"]["price"] = 100  # ratio vs prior avg 900 = 0.11 < 0.30

    p = _tmp()
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert len(route_warns) == 1, \
            f"Should warn (current excluded from baseline): {route_warns}"
        assert "CDG" in route_warns[0]
    finally:
        os.unlink(p)


def test_route_aware_normal_price_no_warning():
    """Prix normal pour la route = pas de warning route-aware."""
    fd_entries = _fd_with_history("CDG", "Montreal -> Paris",
                                 [800, 900, 1000], 850)
    for d in ("CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["CDG"]["price"] = 850  # normal: ratio ~0.94

    p = _tmp()
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert not route_warns, f"Normal price should not trigger: {route_warns}"
    finally:
        os.unlink(p)


def test_route_baselines_unit():
    """Test unitaire de _route_baselines() — cle (origin, dest), excl. cycle courant."""
    from main_ci import _route_baselines
    flights = [
        # Prior: 3 entries YUL-CDG
        {"origin": "YUL", "destination": "CDG", "price": 800,
         "date": "2026-04-02 10:00Z", "airline": "Air Canada"},
        {"origin": "YUL", "destination": "CDG", "price": 900,
         "date": "2026-04-02 10:00Z", "airline": "Air Transat"},
        {"origin": "YUL", "destination": "CDG", "price": 1000,
         "date": "2026-04-02 10:00Z", "airline": "Delta"},
        # Prior: only 2 for YUL-NRT (insufficient)
        {"origin": "YUL", "destination": "NRT", "price": 1500,
         "date": "2026-04-02 10:00Z", "airline": "United"},
        {"origin": "YUL", "destination": "NRT", "price": 1600,
         "date": "2026-04-02 10:00Z", "airline": "ANA"},
        # Current cycle (excluded)
        {"origin": "YUL", "destination": "CDG", "price": 100,
         "date": LU, "airline": "Air Canada"},
    ]
    bl = _route_baselines(flights, LU)
    assert ("YUL", "CDG") in bl
    assert bl[("YUL", "CDG")]["count"] == 3
    assert bl[("YUL", "CDG")]["avg"] == 900.0
    assert bl[("YUL", "CDG")]["min"] == 800
    assert ("YUL", "NRT") not in bl  # insufficient history


def test_route_baselines_excludes_inconnue():
    """_route_baselines() ignore les lignes airline=Inconnue dans la baseline."""
    from main_ci import _route_baselines
    flights = [
        # 3 Inconnue + 2 connues pour YUL-JFK
        {"origin": "YUL", "destination": "JFK", "price": 100,
         "date": "2026-04-02 10:00Z", "airline": "Inconnue"},
        {"origin": "YUL", "destination": "JFK", "price": 150,
         "date": "2026-04-02 10:00Z", "airline": "Inconnue"},
        {"origin": "YUL", "destination": "JFK", "price": 200,
         "date": "2026-04-02 10:00Z", "airline": "Inconnue"},
        {"origin": "YUL", "destination": "JFK", "price": 800,
         "date": "2026-04-02 10:00Z", "airline": "Delta"},
        {"origin": "YUL", "destination": "JFK", "price": 900,
         "date": "2026-04-02 10:00Z", "airline": "United"},
        # Current cycle
        {"origin": "YUL", "destination": "JFK", "price": 350,
         "date": LU, "airline": "JetBlue"},
    ]
    bl = _route_baselines(flights, LU)
    # Only 2 publishable prior entries → below MIN_ROUTE_DATAPOINTS
    assert ("YUL", "JFK") not in bl, \
        "Inconnue rows should not count toward baseline datapoints"


def test_route_baselines_inconnue_mixed_enough_known():
    """Avec assez de lignes connues malgré des Inconnue, baseline = connues seules."""
    from main_ci import _route_baselines
    flights = [
        {"origin": "YUL", "destination": "JFK", "price": 100,
         "date": "2026-04-02 10:00Z", "airline": "Inconnue"},
        {"origin": "YUL", "destination": "JFK", "price": 800,
         "date": "2026-04-02 10:00Z", "airline": "Delta"},
        {"origin": "YUL", "destination": "JFK", "price": 900,
         "date": "2026-04-02 10:00Z", "airline": "United"},
        {"origin": "YUL", "destination": "JFK", "price": 1000,
         "date": "2026-04-02 10:00Z", "airline": "JetBlue"},
        # Current cycle
        {"origin": "YUL", "destination": "JFK", "price": 350,
         "date": LU, "airline": "Delta"},
    ]
    bl = _route_baselines(flights, LU)
    assert ("YUL", "JFK") in bl
    # avg of 800, 900, 1000 = 900 (Inconnue 100 excluded)
    assert bl[("YUL", "JFK")]["avg"] == 900.0
    assert bl[("YUL", "JFK")]["count"] == 3


def test_route_label_drift_still_matches():
    """Labels route differents mais meme (origin, dest) -> warning correct.

    Le rapprochement utilise (origin, destination) IATA, pas le libelle.
    Historique avec "Montreal -> Paris", cycle courant avec "Montréal → Paris"
    doivent matcher sur (YUL, CDG)."""
    fd_entries = []
    # Historique avec un ancien label
    for p in [800, 900, 1000]:
        fd_entries.append({
            "origin": "YUL", "destination": "CDG",
            "route": "Montreal -> Paris",  # ancien label
            "price": p, "airline": "Air Canada",
            "date": "2026-04-02 10:00Z", "stops": "Direct",
            "depart": "2026-06-01", "retour": "2026-06-08",
        })
    # Cycle courant avec un label different
    fd_entries.append({
        "origin": "YUL", "destination": "CDG",
        "route": "Montréal → Paris",  # nouveau label
        "price": 850, "airline": "Air Transat",
        "date": LU, "stops": "Direct",
        "depart": "2026-06-01", "retour": "2026-06-08",
    })
    # Autres destinations pour couverture BO
    for d in ("CUN", "NRT", "HND", "PUJ"):
        fd_entries.extend(_fd_with_history(d, f"Montreal -> {d}",
                                           [500, 600, 700], 550))
    dests = ("CDG", "CUN", "NRT", "HND", "PUJ")
    bo = {d: {"price": 550, "date": LU, "search_url": "https://..."}
          for d in dests}
    bo["CDG"]["price"] = 100  # ratio 100/900 = 0.11 < 0.30

    p = _tmp()
    _write_js(p, flight_data=json.dumps(fd_entries),
              best_offers=json.dumps(bo))
    try:
        ok, errs, warns = validate_data_js(p)
        route_warns = [w for w in warns if "W-PRICE-ROUTE" in w]
        assert len(route_warns) == 1, \
            f"Label drift should not prevent warning: {route_warns}"
        assert "CDG" in route_warns[0]
        assert "YUL-CDG" in route_warns[0]
    finally:
        os.unlink(p)


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
