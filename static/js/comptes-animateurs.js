document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("#comptes-animateurs-management");
    if (!root) return;
    const list = root.querySelector("[data-comptes-list]");
    const search = root.querySelector("[data-comptes-search]");
    const filter = root.querySelector("[data-comptes-filter]");
    const bulk = root.querySelector("[data-comptes-bulk]");
    const feedback = root.querySelector("[data-comptes-feedback]");
    let animateurs = [];
    const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;", "'":"&#39;"}[c]));
    const state = (a) => !a.access?.exists ? ["none", "Accès non activé"] : a.access.activation_pending ? ["pending", "Compte créé – activation à faire"] : ["used", "Compte activé"];
    const updateBulk = () => { bulk.disabled = !list.querySelector("input:checked"); };
    const render = () => {
        const needle = search.value.trim().toLowerCase();
        const rows = animateurs.filter((a) => { const s = state(a)[0]; return (!needle || `${a.prenom} ${a.nom}`.toLowerCase().includes(needle)) && (filter.value === "all" || s === filter.value); });
        list.innerHTML = rows.map((a) => {
            const [kind, label] = state(a); const phone = a.telephone || "";
            const smsText = a.access?.activation_pending
                ? `Bonjour ${a.prenom},\n\nTon accès au portail animateur Animation Manager est prêt.\n\nIdentifiant : ${a.access?.username || ""}\n\nClique sur ce lien pour activer ton compte et choisir ton mot de passe :\n${a.access?.activation_url || ""}`
                : `Bonjour ${a.prenom},\n\nTon accès au portail animateur Animation Manager est activé.\n\nLien : ${location.origin}/connexion/\nIdentifiant : ${a.access?.username || ""}\n\nÀ bientôt !`;
            return `<article class="compte-card" data-id="${a.id}"><label class="compte-select"><input type="checkbox" value="${a.id}" ${kind !== "none" ? "disabled" : ""}><span class="sr-only">Sélectionner ${esc(a.prenom)} ${esc(a.nom)}</span></label><div class="compte-main"><h3>${esc(a.prenom)} ${esc(a.nom)}</h3><strong class="compte-status compte-status--${kind}">${label}</strong><div class="compte-contact">${esc(phone || "Téléphone non renseigné")} · ${esc(a.email || "E-mail non renseigné")}</div>${a.access?.username ? `<div class="compte-username">Identifiant : <code>${esc(a.access.username)}</code></div>` : ""}${a.access?.last_login ? `<small>Dernière connexion : ${new Date(a.access.last_login).toLocaleString("fr-FR")}</small>` : ""}</div><div class="compte-actions">${kind === "none" ? `<button type="button" class="btn btn-primary btn-small" data-action="activate">Activer l’accès</button>` : ""}${kind !== "none" && phone ? `<a class="btn btn-secondary btn-small" href="sms:${encodeURIComponent(phone)}?body=${encodeURIComponent(smsText)}">SMS</a>` : ""}${kind !== "none" && a.access?.username ? `<button type="button" class="btn btn-ghost btn-small" data-action="copy">Copier</button>` : ""}</div></article>`;
        }).join("") || `<p class="empty-note">Aucun compte correspondant.</p>`;
        updateBulk();
    };
    const load = async () => { const response = await fetch(root.dataset.apiUrl, {headers: {"X-Requested-With": "XMLHttpRequest"}}); animateurs = await response.json(); render(); };
    const activate = async (id) => { const response = await fetch(`${root.dataset.apiUrl}${id}/`, {method: "PATCH", headers: {"Content-Type":"application/json", "X-CSRFToken":csrf}, body: JSON.stringify({role:"animateur", create_access:true})}); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Activation impossible"); await load(); };
    const copyText = async (text) => {
        if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
        const area = document.createElement("textarea"); area.value = text; area.style.position = "fixed"; area.style.opacity = "0"; document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
    };
    list.addEventListener("change", updateBulk);
    list.addEventListener("click", async (event) => { const button = event.target.closest("[data-action]"); if (!button) return; const id = Number(button.closest("[data-id]").dataset.id); try { if (button.dataset.action === "activate") { button.disabled = true; await activate(id); feedback.textContent = "Compte créé. Le lien d’activation est disponible dans le bouton SMS."; } else { const a = animateurs.find((item) => item.id === id); await copyText(`Accès portail animateur\nIdentifiant : ${a.access.username}${a.access.activation_pending ? `\nLien d’activation : ${a.access.activation_url}` : ""}`); feedback.textContent = "Accès copiés."; } } catch (error) { feedback.textContent = error.message; } });
    bulk.addEventListener("click", async () => { const ids = [...list.querySelectorAll("input:checked")].map((input) => Number(input.value)); let activated = 0; for (const id of ids) { try { await activate(id); activated += 1; } catch {} } feedback.textContent = `${activated} accès activé${activated > 1 ? "s" : ""} – ${ids.length - activated} déjà actifs ou en erreur.`; });
    search.addEventListener("input", render); filter.addEventListener("change", render); load().catch(() => { feedback.textContent = "Impossible de charger les comptes."; });
});
