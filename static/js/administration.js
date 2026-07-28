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

    const exportForm = document.querySelector("[data-export-planning-form]");
    const exportWeeks = Array.from(exportForm?.querySelectorAll("[data-export-week]") || []);
    const exportCheckboxes = exportWeeks.map((week) => week.querySelector('input[name="periode_ids"]'));
    const exportSelectionCount = exportForm?.querySelector("[data-export-selection-count]");
    const exportActionsCount = exportForm?.querySelector("[data-export-actions-count]");
    const exportButtons = Array.from(exportForm?.querySelectorAll('.export-actions button[type="submit"]') || []);

    const periodeDemandee = new URLSearchParams(window.location.search).get("periode_id");
    if (periodeDemandee && /^\d+$/.test(periodeDemandee)) {
        const checkbox = exportCheckboxes.find((item) => item.value === periodeDemandee);
        if (checkbox) {
            checkbox.checked = true;
            let parent = checkbox.parentElement;
            while (parent && parent !== exportForm) {
                if (parent.tagName === "DETAILS") parent.open = true;
                parent = parent.parentElement;
            }
        }
    }

    function updateExportSelection() {
        const count = exportCheckboxes.filter((checkbox) => checkbox.checked).length;
        const label = count
            ? `${count} semaine${count > 1 ? "s" : ""} sélectionnée${count > 1 ? "s" : ""}`
            : "Aucune semaine sélectionnée";
        if (exportSelectionCount) exportSelectionCount.textContent = label;
        if (exportActionsCount) exportActionsCount.textContent = count ? label : "Aucune semaine";
        exportButtons.forEach((button) => { button.disabled = count === 0; });
    }

    exportCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", updateExportSelection));
    exportForm?.querySelectorAll("[data-export-select-group]").forEach((button) => {
        button.addEventListener("click", () => {
            button.closest(".export-vacation-group")?.querySelectorAll('input[name="periode_ids"]')
                .forEach((checkbox) => { checkbox.checked = true; });
            updateExportSelection();
        });
    });
    exportForm?.querySelector("[data-export-clear]")?.addEventListener("click", () => {
        exportCheckboxes.forEach((checkbox) => { checkbox.checked = false; });
        updateExportSelection();
    });
    updateExportSelection();

    let exportConfirme = false;
    exportForm?.addEventListener("submit", async (event) => {
        if (exportConfirme) {
            exportConfirme = false;
            return;
        }
        event.preventDefault();
        const submitter = event.submitter;
        const params = new URLSearchParams(new FormData(exportForm));
        try {
            const response = await fetch(`${exportForm.dataset.verificationUrl}?${params}`, {
                credentials: "same-origin",
                cache: "no-store",
            });
            const data = await response.json();
            if (!response.ok) throw data;
            if (data.nombre) {
                const accord = window.confirm(
                    `${data.nombre} journée${data.nombre > 1 ? "s" : ""} de groupe `
                    + `n’${data.nombre > 1 ? "ont" : "a"} pas d’horaires d’arrivée et de départ. `
                    + "Exporter quand même ?"
                );
                if (!accord) return;
            }
            exportConfirme = true;
            exportForm.requestSubmit(submitter);
        } catch (erreur) {
            afficherToast(erreur?.error || "La vérification des horaires a échoué.", true);
        }
    });
});
