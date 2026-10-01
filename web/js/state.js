/* Everything the page knows, in one object, plus lookups over it. The bridge writes it; the views read it. */
export const state = {
  sys:"cage", hover:null, dragging:false,
  /* Cage points are measured positions, kept by the bridge (bridge/cage_points.json);
     receivers are placed on them. Nothing on the cage side is simulated. */
  cage:{points:[], selected:null, editedAt:{}},
  /* Saguaro receivers, shared by both views: a board rides on an xBot or sits at a point. */
  bridge:{events:null, up:false, receivers:[], history:{power:{}, voltage:{}, current:{}}},
  /* Flyway is live only: everything here comes from the bridge. */
  fly:{connected:false, error:null, pmc:null, source:null, layout:null, xbots:[], lastPose:0, telemetry:null,
       flywayPower:{}, tracking:{sums:{}, shown:{}, history:{}, windowStart:0}}
};
/* Bridge: bridge/pmc_bridge.py. Override with index.html?bridge=http://host:port;
   bridge=same means the bridge served this page. */
const BRIDGE_PARAM = new URLSearchParams(location.search).get("bridge") || "http://localhost:8765";
const BRIDGE = BRIDGE_PARAM === "same" ? location.origin : BRIDGE_PARAM;
export const EVENTS_URL = BRIDGE+"/events", RECEIVERS_API = BRIDGE+"/api/receivers/", POINTS_API = BRIDGE+"/api/points";

export function pointById(id){ return state.cage.points.filter(function(p){ return p.id === id; })[0] || null; }
export function selectedPoint(){ return pointById(state.cage.selected); }
export function receiverAt(pointId){ return state.bridge.receivers.filter(function(r){ return r.point === pointId; })[0] || null; }
export function receiverOn(xbotId){ return state.bridge.receivers.filter(function(r){ return r.xbot === xbotId; })[0] || null; }
export function receiverByMac(mac){ return state.bridge.receivers.filter(function(r){ return r.mac === mac; })[0] || null; }
export function isStreaming(rx){ return rx.state === "streaming"; }
export function streamingCount(){ return state.bridge.receivers.filter(isStreaming).length; }
export function receiverName(rx){ return rx.label || rx.name || rx.mac; }
export function historyOf(rx, key){ return state.bridge.history[key][rx.mac]; }
