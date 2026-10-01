/* Small pure helpers: DOM lookup, escaping, number formatting, colour maths, rolling histories. */
import {SNAP_MM} from "./config.js";
import {theme} from "./theme.js";

export function clamp(v, lo, hi){ return Math.max(lo, Math.min(hi, v)); }
export function $(id){ return document.getElementById(id); }
export function esc(s){ return String(s).replace(/[&<>"]/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
export function snapMm(v){ return Math.round(v/SNAP_MM)*SNAP_MM; }
function niceCeil(v, step){ return Math.ceil(v/step)*step; }
export function maxAbs(vals){ return vals.reduce(function(m, v){ return Math.max(m, Math.abs(v)); }, 0); }
/* The top of a scale: a little over the largest value, rounded to a readable step. */
export function scaleTop(max, step, floor){ return Math.max(floor, niceCeil(max*1.1, step)); }
export function readingStep(max){ return max >= 10 ? 5 : max >= 1 ? 1 : .1; }

export function signed(v, dp){ return (v < 0 ? "−" : "")+Math.abs(v).toFixed(dp); }   // true minus sign
export function mmText(v){ return signed(Math.round(v), 0); }
export function xyzText(p){ return mmText(p.x)+", "+mmText(p.y)+", "+mmText(p.z)+" mm"; }
/* A receiver's readings, each a dash until the board has sent one. */
export function fmtW(v){ return v == null ? "—" : Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1); }
export function fmtV(v){ return v == null ? "—" : Math.abs(v) < 100 ? v.toFixed(2) : v.toFixed(1); }
export function fmtA(v){ return v == null ? "—" : Math.abs(v) < 10 ? v.toFixed(3) : v.toFixed(2); }
export function voltsAmpsText(rx){
  return rx && (rx.voltage != null || rx.current != null) ? fmtV(rx.voltage)+" V · "+fmtA(rx.current)+" A" : "";
}
export function kindLabel(kind){ var m = /^M(\d)(\d\d)(.*)$/.exec(kind || ""); return m ? "M"+m[1]+"-"+m[2]+m[3] : (kind || ""); }

export function rampColor(t){
  t = clamp(t, 0, 1);
  var i = t*(theme.ramp.length-1), lo = Math.floor(i), hi = Math.min(theme.ramp.length-1, lo+1), f = i-lo;
  var a = parseInt(theme.ramp[lo].slice(1), 16), b = parseInt(theme.ramp[hi].slice(1), 16);
  function mix(shift){ return Math.round(((a>>shift)&255)*(1-f)+((b>>shift)&255)*f) << shift; }
  return mix(16) | mix(8) | mix(0);
}
export function hexOf(n){ return "#"+("000000"+n.toString(16)).slice(-6); }
export function hexToInt(hex){ return parseInt(hex.slice(1), 16); }
export function hexToRgba(hex, alpha){ var n = hexToInt(hex); return "rgba("+(n>>16&255)+","+(n>>8&255)+","+(n&255)+","+alpha+")"; }
export function luminance(n){ return (.2126*((n>>16)&255) + .7152*((n>>8)&255) + .0722*(n&255))/255; }

/* Rolling history of the last n values. */
function makeRing(n){
  return {buf:new Float32Array(n), i:0, len:0,
    push:function(v){ this.buf[this.i] = v; this.i = (this.i+1)%n; if (this.len < n) this.len++; },
    vals:function(){ var out = []; for (var k = this.len; k > 0; k--) out.push(this.buf[(this.i-k+n)%n]); return out; }};
}
export function pushTo(rings, key, size, value){ (rings[key] = rings[key] || makeRing(size)).push(value); }
