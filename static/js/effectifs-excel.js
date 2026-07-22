(() => {
    "use strict";

    const boutonOuvrir = document.getElementById("btn-effectifs-excel");
    const modal = document.getElementById("modal-effectifs-excel");
    if (!boutonOuvrir || !modal) return;

    const etapes = {
        home: document.getElementById("effectifs-excel-home"),
        mapping: document.getElementById("effectifs-excel-mapping"),
        preview: document.getElementById("effectifs-excel-preview-step"),
    };
    const sousTitre = document.getElementById("effectifs-excel-subtitle");
    const inputDebut = document.getElementById("effectifs-excel-debut");
    const inputFin = document.getElementById("effectifs-excel-fin");
    const centresRoot = document.getElementById("effectifs-excel-centres");
    const boutonTousLieux = document.getElementById("effectifs-excel-tous-lieux");
    const boutonDownload = document.getElementById("effectifs-excel-download");
    const inputFichier = document.getElementById("effectifs-excel-file");
    const nomFichier = document.getElementById("effectifs-excel-file-name");
    const boutonAnalyse = document.getElementById("effectifs-excel-analyse");
    const feuillesRoot = document.getElementById("effectifs-excel-sheets");
    const selectProfil = document.getElementById("effectifs-excel-profile");
    const boutonSupprimerProfil = document.getElementById("effectifs-excel-delete-profile");
    const inputNomProfil = document.getElementById("effectifs-excel-profile-name");
    const boutonSauverProfil = document.getElementById("effectifs-excel-save-profile");
    const boutonPreview = document.getElementById("effectifs-excel-preview");
    const boutonRetourPreview = document.getElementById("effectifs-excel-preview-back");
    const previewSummary = document.getElementById("effectifs-excel-preview-summary");
    const errorsRoot = document.getElementById("effectifs-excel-errors");
    const previewRows = document.getElementById("effectifs-excel-preview-rows");
    const selectAll = document.getElementById("effectifs-excel-select-all");
    const boutonConfirm = document.getElementById("effectifs-excel-confirm");

    let centres = [];
    let groupes = [];
    let profils = [];
    let fichierCourant = null;
    let analyseCourante = null;
    let configurationCourante = null;
    let previewCourante = null;

    function normaliser(value) {
        return String(value ?? "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, " ")
            .trim();
    }

    function option(value, label, selected = false) {
        return `<option value="${escapeHtml(value)}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
    }

    function optionsColonnes(feuille, selected = "", avecVide = true) {
        return `${avecVide ? option("", "Choisir une colonne", !selected) : ""}${(feuille.columns || [])
            .map((colonne) => option(colonne.letter, `${colonne.letter} — ${colonne.label}`, colonne.letter === selected))
            .join("")}`;
    }

    function optionsCentres(selected = "") {
        return `${option("", "Choisir un lieu", !selected)}${centres
            .map((centre) => option(String(centre.id), `${centre.nom} (${centre.code})`, String(centre.id) === String(selected)))
            .join("")}`;
    }

    function optionsGroupes(selected = "", avecIgnorer = true) {
        return `${avecIgnorer ? option("", "Ignorer", !selected) : option("", "Choisir un groupe", !selected)}${groupes
            .map((groupe) => option(String(groupe.id), groupe.nom, String(groupe.id) === String(selected)))
            .join("")}`;
    }

    function groupeSuggere(value) {
        const cle = normaliser(value);
        let trouve = groupes.find((groupe) => normaliser(groupe.nom) === cle);
        if (trouve) return trouve.id;
        if (/mater|3 5|3 6/.test(cle)) {
            trouve = groupes.find((groupe) => /mater|3 5|3 6/.test(normaliser(groupe.nom)));
        } else if (/element|6 10|6 11/.test(cle)) {
            trouve = groupes.find((groupe) => /element|6 10|6 11/.test(normaliser(groupe.nom)));
        }
        return trouve?.id || "";
    }

    function centreSuggere(value) {
        const cle = normaliser(value);
        return centres.find((centre) => normaliser(centre.nom) === cle || normaliser(centre.code) === cle)?.id || "";
    }

    function colonneSuggeree(feuille, motifs) {
        const trouve = (feuille.columns || []).find((colonne) => motifs.some((motif) => motif.test(normaliser(colonne.label))));
        return trouve?.letter || "";
    }

    function configurationDefautFeuille(feuille) {
        const dateColumn = colonneSuggeree(feuille, [/^date$/, /journee/, /date /]);
        const centreColumn = colonneSuggeree(feuille, [/lieu/, /centre/, /site/]);
        const groupColumn = colonneSuggeree(feuille, [/^groupe$/, /tranche/, /categorie/]);
        const effectifColumn = colonneSuggeree(feuille, [/effectif/, /^nombre$/, /nb enfant/, /enfants/]);
        const fixedCentre = centreSuggere(feuille.name);
        const layout = groupColumn && effectifColumn ? "long" : "wide";
        const groupColumns = {};
        if (layout === "wide") {
            (feuille.columns || []).forEach((colonne) => {
                if ([dateColumn, centreColumn].includes(colonne.letter)) return;
                const groupeId = groupeSuggere(colonne.label);
                if (groupeId) groupColumns[colonne.letter] = groupeId;
            });
        }
        return {
            name: feuille.name,
            enabled: Boolean(feuille.header_row),
            header_row: feuille.header_row || 1,
            date_column: dateColumn,
            centre: fixedCentre
                ? { mode: "fixed", centre_id: fixedCentre }
                : (centreColumn ? { mode: "column", column: centreColumn, values: {} } : { mode: "fixed", centre_id: "" }),
            layout,
            group_columns: groupColumns,
            group: { column: groupColumn, values: {} },
            effectif_column: effectifColumn,
        };
    }

    function configFeuilleCourante(nom) {
        return configurationCourante?.sheets?.find((item) => item.name === nom) || null;
    }

    function valeurMapHTML(feuille, colonne, mappings, type) {
        if (!colonne) return "";
        const values = feuille.values?.[colonne] || [];
        if (!values.length) return '<p class="empty-note">Aucune valeur détectée dans cette colonne.</p>';
        const centreMap = type === "centre";
        return values.map((value) => {
            const cle = String(value);
            const valeur = mappings?.[cle] ?? (centreMap ? centreSuggere(value) : groupeSuggere(value));
            return `<label class="effectifs-excel-map-row">
                <span title="${escapeHtml(cle)}">${escapeHtml(cle)}</span>
                <select data-excel-${centreMap ? "centre" : "group"}-value="${escapeHtml(cle)}">
                    ${centreMap ? optionsCentres(valeur) : optionsGroupes(valeur, false)}
                </select>
            </label>`;
        }).join("");
    }

    function renderFeuille(feuille, cfg) {
        const centre = cfg.centre || { mode: "fixed", centre_id: "" };
        const layout = cfg.layout || "wide";
        const centreValues = centre.mode === "column"
            ? valeurMapHTML(feuille, centre.column, centre.values || {}, "centre")
            : "";
        const colonnesGroupes = (feuille.columns || [])
            .filter((colonne) => colonne.letter !== cfg.date_column && colonne.letter !== centre.column)
            .map((colonne) => `<label class="effectifs-excel-map-row">
                <span>${escapeHtml(`${colonne.letter} — ${colonne.label}`)}</span>
                <select data-excel-group-column="${colonne.letter}">${optionsGroupes(cfg.group_columns?.[colonne.letter] || "")}</select>
            </label>`).join("");
        const groupValues = layout === "long"
            ? valeurMapHTML(feuille, cfg.group?.column, cfg.group?.values || {}, "group")
            : "";
        return `<article class="effectifs-excel-sheet" data-sheet-name="${escapeHtml(feuille.name)}">
            <div class="effectifs-excel-sheet-head">
                <input type="checkbox" data-excel-sheet-enabled${cfg.enabled ? " checked" : ""}>
                <strong>${escapeHtml(feuille.name)}</strong>
                <small>Ligne d’en-tête détectée : ${escapeHtml(cfg.header_row)}</small>
            </div>
            <div class="effectifs-excel-sheet-body"${cfg.enabled ? "" : " hidden"}>
                <label class="field"><span>Colonne date</span><select data-excel-date-column>${optionsColonnes(feuille, cfg.date_column)}</select></label>
                <label class="field"><span>Gestion du lieu</span><select data-excel-centre-mode>
                    ${option("fixed", "Un lieu fixe pour cette feuille", centre.mode === "fixed")}
                    ${option("column", "Une colonne contient le lieu", centre.mode === "column")}
                </select></label>
                <label class="field" data-excel-fixed-centre${centre.mode === "fixed" ? "" : " hidden"}><span>Lieu</span><select data-excel-centre-id>${optionsCentres(centre.centre_id || "")}</select></label>
                <label class="field" data-excel-centre-column${centre.mode === "column" ? "" : " hidden"}><span>Colonne lieu</span><select data-excel-centre-column-select>${optionsColonnes(feuille, centre.column || "")}</select></label>
                <label class="field"><span>Organisation des groupes</span><select data-excel-layout>
                    ${option("wide", "Une colonne par groupe", layout === "wide")}
                    ${option("long", "Une ligne par groupe", layout === "long")}
                </select></label>
                <div class="effectifs-excel-value-map" data-excel-centre-values${centre.mode === "column" ? "" : " hidden"}>
                    <strong>Correspondance des lieux</strong>${centreValues}
                </div>
                <div class="effectifs-excel-columns-map" data-excel-wide${layout === "wide" ? "" : " hidden"}>
                    <strong>Correspondance des colonnes de groupes</strong>${colonnesGroupes || '<p class="empty-note">Aucune colonne disponible.</p>'}
                </div>
                <div class="effectifs-excel-span-all" data-excel-long${layout === "long" ? "" : " hidden"}>
                    <div class="effectifs-excel-date-grid">
                        <label class="field"><span>Colonne groupe</span><select data-excel-group-column-long>${optionsColonnes(feuille, cfg.group?.column || "")}</select></label>
                        <label class="field"><span>Colonne effectif</span><select data-excel-effectif-column>${optionsColonnes(feuille, cfg.effectif_column || "")}</select></label>
                    </div>
                    <div class="effectifs-excel-value-map" data-excel-group-values>
                        <strong>Correspondance des groupes</strong>${groupValues}
                    </div>
                </div>
            </div>
        </article>`;
    }

    function afficherEtape(nom) {
        Object.entries(etapes).forEach(([cle, element]) => { element.hidden = cle !== nom; });
        if (nom === "home") sousTitre.textContent = "Téléchargez un gabarit ou importez un classeur existant.";
        if (nom === "mapping") sousTitre.textContent = "Indiquez à quoi correspondent les colonnes de chaque feuille.";
        if (nom === "preview") sousTitre.textContent = "Vérifiez les valeurs avant de modifier les effectifs.";
    }

    function rendreProfils() {
        const valeur = selectProfil.value;
        selectProfil.innerHTML = `${option("", "Aucun profil", !valeur)}${profils.map((profil) => option(String(profil.id), profil.nom, String(profil.id) === valeur)).join("")}`;
        boutonSupprimerProfil.hidden = !selectProfil.value;
    }

    function rendreMapping() {
        if (!analyseCourante) return;
        configurationCourante ||= { sheets: analyseCourante.sheets.map(configurationDefautFeuille) };
        feuillesRoot.innerHTML = analyseCourante.sheets
            .map((feuille) => renderFeuille(feuille, configFeuilleCourante(feuille.name) || configurationDefautFeuille(feuille)))
            .join("") || '<p class="effectifs-excel-empty">Aucune feuille exploitable n’a été trouvée.</p>';
        rendreProfils();
        brancherCartesMapping();
    }

    function lireConfiguration() {
        const sheets = Array.from(feuillesRoot.querySelectorAll("[data-sheet-name]")).map((carte) => {
            const name = carte.dataset.sheetName;
            const feuille = analyseCourante.sheets.find((item) => item.name === name);
            const enabled = carte.querySelector("[data-excel-sheet-enabled]").checked;
            const centreMode = carte.querySelector("[data-excel-centre-mode]").value;
            const centre = centreMode === "fixed"
                ? { mode: "fixed", centre_id: carte.querySelector("[data-excel-centre-id]").value }
                : {
                    mode: "column",
                    column: carte.querySelector("[data-excel-centre-column-select]").value,
                    values: Object.fromEntries(Array.from(carte.querySelectorAll("[data-excel-centre-value]")).map((select) => [select.dataset.excelCentreValue, select.value]).filter(([, value]) => value)),
                };
            const layout = carte.querySelector("[data-excel-layout]").value;
            return {
                name,
                enabled,
                header_row: feuille.header_row || 1,
                date_column: carte.querySelector("[data-excel-date-column]").value,
                centre,
                layout,
                group_columns: Object.fromEntries(Array.from(carte.querySelectorAll("[data-excel-group-column]")).map((select) => [select.dataset.excelGroupColumn, select.value]).filter(([, value]) => value)),
                group: {
                    column: carte.querySelector("[data-excel-group-column-long]")?.value || "",
                    values: Object.fromEntries(Array.from(carte.querySelectorAll("[data-excel-group-value]")).map((select) => [select.dataset.excelGroupValue, select.value]).filter(([, value]) => value)),
                },
                effectif_column: carte.querySelector("[data-excel-effectif-column]")?.value || "",
            };
        });
        configurationCourante = { sheets };
        return configurationCourante;
    }

    function actualiserCarte(carte) {
        const nom = carte.dataset.sheetName;
        lireConfiguration();
        const feuille = analyseCourante.sheets.find((item) => item.name === nom);
        const nouvelle = document.createElement("div");
        nouvelle.innerHTML = renderFeuille(feuille, configFeuilleCourante(nom));
        carte.replaceWith(nouvelle.firstElementChild);
        brancherCartesMapping();
    }

    function brancherCartesMapping() {
        feuillesRoot.querySelectorAll("[data-sheet-name]").forEach((carte) => {
            if (carte.dataset.excelBound === "1") return;
            carte.dataset.excelBound = "1";
            const enabled = carte.querySelector("[data-excel-sheet-enabled]");
            enabled.addEventListener("change", () => {
                carte.querySelector(".effectifs-excel-sheet-body").hidden = !enabled.checked;
            });
            ["[data-excel-centre-mode]", "[data-excel-centre-column-select]", "[data-excel-layout]", "[data-excel-group-column-long]", "[data-excel-date-column]"]
                .forEach((selecteur) => carte.querySelector(selecteur)?.addEventListener("change", () => actualiserCarte(carte)));
        });
    }

    function verifierConfiguration(config) {
        const actives = config.sheets.filter((item) => item.enabled);
        if (!actives.length) throw new Error("Sélectionnez au moins une feuille à importer.");
        actives.forEach((item) => {
            if (!item.date_column) throw new Error(`Choisissez la colonne date de la feuille « ${item.name} ».`);
            if (item.centre.mode === "fixed" && !item.centre.centre_id) throw new Error(`Choisissez le lieu de la feuille « ${item.name} ».`);
            if (item.centre.mode === "column" && !item.centre.column) throw new Error(`Choisissez la colonne lieu de la feuille « ${item.name} ».`);
            if (item.layout === "wide" && !Object.keys(item.group_columns).length) throw new Error(`Associez au moins une colonne à un groupe dans « ${item.name} ».`);
            if (item.layout === "long" && (!item.group.column || !item.effectif_column)) throw new Error(`Choisissez les colonnes groupe et effectif dans « ${item.name} ».`);
        });
    }

    function formDataFichier(configuration = null) {
        const form = new FormData();
        form.append("fichier", fichierCourant);
        if (configuration) form.append("configuration", JSON.stringify(configuration));
        return form;
    }

    async function chargerCentres() {
        if (centres.length) return;
        centres = await apiFetch("/api/centres/");
        centresRoot.innerHTML = centres.map((centre) => `<label class="effectifs-excel-check"><input type="checkbox" value="${centre.id}" checked><span>${escapeHtml(centre.nom)}</span></label>`).join("");
    }

    function datesParDefaut() {
        const reference = WeekPicker.getPersistedDate?.() || formatDateLocal(new Date());
        const date = parseLocalDate(reference);
        const debut = new Date(date.getFullYear(), date.getMonth(), 1);
        const fin = new Date(date.getFullYear(), date.getMonth() + 1, 0);
        inputDebut.value = formatDateLocal(debut);
        inputFin.value = formatDateLocal(fin);
    }

    async function telechargerGabarit() {
        const ids = idsCheckboxesCochees(centresRoot);
        if (!inputDebut.value || !inputFin.value || !ids.length) {
            afficherToast("Choisissez la période et au moins un lieu.", true);
            return;
        }
        const query = new URLSearchParams({ debut: inputDebut.value, fin: inputFin.value });
        ids.forEach((id) => query.append("centre", id));
        boutonDownload.disabled = true;
        try {
            const response = await fetch(`/api/effectifs-enfants/excel/gabarit/?${query.toString()}`, { cache: "no-store" });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || "Impossible de générer le gabarit.");
            }
            const blob = await response.blob();
            const disposition = response.headers.get("Content-Disposition") || "";
            const nom = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "effectifs.xlsx";
            const url = URL.createObjectURL(blob);
            const lien = document.createElement("a");
            lien.href = url;
            lien.download = nom;
            document.body.appendChild(lien);
            lien.click();
            lien.remove();
            URL.revokeObjectURL(url);
            afficherToast("Le gabarit Excel a été généré.");
        } catch (error) {
            afficherToast(error.message || "Impossible de générer le gabarit.", true);
        } finally {
            boutonDownload.disabled = false;
        }
    }

    async function analyserFichier() {
        if (!fichierCourant) return;
        boutonAnalyse.disabled = true;
        boutonAnalyse.textContent = "Analyse…";
        try {
            analyseCourante = await apiFetch("/api/effectifs-enfants/excel/analyser/", { method: "POST", body: formDataFichier() });
            centres = analyseCourante.centres || [];
            groupes = analyseCourante.groupes || [];
            profils = analyseCourante.profiles || [];
            configurationCourante = null;
            if (analyseCourante.official) {
                await previsualiser(null);
            } else {
                configurationCourante = { sheets: analyseCourante.sheets.map(configurationDefautFeuille) };
                rendreMapping();
                afficherEtape("mapping");
            }
        } catch (error) {
            afficherToast(erreurMessage(error, "Impossible d’analyser le fichier Excel."), true);
        } finally {
            boutonAnalyse.textContent = "Analyser le fichier";
            boutonAnalyse.disabled = !fichierCourant;
        }
    }

    async function previsualiser(configuration) {
        boutonPreview.disabled = true;
        try {
            previewCourante = await apiFetch("/api/effectifs-enfants/excel/previsualiser/", {
                method: "POST",
                body: formDataFichier(configuration),
            });
            rendrePreview();
            afficherEtape("preview");
        } catch (error) {
            afficherToast(erreurMessage(error, "Impossible de préparer l’aperçu."), true);
        } finally {
            boutonPreview.disabled = false;
        }
    }

    function dateFr(dateStr) {
        return parseLocalDate(dateStr).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
    }

    function rendrePreview() {
        const rows = previewCourante?.rows || [];
        const changes = rows.filter((row) => row.change).length;
        previewSummary.textContent = `${rows.length} ligne${rows.length > 1 ? "s" : ""} reconnue${rows.length > 1 ? "s" : ""}, ${changes} modification${changes > 1 ? "s" : ""}`;
        previewRows.innerHTML = rows.map((row, index) => `<tr class="${row.change ? "" : "is-unchanged"}">
            <td><input type="checkbox" data-preview-row="${index}"${row.change ? " checked" : ""}></td>
            <td>${escapeHtml(dateFr(row.date))}</td>
            <td>${escapeHtml(row.centre_nom)}</td>
            <td>${escapeHtml(row.groupe_nom)}</td>
            <td class="number">${row.actuel}</td>
            <td class="number ${row.change ? "is-change" : ""}">${row.importe}</td>
        </tr>`).join("") || '<tr><td colspan="6" class="effectifs-excel-empty">Aucun effectif exploitable n’a été trouvé.</td></tr>';
        const errors = previewCourante?.errors || [];
        errorsRoot.hidden = !errors.length;
        errorsRoot.innerHTML = errors.length
            ? `<strong>${errors.length} ligne${errors.length > 1 ? "s" : ""} ignorée${errors.length > 1 ? "s" : ""}</strong><ul>${errors.slice(0, 30).map((item) => `<li>${escapeHtml(item.sheet || "Feuille")}${item.row ? `, ligne ${item.row}` : ""} : ${escapeHtml(item.message)}</li>`).join("")}</ul>${errors.length > 30 ? `<p>… et ${errors.length - 30} autre(s).</p>` : ""}`
            : "";
        selectAll.checked = changes > 0 && changes === rows.length;
        selectAll.indeterminate = changes > 0 && changes < rows.length;
        actualiserBoutonImport();
    }

    function lignesSelectionnees() {
        return Array.from(previewRows.querySelectorAll("[data-preview-row]:checked"))
            .map((input) => previewCourante.rows[Number(input.dataset.previewRow)])
            .filter(Boolean);
    }

    function actualiserBoutonImport() {
        const count = lignesSelectionnees().length;
        boutonConfirm.disabled = count === 0;
        boutonConfirm.textContent = count ? `Importer ${count} ligne${count > 1 ? "s" : ""}` : "Importer les lignes sélectionnées";
    }

    async function importerSelection() {
        const rows = lignesSelectionnees();
        if (!rows.length) return;
        boutonConfirm.disabled = true;
        try {
            const resultat = await apiFetch("/api/effectifs-enfants/excel/importer/", {
                method: "POST",
                body: JSON.stringify({ rows }),
            });
            fermerModal(modal);
            afficherToast(`${resultat.count} effectif${resultat.count > 1 ? "s" : ""} traité${resultat.count > 1 ? "s" : ""}.`);
            document.dispatchEvent(new CustomEvent("effectifs-enfants-importes", { detail: resultat }));
        } catch (error) {
            afficherToast(erreurMessage(error, "Impossible d’importer les effectifs."), true);
            actualiserBoutonImport();
        }
    }

    async function sauverProfil() {
        const nom = inputNomProfil.value.trim();
        if (!nom) {
            afficherToast("Donnez un nom à ce profil.", true);
            inputNomProfil.focus();
            return;
        }
        try {
            const configuration = lireConfiguration();
            verifierConfiguration(configuration);
            const profilId = Number(selectProfil.value) || null;
            const profil = await apiFetch("/api/effectifs-enfants/excel/profils/", {
                method: "POST",
                body: JSON.stringify({ id: profilId, nom, configuration }),
            });
            profils = profils.filter((item) => item.id !== profil.id);
            profils.push(profil);
            profils.sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
            selectProfil.value = String(profil.id);
            rendreProfils();
            afficherToast("La correspondance a été enregistrée.");
        } catch (error) {
            afficherToast(erreurMessage(error, error.message || "Impossible d’enregistrer le profil."), true);
        }
    }

    async function supprimerProfil() {
        const id = Number(selectProfil.value);
        if (!id) return;
        try {
            await apiFetch(`/api/effectifs-enfants/excel/profils/${id}/`, { method: "DELETE" });
            profils = profils.filter((profil) => profil.id !== id);
            selectProfil.value = "";
            rendreProfils();
            afficherToast("Le profil a été supprimé.");
        } catch (error) {
            afficherToast(erreurMessage(error, "Impossible de supprimer le profil."), true);
        }
    }

    boutonOuvrir.addEventListener("click", async () => {
        await chargerCentres().catch((error) => afficherToast(erreurMessage(error, "Impossible de charger les lieux."), true));
        if (!inputDebut.value) datesParDefaut();
        afficherEtape("home");
        ouvrirModal(modal);
    });
    boutonTousLieux.addEventListener("click", () => {
        const cases = Array.from(centresRoot.querySelectorAll("input[type=checkbox]"));
        const toutCoche = cases.every((input) => input.checked);
        cases.forEach((input) => { input.checked = !toutCoche; });
        boutonTousLieux.textContent = toutCoche ? "Tout sélectionner" : "Tout désélectionner";
    });
    boutonDownload.addEventListener("click", telechargerGabarit);
    inputFichier.addEventListener("change", () => {
        fichierCourant = inputFichier.files?.[0] || null;
        nomFichier.textContent = fichierCourant?.name || "Aucun fichier sélectionné";
        boutonAnalyse.disabled = !fichierCourant;
    });
    boutonAnalyse.addEventListener("click", analyserFichier);
    document.querySelectorAll("[data-excel-back=home]").forEach((button) => button.addEventListener("click", () => afficherEtape("home")));
    boutonPreview.addEventListener("click", async () => {
        try {
            const configuration = lireConfiguration();
            verifierConfiguration(configuration);
            await previsualiser(configuration);
        } catch (error) {
            afficherToast(error.message || "La correspondance est incomplète.", true);
        }
    });
    boutonRetourPreview.addEventListener("click", () => {
        if (analyseCourante?.official) afficherEtape("home");
        else afficherEtape("mapping");
    });
    boutonSauverProfil.addEventListener("click", sauverProfil);
    boutonSupprimerProfil.addEventListener("click", supprimerProfil);
    selectProfil.addEventListener("change", () => {
        const profil = profils.find((item) => String(item.id) === selectProfil.value);
        boutonSupprimerProfil.hidden = !profil;
        if (!profil) return;
        configurationCourante = JSON.parse(JSON.stringify(profil.configuration));
        inputNomProfil.value = profil.nom;
        rendreMapping();
        selectProfil.value = String(profil.id);
        boutonSupprimerProfil.hidden = false;
    });
    previewRows.addEventListener("change", actualiserBoutonImport);
    selectAll.addEventListener("change", () => {
        previewRows.querySelectorAll("[data-preview-row]").forEach((input) => { input.checked = selectAll.checked; });
        selectAll.indeterminate = false;
        actualiserBoutonImport();
    });
    boutonConfirm.addEventListener("click", importerSelection);

    initFermetureModal(modal);
})();
