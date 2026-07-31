document.addEventListener("DOMContentLoaded", async () => {
    const card = document.querySelector("[data-animateur-id]");
    if (!card) return;

    const animateurId = Number(card.dataset.animateurId);
    const root = document.getElementById("mes-disponibilites-root");
    const status = document.getElementById("disponibilites-status");
    const save = document.getElementById("enregistrer-disponibilites");

    function dateLocaleIso() {
        const maintenant = new Date();
        maintenant.setMinutes(maintenant.getMinutes() - maintenant.getTimezoneOffset());
        return maintenant.toISOString().slice(0, 10);
    }

    function libelleJour(dateIso) {
        return new Intl.DateTimeFormat("fr-FR", {
            weekday: "short",
            day: "numeric",
            month: "short",
        }).format(new Date(`${dateIso}T12:00:00`));
    }

    function synchroniserSemaine(carte) {
        const toggle = carte.querySelector(".availability-week-toggle");
        const jours = [...carte.querySelectorAll(".availability-day-input")];
        const selectionnes = jours.filter((input) => input.checked).length;

        toggle.checked = jours.length > 0 && selectionnes === jours.length;
        toggle.indeterminate = selectionnes > 0 && selectionnes < jours.length;
        carte.classList.toggle("is-selected", selectionnes > 0);
        carte.querySelector(".availability-days").hidden = selectionnes === 0;
    }

    function render(data, placerSurSemaineCourante = false) {
        const aujourdHui = dateLocaleIso();
        // Une semaine est conservée tant qu'elle n'est pas entièrement passée.
        const periodes = [...(data.periodes || [])]
            .filter((periode) => periode.fin >= aujourdHui)
            .sort((a, b) => a.debut.localeCompare(b.debut));

        if (!periodes.length) {
            root.innerHTML = '<p class="empty-note">Aucune semaine à venir n’est encore ouverte.</p>';
            save.disabled = true;
            return;
        }
        save.disabled = false;

        let periodeCible = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
        periodeCible ||= periodes[0];

        root.innerHTML = periodes.map((periode) => {
            const joursSelectionnes = periode.jours.filter((jour) => jour.disponible).length;
            const selectionComplete = joursSelectionnes === periode.jours.length && periode.jours.length > 0;
            const selectionPartielle = joursSelectionnes > 0 && !selectionComplete;
            const estCourante = periode === periodeCible && periode.debut <= aujourdHui && periode.fin >= aujourdHui;
            const detailVisible = joursSelectionnes > 0;

            return `<article class="availability-period availability-week-card availability-week-card--selectable${estCourante ? " is-current" : ""}${detailVisible ? " is-selected" : ""}" data-period-id="${escapeHtml(periode.id)}">
                <label class="availability-week-summary">
                    <input class="availability-week-toggle" type="checkbox" ${selectionComplete ? "checked" : ""} data-indeterminate="${selectionPartielle ? "true" : "false"}">
                    <span><strong>${escapeHtml(periode.nom)}</strong>${estCourante ? "<small>Semaine en cours</small>" : ""}</span>
                </label>
                <div class="availability-days" ${detailVisible ? "" : "hidden"}>
                    ${periode.jours.map((jour) => `<label class="availability-day">
                        <input class="availability-day-input" type="checkbox" value="${jour.date}" ${jour.disponible ? "checked" : ""}>
                        <span>${escapeHtml(libelleJour(jour.date))}</span>
                    </label>`).join("")}
                </div>
            </article>`;
        }).join("");

        root.querySelectorAll('.availability-week-toggle[data-indeterminate="true"]').forEach((input) => {
            input.indeterminate = true;
        });

        if (placerSurSemaineCourante && periodeCible) {
            requestAnimationFrame(() => {
                root.querySelector(`[data-period-id="${CSS.escape(String(periodeCible.id))}"]`)
                    ?.scrollIntoView({block: "nearest"});
            });
        }
    }

    root.addEventListener("change", (event) => {
        const carte = event.target.closest(".availability-week-card");
        if (!carte) return;

        if (event.target.matches(".availability-week-toggle")) {
            const coche = event.target.checked;
            carte.querySelectorAll(".availability-day-input").forEach((input) => {
                input.checked = coche;
            });
        }
        synchroniserSemaine(carte);
    });

    async function load() {
        render(await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`), true);
    }

    save.addEventListener("click", async () => {
        save.disabled = true;
        status.textContent = "Enregistrement…";
        try {
            const jours_disponibles = [...root.querySelectorAll(".availability-day-input:checked")]
                .map((input) => input.value);
            const data = await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`, {
                method: "PUT",
                body: JSON.stringify({jours_disponibles}),
            });
            status.textContent = "Tes disponibilités ont bien été enregistrées.";
            render(data);
        } catch (error) {
            status.textContent = erreurMessage(error, "Enregistrement impossible.");
        } finally {
            save.disabled = false;
        }
    });

    try {
        await load();
    } catch (error) {
        status.textContent = erreurMessage(error, "Chargement impossible.");
    }
});
