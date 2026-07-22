document.addEventListener("DOMContentLoaded", () => {
    const app = document.getElementById("documents-management-app");
    if (!app) return;

    const form = document.getElementById("form-upload");
    const grid = document.getElementById("documents-grid");
    const titleInput = document.getElementById("doc-titre");
    const fileInput = document.getElementById("doc-fichier");
    const errorElement = document.getElementById("doc-error");
    const mainPickerRoot = document.getElementById("doc-semaines-picker");
    const mainPicker = WeekPicker.get(mainPickerRoot);
    let periods = mainPicker?.periods || [];

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

    function documentCard(documentItem) {
        const extension = DocumentUtils.extension(documentItem.url);
        const card = document.createElement("article");
        card.className = "document-card";
        card.innerHTML = `
            <div class="document-file-type" aria-hidden="true">${escapeHtml(extension ? extension.toUpperCase() : "FIC")}</div>
            <h3 class="document-title truncate" title="${escapeHtml(documentItem.titre)}">${escapeHtml(documentItem.titre)}</h3>
            <p class="document-period-label">${escapeHtml(documentItem.libelle_periode || "")}</p>
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
                <span class="field-label">Semaines concernées</span>
                <div class="document-inline-picker-slot"></div>
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
            editor.querySelector(".editor-cancel").addEventListener("click", () => editor.remove());
            editor.addEventListener("submit", async (event) => {
                event.preventDefault();
                const ids = selectedIds(editorPicker);
                const inlineError = editor.querySelector(".form-error");
                inlineError.textContent = "";
                if (!ids.length) {
                    inlineError.textContent = "Sélectionne au moins une semaine.";
                    return;
                }
                try {
                    await apiFetch(`/api/documents/${documentItem.id}/`, {
                        method: "PATCH",
                        body: JSON.stringify({ titre: editor.elements.titre.value.trim(), periode_ids: ids }),
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
            const key = (documentItem.periode_ids || []).join(",") || "sans-periode";
            if (!groups.has(key)) groups.set(key, { title: documentItem.libelle_periode || "Sans période", documents: [] });
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
        if (!file) {
            errorElement.textContent = "Choisis un fichier.";
            return;
        }
        if (!ids.length) {
            errorElement.textContent = "Sélectionne au moins une semaine.";
            return;
        }

        const data = new FormData();
        data.append("titre", titleInput.value.trim());
        data.append("fichier", file);
        ids.forEach((id) => data.append("periode_ids", String(id)));
        try {
            await apiFetch("/api/documents/", { method: "POST", body: data });
            form.reset();
            mainPicker?.clear();
            afficherToast("Document ajouté.");
            await loadDocuments();
        } catch (error) {
            errorElement.textContent = erreurMessage(error, "Impossible d’ajouter ce document.");
        }
    });

    mainPickerRoot?.addEventListener("week-picker:ready", (event) => {
        periods = event.detail.periods || [];
    });
    if (mainPicker?.ready) periods = mainPicker.periods;
    loadDocuments();
});
