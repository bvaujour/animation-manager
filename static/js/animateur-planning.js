(function () {
    "use strict";

    const page = document.querySelector("[data-animator-planning-page]");
    if (!page) return;

    const contacts = new Map();
    const sortiesAutorisees = new Set();
    let contactDialog = null;

    function normaliser(value) {
        return String(value || "").trim();
    }

    function initiales(prenom, nom) {
        return `${normaliser(prenom).charAt(0)}${normaliser(nom).charAt(0)}`.toUpperCase() || "?";
    }

    function ouvrirDialogue(dialog) {
        if (!dialog) return;
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
    }

    function fermerDialogue(dialog) {
        if (!dialog) return;
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
    }

    function chargerDonneesPortail() {
        document.querySelectorAll("[data-planning-sortie-id]").forEach((node) => {
            const id = normaliser(node.dataset.planningSortieId);
            if (id) sortiesAutorisees.add(id);
        });
        document.querySelectorAll("[data-planning-contact-id]").forEach((node) => {
            const id = normaliser(node.dataset.planningContactId);
            if (!id || contacts.has(id)) return;
            contacts.set(id, {
                prenom: normaliser(node.dataset.contactPrenom),
                nom: normaliser(node.dataset.contactNom),
                telephone: normaliser(node.dataset.contactTelephone),
                email: normaliser(node.dataset.contactEmail),
            });
        });
    }

    function ouvrirContact(contact) {
        if (!contact || !contactDialog) return;
        const nomComplet = [contact.prenom, contact.nom].filter(Boolean).join(" ") || "Collègue";
        const name = contactDialog.querySelector("[data-contact-name]");
        const initials = contactDialog.querySelector("[data-contact-initials]");
        const phoneLink = contactDialog.querySelector("[data-contact-phone-link]");
        const phone = contactDialog.querySelector("[data-contact-phone]");
        const emailLink = contactDialog.querySelector("[data-contact-email-link]");
        const email = contactDialog.querySelector("[data-contact-email]");
        const empty = contactDialog.querySelector("[data-contact-empty]");

        if (name) name.textContent = nomComplet;
        if (initials) initials.textContent = initiales(contact.prenom, contact.nom);

        if (phoneLink && phone) {
            phoneLink.hidden = !contact.telephone;
            phone.textContent = contact.telephone;
            phoneLink.href = contact.telephone ? `tel:${contact.telephone.replace(/\s+/g, "")}` : "#";
        }
        if (emailLink && email) {
            emailLink.hidden = !contact.email;
            email.textContent = contact.email;
            emailLink.href = contact.email ? `mailto:${contact.email}` : "#";
        }
        if (empty) empty.hidden = Boolean(contact.telephone || contact.email);
        ouvrirDialogue(contactDialog);
    }

    function handleCalendarEventClick(info) {
        if (info?.event?.extendedProps?.type_affichage === "effectif_enfants") return false;
        const id = normaliser(info?.event?.extendedProps?.animateur_id);
        const contact = contacts.get(id);
        if (!contact) return false;
        info.jsEvent?.preventDefault?.();
        ouvrirContact(contact);
        return true;
    }

    function decorateCalendarEvent(info) {
        if (info?.event?.extendedProps?.type_affichage === "effectif_enfants") return;
        const id = normaliser(info?.event?.extendedProps?.animateur_id);
        const contact = contacts.get(id);
        if (!contact || !info.el) return;
        info.el.classList.add("animator-planning-contact-event");
        info.el.setAttribute("title", `Voir le contact de ${contact.prenom} ${contact.nom}`.trim());
        info.el.setAttribute("aria-label", `${info.event.title}. Ouvrir les coordonnées.`);
    }

    function markerHrefBuilder(items) {
        const base = normaliser(page.dataset.sortiesUrl);
        if (!base || !Array.isArray(items)) return "";
        const pertinentes = items.filter((item) => sortiesAutorisees.has(normaliser(item?.id)));
        if (!pertinentes.length) return "";
        if (pertinentes.length === 1 && pertinentes[0]?.id) {
            return `${base}#sortie-${encodeURIComponent(pertinentes[0].id)}`;
        }
        return base;
    }

    document.addEventListener("DOMContentLoaded", () => {
        chargerDonneesPortail();
        contactDialog = document.getElementById("planning-contact-dialog");

        document.querySelectorAll("[data-open-dialog]").forEach((button) => {
            button.addEventListener("click", () => ouvrirDialogue(document.getElementById(button.dataset.openDialog)));
        });

        document.querySelectorAll(".animator-portal-dialog").forEach((dialog) => {
            dialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
                button.addEventListener("click", () => fermerDialogue(dialog));
            });
            dialog.addEventListener("click", (event) => {
                if (event.target === dialog) fermerDialogue(dialog);
            });
            dialog.addEventListener("cancel", (event) => {
                event.preventDefault();
                fermerDialogue(dialog);
            });
        });
    });

    window.AnimatorPlanningPortal = {
        handleCalendarEventClick,
        decorateCalendarEvent,
        markerOptions: { markerHrefBuilder },
    };
})();
