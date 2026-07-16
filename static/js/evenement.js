document.addEventListener("DOMContentLoaded", () => {
    const listEl = document.getElementById("evenement-list");
    const detailEl = document.getElementById("evenement-detail");
    const searchEl = document.getElementById("evenement-search");
    const addBtn = document.getElementById("evenement-add");

    let animateurs = [];
    let qualifications = [];
    let centres = [];
    let selectedId = null;

    function fullName(a) { return `${a.prenom || ""} ${a.nom || ""}`.trim(); }
    function centreCodes(a) {
        return (a.centres_autorises || []).map((c) => c.code).join(" · ");
    }

    function setStatus(message = "", error = false) {
        const el = detailEl.querySelector(".fiche-status");
        if (!el) return;
        el.textContent = message;
        el.className = `fiche-status ${message ? (error ? "error" : "success") : ""}`;
    }

    function renderList() {
        const query = searchEl.value.trim().toLocaleLowerCase("fr");
        const filtered = animateurs.filter((a) => fullName(a).toLocaleLowerCase("fr").includes(query));
        listEl.innerHTML = "";

        if (!filtered.length) {
            listEl.innerHTML = '<p class="empty-note">Aucun animateur trouvé.</p>';
            return;
        }

        filtered.forEach((a) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `evenement-list-item ${a.id === selectedId ? "active" : ""}`;
            btn.style.setProperty("--anim-color", a.couleur || "#94a3b8");
            btn.innerHTML = `
                <span class="evenement-list-color"></span>
                <span>
                    <span class="evenement-list-name">${escapeHtml(fullName(a))}</span>
                    <span class="evenement-list-meta">${escapeHtml(centreCodes(a) || "Aucun centre renseigné")}</span>
                </span>`;
            btn.addEventListener("click", () => selectAnimateur(a.id));
            listEl.appendChild(btn);
        });
    }

    function qualificationsHtml(checked = []) {
        return FormOptionsUtils.qualifications(qualifications, checked);
    }

    function centresHtml(prefere = null, secondaires = [], group = "fiche-centre-prefere") {
        return FormOptionsUtils.centresHierarchises(centres, prefere, secondaires, group);
    }

    function optionsEvenementPreferee(centreId, evenementId = null) {
        const centre = centres.find((item) => Number(item.id) === Number(centreId));
        const evenements = (centre?.evenements || []).filter((evenement) => evenement.active);
        const selected = Number(evenementId) || null;

        if (!centreId) {
            return '<option value="">Choisis d’abord un centre préféré</option>';
        }
        if (!evenements.length) {
            return '<option value="">Aucune événement active dans ce centre</option>';
        }

        return [
            '<option value="">Aucune préférence d’événement</option>',
            ...evenements.map((evenement) => `
                <option value="${escapeHtml(evenement.id)}" ${selected === Number(evenement.id) ? "selected" : ""}>
                    ${escapeHtml(evenement.nom)}
                </option>
            `),
        ].join("");
    }

    function synchroniserEvenementPreferee(evenementSelectionnee = null) {
        const select = detailEl.querySelector("#fiche-evenement-preferee");
        const zoneCentres = detailEl.querySelector("#fiche-centres");
        if (!select || !zoneCentres) return;
        const centresChoisis = FormOptionsUtils.lireCentresHierarchises(zoneCentres);
        const ancienneValeur = evenementSelectionnee ?? select.value;
        select.innerHTML = optionsEvenementPreferee(centresChoisis.centre_prefere, ancienneValeur);
        select.disabled = !centresChoisis.centre_prefere
            || !centres.find((centre) => Number(centre.id) === Number(centresChoisis.centre_prefere))?.evenements?.some((evenement) => evenement.active);
    }

    function blankAnimateur() {
        return {
            id: null, prenom: "", nom: "", telephone: "", email: "",
            date_naissance: null, age: null, couleur: "#2563EB",
            qualification_ids: [], centre_prefere: null, centres_secondaires: [],
            evenement_preferee: null, evenement_preferee_id: null, disponibilites: [],
        };
    }

    function renderFiche(a, isNew = false) {
        const title = isNew ? "Nouvel animateur" : fullName(a);
        detailEl.style.setProperty("--anim-color", a.couleur || "#94a3b8");
        detailEl.innerHTML = `
            <div class="fiche-head">
                <div class="fiche-title">
                    <span class="fiche-color"></span>
                    <div><h2>${escapeHtml(title)}</h2><p>${isNew ? "Complète la fiche puis enregistre." : `Identifiant ${a.id}`}</p></div>
                </div>
                <div class="fiche-actions">
                    <button class="btn btn-primary" type="button" id="fiche-save">Enregistrer</button>
                    ${isNew ? '<button class="btn btn-ghost" type="button" id="fiche-cancel">Annuler</button>' : '<button class="btn-danger" type="button" id="fiche-delete">Supprimer</button>'}
                </div>
            </div>

            <section class="fiche-section fiche-card">
                <div class="fiche-section-head"><div><h3>Informations personnelles</h3><p>Coordonnées et identité de l’animateur.</p></div></div>
                <div class="fiche-grid">
                    <div class="field"><label>Prénom</label><input id="fiche-prenom" value="${escapeHtml(a.prenom || "")}"></div>
                    <div class="field"><label>Nom</label><input id="fiche-nom" value="${escapeHtml(a.nom || "")}"></div>
                    <div class="field"><label>Téléphone</label><input id="fiche-telephone" value="${escapeHtml(a.telephone || "")}"></div>
                    <div class="field"><label>E-mail</label><input id="fiche-email" type="email" value="${escapeHtml(a.email || "")}"></div>
                    <div class="field"><label>Date de naissance</label><input id="fiche-naissance" type="date" value="${escapeHtml(a.date_naissance || "")}"></div>
                    <div class="field"><label>Âge</label><div class="fiche-readonly">${a.age ? `${a.age} ans` : "Non calculé"}</div></div>
                    <div class="field"><label>Couleur planning</label><input id="fiche-couleur" type="color" value="${escapeHtml(a.couleur || "#2563EB")}"></div>
                </div>
            </section>

            <section class="fiche-section fiche-card">
                <div class="fiche-section-head">
                    <div>
                        <h3>Qualifications</h3>
                        <p>Compétences et diplômes de l’animateur.</p>
                    </div>
                </div>
                <div class="evenement-qualifs" id="fiche-qualifs">${qualificationsHtml(a.qualification_ids || [])}</div>
            </section>

            <section class="fiche-section fiche-card centres-card">
                <div class="fiche-section-head">
                    <div>
                        <h3>Centres d’affectation</h3>
                        <p>Choisis un centre principal et, si besoin, plusieurs centres secondaires.</p>
                    </div>
                </div>
                <div class="centre-hierarchy-grid evenement-centres" id="fiche-centres">
                    ${centresHtml(a.centre_prefere, a.centres_secondaires || [], `fiche-centre-prefere-${a.id || "new"}`)}
                </div>
                <div class="evenement-preferee-field field">
                    <label for="fiche-evenement-preferee">Événement préférée <span class="label-hint">(facultatif)</span></label>
                    <select id="fiche-evenement-preferee">
                        ${optionsEvenementPreferee(a.centre_prefere?.id || a.centre_prefere, a.evenement_preferee_id || a.evenement_preferee?.id)}
                    </select>
                    <p class="form-hint">Le remplissage automatique privilégiera cette événement, sans bloquer les affectations manuelles dans les autres événements.</p>
                </div>
            </section>

            <section class="fiche-section fiche-card disponibilites-card" ${isNew ? 'hidden' : ''}>
                <div class="fiche-section-head">
                    <div>
                        <h3>Disponibilités</h3>
                        <p>Ajoute une période disponible, puis ajuste les plages existantes si nécessaire.</p>
                    </div>
                </div>
                <div class="dispo-editor-card">
                    <div class="dispo-editor-title">Ajouter une disponibilité</div>
                    <div class="dispo-editor">
                        <div class="field"><label for="dispo-new-debut">Du</label><input type="date" id="dispo-new-debut"></div>
                        <div class="field"><label for="dispo-new-fin">Au <span class="label-hint">(inclus)</span></label><input type="date" id="dispo-new-fin"></div>
                        <button class="btn btn-primary" type="button" id="dispo-add">+ Ajouter</button>
                    </div>
                </div>
                <div class="dispo-list-head">
                    <span>Périodes enregistrées</span>
                </div>
                <div class="dispo-items" id="dispo-items"></div>
            </section>
            <p class="fiche-status"></p>`;

        FormOptionsUtils.activerCentresHierarchises(detailEl.querySelector("#fiche-centres"));
        detailEl.querySelectorAll('#fiche-centres input[data-role="prefere"]').forEach((radio) => {
            radio.addEventListener("change", () => synchroniserEvenementPreferee(null));
        });
        synchroniserEvenementPreferee(a.evenement_preferee_id || a.evenement_preferee?.id || null);
        detailEl.querySelector("#fiche-couleur").addEventListener("input", (e) => detailEl.style.setProperty("--anim-color", e.target.value));
        detailEl.querySelector("#fiche-save").addEventListener("click", () => saveFiche(a, isNew));

        if (isNew) detailEl.querySelector("#fiche-cancel").addEventListener("click", () => selectedId ? selectAnimateur(selectedId) : showEmpty());
        else {
            detailEl.querySelector("#fiche-delete").addEventListener("click", () => deleteAnimateur(a));
            detailEl.querySelector("#dispo-add").addEventListener("click", () => addDisponibilite(a.id));
            renderDisponibilites(a.id);
        }
    }

    function payloadFiche() {
        const centresChoisis = FormOptionsUtils.lireCentresHierarchises(detailEl.querySelector("#fiche-centres"));
        return {
            prenom: detailEl.querySelector("#fiche-prenom").value.trim(),
            nom: detailEl.querySelector("#fiche-nom").value.trim(),
            telephone: detailEl.querySelector("#fiche-telephone").value.trim(),
            email: detailEl.querySelector("#fiche-email").value.trim(),
            date_naissance: detailEl.querySelector("#fiche-naissance").value || null,
            couleur: detailEl.querySelector("#fiche-couleur").value,
            qualifications: idsCheckboxesCochees(detailEl.querySelector("#fiche-qualifs")),
            centre_prefere: centresChoisis.centre_prefere,
            centres_secondaires: centresChoisis.centres_secondaires,
            evenement_preferee: detailEl.querySelector("#fiche-evenement-preferee")?.value || null,
        };
    }

    async function saveFiche(a, isNew) {
        const payload = payloadFiche();
        if (!payload.prenom || !payload.nom) return setStatus("Le prénom et le nom sont obligatoires.", true);
        setStatus("Enregistrement…");
        try {
            const saved = await apiFetch(isNew ? "/api/animateurs/" : `/api/animateurs/${a.id}/`, {
                method: isNew ? "POST" : "PATCH",
                body: JSON.stringify(payload),
            });
            await loadAnimateurs();
            selectedId = saved.id;
            const current = animateurs.find((item) => item.id === saved.id) || saved;
            renderList();
            renderFiche(current);
            setStatus("Fiche enregistrée.");
        } catch (err) { setStatus(erreurMessage(err, "Enregistrement impossible."), true); }
    }

    async function deleteAnimateur(a) {
        if (!confirm(`Supprimer ${fullName(a)} ? Ses affectations et disponibilités seront également supprimées.`)) return;
        try {
            await apiFetch(`/api/animateurs/${a.id}/`, { method: "DELETE" });
            selectedId = null;
            await loadAnimateurs();
            renderList();
            showEmpty();
            afficherToast("Animateur supprimé.");
        } catch (err) { setStatus(erreurMessage(err, "Suppression impossible."), true); }
    }

    async function renderDisponibilites(animateurId) {
        const target = detailEl.querySelector("#dispo-items");
        if (!target) return;
        const data = await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`);
        const plages = data.disponibilites || [];
        target.innerHTML = "";
        if (!plages.length) {
            target.innerHTML = '<p class="empty-note">Aucune disponibilité : cet animateur est indisponible pour le planning.</p>';
            return;
        }
        plages.forEach((p) => {
            const row = document.createElement("div");
            row.className = "dispo-row";
            row.innerHTML = `
                <div class="field"><label>Début</label><input type="date" class="dispo-debut" value="${escapeHtml(p.debut)}"></div>
                <div class="field"><label>Fin</label><input type="date" class="dispo-fin" value="${escapeHtml(p.fin)}"></div>
                <button class="btn btn-ghost dispo-save" type="button">Modifier</button>
                <button class="btn-danger dispo-delete" type="button">Supprimer</button>`;
            row.querySelector(".dispo-save").addEventListener("click", async () => {
                try {
                    await apiFetch(`/api/animateurs/${animateurId}/disponibilites/${p.id}/`, {
                        method: "PATCH",
                        body: JSON.stringify({ debut: row.querySelector(".dispo-debut").value, fin: row.querySelector(".dispo-fin").value }),
                    });
                    await loadAnimateurs();
                    await renderDisponibilites(animateurId);
                    setStatus("Disponibilité modifiée.");
                } catch (err) { setStatus(erreurMessage(err, "Modification impossible."), true); }
            });
            row.querySelector(".dispo-delete").addEventListener("click", async () => {
                if (!confirm("Supprimer cette plage de disponibilité ?")) return;
                try {
                    await apiFetch(`/api/animateurs/${animateurId}/disponibilites/${p.id}/`, { method: "DELETE" });
                    await loadAnimateurs();
                    await renderDisponibilites(animateurId);
                    setStatus("Disponibilité supprimée.");
                } catch (err) { setStatus(erreurMessage(err, "Suppression impossible."), true); }
            });
            target.appendChild(row);
        });
    }

    async function addDisponibilite(animateurId) {
        const debut = detailEl.querySelector("#dispo-new-debut").value;
        const fin = detailEl.querySelector("#dispo-new-fin").value || debut;
        if (!debut) return setStatus("La date de début est obligatoire.", true);
        try {
            await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`, { method: "POST", body: JSON.stringify({ debut, fin }) });
            detailEl.querySelector("#dispo-new-debut").value = "";
            detailEl.querySelector("#dispo-new-fin").value = "";
            await loadAnimateurs();
            await renderDisponibilites(animateurId);
            setStatus("Disponibilité ajoutée.");
        } catch (err) { setStatus(erreurMessage(err, "Ajout impossible."), true); }
    }

    function showEmpty() {
        detailEl.innerHTML = '<div class="evenement-empty"><strong>Sélectionne un animateur</strong><p>Sa fiche complète apparaîtra ici.</p></div>';
    }

    function selectAnimateur(id) {
        selectedId = id;
        const a = animateurs.find((item) => item.id === id);
        renderList();
        if (a) renderFiche(a);
    }

    async function loadAnimateurs() {
        animateurs = await apiFetch("/api/animateurs/");
        return animateurs;
    }

    async function init() {
        try {
            const [qualificationsChargees, centresCharges] = await Promise.all([
                apiFetch("/api/qualifications/"),
                apiFetch("/api/centres/"),
            ]);
            qualifications = qualificationsChargees;
            centres = await Promise.all(centresCharges.map(async (centre) => ({
                ...centre,
                evenements: await apiFetch(`/api/centres/${centre.id}/evenements/`),
            })));
            await loadAnimateurs();
            renderList();
            if (animateurs.length) selectAnimateur(animateurs[0].id);
        } catch (err) {
            detailEl.innerHTML = `<div class="evenement-empty"><strong>Chargement impossible</strong><p>${escapeHtml(erreurMessage(err, "Erreur inconnue"))}</p></div>`;
        }
    }

    searchEl.addEventListener("input", renderList);
    addBtn.addEventListener("click", () => { selectedId = null; renderList(); renderFiche(blankAnimateur(), true); });
    init();
});
