function csrfToken() {
	return document.querySelector("[name=csrfmiddlewaretoken]").value;
}

function apiFetch(url, options = {}) {
	options.headers = Object.assign(
		{
			"Content-Type": "application/json",
			"X-CSRFToken": csrfToken(),
		},
		options.headers || {}
	);

	return fetch(url, options).then((response) =>
	{
		if (!response.ok)
		{
			return response.json().then((err) => { throw err; });
		}
		return response.status === 204 ? null : response.json();
	});
}

function erreurMessage(err, repli) {
	return (err && err.error) ? err.error : repli;
}

function addDays(dateStr, days) {
	const d = new Date(dateStr);
	d.setDate(d.getDate() + days);
	return d.toISOString().slice(0, 10);
}

function ouvrirModal(backdropEl) {
	backdropEl.hidden = false;
}

function fermerModal(backdropEl) {
	backdropEl.hidden = true;
}

function initFermetureModal(backdropEl) {
	backdropEl.addEventListener("click", (event) => {
		if (event.target === backdropEl) {
			fermerModal(backdropEl);
		}
	});

	backdropEl.querySelectorAll("[data-modal-close]").forEach((btn) => {
		btn.addEventListener("click", () => fermerModal(backdropEl));
	});

	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && !backdropEl.hidden) {
			fermerModal(backdropEl);
		}
	});
}

function afficherToast(message, estErreur = false) {
	const existant = document.querySelector(".toast");
	if (existant) {
		existant.remove();
	}

	const toast = document.createElement("div");
	toast.classList.add("toast");
	if (estErreur) {
		toast.classList.add("error");
	}
	toast.textContent = message;
	document.body.appendChild(toast);

	setTimeout(() => toast.remove(), 3200);
}

function initTabs(rootEl) {
	const boutons = rootEl.querySelectorAll(".tab-btn");

	boutons.forEach((btn) => {
		btn.addEventListener("click", () => {
			boutons.forEach((b) => b.classList.remove("active"));
			rootEl.querySelectorAll(".tab-panel").forEach((p) => { p.hidden = true; });

			btn.classList.add("active");
			rootEl.querySelector(`.tab-panel[data-panel="${btn.dataset.tab}"]`).hidden = false;
		});
	});
}
