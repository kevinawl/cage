/* Talking to the bridge (bridge/pmc_bridge.py): the event stream that fills `state`, and the POSTs that change points and receivers. */
import {EDIT_HOLD_MS, ERR_SAMPLES, ERR_WINDOW_MS, FLYWAY_SAMPLES, MESSAGE_MS, RX_SAMPLES} from "./config.js";
import {READINGS} from "./labels.js";
import {EVENTS_URL, POINTS_API, RECEIVERS_API, selectedPoint, state} from "./state.js";
import {pushTo} from "./util.js";

/* The bridge's event stream updates `state`; the views it affects are told through hooks,
   so this module depends on nothing above it:
     hooks.layoutChanged(layout), hooks.telemetry(), hooks.receivers() */
/* POSTed as text/plain so the browser sends no CORS preflight; the bridge checks the Origin. */
function postJson(url, body){
  return fetch(url, {method:"POST", headers:{"Content-Type":"text/plain"}, body:JSON.stringify(body || {})})
    .then(function(res){
      return res.json().catch(function(){ return {}; }).then(function(reply){
        if (!res.ok) throw new Error(reply.error || String(res.status));
        return reply;
      });
    });
}
function bridgeProblem(e){ return e instanceof TypeError ? "Couldn't reach the bridge. Is it running?" : "Not saved: "+e.message; }

/* A message shows for MESSAGE_MS under whatever it's about. */
const messages = {};
function flash(about, text){ messages[about] = {text:text, at:performance.now()}; }
export function messageFor(about){
  var m = messages[about];
  return m && performance.now() - m.at < MESSAGE_MS ? m.text : "";
}

export function postReceiver(mac, action, body){
  return postJson(RECEIVERS_API+encodeURIComponent(mac)+(action ? "/"+action : ""), body)
    .catch(function(e){ flash(mac, bridgeProblem(e)); });
}
export function postPoint(path, body){
  return postJson(POINTS_API+path, body).catch(function(e){ flash("points", bridgeProblem(e)); throw e; });
}

let hooks = {layoutChanged:function(){}, telemetry:function(){}, receivers:function(){}};
export function connectBridge(viewHooks){
  if (viewHooks) hooks = Object.assign({}, hooks, viewHooks);
  var bridge = state.bridge; if (bridge.events) return;
  bridge.events = new EventSource(EVENTS_URL);
  bridge.events.onopen = function(){ bridge.up = true; };
  bridge.events.onerror = function(){ bridge.up = false; state.fly.connected = false; };
  bridge.events.onmessage = function(ev){
    var msg; try { msg = JSON.parse(ev.data); } catch(e){ return; }
    bridge.up = true;
    var handle = ON_MESSAGE[msg.type];
    if (handle) handle(msg);
  };
}
const ON_MESSAGE = {status:onStatus, pose:onPose, receivers:onReceivers, telemetry:onTelemetry};

function onStatus(msg){
  var fly = state.fly;
  fly.connected = msg.connected; fly.error = msg.error; fly.pmc = msg.pmc; fly.source = msg.source;
  if (msg.layout && JSON.stringify(msg.layout) !== JSON.stringify(fly.layout)){
    fly.layout = msg.layout; hooks.layoutChanged(fly.layout);
  }
}
function onPose(msg){
  var fly = state.fly;
  fly.xbots = msg.xbots; fly.lastPose = performance.now(); fly.connected = true;
  accumulateTracking(fly.xbots);
  if (fly.lastPose - fly.tracking.windowStart >= ERR_WINDOW_MS) closeTrackingWindow(fly.lastPose);
}
function onReceivers(msg){
  var bridge = state.bridge;
  bridge.receivers = msg.boards;
  if (msg.points) mergePoints(msg.points);
  bridge.receivers.forEach(function(rx){
    READINGS.forEach(function(q){ if (rx[q.key] != null) pushTo(bridge.history[q.key], rx.mac, RX_SAMPLES, rx[q.key]); });
  });
  hooks.receivers();
}
function onTelemetry(msg){
  var fly = state.fly;
  fly.telemetry = msg;
  msg.flyways.forEach(function(f){ pushTo(fly.flywayPower, f.id, FLYWAY_SAMPLES, f.w); });
  hooks.telemetry();
}
/* Tracking error: every pose counts, but it's shown as the mean over ERR_WINDOW_MS, so the
   number and its trend move at a readable pace instead of flickering at 20 Hz. */
function accumulateTracking(xbots){
  var sums = state.fly.tracking.sums;
  xbots.forEach(function(b){
    if (!b.err) return;
    var a = sums[b.id] = sums[b.id] || {n:0, x:0, y:0, z:0, m:0};
    a.n++; a.x += b.err[0]; a.y += b.err[1]; a.z += b.err[2]; a.m += Math.hypot(b.err[0], b.err[1], b.err[2]);
  });
}
function closeTrackingWindow(now){
  var t = state.fly.tracking;
  t.windowStart = now;
  Object.keys(t.sums).forEach(function(id){
    var a = t.sums[id]; if (!a.n) return;
    var mean = t.shown[id] = {m:a.m/a.n, x:a.x/a.n, y:a.y/a.n, z:a.z/a.n};
    pushTo(t.history, id, ERR_SAMPLES, mean.m);
    a.n = a.x = a.y = a.z = a.m = 0;
  });
}
/* Edits show at once; the bridge's copy wins again once they have had time to land. */
function mergePoints(list){
  var cage = state.cage, now = performance.now(), mine = {};
  cage.points.forEach(function(p){ mine[p.id] = p; });
  cage.points = list.map(function(p){
    var editedAt = cage.editedAt[p.id];
    return editedAt && now - editedAt < EDIT_HOLD_MS && mine[p.id] ? mine[p.id] : p;
  });
  if (cage.selected && !selectedPoint()) cage.selected = null;
}
