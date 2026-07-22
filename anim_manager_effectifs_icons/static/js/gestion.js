// ===========================================================================
// gestion.js
// ---------------------------------------------------------------------------
// Module CRUD de la page /gestion/ pour les paramètres partagés :
// salariés, lieux, groupes et qualifications sont réunis dans /gestion/.
// ===========================================================================

const GestionApp = (function ()
{
let formFieldSequence = 0;

function identifiantChamp(prefix)
	{
		formFieldSequence += 1;
		return `${prefix}-${formFieldSequence}`;
	}

function champValeur(form, selector)
	{
		return form.querySelector(selector).value.trim();
	}

	function libelleDate(dateStr)
	{
		if (!dateStr) return "";
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
	}

function bouton(label, classes, onClick)
	{
		const btn = document.createElement("button");
		btn.type = "button";
		btn.className = classes;
		btn.innerHTML = label;
		btn.addEventListener("click", onClick);
		return btn;
	}

	function creerFormActions(onSave, onCancel)
	{
		const actions = document.createElement("div");
		actions.classList.add("edit-actions");
		actions.appendChild(bouton("Enregistrer", "btn btn-primary", onSave));
		actions.appendChild(bouton("Annuler", "btn btn-ghost", onCancel));
		return actions;
	}





	// ------------------------------------------------------------------
	// Qualifications
	// ------------------------------------------------------------------
	function mountQualifications(container, options = {})
	{
		let qualifications = [];
		const qualificationIcones = [
			["", "Aucune icône", ""],
			["diplome", "Diplôme / qualification", "🎓"],
			["secours", "Premiers secours", "✚"],
			["baignade", "Surveillance baignade", "🛟"],
			["conduite", "Permis / conduite", "🚐"],
			["sport", "Sport", "⚽"],
			["direction", "Direction", "★"],
			["repas", "Repas / alimentation", "🍴"],
		];
		const optionsIcones = (valeur = "") => qualificationIcones
			.map(([cle, libelle, symbole]) => `<option value="${cle}" ${cle === valeur ? "selected" : ""}>${symbole ? `${symbole} ` : ""}${escapeHtml(libelle)}</option>`)
			.join("");
		const badgeIcone = (qualification) => {
			const item = qualificationIcones.find(([cle]) => cle === qualification.icone);
			return item && item[2] ? `<span class="qualification-icon-badge" title="${escapeHtml(item[1])}" aria-label="${escapeHtml(item[1])}">${item[2]}</span>` : "";
		};
		container.innerHTML = `
			<p class="section-title">Diplômes et statuts existants</p>
			
			<div class="entity-list" id="qualifs-list"></div>
			<p class="section-title">Ajouter un diplôme ou un statut</p>
			<div class="gestion-form" id="qualif-form">
				<div class="field">
					<label for="qualif-nom">Nom</label>
					<input type="text" id="qualif-nom" name="qualification_nom" placeholder="ex : BAFA">
				</div>
				<label class="checkbox-option">
					<input type="checkbox" id="qualif-auto" name="qualification_auto" checked>
					<span>Proposer ce diplôme dans les besoins des groupes</span>
				</label>
				<label class="checkbox-option">
					<input type="checkbox" id="qualif-categorie" name="qualification_est_statut">
					<span>C’est un statut (ex. Diplômé, Stagiaire, Non diplômé)</span>
				</label>
				<div class="field"><label for="qualif-categorie-parent">Statut validé par ce diplôme</label><select id="qualif-categorie-parent"></select></div>
				<div class="field" id="qualif-icone-field"><label for="qualif-icone">Icône dans le planning</label><select id="qualif-icone">${optionsIcones()}</select></div>
				<p class="form-error" id="qualif-error"></p>
				<button class="btn btn-primary" id="qualif-submit" type="button">Ajouter</button>
			</div>
		`;

		const list = container.querySelector("#qualifs-list");
		const input = container.querySelector("#qualif-nom");
		const autoEl = container.querySelector("#qualif-auto");
		const estCategorieEl = container.querySelector("#qualif-categorie");
		const categorieEl = container.querySelector("#qualif-categorie-parent");
		const iconeEl = container.querySelector("#qualif-icone");
		const iconeField = container.querySelector("#qualif-icone-field");
		const errorEl = container.querySelector("#qualif-error");

		function synchroniserChampsType(estStatut, parentField = null, iconField = null, iconSelect = null)
		{
			if (parentField) parentField.hidden = estStatut;
			if (iconField) iconField.hidden = estStatut;
			if (iconSelect && estStatut) iconSelect.value = "";
		}

		function optionsStatuts(valeur = null, qualificationExclueId = null)
		{
			return `<option value="">Aucun statut</option>${qualifications
				.filter((item) => item.est_statut && Number(item.id) !== Number(qualificationExclueId))
				.map((item) => `<option value="${item.id}" ${Number(valeur) === Number(item.id) ? "selected" : ""}>${escapeHtml(item.nom)}</option>`)
				.join("")}`;
		}

		function ouvrirEdition(q, row)
		{
			const nomId = `edit-qualification-${q.id}-nom`;
			const autoId = `edit-qualification-${q.id}-auto`;
			row.classList.add("entity-row-editing");
			row.innerHTML = `
				<div class="edit-grid edit-grid-single">
					<div class="field">
						<label for="${nomId}">Nom</label>
						<input type="text" id="${nomId}" name="qualification_${q.id}_nom" class="edit-qualif-nom" value="${escapeHtml(q.nom)}">
					</div>
					<label class="checkbox-option" for="${autoId}">
						<input type="checkbox" id="${autoId}" name="qualification_${q.id}_auto" class="edit-qualif-auto" ${q.selectionnable_remplissage_auto !== false ? "checked" : ""}>
						<span>Proposer dans le remplissage automatique</span>
					</label>
					<label class="checkbox-option"><input type="checkbox" class="edit-qualif-categorie" ${q.est_statut ? "checked" : ""}><span>C’est un statut</span></label>
					<div class="field edit-qualif-categorie-parent-field"><label>Statut validé par ce diplôme</label><select class="edit-qualif-categorie-parent">${optionsStatuts(q.statut_id, q.id)}</select></div>
					<div class="field edit-qualif-icone-field"><label>Icône dans le planning</label><select class="edit-qualif-icone">${optionsIcones(q.icone || "")}</select></div>
					<p class="form-error edit-error"></p>
				</div>
			`;

			const error = row.querySelector(".edit-error");
			const editCategorie = row.querySelector(".edit-qualif-categorie");
			const editParentField = row.querySelector(".edit-qualif-categorie-parent-field");
			const editIconField = row.querySelector(".edit-qualif-icone-field");
			const editIconSelect = row.querySelector(".edit-qualif-icone");
			synchroniserChampsType(editCategorie.checked, editParentField, editIconField, editIconSelect);
			editCategorie.addEventListener("change", () => synchroniserChampsType(editCategorie.checked, editParentField, editIconField, editIconSelect));
			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const nom = champValeur(row, ".edit-qualif-nom");
				const selectionnable_remplissage_auto = row.querySelector(".edit-qualif-auto").checked;
				const est_statut = row.querySelector(".edit-qualif-categorie").checked;
				const statut_id = est_statut ? null : (Number(row.querySelector(".edit-qualif-categorie-parent").value) || null);
				const icone = est_statut ? "" : row.querySelector(".edit-qualif-icone").value;

				if (!nom)
				{
					error.textContent = "Le nom est obligatoire.";
					return;
				}

				apiFetch(`/api/qualifications/${escapeHtml(q.id)}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom, selectionnable_remplissage_auto, est_statut, statut_id, icone }),
				}).then(() =>
				{
					afficherToast("Qualification modifiée.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Modification impossible."); });
			}, charger));
		}

		function charger()
		{
			return apiFetch("/api/qualifications/").then((data) =>
			{
				qualifications = data;
				list.innerHTML = "";
				categorieEl.innerHTML = optionsStatuts();

				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucun diplôme ou statut pour l\'instant.</p>';
					return data;
				}

				list.classList.add("diplomes-statuts-board");
				const statuts = data.filter((item) => item.est_statut);
				const diplomes = data.filter((item) => !item.est_statut);

				function ajouterActions(actions, item, support)
				{
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEdition(item, support)));
					actions.appendChild(bouton("&times; Supprimer", "btn-danger", () =>
					{
						if (!confirm(`Supprimer le diplôme ou statut "${escapeHtml(item.nom)}" ?`)) return;
						apiFetch(`/api/qualifications/${item.id}/`, { method: "DELETE" })
							.then(() => { afficherToast("Diplôme ou statut supprimé."); charger(); if (options.onChange) options.onChange(); })
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					}));
				}

				const bibliotheque = document.createElement("aside");
				bibliotheque.className = "diplomes-library";
				bibliotheque.innerHTML = `<header><strong>Tous les diplômes</strong><small>${diplomes.length} diplôme(s)</small></header><div class="diplomes-library-list"></div>`;
				const listeDiplomes = bibliotheque.querySelector(".diplomes-library-list");
				const grilleStatuts = document.createElement("div");
				grilleStatuts.className = "statuts-drop-grid";

				function rendreDepot(element, statut)
				{
					element.addEventListener("dragover", (event) => { event.preventDefault(); element.closest(".diplome-statut-zone, .diplomes-library")?.classList.add("drag-over"); });
					element.addEventListener("dragleave", () => element.closest(".diplome-statut-zone, .diplomes-library")?.classList.remove("drag-over"));
					element.addEventListener("drop", (event) =>
					{
						event.preventDefault();
						element.closest(".diplome-statut-zone, .diplomes-library")?.classList.remove("drag-over");
						const diplomeId = Number(event.dataTransfer.getData("text/plain"));
						const diplome = diplomes.find((item) => Number(item.id) === diplomeId);
						if (!diplome || Number(diplome.statut_id || 0) === Number(statut?.id || 0)) return;
						apiFetch(`/api/qualifications/${diplome.id}/`, { method: "PATCH", body: JSON.stringify({ statut_id: statut?.id || null }) })
							.then(() => { afficherToast(statut ? `${diplome.nom} ajouté à ${statut.nom}.` : `${diplome.nom} retiré de son statut.`); charger(); if (options.onChange) options.onChange(); })
							.catch((err) => afficherToast(erreurMessage(err, "Déplacement impossible."), true));
					});
				}

				diplomes.forEach((diplome) =>
				{
					const carte = document.createElement("article");
					carte.className = "diplome-drag-card diplome-library-card";
					carte.draggable = true;
					carte.innerHTML = `<div><strong>${badgeIcone(diplome)}${escapeHtml(diplome.nom)}</strong><small>${diplome.statut_nom ? escapeHtml(diplome.statut_nom) : "Sans statut"}</small></div><div class="entity-actions"></div>`;
					carte.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/plain", String(diplome.id)); event.dataTransfer.effectAllowed = "move"; });
					ajouterActions(carte.querySelector(".entity-actions"), diplome, carte);
					listeDiplomes.appendChild(carte);
				});
				rendreDepot(listeDiplomes, null);
				list.appendChild(bibliotheque);

				statuts.forEach((statut) =>
				{
					const zone = document.createElement("section");
					zone.className = "diplome-statut-zone";
					zone.dataset.statutId = statut.id || "";
					zone.innerHTML = `<header class="diplome-statut-head"><div><strong>${escapeHtml(statut.nom)}</strong><small>${diplomes.filter((diplome) => Number(diplome.statut_id || 0) === Number(statut.id || 0)).length} diplôme(s)</small></div><div class="entity-actions"></div></header><div class="diplome-statut-dropzone"></div>`;
					if (statut.id) ajouterActions(zone.querySelector(".entity-actions"), statut, zone.querySelector(".diplome-statut-head"));

					const depot = zone.querySelector(".diplome-statut-dropzone");
					rendreDepot(depot, statut);

					diplomes.filter((diplome) => Number(diplome.statut_id || 0) === Number(statut.id || 0)).forEach((diplome) =>
					{
						const carte = document.createElement("article");
						carte.className = "diplome-drag-card diplome-statut-member";
						carte.draggable = true;
						carte.innerHTML = `<div><strong>${badgeIcone(diplome)}${escapeHtml(diplome.nom)}</strong><small>${diplome.selectionnable_remplissage_auto ? "Proposé en auto" : "Masqué en auto"}</small></div>`;
						carte.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/plain", String(diplome.id)); event.dataTransfer.effectAllowed = "move"; });
						depot.appendChild(carte);
					});
					if (!depot.children.length) depot.innerHTML = '<span class="diplome-drop-empty">Dépose un diplôme ici</span>';
					grilleStatuts.appendChild(zone);
				});
				if (!statuts.length) grilleStatuts.innerHTML = '<p class="empty-note">Crée un statut pour pouvoir y déposer des diplômes.</p>';
				list.appendChild(grilleStatuts);

				return data;
			});
		}

		synchroniserChampsType(estCategorieEl.checked, categorieEl.closest(".field"), iconeField, iconeEl);
		estCategorieEl.addEventListener("change", () => synchroniserChampsType(estCategorieEl.checked, categorieEl.closest(".field"), iconeField, iconeEl));

		container.querySelector("#qualif-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = input.value.trim();
			const selectionnable_remplissage_auto = autoEl.checked;
			const est_statut = estCategorieEl.checked;
			const statut_id = est_statut ? null : (Number(categorieEl.value) || null);
			const icone = est_statut ? "" : iconeEl.value;

			if (!nom)
			{
				errorEl.textContent = "Le nom est obligatoire.";
				return;
			}

			apiFetch("/api/qualifications/", { method: "POST", body: JSON.stringify({ nom, selectionnable_remplissage_auto, est_statut, statut_id, icone }) })
				.then((nouvelle) =>
				{
					input.value = "";
					autoEl.checked = true;
					estCategorieEl.checked = false;
					categorieEl.value = "";
					iconeEl.value = "";
					synchroniserChampsType(false, categorieEl.closest(".field"), iconeField, iconeEl);
					afficherToast("Qualification ajoutée.");
					charger();
					if (options.onChange) options.onChange(nouvelle);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce diplôme ou statut."); });
		});

		charger();
		return { charger };
	}

	// ------------------------------------------------------------------
	// Groupes partagés
	// ------------------------------------------------------------------
	function mountGroupes(container)
	{
		container.innerHTML = `
			<div class="gestion-form" id="groupe-partage-form">
				<p class="section-title">Ajouter un groupe</p>
				<div class="edit-grid">
					<div class="field"><label>Nom</label><input class="shared-group-name" placeholder="ex : Maternelles"></div>
					<div class="field"><label>Enfants par animateur</label><input class="shared-group-ratio" type="number" min="1" max="999" value="8"></div>
				</div>
				<p class="form-error shared-group-error"></p>
				<button class="btn btn-primary shared-group-submit" type="button">Ajouter le groupe</button>
			</div>
			<p class="section-title">Groupes disponibles</p>
			<div class="team-list shared-groups-list"></div>`;

		const liste = container.querySelector(".shared-groups-list");
		const formulaire = container.querySelector("#groupe-partage-form");

		function payloadDepuis(root)
		{
			return {
				nom: root.querySelector(".shared-group-name").value.trim(),
				enfants_par_animateur_defaut: Number.parseInt(root.querySelector(".shared-group-ratio").value, 10) || 8,
			};
		}

		async function charger()
		{
			const groupes = await apiFetch("/api/groupes-partages/");
			liste.innerHTML = groupes.map((groupe) => `
				<div class="team-row" data-shared-group-id="${groupe.id}">
					<div class="team-main"><strong>${escapeHtml(groupe.nom)}</strong><div class="team-meta">
						<span>1 anim. / ${groupe.enfants_par_animateur_defaut} enfants</span>
						<span>${groupe.nombre_instances} instance${groupe.nombre_instances > 1 ? "s" : ""}</span>
						${groupe.lieux.length ? `<span>${escapeHtml(groupe.lieux.map((lieu) => lieu.nom).join(", "))}</span>` : ""}
					</div></div>
					<div class="team-actions"><button class="btn btn-ghost shared-group-edit" type="button">Modifier</button><button class="btn btn-danger-ghost shared-group-delete" type="button" ${groupe.nombre_instances ? "disabled" : ""}>Supprimer</button></div>
				</div>`).join("") || '<p class="empty-note">Aucun groupe pour l’instant.</p>';

			liste.querySelectorAll("[data-shared-group-id]").forEach((ligne) => {
				const groupe = groupes.find((item) => Number(item.id) === Number(ligne.dataset.sharedGroupId));
				ligne.querySelector(".shared-group-edit").addEventListener("click", () => {
					ligne.innerHTML = `<div class="team-form-grid"><div class="field"><label>Nom</label><input class="shared-group-name" value="${escapeHtml(groupe.nom)}"></div><div class="field"><label>Enfants par animateur</label><input class="shared-group-ratio" type="number" min="1" max="999" value="${groupe.enfants_par_animateur_defaut}"></div><p class="form-error shared-group-error"></p><div class="edit-actions"><button class="btn btn-primary shared-group-save" type="button">Enregistrer</button><button class="btn btn-ghost shared-group-cancel" type="button">Annuler</button></div></div>`;
					ligne.querySelector(".shared-group-cancel").addEventListener("click", charger);
					ligne.querySelector(".shared-group-save").addEventListener("click", () => {
						apiFetch(`/api/groupes-partages/${groupe.id}/`, { method: "PATCH", body: JSON.stringify(payloadDepuis(ligne)) })
							.then(() => { afficherToast("Groupe modifié dans tous ses lieux."); charger(); })
							.catch((err) => { ligne.querySelector(".shared-group-error").textContent = erreurMessage(err, "Modification impossible."); });
					});
				});
				ligne.querySelector(".shared-group-delete").addEventListener("click", () => {
					if (!confirm(`Supprimer le groupe « ${groupe.nom} » ?`)) return;
					apiFetch(`/api/groupes-partages/${groupe.id}/`, { method: "DELETE" }).then(charger)
						.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
				});
			});
		}

		charger();
		formulaire.querySelector(".shared-group-submit").addEventListener("click", () => {
			const payload = payloadDepuis(formulaire);
			if (!payload.nom) { formulaire.querySelector(".shared-group-error").textContent = "Le nom est obligatoire."; return; }
			apiFetch("/api/groupes-partages/", { method: "POST", body: JSON.stringify(payload) }).then(() => {
				formulaire.querySelector(".shared-group-name").value = "";
				afficherToast("Groupe ajouté.");
				charger();
			}).catch((err) => { formulaire.querySelector(".shared-group-error").textContent = erreurMessage(err, "Ajout impossible."); });
		});
		return { charger };
	}

	// ------------------------------------------------------------------
	// Lieux et instances de groupes
	// ------------------------------------------------------------------
	function mountCentres(container, options = {})
	{
		let qualificationsEvenements = [];
		let periodesScolaires = [];
		let groupesPartages = [];
		container.innerHTML = `
			<p class="section-title">Ajouter un lieu</p>
			<div class="gestion-form gestion-form--inline" id="lieu-form">
				<div class="edit-grid">
					<div class="field">
						<label for="lieu-nom">Nom</label>
						<input type="text" id="lieu-nom" name="lieu_nom" placeholder="ex : Pacaudière">
					</div>
					<div class="field">
						<label for="lieu-code">Code</label>
						<input type="text" id="lieu-code" name="lieu_code" placeholder="ex : PAC" maxlength="10">
					</div>
					<div class="field">
						<label for="lieu-couleur">Couleur</label>
						<input type="color" id="lieu-couleur" name="lieu_couleur" value="#1f6f54">
					</div>
				</div>
				<p class="form-error" id="lieu-error"></p>
				<button class="btn btn-primary" id="lieu-submit" type="button">Ajouter le lieu</button>
			</div>
			<p class="section-title">Lieux</p>
			<div class="lieux-cards" id="lieux-list"></div>
		`;

		const list = container.querySelector("#lieux-list");
		const nomEl = container.querySelector("#lieu-nom");
		const codeEl = container.querySelector("#lieu-code");
		const couleurEl = container.querySelector("#lieu-couleur");
		const errorEl = container.querySelector("#lieu-error");

		const JOURS_EVENEMENT = [
			{ numero: 0, court: "Lun", long: "Lundi" },
			{ numero: 1, court: "Mar", long: "Mardi" },
			{ numero: 2, court: "Mer", long: "Mercredi" },
			{ numero: 3, court: "Jeu", long: "Jeudi" },
			{ numero: 4, court: "Ven", long: "Vendredi" },
			{ numero: 5, court: "Sam", long: "Samedi" },
			{ numero: 6, court: "Dim", long: "Dimanche" },
		];

		function periodesFormHtml(uid, prefix, groupe = null)
		{
			if (!periodesScolaires.length)
				return '<p class="empty-note">Aucune période enregistrée. Le groupe peut tout de même être créé et configuré plus tard.</p>';

			const selectionnees = new Set(
				groupe ? (groupe.periode_ids || []).map(Number) : []
			);
						return grouperPeriodesParAnnee(periodesScolaires).map(({ annee, periodes }) =>
			{
				const zones = new Map();
				periodes.forEach((periode) =>
				{
					const zone = String(periode.zone || "Sans zone");
					if (!zones.has(zone)) zones.set(zone, []);
					zones.get(zone).push(periode);
				});
				const nbSelectionnees = periodes.filter((periode) => selectionnees.has(Number(periode.id))).length;

				return `
					<details class="period-year-accordion group-period-year" data-period-year="${escapeHtml(annee)}">
						<summary>
							<span class="period-year-summary"><strong>${escapeHtml(annee)}</strong><small class="group-period-year-count">${nbSelectionnees}/${periodes.length} sélectionnée${nbSelectionnees > 1 ? "s" : ""}</small></span>
							<span class="period-year-chevron" aria-hidden="true">⌄</span>
						</summary>
						<div class="period-year-content">
							${[...zones.entries()].map(([zone, elements]) => `
								<section class="period-zone-block">
									<div class="period-zone-head">
										<strong>Zone ${escapeHtml(zone)}</strong>
										<button type="button" class="period-zone-toggle" data-zone-action="toggle">Tout sélectionner</button>
									</div>
									<div class="group-period-grid period-year-list">
										${elements.map((periode) => {
											const id = `${uid}-periode-${periode.id}`;
											return `<label class="group-period-option" for="${id}" title="${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}">
												<input type="checkbox" id="${id}" name="${uid}_periode_${periode.id}" class="${prefix}-periode" value="${periode.id}" ${selectionnees.has(Number(periode.id)) ? "checked" : ""}>
												<span><strong>${escapeHtml(periode.nom || libellePeriodeAvecAnnee(periode))}</strong><small>${escapeHtml(libelleDate(periode.debut))}–${escapeHtml(libelleDate(periode.fin))}</small></span>
											</label>`;
										}).join("")}
									</div>
								</section>
							`).join("")}
						</div>
					</details>`;
			}).join("");
		}

		function evenementFormHtml(prefix, groupe = null)
		{
			const uid = identifiantChamp(`groupe-${groupe?.id || "nouveau"}`);
			const nomId = `${uid}-nom`;
			const effectifId = `${uid}-effectif`;
			const feriesId = `${uid}-feries`;
			const permanentId = `${uid}-permanent`;
			const joursSelectionnes = new Set(
				(groupe?.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number)
			);
			const optionsGroupes = groupesPartages.map((modele) =>
				`<option value="${modele.id}" ${Number(groupe?.groupe_id) === Number(modele.id) ? "selected" : ""}>${escapeHtml(modele.nom)} — 1/${modele.enfants_par_animateur_defaut}</option>`
			).join("");
			const valeursBesoins = groupe?.qualifications_requises || {};
			function blocBesoins(titre, elements, classe)
			{
				const champs = elements.map((qualification) => `
					<label class="qualification-requirement"><span>${escapeHtml(qualification.nom)}</span><input type="number" min="0" step="1" value="${valeursBesoins[String(qualification.id)] || 0}" data-qualification-id="${qualification.id}"></label>`).join("") || '<span class="empty-note compact">Aucun élément</span>';
				return `<section class="besoin-type-block ${classe}"><strong class="besoin-type-title">${titre}</strong><div class="besoin-type-fields">${champs}</div></section>`;
			}
			const besoinsHtml = `<div class="besoins-diplomes-statuts">${blocBesoins("Statuts", qualificationsEvenements.filter((item) => item.est_statut), "besoin-type-block--statuts")}${blocBesoins("Diplômes", qualificationsEvenements.filter((item) => !item.est_statut), "besoin-type-block--diplomes")}</div>`;

			const joursHtml = JOURS_EVENEMENT.map((jour) => {
				const id = `${uid}-jour-${jour.numero}`;
				return `<label class="group-weekday-option" for="${id}">
					<input type="checkbox" id="${id}" name="${uid}_jour_${jour.numero}" class="${prefix}-jour-ouvert" value="${jour.numero}" ${joursSelectionnes.has(jour.numero) ? "checked" : ""}>
					<span title="${escapeHtml(jour.long)}">${escapeHtml(jour.court)}</span>
				</label>`;
			}).join("");

			return `
				<div class="team-form-grid">
					<div class="field team-name-field"><label for="${nomId}">Groupe</label><select id="${nomId}" class="${prefix}-groupe-id" ${groupe ? "disabled" : ""}><option value="">Choisir un groupe</option>${optionsGroupes}</select></div>
				</div>
				<section class="event-opening-settings">
					<label class="checkbox-option group-permanent-option" for="${permanentId}"><input type="checkbox" id="${permanentId}" name="${uid}_permanent" class="${prefix}-permanent" ${groupe?.permanent ? "checked" : ""}><span><strong>Groupe permanent</strong></span></label>
					<div class="${prefix}-period-settings">
					<div class="event-setting-heading"><strong>Périodes ouvertes</strong><span>Pour une instance non permanente, aucune période n’est ouverte par défaut ; sans période elle reste masquée du planning.</span></div>
					<div class="group-period-actions">
						<button type="button" class="btn btn-ghost ${prefix}-periods-all">Tout cocher</button>
						<button type="button" class="btn btn-ghost ${prefix}-periods-none">Tout décocher</button>
					</div>
					<div class="group-periods">${periodesFormHtml(uid, prefix, groupe)}</div>
					</div>
					<div class="event-setting-heading"><strong>Jours ouverts</strong><span>Lundi à samedi ouverts par défaut ; dimanche fermé.</span></div>
					<div class="group-weekdays">${joursHtml}</div>
					<div class="group-closure-options">
						<label class="checkbox-option" for="${feriesId}"><input type="checkbox" id="${feriesId}" name="${uid}_ferme_jours_feries" class="${prefix}-ferme-feries" ${groupe?.ferme_jours_feries !== false ? "checked" : ""}><span>Fermé les jours fériés</span></label>
					</div>
				</section>
				<section class="event-staffing-settings">
					<div class="event-setting-heading"><strong>Personnel requis par jour</strong><span>Ce nombre est propre à cette instance dans ce lieu.</span></div>
					<div class="staffing-requirements-grid">
						<label class="staffing-total" for="${effectifId}"><span>Nombre total</span><input type="number" id="${effectifId}" name="${uid}_effectif" class="${prefix}-effectif" value="${groupe?.effectif_cible || 1}" min="1" step="1"></label>
					</div>
					<div class="event-setting-heading event-setting-heading--needs"><strong>Besoins propres à cette instance</strong><span>Choisis les statuts et diplômes nécessaires uniquement pour ce lieu.</span></div>
					${besoinsHtml}
				</section>
				<p class="form-error ${prefix}-error"></p>`;
		}

		function initialiserFormGroupe(root, prefix)
		{
			const permanentInput = root.querySelector(`.${prefix}-permanent`);
			const periodSettings = root.querySelector(`.${prefix}-period-settings`);

			function actualiserModePermanent()
			{
				const permanent = Boolean(permanentInput?.checked);
				if (periodSettings)
				{
					periodSettings.hidden = permanent;
					periodSettings.setAttribute("aria-hidden", permanent ? "true" : "false");
				}
			}

			function actualiserCompteursAnnees()
			{
				root.querySelectorAll(".group-period-year").forEach((details) =>
				{
					const cases = [...details.querySelectorAll(`.${prefix}-periode`)];
					const nb = cases.filter((input) => input.checked).length;
					const compteur = details.querySelector(".group-period-year-count");
					if (compteur) compteur.textContent = `${nb}/${cases.length} sélectionnée${nb > 1 ? "s" : ""}`;
				});
			}

			root.querySelector(`.${prefix}-periods-all`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = true; });
				actualiserCompteursAnnees();
			});
			root.querySelector(`.${prefix}-periods-none`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = false; });
				actualiserCompteursAnnees();
			});
			root.querySelectorAll(`.${prefix}-periode`).forEach((input) =>
				input.addEventListener("change", actualiserCompteursAnnees)
			);
			root.querySelectorAll('[data-zone-action="toggle"]').forEach((button) => {
				button.addEventListener("click", () => {
					const zone = button.closest(".period-zone-block");
					const cases = [...(zone?.querySelectorAll(`.${prefix}-periode`) || [])];
					const toutCoche = cases.length > 0 && cases.every((input) => input.checked);
					cases.forEach((input) => { input.checked = !toutCoche; });
					button.textContent = toutCoche ? "Tout sélectionner" : "Tout retirer";
					actualiserCompteursAnnees();
				});
			});
			permanentInput?.addEventListener("change", actualiserModePermanent);
			actualiserModePermanent();
			actualiserCompteursAnnees();
		}

		function lireEvenementForm(root, prefix)
		{
			const permanent = Boolean(root.querySelector(`.${prefix}-permanent`)?.checked);
			const groupeId = Number(root.querySelector(`.${prefix}-groupe-id`)?.value || 0);
			const modele = groupesPartages.find((item) => Number(item.id) === groupeId);
			const besoins = {};
			root.querySelectorAll("[data-qualification-id]").forEach((input) =>
			{
				const nombre = Number.parseInt(input.value, 10) || 0;
				if (nombre > 0) besoins[input.dataset.qualificationId] = nombre;
			});
			return {
				groupe_id: groupeId,
				nom: modele?.nom || "",
				permanent,
				periode_ids: permanent ? [] : Array.from(root.querySelectorAll(`.${prefix}-periode:checked`)).map((input) => Number(input.value)),
				effectif_cible: parseInt(champValeur(root, `.${prefix}-effectif`), 10) || 1,
				jours_ouverts: Array.from(root.querySelectorAll(`.${prefix}-jour-ouvert:checked`)).map((input) => Number(input.value)),
				ferme_jours_feries: root.querySelector(`.${prefix}-ferme-feries`).checked,
				qualifications_requises: besoins,
			};
		}

		function periodeLibelle(groupe)
		{
			if (groupe.permanent) return "Permanent — ouvert à toutes les périodes";
			const periodes = groupe.periodes || [];
			if (!periodes.length) return "Aucune période — masqué des calendriers";
			if (periodes.length === 1) return periodes[0].nom;
			return `${periodes.length} périodes sélectionnées`;
		}

		function joursOuvertureLibelle(groupe)
		{
			const noms = new Map(JOURS_EVENEMENT.map((jour) => [jour.numero, jour.court]));
			const jours = (groupe.jours_ouverts || []).map(Number).sort((a, b) => a - b);
			const libelle = jours.length === 7 ? "Tous les jours" : jours.map((jour) => noms.get(jour)).join(" · ");
			return groupe.ferme_jours_feries ? `${libelle} · jours fériés fermés` : `${libelle} · jours fériés ouverts`;
		}

		function couleurTexteLisible(couleur)
		{
			const valeur = String(couleur || "#1f6f54").trim();
			const court = /^#([0-9a-f]{3})$/i.exec(valeur);
			const long = /^#([0-9a-f]{6})$/i.exec(valeur);
			let hex = long?.[1];
			if (court) hex = court[1].split("").map((caractere) => caractere + caractere).join("");
			if (!hex) return "#ffffff";

			const composantes = [0, 2, 4].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255);
			const lineaires = composantes.map((valeurCouleur) =>
				valeurCouleur <= 0.03928 ? valeurCouleur / 12.92 : Math.pow((valeurCouleur + 0.055) / 1.055, 2.4)
			);
			const luminance = 0.2126 * lineaires[0] + 0.7152 * lineaires[1] + 0.0722 * lineaires[2];
			return luminance > 0.48 ? "#17211b" : "#ffffff";
		}

		function appliquerCouleurLieu(card, couleur)
		{
			const valeur = couleur || "#1f6f54";
			card.style.setProperty("--lieu-color", valeur);
			card.style.setProperty("--lieu-contrast", couleurTexteLisible(valeur));
		}

		function ouvrirEditionLieu(c, card)
		{
			const nomId = `edit-lieu-${c.id}-nom`;
			const codeId = `edit-lieu-${c.id}-code`;
			const couleurId = `edit-lieu-${c.id}-couleur`;
			const header = card.querySelector(".lieu-card-header");
			header.innerHTML = `
				<div class="lieu-edit-grid">
					<div class="field"><label for="${nomId}">Nom</label><input type="text" id="${nomId}" name="lieu_${c.id}_nom" class="edit-lieu-nom" value="${escapeHtml(c.nom)}"></div>
					<div class="field"><label for="${codeId}">Code</label><input type="text" id="${codeId}" name="lieu_${c.id}_code" class="edit-lieu-code" value="${escapeHtml(c.code)}" maxlength="10"></div>
					<div class="field"><label for="${couleurId}">Couleur</label><input type="color" id="${couleurId}" name="lieu_${c.id}_couleur" class="edit-lieu-couleur" value="${escapeHtml(c.couleur)}"></div>
					<div class="lieu-total-readonly"><span>Effectif global</span><strong>${escapeHtml(c.effectif_cible)}</strong></div>
					<p class="form-error edit-lieu-error"></p>
				</div>
			`;
			const error = header.querySelector(".edit-lieu-error");
			const couleurInput = header.querySelector(".edit-lieu-couleur");
			couleurInput.addEventListener("input", () => appliquerCouleurLieu(card, couleurInput.value));
			header.appendChild(creerFormActions(() =>
			{
				const nom = champValeur(header, ".edit-lieu-nom");
				const code = champValeur(header, ".edit-lieu-code");
				const couleur = champValeur(header, ".edit-lieu-couleur");
				if (!nom || !code)
				{
					error.textContent = "Le nom et le code sont obligatoires.";
					return;
				}
				apiFetch(`/api/centres/${c.id}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom, code, couleur }),
				}).then(() =>
				{
					afficherToast("Lieu modifié.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Modification impossible."); });
			}, charger));
		}


		function enregistrerOrdre(lieu, ids)
		{
			apiFetch(`/api/centres/${lieu.id}/groupes/reordonner/`, {
				method: "POST",
				body: JSON.stringify({ evenement_ids: ids }),
			}).then(() =>
			{
				afficherToast("Ordre des groupes enregistré.");
				charger();
			}).catch((err) => afficherToast(erreurMessage(err, "Réorganisation impossible."), true));
		}

		function deplacerEvenement(lieu, evenements, index, direction)
		{
			const destination = index + direction;
			if (destination < 0 || destination >= evenements.length) return;
			const ids = evenements.map((evenement) => evenement.id);
			[ids[index], ids[destination]] = [ids[destination], ids[index]];
			enregistrerOrdre(lieu, ids);
		}

		function enregistrerEvenement(url, method, payload, error, onSuccess)
		{
			apiFetch(url, { method, body: JSON.stringify(payload) })
				.then(onSuccess)
				.catch((err) =>
				{
					if (err?.code === "affectations_dates_fermees")
					{
						const dates = (err.dates || []).map(libelleDate).join(", ");
						const message = `${err.error}\n\nDates concernées : ${dates || "voir le planning"}.\n\nConfirmer la fermeture et supprimer ces affectations ?`;
						if (confirm(message))
						{
							const confirmation = { ...payload, supprimer_affectations_dates_fermees: true };
							enregistrerEvenement(url, method, confirmation, error, onSuccess);
						}
						return;
					}
					error.textContent = erreurMessage(err, "Enregistrement impossible.");
				});
		}

		function ouvrirEditionEvenement(evenement, lieu, row)
		{
			row.classList.add("team-row-editing");
			row.innerHTML = evenementFormHtml("edit-team", evenement);
			initialiserFormGroupe(row, "edit-team");
			const error = row.querySelector(".edit-team-error");
			row.appendChild(creerFormActions(() =>
			{
				const payload = lireEvenementForm(row, "edit-team");
				if (!payload.groupe_id || payload.jours_ouverts.length === 0)
				{
					error.textContent = "Le nom et au moins un jour d’ouverture sont obligatoires.";
					return;
				}
				enregistrerEvenement(`/api/groupes/${evenement.id}/`, "PATCH", payload, error, () =>
				{
					afficherToast("Groupe modifié.");
					charger();
					if (options.onChange) options.onChange();
				});
			}, charger));
		}

		function chargerEvenements(c, card)
		{
			const teamList = card.querySelector(".team-list");
			return apiFetch(`/api/centres/${c.id}/groupes/`).then((evenements) =>
			{
				teamList.innerHTML = "";
				evenements.forEach((evenement, index) =>
				{
					const row = document.createElement("div");
					row.className = "team-row";
					row.dataset.evenementId = evenement.id;
					row.innerHTML = `
						<div class="team-main">
							<div class="team-title-line">
								<strong>${escapeHtml(evenement.nom)}</strong>
							</div>
							<div class="team-meta">
								<span>${evenement.effectif_cible} animateur${evenement.effectif_cible > 1 ? "s" : ""}</span>
								<span>1 anim. / ${evenement.enfants_par_animateur_defaut || 8} enfants</span>
								<span>${escapeHtml(periodeLibelle(evenement))}</span>
								<span>${escapeHtml(joursOuvertureLibelle(evenement))}</span>
								${(evenement.dates_exclues || []).length ? `<span>${evenement.dates_exclues.length} fermeture${evenement.dates_exclues.length > 1 ? "s" : ""}</span>` : ""}
								${(evenement.qualifications_libelle || []).length ? `<span>${escapeHtml(evenement.qualifications_libelle.join(", "))}</span>` : ""}
								${evenement.nb_affectations ? `<span>${evenement.nb_affectations} affectation${evenement.nb_affectations > 1 ? "s" : ""}</span>` : ""}
							</div>
						</div>
						<div class="team-actions"></div>
					`;
					const actions = row.querySelector(".team-actions");
					actions.appendChild(bouton("↑", "btn btn-icon btn-ghost", () => deplacerEvenement(c, evenements, index, -1)));
					actions.lastChild.disabled = index === 0;
					actions.appendChild(bouton("↓", "btn btn-icon btn-ghost", () => deplacerEvenement(c, evenements, index, 1)));
					actions.lastChild.disabled = index === evenements.length - 1;
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEditionEvenement(evenement, c, row)));
					const supprimer = bouton("Supprimer", "btn btn-danger-ghost", () =>
					{
						if (!confirm(`Supprimer le groupe « ${evenement.nom} » ?`)) return;
						apiFetch(`/api/groupes/${evenement.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Groupe supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					});
					supprimer.disabled = !evenement.peut_supprimer;
					if (!evenement.peut_supprimer)
					{
						supprimer.title = "Ce groupe contient des affectations.";
					}
					actions.appendChild(supprimer);
					teamList.appendChild(row);
				});
				return evenements;
			}).catch((err) =>
			{
				teamList.innerHTML = `<p class="form-error gestion-load-error">${escapeHtml(erreurMessage(err, "Impossible de recharger les groupes de ce lieu."))}</p>`;
				throw err;
			});
		}

		function creerCarteLieu(c)
		{
			const card = document.createElement("section");
			card.className = "lieu-card";
			appliquerCouleurLieu(card, c.couleur);
			card.innerHTML = `
				<div class="lieu-card-header">
					<div class="lieu-card-identity">
						<span class="swatch lieu-swatch" style="background:${escapeHtml(c.couleur)}"></span>
						<div><h3>${escapeHtml(c.nom)}</h3><span class="lieu-code">${escapeHtml(c.code)}</span></div>
					</div>
					<div class="lieu-summary"><strong>${escapeHtml(c.effectif_cible)}</strong><span>animateur${c.effectif_cible > 1 ? "s" : ""} / jour</span></div>
					<div class="lieu-actions"></div>
				</div>
				<div class="lieu-teams-block">
					<div class="teams-heading">
						<div><h4>Instances de groupes</h4><p>Chaque instance possède son nombre d’animateurs et son calendrier.</p></div>
						<button type="button" class="btn btn-secondary team-add-toggle">+ Attribuer un groupe</button>
					</div>
					<div class="team-list"><p class="empty-note">Chargement…</p></div>
					<div class="team-create-form" hidden></div>
				</div>
			`;

			const actions = card.querySelector(".lieu-actions");
			actions.appendChild(bouton("Modifier le lieu", "btn btn-ghost", () => ouvrirEditionLieu(c, card)));
			actions.appendChild(bouton("Supprimer le lieu", "btn btn-danger-ghost", () =>
			{
				if (!confirm(`Supprimer le lieu « ${c.nom} » ?`)) return;
				apiFetch(`/api/centres/${c.id}/`, { method: "DELETE" })
					.then(() =>
					{
						afficherToast("Lieu supprimé.");
						charger();
						if (options.onChange) options.onChange();
					})
					.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
			}));

			const form = card.querySelector(".team-create-form");
			function initialiserCreationInstance()
			{
				if (form.dataset.initialise) return;
				form.dataset.initialise = "1";
				form.innerHTML = `${evenementFormHtml("new-team")}<div class="edit-actions"><button type="button" class="btn btn-primary team-create-submit">Créer l’instance</button><button type="button" class="btn btn-ghost team-create-cancel">Annuler</button></div>`;
				initialiserFormGroupe(form, "new-team");
				form.querySelector(".team-create-cancel").addEventListener("click", () => { form.hidden = true; });
				form.querySelector(".team-create-submit").addEventListener("click", () =>
				{
					const error = form.querySelector(".new-team-error");
					error.textContent = "";
					const payload = lireEvenementForm(form, "new-team");
					if (!payload.groupe_id || payload.jours_ouverts.length === 0)
					{
						error.textContent = "Choisis un groupe et au moins un jour d’ouverture.";
						return;
					}
					apiFetch(`/api/centres/${c.id}/groupes/`, { method: "POST", body: JSON.stringify(payload) })
						.then(() => { afficherToast("Groupe ajouté."); charger(); if (options.onChange) options.onChange(); })
						.catch((err) => { error.textContent = erreurMessage(err, "Ajout impossible."); });
				});
			}
			card.querySelector(".team-add-toggle").addEventListener("click", () =>
			{
				initialiserCreationInstance();
				form.hidden = !form.hidden;
					if (!form.hidden) form.querySelector(".new-team-groupe-id").focus();
			});

			chargerEvenements(c, card);
			return card;
		}

		function charger()
		{
			list.setAttribute("aria-busy", "true");
			return apiFetch("/api/centres/").then((data) =>
			{
				const contenu = document.createDocumentFragment();
				if (data.length === 0)
				{
					const vide = document.createElement("p");
					vide.className = "empty-note";
					vide.textContent = "Aucun lieu pour l’instant.";
					contenu.appendChild(vide);
				}
				else
				{
					data.forEach((lieu) => contenu.appendChild(creerCarteLieu(lieu)));
				}

				// Ne remplace l'ancien affichage qu'une fois le nouveau construit.
				// Ainsi, une erreur réseau ne laisse jamais la page Gestion vide.
				list.replaceChildren(contenu);
				return data;
			}).catch((err) =>
			{
				afficherToast(erreurMessage(err, "Impossible de recharger les lieux et groupes."), true);
				if (!list.children.length)
				{
					list.innerHTML = '<p class="form-error gestion-load-error">Impossible de charger les lieux et groupes. Recharge la page pour réessayer.</p>';
				}
				throw err;
			}).finally(() =>
			{
				list.removeAttribute("aria-busy");
			});
		}

		container.querySelector("#lieu-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = nomEl.value.trim();
			const code = codeEl.value.trim();
			const couleur = couleurEl.value;
			if (!nom || !code)
			{
				errorEl.textContent = "Le nom et le code sont obligatoires.";
				return;
			}
			apiFetch("/api/centres/", { method: "POST", body: JSON.stringify({ nom, code, couleur }) })
				.then((nouveau) =>
				{
					nomEl.value = "";
					codeEl.value = "";
					afficherToast("Lieu ajouté. Tu peux maintenant y créer un groupe.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d’ajouter ce lieu."); });
		});

		Promise.all([apiFetch("/api/qualifications/"), apiFetch("/api/periodes-scolaires/"), apiFetch("/api/groupes-partages/")])
			.then(([qualifications, periodes, groupes]) =>
			{
				qualificationsEvenements = qualifications;
				periodesScolaires = periodes;
				groupesPartages = groupes;
				return charger();
			})
			.catch((err) =>
			{
				if (!list.children.length)
					list.innerHTML = `<p class="form-error gestion-load-error">${escapeHtml(erreurMessage(err, "Impossible d'initialiser la gestion des lieux et groupes."))}</p>`;
			});
		return { charger };
	}


	// ------------------------------------------------------------------
	// Périodes scolaires indépendantes
	// ------------------------------------------------------------------
	function mountPeriodes(container)
	{
		function anneeScolaireParDefaut()
		{
			const maintenant = new Date();
			const anneeDebut = maintenant.getMonth() >= 6
				? maintenant.getFullYear()
				: maintenant.getFullYear() - 1;
			return `${anneeDebut}-${anneeDebut + 1}`;
		}

		container.innerHTML = `
			<div class="periods-intro">
				<div>
					<p class="section-title">Importer les vacances scolaires</p>
					
				</div>
				<span class="periods-independent-badge">Indépendant du planning</span>
			</div>

			<div class="gestion-form period-import-form">
				<div class="period-import-grid">
					<div class="field">
						<label for="period-school-year">Année scolaire</label>
						<input type="text" id="period-school-year" name="periode_annee_scolaire" maxlength="9" placeholder="2026-2027" value="${anneeScolaireParDefaut()}">
					</div>
					<div class="field">
						<label for="period-zone">Zone</label>
						<select id="period-zone" name="periode_zone">
							<option value="A">Zone A</option>
							<option value="B">Zone B</option>
							<option value="C">Zone C</option>
						</select>
					</div>
					<div class="period-import-action">
						<button class="btn btn-primary" id="period-preview-button" type="button">Rechercher les périodes</button>
					</div>
				</div>
				<p class="form-error" id="period-import-error"></p>
			</div>

			<div id="period-preview-zone"></div>

			<div class="period-library-head">
				<div>
					<p class="section-title">Périodes enregistrées</p>
					
				</div>
				<div class="field period-library-filter">
					<label for="period-library-year">Afficher</label>
					<select id="period-library-year" name="periode_filtre_annee">
						<option value="">Toutes les années</option>
					</select>
				</div>
			</div>
			<div id="period-library" class="period-library"></div>
		`;

		const yearInput = container.querySelector("#period-school-year");
		const zoneInput = container.querySelector("#period-zone");
		const previewButton = container.querySelector("#period-preview-button");
		const errorEl = container.querySelector("#period-import-error");
		const previewZone = container.querySelector("#period-preview-zone");
		const library = container.querySelector("#period-library");
		const filterYear = container.querySelector("#period-library-year");
		let previewData = null;
		let savedPeriods = [];

		function payloadImport()
		{
			return {
				annee_scolaire: yearInput.value.trim(),
				zone: zoneInput.value,
			};
		}

		function rendrePreview(data)
		{
			previewData = data;
			const rows = data.periodes.map((periode) => `
				<tr>
					<td><strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong>${periode.deja_enregistree ? '<span class="period-existing">Déjà enregistrée</span>' : ""}</td>
					<td>${escapeHtml(libelleDate(periode.debut))}</td>
					<td>${escapeHtml(libelleDate(periode.fin))}</td>
				</tr>
			`).join("");

			previewZone.innerHTML = `
				<section class="period-preview-card">
					<div class="period-preview-head">
						<div>
							<h3>${escapeHtml(data.annee_scolaire)} — Zone ${escapeHtml(data.zone)}</h3>
							<p>${data.nombre} semaine${data.nombre > 1 ? "s" : ""} complète${data.nombre > 1 ? "s" : ""} trouvée${data.nombre > 1 ? "s" : ""}. Rien n'est enregistré tant que tu ne confirmes pas.</p>
						</div>
						<button class="btn btn-ghost" id="period-preview-close" type="button">Fermer</button>
					</div>
					<div class="period-table-wrap">
						<table class="period-table">
							<thead><tr><th>Période</th><th>Du lundi</th><th>Au vendredi</th></tr></thead>
							<tbody>${rows}</tbody>
						</table>
					</div>
					<div class="period-preview-actions">
						<button class="btn btn-primary" id="period-import-button" type="button">Enregistrer toutes les périodes</button>
						<p class="form-error" id="period-preview-error"></p>
					</div>
				</section>
			`;

			previewZone.querySelector("#period-preview-close").addEventListener("click", () =>
			{
				previewData = null;
				previewZone.innerHTML = "";
			});
			previewZone.querySelector("#period-import-button").addEventListener("click", importer);
		}

		async function previsualiser()
		{
			errorEl.textContent = "";
			previewButton.disabled = true;
			previewButton.textContent = "Recherche…";
			try
			{
				const data = await apiFetch("/api/periodes-scolaires/previsualiser/", {
					method: "POST",
					body: JSON.stringify(payloadImport()),
				});
				rendrePreview(data);
			}
			catch (err)
			{
				errorEl.textContent = erreurMessage(err, "Impossible de récupérer le calendrier scolaire.");
			}
			finally
			{
				previewButton.disabled = false;
				previewButton.textContent = "Rechercher les périodes";
			}
		}

		async function importer()
		{
			if (!previewData) return;
			const importButton = previewZone.querySelector("#period-import-button");
			const previewError = previewZone.querySelector("#period-preview-error");
			previewError.textContent = "";
			importButton.disabled = true;
			importButton.textContent = "Enregistrement…";
			try
			{
				const result = await apiFetch("/api/periodes-scolaires/importer/", {
					method: "POST",
					body: JSON.stringify(payloadImport()),
				});
				afficherToast(result.cree
					? `${result.cree} période${result.cree > 1 ? "s" : ""} enregistrée${result.cree > 1 ? "s" : ""}.`
					: "Toutes ces périodes étaient déjà enregistrées.");
				previewData = null;
				previewZone.innerHTML = "";
				await chargerBibliotheque();
			}
			catch (err)
			{
				previewError.textContent = erreurMessage(err, "Enregistrement impossible.");
				importButton.disabled = false;
				importButton.textContent = "Enregistrer toutes les périodes";
			}
		}

		function rendreBibliotheque()
		{
			const anneeFiltre = filterYear.value;
			const visibles = anneeFiltre
				? savedPeriods.filter((periode) => periode.annee_scolaire === anneeFiltre)
				: savedPeriods;

			library.innerHTML = "";
			if (!visibles.length)
			{
				library.innerHTML = '<p class="empty-note">Aucune période enregistrée pour le moment.</p>';
				return;
			}

			const anneeOuverte = anneeFiltre || anneePeriodesADeplier(visibles);
			grouperPeriodesParAnnee(visibles).forEach(({ annee, periodes }) =>
			{
				const zones = new Map();
				periodes.forEach((periode) =>
				{
					const zone = String(periode.zone || "Sans zone");
					if (!zones.has(zone)) zones.set(zone, []);
					zones.get(zone).push(periode);
				});

				const section = document.createElement("details");
				section.className = "period-year-card period-year-accordion";
				section.open = annee === anneeOuverte;
				section.innerHTML = `
					<summary>
						<span class="period-year-summary"><strong>${escapeHtml(annee)}</strong><small>${periodes.length} période${periodes.length > 1 ? "s" : ""} · ${zones.size} zone${zones.size > 1 ? "s" : ""}</small></span>
						<span class="period-year-chevron" aria-hidden="true">⌄</span>
					</summary>
					<div class="period-year-content period-library-year-content"></div>
				`;
				const content = section.querySelector(".period-library-year-content");

				[...zones.entries()].forEach(([zone, elements]) =>
				{
					const zoneSection = document.createElement("section");
					zoneSection.className = "period-zone-block";
					zoneSection.innerHTML = `
						<p class="period-zone-title">Zone ${escapeHtml(zone)}</p>
						<div class="period-saved-list"></div>
					`;
					const list = zoneSection.querySelector(".period-saved-list");

					elements.forEach((periode) =>
					{
						const row = document.createElement("div");
						row.className = "period-saved-row";
						row.innerHTML = `
							<div class="period-saved-date"><strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong><span>${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}</span></div>
							<div class="entity-actions"></div>
						`;
						row.querySelector(".entity-actions").appendChild(bouton("Supprimer", "btn btn-danger-ghost", async () =>
						{
							if (!confirm(`Supprimer la période « ${libellePeriodeAvecAnnee(periode)} » ?`)) return;
							try
							{
								await apiFetch(`/api/periodes-scolaires/${periode.id}/`, { method: "DELETE" });
								afficherToast("Période supprimée.");
								await chargerBibliotheque();
							}
							catch (err)
							{
								afficherToast(erreurMessage(err, "Suppression impossible."), true);
							}
						}));
						list.appendChild(row);
					});
					content.appendChild(zoneSection);
				});
				library.appendChild(section);
			});
		}

		async function chargerBibliotheque()
		{
			savedPeriods = await apiFetch("/api/periodes-scolaires/");
			const current = filterYear.value;
			const annees = [...new Set(savedPeriods.map((periode) => periode.annee_scolaire))].sort().reverse();
			filterYear.innerHTML = '<option value="">Toutes les années</option>' + annees.map((annee) => `<option value="${escapeHtml(annee)}">${escapeHtml(annee)}</option>`).join("");
			if (annees.includes(current)) filterYear.value = current;
			rendreBibliotheque();
		}

		previewButton.addEventListener("click", previsualiser);
		filterYear.addEventListener("change", rendreBibliotheque);
		chargerBibliotheque().catch((err) =>
		{
			library.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(err, "Impossible de charger les périodes."))}</p>`;
		});

		return { charger: chargerBibliotheque };
	}

	// ------------------------------------------------------------------
	return { mountCentres, mountGroupes, mountQualifications, mountPeriodes };
})();
