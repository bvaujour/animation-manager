document.addEventListener("DOMContentLoaded", () => {
    const pageRoot = document.querySelector("[data-animateur-page]");
    if (!pageRoot) return;
    const listEl = document.getElementById("evenement-list");
    const detailEl = document.getElementById("evenement-detail");
    const searchEl = document.getElementById("evenement-search");
    const addBtn = document.getElementById("evenement-add");
    const filterQualificationsEl = document.getElementById("salaries-filter-qualifications");
    const filterCentresEl = document.getElementById("salaries-filter-centres");
    const filterDisponibiliteEl = document.getElementById("salaries-filter-disponibilite");
    const filterAffectationEl = document.getElementById("salaries-filter-affectation");
    const filterCountEl = document.getElementById("salaries-filter-count");
    const filterResetBtn = document.getElementById("salaries-filter-reset");
    const initialParams = new URLSearchParams(window.location.search);
    const requestedId = Number(initialParams.get("salarie") || 0) || null;
    const creationMode = initialParams.get("nouveau") === "1";
    const countEl = document.getElementById("employees-count");

    let animateurs = [];
    const selectedQualificationIds = new Set();
    const selectedCentreIds = new Set();
    let selectedDisponibilite = "";
    let selectedAffectation = "";

    let qualifications = [];
    let statuts = [];
    let centres = [];
    let typesContrats = [];
    let selectedId = null;
    let previousSelectedId = null;
    let activeDetailTab = "fiche";

    function fullName(a) { return `${a.prenom || ""} ${a.nom || ""}`.trim(); }
    function initials(a) {
        const first = String(a.prenom || "").trim().charAt(0);
        const last = String(a.nom || "").trim().charAt(0);
        return `${first}${last}`.toLocaleUpperCase("fr") || "?";
    }
    function centreCodes(a) {
        return (a.centres_autorises || []).map((c) => c.code).join(" · ");
    }
    function qualificationLabel(a) {
        const ids = new Set((a.qualification_ids || []).map(Number));
        const names = qualifications
            .filter((qualification) => ids.has(Number(qualification.id)))
            .map((qualification) => qualification.nom)
            .filter(Boolean);
        return names[0] || "Qualification non renseignée";
    }

    function setStatus(message = "", error = false) {
        if (!detailEl) return;
        const el = detailEl.querySelector(".fiche-status");
        if (!el) return;
        el.textContent = message;
        el.className = `fiche-status ${message ? (error ? "error" : "success") : ""}`;
    }

    function renderList() {
        if (!listEl || !searchEl) return;
        const query = searchEl.value.trim().toLocaleLowerCase("fr");
        const matchesDirectoryFilter = (a) => {
            const qualificationIds = new Set((a.qualification_ids || []).map(Number));
            const matchesQualifications = [...selectedQualificationIds].every((id) => qualificationIds.has(id));
            if (!matchesQualifications) return false;
            if (selectedCentreIds.size && !selectedCentreIds.has(Number(a.centre_prefere?.id))) return false;
            const today = new Date();
            const day = today.getDay();
            const monday = new Date(today); monday.setHours(0,0,0,0); monday.setDate(today.getDate() - ((day + 6) % 7));
            const friday = new Date(monday); friday.setDate(monday.getDate() + 4);
            const start = formatDateLocal(monday), end = formatDateLocal(friday);
            const overlap = (range, exclusive=false) => range && String(range.debut||"") <= end && (exclusive ? String(range.fin||"") > start : String(range.fin||"") >= start);
            const available = (a.disponibilites || []).some((range) => overlap(range));
            const assigned = (a.affectations || []).some((range) => overlap(range, true));
            if (selectedDisponibilite === "disponible" && !available) return false;
            if (selectedDisponibilite === "indisponible" && available) return false;
            if (selectedAffectation === "affecte" && !assigned) return false;
            if (selectedAffectation === "non-affecte" && assigned) return false;
            return true;
        };
        const filtered = animateurs
            .filter((a) => fullName(a).toLocaleLowerCase("fr").includes(query))
            .filter(matchesDirectoryFilter)
            .sort((a, b) => {
                const prenom = (a.prenom || "").localeCompare(b.prenom || "", "fr", { sensitivity: "base" });
                if (prenom !== 0) return prenom;
                const nom = (a.nom || "").localeCompare(b.nom || "", "fr", { sensitivity: "base" });
                return nom !== 0 ? nom : Number(a.id) - Number(b.id);
            });
        listEl.innerHTML = "";
        if (countEl) {
            countEl.textContent = filtered.length === animateurs.length
                ? `${animateurs.length} salarié${animateurs.length > 1 ? "s" : ""}`
                : `${filtered.length} sur ${animateurs.length}`;
        }

        if (!filtered.length) {
            listEl.innerHTML = '<p class="empty-note">Aucun salarié trouvé.</p>';
            return;
        }

        const symbolesIcones = {
            diplome: "🎓",
            secours: "✚",
            baignade: "🛟",
            conduite: "🚐",
            sport: "⚽",
            direction: "★",
            repas: "🍴",
        };

        filtered.forEach((a) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `animateur staff-list-item ${Number(a.id) === Number(selectedId) ? "selected" : ""}`;
            const couleurStatut = a.couleur_statut || a.couleur || "#718096";
            button.style.setProperty("--animateur-color", couleurStatut);
            button.dataset.animateurId = a.id;
            button.setAttribute("role", "option");
            button.setAttribute("aria-selected", Number(a.id) === Number(selectedId) ? "true" : "false");

            const contenu = document.createElement("span");
            contenu.className = "anim-content";

            const ligneNom = document.createElement("span");
            ligneNom.className = "anim-name-row";

            const iconesUniques = new Map();
            (a.qualification_icones || []).forEach((qualification) => {
                if (qualification?.icone && symbolesIcones[qualification.icone] && !iconesUniques.has(qualification.icone)) {
                    iconesUniques.set(qualification.icone, qualification.nom || "Qualification");
                }
            });
            if (iconesUniques.size) {
                const icones = document.createElement("span");
                icones.className = "anim-qualification-icons";
                [...iconesUniques.entries()].slice(0, 3).forEach(([icone, libelle]) => {
                    const badge = document.createElement("span");
                    badge.className = "anim-qualification-icon";
                    badge.textContent = symbolesIcones[icone];
                    badge.title = libelle;
                    badge.setAttribute("aria-label", libelle);
                    icones.appendChild(badge);
                });
                ligneNom.appendChild(icones);
            }

            const nom = document.createElement("span");
            nom.className = "anim-name";
            nom.textContent = fullName(a);
            ligneNom.appendChild(nom);
            contenu.appendChild(ligneNom);

            const details = document.createElement("span");
            details.className = "anim-details";
            const statutNom = a.statut_principal?.nom || qualificationLabel(a) || "Sans statut";
            const centre = a.centre_prefere?.code || centreCodes(a) || "";
            details.textContent = [statutNom, centre].filter(Boolean).join(" · ");
            contenu.appendChild(details);
            button.appendChild(contenu);

            const infos = [a.telephone || null, a.email || null].filter(Boolean).join(" · ");
            if (infos) button.title = infos;

            button.addEventListener("click", () => selectAnimateur(a.id));
            listEl.appendChild(button);
        });
    }


    function updateFilterCount() {
        const count = selectedQualificationIds.size + selectedCentreIds.size + (selectedDisponibilite ? 1 : 0) + (selectedAffectation ? 1 : 0);
        StaffFilterUI.updateCount(filterCountEl, count);
    }

    function renderDirectoryFilters() {
        StaffFilterUI.renderOptions(filterQualificationsEl, qualifications, {
            selected: selectedQualificationIds,
            emptyText: "Aucun diplôme",
            name: "salaries_filter_qualification",
            onChange: (input) => {
                const id = Number(input.value);
                if (input.checked) selectedQualificationIds.add(id);
                else selectedQualificationIds.delete(id);
                updateFilterCount();
                renderList();
            },
        });
        StaffFilterUI.renderOptions(filterCentresEl, centres, {
            selected: selectedCentreIds,
            emptyText: "Aucun centre",
            name: "salaries_filter_centre",
            onChange: (input) => {
                const id = Number(input.value);
                if (input.checked) selectedCentreIds.add(id);
                else selectedCentreIds.delete(id);
                updateFilterCount();
                renderList();
            },
        });
        updateFilterCount();
    }

    [filterDisponibiliteEl, filterAffectationEl].forEach((select) => select?.addEventListener("change", () => {
        selectedDisponibilite = filterDisponibiliteEl?.value || "";
        selectedAffectation = filterAffectationEl?.value || "";
        updateFilterCount();
        renderList();
    }));
    function qualificationsHtml(checked = [], group = "fiche-qualifications") {
        return FormOptionsUtils.qualifications(qualifications, checked, group);
    }

    function centresHtml(prefere = null, secondaires = [], group = "fiche-centre-prefere") {
        return FormOptionsUtils.centresHierarchises(centres, prefere, secondaires, group);
    }

    function affinitesGroupesHtml(affinites = []) {
        if (!affinites.length) {
            return '<p class="empty-note">Aucune affinité avec un groupe n’est encore enregistrée.</p>';
        }
        const total = affinites.reduce((somme, entree) => somme + Number(entree.score_affinite ?? entree.jours_travailles ?? 0), 0);
        return `
            <div class="employee-group-history-summary">
                <strong>${total}</strong>
                <span>point${total > 1 ? "s" : ""} d’affinité cumulé${total > 1 ? "s" : ""}</span>
            </div>
            <div class="employee-group-history-list">
                ${affinites.map((entree) => `
                    <div class="employee-group-history-row">
                        <div>
                            <strong>${escapeHtml(entree.groupe_nom || "Groupe")}</strong>
                            <span>${escapeHtml(entree.centre_nom || "")}</span>
                        </div>
                        <div class="employee-group-history-count">
                            <strong>${Number(entree.score_affinite ?? entree.jours_travailles ?? 0)}</strong>
                            <span>point${Number(entree.score_affinite ?? entree.jours_travailles ?? 0) > 1 ? "s" : ""}</span>
                        </div>
                    </div>
                `).join("")}
            </div>
            <p class="field-help">Chaque journée terminée dans un groupe ajoute automatiquement 1 point. Le remplissage automatique privilégie ensuite les salariés ayant la meilleure affinité avec ce groupe.</p>`;
    }

    function blankAnimateur() {
        return {
            id: null, prenom: "", nom: "", telephone: "", email: "",
            date_naissance: null, adresse: "", numero_securite_sociale: "",
            paie_jour: null, age: null, couleur: "#94A3B8", statut_principal: null,
            qualification_ids: [], centres_preferes: [], centres_interdits: [], centre_prefere: null, centres_secondaires: [],
            evenement_preferee: null, evenement_preferee_id: null, disponibilites: [], affinites_groupes: [], historique_groupes: [],
            contrats: [], role: "animateur", access: { exists: false, username: null, active: false },
        };
    }

    function formatMontantContrat(valeur) {
        return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(Number(valeur));
    }

    function formatDateContrat(valeur) {
        if (!valeur) return "";
        return new Intl.DateTimeFormat("fr-FR").format(new Date(`${valeur}T12:00:00`));
    }

    function periodeContrat(contrat) {
        if (!contrat.date_debut && !contrat.date_fin) return "Sans dates renseignées";
        if (contrat.date_debut && !contrat.date_fin) return `Depuis le ${formatDateContrat(contrat.date_debut)}`;
        if (!contrat.date_debut && contrat.date_fin) return `Jusqu’au ${formatDateContrat(contrat.date_fin)}`;
        return `${formatDateContrat(contrat.date_debut)} → ${formatDateContrat(contrat.date_fin)}`;
    }

    function contratsHtml(a) {
        const contrats = [...(a.contrats || [])].sort((premier, second) => {
            const priorite = { en_cours: 0, a_venir: 1, termine: 2 };
            return (priorite[premier.statut] - priorite[second.statut])
                || String(second.date_debut).localeCompare(String(premier.date_debut));
        });
        const liste = contrats.length ? contrats.map((contrat) => {
            const remuneration = contrat.mode_paie === "cee_journalier"
                ? `Taux journalier de référence : ${formatMontantContrat(contrat.taux_journalier_reference)} / jour`
                : contrat.mode_paie === "paie_habituelle" ? "Paie habituelle / hors calcul"
                : `Salaire mensuel de référence : ${formatMontantContrat(contrat.salaire_mensuel_reference)}`;
            return `<article class="employee-contract-row employee-contract-row--${escapeHtml(contrat.statut)}">
                <div class="employee-contract-main">
                    <span class="employee-contract-status">${escapeHtml(contrat.statut_libelle)}</span>
                    <strong>${escapeHtml(contrat.type_contrat_libelle)}</strong>
                    <span>${escapeHtml(periodeContrat(contrat))}</span>
                    <small>${escapeHtml(remuneration)}</small>
                </div>
                <div class="employee-contract-actions">
                    <button class="btn btn-ghost btn-small" type="button" data-contract-edit="${Number(contrat.id)}">Modifier</button>
                    <button class="btn-danger btn-small" type="button" data-contract-delete="${Number(contrat.id)}">Supprimer</button>
                </div>
            </article>`;
        }).join("") : '<p class="empty-note">Contrat non renseigné.</p>';
        return `${liste}
            <form class="employee-contract-form" id="employee-contract-form" hidden>
                <input type="hidden" id="contract-id">
                <div class="field"><label for="contract-type">Type de contrat</label><select id="contract-type" required>${typesContrats.map((item) => `<option value="${escapeHtml(item.code)}" data-pay-mode="${escapeHtml(item.mode_remuneration)}">${escapeHtml(item.nom)}</option>`).join("")}</select></div>
                <div class="field"><label for="contract-start">Date de début</label><input id="contract-start" type="date" required></div>
                <div class="field"><label for="contract-end">Date de fin</label><input id="contract-end" type="date"></div>
                <div class="field" data-contract-daily><label for="contract-daily">Taux journalier de référence</label><input id="contract-daily" type="number" min="0" step="0.01" inputmode="decimal"></div>
                <div class="field" data-contract-monthly hidden><label for="contract-monthly">Salaire mensuel de référence</label><input id="contract-monthly" type="number" min="0" step="0.01" inputmode="decimal"></div>
                <div class="field" data-contract-salary-date hidden><label for="contract-salary-date">Date d’effet de la rémunération</label><input id="contract-salary-date" type="date"></div>
                <div class="field" data-contract-time-mode hidden><label for="contract-time-mode">Mode de temps de travail</label><select id="contract-time-mode"><option value="non_renseigne">Non renseigné</option><option value="hebdomadaire">Hebdomadaire</option><option value="mensuel">Mensuel</option><option value="annualise">Annualisé / lissé</option></select></div>
                <div class="field" data-contract-weekly hidden><label for="contract-weekly">Heures par semaine</label><input id="contract-weekly" type="number" min="0" step="0.01"></div>
                <div class="field" data-contract-monthly-hours hidden><label for="contract-monthly-hours">Heures par mois</label><input id="contract-monthly-hours" type="number" min="0" step="0.01"></div>
                <div class="field" data-contract-annual hidden><label for="contract-annual">Heures par an</label><input id="contract-annual" type="number" min="0" step="0.01"></div>
                <div class="field" data-contract-pay-mode hidden><label for="contract-pay-mode">Mode de rémunération</label><select id="contract-pay-mode"></select></div>
                <div class="field" data-contract-apprentice-year hidden><label for="contract-apprentice-year">Année d’exécution initiale</label><select id="contract-apprentice-year"><option value="">À renseigner</option><option value="1">1re année</option><option value="2">2e année</option><option value="3">3e année</option></select></div>
                <div class="field" data-contract-apprentice-date hidden><label for="contract-apprentice-date">Date d’effet de l’année</label><input id="contract-apprentice-date" type="date"></div>
                <div class="employee-contract-form-actions"><button class="btn btn-primary btn-small" type="submit">Enregistrer</button><button class="btn btn-ghost btn-small" type="button" data-contract-cancel>Annuler</button></div>
            </form>`;
    }

    function historiqueStatutsHtml(a) {
        const historique = a.historique_statuts || [];
        return `<div class="employee-status-history-current"><span>Statut actuel</span><strong>${escapeHtml(a.statut_principal?.nom || "Non renseigné")}</strong></div>
            <div class="employee-status-history-list">${historique.length ? historique.map((entree) => `
                <article class="employee-status-history-row">
                    <div><strong>${formatDateContrat(entree.date_effet)} — ${escapeHtml(entree.statut_nom)}</strong><small>${escapeHtml(entree.origine_libelle)}${entree.date_effet_incertaine ? " · date technique de reprise" : ""}</small></div>
                    <div class="employee-contract-actions"><button class="btn btn-ghost btn-small" data-status-history-edit="${entree.id}" type="button">Modifier</button><button class="btn-danger btn-small" data-status-history-delete="${entree.id}" type="button">Supprimer</button></div>
                </article>`).join("") : '<p class="empty-note">Aucun historique daté.</p>'}</div>
            <form id="employee-status-history-form" class="employee-status-history-form" hidden>
                <input name="id" type="hidden">
                <div class="field"><label>Statut</label><select name="statut_id" required>${statuts.map((statut) => `<option value="${statut.id}">${escapeHtml(statut.nom)}</option>`).join("")}</select></div>
                <div class="field"><label>Date d’effet</label><input name="date_effet" type="date" required></div>
                <div class="field"><label>Commentaire</label><input name="commentaire" maxlength="240"></div>
                <div class="employee-contract-form-actions"><button class="btn btn-primary btn-small" type="submit">Enregistrer</button><button class="btn btn-ghost btn-small" data-status-history-cancel type="button">Annuler</button></div>
            </form>`;
    }

    function renderFiche(a, isNew = false) {
        const title = isNew ? "Nouveau salarié" : fullName(a);
        if (isNew) activeDetailTab = "fiche";
        detailEl.style.setProperty("--anim-color", a.couleur || "#94a3b8");
        detailEl.innerHTML = `
            <div class="fiche-head employee-editor-head">
                <div class="fiche-title">
                    <span class="fiche-color"></span>
                    <div class="employee-title-copy">
                        <h2>${escapeHtml(title)}</h2>
                        <div class="employee-title-meta">
                            <span>${isNew ? "Création d’une fiche" : `Salarié n°${a.id}`}</span>
                            <span class="fiche-status" aria-live="polite"></span>
                        </div>
                    </div>
                </div>
                <div class="fiche-actions">
                    <button class="btn btn-primary" type="button" id="fiche-save">Enregistrer</button>
                    ${isNew ? '<button class="btn btn-ghost" type="button" id="fiche-cancel">Annuler</button>' : '<button class="btn-danger" type="button" id="fiche-delete">Supprimer</button>'}
                </div>
            </div>

            <nav class="employee-detail-tabs" aria-label="Rubriques de la fiche">
                <button type="button" data-employee-tab="fiche">Fiche</button>
                <button type="button" data-employee-tab="affectations">Affectations</button>
                <button type="button" data-employee-tab="acces">Accès</button>
                ${isNew ? "" : '<button type="button" data-employee-tab="disponibilites">Disponibilités</button><button type="button" data-employee-tab="email">E-mail</button>'}
            </nav>

            <div class="employee-detail-panels">
                <div class="employee-detail-panel" data-employee-panel="fiche">
                    <section class="fiche-section fiche-card employee-compact-card">
                        <div class="fiche-section-head"><h3>Informations personnelles</h3></div>
                        <div class="fiche-grid employee-profile-grid">
                            <div class="field"><label for="fiche-prenom">Prénom</label><input id="fiche-prenom" name="prenom" autocomplete="given-name" value="${escapeHtml(a.prenom || "")}"></div>
                            <div class="field"><label for="fiche-nom">Nom</label><input id="fiche-nom" name="nom" autocomplete="family-name" value="${escapeHtml(a.nom || "")}"></div>
                            <div class="field"><label for="fiche-telephone">Téléphone</label><input id="fiche-telephone" name="telephone" type="tel" autocomplete="tel" value="${escapeHtml(a.telephone || "")}"></div>
                            <div class="field employee-span-2"><label for="fiche-email">E-mail</label><input id="fiche-email" name="email" type="email" autocomplete="email" value="${escapeHtml(a.email || "")}"></div>
                            <div class="field"><label for="fiche-naissance">Naissance</label><input id="fiche-naissance" name="date_naissance" type="date" autocomplete="bday" value="${escapeHtml(a.date_naissance || "")}"></div>
                            <div class="field"><label>Âge</label><div class="fiche-readonly">${a.age ? `${a.age} ans` : "—"}</div></div>
                            <div class="field"><label for="fiche-paie-jour">Paie / jour (€)</label><input id="fiche-paie-jour" name="paie_jour" type="number" min="0" step="0.01" inputmode="decimal" value="${escapeHtml(a.paie_jour ?? "")}"></div>
                            <div class="field employee-span-2"><label for="fiche-securite-sociale">N° de sécurité sociale</label><input id="fiche-securite-sociale" name="numero_securite_sociale" maxlength="21" autocomplete="off" value="${escapeHtml(a.numero_securite_sociale || "")}"></div>
                            <div class="field employee-span-2"><label for="fiche-adresse">Adresse</label><textarea id="fiche-adresse" name="adresse" rows="2" autocomplete="street-address">${escapeHtml(a.adresse || "")}</textarea></div>
                            <div class="field employee-span-2 fiche-couleur-field">
                                <label>Couleur du planning</label>
                                <div class="employee-status-color-info">
                                    <span class="employee-status-color-dot" style="--status-color:${escapeHtml(a.couleur || "#94A3B8")}"></span>
                                    <span>${a.statut_principal ? `Définie automatiquement par le statut <strong>${escapeHtml(a.statut_principal.nom)}</strong>.` : "Aucun statut associé : couleur neutre appliquée."}</span>
                                </div>
                            </div>
                        </div>
                    </section>

                    ${isNew ? "" : `<section id="contrats" class="fiche-section fiche-card employee-compact-card employee-contracts-card">
                        <div class="fiche-section-head"><h3>Contrats</h3><button class="btn btn-ghost btn-small" type="button" data-contract-add>+ Ajouter un contrat</button></div>
                        <div class="employee-contract-list">${contratsHtml(a)}</div>
                    </section>`}

                    ${isNew ? "" : `<section id="historique-statut" class="fiche-section fiche-card employee-compact-card employee-status-history-card">
                        <div class="fiche-section-head"><h3>Historique du statut</h3><button class="btn btn-ghost btn-small" data-status-history-add type="button">+ Ajouter un changement</button></div>
                        ${historiqueStatutsHtml(a)}
                    </section>`}

                    <section class="fiche-section fiche-card employee-compact-card">
                        <div class="fiche-section-head"><h3>Diplômes</h3></div>
                        <div class="evenement-qualifs employee-qualifications" id="fiche-qualifs">${qualificationsHtml(a.qualification_ids || [], `fiche-qualifications-${a.id || "new"}`)}</div>
                    </section>
                </div>

                <div class="employee-detail-panel" data-employee-panel="affectations" hidden>
                    <section class="fiche-section fiche-card employee-compact-card centres-card">
                        <div class="fiche-section-head"><h3>Lieux d’affectation</h3></div>
                        <div class="centre-hierarchy-grid evenement-centres" id="fiche-centres">
                            ${centresHtml(a.centres_preferes || (a.centre_prefere ? [a.centre_prefere] : []), a.centres_interdits || [], `fiche-centre-prefere-${a.id || "new"}`)}
                        </div>
                    </section>
                    ${isNew ? "" : `
                    <section class="fiche-section fiche-card employee-compact-card employee-group-history-card">
                        <div class="fiche-section-head"><h3>Affinité avec les groupes</h3></div>
                        ${affinitesGroupesHtml(a.affinites_groupes || a.historique_groupes || [])}
                    </section>`}
                </div>

                <div class="employee-detail-panel" data-employee-panel="acces" hidden>
                    <section class="fiche-section fiche-card employee-compact-card access-card">
                        <div class="fiche-section-head"><h3>Accès au site</h3></div>
                        <div class="fiche-grid access-grid">
                            <div class="field">
                                <label>Rôle</label>
                                <div class="fiche-readonly">Animateur</div>
                                
                            </div>
                            ${isNew ? `
                            <label class="access-create-option">
                                <input type="checkbox" id="fiche-create-access">
                                <span><strong>Créer son accès au site</strong></span>
                            </label>` : `
                            <div class="access-account-state">
                                ${a.access?.exists ? `
                                    <p><strong>Compte :</strong> ${escapeHtml(a.access.username || "")}</p>
                                    <label class="access-toggle"><input type="checkbox" id="fiche-access-active" ${a.access.active ? "checked" : ""}> <span>Accès actif</span></label>
                                    <div class="access-actions">
                                        <button type="button" class="btn btn-ghost btn-small" id="fiche-reset-password">Réinitialiser le mot de passe</button>
                                        <button type="button" class="btn-danger btn-small" id="fiche-remove-access">Supprimer l’accès</button>
                                    </div>
                                ` : `
                                    <p class="empty-note">Aucun compte de connexion associé.</p>
                                    <button type="button" class="btn btn-primary btn-small" id="fiche-create-access-now">Créer l’accès</button>
                                `}
                            </div>`}
                        </div>
                        <div id="temporary-credentials" class="temporary-credentials" hidden></div>
                    </section>
                </div>

                ${isNew ? "" : `
                <div class="employee-detail-panel" data-employee-panel="disponibilites" hidden>
                    <section class="fiche-section fiche-card employee-compact-card disponibilites-card">
                        <div class="fiche-section-head"><h3>Disponibilités</h3></div>
                        
                        <div class="dispo-items" id="dispo-items"></div>
                    </section>
                </div>
                <div class="employee-detail-panel" data-employee-panel="email" hidden>
                    <section class="fiche-section fiche-card employee-compact-card communication-card">
                        <div class="fiche-section-head"><h3>Envoyer un e-mail à ${escapeHtml(a.prenom || "ce salarié")}</h3></div>
                        <div id="employee-email-configuration" class="employee-email-configuration" role="status">Vérification de la configuration…</div>
                        <div class="communication-grid">
                            <div class="field"><label>Destinataire</label><div class="fiche-readonly">${escapeHtml(a.email || "Aucune adresse e-mail")}</div></div>
                            <div class="field">
                                <label for="employee-email-template">Modèle</label>
                                <select id="employee-email-template">
                                    <option value="">Message personnalisé</option>
                                </select>
                                
                            </div>
                            <div class="field"><label for="employee-email-object">Objet</label><input id="employee-email-object" maxlength="200" value="Information AJS"></div>
                            <div class="field communication-message-field"><label for="employee-email-message">Message</label><textarea id="employee-email-message" rows="7" maxlength="10000"></textarea></div>
                        </div>
                        <div class="email-variable-guide employee-email-variable-guide">
                            <strong>Variables disponibles</strong>
                            <div id="employee-email-variables" class="email-variable-list"></div>
                            
                        </div>
                        <details class="employee-email-attachments">
                            <summary>Pièces jointes <span class="label-hint">(facultatif)</span></summary>
                            <div id="employee-email-documents" class="employee-email-document-list"><p class="empty-note">Chargement…</p></div>
                        </details>
                        <p class="form-error" id="employee-email-error"></p>
                        <div id="employee-email-result" class="email-resultat" hidden></div>
                        <div class="communication-actions">
                            <button class="btn btn-primary" type="button" id="employee-email-send" disabled>Envoyer depuis le site</button>
                        </div>
                    </section>
                </div>`}
            </div>`;

        const activerOnglet = (onglet) => {
            const disponible = detailEl.querySelector(`[data-employee-tab="${onglet}"]`) ? onglet : "fiche";
            activeDetailTab = disponible;
            detailEl.querySelectorAll("[data-employee-tab]").forEach((button) => {
                const active = button.dataset.employeeTab === disponible;
                button.classList.toggle("active", active);
                button.setAttribute("aria-selected", active ? "true" : "false");
            });
            detailEl.querySelectorAll("[data-employee-panel]").forEach((panel) => {
                panel.hidden = panel.dataset.employeePanel !== disponible;
            });
            const panels = detailEl.querySelector(".employee-detail-panels");
            if (panels) panels.scrollTop = 0;
        };
        detailEl.querySelectorAll("[data-employee-tab]").forEach((button) => {
            button.addEventListener("click", () => activerOnglet(button.dataset.employeeTab));
        });
        activerOnglet(activeDetailTab);

        FormOptionsUtils.activerCentresHierarchises(detailEl.querySelector("#fiche-centres"));
        detailEl.querySelector("#fiche-save").addEventListener("click", () => saveFiche(a, isNew));

        if (!isNew) {
            initialiserHistoriqueStatuts(a);
            initialiserContrats(a);
            initialiserEmailAnimateur(a);
            detailEl.querySelector("#fiche-create-access-now")?.addEventListener("click", () => actionCompte(a, { create_access: true }));
            detailEl.querySelector("#fiche-reset-password")?.addEventListener("click", () => actionCompte(a, { reset_password: true }, "Créer un nouveau mot de passe provisoire ?"));
            detailEl.querySelector("#fiche-remove-access")?.addEventListener("click", () => actionCompte(a, { remove_access: true }, "Supprimer uniquement son accès au site ? La fiche salarié sera conservée."));
            detailEl.querySelector("#fiche-access-active")?.addEventListener("change", (event) => actionCompte(a, { access_active: event.target.checked }));
            const storedCredentials = sessionStorage.getItem("temporaryCredentials");
            if (storedCredentials) {
                sessionStorage.removeItem("temporaryCredentials");
                try { afficherIdentifiants(JSON.parse(storedCredentials)); } catch {}
            }
        }

        if (isNew) {
            detailEl.querySelector("#fiche-cancel").addEventListener("click", () => {
                const fallback = animateurs.find((item) => Number(item.id) === Number(previousSelectedId)) || animateurs[0];
                if (fallback) selectAnimateur(fallback.id); else showEmpty();
            });
        } else {
            detailEl.querySelector("#fiche-delete").addEventListener("click", () => deleteAnimateur(a));
            renderDisponibilites(a.id);
        }
    }

    function initialiserHistoriqueStatuts(a) {
        const form = detailEl.querySelector("#employee-status-history-form");
        if (!form) return;
        const ouvrir = (entree = null) => {
            form.hidden = false;
            form.elements.id.value = entree?.id || "";
            form.elements.statut_id.value = entree?.statut_id || statuts[0]?.id || "";
            form.elements.date_effet.value = entree?.date_effet || "";
            form.elements.commentaire.value = entree?.commentaire || "";
            form.elements.statut_id.focus();
        };
        const rafraichir = async (message) => {
            await loadAnimateurs();
            const actualise = animateurs.find((item) => Number(item.id) === Number(a.id));
            await chargerHistoriqueStatuts(actualise);
            renderFiche(actualise);
            setStatus(message);
        };
        detailEl.querySelector("[data-status-history-add]")?.addEventListener("click", () => ouvrir());
        detailEl.querySelectorAll("[data-status-history-edit]").forEach((button) => button.addEventListener("click", () => {
            ouvrir((a.historique_statuts || []).find((item) => Number(item.id) === Number(button.dataset.statusHistoryEdit)));
        }));
        detailEl.querySelectorAll("[data-status-history-delete]").forEach((button) => button.addEventListener("click", async () => {
            const entree = (a.historique_statuts || []).find((item) => Number(item.id) === Number(button.dataset.statusHistoryDelete));
            if (!entree || !confirm(`Supprimer le changement « ${entree.statut_nom} » du ${formatDateContrat(entree.date_effet)} ? Cette suppression pourra modifier les futurs calculs de paie.`)) return;
            try {
                await apiFetch(`/api/animateurs/${a.id}/historique-statuts/${entree.id}/`, { method: "DELETE" });
                await rafraichir("Changement de statut supprimé.");
            } catch (error) { setStatus(erreurMessage(error, "Suppression impossible."), true); }
        }));
        form.querySelector("[data-status-history-cancel]").addEventListener("click", () => { form.hidden = true; });
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const id = Number(form.elements.id.value) || null;
            try {
                await apiFetch(`/api/animateurs/${a.id}/historique-statuts/${id ? `${id}/` : ""}`, {
                    method: id ? "PATCH" : "POST",
                    body: JSON.stringify({
                        statut_id: Number(form.elements.statut_id.value),
                        date_effet: form.elements.date_effet.value,
                        commentaire: form.elements.commentaire.value.trim(),
                    }),
                });
                await rafraichir(id ? "Changement de statut modifié." : "Changement de statut ajouté.");
            } catch (error) { setStatus(erreurMessage(error, "Enregistrement impossible."), true); }
        });
    }

    function initialiserContrats(a) {
        const form = detailEl.querySelector("#employee-contract-form");
        if (!form) return;
        const type = form.querySelector("#contract-type");
        const actualiserRemuneration = () => {
            const mode = type.selectedOptions[0]?.dataset.payMode || "cee_journalier";
            const cee = mode === "cee_journalier";
            const mensualise = mode === "mensualise";
            const apprentissage = mode === "apprentissage";
            const temps = form.querySelector("#contract-time-mode").value;
            const payMode = form.querySelector("#contract-pay-mode");
            const optionsAttendues = apprentissage
                ? [["grille_auto", "Minimum grille automatique"], ["grille_controle", "Salaire contractuel avec contrôle du minimum"]]
                : [["salaire_fixe", "Salaire fixe"], ["minimum_smic", "Minimum SMIC automatique"], ["fixe_controle", "Salaire fixe avec contrôle du minimum"]];
            if (!optionsAttendues.some(([value]) => value === payMode.value)) {
                payMode.innerHTML = optionsAttendues.map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
            }
            form.querySelector("[data-contract-daily]").hidden = !cee;
            form.querySelector("[data-contract-monthly]").hidden = !(mensualise || apprentissage);
            form.querySelector("[data-contract-salary-date]").hidden = !(mensualise || apprentissage);
            form.querySelector("[data-contract-time-mode]").hidden = !mensualise;
            form.querySelector("[data-contract-pay-mode]").hidden = !(mensualise || apprentissage);
            form.querySelector("[data-contract-weekly]").hidden = !mensualise || temps !== "hebdomadaire";
            form.querySelector("[data-contract-monthly-hours]").hidden = !mensualise || !["mensuel", "annualise"].includes(temps);
            form.querySelector("[data-contract-annual]").hidden = !mensualise || temps !== "annualise";
            form.querySelector("[data-contract-apprentice-year]").hidden = !apprentissage;
            form.querySelector("[data-contract-apprentice-date]").hidden = !apprentissage;
            form.querySelector("#contract-daily").required = cee;
            form.querySelector("#contract-start").required = mode !== "paie_habituelle";
            const remuneration = form.querySelector("#contract-pay-mode").value;
            form.querySelector("#contract-monthly").required = mensualise && remuneration !== "minimum_smic";
        };
        const ouvrir = (contrat = null) => {
            form.hidden = false;
            form.querySelector("#contract-id").value = contrat?.id || "";
            type.value = contrat?.type_contrat || "cee";
            form.querySelector("#contract-start").value = contrat?.date_debut || "";
            form.querySelector("#contract-end").value = contrat?.date_fin || "";
            form.querySelector("#contract-daily").value = contrat?.taux_journalier_reference || "";
            form.querySelector("#contract-monthly").value = contrat?.salaire_mensuel_reference || "";
            form.querySelector("#contract-salary-date").value = contrat?.historique_remunerations?.[0]?.date_effet || contrat?.date_debut || "";
            form.querySelector("#contract-time-mode").value = contrat?.mode_temps_travail || "non_renseigne";
            form.querySelector("#contract-weekly").value = contrat?.heures_hebdomadaires || "";
            form.querySelector("#contract-monthly-hours").value = contrat?.heures_mensuelles_reference || "";
            form.querySelector("#contract-annual").value = contrat?.heures_annuelles_reference || "";
            const payMode = form.querySelector("#contract-pay-mode");
            const selectedMode = type.selectedOptions[0]?.dataset.payMode;
            payMode.innerHTML = selectedMode === "apprentissage"
                ? '<option value="grille_auto">Minimum grille automatique</option><option value="grille_controle">Salaire contractuel avec contrôle du minimum</option>'
                : '<option value="salaire_fixe">Salaire fixe</option><option value="minimum_smic">Minimum SMIC automatique</option><option value="fixe_controle">Salaire fixe avec contrôle du minimum</option>';
            payMode.value = contrat?.mode_remuneration || (selectedMode === "apprentissage" ? "grille_controle" : "salaire_fixe");
            form.querySelector("#contract-apprentice-year").value = contrat?.annee_execution_initiale || "";
            form.querySelector("#contract-apprentice-date").value = contrat?.date_effet_annee_execution || "";
            actualiserRemuneration();
            form.querySelector("#contract-start").focus();
        };
        const rafraichir = async (message) => {
            await loadAnimateurs();
            const actualise = animateurs.find((item) => Number(item.id) === Number(a.id));
            await chargerHistoriqueStatuts(actualise);
            renderFiche(actualise);
            setStatus(message);
        };
        type.addEventListener("change", actualiserRemuneration);
        form.querySelector("#contract-time-mode").addEventListener("change", actualiserRemuneration);
        form.querySelector("#contract-pay-mode").addEventListener("change", actualiserRemuneration);
        detailEl.querySelector("[data-contract-add]")?.addEventListener("click", () => ouvrir());
        detailEl.querySelectorAll("[data-contract-edit]").forEach((bouton) => bouton.addEventListener("click", () => {
            ouvrir((a.contrats || []).find((item) => Number(item.id) === Number(bouton.dataset.contractEdit)));
        }));
        detailEl.querySelectorAll("[data-contract-delete]").forEach((bouton) => bouton.addEventListener("click", async () => {
            const contrat = (a.contrats || []).find((item) => Number(item.id) === Number(bouton.dataset.contractDelete));
            if (!contrat || !confirm(`Supprimer le contrat ${contrat.type_contrat_libelle} débutant le ${formatDateContrat(contrat.date_debut)} ?`)) return;
            try {
                await apiFetch(`/api/animateurs/${a.id}/contrats/${contrat.id}/`, { method: "DELETE" });
                await rafraichir("Contrat supprimé.");
            } catch (error) { setStatus(erreurMessage(error, "Suppression impossible."), true); }
        }));
        form.querySelector("[data-contract-cancel]").addEventListener("click", () => { form.hidden = true; });
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const id = Number(form.querySelector("#contract-id").value) || null;
            const mode = type.selectedOptions[0]?.dataset.payMode || "cee_journalier";
            const cee = mode === "cee_journalier";
            const mensualise = ["mensualise", "apprentissage"].includes(mode);
            const payload = {
                type_contrat: type.value,
                date_debut: form.querySelector("#contract-start").value,
                date_fin: form.querySelector("#contract-end").value || null,
                taux_journalier_reference: cee ? (form.querySelector("#contract-daily").value || null) : null,
                salaire_mensuel_reference: mensualise ? (form.querySelector("#contract-monthly").value || null) : null,
                date_effet_remuneration: mensualise ? (form.querySelector("#contract-salary-date").value || form.querySelector("#contract-start").value) : null,
                mode_temps_travail: form.querySelector("#contract-time-mode").value,
                heures_hebdomadaires: form.querySelector("#contract-weekly").value || null,
                heures_mensuelles_reference: form.querySelector("#contract-monthly-hours").value || null,
                heures_annuelles_reference: form.querySelector("#contract-annual").value || null,
                mode_remuneration: form.querySelector("#contract-pay-mode").value || "salaire_fixe",
                annee_execution_initiale: form.querySelector("#contract-apprentice-year").value || null,
                date_effet_annee_execution: form.querySelector("#contract-apprentice-date").value || null,
            };
            try {
                await apiFetch(`/api/animateurs/${a.id}/contrats/${id ? `${id}/` : ""}`, {
                    method: id ? "PATCH" : "POST",
                    body: JSON.stringify(payload),
                });
                await rafraichir(id ? "Contrat modifié." : "Contrat ajouté.");
            } catch (error) { setStatus(erreurMessage(error, "Enregistrement du contrat impossible."), true); }
        });
        actualiserRemuneration();
    }


    let modelesEmailAnimateur = [];
    let champVariableEmailActif = null;
    const identifiantsProvisoires = new Map();

    function insererVariableEmail(champ, code) {
        if (!champ) return;
        const debut = Number.isInteger(champ.selectionStart) ? champ.selectionStart : champ.value.length;
        const fin = Number.isInteger(champ.selectionEnd) ? champ.selectionEnd : debut;
        champ.value = `${champ.value.slice(0, debut)}${code}${champ.value.slice(fin)}`;
        const position = debut + code.length;
        champ.focus();
        champ.setSelectionRange?.(position, position);
    }

    function afficherModelesEmailAnimateur(modeles) {
        const select = detailEl.querySelector("#employee-email-template");
        if (!select) return;
        modelesEmailAnimateur = Array.isArray(modeles) ? modeles : [];
        select.innerHTML = '<option value="">Message personnalisé</option>' + modelesEmailAnimateur
            .map((modele) => `<option value="${Number(modele.id)}">${escapeHtml(modele.nom)}</option>`)
            .join("");
    }

    function afficherVariablesEmailAnimateur(variables) {
        const zone = detailEl.querySelector("#employee-email-variables");
        if (!zone) return;
        zone.innerHTML = "";
        (variables || []).forEach((variable) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "email-variable-chip";
            button.textContent = variable.code;
            button.title = variable.libelle;
            button.addEventListener("click", () => {
                insererVariableEmail(
                    champVariableEmailActif || detailEl.querySelector("#employee-email-message"),
                    variable.code,
                );
            });
            zone.appendChild(button);
        });
    }

    function formatTailleEmail(octets) {
        const valeur = Number(octets);
        if (!Number.isFinite(valeur)) return "taille inconnue";
        if (valeur < 1024) return `${valeur} o`;
        if (valeur < 1048576) return `${Math.round(valeur / 1024)} Ko`;
        return `${(valeur / 1048576).toFixed(1).replace(".", ",")} Mo`;
    }

    function afficherDocumentsEmail(documents) {
        const zone = detailEl.querySelector("#employee-email-documents");
        if (!zone) return;
        zone.innerHTML = documents.length ? documents.map((document) => `
            <label class="employee-email-document-option">
                <input type="checkbox" value="${Number(document.id)}">
                <span><strong>${escapeHtml(document.titre)}</strong><small>${escapeHtml(document.libelle_periode || "Permanent")} · ${escapeHtml(formatTailleEmail(document.taille))}</small></span>
            </label>`).join("") : '<p class="empty-note">Aucun document disponible. Les pièces jointes restent facultatives.</p>';
    }

    async function chargerEmailsAnimateur(a) {
        const configuration = detailEl.querySelector("#employee-email-configuration");
        const envoyer = detailEl.querySelector("#employee-email-send");
        try {
            const data = await apiFetch(`/api/animateurs/${a.id}/emails/`);
            const statut = data.configuration || {};
            configuration.className = `employee-email-configuration ${statut.operationnel ? (statut.mode_test ? "test" : "success") : "error"}`;
            configuration.textContent = statut.message || "Configuration e-mail inconnue.";
            envoyer.disabled = !statut.operationnel || !a.email;
            afficherModelesEmailAnimateur(data.modeles || []);
            afficherVariablesEmailAnimateur(data.variables || []);
            afficherDocumentsEmail(data.documents || []);
        } catch (error) {
            configuration.className = "employee-email-configuration error";
            const message = erreurMessage(error, "Impossible de préparer l’envoi d’e-mail.");
            configuration.textContent = message;
            envoyer.disabled = true;
        }
    }

    function initialiserEmailAnimateur(a) {
        const objetEl = detailEl.querySelector("#employee-email-object");
        const messageEl = detailEl.querySelector("#employee-email-message");
        const modeleEl = detailEl.querySelector("#employee-email-template");
        const envoyer = detailEl.querySelector("#employee-email-send");
        const erreurEl = detailEl.querySelector("#employee-email-error");
        const resultatEl = detailEl.querySelector("#employee-email-result");
        if (!messageEl || !envoyer) return;

        [objetEl, messageEl].forEach((champ) => {
            champ?.addEventListener("focus", () => { champVariableEmailActif = champ; });
        });
        champVariableEmailActif = messageEl;
        modeleEl?.addEventListener("change", () => {
            const modele = modelesEmailAnimateur.find((item) => Number(item.id) === Number(modeleEl.value));
            if (!modele) return;
            objetEl.value = modele.objet;
            messageEl.value = modele.message;
            messageEl.focus();
        });
        detailEl.querySelector("#employee-email-refresh")?.addEventListener("click", () => chargerEmailsAnimateur(a));
        envoyer.addEventListener("click", async () => {
            erreurEl.textContent = "";
            resultatEl.hidden = true;
            const objet = objetEl.value.trim();
            const message = messageEl.value.trim();
            const document_ids = [...detailEl.querySelectorAll('#employee-email-documents input[type="checkbox"]:checked')].map((input) => Number(input.value));
            if (!objet || !message) {
                erreurEl.textContent = "L’objet et le message sont obligatoires.";
                return;
            }
            if (!a.email) {
                erreurEl.textContent = "Ajoute d’abord une adresse e-mail valide dans la fiche.";
                return;
            }
            if (!confirm(`Envoyer maintenant cet e-mail à ${a.prenom} ${a.nom} (${a.email}) ?`)) return;

            const texteInitial = envoyer.textContent;
            envoyer.disabled = true;
            envoyer.textContent = "Envoi en cours…";
            try {
                const data = await apiFetch(`/api/animateurs/${a.id}/emails/`, {
                    method: "POST",
                    body: JSON.stringify({ objet, message, document_ids }),
                });
                resultatEl.hidden = false;
                resultatEl.className = "email-resultat success";
                resultatEl.textContent = data.mode_test ? "E-mail intercepté en mode test." : "E-mail envoyé directement depuis le site.";
                setStatus("E-mail envoyé.");
                await chargerEmailsAnimateur(a);
            } catch (error) {
                erreurEl.textContent = erreurMessage(error, "L’envoi a échoué.");
                setStatus("Échec de l’envoi.", true);
                await chargerEmailsAnimateur(a);
            } finally {
                envoyer.textContent = texteInitial;
            }
        });
        chargerEmailsAnimateur(a);
    }

    function payloadFiche() {
        const centresChoisis = FormOptionsUtils.lireCentresHierarchises(detailEl.querySelector("#fiche-centres"));
        return {
            prenom: detailEl.querySelector("#fiche-prenom").value.trim(),
            nom: detailEl.querySelector("#fiche-nom").value.trim(),
            telephone: detailEl.querySelector("#fiche-telephone").value.trim(),
            email: detailEl.querySelector("#fiche-email").value.trim(),
            date_naissance: detailEl.querySelector("#fiche-naissance").value || null,
            paie_jour: detailEl.querySelector("#fiche-paie-jour").value || null,
            numero_securite_sociale: detailEl.querySelector("#fiche-securite-sociale").value.trim(),
            adresse: detailEl.querySelector("#fiche-adresse").value.trim(),
            qualifications: idsCheckboxesCochees(detailEl.querySelector("#fiche-qualifs")),
            centres_preferes: centresChoisis.centres_preferes,
            centres_interdits: centresChoisis.centres_interdits,
            role: "animateur",
            create_access: Boolean(detailEl.querySelector("#fiche-create-access")?.checked),
            access_active: detailEl.querySelector("#fiche-access-active") ? detailEl.querySelector("#fiche-access-active").checked : undefined,
        };
    }

    function afficherIdentifiants(credentials) {
        if (!credentials) return;
        if (selectedId) identifiantsProvisoires.set(Number(selectedId), credentials);
        const texte = `Identifiant : ${credentials.username}\nMot de passe provisoire : ${credentials.temporary_password}`;
        const zone = detailEl.querySelector("#temporary-credentials");
        if (zone) {
            zone.hidden = false;
            zone.innerHTML = `<strong>Accès créé</strong><p>Identifiant : <code>${escapeHtml(credentials.username)}</code></p><p>Mot de passe provisoire : <code>${escapeHtml(credentials.temporary_password)}</code></p><div class="communication-actions"><button type="button" class="btn btn-ghost btn-small" id="copy-credentials">Copier les accès</button></div>`;
            zone.querySelector("#copy-credentials")?.addEventListener("click", async () => {
                await navigator.clipboard.writeText(texte);
                afficherToast("Accès copiés.");
            });
        }
        return texte;
    }

    async function actionCompte(a, action, confirmation = null) {
        if (confirmation && !confirm(confirmation)) return;
        setStatus("Mise à jour de l’accès…");
        try {
            const saved = await apiFetch(`/api/animateurs/${a.id}/`, { method: "PATCH", body: JSON.stringify({ role: "animateur", ...action }) });
            await loadAnimateurs();
            const current = animateurs.find((item) => item.id === saved.id) || saved;
            renderFiche(current);
            if (saved.temporary_credentials) afficherIdentifiants(saved.temporary_credentials);
            setStatus("Accès mis à jour.");
        } catch (err) { setStatus(erreurMessage(err, "Modification de l’accès impossible."), true); }
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
            if (isNew && saved.temporary_credentials) activeDetailTab = "acces";
            await loadAnimateurs();
            selectedId = saved.id;
            previousSelectedId = saved.id;
            const current = animateurs.find((item) => Number(item.id) === Number(saved.id)) || saved;
            mettreAJourUrl(saved.id);
            renderList();
            renderFiche(current);
            if (saved.temporary_credentials) afficherIdentifiants(saved.temporary_credentials);
            setStatus(isNew ? "Salarié créé." : "Fiche enregistrée.");
        } catch (err) { setStatus(erreurMessage(err, "Enregistrement impossible."), true); }
    }

    async function deleteAnimateur(a) {
        if (!confirm(`Supprimer ${fullName(a)} ? Ses affectations et disponibilités seront également supprimées.`)) return;
        try {
            await apiFetch(`/api/animateurs/${a.id}/`, { method: "DELETE" });
            animateurs = animateurs.filter((item) => Number(item.id) !== Number(a.id));
            afficherToast("Salarié supprimé.");
            const suivant = animateurs[0] || null;
            if (suivant) selectAnimateur(suivant.id);
            else { selectedId = null; mettreAJourUrl(); renderList(); showEmpty(); }
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
        if (!detailEl) return;
        detailEl.innerHTML = '<div class="evenement-empty"><strong>Sélectionne un salarié</strong><p>Sa fiche complète apparaîtra ici.</p></div>';
    }

    function mettreAJourUrl(id = null, nouveau = false) {
        const url = new URL(window.location.href);
        url.searchParams.delete("salarie");
        url.searchParams.delete("nouveau");
        if (nouveau) url.searchParams.set("nouveau", "1");
        else if (id) url.searchParams.set("salarie", String(id));
        window.history.replaceState({}, "", url);
    }

    function afficherSectionDemandee() {
        const sectionId = window.location.hash.slice(1);
        if (!["contrats", "historique-statut"].includes(sectionId)) return;
        requestAnimationFrame(() => document.getElementById(sectionId)?.scrollIntoView({ block: "center" }));
    }

    async function chargerHistoriqueStatuts(a) {
        if (!a?.id) return;
        a.historique_statuts = await apiFetch(`/api/animateurs/${a.id}/historique-statuts/`);
        const aujourdHui = new Date();
        aujourdHui.setMinutes(aujourdHui.getMinutes() - aujourdHui.getTimezoneOffset());
        const dateLocale = aujourdHui.toISOString().slice(0, 10);
        const courant = a.historique_statuts.find((item) => item.date_effet <= dateLocale);
        if (courant) a.statut_principal = { id: courant.statut_id, nom: courant.statut_nom };
    }

    async function selectAnimateur(id) {
        const a = animateurs.find((item) => Number(item.id) === Number(id));
        if (!a) return;
        selectedId = a.id;
        previousSelectedId = a.id;
        activeDetailTab = "fiche";
        mettreAJourUrl(a.id);
        renderList();
        await chargerHistoriqueStatuts(a);
        renderList();
        renderFiche(a);
        afficherSectionDemandee();
    }

    async function loadAnimateurs() {
        animateurs = await apiFetch("/api/animateurs/?include_affectations=1");
        return animateurs;
    }

    async function init() {
        if (listEl) listEl.innerHTML = '<p class="empty-note">Chargement des salariés…</p>';
        try {
            const [animateursCharges, qualificationsChargees, centresCharges, typesContratsCharges] = await Promise.all([
                loadAnimateurs(),
                apiFetch("/api/qualifications/"),
                apiFetch("/api/centres/").then((items) => Promise.all(items.map(async (centre) => ({
                    ...centre,
                    evenements: await apiFetch(`/api/centres/${centre.id}/groupes/`),
                })))),
                apiFetch("/api/types-contrats/"),
            ]);
            typesContrats = typesContratsCharges;
            statuts = qualificationsChargees.filter((qualification) => qualification.est_statut);
            qualifications = qualificationsChargees.filter((qualification) => !qualification.est_statut);
            centres = centresCharges;
            renderDirectoryFilters();

            if (creationMode) {
                previousSelectedId = animateursCharges[0]?.id || null;
                selectedId = null;
                renderList();
                renderFiche(blankAnimateur(), true);
                return;
            }

            const employee = animateursCharges.find((item) => Number(item.id) === Number(requestedId)) || animateursCharges[0];
            if (!employee) {
                renderList();
                showEmpty();
                return;
            }
            selectedId = employee.id;
            previousSelectedId = employee.id;
            mettreAJourUrl(employee.id);
            renderList();
            await chargerHistoriqueStatuts(employee);
            renderList();
            renderFiche(employee);
            afficherSectionDemandee();
        } catch (err) {
            if (listEl) listEl.innerHTML = `<p class="empty-note">${escapeHtml(erreurMessage(err, "Chargement impossible."))}</p>`;
            detailEl.innerHTML = `<div class="evenement-empty"><strong>Chargement impossible</strong><p>${escapeHtml(erreurMessage(err, "Erreur inconnue"))}</p></div>`;
        }
    }


    if (addBtn) {
        addBtn.addEventListener("click", () => {
            previousSelectedId = selectedId || previousSelectedId;
            selectedId = null;
            activeDetailTab = "fiche";
            mettreAJourUrl(null, true);
            renderList();
            renderFiche(blankAnimateur(), true);
        });
    }

    if (searchEl) searchEl.addEventListener("input", renderList);

    if (filterResetBtn) {
        filterResetBtn.addEventListener("click", () => {
            selectedQualificationIds.clear();
            selectedCentreIds.clear();
            selectedDisponibilite = "";
            selectedAffectation = "";
            if (filterDisponibiliteEl) filterDisponibiliteEl.value = "";
            if (filterAffectationEl) filterAffectationEl.value = "";
            document.querySelectorAll('#salaries-filter input[type="checkbox"]').forEach((input) => { input.checked = false; });
            updateFilterCount();
            renderList();
        });
    }



    init();
});
