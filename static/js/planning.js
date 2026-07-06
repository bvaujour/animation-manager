// ===========================================================================
// planning.js
// ---------------------------------------------------------------------------
// Logique de la page /planning/ : un calendrier FullCalendar par centre,
// la liste des animateurs (glisser-déposer OU clic-puis-clic pour les
// affecter), la barre d'outils (navigation, vue, vider/placer auto) et la
// popup d'ajout rapide (qui réutilise gestion.js).
//
// Toutes les fonctions utilitaires génériques (apiFetch, addDays, modal,
// toast...) viennent de ui.js, chargé juste avant ce fichier.
// ===========================================================================

document.addEventListener("DOMContentLoaded", function ()
{
	// -- Références DOM utilisées à plusieurs endroits --
	const calendarsContainer = document.getElementById("calendars-container");
	const animList = document.getElementById("animateurs-list");
	const selectedCard = document.getElementById("selected-animateur-card");
	const toolbarLabel = document.getElementById("toolbar-label");

	// Un FullCalendar.Calendar par centre, dans le même ordre que les
	// centres reçus de l'API. On s'en sert pour synchroniser la
	// navigation (prev/next/today/changeView) sur les 3 à la fois.
	const calendars = [];

	// Petits caches front : ils évitent de refaire des appels API quand on
	// ouvre la modal de placement automatique. Ils sont mis à jour par
	// chargerCentres() et chargerAnimateurs().
	let centresPlanning = [];
	let animateursPlanning = [];
	let qualificationsPlanning = [];

	// Identifiant de la "source d'évènements" utilisée pour afficher les
	// disponibilités en fond de calendrier (voir afficherDisponibilites).
	const DISPO_SOURCE_ID = "disponibilites";

	// Animateur actuellement sélectionné dans la liste, s'il y en a un.
	// Sert à deux choses en même temps :
	//   - afficher ses disponibilités en surbrillance sur les calendriers ;
	//   - permettre de l'affecter en cliquant sur un jour (alternative au
	//     glisser-déposer, plus fiable au doigt sur téléphone).
	let animateurActif = null;


	function escapeHtml(value)
	{
		return String(value ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll("\"", "&quot;")
			.replaceAll("'", "&#039;");
	}

	function libelleDate(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
	}

	function idsCheckboxesCochees(root)
	{
		return Array.from(root.querySelectorAll("input:checked")).map((input) => parseInt(input.value, 10));
	}

	function qualificationCheckboxes(cochees = [])
	{
		if (qualificationsPlanning.length === 0)
		{
			return '<p class="empty-note">Aucune qualification disponible.</p>';
		}

		const cocheesSet = new Set((cochees || []).map(Number));
		return qualificationsPlanning.map((qualification) => `
			<label class="checkbox-chip">
				<input type="checkbox" value="${escapeHtml(qualification.id)}" ${cocheesSet.has(qualification.id) ? "checked" : ""}>
				${escapeHtml(qualification.nom)}
			</label>
		`).join("");
	}

	function preferencesInputs(preferences = [])
	{
		if (centresPlanning.length === 0)
		{
			return '<p class="empty-note">Ajoute d\'abord des centres pour pouvoir définir des préférences.</p>';
		}

		const ordreParCentre = new Map((preferences || []).map((pref) => [Number(pref.id), pref.ordre]));

		return centresPlanning.map((centre) => `
			<label class="preference-row">
				<span><span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>${escapeHtml(centre.nom)}</span>
				<select data-centre-id="${escapeHtml(centre.id)}">
					<option value="">Pas de préférence</option>
					${centresPlanning.map((_, index) => {
						const ordre = index + 1;
						return `<option value="${ordre}" ${ordreParCentre.get(Number(centre.id)) === ordre ? "selected" : ""}>${ordre}</option>`;
					}).join("")}
				</select>
			</label>
		`).join("");
	}

	function preferencesDepuisForm(root)
	{
		return Array.from(root.querySelectorAll("select[data-centre-id]"))
			.filter((select) => select.value !== "")
			.map((select) => ({
				centre_id: parseInt(select.dataset.centreId, 10),
				ordre: parseInt(select.value, 10),
			}));
	}

	function disponibilitesTexte(disponibilites)
	{
		if (!disponibilites || disponibilites.length === 0)
		{
			return "Aucune disponibilité renseignée";
		}

		return disponibilites.map((plage) => `${libelleDate(plage.debut)} → ${libelleDate(plage.fin)}`).join(" · ");
	}

	function preferencesTexte(animateur)
	{
		if (!animateur.centres_preferes || animateur.centres_preferes.length === 0)
		{
			return "Aucun centre préféré";
		}

		return animateur.centres_preferes.map((pref) => `${pref.ordre}. ${pref.nom}`).join(" · ");
	}

	function rendreFicheAnimateurSelectionne(disponibilites = null)
	{
		if (!animateurActif)
		{
			selectedCard.classList.add("empty");
			selectedCard.innerHTML = `
				<p class="selected-title">Aucun animateur sélectionné</p>
				<p class="selected-help">Clique sur un animateur pour voir ses infos, modifier sa fiche ou ajouter une disponibilité.</p>
			`;
			return;
		}

		const animateur = animateurActif;
		const plages = disponibilites || animateur.disponibilites || [];
		const age = animateur.age !== null && animateur.age !== undefined ? `${animateur.age} ans` : "Âge non renseigné";
		const qualifications = animateur.qualifications && animateur.qualifications.length ? animateur.qualifications.join(", ") : "Aucune qualification";

		selectedCard.classList.remove("empty");
		selectedCard.innerHTML = `
			<div class="selected-header">
				<div>
					<p class="selected-kicker">Animateur sélectionné</p>
					<h2>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</h2>
				</div>
				<span class="selected-age">${escapeHtml(age)}</span>
			</div>
			<div class="selected-details">
				<p><strong>Tél.</strong><span>${escapeHtml(animateur.telephone || "Non renseigné")}</span></p>
				<p><strong>Email</strong><span>${escapeHtml(animateur.email || "Non renseigné")}</span></p>
				<p><strong>Qualifications</strong><span>${escapeHtml(qualifications)}</span></p>
				<p><strong>Préférences</strong><span>${escapeHtml(preferencesTexte(animateur))}</span></p>
				<p><strong>Disponibilités</strong><span>${escapeHtml(disponibilitesTexte(plages))}</span></p>
			</div>
			<div class="selected-actions">
				<button class="btn btn-primary" id="btn-edit-selected" type="button">Modifier la fiche</button>
				<button class="btn btn-accent" id="btn-dispo-selected" type="button">Ajouter une dispo</button>
			</div>
			<p class="selected-help">Clique sur un jour d'un calendrier pour affecter ${escapeHtml(animateur.prenom)}.</p>
		`;

		selectedCard.querySelector("#btn-edit-selected").addEventListener("click", ouvrirModalEditionAnimateur);
		selectedCard.querySelector("#btn-dispo-selected").addEventListener("click", ouvrirModalDispoAnimateur);
	}

	// -----------------------------------------------------------------
	// Calendriers (un par centre)
	// -----------------------------------------------------------------

	// Appelée quand on déplace ou redimensionne un évènement existant
	// (glisser-déposer classique). On enregistre le nouveau créneau côté
	// serveur, et si le serveur refuse (conflit, indisponibilité...) on
	// annule visuellement le déplacement avec info.revert().
	function updateAffectation(info)
	{
		const event = info.event;

		apiFetch(`/api/affectations/${event.id}/`,
		{
			method: "PATCH",
			body: JSON.stringify({
				debut: event.startStr,
				fin: event.endStr || addDays(event.startStr, 1),
			}),
		}).catch((err) =>
		{
			afficherToast(erreurMessage(err, "La mise à jour n'a pas pu être enregistrée."), true);
			info.revert();
		});
	}

	// Crée l'instance FullCalendar pour un centre donné et la monte dans
	// la carte fournie. `centre` reste accessible dans toutes les
	// fonctions de callback ci-dessous grâce à la fermeture (closure).
	function creerCalendar(centre, card)
	{
		const calendarEl = card.querySelector(".calendar");

		const calendar = new FullCalendar.Calendar(calendarEl,
		{
			initialView: "dayGridWeek",
			height: "100%",
			locale: "fr",
			firstDay: 1, // la semaine commence le lundi
			overflow: false,
			editable: true,   // autorise glisser/redimensionner un évènement existant
			droppable: true,  // autorise à recevoir un élément externe (la liste d'animateurs)
			selectable: true,

			expandRows: true,
			headerToolbar: false, // on utilise notre propre barre d'outils commune
			footerToolbar: false,

			// Chaque calendrier ne charge que les évènements de SON centre.
			events: `/api/planning/?centre_id=${centre.id}`,

			// Se déclenche à chaque changement de dates affichées (navigation,
			// changement de vue...). Comme les 3 calendriers sont toujours
			// synchronisés, n'importe lequel peut mettre à jour le libellé
			// commun de la barre d'outils.
			datesSet: function (info)
			{
				toolbarLabel.textContent = info.view.title;
			},

			// Clic sur un jour du calendrier : si un animateur est
			// sélectionné dans la liste, on l'affecte à ce jour. Sinon,
			// on ne fait rien (c'est juste un clic normal sur le calendrier).
			dateClick: function (info)
			{
				if (!animateurActif) return;

				const debut = info.dateStr;
				const fin = addDays(debut, 1);

				apiFetch("/api/affectations/",
				{
					method: "POST",
					body: JSON.stringify({
						animateur_id: animateurActif.id,
						centre_id: centre.id,
						debut: debut,
						fin: fin,
					}),
				}).then((data) =>
				{
					// On ajoute l'évènement directement au calendrier plutôt
					// que de tout recharger : plus rapide et évite un
					// aller-retour réseau supplémentaire.
					info.view.calendar.addEvent({
						id: data.id,
						title: data.title,
						start: data.start,
						end: data.end,
						allDay: true,
					});
					afficherToast(`${animateurActif.prenom} affecté·e le ${parseLocalDate(debut).toLocaleDateString("fr-FR")}.`);
				}).catch((err) =>
				{
					afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true);
				});
			},

			// Un élément de la liste d'animateurs (voir plus bas, la
			// FullCalendar.Draggable) est déposé sur ce calendrier.
			eventReceive: function (info)
			{
				const animateurId = info.event.extendedProps.animateurId;
				const debut = info.event.startStr;
				const fin = info.event.endStr || addDays(debut, 1);

				apiFetch("/api/affectations/",
				{
					method: "POST",
					body: JSON.stringify({
						animateur_id: animateurId,
						centre_id: centre.id,
						debut: debut,
						fin: fin,
					}),
				}).then((data) =>
				{
					// FullCalendar a déjà affiché l'évènement de façon
					// optimiste ; on lui donne juste le vrai id renvoyé
					// par le serveur pour pouvoir le retrouver plus tard
					// (PATCH/DELETE).
					info.event.setProp("id", data.id);
				}).catch((err) =>
				{
					afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true);
					info.event.remove();
				});
			},

			eventDrop: function (info) { updateAffectation(info); },
			eventResize: function (info) { updateAffectation(info); },

			// Clic sur un évènement existant : proposer de le supprimer.
			// On ignore les évènements "background" (les plages de
			// disponibilité affichées en surbrillance, qui ne sont pas
			// de vraies affectations).
			eventClick: function (info)
			{
				if (info.event.display === "background") return;

				if (confirm(`Supprimer l'affectation de ${info.event.title} ?`))
				{
					apiFetch(`/api/affectations/${info.event.id}/`, { method: "DELETE" })
						.then(() => info.event.remove())
						.catch((err) => afficherToast(erreurMessage(err, "La suppression a échoué."), true));
				}
			},
		});

		calendar.render();
		return calendar;
	}

	// Ajoute la carte HTML + l'instance FullCalendar d'un nouveau centre
	// (appelé au chargement initial pour chaque centre, et aussi juste
	// après avoir créé un centre depuis la popup d'ajout rapide).
	function ajouterCentreAuPlanning(centre)
	{
		const card = document.createElement("div");
		card.classList.add("calendar-card");
		card.dataset.centreId = centre.id;
		card.style.setProperty("--centre-color", centre.couleur);

		card.innerHTML = `<h3>${centre.nom}</h3><div class="calendar"></div>`;
		calendarsContainer.appendChild(card);

		attacherSurvolCentre(card, centre.id);

		const calendar = creerCalendar(centre, card);
		calendars.push(calendar);
	}

	// Charge la liste des centres et construit un calendrier pour chacun.
	function chargerCentres()
	{
		return apiFetch("/api/centres/").then((centres) =>
		{
			centresPlanning = centres;
			calendarsContainer.innerHTML = "";

			if (centres.length === 0)
			{
				calendarsContainer.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant. Utilise le bouton "+" pour en ajouter un.</p>';
				return;
			}

			centres.forEach((centre) => ajouterCentreAuPlanning(centre));
		});
	}

	// -----------------------------------------------------------------
	// Barre d'outils commune : navigation, vue, actions groupées.
	// Les 3 calendriers sont toujours pilotés EN MÊME TEMPS, en itérant
	// simplement sur le tableau `calendars`.
	// -----------------------------------------------------------------

	document.getElementById("btn-prev").addEventListener("click", () => calendars.forEach((c) => c.prev()));
	document.getElementById("btn-next").addEventListener("click", () => calendars.forEach((c) => c.next()));
	document.getElementById("btn-today").addEventListener("click", () => calendars.forEach((c) => c.today()));

	document.querySelectorAll(".view-btn").forEach((btn) =>
	{
		btn.addEventListener("click", () =>
		{
			document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("active"));
			btn.classList.add("active");
			calendars.forEach((c) => c.changeView(btn.dataset.view));
		});
	});

	// Renvoie le lundi de la semaine contenant `date` (à minuit local).
	// getDay() renvoie 0 pour dimanche, 1 pour lundi, ..., 6 pour samedi ;
	// le petit calcul ci-dessous ramène toujours au lundi précédent (ou
	// au jour même si on est déjà lundi).
	function lundiDeLaSemaine(date)
	{
		const d = new Date(date);
		const jour = d.getDay();
		const diff = (jour === 0 ? -6 : 1 - jour);
		d.setDate(d.getDate() + diff);
		d.setHours(0, 0, 0, 0);
		return d;
	}

	// NB : le formatage en "YYYY-MM-DD" utilise formatDateLocal() (définie
	// dans ui.js), PAS toISOString(). Ce fichier manipule des dates en
	// heure locale (calendars[0].getDate(), new Date() "maintenant"...) ;
	// toISOString() les aurait reconverties en UTC et décalées d'un jour
	// pour les fuseaux horaires en avance sur UTC (la France l'été,
	// UTC+2) — c'est exactement ce qui empêchait le vendredi d'être
	// rempli par le placement automatique.

	// -----------------------------------------------------------------
	// Bouton "Vider la semaine" : supprime les affectations (3 centres
	// confondus) de la semaine affichée, À PARTIR D'AUJOURD'HUI
	// uniquement. Le serveur applique aussi cette règle de son côté par
	// sécurité (voir api_planning_plage) : même en cas de bug côté
	// front, l'historique déjà passé n'est jamais supprimé par ce bouton.
	// -----------------------------------------------------------------

	document.getElementById("btn-vider-semaine").addEventListener("click", () =>
	{
		if (calendars.length === 0) return;

		// On se base sur la date "de référence" du premier calendrier :
		// comme les 3 sont toujours synchronisés, peu importe lequel.
		const lundi = lundiDeLaSemaine(calendars[0].getDate());
		const dimancheSuivant = new Date(lundi);
		dimancheSuivant.setDate(dimancheSuivant.getDate() + 7);

		const confirmation = confirm(
			"Supprimer les affectations À VENIR de cette semaine (à partir d'aujourd'hui), dans les 3 centres ? Les jours déjà passés ne sont jamais touchés. Cette action est irréversible."
		);
		if (!confirmation) return;

		apiFetch(`/api/planning/plage/?debut=${formatDateLocal(lundi)}&fin=${formatDateLocal(dimancheSuivant)}`, { method: "DELETE" })
			.then((data) =>
			{
				afficherToast(`${data.supprimees} affectation(s) supprimée(s).`);
				calendars.forEach((c) => c.refetchEvents());
			})
			.catch((err) => afficherToast(erreurMessage(err, "La suppression a échoué."), true));
	});

	// -----------------------------------------------------------------
	// Bouton "Placer automatiquement" :
	// 1. ouvre une modal plus complète ;
	// 2. permet de choisir l'effectif voulu par centre ;
	// 3. permet de cocher/décocher les animateurs autorisés jour par jour ;
	// 4. envoie tout au serveur, qui cherche la meilleure combinaison.
	//
	// Important : la modal ne sauvegarde rien tant qu'on ne clique pas sur
	// "Lancer le placement". Elle prépare seulement les contraintes.
	// -----------------------------------------------------------------

	const modalAuto = document.getElementById("modal-auto");
	initFermetureModal(modalAuto);

	function joursSemaineAffichee()
	{
		const lundi = lundiDeLaSemaine(calendars[0].getDate());
		return [0, 1, 2, 3, 4].map((offset) =>
		{
			const date = new Date(lundi);
			date.setDate(date.getDate() + offset);
			return formatDateLocal(date);
		});
	}

	function libelleJour(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR", {
			weekday: "long",
			day: "2-digit",
			month: "2-digit",
		});
	}

	function nomAnimateurCourt(animateur)
	{
		return `${animateur.prenom} ${animateur.nom[0]}.`;
	}

	function animateurDisponibleLeJour(animateur, dateStr)
	{
		// Même règle que côté serveur : aucune plage renseignée = pas de
		// contrainte connue, donc l'animateur est proposé par défaut.
		if (!animateur.disponibilites || animateur.disponibilites.length === 0)
		{
			return true;
		}

		return animateur.disponibilites.some((plage) => plage.debut <= dateStr && dateStr <= plage.fin);
	}

	function construireModalAuto()
	{
		const zone = document.getElementById("modal-auto-centres");

		if (centresPlanning.length === 0)
		{
			zone.innerHTML = '<p class="empty-note">Ajoute d\'abord au moins un centre.</p>';
			return;
		}

		if (animateursPlanning.length === 0)
		{
			zone.innerHTML = '<p class="empty-note">Ajoute d\'abord au moins un animateur.</p>';
			return;
		}

		const jours = joursSemaineAffichee();
		const totalPlacesParJour = centresPlanning.reduce((total, centre) => total + (parseInt(centre.effectif_cible, 10) || 0), 0);

		zone.innerHTML = `
			<div class="auto-summary">
				<div>
					<strong>Semaine affichée</strong>
					<span>${libelleJour(jours[0])} → ${libelleJour(jours[4])}</span>
				</div>
				<div>
					<strong>${animateursPlanning.length}</strong>
					<span>animateur(s)</span>
				</div>
				<div>
					<strong>${totalPlacesParJour}</strong>
					<span>place(s) / jour</span>
				</div>
			</div>

			<h3 class="auto-section-title">Besoin par centre</h3>
			<div class="auto-centres-grid">
				${centresPlanning.map((centre) => `
					<label class="auto-centre-row" data-centre-id="${centre.id}">
						<span class="auto-centre-name"><span class="swatch" style="background:${centre.couleur}"></span>${centre.nom}</span>
						<input type="number" class="auto-effectif-input" value="${centre.effectif_cible}" min="0" step="1" aria-label="Effectif souhaité pour ${centre.nom}">
					</label>
				`).join("")}
			</div>

			<h3 class="auto-section-title">Animateurs autorisés par jour</h3>
			<p class="empty-note auto-help">Décoche un animateur si tu ne veux pas que l'automatique l'utilise ce jour-là. Les personnes non disponibles sont grisées.</p>
			<div class="auto-days-grid">
				${jours.map((dateStr) => `
					<section class="auto-day-card" data-date="${dateStr}">
						<div class="auto-day-header">
							<strong>${libelleJour(dateStr)}</strong>
							<div class="auto-day-actions">
								<button type="button" class="mini-link auto-day-check-all">Tout</button>
								<button type="button" class="mini-link auto-day-check-available">Dispos</button>
							</div>
						</div>
						<div class="auto-animateurs-grid">
							${animateursPlanning.map((animateur) =>
							{
								const disponible = animateurDisponibleLeJour(animateur, dateStr);
								const classes = disponible ? "" : " auto-unavailable";
								const checked = disponible ? "checked" : "";
								const disabled = disponible ? "" : "disabled";
								const title = disponible ? "" : " title=\"Pas disponible selon les plages renseignées\"";
								return `
									<label class="auto-anim-chip${classes}"${title}>
										<input type="checkbox" value="${animateur.id}" ${checked} ${disabled}>
										<span>${nomAnimateurCourt(animateur)}</span>
									</label>
								`;
							}).join("")}
						</div>
					</section>
				`).join("")}
			</div>
		`;
	}

	document.getElementById("btn-auto-placement").addEventListener("click", () =>
	{
		if (calendars.length === 0) return;

		// On recharge animateurs + centres avant d'ouvrir la modal pour être
		// sûr d'avoir les derniers ajouts/modifications.
		Promise.all([
			apiFetch("/api/centres/").then((centres) => { centresPlanning = centres; }),
			apiFetch("/api/animateurs/").then((animateurs) => { animateursPlanning = animateurs; }),
		]).then(() =>
		{
			construireModalAuto();
			ouvrirModal(modalAuto);
		}).catch((err) => afficherToast(erreurMessage(err, "Impossible de préparer le placement automatique."), true));
	});

	// Petits boutons internes de la modal : "Tout" coche tous les
	// disponibles du jour ; "Dispos" revient au choix conseillé par défaut.
	document.getElementById("modal-auto-centres").addEventListener("click", (event) =>
	{
		const card = event.target.closest(".auto-day-card");
		if (!card) return;

		if (event.target.classList.contains("auto-day-check-all") || event.target.classList.contains("auto-day-check-available"))
		{
			card.querySelectorAll('.auto-anim-chip input[type="checkbox"]').forEach((input) =>
			{
				if (!input.disabled) input.checked = true;
			});
		}
	});

	document.getElementById("btn-auto-confirmer").addEventListener("click", () =>
	{
		if (calendars.length === 0) return;

		const effectifs = {};
		document.querySelectorAll("#modal-auto-centres .auto-centre-row").forEach((row) =>
		{
			effectifs[row.dataset.centreId] = parseInt(row.querySelector(".auto-effectif-input").value, 10) || 0;
		});

		const animateursParJour = {};
		document.querySelectorAll("#modal-auto-centres .auto-day-card").forEach((card) =>
		{
			animateursParJour[card.dataset.date] = Array.from(card.querySelectorAll('.auto-anim-chip input[type="checkbox"]:checked'))
				.map((input) => parseInt(input.value, 10));
		});

		const lundi = lundiDeLaSemaine(calendars[0].getDate());
		const vendredi = new Date(lundi);
		vendredi.setDate(vendredi.getDate() + 4);

		fermerModal(modalAuto);

		apiFetch("/api/planning/auto/",
		{
			method: "POST",
			body: JSON.stringify({
				debut: formatDateLocal(lundi),
				fin: formatDateLocal(vendredi),
				effectifs: effectifs,
				animateurs_par_jour: animateursParJour,
			}),
		}).then((data) =>
		{
			calendars.forEach((c) => c.refetchEvents());

			let message = `${data.creees.length} affectation(s) créée(s) automatiquement.`;
			if (data.supprimees && data.supprimees > 0)
			{
				message = `${data.supprimees} ancienne(s) affectation(s) supprimée(s), puis ${data.creees.length} créée(s) automatiquement.`;
			}
			if (data.non_couverts.length > 0)
			{
				message += ` ${data.non_couverts.length} place(s) restent vides.`;
			}
			if (data.animateurs_non_utilises && data.animateurs_non_utilises.length > 0)
			{
				message += ` ${data.animateurs_non_utilises.length} animateur(s) sélectionné(s) n'ont pas pu être utilisés.`;
			}
			afficherToast(message, data.non_couverts.length > 0);
		}).catch((err) => afficherToast(erreurMessage(err, "Le placement automatique a échoué."), true));
	});

	// -----------------------------------------------------------------
	// Liste des animateurs (badges de type "badge de colo")
	// -----------------------------------------------------------------

	// Construit le petit badge d'un animateur : ruban coloré = son
	// centre préféré n°1, pastilles numérotées = tous ses centres
	// préférés dans l'ordre (voir aussi attacherSurvolCentre).
	function creerChipAnimateur(animateur)
	{
		const div = document.createElement("div");
		div.classList.add("animateur");
		div.dataset.animateurId = animateur.id;

		const rubanCouleur = animateur.centres_preferes.length > 0
			? animateur.centres_preferes[0].couleur
			: "var(--color-border)";
		div.style.setProperty("--ruban", rubanCouleur);

		const name = document.createElement("span");
		name.classList.add("anim-name");
		name.textContent = `${animateur.prenom} ${animateur.nom[0]}.`;
		div.appendChild(name);

		if (animateur.age !== null && animateur.age !== undefined)
		{
			const age = document.createElement("span");
			age.classList.add("anim-age");
			age.textContent = `${animateur.age} ans`;
			div.appendChild(age);
		}

		const infos = [
			animateur.age !== null && animateur.age !== undefined ? `${animateur.age} ans` : null,
			animateur.telephone || null,
			animateur.email || null,
		].filter(Boolean).join(" · ");
		if (infos) div.title = infos;

		const prefs = document.createElement("span");
		prefs.classList.add("anim-prefs");

		animateur.centres_preferes.forEach((pref) =>
		{
			const dot = document.createElement("span");
			dot.classList.add("pref-dot");
			dot.dataset.centre = pref.id;
			dot.style.setProperty("--c", pref.couleur);
			dot.title = `${pref.ordre}. ${pref.nom}`;
			dot.textContent = pref.ordre;
			prefs.appendChild(dot);
		});

		div.appendChild(prefs);

		// Clic = sélectionner/désélectionner cet animateur (voir toggleSelection).
		div.addEventListener("click", () => toggleSelection(div, animateur));

		return div;
	}

	// (Re)charge la liste des animateurs dans la barre latérale. Appelée
	// au chargement initial, et à nouveau après un ajout/suppression
	// depuis la popup d'ajout rapide.
	function chargerAnimateurs()
	{
		return apiFetch("/api/animateurs/").then((animateurs) =>
		{
			animateursPlanning = animateurs;
			animList.innerHTML = "";

			if (animateurs.length === 0)
			{
				animList.innerHTML = '<p class="empty-note">Aucun animateur pour l\'instant.</p>';
				return;
			}

			animateurs.forEach((animateur) =>
			{
				const chip = creerChipAnimateur(animateur);
				if (animateurActif && animateurActif.id === animateur.id)
				{
					animateurActif = animateur;
					chip.classList.add("selected");
					rendreFicheAnimateurSelectionne(animateur.disponibilites || []);
				}
				animList.appendChild(chip);
			});
		});
	}

	// -----------------------------------------------------------------
	// Disponibilités affichées sur les calendriers au clic sur un animateur
	// -----------------------------------------------------------------

	// Retire la surbrillance de disponibilité affichée précédemment
	// (appelé avant d'en afficher une nouvelle, ou quand on désélectionne).
	function effacerDisponibilitesAffichees()
	{
		calendars.forEach((calendar) =>
		{
			const source = calendar.getEventSourceById(DISPO_SOURCE_ID);
			if (source) source.remove();
		});
	}

	// Affiche, en fond de chaque calendrier, les plages de disponibilité
	// de l'animateur sélectionné + un message texte au-dessus de la liste.
	function afficherDisponibilites(animateur, plages)
	{
		animateur.disponibilites = plages;
		if (animateurActif && animateurActif.id === animateur.id)
		{
			animateurActif.disponibilites = plages;
			rendreFicheAnimateurSelectionne(plages);
		}

		// FullCalendar affiche les évènements "display: background" comme
		// une simple teinte de fond, sans les traiter comme de vraies
		// affectations (pas cliquables, pas de titre affiché).
		const events = plages.map((plage) => ({
			start: plage.debut,
			end: addDays(plage.fin, 1),
			display: "background",
			color: "#3ba55c",
		}));

		calendars.forEach((calendar) =>
		{
			calendar.addEventSource({ id: DISPO_SOURCE_ID, events: events });
		});
	}

	// Sélectionne/désélectionne un animateur au clic sur son badge.
	// Un seul animateur peut être sélectionné à la fois.
	function toggleSelection(chip, animateur)
	{
		const dejaSelectionne = chip.classList.contains("selected");

		document.querySelectorAll(".animateur.selected").forEach((el) => el.classList.remove("selected"));
		effacerDisponibilitesAffichees();
		animateurActif = null;
		rendreFicheAnimateurSelectionne();

		// Un second clic sur le même animateur = désélectionner et s'arrêter là.
		if (dejaSelectionne) return;

		chip.classList.add("selected");
		animateurActif = animateur;
		rendreFicheAnimateurSelectionne(animateur.disponibilites || []);

		apiFetch(`/api/animateurs/${animateur.id}/disponibilites/`)
			.then((data) => afficherDisponibilites(animateur, data.disponibilites));
	}

	// -----------------------------------------------------------------
	// Survol d'un calendrier : met en avant, pour chaque animateur, son
	// classement de préférence pour ce centre (et estompe les autres).
	// Aide visuelle pour savoir "qui préfère le plus ce centre" avant de
	// le glisser-déposer ou de le sélectionner.
	// -----------------------------------------------------------------

	function attacherSurvolCentre(card, centreId)
	{
		card.addEventListener("mouseenter", () =>
		{
			document.querySelectorAll(".animateur").forEach((chip) =>
			{
				const dot = chip.querySelector(`.pref-dot[data-centre="${centreId}"]`);

				if (dot)
				{
					dot.classList.add("active");
					chip.classList.remove("dimmed");
				}
				else
				{
					chip.classList.add("dimmed");
				}
			});
		});

		card.addEventListener("mouseleave", () =>
		{
			document.querySelectorAll(".animateur").forEach((chip) =>
			{
				chip.classList.remove("dimmed");
				chip.querySelectorAll(".pref-dot").forEach((dot) => dot.classList.remove("active"));
			});
		});
	}

	// -----------------------------------------------------------------
	// Actions sur l'animateur sélectionné : modifier sa fiche ou ajouter
	// rapidement une disponibilité depuis la page planning.
	// -----------------------------------------------------------------

	const modalEditAnimateur = document.getElementById("modal-edit-animateur");
	const modalDispoAnimateur = document.getElementById("modal-dispo-animateur");
	const modalEditContent = document.getElementById("modal-edit-animateur-content");
	const modalDispoContent = document.getElementById("modal-dispo-animateur-content");

	initFermetureModal(modalEditAnimateur);
	initFermetureModal(modalDispoAnimateur);

	function chargerReferentielsEdition()
	{
		return Promise.all([
			apiFetch("/api/centres/").then((centres) => { centresPlanning = centres; }),
			apiFetch("/api/qualifications/").then((qualifications) => { qualificationsPlanning = qualifications; }),
		]);
	}

	function ouvrirModalEditionAnimateur()
	{
		if (!animateurActif)
		{
			afficherToast("Sélectionne d'abord un animateur.", true);
			return;
		}

		chargerReferentielsEdition().then(() =>
		{
			const a = animateurActif;
			modalEditContent.innerHTML = `
				<div class="gestion-form selected-edit-form">
					<div class="field">
						<label>Prénom</label>
						<input type="text" id="edit-selected-prenom" value="${escapeHtml(a.prenom)}">
					</div>
					<div class="field">
						<label>Nom</label>
						<input type="text" id="edit-selected-nom" value="${escapeHtml(a.nom)}">
					</div>
					<div class="field">
						<label>Téléphone</label>
						<input type="tel" id="edit-selected-telephone" value="${escapeHtml(a.telephone || "")}">
					</div>
					<div class="field">
						<label>Email</label>
						<input type="email" id="edit-selected-email" value="${escapeHtml(a.email || "")}">
					</div>
					<div class="field">
						<label>Date de naissance</label>
						<input type="date" id="edit-selected-date-naissance" value="${a.date_naissance || ""}">
					</div>
					<div class="field field-wide">
						<label>Qualifications</label>
						<div class="checkbox-grid" id="edit-selected-qualifs">${qualificationCheckboxes(a.qualification_ids || [])}</div>
					</div>
					<div class="field field-wide">
						<label>Centres préférés</label>
						<div class="preferences-grid" id="edit-selected-preferences">${preferencesInputs(a.centres_preferes || [])}</div>
						<small class="entity-muted">Choisis 1 pour le centre préféré, 2 pour le second, etc.</small>
					</div>
					<p class="form-error" id="edit-selected-error"></p>
					<div class="edit-actions">
						<button class="btn btn-primary" id="edit-selected-save" type="button">Enregistrer</button>
						<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
					</div>
				</div>
			`;

			modalEditContent.querySelector("#edit-selected-save").addEventListener("click", () =>
			{
				const error = modalEditContent.querySelector("#edit-selected-error");
				error.textContent = "";

				const payload = {
					prenom: modalEditContent.querySelector("#edit-selected-prenom").value.trim(),
					nom: modalEditContent.querySelector("#edit-selected-nom").value.trim(),
					telephone: modalEditContent.querySelector("#edit-selected-telephone").value.trim(),
					email: modalEditContent.querySelector("#edit-selected-email").value.trim(),
					date_naissance: modalEditContent.querySelector("#edit-selected-date-naissance").value || null,
					qualifications: idsCheckboxesCochees(modalEditContent.querySelector("#edit-selected-qualifs")),
					preferences: preferencesDepuisForm(modalEditContent.querySelector("#edit-selected-preferences")),
				};

				if (!payload.prenom || !payload.nom)
				{
					error.textContent = "Le prénom et le nom sont obligatoires.";
					return;
				}

				apiFetch(`/api/animateurs/${a.id}/`, {
					method: "PATCH",
					body: JSON.stringify(payload),
				}).then((animateurModifie) =>
				{
					animateurActif = animateurModifie;
					rendreFicheAnimateurSelectionne(animateurModifie.disponibilites || []);
					chargerAnimateurs();
					calendars.forEach((calendar) => calendar.refetchEvents());
					fermerModal(modalEditAnimateur);
					afficherToast("Animateur modifié.");
				}).catch((err) =>
				{
					error.textContent = erreurMessage(err, "Modification impossible.");
				});
			});

			ouvrirModal(modalEditAnimateur);
		}).catch((err) => afficherToast(erreurMessage(err, "Impossible de préparer le formulaire."), true));
	}

	function ouvrirModalDispoAnimateur()
	{
		if (!animateurActif)
		{
			afficherToast("Sélectionne d'abord un animateur.", true);
			return;
		}

		const aujourdHui = formatDateLocal(new Date());
		modalDispoContent.innerHTML = `
			<div class="gestion-form selected-dispo-form">
				<p class="empty-note">Ajouter une plage de disponibilité pour <strong>${escapeHtml(animateurActif.prenom)} ${escapeHtml(animateurActif.nom)}</strong>.</p>
				<div class="field">
					<label>Début</label>
					<input type="date" id="dispo-selected-debut" value="${aujourdHui}">
				</div>
				<div class="field">
					<label>Fin incluse</label>
					<input type="date" id="dispo-selected-fin" value="${aujourdHui}">
				</div>
				<p class="form-error" id="dispo-selected-error"></p>
				<div class="edit-actions">
					<button class="btn btn-primary" id="dispo-selected-save" type="button">Ajouter la disponibilité</button>
					<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
				</div>
			</div>
		`;

		modalDispoContent.querySelector("#dispo-selected-save").addEventListener("click", () =>
		{
			const debut = modalDispoContent.querySelector("#dispo-selected-debut").value;
			const fin = modalDispoContent.querySelector("#dispo-selected-fin").value;
			const error = modalDispoContent.querySelector("#dispo-selected-error");
			error.textContent = "";

			if (!debut || !fin)
			{
				error.textContent = "Les deux dates sont obligatoires.";
				return;
			}

			apiFetch(`/api/animateurs/${animateurActif.id}/disponibilites/`, {
				method: "POST",
				body: JSON.stringify({ debut, fin }),
			}).then((data) =>
			{
				afficherDisponibilites(animateurActif, data.disponibilites);
				fermerModal(modalDispoAnimateur);
				afficherToast("Disponibilité ajoutée.");
			}).catch((err) =>
			{
				error.textContent = erreurMessage(err, "Impossible d'ajouter cette disponibilité.");
			});
		});

		ouvrirModal(modalDispoAnimateur);
	}

	// -----------------------------------------------------------------
	// Chargement initial
	// -----------------------------------------------------------------

	chargerCentres();
	chargerAnimateurs();

	// Glisser-déposer : un seul objet Draggable enregistré une fois pour
	// toutes sur le conteneur de la liste (et non un par animateur), qui
	// détecte automatiquement les éléments `.animateur` au moment du
	// glisser grâce à `itemSelector` — ça marche donc aussi pour les
	// animateurs ajoutés dynamiquement plus tard (pas besoin de le
	// recréer à chaque chargerAnimateurs()).
	new FullCalendar.Draggable(animList,
	{
		itemSelector: ".animateur",
		eventData: function (eventEl)
		{
			return {
				title: eventEl.querySelector(".anim-name").textContent,
				allDay: true,
				extendedProps: {
					animateurId: eventEl.dataset.animateurId,
				},
			};
		},
	});
})
