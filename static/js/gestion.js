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
				if (!statuts.length) grilleStatuts.innerHTML = '<p class="empty-note">Créez un statut pour pouvoir y déposer des diplômes.</p>';
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
		let centresGroupes = [];
		function porteeHtml(groupe = {}) {
			return `<div class="field"><label>Portée du groupe</label><select class="group-scope"><option value="LOCAL" ${groupe.portee !== "PARTAGE" ? "selected" : ""}>Local à un site</option><option value="PARTAGE" ${groupe.portee === "PARTAGE" ? "selected" : ""}>Partagé entre plusieurs sites</option></select></div><div class="field"><label>Centre de rattachement (groupe local)</label><select class="group-owner"><option value="">Choisir un centre</option>${centresGroupes.map((centre) => `<option value="${centre.id}" ${Number(groupe.centre_id) === Number(centre.id) ? "selected" : ""}>${escapeHtml(centre.nom)}</option>`).join("")}</select></div>`;
		}
		let typesAccueilStructure = [];
		container.innerHTML = `
			<div class="gestion-form" id="groupe-partage-form">
				<p class="section-title">Ajouter un groupe</p>
				<div class="edit-grid">
					<div class="field"><label>Nom</label><input class="shared-group-name" placeholder="ex : Maternelles"></div>
					<div class="field"><label>Type de groupe</label><select class="shared-group-kind"><option value="structure">Structurel</option><option value="sejour">Séjour temporaire</option></select></div>
					<div class="field"><label>Catégorie d’âge réglementaire</label><select class="shared-group-age"><option value="moins_6">Moins de 6 ans</option><option value="six_plus">6 ans et plus</option><option value="autre">Autre / non réglementaire</option></select></div>
					<div class="field"><label>Ratio manuel historique</label><input class="shared-group-ratio" type="number" min="1" max="999" value="8"></div>
					<div class="field shared-group-validity" hidden><label>Début du séjour</label><input class="shared-group-valid-from" type="date"></div>
					<div class="field shared-group-validity" hidden><label>Fin du séjour</label><input class="shared-group-valid-to" type="date"></div>
				</div>
				<div class="field shared-group-types-field"><span class="field-label">Utilisé pour le planning</span><div class="accueil-type-options shared-group-types"></div></div>
				<p class="form-error shared-group-error"></p>
				<button class="btn btn-primary shared-group-submit" type="button">Ajouter le groupe</button>
			</div>
			<p class="section-title">Groupes disponibles</p>
			<div class="team-list shared-groups-list"></div>`;

		const liste = container.querySelector(".shared-groups-list");
		const formulaire = container.querySelector("#groupe-partage-form");

		function typesAccueilHtml(prefix, selection = ["vacances"])
		{
			const actifs = new Set((selection || []).map(String));
			return typesAccueilStructure.map((type) => `<label class="accueil-type-option"><input type="checkbox" class="${prefix}-type-accueil" value="${escapeHtml(type.code)}" ${actifs.has(type.code) ? "checked" : ""}><span>${escapeHtml(type.nom)}</span></label>`).join("");
		}

		function actualiserTypesCreation()
		{
			const cible = formulaire.querySelector(".shared-group-types");
			if (cible) cible.innerHTML = typesAccueilHtml("shared-group", ["vacances"]);
		}

		function actualiserValidite(root)
		{
			const estSejour = root.querySelector(".shared-group-kind")?.value === "sejour";
			root.querySelectorAll(".shared-group-validity").forEach((field) => { field.hidden = !estSejour; });
		}

		function libelleStatutSejour(groupe)
		{
			if (groupe.statut_validite === "a_venir") return "À venir";
			if (groupe.statut_validite === "termine") return "Terminé";
			return "En cours";
		}

		function payloadDepuis(root)
		{
			const typeGroupe = root.querySelector(".shared-group-kind")?.value || "structure";
			return {
				nom: root.querySelector(".shared-group-name").value.trim(),
				portee: root.querySelector(".group-scope").value,
				centre_id: root.querySelector(".group-scope").value === "LOCAL" ? (root.querySelector(".group-owner").value || null) : null,
				type_groupe: typeGroupe,
				date_debut_validite: typeGroupe === "sejour" ? (root.querySelector(".shared-group-valid-from")?.value || "") : "",
				date_fin_validite: typeGroupe === "sejour" ? (root.querySelector(".shared-group-valid-to")?.value || "") : "",
				categorie_age_reglementaire: root.querySelector(".shared-group-age")?.value || "autre",
				enfants_par_animateur_defaut: Number.parseInt(root.querySelector(".shared-group-ratio").value, 10) || 8,
				type_accueil_codes: [...root.querySelectorAll(".shared-group-type-accueil:checked")].map((input) => input.value),
			};
		}

		async function charger()
		{
			const [groupes, centres] = await Promise.all([apiFetch("/api/groupes-partages/"), apiFetch("/api/centres/")]);
			centresGroupes = centres;
			if (!formulaire.querySelector(".group-scope")) formulaire.querySelector(".edit-grid").insertAdjacentHTML("beforeend", porteeHtml());
			liste.innerHTML = groupes.map((groupe) => `
				<div class="team-row ${groupe.type_groupe === "sejour" ? "shared-group-stay" : ""}" data-shared-group-id="${groupe.id}">
					<div class="team-main"><strong>${escapeHtml(groupe.nom)}</strong><div class="accueil-type-badges">${groupe.type_groupe === "sejour" ? `<span class="accueil-type-badge accueil-type-badge--stay">Séjour · ${escapeHtml(libelleStatutSejour(groupe))}</span>` : ""}${(groupe.types_accueil || []).map((type) => `<span class="accueil-type-badge">${escapeHtml(type.nom)}</span>`).join("")}</div><div class="team-meta">
						${groupe.type_groupe === "sejour" ? `<span>${escapeHtml(libelleDate(groupe.date_debut_validite))} → ${escapeHtml(libelleDate(groupe.date_fin_validite))}</span>` : ""}
						<span>${escapeHtml(groupe.categorie_age_reglementaire_libelle || "Catégorie non définie")}</span>
						<span>ratio manuel 1/${groupe.enfants_par_animateur_defaut}</span>
						<span>${groupe.portee === "LOCAL" ? `Local · ${escapeHtml(groupe.centre_nom || "")}` : "Partagé entre sites"}</span>
						<span>${groupe.nombre_instances} instance${groupe.nombre_instances > 1 ? "s" : ""}</span>
						${groupe.lieux.length ? `<span>${escapeHtml(groupe.lieux.map((lieu) => lieu.nom).join(", "))}</span>` : ""}
					</div></div>
					<div class="team-actions"><button class="btn btn-ghost shared-group-edit" type="button">Modifier</button><button class="btn btn-danger-ghost shared-group-delete" type="button" ${groupe.nombre_instances ? "disabled" : ""}>Supprimer</button></div>
				</div>`).join("") || '<p class="empty-note">Aucun groupe pour l’instant.</p>';

			liste.querySelectorAll("[data-shared-group-id]").forEach((ligne) => {
				const groupe = groupes.find((item) => Number(item.id) === Number(ligne.dataset.sharedGroupId));
				ligne.querySelector(".shared-group-edit").addEventListener("click", () => {
					ligne.innerHTML = `<div class="team-form-grid"><div class="field"><label>Nom</label><input class="shared-group-name" value="${escapeHtml(groupe.nom)}"></div><div class="field"><label>Type de groupe</label><select class="shared-group-kind"><option value="structure" ${groupe.type_groupe !== "sejour" ? "selected" : ""}>Structurel</option><option value="sejour" ${groupe.type_groupe === "sejour" ? "selected" : ""}>Séjour temporaire</option></select></div><div class="field"><label>Catégorie d’âge réglementaire</label><select class="shared-group-age"><option value="moins_6" ${groupe.categorie_age_reglementaire === "moins_6" ? "selected" : ""}>Moins de 6 ans</option><option value="six_plus" ${groupe.categorie_age_reglementaire === "six_plus" ? "selected" : ""}>6 ans et plus</option><option value="autre" ${groupe.categorie_age_reglementaire === "autre" ? "selected" : ""}>Autre / non réglementaire</option></select></div><div class="field"><label>Ratio manuel historique</label><input class="shared-group-ratio" type="number" min="1" max="999" value="${groupe.enfants_par_animateur_defaut}"></div><div class="field shared-group-validity" ${groupe.type_groupe === "sejour" ? "" : "hidden"}><label>Début du séjour</label><input class="shared-group-valid-from" type="date" value="${escapeHtml(groupe.date_debut_validite || "")}"></div><div class="field shared-group-validity" ${groupe.type_groupe === "sejour" ? "" : "hidden"}><label>Fin du séjour</label><input class="shared-group-valid-to" type="date" value="${escapeHtml(groupe.date_fin_validite || "")}"></div><div class="field shared-group-types-field"><span class="field-label">Utilisé pour le planning</span><div class="accueil-type-options">${typesAccueilHtml("shared-group", groupe.type_accueil_codes)}</div></div><p class="form-error shared-group-error"></p><div class="edit-actions"><button class="btn btn-primary shared-group-save" type="button">Enregistrer</button><button class="btn btn-ghost shared-group-cancel" type="button">Annuler</button></div></div>`;
					ligne.querySelector(".team-form-grid").insertAdjacentHTML("afterbegin", porteeHtml(groupe));
					ligne.querySelector(".shared-group-kind")?.addEventListener("change", () => actualiserValidite(ligne));
					ligne.querySelector(".shared-group-cancel").addEventListener("click", charger);
					ligne.querySelector(".shared-group-save").addEventListener("click", () => {
						const payload = payloadDepuis(ligne);
						if (payload.type_groupe === "sejour" && (!payload.date_debut_validite || !payload.date_fin_validite)) { ligne.querySelector(".shared-group-error").textContent = "Renseignez les dates de début et de fin du séjour."; return; }
						if (!payload.type_accueil_codes.length) { ligne.querySelector(".shared-group-error").textContent = "Choisissez au moins Vacances ou Périscolaire."; return; }
						apiFetch(`/api/groupes-partages/${groupe.id}/`, { method: "PATCH", body: JSON.stringify(payload) })
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

		formulaire.querySelector(".shared-group-kind")?.addEventListener("change", () => actualiserValidite(formulaire));
		apiFetch("/api/types-accueil/").then((types) => { typesAccueilStructure = types || []; actualiserTypesCreation(); actualiserValidite(formulaire); charger(); })
			.catch((err) => { liste.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(err, "Impossible de charger les types d’accueil."))}</p>`; });
		formulaire.querySelector(".shared-group-submit").addEventListener("click", () => {
			const payload = payloadDepuis(formulaire);
			if (!payload.nom) { formulaire.querySelector(".shared-group-error").textContent = "Le nom est obligatoire."; return; }
			if (payload.type_groupe === "sejour" && (!payload.date_debut_validite || !payload.date_fin_validite)) { formulaire.querySelector(".shared-group-error").textContent = "Renseignez les dates de début et de fin du séjour."; return; }
			if (!payload.type_accueil_codes.length) { formulaire.querySelector(".shared-group-error").textContent = "Choisissez au moins Vacances ou Périscolaire."; return; }
			apiFetch("/api/groupes-partages/", { method: "POST", body: JSON.stringify(payload) }).then(() => {
				formulaire.querySelector(".shared-group-name").value = "";
				formulaire.querySelector(".shared-group-kind").value = "structure";
				formulaire.querySelector(".shared-group-valid-from").value = "";
				formulaire.querySelector(".shared-group-valid-to").value = "";
				actualiserValidite(formulaire);
				actualiserTypesCreation();
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
		let typesAccueilStructure = [];
		let modalitesPeriscolaires = [];
		let periodesCalendrier = [];
		let periodesCalendrierScolaires = [];
		let lieuxDonnees = [];
		let carteLieuGlissee = null;
		const CLE_ETAT_LIEUX = "animation-manager:configuration-lieux";
		container.innerHTML = `
			<div class="centre-config-toolbar">
				<div><p class="section-title">Lieux & accueils</p></div>
				<button class="btn btn-primary" id="centre-wizard-new" type="button">+ Nouveau lieu</button>
			</div>
			<div class="lieux-navigation" aria-label="Rechercher et filtrer les lieux">
				<label class="lieux-search"><span class="sr-only">Recherche par nom, nom court ou commune</span><input type="search" id="lieux-search" placeholder="Rechercher un lieu, un nom court ou une commune"></label>
				<label class="lieux-filter"><span class="sr-only">Filtrer par accueil</span><select id="lieux-filter"><option value="tous">Tous les accueils</option></select></label>
			</div>
			<div id="centre-wizard-host" class="centre-wizard-host" hidden></div>
			<div class="lieux-cards" id="lieux-list"></div>
			<details class="centre-legacy-create">
				<summary>Création avancée</summary>
				<div class="gestion-form gestion-form--inline" id="lieu-form">
					<div class="edit-grid">
						<div class="field"><label for="lieu-nom">Nom</label><input type="text" id="lieu-nom" name="lieu_nom" placeholder="ex : Pacaudière"></div>
						<div class="field"><label for="lieu-code">Nom court ou abréviation</label><input type="text" id="lieu-code" name="lieu_code" placeholder="ex : PAC" maxlength="10"></div>
						<div class="field"><label for="lieu-couleur">Couleur</label><input type="color" id="lieu-couleur" name="lieu_couleur" value="#1f6f54"></div>
						<div class="field lieu-types-field"><span class="field-label">Utilisé pour</span><div class="accueil-type-options lieu-types"></div></div>
						<div class="lieu-location-fields" data-location-autocomplete>
							<div class="field"><label for="lieu-adresse">Adresse ou lieu-dit <small>(facultatif)</small></label><input type="text" id="lieu-adresse" name="lieu_adresse" autocomplete="street-address"></div>
							<div class="lieu-location-locality"><div class="field"><label for="lieu-code-postal">Code postal</label><input type="text" id="lieu-code-postal" name="lieu_code_postal" data-location-postal inputmode="numeric" maxlength="5" pattern="[0-9]{5}" placeholder="42640"></div><div class="field"><label for="lieu-commune">Commune</label><input type="text" id="lieu-commune" name="lieu_commune" data-location-city autocomplete="address-level2"></div></div>
							<div data-location-suggestions role="listbox" hidden></div><small data-location-status aria-live="polite"></small><input type="hidden" data-location-insee><input type="hidden" data-location-requested value="1">
						</div>
					</div>
					<p class="form-error" id="lieu-error"></p>
					<button class="btn btn-primary" id="lieu-submit" type="button">Ajouter le lieu</button>
				</div>
			</details>
		`;

		const list = container.querySelector("#lieux-list");
		const wizardHost = container.querySelector("#centre-wizard-host");
		const wizardNewButton = container.querySelector("#centre-wizard-new");
		const rechercheLieux = container.querySelector("#lieux-search");
		const filtreLieux = container.querySelector("#lieux-filter");
		const nomEl = container.querySelector("#lieu-nom");
		const codeEl = container.querySelector("#lieu-code");
		const couleurEl = container.querySelector("#lieu-couleur");
		const adresseEl = container.querySelector("#lieu-adresse");
		const codePostalEl = container.querySelector("#lieu-code-postal");
		const communeEl = container.querySelector("#lieu-commune");
		const codeInseeEl = container.querySelector("#lieu-form [data-location-insee]");
		const errorEl = container.querySelector("#lieu-error");
		initLocationAutocomplete(container.querySelector("#lieu-form [data-location-autocomplete]"));

		const JOURS_EVENEMENT = [
			{ numero: 0, court: "Lun", long: "Lundi" },
			{ numero: 1, court: "Mar", long: "Mardi" },
			{ numero: 2, court: "Mer", long: "Mercredi" },
			{ numero: 3, court: "Jeu", long: "Jeudi" },
			{ numero: 4, court: "Ven", long: "Vendredi" },
			{ numero: 5, court: "Sam", long: "Samedi" },
			{ numero: 6, court: "Dim", long: "Dimanche" },
		];

		function lireEtatLieux()
		{
			try { return JSON.parse(sessionStorage.getItem(CLE_ETAT_LIEUX) || "{}") || {}; }
			catch (_err) { return {}; }
		}

		function enregistrerEtatLieux(changements)
		{
			try { sessionStorage.setItem(CLE_ETAT_LIEUX, JSON.stringify({ ...lireEtatLieux(), ...changements })); }
			catch (_err) { /* Le stockage local est un confort, jamais un prérequis. */ }
		}

		function definirLieuOuvert(card, ouvert, memoriser = true)
		{
			const corps = card.querySelector(".lieu-accueils-block");
			const boutonOuverture = card.querySelector(".lieu-toggle");
			card.classList.toggle("is-open", ouvert);
			corps.hidden = !ouvert;
			boutonOuverture.setAttribute("aria-expanded", String(ouvert));
			boutonOuverture.textContent = ouvert ? "Replier" : "Ouvrir";
			if (memoriser)
			{
				const etat = lireEtatLieux();
				const memeLieu = Number(etat.lieuId) === Number(card.dataset.lieuId);
				enregistrerEtatLieux({ lieuId: ouvert ? Number(card.dataset.lieuId) : null, accueilId: ouvert && memeLieu ? etat.accueilId || null : null });
			}
		}

		function ouvrirLieuUnique(card)
		{
			const ouvrir = !card.classList.contains("is-open");
			list.querySelectorAll(".lieu-card.is-open").forEach((autre) => {
				if (autre !== card) definirLieuOuvert(autre, false, false);
			});
			definirLieuOuvert(card, ouvrir);
		}

		function normaliserRecherche(valeur)
		{
			return String(valeur || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
		}

		function appliquerFiltresLieux()
		{
			const recherche = normaliserRecherche(rechercheLieux.value);
			const type = filtreLieux.value;
			let visibles = 0;
			list.querySelectorAll(".lieu-card").forEach((card) => {
				const correspondRecherche = !recherche || card.dataset.recherche.includes(recherche);
				const correspondType = type === "tous" || card.dataset.typesAccueil.split(" ").includes(type);
				card.hidden = !(correspondRecherche && correspondType);
				if (!card.hidden) visibles += 1;
			});
			let vide = list.querySelector(".lieux-filter-empty");
			if (!vide)
			{
				vide = document.createElement("p");
				vide.className = "empty-note lieux-filter-empty";
				vide.textContent = "Aucun lieu ne correspond à cette recherche.";
				list.appendChild(vide);
			}
			vide.hidden = visibles > 0 || lieuxDonnees.length === 0;
		}

		function cartesLieuxOrdonnees()
		{
			return [...list.querySelectorAll(".lieu-card")];
		}

		function persisterOrdreLieux()
		{
			const centre_ids = cartesLieuxOrdonnees().map((card) => Number(card.dataset.lieuId));
			return apiFetch("/api/centres/reordonner/", {
				method: "POST",
				body: JSON.stringify({ centre_ids }),
			}).then(() => {
				lieuxDonnees.sort((a, b) => centre_ids.indexOf(Number(a.id)) - centre_ids.indexOf(Number(b.id)));
				afficherToast("Ordre des lieux enregistré.");
			}).catch((err) => {
				afficherToast(erreurMessage(err, "Impossible d’enregistrer l’ordre des lieux."), true);
				return charger();
			});
		}

		function typesLieuHtml(prefix, selection = ["vacances"])
		{
			const actifs = new Set((selection || []).map(String));
			return typesAccueilStructure.map((type) => `<label class="accueil-type-option"><input type="checkbox" class="${prefix}-type-accueil" value="${escapeHtml(type.code)}" ${actifs.has(type.code) ? "checked" : ""}><span>${escapeHtml(type.nom)}</span></label>`).join("");
		}

		function lireTypesLieu(root, prefix)
		{
			return [...root.querySelectorAll(`.${prefix}-type-accueil:checked`)].map((input) => input.value);
		}

		function badgesTypesAccueil(types)
		{
			return `<div class="accueil-type-badges">${(types || []).map((type) => `<span class="accueil-type-badge">${escapeHtml(type.nom)}</span>`).join("")}</div>`;
		}

		function nomReferenceDepuisSemaines(elements)
		{
			const nom = String(elements?.[0]?.nom || "").trim();
			return nom
				.replace(/\s*[—–-]\s*Semaine\s*\d*.*$/i, "")
				.replace(/\s+\d{4}$/i, "")
				.trim() || "Période";
		}

		function groupesReferencesPeriodes(elements)
		{
			const referencesParId = new Map(periodesCalendrier.map((reference) => [Number(reference.id), reference]));
			const groupes = new Map();
			(elements || []).forEach((periode) =>
			{
				const reference = referencesParId.get(Number(periode.periode_calendrier_id)) || null;
				const categorie = reference?.categorie || (periode.type_accueil === "vacances" ? "vacances" : "scolaire");
				const nomFallback = nomReferenceDepuisSemaines([periode]);
				const cle = reference
					? `reference-${reference.id}`
					: `fallback-${categorie}-${periode.zone || ""}-${nomFallback.toLowerCase()}`;
				if (!groupes.has(cle)) groupes.set(cle, { reference, categorie, periodes: [] });
				groupes.get(cle).periodes.push(periode);
			});

			return [...groupes.values()]
				.map((groupeReference) =>
				{
					const semaines = [...groupeReference.periodes].sort((a, b) => String(a.debut || "").localeCompare(String(b.debut || "")));
					const nomBase = groupeReference.reference?.nom || nomReferenceDepuisSemaines(semaines);
					const libelle = groupeReference.categorie === "vacances" ? libelleNomVacances(nomBase) : nomBase;
					return {
						...groupeReference,
						periodes: semaines,
						libelle,
						debut: groupeReference.reference?.debut || semaines[0]?.debut || "",
						fin: groupeReference.reference?.fin || semaines.at(-1)?.fin || "",
					};
				})
				.sort((a, b) => String(a.debut).localeCompare(String(b.debut)));
		}

		function periodesFormHtml(uid, prefix, groupe = null, accueilCode = null)
		{
			const codeAccueil = accueilCode || groupe?.type_accueil_code || groupe?.type_accueil_codes?.[0] || null;
			const periodesDisponibles = codeAccueil
				? periodesScolaires.filter((periode) =>
					periode.type_accueil === codeAccueil || (periode.types_accueil || []).includes(codeAccueil)
				)
				: periodesScolaires;
			if (!periodesDisponibles.length)
				return '<p class="empty-note">Aucune période enregistrée pour cet accueil. Le groupe peut tout de même être créé et configuré plus tard.</p>';

			const selectionnees = new Set(
				groupe ? (groupe.periode_ids || []).map(Number) : []
			);
			return grouperPeriodesParAnnee(periodesDisponibles).map(({ annee, periodes }) =>
			{
				const zones = new Map();
				periodes.forEach((periode) =>
				{
					const zone = String(periode.zone || "Sans zone");
					if (!zones.has(zone)) zones.set(zone, []);
					zones.get(zone).push(periode);
				});
				const nbSelectionnees = periodes.filter((periode) => selectionnees.has(Number(periode.id))).length;
				const referencesAnnee = [...zones.values()].flatMap((elements) => groupesReferencesPeriodes(elements));
				const nbReferencesSelectionnees = referencesAnnee.filter((reference) =>
					reference.periodes.some((periode) => selectionnees.has(Number(periode.id)))
				).length;

				return `
					<details class="period-year-accordion group-period-year" data-period-year="${escapeHtml(annee)}">
						<summary>
							<span class="period-year-summary"><strong>${escapeHtml(annee)}</strong><small class="group-period-year-count">${nbReferencesSelectionnees}/${referencesAnnee.length} périodes · ${nbSelectionnees}/${periodes.length} semaines</small></span>
							<span class="period-year-chevron" aria-hidden="true">⌄</span>
						</summary>
						<div class="period-year-content">
							${[...zones.entries()].map(([zone, elements]) => `
								<section class="period-zone-block">
									<div class="period-zone-head">
										<strong>Zone ${escapeHtml(zone)}</strong>
										<button type="button" class="period-zone-toggle" data-zone-action="toggle">Tout sélectionner</button>
									</div>
									<div class="group-period-references">
										${groupesReferencesPeriodes(elements).map((reference, index) => {
											const refUid = `${uid}-reference-${String(reference.reference?.id || `${zone}-${index}`).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
											const nbCochees = reference.periodes.filter((periode) => selectionnees.has(Number(periode.id))).length;
											const resume = nbCochees === reference.periodes.length
												? `Toutes les ${reference.periodes.length} semaines`
												: (nbCochees ? `${nbCochees}/${reference.periodes.length} semaines` : "Aucune semaine");
											return `<section class="group-period-reference" data-period-reference>
												<div class="group-period-reference-head">
													<label class="group-period-reference-main" for="${refUid}-all">
														<input type="checkbox" id="${refUid}-all" class="group-period-reference-toggle" ${nbCochees === reference.periodes.length ? "checked" : ""} data-indeterminate="${nbCochees > 0 && nbCochees < reference.periodes.length ? "true" : "false"}">
														<span><strong>${escapeHtml(reference.libelle)}</strong><small>${escapeHtml(libelleDate(reference.debut))} → ${escapeHtml(libelleDate(reference.fin))}</small></span>
													</label>
													<div class="group-period-reference-actions"><span class="group-period-reference-count">${escapeHtml(resume)}</span><button type="button" class="group-period-reference-customize" aria-expanded="false" aria-controls="${refUid}-weeks">Personnaliser</button></div>
												</div>
												<div class="group-period-reference-weeks" id="${refUid}-weeks" hidden>
													${reference.periodes.map((periode) => {
														const id = `${uid}-periode-${periode.id}`;
														return `<label class="group-period-option" for="${id}" title="${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}">
															<input type="checkbox" id="${id}" name="${uid}_periode_${periode.id}" class="${prefix}-periode" value="${periode.id}" ${selectionnees.has(Number(periode.id)) ? "checked" : ""}>
															<span><strong>${escapeHtml(periode.nom || libellePeriodeAvecAnnee(periode))}</strong><small>${escapeHtml(libelleDate(periode.debut))}–${escapeHtml(libelleDate(periode.fin))}</small></span>
														</label>`;
													}).join("")}
												</div>
											</section>`;
										}).join("")}
									</div>
								</section>
							`).join("")}
						</div>
					</details>`;
			}).join("");
		}

		function evenementFormHtml(prefix, groupe = null, accueilCode = null, accueil = null)
		{
			const uid = identifiantChamp(`groupe-${groupe?.id || "nouveau"}`);
			const nomId = `${uid}-nom`;
			const effectifId = `${uid}-effectif`;
			const feriesId = `${uid}-feries`;
			const permanentId = `${uid}-permanent`;
			const joursSelectionnes = new Set(
				(groupe?.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number)
			);
			const centreCible = accueil?.centre_id || groupe?.centre_id;
			const optionsGroupes = groupesPartages.filter((modele) => modele.portee !== "LOCAL" || !centreCible || Number(modele.centre_id) === Number(centreCible)).map((modele) => {
				const sejour = modele.type_groupe === "sejour"
					? ` · séjour ${libelleDate(modele.date_debut_validite)} → ${libelleDate(modele.date_fin_validite)}`
					: "";
				return `<option value="${modele.id}" ${Number(groupe?.groupe_id) === Number(modele.id) ? "selected" : ""}>${escapeHtml(modele.nom)}${escapeHtml(sejour)} — 1/${modele.enfants_par_animateur_defaut}</option>`;
			}).join("");
			const valeursBesoins = groupe?.qualifications_requises || {};
			const contextes = groupe?.besoins_encadrement || [];

			function contexteExistant(typeCode, modaliteCode = null)
			{
				return contextes.find((item) => item.type_accueil === typeCode
					&& (item.modalite_periscolaire || null) === modaliteCode
					&& !item.periode_calendrier_id) || null;
			}

			function blocBesoins(titre, elements, classe, valeurs = {}, attribut = "data-context-qualification-id")
			{
				const champs = elements.map((qualification) => `
					<label class="qualification-requirement"><span>${escapeHtml(qualification.nom)}</span><input type="number" min="0" step="1" value="${valeurs[String(qualification.id)] || 0}" ${attribut}="${qualification.id}"></label>`).join("") || '<span class="empty-note compact">Aucun élément</span>';
				return `<section class="besoin-type-block ${classe}"><strong class="besoin-type-title">${titre}</strong><div class="besoin-type-fields">${champs}</div></section>`;
			}

			function besoinsHtmlContexte(valeurs, attribut = "data-context-qualification-id")
			{
				return `<details class="staffing-advanced-requirements"><summary><span>Qualifications et exigences particulières</span><span class="period-year-chevron" aria-hidden="true">⌄</span></summary><div class="besoins-diplomes-statuts">${blocBesoins("Statuts", qualificationsEvenements.filter((item) => item.est_statut), "besoin-type-block--statuts", valeurs, attribut)}${blocBesoins("Diplômes / besoins spécifiques", qualificationsEvenements.filter((item) => !item.est_statut), "besoin-type-block--diplomes", valeurs, attribut)}</div></details>`;
			}

			const vacances = contexteExistant("vacances", null);
			const periscolaireDefaut = contexteExistant("periscolaire", null);
			const effectifBase = Math.max(1, Number(groupe?.effectif_cible_base || groupe?.effectif_cible || 1));

			function carteBesoin({ cle, typeCode, titre, sousTitre, regle, modaliteCode = null, obligatoire = false, herite = false })
			{
				const active = obligatoire || Boolean(regle);
				const mode = regle?.mode_calcul || "manuel";
				const effectif = Math.max(1, Number(regle?.effectif_cible || (typeCode === "vacances" ? effectifBase : 1)));
				const reference = regle?.effectif_enfants_reference ?? "";
				const renforts = Math.max(0, Number(regle?.renforts_souhaites || 0));
				const qualifs = regle?.qualifications_requises || (typeCode === "vacances" ? valeursBesoins : {});
				const toggleId = `${uid}-besoin-${cle}-active`;
				const modeId = `${uid}-besoin-${cle}-mode`;
				const etat = active ? (mode === "reglementaire" ? "Calcul réglementaire" : "Manuel") : (herite ? "Utilise le défaut périscolaire" : "Non configuré");
				return `<section class="staffing-context-card ${active ? "is-custom" : "is-inherited"}" data-staffing-context="${escapeHtml(cle)}" data-type-accueil-code="${escapeHtml(typeCode)}" data-modalite-code="${escapeHtml(modaliteCode || "")}" data-required="${obligatoire ? "1" : "0"}" data-inherits="${herite ? "1" : "0"}">
					<div class="staffing-context-head">
						${obligatoire
							? `<div><strong>${escapeHtml(titre)}</strong><small>${escapeHtml(sousTitre)}</small></div>`
							: `<label class="staffing-context-toggle" for="${toggleId}"><input type="checkbox" id="${toggleId}" class="${prefix}-staffing-context-enabled" ${active ? "checked" : ""}><span><strong>${escapeHtml(titre)}</strong><small>${escapeHtml(sousTitre)}</small></span></label>`}
						<span class="staffing-context-state">${etat}</span>
					</div>
					<div class="staffing-context-fields" ${active ? "" : "aria-disabled=\"true\""}>
						<div class="staffing-mode-row">
							<label class="field"><span>Mode de calcul</span><select id="${modeId}" class="${prefix}-staffing-context-mode" ${active ? "" : "disabled"}><option value="reglementaire" ${mode === "reglementaire" ? "selected" : ""}>Calcul automatique selon les enfants</option><option value="manuel" ${mode !== "reglementaire" ? "selected" : ""}>Nombre de postes défini manuellement</option></select></label>
							<label class="staffing-total" data-staffing-manual><span>Postes requis</span><input type="number" min="1" step="1" class="${prefix}-staffing-context-effectif" value="${effectif}" ${active ? "" : "disabled"}></label>
							<label class="staffing-total" data-staffing-auto><span>Fréquentation de référence</span><input type="number" min="0" step="1" class="${prefix}-staffing-context-reference" value="${reference}" placeholder="ex : 24" ${active ? "" : "disabled"}><small>L’effectif réel saisi dans le Planning reste prioritaire.</small></label>
							<label class="staffing-total"><span>Renforts souhaités</span><input type="number" min="0" step="1" class="${prefix}-staffing-context-renforts" value="${renforts}" ${active ? "" : "disabled"}><small>Ajoutés au-delà du minimum requis.</small></label>
						</div>
						<div class="staffing-specific-needs">${besoinsHtmlContexte(qualifs)}</div>
					</div>
				</section>`;
			}

			const vacancesHtml = carteBesoin({
				cle: "vacances",
				typeCode: "vacances",
				titre: "Vacances / extrascolaire",
				sousTitre: "Configuration indépendante du Périscolaire.",
				regle: vacances,
				obligatoire: true,
			});
			const modalitesAccueil = accueil?.modalites_periscolaires || (accueil ? [] : modalitesPeriscolaires);
			const periDefautHtml = carteBesoin({
				cle: "periscolaire-defaut",
				typeCode: "periscolaire",
				titre: modalitesAccueil.length === 1 ? "Encadrement" : "Encadrement par défaut",
				sousTitre: modalitesAccueil.length > 1 ? "Ce besoin s’applique à tous les temps de cet accueil." : "C’est l’encadrement normal de ce groupe pour cet accueil.",
				regle: periscolaireDefaut,
				obligatoire: true,
			});
			const periModalitesHtml = modalitesAccueil.map((modalite) => {
				const regle = contexteExistant("periscolaire", modalite.code);
				return `<div class="staffing-exception-item" data-staffing-exception="${escapeHtml(modalite.code)}" ${regle ? "" : "hidden"}>${carteBesoin({
					cle: `periscolaire-${modalite.code}`,
					typeCode: "periscolaire",
					titre: modalite.nom,
					sousTitre: "Personnalisez ce créneau uniquement s’il diffère du défaut Périscolaire.",
					regle,
					modaliteCode: modalite.code,
					herite: Boolean(periscolaireDefaut),
				})}</div>`;
			}).join("");
			const modalitesDisponiblesHtml = modalitesAccueil.map((modalite) => `<option value="${escapeHtml(modalite.code)}" ${contexteExistant("periscolaire", modalite.code) ? "hidden" : ""}>${escapeHtml(modalite.nom)}</option>`).join("");

			const joursHtml = JOURS_EVENEMENT.map((jour) => {
				const id = `${uid}-jour-${jour.numero}`;
				return `<label class="group-weekday-option" for="${id}">
					<input type="checkbox" id="${id}" name="${uid}_jour_${jour.numero}" class="${prefix}-jour-ouvert" value="${jour.numero}" ${joursSelectionnes.has(jour.numero) ? "checked" : ""}>
					<span title="${escapeHtml(jour.long)}">${escapeHtml(jour.court)}</span>
				</label>`;
			}).join("");
			const afficherVacances = !accueilCode || accueilCode === "vacances";
			const afficherPeriscolaire = !accueilCode || accueilCode === "periscolaire";

			return `
				<div class="team-form-grid">
					<div class="field team-name-field"><label for="${nomId}">Groupe</label><select id="${nomId}" class="${prefix}-groupe-id" ${groupe ? "disabled" : ""}><option value="">Choisir un groupe</option>${optionsGroupes}</select></div>
				</div>
				<section class="event-opening-settings">
					<label class="checkbox-option group-permanent-option" for="${permanentId}"><input type="checkbox" id="${permanentId}" name="${uid}_permanent" class="${prefix}-permanent" ${groupe?.permanent ? "checked" : ""}><span><strong>Groupe permanent</strong></span></label>
					<div class="${prefix}-period-settings">
					<div class="event-setting-heading"><strong>Périodes ouvertes</strong><span>Sélectionnez une période entière en un clic. Utilisez « Personnaliser » uniquement pour exclure ou ajouter certaines semaines.</span></div>
					<div class="group-period-actions">
						<button type="button" class="btn btn-ghost ${prefix}-periods-all">Tout sélectionner</button>
						<button type="button" class="btn btn-ghost ${prefix}-periods-none">Tout désélectionner</button>
					</div>
					<div class="group-periods">${periodesFormHtml(uid, prefix, groupe, accueilCode)}</div>
					</div>
					<div class="event-setting-heading"><strong>Jours ouverts</strong><span>Lundi à samedi ouverts par défaut ; dimanche fermé.</span></div>
					<div class="group-weekdays">${joursHtml}</div>
					<div class="group-closure-options">
						<label class="checkbox-option" for="${feriesId}"><input type="checkbox" id="${feriesId}" name="${uid}_ferme_jours_feries" class="${prefix}-ferme-feries" ${groupe?.ferme_jours_feries !== false ? "checked" : ""}><span>Fermé les jours fériés</span></label>
					</div>
				</section>
				<section class="event-staffing-settings">
					<div class="event-setting-heading"><strong>Besoins d’encadrement</strong><span>Vacances et Périscolaire sont indépendants. Le mode automatique utilise l’effectif réel s’il est saisi, sinon la fréquentation de référence.</span></div>
					${afficherVacances ? `<details class="staffing-vacances-details" open>
						<summary><span><strong>Vacances / extrascolaire</strong><small>Configuration indépendante du Périscolaire.</small></span><span class="period-year-chevron" aria-hidden="true">⌄</span></summary>
						<div class="staffing-vacances-content">${vacancesHtml}</div>
					</details>` : ""}
					${afficherPeriscolaire ? `<details class="staffing-periscolaire-details" ${periscolaireDefaut || contextes.some((item) => item.type_accueil === "periscolaire") ? "open" : ""}>
						<summary><span><strong>Périscolaire</strong><small>Configuration propre au Périscolaire, sans reprise des besoins Vacances.</small></span><span class="period-year-chevron" aria-hidden="true">⌄</span></summary>
						<div class="staffing-periscolaire-content">
							${periDefautHtml}
							${modalitesAccueil.length === 1 ? `<p class="staffing-single-modality">Cet accueil utilise uniquement : <strong>${escapeHtml(modalitesAccueil[0].nom)}</strong>. Aucun autre réglage n’est nécessaire.</p>` : ""}
							${modalitesAccueil.length > 1 ? `<section class="staffing-exceptions"><div class="event-setting-heading event-setting-heading--needs"><strong>Adapter l’encadrement pour un temps particulier</strong><span>Ajoutez une exception uniquement si un temps nécessite un encadrement différent.</span></div><div class="staffing-exception-add"><select class="${prefix}-staffing-exception-select" aria-label="Temps à différencier"><option value="">Choisir un temps</option>${modalitesDisponiblesHtml}</select><button type="button" class="btn btn-secondary ${prefix}-staffing-exception-add">+ Ajouter un encadrement différent</button></div><div class="staffing-context-modalities">${periModalitesHtml}</div></section>` : ""}
						</div>
					</details>` : ""}
				</section>
				<p class="form-error ${prefix}-error"></p>`;
		}

		function initialiserFormGroupe(root, prefix)
		{
			const permanentInput = root.querySelector(`.${prefix}-permanent`);
			const periodSettings = root.querySelector(`.${prefix}-period-settings`);
			const exceptionSelect = root.querySelector(`.${prefix}-staffing-exception-select`);
			const exceptionAdd = root.querySelector(`.${prefix}-staffing-exception-add`);
			if (exceptionSelect && exceptionAdd)
			{
				exceptionAdd.addEventListener("click", () =>
				{
					const code = exceptionSelect.value;
					if (!code) return;
					const item = root.querySelector(`[data-staffing-exception="${CSS.escape(code)}"]`);
					const toggle = item?.querySelector(`.${prefix}-staffing-context-enabled`);
					if (item && toggle)
					{
						item.hidden = false;
						toggle.checked = true;
						toggle.dispatchEvent(new Event("change", { bubbles: true }));
						exceptionSelect.querySelector(`option[value="${CSS.escape(code)}"]`).hidden = true;
						exceptionSelect.value = "";
					}
				});
			}

			function actualiserModePermanent()
			{
				const permanent = Boolean(permanentInput?.checked);
				if (periodSettings)
				{
					periodSettings.hidden = permanent;
					periodSettings.setAttribute("aria-hidden", permanent ? "true" : "false");
				}
			}

			function actualiserReferences()
			{
				root.querySelectorAll("[data-period-reference]").forEach((reference) =>
				{
					const cases = [...reference.querySelectorAll(`.${prefix}-periode`)];
					const nb = cases.filter((input) => input.checked).length;
					const toggle = reference.querySelector(".group-period-reference-toggle");
					if (toggle)
					{
						toggle.checked = cases.length > 0 && nb === cases.length;
						toggle.indeterminate = nb > 0 && nb < cases.length;
					}
					const compteur = reference.querySelector(".group-period-reference-count");
					if (compteur)
					{
						compteur.textContent = nb === cases.length && cases.length
							? `Toutes les ${cases.length} semaines`
							: (nb ? `${nb}/${cases.length} semaines` : "Aucune semaine");
					}
				});
			}

			function actualiserCompteursAnnees()
			{
				root.querySelectorAll(".group-period-year").forEach((details) =>
				{
					const cases = [...details.querySelectorAll(`.${prefix}-periode`)];
					const nb = cases.filter((input) => input.checked).length;
					const references = [...details.querySelectorAll("[data-period-reference]")];
					const nbReferences = references.filter((reference) =>
						[...reference.querySelectorAll(`.${prefix}-periode`)].some((input) => input.checked)
					).length;
					const compteur = details.querySelector(".group-period-year-count");
					if (compteur) compteur.textContent = `${nbReferences}/${references.length} périodes · ${nb}/${cases.length} semaines`;
				});

				root.querySelectorAll('.period-zone-block').forEach((zone) =>
				{
					const cases = [...zone.querySelectorAll(`.${prefix}-periode`)];
					const toutCoche = cases.length > 0 && cases.every((input) => input.checked);
					const button = zone.querySelector('[data-zone-action="toggle"]');
					if (button) button.textContent = toutCoche ? "Tout retirer" : "Tout sélectionner";
				});
			}

			function actualiserSelection()
			{
				actualiserReferences();
				actualiserCompteursAnnees();
			}

			function actualiserContextesEncadrement()
			{
				root.querySelectorAll("[data-staffing-context]").forEach((carte) =>
				{
					const toggle = carte.querySelector(`.${prefix}-staffing-context-enabled`);
					const obligatoire = carte.dataset.required === "1";
					const actif = obligatoire || Boolean(toggle?.checked);
					const mode = carte.querySelector(`.${prefix}-staffing-context-mode`)?.value || "manuel";
					carte.classList.toggle("is-custom", actif);
					carte.classList.toggle("is-inherited", !actif);
					const etat = carte.querySelector(".staffing-context-state");
					if (etat)
					{
						if (actif) etat.textContent = mode === "reglementaire" ? "Calcul réglementaire" : "Manuel";
						else etat.textContent = carte.dataset.modaliteCode && carte.dataset.inherits === "1"
							? "Utilise le défaut périscolaire"
							: "Non configuré";
					}
					const champs = carte.querySelector(".staffing-context-fields");
					if (champs) champs.setAttribute("aria-disabled", actif ? "false" : "true");
					carte.querySelectorAll(".staffing-context-fields input, .staffing-context-fields select").forEach((input) =>
					{
						input.disabled = !actif;
					});
					const manuel = carte.querySelector("[data-staffing-manual]");
					const auto = carte.querySelector("[data-staffing-auto]");
					if (manuel) manuel.hidden = mode === "reglementaire";
					if (auto) auto.hidden = mode !== "reglementaire";
				});
			}

			root.querySelector(`.${prefix}-periods-all`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = true; });
				actualiserSelection();
			});
			root.querySelector(`.${prefix}-periods-none`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = false; });
				actualiserSelection();
			});
			root.querySelectorAll(`.${prefix}-periode`).forEach((input) =>
				input.addEventListener("change", actualiserSelection)
			);
			root.querySelectorAll(".group-period-reference-toggle").forEach((toggle) =>
			{
				toggle.addEventListener("change", () =>
				{
					const reference = toggle.closest("[data-period-reference]");
					reference?.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = toggle.checked; });
					actualiserSelection();
				});
			});
			root.querySelectorAll(".group-period-reference-customize").forEach((button) =>
			{
				button.addEventListener("click", () =>
				{
					const reference = button.closest("[data-period-reference]");
					const semaines = reference?.querySelector(".group-period-reference-weeks");
					if (!semaines) return;
					semaines.hidden = !semaines.hidden;
					button.setAttribute("aria-expanded", semaines.hidden ? "false" : "true");
					button.textContent = semaines.hidden ? "Personnaliser" : "Masquer les semaines";
				});
			});
			root.querySelectorAll('[data-zone-action="toggle"]').forEach((button) => {
				button.addEventListener("click", () => {
					const zone = button.closest(".period-zone-block");
					const cases = [...(zone?.querySelectorAll(`.${prefix}-periode`) || [])];
					const toutCoche = cases.length > 0 && cases.every((input) => input.checked);
					cases.forEach((input) => { input.checked = !toutCoche; });
					actualiserSelection();
				});
			});
			root.querySelectorAll(`.${prefix}-staffing-context-enabled`).forEach((input) =>
				input.addEventListener("change", () =>
				{
					actualiserContextesEncadrement();
					const item = input.closest("[data-staffing-exception]");
					if (item && !input.checked)
					{
						item.hidden = true;
						const option = exceptionSelect?.querySelector(`option[value="${CSS.escape(item.dataset.staffingException)}"]`);
						if (option) option.hidden = false;
					}
				})
			);
			root.querySelectorAll(`.${prefix}-staffing-context-mode`).forEach((input) =>
				input.addEventListener("change", actualiserContextesEncadrement)
			);
			permanentInput?.addEventListener("change", actualiserModePermanent);
			actualiserModePermanent();
			actualiserSelection();
			actualiserContextesEncadrement();
		}

		function lireEvenementForm(root, prefix)
		{

			const accueilCode = root.dataset.accueilCode || null;
			const permanent = Boolean(root.querySelector(`.${prefix}-permanent`)?.checked);
			const groupeId = Number(root.querySelector(`.${prefix}-groupe-id`)?.value || 0);
			const modele = groupesPartages.find((item) => Number(item.id) === groupeId);
			const besoinsEncadrement = [];
			let effectifHistorique = 1;
			let qualificationsHistoriques = {};
			root.querySelectorAll("[data-staffing-context]").forEach((carte) =>
			{
				if (accueilCode && carte.dataset.typeAccueilCode !== accueilCode) return;
				const obligatoire = carte.dataset.required === "1";
				const active = carte.querySelector(`.${prefix}-staffing-context-enabled`);
				if (!obligatoire && !active?.checked) return;
				const qualifications = {};
				carte.querySelectorAll("[data-context-qualification-id]").forEach((input) =>
				{
					const nombre = Number.parseInt(input.value, 10) || 0;
					if (nombre > 0) qualifications[input.dataset.contextQualificationId] = nombre;
				});
				const mode = carte.querySelector(`.${prefix}-staffing-context-mode`)?.value || "manuel";
				const ligne = {
					type_accueil: carte.dataset.typeAccueilCode,
					modalite_periscolaire: carte.dataset.modaliteCode || null,
					mode_calcul: mode,
					effectif_cible: Number.parseInt(carte.querySelector(`.${prefix}-staffing-context-effectif`)?.value, 10) || 1,
					effectif_enfants_reference: carte.querySelector(`.${prefix}-staffing-context-reference`)?.value === "" ? null : (Number.parseInt(carte.querySelector(`.${prefix}-staffing-context-reference`)?.value, 10) || 0),
					renforts_souhaites: Number.parseInt(carte.querySelector(`.${prefix}-staffing-context-renforts`)?.value, 10) || 0,
					qualifications_requises: qualifications,
				};
				besoinsEncadrement.push(ligne);
				if (carte.dataset.typeAccueilCode === "vacances" && !carte.dataset.modaliteCode)
				{
					effectifHistorique = ligne.effectif_cible;
					qualificationsHistoriques = qualifications;
				}
			});
			return {
				groupe_id: groupeId,
				nom: modele?.nom || "",
				permanent,
				periode_ids: permanent ? [] : Array.from(root.querySelectorAll(`.${prefix}-periode:checked`)).map((input) => Number(input.value)),
				effectif_cible: effectifHistorique,
				jours_ouverts: Array.from(root.querySelectorAll(`.${prefix}-jour-ouvert:checked`)).map((input) => Number(input.value)),
				ferme_jours_feries: root.querySelector(`.${prefix}-ferme-feries`).checked,
				qualifications_requises: qualificationsHistoriques,
				besoins_encadrement: besoinsEncadrement,
			};
		}

		function periodeLibelle(groupe)
		{
			if (groupe.permanent) return "Permanent — ouvert à toutes les périodes";
			const periodes = groupe.periodes || [];
			if (!periodes.length) return "Aucune période — masqué des calendriers";
			if (periodes.length === 1) return periodes[0].nom;
			return `${periodes.length} semaines sélectionnées`;
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
			const adresseId = `edit-lieu-${c.id}-adresse`;
			const codePostalId = `edit-lieu-${c.id}-code-postal`;
			const communeId = `edit-lieu-${c.id}-commune`;
			const header = card.querySelector(".lieu-card-header");
			header.innerHTML = `
				<div class="lieu-edit-grid">
					<div class="field"><label for="${nomId}">Nom</label><input type="text" id="${nomId}" name="lieu_${c.id}_nom" class="edit-lieu-nom" value="${escapeHtml(c.nom)}"></div>
					<div class="field"><label for="${codeId}">Nom court ou abréviation</label><input type="text" id="${codeId}" name="lieu_${c.id}_code" class="edit-lieu-code" value="${escapeHtml(c.code)}" maxlength="10"></div>
					<div class="field"><label for="${couleurId}">Couleur</label><input type="color" id="${couleurId}" name="lieu_${c.id}_couleur" class="edit-lieu-couleur" value="${escapeHtml(c.couleur)}"></div>
					<div class="lieu-location-fields" data-location-autocomplete><div class="field"><label for="${adresseId}">Adresse ou lieu-dit <small>(facultatif)</small></label><input type="text" id="${adresseId}" class="edit-lieu-adresse" value="${escapeHtml(c.adresse||"")}" autocomplete="street-address"></div><div class="lieu-location-locality"><div class="field"><label for="${codePostalId}">Code postal</label><input type="text" id="${codePostalId}" class="edit-lieu-code-postal" data-location-postal value="${escapeHtml(c.code_postal||"")}" inputmode="numeric" maxlength="5" pattern="[0-9]{5}"></div><div class="field"><label for="${communeId}">Commune</label><input type="text" id="${communeId}" class="edit-lieu-commune" data-location-city value="${escapeHtml(c.commune||"")}" autocomplete="address-level2"></div></div><div data-location-suggestions role="listbox" hidden></div><small data-location-status aria-live="polite"></small><input type="hidden" data-location-insee value="${escapeHtml(c.code_insee||"")}"><input type="hidden" data-location-requested value="1"></div>
					<p class="form-error edit-lieu-error"></p>
				</div>
			`;
			const error = header.querySelector(".edit-lieu-error");
			const couleurInput = header.querySelector(".edit-lieu-couleur");
			initLocationAutocomplete(header.querySelector("[data-location-autocomplete]"));
			couleurInput.addEventListener("input", () => appliquerCouleurLieu(card, couleurInput.value));
			header.appendChild(creerFormActions(() =>
			{
				const nom = champValeur(header, ".edit-lieu-nom");
				const code = champValeur(header, ".edit-lieu-code");
				const couleur = champValeur(header, ".edit-lieu-couleur");
				const adresse = champValeur(header, ".edit-lieu-adresse");
				const code_postal = champValeur(header, ".edit-lieu-code-postal");
				const commune = champValeur(header, ".edit-lieu-commune");
				const code_insee = champValeur(header, "[data-location-insee]");
				if (!nom || !code)
				{
					error.textContent = "Le nom et le code sont obligatoires.";
					return;
				}
				apiFetch(`/api/centres/${c.id}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom, code, couleur, adresse, code_postal, commune, code_insee, localisation_demandee:true }),
				}).then((resultat) =>
				{
					afficherToast(resultat.localisation_warning||"Lieu modifié.",Boolean(resultat.localisation_warning));
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

		function contextualiserFormGroupe(root, accueilCode)
		{
			if (!accueilCode) return;
			root.dataset.accueilCode = accueilCode;
			const vacances = root.querySelector(".staffing-vacances-details");
			const perisco = root.querySelector(".staffing-periscolaire-details");
			if (vacances) vacances.hidden = accueilCode !== "vacances";
			if (perisco) perisco.hidden = accueilCode !== "periscolaire";
			const intro = root.querySelector(".event-staffing-settings > .event-setting-heading span");
			if (intro) intro.textContent = accueilCode === "vacances" ? "Besoins propres à cet accueil Vacances." : "Besoins propres à cet accueil Périscolaire.";
		}

		function ouvrirEditionEvenement(evenement, lieu, row, accueil = null)
		{
			row.classList.add("team-row-editing");
			row.innerHTML = evenementFormHtml("edit-team", evenement, evenement.type_accueil_code || evenement.type_accueil_codes?.[0] || null, accueil);
			initialiserFormGroupe(row, "edit-team");
			contextualiserFormGroupe(row, evenement.type_accueil_code || evenement.type_accueil_codes?.[0] || null);
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

		function chargerEvenements(c, card, accueil = null)
		{
			const teamList = card.querySelector(".team-list");
			const suffixe = accueil ? `?accueil_id=${encodeURIComponent(accueil.id)}` : "";
			return apiFetch(`/api/centres/${c.id}/groupes/${suffixe}`).then((evenements) =>
			{
				teamList.innerHTML = "";
				if (!evenements.length) teamList.innerHTML = '<p class="empty-note">Aucun groupe dans cet accueil.</p>';
				evenements.forEach((evenement, index) =>
				{
					const row = document.createElement("div");
					row.className = "team-row";
					row.dataset.evenementId = evenement.id;
					row.innerHTML = `
						<div class="team-main">
							<div class="team-title-line">
								<strong>${escapeHtml(evenement.nom)}</strong>
								${evenement.groupe_type === "sejour" ? '<span class="accueil-type-badge accueil-type-badge--stay">Séjour</span>' : ""}
							</div>
							<div class="team-meta">
								${evenement.groupe_type === "sejour" ? `<span>${escapeHtml(libelleDate(evenement.groupe_date_debut_validite))} → ${escapeHtml(libelleDate(evenement.groupe_date_fin_validite))}</span>` : ""}
								${evenement.accueil_centre_id
									? `<span>Encadrement : ${escapeHtml(evenement.encadrement_resume || "À configurer")}</span>`
									: `<span>${evenement.effectif_cible} animateur${evenement.effectif_cible > 1 ? "s" : ""}</span><span>1 anim. / ${evenement.enfants_par_animateur_defaut || 8} enfants</span>`}
								<span>${escapeHtml(periodeLibelle(evenement))}</span>
								<span>${escapeHtml(joursOuvertureLibelle(evenement))}</span>
								${(evenement.dates_exclues || []).length ? `<span>${evenement.dates_exclues.length} fermeture${evenement.dates_exclues.length > 1 ? "s" : ""}</span>` : ""}
								${evenement.accueil_centre_id
									? ((evenement.exigences_particulieres_libelle || []).length ? `<span>Exigence particulière : ${escapeHtml(evenement.exigences_particulieres_libelle.join(", "))}</span>` : "")
									: ((evenement.qualifications_libelle || []).length ? `<span>${escapeHtml(evenement.qualifications_libelle.join(", "))}</span>` : "")}
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
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEditionEvenement(evenement, c, row, accueil)));
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

		async function afficherConfigurationPeriscolaire(c, host, accueil = null)
		{
			host.hidden = false;
			if (!periodesCalendrierScolaires.length)
			{
				host.innerHTML = `<section class="periscolaire-openings-panel"><div class="periscolaire-openings-heading"><div><h4>Ouvertures périscolaires</h4><p>Commencez par enregistrer l’année scolaire dans Configuration → Calendrier scolaire.</p></div><button class="btn btn-ghost periscolaire-openings-close" type="button">Fermer</button></div></section>`;
				host.querySelector(".periscolaire-openings-close").addEventListener("click", () => { host.hidden = true; });
				return;
			}

			const optionsPeriodes = periodesCalendrierScolaires.map((periode) => `<option value="${periode.id}">${escapeHtml(periode.libelle || `${periode.nom} · ${periode.annee_scolaire}`)}</option>`).join("");
			host.innerHTML = `<section class="periscolaire-openings-panel">
				<div class="periscolaire-openings-heading"><div><h4>Ouvertures périscolaires</h4><p>Définissez les créneaux réellement ouverts dans cet accueil. Les horaires peuvent varier selon le jour et l’année scolaire.</p>${accueil ? `<span class="accueil-context-badge">${escapeHtml(accueil.nom_affichage || accueil.type_accueil_nom)}</span>` : ""}</div><button class="btn btn-ghost periscolaire-openings-close" type="button">Fermer</button></div>
				<label class="field periscolaire-period-select"><span>Période scolaire</span><select class="periscolaire-opening-period">${optionsPeriodes}</select></label>
				<div class="periscolaire-opening-grid"><p class="empty-note">Chargement…</p></div>
			</section>`;
			host.querySelector(".periscolaire-openings-close").addEventListener("click", () => { host.hidden = true; });
			const selectPeriode = host.querySelector(".periscolaire-opening-period");
			const grid = host.querySelector(".periscolaire-opening-grid");

			async function chargerOuvertures()
			{
				const periodeId = Number(selectPeriode.value);
				const suffixeAccueil = accueil ? `&accueil_id=${encodeURIComponent(accueil.id)}` : "";
				const ouvertures = await apiFetch(`/api/centres/${c.id}/ouvertures-periscolaires/?periode_calendrier_id=${periodeId}${suffixeAccueil}`);
				const index = new Map((ouvertures || []).map((item) => [`${item.modalite_id}-${item.jour_semaine}`, item]));
				grid.innerHTML = `${modalitesPeriscolaires.map((modalite) => `<details class="periscolaire-modality" ${modalite.code === "mercredi_journee" ? "open" : ""}>
					<summary><strong>${escapeHtml(modalite.nom)}</strong><span>${escapeHtml([modalite.heure_debut, modalite.heure_fin].filter(Boolean).join("–") || "Horaires à définir")}</span></summary>
					<div class="periscolaire-modality-days">${JOURS_EVENEMENT.map((jour) => {
						const existante = index.get(`${modalite.id}-${jour.numero}`);
						const coche = Boolean(existante);
						const debut = existante?.heure_debut || modalite.heure_debut || "";
						const fin = existante?.heure_fin || modalite.heure_fin || "";
						return `<div class="periscolaire-opening-row" data-modalite-id="${modalite.id}" data-jour="${jour.numero}"><label class="periscolaire-day-toggle"><input type="checkbox" class="opening-enabled" ${coche ? "checked" : ""}><span>${escapeHtml(jour.long)}</span></label><label><span>Début</span><input type="time" class="opening-start" value="${escapeHtml(debut)}" ${coche ? "" : "disabled"}></label><label><span>Fin</span><input type="time" class="opening-end" value="${escapeHtml(fin)}" ${coche ? "" : "disabled"}></label></div>`;
					}).join("")}</div>
				</details>`).join("")}<div class="periscolaire-openings-actions"><p class="form-error periscolaire-opening-error"></p><button class="btn btn-primary periscolaire-opening-save" type="button">Enregistrer les ouvertures</button></div>`;

				grid.querySelectorAll(".opening-enabled").forEach((input) => input.addEventListener("change", () => {
					const row = input.closest(".periscolaire-opening-row");
					row.querySelectorAll('input[type="time"]').forEach((champ) => { champ.disabled = !input.checked; });
				}));
				grid.querySelector(".periscolaire-opening-save").addEventListener("click", async () => {
					const error = grid.querySelector(".periscolaire-opening-error");
					error.textContent = "";
					const lignes = [];
					for (const row of grid.querySelectorAll(".periscolaire-opening-row"))
					{
						if (!row.querySelector(".opening-enabled").checked) continue;
						const heure_debut = row.querySelector(".opening-start").value;
						const heure_fin = row.querySelector(".opening-end").value;
						if ((heure_debut && !heure_fin) || (!heure_debut && heure_fin) || (heure_debut && heure_fin <= heure_debut))
						{
							error.textContent = "Vérifiez les heures de début et de fin des créneaux cochés.";
							return;
						}
						lignes.push({ modalite_id: Number(row.dataset.modaliteId), jour_semaine: Number(row.dataset.jour), heure_debut, heure_fin });
					}
					const payloadOuvertures = { periode_calendrier_id: periodeId, accueil_id: accueil?.id || null, ouvertures: lignes };
					async function enregistrer(recupererHistoriques = false)
					{
						await apiFetch(`/api/centres/${c.id}/ouvertures-periscolaires/`, {
							method: "POST",
							body: JSON.stringify({ ...payloadOuvertures, recuperer_ouvertures_historiques: recupererHistoriques }),
						});
					}
					try
					{
						try
						{
							await enregistrer(false);
						}
						catch (err)
						{
							if (err?.code !== "ouvertures_historiques_a_recuperer") throw err;
							if (!confirmerRecuperationOuverturesHistoriques(err)) return;
							await enregistrer(true);
						}
						afficherToast("Ouvertures périscolaires enregistrées.");
						await chargerOuvertures();
					}
					catch (err) { error.textContent = erreurMessage(err, "Enregistrement impossible."); }
				});
			}

			selectPeriode.addEventListener("change", () => chargerOuvertures().catch((err) => { grid.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(err, "Chargement impossible."))}</p>`; }));
			await chargerOuvertures();
		}


		function accueilStatutLibelle(accueil)
		{
			if (accueil.statut === "a_venir") return "À venir";
			if (accueil.statut === "termine") return "Terminé";
			return "Actif";
		}

		function accueilDateResume(accueil)
		{
			if (!accueil.date_debut && !accueil.date_fin) return "Historique non daté";
			if (accueil.date_debut && accueil.date_fin) return `${libelleDate(accueil.date_debut)} → ${libelleDate(accueil.date_fin)}`;
			if (accueil.date_debut) return `Depuis le ${libelleDate(accueil.date_debut)}`;
			return `Jusqu’au ${libelleDate(accueil.date_fin)}`;
		}

		function confirmerRecuperationOuverturesHistoriques(err)
		{
			if (err?.code !== "ouvertures_historiques_a_recuperer") return false;
			const ouvertures = Array.isArray(err.ouvertures) ? err.ouvertures : [];
			const nb = ouvertures.length;
			const lignes = ouvertures.slice(0, 6).map((item) =>
			{
				const periode = [item.periode_nom, item.annee_scolaire].filter(Boolean).join(" · ");
				const horaire = [item.heure_debut, item.heure_fin].filter(Boolean).join("–");
				return `• ${item.modalite_nom || "Créneau"} — ${item.jour_nom || "jour"}${periode ? ` — ${periode}` : ""}${horaire ? ` — ${horaire}` : ""}`;
			});
			if (nb > lignes.length) lignes.push(`• … et ${nb - lignes.length} autre${nb - lignes.length > 1 ? "s" : ""}`);
			const intro = nb === 1
				? "Animation Manager a trouvé un ancien créneau déjà enregistré pour ce lieu, mais pas encore rattaché à un accueil précis."
				: `Animation Manager a trouvé ${nb || "plusieurs"} anciens créneaux déjà enregistrés pour ce lieu, mais pas encore rattachés à un accueil précis.`;
			const cible = err.accueil_nom ? `« ${err.accueil_nom} »` : "ce nouvel accueil";
			return confirm(`${intro}${lignes.length ? `\n\n${lignes.join("\n")}` : ""}\n\nVoulez-vous ${nb === 1 ? "le" : "les"} récupérer dans ${cible} ?`);
		}

		function groupesStructurelsAssistant()
		{
			return groupesPartages.filter((groupe) => (groupe.type_groupe || "structure") === "structure");
		}

		function referencesVacancesAssistant()
		{
			const semaines = periodesScolaires.filter((periode) =>
				periode.type_accueil === "vacances"
				|| (periode.types_accueil || []).includes("vacances")
				|| periodesCalendrier.find((ref) => Number(ref.id) === Number(periode.periode_calendrier_id))?.categorie === "vacances"
			);
			return groupesReferencesPeriodes(semaines).filter((reference) => reference.categorie === "vacances");
		}

		async function ouvrirAssistantCentre(centre = null)
		{
			try { modalitesPeriscolaires = await apiFetch("/api/modalites-periscolaires/"); }
			catch (_err) { /* le référentiel déjà chargé reste disponible */ }

			const accueilsExistants = centre?.accueils || [];
			const vacancesExiste = accueilsExistants.some((item) => item.type_accueil_code === "vacances");
			const nbPeriscoExistants = accueilsExistants.filter((item) => item.type_accueil_code === "periscolaire").length;
			const vacReferences = referencesVacancesAssistant();
			const aujourdHui = new Date().toISOString().slice(0, 10);
			const groupesDisponibles = groupesStructurelsAssistant();
			const contexte = centre ? "ajout" : "creation";

			function groupesHtml(code)
			{
				return `<div class="wizard-accueil-groups" data-groups-for="${code}">
					<div class="wizard-section-inline-head"><div><strong>Groupes de cet accueil</strong><small>Ils sont indépendants des groupes de l’autre accueil.</small></div><button type="button" class="btn btn-secondary wizard-add-group" data-code="${code}">+ Nouveau groupe</button></div>
					<div class="wizard-group-grid">${groupesDisponibles.map((groupe) => `<label class="wizard-group-choice"><input type="checkbox" class="wizard-group-existing" data-code="${code}" value="${groupe.id}"><span><strong>${escapeHtml(groupe.nom)}</strong><small>${escapeHtml(groupe.categorie_age_reglementaire_libelle || "Catégorie non renseignée")}</small></span></label>`).join("") || '<p class="empty-note">Aucun groupe structurel existant.</p>'}</div>
					<div class="wizard-new-group-list" data-new-groups="${code}"></div>
				</div>`;
			}

			function besoinQualificationsHtml()
			{
				return qualificationsEvenements.map((qualification) => `<label><span>${escapeHtml(qualification.nom)}</span><input type="number" min="0" value="0" data-wizard-qualification-id="${qualification.id}"></label>`).join("");
			}

			function staffingRowHtml(type, titre, modalite = "", optionnel = false)
			{
				return `<div class="wizard-staffing-row ${optionnel ? "is-optional" : ""}" data-type="${type}" data-modalite="${escapeHtml(modalite)}">
					${optionnel ? `<label class="wizard-staffing-exception"><input type="checkbox" class="wizard-staffing-enabled"><span>Personnaliser ${escapeHtml(titre)}</span></label>` : `<strong>${escapeHtml(titre)}</strong>`}
					<div class="wizard-staffing-fields">
						<label class="field"><span>Mode</span><select class="wizard-staffing-mode"><option value="reglementaire">Calcul automatique selon les enfants</option><option value="manuel">Postes définis manuellement</option></select></label>
						<label class="field wizard-staffing-reference"><span>Fréquentation de référence</span><input type="number" min="0" class="wizard-staffing-ref" placeholder="facultatif"></label>
						<label class="field wizard-staffing-manual" hidden><span>Postes requis</span><input type="number" min="1" class="wizard-staffing-postes" value="1"></label>
						<label class="field"><span>Renforts souhaités</span><input type="number" min="0" class="wizard-staffing-renforts" value="0"></label>
						<details class="wizard-specific-needs"><summary>Diplômes / statuts spécifiques</summary><div class="wizard-specific-grid">${besoinQualificationsHtml()}</div></details>
					</div>
				</div>`;
			}

			function accueilVacancesHtml()
			{
				if (centre && vacancesExiste) return `<div class="wizard-skip-card"><strong>Vacances / extrascolaire</strong><span>Déjà configuré dans ce lieu.</span></div>`;
				return `<section class="wizard-accueil-workflow" data-accueil-workflow="vacances">
					<label class="wizard-accueil-enable"><input type="checkbox" class="wizard-enable-accueil" data-code="vacances" ${centre ? "checked" : "checked"}><span><strong>Configurer un accueil Vacances / extrascolaire</strong><small>Décochez si ce lieu n’en propose pas.</small></span></label>
					<div class="wizard-accueil-workflow-content">
						<div class="wizard-date-row"><label class="field"><span>Début d’activité</span><input type="date" class="wizard-accueil-debut" value="${aujourdHui}"></label><label class="field"><span>Fin d’activité <small>(facultatif)</small></span><input type="date" class="wizard-accueil-fin"></label></div>
						${groupesHtml("vacances")}
						<section class="wizard-subsection"><div class="wizard-card-title"><strong>Fonctionnement Vacances</strong></div><label class="wizard-switch"><input type="checkbox" class="wizard-vacances-permanent"><span>Ouvert à toutes les périodes Vacances disponibles</span></label><div class="wizard-period-grid">${vacReferences.map((reference) => `<label class="wizard-period-choice"><input type="checkbox" class="wizard-vacances-reference" data-periode-ids="${reference.periodes.map((p) => p.id).join(",")}"><span><strong>${escapeHtml(reference.libelle)}</strong><small>${escapeHtml(libelleDate(reference.debut))} → ${escapeHtml(libelleDate(reference.fin))}</small></span></label>`).join("") || '<p class="empty-note">Aucune période Vacances disponible.</p>'}</div><div class="wizard-subrow"><span>Jours habituels</span><div class="wizard-weekdays">${JOURS_EVENEMENT.map((jour) => `<label><input type="checkbox" class="wizard-vacances-day" value="${jour.numero}" ${jour.numero < 5 ? "checked" : ""}><span>${jour.court}</span></label>`).join("")}</div></div><label class="wizard-switch"><input type="checkbox" class="wizard-vacances-feries" checked><span>Fermé les jours fériés</span></label></section>
						<section class="wizard-subsection"><div class="wizard-card-title"><strong>Encadrement Vacances</strong><span>À renseigner pour chaque groupe sélectionné.</span></div><div class="wizard-staffing-host" data-staffing-for="vacances"></div></section>
					</div>
				</section>`;
			}

			function openingRowHtml(modalite)
			{
				return `<div class="wizard-opening-row" data-modalite-id="${modalite.id}" data-modalite-code="${escapeHtml(modalite.code)}"><label class="wizard-opening-name"><input type="checkbox" class="wizard-opening-active"><span><strong>${escapeHtml(modalite.nom)}</strong></span></label><div class="wizard-weekdays">${JOURS_EVENEMENT.map((jour) => `<label><input type="checkbox" class="wizard-opening-day" value="${jour.numero}" ${modalite.jour_entier && jour.numero === 2 ? "checked" : ""}><span>${jour.court}</span></label>`).join("")}</div><div class="wizard-opening-times"><input type="time" class="wizard-opening-start" value="${escapeHtml(modalite.heure_debut || "")}"><span>→</span><input type="time" class="wizard-opening-end" value="${escapeHtml(modalite.heure_fin || "")}"></div></div>`;
			}

			function accueilPeriscoHtml()
			{
				return `<section class="wizard-accueil-workflow" data-accueil-workflow="periscolaire">
					<label class="wizard-accueil-enable"><input type="checkbox" class="wizard-enable-accueil" data-code="periscolaire" ${centre && vacancesExiste ? "checked" : ""}><span><strong>${nbPeriscoExistants ? "Ajouter un autre accueil Périscolaire" : "Configurer un accueil Périscolaire"}</strong><small>Décochez si ce lieu n’en propose pas.</small></span></label>
					<div class="wizard-accueil-workflow-content">
						<label class="field wizard-accueil-label"><span>Nom complémentaire ${nbPeriscoExistants ? "(obligatoire)" : "(facultatif)"}</span><input class="wizard-accueil-libelle" maxlength="80" placeholder="ex : Mercredi ou Semaine"><small>${nbPeriscoExistants ? "Permet de distinguer les accueils Périscolaire du même lieu." : "Utile seulement si plusieurs accueils Périscolaire existent dans ce lieu."}</small></label>
						<div class="wizard-date-row"><label class="field"><span>Début d’activité</span><input type="date" class="wizard-accueil-debut" value="${aujourdHui}"></label><label class="field"><span>Fin d’activité <small>(facultatif)</small></span><input type="date" class="wizard-accueil-fin"></label></div><label class="wizard-switch"><input type="checkbox" class="wizard-pedt"><span>PEDT applicable à cet accueil</span></label>
						${groupesHtml("periscolaire")}
						<section class="wizard-subsection"><div class="wizard-card-title"><strong>Fonctionnement Périscolaire</strong><button type="button" class="btn btn-ghost wizard-add-modalite">+ Créer un temps</button></div><div class="wizard-inline-time-form" hidden><label class="field"><span>Nom</span><input class="wizard-inline-time-name" placeholder="ex : Étude surveillée"></label><label class="field"><span>Début par défaut</span><input type="time" class="wizard-inline-time-start"></label><label class="field"><span>Fin par défaut</span><input type="time" class="wizard-inline-time-end"></label><label class="wizard-switch"><input type="checkbox" class="wizard-inline-time-full"><span>Journée entière</span></label><button type="button" class="btn btn-primary wizard-inline-time-save">Ajouter</button><button type="button" class="btn btn-ghost wizard-inline-time-cancel">Annuler</button><p class="form-error wizard-inline-time-error"></p></div><div class="wizard-school-periods">${periodesCalendrierScolaires.map((periode) => `<label class="wizard-period-choice"><input type="checkbox" class="wizard-perisco-period" value="${periode.id}"><span><strong>${escapeHtml(periode.nom)}</strong><small>${escapeHtml(periode.annee_scolaire || "")} · ${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}</small></span></label>`).join("") || '<p class="empty-note">Aucune période scolaire disponible.</p>'}</div><div class="wizard-opening-table">${modalitesPeriscolaires.map(openingRowHtml).join("")}</div></section>
						<section class="wizard-subsection"><div class="wizard-card-title"><strong>Encadrement Périscolaire</strong><span>Besoin par défaut + exceptions facultatives par temps.</span></div><div class="wizard-staffing-host" data-staffing-for="periscolaire"></div></section>
					</div>
				</section>`;
			}

			wizardHost.hidden = false;
			wizardHost.innerHTML = `<section class="centre-wizard" data-centre-id="${centre ? centre.id : ""}">
				<div class="centre-wizard-head"><div><span class="centre-wizard-kicker">Assistant de configuration</span><h3>${centre ? `Ajouter un accueil à ${escapeHtml(centre.nom)}` : "Créer un lieu et ses accueils"}</h3></div><button type="button" class="btn btn-ghost centre-wizard-close">Fermer</button></div>
				<div class="centre-wizard-progress" aria-label="Progression">${["Lieu", "Vacances", "Périscolaire", "Vérification"].map((label, i) => `<button type="button" data-wizard-step-button="${i + 1}" ${i ? "disabled" : ""}><span>${i + 1}</span>${label}</button>`).join("")}</div>
				<div class="centre-wizard-body">
					<section class="centre-wizard-step" data-wizard-step="1">${centre ? `<div class="wizard-existing-place"><strong>${escapeHtml(centre.nom)}</strong><span>${escapeHtml(centre.code)}${centre.code_postal ? ` · ${escapeHtml(centre.code_postal)} ${escapeHtml(centre.commune || "")}` : ""}</span></div>` : `<div class="wizard-fields wizard-fields--identity"><label class="field"><span>Nom du lieu</span><input class="wizard-centre-nom"></label><label class="field"><span>Nom court ou abréviation</span><input class="wizard-centre-code" maxlength="10"></label><label class="field wizard-color-field"><span>Couleur</span><input type="color" class="wizard-centre-couleur" value="#1f6f54"></label><label class="field wizard-address-field"><span>Adresse ou lieu-dit</span><input class="wizard-centre-adresse"></label><label class="field"><span>Code postal</span><input class="wizard-centre-cp" maxlength="5" inputmode="numeric"></label><label class="field"><span>Commune</span><input class="wizard-centre-commune"></label></div>`}</section>
					<section class="centre-wizard-step" data-wizard-step="2" hidden>${accueilVacancesHtml()}</section>
					<section class="centre-wizard-step" data-wizard-step="3" hidden>${accueilPeriscoHtml()}</section>
					<section class="centre-wizard-step" data-wizard-step="4" hidden><div class="wizard-review"></div></section>
				</div><p class="form-error centre-wizard-error" aria-live="polite"></p><div class="centre-wizard-actions"><button type="button" class="btn btn-ghost wizard-prev" hidden>Précédent</button><button type="button" class="btn btn-primary wizard-next">Suivant</button><button type="button" class="btn btn-primary wizard-submit" hidden>${centre ? "Ajouter l’accueil" : "Créer le lieu"}</button></div></section>`;

			const assistant = wizardHost.querySelector(".centre-wizard");
			const error = assistant.querySelector(".centre-wizard-error");
			let etape = 1;

			function workflow(code) { return assistant.querySelector(`[data-accueil-workflow="${code}"]`); }
			function accueilActive(code) { const bloc = workflow(code); return Boolean(bloc?.querySelector(`.wizard-enable-accueil[data-code="${code}"]`)?.checked); }
			function synchroniserAccueil(code)
			{
				const bloc = workflow(code); if (!bloc) return;
				const actif = accueilActive(code); const contenu = bloc.querySelector(".wizard-accueil-workflow-content"); if (contenu) contenu.hidden = !actif;
			}
			assistant.querySelectorAll(".wizard-enable-accueil").forEach((input) => input.addEventListener("change", () => synchroniserAccueil(input.dataset.code)));
			["vacances", "periscolaire"].forEach(synchroniserAccueil);

			function ajouterNouveauGroupe(code)
			{
				const liste = assistant.querySelector(`[data-new-groups="${code}"]`); if (!liste) return;
				const row = document.createElement("div"); row.className = "wizard-new-group-row"; row.dataset.groupKey = `new-${code}-${Date.now()}-${liste.children.length}`;
				row.innerHTML = `<label class="field"><span>Nom</span><input class="wizard-new-group-name" placeholder="ex : Maternelle"></label><label class="field"><span>Catégorie d’âge</span><select class="wizard-new-group-age"><option value="moins_6">Moins de 6 ans</option><option value="six_plus">6 ans et plus</option><option value="autre">Autre / non réglementaire</option></select></label><label class="field"><span>Ratio manuel historique</span><input type="number" min="1" max="999" class="wizard-new-group-ratio" value="8"></label><button type="button" class="btn btn-ghost wizard-remove-new-group">Retirer</button>`;
				row.querySelector(".wizard-remove-new-group").addEventListener("click", () => { row.remove(); rendreEncadrement(code); });
				row.querySelector(".wizard-new-group-name").addEventListener("input", () => rendreEncadrement(code)); liste.appendChild(row);
			}
			assistant.querySelectorAll(".wizard-add-group").forEach((button) => button.addEventListener("click", () => ajouterNouveauGroupe(button.dataset.code)));
			assistant.querySelectorAll(".wizard-group-existing").forEach((input) => input.addEventListener("change", () => rendreEncadrement(input.dataset.code)));

			function groupesSelectionnes(code)
			{
				const resultats = [...assistant.querySelectorAll(`.wizard-group-existing[data-code="${code}"]:checked`)].map((input) => { const groupe = groupesPartages.find((item) => Number(item.id) === Number(input.value)); return { key:`id-${input.value}`, id:Number(input.value), nom:groupe?.nom || `Groupe ${input.value}` }; });
				assistant.querySelectorAll(`[data-new-groups="${code}"] .wizard-new-group-row`).forEach((row) => { const nom=row.querySelector(".wizard-new-group-name").value.trim(); if(nom) resultats.push({ key:row.dataset.groupKey, nom, categorie_age_reglementaire:row.querySelector(".wizard-new-group-age").value, enfants_par_animateur_defaut:Number(row.querySelector(".wizard-new-group-ratio").value)||8 }); }); return resultats;
			}

			function modalitesActives()
			{
				return [...assistant.querySelectorAll('[data-accueil-workflow="periscolaire"] .wizard-opening-row')].filter((row) => row.querySelector(".wizard-opening-active")?.checked).map((row) => ({ code:row.dataset.modaliteCode, nom:modalitesPeriscolaires.find((m)=>m.code===row.dataset.modaliteCode)?.nom || row.dataset.modaliteCode }));
			}
			function brancherStaffing(host)
			{
				host.querySelectorAll(".wizard-staffing-mode").forEach((select) => select.addEventListener("change", () => { const row=select.closest(".wizard-staffing-row"); row.querySelector(".wizard-staffing-reference").hidden=select.value==="manuel"; row.querySelector(".wizard-staffing-manual").hidden=select.value!=="manuel"; }));
				host.querySelectorAll(".wizard-staffing-enabled").forEach((input) => input.addEventListener("change", () => { input.closest(".wizard-staffing-row").classList.toggle("is-enabled", input.checked); }));
			}
			function rendreEncadrement(code)
			{
				const host=assistant.querySelector(`[data-staffing-for="${code}"]`); if(!host) return; const groupes=groupesSelectionnes(code);
				if(!groupes.length){ host.innerHTML='<p class="empty-note">Sélectionnez d’abord les groupes de cet accueil.</p>'; return; }
				const modalites=code==="periscolaire"?modalitesActives():[];
				host.innerHTML=groupes.map((groupe)=>`<section class="wizard-staffing-group" data-group-key="${escapeHtml(groupe.key)}"><div class="wizard-card-title"><strong>${escapeHtml(groupe.nom)}</strong></div>${code==="vacances"?staffingRowHtml("vacances","Vacances / extrascolaire"):staffingRowHtml("periscolaire","Besoin Périscolaire par défaut")}${code==="periscolaire"&&modalites.length?`<details class="wizard-staffing-exceptions"><summary>Exceptions par temps périscolaire</summary>${modalites.map((m)=>staffingRowHtml("periscolaire",m.nom,m.code,true)).join("")}</details>`:""}</section>`).join(""); brancherStaffing(host);
			}

			assistant.querySelectorAll(".wizard-opening-active").forEach((input)=>input.addEventListener("change",()=>rendreEncadrement("periscolaire")));
			rendreEncadrement("vacances"); rendreEncadrement("periscolaire");

			const inlineForm=assistant.querySelector(".wizard-inline-time-form");
			assistant.querySelector(".wizard-add-modalite")?.addEventListener("click",()=>{inlineForm.hidden=false; inlineForm.querySelector(".wizard-inline-time-name").focus();});
			inlineForm?.querySelector(".wizard-inline-time-cancel")?.addEventListener("click",()=>{inlineForm.hidden=true;});
			inlineForm?.querySelector(".wizard-inline-time-save")?.addEventListener("click",async()=>{const err=inlineForm.querySelector(".wizard-inline-time-error"); const nom=inlineForm.querySelector(".wizard-inline-time-name").value.trim(); const heure_debut=inlineForm.querySelector(".wizard-inline-time-start").value; const heure_fin=inlineForm.querySelector(".wizard-inline-time-end").value; err.textContent=""; if(!nom){err.textContent="Donnez un nom à ce temps.";return;} if((heure_debut&&!heure_fin)||(!heure_debut&&heure_fin)||(heure_debut&&heure_fin<=heure_debut)){err.textContent="Vérifiez les horaires.";return;} try{const modalite=await apiFetch("/api/modalites-periscolaires/",{method:"POST",body:JSON.stringify({nom,heure_debut,heure_fin,jour_entier:inlineForm.querySelector(".wizard-inline-time-full").checked})}); modalitesPeriscolaires.push(modalite); const table=assistant.querySelector(".wizard-opening-table"); table.insertAdjacentHTML("beforeend",openingRowHtml(modalite)); const row=table.lastElementChild; row.querySelector(".wizard-opening-active").addEventListener("change",()=>rendreEncadrement("periscolaire")); inlineForm.hidden=true; inlineForm.querySelector(".wizard-inline-time-name").value=""; afficherToast("Temps périscolaire créé.");}catch(e){err.textContent=erreurMessage(e,"Création impossible.");}});

			function ouverturesSelectionnees()
			{
				const lignes=[]; assistant.querySelectorAll('[data-accueil-workflow="periscolaire"] .wizard-opening-row').forEach((row)=>{if(!row.querySelector(".wizard-opening-active")?.checked)return; row.querySelectorAll(".wizard-opening-day:checked").forEach((jour)=>lignes.push({modalite_id:Number(row.dataset.modaliteId),modalite_code:row.dataset.modaliteCode,jour_semaine:Number(jour.value),heure_debut:row.querySelector(".wizard-opening-start").value,heure_fin:row.querySelector(".wizard-opening-end").value}));}); return lignes;
			}
			function besoinsPourGroupe(code, key)
			{
				const bloc=assistant.querySelector(`[data-staffing-for="${code}"] [data-group-key="${CSS.escape(key)}"]`); if(!bloc)return[]; const lignes=[]; bloc.querySelectorAll(".wizard-staffing-row").forEach((row)=>{if(row.classList.contains("is-optional")&&!row.querySelector(".wizard-staffing-enabled")?.checked)return; const qualifications={}; row.querySelectorAll("[data-wizard-qualification-id]").forEach((input)=>{const n=Number(input.value)||0;if(n>0)qualifications[input.dataset.wizardQualificationId]=n;}); const mode=row.querySelector(".wizard-staffing-mode").value; lignes.push({type_accueil:row.dataset.type,modalite_periscolaire:row.dataset.modalite||null,mode_calcul:mode,effectif_cible:Number(row.querySelector(".wizard-staffing-postes").value)||1,effectif_enfants_reference:row.querySelector(".wizard-staffing-ref").value===""?null:Number(row.querySelector(".wizard-staffing-ref").value),renforts_souhaites:Number(row.querySelector(".wizard-staffing-renforts").value)||0,qualifications_requises:qualifications});}); return lignes;
			}
			function groupesPayload(code){return groupesSelectionnes(code).map(({key,...g})=>({...g,besoins_encadrement:besoinsPourGroupe(code,key)}));}

			function accueilPayload(code)
			{
				if(!accueilActive(code))return null; const bloc=workflow(code); const base={type_accueil:code,libelle:code==="periscolaire"?(bloc.querySelector(".wizard-accueil-libelle")?.value.trim()||""):"",date_debut:bloc.querySelector(".wizard-accueil-debut").value,date_fin:bloc.querySelector(".wizard-accueil-fin").value,pedt_applicable:code==="periscolaire"&&Boolean(bloc.querySelector(".wizard-pedt")?.checked),groupes:groupesPayload(code)};
				if(code==="vacances") base.fonctionnement={permanent:bloc.querySelector(".wizard-vacances-permanent").checked,periode_ids:[...bloc.querySelectorAll(".wizard-vacances-reference:checked")].flatMap((input)=>input.dataset.periodeIds.split(",").filter(Boolean).map(Number)),jours_ouverts:[...bloc.querySelectorAll(".wizard-vacances-day:checked")].map((input)=>Number(input.value)),ferme_jours_feries:bloc.querySelector(".wizard-vacances-feries").checked};
				else base.fonctionnement={periode_calendrier_ids:[...bloc.querySelectorAll(".wizard-perisco-period:checked")].map((input)=>Number(input.value)),ouvertures:ouverturesSelectionnees().map(({modalite_code,...ligne})=>ligne)}; return base;
			}
			function lirePayload(){const accueils=[accueilPayload("vacances"),accueilPayload("periscolaire")].filter(Boolean); const payload={centre_id:centre?.id||null,accueils}; if(!centre)payload.centre={nom:assistant.querySelector(".wizard-centre-nom").value.trim(),code:assistant.querySelector(".wizard-centre-code").value.trim(),couleur:assistant.querySelector(".wizard-centre-couleur").value,adresse:assistant.querySelector(".wizard-centre-adresse").value.trim(),code_postal:assistant.querySelector(".wizard-centre-cp").value.trim(),commune:assistant.querySelector(".wizard-centre-commune").value.trim(),localisation_demandee:true}; return payload;}

			function validerAccueil(code)
			{
				if(!accueilActive(code))return ""; const bloc=workflow(code); const debut=bloc.querySelector(".wizard-accueil-debut").value; const fin=bloc.querySelector(".wizard-accueil-fin").value; if(!debut)return"La date de début de l’accueil est obligatoire."; if(fin&&fin<debut)return"La date de fin est antérieure à la date de début."; if(code==="periscolaire"&&nbPeriscoExistants&&!(bloc.querySelector(".wizard-accueil-libelle")?.value.trim()))return"Donnez un nom complémentaire au nouvel accueil Périscolaire."; if(!groupesSelectionnes(code).length)return`Choisissez au moins un groupe pour ${code==="vacances"?"les Vacances":"le Périscolaire"}.`; if(code==="vacances"){if(!bloc.querySelector(".wizard-vacances-permanent").checked&&!bloc.querySelector(".wizard-vacances-reference:checked"))return"Choisissez au moins une période de Vacances ou activez toutes les périodes."; if(!bloc.querySelector(".wizard-vacances-day:checked"))return"Choisissez au moins un jour d’ouverture Vacances.";}else{if(!bloc.querySelector(".wizard-perisco-period:checked"))return"Choisissez au moins une période scolaire."; const ouv=ouverturesSelectionnees(); if(!ouv.length)return"Activez au moins un temps périscolaire et un jour."; for(const ligne of ouv){if((ligne.heure_debut&&!ligne.heure_fin)||(!ligne.heure_debut&&ligne.heure_fin)||(ligne.heure_debut&&ligne.heure_fin<=ligne.heure_debut))return"Vérifiez les horaires des temps périscolaires.";}} return"";
			}
			function afficherEtape(numero)
			{
				etape=numero; assistant.querySelectorAll("[data-wizard-step]").forEach((section)=>{section.hidden=Number(section.dataset.wizardStep)!==numero;}); assistant.querySelectorAll("[data-wizard-step-button]").forEach((button)=>{const n=Number(button.dataset.wizardStepButton);button.classList.toggle("is-current",n===numero);button.classList.toggle("is-done",n<numero);button.disabled=n>numero;}); assistant.querySelector(".wizard-prev").hidden=numero===1; assistant.querySelector(".wizard-next").hidden=numero===4; assistant.querySelector(".wizard-submit").hidden=numero!==4;
				if(numero===2)rendreEncadrement("vacances"); if(numero===3)rendreEncadrement("periscolaire"); if(numero===4){const payload=lirePayload(); assistant.querySelector(".wizard-review").innerHTML=`<div class="wizard-review-place"><strong>${escapeHtml(centre?.nom||payload.centre?.nom||"")}</strong><span>${escapeHtml(centre?.code||payload.centre?.code||"")}</span></div>${payload.accueils.length?payload.accueils.map((a)=>`<section class="wizard-review-card"><strong>${escapeHtml(a.type_accueil==="vacances"?"Vacances / extrascolaire":(`Périscolaire${a.libelle?` — ${a.libelle}`:""}`))}</strong><span>${a.groupes.map((g)=>escapeHtml(g.nom||groupesPartages.find((x)=>Number(x.id)===Number(g.id))?.nom||"Groupe")).join(" · ")} · ${escapeHtml(libelleDate(a.date_debut))}${a.date_fin?` → ${escapeHtml(libelleDate(a.date_fin))}`:""}</span></section>`).join(""):'<p class="form-error">Aucun accueil ne sera créé.</p>'}`;} wizardHost.scrollIntoView({behavior:"smooth",block:"start"});
			}

			assistant.querySelector(".centre-wizard-close").addEventListener("click",()=>{wizardHost.hidden=true;wizardHost.innerHTML="";}); assistant.querySelector(".wizard-prev").addEventListener("click",()=>afficherEtape(Math.max(1,etape-1))); assistant.querySelector(".wizard-next").addEventListener("click",()=>{error.textContent="";let msg="";if(etape===1&&!centre&&(!assistant.querySelector(".wizard-centre-nom").value.trim()||!assistant.querySelector(".wizard-centre-code").value.trim()))msg="Le nom du lieu et son nom court sont obligatoires."; if(etape===2)msg=validerAccueil("vacances"); if(etape===3)msg=validerAccueil("periscolaire"); if(msg){error.textContent=msg;return;} afficherEtape(Math.min(4,etape+1));});
			assistant.querySelector(".wizard-submit").addEventListener("click", async () => {
				error.textContent = "";
				const payload = lirePayload();
				if (!payload.accueils.length) { error.textContent = "Configurez au moins un accueil."; return; }
				const button = assistant.querySelector(".wizard-submit");
				button.disabled = true;
				async function envoyer(recupererHistoriques = false)
				{
					const aEnvoyer = {
						...payload,
						accueils: payload.accueils.map((item) => item.type_accueil === "periscolaire"
							? {
								...item,
								fonctionnement: {
									...(item.fonctionnement || {}),
									recuperer_ouvertures_historiques: recupererHistoriques,
								},
							}
							: item),
					};
					return apiFetch("/api/centres/assistant/", { method: "POST", body: JSON.stringify(aEnvoyer) });
				}
				try
				{
					let resultat;
					try
					{
						resultat = await envoyer(false);
					}
					catch (err)
					{
						if (err?.code !== "ouvertures_historiques_a_recuperer") throw err;
						if (!confirmerRecuperationOuverturesHistoriques(err)) return;
						resultat = await envoyer(true);
					}
					afficherToast(resultat.localisation_warning || (centre ? "Accueil ajouté." : "Lieu et accueils créés."), Boolean(resultat.localisation_warning));
					wizardHost.hidden = true;
					wizardHost.innerHTML = "";
					await charger();
					if (options.onChange) options.onChange(resultat);
				}
				catch (err) { error.textContent = erreurMessage(err, "Création impossible."); }
				finally { button.disabled = false; }
			});
			afficherEtape(1);
		}

		function afficherEditionAccueil(c, accueil, host)
		{
			host.hidden = false;
			host.dataset.accueilId = accueil.id;
			host.innerHTML = `<section class="accueil-config-panel">
				<div class="accueil-config-head"><div><span class="accueil-status">${escapeHtml(accueilStatutLibelle(accueil))}</span><h4>${escapeHtml(accueil.nom_affichage || accueil.type_accueil_nom)}</h4><small>${escapeHtml(accueil.libelle_analytique || "")}</small></div><button type="button" class="btn btn-ghost accueil-config-close">Fermer</button></div>
				<div class="accueil-config-section"><div class="wizard-card-title"><strong>Informations générales</strong></div><div class="accueil-inline-edit"><label class="field"><span>Début</span><input type="date" class="accueil-edit-start" value="${escapeHtml(accueil.date_debut || "")}"></label><label class="field"><span>Fin <small>(facultatif)</small></span><input type="date" class="accueil-edit-end" value="${escapeHtml(accueil.date_fin || "")}"></label>${accueil.type_accueil_code === "periscolaire" ? `<label class="field"><span>Nom complémentaire</span><input class="accueil-edit-label" maxlength="80" value="${escapeHtml(accueil.libelle || "")}" placeholder="ex : Mercredi"></label><label class="wizard-switch"><input type="checkbox" class="accueil-edit-pedt" ${accueil.pedt_applicable ? "checked" : ""}><span>PEDT applicable</span></label>` : ""}<button type="button" class="btn btn-primary accueil-edit-save">Enregistrer</button><p class="form-error accueil-general-error"></p></div></div>
				<div class="accueil-config-section"><div class="teams-heading"><div><h4>Groupes de cet accueil</h4><p>Ces groupes et leurs besoins sont propres à ${escapeHtml(accueil.nom_affichage || accueil.type_accueil_nom)}.</p></div><button type="button" class="btn btn-secondary team-add-toggle">+ Attribuer un groupe</button></div><div class="team-list"><p class="empty-note">Chargement…</p></div><div class="team-create-form" hidden></div></div>
				${accueil.type_accueil_code === "periscolaire" ? '<div class="accueil-config-section"><div class="wizard-card-title"><strong>Fonctionnement Périscolaire</strong><button type="button" class="btn btn-secondary accueil-openings-toggle">Configurer les ouvertures</button></div><div class="periscolaire-openings-host" hidden></div></div>' : '<div class="accueil-config-section accueil-function-summary"><div class="wizard-card-title"><strong>Fonctionnement Vacances</strong><span>Les périodes et jours sont repris sur les groupes de cet accueil.</span></div></div>'}
			</section>`;
			host.querySelector(".accueil-config-close").addEventListener("click", () => { host.hidden = true; host.innerHTML = ""; enregistrerEtatLieux({ accueilId: null }); });
			host.querySelector(".accueil-edit-save").addEventListener("click", async () => {
				const err = host.querySelector(".accueil-general-error"); err.textContent = "";
				const date_debut = host.querySelector(".accueil-edit-start").value; const date_fin = host.querySelector(".accueil-edit-end").value;
				if (!date_debut) { err.textContent = "La date de début est obligatoire."; return; }
				const payload = { date_debut, date_fin, pedt_applicable: Boolean(host.querySelector(".accueil-edit-pedt")?.checked) };
				if (accueil.type_accueil_code === "periscolaire") payload.libelle = host.querySelector(".accueil-edit-label")?.value.trim() || "";
				try { await apiFetch(`/api/accueils-centres/${accueil.id}/`, { method:"PATCH", body:JSON.stringify(payload) }); afficherToast("Accueil mis à jour."); await charger(); }
				catch (e) { err.textContent = erreurMessage(e, "Modification impossible."); }
			});

			const form = host.querySelector(".team-create-form");
			function initialiserCreationInstance()
			{
				if (form.dataset.initialise) return;
				form.dataset.initialise = "1";
				form.innerHTML = `${evenementFormHtml("new-team", null, accueil.type_accueil_code, accueil)}<div class="edit-actions"><button type="button" class="btn btn-primary team-create-submit">Créer l’instance</button><button type="button" class="btn btn-ghost team-create-cancel">Annuler</button></div>`;
				initialiserFormGroupe(form, "new-team"); contextualiserFormGroupe(form, accueil.type_accueil_code);
				form.querySelector(".team-create-cancel").addEventListener("click", () => { form.hidden = true; });
				form.querySelector(".team-create-submit").addEventListener("click", () => {
					const error = form.querySelector(".new-team-error"); error.textContent = ""; const payload = lireEvenementForm(form, "new-team"); payload.accueil_id = accueil.id;
					payload.besoins_encadrement = (payload.besoins_encadrement || []).filter((item) => item.type_accueil === accueil.type_accueil_code);
					if (!payload.groupe_id || payload.jours_ouverts.length === 0) { error.textContent = "Choisissez un groupe et au moins un jour d’ouverture."; return; }
					apiFetch(`/api/centres/${c.id}/groupes/`, { method:"POST", body:JSON.stringify(payload) }).then(() => { afficherToast("Groupe ajouté à l’accueil."); chargerEvenements(c, host, accueil); if(options.onChange) options.onChange(); }).catch((err) => { error.textContent = erreurMessage(err, "Ajout impossible."); });
				});
			}
			host.querySelector(".team-add-toggle").addEventListener("click", () => { initialiserCreationInstance(); form.hidden = !form.hidden; });
			if (accueil.type_accueil_code === "periscolaire") host.querySelector(".accueil-openings-toggle").addEventListener("click", () => { const ouvertureHost = host.querySelector(".periscolaire-openings-host"); if(!ouvertureHost.hidden){ouvertureHost.hidden=true;return;} afficherConfigurationPeriscolaire(c, ouvertureHost, accueil).catch((err)=>{ouvertureHost.hidden=false;ouvertureHost.innerHTML=`<p class="form-error">${escapeHtml(erreurMessage(err,"Impossible de charger les ouvertures."))}</p>`;}); });
			chargerEvenements(c, host, accueil);
		}

		function creerCarteLieu(c)
		{
			const card = document.createElement("section"); card.className = "lieu-card"; card.dataset.lieuId = c.id; appliquerCouleurLieu(card, c.couleur); const accueils = c.accueils || [];
			card.dataset.recherche = normaliserRecherche([c.nom, c.code, c.commune].join(" "));
			card.dataset.typesAccueil = [...new Set(accueils.map((accueil) => accueil.type_accueil_code).filter(Boolean))].join(" ");
			function resumeAccueil(accueil)
			{
				const joursMap = new Map(JOURS_EVENEMENT.map((j)=>[j.numero,j.court]));
				const jours = (accueil.jours_ouverts || []).map((j)=>joursMap.get(Number(j))).filter(Boolean).join(" · ") || "À compléter";
				const groupes = (accueil.groupes_noms || []).join(" · ") || "Aucun groupe";
				const ouverture = accueil.type_accueil_code === "periscolaire"
					? `<div class="accueil-summary-section"><strong>Temps d’accueil</strong><span>${escapeHtml((accueil.modalites_noms || []).join(" · ") || "À compléter")}</span></div>`
					: `<div class="accueil-summary-section"><strong>Périodes ouvertes</strong><div class="accueil-period-lines">${(accueil.periodes_ouvertes || []).length ? accueil.periodes_ouvertes.map((periode) => `<span>${escapeHtml(periode.nom)}${periode.semaines?.length ? ` · ${escapeHtml(periode.semaines.join(", "))}` : ""}</span>`).join("") : "<span>À compléter</span>"}</div></div>`;
				const encadrement = (accueil.encadrement_groupes || []).length
					? accueil.encadrement_groupes.map((groupe) => `<div class="accueil-staffing-line"><strong>${escapeHtml(groupe.nom)}</strong><span>${escapeHtml(groupe.resume)}</span>${(groupe.details || []).length ? `<ul>${groupe.details.map((detail) => `<li><b>${escapeHtml(detail.contexte)}</b> : ${escapeHtml(detail.texte)}</li>`).join("")}</ul>` : ""}${(groupe.exigences || []).length ? `<small>Exigence particulière : ${escapeHtml(groupe.exigences.join(", "))}</small>` : ""}</div>`).join("")
					: '<span class="empty-note compact">Aucun groupe</span>';
				return `<div class="lieu-accueil-summary">${ouverture}<div class="accueil-summary-section"><strong>Jours ouverts</strong><span>${escapeHtml(jours)}</span></div><div class="accueil-summary-section"><strong>Groupes</strong><span>${escapeHtml(groupes)}</span></div><div class="accueil-summary-section accueil-summary-staffing"><strong>Encadrement</strong><div>${encadrement}</div></div></div>`;
			}
			const nomsAccueils = [...new Set(accueils.map((accueil) => accueil.nom_affichage || accueil.type_accueil_nom).filter(Boolean))];
			const resumeLieu = `${accueils.length} accueil${accueils.length > 1 ? "s" : ""}${nomsAccueils.length ? ` · ${nomsAccueils.join(" · ")}` : ""}`;
			card.innerHTML = `<div class="lieu-card-header"><button type="button" class="lieu-drag-handle" draggable="true" title="Faire glisser pour réordonner" aria-label="Déplacer ${escapeHtml(c.nom)} par glisser-déposer">⋮⋮</button><div class="lieu-card-identity"><span class="swatch lieu-swatch" style="background:${escapeHtml(c.couleur)}"></span><div><div class="lieu-title-line"><h3>${escapeHtml(c.nom)}</h3><span class="lieu-code">${escapeHtml(c.code)}</span></div><small class="lieu-compact-summary">${escapeHtml(resumeLieu)}</small><small class="lieu-address">${c.code_postal?`${escapeHtml(c.commune||"")} · ${escapeHtml(c.code_postal)}`:"Coordonnées routières à compléter"}</small></div></div><div class="lieu-actions"><button type="button" class="btn btn-ghost lieu-toggle" aria-expanded="false">Ouvrir</button></div></div>
				<div class="lieu-accueils-block" hidden><div class="lieu-inner-actions"></div><div class="lieu-accueils-grid">${accueils.length?accueils.map((accueil)=>`<article class="lieu-accueil-card ${accueil.statut === "termine" ? "is-ended" : accueil.statut === "a_venir" ? "is-upcoming" : "is-active"}" data-accueil-id="${accueil.id}"><div class="lieu-accueil-card-main"><span class="accueil-status">${escapeHtml(accueilStatutLibelle(accueil))}</span><strong>${escapeHtml(accueil.nom_affichage || accueil.type_accueil_nom)}</strong><small>${escapeHtml(accueilDateResume(accueil))}${accueil.type_accueil_code === "periscolaire" && accueil.pedt_applicable ? " · PEDT" : ""}</small><em>${escapeHtml(accueil.libelle_analytique || "")}</em>${resumeAccueil(accueil)}</div><button type="button" class="btn btn-primary accueil-configure" data-accueil-id="${accueil.id}">Configurer l’accueil</button></article>`).join(""):'<div class="empty-note">Aucun accueil configuré.</div>'}</div><div class="accueil-inline-edit-host" hidden></div></div>`;
			card.querySelector(".lieu-toggle").addEventListener("click", () => ouvrirLieuUnique(card));
			const poignee = card.querySelector(".lieu-drag-handle");
			poignee.addEventListener("dragstart", (event) => {
				carteLieuGlissee = card;
				card.classList.add("is-dragging");
				event.dataTransfer.effectAllowed = "move";
				event.dataTransfer.setData("text/plain", String(c.id));
			});
			poignee.addEventListener("dragend", () => {
				card.classList.remove("is-dragging");
				list.querySelectorAll(".lieu-card.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
				carteLieuGlissee = null;
			});
			card.addEventListener("dragover", (event) => {
				if (!carteLieuGlissee || carteLieuGlissee === card) return;
				event.preventDefault();
				card.classList.add("is-drag-over");
			});
			card.addEventListener("dragleave", () => card.classList.remove("is-drag-over"));
			card.addEventListener("drop", (event) => {
				event.preventDefault();
				card.classList.remove("is-drag-over");
				if (!carteLieuGlissee || carteLieuGlissee === card) return;
				const apres = event.clientY > card.getBoundingClientRect().top + card.offsetHeight / 2;
				list.insertBefore(carteLieuGlissee, apres ? card.nextSibling : card);
				persisterOrdreLieux();
			});
			const actions = card.querySelector(".lieu-inner-actions"); actions.appendChild(bouton("+ Ajouter un accueil","btn btn-primary",()=>ouvrirAssistantCentre(c))); actions.appendChild(bouton("Modifier le lieu","btn btn-ghost",()=>ouvrirEditionLieu(c,card))); actions.appendChild(bouton("Supprimer le lieu","btn btn-danger-ghost",()=>{if(!confirm(`Supprimer le lieu « ${c.nom} » ?`))return;apiFetch(`/api/centres/${c.id}/`,{method:"DELETE"}).then(()=>{afficherToast("Lieu supprimé.");charger();if(options.onChange)options.onChange();}).catch((err)=>afficherToast(erreurMessage(err,"Suppression impossible."),true));}));
			card.querySelectorAll(".accueil-configure").forEach((button)=>button.addEventListener("click",()=>{const accueil=accueils.find((item)=>Number(item.id)===Number(button.dataset.accueilId));const host=card.querySelector(".accueil-inline-edit-host");if(!accueil)return;if(!host.hidden&&Number(host.dataset.accueilId)===Number(accueil.id)){host.hidden=true;host.innerHTML="";enregistrerEtatLieux({accueilId:null});return;}enregistrerEtatLieux({lieuId:Number(c.id),accueilId:Number(accueil.id)});afficherEditionAccueil(c,accueil,host);})); return card;
		}

		function charger()
		{
			const positionScroll = window.scrollY;
			list.setAttribute("aria-busy", "true");
			return apiFetch("/api/centres/?tous_types=1").then((data) =>
			{
				lieuxDonnees = data;
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
				const typesPresents = new Map();
				data.forEach((lieu) => (lieu.accueils || []).forEach((accueil) => typesPresents.set(accueil.type_accueil_code, accueil.type_accueil_nom)));
				const filtreActuel = filtreLieux.value;
				filtreLieux.innerHTML = '<option value="tous">Tous les accueils</option>' + [...typesPresents].map(([code, nom]) => `<option value="${escapeHtml(code)}">${escapeHtml(nom)}</option>`).join("");
				if ([...filtreLieux.options].some((option) => option.value === filtreActuel)) filtreLieux.value = filtreActuel;
				appliquerFiltresLieux();
				const etat = lireEtatLieux();
				const cardOuverte = etat.lieuId ? list.querySelector(`.lieu-card[data-lieu-id="${CSS.escape(String(etat.lieuId))}"]`) : null;
				if (cardOuverte)
				{
					definirLieuOuvert(cardOuverte, true, false);
					const accueilBouton = etat.accueilId ? cardOuverte.querySelector(`.accueil-configure[data-accueil-id="${CSS.escape(String(etat.accueilId))}"]`) : null;
					if (accueilBouton) accueilBouton.click();
				}
				requestAnimationFrame(() => window.scrollTo({ top: positionScroll, behavior: "auto" }));
				return data;
			}).catch((err) =>
			{
				afficherToast(erreurMessage(err, "Impossible de recharger les lieux et groupes."), true);
				if (!list.children.length)
				{
					list.innerHTML = '<p class="form-error gestion-load-error">Impossible de charger les lieux et groupes. Rechargez la page pour réessayer.</p>';
				}
				throw err;
			}).finally(() =>
			{
				list.removeAttribute("aria-busy");
			});
		}

		rechercheLieux.addEventListener("input", appliquerFiltresLieux);
		filtreLieux.addEventListener("change", appliquerFiltresLieux);

		container.querySelector("#lieu-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = nomEl.value.trim();
			const code = codeEl.value.trim();
			const couleur = couleurEl.value;
			const adresse = adresseEl.value.trim();
			const code_postal = codePostalEl.value.trim();
			const commune = communeEl.value.trim();
			const code_insee = codeInseeEl.value.trim();
			const type_accueil_codes = lireTypesLieu(container.querySelector("#lieu-form"), "lieu");
			if (!nom || !code)
			{
				errorEl.textContent = "Le nom et le code sont obligatoires.";
				return;
			}
			if (!type_accueil_codes.length) { errorEl.textContent = "Choisissez au moins Vacances ou Périscolaire."; return; }
			apiFetch("/api/centres/", { method: "POST", body: JSON.stringify({ nom, code, couleur, adresse, code_postal, commune, code_insee, localisation_demandee:true, type_accueil_codes }) })
				.then((nouveau) =>
				{
					nomEl.value = "";
					codeEl.value = "";
					adresseEl.value = "";
					codePostalEl.value = "";
					communeEl.value = "";
					codeInseeEl.value = "";
					afficherToast(nouveau.localisation_warning||"Lieu ajouté. Tu peux maintenant y créer un groupe.",Boolean(nouveau.localisation_warning));
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d’ajouter ce lieu."); });
		});

		Promise.all([
			apiFetch("/api/qualifications/"),
			apiFetch("/api/periodes-scolaires/"),
			apiFetch("/api/groupes-partages/"),
			apiFetch("/api/types-accueil/"),
			apiFetch("/api/modalites-periscolaires/"),
			apiFetch("/api/periodes-calendrier/"),
		])
			.then(([qualifications, periodes, groupes, typesAccueil, modalites, referencesCalendrier]) =>
			{
				qualificationsEvenements = qualifications;
				periodesScolaires = periodes;
				groupesPartages = groupes;
				typesAccueilStructure = typesAccueil || [];
				modalitesPeriscolaires = modalites || [];
				periodesCalendrier = referencesCalendrier || [];
				periodesCalendrierScolaires = periodesCalendrier.filter((periode) => periode.categorie === "scolaire");
				container.querySelector(".lieu-types").innerHTML = typesLieuHtml("lieu", ["vacances"]);
				wizardNewButton.addEventListener("click", () => ouvrirAssistantCentre());
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
	// Temps périscolaires
	// ------------------------------------------------------------------
	function mountModalitesPeriscolaires(container)
	{
		if (!container) return null;
		container.innerHTML = `<div class="periods-intro"><div><p class="section-title">Temps périscolaires</p><p>Référentiel commun des créneaux proposés dans les accueils Périscolaire.</p></div><button type="button" class="btn btn-primary perisco-time-new">+ Ajouter un temps</button></div><div class="perisco-time-form-host" hidden></div><div class="perisco-time-list"><p class="empty-note">Chargement…</p></div>`;
		const list=container.querySelector(".perisco-time-list"); const host=container.querySelector(".perisco-time-form-host");
		function ouvrir(item=null){host.hidden=false;host.innerHTML=`<div class="gestion-form perisco-time-form"><div class="wizard-fields"><label class="field"><span>Nom</span><input class="perisco-time-name" value="${escapeHtml(item?.nom||"")}" placeholder="ex : Aide aux devoirs"></label><label class="field"><span>Début par défaut</span><input type="time" class="perisco-time-start" value="${escapeHtml(item?.heure_debut||"")}"></label><label class="field"><span>Fin par défaut</span><input type="time" class="perisco-time-end" value="${escapeHtml(item?.heure_fin||"")}"></label></div><label class="wizard-switch"><input type="checkbox" class="perisco-time-full" ${item?.jour_entier?"checked":""}><span>Journée entière</span></label><p class="form-error perisco-time-error"></p><div class="edit-actions"><button type="button" class="btn btn-primary perisco-time-save">${item?"Enregistrer":"Créer le temps"}</button><button type="button" class="btn btn-ghost perisco-time-cancel">Annuler</button></div></div>`;host.querySelector(".perisco-time-cancel").addEventListener("click",()=>{host.hidden=true;host.innerHTML="";});host.querySelector(".perisco-time-save").addEventListener("click",async()=>{const err=host.querySelector(".perisco-time-error");const nom=host.querySelector(".perisco-time-name").value.trim();const heure_debut=host.querySelector(".perisco-time-start").value;const heure_fin=host.querySelector(".perisco-time-end").value;err.textContent="";if(!nom){err.textContent="Le nom est obligatoire.";return;}if((heure_debut&&!heure_fin)||(!heure_debut&&heure_fin)||(heure_debut&&heure_fin<=heure_debut)){err.textContent="Vérifiez les horaires.";return;}try{await apiFetch(item?`/api/modalites-periscolaires/${item.id}/`:"/api/modalites-periscolaires/",{method:item?"PATCH":"POST",body:JSON.stringify({nom,heure_debut,heure_fin,jour_entier:host.querySelector(".perisco-time-full").checked})});host.hidden=true;host.innerHTML="";afficherToast(item?"Temps périscolaire modifié.":"Temps périscolaire créé.");await charger();}catch(e){err.textContent=erreurMessage(e,"Enregistrement impossible.");}});}
		async function charger(){const items=await apiFetch("/api/modalites-periscolaires/?tous=1");list.innerHTML=items.length?items.map((item)=>`<article class="perisco-time-card ${item.actif?"":"is-inactive"}" data-id="${item.id}"><div><span class="accueil-status">${item.actif?"Actif":"Archivé"}</span><strong>${escapeHtml(item.nom)}</strong><small>${escapeHtml(item.heure_debut&&item.heure_fin?`${item.heure_debut}–${item.heure_fin}`:"Horaires définis dans chaque accueil")}${item.jour_entier?" · journée entière":""}</small></div><div class="perisco-time-card-actions"><button type="button" class="btn btn-ghost perisco-time-edit">Modifier</button><button type="button" class="btn btn-secondary perisco-time-toggle">${item.actif?"Archiver":"Réactiver"}</button></div></article>`).join(""):'<p class="empty-note">Aucun temps périscolaire.</p>';list.querySelectorAll(".perisco-time-card").forEach((card)=>{const item=items.find((x)=>Number(x.id)===Number(card.dataset.id));card.querySelector(".perisco-time-edit").addEventListener("click",()=>ouvrir(item));card.querySelector(".perisco-time-toggle").addEventListener("click",async()=>{try{await apiFetch(`/api/modalites-periscolaires/${item.id}/`,{method:"PATCH",body:JSON.stringify({actif:!item.actif})});await charger();}catch(e){afficherToast(erreurMessage(e,"Modification impossible."),true);}});});}
		container.querySelector(".perisco-time-new").addEventListener("click",()=>ouvrir()); charger().catch((e)=>{list.innerHTML=`<p class="form-error">${escapeHtml(erreurMessage(e,"Chargement impossible."))}</p>`;}); return {charger};
	}

	// ------------------------------------------------------------------
	// Périodes scolaires indépendantes
	// ------------------------------------------------------------------
	function mountPeriodes(container)
	{
		const typesAccueil = [["vacances", "Vacances"], ["periscolaire", "Périscolaire"], ["sejours", "Séjour"]];
		const typeContexte = typesAccueil.some(([code]) => code === container.dataset.typeAccueilSelectionne)
			? container.dataset.typeAccueilSelectionne : "vacances";
		function choixTypes(nom, selection = typeContexte)
		{
			return `<div class="period-type-options">${typesAccueil.map(([code, libelle]) => `<label class="period-type-option"><input type="radio" name="${nom}" value="${code}" ${code === selection ? "checked" : ""} required><span>${libelle}</span></label>`).join("")}</div>`;
		}
		function typeSelectionne(root, nom)
		{
			return root.querySelector(`input[name="${nom}"]:checked`)?.value || "";
		}
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
					<p class="section-title">Vacances scolaires</p>
					
				</div>
				<span class="periods-independent-badge">Indépendant du planning</span>
			</div>

			<div class="gestion-form period-manual-form">
				<p class="section-title">Ajouter une période</p>
				<div class="edit-grid period-manual-grid">
					<div class="field"><label>Nom</label><input class="period-create-name" required></div>
					<div class="field"><label>Année scolaire</label><input class="period-create-year" maxlength="9" value="${anneeScolaireParDefaut()}" required></div>
					<div class="field"><label>Zone</label><select class="period-create-zone"><option>A</option><option>B</option><option>C</option></select></div>
					<div class="field"><label>Début</label><input class="period-create-start" type="date" required></div>
					<div class="field"><label>Fin</label><input class="period-create-end" type="date" required></div>
				</div>
				<p class="form-error period-create-error"></p>
				<button class="btn btn-primary period-create-submit" type="button">Ajouter une période de vacances manuellement</button>
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
			<section class="period-stays-section">
				<p class="section-title">Séjours</p>
				<div class="gestion-form period-stay-form"><div class="edit-grid">
					<div class="field"><label>Nom</label><input class="stay-name"></div><div class="field"><label>Destination</label><input class="stay-destination"></div>
					<div class="field"><label>Début</label><input class="stay-start" type="date"></div><div class="field"><label>Fin</label><input class="stay-end" type="date"></div>
					<div class="field"><label>Période de vacances associée</label><select class="stay-vacation"><option value="">Aucune</option></select></div>
					<div class="field"><label>Équipe</label><select class="stay-team" multiple></select></div>
				</div><p class="form-error stay-error"></p><button class="btn btn-primary stay-submit" type="button">Ajouter le séjour</button></div>
				<div class="period-stays-list"></div>
			</section>
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

		async function chargerSejours()
		{
			const data = await apiFetch("/api/sejours/");
			container.querySelector(".stay-vacation").innerHTML = '<option value="">Aucune</option>' + data.periodes_vacances.map((item) => `<option value="${item.id}">${escapeHtml(libelleNomVacances(item.nom))}</option>`).join("");
			container.querySelector(".stay-team").innerHTML = data.animateurs.map((item) => `<option value="${item.id}">${escapeHtml(`${item.prenom} ${item.nom}`)}</option>`).join("");
			container.querySelector(".period-stays-list").innerHTML = data.sejours.map((item) => `<div class="period-saved-row"><div class="period-saved-date"><strong>${escapeHtml(item.nom)}</strong><span>${escapeHtml(item.destination || "Destination non renseignée")} · ${escapeHtml(libelleDate(item.date_debut))} → ${escapeHtml(libelleDate(item.date_fin))}</span></div></div>`).join("") || '<p class="empty-note">Aucun séjour enregistré.</p>';
		}

		container.querySelector(".stay-submit").addEventListener("click", async () => {
			const form = container.querySelector(".period-stay-form");
			try {
				await apiFetch("/api/sejours/", { method: "POST", body: JSON.stringify({ nom: form.querySelector(".stay-name").value.trim(), destination: form.querySelector(".stay-destination").value.trim(), date_debut: form.querySelector(".stay-start").value, date_fin: form.querySelector(".stay-end").value, periode_vacances_id: Number(form.querySelector(".stay-vacation").value) || null, equipe_ids: [...form.querySelector(".stay-team").selectedOptions].map((item) => Number(item.value)) }) });
				afficherToast("Séjour ajouté."); await chargerSejours();
			} catch (err) { form.querySelector(".stay-error").textContent = erreurMessage(err, "Ajout impossible."); }
		});

		function payloadImport()
		{
			return {
				annee_scolaire: yearInput.value.trim(),
				zone: zoneInput.value,
				type_accueil: "vacances",
			};
		}

		async function creerPeriode()
		{
			const form = container.querySelector(".period-manual-form");
			const error = form.querySelector(".period-create-error");
			error.textContent = "";
			try {
				await apiFetch("/api/periodes-scolaires/", { method: "POST", body: JSON.stringify({
					nom: form.querySelector(".period-create-name").value.trim(),
					annee_scolaire: form.querySelector(".period-create-year").value.trim(),
					zone: form.querySelector(".period-create-zone").value,
					debut: form.querySelector(".period-create-start").value,
					fin: form.querySelector(".period-create-end").value,
					type_accueil: "vacances",
				}) });
				form.querySelector(".period-create-name").value = "";
				form.querySelector(".period-create-start").value = "";
				form.querySelector(".period-create-end").value = "";
				afficherToast("Période ajoutée.");
				await chargerBibliotheque();
			} catch (err) { error.textContent = erreurMessage(err, "Ajout impossible."); }
		}

		function rendrePreview(data)
		{
			previewData = data;
			const rows = (data.groupes || []).map((groupe) => `<tbody><tr class="period-group-row"><th colspan="4">${escapeHtml(libelleNomVacances(groupe.nom))}</th></tr>${groupe.semaines.map((periode) => `
				<tr><td><input class="vacation-week-choice" type="checkbox" value="${periode.debut}" ${periode.deja_enregistree ? "disabled" : "checked"}></td>
				<td><strong>Semaine du ${escapeHtml(libelleDate(periode.debut))} au ${escapeHtml(libelleDate(periode.fin))}</strong>${periode.deja_enregistree ? '<span class="period-existing">Déjà enregistrée</span>' : ""}</td>
				<td>${escapeHtml(libelleDate(periode.debut))}</td><td>${escapeHtml(libelleDate(periode.fin))}</td></tr>`).join("")}</tbody>`).join("");

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
							<thead><tr><th></th><th>Semaine</th><th>Du</th><th>Au</th></tr></thead>${rows}
						</table>
					</div>
					<div class="period-preview-actions">
						<button class="btn btn-ghost period-select-all" type="button">Tout sélectionner</button><button class="btn btn-ghost period-select-none" type="button">Tout désélectionner</button>
						<button class="btn btn-primary" id="period-import-button" type="button">Enregistrer les semaines sélectionnées</button>
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
			previewZone.querySelector(".period-select-all").addEventListener("click", () => previewZone.querySelectorAll(".vacation-week-choice:not(:disabled)").forEach((item) => { item.checked = true; }));
			previewZone.querySelector(".period-select-none").addEventListener("click", () => previewZone.querySelectorAll(".vacation-week-choice:not(:disabled)").forEach((item) => { item.checked = false; }));
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
					body: JSON.stringify({ ...payloadImport(), semaine_ids: [...previewZone.querySelectorAll(".vacation-week-choice:checked")].map((item) => item.value) }),
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
							<div class="period-saved-date"><strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong><span>${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}</span><span class="period-type-badge">${escapeHtml(periode.type_accueil_nom || "Type non renseigné")}</span></div>
							<div class="entity-actions"></div>
						`;
						row.querySelector(".entity-actions").appendChild(bouton("Modifier", "btn btn-ghost", () =>
						{
							const typeName = `period_edit_type_${periode.id}`;
							row.innerHTML = `<div class="period-edit-form"><div class="edit-grid">
								<div class="field"><label>Nom</label><input class="period-edit-name" value="${escapeHtml(periode.nom)}"></div>
								<div class="field"><label>Année scolaire</label><input class="period-edit-year" value="${escapeHtml(periode.annee_scolaire)}"></div>
								<div class="field"><label>Zone</label><select class="period-edit-zone"><option ${periode.zone === "A" ? "selected" : ""}>A</option><option ${periode.zone === "B" ? "selected" : ""}>B</option><option ${periode.zone === "C" ? "selected" : ""}>C</option></select></div>
								<div class="field"><label>Début</label><input class="period-edit-start" type="date" value="${periode.debut}"></div>
								<div class="field"><label>Fin</label><input class="period-edit-end" type="date" value="${periode.fin}"></div>
							</div><div class="field"><span class="field-label">Type d'accueil</span>${choixTypes(typeName, periode.type_accueil)}</div><p class="form-error period-edit-error"></p><div class="edit-actions"><button class="btn btn-primary period-edit-save" type="button">Enregistrer</button><button class="btn btn-ghost period-edit-cancel" type="button">Annuler</button></div></div>`;
							row.querySelector(".period-edit-cancel").addEventListener("click", rendreBibliotheque);
							row.querySelector(".period-edit-save").addEventListener("click", async () => {
								try {
									await apiFetch(`/api/periodes-scolaires/${periode.id}/`, { method: "PATCH", body: JSON.stringify({ nom: row.querySelector(".period-edit-name").value.trim(), annee_scolaire: row.querySelector(".period-edit-year").value.trim(), zone: row.querySelector(".period-edit-zone").value, debut: row.querySelector(".period-edit-start").value, fin: row.querySelector(".period-edit-end").value, type_accueil: typeSelectionne(row, typeName) }) });
									afficherToast("Période modifiée.");
									await chargerBibliotheque();
								} catch (err) { row.querySelector(".period-edit-error").textContent = erreurMessage(err, "Modification impossible."); }
							});
						}));
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
		container.querySelector(".period-create-submit").addEventListener("click", creerPeriode);
		filterYear.addEventListener("change", rendreBibliotheque);
		chargerBibliotheque().catch((err) =>
		{
			library.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(err, "Impossible de charger les périodes."))}</p>`;
		});
		chargerSejours().catch(() => {});

		return { charger: chargerBibliotheque };
	}

	function mountPeriodesScolaires(container)
	{
		const maintenant = new Date();
		const debut = maintenant.getMonth() >= 6 ? maintenant.getFullYear() : maintenant.getFullYear() - 1;
		container.innerHTML = `<div class="periods-intro"><div><p class="section-title">Périodes scolaires</p><p>Calendrier de référence commun à toutes les modalités du Périscolaire.</p></div><span class="periods-independent-badge">Référence commune</span></div>
			<div class="gestion-form school-period-form"><div class="period-import-grid"><div class="field"><label>Année scolaire</label><input class="school-year" value="${debut}-${debut + 1}"></div><div class="field"><label>Zone</label><select class="school-zone"><option>A</option><option>B</option><option>C</option></select></div><button class="btn btn-primary school-preview" type="button">Calculer les périodes scolaires</button></div><p class="form-error school-error"></p></div><div class="school-preview-zone"></div>`;
		const zone = container.querySelector(".school-preview-zone");
		const payloadBase = () => ({ annee_scolaire: container.querySelector(".school-year").value.trim(), zone: container.querySelector(".school-zone").value });
		container.querySelector(".school-preview").addEventListener("click", async () => {
			try {
				const data = await apiFetch("/api/calendrier-scolaire/previsualiser/", { method: "POST", body: JSON.stringify(payloadBase()) });
				zone.innerHTML = `<section class="period-preview-card"><div class="school-reference-note"><strong>Référence commune</strong><span>Ces semaines sont enregistrées une seule fois. Les créneaux matin, midi, soir, mercredi… se configurent ensuite dans chaque lieu.</span></div><div class="school-reference-list">${data.periodes.map((periode, index) => `<article class="school-reference-card"><label><input class="school-period-choice" type="checkbox" value="${index}" checked><strong>${escapeHtml(periode.nom)}</strong>${periode.deja_enregistree ? '<span class="period-existing">Référence déjà enregistrée — rattachement possible sans duplication</span>' : ""}</label><ul>${periode.semaines.map((semaine) => `<li>Semaine du ${escapeHtml(libelleDate(semaine.debut))} au ${escapeHtml(libelleDate(semaine.fin))}<small>Jours scolaires : ${semaine.jours_scolaires.map(libelleDate).join(", ")}</small></li>`).join("")}</ul></article>`).join("")}</div><div class="period-preview-actions"><button class="btn btn-ghost school-all" type="button">Tout sélectionner</button><button class="btn btn-ghost school-none" type="button">Tout désélectionner</button><button class="btn btn-primary school-save" type="button">Enregistrer les périodes sélectionnées</button></div><p class="form-error school-save-error"></p></section>`;
				zone.querySelector(".school-all").addEventListener("click", () => zone.querySelectorAll(".school-period-choice:not(:disabled)").forEach((item) => { item.checked = true; }));
				zone.querySelector(".school-none").addEventListener("click", () => zone.querySelectorAll(".school-period-choice:not(:disabled)").forEach((item) => { item.checked = false; }));
				zone.querySelector(".school-save").addEventListener("click", async () => {
					try {
						await apiFetch("/api/calendrier-scolaire/enregistrer/", { method: "POST", body: JSON.stringify({ ...payloadBase(), type_accueil: "periscolaire", periode_ids: [...zone.querySelectorAll(".school-period-choice:checked")].map((item) => Number(item.value)) }) });
						afficherToast("Périodes scolaires enregistrées.");
					} catch (err) { zone.querySelector(".school-save-error").textContent = erreurMessage(err, "Enregistrement impossible."); }
				});
			} catch (err) { container.querySelector(".school-error").textContent = erreurMessage(err, "Calcul impossible."); }
		});
	}

	// ------------------------------------------------------------------
	return { mountCentres, mountGroupes, mountModalitesPeriscolaires, mountQualifications, mountPeriodes, mountPeriodesScolaires };
})();
