"""
MesVols - Pipeline CI (GitHub Actions).
Scrape + generation data.js, sans booking capture ni alertes.
"""

import json
import os
import sys
from datetime import datetime, timezone

from scraper import run_scraper, HORIZONS
from config import ROUTES
from main import generate_data_js, get_airline_code
from analyzer import find_deals, parse_stops, compute_score
from links import build_skyscanner_url, build_search_link

CI_HEALTH_PATH = os.path.join(os.path.dirname(__file__), "ci_health.json")

# Seuil minimum de couverture pour publier (50% des resultats attendus)
MIN_COVERAGE_RATIO = 0.50


def _write_health(results, by_dest, deals, status):
    """Ecrit ci_health.json quel que soit le statut."""
    expected = len(ROUTES) * len(HORIZONS)
    actual = len(results) if results else 0
    prices = [r.get("price_google", 0) for r in results] if results else []
    health = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "status": status,
        "routes_expected": expected,
        "routes_scraped": actual,
        "coverage_pct": round(actual / expected * 100) if expected else 0,
        "destinations": len(by_dest) if by_dest else 0,
        "deals_detected": len(deals) if deals else 0,
        "min_price": min(prices) if prices else None,
    }
    with open(CI_HEALTH_PATH, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)
    return health


def main():
    # 1. Scraper
    results = run_scraper()
    expected = len(ROUTES) * len(HORIZONS)

    if not results:
        _write_health([], {}, [], "failed")
        print("\nAucun resultat. Le scraping a echoue.")
        sys.exit(1)

    coverage = len(results) / expected if expected else 0

    # 2. Analyser
    print("\n" + "=" * 50)
    print("Analyse des prix")
    print("=" * 50)
    deals = find_deals(results)
    if deals:
        print(f"{len(deals)} aubaine(s) detectee(s) (alertes desactivees en CI)")
    else:
        print("Pas d'aubaine.")

    # 3. Construire best_offers_current (simplifie, sans booking capture)
    by_dest = {}
    for r in results:
        dest = r.get("destination", "")
        price = r.get("price_google", 0)
        if isinstance(price, str):
            price = int(price) if price else 0
        if dest not in by_dest or price < by_dest[dest].get("price_google", 0):
            by_dest[dest] = r

    best_offers_current = {}
    for dest, r in by_dest.items():
        stops_text = r.get("escales", "")
        num_stops = parse_stops(stops_text)
        airline_code = get_airline_code(r.get("airline", ""))
        sky_url = build_skyscanner_url({
            "origin": r["origin"], "destination": dest,
            "depart_date": r["depart"], "return_date": r["retour"],
        })
        google_url = (f"https://www.google.com/travel/flights"
                      f"?q=flights+from+{r['origin']}+to+{dest}"
                      f"+on+{r['depart']}+return+{r['retour']}")
        search_url, search_label = build_search_link(
            r["origin"], dest, r["depart"], r["retour"], airline_code)

        best_offers_current[dest] = {
            "price": r["price_google"],
            "price_google": r["price_google"],
            "price_skyscanner": None,
            "best_source": "Google",
            "depart": r["depart"],
            "retour": r["retour"],
            "airline": r.get("airline", ""),
            "airline_code": airline_code,
            "stops": stops_text,
            "score": compute_score(r["price_google"], 0, num_stops, None),
            "skyscanner_url": sky_url,
            "google_url": google_url,
            "deal_id": "",
            "reserve_url": "",
            "final_domain": "",
            "search_url": search_url,
            "search_label": search_label,
        }

    # 4. Coverage gate — bloquer la publication si couverture insuffisante
    if coverage < MIN_COVERAGE_RATIO:
        health = _write_health(results, by_dest, deals, "degraded")
        print(f"\nCouverture insuffisante : {len(results)}/{expected} "
              f"({health['coverage_pct']}% < {int(MIN_COVERAGE_RATIO*100)}%)")
        print("Publication bloquee. ci_health.json ecrit avec status=degraded.")
        sys.exit(1)

    # 5. Regenerer data.js (seulement si couverture suffisante)
    generate_data_js(best_offers_current)

    # 6. Ecrire ci_health.json
    health = _write_health(results, by_dest, deals, "ok")
    print(f"ci_health.json ecrit ({health['routes_scraped']}/{health['routes_expected']} routes, "
          f"{health['coverage_pct']}%)")

    print("\nPipeline CI termine.")


if __name__ == "__main__":
    main()
