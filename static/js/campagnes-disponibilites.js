document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-recipient-selector]");
    if (!root) return;
    const recipients = () => [...root.querySelectorAll(".availability-recipient")];
    const updateRecipientCount = () => {
        const count = recipients().filter((item) => item.querySelector("input").checked).length;
        root.querySelectorAll("[data-recipient-count]").forEach((target) => { target.textContent = count; });
    };
    root.querySelector("[data-select-all]")?.addEventListener("click", () => {
        recipients().forEach((item) => { item.querySelector("input").checked = true; });
        updateRecipientCount();
    });
    root.querySelector("[data-clear-all]")?.addEventListener("click", () => {
        recipients().forEach((item) => { item.querySelector("input").checked = false; });
        updateRecipientCount();
    });
    recipients().forEach((item) => item.querySelector("input").addEventListener("change", updateRecipientCount));
    root.querySelector("[data-recipient-search]")?.addEventListener("input", (event) => {
        const query = event.target.value.trim().toLocaleLowerCase("fr");
        recipients().forEach((item) => { item.hidden = Boolean(query) && !item.dataset.recipientName.toLocaleLowerCase("fr").includes(query); });
    });
    const validation = root.querySelector("[data-validation-toggle]");
    const validationTitle = root.querySelector("[data-validation-title]");
    const validationMessage = root.querySelector("[data-validation-message]");
    validation?.addEventListener("change", () => {
        const manuel = validation.checked;
        validationTitle.textContent = manuel
            ? "Les réponses doivent être validées par la direction avant de devenir officielles"
            : "Appliquer automatiquement les disponibilités à l’envoi";
        validationMessage.textContent = manuel
            ? "Les disponibilités envoyées ne modifieront les disponibilités officielles qu’après validation."
            : "Les disponibilités déclarées par l’animateur deviendront immédiatement officielles et pourront être utilisées pour les affectations.";
    });
    const addPanels = [...root.querySelectorAll("[data-add-panel]")];
    addPanels.forEach((panel) => {
        panel.addEventListener("toggle", () => {
            if (panel.open) addPanels.forEach((other) => { if (other !== panel) other.open = false; });
        });
    });
    root.querySelectorAll("[data-close-add]").forEach((button) => {
        button.addEventListener("click", () => { button.closest("details").open = false; });
    });
    updateRecipientCount();
});
