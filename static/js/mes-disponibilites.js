document.addEventListener("DOMContentLoaded", async () => {
    const card = document.querySelector("[data-animateur-id]");
    const animateurId = Number(card.dataset.animateurId);
    const root = document.getElementById("mes-disponibilites-root");
    const status = document.getElementById("disponibilites-status");
    const save = document.getElementById("enregistrer-disponibilites");

    function dateLocaleIso() {
        const maintenant = new Date();
        maintenant.setMinutes(maintenant.getMinutes() - maintenant.getTimezoneOffset());
        return maintenant.toISOString().slice(0, 10);
    }

    function render(data, placerSurSemaineCourante = false) {
        const periodes = [...(data.periodes || [])].sort((a, b) => a.debut.localeCompare(b.debut));
        if (!periodes.length) {
            root.innerHTML = '<p class="empty-note">Aucune période n’est encore ouverte.</p>';
            save.disabled = true;
            return;
        }
        const aujourdHui = dateLocaleIso();
        let periodeCible = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
        periodeCible ||= periodes.find((periode) => periode.debut > aujourdHui) || periodes[periodes.length - 1];

        root.innerHTML = periodes.map((periode) => {
            const estCourante = periode === periodeCible && periode.debut <= aujourdHui && periode.fin >= aujourdHui;
            return `<article class="availability-period availability-week-card${estCourante ? " is-current" : ""}" data-period-id="${escapeHtml(periode.id)}">
            <header><div><strong>${escapeHtml(periode.nom)}</strong><span>${escapeHtml(periode.annee_scolaire)} · zone ${escapeHtml(periode.zone)}</span></div>${estCourante ? '<b>Semaine en cours</b>' : ""}</header>
            <div class="availability-days">${periode.jours.map((jour) => {
                const date = new Date(`${jour.date}T12:00:00`);
                const label = new Intl.DateTimeFormat("fr-FR", {weekday:"short", day:"numeric", month:"short"}).format(date);
                return `<label class="availability-day"><input type="checkbox" value="${jour.date}" ${jour.disponible ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
            }).join("")}</div>
        </article>`;
        }).join("");

        if (placerSurSemaineCourante && periodeCible) {
            requestAnimationFrame(() => {
                [...root.querySelectorAll("[data-period-id]")]
                    .find((carte) => carte.dataset.periodId === periodeCible.id)
                    ?.scrollIntoView({block: "start"});
            });
        }
    }

    async function load() {
        render(await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`), true);
    }

    save.addEventListener("click", async () => {
        save.disabled = true; status.textContent = "Enregistrement…";
        try {
            const jours_disponibles = [...root.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
            const data = await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`, {
                method: "PUT",
                body: JSON.stringify({ jours_disponibles }),
            });
            status.textContent = "Tes disponibilités ont bien été enregistrées.";
            render(data);
        } catch (error) { status.textContent = erreurMessage(error, "Enregistrement impossible."); }
        finally { save.disabled = false; }
    });

    try { await load(); } catch (error) { status.textContent = erreurMessage(error, "Chargement impossible."); }
});
