/* The Flyways panel: one card per stator tile with its power draw and temperatures. */
import {FLYWAY_PERIOD_S, FLYWAY_SAMPLES} from "./config.js";
import {flywayPowerTop, flywayReadings} from "./flyway-view.js";
import {state} from "./state.js";
import {hoverableTrend, setTrend} from "./trends.js";
import {$, esc, hexOf, rampColor} from "./util.js";

let flywayCards = {};
export function buildFlywayPanel(){
  var layout = state.fly.layout, grid = $("fwgrid"); if (!layout) return;
  var cells = layout.flyways.slice().sort(function(a, b){ return b.row-a.row || a.col-b.col; });   // plan view: +Y at top
  grid.style.setProperty("--cols", layout.cols);
  grid.innerHTML = cells.map(function(f){
    return '<div class="fw" data-id="'+f.id+'"><div class="fw-hd"><span class="fw-sw"></span>Flyway '+f.id+
      (f.sn ? '<span class="fw-sn">SN '+esc(f.sn)+'</span>' : '')+'</div>'+
      '<div class="fw-val"><span class="n">—</span><small>W</small></div><div class="fw-tag"></div>'+
      '<canvas class="spark" aria-label="Flyway '+f.id+' power over the last 60 seconds"></canvas>'+
      '<div class="fw-temps"><div>CPU<b class="cpu">—</b></div><div>Amplifier<b class="amp">—</b></div>'+
      '<div>Motor<b class="mot">—</b></div></div></div>';
  }).join("");
  flywayCards = {};
  grid.querySelectorAll(".fw").forEach(function(el){
    var trend = el.querySelector(".spark"); hoverableTrend(trend);
    flywayCards[el.dataset.id] = {power:el.querySelector(".n"), swatch:el.querySelector(".fw-sw"), carrying:el.querySelector(".fw-tag"),
      trend:trend, cpu:el.querySelector(".cpu"), amp:el.querySelector(".amp"), motor:el.querySelector(".mot")};
  });
  renderFlyways();
}
export function renderFlyways(){
  var readings = flywayReadings(), top = flywayPowerTop(), total = 0, any = false;
  Object.keys(flywayCards).forEach(function(id){
    var card = flywayCards[id], f = readings[id], h = state.fly.flywayPower[id];
    if (f){ total += f.w; any = true; }
    card.power.textContent = f ? f.w.toFixed(1) : "—";
    card.swatch.style.background = f ? hexOf(rampColor(f.w/top)) : "";
    card.cpu.textContent = f ? f.cpu.toFixed(1)+" °C" : "—";
    card.amp.textContent = f ? f.amp.toFixed(1)+" °C" : "—";
    card.motor.textContent = f ? f.motor.toFixed(1)+" °C" : "—";
    var on = moversOn(id);
    card.carrying.innerHTML = on.length ? "Carrying <b>"+on.map(function(b){ return "xBot "+b.id; }).join(", ")+"</b>" : "No mover";
    setTrend(card.trend, h ? h.vals() : [], top, FLYWAY_SAMPLES, FLYWAY_PERIOD_S, function(v){ return v.toFixed(1)+" W"; });
  });
  $("fwSub").textContent = "Power draw, last 60 s · shared scale 0–"+top+" W";
  $("fwTotal").innerHTML = any ? "Total <b>"+total.toFixed(1)+" W</b>" : "";
  $("flyMax").textContent = top+" W";
}
function moversOn(flywayId){
  var layout = state.fly.layout; if (!layout) return [];
  var f = layout.flyways.filter(function(x){ return String(x.id) === String(flywayId); })[0]; if (!f) return [];
  var T = layout.tile;
  return state.fly.xbots.filter(function(b){
    return b.x >= f.col*T && b.x < (f.col+1)*T && b.y >= f.row*T && b.y < (f.row+1)*T; });
}
