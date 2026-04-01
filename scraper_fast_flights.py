"""
Spike controle : scraper Google Flights via fast-flights 2.2.
Test limite a YUL-CDG, comparaison avec Selenium.

fast-flights utilise primp (HTTP impersonation) au lieu de Selenium/Playwright.
Pas de navigateur headless necessaire.
"""

import re
import sys
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")


def scrape_fast_flights(origin, dest, depart, retour):
    """
    Scrape Google Flights via fast-flights pour un aller-retour.
    Retourne une liste de dicts {price, airline, stops, stops_text}.
    """
    from fast_flights import FlightData, Passengers, get_flights

    flight_data = [
        FlightData(date=depart.strftime("%Y-%m-%d"), from_airport=origin, to_airport=dest),
        FlightData(date=retour.strftime("%Y-%m-%d"), from_airport=dest, to_airport=origin),
    ]
    passengers = Passengers(adults=1)

    result = get_flights(
        flight_data=flight_data,
        trip="round-trip",
        passengers=passengers,
        seat="economy",
    )

    flights = []
    for f in result.flights:
        # Extraire le prix numerique depuis "759 $CA", "1 060 CAD", "$719", etc.
        price = None
        if f.price:
            cleaned = f.price.replace("\xa0", " ").replace("\u202f", " ")
            m = re.search(r"[\d\s]+", cleaned.replace(",", "").replace(".", ""))
            if m:
                digits = m.group().replace(" ", "")
                try:
                    price = int(digits)
                except ValueError:
                    pass

        flights.append({
            "price": price,
            "airline": f.name or "",
            "stops": f.stops,
            "stops_text": "Direct" if f.stops == 0 else f"{f.stops} escale(s)",
            "departure": f.departure or "",
            "arrival": f.arrival or "",
            "duration": f.duration or "",
            "is_best": f.is_best,
            "raw_price": f.price or "",
        })

    return flights, result.current_price


def scrape_selenium(origin, dest, depart, retour):
    """Scrape via Selenium (le scraper existant) pour comparaison."""
    from scraper import get_driver, build_flights_url, parse_flight_results

    url = build_flights_url(origin, dest, depart, retour)
    driver = get_driver()
    try:
        driver.get(url)
        time.sleep(7)
        flights = parse_flight_results(driver)
        return flights
    finally:
        driver.quit()


