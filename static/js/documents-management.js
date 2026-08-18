document.addEventListener("DOMContentLoaded", () => {
    const app = document.getElementById("documents-management-app");
    if (!app) return;

    const form = document.getElementById("form-upload");
    const grid = document.getElementById("documents-grid");
    const titleInput = document.getElementById("doc-titre");
    const fileInput = document.getElementById("doc-fichier");
    const errorElement = document.getElementById("doc-error");
    const permanentInput = document.getElementById("doc-permanent");
    const periodPickerField = document.getElementById("doc-period-picker-field");
    const mainPickerRoot = document.getElementById("doc-semaines-picker");
    const mainPicker = WeekPicker.get(mainPickerRoot);
    let periods = mainPicker?.periods || [];
    let centres = [];

    function initCentreSelector(root, { tousCentres = true, centreIds = [] } = {}) {
        const selected = new Set((centreIds || []).map(Number));
        const list = root.querySelector(".document-centres-list");
        list.innerHTML = centres.map((centre) => `
            <label class="form-check"><input class="form-check-input" type="checkbox" value="${centre.id}" ${selected.has(Number(centre.id)) ? "checked" : ""}><span class="form-check-label">${escapeHtml(centre.nom)}</span></label>
        `).join("");
        const initialMode = tousCentres ? "tous" : (selected.size === 1 ? "un" : "plusieurs");
        const initialRadio = root.querySelector(`[name="centres_mode"][value="${initialMode}"]`);
        if (initialRadio) initialRadio.checked = true;

        const update = () => {
            const mode = root.querySelector('[name="centres_mode"]:checked')?.value || "tous";
            list.hidden = mode === "tous";
            if (mode === "un") {
                const checked = [...list.querySelectorAll('input:checked')];
                checked.slice(1).forEach((input) => { input.checked = false; });
            }
        };
        root.querySelectorAll('[name="centres_mode"]').forEach((radio) => radio.addEventListener("change", update));
        list.addEventListener("change", (event) => {
            if (root.querySelector('[name="centres_mode"]:checked')?.value === "un" && event.target.checked) {
                list.querySelectorAll("input").forEach((input) => { if (input !== event.target) input.checked = false; });
            }
        });
        update();
        return {
            tousCentres: () => root.querySelector('[name="centres_mode"]:checked')?.value === "tous",
            ids: () => [...list.querySelectorAll('input:checked')].map((input) => Number(input.value)),
            refresh: update,
        };
    }

    function selectedIds(picker = mainPicker) {
        return picker?.getSelectedIds() || [];
    }

    function clonePickerRoot() {
        const clone = mainPickerRoot.cloneNode(true);
        clone.removeAttribute("id");
        clone.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
        const toggle = clone.querySelector(".week-picker__toggle");
        toggle?.removeAttribute("aria-labelledby");
        toggle?.setAttribute("aria-label", "Choisir les semaines concernées");
        toggle?.setAttribute("aria-expanded", "false");
        const menu = clone.querySelector(".week-picker__menu");
        if (menu) menu.hidden = true;
        return clone;
    }

    function setPickerVisibility({ permanent, field = periodPickerField, picker = mainPicker } = {}) {
        if (field) field.hidden = Boolean(permanent);
        if (permanent) picker?.clear();
    }

    function documentCard(documentItem) {
        const extension = DocumentUtils.extension(documentItem.url);
        const card = document.createElement("article");
        card.className = "document-card";
        card.innerHTML = `
            <div class="document-file-type" aria-hidden="true">${escapeHtml(extension ? extension.toUpperCase() : "FIC")}</div>
            <div class="document-card-main">
                <h3 class="document-title" title="${escapeHtml(documentItem.titre)}">${escapeHtml(documentItem.titre)}</h3>
                <div class="document-card-meta">
                    <span class="document-period-badge ${documentItem.permanent ? "permanent" : "dated"}">${escapeHtml(documentItem.permanent ? "Permanent" : (documentItem.libelle_periode || ""))}</span>
                    <span class="document-publication-status ${documentItem.publie ? "is-published" : "is-draft"}">${documentItem.publie ? "Publié" : "Non publié"}</span>
                </div>
            </div>
            <div class="document-actions">
                <a href="${escapeHtml(documentItem.url)}" target="_blank" rel="noopener" class="btn btn-ghost">Ouvrir</a>
                <button class="btn btn-ghost document-edit" type="button">Modifier</button>
                <button class="btn btn-danger document-delete" type="button" aria-label="Supprimer ${escapeHtml(documentItem.titre)}">&times;</button>
            </div>`;

        card.querySelector(".document-edit").addEventListener("click", () => {
            if (card.querySelector(".document-inline-editor")) return;
            const editor = document.createElement("form");
            editor.className = "document-inline-editor";
            editor.innerHTML = `
                <label>Titre<input type="text" name="titre" value="${escapeHtml(documentItem.titre)}" required></label>
                <div class="document-editor-options">
                    <label class="form-check"><input class="form-check-input" type="checkbox" name="permanent" ${documentItem.permanent ? "checked" : ""}><span class="form-check-label">Document permanent</span></label>
                    <label class="form-check"><input class="form-check-input" type="checkbox" name="publie" ${documentItem.publie ? "checked" : ""}><span class="form-check-label">Visible par les animateurs</span></label>
                </div>
                <div class="document-editor-periods">
                    <span class="field-label">Semaines concernées</span>
                    <div class="document-inline-picker-slot"></div>
                </div>
                <div class="field document-editor-centres">
                    <span class="field-label">Centres concernés</span>
                    <label class="form-check"><input class="form-check-input" type="radio" name="centres_mode" value="tous"><span class="form-check-label">Tous les centres</span></label>
                    <label class="form-check"><input class="form-check-input" type="radio" name="centres_mode" value="un"><span class="form-check-label">Un seul centre</span></label>
                    <label class="form-check"><input class="form-check-input" type="radio" name="centres_mode" value="plusieurs"><span class="form-check-label">Plusieurs centres sélectionnés</span></label>
                    <div class="document-centres-list"></div>
                </div>
                <p class="form-error"></p>
                <div class="editor-actions">
                    <button class="btn btn-primary" type="submit">Enregistrer</button>
                    <button class="btn btn-ghost editor-cancel" type="button">Annuler</button>
                </div>`;
            const pickerRoot = clonePickerRoot();
            editor.querySelector(".document-inline-picker-slot").replaceWith(pickerRoot);
            card.appendChild(editor);

            const editorPicker = WeekPicker.init(pickerRoot, {
                periods,
                selectedIds: documentItem.periode_ids || [],
            });
            const editorPermanent = editor.elements.permanent;
            const editorCentres = initCentreSelector(editor.querySelector(".document-editor-centres"), {
                tousCentres: documentItem.tous_centres,
                centreIds: documentItem.centre_ids,
            });
            const editorPeriods = editor.querySelector(".document-editor-periods");
            const updateEditorMode = () => setPickerVisibility({ permanent: editorPermanent.checked, field: editorPeriods, picker: editorPicker });
            editorPermanent.addEventListener("change", updateEditorMode);
            updateEditorMode();
            editor.querySelector(".editor-cancel").addEventListener("click", () => editor.remove());
            editor.addEventListener("submit", async (event) => {
                event.preventDefault();
                const ids = selectedIds(editorPicker);
                const inlineError = editor.querySelector(".form-error");
                inlineError.textContent = "";
                if (!editorPermanent.checked && !ids.length) {
                    inlineError.textContent = "Sélectionne au moins une semaine ou choisis Document permanent.";
                    return;
                }
                if (!editorCentres.tousCentres() && !editorCentres.ids().length) {
                    inlineError.textContent = "Sélectionne au moins un centre.";
                    return;
                }
                try {
                    await apiFetch(`/api/documents/${documentItem.id}/`, {
                        method: "PATCH",
                        body: JSON.stringify({
                            titre: editor.elements.titre.value.trim(),
                            permanent: editorPermanent.checked,
                            periode_ids: editorPermanent.checked ? [] : ids,
                            publie: editor.elements.publie.checked,
                            tous_centres: editorCentres.tousCentres(),
                            centre_ids: editorCentres.ids(),
                        }),
                    });
                    afficherToast("Document modifié.");
                    await loadDocuments();
                } catch (error) {
                    inlineError.textContent = erreurMessage(error, "Modification impossible.");
                }
            });
        });

        card.querySelector(".document-delete").addEventListener("click", async () => {
            if (!confirm(`Supprimer « ${documentItem.titre} » ?`)) return;
            try {
                await apiFetch(`/api/documents/${documentItem.id}/`, { method: "DELETE" });
                afficherToast("Document supprimé.");
                await loadDocuments();
            } catch (error) {
                afficherToast(erreurMessage(error, "Suppression impossible."), true);
            }
        });
        return card;
    }

    function displayDocuments(documents) {
        grid.innerHTML = "";
        if (!documents.length) {
            grid.innerHTML = '<p class="empty-note">Aucun document pour l’instant.</p>';
            return;
        }
        const groups = new Map();
        documents.forEach((documentItem) => {
            const key = documentItem.permanent ? "permanent" : ((documentItem.periode_ids || []).join(",") || "sans-periode");
            if (!groups.has(key)) groups.set(key, { title: documentItem.permanent ? "Documents permanents" : (documentItem.libelle_periode || "Sans période"), documents: [] });
            groups.get(key).documents.push(documentItem);
        });
        groups.forEach((group) => {
            const section = document.createElement("section");
            section.className = "document-group";
            section.innerHTML = `<h2>${escapeHtml(group.title)}</h2><div class="document-group-grid"></div>`;
            const groupGrid = section.querySelector(".document-group-grid");
            group.documents.forEach((documentItem) => groupGrid.appendChild(documentCard(documentItem)));
            grid.appendChild(section);
        });
    }

    async function loadDocuments() {
        try {
            displayDocuments(await apiFetch("/api/documents/"));
        } catch (error) {
            grid.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(error, "Impossible de charger les documents."))}</p>`;
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorElement.textContent = "";
        const file = fileInput.files[0];
        const ids = selectedIds();
        const centreSelection = initMainCentres;
        if (!file) {
            errorElement.textContent = "Choisis un fichier.";
            return;
        }
        if (!permanentInput.checked && !ids.length) {
            errorElement.textContent = "Sélectionne au moins une semaine ou choisis Document permanent.";
            return;
        }
        if (!centreSelection.tousCentres() && !centreSelection.ids().length) {
            errorElement.textContent = "Sélectionne au moins un centre.";
            return;
        }

        const data = new FormData();
        data.append("titre", titleInput.value.trim());
        data.append("fichier", file);
        data.append("permanent", permanentInput.checked ? "true" : "false");
        data.append("publie", document.getElementById("doc-publie")?.checked ? "true" : "false");
        data.append("tous_centres", centreSelection.tousCentres() ? "true" : "false");
        centreSelection.ids().forEach((id) => data.append("centre_ids", String(id)));
        if (!permanentInput.checked) ids.forEach((id) => data.append("periode_ids", String(id)));
        try {
            await apiFetch("/api/documents/", { method: "POST", body: data });
            form.reset();
            centreSelection.refresh();
            mainPicker?.clear();
            setPickerVisibility({ permanent: false });
            afficherToast("Document ajouté.");
            await loadDocuments();
        } catch (error) {
            errorElement.textContent = erreurMessage(error, "Impossible d’ajouter ce document.");
        }
    });

    let initMainCentres;
    async function initCentres() {
        centres = await apiFetch("/api/centres/");
        initMainCentres = initCentreSelector(document.getElementById("doc-centres-field"));
    }

    permanentInput?.addEventListener("change", () => setPickerVisibility({ permanent: permanentInput.checked }));
    setPickerVisibility({ permanent: permanentInput?.checked });

    mainPickerRoot?.addEventListener("week-picker:ready", (event) => {
        periods = event.detail.periods || [];
    });
    if (mainPicker?.ready) periods = mainPicker.periods;
    initCentres().then(loadDocuments).catch((error) => {
        errorElement.textContent = erreurMessage(error, "Impossible de charger les centres.");
    });
});
