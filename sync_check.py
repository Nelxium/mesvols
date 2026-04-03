#!/usr/bin/env python3
"""
sync_check.py — Détecte le drift accidentel entre docs/index.html (public)
et dashboard-mesvols.html (desktop).

Usage : python sync_check.py
  → Exit 0 : seules les différences attendues (légitimes)
  → Exit 1 : drift inattendu détecté, avec détail

Différences LÉGITIMES attendues (ne déclenchent pas d'alerte) :

  CSS desktop-only  : .empty / .empty-btn (état vide avec bouton CSV)
  CSS public-only   : @media(max-width:768px) (public accessible depuis mobile)
  HTML desktop-only : #empty div (UI état vide + chargement CSV + commande python)
  JS desktop-only   : skyFallback(), csv-input listener
  JS desktop-only   : auto-reload setInterval (public est statique)
  JS différent      : render() empty/data toggle (null-safe public vs direct desktop)
  JS différent      : render() upd display (mobile-aware public vs fixe desktop)
  Texte footer      : libellés différents (contexte différent)

Toute autre différence = drift accidentel à corriger.
"""
import difflib
import io
import sys
from pathlib import Path

# Force UTF-8 output on Windows where the default console may be cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
PUB = ROOT / "docs" / "index.html"
DSK = ROOT / "dashboard-mesvols.html"

# Fragments de contenu qui identifient une ligne comme "différence attendue".
# Une ligne modifiée est "connue" si son contenu (stripped) contient au moins
# un de ces fragments dans l'un OU l'autre fichier.
KNOWN_DIFF_FRAGMENTS = [
    # CSS desktop-only: état vide
    ".empty{",
    ".empty h2{",
    ".empty p{",
    ".empty-btn{",
    # CSS public-only: media query mobile (chaque ligne de ce bloc)
    "@media(max-width:768px)",
    "nav{padding:10px 16px",
    ".nav-r{flex-basis:100%",
    ".nav-time{font-size:.65rem}",
    ".signature{font-size:.45rem",
    ".signature b{font-size:.95rem}",
    ".hero{padding:32px 24px}",
    ".hero-stats{gap:20px}",
    ".grid{grid-template-columns:1fr}",
    ".chart-info{flex-wrap:wrap",
    ".deal-scroll{flex-direction:column}",
    "}",  # fermeture du bloc @media (public) — seule ligne diff CSS de ce type
    # HTML desktop-only: #empty div
    '<div id="empty"',
    "<h2>En attente de données</h2>",
    "python C:\\MesVols",
    'type="file" id="csv-input"',
    'class="empty-btn"',
    "</div>",  # fermeture du #empty div (desktop) — seule ligne diff HTML de ce type
    # Footer (libellés différents par design)
    "<footer>MesVols",
    # JS desktop-only: skyFallback
    "function skyFallback(",
    # JS desktop-only: CSV loader
    "document.getElementById('csv-input')",
    # JS desktop-only: auto-reload
    "setInterval(()=>location.reload",
    "// Auto-reload desactive",
    # JS différent: render() empty/data toggle (null-safe public vs direct desktop)
    "_em=document.getElementById('empty')",
    "document.getElementById('empty').style.display",
    # JS différent: render() upd display (mobile-aware public vs fixe desktop)
    "document.getElementById('upd').textContent=upd",
]


def is_known_diff(line_content: str) -> bool:
    s = line_content.strip()
    return any(frag in s for frag in KNOWN_DIFF_FRAGMENTS)


def main() -> int:
    if not PUB.exists():
        print(f"[sync_check] ERREUR : fichier introuvable : {PUB}")
        return 2
    if not DSK.exists():
        print(f"[sync_check] ERREUR : fichier introuvable : {DSK}")
        return 2

    pub_lines = PUB.read_text(encoding="utf-8").splitlines()
    dsk_lines = DSK.read_text(encoding="utf-8").splitlines()

    diff = list(difflib.unified_diff(pub_lines, dsk_lines, fromfile=str(PUB), tofile=str(DSK), lineterm="", n=0))

    unexpected = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if not (line.startswith("+") or line.startswith("-")):
            continue
        content = line[1:]
        if not content.strip():
            continue  # ligne vide : neutre
        if not is_known_diff(content):
            unexpected.append(line)

    if unexpected:
        print(f"[sync_check] DRIFT DÉTECTÉ — {len(unexpected)} ligne(s) inattendue(s) :\n")
        for ln in unexpected:
            print(f"  {ln}")
        print()
        print("  -> Appliquer le patch manquant a l'un des deux fichiers, puis relancer sync_check.py")
        return 1

    expected_count = sum(
        1 for line in diff
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("---") and not line.startswith("+++")
        and line[1:].strip()
    )
    print(f"[sync_check] OK — {expected_count} différence(s) attendue(s) uniquement entre :")
    print(f"  public  : {PUB.relative_to(ROOT)}")
    print(f"  desktop : {DSK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
