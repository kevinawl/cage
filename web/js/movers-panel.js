/* The Movers panel (Flyway): pose, lift, tracking error and received power per xBot. */
import {ERR_SAMPLES, ERR_WINDOW_MS} from "./config.js";
import {flyStatus} from "./header.js";
import {RX_STATE, XBOT_STATE} from "./labels.js";
import {dropCardsNotIn} from "./receivers-panel.js";
import {isStreaming, receiverName, receiverOn, state} from "./state.js";
import {bindReadings, fillReadings, hoverableTrend, readingsHtml, setTrend} from "./trends.js";
import {$, esc, kindLabel, maxAbs, scaleTop, signed} from "./util.js";

let moverCards = {};
export function renderMovers(){
  var list = $("mlist"), fly = state.fly;
  if (!fly.xbots.length){
    moverCards = {};
    list.innerHTML = noMoversHtml();
    return;
  }
  if (list.querySelector(".empty")) list.innerHTML = "";
  dropCardsNotIn(moverCards, fly.xbots.map(function(b){ return String(b.id); }));
  fly.xbots.forEach(function(b){
    var card = moverCards[b.id] || (moverCards[b.id] = makeMoverCard(list, b));
    fillMoverCard(card, b);
  });
}
function noMoversHtml(){
  var fly = state.fly, st = flyStatus();
  var title = fly.connected ? "No xBots on the flyway" : esc(st[1]);
  var body = fly.connected ? "The PMC is connected but reports no movers."
    : state.bridge.up ? esc(st[2] || "Waiting for the PMC.")
    : 'Run <code>bridge\\pmc_bridge.py</code>, then this view connects by itself.';
  return '<div class="empty"><b>'+title+'</b>'+body+'</div>';
}
function makeMoverCard(list, b){
  var el = document.createElement("div"); el.className = "mover";
  el.innerHTML = '<div class="hd"><span class="nm">xBot '+b.id+'</span><span class="kind"></span>'+
    '<span class="state"></span></div><div class="mrx" hidden><div class="k">Received · <b class="rxn"></b></div>'+readingsHtml()+'</div>'+
    '<div class="coords"></div>'+
    '<div class="mstats"><div class="mstat"><div class="k">Lift</div><div class="v"><span class="fz">—</span><small>N</small></div>'+
    '<div class="s mass"></div><div class="s fxy"></div></div>'+
    '<div class="mstat"><div class="k">Tracking error</div><div class="v"><span class="e">—</span><small>µm</small></div>'+
    '<canvas class="spark" aria-label="Tracking error over the last 30 seconds"></canvas><div class="s exyz"></div></div></div>';
  list.appendChild(el);
  var card = {el:el, kind:el.querySelector(".kind"), status:el.querySelector(".state"), pose:el.querySelector(".coords"),
    lift:el.querySelector(".fz"), mass:el.querySelector(".mass"), sideForce:el.querySelector(".fxy"),
    error:el.querySelector(".e"), errorTrend:el.querySelector(".mstats .spark"), errorXyz:el.querySelector(".exyz"),
    received:el.querySelector(".mrx"), receiver:el.querySelector(".rxn")};
  hoverableTrend(card.errorTrend); bindReadings(el);
  return card;
}
function fillMoverCard(card, b){
  var st = XBOT_STATE[b.state] || ["s-crit", b.state.replace(/^XBOT_/,"").toLowerCase()];
  card.kind.textContent = kindLabel(b.kind);
  card.status.className = "state "+st[0]; card.status.innerHTML = '<span class="d"></span>'+esc(st[1]);
  card.pose.innerHTML = poseHtml(b);
  fillMoverReceiver(card, receiverOn(b.id));
  fillMoverForce(card, (state.fly.telemetry ? state.fly.telemetry.force : {})[b.id]);
  fillMoverTracking(card, b.id);
}
function poseHtml(b){
  function v(n, unit, dp){ return '<span>'+signed(+n.toFixed(dp) || 0, dp)+'<i>'+unit+'</i></span>'; }   // no "-0.00"
  return '<b>X</b>'+v(b.x," mm",1)+'<b>Rx</b>'+v(b.rx,"°",2)+'<b>Y</b>'+v(b.y," mm",1)+
    '<b>Ry</b>'+v(b.ry,"°",2)+'<b>Z</b>'+v(b.z," mm",2)+'<b>Rz</b>'+v(b.rz,"°",2);
}
function fillMoverReceiver(card, rx){
  card.received.hidden = !rx;
  if (!rx) return;
  card.receiver.textContent = receiverName(rx) + (isStreaming(rx) ? "" : " · "+(RX_STATE[rx.state] || ["",""])[1].toLowerCase());
  fillReadings(card.received, rx);
}
function fillMoverForce(card, force){
  card.lift.textContent = force ? force[2].toFixed(2) : "—";
  card.mass.textContent = force ? "≈ "+(force[2]/9.81).toFixed(2)+" kg held" : "Waiting for force";
  card.sideForce.textContent = force ? "Fx "+signed(force[0],2)+"  Fy "+signed(force[1],2) : "";
}
function fillMoverTracking(card, id){
  var t = state.fly.tracking, mean = t.shown[id], h = t.history[id], vals = h ? h.vals() : [];
  card.error.textContent = !mean ? "—" : mean.m < 10 ? mean.m.toFixed(2) : mean.m.toFixed(1);
  card.errorXyz.textContent = mean ? "X "+signed(mean.x,1)+" Y "+signed(mean.y,1)+" Z "+signed(mean.z,1) : "";
  setTrend(card.errorTrend, vals, scaleTop(maxAbs(vals), 1, 2), ERR_SAMPLES, ERR_WINDOW_MS/1000,
    function(x){ return x.toFixed(2)+" µm, "+(ERR_WINDOW_MS/1000)+" s mean"; });
}
