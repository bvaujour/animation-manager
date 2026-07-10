// ===========================================================================
// gestion.js
// ---------------------------------------------------------------------------
// Module CRUD partagé pour la page /gestion/ et la modal d'ajout rapide du
// planning. Cette version permet maintenant :
//   - d'ajouter ;
//   - de modifier les entrées existantes ;
//   - de supprimer ;
//   - de modifier tous les champs disponibles pour les 3 tables gérées ici :
//     Animateur, Centre, Qualification.
// ===========================================================================

const GestionApp = (function ()
{
	function escapeHtml(value)
	{
		return String(value ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll("\"", "&quot;")
			.replaceAll("'", "&#039;");
	}

	function champValeur(form, selector)
	{
		return form.querySelector(selector).value.trim();
	}

	function idsCheckboxesCochees(root)
	{
		return Array.from(root.querySelectorAll("input:checked")).map((el) => parseInt(el.value, 10));
	}

	function bouton(label, classes, onClick)
	{
		const btn = document.createElement("button");
		btn.type = "button";
		btn.className = classes;
		btn.innerHTML = label;
		btn.addEventListener("click", onClick);
		return btn;
	}

	function creerFormActions(onSave, onCancel)
	{
		const actions = document.createElement("div");
		actions.classList.add("edit-actions");
		actions.appendChild(bouton("Enregistrer", "btn btn-primary", onSave));
		actions.appendChild(bouton("Annuler", "btn btn-ghost", onCancel));
		return actions;
	}

	function resetFormAnimateur(form)
	{
		form.querySelector("#anim-prenom").value = "";
		form.querySelector("#anim-nom").value = "";
		form.querySelector("#anim-telephone").value = "";
		form.querySelector("#anim-email").value = "";
		form.querySelector("#anim-date-naissance").value = "";
		form.querySelectorAll("#anim-qualifs input:checked").forEach((el) => { el.checked = false; });
		form.querySelectorAll("#anim-centres input:checked").forEach((el) => { el.checked = false; });
	}

	function qualificationCheckboxes(qualifications, cochees = [])
	{
		if (!qualifications.length)
		{
			return '<p class="empty-note">Aucune qualification disponible.</p>';
		}

		const cocheesSet = new Set(cochees.map(Number));

		return qualifications.map((q) => `
			<label class="checkbox-chip">
				<input type="checkbox" value="${escapeHtml(q.id)}" ${cocheesSet.has(q.id) ? "checked" : ""}>
				${escapeHtml(q.nom)}
			</label>
		`).join("");
	}


	function centresAutorisesInputs(centres, centresAutorises = [])
	{
		if (!centres.length)
		{
			return '<p class="empty-note">Ajoute d\'abord des centres pour pouvoir choisir où affecter l\'animateur.</p>';
		}

		const centresSet = new Set((centresAutorises || []).map((centre) => Number(centre.id ?? centre)));

		return centres.map((centre) => `
			<label class="checkbox-chip centre-chip-option">
				<input type="checkbox" value="${escapeHtml(centre.id)}" ${centresSet.has(Number(centre.id)) ? "checked" : ""}>
				<span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>
				${escapeHtml(centre.code || centre.nom)}
			</label>
		`).join("");
	}

	function centresAutorisesDepuisForm(root)
	{
		return idsCheckboxesCochees(root);
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
			<div class="gestion-form" id="qualif-form">
				<div class="field">
					<label for="qualif-nom">Nom</label>
					<input type="text" id="qualif-nom" placeholder="ex : BAFA">
				</div>
				<p class="form-error" id="qualif-error"></p>
				<button class="btn btn-primary" id="qualif-submit" type="button">Ajouter</button>
			</div>
		`;

		const list = container.querySelector("#qualifs-list");
		const input = container.querySelector("#qualif-nom");
		const errorEl = container.querySelector("#qualif-error");

		function ouvrirEdition(q, row)
		{
			row.classList.add("entity-row-editing");
			row.innerHTML = `
				<div class="edit-grid edit-grid-single">
					<div class="field">
						<label>Nom</label>
						<input type="text" class="edit-qualif-nom" value="${escapeHtml(q.nom)}">
					</div>
					<p class="form-error edit-error"></p>
				</div>
			`;

			const error = row.querySelector(".edit-error");
			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const nom = champValeur(row, ".edit-qualif-nom");

				if (!nom)
				{
					error.textContent = "Le nom est obligatoire.";
					return;
				}

				apiFetch(`/api/qualifications/${escapeHtml(q.id)}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom }),
				}).then(() =>
				{
					afficherToast("Qualification modifiée.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Modification impossible."); });
			}, charger));
		}

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
					const row = document.createElement("div");
					row.classList.add("entity-row");
					row.innerHTML = `
						<div class="entity-main"><span class="truncate">${escapeHtml(q.nom)}</span></div>
						<div class="entity-actions"></div>
					`;

					const actions = row.querySelector(".entity-actions");
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEdition(q, row)));
					actions.appendChild(bouton("&times; Supprimer", "btn-danger", () =>
					{
						if (!confirm(`Supprimer la qualification "${escapeHtml(q.nom)}" ?`)) return;

						apiFetch(`/api/qualifications/${escapeHtml(q.id)}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Qualification supprimée.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					}));

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
			<div class="gestion-form" id="centre-form">
				<div class="field">
					<label for="centre-nom">Nom</label>
					<input type="text" id="centre-nom" placeholder="ex : Pacaudière">
				</div>
				<div class="field">
					<label for="centre-code">Code</label>
					<input type="text" id="centre-code" placeholder="ex : PAC" maxlength="10">
				</div>
				<div class="field">
					<label for="centre-couleur">Couleur</label>
					<input type="color" id="centre-couleur" value="#1f6f54">
				</div>
				<div class="field">
					<label for="centre-effectif">Animateurs par jour souhaités</label>
					<input type="number" id="centre-effectif" value="1" min="1" step="1">
				</div>
				<p class="form-error" id="centre-error"></p>
				<button class="btn btn-primary" id="centre-submit" type="button">Ajouter</button>
			</div>
		`;

		const list = container.querySelector("#centres-list");
		const nomEl = container.querySelector("#centre-nom");
		const codeEl = container.querySelector("#centre-code");
		const couleurEl = container.querySelector("#centre-couleur");
		const effectifEl = container.querySelector("#centre-effectif");
		const errorEl = container.querySelector("#centre-error");

		function ouvrirEdition(c, row)
		{
			row.classList.add("entity-row-editing");
			row.innerHTML = `
				<div class="edit-grid">
					<div class="field">
						<label>Nom</label>
						<input type="text" class="edit-centre-nom" value="${escapeHtml(c.nom)}">
					</div>
					<div class="field">
						<label>Code</label>
						<input type="text" class="edit-centre-code" value="${escapeHtml(c.code)}" maxlength="10">
					</div>
					<div class="field">
						<label>Couleur</label>
						<input type="color" class="edit-centre-couleur" value="${escapeHtml(c.couleur)}">
					</div>
					<div class="field">
						<label>Animateurs par jour souhaités</label>
						<input type="number" class="edit-centre-effectif" value="${c.effectif_cible}" min="1" step="1">
					</div>
					<p class="form-error edit-error"></p>
				</div>
			`;

			const error = row.querySelector(".edit-error");
			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const nom = champValeur(row, ".edit-centre-nom");
				const code = champValeur(row, ".edit-centre-code");
				const couleur = champValeur(row, ".edit-centre-couleur");
				const effectif_cible = parseInt(champValeur(row, ".edit-centre-effectif"), 10) || 1;

				if (!nom || !code)
				{
					error.textContent = "Le nom et le code sont obligatoires.";
					return;
				}

				apiFetch(`/api/centres/${escapeHtml(c.id)}/`, {
					method: "PATCH",
					body: JSON.stringify({ nom, code, couleur, effectif_cible }),
				}).then(() =>
				{
					afficherToast("Centre modifié.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Modification impossible."); });
			}, charger));
		}

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
					const row = document.createElement("div");
					row.classList.add("entity-row");
					row.innerHTML = `
						<div class="entity-main">
							<span class="swatch" style="background:${escapeHtml(c.couleur)}"></span>
							<span class="truncate">${escapeHtml(c.nom)} (${escapeHtml(c.code)})</span>
							<small class="entity-muted">${escapeHtml(c.effectif_cible)} / jour</small>
						</div>
						<div class="entity-actions"></div>
					`;

					const actions = row.querySelector(".entity-actions");
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEdition(c, row)));
					actions.appendChild(bouton("&times; Supprimer", "btn-danger", () =>
					{
						if (!confirm(`Supprimer le centre "${c.nom}" ? Ses affectations et centres autorisés liés seront aussi supprimées.`)) return;

						apiFetch(`/api/centres/${escapeHtml(c.id)}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Centre supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					}));

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
			const effectif_cible = parseInt(effectifEl.value, 10) || 1;

			if (!nom || !code)
			{
				errorEl.textContent = "Le nom et le code sont obligatoires.";
				return;
			}

			apiFetch("/api/centres/", { method: "POST", body: JSON.stringify({ nom, code, couleur, effectif_cible }) })
				.then((nouveau) =>
				{
					nomEl.value = "";
					codeEl.value = "";
					effectifEl.value = "1";
					afficherToast("Centre ajouté.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce centre."); });
		});

		charger();
		return { charger };
	}

	// ------------------------------------------------------------------
	// Animateurs
	// ------------------------------------------------------------------
	function mountAnimateurs(container, options = {})
	{
		let qualificationsCache = [];
		let centresCache = [];

		container.innerHTML = `
			<p class="section-title">Animateurs existants</p>
			<div class="entity-list" id="anims-list"></div>
			<p class="section-title">Ajouter un animateur</p>
			<div class="gestion-form" id="anim-form">
				<div class="field">
					<label for="anim-prenom">Prénom</label>
					<input type="text" id="anim-prenom">
				</div>
				<div class="field">
					<label for="anim-nom">Nom</label>
					<input type="text" id="anim-nom">
				</div>
				<div class="field">
					<label for="anim-telephone">Téléphone</label>
					<input type="tel" id="anim-telephone" placeholder="ex : 07 82 35 18 87">
				</div>
				<div class="field">
					<label for="anim-email">Email</label>
					<input type="email" id="anim-email" placeholder="ex : prenom.nom@mail.com">
				</div>
				<div class="field">
					<label for="anim-date-naissance">Date de naissance</label>
					<input type="date" id="anim-date-naissance">
				</div>
				<div class="field">
					<label>Qualifications</label>
					<div class="checkbox-grid" id="anim-qualifs"></div>
				</div>
				<div class="field field-wide">
					<label>Centres possibles</label>
					<div class="checkbox-grid" id="anim-centres"></div>
					<small class="entity-muted">Coche les centres où cet animateur peut être affecté.</small>
				</div>
				<p class="form-error" id="anim-error"></p>
				<button class="btn btn-primary" id="anim-submit" type="button">Ajouter</button>
			</div>
		`;

		const list = container.querySelector("#anims-list");
		const form = container.querySelector("#anim-form");
		const prenomEl = container.querySelector("#anim-prenom");
		const nomEl = container.querySelector("#anim-nom");
		const telephoneEl = container.querySelector("#anim-telephone");
		const emailEl = container.querySelector("#anim-email");
		const dateNaissanceEl = container.querySelector("#anim-date-naissance");
		const qualifsEl = container.querySelector("#anim-qualifs");
		const centresEl = container.querySelector("#anim-centres");
		const errorEl = container.querySelector("#anim-error");

		function chargerCheckboxesQualifs()
		{
			return apiFetch("/api/qualifications/").then((data) =>
			{
				qualificationsCache = data;
				qualifsEl.innerHTML = qualificationCheckboxes(data);
				return data;
			});
		}

		function chargerCentresAutorises()
		{
			return apiFetch("/api/centres/").then((data) =>
			{
				centresCache = data;
				centresEl.innerHTML = centresAutorisesInputs(data);
				return data;
			});
		}

		function ouvrirEdition(a, row)
		{
			row.classList.add("entity-row-editing");
			row.innerHTML = `
				<div class="edit-grid">
					<div class="field">
						<label>Prénom</label>
						<input type="text" class="edit-anim-prenom" value="${escapeHtml(a.prenom)}">
					</div>
					<div class="field">
						<label>Nom</label>
						<input type="text" class="edit-anim-nom" value="${escapeHtml(a.nom)}">
					</div>
					<div class="field">
						<label>Téléphone</label>
						<input type="tel" class="edit-anim-telephone" value="${escapeHtml(a.telephone || "")}">
					</div>
					<div class="field">
						<label>Email</label>
						<input type="email" class="edit-anim-email" value="${escapeHtml(a.email || "")}">
					</div>
					<div class="field">
						<label>Date de naissance</label>
						<input type="date" class="edit-anim-date-naissance" value="${a.date_naissance || ""}">
					</div>
					<div class="field">
						<label>Couleur planning</label>
						<input type="color" class="edit-anim-couleur" value="${escapeHtml(a.couleur || "#2563EB")}">
					</div>
					<div class="field edit-qualifs-field">
						<label>Qualifications</label>
						<div class="checkbox-grid edit-anim-qualifs">
							${qualificationCheckboxes(qualificationsCache, a.qualification_ids || [])}
						</div>
					</div>
					<div class="field edit-qualifs-field">
						<label>Centres possibles</label>
						<div class="checkbox-grid edit-anim-centres">
							${centresAutorisesInputs(centresCache, a.centres_autorises || [])}
						</div>
					</div>
					<p class="form-error edit-error"></p>
				</div>
			`;

			const error = row.querySelector(".edit-error");
			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const prenom = champValeur(row, ".edit-anim-prenom");
				const nom = champValeur(row, ".edit-anim-nom");
				const telephone = champValeur(row, ".edit-anim-telephone");
				const email = champValeur(row, ".edit-anim-email");
				const date_naissance = row.querySelector(".edit-anim-date-naissance").value || null;
				const couleur = row.querySelector(".edit-anim-couleur").value;
				const qualifications = idsCheckboxesCochees(row.querySelector(".edit-anim-qualifs"));
				const centres_autorises = centresAutorisesDepuisForm(row.querySelector(".edit-anim-centres"));

				if (!prenom || !nom)
				{
					error.textContent = "Le prénom et le nom sont obligatoires.";
					return;
				}

				apiFetch(`/api/animateurs/${a.id}/`, {
					method: "PATCH",
					body: JSON.stringify({ prenom, nom, telephone, email, date_naissance, couleur, qualifications, centres_autorises }),
				}).then(() =>
				{
					afficherToast("Animateur modifié.");
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Modification impossible."); });
			}, charger));
		}


		function ouvrirDisponibilites(a, row)
		{
			row.classList.add("entity-row-editing");
			row.innerHTML = `
				<div class="entity-main entity-main-stack">
					<strong>Disponibilités de ${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}</strong>
					<small class="entity-muted">Ajoute une plage rapidement. Si aucune disponibilité n'est renseignée, l'animateur est considéré disponible par défaut.</small>
				</div>
				<div class="dispos-list" id="edit-dispos-list"></div>
				<div class="edit-grid">
					<div class="field">
						<label>Début</label>
						<input type="date" class="edit-dispo-debut">
					</div>
					<div class="field">
						<label>Fin incluse</label>
						<input type="date" class="edit-dispo-fin">
					</div>
					<p class="form-error edit-error"></p>
				</div>
			`;

			const listDispos = row.querySelector("#edit-dispos-list");
			const debutEl = row.querySelector(".edit-dispo-debut");
			const finEl = row.querySelector(".edit-dispo-fin");
			const error = row.querySelector(".edit-error");

			function afficherDispos(plages)
			{
				if (!plages || plages.length === 0)
				{
					listDispos.innerHTML = '<p class="empty-note">Aucune disponibilité renseignée.</p>';
					return;
				}

				listDispos.innerHTML = plages.map((plage) => `
					<span class="dispo-chip">${escapeHtml(plage.debut)} → ${escapeHtml(plage.fin)}</span>
				`).join("");
			}

			function rechargerDispos()
			{
				return apiFetch(`/api/animateurs/${a.id}/disponibilites/`)
					.then((data) => afficherDispos(data.disponibilites));
			}

			row.appendChild(creerFormActions(() =>
			{
				error.textContent = "";
				const debut = debutEl.value;
				const fin = finEl.value || debut;

				if (!debut || !fin)
				{
					error.textContent = "Les dates sont obligatoires.";
					return;
				}

				apiFetch(`/api/animateurs/${a.id}/disponibilites/`, {
					method: "POST",
					body: JSON.stringify({ debut, fin }),
				}).then(() =>
				{
					debutEl.value = "";
					finEl.value = "";
					afficherToast("Disponibilité ajoutée.");
					rechargerDispos();
					charger();
					if (options.onChange) options.onChange();
				}).catch((err) => { error.textContent = erreurMessage(err, "Impossible d'ajouter cette disponibilité."); });
			}, charger));

			rechargerDispos();
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
					const details = [
						a.age ? `${a.age} ans` : null,
						a.telephone || null,
						a.email || null,
						a.qualifications && a.qualifications.length ? a.qualifications.join(", ") : null,
					a.centres_autorises && a.centres_autorises.length ? `Centres : ${a.centres_autorises.map((c) => c.code).join(" / ")}` : null,
					].filter(Boolean).join(" · ");

					const row = document.createElement("div");
					row.classList.add("entity-row");
					row.style.setProperty("--animateur-color", a.couleur || "#94a3b8");
					row.innerHTML = `
						<div class="entity-main entity-main-stack">
							<span class="truncate">${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}</span>
							${details ? `<small class="entity-muted">${escapeHtml(details)}</small>` : ""}
						</div>
						<div class="entity-actions"></div>
					`;

					const actions = row.querySelector(".entity-actions");
					actions.appendChild(bouton("Modifier", "btn btn-ghost", () => ouvrirEdition(a, row)));
					actions.appendChild(bouton("Dispos", "btn btn-ghost", () => ouvrirDisponibilites(a, row)));
					actions.appendChild(bouton("&times; Supprimer", "btn-danger", () =>
					{
						if (!confirm(`Supprimer l'animateur "${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}" ? Son planning et ses disponibilités seront aussi supprimés.`)) return;

						apiFetch(`/api/animateurs/${a.id}/`, { method: "DELETE" })
							.then(() =>
							{
								afficherToast("Animateur supprimé.");
								charger();
								if (options.onChange) options.onChange();
							})
							.catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
					}));

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
			const telephone = telephoneEl.value.trim();
			const email = emailEl.value.trim();
			const date_naissance = dateNaissanceEl.value || null;
			const qualifications = idsCheckboxesCochees(qualifsEl);
			const centres_autorises = centresAutorisesDepuisForm(centresEl);

			if (!prenom || !nom)
			{
				errorEl.textContent = "Le prénom et le nom sont obligatoires.";
				return;
			}

			apiFetch("/api/animateurs/", {
				method: "POST",
				body: JSON.stringify({ prenom, nom, telephone, email, date_naissance, qualifications, centres_autorises }),
			})
				.then((nouveau) =>
				{
					resetFormAnimateur(form);
					afficherToast("Animateur ajouté.");
					charger();
					if (options.onChange) options.onChange(nouveau);
				})
				.catch((err) => { errorEl.textContent = erreurMessage(err, "Impossible d'ajouter cet animateur."); });
		});

		Promise.all([chargerCheckboxesQualifs(), chargerCentresAutorises()]).then(charger);
		return { charger, chargerCheckboxesQualifs, chargerCentresAutorises };
	}

	return { mountAnimateurs, mountCentres, mountQualifications };
})();
