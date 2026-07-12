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

    centresHierarchises(centres, centrePrefere = null, centresSecondaires = [], groupe = "centre-prefere") {
        if (!centres.length) {
            return '<p class="empty-note">Ajoute d\'abord des centres.</p>';
        }

        const prefereId = Number(centrePrefere && (centrePrefere.id ?? centrePrefere)) || null;
        const secondairesSet = new Set((centresSecondaires || []).map((centre) => Number(centre.id ?? centre)));

        return `
            <div class="centre-hierarchy-head">
                <span>Centre</span><span>Préféré</span><span>Secondaire</span>
            </div>
            ${centres.map((centre) => {
                const id = Number(centre.id);
                const estPrefere = prefereId === id;
                const estSecondaire = secondairesSet.has(id) && !estPrefere;
                return `
                    <div class="centre-hierarchy-row" data-centre-id="${escapeHtml(id)}">
                        <span class="centre-hierarchy-name">
                            <span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>
                            ${escapeHtml(centre.code || centre.nom)}
                        </span>
                        <label class="centre-hierarchy-choice" title="Centre préféré">
                            <input type="radio" name="${escapeHtml(groupe)}" data-role="prefere" value="${escapeHtml(id)}" ${estPrefere ? "checked" : ""}>
                        </label>
                        <label class="centre-hierarchy-choice" title="Centre secondaire">
                            <input type="checkbox" data-role="secondaire" value="${escapeHtml(id)}" ${estSecondaire ? "checked" : ""} ${estPrefere ? "disabled" : ""}>
                        </label>
                    </div>
                `;
            }).join("")}
        `;
    },

    activerCentresHierarchises(root) {
        if (!root) return;
        const synchroniser = () => {
            const prefere = root.querySelector('input[data-role="prefere"]:checked');
            const prefereId = prefere ? Number(prefere.value) : null;
            root.querySelectorAll('input[data-role="secondaire"]').forEach((checkbox) => {
                const memeCentre = Number(checkbox.value) === prefereId;
                if (memeCentre) checkbox.checked = false;
                checkbox.disabled = memeCentre;
            });
        };
        root.querySelectorAll('input[data-role="prefere"]').forEach((radio) => {
            radio.addEventListener("change", synchroniser);
        });
        synchroniser();
    },

    lireCentresHierarchises(root) {
        const prefere = root ? root.querySelector('input[data-role="prefere"]:checked') : null;
        const centre_prefere = prefere ? Number(prefere.value) : null;
        const centres_secondaires = root
            ? Array.from(root.querySelectorAll('input[data-role="secondaire"]:checked')).map((el) => Number(el.value))
            : [];
        return { centre_prefere, centres_secondaires };
    },

    idsCoches(root) {
        return idsCheckboxesCochees(root);
    },
});
