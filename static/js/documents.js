// ===========================================================================
// documents.js
// ---------------------------------------------------------------------------
// Page /documents/ : liste des documents (chargée via l'API), formulaire
// d'ajout (upload de fichier) et suppression.
//
// Particularité par rapport aux autres pages : l'ajout se fait via un
// vrai formulaire multipart/form-data (à cause du fichier), donc on ne
// peut PAS utiliser apiFetch() pour l'upload (elle force le Content-Type
// JSON) — on fait un fetch() "à la main" pour cette seule requête, avec
// juste l'en-tête CSRF ajouté ; le reste (liste, suppression) passe par
// apiFetch() comme d'habitude.
// ===========================================================================

document.addEventListener("DOMContentLoaded", () =>
{
	const grid = document.getElementById("documents-grid");
	const form = document.getElementById("form-upload");
	const titreInput = document.getElementById("doc-titre");
	const fichierInput = document.getElementById("doc-fichier");
	const errorEl = document.getElementById("doc-error");

	const EXTENSIONS_IMAGE = ["jpg", "jpeg", "png", "gif", "webp"];

	function extensionDe(url)
	{
		return url.split("?")[0].split(".").pop().toLowerCase();
	}

	// Construit la carte d'un document : aperçu adapté au type de
	// fichier (PDF intégré, image, ou simple icône + lien pour le reste),
	// suivi du titre, de la date d'ajout et des actions.
	function carteDocument(doc)
	{
		const extension = extensionDe(doc.url);
		const div = document.createElement("div");
		div.classList.add("document-card");

		let apercu;
		if (extension === "pdf")
		{
			apercu = `<iframe src="${doc.url}" loading="lazy" title="${doc.titre}"></iframe>`;
		}
		else if (EXTENSIONS_IMAGE.includes(extension))
		{
			apercu = `<img src="${doc.url}" alt="${doc.titre}" loading="lazy">`;
		}
		else
		{
			apercu = `<div class="document-icon" aria-hidden="true">📄</div>`;
		}

		const dateAjout = new Date(doc.date_ajout).toLocaleDateString("fr-FR");

		div.innerHTML = `
			<div class="document-apercu">${apercu}</div>
			<div class="document-info">
				<h3 class="truncate">${doc.titre}</h3>
				<span class="document-date">Ajouté le ${dateAjout}</span>
			</div>
			<div class="document-actions">
				<a href="${doc.url}" target="_blank" rel="noopener" class="btn btn-ghost">Ouvrir</a>
				<button class="btn btn-danger" type="button">&times; Supprimer</button>
			</div>
		`;

		div.querySelector(".btn-danger").addEventListener("click", () =>
		{
			if (!confirm(`Supprimer le document "${doc.titre}" ?`)) return;

			apiFetch(`/api/documents/${doc.id}/`, { method: "DELETE" })
				.then(() =>
				{
					afficherToast("Document supprimé.");
					charger();
				})
				.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
		});

		return div;
	}

	function charger()
	{
		apiFetch("/api/documents/").then((documents) =>
		{
			grid.innerHTML = "";

			if (documents.length === 0)
			{
				grid.innerHTML = '<p class="empty-note">Aucun document pour l\'instant.</p>';
				return;
			}

			documents.forEach((doc) => grid.appendChild(carteDocument(doc)));
		});
	}

	form.addEventListener("submit", (event) =>
	{
		event.preventDefault();
		errorEl.textContent = "";

		const fichier = fichierInput.files[0];
		if (!fichier)
		{
			errorEl.textContent = "Choisis un fichier.";
			return;
		}

		const donnees = new FormData();
		donnees.append("titre", titreInput.value.trim());
		donnees.append("fichier", fichier);

		// Pas d'apiFetch() ici : elle imposerait un Content-Type JSON qui
		// casserait l'upload. Le navigateur ajoute lui-même le bon
		// Content-Type "multipart/form-data; boundary=..." pour un objet
		// FormData ; on ne fournit que l'en-tête CSRF requis par Django.
		fetch("/api/documents/",
		{
			method: "POST",
			headers: { "X-CSRFToken": csrfToken() },
			body: donnees,
		}).then((response) =>
		{
			if (!response.ok)
			{
				return response.json().then((err) => { throw err; });
			}
			return response.json();
		}).then(() =>
		{
			form.reset();
			afficherToast("Document ajouté.");
			charger();
		}).catch((err) =>
		{
			errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce document.");
		});
	});

	charger();
});
