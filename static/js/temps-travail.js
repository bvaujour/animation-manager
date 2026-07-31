document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("worktime-panel");
    const pickerRoot = document.getElementById("worktime-periods");
    if (!panel || !pickerRoot) return;

    const picker = WeekPicker.get(pickerRoot);
    const emptyRoot = document.getElementById("worktime-empty");
    const contentRoot = document.getElementById("worktime-content");
    const meetingsRoot = document.getElementById("worktime-meetings-list");
    const preparationRoot = document.getElementById("worktime-preparation-table");
    const addMeetingButton = document.getElementById("worktime-add-meeting");
    const preparationForm = document.getElementById("worktime-preparation-form");
    const preparationSearch = document.getElementById("worktime-preparation-search");
    const preparationAnimatorId = document.getElementById("worktime-preparation-animator-id");
    const preparationSuggestions = document.getElementById("worktime-preparation-suggestions");
    const preparationSubmit = document.getElementById("worktime-preparation-submit");
    const preparationCancel = document.getElementById("worktime-preparation-cancel");
    const preparationError = document.getElementById("worktime-preparation-error");
    const modal = document.getElementById("worktime-meeting-modal");
    const form = document.getElementById("worktime-meeting-form");
    const participantsRoot = document.getElementById("worktime-participants");
    const meetingError = document.getElementById("worktime-meeting-error");
    const meetingDateInfo = document.getElementById("worktime-meeting-date-info");
    let selectedIds = [];
    let data = null;
    let editingMeeting = null;
    let editingPreparationId = null;
    let conflictIds = new Set();
    let conflictRequest = 0;

    function formatDate(value) {
        return formatDateLocale(value, {
            weekday: "long", day: "numeric", month: "long", year: "numeric",
        });
    }

    function selectedQuery() {
        return selectedIds.join(",");
    }

    function setLoading() {
        emptyRoot.hidden = false;
        contentRoot.hidden = true;
        emptyRoot.textContent = "Chargement du temps de travail…";
    }

    function renderMeetings() {
        const meetings = data?.reunions || [];
        meetingsRoot.innerHTML = meetings.length ? meetings.map((meeting) => {
            const doubles = meeting.participants.filter((item) => item.autoriser_double_comptage).length;
            return `
                <article class="worktime-meeting-row" data-meeting-id="${meeting.id}">
                    <div><strong>${escapeHtml(meeting.intitule)}</strong><small>${escapeHtml(formatDate(meeting.date))} · ${meeting.participants.length} participant${meeting.participants.length > 1 ? "s" : ""}${doubles ? ` · ${doubles} double comptage explicite` : ""}</small>${meeting.remarque ? `<small>${escapeHtml(meeting.remarque)}</small>` : ""}</div>
                    <div class="worktime-meeting-actions"><button class="btn btn-secondary btn-small" type="button" data-edit-meeting>Modifier</button><button class="btn btn-danger-ghost btn-small" type="button" data-delete-meeting>Supprimer</button></div>
                </article>`;
        }).join("") : '<p class="empty-note">Aucune réunion enregistrée pour cette période.</p>';
    }

    function renderPreparation() {
        const animateurs = data?.animateurs || [];
        if (!animateurs.length) {
            preparationRoot.innerHTML = '<p class="empty-note">Aucun animateur n’est affecté pendant cette période.</p>';
            preparationForm.hidden = true;
            return;
        }
        preparationForm.hidden = false;
        const entries = animateurs.filter((animateur) => data.preparation?.[animateur.id]);
        if (!entries.length) {
            preparationRoot.innerHTML = '<p class="empty-note">Aucune journée de télétravail ou préparation enregistrée.</p>';
            return;
        }
        preparationRoot.innerHTML = `
            <table class="worktime-table">
                <thead><tr><th>Animateur</th><th>Nombre de jours</th><th>Remarque</th><th>Actions</th></tr></thead>
                <tbody>${entries.map((animateur) => {
                    const attribution = data.preparation[animateur.id];
                    return `<tr data-preparation-id="${animateur.id}"><td><strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong></td><td>${escapeHtml(attribution.nombre_jours)}</td><td>${escapeHtml(attribution.remarque || "—")}</td><td><div class="worktime-preparation-actions"><button class="btn btn-secondary btn-small" type="button" data-edit-preparation>Modifier</button><button class="btn btn-danger-ghost btn-small" type="button" data-delete-preparation>Supprimer</button></div></td></tr>`;
                }).join("")}</tbody>
            </table>`;
    }

    function animatorLabel(animateur) {
        return `${animateur.prenom} ${animateur.nom}`;
    }

    function normalized(value) {
        return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    }

    function closePreparationSuggestions() {
        preparationSuggestions.hidden = true;
        preparationSearch.setAttribute("aria-expanded", "false");
    }

    function renderPreparationSuggestions() {
        const query = normalized(preparationSearch.value);
        const choices = (data?.animateurs || []).filter((animateur) => normalized(animatorLabel(animateur)).includes(query));
        preparationSuggestions.innerHTML = choices.length
            ? choices.map((animateur) => `<button class="worktime-preparation-suggestion" type="button" role="option" data-select-preparation="${animateur.id}">${escapeHtml(animatorLabel(animateur))}${data.preparation?.[animateur.id] ? " · déjà enregistré" : ""}</button>`).join("")
            : '<span class="empty-note">Aucun animateur trouvé.</span>';
        preparationSuggestions.hidden = false;
        preparationSearch.setAttribute("aria-expanded", "true");
    }

    function resetPreparationForm() {
        editingPreparationId = null;
        preparationForm.reset();
        preparationAnimatorId.value = "";
        preparationSubmit.textContent = "Ajouter";
        preparationCancel.hidden = true;
        preparationError.hidden = true;
        closePreparationSuggestions();
    }

    function editPreparation(animateurId) {
        const animateur = (data?.animateurs || []).find((item) => Number(item.id) === Number(animateurId));
        const attribution = data?.preparation?.[animateurId];
        if (!animateur || !attribution) return;
        editingPreparationId = Number(animateurId);
        preparationAnimatorId.value = animateur.id;
        preparationSearch.value = animatorLabel(animateur);
        preparationForm.elements.nombre_jours.value = attribution.nombre_jours;
        preparationForm.elements.remarque.value = attribution.remarque || "";
        preparationSubmit.textContent = "Enregistrer";
        preparationCancel.hidden = false;
        closePreparationSuggestions();
        preparationForm.elements.nombre_jours.focus();
    }

    async function savePreparations(nextPreparation) {
        const attributions = Object.entries(nextPreparation).map(([animateurId, attribution]) => ({
            animateur_id: Number(animateurId),
            nombre_jours: attribution.nombre_jours,
            remarque: attribution.remarque || "",
        }));
        data = await apiFetch("/api/temps-travail/preparation/", {
            method: "PUT",
            body: JSON.stringify({ periode_ids: selectedIds, attributions }),
        });
        resetPreparationForm();
        render();
    }

    function render() {
        emptyRoot.hidden = true;
        contentRoot.hidden = false;
        addMeetingButton.disabled = !(data?.animateurs || []).length;
        renderMeetings();
        renderPreparation();
    }

    async function load() {
        if (!selectedIds.length) {
            data = null;
            emptyRoot.hidden = false;
            contentRoot.hidden = true;
            emptyRoot.textContent = "Choisissez une ou plusieurs semaines.";
            return;
        }
        setLoading();
        try {
            data = await apiFetch(`/api/temps-travail/?periode_ids=${selectedQuery()}`);
            resetPreparationForm();
            render();
        } catch (error) {
            emptyRoot.textContent = erreurMessage(error, "Le temps de travail n’a pas pu être chargé.");
            afficherToast(emptyRoot.textContent, true);
        }
    }

    function updateMeetingConflicts() {
        participantsRoot.querySelectorAll("[data-participant-id]").forEach((row) => {
            const conflict = conflictIds.has(Number(row.dataset.participantId));
            row.classList.toggle("has-conflict", conflict);
            const override = row.querySelector('[name="double_comptage"]');
            if (!conflict) override.checked = false;
        });
    }

    async function refreshMeetingDateStatus() {
        const date = form.elements.date.value;
        const requestNumber = ++conflictRequest;
        meetingDateInfo.hidden = true;
        if (!date || !selectedIds.length) {
            conflictIds = new Set();
            updateMeetingConflicts();
            return;
        }
        try {
            const result = await apiFetch(`/api/temps-travail/conflits-reunion/?periode_ids=${selectedQuery()}&date=${encodeURIComponent(date)}`);
            if (requestNumber !== conflictRequest) return;
            conflictIds = new Set((result.animateur_ids || []).map(Number));
            if (result.hors_periode) {
                const periodeLabel = (result.periodes || []).join(" · ");
                meetingDateInfo.textContent = `Cette réunion a lieu en dehors des dates de la période, mais elle sera comptabilisée dans ${periodeLabel}.`;
                meetingDateInfo.hidden = false;
            }
            updateMeetingConflicts();
        } catch (error) {
            if (requestNumber !== conflictRequest) return;
            conflictIds = new Set();
            updateMeetingConflicts();
        }
    }

    function renderParticipants(meeting = null) {
        const current = new Map((meeting?.participants || []).map((item) => [Number(item.animateur_id), item]));
        participantsRoot.innerHTML = (data.animateurs || []).map((animateur) => {
            const participation = current.get(Number(animateur.id));
            const checked = meeting ? Boolean(participation) : true;
            return `
                <div class="worktime-participant" data-participant-id="${animateur.id}">
                    <label class="worktime-participant-main"><input name="participant" type="checkbox" value="${animateur.id}" ${checked ? "checked" : ""}><strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong></label>
                    <label class="worktime-participant-override"><input name="double_comptage" type="checkbox" value="${animateur.id}" ${participation?.autoriser_double_comptage ? "checked" : ""}> Compter une journée supplémentaire malgré l’affectation</label>
                </div>`;
        }).join("");
        conflictIds = new Set(
            (meeting?.participants || []).filter((item) => item.deja_affecte).map((item) => Number(item.animateur_id))
        );
        updateMeetingConflicts();
    }

    function openMeeting(meeting = null) {
        if (!data?.animateurs?.length) return;
        editingMeeting = meeting;
        form.reset();
        meetingError.hidden = true;
        document.getElementById("worktime-meeting-title").textContent = meeting ? "Modifier la réunion" : "Ajouter une réunion";
        form.elements.intitule.value = meeting?.intitule || "";
        form.elements.date.value = meeting?.date || data.periodes[0]?.debut || "";
        form.elements.remarque.value = meeting?.remarque || "";
        renderParticipants(meeting);
        ouvrirModal(modal);
        refreshMeetingDateStatus();
        form.elements.intitule.focus();
    }

    form.elements.date.addEventListener("change", refreshMeetingDateStatus);
    participantsRoot.addEventListener("change", (event) => {
        if (event.target.name !== "participant") return;
        const row = event.target.closest("[data-participant-id]");
        if (!event.target.checked) row.querySelector('[name="double_comptage"]').checked = false;
    });
    document.getElementById("worktime-toggle-participants").addEventListener("click", () => {
        const choices = [...participantsRoot.querySelectorAll('[name="participant"]')];
        const shouldCheck = choices.some((item) => !item.checked);
        choices.forEach((item) => { item.checked = shouldCheck; });
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const participantIds = [...participantsRoot.querySelectorAll('[name="participant"]:checked')].map((item) => Number(item.value));
        const doubleIds = [...participantsRoot.querySelectorAll('.has-conflict [name="double_comptage"]:checked')]
            .filter((item) => participantIds.includes(Number(item.value)))
            .map((item) => Number(item.value));
        const payload = {
            periode_ids: selectedIds,
            intitule: form.elements.intitule.value,
            date: form.elements.date.value,
            remarque: form.elements.remarque.value,
            participant_ids: participantIds,
            double_comptage_ids: doubleIds,
        };
        meetingError.hidden = true;
        try {
            await apiFetch(editingMeeting ? `/api/temps-travail/reunions/${editingMeeting.id}/` : "/api/temps-travail/reunions/", {
                method: editingMeeting ? "PATCH" : "POST",
                body: JSON.stringify(payload),
            });
            fermerModal(modal);
            await load();
            afficherToast(editingMeeting ? "Réunion modifiée." : "Réunion ajoutée.");
        } catch (error) {
            meetingError.textContent = erreurMessage(error, "La réunion n’a pas pu être enregistrée.");
            meetingError.hidden = false;
        }
    });

    meetingsRoot.addEventListener("click", async (event) => {
        const row = event.target.closest("[data-meeting-id]");
        if (!row) return;
        const meeting = data.reunions.find((item) => Number(item.id) === Number(row.dataset.meetingId));
        if (event.target.closest("[data-edit-meeting]")) openMeeting(meeting);
        if (event.target.closest("[data-delete-meeting]")) {
            if (!confirm(`Supprimer la réunion « ${meeting.intitule} » ?`)) return;
            try {
                await apiFetch(`/api/temps-travail/reunions/${meeting.id}/`, { method: "DELETE" });
                await load();
                afficherToast("Réunion supprimée.");
            } catch (error) {
                afficherToast(erreurMessage(error, "La réunion n’a pas pu être supprimée."), true);
            }
        }
    });

    preparationSearch.addEventListener("input", () => {
        preparationAnimatorId.value = "";
        renderPreparationSuggestions();
    });
    preparationSearch.addEventListener("focus", renderPreparationSuggestions);
    preparationSuggestions.addEventListener("click", (event) => {
        const choice = event.target.closest("[data-select-preparation]");
        if (!choice) return;
        const animateurId = Number(choice.dataset.selectPreparation);
        if (data.preparation?.[animateurId]) {
            editPreparation(animateurId);
            return;
        }
        const animateur = data.animateurs.find((item) => Number(item.id) === animateurId);
        preparationAnimatorId.value = animateur.id;
        preparationSearch.value = animatorLabel(animateur);
        closePreparationSuggestions();
        preparationForm.elements.nombre_jours.focus();
    });
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".worktime-preparation-animator")) closePreparationSuggestions();
    });
    preparationCancel.addEventListener("click", resetPreparationForm);

    preparationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const animateurId = Number(preparationAnimatorId.value);
        const nombreJours = Number(preparationForm.elements.nombre_jours.value);
        preparationError.hidden = true;
        if (!animateurId || !(data.animateurs || []).some((item) => Number(item.id) === animateurId)) {
            preparationError.textContent = "Sélectionnez un animateur dans la liste.";
            preparationError.hidden = false;
            return;
        }
        if (!(nombreJours > 0)) {
            preparationError.textContent = "Le nombre de jours doit être supérieur à zéro.";
            preparationError.hidden = false;
            return;
        }
        if (data.preparation?.[animateurId] && editingPreparationId !== animateurId) {
            editPreparation(animateurId);
            afficherToast("Une entrée existe déjà : elle a été ouverte pour modification.");
            return;
        }
        preparationSubmit.disabled = true;
        const wasEditing = editingPreparationId !== null;
        try {
            await savePreparations({
                ...(data.preparation || {}),
                [animateurId]: {
                    nombre_jours: preparationForm.elements.nombre_jours.value,
                    remarque: preparationForm.elements.remarque.value,
                },
            });
            afficherToast(wasEditing ? "Entrée modifiée." : "Entrée ajoutée.");
        } catch (error) {
            preparationError.textContent = erreurMessage(error, "L’entrée n’a pas pu être enregistrée.");
            preparationError.hidden = false;
        } finally {
            preparationSubmit.disabled = false;
        }
    });

    preparationRoot.addEventListener("click", async (event) => {
        const row = event.target.closest("[data-preparation-id]");
        if (!row) return;
        const animateurId = Number(row.dataset.preparationId);
        if (event.target.closest("[data-edit-preparation]")) editPreparation(animateurId);
        if (event.target.closest("[data-delete-preparation]")) {
            const animateur = data.animateurs.find((item) => Number(item.id) === animateurId);
            if (!confirm(`Supprimer les journées de ${animatorLabel(animateur)} ?`)) return;
            const nextPreparation = { ...(data.preparation || {}) };
            delete nextPreparation[animateurId];
            try {
                await savePreparations(nextPreparation);
                afficherToast("Entrée supprimée.");
            } catch (error) {
                afficherToast(erreurMessage(error, "L’entrée n’a pas pu être supprimée."), true);
            }
        }
    });

    addMeetingButton.addEventListener("click", () => openMeeting());
    modal.querySelectorAll("[data-modal-close]").forEach((button) => button.addEventListener("click", () => fermerModal(modal)));
    pickerRoot.addEventListener("week-picker:ready", (event) => {
        selectedIds = event.detail.picker.getSelectedIds();
        load();
    });
    pickerRoot.addEventListener("week-picker:change", (event) => {
        selectedIds = event.detail.ids;
        load();
    });
});
