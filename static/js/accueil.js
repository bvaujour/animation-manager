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

    function formatDate(dateIso)
    {
        return new Date(dateIso).toLocaleDateString("fr-FR");
    }

    function addDays(date, days)
    {
        const d = new Date(date);
        d.setDate(d.getDate() + days);
        return d;
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
        currentDate = activeDate ? new Date(activeDate) : addDays(currentDate, delta * 7);

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

                    const title = document.createElement("h3");
                    title.textContent = centre.nom;
                    title.style.setProperty("--centre-color", centre.couleur || "#1f6f54");

                    const calendarEl = document.createElement("div");
                    calendarEl.classList.add("home-calendar");

                    card.appendChild(title);
                    card.appendChild(calendarEl);
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

                    calendars.push(calendar);
                    calendar.render();
                    mettreAJourPeriodeVisible();
                });
            })
            .catch(() => message(calendarsContainer, "Impossible de charger le planning."));
    }

    function extensionDe(url)
    {
        return url.split("?")[0].split(".").pop().toLowerCase();
    }

    function iconeDocument(url)
    {
        const ext = extensionDe(url);

        if (ext === "pdf") return "PDF";
        if (["jpg", "jpeg", "png", "gif", "webp"].includes(ext)) return "IMG";
        if (["doc", "docx"].includes(ext)) return "DOC";
        if (["xls", "xlsx", "csv"].includes(ext)) return "XLS";

        return "FIC";
    }

    function carteDocument(doc)
    {
        const card = document.createElement("article");
        card.classList.add("home-document-card");

        const dateAjout = doc.date_ajout ? formatDate(doc.date_ajout) : "";

        card.innerHTML = `
            <div class="home-document-icon">${iconeDocument(doc.url)}</div>
            <div class="home-document-info">
                <h3>${doc.titre}</h3>
                <span>${dateAjout ? `Ajouté le ${dateAjout}` : "Document disponible"}</span>
            </div>
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

                documents.forEach((doc) => documentsContainer.appendChild(carteDocument(doc)));
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
