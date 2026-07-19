document.addEventListener("DOMContentLoaded", () => {
    const pickerRoot = document.getElementById("periode-select");
    const picker = WeekPicker.get(pickerRoot);
    const applyButton = document.getElementById("btn-appliquer-periode");
    const displayedPeriod = document.getElementById("periode-affichee");
    const centresRoot = document.getElementById("recap-centres");
    const employeesRoot = document.getElementById("recap-salaries");
    const legendRoot = document.getElementById("recap-legende");
    const tabButtons = Array.from(document.querySelectorAll("[data-recap-tab]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-recap-panel]"));

    const currencyFormatter = new Intl.NumberFormat("fr-FR", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: 2,
    });

    function formatDateFr(dateStr) {
        return dateStr ? parseLocalDate(dateStr).toLocaleDateString("fr-FR") : "";
    }

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

    function updateSelectionSummary() {
        const selected = picker?.getSelectedPeriods() || [];
        displayedPeriod.textContent = !selected.length
            ? "Aucune semaine sélectionnée"
            : selected.length === 1
                ? `${formatDateFr(selected[0].debut)} au ${formatDateFr(selected[0].fin)}`
                : selected.map(libellePeriodeAvecAnnee).join(" · ");
    }

    function buildApiUrl() {
        const ids = picker?.getSelectedIds() || [];
        if (!ids.length) {
            afficherToast("Sélectionne au moins une semaine.", true);
            return null;
        }
        return `/api/recapitulatif/?periode_ids=${ids.join(",")}`;
    }

    function displayLegend(centres) {
        legendRoot.innerHTML = centres.length ? centres.map(centreBadge).join("") : "";
    }

    function missingRateCell() {
        return '<span class="missing-rate" title="Renseigne la paie par jour dans la fiche salarié">Tarif manquant</span>';
    }

    function displayCentres(data) {
        const centres = data.centres || [];
        displayLegend(centres);
        if (!data.animateurs.length) {
            centresRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour planifié</strong><span>Aucun animateur n’est affecté sur cette période.</span></div>';
            return;
        }

        const firstHeader = centres.map((centre) => `
            <th class="centre-heading" colspan="2" scope="colgroup" style="--centre-color:${escapeHtml(centre.couleur || "#64748b")}">
                <span>${escapeHtml(centre.code || centre.nom)}</span><small>${escapeHtml(centre.nom)}</small>
            </th>`).join("");
        const secondHeader = centres.map(() => '<th class="metric-heading" scope="col">Jours</th><th class="metric-heading" scope="col">Paie</th>').join("");

        const rows = data.animateurs.map((animateur) => {
            const byCentre = new Map((animateur.centres || []).map((item) => [String(item.centre_id), item]));
            const cells = centres.map((centre) => {
                const result = byCentre.get(String(centre.id)) || { jours_travailles: 0, paie: animateur.paie_jour === null ? null : "0.00" };
                return `<td class="days-value">${result.jours_travailles}</td><td class="money-value">${formatMoney(result.paie) || missingRateCell()}</td>`;
            }).join("");
            return `
                <tr>
                    <th scope="row" class="employee-cell"><strong>${escapeHtml(animateur.prenom)}</strong> ${escapeHtml(animateur.nom)}<small>${formatMoney(animateur.paie_jour) ? `${formatMoney(animateur.paie_jour)} / jour` : "Tarif journalier non renseigné"}</small></th>
                    ${cells}
                    <td class="days-value total-column">${animateur.jours_travailles}</td>
                    <td class="money-value total-column">${formatMoney(animateur.paie_totale) || missingRateCell()}</td>
                </tr>`;
        }).join("");

        centresRoot.innerHTML = `
            <table class="recap-table recap-centres-table">
                <thead>
                    <tr><th class="employee-cell employee-cell--header" rowspan="2" scope="col">Animateur</th>${firstHeader}<th class="total-heading" colspan="2" scope="colgroup">Total</th></tr>
                    <tr>${secondHeader}<th class="metric-heading total-column" scope="col">Jours</th><th class="metric-heading total-column" scope="col">Paie</th></tr>
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
                <td class="jours-cell">${animateur.jours_travailles}</td>
                <td class="jours-cell">${formatMoney(animateur.paie_jour) || "Non renseigné"}</td>
                <td class="jours-cell">${formatMoney(animateur.paie_totale) || missingRateCell()}</td>
            </tr>`).join("");
        const warning = data.tarifs_manquants
            ? `<span class="recap-warning">${data.tarifs_manquants} tarif${data.tarifs_manquants > 1 ? "s" : ""} journalier${data.tarifs_manquants > 1 ? "s" : ""} manquant${data.tarifs_manquants > 1 ? "s" : ""}</span>`
            : "";
        employeesRoot.innerHTML = `
            <table class="recap-table">
                <thead><tr><th>Animateur</th><th>Jours travaillés</th><th>Paie par jour</th><th>Paie totale</th></tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><th>Total ${warning}</th><th class="jours-cell">${data.total_jours}</th><th></th><th class="jours-cell">${formatMoney(data.total_paie_connue)}</th></tr></tfoot>
            </table>`;
    }

    function openTab(tabName) {
        const selected = tabName === "totaux" ? "totaux" : "centres";
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
        if (!url) return;
        picker?.close();
        centresRoot.innerHTML = '<div class="loading-note">Calcul des jours et de la paie par centre…</div>';
        employeesRoot.innerHTML = '<div class="loading-note">Calcul des totaux…</div>';
        legendRoot.innerHTML = "";
        applyButton.disabled = true;
        try {
            const data = await apiFetch(url);
            displayCentres(data);
            displayEmployees(data);
        } catch (error) {
            const message = erreurMessage(error, "Le récapitulatif n’a pas pu être chargé.");
            centresRoot.innerHTML = `<div class="empty-state"><strong>Chargement impossible</strong><span>${escapeHtml(message)}</span></div>`;
            employeesRoot.innerHTML = "";
            afficherToast(message, true);
        } finally {
            applyButton.disabled = false;
        }
    }

    tabButtons.forEach((button) => button.addEventListener("click", () => openTab(button.dataset.recapTab)));
    pickerRoot?.addEventListener("week-picker:change", updateSelectionSummary);
    pickerRoot?.addEventListener("week-picker:ready", () => {
        updateSelectionSummary();
        if (picker?.periods.length) {
            const prompt = '<div class="empty-state"><strong>Sélectionne une ou plusieurs semaines</strong><span>Puis clique sur Afficher.</span></div>';
            centresRoot.innerHTML = prompt;
            employeesRoot.innerHTML = prompt;
        } else {
            applyButton.disabled = true;
        }
    });
    applyButton.addEventListener("click", loadRecap);
    openTab("centres");
    updateSelectionSummary();
});
