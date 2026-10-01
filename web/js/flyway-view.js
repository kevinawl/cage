/* The flyway in 3D: the stator tiles coloured by power draw, and the xBots. */
import {DEG, FINISH, FLY_TILE, MOVER_MM, TILE_BASE} from "./config.js";
import {cameras, placeCamera, scenes, textSprite} from "./scene.js";
import {VIEW} from "./settings.js";
import {receiverOn, state} from "./state.js";
import {theme} from "./theme.js";
import {fmtW, hexToInt, luminance, maxAbs, rampColor, scaleTop} from "./util.js";

/* ---------- flyway: stator and xBots, drawn from what the PMC reports ----------
   Origin is the outer corner of the flyway in column 0, row 0, as in the PMC.
   Each tile is coloured by its power draw and carries its reading on the surface. */
const statorGroup = new THREE.Group(); scenes.fly.add(statorGroup);
const MAT_EDGE = new THREE.LineBasicMaterial({color:0xaab0ba});
export const MAT_MOVER = new THREE.MeshStandardMaterial({color:FINISH[VIEW.finish] || FINISH.graphite, roughness:.55, metalness:.25});
const TILE_LABEL_W = 512, TILE_LABEL_H = 160;
export let tiles = {}, flyAxes = [];
export function buildStator(layout){
  statorGroup.children.slice().forEach(function(o){ statorGroup.remove(o); });
  tiles = {};
  var T = layout ? layout.tile : FLY_TILE, cols = layout ? layout.cols : 4, rows = layout ? layout.rows : 1;
  var cells = layout && layout.flyways.length ? layout.flyways : defaultCells(cols, rows);
  var geo = new THREE.BoxGeometry(T-3, T-3, 30), edges = new THREE.EdgesGeometry(geo);
  cells.forEach(function(f){ tiles[f.id] = addTile(f, T, geo, edges); });
  addFlywayAxes();
  frameFlyway(cols, rows, T);
  paintTiles();
}
function defaultCells(cols, rows){
  var cells = [];
  for (var i = 0; i < cols*rows; i++) cells.push({id:i+1, col:i%cols, row:Math.floor(i/cols)});
  return cells;
}
function addTile(f, T, geo, edges){
  var x = (f.col+.5)*T, y = (f.row+.5)*T;
  var mat = new THREE.MeshStandardMaterial({color:TILE_BASE, roughness:.75, metalness:.2});
  var mesh = new THREE.Mesh(geo, mat); mesh.position.set(x, y, -15); mesh.userData.flyway = f.id; statorGroup.add(mesh);
  var edge = new THREE.LineSegments(edges, MAT_EDGE); edge.position.copy(mesh.position); statorGroup.add(edge);
  var c = document.createElement("canvas"); c.width = TILE_LABEL_W; c.height = TILE_LABEL_H;
  var tex = new THREE.CanvasTexture(c); tex.anisotropy = 4;
  var w = T*.84, label = new THREE.Mesh(new THREE.PlaneGeometry(w, w*TILE_LABEL_H/TILE_LABEL_W),
    new THREE.MeshBasicMaterial({map:tex, transparent:true, depthWrite:false}));
  label.position.set(x, y-T/2+14+w*TILE_LABEL_H/TILE_LABEL_W/2, .6); label.renderOrder = 1; label.visible = VIEW.tileLabels;
  statorGroup.add(label);
  return {mesh:mesh, mat:mat, canvas:c, tex:tex, painted:null, label:label};
}
function addFlywayAxes(){
  var geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,0,1), new THREE.Vector3(90,0,1),
    new THREE.Vector3(0,0,1), new THREE.Vector3(0,90,1)]);
  var lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({color:hexToInt(theme.accent)}));
  var x = textSprite("X", 34, theme.accent); x.position.set(104,-26,6);
  var y = textSprite("Y", 34, theme.accent); y.position.set(-26,104,6);
  flyAxes = [lines, x, y];
  flyAxes.forEach(function(o){ o.visible = VIEW.axes; statorGroup.add(o); });
}
function frameFlyway(cols, rows, T){
  var cam = cameras.fly, span = Math.max(cols*T, rows*T*2);
  cam.target = [cols*T/2, rows*T/2, 0]; cam.rad = span*.95 + 160; cam.az = -1.3; cam.pol = .88;
  if (state.sys === "fly") placeCamera();
}
/* Tile fill on the sequential ramp; label ink picked by the fill's luminance. */
export function paintTiles(){
  var readings = flywayReadings(), top = flywayPowerTop();
  Object.keys(tiles).forEach(function(id){
    var tile = tiles[id], f = readings[id], fill = f && VIEW.tileHeat ? rampColor(f.w/top) : TILE_BASE;
    tile.mat.color.setHex(fill);
    var key = f ? f.w.toFixed(1)+"|"+fill : "none";
    if (key === tile.painted) return;
    tile.painted = key;
    paintTileLabel(tile, id, f, luminance(fill) < .55);
  });
}
function paintTileLabel(tile, id, reading, onDark){
  var g = tile.canvas.getContext("2d"), soft = onDark ? "rgba(255,255,255,.72)" : "#5b6170";
  g.clearRect(0, 0, TILE_LABEL_W, TILE_LABEL_H);
  g.textBaseline = "alphabetic"; g.textAlign = "left";
  g.fillStyle = soft; g.font = '500 34px "Geist", sans-serif';
  g.fillText("Flyway "+id, 8, 44);
  var value = reading ? reading.w.toFixed(1) : "—";
  g.fillStyle = onDark ? "#ffffff" : "#15171c"; g.font = '600 84px "Geist", sans-serif';
  g.fillText(value, 4, 138);
  if (reading){
    var vw = g.measureText(value).width;
    g.fillStyle = soft; g.font = '500 40px "Geist", sans-serif';
    g.fillText("W", 14+vw, 138);
  }
  tile.tex.needsUpdate = true;
}
export const moverMeshes = {};                                  // xBot id -> group
function moverMesh(b){
  if (moverMeshes[b.id]) return moverMeshes[b.id];
  var size = MOVER_MM[b.kind] || MOVER_MM.M306, group = new THREE.Group();
  var body = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]), MAT_MOVER);
  body.position.z = size[2]/2; group.add(body);
  var c = document.createElement("canvas"); c.width = c.height = 512;           // the top face, printed
  var top = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]),
    new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(c), transparent:true, depthWrite:false}));
  top.material.map.anisotropy = 8; top.position.z = size[2]+.3; top.renderOrder = 1; group.add(top);
  var id = textSprite(String(b.id), 44, "#15171c", true); id.position.set(0, 0, size[2]+70); id.visible = VIEW.moverIds;
  group.add(id);
  group.userData.idSprite = id;
  group.userData.face = {canvas:c, tex:top.material.map, painted:null};
  scenes.fly.add(group); moverMeshes[b.id] = group;
  return group;
}
/* The top face: an accent bar on the +X edge (so Rz reads) and, when a receiver rides on
   this xBot, its power printed across the face. It turns with the mover. */
