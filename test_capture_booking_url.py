"""
Test isole : capture de l'URL de reservation via le flow complet Google Flights.

Flow : resultats aller -> selection vol aller -> resultats retour ->
       selection vol retour -> ecran offres partenaires -> clic offre -> capture.

Utilise Chrome DevTools Protocol (performance logs) pour capturer la chaine
complete de redirections reseau. Pas de Selenium Wire.

Fait 3 tentatives independantes avec un driver propre a chaque fois.
Ecrit un rapport lisible dans debug_booking_capture/.
"""

import base64
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

REPORT_DIR = os.path.join(os.path.dirname(__file__), "debug_booking_capture")
ORIGIN = "YUL"
DEST = "CDG"

GOOGLE_DOMAINS = {
    "google.com", "google.ca", "google.fr", "googleapis.com",
    "gstatic.com", "googleusercontent.com", "googlesyndication.com",
    "googleadservices.com", "doubleclick.net", "google-analytics.com",
    "googletagmanager.com", "youtube.com",
}

BOOKING_DOMAINS = {
    "aircanada.com", "airtransat.com", "westjet.com", "porterairlines.com",
    "flyflair.com", "united.com", "delta.com", "aa.com", "jetblue.com",
    "spirit.com", "flyfrontier.com", "southwest.com",
    "airfrance.com", "airfrance.fr", "lufthansa.com", "britishairways.com",
    "klm.com", "swiss.com", "iberia.com", "flytap.com", "alitalia.com",
    "ita-airways.com", "aegeanair.com", "turkishairlines.com",
    "emirates.com", "qatarairways.com", "icelandair.com",
    "hawaiianairlines.com", "alaskaair.com",
    "kayak.com", "expedia.com", "expedia.ca", "skyscanner.ca",
    "skyscanner.com", "booking.com", "momondo.com", "cheapflights.com",
    "kiwi.com", "trip.com", "orbitz.com", "priceline.com",
    "travelocity.com", "flightnetwork.com", "flighthub.com",
    "edreams.com", "opodo.com", "lastminute.com", "gotogate.com",
    "budgetair.com", "bravofly.com", "mytrip.com",
}


# ── URL builder ──────────────────────────────────────────────────────────

def _build_segment(origin, dest, date_str):
    origin_b, dest_b, date_b = origin.encode(), dest.encode(), date_str.encode()
    f13_inner = b"\x08\x01\x12" + bytes([len(origin_b)]) + origin_b
    f13 = b"\x6a" + bytes([len(f13_inner)]) + f13_inner
    f2 = b"\x12" + bytes([len(date_b)]) + date_b
    f14_inner = b"\x08\x01\x12" + bytes([len(dest_b)]) + dest_b
    f14 = b"\x72" + bytes([len(f14_inner)]) + f14_inner
    return f13 + f2 + f14


def build_flights_url(origin, dest, depart_date, return_date):
    d_str = depart_date.strftime("%Y-%m-%d")
    r_str = return_date.strftime("%Y-%m-%d")
    seg1 = _build_segment(origin, dest, d_str)
    leg1 = b"\x1a" + bytes([len(seg1)]) + seg1
    seg2 = _build_segment(dest, origin, r_str)
    leg2 = b"\x1a" + bytes([len(seg2)]) + seg2
    payload = b"\x08\x1c\x10\x02" + leg1 + leg2
    tfs = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=CAD&hl=fr&gl=CA"


# ── Helpers ──────────────────────────────────────────────────────────────

def get_driver():
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


def is_google_domain(url):
    try:
        host = urlparse(url).hostname or ""
        return any(host.endswith(d) for d in GOOGLE_DOMAINS)
    except Exception:
        return True


def is_booking_domain(url):
    try:
        host = urlparse(url).hostname or ""
        return any(host.endswith(d) for d in BOOKING_DOMAINS)
    except Exception:
        return False


def get_domain(url):
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def flush_logs(driver):
    try:
        driver.get_log("performance")
    except Exception:
        pass


