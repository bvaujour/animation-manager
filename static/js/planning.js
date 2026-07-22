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
	const centresToolbar = document.getElementById("planning-centres-toolbar");
	const menuAjouterCentre = document.getElementById("planning-add-centre-menu");
	const compteurCentresMasques = document.getElementById("planning-hidden-centres-count");
	const layoutPlanning = document.getElementById("layout");
	const ongletsPlanning = Array.from(document.querySelectorAll("[data-planning-mode]"));
	const planningQuery = new URLSearchParams(window.location.search);
	const modeDemande = planningQuery.get("mode");
	let modePlanning = ["affectations", "effectifs"].includes(modeDemande)
		? modeDemande
		: (["effectifs"].includes(localStorage.getItem("planning-mode"))
			? localStorage.getItem("planning-mode") : "affectations");
	const animList = document.getElementById("animateurs-list");
	const filtresStatutsConteneur = document.getElementById("animateurs-filter-statuts");
	const filtresQualificationsConteneur = document.getElementById("animateurs-filter-qualifications");
	const filtresCentresConteneur = document.getElementById("animateurs-filter-centres");
	const filtreSituationAnimateurs = document.getElementById("animateurs-filter-situation");
	const compteurFiltresAnimateurs = document.getElementById("animateurs-filter-count");
	const boutonEffacerFiltresAnimateurs = document.getElementById("animateurs-filter-reset");
	const rechercheAnimateursInput = document.getElementById("animateurs-search-input");
	const toolbarLabel = document.getElementById("toolbar-label");
	const modalEffectifsEnfants = document.getElementById("modal-effectifs-enfants");
	const formulaireEffectifsEnfants = document.getElementById("effectifs-enfants-form");
	const champsEffectifsEnfants = document.getElementById("effectifs-enfants-fields");
	const titreEffectifsEnfants = document.getElementById("effectifs-enfants-title");
	const boutonViderSemaineEffectifs = document.getElementById("effectifs-enfants-vider-semaine");
	const modalEncadrementSpecial = document.getElementById("modal-encadrement-special");
	const formulaireEncadrementSpecial = document.getElementById("encadrement-special-form");
	const champsEncadrementSpecial = document.getElementById("encadrement-special-fields");
	const titreEncadrementSpecial = document.getElementById("encadrement-special-title");
	const modalHorairesAffectation = document.getElementById("modal-horaires-affectation");
	const formulaireHorairesAffectation = document.getElementById("horaires-affectation-form");
	const champsHorairesAffectation = document.getElementById("horaires-affectation-fields");
	const titreHorairesAffectation = document.getElementById("horaires-affectation-title");
	const boutonSupprimerAffectation = document.getElementById("supprimer-affectation");
	const caseAffectationFlottante = document.getElementById("affectation-case-flottante");
	const modalHorairesGroupe = document.getElementById("modal-horaires-groupe");
	const formulaireHorairesGroupe = document.getElementById("horaires-groupe-form");
	const champsHorairesGroupe = document.getElementById("horaires-groupe-fields");
	const titreHorairesGroupe = document.getElementById("horaires-groupe-title");
	let contexteEffectifsEnfants = null;
	let contexteEncadrementSpecial = null;
	let contexteHorairesAffectation = null;
	let contexteHorairesGroupe = null;

	// Un FullCalendar.Calendar par centre, dans le même ordre que les
	// centres reçus de l'API. On s'en sert pour synchroniser la
	// navigation (précédent/suivant/aujourd’hui) sur tous les calendriers.
	const calendars = [];
	// Date de la période ciblée par la barre de navigation. Le tableau de
	// bord peut ouvrir directement le Planning sur une date précise.
	const dateDemandee = /^\d{4}-\d{2}-\d{2}$/.test(planningQuery.get("date") || "")
		? planningQuery.get("date")
		: null;
	const centreDemande = /^\d+$/.test(planningQuery.get("centre") || "")
		? Number(planningQuery.get("centre"))
		: null;
	let datePeriodeCourante = dateDemandee || WeekPicker.getPersistedDate() || null;

	// Petits caches front : ils évitent de refaire des appels API quand on
	// modifie un animateur ou qu'on affiche ses informations. Ils sont mis à jour
	// par chargerCentres() et chargerAnimateurs().
	let centresPlanning = [];
	const affectationsFlottantesParId = new Map();
	const creationsFlottantesEnCours = new Map();

	function eventEstFlottant(event)
	{
		return event?.extendedProps?.type_affectation === "flottant";
	}
	let animateursPlanning = [];
	let qualificationsPlanning = [];
	let centresFiltresCharges = false;
	let qualificationsFiltresChargees = false;
	let requeteAnimateursCourante = 0;

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

	let filtresStatutsAnimateurs = lireIdsFiltres("planning-filtres-statuts");
	let filtresQualificationsAnimateurs = lireIdsFiltres("planning-filtres-qualifications");
	let filtresCentresAnimateurs = lireIdsFiltres("planning-filtres-centres-preferes");
	// La vue par défaut doit toujours être « Encore plaçables ».
	// Ne pas restaurer ce filtre depuis localStorage : une ancienne sélection
	// « Tout le monde » ou « Disponibles » donnait l'impression que la règle
	// de disparition ne fonctionnait pas, même lorsque le serveur renvoyait
	// correctement encore_placable=false.
	let filtreSituationAnimateursValeur = "placable";
	let rechercheAnimateurs = "";
	localStorage.removeItem("planning-tri-animateurs");
	localStorage.removeItem("planning-filtre-disponibilite");
	localStorage.removeItem("planning-filtre-affectation");
	localStorage.removeItem("planning-filtre-situation");
	if (filtreSituationAnimateurs) filtreSituationAnimateurs.value = filtreSituationAnimateursValeur;

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


	// -----------------------------------------------------------------
	// Centres visibles et disposition libre des calendriers
	// -----------------------------------------------------------------
	// La disposition est conservée dans le navigateur. Chaque sous-tableau
	// représente une ligne ; les centres d'une même ligne se partagent toute
	// la largeur disponible. Un centre peut être fermé totalement puis rouvert
	// avec son petit bouton dans la barre située au-dessus des calendriers.
	const PLANNING_CENTRES_LAYOUT_KEY = "planning-centres-layout-v3";
	let dispositionCentres = [];
	let centreGlisseId = null;
	let cibleDepotCentre = null;

	function idsCentresVisibles()
	{
		return dispositionCentres.flat().map(Number).filter(Number.isFinite);
	}

	function normaliserDispositionCentres(valeur, centres = centresPlanning)
	{
		const idsDisponibles = new Set((centres || []).map((centre) => Number(centre.id)));
		const lignesSource = Array.isArray(valeur)
			? valeur
			: (Array.isArray(valeur?.rows) ? valeur.rows : []);
		const dejaVus = new Set();
		const lignes = [];

		for (const ligneSource of lignesSource)
		{
			if (!Array.isArray(ligneSource)) continue;
			const ligne = [];
			for (const valeurId of ligneSource)
			{
				const id = Number(valeurId);
				if (!idsDisponibles.has(id) || dejaVus.has(id)) continue;
				dejaVus.add(id);
				ligne.push(id);
			}
			if (ligne.length) lignes.push(ligne);
		}

		return lignes;
	}

	function chargerDispositionCentres(centres)
	{
		const idsDisponibles = new Set((centres || []).map((centre) => Number(centre.id)));
		if (centreDemande && idsDisponibles.has(Number(centreDemande)))
		{
			return [[Number(centreDemande)]];
		}

		try
		{
			const memorisee = JSON.parse(localStorage.getItem(PLANNING_CENTRES_LAYOUT_KEY) || "null");
			if (memorisee !== null)
			{
				const normalisee = normaliserDispositionCentres(memorisee, centres);
				// Une ancienne disposition vide ou devenue invalide ne doit jamais
				// produire un Planning entièrement blanc au chargement.
				if (normalisee.length) return normalisee;
			}
		}
		catch
		{
			// Une valeur locale invalide ne doit jamais bloquer le planning.
		}

		// Première ouverture : tous les centres occupent une seule ligne.
		return centres?.length ? [centres.map((centre) => Number(centre.id))] : [];
	}

	function sauvegarderDispositionCentres()
	{
		localStorage.setItem(PLANNING_CENTRES_LAYOUT_KEY, JSON.stringify({ rows: dispositionCentres }));
	}

	function positionCentre(centreId)
	{
		const id = Number(centreId);
		for (let ligneIndex = 0; ligneIndex < dispositionCentres.length; ligneIndex += 1)
		{
			const colonneIndex = dispositionCentres[ligneIndex].indexOf(id);
			if (colonneIndex >= 0) return { ligneIndex, colonneIndex };
		}
		return null;
	}

	function mettreAJourBarreCentres()
	{
		if (!menuAjouterCentre || !centresToolbar) return;
		const visibles = new Set(idsCentresVisibles());
		const centresMasques = centresPlanning.filter((centre) => !visibles.has(Number(centre.id)));

		if (compteurCentresMasques)
		{
			compteurCentresMasques.hidden = centresMasques.length === 0;
			compteurCentresMasques.textContent = String(centresMasques.length);
		}

		if (!centresMasques.length)
		{
			menuAjouterCentre.innerHTML = `
				<div class="planning-centres-dropdown-empty" role="status">
					<span aria-hidden="true">✓</span>
					<span>Tous les centres sont affichés</span>
				</div>`;
			return;
		}

		menuAjouterCentre.innerHTML = `
			<div class="planning-centres-dropdown-heading">Afficher un centre</div>
			${centresMasques.map((centre) => `
				<button class="planning-centres-dropdown-option" type="button" role="menuitem" data-add-centre-id="${centre.id}">
					<span class="planning-centre-color" style="--centre-option-color:${escapeHtml(centre.couleur || "#6650c8")}"></span>
					<span>${escapeHtml(centre.nom)}</span>
					<span class="planning-centres-dropdown-add" aria-hidden="true">＋</span>
				</button>`).join("")}
		`;
	}

	function detruireCentreRendu(centreId)
	{
		const id = Number(centreId);
		for (let index = calendars.length - 1; index >= 0; index -= 1)
		{
			if (Number(calendars[index].centrePlanning?.id) !== id) continue;
			calendars[index].destroy();
			calendars.splice(index, 1);
		}
		calendarsContainer.querySelector(`.centre-planning-group[data-centre-id="${id}"]`)?.remove();
	}

	function creerZoneDepotLigne(indexInsertion)
	{
		const zone = document.createElement("div");
		zone.className = "planning-row-dropzone";
		zone.dataset.insertRow = String(indexInsertion);
		zone.setAttribute("aria-label", "Créer une nouvelle ligne");
		zone.innerHTML = `
			<span class="planning-row-dropzone-icon" aria-hidden="true">＋</span>
			<span class="planning-row-dropzone-label">Créer une nouvelle ligne</span>
		`;
		return zone;
	}

	function rendreDispositionCentres({ persister = true } = {})
	{
		dispositionCentres = normaliserDispositionCentres(dispositionCentres);
		calendarsContainer.dataset.planningRows = String(dispositionCentres.length);
		calendarsContainer.style.setProperty("--planning-visible-row-count", String(Math.max(1, dispositionCentres.length)));

		const visibles = new Set(idsCentresVisibles());
		Array.from(calendarsContainer.querySelectorAll(".centre-planning-group")).forEach((carte) =>
		{
			const id = Number(carte.dataset.centreId);
			if (!visibles.has(id)) detruireCentreRendu(id);
		});

		const cartesExistantes = new Map(
			Array.from(calendarsContainer.querySelectorAll(".centre-planning-group"))
				.map((carte) => [Number(carte.dataset.centreId), carte])
		);
		const fragment = document.createDocumentFragment();
		const lignesDom = [];

		if (dispositionCentres.length)
		{
			fragment.appendChild(creerZoneDepotLigne(0));
			dispositionCentres.forEach((ligne, index) =>
			{
				const element = document.createElement("div");
				element.className = "planning-centres-row";
				element.dataset.planningRow = String(index);
				element.dataset.centresCount = String(Math.max(1, ligne.length));
				element.style.setProperty("--planning-row-count", String(Math.max(1, ligne.length)));
				ligne.forEach((centreId) =>
				{
					const carte = cartesExistantes.get(Number(centreId));
					if (carte) element.appendChild(carte);
				});
				fragment.appendChild(element);
				fragment.appendChild(creerZoneDepotLigne(index + 1));
				lignesDom.push(element);
			});
		}
		else
		{
			const vide = document.createElement("div");
			vide.className = "planning-centres-empty";
			vide.setAttribute("aria-hidden", "true");
			fragment.appendChild(vide);
		}

		calendarsContainer.replaceChildren(fragment);
		const calendriersAvant = new Set(calendars);
		dispositionCentres.forEach((ligne, ligneIndex) =>
		{
			ligne.forEach((centreId) =>
			{
				if (cartesExistantes.has(Number(centreId))) return;
				const centre = centresPlanning.find((item) => Number(item.id) === Number(centreId));
				if (centre) ajouterCentreAuPlanning(centre, lignesDom[ligneIndex]);
			});
		});

		if (datePeriodeCourante)
		{
			calendars.filter((calendar) => !calendriersAvant.has(calendar)).forEach((calendar) => calendar.gotoDate(datePeriodeCourante));
		}
		if (persister) sauvegarderDispositionCentres();
		mettreAJourBarreCentres();
		mettreAJourDimensionsCalendriers();
		window.setTimeout(mettreAJourDimensionsCalendriers, 60);
	}

	function ajouterCentreVisible(centreId)
	{
		const id = Number(centreId);
		if (idsCentresVisibles().includes(id)) return;
		if (!dispositionCentres.length) dispositionCentres = [[id]];
		else dispositionCentres[dispositionCentres.length - 1].push(id);
		rendreDispositionCentres();
	}

	function retirerCentreVisible(centreId)
	{
		const id = Number(centreId);
		dispositionCentres = dispositionCentres
			.map((ligne) => ligne.filter((valeur) => Number(valeur) !== id))
			.filter((ligne) => ligne.length);
		nettoyerModePlacementJour();
		rendreDispositionCentres();
	}

	function retirerCentreDeDisposition(centreId)
	{
		const position = positionCentre(centreId);
		if (!position) return null;
		const { ligneIndex, colonneIndex } = position;
		dispositionCentres[ligneIndex].splice(colonneIndex, 1);
		const ligneSupprimee = dispositionCentres[ligneIndex].length === 0;
		if (ligneSupprimee) dispositionCentres.splice(ligneIndex, 1);
		return { ligneIndex, colonneIndex, ligneSupprimee };
	}

	function nettoyerIndicationsDepotCentre()
	{
		calendarsContainer.querySelectorAll(".planning-drop-before, .planning-drop-after, .planning-drop-row, .is-drop-target")
			.forEach((element) => element.classList.remove("planning-drop-before", "planning-drop-after", "planning-drop-row", "is-drop-target"));
		cibleDepotCentre = null;
	}

	function appliquerDepotCentre(centreId, cible)
	{
		const id = Number(centreId);
		if (!Number.isFinite(id) || !cible) return;

		if (cible.type === "before" || cible.type === "after")
		{
			if (Number(cible.targetId) === id) return;
			retirerCentreDeDisposition(id);
			const positionCible = positionCentre(cible.targetId);
			if (!positionCible) return;
			const index = positionCible.colonneIndex + (cible.type === "after" ? 1 : 0);
			dispositionCentres[positionCible.ligneIndex].splice(index, 0, id);
		}
		else if (cible.type === "append-row")
		{
			retirerCentreDeDisposition(id);
			const positionAncre = positionCentre(cible.anchorId);
			if (!positionAncre)
			{
				dispositionCentres.push([id]);
			}
			else
			{
				dispositionCentres[positionAncre.ligneIndex].push(id);
			}
		}
		else if (cible.type === "new-row")
		{
			const retrait = retirerCentreDeDisposition(id);
			let indexInsertion = Math.max(0, Math.min(Number(cible.rowIndex), dispositionCentres.length));
			if (retrait?.ligneSupprimee && retrait.ligneIndex < Number(cible.rowIndex)) indexInsertion -= 1;
			indexInsertion = Math.max(0, Math.min(indexInsertion, dispositionCentres.length));
			dispositionCentres.splice(indexInsertion, 0, [id]);
		}
		else
		{
			return;
		}

		dispositionCentres = dispositionCentres.filter((ligne) => ligne.length);
		rendreDispositionCentres();
	}

	menuAjouterCentre?.addEventListener("click", (event) =>
	{
		const option = event.target.closest("[data-add-centre-id]");
		if (!option) return;
		ajouterCentreVisible(option.dataset.addCentreId);
		centresToolbar?.removeAttribute("open");
	});

	document.addEventListener("click", (event) =>
	{
		if (!centresToolbar?.hasAttribute("open") || centresToolbar.contains(event.target)) return;
		centresToolbar.removeAttribute("open");
	});

	centresToolbar?.addEventListener("keydown", (event) =>
	{
		if (event.key !== "Escape") return;
		centresToolbar.removeAttribute("open");
		centresToolbar.querySelector("summary")?.focus();
	});

	calendarsContainer.addEventListener("click", (event) =>
	{
		const bouton = event.target.closest("[data-centre-action=remove]");
		if (!bouton) return;
		const carte = bouton.closest(".centre-planning-group");
		if (!carte) return;
		event.preventDefault();
		event.stopPropagation();
		retirerCentreVisible(carte.dataset.centreId);
	});

	// Le drag HTML5 natif s'avère peu fiable avec FullCalendar et les cartes
	// reconstruites dynamiquement. On utilise donc les Pointer Events : le geste
	// démarre depuis n'importe quel point de l'en-tête, suit réellement la souris
	// (ou le doigt), puis applique la disposition au relâchement.
	let deplacementCentre = null;
	let fantomeCentre = null;

	function creerFantomeCentre(carte)
	{
		const fantome = document.createElement("div");
		fantome.className = "planning-centre-drag-ghost";
		fantome.style.setProperty("--centre-color", carte.style.getPropertyValue("--centre-color") || "var(--color-primary)");
		fantome.textContent = carte.querySelector(".calendar-site-name")?.textContent?.trim() || "Centre";
		document.body.appendChild(fantome);
		return fantome;
	}

	function positionnerFantomeCentre(clientX, clientY)
	{
		if (!fantomeCentre) return;
		fantomeCentre.style.transform = `translate3d(${Math.round(clientX + 14)}px, ${Math.round(clientY + 14)}px, 0)`;
	}

	function definirCibleDepotCentre(clientX, clientY)
	{
		nettoyerIndicationsDepotCentre();
		const element = document.elementFromPoint(clientX, clientY);
		if (!element || !calendarsContainer.contains(element)) return;

		const zone = element.closest(".planning-row-dropzone");
		if (zone)
		{
			zone.classList.add("is-drop-target");
			cibleDepotCentre = { type: "new-row", rowIndex: Number(zone.dataset.insertRow) };
			return;
		}

		const carte = element.closest(".centre-planning-group");
		if (carte && Number(carte.dataset.centreId) !== centreGlisseId)
		{
			const rect = carte.getBoundingClientRect();
			const apres = clientX >= rect.left + rect.width / 2;
			carte.classList.add(apres ? "planning-drop-after" : "planning-drop-before");
			cibleDepotCentre = {
				type: apres ? "after" : "before",
				targetId: Number(carte.dataset.centreId),
			};
			return;
		}

		const ligne = element.closest(".planning-centres-row");
		if (!ligne) return;
		const ancre = Array.from(ligne.querySelectorAll(".centre-planning-group"))
			.find((item) => Number(item.dataset.centreId) !== centreGlisseId);
		if (!ancre) return;
		ligne.classList.add("planning-drop-row");
		cibleDepotCentre = { type: "append-row", anchorId: Number(ancre.dataset.centreId) };
	}

	function faireDefilerPendantDeplacement(clientY)
	{
		const marge = 72;
		const vitesse = 18;
		const rect = calendarsContainer.getBoundingClientRect();
		if (clientY < rect.top + marge) calendarsContainer.scrollTop -= vitesse;
		else if (clientY > rect.bottom - marge) calendarsContainer.scrollTop += vitesse;
	}

	function demarrerDeplacementCentre(event)
	{
		const entete = event.target.closest?.(".centre-planning-header");
		const carte = entete?.closest(".centre-planning-group");
		if (!entete || !carte || event.isPrimary === false) return;
		if (event.pointerType === "mouse" && event.button !== 0) return;
		if (event.target.closest("button, a, input, select, textarea, summary, [role=button]")) return;

		deplacementCentre = {
			pointerId: event.pointerId,
			startX: event.clientX,
			startY: event.clientY,
			clientX: event.clientX,
			clientY: event.clientY,
			carte,
			entete,
			actif: false,
		};
		try
		{
			entete.setPointerCapture?.(event.pointerId);
		}
		catch
		{
			// Le déplacement reste fonctionnel grâce aux écouteurs installés sur window.
		}
		event.preventDefault();
	}

	function suivreDeplacementCentre(event)
	{
		if (!deplacementCentre || event.pointerId !== deplacementCentre.pointerId) return;
		deplacementCentre.clientX = event.clientX;
		deplacementCentre.clientY = event.clientY;

		if (!deplacementCentre.actif)
		{
			const distance = Math.hypot(
				event.clientX - deplacementCentre.startX,
				event.clientY - deplacementCentre.startY,
			);
			if (distance < 5) return;

			deplacementCentre.actif = true;
			centreGlisseId = Number(deplacementCentre.carte.dataset.centreId);
			deplacementCentre.carte.classList.add("planning-centre-dragging");
			document.body.classList.add("planning-centre-sort-active");
			fantomeCentre = creerFantomeCentre(deplacementCentre.carte);
		}

		event.preventDefault();
		positionnerFantomeCentre(event.clientX, event.clientY);
		definirCibleDepotCentre(event.clientX, event.clientY);
		faireDefilerPendantDeplacement(event.clientY);
	}

	function terminerDeplacementCentre(event, annuler = false)
	{
		if (!deplacementCentre || (event && event.pointerId !== deplacementCentre.pointerId)) return;
		const etat = deplacementCentre;
		const id = centreGlisseId;
		const cible = cibleDepotCentre ? { ...cibleDepotCentre } : null;

		if (event && etat.actif) event.preventDefault();
		if (etat.entete.hasPointerCapture?.(etat.pointerId))
		{
			etat.entete.releasePointerCapture(etat.pointerId);
		}
		etat.carte.classList.remove("planning-centre-dragging");
		fantomeCentre?.remove();
		fantomeCentre = null;
		deplacementCentre = null;
		centreGlisseId = null;
		document.body.classList.remove("planning-centre-sort-active");
		nettoyerIndicationsDepotCentre();

		if (!annuler && etat.actif && Number.isFinite(id) && cible)
		{
			appliquerDepotCentre(id, cible);
		}
	}

	calendarsContainer.addEventListener("pointerdown", demarrerDeplacementCentre);
	window.addEventListener("pointermove", suivreDeplacementCentre, { passive: false });
	window.addEventListener("pointerup", (event) => terminerDeplacementCentre(event));
	window.addEventListener("pointercancel", (event) => terminerDeplacementCentre(event, true));
	window.addEventListener("blur", () => terminerDeplacementCentre(null, true));



