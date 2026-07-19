document.addEventListener("DOMContentLoaded", () => {
    const page = document.querySelector(".administration-page");
    const tabs = Array.from(document.querySelectorAll("#administration-tabs [data-admin-tab]"));
    const panels = Array.from(document.querySelectorAll(".admin-tab-panel[data-admin-panel]"));
    const allowedTabs = new Set(tabs.map((button) => button.dataset.adminTab));

    function openTab(tabName, updateUrl = true) {
        const selected = allowedTabs.has(tabName) ? tabName : "export";
        tabs.forEach((button) => {
            const active = button.dataset.adminTab === selected;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        panels.forEach((panel) => {
            panel.hidden = panel.dataset.adminPanel !== selected;
        });

        if (updateUrl) {
            const url = new URL(window.location.href);
            url.searchParams.set("onglet", selected);
            url.hash = "";
            window.history.replaceState({}, "", url);
        }
    }

    tabs.forEach((button) => {
        button.addEventListener("click", () => openTab(button.dataset.adminTab));
    });

    const queryTab = new URLSearchParams(window.location.search).get("onglet");
    const initialTab = queryTab || page?.dataset.activeTab || "export";
    openTab(initialTab, false);

    const debut = document.getElementById("export-date-debut");
    const fin = document.getElementById("export-date-fin");
    if (debut && fin) {
        function synchroniserFin() {
            const dateDebut = debut.value;
            Array.from(fin.options).forEach((option) => {
                option.disabled = option.value < dateDebut;
            });
            if (fin.value < dateDebut) fin.value = dateDebut;
        }
        debut.addEventListener("change", synchroniserFin);
        synchroniserFin();
    }
});