def extract_network_urls(driver):
    urls = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return urls
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "Network.requestWillBeSent":
                req_url = params.get("request", {}).get("url", "")
                redir_url = params.get("redirectResponse", {}).get("url", "") if "redirectResponse" in params else ""
                rtype = params.get("type", "")
                if redir_url and redir_url.startswith("http"):
                    urls.append({"url": redir_url, "type": "redirect", "resource": rtype})
                if req_url and req_url.startswith("http"):
                    urls.append({"url": req_url, "type": "request", "resource": rtype})
            elif method == "Page.frameNavigated":
                frame_url = params.get("frame", {}).get("url", "")
                if frame_url and frame_url.startswith("http"):
                    urls.append({"url": frame_url, "type": "navigation", "resource": "Document"})
        except Exception:
            continue
    return urls


def dismiss_consent(driver):
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
                    return True
        except Exception:
            continue
    return False


def save_debug(driver, attempt, suffix):
    path = os.path.join(REPORT_DIR, f"attempt_{attempt}_{suffix}.png")
    try:
        driver.save_screenshot(path)
    except Exception:
        pass
    return path


def detect_airline(row):
    """Extrait le nom de la compagnie depuis une ligne de resultat vol."""
    try:
        for el in row.find_elements(By.CSS_SELECTOR, ".JMc5Xc, [class*='JMc5Xc']"):
            aria = el.get_attribute("aria-label") or ""
            m = re.search(r"Vol avec ([^,\.]+)", aria)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    # Fallback texte
    try:
        for line in row.text.split("\n"):
            line = line.strip()
            if (line and len(line) > 2 and "$" not in line
                    and not re.match(r"^\d", line) and ":" not in line
                    and "escale" not in line.lower() and len(line) < 50):
                return line
    except Exception:
        pass
    return ""


def click_flight_row(driver, rows, notes):
    """
    Clique sur la premiere ligne de vol. Google Flights peut necesiter :
    1. Un clic sur la ligne pour l'ouvrir
    2. Puis un clic sur un bouton dans le detail expanse
    Retourne True si un clic a ete effectue.
    """
    if not rows:
        return False

    first = rows[0]
    try:
        first.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", first)
        except Exception as e:
            notes.append(f"Erreur clic ligne: {e}")
            return False
    time.sleep(3)
    return True


def wait_for_url_change(driver, old_url, timeout=10):
    """Attend que l'URL change ou que le contenu se mette a jour."""
    for _ in range(timeout):
        if driver.current_url != old_url:
            return True
        time.sleep(1)
    return False


