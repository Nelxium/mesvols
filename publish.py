"""
MesVols - Prepare le dashboard statique pour GitHub Pages.
Copie les fichiers necessaires vers docs/.

Usage:
    python publish.py
"""

import shutil
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")

# Fichiers a copier vers docs/
FILES = {
    "data.js": "data.js",
    "ci_health.json": "ci_health.json",
}

# index.html est maintenu directement dans docs/ (base sur dashboard-mobile.html)
# On ne copie que data.js qui change a chaque cycle de scraping.


def publish():
    os.makedirs(DOCS, exist_ok=True)

    for src_name, dst_name in FILES.items():
        src = os.path.join(HERE, src_name)
        dst = os.path.join(DOCS, dst_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  {src_name} -> docs/{dst_name}")
        else:
            print(f"  ATTENTION: {src_name} introuvable, ignore.")

    print(f"\ndocs/ pret pour GitHub Pages.")
    print(f"  git add docs/ && git commit -m 'update data' && git push")


if __name__ == "__main__":
    publish()
