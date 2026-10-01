/* Sparklines: the 60 s trend under every reading, with a hover readout. */
import {RX_PERIOD_S, RX_SAMPLES} from "./config.js";
import {READINGS} from "./labels.js";
import {historyOf} from "./state.js";
import {theme} from "./theme.js";
import {$, clamp, hexToRgba, maxAbs, readingStep, scaleTop} from "./util.js";

/* One series: 2px line, 10% wash, end dot ringed in the surface colour; oldest left, newest right. */
export function setTrend(c, vals, top, capacity, period, format){
  c._trend = {vals:vals, top:top, capacity:capacity, period:period, format:format};
  if (c._hover != null && c._hover >= vals.length) c._hover = vals.length-1;
  drawTrend(c);
}
export function drawTrend(c){
  var d = c._trend; if (!d) return;
  var dpr = Math.min(devicePixelRatio || 1, 2), W = c.clientWidth, H = c.clientHeight; if (!W || !H) return;
  if (c.width !== Math.round(W*dpr) || c.height !== Math.round(H*dpr)){ c.width = Math.round(W*dpr); c.height = Math.round(H*dpr); }
  var g = c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,W,H);
  var L = 5, R = W-6, T = 6, B = H-1.5, vals = d.vals, n = vals.length;
  g.strokeStyle = "#e4e6ea"; g.lineWidth = 1; g.beginPath(); g.moveTo(0,B); g.lineTo(W,B); g.stroke();
  if (!n) return;
  var X = function(j){ return R - (n-1-j)*(R-L)/(d.capacity-1); }, Y = function(v){ return B - Math.min(1, v/d.top)*(B-T); };
  function trace(){ g.beginPath(); vals.forEach(function(v, j){ if (j) g.lineTo(X(j), Y(v)); else g.moveTo(X(j), Y(v)); }); }
  trace(); g.lineTo(X(n-1),B); g.lineTo(X(0),B); g.closePath(); g.fillStyle = hexToRgba(theme.accent, .10); g.fill();
  trace(); g.strokeStyle = theme.accent; g.lineWidth = 2; g.lineJoin = g.lineCap = "round"; g.stroke();
  var j = c._hover != null ? clamp(c._hover, 0, n-1) : n-1;
  if (c._hover != null){ g.strokeStyle = "#cfd3da"; g.lineWidth = 1; g.beginPath(); g.moveTo(X(j)+.5,T-4); g.lineTo(X(j)+.5,B); g.stroke(); }
  g.beginPath(); g.arc(X(j), Y(vals[j]), 4, 0, 7); g.fillStyle = theme.accent; g.fill();
  g.strokeStyle = "#ffffff"; g.lineWidth = 2; g.stroke();
  c._X = X; c._n = n;
}
export const trendTip = $("ftip");
export function hoverableTrend(c){
  c.addEventListener("pointermove", function(e){
    var d = c._trend; if (!d || !c._n) return;
    var rect = c.getBoundingClientRect(), x = e.clientX - rect.left, best = 0, bestDx = Infinity;
    for (var j = 0; j < c._n; j++){ var dx = Math.abs(c._X(j)-x); if (dx < bestDx){ bestDx = dx; best = j; } }
    c._hover = best; drawTrend(c);
    var ago = (c._n-1-best)*d.period;
    trendTip.innerHTML = "<b>"+d.format(d.vals[best])+"</b> &nbsp;<i>"+(ago < .05 ? "now" : ago.toFixed(ago < 10 ? 1 : 0)+" s ago")+"</i>";
    trendTip.style.left = (rect.left + c._X(best))+"px"; trendTip.style.top = rect.top+"px"; trendTip.classList.add("on");
  });
  c.addEventListener("pointerleave", function(){ c._hover = null; drawTrend(c); trendTip.classList.remove("on"); });
}

/* ---------- a receiver's readings, side by side, each with its last minute ---------- */
export function readingsHtml(){
  return '<div class="pvi">'+READINGS.map(function(q){
    return '<div data-q="'+q.key+'"><div class="k">'+q.label+'</div><div class="v"><span class="n">—</span><small>'+q.unit+'</small></div>'+
      '<canvas class="spark" aria-label="'+q.label+' over the last 60 seconds"></canvas></div>'; }).join("")+'</div>';
}
export function bindReadings(el){ el.querySelectorAll(".pvi .spark").forEach(hoverableTrend); }
export function fillReadings(el, rx){
  READINGS.forEach(function(q){
    var cell = el.querySelector('.pvi [data-q="'+q.key+'"]'); if (!cell) return;
    cell.querySelector(".n").textContent = q.format(rx[q.key]);
    var h = historyOf(rx, q.key), vals = h ? h.vals() : [], max = maxAbs(vals);
    setTrend(cell.querySelector(".spark"), vals, scaleTop(max, readingStep(max), max > 0 ? 0 : 1), RX_SAMPLES, RX_PERIOD_S,
      function(v){ return q.format(v)+" "+q.unit; });
  });
}