def find_booking_offers(driver):
    """
    Detecte les offres de reservation sur l'ecran final Google Flights.
    Google Flights affiche "Options de reservation" avec des lignes :
      "Reserver avec <partenaire>" | prix | bouton "Continuer"
    Les boutons "Continuer" sont des <a> ou <button> internes Google qui
    redirigent via JS — pas de href externe direct.

    Retourne une liste de dicts {name, price, button_text, href, element}.
    """
    offers = []

    # Strategie 1 : texte de la page contenant "Réserver avec ..."
    # Chercher les blocs contenant a la fois un nom de partenaire et un prix
    body_text = driver.find_element(By.TAG_NAME, "body").text
    reserve_matches = re.findall(
        r"[Rr][eé]server avec ([^\n]+)", body_text
    )

    # Strategie 2 : trouver les lignes d'offres via le DOM
    # Google Flights structure chaque offre dans un conteneur cliquable
    # Chercher tous les elements contenant "Réserver avec" ou "Book with"
    offer_containers = []

    # Methode A : XPath sur le texte
    try:
        offer_containers = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), 'server avec') or contains(text(), 'Book with') "
            "or contains(text(), 'Book on')]"
        )
    except Exception:
        pass

    # Pour chaque match, remonter au conteneur parent qui contient le prix et le bouton
    for el in offer_containers:
        try:
            # Remonter de quelques niveaux pour trouver le conteneur complet de l'offre
            container = el
            for _ in range(6):
                parent = container.find_element(By.XPATH, "./..")
                parent_text = parent.text.strip()
                if "$" in parent_text and ("continuer" in parent_text.lower()
                                            or "continue" in parent_text.lower()
                                            or "select" in parent_text.lower()):
                    container = parent
                    break
                if "$" in parent_text:
                    container = parent
                container = parent

            text = container.text.strip()
            if "$" not in text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Extraire le nom du partenaire
            name = ""
            for line in lines:
                m = re.search(r"[Rr][eé]server avec (.+)", line)
                if m:
                    name = m.group(1).strip()
                    break
                m = re.search(r"Book (?:with|on) (.+)", line)
                if m:
                    name = m.group(1).strip()
                    break
            if not name:
                continue

            # Extraire le prix
            price = ""
            for line in lines:
                if "$" in line:
                    price = line.strip()
                    break

            # Trouver le bouton "Continuer" / "Continue" dans ce conteneur
            clickable = None
            href = ""
            # D'abord chercher un lien
            for a_tag in container.find_elements(By.CSS_SELECTOR, "a[href]"):
                h = a_tag.get_attribute("href") or ""
                a_text = a_tag.text.lower().strip()
                if any(w in a_text for w in ["continuer", "continue", "select",
                                              "réserver", "book", "go to"]):
                    clickable = a_tag
                    href = h
                    break
                if h and not is_google_domain(h):
                    clickable = a_tag
                    href = h

            # Sinon chercher un bouton
            if not clickable:
                for btn in container.find_elements(By.CSS_SELECTOR, "button"):
                    btn_text = btn.text.lower().strip()
                    if any(w in btn_text for w in ["continuer", "continue", "select",
                                                    "réserver", "book"]):
                        clickable = btn
                        break

            # Dernier recours : le conteneur lui-meme
            if not clickable:
                clickable = container

            # Eviter les doublons
            if any(o["name"] == name for o in offers):
                continue

            offers.append({
                "name": name,
                "price": price,
                "button_text": clickable.text.strip()[:60] if clickable.text else "",
                "href": href,
                "element": clickable,
            })
        except Exception:
            continue

    # Strategie 3 : fallback — chercher tout lien googleadservices
    if not offers:
        for a_tag in driver.find_elements(By.CSS_SELECTOR, "a[href*='googleadservices']"):
            href = a_tag.get_attribute("href") or ""
            text = a_tag.text.strip()
            parent_text = ""
            try:
                parent_text = a_tag.find_element(By.XPATH, "./..").text.strip()
            except Exception:
                pass
            display = text or parent_text
            lines = [l.strip() for l in display.split("\n") if l.strip()]
            offers.append({
                "name": lines[0] if lines else "Offre Google Ads",
                "price": next((l for l in lines if "$" in l), ""),
                "button_text": text[:60] if text else "",
                "href": href,
                "element": a_tag,
            })

    return offers


# ── Tentative complete ───────────────────────────────────────────────────

