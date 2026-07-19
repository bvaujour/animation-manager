// Fonctions pures utilisées par planning.js.
window.PlanningUtils = Object.freeze({
    dateDansPlage(dateStr, debutStr, finStr) {
        return debutStr <= dateStr && dateStr <= finStr;
    },

    estVraieAffectation(event) {
        return Boolean(event && event.display !== "background");
    },

    idAnimateurDepuisEvent(event) {
        return Number(event?.extendedProps?.animateur_id || event?.extendedProps?.animateurId || 0);
    },

    idEventNormalise(event) {
        return event?.id !== undefined && event?.id !== null ? String(event.id) : null;
    },

    intervallesSeChevauchent(debutA, finA, debutB, finB) {
        return debutA < finB && finA > debutB;
    },

    eventIntervalleDates(event) {
        const debut = event.start ? formatDateLocal(event.start) : event.startStr;
        const fin = event.end
            ? formatDateLocal(event.end)
            : (event.endStr || addDays(debut, 1));
        return { debut, fin };
    },

    lundiDeLaSemaine(date) {
        const d = new Date(date);
        const jour = d.getDay();
        const diff = jour === 0 ? -6 : 1 - jour;
        d.setDate(d.getDate() + diff);
        d.setHours(0, 0, 0, 0);
        return d;
    },
});
