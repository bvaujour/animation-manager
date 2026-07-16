// Page /documents/ : bibliothèque, envoi individuel aux salariés et historique.
document.addEventListener("DOMContentLoaded", () =>
{
    const app = document.getElementById("documents-app");
    initTabs(app);

    const grid = document.getElementById("documents-grid");
    const form = document.getElementById("form-upload");
    const titreInput = document.getElementById("doc-titre");
    const fichierInput = document.getElementById("doc-fichier");
    const permanentInput = document.getElementById("doc-permanent");
    const periodFields = document.getElementById("doc-period-fields");
    const debutInput = document.getElementById("doc-periode-debut");
    const finInput = document.getElementById("doc-periode-fin");
    const errorEl = document.getElementById("doc-error");

    const emailForm = document.getElementById("form-envoi-email");
    const emailConfiguration = document.getElementById("email-configuration");
    const destinatairesRoot = document.getElementById("email-destinataires");
    const documentsRoot = document.getElementById("email-documents");
    const rechercheDestinataire = document.getElementById("recherche-destinataire");
    const destinatairesCompteur = document.getElementById("destinataires-compteur");
    const documentsCompteur = document.getElementById("documents-compteur");
    const emailErreur = document.getElementById("email-erreur");
    const emailResultat = document.getElementById("email-resultat");
    const emailEnvoyer = document.getElementById("email-envoyer");
    const historiqueRoot = document.getElementById("email-historique");

    let donneesEmail = { animateurs: [], documents: [], historique: [], configuration: {} };

    function afficherChampsPeriode()
    {
        const permanent = permanentInput.checked;
        periodFields.hidden = permanent;
        debutInput.required = !permanent;
        finInput.required = !permanent;

        if (permanent)
        {
            debutInput.value = "";
            finInput.value = "";
        }
    }

    function formatTaille(octets)
    {
        if (!Number.isFinite(octets)) return "taille inconnue";
        if (octets < 1024) return `${octets} o`;
        if (octets < 1024 * 1024) return `${Math.round(octets / 1024)} Ko`;
        return `${(octets / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
    }

    function carteDocument(doc)
    {
        const extension = DocumentUtils.extension(doc.url);
        const div = document.createElement("article");
        div.classList.add("document-card");
        const typeLabel = extension ? extension.toUpperCase() : "FIC";

        div.innerHTML = `
            <div class="document-file-type" aria-hidden="true">${escapeHtml(typeLabel)}</div>
            <h3 class="document-title truncate" title="${escapeHtml(doc.titre)}">${escapeHtml(doc.titre)}</h3>
            <div class="document-actions">
                <a href="${escapeHtml(doc.url)}" target="_blank" rel="noopener" class="btn btn-ghost">Ouvrir</a>
                <button class="btn btn-ghost document-edit" type="button">Modifier</button>
                <button class="btn btn-danger" type="button" aria-label="Supprimer ${escapeHtml(doc.titre)}">&times;</button>
            </div>
        `;

        div.querySelector(".document-edit").addEventListener("click", () =>
        {
            if (div.querySelector(".document-inline-editor")) return;

            const titreId = `document-${doc.id}-titre`;
            const permanentId = `document-${doc.id}-permanent`;
            const debutId = `document-${doc.id}-debut`;
            const finId = `document-${doc.id}-fin`;
            const editor = document.createElement("form");
            editor.className = "document-inline-editor";
            editor.innerHTML = `
                <label for="${titreId}">Titre</label>
                <input type="text" id="${titreId}" name="titre" value="${escapeHtml(doc.titre)}" required>
                <label class="editor-permanent" for="${permanentId}"><input type="checkbox" id="${permanentId}" name="permanent" ${doc.permanent ? "checked" : ""}> Permanent</label>
                <div class="editor-dates" ${doc.permanent ? "hidden" : ""}>
                    <label for="${debutId}">Début</label><input type="date" id="${debutId}" name="periode_debut" value="${doc.periode_debut || ""}">
                    <label for="${finId}">Fin</label><input type="date" id="${finId}" name="periode_fin" value="${doc.periode_fin || ""}">
                </div>
                <p class="form-error"></p>
                <div class="editor-actions">
                    <button class="btn btn-primary" type="submit">Enregistrer</button>
                    <button class="btn btn-ghost editor-cancel" type="button">Annuler</button>
                </div>
            `;
            div.appendChild(editor);

            const perm = editor.elements.permanent;
            const dates = editor.querySelector(".editor-dates");
            perm.addEventListener("change", () => { dates.hidden = perm.checked; });
            editor.querySelector(".editor-cancel").addEventListener("click", () => editor.remove());

            editor.addEventListener("submit", (event) =>
            {
                event.preventDefault();
                const payload = {
                    titre: editor.elements.titre.value.trim(),
                    permanent: perm.checked,
                    periode_debut: editor.elements.periode_debut.value || null,
                    periode_fin: editor.elements.periode_fin.value || null,
                };

                apiFetch(`/api/documents/${doc.id}/`, {
                    method: "PATCH",
                    body: JSON.stringify(payload),
                }).then(() =>
                {
                    afficherToast("Document modifié.");
                    return Promise.all([chargerDocuments(), chargerPreparationEmail()]);
                }).catch((err) =>
                {
                    editor.querySelector(".form-error").textContent = erreurMessage(err, "Modification impossible.");
                });
            });
        });

        div.querySelector(".btn-danger").addEventListener("click", () =>
        {
            if (!confirm(`Supprimer le document « ${doc.titre} » ?`)) return;

            apiFetch(`/api/documents/${doc.id}/`, { method: "DELETE" })
                .then(() =>
                {
                    afficherToast("Document supprimé.");
                    return Promise.all([chargerDocuments(), chargerPreparationEmail()]);
                })
                .catch((err) => afficherToast(erreurMessage(err, "Suppression impossible."), true));
        });

        return div;
    }

    function cleGroupe(doc)
    {
        if (doc.permanent) return "permanent";
        return `${doc.periode_debut || ""}|${doc.periode_fin || ""}`;
    }

    function titreGroupe(doc)
    {
        return doc.permanent ? "Documents permanents" : doc.libelle_periode;
    }

    function afficherDocumentsGroupes(documents)
    {
        grid.innerHTML = "";
        if (documents.length === 0)
        {
            grid.innerHTML = '<p class="empty-note">Aucun document pour l\'instant.</p>';
            return;
        }

        const groupes = new Map();
        documents.forEach((doc) =>
        {
            const cle = cleGroupe(doc);
            if (!groupes.has(cle)) groupes.set(cle, { titre: titreGroupe(doc), documents: [] });
            groupes.get(cle).documents.push(doc);
        });

        groupes.forEach((groupe) =>
        {
            const section = document.createElement("section");
            section.classList.add("document-group");
            section.innerHTML = `<h2>${escapeHtml(groupe.titre)}</h2><div class="document-group-grid"></div>`;
            const groupGrid = section.querySelector(".document-group-grid");
            groupe.documents.forEach((doc) => groupGrid.appendChild(carteDocument(doc)));
            grid.appendChild(section);
        });
    }

    function chargerDocuments()
    {
        return apiFetch("/api/documents/")
            .then(afficherDocumentsGroupes)
            .catch((err) =>
            {
                grid.innerHTML = `<p class="form-error">${escapeHtml(erreurMessage(err, "Impossible de charger les documents."))}</p>`;
            });
    }

    function casesCochees(root)
    {
        return Array.from(root.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)'));
    }

    function mettreAJourCompteurs()
    {
        const nbDestinataires = casesCochees(destinatairesRoot).length;
        const documentsCoches = casesCochees(documentsRoot);
        const taille = documentsCoches.reduce((total, input) => total + Number(input.dataset.taille || 0), 0);
        destinatairesCompteur.textContent = `${nbDestinataires} salarié${nbDestinataires > 1 ? "s" : ""} sélectionné${nbDestinataires > 1 ? "s" : ""}`;
        documentsCompteur.textContent = `${documentsCoches.length} document${documentsCoches.length > 1 ? "s" : ""} — ${formatTaille(taille)}`;
    }

    function afficherDestinataires()
    {
        destinatairesRoot.innerHTML = "";
        if (!donneesEmail.animateurs.length)
        {
            destinatairesRoot.innerHTML = '<p class="empty-note">Aucun salarié enregistré.</p>';
            return;
        }

        donneesEmail.animateurs.forEach((animateur) =>
        {
            const id = `destinataire-${animateur.id}`;
            const label = document.createElement("label");
            label.className = "email-checkbox-option";
            const emailValide = Boolean(animateur.email);
            if (!emailValide) label.classList.add("disabled");
            const indexRecherche = [
                animateur.prenom,
                animateur.nom,
                animateur.email,
                ...(animateur.qualifications || []),
                ...(animateur.lieux || []),
            ].join(" ").toLocaleLowerCase("fr");
            label.dataset.recherche = indexRecherche;
            label.innerHTML = `
                <input type="checkbox" id="${id}" name="animateur_ids" value="${animateur.id}" ${emailValide ? "" : "disabled"}>
                <span class="email-option-main">
                    <strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong>
                    <small>${emailValide ? escapeHtml(animateur.email) : "Adresse e-mail à renseigner dans Gestion"}</small>
                </span>
                ${emailValide ? "" : '<span class="email-missing-badge">E-mail manquant</span>'}
            `;
            label.querySelector("input").addEventListener("change", mettreAJourCompteurs);
            destinatairesRoot.appendChild(label);
        });
    }

    function afficherDocumentsEmail()
    {
        documentsRoot.innerHTML = "";
        if (!donneesEmail.documents.length)
        {
            documentsRoot.innerHTML = '<p class="empty-note">Ajoute d’abord un document dans la bibliothèque.</p>';
            return;
        }

        donneesEmail.documents.forEach((doc) =>
        {
            const id = `piece-jointe-${doc.id}`;
            const label = document.createElement("label");
            label.className = "email-checkbox-option";
            label.innerHTML = `
                <input type="checkbox" id="${id}" name="document_ids" value="${doc.id}" data-taille="${Number(doc.taille || 0)}">
                <span class="email-option-main">
                    <strong>${escapeHtml(doc.titre)}</strong>
                    <small>${escapeHtml(doc.libelle_periode)} · ${escapeHtml(formatTaille(doc.taille))}</small>
                </span>
            `;
            label.querySelector("input").addEventListener("change", mettreAJourCompteurs);
            documentsRoot.appendChild(label);
        });
    }

    function afficherConfiguration()
    {
        const config = donneesEmail.configuration || {};
        emailConfiguration.className = "email-configuration";
        if (!config.operationnel) emailConfiguration.classList.add("error");
        else if (config.mode_test) emailConfiguration.classList.add("test");
        else emailConfiguration.classList.add("success");
        emailConfiguration.textContent = config.message || "Configuration e-mail inconnue.";
        emailEnvoyer.disabled = !config.operationnel;
    }

    function afficherHistorique()
    {
        historiqueRoot.innerHTML = "";
        const historique = donneesEmail.historique || [];
        if (!historique.length)
        {
            historiqueRoot.innerHTML = '<p class="empty-note">Aucun e-mail envoyé pour l’instant.</p>';
            return;
        }

        historique.forEach((envoi) =>
        {
            const article = document.createElement("article");
            article.className = "email-history-card";
            const date = new Date(envoi.date_creation).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" });
            const statutClasse = envoi.nombre_echecs ? "warning" : "success";
            article.innerHTML = `
                <div class="history-card-main">
                    <div>
                        <h3>${escapeHtml(envoi.objet)}</h3>
                        <p>${escapeHtml(date)}${envoi.mode_test ? " · Mode test" : ""}</p>
                    </div>
                    <span class="history-status ${statutClasse}">${envoi.nombre_envoyes} envoyé${envoi.nombre_envoyes > 1 ? "s" : ""}${envoi.nombre_echecs ? ` · ${envoi.nombre_echecs} échec${envoi.nombre_echecs > 1 ? "s" : ""}` : ""}</span>
                </div>
                <p class="history-documents"><strong>Documents :</strong> ${envoi.documents.length ? envoi.documents.map(escapeHtml).join(", ") : "Aucun"}</p>
                <div class="history-errors"></div>
            `;
            const errors = article.querySelector(".history-errors");
            if (envoi.echecs && envoi.echecs.length)
            {
                const details = document.createElement("details");
                details.innerHTML = `<summary>Voir les échecs</summary><ul>${envoi.echecs.map((echec) => `<li><strong>${escapeHtml(echec.prenom)} ${escapeHtml(echec.nom)}</strong> (${escapeHtml(echec.email)}) : ${escapeHtml(echec.erreur || "Erreur inconnue")}</li>`).join("")}</ul>`;
                errors.appendChild(details);
            }
            historiqueRoot.appendChild(article);
        });
    }

    function chargerPreparationEmail()
    {
        return apiFetch("/api/envois-email/").then((data) =>
        {
            donneesEmail = data;
            afficherConfiguration();
            afficherDestinataires();
            afficherDocumentsEmail();
            afficherHistorique();
            mettreAJourCompteurs();
            rechercheDestinataire.dispatchEvent(new Event("input"));
        }).catch((err) =>
        {
            emailConfiguration.className = "email-configuration error";
            emailConfiguration.textContent = erreurMessage(err, "Impossible de préparer l'envoi d'e-mails.");
            emailEnvoyer.disabled = true;
        });
    }

    function cocherTout(root, checked, visiblesSeulement = false)
    {
        root.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((input) =>
        {
            const option = input.closest(".email-checkbox-option");
            if (!visiblesSeulement || !option.hidden) input.checked = checked;
        });
        mettreAJourCompteurs();
    }

    rechercheDestinataire.addEventListener("input", () =>
    {
        const recherche = rechercheDestinataire.value.trim().toLocaleLowerCase("fr");
        destinatairesRoot.querySelectorAll(".email-checkbox-option").forEach((option) =>
        {
            option.hidden = Boolean(recherche) && !option.dataset.recherche.includes(recherche);
        });
    });

    document.getElementById("destinataires-tous").addEventListener("click", () => cocherTout(destinatairesRoot, true, true));
    document.getElementById("destinataires-aucun").addEventListener("click", () => cocherTout(destinatairesRoot, false));
    document.getElementById("documents-tous").addEventListener("click", () => cocherTout(documentsRoot, true));
    document.getElementById("documents-aucun").addEventListener("click", () => cocherTout(documentsRoot, false));
    document.getElementById("historique-actualiser").addEventListener("click", chargerPreparationEmail);

    emailForm.addEventListener("submit", (event) =>
    {
        event.preventDefault();
        emailErreur.textContent = "";
        emailResultat.hidden = true;

        const animateurIds = casesCochees(destinatairesRoot).map((input) => Number(input.value));
        const documentIds = casesCochees(documentsRoot).map((input) => Number(input.value));
        const objet = document.getElementById("email-objet").value.trim();
        const message = document.getElementById("email-message").value.trim();

        if (!animateurIds.length)
        {
            emailErreur.textContent = "Choisis au moins un salarié.";
            return;
        }
        if (!documentIds.length)
        {
            emailErreur.textContent = "Choisis au moins un document.";
            return;
        }
        if (!objet || !message)
        {
            emailErreur.textContent = "L'objet et le message sont obligatoires.";
            return;
        }
        if (!confirm(`Envoyer ce message séparément à ${animateurIds.length} salarié${animateurIds.length > 1 ? "s" : ""} ?`)) return;

        emailEnvoyer.disabled = true;
        const ancienLibelle = emailEnvoyer.textContent;
        emailEnvoyer.textContent = "Envoi en cours…";

        apiFetch("/api/envois-email/", {
            method: "POST",
            body: JSON.stringify({
                animateur_ids: animateurIds,
                document_ids: documentIds,
                objet,
                message,
            }),
        }).then((resultat) =>
        {
            emailResultat.hidden = false;
            emailResultat.className = `email-resultat ${resultat.nombre_echecs ? "warning" : "success"}`;
            const mode = resultat.mode_test ? " en mode test" : "";
            emailResultat.textContent = `${resultat.nombre_envoyes} e-mail${resultat.nombre_envoyes > 1 ? "s" : ""} envoyé${resultat.nombre_envoyes > 1 ? "s" : ""}${mode}${resultat.nombre_echecs ? `, ${resultat.nombre_echecs} en échec` : ""}.`;
            if (!resultat.nombre_echecs)
            {
                emailForm.reset();
                rechercheDestinataire.value = "";
            }
            afficherToast(resultat.nombre_echecs ? "Envoi terminé avec des échecs." : "E-mails envoyés.", Boolean(resultat.nombre_echecs));
            return chargerPreparationEmail();
        }).catch((err) =>
        {
            emailErreur.textContent = erreurMessage(err, "L'envoi a échoué.");
        }).finally(() =>
        {
            emailEnvoyer.textContent = ancienLibelle;
            emailEnvoyer.disabled = !(donneesEmail.configuration || {}).operationnel;
        });
    });

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
        if (!permanentInput.checked && (!debutInput.value || !finInput.value))
        {
            errorEl.textContent = "Renseigne une date de début et une date de fin.";
            return;
        }

        const donnees = new FormData();
        donnees.append("titre", titreInput.value.trim());
        donnees.append("fichier", fichier);
        donnees.append("permanent", permanentInput.checked ? "true" : "false");
        donnees.append("periode_debut", debutInput.value);
        donnees.append("periode_fin", finInput.value);

        fetch("/api/documents/", {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken() },
            body: donnees,
        }).then((response) =>
        {
            if (!response.ok) return response.json().then((err) => { throw err; });
            return response.json();
        }).then(() =>
        {
            form.reset();
            permanentInput.checked = true;
            afficherChampsPeriode();
            afficherToast("Document ajouté.");
            return Promise.all([chargerDocuments(), chargerPreparationEmail()]);
        }).catch((err) =>
        {
            errorEl.textContent = erreurMessage(err, "Impossible d'ajouter ce document.");
        });
    });

    permanentInput.addEventListener("change", afficherChampsPeriode);
    afficherChampsPeriode();
    chargerDocuments();
    chargerPreparationEmail();
});
