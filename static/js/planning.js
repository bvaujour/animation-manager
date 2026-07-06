document.addEventListener("DOMContentLoaded", function ()
{
	const calendarsContainer = document.getElementById("calendars-container");
	const animList = document.getElementById("animateurs-list");
	const dispoInfo = document.getElementById("dispo-info");
	const toolbarLabel = document.getElementById("toolbar-label");

	const calendars = [];

	const DISPO_SOURCE_ID = "disponibilites";

	// L'animateur actuellement sélectionné dans la liste : ses disponibilités
	// s'affichent sur les calendriers, et un clic sur un jour l'y affecte
	// (alternative au glisser-déposer, plus fiable sur téléphone).
	let animateurActif = null;

	// ------------------------------------------------------------------
	// Calendriers (un par centre)
	// ------------------------------------------------------------------

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

	function creerCalendar(centre, card)
	{
		const calendarEl = card.querySelector(".calendar");

		const calendar = new FullCalendar.Calendar(calendarEl,
		{
			initialView: "dayGridWeek",
			height: "100%",
			locale: "fr",
			firstDay: 1,
			overflow: false,
			editable: true,
			droppable: true,
			selectable: true,

			expandRows: true,

			headerToolbar: false,
			footerToolbar: false,

			events: `/api/planning/?centre_id=${centre.id}`,

			datesSet: function (info)
			{
				toolbarLabel.textContent = info.view.title;
			},

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
					info.view.calendar.addEvent({
						id: data.id,
						title: data.title,
						start: data.start,
						end: data.end,
						allDay: true,
					});
					afficherToast(`${animateurActif.prenom} affecté·e le ${new Date(debut).toLocaleDateString("fr-FR")}.`);
				}).catch((err) =>
				{
					afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true);
				});
			},

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
					info.event.setProp("id", data.id);
				}).catch((err) =>
				{
					afficherToast(erreurMessage(err, "Cette affectation n'a pas pu être enregistrée."), true);
					info.event.remove();
				});
			},

			eventDrop: function (info) { updateAffectation(info); },
			eventResize: function (info) { updateAffectation(info); },

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

	function chargerCentres()
	{
		return apiFetch("/api/centres/").then((centres) =>
		{
			calendarsContainer.innerHTML = "";

			if (centres.length === 0)
			{
				calendarsContainer.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant. Utilise le bouton "+" pour en ajouter un.</p>';
				return;
			}

			centres.forEach((centre) => ajouterCentreAuPlanning(centre));
		});
	}

	// ------------------------------------------------------------------
	// Barre d'outils commune : navigation et vue, synchronisées sur les
	// 3 calendriers en même temps.
	// ------------------------------------------------------------------

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

	// ------------------------------------------------------------------
	// Liste des animateurs (badges de type "badge de colo")
	// ------------------------------------------------------------------

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
		div.addEventListener("click", () => toggleSelection(div, animateur));

		return div;
	}

	function chargerAnimateurs()
	{
		return apiFetch("/api/animateurs/").then((animateurs) =>
		{
			animList.innerHTML = "";

			if (animateurs.length === 0)
			{
				animList.innerHTML = '<p class="empty-note">Aucun animateur pour l\'instant.</p>';
				return;
			}

			animateurs.forEach((animateur) => animList.appendChild(creerChipAnimateur(animateur)));
		});
	}

	// ------------------------------------------------------------------
	// Disponibilités affichées sur les calendriers au clic sur un animateur
	// ------------------------------------------------------------------

	function effacerDisponibilitesAffichees()
	{
		calendars.forEach((calendar) =>
		{
			const source = calendar.getEventSourceById(DISPO_SOURCE_ID);
			if (source) source.remove();
		});
	}

	function afficherDisponibilites(animateur, plages)
	{
		dispoInfo.innerHTML = "";

		const consigne = "Clique sur un jour d'un calendrier pour l'y affecter.";

		if (plages.length === 0)
		{
			dispoInfo.textContent = `${animateur.prenom} : aucune disponibilité renseignée. ${consigne}`;
			return;
		}

		const periodes = plages.map((plage) =>
		{
			const debutStr = new Date(plage.debut).toLocaleDateString("fr-FR");
			const finStr = new Date(plage.fin).toLocaleDateString("fr-FR");
			return `${debutStr} → ${finStr}`;
		}).join(", ");

		dispoInfo.textContent = `${animateur.prenom} disponible : ${periodes}. ${consigne}`;

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

	function toggleSelection(chip, animateur)
	{
		const dejaSelectionne = chip.classList.contains("selected");

		document.querySelectorAll(".animateur.selected").forEach((el) => el.classList.remove("selected"));
		effacerDisponibilitesAffichees();
		dispoInfo.textContent = "";
		animateurActif = null;

		if (dejaSelectionne) return;

		chip.classList.add("selected");
		animateurActif = animateur;

		apiFetch(`/api/animateurs/${animateur.id}/disponibilites/`)
			.then((data) => afficherDisponibilites(animateur, data.disponibilites));
	}

	// ------------------------------------------------------------------
	// Survol d'un calendrier : met en avant, pour chaque animateur, son
	// classement de préférence pour ce centre (et estompe les autres).
	// ------------------------------------------------------------------

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

	// ------------------------------------------------------------------
	// Modal d'ajout rapide (animateur / centre / qualification)
	// ------------------------------------------------------------------

	const modal = document.getElementById("modal-ajout");
	let modalInitialisee = false;

	initFermetureModal(modal);

	document.getElementById("btn-ajout-rapide").addEventListener("click", () =>
	{
		if (!modalInitialisee)
		{
			const animateursModal = GestionApp.mountAnimateurs(document.getElementById("modal-panel-animateurs"), {
				onChange: () => chargerAnimateurs(),
			});

			GestionApp.mountCentres(document.getElementById("modal-panel-centres"), {
				onChange: (nouveauCentre) =>
				{
					if (nouveauCentre) ajouterCentreAuPlanning(nouveauCentre);
				},
			});

			GestionApp.mountQualifications(document.getElementById("modal-panel-qualifications"), {
				onChange: () => animateursModal.chargerCheckboxesQualifs(),
			});

			initTabs(document.getElementById("modal-tabs").closest(".modal-body"));

			modalInitialisee = true;
		}

		ouvrirModal(modal);
	});

	// ------------------------------------------------------------------
	// Chargement initial
	// ------------------------------------------------------------------

	chargerCentres();
	chargerAnimateurs();

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
