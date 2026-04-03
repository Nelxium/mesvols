"""
Scraper Google Flights avec Selenium.
Recupere les prix de vols aller-retour au depart de Montreal.
Utilise les URLs directes Google Flights avec parametre tfs (protobuf encode).
"""

import base64
import csv
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

from config import ROUTES

CSV_FILE = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
CSV_FIELDNAMES = ["date", "route", "origin", "destination",
                  "price_google", "price_skyscanner",
                  "airline", "escales", "depart", "retour", "booking_url"]


def get_driver(stealth=False):
    """Lance Chrome en mode headless. stealth=True utilise undetected-chromedriver."""
    if stealth and HAS_UC:
        uc_opts = uc.ChromeOptions()
        uc_opts.add_argument("--headless=new")
        uc_opts.add_argument("--no-sandbox")
        uc_opts.add_argument("--disable-dev-shm-usage")
        uc_opts.add_argument("--disable-gpu")
        uc_opts.add_argument("--window-size=1920,1080")
        uc_opts.add_argument("--lang=fr")
        driver = uc.Chrome(options=uc_opts, headless=True)
        return driver

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=fr")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


# ---------------------------------------------------------------------------
# Migration CSV : price_cad -> price_google + price_skyscanner
# ---------------------------------------------------------------------------

def _migrate_csv():
    """Migre le CSV ancien format (price_cad) vers price_google/price_skyscanner."""
    if not os.path.isfile(CSV_FILE):
        return
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        first_line = f.readline()
    if "price_google" in first_line:
        return  # deja migre
    if "price_cad" not in first_line and "date" not in first_line:
        return

    rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip old header
        for row in reader:
            if not row:
                continue
            n = len(row)
            if n >= 9:
                d, route, orig, dest, price = row[0], row[1], row[2], row[3], row[4]
                airline, escales, dep, ret = row[5], row[6], row[7], row[8]
                burl = row[9] if n >= 10 else ""
            elif n == 8:
                d, route, orig, dest, price = row[0], row[1], row[2], row[3], row[4]
                airline, dep, ret = row[5], row[6], row[7]
                escales, burl = "", ""
            else:
                continue
            rows.append({"date": d, "route": route, "origin": orig,
                         "destination": dest, "price_google": price,
                         "price_skyscanner": "", "airline": airline,
                         "escales": escales, "depart": dep, "retour": ret,
                         "booking_url": burl})

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV migre vers nouveau format ({len(rows)} lignes)")


# ---------------------------------------------------------------------------
# Construction de l'URL Google Flights via protobuf encode (tfs=)
# ---------------------------------------------------------------------------

def _build_segment(origin, dest, date_str):
    """Construit un segment protobuf (une jambe du vol)."""
    origin_b = origin.encode()
    dest_b = dest.encode()
    date_b = date_str.encode()

    # field 13 (aeroport depart) : tag 0x6a, inner: field1=varint1, field2=string(code)
    f13_inner = b"\x08\x01\x12" + bytes([len(origin_b)]) + origin_b
    f13 = b"\x6a" + bytes([len(f13_inner)]) + f13_inner

    # field 2 (date) : tag 0x12
    f2 = b"\x12" + bytes([len(date_b)]) + date_b

    # field 14 (aeroport arrivee) : tag 0x72, meme structure
    f14_inner = b"\x08\x01\x12" + bytes([len(dest_b)]) + dest_b
    f14 = b"\x72" + bytes([len(f14_inner)]) + f14_inner

    return f13 + f2 + f14


def build_flights_url(origin, dest, depart_date, return_date=None):
    """
    Construit l'URL Google Flights avec le parametre tfs encode en protobuf/base64.
    Supporte aller simple et aller-retour.
    """
    d_str = depart_date.strftime("%Y-%m-%d")
    seg1 = _build_segment(origin, dest, d_str)
    leg1 = b"\x1a" + bytes([len(seg1)]) + seg1

    if return_date:
        r_str = return_date.strftime("%Y-%m-%d")
        seg2 = _build_segment(dest, origin, r_str)
        leg2 = b"\x1a" + bytes([len(seg2)]) + seg2
        header = b"\x08\x1c\x10\x02"  # round trip (2 legs)
        payload = header + leg1 + leg2
    else:
        header = b"\x08\x1c\x10\x02"  # one way (1 leg)
        payload = header + leg1

    tfs = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=CAD&hl=fr&gl=CA"


