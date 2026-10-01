/* The Receivers panel: one card per Saguaro board, with its readings and where it is placed. */
import {messageFor, postReceiver} from "./bridge.js";
import {READINGS, RX_STATE} from "./labels.js";
import {isStreaming, pointById, receiverName, state, streamingCount} from "./state.js";
import {bindReadings, fillReadings, readingsHtml} from "./trends.js";
import {$, esc} from "./util.js";

export let receiverCards = {};
export function renderReceivers(){
  var list = $("rxblist"), boards = state.bridge.receivers;
  $("rxbCount").innerHTML = boards.length ? "<b>"+streamingCount()+"</b> of "+boards.length+" streaming" : "";
  if (!boards.length){
    receiverCards = {};
    list.innerHTML = state.bridge.up
      ? '<div class="empty"><b>No receivers found</b>Saguaro boards announce themselves on 224.0.0.251:4210. '+
        'Power one on, on the same network as this PC, and it appears here.</div>'
      : '<div class="empty"><b>Bridge offline</b>Receivers are found by the bridge.</div>';
    return;
  }
  if (list.querySelector(".empty")) list.innerHTML = "";
  dropCardsNotIn(receiverCards, boards.map(function(rx){ return rx.mac; }));
  boards.forEach(function(rx){
    var card = receiverCards[rx.mac] || (receiverCards[rx.mac] = makeReceiverCard(list));
    card.rx = rx;
    fillReceiverCard(card, rx);
  });
}
export function dropCardsNotIn(cards, keys){
  Object.keys(cards).forEach(function(k){ if (keys.indexOf(k) < 0){ cards[k].el.remove(); delete cards[k]; } });
}
function makeReceiverCard(list){
  var el = document.createElement("div"); el.className = "rxb";
  el.innerHTML = '<div class="rxb-hd"><span class="rxb-nm"></span><span class="state"></span>'+
    '<button class="btn sm act"></button></div><div class="rxb-id"></div>'+readingsHtml()+
    '<div class="rxb-sel"><div><label class="sxl">Rides on</label><select class="sx" aria-label="Where this receiver is"></select></div>'+
    READINGS.map(function(q){ return '<div><label>'+q.label+' from</label><select data-ep="'+q.key+'" aria-label="Endpoint that carries '+
      q.key+'"></select></div>'; }).join("")+'</div>'+
    '<div class="rxb-eps"></div><div class="rxb-err" hidden></div>';
  list.appendChild(el);
  var card = {el:el, rx:null, placementKey:null, endpointKeys:{},
    name:el.querySelector(".rxb-nm"), status:el.querySelector(".state"), action:el.querySelector(".act"),
    id:el.querySelector(".rxb-id"), readings:el.querySelector(".pvi"), place:el.querySelector(".sx"), placeLabel:el.querySelector(".sxl"),
    others:el.querySelector(".rxb-eps"), error:el.querySelector(".rxb-err")};
  bindReadings(el);
  card.action.onclick = function(){
    var busy = ["streaming","connecting","handshake"].indexOf(card.rx.state) >= 0;
    postReceiver(card.rx.mac, busy ? "disconnect" : "connect");
  };
  card.place.onchange = function(){
    if (state.sys === "cage") placeAtPoint(card.rx, this.value || null);
    else postReceiver(card.rx.mac, null, {xbot: this.value === "" ? null : +this.value});
  };
  READINGS.forEach(function(q){
    el.querySelector('[data-ep="'+q.key+'"]').onchange = function(){
      var body = {}; body[q.endpointField] = this.value || null; postReceiver(card.rx.mac, null, body);
    };
  });
  return card;
}
function placeAtPoint(rx, pointId){
  rx.point = pointId; if (pointId) rx.xbot = null;
  postReceiver(rx.mac, null, {point:pointId});
}
function fillReceiverCard(card, rx){
  var st = RX_STATE[rx.state] || ["s-off", rx.state];
  card.name.textContent = receiverName(rx);
  card.status.className = "state "+st[0]; card.status.innerHTML = '<span class="d"></span>'+st[1];
  card.status.title = rx.error || "";
  card.action.textContent = rx.state === "idle" ? "Connect" : "Disconnect";
  card.id.textContent = [receiverName(rx) !== rx.mac && rx.mac, rx.ip && rx.ip+":"+rx.port, rx.fw && "fw "+rx.fw]
    .filter(Boolean).join(" · ");
  card.readings.hidden = !isStreaming(rx);
  if (isStreaming(rx)) fillReadings(card.el, rx);
  if (state.sys === "cage") fillPointPlacement(card, rx); else fillXbotPlacement(card, rx);
  fillEndpointChoices(card, rx);
  card.others.innerHTML = otherEndpointsHtml(rx);
  var text = messageFor(rx.mac) || (rx.state === "error" ? rx.error : "");
  card.error.hidden = !text; card.error.textContent = text || "";
}
/* The placement select: a cage point in the Cage view, an xBot in the Flyway view.
   Options rebuilt only when they change, so an open dropdown isn't reset. */
