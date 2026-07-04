document.addEventListener("DOMContentLoaded", function ()
{
	function	createCalendar(containerID)
	{
		const calendarEl = document.getElementById(containerID);
		const calendar = new FullCalendar.Calendar(calendarEl,
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
				center: "",
				right: "dayGridMonth dayGridWeek"
			}
		});
		return (calendar);
	}
	const calendar1 = createCalendar("calendar-1");
	const calendar2 = createCalendar("calendar-2");
	const calendar3 = createCalendar("calendar-3");
    calendar1.render();
    calendar2.render();
    calendar3.render();

	const animList = document.getElementById("animateurs-list");

	fetch("/api/animateurs/").then(response => response.json()).then(data =>
	{
		data.forEach((animateur) =>
		{
			const div = document.createElement("div");
			div.textContent = animateur.prenom + " ." + animateur.nom[0];
			div.classList.add("animateur");
			animList.appendChild(div);
		});
	});

    new FullCalendar.Draggable(animList,
	{
        itemSelector: ".animateur",
        eventData: function (eventEl)
		{
			return {
				title: eventEl.textContent,
				allDay: true
			};
		}
    });
})