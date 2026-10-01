/* Entry point: wires the bridge to the views, switches between the two rigs and runs the frame loop. */
import {connectBridge} from "./bridge.js";
import {buildScale, cagePowerTop, hideGhost, syncPoints} from "./cage-view.js";
import {UI_REFRESH_MS} from "./config.js";
import {buildStator, paintTiles, syncMovers} from "./flyway-view.js";
import {buildFlywayPanel, renderFlyways} from "./flyways-panel.js";
import {renderBadge, renderReadings} from "./header.js";
import {renderMovers} from "./movers-panel.js";
import {refreshPlots, renderPlot} from "./plot-dialog.js";
import {plot} from "./plot-model.js";
import {hideViewTip} from "./pointer.js";
import {renderPoints, renderPointsMessage} from "./points-panel.js";
import {receiverCards, renderReceivers} from "./receivers-panel.js";
import {recordReadings} from "./recorder.js";
import {cameras, canvas3d, placeCamera, renderer, scenes} from "./scene.js";
import {state} from "./state.js";
import {$} from "./util.js";
import {applyView, renderViewPanel, viewPanel} from "./view-panel.js";

function switchSystem(sys){
  state.sys = sys; state.hover = null; state.dragging = false; hideGhost();
  if (plot.open) renderPlot();
  var isCage = sys === "cage";
  if (!viewPanel.hidden) renderViewPanel();
  document.querySelectorAll(".sysbtn").forEach(function(b){ b.setAttribute("aria-selected", b.dataset.sys === sys ? "true" : "false"); });
  $("viewTitle").textContent = isCage ? "Cage · 3 m cube, 48 bars of 1.5 m" : "Flyway";
  ["ptPanel","rampLegend","scaleNote"].forEach(function(id){ $(id).hidden = !isCage; });
  ["moverPanel","flywayPanel","flyLegend"].forEach(function(id){ $(id).hidden = isCage; });
  $("rxbPanel").hidden = false;
  $("hint").textContent = isCage
    ? "Drag to orbit · scroll to zoom · click a point to select it, then click a bar to put it there, or drag it along the bars"
    : "Drag to orbit · scroll to zoom";
  hideViewTip();
  Object.keys(receiverCards).forEach(function(mac){ receiverCards[mac].placementKey = null; });   // the select changes meaning
  placeCamera();
  refreshPanels();
}
document.querySelectorAll(".sysbtn").forEach(function(b){ b.onclick = function(){ switchSystem(b.dataset.sys); }; });

/* ---------- resize + loop ---------- */
function resize(){
  var w = canvas3d.clientWidth, h = canvas3d.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  Object.keys(cameras).forEach(function(k){ cameras[k].obj.aspect = w/h; cameras[k].obj.updateProjectionMatrix(); });
}
new ResizeObserver(resize).observe(canvas3d);

function refreshPanels(){
  renderReadings(); renderBadge(); renderReceivers();
  if (state.sys === "cage"){
    renderPoints(); renderPointsMessage();
    $("rampMax").textContent = cagePowerTop()+" W";
  } else {
    renderMovers(); renderFlyways();
  }
}
let lastRefresh = 0;
function frame(now){
  requestAnimationFrame(frame);
  if (state.sys === "cage") syncPoints(); else syncMovers();
  renderer.render(scenes[state.sys], cameras[state.sys].obj);
  refreshPlots(now);
  if (now - lastRefresh <= UI_REFRESH_MS) return;
  lastRefresh = now;
  refreshPanels();
}

/* ---------- start ---------- */
/* What the bridge's events change beyond `state` itself. */
const BRIDGE_HOOKS = {
  layoutChanged:function(layout){ buildStator(layout); buildFlywayPanel(); },
  telemetry:paintTiles,
  receivers:recordReadings
};

buildStator(null);
if (document.fonts) Promise.all([document.fonts.load('600 56px "Geist Mono"'), document.fonts.load('600 84px "Geist"')])
  .then(function(){ buildStator(state.fly.layout); buildScale(); });
applyView();
connectBridge(BRIDGE_HOOKS);
switchSystem(new URLSearchParams(location.search).get("view") === "fly" ? "fly" : "cage");
resize();
canvas3d.style.cursor = "grab";
requestAnimationFrame(frame);
