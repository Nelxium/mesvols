"""
Module partage de capture d'URLs de reservation via Google Flights.
Reutilise la logique du prototype test_capture_booking_url.py.

Flow : resultats aller -> selection vol aller -> resultats retour ->
       selection vol retour -> ecran offres partenaires -> clic offre -> capture.
"""

import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from scraper import build_flights_url

DEALS_PATH = os.path.join(os.path.dirname(__file__), "deals.json")
MAX_CAPTURES_PER_CYCLE = 5
FRESHNESS_MINUTES = 30

GOOGLE_DOMAINS = {
    "google.com", "google.ca", "google.fr", "googleapis.com",
    "gstatic.com", "googleusercontent.com", "googlesyndication.com",
    "googleadservices.com", "doubleclick.net", "google-analytics.com",
    "googletagmanager.com", "youtube.com",
}


# ── deal_id + persistence ────────────────────────────────────────────────

def make_deal_id(origin, dest, depart, retour, airline_code="", airline=""):
    """Genere un deal_id stable et URL-safe.  Ex: YUL-CDG-20260531-20260607-TS"""
    code = airline_code or re.sub(r"\W+", "", airline)[:10]
    dep = depart.replace("-", "")
    ret = retour.replace("-", "")
    return f"{origin}-{dest}-{dep}-{ret}-{code}"


def load_deals():
    """Charge deals.json. Retourne {} si absent ou invalide."""
    try:
        with open(DEALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_deals(deals):
    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)


def is_fresh(deal, minutes=FRESHNESS_MINUTES):
    """Verifie si un deal capture est encore frais (< minutes)."""
    captured_at = deal.get("captured_at", "")
    if not captured_at:
        return False
    try:
        ts = datetime.strptime(captured_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() < minutes * 60
    except ValueError:
        return False


# ── Selenium helpers ─────────────────────────────────────────────────────

def _get_capture_driver():
    """Chrome headless avec CDP performance logs actifs."""
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
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def _is_google(url):
    try:
        host = urlparse(url).hostname or ""
        return any(host.endswith(d) for d in GOOGLE_DOMAINS)
    except Exception:
        return True


def _get_domain(url):
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _flush_logs(driver):
    try:
        driver.get_log("performance")
    except Exception:
        pass


def _dismiss_consent(driver):
    for sel in [
        "button[aria-label*='Tout accepter']",
        "button[aria-label*='Accept all']",
        "form[action*='consent'] button",
    ]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if any(w in btn.text.lower() for w in ["accept", "tout", "ok"]):
                    btn.click()
                    time.sleep(1)
                    return
        except Exception:
            continue


def _click_first_flight(driver):
    """Clique sur la premiere ligne de vol visible. Retourne True si OK."""
    rows = driver.find_elements(By.CSS_SELECTOR, "li.pIav2d")
    if not rows:
        rows = driver.find_elements(By.CSS_SELECTOR, ".yR1fYc, .OgQvJf")
    if not rows:
        return False
    try:
        rows[0].click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", rows[0])
        except Exception:
            return False
    time.sleep(4)
    return True


def _try_select_button(driver):
    """Cherche et clique sur un bouton 'Selectionner' si present."""
    for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
        txt = btn.text.lower().strip()
        if any(w in txt for w in ["sélectionner", "selectionner", "select"]):
            btn.click()
            time.sleep(4)
            return True
    return False


def _find_booking_offers(driver):
    """Detecte les offres 'Reserver avec <partenaire>' sur l'ecran final."""
    offers = []
    try:
        containers = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), 'server avec') or contains(text(), 'Book with') "
            "or contains(text(), 'Book on')]"
        )
    except Exception:
        return offers

    for el in containers:
        try:
            container = el
            for _ in range(6):
                parent = container.find_element(By.XPATH, "./..")
                if "$" in parent.text.strip():
                    container = parent
                    if "continuer" in parent.text.lower() or "continue" in parent.text.lower():
                        break
                container = parent

            text = container.text.strip()
            if "$" not in text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            name = ""
            for line in lines:
                m = re.search(r"[Rr][eé]server avec (.+)", line)
                if not m:
                    m = re.search(r"Book (?:with|on) (.+)", line)
                if m:
                    name = m.group(1).strip()
                    break
            if not name or any(o["name"] == name for o in offers):
                continue

            price = next((l for l in lines if "$" in l), "")

            clickable = None
            for btn in container.find_elements(By.CSS_SELECTOR, "a[href], button"):
                if any(w in btn.text.lower() for w in
                       ["continuer", "continue", "select", "réserver", "book"]):
                    clickable = btn
                    break
            if not clickable:
                clickable = container

            offers.append({"name": name, "price": price, "element": clickable})
        except Exception:
            continue

    return offers


