document.addEventListener("DOMContentLoaded", () =>
{
    const calendarsContainer = document.getElementById("home-calendars");
    const documentsContainer = document.getElementById("home-documents");
    const btnPrevWeek = document.getElementById("home-prev-week");
    const btnCurrentWeek = document.getElementById("home-current-week");
    const btnNextWeek = document.getElementById("home-next-week");
    const visiblePeriod = document.getElementById("home-visible-period");
    const calendrierPersonnel = document.querySelector("[data-personal-calendar]") !== null;


    const CENTRES_REPLIES_KEY = "calendar-centres-replies";

    function lireCentresReplies()
    {
        try
        {
            const ids = JSON.parse(localStorage.getItem(CENTRES_REPLIES_KEY) || "[]");
            return new Set(Array.isArray(ids) ? ids.map(Number).filter(Number.isFinite) : []);
        }
        catch
        {
            return new Set();
        }
    }

    const centresReplies = lireCentresReplies();

    function sauvegarderCentresReplies()
    {
        localStorage.setItem(CENTRES_REPLIES_KEY, JSON.stringify([...centresReplies]));
    }
    const calendars = [];
    let chargementCalendriers = 0;
    const today = new Date();
    const pageInitialDate = document.querySelector("[data-calendar-date]")?.dataset.calendarDate;
    const persistedWeek = WeekPicker.getPersistedDate();
    let currentDate = pageInitialDate
        ? parseLocalDate(pageInitialDate)
        : (persistedWeek ? parseLocalDate(persistedWeek) : new Date(today));

    function message(container, texte)
    {
        if (!container) return;
        container.innerHTML = `<p class="empty-note">${texte}</p>`;
    }



    function periodePourDate(dateStr)
    {
        const periodesEnregistrees = WeekPicker.get("home-period-nav")?.periods || [];
        return periodesEnregistrees.find((periode) => periode.debut <= dateStr && periode.fin >= dateStr)
            || periodesOuvertes().find((periode) => periode.debut <= dateStr && periode.fin >= dateStr)
            || null;
    }

    function mettreAJourPeriodeVisible()
    {
        const dateCourante = dateIsoLocale(currentDate);
        WeekPicker.get("home-period-nav")?.setActiveDate(dateCourante, { persist: false });
        if (!visiblePeriod) return;
        const periode = periodePourDate(dateCourante);
        visiblePeriod.textContent = periode
            ? libellePeriodeAvecDates(periode)
            : libelleSemaine(currentDate);
    }

    function libelleSemaine(dateReference)
    {
        const lundi = new Date(dateReference);
        lundi.setDate(lundi.getDate() - ((lundi.getDay() + 6) % 7));
        const dimanche = new Date(lundi);
        dimanche.setDate(dimanche.getDate() + 6);
        const format = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
        return `Semaine du ${format.format(lundi)} au ${format.format(dimanche)}`;
    }

    function synchroniserCalendriers()
    {
        WeekPicker.setPersistedDate(dateIsoLocale(currentDate));
        calendars.forEach((calendar) => calendar.gotoDate(currentDate));
        requestAnimationFrame(mettreAJourPeriodeVisible);
    }

    function changerPeriode(delta)
    {
        if (calendrierPersonnel)
        {
            const picker = WeekPicker.get("home-period-nav");
            const periodes = [...(picker?.periods || [])]
                .sort((a, b) => String(a.debut).localeCompare(String(b.debut)));
            const dateCourante = dateIsoLocale(currentDate);
            const indexCourant = periodes.findIndex(
                (periode) => periode.debut <= dateCourante && periode.fin >= dateCourante
            );
            let cible = indexCourant >= 0 ? periodes[indexCourant + delta] : null;
            if (!cible)
            {
                cible = delta > 0
                    ? periodes.find((periode) => periode.debut > dateCourante)
                    : [...periodes].reverse().find((periode) => periode.fin < dateCourante);
            }
            if (!cible) return;
            currentDate = new Date(`${cible.debut}T12:00:00`);
            mettreAJourPeriodeVisible();
            chargerCalendriers();
            return;
        }
        const periodes = periodesOuvertes();
        if (!periodes.length) return;
        const dateCourante = dateIsoLocale(currentDate);
        const cible = delta > 0
            ? periodes.find((periode) => periode.debut > dateCourante)
            : [...periodes].reverse().find((periode) => periode.debut < dateCourante);
        if (!cible) return;
        currentDate = new Date(`${cible.debut}T12:00:00`);
        chargerCalendriers();
    }

    document.getElementById("home-period-nav")?.addEventListener("week-picker:select", (event) => {
        if (!event.detail?.date) return;
        currentDate = new Date(`${event.detail.date}T12:00:00`);
        chargerCalendriers();
    });

    document.getElementById("home-period-nav")?.addEventListener("week-picker:ready", (event) => {
        const dateInitiale = event.detail?.picker?.activeDate;
        if (!dateInitiale) return;
        const dateNormalisee = new Date(`${dateInitiale}T12:00:00`);
        const doitRecharger = dateIsoLocale(currentDate) !== dateInitiale;
        currentDate = dateNormalisee;
        mettreAJourPeriodeVisible();
        if (doitRecharger) chargerCalendriers();
    });

    function retourPeriodeActuelle()
    {
        if (calendrierPersonnel)
        {
            currentDate = new Date(today);
            mettreAJourPeriodeVisible();
            chargerCalendriers();
            return;
        }
        const periodes = periodesOuvertes();
        const aujourdHui = dateIsoLocale(today);
        const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
        const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
        const cible = courante || prochaine || periodes.at(-1);
        if (!cible) return;
        currentDate = new Date(`${cible.debut}T12:00:00`);
        chargerCalendriers();
    }

    function dateIsoLocale(date)
    {
        const annee = date.getFullYear();
        const mois = String(date.getMonth() + 1).padStart(2, "0");
        const jour = String(date.getDate()).padStart(2, "0");
        return `${annee}-${mois}-${jour}`;
    }

    function evenementCouvreJour(groupe, date)
    {
        const iso = dateIsoLocale(date);
        const periodes = Array.isArray(groupe.periodes) ? groupe.periodes : [];
        if (!groupe.permanent && !periodes.some((periode) => iso >= periode.debut && iso <= (periode.fin_ouverture || periode.fin))) return false;
        const numeroJour = (date.getDay() + 6) % 7;
        const joursOuverts = Array.isArray(groupe.jours_ouverts)
            ? groupe.jours_ouverts.map(Number)
            : [0, 1, 2, 3, 4, 5];
        if (!joursOuverts.includes(numeroJour)) return false;
        return !(groupe.dates_exclues || []).includes(iso)
            && !(groupe.dates_feriees_fermees || []).includes(iso);
    }

    function groupeChevauchePlage(groupe, debutStr, finExclusiveStr)
    {
        return groupe.permanent || (groupe.periodes || []).some((periode) => periode.debut < finExclusiveStr && (periode.fin_ouverture || periode.fin) >= debutStr);
    }

    function periodesOuvertes()
    {
        const uniques = new Map();
        calendars.forEach((calendar) =>
            (calendar.evenementPlanning?.periodes || []).forEach((periode) =>
            {
                const cle = periode.id || `${periode.debut}|${periode.fin}`;
                const finOuverture = periode.fin_ouverture || periode.fin;
                const existante = uniques.get(cle);
                if (!existante)
                {
                    uniques.set(cle, { ...periode, fin_periode: periode.fin, fin: finOuverture });
                }
                else if (finOuverture > existante.fin)
                {
                    existante.fin = finOuverture;
                }
            })
        );
        return [...uniques.values()].sort((a, b) => a.debut.localeCompare(b.debut));
    }

    function mettreAJourVisibilite(info)
    {
        if (!info) return;
        const debut = dateIsoLocale(info.start);
        const fin = dateIsoLocale(info.end);

        document.querySelectorAll(".home-event-calendar-card").forEach((card) => {
            const calendar = calendars.find((item) => Number(item.evenementPlanning?.id) === Number(card.dataset.groupeId));
            card.hidden = !calendar || !groupeChevauchePlage(calendar.evenementPlanning, debut, fin);
        });

        document.querySelectorAll(".home-calendar-card").forEach((card) => {
            const groupes = Array.from(card.querySelectorAll(".home-event-calendar-card"));
            const visibles = groupes.filter((groupe) => !groupe.hidden);
            // Le lieu reste affiché en permanence ; seuls les groupes sont filtrés.
            card.hidden = false;

            const compteur = card.querySelector(".home-calendar-toggle-meta");
            if (compteur) compteur.textContent = visibles.length
                ? `${visibles.length} groupe${visibles.length > 1 ? "s" : ""}`
                : "Aucun groupe";

            const etatVide = card.querySelector(".calendar-site-empty");
            if (etatVide) etatVide.hidden = visibles.length > 0;

            if (!card.classList.contains("collapsed"))
            {
                window.setTimeout(() => {
                    visibles.forEach((groupe) => {
                        const calendar = calendars.find((item) =>
                            Number(item.evenementPlanning?.id) === Number(groupe.dataset.groupeId)
                        );
                        calendar?.updateSize();
                    });
                }, 20);
            }
        });
    }


    function creerCalendrierEvenement(centre, evenement, liste, calendriersCentre)
    {
        const eventCard = document.createElement("article");
        eventCard.classList.add("home-event-calendar-card", "calendar-group-card");
        eventCard.dataset.groupeId = evenement.id;

        const header = document.createElement("header");
        header.classList.add("home-event-calendar-header", "calendar-group-header");
        header.innerHTML = `
            <h3 class="calendar-group-name">${escapeHtml(evenement.nom)}</h3>
            <span class="calendar-group-meta">Objectif ${escapeHtml(evenement.effectif_cible)}</span>
        `;

        const calendarEl = document.createElement("div");
        calendarEl.classList.add("home-calendar", "shared-calendar");

        eventCard.appendChild(header);
        eventCard.appendChild(calendarEl);
        liste.appendChild(eventCard);

        const calendar = new FullCalendar.Calendar(calendarEl,
        {
            initialView: "dayGridWeek",
            initialDate: currentDate,
            locale: "fr",
            firstDay: 1,
            hiddenDays: PlanningData.hiddenDays(evenement),
            height: "auto",
            fixedWeekCount: false,
            dayMaxEvents: false,
            dayMaxEventRows: false,
            headerToolbar: false,
            footerToolbar: false,
            editable: false,
            droppable: false,
            selectable: false,
            events: (fetchInfo, successCallback, failureCallback) => {
                Promise.all([
                    PlanningData.fetchWeekEvents(fetchInfo.startStr, fetchInfo.endStr),
                    PlanningData.fetchWeekEffectifs(fetchInfo.startStr, fetchInfo.endStr),
                ])
                    .then(([events, effectifs]) => {
                        let affectations = (events || []).filter(
                            (item) => Number(item.extendedProps?.evenement_id || item.extendedProps?.groupe_id)
                                === Number(evenement.id)
                        );
                        let espacesLignesPortail = [];
                        if (window.AnimatorPlanningPortal) {
                            const joursParAnimateur = new Map();
                            const libellesAnimateurs = new Map();

                            affectations.forEach((item) => {
                                const animateurId = Number(item.extendedProps?.animateur_id);
                                if (!animateurId) return;
                                libellesAnimateurs.set(
                                    animateurId,
                                    String(item.extendedProps?.animateur_nom || item.title || "")
                                );
                                const jours = joursParAnimateur.get(animateurId) || new Set();
                                let courant = parseLocalDate(item.start);
                                let fin = item.end ? parseLocalDate(item.end) : new Date(courant);
                                if (!item.end) fin.setDate(fin.getDate() + 1);
                                while (courant < fin) {
                                    jours.add(formatDateLocal(courant));
                                    courant.setDate(courant.getDate() + 1);
                                }
                                joursParAnimateur.set(animateurId, jours);
                            });

                            // Une ligne fixe par animateur sur la semaine. Deux animateurs
                            // qui ne travaillent jamais le même jour peuvent partager la
                            // même ligne : on garde ainsi la grille la plus compacte possible.
                            const animateursOrdonnes = Array.from(joursParAnimateur.keys()).sort((a, b) =>
                                String(libellesAnimateurs.get(a) || "").localeCompare(
                                    String(libellesAnimateurs.get(b) || ""),
                                    "fr",
                                    { sensitivity: "base" }
                                )
                            );
                            const joursParLigne = [];
                            const ligneParAnimateur = new Map();
                            animateursOrdonnes.forEach((animateurId) => {
                                const jours = joursParAnimateur.get(animateurId) || new Set();
                                let ligne = joursParLigne.findIndex((joursOccupes) =>
                                    !Array.from(jours).some((date) => joursOccupes.has(date))
                                );
                                if (ligne < 0) {
                                    ligne = joursParLigne.length;
                                    joursParLigne.push(new Set());
                                }
                                jours.forEach((date) => joursParLigne[ligne].add(date));
                                ligneParAnimateur.set(animateurId, ligne);
                            });

                            affectations = affectations.map((item) => ({
                                ...item,
                                title: String(item.title || "").split(" · ")[0],
                                extendedProps: {
                                    ...(item.extendedProps || {}),
                                    portail_order: ligneParAnimateur.get(Number(item.extendedProps?.animateur_id)) ?? 999,
                                },
                            }));

                            const datesVisibles = [];
                            let dateVisible = parseLocalDate(fetchInfo.startStr);
                            const dateFinVisible = parseLocalDate(fetchInfo.endStr);
                            while (dateVisible < dateFinVisible) {
                                datesVisibles.push(formatDateLocal(dateVisible));
                                dateVisible.setDate(dateVisible.getDate() + 1);
                            }
                            joursParLigne.forEach((joursOccupes, ligne) => {
                                datesVisibles.forEach((date) => {
                                    if (joursOccupes.has(date)) return;
                                    espacesLignesPortail.push({
                                        id: `portail-spacer-${evenement.id}-${ligne}-${date}`,
                                        title: "",
                                        start: date,
                                        allDay: true,
                                        backgroundColor: "transparent",
                                        borderColor: "transparent",
                                        textColor: "transparent",
                                        classNames: ["animator-planning-row-spacer"],
                                        extendedProps: {
                                            type_affichage: "portail_spacer",
                                            portail_order: ligne,
                                        },
                                    });
                                });
                            });
                        }
                        const nombresEnfants = (effectifs || [])
                            .filter((item) => Number(item.groupe_id) === Number(evenement.id))
                            .map((item) => ({
                                id: `effectif-${evenement.id}-${item.date}`,
                                title: window.AnimatorPlanningPortal
                                    ? `${item.nombre} ENF`
                                    : `${item.nombre} enfant${Number(item.nombre) > 1 ? "s" : ""}`,
                                start: item.date,
                                allDay: true,
                                backgroundColor: "#fff2c7",
                                borderColor: "#e4bd55",
                                textColor: "#725510",
                                classNames: ["calendar-effectif-event"],
                                extendedProps: { type_affichage: "effectif_enfants" },
                            }));
                        successCallback([...nombresEnfants, ...affectations, ...espacesLignesPortail]);
                    })
                    .catch(failureCallback);
            },
            eventOrder: (a, b) => {
                const rangTypeA = a.extendedProps.type_affichage === "effectif_enfants" ? -1 : 0;
                const rangTypeB = b.extendedProps.type_affichage === "effectif_enfants" ? -1 : 0;
                if (rangTypeA !== rangTypeB) return rangTypeA - rangTypeB;
                if (window.AnimatorPlanningPortal) {
                    return Number(a.extendedProps?.portail_order ?? 999)
                        - Number(b.extendedProps?.portail_order ?? 999);
                }
                return 0;
            },
            eventOrderStrict: Boolean(window.AnimatorPlanningPortal),
            dayCellClassNames: (info) => evenementCouvreJour(evenement, info.date)
                ? []
                : ["home-evenement-hors-periode"],
            eventDidMount: (info) => {
                window.AnimatorPlanningPortal?.decorateCalendarEvent?.(info);
            },
            eventClick: (info) => {
                window.AnimatorPlanningPortal?.handleCalendarEventClick?.(info);
            },
            datesSet: (info) => {
                mettreAJourVisibilite(info);
                mettreAJourPeriodeVisible();
                PlanningData.applySortieMarkers(
                    info.view.calendar,
                    evenement.id,
                    info.startStr,
                    info.endStr,
                    window.AnimatorPlanningPortal?.markerOptions || {}
                );
            },
        });

        calendar.centrePlanning = centre;
        calendar.evenementPlanning = evenement;
        calendars.push(calendar);
        calendriersCentre.push(calendar);
        calendar.render();
    }

    async function chargerCalendriers()
    {
        if (!calendarsContainer) return;
        const numeroChargement = ++chargementCalendriers;
        try
        {
            const plage = PlanningData.weekRange(currentDate);
            const centresAvecEvenements = (await PlanningData.fetchCentresWithGroups(plage.debut, plage.fin)).map((centre) => ({
                ...centre,
                evenements: (centre.evenements || []).filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0),
            }));
            if (numeroChargement !== chargementCalendriers) return;

            calendars.forEach((calendar) => calendar.destroy());
            calendarsContainer.innerHTML = "";
            calendars.length = 0;

            if (!centresAvecEvenements.length)
            {
                // Une semaine sans affectation reste volontairement vide ; les
                // flèches permettent toujours de rejoindre une autre semaine.
                mettreAJourPeriodeVisible();
                return;
            }

            centresAvecEvenements.forEach((centre) =>
            {
                const card = document.createElement("article");
                card.classList.add("home-calendar-card", "calendar-site-card");
                card.dataset.centreId = centre.id;
                card.style.setProperty("--centre-color", centre.couleur || "#1f6f54");

                const toggle = document.createElement("button");
                toggle.type = "button";
                toggle.classList.add("home-calendar-toggle", "calendar-site-header");
                toggle.setAttribute("aria-expanded", "true");
                toggle.innerHTML = `
                    <span class="home-calendar-toggle-title calendar-site-name">${escapeHtml(centre.nom)}</span>
                    <span class="home-calendar-toggle-meta calendar-site-count">
                        ${centre.evenements.length} groupe${centre.evenements.length > 1 ? "s" : ""}
                    </span>
                    <span class="home-calendar-toggle-icon" aria-hidden="true">⌄</span>
                `;

                const collapse = document.createElement("div");
                collapse.classList.add("home-calendar-collapse");

                const collapseInner = document.createElement("div");
                collapseInner.classList.add("home-calendar-collapse-inner");

                const listeEvenements = document.createElement("div");
                listeEvenements.classList.add("home-event-calendars", "calendar-group-list");
                collapseInner.appendChild(listeEvenements);
                collapse.appendChild(collapseInner);
                const etatVide = document.createElement("p");
                etatVide.className = "calendar-site-empty";
                etatVide.textContent = "Aucun groupe ouvert cette semaine.";
                etatVide.hidden = centre.evenements.length > 0;

                card.appendChild(toggle);
                card.appendChild(collapse);
                card.appendChild(etatVide);
                calendarsContainer.appendChild(card);

                const calendriersCentre = [];
                // Le planning personnel reprend la même lecture que le planning
                // principal : un lieu contient un calendrier distinct par groupe.
                // Chaque calendrier charge aussi l'effectif enfants du jour.
                centre.evenements.forEach((evenement) =>
                {
                    creerCalendrierEvenement(centre, evenement, listeEvenements, calendriersCentre);
                });

                if (centresReplies.has(Number(centre.id)))
                {
                    card.classList.add("collapsed");
                    toggle.setAttribute("aria-expanded", "false");
                }

                toggle.addEventListener("click", () =>
                {
                    const ferme = card.classList.toggle("collapsed");
                    toggle.setAttribute("aria-expanded", String(!ferme));
                    if (ferme) centresReplies.add(Number(centre.id));
                    else centresReplies.delete(Number(centre.id));
                    sauvegarderCentresReplies();

                    if (!ferme)
                    {
                        window.setTimeout(() =>
                        {
                            calendriersCentre.forEach((calendar) => calendar.updateSize());
                        }, 220);
                    }
                });
            });

            const periodes = periodesOuvertes();
            if (calendars.length && periodes.length)
            {
                const dateDemandee = dateIsoLocale(currentDate);
                const demandee = periodes.find((periode) => periode.debut <= dateDemandee && periode.fin >= dateDemandee);
                const aujourdHui = dateIsoLocale(today);
                const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
                const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
                currentDate = new Date(`${(demandee || courante || prochaine || periodes[0]).debut}T12:00:00`);
                synchroniserCalendriers();
            }
            mettreAJourPeriodeVisible();
        }
        catch
        {
            message(calendarsContainer, "Impossible de charger le planning.");
            if (visiblePeriod) visiblePeriod.textContent = "indisponible";
        }
    }

    function carteDocument(doc)
    {
        const card = document.createElement("article");
        card.classList.add("home-document-card");

        card.innerHTML = `
            <div class="home-document-icon">${escapeHtml(DocumentUtils.typeCourt(doc.url))}</div>
            <h3 class="home-document-title" title="${escapeHtml(doc.titre)}">${escapeHtml(doc.titre)}</h3>
            <a class="btn btn-ghost" href="${escapeHtml(doc.url)}" target="_blank" rel="noopener" download>
                Télécharger
            </a>
        `;

        return card;
    }

    function chargerDocuments()
    {
        if (!documentsContainer) return;
        apiFetch("/api/documents/")
            .then((documents) =>
            {
                documentsContainer.innerHTML = "";

                if (!documents.length)
                {
                    message(documentsContainer, "Aucun document disponible.");
                    return;
                }

                const groupes = new Map();
                documents.forEach((doc) =>
                {
                    const cle = doc.permanent
                        ? "permanent"
                        : `${doc.periode_debut || ""}|${doc.periode_fin || ""}`;
                    if (!groupes.has(cle))
                    {
                        groupes.set(cle, {
                            titre: doc.permanent ? "Permanents" : doc.libelle_periode,
                            documents: [],
                        });
                    }
                    groupes.get(cle).documents.push(doc);
                });

                groupes.forEach((groupe) =>
                {
                    const section = document.createElement("section");
                    section.classList.add("home-document-group");
                    section.innerHTML = `<h3>${escapeHtml(groupe.titre)}</h3><div class="home-document-group-grid"></div>`;
                    const groupGrid = section.querySelector(".home-document-group-grid");
                    groupe.documents.forEach((doc) => groupGrid.appendChild(carteDocument(doc)));
                    documentsContainer.appendChild(section);
                });
            })
            .catch(() => message(documentsContainer, "Impossible de charger les documents."));
    }

    btnPrevWeek?.addEventListener("click", () => changerPeriode(-1));
    btnCurrentWeek?.addEventListener("click", retourPeriodeActuelle);
    btnNextWeek?.addEventListener("click", () => changerPeriode(1));

    const materialForm = document.querySelector("[data-material-form]");
    const materialDate = materialForm?.querySelector("[data-material-date]");
    const materialCentre = materialForm?.querySelector("[data-material-centre]");

    materialDate?.addEventListener("change", async () =>
    {
        if (!materialDate.value || !materialCentre) return;
        try
        {
            const url = `${materialForm.dataset.centreApi}?date=${encodeURIComponent(materialDate.value)}`;
            const data = await apiFetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (data.centre_id)
            {
                materialCentre.value = String(data.centre_id);
            }
        }
        catch (_) {}
    });

    chargerCalendriers();
    chargerDocuments();
});
