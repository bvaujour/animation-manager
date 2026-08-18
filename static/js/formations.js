(function () {
    "use strict";

    const listRoot = document.getElementById("formations-list");
    const dialog = document.getElementById("formation-dialog");
    const form = document.getElementById("formation-form");
    const errorRoot = document.getElementById("formation-form-error");
    const participantRoot = document.getElementById("formation-participants-list");
    const documentRoot = document.getElementById("formation-documents-list");
    const animatorFilter = document.getElementById("formation-animateur-filter");
    const closeDialog = document.getElementById("formation-close-dialog");
    const closeForm = document.getElementById("formation-close-form");
    const closeSummary = document.getElementById("formation-close-summary");
    const presenceRoot = document.getElementById("formation-presences-list");
    const closeError = document.getElementById("formation-close-error");
    let data = {formations: [], animateurs: [], qualifications: [], documents: [], statuts: []};
    let activeStatus = new URLSearchParams(window.location.search).get("statut") || "";
    let editingId = null;
    let closingId = null;

    function formatDate(value) {
        return new Intl.DateTimeFormat("fr-FR", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"}).format(new Date(`${value}T00:00:00Z`));
    }

    function datesLabel(item) {
        if (item.date_debut === item.date_fin) return formatDate(item.date_debut);
        return `${formatDate(item.date_debut)} au ${formatDate(item.date_fin)}`;
    }

    function render() {
        if (!data.formations.length) {
            listRoot.innerHTML = '<div class="ui-card empty-note">Aucune formation ne correspond à ces filtres.</div>';
            return;
        }
        listRoot.innerHTML = data.formations.map((item) => {
            const participants = item.statut === "terminee"
                ? item.animateurs.map((person) => `<span class="formation-presence formation-presence--${person.presence}">${person.presence === "present" ? "✓" : person.presence === "absent" ? "✕" : "?"} ${escapeHtml(person.prenom)} ${escapeHtml(person.nom)} — ${escapeHtml(person.presence_libelle)}</span>`).join("")
                : item.animateurs.map((person) => `${escapeHtml(person.prenom)} ${escapeHtml(person.nom)}`).join(" · ");
            const organisation = [item.organisme, item.lieu].filter(Boolean).map(escapeHtml).join(" · ");
            const contacts = [
                item.email_contact ? `<a href="mailto:${escapeHtml(item.email_contact)}">${escapeHtml(item.email_contact)}</a>` : "",
                item.telephone_contact ? `<a href="tel:${escapeHtml(item.telephone_contact)}">${escapeHtml(item.telephone_contact)}</a>` : "",
            ].filter(Boolean).join(" · ");
            const qualifications = [item.qualification?.nom, item.qualification_libre]
                .filter(Boolean)
                .filter((value, index, values) => values.findIndex((other) => other.toLocaleLowerCase() === value.toLocaleLowerCase()) === index);
            const documents = item.documents.length
                ? `<div class="formation-card-documents"><strong>Documents</strong>${item.documents.map((document) => `<a href="${escapeHtml(document.url)}" target="_blank" rel="noopener">${escapeHtml(document.titre)} <small>${document.publie ? "Publié" : "Non publié"}</small></a>`).join("")}</div>`
                : "";
            const conflits = item.conflits.length
                ? `<div class="formation-card-conflicts"><strong>⚠ ${item.conflits.length} conflit${item.conflits.length > 1 ? "s" : ""} de planning</strong><span class="formation-conflict-links">${item.conflits.map((conflict) => `<a href="${escapeHtml(conflict.planning_url)}">${escapeHtml(conflict.animateur)} · ${formatDate(conflict.date)}</a>`).join("")}</span></div>`
                : "";
            return `<article class="formation-card" data-formation-id="${item.id}">
                <div class="formation-card-main"><h2>${escapeHtml(item.intitule)}</h2><p>${datesLabel(item)}</p><span class="formation-status formation-status--${item.statut}">${escapeHtml(item.statut_libelle)}</span><p class="formation-card-participants${item.statut === "terminee" ? " formation-participants-history" : ""}">${participants}</p>${conflits}</div>
                <div class="formation-card-details">${organisation ? `<p>${organisation}</p>` : ""}${contacts ? `<p class="formation-card-contacts">${contacts}</p>` : ""}${item.hebergement_libelle ? `<p>${escapeHtml(item.hebergement_libelle)}</p>` : ""}${qualifications.length ? `<p>Qualification${qualifications.length > 1 ? "s" : ""} : <strong>${qualifications.map(escapeHtml).join(" · ")}</strong></p>` : ""}${documents}${item.commentaire ? `<small>${escapeHtml(item.commentaire)}</small>` : ""}</div>
                <div class="formation-card-actions">${item.statut === "a_cloturer" ? '<button class="btn btn-primary btn-small" type="button" data-close-formation>Clôturer la formation</button>' : ""}<button class="btn btn-secondary btn-small" type="button" data-edit>Modifier</button><button class="btn btn-danger-ghost btn-small" type="button" data-delete>Supprimer</button></div>
            </article>`;
        }).join("");
    }

    function populateCatalogues() {
        const selectedAnimator = animatorFilter.value;
        animatorFilter.innerHTML = '<option value="">Tous les animateurs</option>' + data.animateurs.map((item) => `<option value="${item.id}">${escapeHtml(item.prenom)} ${escapeHtml(item.nom)}</option>`).join("");
        animatorFilter.value = selectedAnimator;
        form.elements.statut.innerHTML = data.statuts.map((item) => `<option value="${item.value}">${escapeHtml(item.label)}</option>`).join("");
        form.elements.qualification_id.innerHTML = '<option value="">Aucune</option>' + data.qualifications.map((item) => `<option value="${item.id}">${escapeHtml(item.nom)}</option>`).join("");
        participantRoot.innerHTML = data.animateurs.map((item) => `<label class="formation-participant-choice"><input type="checkbox" name="animateurs" value="${item.id}"><span>${escapeHtml(item.prenom)} ${escapeHtml(item.nom)}</span></label>`).join("");
        documentRoot.innerHTML = data.documents.length
            ? data.documents.map((item) => `<label class="formation-document-choice"><input type="checkbox" name="documents" value="${item.id}"><span>${escapeHtml(item.titre)} <small>${item.publie ? "Publié" : "Non publié"}</small></span></label>`).join("")
            : '<p class="empty-note">Aucun document dans la bibliothèque.</p>';
    }

    async function load({refreshCatalogues = false} = {}) {
        const params = new URLSearchParams();
        if (activeStatus) params.set("statut", activeStatus);
        if (animatorFilter.value) params.set("animateur_id", animatorFilter.value);
        listRoot.innerHTML = '<p class="empty-note">Chargement des formations…</p>';
        try {
            const result = await apiFetch(`/api/formations/${params.size ? `?${params}` : ""}`);
            data = result;
            if (refreshCatalogues) populateCatalogues();
            render();
        } catch (error) {
            listRoot.innerHTML = `<p class="empty-note">${escapeHtml(erreurMessage(error, "Les formations n’ont pas pu être chargées."))}</p>`;
        }
    }

    function openForm(item = null) {
        editingId = item?.id || null;
        form.reset();
        form.elements.statut.querySelector('[value="terminee"]')?.remove();
        errorRoot.hidden = true;
        document.getElementById("formation-dialog-title").textContent = item ? "Modifier la formation" : "Ajouter une formation";
        if (item) {
            ["intitule", "date_debut", "date_fin", "organisme", "email_contact", "telephone_contact", "lieu", "hebergement", "qualification_libre", "commentaire"].forEach((field) => { form.elements[field].value = item[field] || ""; });
            if (item.statut_stocke === "terminee" && !form.elements.statut.querySelector('[value="terminee"]')) {
                form.elements.statut.add(new Option("Terminée (clôturée)", "terminee"));
            }
            form.elements.statut.value = item.statut_stocke;
            form.elements.qualification_id.value = item.qualification?.id || "";
            const selected = new Set(item.animateurs.map((person) => Number(person.id)));
            form.querySelectorAll('[name="animateurs"]').forEach((input) => { input.checked = selected.has(Number(input.value)); });
            const selectedDocuments = new Set(item.documents.map((document) => Number(document.id)));
            form.querySelectorAll('[name="documents"]').forEach((input) => { input.checked = selectedDocuments.has(Number(input.value)); });
        }
        dialog.showModal();
        form.elements.intitule.focus();
    }

    document.getElementById("formation-add").addEventListener("click", () => openForm());
    dialog.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    closeDialog.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog.close()));
    document.getElementById("formation-all-present").addEventListener("click", () => {
        presenceRoot.querySelectorAll("select").forEach((select) => { select.value = "present"; });
    });
    document.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", () => {
        activeStatus = button.dataset.status;
        document.querySelectorAll("[data-status]").forEach((item) => item.classList.toggle("active", item === button));
        load();
    }));
    animatorFilter.addEventListener("change", () => load());

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        payload.animateur_ids = [...form.querySelectorAll('[name="animateurs"]:checked')].map((input) => Number(input.value));
        payload.document_ids = [...form.querySelectorAll('[name="documents"]:checked')].map((input) => Number(input.value));
        errorRoot.hidden = true;
        try {
            await apiFetch(editingId ? `/api/formations/${editingId}/` : "/api/formations/", {method: editingId ? "PATCH" : "POST", body: JSON.stringify(payload)});
            dialog.close();
            await load({refreshCatalogues: true});
            afficherToast(editingId ? "Formation modifiée." : "Formation ajoutée.");
        } catch (error) {
            errorRoot.textContent = erreurMessage(error, "La formation n’a pas pu être enregistrée.");
            errorRoot.hidden = false;
        }
    });

    listRoot.addEventListener("click", async (event) => {
        const card = event.target.closest("[data-formation-id]");
        if (!card) return;
        const item = data.formations.find((formation) => formation.id === Number(card.dataset.formationId));
        if (event.target.closest("[data-close-formation]")) {
            closingId = item.id;
            closeError.hidden = true;
            closeSummary.textContent = `${item.intitule} · ${datesLabel(item)}`;
            presenceRoot.innerHTML = item.animateurs.map((person) => `<label class="formation-presence-row"><strong>${escapeHtml(person.prenom)} ${escapeHtml(person.nom)}</strong><select data-animateur-id="${person.id}" required><option value="">À confirmer</option><option value="present">Présent</option><option value="absent">Absent</option></select></label>`).join("");
            closeDialog.showModal();
            return;
        }
        if (event.target.closest("[data-edit]")) openForm(item);
        if (event.target.closest("[data-delete]")) {
            if (!confirm(`Supprimer la formation « ${item.intitule} » ?`)) return;
            try {
                await apiFetch(`/api/formations/${item.id}/`, {method: "DELETE"});
                await load({refreshCatalogues: true});
                afficherToast("Formation supprimée.");
            } catch (error) {
                afficherToast(erreurMessage(error, "La formation n’a pas pu être supprimée."), true);
            }
        }
    });

    closeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const presences = [...presenceRoot.querySelectorAll("select")].map((select) => ({
            animateur_id: Number(select.dataset.animateurId),
            presence: select.value,
        }));
        closeError.hidden = true;
        try {
            await apiFetch(`/api/formations/${closingId}/cloture/`, {method: "POST", body: JSON.stringify({presences})});
            closeDialog.close();
            await load({refreshCatalogues: true});
            afficherToast("Formation clôturée et présences enregistrées.");
        } catch (error) {
            closeError.textContent = erreurMessage(error, "La formation n’a pas pu être clôturée.");
            closeError.hidden = false;
        }
    });

    const initialStatusButton = document.querySelector(`[data-status="${CSS.escape(activeStatus)}"]`);
    if (initialStatusButton) {
        document.querySelectorAll("[data-status]").forEach((item) => item.classList.toggle("active", item === initialStatusButton));
    } else {
        activeStatus = "";
    }
    load({refreshCatalogues: true});
})();
