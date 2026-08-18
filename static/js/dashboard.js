document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("dashboard-root");
    if (!root) return;

    const apiUrl = root.dataset.apiUrl;
    const preparationStatusUrl = root.dataset.preparationStatusUrl;
    const canForcePreparation = root.dataset.canForcePreparation === "true";
    const loading = document.getElementById("dashboard-loading");
    const centresRoot = document.getElementById("dashboard-centres");
    const alertsRoot = document.getElementById("dashboard-alerts");
    const weekRoot = document.getElementById("dashboard-week");
    const formationsCard = document.getElementById("dashboard-formations-card");
    const formationsRoot = document.getElementById("dashboard-formations");
    const formationsSummary = document.getElementById("dashboard-formations-summary");
    const weekLabel = document.getElementById("dashboard-week-label");
    const centresPeriod = document.getElementById("dashboard-centres-period");
    const alertsPeriod = document.getElementById("dashboard-alerts-period");
    const periodWeeksRoot = document.getElementById("dashboard-period-weeks");
    const pickerRoot = document.getElementById("dashboard-period-nav");
    const picker = window.WeekPicker?.get(pickerRoot) || window.WeekPicker?.init(pickerRoot);
    const vacancesSelectionnees = root.dataset.typeAccueil === "vacances"
        && /^\d{4}-\d{2}-\d{2}$/.test(root.dataset.periodeAccueilDebut || "")
        && /^\d{4}-\d{2}-\d{2}$/.test(root.dataset.periodeAccueilFin || "");
    const vacancesDebut = root.dataset.periodeAccueilDebut || "";
    const vacancesFin = root.dataset.periodeAccueilFin || "";
    let periodWeeks = [];

    function limiterAuxVacances(instance, periods) {
        if (!vacancesSelectionnees) return periods || [];
        periodWeeks = (periods || []).filter((period) => (
            period.type_accueil === "vacances"
            && String(period.debut || "") >= vacancesDebut
            && String(period.fin || "") <= vacancesFin
        )).sort((left, right) => String(left.debut).localeCompare(String(right.debut)));
        instance.setPeriods(periodWeeks);
        return periodWeeks;
    }

    const params = new URLSearchParams(window.location.search);
    const dateParam = params.get("semaine") || params.get("date") || "";
    let selectedDate = /^\d{4}-\d{2}-\d{2}$/.test(dateParam)
        ? dateParam
        : (WeekPicker.getPersistedDate() || formatDateLocal(new Date()));
    let currentPeriod = null;

    function activerTriPersistant(conteneur, cleStockage) {
        const blocs = () => Array.from(conteneur.querySelectorAll(":scope > [data-dashboard-block]"));
        try {
            const ordre = JSON.parse(localStorage.getItem(cleStockage) || "[]");
            if (Array.isArray(ordre)) {
                ordre.forEach((identifiant) => {
                    const bloc = blocs().find((item) => item.dataset.dashboardBlock === identifiant);
                    if (bloc) conteneur.appendChild(bloc);
                });
            }
        } catch {
            localStorage.removeItem(cleStockage);
        }

        let blocDeplace = null;
        blocs().forEach((bloc) => {
            const poignee = document.createElement("button");
            poignee.className = "dashboard-drag-handle";
            poignee.type = "button";
            poignee.draggable = true;
            poignee.title = "Déplacer ce bloc";
            poignee.setAttribute("aria-label", "Déplacer ce bloc");
            poignee.innerHTML = '<span aria-hidden="true">⠿</span>';
            bloc.appendChild(poignee);

            poignee.addEventListener("dragstart", (event) => {
                blocDeplace = bloc;
                bloc.classList.add("is-dragging");
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", bloc.dataset.dashboardBlock);
            });
            poignee.addEventListener("dragend", () => {
                bloc.classList.remove("is-dragging");
                blocDeplace = null;
                localStorage.setItem(
                    cleStockage,
                    JSON.stringify(blocs().map((item) => item.dataset.dashboardBlock))
                );
            });
        });

        conteneur.addEventListener("dragover", (event) => {
            if (!blocDeplace) return;
            event.preventDefault();
            const cible = event.target.closest("[data-dashboard-block]");
            if (!cible || cible === blocDeplace || cible.parentElement !== conteneur) return;
            const rectangle = cible.getBoundingClientRect();
            const apres = event.clientY > rectangle.top + rectangle.height / 2
                || (Math.abs(event.clientY - (rectangle.top + rectangle.height / 2)) < rectangle.height / 3
                    && event.clientX > rectangle.left + rectangle.width / 2);
            conteneur.insertBefore(blocDeplace, apres ? cible.nextSibling : cible);
        });
    }

    activerTriPersistant(document.querySelector(".dashboard-kpis"), "animation-manager-dashboard-kpis");
    activerTriPersistant(document.querySelector(".dashboard-main-grid"), "animation-manager-dashboard-blocs");

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
            critiques: indicateurs.problemes_critiques > 0
                ? "danger" : indicateurs.problemes_moderes > 0 ? "vigilance" : "ok",
        };
    }

    function preparationSemaine(indicateurs, statutManuel) {
        if (statutManuel?.est_force_prete) {
            return {classe: "ready", libelle: "Prête manuellement", estForce: true};
        }
        const etats = Object.values(determinerEtatsKpis(indicateurs));
        if (etats.includes("danger")) return {classe: "incomplete", libelle: "Incomplète", estForce: false};
        if (etats.includes("vigilance")) return {classe: "partial", libelle: "Partiellement préparée", estForce: false};
        return {classe: "ready", libelle: "Prête", estForce: false};
    }

    function titreCarteSemaine(debut, fin) {
        const start = localDate(debut);
        const end = localDate(fin);
        const sameMonth = start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth();
        const startLabel = sameMonth
            ? String(start.getDate())
            : start.toLocaleDateString("fr-FR", {day: "numeric", month: "long"});
        const endLabel = end.toLocaleDateString("fr-FR", {day: "numeric", month: "long"});
        return {libelle: `Du ${startLabel} au ${endLabel}`, annee: String(end.getFullYear())};
    }

    function updatePeriodSelection() {
        periodWeeksRoot?.querySelectorAll("[data-dashboard-period-week]").forEach((card) => {
            const active = card.dataset.dashboardPeriodWeek === selectedDate;
            card.classList.toggle("is-active", active);
            card.setAttribute("aria-pressed", active ? "true" : "false");
        });
    }

    function renderPeriodOverview(results) {
        if (!periodWeeksRoot) return;
        periodWeeksRoot.innerHTML = results.map((data) => {
            const indicateurs = data.indicateurs;
            const debut = data.periode.debut_semaine;
            const preparation = preparationSemaine(indicateurs, data.statut_preparation_manuel);
            const titre = titreCarteSemaine(debut, data.periode.fin_semaine);
            const centres = (data.centres_semaine || []).filter((centre) => centre.jours_ouverts > 0).length;
            const sejours = Number(data.nombre_sejours) || 0;
            const sorties = Number(data.nombre_sorties) || 0;
            const qualifications = (data.centres_semaine || []).reduce(
                (total, centre) => total + (Number(centre.qualifications_manquantes) || 0), 0
            );
            const postes = Number(indicateurs.manque_animateurs) || 0;
            const menu = canForcePreparation ? `
                <details class="dashboard-period-week-menu">
                    <summary aria-label="Actions pour la semaine du ${escapeHtml(debut)}">…</summary>
                    <button type="button" data-dashboard-preparation-force="${preparation.estForce ? "false" : "true"}" data-week="${escapeHtml(debut)}">
                        ${preparation.estForce ? "Revenir au statut automatique" : "Marquer comme prête"}
                    </button>
                </details>` : "";
            return `
                <div class="dashboard-period-week-wrap">
                <button class="dashboard-period-week dashboard-period-week--${preparation.classe}" type="button" data-dashboard-period-week="${escapeHtml(debut)}" aria-pressed="false">
                    <span class="dashboard-period-week-title"><strong>${escapeHtml(titre.libelle)}</strong><small>${escapeHtml(titre.annee)}</small></span>
                    <span class="dashboard-period-week-meta">${centres} centre${centres > 1 ? "s" : ""} ouvert${centres > 1 ? "s" : ""} · ${sejours} séjour${sejours > 1 ? "s" : ""} · ${sorties} sortie${sorties > 1 ? "s" : ""}</span>
                    <span class="dashboard-period-week-status">${escapeHtml(preparation.libelle)}</span>
                    <span class="dashboard-period-week-alerts">
                        <span class="${postes ? "has-alert" : "is-valid"}">${postes ? `${postes} poste${postes > 1 ? "s" : ""} non couvert${postes > 1 ? "s" : ""}` : "Encadrement conforme"}</span>
                        <span class="${qualifications ? "has-alert" : "is-valid"}">${qualifications ? `${qualifications} qualification${qualifications > 1 ? "s" : ""} manquante${qualifications > 1 ? "s" : ""}` : "Qualifications conformes"}</span>
                    </span>
                </button>
                ${menu}
                </div>`;
        }).join("");
        updatePeriodSelection();
    }

    async function loadPeriodOverview(periods) {
        if (!periodWeeksRoot || !periods.length) return;
        periodWeeksRoot.innerHTML = '<div class="dashboard-period-loading">Chargement des semaines…</div>';
        try {
            const results = await Promise.all(periods.map((period) => {
                const query = new URLSearchParams({ semaine: period.debut });
                return apiFetch(`${apiUrl}?${query.toString()}`);
            }));
            renderPeriodOverview(results);
        } catch (error) {
            periodWeeksRoot.innerHTML = emptyState("Chargement impossible", erreurMessage(error, "La vue de la période n’a pas pu être chargée."));
        }
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
        picker?.setActiveDate(data.periode.debut_semaine, {
            persist: false,
        });
        updatePeriodSelection();
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
        document.getElementById("kpi-moderes").textContent = indicateurs.problemes_moderes;
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
            const metrics = centre.jours_ouverts
                ? `<span><b>${escapeHtml(centre.moyenne_enfants_groupe_jour)}</b> enfants / groupe / jour</span><span><b>${escapeHtml(centre.journees_necessaires)}</b> poste${centre.journees_necessaires > 1 ? "s" : ""} requis</span>`
                : `<span class="dashboard-centre-closed">Aucune ouverture cette semaine</span>`;
            return `
                <a class="dashboard-centre-row" style="--centre-color:${escapeHtml(centre.couleur)}" href="${urlPlanning(debut, centre.effectifs_non_renseignes ? "effectifs" : "affectations", centre.id)}">
                    <span class="dashboard-centre-logo">${escapeHtml(centre.code || centre.nom.slice(0, 2).toUpperCase())}</span>
                    <span class="dashboard-centre-copy">
                        <strong>${escapeHtml(centre.nom)}</strong>
                        <span class="dashboard-centre-metrics">${metrics}</span>
                    </span>
                    <span class="dashboard-status dashboard-status--${state}">${escapeHtml(centre.etat_libelle)}</span>
                    <span class="dashboard-row-chevron" aria-hidden="true">›</span>
                </a>`;
        }).join("");
    }

    function renderAlerts(data) {
        document.getElementById("dashboard-alerts-link").href = urlPlanning(data.periode.debut_semaine, "affectations");
        if (!data.alertes.length) {
            alertsRoot.innerHTML = emptyState("Aucune alerte", "Les effectifs, les diplômes, les statuts et l’encadrement sont cohérents pour toute la semaine.");
            return;
        }
        const alertesRegroupees = Array.from(data.alertes.reduce((groupes, alerte) => {
            const groupe = groupes.get(alerte.titre) || { ...alerte, nombre: 0, dates: [] };
            groupe.nombre += 1;
            groupe.dates.push(alerte.date);
            if (alerte.niveau === "danger") groupe.niveau = "danger";
            groupes.set(alerte.titre, groupe);
            return groupes;
        }, new Map()).values());
        alertsRoot.innerHTML = alertesRegroupees.map((alert) => `
            <div class="dashboard-alert-row dashboard-alert-row--${classeEtat(alert.niveau)}">
                <span class="dashboard-alert-symbol" aria-hidden="true">${alert.niveau === "danger" ? "!" : "△"}</span>
                <span class="dashboard-alert-copy"><strong>${escapeHtml(alert.titre)} <span class="dashboard-alert-count">${alert.nombre}</span></strong><small>${escapeHtml(alert.nombre > 1 ? `${alert.nombre} situations cette semaine` : `${dateCourte(alert.date)} · ${alert.detail}`)}</small></span>
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
                    <span class="dashboard-week-metric"><span>Total enfants</span><strong>${day.enfants}</strong></span>
                    <span class="dashboard-week-metric"><span>Maternels</span><strong>${day.enfants_maternels}</strong></span>
                    <span class="dashboard-week-metric"><span>Élémentaires</span><strong>${day.enfants_elementaires}</strong></span>
                    <span class="dashboard-week-metric"><span>Animateurs</span><strong>${day.animateurs_affectes}</strong></span>
                </a>`;
        }).join("");
    }

    function renderFormations(data) {
        if (!formationsCard || !formationsRoot || !formationsSummary) return;
        const formations = data.formations || {elements: [], en_cours: 0, a_cloturer: 0, a_venir: 0, conflits: 0};
        const visible = formations.elements.length > 0 || formations.conflits > 0 || formations.a_cloturer > 0;
        formationsCard.hidden = !visible;
        if (!visible) return;
        formationsSummary.textContent = `${formations.en_cours} en cours · ${formations.a_cloturer} à clôturer · ${formations.a_venir} à venir`;
        const cloture = formations.a_cloturer
            ? `<a class="dashboard-formations-alert" href="/formations/?statut=a_cloturer">⚠ ${formations.a_cloturer} formation${formations.a_cloturer > 1 ? "s" : ""} à clôturer</a>`
            : "";
        const alerte = formations.conflits
            ? `<a class="dashboard-formations-alert" href="/formations/">⚠ ${formations.conflits} conflit${formations.conflits > 1 ? "s" : ""} de planning</a>`
            : "";
        formationsRoot.innerHTML = cloture + alerte + formations.elements.map((formation) => {
            const participants = formation.animateurs.map((item) => escapeHtml(item.prenom)).join(" · ");
            const dates = formation.date_debut === formation.date_fin
                ? dateCourte(formation.date_debut)
                : `${dateCourte(formation.date_debut)} → ${dateCourte(formation.date_fin)}`;
            return `<a class="dashboard-formation-row" href="/formations/${formation.statut === "a_cloturer" ? "?statut=a_cloturer" : ""}">
                <strong>${escapeHtml(formation.intitule)}</strong><small>${formation.statut === "a_cloturer" ? "À clôturer · " : ""}${escapeHtml(dates)}</small><span>${participants}</span>
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
            WeekPicker.setPersistedDate(selectedDate);
            updatePeriodSelection();
            renderKpis(data);
            syncPeriodLabels(data);
            renderCentres(data);
            renderAlerts(data);
            renderWeek(data);
            renderFormations(data);
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
    pickerRoot?.addEventListener("week-picker:ready", (event) => {
        const periods = limiterAuxVacances(event.detail.picker, event.detail?.periods);
        loadPeriodOverview(periods);
        if (currentPeriod) {
            syncPeriodLabels({ periode: currentPeriod });
            return;
        }
        selectedDate = event.detail?.picker?.activeDate || selectedDate;
        loadDashboard();
    });
    pickerRoot?.addEventListener("week-picker:error", loadDashboard);
    periodWeeksRoot?.addEventListener("click", async (event) => {
        const action = event.target.closest("[data-dashboard-preparation-force]");
        if (action) {
            event.stopPropagation();
            const forcer = action.dataset.dashboardPreparationForce === "true";
            if (forcer && !window.confirm("Marquer cette semaine comme prête manuellement ?")) return;
            action.disabled = true;
            try {
                await apiFetch(preparationStatusUrl, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({semaine: action.dataset.week, forcer}),
                });
                await loadPeriodOverview(periodWeeks);
                afficherToast(forcer ? "Semaine marquée comme prête." : "Statut automatique rétabli.");
            } catch (error) {
                action.disabled = false;
                afficherToast(erreurMessage(error, "Le statut n’a pas pu être modifié."), true);
            }
            return;
        }
        const card = event.target.closest("[data-dashboard-period-week]");
        if (!card) return;
        selectedDate = card.dataset.dashboardPeriodWeek;
        updatePeriodSelection();
        loadDashboard();
    });

    if (picker?.ready) {
        const periods = limiterAuxVacances(picker, picker.periods);
        loadPeriodOverview(periods);
        selectedDate = picker.activeDate || selectedDate;
        loadDashboard();
    }
});
