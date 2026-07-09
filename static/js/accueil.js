document.addEventListener("DOMContentLoaded", () =>
{
    const calendarsContainer = document.getElementById("home-calendars");
    const documentsContainer = document.getElementById("home-documents");

    function message(container, texte)
    {
        container.innerHTML = `<p class="empty-note">${texte}</p>`;
    }

    function formatDate(dateIso)
    {
        return new Date(dateIso).toLocaleDateString("fr-FR");
    }

    function chargerCalendriers()
    {
        fetch("/api/centres/")
            .then((response) => response.json())
            .then((centres) =>
            {
                calendarsContainer.innerHTML = "";

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

                    const calendarEl = document.createElement("div");
                    calendarEl.classList.add("home-calendar");

                    card.appendChild(title);
                    card.appendChild(calendarEl);
                    calendarsContainer.appendChild(card);

                    const calendar = new FullCalendar.Calendar(calendarEl,
                    {
                        initialView: "dayGridWeek",
                        locale: "fr",
                        firstDay: 1,
                        weekends: false,
                        height: "auto",
                        fixedWeekCount: false,
                        dayMaxEventRows: 3,
                        headerToolbar: false,
                        footerToolbar: false,
                        editable: false,
                        droppable: false,
                        selectable: false,
                        events: `/api/planning/?centre_id=${centre.id}`,
                    });

                    calendar.render();
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

    chargerCalendriers();
    chargerDocuments();
});
