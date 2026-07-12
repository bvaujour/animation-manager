// Générateurs HTML communs pour les formulaires Animateur.
window.FormOptionsUtils = Object.freeze({
    qualifications(qualifications, cochees = []) {
        if (!qualifications.length) {
            return '<p class="empty-note">Aucune qualification disponible.</p>';
        }

        const cocheesSet = new Set((cochees || []).map(Number));
        return qualifications.map((qualification) => `
            <label class="checkbox-chip">
                <input type="checkbox" value="${escapeHtml(qualification.id)}" ${cocheesSet.has(Number(qualification.id)) ? "checked" : ""}>
                ${escapeHtml(qualification.nom)}
            </label>
        `).join("");
    },

    centres(centres, centresAutorises = [], messageVide = "Ajoute d'abord des centres pour choisir où affecter l'animateur.") {
        if (!centres.length) {
            return `<p class="empty-note">${escapeHtml(messageVide)}</p>`;
        }

        const centresSet = new Set((centresAutorises || []).map((centre) => Number(centre.id ?? centre)));
        return centres.map((centre) => `
            <label class="checkbox-chip centre-chip-option">
                <input type="checkbox" value="${escapeHtml(centre.id)}" ${centresSet.has(Number(centre.id)) ? "checked" : ""}>
                <span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>
                ${escapeHtml(centre.code || centre.nom)}
            </label>
        `).join("");
    },

    idsCoches(root) {
        return idsCheckboxesCochees(root);
    },
});
