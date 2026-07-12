document.addEventListener("DOMContentLoaded", () => {
    const listEl = document.getElementById("equipe-list");
    const detailEl = document.getElementById("equipe-detail");
    const searchEl = document.getElementById("equipe-search");
    const addBtn = document.getElementById("equipe-add");

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
            btn.className = `equipe-list-item ${a.id === selectedId ? "active" : ""}`;
            btn.style.setProperty("--anim-color", a.couleur || "#94a3b8");
            btn.innerHTML = `
                <span class="equipe-list-color"></span>
                <span>
                    <span class="equipe-list-name">${escapeHtml(fullName(a))}</span>
                    <span class="equipe-list-meta">${escapeHtml(centreCodes(a) || "Aucun centre renseigné")}</span>
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

    function blankAnimateur() {
        return {
            id: null, prenom: "", nom: "", telephone: "", email: "",
            date_naissance: null, age: null, couleur: "#2563EB",
            qualification_ids: [], centre_prefere: null, centres_secondaires: [], disponibilites: [],
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

            <section class="fiche-section">
                <h3>Informations personnelles</h3>
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

            <section class="fiche-section">
                <h3>Qualifications</h3>
                <div class="equipe-qualifs" id="fiche-qualifs">${qualificationsHtml(a.qualification_ids || [])}</div>
            </section>

            <section class="fiche-section">
                <h3>Centres</h3>
                <div class="centre-hierarchy-grid equipe-centres" id="fiche-centres">
                    ${centresHtml(a.centre_prefere, a.centres_secondaires || [], `fiche-centre-prefere-${a.id || "new"}`)}
                </div>
            </section>

            <section class="fiche-section" ${isNew ? 'hidden' : ''}>
                <h3>Disponibilités</h3>
                <div class="dispo-editor">
                    <div class="field"><label>Début</label><input type="date" id="dispo-new-debut"></div>
                    <div class="field"><label>Fin incluse</label><input type="date" id="dispo-new-fin"></div>
                    <button class="btn btn-primary" type="button" id="dispo-add">Ajouter la plage</button>
                </div>
                <div class="dispo-items" id="dispo-items"></div>
            </section>
            <p class="fiche-status"></p>`;

        FormOptionsUtils.activerCentresHierarchises(detailEl.querySelector("#fiche-centres"));
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
        detailEl.innerHTML = '<div class="equipe-empty"><strong>Sélectionne un animateur</strong><p>Sa fiche complète apparaîtra ici.</p></div>';
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
            [qualifications, centres] = await Promise.all([apiFetch("/api/qualifications/"), apiFetch("/api/centres/")]);
            await loadAnimateurs();
            renderList();
            if (animateurs.length) selectAnimateur(animateurs[0].id);
        } catch (err) {
            detailEl.innerHTML = `<div class="equipe-empty"><strong>Chargement impossible</strong><p>${escapeHtml(erreurMessage(err, "Erreur inconnue"))}</p></div>`;
        }
    }

    searchEl.addEventListener("input", renderList);
    addBtn.addEventListener("click", () => { selectedId = null; renderList(); renderFiche(blankAnimateur(), true); });
    init();
});
