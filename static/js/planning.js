document.addEventListener("DOMContentLoaded", function () {
    const calendarEl = document.getElementById("calendar");
    const animateursList = document.getElementById("animateurs-list");

    new FullCalendar.Draggable(animateursList,
	{
        itemSelector: ".animateur-draggable",
        eventData: function (eventEl) {
    return {
        title: eventEl.dataset.title,
        allDay: true
    };
}
    });

	const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "dayGridMonth",
    locale: "fr",
    firstDay: 1,

    editable: true,
    droppable: true,
    selectable: true,

    height: 600,
	aspectRatio: 3,
    contentHeight: 100,
    fixedWeekCount: false,
    dayMaxEventRows: 3,
	eventClick: function (info)
	{
		const confirmation = confirm(`Supprimer "${info.event.title}" du planning ?`);

		if (confirmation)
			info.event.remove();
	},

    headerToolbar: {
        left: "prev,next today",
        center: "title",
        right: "dayGridMonth dayGridWeek"
    }
});
    calendar.render();
});