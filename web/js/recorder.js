/* Recording: every reading with where it was taken, kept in this tab, and the CSV export. */
import {POSE_STALE_MS} from "./config.js";
import {isStreaming, pointById, receiverName, state} from "./state.js";

/* A sample per streaming, placed receiver per receivers message (5 Hz). Kept in this tab
   only, so a reload clears it; Export writes it out as CSV. */
const REC_MAX = 200000, REC_TRIM = 20000;
/* Categorical slots, in fixed order: a receiver keeps its colour for the session. A 9th is grey. */
const SERIES = ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4","#008300","#4a3aa7","#e34948"], SERIES_MORE = "#878d99";
export const rec = {on:true, samples:[], colorOf:{}, nameOf:{}, seen:0};
function seriesColor(mac){
  if (!(mac in rec.colorOf)){ rec.colorOf[mac] = rec.seen < SERIES.length ? SERIES[rec.seen] : SERIES_MORE; rec.seen++; }
  return rec.colorOf[mac];
}
function numOrNull(v){ return v == null ? null : v; }
function statorWatts(){
  var fly = state.fly; if (!fly.connected || !fly.telemetry) return null;
  return fly.telemetry.flyways.reduce(function(sum, f){ return sum+f.w; }, 0);
}
function placeOf(rx){
  if (rx.point != null){ var p = pointById(rx.point); return p ? {rig:"cage", place:p.name, x:p.x, y:p.y, z:p.z} : null; }
  if (rx.xbot == null || performance.now() - state.fly.lastPose > POSE_STALE_MS) return null;
  var b = state.fly.xbots.filter(function(b){ return b.id === rx.xbot; })[0];
  return b ? {rig:"fly", place:"xBot "+b.id, x:b.x, y:b.y, z:b.z} : null;
}
export function recordReadings(){
  if (!rec.on) return;
  var t = Date.now(), sent = statorWatts();
  state.bridge.receivers.forEach(function(rx){
    if (!isStreaming(rx) || (rx.power == null && rx.voltage == null && rx.current == null)) return;
    var at = placeOf(rx); if (!at) return;
    seriesColor(rx.mac); rec.nameOf[rx.mac] = receiverName(rx);
    rec.samples.push({t:t, mac:rx.mac, rig:at.rig, place:at.place, x:at.x, y:at.y, z:at.z,
      p:numOrNull(rx.power), v:numOrNull(rx.voltage), i:numOrNull(rx.current), sent:at.rig === "fly" ? sent : null});
  });
  if (rec.samples.length > REC_MAX) rec.samples.splice(0, REC_TRIM);
}
export function exportCsv(){
  function cell(s){ s = String(s); return /[",\n]/.test(s) ? '"'+s.replace(/"/g, '""')+'"' : s; }
  function n(v, dp){ return v == null ? "" : String(+v.toFixed(dp)); }
  var lines = ["time,receiver,mac,rig,place,x_mm,y_mm,z_mm,power_W,voltage_V,current_A,stator_W"];
  rec.samples.forEach(function(s){
    lines.push([new Date(s.t).toISOString(), cell(rec.nameOf[s.mac] || s.mac), s.mac, s.rig, cell(s.place),
      n(s.x, 1), n(s.y, 1), n(s.z, 1), n(s.p, 4), n(s.v, 4), n(s.i, 5), n(s.sent, 2)].join(","));
  });
  var stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "-");
  var a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")+"\n"], {type:"text/csv"}));
  a.download = "cage-readings-"+stamp+".csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
}
