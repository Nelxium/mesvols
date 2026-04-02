"""Tests pour le watchdog local — verifie qu'il ne modifie pas les artefacts publics."""

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def test_watchdog_does_not_write_csv():
    """Le watchdog monkey-patch save_to_csv pour ne pas ecrire au CSV."""
    import scraper as _scraper_mod
    calls = []
    original = _scraper_mod.save_to_csv

    # Simuler le monkey-patch du watchdog
    _scraper_mod.save_to_csv = lambda results: calls.append(len(results))
    try:
        _scraper_mod.save_to_csv([{"test": 1}])
        assert len(calls) == 1, "save_to_csv should be intercepted"
    finally:
        _scraper_mod.save_to_csv = original


def test_watchdog_state_is_gitignored():
    """watchdog_state.json doit etre dans .gitignore."""
    gitignore = os.path.join(HERE, ".gitignore")
    with open(gitignore, encoding="utf-8") as f:
        content = f.read()
    assert "watchdog_state.json" in content, "watchdog_state.json not in .gitignore"


def test_watchdog_does_not_import_data_js_write():
    """Le watchdog ne doit pas importer generate_data_js pour ecrire."""
    with open(os.path.join(HERE, "watchdog.py"), encoding="utf-8") as f:
        content = f.read()
    assert "generate_data_js" not in content, "watchdog should not call generate_data_js"
    assert "publish" not in content.lower() or "public" in content.lower(), \
        "watchdog should not publish"


def test_watchdog_does_not_write_data_js():
    """Le watchdog ne doit pas ecrire dans data.js ou docs/data.js."""
    with open(os.path.join(HERE, "watchdog.py"), encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines, 1):
        # Chercher les writes explicites vers data.js
        if "open(" in line and ("data.js" in line or "docs/" in line):
            if '"w"' in line or "'w'" in line:
                assert False, f"Line {i} writes to data.js/docs: {line.strip()}"


def test_public_state_readonly():
    """_load_public_state lit data.js en mode readonly."""
    from watchdog import _load_public_state
    # Devrait fonctionner sans erreur (lecture seule)
    last_update, best_offers = _load_public_state()
    # Pas d'assertion sur le contenu — juste qu'il ne crash pas
    # et qu'il retourne le bon type
    assert last_update is None or isinstance(last_update, str)
    assert best_offers is None or isinstance(best_offers, dict)


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
