/* Lecture du PDF d'emploi du temps directement dans le navigateur (pdf.js).
   Même logique que la version Python : en-tête = dates, lignes = Matin / Après-midi. */
(function (root) {
  "use strict";

  const RE_HEURES = /(\d{1,2})\s*[hH:]\s*(\d{2})?\s*(?:-|–|—|à|a)\s*(\d{1,2})\s*[hH:]\s*(\d{2})?/;
  const RE_DATE_TEXTE = /(\d{1,2})\s*[-\/. ]\s*([A-Za-zÀ-ÿ]+)\.?\s*[-\/. ]\s*(\d{2,4})/;
  const RE_DATE_NUM = /(\d{1,2})\s*[\/.-]\s*(\d{1,2})\s*[\/.-]\s*(\d{2,4})/;
  const RE_SEANCE = /^\s*(\d+)\s*\/\s*(\d+)\s*$/;
  const RE_PROF = /^(?:DR|DRA|PR|PROF|MR|MME|MLLE|M)\b\.?\s+\S/i;
  const MOIS = {jan:1, fev:2, mar:3, avr:4, mai:5, aou:8, sep:9, oct:10, nov:11, dec:12};

  const sansAccents = t => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const p2 = n => String(n).padStart(2, "0");

  function numeroMois(t) {
    t = sansAccents(t).toLowerCase().replace(/\./g, "");
    if (t.startsWith("juil")) return 7;
    if (t.startsWith("juin")) return 6;
    return MOIS[t.slice(0, 3)] || null;
  }

  function isoValide(a, m, j) {
    const d = new Date(Date.UTC(a, m - 1, j));
    if (d.getUTCFullYear() !== a || d.getUTCMonth() !== m - 1 || d.getUTCDate() !== j) return null;
    return `${a}-${p2(m)}-${p2(j)}`;
  }

  function dateEntete(s) {
    let m = RE_DATE_TEXTE.exec(s);
    if (m) {
      const mois = numeroMois(m[2]);
      if (mois) {
        let a = +m[3]; if (a < 100) a += 2000;
        const r = isoValide(a, mois, +m[1]);
        if (r) return r;
      }
    }
    m = RE_DATE_NUM.exec(s);
    if (m) {
      let a = +m[3]; if (a < 100) a += 2000;
      return isoValide(a, +m[2], +m[1]);
    }
    return null;
  }

  const heure = (h, m) => `${p2(+h)}:${p2(+(m || 0))}`;
  const minutes = hhmm => { const [h, m] = hhmm.split(":"); return +h * 60 + +m; };

  /* Regroupe des morceaux de texte en lignes (même hauteur), de haut en bas. */
  function lignes(items) {
    const tri = items.slice().sort((a, b) => a.y - b.y || a.x - b.x);
    const res = [];
    let courante = [], yRef = null;
    for (const it of tri) {
      if (yRef === null || Math.abs(it.y - yRef) <= 4) {
        courante.push(it); if (yRef === null) yRef = it.y;
      } else {
        res.push(courante); courante = [it]; yRef = it.y;
      }
    }
    if (courante.length) res.push(courante);
    return res.map(l => l.sort((a, b) => a.x - b.x).map(i => i.str).join(" ").replace(/\s+/g, " ").trim())
              .filter(Boolean);
  }

  function lireCellule(lns, debut, fin) {
    let seance = "";
    for (const l of lns) {
      const m = RE_SEANCE.exec(l);
      if (m) { seance = `${m[1]}/${m[2]}`; break; }
    }
    const propres = lns.filter(l => !RE_SEANCE.test(l));
    let prof = "";
    if (propres.length > 1 && RE_PROF.test(propres[propres.length - 1])) prof = propres.pop();

    let texte = propres.join(" ");
    const mh = RE_HEURES.exec(texte);                  // ex : « 14H à 16H » pour un contrôle
    if (mh) {
      debut = heure(mh[1], mh[2]); fin = heure(mh[3], mh[4]);
      texte = (texte.slice(0, mh.index) + texte.slice(mh.index + mh[0].length)).trim();
    }
    texte = texte.replace(/\s+/g, " ").replace(/\s*:\s*/, " : ").replace(/\s+FIN$/, " (FIN)").trim();
    if (!texte) return null;

    const norm = sansAccents(texte).toLowerCase();
    let type = "Cours";
    if (/^(controle|examen|devoir|partiel)/.test(norm)) type = "Contrôle";
    else if (norm.startsWith("tpe")) type = "TPE";
    else if (norm.startsWith("tp")) type = "TP";

    if (minutes(fin) <= minutes(debut)) return null;
    return {debut, fin, matiere: texte, intervenant: prof, seance, type};
  }

  /* items : [{str, x, y, w}] d'une page (y augmente vers le bas). */
  function lirePage(items) {
    items = items.filter(i => i.str && i.str.trim()).map(i => ({...i, str: i.str.trim()}));

    // 1. en-tête : une date par colonne
    const datesBrutes = items.map(i => ({cx: i.x + i.w / 2, y: i.y, iso: dateEntete(i.str)})).filter(d => d.iso);
    if (datesBrutes.length < 2) return {seances: [], dates: []};
    const headerY = datesBrutes[0].y;
    const cols = datesBrutes.filter(d => Math.abs(d.y - headerY) < 6).sort((a, b) => a.cx - b.cx);
    if (cols.length < 2) return {seances: [], dates: []};
    const bornes = cols.map((c, i) => {
      const gauche = i === 0 ? c.cx - (cols[1].cx - c.cx) / 2 : (cols[i - 1].cx + c.cx) / 2;
      const droite = i === cols.length - 1 ? c.cx + (c.cx - cols[i - 1].cx) / 2 : (c.cx + cols[i + 1].cx) / 2;
      return {gauche, droite, iso: c.iso};
    });
    const xTable = bornes[0].gauche;

    // 2. bas du tableau (NB, signature) et ligne de pause
    const pieds = items.filter(i => /^(NB\b|La Direction)/i.test(i.str) && i.y > headerY).map(i => i.y);
    const basY = pieds.length ? Math.min(...pieds) - 3 : Infinity;
    const pause = items.find(i => /^pause$/i.test(i.str) && i.y > headerY);
    const pauseY = pause ? pause.y : null;

    // 3. plages horaires (colonne de gauche)
    let labels = items
      .filter(i => i.x + i.w / 2 < xTable && i.y > headerY)
      .map(i => ({y: i.y, m: RE_HEURES.exec(i.str)}))
      .filter(l => l.m)
      .map(l => ({y: l.y, debut: heure(l.m[1], l.m[2]), fin: heure(l.m[3], l.m[4])}));
    labels = labels.filter(l => pauseY !== null ? Math.abs(l.y - pauseY) > 8 : minutes(l.fin) - minutes(l.debut) > 60)
                   .sort((a, b) => a.y - b.y);
    if (!labels.length) return {seances: [], dates: cols.map(c => c.iso)};

    const bandes = labels.map((l, i) => {
      let haut = headerY + 4, bas = basY;
      if (i > 0) {
        const prec = labels[i - 1].y;
        haut = (pauseY !== null && pauseY > prec && pauseY < l.y) ? pauseY + 5 : (prec + l.y) / 2;
      }
      if (i < labels.length - 1) {
        const suiv = labels[i + 1].y;
        bas = (pauseY !== null && pauseY > l.y && pauseY < suiv) ? pauseY - 5 : (l.y + suiv) / 2;
      }
      return {haut, bas, debut: l.debut, fin: l.fin};
    });

    // 4. une séance par bande et par jour
    const seances = [];
    for (const b of bandes) {
      for (const c of bornes) {
        const cell = items.filter(i => {
          const cx = i.x + i.w / 2;
          return cx >= c.gauche && cx < c.droite && i.y > b.haut && i.y < b.bas;
        });
        if (!cell.length) continue;
        const s = lireCellule(lignes(cell), b.debut, b.fin);
        if (s) seances.push({date: c.iso, ...s});
      }
    }
    return {seances, dates: cols.map(c => c.iso)};
  }

  /* pages : tableau de tableaux d'items. Retourne {seances, periode:[debut, fin]}. */
  function lirePages(pages) {
    let seances = [], dates = [];
    for (const items of pages) {
      const r = lirePage(items);
      seances = seances.concat(r.seances);
      dates = dates.concat(r.dates);
    }
    if (!seances.length) {
      throw new Error("Aucune séance reconnue dans ce PDF. Est-ce bien l'emploi du temps de l'école (et pas une photo ou un scan) ?");
    }
    dates.sort();
    seances.sort((a, b) => (a.date + a.debut).localeCompare(b.date + b.debut));
    return {seances, periode: [dates[0], dates[dates.length - 1]]};
  }

  /* Navigateur : lit un fichier PDF avec pdf.js (pdfjsLib doit être chargé). */
  async function lireFichier(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    const pdf = await root.pdfjsLib.getDocument({data: buf}).promise;
    const pages = [];
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n);
      const tc = await page.getTextContent();
      pages.push(tc.items.map(it => ({str: it.str, x: it.transform[4], y: -it.transform[5], w: it.width})));
    }
    return lirePages(pages);
  }

  const api = {lirePage, lirePages, lireFichier};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.EDT_PDF = api;
})(typeof window !== "undefined" ? window : globalThis);