# ---------------------------------------------------------------------------
# Extraction des prix depuis un texte
# ---------------------------------------------------------------------------

def extract_price(text):
    """Extrait un prix depuis '824 $CA', '1 060 $CA', '$719', etc."""
    cleaned = text.replace("\xa0", " ").replace("\u202f", " ")
    match = re.search(r"(\d[\d\s]*)\s*\$", cleaned)
    if match:
        digits = match.group(1).replace(" ", "")
        return int(digits)
    match = re.search(r"\$\s*(\d[\d\s]*)", cleaned)
    if match:
        digits = match.group(1).replace(" ", "")
        return int(digits)
    return None


# ---------------------------------------------------------------------------
# Normalisation du nom de compagnie
# ---------------------------------------------------------------------------

# Compagnies connues (ordre decroissant de longueur pour match greedy)
KNOWN_AIRLINES = [
    "Air Canada Rouge", "Air Canada Express", "Air Canada",
    "Air Transat", "Air France",
    "Porter Airlines", "Alaska Airlines", "Hawaiian Airlines",
    "Turkish Airlines", "Sun Country", "Norse Atlantic",
    "TAP Portugal", "ITA Airways", "British Airways",
    "Qatar Airways",
    "WestJet", "United", "Delta", "American", "JetBlue",
    "Spirit", "Frontier", "Southwest", "Lufthansa", "KLM",
    "Swiss", "Iberia", "Alitalia", "Aegean", "Copa",
    "Aeromexico", "Sunwing", "Condor", "Eurowings", "Play",
    "Icelandair", "Emirates", "Volaris", "VivaAerobus",
    "Flair", "Lynx", "Arajet", "Avianca", "ANA", "JAL",
]

# Regex route codes (ex: YUL–JFK, YUL-CDG)
_ROUTE_CODE_RE = re.compile(r"^[A-Z]{3}\s*[–\-]\s*[A-Z]{3}$")


def normalize_airline(raw):
    """Normalise un nom de compagnie brut extrait du scraping.

    Gere les cas :
    - concatenation sans separateur : "Air FranceDelta" -> "Air France"
    - texte parasite : "Air CanadaVol opéré par ..." -> "Air Canada"
    - code de route : "YUL–JFK" -> "Inconnue"
    - multi-carriers propres : "Qatar Airways et JAL" -> "Qatar Airways"
    - noms propres : "Air Canada" -> "Air Canada" (inchange)

    Regle : retourner la premiere compagnie connue trouvee dans le texte,
    ou le texte original nettoye si aucune compagnie connue n'est trouvee.
    """
    if not raw or raw == "Inconnue":
        return "Inconnue"

    # Rejeter les codes de route et labels parasites Google Flights
    if _ROUTE_CODE_RE.match(raw.strip()):
        return "Inconnue"
    if "mission" in raw.lower():  # "Émissions hab.", "Émissions habituelles"
        return "Inconnue"
    low = raw.strip().lower()
    if low in ("aller-retour", "aller", "retour", "round trip", "one way"):
        return "Inconnue"

    # Chercher la compagnie connue qui apparait le plus tot dans le texte brut
    best_match = None
    best_pos = len(raw) + 1
    for name in KNOWN_AIRLINES:
        pos = raw.find(name)
        if pos != -1 and pos < best_pos:
            best_pos = pos
            best_match = name
    if best_match:
        return best_match

    # Nettoyer les prefixes/suffixes parasites
    cleaned = raw.strip()
    # Couper a "Vol opéré" ou "Operated by"
    for sep in ("Vol opéré", "Operated by", "operated by"):
        if sep in cleaned:
            cleaned = cleaned[:cleaned.index(sep)].strip()
    # Couper a "et " pour multi-carriers non reconnus
    if " et " in cleaned:
        cleaned = cleaned[:cleaned.index(" et ")].strip()

    return cleaned if cleaned and len(cleaned) > 1 else "Inconnue"


# ---------------------------------------------------------------------------
# Parsing des resultats de vol
# ---------------------------------------------------------------------------

