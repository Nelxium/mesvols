"""
MesVols - Scheduler V2 (dry-run prototype).

Selectionne quelles routes lancer au prochain cycle, sans executer
le scrape ni toucher aux artefacts publics (data.js, docs/, CSV).

Usage :
    python scheduler.py              # dry-run, affiche la selection
    python scheduler.py --json       # idem, sortie JSON
    python scheduler.py --apply      # ecrit l'etat (simule un cycle)

Ce fichier est 100% local, non branche sur GitHub Actions.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from config import ROUTES

# ---------------------------------------------------------------------------
# Configuration scheduling par route
# Cle = (origin, dest). Interval en minutes. Priority : 1 = max.
# Les routes absentes de ce dict utilisent les defaults.
# ---------------------------------------------------------------------------
ROUTE_SCHEDULE = {
    ("YUL", "CDG"): {"priority": 1, "interval_min": 360},   # Paris : toutes les 6h
    ("YUL", "CUN"): {"priority": 2, "interval_min": 360},   # Cancun
    ("YUL", "JFK"): {"priority": 2, "interval_min": 360},   # New York
    ("YUL", "PUJ"): {"priority": 3, "interval_min": 480},   # Punta Cana : 8h
    ("YUL", "MIA"): {"priority": 3, "interval_min": 480},   # Miami
    ("YUL", "NRT"): {"priority": 4, "interval_min": 720},   # Tokyo Narita : 12h
    ("YUL", "HND"): {"priority": 4, "interval_min": 720},   # Tokyo Haneda
    ("YUL", "HNL"): {"priority": 5, "interval_min": 720},   # Hawai
}

DEFAULT_PRIORITY = 5
DEFAULT_INTERVAL_MIN = 720  # 12h par defaut
MAX_BATCH_SIZE = 4          # max routes par cycle dry-run
MAX_BACKOFF_MULT = 8        # plafond multiplicateur backoff

STATE_PATH = os.path.join(os.path.dirname(__file__), "scheduler_state.json")


# ---------------------------------------------------------------------------
# Logique pure — testable sans effets de bord
# ---------------------------------------------------------------------------

def _get_route_config(origin, dest):
    """Retourne (priority, interval_minutes) pour une route."""
    cfg = ROUTE_SCHEDULE.get((origin, dest), {})
    return (
        cfg.get("priority", DEFAULT_PRIORITY),
        cfg.get("interval_min", DEFAULT_INTERVAL_MIN),
    )


def _backoff_multiplier(consecutive_failures):
    """Multiplicateur exponentiel plafonne : 2^n, max MAX_BACKOFF_MULT."""
    if consecutive_failures <= 0:
        return 1
    return min(2 ** consecutive_failures, MAX_BACKOFF_MULT)


def select_routes(routes, state, now, batch_size=MAX_BATCH_SIZE):
    """Selectionne les routes a lancer, avec explication.

    Args:
        routes: liste de (origin, dest, name) depuis config.ROUTES
        state: dict {route_key: {last_attempt, last_success,
                                  consecutive_failures}} ou {}
        now: datetime UTC
        batch_size: nombre max de routes a selectionner

    Returns:
        list de dicts, tries par score decroissant, chacun contenant :
        - origin, dest, name
        - priority, interval_min
        - eligible (bool)
        - staleness (float, >= 0)
        - backoff_mult (int)
        - next_eligible_at (str ISO)
        - selected (bool)
        - reason (str)
    """
    candidates = []

    for origin, dest, name in routes:
        key = f"{origin}-{dest}"
        priority, interval_min = _get_route_config(origin, dest)
        interval = timedelta(minutes=interval_min)

        rs = state.get(key, {})
        last_attempt_str = rs.get("last_attempt")
        last_success_str = rs.get("last_success")
        consecutive_failures = rs.get("consecutive_failures", 0)

        last_attempt = (datetime.fromisoformat(last_attempt_str)
                        if last_attempt_str else None)
        last_success = (datetime.fromisoformat(last_success_str)
                        if last_success_str else None)

        # Backoff
        bmult = _backoff_multiplier(consecutive_failures)
        effective_interval = interval * bmult

        # Eligibilite
        if last_attempt is None:
            eligible = True
            next_eligible_at = now  # jamais lance → eligible immediatement
        else:
            next_eligible_at = last_attempt + effective_interval
            eligible = now >= next_eligible_at

        # Staleness : combien de fois l'intervalle cible est depasse
        if last_success is None:
            staleness = 999.0  # jamais reussi → maximalement stale
        else:
            elapsed = (now - last_success).total_seconds()
            target = interval.total_seconds()
            staleness = elapsed / target if target > 0 else 0.0

        candidates.append({
            "origin": origin,
            "dest": dest,
            "name": name,
            "key": key,
            "priority": priority,
            "interval_min": interval_min,
            "eligible": eligible,
            "staleness": round(staleness, 2),
            "backoff_mult": bmult,
            "consecutive_failures": consecutive_failures,
            "next_eligible_at": next_eligible_at.isoformat(),
            "selected": False,
            "reason": "",
        })

    # Tri deterministe : eligible d'abord, puis staleness desc, puis priority asc,
    # puis key asc (tie-breaker alphabetique pour determinisme total)
    candidates.sort(key=lambda c: (
        not c["eligible"],      # eligible=True first (False > True, negate)
        -c["staleness"],        # most stale first
        c["priority"],          # lower priority number first
        c["key"],               # alphabetical tie-breaker
    ))

    # Selectionner le batch
    selected_count = 0
    for c in candidates:
        if selected_count >= batch_size:
            c["reason"] = "batch plein"
        elif not c["eligible"]:
            c["reason"] = f"pas eligible avant {c['next_eligible_at']}"
        else:
            c["selected"] = True
            c["reason"] = _explain(c)
            selected_count += 1

    # Raisons pour les non-selectionnes eligibles (depassees par le batch)
    for c in candidates:
        if not c["selected"] and c["eligible"] and not c["reason"]:
            c["reason"] = "batch plein"

    return candidates


def _explain(c):
    """Genere une explication courte pour une route selectionnee."""
    parts = []
    if c["staleness"] >= 2.0:
        parts.append(f"stale x{c['staleness']:.1f}")
    if c["consecutive_failures"] > 0:
        parts.append(f"backoff x{c['backoff_mult']}")
    if c["priority"] <= 2:
        parts.append(f"prio {c['priority']}")
    if not parts:
        parts.append("eligible")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# I/O state
# ---------------------------------------------------------------------------

def load_state(path=STATE_PATH):
    """Charge l'etat depuis le fichier JSON. Retourne {} si absent/invalide."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state, path=STATE_PATH):
    """Ecrit l'etat dans le fichier JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def apply_dry_run(state, selected, now):
    """Simule l'application d'un cycle : met a jour last_attempt pour les
    routes selectionnees (simule un succes pour le dry-run)."""
    for c in selected:
        if not c["selected"]:
            continue
        key = c["key"]
        if key not in state:
            state[key] = {}
        state[key]["last_attempt"] = now.isoformat()
        state[key]["last_success"] = now.isoformat()
        state[key]["consecutive_failures"] = 0
    return state


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    state = load_state()
    result = select_routes(ROUTES, state, now)

    selected = [c for c in result if c["selected"]]
    skipped = [c for c in result if not c["selected"]]

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== Scheduler V2 dry-run — {now.strftime('%Y-%m-%d %H:%M')} UTC ===")
        print(f"Routes: {len(ROUTES)} | Batch max: {MAX_BATCH_SIZE} | "
              f"Selectionnees: {len(selected)}\n")

        if selected:
            print("SELECTIONNEES:")
            for c in selected:
                print(f"  {c['key']:10s}  prio={c['priority']}  "
                      f"stale={c['staleness']:5.1f}x  "
                      f"backoff={c['backoff_mult']}x  "
                      f"-> {c['reason']}")

        if skipped:
            print("\nNON SELECTIONNEES:")
            for c in skipped:
                print(f"  {c['key']:10s}  prio={c['priority']}  "
                      f"stale={c['staleness']:5.1f}x  "
                      f"backoff={c['backoff_mult']}x  "
                      f"-> {c['reason']}")

    if "--apply" in sys.argv:
        state = apply_dry_run(state, result, now)
        save_state(state)
        print(f"\nEtat ecrit dans {STATE_PATH}")


if __name__ == "__main__":
    main()
