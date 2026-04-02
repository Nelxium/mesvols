"""
MesVols - POC scraping Google Flights (1 route, 1 horizon).
Verifie que Selenium + Chrome headless + Google Flights fonctionnent.

Usage:
    python scrape_poc.py
"""

import sys
import time
from datetime import datetime, timedelta

from scraper import get_driver, build_flights_url, parse_flight_results

ORIGIN = "YUL"
DESTINATION = "JFK"
ROUTE_NAME = "Montreal -> New York"
DAYS_AHEAD = 30


def main():
    depart = datetime.now() + timedelta(days=DAYS_AHEAD)
    retour = depart + timedelta(days=7)
    d_str = depart.strftime("%Y-%m-%d")
    r_str = retour.strftime("%Y-%m-%d")

    url = build_flights_url(ORIGIN, DESTINATION, depart, retour)

    print("=" * 60)
    print("MesVols - POC Scraping")
    print("=" * 60)
    print(f"Route:   {ROUTE_NAME} ({ORIGIN} -> {DESTINATION})")
    print(f"Dates:   {d_str} -> {r_str}")
    print(f"URL:     {url}")
    print()

    print("[1/3] Lancement du navigateur headless...")
    try:
        driver = get_driver()
    except Exception as e:
        print(f"ECHEC: impossible de lancer Chrome headless: {e}")
        sys.exit(1)
    print("  -> Chrome demarre OK")

    print(f"[2/3] Chargement de Google Flights...")
    try:
        driver.get(url)
        time.sleep(10)
        title = driver.title
        print(f"  -> Page chargee (titre: {title})")
    except Exception as e:
        print(f"ECHEC: erreur chargement page: {e}")
        driver.quit()
        sys.exit(2)

    print(f"[3/3] Extraction des resultats...")
    try:
        flights = parse_flight_results(driver)
    except Exception as e:
        print(f"ECHEC: erreur parsing: {e}")
        driver.quit()
        sys.exit(3)
    finally:
        driver.quit()

    print()
    print("=" * 60)
    print("RESULTATS")
    print("=" * 60)

    if not flights:
        print("ECHEC: aucun vol trouve.")
        print("Google Flights a peut-etre bloque la requete ou change son HTML.")
        sys.exit(4)

    best = min(flights, key=lambda f: f["price"])
    print(f"Vols trouves:  {len(flights)}")
    print(f"Meilleur prix: {best['price']} $ CAD")
    print(f"Compagnie:     {best['airline']}")
    print(f"Escales:       {best.get('stops_text', '?')}")
    print()
    print("POC REUSSI — Selenium + Google Flights fonctionnent.")
    sys.exit(0)


if __name__ == "__main__":
    main()
