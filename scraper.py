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

            # Compagnie : "Vol avec Air Transat" ou "Vol avec United"
            m = re.search(r"Vol avec ([^,\.]+)", aria)
            if m:
                airline = m.group(1).strip()

            # Escales : "1 escale", "Sans escale", "direct"
            if "sans escale" in aria.lower() or "direct" in aria.lower():
                stops = 0
                stops_text = "Direct"
            else:
                m2 = re.search(r"(\d+)\s*escale", aria.lower())
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
                        and len(line) < 50):
                    airline = line
                    break

        # Fallback escales dans le texte
        if stops == -1:
            row_text = row.text.lower()
            if "sans escale" in row_text:
                stops = 0
                stops_text = "Direct"
            else:
                m3 = re.search(r"(\d+)\s*escale", row_text)
                if m3:
                    stops = int(m3.group(1))
                    stops_text = f"{stops} escale(s)"

        flight["airline"] = airline
        flight["stops"] = stops
        flight["stops_text"] = stops_text
        flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Scraping d'une route
# ---------------------------------------------------------------------------

HORIZONS = [30, 60, 90]  # Jours dans le futur a scraper


def scrape_route(driver, origin, destination, route_name):
    """Scrape le prix le moins cher pour une route sur plusieurs horizons (30/60/90 jours)."""
    all_results = []

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
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
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

def run_scraper():
    """Lance le scraping de toutes les routes."""
    # Migration CSV si ancien format
    _migrate_csv()

    print("=" * 60)
    print(f"Scraping Google Flights - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{len(ROUTES)} routes a verifier")
    print("=" * 60)

    driver = get_driver()
    all_results = []
    errors = []

    try:
        for origin, destination, name in ROUTES:
            try:
                results = scrape_route(driver, origin, destination, name)
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

    print(f"{len(all_results)}/{len(ROUTES)} routes scrapees avec succes")
    return all_results


if __name__ == "__main__":
    run_scraper()
