#!/usr/bin/env python3
"""
Mon emploi du temps - L2 B IT (Tkinter)

Fonctions :
  - Affiche l'emploi du temps en TABLEAU (jours en colonnes, Matin / Après-midi
    en lignes, navigation par semaine) + un onglet « Liste »
  - Ajoute / modifie / supprime les séances
  - Lit automatiquement le PDF de l'emploi du temps envoyé par l'école
    (bouton « Importer PDF », bouton « Dernier EDT », et détection au lancement
    d'un fichier EDT*.pdf dans le dossier Téléchargements)
  - Importe aussi un emploi du temps depuis un fichier CSV ou JSON
  - Exporte :
      * un fichier .ics  -> s'importe dans Google Agenda / agenda du téléphone
                            (avec rappel 30 min avant chaque séance)
      * une page .html   -> à envoyer sur le téléphone (WhatsApp, mail...) et à ouvrir
      * CSV / JSON       -> sauvegarde ou partage

Installation (une seule fois) :  pip install pdfplumber
Lancer :  python emploi_du_temps.py
Diagnostic PDF :  python emploi_du_temps.py --pdf mon_edt.pdf
                  python emploi_du_temps.py --debug-pdf mon_edt.pdf   (affiche le tableau brut)
"""

import csv
import hashlib
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # permet de tester la logique sans interface graphique
    tk = ttk = filedialog = messagebox = None

_Frame = ttk.Frame if tk is not None else object

# ----------------------------------------------------------------------------
# Réglages
# ----------------------------------------------------------------------------
DATA_FILE = Path(__file__).with_name("emploi_du_temps.json")
ETAT_FILE = Path(__file__).with_name("emploi_du_temps_etat.json")
# Dossiers où chercher le PDF reçu (WhatsApp enregistre dans Téléchargements)
DOSSIERS_PDF = [Path.home() / d for d in ("Downloads", "Téléchargements", "Desktop", "Bureau")]
# Les PDF de l'école s'appellent EDT_SEMAINE4_L2_B_IT.pdf : on cherche ce préfixe
PREFIXE_PDF = "edt"
TITRE_CALENDRIER = "Emploi du temps L2 B IT"
# Décalage horaire par rapport à UTC (Lomé / Togo = GMT, donc 0)
UTC_OFFSET_HOURS = 0
# Rappel avant chaque séance (minutes) dans le fichier .ics
RAPPEL_MINUTES = 30

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
JOURS_LONGS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
CHAMPS = ["date", "debut", "fin", "matiere", "intervenant", "seance", "type"]
TYPES = ["Cours", "Contrôle", "TPE", "TP", "Autre"]


def _s(date, debut, fin, matiere, intervenant="", seance="", type_="Cours"):
    return {
        "date": date, "debut": debut, "fin": fin, "matiere": matiere,
        "intervenant": intervenant, "seance": seance, "type": type_,
    }


MATH = "Mathématiques (Dénombrements et Probabilités)"
IRO = "Initiation à la Recherche Opérationnelle"
UIUX = "UI / UX Responsive Design"
WIN = "Administration et maintenance Windows Server 1"

# Semaine du 16 au 21 novembre 2026 (d'après le PDF)
DEFAULT = [
    _s("2026-11-16", "08:00", "12:00", MATH, "DR AGBOKOU", "7/8"),
    _s("2026-11-16", "13:00", "17:00", IRO, "DR TCHAZINO", "6/8"),
    _s("2026-11-17", "08:00", "12:00", IRO + " (FIN)", "DR TCHAZINO", "8/8"),
    _s("2026-11-17", "13:00", "17:00", MATH + " (FIN)", "DR AGBOKOU", "8/8"),
    _s("2026-11-18", "08:00", "12:00", UIUX, "M ATIKOSSIE", "4/6"),
    _s("2026-11-18", "14:00", "16:00", "Contrôle Continu : " + IRO, "DR TCHAZINO", "1/1", "Contrôle"),
    _s("2026-11-19", "08:00", "12:00", UIUX, "M ATIKOSSIE", "5/6"),
    _s("2026-11-19", "13:00", "17:00", WIN, "M BOUKLINAM", "1/6"),
    _s("2026-11-20", "08:00", "12:00", UIUX + " (FIN)", "M ATIKOSSIE", "6/6"),
    _s("2026-11-20", "13:00", "17:00", "TPE", "", "", "TPE"),
]


