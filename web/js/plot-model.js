/* Plot data, the model: what can be plotted, the dialog's choices, and the maths shared by the charts. */
import {rec} from "./recorder.js";
import {state} from "./state.js";
import {fmtA, fmtV, fmtW, maxAbs, readingStep, scaleTop, signed} from "./util.js";

/* What can be plotted. Sent and efficiency need the stator's telemetry, so the flyway only:
   the cage's TX doesn't report its output. */
export const METRICS = [
  {key:"p",    label:"Power",      unit:"W", fmt:fmtW},
  {key:"v",    label:"Voltage",    unit:"V", fmt:fmtV},
  {key:"i",    label:"Current",    unit:"A", fmt:fmtA},
  {key:"sent", label:"Sent",       unit:"W", fmt:fmtW, fly:true, title:"Total stator power, all flyways"},
  {key:"eff",  label:"Efficiency", unit:"%", fmt:function(v){ return v == null ? "—" : v.toFixed(1); }, fly:true,
   title:"Received ÷ stator power. The stator also levitates and drives the movers, so this is end to end."}];
export const METRIC_BY = {}; METRICS.forEach(function(m){ METRIC_BY[m.key] = m; });
export const PLOT_TABS = [["heat","Heat map"],["table","Locations"],["time","Over time"],["scatter","vs position"]];
export const PLOT_RANGES = [["60","1 min"],["600","10 min"],["3600","1 h"],["all","All"]];
export const PLOT_BINS = {cage:[100,250,500], fly:[10,20,40]};
export const PLOT_REFRESH_MS = 1000;
const PLOT_KEY = "cagePowerMap.plot.v1";
export const plot = {open:false, tab:"heat", metric:"p", rx:"all", range:"all", bin:{cage:250, fly:20}, axis:"dist", ref:"centre",
  sort:"place", desc:false, spots:false, hovering:false, lastDraw:0, tips:[], time:null, clearArmed:-Infinity, barSeen:0};
(function loadPlot(){
  try {
    var saved = JSON.parse(localStorage.getItem(PLOT_KEY) || "{}");
    ["tab","metric","range","axis"].forEach(function(k){ if (typeof saved[k] === "string") plot[k] = saved[k]; });
    if (typeof saved.spots === "boolean") plot.spots = saved.spots;
    if (saved.bin) ["cage","fly"].forEach(function(r){ if (PLOT_BINS[r].indexOf(saved.bin[r]) >= 0) plot.bin[r] = saved.bin[r]; });
  } catch(e){}
})();
export function savePlot(){
  try { localStorage.setItem(PLOT_KEY, JSON.stringify({tab:plot.tab, metric:plot.metric, range:plot.range, axis:plot.axis,
    spots:plot.spots, bin:plot.bin})); } catch(e){}
}
export function metricNow(){ var m = METRIC_BY[plot.metric] || METRICS[0]; return m.fly && state.sys !== "fly" ? METRICS[0] : m; }
export function valueOf(s, key){
  if (key === "eff") return s.p != null && s.sent > 0 ? s.p/s.sent*100 : null;
  return s[key];
}
export function plotSamples(rig){
  var key = metricNow().key, since = plot.range === "all" ? 0 : Date.now()-(+plot.range)*1000;
  return rec.samples.filter(function(s){
    return s.rig === rig && s.t >= since && (plot.rx === "all" || s.mac === plot.rx) && valueOf(s, key) != null;
  });
}
/* One row per receiver per spot (10 mm): every metric's mean, min and max while it sat there. */
export function locationsOf(samples){
  var byKey = {}, list = [];
  samples.forEach(function(s){
    var k = s.mac+"|"+Math.round(s.x/10)+"|"+Math.round(s.y/10)+"|"+Math.round(s.z/10), L = byKey[k];
    if (!L){ L = byKey[k] = {mac:s.mac, place:s.place, x:s.x, y:s.y, z:s.z, t0:s.t, t1:s.t, n:0, stats:{}}; list.push(L); }
    L.t1 = s.t; L.n++;
    METRICS.forEach(function(m){
      var v = valueOf(s, m.key); if (v == null) return;
      var st = L.stats[m.key] || (L.stats[m.key] = {n:0, sum:0, min:Infinity, max:-Infinity});
      st.n++; st.sum += v; if (v < st.min) st.min = v; if (v > st.max) st.max = v;
    });
  });
  list.forEach(function(L){ Object.keys(L.stats).forEach(function(k){ L.stats[k].mean = L.stats[k].sum/L.stats[k].n; }); });
  return list;
}
export function topOf(values){ var max = maxAbs(values); return scaleTop(max, readingStep(max), max > 0 ? 0 : 1); }
/* Ticks on round numbers; the domain is widened to the outer ticks. */
export function niceScale(lo, hi, count){
  if (hi <= lo) hi = lo+1;
  var raw = (hi-lo)/count, step = Math.pow(10, Math.floor(Math.log(raw)/Math.LN10)), f = raw/step;
  step *= f >= 7.5 ? 10 : f >= 3.5 ? 5 : f >= 1.5 ? 2 : 1;
  var a = Math.floor(lo/step+1e-9)*step, b = Math.ceil(hi/step-1e-9)*step, ticks = [];
  for (var v = a; v <= b+step/2; v += step) ticks.push(+v.toFixed(10));
  return {lo:a, hi:b, ticks:ticks, step:step};
}
export function tickText(v, step){ var dp = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log(step)/Math.LN10)); return signed(v, dp); }
export function clockText(t, seconds){ var s = new Date(t).toTimeString(); return seconds ? s.slice(0, 8) : s.slice(0, 5); }
export function durationText(ms){
  if (ms < 9500) return +(ms/1000).toFixed(ms < 1000 ? 2 : 1)+" s";   // short time buckets: "0.25 s", not "0 s"
  var s = Math.round(ms/1000);
  return s < 60 ? s+" s" : s < 3600 ? Math.floor(s/60)+" min "+(s%60)+" s" : Math.floor(s/3600)+" h "+Math.floor(s%3600/60)+" min";
}
export function compactCount(n){ return n < 1000 ? String(n) : n < 1e5 ? (n/1000).toFixed(1)+"k" : Math.round(n/1000)+"k"; }
export function tipFor(html){ plot.tips.push(html); return ' data-tip="'+(plot.tips.length-1)+'"'; }
export function receiversRecorded(rig){
  var seen = {}, out = [];
  rec.samples.forEach(function(s){ if (s.rig === rig && !seen[s.mac]){ seen[s.mac] = true; out.push(s.mac); } });
  return out;
}
