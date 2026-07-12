// ===========================================================================
// recapitulatif.js
// ---------------------------------------------------------------------------
// Page /recapitulatif/ simplifiée : choix d'une période et affichage du
// nombre de jours travaillés par animateur, avec une colonne par centre.
// La période par défaut est le mois actuel.
// ===========================================================================

document.addEventListener("DOMContentLoaded", () =>
{
	const debutInput = document.getElementById("periode-debut");
	const finInput = document.getElementById("periode-fin");
	const btnAppliquer = document.getElementById("btn-appliquer-periode");
	const periodeAffichee = document.getElementById("periode-affichee");
	const table = document.getElementById("table-recap");

	function debutMoisCourant()
	{
		const now = new Date();
		return new Date(now.getFullYear(), now.getMonth(), 1);
	}

	function finMoisCourantInclusive()
	{
		const now = new Date();
		return new Date(now.getFullYear(), now.getMonth() + 1, 0);
	}

	function formatDateFr(dateStr)
	{
		return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
	}

	function initialiserPeriodeParDefaut()
	{
		debutInput.value = formatDateLocal(debutMoisCourant());
		finInput.value = formatDateLocal(finMoisCourantInclusive());
	}

	function construireUrlApi()
	{
		const debut = debutInput.value;
		const finInclusive = finInput.value;

		if (!debut || !finInclusive)
		{
			afficherToast("Renseigne une date de début et une date de fin.", true);
			return null;
		}

		if (debut > finInclusive)
		{
			afficherToast("La date de début doit être avant la date de fin.", true);
			return null;
		}

		// L'API attend une fin exclusive : pour afficher du 01 au 31 inclus,
		// on envoie fin = 1er du mois suivant.
		const finExclusive = addDays(finInclusive, 1);
		const params = new URLSearchParams({ debut, fin: finExclusive });
		return `/api/recapitulatif/?${params.toString()}`;
	}


	function afficherTableau(data)
	{
		const thead = table.querySelector("thead");
		const tbody = table.querySelector("tbody");

		periodeAffichee.textContent = `Du ${formatDateFr(debutInput.value)} au ${formatDateFr(finInput.value)}`;

		thead.innerHTML = `
			<tr>
				<th class="animateur-header">Animateur</th>
				${data.centres.map((centre) => `
					<th
						class="centre-header"
						style="--centre-color:${centre.couleur}; --centre-bg:${ColorUtils.rgba(centre.couleur, 0.16)};"
					>
						<span class="centre-dot" style="--c:${centre.couleur}"></span>
						<span>${centre.code || centre.nom}</span>
					</th>
				`).join("")}
				<th class="total-header">Total</th>
			</tr>
		`;

		if (data.animateurs.length === 0)
		{
			tbody.innerHTML = `<tr><td colspan="${data.centres.length + 2}" class="empty-note">Aucun animateur.</td></tr>`;
			return;
		}

		tbody.innerHTML = data.animateurs.map((animateur) =>
		{
			const cellulesCentres = animateur.centres.map((centreRecap, index) =>
			{
				const centre = data.centres[index];
				const classe = centreRecap.jours > 0 ? "jours-value has-days" : "jours-value";
				return `
					<td
						class="number-cell centre-cell"
						style="--centre-color:${centre.couleur}; --centre-bg:${ColorUtils.rgba(centre.couleur, 0.08)};"
					>
						<span class="${classe}">${centreRecap.jours}</span>
					</td>
				`;
			}).join("");

			return `
				<tr>
					<td class="animateur-cell">${animateur.prenom} ${animateur.nom}</td>
					${cellulesCentres}
					<td class="number-cell total-cell">${animateur.total}</td>
				</tr>
			`;
		}).join("");
	}

	function chargerRecap()
	{
		const url = construireUrlApi();
		if (!url) return;

		apiFetch(url)
			.then(afficherTableau)
			.catch((err) => afficherToast(erreurMessage(err, "Le récapitulatif n'a pas pu être chargé."), true));
	}

	btnAppliquer.addEventListener("click", chargerRecap);

	initialiserPeriodeParDefaut();
	chargerRecap();
});
