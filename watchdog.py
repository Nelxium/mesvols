"""
MesVols - Watchdog local (monitoring/verification).

Role : surveiller plus souvent que GitHub Actions (toutes les 30 min)
       sans modifier les artefacts du pipeline public.

Ce que le watchdog fait :
  - Scrape Google Flights (memes routes/horizons que le pipeline)
  - Compare les prix locaux vs les donnees publiques (data.js)
  - Detecte les deals >= 30%
  - Alerte Discord si : deal detecte, scraping echoue, donnees publiques trop vieilles
  - Ecrit watchdog_state.json (local, gitignored)

Ce que le watchdog ne fait PAS :
  - Ecrire dans prix_vols.csv (source de verite du pipeline CI)
  - Ecrire data.js ou docs/data.js
  - Faire git add/commit/push
  - Modifier deals.json ou health.json
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from scraper import run_scraper, HORIZONS
from analyzer import find_deals, parse_stops, compute_score
from config import ROUTES, DISCORD_WEBHOOK_URL, DEAL_THRESHOLD
from links import build_search_link
from main import get_airline_code

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "watchdog_state.json")
DATA_JS_PATH = os.path.join(HERE, "docs", "data.js")


def _load_public_state():
    """Charge l'etat public depuis data.js (readonly)."""
    if not os.path.isfile(DATA_JS_PATH):
        return None, None
    try:
        with open(DATA_JS_PATH, encoding="utf-8") as f:
            content = f.read()
        import re
        m_update = re.search(r'LAST_UPDATE = "(.+?)"', content)
        m_bo = re.search(r'const BEST_OFFERS = ({.*?});', content, re.DOTALL)
        last_update = m_update.group(1) if m_update else ""
        best_offers = json.loads(m_bo.group(1)) if m_bo else {}
        return last_update, best_offers
    except Exception:
        return None, None


def _send_discord(embeds, content=None):
    """Envoie un message Discord."""
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {"embeds": embeds}
    if content:
        payload["content"] = content
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(DISCORD_WEBHOOK_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "MesVols-Watchdog/1.0")
        urlopen(req, timeout=10)
    except Exception as e:
        print(f"  Discord error: {e}")


