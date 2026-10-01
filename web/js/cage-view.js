/* The cage in 3D: bars, rulers, the stand, the measured points and the hover ghost. */
import {BARS, vec3} from "./cage-geometry.js";
import {BAR_LEN, BAR_SECTION, CAGE, GRID_MM, HALF, POINT_IDLE, POINT_WAITING, STAND_X, STAND_Y} from "./config.js";
import {scenes, textSprite} from "./scene.js";
import {VIEW} from "./settings.js";
import {historyOf, receiverAt, selectedPoint, state} from "./state.js";
import {theme} from "./theme.js";
import {fmtW, hexToInt, maxAbs, rampColor, readingStep, scaleTop, voltsAmpsText} from "./util.js";

export const barMeshes = [];
(function buildCage(){
  var mat = new THREE.MeshStandardMaterial({color:0x2a2a33, roughness:.55, metalness:.4});
  BARS.forEach(function(bar){
    var m = new THREE.Mesh(new THREE.BoxGeometry(BAR_SECTION, BAR_SECTION, BAR_LEN), mat);
    m.position.copy(bar.A.clone().add(bar.B).multiplyScalar(.5));
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), bar.dir);
    m.userData.bar = bar.id;
    scenes.cage.add(m); barMeshes.push(m);
  });
  var grid = new THREE.GridHelper(CAGE, CAGE/GRID_MM, 0xc3c6ce, 0xc3c6ce);
  grid.rotation.x = Math.PI/2; grid.position.z = 1; scenes.cage.add(grid);
})();

/* ---------- cage: rulers and axes, in the same coordinates the points are typed in ----------
   X along the south side and Y along the west side, both on the floor; Z standing off the
   north-west post. Ticks every 250 mm, numbered every 500; the long ticks are the joints, and
   each 1.5 m span between them is one bar, labelled as such. */
const RULER_GAP = 380;                        // from the frame to the rulers
let scaleObjects = [];
export function buildScale(){
  scaleObjects.forEach(function(o){
    scenes.cage.remove(o);
    if (o.material && o.material.map) o.material.map.dispose();
  });
  scaleObjects = [];
  var segs = [], x0 = -HALF-RULER_GAP, y0 = -HALF-RULER_GAP, y1 = HALF+RULER_GAP;
  function seg(a, b){ segs.push(vec3(a), vec3(b)); }
  function label(text, at, h, color){
    var s = textSprite(text, h, color || "#4f5563", true); s.position.set(at[0], at[1], at[2]); scaleObjects.push(s);
  }
  function mm(v){ return v < 0 ? "−"+(-v) : String(v); }
  function tick(v){ return v % BAR_LEN === 0 ? 90 : v % 500 === 0 ? 55 : 32; }

  seg([-HALF,y0,0],[HALF,y0,0]); seg([x0,-HALF,0],[x0,HALF,0]); seg([x0,y1,0],[x0,y1,CAGE]);
  [-HALF,0,HALF].forEach(function(v){                              // extension lines from every joint
    seg([v,-HALF-30,0],[v,y0-20,0]); seg([-HALF-30,v,0],[x0-20,v,0]);
  });
  [0,BAR_LEN,CAGE].forEach(function(z){ seg([-HALF-25,HALF+25,z],[x0-15,y1+15,z]); });
  for (var v = -HALF; v <= HALF; v += GRID_MM){
    seg([v,y0,0],[v,y0-tick(v),0]); seg([x0,v,0],[x0-tick(v),v,0]);
    if (v % 500 === 0){ label(mm(v), [v, y0-250, 0], 150); label(mm(v), [x0-370, v, 0], 150); }
  }
  for (var z = 0; z <= CAGE; z += GRID_MM){
    seg([x0,y1,z],[x0-tick(z),y1,z]);
    if (z % 500 === 0) label(mm(z), [x0-370, y1, z], 150);
  }
  [-HALF/2, HALF/2].forEach(function(c){
    label("1.5 m", [c, y0+190, 0], 130); label("1.5 m", [x0+190, c, 0], 130); label("1.5 m", [x0+190, y1, c+HALF], 130);
  });
  label("X, 3 m", [0, y0-560, 0], 200, theme.accent);
  label("Y, 3 m", [x0-950, 0, 0], 200, theme.accent);
  label("Z, 3 m", [x0-250, y1, CAGE+330], 200, theme.accent);
  scaleObjects.push(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(segs),
    new THREE.LineBasicMaterial({color:0x6b7180})));
  addOriginAxes(label);
  scaleObjects.forEach(function(o){ o.visible = VIEW.cScale; scenes.cage.add(o); });
}
function addOriginAxes(label){
  var O = [0,0,2];
  scaleObjects.push(new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints([vec3(O),vec3([300,0,2]),vec3(O),vec3([0,300,2]),vec3(O),vec3([0,0,300])]),
    new THREE.LineBasicMaterial({color:hexToInt(theme.accent)})));
  label("X", [390, 0, 10], 90, theme.accent); label("Y", [0, 390, 10], 90, theme.accent); label("Z", [0, 0, 390], 90, theme.accent);
}

