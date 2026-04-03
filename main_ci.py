"""
MesVols - Pipeline CI (GitHub Actions).
Scrape + generation data.js, sans booking capture ni alertes.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from scraper import run_scraper, HORIZONS, normalize_airline, _ROUTE_CODE_RE
from config import ROUTES
from main import generate_data_js, get_airline_code, DATA_JS_PATH
from analyzer import find_deals, parse_stops, compute_score
from links import build_skyscanner_url, build_search_link

CI_HEALTH_PATH = os.path.join(os.path.dirname(__file__), "ci_health.json")
DEST_CODES = {r[1] for r in ROUTES}

# Seuil minimum de couverture pour publier (50% des resultats attendus)
MIN_COVERAGE_RATIO = 0.50
# Seuil max de lignes Inconnue dans le cycle courant (au-dela, publication bloquee)
MAX_INCONNUE_RATIO = 0.30


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


def validate_data_js(path=DATA_JS_PATH):
    """Valide la structure et la sante de data.js avant publication.
    Retourne (ok, errors, warnings)."""
    errors = []
    warnings = []

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return False, ["data.js introuvable"], []

    # B1: FLIGHT_DATA — parser et valider chaque entree
    m_fd = re.search(r"const FLIGHT_DATA = (\[.+?\]);", content, re.DOTALL)
    flights = []
    if not m_fd:
        errors.append("FLIGHT_DATA absent")
    else:
        try:
            flights = json.loads(m_fd.group(1))
        except json.JSONDecodeError as e:
            errors.append(f"FLIGHT_DATA JSON invalide: {e}")
            return False, errors, warnings
        if not flights:
            errors.append("FLIGHT_DATA vide")
        else:
            fd_required = ("destination", "route", "price", "date")
            bad_records = 0
            for i, entry in enumerate(flights):
                for field in fd_required:
                    if not entry.get(field):
                        bad_records += 1
                        break
                else:
                    p = entry.get("price", 0)
                    if not isinstance(p, (int, float)) or p <= 0:
                        bad_records += 1
            if bad_records > 0:
                errors.append(
                    f"FLIGHT_DATA: {bad_records}/{len(flights)} entrees invalides "
                    f"(champs requis: {', '.join(fd_required)}, price > 0)")

    # B3: LAST_UPDATE valide (lu tot pour la coherence ci-dessous)
    m_upd = re.search(r'const LAST_UPDATE = "(.+?)"', content)
    last_update = ""
    if not m_upd or not m_upd.group(1).strip():
        errors.append("LAST_UPDATE vide ou absent")
    else:
        last_update = m_upd.group(1)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z?", last_update):
            errors.append(f"LAST_UPDATE format invalide: {last_update}")

    # B2: BEST_OFFERS non vide + prix valides
    m_bo = re.search(r"const BEST_OFFERS = ({.*?});", content, re.DOTALL)
    bo = {}
    if not m_bo:
        errors.append("BEST_OFFERS absent")
    else:
        try:
            bo = json.loads(m_bo.group(1))
        except json.JSONDecodeError as e:
            errors.append(f"BEST_OFFERS JSON invalide: {e}")
            return False, errors, warnings

        if not bo:
            errors.append("BEST_OFFERS vide")
        else:
            for dest, info in bo.items():
                price = info.get("price", 0)
                if not isinstance(price, (int, float)) or price <= 0:
                    errors.append(f"BEST_OFFERS[{dest}].price invalide: {price}")

            # Couverture minimale (garde-fou large)
            coverage = len(bo) / len(DEST_CODES) if DEST_CODES else 1
            if coverage < 0.5:
                missing = DEST_CODES - set(bo.keys())
                errors.append(
                    f"BEST_OFFERS couvre {len(bo)}/{len(DEST_CODES)} destinations "
                    f"(manquent: {', '.join(sorted(missing))})")

    # B6: coherence FLIGHT_DATA cycle courant ↔ BEST_OFFERS
    # Meme logique que generate_data_js() : le cycle courant = toutes les lignes
    # consecutives en fin de FLIGHT_DATA dont le prefix horaire ([:13]) correspond
    # au dernier timestamp. Robuste avec des timestamps per-row legacy.
    if flights and bo and last_update:
        last_hour = last_update[:13] if len(last_update) >= 13 else last_update
        last_cycle_dates = set()
        for e in reversed(flights):
            d = e.get("date", "")
            if d[:13] == last_hour:
                last_cycle_dates.add(d)
            else:
                break

        fd_current = [e for e in flights
                      if e.get("date") in last_cycle_dates and e.get("destination")]
        if not fd_current:
            errors.append(
                f"Aucune entree FLIGHT_DATA dans le cycle courant "
                f"(prefix horaire {last_hour})")
        else:
            fd_current_dests = {e["destination"] for e in fd_current}
            bo_dests = set(bo.keys())
            # Sens 1 : FD courant → BO
            missing_in_bo = fd_current_dests - bo_dests
            if missing_in_bo:
                errors.append(
                    f"Destinations dans FLIGHT_DATA courant mais absentes de BEST_OFFERS: "
                    f"{', '.join(sorted(missing_in_bo))}")
            # Sens 2 : BO → FD courant
            missing_in_fd = bo_dests - fd_current_dests
            if missing_in_fd:
                errors.append(
                    f"Destinations dans BEST_OFFERS mais absentes de FLIGHT_DATA courant: "
                    f"{', '.join(sorted(missing_in_fd))}")

    # B7: qualite airline dans BEST_OFFERS
    if bo:
        bad_airlines = []
        for dest, info in bo.items():
            al = info.get("airline", "")
            if not al or al == "Inconnue":
                continue
            if _ROUTE_CODE_RE.match(al.strip()):
                bad_airlines.append(f"{dest}={al}")
            elif al != normalize_airline(al):
                bad_airlines.append(f"{dest}={al}")
        if bad_airlines:
            errors.append(
                f"Airlines non normalisees dans BEST_OFFERS: "
                f"{', '.join(bad_airlines[:5])}")

    # Warnings non-bloquants
    if bo and last_update:
        for dest, info in bo.items():
            d = info.get("date", "")
            if d and d != last_update:
                warnings.append(f"BEST_OFFERS[{dest}].date={d} != LAST_UPDATE={last_update}")
                break
        empty_urls = [d for d, i in bo.items() if not i.get("search_url")]
        if empty_urls:
            warnings.append(f"search_url vide pour: {', '.join(empty_urls)}")

    # W-PRICE: detection prudente de prix aberrants (warning, non bloquant)
    PRICE_FLOOR = 50    # Aucun vol reel < 50 CAD
    PRICE_CEIL = 15000  # Aucun vol eco reel > 15000 CAD
    if bo:
        for dest, info in bo.items():
            p = info.get("price", 0)
            if isinstance(p, (int, float)) and (p < PRICE_FLOOR or p > PRICE_CEIL):
                warnings.append(f"BEST_OFFERS[{dest}].price suspect: {p}$")
    if flights:
        suspect_fd = 0
        for e in flights:
            p = e.get("price", 0)
            if isinstance(p, (int, float)) and (p < PRICE_FLOOR or p > PRICE_CEIL):
                suspect_fd += 1
        if suspect_fd:
            warnings.append(
                f"FLIGHT_DATA: {suspect_fd} prix suspect(s) "
                f"(hors {PRICE_FLOOR}-{PRICE_CEIL}$)")

    return len(errors) == 0, errors, warnings


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
    #    Preferer une compagnie connue meme si un peu plus chere
    by_dest = {}
    for r in results:
        dest = r.get("destination", "")
        price = r.get("price_google", 0)
        if isinstance(price, str):
            price = int(price) if price else 0
        is_known = normalize_airline(r.get("airline", "")) != "Inconnue"

        current = by_dest.get(dest)
        if current is None:
            by_dest[dest] = r
        else:
            cur_price = current.get("price_google", 0)
            if isinstance(cur_price, str):
                cur_price = int(cur_price) if cur_price else 0
            cur_known = normalize_airline(current.get("airline", "")) != "Inconnue"
            # Compagnie connue bat Inconnue ; a status egal, le moins cher gagne
            if (is_known and not cur_known) or (is_known == cur_known and price < cur_price):
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
            "date": r.get("date", ""),
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

    # 4a. Inconnue gate — bloquer si trop de lignes sans compagnie identifiee
    n_inconnue = sum(1 for r in results
                     if normalize_airline(r.get("airline", "")) == "Inconnue")
    if results and n_inconnue / len(results) > MAX_INCONNUE_RATIO:
        _write_health(results, by_dest, deals, "degraded")
        pct = round(n_inconnue / len(results) * 100)
        print(f"\nTrop de lignes Inconnue : {n_inconnue}/{len(results)} "
              f"({pct}% > {int(MAX_INCONNUE_RATIO * 100)}%)")
        print("Publication bloquee. Verifier le scraper.")
        sys.exit(1)

    # 4b. Coverage gate — bloquer la publication si couverture insuffisante
    if coverage < MIN_COVERAGE_RATIO:
        health = _write_health(results, by_dest, deals, "degraded")
        print(f"\nCouverture insuffisante : {len(results)}/{expected} "
              f"({health['coverage_pct']}% < {int(MIN_COVERAGE_RATIO*100)}%)")
        print("Publication bloquee. ci_health.json ecrit avec status=degraded.")
        sys.exit(1)

    # 5. Regenerer data.js (seulement si couverture suffisante)
    generate_data_js(best_offers_current)

    # 6. Valider data.js avant publication
    ok, errs, warns = validate_data_js()
    for w in warns:
        print(f"  WARNING: {w}")
    if not ok:
        for e in errs:
            print(f"  ERROR: {e}")
        _write_health(results, by_dest, deals, "invalid")
        print("\nPublication bloquee : data.js invalide.")
        sys.exit(1)
    print(f"data.js valide ({len(errs)} erreurs, {len(warns)} warnings)")

    # 7. Ecrire ci_health.json
    health = _write_health(results, by_dest, deals, "ok")
    print(f"ci_health.json ecrit ({health['routes_scraped']}/{health['routes_expected']} routes, "
          f"{health['coverage_pct']}%)")

    print("\nPipeline CI termine.")


if __name__ == "__main__":
    main()
