#!/usr/bin/env python3
"""
Lit les PDF d'emploi du temps déposés dans le dépôt (à la racine ou dans pdf/)
et met à jour emploi_du_temps.json et meta.json (nom de la classe, lu dans le PDF).
Lancé automatiquement par GitHub Actions.

Un dépôt = une classe : si le PDF est celui d'une AUTRE classe que celle de meta.json,
on repart de zéro au lieu de mélanger les deux emplois du temps.
"""
import json
import re
import sys
from pathlib import Path

import emploi_du_temps as edt

META = Path("meta.json")


def nom_classe(chemin):
    """« LICENCE 2 (L2) B IT » -> « L2 B IT » (None si non reconnu)."""
    pdfplumber = edt._ouvrir_pdfplumber()
    with pdfplumber.open(str(chemin)) as pdf:
        texte = (pdf.pages[0].extract_text() if pdf.pages else "") or ""
    lignes = [l.strip() for l in texte.splitlines() if l.strip()]
    for l in lignes:
        m = re.search(r"\((L\d|M\d|B\d)\)\s*(.+)$", l, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", f"{m.group(1)} {m.group(2)}").strip().upper()
    for l in lignes:
        if re.match(r"^(licence|master|bachelor|classe|fili[eè]re)\b", l, re.IGNORECASE):
            return l
    return None


def norm(t):
    return re.sub(r"\s+", " ", edt._sans_accents(t or "")).strip().upper()


def lire_meta():
    try:
        return json.loads(META.read_text(encoding="utf-8")).get("classe")
    except (OSError, ValueError):
        return None


def main():
    pdfs = sorted(set(Path(".").glob("*.pdf")) | set(Path("pdf").glob("*.pdf")))
    if not pdfs:
        print("Aucun PDF trouvé.")
        return 0

    classe = lire_meta()
    seances = edt.charger() if edt.DATA_FILE.exists() else []
    erreurs = 0
    for pdf in pdfs:
        try:
            nouvelles, periode = edt.lire_pdf(pdf)
            nom = nom_classe(pdf)
        except Exception as err:  # on continue avec les autres PDF
            print(f"[ECHEC] {pdf} : {err}")
            erreurs += 1
            continue
        if nom and classe and norm(nom) != norm(classe):
            print(f"[INFO] {pdf} : nouvelle classe « {nom} » (avant : « {classe} ») -> on repart de zéro.")
            seances = []
        if nom:
            classe = nom
        seances = edt.fusionner(seances, nouvelles, periode)
        print(f"[OK] {pdf} : {len(nouvelles)} séance(s), du {periode[0]} au {periode[1]}"
              + (f", classe {nom}" if nom else ""))

    edt.sauvegarder(seances)
    if classe:
        META.write_text(json.dumps({"classe": classe}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Total : {len(seances)} séance(s) enregistrée(s).")
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