/* ---------- the stand: PSU + TX electronics, off the south-east corner ---------- */
(function buildStand(){
  var steel = new THREE.MeshStandardMaterial({color:0x9a9aa6, roughness:.45, metalness:.75});
  var panel = new THREE.MeshStandardMaterial({color:0xd6d6dd, roughness:.6, metalness:.3});
  var dark  = new THREE.MeshStandardMaterial({color:0x3c3c48, roughness:.5, metalness:.5});
  function led(color, glow){ return new THREE.MeshStandardMaterial({color:color, emissive:color, emissiveIntensity:glow}); }
  function box(w, d, h, dx, dy, z, mat){                          // dx, dy from the stand's centre
    var m = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), mat);
    m.position.set(STAND_X+dx, STAND_Y+dy, z); scenes.cage.add(m);
  }
  var W = 620, D = 820, H = 980, MID = H*.46;
  [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(function(c){ box(45, 45, H, c[0]*(W/2-25), c[1]*(D/2-25), H/2, steel); });
  box(W, D, 26, 0, 0, H, panel);                                   // shelves
  box(W, D, 22, 0, 0, MID, panel);
  box(W, D, 22, 0, 0, 90, panel);
  box(500, 330, 190, 0, -90, H+108, panel);                        // PSU on top
  box(14, 300, 150, -250, -90, H+108, dark);
  box(60, 26, 26, -258, -190, H+150, led(0x2a78d6, .7));
  box(440, 300, 210, 0, -40, MID+116, dark);                       // TX electronics in the middle
  box(70, 24, 24, -226, -140, MID+180, led(0x2f6fdb, .8));
})();

