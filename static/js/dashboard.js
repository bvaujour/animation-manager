document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("dashboard-root");
    if (!root) return;

    const apiUrl = root.dataset.apiUrl;
    const loading = document.getElementById("dashboard-loading");
    const centresRoot = document.getElementById("dashboard-centres");
    const alertsRoot = document.getElementById("dashboard-alerts");
    const weekRoot = document.getElementById("dashboard-week");
    const weekLabel = document.getElementById("dashboard-week-label");
    const centresPeriod = document.getElementById("dashboard-centres-period");
    const alertsPeriod = document.getElementById("dashboard-alerts-period");
    const pickerRoot = document.getElementById("dashboard-period-nav");
    const picker = window.WeekPicker?.get(pickerRoot) || window.WeekPicker?.init(pickerRoot);

    const params = new URLSearchParams(window.location.search);
    const dateParam = params.get("semaine") || params.get("date") || "";
    let selectedDate = /^\d{4}-\d{2}-\d{2}$/.test(dateParam)
        ? dateParam
        : formatDateLocal(new Date());
    let currentPeriod = null;

    function localDate(value) {
        return parseLocalDate(value);
    }

    function dateCourte(value) {
        return localDate(value).toLocaleDateString("fr-FR", {
            weekday: "short",
            day: "numeric",
            month: "short",
        });
    }

    function libelleSemaine(debut, fin) {
        const start = localDate(debut);
        const end = localDate(fin);
        const sameYear = start.getFullYear() === end.getFullYear();
        const sameMonth = sameYear && start.getMonth() === end.getMonth();

        if (sameMonth) {
            return `Du ${start.getDate()} au ${end.getDate()} ${end.toLocaleDateString("fr-FR", {
                month: "long",
                year: "numeric",
            })}`;
        }
        if (sameYear) {
            return `Du ${start.toLocaleDateString("fr-FR", { day: "numeric", month: "long" })} au ${end.toLocaleDateString("fr-FR", {
                day: "numeric",
                month: "long",
                year: "numeric",
            })}`;
        }
        return `Du ${start.toLocaleDateString("fr-FR")} au ${end.toLocaleDateString("fr-FR")}`;
    }

    function classeEtat(etat) {
        return ["ok", "vigilance", "danger", "vide"].includes(etat) ? etat : "vide";
    }

    const KPI_STATE_CLASSES = ["ok", "vigilance", "danger"]
        .map((state) => `dashboard-kpi--${state}`);

    function appliquerEtatKpi(elementId, state) {
        const card = document.getElementById(elementId)?.closest(".dashboard-kpi");
        if (!card) return;
        card.classList.remove(...KPI_STATE_CLASSES);
        card.classList.add(`dashboard-kpi--${state}`);
    }

    function determinerEtatsKpis(indicateurs) {
        const groupesOuverts = Number(indicateurs.groupes_ouverts) || 0;
        const necessaires = Number(indicateurs.journees_necessaires) || 0;
        const affectes = Number(indicateurs.journees_animateurs) || 0;
        const effectifsManquants = Number(indicateurs.effectifs_non_renseignes) || 0;
        const couverture = necessaires > 0 && affectes === 0
            ? "danger"
            : affectes === necessaires ? "ok" : "vigilance";
        const saisie = effectifsManquants === 0
            ? "ok"
            : groupesOuverts > 0 && effectifsManquants >= groupesOuverts ? "danger" : "vigilance";

        return {
            couverture,
            enfants: saisie,
            saisie,
            manques: indicateurs.manque_animateurs === 0
                ? "ok"
                : necessaires > 0 && affectes === 0 ? "danger" : "vigilance",
            critiques: indicateurs.problemes_critiques === 0 ? "ok" : "danger",
        };
    }

    function urlPlanning(date, mode = "affectations", centreId = "") {
        const query = new URLSearchParams({ date, mode });
        if (centreId) query.set("centre", centreId);
        return `/planning/?${query.toString()}`;
    }

    function updateBrowserUrl() {
        const url = new URL(window.location.href);
        url.searchParams.set("semaine", selectedDate);
        url.searchParams.delete("date");
        url.searchParams.delete("centre");
        window.history.replaceState({}, "", url);
    }

    function setLoading(value) {
        root.classList.toggle("is-loading", value);
        loading.classList.toggle("is-visible", value);
    }

    function emptyState(title, detail) {
        return `<div class="dashboard-empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
    }

    function syncPeriodLabels(data) {
        const label = libelleSemaine(data.periode.debut_semaine, data.periode.fin_semaine);
        currentPeriod = data.periode;
        weekLabel.textContent = label;
        centresPeriod.textContent = label;
        alertsPeriod.textContent = label;
        const pickerLabel = document.getElementById("dashboard-visible-period");
        if (pickerLabel) pickerLabel.textContent = label;
        picker?.setActiveDate(data.periode.debut_semaine);
    }

    function renderKpis(data) {
        const indicateurs = data.indicateurs;
        const etats = determinerEtatsKpis(indicateurs);
        appliquerEtatKpi("kpi-couverture", etats.couverture);
        appliquerEtatKpi("kpi-enfants", etats.enfants);
        appliquerEtatKpi("kpi-vigilances", etats.saisie);
        appliquerEtatKpi("kpi-manques", etats.manques);
        appliquerEtatKpi("kpi-critiques", etats.critiques);
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
            ? `${indicateurs.groupes_a_risque} situation${indicateurs.groupes_a_risque > 1 ? "s" : ""} à risque`
            : "Toutes les équipes sont couvertes";
        document.getElementById("kpi-critiques").textContent = indicateurs.problemes_critiques;
    }

    function renderCentres(data) {
        const debut = data.periode.debut_semaine;
        document.getElementById("dashboard-centres-link").href = urlPlanning(debut, "affectations");
        const centres = data.centres_semaine || [];
        if (!centres.length) {
            centresRoot.innerHTML = emptyState("Aucun centre", "Aucun centre n’est enregistré.");
            return;
        }
        centresRoot.innerHTML = centres.map((centre) => {
            const state = classeEtat(centre.etat);
            const jours = `${centre.jours_ouverts} jour${centre.jours_ouverts > 1 ? "s" : ""} ouvert${centre.jours_ouverts > 1 ? "s" : ""}`;
            const details = centre.jours_ouverts
                ? `${centre.enfants} enfants · ${centre.journees_animateurs}/${centre.journees_necessaires} journées anim. · ${jours}`
                : "Aucune ouverture sur cette semaine";
            return `
                <a class="dashboard-centre-row" style="--centre-color:${escapeHtml(centre.couleur)}" href="${urlPlanning(debut, centre.effectifs_non_renseignes ? "effectifs" : "affectations", centre.id)}">
                    <span class="dashboard-centre-logo">${escapeHtml(centre.code || centre.nom.slice(0, 2).toUpperCase())}</span>
                    <span class="dashboard-centre-copy"><strong>${escapeHtml(centre.nom)}</strong><small>${escapeHtml(details)}</small></span>
                    <span class="dashboard-status dashboard-status--${state}">${escapeHtml(centre.etat_libelle)}</span>
                    <span class="dashboard-row-chevron" aria-hidden="true">›</span>
                </a>`;
        }).join("");
    }

    function renderAlerts(data) {
        document.getElementById("dashboard-alerts-link").href = urlPlanning(data.periode.debut_semaine, "affectations");
        if (!data.alertes.length) {
            alertsRoot.innerHTML = emptyState("Aucune alerte", "Les effectifs, les qualifications et l’encadrement sont cohérents pour toute la semaine.");
            return;
        }
        alertsRoot.innerHTML = data.alertes.map((alert) => `
            <div class="dashboard-alert-row dashboard-alert-row--${classeEtat(alert.niveau)}">
                <span class="dashboard-alert-symbol" aria-hidden="true">${alert.niveau === "danger" ? "!" : "△"}</span>
                <span class="dashboard-alert-copy"><strong>${escapeHtml(alert.titre)}</strong><small>${escapeHtml(`${dateCourte(alert.date)} · ${alert.detail}`)}</small></span>
                <a class="dashboard-alert-action" href="${escapeHtml(alert.action_url)}">${escapeHtml(alert.action_label)}</a>
            </div>`).join("");
    }

    function renderWeek(data) {
        const debut = data.periode.debut_semaine;
        document.getElementById("dashboard-week-planning-link").href = urlPlanning(debut, "affectations");
        if (!data.semaine.length) {
            weekRoot.innerHTML = emptyState("Semaine vide", "Aucune donnée n’est enregistrée.");
            return;
        }
        weekRoot.innerHTML = data.semaine.map((day) => {
            const state = classeEtat(day.etat);
            const date = localDate(day.date);
            return `
                <a class="dashboard-week-day dashboard-week-day--${state}" href="${urlPlanning(day.date, day.effectifs_non_renseignes ? "effectifs" : "affectations")}">
                    <header><strong>${date.toLocaleDateString("fr-FR", { weekday: "long" })}</strong><small>${date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}</small></header>
                    <span class="dashboard-week-metric"><span>Enfants</span><strong>${day.enfants}</strong></span>
                    <span class="dashboard-week-metric"><span>Animateurs</span><strong>${day.animateurs_affectes}/${day.animateurs_necessaires}</strong></span>
                    <span class="dashboard-week-metric"><span>Groupes</span><strong>${day.groupes_ouverts}</strong></span>
                </a>`;
        }).join("");
    }

    function updateQuickActions(data) {
        const debut = data.periode.debut_semaine;
        document.getElementById("action-effectifs").href = urlPlanning(debut, "effectifs");
        document.getElementById("action-affectations").href = urlPlanning(debut, "affectations");
    }

    function showError(error) {
        const message = erreurMessage(error, "Le tableau de bord n’a pas pu être chargé.");
        centresRoot.innerHTML = emptyState("Chargement impossible", message);
        alertsRoot.innerHTML = "";
        weekRoot.innerHTML = "";
        afficherToast(message, true);
    }

    async function loadDashboard() {
        setLoading(true);
        const query = new URLSearchParams({ semaine: selectedDate });
        try {
            const data = await apiFetch(`${apiUrl}?${query.toString()}`);
            selectedDate = data.periode.debut_semaine;
            renderKpis(data);
            syncPeriodLabels(data);
            renderCentres(data);
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

    function changeWeek(delta) {
        const date = localDate(selectedDate);
        date.setDate(date.getDate() + (delta * 7));
        selectedDate = formatDateLocal(date);
        loadDashboard();
    }

    document.getElementById("dashboard-prev-week")?.addEventListener("click", () => changeWeek(-1));
    document.getElementById("dashboard-next-week")?.addEventListener("click", () => changeWeek(1));
    document.getElementById("dashboard-current-week")?.addEventListener("click", () => {
        selectedDate = formatDateLocal(new Date());
        loadDashboard();
    });
    pickerRoot?.addEventListener("week-picker:select", (event) => {
        selectedDate = event.detail?.period?.debut || event.detail?.date || selectedDate;
        loadDashboard();
    });
    pickerRoot?.addEventListener("week-picker:ready", () => {
        if (currentPeriod) syncPeriodLabels({ periode: currentPeriod });
    });

    loadDashboard();
});
