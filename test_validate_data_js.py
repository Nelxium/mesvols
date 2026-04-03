"""Tests pour validate_data_js — publication contract gate."""

import json
import os
import tempfile

from main_ci import validate_data_js


def _write_js(path, flight_data="[{}]", best_offers='{"CDG":{"price":500}}',
              last_update="2026-04-03 12:00Z"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"const FLIGHT_DATA = {flight_data};\n\n")
        f.write(f"const BEST_OFFERS = {best_offers};\n\n")
        f.write(f'const LAST_UPDATE = "{last_update}";\n')


def _tmp():
    return tempfile.mktemp(suffix=".js")


def test_valid_data_js():
    """Un data.js valide passe sans erreur."""
    p = _tmp()
    bo = json.dumps({
        "CDG": {"price": 750, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "CUN": {"price": 400, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "NRT": {"price": 1500, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "HND": {"price": 1500, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "PUJ": {"price": 600, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
    })
    _write_js(p, flight_data='[{"route":"a"}]', best_offers=bo)
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok, f"Should pass: {errs}"
        assert not errs
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


def test_zero_price():
    """Un prix a 0 dans BEST_OFFERS = erreur."""
    p = _tmp()
    bo = json.dumps({"CDG": {"price": 0}, "CUN": {"price": 400},
                      "NRT": {"price": 1500}, "HND": {"price": 1500}})
    _write_js(p, best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("price invalide" in e for e in errs)
    finally:
        os.unlink(p)


def test_low_destination_coverage():
    """Moins de 50% des destinations = erreur."""
    p = _tmp()
    # 8 routes, seulement 3 destinations = 37.5%
    bo = json.dumps({"CDG": {"price": 750}, "CUN": {"price": 400},
                      "NRT": {"price": 1500}})
    _write_js(p, best_offers=bo)
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("destinations" in e for e in errs)
    finally:
        os.unlink(p)


def test_bad_last_update_format():
    """LAST_UPDATE avec format invalide = erreur."""
    p = _tmp()
    bo = json.dumps({"CDG": {"price": 750}, "CUN": {"price": 400},
                      "NRT": {"price": 1500}, "HND": {"price": 1500},
                      "PUJ": {"price": 600}})
    _write_js(p, best_offers=bo, last_update="invalid-date")
    try:
        ok, errs, _ = validate_data_js(p)
        assert not ok
        assert any("LAST_UPDATE" in e for e in errs)
    finally:
        os.unlink(p)


def test_empty_last_update():
    """LAST_UPDATE vide = erreur."""
    p = _tmp()
    bo = json.dumps({"CDG": {"price": 750}, "CUN": {"price": 400},
                      "NRT": {"price": 1500}, "HND": {"price": 1500}})
    _write_js(p, best_offers=bo, last_update="")
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
        "CUN": {"price": 400, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "NRT": {"price": 1500, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
        "HND": {"price": 1500, "date": "2026-04-03 12:00Z", "search_url": "https://..."},
    })
    _write_js(p, flight_data='[{"route":"a"}]', best_offers=bo)
    try:
        ok, errs, warns = validate_data_js(p)
        assert ok, f"Warnings should not block: {errs}"
        assert len(warns) >= 1, "Should have at least 1 warning"
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
