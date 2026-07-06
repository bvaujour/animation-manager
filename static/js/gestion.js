const GestionApp = (function ()
{
	function ligneEntite(labelHtml, onDelete)
	{
		const row = document.createElement("div");
		row.classList.add("entity-row");

		const main = document.createElement("div");
		main.classList.add("entity-main");
		main.innerHTML = labelHtml;
		row.appendChild(main);

		const del = document.createElement("button");
		del.classList.add("btn-danger");
		del.innerHTML = "&times; Supprimer";
		del.addEventListener("click", onDelete);
		row.appendChild(del);

		return row;
	}

	// ------------------------------------------------------------------
	// Qualifications
	// ------------------------------------------------------------------

	function mountQualifications(container, options = {})
	{
		container.innerHTML = `
			<p class="section-title">Qualifications existantes</p>
			<div class="entity-list" id="qualifs-list"></div>
			<p class="section-title">Ajouter une qualification</p>
			<div class="field">
				<label for="qualif-nom">Nom</label>
				<input type="text" id="qualif-nom" placeholder="ex : BAFA">
			</div>
			<p class="form-error" id="qualif-error"></p>
			<button class="btn btn-primary" id="qualif-submit" type="button">Ajouter</button>
		`;

		const list = container.querySelector("#qualifs-list");
		const input = container.querySelector("#qualif-nom");
		const errorEl = container.querySelector("#qualif-error");

		function charger()
		{
			return apiFetch("/api/qualifications/").then((data) =>
			{
				list.innerHTML = "";

				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucune qualification pour l\'instant.</p>';
					return data;
				}

				data.forEach((q) =>
				{
					const row = ligneEntite(`<span class="truncate">${q.nom}</span>`, () =>
					{
						if (!confirm(`Supprimer la qualification "${q.nom}" ?`)) return;

						apiFetch(`/api/qualifications/${q.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Qualification supprimée.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					});
					list.appendChild(row);
				});

				return data;
			});
		}

		container.querySelector("#qualif-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = input.value.trim();

			if (!nom)
			{
				errorEl.textContent = "Le nom est obligatoire.";
				return;
			}

			apiFetch("/api/qualifications/", { method: "POST", body: JSON.stringify({ nom }) })
				.then((nouvelle) =>
				{
					input.value = "";
					afficherToast("Qualification ajoutée.");
					charger();
					if (options.onChange) options.onChange(nouvelle);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter cette qualification."); });
		});

		charger();
		return { charger };
	}

	// ------------------------------------------------------------------
	// Centres
	// ------------------------------------------------------------------

	function mountCentres(container, options = {})
	{
		container.innerHTML = `
			<p class="section-title">Centres existants</p>
			<div class="entity-list" id="centres-list"></div>
			<p class="section-title">Ajouter un centre</p>
			<div class="field">
				<label for="centre-nom">Nom</label>
				<input type="text" id="centre-nom" placeholder="ex : Pacaudière">
			</div>
			<div class="field">
				<label for="centre-code">Code (affiché dans les badges)</label>
				<input type="text" id="centre-code" placeholder="ex : PAC" maxlength="10">
			</div>
			<div class="field">
				<label for="centre-couleur">Couleur</label>
				<input type="color" id="centre-couleur" value="#1f6f54">
			</div>
			<p class="form-error" id="centre-error"></p>
			<button class="btn btn-primary" id="centre-submit" type="button">Ajouter</button>
		`;

		const list = container.querySelector("#centres-list");
		const nomEl = container.querySelector("#centre-nom");
		const codeEl = container.querySelector("#centre-code");
		const couleurEl = container.querySelector("#centre-couleur");
		const errorEl = container.querySelector("#centre-error");

		function charger()
		{
			return apiFetch("/api/centres/").then((data) =>
			{
				list.innerHTML = "";

				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucun centre pour l\'instant.</p>';
					return data;
				}

				data.forEach((c) =>
				{
					const label = `<span class="swatch" style="background:${c.couleur}"></span><span class="truncate">${c.nom} (${c.code})</span>`;
					const row = ligneEntite(label, () =>
					{
						if (!confirm(`Supprimer le centre "${c.nom}" ? Ses affectations et disponibilités liées seront aussi supprimées.`)) return;

						apiFetch(`/api/centres/${c.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Centre supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					});
					list.appendChild(row);
				});

				return data;
			});
		}

		container.querySelector("#centre-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const nom = nomEl.value.trim();
			const code = codeEl.value.trim();
			const couleur = couleurEl.value;

			if (!nom || !code)
			{
				errorEl.textContent = "Le nom et le code sont obligatoires.";
				return;
			}

			apiFetch("/api/centres/", { method: "POST", body: JSON.stringify({ nom, code, couleur }) })
				.then((nouveau) =>
				{
					nomEl.value = "";
					codeEl.value = "";
					afficherToast("Centre ajouté.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce centre (le code est peut-être déjà pris)."); });
		});

		charger();
		return { charger };
	}

	// ------------------------------------------------------------------
	// Animateurs
	// ------------------------------------------------------------------

	function mountAnimateurs(container, options = {})
	{
		container.innerHTML = `
			<p class="section-title">Animateurs existants</p>
			<div class="entity-list" id="anims-list"></div>
			<p class="section-title">Ajouter un animateur</p>
			<div class="field">
				<label for="anim-prenom">Prénom</label>
				<input type="text" id="anim-prenom">
			</div>
			<div class="field">
				<label for="anim-nom">Nom</label>
				<input type="text" id="anim-nom">
			</div>
			<div class="field">
				<label>Qualifications</label>
				<div class="checkbox-grid" id="anim-qualifs"></div>
			</div>
			<p class="form-error" id="anim-error"></p>
			<button class="btn btn-primary" id="anim-submit" type="button">Ajouter</button>
		`;

		const list = container.querySelector("#anims-list");
		const prenomEl = container.querySelector("#anim-prenom");
		const nomEl = container.querySelector("#anim-nom");
		const qualifsEl = container.querySelector("#anim-qualifs");
		const errorEl = container.querySelector("#anim-error");

		function chargerCheckboxesQualifs()
		{
			apiFetch("/api/qualifications/").then((data) =>
			{
				qualifsEl.innerHTML = "";

				if (data.length === 0)
				{
					qualifsEl.innerHTML = '<p class="empty-note">Ajoute d\'abord une qualification (onglet Qualifications).</p>';
					return;
				}

				data.forEach((q) =>
				{
					const label = document.createElement("label");
					label.classList.add("checkbox-chip");
					label.innerHTML = `<input type="checkbox" value="${q.id}"> ${q.nom}`;
					qualifsEl.appendChild(label);
				});
			});
		}

		function charger()
		{
			return apiFetch("/api/animateurs/").then((data) =>
			{
				list.innerHTML = "";

				if (data.length === 0)
				{
					list.innerHTML = '<p class="empty-note">Aucun animateur pour l\'instant.</p>';
					return data;
				}

				data.forEach((a) =>
				{
					const label = `<span class="truncate">${a.prenom} ${a.nom}</span>`;
					const row = ligneEntite(label, () =>
					{
						if (!confirm(`Supprimer l'animateur "${a.prenom} ${a.nom}" ? Son planning et ses disponibilités seront aussi supprimés.`)) return;

						apiFetch(`/api/animateurs/${a.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Animateur supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					});
					list.appendChild(row);
				});

				return data;
			});
		}

		container.querySelector("#anim-submit").addEventListener("click", () =>
		{
			errorEl.textContent = "";
			const prenom = prenomEl.value.trim();
			const nom = nomEl.value.trim();
			const qualifications = Array.from(qualifsEl.querySelectorAll("input:checked")).map((el) => parseInt(el.value, 10));

			if (!prenom || !nom)
			{
				errorEl.textContent = "Le prénom et le nom sont obligatoires.";
				return;
			}

			apiFetch("/api/animateurs/", { method: "POST", body: JSON.stringify({ prenom, nom, qualifications }) })
				.then((nouveau) =>
				{
					prenomEl.value = "";
					nomEl.value = "";
					qualifsEl.querySelectorAll("input:checked").forEach((el) => { el.checked = false; });
					afficherToast("Animateur ajouté.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter cet animateur."); });
		});

		chargerCheckboxesQualifs();
		charger();
		return { charger, chargerCheckboxesQualifs };
	}

	return { mountAnimateurs, mountCentres, mountQualifications };
})();
