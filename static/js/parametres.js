document.addEventListener("DOMContentLoaded", async () => {
    const root = document.querySelector("[data-settings-root]");
    if (!root) return;
    const fieldsRoot = document.getElementById("settings-form");
    const status = document.getElementById("settings-status");
    const primeForm = document.getElementById("settings-prime-form");
    let payrollData = { statuts: [], baremes: [], primes: [], types_contrats: [], modes_calcul: [], types_montant: [] };
    let contractData = { types: [], references_smic: [], baremes_apprentissage: [], modes_paie: [] };
    initTabs(root);
    if (window.location.hash === "#baremes-cee") {
        root.querySelector('[data-tab="paie"]')?.click();
        requestAnimationFrame(() => document.getElementById("baremes-cee")?.scrollIntoView({ block: "center" }));
    }

    function setStatus(message = "", error = false) {
        status.textContent = message;
        status.className = message ? (error ? "error" : "success") : "";
    }

    function afficher(data) {
        Object.entries(data).forEach(([name, value]) => {
            const field = fieldsRoot.querySelector(`[name="${name}"]`);
            if (!field) return;
            if (field.type === "checkbox") field.checked = Boolean(value);
            else field.value = value ?? "";
        });
    }

    function dateAujourdhui() {
        const local = new Date();
        local.setMinutes(local.getMinutes() - local.getTimezoneOffset());
        return local.toISOString().slice(0, 10);
    }

    function renderBaremes() {
        const target = document.getElementById("settings-cee-rates");
        if (!payrollData.statuts.length) {
            target.innerHTML = '<p class="settings-note">Aucun statut animateur configuré dans Gestion.</p>';
            return;
        }
        target.innerHTML = payrollData.statuts.map((statut) => {
            const historique = payrollData.baremes.filter((item) => Number(item.statut_id) === Number(statut.id));
            return `<article class="settings-rate-row" data-rate-status="${Number(statut.id)}">
                <div class="settings-rate-name"><strong>${escapeHtml(statut.nom)}</strong><small>${historique.length ? `${historique[0].montant_journalier} €/jour depuis le ${formatDateFr(historique[0].date_effet)}` : "Aucun taux renseigné"}</small></div>
                <div class="settings-rate-editor"><input data-rate-amount type="number" min="0" step="0.01" placeholder="Taux"><input data-rate-date type="date" value="${dateAujourdhui()}"><button class="btn btn-ghost btn-small" data-rate-save type="button">Ajouter</button></div>
                ${historique.length ? `<details><summary>Historique (${historique.length})</summary><div class="settings-rate-history">${historique.map((item) => `<span>${formatDateFr(item.date_effet)} · <strong>${escapeHtml(item.montant_journalier)} €</strong></span>`).join("")}</div></details>` : ""}
            </article>`;
        }).join("");
        target.querySelectorAll("[data-rate-save]").forEach((button) => button.addEventListener("click", async () => {
            const row = button.closest("[data-rate-status]");
            try {
                await apiFetch(root.dataset.ratesUrl, { method: "POST", body: JSON.stringify({
                    statut_id: Number(row.dataset.rateStatus),
                    montant_journalier: row.querySelector("[data-rate-amount]").value,
                    date_effet: row.querySelector("[data-rate-date]").value,
                }) });
                await chargerPaie();
                setStatus("Barème CEE enregistré.");
            } catch (error) { setStatus(erreurMessage(error, "Enregistrement du barème impossible."), true); }
        }));
    }

    function formatDateFr(value) {
        return new Intl.DateTimeFormat("fr-FR").format(new Date(`${value}T12:00:00`));
    }

    function contractResourceUrl(resource, id = null) {
        return id ? `${root.dataset.contractSettingsUrl}${resource}/${id}/` : root.dataset.contractSettingsUrl;
    }

    function openSettingsForm(form, item = null) {
        form.hidden = false;
        form.reset();
        [...form.elements].forEach((field) => {
            if (!field.name || !item || !(field.name in item)) return;
            if (field.type === "checkbox") field.checked = Boolean(item[field.name]);
            else field.value = item[field.name] ?? "";
        });
        form.querySelector("input:not([type=hidden]), select")?.focus();
    }

    function renderContractSettings() {
        const typesList = root.querySelector("[data-contract-types-list]");
        typesList.innerHTML = contractData.types.map((item) => `<article class="settings-reference-row"><div><strong>${escapeHtml(item.nom)}</strong><small>${escapeHtml(item.mode_remuneration_libelle)} · ${item.actif ? "Actif" : "Inactif"}${item.systeme ? " · système" : ""}</small></div><button class="btn btn-ghost btn-small" data-contract-type-edit="${item.id}" type="button">Modifier</button></article>`).join("") || '<p class="settings-note">Aucun type.</p>';
        typesList.querySelectorAll("[data-contract-type-edit]").forEach((button) => button.addEventListener("click", () => openSettingsForm(root.querySelector("[data-contract-type-form]"), contractData.types.find((item) => Number(item.id) === Number(button.dataset.contractTypeEdit)))));
        const current = contractData.references_smic.find((item) => Number(item.id) === Number(contractData.smic_actuel_id));
        root.querySelector("[data-current-smic]").textContent = current ? `${current.montant_horaire} €/h · applicable depuis le ${formatDateFr(current.date_effet)}` : "Aucune référence enregistrée.";
        const smicList = root.querySelector("[data-smic-list]");
        smicList.innerHTML = contractData.references_smic.map((item) => `<article class="settings-reference-row"><div><strong>${escapeHtml(item.montant_horaire)} €/h</strong><small>${formatDateFr(item.date_effet)}${item.source ? ` · ${escapeHtml(item.source)}` : ""}</small></div><button class="btn btn-ghost btn-small" data-smic-edit="${item.id}" type="button">Modifier</button></article>`).join("") || '<p class="settings-note">Historique vide.</p>';
        smicList.querySelectorAll("[data-smic-edit]").forEach((button) => button.addEventListener("click", () => openSettingsForm(root.querySelector("[data-smic-form]"), contractData.references_smic.find((item) => Number(item.id) === Number(button.dataset.smicEdit)))));
        const ratesList = root.querySelector("[data-apprentice-rates-list]");
        ratesList.innerHTML = contractData.baremes_apprentissage.map((item) => `<article class="settings-reference-row"><div><strong>Année ${item.annee_execution} · ${item.age_minimum}${item.age_maximum === null ? "+" : `–${item.age_maximum}`} ans</strong><small>${escapeHtml(item.pourcentage_smic)} % · depuis le ${formatDateFr(item.date_effet)}${item.actif ? "" : " · inactive"}</small></div><button class="btn btn-ghost btn-small" data-apprentice-rate-edit="${item.id}" type="button">Modifier</button></article>`).join("") || '<p class="settings-note">Aucune grille configurée.</p>';
        ratesList.querySelectorAll("[data-apprentice-rate-edit]").forEach((button) => button.addEventListener("click", () => openSettingsForm(root.querySelector("[data-apprentice-rate-form]"), contractData.baremes_apprentissage.find((item) => Number(item.id) === Number(button.dataset.apprenticeRateEdit)))));
    }

    async function chargerContrats() {
        contractData = await apiFetch(root.dataset.contractSettingsUrl);
        const select = root.querySelector('[data-contract-type-form] [name="mode_remuneration"]');
        select.innerHTML = contractData.modes_paie.map((item) => `<option value="${item.value}">${escapeHtml(item.label)}</option>`).join("");
        root.querySelector("[data-smic-sync]").disabled = !contractData.provider_smic?.disponible;
        renderContractSettings();
    }

    function setupContractForm(selector, resource, fields) {
        const form = root.querySelector(selector);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const id = Number(form.elements.id.value) || null;
            const payload = { ressource: resource };
            fields.forEach((name) => {
                const input = form.elements[name];
                payload[name] = input.type === "checkbox" ? input.checked : (input.value || null);
            });
            try {
                await apiFetch(contractResourceUrl(resource, id), { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
                form.hidden = true;
                await Promise.all([chargerContrats(), chargerPaie()]);
                setStatus("Paramètre de contrat enregistré.");
            } catch (error) { setStatus(erreurMessage(error, "Enregistrement impossible."), true); }
        });
    }

    function primePayload(prime, changes = {}) {
        return {
            nom: prime.nom, description: prime.description, active: prime.active,
            mode_calcul: prime.mode_calcul, type_montant: prime.type_montant,
            montant_fixe: prime.montant_fixe, montant_maximum: prime.montant_maximum,
            contrats_eligibles: prime.contrats_eligibles, tous_statuts: prime.tous_statuts,
            statut_ids: prime.statut_ids, ...changes,
        };
    }

    function montantPrime(prime) {
        const unite = { jour: "/jour", semaine: "/semaine", mois: "/mois", forfait: "" }[prime.mode_calcul] || "";
        return prime.type_montant === "fixe"
            ? `${prime.montant_fixe ?? "Non renseigné"} €${unite}`
            : `Variable · max. ${prime.montant_maximum ?? "non renseigné"} €${unite}`;
    }

    function renderPrimes() {
        const target = document.getElementById("settings-primes-list");
        target.innerHTML = payrollData.primes.length ? payrollData.primes.map((prime) => `
            <article class="settings-prime-row ${prime.active ? "is-active" : ""}">
                <div><strong>${escapeHtml(prime.nom)}</strong><span>${escapeHtml(montantPrime(prime))}</span><small>${escapeHtml(prime.contrats_eligibles_libelles.join(" · ") || "Aucun contrat")}</small></div>
                <span class="settings-prime-state">${prime.active ? "Active" : "Inactive"}</span>
                <div class="settings-prime-actions"><button class="btn btn-ghost btn-small" data-prime-edit="${prime.id}" type="button">Modifier</button><button class="btn btn-ghost btn-small" data-prime-toggle="${prime.id}" type="button">${prime.active ? "Désactiver" : "Activer"}</button><button class="btn-danger btn-small" data-prime-delete="${prime.id}" type="button">Supprimer</button></div>
            </article>`).join("") : '<p class="settings-note">Aucun type de prime.</p>';
        target.querySelectorAll("[data-prime-edit]").forEach((button) => button.addEventListener("click", () => ouvrirPrime(payrollData.primes.find((item) => Number(item.id) === Number(button.dataset.primeEdit)))));
        target.querySelectorAll("[data-prime-toggle]").forEach((button) => button.addEventListener("click", async () => {
            const prime = payrollData.primes.find((item) => Number(item.id) === Number(button.dataset.primeToggle));
            try {
                await apiFetch(`${root.dataset.primesUrl}${prime.id}/`, { method: "PATCH", body: JSON.stringify(primePayload(prime, { active: !prime.active })) });
                await chargerPaie();
                setStatus(prime.active ? "Prime désactivée." : "Prime activée.");
            } catch (error) { setStatus(erreurMessage(error, "Modification impossible."), true); }
        }));
        target.querySelectorAll("[data-prime-delete]").forEach((button) => button.addEventListener("click", async () => {
            const prime = payrollData.primes.find((item) => Number(item.id) === Number(button.dataset.primeDelete));
            if (!confirm(`Supprimer la prime « ${prime.nom} » ?`)) return;
            try {
                await apiFetch(`${root.dataset.primesUrl}${prime.id}/`, { method: "DELETE" });
                await chargerPaie();
                setStatus("Prime supprimée.");
            } catch (error) { setStatus(erreurMessage(error, "Suppression impossible. Désactive la prime si elle est déjà utilisée."), true); }
        }));
    }

    function actualiserChampsPrime() {
        const variable = primeForm.elements.type_montant.value === "variable_plafonne";
        primeForm.querySelector("[data-prime-fixed]").hidden = variable;
        primeForm.querySelector("[data-prime-cap]").hidden = !variable;
        primeForm.querySelector("[data-prime-statuses]").hidden = primeForm.elements.tous_statuts.checked;
    }

    function ouvrirPrime(prime = null) {
        primeForm.hidden = false;
        primeForm.reset();
        primeForm.elements.id.value = prime?.id || "";
        primeForm.elements.nom.value = prime?.nom || "";
        primeForm.elements.description.value = prime?.description || "";
        primeForm.elements.active.checked = Boolean(prime?.active);
        primeForm.elements.mode_calcul.value = prime?.mode_calcul || "jour";
        primeForm.elements.type_montant.value = prime?.type_montant || "fixe";
        primeForm.elements.montant_fixe.value = prime?.montant_fixe || "";
        primeForm.elements.montant_maximum.value = prime?.montant_maximum || "";
        primeForm.elements.tous_statuts.checked = prime ? prime.tous_statuts : true;
        primeForm.querySelectorAll('[name="contrats_eligibles"]').forEach((input) => { input.checked = Boolean(prime?.contrats_eligibles.includes(input.value)); });
        primeForm.querySelectorAll('[name="statut_ids"]').forEach((input) => { input.checked = Boolean(prime?.statut_ids.includes(Number(input.value))); });
        actualiserChampsPrime();
        primeForm.elements.nom.focus();
    }

    function preparerFormulairePrime() {
        primeForm.elements.mode_calcul.innerHTML = payrollData.modes_calcul.map((item) => `<option value="${item.value}">${escapeHtml(item.label)}</option>`).join("");
        primeForm.elements.type_montant.innerHTML = payrollData.types_montant.map((item) => `<option value="${item.value}">${escapeHtml(item.label)}</option>`).join("");
        primeForm.querySelector("[data-prime-contracts]").innerHTML = payrollData.types_contrats.map((item) => `<label><input name="contrats_eligibles" type="checkbox" value="${item.value}"> ${escapeHtml(item.label)}</label>`).join("");
        primeForm.querySelector("[data-prime-statuses]").innerHTML = payrollData.statuts.map((item) => `<label><input name="statut_ids" type="checkbox" value="${item.id}"> ${escapeHtml(item.nom)}</label>`).join("");
    }

    async function chargerPaie() {
        payrollData = await apiFetch(root.dataset.payrollUrl);
        const adaptation = fieldsRoot.querySelector('[name="adapter_taux_cee_changement_statut"]');
        adaptation.checked = payrollData.adapter_taux_cee_changement_statut;
        renderBaremes();
        preparerFormulairePrime();
        renderPrimes();
    }

    async function charger() {
        setStatus("Chargement…");
        try {
            const [settings] = await Promise.all([apiFetch(root.dataset.apiUrl), chargerPaie(), chargerContrats()]);
            afficher(settings);
            setStatus();
        } catch (error) { setStatus(erreurMessage(error, "Chargement impossible."), true); }
    }

    document.getElementById("settings-save").addEventListener("click", async () => {
        const payload = {};
        fieldsRoot.querySelectorAll("[name]").forEach((field) => {
            if (field.closest("#settings-prime-form")) return;
            payload[field.name] = field.type === "checkbox" ? field.checked : field.value;
        });
        setStatus("Enregistrement…");
        try {
            const saved = await apiFetch(root.dataset.apiUrl, { method: "PUT", body: JSON.stringify(payload) });
            afficher(saved);
            await chargerPaie();
            setStatus("Paramètres enregistrés.");
        } catch (error) { setStatus(erreurMessage(error, "Enregistrement impossible."), true); }
    });

    document.getElementById("settings-prime-add").addEventListener("click", () => ouvrirPrime());
    primeForm.elements.type_montant.addEventListener("change", actualiserChampsPrime);
    primeForm.elements.tous_statuts.addEventListener("change", actualiserChampsPrime);
    primeForm.querySelector("[data-prime-cancel]").addEventListener("click", () => { primeForm.hidden = true; });
    primeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const id = Number(primeForm.elements.id.value) || null;
        const variable = primeForm.elements.type_montant.value === "variable_plafonne";
        const payload = {
            nom: primeForm.elements.nom.value.trim(), description: primeForm.elements.description.value.trim(),
            active: primeForm.elements.active.checked, mode_calcul: primeForm.elements.mode_calcul.value,
            type_montant: primeForm.elements.type_montant.value,
            montant_fixe: variable ? null : (primeForm.elements.montant_fixe.value || null),
            montant_maximum: variable ? (primeForm.elements.montant_maximum.value || null) : null,
            contrats_eligibles: [...primeForm.querySelectorAll('[name="contrats_eligibles"]:checked')].map((input) => input.value),
            tous_statuts: primeForm.elements.tous_statuts.checked,
            statut_ids: [...primeForm.querySelectorAll('[name="statut_ids"]:checked')].map((input) => Number(input.value)),
        };
        try {
            await apiFetch(id ? `${root.dataset.primesUrl}${id}/` : root.dataset.primesUrl, { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
            primeForm.hidden = true;
            await chargerPaie();
            setStatus(id ? "Prime modifiée." : "Prime ajoutée.");
        } catch (error) { setStatus(erreurMessage(error, "Enregistrement de la prime impossible."), true); }
    });

    root.querySelector("[data-contract-type-add]").addEventListener("click", () => openSettingsForm(root.querySelector("[data-contract-type-form]")));
    root.querySelector("[data-smic-add]").addEventListener("click", () => openSettingsForm(root.querySelector("[data-smic-form]")));
    root.querySelector("[data-apprentice-rate-add]").addEventListener("click", () => openSettingsForm(root.querySelector("[data-apprentice-rate-form]")));
    root.querySelector("[data-contract-type-cancel]").addEventListener("click", () => { root.querySelector("[data-contract-type-form]").hidden = true; });
    root.querySelector("[data-smic-cancel]").addEventListener("click", () => { root.querySelector("[data-smic-form]").hidden = true; });
    root.querySelector("[data-apprentice-rate-cancel]").addEventListener("click", () => { root.querySelector("[data-apprentice-rate-form]").hidden = true; });
    setupContractForm("[data-contract-type-form]", "type", ["nom", "code", "mode_remuneration", "ordre", "actif", "description"]);
    setupContractForm("[data-smic-form]", "smic", ["date_effet", "montant_horaire", "montant_mensuel_35h", "source", "commentaire"]);
    setupContractForm("[data-apprentice-rate-form]", "apprentissage", ["date_effet", "annee_execution", "age_minimum", "age_maximum", "pourcentage_smic", "actif", "commentaire"]);

    await charger();
});