function paintMoverFace(group, rx){
  var face = group.userData.face; rx = VIEW.moverPower ? rx : null;
  var watts = rx ? rx.power : null;
  var key = (watts == null ? (rx ? "wait" : "none") : watts.toFixed(2))+"|"+theme.accent+"|"+VIEW.finish;
  if (key === face.painted) return;
  face.painted = key;
  var g = face.canvas.getContext("2d"); g.clearRect(0,0,512,512);
  var light = VIEW.finish !== "graphite", ink = light ? "#15171c" : "#ffffff", soft = light ? "rgba(21,23,28,.55)" : "rgba(255,255,255,.62)";
  g.fillStyle = theme.accent; g.beginPath();
  if (g.roundRect) g.roundRect(462, 128, 22, 256, 11); else g.rect(462, 128, 22, 256);
  g.fill();
  if (rx){
    g.textAlign = "center"; g.textBaseline = "alphabetic";
    g.fillStyle = soft; g.font = '500 44px "Geist", sans-serif'; g.fillText("Received", 236, 196);
    g.fillStyle = ink; g.font = '600 150px "Geist", sans-serif'; g.fillText(fmtW(watts), 236, 340);
    g.fillStyle = soft; g.font = '500 56px "Geist", sans-serif'; g.fillText("W", 236, 412);
  }
  face.tex.needsUpdate = true;
}
export function syncMovers(){
  var seen = {};
  state.fly.xbots.forEach(function(b){
    var group = moverMesh(b); seen[b.id] = true; group.visible = true;
    group.position.set(b.x, b.y, b.z);
    group.rotation.set(b.rx*DEG, b.ry*DEG, b.rz*DEG);
    paintMoverFace(group, receiverOn(b.id));
  });
  Object.keys(moverMeshes).forEach(function(id){ if (!seen[id]) moverMeshes[id].visible = false; });
}
export function flywayReadings(){
  var byId = {}; if (state.fly.telemetry) state.fly.telemetry.flyways.forEach(function(f){ byId[f.id] = f; }); return byId;
}
/* Shared scale for every flyway: the same watts read the same height and colour on every tile. */
export function flywayPowerTop(){
  var max = 0;
  Object.keys(state.fly.flywayPower).forEach(function(id){ max = Math.max(max, maxAbs(state.fly.flywayPower[id].vals())); });
  return scaleTop(max, 20, 40);
}
