(function () {
    "use strict";

    function selectedNumbers(container) {
        if (!container) return [];
        return Array.from(container.querySelectorAll('input[type="checkbox"]:checked'))
            .map((input) => Number(input.value))
            .filter(Number.isFinite);
    }

    function renderOptions(container, items, { selected = [], emptyText = "Aucune option", name = "staff_filter", onChange = null, showColor = false } = {}) {
        if (!container) return;
        const selectedSet = selected instanceof Set ? selected : new Set((selected || []).map(Number));
        container.innerHTML = "";
        const sorted = [...(items || [])].sort((a, b) => String(a.nom || a.label || "").localeCompare(String(b.nom || b.label || ""), "fr", { sensitivity: "base" }));
        if (!sorted.length) {
            const empty = document.createElement("span");
            empty.className = "empty-note";
            empty.textContent = emptyText;
            container.appendChild(empty);
            return;
        }
        sorted.forEach((item) => {
            const label = document.createElement("label");
            label.className = "animateurs-filter-option";
            const input = document.createElement("input");
            input.type = "checkbox";
            input.name = name;
            input.value = String(item.id);
            input.checked = selectedSet.has(Number(item.id));
            const text = document.createElement("span");
            text.textContent = item.nom || item.label || String(item.id);
            if (showColor && (item.couleur_statut || item.couleur)) {
                const couleur = item.couleur_statut || item.couleur;
                label.classList.add("has-status-color");
                label.style.setProperty("--filter-status-color", couleur);
                const swatch = document.createElement("span");
                swatch.className = "animateurs-filter-status-swatch";
                swatch.setAttribute("aria-hidden", "true");
                label.append(input, swatch, text);
            } else {
                label.append(input, text);
            }
            if (onChange) input.addEventListener("change", () => onChange(input, item));
            container.appendChild(label);
        });
    }

    function activeCount({ qualifications, centres, availability, assignment }) {
        return selectedNumbers(qualifications).length
            + selectedNumbers(centres).length
            + (availability?.value ? 1 : 0)
            + (assignment?.value ? 1 : 0);
    }

    function updateCount(element, count) {
        if (!element) return;
        element.textContent = String(count);
        element.hidden = count === 0;
    }

    function fermerDialog(dialog, boutonOuverture = null) {
        if (!dialog?.open) return;
        dialog.close();
        boutonOuverture?.focus({ preventScroll: true });
    }

    function ouvrirDialog(dialog) {
        if (!dialog || dialog.open) return;

        // Une seule fenêtre de filtres peut être ouverte à la fois.
        document.querySelectorAll("dialog[data-staff-filter-dialog][open]").forEach((autreDialog) => {
            if (autreDialog !== dialog) autreDialog.close();
        });

        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");

        requestAnimationFrame(() => {
            const premierChamp = dialog.querySelector('input:not([disabled]), select:not([disabled]), button:not([disabled])');
            premierChamp?.focus({ preventScroll: true });
        });
    }

    function init(root) {
        if (!root || root.dataset.staffFilterReady === "1") return;
        const dialog = root.querySelector("dialog[data-staff-filter-dialog]");
        const boutonOuverture = root.querySelector("[data-staff-filter-open]");
        if (!dialog || !boutonOuverture) return;

        root.dataset.staffFilterReady = "1";
        boutonOuverture.addEventListener("click", () => ouvrirDialog(dialog));
        dialog.querySelectorAll("[data-staff-filter-close]").forEach((bouton) => {
            bouton.addEventListener("click", () => fermerDialog(dialog, boutonOuverture));
        });

        // Un clic sur le fond assombri ferme la fenêtre, sans fermer lors d'un clic dans son contenu.
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) fermerDialog(dialog, boutonOuverture);
        });
        dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            fermerDialog(dialog, boutonOuverture);
        });
    }

    document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-staff-filter]").forEach(init));

    window.StaffFilterUI = { selectedNumbers, renderOptions, activeCount, updateCount, ouvrirDialog, fermerDialog, init };
})();
