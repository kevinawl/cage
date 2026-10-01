/* The View popover: toggles and colour choices, applied to every view. */
import {buildScale} from "./cage-view.js";
import {ACCENTS, FINISH, RAMPS} from "./config.js";
import {MAT_MOVER, buildStator, flyAxes, moverMeshes, paintTiles, tiles} from "./flyway-view.js";
import {VIEW, VIEW_DEFAULT, saveView} from "./settings.js";
import {state} from "./state.js";
import {theme} from "./theme.js";
import {drawTrend} from "./trends.js";
import {$} from "./util.js";

/* Sections are hidden by attributes on <html>, so no view code has to know. */
const HIDE_KEYS = ["kpis","fwPanel","mvPanel","rxPanel","mPos","mLift","mErr","fwSpark","fwTemps","cPoints"];
export function applyView(){
  var root = document.documentElement;
  HIDE_KEYS.forEach(function(k){ root.toggleAttribute("data-hide-"+k.toLowerCase(), !VIEW[k]); });
  root.setAttribute("data-stage", VIEW.stage);
  var a = ACCENTS[VIEW.accent] || ACCENTS.blue, accentChanged = a[0] !== theme.accent;
  theme.accent = a[0];
  root.style.setProperty("--accent", a[0]); root.style.setProperty("--accent-hover", a[1]); root.style.setProperty("--accent-soft", a[2]);
  theme.ramp = RAMPS[VIEW.ramp] || RAMPS.blue;
  var gradient = "linear-gradient(90deg,"+theme.ramp.join(",")+")";
  $("rampBar").style.background = gradient; $("flyRamp").style.background = gradient;
  MAT_MOVER.color.setHex(FINISH[VIEW.finish] || FINISH.graphite);
  Object.keys(tiles).forEach(function(id){ tiles[id].painted = null; tiles[id].label.visible = VIEW.tileLabels; });
  if (accentChanged) buildStator(state.fly.layout);
  flyAxes.forEach(function(o){ o.visible = VIEW.axes; });
  Object.keys(moverMeshes).forEach(function(id){
    var m = moverMeshes[id]; m.userData.idSprite.visible = VIEW.moverIds; m.userData.face.painted = null; });
  paintTiles();
  buildScale();
  document.querySelectorAll("canvas.spark").forEach(drawTrend);
}

const VIEW_GROUPS = [
  {sys:"fly", title:"Sections", rows:[["kpis","Readings strip"],["fwPanel","Flyways"],["mvPanel","Movers"],["rxPanel","Receivers"]]},
  {sys:"fly", title:"3D view", rows:[["tileHeat","Colour tiles by power"],["tileLabels","Power on tiles"],
    ["moverPower","Received power on xBots"],["moverIds","xBot numbers"],["axes","X / Y axes"]]},
  {sys:"fly", title:"Details", rows:[["mPos","Mover position"],["mLift","Lift"],["mErr","Tracking error"],
    ["fwSpark","Flyway power trends"],["fwTemps","Flyway temperatures"]]},
  {sys:"cage", title:"Sections", rows:[["kpis","Readings strip"],["cPoints","Points"],["rxPanel","Receivers"]]},
  {sys:"cage", title:"3D view", rows:[["cScale","Rulers and axes"],["cLabels","Point labels"],["cDrops","Drop lines to the floor"]]}];
const NAMES = {blue:"Blue", teal:"Teal", violet:"Violet", amber:"Amber", graphite:"Graphite", silver:"Silver", white:"White",
  light:"Light", soft:"Soft", dark:"Dark"};
export const viewPanel = $("viewPop"), viewButton = $("btnView");
export function renderViewPanel(){
  var html = '<div class="vp-hd"><h3>View</h3><span class="hsub">Saved in this browser</span>'+
    '<button class="vp-reset" data-reset>Reset</button></div>';
  VIEW_GROUPS.filter(function(g){ return g.sys === state.sys; }).forEach(function(g){
    html += '<div class="vp-grp"><h4>'+g.title+'</h4>'+g.rows.map(function(r){ return toggleHtml(r[0], r[1]); }).join("")+'</div>';
  });
  html += '<div class="vp-grp"><h4>Colours</h4>'+
    swatchesHtml("accent", Object.keys(ACCENTS), "swc", function(o){ return ACCENTS[o][0]; }, "Accent")+
    swatchesHtml("ramp", Object.keys(RAMPS), "swr", function(o){ return "linear-gradient(90deg,"+RAMPS[o].join(",")+")"; }, "Power scale")+
    (state.sys === "fly" ? segmentsHtml("finish", ["graphite","silver","white"], "xBot finish") : "")+
    segmentsHtml("stage", ["light","soft","dark"], "3D background")+'</div>';
  viewPanel.innerHTML = html;
}
function toggleHtml(key, label){
  return '<label class="vp-row"><span>'+label+'</span><button class="tgl" role="switch" data-k="'+key+
    '" aria-checked="'+VIEW[key]+'" aria-label="'+label+'"></button></label>';
}
function swatchesHtml(key, options, cls, fill, label){
  return '<div class="vp-lbl">'+label+'<em>'+NAMES[VIEW[key]]+'</em></div><div class="vp-sws" role="radiogroup" aria-label="'+label+'">'+
    options.map(function(o){ return '<button class="'+cls+'" role="radio" data-k="'+key+'" data-v="'+o+'" aria-checked="'+(VIEW[key] === o)+
      '" aria-label="'+NAMES[o]+'" title="'+NAMES[o]+'" style="--c:'+fill(o)+'"></button>'; }).join("")+'</div>';
}
function segmentsHtml(key, options, label){
  return '<div class="vp-lbl">'+label+'</div><div class="tabs vp-seg" role="radiogroup" aria-label="'+label+'">'+
    options.map(function(o){ return '<button class="tab" role="radio" data-k="'+key+'" data-v="'+o+'" aria-selected="'+(VIEW[key] === o)+
      '" aria-checked="'+(VIEW[key] === o)+'">'+NAMES[o]+'</button>'; }).join("")+'</div>';
}
export function openViewPanel(open){
  viewPanel.hidden = !open; viewButton.setAttribute("aria-expanded", open ? "true" : "false");
  if (!open) return;
  renderViewPanel();
  var first = viewPanel.querySelector(".tgl, [role=radio]"); if (first) first.focus();
}
function changeView(control){
  if (control.hasAttribute("data-reset")) Object.keys(VIEW_DEFAULT).forEach(function(k){ VIEW[k] = VIEW_DEFAULT[k]; });
  else if (control.hasAttribute("data-v")) VIEW[control.dataset.k] = control.dataset.v;
  else VIEW[control.dataset.k] = !VIEW[control.dataset.k];
  saveView(); applyView(); renderViewPanel();
}
viewButton.onclick = function(e){ e.stopPropagation(); openViewPanel(viewPanel.hidden); };
viewPanel.addEventListener("click", function(e){
  e.stopPropagation();
  var control = e.target.closest("[data-k], [data-reset]"); if (!control) return;
  e.preventDefault();
  var key = control.dataset.k, value = control.dataset.v;
  changeView(control);
  var again = viewPanel.querySelector(key ? '[data-k="'+key+'"]'+(value ? '[data-v="'+value+'"]' : '') : "[data-reset]");
  if (again) again.focus();                                       // the panel was redrawn; keep focus in place
});
document.addEventListener("click", function(){ if (!viewPanel.hidden) openViewPanel(false); });
document.addEventListener("keydown", function(e){
  if (e.key === "Escape" && !viewPanel.hidden){ openViewPanel(false); viewButton.focus(); }
});
