(function () {
    "use strict";

    const root = document.getElementById("sorties-content");
    const pickerRoot = document.getElementById("sorties-periods");
    const dialog = document.getElementById("sortie-create");
    const form = document.getElementById("sortie-create-form");
    const groupsRoot = document.getElementById("sortie-create-groups");
    const previewRoot = document.getElementById("sortie-create-preview");
    const previewLoading = document.getElementById("sortie-preview-loading");
    const groupsCount = document.getElementById("sortie-groups-count");
    const submitButton = document.getElementById("sortie-create-submit");
    const dateInput = form.elements.date;
    let selectedPeriods = [];
    let previewTimer = null;
    let previewController = null;

    function formatDate(date, options) {
        return parseLocalDate(date).toLocaleDateString("fr-FR", options);
    }

    async function load() {
        if (!selectedPeriods.length) {
            root.innerHTML = '<p class="empty-note">Choisissez une ou plusieurs semaines.</p>';
            return;
        }
        const data = await apiFetch(`/api/sorties/?periode_ids=${selectedPeriods.join(",")}`);
        root.innerHTML = data.semaines.map((week) => {
            const content = week.sorties.length
                ? `<div class="sorties-cards sorties-week-cards">
                            ${week.sorties.map((sortie) => `
                                <a class="sortie-card" href="/sorties/${sortie.id}/">
                                    <header>
                                        <strong>${escapeHtml(sortie.nom)}</strong>
                                        <span class="sortie-status sortie-status--${sortie.statut}">
                                            ${sortie.statut === "prete" ? "Prête" : "À compléter"}
                                        </span>
                                    </header>
                                    <small class="sortie-card-date">${formatDate(sortie.date, { weekday: "long", day: "numeric", month: "long" })}</small>
                                    <p>${escapeHtml(sortie.destination)}</p>
                                    <small>${sortie.groupes.length
                                        ? sortie.groupes.map((group) => `${escapeHtml(group.centre)} — ${escapeHtml(group.groupe)}`).join(" · ")
                                        : "Aucun groupe"}</small>
                                    <small>${sortie.totaux.enfants} enfants · ${sortie.totaux.animateurs} animateurs</small>
                                </a>
                            `).join("")}
                        </div>`
                : '<p class="empty-note">Aucune sortie cette semaine.</p>';
            return `
                <section class="sorties-week">
                    <h2>${escapeHtml(week.nom)} — du ${formatDate(week.debut, { day: "numeric", month: "long" })} au ${formatDate(week.fin, { day: "numeric", month: "long" })}</h2>
                    ${content}
                </section>
            `;
        }).join("");
    }

    function showLoadError(error) {
        root.innerHTML = `<p class="empty-note">${escapeHtml(erreurMessage(error, "Chargement impossible."))}</p>`;
    }

    function selectedGroupIds() {
        return [...groupsRoot.querySelectorAll('input[name="groupes"]:checked:not(:disabled)')]
            .map((input) => Number(input.value));
    }

    function plural(value, singular, pluralValue) {
        return `${value} ${value > 1 ? pluralValue : singular}`;
    }

    function updateSelectionCount() {
        const count = selectedGroupIds().length;
        groupsCount.textContent = plural(count, "groupe", "groupes");
        groupsRoot.querySelectorAll("[data-centre-card]").forEach((card) => {
            const toggle = card.querySelector("[data-centre-toggle]");
            const choices = [...card.querySelectorAll('input[name="groupes"]:not(:disabled)')];
            const checked = choices.filter((choice) => choice.checked).length;
            toggle.checked = choices.length > 0 && checked === choices.length;
            toggle.indeterminate = checked > 0 && checked < choices.length;
        });
    }

    function renderGroups(catalogue, selectedIds) {
        const selected = new Set(selectedIds || []);
        const centres = new Map();
        catalogue.forEach((group) => {
            if (!centres.has(group.centre_id)) {
                centres.set(group.centre_id, { id: group.centre_id, nom: group.centre, groupes: [] });
            }
            centres.get(group.centre_id).groupes.push(group);
        });

        if (!centres.size) {
            groupsRoot.innerHTML = '<p class="empty-note">Aucun groupe disponible.</p>';
            updateSelectionCount();
            return;
        }

        groupsRoot.innerHTML = [...centres.values()].map((centre) => {
            const hasOpenGroup = centre.groupes.some((group) => group.ouvert);
            return `
                <article class="sortie-centre-choice" data-centre-card>
                    <label class="sortie-centre-choice__header">
                        <input type="checkbox" data-centre-toggle ${hasOpenGroup ? "" : "disabled"}>
                        <span>${escapeHtml(centre.nom)}</span>
                        <small>${centre.groupes.filter((group) => group.ouvert).length}/${centre.groupes.length} ouvert(s)</small>
                    </label>
                    <div class="sortie-centre-choice__groups">
                        ${centre.groupes.map((group) => `
                            <label class="sortie-group-choice${group.ouvert ? "" : " is-closed"}">
                                <input type="checkbox" name="groupes" value="${group.id}"
                                    ${selected.has(group.id) && group.ouvert ? "checked" : ""}
                                    ${group.ouvert ? "" : "disabled"}>
                                <span>${escapeHtml(group.nom)}</span>
                                ${group.ouvert ? "" : '<small>Fermé ce jour</small>'}
                            </label>
                        `).join("")}
                    </div>
                </article>
            `;
        }).join("");

        groupsRoot.querySelectorAll("[data-centre-toggle]").forEach((toggle) => {
            toggle.addEventListener("change", () => {
                const card = toggle.closest("[data-centre-card]");
                card.querySelectorAll('input[name="groupes"]:not(:disabled)').forEach((choice) => {
                    choice.checked = toggle.checked;
                });
                updateSelectionCount();
                schedulePreview();
            });
        });
        groupsRoot.querySelectorAll('input[name="groupes"]').forEach((choice) => {
            choice.addEventListener("change", () => {
                updateSelectionCount();
                schedulePreview();
            });
        });
        updateSelectionCount();
    }

    function coverageLabel(group) {
        if (group.non_couverts > 0) return `${group.non_couverts} non couvert${group.non_couverts > 1 ? "s" : ""}`;
        return "Conforme";
    }

    function renderPreview(data) {
        if (!data.groupes.length) {
            previewRoot.innerHTML = `
                <p class="empty-note">Sélectionnez au moins un groupe pour afficher le récapitulatif.</p>
                ${data.vigilances.length ? `<div class="sortie-preview-alert">${data.vigilances.map(escapeHtml).join(" · ")}</div>` : ""}
            `;
            return;
        }

        const totals = data.totaux;
        const statusClass = totals.non_couverts ? "is-warning" : "is-ok";
        const statusText = totals.non_couverts ? "Encadrement à vérifier" : "Encadrement conforme";
        const floating = data.flottants_par_centre.length
            ? `<div class="sortie-floating-list">${data.flottants_par_centre.map((centre) => `
                <span><strong>${escapeHtml(centre.centre)}</strong> · Flottant${centre.animateurs.length > 1 ? "s" : ""} : ${centre.animateurs.map((item) => escapeHtml(item.nom)).join(", ")}</span>
              `).join("")}</div>`
            : "";

        previewRoot.innerHTML = `
            <div class="sortie-preview-totals">
                <div><strong>${totals.groupes}</strong><span>Groupes</span></div>
                <div><strong>${totals.enfants}</strong><span>Enfants</span></div>
                <div><strong>${totals.animateurs}</strong><span>Animateurs</span></div>
                <div class="${statusClass}"><strong>${totals.non_couverts}</strong><span>Non couverts</span></div>
                <span class="sortie-preview-status ${statusClass}">${statusText}</span>
            </div>
            <div class="sortie-preview-grid">
                ${data.groupes.map((group) => `
                    <article class="sortie-preview-row">
                        <div class="sortie-preview-group"><strong>${escapeHtml(group.groupe)}</strong><span>${escapeHtml(group.centre)}</span></div>
                        <div><span>Effectif</span><strong>${group.effectif}${group.effectif_renseigne ? "" : " *"}</strong></div>
                        <div><span>Taux</span><strong>${escapeHtml(group.ratio_libelle)}</strong></div>
                        <div><span>Requis</span><strong>${group.animateurs_requis}</strong></div>
                        <div class="sortie-preview-team"><span>Équipe prévue</span><strong>${group.animateurs.length ? group.animateurs.map((item) => escapeHtml(item.nom)).join(", ") : "Aucune"}</strong></div>
                        <div class="sortie-preview-coverage ${group.non_couverts ? "is-warning" : "is-ok"}">${coverageLabel(group)}</div>
                    </article>
                `).join("")}
            </div>
            ${floating}
            ${data.groupes.some((group) => !group.effectif_renseigne) ? '<small class="sortie-preview-note">* Effectif non renseigné dans le Planning.</small>' : ""}
            ${data.vigilances.length ? `<div class="sortie-preview-alert">${data.vigilances.map(escapeHtml).join(" · ")}</div>` : ""}
        `;
    }

    async function refreshPreview({ renderCatalogue = false } = {}) {
        window.clearTimeout(previewTimer);
        const date = dateInput.value;
        if (!date) {
            groupsRoot.innerHTML = '<p class="empty-note">Choisissez une date pour afficher les groupes.</p>';
            previewRoot.innerHTML = '<p class="empty-note">Sélectionnez au moins un groupe pour afficher le récapitulatif.</p>';
            updateSelectionCount();
            return;
        }

        previewController?.abort();
        const controller = new AbortController();
        previewController = controller;
        previewLoading.hidden = false;
        try {
            const data = await apiFetch("/api/sorties/apercu/", {
                method: "POST",
                body: JSON.stringify({ date, groupes: selectedGroupIds() }),
                signal: controller.signal,
            });
            if (renderCatalogue) renderGroups(data.catalogue_groupes, data.groupes_selectionnes);
            renderPreview(data);
        } catch (error) {
            if (error?.name === "AbortError") return;
            previewRoot.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(error, "Aperçu impossible."))}</p>`;
        } finally {
            if (previewController === controller) previewLoading.hidden = true;
        }
    }

    function schedulePreview() {
        window.clearTimeout(previewTimer);
        previewTimer = window.setTimeout(() => refreshPreview(), 250);
    }

    function closeCreateDialog() {
        previewController?.abort();
        dialog.close();
    }

    async function openCreateDialog() {
        form.reset();
        form.querySelector(".form-error").hidden = true;
        groupsRoot.innerHTML = '<p class="empty-note">Chargement des groupes…</p>';
        previewRoot.innerHTML = '<p class="empty-note">Sélectionnez au moins un groupe pour afficher le récapitulatif.</p>';
        const periods = WeekPicker.get(pickerRoot)?.getSelectedPeriods() || [];
        if (periods.length) dateInput.value = periods[0].debut;
        dialog.showModal();
        form.elements.nom.focus();
        if (dateInput.value) await refreshPreview({ renderCatalogue: true });
    }

    pickerRoot.addEventListener("week-picker:ready", (event) => {
        const saved = JSON.parse(sessionStorage.getItem("sorties-periods") || "[]");
        if (saved.length) event.detail.picker.setSelectedIds(saved);
        else {
            selectedPeriods = event.detail.picker.getSelectedIds();
            load().catch(showLoadError);
        }
    });
    pickerRoot.addEventListener("week-picker:change", (event) => {
        selectedPeriods = event.detail.ids;
        sessionStorage.setItem("sorties-periods", JSON.stringify(selectedPeriods));
        load().catch(showLoadError);
    });

    document.getElementById("nouvelle-sortie").addEventListener("click", () => {
        openCreateDialog().catch((error) => {
            const errorElement = form.querySelector(".form-error");
            errorElement.textContent = erreurMessage(error, "Impossible d’ouvrir la création.");
            errorElement.hidden = false;
        });
    });
    dialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", closeCreateDialog);
    });
    dialog.addEventListener("close", () => previewController?.abort());
    dateInput.addEventListener("change", () => refreshPreview({ renderCatalogue: true }));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const errorElement = form.querySelector(".form-error");
        errorElement.hidden = true;
        if (!form.reportValidity()) return;

        const payload = {
            nom: String(form.elements.nom.value || "").trim(),
            date: dateInput.value,
            destination: String(form.elements.destination.value || "").trim(),
            groupes: selectedGroupIds(),
        };
        submitButton.disabled = true;
        submitButton.textContent = "Création…";
        try {
            const item = await apiFetch("/api/sorties/", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            location.href = `/sorties/${item.id}/`;
        } catch (error) {
            errorElement.textContent = erreurMessage(error, "Création impossible.");
            errorElement.hidden = false;
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Créer la sortie";
        }
    });
})();
