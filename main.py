"""
MesVols - Detecteur de vols pas chers
Point d'entree principal : scrape, analyse et alerte.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

from scraper import run_scraper
from analyzer import find_deals, parse_stops, compute_score
from notifier import send_deal_alert
from links import build_skyscanner_url
from booking_capture import make_deal_id, load_deals, resolve_deals
from config import BASE_URL

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


def generate_data_js(best_offers_current=None):
    """Regenere data.js a partir de prix_vols.csv (supporte ancien et nouveau format).
    best_offers_current : dict {dest: {...}} calcule depuis les resultats du cycle courant.
    Si fourni, utilise comme BEST_OFFERS au lieu de recalculer depuis le CSV."""
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
        reserve_url = BASE_URL + "/r/" + deal_id if cap and cap.get("success") else ""

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
            "final_domain": cap.get("final_domain", "") if cap and cap.get("success") else "",
        }
        flights.append(entry)

    # BEST_OFFERS : utiliser le calcul du cycle courant si fourni
    best_offers = best_offers_current if best_offers_current else {}

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


HEALTH_PATH = os.path.join(os.path.dirname(__file__), "health.json")


def _write_health(cycle_report, candidates_total):
    """Ecrit health.json apres chaque cycle."""
    health = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "capture": {
            "candidates_total": candidates_total,
            "eligible_total": 0,
            "planned_total": 0,
            "attempted_total": 0,
            "success_total": 0,
            "failed_total": 0,
            "skipped_fresh_total": 0,
            "skipped_backoff_total": 0,
            "consecutive_fail_stop_triggered": False,
        },
        "errors_by_code": {},
        "attempts": [],
    }
    if cycle_report:
        health["capture"].update({
            k: cycle_report[k] for k in health["capture"] if k in cycle_report
        })
        health["errors_by_code"] = cycle_report.get("errors_by_code", {})
        health["attempts"] = cycle_report.get("attempts", [])

    try:
        with open(HEALTH_PATH, "w", encoding="utf-8") as f:
            json.dump(health, f, ensure_ascii=False, indent=2)
        print(f"health.json ecrit ({health['capture']['attempted_total']} tentatives)")
    except Exception as e:
        print(f"Erreur ecriture health.json: {e}")


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

    # 3. Construire la liste unique de candidats a la capture
    #    Priorite 1 : best_offer par destination (depuis les resultats du cycle)
    #    Priorite 2 : deals >= 30% non deja couverts
    candidates = []
    seen = set()  # (origin, destination, depart, retour)

    # 3a. Best offers du cycle courant (prix le plus bas par destination)
    by_dest = {}
    for r in results:
        dest = r.get("destination", "")
        price = r.get("price_google", 0)
        if isinstance(price, str):
            price = int(price) if price else 0
        if dest not in by_dest or price < by_dest[dest].get("price_google", 0):
            by_dest[dest] = r

    # Construire best_offers_current pour data.js (source de verite unique)
    captured_deals = load_deals()
    best_offers_current = {}

    for dest, r in by_dest.items():
        stops_text = r.get("escales", "")
        num_stops = parse_stops(stops_text)
        airline_code = get_airline_code(r.get("airline", ""))
        deal_id = make_deal_id(r["origin"], dest, r["depart"], r["retour"],
                               airline_code, r.get("airline", ""))
        cap = captured_deals.get(deal_id)
        reserve_url = BASE_URL + "/r/" + deal_id if cap and cap.get("success") else ""
        sky_url = build_skyscanner_url({
            "origin": r["origin"], "destination": dest,
            "depart_date": r["depart"], "return_date": r["retour"],
        })
        google_url = (f"https://www.google.com/travel/flights"
                      f"?q=flights+from+{r['origin']}+to+{dest}"
                      f"+on+{r['depart']}+return+{r['retour']}")

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
            "deal_id": deal_id,
            "reserve_url": reserve_url,
            "final_domain": cap.get("final_domain", "") if cap and cap.get("success") else "",
        }

        key = (r["origin"], r["destination"], r["depart"], r["retour"])
        seen.add(key)
        candidates.append({
            "origin": r["origin"],
            "destination": r["destination"],
            "depart": r["depart"],
            "retour": r["retour"],
            "price": r["price_google"],
            "airline": r.get("airline", ""),
            "stops": stops_text,
            "num_stops": num_stops,
        })

    # 3b. Deals >= 30% non deja couverts
    notifiable = [d for d in deals if d.get("discount_pct", 0) >= 30] if deals else []
    for d in notifiable:
        key = (d.get("origin", ""), d.get("destination", ""), d.get("depart", ""), d.get("retour", ""))
        if key not in seen:
            seen.add(key)
            candidates.append(d)

    cycle_report = None
    if candidates:
        print(f"\n{len(candidates)} candidat(s) a la capture ({len(by_dest)} best_offer + {len(notifiable)} deal(s) >= 30%)")
        _, cycle_report = resolve_deals(candidates, get_airline_code)

    # 4. Regenerer data.js (inclut deal_id + reserve_url si disponibles)
    generate_data_js(best_offers_current)

    # 4b. Ecrire health.json
    _write_health(cycle_report, len(candidates))

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
    try:
        main()
    except Exception as exc:
        # Alerte Discord en cas de crash complet
        try:
            from urllib.request import Request, urlopen
            from config import DISCORD_WEBHOOK_URL
            if DISCORD_WEBHOOK_URL:
                payload = json.dumps({
                    "embeds": [{
                        "title": "MesVols - CRASH",
                        "description": f"**{type(exc).__name__}**: {exc}",
                        "color": 0xe11d48,
                        "footer": {"text": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                    }]
                }).encode("utf-8")
                req = Request(DISCORD_WEBHOOK_URL, data=payload, method="POST")
                req.add_header("Content-Type", "application/json")
                urlopen(req)
        except Exception as discord_err:
            print(f"Erreur envoi alerte Discord: {discord_err}")
        raise
