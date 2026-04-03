"""Tests pour normalize_airline() — normalisation des noms de compagnies."""

from scraper import normalize_airline


# --- Noms propres (inchanges) ---

def test_clean_names():
    """Les noms propres connus restent inchanges."""
    assert normalize_airline("Air Canada") == "Air Canada"
    assert normalize_airline("Delta") == "Delta"
    assert normalize_airline("United") == "United"
    assert normalize_airline("Air Transat") == "Air Transat"
    assert normalize_airline("Qatar Airways") == "Qatar Airways"
    assert normalize_airline("Porter Airlines") == "Porter Airlines"


# --- Concatenations sans separateur ---

def test_concat_air_france_delta():
    """Air FranceDelta -> Air France."""
    assert normalize_airline("Air FranceDelta") == "Air France"


def test_concat_air_transat_porter():
    """Air TransatPorter Airlines -> Air Transat."""
    assert normalize_airline("Air TransatPorter Airlines") == "Air Transat"


def test_concat_american_porter():
    """AmericanPorter Airlines -> American."""
    assert normalize_airline("AmericanPorter Airlines") == "American"


def test_concat_air_canada_ana():
    """Air CanadaANA -> Air Canada."""
    assert normalize_airline("Air CanadaANA") == "Air Canada"


# --- Texte parasite colle ---

def test_vol_opere_par():
    """Air CanadaVol opéré par Air Canada Rouge -> Air Canada."""
    assert normalize_airline("Air CanadaVol opéré par Air Canada Rouge") == "Air Canada"


def test_vol_opere_express():
    """Air CanadaVol opéré par Air Canada Express - Jazz -> Air Canada."""
    assert normalize_airline("Air CanadaVol opéré par Air Canada Express - Jazz") == "Air Canada"


def test_lufthansa_brussels():
    """Air CanadaLufthansa, Brussels Airlines -> Air Canada."""
    assert normalize_airline("Air CanadaLufthansa, Brussels Airlines") == "Air Canada"


# --- Multi-carriers propres ---

def test_multi_carrier_et():
    """Qatar Airways et JAL -> Qatar Airways (premiere connue)."""
    assert normalize_airline("Qatar Airways et JAL") == "Qatar Airways"


def test_multi_carrier_air_canada_united():
    """Air Canada et United -> Air Canada."""
    assert normalize_airline("Air Canada et United") == "Air Canada"


def test_multi_carrier_porter_air_transat():
    """Porter Airlines et Air Transat -> Porter Airlines."""
    assert normalize_airline("Porter Airlines et Air Transat") == "Porter Airlines"


# --- Codes de route (doivent etre rejetes) ---

def test_route_code_yul_jfk():
    """YUL-JFK (code route) -> Inconnue."""
    assert normalize_airline("YUL–JFK") == "Inconnue"


def test_route_code_yul_cdg():
    """YUL-CDG -> Inconnue."""
    assert normalize_airline("YUL-CDG") == "Inconnue"


def test_route_code_with_spaces():
    """YUL – MIA -> Inconnue."""
    assert normalize_airline("YUL – MIA") == "Inconnue"


# --- Cas limites ---

def test_empty():
    assert normalize_airline("") == "Inconnue"


def test_none():
    assert normalize_airline(None) == "Inconnue"


def test_inconnue():
    assert normalize_airline("Inconnue") == "Inconnue"


def test_unknown_airline():
    """Compagnie non connue mais propre -> retournee telle quelle."""
    assert normalize_airline("Arajet") == "Arajet"


def test_unknown_airline_not_in_list():
    """Compagnie totalement inconnue -> retournee telle quelle."""
    assert normalize_airline("FlyBondi") == "FlyBondi"


# --- Labels parasites Google Flights ---

def test_emissions_hab():
    """Émissions hab. (label Google Flights) -> Inconnue."""
    assert normalize_airline("Émissions hab.") == "Inconnue"


def test_emissions_habituelles():
    """Émissions habituelles -> Inconnue."""
    assert normalize_airline("Émissions habituelles") == "Inconnue"


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
