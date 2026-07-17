// ===========================================================================
// recapitulatif.js
// ---------------------------------------------------------------------------
// Tableau de bord de contrôle du planning : couverture des groupes,
// alertes métier et répartition des journées par salarié.
// ===========================================================================

document.addEventListener("DOMContentLoaded", () =>
{
    const selectRoot = document.getElementById("periode-select");
    const selectToggle = document.getElementById("periode-select-toggle");
    const selectLabel = document.getElementById("periode-select-label");
    const selectMenu = document.getElementById("periode-select-menu");
    const selectOptions = document.getElementById("periode-select-options");
    const btnToutSelectionner = document.getElementById("periodes-tout-selectionner");
    const btnToutDeselectionner = document.getElementById("periodes-tout-deselectionner");
    const btnAppliquer = document.getElementById("btn-appliquer-periode");
    const periodeAffichee = document.getElementById("periode-affichee");
    const syntheseRoot = document.getElementById("recap-synthese");
    const alertesRoot = document.getElementById("recap-alertes");
    const alertesCompteur = document.getElementById("alertes-compteur");
    const tableEvenements = document.getElementById("table-evenements");
    const tableSalaries = document.getElementById("table-recap");

    let periodes = [];
    const periodeIdsSelectionnees = new Set();
    const anneesPeriodesOuvertes = new Set();

    function formatDateFr(dateStr)
    {
        if (!dateStr) return "Non précisée";
        return parseLocalDate(dateStr).toLocaleDateString("fr-FR");
    }

    function libellePeriode(periode)
    {
        return `${libellePeriodeAvecAnnee(periode)} · ${formatDateFr(periode.debut)} au ${formatDateFr(periode.fin)}`;
    }

    function mettreAJourLibelleSelection()
    {
        const selection = periodes.filter((periode) => periodeIdsSelectionnees.has(periode.id));
        if (!selection.length)
        {
            selectLabel.textContent = "Choisir les périodes";
            periodeAffichee.textContent = "Aucune période sélectionnée";
            return;
        }

        selectLabel.textContent = selection.length === 1
            ? libellePeriodeAvecAnnee(selection[0])
            : `${selection.length} périodes sélectionnées`;
        periodeAffichee.textContent = selection.length === 1
            ? `${formatDateFr(selection[0].debut)} au ${formatDateFr(selection[0].fin)}`
            : selection.map((periode) => libellePeriodeAvecAnnee(periode)).join(" · ");
    }

    function rendreOptionsPeriodes()
    {
        if (!anneesPeriodesOuvertes.size)
        {
            const premiereSelectionnee = periodes.find((periode) => periodeIdsSelectionnees.has(periode.id));
            anneesPeriodesOuvertes.add(premiereSelectionnee?.annee_scolaire || anneePeriodesADeplier(periodes));
        }

        selectOptions.innerHTML = grouperPeriodesParAnnee(periodes).map(({ annee, periodes: elements }) =>
        {
            const zones = new Map();
            elements.forEach((periode) =>
            {
                const zone = String(periode.zone || "Sans zone");
                if (!zones.has(zone)) zones.set(zone, []);
                zones.get(zone).push(periode);
            });
            const nbSelectionnees = elements.filter((periode) => periodeIdsSelectionnees.has(periode.id)).length;

            return `
                <details class="periode-option-group period-year-accordion" data-period-year="${escapeHtml(annee)}" ${anneesPeriodesOuvertes.has(annee) ? "open" : ""}>
                    <summary>
                        <span class="period-year-summary"><strong>${escapeHtml(annee)}</strong><small>${nbSelectionnees}/${elements.length} sélectionnée${nbSelectionnees > 1 ? "s" : ""}</small></span>
                        <span class="period-year-chevron" aria-hidden="true">⌄</span>
                    </summary>
                    <div class="period-year-content">
                        ${[...zones.entries()].map(([zone, periodesZone]) => `
                            <section class="period-zone-block">
                                <p class="period-zone-title">Zone ${escapeHtml(zone)}</p>
                                <div class="period-year-list">
                                    ${periodesZone.map((periode) => `
                                        <label class="periode-option">
                                            <input type="checkbox" value="${periode.id}" ${periodeIdsSelectionnees.has(periode.id) ? "checked" : ""}>
                                            <span>
                                                <strong>${escapeHtml(libellePeriodeAvecAnnee(periode))}</strong>
                                                <small>${escapeHtml(formatDateFr(periode.debut))} au ${escapeHtml(formatDateFr(periode.fin))}</small>
                                            </span>
                                        </label>
                                    `).join("")}
                                </div>
                            </section>
                        `).join("")}
                    </div>
                </details>
            `;
        }).join("");

        selectOptions.querySelectorAll(".periode-option-group").forEach((details) =>
        {
            details.addEventListener("toggle", () =>
            {
                const annee = details.dataset.periodYear;
                if (details.open) anneesPeriodesOuvertes.add(annee);
                else anneesPeriodesOuvertes.delete(annee);
            });
        });

        selectOptions.querySelectorAll('input[type="checkbox"]').forEach((checkbox) =>
        {
            checkbox.addEventListener("change", () =>
            {
                const id = Number(checkbox.value);
                if (checkbox.checked) periodeIdsSelectionnees.add(id);
                else periodeIdsSelectionnees.delete(id);
                mettreAJourLibelleSelection();

                const details = checkbox.closest(".periode-option-group");
                const compteur = details?.querySelector(".period-year-summary small");
                if (details && compteur)
                {
                    const cases = [...details.querySelectorAll('input[type="checkbox"]')];
                    const nb = cases.filter((input) => input.checked).length;
                    compteur.textContent = `${nb}/${cases.length} sélectionnée${nb > 1 ? "s" : ""}`;
                }
            });
        });
    }

    function choisirPeriodeParDefaut()
    {
        const aujourdHui = formatDateLocal(new Date());
        const courante = periodes.find((periode) => periode.debut <= aujourdHui && periode.fin >= aujourdHui);
        const prochaine = periodes.find((periode) => periode.debut > aujourdHui);
        const choix = courante || prochaine || periodes[periodes.length - 1];
        if (choix) periodeIdsSelectionnees.add(choix.id);
    }

    function construireUrlApi()
    {
        if (!periodeIdsSelectionnees.size)
        {
            afficherToast("Sélectionne au moins une période.", true);
            return null;
        }
        const params = new URLSearchParams({
            periode_ids: [...periodeIdsSelectionnees].sort((a, b) => a - b).join(","),
        });
        return `/api/recapitulatif/?${params.toString()}`;
    }

    function carteIndicateur(label, valeur, precision, ton = "neutre")
    {
        return `
            <article class="indicator-card indicator-${escapeHtml(ton)}">
                <span class="indicator-label">${escapeHtml(label)}</span>
                <strong class="indicator-value">${escapeHtml(valeur)}</strong>
                <span class="indicator-detail">${escapeHtml(precision)}</span>
            </article>
        `;
    }

    function afficherSynthese(synthese)
    {
        const couvertureTon = synthese.postes_manquants > 0 ? "danger" : "ok";
        const qualificationTon = synthese.qualifications_manquantes > 0 ? "danger" : "ok";
        const disponibiliteTon = synthese.disponibles_sans_affectation > 0 ? "info" : "neutre";

        syntheseRoot.innerHTML = [
            carteIndicateur(
                "Couverture globale",
                `${synthese.couverture}%`,
                `${synthese.postes_couverts} poste(s) couvert(s) sur ${synthese.postes_requis}`,
                couvertureTon,
            ),
            carteIndicateur(
                "Postes manquants",
                synthese.postes_manquants,
                `${synthese.journees_sous_tension} journée(s) / groupe sous tension`,
                synthese.postes_manquants > 0 ? "danger" : "ok",
            ),
            carteIndicateur(
                "Qualifications manquantes",
                synthese.qualifications_manquantes,
                "Minimums définis dans Gestion",
                qualificationTon,
            ),
            carteIndicateur(
                "Sureffectif",
                synthese.sureffectif,
                "Présences au-delà du besoin déclaré",
                synthese.sureffectif > 0 ? "warning" : "neutre",
            ),
            carteIndicateur(
                "Salariés mobilisés",
                `${synthese.animateurs_mobilises}/${synthese.animateurs_total}`,
                `Charge moyenne : ${synthese.charge_moyenne} jour(s)`,
                "neutre",
            ),
            carteIndicateur(
                "Disponibles sans affectation",
                synthese.disponibles_sans_affectation,
                `Charge constatée : de ${synthese.charge_min} à ${synthese.charge_max} jour(s)`,
                disponibiliteTon,
            ),
        ].join("");
    }

    function iconeAlerte(niveau)
    {
        if (niveau === "danger") return "!";
        if (niveau === "warning") return "⚠";
        return "i";
    }

    function afficherAlertes(alertes)
    {
        const alertesPrioritaires = alertes.filter((alerte) => alerte.niveau !== "info");
        alertesCompteur.textContent = alertes.length
            ? `${alertesPrioritaires.length} point(s) prioritaire(s) · ${alertes.length} élément(s) au total`
            : "Aucune alerte";

        if (!alertes.length)
        {
            alertesRoot.innerHTML = `
                <div class="alert-empty">
                    <span class="alert-icon">✓</span>
                    <div>
                        <strong>Aucun point de vigilance sur cette période</strong>
                        <p>Les effectifs et qualifications déclarés sont couverts.</p>
                    </div>
                </div>
            `;
            return;
        }

        alertesRoot.innerHTML = alertes.map((alerte) => `
            <article class="alert-item alert-${escapeHtml(alerte.niveau)}">
                <span class="alert-icon" aria-hidden="true">${escapeHtml(iconeAlerte(alerte.niveau))}</span>
                <div class="alert-content">
                    <div class="alert-title-row">
                        <strong>${escapeHtml(alerte.titre)}</strong>
                        <span class="alert-location">${escapeHtml(alerte.lieu)}</span>
                    </div>
                    <p>${escapeHtml(alerte.message)}</p>
                    <span class="alert-dates">${escapeHtml(alerte.dates)}</span>
                </div>
            </article>
        `).join("");
    }

    function periodeEvenement(evenement)
    {
        if (!evenement.debut && !evenement.fin) return "Toute la période";
        if (evenement.debut && evenement.fin)
        {
            return `${formatDateFr(evenement.debut)} → ${formatDateFr(evenement.fin)}`;
        }
        if (evenement.debut) return `À partir du ${formatDateFr(evenement.debut)}`;
        return `Jusqu’au ${formatDateFr(evenement.fin)}`;
    }

    function qualificationsEvenement(evenement)
    {
        if (!evenement.qualifications.length) return '<span class="muted-value">Aucune</span>';
        return evenement.qualifications.map((qualification) => `
            <span class="qualification-pill">${escapeHtml(qualification.minimum)} × ${escapeHtml(qualification.nom)}</span>
        `).join("");
    }

    function afficherEvenements(evenements)
    {
        const thead = tableEvenements.querySelector("thead");
        const tbody = tableEvenements.querySelector("tbody");

        thead.innerHTML = `
            <tr>
                <th>Lieu / groupe</th>
                <th>Période</th>
                <th>Besoin</th>
                <th>Journées complètes</th>
                <th>Couverture</th>
                <th>Manques</th>
                <th>Qualifications requises</th>
            </tr>
        `;

        if (!evenements.length)
        {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-note">Aucun groupe sur cette période.</td></tr>';
            return;
        }

        tbody.innerHTML = evenements.map((evenement) =>
        {
            const manques = [];
            if (evenement.postes_manquants > 0) manques.push(`${evenement.postes_manquants} poste(s)`);
            if (evenement.qualifications_manquantes > 0) manques.push(`${evenement.qualifications_manquantes} qualification(s)`);
            if (evenement.sureffectif > 0) manques.push(`${evenement.sureffectif} en trop`);

            return `
                <tr class="event-row event-${escapeHtml(evenement.statut)}">
                    <td class="event-name-cell">
                        <span class="centre-dot" style="--c:${escapeHtml(evenement.couleur)}"></span>
                        <span>
                            <strong>${escapeHtml(evenement.nom)}</strong>
                            <small>${escapeHtml(evenement.lieu)}${evenement.actif ? "" : " · inactif"}</small>
                        </span>
                    </td>
                    <td>${escapeHtml(periodeEvenement(evenement))}</td>
                    <td class="number-cell">${escapeHtml(evenement.effectif_cible)} / jour</td>
                    <td class="number-cell">${escapeHtml(evenement.jours_complets)} / ${escapeHtml(evenement.jours_prevus)}</td>
                    <td class="coverage-cell">
                        <div class="coverage-value"><strong>${escapeHtml(evenement.couverture)}%</strong><span>${escapeHtml(evenement.postes_couverts)} / ${escapeHtml(evenement.postes_requis)}</span></div>
                        <div class="coverage-track"><span style="width:${Math.min(100, Math.max(0, evenement.couverture))}%"></span></div>
                    </td>
                    <td>${manques.length ? `<span class="issues-value">${escapeHtml(manques.join(" · "))}</span>` : '<span class="ok-value">Complet</span>'}</td>
                    <td><div class="qualification-list">${qualificationsEvenement(evenement)}</div></td>
                </tr>
            `;
        }).join("");
    }

    function afficherSalaries(data)
    {
        const thead = tableSalaries.querySelector("thead");
        const tbody = tableSalaries.querySelector("tbody");

        thead.innerHTML = `
            <tr>
                <th class="animateur-header">Salarié</th>
                ${data.centres.map((centre) => `
                    <th
                        class="centre-header"
                        style="--centre-color:${escapeHtml(centre.couleur)}; --centre-bg:${ColorUtils.rgba(centre.couleur, 0.16)};"
                    >
                        <span class="centre-dot" style="--c:${escapeHtml(centre.couleur)}"></span>
                        <span>${escapeHtml(centre.code || centre.nom)}</span>
                    </th>
                `).join("")}
                <th class="total-header">Total</th>
                <th class="availability-header">Disponible</th>
                <th class="availability-header">Libre</th>
            </tr>
        `;

        if (data.animateurs.length === 0)
        {
            tbody.innerHTML = `<tr><td colspan="${data.centres.length + 4}" class="empty-note">Aucun salarié.</td></tr>`;
            return;
        }

        tbody.innerHTML = data.animateurs.map((animateur) =>
        {
            const cellulesCentres = animateur.centres.map((centreRecap, index) =>
            {
                const centre = data.centres[index];
                const classe = centreRecap.jours > 0 ? "jours-value has-days" : "jours-value";
                return `
                    <td
                        class="number-cell centre-cell"
                        style="--centre-color:${escapeHtml(centre.couleur)}; --centre-bg:${ColorUtils.rgba(centre.couleur, 0.08)};"
                    >
                        <span class="${classe}">${escapeHtml(centreRecap.jours)}</span>
                    </td>
                `;
            }).join("");

            const libreClasse = animateur.jours_libres > 0 ? "availability-value has-free-days" : "availability-value";
            return `
                <tr>
                    <td class="animateur-cell">${escapeHtml(animateur.prenom)} ${escapeHtml(animateur.nom)}</td>
                    ${cellulesCentres}
                    <td class="number-cell total-cell">${escapeHtml(animateur.total)}</td>
                    <td class="number-cell"><span class="availability-value">${escapeHtml(animateur.jours_disponibles)}</span></td>
                    <td class="number-cell"><span class="${libreClasse}">${escapeHtml(animateur.jours_libres)}</span></td>
                </tr>
            `;
        }).join("");
    }

    function afficherChargement()
    {
        syntheseRoot.innerHTML = '<div class="loading-note">Calcul du récapitulatif…</div>';
        alertesRoot.innerHTML = '<div class="loading-note">Analyse des alertes…</div>';
    }

    function afficherTableau(data)
    {
        afficherSynthese(data.synthese);
        afficherAlertes(data.alertes);
        afficherEvenements(data.evenements);
        afficherSalaries(data);
    }

    function chargerRecap()
    {
        const url = construireUrlApi();
        if (!url) return;

        afficherChargement();
        btnAppliquer.disabled = true;

        apiFetch(url)
            .then(afficherTableau)
            .catch((err) => afficherToast(erreurMessage(err, "Le récapitulatif n'a pas pu être chargé."), true))
            .finally(() => { btnAppliquer.disabled = false; });
    }

    function definirToutesLesPeriodes(selectionnees)
    {
        periodeIdsSelectionnees.clear();
        if (selectionnees) periodes.forEach((periode) => periodeIdsSelectionnees.add(periode.id));
        rendreOptionsPeriodes();
        mettreAJourLibelleSelection();
    }

    selectToggle.addEventListener("click", () =>
    {
        const ouvrir = selectMenu.hidden;
        selectMenu.hidden = !ouvrir;
        selectToggle.setAttribute("aria-expanded", String(ouvrir));
    });

    document.addEventListener("click", (event) =>
    {
        if (!selectRoot.contains(event.target))
        {
            selectMenu.hidden = true;
            selectToggle.setAttribute("aria-expanded", "false");
        }
    });

    btnToutSelectionner.addEventListener("click", () => definirToutesLesPeriodes(true));
    btnToutDeselectionner.addEventListener("click", () => definirToutesLesPeriodes(false));
    btnAppliquer.addEventListener("click", () =>
    {
        selectMenu.hidden = true;
        selectToggle.setAttribute("aria-expanded", "false");
        chargerRecap();
    });

    apiFetch("/api/periodes-scolaires/")
        .then((data) =>
        {
            periodes = [...data].sort((a, b) => a.debut.localeCompare(b.debut));
            choisirPeriodeParDefaut();
            rendreOptionsPeriodes();
            mettreAJourLibelleSelection();
            if (periodes.length) chargerRecap();
            else
            {
                selectLabel.textContent = "Aucune période enregistrée";
                btnAppliquer.disabled = true;
                afficherToast("Ajoute d'abord des périodes dans Gestion > Périodes.", true);
            }
        })
        .catch((err) => afficherToast(erreurMessage(err, "Les périodes n'ont pas pu être chargées."), true));

});
