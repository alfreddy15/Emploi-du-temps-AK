#!/usr/bin/env python3
"""
Lit les PDF d'emploi du temps déposés dans le dépôt (à la racine ou dans pdf/)
et met à jour emploi_du_temps.json. Lancé automatiquement par GitHub Actions.
"""
import sys
from pathlib import Path

import emploi_du_temps as edt


def main():
    pdfs = sorted(set(Path(".").glob("*.pdf")) | set(Path("pdf").glob("*.pdf")))
    if not pdfs:
        print("Aucun PDF trouvé.")
        return 0

    seances = edt.charger()
    erreurs = 0
    for pdf in pdfs:
        try:
            nouvelles, periode = edt.lire_pdf(pdf)
        except Exception as err:  # on continue avec les autres PDF
            print(f"[ECHEC] {pdf} : {err}")
            erreurs += 1
            continue
        seances = edt.fusionner(seances, nouvelles, periode)
        print(f"[OK] {pdf} : {len(nouvelles)} séance(s), du {periode[0]} au {periode[1]}")

    edt.sauvegarder(seances)
    print(f"Total : {len(seances)} séance(s) enregistrée(s).")
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
