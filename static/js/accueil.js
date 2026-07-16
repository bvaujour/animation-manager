document.addEventListener("DOMContentLoaded", () =>
{
    const calendarsContainer = document.getElementById("home-calendars");
    const documentsContainer = document.getElementById("home-documents");
    const btnPrevWeek = document.getElementById("home-prev-week");
    const btnCurrentWeek = document.getElementById("home-current-week");
    const btnNextWeek = document.getElementById("home-next-week");
    const btnViewWeek = document.getElementById("home-view-week");
    const btnViewMonth = document.getElementById("home-view-month");
    const visiblePeriod = document.getElementById("home-visible-period");

    const calendars = [];
    const today = new Date();
    let currentDate = new Date(today);
    let currentView = "dayGridWeek";

    function message(container, texte)
    {
        container.innerHTML = `<p class="empty-note">${texte}</p>`;
    }


    function decalerDate(date, jours)
    {
        const resultat = new Date(date);
        resultat.setDate(resultat.getDate() + jours);
        return resultat;
    }

    function mettreAJourPeriodeVisible()
    {
        if (!visiblePeriod || !calendars.length) return;

        const title = calendars[0].view?.title || "";
        visiblePeriod.textContent = title || "période en cours";
    }

    function synchroniserCalendriers()
    {
        calendars.forEach((calendar) =>
        {
            calendar.changeView(currentView, currentDate);
        });

        requestAnimationFrame(mettreAJourPeriodeVisible);
    }

    function changerPeriode(delta)
    {
        const increment = currentView === "dayGridMonth"
            ? { months: delta }
            : { days: delta * 7 };

        calendars.forEach((calendar) =>
        {
            calendar.incrementDate(increment);
        });

        const activeDate = calendars[0]?.getDate();
        currentDate = activeDate ? new Date(activeDate) : decalerDate(currentDate, delta * 7);

        requestAnimationFrame(mettreAJourPeriodeVisible);
    }

    function retourPeriodeActuelle()
    {
        currentDate = new Date(today);
        synchroniserCalendriers();
    }

    function setVuePlanning(viewName)
    {
        currentView = viewName;

        btnViewWeek?.classList.toggle("active", currentView === "dayGridWeek");
        btnViewMonth?.classList.toggle("active", currentView === "dayGridMonth");

        synchroniserCalendriers();
    }

    function dateIsoLocale(date)
    {
        const annee = date.getFullYear();
        const mois = String(date.getMonth() + 1).padStart(2, "0");
        const jour = String(date.getDate()).padStart(2, "0");
        return `${annee}-${mois}-${jour}`;
    }

    function evenementCouvreJour(evenement, date)
    {
        const iso = dateIsoLocale(date);
        if (evenement.active === false) return false;
        if (evenement.debut && iso < evenement.debut) return false;
        if (evenement.fin && iso > evenement.fin) return false;
        const numeroJour = (date.getDay() + 6) % 7;
        const joursOuverts = Array.isArray(evenement.jours_ouverts)
            ? evenement.jours_ouverts.map(Number)
            : [0, 1, 2, 3, 4, 5];
        if (!joursOuverts.includes(numeroJour)) return false;
        return !(evenement.dates_exclues || []).includes(iso);
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
        if (!evenement.active) eventCard.classList.add("inactive");

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
            initialView: currentView,
            initialDate: currentDate,
            locale: "fr",
            firstDay: 1,
            hiddenDays: [0],
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
            const centresAvecEvenements = await Promise.all(centres.map(async (centre) => ({
                ...centre,
                evenements: await chargerJson(`/api/centres/${centre.id}/evenements/`),
            })));

            calendarsContainer.innerHTML = "";
            calendars.length = 0;

            if (!centresAvecEvenements.length)
            {
                message(calendarsContainer, "Aucun lieu configuré.");
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
                        ${centre.evenements.length} événement${centre.evenements.length > 1 ? "s" : ""}
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
                if (!centre.evenements.length)
                {
                    message(listeEvenements, "Aucun événement dans ce lieu.");
                }
                else
                {
                    centre.evenements.forEach((evenement) =>
                    {
                        creerCalendrierEvenement(centre, evenement, listeEvenements, calendriersCentre);
                    });
                }

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
    btnViewWeek?.addEventListener("click", () => setVuePlanning("dayGridWeek"));
    btnViewMonth?.addEventListener("click", () => setVuePlanning("dayGridMonth"));

    chargerCalendriers();
    chargerDocuments();
});
