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
from links import build_skyscanner_url
from booking_capture import make_deal_id, load_deals, resolve_deals

CSV_PATH = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
DATA_JS_PATH = os.path.join(os.path.dirname(__file__), "data.js")

# Mapping nom de compagnie -> code IATA (pour le filtre Skyscanner)
AIRLINE_CODES = {
    "Air Canada": "AC",
    "Air Transat": "TS",
    "WestJet": "WS",
    "Porter": "PD",
    "Flair": "F8",
    "Lynx": "Y9",
    "United": "UA",
    "Delta": "DL",
    "American": "AA",
    "JetBlue": "B6",
    "Spirit": "NK",
    "Frontier": "F9",
    "Southwest": "WN",
    "Air France": "AF",
    "Lufthansa": "LH",
    "British Airways": "BA",
    "KLM": "KL",
    "Swiss": "LX",
    "Iberia": "IB",
    "TAP Portugal": "TP",
    "Alitalia": "AZ",
    "ITA Airways": "AZ",
    "Aegean": "A3",
    "Copa": "CM",
    "Aeromexico": "AM",
    "Sunwing": "WG",
    "Condor": "DE",
    "Eurowings": "EW",
    "Norse Atlantic": "N0",
    "Play": "OG",
    "Icelandair": "FI",
    "Turkish Airlines": "TK",
    "Emirates": "EK",
    "Qatar Airways": "QR",
    "Hawaiian Airlines": "HA",
    "Alaska Airlines": "AS",
    "Sun Country": "SY",
    "Volaris": "Y4",
    "VivaAerobus": "VB",
}


def get_airline_code(airline_name):
    """Extrait le code IATA d'une compagnie a partir de son nom."""
    if not airline_name or airline_name == "Inconnue":
        return ""
    # Match exact
    if airline_name in AIRLINE_CODES:
        return AIRLINE_CODES[airline_name]
    # Match partiel (ex: "Air Canada Rouge" -> "Air Canada" -> AC)
    for name, code in AIRLINE_CODES.items():
        if name in airline_name or airline_name in name:
            return code
    return ""


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

    # Charger les deals captures pour ajouter deal_id / reserve_url
    captured_deals = load_deals()

    flights = []
    for r in raw_rows:
        origin, dest = r["origin"], r["dest"]
        depart, retour = r["depart"], r["retour"]
        price_g, price_s = r["price_google"], r["price_skyscanner"]

        # URL Skyscanner
        airline_code = get_airline_code(r["airline"])
        skyscanner_url = build_skyscanner_url({
            "origin": origin, "destination": dest,
            "depart_date": depart, "return_date": retour,
            "airline_code": airline_code,
        })
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

        # deal_id + reserve_url si capture disponible
        deal_id = make_deal_id(origin, dest, depart, retour, airline_code, r["airline"])
        cap = captured_deals.get(deal_id)
        reserve_url = f"/r/{deal_id}" if cap and cap.get("success") else ""

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
            "deal_id": deal_id,
            "reserve_url": reserve_url,
        }
        flights.append(entry)

    # Calculer best_offer par destination (meilleur prix des 3 horizons du dernier scrape)
    best_offers = {}
    if flights:
        by_dest = defaultdict(list)
        for f in flights:
            if f["date"] == last_date:
                by_dest[f["destination"]].append(f)

        for dest, dest_entries in by_dest.items():
            best = min(dest_entries, key=lambda e: e["price"])
            best_offers[dest] = {
                "price": best["price"],
                "price_google": best["price_google"],
                "price_skyscanner": best["price_skyscanner"],
                "best_source": best["best_source"],
                "depart": best["depart"],
                "retour": best["retour"],
                "airline": best["airline"],
                "airline_code": get_airline_code(best["airline"]),
                "stops": best["stops"],
                "score": best["score"],
                "skyscanner_url": best["skyscanner_url"],
                "google_url": best["google_url"],
                "deal_id": best.get("deal_id", ""),
                "reserve_url": best.get("reserve_url", ""),
            }

    entries = ",\n  ".join(json.dumps(f, ensure_ascii=False) for f in flights)
    bo_json = json.dumps(best_offers, ensure_ascii=False)
    js_content = (
        f"const FLIGHT_DATA = [\n  {entries}\n];\n\n"
        f"const BEST_OFFERS = {bo_json};\n\n"
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

    # 2. Analyser et comparer avec l'historique
    print("\n" + "=" * 50)
    print("Analyse des prix")
    print("=" * 50)
    deals = find_deals(results)

    # 3. Capturer les URLs de reservation pour les aubaines >= 30%
    notifiable = [d for d in deals if d.get("discount_pct", 0) >= 30] if deals else []
    if notifiable:
        print(f"\n{len(notifiable)} aubaine(s) >= 30%, capture des URLs...")
        resolve_deals(notifiable, get_airline_code)

    # 4. Regenerer data.js (inclut deal_id + reserve_url si disponibles)
    generate_data_js()

    # 5. Envoyer une alerte si aubaine(s)
    if deals:
        print(f"\n{len(deals)} AUBAINE(S) DETECTEE(S) !")
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