def run_attempt(attempt_num):
    result = {
        "attempt": attempt_num,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "airline_outbound": "",
        "airline_return": "",
        "depart": "",
        "retour": "",
        "partner_clicked": "",
        "offers_visible": [],
        "click_timestamp": "",
        "urls_observed": [],
        "final_url": "",
        "final_domain": "",
        "success": False,
        "error": "",
        "notes": [],
    }

    depart = datetime.now() + timedelta(days=60)
    retour = depart + timedelta(days=7)
    result["depart"] = depart.strftime("%Y-%m-%d")
    result["retour"] = retour.strftime("%Y-%m-%d")

    url = build_flights_url(ORIGIN, DEST, depart, retour)
    driver = None

    try:
        driver = get_driver()
        notes = result["notes"]
        notes.append("Driver demarre")

        # ── ETAPE 0 : Charger la page ────────────────────────────────
        driver.get(url)
        time.sleep(6)

        if "consent" in driver.current_url.lower():
            notes.append("Consentement detecte")
            dismiss_consent(driver)
            time.sleep(2)
            if "consent" in driver.current_url.lower():
                driver.get(url)
                time.sleep(6)
        dismiss_consent(driver)

        # ── ETAPE 1 : Resultats aller ────────────────────────────────
        rows = driver.find_elements(By.CSS_SELECTOR, "li.pIav2d")
        if not rows:
            rows = driver.find_elements(By.CSS_SELECTOR, ".yR1fYc, .OgQvJf")
        if not rows:
            save_debug(driver, attempt_num, "no_outbound")
            result["error"] = "Aucun vol aller trouve"
            return result

        notes.append(f"ETAPE 1: {len(rows)} vols aller trouves")
        result["airline_outbound"] = detect_airline(rows[0])
        notes.append(f"  Compagnie aller: {result['airline_outbound'] or '?'}")

        # ── ETAPE 2 : Selection vol aller ────────────────────────────
        url_before = driver.current_url
        flush_logs(driver)

        if not click_flight_row(driver, rows, notes):
            save_debug(driver, attempt_num, "click_outbound_fail")
            result["error"] = "Impossible de cliquer sur le vol aller"
            return result

        notes.append("ETAPE 2: Clic vol aller effectue")
        save_debug(driver, attempt_num, "after_outbound_click")

        # Attendre que l'URL change (parametre tfu ajoute) ou que de nouveaux vols apparaissent
        time.sleep(5)

        # Verifier si on voit des vols retour (l'URL a un tfu= maintenant)
        # ou si la page a change de contenu
        current_url = driver.current_url
        if current_url == url_before:
            notes.append("  URL n'a pas change — peut-etre un panel expanse")
            # Tenter de trouver un bouton "Selectionner" dans le detail
            for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
                txt = btn.text.lower().strip()
                if any(w in txt for w in ["sélectionner", "selectionner", "select"]):
                    notes.append(f"  Bouton '{btn.text.strip()}' trouve, clic")
                    btn.click()
                    time.sleep(5)
                    break
            current_url = driver.current_url

        notes.append(f"  URL apres selection aller: ...{current_url[-80:]}")

        # ── ETAPE 3 : Resultats retour ───────────────────────────────
        # Verifier qu'on voit la banniere "Vols retour" ou des resultats
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        has_return = ("retour" in page_text or "return" in page_text
                      or "vol de retour" in page_text or "vols retour" in page_text)

        rows2 = driver.find_elements(By.CSS_SELECTOR, "li.pIav2d")
        if not rows2:
            rows2 = driver.find_elements(By.CSS_SELECTOR, ".yR1fYc, .OgQvJf")

        if not rows2 and not has_return:
            save_debug(driver, attempt_num, "no_return")
            # Peut-etre qu'on est deja sur l'ecran des offres (vol direct aller-retour?)
            notes.append("ETAPE 3: Pas de vols retour visibles — verif ecran offres")
        else:
            notes.append(f"ETAPE 3: {len(rows2)} vols retour trouves")

            if rows2:
                result["airline_return"] = detect_airline(rows2[0])
                notes.append(f"  Compagnie retour: {result['airline_return'] or '?'}")

                # ── ETAPE 4 : Selection vol retour ────────────────────
                url_before = driver.current_url
                flush_logs(driver)

                if not click_flight_row(driver, rows2, notes):
                    save_debug(driver, attempt_num, "click_return_fail")
                    result["error"] = "Impossible de cliquer sur le vol retour"
                    return result

                notes.append("ETAPE 4: Clic vol retour effectue")
                time.sleep(5)

                current_url = driver.current_url
                if current_url == url_before:
                    # Tenter bouton Selectionner
                    for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
                        txt = btn.text.lower().strip()
                        if any(w in txt for w in ["sélectionner", "selectionner", "select"]):
                            notes.append(f"  Bouton '{btn.text.strip()}' trouve, clic")
                            btn.click()
                            time.sleep(5)
                            break

                save_debug(driver, attempt_num, "after_return_click")
                notes.append(f"  URL apres selection retour: ...{driver.current_url[-80:]}")

        # ── ETAPE 5 : Ecran des offres de reservation ────────────────
        time.sleep(3)
        save_debug(driver, attempt_num, "booking_screen")

        # Sauvegarder le HTML de l'ecran booking pour debug
        html_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_booking_page.html")
        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            notes.append(f"  HTML sauvegarde: {html_path}")
        except Exception:
            pass

        # Detecter les offres
        offers = find_booking_offers(driver)
        notes.append(f"ETAPE 5: {len(offers)} offres de reservation detectees")

        # Sauvegarder les offres dans le resultat (sans l'element Selenium)
        for o in offers:
            result["offers_visible"].append({
                "name": o["name"],
                "price": o["price"],
                "button_text": o["button_text"],
                "href": o["href"],
            })
            notes.append(f"  Offre: {o['name'][:40]} | {o['price']} | href={'oui' if o['href'] else 'non'}")

        if not offers:
            result["error"] = "Aucune offre de reservation trouvee sur l'ecran final"
            return result

        # ── ETAPE 6 : Clic sur la premiere offre exploitable ─────────
        clicked_offer = None
        for o in offers:
            # Preferer les offres avec href externe ou avec un nom identifiable
            if o["href"] or o["name"]:
                clicked_offer = o
                break
        if not clicked_offer:
            clicked_offer = offers[0]

        result["partner_clicked"] = clicked_offer["name"]
        notes.append(f"ETAPE 6: Clic sur '{clicked_offer['name']}' (href={'oui' if clicked_offer['href'] else 'non'})")

        original_handles = set(driver.window_handles)
        flush_logs(driver)

        result["click_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        try:
            clicked_offer["element"].click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", clicked_offer["element"])
            except Exception as e:
                notes.append(f"  Erreur clic offre: {e}")
                result["error"] = f"Impossible de cliquer sur l'offre: {e}"
                return result

        notes.append("  Clic effectue, attente redirections...")
        time.sleep(10)

        # ── ETAPE 7 : Capture des redirections ───────────────────────
        # Verifier nouvel onglet
        new_handles = set(driver.window_handles) - original_handles
        if new_handles:
            new_tab = new_handles.pop()
            driver.switch_to.window(new_tab)
            notes.append(f"  Nouvel onglet detecte, switch effectue")
            time.sleep(4)

        current_url = driver.current_url
        notes.append(f"  URL courante: {current_url[:120]}")

        # Extraire les URLs des logs reseau
        network_urls = extract_network_urls(driver)

        seen = set()
        ordered_urls = []
        for entry in network_urls:
            u = entry["url"]
            if u not in seen:
                seen.add(u)
                ordered_urls.append({
                    "url": u,
                    "type": entry["type"],
                    "domain": get_domain(u),
                    "is_google": is_google_domain(u),
                    "is_booking": is_booking_domain(u),
                })

        result["urls_observed"] = ordered_urls

        non_google = [u for u in ordered_urls if not u["is_google"]]
        booking = [u for u in ordered_urls if u["is_booking"]]

        notes.append(f"  URLs: {len(ordered_urls)} total, {len(non_google)} non-Google, {len(booking)} booking")

        # Determiner l'URL finale
        if not is_google_domain(current_url) and is_booking_domain(current_url):
            result["final_url"] = current_url
            result["final_domain"] = get_domain(current_url)
            result["success"] = True
            notes.append(f"  SUCCES: navigateur sur {result['final_domain']}")

        elif not is_google_domain(current_url) and "google" not in current_url.lower():
            result["final_url"] = current_url
            result["final_domain"] = get_domain(current_url)
            result["success"] = True
            notes.append(f"  SUCCES: navigateur sur domaine externe {result['final_domain']}")

        elif booking:
            last_b = booking[-1]
            result["final_url"] = last_b["url"]
            result["final_domain"] = last_b["domain"]
            result["success"] = True
            notes.append(f"  SUCCES: URL booking dans logs: {last_b['domain']}")

        elif non_google:
            last_ext = non_google[-1]
            result["final_url"] = last_ext["url"]
            result["final_domain"] = last_ext["domain"]
            if last_ext["domain"] and "." in last_ext["domain"]:
                result["success"] = True
                notes.append(f"  SUCCES: domaine externe {last_ext['domain']}")
            else:
                notes.append(f"  URL externe non identifiable: {last_ext['url'][:100]}")

        else:
            result["error"] = "Aucune URL exploitable capturee hors de Google"
            notes.append("  ECHEC: seules des URLs Google observees apres clic offre")

        save_debug(driver, attempt_num, "final")

    except Exception as e:
        result["error"] = f"Exception: {e}"
        result["notes"].append(traceback.format_exc())
        if driver:
            save_debug(driver, attempt_num, "error")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return result


# ── Rapport ──────────────────────────────────────────────────────────────

def write_report(results):
    report_path = os.path.join(REPORT_DIR, "rapport.txt")
    json_path = os.path.join(REPORT_DIR, "resultats.json")

    successes = sum(1 for r in results if r["success"])

    lines = []
    lines.append("=" * 70)
    lines.append("RAPPORT — Capture URLs reservation Google Flights (flow complet)")
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Route: {ORIGIN} -> {DEST}")
    lines.append(f"Tentatives: {len(results)}, Succes: {successes}")
    lines.append("=" * 70)

    for r in results:
        lines.append("")
        lines.append(f"--- Tentative {r['attempt']} ---")
        lines.append(f"Timestamp:        {r['timestamp']}")
        lines.append(f"Compagnie aller:  {r['airline_outbound'] or '?'}")
        lines.append(f"Compagnie retour: {r['airline_return'] or '?'}")
        lines.append(f"Dates:            {r['depart']} -> {r['retour']}")
        lines.append(f"Partenaire:       {r['partner_clicked'] or 'N/A'}")
        lines.append(f"Clic a:           {r['click_timestamp'] or 'N/A'}")
        lines.append(f"Statut:           {'SUCCES' if r['success'] else 'ECHEC'}")

        if r["error"]:
            lines.append(f"Erreur:           {r['error']}")
        if r["final_url"]:
            lines.append(f"URL finale:       {r['final_url'][:150]}")
            lines.append(f"Domaine final:    {r['final_domain']}")

        if r["offers_visible"]:
            lines.append(f"Offres visibles ({len(r['offers_visible'])}):")
            for o in r["offers_visible"]:
                href_tag = f" href={o['href'][:60]}" if o["href"] else " (pas de href)"
                lines.append(f"  - {o['name'][:40]} | {o['price']} | btn='{o['button_text'][:30]}'{href_tag}")
        else:
            lines.append("Offres visibles: aucune")

        non_google = [u for u in r["urls_observed"] if not u["is_google"]]
        if non_google:
            lines.append(f"URLs externes ({len(non_google)}):")
            for u in non_google[:25]:
                tag = " [BOOKING]" if u["is_booking"] else ""
                lines.append(f"  [{u['type']:10}] {u['domain']}{tag}")
                lines.append(f"               {u['url'][:140]}")
        else:
            lines.append("URLs externes: aucune")

        lines.append(f"Total URLs capturees: {len(r['urls_observed'])}")
        lines.append("Notes:")
        for note in r["notes"]:
            for sub in note.split("\n"):
                lines.append(f"  {sub}")

    lines.append("")
    lines.append("=" * 70)
    if successes == 0:
        lines.append("CONCLUSION: Aucun lien exploitable capture apres 3 tentatives.")
        lines.append("Pour MesVols, on reste sur les liens Skyscanner day-view")
        lines.append("construits par links.py comme URLs de reservation.")
    else:
        lines.append(f"CONCLUSION: {successes}/3 tentatives ont capture un lien exploitable.")
        lines.append("Il serait possible d'integrer cette capture dans le scraper.")
    lines.append("=" * 70)

    report_text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    with open(json_path, "w", encoding="utf-8") as f:
        # Retirer les elements Selenium avant serialisation
        clean = json.loads(json.dumps(results, default=str))
        json.dump(clean, f, ensure_ascii=False, indent=2)

    return report_text


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("=" * 60)
    print(f"Test capture URL reservation — flow complet")
    print(f"{ORIGIN} -> {DEST}")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = []
    for i in range(1, 4):
        print(f"\n--- Tentative {i}/3 ---")
        r = run_attempt(i)
        results.append(r)
        status = "SUCCES" if r["success"] else "ECHEC"
        print(f"  Statut:     {status}")
        print(f"  Aller:      {r['airline_outbound'] or '?'}")
        print(f"  Retour:     {r['airline_return'] or '?'}")
        print(f"  Partenaire: {r['partner_clicked'] or 'N/A'}")
        print(f"  Offres:     {len(r['offers_visible'])}")
        if r["final_url"]:
            print(f"  URL finale: {r['final_url'][:100]}")
        if r["error"]:
            print(f"  Erreur:     {r['error']}")
        print(f"  URLs:       {len(r['urls_observed'])}")

    report = write_report(results)
    print(f"\n{report}")


if __name__ == "__main__":
    main()
