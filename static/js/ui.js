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
	return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
}

// Wrapper commun autour de fetch(). Il respecte les envois multipart
// (FormData), ajoute le CSRF uniquement aux méthodes qui modifient les
// données et produit une erreur lisible même si le serveur renvoie du texte
// ou une page HTML au lieu du JSON attendu.
async function apiFetch(url, options = {}) {
	const config = { ...options };
	const headers = new Headers(options.headers || {});
	const method = String(config.method || "GET").toUpperCase();
	const bodyIsFormData = typeof FormData !== "undefined" && config.body instanceof FormData;

	if (!headers.has("Accept")) headers.set("Accept", "application/json");
	if (config.body != null && !bodyIsFormData && !headers.has("Content-Type")) {
		headers.set("Content-Type", "application/json");
	}
	if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method) && !headers.has("X-CSRFToken")) {
		const token = csrfToken();
		if (token) headers.set("X-CSRFToken", token);
	}
	config.headers = headers;

	// Les écrans de gestion doivent toujours relire les données courantes.
	// Sans cette option, certains navigateurs peuvent réutiliser une ancienne
	// réponse GET après un enregistrement (notamment les effectifs enfants),
	// ce qui donne l'impression que la donnée a disparu après actualisation.
	if ((method === "GET" || method === "HEAD") && config.cache == null) {
		config.cache = "no-store";
	}

	const response = await fetch(url, config);
	let payload = null;
	if (response.status !== 204) {
		const text = await response.text();
		if (text) {
			try {
				payload = JSON.parse(text);
			} catch {
				payload = { error: text };
			}
		}
	}

	if (!response.ok) {
		throw payload || { error: `Erreur HTTP ${response.status}` };
	}
	return payload;
}

// Extrait un message d'erreur lisible d'un objet d'erreur venant
// d'apiFetch (ou renvoie un message de repli si la forme est inattendue,
// par exemple en cas d'erreur réseau plutôt que d'erreur métier).
function erreurMessage(err, repli) {
	return err?.error || err?.message || repli;
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


// Échappe du texte avant insertion dans une chaîne HTML.
function escapeHtml(value) {
	return String(value ?? "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll("\"", "&quot;")
		.replaceAll("'", "&#039;");
}

// Affiche une semaine avec son année civile, partout de la même façon.
// Exemple : « Été — Semaine 2 » devient « Été 2026 — Semaine 2 ».
function libellePeriodeAvecAnnee(periode) {
	const nom = String(periode?.nom ?? "").trim();
	if (!nom) return "Période sans nom";

	const annee = String(periode?.debut ?? periode?.annee_scolaire ?? "").slice(0, 4);
	if (!/^\d{4}$/.test(annee) || nom.includes(annee)) return nom;

	const separateurSemaine = " — Semaine ";
	if (nom.includes(separateurSemaine)) {
		return nom.replace(separateurSemaine, ` ${annee}${separateurSemaine}`);
	}
	return `${nom} ${annee}`;
}

// Ajoute les dates de début et de fin juste après le nom de la semaine,
// sans modifier la structure ni les boutons de la barre de navigation.
function libellePeriodeAvecDates(periode) {
	const libelle = libellePeriodeAvecAnnee(periode);
	const debutStr = periode?.debut;
	const finStr = periode?.fin_periode || periode?.fin;
	if (!debutStr || !finStr) return libelle;

	const debut = parseLocalDate(debutStr);
	const fin = parseLocalDate(finStr);
	if (Number.isNaN(debut.getTime()) || Number.isNaN(fin.getTime())) return libelle;

	const jourDebut = debut.getDate();
	const jourFin = fin.getDate();
	const moisDebut = debut.toLocaleDateString("fr-FR", { month: "long" });
	const moisFin = fin.toLocaleDateString("fr-FR", { month: "long" });
	const anneeDebut = debut.getFullYear();
	const anneeFin = fin.getFullYear();

	let dates;
	if (anneeDebut !== anneeFin) {
		dates = `du ${jourDebut} ${moisDebut} ${anneeDebut} au ${jourFin} ${moisFin} ${anneeFin}`;
	} else if (debut.getMonth() !== fin.getMonth()) {
		dates = `du ${jourDebut} ${moisDebut} au ${jourFin} ${moisFin} ${anneeFin}`;
	} else {
		dates = `du ${jourDebut} au ${jourFin} ${moisFin} ${anneeFin}`;
	}

	return `${libelle} · ${dates}`;
}

// Renvoie les identifiants numériques de cases cochées dans un conteneur.
function idsCheckboxesCochees(root) {
	return Array.from(root.querySelectorAll("input:checked"))
		.map((input) => Number.parseInt(input.value, 10))
		.filter(Number.isFinite);
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

// --- Navigation latérale commune ---
function initNavigationLaterale() {
    if (window.__gestionAnimationNavReady) return;
    window.__gestionAnimationNavReady = true;

    const drawer = document.getElementById("app-drawer");
    const overlay = document.querySelector("[data-nav-close].nav-overlay");
    const openButton = document.querySelector("[data-nav-open]");
    const closeButtons = document.querySelectorAll("[data-nav-close]");

    if (!drawer || !overlay || !openButton) return;

    function ouvrirNavigation() {
        drawer.hidden = false;
        overlay.hidden = false;
        requestAnimationFrame(() => {
            drawer.classList.add("open");
            overlay.classList.add("open");
            openButton.setAttribute("aria-expanded", "true");
        });
    }

    function fermerNavigation() {
        drawer.classList.remove("open");
        overlay.classList.remove("open");
        openButton.setAttribute("aria-expanded", "false");
        window.setTimeout(() => {
            drawer.hidden = true;
            overlay.hidden = true;
        }, 180);
    }

    openButton.addEventListener("click", ouvrirNavigation);
    closeButtons.forEach((button) => button.addEventListener("click", fermerNavigation));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !drawer.hidden) fermerNavigation();
    });
}

document.addEventListener("DOMContentLoaded", initNavigationLaterale);


// --- Classement commun des périodes par année scolaire ---
// Toutes les interfaces qui affichent plusieurs années (groupes,
// disponibilités, récapitulatif, bibliothèque) utilisent ces helpers afin de
// garder le même ordre et d'ouvrir la même année par défaut.
function anneeScolaireCourante(date = new Date()) {
    const anneeDebut = date.getMonth() >= 6 ? date.getFullYear() : date.getFullYear() - 1;
    return `${anneeDebut}-${anneeDebut + 1}`;
}

function grouperPeriodesParAnnee(periodes) {
    const groupes = new Map();
    (periodes || []).forEach((periode) => {
        const annee = String(periode.annee_scolaire || String(periode.debut || "").slice(0, 4) || "Sans année");
        if (!groupes.has(annee)) groupes.set(annee, []);
        groupes.get(annee).push(periode);
    });

    return [...groupes.entries()]
        .sort(([anneeA], [anneeB]) => anneeB.localeCompare(anneeA, "fr"))
        .map(([annee, elements]) => ({
            annee,
            periodes: [...elements].sort((a, b) => String(a.debut || "").localeCompare(String(b.debut || ""))),
        }));
}

function anneePeriodesADeplier(periodes) {
    const groupes = grouperPeriodesParAnnee(periodes);
    const courante = anneeScolaireCourante();
    return groupes.some((groupe) => groupe.annee === courante)
        ? courante
        : (groupes[0]?.annee || "");
}
