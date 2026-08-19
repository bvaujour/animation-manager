(function () {
    "use strict";

    const eventsCache = new Map();
    const effectifsCache = new Map();
    const sortiesCache = new Map();

    function normaliseDate(value) {
        if (value instanceof Date) return formatDateLocal(value);
        return String(value || "").slice(0, 10);
    }

    function cacheKey(start, end) {
        return `${normaliseDate(start)}|${normaliseDate(end)}`;
    }

    function fetchCentresWithGroups(start = null, end = null) {
        const query = new URLSearchParams({ include_groupes: "1" });
        if (start) query.set("start", normaliseDate(start));
        if (end) query.set("end", normaliseDate(end));
        return apiFetch(`/api/centres/?${query.toString()}`);
    }

    function fetchWeekEvents(start, end, { force = false } = {}) {
        const key = cacheKey(start, end);
        if (force) eventsCache.delete(key);
        if (!eventsCache.has(key)) {
            const query = new URLSearchParams({ start: String(start), end: String(end) });
            const request = apiFetch(`/api/planning/?${query.toString()}`)
                .catch((error) => {
                    eventsCache.delete(key);
                    throw error;
                });
            eventsCache.set(key, request);
        }
        return eventsCache.get(key);
    }

    function invalidateWeekEvents(start = null, end = null) {
        if (start && end) eventsCache.delete(cacheKey(start, end));
        else eventsCache.clear();
    }

    function fetchWeekEffectifs(start, end, { force = false } = {}) {
        const debut = normaliseDate(start);
        const fin = normaliseDate(end);
        const key = cacheKey(debut, fin);
        if (force) effectifsCache.delete(key);
        if (!effectifsCache.has(key)) {
            const query = new URLSearchParams({ debut, fin });
            const request = apiFetch(`/api/effectifs-enfants/?${query.toString()}`, { cache: "no-store" })
                .catch((error) => {
                    effectifsCache.delete(key);
                    throw error;
                });
            effectifsCache.set(key, request);
        }
        return effectifsCache.get(key);
    }

    function invalidateWeekEffectifs(start = null, end = null) {
        if (start && end) effectifsCache.delete(cacheKey(normaliseDate(start), normaliseDate(end)));
        else effectifsCache.clear();
    }

    function fetchWeekSorties(start, end, { force = false } = {}) {
        const debut = normaliseDate(start);
        const fin = normaliseDate(end);
        const key = cacheKey(debut, fin);
        if (force) sortiesCache.delete(key);
        if (!sortiesCache.has(key)) {
            const query = new URLSearchParams({ start: debut, end: fin });
            const request = apiFetch(`/api/calendrier/sorties/?${query.toString()}`, { cache: "no-store" })
                .then((data) => data?.sorties || [])
                .catch((error) => {
                    sortiesCache.delete(key);
                    throw error;
                });
            sortiesCache.set(key, request);
        }
        return sortiesCache.get(key);
    }

    function applySortieMarkers(calendar, groupeId, start, end, options = {}) {
        if (!calendar?.el) return Promise.resolve();
        return fetchWeekSorties(start, end).then((sorties) => {
            calendar.el.querySelectorAll(".calendar-sortie-marker").forEach((marker) => marker.remove());
            calendar.el.querySelectorAll(".has-calendar-sortie").forEach((cell) => cell.classList.remove("has-calendar-sortie"));
            const pertinentes = (sorties || []).filter((sortie) =>
                (sortie.groupe_ids || []).map(Number).includes(Number(groupeId))
            );
            const parDate = pertinentes.reduce((acc, sortie) => {
                (acc[sortie.date] ||= []).push(sortie);
                return acc;
            }, {});
            Object.entries(parDate).forEach(([date, items]) => {
                const cell = calendar.el.querySelector(`.fc-daygrid-day[data-date="${date}"]`);
                if (!cell) return;
                const top = cell.querySelector(".fc-daygrid-day-top") || cell;
                const href = typeof options.markerHrefBuilder === "function"
                    ? options.markerHrefBuilder(items, date, groupeId)
                    : "";
                const marker = document.createElement(href ? "a" : "span");
                marker.className = "calendar-sortie-marker";
                marker.textContent = items.length > 1 ? `🚌 ${items.length}` : "🚌";
                marker.title = items.map((item) => `Sortie : ${item.nom}`).join("\n");
                marker.setAttribute("aria-label", marker.title);
                if (href) {
                    marker.href = href;
                    marker.classList.add("calendar-sortie-marker--link");
                }
                top.appendChild(marker);
                cell.classList.add("has-calendar-sortie");
            });
        }).catch(() => {
            // Le calendrier reste pleinement utilisable si les repères ne chargent pas.
        });
    }

    function hiddenDays(group) {
        const openDays = new Set((group?.jours_ouverts || [0, 1, 2, 3, 4, 5]).map(Number));
        return [0, 1, 2, 3, 4, 5, 6].filter((jsDay) => !openDays.has((jsDay + 6) % 7));
    }

    function weekRange(reference) {
        const date = typeof reference === "string"
            ? parseLocalDate(reference)
            : new Date(reference || new Date());
        const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
        const nextMonday = new Date(monday);
        nextMonday.setDate(nextMonday.getDate() + 7);
        return {
            debut: formatDateLocal(monday),
            fin: formatDateLocal(nextMonday),
        };
    }

    window.PlanningData = {
        fetchCentresWithGroups,
        fetchWeekEvents,
        invalidateWeekEvents,
        fetchWeekEffectifs,
        invalidateWeekEffectifs,
        fetchWeekSorties,
        applySortieMarkers,
        weekRange,
        hiddenDays,
    };
})();
