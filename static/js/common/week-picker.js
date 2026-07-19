(function () {
    "use strict";

    const instances = new WeakMap();

    function localIsoDate(date = new Date()) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    function formatDateFr(value) {
        if (!value) return "";
        const date = typeof parseLocalDate === "function"
            ? parseLocalDate(value)
            : new Date(`${value}T12:00:00`);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("fr-FR");
    }

    function periodLabel(period) {
        if (typeof libellePeriodeAvecDates === "function") return libellePeriodeAvecDates(period);
        return period?.libelle || period?.nom || period?.semaine || "Semaine";
    }

    function isCurrentPeriod(period, today = localIsoDate()) {
        const explicit = period?.est_actuelle === true
            || String(period?.est_actuelle).toLowerCase() === "true";
        return explicit || (
            String(period?.debut || "") <= today
            && today <= String(period?.fin || "")
        );
    }

    function closestPeriod(periods, referenceDate = "") {
        if (referenceDate) {
            const active = periods.find((period) => (
                String(period?.debut || "") <= referenceDate
                && referenceDate <= String(period?.fin || "")
            ));
            if (active) return active;
        }

        const today = localIsoDate();
        const current = periods.find((period) => isCurrentPeriod(period, today));
        if (current) return current;
        return periods.find((period) => String(period?.debut || "") > today)
            || periods.at(-1)
            || null;
    }

    function vacationLabel(period) {
        const explicit = String(period?.vacances || period?.vacance || "").trim();
        if (explicit) return explicit;

        const name = String(period?.nom || period?.libelle || "").trim();
        const nameMatch = name.match(/^(.*?)\s+(?:—|-)\s+Semaine\b/i);
        if (nameMatch?.[1]) return nameMatch[1].trim();

        const source = String(period?.description_source || "").trim();
        return source
            .replace(/^vacances(?: scolaires)?\s+(?:de la|de l[’']|du|des|d[’'])\s*/i, "")
            .trim() || "Autres périodes";
    }

    function weekLabel(period) {
        const explicit = String(period?.semaine || "").trim();
        if (explicit) return explicit;

        const name = String(period?.nom || period?.libelle || "").trim();
        const nameMatch = name.match(/(?:—|-)\s*(Semaine\b.*)$/i);
        return nameMatch?.[1]?.trim() || name || "Semaine";
    }

    function groupPeriods(periods) {
        const years = new Map();
        periods.forEach((period) => {
            const year = period.annee_scolaire
                || String(period.debut || "").slice(0, 4)
                || "Année non définie";
            const vacation = vacationLabel(period);
            if (!years.has(year)) years.set(year, new Map());
            if (!years.get(year).has(vacation)) years.get(year).set(vacation, []);
            years.get(year).get(vacation).push(period);
        });

        return [...years.entries()]
            .sort(([a], [b]) => String(b).localeCompare(String(a), "fr"))
            .map(([year, vacations]) => ({
                year,
                vacations: [...vacations.entries()]
                    .sort(([, a], [, b]) => String(a[0]?.debut || "").localeCompare(String(b[0]?.debut || "")))
                    .map(([name, items]) => ({
                        name,
                        periods: [...items].sort((a, b) => String(a.debut || "").localeCompare(String(b.debut || ""))),
                    })),
            }));
    }

    class WeekPicker {
        constructor(root, options = {}) {
            this.root = root;
            this.mode = options.mode || root.dataset.weekPickerMode || "multiple";
            this.placeholder = options.placeholder
                || root.dataset.weekPickerPlaceholder
                || (this.mode === "single" ? "Choisir une semaine" : "Choisir des semaines");
            this.toggle = root.querySelector(".week-picker__toggle");
            this.label = root.querySelector(".week-picker__label");
            this.menu = root.querySelector(".week-picker__menu");
            this.tree = root.querySelector(".week-picker__tree");
            this.clearButton = root.querySelector("[data-week-picker-clear]");
            this.selectAllButton = root.querySelector("[data-week-picker-select-all]");
            this.periods = [];
            this.selectedIds = new Set();
            this.activeDate = String(options.activeDate || root.dataset.weekPickerActiveDate || "").slice(0, 10);
            this.ready = false;
            this.defaultCurrent = options.defaultCurrent ?? root.dataset.weekPickerDefaultCurrent !== "false";

            const initialIds = options.selectedIds ?? String(root.dataset.weekPickerSelected || "")
                .split(",")
                .map((value) => Number(value.trim()))
                .filter(Number.isFinite);
            initialIds.forEach((id) => this.selectedIds.add(Number(id)));

            this.bind();
            if (options.periods) this.setPeriods(options.periods, { emitReady: true });
            else this.load();
        }

        bind() {
            this.toggle?.addEventListener("click", () => {
                if (this.menu?.hidden) this.open();
                else this.close();
            });
            this.clearButton?.addEventListener("click", () => this.clear());
            this.selectAllButton?.addEventListener("click", () => this.selectAll());
        }

        async load() {
            if (!this.tree) return;
            try {
                const periods = await apiFetch("/api/periodes-scolaires/");
                this.setPeriods(periods, { emitReady: true });
            } catch (error) {
                this.tree.innerHTML = '<p class="empty-note">Les semaines n’ont pas pu être chargées.</p>';
                this.root.dispatchEvent(new CustomEvent("week-picker:error", {
                    bubbles: true,
                    detail: { error, picker: this },
                }));
            }
        }

        setPeriods(periods, { emitReady = false } = {}) {
            this.periods = [...(periods || [])]
                .sort((a, b) => String(a.debut || "").localeCompare(String(b.debut || "")));
            const validIds = new Set(this.periods.map((period) => Number(period.id)));
            this.selectedIds = new Set(
                [...this.selectedIds].filter((id) => validIds.has(Number(id)))
            );
            if (this.mode === "multiple" && !this.ready && !this.selectedIds.size && this.defaultCurrent) {
                const current = this.periods.find((period) => isCurrentPeriod(period));
                if (current) this.selectedIds.add(Number(current.id));
            }
            this.render();
            this.updateLabel();
            this.ready = true;
            if (emitReady) {
                this.root.dispatchEvent(new CustomEvent("week-picker:ready", {
                    bubbles: true,
                    detail: { picker: this, periods: this.periods },
                }));
            }
        }

        render() {
            if (!this.tree) return;
            if (!this.periods.length) {
                this.tree.innerHTML = '<p class="empty-note">Aucune semaine enregistrée.</p>';
                return;
            }

            const reference = closestPeriod(this.periods, this.activeDate);
            const groups = groupPeriods(this.periods);
            this.tree.innerHTML = "";

            groups.forEach((yearGroup, yearIndex) => {
                const yearDetails = document.createElement("details");
                yearDetails.className = "week-picker__year";
                const referenceYear = reference && String(
                    reference.annee_scolaire
                    || String(reference.debut || "").slice(0, 4)
                    || "Année non définie"
                ) === String(yearGroup.year);
                yearDetails.open = reference ? referenceYear : yearIndex === 0;

                const yearSummary = document.createElement("summary");
                yearSummary.textContent = yearGroup.year;
                yearDetails.appendChild(yearSummary);

                yearGroup.vacations.forEach((vacationGroup, vacationIndex) => {
                    const vacationDetails = document.createElement("details");
                    vacationDetails.className = "week-picker__vacation";
                    const containsReference = reference && vacationGroup.periods.some(
                        (period) => Number(period.id) === Number(reference.id)
                    );
                    vacationDetails.open = reference
                        ? Boolean(containsReference)
                        : yearIndex === 0 && vacationIndex === 0;

                    const vacationSummary = document.createElement("summary");
                    const vacationName = document.createElement("span");
                    vacationName.textContent = vacationGroup.name;
                    vacationSummary.appendChild(vacationName);
                    if (this.mode === "multiple") {
                        vacationSummary.appendChild(this.createVacationSelector(vacationGroup));
                    }
                    vacationDetails.appendChild(vacationSummary);
                    vacationGroup.periods.forEach((period) => {
                        vacationDetails.appendChild(this.createOption(period));
                    });
                    yearDetails.appendChild(vacationDetails);
                });
                this.tree.appendChild(yearDetails);
            });
        }


        createVacationSelector(vacationGroup) {
            const wrapper = document.createElement("label");
            wrapper.className = "week-picker__vacation-select";
            wrapper.title = `Sélectionner toutes les semaines de ${vacationGroup.name}`;
            wrapper.addEventListener("click", (event) => event.stopPropagation());

            const input = document.createElement("input");
            input.type = "checkbox";
            const ids = vacationGroup.periods.map((period) => Number(period.id));
            const selectedCount = ids.filter((id) => this.selectedIds.has(id)).length;
            input.checked = selectedCount === ids.length && ids.length > 0;
            input.indeterminate = selectedCount > 0 && selectedCount < ids.length;
            input.setAttribute("aria-label", `Sélectionner toutes les semaines de ${vacationGroup.name}`);
            input.addEventListener("click", (event) => event.stopPropagation());
            input.addEventListener("change", () => {
                ids.forEach((id) => {
                    if (input.checked) this.selectedIds.add(id);
                    else this.selectedIds.delete(id);
                });
                this.syncSelectionControls();
                this.updateLabel();
                this.emitChange();
            });

            const text = document.createElement("span");
            text.textContent = "Toute la période";
            wrapper.append(input, text);
            return wrapper;
        }

        createOption(period) {
            const option = document.createElement(this.mode === "single" ? "button" : "label");
            option.className = "week-picker__option";
            option.dataset.periodId = String(period.id);
            option.dataset.weekDate = String(period.debut || "");
            if (this.mode === "single") option.type = "button";
            if (isCurrentPeriod(period)) option.classList.add("is-current");
            if (this.periodContainsDate(period, this.activeDate)) option.classList.add("is-active");

            if (this.mode === "multiple") {
                const input = document.createElement("input");
                input.type = "checkbox";
                input.value = String(period.id);
                input.dataset.periodeId = String(period.id);
                input.checked = this.selectedIds.has(Number(period.id));
                input.addEventListener("change", () => {
                    if (input.checked) this.selectedIds.add(Number(period.id));
                    else this.selectedIds.delete(Number(period.id));
                    this.syncSelectionControls();
                    this.updateLabel();
                    this.emitChange();
                });
                option.appendChild(input);
            } else {
                option.addEventListener("click", () => {
                    this.activeDate = String(period.debut || "");
                    this.updateActiveOption();
                    if (this.label) this.label.textContent = periodLabel(period);
                    this.root.dispatchEvent(new CustomEvent("week-picker:select", {
                        bubbles: true,
                        detail: { date: period.debut, period, picker: this },
                    }));
                    this.close();
                });
            }

            const text = document.createElement("span");
            const strong = document.createElement("strong");
            strong.textContent = weekLabel(period);
            const small = document.createElement("small");
            small.textContent = `${formatDateFr(period.debut)} au ${formatDateFr(period.fin)}`;
            text.append(strong, small);
            option.appendChild(text);
            return option;
        }

        syncSelectionControls() {
            this.tree?.querySelectorAll(".week-picker__option input[data-periode-id]").forEach((input) => {
                input.checked = this.selectedIds.has(Number(input.dataset.periodeId));
            });
            this.tree?.querySelectorAll(".week-picker__vacation").forEach((details) => {
                const selector = details.querySelector(":scope > summary .week-picker__vacation-select input");
                if (!selector) return;
                const weekInputs = [...details.querySelectorAll(":scope > .week-picker__option input[data-periode-id]")];
                const selectedCount = weekInputs.filter((input) => this.selectedIds.has(Number(input.dataset.periodeId))).length;
                selector.checked = weekInputs.length > 0 && selectedCount === weekInputs.length;
                selector.indeterminate = selectedCount > 0 && selectedCount < weekInputs.length;
            });
        }

        periodContainsDate(period, date) {
            return Boolean(
                date
                && String(period?.debut || "") <= date
                && date <= String(period?.fin || "")
            );
        }

        updateActiveOption() {
            this.tree?.querySelectorAll(".week-picker__option").forEach((option) => {
                const period = this.periods.find(
                    (item) => String(item.id) === option.dataset.periodId
                );
                option.classList.toggle("is-active", this.periodContainsDate(period, this.activeDate));
            });
        }

        expandReferenceBranch() {
            const reference = closestPeriod(this.periods, this.activeDate);
            if (!reference || !this.tree) return;
            const option = [...this.tree.querySelectorAll("[data-period-id]")].find(
                (item) => item.dataset.periodId === String(reference.id)
            );
            let parent = option?.parentElement;
            while (parent && parent !== this.tree) {
                if (parent.tagName === "DETAILS") parent.open = true;
                parent = parent.parentElement;
            }
            option?.scrollIntoView({ block: "nearest" });
        }

        updateLabel() {
            if (!this.label || this.mode === "single") return;
            const selected = this.getSelectedPeriods();
            if (!selected.length) this.label.textContent = this.placeholder;
            else if (selected.length === 1) this.label.textContent = periodLabel(selected[0]);
            else this.label.textContent = `${selected.length} semaines sélectionnées`;
        }

        getSelectedIds() {
            return [...this.selectedIds].sort((a, b) => a - b);
        }

        getSelectedPeriods() {
            return this.periods.filter((period) => this.selectedIds.has(Number(period.id)));
        }

        setSelectedIds(ids, { emit = true } = {}) {
            const validIds = this.ready
                ? new Set(this.periods.map((period) => Number(period.id)))
                : null;
            this.selectedIds = new Set(
                (ids || [])
                    .map(Number)
                    .filter((id) => Number.isFinite(id) && (!validIds || validIds.has(id)))
            );
            this.render();
            this.updateLabel();
            if (emit) this.emitChange();
        }

        setActiveDate(date, { updateLabel = false } = {}) {
            this.activeDate = String(date || "").slice(0, 10);
            this.updateActiveOption();
            if (updateLabel) {
                const period = this.periods.find((item) => this.periodContainsDate(item, this.activeDate));
                if (period && this.label) this.label.textContent = periodLabel(period);
            }
        }

        clear() {
            this.setSelectedIds([]);
        }

        selectAll() {
            this.setSelectedIds(this.periods.map((period) => period.id));
        }

        emitChange() {
            this.root.dispatchEvent(new CustomEvent("week-picker:change", {
                bubbles: true,
                detail: {
                    ids: this.getSelectedIds(),
                    periods: this.getSelectedPeriods(),
                    picker: this,
                },
            }));
        }

        open() {
            document.querySelectorAll("[data-week-picker] .week-picker__menu:not([hidden])")
                .forEach((menu) => {
                    if (menu !== this.menu) instances.get(menu.closest("[data-week-picker]"))?.close();
                });
            if (this.menu) this.menu.hidden = false;
            this.toggle?.setAttribute("aria-expanded", "true");
            requestAnimationFrame(() => this.expandReferenceBranch());
        }

        close() {
            if (this.menu) this.menu.hidden = true;
            this.toggle?.setAttribute("aria-expanded", "false");
        }
    }

    function init(root, options = {}) {
        if (!root) return null;
        if (instances.has(root)) return instances.get(root);
        const picker = new WeekPicker(root, options);
        instances.set(root, picker);
        root.weekPicker = picker;
        return picker;
    }

    function get(rootOrId) {
        const root = typeof rootOrId === "string"
            ? document.getElementById(rootOrId)
            : rootOrId;
        return root ? instances.get(root) || root.weekPicker || null : null;
    }

    document.addEventListener("click", (event) => {
        document.querySelectorAll("[data-week-picker]").forEach((root) => {
            if (!root.contains(event.target)) get(root)?.close();
        });
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            document.querySelectorAll("[data-week-picker]").forEach((root) => get(root)?.close());
        }
    });
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-week-picker]").forEach((root) => init(root));
    });

    window.WeekPicker = {
        init,
        get,
        WeekPicker,
        isCurrentPeriod,
        vacationLabel,
        weekLabel,
        groupPeriods,
    };
})();