def parse_flight_results(driver):
    """
    Parse les resultats Google Flights.
    Utilise les li.pIav2d (lignes de vol) et les aria-label de .JMc5Xc.
    """
    flights = []

    # Chaque ligne de vol est un li.pIav2d
    rows = driver.find_elements(By.CSS_SELECTOR, "li.pIav2d")
    if not rows:
        # Fallback : essayer d'autres selecteurs
        rows = driver.find_elements(By.CSS_SELECTOR, ".yR1fYc, .OgQvJf")

    for row in rows:
        flight = {}

        # --- Prix ---
        # Chercher dans les spans avec classe YMlIz FpEdX (prix standard)
        # ou hXU5Ud (prix mis en avant)
        price = None
        price_els = row.find_elements(By.CSS_SELECTOR, ".YMlIz span, .hXU5Ud, .FpEdX span")
        for pel in price_els:
            p = extract_price(pel.text)
            if p and 50 < p < 50000:
                price = p
                break

        if not price:
            # Fallback : chercher $ dans tout le texte de la ligne
            p = extract_price(row.text)
            if p and 50 < p < 50000:
                price = p

        if not price:
            continue

        flight["price"] = price

        # --- Compagnie et escales via aria-label ---
        airline = "Inconnue"
        stops_text = "Inconnu"
        stops = -1

        # Le div.JMc5Xc contient un aria-label tres detaille
        info_els = row.find_elements(By.CSS_SELECTOR, ".JMc5Xc, [class*='JMc5Xc']")
        for info_el in info_els:
            aria = info_el.get_attribute("aria-label") or ""
            if not aria:
                continue

            # Compagnie : "Vol avec X" / "Vols avec X" / "Flights with X"
            m = re.search(r"(?:Vols? avec|Flights? with)\s+([^,\.]+)", aria, re.IGNORECASE)
            if m:
                airline = m.group(1).strip()
            else:
                # Second chance : chercher une compagnie connue dans l'aria-label
                for known in KNOWN_AIRLINES:
                    if known in aria:
                        airline = known
                        break

            # Escales : "Sans escale" / "direct" / "nonstop" / "non-stop" / "N escale(s)" / "N stop(s)"
            aria_low = aria.lower()
            if ("sans escale" in aria_low or "direct" in aria_low
                    or "nonstop" in aria_low or "non-stop" in aria_low):
                stops = 0
                stops_text = "Direct"
            else:
                m2 = re.search(r"(\d+)\s*(?:escales?|stops?)", aria_low)
                if m2:
                    stops = int(m2.group(1))
                    stops_text = f"{stops} escale(s)"
            break

        # Fallback compagnie : chercher dans le texte de la ligne
        if airline == "Inconnue":
            row_text = row.text
            lines = [l.strip() for l in row_text.split("\n") if l.strip()]
            for line in lines:
                # Les lignes de compagnie n'ont pas de $, pas de h, pas de chiffres au debut
                if (line and len(line) > 2 and "$" not in line
                        and not re.match(r"^\d", line) and ":" not in line
                        and "escale" not in line.lower() and "kg" not in line.lower()
                        and "min" not in line.lower() and "CO2" not in line
                        and "mission" not in line.lower()
                        and "aller" not in line.lower()
                        and "retour" not in line.lower()
                        and not _ROUTE_CODE_RE.match(line)
                        and len(line) < 50):
                    airline = line
                    break

        # Fallback escales dans le texte
        if stops == -1:
            row_text = row.text.lower()
            if ("sans escale" in row_text or "direct" in row_text
                    or "nonstop" in row_text or "non-stop" in row_text):
                stops = 0
                stops_text = "Direct"
            else:
                m3 = re.search(r"(\d+)\s*(?:escales?|stops?)", row_text)
                if m3:
                    stops = int(m3.group(1))
                    stops_text = f"{stops} escale(s)"

        flight["airline"] = normalize_airline(airline)
        flight["stops"] = stops
        flight["stops_text"] = stops_text
        flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Scraping d'une route
# ---------------------------------------------------------------------------

HORIZONS = [30, 60, 90]  # Jours dans le futur a scraper


