"""Tests pour links.py — URLs de recherche CTA."""

from links import build_united_search_url, build_search_link


def test_united_url_uses_canada_locale():
    """L'URL United pointe vers /en/ca/ (Canada), pas /en/us/."""
    url = build_united_search_url("YUL", "NRT", "2026-05-03", "2026-05-10")
    assert "/en/ca/fsr/choose-flights" in url
    assert "/en/us/" not in url


def test_united_url_has_required_params():
    """Les paramètres de recherche sont présents."""
    url = build_united_search_url("YUL", "NRT", "2026-05-03", "2026-05-10")
    assert "f=YUL" in url
    assert "t=NRT" in url
    assert "d=2026-05-03" in url
    assert "r=2026-05-10" in url
    assert "tt=RT" in url


def test_search_link_ua_routes_to_united():
    """airline_code UA → united.com avec locale Canada."""
    url, label = build_search_link("YUL", "NRT", "2026-05-03", "2026-05-10", "UA")
    assert "united.com/en/ca/" in url
    assert label == "Rechercher sur united.com"


def test_search_link_non_ua_routes_to_kayak():
    """Autre compagnie → kayak.com."""
    url, label = build_search_link("YUL", "CDG", "2026-05-03", "2026-05-10", "AC")
    assert "kayak.com" in url
