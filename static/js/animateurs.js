document.addEventListener("DOMContentLoaded", () => {
    const listEl = document.getElementById("evenement-list");
    const detailEl = document.getElementById("evenement-detail");
    const searchEl = document.getElementById("evenement-search");
    const addBtn = document.getElementById("evenement-add");

    let animateurs = [];

    const PALETTE_ANIMATEURS = [
        "#2563EB", "#7C3AED", "#DB2777", "#DC2626",
        "#EA580C", "#CA8A04", "#16A34A", "#059669",
        "#0891B2", "#4F46E5", "#9333EA", "#475569",
    ];

    function couleurAleatoireAnimateur() {
        return PALETTE_ANIMATEURS[Math.floor(Math.random() * PALETTE_ANIMATEURS.length)];
    }

    function paletteCouleursHtml(couleurActive) {
        return PALETTE_ANIMATEURS.map((couleur) => `
            <button
                class="animateur-color-swatch ${couleur.toLowerCase() === String(couleurActive || "").toLowerCase() ? "active" : ""}"
                type="button"
                data-couleur="${couleur}"
                aria-label="Choisir la couleur ${couleur}"
                title="${couleur}"
                style="--swatch-color:${couleur}"
            ></button>
        `).join("");
    }
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
        const filtered = animateurs
            .filter((a) => fullName(a).toLocaleLowerCase("fr").includes(query))
            .sort((a, b) => {
                const prenom = (a.prenom || "").localeCompare(b.prenom || "", "fr", { sensitivity: "base" });
                if (prenom !== 0) return prenom;
                const nom = (a.nom || "").localeCompare(b.nom || "", "fr", { sensitivity: "base" });
                return nom !== 0 ? nom : Number(a.id) - Number(b.id);
            });
        listEl.innerHTML = "";

        if (!filtered.length) {
            listEl.innerHTML = '<p class="empty-note">Aucun salarié trouvé.</p>';
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
                    <span class="evenement-list-meta">${escapeHtml(centreCodes(a) || "Aucun lieu renseigné")}</span>
                </span>`;
            btn.addEventListener("click", () => selectAnimateur(a.id));
            listEl.appendChild(btn);
        });
    }

    function qualificationsHtml(checked = [], group = "fiche-qualifications") {
        return FormOptionsUtils.qualifications(qualifications, checked, group);
    }

    function centresHtml(prefere = null, secondaires = [], group = "fiche-centre-prefere") {
        return FormOptionsUtils.centresHierarchises(centres, prefere, secondaires, group);
    }

    function optionsEvenementPreferee(centreId, evenementId = null) {
        const centre = centres.find((item) => Number(item.id) === Number(centreId));
        const evenements = (centre?.evenements || []);
        const selected = Number(evenementId) || null;

        if (!centreId) {
            return '<option value="">Choisis d’abord un lieu préféré</option>';
        }
        if (!evenements.length) {
            return '<option value="">Aucun groupe dans ce lieu</option>';
        }

        return [
            '<option value="">Aucune préférence de groupe</option>',
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
            || !centres.find((centre) => Number(centre.id) === Number(centresChoisis.centre_prefere))?.evenements?.length;
    }

    function blankAnimateur() {
        return {
            id: null, prenom: "", nom: "", telephone: "", email: "",
            date_naissance: null, age: null, couleur: couleurAleatoireAnimateur(),
            qualification_ids: [], centre_prefere: null, centres_secondaires: [],
            evenement_preferee: null, evenement_preferee_id: null, disponibilites: [],
        };
    }

    function renderFiche(a, isNew = false) {
        const title = isNew ? "Nouveau salarié" : fullName(a);
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
                <div class="fiche-section-head"><div><h3>Informations personnelles</h3><p>Coordonnées et identité du salarié.</p></div></div>
                <div class="fiche-grid">
                    <div class="field"><label for="fiche-prenom">Prénom</label><input id="fiche-prenom" name="prenom" autocomplete="given-name" value="${escapeHtml(a.prenom || "")}"></div>
                    <div class="field"><label for="fiche-nom">Nom</label><input id="fiche-nom" name="nom" autocomplete="family-name" value="${escapeHtml(a.nom || "")}"></div>
                    <div class="field"><label for="fiche-telephone">Téléphone</label><input id="fiche-telephone" name="telephone" type="tel" autocomplete="tel" value="${escapeHtml(a.telephone || "")}"></div>
                    <div class="field"><label for="fiche-email">E-mail</label><input id="fiche-email" name="email" type="email" autocomplete="email" value="${escapeHtml(a.email || "")}"></div>
                    <div class="field"><label for="fiche-naissance">Date de naissance</label><input id="fiche-naissance" name="date_naissance" type="date" autocomplete="bday" value="${escapeHtml(a.date_naissance || "")}"></div>
                    <div class="field"><label>Âge</label><div class="fiche-readonly">${a.age ? `${a.age} ans` : "Non calculé"}</div></div>
                    <div class="field fiche-couleur-field">
                        <label for="fiche-couleur">Couleur planning</label>
                        <div class="animateur-color-picker">
                            <div class="animateur-color-palette" id="fiche-couleur-palette">${paletteCouleursHtml(a.couleur || "#2563EB")}</div>
                            <div class="animateur-color-custom">
                                <input id="fiche-couleur" name="couleur" type="color" value="${escapeHtml(a.couleur || "#2563EB")}" aria-label="Choisir une couleur personnalisée">
                                <button class="btn btn-ghost btn-small" id="fiche-couleur-random" type="button">Aléatoire</button>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <section class="fiche-section fiche-card">
                <div class="fiche-section-head">
                    <div>
                        <h3>Qualifications</h3>
                        <p>Compétences et diplômes du salarié.</p>
                    </div>
                </div>
                <div class="evenement-qualifs" id="fiche-qualifs">${qualificationsHtml(a.qualification_ids || [], `fiche-qualifications-${a.id || "new"}`)}</div>
            </section>

            <section class="fiche-section fiche-card centres-card">
                <div class="fiche-section-head">
                    <div>
                        <h3>Lieux d’affectation</h3>
                        <p>Choisis un lieu principal et, si besoin, plusieurs lieux secondaires.</p>
                    </div>
                </div>
                <div class="centre-hierarchy-grid evenement-centres" id="fiche-centres">
                    ${centresHtml(a.centre_prefere, a.centres_secondaires || [], `fiche-centre-prefere-${a.id || "new"}`)}
                </div>
                <div class="evenement-preferee-field field">
                    <label for="fiche-evenement-preferee">Groupe préféré <span class="label-hint">(facultatif)</span></label>
                    <select id="fiche-evenement-preferee" name="evenement_preferee">
                        ${optionsEvenementPreferee(a.centre_prefere?.id || a.centre_prefere, a.evenement_preferee_id || a.evenement_preferee?.id)}
                    </select>
                    <p class="form-hint">Le remplissage automatique privilégiera cet groupe, sans bloquer les affectations manuelles dans les autres groupes.</p>
                </div>
            </section>

            <section class="fiche-section fiche-card disponibilites-card" ${isNew ? 'hidden' : ''}>
                <div class="fiche-section-head">
                    <div>
                        <h3>Disponibilités</h3>
                        <p>Coche une période entière, puis décoche seulement les jours où le salarié n’est pas disponible.</p>
                    </div>
                </div>
                <div class="dispo-items" id="dispo-items"></div>
            </section>
            <p class="fiche-status"></p>`;

        FormOptionsUtils.activerCentresHierarchises(detailEl.querySelector("#fiche-centres"));
        detailEl.querySelectorAll('#fiche-centres input[data-role="prefere"]').forEach((radio) => {
            radio.addEventListener("change", () => synchroniserEvenementPreferee(null));
        });
        synchroniserEvenementPreferee(a.evenement_preferee_id || a.evenement_preferee?.id || null);
        const couleurInput = detailEl.querySelector("#fiche-couleur");
        const appliquerCouleur = (couleur) => {
            couleurInput.value = couleur;
            detailEl.style.setProperty("--anim-color", couleur);
            detailEl.querySelectorAll(".animateur-color-swatch").forEach((swatch) => {
                swatch.classList.toggle("active", swatch.dataset.couleur.toLowerCase() === couleur.toLowerCase());
            });
        };
        couleurInput.addEventListener("input", (e) => appliquerCouleur(e.target.value));
        detailEl.querySelectorAll(".animateur-color-swatch").forEach((swatch) => {
            swatch.addEventListener("click", () => appliquerCouleur(swatch.dataset.couleur));
        });
        detailEl.querySelector("#fiche-couleur-random").addEventListener("click", () => appliquerCouleur(couleurAleatoireAnimateur()));
        detailEl.querySelector("#fiche-save").addEventListener("click", () => saveFiche(a, isNew));

        if (isNew) detailEl.querySelector("#fiche-cancel").addEventListener("click", () => selectedId ? selectAnimateur(selectedId) : showEmpty());
        else {
            detailEl.querySelector("#fiche-delete").addEventListener("click", () => deleteAnimateur(a));
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
            afficherToast("Salarié supprimé.");
        } catch (err) { setStatus(erreurMessage(err, "Suppression impossible."), true); }
    }

    function formaterJour(dateIso) {
        const date = new Date(`${dateIso}T12:00:00`);
        return new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit" }).format(date);
    }

    async function enregistrerDisponibilites(animateurId, target) {
        const joursDisponibles = [...target.querySelectorAll('.dispo-jour input[type="checkbox"]:checked')]
            .map((input) => input.value);
        await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`, {
            method: "PUT",
            body: JSON.stringify({ jours_disponibles: joursDisponibles }),
        });
        await loadAnimateurs();
        setStatus("Disponibilités enregistrées.");
    }

    async function renderDisponibilites(animateurId) {
        const target = detailEl.querySelector("#dispo-items");
        if (!target) return;
        target.innerHTML = '<p class="empty-note">Chargement des périodes…</p>';
        const data = await apiFetch(`/api/animateurs/${animateurId}/disponibilites/`);
        const periodes = data.periodes || [];
        target.innerHTML = "";
        if (!periodes.length) {
            target.innerHTML = '<p class="empty-note">Aucune période enregistrée dans la bibliothèque.</p>';
            return;
        }

        const anneeOuverte = anneePeriodesADeplier(periodes);
        grouperPeriodesParAnnee(periodes).forEach(({ annee, periodes: periodesAnnee }) => {
            const anneeBloc = document.createElement("details");
            anneeBloc.className = "dispo-annee period-year-accordion";
            anneeBloc.open = annee === anneeOuverte;
            anneeBloc.innerHTML = `
                <summary>
                    <span class="period-year-summary"><strong>${escapeHtml(annee)}</strong><small class="dispo-annee-count"></small></span>
                    <span class="period-year-chevron" aria-hidden="true">⌄</span>
                </summary>
                <div class="period-year-content dispo-annee-content"></div>`;

            const content = anneeBloc.querySelector(".dispo-annee-content");
            const compteurAnnee = anneeBloc.querySelector(".dispo-annee-count");

            function actualiserAnnee() {
                const jours = [...anneeBloc.querySelectorAll('.dispo-jour input[type="checkbox"]')];
                const joursCoches = jours.filter((input) => input.checked).length;
                const periodesActives = [...anneeBloc.querySelectorAll(".dispo-periode-toggle")].filter((input) => input.checked).length;
                compteurAnnee.textContent = `${periodesActives}/${periodesAnnee.length} période${periodesAnnee.length > 1 ? "s" : ""} · ${joursCoches}/${jours.length} jours`;
            }

            periodesAnnee.forEach((periode) => {
                const bloc = document.createElement("details");
                bloc.className = "dispo-periode";
                const checkedCount = periode.jours.filter((jour) => jour.disponible).length;
                bloc.innerHTML = `
                    <summary>
                        <label class="dispo-periode-check" onclick="event.stopPropagation()">
                            <input type="checkbox" class="dispo-periode-toggle" ${periode.selectionnee ? "checked" : ""}>
                            <span><strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong><small>${checkedCount}/${periode.jours.length} jours</small></span>
                        </label>
                        <span class="dispo-chevron">⌄</span>
                    </summary>
                    <div class="dispo-jours">
                        ${periode.jours.map((jour) => `
                            <label class="dispo-jour">
                                <input type="checkbox" value="${escapeHtml(jour.date)}" ${jour.disponible ? "checked" : ""}>
                                <span>${escapeHtml(formaterJour(jour.date))}</span>
                            </label>`).join("")}
                    </div>`;

                const periodeToggle = bloc.querySelector(".dispo-periode-toggle");
                const jours = [...bloc.querySelectorAll('.dispo-jour input[type="checkbox"]')];
                const actualiser = () => {
                    const nb = jours.filter((input) => input.checked).length;
                    periodeToggle.checked = nb > 0;
                    periodeToggle.indeterminate = nb > 0 && nb < jours.length;
                    bloc.querySelector("small").textContent = `${nb}/${jours.length} jours`;
                    actualiserAnnee();
                };
                periodeToggle.addEventListener("change", async () => {
                    jours.forEach((input) => { input.checked = periodeToggle.checked; });
                    bloc.open = periodeToggle.checked;
                    actualiser();
                    try { await enregistrerDisponibilites(animateurId, target); }
                    catch (err) { setStatus(erreurMessage(err, "Enregistrement impossible."), true); }
                });
                jours.forEach((input) => input.addEventListener("change", async () => {
                    actualiser();
                    try { await enregistrerDisponibilites(animateurId, target); }
                    catch (err) { setStatus(erreurMessage(err, "Enregistrement impossible."), true); }
                }));
                content.appendChild(bloc);
                actualiser();
            });

            actualiserAnnee();
            target.appendChild(anneeBloc);
        });
    }

    function showEmpty() {
        detailEl.innerHTML = '<div class="evenement-empty"><strong>Sélectionne un salarié</strong><p>Sa fiche complète apparaîtra ici.</p></div>';
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
        listEl.innerHTML = '<p class="empty-note">Chargement des salariés…</p>';

        // La liste principale est indépendante des données nécessaires à la
        // fiche. Ainsi, une lenteur ou une erreur sur les lieux/groupes
        // n'empêche plus les noms de s'afficher.
        const animateursPromise = loadAnimateurs()
            .then(() => {
                renderList();
                return true;
            })
            .catch((err) => {
                listEl.innerHTML = "";
                detailEl.innerHTML = `<div class="evenement-empty"><strong>Chargement impossible</strong><p>${escapeHtml(erreurMessage(err, "Erreur inconnue"))}</p></div>`;
                return false;
            });

        const referencesPromise = Promise.all([
            apiFetch("/api/qualifications/"),
            apiFetch("/api/centres/").then((centresCharges) =>
                Promise.all(centresCharges.map(async (centre) => ({
                    ...centre,
                    evenements: await apiFetch(`/api/centres/${centre.id}/groupes/`),
                })))
            ),
        ])
            .then((data) => ({ ok: true, data }))
            .catch((error) => ({ ok: false, error }));

        const animateursCharges = await animateursPromise;
        if (!animateursCharges) return;

        const references = await referencesPromise;
        if (!references.ok) {
            detailEl.innerHTML = `<div class="evenement-empty"><strong>Fiche momentanément indisponible</strong><p>La liste est chargée, mais les lieux ou qualifications n’ont pas pu être récupérés.</p></div>`;
            return;
        }

        [qualifications, centres] = references.data;
        if (animateurs.length) selectAnimateur(animateurs[0].id);
        else showEmpty();
    }

    searchEl.addEventListener("input", renderList);
    addBtn.addEventListener("click", () => { selectedId = null; renderList(); renderFiche(blankAnimateur(), true); });
    init();
});
