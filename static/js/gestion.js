// ===========================================================================
// gestion.js
// ---------------------------------------------------------------------------
// Module CRUD de la page /gestion/ pour les paramètres partagés :
// salariés, lieux, événements et qualifications sont réunis dans /gestion/.
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

	function resetFormAnimateur(form)
	{
		form.querySelector("#anim-prenom").value = "";
		form.querySelector("#anim-nom").value = "";
		form.querySelector("#anim-telephone").value = "";
		form.querySelector("#anim-email").value = "";
		form.querySelector("#anim-date-naissance").value = "";
		form.querySelectorAll("#anim-qualifs input:checked").forEach((el) => { el.checked = false; });
		form.querySelectorAll("#anim-lieux input").forEach((el) => { el.checked = false; el.disabled = false; });
	}

	function qualificationCheckboxes(qualifications, cochees = [])
	{
		return FormOptionsUtils.qualifications(qualifications, cochees);
	}

	function lieuxHierarchisesInputs(lieux, centrePrefere = null, lieuxSecondaires = [], groupe = "lieu-prefere")
	{
		return FormOptionsUtils.lieuxHierarchises(lieux, centrePrefere, lieuxSecondaires, groupe);
	}

	function lieuxHierarchisesDepuisForm(root)
	{
		return FormOptionsUtils.lireLieuxHierarchises(root);
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
		container.innerHTML = `
			<p class="section-title">Lieux et événements</p>
			<p class="section-help">Chaque lieu peut accueillir plusieurs événements sur des périodes différentes.</p>
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

		function isoDate(date)
		{
			return formatDateLocal(date);
		}

		function dateDansPeriode(dateStr, debut, fin)
		{
			return Boolean(debut && fin && dateStr >= debut && dateStr <= fin);
		}

		function ajouterJoursDate(date, jours)
		{
			const copie = new Date(date.getFullYear(), date.getMonth(), date.getDate());
			copie.setDate(copie.getDate() + jours);
			return copie;
		}

		function paques(annee)
		{
			const a = annee % 19;
			const b = Math.floor(annee / 100);
			const c = annee % 100;
			const d = Math.floor(b / 4);
			const e = b % 4;
			const f = Math.floor((b + 8) / 25);
			const g = Math.floor((b - f + 1) / 3);
			const h = (19 * a + b - d - g + 15) % 30;
			const i = Math.floor(c / 4);
			const k = c % 4;
			const l = (32 + 2 * e + 2 * i - h - k) % 7;
			const m = Math.floor((a + 11 * h + 22 * l) / 451);
			const mois = Math.floor((h + l - 7 * m + 114) / 31);
			const jour = ((h + l - 7 * m + 114) % 31) + 1;
			return new Date(annee, mois - 1, jour);
		}

		function joursFeriesFrancais(annee)
		{
			const dimanchePaques = paques(annee);
			return [
				new Date(annee, 0, 1),
				ajouterJoursDate(dimanchePaques, 1),
				new Date(annee, 4, 1),
				new Date(annee, 4, 8),
				ajouterJoursDate(dimanchePaques, 39),
				ajouterJoursDate(dimanchePaques, 50),
				new Date(annee, 6, 14),
				new Date(annee, 7, 15),
				new Date(annee, 10, 1),
				new Date(annee, 10, 11),
				new Date(annee, 11, 25),
			];
		}

		function initialiserCalendrierExclusions(root, prefix)
		{
			const debutInput = root.querySelector(`.${prefix}-debut`);
			const finInput = root.querySelector(`.${prefix}-fin`);
			const hiddenInput = root.querySelector(`.${prefix}-dates-exclues`);
			const calendar = root.querySelector(`.${prefix}-exclusion-calendar`);
			if (!debutInput || !finInput || !hiddenInput || !calendar) return;

			const titre = calendar.querySelector(".event-calendar-title");
			const grille = calendar.querySelector(".event-calendar-grid");
			const compteur = root.querySelector(`.${prefix}-exclusions-count`);
			let moisCourant = debutInput.value
				? new Date(parseLocalDate(debutInput.value).getFullYear(), parseLocalDate(debutInput.value).getMonth(), 1)
				: new Date(new Date().getFullYear(), new Date().getMonth(), 1);

			function datesExclues()
			{
				return new Set((hiddenInput.value || "").split(",").filter(Boolean));
			}

			function enregistrerDates(dates)
			{
				const debut = debutInput.value;
				const fin = finInput.value;
				const nettoyees = [...dates]
					.filter((date) => dateDansPeriode(date, debut, fin))
					.sort();
				hiddenInput.value = nettoyees.join(",");
				if (compteur)
				{
					compteur.textContent = nettoyees.length
						? `${nettoyees.length} date${nettoyees.length > 1 ? "s" : ""} exclue${nettoyees.length > 1 ? "s" : ""}`
						: "Aucune date exclue";
				}
			}

			function joursOuverts()
			{
				return new Set(Array.from(root.querySelectorAll(`.${prefix}-jour-ouvert:checked`)).map((input) => Number(input.value)));
			}

			function bornerMois()
			{
				if (!debutInput.value || !finInput.value) return;
				const debut = parseLocalDate(debutInput.value);
				const fin = parseLocalDate(finInput.value);
				const premierMois = new Date(debut.getFullYear(), debut.getMonth(), 1);
				const dernierMois = new Date(fin.getFullYear(), fin.getMonth(), 1);
				if (moisCourant < premierMois) moisCourant = premierMois;
				if (moisCourant > dernierMois) moisCourant = dernierMois;
			}

			function rendreCalendrier()
			{
				bornerMois();
				const debut = debutInput.value;
				const fin = finInput.value;
				const exclusions = datesExclues();
				const ouverts = joursOuverts();
				titre.textContent = moisCourant.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
				grille.innerHTML = "";

				["L", "M", "M", "J", "V", "S", "D"].forEach((jour) =>
				{
					const entete = document.createElement("span");
					entete.className = "event-calendar-weekday";
					entete.textContent = jour;
					grille.appendChild(entete);
				});

				const premierJour = new Date(moisCourant.getFullYear(), moisCourant.getMonth(), 1);
				const decalage = (premierJour.getDay() + 6) % 7;
				const debutGrille = ajouterJoursDate(premierJour, -decalage);
				for (let index = 0; index < 42; index += 1)
				{
					const date = ajouterJoursDate(debutGrille, index);
					const dateStr = isoDate(date);
					const numeroJour = (date.getDay() + 6) % 7;
					const boutonJour = document.createElement("button");
					boutonJour.type = "button";
					boutonJour.className = "event-calendar-day";
					boutonJour.textContent = String(date.getDate());
					boutonJour.title = date.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
					if (date.getMonth() !== moisCourant.getMonth()) boutonJour.classList.add("is-other-month");
					if (!dateDansPeriode(dateStr, debut, fin))
					{
						boutonJour.disabled = true;
						boutonJour.classList.add("is-outside-period");
					}
					else
					{
						if (!ouverts.has(numeroJour)) boutonJour.classList.add("is-closed-weekday");
						if (exclusions.has(dateStr)) boutonJour.classList.add("is-excluded");
						boutonJour.addEventListener("click", () =>
						{
							const dates = datesExclues();
							if (dates.has(dateStr)) dates.delete(dateStr);
							else dates.add(dateStr);
							enregistrerDates(dates);
							rendreCalendrier();
						});
					}
					grille.appendChild(boutonJour);
				}
				enregistrerDates(exclusions);
			}

			calendar.querySelector("[data-calendar-prev]").addEventListener("click", () =>
			{
				moisCourant = new Date(moisCourant.getFullYear(), moisCourant.getMonth() - 1, 1);
				rendreCalendrier();
			});
			calendar.querySelector("[data-calendar-next]").addEventListener("click", () =>
			{
				moisCourant = new Date(moisCourant.getFullYear(), moisCourant.getMonth() + 1, 1);
				rendreCalendrier();
			});

			root.querySelector(`.${prefix}-exclude-holidays`).addEventListener("click", () =>
			{
				if (!debutInput.value || !finInput.value) return;
				const dates = datesExclues();
				const debut = parseLocalDate(debutInput.value);
				const fin = parseLocalDate(finInput.value);
				for (let annee = debut.getFullYear(); annee <= fin.getFullYear(); annee += 1)
				{
					joursFeriesFrancais(annee).forEach((date) =>
					{
						const dateStr = isoDate(date);
						if (dateDansPeriode(dateStr, debutInput.value, finInput.value)) dates.add(dateStr);
					});
				}
				enregistrerDates(dates);
				rendreCalendrier();
			});

			root.querySelector(`.${prefix}-exclude-weekends`).addEventListener("click", () =>
			{
				if (!debutInput.value || !finInput.value) return;
				const dates = datesExclues();
				let date = parseLocalDate(debutInput.value);
				const fin = parseLocalDate(finInput.value);
				while (date <= fin)
				{
					if (date.getDay() === 0 || date.getDay() === 6) dates.add(isoDate(date));
					date = ajouterJoursDate(date, 1);
				}
				enregistrerDates(dates);
				rendreCalendrier();
			});

			root.querySelector(`.${prefix}-clear-exclusions`).addEventListener("click", () =>
			{
				enregistrerDates(new Set());
				rendreCalendrier();
			});

			[debutInput, finInput].forEach((input) => input.addEventListener("change", () =>
			{
				if (debutInput.value)
				{
					const debut = parseLocalDate(debutInput.value);
					moisCourant = new Date(debut.getFullYear(), debut.getMonth(), 1);
				}
				enregistrerDates(datesExclues());
				rendreCalendrier();
			}));
			root.querySelectorAll(`.${prefix}-jour-ouvert`).forEach((input) => input.addEventListener("change", rendreCalendrier));
			rendreCalendrier();
		}

		function evenementFormHtml(prefix, evenement = null)
		{
			const uid = identifiantChamp(`evenement-${evenement?.id || "nouveau"}`);
			const nomId = `${uid}-nom`;
			const debutId = `${uid}-debut`;
			const finId = `${uid}-fin`;
			const effectifId = `${uid}-effectif`;
			const activeId = `${uid}-active`;
			const active = evenement ? evenement.active : true;
			const besoins = evenement?.qualifications_requises || {};
			const joursOuverts = new Set((evenement?.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number));
			const datesExclues = evenement?.dates_exclues || [];
			const joursHtml = JOURS_EVENEMENT.map((jour) =>
			{
				const inputId = `${uid}-jour-${jour.numero}`;
				return `<label class="event-weekday-option" for="${inputId}"><input type="checkbox" id="${inputId}" name="${uid}_jour_${jour.numero}" value="${jour.numero}" class="${prefix}-jour-ouvert" ${joursOuverts.has(jour.numero) ? "checked" : ""}><span>${jour.court}</span></label>`;
			}).join("");
			const qualifsHtml = qualificationsEvenements.length
				? qualificationsEvenements.map((q) => {
					const qualificationId = `${uid}-qualification-${q.id}`;
					return `
					<label class="qualification-requirement" for="${qualificationId}">
						<span>${escapeHtml(q.nom)}</span>
						<input type="number" id="${qualificationId}" name="${uid}_qualification_${q.id}" min="0" step="1" value="${besoins[String(q.id)] || 0}" data-qualification-id="${q.id}">
					</label>`;
				}).join("")
				: '<p class="empty-note">Aucune qualification configurée.</p>';
			return `
				<div class="team-form-grid">
					<div class="field team-name-field"><label for="${nomId}">Nom de l’événement</label><input type="text" id="${nomId}" name="${uid}_nom" class="${prefix}-nom" value="${escapeHtml(evenement?.nom || "")}" placeholder="ex : Pacaudière maternelles"></div>
					<div class="field"><label for="${debutId}">Du</label><input type="date" id="${debutId}" name="${uid}_debut" class="${prefix}-debut" value="${escapeHtml(evenement?.debut || "")}"></div>
					<div class="field"><label for="${finId}">Au</label><input type="date" id="${finId}" name="${uid}_fin" class="${prefix}-fin" value="${escapeHtml(evenement?.fin || "")}"></div>
					<div class="field"><label for="${effectifId}">Personnel nécessaire par jour</label><input type="number" id="${effectifId}" name="${uid}_effectif" class="${prefix}-effectif" value="${evenement?.effectif_cible || 1}" min="1" step="1"></div>
					<label class="checkbox-option team-active-field" for="${activeId}"><input type="checkbox" id="${activeId}" name="${uid}_active" class="${prefix}-active" ${active ? "checked" : ""}><span>Événement actif</span></label>
				</div>
				<section class="event-opening-settings">
					<div class="event-setting-heading"><strong>Jours habituels d’ouverture</strong><span>Les autres jours seront automatiquement fermés.</span></div>
					<div class="event-weekdays">${joursHtml}</div>
					<input type="hidden" class="${prefix}-dates-exclues" name="${uid}_dates_exclues" value="${escapeHtml(datesExclues.join(","))}">
					<div class="event-exclusions-toolbar">
						<div><strong>Fermetures ponctuelles</strong><span class="${prefix}-exclusions-count"></span></div>
						<div class="event-exclusion-actions">
							<button type="button" class="btn btn-ghost ${prefix}-exclude-holidays">Jours fériés</button>
							<button type="button" class="btn btn-ghost ${prefix}-exclude-weekends">Week-ends</button>
							<button type="button" class="btn btn-ghost ${prefix}-clear-exclusions">Tout réactiver</button>
						</div>
					</div>
					<div class="event-exclusion-calendar ${prefix}-exclusion-calendar">
						<div class="event-calendar-nav">
							<button type="button" class="btn btn-icon btn-ghost" data-calendar-prev aria-label="Mois précédent">‹</button>
							<strong class="event-calendar-title"></strong>
							<button type="button" class="btn btn-icon btn-ghost" data-calendar-next aria-label="Mois suivant">›</button>
						</div>
						<div class="event-calendar-grid"></div>
					</div>
					<p class="event-calendar-help">Clique sur une date pour la fermer ou la rouvrir. Les dates fermées apparaîtront en noir dans le planning.</p>
				</section>
				<div class="event-qualifications"><strong>Qualifications requises chaque jour</strong>${qualifsHtml}</div>
				<p class="form-error ${prefix}-error"></p>`;
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
				debut: root.querySelector(`.${prefix}-debut`).value,
				fin: root.querySelector(`.${prefix}-fin`).value,
				effectif_cible: parseInt(champValeur(root, `.${prefix}-effectif`), 10) || 1,
				jours_ouverts: Array.from(root.querySelectorAll(`.${prefix}-jour-ouvert:checked`)).map((input) => Number(input.value)),
				dates_exclues: (root.querySelector(`.${prefix}-dates-exclues`).value || "").split(",").filter(Boolean),
				qualifications_requises,
				active: root.querySelector(`.${prefix}-active`).checked,
			};
		}

		function periodeLibelle(evenement)
		{
			if (!evenement.debut || !evenement.fin) return "Période à compléter";
			return `Du ${libelleDate(evenement.debut)} au ${libelleDate(evenement.fin)}`;
		}


		function joursOuvertureLibelle(evenement)
		{
			const jours = new Set((evenement.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number));
			const libelles = JOURS_EVENEMENT.filter((jour) => jours.has(jour.numero)).map((jour) => jour.court);
			return libelles.length === 7 ? "Tous les jours" : libelles.join(" · ");
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
					<div class="lieu-total-readonly"><span>Effectif global</span><strong>${escapeHtml(c.effectif_cible)}</strong><small>calculé depuis les événements actifs</small></div>
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
			apiFetch(`/api/centres/${lieu.id}/evenements/reordonner/`, {
				method: "POST",
				body: JSON.stringify({ evenement_ids: ids }),
			}).then(() =>
			{
				afficherToast("Ordre des événements enregistré.");
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
			initialiserCalendrierExclusions(row, "edit-team");
			const error = row.querySelector(".edit-team-error");
			row.appendChild(creerFormActions(() =>
			{
				const payload = lireEvenementForm(row, "edit-team");
				if (!payload.nom || !payload.debut || !payload.fin)
				{
					error.textContent = "Le nom et la période sont obligatoires.";
					return;
				}
				if (payload.jours_ouverts.length === 0)
				{
					error.textContent = "Choisis au moins un jour habituel d’ouverture.";
					return;
				}
				enregistrerEvenement(`/api/evenements/${evenement.id}/`, "PATCH", payload, error, () =>
				{
					afficherToast("Événement modifié.");
					charger();
					if (options.onChange) options.onChange();
				});
			}, charger));
		}

		function chargerEvenements(c, card)
		{
			const teamList = card.querySelector(".team-list");
			return apiFetch(`/api/centres/${c.id}/evenements/`).then((evenements) =>
			{
				teamList.innerHTML = "";
				evenements.forEach((evenement, index) =>
				{
					const row = document.createElement("div");
					row.className = `team-row${evenement.active ? "" : " team-row-inactive"}`;
					row.dataset.evenementId = evenement.id;
					row.innerHTML = `
						<div class="team-main">
							<div class="team-title-line">
								<strong>${escapeHtml(evenement.nom)}</strong>
								<span class="team-status ${evenement.active ? "is-active" : "is-inactive"}">${evenement.active ? "Active" : "Inactive"}</span>
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
						if (!confirm(`Supprimer l’événement « ${evenement.nom} » ?`)) return;
						apiFetch(`/api/evenements/${evenement.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Événement supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					});
					supprimer.disabled = !evenement.peut_supprimer;
					if (!evenement.peut_supprimer)
					{
						supprimer.title = evenement.nb_affectations
							? "Cet événement contient des affectations."
							: "Un lieu doit conserver au moins un événement.";
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
						<div><h4>Événements de ce lieu</h4><p>Chaque événement garde sa période, son effectif et ses qualifications propres.</p></div>
						<button type="button" class="btn btn-secondary team-add-toggle">+ Ajouter un événement</button>
					</div>
					<div class="team-list"><p class="empty-note">Chargement…</p></div>
					<div class="team-create-form" hidden>
						${evenementFormHtml("new-team")}
						<div class="edit-actions">
							<button type="button" class="btn btn-primary team-create-submit">Ajouter l’événement</button>
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
			initialiserCalendrierExclusions(form, "new-team");
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
				if (!payload.nom || !payload.debut || !payload.fin)
				{
					error.textContent = "Le nom et la période sont obligatoires.";
					return;
				}
				if (payload.jours_ouverts.length === 0)
				{
					error.textContent = "Choisis au moins un jour habituel d’ouverture.";
					return;
				}
				apiFetch(`/api/centres/${c.id}/evenements/`, {
					method: "POST",
					body: JSON.stringify(payload),
				}).then(() =>
				{
					afficherToast("Événement ajouté.");
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
					afficherToast("Lieu ajouté. Tu peux maintenant y créer un événement.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d’ajouter ce lieu."); });
		});

		apiFetch("/api/qualifications/").then((items) => { qualificationsEvenements = items; return charger(); });
		return { charger };
	}

	// ------------------------------------------------------------------
	return { mountCentres, mountQualifications };
})();