/* ---------- cage points: a ball where the receiver sits, a drop line to the floor, a label ---------- */
const BALL = new THREE.SphereGeometry(60, 24, 16), HALO = new THREE.SphereGeometry(95, 24, 16), FOOT = new THREE.RingGeometry(24, 38, 24);
const MAT_DROP = new THREE.LineDashedMaterial({color:0x878d99, dashSize:45, gapSize:32});
const MAT_FOOT = new THREE.MeshBasicMaterial({color:0x878d99, side:THREE.DoubleSide});
const LABEL_W = 512, LABEL_H = 200;
export const pointMeshes = {};
function pointMesh(point){
  var m = pointMeshes[point.id]; if (m) return m;
  var ball = new THREE.Mesh(BALL, new THREE.MeshStandardMaterial({color:POINT_IDLE, roughness:.4, metalness:.2}));
  var halo = new THREE.Mesh(HALO, new THREE.MeshBasicMaterial({transparent:true, opacity:.25, depthWrite:false}));
  var drop = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), MAT_DROP);
  var foot = new THREE.Mesh(FOOT, MAT_FOOT);
  var c = document.createElement("canvas"); c.width = LABEL_W; c.height = LABEL_H;
  var label = new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c), depthTest:false, transparent:true}));
  label.scale.set(920, 920*LABEL_H/LABEL_W, 1); label.center.set(.5, 0); label.renderOrder = 3;
  ball.userData.point = point.id;
  m = pointMeshes[point.id] = {ball:ball, halo:halo, drop:drop, foot:foot, label:label, canvas:c, painted:null, at:null};
  [ball, halo, drop, foot, label].forEach(function(o){ scenes.cage.add(o); });
  return m;
}
/* The ghost: a see-through ball at the snapped spot on the bar under the pointer, i.e. where a click would put the selected point. */
const ghost = new THREE.Mesh(BALL, new THREE.MeshBasicMaterial({transparent:true, opacity:.35, depthWrite:false}));
ghost.visible = false; ghost.renderOrder = 2; scenes.cage.add(ghost);
export function showGhost(hit){
  ghost.position.copy(hit.pos);
  ghost.material.color.setHex(selectedPoint() ? hexToInt(theme.accent) : 0x6b7180);
  ghost.visible = true;
}
export function hideGhost(){ ghost.visible = false; }
function removePointMesh(id){
  var m = pointMeshes[id];
  [m.ball, m.halo, m.drop, m.foot, m.label].forEach(function(o){ scenes.cage.remove(o); });
  m.ball.material.dispose(); m.halo.material.dispose(); m.drop.geometry.dispose(); m.label.material.map.dispose();
  delete pointMeshes[id];
}
/* Name and watts on the first line, volts and amps under it; one line sits on the point. */
function paintPointLabel(m, point, rx){
  var watts = rx ? rx.power : null, va = voltsAmpsText(rx);
  var key = point.name+"|"+fmtW(watts)+"|"+va;
  if (key === m.painted) return;
  m.painted = key;
  var g = m.canvas.getContext("2d"), title = watts == null ? point.name : point.name+"  "+fmtW(watts)+" W";
  g.clearRect(0, 0, LABEL_W, LABEL_H);
  g.textAlign = "center"; g.textBaseline = "alphabetic"; g.lineJoin = "round"; g.lineWidth = 12;
  g.strokeStyle = "rgba(255,255,255,.92)";
  function line(text, px, weight, y, ink){
    g.font = weight+" "+px+'px "Geist", sans-serif';
    var w = g.measureText(text).width, room = LABEL_W-32;
    if (w > room) g.font = weight+" "+Math.floor(px*room/w)+'px "Geist", sans-serif';
    g.strokeText(text, LABEL_W/2, y); g.fillStyle = ink; g.fillText(text, LABEL_W/2, y);
  }
  if (va){ line(title, 50, 600, 104, "#15171c"); line(va, 40, 500, 164, "#4f5563"); }
  else line(title, 50, 600, 164, "#15171c");
  m.label.material.map.needsUpdate = true;
}
export function pointColor(rx, top){
  if (!rx) return POINT_IDLE;
  return rx.power == null ? POINT_WAITING : rampColor(rx.power/top);
}
export function syncPoints(){
  var cage = state.cage, seen = {}, top = cagePowerTop();
  cage.points.forEach(function(point){
    var m = pointMesh(point), rx = receiverAt(point.id), selected = cage.selected === point.id;
    seen[point.id] = true;
    m.ball.position.set(point.x, point.y, point.z); m.halo.position.copy(m.ball.position);
    m.ball.material.color.setHex(pointColor(rx, top));
    m.halo.visible = selected || state.hover === point.id;
    m.halo.material.color.setHex(selected ? hexToInt(theme.accent) : 0x6b7180);
    m.halo.material.opacity = selected ? .28 : .16;
    placeDropLine(m, point);
    m.label.visible = VIEW.cLabels; m.label.position.set(point.x, point.y, point.z+75);
    paintPointLabel(m, point, rx);
  });
  Object.keys(pointMeshes).forEach(function(id){ if (!seen[id]) removePointMesh(id); });
}
function placeDropLine(m, point){
  var at = point.x+","+point.y+","+point.z;
  if (at !== m.at){
    m.at = at;
    var pos = m.drop.geometry.attributes.position;
    pos.setXYZ(0, point.x, point.y, point.z); pos.setXYZ(1, point.x, point.y, 1.5); pos.needsUpdate = true;
    m.drop.geometry.computeBoundingSphere(); m.drop.computeLineDistances();
  }
  m.drop.visible = m.foot.visible = VIEW.cDrops && point.z > 5;
  m.foot.position.set(point.x, point.y, 1.5);
}
/* Power scale for the points: 0 to a little over the highest reading in the last minute. */
export function cagePowerTop(){
  var max = 0;
  state.bridge.receivers.forEach(function(rx){
    var h = rx.point != null && historyOf(rx, "power");
    if (h) max = Math.max(max, maxAbs(h.vals()));
  });
  return scaleTop(max, readingStep(max), 1);
}
