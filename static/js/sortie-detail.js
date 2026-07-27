(function(){
"use strict";
const root=document.getElementById("sortie-detail"),blocks=document.getElementById("sortie-blocks"),dialog=document.getElementById("sortie-editor"),form=document.getElementById("sortie-editor-form"),body=document.getElementById("editor-body");
const assignmentDialog=document.getElementById("sortie-assignment-dialog"),assignmentForm=document.getElementById("sortie-assignment-form"),supportRemoval=document.getElementById("sortie-support-removal");
const id=root.dataset.sortieId;
let data,current,weather=null,pendingResponsibilities=null,pendingRemovedAssignments=[],pendingNewAssignments=[],pendingAssignment=null,pendingSupportRemoval=null;

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

function splitGroups(groups){
  const categoryBuckets={maternelle:"maternels",elementaire:"elementaires",autre:"autres"};
  return (groups||[]).reduce((acc,group)=>{
    // La catégorie est calculée par le service métier Python. Le navigateur
    // ne réinterprète jamais le nom affiché du groupe ou de son centre.
    const key=categoryBuckets[group.categorie_age]||"autres";
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

// La répartition opérationnelle se lit par lieu : les groupes, effectifs et
// salariés d'un même centre sont réunis sur une seule ligne.
function locationRows(groups){
  return (groups||[]).map(group=>({
    centre:group.centre,
    centreId:group.centre_id,
    group,
    children:Number(group.effectif)||0,
    staff:group.animateurs||[],
    coverageStaff:dedupeById([...(group.animateurs||[]),...(group.flottants_mobilises||[])]),
  }));
}

function formatRatio(value){
  return Number(value).toLocaleString("fr-FR",{maximumFractionDigits:2});
}
function ratioEditButton(row){
  return `<button class="sortie-ratio-edit-trigger" type="button" data-edit-group-ratio="${row.group.evenement_id}" data-current-ratio="${row.group.ratio}" data-default-ratio="${row.group.ratio_defaut}" data-exceptional-ratio="${row.group.ratio_exceptionnel??""}" title="Cliquer pour modifier. Videz la valeur pour revenir au taux du groupe 1/${row.group.ratio_defaut}"><span aria-hidden="true">✎</span> Requis 1/${row.group.ratio}</button>`;
}
function coverageDetails(row){
  const staffCount=row.coverageStaff.length;
  const actual=staffCount
    ? `1/${formatRatio(row.children/staffCount)}`
    : "—";
  const missing=Number(row.group.non_couverts)||0;
  const state=missing?"Insuffisant":"Conforme";
  return `<div class="sortie-coverage-badges" aria-label="Taux d’encadrement">
    ${ratioEditButton(row)}
    <span class="sortie-ratio-real-badge ${missing?"is-danger":"is-ok"}" title="Taux réel ${actual} · Taux requis 1/${row.group.ratio} · ${state}" aria-label="Taux réel ${actual}, ${state.toLowerCase()}">Réel ${actual}</span>
  </div>`;
}

function bindRatioEditors(){
  blocks.querySelectorAll("[data-edit-group-ratio]").forEach(button=>button.addEventListener("click",event=>{
    event.preventDefault();
    event.stopPropagation();
    document.querySelector(".sortie-ratio-inline-editor input")?.blur();

    const groupId=Number(button.dataset.editGroupRatio);
    const currentRatio=Number(button.dataset.currentRatio);
    const defaultRatio=Number(button.dataset.defaultRatio);
    const editor=document.createElement("span");
    editor.className="sortie-ratio-inline-editor";
    editor.innerHTML=`<span>Requis 1/</span><input type="number" min="1" max="999" step="1" inputmode="numeric" value="${currentRatio}" aria-label="Modifier le taux d’encadrement requis" title="Videz la valeur pour revenir au taux par défaut 1/${defaultRatio}">`;
    button.hidden=true;
    button.insertAdjacentElement("afterend",editor);
    const input=editor.querySelector("input");
    let finished=false,saving=false;

    const restore=()=>{
      if(finished)return;
      finished=true;
      editor.remove();
      button.hidden=false;
    };
    const save=async()=>{
      if(finished||saving)return;
      const raw=input.value.trim();
      const ratio=raw===""?null:Number(raw);
      if(ratio!==null&&(!Number.isInteger(ratio)||ratio<1||ratio>999)){
        editor.classList.add("is-error");
        editor.title="Le taux doit être compris entre 1 et 999.";
        input.focus();
        return;
      }
      if((ratio===null&&button.dataset.exceptionalRatio==="")||ratio===currentRatio){restore();return}
      saving=true;
      editor.classList.add("is-saving");
      input.disabled=true;
      try{
        await apiFetch(`/api/groupes/${groupId}/effectifs-enfants/`,{
          method:"POST",
          body:JSON.stringify({ratios_encadrement:[{date:data.date,ratio}]})
        });
        finished=true;
        data=await apiFetch(`/api/sorties/${id}/`);
        render();
      }catch(error){
        saving=false;
        input.disabled=false;
        editor.classList.remove("is-saving");
        editor.classList.add("is-error");
        editor.title=erreurMessage(error,"Le taux n’a pas pu être enregistré.");
        input.focus();
      }
    };
    input.addEventListener("keydown",event=>{
      if(event.key==="Enter"){event.preventDefault();save()}
      if(event.key==="Escape"){event.preventDefault();restore()}
    });
    input.addEventListener("blur",save);
    input.focus();
    input.select();
  }));
}

const availableAnimators=()=>data.animateurs_supplementaires||[];
function supportAnimatorOptions(){
  const items=availableAnimators();
  return `<option value="">Choisir…</option>${items.map(person=>`<option value="${person.id}">${escapeHtml(person.nom)} — ${escapeHtml(staffStatusName(person))}</option>`).join("")}`;
}

function assignmentGroups(centreId){
  return (data.groupes||[]).filter(group=>String(group.centre_id)===String(centreId));
}
function fillAssignmentGroups(selectedId=null){
  const centre=assignmentForm.querySelector("[data-assignment-centre]").value;
  const select=assignmentForm.querySelector("[data-assignment-group]");
  select.innerHTML=assignmentGroups(centre).map(group=>`<option value="${group.evenement_id}">${escapeHtml(group.groupe)}</option>`).join("");
  if(selectedId!=null) select.value=String(selectedId);
}
function bindAssignmentActions(){
  blocks.querySelectorAll("[data-add-assignment]").forEach(button=>button.addEventListener("click",()=>{
    const select=button.parentElement.querySelector("[data-extra-animator]");
    const person=(data.catalogue_animateurs||[]).find(item=>String(item.id)===select.value);
    if(!person) return;
    pendingAssignment={animateurId:person.id};
    assignmentForm.querySelector("[data-assignment-name]").textContent=person.nom;
    assignmentForm.querySelector("[data-assignment-date]").textContent=formatDateHeader(data.date).full;
    const centres=[...new Map((data.groupes||[]).map(group=>[String(group.centre_id),group.centre])).entries()];
    const centreSelect=assignmentForm.querySelector("[data-assignment-centre]");
    centreSelect.innerHTML=centres.map(([centreId,nom])=>`<option value="${centreId}">${escapeHtml(nom)}</option>`).join("");
    centreSelect.value=String(button.dataset.centreId||centres[0]?.[0]||"");
    fillAssignmentGroups(button.dataset.groupId||null);
    assignmentForm.querySelector(".form-error").hidden=true;
    assignmentDialog.showModal();
  }));
  blocks.querySelectorAll("[data-remove-support]").forEach(button=>button.addEventListener("click",()=>{
    pendingSupportRemoval=button.dataset.removeSupport;
    supportRemoval.querySelector(".form-error").hidden=true;
    supportRemoval.showModal();
  }));
}

function renderSupports(){
  const supports=data.renforts||[];
  return `<div class="sortie-support-add"><select data-extra-animator aria-label="Animateur disponible">${supportAnimatorOptions()}</select><button type="button" class="btn btn-secondary" data-add-assignment ${availableAnimators().length?"":"disabled"}>Ajouter</button></div>
    <div class="sortie-support-list">${supports.length?supports.map(item=>`<article style="${staffVars(item.animateur)}"><span><strong>${escapeHtml(item.animateur.nom)}</strong><small>${escapeHtml(item.centre.nom)} — ${escapeHtml(item.groupe.nom)}</small></span><button type="button" data-remove-support="${item.id}" aria-label="Retirer ${escapeHtml(item.animateur.nom)}">×</button></article>`).join(""):'<p class="sortie-muted">Aucun renfort ajouté.</p>'}</div>`;
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

function teamFor(group){return group.animateurs&&group.animateurs.length?escapeHtml(group.animateurs.map(item=>item.nom).join(" · ")):'<span class="sortie-muted">Aucun animateur</span>';}
function groupCountLabel(groups){return `${(groups||[]).length} groupe${(groups||[]).length>1?"s":""}`;}

function transportCircuit(t,sens){
  const etapes=t.circuits?.[sens]||[];
  if(etapes.length||sens==="aller") return etapes;
  return [...(t.circuits?.aller||[])].reverse();
}
function transportRoute(etapes){
  return etapes.length?`<p class="sortie-transport-route">${etapes.map(item=>escapeHtml(item.nom)).join(" <span aria-hidden=\"true\">→</span> ")}</p>`:'<p class="sortie-transport-missing">Circuit de ramassage à compléter</p>';
}
function transportLine(label,value){
  return timeValue(value)?`<p class="sortie-transport-time"><strong>${label} :</strong> ${timeValue(value)}</p>`:"";
}
function transportModeSummary(t){
  if(!t.mode_transport) return '<p class="sortie-transport-missing">Mode de transport à compléter</p>';
  const avecVehicules=["Car","Minibus"].includes(t.mode_transport)&&t.nombre_vehicules;
  const vehicules=avecVehicules?` · ${plural(t.nombre_vehicules,t.mode_transport==="Car"?"car":"minibus",t.mode_transport==="Car"?"cars":"minibus")}`:"";
  return `<p class="sortie-transport-mode"><strong>${escapeHtml(t.mode_transport)}</strong>${vehicules}</p>`;
}
function transportSourceNote(source){
  if(source==="automatique") return '<small class="sortie-transport-source">Estimation automatique</small>';
  if(source==="manuelle") return '<small class="sortie-transport-source is-manual">Heure ajustée manuellement</small>';
  return "";
}
function formatMinutes(value){
  const minutes=Number(value)||0,hours=Math.floor(minutes/60),remaining=minutes%60;
  return hours?`${hours} h${remaining?` ${String(remaining).padStart(2,"0")}`:""}`:`${remaining} min`;
}
function transportCalculationMarkup(result){
  return `<div class="sortie-route-calculation"><span>Durée routière : <strong>${formatMinutes(result.route_duration_minutes)}</strong></span><span>Arrêts : <strong>${result.stop_count} × ${result.stop_minutes_per_site} min = ${result.stop_duration_minutes} min</strong></span><span>Durée totale estimée : <strong>${formatMinutes(result.total_duration_minutes)}</strong></span><span>Arrivée estimée : <strong>${escapeHtml(result.estimated_arrival)}</strong></span><small>${result.precision==="precise"?"Estimation précise":"Estimation approximative basée sur le code postal ou la commune"} · ${escapeHtml(result.source||"Géoplateforme IGN · BD TOPO")}</small></div>`;
}
function destinationMarkup(destination){
  const item=destination||{};
  const locality=[item.code_postal,item.commune].filter(Boolean).map(escapeHtml).join(" ");
  return `<span class="sortie-destination-name">${escapeHtml(item.nom||data.destination)}</span>${item.adresse?`<span>${escapeHtml(item.adresse)}</span>`:""}${locality?`<span>${locality}</span>`:""}`;
}

function weatherSummary(compact=false){
  const compactClass=compact?' sortie-weather-summary--compact':'';
  if(!data.meteo_lieu?.latitude) return '<p class="sortie-weather-empty"><strong>Météo indisponible</strong><small>Lieu à définir</small></p>';
  if(!weather) return '<p class="sortie-weather-empty"><strong>Chargement…</strong></p>';
  if(weather.statut!=="prevision") return `<p class="sortie-weather-empty"><strong>Météo indisponible</strong>${weather.message?`<small>${escapeHtml(weather.message)}</small>`:""}</p>`;
  const r=weather.resume,c=weather.conditions;
  if(compact) return `<div class="sortie-weather-summary${compactClass}"><span class="sortie-weather-icon">${c.pictogramme}</span><div><strong>${escapeHtml(c.libelle)}</strong><b>${r.temperature_min} à ${r.temperature_max} °C</b><small>${r.precipitations_mm} mm · Rafales ${r.rafales_max_kmh} km/h${r.uv_max!=null?` · UV ${r.uv_max}`:""}</small></div></div>`;
  return `<div class="sortie-weather-summary"><span class="sortie-weather-icon">${c.pictogramme}</span><div><strong>${escapeHtml(c.libelle)}</strong><b>${r.temperature_min} à ${r.temperature_max} °C</b></div><dl><div><dt>Pluie</dt><dd>${r.precipitations_mm} mm</dd></div><div><dt>Rafales</dt><dd>${r.rafales_max_kmh} km/h</dd></div><div><dt>UV</dt><dd>${r.uv_max}</dd></div></dl><small>${escapeHtml(weather.source_libelle)} · ${new Date(weather.mis_a_jour_le).toLocaleTimeString("fr-FR",{hour:"numeric",minute:"2-digit"})}</small></div>`;
}
async function loadWeather(force=false){
  if(!data.meteo_lieu?.latitude){weather=null;render();return}
  try{weather=await apiFetch(`/api/sorties/${id}/meteo/${force?"?forcer=1":""}`)}catch(error){weather={statut:"erreur",message:erreurMessage(error,"Météo momentanément indisponible")}}
  render();
}
async function load(){data=await apiFetch(`/api/sorties/${id}/`);render();loadWeather()}

function completionControlsMarkup(){
  const controls=data.controles_completion||[];
  return `<article class="sortie-summary-completion" aria-label="Contrôle de complétude de la sortie">
    <span>Contrôle de la sortie</span>
    <div class="sortie-completion-list">${controls.map(item=>`<div class="sortie-completion-item ${item.ok?"is-ok":"is-warning"}">
      <span class="sortie-completion-icon sortie-completion-icon--${item.ok?"ok":"warning"}" aria-hidden="true">${item.ok?"✓":"!"}</span>
      <span>${escapeHtml(item.libelle)}</span>
    </div>`).join("")}</div>
  </article>`;
}

async function refreshDestinationCalculations(){
  weather=null;
  render();
  const calculations=[];
  if(data.meteo_lieu?.latitude){
    calculations.push(
      apiFetch(`/api/sorties/${id}/meteo/?forcer=1`)
        .then(result=>{weather=result})
        .catch(error=>{weather={statut:"erreur",message:erreurMessage(error,"Météo momentanément indisponible")}})
    );
  }
  if(data.transport?.estimation_disponible!==false){
    for(const [sens,departureField,arrivalField,sourceField] of [
      ["aller","heure_depart","heure_arrivee","source_heure_arrivee"],
      ["retour","heure_retour","heure_arrivee_retour","source_heure_arrivee_retour"],
    ]){
      // Un horaire ajusté par la direction reste prioritaire sur le recalcul automatique.
      if(!data.transport[departureField]||data.transport[sourceField]==="manuelle") continue;
      calculations.push(
        apiFetch(`/api/sorties/${id}/estimation-trajet/`,{method:"POST",body:JSON.stringify({sens})})
          .then(result=>{
            data.transport[arrivalField]=result.estimated_arrival;
            data.transport[sourceField]="automatique";
          })
          // La destination reste enregistrée même si le service d'itinéraire est indisponible.
          .catch(()=>{})
      );
    }
  }
  await Promise.all(calculations);
  render();
}

function render(){
  const dateParts=formatDateHeader(data.date);
  const buckets=splitGroups(data.groupes||[]);
  const maternalStats=bucketStats(buckets.maternels);
  const elementaryStats=bucketStats(buckets.elementaires);
  const otherStats=bucketStats(buckets.autres);
  const totalChildren=(data.totaux&&data.totaux.enfants)||0;
  const totalAnimators=(data.totaux&&data.totaux.animateurs)||0;
  const repartitionRows=locationRows(data.groupes||[]);
  const categoryTotals=data.totaux?.categories||{};
  const maternalTotal=categoryTotals.maternelle||{enfants:0,animateurs:0};
  const elementaryTotal=categoryTotals.elementaire||{enfants:0,animateurs:0};
  const locationCodes=(data.totaux?.lieux||[]).map(item=>item.code||item.nom);
  const transportLabel=data.transport.nombre_vehicules?`${data.transport.nombre_vehicules} ${data.transport.mode_transport||"véhicule(s)"}`:(data.transport.mode_transport||"À compléter");
  // La présence des cartes d'âge dépend des groupes, et non de leur effectif :
  // un groupe concerné reste utile à afficher même si son effectif vaut zéro.
  const locationCard=locationCodes.length?`<article class="sortie-summary-locations is-clickable" data-block="participants" tabindex="0" role="button"><span>Lieux concernés</span><strong>${locationCodes.map(escapeHtml).join(" · ")}</strong></article>`:"";
  const effectifRows=[
    buckets.maternels.length?`<div><span>Maternelles</span><strong>${plural(maternalTotal.enfants,"enfant")} + ${plural(maternalTotal.animateurs,"animateur")}</strong></div>`:"",
    buckets.elementaires.length?`<div><span>Élémentaires</span><strong>${plural(elementaryTotal.enfants,"enfant")} + ${plural(elementaryTotal.animateurs,"animateur")}</strong></div>`:"",
    `<div class="sortie-effectifs-total"><span>Total</span><strong>${plural(totalChildren,"enfant")} + ${plural(totalAnimators,"animateur")}</strong></div>`,
  ].join("");
  const effectifsCard=`<article class="sortie-summary-effectifs is-clickable" data-block="participants" tabindex="0" role="button"><span>Effectifs</span><div class="sortie-effectifs-lines">${effectifRows}</div></article>`;
  const transportCard=`<article class="sortie-summary-transport is-clickable" data-block="participants" tabindex="0" role="button"><span>Transport</span><strong>${escapeHtml(transportLabel)}</strong></article>`;
  const floatingNotes=(data.flottants_par_centre||[]).map(item=>`${item.centre} : ${item.animateurs.map(anim=>anim.nom).join(" · ")}`).join("<br>");

  document.getElementById("sortie-title").textContent=data.nom;
  document.getElementById("sortie-subtitle").textContent=dateParts.full;

  blocks.innerHTML=`
    <div class="sortie-document">
      <section class="sortie-sheet-page">
        <div class="sortie-sheet-top is-clickable" data-block="general" tabindex="0" role="button">
          <div class="sortie-sheet-title">
            <span>Fiche de sortie</span>
            <div class="sortie-sheet-heading-row">
              <div class="sortie-sheet-identity">
                <h2>${escapeHtml(data.nom)}</h2>
                <span class="sortie-sheet-separator" aria-hidden="true">—</span>
                <p class="sortie-sheet-address">${destinationMarkup(data.destination_details)}</p>
              </div>
              <div class="sortie-title-weather is-clickable" data-block="meteo" tabindex="0" role="button" aria-label="Voir les détails météo">
                ${weatherSummary(true)}
              </div>
            </div>
          </div>
          <div class="sortie-sheet-date">
            <span>${dateParts.weekday}</span>
            <strong>${dateParts.dayMonth}</strong>
            <small>${dateParts.year}</small>
          </div>
        </div>

        <div class="sortie-stats-band">
          ${locationCard}${effectifsCard}${transportCard}${completionControlsMarkup()}
        </div>

        <div class="sortie-team-management">
          <section class="sortie-section is-clickable" data-block="responsables" tabindex="0" role="button"><header><h3>Responsables et contacts</h3><span class="sortie-edit-chip">Modifier</span></header><div class="sortie-responsables-grid">${renderResponsibilities()}</div></section>
          <section class="sortie-section sortie-supports"><header><h3>Renforts animateurs</h3></header>${renderSupports()}</section>
        </div>

        <section class="sortie-section is-clickable" data-block="transport" tabindex="0" role="button">
          <header><h3>Transport</h3><span class="sortie-edit-chip">Modifier</span></header>
          ${transportModeSummary(data.transport)}
          <div class="sortie-transport-grid">
            <article>
              <h4>Aller</h4>
              ${transportLine("Départ du premier site",data.transport.heure_depart)}
              ${transportRoute(transportCircuit(data.transport,"aller"))}
              ${transportLine("Arrivée estimée à destination",data.transport.heure_arrivee)}
              ${transportSourceNote(data.transport.source_heure_arrivee)}
            </article>
            <article>
              <h4>Retour</h4>
              ${transportLine("Départ du lieu de sortie",data.transport.heure_retour)}
              ${transportRoute(transportCircuit(data.transport,"retour"))}
              ${transportLine("Arrivée estimée au dernier site",data.transport.heure_arrivee_retour)}
              ${transportSourceNote(data.transport.source_heure_arrivee_retour)}
            </article>
          </div>
          ${floatingNotes?`<p class="sortie-floating-note"><strong>Animateurs flottants :</strong><br>${floatingNotes}</p>`:""}
        </section>

        <section class="sortie-section">
          <header><h3>Répartition des groupes</h3></header>
          <div class="sortie-table-wrap sortie-repartition-wrap">
            <table class="sortie-sheet-table sortie-repartition-table">
              <thead>
                <tr><th>Groupe et effectifs</th><th>Taux d’encadrement</th><th>Animateurs affectés</th></tr>
              </thead>
              <tbody>
                ${repartitionRows.map(row=>`<tr>
                  <td data-label="Groupe et effectifs">
                    <div class="sortie-repartition-heading">
                      <strong class="sortie-repartition-name"><span>${escapeHtml(row.group.centre_code||row.centre)}</span><i aria-hidden="true">·</i><span>${escapeHtml(row.group.groupe)}</span></strong>
                    </div>
                    <span class="sortie-effectifs-text">${plural(row.children,"enfant")} + ${plural(row.coverageStaff.length,"animateur")}</span>
                  </td>
                  <td data-label="Taux d’encadrement">${coverageDetails(row)}</td>
                  <td data-label="Animateurs affectés"><div class="sortie-assigned-staff">${row.staff.length?row.staff.map(person=>`<span class="sortie-staff-pill" style="${staffVars(person)}"><strong>${escapeHtml(person.nom)}</strong><small>· ${escapeHtml(staffStatusName(person))}</small></span>`).join(""):'<span class="sortie-muted">Aucun animateur affecté</span>'}</div></td>
                </tr>`).join("")}
              </tbody>
            </table>
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
      event.stopPropagation();
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
  bindAssignmentActions();
  bindRatioEditors();
}

function input(name,label,value="",type="text"){return `<label>${label}<input name="${name}" type="${type}" value="${escapeHtml(value??"")}"></label>`}

function destinationEditorMarkup(){
  const destination=data.destination_details||{};
  return `${input("nom","Nom de la sortie",data.nom)}${input("date","Date",data.date,"date")}<div class="full sortie-location-fields" data-location-autocomplete><label class="full">Nom du lieu ou de la destination<input name="destination" required maxlength="180" value="${escapeHtml(destination.nom||data.destination)}"></label><div class="sortie-location-locality"><label>Code postal<input name="destination_code_postal" data-location-postal maxlength="5" inputmode="numeric" pattern="[0-9]{5}" value="${escapeHtml(destination.code_postal||"")}"></label><label>Commune<input name="destination_commune" data-location-city maxlength="120" value="${escapeHtml(destination.commune||"")}"></label></div><div class="sortie-location-suggestions" data-location-suggestions role="listbox" hidden></div><small class="sortie-location-status" data-location-status aria-live="polite"></small><label class="full">Adresse ou lieu-dit <small>(facultatif)</small><input name="destination_adresse" maxlength="240" value="${escapeHtml(destination.adresse||"")}"></label><input type="hidden" name="destination_code_insee" data-location-insee value="${escapeHtml(destination.code_insee||"")}"><input type="hidden" name="destination_localisation_demandee" data-location-requested value="1"></div>`;
}

function transportCircuitEditor(sens,titre,etapes){
  return `<section class="sortie-transport-trip"><h4>${titre}</h4><ol class="sortie-transport-stops" data-transport-circuit="${sens}">${etapes.map(item=>`<li data-centre-id="${item.centre_id}"><button class="sortie-transport-drag" type="button" draggable="true" aria-label="Déplacer ${escapeHtml(item.nom)}" title="Glisser pour déplacer">⠿</button><span class="sortie-transport-stop-number"></span><span class="sortie-transport-stop-location"><strong>${escapeHtml(item.nom)}</strong><small>${item.code_postal?`${escapeHtml(item.code_postal)} ${escapeHtml(item.commune||"")}`:"Code postal manquant"}</small><em class="${item.localisation_disponible?"is-ready":"is-missing"}">${item.localisation_disponible?(item.precision==="adresse"?"Adresse localisée":"Localisation disponible"):"Localisation à compléter"}</em></span></li>`).join("")}</ol>${etapes.length?"":'<p class="sortie-transport-missing">Aucun lieu concerné par cette sortie</p>'}</section>`;
}

function destinationTransportStatus(){
  const destination=data.destination_details||{};
  const locality=[destination.code_postal,destination.commune].filter(Boolean).map(escapeHtml).join(" ");
  const ready=destination.latitude!=null&&destination.longitude!=null;
  return `<div class="sortie-transport-destination"><strong>${escapeHtml(destination.nom||data.destination)}</strong><small>${locality||"Code postal manquant"}</small><em class="${ready?"is-ready":"is-missing"}">${ready?(destination.precision==="adresse"?"Adresse localisée":"Localisation disponible"):"Destination à localiser"}</em></div>`;
}

function updateTransportStopNumbers(container){
  container.querySelectorAll("li").forEach((item,index)=>{item.querySelector(".sortie-transport-stop-number").textContent=`${index+1}.`});
}

function bindTransportCircuit(container){
  let dragged=null;
  updateTransportStopNumbers(container);
  container.querySelectorAll("li").forEach(item=>{
    const handle=item.querySelector(".sortie-transport-drag");
    handle.addEventListener("dragstart",event=>{
      dragged=item;item.classList.add("is-dragging");event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("text/plain",item.dataset.centreId);
    });
    item.addEventListener("dragend",()=>{item.classList.remove("is-dragging");dragged=null;updateTransportStopNumbers(container)});
  });
  container.addEventListener("dragover",event=>{
    if(!dragged)return;
    event.preventDefault();
    const target=event.target.closest("li");
    if(!target||target===dragged||target.parentElement!==container)return;
    const rect=target.getBoundingClientRect();
    container.insertBefore(dragged,event.clientY>rect.top+rect.height/2?target.nextSibling:target);
    updateTransportStopNumbers(container);
  });
}

function open(key,title){
  if(key==="vigilances")return;
  current=key;
  dialog.classList.toggle("sortie-dialog--transport",key==="transport");
  document.getElementById("editor-title").textContent=title;
  form.querySelector(".form-error").hidden=true;
  form.querySelector(".form-error").textContent="";
  if(key==="general"){
    body.innerHTML=destinationEditorMarkup();
    initLocationAutocomplete(body.querySelector("[data-location-autocomplete]"));
  }else if(key==="participants"){
    const groupsByCentre=(data.catalogue_groupes||[]).reduce((acc,group)=>{(acc[group.centre]||(acc[group.centre]=[])).push(group);return acc;},{});
    const chosen=new Set((data.groupes||[]).map(group=>group.evenement_id));
    body.innerHTML=`<div class="full">${Object.entries(groupsByCentre).map(([centre,groups])=>`<label class="group-centre group-choice"><input type="checkbox" data-select-centre><span>${escapeHtml(centre)} — tous les groupes</span></label>${groups.map(group=>`<label class="group-choice${group.ouvert?"":" is-closed"}"><input type="checkbox" name="groupes" value="${group.id}" ${chosen.has(group.id)?"checked":""} ${group.ouvert?"":"disabled"}><span>${escapeHtml(group.nom)}</span>${group.ouvert?"":"<small>fermé ce jour</small>"}</label>`).join("")}`).join("")}</div>`;
    body.querySelectorAll("[data-select-centre]").forEach(toggle=>toggle.addEventListener("change",()=>{let row=toggle.parentElement.nextElementSibling;while(row&&row.classList.contains("group-choice")&&!row.classList.contains("group-centre")){const checkbox=row.querySelector("input[name='groupes']");if(checkbox&&!checkbox.disabled) checkbox.checked=toggle.checked;row=row.nextElementSibling}}));
  }else if(key==="responsables"){
    openResponsibilitiesEditor();
  }else if(key==="transport"){
    const t=data.transport;
    const selectedMode=t.mode_transport||t.mode_transport_suggere||"";
    const modes=["Car","Minibus","Ligne régulière","Transport en commun"];
    const aller=transportCircuit(t,"aller"),retour=transportCircuit(t,"retour");
    const unavailable=t.estimation_disponible===false?'<p class="sortie-estimation-unavailable">Estimation automatique indisponible. L’heure peut être renseignée manuellement.</p>':"";
    body.innerHTML=`<div class="full sortie-transport-editor"><fieldset class="sortie-transport-modes"><legend>Mode de transport</legend><div>${modes.map(mode=>`<label><input type="radio" name="mode_transport" value="${escapeHtml(mode)}" ${selectedMode===mode?"checked":""}><span>${escapeHtml(mode)}</span></label>`).join("")}</div></fieldset><div class="sortie-transport-settings"><label class="sortie-vehicle-count">Nombre de véhicules<input name="nombre_vehicules" type="number" min="1" max="32767" value="${escapeHtml(t.nombre_vehicules??"")}"></label><label>Temps d’arrêt par site<input name="temps_arret_par_site" type="number" min="0" max="60" required value="${escapeHtml(t.temps_arret_par_site??10)}"></label></div>${unavailable}<div class="sortie-transport-journeys"><section class="sortie-transport-trip"><h3>Trajet aller</h3><label>Départ du premier site<input name="heure_depart" type="time" value="${escapeHtml(t.heure_depart)}"></label>${transportCircuitEditor("aller","Ordre de ramassage",aller)}<label>Arrivée estimée à destination<input name="heure_arrivee" type="time" value="${escapeHtml(t.heure_arrivee)}"><small data-arrival-source="aller">${t.source_heure_arrivee==="automatique"?"Estimation automatique":t.source_heure_arrivee==="manuelle"?"Heure ajustée manuellement":""}</small></label><button class="btn btn-ghost sortie-estimate-button" type="button" data-estimate-route="aller" ${t.estimation_disponible===false?"disabled":""}>Estimer l’heure d’arrivée</button><div data-route-calculation="aller"></div></section><section class="sortie-transport-trip"><h3>Trajet retour</h3><label>Départ du lieu de sortie<input name="heure_retour" type="time" value="${escapeHtml(t.heure_retour)}"></label>${transportCircuitEditor("retour","Ordre de dépose",retour)}<label>Arrivée estimée au dernier site<input name="heure_arrivee_retour" type="time" value="${escapeHtml(t.heure_arrivee_retour)}"><small data-arrival-source="retour">${t.source_heure_arrivee_retour==="automatique"?"Estimation automatique":t.source_heure_arrivee_retour==="manuelle"?"Heure ajustée manuellement":""}</small></label><button class="btn btn-ghost sortie-estimate-button" type="button" data-estimate-route="retour" ${t.estimation_disponible===false?"disabled":""}>Estimer l’arrivée au dernier site</button><div data-route-calculation="retour"></div></section></div></div>`;
    body.querySelector(".sortie-transport-editor").insertAdjacentHTML("afterbegin",destinationTransportStatus());
    const vehicleField=body.querySelector(".sortie-vehicle-count"),vehicleInput=vehicleField.querySelector("input");
    const updateMode=()=>{
      const mode=body.querySelector('[name="mode_transport"]:checked')?.value||"";
      const visible=["Car","Minibus"].includes(mode);
      vehicleField.hidden=!visible;vehicleInput.disabled=!visible;
      vehicleField.firstChild.textContent=mode==="Car"?"Nombre de cars":"Nombre de minibus";
    };
    body.querySelectorAll('[name="mode_transport"]').forEach(input=>input.addEventListener("change",updateMode));
    body.querySelectorAll("[data-transport-circuit]").forEach(bindTransportCircuit);
    for(const [sens,name] of [["aller","heure_arrivee"],["retour","heure_arrivee_retour"]]){
      body.querySelector(`[name="${name}"]`).addEventListener("input",()=>{
        body.querySelector(`[data-arrival-source="${sens}"]`).textContent="Heure ajustée manuellement";
      });
    }
    body.querySelectorAll("[data-estimate-route]").forEach(button=>button.addEventListener("click",()=>estimateTransportRoute(button.dataset.estimateRoute,button)));
    updateMode();
  }else if(key==="meteo"){
    const details=weather?.statut==="prevision"?`<section class="sortie-weather-detail"><div>${weatherSummary()}</div>${weather.alertes?.length?`<ul>${weather.alertes.map(item=>`<li>Point de vigilance météo : ${escapeHtml(item)}</li>`).join("")}</ul>`:""}<button type="button" class="btn btn-ghost" data-weather-refresh>Actualiser</button><div class="sortie-weather-hours"><table><thead><tr><th>Heure</th><th></th><th>Temp.</th><th>Pluie</th><th>Vent</th><th>Rafales</th></tr></thead><tbody>${weather.heures.map(item=>`<tr><td>${item.heure}</td><td>${item.pictogramme}</td><td>${item.temperature} °C</td><td>${item.precipitations_mm} mm</td><td>${item.vent_kmh}</td><td>${item.rafales_kmh}</td></tr>`).join("")}</tbody></table></div></section>`:"";
    body.innerHTML=`<div class="full sortie-weather-editor">${details||weatherSummary()}<p class="sortie-muted">La météo utilise automatiquement la destination de la sortie. Modifiez les informations générales pour changer le lieu.</p>${weather?.statut==="prevision"?"":'<button type="button" class="btn btn-ghost" data-weather-refresh>Réessayer</button>'}</div>`;
    body.querySelector("[data-weather-refresh]")?.addEventListener("click",async()=>{weather=null;dialog.close();render();await loadWeather(true)});
  }else if(key==="liens"){
    body.innerHTML=`<label class="full links-editor">Liens — une ligne par lien, sous la forme Libellé | URL<textarea name="liens">${(data.liens||[]).map(item=>`${item.libelle} | ${item.url}`).join("\n")}</textarea></label>`
  }else {
    body.innerHTML=`<label class="full"><textarea name="${key}" rows="10">${escapeHtml(data.textes[key]||"")}</textarea></label>`
  }
  dialog.showModal();
}

function transportPayload(){
  const fd=new FormData(form),payload={};
  for(const [key,value] of fd) payload[key]=value;
  payload.circuit_aller=[...body.querySelectorAll('[data-transport-circuit="aller"] li')].map(item=>Number(item.dataset.centreId));
  payload.circuit_retour=[...body.querySelectorAll('[data-transport-circuit="retour"] li')].map(item=>Number(item.dataset.centreId));
  return payload;
}

async function estimateTransportRoute(sens,button){
  const source=data.transport[sens==="aller"?"source_heure_arrivee":"source_heure_arrivee_retour"];
  const sourceLabel=body.querySelector(`[data-arrival-source="${sens}"]`)?.textContent;
  if((source==="manuelle"||sourceLabel==="Heure ajustée manuellement")&&!confirm("Cette heure a été ajustée manuellement. Souhaitez-vous la remplacer par une nouvelle estimation ?")) return;
  const error=form.querySelector(".form-error");error.hidden=true;button.disabled=true;
  try{
    data=await apiFetch(`/api/sorties/${id}/`,{method:"PATCH",body:JSON.stringify(transportPayload())});
    const result=await apiFetch(`/api/sorties/${id}/estimation-trajet/`,{method:"POST",body:JSON.stringify({sens})});
    const inputName=sens==="aller"?"heure_arrivee":"heure_arrivee_retour";
    body.querySelector(`[name="${inputName}"]`).value=result.estimated_arrival;
    body.querySelector(`[data-arrival-source="${sens}"]`).textContent="Estimation automatique";
    body.querySelector(`[data-route-calculation="${sens}"]`).innerHTML=transportCalculationMarkup(result);
    data.transport[inputName]=result.estimated_arrival;
    data.transport[sens==="aller"?"source_heure_arrivee":"source_heure_arrivee_retour"]="automatique";
  }catch(err){error.textContent=erreurMessage(err,"Impossible de calculer l’itinéraire pour le moment.");error.hidden=false}
  finally{button.disabled=data.transport.estimation_disponible===false}
}

form.addEventListener("submit",async event=>{
  event.preventDefault();
  const fd=new FormData(form),payload={};
  const previousPostalCode=data.destination_details?.code_postal||"";
  if(current==="participants") payload.groupes=fd.getAll("groupes").map(Number);
  else if(current==="transport"){
    Object.assign(payload,transportPayload());
  }
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
  else if(current==="liens") payload.liens=String(fd.get("liens")||"").split("\n").map(row=>{const [libelle,...url]=row.split("|");return {libelle:libelle?.trim(),url:url.join("|").trim()}}).filter(item=>item.libelle&&item.url);
  else for(const [key,value] of fd) payload[key]=value;

  try{
    data=await apiFetch(`/api/sorties/${id}/`,{method:"PATCH",body:JSON.stringify(payload)});
    const postalCodeChanged=current==="general"
      && String(payload.destination_code_postal||"").trim()!==previousPostalCode;
    pendingResponsibilities=null;
    pendingRemovedAssignments=[];
    pendingNewAssignments=[];
    dialog.close();
    render();
    if(postalCodeChanged) await refreshDestinationCalculations();
    else if(current==="meteo") loadWeather();
  }catch(err){
    const el=form.querySelector(".form-error");
    el.textContent=erreurMessage(err,"Enregistrement impossible.");
    el.hidden=false;
  }
});

assignmentForm.querySelector("[data-assignment-centre]").addEventListener("change",()=>fillAssignmentGroups());
assignmentForm.addEventListener("submit",async event=>{
  event.preventDefault();
  if(!pendingAssignment) return;
  const groupId=Number(assignmentForm.querySelector("[data-assignment-group]").value);
  const group=(data.groupes||[]).find(item=>item.evenement_id===groupId);
  const error=assignmentForm.querySelector(".form-error");
  try{
    await apiFetch(`/api/sorties/${id}/renforts/`,{method:"POST",body:JSON.stringify({animateur_id:pendingAssignment.animateurId,evenement_id:groupId})});
    assignmentDialog.close();pendingAssignment=null;
    data=await apiFetch(`/api/sorties/${id}/`);render();
  }catch(err){error.textContent=erreurMessage(err,"Affectation impossible.");error.hidden=false}
});

supportRemoval.querySelectorAll("[data-support-cancel]").forEach(button=>button.addEventListener("click",()=>{pendingSupportRemoval=null;supportRemoval.close()}));
supportRemoval.querySelectorAll("[data-support-remove]").forEach(button=>button.addEventListener("click",async()=>{
  const error=supportRemoval.querySelector(".form-error");
  try{
    await apiFetch(`/api/sorties/${id}/renforts/${pendingSupportRemoval}/?planning=${button.dataset.supportRemove}`,{method:"DELETE"});
    supportRemoval.close();pendingSupportRemoval=null;
    data=await apiFetch(`/api/sorties/${id}/`);render();
  }catch(err){error.textContent=erreurMessage(err,"Suppression impossible.");error.hidden=false}
}));

document.getElementById("edit-sortie-main").addEventListener("click",()=>open("general","Informations générales"));
document.getElementById("delete-sortie").addEventListener("click",async()=>{if(!confirm(`Supprimer la sortie « ${data.nom} » ?`)) return;await apiFetch(`/api/sorties/${id}/`,{method:"DELETE"});location.href="/sorties/"});
load().catch(err=>{blocks.innerHTML=`<p class="empty-note">${text(erreurMessage(err,"Chargement impossible."))}</p>`});
})();
