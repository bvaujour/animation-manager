document.addEventListener("DOMContentLoaded", () => {
    const app = document.getElementById("emails-app");
    if (!app) return;

    initTabs(app);

    const form = document.getElementById("form-envoi-email");
    const configuration = document.getElementById("email-configuration");
    const destinatairesRoot = document.getElementById("email-destinataires");
    const contactsRoot = document.getElementById("email-contacts-externes");
    const documentsRoot = document.getElementById("email-documents");
    const recherche = document.getElementById("recherche-destinataire");
    const filtreQualifications = document.getElementById("filtre-destinataire-qualifications");
    const filtreDisponibilite = document.getElementById("filtre-destinataire-disponibilite");
    const filtreAffectation = document.getElementById("filtre-destinataire-affectation");
    const filtreCentres = document.getElementById("filtre-destinataire-centres");
    const filtreCompteur = document.getElementById("email-filter-count");
    const filtreReset = document.getElementById("email-filter-reset");
    const filtreInfo = document.getElementById("destinataires-filtres-info");
    const compteurDest = document.getElementById("destinataires-compteur");
    const compteurDocs = document.getElementById("documents-compteur");
    const erreur = document.getElementById("email-erreur");
    const resultat = document.getElementById("email-resultat");
    const envoyer = document.getElementById("email-envoyer");
    const modeleSelect = document.getElementById("email-modele");
    const semainesPicker = document.getElementById("email-semaines-picker");
    const variablesRoot = document.getElementById("email-variables");
    const objetInput = document.getElementById("email-objet");
    const messageInput = document.getElementById("email-message");

    const modeleForm = document.getElementById("modele-email-form");
    const modeleIdInput = document.getElementById("modele-email-id");
    const modeleNomInput = document.getElementById("modele-email-nom");
    const modeleObjetInput = document.getElementById("modele-email-objet");
    const modeleMessageInput = document.getElementById("modele-email-message");
    const modeleActifInput = document.getElementById("modele-email-actif");
    const modeleTitre = document.getElementById("modele-email-form-title");
    const modeleErreur = document.getElementById("modele-email-erreur");
    const modeleSupprimer = document.getElementById("modele-email-supprimer");
    const modelesListe = document.getElementById("modeles-email-liste");
    const modelesCompteur = document.getElementById("modeles-compteur");
    const modeleVariablesRoot = document.getElementById("modele-email-variables");

    let champVariableActif = messageInput;
    let champVariableModeleActif = modeleMessageInput;
    let donnees = {
        animateurs: [],
        contacts_externes: [],
        documents: [],
        modeles: [],
        variables: [],
        periodes: [],
        qualifications: [],
        configuration: {},
    };
    let modelesGestion = [];
    const filtreQualificationIds = new Set();
    const filtreCentreIds = new Set();

    const contactForm = document.getElementById("contact-email-form");
    const contactId = document.getElementById("contact-email-id");
    const contactPrenom = document.getElementById("contact-email-prenom");
    const contactNom = document.getElementById("contact-email-nom");
    const contactAdresse = document.getElementById("contact-email-adresse");
    const contactOrganisation = document.getElementById("contact-email-organisation");
    const contactErreur = document.getElementById("contact-email-erreur");
    const contactSupprimer = document.getElementById("contact-email-supprimer");
    const contactEnregistrer = document.getElementById("contact-email-enregistrer");

    const cases = (root) => Array.from(root.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)'));

    function formatTaille(octets) {
        if (!Number.isFinite(Number(octets))) return "taille inconnue";
        const valeur = Number(octets);
        if (valeur < 1024) return `${valeur} o`;
        if (valeur < 1048576) return `${Math.round(valeur / 1024)} Ko`;
        return `${(valeur / 1048576).toFixed(1).replace(".", ",")} Mo`;
    }

    function compteurs() {
        const nombre = cases(destinatairesRoot).length + cases(contactsRoot).length;
        const documents = cases(documentsRoot);
        const taille = documents.reduce((total, input) => total + Number(input.dataset.taille || 0), 0);
        compteurDest.textContent = `${nombre} destinataire${nombre > 1 ? "s" : ""} sélectionné${nombre > 1 ? "s" : ""}`;
        compteurDocs.textContent = `${documents.length} document${documents.length > 1 ? "s" : ""} — ${formatTaille(taille)}`;
    }

    function selecteurSemaines() {
        return WeekPicker.get(semainesPicker);
    }

    function idsSemainesSelectionnees() {
        return selecteurSemaines()?.getSelectedIds() || [];
    }

    function periodesSelectionnees() {
        const picker = selecteurSemaines();
        if (picker?.ready) return picker.getSelectedPeriods();
        const ids = new Set(idsSemainesSelectionnees().map(String));
        return [...(donnees.periodes || [])]
            .filter((periode) => ids.has(String(periode.id)))
            .sort((a, b) => String(a.debut).localeCompare(String(b.debut)));
    }

    function formatDateFr(iso) {
        const [annee, mois, jour] = String(iso || "").split("-");
        return annee && mois && jour ? `${jour}/${mois}/${annee}` : String(iso || "");
    }

    function afficherConfiguration() {
        const statut = donnees.configuration || {};
        configuration.className = `email-configuration ${!statut.operationnel ? "error" : statut.mode_test ? "test" : "success"}`;
        configuration.textContent = statut.message || "Configuration e-mail inconnue.";
        envoyer.disabled = !statut.operationnel;
    }


    function chevauchePeriode(plage, periode, finExclusive = false) {
        if (!plage || !periode) return false;
        const debut = String(plage.debut || "");
        const fin = String(plage.fin || "");
        if (!debut || !fin) return false;
        return finExclusive
            ? debut <= periode.fin && fin > periode.debut
            : debut <= periode.fin && fin >= periode.debut;
    }

    function remplirFiltresAnnuaire() {
        const qualificationsDisponibles = donnees.qualifications || [];
        const qualificationIdsDisponibles = new Set(qualificationsDisponibles.map((item) => Number(item.id)));
        [...filtreQualificationIds].forEach((id) => {
            if (!qualificationIdsDisponibles.has(Number(id))) filtreQualificationIds.delete(id);
        });
        StaffFilterUI.renderOptions(filtreQualifications, qualificationsDisponibles, {
            selected: filtreQualificationIds,
            emptyText: "Aucune qualification",
            name: "email_filter_qualification",
            onChange: (input) => {
                const id = Number(input.value);
                if (input.checked) filtreQualificationIds.add(id);
                else filtreQualificationIds.delete(id);
                appliquerFiltresDestinataires();
            },
        });

        const centres = new Map();
        (donnees.animateurs || []).forEach((animateur) => {
            const centre = animateur.centre_prefere;
            if (centre?.id) centres.set(Number(centre.id), { id: Number(centre.id), nom: centre.nom || centre.code || `Centre ${centre.id}` });
        });
        const centresDisponibles = [...centres.values()];
        const centreIdsDisponibles = new Set(centresDisponibles.map((item) => Number(item.id)));
        [...filtreCentreIds].forEach((id) => {
            if (!centreIdsDisponibles.has(Number(id))) filtreCentreIds.delete(id);
        });
        StaffFilterUI.renderOptions(filtreCentres, centresDisponibles, {
            selected: filtreCentreIds,
            emptyText: "Aucun centre",
            name: "email_filter_centre",
            onChange: (input) => {
                const id = Number(input.value);
                if (input.checked) filtreCentreIds.add(id);
                else filtreCentreIds.delete(id);
                appliquerFiltresDestinataires();
            },
        });
    }

    function appliquerFiltresDestinataires() {
        const requete = recherche.value.trim().toLocaleLowerCase("fr");
        const disponibilite = filtreDisponibilite?.value || "";
        const affectation = filtreAffectation?.value || "";
        const periodes = periodesSelectionnees();
        let visibles = 0;
        const animateursParId = new Map(
            (donnees.animateurs || []).map((animateur) => [String(animateur.id), animateur])
        );

        destinatairesRoot.querySelectorAll(".email-checkbox-option").forEach((option) => {
            const animateur = animateursParId.get(option.dataset.animateurId);
            const correspondRecherche = !requete || option.dataset.recherche.includes(requete);
            const qualificationsAnimateur = new Set((animateur?.qualification_ids || []).map(Number));
            const correspondQualification = !filtreQualificationIds.size
                || [...filtreQualificationIds].every((id) => qualificationsAnimateur.has(Number(id)));
            const estDisponible = Boolean(periodes.length && periodes.some((periode) =>
                (animateur?.disponibilites || []).some((plage) => chevauchePeriode(plage, periode))
            ));
            const estAffecte = Boolean(periodes.length && periodes.some((periode) =>
                (animateur?.affectations || []).some((plage) => chevauchePeriode(plage, periode, true))
            ));
            const correspondCentre = !filtreCentreIds.size
                || filtreCentreIds.has(Number(animateur?.centre_prefere?.id));
            const correspondDisponibilite = !disponibilite
                || (periodes.length > 0 && disponibilite === "disponible" && estDisponible)
                || (periodes.length > 0 && disponibilite === "indisponible" && !estDisponible);
            const correspondAffectation = !affectation
                || (periodes.length > 0 && affectation === "affecte" && estAffecte)
                || (periodes.length > 0 && affectation === "non-affecte" && !estAffecte);
            option.hidden = !(correspondRecherche && correspondQualification && correspondCentre && correspondDisponibilite && correspondAffectation);
            if (!option.hidden) visibles += 1;
        });

        contactsRoot.querySelectorAll(".email-checkbox-option").forEach((option) => {
            option.hidden = Boolean(requete) && !option.dataset.recherche.includes(requete);
        });

        const filtresSemaineActifs = Boolean(disponibilite || affectation);
        const nombreFiltres = filtreQualificationIds.size + filtreCentreIds.size + (disponibilite ? 1 : 0) + (affectation ? 1 : 0);
        StaffFilterUI.updateCount(filtreCompteur, nombreFiltres);
        if (filtreInfo) {
            filtreInfo.textContent = filtresSemaineActifs && !periodes.length
                ? "Choisis au moins une semaine pour filtrer par dispo ou affectation."
                : `${visibles} salarié${visibles > 1 ? "s" : ""} affiché${visibles > 1 ? "s" : ""}.`;
        }
    }

    function afficherDestinataires() {
        destinatairesRoot.innerHTML = "";
        if (!donnees.animateurs.length) {
            destinatairesRoot.innerHTML = '<p class="empty-note">Aucun salarié enregistré.</p>';
            return;
        }

        donnees.animateurs.forEach((animateur) => {
            const label = document.createElement("label");
            label.className = `email-checkbox-option${animateur.email ? "" : " disabled"}`;
            label.dataset.animateurId = String(animateur.id);
            label.dataset.recherche = [
                animateur.prenom,
                animateur.nom,
                animateur.email,
                ...(animateur.qualifications || []),
                ...(animateur.lieux || []),
            ].join(" ").toLocaleLowerCase("fr");
            label.innerHTML = `
                <input type="checkbox" value="${Number(animateur.id)}" data-type="salarie" ${animateur.email ? "" : "disabled"}>
                <span class="email-option-main">
                    <strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong>
                    <small>${escapeHtml(animateur.email || "Aucune adresse e-mail")}</small>
                </span>
            `;
            label.querySelector("input").addEventListener("change", compteurs);
            destinatairesRoot.appendChild(label);
        });
        remplirFiltresAnnuaire();
        appliquerFiltresDestinataires();
    }

    function afficherContactsExternes() {
        contactsRoot.innerHTML = "";
        const contacts = donnees.contacts_externes || [];
        if (!contacts.length) {
            contactsRoot.innerHTML = '<p class="empty-note">Aucun contact externe enregistré.</p>';
            return;
        }
        contacts.forEach((contact) => {
            const ligne = document.createElement("div");
            ligne.className = "email-contact-row email-checkbox-option";
            ligne.dataset.recherche = [contact.prenom, contact.nom, contact.email, contact.organisation].join(" ").toLocaleLowerCase("fr");
            ligne.innerHTML = `<label><input type="checkbox" value="${Number(contact.id)}" data-type="contact"><span class="email-option-main"><strong>${escapeHtml(`${contact.prenom || ""} ${contact.nom}`.trim())}</strong><small>${escapeHtml(contact.email)}${contact.organisation ? ` · ${escapeHtml(contact.organisation)}` : ""}</small></span></label><button type="button" class="btn btn-ghost btn-small contact-edit">Modifier</button>`;
            ligne.querySelector("input").addEventListener("change", compteurs);
            ligne.querySelector(".contact-edit").addEventListener("click", () => editerContact(contact));
            contactsRoot.appendChild(ligne);
        });
    }

    function fermerContact() {
        contactForm.hidden = true;
        contactId.value = "";
        contactPrenom.value = "";
        contactNom.value = "";
        contactAdresse.value = "";
        contactOrganisation.value = "";
        contactErreur.textContent = "";
        contactSupprimer.hidden = true;
    }
    function editerContact(contact) {
        contactForm.hidden = false; contactId.value = contact.id; contactPrenom.value = contact.prenom || ""; contactNom.value = contact.nom; contactAdresse.value = contact.email; contactOrganisation.value = contact.organisation || ""; contactSupprimer.hidden = false; contactErreur.textContent = ""; contactNom.focus();
    }

    function afficherDocuments() {
        documentsRoot.innerHTML = "";
        if (!donnees.documents.length) {
            documentsRoot.innerHTML = '<p class="empty-note">Aucun document disponible. L’envoi reste possible sans pièce jointe.</p>';
            return;
        }

        donnees.documents.forEach((documentItem) => {
            const label = document.createElement("label");
            label.className = "email-checkbox-option";
            label.innerHTML = `
                <input type="checkbox" value="${Number(documentItem.id)}" data-taille="${Number(documentItem.taille || 0)}">
                <span class="email-option-main">
                    <strong>${escapeHtml(documentItem.titre)}</strong>
                    <small>${escapeHtml(documentItem.libelle_periode)} · ${escapeHtml(formatTaille(documentItem.taille))}</small>
                </span>
            `;
            label.querySelector("input").addEventListener("change", compteurs);
            documentsRoot.appendChild(label);
        });
    }

    function afficherModelesEnvoi() {
        if (!modeleSelect) return;
        const selection = modeleSelect.value;
        modeleSelect.innerHTML = '<option value="">Message personnalisé</option>';
        (donnees.modeles || []).forEach((modele) => {
            const option = document.createElement("option");
            option.value = String(modele.id);
            option.textContent = modele.nom;
            modeleSelect.appendChild(option);
        });
        if ([...modeleSelect.options].some((option) => option.value === selection)) {
            modeleSelect.value = selection;
        }
    }

    function insererVariable(champ, code) {
        if (!champ) return;
        const debut = Number.isInteger(champ.selectionStart) ? champ.selectionStart : champ.value.length;
        const fin = Number.isInteger(champ.selectionEnd) ? champ.selectionEnd : debut;
        champ.value = `${champ.value.slice(0, debut)}${code}${champ.value.slice(fin)}`;
        const position = debut + code.length;
        champ.focus();
        champ.setSelectionRange?.(position, position);
    }

    function afficherVariables(root, obtenirChamp) {
        if (!root) return;
        root.innerHTML = "";
        (donnees.variables || []).forEach((variable) => {
            const bouton = document.createElement("button");
            bouton.type = "button";
            bouton.className = "email-variable-chip";
            bouton.textContent = variable.code;
            bouton.title = variable.libelle;
            bouton.addEventListener("click", () => insererVariable(obtenirChamp(), variable.code));
            root.appendChild(bouton);
        });
    }

    function reinitialiserModele() {
        modeleForm.reset();
        modeleIdInput.value = "";
        modeleActifInput.checked = true;
        modeleTitre.textContent = "Nouveau modèle";
        modeleErreur.textContent = "";
        modeleSupprimer.hidden = true;
        modelesListe.querySelectorAll(".email-template-list-item").forEach((item) => item.classList.remove("active"));
        champVariableModeleActif = modeleMessageInput;
    }

    function editerModele(modeleId) {
        const modele = modelesGestion.find((item) => Number(item.id) === Number(modeleId));
        if (!modele) {
            reinitialiserModele();
            return;
        }
        modeleIdInput.value = String(modele.id);
        modeleNomInput.value = modele.nom;
        modeleObjetInput.value = modele.objet;
        modeleMessageInput.value = modele.message;
        modeleActifInput.checked = Boolean(modele.actif);
        modeleTitre.textContent = "Modifier le modèle";
        modeleErreur.textContent = "";
        modeleSupprimer.hidden = false;
        modelesListe.querySelectorAll(".email-template-list-item").forEach((item) => {
            item.classList.toggle("active", Number(item.dataset.modeleId) === Number(modele.id));
        });
    }

    function afficherGestionModeles() {
        modelesCompteur.textContent = `${modelesGestion.length} modèle${modelesGestion.length > 1 ? "s" : ""}`;
        modelesListe.innerHTML = "";
        if (!modelesGestion.length) {
            modelesListe.innerHTML = '<div class="email-template-empty"><strong>Aucun modèle</strong><p>Crée ton premier modèle avec le formulaire.</p></div>';
            reinitialiserModele();
            return;
        }

        modelesGestion.forEach((modele) => {
            const bouton = document.createElement("button");
            bouton.type = "button";
            bouton.className = "email-template-list-item";
            bouton.dataset.modeleId = String(modele.id);
            bouton.innerHTML = `
                <span><strong>${escapeHtml(modele.nom)}</strong><small>${escapeHtml(modele.objet)}</small></span>
                <span class="email-template-status ${modele.actif ? "active" : "inactive"}">${modele.actif ? "Actif" : "Inactif"}</span>
            `;
            bouton.addEventListener("click", () => editerModele(modele.id));
            modelesListe.appendChild(bouton);
        });
    }

    async function chargerModeles() {
        const payload = await apiFetch("/api/modeles-email/");
        modelesGestion = payload.modeles || [];
        if (payload.variables?.length) donnees.variables = payload.variables;
        donnees.modeles = modelesGestion.filter((modele) => modele.actif);
        afficherModelesEnvoi();
        afficherGestionModeles();
        afficherVariables(variablesRoot, () => champVariableActif || messageInput);
        afficherVariables(modeleVariablesRoot, () => champVariableModeleActif || modeleMessageInput);
    }

    async function chargerEnvois() {
        donnees = await apiFetch("/api/envois-email/");
        afficherConfiguration();
        selecteurSemaines()?.setPeriods(donnees.periodes || []);
        afficherDestinataires();
        afficherContactsExternes();
        afficherDocuments();
        afficherModelesEnvoi();
        afficherVariables(variablesRoot, () => champVariableActif || messageInput);
        compteurs();
        recherche.dispatchEvent(new Event("input"));
    }

    async function charger() {
        // Les destinataires constituent le cœur de l’écran : leur chargement est
        // volontairement indépendant des modèles. Un problème sur les modèles
        // ne doit plus vider ou bloquer la liste des salariés.
        try {
            await chargerEnvois();
        } catch (err) {
            configuration.className = "email-configuration error";
            configuration.textContent = erreurMessage(err, "Impossible de charger la liste des salariés.");
            destinatairesRoot.innerHTML = '<p class="empty-note error-note">Impossible de charger les destinataires.</p>';
            envoyer.disabled = true;
            return;
        }

        try {
            await chargerModeles();
        } catch (err) {
            modelesGestion = [];
            donnees.modeles = [];
            afficherModelesEnvoi();
            afficherGestionModeles();
            if (modeleErreur) {
                modeleErreur.textContent = erreurMessage(err, "Les modèles d’e-mails ne sont pas disponibles pour le moment.");
            }
        }
    }

    function cocher(root, valeur, visiblesSeulement = false) {
        root.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((input) => {
            const option = input.closest(".email-checkbox-option");
            if (!visiblesSeulement || !option.hidden) input.checked = valeur;
        });
        compteurs();
    }

    recherche.addEventListener("input", appliquerFiltresDestinataires);
    [filtreDisponibilite, filtreAffectation].forEach((filtre) => filtre?.addEventListener("change", appliquerFiltresDestinataires));
    semainesPicker?.addEventListener("week-picker:change", appliquerFiltresDestinataires);

    document.getElementById("destinataires-tous").addEventListener("click", () => { cocher(destinatairesRoot, true, true); cocher(contactsRoot, true, true); });
    document.getElementById("destinataires-aucun").addEventListener("click", () => { cocher(destinatairesRoot, false); cocher(contactsRoot, false); });
    document.getElementById("documents-tous").addEventListener("click", () => cocher(documentsRoot, true));
    document.getElementById("documents-aucun").addEventListener("click", () => cocher(documentsRoot, false));

    [objetInput, messageInput].forEach((champ) => champ?.addEventListener("focus", () => { champVariableActif = champ; }));
    [modeleObjetInput, modeleMessageInput].forEach((champ) => champ?.addEventListener("focus", () => { champVariableModeleActif = champ; }));

    modeleSelect?.addEventListener("change", () => {
        const modele = (donnees.modeles || []).find((item) => Number(item.id) === Number(modeleSelect.value));
        if (!modele) return;
        objetInput.value = modele.objet;
        messageInput.value = modele.message;
        messageInput.focus();
    });

    document.getElementById("modele-email-nouveau").addEventListener("click", () => {
        reinitialiserModele();
        modeleNomInput.focus();
    });
    document.getElementById("modele-email-annuler").addEventListener("click", reinitialiserModele);

    modeleForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        modeleErreur.textContent = "";
        const id = modeleIdInput.value;
        const payload = {
            nom: modeleNomInput.value.trim(),
            objet: modeleObjetInput.value.trim(),
            message: modeleMessageInput.value.trim(),
            actif: modeleActifInput.checked,
        };
        if (!payload.nom || !payload.objet || !payload.message) {
            modeleErreur.textContent = "Le nom, l’objet et le message sont obligatoires.";
            return;
        }

        const bouton = document.getElementById("modele-email-enregistrer");
        const texteInitial = bouton.textContent;
        bouton.disabled = true;
        bouton.textContent = "Enregistrement…";
        try {
            const modele = await apiFetch(id ? `/api/modeles-email/${id}/` : "/api/modeles-email/", {
                method: id ? "PATCH" : "POST",
                body: JSON.stringify(payload),
            });
            await chargerModeles();
            editerModele(modele.id);
            afficherToast(id ? "Modèle modifié." : "Modèle créé.");
        } catch (err) {
            modeleErreur.textContent = erreurMessage(err, "Impossible d’enregistrer le modèle.");
        } finally {
            bouton.disabled = false;
            bouton.textContent = texteInitial;
        }
    });

    modeleSupprimer.addEventListener("click", async () => {
        const id = modeleIdInput.value;
        const modele = modelesGestion.find((item) => Number(item.id) === Number(id));
        if (!modele || !confirm(`Supprimer définitivement le modèle « ${modele.nom} » ?`)) return;
        modeleErreur.textContent = "";
        try {
            await apiFetch(`/api/modeles-email/${id}/`, { method: "DELETE" });
            await chargerModeles();
            reinitialiserModele();
            afficherToast("Modèle supprimé.");
        } catch (err) {
            modeleErreur.textContent = erreurMessage(err, "Impossible de supprimer le modèle.");
        }
    });

    document.getElementById("contact-email-nouveau").addEventListener("click", () => { fermerContact(); contactForm.hidden = false; contactNom.focus(); });
    document.getElementById("contact-email-annuler").addEventListener("click", fermerContact);
    contactEnregistrer.addEventListener("click", async () => {
        contactErreur.textContent = "";
        if (!contactNom.value.trim() || !contactAdresse.value.trim()) {
            contactErreur.textContent = "Le nom et l’adresse e-mail sont obligatoires.";
            return;
        }
        if (!contactAdresse.checkValidity()) {
            contactErreur.textContent = "L’adresse e-mail n’est pas valide.";
            contactAdresse.focus();
            return;
        }
        const id = contactId.value;
        try {
            await apiFetch(id ? `/api/contacts-email/${id}/` : "/api/contacts-email/", {method: id ? "PATCH" : "POST", body: JSON.stringify({prenom: contactPrenom.value.trim(), nom: contactNom.value.trim(), email: contactAdresse.value.trim(), organisation: contactOrganisation.value.trim(), actif: true})});
            fermerContact(); await chargerEnvois(); afficherToast(id ? "Contact modifié." : "Contact ajouté.");
        } catch (err) { contactErreur.textContent = erreurMessage(err, "Impossible d’enregistrer le contact."); }
    });
    contactSupprimer.addEventListener("click", async () => {
        if (!contactId.value || !confirm("Supprimer définitivement ce contact externe ?")) return;
        try { await apiFetch(`/api/contacts-email/${contactId.value}/`, {method: "DELETE"}); fermerContact(); await chargerEnvois(); afficherToast("Contact supprimé."); }
        catch (err) { contactErreur.textContent = erreurMessage(err, "Impossible de supprimer le contact."); }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        erreur.textContent = "";
        resultat.hidden = true;

        const animateurIds = cases(destinatairesRoot).map((input) => Number(input.value));
        const contactIds = cases(contactsRoot).map((input) => Number(input.value));
        const documentIds = cases(documentsRoot).map((input) => Number(input.value));
        const objet = objetInput.value.trim();
        const message = messageInput.value.trim();

        if (!animateurIds.length && !contactIds.length) {
            erreur.textContent = "Choisis au moins un destinataire.";
            return;
        }
        if (!objet || !message) {
            erreur.textContent = "L’objet et le message sont obligatoires.";
            return;
        }
        const nombreDestinataires = animateurIds.length + contactIds.length;
        if (!confirm(`Envoyer ce message séparément à ${nombreDestinataires} destinataire${nombreDestinataires > 1 ? "s" : ""} ?`)) return;

        const texteInitial = envoyer.textContent;
        envoyer.disabled = true;
        envoyer.textContent = "Envoi en cours…";
        try {
            const reponse = await apiFetch("/api/envois-email/", {
                method: "POST",
                body: JSON.stringify({
                    animateur_ids: animateurIds,
                    contact_ids: contactIds,
                    document_ids: documentIds,
                    periode_ids: idsSemainesSelectionnees(),
                    objet,
                    message,
                }),
            });
            resultat.hidden = false;
            resultat.className = `email-resultat ${reponse.nombre_echecs ? "warning" : "success"}`;
            resultat.textContent = `${reponse.nombre_envoyes} e-mail${reponse.nombre_envoyes > 1 ? "s" : ""} envoyé${reponse.nombre_envoyes > 1 ? "s" : ""}${reponse.mode_test ? " en mode test" : ""}${reponse.nombre_echecs ? `, ${reponse.nombre_echecs} en échec` : ""}.`;
            if (!reponse.nombre_echecs) {
                form.reset();
                selecteurSemaines()?.clear();
                recherche.value = "";
            }
            afficherToast(reponse.nombre_echecs ? "Envoi terminé avec des échecs." : "E-mails envoyés.", Boolean(reponse.nombre_echecs));
            await chargerEnvois();
        } catch (err) {
            erreur.textContent = erreurMessage(err, "L’envoi a échoué.");
        } finally {
            envoyer.textContent = texteInitial;
            envoyer.disabled = !(donnees.configuration || {}).operationnel;
        }
    });

    reinitialiserModele();
    charger();

    filtreReset?.addEventListener("click", () => {
        filtreQualificationIds.clear();
        filtreCentreIds.clear();
        [filtreDisponibilite, filtreAffectation].forEach((select) => { if (select) select.value = ""; });
        filtreQualifications?.querySelectorAll('input[type="checkbox"]').forEach((input) => { input.checked = false; });
        filtreCentres?.querySelectorAll('input[type="checkbox"]').forEach((input) => { input.checked = false; });
        appliquerFiltresDestinataires();
    });
});
