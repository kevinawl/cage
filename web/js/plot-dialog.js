/* Plot data, the dialog: its header, the filter row, the tab switching and the 1 s refresh. */
import {hoverTime, renderHeat, renderScatter, renderTable, renderTime} from "./plot-charts.js";
import {METRICS, METRIC_BY, PLOT_BINS, PLOT_RANGES, PLOT_REFRESH_MS, PLOT_TABS, clockText, compactCount, metricNow, plot, plotSamples, receiversRecorded, savePlot} from "./plot-model.js";
import {hideSpots, syncSpots} from "./plot-spots.js";
import {exportCsv, rec} from "./recorder.js";
import {state} from "./state.js";
import {trendTip} from "./trends.js";
import {$, esc} from "./util.js";
import {openViewPanel, viewPanel} from "./view-panel.js";

const plotPop = $("plotPop"), plotButton = $("btnPlot"), plotBar = $("plotBar"), plotBody = $("plotBody");
function openPlot(open){
  plot.open = open; plotPop.hidden = !open; plotButton.setAttribute("aria-expanded", open ? "true" : "false");
  if (!open){ trendTip.classList.remove("on"); plotButton.focus(); return; }
  if (!viewPanel.hidden) openViewPanel(false);
  renderPlot();
  var first = plotBar.querySelector('[data-pk="tab"][aria-selected="true"]'); if (first) first.focus();
}
function segmentedControl(key, label, options, current, disabledOf){
  return '<div class="tabs" role="radiogroup" aria-label="'+label+'">'+options.map(function(o){
    var off = disabledOf && disabledOf(o[0]);
    return '<button class="tab" role="radio" data-pk="'+key+'" data-pv="'+o[0]+'" aria-checked="'+(current === o[0])+'" aria-selected="'+
      (current === o[0])+'"'+(off ? ' disabled title="'+esc(off)+'"' : o[2] ? ' title="'+esc(o[2])+'"' : '')+'>'+o[1]+'</button>'; }).join("")+'</div>';
}
function renderPlotBar(){
  var rig = state.sys, m = metricNow(), macs = receiversRecorded(rig), html = "";
  if (plot.rx !== "all" && macs.indexOf(plot.rx) < 0) plot.rx = "all";
  html += '<div class="tabs pl-tabs" role="tablist" aria-label="Plot">'+PLOT_TABS.map(function(t){
    return '<button class="tab" role="tab" data-pk="tab" data-pv="'+t[0]+'" aria-selected="'+(plot.tab === t[0])+'">'+t[1]+'</button>'; }).join("")+'</div>';
  html += '<div class="pl-ctl">'+segmentedControl("metric", "Reading", METRICS.map(function(q){ return [q.key, q.label, q.title]; }), m.key,
    function(k){ return METRIC_BY[k].fly && rig !== "fly" ? "Flyway only: the cage's TX doesn't report its output" : ""; })+'</div>';
  html += '<div class="pl-ctl">'+segmentedControl("range", "Time range", PLOT_RANGES, plot.range)+'</div>';
  html += '<label class="pl-ctl pl-lab">Receiver <select class="pl-sel" data-pk="rx"><option value="all">All</option>'+macs.map(function(mac){
    return '<option value="'+esc(mac)+'"'+(plot.rx === mac ? " selected" : "")+'>'+esc(rec.nameOf[mac] || mac)+'</option>'; }).join("")+'</select></label>';
  if (plot.tab === "heat"){
    html += '<div class="pl-ctl pl-lab">Cell '+segmentedControl("bin", "Cell size", PLOT_BINS[rig].map(function(b){ return [String(b), b+" mm"]; }), String(plot.bin[rig]))+'</div>';
    if (rig === "cage") html += '<label class="pl-ctl vp-row pl-lab"><span>Show spots in 3D</span><button class="tgl" role="switch" data-pk="spots" aria-checked="'+
      plot.spots+'" aria-label="Show measured spots in the 3D view"></button></label>';
  }
  if (plot.tab === "scatter"){
    html += '<label class="pl-ctl pl-lab">Against <select class="pl-sel" data-pk="axis">'+[["dist","Distance from"],["x","X"],["y","Y"],["z","Z"]].map(function(o){
      return '<option value="'+o[0]+'"'+(plot.axis === o[0] ? " selected" : "")+'>'+o[1]+'</option>'; }).join("")+'</select></label>';
    if (plot.axis === "dist"){
      var refs = [["centre", rig === "cage" ? "Cage centre" : "Stator origin"]];
      if (rig === "cage") state.cage.points.forEach(function(p){ refs.push([p.id, p.name]); });
      if (!refs.some(function(r){ return r[0] === plot.ref; })) plot.ref = "centre";
      html += '<select class="pl-sel pl-ctl" data-pk="ref" aria-label="Distance from">'+refs.map(function(r){
        return '<option value="'+esc(r[0])+'"'+(plot.ref === r[0] ? " selected" : "")+'>'+esc(r[1])+'</option>'; }).join("")+'</select>';
    }
  }
  plotBar.innerHTML = html;
}
function renderPlotHead(){
  var n = rec.samples.length, first = rec.samples[0];
  $("plotSub").textContent = n ? compactCount(n)+" readings since "+clockText(first.t, false) : "Nothing recorded yet";
  var r = $("plotRec");
  r.setAttribute("aria-pressed", rec.on ? "true" : "false");
  r.querySelector("span").textContent = rec.on ? "Recording" : "Paused";
  $("plotClear").textContent = performance.now()-plot.clearArmed < 3000 ? "Click again to clear" : "Clear";
  $("plotCsv").disabled = !n; $("plotClear").disabled = !n;
}
export function renderPlot(){ renderPlotHead(); renderPlotBar(); renderPlotBody(); }
function renderPlotBody(){
  plot.lastDraw = performance.now(); plot.tips = []; plot.time = null;
  renderPlotHead();
  var rig = state.sys, m = metricNow(), samples = plotSamples(rig);
  if (!samples.length){
    var what = rig === "cage" ? "at a cage point" : "on an xBot";
    plotBody.innerHTML = '<div class="empty"><b>'+(rec.samples.length ? "Nothing in this selection" : "No readings yet")+'</b>'+
      (rec.on ? "Every reading is recorded while a receiver streams "+what+". Move it between points to build the map."
              : "Recording is paused. Resume it to collect readings.")+'</div>';
    return;
  }
  var draw = {heat:renderHeat, table:renderTable, time:renderTime, scatter:renderScatter}[plot.tab] || renderHeat;
  plotBody.innerHTML = draw(samples, m, rig);
}

