/* The readings strip and the status badge at the top of the page. */
import {BARS} from "./cage-geometry.js";
import {BAR_LEN, CAGE, FLY_TILE, POSE_STALE_MS, START_COMMAND} from "./config.js";
import {PMC_STATE} from "./labels.js";
import {pointById, state, streamingCount} from "./state.js";
import {$, esc} from "./util.js";

export function renderReadings(){
  var cells = state.sys === "cage" ? cageReadings() : flyReadings();
  $("kpis").innerHTML = cells.map(function(c){
    return '<div class="kpi"><div class="k">'+c[0]+'</div><div class="v">'+c[1]+
      (c[2] ? '<small>'+c[2]+'</small>' : '')+'</div></div>'; }).join("");
}
function cageReadings(){
  var bridge = state.bridge;
  var placed = bridge.receivers.filter(function(rx){ return rx.point != null && pointById(rx.point); });
  var live = placed.filter(function(rx){ return rx.power != null; });
  var total = live.reduce(function(sum, rx){ return sum+rx.power; }, 0);
  var best = live.reduce(function(a, rx){ return !a || rx.power > a.power ? rx : a; }, null);
  return [["Cage", String(CAGE/1000), "m cube"],
    ["Bar length", String(BAR_LEN/1000), "m · "+BARS.length+" bars"],
    ["Points", bridge.up ? String(state.cage.points.length) : "—", placed.length ? placed.length+" with a receiver" : ""],
    ["Receivers", bridge.up ? streamingCount()+" / "+bridge.receivers.length : "—", bridge.up ? "streaming" : "bridge offline"],
    ["Received", live.length ? total.toFixed(2) : "—", live.length ? "W total" : ""],
    ["Strongest", best ? best.power.toFixed(2) : "—", best ? "W at "+esc(pointById(best.point).name) : ""]];
}
function flyReadings(){
  var fly = state.fly, layout = fly.layout, T = layout ? layout.tile : FLY_TILE, flyways = fly.telemetry ? fly.telemetry.flyways : [];
  var stator = flyways.reduce(function(sum, f){ return sum+f.w; }, 0), hot = hottest(flyways);
  var riding = state.bridge.receivers.filter(function(rx){ return rx.xbot != null && rx.power != null; });
  var received = riding.reduce(function(sum, rx){ return sum+rx.power; }, 0);
  return [["Controller", PMC_STATE[fly.pmc] || (fly.pmc ? fly.pmc.replace(/^PMC_/,"").toLowerCase() : "—"), ""],
    ["Layout", layout ? layout.cols+" × "+layout.rows : "—", layout ? (layout.cols*T)+" × "+(layout.rows*T)+" mm" : ""],
    ["Stator power", flyways.length ? stator.toFixed(1) : "—", flyways.length ? "W" : ""],
    ["Hottest", hot ? hot.v.toFixed(1) : "—", hot ? "°C "+hot.where : ""],
    ["xBots", fly.connected ? String(fly.xbots.length) : "—", ""],
    ["Received", riding.length ? received.toFixed(2) : "—",
      riding.length ? "W from "+riding.length+" receiver"+(riding.length > 1 ? "s" : "") : ""]];
}
function hottest(flyways){
  var hot = null;
  flyways.forEach(function(f){
    [["CPU",f.cpu],["amp",f.amp],["motor",f.motor]].forEach(function(t){
      if (!hot || t[1] > hot.v) hot = {v:t[1], where:t[0]+", flyway "+f.id};
    });
  });
  return hot;
}

/* ---------- status badge ---------- */
export function renderBadge(){
  var st = state.sys === "cage" ? cageStatus() : flyStatus(), badge = $("srcBadge");
  badge.className = "badge link "+st[0]; badge.title = st[2];
  badge.innerHTML = '<span class="dot"></span>'+esc(st[1]);
}
function cageStatus(){
  if (!state.bridge.up) return ["bad", "Bridge offline", "Start it: "+START_COMMAND];
  var n = streamingCount();
  return n ? ["", n+" receiver"+(n > 1 ? "s" : "")+" live", ""] : ["warn", "Bridge up", "No receiver streaming"];
}
export function flyStatus(){
  var fly = state.fly;
  if (!state.bridge.up) return ["bad", "Bridge offline", "Start it: "+START_COMMAND];
  if (!fly.connected) return ["bad", "PMC not connected", fly.error || ""];
  if (performance.now() - fly.lastPose > POSE_STALE_MS) return ["warn", "PMC stale", "No pose for over "+POSE_STALE_MS/1000+" s"];
  return fly.source === "mock" ? ["", "Mock live", "Bridge is running with --mock"] : ["", "PMC live", ""];
}
