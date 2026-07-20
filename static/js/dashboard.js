document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("dashboard-root");
    if (!root) return;

    const apiUrl = root.dataset.apiUrl;
    const centreSelect = document.getElementById("dashboard-centre-select");
    const loading = document.getElementById("dashboard-loading");
    const calendarRoot = document.getElementById("dashboard-calendar");
    const monthLabel = document.getElementById("dashboard-month-label");
    const centresRoot = document.getElementById("dashboard-centres");
    const upcomingRoot = document.getElementById("dashboard-upcoming");
    const alertsRoot = document.getElementById("dashboard-alerts");
    const weekRoot = document.getElementById("dashboard-week");
    const selectedDateLabel = document.getElementById("dashboard-selected-date");
    const weekLabel = document.getElementById("dashboard-week-label");

    const params = new URLSearchParams(window.location.search);
    let selectedDate = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "")
        ? params.get("date")
        : formatDateLocal(new Date());
    let selectedCentre = /^\d+$/.test(params.get("centre") || "") ? params.get("centre") : "";
    let centresInitialises = false;

    function localDate(value) {
        return parseLocalDate(value);
    }

    function dateLongue(value) {
        return localDate(value).toLocaleDateString("fr-FR", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
        });
    }

    function dateCourte(value) {
        return localDate(value).toLocaleDateString("fr-FR", {
            weekday: "short",
            day: "numeric",
            month: "short",
        });
    }

    function moisFrancais(annee, mois) {
        return new Date(annee, mois - 1, 1).toLocaleDateString("fr-FR", {
            month: "long",
            year: "numeric",
        });
    }

    function classeEtat(etat) {
        return ["ok", "info", "vigilance", "danger", "vide"].includes(etat) ? etat : "vide";
    }

    function urlPlanning(date, mode = "affectations", centreId = selectedCentre) {
        const query = new URLSearchParams({ date, mode });
        if (centreId) query.set("centre", centreId);
        return `/planning/?${query.toString()}`;
    }

    function updateBrowserUrl() {
        const url = new URL(window.location.href);
        url.searchParams.set("date", selectedDate);
        if (selectedCentre) url.searchParams.set("centre", selectedCentre);
        else url.searchParams.delete("centre");
        window.history.replaceState({}, "", url);
    }

    function setLoading(value) {
        root.classList.toggle("is-loading", value);
        loading.classList.toggle("is-visible", value);
    }

    function emptyState(title, detail) {
        return `<div class="dashboard-empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
    }

    function renderCentresSelect(data) {
        if (!centresInitialises) {
            centreSelect.innerHTML = '<option value="">Tous les centres</option>' + data.centres_filtres.map((centre) =>
                `<option value="${centre.id}">${escapeHtml(centre.nom)}</option>`
            ).join("");
            centresInitialises = true;
        }
        centreSelect.value = selectedCentre;
    }

    function renderKpis(data) {
        const indicateurs = data.indicateurs;
        document.getElementById("kpi-couverture").textContent = `${indicateurs.journees_animateurs} / ${indicateurs.journees_necessaires}`;
        document.getElementById("kpi-couverture-detail").textContent = `${indicateurs.couverture_pourcentage}% des besoins couverts`;
        document.getElementById("kpi-enfants").textContent = indicateurs.enfants;
        const variation = indicateurs.variation_enfants;
        document.getElementById("kpi-enfants-detail").textContent = variation === 0
            ? "Stable par rapport à la semaine précédente"
            : `${variation > 0 ? "+" : ""}${variation} par rapport à la semaine précédente`;
        document.getElementById("kpi-vigilances").textContent = indicateurs.effectifs_non_renseignes;
        document.getElementById("kpi-manques").textContent = indicateurs.manque_animateurs;
        document.getElementById("kpi-manques-detail").textContent = indicateurs.groupes_a_risque
            ? `${indicateurs.groupes_a_risque} groupe${indicateurs.groupes_a_risque > 1 ? "s" : ""} à risque`
            : "Toutes les équipes sont couvertes";
        document.getElementById("kpi-critiques").textContent = indicateurs.problemes_critiques;
    }

    function renderCalendar(data) {
        monthLabel.textContent = moisFrancais(data.periode.annee, data.periode.mois);
        calendarRoot.innerHTML = "";
        if (!data.calendrier.length) {
            calendarRoot.innerHTML = emptyState("Aucune donnée", "Aucun jour n’est disponible pour ce mois.");
            return;
        }

        const firstDate = localDate(data.calendrier[0].date);
        const firstOffset = (firstDate.getDay() + 6) % 7;
        for (let i = 0; i < firstOffset; i += 1) {
            const empty = document.createElement("span");
            empty.className = "dashboard-calendar-empty";
            calendarRoot.appendChild(empty);
        }

        const today = formatDateLocal(new Date());
        data.calendrier.forEach((day) => {
            const button = document.createElement("button");
            const state = classeEtat(day.etat);
            button.type = "button";
            button.className = "dashboard-calendar-day";
            button.dataset.date = day.date;
            if (day.date === selectedDate) button.classList.add("is-selected");
            if (day.date === today) button.classList.add("is-today");
            button.setAttribute("aria-label", `${dateLongue(day.date)} : ${day.enfants} enfants, ${day.animateurs_affectes}/${day.animateurs_necessaires} animateurs`);
            button.innerHTML = `<span>${day.jour}</span>${day.groupes_ouverts ? `<span class="dashboard-calendar-day-dots"><i class="is-${state}"></i></span>` : ""}`;
            button.addEventListener("click", () => {
                selectedDate = day.date;
                loadDashboard();
            });
            calendarRoot.appendChild(button);
        });
    }

    function renderCentres(data) {
        selectedDateLabel.textContent = dateLongue(data.date_selectionnee);
        document.getElementById("dashboard-centres-link").href = urlPlanning(data.date_selectionnee, "affectations");
        const centres = data.jour.centres || [];
        if (!centres.length) {
            centresRoot.innerHTML = emptyState("Aucun centre ouvert", "Aucun groupe n’est ouvert à cette date.");
            return;
        }
        centresRoot.innerHTML = centres.map((centre) => {
            const state = classeEtat(centre.etat);
            const details = `${centre.enfants} enfant${centre.enfants > 1 ? "s" : ""} · ${centre.animateurs_affectes}/${centre.animateurs_necessaires} anim.`;
            return `
                <a class="dashboard-centre-row" style="--centre-color:${escapeHtml(centre.couleur)}" href="${urlPlanning(data.date_selectionnee, state === "vigilance" ? "effectifs" : "affectations", centre.id)}">
                    <span class="dashboard-centre-logo">${escapeHtml(centre.code || centre.nom.slice(0, 2).toUpperCase())}</span>
                    <span class="dashboard-centre-copy"><strong>${escapeHtml(centre.nom)}</strong><small>${escapeHtml(details)}</small></span>
                    <span class="dashboard-status dashboard-status--${state}">${escapeHtml(centre.etat_libelle)}</span>
                    <span class="dashboard-row-chevron" aria-hidden="true">›</span>
                </a>`;
        }).join("");
    }

    function renderUpcoming(data) {
        if (!data.prochains_jours.length) {
            upcomingRoot.innerHTML = emptyState("Aucun jour à venir", "Aucune ouverture n’est enregistrée prochainement.");
            return;
        }
        upcomingRoot.innerHTML = data.prochains_jours.map((item) => {
            const date = localDate(item.date);
            const state = classeEtat(item.etat);
            return `
                <a class="dashboard-upcoming-row" href="${escapeHtml(item.action_url)}">
                    <span class="dashboard-upcoming-date"><strong>${date.getDate()}</strong><small>${date.toLocaleDateString("fr-FR", { month: "short" })}</small></span>
                    <span class="dashboard-upcoming-copy"><strong>${escapeHtml(item.centre_nom)} · ${item.groupes} groupe${item.groupes > 1 ? "s" : ""}</strong><small>${item.enfants} enfants · ${item.animateurs_affectes}/${item.animateurs_necessaires} animateurs</small></span>
                    <span class="dashboard-status dashboard-status--${state}">${escapeHtml(item.etat_libelle)}</span>
                </a>`;
        }).join("");
    }

    function renderAlerts(data) {
        if (!data.alertes.length) {
            alertsRoot.innerHTML = emptyState("Aucune alerte", "Les effectifs et l’encadrement sont cohérents pour cette journée.");
            return;
        }
        alertsRoot.innerHTML = data.alertes.map((alert) => `
            <div class="dashboard-alert-row dashboard-alert-row--${classeEtat(alert.niveau)}">
                <span class="dashboard-alert-symbol" aria-hidden="true">${alert.niveau === "danger" ? "!" : "△"}</span>
                <span class="dashboard-alert-copy"><strong>${escapeHtml(alert.titre)}</strong><small>${escapeHtml(alert.detail)}</small></span>
                <a class="dashboard-alert-action" href="${escapeHtml(alert.action_url)}">${escapeHtml(alert.action_label)}</a>
            </div>`).join("");
    }

    function renderWeek(data) {
        const debut = data.periode.debut_semaine;
        const fin = data.periode.fin_semaine;
        weekLabel.textContent = `Du ${localDate(debut).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })} au ${localDate(fin).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })}`;
        document.getElementById("dashboard-week-planning-link").href = urlPlanning(debut, "affectations");
        if (!data.semaine.length) {
            weekRoot.innerHTML = emptyState("Semaine vide", "Aucune donnée n’est enregistrée.");
            return;
        }
        weekRoot.innerHTML = data.semaine.map((day) => {
            const state = classeEtat(day.etat);
            const date = localDate(day.date);
            return `
                <a class="dashboard-week-day dashboard-week-day--${state}" href="${urlPlanning(day.date, state === "vigilance" ? "effectifs" : "affectations")}">
                    <header><strong>${date.toLocaleDateString("fr-FR", { weekday: "long" })}</strong><small>${date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}</small></header>
                    <span class="dashboard-week-metric"><span>Enfants</span><strong>${day.enfants}</strong></span>
                    <span class="dashboard-week-metric"><span>Animateurs</span><strong>${day.animateurs_affectes}/${day.animateurs_necessaires}</strong></span>
                    <span class="dashboard-week-metric"><span>Groupes</span><strong>${day.groupes_ouverts}</strong></span>
                </a>`;
        }).join("");
    }

    function updateQuickActions(data) {
        document.getElementById("action-effectifs").href = urlPlanning(data.date_selectionnee, "effectifs");
        document.getElementById("action-affectations").href = urlPlanning(data.date_selectionnee, "affectations");
    }

    function showError(error) {
        const message = erreurMessage(error, "Le tableau de bord n’a pas pu être chargé.");
        centresRoot.innerHTML = emptyState("Chargement impossible", message);
        upcomingRoot.innerHTML = "";
        alertsRoot.innerHTML = "";
        weekRoot.innerHTML = "";
        afficherToast(message, true);
    }

    async function loadDashboard() {
        setLoading(true);
        const query = new URLSearchParams({ date: selectedDate });
        if (selectedCentre) query.set("centre_id", selectedCentre);
        try {
            const data = await apiFetch(`${apiUrl}?${query.toString()}`);
            selectedDate = data.date_selectionnee;
            selectedCentre = data.centre_selectionne ? String(data.centre_selectionne) : "";
            renderCentresSelect(data);
            renderKpis(data);
            renderCalendar(data);
            renderCentres(data);
            renderUpcoming(data);
            renderAlerts(data);
            renderWeek(data);
            updateQuickActions(data);
            updateBrowserUrl();
        } catch (error) {
            showError(error);
        } finally {
            setLoading(false);
        }
    }

    function changeMonth(delta) {
        const date = localDate(selectedDate);
        const target = new Date(date.getFullYear(), date.getMonth() + delta, 1);
        selectedDate = formatDateLocal(target);
        loadDashboard();
    }

    document.getElementById("dashboard-month-prev").addEventListener("click", () => changeMonth(-1));
    document.getElementById("dashboard-month-next").addEventListener("click", () => changeMonth(1));
    centreSelect.addEventListener("change", () => {
        selectedCentre = centreSelect.value;
        loadDashboard();
    });

    loadDashboard();
});
