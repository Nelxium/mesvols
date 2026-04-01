"""
Test rapide du resolveur /r/<deal_id> de server.py.
Teste 3 cas : deal frais, deal expire, deal_id inconnu.
Restaure deals.json a la fin.
"""

import json
import os
import shutil
from datetime import datetime, timedelta

DEALS_PATH = os.path.join(os.path.dirname(__file__), "deals.json")
BACKUP_PATH = DEALS_PATH + ".bak"


def setup():
    """Sauvegarde deals.json existant et ecrit les donnees de test."""
    if os.path.isfile(DEALS_PATH):
        shutil.copy2(DEALS_PATH, BACKUP_PATH)

    now = datetime.now()
    expired = now - timedelta(hours=2)

    test_deals = {
        "YUL-CDG-20260531-20260607-TS": {
            "deal_id": "YUL-CDG-20260531-20260607-TS",
            "origin": "YUL",
            "destination": "CDG",
            "depart": "2026-05-31",
            "retour": "2026-06-07",
            "airline": "Air Transat",
            "airline_code": "TS",
            "partner_clicked": "Air Transat",
            "final_url": "https://www.airtransat.com/test",
            "final_domain": "www.airtransat.com",
            "captured_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "success": True,
        },
        "YUL-CUN-20260701-20260708-WS": {
            "deal_id": "YUL-CUN-20260701-20260708-WS",
            "origin": "YUL",
            "destination": "CUN",
            "depart": "2026-07-01",
            "retour": "2026-07-08",
            "airline": "WestJet",
            "airline_code": "WS",
            "partner_clicked": "WestJet",
            "final_url": "https://www.westjet.com/old-expired",
            "final_domain": "www.westjet.com",
            "captured_at": expired.strftime("%Y-%m-%d %H:%M:%S"),
            "success": True,
        },
    }

    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(test_deals, f, ensure_ascii=False, indent=2)


def teardown():
    """Restaure deals.json original."""
    if os.path.isfile(BACKUP_PATH):
        shutil.move(BACKUP_PATH, DEALS_PATH)
    elif os.path.isfile(DEALS_PATH):
        os.remove(DEALS_PATH)


def resolve(deal_id):
    """Appelle _resolve_url via une instance de MesVolsHandler simulee."""
    from server import MesVolsHandler
    # _resolve_url est une methode d'instance mais n'utilise pas self
    # On cree un objet minimal sans lancer le serveur
    return MesVolsHandler._resolve_url(None, deal_id)


def main():
    setup()
    results = []

    try:
        # Cas 1 : deal frais
        url = resolve("YUL-CDG-20260531-20260607-TS")
        ok = url == "https://www.airtransat.com/test"
        results.append(("Deal frais -> URL capturee", ok, url))

        # Cas 2 : deal expire -> fallback Skyscanner
        url = resolve("YUL-CUN-20260701-20260708-WS")
        ok = ("skyscanner.ca" in url
              and "origin=YUL" in url
              and "destination=CUN" in url
              and "outboundDate=2026-07-01" in url
              and "inboundDate=2026-07-08" in url
              and "airlines=WS" in url)
        results.append(("Deal expire -> fallback Skyscanner", ok, url))

        # Cas 3 : deal_id inconnu -> fallback Skyscanner parse depuis l'ID
        url = resolve("YUL-PUJ-20260815-20260822-DL")
        ok = ("skyscanner.ca" in url
              and "origin=YUL" in url
              and "destination=PUJ" in url
              and "outboundDate=2026-08-15" in url
              and "inboundDate=2026-08-22" in url
              and "airlines=DL" in url)
        results.append(("Deal inconnu -> fallback Skyscanner parse", ok, url))

    except Exception as e:
        results.append(("Exception inattendue", False, str(e)))
    finally:
        teardown()

    # Affichage
    print()
    all_pass = True
    for label, ok, url in results:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{tag}] {label}")
        print(f"         -> {url}")

    print()
    if all_pass:
        print("Tous les tests passent.")
    else:
        print("ECHEC: certains tests ont echoue.")
    return all_pass


if __name__ == "__main__":
    main()
