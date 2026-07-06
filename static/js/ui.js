// ===========================================================================
// ui.js
// ---------------------------------------------------------------------------
// Petites fonctions utilitaires partagées par TOUTES les pages qui font des
// appels à l'API (planning.js, gestion.js, recapitulatif.js). Rien de
// spécifique à une page en particulier ici : ça reste volontairement
// générique.
//
// Chargé en premier dans le <head>/<body> de chaque template concerné,
// avant le fichier JS propre à la page.
// ===========================================================================

// Récupère le jeton CSRF présent dans le formulaire caché généré par
// {% csrf_token %} dans le template. Django en a besoin pour accepter les
// requêtes POST/PATCH/DELETE (sans ça : erreur 403 Forbidden).
function csrfToken() {
	return document.querySelector("[name=csrfmiddlewaretoken]").value;
}

// Petit wrapper autour de fetch() qui :
//   - ajoute automatiquement les en-têtes CSRF + Content-Type JSON ;
//   - transforme une réponse HTTP en erreur (status non-2xx) en exception
//     JS rejetée avec le corps JSON de l'erreur (donc utilisable avec
//     .catch((err) => ... err.error ...) partout dans le code) ;
//   - renvoie directement l'objet JS déjà parsé (plus besoin de faire
//     .then(r => r.json()) à chaque appel).
function apiFetch(url, options = {}) {
	options.headers = Object.assign(
		{
			"Content-Type": "application/json",
			"X-CSRFToken": csrfToken(),
		},
		options.headers || {}
	);

	return fetch(url, options).then((response) =>
	{
		if (!response.ok)
		{
			// Le corps de la réponse d'erreur est du JSON {"error": "..."}
			// (convention utilisée par toutes les vues API, voir views.py).
			return response.json().then((err) => { throw err; });
		}
		// Les réponses 204 (No Content) n'ont pas de corps JSON à parser.
		return response.status === 204 ? null : response.json();
	});
}

// Extrait un message d'erreur lisible d'un objet d'erreur venant
// d'apiFetch (ou renvoie un message de repli si la forme est inattendue,
// par exemple en cas d'erreur réseau plutôt que d'erreur métier).
function erreurMessage(err, repli) {
	return (err && err.error) ? err.error : repli;
}

// Ajoute `days` jours à une date "YYYY-MM-DD" et renvoie le résultat dans
// le même format. Utilisé partout où on manipule des bornes de dates
// "exclusives" à la FullCalendar (le jour de fin affiché = dernier jour + 1).
//
// Implémentation en UTC de bout en bout (parse UTC, arithmétique UTC,
// formatage UTC) : une chaîne "YYYY-MM-DD" est de toute façon interprétée
// par JS comme un instant UTC, donc rester en UTC partout évite tout
// décalage d'un jour selon le fuseau horaire de la personne qui utilise
// l'appli (voir formatDateLocal ci-dessous pour le cas différent où l'on
// part d'un vrai objet Date en heure locale).
function addDays(dateStr, days) {
	const d = new Date(dateStr);
	d.setUTCDate(d.getUTCDate() + days);
	return d.toISOString().slice(0, 10);
}

// Formate un objet Date en "YYYY-MM-DD" en utilisant ses composants
// LOCAUX (getFullYear/getMonth/getDate), PAS toISOString() qui convertit
// en UTC et peut décaler la date d'un jour.
//
// Piège classique : si on construit un Date à minuit en heure locale
// (ex: le lundi de la semaine affichée dans le planning) puis qu'on
// appelle toISOString(), le résultat est converti en UTC — et pour un
// fuseau horaire en avance sur UTC (la France en été, UTC+2), minuit
// local devient 22h la veille en UTC : on obtient donc la date du
// DIMANCHE au lieu du LUNDI. C'est exactement le bug qui empêchait le
// vendredi d'être décalé d'un jour. Cette fonction
// est la version correcte à utiliser pour formater une date "calendaire"
// construite/manipulée en heure locale (par opposition à addDays()
// ci-dessus, qui part d'une chaîne et reste volontairement en UTC).
function formatDateLocal(date) {
	const annee = date.getFullYear();
	const mois = String(date.getMonth() + 1).padStart(2, "0");
	const jour = String(date.getDate()).padStart(2, "0");
	return `${annee}-${mois}-${jour}`;
}

// Parse une chaîne "YYYY-MM-DD" en objet Date à MINUIT LOCAL, plutôt que
// `new Date("YYYY-MM-DD")` qui la traite comme un instant UTC (et peut
// donc afficher la veille avec toLocaleDateString() selon le fuseau).
// À utiliser pour tout affichage de date à l'utilisateur.
function parseLocalDate(dateStr) {
	const [annee, mois, jour] = dateStr.split("-").map(Number);
	return new Date(annee, mois - 1, jour);
}

// --- Modal générique (popup) ---
// Une seule modal HTML par page (voir planning.html), affichée/masquée
// simplement via l'attribut `hidden`.

function ouvrirModal(backdropEl) {
	backdropEl.hidden = false;
}

function fermerModal(backdropEl) {
	backdropEl.hidden = true;
}

// Branche les différentes façons de fermer une modal : clic sur le fond
// sombre, clic sur un bouton marqué [data-modal-close], ou touche Échap.
function initFermetureModal(backdropEl) {
	// Sécurité : si la page n'a pas cette modal, on ne bloque pas tout le JS.
	if (!backdropEl) {
		return;
	}

	backdropEl.addEventListener("click", (event) => {
		if (event.target === backdropEl) {
			fermerModal(backdropEl);
		}
	});

	backdropEl.querySelectorAll("[data-modal-close]").forEach((btn) => {
		btn.addEventListener("click", () => fermerModal(backdropEl));
	});

	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && !backdropEl.hidden) {
			fermerModal(backdropEl);
		}
	});
}

// Affiche un petit message temporaire en bas de l'écran (succès par
// défaut, ou en rouge si `estErreur` est vrai). Un seul toast à la fois :
// un nouveau appel remplace celui déjà affiché plutôt que de les empiler.
function afficherToast(message, estErreur = false) {
	const existant = document.querySelector(".toast");
	if (existant) {
		existant.remove();
	}

	const toast = document.createElement("div");
	toast.classList.add("toast");
	if (estErreur) {
		toast.classList.add("error");
	}
	toast.textContent = message;
	document.body.appendChild(toast);

	setTimeout(() => toast.remove(), 3200);
}

// --- Onglets génériques ---
// Attend une structure HTML du type :
//   <div class="tabs"><button class="tab-btn" data-tab="x">...</button>...</div>
//   <div class="tab-panel" data-panel="x">...</div>
// `rootEl` doit englober à la fois les .tab-btn ET les .tab-panel (peu
// importe la structure exacte autour, seuls ces sélecteurs comptent).
// Utilisé à la fois sur la page /gestion/ et dans la popup d'ajout rapide
// du planning (deux instances indépendantes, chacune avec son propre
// rootEl).
function initTabs(rootEl) {
	const boutons = rootEl.querySelectorAll(".tab-btn");

	boutons.forEach((btn) => {
		btn.addEventListener("click", () => {
			boutons.forEach((b) => b.classList.remove("active"));
			rootEl.querySelectorAll(".tab-panel").forEach((p) => { p.hidden = true; });

			btn.classList.add("active");
			rootEl.querySelector(`.tab-panel[data-panel="${btn.dataset.tab}"]`).hidden = false;
		});
	});
}
