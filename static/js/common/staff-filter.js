(function () {
    "use strict";

    function selectedNumbers(container) {
        if (!container) return [];
        return Array.from(container.querySelectorAll('input[type="checkbox"]:checked'))
            .map((input) => Number(input.value))
            .filter(Number.isFinite);
    }

    function renderOptions(container, items, { selected = [], emptyText = "Aucune option", name = "staff_filter", onChange = null } = {}) {
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
            label.append(input, text);
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

    function positionPanel(details) {
        if (!details?.open) return;
        const panel = details.querySelector(".animateurs-filter-panel");
        const button = details.querySelector("summary");
        if (!panel || !button) return;
        const rect = button.getBoundingClientRect();
        const margin = 10;
        const width = Math.min(380, window.innerWidth - margin * 2);
        const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin));
        const availableBelow = window.innerHeight - rect.bottom - margin;
        const top = availableBelow >= 250 ? rect.bottom + 8 : Math.max(margin, rect.top - Math.min(520, window.innerHeight - margin * 2) - 8);
        panel.style.setProperty("--filter-panel-top", `${Math.round(top)}px`);
        panel.style.setProperty("--filter-panel-left", `${Math.round(left)}px`);
        panel.style.setProperty("--filter-panel-width", `${Math.round(width)}px`);
        panel.classList.add("is-viewport-positioned");
    }

    function init(root) {
        const details = root.matches("details") ? root : root.querySelector("details.compact-filter");
        if (!details || details.dataset.staffFilterReady === "1") return;
        details.dataset.staffFilterReady = "1";
        const reposition = () => positionPanel(details);
        details.addEventListener("toggle", () => {
            if (details.open) requestAnimationFrame(reposition);
        });
        window.addEventListener("resize", reposition);
        window.addEventListener("scroll", reposition, true);
    }

    document.addEventListener("click", (event) => {
        document.querySelectorAll("details.compact-filter[open]").forEach((details) => {
            if (!details.contains(event.target)) details.removeAttribute("open");
        });
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") document.querySelectorAll("details.compact-filter[open]").forEach((details) => details.removeAttribute("open"));
    });
    document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("[data-staff-filter]").forEach(init));

    window.StaffFilterUI = { selectedNumbers, renderOptions, activeCount, updateCount, positionPanel, init };
})();
