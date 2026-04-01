"""
MesVols - Detecteur de vols pas chers
Point d'entree principal : scrape, analyse et alerte.
"""

import csv
import json
import os
from collections import defaultdict

from scraper import run_scraper
from analyzer import find_deals, parse_stops, compute_score
from notifier import send_deal_alert

CSV_PATH = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
DATA_JS_PATH = os.path.join(os.path.dirname(__file__), "data.js")


def generate_data_js():
    """Regenere data.js a partir de prix_vols.csv (supporte ancien et nouveau format)."""
    raw_rows = []
    last_date = ""
    route_prices = defaultdict(list)

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            date = row.get("date", "")
            route = row.get("route", "")
            origin = row.get("origin", "")
            dest = row.get("destination", "")
            airline = row.get("airline", "Inconnue")
            stops = row.get("escales", "")
            depart = row.get("depart", "")
            retour = row.get("retour", "")

            # Prix Google (ancien: price_cad, nouveau: price_google)
            pg = row.get("price_google") or row.get("price_cad", "0")
            try:
                price_g = int(pg)
            except (ValueError, TypeError):
                continue
            # Prix Skyscanner (peut etre vide)
            ps = row.get("price_skyscanner", "")
            price_s = int(ps) if ps else None

            # Prix effectif = le plus bas des deux
            best_price = min(price_g, price_s) if price_s else price_g
            route_prices[route].append(best_price)

            raw_rows.append({
                "date": date, "route": route, "origin": origin, "dest": dest,
                "price_google": price_g, "price_skyscanner": price_s,
                "airline": airline, "stops": stops,
                "depart": depart, "retour": retour,
            })
            last_date = date

    # Calculer les moyennes et minimums par route
    route_avg = {r: sum(p) / len(p) for r, p in route_prices.items()}
    route_min = {r: min(p) for r, p in route_prices.items()}

    flights = []
    for r in raw_rows:
        origin, dest = r["origin"], r["dest"]
        depart, retour = r["depart"], r["retour"]
        price_g, price_s = r["price_google"], r["price_skyscanner"]

        # URL Skyscanner
        sky_dep = depart.replace("-", "")[2:]
        sky_ret = retour.replace("-", "")[2:]
        skyscanner_url = (
            f"https://www.skyscanner.ca/transport/flights/"
            f"{origin.lower()}/{dest.lower()}/{sky_dep}/{sky_ret}/"
            f"?adultsv2=1&currency=CAD&locale=fr-CA&market=CA"
        )
        # URL Google Flights
        google_url = (f"https://www.google.com/travel/flights"
                      f"?q=flights+from+{origin}+to+{dest}"
                      f"+on+{depart}+return+{retour}")

        # Meilleur prix et source
        if price_s and price_s < price_g:
            best_price = price_s
            best_source = "Skyscanner"
            best_url = skyscanner_url
        else:
            best_price = price_g
            best_source = "Google"
            best_url = google_url

        city = r["route"].split("->")[-1].strip() if "->" in r["route"] else dest
        q = f"{r['airline']} vol Montreal {city} billet".replace(" ", "+")
        airline_url = f"https://www.google.com/search?q={q}"

        num_stops = parse_stops(r["stops"])
        score = compute_score(best_price, route_avg.get(r["route"], 0),
                              num_stops, route_min.get(r["route"]))

        entry = {
            "date": r["date"],
            "route": r["route"],
            "origin": origin,
            "destination": dest,
            "price": best_price,
            "price_google": price_g,
            "price_skyscanner": price_s,
            "best_source": best_source,
            "airline": r["airline"],
            "stops": r["stops"],
            "score": score,
            "depart": depart,
            "retour": retour,
            "booking_url": best_url,
            "skyscanner_url": skyscanner_url,
            "google_url": google_url,
            "airline_url": airline_url,
        }
        flights.append(entry)

    entries = ",\n  ".join(json.dumps(f, ensure_ascii=False) for f in flights)
    js_content = (
        f"const FLIGHT_DATA = [\n  {entries}\n];\n\n"
        f'const LAST_UPDATE = "{last_date}";\n'
    )

    with open(DATA_JS_PATH, "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"data.js regenere avec {len(flights)} vols.")


def main():
    # 1. Scraper les prix actuels
    results = run_scraper()

    if not results:
        print("\nAucun resultat trouve. Reessaie plus tard.")
        return

    # 2. Regenerer data.js
    generate_data_js()

    # 3. Analyser et comparer avec l'historique
    print("\n" + "=" * 50)
    print("Analyse des prix")
    print("=" * 50)
    deals = find_deals(results)

    # 3. Envoyer une alerte si aubaine(s) avec rabais >= 30%
    if deals:
        print(f"\n{len(deals)} AUBAINE(S) DETECTEE(S) !")
        notifiable = [d for d in deals if d.get("discount_pct", 0) >= 30]
        skipped = len(deals) - len(notifiable)
        if notifiable:
            send_deal_alert(notifiable)
            if skipped:
                print(f"  ({skipped} aubaine(s) < 30% de rabais ignoree(s) dans l'email)")
        else:
            print("  Aucune aubaine >= 30% de rabais, email non envoye.")
    else:
        print("\nPas d'aubaine aujourd'hui. Les prix sont normaux.")


if __name__ == "__main__":
    main()
