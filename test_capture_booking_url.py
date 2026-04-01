"""
Test isole : capture de l'URL de reservation apres clic sur "Selectionner"
dans Google Flights (YUL -> CDG).

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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

REPORT_DIR = os.path.join(os.path.dirname(__file__), "debug_booking_capture")
ORIGIN = "YUL"
DEST = "CDG"

# Domaines Google a ignorer (pas des sites de reservation)
GOOGLE_DOMAINS = {
    "google.com", "google.ca", "google.fr", "googleapis.com",
    "gstatic.com", "googleusercontent.com", "googlesyndication.com",
    "googleadservices.com", "doubleclick.net", "google-analytics.com",
    "googletagmanager.com", "youtube.com",
}

# Domaines de reservation connus (compagnies + OTA)
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


def _build_segment(origin, dest, date_str):
    origin_b = origin.encode()
    dest_b = dest.encode()
    date_b = date_str.encode()
    f13_inner = b"\x08\x01\x12" + bytes([len(origin_b)]) + origin_b
    f13 = b"\x6a" + bytes([len(f13_inner)]) + f13_inner
    f2 = b"\x12" + bytes([len(date_b)]) + date_b
    f14_inner = b"\x08\x01\x12" + bytes([len(dest_b)]) + dest_b
    f14 = b"\x72" + bytes([len(f14_inner)]) + f14_inner
    return f13 + f2 + f14


def build_flights_url(origin, dest, depart_date, return_date):
    d_str = depart_date.strftime("%Y-%m-%d")
    seg1 = _build_segment(origin, dest, d_str)
    leg1 = b"\x1a" + bytes([len(seg1)]) + seg1
    r_str = return_date.strftime("%Y-%m-%d")
    seg2 = _build_segment(dest, origin, r_str)
    leg2 = b"\x1a" + bytes([len(seg2)]) + seg2
    header = b"\x08\x1c\x10\x02"
    payload = header + leg1 + leg2
    tfs = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=CAD&hl=fr&gl=CA"


def get_driver():
    """Chrome avec performance logging active (CDP network events)."""
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
    # Activer les logs performance pour capturer le traffic reseau
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


def extract_network_urls(driver):
    """Extrait toutes les URLs de navigation depuis les performance logs Chrome."""
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

            # Requetes reseau (redirections, navigations)
            if method == "Network.requestWillBeSent":
                url = params.get("request", {}).get("url", "")
                doc_url = params.get("documentURL", "")
                redirect_url = params.get("redirectResponse", {}).get("url", "") if "redirectResponse" in params else ""
                rtype = params.get("type", "")

                if redirect_url and redirect_url.startswith("http"):
                    urls.append({"url": redirect_url, "type": "redirect", "resource": rtype})
                if url and url.startswith("http"):
                    urls.append({"url": url, "type": "request", "resource": rtype})
                if doc_url and doc_url.startswith("http") and doc_url != url:
                    urls.append({"url": doc_url, "type": "document", "resource": rtype})

            # Navigations vers de nouvelles pages
            elif method == "Page.frameNavigated":
                frame_url = params.get("frame", {}).get("url", "")
                if frame_url and frame_url.startswith("http"):
                    urls.append({"url": frame_url, "type": "navigation", "resource": "Document"})

        except Exception:
            continue

    return urls


def dismiss_consent(driver):
    """Tente de fermer les bannieres de cookies/consentement Google."""
    consent_selectors = [
        "button[aria-label*='Tout accepter']",
        "button[aria-label*='Accept all']",
        "button[aria-label*='Accepter']",
        "[data-ved] button",
        "form[action*='consent'] button",
        ".VfPpkd-LgbsSe[jsname]",
    ]
    for sel in consent_selectors:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                text = btn.text.lower()
                if any(w in text for w in ["accept", "tout", "j'accept", "ok", "agree"]):
                    btn.click()
                    time.sleep(1)
                    return True
        except Exception:
            continue
    return False


def run_attempt(attempt_num):
    """Execute une tentative complete de capture."""
    result = {
        "attempt": attempt_num,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "airline": "",
        "depart": "",
        "retour": "",
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
        result["notes"].append(f"Driver demarre, ouverture de Google Flights")
        driver.get(url)
        time.sleep(5)

        # Gerer le consentement cookies
        if "consent" in driver.current_url.lower():
            result["notes"].append("Page de consentement detectee, tentative de fermeture")
            dismiss_consent(driver)
            time.sleep(2)
            if "consent" in driver.current_url.lower():
                driver.get(url)
                time.sleep(5)

        dismiss_consent(driver)
        time.sleep(1)

        # Verifier qu'on a des resultats de vol
        rows = driver.find_elements(By.CSS_SELECTOR, "li.pIav2d")
        if not rows:
            rows = driver.find_elements(By.CSS_SELECTOR, ".yR1fYc, .OgQvJf")
        if not rows:
            # Sauvegarder screenshot pour debug
            debug_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_no_results.png")
            driver.save_screenshot(debug_path)
            result["error"] = f"Aucun resultat de vol trouve ({len(rows)} lignes)"
            result["notes"].append(f"Screenshot sauvegarde: {debug_path}")
            return result

        result["notes"].append(f"{len(rows)} resultats de vol trouves")

        # Extraire la compagnie du premier resultat
        first_row = rows[0]
        try:
            info_els = first_row.find_elements(By.CSS_SELECTOR, ".JMc5Xc, [class*='JMc5Xc']")
            for info_el in info_els:
                aria = info_el.get_attribute("aria-label") or ""
                m = re.search(r"Vol avec ([^,\.]+)", aria)
                if m:
                    result["airline"] = m.group(1).strip()
                    break
        except Exception:
            pass

        if not result["airline"]:
            try:
                row_text = first_row.text
                lines = [l.strip() for l in row_text.split("\n") if l.strip()]
                for line in lines:
                    if (line and len(line) > 2 and "$" not in line
                            and not re.match(r"^\d", line) and ":" not in line
                            and "escale" not in line.lower() and len(line) < 50):
                        result["airline"] = line
                        break
            except Exception:
                pass

        result["notes"].append(f"Compagnie detectee: {result['airline'] or 'inconnue'}")

        # Vider les logs performance avant le clic
        try:
            driver.get_log("performance")
        except Exception:
            pass

        # Chercher et cliquer sur le bouton "Selectionner" / "Select"
        select_btn = None
        original_handles = set(driver.window_handles)

        # Strategie 1 : boutons avec texte "Sélectionner" / "Select"
        buttons = driver.find_elements(By.CSS_SELECTOR, "button, a[role='button'], [role='link']")
        for btn in buttons:
            try:
                text = btn.text.lower().strip()
                if text in ("sélectionner", "selectionner", "select", "sélectionner ce vol"):
                    select_btn = btn
                    break
            except Exception:
                continue

        # Strategie 2 : cliquer directement sur la premiere ligne de vol
        if not select_btn:
            result["notes"].append("Bouton 'Selectionner' non trouve, clic sur la ligne de vol")
            try:
                first_row.click()
                time.sleep(3)

                # Apres expansion, chercher a nouveau le bouton
                buttons = driver.find_elements(By.CSS_SELECTOR, "button, a[role='button']")
                for btn in buttons:
                    try:
                        text = btn.text.lower().strip()
                        if any(w in text for w in ["sélectionner", "selectionner", "select", "réserver", "reserver", "book"]):
                            select_btn = btn
                            break
                    except Exception:
                        continue
            except Exception as e:
                result["notes"].append(f"Erreur clic ligne: {e}")

        # Strategie 3 : aria-label contenant "select" ou "selectionner"
        if not select_btn:
            for btn in driver.find_elements(By.CSS_SELECTOR, "[aria-label]"):
                try:
                    aria = (btn.get_attribute("aria-label") or "").lower()
                    if any(w in aria for w in ["sélectionner", "selectionner", "select flight", "book"]):
                        select_btn = btn
                        break
                except Exception:
                    continue

        if not select_btn:
            debug_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_no_button.png")
            driver.save_screenshot(debug_path)
            # Sauvegarder aussi le HTML pour debug
            html_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            result["error"] = "Bouton 'Selectionner' introuvable dans le DOM"
            result["notes"].append(f"Screenshot: {debug_path}, HTML: {html_path}")
            return result

        result["notes"].append(f"Bouton trouve: '{select_btn.text.strip()}'")

        # Vider les logs une derniere fois juste avant le clic
        try:
            driver.get_log("performance")
        except Exception:
            pass

        # Clic !
        result["click_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        try:
            select_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", select_btn)
        result["notes"].append("Clic effectue")

        # Attendre les redirections
        time.sleep(8)

        # Verifier si un nouvel onglet a ete ouvert
        new_handles = set(driver.window_handles) - original_handles
        if new_handles:
            new_tab = new_handles.pop()
            driver.switch_to.window(new_tab)
            result["notes"].append(f"Nouvel onglet detecte, switch effectue")
            time.sleep(3)

        # Capturer l'URL courante du navigateur
        current_url = driver.current_url
        result["notes"].append(f"URL courante apres clic: {current_url}")

        # Extraire toutes les URLs des logs reseau
        network_urls = extract_network_urls(driver)

        # Construire la liste ordonnee des URLs observees
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

        # Identifier les URLs non-Google (potentiellement des redirections vers reservation)
        non_google_urls = [u for u in ordered_urls if not u["is_google"]]
        booking_urls = [u for u in ordered_urls if u["is_booking"]]

        result["notes"].append(
            f"URLs capturees: {len(ordered_urls)} total, "
            f"{len(non_google_urls)} non-Google, {len(booking_urls)} booking"
        )

        # Determiner l'URL finale
        # Priorite 1 : URL courante du navigateur si c'est un site de reservation
        if not is_google_domain(current_url) and is_booking_domain(current_url):
            result["final_url"] = current_url
            result["final_domain"] = get_domain(current_url)
            result["success"] = True
            result["notes"].append(f"Succes: navigateur sur {result['final_domain']}")

        # Priorite 2 : URL courante non-Google (meme si pas dans la liste connue)
        elif not is_google_domain(current_url) and "google" not in current_url.lower():
            result["final_url"] = current_url
            result["final_domain"] = get_domain(current_url)
            result["success"] = True
            result["notes"].append(f"Succes: navigateur sur domaine externe {result['final_domain']}")

        # Priorite 3 : derniere URL de booking dans les logs reseau
        elif booking_urls:
            last_booking = booking_urls[-1]
            result["final_url"] = last_booking["url"]
            result["final_domain"] = last_booking["domain"]
            result["success"] = True
            result["notes"].append(f"Succes: URL booking trouvee dans les logs: {last_booking['domain']}")

        # Priorite 4 : derniere URL non-Google dans les logs
        elif non_google_urls:
            last_ext = non_google_urls[-1]
            result["final_url"] = last_ext["url"]
            result["final_domain"] = last_ext["domain"]
            # Succes seulement si c'est un domaine identifiable
            if last_ext["domain"] and "." in last_ext["domain"]:
                result["success"] = True
                result["notes"].append(f"URL externe trouvee: {last_ext['domain']}")
            else:
                result["notes"].append(f"URL externe non identifiable: {last_ext['url'][:100]}")

        else:
            result["error"] = "Aucune URL exploitable capturee hors de Google"
            result["notes"].append("Seules des URLs Google ont ete observees")

        # Screenshot final
        debug_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_final.png")
        driver.save_screenshot(debug_path)
        result["notes"].append(f"Screenshot final: {debug_path}")

    except Exception as e:
        result["error"] = f"Exception: {e}"
        result["notes"].append(traceback.format_exc())
        if driver:
            try:
                debug_path = os.path.join(REPORT_DIR, f"attempt_{attempt_num}_error.png")
                driver.save_screenshot(debug_path)
            except Exception:
                pass
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return result


def write_report(results):
    """Ecrit un rapport lisible dans debug_booking_capture/."""
    report_path = os.path.join(REPORT_DIR, "rapport.txt")
    json_path = os.path.join(REPORT_DIR, "resultats.json")

    successes = sum(1 for r in results if r["success"])

    lines = []
    lines.append("=" * 70)
    lines.append("RAPPORT DE CAPTURE — URLs de reservation Google Flights")
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Route: {ORIGIN} -> {DEST}")
    lines.append(f"Tentatives: {len(results)}, Succes: {successes}")
    lines.append("=" * 70)

    for r in results:
        lines.append("")
        lines.append(f"--- Tentative {r['attempt']} ---")
        lines.append(f"Timestamp:    {r['timestamp']}")
        lines.append(f"Compagnie:    {r['airline'] or 'non detectee'}")
        lines.append(f"Dates:        {r['depart']} -> {r['retour']}")
        lines.append(f"Clic a:       {r['click_timestamp'] or 'N/A'}")
        lines.append(f"Statut:       {'SUCCES' if r['success'] else 'ECHEC'}")

        if r["error"]:
            lines.append(f"Erreur:       {r['error']}")

        if r["final_url"]:
            lines.append(f"URL finale:   {r['final_url']}")
            lines.append(f"Domaine:      {r['final_domain']}")

        # URLs non-Google observees
        non_google = [u for u in r["urls_observed"] if not u["is_google"]]
        if non_google:
            lines.append(f"URLs externes ({len(non_google)}):")
            for u in non_google[:20]:
                tag = " [BOOKING]" if u["is_booking"] else ""
                lines.append(f"  [{u['type']:10}] {u['domain']}{tag}")
                lines.append(f"               {u['url'][:120]}")
        else:
            lines.append("URLs externes: aucune")

        lines.append(f"Total URLs capturees: {len(r['urls_observed'])}")
        lines.append("Notes:")
        for note in r["notes"]:
            for sub_line in note.split("\n"):
                lines.append(f"  {sub_line}")

    lines.append("")
    lines.append("=" * 70)
    if successes == 0:
        lines.append("CONCLUSION: Aucun lien exploitable capture apres 3 tentatives.")
        lines.append("Google Flights ne redirige probablement pas vers un site externe")
        lines.append("lors du clic sur 'Selectionner' — il garde l'utilisateur dans")
        lines.append("son propre flow de reservation ou affiche les details du vol.")
    else:
        lines.append(f"CONCLUSION: {successes}/3 tentatives ont capture un lien exploitable.")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return report_text


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("=" * 60)
    print(f"Test capture URL de reservation — {ORIGIN} -> {DEST}")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = []
    for i in range(1, 4):
        print(f"\n--- Tentative {i}/3 ---")
        result = run_attempt(i)
        results.append(result)
        status = "SUCCES" if result["success"] else "ECHEC"
        print(f"  Statut: {status}")
        if result["airline"]:
            print(f"  Compagnie: {result['airline']}")
        if result["final_url"]:
            print(f"  URL finale: {result['final_url'][:100]}")
        if result["error"]:
            print(f"  Erreur: {result['error']}")
        print(f"  URLs capturees: {len(result['urls_observed'])}")

    report = write_report(results)
    print(f"\n{report}")


if __name__ == "__main__":
    main()