function libelleDate(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
	}

	function periodeEvenementLibelle(evenement)
	{
		if (evenement.permanent) return "Permanent — toutes les semaines";
		if ((evenement.periodes || []).length)
		{
			return evenement.periodes.map((periode) => periode.libelle || periode.nom).join(", ");
		}
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

	function creerAffectationFlottanteDepuisJour(animateur, centre, debut, cellule = null)
	{
		if (!animateur || !centre || !debut) return Promise.reject({ error: "Affectation flottante incomplète." });
		if (!animateurDisponibleCeJour(animateur, debut))
		{
			return Promise.reject({ error: `${animateur.prenom} n'est pas disponible le ${libelleDate(debut)}.` });
		}

		const fin = addDays(debut, 1);
		const cleRequete = `${animateur.id}:${centre.id}:${debut}`;
		if (creationsFlottantesEnCours.has(cleRequete))
		{
			return creationsFlottantesEnCours.get(cleRequete);
		}
		if (cellule)
		{
			cellule.classList.add("is-saving");
			const ligneCourante = cellule.closest(".planning-floating-lane");
			// Fige le rendu de cette ligne pendant l'enregistrement : une lecture
			// plus ancienne ne doit pas remplacer la cellule manipulée.
			if (ligneCourante)
				ligneCourante.floatingRequestVersion = (ligneCourante.floatingRequestVersion || 0) + 1;
		}

		const requete = apiFetch("/api/affectations/",
		{
			method: "POST",
			body: JSON.stringify({
				animateur_id: animateur.id,
				centre_id: centre.id,
				type_affectation: "flottant",
				debut: debut,
				fin: fin,
			}),
		}).then((data) =>
		{
			// La ligne flottante n'est pas un calendrier FullCalendar : on y
			// injecte donc immédiatement la réponse enregistrée par l'API.
			affectationsFlottantesParId.set(String(data.id), data);
			const ligne = document.querySelector(`.centre-planning-group[data-centre-id="${centre.id}"] .planning-floating-lane`);
			// Invalide une éventuelle lecture de semaine partie avant ce POST :
			// sa réponse ne doit pas réafficher la case vide après notre rendu.
			if (ligne) ligne.floatingRequestVersion = (ligne.floatingRequestVersion || 0) + 1;
			// La ligne peut avoir été reconstruite pendant l'attente réseau. On
			// privilégie toujours sa cellule actuellement attachée au document.
			const celluleCible = ligne?.querySelector(`.planning-floating-day[data-date="${debut}"]`)
				|| (cellule?.isConnected ? cellule : null);
			if (celluleCible)
			{
				celluleCible.classList.add("is-occupied");
				celluleCible.title = `Modifier l’animateur flottant le ${libelleDate(debut)}`;
				celluleCible.setAttribute("aria-label", celluleCible.title);
				celluleCible.innerHTML = `<button type="button" class="planning-floating-person" data-affectation-id="${data.id}" style="--floating-bg:${escapeHtml(data.backgroundColor || '#eef2ff')};--floating-border:${escapeHtml(data.borderColor || '#64748b')}">${escapeHtml((data.title || '').replace(/^↔\s*/, ''))}</button>`;
			}
			calendars
				.filter((calendar) => Number(calendar.centrePlanning?.id) === Number(centre.id))
				.forEach((calendar) => rafraichirAffichageEffectifsEnfants(calendar));
			// Aucun calendrier de groupe n'a changé : les recharger tous retardait
			// l'affichage et pouvait écraser la case avec une réponse obsolète.
			PlanningData.invalidateWeekEvents();
			rafraichirAnimateursSemaine();
			afficherToast(`${animateur.prenom} est flottant·e à ${centre.nom}, le ${libelleDate(debut)}.`);
			return data;
		}).finally(() =>
		{
			creationsFlottantesEnCours.delete(cleRequete);
			if (cellule) cellule.classList.remove("is-saving");
		});

		creationsFlottantesEnCours.set(cleRequete, requete);
		return requete;
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
			PlanningData.invalidateWeekEvents(calendarCible.view?.activeStart, calendarCible.view?.activeEnd);
			calendarCible.refetchEvents();
			rafraichirAnimateursSemaine();
			return;
		}

		// Les actions globales (remplissage automatique, etc.) peuvent modifier
		// plusieurs groupes : elles seules rechargent tous les calendriers.
		const calendarReference = calendars[0];
		PlanningData.invalidateWeekEvents(calendarReference?.view?.activeStart, calendarReference?.view?.activeEnd);
		calendars.forEach((calendar) => calendar.refetchEvents());
		rafraichirAnimateursSemaine();
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
			PlanningData.invalidateWeekEvents();
			rafraichirAnimateursSemaine();
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
		const definirVisibilite = (element, visible) =>
		{
			element.hidden = !visible;
			if (visible) element.style.removeProperty("display");
			else element.style.setProperty("display", "none", "important");
		};

		document.querySelectorAll(".evenement-calendar-card").forEach((card) => {
			const groupe = centresPlanning.flatMap((centre) => centre.evenements || [])
				.find((item) => Number(item.id) === Number(card.dataset.evenementId));
			card.hidden = !groupe || !groupeOuvertSurPlage(groupe, debut, fin);
			if (card.hidden) card.style.setProperty("display", "none", "important");
			else card.style.removeProperty("display");
		});

		document.querySelectorAll(".centre-planning-group").forEach((bloc) => {
			const cartes = Array.from(bloc.querySelectorAll(".evenement-calendar-card"));
			const visibles = cartes.filter((card) => !card.hidden);
			const aucunGroupeVisible = visibles.length === 0;
			const zoneGroupes = bloc.querySelector(".evenement-calendars");
			if (zoneGroupes)
			{
				zoneGroupes.dataset.visibleGroups = String(visibles.length);
				zoneGroupes.style.setProperty("--planning-visible-group-count", String(Math.max(1, visibles.length)));
			}

			// Le lieu reste visible même lorsque tous ses groupes sont fermés.
			// Seules les cartes de groupes sortent du Planning.
			bloc.hidden = false;
			bloc.style.removeProperty("display");

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

		// Les rangées portent les lieux : elles restent donc présentes même si
		// aucun groupe n'est ouvert durant la semaine.
		document.querySelectorAll(".planning-centres-row").forEach((ligne) =>
		{
			definirVisibilite(ligne, true);
		});
	}

	function estModeEffectifs()
	{
		return modePlanning === "effectifs";
	}

	function estModeAffectations()
	{
		return modePlanning === "affectations";
	}

	function appliquerModePlanning(nouveauMode, memoriser = true)
	{
		// Les deux onglets réutilisent exactement les mêmes instances et la
		// même géométrie de calendriers. On mémorise donc la position de
		// défilement avant de remplacer uniquement leur contenu visible.
		const scrollTopAvant = calendarsContainer.scrollTop;
		modePlanning = ["affectations", "effectifs"].includes(nouveauMode)
			? nouveauMode : "affectations";
		if (memoriser) localStorage.setItem("planning-mode", modePlanning);
		layoutPlanning.dataset.planningMode = modePlanning;
		document.body.classList.toggle("planning-mode-effectifs", estModeEffectifs());
		document.body.classList.toggle("planning-mode-affectations", modePlanning === "affectations");
		ongletsPlanning.forEach((onglet) =>
		{
			const actif = onglet.dataset.planningMode === modePlanning;
			onglet.classList.toggle("active", actif);
			onglet.setAttribute("aria-selected", String(actif));
		});
		calendars.forEach((calendar) =>
		{
			const modeAffectationsActif = modePlanning === "affectations";
			calendar.setOption("editable", modeAffectationsActif);
			calendar.setOption("droppable", modeAffectationsActif);
			// La sélection d'une journée FullCalendar entre en conflit avec les
			// boutons d'édition directe des effectifs. Elle n'est utile que dans
			// l'onglet Affectations.
			calendar.setOption("selectable", modeAffectationsActif);
			if (!modeAffectationsActif) calendar.unselect();
			calendar.updateSize();
		});
		centresPlanning.forEach((centre) => mettreAJourTotalEffectifsCentre(centre.id));
		if (!estModeAffectations())
		{
			animateurActif = null;
			animateurDragPreview = null;
			effacerDisponibilitesAffichees();
			nettoyerModePlacementJour();
			document.querySelectorAll(".animateur.selected").forEach((element) => element.classList.remove("selected"));
		}
		calendars.forEach((calendar) => rafraichirAffichageEffectifsEnfants(calendar));
		window.setTimeout(() =>
		{
			mettreAJourDimensionsCalendriers();
			calendarsContainer.scrollTop = scrollTopAvant;
		}, 20);
	}

	ongletsPlanning.forEach((onglet) => onglet.addEventListener("click", () =>
		appliquerModePlanning(onglet.dataset.planningMode)
	));

	function libelleJourEffectif(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "2-digit" });
	}

	function evenementActifLeJour(event, dateStr)
	{
		if (event.display === "background" || !event.start) return false;
		// Les événements FullCalendar portent des Date, tandis que la ligne
		// flottante lit directement le JSON de l'API et reçoit des chaînes.
		const debut = typeof event.start === "string" ? event.start.slice(0, 10) : formatDateLocal(event.start);
		const fin = event.end
			? (typeof event.end === "string" ? event.end.slice(0, 10) : formatDateLocal(event.end))
			: addDays(debut, 1);
		return debut <= dateStr && dateStr < fin;
	}

	function compterAnimateursAffectes(calendar, dateStr)
	{
		const ids = new Set();
		calendar.getEvents().forEach((event) =>
		{
			if (!evenementActifLeJour(event, dateStr) || eventEstFlottant(event)) return;
			const animateurId = idAnimateurDepuisEvent(event);
			if (animateurId) ids.add(Number(animateurId));
		});
		return ids.size;
	}

	function calculerCouvertureLieu(centreId, dateStr)
	{
		const groupes = calendars
			.filter((calendar) => Number(calendar.centrePlanning?.id) === Number(centreId))
			.map((calendar) =>
			{
				const valeur = normaliserEffectifJour(
					calendar.evenementPlanning.effectifsEnfants?.[dateStr],
					calendar.evenementPlanning.enfants_par_animateur_defaut
				);
				const fixes = compterAnimateursAffectes(calendar, dateStr);
				return {
					calendar,
					ratio: valeur.enfantsParAnimateur,
					restant: Math.max(0, valeur.nombre - (fixes * valeur.enfantsParAnimateur)),
				};
			});

		// Les flottants vivent dans une ligne extérieure aux calendriers des
		// groupes. Leur cache dédié est donc la source fiable du calcul du lieu.
		const flottants = new Map();
		for (const event of affectationsFlottantesParId.values())
		{
			if (Number(event.extendedProps?.centre_id) !== Number(centreId)
				|| !evenementActifLeJour(event, dateStr)) continue;
			const animateurId = idAnimateurDepuisEvent(event);
			if (animateurId) flottants.set(Number(animateurId), event);
		}

		const ratiosFlottants = [];
		for (const event of flottants.values())
		{
			const groupesRestants = groupes.filter((groupe) => groupe.restant > 0);
			if (!groupesRestants.length) break;
			const ratioFlottant = Math.min(...groupesRestants.map((groupe) => groupe.ratio));
			ratiosFlottants.push({ animateurId: idAnimateurDepuisEvent(event), ratio: ratioFlottant });
			let capacite = ratioFlottant;
			groupesRestants.sort((a, b) => a.ratio - b.ratio || a.calendar.evenementPlanning.id - b.calendar.evenementPlanning.id);
			for (const groupe of groupesRestants)
			{
				if (capacite <= 0) break;
				const couverts = Math.min(groupe.restant, capacite);
				groupe.restant -= couverts;
				capacite -= couverts;
			}
		}

		return {
			parGroupe: new Map(groupes.map((groupe) => [Number(groupe.calendar.evenementPlanning.id), groupe.restant])),
			flottants: ratiosFlottants,
		};
	}

	function normaliserEffectifJour(valeur, ratioDefaut = 8)
	{
		const ratio = Math.max(1, Number(ratioDefaut || 8));
		if (typeof valeur === "number")
		{
			return { nombre: valeur, enfantsParAnimateur: ratio, heureArrivee: "", heureDepart: "" };
		}
		const exceptionnel = valeur?.ratioEncadrementExceptionnel ?? valeur?.ratio_encadrement_exceptionnel ?? null;
		return {
			nombre: Number(valeur?.nombre || 0),
			enfantsParAnimateur: Math.max(1, Number(exceptionnel || valeur?.enfantsParAnimateur || valeur?.enfants_par_animateur || ratio)),
			ratioEncadrementExceptionnel: exceptionnel === null || exceptionnel === "" ? null : Math.max(1, Number(exceptionnel)),
			heureArrivee: valeur?.heureArrivee ?? valeur?.heure_arrivee ?? "",
			heureDepart: valeur?.heureDepart ?? valeur?.heure_depart ?? "",
		};
	}

	async function enregistrerValeurEffectifInline(calendar, dateStr, champ, valeur)
	{
		const payload = champ === "nombre"
			? { effectifs: [{ date: dateStr, nombre: valeur }] }
			: { ratios_encadrement: [{ date: dateStr, ratio: valeur }] };

		await apiFetch(`/api/groupes/${calendar.evenementPlanning.id}/effectifs-enfants/`, {
			method: "POST",
			body: JSON.stringify(payload),
		});

		const ratioDefaut = Math.max(1, Number(calendar.evenementPlanning.enfants_par_animateur_defaut || 8));
		const valeurCourante = normaliserEffectifJour(
			calendar.evenementPlanning.effectifsEnfants?.[dateStr],
			ratioDefaut
		);
		calendar.evenementPlanning.effectifsEnfants = {
			...(calendar.evenementPlanning.effectifsEnfants || {}),
			[dateStr]: champ === "nombre"
				? { ...valeurCourante, nombre: valeur }
				: {
					...valeurCourante,
					enfantsParAnimateur: valeur ?? ratioDefaut,
					ratioEncadrementExceptionnel: valeur,
				},
		};
		rafraichirAffichageEffectifsEnfants(calendar);
		PlanningData.invalidateWeekEffectifs(calendar.view?.activeStart, calendar.view?.activeEnd);
		await chargerEffectifsEnfants(calendar);
	}

	function ouvrirEditionEffectifInline(calendar, dateStr, champ, bouton)
	{
		if (!estModeEffectifs() || !bouton || bouton.disabled) return;

		// Une seule valeur est éditée à la fois. Un clic ailleurs valide l'éditeur
		// déjà ouvert grâce à son événement blur.
		document.querySelector(".planning-inline-editor input")?.blur();

		const valeurJour = normaliserEffectifJour(
			calendar.evenementPlanning.effectifsEnfants?.[dateStr],
			calendar.evenementPlanning.enfants_par_animateur_defaut
		);
		const valeurInitiale = champ === "nombre"
			? valeurJour.nombre
			: valeurJour.enfantsParAnimateur;
		const autoriserVide = champ === "ratio";
		const editeur = document.createElement("span");
		editeur.className = "planning-inline-editor";
		editeur.innerHTML = `${champ === "ratio" ? '<span class="planning-inline-prefix">1/</span>' : ""}<input type="number" inputmode="numeric" min="${champ === "nombre" ? 0 : 1}" max="999" step="1" value="${valeurInitiale}" aria-label="${champ === "nombre" ? "Modifier le nombre d’enfants" : "Modifier le taux d’encadrement"}">`;

		bouton.hidden = true;
		bouton.insertAdjacentElement("afterend", editeur);
		const input = editeur.querySelector("input");
		let termine = false;

		function restaurer()
		{
			if (termine) return;
			termine = true;
			editeur.remove();
			bouton.hidden = false;
		}

		async function valider()
		{
			if (termine) return;
			const brut = input.value.trim();
			if (!brut && !autoriserVide)
			{
				afficherToast("Saisissez un nombre d’enfants, même zéro.", true);
				input.focus();
				return;
			}

			const valeur = brut === "" ? null : Number(brut);
			const minimum = champ === "nombre" ? 0 : 1;
			if (valeur !== null && (!Number.isInteger(valeur) || valeur < minimum || valeur > 999))
			{
				afficherToast(champ === "nombre"
					? "L’effectif doit être compris entre 0 et 999."
					: "Le taux doit être compris entre 1 et 999.", true);
				input.focus();
				return;
			}

			const valeurComparee = champ === "ratio" && valeur === null
				? calendar.evenementPlanning.enfants_par_animateur_defaut
				: valeur;
			if (Number(valeurComparee) === Number(valeurInitiale)
				&& !(champ === "ratio" && valeur === null && valeurJour.ratioEncadrementExceptionnel !== null))
			{
				restaurer();
				return;
			}

			editeur.classList.add("is-saving");
			input.disabled = true;
			try
			{
				await enregistrerValeurEffectifInline(calendar, dateStr, champ, valeur);
				termine = true;
				editeur.remove();
				bouton.remove();
			}
			catch (err)
			{
				editeur.classList.remove("is-saving");
				input.disabled = false;
				afficherToast(erreurMessage(err, "La valeur n’a pas pu être enregistrée."), true);
				input.focus();
			}
		}

		input.addEventListener("keydown", (event) =>
		{
			if (event.key === "Enter")
			{
				event.preventDefault();
				valider();
			}
			else if (event.key === "Escape")
			{
				event.preventDefault();
				restaurer();
			}
		});
		input.addEventListener("blur", () => window.setTimeout(() => valider(), 0));
		input.focus();
		input.select();
	}

	function iconeEffectif(type)
	{
		const icones = {
			enfants: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 2a4 4 0 0 0-4 4c0 .62.14 1.2.39 1.72A5.5 5.5 0 0 0 6.5 18v2h11v-2a5.5 5.5 0 0 0-1.89-4.28c.25-.52.39-1.1.39-1.72a4 4 0 0 0-4-4Zm0 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm0 6c1.93 0 3.5 1.57 3.5 3.5V18h-7v-4.5A3.5 3.5 0 0 1 12 10Z"/></svg>`,
			ratio: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7 3h10v2h-4v3.1a5 5 0 0 1 3.9 3.9H20v2h-3.1a5 5 0 0 1-9.8 0H4v-2h3.1A5 5 0 0 1 11 8.1V5H7V3Zm5 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/></svg>`,
			nonCouverts: `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 2a4 4 0 0 0-4 4c0 .62.14 1.2.39 1.72A5.5 5.5 0 0 0 6.5 18v2h7.18A6 6 0 0 1 18 10.35V10a4 4 0 0 0-2.39-3.66A4 4 0 0 0 12 2Zm0 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm0 6c.4 0 .79.07 1.15.2A6 6 0 0 0 12 13.5c0 1.74.74 3.31 1.92 4.4H8.5v-4.4A3.5 3.5 0 0 1 12 10Zm6 2a1 1 0 0 1 1 1v3.59l1.2 1.2-1.41 1.42L17 17.41V13a1 1 0 0 1 1-1Zm0 8a1.15 1.15 0 1 1 0-2.3A1.15 1.15 0 0 1 18 20Z"/></svg>`,
		};
		return `<span class="planning-effectif-icon planning-effectif-icon--${type}">${icones[type] || ""}</span>`;
	}

	function afficherEffectifsEnfantsDansCalendrier(calendar)
	{
		const valeurs = calendar.evenementPlanning.effectifsEnfants || {};
		const cellules = Array.from(calendar.el.querySelectorAll(".fc-daygrid-day"));
		cellules.forEach((cellule) =>
		{
			const dateStr = cellule.dataset.date;
			const cadre = cellule.querySelector(".fc-daygrid-day-frame");
			if (!cadre || !dateStr) return;

			cadre.querySelector(".planning-effectif-enfants-zone")?.remove();
			cadre.querySelector(".planning-uncovered-children")?.remove();

			const valeur = normaliserEffectifJour(
				valeurs[dateStr],
				calendar.evenementPlanning.enfants_par_animateur_defaut
			);
			if (!valeur.nombre) return;

			const animateursAffectes = compterAnimateursAffectes(calendar, dateStr);
			const couvertureLieu = calculerCouvertureLieu(calendar.centrePlanning?.id, dateStr);
			const enfantsNonCouverts = couvertureLieu.parGroupe.get(Number(calendar.evenementPlanning.id))
				?? Math.max(0, valeur.nombre - (animateursAffectes * valeur.enfantsParAnimateur));
			const etat = enfantsNonCouverts > 0 ? "manque" : "ok";
			const flottantsLabel = couvertureLieu.flottants.length
				? ` — flottant${couvertureLieu.flottants.length > 1 ? "s" : ""} : ${couvertureLieu.flottants.map((item) => `1/${item.ratio}`).join(", ")}`
				: "";
			const details = `${valeur.nombre} enfant${valeur.nombre > 1 ? "s" : ""} — taux 1/${valeur.enfantsParAnimateur} — ${animateursAffectes} animateur${animateursAffectes > 1 ? "s" : ""} fixe${animateursAffectes > 1 ? "s" : ""}${flottantsLabel} — ${enfantsNonCouverts} enfant${enfantsNonCouverts > 1 ? "s" : ""} non couvert${enfantsNonCouverts > 1 ? "s" : ""}`;

			if (estModeAffectations())
			{
				const indicateur = document.createElement("span");
				indicateur.className = `planning-uncovered-children planning-uncovered-children--${etat}`;
				indicateur.innerHTML = `${iconeEffectif("nonCouverts")}<strong>${enfantsNonCouverts}</strong>`;
				indicateur.title = `Enfants non couverts : ${enfantsNonCouverts}. ${details}`;
				indicateur.setAttribute("aria-label", `Enfants non couverts : ${enfantsNonCouverts}. ${details}`);
				const evenementsJour = cadre.querySelector(".fc-daygrid-day-events");
				if (evenementsJour) evenementsJour.insertAdjacentElement("afterend", indicateur);
				else cadre.appendChild(indicateur);
				return;
			}

			const zone = document.createElement("div");
			zone.className = "planning-effectif-enfants-zone";
			const badge = document.createElement("span");
			badge.className = `planning-effectif-enfants planning-effectif-enfants--${etat}`;
			badge.innerHTML = `
				<span class="planning-effectif-details">
					<span class="planning-effectif-line planning-effectif-main" title="Nombre d’enfants">${iconeEffectif("enfants")}<button class="planning-inline-edit-trigger" type="button" data-effectif-inline="nombre" aria-label="Modifier l’effectif du ${escapeHtml(libelleJourEffectif(dateStr))}" title="Nombre d’enfants — cliquer pour modifier"><strong>${valeur.nombre}</strong></button></span>
					<span class="planning-effectif-line planning-ratio-visible" title="Taux d’encadrement">${iconeEffectif("ratio")}<button class="planning-inline-edit-trigger" type="button" data-effectif-inline="ratio" aria-label="Modifier le taux d’encadrement du ${escapeHtml(libelleJourEffectif(dateStr))}" title="Taux d’encadrement — cliquer pour modifier"><strong>1/${valeur.enfantsParAnimateur}</strong></button></span>
					<span class="planning-effectif-line planning-enfants-non-couverts" title="Nombre d’enfants non couverts">${iconeEffectif("nonCouverts")}<strong>${enfantsNonCouverts}</strong></span>
				</span>`;
			badge.querySelectorAll("[data-effectif-inline]").forEach((bouton) =>
			{
				["pointerdown", "mousedown", "touchstart"].forEach((type) =>
					bouton.addEventListener(type, (event) => event.stopPropagation(), { passive: true })
				);
				bouton.addEventListener("click", (event) =>
				{
					event.preventDefault();
					event.stopPropagation();
					ouvrirEditionEffectifInline(calendar, dateStr, bouton.dataset.effectifInline, bouton);
				});
			});
			badge.title = details;
			zone.appendChild(badge);

			const evenements = cadre.querySelector(".fc-daygrid-day-events");
			if (evenements) cadre.insertBefore(zone, evenements);
			else cadre.appendChild(zone);
		});
		mettreAJourTotalEffectifsCentre(calendar.centrePlanning?.id);
	}

	function heurePourSaisie(valeur)
	{
		return String(valeur || "").replace(":", ".");
	}

	function normaliserHeureSaisie(valeur)
	{
		const correspondance = String(valeur || "").trim().match(/^(\d{1,2})(?:[.:h](\d{1,2}))?$/i);
		if (!correspondance) return null;
		const heures = Number(correspondance[1]);
		const minutes = Number(correspondance[2] || 0);
		if (heures > 23 || minutes > 59) return null;
		return `${String(heures).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
	}

	function mettreAJourTotalEffectifsCentre(centreId)
	{
		if (!centreId) return;
		const blocCentre = calendarsContainer.querySelector(`.centre-planning-group[data-centre-id="${centreId}"]`);
		const resume = blocCentre?.querySelector(".centre-effectifs-summary");
		if (!resume) return;

		const calendriersCentre = calendars.filter((calendar) =>
			Number(calendar.centrePlanning?.id) === Number(centreId)
		);
		const calendrierReference = calendriersCentre.find((calendar) => calendar.view?.activeStart && calendar.view?.activeEnd);
		if (!calendrierReference)
		{
			resume.innerHTML = '<span class="centre-effectifs-total">Aucun effectif renseigné</span>';
			return;
		}

		const debut = formatDateLocal(calendrierReference.view.activeStart);
		const fin = formatDateLocal(calendrierReference.view.activeEnd);
		const totauxParJour = [];

		for (let dateStr = debut; dateStr < fin; dateStr = addDays(dateStr, 1))
		{
			const groupesOuverts = calendriersCentre.filter((calendar) =>
				evenementOuvertCeJour(calendar.evenementPlanning, dateStr)
			);
			if (!groupesOuverts.length) continue;

			const totalJour = groupesOuverts.reduce((total, calendar) =>
			{
				const valeurs = calendar.evenementPlanning.effectifsEnfants || {};
				return total + normaliserEffectifJour(
					valeurs[dateStr],
					calendar.evenementPlanning.enfants_par_animateur_defaut
				).nombre;
			}, 0);

			totauxParJour.push({ dateStr, totalJour });
		}

		const joursHtml = totauxParJour.map(({ dateStr, totalJour }) =>
		{
			const date = parseLocalDate(dateStr);
			const jour = date.toLocaleDateString("fr-FR", { weekday: "short" }).replace(".", "");
			const numero = date.toLocaleDateString("fr-FR", { day: "2-digit" });
			return `<span class="centre-effectifs-day"><span>${jour} ${numero}</span><strong>${totalJour}</strong></span>`;
		}).join("");

		resume.innerHTML = `
			<div class="centre-effectifs-summary-label">Total</div>
			<div class="centre-effectifs-days">${joursHtml}</div>`;
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
			const toutesLesLignes = await PlanningData.fetchWeekEffectifs(debut, fin);
			const lignes = (toutesLesLignes || []).filter(
				(ligne) => Number(ligne.groupe_id) === Number(calendar.evenementPlanning.id)
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
					{
						nombre: ligne.nombre,
						enfantsParAnimateur: ligne.enfants_par_animateur || 8,
						ratioEncadrementExceptionnel: ligne.ratio_encadrement_exceptionnel ?? null,
						heureArrivee: ligne.heure_arrivee || "",
						heureDepart: ligne.heure_depart || "",
					},
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
				<div class="effectif-enfants-row effectif-enfants-row--simple">
					<span>${escapeHtml(libelleJourEffectif(dateStr))}</span>
					<label><small>Enfants</small><input type="number" min="0" max="999" step="1" inputmode="numeric" data-date="${dateStr}" data-field="nombre" value="${valeur.nombre || ""}" placeholder="0"></label>
					<button class="btn btn-danger-ghost btn-vider-effectif-jour" type="button" data-date="${dateStr}">Vider</button>
				</div>`;
		}).join("") || '<p class="empty-note">Ce groupe n’est ouvert aucun jour cette semaine.</p>';
		ouvrirModal(modalEffectifsEnfants);
	}

	champsEffectifsEnfants?.addEventListener("click", (event) =>
	{
		const bouton = event.target.closest(".btn-vider-effectif-jour");
		if (!bouton) return;
		const input = champsEffectifsEnfants.querySelector(`input[data-field="nombre"][data-date="${bouton.dataset.date}"]`);
		if (!input) return;
		input.value = "";
		formulaireEffectifsEnfants.requestSubmit();
	});

	boutonViderSemaineEffectifs?.addEventListener("click", () =>
	{
		if (!contexteEffectifsEnfants || !window.confirm("Vider tous les effectifs enfants de cette semaine ?")) return;
		champsEffectifsEnfants.querySelectorAll('input[data-field="nombre"]').forEach((input) =>
		{
			input.value = "";
		});
		formulaireEffectifsEnfants.requestSubmit();
	});

	function ouvrirSaisieEncadrementSpecial(calendar)
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
		contexteEncadrementSpecial = { calendar, evenement, jours };
		titreEncadrementSpecial.textContent = `Encadrement spécial — ${evenement.nom}`;
		champsEncadrementSpecial.innerHTML = jours.map((dateStr) =>
		{
			const valeur = normaliserEffectifJour(valeurs[dateStr], evenement.enfants_par_animateur_defaut);
			const ratioExceptionnel = valeur.ratioEncadrementExceptionnel;
			return `
				<div class="effectif-enfants-row effectif-enfants-row--encadrement">
					<span>${escapeHtml(libelleJourEffectif(dateStr))}</span>
					<label><small>Enfants / anim.</small><input type="number" min="1" max="999" step="1" inputmode="numeric" data-date="${dateStr}" data-field="ratio-special" value="${ratioExceptionnel || ""}" placeholder="${evenement.enfants_par_animateur_defaut}"></label>
					<small class="ratio-default-label">Défaut : 1/${evenement.enfants_par_animateur_defaut}</small>
				</div>`;
		}).join("") || '<p class="empty-note">Ce groupe n’est ouvert aucun jour cette semaine.</p>';
		ouvrirModal(modalEncadrementSpecial);
	}

	function ouvrirSaisieHorairesAffectation(info, calendar)
	{
		const affectation = info.event;
		const jours = [];
		const debut = new Date(`${affectation.startStr.slice(0, 10)}T00:00:00`);
		const fin = new Date(`${(affectation.endStr || addDays(affectation.startStr, 1)).slice(0, 10)}T00:00:00`);
		for (let curseur = debut; curseur < fin; curseur = new Date(curseur.getFullYear(), curseur.getMonth(), curseur.getDate() + 1))
		{
			jours.push(formatDateLocal(curseur));
		}
		contexteHorairesAffectation = { calendar, affectation, jours };
		if (caseAffectationFlottante) caseAffectationFlottante.checked = eventEstFlottant(affectation);
		titreHorairesAffectation.textContent = `Horaires — ${affectation.extendedProps.animateur_nom || affectation.title}`;
		const horaires = affectation.extendedProps.horaires || {};
		champsHorairesAffectation.innerHTML = jours.map((dateStr) =>
		{
			const valeur = horaires[dateStr] || {};
			return `
				<div class="effectif-enfants-row horaires-affectation-row">
					<span>${escapeHtml(libelleJourEffectif(dateStr))}</span>
					<label><small>Arrivée</small><input type="text" inputmode="decimal" data-date="${dateStr}" data-field="arrivee" value="${escapeHtml(heurePourSaisie(valeur.heure_arrivee))}" placeholder="7.35" required></label>
					<label><small>Départ</small><input type="text" inputmode="decimal" data-date="${dateStr}" data-field="depart" value="${escapeHtml(heurePourSaisie(valeur.heure_depart))}" placeholder="18.35" required></label>
				</div>`;
		}).join("");
		ouvrirModal(modalHorairesAffectation);
	}

	caseAffectationFlottante?.addEventListener("change", async () =>
	{
		if (!contexteHorairesAffectation) return;
		caseAffectationFlottante.disabled = true;
		try
		{
			await apiFetch(`/api/affectations/${contexteHorairesAffectation.affectation.id}/`, {
				method: "PATCH",
				body: JSON.stringify({ type_affectation: caseAffectationFlottante.checked ? "flottant" : "groupe" }),
			});
			PlanningData.invalidateWeekEvents();
			calendars.forEach((item) => item.refetchEvents());
			afficherToast(caseAffectationFlottante.checked
				? "L’animateur couvre maintenant les reliquats de ce lieu."
				: "L’animateur est de nouveau affecté uniquement à ce groupe.");
		}
		catch (err)
		{
			caseAffectationFlottante.checked = !caseAffectationFlottante.checked;
			afficherToast(erreurMessage(err, "Le statut flottant n’a pas pu être enregistré."), true);
		}
		finally
		{
			caseAffectationFlottante.disabled = false;
		}
	});

	formulaireHorairesAffectation?.addEventListener("submit", async (event) =>
	{
		event.preventDefault();
		if (!contexteHorairesAffectation) return;
		const horaires = [];
		for (const dateStr of contexteHorairesAffectation.jours)
		{
			const arriveeBrute = champsHorairesAffectation.querySelector(`[data-date="${dateStr}"][data-field="arrivee"]`).value.trim();
			const departBrut = champsHorairesAffectation.querySelector(`[data-date="${dateStr}"][data-field="depart"]`).value.trim();
			const arrivee = arriveeBrute ? normaliserHeureSaisie(arriveeBrute) : "";
			const depart = departBrut ? normaliserHeureSaisie(departBrut) : "";
			if (!arrivee || !depart || depart <= arrivee)
			{
				afficherToast(`Horaires invalides pour ${libelleJourEffectif(dateStr)}. Le départ doit être après l’arrivée.`, true);
				return;
			}
			horaires.push({ date: dateStr, heure_arrivee: arrivee, heure_depart: depart });
		}
		try
		{
			await apiFetch(`/api/affectations/${contexteHorairesAffectation.affectation.id}/`, {
				method: "PATCH", body: JSON.stringify({ horaires, type_affectation: caseAffectationFlottante?.checked ? "flottant" : "groupe" }),
			});
			const calendarEnregistre = contexteHorairesAffectation.calendar;
			fermerModal(modalHorairesAffectation);
			afficherToast(caseAffectationFlottante?.checked ? "Animateur enregistré comme flottant." : "Affectation enregistrée.");
			PlanningData.invalidateWeekEvents(calendarEnregistre.view?.activeStart, calendarEnregistre.view?.activeEnd);
			calendars.forEach((item) => item.refetchEvents());
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "Les horaires n’ont pas pu être enregistrés."), true);
		}
	});

	boutonSupprimerAffectation?.addEventListener("click", async () =>
	{
		if (!contexteHorairesAffectation) return;
		const affectationSupprimee = contexteHorairesAffectation.affectation;
		const calendarSupprime = contexteHorairesAffectation.calendar;
		const etaitFlottante = eventEstFlottant(affectationSupprimee);
		try
		{
			await apiFetch(`/api/affectations/${affectationSupprimee.id}/`, { method: "DELETE" });
			PlanningData.invalidateWeekEvents();
			affectationSupprimee.remove();
			if (etaitFlottante)
			{
				const centre = calendarSupprime.centrePlanning;
				if (centre)
				{
					const ligne = document.querySelector(`.centre-planning-group[data-centre-id="${centre.id}"] .planning-floating-lane`);
					// La ligne flottante vit hors de FullCalendar : elle doit être
					// reconstruite explicitement après la suppression côté serveur.
					rafraichirLigneAnimateursFlottants(centre, ligne);
				}
			}
			fermerModal(modalHorairesAffectation);
			afficherToast("Affectation supprimée.");
			rafraichirAnimateursSemaine();
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "La suppression a échoué."), true);
		}
	});

	function ouvrirSaisieHorairesGroupe(calendar)
	{
		const evenement = calendar.evenementPlanning;
		const lignes = [];
		calendar.getEvents().filter((affectation) => affectation.display !== "background").forEach((affectation) =>
		{
			const debut = new Date(Math.max(affectation.start.getTime(), calendar.view.activeStart.getTime()));
			const finAffectation = affectation.end || new Date(affectation.start.getTime() + 86400000);
			const fin = new Date(Math.min(finAffectation.getTime(), calendar.view.activeEnd.getTime()));
			for (let curseur = debut; curseur < fin; curseur = new Date(curseur.getFullYear(), curseur.getMonth(), curseur.getDate() + 1))
			{
				const date = formatDateLocal(curseur);
				const horaire = affectation.extendedProps.horaires?.[date] || {};
				lignes.push({
					affectationId: affectation.id,
					animateur: affectation.extendedProps.animateur_nom || affectation.title,
					date,
					heureArrivee: horaire.heure_arrivee || "",
					heureDepart: horaire.heure_depart || "",
				});
			}
		});
		lignes.sort((a, b) => a.date.localeCompare(b.date) || a.animateur.localeCompare(b.animateur, "fr"));
		contexteHorairesGroupe = { calendar, evenement, lignes };
		titreHorairesGroupe.textContent = `Horaires des animateurs — ${evenement.nom}`;
		champsHorairesGroupe.innerHTML = lignes.map((ligne, index) => `
			<div class="effectif-enfants-row horaires-affectation-row">
				<span><strong>${escapeHtml(ligne.animateur)}</strong><small>${escapeHtml(libelleJourEffectif(ligne.date))}</small></span>
				<label><small>Arrivée</small><input type="text" inputmode="decimal" data-index="${index}" data-field="arrivee" value="${escapeHtml(heurePourSaisie(ligne.heureArrivee))}" placeholder="7.35" required></label>
				<label><small>Départ</small><input type="text" inputmode="decimal" data-index="${index}" data-field="depart" value="${escapeHtml(heurePourSaisie(ligne.heureDepart))}" placeholder="18.35" required></label>
			</div>`).join("") || '<p class="empty-note">Aucun animateur n’est affecté à ce groupe cette semaine.</p>';
		ouvrirModal(modalHorairesGroupe);
	}

	formulaireHorairesGroupe?.addEventListener("submit", async (event) =>
	{
		event.preventDefault();
		if (!contexteHorairesGroupe) return;
		const horaires = [];
		for (let index = 0; index < contexteHorairesGroupe.lignes.length; index += 1)
		{
			const ligne = contexteHorairesGroupe.lignes[index];
			const arrivee = normaliserHeureSaisie(champsHorairesGroupe.querySelector(`[data-index="${index}"][data-field="arrivee"]`).value.trim());
			const depart = normaliserHeureSaisie(champsHorairesGroupe.querySelector(`[data-index="${index}"][data-field="depart"]`).value.trim());
			if (!arrivee || !depart || depart <= arrivee)
			{
				afficherToast(`Horaires invalides pour ${ligne.animateur}, ${libelleJourEffectif(ligne.date)}.`, true);
				return;
			}
			horaires.push({ affectation_id: ligne.affectationId, date: ligne.date, heure_arrivee: arrivee, heure_depart: depart });
		}
		try
		{
			const resultat = await apiFetch(`/api/groupes/${contexteHorairesGroupe.evenement.id}/horaires-affectations/`, {
				method: "POST", body: JSON.stringify({ horaires }),
			});
			fermerModal(modalHorairesGroupe);
			PlanningData.invalidateWeekEvents(
				contexteHorairesGroupe.calendar.view?.activeStart,
				contexteHorairesGroupe.calendar.view?.activeEnd
			);
			contexteHorairesGroupe.calendar.refetchEvents();
			afficherToast(`${resultat.nombre} horaire${resultat.nombre > 1 ? "s" : ""} appliqué${resultat.nombre > 1 ? "s" : ""}.`);
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "Les horaires du groupe n’ont pas pu être enregistrés."), true);
		}
	});

	formulaireEncadrementSpecial?.addEventListener("submit", async (event) =>
	{
		event.preventDefault();
		if (!contexteEncadrementSpecial) return;
		const ratiosEncadrement = Array.from(champsEncadrementSpecial.querySelectorAll('input[data-field="ratio-special"]')).map((input) => ({
			date: input.dataset.date,
			ratio: input.value.trim() === "" ? null : Number.parseInt(input.value, 10),
		}));
		try
		{
			await apiFetch(`/api/groupes/${contexteEncadrementSpecial.evenement.id}/effectifs-enfants/`, {
				method: "POST", body: JSON.stringify({ ratios_encadrement: ratiosEncadrement }),
			});
			const calendarEnregistre = contexteEncadrementSpecial.calendar;
			fermerModal(modalEncadrementSpecial);
			afficherToast("Encadrement spécial enregistré.");
			PlanningData.invalidateWeekEffectifs(calendarEnregistre.view?.activeStart, calendarEnregistre.view?.activeEnd);
			await chargerEffectifsEnfants(calendarEnregistre);
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "L’encadrement spécial n’a pas pu être enregistré."), true);
		}
	});

	formulaireEffectifsEnfants?.addEventListener("submit", async (event) =>
	{
		event.preventDefault();
		if (!contexteEffectifsEnfants) return;
		const effectifs = Array.from(champsEffectifsEnfants.querySelectorAll('input[data-field="nombre"]')).map((input) => ({
			date: input.dataset.date,
			nombre: Number.parseInt(input.value || "0", 10) || 0,
		}));
		try
		{
			await apiFetch(`/api/groupes/${contexteEffectifsEnfants.evenement.id}/effectifs-enfants/`, {
				method: "POST", body: JSON.stringify({ effectifs }),
			});
			const calendarEnregistre = contexteEffectifsEnfants.calendar;
			const valeursExistantes = contexteEffectifsEnfants.evenement.effectifsEnfants || {};
			contexteEffectifsEnfants.evenement.effectifsEnfants = Object.fromEntries(
				effectifs
					.filter((item) => item.nombre > 0
						|| valeursExistantes[item.date]?.ratioEncadrementExceptionnel
						|| valeursExistantes[item.date]?.heureArrivee)
					.map((item) => [item.date, {
						...normaliserEffectifJour(valeursExistantes[item.date], contexteEffectifsEnfants.evenement.enfants_par_animateur_defaut),
						nombre: item.nombre,
					}])
			);
			// Affichage immédiat, puis relecture de la base : l'utilisateur voit le
			// résultat sans attendre et le cache local ne peut pas masquer un échec.
			rafraichirAffichageEffectifsEnfants(calendarEnregistre);
			fermerModal(modalEffectifsEnfants);
			afficherToast("Effectifs enfants enregistrés.");
			PlanningData.invalidateWeekEffectifs(calendarEnregistre.view?.activeStart, calendarEnregistre.view?.activeEnd);
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
			contentHeight: "auto",
			locale: "fr",
			firstDay: 1,
			hiddenDays: joursCachesFullCalendar(evenement),
			editable: estModeAffectations(),
			droppable: estModeAffectations(),
			// La sélection de plage est réservée aux affectations. Dans l'onglet
			// Effectifs, elle empêcherait de cliquer les valeurs éditables.
			selectable: estModeAffectations(),

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
			eventClassNames: function (arg)
			{
				return eventEstFlottant(arg.event) ? ["is-floating-assignment"] : [];
			},
			expandRows: false,
			dayMaxEvents: false,
			headerToolbar: false,
			footerToolbar: false,

			events: function (fetchInfo, successCallback, failureCallback)
			{
				PlanningData.fetchWeekEvents(fetchInfo.startStr, fetchInfo.endStr)
					.then((events) => successCallback((events || []).filter(
						(item) => Number(item.extendedProps?.evenement_id || item.extendedProps?.groupe_id)
							=== Number(evenement.id)
					)))
					.catch(failureCallback);
			},

				eventsSet: function ()
			{
				window.setTimeout(() => calendars
					.filter((item) => Number(item.centrePlanning?.id) === Number(centre.id))
					.forEach((item) => rafraichirAffichageEffectifsEnfants(item)), 0);
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
				if (!estModeAffectations()) return;
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
				if (!estModeAffectations()) return false;

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
				if (!estModeAffectations()) { info.event.remove(); return; }
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

			eventDrop: function (info) { if (estModeAffectations()) updateAffectation(info, centre, evenement); },
			eventResize: function (info) { if (estModeAffectations()) updateAffectation(info, centre, evenement); },

			eventClick: function (info)
			{
				if (!estModeAffectations()) return;
				if (info.event.display === "background") return;
				ouvrirSaisieHorairesAffectation(info, calendar);
			},
		});

		calendar.centrePlanning = centre;
		evenement.effectifsEnfants = evenement.effectifsEnfants || {};
		calendar.evenementPlanning = evenement;
		calendar.render();
		// FullCalendar termine le montage des cellules après `datesSet` selon
		// le navigateur. Un second passage se base sur les cellules réellement
		// visibles et retire les calendriers dont tous les jours sont fermés.
		window.setTimeout(() =>
		{
			const vue = calendar.view;
			mettreAJourVisibiliteCalendriers(vue ? { start: vue.activeStart, end: vue.activeEnd } : null);
		}, 80);

		// datesSet est normalement déclenché par render(), mais ce chargement
		// explicite couvre aussi les rendus initiaux différés/masqués de FullCalendar.
		window.setTimeout(() => chargerEffectifsEnfants(calendar), 0);
		return calendar;
	}


	function rafraichirLigneAnimateursFlottants(centre, ligne)
	{
		if (!ligne) return;
		const calendarReference = calendars.find((calendar) => Number(calendar.centrePlanning?.id) === Number(centre.id));
		if (!calendarReference?.view?.activeStart || !calendarReference?.view?.activeEnd) return;
		const debut = calendarReference.view.activeStart;
		const fin = calendarReference.view.activeEnd;
		const numeroRequete = (ligne.floatingRequestVersion || 0) + 1;
		ligne.floatingRequestVersion = numeroRequete;
		PlanningData.fetchWeekEvents(debut.toISOString(), fin.toISOString()).then((events) =>
		{
			if (numeroRequete !== ligne.floatingRequestVersion) return;
			const flottants = (events || []).filter((event) =>
				eventEstFlottant(event)
				&& Number(event.extendedProps?.centre_id) === Number(centre.id)
			);
			// Retire les anciennes valeurs de ce lieu avant de recopier la semaine
			// courante, notamment après suppression ou déplacement.
			for (const [id, event] of affectationsFlottantesParId)
			{
				if (Number(event.extendedProps?.centre_id) === Number(centre.id))
					affectationsFlottantesParId.delete(id);
			}
			flottants.forEach((event) => affectationsFlottantesParId.set(String(event.id), event));
			const jours = [];
			for (let curseur = new Date(debut); curseur < fin; curseur = new Date(curseur.getFullYear(), curseur.getMonth(), curseur.getDate() + 1))
			{
				jours.push(formatDateLocal(curseur));
			}
			ligne.querySelector('.planning-floating-days').innerHTML = jours.map((dateStr) =>
			{
				const affectationJour = flottants.find((event) => evenementActifLeJour(event, dateStr));
				const libelleAction = affectationJour ? "Modifier l’animateur flottant" : "Ajouter un animateur flottant";
				return `<div class="planning-floating-day${affectationJour ? ' is-occupied' : ''}" data-date="${dateStr}" data-centre-id="${centre.id}" role="button" tabindex="0" title="${libelleAction} le ${escapeHtml(libelleDate(dateStr))}" aria-label="${libelleAction} le ${escapeHtml(libelleDate(dateStr))}">
					${affectationJour ? `<button type="button" class="planning-floating-person" data-affectation-id="${affectationJour.id}" style="--floating-bg:${escapeHtml(affectationJour.backgroundColor || '#eef2ff')};--floating-border:${escapeHtml(affectationJour.borderColor || '#64748b')}">${escapeHtml((affectationJour.title || '').replace(/^↔\s*/, ''))}</button>` : '<span class="planning-floating-tooltip" aria-hidden="true">Flottant</span>'}
				</div>`;
			}).join('');
			ligne.hidden = false;
			calendars
				.filter((calendar) => Number(calendar.centrePlanning?.id) === Number(centre.id))
				.forEach((calendar) => rafraichirAffichageEffectifsEnfants(calendar));
		}).catch(() => { ligne.hidden = false; });
	}

	function ouvrirAffectationFlottanteDepuisLigne(affectationId)
	{
		for (const calendar of calendars)
		{
			const event = calendar.getEventById(String(affectationId));
			if (!event) continue;
			ouvrirSaisieHorairesAffectation({ event }, calendar);
			return;
		}

		const brut = affectationsFlottantesParId.get(String(affectationId));
		if (!brut) return;
		const calendar = calendars.find((item) => Number(item.centrePlanning?.id) === Number(brut.extendedProps?.centre_id));
		if (!calendar) return;
		const event = {
			id: String(brut.id),
			title: brut.title || '',
			startStr: brut.start,
			endStr: brut.end,
			extendedProps: brut.extendedProps || {},
			remove() { affectationsFlottantesParId.delete(String(brut.id)); },
		};
		ouvrirSaisieHorairesAffectation({ event }, calendar);
	}

	function ajouterCentreAuPlanning(centre, conteneurLigne)
	{
		const evenements = (centre.evenements || []).filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0);

		const groupe = document.createElement("section");
		groupe.classList.add("centre-planning-group", "calendar-site-card");
		groupe.dataset.centreId = centre.id;
		groupe.style.setProperty("--centre-color", centre.couleur);
		groupe.innerHTML = `
			<header class="centre-planning-header calendar-site-header" title="Maintenir et glisser pour déplacer ce centre">
				<div class="centre-planning-title calendar-site-title">
					<div class="calendar-site-identity">
						<span class="centre-planning-code calendar-site-code">${escapeHtml(centre.code || "")}</span>
						<h2 class="calendar-site-name">${escapeHtml(centre.nom)}</h2>
					</div>
				</div>
				<div class="centre-planning-actions calendar-site-actions">
					<span class="centre-evenements-count calendar-site-count">${evenements.length} groupe${evenements.length > 1 ? "s" : ""}</span>
					<button class="planning-centre-close" type="button" data-centre-action="remove" aria-label="Fermer le centre ${escapeHtml(centre.nom)}" title="Fermer ce centre">×</button>
				</div>
			</header>
			<section class="planning-floating-lane" aria-label="Animateur flottant">
				<span class="planning-floating-label" aria-hidden="true">Flottant</span>
				<div class="planning-floating-days"></div>
			</section>
			<div class="evenement-calendars calendar-group-list"></div>
			<p class="calendar-site-empty" ${evenements.length ? "hidden" : ""}>Aucun groupe ouvert cette semaine.</p>
			<footer class="centre-effectifs-summary" aria-live="polite"></footer>`;

		(conteneurLigne || calendarsContainer).appendChild(groupe);
		attacherSurvolCentre(groupe, centre.id);

		const zoneEvenements = groupe.querySelector(".evenement-calendars");
		const ligneFlottants = groupe.querySelector(".planning-floating-lane");
		ligneFlottants?.addEventListener("click", (event) =>
		{
			const bouton = event.target.closest("[data-affectation-id]");
			if (bouton)
			{
				ouvrirAffectationFlottanteDepuisLigne(bouton.dataset.affectationId);
				return;
			}
			const cellule = event.target.closest(".planning-floating-day");
			if (!cellule) return;
			if (cellule.classList.contains("is-occupied")) return;
			if (cellule.dataset.ignoreNextClick === "1")
			{
				delete cellule.dataset.ignoreNextClick;
				return;
			}
			if (!animateurActif)
			{
				afficherToast("Sélectionne un animateur dans la liste, puis clique dans la case Flottant du jour.", true);
				return;
			}
			creerAffectationFlottanteDepuisJour(animateurActif, centre, cellule.dataset.date, cellule)
				.then(() =>
				{
					document.querySelectorAll(".animateur.selected").forEach((el) => el.classList.remove("selected"));
					animateurActif = null;
					effacerDisponibilitesAffichees();
				})
				.catch((err) => afficherToast(erreurMessage(err, "Cette affectation flottante n'a pas pu être enregistrée."), true));
		});
		ligneFlottants?.addEventListener("keydown", (event) =>
		{
			if (event.key !== "Enter" && event.key !== " ") return;
			const cellule = event.target.closest(".planning-floating-day");
			if (!cellule) return;
			event.preventDefault();
			cellule.click();
		});
		zoneEvenements.dataset.visibleGroups = String(evenements.length);
		zoneEvenements.style.setProperty("--planning-visible-group-count", String(Math.max(1, evenements.length)));
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
						<div><h3 class="calendar-group-name">${escapeHtml(evenement.nom)}</h3></div>
					</div>
					<div class="evenement-calendar-meta calendar-group-meta">
						<span class="planning-objectif-groupe">Objectif ${escapeHtml(evenement.effectif_cible)}</span>
						<div class="planning-group-hours-actions">
							<button class="btn btn-secondary btn-horaires-groupe" type="button" title="Remplir les horaires de tous les animateurs du groupe">◷ Horaires</button>
						</div>
						<div class="planning-effectifs-actions">
							<button class="btn btn-secondary btn-effectifs-enfants" type="button">Effectifs</button>
							<button class="btn btn-ghost btn-encadrement-special" type="button">Encadrement spécial</button>
						</div>
					</div>
				</header>
				<div class="calendar shared-calendar"></div>`;

			zoneEvenements.appendChild(card);
			const calendar = creerCalendar(centre, evenement, card);
			card.querySelector(".btn-effectifs-enfants").addEventListener("click", () => ouvrirSaisieEffectifsEnfants(calendar));
			card.querySelector(".btn-encadrement-special").addEventListener("click", () => ouvrirSaisieEncadrementSpecial(calendar));
			card.querySelector(".btn-horaires-groupe").addEventListener("click", () => ouvrirSaisieHorairesGroupe(calendar));
			calendars.push(calendar);
			calendar.on("eventsSet", () => rafraichirLigneAnimateursFlottants(centre, ligneFlottants));
		});
		window.setTimeout(() => rafraichirLigneAnimateursFlottants(centre, ligneFlottants), 0);

		return groupe;
	}

	let rafMiseAJourCalendriers = null;

	function mettreAJourDimensionsCalendriers()
	{
		if (rafMiseAJourCalendriers) cancelAnimationFrame(rafMiseAJourCalendriers);
		rafMiseAJourCalendriers = requestAnimationFrame(() =>
		{
			calendars.forEach((calendar) =>
			{
				const card = calendar.el?.closest(".evenement-calendar-card");
				if (card)
				{
					const largeur = card.getBoundingClientRect().width;
					card.classList.toggle("planning-calendar-tight", largeur < 520);
					card.classList.toggle("planning-calendar-ultra-tight", largeur < 340);
				}
				calendar.updateSize();
			});
			rafMiseAJourCalendriers = null;
		});
	}

	function chargerCentres()
	{
		return PlanningData.fetchCentresWithGroups()
			.then((centres) => (centres || []).map((centre) => ({
				...centre,
				evenements: (centre.evenements || []).map((evenement) => ({
					...evenement,
					effectifsEnfants: {},
				})),
			})))
			.then((centres) =>
			{
				centresPlanning = centres;
				centresFiltresCharges = true;
				rafraichirFiltresAnimateurs(false);
				calendars.splice(0).forEach((calendar) => calendar.destroy());
				calendarsContainer.innerHTML = "";

				if (centres.length === 0)
				{
					dispositionCentres = [];
					calendarsContainer.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant. Ajoute-en un depuis Gestion.</p>';
					mettreAJourBarreCentres();
					return;
				}

				dispositionCentres = chargerDispositionCentres(centres);
				rendreDispositionCentres({ persister: false });
				const periodes = periodesOuvertesPlanning();
				const dateValide = datePeriodeCourante && periodes.some(
					(periode) => periode.debut <= datePeriodeCourante && periode.fin >= datePeriodeCourante
				);
				if (!dateValide && periodes.length)
				{
					const aujourdHui = formatDateLocal(new Date());
					const ouverte = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
					const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
					datePeriodeCourante = ouverte ? aujourdHui : (prochaine || periodes[0]).debut;
				}

				if (!calendars.length)
				{
					// Même avec tous les centres fermés, la semaine choisie reste mémorisée.
					mettreAJourLibelleSemaine();
					return;
				}
				if (datePeriodeCourante)
				{
					allerDateTous(datePeriodeCourante, { rafraichirAnimateurs: false });
				}

				if (centreDemande)
				{
					const centreCible = calendarsContainer.querySelector(`.centre-planning-group[data-centre-id="${centreDemande}"]`);
					if (centreCible)
					{
						centreCible.classList.add("planning-centre-cible");
						window.setTimeout(() => centreCible.scrollIntoView({ block: "start", behavior: "smooth" }), 80);
					}
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
	// Barre d'outils commune : navigation, vue et actions groupées.
	// Toutes les calendriers actuellement visibles restent synchronisés
	// en itérant simplement sur le tableau `calendars`.
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
		WeekPicker.get("planning-period-nav")?.setActiveDate(dateReference, { persist: false });
		if (!toolbarLabel) return;
		const periode = dateReference ? periodePourDate(dateReference) : null;
		toolbarLabel.textContent = periode
			? libellePeriodeAvecDates(periode)
			: "Aucune période ouverte";
	}

	function allerDateTous(dateStr, { rafraichirAnimateurs = true, persister = true } = {})
	{
		datePeriodeCourante = dateStr;
		if (persister) WeekPicker.setPersistedDate(dateStr);
		calendars.forEach((calendar) => calendar.gotoDate(dateStr));
		mettreAJourLibelleSemaine();
		if (rafraichirAnimateurs) rafraichirAnimateursSemaine();
	}

	function naviguerVersPeriode(direction)
	{
		const periodes = periodesOuvertesPlanning();
		if (!periodes.length) return;
		const dateCourante = datePeriodeCourante
			|| (calendars[0] ? formatDateLocal(calendars[0].getDate()) : periodes[0].debut);
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
			"Supprimer les affectations À VENIR de cette semaine (à partir d'aujourd'hui), dans tous les centres ? Les jours déjà passés ne sont jamais touchés. Cette action est irréversible."
		);
		if (!confirmation) return;

		apiFetch(`/api/planning/plage/?debut=${formatDateLocal(lundi)}&fin=${formatDateLocal(samedi)}`, { method: "DELETE" })
			.then((data) =>
			{
				afficherToast(`${data.supprimees} affectation(s) supprimée(s).`);
				PlanningData.invalidateWeekEvents();

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
				rafraichirAnimateursSemaine();
			})
			.catch((err) => afficherToast(erreurMessage(err, "La suppression a échoué."), true));
	});

	// -----------------------------------------------------------------
	// Liste des animateurs (badges de type "badge de colo")
	// -----------------------------------------------------------------

	// Construit une ligne compacte mais informative : identité, centre préféré,
	// qualifications principales et état sur la semaine visible.

	function creerChipAnimateur(animateur)
	{
		const div = document.createElement("div");
		div.classList.add("animateur");
		div.dataset.animateurId = animateur.id;

		const couleurStatut = animateur.couleur_statut || "#718096";
		div.dataset.couleur = couleurStatut;
		div.style.setProperty("--animateur-color", couleurStatut);
		div.style.setProperty("--animateur-text", animateur.couleur_texte_statut || ColorUtils.texteLisible(couleurStatut));

		const contenu = document.createElement("span");
		contenu.classList.add("anim-content");

		const ligneNom = document.createElement("span");
		ligneNom.classList.add("anim-name-row");

		const symbolesIcones = {
			diplome: "🎓",
			secours: "✚",
			baignade: "🛟",
			conduite: "🚐",
			sport: "⚽",
			direction: "★",
			repas: "🍴",
		};
		const iconesUniques = new Map();
		(animateur.qualification_icones || []).forEach((qualification) =>
		{
			if (qualification?.icone && symbolesIcones[qualification.icone] && !iconesUniques.has(qualification.icone))
			{
				iconesUniques.set(qualification.icone, qualification.nom || "Qualification");
			}
		});
		if (iconesUniques.size)
		{
			const icones = document.createElement("span");
			icones.classList.add("anim-qualification-icons");
			[...iconesUniques.entries()].slice(0, 3).forEach(([icone, libelle]) =>
			{
				const badge = document.createElement("span");
				badge.classList.add("anim-qualification-icon");
				badge.textContent = symbolesIcones[icone];
				badge.title = libelle;
				badge.setAttribute("aria-label", libelle);
				icones.appendChild(badge);
			});
			ligneNom.appendChild(icones);
		}

		const name = document.createElement("span");
		name.classList.add("anim-name");
		name.textContent = `${animateur.prenom} ${animateur.nom}`;
		ligneNom.appendChild(name);
		contenu.appendChild(ligneNom);

		const details = document.createElement("span");
		details.classList.add("anim-details");
		const statutNom = animateur.statut_principal?.nom || "Sans statut";
		const centre = animateur.centre_prefere?.code || "";
		details.textContent = [statutNom, centre].filter(Boolean).join(" · ");
		contenu.appendChild(details);
		div.appendChild(contenu);

		const infos = [animateur.telephone || null, animateur.email || null].filter(Boolean).join(" · ");
		if (infos) div.title = infos;


		["pointerdown", "mousedown", "touchstart"].forEach((eventName) =>
		{
			div.addEventListener(eventName, () => afficherDisponibilitesPendantDrag(animateur), { passive: true });
		});

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
		const diplomesAnimateur = new Set((animateur.diplome_ids || animateur.qualification_ids || []).map(Number));
		const statutsAnimateur = new Set((animateur.statut_ids || []).map(Number));
		const possedeTousLesDiplomes = [...filtresQualificationsAnimateurs]
			.every((qualificationId) => diplomesAnimateur.has(qualificationId));
		if (!possedeTousLesDiplomes) return false;
		const possedeTousLesStatuts = [...filtresStatutsAnimateurs]
			.every((statutId) => statutsAnimateur.has(statutId));
		if (!possedeTousLesStatuts) return false;

		if (filtresCentresAnimateurs.size > 0)
		{
			const centrePrefereId = Number(animateur.centre_prefere?.id);
			if (!filtresCentresAnimateurs.has(centrePrefereId)) return false;
		}

		// Source unique : le serveur calcule la situation sur tous les jours
		// réellement ouverts, y compris dans les centres masqués. On ne dépend
		// donc plus de l'ordre de chargement des calendriers FullCalendar.
		const situation = animateur.situation_semaine || {};
		const encorePlacable = situation.encore_placable === true;
		const disponible = situation.disponible === true;
		const affecte = situation.affecte === true;

		if (filtreSituationAnimateursValeur === "placable" && !encorePlacable) return false;
		if (filtreSituationAnimateursValeur === "disponible" && !disponible) return false;
		if (filtreSituationAnimateursValeur === "affecte" && !affecte) return false;
		if (filtreSituationAnimateursValeur === "indisponible" && disponible) return false;
		return true;
	}

	function sauvegarderFiltresAnimateurs()
	{
		localStorage.setItem("planning-filtres-statuts", JSON.stringify([...filtresStatutsAnimateurs]));
		localStorage.setItem("planning-filtres-qualifications", JSON.stringify([...filtresQualificationsAnimateurs]));
		localStorage.setItem("planning-filtres-centres-preferes", JSON.stringify([...filtresCentresAnimateurs]));
	}

	function nombreFiltresAnimateursActifs()
	{
		return filtresStatutsAnimateurs.size + filtresQualificationsAnimateurs.size + filtresCentresAnimateurs.size
			+ (filtreSituationAnimateursValeur !== "placable" ? 1 : 0);
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
			const statuts = qualificationsPlanning.filter((qualification) => qualification.est_statut);
			const diplomes = qualificationsPlanning.filter((qualification) => !qualification.est_statut);
			const idsStatuts = new Set(statuts.map((qualification) => Number(qualification.id)));
			const idsDiplomes = new Set(diplomes.map((qualification) => Number(qualification.id)));

			// Migre silencieusement d'anciens filtres qui mélangeaient statuts et diplômes.
			[...filtresQualificationsAnimateurs].forEach((id) =>
			{
				if (idsStatuts.has(id))
				{
					filtresQualificationsAnimateurs.delete(id);
					filtresStatutsAnimateurs.add(id);
				}
			});
			filtresStatutsAnimateurs = new Set([...filtresStatutsAnimateurs].filter((id) => idsStatuts.has(id)));
			filtresQualificationsAnimateurs = new Set([...filtresQualificationsAnimateurs].filter((id) => idsDiplomes.has(id)));

			StaffFilterUI.renderOptions(filtresStatutsConteneur, statuts, {
				selected: filtresStatutsAnimateurs,
				emptyText: "Aucun statut",
				name: "planning_filter_statut",
				showColor: true,
				onChange: (input) =>
				{
					const id = Number(input.value);
					if (input.checked) filtresStatutsAnimateurs.add(id);
					else filtresStatutsAnimateurs.delete(id);
					sauvegarderFiltresAnimateurs();
					rendreListeAnimateurs();
				},
			});
			StaffFilterUI.renderOptions(filtresQualificationsConteneur, diplomes, {
				selected: filtresQualificationsAnimateurs,
				emptyText: "Aucun diplôme",
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
	}

	if (rechercheAnimateursInput)
	{
		rechercheAnimateursInput.addEventListener("input", () =>
		{
			rechercheAnimateurs = rechercheAnimateursInput.value.trim().toLocaleLowerCase("fr");
			rendreListeAnimateurs();
		});
	}

	// (Re)charge la liste des animateurs dans la barre latérale. Appelée
	// au chargement initial, et à nouveau après un ajout/suppression.
	function chargerAnimateurs()
	{
		const numeroRequete = ++requeteAnimateursCourante;
		const plage = PlanningData.weekRange(datePeriodeCourante || new Date());
		const query = new URLSearchParams({
			include_affectations: "1",
			format: "planning",
			debut: plage.debut,
			fin: plage.fin,
		});
		return apiFetch(`/api/animateurs/?${query.toString()}`).then((animateurs) =>
		{
			if (numeroRequete !== requeteAnimateursCourante) return false;
			animateursPlanning = animateurs;
			return true;
		});
	}

	function rafraichirAnimateursSemaine()
	{
		return chargerAnimateurs().then((appliquer) =>
		{
			if (appliquer === false) return;
			rendreListeAnimateurs();
		}).catch((err) =>
		{
			afficherToast(erreurMessage(err, "La liste des animateurs n'a pas pu être actualisée."), true);
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

	filtreSituationAnimateurs?.addEventListener("change", () =>
	{
		filtreSituationAnimateursValeur = filtreSituationAnimateurs.value;
		sauvegarderFiltresAnimateurs();
		rendreListeAnimateurs();
	});

	if (boutonEffacerFiltresAnimateurs)
	{
		boutonEffacerFiltresAnimateurs.addEventListener("click", () =>
		{
			filtresStatutsAnimateurs.clear();
			filtresQualificationsAnimateurs.clear();
			filtresCentresAnimateurs.clear();
			filtreSituationAnimateursValeur = "placable";
			if (filtreSituationAnimateurs) filtreSituationAnimateurs.value = "placable";
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
		const estPrefere = (animateur.centres_preferes || []).some((c) => Number(c.id) === Number(centre.id));
		if (estPrefere) return "#3ba55c";
		const estInterdit = (animateur.centres_interdits || []).some((c) => Number(c.id) === Number(centre.id));
		if (estInterdit) return "#dc2626";
		return "#f59e0b"; // neutre : autorisé sans priorité
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

	initFermetureModal(modalEffectifsEnfants);
	initFermetureModal(modalEncadrementSpecial);
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
	]).then(() => chargerAnimateurs()).then(() =>
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

	// Les cases « Flottant » ne sont pas des calendriers FullCalendar. On
	// intercepte donc le relâchement du pointeur pour accepter directement un
	// animateur glissé depuis la liste dans la case du lieu et du jour.
	document.addEventListener("pointermove", (event) =>
	{
		document.querySelectorAll(".planning-floating-day.is-drag-over").forEach((cellule) => cellule.classList.remove("is-drag-over"));
		if (!animateurDragPreview) return;
		const cible = document.elementFromPoint(event.clientX, event.clientY)?.closest(".planning-floating-day");
		if (cible) cible.classList.add("is-drag-over");
	}, { passive: true });

	document.addEventListener("pointerup", (event) =>
	{
		const animateur = animateurDragPreview;
		const cible = document.elementFromPoint(event.clientX, event.clientY)?.closest(".planning-floating-day");
		document.querySelectorAll(".planning-floating-day.is-drag-over").forEach((cellule) => cellule.classList.remove("is-drag-over"));
		if (!animateur || !cible || cible.classList.contains("is-saving")) return;
		if (cible.classList.contains("is-occupied"))
		{
			afficherToast("La case flottante de ce jour est déjà occupée.", true);
			return;
		}
		const centre = centresPlanning.find((item) => Number(item.id) === Number(cible.dataset.centreId));
		if (!centre) return;
		cible.dataset.ignoreNextClick = "1";
		creerAffectationFlottanteDepuisJour(animateur, centre, cible.dataset.date, cible)
			.catch((err) => afficherToast(erreurMessage(err, "Cette affectation flottante n'a pas pu être enregistrée."), true));
	}, true);

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

		const centresHtml = centresPlanning.map((centre) =>
		{
			const evenements = (centre.evenements || []).filter((groupe) => groupe.permanent || (groupe.periodes || []).length > 0);
			if (!evenements.length) return "";

			const evenementsHtml = evenements.map((evenement) => `
				<div class="auto-evenement-bloc">
					<div class="auto-evenement-entete">
						<div>
							<strong>${escapeHtml(evenement.nom)}</strong>
							<span class="auto-evenement-periode">${escapeHtml(periodeEvenementLibelle(evenement))}</span>
							${(evenement.qualifications_libelle || []).length ? `<span class="auto-evenement-periode">Diplômes / statuts : ${escapeHtml(evenement.qualifications_libelle.join(", "))}</span>` : ""}
						</div>
						<div class="auto-centre-total auto-centre-total-readonly">
							<span>Personnel / jour</span>
							<strong>${Math.max(0, Number(evenement.effectif_cible) || 0)}</strong>
						</div>
					</div>
				</div>`).join("");

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
			<div class="auto-remplissage-regles">
				<strong>Règles utilisées</strong>
				<ul>
					<li>statuts requis couverts en premier ;</li>
					<li>diplômes précis couverts ensuite ;</li>
					<li>postes restants attribués selon l’affinité avec le groupe ;</li>
					<li>disponibilités et absence de double affectation ;</li>
					<li>lieux interdits exclus et préférences de lieu respectées ;</li>
					<li>même équipe conservée sur la semaine et expérience passée dans le groupe.</li>
				</ul>
			</div>
			<div class="auto-centres-liste">${centresHtml}</div>
			<div class="edit-actions">
				<button class="btn btn-primary" id="auto-valider" type="button">Remplir la semaine</button>
				<button class="btn btn-ghost" data-modal-close type="button">Annuler</button>
			</div>`;

		modalAutoContent.querySelector("#auto-valider").addEventListener("click", () =>
		{
			if (!confirm("Remplir automatiquement tous les groupes du lundi au vendredi ? Les affectations existantes de ces jours seront remplacées.")) return;
			lancerRemplissageAuto(modalAutoContent.querySelector("#auto-valider"));
		});

		ouvrirModal(modalAuto);
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

	document.addEventListener("effectifs-enfants-importes", async (event) =>
	{
		// L'import Excel peut toucher plusieurs semaines. Elles sont toutes
		// invalidées et préchargées immédiatement ; la semaine visible est relue
		// en parallèle pour que l'affichage change sans rafraîchir le navigateur.
		const periodesImportees = Array.isArray(event.detail?.periodes)
			? event.detail.periodes.filter((periode) => periode?.debut && periode?.fin)
			: [];
		PlanningData.invalidateWeekEffectifs();
		const prechargement = Promise.allSettled(periodesImportees.map((periode) =>
			PlanningData.fetchWeekEffectifs(periode.debut, periode.fin, { force: true })
		));
		try
		{
			await Promise.all(calendars.map((calendar) => chargerEffectifsEnfants(calendar)));
			centresPlanning.forEach((centre) => mettreAJourTotalEffectifsCentre(centre.id));
			await prechargement;
		}
		catch (err)
		{
			afficherToast(erreurMessage(err, "Les effectifs importés sont enregistrés, mais l’affichage n’a pas pu être actualisé."), true);
		}
	});

	appliquerModePlanning(modePlanning, false);

});
