(function () {
    "use strict";

    const panel = document.getElementById("planning-horaires");
    if (!panel || !window.PlanningData) return;

    const layout = document.getElementById("layout");
    const selectModalite = document.getElementById("planning-modalite-periscolaire");
    const estPeriscolaire = () => String(layout?.dataset.typeAccueil || "") === "periscolaire";
    const modaliteCourante = () => String(selectModalite?.value || "");

    let events = [];
    let centres = [];
    let dirty = new Set();
    let referenceDate = null;
    let activePreset = null;
    let loadSequence = 0;
    const presetsStorageKey = "planning-horaires-presets";
    const presetColors = ["#dcecff", "#dff4e8", "#fff0cf", "#eadffc", "#ffe0e6", "#dff3f4", "#f3e5d5"];
    const defaultPresets = [
        { id: "ouverture", nom: "Ouverture", debut: "07:15", fin: "17:15", couleur: presetColors[0] },
        { id: "journee", nom: "Journée", debut: "08:00", fin: "18:00", couleur: presetColors[1] },
        { id: "fermeture", nom: "Fermeture", debut: "09:00", fin: "18:00", couleur: presetColors[2] },
    ];
    let presets = loadPresets();

    const esc = (value) => String(value || "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
    }[char]));

    function loadPresets() {
        try {
            const stored = JSON.parse(localStorage.getItem(presetsStorageKey) || "null");
            if (!Array.isArray(stored)) return defaultPresets.map((preset) => ({ ...preset }));
            return stored
                .filter((preset) => preset?.id && preset?.nom && preset?.debut && preset?.fin)
                .map((preset, index) => ({ ...preset, couleur: preset.couleur || presetColors[index % presetColors.length] }));
        } catch {
            return defaultPresets.map((preset) => ({ ...preset }));
        }
    }

    function savePresets() {
        localStorage.setItem(presetsStorageKey, JSON.stringify(presets));
    }

    const week = () => PlanningData.weekRange(referenceDate || new Date());
    const days = (monday) => Array.from({ length: 5 }, (_, index) => {
        const date = new Date(`${monday}T12:00:00`);
        date.setDate(date.getDate() + index);
        return formatDateLocal(date);
    });
    const groupId = (event) => Number(event.extendedProps?.groupe_id || event.extendedProps?.evenement_id || 0);
    const groupName = (event) => event.extendedProps?.groupe_nom || event.extendedProps?.evenement_nom || "Équipe";
    const activeOn = (event, date) => {
        const start = String(event.start || "").slice(0, 10);
        const end = String(event.end || "").slice(0, 10) || start;
        return Boolean(start) && start <= date && date < end;
    };
    const eventFor = (centreId, groupeId, animateurId, date) => events.find((event) =>
        Number(event.extendedProps?.centre_id) === Number(centreId)
        && groupIdOf(event) === Number(groupeId)
        && Number(event.extendedProps?.animateur_id) === Number(animateurId)
        && activeOn(event, date)
    );

    // Alias séparé pour ne pas masquer le paramètre groupeId dans eventFor().
    function groupIdOf(event) {
        return groupId(event);
    }

    function toast(message, error = false) {
        if (typeof window.afficherToast === "function") window.afficherToast(message, error);
    }

    function horaireLabel(horaire) {
        if (!horaire?.heure_arrivee || !horaire?.heure_depart) return "—";
        return `${horaire.heure_arrivee}–${horaire.heure_depart}`;
    }

    function colorForHours(start, end) {
        return presets.find((preset) => preset.debut === start && preset.fin === end)?.couleur || "";
    }

    function paintCell(cell, start, end, color = colorForHours(start, end)) {
        if (color) cell.style.setProperty("--horaire-color", color);
        else cell.style.removeProperty("--horaire-color");
        cell.classList.toggle("has-preset-color", Boolean(color));
    }

    function setEventHoraire(event, date, start, end) {
        event.extendedProps.horaires ||= {};
        if (!start && !end) {
            delete event.extendedProps.horaires[date];
        } else {
            event.extendedProps.horaires[date] = { heure_arrivee: start, heure_depart: end };
        }
        dirty.add(String(event.id));
    }

    function updateCell(cell, start, end) {
        const label = cell.querySelector("[data-cell-value]");
        const inputStart = cell.querySelector('[data-part="heure_arrivee"]');
        const inputEnd = cell.querySelector('[data-part="heure_depart"]');
        if (label) label.textContent = start && end ? `${start}–${end}` : "—";
        if (inputStart) inputStart.value = start || "";
        if (inputEnd) inputEnd.value = end || "";
        paintCell(cell, start, end, activePreset?.debut === start && activePreset?.fin === end ? activePreset.couleur : undefined);
        cell.classList.add("is-dirty");
    }

    function closeCellEditor(cell, { restore = true } = {}) {
        const editor = cell.querySelector("[data-cell-editor]");
        if (!editor) return;
        if (restore) {
            const event = events.find((item) => String(item.id) === cell.dataset.affectationId);
            const horaire = event?.extendedProps?.horaires?.[cell.dataset.date] || {};
            const inputStart = editor.querySelector('[data-part="heure_arrivee"]');
            const inputEnd = editor.querySelector('[data-part="heure_depart"]');
            if (inputStart) inputStart.value = horaire.heure_arrivee || "";
            if (inputEnd) inputEnd.value = horaire.heure_depart || "";
        }
        editor.hidden = true;
        cell.classList.remove("is-editing");
    }

    function openCellEditor(cell) {
        panel.querySelectorAll("td[data-cell].is-editing").forEach((other) => {
            if (other !== cell) closeCellEditor(other);
        });
        const editor = cell.querySelector("[data-cell-editor]");
        if (!editor) return;
        editor.hidden = false;
        cell.classList.add("is-editing");
        editor.querySelector('[data-part="heure_arrivee"]')?.focus();
    }

    function applyPresetToCell(cell) {
        if (!activePreset) {
            openCellEditor(cell);
            return;
        }
        const event = events.find((item) => String(item.id) === cell.dataset.affectationId);
        if (!event) return;
        setEventHoraire(event, cell.dataset.date, activePreset.debut, activePreset.fin);
        updateCell(cell, activePreset.debut, activePreset.fin);
    }

    function centreOrder(byCentre) {
        const known = centres
            .map((centre) => Number(centre.id))
            .filter((id) => byCentre.has(id));
        const knownSet = new Set(known);
        const extras = [...byCentre.keys()].filter((id) => !knownSet.has(id));
        return [...known, ...extras];
    }

    function groupOrder(centreId, list) {
        const groups = new Map();
        list.forEach((event) => {
            const id = groupIdOf(event);
            if (!groups.has(id)) groups.set(id, { id, nom: groupName(event), events: [] });
            groups.get(id).events.push(event);
        });

        const centre = centres.find((item) => Number(item.id) === Number(centreId));
        const order = new Map((centre?.evenements || []).map((groupe, index) => [Number(groupe.id), index]));
        return [...groups.values()].sort((a, b) => {
            const orderA = order.has(a.id) ? order.get(a.id) : Number.MAX_SAFE_INTEGER;
            const orderB = order.has(b.id) ? order.get(b.id) : Number.MAX_SAFE_INTEGER;
            return orderA - orderB || String(a.nom).localeCompare(String(b.nom), "fr");
        });
    }

    function renderCell(centreId, groupeId, animateurId, date) {
        const event = eventFor(centreId, groupeId, animateurId, date);
        if (!event) return '<td class="planning-horaires-cell is-disabled" aria-disabled="true">—</td>';
        const horaire = event.extendedProps?.horaires?.[date] || {};
        const label = horaireLabel(horaire);
        const color = colorForHours(horaire.heure_arrivee, horaire.heure_depart);
        return `
            <td class="planning-horaires-cell${color ? " has-preset-color" : ""}" data-cell data-affectation-id="${esc(event.id)}" data-date="${date}"${color ? ` style="--horaire-color:${color}"` : ""}>
                <button type="button" class="planning-horaires-cell-main" data-apply-cell title="Appliquer la plage active ou modifier manuellement">
                    <span data-cell-value>${esc(label)}</span>
                </button>
                <div class="planning-horaires-cell-editor" data-cell-editor hidden>
                    <label><span>Début</span><input type="time" data-part="heure_arrivee" value="${esc(horaire.heure_arrivee)}"></label>
                    <label><span>Fin</span><input type="time" data-part="heure_depart" value="${esc(horaire.heure_depart)}"></label>
                    <div class="planning-horaires-cell-editor-actions">
                        <button type="button" class="btn btn-primary" data-cell-confirm>OK</button>
                        <button type="button" class="btn btn-secondary" data-cell-cancel>Annuler</button>
                    </div>
                </div>
            </td>`;
    }

    function render() {
        const range = week();
        const dates = days(range.debut);
        const byCentre = new Map();
        events.forEach((event) => {
            const id = Number(event.extendedProps?.centre_id);
            if (!id) return;
            if (!byCentre.has(id)) byCentre.set(id, []);
            byCentre.get(id).push(event);
        });

        panel.innerHTML = `
            <div class="planning-horaires-toolbar">
                <div class="planning-horaires-presets-block">
                    <strong>PLAGES HORAIRES</strong>
                </div>
                <div class="planning-horaires-actions">
                    <button type="button" class="btn btn-secondary" data-export="pdf">Export PDF</button>
                    <button type="button" class="btn btn-secondary" data-export="jpg">Export JPG</button>
                    <button type="button" class="btn btn-primary planning-horaires-save" data-save>Enregistrer les horaires</button>
                </div>
                <div class="planning-horaires-presets"></div>
            </div>
            <form class="planning-horaires-preset-form planning-horaires-new-preset" hidden>
                <label><span>Nom</span><input name="nom" placeholder="Ex. Intermédiaire" required></label>
                <label><span>Début</span><input name="debut" type="time" required></label>
                <label><span>Fin</span><input name="fin" type="time" required></label>
                <button type="submit" class="btn btn-primary">Ajouter</button>
                <button type="button" class="btn btn-secondary" data-cancel>Annuler</button>
            </form>
            <form class="planning-horaires-preset-form planning-horaires-edit-preset" hidden>
                <label><span>Nom</span><input name="nom" required></label>
                <label><span>Début</span><input name="debut" type="time" required></label>
                <label><span>Fin</span><input name="fin" type="time" required></label>
                <button type="submit" class="btn btn-primary">Modifier</button>
                <button type="button" class="btn btn-secondary" data-cancel>Annuler</button>
            </form>
            <div class="planning-horaires-tables"></div>`;

        const zone = panel.querySelector(".planning-horaires-presets");
        const paintPresets = () => {
            panel.classList.toggle("has-active-preset", Boolean(activePreset));
            zone.innerHTML = presets.map((preset) => `
                <span class="planning-horaires-preset-wrap">
                    <button type="button" class="planning-horaires-preset${activePreset?.id === preset.id ? " is-active" : ""}" style="--preset-color:${preset.couleur}" data-preset="${esc(preset.id)}" aria-pressed="${activePreset?.id === preset.id ? "true" : "false"}">
                        ${esc(preset.nom)} <span>${preset.debut}–${preset.fin}</span>
                    </button>
                    <button type="button" class="planning-horaires-preset-action" data-edit="${esc(preset.id)}" aria-label="Modifier ${esc(preset.nom)}" title="Modifier">✎</button>
                    <button type="button" class="planning-horaires-preset-action" data-remove="${esc(preset.id)}" aria-label="Supprimer ${esc(preset.nom)}" title="Supprimer">×</button>
                </span>`).join("")
                + '<button type="button" class="btn btn-secondary" data-add>+ Ajouter une plage</button>';
        };
        paintPresets();

        zone.addEventListener("click", (event) => {
            event.preventDefault();
            const button = event.target.closest("button");
            if (!button) return;

            if (button.hasAttribute("data-add")) {
                const form = panel.querySelector(".planning-horaires-new-preset");
                panel.querySelector(".planning-horaires-edit-preset").hidden = true;
                form.hidden = false;
                form.elements.nom.focus();
                return;
            }

            if (button.hasAttribute("data-preset")) {
                activePreset = presets.find((preset) => preset.id === button.dataset.preset) || null;
                paintPresets();
                return;
            }

            if (button.hasAttribute("data-edit")) {
                const preset = presets.find((item) => item.id === button.dataset.edit);
                if (!preset) return;
                const form = panel.querySelector(".planning-horaires-edit-preset");
                panel.querySelector(".planning-horaires-new-preset").hidden = true;
                form.elements.nom.value = preset.nom;
                form.elements.debut.value = preset.debut;
                form.elements.fin.value = preset.fin;
                form.dataset.presetId = preset.id;
                form.hidden = false;
                form.elements.nom.focus();
                return;
            }

            if (button.hasAttribute("data-remove")) {
                presets = presets.filter((preset) => preset.id !== button.dataset.remove);
                if (activePreset?.id === button.dataset.remove) activePreset = null;
                savePresets();
                paintPresets();
            }
        });

        panel.querySelector(".planning-horaires-new-preset").addEventListener("submit", (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const preset = {
                id: `custom-${Date.now()}`,
                nom: String(data.get("nom") || "").trim(),
                debut: String(data.get("debut") || ""),
                fin: String(data.get("fin") || ""),
                couleur: presetColors[presets.length % presetColors.length],
            };
            if (!preset.nom || !preset.debut || !preset.fin || preset.debut >= preset.fin) {
                toast("La plage horaire est invalide.", true);
                return;
            }
            presets.push(preset);
            activePreset = preset;
            savePresets();
            event.currentTarget.reset();
            event.currentTarget.hidden = true;
            paintPresets();
        });

        panel.querySelector(".planning-horaires-edit-preset").addEventListener("submit", (event) => {
            event.preventDefault();
            const preset = presets.find((item) => item.id === event.currentTarget.dataset.presetId);
            const data = new FormData(event.currentTarget);
            const nom = String(data.get("nom") || "").trim();
            const debut = String(data.get("debut") || "");
            const fin = String(data.get("fin") || "");
            if (!preset || !nom || !debut || !fin || debut >= fin) {
                toast("La plage horaire est invalide.", true);
                return;
            }
            preset.nom = nom;
            preset.debut = debut;
            preset.fin = fin;
            savePresets();
            event.currentTarget.hidden = true;
            paintPresets();
        });

        panel.querySelectorAll("[data-cancel]").forEach((button) => button.addEventListener("click", (event) => {
            event.preventDefault();
            button.closest("form").hidden = true;
        }));

        const tables = panel.querySelector(".planning-horaires-tables");
        tables.innerHTML = centreOrder(byCentre).map((centreId) => {
            const list = byCentre.get(centreId) || [];
            const groups = groupOrder(centreId, list);
            const rows = groups.flatMap((group, groupIndex) => {
                const people = new Map();
                group.events.forEach((event) => {
                    const id = Number(event.extendedProps?.animateur_id);
                    if (!people.has(id)) people.set(id, event.extendedProps?.animateur_nom || event.title || `Animateur ${id}`);
                });
                const peopleRows = [...people.entries()]
                    // FullCalendar utilise l'id animateur comme premier critère d'ordre dans Affectations.
                    .sort(([idA], [idB]) => Number(idA) - Number(idB))
                    .map(([animateurId, nom], personIndex, allPeople) => `
                        <tr class="planning-horaires-group-row group-tone-${groupIndex % 2}${personIndex === allPeople.length - 1 ? " is-group-last" : ""}">
                            <th scope="row">${esc(nom)}</th>
                            ${dates.map((date) => renderCell(centreId, group.id, animateurId, date)).join("")}
                            <td class="planning-horaires-row-action"><button type="button" class="btn btn-secondary planning-horaires-copy">Même horaire</button></td>
                        </tr>`);
                if (!peopleRows.length) return [];
                return [
                    `<tr class="planning-horaires-group group-tone-${groupIndex % 2}"><th colspan="${dates.length + 1}">${esc(group.nom)}</th><td class="planning-horaires-row-action"></td></tr>`,
                    ...peopleRows,
                ];
            }).join("");
            if (!rows) return "";
            const centre = centres.find((item) => Number(item.id) === Number(centreId));
            const nom = centre?.nom || `Centre ${centreId}`;
            return `
                <section class="planning-horaires-centre" data-centre-id="${centreId}">
                    <div class="planning-horaires-heading"><h2>${esc(nom)}</h2></div>
                    <div class="planning-horaires-table-wrap">
                        <table>
                            <thead><tr><th>Animateur</th>${dates.map((date) => `<th>${new Date(`${date}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit" })}</th>`).join("")}<th></th></tr></thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                </section>`;
        }).join("") || '<p class="empty-note">Aucun animateur affecté dans les centres cette semaine.</p>';

        bindCells();
    }

    function exportTitle() {
        const range = week();
        const date = (value) => new Date(`${value}T12:00:00`).toLocaleDateString("fr-FR");
        return `Planning horaire — semaine du ${date(range.debut)} au ${date(range.fin)}`;
    }

    async function exportPlanning(format) {
        if (!window.html2canvas) {
            toast("Le module d’export n’est pas disponible.", true);
            return;
        }
        const wrapper = document.createElement("div");
        wrapper.className = "planning-horaires planning-horaires-export-canvas";
        wrapper.innerHTML = `<h1>${esc(exportTitle())}</h1>`;
        const exportedTables = panel.querySelector(".planning-horaires-tables").cloneNode(true);
        exportedTables.querySelectorAll(".planning-horaires-cell-main").forEach((button) => {
            const value = document.createElement("div");
            value.className = "planning-horaires-export-value";
            value.textContent = button.querySelector("[data-cell-value]")?.textContent || "—";
            button.replaceWith(value);
        });
        wrapper.append(exportedTables);
        document.body.append(wrapper);
        try {
            const canvas = await window.html2canvas(wrapper, { backgroundColor: "#ffffff", scale: 2, useCORS: true });
            const filename = `planning-horaires-${week().debut}`;
            if (format === "jpg") {
                const link = document.createElement("a");
                link.download = `${filename}.jpg`;
                link.href = canvas.toDataURL("image/jpeg", 0.94);
                link.click();
                return;
            }
            if (!window.jspdf?.jsPDF) throw new Error("Le module PDF n’est pas disponible.");
            const pdf = new window.jspdf.jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
            const pageWidth = pdf.internal.pageSize.getWidth();
            const pageHeight = pdf.internal.pageSize.getHeight();
            const imageHeight = canvas.height * pageWidth / canvas.width;
            for (let offset = 0; offset < imageHeight; offset += pageHeight) {
                if (offset) pdf.addPage();
                pdf.addImage(canvas, "JPEG", 0, -offset, pageWidth, imageHeight, undefined, "FAST");
            }
            pdf.save(`${filename}.pdf`);
        } catch (error) {
            toast(error.message || "L’export a échoué.", true);
        } finally {
            wrapper.remove();
        }
    }

    function bindCells() {
        const tables = panel.querySelector(".planning-horaires-tables");
        if (!tables) return;

        tables.addEventListener("click", (event) => {
            const copyButton = event.target.closest(".planning-horaires-copy");
            if (copyButton) {
                event.preventDefault();
                const row = copyButton.closest("tr");
                const source = [...row.querySelectorAll("td[data-cell]")].find((cell) => {
                    const assignment = events.find((item) => String(item.id) === cell.dataset.affectationId);
                    const horaire = assignment?.extendedProps?.horaires?.[cell.dataset.date];
                    return horaire?.heure_arrivee && horaire?.heure_depart;
                });
                if (!source) {
                    toast("Saisissez d’abord un horaire sur cette ligne.", true);
                    return;
                }
                const sourceEvent = events.find((item) => String(item.id) === source.dataset.affectationId);
                const sourceHoraire = sourceEvent.extendedProps.horaires[source.dataset.date];
                row.querySelectorAll("td[data-cell]").forEach((cell) => {
                    const assignment = events.find((item) => String(item.id) === cell.dataset.affectationId);
                    if (!assignment) return;
                    setEventHoraire(assignment, cell.dataset.date, sourceHoraire.heure_arrivee, sourceHoraire.heure_depart);
                    updateCell(cell, sourceHoraire.heure_arrivee, sourceHoraire.heure_depart);
                });
                return;
            }

            const cell = event.target.closest("td[data-cell]");
            if (!cell) return;

            if (event.target.closest("[data-edit-cell]")) {
                event.preventDefault();
                event.stopPropagation();
                openCellEditor(cell);
                return;
            }

            if (event.target.closest("[data-cell-cancel]")) {
                event.preventDefault();
                event.stopPropagation();
                closeCellEditor(cell);
                return;
            }

            if (event.target.closest("[data-cell-confirm]")) {
                event.preventDefault();
                event.stopPropagation();
                const start = cell.querySelector('[data-part="heure_arrivee"]').value;
                const end = cell.querySelector('[data-part="heure_depart"]').value;
                if ((start && !end) || (!start && end) || (start && end && end <= start)) {
                    toast("L’heure de fin doit être après l’heure de début.", true);
                    return;
                }
                const assignment = events.find((item) => String(item.id) === cell.dataset.affectationId);
                if (!assignment) return;
                setEventHoraire(assignment, cell.dataset.date, start, end);
                updateCell(cell, start, end);
                closeCellEditor(cell, { restore: false });
                return;
            }

            if (event.target.closest("[data-cell-editor]")) return;

            if (event.target.closest("[data-apply-cell]") || event.target === cell) {
                event.preventDefault();
                applyPresetToCell(cell);
            }
        });

        tables.addEventListener("keydown", (event) => {
            const input = event.target.closest('[data-cell-editor] input[type="time"]');
            if (!input || event.key !== "Enter") return;
            event.preventDefault();
            const cell = input.closest("td[data-cell]");
            const inputs = [...cell.querySelectorAll('[data-cell-editor] input[type="time"]')];
            const index = inputs.indexOf(input);
            if (index >= 0 && index < inputs.length - 1) {
                inputs[index + 1].focus();
            } else {
                cell.querySelector("[data-cell-confirm]")?.click();
            }
        });

        panel.querySelector("[data-save]")?.addEventListener("click", sauvegarder);
        panel.querySelectorAll("[data-export]").forEach((button) => button.addEventListener("click", () => exportPlanning(button.dataset.export)));
    }

    async function charger() {
        const sequence = ++loadSequence;
        const range = week();
        const modalite = modaliteCourante();
        panel.hidden = false;
        if (estPeriscolaire() && !modalite) {
            events = [];
            centres = [];
            dirty = new Set();
            panel.innerHTML = '<p class="empty-note">Choisissez un créneau périscolaire en haut du Planning pour saisir les horaires correspondants.</p>';
            return;
        }
        panel.innerHTML = '<p class="empty-note">Chargement des horaires…</p>';
        try {
            const [nextCentres, nextEvents] = await Promise.all([
                PlanningData.fetchCentresWithGroups(range.debut, range.fin),
                PlanningData.fetchWeekEvents(range.debut, range.fin, { force: true, modalite }),
            ]);
            if (sequence !== loadSequence || panel.hidden) return;
            centres = nextCentres || [];
            events = (nextEvents || []).filter((event) => event.extendedProps?.centre_id);
            dirty = new Set();
            render();
        } catch (error) {
            if (sequence !== loadSequence || panel.hidden) return;
            panel.innerHTML = `<p class="empty-note">${esc(error.message || "Chargement impossible")}</p>`;
        }
    }

    async function sauvegarder() {
        const ids = [...dirty];
        if (!ids.length) {
            toast("Aucune modification à enregistrer.");
            return;
        }
        const button = panel.querySelector("[data-save]");
        if (button) button.disabled = true;
        try {
            await Promise.all(ids.map((id) => {
                const event = events.find((item) => String(item.id) === id);
                if (!event) return Promise.resolve();
                const horaires = Object.entries(event.extendedProps?.horaires || {})
                    .filter(([, horaire]) => horaire?.heure_arrivee && horaire?.heure_depart)
                    .map(([date, horaire]) => ({ date, heure_arrivee: horaire.heure_arrivee, heure_depart: horaire.heure_depart }));
                return apiFetch(`/api/affectations/${id}/`, { method: "PATCH", body: JSON.stringify({ horaires }) });
            }));
            dirty.clear();
            panel.querySelectorAll(".is-dirty").forEach((cell) => cell.classList.remove("is-dirty"));
            PlanningData.invalidateWeekEvents();
            toast("Horaires enregistrés.");
        } catch (error) {
            toast(error.message || "Enregistrement impossible.", true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    function mode(name) {
        const visible = name === "horaires";
        panel.hidden = !visible;
        if (!visible) {
            loadSequence += 1; // invalide un éventuel chargement encore en cours
            return;
        }
        charger();
    }

    // planning.js reste la source de vérité du mode et de la semaine active.
    // On évite ainsi qu'un chargement précoce basé sur l'URL/la date du jour
    // prenne le pas sur datePeriodeCourante.
    document.addEventListener("planning:mode-change", (event) => {
        if (event.detail?.date) referenceDate = event.detail.date;
        mode(event.detail?.mode);
    });

    document.getElementById("planning-period-nav")?.addEventListener("week-picker:select", (event) => {
        referenceDate = event.detail?.date || referenceDate;
        if (!panel.hidden) charger();
    });

    document.addEventListener("planning:modalite-change", () => {
        if (!panel.hidden) charger();
    });
})();