# ── Capture principale ───────────────────────────────────────────────────

def capture_booking_url(origin, dest, depart_str, retour_str):
    """
    Parcourt le flow complet Google Flights et capture l'URL de reservation.
    Retourne {success, final_url, final_domain, partner_clicked, error}.
    """
    result = {
        "success": False, "final_url": "", "final_domain": "",
        "partner_clicked": "", "error": "",
    }

    depart = datetime.strptime(depart_str, "%Y-%m-%d")
    retour = datetime.strptime(retour_str, "%Y-%m-%d")
    url = build_flights_url(origin, dest, depart, retour)

    driver = None
    try:
        driver = _get_capture_driver()
        driver.get(url)
        time.sleep(6)

        # Consentement cookies
        if "consent" in driver.current_url.lower():
            _dismiss_consent(driver)
            time.sleep(2)
            if "consent" in driver.current_url.lower():
                driver.get(url)
                time.sleep(6)
        _dismiss_consent(driver)

        # Etape 1-2 : Selection vol aller
        url_before = driver.current_url
        if not _click_first_flight(driver):
            result["error"] = "Aucun vol aller"
            return result
        if driver.current_url == url_before:
            _try_select_button(driver)

        # Etape 3-4 : Selection vol retour
        url_before = driver.current_url
        if _click_first_flight(driver):
            if driver.current_url == url_before:
                _try_select_button(driver)
        time.sleep(3)

        # Etape 5 : Offres de reservation
        offers = _find_booking_offers(driver)
        if not offers:
            result["error"] = "Aucune offre partenaire"
            return result

        # Etape 6 : Clic sur la premiere offre
        offer = offers[0]
        result["partner_clicked"] = offer["name"]
        original_handles = set(driver.window_handles)
        _flush_logs(driver)

        try:
            offer["element"].click()
        except Exception:
            driver.execute_script("arguments[0].click();", offer["element"])
        time.sleep(10)

        # Verifier nouvel onglet
        new_handles = set(driver.window_handles) - original_handles
        if new_handles:
            driver.switch_to.window(new_handles.pop())
            time.sleep(3)

        current_url = driver.current_url
        if not _is_google(current_url) and "google" not in current_url.lower():
            result["final_url"] = current_url
            result["final_domain"] = _get_domain(current_url)
            result["success"] = True
        else:
            result["error"] = "Pas de redirection hors Google"

    except Exception as e:
        result["error"] = str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return result


# ── Resolveur de deals ───────────────────────────────────────────────────

def resolve_deals(deals_list, get_airline_code_fn=None):
    """
    Pour une liste de deals (aubaines 30%+), capture les URLs de reservation.
    Max MAX_CAPTURES_PER_CYCLE par cycle. Ne recapture pas les deals frais.
    Retourne le dict deals mis a jour.
    """
    stored = load_deals()
    captured = 0

    for deal in deals_list:
        if captured >= MAX_CAPTURES_PER_CYCLE:
            print(f"  [Capture] Limite de {MAX_CAPTURES_PER_CYCLE} captures atteinte")
            break

        origin = deal.get("origin", "")
        dest = deal.get("destination", "")
        depart = deal.get("depart", "")
        retour = deal.get("retour", "")
        airline = deal.get("airline", "")
        airline_code = get_airline_code_fn(airline) if get_airline_code_fn else ""

        deal_id = make_deal_id(origin, dest, depart, retour, airline_code, airline)

        # Skip si lien frais existant
        if deal_id in stored and stored[deal_id].get("success") and is_fresh(stored[deal_id]):
            print(f"  [Capture] {deal_id}: lien frais, skip")
            continue

        print(f"  [Capture] {deal_id}: demarrage...")
        cap = capture_booking_url(origin, dest, depart, retour)

        stored[deal_id] = {
            "deal_id": deal_id,
            "origin": origin,
            "destination": dest,
            "depart": depart,
            "retour": retour,
            "airline": airline,
            "airline_code": airline_code,
            "partner_clicked": cap["partner_clicked"],
            "final_url": cap["final_url"],
            "final_domain": cap["final_domain"],
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "success": cap["success"],
        }
        captured += 1

        tag = "OK" if cap["success"] else "ECHEC"
        print(f"  [Capture] {deal_id}: {tag} -> {cap['final_domain'] or cap['error']}")

    save_deals(stored)
    return stored
