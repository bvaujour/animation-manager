(function(){
"use strict";
const root=document.getElementById("sortie-detail"),blocks=document.getElementById("sortie-blocks"),dialog=document.getElementById("sortie-editor"),form=document.getElementById("sortie-editor-form"),body=document.getElementById("editor-body");
const id=root.dataset.sortieId;
let data,current,weather=null,pendingResponsibilities=null,pendingRemovedAssignments=[],pendingNewAssignments=[];

const text=v=>escapeHtml(v||"Non renseigné"),names=v=>(v||[]).map(x=>x.nom).join(", ")||"Aucun";
const parseMaybeDate=value=>value?parseLocalDate(value):null;
const nl2br=value=>text(value).replace(/\n/g,"<br>");
const timeValue=value=>value?String(value).slice(0,5):"";
const plural=(count,singular,pluralForm=null)=>`${count} ${count>1?(pluralForm||singular+"s"):singular}`;
const dedupeById=items=>Object.values((items||[]).reduce((acc,item)=>{if(item&&item.id!=null)acc[item.id]=item;return acc;},{}));
const safeHex=value=>/^#[0-9a-f]{6}$/i.test(String(value||""))?String(value):"#64748B";
const staffVars=person=>`--staff-color:${safeHex(person?.couleur_statut)};--staff-bg:${safeHex(person?.couleur_fond_statut||"#EEF1F5")}`;
const staffStatusName=person=>person?.statut_principal?.nom||"Sans statut";

function staffStatusBadge(person){
  return `<span class="sortie-staff-status" style="${staffVars(person)}"><i></i>${escapeHtml(staffStatusName(person))}</span>`;
}

function ageKey(group){
  const source=`${group.groupe||""} ${group.centre||""}`.toLowerCase();
  if(source.includes("mater")||source.includes("matern")||source.includes("3/5")) return "maternels";
  if(source.includes("elem")||source.includes("élém")||source.includes("element")||source.includes("6/10")) return "elementaires";
  return "autres";
}

function splitGroups(groups){
  return (groups||[]).reduce((acc,group)=>{
    const key=ageKey(group);
    (acc[key]||(acc[key]=[])).push(group);
    return acc;
  },{maternels:[],elementaires:[],autres:[]});
}

function sumBy(groups,key){return (groups||[]).reduce((total,item)=>total+(Number(item[key])||0),0);}

function bucketStats(groups){
  const animateurs=dedupeById((groups||[]).flatMap(group=>group.animateurs||[]));
  return {
    groupes:(groups||[]).length,
    enfants:sumBy(groups,"effectif"),
    animateurs:animateurs.length,
    animateursList:animateurs,
    nonCouverts:sumBy(groups,"non_couverts"),
  };
}

function formatDateHeader(value){
  const date=parseMaybeDate(value);
  if(!date){
    return {weekday:"DATE",dayMonth:"À compléter",year:"",full:"Date non renseignée"};
  }
  const weekday=date.toLocaleDateString("fr-FR",{weekday:"long"}).toUpperCase();
  const dayMonth=date.toLocaleDateString("fr-FR",{day:"numeric",month:"long"}).toUpperCase();
  const year=date.toLocaleDateString("fr-FR",{year:"numeric"});
  const full=date.toLocaleDateString("fr-FR",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
  return {weekday,dayMonth,year,full};
}

function formatSummaryList(raw){
  const lines=String(raw||"").split(/\n+/).map(line=>line.trim()).filter(Boolean);
  if(!lines.length){
    return '<p class="sortie-empty">Non renseigné</p>';
  }
  return `<ul class="sortie-bullets">${lines.map(line=>`<li>${escapeHtml(line.replace(/^[•\-]\s*/,""))}</li>`).join("")}</ul>`;
}

function formatContacts(person){
  if(!person){return '<p class="sortie-empty">Non renseigné</p>'}
  const extras=[];
  if(person.telephone) extras.push(`<span>${escapeHtml(person.telephone)}</span>`);
  if(person.email) extras.push(`<span>${escapeHtml(person.email)}</span>`);
  return `${staffStatusBadge(person)}<strong>${escapeHtml(person.nom)}</strong>${extras.length?`<div class="sortie-contact-lines">${extras.join("")}</div>`:""}`;
}


function responsibilityTitle(item){
  if(item.type==="lieu"&&item.centre) return `Lieu — ${item.centre.nom}`;
  if(item.type==="groupe"&&item.groupe) return `Groupe — ${item.groupe.nom}`;
  return "Direction";
}

function responsibilitySummary(item){
  if(item.type==="direction"){
    return {
      key:"direction",
      title:"Direction",
      subtitle:"Toute la sortie",
      enfants:(data.totaux&&data.totaux.enfants)||0,
      animateurs:(data.totaux&&data.totaux.animateurs)||0,
    };
  }
  if(item.type==="lieu" && item.centre){
    const groups=(data.groupes||[]).filter(group=>Number(group.centre_id)===Number(item.centre.id));
    const animateurs=dedupeById(groups.flatMap(group=>group.animateurs||[]));
    return {
      key:`lieu-${item.centre.id}`,
      title:`Lieu — ${item.centre.nom}`,
      subtitle:groups.length?`${plural(groups.length,'groupe')}`:'Aucun groupe',
      enfants:sumBy(groups,'effectif'),
      animateurs:animateurs.length,
    };
  }
  if(item.type==="groupe" && item.groupe){
    const group=(data.groupes||[]).find(entry=>Number(entry.evenement_id)===Number(item.groupe.id));
    return {
      key:`groupe-${item.groupe.id}`,
      title:`Groupe — ${item.groupe.nom}`,
      subtitle:item.groupe.centre||'',
      enfants:Number(group?.effectif)||0,
      animateurs:(group?.animateurs||[]).length,
    };
  }
  return {
    key:`other-${item.id}`,
    title:responsibilityTitle(item),
    subtitle:'',
    enfants:0,
    animateurs:0,
  };
}

function renderResponsibilities(){
  const items=data.responsabilites||[];
  if(!items.length){
    return '<div class="sortie-responsables-empty"><p>Aucun responsable défini.</p><span>Cliquez sur ce bloc pour en ajouter.</span></div>';
  }
  const grouped=new Map();
  items.forEach(item=>{
    if(!item.animateur) return;
    const key=String(item.animateur.id);
    if(!grouped.has(key)) grouped.set(key,{animateur:item.animateur,scopes:[]});
    const card=grouped.get(key);
    const summary=responsibilitySummary(item);
    if(!card.scopes.some(scope=>scope.key===summary.key)) card.scopes.push(summary);
  });
  return [...grouped.values()].map(card=>`<article class="sortie-responsibility-card" style="${staffVars(card.animateur)}">
    <div class="sortie-responsibility-card__header">
      ${staffStatusBadge(card.animateur)}
      <strong class="sortie-responsibility-card__name">${escapeHtml(card.animateur.nom)}</strong>
      ${(card.animateur.telephone||card.animateur.email)?`<div class="sortie-contact-lines">${card.animateur.telephone?`<span>${escapeHtml(card.animateur.telephone)}</span>`:''}${card.animateur.email?`<span>${escapeHtml(card.animateur.email)}</span>`:''}</div>`:''}
    </div>
    <div class="sortie-responsibility-scope-list">${card.scopes.map(scope=>`<div class="sortie-responsibility-scope-item">
      <div class="sortie-responsibility-scope-text">
        <span class="sortie-responsibility-scope-title">${escapeHtml(scope.title)}</span>
        ${scope.subtitle?`<span class="sortie-responsibility-scope-subtitle">${escapeHtml(scope.subtitle)}</span>`:''}
      </div>
      <strong class="sortie-responsibility-scope-count">${scope.enfants} enfants + ${scope.animateurs} animateurs</strong>
    </div>`).join('')}</div>
  </article>`).join('');
}

function groupedResponsibilities(){
  const grouped=new Map();
  (data.responsabilites||[]).forEach(item=>{
    const key=`${item.animateur.id}|${item.type}`;
    if(!grouped.has(key)) grouped.set(key,{animateur_id:item.animateur.id,type:item.type,cibles:[]});
    if(item.type==="lieu"&&item.centre) grouped.get(key).cibles.push(item.centre.id);
    if(item.type==="groupe"&&item.groupe) grouped.get(key).cibles.push(item.groupe.id);
  });
  return [...grouped.values()];
}

function catalogueResponsables(){return data.catalogue_animateurs||[];}
function candidateById(id){return catalogueResponsables().find(item=>item.id===Number(id))||null;}

function animatorOptions(selected){
  const selectedId=Number(selected);
  const groups=[
    ["affecte","Affectés sur un groupe ou lieu concerné"],
    ["disponible","Disponibles et non affectés"],
  ];
  const options=groups.map(([type,label])=>{
    const items=catalogueResponsables().filter(item=>item.eligibilite===type);
    if(!items.length) return "";
    return `<optgroup label="${label}">${items.map(item=>`<option value="${item.id}" ${selectedId===item.id?"selected":""} style="background:${safeHex(item.couleur_fond_statut)};color:#243244">${escapeHtml(item.nom)} — ${escapeHtml(staffStatusName(item))} — ${escapeHtml(item.situation||"")}</option>`).join("")}</optgroup>`;
  }).join("");
  return `<option value="">Choisir…</option>${options}`;
}

function staffCandidatePreview(person){
  if(!person) return '<p class="sortie-responsibility-candidate-empty">Choisissez un salarié dans la liste autorisée.</p>';
  return `<div class="sortie-responsibility-candidate" style="${staffVars(person)}">
    ${staffStatusBadge(person)}
    <strong>${escapeHtml(person.nom)}</strong>
    <span>${escapeHtml(person.situation||person.eligibilite_libelle||"")}</span>
  </div>`;
}

function updateResponsibilityCandidate(wrapper){
  const person=candidateById(wrapper.querySelector("[data-resp-animateur]").value);
  wrapper.style.setProperty("--staff-color",safeHex(person?.couleur_statut));
  wrapper.style.setProperty("--staff-bg",safeHex(person?.couleur_fond_statut||"#F8FAFC"));
  wrapper.querySelector("[data-resp-candidate-preview]").innerHTML=staffCandidatePreview(person);
}


function responsibilityTargets(type,selected=[]){
  const chosen=new Set((selected||[]).map(Number));
  if(type==="direction") return '<p class="sortie-responsibility-scope-note">Responsabilité sur l’ensemble de la sortie.</p>';
  if(type==="lieu"){
    const centres=[...new Map((data.groupes||[]).map(group=>[group.centre_id,{id:group.centre_id,nom:group.centre}])).values()];
    if(!centres.length) return '<p class="sortie-responsibility-scope-note">Sélectionnez d’abord les groupes participants.</p>';
    return `<div class="sortie-responsibility-target-list">${centres.map(centre=>`<label><input type="checkbox" data-resp-target value="${centre.id}" ${chosen.has(centre.id)?"checked":""}><span>${escapeHtml(centre.nom)}</span></label>`).join("")}</div>`;
  }
  if(!(data.groupes||[]).length) return '<p class="sortie-responsibility-scope-note">Sélectionnez d’abord les groupes participants.</p>';
  return `<div class="sortie-responsibility-target-list">${(data.groupes||[]).map(group=>`<label><input type="checkbox" data-resp-target value="${group.evenement_id}" ${chosen.has(group.evenement_id)?"checked":""}><span>${escapeHtml(group.centre)} — ${escapeHtml(group.groupe)}</span></label>`).join("")}</div>`;
}

function responsibilityRow(entry={animateur_id:"",type:"direction",cibles:[]}){
  const wrapper=document.createElement("div");
  wrapper.className="sortie-responsibility-row";
  wrapper.dataset.responsibilityRow="";
  wrapper.innerHTML=`
    <div class="sortie-responsibility-row__top">
      <label class="sortie-responsibility-staff-field">Responsable<select data-resp-animateur>${animatorOptions(entry.animateur_id)}</select><div data-resp-candidate-preview></div></label>
      <label>Périmètre<select data-resp-type>
        <option value="direction" ${entry.type==="direction"?"selected":""}>Direction</option>
        <option value="lieu" ${entry.type==="lieu"?"selected":""}>Un ou plusieurs lieux</option>
        <option value="groupe" ${entry.type==="groupe"?"selected":""}>Un ou plusieurs groupes</option>
      </select></label>
      <button type="button" class="btn btn-danger-ghost sortie-responsibility-remove" data-resp-remove>Supprimer</button>
    </div>
    <div class="sortie-responsibility-targets" data-resp-targets>${responsibilityTargets(entry.type,entry.cibles)}</div>`;
  wrapper.querySelector("[data-resp-type]").addEventListener("change",event=>{
    wrapper.querySelector("[data-resp-targets]").innerHTML=responsibilityTargets(event.target.value,[]);
  });
  wrapper.querySelector("[data-resp-animateur]").addEventListener("change",()=>updateResponsibilityCandidate(wrapper));
  wrapper.querySelector("[data-resp-remove]").addEventListener("click",()=>wrapper.remove());
  updateResponsibilityCandidate(wrapper);
  return wrapper;
}

function openResponsibilitiesEditor(){
  body.innerHTML='<div class="full sortie-responsibility-editor"><div data-responsibility-list></div><button type="button" class="btn btn-secondary" data-add-responsibility>+ Ajouter un responsable</button></div>';
  const list=body.querySelector("[data-responsibility-list]");
  groupedResponsibilities().forEach(entry=>list.appendChild(responsibilityRow(entry)));
  body.querySelector("[data-add-responsibility]").addEventListener("click",()=>list.appendChild(responsibilityRow()));
}

function renderLinks(){
  const links=(data.liens||[]).map(item=>`<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.libelle)}</a></li>`).join("");
  const docs=(data.documents||[]).map(item=>`<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.titre)}</a></li>`).join("");
  if(!links && !docs){
    return '<p class="sortie-empty">Aucun document ou lien.</p>';
  }
  return `
    ${links?`<div><h4>Liens</h4><ul class="sortie-links-list">${links}</ul></div>`:""}
    ${docs?`<div><h4>Documents</h4><ul class="sortie-links-list">${docs}</ul></div>`:""}
  `;
}

function activityFor(group){return group.activite_horaire?escapeHtml(group.activite_horaire):'<span class="sortie-muted">À compléter</span>';}
function teamFor(group){return group.animateurs&&group.animateurs.length?escapeHtml(group.animateurs.map(item=>item.nom).join(" · ")):'<span class="sortie-muted">Aucun animateur</span>';}
function groupCountLabel(groups){return `${(groups||[]).length} groupe${(groups||[]).length>1?"s":""}`;}

function weatherSummary(){
  if(!data.meteo_lieu?.latitude) return '<p class="sortie-weather-empty"><strong>Lieu météo à définir</strong><span>Cliquer pour localiser la sortie</span></p>';
  if(!weather) return '<p class="sortie-weather-empty">Chargement de la météo…</p>';
  if(weather.statut!=="prevision") return `<p class="sortie-weather-empty"><strong>${escapeHtml(weather.message||"Météo momentanément indisponible")}</strong></p>`;
  const r=weather.resume,c=weather.conditions;
  return `<div class="sortie-weather-summary"><span class="sortie-weather-icon">${c.pictogramme}</span><div><strong>${escapeHtml(c.libelle)}</strong><b>${r.temperature_min} à ${r.temperature_max} °C</b></div><dl><div><dt>Pluie</dt><dd>${r.precipitations_mm} mm</dd></div><div><dt>Rafales</dt><dd>${r.rafales_max_kmh} km/h</dd></div><div><dt>UV</dt><dd>${r.uv_max}</dd></div></dl><small>${escapeHtml(weather.source_libelle)} · ${new Date(weather.mis_a_jour_le).toLocaleTimeString("fr-FR",{hour:"numeric",minute:"2-digit"})}</small></div>`;
}
async function loadWeather(force=false){
  if(!data.meteo_lieu?.latitude){weather=null;render();return}
  try{weather=await apiFetch(`/api/sorties/${id}/meteo/${force?"?forcer=1":""}`)}catch(error){weather={statut:"erreur",message:erreurMessage(error,"Météo momentanément indisponible")}}
  render();
}
async function load(){data=await apiFetch(`/api/sorties/${id}/`);render();loadWeather()}

function render(){
  const dateParts=formatDateHeader(data.date);
  const buckets=splitGroups(data.groupes||[]);
  const maternalStats=bucketStats(buckets.maternels);
  const elementaryStats=bucketStats(buckets.elementaires);
  const otherStats=bucketStats(buckets.autres);
  const totalChildren=(data.totaux&&data.totaux.enfants)||0;
  const totalAnimators=(data.totaux&&data.totaux.animateurs)||0;
  const uncovered=(data.totaux&&data.totaux.non_couverts)||0;
  const totalGroups=(data.groupes||[]).length;
  const transportLabel=data.transport.nombre_vehicules?`${data.transport.nombre_vehicules} ${data.transport.mode_transport||"véhicule(s)"}`:(data.transport.mode_transport||"À compléter");
  const floatingNotes=(data.flottants_par_centre||[]).map(item=>`${item.centre} : ${item.animateurs.map(anim=>anim.nom).join(" · ")}`).join("<br>");

  document.getElementById("sortie-title").textContent=data.nom;
  document.getElementById("sortie-subtitle").textContent=`${dateParts.full} · ${data.destination}`;

  blocks.innerHTML=`
    <div class="sortie-document">
      <section class="sortie-sheet-page">
        <div class="sortie-sheet-top is-clickable" data-block="general" tabindex="0" role="button">
          <div class="sortie-sheet-title">
            <span>Fiche de sortie</span>
            <h2>${escapeHtml(data.nom)}</h2>
          </div>
          <div class="sortie-sheet-date">
            <span>${dateParts.weekday}</span>
            <strong>${dateParts.dayMonth}</strong>
            <small>${dateParts.year}</small>
          </div>
        </div>

        <div class="sortie-stats-band is-clickable" data-block="participants" tabindex="0" role="button">
          <article><span>Lieu</span><strong>${escapeHtml(data.destination)}</strong></article>
          <article><span>Enfants</span><strong>${totalChildren}</strong></article>
          <article><span>Adultes</span><strong>${totalAnimators}</strong></article>
          <article><span>Transport</span><strong>${escapeHtml(transportLabel)}</strong></article>
        </div>

        <section class="sortie-section is-clickable" data-block="responsables" tabindex="0" role="button">
          <header><h3>Responsables et contacts</h3><span class="sortie-edit-chip">Modifier</span></header>
          <div class="sortie-responsables-grid">${renderResponsibilities()}</div>
        </section>

        <section class="sortie-section is-clickable" data-block="transport" tabindex="0" role="button">
          <header><h3>Transport</h3><span class="sortie-edit-chip">Modifier</span></header>
          <div class="sortie-transport-grid">
            <article>
              <h4>Aller ${timeValue(data.transport.heure_depart)?`- départ ${timeValue(data.transport.heure_depart)}`:""}</h4>
              <p>${nl2br(data.transport.trajet_ramassage||data.transport.mode_transport||"À compléter")}</p>
              ${timeValue(data.transport.heure_arrivee)?`<p class="sortie-transport-note"><strong>Arrivée estimée :</strong> ${timeValue(data.transport.heure_arrivee)}</p>`:""}
            </article>
            <article>
              <h4>Retour ${timeValue(data.transport.heure_retour)?`- départ ${timeValue(data.transport.heure_retour)}`:""}</h4>
              <p>${nl2br(data.transport.consignes_transport||"À compléter")}</p>
              ${timeValue(data.transport.heure_depart_site)?`<p class="sortie-transport-note"><strong>Départ du site :</strong> ${timeValue(data.transport.heure_depart_site)}</p>`:""}
            </article>
          </div>
          ${floatingNotes?`<p class="sortie-floating-note"><strong>Animateurs flottants :</strong><br>${floatingNotes}</p>`:""}
        </section>

        <section class="sortie-section sortie-weather-card is-clickable" data-block="meteo" tabindex="0" role="button">
          <header><h3>Météo de la sortie</h3><span class="sortie-edit-chip">Détails</span></header>
          ${weatherSummary()}
        </section>

        <section class="sortie-section is-clickable" data-block="repartition" tabindex="0" role="button">
          <header><h3>Répartition des groupes et ateliers</h3><span class="sortie-edit-chip">Modifier</span></header>
          <div class="sortie-table-wrap">
            <table class="sortie-sheet-table">
              <thead>
                <tr><th>Âge</th><th>Centre</th><th>Équipe</th><th>Atelier</th></tr>
              </thead>
              <tbody>
                ${(data.groupes||[]).map(group=>`<tr>
                  <td>${escapeHtml(ageKey(group)==="maternels"?"Maternels":ageKey(group)==="elementaires"?"Élémentaires":"Groupe")}</td>
                  <td><strong>${escapeHtml(group.centre)}</strong><br><span>${group.effectif} enfants</span></td>
                  <td>${teamFor(group)}</td>
                  <td>${activityFor(group)}</td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
          <div class="sortie-table-footnotes">
            <span>${plural(totalGroups,"groupe")}</span>
            <span>${plural(totalChildren,"enfant")}</span>
            <span>${plural(totalAnimators,"animateur")}</span>
            <span class="${uncovered?"is-warning":"is-ok"}">${uncovered?`${plural(uncovered,"enfant")} non couvert${uncovered>1?"s":""}`:"Encadrement complet"}</span>
          </div>
        </section>

        <section class="sortie-section">
          <header><h3>Mémo équipe et vigilances</h3></header>
          <div class="sortie-two-columns">
            <article class="is-clickable" data-block="consignes_encadrement" tabindex="0" role="button">
              <h4>Consignes d’encadrement</h4>
              ${formatSummaryList(data.textes.consignes_encadrement)}
            </article>
            <article class="sortie-vigilances-panel ${data.vigilances&&data.vigilances.length?"has-warning":""}">
              <h4>Vigilances</h4>
              ${formatSummaryList((data.vigilances||[]).join("\n"))}
            </article>
          </div>
        </section>
      </section>

      <section class="sortie-sheet-page">
        <section class="sortie-section is-clickable" data-block="objectifs_pedagogiques" tabindex="0" role="button">
          <header><h3>Objectifs pédagogiques</h3><span class="sortie-edit-chip">Modifier</span></header>
          <div class="sortie-two-columns sortie-two-columns--text">
            <article>${formatSummaryList(data.textes.objectifs_pedagogiques)}</article>
            <article class="sortie-complement-card">
              <h4>Données Planning reprises automatiquement</h4>
              <ul class="sortie-bullets">
                <li>${groupCountLabel(buckets.maternels)} maternels · ${maternalStats.enfants} enfants</li>
                <li>${groupCountLabel(buckets.elementaires)} élémentaires · ${elementaryStats.enfants} enfants</li>
                ${otherStats.groupes?`<li>${groupCountLabel(buckets.autres)} autre(s) · ${otherStats.enfants} enfants</li>`:""}
                <li>${plural(totalAnimators,"animateur")} mobilisé${totalAnimators>1?"s":""}</li>
              </ul>
            </article>
          </div>
        </section>

        <section class="sortie-section">
          <header><h3>Organisation pédagogique</h3></header>
          <div class="sortie-two-columns">
            <article class="is-clickable" data-block="organisation_maternels" tabindex="0" role="button">
              <h4>Maternels</h4>
              <p class="sortie-mini-meta">${maternalStats.enfants} enfants · ${maternalStats.animateurs} anim</p>
              <div class="sortie-richtext">${nl2br(data.textes.organisation_maternels)}</div>
            </article>
            <article class="is-clickable" data-block="organisation_elementaires" tabindex="0" role="button">
              <h4>Élémentaires</h4>
              <p class="sortie-mini-meta">${elementaryStats.enfants} enfants · ${elementaryStats.animateurs} anim</p>
              <div class="sortie-richtext">${nl2br(data.textes.organisation_elementaires)}</div>
            </article>
          </div>
        </section>

        <section class="sortie-section">
          <header><h3>Repas, goûter et ressources</h3></header>
          <div class="sortie-two-columns">
            <article class="is-clickable" data-block="repas_gouter" tabindex="0" role="button">
              <h4>Repas et goûter</h4>
              <div class="sortie-richtext">${nl2br(data.textes.repas_gouter)}</div>
            </article>
            <article class="is-clickable" data-block="liens" tabindex="0" role="button">
              <h4>Documents et liens</h4>
              <div class="sortie-links-grid">${renderLinks()}</div>
            </article>
          </div>
        </section>
      </section>
    </div>`;

  blocks.querySelectorAll("[data-block]").forEach(item=>{
    item.addEventListener("click",event=>{
      const block=event.currentTarget.dataset.block;
      if(block) open(block,event.currentTarget.querySelector("h3, h2")?.textContent||"Modifier");
    });
    item.addEventListener("keydown",event=>{
      if(event.key==="Enter"||event.key===" "){
        event.preventDefault();
        event.currentTarget.click();
      }
    });
  });
}

function input(name,label,value="",type="text"){return `<label>${label}<input name="${name}" type="${type}" value="${escapeHtml(value??"")}"></label>`}

function open(key,title){
  if(key==="vigilances")return;
  current=key;
  document.getElementById("editor-title").textContent=title;
  form.querySelector(".form-error").hidden=true;
  form.querySelector(".form-error").textContent="";
  if(key==="general"){
    body.innerHTML=input("nom","Nom",data.nom)+input("date","Date",data.date,"date")+input("destination","Lieu ou destination",data.destination)
  }else if(key==="participants"){
    const groupsByCentre=(data.catalogue_groupes||[]).reduce((acc,group)=>{(acc[group.centre]||(acc[group.centre]=[])).push(group);return acc;},{});
    const chosen=new Set((data.groupes||[]).map(group=>group.evenement_id));
    body.innerHTML=`<div class="full">${Object.entries(groupsByCentre).map(([centre,groups])=>`<label class="group-centre group-choice"><input type="checkbox" data-select-centre><span>${escapeHtml(centre)} — tous les groupes</span></label>${groups.map(group=>`<label class="group-choice${group.ouvert?"":" is-closed"}"><input type="checkbox" name="groupes" value="${group.id}" ${chosen.has(group.id)?"checked":""} ${group.ouvert?"":"disabled"}><span>${escapeHtml(group.nom)}</span>${group.ouvert?"":"<small>fermé ce jour</small>"}</label>`).join("")}`).join("")}</div>`;
    body.querySelectorAll("[data-select-centre]").forEach(toggle=>toggle.addEventListener("change",()=>{let row=toggle.parentElement.nextElementSibling;while(row&&row.classList.contains("group-choice")&&!row.classList.contains("group-centre")){const checkbox=row.querySelector("input[name='groupes']");if(checkbox&&!checkbox.disabled) checkbox.checked=toggle.checked;row=row.nextElementSibling}}));
  }else if(key==="responsables"){
    openResponsibilitiesEditor();
  }else if(key==="transport"){
    const t=data.transport;
    body.innerHTML=input("mode_transport","Mode de transport",t.mode_transport)+input("nombre_vehicules","Nombre de véhicules",t.nombre_vehicules,"number")+input("heure_depart","Départ",t.heure_depart,"time")+input("heure_arrivee","Arrivée",t.heure_arrivee,"time")+input("heure_depart_site","Départ du site",t.heure_depart_site,"time")+input("heure_retour","Retour",t.heure_retour,"time")+`<label class="full">Trajet ou ramassage<textarea name="trajet_ramassage">${escapeHtml(t.trajet_ramassage)}</textarea></label><label class="full">Consignes transport / retour<textarea name="consignes_transport">${escapeHtml(t.consignes_transport)}</textarea></label>`
  }else if(key==="meteo"){
    const current=data.meteo_lieu||{};
    const details=weather?.statut==="prevision"?`<section class="sortie-weather-detail"><div>${weatherSummary()}</div>${weather.alertes?.length?`<ul>${weather.alertes.map(item=>`<li>Point de vigilance météo : ${escapeHtml(item)}</li>`).join("")}</ul>`:""}<button type="button" class="btn btn-ghost" data-weather-refresh>Actualiser</button><div class="sortie-weather-hours"><table><thead><tr><th>Heure</th><th></th><th>Temp.</th><th>Pluie</th><th>Vent</th><th>Rafales</th></tr></thead><tbody>${weather.heures.map(item=>`<tr><td>${item.heure}</td><td>${item.pictogramme}</td><td>${item.temperature} °C</td><td>${item.precipitations_mm} mm</td><td>${item.vent_kmh}</td><td>${item.rafales_kmh}</td></tr>`).join("")}</tbody></table></div></section>`:"";
    body.innerHTML=`<div class="full sortie-weather-editor">${details}<h3>Modifier le lieu météo</h3><label>Rechercher un lieu<input data-weather-search value="${escapeHtml(current.libelle||data.destination)}" autocomplete="off"></label><div data-weather-results></div><p data-weather-selected>${current.adresse?escapeHtml(current.adresse):"Aucun lieu validé"}</p><input type="hidden" name="meteo_lieu_libelle" value="${escapeHtml(current.libelle||"")}"><input type="hidden" name="meteo_adresse" value="${escapeHtml(current.adresse||"")}"><input type="hidden" name="meteo_latitude" value="${current.latitude??""}"><input type="hidden" name="meteo_longitude" value="${current.longitude??""}"><input type="hidden" name="meteo_code_departement" value="${escapeHtml(current.code_departement||"")}"></div>`;
    let timer;const search=body.querySelector("[data-weather-search]"),results=body.querySelector("[data-weather-results]");search.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(async()=>{if(search.value.trim().length<3){results.innerHTML="";return}try{const response=await apiFetch(`/api/sorties/geocodage/?q=${encodeURIComponent(search.value.trim())}`);results.innerHTML=response.resultats.map((item,index)=>`<button type="button" data-weather-result="${index}"><strong>${escapeHtml(item.libelle)}</strong><small>${escapeHtml(item.adresse)}</small></button>`).join("");results.querySelectorAll("[data-weather-result]").forEach(button=>button.addEventListener("click",()=>{const item=response.resultats[Number(button.dataset.weatherResult)];for(const [name,value] of Object.entries({meteo_lieu_libelle:item.libelle,meteo_adresse:item.adresse,meteo_latitude:item.latitude,meteo_longitude:item.longitude,meteo_code_departement:item.code_departement}))body.querySelector(`[name="${name}"]`).value=value;body.querySelector("[data-weather-selected]").textContent=item.adresse;results.innerHTML=""}))}catch(error){results.innerHTML=`<p class="form-error">${escapeHtml(erreurMessage(error,"Recherche indisponible"))}</p>`}},350)});
    body.querySelector("[data-weather-refresh]")?.addEventListener("click",async()=>{weather=null;dialog.close();render();await loadWeather(true)});
  }else if(key==="repartition"){
    body.innerHTML=`<table class="sortie-table"><thead><tr><th>Lieu</th><th>Groupe</th><th>Effectif</th><th>Animateurs</th><th>Activité / horaire</th></tr></thead><tbody>${(data.groupes||[]).map(group=>`<tr><td>${text(group.centre)}</td><td>${text(group.groupe)}</td><td>${group.effectif}</td><td>${text(names(group.animateurs))}</td><td><input name="activity-${group.evenement_id}" value="${escapeHtml(group.activite_horaire)}"></td></tr>`).join("")}</tbody></table>`
  }else if(key==="liens"){
    body.innerHTML=`<label class="full links-editor">Liens — une ligne par lien, sous la forme Libellé | URL<textarea name="liens">${(data.liens||[]).map(item=>`${item.libelle} | ${item.url}`).join("\n")}</textarea></label>`
  }else {
    body.innerHTML=`<label class="full"><textarea name="${key}" rows="10">${escapeHtml(data.textes[key]||"")}</textarea></label>`
  }
  dialog.showModal();
}

form.addEventListener("submit",async event=>{
  event.preventDefault();
  const fd=new FormData(form),payload={};
  if(current==="participants") payload.groupes=fd.getAll("groupes").map(Number);
  else if(current==="responsables"){
    payload.responsabilites=[...body.querySelectorAll("[data-responsibility-row]")].map(row=>({
      animateur_id:Number(row.querySelector("[data-resp-animateur]").value),
      type:row.querySelector("[data-resp-type]").value,
      cibles:[...row.querySelectorAll("[data-resp-target]:checked")].map(input=>Number(input.value)),
    }));
    const nouveauxIds=new Set(payload.responsabilites.map(item=>item.animateur_id));
    const anciens=[...new Map((data.responsabilites||[]).map(item=>[Number(item.animateur.id),item.animateur])).entries()];
    const suppressionsPossibles=anciens.filter(([animateurId])=>
      !nouveauxIds.has(animateurId)
      && (data.responsabilites||[]).some(item=>Number(item.animateur.id)===animateurId&&item.affectation_creee)
    );
    const nonAffectes=[...new Set(payload.responsabilites.map(item=>item.animateur_id))]
      .map(candidateById)
      .filter(person=>person?.eligibilite==="disponible");
    pendingResponsibilities=payload.responsabilites;
    pendingNewAssignments=nonAffectes;
    if(suppressionsPossibles.length){
      current="responsable_suppressions";
      document.getElementById("editor-title").textContent="Retirer du Planning ?";
      body.innerHTML=`<div class="full sortie-responsibility-assignment"><p>Ces affectations avaient été ajoutées lors de la nomination comme responsable. Voulez-vous aussi les enlever du Planning pour le jour de la sortie ?</p>${suppressionsPossibles.map(([animateurId,animateur])=>`<fieldset><legend>${escapeHtml(animateur.nom)}</legend><label><input type="radio" name="remove-${animateurId}" value="yes" required> Oui</label><label><input type="radio" name="remove-${animateurId}" value="no"> Non</label></fieldset>`).join("")}</div>`;
      return;
    }
    if(nonAffectes.length){
      current="responsable_affectations";
      document.getElementById("editor-title").textContent="Affecter les nouveaux responsables";
      const groupsByCentre=(data.groupes||[]).reduce((acc,group)=>{(acc[group.centre]||(acc[group.centre]=[])).push(group);return acc;},{});
      const options=Object.entries(groupsByCentre).map(([centre,groups])=>`<optgroup label="${escapeHtml(centre)}">${groups.map(group=>`<option value="${group.evenement_id}">${escapeHtml(group.groupe)}</option>`).join("")}</optgroup>`).join("");
      body.innerHTML=`<div class="full sortie-responsibility-assignment"><p>Ces responsables n’étaient pas affectés au Planning le jour de la sortie. Choisissez leur lieu et leur groupe.</p>${nonAffectes.map(person=>`<label>${escapeHtml(person.nom)}<select name="assignment-${person.id}" required><option value="">Choisir un lieu et un groupe…</option>${options}</select></label>`).join("")}</div>`;
      return;
    }
  }
  else if(current==="responsable_suppressions"){
    pendingRemovedAssignments=[];
    for(const [key,value] of fd){
      if(key.startsWith("remove-")&&value==="yes") pendingRemovedAssignments.push(Number(key.replace("remove-","")));
    }
    if(pendingNewAssignments.length){
      current="responsable_affectations";
      document.getElementById("editor-title").textContent="Affecter les nouveaux responsables";
      const groupsByCentre=(data.groupes||[]).reduce((acc,group)=>{(acc[group.centre]||(acc[group.centre]=[])).push(group);return acc;},{});
      const options=Object.entries(groupsByCentre).map(([centre,groups])=>`<optgroup label="${escapeHtml(centre)}">${groups.map(group=>`<option value="${group.evenement_id}">${escapeHtml(group.groupe)}</option>`).join("")}</optgroup>`).join("");
      body.innerHTML=`<div class="full sortie-responsibility-assignment"><p>Ces responsables n’étaient pas affectés au Planning le jour de la sortie. Choisissez leur lieu et leur groupe.</p>${pendingNewAssignments.map(person=>`<label>${escapeHtml(person.nom)}<select name="assignment-${person.id}" required><option value="">Choisir un lieu et un groupe…</option>${options}</select></label>`).join("")}</div>`;
      return;
    }
    payload.responsabilites=pendingResponsibilities||[];
    payload.supprimer_affectations_responsables=pendingRemovedAssignments;
  }
  else if(current==="responsable_affectations"){
    payload.responsabilites=pendingResponsibilities||[];
    payload.supprimer_affectations_responsables=pendingRemovedAssignments;
    payload.affectations_responsables={};
    for(const [key,value] of fd){
      if(key.startsWith("assignment-")) payload.affectations_responsables[key.replace("assignment-","")]=Number(value);
    }
  }
  else if(current==="repartition"){
    payload.activites={};
    for(const [key,value] of fd) payload.activites[key.replace("activity-","")]=value;
  }else if(current==="liens") payload.liens=String(fd.get("liens")||"").split("\n").map(row=>{const [libelle,...url]=row.split("|");return {libelle:libelle?.trim(),url:url.join("|").trim()}}).filter(item=>item.libelle&&item.url);
  else for(const [key,value] of fd) payload[key]=value;

  try{
    data=await apiFetch(`/api/sorties/${id}/`,{method:"PATCH",body:JSON.stringify(payload)});
    pendingResponsibilities=null;
    pendingRemovedAssignments=[];
    pendingNewAssignments=[];
    dialog.close();
    render();
    if(current==="meteo") loadWeather();
  }catch(err){
    const el=form.querySelector(".form-error");
    el.textContent=erreurMessage(err,"Enregistrement impossible.");
    el.hidden=false;
  }
});

document.getElementById("edit-sortie-main").addEventListener("click",()=>open("general","Informations générales"));
document.getElementById("delete-sortie").addEventListener("click",async()=>{if(!confirm(`Supprimer la sortie « ${data.nom} » ?`)) return;await apiFetch(`/api/sorties/${id}/`,{method:"DELETE"});location.href="/sorties/"});
load().catch(err=>{blocks.innerHTML=`<p class="empty-note">${text(erreurMessage(err,"Chargement impossible."))}</p>`});
})();
