document.addEventListener("DOMContentLoaded", () =>
{
    const calendarsContainer = document.getElementById("home-calendars");
    const documentsContainer = document.getElementById("home-documents");
    const btnPrevWeek = document.getElementById("home-prev-week");
    const btnCurrentWeek = document.getElementById("home-current-week");
    const btnNextWeek = document.getElementById("home-next-week");
    const visiblePeriod = document.getElementById("home-visible-period");

    const calendars = [];
    const today = new Date();
    let currentDate = new Date(today);

    function message(container, texte)
    {
        container.innerHTML = `<p class="empty-note">${texte}</p>`;
    }



    function parseDateLocale(dateStr)
    {
        const [annee, mois, jour] = dateStr.split("-").map(Number);
        return new Date(annee, mois - 1, jour, 12, 0, 0);
    }

    function periodePourDate(dateStr)
    {
        return periodesOuvertes().find((periode) => periode.debut <= dateStr && periode.fin >= dateStr) || null;
    }

    function mettreAJourPeriodeVisible()
    {
        if (!visiblePeriod) return;
        const periode = periodePourDate(dateIsoLocale(currentDate));
        visiblePeriod.textContent = periode
            ? libellePeriodeAvecAnnee(periode)
            : "Aucune période ouverte";
    }

    function synchroniserCalendriers()
    {
        calendars.forEach((calendar) => calendar.gotoDate(currentDate));
        requestAnimationFrame(mettreAJourPeriodeVisible);
    }

    function changerPeriode(delta)
    {
        const periodes = periodesOuvertes();
        if (!periodes.length) return;
        const dateCourante = dateIsoLocale(currentDate);
        const cible = delta > 0
            ? periodes.find((periode) => periode.debut > dateCourante)
            : [...periodes].reverse().find((periode) => periode.debut < dateCourante);
        if (!cible) return;
        currentDate = new Date(`${cible.debut}T12:00:00`);
        synchroniserCalendriers();
    }

    function retourPeriodeActuelle()
    {
        const periodes = periodesOuvertes();
        const aujourdHui = dateIsoLocale(today);
        const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
        const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
        const cible = courante || prochaine || periodes.at(-1);
        if (!cible) return;
        currentDate = new Date(`${cible.debut}T12:00:00`);
        synchroniserCalendriers();
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
        if (!periodes.some((periode) => iso >= periode.debut && iso <= (periode.fin_ouverture || periode.fin))) return false;
        const numeroJour = (date.getDay() + 6) % 7;
        const joursOuverts = Array.isArray(groupe.jours_ouverts)
            ? groupe.jours_ouverts.map(Number)
            : [0, 1, 2, 3, 4, 5];
        if (!joursOuverts.includes(numeroJour)) return false;
        return !(groupe.dates_exclues || []).includes(iso)
            && !(groupe.dates_feriees_fermees || []).includes(iso);
    }

    function joursCachesFullCalendar(groupe)
    {
        const ouverts = new Set((groupe.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number));
        return [0, 1, 2, 3, 4, 5, 6].filter((jourJs) => !ouverts.has((jourJs + 6) % 7));
    }

    function groupeChevauchePlage(groupe, debutStr, finExclusiveStr)
    {
        return (groupe.periodes || []).some((periode) => periode.debut < finExclusiveStr && (periode.fin_ouverture || periode.fin) >= debutStr);
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
            card.hidden = groupes.length === 0 || groupes.every((groupe) => groupe.hidden);
        });
    }

    async function chargerJson(url)
    {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Erreur HTTP ${response.status}`);
        return response.json();
    }

    function creerCalendrierEvenement(centre, evenement, liste, calendriersCentre)
    {
        const eventCard = document.createElement("article");
        eventCard.classList.add("home-event-calendar-card");
        eventCard.dataset.groupeId = evenement.id;

        const header = document.createElement("header");
        header.classList.add("home-event-calendar-header");
        header.innerHTML = `
            <h3>${escapeHtml(evenement.nom)}</h3>
            <span>Objectif ${escapeHtml(evenement.effectif_cible)}</span>
        `;

        const calendarEl = document.createElement("div");
        calendarEl.classList.add("home-calendar");

        eventCard.appendChild(header);
        eventCard.appendChild(calendarEl);
        liste.appendChild(eventCard);

        const calendar = new FullCalendar.Calendar(calendarEl,
        {
            initialView: "dayGridWeek",
            initialDate: currentDate,
            locale: "fr",
            firstDay: 1,
            hiddenDays: joursCachesFullCalendar(evenement),
            height: "auto",
            fixedWeekCount: false,
            dayMaxEvents: false,
            dayMaxEventRows: false,
            headerToolbar: false,
            footerToolbar: false,
            editable: false,
            droppable: false,
            selectable: false,
            events: `/api/planning/?evenement_id=${evenement.id}`,
            eventOrder: "title",
            dayCellClassNames: (info) => evenementCouvreJour(evenement, info.date)
                ? []
                : ["home-evenement-hors-periode"],
            datesSet: (info) => {
                mettreAJourVisibilite(info);
                mettreAJourPeriodeVisible();
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
        try
        {
            const centres = await chargerJson("/api/centres/");
            const centresAvecEvenements = (await Promise.all(centres.map(async (centre) => ({
                ...centre,
                evenements: (await chargerJson(`/api/centres/${centre.id}/groupes/`))
                    .filter((groupe) => (groupe.periodes || []).length > 0),
            })))).filter((centre) => centre.evenements.length > 0);

            calendarsContainer.innerHTML = "";
            calendars.length = 0;

            if (!centresAvecEvenements.length)
            {
                message(calendarsContainer, "Aucun groupe n’a encore de période ouverte.");
                if (visiblePeriod) visiblePeriod.textContent = "aucun planning";
                return;
            }

            centresAvecEvenements.forEach((centre) =>
            {
                const card = document.createElement("article");
                card.classList.add("home-calendar-card");
                card.style.setProperty("--centre-color", centre.couleur || "#1f6f54");

                const toggle = document.createElement("button");
                toggle.type = "button";
                toggle.classList.add("home-calendar-toggle");
                toggle.setAttribute("aria-expanded", "true");
                toggle.innerHTML = `
                    <span class="home-calendar-toggle-title">${escapeHtml(centre.nom)}</span>
                    <span class="home-calendar-toggle-meta">
                        ${centre.evenements.length} groupe${centre.evenements.length > 1 ? "s" : ""}
                    </span>
                    <span class="home-calendar-toggle-icon" aria-hidden="true">⌄</span>
                `;

                const collapse = document.createElement("div");
                collapse.classList.add("home-calendar-collapse");

                const collapseInner = document.createElement("div");
                collapseInner.classList.add("home-calendar-collapse-inner");

                const listeEvenements = document.createElement("div");
                listeEvenements.classList.add("home-event-calendars");
                collapseInner.appendChild(listeEvenements);
                collapse.appendChild(collapseInner);
                card.appendChild(toggle);
                card.appendChild(collapse);
                calendarsContainer.appendChild(card);

                const calendriersCentre = [];
                centre.evenements.forEach((evenement) =>
                {
                    creerCalendrierEvenement(centre, evenement, listeEvenements, calendriersCentre);
                });

                toggle.addEventListener("click", () =>
                {
                    const ferme = card.classList.toggle("collapsed");
                    toggle.setAttribute("aria-expanded", String(!ferme));

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
                const aujourdHui = dateIsoLocale(today);
                const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
                const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
                currentDate = new Date(`${(courante || prochaine || periodes[0]).debut}T12:00:00`);
                synchroniserCalendriers();
            }
            mettreAJourPeriodeVisible();
        }
        catch (_erreur)
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
            <div class="home-document-icon">${DocumentUtils.typeCourt(doc.url)}</div>
            <h3 class="home-document-title" title="${doc.titre}">${doc.titre}</h3>
            <a class="btn btn-ghost" href="${doc.url}" target="_blank" rel="noopener" download>
                Télécharger
            </a>
        `;

        return card;
    }

    function chargerDocuments()
    {
        fetch("/api/documents/")
            .then((response) => response.json())
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
                    section.innerHTML = `<h3>${groupe.titre}</h3><div class="home-document-group-grid"></div>`;
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

    chargerCalendriers();
    chargerDocuments();
});
