document.addEventListener("DOMContentLoaded", async () => {
    const grid = document.getElementById("documents-partages");
    try {
        const documents = await apiFetch("/api/documents/");
        if (!documents.length) {
            grid.innerHTML = '<p class="empty-note">Aucun document disponible pour le moment.</p>';
            return;
        }
        grid.innerHTML = documents.map((doc) => {
            const extension = (doc.url || "").split(".").pop().split(/[?#]/)[0].slice(0, 4).toUpperCase() || "FIC";
            return `<article class="document-card">
                <div class="document-file-type" aria-hidden="true">${escapeHtml(extension)}</div>
                <h2 class="document-title truncate" title="${escapeHtml(doc.titre)}">${escapeHtml(doc.titre)}</h2>
                <p class="document-period-label">${escapeHtml(doc.libelle_periode || (doc.permanent ? "Permanent" : ""))}</p>
                <div class="document-actions"><a href="${escapeHtml(doc.url)}" target="_blank" rel="noopener" class="btn btn-primary">Télécharger</a></div>
            </article>`;
        }).join("");
    } catch {
        grid.innerHTML = '<p class="empty-note">Impossible de charger les documents.</p>';
    }
});
