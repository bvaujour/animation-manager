document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("email-form");
    const animateursRoot = document.getElementById("email-animateurs");
    const documentsRoot = document.getElementById("email-documents");
    const statusEl = document.getElementById("email-config-status");
    const errorEl = document.getElementById("email-error");
    const submitButton = document.getElementById("email-submit");
    const selectAllButton = document.getElementById("select-all-animateurs");

    function splitEmails(value) {
        return value
            .split(/[;,\n]+/)
            .map((email) => email.trim())
            .filter(Boolean);
    }

    function renderAnimateurs(animateurs) {
        const avecEmail = animateurs.filter((a) => a.email);
        if (!avecEmail.length) {
            animateursRoot.innerHTML = '<p class="empty-note">Aucun animateur n’a d’adresse e-mail renseignée.</p>';
            selectAllButton.disabled = true;
            return;
        }

        animateursRoot.innerHTML = avecEmail.map((a) => `
            <label class="recipient-chip" style="--anim-color:${escapeHtml(a.couleur || "#1f6f54")}">
                <input type="checkbox" value="${a.id}">
                <span class="recipient-name">${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}</span>
                <span class="recipient-email">${escapeHtml(a.email)}</span>
            </label>
        `).join("");
    }

    function renderDocuments(documents) {
        if (!documents.length) {
            documentsRoot.innerHTML = '<p class="empty-note">Aucun document disponible.</p>';
            return;
        }
        documentsRoot.innerHTML = documents.map((doc) => `
            <label class="attachment-chip">
                <input type="checkbox" value="${doc.id}">
                <span>${escapeHtml(doc.titre)}</span>
            </label>
        `).join("");
    }

    function loadData() {
        return Promise.all([
            apiFetch("/api/emails/status/"),
            apiFetch("/api/animateurs/"),
            apiFetch("/api/documents/"),
        ]).then(([status, animateurs, documents]) => {
            statusEl.textContent = status.configured
                ? `Envoi SMTP actif — expéditeur : ${status.from_email}`
                : "Mode développement : les e-mails seront affichés dans le terminal, pas envoyés réellement.";
            statusEl.classList.toggle("warning", !status.configured);
            renderAnimateurs(animateurs);
            renderDocuments(documents);
        }).catch((err) => {
            errorEl.textContent = erreurMessage(err, "Impossible de charger la page d’envoi.");
        });
    }

    selectAllButton.addEventListener("click", () => {
        const checkboxes = Array.from(animateursRoot.querySelectorAll('input[type="checkbox"]'));
        const tousCoches = checkboxes.length && checkboxes.every((input) => input.checked);
        checkboxes.forEach((input) => { input.checked = !tousCoches; });
        selectAllButton.textContent = tousCoches ? "Tout sélectionner" : "Tout désélectionner";
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        errorEl.textContent = "";
        submitButton.disabled = true;
        submitButton.textContent = "Envoi…";

        const payload = {
            animateur_ids: idsCheckboxesCochees(animateursRoot),
            emails: splitEmails(document.getElementById("email-manual").value),
            sujet: document.getElementById("email-subject").value.trim(),
            message: document.getElementById("email-body").value.trim(),
            document_ids: idsCheckboxesCochees(documentsRoot),
        };

        apiFetch("/api/emails/send/", {
            method: "POST",
            body: JSON.stringify(payload),
        }).then((data) => {
            afficherToast(data.message || "E-mail envoyé.");
            form.reset();
            selectAllButton.textContent = "Tout sélectionner";
        }).catch((err) => {
            errorEl.textContent = erreurMessage(err, "L’envoi a échoué.");
        }).finally(() => {
            submitButton.disabled = false;
            submitButton.textContent = "Envoyer";
        });
    });

    loadData();
});
