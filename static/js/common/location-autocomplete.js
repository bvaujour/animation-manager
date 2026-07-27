(function(global){
"use strict";
function initLocationAutocomplete(root){
  if(!root)return null;
  const postal=root.querySelector("[data-location-postal]"),city=root.querySelector("[data-location-city]"),insee=root.querySelector("[data-location-insee]"),requested=root.querySelector("[data-location-requested]"),suggestions=root.querySelector("[data-location-suggestions]"),status=root.querySelector("[data-location-status]");
  if(!postal||!city||!suggestions)return null;
  let timer=null,controller=null,active=-1,automatic=false,items=[];
  const close=()=>{suggestions.hidden=true;suggestions.innerHTML="";items=[];active=-1};
  const setStatus=message=>{if(status)status.textContent=message||""};
  const markManual=()=>{if(automatic)return;if(insee)insee.value="";if(requested)requested.value="1"};
  const select=item=>{automatic=true;postal.value=item.code_postal||"";city.value=item.nom||"";if(insee)insee.value=item.code_insee||"";if(requested)requested.value="1";automatic=false;close();setStatus("Commune sélectionnée")};
  const render=results=>{items=results||[];active=-1;if(!items.length){close();setStatus("Aucune commune trouvée. La saisie manuelle reste possible.");return}suggestions.innerHTML=items.map((item,index)=>`<button type="button" role="option" data-location-index="${index}"><strong>${escapeHtml(item.nom)}</strong><span>${escapeHtml(item.code_postal)}</span></button>`).join("");suggestions.hidden=false;setStatus(items.length===1?"1 commune trouvée":`${items.length} communes proposées`);suggestions.querySelectorAll("button").forEach(button=>button.addEventListener("click",()=>select(items[Number(button.dataset.locationIndex)])))};
  const search=async params=>{controller?.abort();controller=new AbortController();setStatus("Recherche…");try{const response=await apiFetch(`/api/localisation/communes/?${new URLSearchParams(params)}`,{signal:controller.signal});render(response.resultats);if(params.code_postal&&response.resultats.length===1)select(response.resultats[0])}catch(error){if(error.name==="AbortError")return;close();setStatus("Recherche indisponible. Vous pouvez saisir la commune manuellement.")}};
  const schedule=(params,delay=350)=>{clearTimeout(timer);timer=setTimeout(()=>search(params),delay)};
  postal.addEventListener("input",()=>{markManual();close();setStatus("");const value=postal.value.trim();if(/^\d{5}$/.test(value))schedule({code_postal:value},250)});
  city.addEventListener("input",()=>{markManual();close();setStatus("");const value=city.value.trim();if(value.length>=3)schedule({nom:value})});
  root.addEventListener("keydown",event=>{if(event.key==="Escape"){close();return}if(suggestions.hidden||!items.length)return;if(event.key==="ArrowDown"||event.key==="ArrowUp"){event.preventDefault();active=(active+(event.key==="ArrowDown"?1:-1)+items.length)%items.length;suggestions.querySelectorAll("button").forEach((button,index)=>button.classList.toggle("is-active",index===active))}else if(event.key==="Enter"&&active>=0){event.preventDefault();select(items[active])}});
  root.addEventListener("focusout",()=>setTimeout(()=>{if(!root.contains(document.activeElement))close()},0));
  return {close};
}
global.initLocationAutocomplete=initLocationAutocomplete;
})(window);
