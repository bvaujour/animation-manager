// Fonctions de couleurs communes au planning et au récapitulatif.
window.ColorUtils = Object.freeze({
    texteLisible(couleur) {
        if (!/^#[0-9A-Fa-f]{6}$/.test(couleur || "")) return "#ffffff";
        const r = Number.parseInt(couleur.slice(1, 3), 16);
        const g = Number.parseInt(couleur.slice(3, 5), 16);
        const b = Number.parseInt(couleur.slice(5, 7), 16);
        const luminance = 0.299 * r + 0.587 * g + 0.114 * b;
        return luminance > 165 ? "#172033" : "#ffffff";
    },

    rgba(couleur, opacite = 0.12) {
        if (!/^#[0-9A-Fa-f]{6}$/.test(couleur || "")) {
            return `rgba(224, 60, 0, ${opacite})`;
        }
        const r = Number.parseInt(couleur.slice(1, 3), 16);
        const g = Number.parseInt(couleur.slice(3, 5), 16);
        const b = Number.parseInt(couleur.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${opacite})`;
    },
});
