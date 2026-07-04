document.addEventListener("DOMContentLoaded", function () {
    const calendarEl = document.getElementById("calendar");
    const animateursList = document.getElementById("animateurs-list");

    new FullCalendar.Draggable(animateursList, {
        itemSelector: ".animateur-draggable",
        eventData: function (eventEl) {
            return {
                title: eventEl.dataset.title,
                duration: "08:00"
            };
        }
    });

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: "timeGridWeek",
        locale: "fr",
        firstDay: 1,
        editable: true,
        droppable: true,
        selectable: true,
        height: "auto",

        headerToolbar: {
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek"
        },

        drop: function (info) {
            console.log("Animateur déposé le :", info.dateStr);
        },

        eventReceive: function (info) {
            console.log("Créneau créé :", {
                titre: info.event.title,
                debut: info.event.start,
                fin: info.event.end
            });

            // Ici ensuite on enverra à Django pour sauvegarder
        },

        eventDrop: function (info) {
            console.log("Créneau déplacé :", info.event.id);
        },

        eventResize: function (info) {
            console.log("Créneau modifié :", info.event.id);
        }
    });

    calendar.render();
});