function fillPointPlacement(card, rx){
  card.placeLabel.textContent = "At point";
  var key = "cage|"+state.cage.points.map(function(p){ return p.id+":"+p.name; }).join(",")+"|"+rx.point+"|"+rx.xbot;
  if (key === card.placementKey || card.place === document.activeElement) return;
  card.placementKey = key;
  card.place.innerHTML = '<option value="">'+(rx.xbot != null ? "On xBot "+rx.xbot : "Not placed")+'</option>'+
    state.cage.points.map(function(p){ return '<option value="'+esc(p.id)+'">'+esc(p.name)+'</option>'; }).join("");
  card.place.value = rx.point && pointById(rx.point) ? rx.point : "";
}
function fillXbotPlacement(card, rx){
  card.placeLabel.textContent = "Rides on";
  var bots = state.fly.xbots.map(function(b){ return b.id; });
  var key = "fly|"+bots.join(",")+"|"+rx.xbot;
  if (key === card.placementKey) return;
  card.placementKey = key;
  var options = bots.slice(); if (rx.xbot != null && options.indexOf(rx.xbot) < 0) options.push(rx.xbot);
  card.place.innerHTML = '<option value="">Not assigned</option>'+options.map(function(id){
    return '<option value="'+id+'">xBot '+id+(bots.indexOf(id) < 0 ? " (not on flyway)" : "")+'</option>'; }).join("");
  card.place.value = rx.xbot == null ? "" : String(rx.xbot);
}
function fillEndpointChoices(card, rx){
  var names = rx.endpoints.filter(function(e){ return e.type === "float" || e.type === "int"; }).map(function(e){ return e.name; });
  READINGS.forEach(function(q){
    var select = card.el.querySelector('[data-ep="'+q.key+'"]'), chosen = rx[q.endpointName];
    var key = names.join(",")+"|"+chosen;
    if (key === card.endpointKeys[q.key] || select === document.activeElement) return;
    card.endpointKeys[q.key] = key;
    var options = names.slice(); if (chosen && options.indexOf(chosen) < 0) options.push(chosen);
    select.innerHTML = '<option value="">'+(options.length ? "Choose…" : "Connect to list")+'</option>'+
      options.map(function(n){ return '<option>'+esc(n)+'</option>'; }).join("");
    select.value = chosen || "";
  });
}
/* Everything else the board reports, small, under the selects. */
function otherEndpointsHtml(rx){
  var shown = READINGS.map(function(q){ return rx[q.endpointName]; });
  return rx.endpoints.filter(function(e){ return shown.indexOf(e.name) < 0; }).map(function(e){
    return '<span>'+esc(e.name)+' <b>'+endpointValueText(e.value)+'</b></span>'; }).join("");
}
function endpointValueText(v){
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3);
  if (typeof v === "boolean") return v ? "on" : "off";
  return esc(String(v));
}
