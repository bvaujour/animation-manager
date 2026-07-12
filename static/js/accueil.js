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

    function chargerCalendriers()
    {
        fetch("/api/centres/")
            .then((response) => response.json())
            .then((centres) =>
            {
                calendarsContainer.innerHTML = "";
                calendars.length = 0;

                if (!centres.length)
                {
                    message(calendarsContainer, "Aucun centre configuré.");
                    return;
                }

                centres.forEach((centre) =>
                {
                    const card = document.createElement("article");
                    card.classList.add("home-calendar-card");

                    const toggle = document.createElement("button");
                    toggle.type = "button";
                    toggle.classList.add("home-calendar-toggle");
                    toggle.style.setProperty("--centre-color", centre.couleur || "#1f6f54");
                    toggle.setAttribute("aria-expanded", "true");
                    toggle.innerHTML = `
                        <span class="home-calendar-toggle-title">${escapeHtml(centre.nom)}</span>
                        <span class="home-calendar-toggle-icon" aria-hidden="true">⌄</span>
                    `;

                    const collapse = document.createElement("div");
                    collapse.classList.add("home-calendar-collapse");

                    const collapseInner = document.createElement("div");
                    collapseInner.classList.add("home-calendar-collapse-inner");

                    const calendarEl = document.createElement("div");
                    calendarEl.classList.add("home-calendar");

                    collapseInner.appendChild(calendarEl);
                    collapse.appendChild(collapseInner);
                    card.appendChild(toggle);
                    card.appendChild(collapse);
                    calendarsContainer.appendChild(card);

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
                        events: `/api/planning/?centre_id=${centre.id}`,
                        eventOrder: "title",
                    });

                    toggle.addEventListener("click", () =>
                    {
                        const ferme = card.classList.toggle("collapsed");
                        toggle.setAttribute("aria-expanded", String(!ferme));

                        if (!ferme)
                        {
                            window.setTimeout(() => calendar.updateSize(), 220);
                        }
                    });

                    calendars.push(calendar);
                    calendar.render();
                    mettreAJourPeriodeVisible();
                });
            })
            .catch(() => message(calendarsContainer, "Impossible de charger le planning."));
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
