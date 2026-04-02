"""
Module partage de capture d'URLs de reservation via Google Flights.
Reutilise la logique du prototype test_capture_booking_url.py.

Flow : resultats aller -> selection vol aller -> resultats retour ->
       selection vol retour -> ecran offres partenaires -> clic offre -> capture.
"""

import hashlib
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
MAX_CAPTURES_PER_CYCLE = 3
FRESHNESS_MINUTES = 30   # Pour servir les liens via /r/ (server.py)
RECAPTURE_MINUTES = 75   # Pour decider de relancer une capture

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


# ── Priorite / hash / backoff ────────────────────────────────────────────

def compute_offer_hash(deal):
    """Hash stable des champs cles du best_offer (inclut stops)."""
    key = ":".join(str(x) for x in [
        deal.get("origin", ""),
        deal.get("destination", ""),
        deal.get("depart", ""),
        deal.get("retour", ""),
        deal.get("price", ""),
        deal.get("airline", ""),
        deal.get("num_stops", deal.get("stops", "")),
    ])
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _age_minutes(timestamp_str):
    """Age en minutes d'un timestamp YYYY-MM-DD HH:MM:SS. None si invalide."""
    if not timestamp_str:
        return None
    try:
        ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() / 60
    except ValueError:
        return None


def _backoff_minutes(fail_count):
    """Backoff exponentiel : 10, 20, 40, 80, max 120 min."""
    if fail_count <= 0:
        return 0
    return min(10 * (2 ** (fail_count - 1)), 120)


