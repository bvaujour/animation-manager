/* Invitations portail : période locale, sans modifier le contexte global. */
window.InvitationsPortail = (() => {
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const api = async (url, options = {}) => {
        const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
        const response = await fetch(url, {headers: {"X-CSRFToken": csrf, "Content-Type": "application/json", ...(options.headers || {})}, ...options});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Opération impossible");
        return data;
    };
    const copierTexte = async (texte) => {
        if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(texte);
        const zone = document.createElement("textarea");
        zone.value = texte;
        zone.style.cssText = "position:fixed;opacity:0";
        document.body.appendChild(zone);
        zone.select();
        document.execCommand("copy");
        zone.remove();
    };
    const texteInvitation = (animateur) => `Bonjour ${animateur.prenom},\n\nTon accès au portail Animation Manager est prêt.\nIdentifiant : ${animateur.username}\nActive-le sous 3 jours : ${animateur.activation_url}`;

    function mount(root) {
        if (!root || root.dataset.mounted) return;
        root.dataset.mounted = "true";
        const base = root.dataset.apiUrl;
        const animateursApi = root.dataset.animateursApiUrl;
        root.innerHTML = `<header><h2>Invitations portail</h2><p>Choisissez une période : ce sélecteur est propre aux invitations.</p></header><label class="invitation-period-label">Période concernée <select data-period><option value="">Choisir une période…</option></select></label><div data-content class="invitation-empty">Choisissez une période pour afficher les animateurs affectés.</div>`;
        const select = root.querySelector("[data-period]");
        const content = root.querySelector("[data-content]");
        let data = null;
        let selection = new Set();

        const enregistrerCoordonnees = (animateur) => {
            const dialog = document.createElement("dialog");
            dialog.className = "invitation-contact-dialog";
            dialog.innerHTML = `<form method="dialog"><header><h2>Coordonnées de ${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</h2><p>Ces coordonnées sont enregistrées sur la fiche animateur.</p></header><label>E-mail <input name="email" type="email" autocomplete="email" value="${escapeHtml(animateur.email)}"></label><label>Téléphone <input name="telephone" type="tel" autocomplete="tel" value="${escapeHtml(animateur.telephone)}"></label><p data-error class="invitation-result" role="alert"></p><footer><button type="button" class="btn btn-ghost" data-cancel>Annuler</button><button type="submit" class="btn btn-primary">Enregistrer</button></footer></form>`;
            document.body.appendChild(dialog);
            const form = dialog.querySelector("form");
            const fermer = () => { dialog.close(); dialog.remove(); };
            dialog.querySelector("[data-cancel]").addEventListener("click", fermer);
            dialog.addEventListener("cancel", () => dialog.remove());
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                if (!form.reportValidity()) return;
                const erreur = form.querySelector("[data-error]");
                try {
                    const modifie = await api(`${animateursApi}${animateur.id}/`, {
                        method: "PATCH",
                        body: JSON.stringify({email: form.elements.email.value.trim(), telephone: form.elements.telephone.value.trim()}),
                    });
                    animateur.email = modifie.email || "";
                    animateur.telephone = modifie.telephone || "";
                    fermer();
                    render();
                } catch (error) { erreur.textContent = error.message; }
            });
            dialog.showModal();
        };

        const render = () => {
            if (!data?.periode_id) {
                content.className = "invitation-empty";
                content.textContent = "Choisissez une période pour afficher les animateurs affectés.";
                return;
            }
            const s = data.synthese;
            const rows = data.animateurs.map(a => {
                const active = a.etat === "actif";
                const pending = a.etat === "attente";
                const contactAction = `<button type="button" class="btn btn-ghost btn-small" data-contact="${a.id}">${a.email || a.telephone ? "Modifier les coordonnées" : "Compléter les coordonnées"}</button>`;
                const invitationActions = pending ? `${a.telephone ? `<a class="btn btn-secondary btn-small" href="sms:${encodeURIComponent(a.telephone)}?body=${encodeURIComponent(texteInvitation(a))}">SMS</a>` : ""}<button type="button" class="btn btn-ghost btn-small" data-copy="${a.id}">Copier l’invitation</button>` : "";
                return `<article class="invitation-row"><label class="invitation-select"><input type="checkbox" value="${a.id}" ${selection.has(a.id) ? "checked" : ""} ${active ? "disabled" : ""}><span class="sr-only">Sélectionner ${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}</span></label><span><strong>${escapeHtml(a.prenom)} ${escapeHtml(a.nom)}</strong><small>${a.email ? escapeHtml(a.email) : "Sans e-mail"} · ${a.telephone ? escapeHtml(a.telephone) : "Sans téléphone"}</small></span><b class="invitation-state invitation-state--${a.etat}">${active ? "Accès actif" : pending ? "Invitation en attente" : "Sans accès"}</b><span class="invitation-actions">${contactAction}${invitationActions}</span></article>`;
            }).join("") || "<p>Aucun animateur affecté.</p>";
            content.className = "";
            content.innerHTML = `<div class="invitation-summary"><strong>${s.affectes} animateurs affectés</strong><span>${s.actifs} accès actifs</span><span>${s.a_inviter} à inviter</span></div><div class="invitation-list">${rows}</div><button class="btn btn-primary" data-send>Créer les accès et envoyer les invitations</button><button class="btn btn-ghost" data-regenerate>Renvoyer / régénérer les invitations cochées</button><p data-result class="invitation-result"></p>`;
            content.querySelector("[data-send]").onclick = () => submit(false);
            content.querySelector("[data-regenerate]").onclick = () => submit(true);
        };

        const submit = async (regenerer) => {
            const ids = [...selection];
            if (!ids.length) return;
            const result = content.querySelector("[data-result]");
            result.textContent = "Traitement…";
            try {
                const response = await api(base, {method: "POST", body: JSON.stringify({periode_id: data.periode_id, animateur_ids: ids, regenerer})});
                const manuels = response.resultats.filter(x => !x.email_envoye && x.activation_url);
                result.textContent = `${response.resultats.filter(x => x.email_envoye).length} e-mail(s) envoyé(s). ${manuels.length} invitation(s) disponible(s) par SMS ou copie.`;
                await load(data.periode_id, true);
            } catch (error) { result.textContent = error.message; }
        };

        const load = async (periodId = "", conserverSelection = false) => {
            data = await api(`${base}${periodId ? `?periode_id=${encodeURIComponent(periodId)}` : ""}`, {headers: {"Content-Type": ""}});
            if (!select.options.length || select.options.length === 1) data.periodes.forEach(p => select.add(new Option(p.libelle, p.id)));
            select.value = data.periode_id || "";
            const disponibles = new Set(data.animateurs.map(a => a.id));
            selection = conserverSelection ? new Set([...selection].filter(id => disponibles.has(id))) : new Set(data.animateurs.filter(a => a.etat === "sans_acces").map(a => a.id));
            render();
        };

        select.addEventListener("change", () => load(select.value));
        content.addEventListener("change", (event) => {
            if (!event.target.matches("input[type=checkbox]")) return;
            const id = Number(event.target.value);
            if (event.target.checked) selection.add(id); else selection.delete(id);
        });
        content.addEventListener("click", async (event) => {
            const contact = event.target.closest("[data-contact]");
            if (contact) {
                enregistrerCoordonnees(data.animateurs.find(a => a.id === Number(contact.dataset.contact)));
                return;
            }
            const copy = event.target.closest("[data-copy]");
            if (copy) {
                const result = content.querySelector("[data-result]");
                try {
                    await copierTexte(texteInvitation(data.animateurs.find(a => a.id === Number(copy.dataset.copy))));
                    result.textContent = "Invitation copiée.";
                } catch { result.textContent = "Impossible de copier l’invitation."; }
            }
        });
        load().catch(error => { content.textContent = error.message; });
    }
    return {mount};
})();
