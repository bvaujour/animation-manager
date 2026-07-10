// Page /documents/ : ajout, classement par période et suppression.
document.addEventListener("DOMContentLoaded", () =>
{
    const grid = document.getElementById("documents-grid");
    const form = document.getElementById("form-upload");
    const titreInput = document.getElementById("doc-titre");
    const fichierInput = document.getElementById("doc-fichier");
    const permanentInput = document.getElementById("doc-permanent");
    const periodFields = document.getElementById("doc-period-fields");
    const debutInput = document.getElementById("doc-periode-debut");
    const finInput = document.getElementById("doc-periode-fin");
    const errorEl = document.getElementById("doc-error");

    const EXTENSIONS_IMAGE = ["jpg", "jpeg", "png", "gif", "webp"];

    function extensionDe(url)
    {
        return url.split("?")[0].split(".").pop().toLowerCase();
    }

    function afficherChampsPeriode()
    {
        const permanent = permanentInput.checked;
        periodFields.hidden = permanent;
        debutInput.required = !permanent;
        finInput.required = !permanent;

        if (permanent)
        {
            debutInput.value = "";
            finInput.value = "";
        }
    }

    function carteDocument(doc)
    {
        const extension = extensionDe(doc.url);
        const div = document.createElement("article");
        div.classList.add("document-card");

        const typeLabel = extension ? extension.toUpperCase() : "FIC";

        div.innerHTML = `
            <div class="document-file-type" aria-hidden="true">${typeLabel}</div>
            <h3 class="document-title truncate" title="${doc.titre}">${doc.titre}</h3>
            <div class="document-actions">
                <a href="${doc.url}" target="_blank" rel="noopener" class="btn btn-ghost">Ouvrir</a>
                <button class="btn btn-ghost document-edit" type="button">Modifier</button>
                <button class="btn btn-danger" type="button" aria-label="Supprimer ${doc.titre}">&times;</button>
            </div>
        `;

        const editButton = div.querySelector(".document-edit");

        editButton.addEventListener("click", () =>
        {
            if (div.querySelector(".document-inline-editor")) return;

            const editor = document.createElement("form");
            editor.className = "document-inline-editor";
            editor.innerHTML = `
                <label>Titre<input type="text" name="titre" value="${doc.titre}" required></label>
                <label class="editor-permanent"><input type="checkbox" name="permanent" ${doc.permanent ? "checked" : ""}> Permanent</label>
                <div class="editor-dates" ${doc.permanent ? "hidden" : ""}>
                    <label>Début<input type="date" name="periode_debut" value="${doc.periode_debut || ""}"></label>
                    <label>Fin<input type="date" name="periode_fin" value="${doc.periode_fin || ""}"></label>
                </div>
                <p class="form-error"></p>
                <div class="editor-actions">
                    <button class="btn btn-primary" type="submit">Enregistrer</button>
                    <button class="btn btn-ghost editor-cancel" type="button">Annuler</button>
                </div>
            `;
            div.appendChild(editor);

            const perm = editor.elements.permanent;
            const dates = editor.querySelector(".editor-dates");
            const toggleDates = () => { dates.hidden = perm.checked; };
            perm.addEventListener("change", toggleDates);
            editor.querySelector(".editor-cancel").addEventListener("click", () => editor.remove());

            editor.addEventListener("submit", (event) =>
            {
                event.preventDefault();
                const payload = {
                    titre: editor.elements.titre.value.trim(),
                    permanent: perm.checked,
                    periode_debut: editor.elements.periode_debut.value || null,
                    periode_fin: editor.elements.periode_fin.value || null,
                };

                apiFetch(`/api/documents/${doc.id}/`, {
                    method: "PATCH",
                    body: JSON.stringify(payload),
                }).then(() =>
                {
                    afficherToast("Document modifié.");
                    charger();
                }).catch((err) =>
                {
                    editor.querySelector(".form-error").textContent = erreurMessage(err, "Modification impossible.");
                });
            });
        });

        div.querySelector(".btn-danger").addEventListener("click", () =>
        {
            if (!confirm(`Supprimer le document "${doc.titre}" ?`)) return;

            apiFetch(`/api/documents/${doc.id}/`, { method: "DELETE" })
                .then(() =>
                {
                    afficherToast("Document supprimé.");
                    charger();
                })
                .catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
        });

        return div;
    }

    function cleGroupe(doc)
    {
        if (doc.permanent) return "permanent";
        return `${doc.periode_debut || ""}|${doc.periode_fin || ""}`;
    }

    function titreGroupe(doc)
    {
        return doc.permanent ? "Documents permanents" : doc.libelle_periode;
    }

    function afficherDocumentsGroupes(documents)
    {
        grid.innerHTML = "";

        if (documents.length === 0)
        {
            grid.innerHTML = '<p class="empty-note">Aucun document pour l\'instant.</p>';
            return;
        }

        const groupes = new Map();
        documents.forEach((doc) =>
        {
            const cle = cleGroupe(doc);
            if (!groupes.has(cle)) groupes.set(cle, { titre: titreGroupe(doc), documents: [] });
            groupes.get(cle).documents.push(doc);
        });

        groupes.forEach((groupe) =>
        {
            const section = document.createElement("section");
            section.classList.add("document-group");
            section.innerHTML = `<h2>${groupe.titre}</h2><div class="document-group-grid"></div>`;
            const groupGrid = section.querySelector(".document-group-grid");
            groupe.documents.forEach((doc) => groupGrid.appendChild(carteDocument(doc)));
            grid.appendChild(section);
        });
    }

    function charger()
    {
        apiFetch("/api/documents/")
            .then(afficherDocumentsGroupes)
            .catch((err) =>
            {
                grid.innerHTML = `<p class="form-error">${erreurMessage(err, "Impossible de charger les documents.")}</p>`;
            });
    }

    form.addEventListener("submit", (event) =>
    {
        event.preventDefault();
        errorEl.textContent = "";

        const fichier = fichierInput.files[0];
        if (!fichier)
        {
            errorEl.textContent = "Choisis un fichier.";
            return;
        }

        if (!permanentInput.checked && (!debutInput.value || !finInput.value))
        {
            errorEl.textContent = "Renseigne une date de début et une date de fin.";
            return;
        }

        const donnees = new FormData();
        donnees.append("titre", titreInput.value.trim());
        donnees.append("fichier", fichier);
        donnees.append("permanent", permanentInput.checked ? "true" : "false");
        donnees.append("periode_debut", debutInput.value);
        donnees.append("periode_fin", finInput.value);

        fetch("/api/documents/",
        {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken() },
            body: donnees,
        }).then((response) =>
        {
            if (!response.ok) return response.json().then((err) => { throw err; });
            return response.json();
        }).then(() =>
        {
            form.reset();
            permanentInput.checked = true;
            afficherChampsPeriode();
            afficherToast("Document ajouté.");
            charger();
        }).catch((err) =>
        {
            errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce document.");
        });
    });

    permanentInput.addEventListener("change", afficherChampsPeriode);
    afficherChampsPeriode();
    charger();
});