def _write_state(state):
    """Ecrit watchdog_state.json (local uniquement)."""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print("=" * 60)
    print(f"MesVols Watchdog - {now}")
    print("=" * 60)

    state = {
        "timestamp": now,
        "status": "running",
        "routes_expected": len(ROUTES) * len(HORIZONS),
        "routes_scraped": 0,
        "deals_detected": 0,
        "alerts_sent": 0,
        "public_last_update": None,
        "public_stale_minutes": None,
        "errors": [],
    }

    # 1. Charger l'etat public (readonly)
    pub_update, pub_offers = _load_public_state()
    state["public_last_update"] = pub_update

    if pub_update:
        # Calculer la fraicheur des donnees publiques
        try:
            clean = pub_update.rstrip("Z")
            parts = clean.split(" ")
            date_parts = parts[0].split("-")
            time_parts = parts[1].split(":") if len(parts) > 1 else ["0", "0"]
            pub_dt = datetime(
                int(date_parts[0]), int(date_parts[1]), int(date_parts[2]),
                int(time_parts[0]), int(time_parts[1]),
                tzinfo=timezone.utc)
            stale_min = int((datetime.now(timezone.utc) - pub_dt).total_seconds() / 60)
            state["public_stale_minutes"] = stale_min
            print(f"  Donnees publiques : {pub_update} (il y a {stale_min} min)")
        except Exception:
            state["public_stale_minutes"] = None
            print(f"  Donnees publiques : {pub_update} (fraicheur inconnue)")
    else:
        print("  Donnees publiques : introuvables")

    # 2. Scraper (ne modifie PAS le CSV — on monkey-patch save_to_csv)
    import scraper as _scraper_mod
    _original_save = _scraper_mod.save_to_csv
    _scraper_mod.save_to_csv = lambda results: print(
        f"  [watchdog] CSV write skipped ({len(results)} rows)")
    try:
        results = run_scraper()
    finally:
        _scraper_mod.save_to_csv = _original_save

    if not results:
        state["status"] = "scrape_failed"
        state["errors"].append("Aucun resultat du scraping")
        _write_state(state)
        _send_discord([{
            "title": "MesVols Watchdog - SCRAPING ECHOUE",
            "description": "Le watchdog n'a obtenu aucun resultat de Google Flights.",
            "color": 0xe11d48,
            "footer": {"text": now},
        }])
        print("\nSCRAPE ECHOUE — alerte envoyee")
        sys.exit(1)

    state["routes_scraped"] = len(results)
    expected = len(ROUTES) * len(HORIZONS)
    coverage = len(results) / expected if expected else 0
    print(f"\n  Couverture : {len(results)}/{expected} ({int(coverage*100)}%)")

    if coverage < 0.50:
        state["errors"].append(f"Couverture degradee: {int(coverage*100)}%")

    # 3. Detecter les deals
    deals = find_deals(results)
    state["deals_detected"] = len(deals) if deals else 0

    # 4. Comparer avec l'etat public
    drifts = []
    if pub_offers:
        for r in results:
            dest = r.get("destination", "")
            local_price = r.get("price_google", 0)
            if isinstance(local_price, str):
                local_price = int(local_price) if local_price else 0
            pub = pub_offers.get(dest, {})
            pub_price = pub.get("price", 0)
            if pub_price and local_price and abs(local_price - pub_price) / pub_price > 0.20:
                drifts.append({
                    "dest": dest,
                    "local": local_price,
                    "public": pub_price,
                    "diff_pct": round((local_price - pub_price) / pub_price * 100),
                })

    if drifts:
        unique_drifts = {}
        for d in drifts:
            if d["dest"] not in unique_drifts or abs(d["diff_pct"]) > abs(unique_drifts[d["dest"]]["diff_pct"]):
                unique_drifts[d["dest"]] = d
        state["price_drifts"] = list(unique_drifts.values())
        print(f"  Drifts detectes : {len(unique_drifts)} destinations")

    # 5. Alertes Discord
    alerts_sent = 0

    # 5a. Donnees publiques trop vieilles (> 8h = plus d'un cycle CI rate)
    stale = state.get("public_stale_minutes")
    if stale and stale > 480:
        _send_discord([{
            "title": "MesVols Watchdog - DONNEES PUBLIQUES PERIMEES",
            "description": (
                f"Les donnees publiques ont **{stale // 60}h{stale % 60:02d}**.\n"
                f"Dernier update : {pub_update}\n"
                f"Le pipeline CI a peut-etre echoue."
            ),
            "color": 0xd97706,
            "footer": {"text": now},
        }])
        alerts_sent += 1
        print(f"  ALERTE : donnees publiques perimees ({stale} min)")

    # 5b. Deals >= 30%
    notifiable = [d for d in deals if d.get("discount_pct", 0) >= 30] if deals else []
    if notifiable:
        embeds = []
        for deal in notifiable[:5]:  # Max 5 embeds
            is_direct = deal.get("num_stops", 1) == 0
            airline_code = deal.get("airline_code", "")
            search_url, search_label = build_search_link(
                deal.get("origin", "YUL"), deal.get("destination", ""),
                deal.get("depart", ""), deal.get("retour", ""),
                airline_code)
            stops_label = "Direct" if is_direct else f"{deal.get('num_stops', '?')} escale(s)"
            embeds.append({
                "title": f"{deal.get('route', '?')} — {deal['price']} $ (-{deal['discount_pct']}%)",
                "description": (
                    f"~~{deal['average']} $~~ → **{deal['price']} $**\n"
                    f"{deal.get('depart', '')} → {deal.get('retour', '')}\n"
                    f"{deal.get('airline', '?')} · {stops_label}\n"
                    f"[{search_label}]({search_url})"
                ),
                "color": 0x0d9488 if is_direct else 0xe85d24,
                "footer": {"text": f"Watchdog · {now}"},
            })
        _send_discord(embeds, content=f"**{len(notifiable)} aubaine(s) >= 30% detectee(s)**")
        alerts_sent += len(notifiable)
        print(f"  ALERTE : {len(notifiable)} deal(s) >= 30%")

    # 5c. Couverture degradee
    if coverage < 0.50:
        _send_discord([{
            "title": "MesVols Watchdog - COUVERTURE DEGRADEE",
            "description": (
                f"Seulement **{len(results)}/{expected}** routes scrapees "
                f"({int(coverage*100)}%).\n"
                f"Google Flights bloque peut-etre les requetes."
            ),
            "color": 0xd97706,
            "footer": {"text": now},
        }])
        alerts_sent += 1

    state["alerts_sent"] = alerts_sent
    state["status"] = "ok" if not state["errors"] else "degraded"
    _write_state(state)

    # Resume
    print(f"\n{'=' * 60}")
    print(f"Watchdog termine — {state['status']}")
    print(f"  Routes : {state['routes_scraped']}/{state['routes_expected']}")
    print(f"  Deals >= 30% : {len(notifiable)}")
    print(f"  Alertes envoyees : {alerts_sent}")
    if state.get("price_drifts"):
        print(f"  Drifts prix : {len(state['price_drifts'])}")
    print(f"  State ecrit dans watchdog_state.json")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            _send_discord([{
                "title": "MesVols Watchdog - CRASH",
                "description": f"**{type(exc).__name__}**: {exc}",
                "color": 0xe11d48,
                "footer": {"text": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")},
            }])
        except Exception:
            pass
        traceback.print_exc()
        sys.exit(1)
