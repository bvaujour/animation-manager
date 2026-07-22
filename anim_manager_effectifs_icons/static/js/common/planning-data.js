(function () {
    "use strict";

    const eventsCache = new Map();
    const effectifsCache = new Map();

    function normaliseDate(value) {
        if (value instanceof Date) return formatDateLocal(value);
        return String(value || "").slice(0, 10);
    }

    function cacheKey(start, end) {
        return `${normaliseDate(start)}|${normaliseDate(end)}`;
    }

    function fetchCentresWithGroups() {
        return apiFetch("/api/centres/?include_groupes=1");
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
        weekRange,
    };
})();
