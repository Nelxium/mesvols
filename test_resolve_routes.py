"""Tests pour _resolve_routes() — filtrage de routes pour run_scraper()."""

from scraper import _resolve_routes
from config import ROUTES


def test_none_returns_all_routes():
    """routes_subset=None retourne toutes les routes (comportement par defaut)."""
    result = _resolve_routes(None)
    assert result == list(ROUTES)
    assert len(result) == len(ROUTES)


def test_empty_list_returns_empty():
    """Liste vide → pas de routes."""
    result = _resolve_routes([])
    assert result == []


def test_full_tuple_accepted():
    """Un tuple complet (origin, dest, name) est accepte."""
    subset = [("YUL", "CDG", "Montreal -> Paris")]
    result = _resolve_routes(subset)
    assert len(result) == 1
    assert result[0] == ("YUL", "CDG", "Montreal -> Paris")


def test_short_tuple_accepted():
    """Un tuple (origin, dest) sans nom est resolu vers le tuple complet."""
    subset = [("YUL", "CDG")]
    result = _resolve_routes(subset)
    assert len(result) == 1
    assert result[0] == ("YUL", "CDG", "Montreal -> Paris")


def test_multiple_routes():
    """Plusieurs routes valides sont toutes retournees."""
    subset = [("YUL", "CDG"), ("YUL", "JFK"), ("YUL", "CUN")]
    result = _resolve_routes(subset)
    assert len(result) == 3
    keys = [(r[0], r[1]) for r in result]
    assert ("YUL", "CDG") in keys
    assert ("YUL", "JFK") in keys
    assert ("YUL", "CUN") in keys


def test_unknown_route_skipped(capsys):
    """Une route inconnue est ignoree avec un warning."""
    subset = [("YYZ", "LAX", "Toronto -> LA")]
    result = _resolve_routes(subset)
    assert result == []
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "YYZ" in captured.out


def test_mix_valid_and_invalid(capsys):
    """Les routes valides passent, les inconnues sont filtrees."""
    subset = [("YUL", "CDG"), ("YYZ", "LAX"), ("YUL", "JFK")]
    result = _resolve_routes(subset)
    assert len(result) == 2
    keys = [(r[0], r[1]) for r in result]
    assert ("YUL", "CDG") in keys
    assert ("YUL", "JFK") in keys
    captured = capsys.readouterr()
    assert "YYZ" in captured.out


def test_order_preserved():
    """L'ordre des routes demandees est preserve."""
    subset = [("YUL", "JFK"), ("YUL", "CDG"), ("YUL", "CUN")]
    result = _resolve_routes(subset)
    assert result[0][1] == "JFK"
    assert result[1][1] == "CDG"
    assert result[2][1] == "CUN"


def test_duplicate_routes_preserved():
    """Les doublons sont gardes (pas de dedup implicite)."""
    subset = [("YUL", "CDG"), ("YUL", "CDG")]
    result = _resolve_routes(subset)
    assert len(result) == 2


def test_all_config_routes_accepted():
    """Passer toutes les ROUTES explicitement donne le meme resultat que None."""
    result_explicit = _resolve_routes(list(ROUTES))
    result_default = _resolve_routes(None)
    assert result_explicit == result_default


def test_resolved_tuples_are_always_full():
    """Meme avec des 2-tuples en entree, la sortie est toujours des 3-tuples."""
    subset = [("YUL", "CDG"), ("YUL", "NRT")]
    result = _resolve_routes(subset)
    for r in result:
        assert len(r) == 3, f"Expected 3-tuple, got {r}"
        assert isinstance(r[2], str) and len(r[2]) > 0
