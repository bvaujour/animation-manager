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
		container.innerHTML = `
			<p class="section-title">Qualifications existantes</p>
			<div class="entity-list" id="qualifs-list"></div>
			<p class="section-title">Ajouter une qualification</p>
			<div class="gestion-form" id="qualif-form">
				<div class="field">
					<label for="qualif-nom">Nom</label>
					<input type="text" id="qualif-nom" name="qualification_nom" placeholder="ex : BAFA">
				</div>
				<label class="checkbox-option">
					<input type="checkbox" id="qualif-auto" name="qualification_auto">
					<span>Proposer cette qualification dans le remplissage automatique</span>
				</label>
				<p class="form-error" id="qualif-error"></p>
				<button class="btn btn-primary" id="qualif-submit" type="button">Ajouter</button>
			</div>
		`;

		const list = container.querySelector("#qualifs-list");
		const input = container.querySelector("#qualif-nom");
		const autoEl = container.querySelector("#qualif-auto");
		const errorEl = container.querySelector("#qualif-error");

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
					<p class="form-error edit-error"></p>
				</div>
			`;


			const error = row.querySelector(".edit-error");
			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const nom = champValeur(row, ".edit-qualif-nom");
				const selectionnable_remplissage_auto = row.querySelector(".edit-qualif-auto").checked;

				if (!nom)
				{
					error.textContent = "Le nom est obligatoire.";
					return;
				}

				apiFetch(`/api/qualifications/${escapeHtml(q.id)}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom, selectionnable_remplissage_auto }),
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
				list.innerHTML = "";

				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucune qualification pour l\'instant.</p>';
					return data;
				}

				data.forEach((q) =>
				{
					const row = document.createElement("div");
					row.classList.add("entity-row");
					row.innerHTML = `
						<div class="entity-main">
							<span class="truncate">${escapeHtml(q.nom)}</span>
							<span class="entity-meta">${q.selectionnable_remplissage_auto !== false ? "Disponible en auto" : "Masquée dans l’auto"}</span>
						</div>
						<div class="entity-actions"></div>
					`;

					const actions = row.querySelector(".entity-actions");
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEdition(q, row)));
					actions.appendChild(bouton("&times; Supprimer", "btn-danger", () =>
					{
						if (!confirm(`Supprimer la qualification "${escapeHtml(q.nom)}" ?`)) return;

						apiFetch(`/api/qualifications/${escapeHtml(q.id)}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Qualification supprimée.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					}));

					list.appendChild(row);
				});

				return data;
			});
		}

		container.querySelector("#qualif-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = input.value.trim();
			const selectionnable_remplissage_auto = autoEl.checked;

			if (!nom)
			{
				errorEl.textContent = "Le nom est obligatoire.";
				return;
			}

			apiFetch("/api/qualifications/", { method: "POST", body: JSON.stringify({ nom, selectionnable_remplissage_auto }) })
				.then((nouvelle) =>
				{
					input.value = "";
					autoEl.checked = false;
					afficherToast("Qualification ajoutée.");
					charger();
					if (options.onChange) options.onChange(nouvelle);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter cette qualification."); });
		});

		charger();
		return { charger };
	}

	// ------------------------------------------------------------------
	// Lieux
	// ------------------------------------------------------------------
	function mountCentres(container, options = {})
	{
		let qualificationsEvenements = [];
		let periodesScolaires = [];
		container.innerHTML = `
			<p class="section-title">Lieux et groupes</p>
			<p class="section-help">Chaque lieu peut accueillir plusieurs groupes sur les périodes enregistrées.</p>
			<div class="lieux-cards" id="lieux-list"></div>
			<p class="section-title">Ajouter un lieu</p>
			<div class="gestion-form" id="lieu-form">
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
				groupe ? (groupe.periode_ids || []).map(Number) : periodesScolaires.map((periode) => Number(periode.id))
			);
			const ensembles = new Map();
			let groupesPeriode;
			periodesScolaires.forEach((periode) => {
				const cle = `${periode.annee_scolaire} — Zone ${periode.zone}`;
				if (!ensembles.has(cle)) ensembles.set(cle, []);
				groupesPeriode = ensembles.get(cle);
				groupesPeriode.push(periode);
			});

			return [...ensembles.entries()].map(([titre, periodes]) => `
				<fieldset class="group-period-fieldset">
					<legend>${escapeHtml(titre)}</legend>
					<div class="group-period-grid">
						${periodes.map((periode) => {
							const id = `${uid}-periode-${periode.id}`;
							return `<label class="group-period-option" for="${id}">
								<input type="checkbox" id="${id}" name="${uid}_periode_${periode.id}" class="${prefix}-periode" value="${periode.id}" ${selectionnees.has(Number(periode.id)) ? "checked" : ""}>
								<span><strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong><small>${escapeHtml(libelleDate(periode.debut))} → ${escapeHtml(libelleDate(periode.fin))}</small></span>
							</label>`;
						}).join("")}
					</div>
				</fieldset>
			`).join("");
		}

		function evenementFormHtml(prefix, groupe = null)
		{
			const uid = identifiantChamp(`groupe-${groupe?.id || "nouveau"}`);
			const nomId = `${uid}-nom`;
			const effectifId = `${uid}-effectif`;
			const feriesId = `${uid}-feries`;
			const besoins = groupe?.qualifications_requises || {};
			const joursSelectionnes = new Set(
				(groupe?.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number)
			);
			const qualifsHtml = qualificationsEvenements.length
				? qualificationsEvenements.map((q) => {
					const qualificationId = `${uid}-qualification-${q.id}`;
					return `<label class="qualification-requirement" for="${qualificationId}">
						<span>${escapeHtml(q.nom)}</span>
						<input type="number" id="${qualificationId}" name="${uid}_qualification_${q.id}" min="0" step="1" value="${besoins[String(q.id)] || 0}" data-qualification-id="${q.id}">
					</label>`;
				}).join("")
				: '<p class="empty-note">Aucune qualification configurée.</p>';

			const joursHtml = JOURS_EVENEMENT.map((jour) => {
				const id = `${uid}-jour-${jour.numero}`;
				return `<label class="group-weekday-option" for="${id}">
					<input type="checkbox" id="${id}" name="${uid}_jour_${jour.numero}" class="${prefix}-jour-ouvert" value="${jour.numero}" ${joursSelectionnes.has(jour.numero) ? "checked" : ""}>
					<span title="${escapeHtml(jour.long)}">${escapeHtml(jour.court)}</span>
				</label>`;
			}).join("");

			return `
				<div class="team-form-grid">
					<div class="field team-name-field"><label for="${nomId}">Nom du groupe</label><input type="text" id="${nomId}" name="${uid}_nom" class="${prefix}-nom" value="${escapeHtml(groupe?.nom || "")}" placeholder="ex : Maternelles"></div>
					<div class="field"><label for="${effectifId}">Personnel nécessaire par jour</label><input type="number" id="${effectifId}" name="${uid}_effectif" class="${prefix}-effectif" value="${groupe?.effectif_cible || 1}" min="1" step="1"></div>
				</div>
				<section class="event-opening-settings">
					<div class="event-setting-heading"><strong>Périodes</strong><span>Facultatif : sans période, le groupe est conservé dans Gestion mais n’apparaît pas dans les calendriers.</span></div>
					<div class="group-period-actions">
						<button type="button" class="btn btn-ghost ${prefix}-periods-all">Tout cocher</button>
						<button type="button" class="btn btn-ghost ${prefix}-periods-none">Tout décocher</button>
					</div>
					<div class="group-periods">${periodesFormHtml(uid, prefix, groupe)}</div>
					<div class="event-setting-heading"><strong>Jours ouverts</strong><span>Lundi à samedi ouverts par défaut ; dimanche fermé.</span></div>
					<div class="group-weekdays">${joursHtml}</div>
					<div class="group-closure-options">
						<label class="checkbox-option" for="${feriesId}"><input type="checkbox" id="${feriesId}" name="${uid}_ferme_jours_feries" class="${prefix}-ferme-feries" ${groupe?.ferme_jours_feries !== false ? "checked" : ""}><span>Fermé les jours fériés</span></label>
					</div>
				</section>
				<div class="event-qualifications"><strong>Qualifications requises chaque jour</strong>${qualifsHtml}</div>
				<p class="form-error ${prefix}-error"></p>`;
		}

		function initialiserFormGroupe(root, prefix)
		{
			root.querySelector(`.${prefix}-periods-all`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = true; });
			});
			root.querySelector(`.${prefix}-periods-none`)?.addEventListener("click", () => {
				root.querySelectorAll(`.${prefix}-periode`).forEach((input) => { input.checked = false; });
			});
		}

		function lireEvenementForm(root, prefix)
		{
			const qualifications_requises = {};
			root.querySelectorAll('[data-qualification-id]').forEach((input) => {
				const nombre = parseInt(input.value, 10) || 0;
				if (nombre > 0) qualifications_requises[input.dataset.qualificationId] = nombre;
			});
			return {
				nom: champValeur(root, `.${prefix}-nom`),
				periode_ids: Array.from(root.querySelectorAll(`.${prefix}-periode:checked`)).map((input) => Number(input.value)),
				effectif_cible: parseInt(champValeur(root, `.${prefix}-effectif`), 10) || 1,
				jours_ouverts: Array.from(root.querySelectorAll(`.${prefix}-jour-ouvert:checked`)).map((input) => Number(input.value)),
				ferme_jours_feries: root.querySelector(`.${prefix}-ferme-feries`).checked,
				qualifications_requises,
			};
		}

		function periodeLibelle(groupe)
		{
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
					<div class="lieu-total-readonly"><span>Effectif global</span><strong>${escapeHtml(c.effectif_cible)}</strong><small>calculé depuis les groupes</small></div>
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
				if (!payload.nom || payload.jours_ouverts.length === 0)
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
						<div><h4>Groupes de ce lieu</h4><p>Les périodes sont facultatives ; sans période, le groupe reste uniquement dans Gestion.</p></div>
						<button type="button" class="btn btn-secondary team-add-toggle">+ Ajouter un groupe</button>
					</div>
					<div class="team-list"><p class="empty-note">Chargement…</p></div>
					<div class="team-create-form" hidden>
						${evenementFormHtml("new-team")}
						<div class="edit-actions">
							<button type="button" class="btn btn-primary team-create-submit">Ajouter le groupe</button>
							<button type="button" class="btn btn-ghost team-create-cancel">Annuler</button>
						</div>
					</div>
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
			initialiserFormGroupe(form, "new-team");
			card.querySelector(".team-add-toggle").addEventListener("click", () =>
			{
				form.hidden = !form.hidden;
				if (!form.hidden) form.querySelector(".new-team-nom").focus();
			});
			card.querySelector(".team-create-cancel").addEventListener("click", () => { form.hidden = true; });
			card.querySelector(".team-create-submit").addEventListener("click", () =>
			{
				const error = form.querySelector(".new-team-error");
				error.textContent = "";
				const payload = lireEvenementForm(form, "new-team");
				if (!payload.nom || payload.jours_ouverts.length === 0)
				{
					error.textContent = "Le nom et au moins un jour d’ouverture sont obligatoires.";
					return;
				}
				apiFetch(`/api/centres/${c.id}/groupes/`, {
					method: "POST",
					body: JSON.stringify(payload),
				}).then(() =>
				{
					afficherToast("Groupe ajouté.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Ajout impossible."); });
			});

			chargerEvenements(c, card);
			return card;
		}

		function charger()
		{
			return apiFetch("/api/centres/").then((data) =>
			{
				list.innerHTML = "";
				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucun lieu pour l’instant.</p>';
					return data;
				}
				data.forEach((lieu) => list.appendChild(creerCarteLieu(lieu)));
				return data;
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

		Promise.all([apiFetch("/api/qualifications/"), apiFetch("/api/periodes-scolaires/")]).then(([qualifications, periodes]) => { qualificationsEvenements = qualifications; periodesScolaires = periodes; return charger(); });
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
					<p class="section-help">Choisis une année scolaire et une zone. Le logiciel récupère les dates officielles et les découpe en semaines complètes du lundi au vendredi.</p>
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
					<p class="section-help">Cette bibliothèque n'est encore reliée à aucune autre fonctionnalité.</p>
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

			const groupes = new Map();
			visibles.forEach((periode) =>
			{
				const cle = `${periode.annee_scolaire}|${periode.zone}`;
				if (!groupes.has(cle)) groupes.set(cle, []);
				groupes.get(cle).push(periode);
			});

			groupes.forEach((periodes, cle) =>
			{
				const [annee, zone] = cle.split("|");
				const section = document.createElement("section");
				section.className = "period-year-card";
				section.innerHTML = `
					<div class="period-year-head">
						<div><h3>${escapeHtml(annee)}</h3><p>Zone ${escapeHtml(zone)} · ${periodes.length} période${periodes.length > 1 ? "s" : ""}</p></div>
					</div>
					<div class="period-saved-list"></div>
				`;
				const list = section.querySelector(".period-saved-list");
				periodes.forEach((periode) =>
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
	return { mountCentres, mountQualifications, mountPeriodes };
})();
