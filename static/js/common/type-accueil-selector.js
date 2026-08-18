document.addEventListener("DOMContentLoaded", () => {
    const typeSelect = document.getElementById("app-type-accueil");
    const periodeSelect = document.getElementById("app-periode-accueil");
    if (!typeSelect || !periodeSelect) return;

    const naviguer = ({ typeChange = false } = {}) => {
        const url = new URL(window.location.href);
        if (typeSelect.value) url.searchParams.set("type_accueil", typeSelect.value);
        else url.searchParams.delete("type_accueil");
        if (typeChange) {
            url.searchParams.delete("periode_accueil");
        } else if (periodeSelect.value) {
            url.searchParams.set("periode_accueil", periodeSelect.value);
        } else {
            url.searchParams.delete("periode_accueil");
        }
        window.location.assign(url.toString());
    };

    typeSelect.addEventListener("change", () => naviguer({ typeChange: true }));
    periodeSelect.addEventListener("change", () => naviguer());
});
