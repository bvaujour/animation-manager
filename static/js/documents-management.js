(() => {
function mountDocuments(app) {
    if (!app) return;
    if (app.dataset.documentsMounted) return app.documentsManagement;
    app.dataset.documentsMounted = "1";

    const form = document.getElementById("form-upload");
    const grid = document.getElementById("documents-grid");
    const titleInput = document.getElementById("doc-titre");
    const fileInput = document.getElementById("doc-fichier");
    const errorElement = document.getElementById("doc-error");
    const permanentInput = document.getElementById("doc-permanent");
    const categoryInput = document.getElementById("doc-categorie");
    const importantInput = document.getElementById("doc-important");
    const periodPickerField = document.getElementById("doc-period-picker-field");
    const mainPickerRoot = document.getElementById("doc-semaines-picker");
    const mainPicker = WeekPicker.init(mainPickerRoot);
    let periods = mainPicker?.periods || [];
    let centres = [];
    let activeView = "periode";
    let activeEditor = null;

    const filters = {
        categorie: document.getElementById("documents-filter-categorie"),
        periode: document.getElementById("documents-filter-periode"),
        centre: document.getElementById("documents-filter-centre"),
        publie: document.getElementById("documents-filter-publie"),
    };

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
            <h3 class="document-title" title="${escapeHtml(documentItem.titre)}">${documentItem.important ? "⭐ " : ""}${escapeHtml(documentItem.titre)}</h3>
            <div class="document-card-meta">
                <span class="document-category-label">${escapeHtml(documentItem.categorie_libelle || "Autre")}</span>
                <span class="document-period-badge ${documentItem.permanent ? "permanent" : "dated"}">${escapeHtml(documentItem.permanent ? "Permanent" : (documentItem.libelle_periode || ""))}</span>
                <span class="document-publication-status ${documentItem.publie ? "is-published" : "is-draft"}">${documentItem.publie ? "Publié" : "Non publié"}</span>
            </div>
            <div class="document-actions">
                <a href="${escapeHtml(documentItem.url)}" target="_blank" rel="noopener" class="btn btn-ghost">Ouvrir</a>
                <button class="btn btn-ghost document-edit" type="button">Modifier</button>
                <button class="btn btn-ghost document-archive" type="button">${documentItem.archive ? "Restaurer" : "Archiver"}</button>
                <button class="btn btn-danger document-delete" type="button" aria-label="Supprimer ${escapeHtml(documentItem.titre)}">&times;</button>
            </div>`;

        card.querySelector(".document-edit").addEventListener("click", () => {
            activeEditor?.remove();
            const editor = document.createElement("form");
            editor.className = "document-inline-editor document-editor-form";
            editor.innerHTML = `
                <div class="document-editor-fields">
                    <label class="field document-editor-title"><span>Titre</span><input type="text" name="titre" value="${escapeHtml(documentItem.titre)}" required></label>
                    <label class="field"><span>Type de document</span><select name="type_document"><option value="classique" ${documentItem.type_document === "classique" ? "selected" : ""}>Document classique</option><option value="programme_activites" ${documentItem.type_document === "programme_activites" ? "selected" : ""}>Programme d'activités</option></select></label>
                    <label class="field"><span>Catégorie</span><select name="categorie"><option value="pedagogie_activites" ${documentItem.categorie === "pedagogie_activites" ? "selected" : ""}>Pédagogie & activités</option><option value="organisation_planning" ${documentItem.categorie === "organisation_planning" ? "selected" : ""}>Organisation & planning</option><option value="protocoles_securite" ${documentItem.categorie === "protocoles_securite" ? "selected" : ""}>Protocoles & sécurité</option><option value="administratif" ${documentItem.categorie === "administratif" ? "selected" : ""}>Administratif</option><option value="autre" ${documentItem.categorie === "autre" ? "selected" : ""}>Autre</option></select></label>
                    <div class="document-editor-options">
                        <span class="field-label">Portée</span>
                        <label class="form-check"><input class="form-check-input" type="radio" name="portee" value="permanent" ${documentItem.permanent ? "checked" : ""}><span class="form-check-label">Permanent</span></label>
                        <label class="form-check"><input class="form-check-input" type="radio" name="portee" value="periode" ${documentItem.permanent ? "" : "checked"}><span class="form-check-label">Lié à une période</span></label>
                        <label class="form-check"><input class="form-check-input" type="checkbox" name="publie" ${documentItem.publie ? "checked" : ""}><span class="form-check-label">Publié à l’équipe</span></label>
                        <label class="form-check"><input class="form-check-input" type="checkbox" name="important" ${documentItem.important ? "checked" : ""}><span class="form-check-label">Important</span></label>
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
                </div>
                <p class="form-error"></p>
                <div class="editor-actions">
                    <button class="btn btn-primary" type="submit">Enregistrer</button>
                    <button class="btn btn-ghost editor-cancel" type="button">Annuler</button>
                </div>`;
            const pickerRoot = clonePickerRoot();
            editor.querySelector(".document-inline-picker-slot").replaceWith(pickerRoot);
            card.appendChild(editor);
            activeEditor = editor;
            editor.elements.titre.focus();

            const editorPicker = WeekPicker.init(pickerRoot, {
                periods,
                selectedIds: documentItem.periode_ids || [],
            });
            const isPermanent = () => editor.elements.portee.value === "permanent";
            const editorCentres = initCentreSelector(editor.querySelector(".document-editor-centres"), {
                tousCentres: documentItem.tous_centres,
                centreIds: documentItem.centre_ids,
            });
            const editorPeriods = editor.querySelector(".document-editor-periods");
            const updateEditorMode = () => setPickerVisibility({ permanent: isPermanent(), field: editorPeriods, picker: editorPicker });
            editor.querySelectorAll('[name="portee"]').forEach((input) => input.addEventListener("change", updateEditorMode));
            updateEditorMode();
            editor.querySelector(".editor-cancel").addEventListener("click", () => {
                editor.remove();
                activeEditor = null;
            });
            editor.addEventListener("submit", async (event) => {
                event.preventDefault();
                const ids = selectedIds(editorPicker);
                const inlineError = editor.querySelector(".form-error");
                inlineError.textContent = "";
                if (!isPermanent() && !ids.length) {
                    inlineError.textContent = "Sélectionnez au moins une semaine ou choisissez « Document permanent ».";
                    return;
                }
                if (!editorCentres.tousCentres() && !editorCentres.ids().length) {
                    inlineError.textContent = "Sélectionnez au moins un centre.";
                    return;
                }
                try {
                    await apiFetch(`/api/documents/${documentItem.id}/`, {
                        method: "PATCH",
                        body: JSON.stringify({
                            titre: editor.elements.titre.value.trim(),
                            type_document: editor.elements.type_document.value,
                            categorie: editor.elements.categorie.value,
                            important: editor.elements.important.checked,
                            permanent: isPermanent(),
                            periode_ids: isPermanent() ? [] : ids,
                            publie: editor.elements.publie.checked,
                            tous_centres: editorCentres.tousCentres(),
                            centre_ids: editorCentres.ids(),
                        }),
                    });
                    afficherToast("Document modifié.");
                    activeEditor = null;
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
        card.querySelector(".document-archive").addEventListener("click", async () => {
            try {
                await apiFetch(`/api/documents/${documentItem.id}/`, {
                    method: "PATCH",
                    body: JSON.stringify({ archive: !documentItem.archive }),
                });
                afficherToast(documentItem.archive ? "Document restauré." : "Document archivé.");
                await loadDocuments();
            } catch (error) {
                afficherToast(erreurMessage(error, "Archivage impossible."), true);
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

    function selectedPeriodId() {
        const navigation = WeekPicker.get("gestion-period-nav");
        const selected = periods.find((period) => (
            String(period.debut) <= String(navigation?.activeDate || "")
            && String(navigation?.activeDate || "") <= String(period.fin)
        ));
        return filters.periode?.value || selected?.id || "";
    }

    async function loadDocuments() {
        try {
            const query = new URLSearchParams({ vue: activeView });
            const periodeId = selectedPeriodId();
            if (periodeId) query.set("periode_id", periodeId);
            ["categorie", "centre", "publie"].forEach((name) => {
                if (filters[name]?.value) query.set(`${name}_id`.replace("categorie_id", "categorie").replace("publie_id", "publie"), filters[name].value);
            });
            displayDocuments(await apiFetch(`/api/documents/?${query.toString()}`));
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
            errorElement.textContent = "Choisissez un fichier.";
            return;
        }
        if (!permanentInput.checked && !ids.length) {
            errorElement.textContent = "Sélectionnez au moins une semaine ou choisissez « Document permanent ».";
            return;
        }
        if (!centreSelection.tousCentres() && !centreSelection.ids().length) {
            errorElement.textContent = "Sélectionnez au moins un centre.";
            return;
        }

        const data = new FormData();
        data.append("titre", titleInput.value.trim());
        data.append("fichier", file);
        data.append("type_document", document.getElementById("doc-type-document")?.value || "classique");
        data.append("categorie", categoryInput?.value || "autre");
        data.append("important", importantInput?.checked ? "true" : "false");
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
    async function initCentres({ force = false } = {}) {
        const source = window.GestionData?.["fetch"]
            ? GestionData["fetch"]("centres", "/api/centres/", { force })
            : apiFetch("/api/centres/");
        centres = await source;
        initMainCentres = initCentreSelector(document.getElementById("doc-centres-field"));
    }

    permanentInput?.addEventListener("change", () => setPickerVisibility({ permanent: permanentInput.checked }));
    document.getElementById("doc-type-document")?.addEventListener("change", (event) => {
        if (event.target.value === "programme_activites" && categoryInput?.value === "autre") {
            categoryInput.value = "pedagogie_activites";
        }
    });
    setPickerVisibility({ permanent: permanentInput?.checked });

    mainPickerRoot?.addEventListener("week-picker:ready", (event) => {
        periods = event.detail.periods || [];
        filters.periode.innerHTML = '<option value="">Période sélectionnée</option>' + periods.map((period) => `<option value="${period.id}">${escapeHtml(period.libelle || period.nom)}</option>`).join("");
    });
    if (mainPicker?.ready) periods = mainPicker.periods;
    document.querySelectorAll("[data-documents-view]").forEach((button) => button.addEventListener("click", () => {
        activeView = button.dataset.documentsView;
        document.querySelectorAll("[data-documents-view]").forEach((item) => item.className = "btn btn-ghost");
        button.className = "btn btn-primary";
        loadDocuments();
    }));
    Object.values(filters).forEach((filter) => filter?.addEventListener("change", loadDocuments));
    window.addEventListener("animation-manager:week-change", () => {
        if (!filters.periode?.value) loadDocuments();
    });

    initCentres().then(() => {
        filters.centre.innerHTML = '<option value="">Tous les centres</option>' + centres.map((centre) => `<option value="${centre.id}">${escapeHtml(centre.nom)}</option>`).join("");
        return loadDocuments();
    }).catch((error) => {
        errorElement.textContent = erreurMessage(error, "Impossible de charger les centres.");
    });
    app.documentsManagement = {
        rafraichirCentres: () => initCentres({ force: true }),
    };
    return app.documentsManagement;
}

window.DocumentsManagement = { mount: mountDocuments };
})();
