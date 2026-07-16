// ===========================================================================
// planning.js
// ---------------------------------------------------------------------------
// Logique de la page /planning/ : un calendrier FullCalendar par centre,
// la liste des animateurs (glisser-déposer OU clic-puis-clic pour les
// affecter), la barre d'outils (navigation, vue, vider la semaine) et la
// popup de remplissage automatique. La fiche et les disponibilités d'un
// animateur se modifient dans Gestion > Salariés, pas ici.
//
// Toutes les fonctions utilitaires génériques (apiFetch, addDays, modal,
// toast...) viennent de ui.js, chargé juste avant ce fichier.
// ===========================================================================

document.addEventListener("DOMContentLoaded", function ()
{
	const {
		dateDansPlage,
		evenementCouvreJour,
		estVraieAffectation,
		idAnimateurDepuisEvent,
		idEventNormalise,
		intervallesSeChevauchent,
		eventIntervalleDates,
		lundiDeLaSemaine,
	} = PlanningUtils;
	// -- Références DOM utilisées à plusieurs endroits --
	const calendarsContainer = document.getElementById("calendars-container");
	const animList = document.getElementById("animateurs-list");
	const filtresAnimateursDetails = document.getElementById("animateurs-filters");
	const filtresQualificationsConteneur = document.getElementById("animateurs-filter-qualifications");
	const filtresCentresConteneur = document.getElementById("animateurs-filter-centres");
	const compteurFiltresAnimateurs = document.getElementById("animateurs-filter-count");
	const boutonEffacerFiltresAnimateurs = document.getElementById("animateurs-filter-reset");
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
	let centresFiltresCharges = false;
	let qualificationsFiltresChargees = false;

	function lireIdsFiltres(cle)
	{
		try
		{
			const valeur = JSON.parse(localStorage.getItem(cle) || "[]");
			return new Set(Array.isArray(valeur) ? valeur.map(Number).filter(Number.isFinite) : []);
		}
		catch (_erreur)
		{
			return new Set();
		}
	}

	let filtresQualificationsAnimateurs = lireIdsFiltres("planning-filtres-qualifications");
	let filtresCentresAnimateurs = lireIdsFiltres("planning-filtres-centres");
	localStorage.removeItem("planning-tri-animateurs");

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

	// Animateur dont on affiche temporairement les disponibilités pendant
	// un glisser-déposer depuis la liste.
	// Différent d'animateurActif : ici, on ne sélectionne pas vraiment
	// l'animateur, on donne juste une aide visuelle pendant le drag.
	let animateurDragPreview = null;

	// Mode "clic sur un jour sans animateur sélectionné".
	// Quand il est actif, les animateurs disponibles pour ce jour sont
	// mis en évidence. Un clic sur l'un d'eux crée directement
	// l'affectation sur le jour et le centre sélectionnés.
	let jourSelectionnePourPlacement = null;
	let celluleJourSelectionnee = null;

	// Tri visuel des blocs du planning. Le déplacement ne modifie aucune
	// affectation : il enregistre uniquement l'ordre des centres et des
	// événements afin de retrouver la même disposition au prochain chargement.
	let triPlanningActif = null;

	// Les lieux peuvent être repliés pour libérer de la place. Le choix est
	// conservé uniquement dans le navigateur : il ne modifie aucune donnée.
	const CENTRES_REPLIES_KEY = "planning-centres-replies";

	function lireCentresReplies()
	{
		try
		{
			const ids = JSON.parse(localStorage.getItem(CENTRES_REPLIES_KEY) || "[]");
			return new Set(Array.isArray(ids) ? ids.map(Number).filter(Number.isFinite) : []);
		}
		catch (_erreur)
		{
			return new Set();
		}
	}

	const centresReplies = lireCentresReplies();

	function sauvegarderCentresReplies()
	{
		localStorage.setItem(CENTRES_REPLIES_KEY, JSON.stringify([...centresReplies]));
	}

	function reglerCentreReplie(groupe, centreId, replie)
	{
		const id = Number(centreId);
		const bouton = groupe.querySelector(".centre-collapse-toggle");
		groupe.classList.toggle("collapsed", replie);
		bouton?.setAttribute("aria-expanded", String(!replie));
		bouton?.setAttribute("aria-label", replie ? "Déplier ce lieu" : "Replier ce lieu");

		if (replie) centresReplies.add(id);
		else centresReplies.delete(id);
		sauvegarderCentresReplies();

		if (!replie)
		{
			window.setTimeout(() =>
			{
				calendars
					.filter((calendar) => Number(calendar.centrePlanning?.id) === id)
					.forEach((calendar) => calendar.updateSize());
			}, 30);
		}
	}

	function idsEnfants(container, selector, dataKey)
	{
		return Array.from(container.querySelectorAll(`:scope > ${selector}`))
			.map((element) => Number(element.dataset[dataKey]));
	}

	function memesIds(idsA, idsB)
	{
		return idsA.length === idsB.length && idsA.every((id, index) => id === idsB[index]);
	}

	function restaurerOrdreDom(container, selector, dataKey, ids)
	{
		const elements = new Map(
			Array.from(container.querySelectorAll(`:scope > ${selector}`))
				.map((element) => [Number(element.dataset[dataKey]), element])
		);
		ids.forEach((id) =>
		{
			const element = elements.get(Number(id));
			if (element) container.appendChild(element);
		});
	}

	function placerAvantCible(event, cible, verticalSeulement = false)
	{
		const rect = cible.getBoundingClientRect();
		if (verticalSeulement) return event.clientY < rect.top + (rect.height / 2);

		// Les centres sont disposés dans une grille : sur une même ligne, la
		// position horizontale décide ; entre deux lignes, la verticale suffit.
		if (event.clientY >= rect.top && event.clientY <= rect.bottom)
		{
			return event.clientX < rect.left + (rect.width / 2);
		}
		return event.clientY < rect.top + (rect.height / 2);
	}

	function demarrerTriPlanning(event, configuration)
	{
		event.stopPropagation();
		triPlanningActif = {
			...configuration,
			idsOrigine: idsEnfants(
				configuration.container,
				configuration.selector,
				configuration.dataKey
			),
		};
		configuration.element.classList.add("planning-dragging");
		document.body.classList.add("planning-sort-active");
		event.dataTransfer.effectAllowed = "move";
		event.dataTransfer.setData("text/plain", `${configuration.type}:${configuration.id}`);
	}

	function deplacerTriPlanning(event, cible, verticalSeulement = false)
	{
		if (!triPlanningActif || triPlanningActif.element === cible) return;
		event.preventDefault();
		event.dataTransfer.dropEffect = "move";

		const container = triPlanningActif.container;
		if (placerAvantCible(event, cible, verticalSeulement))
		{
			container.insertBefore(triPlanningActif.element, cible);
		}
		else
		{
			cible.insertAdjacentElement("afterend", triPlanningActif.element);
		}
	}

	function mettreAJourCacheOrdre(type, ids, centreId = null)
	{
		if (type === "centre")
		{
			const centresParId = new Map(centresPlanning.map((centre) => [Number(centre.id), centre]));
			centresPlanning = ids.map((id, ordre) =>
			{
				const centre = centresParId.get(Number(id));
				if (centre) centre.ordre = ordre;
				return centre;
			}).filter(Boolean);
			return;
		}

		const centre = centresPlanning.find((item) => Number(item.id) === Number(centreId));
		if (!centre) return;
		const evenementsParId = new Map((centre.evenements || []).map((evenement) => [Number(evenement.id), evenement]));
		centre.evenements = ids.map((id, ordre) =>
		{
			const evenement = evenementsParId.get(Number(id));
			if (evenement) evenement.ordre = ordre;
			return evenement;
		}).filter(Boolean);
	}

	function terminerTriPlanning()
	{
		if (!triPlanningActif) return;

		const etat = triPlanningActif;
		triPlanningActif = null;
		etat.element.classList.remove("planning-dragging");
		document.body.classList.remove("planning-sort-active");

		const ids = idsEnfants(etat.container, etat.selector, etat.dataKey);
		if (memesIds(ids, etat.idsOrigine)) return;

		const url = etat.type === "centre"
			? "/api/centres/reordonner/"
			: `/api/centres/${etat.centreId}/evenements/reordonner/`;
		const payload = etat.type === "centre"
			? { centre_ids: ids }
			: { evenement_ids: ids };

		apiFetch(url, { method: "POST", body: JSON.stringify(payload) })
			.then(() =>
			{
				mettreAJourCacheOrdre(etat.type, ids, etat.centreId);
				afficherToast(etat.type === "centre"
					? "Ordre des centres enregistré."
					: "Ordre des événements enregistré.");
			})
			.catch((err) =>
			{
				restaurerOrdreDom(etat.container, etat.selector, etat.dataKey, etat.idsOrigine);
				afficherToast(erreurMessage(err, "L’ordre n’a pas pu être enregistré."), true);
			});
	}

	function installerTriCentre(groupe, centre)
	{
		const poignee = groupe.querySelector(".centre-drag-handle");
		poignee.addEventListener("dragstart", (event) => demarrerTriPlanning(event, {
			type: "centre",
			id: centre.id,
			element: groupe,
			container: calendarsContainer,
			selector: ".centre-planning-group",
			dataKey: "centreId",
		}));
		poignee.addEventListener("dragend", terminerTriPlanning);
		groupe.addEventListener("dragover", (event) =>
		{
			if (triPlanningActif?.type === "centre") deplacerTriPlanning(event, groupe);
		});
		groupe.addEventListener("drop", (event) =>
		{
			if (triPlanningActif?.type !== "centre") return;
			event.preventDefault();
			terminerTriPlanning();
		});
	}

	function installerTriEvenement(card, centre, evenement, zoneEvenements)
	{
		const poignee = card.querySelector(".evenement-drag-handle");
		poignee.addEventListener("dragstart", (event) => demarrerTriPlanning(event, {
			type: "evenement",
			id: evenement.id,
			centreId: centre.id,
			element: card,
			container: zoneEvenements,
			selector: ".evenement-calendar-card",
			dataKey: "evenementId",
		}));
		poignee.addEventListener("dragend", terminerTriPlanning);
		card.addEventListener("dragover", (event) =>
		{
			if (triPlanningActif?.type === "evenement" && Number(triPlanningActif.centreId) === Number(centre.id))
			{
				deplacerTriPlanning(event, card, true);
			}
		});
		card.addEventListener("drop", (event) =>
		{
			if (triPlanningActif?.type !== "evenement" || Number(triPlanningActif.centreId) !== Number(centre.id)) return;
			event.preventDefault();
			terminerTriPlanning();
		});
	}


function libelleDate(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
	}

	function periodeEvenementLibelle(evenement)
	{
		if (evenement.debut && evenement.fin)
		{
			return `Du ${libelleDate(evenement.debut)} au ${libelleDate(evenement.fin)}`;
		}
		if (evenement.debut) return `À partir du ${libelleDate(evenement.debut)}`;
		if (evenement.fin) return `Jusqu’au ${libelleDate(evenement.fin)}`;
		return "Période non définie";
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
		const morceaux = [];
		if (animateur.centre_prefere) morceaux.push(`Préféré : ${animateur.centre_prefere.nom}`);
		if (animateur.centres_secondaires && animateur.centres_secondaires.length)
		{
			morceaux.push(`Secondaires : ${animateur.centres_secondaires.map((centre) => centre.nom).join(" · ")}`);
		}
		return morceaux.length ? morceaux.join(" — ") : "Aucun centre renseigné";
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
				<p><strong>Événement préféré</strong><span>${escapeHtml(animateur.evenement_preferee?.nom || "Aucune préférence")}</span></p>
				<p><strong>Disponibilités</strong><span>${escapeHtml(disponibilitesTexte(plages))}</span></p>
			</div>
			<p class="selected-help">Clique sur un jour d'un calendrier pour affecter ${escapeHtml(animateur.prenom)}. Sa fiche et ses disponibilités se modifient dans Gestion > Salariés.</p>
		`;

		selectedChip.insertAdjacentElement("afterend", selectedDetail);

		// requestAnimationFrame laisse le navigateur insérer l'élément avant
		// d'ajouter la classe .open : l'animation CSS peut ainsi se déclencher.
		requestAnimationFrame(() => selectedDetail.classList.add("open"));

	}



	function animateurDisponibleCeJour(animateur, dateStr)
	{
		// Même règle que le backend : sans plage renseignée, l'animateur est indisponible.
		if (!animateur.disponibilites || animateur.disponibilites.length === 0)
		{
			return false;
		}

		return animateur.disponibilites.some((plage) => dateDansPlage(dateStr, plage.debut, plage.fin));
	}



	function numeroJourSemaine(dateStr)
	{
		const jourJs = parseLocalDate(dateStr).getDay();
		return (jourJs + 6) % 7; // 0=lundi ... 6=dimanche
	}

	function evenementOuvertCeJour(evenement, dateStr)
	{
		if (!evenement || !dateStr || evenement.active === false) return false;
		if (evenement.debut && dateStr < evenement.debut) return false;
		if (evenement.fin && dateStr > evenement.fin) return false;
		const joursOuverts = Array.isArray(evenement.jours_ouverts)
			? evenement.jours_ouverts.map(Number)
			: [0, 1, 2, 3, 4, 5];
		if (!joursOuverts.includes(numeroJourSemaine(dateStr))) return false;
		if ((evenement.dates_exclues || []).includes(dateStr)) return false;
		return true;
	}

	function intervalleDansPeriodeEvenement(evenement, debutStr, finExclusiveStr)
	{
		if (!finExclusiveStr) return evenementOuvertCeJour(evenement, debutStr);
		let jour = debutStr;
		while (jour < finExclusiveStr)
		{
			if (!evenementOuvertCeJour(evenement, jour)) return false;
			jour = addDays(jour, 1);
		}
		return true;
	}

	function animateurDejaAffecteSurIntervalle(animateurId, debutStr, finStr, excludeEventId = null)
	{
		const exclude = excludeEventId !== null && excludeEventId !== undefined ? String(excludeEventId) : null;

		return calendars.some((calendar) =>
			calendar.getEvents().some((event) =>
			{
				if (!estVraieAffectation(event)) return false;
				if (exclude && idEventNormalise(event) === exclude) return false;

				const eventAnimateurId = idAnimateurDepuisEvent(event);
				if (eventAnimateurId !== Number(animateurId)) return false;

				const intervalle = eventIntervalleDates(event);
				if (!intervallesSeChevauchent(debutStr, finStr, intervalle.debut, intervalle.fin)) return false;

				// La gestion est exclusivement journalière : toute autre affectation
				// qui chevauche cette date constitue donc un conflit.
				return true;
			})
		);
	}

	function animateurDejaAffecteCeJour(animateurId, dateStr, excludeEventId = null)
	{
		return animateurDejaAffecteSurIntervalle(
			animateurId,
			dateStr,
			addDays(dateStr, 1),
			excludeEventId
		);
	}

	function animateurPlacableSurJour(animateur, dateStr, evenement = null, excludeEventId = null)
	{
		return evenementOuvertCeJour(evenement, dateStr)
			&& animateurDisponibleCeJour(animateur, dateStr)
			&& !animateurDejaAffecteCeJour(animateur.id, dateStr, excludeEventId);
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

	function surlignerAnimateursDisponibles(dateStr, centre, evenement)
	{
		document.querySelectorAll(".animateur").forEach((chip) =>
		{
			const animateur = animateursPlanning.find((a) => Number(a.id) === Number(chip.dataset.animateurId));
			if (!animateur) return;

			const disponible = animateurDisponibleCeJour(animateur, dateStr);
			const dejaPlace = animateurDejaAffecteCeJour(animateur.id, dateStr);
			const placable = disponible && !dejaPlace;

			chip.classList.toggle("day-available", placable);
			chip.classList.toggle("day-unavailable", !placable);

			if (!disponible)
			{
				chip.dataset.dayHint = "Non disponible ce jour-là";
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

	function activerModePlacementJour(info, centre, evenement, calendar)
	{
		if (!evenementOuvertCeJour(evenement, info.dateStr)) return;

		if (!evenement.active)
		{
			afficherToast(`L’événement ${evenement.nom} est inactif : réactive-la dans Gestion pour y ajouter des animateurs.`, true);
			return;
		}

		const memeJour = jourSelectionnePourPlacement
			&& jourSelectionnePourPlacement.date === info.dateStr
			&& Number(jourSelectionnePourPlacement.evenement.id) === Number(evenement.id);

		nettoyerModePlacementJour();

		if (memeJour)
		{
			afficherToast("Sélection du jour annulée.");
			return;
		}

		jourSelectionnePourPlacement = {
			date: info.dateStr,
			centre: centre,
			evenement: evenement,
			calendar: calendar,
		};

		celluleJourSelectionnee = info.dayEl;
		celluleJourSelectionnee.classList.add("jour-placement-selected");
		info.dayEl.closest(".calendar-card")?.classList.add("day-pick-active");

		surlignerAnimateursDisponibles(info.dateStr, centre, evenement);
		afficherToast(`Choisis un animateur pour ${centre.nom} — ${evenement.nom}, le ${libelleDate(info.dateStr)}.`);
	}

	function creerAffectationDepuisJour(animateur, centre, evenement, calendar, debut)
	{
		if (!evenementOuvertCeJour(evenement, debut))
		{
			return Promise.reject({ error: "Ce jour est en dehors de la période de l’événement." });
		}

		const fin = addDays(debut, 1);

		return apiFetch("/api/affectations/",
		{
			method: "POST",
			body: JSON.stringify({
				animateur_id: animateur.id,
				centre_id: centre.id,
				evenement_id: evenement.id,
				debut: debut,
				fin: fin,
			}),
		}).then((data) =>
		{
			rafraichirAffectationsVisibles();
			afficherToast(`${animateur.prenom} affecté·e à ${centre.nom} — ${evenement.nom}, le ${libelleDate(debut)}.`);
			return data;
		});
	}

	function affecterAnimateurSurJourSelectionne(animateur)
	{
		if (!jourSelectionnePourPlacement) return false;

		const { date, centre, evenement, calendar } = jourSelectionnePourPlacement;

		if (!animateurPlacableSurJour(animateur, date, evenement))
		{
			if (!animateurDisponibleCeJour(animateur, date))
			{
				afficherToast(`${animateur.prenom} n'est pas disponible le ${libelleDate(date)}.`, true);
			}
			else
			{
				afficherToast(`${animateur.prenom} est déjà affecté·e ce jour-là.`, true);
			}
			return true;
		}

		creerAffectationDepuisJour(animateur, centre, evenement, calendar, date)
			.then(() => nettoyerModePlacementJour())
			.catch((err) => afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true));

		return true;
	}

	function rafraichirAffectationsVisibles()
	{
		calendars.forEach((calendar) =>
		{
			calendar.getEvents().forEach((event) =>
			{
				if (estVraieAffectation(event)) event.remove();
			});
			calendar.refetchEvents();
		});
	}

	// -----------------------------------------------------------------
	// Calendriers (un par centre)
	// -----------------------------------------------------------------

	// Appelée quand on déplace ou redimensionne un évènement existant
	// (glisser-déposer classique). On enregistre le nouveau créneau côté
	// serveur, et si le serveur refuse (conflit, indisponibilité...) on
	// annule visuellement le déplacement avec info.revert().
	function updateAffectation(info, centre = null, evenement = null)
	{
		const event = info.event;
		const payload = {
			debut: event.startStr,
			fin: event.endStr || addDays(event.startStr, 1),
		};

		if (evenement)
		{
			payload.evenement_id = evenement.id;
			payload.centre_id = centre.id;
		}
		else if (centre)
		{
			payload.centre_id = centre.id;
		}

		return apiFetch(`/api/affectations/${event.id}/`,
		{
			method: "PATCH",
			body: JSON.stringify(payload),
		}).then((data) =>
		{
			rafraichirAffectationsVisibles();
			return data;
		}).catch((err) =>
		{
			afficherToast(erreurMessage(err, "La mise à jour n'a pas pu être enregistrée."), true);
			if (typeof info.revert === "function") info.revert();
			throw err;
		});
	}

	// Une instance FullCalendar par événement. Toutes les événements d'un même
	// centre restent regroupées visuellement dans le même bloc.
	function creerCalendar(centre, evenement, card)
	{
		const calendarEl = card.querySelector(".calendar");

		const calendar = new FullCalendar.Calendar(calendarEl,
		{
			initialView: "dayGridWeek",
			height: "auto",
			locale: "fr",
			firstDay: 1,
			hiddenDays: [0],
			editable: true,
			droppable: Boolean(evenement.active),
			selectable: Boolean(evenement.active),

			dayCellClassNames: function (arg)
			{
				const dateStr = formatDateLocal(arg.date);
				return evenementOuvertCeJour(evenement, dateStr)
					? []
					: ["evenement-hors-periode"];
			},

			dayCellDidMount: function (arg)
			{
				const dateStr = formatDateLocal(arg.date);
				if (!evenementOuvertCeJour(evenement, dateStr))
				{
					arg.el.setAttribute("aria-disabled", "true");
					arg.el.title = "Événement fermé à cette date (hors période, jour habituel non ouvert ou date exclue)";
				}
			},

			eventOrder: function (eventA, eventB)
			{
				const animateurA = Number(eventA.extendedProps?.animateur_id || eventA.extendedProps?.animateurId || 0);
				const animateurB = Number(eventB.extendedProps?.animateur_id || eventB.extendedProps?.animateurId || 0);
				if (animateurA !== animateurB) return animateurA - animateurB;
				return String(eventA.title || "").localeCompare(String(eventB.title || ""), "fr");
			},
			eventOrderStrict: true,
			expandRows: false,
			headerToolbar: false,
			footerToolbar: false,

			events: `/api/planning/?evenement_id=${evenement.id}`,

			datesSet: function (info)
			{
				toolbarLabel.textContent = info.view.title;
				if (animateurActif)
				{
					afficherDisponibilites(animateurActif, animateurActif.disponibilites || []);
				}
				else if (animateurDragPreview)
				{
					afficherDisponibilites(animateurDragPreview, animateurDragPreview.disponibilites || []);
				}
			},

			dateClick: function (info)
			{
				if (!evenementOuvertCeJour(evenement, info.dateStr)) return;

				if (!evenement.active)
				{
					afficherToast(`L’événement ${evenement.nom} est inactif.`, true);
					return;
				}

				if (!animateurActif)
				{
					activerModePlacementJour(info, centre, evenement, calendar);
					return;
				}

				creerAffectationDepuisJour(animateurActif, centre, evenement, info.view.calendar, info.dateStr)
					.catch((err) => afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true));
			},

			eventAllow: function (dropInfo, draggedEvent)
			{
				if (!evenement.active) return false;

				const debut = formatDateLocal(dropInfo.start);
				const fin = dropInfo.end ? formatDateLocal(dropInfo.end) : addDays(debut, 1);
				if (!intervalleDansPeriodeEvenement(evenement, debut, fin)) return false;

				const animateurId = idAnimateurDepuisEvent(draggedEvent);
				if (!animateurId) return true;
				const animateur = animateursPlanning.find((a) => Number(a.id) === Number(animateurId));
				if (animateur && !animateurDisponibleCeJour(animateur, debut)) return false;

				return !animateurDejaAffecteSurIntervalle(
					animateurId,
					debut,
					fin,
					idEventNormalise(draggedEvent)
				);
			},

			eventReceive: function (info)
			{
				const debut = info.event.startStr;
				const fin = info.event.endStr || addDays(debut, 1);

				if (!intervalleDansPeriodeEvenement(evenement, debut, fin))
				{
					info.event.remove();
					return;
				}

				if (!evenement.active)
				{
					info.event.remove();
					afficherToast(`L’événement ${evenement.nom} est inactif.`, true);
					return;
				}

				if (info.event.id)
				{
					updateAffectation(info, centre, evenement).catch(() => info.event.remove());
					return;
				}

				const animateurId = info.event.extendedProps.animateurId;
				apiFetch("/api/affectations/",
				{
					method: "POST",
					body: JSON.stringify({
						animateur_id: animateurId,
						centre_id: centre.id,
						evenement_id: evenement.id,
						debut: debut,
						fin: fin,
					}),
				}).then(() =>
				{
					rafraichirAffectationsVisibles();
				}).catch((err) =>
				{
					afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true);
					info.event.remove();
				}).finally(() =>
				{
					if (!animateurActif) nettoyerDisponibilitesDragPreview();
				});
			},

			eventDrop: function (info) { updateAffectation(info, centre, evenement); },
			eventResize: function (info) { updateAffectation(info, centre, evenement); },

			eventClick: function (info)
			{
				if (info.event.display === "background") return;
				if (confirm(`Supprimer l'affectation de ${info.event.title} dans ${evenement.nom} ?`))
				{
					apiFetch(`/api/affectations/${info.event.id}/`, { method: "DELETE" })
						.then(() => info.event.remove())
						.catch((err) => afficherToast(erreurMessage(err, "La suppression a échoué."), true));
				}
			},
		});

		calendar.centrePlanning = centre;
		calendar.evenementPlanning = evenement;
		calendar.render();
		return calendar;
	}

	function ajouterCentreAuPlanning(centre)
	{
		const groupe = document.createElement("section");
		groupe.classList.add("centre-planning-group");
		groupe.dataset.centreId = centre.id;
		groupe.style.setProperty("--centre-color", centre.couleur);

		const evenements = centre.evenements || [];
		groupe.innerHTML = `
			<header class="centre-planning-header">
				<div class="centre-planning-title">
					<span class="planning-drag-handle centre-drag-handle" draggable="true" role="button" tabindex="0" aria-label="Déplacer le planning du centre ${escapeHtml(centre.nom)}" title="Glisser pour déplacer ce centre">⠿</span>
					<div>
						<span class="centre-planning-code">${escapeHtml(centre.code || "")}</span>
						<h2>${escapeHtml(centre.nom)}</h2>
					</div>
				</div>
				<div class="centre-planning-actions">
					<span class="centre-evenements-count">${evenements.length} événement${evenements.length > 1 ? "s" : ""}</span>
					<button class="centre-collapse-toggle" type="button" aria-expanded="true" aria-label="Replier ce lieu" title="Replier ou déplier ce lieu">
						<span aria-hidden="true">⌄</span>
					</button>
				</div>
			</header>
			<div class="evenement-calendars"></div>`;

		calendarsContainer.appendChild(groupe);
		attacherSurvolCentre(groupe, centre.id);
		installerTriCentre(groupe, centre);

		const boutonRepli = groupe.querySelector(".centre-collapse-toggle");
		boutonRepli.addEventListener("click", () =>
		{
			reglerCentreReplie(groupe, centre.id, !groupe.classList.contains("collapsed"));
		});

		const zoneEvenements = groupe.querySelector(".evenement-calendars");
		if (evenements.length === 0)
		{
			zoneEvenements.innerHTML = '<p class="empty-note">Aucun événement dans ce lieu.</p>';
			if (centresReplies.has(Number(centre.id)))
			{
				reglerCentreReplie(groupe, centre.id, true);
			}
			return;
		}

		evenements.forEach((evenement) =>
		{
			const card = document.createElement("article");
			card.classList.add("calendar-card", "evenement-calendar-card");
			if (!evenement.active) card.classList.add("evenement-inactive");
			card.dataset.centreId = centre.id;
			card.dataset.evenementId = evenement.id;
			card.style.setProperty("--centre-color", centre.couleur);

			card.innerHTML = `
				<header class="evenement-calendar-header">
					<div class="evenement-calendar-title">
						<span class="planning-drag-handle evenement-drag-handle" draggable="true" role="button" tabindex="0" aria-label="Déplacer le planning ${escapeHtml(evenement.nom)}" title="Glisser pour déplacer cet événement">⠿</span>
						<div>
							<h3>${escapeHtml(evenement.nom)}</h3>
						</div>
					</div>
					<div class="evenement-calendar-meta">
						<span>Objectif ${escapeHtml(evenement.effectif_cible)}</span>
						${evenement.active ? "" : '<span class="evenement-inactive-badge">Inactive</span>'}
					</div>
				</header>
				<div class="calendar"></div>`;

			zoneEvenements.appendChild(card);
			installerTriEvenement(card, centre, evenement, zoneEvenements);
			const calendar = creerCalendar(centre, evenement, card);
			calendars.push(calendar);
		});

		if (centresReplies.has(Number(centre.id)))
		{
			reglerCentreReplie(groupe, centre.id, true);
		}
	}

	function chargerCentres()
	{
		return apiFetch("/api/centres/")
			.then((centres) => Promise.all(centres.map((centre) =>
				apiFetch(`/api/centres/${centre.id}/evenements/`)
					.then((evenements) => ({ ...centre, evenements }))
			)))
			.then((centres) =>
			{
				centresPlanning = centres;
				centresFiltresCharges = true;
				rafraichirFiltresAnimateurs();
				calendars.splice(0).forEach((calendar) => calendar.destroy());
				calendarsContainer.innerHTML = "";

				if (centres.length === 0)
				{
					calendarsContainer.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant. Ajoute-en un depuis Gestion.</p>';
					return;
				}

				centres.forEach((centre) => ajouterCentreAuPlanning(centre));
				appliquerModeVue(document.querySelector(".view-btn.active")?.dataset.view || "dayGridWeek");
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

	function appliquerModeVue(viewName)
	{
		// Sur la page planning, les calendriers doivent se comporter comme sur
		// l'accueil : en vue semaine ils restent compacts, et en vue mois ils
		// grandissent naturellement avec toutes les lignes du mois.
		const vueMois = viewName === "dayGridMonth";
		calendarsContainer.classList.toggle("planning-view-month", vueMois);
		calendarsContainer.classList.toggle("planning-view-week", !vueMois);

		requestAnimationFrame(() =>
		{
			calendars.forEach((calendar) => calendar.updateSize());
		});
	}

	document.querySelectorAll(".view-btn").forEach((btn) =>
	{
		btn.addEventListener("click", () =>
		{
			document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("active"));
			btn.classList.add("active");
			calendars.forEach((c) => c.changeView(btn.dataset.view));
			appliquerModeVue(btn.dataset.view);
		});
	});

	// Mode initial : semaine compacte.
	appliquerModeVue("dayGridWeek");


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
		const samedi = new Date(lundi);
		samedi.setDate(samedi.getDate() + 5);

		const confirmation = confirm(
			"Supprimer les affectations À VENIR de cette semaine (à partir d'aujourd'hui), dans les 3 centres ? Les jours déjà passés ne sont jamais touchés. Cette action est irréversible."
		);
		if (!confirmation) return;

		apiFetch(`/api/planning/plage/?debut=${formatDateLocal(lundi)}&fin=${formatDateLocal(samedi)}`, { method: "DELETE" })
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
		div.dataset.couleur = animateur.couleur || "";

		const centresAutorises = animateur.centres_autorises || [];
		const couleurAnimateur = animateur.couleur || "#64748b";
		div.style.setProperty("--animateur-color", couleurAnimateur);
		div.style.setProperty("--animateur-text", ColorUtils.texteLisible(couleurAnimateur));

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
			const estPrefere = animateur.centre_prefere && Number(animateur.centre_prefere.id) === Number(centre.id);
			if (estPrefere) dot.classList.add("preferred");
			dot.dataset.centre = centre.id;
			dot.style.setProperty("--c", centre.couleur);
			dot.title = estPrefere ? `${centre.nom} — centre préféré` : `${centre.nom} — centre secondaire`;
			dot.textContent = `${estPrefere ? "★" : ""}${centre.code || "•"}`;
			centresBadges.appendChild(dot);
		});

		div.appendChild(centresBadges);

		// Début de prise en main de l'étiquette : on affiche tout de suite
		// les disponibilités, avant même que l'animateur soit déposé.
		// On écoute plusieurs évènements car FullCalendar peut initier le
		// déplacement différemment selon souris/tactile/navigateur.
		["pointerdown", "mousedown", "touchstart"].forEach((eventName) =>
		{
			div.addEventListener(eventName, () => afficherDisponibilitesPendantDrag(animateur), { passive: true });
		});

		// Clic = sélectionner/désélectionner cet animateur (voir toggleSelection).
		div.addEventListener("click", () => toggleSelection(div, animateur));

		return div;
	}

	function comparerTexte(a, b)
	{
		return String(a || "").localeCompare(String(b || ""), "fr", { sensitivity: "base" });
	}

	function comparerAnimateursParPrenom(a, b)
	{
		return comparerTexte(a.prenom, b.prenom) || comparerTexte(a.nom, b.nom);
	}

	function idsCentresAnimateur(animateur)
	{
		return new Set((animateur.centres_autorises || []).map((centre) => Number(centre.id)));
	}

	function animateurCorrespondAuxFiltres(animateur)
	{
		const qualificationsAnimateur = new Set((animateur.qualification_ids || []).map(Number));
		const possedeToutesLesQualifications = [...filtresQualificationsAnimateurs]
			.every((qualificationId) => qualificationsAnimateur.has(qualificationId));
		if (!possedeToutesLesQualifications) return false;

		if (filtresCentresAnimateurs.size === 0) return true;
		const centresAnimateur = idsCentresAnimateur(animateur);
		return [...filtresCentresAnimateurs].some((centreId) => centresAnimateur.has(centreId));
	}

	function sauvegarderFiltresAnimateurs()
	{
		localStorage.setItem("planning-filtres-qualifications", JSON.stringify([...filtresQualificationsAnimateurs]));
		localStorage.setItem("planning-filtres-centres", JSON.stringify([...filtresCentresAnimateurs]));
	}

	function nombreFiltresAnimateursActifs()
	{
		return filtresQualificationsAnimateurs.size + filtresCentresAnimateurs.size;
	}

	function mettreAJourResumeFiltresAnimateurs(_nombreAffiche)
	{
		const nombreActifs = nombreFiltresAnimateursActifs();
		if (compteurFiltresAnimateurs)
		{
			compteurFiltresAnimateurs.textContent = String(nombreActifs);
			compteurFiltresAnimateurs.hidden = nombreActifs === 0;
		}
	}

	function creerCaseFiltre(type, item, selection)
	{
		const label = document.createElement("label");
		label.className = "animateurs-filter-option";

		const input = document.createElement("input");
		input.type = "checkbox";
		input.id = `filtre-animateurs-${type}-${item.id}`;
		input.name = `filtres_animateurs_${type}`;
		input.value = String(item.id);
		input.checked = selection.has(Number(item.id));

		const texte = document.createElement("span");
		texte.textContent = item.nom;
		label.append(input, texte);

		input.addEventListener("change", () =>
		{
			const id = Number(input.value);
			if (input.checked) selection.add(id);
			else selection.delete(id);
			sauvegarderFiltresAnimateurs();
			rendreListeAnimateurs();
		});

		return label;
	}

	function rafraichirFiltresAnimateurs()
	{
		if (qualificationsFiltresChargees)
		{
			const idsExistants = new Set(qualificationsPlanning.map((qualification) => Number(qualification.id)));
			filtresQualificationsAnimateurs = new Set(
				[...filtresQualificationsAnimateurs].filter((id) => idsExistants.has(id))
			);
			if (filtresQualificationsConteneur)
			{
				filtresQualificationsConteneur.innerHTML = "";
				if (qualificationsPlanning.length === 0)
				{
					filtresQualificationsConteneur.innerHTML = '<span class="empty-note">Aucune qualification</span>';
				}
				else
				{
					[...qualificationsPlanning]
						.sort((a, b) => comparerTexte(a.nom, b.nom))
						.forEach((qualification) => filtresQualificationsConteneur.appendChild(
							creerCaseFiltre("qualification", qualification, filtresQualificationsAnimateurs)
						));
				}
			}
		}

		if (centresFiltresCharges)
		{
			const idsExistants = new Set(centresPlanning.map((centre) => Number(centre.id)));
			filtresCentresAnimateurs = new Set(
				[...filtresCentresAnimateurs].filter((id) => idsExistants.has(id))
			);
			if (filtresCentresConteneur)
			{
				filtresCentresConteneur.innerHTML = "";
				if (centresPlanning.length === 0)
				{
					filtresCentresConteneur.innerHTML = '<span class="empty-note">Aucun lieu</span>';
				}
				else
				{
					[...centresPlanning]
						.sort((a, b) => comparerTexte(a.nom, b.nom))
						.forEach((centre) => filtresCentresConteneur.appendChild(
							creerCaseFiltre("centre", centre, filtresCentresAnimateurs)
						));
				}
			}
		}

		sauvegarderFiltresAnimateurs();
		rendreListeAnimateurs();
	}

	function animateursFiltresEtTries()
	{
		return animateursPlanning
			.filter(animateurCorrespondAuxFiltres)
			.sort(comparerAnimateursParPrenom);
	}

	function rendreListeAnimateurs()
	{
		animList.innerHTML = "";

		if (animateursPlanning.length === 0)
		{
			animList.innerHTML = '<p class="empty-note">Aucun animateur pour l\'instant.</p>';
			mettreAJourResumeFiltresAnimateurs(0);
			return;
		}

		const animateursAffiches = animateursFiltresEtTries();
		if (animateurActif && !animateursAffiches.some((animateur) => Number(animateur.id) === Number(animateurActif.id)))
		{
			animateurDragPreview = null;
			effacerDisponibilitesAffichees();
			animateurActif = null;
			selectedChip = null;
			retirerFicheAnimateurSelectionne();
		}

		selectedChip = null;
		animateursAffiches.forEach((animateur) =>
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

		if (animateursAffiches.length === 0)
		{
			animList.innerHTML = '<p class="empty-note">Aucun salarié ne correspond aux filtres cochés.</p>';
		}
		mettreAJourResumeFiltresAnimateurs(animateursAffiches.length);
	}

	// (Re)charge la liste des animateurs dans la barre latérale. Appelée
	// au chargement initial, et à nouveau après un ajout/suppression.
	function chargerAnimateurs()
	{
		return apiFetch("/api/animateurs/").then((animateurs) =>
		{
			animateursPlanning = animateurs;
			rendreListeAnimateurs();
		});
	}

	function chargerQualificationsFiltres()
	{
		return apiFetch("/api/qualifications/")
			.then((qualifications) =>
			{
				qualificationsPlanning = qualifications;
				qualificationsFiltresChargees = true;
				rafraichirFiltresAnimateurs();
			})
			.catch(() =>
			{
				qualificationsPlanning = [];
				qualificationsFiltresChargees = true;
				rafraichirFiltresAnimateurs();
			});
	}

	if (boutonEffacerFiltresAnimateurs)
	{
		boutonEffacerFiltresAnimateurs.addEventListener("click", () =>
		{
			filtresQualificationsAnimateurs.clear();
			filtresCentresAnimateurs.clear();
			sauvegarderFiltresAnimateurs();
			rafraichirFiltresAnimateurs();
		});
	}

	if (filtresAnimateursDetails)
	{
		const positionnerPanneauFiltres = () =>
		{
			const panneau = filtresAnimateursDetails.querySelector(".animateurs-filter-panel");
			const resume = filtresAnimateursDetails.querySelector("summary");
			if (!panneau || !resume || window.innerWidth <= 640) return;
			const rect = resume.getBoundingClientRect();
			panneau.style.top = `${Math.round(rect.bottom + 7)}px`;
			panneau.style.right = `${Math.max(10, Math.round(window.innerWidth - rect.right))}px`;
		};

		filtresAnimateursDetails.addEventListener("toggle", () =>
		{
			if (filtresAnimateursDetails.open) positionnerPanneauFiltres();
		});
		window.addEventListener("resize", () =>
		{
			if (filtresAnimateursDetails.open) positionnerPanneauFiltres();
		});

		document.addEventListener("click", (event) =>
		{
			if (filtresAnimateursDetails.open && !filtresAnimateursDetails.contains(event.target))
			{
				filtresAnimateursDetails.removeAttribute("open");
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
	function couleurDisponibilitePourCentre(animateur, centre)
	{
		if (animateur.centre_prefere && Number(animateur.centre_prefere.id) === Number(centre.id))
		{
			return "#3ba55c"; // vert : centre préféré
		}

		const estSecondaire = (animateur.centres_secondaires || []).some(
			(c) => Number(c.id) === Number(centre.id)
		);
		if (estSecondaire) return "#f59e0b"; // orange : centre secondaire

		return "#dc2626"; // rouge : centre non renseigné
	}

	function plagesDisponibilitesPourVue(calendar, plages)
	{
		// Sans disponibilité renseignée, aucune journée ne doit être colorée.
		if (!plages || plages.length === 0)
		{
			return [];
		}

		return plages.map((plage) => ({
			debut: plage.debut,
			finExclusive: addDays(plage.fin, 1),
		}));
	}

	function afficherDisponibilites(animateur, plages)
	{
		animateur.disponibilites = plages || [];
		if (animateurActif && animateurActif.id === animateur.id)
		{
			animateurActif.disponibilites = animateur.disponibilites;
		}

		// On repart toujours de sources propres, sinon les fonds colorés
		// s'empilent quand on change d'animateur ou de semaine.
		effacerDisponibilitesAffichees();

		calendars.forEach((calendar) =>
		{
			const centre = calendar.centrePlanning;
			if (!centre) return;

			const couleur = couleurDisponibilitePourCentre(animateur, centre);

			// FullCalendar affiche les évènements "display: background" comme
			// une simple teinte de fond, sans les traiter comme de vraies
			// affectations (pas cliquables, pas de titre affiché).
			const events = plagesDisponibilitesPourVue(calendar, animateur.disponibilites).map((plage) => ({
				start: plage.debut,
				end: plage.finExclusive,
				display: "background",
				color: couleur,
			}));

			calendar.addEventSource({ id: DISPO_SOURCE_ID, events: events });
		});
	}

	// Affiche temporairement les disponibilités d'un animateur dès que
	// l'utilisateur commence à le prendre pour le glisser dans un calendrier.
	// Ça donne le même repère visuel que la sélection classique : vert sur
	// son premier centre autorisé, orange sur les suivants et rouge sur les
	// centres qui ne font pas partie de ses centres autorisés.
	function afficherDisponibilitesPendantDrag(animateur)
	{
		// Si l'animateur est déjà sélectionné, les disponibilités sont déjà
		// affichées durablement par toggleSelection().
		if (animateurActif && Number(animateurActif.id) === Number(animateur.id))
		{
			return;
		}

		animateurDragPreview = animateur;

		// Si les disponibilités sont déjà présentes dans le cache animateur,
		// on les affiche immédiatement. Sinon on les charge depuis l'API.
		if (Array.isArray(animateur.disponibilites))
		{
			afficherDisponibilites(animateur, animateur.disponibilites);
			return;
		}

		fetch(`/api/animateurs/${animateur.id}/disponibilites/`)
			.then((response) => response.json())
			.then((data) =>
			{
				// Si l'utilisateur a déjà commencé à glisser un autre animateur,
				// on ignore la réponse devenue obsolète.
				if (!animateurDragPreview || Number(animateurDragPreview.id) !== Number(animateur.id))
				{
					return;
				}

				afficherDisponibilites(animateur, data.disponibilites || []);
			})
			.catch(() => afficherDisponibilites(animateur, animateur.disponibilites || []));
	}

	// Nettoie l'affichage temporaire des disponibilités après un drag
	// non sélectionné. Si un animateur est sélectionné, on garde son affichage.
	function nettoyerDisponibilitesDragPreview()
	{
		animateurDragPreview = null;

		if (animateurActif)
		{
			afficherDisponibilites(animateurActif, animateurActif.disponibilites || []);
		}
		else
		{
			effacerDisponibilitesAffichees();
		}
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
		animateurDragPreview = null;
		effacerDisponibilitesAffichees();
		animateurActif = null;
		selectedChip = null;
		retirerFicheAnimateurSelectionne();

		// Un second clic sur le même animateur = désélectionner et s'arrêter là.
		if (dejaSelectionne) return;

		chip.classList.add("selected");
		animateurActif = animateur;
		selectedChip = chip;
		afficherToast(`${animateur.prenom} sélectionné : clique sur un jour pour l'affecter.`);

		// Affiche immédiatement ses jours disponibles : vert sur son premier
		// centre autorisé, orange sur les autres centres autorisés et rouge sur
		// les centres non autorisés.
		fetch(`/api/animateurs/${animateur.id}/disponibilites/`)
			.then((response) => response.json())
			.then((data) => afficherDisponibilites(animateur, data.disponibilites || []))
			.catch(() => afficherDisponibilites(animateur, animateur.disponibilites || []));
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

	// La page planning est volontairement allégée : la fiche et les
	// disponibilités d'un animateur se modifient dans Gestion > Salariés.
	// Ici on garde uniquement la modale de remplissage automatique.
	const modalAuto = document.getElementById("modal-auto-remplissage");
	const modalAutoContent = document.getElementById("modal-auto-remplissage-content");

	initFermetureModal(modalAuto);

	// Les calendriers occupent maintenant toute la largeur disponible.
	// Aucun scroll horizontal synchronisé n'est nécessaire.

	// -----------------------------------------------------------------
	// Chargement initial
	// -----------------------------------------------------------------

	chargerCentres();
	chargerQualificationsFiltres();
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
				backgroundColor: eventEl.dataset.couleur || undefined,
				borderColor: eventEl.dataset.couleur || undefined,
				textColor: "#ffffff",
				extendedProps: {
					animateurId: eventEl.dataset.animateurId,
				},
			};
		},
	});

	// À la fin du geste de drag/clic, on retire l'aide visuelle si elle était
	// seulement temporaire. Le setTimeout laisse le temps au click de sélection
	// de s'exécuter si c'était un simple clic.
	["pointerup", "pointercancel", "mouseup", "touchend", "dragend", "drop"].forEach((eventName) =>
	{
		document.addEventListener(eventName, () =>
		{
			if (!animateurDragPreview) return;
			// Petit délai : FullCalendar doit d'abord exécuter eventReceive
			// si le dépôt a réellement eu lieu.
			window.setTimeout(nettoyerDisponibilitesDragPreview, 120);
		});
	});
	// Placement automatique de la semaine affichée (lundi -> vendredi),
	// désormais calculé événement par événement.
	const btnAutoSemaine = document.getElementById("btn-auto-semaine");

	function lancerRemplissageAuto(boutonValider)
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
			body: JSON.stringify({ debut }),
		})
		.then((data) =>
		{
			rafraichirAffectationsVisibles();
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

	function ouvrirPopupRemplissageAuto()
	{
		const evenementsActives = centresPlanning.flatMap((centre) =>
			(centre.evenements || [])
				.filter((evenement) => evenement.active)
				.map((evenement) => ({ ...evenement, centre }))
		);

		if (evenementsActives.length === 0)
		{
			afficherToast("Ajoute d'abord au moins un événement actif dans Gestion.", true);
			return;
		}

		const construirePopup = () =>
		{
			const nomsQualifications = new Map(
				(qualificationsPlanning || []).map((qualification) => [String(qualification.id), qualification.nom])
			);

			const centresHtml = centresPlanning.map((centre) =>
			{
				const evenements = (centre.evenements || []).filter((evenement) => evenement.active);
				if (!evenements.length) return "";

				const evenementsHtml = evenements.map((evenement) =>
				{
					const exigences = Object.entries(evenement.qualifications_requises || {})
						.filter(([, nombre]) => Number(nombre) > 0)
						.map(([qualificationId, nombre]) => ({
							nom: nomsQualifications.get(String(qualificationId)) || "Qualification supprimée",
							nombre: Math.max(0, Number(nombre) || 0),
						}));

					const lignesQualifs = exigences.length
						? exigences.map((exigence) => `
							<li><strong>${escapeHtml(exigence.nombre)}</strong> ${escapeHtml(exigence.nom)}</li>`).join("")
						: '<li class="empty-note">Aucune qualification particulière</li>';

					return `
						<div class="auto-evenement-bloc">
							<div class="auto-evenement-entete">
								<div>
									<strong>${escapeHtml(evenement.nom)}</strong>
									<span class="auto-evenement-periode">${escapeHtml(periodeEvenementLibelle(evenement))}</span>
								</div>
								<div class="auto-centre-total auto-centre-total-readonly">
									<span>Personnel / jour</span>
									<strong>${Math.max(0, Number(evenement.effectif_cible) || 0)}</strong>
								</div>
							</div>
							<div class="auto-centre-qualifs auto-centre-qualifs-readonly">
								<strong>Qualifications requises</strong>
								<ul>${lignesQualifs}</ul>
							</div>
						</div>`;
				}).join("");

				return `
					<section class="auto-centre-groupe">
						<header class="auto-centre-groupe-head">
							<span class="centre-pastille" style="background:${escapeHtml(centre.couleur)}"></span>
							<div><strong>${escapeHtml(centre.nom)}</strong><span>${evenements.length} événement${evenements.length > 1 ? "s" : ""}</span></div>
						</header>
						<div class="auto-evenements-liste">${evenementsHtml}</div>
					</section>`;
			}).join("");

			modalAutoContent.innerHTML = `
				<p class="form-hint">Le remplissage automatique utilisera directement le personnel et les qualifications définis pour chaque événement dans <strong>Gestion</strong>. Ces besoins ne sont pas modifiables depuis le planning.</p>
				<div class="auto-centres-liste">${centresHtml}</div>
				<div class="edit-actions">
					<button class="btn btn-primary" id="auto-valider" type="button">Remplir la semaine</button>
					<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
				</div>`;

			modalAutoContent.querySelector("#auto-valider").addEventListener("click", () =>
			{
				if (!confirm("Remplir automatiquement tous les événements du lundi au vendredi avec les besoins enregistrés dans Gestion ? Les affectations existantes de ces jours seront remplacées.")) return;
				lancerRemplissageAuto(modalAutoContent.querySelector("#auto-valider"));
			});

			ouvrirModal(modalAuto);
		};

		apiFetch("/api/qualifications/")
			.then((qualifications) => { qualificationsPlanning = qualifications; construirePopup(); })
			.catch(() => construirePopup());
	}

	if (btnAutoSemaine)
	{
		btnAutoSemaine.disabled = false;
		btnAutoSemaine.removeAttribute("title");
		btnAutoSemaine.textContent = "Remplir auto";
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