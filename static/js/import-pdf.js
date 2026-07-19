import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

const DAYS = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven."];
const SLOT_LABELS = ["Case 1", "Case 2", "Case 3"];
const CHECKED_MARKS = new Set(["\uf14a", "✓", "✔", "☑"]);
const EMPTY_MARKS = new Set(["\uf0c8", "□", "☐", "◻"]);
const $ = (id) => document.getElementById(id);
const state = { data: null, objectUrl: null };

const dropZone = $("pdf-drop-zone");
const fileInput = $("pdf-file-input");
const chooseButton = $("choose-pdf-button");

function normalise(value = "") {
    return String(value).replace(/\s+/g, " ").trim();
}

function escapeHtml(value = "") {
    return String(value).replace(/[&<>'"]/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    }[char]));
}

function setProgress(visible, title = "Lecture du PDF…", detail = "") {
    $("import-progress").hidden = !visible;
    $("progress-title").textContent = title;
    $("progress-detail").textContent = detail;
}

function showError(message = "") {
    const box = $("import-error");
    box.textContent = message;
    box.hidden = !message;
}

/**
 * PDF.js renvoie chaque mot ou groupe de symboles séparément. Cette fonction
 * reconstruit les lignes visuelles à partir de leurs coordonnées, sans dépendre
 * de la façon dont le PDF a découpé les mots.
 */
function groupItemsIntoLines(items, tolerance = 3) {
    const lines = [];
    const sorted = [...items].sort((a, b) => {
        const yDiff = a.y - b.y;
        return Math.abs(yDiff) > tolerance ? yDiff : a.x - b.x;
    });

    sorted.forEach((item) => {
        let line = lines.find((candidate) => Math.abs(candidate.y - item.y) <= tolerance);
        if (!line) {
            line = { y: item.y, items: [] };
            lines.push(line);
        }
        line.items.push(item);
        line.y = line.items.reduce((sum, lineItem) => sum + lineItem.y, 0) / line.items.length;
    });

    return lines
        .sort((a, b) => a.y - b.y)
        .map((line) => {
            line.items.sort((a, b) => a.x - b.x);
            line.text = normalise(line.items.map((item) => item.str).join(" "));
            return line;
        });
}

function parseHeader(fullText) {
    const heading = fullText.match(/Semaine\s+(\d+)\s*-\s*Du\s+(.+?)\s+ACCUEIL DE LOISIRS\s+(.+?)\s+-\s+(.+?)\s+-\s+(.+?)\s+-\s+(\d+)\s+inscrits/i);
    if (!heading) {
        return { semaine: "", periode: "", centre: "", vacances: "", saison: "", inscrits: "" };
    }
    return {
        semaine: `Semaine ${heading[1]}`,
        periode: normalise(heading[2]),
        centre: normalise(heading[3]),
        vacances: normalise(heading[4]),
        saison: normalise(heading[5]),
        inscrits: heading[6],
    };
}

function numbersFromItems(items, minimumX = 380) {
    const values = [];
    items
        .filter((item) => item.x >= minimumX)
        .sort((a, b) => a.x - b.x)
        .forEach((item) => {
            const matches = String(item.str).match(/\b\d{1,3}\b/g) || [];
            matches.forEach((value) => values.push(Number(value)));
        });
    return values;
}

function valuesNearLabel(lines, labelIndex) {
    const labelLine = lines[labelIndex];
    for (let offset = 0; offset <= 2; offset += 1) {
        const line = lines[labelIndex + offset];
        if (!line || line.y - labelLine.y > 22) break;
        const values = numbersFromItems(line.items);
        if (values.length >= 15) return values.slice(-15);
    }
    return [];
}

function parseEffectifs(pages) {
    const result = { total: [], groups: [] };

    pages.forEach((page) => {
        page.lines.forEach((line, index) => {
            const text = line.text.toLowerCase();
            if (/^total(?:\s|$)/i.test(line.text) && result.total.length === 0) {
                result.total = valuesNearLabel(page.lines, index);
            }

            let label = "";
            if (/\b2\s*-\s*5\s+ans\b/i.test(line.text)) label = "2-5 ans";
            if (/\b6\s+ans\s+et\s*\+/i.test(line.text)) label = "6 ans et +";
            if (!label || result.groups.some((group) => group.label === label)) return;

            const values = valuesNearLabel(page.lines, index);
            if (values.length >= 15) result.groups.push({ label, values });
        });
    });

    return result;
}

function findDayColumns(page) {
    const candidates = page.items.filter((item) => /^(lun\.|mar\.|mer\.|jeu\.|ven\.)/i.test(normalise(item.str)));
    const columns = [];
    candidates.forEach((item) => {
        const key = normalise(item.str).slice(0, 3).toLowerCase();
        if (!columns.some((column) => column.key === key)) columns.push({ key, x: item.x });
    });
    return columns.sort((a, b) => a.x - b.x).slice(0, 5);
}

function groupLabel(text) {
    if (/^2\s*-\s*5\s+ans$/i.test(normalise(text))) return "2-5 ans";
    if (/^6\s+ans\s+et\s*\+$/i.test(normalise(text))) return "6 ans et +";
    return "";
}

function looksLikeName(text) {
    const value = normalise(text);
    if (!value || value.split(" ").length < 2) return false;
    if (/allerg|alimentaire|intol[eé]rance|aeeh|pai|sans porc|sans viande|semaine|imprim[eé]|filtres?/i.test(value)) return false;
    return /^[A-Za-zÀ-ÖØ-öø-ÿŒœ'’ -]+$/.test(value) && /[A-ZÀ-ÖØ-Þ]/.test(value);
}

function childCandidates(page) {
    const leftLines = groupItemsIntoLines(page.items.filter((item) => item.x < 190));
    const candidates = [];

    leftLines.forEach((line, index) => {
        if (groupLabel(line.text)) return;

        const inlineAge = line.text.match(/^(.+?)\s+(\d{1,2})\s+ans\b/i);
        if (inlineAge && looksLikeName(inlineAge[1])) {
            candidates.push({
                name: normalise(inlineAge[1]),
                age: Number(inlineAge[2]),
                y: line.y,
                ageY: line.y,
            });
            return;
        }

        const ageOnly = line.text.match(/^(\d{1,2})\s+ans$/i);
        const previous = leftLines[index - 1];
        if (ageOnly && previous && line.y - previous.y <= 19 && looksLikeName(previous.text)) {
            candidates.push({
                name: normalise(previous.text),
                age: Number(ageOnly[1]),
                y: previous.y,
                ageY: line.y,
            });
        }
    });

    return candidates.sort((a, b) => a.y - b.y);
}

function isDocumentNoise(text) {
    const value = normalise(text);
    return !value
        || /^\d+\s*\/\s*\d+$/.test(value)
        || /^Semaine\s+\d+/i.test(value)
        || /^Imprim[eé]\s+le/i.test(value)
        || /^Total$/i.test(value)
        || /^\d+\s+filtres?/i.test(value)
        || groupLabel(value);
}

function extractPhone(rawValue) {
    const raw = normalise(rawValue);
    const candidate = raw.match(/(?:\+33|0)[\d .-]{8,}/)?.[0] || "";
    let digits = candidate.replace(/\D/g, "");
    if (digits.startsWith("33") && digits.length === 11) digits = `0${digits.slice(2)}`;
    if (digits.length < 10) return "";
    digits = digits.slice(0, 10);
    return digits.replace(/(\d{2})(?=\d)/g, "$1 ").trim();
}

function parseContacts(items) {
    const lines = groupItemsIntoLines(items.filter((item) => item.x >= 190 && item.x < 390));
    const contacts = [];
    let pending = null;

    const flush = () => {
        if (!pending) return;
        const phone = extractPhone(pending.details);
        const detailsWithoutPhone = normalise(pending.details.replace(/(?:\+33|0)[\d .-]{8,}/, ""));
        contacts.push({
            name: normalise(pending.name) || "Contact",
            phone,
            detail: detailsWithoutPhone,
        });
        pending = null;
    };

    lines.forEach((line) => {
        const text = normalise(line.text);
        if (!text || isDocumentNoise(text)) return;

        const colonIndex = text.indexOf(":");
        if (colonIndex >= 0) {
            flush();
            pending = {
                name: text.slice(0, colonIndex),
                details: text.slice(colonIndex + 1),
            };
            if (extractPhone(pending.details)) flush();
            return;
        }

        if (pending && !extractPhone(pending.details)) {
            pending.details = normalise(`${pending.details} ${text}`);
            if (extractPhone(pending.details)) flush();
            return;
        }

        flush();
        contacts.push({ name: text, phone: "", detail: "" });
    });
    flush();

    const unique = new Map();
    contacts.forEach((contact) => {
        const key = `${contact.name.toLowerCase()}|${contact.phone}|${contact.detail}`;
        if (!unique.has(key)) unique.set(key, contact);
    });
    return [...unique.values()];
}

function decodeMarkerSlots(text) {
    const slots = [];
    for (const character of String(text)) {
        if (CHECKED_MARKS.has(character)) slots.push(true);
        if (EMPTY_MARKS.has(character)) slots.push(false);
    }
    return slots;
}

function detectPresence(page, rowItems, dayColumns) {
    if (dayColumns.length !== 5) return Array.from({ length: 5 }, () => []);

    const boundaries = dayColumns.map((column, index) => ({
        min: index === 0 ? column.x - 18 : (dayColumns[index - 1].x + column.x) / 2,
        max: index === 4 ? page.width + 5 : (column.x + dayColumns[index + 1].x) / 2,
    }));

    return boundaries.map((boundary) => {
        const slots = rowItems
            .filter((item) => item.x >= boundary.min && item.x < boundary.max)
            .sort((a, b) => a.x - b.x)
            .flatMap((item) => decodeMarkerSlots(item.str));
        if (!slots.length) return [false, false, false];
        return slots.slice(0, 3).concat([false, false, false]).slice(0, 3);
    });
}

function parseNotes(rowItems, candidate) {
    const lines = groupItemsIntoLines(rowItems.filter((item) => item.x < 190));
    const notes = lines
        .filter((line) => Math.abs(line.y - candidate.y) > 3 && Math.abs(line.y - candidate.ageY) > 3)
        .map((line) => normalise(line.text))
        .filter((text) => !isDocumentNoise(text))
        .filter((text) => !/^.+?\s+\d{1,2}\s+ans\b/i.test(text));
    return [...new Set(notes)];
}

function parseChildren(pages) {
    const children = [];
    let activeGroup = "";
    let activeDayColumns = [];

    pages.forEach((page) => {
        const detectedDayColumns = findDayColumns(page);
        if (detectedDayColumns.length === 5) activeDayColumns = detectedDayColumns;
        const dayColumns = activeDayColumns;
        const candidates = childCandidates(page);
        const headers = groupItemsIntoLines(page.items.filter((item) => item.x < 190))
            .map((line) => ({ y: line.y, label: groupLabel(line.text) }))
            .filter((header) => header.label);

        candidates.forEach((candidate, index) => {
            headers.forEach((header) => {
                if (header.y <= candidate.y) activeGroup = header.label;
            });

            const nextCandidate = candidates[index + 1];
            const rowStart = Math.max(0, candidate.y - 11);
            const rowEnd = nextCandidate ? nextCandidate.y - 7 : page.height - 18;
            const rowItems = page.items.filter((item) => item.y >= rowStart && item.y < rowEnd);

            children.push({
                name: candidate.name,
                age: candidate.age,
                group: activeGroup || (candidate.age <= 5 ? "2-5 ans" : "6 ans et +"),
                contacts: parseContacts(rowItems),
                notes: parseNotes(rowItems, candidate),
                presence: detectPresence(page, rowItems, dayColumns),
                page: page.number,
            });
        });

        if (headers.length) activeGroup = headers[headers.length - 1].label;
    });

    const unique = new Map();
    children.forEach((child) => {
        const key = `${child.name.toLowerCase()}-${child.age}`;
        if (!unique.has(key)) unique.set(key, child);
    });
    return [...unique.values()];
}

function parseFilterSummary(fullText) {
    const data = [];
    const patterns = [
        ["Repas sans porc", /L'enfant prend-il des repas sans porc\s*\?\s*:\s*(\d+)/i],
        ["Repas sans viande", /L'enfant prend-il des repas sans viande\s*\?\s*:\s*(\d+)/i],
        ["Allergies alimentaires", /Allergie alimentaire\s*:\s*(\d+)/i],
    ];
    patterns.forEach(([label, regex]) => {
        const match = fullText.match(regex);
        if (match) data.push({ label, value: match[1] });
    });
    return data;
}

async function readPdf(file) {
    const buffer = await file.arrayBuffer();
    const document = await pdfjsLib.getDocument({ data: buffer }).promise;
    const pages = [];

    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
        setProgress(true, "Lecture du PDF…", `Page ${pageNumber} sur ${document.numPages}`);
        const page = await document.getPage(pageNumber);
        const viewport = page.getViewport({ scale: 1 });
        const content = await page.getTextContent();
        const items = content.items.map((item) => ({
            str: item.str,
            x: item.transform[4],
            // Conversion en coordonnées visuelles : 0 = haut de page.
            y: viewport.height - item.transform[5],
            width: item.width || 0,
            height: item.height || 0,
        }));
        const lines = groupItemsIntoLines(items);
        pages.push({ number: pageNumber, width: viewport.width, height: viewport.height, items, lines });
    }

    const rawText = pages
        .map((page) => `PAGE ${page.number}\n${page.lines.map((line) => line.text).join("\n")}`)
        .join("\n\n");

    return {
        header: parseHeader(rawText),
        effectifs: parseEffectifs(pages),
        children: parseChildren(pages),
        filters: parseFilterSummary(rawText),
        rawText,
        pages: document.numPages,
    };
}

function renderEffectifs(effectifs) {
    const rows = [];
    if (effectifs.total.length) rows.push({ label: "Total", values: effectifs.total });
    rows.push(...effectifs.groups);

    if (!rows.length) {
        $("effectifs-table").innerHTML = '<div class="empty-state">Aucun tableau d’effectifs n’a pu être reconnu automatiquement.</div>';
        return;
    }

    const dayHeaders = DAYS.map((day) => `<th colspan="3">${day}</th>`).join("");
    const slotHeaders = DAYS.map(() => SLOT_LABELS.map((label) => `<th title="${label}">${label.replace("Case ", "")}</th>`).join("")).join("");
    const body = rows.map((row) => `<tr><td><strong>${escapeHtml(row.label)}</strong></td>${row.values.map((value) => `<td>${value}</td>`).join("")}</tr>`).join("");
    $("effectifs-table").innerHTML = `
        <p class="import-help">Les colonnes 1, 2 et 3 correspondent exactement aux trois cases affichées pour chaque journée dans le PDF.</p>
        <table class="import-table">
            <thead><tr><th rowspan="2">Groupe</th>${dayHeaders}</tr><tr>${slotHeaders}</tr></thead>
            <tbody>${body}</tbody>
        </table>`;
}

function renderPresenceDay(day, slots) {
    const selected = slots.some(Boolean);
    const boxes = slots.map((isSelected, index) => `<span class="presence-slot ${isSelected ? "is-selected" : ""}" title="${SLOT_LABELS[index]}">${isSelected ? "✓" : ""}</span>`).join("");
    return `<span class="presence-day ${selected ? "is-present" : ""}"><strong>${day}</strong><span class="presence-slots">${boxes}</span></span>`;
}

function renderChildren(children, query = "") {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = children.filter((child) => !normalizedQuery || `${child.name} ${child.group} ${child.notes.join(" ")} ${child.contacts.map((contact) => `${contact.name} ${contact.phone}`).join(" ")}`.toLowerCase().includes(normalizedQuery));
    $("children-count").textContent = `${children.length} enfant${children.length > 1 ? "s" : ""} détecté${children.length > 1 ? "s" : ""} — ${filtered.length} affiché${filtered.length > 1 ? "s" : ""}.`;

    if (!filtered.length) {
        $("children-list").innerHTML = '<div class="empty-state">Aucun enfant ne correspond à cette recherche.</div>';
        return;
    }

    $("children-list").innerHTML = filtered.map((child) => {
        const contacts = child.contacts.length
            ? child.contacts.map((contact) => {
                const phone = contact.phone ? ` : ${escapeHtml(contact.phone)}` : "";
                const detail = contact.detail ? ` — ${escapeHtml(contact.detail)}` : "";
                return `<li><strong>${escapeHtml(contact.name || "Contact")}</strong>${phone}${detail}</li>`;
            }).join("")
            : "<li>Aucun contact reconnu</li>";
        const notes = child.notes.length
            ? child.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")
            : "<li>Aucune mention particulière</li>";
        const presence = child.presence.map((slots, index) => renderPresenceDay(DAYS[index], slots)).join("");

        return `<article class="child-card" data-child-name="${escapeHtml(child.name.toLowerCase())}">
            <div>
                <div class="child-name">${escapeHtml(child.name)} <span class="child-age">${child.age} ans</span></div>
                <span class="child-group">${escapeHtml(child.group)}</span>
                <span class="child-page">Page ${child.page}</span>
            </div>
            <div><ul class="contact-list">${contacts}</ul><ul class="note-list">${notes}</ul></div>
            <div class="presence-row">${presence}</div>
        </article>`;
    }).join("");
}

function renderSpecial(data) {
    const entries = [...data.filters];
    data.children.forEach((child) => child.notes.forEach((note) => entries.push({ label: child.name, value: note })));

    const unique = new Map();
    entries.forEach((entry) => {
        const key = `${entry.label.toLowerCase()}|${String(entry.value).toLowerCase()}`;
        if (!unique.has(key)) unique.set(key, entry);
    });
    const uniqueEntries = [...unique.values()];

    if (!uniqueEntries.length) {
        $("special-info").innerHTML = '<div class="empty-state">Aucune information particulière reconnue.</div>';
        return;
    }
    $("special-info").innerHTML = uniqueEntries.map((entry) => `<article class="special-card"><h3>${escapeHtml(entry.label)}</h3><p>${escapeHtml(entry.value)}</p></article>`).join("");
}

function render(data, file) {
    state.data = data;
    $("summary-centre").textContent = data.header.centre || "Non reconnu";
    $("summary-vacances").textContent = [data.header.vacances, data.header.saison].filter(Boolean).join(" — ") || "Non reconnues";
    $("summary-periode").textContent = [data.header.semaine, data.header.periode].filter(Boolean).join(" — ") || "Non reconnue";
    $("summary-inscrits").textContent = data.header.inscrits || data.children.length || "—";
    renderEffectifs(data.effectifs);
    renderChildren(data.children);
    renderSpecial(data);
    $("raw-text").textContent = data.rawText;

    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = URL.createObjectURL(file);
    $("pdf-preview").src = state.objectUrl;
    $("import-results").hidden = false;
    $("import-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function handleFile(file) {
    showError("");
    if (!file || (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf"))) {
        showError("Choisis un fichier PDF valide.");
        return;
    }

    setProgress(true, "Lecture du PDF…", file.name);
    $("import-results").hidden = true;
    try {
        const data = await readPdf(file);
        render(data, file);
    } catch (error) {
        console.error(error);
        showError("Le PDF n’a pas pu être analysé. Vérifie qu’il n’est pas protégé ou endommagé.");
    } finally {
        setProgress(false);
    }
}

chooseButton.addEventListener("click", (event) => { event.stopPropagation(); fileInput.click(); });
dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput.click();
    }
});
fileInput.addEventListener("change", () => handleFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
}));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
}));
dropZone.addEventListener("drop", (event) => handleFile(event.dataTransfer.files[0]));
$("children-search").addEventListener("input", (event) => {
    if (state.data) renderChildren(state.data.children, event.target.value);
});
$("toggle-raw-text").addEventListener("click", () => {
    const raw = $("raw-text");
    raw.hidden = !raw.hidden;
    $("toggle-raw-text").textContent = raw.hidden ? "Afficher le texte extrait" : "Masquer le texte extrait";
});
window.addEventListener("beforeunload", () => {
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
});
