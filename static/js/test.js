document.addEventListener("DOMContentLoaded", function ()
{
	const calendarEl1 = document.getElementById("calendar-1");

	const calendar1 = new FullCalendar.Calendar(calendarEl1,
	{
		initialView: "dayGridWeek",
		locale: "fr",
		firstDay: 1,

		editable: true,
		droppable: true,
		selectable: true,

		fixedWeekCount: false,
		eventClick: function (info)
		{
			const confirmation = confirm(`Supprimer "${info.event.title}" du planning ?`);

			if (confirmation)
				info.event.remove();
		},

		headerToolbar:
		{
			left: "prev,next today",
			center: "title",
			right: "dayGridMonth dayGridWeek"
		}
	});
	const calendarEl2 = document.getElementById("calendar-2");

	const calendar2 = new FullCalendar.Calendar(calendarEl2,
	{
		initialView: "dayGridWeek",
		locale: "fr",
		firstDay: 1,

		editable: true,
		droppable: true,
		selectable: true,

		fixedWeekCount: false,
		eventClick: function (info)
		{
			const confirmation = confirm(`Supprimer "${info.event.title}" du planning ?`);

			if (confirmation)
				info.event.remove();
		},

		headerToolbar:
		{
			left: "prev,next today",
			center: "title",
			right: "dayGridMonth dayGridWeek"
		}
	});
	const calendarEl3 = document.getElementById("calendar-3");

	const calendar3 = new FullCalendar.Calendar(calendarEl3,
	{
		initialView: "dayGridWeek",
		locale: "fr",
		firstDay: 1,

		editable: true,
		droppable: true,
		selectable: true,

		fixedWeekCount: false,
		eventClick: function (info)
		{
			const confirmation = confirm(`Supprimer "${info.event.title}" du planning ?`);

			if (confirmation)
				info.event.remove();
		},

		headerToolbar:
		{
			left: "prev,next today",
			center: "title",
			right: "dayGridMonth dayGridWeek"
		}
	});
    calendar1.render();
    calendar2.render();
    calendar3.render();
	fetch("/api/animateurs/")
    .then(response => response.json())
    .then(data => {
        console.log(data);
    });
})