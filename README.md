# Emploi du temps L2 B IT (version mobile)

- `index.html` : la page (affiche `emploi_du_temps.json`, bouton « Importer mon EDT » pour lire un PDF dans le navigateur)
- `edt-pdf.js` : lecteur de PDF du navigateur
- Mise à jour pour tout le monde : déposer le PDF de l'école dans ce dépôt (GitHub Actions le lit et met à jour `emploi_du_temps.json`)
- La page passe automatiquement à la semaine suivante après la dernière séance (vendredi 17h au plus tôt)
