// Générateurs HTML communs pour les formulaires Animateur.
window.FormOptionsUtils = Object.freeze({
    qualifications(qualifications, cochees = [], groupe = "qualifications") {
        if (!qualifications.length) {
            return '<p class="empty-note">Aucun diplôme disponible.</p>';
        }

        const cocheesSet = new Set((cochees || []).map(Number));
        return qualifications.map((qualification) => {
            const id = `${groupe}-${qualification.id}`;
            return `
            <label class="checkbox-chip" for="${escapeHtml(id)}">
                <input type="checkbox" id="${escapeHtml(id)}" name="${escapeHtml(groupe)}[]" value="${escapeHtml(qualification.id)}" ${cocheesSet.has(Number(qualification.id)) ? "checked" : ""}>
                ${escapeHtml(qualification.nom)}
            </label>
        `;
        }).join("");
    },

    centresHierarchises(centres, centresPreferes = [], centresInterdits = [], groupe = "centre-options") {
        if (!centres.length) return '<p class="empty-note">Ajoute d\'abord des centres.</p>';
        const preferesSet = new Set((Array.isArray(centresPreferes) ? centresPreferes : [centresPreferes]).filter(Boolean).map(c => Number(c.id ?? c)));
        const interditsSet = new Set((centresInterdits || []).map(c => Number(c.id ?? c)));
        return `<div class="centre-hierarchy-head"><span>Lieu</span><span>Préféré</span><span>Interdit</span></div>${centres.map(centre => {
            const id=Number(centre.id);
            return `<div class="centre-hierarchy-row" data-centre-id="${escapeHtml(id)}"><span class="centre-hierarchy-name"><span class="swatch" style="background:${escapeHtml(centre.couleur)}"></span>${escapeHtml(centre.code || centre.nom)}</span><label class="centre-hierarchy-choice"><input type="checkbox" data-role="prefere" value="${escapeHtml(id)}" ${preferesSet.has(id)?"checked":""}></label><label class="centre-hierarchy-choice"><input type="checkbox" data-role="interdit" value="${escapeHtml(id)}" ${interditsSet.has(id)?"checked":""}></label></div>`;
        }).join("")}`;
    },

    activerCentresHierarchises(root) {
        if (!root) return;
        root.addEventListener("change", (event) => {
            const input = event.target.closest('input[data-role="prefere"], input[data-role="interdit"]');
            if (!input || !input.checked) return;
            const row=input.closest('[data-centre-id]');
            const autre=row.querySelector(input.dataset.role === "prefere" ? 'input[data-role="interdit"]' : 'input[data-role="prefere"]');
            if (autre) autre.checked=false;
        });
    },

    lireCentresHierarchises(root) {
        const centres_preferes = root ? Array.from(root.querySelectorAll('input[data-role="prefere"]:checked')).map(el=>Number(el.value)) : [];
        const centres_interdits = root ? Array.from(root.querySelectorAll('input[data-role="interdit"]:checked')).map(el=>Number(el.value)) : [];
        return { centres_preferes, centres_interdits };
    },
});
