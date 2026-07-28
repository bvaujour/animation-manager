document.addEventListener("DOMContentLoaded", () => {
    const pickerRoot = document.getElementById("periode-select");
    const picker = WeekPicker.get(pickerRoot);
    const centresRoot = document.getElementById("recap-centres");
    const employeesRoot = document.getElementById("recap-salaries");
    const payrollRoot = document.getElementById("recap-payroll");
    const legendRoot = document.getElementById("recap-legende");
    const tabButtons = Array.from(document.querySelectorAll("[data-recap-tab]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-recap-panel]"));
    const pdfButton = document.getElementById("btn-recap-pdf");
    let selectedPeriods = [];

    const currencyFormatter = new Intl.NumberFormat("fr-FR", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: 2,
    });

    function formatMoney(value) {
        if (value === null || value === undefined || value === "") return null;
        const number = Number(value);
        return Number.isFinite(number) ? currencyFormatter.format(number) : null;
    }

    function textColorFor(background) {
        const hex = String(background || "").replace("#", "");
        if (!/^[0-9a-f]{6}$/i.test(hex)) return "#1f2937";
        const r = Number.parseInt(hex.slice(0, 2), 16);
        const g = Number.parseInt(hex.slice(2, 4), 16);
        const b = Number.parseInt(hex.slice(4, 6), 16);
        return ((r * 299 + g * 587 + b * 114) / 1000) >= 150 ? "#172033" : "#ffffff";
    }

    function centreBadge(centre) {
        const background = centre.couleur || "#e5e7eb";
        return `<span class="place-badge" style="--place-color:${escapeHtml(background)};--place-text:${textColorFor(background)}">${escapeHtml(centre.nom)}</span>`;
    }

    function buildApiUrl() {
        const ids = selectedPeriods.map((period) => period.id);
        return ids.length ? `/api/recapitulatif/?periode_ids=${ids.join(",")}` : null;
    }

    function displayLegend(centres) {
        legendRoot.innerHTML = centres.length ? centres.map(centreBadge).join("") : "";
    }

    function missingRateCell() {
        return '<span class="missing-rate" title="Tarif manquant : renseigne la paie par jour dans la fiche salarié">Manquant</span>';
    }

    function displayCentres(data) {
        const centres = data.centres || [];
        displayLegend(centres);
        if (!data.animateurs.length) {
            centresRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour planifié</strong><span>Aucun animateur n’est affecté sur cette période.</span></div>';
            return;
        }

        const firstHeader = centres.map((centre) => `
            <th class="centre-heading" scope="col" title="${escapeHtml(centre.nom)}" style="--centre-color:${escapeHtml(centre.couleur || "#64748b")}">
                <span>${escapeHtml(centre.code || centre.nom)}</span><small>${escapeHtml(centre.nom)}</small>
            </th>`).join("");
        const secondHeader = centres.map(() => '<th class="metric-heading" scope="col">Jours</th>').join("");

        const rows = data.animateurs.map((animateur) => {
            const byCentre = new Map((animateur.centres || []).map((item) => [String(item.centre_id), item]));
            const cells = centres.map((centre) => {
                const result = byCentre.get(String(centre.id)) || { jours_travailles: 0 };
                return `<td class="days-value">${result.jours_travailles}</td>`;
            }).join("");
            return `
                <tr>
                    <th scope="row" class="employee-cell"><strong>${escapeHtml(animateur.prenom)}</strong> ${escapeHtml(animateur.nom)}</th>
                    ${cells}
                    <td class="money-value rate-column">${formatMoney(animateur.paie_jour) || missingRateCell()}</td>
                    <td class="days-value complementary-column">${animateur.jours_reunion}</td>
                    <td class="days-value complementary-column">${animateur.jours_preparation}</td>
                    <td class="days-value total-column">${animateur.jours_travailles}</td>
                    <td class="money-value total-column">${formatMoney(animateur.paie_totale) || missingRateCell()}</td>
                </tr>`;
        }).join("");

        centresRoot.innerHTML = `
            <table class="recap-table recap-centres-table" style="--recap-min-width:${500 + (centres.length * 58)}px">
                <colgroup>
                    <col class="employee-col">
                    ${centres.map(() => '<col class="centre-col">').join("")}
                    <col class="rate-col">
                    <col class="compact-col"><col class="compact-col">
                    <col class="compact-col"><col class="pay-col">
                </colgroup>
                <thead>
                    <tr><th class="employee-cell employee-cell--header" rowspan="2" scope="col">Animateur</th>${firstHeader}<th class="total-heading rate-column" rowspan="2" scope="col">Paie / jour</th><th class="complementary-heading" colspan="2" scope="colgroup">Journées complémentaires</th><th class="total-heading" colspan="2" scope="colgroup">Total</th></tr>
                    <tr>${secondHeader}<th class="metric-heading complementary-column" scope="col" title="Réunions">Réun.</th><th class="metric-heading complementary-column" scope="col" title="Télétravail / préparation">Prépa.</th><th class="metric-heading total-column" scope="col" title="Total jours">Jours</th><th class="metric-heading total-column" scope="col" title="Paie totale">Paie</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function displayEmployees(data) {
        if (!data.animateurs.length) {
            employeesRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour planifié</strong><span>Aucun animateur n’est affecté sur cette période.</span></div>';
            return;
        }
        const rows = data.animateurs.map((animateur) => `
            <tr>
                <td>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</td>
                <td class="jours-cell">${animateur.jours_affectation}</td>
                <td class="jours-cell">${animateur.jours_reunion}</td>
                <td class="jours-cell">${animateur.jours_preparation}</td>
                <td class="jours-cell">${animateur.jours_travailles}</td>
                <td class="jours-cell">${formatMoney(animateur.paie_jour) || "Non renseigné"}</td>
                <td class="jours-cell">${formatMoney(animateur.paie_totale) || missingRateCell()}</td>
            </tr>`).join("");
        const warning = data.tarifs_manquants
            ? `<span class="recap-warning">${data.tarifs_manquants} tarif${data.tarifs_manquants > 1 ? "s" : ""} journalier${data.tarifs_manquants > 1 ? "s" : ""} manquant${data.tarifs_manquants > 1 ? "s" : ""}</span>`
            : "";
        employeesRoot.innerHTML = `
            <table class="recap-table">
                <thead><tr><th>Animateur</th><th>Affectations</th><th>Réunions</th><th>Télétravail / préparation</th><th>Total jours</th><th>Paie par jour</th><th>Paie totale</th></tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><th>Total ${warning}</th><th></th><th></th><th></th><th class="jours-cell">${data.total_jours}</th><th></th><th class="jours-cell">${formatMoney(data.total_paie_connue)}</th></tr></tfoot>
            </table>`;
    }

    function displayPayroll(data) {
        if (!data.animateurs.length) {
            payrollRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour travaillé</strong><span>Aucun animateur n’est à préparer sur cette période.</span></div>';
            return;
        }
        const rows = data.animateurs.map((animateur) => {
            const hasRate = animateur.paie_jour !== null;
            const mixedPrime = animateur.prime_jour_variable;
            const primeField = hasRate
                ? `<div class="payroll-prime-field"><input type="number" min="0" max="7" step="0.01" inputmode="decimal" value="${mixedPrime ? "" : escapeHtml(animateur.prime_jour || "0.00")}" placeholder="${mixedPrime ? "Variable" : "0,00"}" data-payroll-prime data-previous-value="${mixedPrime ? "" : escapeHtml(animateur.prime_jour || "0.00")}" aria-label="Prime journalière de ${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}"><span>€</span></div>`
                : '<span class="payroll-not-applicable" title="Le tarif journalier doit être renseigné dans la fiche animateur">—</span>';
            return `
                <tr data-payroll-animateur="${animateur.id}">
                    <th scope="row" class="payroll-employee"><strong>${escapeHtml(animateur.prenom)}</strong> ${escapeHtml(animateur.nom)}</th>
                    <td class="payroll-number">${animateur.jours_travailles}</td>
                    <td class="payroll-money">${formatMoney(animateur.paie_jour) || missingRateCell()}</td>
                    <td class="payroll-prime">${primeField}</td>
                    <td class="payroll-money" data-payroll-daily>${formatMoney(animateur.total_jour_avec_prime) || "—"}</td>
                    <td class="payroll-money payroll-estimated" data-payroll-total>${formatMoney(animateur.total_paie_estime) || "—"}</td>
                </tr>`;
        }).join("");
        payrollRoot.innerHTML = `
            <table class="recap-table payroll-table">
                <thead><tr><th>Animateur</th><th>Jours travaillés</th><th>Base/jour</th><th>Prime/jour</th><th>Total/jour</th><th>Total estimé</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function openTab(tabName) {
        const selected = ["centres", "totaux", "paie"].includes(tabName) ? tabName : "centres";
        tabButtons.forEach((button) => {
            const active = button.dataset.recapTab === selected;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        tabPanels.forEach((panel) => {
            panel.hidden = panel.dataset.recapPanel !== selected;
        });
    }

    async function loadRecap() {
        const url = buildApiUrl();
        if (!url) {
            const emptyMessage = '<div class="empty-state"><strong>Aucune période sélectionnée</strong><span>Choisissez une ou plusieurs semaines.</span></div>';
            centresRoot.innerHTML = emptyMessage;
            employeesRoot.innerHTML = emptyMessage;
            payrollRoot.innerHTML = emptyMessage;
            legendRoot.innerHTML = "";
            return;
        }
        picker?.close();
        centresRoot.innerHTML = '<div class="loading-note">Calcul des jours et de la paie par centre…</div>';
        employeesRoot.innerHTML = '<div class="loading-note">Calcul des totaux…</div>';
        payrollRoot.innerHTML = '<div class="loading-note">Préparation des montants…</div>';
        legendRoot.innerHTML = "";
        try {
            const data = await apiFetch(url);
            displayCentres(data);
            displayEmployees(data);
            displayPayroll(data);
        } catch (error) {
            const message = erreurMessage(error, "Le récapitulatif n’a pas pu être chargé.");
            centresRoot.innerHTML = `<div class="empty-state"><strong>Chargement impossible</strong><span>${escapeHtml(message)}</span></div>`;
            employeesRoot.innerHTML = "";
            payrollRoot.innerHTML = "";
            afficherToast(message, true);
        }
    }

    function selectPeriods(periods) {
        selectedPeriods = periods || [];
        if (pdfButton) pdfButton.disabled = selectedPeriods.length === 0;
        loadRecap();
    }

    tabButtons.forEach((button) => button.addEventListener("click", () => openTab(button.dataset.recapTab)));
    payrollRoot.addEventListener("change", async (event) => {
        const input = event.target.closest("[data-payroll-prime]");
        if (!input) return;
        const row = input.closest("[data-payroll-animateur]");
        const previousValue = input.dataset.previousValue;
        const amount = Number(input.value);
        if (input.value.trim() === "" || !Number.isFinite(amount) || amount < 0 || amount > 7) {
            input.value = previousValue;
            afficherToast("La prime journalière doit être comprise entre 0 € et 7 €.", true);
            return;
        }
        input.disabled = true;
        try {
            const result = await apiFetch("/api/recapitulatif/prime-journaliere/", {
                method: "PUT",
                body: JSON.stringify({
                    animateur_id: Number(row.dataset.payrollAnimateur),
                    periode_ids: selectedPeriods.map((period) => period.id),
                    montant: input.value,
                }),
            });
            input.value = result.prime_jour;
            input.dataset.previousValue = result.prime_jour;
            row.querySelector("[data-payroll-daily]").textContent = formatMoney(result.total_jour_avec_prime) || "—";
            row.querySelector("[data-payroll-total]").textContent = formatMoney(result.total_paie_estime) || "—";
            afficherToast("Prime journalière enregistrée.");
        } catch (error) {
            input.value = previousValue;
            afficherToast(erreurMessage(error, "La prime n’a pas pu être enregistrée."), true);
        } finally {
            input.disabled = false;
        }
    });
    pdfButton?.addEventListener("click", () => {
        const ids = selectedPeriods.map((period) => period.id);
        if (!ids.length) return;
        window.location.assign(`/recapitulatif/export-paie.pdf?periode_ids=${ids.join(",")}`);
    });
    pickerRoot?.addEventListener("week-picker:change", (event) => selectPeriods(event.detail?.periods));
    pickerRoot?.addEventListener("week-picker:ready", (event) => {
        const periods = picker?.periods || [];
        if (!periods.length) {
            selectPeriods([]);
            return;
        }
        const selected = event.detail.picker.getSelectedPeriods();
        if (selected.length) {
            selectPeriods(selected);
            return;
        }

        // Hors vacances, proposer directement la prochaine semaine enregistrée.
        const today = formatDateLocal(new Date());
        const persistedDate = WeekPicker.getPersistedDate?.();
        const persistedPeriod = persistedDate
            ? periods.find((period) => period.debut <= persistedDate && period.fin >= persistedDate)
            : null;
        const fallback = persistedPeriod || periods.find((period) => period.debut > today) || periods.at(-1);
        event.detail.picker.setSelectedIds(fallback ? [fallback.id] : []);
    });
    openTab("centres");
});