/* ---------- wiring ---------- */
plotButton.onclick = function(e){ e.stopPropagation(); openPlot(!plot.open); };
$("plotClose").onclick = function(){ openPlot(false); };
plotPop.addEventListener("click", function(e){ if (e.target === plotPop) openPlot(false); });
$("plotRec").onclick = function(){ rec.on = !rec.on; renderPlot(); };
$("plotCsv").onclick = exportCsv;
$("plotClear").onclick = function(){
  if (performance.now()-plot.clearArmed < 3000){ rec.samples = []; plot.clearArmed = -Infinity; syncSpots(); renderPlot(); return; }
  plot.clearArmed = performance.now(); renderPlotHead();
  setTimeout(function(){ if (plot.open) renderPlotHead(); }, 3100);
};
plotBar.addEventListener("click", function(e){
  var c = e.target.closest("button[data-pk]"); if (!c || c.disabled) return;
  var k = c.dataset.pk, v = c.dataset.pv;
  if (k === "spots"){ plot.spots = !plot.spots; syncSpots(); }
  else if (k === "bin") plot.bin[state.sys] = +v;
  else plot[k] = v;
  savePlot(); renderPlot();
  var again = plotBar.querySelector('[data-pk="'+k+'"]'+(v ? '[data-pv="'+v+'"]' : '')); if (again) again.focus();
});
plotBar.addEventListener("change", function(e){
  var c = e.target.closest("select[data-pk]"); if (!c) return;
  plot[c.dataset.pk] = c.value; savePlot(); renderPlot();
  var again = plotBar.querySelector('select[data-pk="'+c.dataset.pk+'"]'); if (again) again.focus();
});
plotBody.addEventListener("click", function(e){
  var s = e.target.closest("[data-sort]"); if (!s) return;
  if (plot.sort === s.dataset.sort) plot.desc = !plot.desc; else { plot.sort = s.dataset.sort; plot.desc = s.dataset.sort !== "place" && s.dataset.sort !== "rx"; }
  renderPlotBody();
  var again = plotBody.querySelector('[data-sort="'+s.dataset.sort+'"]'); if (again) again.focus();
});
/* While the pointer is on a chart it holds still, so the hovered mark stays put. */
plotBody.addEventListener("pointermove", function(e){
  var chart = e.target.closest(".pl-chart");
  plot.hovering = !!chart;
  if (chart && chart.classList.contains("pl-time")){ hoverTime(chart, e); return; }
  var mark = e.target.closest("[data-tip]");
  if (!mark){ trendTip.classList.remove("on"); return; }
  trendTip.innerHTML = plot.tips[+mark.dataset.tip];
  trendTip.style.left = e.clientX+"px"; trendTip.style.top = e.clientY+"px"; trendTip.classList.add("on");
});
plotBody.addEventListener("pointerleave", function(){
  plot.hovering = false; trendTip.classList.remove("on");
  var xh = plotBody.querySelector(".xh"); if (xh) xh.setAttribute("visibility", "hidden");
});
document.addEventListener("keydown", function(e){ if (e.key === "Escape" && plot.open) openPlot(false); });
export function refreshPlots(now){
  var n = rec.samples.length;
  $("plotCount").textContent = n ? compactCount(n) : "";
  plotButton.classList.toggle("rec", rec.on && n > 0);
  if (now-plot.lastDraw < PLOT_REFRESH_MS) return;
  plot.lastDraw = now;
  if (state.sys === "cage") syncSpots(); else hideSpots();
  if (!plot.open || plot.hovering) return;
  if (rec.seen !== plot.barSeen && !plotBar.contains(document.activeElement)){ plot.barSeen = rec.seen; renderPlotBar(); }
  renderPlotBody();
}
