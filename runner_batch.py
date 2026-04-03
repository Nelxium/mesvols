"""
MesVols - Runner batch local.

Branche le scheduler au scraper : selectionne un batch de routes,
lance run_scraper(routes_subset=...), met a jour l'etat scheduler.

100% local — ne touche pas a main_ci.py, GitHub Actions, ni publish.py.

Usage :
    python runner_batch.py                  # dry-run (affiche la selection)
    python runner_batch.py --run            # execute le scrape + maj etat
    python runner_batch.py --run --batch 2  # batch de 2 routes max
"""

import sys
from datetime import datetime, timezone

from config import ROUTES
from scraper import run_scraper
from scheduler import (
    select_routes, load_state, save_state,
    MAX_BATCH_SIZE, STATE_PATH,
)


def update_state_from_results(state, candidates, results, now):
    """Met a jour l'etat scheduler apres un scrape reel.

    Determine le succes/echec PAR ROUTE en verifiant si des resultats
    existent pour la paire (origin, destination) dans la liste retournee
    par run_scraper(). Pas de modification du contrat scraper.

    Args:
        state: dict d'etat scheduler (mute en place)
        candidates: liste retournee par select_routes()
        results: liste de dicts retournee par run_scraper()
        now: datetime UTC du cycle

    Returns:
        dict {route_key: "success"|"failure"} pour les routes selectionnees
    """
    succeeded_keys = {(r["origin"], r["destination"]) for r in results}
    outcomes = {}

    for c in candidates:
        if not c["selected"]:
            continue
        key = c["key"]
        route_pair = (c["origin"], c["dest"])

        if key not in state:
            state[key] = {}
        state[key]["last_attempt"] = now.isoformat()

        if route_pair in succeeded_keys:
            state[key]["last_success"] = now.isoformat()
            state[key]["consecutive_failures"] = 0
            outcomes[key] = "success"
        else:
            state[key]["consecutive_failures"] = (
                state[key].get("consecutive_failures", 0) + 1)
            state[key]["last_failure"] = now.isoformat()
            outcomes[key] = "failure"

    return outcomes


def run_batch(batch_size=MAX_BATCH_SIZE, dry_run=True):
    """Orchestre un cycle batch local.

    Returns:
        (candidates, outcomes) ou (candidates, None) en dry-run
    """
    now = datetime.now(timezone.utc)
    state = load_state()
    candidates = select_routes(ROUTES, state, now, batch_size)

    selected = [c for c in candidates if c["selected"]]
    print(f"=== Runner batch — {now.strftime('%Y-%m-%d %H:%M')} UTC ===")
    print(f"Mode: {'DRY-RUN' if dry_run else 'EXECUTION'} | "
          f"Batch: {batch_size} | Selectionnees: {len(selected)}")

    if not selected:
        print("\nAucune route eligible. Rien a faire.")
        return candidates, None

    print()
    for c in selected:
        print(f"  {c['key']:10s}  prio={c['priority']}  "
              f"stale={c['staleness']:5.1f}x  -> {c['reason']}")

    if dry_run:
        print("\n(dry-run, aucun scrape lance)")
        return candidates, None

    # Execution reelle
    print(f"\nLancement du scrape pour {len(selected)} route(s)...\n")
    routes_subset = [(c["origin"], c["dest"]) for c in selected]

    try:
        results = run_scraper(routes_subset=routes_subset)
    except Exception as e:
        print(f"\nERREUR SCRAPER: {e}")
        # Marquer toutes les routes comme echec
        results = []

    outcomes = update_state_from_results(state, candidates, results, now)
    save_state(state)

    # Resume
    n_ok = sum(1 for v in outcomes.values() if v == "success")
    n_fail = sum(1 for v in outcomes.values() if v == "failure")
    print(f"\n=== Resultats ===")
    for key, outcome in outcomes.items():
        icon = "OK" if outcome == "success" else "FAIL"
        print(f"  {key:10s}  {icon}")
    print(f"\n{n_ok} succes, {n_fail} echec(s)")
    print(f"Etat ecrit dans {STATE_PATH}")

    return candidates, outcomes


def main():
    batch_size = MAX_BATCH_SIZE
    dry_run = True

    args = sys.argv[1:]
    if "--run" in args:
        dry_run = False
    if "--batch" in args:
        idx = args.index("--batch")
        if idx + 1 < len(args):
            batch_size = int(args[idx + 1])

    run_batch(batch_size=batch_size, dry_run=dry_run)


if __name__ == "__main__":
    main()