# ----------------------------------------------------------------------------
# Logique (sans interface)
# ----------------------------------------------------------------------------
def parse_date(texte):
    """Accepte JJ/MM/AAAA, AAAA-MM-JJ ou JJ-MM-AAAA. Retourne un objet date."""
    texte = str(texte).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Date invalide : « {texte} » (format attendu JJ/MM/AAAA)")


def parse_heure(texte):
    """Accepte 08:00, 8h, 8h30, 14H..."""
    t = str(texte).strip().lower().replace("h", ":")
    if t.endswith(":"):
        t += "00"
    for fmt in ("%H:%M", "%H"):
        try:
            return datetime.strptime(t, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Heure invalide : « {texte} » (format attendu HH:MM)")


def normaliser(entree):
    """Nettoie une séance et vérifie sa validité. Retourne un nouveau dict."""
    e = {c: str(entree.get(c, "")).strip() for c in CHAMPS}
    d = parse_date(e["date"])
    h1, h2 = parse_heure(e["debut"]), parse_heure(e["fin"])
    if not e["matiere"]:
        raise ValueError("La matière est obligatoire.")
    if h2 <= h1:
        raise ValueError("L'heure de fin doit être après l'heure de début.")
    e["date"] = d.isoformat()
    e["debut"], e["fin"] = h1.strftime("%H:%M"), h2.strftime("%H:%M")
    if not e["type"]:
        e["type"] = "Cours"
    return e


def trier(seances):
    return sorted(seances, key=lambda e: (e["date"], e["debut"]))


def charger():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return trier([normaliser(e) for e in data])
        except (ValueError, OSError):
            pass
    return trier([dict(e) for e in DEFAULT])


def sauvegarder(seances):
    DATA_FILE.write_text(
        json.dumps(trier(seances), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def lire_fichier(chemin):
    """Lit un CSV ou un JSON et retourne une liste de séances normalisées."""
    chemin = Path(chemin)
    if chemin.suffix.lower() == ".json":
        brut = json.loads(chemin.read_text(encoding="utf-8-sig"))
    else:
        with open(chemin, newline="", encoding="utf-8-sig") as f:
            echantillon = f.read(2048)
            f.seek(0)
            sep = ";" if echantillon.count(";") > echantillon.count(",") else ","
            brut = list(csv.DictReader(f, delimiter=sep))
    resultat = []
    for i, ligne in enumerate(brut, start=1):
        ligne = {str(k).strip().lower(): v for k, v in ligne.items() if k}
        try:
            resultat.append(normaliser(ligne))
        except ValueError as err:
            raise ValueError(f"Ligne {i} : {err}") from err
    return resultat


def exporter_csv(seances, chemin):
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CHAMPS, delimiter=";")
        w.writeheader()
        w.writerows(trier(seances))


# ----------------------------------------------------------------------------
# Lecture automatique du PDF de l'emploi du temps
# ----------------------------------------------------------------------------
_RE_HEURES = re.compile(
    r"(\d{1,2})\s*[hH:]\s*(\d{2})?\s*(?:-|–|—|à|a)\s*(\d{1,2})\s*[hH:]\s*(\d{2})?"
)
_RE_DATE_TEXTE = re.compile(r"(\d{1,2})\s*[-/. ]\s*([A-Za-zÀ-ÿ]+)\.?\s*[-/. ]\s*(\d{2,4})")
_RE_DATE_NUM = re.compile(r"(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{2,4})")
_RE_SEANCE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_RE_PROF = re.compile(r"^(?:DR|DRA|PR|PROF|MR|MME|MLLE|M)\b\.?\s+\S", re.IGNORECASE)
_MOIS = {"jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "aou": 8,
         "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _sans_accents(texte):
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def _numero_mois(texte):
    t = _sans_accents(texte).lower().strip(".")
    if t.startswith("juil"):
        return 7
    if t.startswith("juin"):
        return 6
    return _MOIS.get(t[:3])


def _date_entete(cellule):
    """Trouve une date comme '16-nov.-26' ou '16/11/2026' dans une cellule d'en-tête."""
    m = _RE_DATE_TEXTE.search(cellule)
    if m:
        mois = _numero_mois(m.group(2))
        if mois:
            annee = int(m.group(3))
            annee += 2000 if annee < 100 else 0
            try:
                return datetime(annee, mois, int(m.group(1))).date()
            except ValueError:
                return None
    m = _RE_DATE_NUM.search(cellule)
    if m:
        annee = int(m.group(3))
        annee += 2000 if annee < 100 else 0
        try:
            return datetime(annee, int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            return None
    return None


def _heure(h, m):
    return f"{int(h):02d}:{int(m or 0):02d}"


def _lire_tableau(table):
    """Transforme un tableau extrait du PDF en séances. Retourne (séances, dates d'en-tête)."""
    cellules = [[(c or "").strip() for c in ligne] for ligne in table]

    # 1. ligne d'en-tête : quelle colonne correspond à quelle date
    dates, entete = {}, None
    for i, ligne in enumerate(cellules):
        trouvees = {j: d for j, c in enumerate(ligne) if (d := _date_entete(c))}
        if len(trouvees) >= 2:
            dates, entete = trouvees, i
            break
    if entete is None:
        return [], []

    # 2. regroupement des lignes par plage horaire (la 1re colonne peut être fusionnée)
    blocs = []
    for ligne in cellules[entete + 1:]:
        m = _RE_HEURES.search(ligne[0]) if ligne else None
        if m:
            debut, fin = _heure(m.group(1), m.group(2)), _heure(m.group(3), m.group(4))
            if not (blocs and (blocs[-1]["debut"], blocs[-1]["fin"]) == (debut, fin)):
                blocs.append({"debut": debut, "fin": fin, "lignes": []})
        if blocs:
            blocs[-1]["lignes"].append(ligne)

    # 3. une séance par bloc horaire et par jour
    seances = []
    for bloc in blocs:
        if any("PAUSE" in c.upper() for l in bloc["lignes"] for c in l):
            continue
        for col, jour in dates.items():
            textes = [l[col] for l in bloc["lignes"] if col < len(l) and l[col]]
            if not textes:
                continue

            toutes = [ln.strip() for t in textes for ln in t.splitlines() if ln.strip()]
            seance = ""
            for ln in toutes:
                m = _RE_SEANCE.match(ln)
                if m:
                    seance = f"{m.group(1)}/{m.group(2)}"
                    break

            def propre(t):
                return [ln.strip() for ln in t.splitlines()
                        if ln.strip() and not _RE_SEANCE.match(ln)]

            if len(textes) >= 2:   # ligne du cours + ligne de l'intervenant
                prof = " ".join(propre(textes[-1]))
                lignes_cours = [ln for t in textes[:-1] for ln in propre(t)]
            else:
                lignes_cours = propre(textes[0])
                prof = ""
                if len(lignes_cours) > 1 and _RE_PROF.match(lignes_cours[-1]):
                    prof = lignes_cours.pop()

            texte = " ".join(lignes_cours)
            debut, fin = bloc["debut"], bloc["fin"]
            m = _RE_HEURES.search(texte)            # ex : « 14H à 16H » pour un contrôle
            if m:
                debut, fin = _heure(m.group(1), m.group(2)), _heure(m.group(3), m.group(4))
                texte = (texte[:m.start()] + texte[m.end():]).strip()
            texte = re.sub(r"\s+", " ", texte)
            texte = re.sub(r"\s*:\s*", " : ", texte, count=1)
            texte = re.sub(r"\s+FIN$", " (FIN)", texte)
            if not texte:
                continue

            norm = _sans_accents(texte).lower()
            if norm.startswith(("controle", "examen", "devoir", "partiel")):
                type_ = "Contrôle"
            elif norm.startswith("tpe"):
                type_ = "TPE"
            elif norm.startswith("tp"):
                type_ = "TP"
            else:
                type_ = "Cours"

            try:
                seances.append(normaliser({
                    "date": jour.isoformat(), "debut": debut, "fin": fin,
                    "matiere": texte, "intervenant": prof, "seance": seance, "type": type_,
                }))
            except ValueError:
                continue
    return seances, sorted(dates.values())


def _ouvrir_pdfplumber():
    try:
        import pdfplumber
    except ImportError as err:
        raise RuntimeError(
            "Le module « pdfplumber » est nécessaire pour lire les PDF.\n"
            "Installez-le avec :  pip install pdfplumber"
        ) from err
    return pdfplumber


def lire_pdf(chemin):
    """Lit le PDF de l'emploi du temps. Retourne (séances, (premier_jour, dernier_jour))."""
    pdfplumber = _ouvrir_pdfplumber()
    seances, jours = [], []
    with pdfplumber.open(str(chemin)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                s, d = _lire_tableau(table)
                seances += s
                jours += d
    if not seances:
        raise ValueError(
            "Aucune séance reconnue dans ce PDF.\n"
            "Lancez « python emploi_du_temps.py --debug-pdf fichier.pdf » pour voir ce qui est lu."
        )
    return trier(seances), (min(jours).isoformat(), max(jours).isoformat())


def fusionner(existantes, nouvelles, periode):
    """Remplace les séances de la période (la semaine du PDF) et garde le reste."""
    debut, fin = periode
    gardees = [e for e in existantes if not (debut <= e["date"] <= fin)]
    return trier(gardees + nouvelles)


def trouver_dernier_pdf():
    """Retourne le PDF EDT*.pdf le plus récent des dossiers de téléchargement, ou None."""
    candidats = []
    for dossier in DOSSIERS_PDF:
        if dossier.is_dir():
            for f in dossier.iterdir():
                n = f.name.lower()
                if f.is_file() and n.startswith(PREFIXE_PDF) and n.endswith(".pdf"):
                    candidats.append(f)
    return max(candidats, key=lambda f: f.stat().st_mtime) if candidats else None


def signature(chemin):
    return f"{Path(chemin).name}|{int(Path(chemin).stat().st_mtime)}"


def charger_etat():
    try:
        return json.loads(ETAT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sauver_etat(etat):
    try:
        ETAT_FILE.write_text(json.dumps(etat), encoding="utf-8")
    except OSError:
        pass


def _ics_texte(s):
    return (
        str(s).replace("\\", "\\\\").replace(";", "\\;")
        .replace(",", "\\,").replace("\n", "\\n")
    )


def _ics_dt(dt_local):
    utc = dt_local - timedelta(hours=UTC_OFFSET_HOURS)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def vers_ics(seances):
    """Génère le contenu d'un fichier calendrier .ics (heures en UTC)."""
    maintenant = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Mon Emploi du Temps//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_texte(TITRE_CALENDRIER)}",
    ]
    for e in trier(seances):
        d = parse_date(e["date"])
        debut = datetime.combine(d, parse_heure(e["debut"]))
        fin = datetime.combine(d, parse_heure(e["fin"]))
        uid = hashlib.md5(
            "|".join(e[c] for c in CHAMPS).encode("utf-8")
        ).hexdigest() + "@edt-l2bit"
        desc = []
        if e["intervenant"]:
            desc.append(f"Intervenant : {e['intervenant']}")
        if e["seance"]:
            desc.append(f"Séance : {e['seance']}")
        if e["type"] and e["type"] != "Cours":
            desc.append(f"Type : {e['type']}")
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{maintenant}",
            f"DTSTART:{_ics_dt(debut)}",
            f"DTEND:{_ics_dt(fin)}",
            f"SUMMARY:{_ics_texte(e['matiere'])}",
            f"DESCRIPTION:{_ics_texte(chr(10).join(desc))}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_texte(e['matiere'])}",
            f"TRIGGER:-PT{RAPPEL_MINUTES}M",
            "END:VALARM",
            "END:VEVENT",
        ]
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"


def vers_html(seances):
    """Page HTML autonome, lisible sur téléphone, groupée par jour."""
    par_jour = {}
    for e in trier(seances):
        par_jour.setdefault(e["date"], []).append(e)

    blocs = []
    for iso, items in par_jour.items():
        d = parse_date(iso)
        titre = f"{JOURS_LONGS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
        cartes = []
        for e in items:
            classe = {"Contrôle": "ctrl", "TPE": "tpe"}.get(e["type"], "")
            infos = " · ".join(x for x in (e["intervenant"], e["seance"]) if x)
            cartes.append(
                f'<div class="carte {classe}">'
                f'<div class="h">{e["debut"]} – {e["fin"]}</div>'
                f'<div class="m">{html.escape(e["matiere"])}</div>'
                + (f'<div class="i">{html.escape(infos)}</div>' if infos else "")
                + "</div>"
            )
        blocs.append(f'<h2 data-d="{iso}">{titre}</h2>' + "".join(cartes))

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(TITRE_CALENDRIER)}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:0;padding:12px;background:#f3f4f6;color:#111}}
 h1{{font-size:1.2rem;margin:4px 0 12px}}
 h2{{font-size:1rem;margin:18px 0 6px;color:#1f4e9c}}
 h2.auj{{background:#1f4e9c;color:#fff;padding:4px 8px;border-radius:6px}}
 .carte{{background:#fff;border-left:5px solid #1f4e9c;border-radius:8px;padding:8px 10px;margin:6px 0;box-shadow:0 1px 2px #0002}}
 .carte.ctrl{{border-color:#e07b00;background:#fff4e8}}
 .carte.tpe{{border-color:#16a34a;background:#eafaf0}}
 .h{{font-weight:700}} .m{{margin:2px 0}} .i{{color:#555;font-size:.9rem}}
</style></head><body>
<h1>{html.escape(TITRE_CALENDRIER)}</h1>
{''.join(blocs)}
<script>
 var t=new Date(),iso=t.getFullYear()+"-"+String(t.getMonth()+1).padStart(2,"0")+"-"+String(t.getDate()).padStart(2,"0");
 document.querySelectorAll("h2").forEach(function(h){{if(h.dataset.d===iso){{h.classList.add("auj");h.scrollIntoView();}}}});
</script>
</body></html>
"""


# ----------------------------------------------------------------------------
# Interface Tkinter
# ----------------------------------------------------------------------------
class Dialogue:
    """Fenêtre d'ajout / modification d'une séance."""

    def __init__(self, parent, titre, valeurs=None):
        self.resultat = None
        v = valeurs or {}
        self.top = tk.Toplevel(parent)
        self.top.title(titre)
        self.top.transient(parent)
        self.top.resizable(False, False)

        cadre = ttk.Frame(self.top, padding=12)
        cadre.pack()

        d = v.get("date")
        date_aff = parse_date(d).strftime("%d/%m/%Y") if d else ""
        self.vars = {
            "date": tk.StringVar(value=date_aff),
            "debut": tk.StringVar(value=v.get("debut", "08:00")),
            "fin": tk.StringVar(value=v.get("fin", "12:00")),
            "matiere": tk.StringVar(value=v.get("matiere", "")),
            "intervenant": tk.StringVar(value=v.get("intervenant", "")),
            "seance": tk.StringVar(value=v.get("seance", "")),
            "type": tk.StringVar(value=v.get("type", "Cours")),
        }
        libelles = [
            ("date", "Date (JJ/MM/AAAA)"), ("debut", "Début (HH:MM)"),
            ("fin", "Fin (HH:MM)"), ("matiere", "Matière"),
            ("intervenant", "Intervenant"), ("seance", "Séance (ex : 4/6)"),
            ("type", "Type"),
        ]
        for i, (cle, txt) in enumerate(libelles):
            ttk.Label(cadre, text=txt).grid(row=i, column=0, sticky="w", pady=3)
            if cle == "type":
                w = ttk.Combobox(cadre, textvariable=self.vars[cle], values=TYPES, width=38)
            else:
                w = ttk.Entry(cadre, textvariable=self.vars[cle], width=40)
            w.grid(row=i, column=1, padx=(10, 0), pady=3)

        boutons = ttk.Frame(cadre)
        boutons.grid(row=len(libelles), column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(boutons, text="Annuler", command=self.top.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(boutons, text="Enregistrer", command=self.valider).pack(side="right")

        self.top.bind("<Return>", lambda _e: self.valider())
        self.top.bind("<Escape>", lambda _e: self.top.destroy())
        self.top.grab_set()
        parent.wait_window(self.top)

    def valider(self):
        try:
            self.resultat = normaliser({k: v.get() for k, v in self.vars.items()})
        except ValueError as err:
            messagebox.showerror("Champ invalide", str(err), parent=self.top)
            return
        self.top.destroy()


class VueTableau(_Frame):
    """Emploi du temps en grille : jours en colonnes, Matin / Après-midi en lignes."""

    COULEURS = {"Cours": "#e3eeff", "Contrôle": "#ffe3c2", "TPE": "#d6f5df",
                "TP": "#efe3ff", "Autre": "#eeeeee"}

    def __init__(self, parent, app):
        super().__init__(parent, padding=6)
        self.app = app
        auj = datetime.now().date()
        self.lundi = auj - timedelta(days=auj.weekday())

        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="◀", width=3, command=lambda: self.changer(-7)).pack(side="left")
        ttk.Button(nav, text="▶", width=3, command=lambda: self.changer(7)).pack(side="right")
        ttk.Button(nav, text="Aujourd'hui", command=self.aujourdhui).pack(side="right", padx=6)
        self.titre = ttk.Label(nav, anchor="center", font=("Segoe UI", 11, "bold"))
        self.titre.pack(side="left", expand=True, fill="x")

        self.grille = tk.Frame(self, bg="#999999")
        self.grille.pack(fill="both", expand=True)

    def changer(self, jours):
        self.lundi += timedelta(days=jours)
        self.dessiner()

    def aujourdhui(self):
        auj = datetime.now().date()
        self.lundi = auj - timedelta(days=auj.weekday())
        self.dessiner()

    @staticmethod
    def _texte(e):
        t = f"{e['debut']} - {e['fin']}\n{e['matiere']}"
        infos = " · ".join(x for x in (e["intervenant"], e["seance"]) if x)
        return t + (f"\n{infos}" if infos else "")

    def dessiner(self):
        for w in self.grille.winfo_children():
            w.destroy()
        jours = [self.lundi + timedelta(days=i) for i in range(6)]   # Lun -> Sam
        auj = datetime.now().date()
        self.titre.config(text=f"Semaine du {jours[0]:%d/%m/%Y} au {jours[-1]:%d/%m/%Y}")

        police = ("Segoe UI", 10, "bold")
        tk.Label(self.grille, bg="#1f4e9c").grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        for c, d in enumerate(jours, start=1):
            tk.Label(
                self.grille, text=f"{JOURS_LONGS[d.weekday()]}\n{d:%d/%m}", font=police,
                bg="#e07b00" if d == auj else "#1f4e9c", fg="white", pady=6,
            ).grid(row=0, column=c, sticky="nsew", padx=1, pady=1)
            self.grille.columnconfigure(c, weight=1, uniform="jour")

        periodes = [("Matin", lambda e: e["debut"] < "12:30"),
                    ("Après-\nmidi", lambda e: e["debut"] >= "12:30")]
        for r, (nom, test) in enumerate(periodes, start=1):
            self.grille.rowconfigure(r, weight=1)
            tk.Label(self.grille, text=nom, font=police, bg="#dfe6f3", width=9
                     ).grid(row=r, column=0, sticky="nsew", padx=1, pady=1)
            for c, d in enumerate(jours, start=1):
                items = [e for e in self.app.seances
                         if e["date"] == d.isoformat() and test(e)]
                texte = "\n\n".join(self._texte(e) for e in items)
                bg = self.COULEURS.get(items[0]["type"], "#ffffff") if items else "#ffffff"
                tk.Label(
                    self.grille, text=texte, bg=bg, justify="left", anchor="nw",
                    wraplength=150, padx=6, pady=6,
                ).grid(row=r, column=c, sticky="nsew", padx=1, pady=1)


class Application:
    def __init__(self, root):
        self.root = root
        root.title(TITRE_CALENDRIER)
        root.geometry("1100x560")
        self.seances = charger()

        # Barre d'outils
        barre = ttk.Frame(root, padding=(8, 8, 8, 4))
        barre.pack(fill="x")
        for texte, cmd in [
            ("➕ Ajouter", self.ajouter), ("✏️ Modifier", self.modifier),
            ("🗑 Supprimer", self.supprimer), ("📥 Importer", self.importer),
        ]:
            ttk.Button(barre, text=texte, command=cmd).pack(side="left", padx=2)
        ttk.Separator(barre, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(barre, text="📅 Export .ics (agenda tél.)", command=self.export_ics).pack(side="left", padx=2)
        ttk.Button(barre, text="📱 Export page HTML", command=self.export_html).pack(side="left", padx=2)
        ttk.Button(barre, text="💾 Export CSV", command=self.export_csv).pack(side="left", padx=2)

        # Onglets : Tableau (grille) + Liste
        self.onglets = ttk.Notebook(root)
        self.onglets.pack(fill="both", expand=True, padx=8, pady=4)
        self.vue = VueTableau(self.onglets, self)
        self.onglets.add(self.vue, text="📊 Tableau")
        cadre = ttk.Frame(self.onglets, padding=(8, 4, 8, 4))
        self.onglets.add(cadre, text="📋 Liste")

        colonnes = ("jour", "horaire", "matiere", "intervenant", "seance", "type")
        self.arbre = ttk.Treeview(cadre, columns=colonnes, show="headings", selectmode="browse")
        for col, txt, larg in [
            ("jour", "Jour", 130), ("horaire", "Horaire", 100), ("matiere", "Matière", 400),
            ("intervenant", "Intervenant", 130), ("seance", "Séance", 60), ("type", "Type", 80),
        ]:
            self.arbre.heading(col, text=txt)
            self.arbre.column(col, width=larg, anchor="w")
        defil = ttk.Scrollbar(cadre, orient="vertical", command=self.arbre.yview)
        self.arbre.configure(yscrollcommand=defil.set)
        self.arbre.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.arbre.tag_configure("auj", background="#cfe3ff")
        self.arbre.tag_configure("ctrl", background="#ffe3c2")
        self.arbre.tag_configure("tpe", background="#d6f5df")
        self.arbre.bind("<Double-1>", lambda _e: self.modifier())
        self.arbre.bind("<Delete>", lambda _e: self.supprimer())

        self.statut = ttk.Label(root, anchor="w", padding=(10, 2))
        self.statut.pack(fill="x")
        self.rafraichir()

    # -- affichage --
    def rafraichir(self):
        self.arbre.delete(*self.arbre.get_children())
        aujourdhui = datetime.now().date()
        for i, e in enumerate(self.seances):
            d = parse_date(e["date"])
            tags = []
            if d == aujourdhui:
                tags.append("auj")
            elif e["type"] == "Contrôle":
                tags.append("ctrl")
            elif e["type"] == "TPE":
                tags.append("tpe")
            self.arbre.insert("", "end", iid=str(i), tags=tags, values=(
                f"{JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')}",
                f"{e['debut']} - {e['fin']}", e["matiere"],
                e["intervenant"], e["seance"], e["type"],
            ))
        self.statut.config(text=f"{len(self.seances)} séance(s) - données enregistrées dans {DATA_FILE.name}")
        self.vue.dessiner()

    def selection(self):
        sel = self.arbre.selection()
        if not sel:
            messagebox.showinfo(
                "Sélection",
                "Allez dans l'onglet « Liste » et sélectionnez d'abord une séance.",
            )
            return None
        return int(sel[0])

    def maj(self):
        self.seances = trier(self.seances)
        sauvegarder(self.seances)
        self.rafraichir()

    # -- actions --
    def ajouter(self):
        res = Dialogue(self.root, "Ajouter une séance").resultat
        if res:
            self.seances.append(res)
            self.maj()

    def modifier(self):
        i = self.selection()
        if i is None:
            return
        res = Dialogue(self.root, "Modifier la séance", self.seances[i]).resultat
        if res:
            self.seances[i] = res
            self.maj()

    def supprimer(self):
        i = self.selection()
        if i is None:
            return
        if messagebox.askyesno("Supprimer", f"Supprimer « {self.seances[i]['matiere']} » ?"):
            del self.seances[i]
            self.maj()

    def importer(self):
        chemin = filedialog.askopenfilename(
            title="Importer un emploi du temps",
            filetypes=[("PDF / CSV / JSON", "*.pdf *.csv *.json"), ("Tous les fichiers", "*.*")],
        )
        if not chemin:
            return
        try:
            if chemin.lower().endswith(".pdf"):
                nouvelles, periode = lire_pdf(chemin)
                self.seances = fusionner(self.seances, nouvelles, periode)
                self.maj()
                d = parse_date(periode[0])
                self.vue.lundi = d - timedelta(days=d.weekday())
                self.vue.dessiner()
                messagebox.showinfo(
                    "Import PDF",
                    f"{len(nouvelles)} séance(s) importée(s) pour la semaine "
                    f"du {periode[0]} au {periode[1]}.",
                )
                return
            nouvelles = lire_fichier(chemin)
        except (ValueError, OSError, KeyError, RuntimeError) as err:
            messagebox.showerror("Import impossible", str(err))
            return
        remplacer = messagebox.askyesnocancel(
            "Import", f"{len(nouvelles)} séance(s) lue(s).\n\n"
            "Oui = remplacer l'emploi du temps actuel\nNon = les ajouter à l'existant"
        )
        if remplacer is None:
            return
        self.seances = nouvelles if remplacer else self.seances + nouvelles
        self.maj()

    def _exporter(self, defaut, types, ecrire, message):
        chemin = filedialog.asksaveasfilename(
            initialfile=defaut, defaultextension=Path(defaut).suffix, filetypes=types
        )
        if not chemin:
            return
        try:
            ecrire(chemin)
        except OSError as err:
            messagebox.showerror("Export impossible", str(err))
            return
        messagebox.showinfo("Export terminé", f"{message}\n\n{chemin}")

    def export_ics(self):
        self._exporter(
            "emploi_du_temps.ics", [("Calendrier", "*.ics")],
            lambda p: Path(p).write_text(vers_ics(self.seances), encoding="utf-8", newline=""),
            "Envoyez ce fichier sur votre téléphone puis ouvrez-le : il s'ajoute à l'agenda.",
        )

    def export_html(self):
        self._exporter(
            "emploi_du_temps.html", [("Page web", "*.html")],
            lambda p: Path(p).write_text(vers_html(self.seances), encoding="utf-8"),
            "Envoyez cette page sur votre téléphone (WhatsApp, mail...) et ouvrez-la.",
        )

    def export_csv(self):
        self._exporter(
            "emploi_du_temps.csv", [("CSV", "*.csv")],
            lambda p: exporter_csv(self.seances, p), "Fichier CSV enregistré.",
        )


def diagnostic_pdf(chemin, brut=False):
    """Mode console : affiche ce que le programme lit dans un PDF."""
    pdfplumber = _ouvrir_pdfplumber()
    with pdfplumber.open(str(chemin)) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            for t, table in enumerate(page.extract_tables(), start=1):
                if brut:
                    print(f"--- page {n}, tableau {t} ---")
                    for ligne in table:
                        print(ligne)
                else:
                    seances, _ = _lire_tableau(table)
                    for e in seances:
                        print(e["date"], e["debut"], e["fin"], e["matiere"],
                              "|", e["intervenant"], "|", e["seance"], "|", e["type"])


def main():
    if len(sys.argv) >= 3 and sys.argv[1] in ("--pdf", "--debug-pdf"):
        try:
            diagnostic_pdf(sys.argv[2], brut=sys.argv[1] == "--debug-pdf")
        except (RuntimeError, OSError) as err:
            raise SystemExit(str(err))
        return
    if tk is None:
        raise SystemExit("Tkinter n'est pas installé sur cette machine.")
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
