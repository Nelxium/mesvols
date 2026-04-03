"""
MesVols - Prepare le dashboard statique pour GitHub Pages.
Copie les fichiers necessaires vers docs/.

Usage:
    python publish.py
"""

import filecmp
import shutil
import os
import sys

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

    errors = []
    for src_name, dst_name in FILES.items():
        src = os.path.join(HERE, src_name)
        dst = os.path.join(DOCS, dst_name)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            if filecmp.cmp(src, dst, shallow=False):
                print(f"  {src_name} -> docs/{dst_name} OK")
            else:
                print(f"  ERROR: docs/{dst_name} differs from {src_name} after copy!")
                errors.append(dst_name)
        else:
            print(f"  ATTENTION: {src_name} introuvable, ignore.")

    if errors:
        print(f"\nERROR: post-publish verification failed for: {', '.join(errors)}")
        sys.exit(1)

    print(f"\ndocs/ pret pour GitHub Pages.")


if __name__ == "__main__":
    publish()
