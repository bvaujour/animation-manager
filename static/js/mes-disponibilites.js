document.addEventListener("DOMContentLoaded", async () => {
    const card = document.querySelector("[data-animateur-id]");
    const animateurId = Number(card.dataset.animateurId);
    const root = document.getElementById("mes-disponibilites-root");
    const status = document.getElementById("disponibilites-status");
    const save = document.getElementById("enregistrer-disponibilites");

    function render(data) {
        const periodes = data.periodes || [];
        if (!periodes.length) {
            root.innerHTML = '<p class="empty-note">Aucune période n’est encore ouverte.</p>';
            save.disabled = true;
            return;
        }
        root.innerHTML = periodes.map((periode, index) => `<details class="availability-period" ${index === 0 ? "open" : ""}>
            <summary><strong>${escapeHtml(periode.nom)}</strong><span>${escapeHtml(periode.annee_scolaire)} · zone ${escapeHtml(periode.zone)}</span></summary>
            <div class="availability-days">${periode.jours.map((jour) => {
                const date = new Date(`${jour.date}T12:00:00`);
                const label = new Intl.DateTimeFormat("fr-FR", {weekday:"short", day:"numeric", month:"short"}).format(date);
                return `<label class="availability-day"><input type="checkbox" value="${jour.date}" ${jour.disponible ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
            }).join("")}</div>
        </details>`).join("");
    }

    async function load() {
        render(await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`));
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