def scrape_route(driver, origin, destination, route_name, run_ts=None):
    """Scrape le prix le moins cher pour une route sur plusieurs horizons (30/60/90 jours).
    run_ts: timestamp unique du cycle (partage entre toutes les routes)."""
    all_results = []
    if run_ts is None:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    MTL = ZoneInfo("America/Montreal")
    for days_ahead in HORIZONS:
        depart = datetime.now(MTL) + timedelta(days=days_ahead)
        retour = depart + timedelta(days=7)
        d_str = depart.strftime("%Y-%m-%d")
        r_str = retour.strftime("%Y-%m-%d")

        url = build_flights_url(origin, destination, depart, retour)
        label = f"{route_name} (J+{days_ahead})"
        print(f"  {label} ...")

        try:
            driver.get(url)
            time.sleep(7)

            flights = parse_flight_results(driver)

            if not flights:
                print(f"    -> Aucun prix trouve")
                if days_ahead == HORIZONS[0]:
                    driver.save_screenshot(
                        os.path.join(os.path.dirname(__file__),
                                     f"debug_noresult_{origin}_{destination}.png"))
                continue

            best = min(flights, key=lambda f: f["price"])

            esc = f", {best['stops_text']}" if best["stops_text"] != "Inconnu" else ""
            print(f"    -> {best['price']} $CA ({best['airline']}{esc})"
                  f"  [{len(flights)} vols trouves]")

            booking_url = (f"https://www.google.com/travel/flights"
                           f"?q=flights+from+{origin}+to+{destination}"
                           f"+on+{d_str}+return+{r_str}")

            all_results.append({
                "date": run_ts,
                "route": route_name,
                "origin": origin,
                "destination": destination,
                "price_google": best["price"],
                "price_skyscanner": "",
                "airline": best["airline"],
                "escales": best["stops_text"],
                "depart": d_str,
                "retour": r_str,
                "booking_url": booking_url,
            })

        except Exception as e:
            print(f"    -> ERREUR ({label}): {e}")
            traceback.print_exc()

        time.sleep(2)

    return all_results


# ---------------------------------------------------------------------------
# Sauvegarde CSV
# ---------------------------------------------------------------------------

def save_to_csv(results):
    """Ajoute les resultats au fichier CSV (nouveau format avec price_google/price_skyscanner)."""
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"\n{len(results)} resultat(s) sauvegarde(s) dans {CSV_FILE}")


# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------

def _resolve_routes(routes_subset=None):
    """Valide et resout un sous-ensemble de routes.

    Accepte des tuples (origin, dest) ou (origin, dest, name).
    Les routes inconnues sont ignorees avec un warning.
    Si routes_subset est None, retourne toutes les ROUTES.
    """
    if routes_subset is None:
        return list(ROUTES)
    routes_by_key = {(o, d): (o, d, n) for o, d, n in ROUTES}
    resolved = []
    for r in routes_subset:
        key = (r[0], r[1])
        if key in routes_by_key:
            resolved.append(routes_by_key[key])
        else:
            print(f"  WARNING: route inconnue ignoree: {r}")
    return resolved


def run_scraper(routes_subset=None):
    """Lance le scraping des routes demandees (toutes par defaut).

    Args:
        routes_subset: liste de tuples (origin, dest) ou (origin, dest, name).
                       Si None, scrape toutes les routes de config.ROUTES.
    """
    # Migration CSV si ancien format
    _migrate_csv()

    routes = _resolve_routes(routes_subset)

    print("=" * 60)
    print(f"Scraping Google Flights - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{len(routes)} routes a verifier"
          + (f" (sous-ensemble de {len(ROUTES)})" if routes_subset is not None else ""))
    print("=" * 60)

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    driver = get_driver()
    all_results = []
    errors = []

    try:
        for origin, destination, name in routes:
            try:
                results = scrape_route(driver, origin, destination, name, run_ts)
                all_results.extend(results)
            except Exception as e:
                print(f"    -> ERREUR CRITIQUE {name}: {e}")
                errors.append(name)
            time.sleep(3)

    finally:
        driver.quit()

    if all_results:
        save_to_csv(all_results)

    if errors:
        print(f"\n{len(errors)} route(s) en erreur : {', '.join(errors)}")

    routes_ok = len(routes) - len(errors)
    print(f"{routes_ok}/{len(routes)} route(s) scrapee(s) avec succes, "
          f"{len(all_results)} resultat(s)")
    return all_results


if __name__ == "__main__":
    run_scraper()