def _make_snapshot(deal):
    """Snapshot lisible du best_offer pour debug dans deals.json."""
    return {
        "price": deal.get("price"),
        "stops": deal.get("num_stops", deal.get("stops", "")),
        "depart": deal.get("depart", ""),
        "retour": deal.get("retour", ""),
        "airline": deal.get("airline", ""),
        "airline_code": deal.get("_airline_code", ""),
    }


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
    Retourne un dict avec succes/erreur + observabilite par etape.
    """
    t0 = time.time()
    result = {
        "success": False, "final_url": "", "final_domain": "",
        "partner_clicked": "", "error": "",
        # Observabilite
        "stage": "INIT",
        "error_code": "",
        "error_detail": "",
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": "",
        "duration_ms": 0,
    }

    def _finish(success=False, stage=None, error_code="", error_detail=""):
        if stage:
            result["stage"] = stage
        if error_code:
            result["error_code"] = error_code
            result["error_detail"] = error_detail or result.get("error", "")
        result["success"] = success
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result["duration_ms"] = int((time.time() - t0) * 1000)
        return result

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
        result["stage"] = "PAGE_LOADED"

        # Etape 1-2 : Selection vol aller
        url_before = driver.current_url
        if not _click_first_flight(driver):
            result["error"] = "Aucun vol aller"
            return _finish(stage="PAGE_LOADED", error_code="OUTBOUND_NOT_FOUND")
        if driver.current_url == url_before:
            _try_select_button(driver)
        result["stage"] = "OUTBOUND_SELECTED"

        # Etape 3-4 : Selection vol retour
        url_before = driver.current_url
        if _click_first_flight(driver):
            if driver.current_url == url_before:
                _try_select_button(driver)
            result["stage"] = "RETURN_SELECTED"
        else:
            result["stage"] = "RETURN_SELECTED"  # peut-etre deja sur l'ecran offres
        time.sleep(3)

        # Etape 5 : Offres de reservation
        offers = _find_booking_offers(driver)
        if not offers:
            result["error"] = "Aucune offre partenaire"
            return _finish(stage="RETURN_SELECTED", error_code="NO_PARTNER_OFFERS")
        result["stage"] = "OFFERS_FOUND"

        # Etape 6 : Clic sur la premiere offre
        offer = offers[0]
        result["partner_clicked"] = offer["name"]
        original_handles = set(driver.window_handles)
        _flush_logs(driver)

        try:
            offer["element"].click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", offer["element"])
            except Exception as click_err:
                result["error"] = str(click_err)
                return _finish(stage="OFFERS_FOUND", error_code="PARTNER_CLICK_FAILED",
                               error_detail=str(click_err))
        result["stage"] = "PARTNER_CLICKED"
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
            return _finish(success=True, stage="EXTERNAL_REDIRECT")
        else:
            result["error"] = "Pas de redirection hors Google"
            return _finish(stage="PARTNER_CLICKED", error_code="NO_EXTERNAL_REDIRECT")

    except Exception as e:
        result["error"] = str(e)
        return _finish(error_code="WEBDRIVER_ERROR", error_detail=str(e))
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ── Resolveur de deals (capture incrementale) ────────────────────────────

def resolve_deals(deals_list, get_airline_code_fn=None):
    """
    Capture incrementale des URLs de reservation pour les aubaines >= 30%.

    Systeme de priorite :
      P100 — jamais capture (deal_id absent de deals.json)
      P90  — offer_hash a change (prix/dates/compagnie/stops differents)
      P50  — capture expiree (> RECAPTURE_MINUTES) et derniere capture reussie
      P30  — derniere capture echouee et backoff ecoule
      Skip — capture fraiche + hash identique, ou en periode de backoff

    Max MAX_CAPTURES_PER_CYCLE par cycle.
    Arret anticipe si 3 echecs consecutifs dans le meme cycle.

    Retourne (stored_deals, cycle_report).
    """
    stored = load_deals()

    # Compteurs pour le rapport
    report = {
        "candidates_total": len(deals_list),
        "eligible_total": 0,
        "planned_total": 0,
        "attempted_total": 0,
        "success_total": 0,
        "failed_total": 0,
        "skipped_fresh_total": 0,
        "skipped_backoff_total": 0,
        "consecutive_fail_stop_triggered": False,
        "errors_by_code": {},
        "attempts": [],
    }

    # Phase 1 : scorer chaque deal
    scored = []  # [(priority, deal_id, deal, offer_hash, airline_code)]

    for deal in deals_list:
        airline = deal.get("airline", "")
        airline_code = get_airline_code_fn(airline) if get_airline_code_fn else ""
        deal["_airline_code"] = airline_code  # pour _make_snapshot

        origin = deal.get("origin", "")
        dest = deal.get("destination", "")
        depart = deal.get("depart", "")
        retour = deal.get("retour", "")

        deal_id = make_deal_id(origin, dest, depart, retour, airline_code, airline)
        offer_hash = compute_offer_hash(deal)
        existing = stored.get(deal_id)

        # P100 : jamais capture
        if not existing:
            scored.append((100, deal_id, deal, offer_hash, airline_code))
            continue

        old_hash = existing.get("offer_hash", "")
        was_success = existing.get("success", False)
        captured_at = existing.get("captured_at", "")
        fail_count = existing.get("fail_count", 0)
        last_fail_at = existing.get("last_fail_at", "")
        age = _age_minutes(captured_at)

        # P90 : hash a change
        if offer_hash != old_hash:
            scored.append((90, deal_id, deal, offer_hash, airline_code))
            continue

        # Hash identique — verifier fraicheur pour recapture (75 min)
        if was_success and age is not None and age < RECAPTURE_MINUTES:
            print(f"  [Capture] {deal_id}: frais ({age:.0f} min), skip")
            report["skipped_fresh_total"] += 1
            continue

        # P30 : echec precedent — verifier backoff
        if fail_count > 0:
            backoff = _backoff_minutes(fail_count)
            fail_age = _age_minutes(last_fail_at)
            if fail_age is not None and fail_age < backoff:
                print(f"  [Capture] {deal_id}: backoff ({backoff:.0f} min, reste {backoff - fail_age:.0f}), skip")
                report["skipped_backoff_total"] += 1
                continue
            scored.append((30, deal_id, deal, offer_hash, airline_code))
            continue

        # P50 : capture expiree (> 75 min), derniere reussie
        if was_success:
            scored.append((50, deal_id, deal, offer_hash, airline_code))
            continue

        # Cas residuel (pas de capture, pas d'echec) → P100
        scored.append((100, deal_id, deal, offer_hash, airline_code))

    report["eligible_total"] = len(scored)

    # Phase 2 : trier par priorite et capturer
    scored.sort(key=lambda x: -x[0])
    to_capture = scored[:MAX_CAPTURES_PER_CYCLE]
    report["planned_total"] = len(to_capture)

    if not to_capture:
        print(f"  [Capture] Aucune capture necessaire")
        return stored, report

    print(f"  [Capture] {len(to_capture)} capture(s) planifiee(s) sur {len(scored)} eligibles")
    consecutive_fails = 0

    for priority, deal_id, deal, offer_hash, airline_code in to_capture:
        if consecutive_fails >= 3:
            print(f"  [Capture] 3 echecs consecutifs — arret du cycle (Google bloque ?)")
            report["consecutive_fail_stop_triggered"] = True
            break

        origin = deal.get("origin", "")
        dest = deal.get("destination", "")
        depart = deal.get("depart", "")
        retour = deal.get("retour", "")
        airline = deal.get("airline", "")

        print(f"  [Capture] {deal_id} (P{priority}): demarrage...")
        cap = capture_booking_url(origin, dest, depart, retour)
        report["attempted_total"] += 1

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = stored.get(deal_id, {})

        # Observabilite enrichie pour deals.json
        obs_fields = {
            "last_stage": cap["stage"],
            "last_error_code": cap["error_code"],
            "last_error_detail": cap["error_detail"],
            "last_duration_ms": cap["duration_ms"],
            "last_attempt_at": now_str,
        }

        # Entree du rapport par tentative
        attempt_entry = {
            "deal_id": deal_id,
            "destination": dest,
            "priority": priority,
            "success": cap["success"],
            "stage": cap["stage"],
            "error_code": cap["error_code"],
            "final_domain": cap["final_domain"],
            "duration_ms": cap["duration_ms"],
            "last_attempt_at": now_str,
        }

        if cap["success"]:
            consecutive_fails = 0
            report["success_total"] += 1
            stored[deal_id] = {
                "deal_id": deal_id,
                "offer_hash": offer_hash,
                "snapshot": _make_snapshot(deal),
                "origin": origin,
                "destination": dest,
                "depart": depart,
                "retour": retour,
                "airline": airline,
                "airline_code": airline_code,
                "partner_clicked": cap["partner_clicked"],
                "final_url": cap["final_url"],
                "final_domain": cap["final_domain"],
                "captured_at": now_str,
                "success": True,
                "fail_count": 0,
                "last_fail_at": "",
                "last_success_at": now_str,
                **obs_fields,
            }
            print(f"  [Capture] {deal_id}: OK -> {cap['final_domain']}")
        else:
            consecutive_fails += 1
            report["failed_total"] += 1
            ec = cap["error_code"] or "UNKNOWN_ERROR"
            report["errors_by_code"][ec] = report["errors_by_code"].get(ec, 0) + 1
            stored[deal_id] = {
                **existing,
                "deal_id": deal_id,
                "offer_hash": offer_hash,
                "snapshot": _make_snapshot(deal),
                "origin": origin,
                "destination": dest,
                "depart": depart,
                "retour": retour,
                "airline": airline,
                "airline_code": airline_code,
                "success": False,
                "fail_count": existing.get("fail_count", 0) + 1,
                "last_fail_at": now_str,
                "last_failure_at": now_str,
                **obs_fields,
            }
            print(f"  [Capture] {deal_id}: ECHEC -> {cap['error_code']} ({cap['stage']})")

        report["attempts"].append(attempt_entry)

    save_deals(stored)
    return stored, report
