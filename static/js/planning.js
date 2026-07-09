// ===========================================================================
// planning.js
// ---------------------------------------------------------------------------
// Logique de la page /planning/ : un calendrier FullCalendar par centre,
// la liste des animateurs (glisser-déposer OU clic-puis-clic pour les
// affecter), la barre d'outils (navigation, vue, vider la semaine) et la
// popup d'édition rapide (qui réutilise gestion.js).
//
// Toutes les fonctions utilitaires génériques (apiFetch, addDays, modal,
// toast...) viennent de ui.js, chargé juste avant ce fichier.
// ===========================================================================

document.addEventListener("DOMContentLoaded", function ()
{
	// -- Références DOM utilisées à plusieurs endroits --
	const calendarsContainer = document.getElementById("calendars-container");
	const animList = document.getElementById("animateurs-list");
	const toolbarLabel = document.getElementById("toolbar-label");

	// Un FullCalendar.Calendar par centre, dans le même ordre que les
	// centres reçus de l'API. On s'en sert pour synchroniser la
	// navigation (prev/next/today/changeView) sur les 3 à la fois.
	const calendars = [];

	// Petits caches front : ils évitent de refaire des appels API quand on
	// modifie un animateur ou qu'on affiche ses informations. Ils sont mis à jour
	// par chargerCentres() et chargerAnimateurs().
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
	let selectedChip = null;
	let selectedDetail = null;

	// Mode "clic sur un jour sans animateur sélectionné".
	// Quand il est actif, les animateurs disponibles pour ce jour sont
	// mis en évidence. Un clic sur l'un d'eux crée directement
	// l'affectation sur le jour et le centre sélectionnés.
	let jourSelectionnePourPlacement = null;
	let celluleJourSelectionnee = null;


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

	function centresAutorisesInputs(centresAutorises = [])
	{
		if (centresPlanning.length === 0)
		{
			return '<p class="empty-note">Ajoute d\'abord des centres pour choisir où affecter l\'animateur.</p>';
		}

		const centresSet = new Set((centresAutorises || []).map((centre) => Number(centre.id ?? centre)));

		return centresPlanning.map((centre) => `
			<label class="checkbox-chip centre-chip-option">
				<input type="checkbox" value="${escapeHtml(centre.id)}" ${centresSet.has(Number(centre.id)) ? "checked" : ""}>
				<span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>
				${escapeHtml(centre.code || centre.nom)}
			</label>
		`).join("");
	}

	function centresAutorisesDepuisForm(root)
	{
		return idsCheckboxesCochees(root);
	}

	function disponibilitesTexte(disponibilites)
	{
		if (!disponibilites || disponibilites.length === 0)
		{
			return "Aucune disponibilité renseignée";
		}

		return disponibilites.map((plage) => `${libelleDate(plage.debut)} → ${libelleDate(plage.fin)}`).join(" · ");
	}

	function centresAutorisesTexte(animateur)
	{
		if (!animateur.centres_autorises || animateur.centres_autorises.length === 0)
		{
			return "Aucun centre autorisé";
		}

		return animateur.centres_autorises.map((centre) => centre.nom).join(" · ");
	}

	function retirerFicheAnimateurSelectionne()
	{
		if (selectedDetail)
		{
			selectedDetail.classList.remove("open");
			const detailARetirer = selectedDetail;
			selectedDetail = null;

			window.setTimeout(() => detailARetirer.remove(), 180);
		}
	}

	function rendreFicheAnimateurSelectionne(disponibilites = null)
	{
		if (!animateurActif || !selectedChip)
		{
			retirerFicheAnimateurSelectionne();
			return;
		}

		const animateur = animateurActif;
		const plages = disponibilites || animateur.disponibilites || [];
		const age = animateur.age !== null && animateur.age !== undefined ? `${animateur.age} ans` : "Âge non renseigné";
		const qualifications = animateur.qualifications && animateur.qualifications.length ? animateur.qualifications.join(", ") : "Aucune qualification";

		if (!selectedDetail)
		{
			selectedDetail = document.createElement("div");
			selectedDetail.classList.add("animateur-detail");
		}

		selectedDetail.innerHTML = `
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
				<p><strong>Centres possibles</strong><span>${escapeHtml(centresAutorisesTexte(animateur))}</span></p>
				<p><strong>Disponibilités</strong><span>${escapeHtml(disponibilitesTexte(plages))}</span></p>
			</div>
			<div class="selected-actions">
				<button class="btn btn-primary" id="btn-edit-selected" type="button">Modifier</button>
				<button class="btn btn-accent" id="btn-dispo-selected" type="button">Ajouter une dispo</button>
			</div>
			<p class="selected-help">Clique sur un jour d'un calendrier pour affecter ${escapeHtml(animateur.prenom)}.</p>
		`;

		selectedChip.insertAdjacentElement("afterend", selectedDetail);

		// requestAnimationFrame laisse le navigateur insérer l'élément avant
		// d'ajouter la classe .open : l'animation CSS peut ainsi se déclencher.
		requestAnimationFrame(() => selectedDetail.classList.add("open"));

		selectedDetail.querySelector("#btn-edit-selected").addEventListener("click", ouvrirModalEditionAnimateur);
		selectedDetail.querySelector("#btn-dispo-selected").addEventListener("click", ouvrirModalDispoAnimateur);
	}


	function dateDansPlage(dateStr, debutStr, finStr)
	{
		return debutStr <= dateStr && dateStr <= finStr;
	}

	function animateurDisponibleCeJour(animateur, dateStr)
	{
		// Même règle que le backend : aucune disponibilité renseignée = pas de contrainte.
		if (!animateur.disponibilites || animateur.disponibilites.length === 0)
		{
			return true;
		}

		return animateur.disponibilites.some((plage) => dateDansPlage(dateStr, plage.debut, plage.fin));
	}

	function animateurAffectableSurCentre(animateur, centre)
	{
		return (animateur.centres_autorises || []).some((c) => Number(c.id) === Number(centre.id));
	}

	function evenementCouvreJour(event, dateStr)
	{
		const debut = event.start ? formatDateLocal(event.start) : event.startStr;
		const finExclusive = event.end ? formatDateLocal(event.end) : (event.endStr || addDays(debut, 1));

		return debut <= dateStr && dateStr < finExclusive;
	}

	function animateurDejaAffecteCeJour(animateurId, dateStr)
	{
		return calendars.some((calendar) =>
			calendar.getEvents().some((event) =>
			{
				if (event.display === "background") return false;

				const eventAnimateurId = Number(
					event.extendedProps.animateur_id || event.extendedProps.animateurId
				);

				return eventAnimateurId === Number(animateurId) && evenementCouvreJour(event, dateStr);
			})
		);
	}

	function animateurPlacableSurJour(animateur, dateStr, centre = null)
	{
		return animateurDisponibleCeJour(animateur, dateStr)
			&& (!centre || animateurAffectableSurCentre(animateur, centre))
			&& !animateurDejaAffecteCeJour(animateur.id, dateStr);
	}

	function nettoyerModePlacementJour()
	{
		jourSelectionnePourPlacement = null;

		if (celluleJourSelectionnee)
		{
			celluleJourSelectionnee.classList.remove("jour-placement-selected");
			celluleJourSelectionnee = null;
		}

		document.querySelectorAll(".calendar-card.day-pick-active").forEach((card) =>
			card.classList.remove("day-pick-active")
		);

		document.querySelectorAll(".animateur.day-available, .animateur.day-unavailable").forEach((chip) =>
		{
			chip.classList.remove("day-available", "day-unavailable");
			chip.removeAttribute("data-day-hint");
		});
	}

	function surlignerAnimateursDisponibles(dateStr, centre)
	{
		document.querySelectorAll(".animateur").forEach((chip) =>
		{
			const animateur = animateursPlanning.find((a) => Number(a.id) === Number(chip.dataset.animateurId));
			if (!animateur) return;

			const disponible = animateurDisponibleCeJour(animateur, dateStr);
			const affectable = animateurAffectableSurCentre(animateur, centre);
			const dejaPlace = animateurDejaAffecteCeJour(animateur.id, dateStr);
			const placable = disponible && affectable && !dejaPlace;

			chip.classList.toggle("day-available", placable);
			chip.classList.toggle("day-unavailable", !placable);

			if (!disponible)
			{
				chip.dataset.dayHint = "Non disponible ce jour-là";
			}
			else if (!affectable)
			{
				chip.dataset.dayHint = "Non affectable sur ce centre";
			}
			else if (dejaPlace)
			{
				chip.dataset.dayHint = "Déjà affecté ce jour-là";
			}
			else
			{
				chip.dataset.dayHint = "Disponible : clique pour affecter";
			}
		});
	}

	function activerModePlacementJour(info, centre, calendar)
	{
		const memeJour = jourSelectionnePourPlacement
			&& jourSelectionnePourPlacement.date === info.dateStr
			&& Number(jourSelectionnePourPlacement.centre.id) === Number(centre.id);

		nettoyerModePlacementJour();

		if (memeJour)
		{
			afficherToast("Sélection du jour annulée.");
			return;
		}

		jourSelectionnePourPlacement = {
			date: info.dateStr,
			centre: centre,
			calendar: calendar,
		};

		celluleJourSelectionnee = info.dayEl;
		celluleJourSelectionnee.classList.add("jour-placement-selected");
		info.dayEl.closest(".calendar-card")?.classList.add("day-pick-active");

		surlignerAnimateursDisponibles(info.dateStr, centre);
		afficherToast(`Choisis un animateur disponible pour ${centre.nom} le ${libelleDate(info.dateStr)}.`);
	}

	function creerAffectationDepuisJour(animateur, centre, calendar, debut)
	{
		const fin = addDays(debut, 1);

		return apiFetch("/api/affectations/",
		{
			method: "POST",
			body: JSON.stringify({
				animateur_id: animateur.id,
				centre_id: centre.id,
				debut: debut,
				fin: fin,
			}),
		}).then((data) =>
		{
			calendar.addEvent({
				id: data.id,
				title: data.title,
				start: data.start,
				end: data.end,
				allDay: true,
				extendedProps: data.extendedProps || {
					animateur_id: animateur.id,
					centre_id: centre.id,
				},
			});
			afficherToast(`${animateur.prenom} affecté·e à ${centre.nom} le ${libelleDate(debut)}.`);
		});
	}

	function affecterAnimateurSurJourSelectionne(animateur)
	{
		if (!jourSelectionnePourPlacement) return false;

		const { date, centre, calendar } = jourSelectionnePourPlacement;

		if (!animateurPlacableSurJour(animateur, date, centre))
		{
			if (!animateurDisponibleCeJour(animateur, date))
			{
				afficherToast(`${animateur.prenom} n'est pas disponible le ${libelleDate(date)}.`, true);
			}
			else if (!animateurAffectableSurCentre(animateur, centre))
			{
				afficherToast(`${animateur.prenom} n'est pas affectable sur ${centre.nom}.`, true);
			}
			else
			{
				afficherToast(`${animateur.prenom} est déjà affecté·e ce jour-là.`, true);
			}
			return true;
		}

		creerAffectationDepuisJour(animateur, centre, calendar, date)
			.then(() => nettoyerModePlacementJour())
			.catch((err) => afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true));

		return true;
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
			editable: true,   // autorise glisser/redimensionner un évènement existant
			droppable: true,  // autorise à recevoir un élément externe (la liste d'animateurs)
			selectable: true,
			weekends: false,
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

			// Clic sur un jour du calendrier :
			// - si un animateur est déjà sélectionné, on l'affecte directement ;
			// - sinon, on passe en mode "choix d'un animateur pour ce jour" :
			//   les animateurs disponibles sont mis en surbrillance dans la liste.
			dateClick: function (info)
			{
				if (!animateurActif)
				{
					activerModePlacementJour(info, centre, calendar);
					return;
				}

				creerAffectationDepuisJour(animateurActif, centre, info.view.calendar, info.dateStr)
					.catch((err) => afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true));
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
	// utilisé pour déterminer précisément la semaine affichée.

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

				calendars.forEach((calendar) =>
				{
					// refetchEvents() recharge les événements venus de l'API,
					// mais ne supprime pas toujours les événements ajoutés
					// manuellement par drag & drop dans la session courante.
					// On retire donc explicitement toutes les affectations
					// visibles de la semaine avant de relire la base.
					calendar.getEvents().forEach((event) =>
					{
						if (event.display !== "background")
						{
							event.remove();
						}
					});

					calendar.refetchEvents();
				});
			})
			.catch((err) => afficherToast(erreurMessage(err, "La suppression a échoué."), true));
	});

	// -----------------------------------------------------------------
	// Liste des animateurs (badges de type "badge de colo")
	// -----------------------------------------------------------------

	// Construit le petit badge d'un animateur : ruban coloré et pastilles
	// indiquent les centres où il peut être affecté.
	function creerChipAnimateur(animateur)
	{
		const div = document.createElement("div");
		div.classList.add("animateur");
		div.dataset.animateurId = animateur.id;

		const centresAutorises = animateur.centres_autorises || [];
		const rubanCouleur = centresAutorises.length > 0
			? centresAutorises[0].couleur
			: "var(--color-border)";
		div.style.setProperty("--ruban", rubanCouleur);

		const name = document.createElement("span");
		name.classList.add("anim-name");
		name.textContent = `${animateur.prenom} ${animateur.nom[0]}.`;
		div.appendChild(name);

		const infos = [
			animateur.telephone || null,
			animateur.email || null,
		].filter(Boolean).join(" · ");
		if (infos) div.title = infos;

		const centresBadges = document.createElement("span");
		centresBadges.classList.add("anim-prefs");

		centresAutorises.forEach((centre) =>
		{
			const dot = document.createElement("span");
			dot.classList.add("pref-dot");
			dot.dataset.centre = centre.id;
			dot.style.setProperty("--c", centre.couleur);
			dot.title = centre.nom;
			dot.textContent = centre.code || "•";
			centresBadges.appendChild(dot);
		});

		div.appendChild(centresBadges);

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

			selectedChip = null;
			animateurs.forEach((animateur) =>
			{
				const chip = creerChipAnimateur(animateur);
				if (animateurActif && animateurActif.id === animateur.id)
				{
					animateurActif = animateur;
					selectedChip = chip;
					chip.classList.add("selected");
				}
				animList.appendChild(chip);
			});

			if (animateurActif && selectedChip)
			{
				rendreFicheAnimateurSelectionne(animateurActif.disponibilites || []);
			}
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
		// Cas spécial : un jour a été cliqué sans animateur sélectionné.
		// Le clic sur un badge disponible doit alors affecter l'animateur
		// à ce jour, au lieu d'ouvrir sa fiche.
		if (jourSelectionnePourPlacement)
		{
			affecterAnimateurSurJourSelectionne(animateur);
			return;
		}

		const dejaSelectionne = chip.classList.contains("selected");

		document.querySelectorAll(".animateur.selected").forEach((el) => el.classList.remove("selected"));
		effacerDisponibilitesAffichees();
		animateurActif = null;
		selectedChip = null;
		rendreFicheAnimateurSelectionne();

		// Un second clic sur le même animateur = désélectionner et s'arrêter là.
		if (dejaSelectionne) return;

		chip.classList.add("selected");
		animateurActif = animateur;
		selectedChip = chip;
		rendreFicheAnimateurSelectionne(animateur.disponibilites || []);

		apiFetch(`/api/animateurs/${animateur.id}/disponibilites/`)
			.then((data) => afficherDisponibilites(animateur, data.disponibilites));
	}

	// -----------------------------------------------------------------
	// Survol d'un calendrier : met en avant les animateurs affectables
	// sur ce centre et estompe les autres.
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
	const modalAuto = document.getElementById("modal-auto-remplissage");
	const modalAutoContent = document.getElementById("modal-auto-remplissage-content");

	initFermetureModal(modalEditAnimateur);
	initFermetureModal(modalDispoAnimateur);
	initFermetureModal(modalAuto);

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
						<label>Centres possibles</label>
						<div class="checkbox-grid" id="edit-selected-centres">${centresAutorisesInputs(a.centres_autorises || [])}</div>
						<small class="entity-muted">Coche les centres où cet animateur peut être affecté.</small>
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
					centres_autorises: centresAutorisesDepuisForm(modalEditContent.querySelector("#edit-selected-centres")),
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
	// Double barre de défilement horizontale pour les calendriers.
	// Sur mobile, #calendars-container déborde à droite et possède déjà
	// une barre de défilement native EN BAS. Mais comme les calendriers
	// sont empilés (un par centre), ce bas est souvent loin sous la ligne
	// de flottaison. On ajoute donc une seconde barre EN HAUT, synchronisée,
	// pour pouvoir faire défiler les jours sans descendre tout en bas.
	//
	// Technique de la "double scrollbar" : un conteneur vide au-dessus,
	// lui-même défilable horizontalement, dont la piste interne fait
	// exactement la largeur défilable des calendriers. On recopie la
	// position de scroll de l'un vers l'autre.
	// -----------------------------------------------------------------
	function installerBarreScrollHaut(container)
	{
		const barreHaut = document.createElement("div");
		barreHaut.id = "calendars-scroll-top";
		const piste = document.createElement("div");
		barreHaut.appendChild(piste);
		container.parentNode.insertBefore(barreHaut, container);

		// La piste prend la largeur totale défilable du conteneur, pour que
		// la barre du haut ait la même amplitude que celle du bas. La barre
		// n'est montrée que s'il y a effectivement un débordement (donc pas
		// sur desktop, où tout tient dans la largeur).
		function rafraichir()
		{
			piste.style.width = container.scrollWidth + "px";
			const deborde = container.scrollWidth > container.clientWidth + 1;
			barreHaut.classList.toggle("visible", deborde);
		}

		// Recalcul groupé sur une frame pour éviter les rafales (rendu
		// FullCalendar, rotation d'écran, ajout de centre...).
		let planifie = false;
		function planifierRafraichir()
		{
			if (planifie) return;
			planifie = true;
			requestAnimationFrame(() => { planifie = false; rafraichir(); });
		}

		// Synchronisation croisée des positions de scroll, avec verrou
		// anti-boucle (déplacer l'un déclenche le scroll de l'autre).
		let enCours = false;
		function relier(source, cible)
		{
			source.addEventListener("scroll", () =>
			{
				if (enCours) return;
				enCours = true;
				cible.scrollLeft = source.scrollLeft;
				requestAnimationFrame(() => { enCours = false; });
			});
		}
		relier(barreHaut, container);
		relier(container, barreHaut);

		// La largeur défilable change avec la taille de l'écran ET avec le
		// contenu (rendu des calendriers, changement de vue, ajout/retrait
		// de centre). On surveille les deux.
		window.addEventListener("resize", planifierRafraichir);
		new ResizeObserver(planifierRafraichir).observe(container);
		new MutationObserver(planifierRafraichir).observe(container, { childList: true, subtree: true });

		planifierRafraichir();
	}

	installerBarreScrollHaut(calendarsContainer);

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
	// Placement automatique de la semaine affichée (lundi -> vendredi).
	// On ouvre d'abord une popup pour choisir le nombre d'animateurs par
	// jour et par centre, puis le serveur vide la semaine et reconstruit
	// les affectations en respectant disponibilités et centres autorisés.
	const btnAutoSemaine = document.getElementById("btn-auto-semaine");

	// Lance réellement le remplissage une fois les effectifs choisis.
	function lancerRemplissageAuto(effectifs, boutonValider)
	{
		const lundi = lundiDeLaSemaine(calendars[0].getDate());
		const debut = formatDateLocal(lundi);

		btnAutoSemaine.disabled = true;
		btnAutoSemaine.textContent = "Remplissage...";
		if (boutonValider)
		{
			boutonValider.disabled = true;
			boutonValider.textContent = "Remplissage...";
		}

		apiFetch("/api/planning/auto/",
		{
			method: "POST",
			body: JSON.stringify({ debut, effectifs }),
		})
		.then((data) =>
		{
			calendars.forEach((calendar) =>
			{
				calendar.getEvents().forEach((event) =>
				{
					if (event.display !== "background")
					{
						event.remove();
					}
				});
				calendar.refetchEvents();
			});
			fermerModal(modalAuto);
			afficherToast(data.message || "Planning rempli automatiquement.", Boolean(data.unfilled));
		})
		.catch((err) =>
		{
			afficherToast(erreurMessage(err, "Le placement automatique a échoué."), true);
		})
		.finally(() =>
		{
			btnAutoSemaine.disabled = false;
			btnAutoSemaine.textContent = "Remplir auto";
			if (boutonValider)
			{
				boutonValider.disabled = false;
				boutonValider.textContent = "Remplir la semaine";
			}
		});
	}

	// Construit et ouvre la popup listant chaque centre avec un champ
	// "nombre d'animateurs par jour" (pré-rempli avec son effectif cible).
	function ouvrirPopupRemplissageAuto()
	{
		if (centresPlanning.length === 0)
		{
			afficherToast("Ajoute d'abord au moins un centre.", true);
			return;
		}

		const lignes = centresPlanning.map((centre) =>
		{
			const defaut = Number(centre.effectif_cible) || 1;
			return `
				<div class="auto-centre-ligne">
					<span class="auto-centre-nom">
						<span class="centre-pastille" style="background:${centre.couleur}"></span>
						${centre.nom}
					</span>
					<input type="number" min="0" max="20" step="1"
						   class="auto-centre-effectif"
						   data-centre-id="${centre.id}"
						   value="${defaut}">
				</div>`;
		}).join("");

		modalAutoContent.innerHTML = `
			<p class="form-hint">Choisis le nombre d'animateurs à placer <strong>par jour</strong> dans chaque centre, du lundi au vendredi. Les disponibilités de chacun sont respectées. Mettre 0 exclut un centre.</p>
			<div class="auto-centres-liste">${lignes}</div>
			<p class="form-error" id="auto-error"></p>
			<div class="edit-actions">
				<button class="btn btn-primary" id="auto-valider" type="button">Remplir la semaine</button>
				<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
			</div>
		`;

		modalAutoContent.querySelector("#auto-valider").addEventListener("click", () =>
		{
			const erreur = modalAutoContent.querySelector("#auto-error");
			erreur.textContent = "";

			const effectifs = {};
			let total = 0;

			modalAutoContent.querySelectorAll(".auto-centre-effectif").forEach((input) =>
			{
				const valeur = Math.max(0, parseInt(input.value, 10) || 0);
				effectifs[input.dataset.centreId] = valeur;
				total += valeur;
			});

			if (total === 0)
			{
				erreur.textContent = "Mets au moins un animateur dans un centre.";
				return;
			}

			if (!confirm("Remplir automatiquement du lundi au vendredi ? Les affectations existantes de ces jours seront remplacées."))
			{
				return;
			}

			lancerRemplissageAuto(effectifs, modalAutoContent.querySelector("#auto-valider"));
		});

		ouvrirModal(modalAuto);
	}

	if (btnAutoSemaine)
	{
		btnAutoSemaine.addEventListener("click", () =>
		{
			if (calendars.length === 0)
			{
				afficherToast("Aucun calendrier n'est chargé.", true);
				return;
			}
			ouvrirPopupRemplissageAuto();
		});
	}
});