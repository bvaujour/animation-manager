document.addEventListener("DOMContentLoaded", () => {
    const recapRoot = document.querySelector("[data-recap-root]");
    const startInput = document.getElementById("recap-date-start");
    const endInput = document.getElementById("recap-date-end");
    const periodError = document.getElementById("recap-period-error");
    const refreshButton = document.getElementById("recap-refresh");
    const centresRoot = document.getElementById("recap-centres");
    const employeesRoot = document.getElementById("recap-salaries");
    const payrollRoot = document.getElementById("recap-payroll");
    const legendRoot = document.getElementById("recap-legende");
    const tabButtons = Array.from(document.querySelectorAll("[data-recap-tab]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-recap-panel]"));
    const pdfButton = document.getElementById("btn-recap-pdf");
    const excelButton = document.getElementById("btn-recap-excel");
    const scopeRoot = document.getElementById("recap-payroll-scope");
    const savePrimesButton = document.getElementById("save-payroll-primes");
    const cancelPrimesButton = document.getElementById("cancel-payroll-primes");
    let selectedRange = null;
    let payrollPeriodIds = [];
    let dirtyPrimes = new Map();
    let lastData = null;
    let primeCatalog = [];
    let primeEligibility = new Map();
    const openPrimeKeys = new Set();
    const primeMutationQueues = new Map();
    const queuedPrimeMutations = new Set();
    const PAYROLL_RANGE_STORAGE_KEY = "animation-manager:payroll-date-range-v1";

    const currencyFormatter = new Intl.NumberFormat("fr-FR", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: 2,
    });

    function formatMoney(value) {
        if (value === null || value === undefined || value === "") return null;
        const number = Number(value);
        return Number.isFinite(number) ? currencyFormatter.format(number) : null;
    }

    function formatDailyPrime(value) {
        if (value === null || value === undefined || value === "") return null;
        const number = Number(value);
        return Number.isInteger(number) ? `${number} €` : null;
    }

    function attributionPrimeHtml(item) {
        const periode = item.date_debut === item.date_fin
            ? formatContractDate(item.date_debut)
            : `${formatContractDate(item.date_debut)} → ${formatContractDate(item.date_fin)}`;
        const mode = item.mode || item.mode_calcul;
        const detailMontant = !item.historique && mode === "jour" && Number.isInteger(Number(item.nombre_jours))
            ? `${item.nombre_jours} j × ${formatMoney(item.montant_unitaire)} = ${formatMoney(item.montant_total)}`
            : formatMoney(item.montant_total);
        const nom = item.nom || item.type_prime_nom;
        return `<span class="payroll-attribution" data-attribution-item="${item.id || "historique"}">${escapeHtml(nom)} · <strong>${detailMontant}</strong><small>${periode}${item.historique ? " · historique" : ""}</small>${item.historique ? "" : ` <button type="button" class="btn btn-secondary btn-small" data-edit-attribution="${item.id}">Modifier</button> <button type="button" class="btn btn-danger btn-small" data-delete-attribution="${item.id}">Supprimer</button>`}</span>`;
    }

    function primeSummaryValues(prime) {
        const resume = prime.resume_attributions || {};
        if (!resume.nombre_attributions) {
            return {titre: prime.nom, detail: "aucune attribution"};
        }
        const titre = `${prime.nom} — ${formatMoney(resume.montant_total)}`;
        if (prime.mode_calcul === "forfait") return {titre, detail: "forfait"};
        if (resume.montants_variables) {
            const unite = prime.mode_calcul === "jour"
                ? `${resume.quantite} jours attribués`
                : prime.mode_calcul === "semaine"
                    ? `${resume.quantite} sem. attribuée${resume.quantite > 1 ? "s" : ""}`
                    : `${resume.quantite} mois attribué${resume.quantite > 1 ? "s" : ""}`;
            return {titre, detail: `${unite} · montants variables`};
        }
        const unite = prime.mode_calcul === "jour"
            ? `${resume.quantite} j`
            : prime.mode_calcul === "semaine"
                ? `${resume.quantite} sem.`
                : `${resume.quantite} mois`;
        return {titre, detail: `${unite} × ${formatMoney(resume.montant_unitaire)}`};
    }

    function updatePrimeEditorSummary(editor, prime) {
        if (!editor || !prime) return;
        const resume = primeSummaryValues(prime);
        editor.querySelector("[data-prime-summary-title]").textContent = resume.titre;
        editor.querySelector("[data-prime-summary-detail]").textContent = `(${resume.detail})`;
    }

    function textColorFor(background) {
        const hex = String(background || "").replace("#", "");
        if (!/^[0-9a-f]{6}$/i.test(hex)) return "#1f2937";
        const r = Number.parseInt(hex.slice(0, 2), 16);
        const g = Number.parseInt(hex.slice(2, 4), 16);
        const b = Number.parseInt(hex.slice(4, 6), 16);
        return ((r * 299 + g * 587 + b * 114) / 1000) >= 150 ? "#172033" : "#ffffff";
    }

    function centreBadge(centre) {
        const background = centre.couleur || "#e5e7eb";
        return `<span class="place-badge" style="--place-color:${escapeHtml(background)};--place-text:${textColorFor(background)}">${escapeHtml(centre.nom)}</span>`;
    }

    function buildApiUrl(base = "/api/recapitulatif/") {
        if (!selectedRange) return null;
        const params = new URLSearchParams({date_debut: selectedRange.start, date_fin: selectedRange.end});
        return `${base}?${params}`;
    }

    function displayLegend(centres) {
        legendRoot.innerHTML = centres.length ? centres.map(centreBadge).join("") : "";
    }

    function missingRateCell() {
        return '<span class="missing-rate" title="Tarif manquant : renseigne la paie par jour dans la fiche salarié">Manquant</span>';
    }

    function formatContractDate(value) {
        if (!value) return "Date non renseignée";
        const [year, month, day] = value.split("-");
        return `${day}/${month}/${year}`;
    }

    function contractTypeLabel(type) {
        if (type === "apprentissage") return "Apprentissage";
        if (type === "cdd") return "CDD";
        if (type === "permanent") return "Permanent";
        return "CEE";
    }

    function contractCell(animateur) {
        const seen = new Set();
        const segments = (animateur.segments_contractuels || []).filter((segment) => {
            const key = segment.contrat_id
                ? `contrat-${segment.contrat_id}`
                : `implicite-${segment.type_contrat}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
        if (!segments.length) {
            if ((animateur.alertes_paie || []).some((item) => item.code === "contrat_implicite")) {
                return '<span class="paie-contract-segment paie-contract-segment--implicit"><span class="paie-cell-main">CEE par défaut</span><span class="paie-cell-detail">Contrat non renseigné</span></span>';
            }
            const fallbackLabel = (animateur.type_contrat_libelle || "CEE")
                .replace("Apprentissage / alternance", "Apprentissage");
            return `<span class="paie-cell-main">${escapeHtml(fallbackLabel)}</span>`;
        }
        return segments.map((segment) => {
            if (!segment.explicite) {
                return '<span class="paie-contract-segment paie-contract-segment--implicit"><span class="paie-cell-main">CEE par défaut</span><span class="paie-cell-detail">Contrat non renseigné</span></span>';
            }
            const dateDebut = segment.contrat_date_debut || segment.date_debut;
            const dateFin = segment.contrat_date_fin || segment.date_fin;
            const dates = !segment.contrat_date_debut && !segment.contrat_date_fin
                ? "Dates non renseignées"
                : !segment.contrat_date_debut
                    ? `Jusqu’au ${formatContractDate(segment.contrat_date_fin)}`
                    : !segment.contrat_date_fin
                        ? `Depuis le ${formatContractDate(segment.contrat_date_debut)}`
                        : `${formatContractDate(dateDebut)} → ${formatContractDate(dateFin)}`;
            return `<span class="paie-contract-segment"><span class="paie-cell-main">${escapeHtml(segment.type_contrat_libelle || contractTypeLabel(segment.type_contrat))}</span><span class="paie-cell-detail">${escapeHtml(dates)}</span></span>`;
        }).join("");
    }

    function payrollCorrection(animateur) {
        const employeeUrl = recapRoot?.dataset.employeesUrl || "/employes/";
        const settingsUrl = recapRoot?.dataset.settingsUrl || "/parametres/";
        const corrections = {
            taux_contractuel_manquant: { label: "Taux contractuel manquant", section: "contrats" },
            salaire_mensuel_manquant: { label: "Salaire mensuel manquant", section: "contrats" },
            statut_manquant: { label: "Statut manquant", section: "historique-statut" },
            statut_incoherent: { label: "Historique du statut à corriger", section: "historique-statut" },
            bareme_manquant: { label: "Barème CEE manquant", settings: true },
            incoherence_contractuelle: { label: "Données contractuelles incohérentes", section: "contrats" },
        };
        const seen = new Set();
        const issues = (animateur.alertes_paie || [])
            .filter((item) => item.niveau === "incomplet")
            .filter((item) => !seen.has(item.code) && seen.add(item.code))
            .map((item) => ({
                ...item,
                ...(corrections[item.code] || { label: "Données à compléter", section: null }),
            }));
        const issue = issues[0] || { label: "Données à compléter", section: null };
        const href = issue.settings
            ? `${settingsUrl}#baremes-cee`
            : `${employeeUrl}?salarie=${encodeURIComponent(animateur.id)}${issue.section ? `#${issue.section}` : ""}`;
        return {
            href,
            label: issue.label || issue.message || "Données à compléter",
            autres: Math.max(0, issues.length - 1),
        };
    }

    function incompletePayrollCell(animateur) {
        const correction = payrollCorrection(animateur);
        return `<span class="paie-pay-block paie-pay-block--incomplete"><a class="paie-non-calculable" href="${escapeHtml(correction.href)}">Non calculable</a><span class="paie-cell-detail">${escapeHtml(correction.label)}</span>${correction.autres ? `<span class="paie-cell-detail">+ ${correction.autres} autre${correction.autres > 1 ? "s" : ""} anomalie${correction.autres > 1 ? "s" : ""}</span>` : ""}</span>`;
    }

    function payrollBaseCell(animateur) {
        if (animateur.etat_preparation === "incomplet") {
            return incompletePayrollCell(animateur);
        }
        const elements = [];
        if (animateur.paie_habituelle) {
            elements.push('<span class="paie-pay-block"><span class="paie-cell-main">Paie habituelle</span><span class="paie-cell-detail">Salaire de base hors calcul</span></span>');
        }
        if (animateur.base_preparee !== null && animateur.base_preparee !== undefined) {
            const label = animateur.base_mensuelle_reference !== null
                ? "Base mensuelle"
                : (animateur.reference_mensuelle_a_ajuster ? "Base CEE calculée" : "");
            elements.push(`<span class="paie-pay-block"><span class="paie-cell-main">${formatMoney(animateur.base_preparee)}</span>${label ? `<span class="paie-cell-detail">${label}</span>` : ""}</span>`);
        }
        if (animateur.reference_mensuelle_a_ajuster && animateur.salaire_mensuel_reference !== null) {
            elements.push(`<span class="paie-pay-block paie-pay-block--reference"><span class="paie-cell-main">${formatMoney(animateur.salaire_mensuel_reference)}</span><span class="paie-cell-detail">Référence mensuelle</span></span>`);
        }
        if (elements.length) return elements.filter(Boolean).join("");
        return incompletePayrollCell(animateur);
    }

    function displayCentres(data) {
        const centres = data.centres || [];
        displayLegend(centres);
        if (!data.animateurs.length) {
            centresRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour planifié</strong><span>Aucun animateur n’est affecté sur cette période.</span></div>';
            return;
        }

        const firstHeader = centres.map((centre) => `
            <th class="centre-heading" scope="col" title="${escapeHtml(centre.nom)}" style="--centre-color:${escapeHtml(centre.couleur || "#64748b")}">
                <span>${escapeHtml(centre.code || centre.nom)}</span><small>${escapeHtml(centre.nom)}</small>
            </th>`).join("");
        const secondHeader = centres.map(() => '<th class="metric-heading" scope="col">Jours</th>').join("");

        const rows = data.animateurs.map((animateur) => {
            const byCentre = new Map((animateur.centres || []).map((item) => [String(item.centre_id), item]));
            const cells = centres.map((centre) => {
                const result = byCentre.get(String(centre.id)) || { jours_travailles: 0 };
                const details = (result.details_cee || []).map((item) => `<span class="paie-cell-detail"><span>${escapeHtml(item.statut)}</span><span>${item.jours} × ${formatMoney(item.taux)} = ${formatMoney(item.montant)}</span></span>`).join("");
                return `<td class="days-value centre-value" data-label="${escapeHtml(centre.code || centre.nom)}"><span class="paie-mobile-content"><span class="paie-cell-main">${result.jours_travailles}</span>${details}</span></td>`;
            }).join("");
            const preparationClass = animateur.etat_preparation === "incomplet"
                ? "payroll-preparation-row--incomplete"
                : (animateur.etat_preparation === "a_verifier" ? "payroll-preparation-row--verification" : "");
            return `
                <tr class="payroll-preparation-row ${preparationClass}">
                    <th scope="row" class="employee-cell"><strong>${escapeHtml(animateur.prenom)}</strong> ${escapeHtml(animateur.nom)}</th>
                    ${cells}
                    <td class="money-value rate-column" data-label="Contrat"><span class="paie-mobile-content">${contractCell(animateur)}</span></td>
                    <td class="days-value complementary-column" data-label="Réunions"><span class="paie-mobile-content">${animateur.jours_reunion}</span></td>
                    <td class="days-value complementary-column" data-label="Préparation complémentaire"><span class="paie-mobile-content">${animateur.jours_preparation}</span></td>
                    <td class="days-value total-column" data-label="Jours travaillés"><span class="paie-mobile-content">${animateur.jours_travailles}</span></td>
                    <td class="money-value total-column pay-value" data-label="Paie"><span class="paie-mobile-content">${payrollBaseCell(animateur)}</span></td>
                </tr>`;
        }).join("");

        centresRoot.innerHTML = `
            <table class="recap-table recap-centres-table">
                <colgroup>
                    <col class="employee-col">
                    ${centres.map(() => '<col class="centre-col">').join("")}
                    <col class="rate-col">
                    <col class="compact-col"><col class="compact-col">
                    <col class="compact-col"><col class="pay-col">
                </colgroup>
                <thead>
                    <tr><th class="employee-cell employee-cell--header" rowspan="2" scope="col">Animateur</th>${firstHeader}<th class="total-heading rate-column" rowspan="2" scope="col">Contrat</th><th class="complementary-heading" colspan="2" scope="colgroup">Journées complémentaires</th><th class="total-heading" colspan="2" scope="colgroup">Préparation</th></tr>
                    <tr>${secondHeader}<th class="metric-heading complementary-column" scope="col" title="Réunions">Réun.</th><th class="metric-heading complementary-column" scope="col" title="Télétravail / préparation">Prépa.</th><th class="metric-heading total-column" scope="col" title="Total jours">Jours</th><th class="metric-heading total-column" scope="col" title="Paie totale">Paie</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function displayEmployees(data) {
        if (!data.animateurs.length) {
            employeesRoot.innerHTML = '<div class="empty-state"><strong>Aucun jour planifié</strong><span>Aucun animateur n’est affecté sur cette période.</span></div>';
            return;
        }
        const rows = data.animateurs.map((animateur) => `
            <tr data-total-animateur="${animateur.id}">
                <td><strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong><small>${escapeHtml(animateur.type_contrat_libelle || "CEE")}</small>${(animateur.alertes_paie || []).map((item) => `<span class="payroll-alert payroll-alert--${escapeHtml(item.niveau)}">${escapeHtml(item.message)}</span>`).join("")}</td>
                <td class="jours-cell">${animateur.jours_affectation}</td>
                <td class="jours-cell">${animateur.jours_reunion}</td>
                <td class="jours-cell">${animateur.jours_preparation}</td>
                <td class="jours-cell">${animateur.jours_travailles}</td>
                <td class="jours-cell">${formatMoney(animateur.base_cee) || "—"}</td>
                <td class="jours-cell">${formatMoney(animateur.indemnite_cp_cee) || "—"}</td>
                <td class="jours-cell">${formatMoney(animateur.salaire_mensuel_reference) || "—"}</td>
                <td class="jours-cell" data-total-primes-animateur>${formatMoney(animateur.montant_primes_preparees)}</td>
                <td class="jours-cell" data-total-prepare-animateur>${formatMoney(animateur.total_prepare) || escapeHtml(animateur.etat_preparation)}</td>
            </tr>`).join("");
        employeesRoot.innerHTML = `
            <table class="recap-table">
                <thead><tr><th>Animateur</th><th>Affectations</th><th>Réunions</th><th>Télétravail / préparation</th><th>Total jours</th><th>Base CEE</th><th>CP CEE</th><th>Salaire mensuel de référence</th><th>Primes</th><th>Total préparé</th></tr></thead>
                <tbody>${rows}</tbody>
                <tfoot><tr><th>Total</th><th></th><th></th><th></th><th class="jours-cell">${data.total_jours}</th><th></th><th></th><th></th><th class="jours-cell" data-total-all-primes>${formatMoney(data.total_primes_preparees)}</th><th class="jours-cell" data-total-all-prepare>${formatMoney(data.total_prepare)}</th></tr></tfoot>
            </table>`;
    }

    function updateScope() {
        const label = selectedRange?.label || "Aucune période sélectionnée";
        scopeRoot.innerHTML = `<strong>${escapeHtml(label)}</strong><span>Tous les types d’accueil sont agrégés.</span>`;
        savePrimesButton.textContent = "Valider les primes pour la période";
    }

    function updateDirtyActions() {
        const dirty = dirtyPrimes.size > 0;
        savePrimesButton.disabled = !dirty;
        cancelPrimesButton.disabled = !dirty;
    }

    function primeContextForForm(form) {
        const card = form.closest("[data-payroll-animateur]");
        const contexte = primeEligibility.get(Number(card.dataset.payrollAnimateur)) || {};
        const prime = (contexte.primes || []).find(
            (item) => Number(item.id) === Number(form.dataset.primeId)
        );
        return {card, prime};
    }

    function updateContextualPrimeForm(form) {
        const {prime} = primeContextForForm(form);
        if (!prime) return;
        updatePrimeEditorSummary(form.closest("details"), prime);
        const editingId = Number(form.dataset.editingAttributionId || 0);
        const joursOccupes = new Set((prime.attributions_couvertures || [])
            .filter((item) => Number(item.id) !== editingId)
            .flatMap((item) => item.jours || []));
        const joursDisponibles = (prime.jours_eligibles || []).filter((jour) => !joursOccupes.has(jour));
        const semaines = (prime.semaines_toutes_eligibles || prime.semaines_eligibles || []).map(
            (semaine) => ({
                ...semaine,
                jours_eligibles: (semaine.jours_eligibles || []).filter((jour) => joursDisponibles.includes(jour)),
            })
        ).filter((semaine) => semaine.jours_eligibles.length);
        prime.semaines_affichees = semaines;
        const niveau = form.querySelector("[data-prime-entry-level]")?.value
            || prime.niveaux_saisie?.[0] || "forfait";
        const amount = form.querySelector("[data-prime-amount]");
        const detail = form.querySelector("[data-prime-fixed]");
        amount.hidden = prime.type_montant === "fixe";
        detail.textContent = prime.type_montant === "fixe"
            ? `${formatMoney(prime.montant_fixe)} · ${prime.mode_libelle}`
            : `Maximum : ${formatMoney(prime.montant_maximum)}`;
        const selection = form.querySelector("[data-prime-selection]");
        if (prime.mode_calcul === "jour" && niveau === "jour") {
            const formatter = new Intl.DateTimeFormat("fr-FR", {weekday: "short", day: "2-digit", month: "2-digit", timeZone: "UTC"});
            selection.innerHTML = semaines.map((semaine) => `<div class="payroll-prime-day-group"><strong>${formatContractDate(semaine.date_debut)} → ${formatContractDate(semaine.date_fin)}</strong><div class="payroll-prime-days">${semaine.jours_eligibles.map((jour) => `<label><input type="checkbox" data-prime-day value="${jour}" checked> ${formatter.format(new Date(`${jour}T00:00:00Z`))}</label>`).join("")}</div></div>`).join("");
        } else if (["jour", "semaine"].includes(prime.mode_calcul) && niveau === "semaine") {
            selection.innerHTML = `<div class="payroll-prime-week-choices">${semaines.map((semaine, index) => `<label><input type="checkbox" data-prime-week-choice value="${index}" checked><span><strong>${formatContractDate(semaine.date_debut)} → ${formatContractDate(semaine.date_fin)}</strong><small>${semaine.jours_eligibles.length} j éligible${semaine.jours_eligibles.length > 1 ? "s" : ""}</small></span></label>`).join("")}</div>`;
        } else if (prime.mode_calcul === "jour") {
            const deja = prime.jours_eligibles.length - joursDisponibles.length;
            selection.innerHTML = `<span class="payroll-prime-period-summary"><strong>${prime.jours_eligibles.length} jours éligibles</strong>${deja ? `<small>${deja} jour${deja > 1 ? "s" : ""} déjà attribué${deja > 1 ? "s" : ""}</small>` : ""}<small>${joursDisponibles.length ? `${joursDisponibles.length} jour${joursDisponibles.length > 1 ? "s" : ""} restant${joursDisponibles.length > 1 ? "s" : ""} à attribuer` : "Aucun jour restant à attribuer"}</small>${prime.montant_fixe && joursDisponibles.length ? `<small>${joursDisponibles.length} × ${formatMoney(prime.montant_fixe)} = ${formatMoney(Number(prime.montant_fixe) * joursDisponibles.length)}</small>` : ""}</span>`;
        } else if (prime.mode_calcul === "semaine") {
            selection.innerHTML = `<span class="payroll-prime-period-summary"><strong>${semaines.length} semaine${semaines.length > 1 ? "s" : ""} éligible${semaines.length > 1 ? "s" : ""}</strong>${prime.estimation_fixe_periode ? `<small>${semaines.length} × ${formatMoney(prime.montant_fixe)} = ${formatMoney(prime.estimation_fixe_periode)}</small>` : ""}</span>`;
        } else {
            const segment = (editingId ? prime.segments_eligibles : prime.segments_disponibles)?.[0];
            selection.innerHTML = `<span class="payroll-prime-period-summary"><strong>${prime.mode_calcul === "mois" ? "Une attribution mensuelle" : "Une attribution forfaitaire"}</strong><small>${segment ? `Éligible du ${formatContractDate(segment.date_debut)} au ${formatContractDate(segment.date_fin)}` : ""}</small></span>`;
        }
        if (prime.conflits_existants) {
            selection.insertAdjacentHTML("beforeend", '<small class="payroll-prime-local-error">⚠ Attributions en doublon sur cette période</small>');
        }
        const addButton = form.querySelector("[data-add-attribution]");
        const disponible = prime.mode_calcul === "jour"
            ? joursDisponibles.length > 0
            : prime.mode_calcul === "semaine"
                ? semaines.length > 0
                : Boolean((editingId ? prime.segments_eligibles : prime.segments_disponibles)?.length);
        addButton.disabled = !disponible;
        addButton.hidden = !disponible && !editingId;
    }

    function deletionScopeLabel() {
        return selectedRange?.label || "la période sélectionnée";
    }

    function displayPayroll(data) {
        const animateursSaisie = data.animateurs.filter((animateur) => primeEligibility.has(Number(animateur.id)));
        const formHtml = (prime, animateur, attributions) => {
            const key = `${animateur.id}:${prime.id}`;
            const niveaux = prime.niveaux_saisie || [];
            const niveauHtml = niveaux.length > 1
                ? `<label class="payroll-prime-level">Niveau <select data-prime-entry-level>${niveaux.map((item) => `<option value="${item}">${item[0].toUpperCase()}${item.slice(1)}</option>`).join("")}</select></label>`
                : `<span class="payroll-prime-level-label">${prime.mode_calcul === "forfait" ? "Attribution ponctuelle" : "Niveau : Mois"}</span>`;
            const resume = primeSummaryValues(prime);
            return `<details class="payroll-prime-editor" data-prime-editor-key="${key}" ${openPrimeKeys.has(key) ? "open" : ""}>
                <summary><span class="payroll-prime-summary-main"><strong data-prime-summary-title>${escapeHtml(resume.titre)}</strong><span data-prime-summary-detail>(${escapeHtml(resume.detail)})</span></span><span class="payroll-prime-configure">Configurer</span></summary>
                <div class="payroll-prime-existing" data-prime-existing ${attributions.length ? "" : "hidden"}><strong>Déjà attribuée</strong><span data-prime-existing-list>${attributions.map(attributionPrimeHtml).join("")}</span></div>
                <div class="payroll-week-form" data-prime-form data-prime-id="${prime.id}">
                ${niveauHtml}<div data-prime-selection></div>
                <input type="number" min="0" step="0.01" data-prime-amount placeholder="Montant" ${prime.type_montant === "fixe" ? "hidden" : ""}>
                <span class="paie-cell-detail" data-prime-fixed></span>
                <button type="button" class="btn btn-primary btn-small" data-add-attribution>Attribuer</button>
                <span class="payroll-prime-local-error" data-prime-local-error hidden></span>
                </div></details>`;
        };
        const saisieHtml = animateursSaisie.length ? `<section class="payroll-prime-section"><h3>Primes à attribuer</h3><div class="payroll-weekly-list">${animateursSaisie.map((animateur) => {
            const contexte = primeEligibility.get(Number(animateur.id)) || {primes: []};
            const attributions = (animateur.attributions_primes || []).filter((item) => !item.historique);
            return `<article class="payroll-employee-card" data-payroll-animateur="${animateur.id}"><header><strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong></header><div class="payroll-prime-editors">${(contexte.primes || []).map((prime) => formHtml(prime, animateur, attributions.filter((item) => Number(item.type_prime_id) === Number(prime.id)))).join("")}</div></article>`;
        }).join("")}</div></section>` : '<div class="empty-state"><strong>Aucune nouvelle prime éligible sur cette période.</strong><span>Les critères dépendent des types de contrats, statuts et primes configurés.</span></div>';
        const historiques = data.animateurs.map((animateur) => {
            const idsEligibles = new Set((primeEligibility.get(Number(animateur.id))?.primes || []).map((item) => Number(item.id)));
            return {...animateur, attributions_primes: (animateur.attributions_primes || []).filter((item) => item.historique || !idsEligibles.has(Number(item.type_prime_id)))};
        }).filter((animateur) => animateur.attributions_primes.length);
        const historiqueHtml = historiques.length ? `<section class="payroll-prime-section payroll-prime-history-section"><h3>Historique des primes</h3><div class="payroll-weekly-list">${historiques.map((animateur) => `<article class="payroll-employee-card" data-payroll-animateur="${animateur.id}"><header><strong>${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</strong></header><div class="payroll-prime-list">${animateur.attributions_primes.map(attributionPrimeHtml).join("")}</div></article>`).join("")}</div></section>` : "";
        payrollRoot.innerHTML = `${saisieHtml}${historiqueHtml}`;
        payrollRoot.querySelectorAll("[data-prime-form]").forEach((form) => updateContextualPrimeForm(form));
    }

    function applyPrimeSynthesis(animateurId, synthese) {
        if (!synthese || !lastData) return;
        const animateur = lastData.animateurs.find((item) => Number(item.id) === Number(animateurId));
        if (!animateur) return;
        const anciennes = animateur.attributions_primes || [];
        const ancienTotal = Number(animateur.montant_primes_preparees || 0);
        const typePrimeId = Number(synthese.contexte_prime?.id || 0);
        const anciennesType = anciennes.filter(
            (item) => !item.historique && Number(item.type_prime_id) === typePrimeId
        );
        const nouvellesType = synthese.attributions.filter(
            (item) => Number(item.type_prime_id) === typePrimeId
        );
        const ancienTotalType = anciennesType.reduce(
            (total, item) => total + Number(item.montant_total || 0), 0
        );
        const nouveauTotalType = nouvellesType.reduce(
            (total, item) => total + Number(item.montant_total || 0), 0
        );
        const nouveauTotal = typePrimeId
            ? ancienTotal - ancienTotalType + nouveauTotalType
            : Number(synthese.montant_total || 0);
        const ecart = nouveauTotal - ancienTotal;
        animateur.attributions_primes = typePrimeId
            ? [...anciennes.filter(
                (item) => item.historique || Number(item.type_prime_id) !== typePrimeId
            ), ...nouvellesType]
            : [...synthese.attributions, ...anciennes.filter((item) => item.historique)];
        animateur.montant_primes_preparees = nouveauTotal.toFixed(2);
        if (animateur.total_prepare !== null && animateur.total_prepare !== undefined) {
            animateur.total_prepare = (Number(animateur.total_prepare) + ecart).toFixed(2);
        }
        lastData.total_primes_preparees = (Number(lastData.total_primes_preparees || 0) + ecart).toFixed(2);
        if (lastData.total_prepare !== null && lastData.total_prepare !== undefined) {
            lastData.total_prepare = (Number(lastData.total_prepare) + ecart).toFixed(2);
        }
        if (synthese.contexte_prime) {
            const contexteAnimateur = primeEligibility.get(Number(animateurId));
            const index = contexteAnimateur?.primes?.findIndex(
                (item) => Number(item.id) === Number(synthese.contexte_prime.id)
            );
            if (index >= 0) {
                // La réponse de mutation ne répète pas le contexte Planning/contrat
                // immuable : elle remplace uniquement attributions, couvertures et résumé.
                contexteAnimateur.primes[index] = {
                    ...contexteAnimateur.primes[index],
                    ...synthese.contexte_prime,
                };
            }
        }

        payrollRoot.querySelectorAll(`[data-payroll-animateur="${animateurId}"] [data-prime-form]`).forEach((form) => {
            if (typePrimeId && Number(form.dataset.primeId) !== typePrimeId) return;
            const attributions = nouvellesType.length || typePrimeId
                ? nouvellesType
                : synthese.attributions.filter(
                (item) => Number(item.type_prime_id) === Number(form.dataset.primeId)
            );
            const existing = form.closest("details").querySelector("[data-prime-existing]");
            existing.hidden = !attributions.length;
            existing.querySelector("[data-prime-existing-list]").innerHTML = attributions.map(attributionPrimeHtml).join("");
            updateContextualPrimeForm(form);
        });
        const totalRow = employeesRoot.querySelector(`[data-total-animateur="${animateurId}"]`);
        if (totalRow) {
            totalRow.querySelector("[data-total-primes-animateur]").textContent = formatMoney(animateur.montant_primes_preparees);
            totalRow.querySelector("[data-total-prepare-animateur]").textContent = formatMoney(animateur.total_prepare) || animateur.etat_preparation;
        }
        employeesRoot.querySelector("[data-total-all-primes]")?.replaceChildren(document.createTextNode(formatMoney(lastData.total_primes_preparees)));
        employeesRoot.querySelector("[data-total-all-prepare]")?.replaceChildren(document.createTextNode(formatMoney(lastData.total_prepare) || "—"));
        restoreQueuedDeletionStates();
    }

    function showPrimeLocalError(form, message = "") {
        const error = form?.querySelector("[data-prime-local-error]");
        if (!error) return;
        error.textContent = message;
        error.hidden = !message;
    }

    function setPrimeEditorBusy(editor, busy) {
        const form = editor?.querySelector("[data-prime-form]") || editor;
        form?.querySelectorAll("button, input, select").forEach((control) => {
            control.disabled = busy;
        });
        form?.setAttribute("aria-busy", busy ? "true" : "false");
    }

    function optimisticAttribution(editor, prime, bodies, editingAttributionId = null) {
        const unit = Number(bodies[0]?.montant || prime.montant_fixe || 0);
        const jours = [...new Set(bodies.flatMap((body) => body.jours || []))].sort();
        const quantite = prime.mode_calcul === "jour"
            ? jours.length : prime.mode_calcul === "semaine" ? bodies.length : 1;
        const total = unit * quantite;
        const debut = jours[0] || bodies[0]?.date_debut;
        const fin = jours[jours.length - 1] || bodies[bodies.length - 1]?.date_fin;
        const libelle = `${escapeHtml(prime.nom)} · <strong>${formatMoney(total)}</strong>`;
        const periode = debut && fin
            ? `<small>${formatContractDate(debut)} → ${formatContractDate(fin)} · ${editingAttributionId ? "Mise à jour…" : "Enregistrement…"}</small>`
            : `<small>${editingAttributionId ? "Mise à jour…" : "Enregistrement…"}</small>`;
        if (editingAttributionId) {
            const item = editor.querySelector(`[data-attribution-item="${editingAttributionId}"]`);
            if (!item) return null;
            const previous = item.innerHTML;
            item.classList.add("is-pending-mutation");
            item.innerHTML = `${libelle}${periode}`;
            return {rollback: () => { item.innerHTML = previous; item.classList.remove("is-pending-mutation"); }};
        }
        const container = editor.querySelector("[data-prime-existing]");
        const list = container?.querySelector("[data-prime-existing-list]");
        if (!list) return null;
        container.hidden = false;
        const item = document.createElement("span");
        item.className = "payroll-attribution is-pending-mutation";
        item.dataset.optimisticAttribution = "";
        item.innerHTML = `${libelle}${periode}`;
        list.appendChild(item);
        return {rollback: () => { item.remove(); container.hidden = !list.children.length; }};
    }

    function attributionButton(attributionId) {
        return payrollRoot.querySelector(`[data-delete-attribution="${attributionId}"]`);
    }

    function setDeletionMutationState(entry, label) {
        const button = attributionButton(entry.attributionId) || entry.button;
        const item = button?.closest("[data-attribution-item]") || entry.item;
        if (button) {
            button.disabled = true;
            button.textContent = label;
            button.setAttribute("aria-label", `${label} ${entry.attributionLabel}`);
        }
        item?.setAttribute("aria-busy", "true");
        item?.classList.add("is-pending-mutation");
    }

    function restoreQueuedDeletionStates() {
        primeMutationQueues.forEach((queue) => {
            queue.current?.setState?.("running");
            queue.items.forEach((entry) => entry.setState?.("waiting"));
        });
    }

    function showAttributionMutationError(entry, message) {
        const item = payrollRoot.querySelector(`[data-attribution-item="${entry.attributionId}"]`) || entry.item;
        if (!item) return;
        item.removeAttribute("aria-busy");
        item.classList.remove("is-pending-mutation");
        let error = item.querySelector("[data-attribution-mutation-error]");
        if (!error) {
            error = document.createElement("small");
            error.dataset.attributionMutationError = "";
            error.className = "payroll-prime-local-error";
            error.setAttribute("role", "alert");
            item.appendChild(error);
        }
        error.textContent = message;
        const button = item.querySelector("[data-delete-attribution]");
        if (button) {
            button.disabled = false;
            button.textContent = "Supprimer";
            button.removeAttribute("aria-label");
        }
    }

    async function processPrimeMutationQueue(key) {
        const queue = primeMutationQueues.get(key);
        if (!queue || queue.current) return;
        while (queue.items.length) {
            const entry = queue.items.shift();
            queue.current = entry;
            entry.setState?.("running");
            try {
                const response = await entry.run();
                entry.onSuccess?.(response);
            } catch (error) {
                entry.onError?.(error);
            } finally {
                queuedPrimeMutations.delete(entry.token);
                queue.current = null;
                entry.onFinally?.();
                restoreQueuedDeletionStates();
            }
        }
        primeMutationQueues.delete(key);
    }

    function enqueuePrimeMutation(entry) {
        if (queuedPrimeMutations.has(entry.token)) return;
        queuedPrimeMutations.add(entry.token);
        const queue = primeMutationQueues.get(entry.key) || {current: null, items: []};
        primeMutationQueues.set(entry.key, queue);
        queue.items.push(entry);
        entry.setState?.(queue.current ? "waiting" : "running");
        void processPrimeMutationQueue(entry.key);
    }

    function enqueuePrimeDeletion(entry) {
        enqueuePrimeMutation({
            ...entry,
            setState: (state) => setDeletionMutationState(
                entry, state === "waiting" ? "Suppression en attente…" : "Suppression…"
            ),
            run: () => apiFetch(`/api/recapitulatif/primes/${entry.attributionId}/?date_debut=${encodeURIComponent(selectedRange.start)}&date_fin=${encodeURIComponent(selectedRange.end)}`, {
                method: "DELETE",
                body: JSON.stringify({jours_eligibles: entry.joursEligibles}),
            }),
            onSuccess: (response) => {
                applyPrimeSynthesis(entry.animateurId, response.synthese);
                entry.item?.remove();
                if (entry.historyCard && !entry.historyCard.querySelector("[data-attribution-item]")) entry.historyCard.remove();
                afficherToast("La prime a été supprimée.");
            },
            onError: (error) => showAttributionMutationError(
                entry, erreurMessage(error, "La prime n'a pas pu être supprimée.")
            ),
        });
    }

    function openTab(tabName) {
        const selected = ["temps-travail", "paie", "centres", "totaux"].includes(tabName) ? tabName : "temps-travail";
        tabButtons.forEach((button) => {
            const active = button.dataset.recapTab === selected;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        tabPanels.forEach((panel) => {
            panel.hidden = panel.dataset.recapPanel !== selected;
        });
        const url = new URL(window.location.href);
        if (selected === "temps-travail") url.searchParams.delete("onglet");
        else url.searchParams.set("onglet", selected);
        window.history.replaceState({}, "", url);
    }

    async function loadRecap() {
        const url = buildApiUrl();
        if (!url) {
            const emptyMessage = '<div class="empty-state"><strong>Aucune période sélectionnée</strong><span>Choisissez un mois ou une plage de dates.</span></div>';
            centresRoot.innerHTML = emptyMessage;
            employeesRoot.innerHTML = emptyMessage;
            payrollRoot.innerHTML = emptyMessage;
            legendRoot.innerHTML = "";
            return;
        }
        centresRoot.innerHTML = '<div class="loading-note">Calcul des jours et de la paie par centre…</div>';
        employeesRoot.innerHTML = '<div class="loading-note">Calcul des totaux…</div>';
        payrollRoot.innerHTML = '<div class="loading-note">Préparation des montants…</div>';
        legendRoot.innerHTML = "";
        try {
            const [data, primesData] = await Promise.all([
                apiFetch(url),
                apiFetch(`/api/recapitulatif/primes/?date_debut=${encodeURIComponent(selectedRange.start)}&date_fin=${encodeURIComponent(selectedRange.end)}`),
            ]);
            primeCatalog = primesData.types_primes || [];
            // L'API renvoie le contexte hebdomadaire complet, pas une liste globale de primes.
            primeEligibility = new Map((primesData.animateurs || []).map((item) => [Number(item.id), item]));
            lastData = data;
            payrollPeriodIds = data.periode?.ids || [];
            displayCentres(data);
            displayEmployees(data);
            displayPayroll(data);
        } catch (error) {
            const message = erreurMessage(error, "La paie n’a pas pu être chargée.");
            centresRoot.innerHTML = `<div class="empty-state"><strong>Chargement impossible</strong><span>${escapeHtml(message)}</span></div>`;
            employeesRoot.innerHTML = "";
            payrollRoot.innerHTML = "";
            afficherToast(message, true);
        }
    }

    function formatIsoDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    function isValidIsoDate(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return false;
        const date = new Date(`${value}T00:00:00Z`);
        return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
    }

    function persistedPayrollRange() {
        try {
            const range = JSON.parse(localStorage.getItem(PAYROLL_RANGE_STORAGE_KEY) || "null");
            if (!isValidIsoDate(range?.start) || !isValidIsoDate(range?.end) || range.end < range.start) {
                return null;
            }
            return range;
        } catch {
            return null;
        }
    }

    function persistPayrollRange(start, end) {
        if (!isValidIsoDate(start) || !isValidIsoDate(end) || end < start) return;
        try {
            localStorage.setItem(PAYROLL_RANGE_STORAGE_KEY, JSON.stringify({start, end}));
        } catch {
            // La page Paie reste utilisable lorsque le stockage local est désactivé.
        }
    }

    function formatRangeLabel(start, end) {
        const formatter = new Intl.DateTimeFormat("fr-FR", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"});
        return `Du ${formatter.format(new Date(`${start}T00:00:00Z`))} au ${formatter.format(new Date(`${end}T00:00:00Z`))} inclus`;
    }

    function selectRange(start, end) {
        if (dirtyPrimes.size && !window.confirm("Des primes modifiées ne sont pas enregistrées. Abandonner ces modifications ?")) {
            return false;
        }
        if (!start || !end || end < start) {
            periodError.textContent = "La date de fin ne peut pas être antérieure à la date de début.";
            periodError.hidden = false;
            return false;
        }
        periodError.hidden = true;
        dirtyPrimes.clear();
        updateDirtyActions();
        payrollPeriodIds = [];
        selectedRange = {start, end, label: formatRangeLabel(start, end)};
        persistPayrollRange(start, end);
        updateScope();
        if (pdfButton) pdfButton.disabled = false;
        if (excelButton) excelButton.disabled = false;
        loadRecap();
        return true;
    }

    tabButtons.forEach((button) => button.addEventListener("click", () => openTab(button.dataset.recapTab)));
    payrollRoot.addEventListener("input", (event) => {
        const input = event.target.closest("[data-payroll-prime]");
        if (!input) return;
        const row = input.closest("[data-payroll-animateur]");
        const id = Number(row.dataset.payrollAnimateur);
        if (input.value.trim() === input.dataset.previousValue) dirtyPrimes.delete(id);
        else dirtyPrimes.set(id, input.value);
        row.classList.toggle("is-dirty", dirtyPrimes.has(id));
        row.querySelector("[data-cancel-prime]").disabled = !dirtyPrimes.has(id);
        updateDirtyActions();
    });
    payrollRoot.addEventListener("change", (event) => {
        const select = event.target.closest("[data-prime-entry-level]");
        if (!select) return;
        updateContextualPrimeForm(select.closest("[data-prime-form]"));
    });
    payrollRoot.addEventListener("toggle", (event) => {
        const editor = event.target.closest("[data-prime-editor-key]");
        if (!editor) return;
        if (editor.open) openPrimeKeys.add(editor.dataset.primeEditorKey);
        else openPrimeKeys.delete(editor.dataset.primeEditorKey);
    }, true);
    payrollRoot.addEventListener("click", async (event) => {
        const row = event.target.closest("[data-payroll-animateur]");
        if (!row) return;
        const id = Number(row.dataset.payrollAnimateur);
        const deleteAttribution = event.target.closest("[data-delete-attribution]");
        if (deleteAttribution) {
            if (!window.confirm("Supprimer cette attribution de prime ?")) return;
            const attributionId = Number(deleteAttribution.dataset.deleteAttribution);
            const attribution = (lastData?.animateurs || []).flatMap(
                (item) => item.attributions_primes || []
            ).find((item) => Number(item.id) === attributionId);
            if (!attribution) return;
            const item = deleteAttribution.closest("[data-attribution-item]");
            const historyCard = item?.closest(".payroll-prime-history-section .payroll-employee-card");
            const typePrimeId = Number(attribution.type_prime_id);
            enqueuePrimeDeletion({
                key: `${id}:${typePrimeId}`,
                token: `delete:${attributionId}`,
                animateurId: id,
                typePrimeId,
                attributionId,
                attributionLabel: `${attribution.type_prime_nom || attribution.nom || "prime"} ${attribution.date_debut}–${attribution.date_fin}`,
                button: deleteAttribution,
                item,
                historyCard,
                joursEligibles: (primeEligibility.get(id)?.primes || []).find(
                    (prime) => Number(prime.id) === typePrimeId
                )?.jours_eligibles || [],
            });
            return;
        }
        const editAttribution = event.target.closest("[data-edit-attribution]");
        if (editAttribution) {
            const attribution = (lastData.animateurs || []).flatMap((item) => item.attributions_primes || [])
                .find((item) => String(item.id) === editAttribution.dataset.editAttribution);
            if (!attribution) return;
            const form = [...payrollRoot.querySelectorAll(`[data-payroll-animateur="${id}"] [data-prime-form]`)].find(
                (candidate) => Number(candidate.dataset.primeId) === Number(attribution.type_prime_id)
            );
            if (!form) {
                afficherToast("Cette attribution reste historique ; aucune nouvelle prime n’est actuellement éligible.");
                return;
            }
            form.dataset.editingAttributionId = attribution.id;
            form.closest("details").open = true;
            const niveau = form.querySelector("[data-prime-entry-level]");
            if (niveau && attribution.mode === "jour") niveau.value = "jour";
            if (niveau && attribution.mode === "semaine") niveau.value = "semaine";
            updateContextualPrimeForm(form);
            form.querySelector("[data-prime-amount]").value = attribution.montant_unitaire;
            form.querySelectorAll("[data-prime-day]").forEach((input) => { input.checked = input.value >= attribution.date_debut && input.value <= attribution.date_fin; });
            form.querySelectorAll("[data-prime-week-choice]").forEach((input) => {
                const semaine = primeContextForForm(form).prime.semaines_eligibles[Number(input.value)];
                input.checked = semaine.date_debut <= attribution.date_fin && semaine.date_fin >= attribution.date_debut;
            });
            form.querySelector("[data-add-attribution]").textContent = "Enregistrer";
            return;
        }
        const addAttribution = event.target.closest("[data-add-attribution]");
        if (addAttribution) {
            if (addAttribution.disabled) return;
            const form = addAttribution.closest("[data-prime-form]");
            const editor = form.closest("details");
            setPrimeEditorBusy(editor, true);
            const {prime} = primeContextForForm(form);
            const niveau = form.querySelector("[data-prime-entry-level]")?.value
                || prime?.niveaux_saisie?.[0] || "forfait";
            const semaines = prime?.semaines_affichees || prime?.semaines_eligibles || [];
            const indicesSemaines = niveau === "semaine"
                ? [...form.querySelectorAll("[data-prime-week-choice]:checked")].map((input) => Number(input.value))
                : semaines.map((_, index) => index);
            const semainesSelectionnees = indicesSemaines.map((index) => semaines[index]).filter(Boolean);
            let jours = niveau === "jour"
                ? [...form.querySelectorAll("[data-prime-day]:checked")].map((input) => input.value)
                : semainesSelectionnees.flatMap((semaine) => semaine.jours_eligibles);
            if (prime?.mode_calcul === "jour" && !jours.length) {
                setPrimeEditorBusy(editor, false);
                afficherToast("Sélectionne au moins un jour concerné.", true); return;
            }
            if (prime?.mode_calcul === "semaine" && !semainesSelectionnees.length) {
                setPrimeEditorBusy(editor, false);
                afficherToast("Sélectionne au moins une semaine concernée.", true); return;
            }
            const baseBody = {
                animateur_id: id,
                type_prime_id: Number(prime.id),
                montant: form.querySelector("[data-prime-amount]").value || null,
                periode_debut: selectedRange.start,
                periode_fin: selectedRange.end,
                jours_eligibles: prime.jours_eligibles || [],
            };
            let bodies;
            if (prime.mode_calcul === "jour") {
                bodies = [{...baseBody, jours}];
            } else if (prime.mode_calcul === "semaine") {
                bodies = semainesSelectionnees.map((semaine) => ({
                    ...baseBody,
                    jours: semaine.jours_eligibles,
                    date_debut: semaine.jours_eligibles[0],
                    date_fin: semaine.jours_eligibles[semaine.jours_eligibles.length - 1],
                }));
            } else {
                const segment = (form.dataset.editingAttributionId
                    ? prime.segments_eligibles
                    : prime.segments_disponibles)?.[0];
                bodies = [{...baseBody, date_debut: segment?.date_debut, date_fin: segment?.date_fin}];
            }
            showPrimeLocalError(form);
            const editingAttributionId = form.dataset.editingAttributionId;
            if (editingAttributionId && bodies.length !== 1) {
                setPrimeEditorBusy(editor, false);
                afficherToast("Modifie une attribution à la fois.", true); return;
            }
            const originalLabel = addAttribution.textContent;
            const optimistic = optimisticAttribution(editor, prime, bodies, editingAttributionId);
            enqueuePrimeMutation({
                key: `${id}:${prime.id}`,
                token: `save:${id}:${prime.id}:${editingAttributionId || "new"}:${Date.now()}`,
                setState: (state) => {
                    addAttribution.textContent = state === "waiting"
                        ? "Enregistrement en attente…" : "Enregistrement…";
                    addAttribution.setAttribute("aria-label", addAttribution.textContent);
                },
                run: () => Promise.all(bodies.map((body) => apiFetch(
                    editingAttributionId ? `/api/recapitulatif/primes/${editingAttributionId}/` : "/api/recapitulatif/primes/",
                    {method: editingAttributionId ? "PATCH" : "POST", body: JSON.stringify(body)},
                ))),
                onSuccess: (responses) => {
                    delete form.dataset.editingAttributionId;
                    const synthese = responses.map((item) => item.synthese).filter(Boolean).sort(
                        (a, b) => b.attributions.length - a.attributions.length
                    )[0];
                    applyPrimeSynthesis(id, synthese);
                    addAttribution.textContent = "✓ Attribuée";
                    afficherToast("La prime a été enregistrée.");
                },
                onError: (error) => {
                    optimistic?.rollback();
                    showPrimeLocalError(form, erreurMessage(error, "La prime n'a pas pu être enregistrée."));
                },
                onFinally: () => {
                    setPrimeEditorBusy(editor, false);
                    if (addAttribution.isConnected) {
                        addAttribution.textContent = originalLabel;
                        addAttribution.removeAttribute("aria-label");
                        updateContextualPrimeForm(form);
                    }
                },
            });
            return;
        }
        if (event.target.closest("[data-cancel-prime]")) {
            const input = row.querySelector("[data-payroll-prime]");
            input.value = input.dataset.previousValue;
            dirtyPrimes.delete(id); row.classList.remove("is-dirty");
            event.target.disabled = true; updateDirtyActions(); return;
        }
        const deleteButton = event.target.closest("[data-delete-prime]");
        if (!deleteButton) return;
        const employee = row.querySelector(".payroll-employee").textContent.trim().replace(/\s+/g, " ");
        const scope = deletionScopeLabel();
        if (!window.confirm(`Supprimer la prime de ${employee} pour ${scope} ?`)) return;
        deleteButton.disabled = true;
        try {
            await apiFetch("/api/recapitulatif/prime-journaliere/", {method: "DELETE", body: JSON.stringify({animateur_id: id, periode_ids: payrollPeriodIds})});
            dirtyPrimes.delete(id); updateDirtyActions(); await loadRecap();
            afficherToast(`La prime de ${employee} a été supprimée pour la période sélectionnée.`);
        } catch (error) {
            deleteButton.disabled = false; afficherToast(erreurMessage(error, "La prime n'a pas pu être supprimée."), true);
        }
    });
    savePrimesButton?.addEventListener("click", async () => {
        const primes = [...dirtyPrimes.entries()].map(([animateur_id, montant]) => ({animateur_id, montant}));
        if (primes.some((item) => item.montant.trim() === "")) {
            afficherToast("Un champ vidé n'efface aucune prime : saisissez explicitement 0 € pour la supprimer.", true); return;
        }
        savePrimesButton.disabled = true;
        try {
            await apiFetch("/api/recapitulatif/prime-journaliere/", {
                method: "PUT",
                body: JSON.stringify({
                    periode_ids: payrollPeriodIds,
                    primes,
                }),
            });
            dirtyPrimes.clear(); updateDirtyActions(); await loadRecap();
            afficherToast("Les primes ont été enregistrées pour la période sélectionnée.");
        } catch (error) {
            afficherToast(erreurMessage(error, "Les primes n'ont pas pu être enregistrées."), true); updateDirtyActions();
        }
    });
    cancelPrimesButton?.addEventListener("click", () => { dirtyPrimes.clear(); updateDirtyActions(); if (lastData) displayPayroll(lastData); });
    pdfButton?.addEventListener("click", () => {
        const url = buildApiUrl("/recapitulatif/export-paie.pdf");
        if (url) window.location.assign(url);
    });
    excelButton?.addEventListener("click", () => {
        const url = buildApiUrl("/recapitulatif/export.xlsx");
        if (url) window.location.assign(url);
    });
    refreshButton?.addEventListener("click", () => selectRange(startInput.value, endInput.value));
    [startInput, endInput].forEach((input) => input.addEventListener("change", () => {
        persistPayrollRange(startInput.value, endInput.value);
    }));

    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    const lastDay = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    const persistedRange = persistedPayrollRange();
    startInput.value = persistedRange?.start || formatIsoDate(firstDay);
    endInput.value = persistedRange?.end || formatIsoDate(lastDay);
    selectRange(startInput.value, endInput.value);
    openTab(new URLSearchParams(window.location.search).get("onglet") || "temps-travail");
});
