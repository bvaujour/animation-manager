// ===========================================================================
// recapitulatif.js
// ---------------------------------------------------------------------------
// Page /recapitulatif/ : appelle /api/recapitulatif/ (avec ou sans filtre
// de période) et affiche les compteurs, les deux tableaux et les listes
// "à surveiller". Toute la logique de calcul est côté serveur (voir
// api_recapitulatif dans views.py) ; ce fichier ne fait que mettre en
// forme la réponse JSON.
// ===========================================================================

document.addEventListener("DOMContentLoaded", () =>
{
	const select = document.getElementById("filtre-periode");
	const plagePersonnalisee = document.getElementById("plage-personnalisee");
	const debutInput = document.getElementById("filtre-debut");
	const finInput = document.getElementById("filtre-fin");
	const btnAppliquer = document.getElementById("btn-appliquer-filtre");

	// Calcule les dates "debut"/"fin" (chaînes YYYY-MM-DD ou undefined)
	// correspondant à l'option choisie dans le menu déroulant.
	function calculerPlage()
	{
		const valeur = select.value;
		const maintenant = new Date();

		if (valeur === "toute-periode")
		{
			return {};
		}

		if (valeur === "cette-semaine")
		{
			// Même logique que lundiDeLaSemaine() dans planning.js : on
			// ramène `maintenant` au lundi de sa semaine, puis +7 jours
			// pour la borne de fin (exclusive). formatDateLocal() (et non
			// toISOString()) car on manipule des dates en heure locale :
			// voir l'explication détaillée dans ui.js.
			const jour = maintenant.getDay();
			const diff = (jour === 0 ? -6 : 1 - jour);
			const lundi = new Date(maintenant);
			lundi.setDate(lundi.getDate() + diff);
			const dimancheSuivant = new Date(lundi);
			dimancheSuivant.setDate(dimancheSuivant.getDate() + 7);

			return {
				debut: formatDateLocal(lundi),
				fin: formatDateLocal(dimancheSuivant),
			};
		}

		if (valeur === "ce-mois")
		{
			const debut = new Date(maintenant.getFullYear(), maintenant.getMonth(), 1);
			const finExclusive = new Date(maintenant.getFullYear(), maintenant.getMonth() + 1, 1);

			return {
				debut: formatDateLocal(debut),
				fin: formatDateLocal(finExclusive),
			};
		}

		// "personnalise" : on renvoie directement le contenu des deux
		// champs date (peuvent être vides, l'API gère l'absence des deux).
		return {
			debut: debutInput.value || undefined,
			fin: finInput.value || undefined,
		};
	}

	// Remplit les 5 petites cartes de compteurs en haut de page.
	function afficherCompteurs(compteurs)
	{
		document.getElementById("compteurs").innerHTML = `
			<div class="stat-card"><span class="stat-value">${compteurs.nb_animateurs}</span><span class="stat-label">Animateurs</span></div>
			<div class="stat-card"><span class="stat-value">${compteurs.nb_centres}</span><span class="stat-label">Centres</span></div>
			<div class="stat-card"><span class="stat-value">${compteurs.nb_qualifications}</span><span class="stat-label">Qualifications</span></div>
			<div class="stat-card"><span class="stat-value">${compteurs.nb_affectations_periode}</span><span class="stat-label">Affectations (période)</span></div>
			<div class="stat-card"><span class="stat-value">${compteurs.nb_affectations_a_venir}</span><span class="stat-label">À venir (total)</span></div>
		`;
	}

	// Remplit un tableau <tbody> à partir d'une liste de lignes déjà
	// construites en HTML (une petite fonction generic pour éviter de
	// dupliquer la même logique pour le tableau animateurs et centres).
	function remplirTableau(selecteurBody, lignesHtml, colspanSiVide, texteSiVide)
	{
		const tbody = document.querySelector(selecteurBody);
		tbody.innerHTML = "";

		if (lignesHtml.length === 0)
		{
			tbody.innerHTML = `<tr><td colspan="${colspanSiVide}" class="empty-note">${texteSiVide}</td></tr>`;
			return;
		}

		tbody.innerHTML = lignesHtml.join("");
	}

	// Affiche (ou masque si vide) un bloc "à surveiller" donné.
	function afficherAlerte(idListe, liste)
	{
		const ul = document.getElementById(idListe);
		const bloc = ul.closest(".alerte-bloc");

		if (liste.length === 0)
		{
			bloc.hidden = true;
			return;
		}

		bloc.hidden = false;
		ul.innerHTML = liste.map((texte) => `<li>${texte}</li>`).join("");
	}

	// Appelle l'API avec le filtre courant et met à jour toute la page.
	function charger()
	{
		const plage = calculerPlage();
		const params = new URLSearchParams();
		if (plage.debut) params.set("debut", plage.debut);
		if (plage.fin) params.set("fin", plage.fin);

		apiFetch(`/api/recapitulatif/?${params.toString()}`).then((data) =>
		{
			afficherCompteurs(data.compteurs);

			remplirTableau(
				"#table-animateurs tbody",
				data.animateurs.map((a) => `<tr><td>${a.prenom} ${a.nom}</td><td>${a.age ?? "—"}</td><td>${a.jours}</td><td>${a.nb_centres}</td></tr>`),
				4,
				"Aucun animateur."
			);

			remplirTableau(
				"#table-centres tbody",
				data.centres.map((c) => `<tr><td>${c.nom} (${c.code})</td><td>${c.jours}</td><td>${c.nb_animateurs}</td></tr>`),
				3,
				"Aucun centre."
			);

			afficherAlerte("alerte-sans-preference", data.alertes.animateurs_sans_preference);
			afficherAlerte("alerte-sans-disponibilite", data.alertes.animateurs_sans_disponibilite);
			afficherAlerte("alerte-jamais-affectes", data.alertes.animateurs_jamais_affectes);
			afficherAlerte("alerte-centres-inutilises", data.alertes.centres_jamais_utilises);
			afficherAlerte("alerte-qualifs-inutilisees", data.alertes.qualifications_non_utilisees);
		});
	}

	// Changer d'option recharge tout de suite, SAUF "personnalise" qui a
	// besoin qu'on saisisse d'abord les deux dates puis clique "Appliquer".
	select.addEventListener("change", () =>
	{
		const estPersonnalise = select.value === "personnalise";
		plagePersonnalisee.hidden = !estPersonnalise;

		if (!estPersonnalise)
		{
			charger();
		}
	});

	btnAppliquer.addEventListener("click", charger);

	charger();
});
