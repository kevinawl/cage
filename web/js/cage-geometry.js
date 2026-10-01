/* The cage's 48 bars as geometry: where each runs, and where a point sits along one. */
import {BAR_LEN, CAGE, HALF, ON_BAR_MM} from "./config.js";
import {clamp} from "./util.js";

export function vec3(a){ return new THREE.Vector3(a[0], a[1], a[2]); }

/* A 2x2 lattice on every face. A line is kept only if it lies ON a face (nothing crosses the
   working volume), and each line is two bars joined at its middle: 24 lines, 48 bars. */
export const BARS = buildBars();
export const BAR_BY_ID = {}; BARS.forEach(function(b){ BAR_BY_ID[b.id] = b; });

function buildBars(){
  var AT = [-HALF, 0, HALF], LEVELS = [0, BAR_LEN, CAGE];
  var NS = byPosition(["S","C","N"]), WE = byPosition(["W","C","E"]);
  var LEVEL = {}; LEVEL[0] = "BOT"; LEVEL[BAR_LEN] = "MID"; LEVEL[CAGE] = "TOP";
  var SIDE = {S:"south", N:"north", W:"west", E:"east", C:"centre"};
  var bars = [];
  function byPosition(letters){ var o = {}; AT.forEach(function(v, i){ o[v] = letters[i]; }); return o; }
  function onFace(u, z){ return Math.abs(u) === HALF || z === 0 || z === CAGE; }
  function add(id, label, a, b, from){ bars.push(makeBar(id, label, a, b, from)); }

  LEVELS.forEach(function(z){ AT.forEach(function(y){
    if (!onFace(y, z)) return;
    [["W",-HALF,0],["E",0,HALF]].forEach(function(h){
      add("X-"+LEVEL[z]+"-"+NS[y]+"-"+h[0], LEVEL[z].toLowerCase()+" level, "+SIDE[NS[y]]+" line, "+SIDE[h[0]]+
        " bar, runs west→east", [h[1],y,z], [h[2],y,z], "west end");
    });
  }); });
  LEVELS.forEach(function(z){ AT.forEach(function(x){
    if (!onFace(x, z)) return;
    [["S",-HALF,0],["N",0,HALF]].forEach(function(h){
      add("Y-"+LEVEL[z]+"-"+WE[x]+"-"+h[0], LEVEL[z].toLowerCase()+" level, "+SIDE[WE[x]]+" line, "+SIDE[h[0]]+
        " bar, runs south→north", [x,h[1],z], [x,h[2],z], "south end");
    });
  }); });
  AT.forEach(function(x){ AT.forEach(function(y){
    if (Math.abs(x) !== HALF && Math.abs(y) !== HALF) return;
    var post = (NS[y] === "C" ? "" : NS[y])+(WE[x] === "C" ? "" : WE[x]);
    var where = (NS[y] === "C" ? "mid" : SIDE[NS[y]])+"/"+(WE[x] === "C" ? "mid" : SIDE[WE[x]]);
    add("Z-"+post+"-LO", "lower post at "+where, [x,y,0], [x,y,BAR_LEN], "floor");
    add("Z-"+post+"-HI", "upper post at "+where, [x,y,BAR_LEN], [x,y,CAGE], "mid joint");
  }); });
  return bars;
}
/* A bar is measured from its zero end A, the way a tape laid from that end reads. */
function makeBar(id, label, a, b, from){
  var A = vec3(a), B = vec3(b);
  return {id:id, label:label, from:from, A:A, B:B, dir:B.clone().sub(A).normalize()};
}
export function distanceAlong(bar, pos){ return clamp(pos.clone().sub(bar.A).dot(bar.dir), 0, BAR_LEN); }
export function positionOn(bar, s){ return bar.A.clone().add(bar.dir.clone().multiplyScalar(s)); }
/* The bar a point sits on, if any, and how far along it. */
export function barUnder(point){
  var P = new THREE.Vector3(point.x, point.y, point.z), best = null;
  BARS.forEach(function(bar){
    var s = distanceAlong(bar, P), d = positionOn(bar, s).distanceTo(P);
    if (d <= ON_BAR_MM && (!best || d < best.d)) best = {bar:bar, s:s, d:d};
  });
  return best;
}
