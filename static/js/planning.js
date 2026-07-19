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
	const filtresQualificationsConteneur = document.getElementById("animateurs-filter-qualifications");
	const filtresCentresConteneur = document.getElementById("animateurs-filter-centres");
	const filtreDisponibiliteAnimateurs = document.getElementById("animateurs-filter-disponibilite");
	const filtreAffectationAnimateurs = document.getElementById("animateurs-filter-affectation");
	const compteurFiltresAnimateurs = document.getElementById("animateurs-filter-count");
	const boutonEffacerFiltresAnimateurs = document.getElementById("animateurs-filter-reset");
	const rechercheAnimateursInput = document.getElementById("animateurs-search-input");
	const compteurAnimateursVisibles = document.getElementById("animateurs-visible-count");
	const redimensionneurSidebar = document.getElementById("planning-sidebar-resizer");
	const toolbarLabel = document.getElementById("toolbar-label");
	const modalEffectifsEnfants = document.getElementById("modal-effectifs-enfants");
	const formulaireEffectifsEnfants = document.getElementById("effectifs-enfants-form");
	const champsEffectifsEnfants = document.getElementById("effectifs-enfants-fields");
	const titreEffectifsEnfants = document.getElementById("effectifs-enfants-title");
	let contexteEffectifsEnfants = null;

	// Un FullCalendar.Calendar par centre, dans le même ordre que les
	// centres reçus de l'API. On s'en sert pour synchroniser la
	// navigation (précédent/suivant/aujourd’hui) sur tous les calendriers.
	const calendars = [];
	// Date de la période ciblée par la barre de navigation.
	let datePeriodeCourante = null;

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
		catch
		{
			return new Set();
		}
	}

	let filtresQualificationsAnimateurs = lireIdsFiltres("planning-filtres-qualifications");
	let filtresCentresAnimateurs = lireIdsFiltres("planning-filtres-centres-preferes");
	let filtreDisponibiliteAnimateursValeur = "";
	let filtreAffectationAnimateursValeur = "";
	let rechercheAnimateurs = "";
	localStorage.removeItem("planning-tri-animateurs");

	// Identifiant de la "source d'affectations" utilisée pour afficher les
	// disponibilités en fond de calendrier (voir afficherDisponibilites).
	const DISPO_SOURCE_ID = "disponibilites";

	// Animateur actuellement sélectionné dans la liste, s'il y en a un.
	// Sert à deux choses en même temps :
	//   - afficher ses disponibilités en surbrillance sur les calendriers ;
	//   - permettre de l'affecter en cliquant sur un jour (alternative au
	//     glisser-déposer, plus fiable au doigt sur téléphone).
	let animateurActif = null;

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


	// Les lieux peuvent être repliés pour libérer de la place. Le choix est
	// conservé uniquement dans le navigateur : il ne modifie aucune donnée.
	const CENTRES_REPLIES_KEY = "calendar-centres-replies";

	function lireCentresReplies()
	{
		try
		{
			const ids = JSON.parse(localStorage.getItem(CENTRES_REPLIES_KEY) || "[]");
			return new Set(Array.isArray(ids) ? ids.map(Number).filter(Number.isFinite) : []);
		}
		catch
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

	async function enregistrerOrdrePlanning(type, container, selector, dataKey, centreId = null)
	{
		const ids = idsEnfants(container, selector, dataKey);
		const url = type === "centre"
			? "/api/centres/reordonner/"
			: `/api/centres/${centreId}/groupes/reordonner/`;
		const payload = type === "centre"
			? { centre_ids: ids }
			: { evenement_ids: ids };

		try
		{
			await apiFetch(url, { method: "POST", body: JSON.stringify(payload) });
			mettreAJourCacheOrdre(type, ids, centreId);
			afficherToast(type === "centre" ? "Ordre des lieux enregistré." : "Ordre des groupes enregistré.");
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "L’ordre n’a pas pu être enregistré. Recharge la page pour retrouver le dernier ordre enregistré."), true);
		}
	}

	let detruireTriCentres = null;
	const sortablesGroupes = [];

	function optionsTriCommun()
	{
		return {
			animation: 180,
			handle: ".planning-drag-handle",
			draggable: ":scope > *",
			ghostClass: "planning-sort-ghost",
			chosenClass: "planning-sort-chosen",
			dragClass: "planning-sort-drag",
			forceFallback: true,
			fallbackOnBody: true,
			fallbackTolerance: 4,
			scroll: true,
			scrollSensitivity: 95,
			scrollSpeed: 18,
			emptyInsertThreshold: 40,
			delay: 0,
			onStart: () => document.body.classList.add("planning-sort-active"),
			onEnd: () => document.body.classList.remove("planning-sort-active"),
		};
	}

	/*
	 * Les lieux sont affichés dans une grille CSS à deux colonnes et leurs
	 * hauteurs peuvent être très différentes. SortableJS traite cette grille
	 * comme une liste et crée des zones d'insertion incohérentes dans les grands
	 * espaces vides. Le tri des lieux utilise donc un geste pointeur dédié :
	 * aucune insertion pendant le mouvement, puis échange strict des deux cartes
	 * au relâchement.
	 */
	function installerTriCentres()
	{
		detruireTriCentres?.();

		const controleur = new AbortController();
		const { signal } = controleur;
		let geste = null;
		let apercu = null;
		let cible = null;
		let clicABloquer = false;

		function cartes()
		{
			return Array.from(calendarsContainer.querySelectorAll(":scope > .centre-planning-group"));
		}

		function retirerCible()
		{
			cible?.classList.remove("planning-swap-target");
			cible = null;
		}

		function definirCible(nouvelleCible)
		{
			if (nouvelleCible === geste?.source) nouvelleCible = null;
			if (cible === nouvelleCible) return;
			retirerCible();
			cible = nouvelleCible;
			cible?.classList.add("planning-swap-target");
		}

		function distanceAuRectangle(x, y, rect)
		{
			const dx = x < rect.left ? rect.left - x : x > rect.right ? x - rect.right : 0;
			const dy = y < rect.top ? rect.top - y : y > rect.bottom ? y - rect.bottom : 0;
			return (dx * dx) + (dy * dy);
		}

		function cibleVisuelle(x, y)
		{
			const rectConteneur = calendarsContainer.getBoundingClientRect();
			const marge = 60;
			if (x < rectConteneur.left - marge || x > rectConteneur.right + marge ||
				y < rectConteneur.top - marge || y > rectConteneur.bottom + marge)
			{
				return null;
			}

			// Lorsqu'une carte est réellement sous le pointeur, elle gagne toujours.
			const directe = document.elementFromPoint(x, y)?.closest?.(".centre-planning-group");
			if (directe && directe !== geste?.source && calendarsContainer.contains(directe))
			{
				return directe;
			}

			// Dans les trous produits par des cartes de hauteurs différentes, on prend
			// la carte dont le rectangle est le plus proche du pointeur. Ainsi, le vide
			// sous une petite carte appartient naturellement à la carte de la ligne
			// suivante, plutôt qu'à une position d'insertion abstraite.
			let meilleure = null;
			let meilleureDistance = Number.POSITIVE_INFINITY;
			for (const carte of cartes())
			{
				if (carte === geste?.source) continue;
				const distance = distanceAuRectangle(x, y, carte.getBoundingClientRect());
				if (distance < meilleureDistance)
				{
					meilleure = carte;
					meilleureDistance = distance;
				}
			}
			return meilleure;
		}

		function placerApercu(x, y)
		{
			if (!apercu) return;
			apercu.style.left = `${x + 14}px`;
			apercu.style.top = `${y + 14}px`;
		}

		function demarrerDrag(x, y)
		{
			if (!geste || geste.actif) return;
			geste.actif = true;
			clicABloquer = true;
			document.body.classList.add("planning-sort-active");
			geste.source.classList.add("planning-dragging");

			apercu = document.createElement("div");
			apercu.className = "planning-centre-drag-preview";
			const nom = geste.source.querySelector(".calendar-site-title, h2, h3")?.textContent?.trim();
			apercu.textContent = nom || "Déplacer ce lieu";
			document.body.appendChild(apercu);
			placerApercu(x, y);
		}

		function nettoyerGeste()
		{
			retirerCible();
			geste?.source?.classList.remove("planning-dragging");
			apercu?.remove();
			apercu = null;
			document.body.classList.remove("planning-sort-active");
			geste = null;
		}

		async function terminerDrag(event)
		{
			if (!geste) return;
			const etat = geste;
			if (etat.actif)
			{
				const cibleFinale = cibleVisuelle(event.clientX, event.clientY) || cible;
				const ordre = etat.ordre.slice();
				const indexSource = ordre.indexOf(etat.source);
				const indexCible = ordre.indexOf(cibleFinale);

				nettoyerGeste();
				if (indexSource >= 0 && indexCible >= 0 && indexSource !== indexCible)
				{
					[ordre[indexSource], ordre[indexCible]] = [ordre[indexCible], ordre[indexSource]];
					ordre.forEach((lieu) => calendarsContainer.appendChild(lieu));
					await enregistrerOrdrePlanning("centre", calendarsContainer, ".centre-planning-group", "centreId");
				}
			}
			else
			{
				nettoyerGeste();
			}
		}

		calendarsContainer.addEventListener("pointerdown", (event) =>
		{
			const poignee = event.target.closest(".centre-drag-handle");
			if (!poignee || event.button !== 0) return;
			const source = poignee.closest(".centre-planning-group");
			if (!source) return;

			event.preventDefault();
			geste = {
				pointerId: event.pointerId,
				source,
				ordre: cartes(),
				departX: event.clientX,
				departY: event.clientY,
				actif: false,
			};
			poignee.setPointerCapture?.(event.pointerId);
		}, { signal });

		document.addEventListener("pointermove", (event) =>
		{
			if (!geste || event.pointerId !== geste.pointerId) return;
			const distance = Math.hypot(event.clientX - geste.departX, event.clientY - geste.departY);
			if (!geste.actif && distance >= 5) demarrerDrag(event.clientX, event.clientY);
			if (!geste.actif) return;

			event.preventDefault();
			placerApercu(event.clientX, event.clientY);
			definirCible(cibleVisuelle(event.clientX, event.clientY));
		}, { signal, capture: true });

		document.addEventListener("pointerup", (event) =>
		{
			if (!geste || event.pointerId !== geste.pointerId) return;
			terminerDrag(event);
		}, { signal, capture: true });

		document.addEventListener("pointercancel", (event) =>
		{
			if (!geste || event.pointerId !== geste.pointerId) return;
			nettoyerGeste();
		}, { signal, capture: true });

		// Le pointerup d'un vrai drag ne doit pas déclencher le bouton voisin ni
		// replier le lieu lorsque le navigateur synthétise ensuite un clic.
		calendarsContainer.addEventListener("click", (event) =>
		{
			if (!clicABloquer) return;
			clicABloquer = false;
			event.preventDefault();
			event.stopImmediatePropagation();
		}, { signal, capture: true });

		detruireTriCentres = () =>
		{
			controleur.abort();
			nettoyerGeste();
		};
	}

	function installerTriEvenements(zoneEvenements, centre)
	{
		if (typeof Sortable === "undefined") return;
		const sortable = Sortable.create(zoneEvenements, {
			...optionsTriCommun(),
			draggable: ".evenement-calendar-card",
			direction: "vertical",
			swapThreshold: 0.65,
			group: { name: `groupes-centre-${centre.id}`, pull: false, put: false },
			onEnd: async (event) =>
			{
				document.body.classList.remove("planning-sort-active");
				if (event.oldIndex === event.newIndex) return;
				await enregistrerOrdrePlanning("evenement", zoneEvenements, ".evenement-calendar-card", "evenementId", centre.id);
			},
		});
		sortablesGroupes.push(sortable);
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

	function evenementOuvertCeJour(groupe, dateStr)
	{
		if (!groupe || !dateStr) return false;
		const periodes = Array.isArray(groupe.periodes) ? groupe.periodes : [];
		if (!periodes.some((periode) => dateStr >= periode.debut && dateStr <= (periode.fin_ouverture || periode.fin))) return false;
		const joursOuverts = Array.isArray(groupe.jours_ouverts)
			? groupe.jours_ouverts.map(Number)
			: [0, 1, 2, 3, 4, 5];
		if (!joursOuverts.includes(numeroJourSemaine(dateStr))) return false;
		if ((groupe.dates_exclues || []).includes(dateStr)) return false;
		if ((groupe.dates_feriees_fermees || []).includes(dateStr)) return false;
		return true;
	}

	function groupeOuvertSurPlage(groupe, debutStr, finExclusiveStr)
	{
		if (!groupe || !debutStr || !finExclusiveStr) return false;

		// Une période qui chevauche la semaine ne suffit pas : le groupe peut
		// être fermé chaque jour (dates exclues, jours habituels ou fériés).
		// On ne l'affiche que si au moins une date est réellement ouverte.
		let jour = debutStr;
		while (jour < finExclusiveStr)
		{
			if (evenementOuvertCeJour(groupe, jour)) return true;
			jour = addDays(jour, 1);
		}
		return false;
	}

	function joursCachesFullCalendar(groupe)
	{
		const ouverts = new Set((groupe.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number));
		return [0, 1, 2, 3, 4, 5, 6].filter((jourJs) => {
			const jourPython = (jourJs + 6) % 7;
			return !ouverts.has(jourPython);
		});
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

	function surlignerAnimateursDisponibles(dateStr)
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

		surlignerAnimateursDisponibles(info.dateStr);
		afficherToast(`Choisis un animateur pour ${centre.nom} — ${evenement.nom}, le ${libelleDate(info.dateStr)}.`);
	}

	function creerAffectationDepuisJour(animateur, centre, evenement, calendar, debut)
	{
		if (!evenementOuvertCeJour(evenement, debut))
		{
			return Promise.reject({ error: "Ce jour est en dehors des périodes du groupe." });
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
			rafraichirAffectationsVisibles(calendar);
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

	function rafraichirAffectationsVisibles(calendarCible = null)
	{
		// Une affectation manuelle ne concerne qu'un groupe. FullCalendar garde
		// alors les événements actuellement visibles pendant la requête et les
		// remplace à réception : aucun écran vide ni clignotement.
		if (calendarCible)
		{
			calendarCible.refetchEvents();
			return;
		}

		// Les actions globales (remplissage automatique, etc.) peuvent modifier
		// plusieurs groupes : elles seules rechargent tous les calendriers.
		calendars.forEach((calendar) => calendar.refetchEvents());
	}

	// -----------------------------------------------------------------
	// Calendriers (un par centre)
	// -----------------------------------------------------------------

	// Appelée quand on déplace ou redimensionne une affectation existante
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
			// Le déplacement est déjà appliqué par FullCalendar. On évite un
			// rechargement visuel complet ; la réponse serveur suffit.
			return data;
		}).catch((err) =>
		{
			afficherToast(erreurMessage(err, "La mise à jour n'a pas pu être enregistrée."), true);
			if (typeof info.revert === "function") info.revert();
			throw err;
		});
	}

	// Une instance FullCalendar par groupe. Tous les groupes d'un même
	// centre restent regroupés visuellement dans le même bloc.
	function mettreAJourVisibiliteCalendriers(info)
	{
		if (!info) return;
		const debut = formatDateLocal(info.start);
		const fin = formatDateLocal(info.end);

		document.querySelectorAll(".evenement-calendar-card").forEach((card) => {
			const groupe = centresPlanning.flatMap((centre) => centre.evenements || [])
				.find((item) => Number(item.id) === Number(card.dataset.evenementId));
			card.hidden = !groupe || !groupeOuvertSurPlage(groupe, debut, fin);
		});

		document.querySelectorAll(".centre-planning-group").forEach((bloc) => {
			const cartes = Array.from(bloc.querySelectorAll(".evenement-calendar-card"));
			const visibles = cartes.filter((card) => !card.hidden);
			const aucunGroupeVisible = visibles.length === 0;

			// Comme sur l'accueil, le lieu reste toujours visible. Seuls les
			// groupes fermés pour toute la semaine sont retirés de l'affichage.
			bloc.hidden = false;

			const compteur = bloc.querySelector(".centre-evenements-count");
			if (compteur)
			{
				compteur.textContent = visibles.length
					? `${visibles.length} groupe${visibles.length > 1 ? "s" : ""}`
					: "Aucun groupe";
			}

			const etatVide = bloc.querySelector(".calendar-site-empty");
			if (etatVide) etatVide.hidden = !aucunGroupeVisible;

			if (!aucunGroupeVisible && !bloc.classList.contains("collapsed"))
			{
				window.setTimeout(() => {
					visibles.forEach((card) => {
						const calendar = calendars.find((item) =>
							Number(item.evenementPlanning?.id) === Number(card.dataset.evenementId)
						);
						calendar?.updateSize();
					});
				}, 20);
			}
		});
	}

	function libelleJourEffectif(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "2-digit" });
	}

	function compterAnimateursAffectes(calendar, dateStr)
	{
		const ids = new Set();
		calendar.getEvents().forEach((event) =>
		{
			if (event.display === "background") return;
			const animateurId = idAnimateurDepuisEvent(event);
			if (!animateurId || !event.start) return;
			const debut = formatDateLocal(event.start);
			const fin = event.end ? formatDateLocal(event.end) : addDays(debut, 1);
			if (debut <= dateStr && dateStr < fin) ids.add(Number(animateurId));
		});
		return ids.size;
	}

	function normaliserEffectifJour(valeur, ratioDefaut = 8)
	{
		const ratio = Math.max(1, Number(ratioDefaut || 8));
		if (typeof valeur === "number")
		{
			return { nombre: valeur, enfantsParAnimateur: ratio };
		}
		return {
			nombre: Number(valeur?.nombre || 0),
			enfantsParAnimateur: Math.max(1, Number(valeur?.enfantsParAnimateur || valeur?.enfants_par_animateur || ratio)),
		};
	}

	function afficherEffectifsEnfantsDansCalendrier(calendar)
	{
		const valeurs = calendar.evenementPlanning.effectifsEnfants || {};
		calendar.el.querySelectorAll(".fc-daygrid-day").forEach((cellule) =>
		{
			const dateStr = cellule.dataset.date;
			const cadre = cellule.querySelector(".fc-daygrid-day-frame");
			if (!cadre || !dateStr) return;

			cadre.querySelector(".planning-effectif-enfants-zone")?.remove();
			const valeur = normaliserEffectifJour(valeurs[dateStr], calendar.evenementPlanning.enfants_par_animateur_defaut);
			if (!valeur.nombre) return;

			const animateursAffectes = compterAnimateursAffectes(calendar, dateStr);
			const animateursNecessaires = Math.ceil(valeur.nombre / valeur.enfantsParAnimateur);
			let etat = "ok";
			if (animateursAffectes < animateursNecessaires) etat = "manque";
			else if (animateursAffectes > animateursNecessaires) etat = "surplus";

			const zone = document.createElement("div");
			zone.className = "planning-effectif-enfants-zone";
			const badge = document.createElement("span");
			badge.className = `planning-effectif-enfants planning-effectif-enfants--${etat}`;
			badge.innerHTML = `<strong>${valeur.nombre} enfant${valeur.nombre > 1 ? "s" : ""}</strong><small>${animateursAffectes}/${animateursNecessaires} anim.</small>`;
			badge.title = `${valeur.nombre} enfant${valeur.nombre > 1 ? "s" : ""} — ratio 1 animateur pour ${valeur.enfantsParAnimateur} enfants — ${animateursAffectes} animateur${animateursAffectes > 1 ? "s" : ""} affecté${animateursAffectes > 1 ? "s" : ""}, ${animateursNecessaires} nécessaire${animateursNecessaires > 1 ? "s" : ""}`;
			zone.appendChild(badge);

			const evenements = cadre.querySelector(".fc-daygrid-day-events");
			if (evenements) cadre.insertBefore(zone, evenements);
			else cadre.appendChild(zone);
		});
	}

	function rafraichirAffichageEffectifsEnfants(calendar)
	{
		// FullCalendar peut terminer un rendu juste après l'enregistrement.
		// Deux frames garantissent que les cellules définitives sont présentes.
		requestAnimationFrame(() => requestAnimationFrame(() =>
		{
			afficherEffectifsEnfantsDansCalendrier(calendar);
			calendar.updateSize();
		}));
	}

	async function chargerEffectifsEnfants(calendar, info = null)
	{
		const vue = info || calendar.view;
		if (!calendar?.evenementPlanning?.id || !vue?.activeStart || !vue?.activeEnd) return;
		const debut = formatDateLocal(vue.activeStart);
		const fin = formatDateLocal(vue.activeEnd);
		const plageDemandee = `${debut}|${fin}`;
		const numeroRequete = (calendar.effectifsEnfantsRequete || 0) + 1;
		calendar.effectifsEnfantsRequete = numeroRequete;

		try
		{
			const lignes = await apiFetch(
				`/api/groupes/${calendar.evenementPlanning.id}/effectifs-enfants/?debut=${debut}&fin=${fin}`,
				{ cache: "no-store" }
			);

			// Une navigation rapide peut laisser revenir une ancienne requête après
			// la nouvelle. Elle ne doit jamais écraser la semaine actuellement visible.
			const vueCourante = calendar.view;
			const plageCourante = vueCourante?.activeStart && vueCourante?.activeEnd
				? `${formatDateLocal(vueCourante.activeStart)}|${formatDateLocal(vueCourante.activeEnd)}`
				: "";
			if (calendar.effectifsEnfantsRequete !== numeroRequete || plageCourante !== plageDemandee) return;

			calendar.evenementPlanning.effectifsEnfants = Object.fromEntries(
				(lignes || []).map((ligne) => [
					ligne.date,
					{ nombre: ligne.nombre, enfantsParAnimateur: ligne.enfants_par_animateur || 8 },
				])
			);
			calendar.effectifsEnfantsPlageChargee = plageDemandee;
			rafraichirAffichageEffectifsEnfants(calendar);
		}
		catch (err)
		{
			if (calendar.effectifsEnfantsRequete === numeroRequete)
			{
				afficherToast(erreurMessage(err, "Les effectifs enfants n'ont pas pu être chargés."), true);
			}
		}
	}

	function ouvrirSaisieEffectifsEnfants(calendar)
	{
		const evenement = calendar.evenementPlanning;
		const debut = calendar.view.activeStart;
		const fin = calendar.view.activeEnd;
		const valeurs = evenement.effectifsEnfants || {};
		const jours = [];
		for (let curseur = new Date(debut); curseur < fin; curseur = new Date(curseur.getFullYear(), curseur.getMonth(), curseur.getDate() + 1))
		{
			const dateStr = formatDateLocal(curseur);
			if (evenementOuvertCeJour(evenement, dateStr)) jours.push(dateStr);
		}
		contexteEffectifsEnfants = { calendar, evenement, jours };
		titreEffectifsEnfants.textContent = `Effectifs enfants — ${evenement.nom}`;
		champsEffectifsEnfants.innerHTML = jours.map((dateStr) =>
		{
			const valeur = normaliserEffectifJour(valeurs[dateStr], calendar.evenementPlanning.enfants_par_animateur_defaut);
			return `
				<div class="effectif-enfants-row">
					<span>${escapeHtml(libelleJourEffectif(dateStr))}</span>
					<label><small>Enfants</small><input type="number" min="0" max="999" step="1" inputmode="numeric" data-date="${dateStr}" data-field="nombre" value="${valeur.nombre || ""}" placeholder="0"></label>
					<label><small>Enfants / anim.</small><input type="number" min="1" max="999" step="1" inputmode="numeric" data-date="${dateStr}" data-field="ratio" value="${valeur.enfantsParAnimateur}" placeholder="8"></label>
				</div>`;
		}).join("") || '<p class="empty-note">Ce groupe n’est ouvert aucun jour cette semaine.</p>';
		ouvrirModal(modalEffectifsEnfants);
	}

	formulaireEffectifsEnfants?.addEventListener("submit", async (event) =>
	{
		event.preventDefault();
		if (!contexteEffectifsEnfants) return;
		const effectifs = Array.from(champsEffectifsEnfants.querySelectorAll('input[data-field="nombre"]')).map((input) =>
		{
			const date = input.dataset.date;
			const ratioInput = champsEffectifsEnfants.querySelector(`input[data-date="${date}"][data-field="ratio"]`);
			return {
				date,
				nombre: Number.parseInt(input.value || "0", 10) || 0,
				enfants_par_animateur: Math.max(1, Number.parseInt(ratioInput?.value || String(contexteEffectifsEnfants.evenement.enfants_par_animateur_defaut || 8), 10) || 8),
			};
		});
		try
		{
			await apiFetch(`/api/groupes/${contexteEffectifsEnfants.evenement.id}/effectifs-enfants/`, {
				method: "POST", body: JSON.stringify({ effectifs }),
			});
			const calendarEnregistre = contexteEffectifsEnfants.calendar;
			contexteEffectifsEnfants.evenement.effectifsEnfants = Object.fromEntries(
				effectifs
					.filter((item) => item.nombre > 0)
					.map((item) => [item.date, { nombre: item.nombre, enfantsParAnimateur: item.enfants_par_animateur }])
			);
			// Affichage immédiat, puis relecture de la base : l'utilisateur voit le
			// résultat sans attendre et le cache local ne peut pas masquer un échec.
			rafraichirAffichageEffectifsEnfants(calendarEnregistre);
			fermerModal(modalEffectifsEnfants);
			afficherToast("Effectifs enfants enregistrés.");
			await chargerEffectifsEnfants(calendarEnregistre);
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "Les effectifs enfants n'ont pas pu être enregistrés."), true);
		}
	});

	function creerCalendar(centre, evenement, card)
	{
		const calendarEl = card.querySelector(".calendar");

		const calendar = new FullCalendar.Calendar(calendarEl,
		{
			initialView: "dayGridWeek",
			height: "auto",
			locale: "fr",
			firstDay: 1,
			hiddenDays: joursCachesFullCalendar(evenement),
			editable: true,
			droppable: true,
			selectable: true,

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
				arg.el.dataset.date = dateStr;
				if (!evenementOuvertCeJour(evenement, dateStr))
				{
					arg.el.setAttribute("aria-disabled", "true");
					arg.el.title = "Groupe fermé à cette date (hors période, jour habituel non ouvert ou date exclue)";
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

			eventsSet: function ()
			{
				rafraichirAffichageEffectifsEnfants(calendar);
			},

			datesSet: function (info)
			{
				mettreAJourLibelleSemaine(info);
				mettreAJourVisibiliteCalendriers(info);
				chargerEffectifsEnfants(info.view.calendar, info);
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
					// Le badge déposé est un événement temporaire sans identifiant.
					// On le retire puis on recharge seulement ce groupe.
					info.event.remove();
					rafraichirAffectationsVisibles(calendar);
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
		evenement.effectifsEnfants = evenement.effectifsEnfants || {};
		calendar.evenementPlanning = evenement;
		calendar.render();

		// datesSet est normalement déclenché par render(), mais ce chargement
		// explicite couvre aussi les rendus initiaux différés/masqués de FullCalendar.
		window.setTimeout(() => chargerEffectifsEnfants(calendar), 0);
		return calendar;
	}

	function ajouterCentreAuPlanning(centre)
	{
		const evenements = (centre.evenements || []).filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0);

		const groupe = document.createElement("section");
		groupe.classList.add("centre-planning-group", "calendar-site-card");
		groupe.dataset.centreId = centre.id;
		groupe.style.setProperty("--centre-color", centre.couleur);
		groupe.innerHTML = `
			<header class="centre-planning-header calendar-site-header">
				<div class="centre-planning-title calendar-site-title">
					<span class="planning-drag-handle centre-drag-handle" role="button" tabindex="0" aria-label="Déplacer le planning du centre ${escapeHtml(centre.nom)}" title="Glisser pour déplacer ce centre">⠿</span>
					<div>
						<span class="centre-planning-code calendar-site-code">${escapeHtml(centre.code || "")}</span>
						<h2 class="calendar-site-name">${escapeHtml(centre.nom)}</h2>
					</div>
				</div>
				<div class="centre-planning-actions calendar-site-actions">
					<span class="centre-evenements-count calendar-site-count">${evenements.length} groupe${evenements.length > 1 ? "s" : ""}</span>
					<button class="centre-collapse-toggle" type="button" aria-expanded="true" aria-label="Replier ce lieu" title="Replier ou déplier ce lieu">
						<span aria-hidden="true">⌄</span>
					</button>
				</div>
			</header>
			<div class="evenement-calendars calendar-group-list"></div>
			<p class="calendar-site-empty" ${evenements.length ? "hidden" : ""}>Aucun groupe ouvert cette semaine.</p>`;

		calendarsContainer.appendChild(groupe);
		attacherSurvolCentre(groupe, centre.id);

		const boutonRepli = groupe.querySelector(".centre-collapse-toggle");
		boutonRepli.addEventListener("click", () =>
		{
			reglerCentreReplie(groupe, centre.id, !groupe.classList.contains("collapsed"));
		});

		const zoneEvenements = groupe.querySelector(".evenement-calendars");

		evenements.forEach((evenement) =>
		{
			const card = document.createElement("article");
			card.classList.add("calendar-card", "evenement-calendar-card", "calendar-group-card");
			card.dataset.centreId = centre.id;
			card.dataset.evenementId = evenement.id;
			card.style.setProperty("--centre-color", centre.couleur);

			card.innerHTML = `
				<header class="evenement-calendar-header calendar-group-header">
					<div class="evenement-calendar-title calendar-group-title">
						<span class="planning-drag-handle evenement-drag-handle" role="button" tabindex="0" aria-label="Déplacer le planning ${escapeHtml(evenement.nom)}" title="Glisser pour déplacer ce groupe">⠿</span>
						<div>
							<h3 class="calendar-group-name">${escapeHtml(evenement.nom)}</h3>
						</div>
					</div>
					<div class="evenement-calendar-meta calendar-group-meta">
						<span>Objectif ${escapeHtml(evenement.effectif_cible)}</span>
						<button class="btn btn-secondary btn-effectifs-enfants" type="button" title="Renseigner le nombre d’enfants pour cette semaine">Effectifs enfants</button>
					</div>
				</header>
				<div class="calendar shared-calendar"></div>`;

			zoneEvenements.appendChild(card);
			const calendar = creerCalendar(centre, evenement, card);
			card.querySelector(".btn-effectifs-enfants").addEventListener("click", () => ouvrirSaisieEffectifsEnfants(calendar));
			calendars.push(calendar);
		});

		installerTriEvenements(zoneEvenements, centre);

		if (centresReplies.has(Number(centre.id)))
		{
			reglerCentreReplie(groupe, centre.id, true);
		}
	}

	let rafMiseAJourCalendriers = null;

	function mettreAJourDimensionsCalendriers()
	{
		if (rafMiseAJourCalendriers) cancelAnimationFrame(rafMiseAJourCalendriers);
		rafMiseAJourCalendriers = requestAnimationFrame(() =>
		{
			rafMiseAJourCalendriers = requestAnimationFrame(() =>
			{
				calendars.forEach((calendar) => calendar.updateSize());
				rafMiseAJourCalendriers = null;
			});
		});
	}

	function chargerCentres()
	{
		return apiFetch("/api/centres/")
			.then((centres) => Promise.all(centres.map((centre) =>
				apiFetch(`/api/centres/${centre.id}/groupes/`)
					.then((evenements) => ({
						...centre,
						evenements: (evenements || []).map((evenement) => ({
							...evenement,
							effectifsEnfants: Object.fromEntries(
								(evenement.effectifs_enfants || []).map((ligne) => [
									ligne.date,
									{ nombre: ligne.nombre, enfantsParAnimateur: ligne.enfants_par_animateur || 8 },
								])
							),
						})),
					}))
			)))
			.then((centres) =>
			{
				centresPlanning = centres;
				centresFiltresCharges = true;
				rafraichirFiltresAnimateurs(false);
				calendars.splice(0).forEach((calendar) => calendar.destroy());
				sortablesGroupes.splice(0).forEach((sortable) => sortable.destroy());
				calendarsContainer.innerHTML = "";

				if (centres.length === 0)
				{
					calendarsContainer.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant. Ajoute-en un depuis Gestion.</p>';
					return;
				}

				centres.forEach((centre) => ajouterCentreAuPlanning(centre));
				installerTriCentres();
				mettreAJourDimensionsCalendriers();
				if (!calendars.length)
				{
					// Les lieux restent visibles même lorsqu’aucun groupe n’a de période.
					return;
				}
				const periodes = periodesOuvertesPlanning();
				if (calendars.length && periodes.length)
				{
					const aujourdHui = formatDateLocal(new Date());
					const ouverte = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
					const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
					// Quand une période est ouverte aujourd’hui, rester sur la semaine
					// actuelle. Aller à periode.debut ramenait systématiquement au premier
					// jour des vacances après un rechargement, ce qui faisait croire que
					// les effectifs saisis sur une autre semaine avaient disparu.
					allerDateTous(ouverte ? aujourdHui : (prochaine || periodes[0]).debut);
				}

				// Le gotoDate initial relance datesSet sur chaque calendrier. Une dernière
				// relecture après stabilisation garantit que les badges persistants sont
				// présents dès l'arrivée sur le Planning, y compris après un refresh.
				window.setTimeout(() => {
					calendars.forEach((calendar) => chargerEffectifsEnfants(calendar));
				}, 50);
			});
	}

	// -----------------------------------------------------------------
	// Barre d'outils commune : navigation, vue, actions groupées.
	// Les 3 calendriers sont toujours pilotés EN MÊME TEMPS, en itérant
	// simplement sur le tableau `calendars`.
	// -----------------------------------------------------------------

	function periodesOuvertesPlanning()
	{
		const uniques = new Map();
		centresPlanning.flatMap((centre) => centre.evenements || []).forEach((groupe) =>
			(groupe.periodes || []).forEach((periode) =>
			{
				const cle = periode.id || `${periode.debut}|${periode.fin}`;
				const finOuverture = periode.fin_ouverture || periode.fin;
				const existante = uniques.get(cle);
				if (!existante)
				{
					uniques.set(cle, { ...periode, fin_periode: periode.fin, fin: finOuverture });
				}
				else if (finOuverture > existante.fin)
				{
					existante.fin = finOuverture;
				}
			})
		);
		return [...uniques.values()].sort((a, b) => a.debut.localeCompare(b.debut));
	}

	function periodePourDate(dateStr)
	{
		return periodesOuvertesPlanning().find((periode) => periode.debut <= dateStr && periode.fin >= dateStr) || null;
	}

	function mettreAJourLibelleSemaine(info = null)
	{
		const dateReference = datePeriodeCourante
			|| (info?.start ? formatDateLocal(info.start) : null)
			|| (calendars[0] ? formatDateLocal(calendars[0].getDate()) : null);
		WeekPicker.get("planning-period-nav")?.setActiveDate(dateReference);
		if (!toolbarLabel) return;
		const periode = dateReference ? periodePourDate(dateReference) : null;
		toolbarLabel.textContent = periode
			? libellePeriodeAvecDates(periode)
			: "Aucune période ouverte";
	}

	function allerDateTous(dateStr)
	{
		datePeriodeCourante = dateStr;
		calendars.forEach((calendar) => calendar.gotoDate(dateStr));
		mettreAJourLibelleSemaine();
	}

	function naviguerVersPeriode(direction)
	{
		const periodes = periodesOuvertesPlanning();
		if (!periodes.length || !calendars.length) return;
		const dateCourante = datePeriodeCourante || formatDateLocal(calendars[0].getDate());
		const cible = direction > 0
			? periodes.find((periode) => periode.debut > dateCourante)
			: [...periodes].reverse().find((periode) => periode.debut < dateCourante);
		if (cible) allerDateTous(cible.debut);
	}

	document.getElementById("planning-period-nav")?.addEventListener("week-picker:select", (event) => { if (event.detail?.date) allerDateTous(event.detail.date); });
	document.getElementById("btn-prev").addEventListener("click", () => naviguerVersPeriode(-1));
	document.getElementById("btn-next").addEventListener("click", () => naviguerVersPeriode(1));
	document.getElementById("btn-today").addEventListener("click", () => {
		const aujourdHui = formatDateLocal(new Date());
		const periodes = periodesOuvertesPlanning();
		const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
		const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
		const cible = courante?.debut || prochaine?.debut || periodes.at(-1)?.debut;
		if (cible) allerDateTous(cible);
	});

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
					// refetchEvents() recharge les groupes venus de l'API,
					// mais ne supprime pas toujours les groupes ajoutés
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
		// On écoute plusieurs signaux car FullCalendar peut initier le
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

		function animateurCorrespondAuxFiltres(animateur)
	{
		const qualificationsAnimateur = new Set((animateur.qualification_ids || []).map(Number));
		const possedeToutesLesQualifications = [...filtresQualificationsAnimateurs]
			.every((qualificationId) => qualificationsAnimateur.has(qualificationId));
		if (!possedeToutesLesQualifications) return false;

		if (filtresCentresAnimateurs.size > 0)
		{
			const centrePrefereId = Number(animateur.centre_prefere?.id);
			if (!filtresCentresAnimateurs.has(centrePrefereId)) return false;
		}
		const lundi = lundiDeLaSemaine(datePeriodeCourante || new Date());
		const debut = formatDateLocal(lundi);
		const finDate = new Date(lundi);
		finDate.setDate(lundi.getDate() + 4);
		const fin = formatDateLocal(finDate);
		const chevauche = (plage, finExclusive = false) => plage && String(plage.debut || "") <= fin && (finExclusive ? String(plage.fin || "") > debut : String(plage.fin || "") >= debut);
		const disponible = (animateur.disponibilites || []).some((plage) => chevauche(plage));
		const affecte = (animateur.affectations || []).some((plage) => chevauche(plage, true));
		if (filtreDisponibiliteAnimateursValeur === "disponible" && !disponible) return false;
		if (filtreDisponibiliteAnimateursValeur === "indisponible" && disponible) return false;
		if (filtreAffectationAnimateursValeur === "affecte" && !affecte) return false;
		if (filtreAffectationAnimateursValeur === "non-affecte" && affecte) return false;
		return true;
	}

	function sauvegarderFiltresAnimateurs()
	{
		localStorage.setItem("planning-filtres-qualifications", JSON.stringify([...filtresQualificationsAnimateurs]));
		localStorage.setItem("planning-filtres-centres-preferes", JSON.stringify([...filtresCentresAnimateurs]));
	}

	function nombreFiltresAnimateursActifs()
	{
		return filtresQualificationsAnimateurs.size + filtresCentresAnimateurs.size + (filtreDisponibiliteAnimateursValeur ? 1 : 0) + (filtreAffectationAnimateursValeur ? 1 : 0);
	}

	function mettreAJourResumeFiltresAnimateurs(_nombreAffiche)
	{
		const nombreActifs = nombreFiltresAnimateursActifs();
		StaffFilterUI.updateCount(compteurFiltresAnimateurs, nombreActifs);
	}

	function rafraichirFiltresAnimateurs(rendreListe = true)
	{
		if (qualificationsFiltresChargees)
		{
			const idsExistants = new Set(qualificationsPlanning.map((qualification) => Number(qualification.id)));
			filtresQualificationsAnimateurs = new Set(
				[...filtresQualificationsAnimateurs].filter((id) => idsExistants.has(id))
			);
			StaffFilterUI.renderOptions(filtresQualificationsConteneur, qualificationsPlanning, {
				selected: filtresQualificationsAnimateurs,
				emptyText: "Aucune qualification",
				name: "planning_filter_qualification",
				onChange: (input) =>
				{
					const id = Number(input.value);
					if (input.checked) filtresQualificationsAnimateurs.add(id);
					else filtresQualificationsAnimateurs.delete(id);
					sauvegarderFiltresAnimateurs();
					rendreListeAnimateurs();
				},
			});
		}

		if (centresFiltresCharges)
		{
			const idsExistants = new Set(centresPlanning.map((centre) => Number(centre.id)));
			filtresCentresAnimateurs = new Set(
				[...filtresCentresAnimateurs].filter((id) => idsExistants.has(id))
			);
			StaffFilterUI.renderOptions(filtresCentresConteneur, centresPlanning, {
				selected: filtresCentresAnimateurs,
				emptyText: "Aucun lieu",
				name: "planning_filter_centre",
				onChange: (input) =>
				{
					const id = Number(input.value);
					if (input.checked) filtresCentresAnimateurs.add(id);
					else filtresCentresAnimateurs.delete(id);
					sauvegarderFiltresAnimateurs();
					rendreListeAnimateurs();
				},
			});
		}

		sauvegarderFiltresAnimateurs();
		if (rendreListe) rendreListeAnimateurs();
	}

	function animateurCorrespondARecherche(animateur)
	{
		if (!rechercheAnimateurs) return true;
		const texte = [animateur.prenom, animateur.nom, animateur.email, animateur.telephone]
			.filter(Boolean)
			.join(" ")
			.toLocaleLowerCase("fr");
		return texte.includes(rechercheAnimateurs);
	}

	function animateursFiltresEtTries()
	{
		return animateursPlanning
			.filter(animateurCorrespondAuxFiltres)
			.filter(animateurCorrespondARecherche)
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
		}

		animateursAffiches.forEach((animateur) =>
		{
			const chip = creerChipAnimateur(animateur);
			if (animateurActif && animateurActif.id === animateur.id)
			{
				animateurActif = animateur;
				chip.classList.add("selected");
			}
			animList.appendChild(chip);
		});

		if (animateursAffiches.length === 0)
		{
			animList.innerHTML = '<p class="empty-note">Aucun salarié ne correspond aux filtres cochés.</p>';
		}
		mettreAJourResumeFiltresAnimateurs(animateursAffiches.length);
		if (compteurAnimateursVisibles)
		{
			compteurAnimateursVisibles.textContent = `${animateursAffiches.length}/${animateursPlanning.length}`;
		}
	}

	if (rechercheAnimateursInput)
	{
		rechercheAnimateursInput.addEventListener("input", () =>
		{
			rechercheAnimateurs = rechercheAnimateursInput.value.trim().toLocaleLowerCase("fr");
			rendreListeAnimateurs();
		});
	}

	function initialiserRedimensionnementSidebar()
	{
		if (!redimensionneurSidebar) return;
		const cle = "planning-largeur-sidebar";
		const largeurSauvegardee = Number(localStorage.getItem(cle));
		if (Number.isFinite(largeurSauvegardee) && largeurSauvegardee >= 220 && largeurSauvegardee <= 450)
		{
			document.body.style.setProperty("--planning-sidebar-width", `${largeurSauvegardee}px`);
		}

		let enCours = false;
		const reglerLargeur = (clientX) =>
		{
			const layout = document.getElementById("layout");
			if (!layout) return;
			const largeur = Math.min(450, Math.max(220, Math.round(clientX - layout.getBoundingClientRect().left)));
			document.body.style.setProperty("--planning-sidebar-width", `${largeur}px`);
			localStorage.setItem(cle, String(largeur));
			calendars.forEach((calendar) => calendar.updateSize());
		};

		redimensionneurSidebar.addEventListener("pointerdown", (event) =>
		{
			if (window.innerWidth < 1024) return;
			enCours = true;
			redimensionneurSidebar.setPointerCapture(event.pointerId);
			redimensionneurSidebar.classList.add("is-resizing");
			document.body.classList.add("planning-sidebar-resizing");
		});

		redimensionneurSidebar.addEventListener("pointermove", (event) =>
		{
			if (enCours) reglerLargeur(event.clientX);
		});

		const terminer = (event) =>
		{
			if (!enCours) return;
			enCours = false;
			if (redimensionneurSidebar.hasPointerCapture(event.pointerId))
			{
				redimensionneurSidebar.releasePointerCapture(event.pointerId);
			}
			redimensionneurSidebar.classList.remove("is-resizing");
			document.body.classList.remove("planning-sidebar-resizing");
		};
		redimensionneurSidebar.addEventListener("pointerup", terminer);
		redimensionneurSidebar.addEventListener("pointercancel", terminer);
	}

	initialiserRedimensionnementSidebar();

	// (Re)charge la liste des animateurs dans la barre latérale. Appelée
	// au chargement initial, et à nouveau après un ajout/suppression.
	function chargerAnimateurs()
	{
		return apiFetch("/api/animateurs/?include_affectations=1").then((animateurs) =>
		{
			animateursPlanning = animateurs;
		});
	}

	function chargerQualificationsFiltres()
	{
		return apiFetch("/api/qualifications/")
			.then((qualifications) =>
			{
				qualificationsPlanning = qualifications;
				qualificationsFiltresChargees = true;
				rafraichirFiltresAnimateurs(false);
			})
			.catch(() =>
			{
				qualificationsPlanning = [];
				qualificationsFiltresChargees = true;
				rafraichirFiltresAnimateurs(false);
			});
	}

	[filtreDisponibiliteAnimateurs, filtreAffectationAnimateurs].forEach((select) => select?.addEventListener("change", () =>
	{
		filtreDisponibiliteAnimateursValeur = filtreDisponibiliteAnimateurs?.value || "";
		filtreAffectationAnimateursValeur = filtreAffectationAnimateurs?.value || "";
		rendreListeAnimateurs();
	}));

	if (boutonEffacerFiltresAnimateurs)
	{
		boutonEffacerFiltresAnimateurs.addEventListener("click", () =>
		{
			filtresQualificationsAnimateurs.clear();
			filtresCentresAnimateurs.clear();
			filtreDisponibiliteAnimateursValeur = "";
			filtreAffectationAnimateursValeur = "";
			if (filtreDisponibiliteAnimateurs) filtreDisponibiliteAnimateurs.value = "";
			if (filtreAffectationAnimateurs) filtreAffectationAnimateurs.value = "";
			sauvegarderFiltresAnimateurs();
			rafraichirFiltresAnimateurs();
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

			// FullCalendar affiche les éléments "display: background" comme
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

		apiFetch(`/api/animateurs/${animateur.id}/disponibilites/`)
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

		// Un second clic sur le même animateur = désélectionner et s'arrêter là.
		if (dejaSelectionne) return;

		chip.classList.add("selected");
		animateurActif = animateur;
		afficherToast(`${animateur.prenom} sélectionné : clique sur un jour pour l'affecter.`);

		// Affiche immédiatement ses jours disponibles : vert sur son premier
		// centre autorisé, orange sur les autres centres autorisés et rouge sur
		// les centres non autorisés.
		apiFetch(`/api/animateurs/${animateur.id}/disponibilites/`)
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

	// Les trois sources arrivaient séparément et reconstruisaient plusieurs
	// fois la liste des salariés, ce qui créait le petit « clip » visible au
	// chargement. On attend maintenant toutes les données puis on rend une fois.
	if (typeof ResizeObserver !== "undefined")
	{
		const observateurCalendriers = new ResizeObserver(() => mettreAJourDimensionsCalendriers());
		observateurCalendriers.observe(calendarsContainer);
	}
	window.addEventListener("resize", mettreAJourDimensionsCalendriers, { passive: true });

	Promise.all([
		chargerCentres(),
		chargerQualificationsFiltres(),
		chargerAnimateurs(),
	]).then(() =>
	{
		rafraichirFiltresAnimateurs(false);
		rendreListeAnimateurs();
	}).catch((err) =>
	{
		afficherToast(erreurMessage(err, "Le planning n'a pas pu être chargé complètement."), true);
	});

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
	// désormais calculé groupe par groupe.
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
				.filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0)
				.map((groupe) => ({ ...groupe, centre }))
		);

		if (evenementsActives.length === 0)
		{
			afficherToast("Ajoute d'abord au moins un groupe permanent ou avec une semaine ouverte dans Gestion.", true);
			return;
		}

		const construirePopup = () =>
		{
			const nomsQualifications = new Map(
				(qualificationsPlanning || []).map((qualification) => [String(qualification.id), qualification.nom])
			);

			const centresHtml = centresPlanning.map((centre) =>
			{
				const evenements = (centre.evenements || []).filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0);
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
							<div><strong>${escapeHtml(centre.nom)}</strong><span>${evenements.length} groupe${evenements.length > 1 ? "s" : ""}</span></div>
						</header>
						<div class="auto-evenements-liste">${evenementsHtml}</div>
					</section>`;
			}).join("");

			modalAutoContent.innerHTML = `
				
				<div class="auto-centres-liste">${centresHtml}</div>
				<div class="edit-actions">
					<button class="btn btn-primary" id="auto-valider" type="button">Remplir la semaine</button>
					<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
				</div>`;

			modalAutoContent.querySelector("#auto-valider").addEventListener("click", () =>
			{
				if (!confirm("Remplir automatiquement tous les groupes du lundi au vendredi avec les besoins enregistrés dans Gestion ? Les affectations existantes de ces jours seront remplacées.")) return;
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