def compare_test():
    """Compare fast-flights vs Selenium sur YUL-CDG J+60."""
    origin, dest = "YUL", "CDG"
    depart = datetime.now() + timedelta(days=60)
    retour = depart + timedelta(days=7)

    print("=" * 60)
    print(f"Comparaison fast-flights vs Selenium")
    print(f"Route: {origin} -> {dest}")
    print(f"Dates: {depart.strftime('%Y-%m-%d')} -> {retour.strftime('%Y-%m-%d')}")
    print("=" * 60)

    # --- fast-flights ---
    print("\n--- fast-flights 2.2 ---")
    ff_error = None
    ff_flights = []
    ff_price_level = ""
    t0 = time.time()
    try:
        ff_flights, ff_price_level = scrape_fast_flights(origin, dest, depart, retour)
        ff_time = time.time() - t0
        print(f"  Temps: {ff_time:.1f}s")
        print(f"  Resultats: {len(ff_flights)} vols")
        print(f"  Niveau prix: {ff_price_level}")
        if ff_flights:
            best = min((f for f in ff_flights if f["price"]), key=lambda f: f["price"], default=None)
            if best:
                print(f"  Meilleur: {best['price']} $ ({best['airline']}, {best['stops_text']})")
            for i, f in enumerate(ff_flights[:5]):
                print(f"    {i+1}. {f['raw_price']:>12} | {f['airline'][:30]:<30} | {f['stops_text']:<12} | {f['duration']}")
        else:
            print("  Aucun resultat")
    except Exception as e:
        ff_time = time.time() - t0
        ff_error = str(e)
        print(f"  ERREUR ({ff_time:.1f}s): {e}")

    # --- Selenium ---
    print("\n--- Selenium ---")
    sel_error = None
    sel_flights = []
    t0 = time.time()
    try:
        sel_flights = scrape_selenium(origin, dest, depart, retour)
        sel_time = time.time() - t0
        print(f"  Temps: {sel_time:.1f}s")
        print(f"  Resultats: {len(sel_flights)} vols")
        if sel_flights:
            best = min(sel_flights, key=lambda f: f["price"])
            print(f"  Meilleur: {best['price']} $ ({best['airline']}, {best['stops_text']})")
            for i, f in enumerate(sel_flights[:5]):
                print(f"    {i+1}. {f['price']:>8} $ | {f['airline'][:30]:<30} | {f['stops_text']:<12}")
        else:
            print("  Aucun resultat")
    except Exception as e:
        sel_time = time.time() - t0
        sel_error = str(e)
        print(f"  ERREUR ({sel_time:.1f}s): {e}")

    # --- Comparaison ---
    print("\n" + "=" * 60)
    print("COMPARAISON")
    print("=" * 60)

    ff_ok = len(ff_flights) > 0 and any(f["price"] for f in ff_flights) and not ff_error
    sel_ok = len(sel_flights) > 0 and not sel_error

    print(f"  fast-flights: {'OK' if ff_ok else 'ECHEC'} ({len(ff_flights)} vols, {ff_time:.1f}s)")
    print(f"  Selenium:     {'OK' if sel_ok else 'ECHEC'} ({len(sel_flights)} vols, {sel_time:.1f}s)")

    if ff_ok and sel_ok:
        ff_best = min((f["price"] for f in ff_flights if f["price"]), default=0)
        sel_best = min((f["price"] for f in sel_flights), default=0)
        diff = abs(ff_best - sel_best)
        pct = (diff / sel_best * 100) if sel_best else 0

        print(f"\n  Prix le plus bas:")
        print(f"    fast-flights: {ff_best} $")
        print(f"    Selenium:     {sel_best} $")
        print(f"    Ecart:        {diff} $ ({pct:.1f}%)")

        ff_airlines = {f["airline"] for f in ff_flights if f["airline"]}
        sel_airlines = {f["airline"] for f in sel_flights if f["airline"]}
        common = ff_airlines & sel_airlines
        print(f"\n  Compagnies fast-flights: {', '.join(sorted(ff_airlines)) or 'aucune'}")
        print(f"  Compagnies Selenium:     {', '.join(sorted(sel_airlines)) or 'aucune'}")
        print(f"  En commun:               {', '.join(sorted(common)) or 'aucune'}")

        speedup = sel_time / ff_time if ff_time > 0 else 0
        print(f"\n  Speedup: {speedup:.1f}x plus rapide")

        # Verdict
        coherent = pct < 20 and len(ff_flights) >= 2 and len(common) >= 1
        print(f"\n  VERDICT: {'COHERENT' if coherent else 'INCOHERENT'}")
        if coherent:
            print("  -> fast-flights retourne des resultats exploitables et coherents.")
            print("  -> Integration via SCRAPER_BACKEND recommandee.")
        else:
            reasons = []
            if pct >= 20:
                reasons.append(f"ecart prix {pct:.0f}%")
            if len(ff_flights) < 2:
                reasons.append(f"seulement {len(ff_flights)} vol(s)")
            if len(common) < 1:
                reasons.append("aucune compagnie en commun")
            print(f"  -> Resultats incoherents ({', '.join(reasons)}).")
            print("  -> Ne pas integrer dans main.py.")

        return coherent

    elif ff_ok and not sel_ok:
        print("\n  Selenium en echec — comparaison impossible.")
        print("  fast-flights semble fonctionner mais pas de reference.")
        return False

    elif not ff_ok:
        print(f"\n  fast-flights en echec: {ff_error or 'aucun resultat exploitable'}")
        print("  -> Ne pas integrer dans main.py.")
        return False

    return False


if __name__ == "__main__":
    is_coherent = compare_test()
    if not is_coherent:
        print("\n>>> Pas d'integration — SCRAPER_BACKEND reste 'selenium'.")
