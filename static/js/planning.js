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
	const aideModePlanning = document.getElementById("planning-mode-help");
	const planningQuery = new URLSearchParams(window.location.search);
	const modeDemande = planningQuery.get("mode");
	let modePlanning = modeDemande === "effectifs" || modeDemande === "affectations"
		? modeDemande
		: (localStorage.getItem("planning-mode") === "effectifs" ? "effectifs" : "affectations");
	const animList = document.getElementById("animateurs-list");
	const filtresQualificationsConteneur = document.getElementById("animateurs-filter-qualifications");
	const filtresCentresConteneur = document.getElementById("animateurs-filter-centres");
	const filtreDisponibiliteAnimateurs = document.getElementById("animateurs-filter-disponibilite");
	const filtreAffectationAnimateurs = document.getElementById("animateurs-filter-affectation");
	const compteurFiltresAnimateurs = document.getElementById("animateurs-filter-count");
	const boutonEffacerFiltresAnimateurs = document.getElementById("animateurs-filter-reset");
	const rechercheAnimateursInput = document.getElementById("animateurs-search-input");
	const compteurAnimateursVisibles = document.getElementById("animateurs-visible-count");
	const toolbarLabel = document.getElementById("toolbar-label");
	const modalEffectifsEnfants = document.getElementById("modal-effectifs-enfants");
	const formulaireEffectifsEnfants = document.getElementById("effectifs-enfants-form");
	const champsEffectifsEnfants = document.getElementById("effectifs-enfants-fields");
	const titreEffectifsEnfants = document.getElementById("effectifs-enfants-title");
	const modalEncadrementSpecial = document.getElementById("modal-encadrement-special");
	const formulaireEncadrementSpecial = document.getElementById("encadrement-special-form");
	const champsEncadrementSpecial = document.getElementById("encadrement-special-fields");
	const titreEncadrementSpecial = document.getElementById("encadrement-special-title");
	let contexteEffectifsEnfants = null;
	let contexteEncadrementSpecial = null;

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
	let datePeriodeCourante = dateDemandee;

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
		const definirVisibilite = (element, visible) =>
		{
			element.hidden = !visible;
			if (visible) element.style.removeProperty("display");
			else element.style.setProperty("display", "none", "important");
		};

		document.querySelectorAll(".evenement-calendar-card").forEach((card) => {
			const groupe = centresPlanning.flatMap((centre) => centre.evenements || [])
				.find((item) => Number(item.id) === Number(card.dataset.evenementId));
			const cellulesRendues = Array.from(card.querySelectorAll(".fc-daygrid-day[data-date]"));
			const aUnJourOuvertVisible = cellulesRendues.length
				? cellulesRendues.some((cellule) => !cellule.classList.contains("evenement-hors-periode"))
				: Boolean(groupe && groupeOuvertSurPlage(groupe, debut, fin));
			definirVisibilite(card, Boolean(groupe && aUnJourOuvertVisible));
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
			definirVisibilite(bloc, true);

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

	function appliquerModePlanning(nouveauMode, memoriser = true)
	{
		// Les deux onglets réutilisent exactement les mêmes instances et la
		// même géométrie de calendriers. On mémorise donc la position de
		// défilement avant de remplacer uniquement leur contenu visible.
		const scrollTopAvant = calendarsContainer.scrollTop;
		const scrollLeftAvant = calendarsContainer.scrollLeft;
		modePlanning = nouveauMode === "effectifs" ? "effectifs" : "affectations";
		if (memoriser) localStorage.setItem("planning-mode", modePlanning);
		layoutPlanning.dataset.planningMode = modePlanning;
		document.body.classList.toggle("planning-mode-effectifs", estModeEffectifs());
		document.body.classList.toggle("planning-mode-affectations", !estModeEffectifs());
		ongletsPlanning.forEach((onglet) =>
		{
			const actif = onglet.dataset.planningMode === modePlanning;
			onglet.classList.toggle("active", actif);
			onglet.setAttribute("aria-selected", String(actif));
		});
		if (aideModePlanning)
		{
			aideModePlanning.textContent = estModeEffectifs()
				? "Renseignez les enfants prévus et, si nécessaire, un taux d’encadrement particulier pour chaque groupe."
				: "Glissez ou sélectionnez un salarié, puis choisissez ses jours d’affectation.";
		}
		calendars.forEach((calendar) =>
		{
			calendar.setOption("editable", !estModeEffectifs());
			calendar.setOption("droppable", !estModeEffectifs());
			calendar.updateSize();
		});
		centresPlanning.forEach((centre) => mettreAJourTotalEffectifsCentre(centre.id));
		if (estModeEffectifs())
		{
			animateurActif = null;
			animateurDragPreview = null;
			effacerDisponibilitesAffichees();
			nettoyerModePlacementJour();
			document.querySelectorAll(".animateur.selected").forEach((element) => element.classList.remove("selected"));
		}
		window.setTimeout(() =>
		{
			mettreAJourDimensionsCalendriers();
			calendarsContainer.scrollTop = scrollTopAvant;
			calendarsContainer.scrollLeft = scrollLeftAvant;
		}, 20);
	}

	ongletsPlanning.forEach((onglet) => onglet.addEventListener("click", () =>
		appliquerModePlanning(onglet.dataset.planningMode)
	));

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
		const exceptionnel = valeur?.ratioEncadrementExceptionnel ?? valeur?.ratio_encadrement_exceptionnel ?? null;
		return {
			nombre: Number(valeur?.nombre || 0),
			enfantsParAnimateur: Math.max(1, Number(exceptionnel || valeur?.enfantsParAnimateur || valeur?.enfants_par_animateur || ratio)),
			ratioEncadrementExceptionnel: exceptionnel === null || exceptionnel === "" ? null : Math.max(1, Number(exceptionnel)),
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
			cellule.querySelector(".planning-staff-balance")?.remove();
			calendar.el.querySelector(`.fc-col-header-cell[data-date="${dateStr}"] .planning-staff-balance`)?.remove();
			const valeur = normaliserEffectifJour(valeurs[dateStr], calendar.evenementPlanning.enfants_par_animateur_defaut);
			if (!valeur.nombre) return;

			const animateursAffectes = compterAnimateursAffectes(calendar, dateStr);
			const animateursNecessaires = Math.ceil(valeur.nombre / valeur.enfantsParAnimateur);
			const ecart = animateursAffectes - animateursNecessaires;
			let etat = "ok";
			if (ecart < 0) etat = "manque";
			else if (ecart > 0) etat = "surplus";

			const details = `${valeur.nombre} enfant${valeur.nombre > 1 ? "s" : ""} — taux 1/${valeur.enfantsParAnimateur} — ${animateursAffectes} animateur${animateursAffectes > 1 ? "s" : ""} affecté${animateursAffectes > 1 ? "s" : ""} — ${animateursNecessaires} nécessaire${animateursNecessaires > 1 ? "s" : ""}`;

			if (ecart !== 0)
			{
				const indicateur = document.createElement("span");
				indicateur.className = `planning-staff-balance planning-staff-balance--${etat}`;
				indicateur.textContent = ecart > 0 ? `+${ecart}` : String(ecart);
				indicateur.title = details;
				indicateur.setAttribute("aria-label", `${ecart > 0 ? "Sureffectif" : "Sous-effectif"} de ${Math.abs(ecart)} animateur${Math.abs(ecart) > 1 ? "s" : ""}. ${details}`);
				// Placé après les événements, le badge reste sous les animateurs
				// affectés et ne peut plus empiéter sur la date de l'en-tête.
				const evenementsJour = cadre.querySelector(".fc-daygrid-day-events");
				if (evenementsJour) evenementsJour.insertAdjacentElement("afterend", indicateur);
				else cadre.appendChild(indicateur);
			}

			const zone = document.createElement("div");
			zone.className = "planning-effectif-enfants-zone";
			const badge = document.createElement("span");
			badge.className = `planning-effectif-enfants planning-effectif-enfants--${etat}`;
			badge.innerHTML = `
				<span class="planning-effectif-details">
					<span class="planning-effectif-line planning-effectif-main"><span class="planning-effectif-label">Enfants</span><strong>${valeur.nombre}</strong></span>
					<span class="planning-effectif-line planning-ratio-visible"><span class="planning-effectif-label">Taux d’encadrement</span><strong>1/${valeur.enfantsParAnimateur}</strong></span>
					<span class="planning-effectif-line planning-animateurs-compteur"><span class="planning-effectif-label">Anim. affectés / nécessaires</span><strong>${animateursAffectes}/${animateursNecessaires}</strong></span>
				</span>`;
			badge.title = details;
			zone.appendChild(badge);

			const evenements = cadre.querySelector(".fc-daygrid-day-events");
			if (evenements) cadre.insertBefore(zone, evenements);
			else cadre.appendChild(zone);
		});
		mettreAJourTotalEffectifsCentre(calendar.centrePlanning?.id);
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
					{
						nombre: ligne.nombre,
						enfantsParAnimateur: ligne.enfants_par_animateur || 8,
						ratioEncadrementExceptionnel: ligne.ratio_encadrement_exceptionnel ?? null,
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
				</div>`;
		}).join("") || '<p class="empty-note">Ce groupe n’est ouvert aucun jour cette semaine.</p>';
		ouvrirModal(modalEffectifsEnfants);
	}

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
					.filter((item) => item.nombre > 0 || valeursExistantes[item.date]?.ratioEncadrementExceptionnel)
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
			editable: !estModeEffectifs(),
			droppable: !estModeEffectifs(),
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
			dayMaxEvents: false,
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
				if (estModeEffectifs()) return;
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
				if (estModeEffectifs()) return false;

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
				if (estModeEffectifs()) { info.event.remove(); return; }
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

			eventDrop: function (info) { if (!estModeEffectifs()) updateAffectation(info, centre, evenement); },
			eventResize: function (info) { if (!estModeEffectifs()) updateAffectation(info, centre, evenement); },

			eventClick: function (info)
			{
				if (estModeEffectifs()) return;
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
			<div class="evenement-calendars calendar-group-list"></div>
			<p class="calendar-site-empty" ${evenements.length ? "hidden" : ""}>Aucun groupe ouvert cette semaine.</p>
			<footer class="centre-effectifs-summary" aria-live="polite"></footer>`;

		(conteneurLigne || calendarsContainer).appendChild(groupe);
		attacherSurvolCentre(groupe, centre.id);

		const zoneEvenements = groupe.querySelector(".evenement-calendars");
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
			calendars.push(calendar);
		});

		return groupe;
	}

	let rafMiseAJourCalendriers = null;

	function mettreAJourDimensionsCalendriers()
	{
		if (rafMiseAJourCalendriers) cancelAnimationFrame(rafMiseAJourCalendriers);
		rafMiseAJourCalendriers = requestAnimationFrame(() =>
		{
			rafMiseAJourCalendriers = requestAnimationFrame(() =>
			{
				calendars.forEach((calendar) =>
				{
					const card = calendar.el?.closest(".evenement-calendar-card");
					if (card)
					{
						const rect = card.getBoundingClientRect();
						card.classList.toggle("planning-calendar-tight", rect.width < 520);
						card.classList.toggle("planning-calendar-ultra-tight", rect.width < 340);
					}
					calendar.updateSize();
				});
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
									{
						nombre: ligne.nombre,
						enfantsParAnimateur: ligne.enfants_par_animateur || 8,
						ratioEncadrementExceptionnel: ligne.ratio_encadrement_exceptionnel ?? null,
					},
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
				if (!datePeriodeCourante && periodes.length)
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
					allerDateTous(datePeriodeCourante);
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

	// Construit une ligne compacte mais informative : identité, centre préféré,
	// qualifications principales et état sur la semaine visible.

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

		const avatar = document.createElement("span");
		avatar.classList.add("anim-avatar");
		avatar.textContent = `${animateur.prenom?.[0] || ""}${animateur.nom?.[0] || ""}`.toUpperCase();
		avatar.setAttribute("aria-hidden", "true");
		div.appendChild(avatar);

		const contenu = document.createElement("span");
		contenu.classList.add("anim-content");

		const name = document.createElement("span");
		name.classList.add("anim-name");
		name.textContent = `${animateur.prenom} ${animateur.nom}`;
		contenu.appendChild(name);

		const details = document.createElement("span");
		details.classList.add("anim-details");
		const centre = animateur.centre_prefere?.code || animateur.centre_prefere?.nom || "Sans centre";
		const qualifications = (animateur.qualifications || []).slice(0, 2);
		const supplement = Math.max(0, (animateur.qualifications || []).length - qualifications.length);
		details.textContent = [centre, qualifications.join(" · ") + (supplement ? ` +${supplement}` : "")]
			.filter(Boolean).join(" — ");
		contenu.appendChild(details);
		div.appendChild(contenu);

		const infos = [
			animateur.telephone || null,
			animateur.email || null,
		].filter(Boolean).join(" · ");
		if (infos) div.title = infos;

		const indicateurs = document.createElement("span");
		indicateurs.classList.add("anim-statuses");
		const lundi = lundiDeLaSemaine(datePeriodeCourante || new Date());
		const debutSemaine = formatDateLocal(lundi);
		const vendredi = new Date(lundi);
		vendredi.setDate(lundi.getDate() + 4);
		const finSemaine = formatDateLocal(vendredi);
		const chevaucheSemaine = (plage, finExclusive = false) => plage
			&& String(plage.debut || "") <= finSemaine
			&& (finExclusive ? String(plage.fin || "") > debutSemaine : String(plage.fin || "") >= debutSemaine);
		const disponible = (animateur.disponibilites || []).some((plage) => chevaucheSemaine(plage));
		const affecte = (animateur.affectations || []).some((plage) => chevaucheSemaine(plage, true));

		const statutDisponibilite = document.createElement("span");
		statutDisponibilite.className = `anim-status ${disponible ? "is-available" : "is-unavailable"}`;
		statutDisponibilite.title = disponible ? "Disponible sur la semaine" : "Aucune disponibilité sur la semaine";
		statutDisponibilite.setAttribute("aria-label", statutDisponibilite.title);
		statutDisponibilite.textContent = disponible ? "D" : "—";
		indicateurs.appendChild(statutDisponibilite);

		if (affecte)
		{
			const statutAffectation = document.createElement("span");
			statutAffectation.className = "anim-status is-assigned";
			statutAffectation.title = "Déjà affecté sur la semaine";
			statutAffectation.setAttribute("aria-label", statutAffectation.title);
			statutAffectation.textContent = "A";
			indicateurs.appendChild(statutAffectation);
		}

		const centresBadges = document.createElement("span");
		centresBadges.classList.add("anim-prefs", "anim-prefs-hidden");

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
		div.appendChild(indicateurs);

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
							${(evenement.qualifications_libelle || []).length ? `<span class="auto-evenement-periode">Qualifications : ${escapeHtml(evenement.qualifications_libelle.join(", "))}</span>` : ""}
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
					<li>nombre d’animateurs et qualifications requises dans chaque groupe ;</li>
					<li>disponibilités et absence de double affectation ;</li>
					<li>lieux interdits exclus, lieux préférés favorisés ;</li>
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

	appliquerModePlanning(modePlanning, false);

});
