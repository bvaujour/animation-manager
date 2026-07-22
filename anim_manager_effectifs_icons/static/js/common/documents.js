// Utilitaires partagés par les pages Accueil et Documents.
window.DocumentUtils = Object.freeze({
    extension(url) {
        const propre = String(url || "").split("?")[0];
        const nom = propre.split("/").pop() || "";
        const morceaux = nom.split(".");
        return morceaux.length > 1 ? morceaux.pop().toLowerCase() : "";
    },

    typeCourt(url) {
        const extension = this.extension(url);
        if (extension === "pdf") return "PDF";
        if (["jpg", "jpeg", "png", "gif", "webp"].includes(extension)) return "IMG";
        if (["doc", "docx"].includes(extension)) return "DOC";
        if (["xls", "xlsx", "csv"].includes(extension)) return "XLS";
        return extension ? extension.toUpperCase().slice(0, 4) : "FIC";
    },
});
