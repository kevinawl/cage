/* Mouse and touch on the 3D view: orbit, zoom, hover tips, and picking points and bars. */
import {BAR_BY_ID, distanceAlong, positionOn} from "./cage-geometry.js";
import {barMeshes, hideGhost, pointMeshes, showGhost} from "./cage-view.js";
import {CLICK_SLOP_PX, ORBIT_PER_PX, POLAR_MAX, POLAR_MIN, ZOOM_LIMITS, ZOOM_STEP} from "./config.js";
import {flywayReadings, tiles} from "./flyway-view.js";
import {movePoint, renderPoints} from "./points-panel.js";
import {cameras, canvas3d, placeCamera} from "./scene.js";
import {pointById, receiverAt, receiverName, selectedPoint, state} from "./state.js";
import {$, clamp, esc, fmtW, snapMm, voltsAmpsText, xyzText} from "./util.js";

const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
const viewTip = $("tip");
const pointer = {down:false, x:0, y:0, moved:0, id:null, overBar:null};
canvas3d.style.touchAction = "none";
canvas3d.addEventListener("pointerdown", function(e){
  canvas3d.setPointerCapture(e.pointerId);
  pointer.down = true; pointer.x = e.clientX; pointer.y = e.clientY; pointer.moved = 0; pointer.id = e.pointerId;
  if (state.sys === "cage" && state.hover && state.hover === state.cage.selected) state.dragging = true;
});
canvas3d.addEventListener("pointermove", function(e){
  var rect = canvas3d.getBoundingClientRect(), px = e.clientX-rect.left, py = e.clientY-rect.top;
  if (!pointer.down){ hoverAt(px, py); return; }
  var dx = e.clientX-pointer.x, dy = e.clientY-pointer.y;
  pointer.moved += Math.abs(dx)+Math.abs(dy); pointer.x = e.clientX; pointer.y = e.clientY;
  if (state.dragging && state.cage.selected){ dragSelected(px, py); return; }
  hideGhost(); orbit(dx, dy);
});
canvas3d.addEventListener("pointerleave", function(){ if (!pointer.down){ state.hover = null; hideViewTip(); hideGhost(); } });
canvas3d.addEventListener("pointerup", endPointer);
canvas3d.addEventListener("pointercancel", endPointer);
canvas3d.addEventListener("wheel", function(e){ e.preventDefault(); zoom(Math.sign(e.deltaY)); }, {passive:false});

function orbit(dx, dy){
  var c = cameras[state.sys];
  c.az -= dx*ORBIT_PER_PX; c.pol = clamp(c.pol-dy*ORBIT_PER_PX, POLAR_MIN, POLAR_MAX);
  placeCamera();
}
function zoom(direction){
  var c = cameras[state.sys], limits = ZOOM_LIMITS[state.sys];
  c.rad = clamp(c.rad*(1+direction*ZOOM_STEP), limits[0], limits[1]);
  placeCamera();
}
/* A click on a point selects it; a click on a bar puts the selected point there. */
function endPointer(){
  var clicked = pointer.down && pointer.moved < CLICK_SLOP_PX && !state.dragging;
  if (clicked && state.sys === "cage"){
    var point = selectedPoint();
    if (state.hover){ state.cage.selected = state.hover; renderPoints(); }
    else if (pointer.overBar && point) movePoint(point, pointer.overBar.pos);
  }
  pointer.down = false; state.dragging = false;
  if (pointer.id !== null){ try { canvas3d.releasePointerCapture(pointer.id); } catch(e){} pointer.id = null; }
}
function dragSelected(px, py){
  var point = selectedPoint(), hit = barAt(px, py);
  if (point && hit) movePoint(point, hit.pos);
}
function castFrom(px, py, camera){
  ndc.x = px/canvas3d.clientWidth*2-1; ndc.y = -(py/canvas3d.clientHeight)*2+1;
  ray.setFromCamera(ndc, camera);
}
/* Where the pointer meets a bar, snapped along it: the same number a tape from the bar's zero end gives. */
function barAt(px, py){
  castFrom(px, py, cameras.cage.obj);
  var hit = ray.intersectObjects(barMeshes, false)[0]; if (!hit) return null;
  var bar = BAR_BY_ID[hit.object.userData.bar], s = snapMm(distanceAlong(bar, hit.point));
  return {bar:bar, s:s, pos:positionOn(bar, s)};
}
function pointAt(px, py){
  castFrom(px, py, cameras.cage.obj);
  var balls = Object.keys(pointMeshes).map(function(id){ return pointMeshes[id].ball; });
  var hit = ray.intersectObjects(balls, false)[0];
  return hit ? hit.object.userData.point : null;
}
function showViewTip(px, py, html){
  viewTip.innerHTML = html; viewTip.style.left = px+"px"; viewTip.style.top = py+"px"; viewTip.classList.add("on");
}
export function hideViewTip(){ viewTip.classList.remove("on"); }
function hoverAt(px, py){
  if (state.sys === "cage") hoverCage(px, py); else hoverFlyway(px, py);
}
function hoverCage(px, py){
  var id = pointAt(px, py);
  state.hover = id; pointer.overBar = null; hideGhost();
  if (id){ hoverPoint(px, py, id); return; }
  var hit = barAt(px, py);
  if (hit){ hoverBar(px, py, hit); return; }
  canvas3d.style.cursor = "grab"; hideViewTip();
}
function hoverPoint(px, py, id){
  var point = pointById(id), rx = receiverAt(id), selected = id === state.cage.selected;
  canvas3d.style.cursor = selected ? "move" : "pointer";
  showViewTip(px, py, "<b>"+esc(point.name)+"</b>"+(rx && rx.power != null ? " &nbsp;"+fmtW(rx.power)+" W" : "")+
    (voltsAmpsText(rx) ? " &nbsp;"+voltsAmpsText(rx) : "")+
    "<br><i>"+xyzText(point)+" &middot; "+(rx ? esc(receiverName(rx)) : "no receiver")+
    (selected ? " &middot; drag along the bars" : "")+"</i>");
}
function hoverBar(px, py, hit){
  var point = selectedPoint();
  pointer.overBar = hit; showGhost(hit);
  canvas3d.style.cursor = point ? "copy" : "grab";
  showViewTip(px, py, "<b>"+hit.bar.id+"</b> &nbsp;"+hit.s+" mm <i>from the "+hit.bar.from+"</i><br><i>"+xyzText(hit.pos)+
    (point ? " &middot; click to put "+esc(point.name)+" here" : " &middot; select a point first")+"</i>");
}
function hoverFlyway(px, py){
  castFrom(px, py, cameras.fly.obj);
  var hit = ray.intersectObjects(Object.keys(tiles).map(function(id){ return tiles[id].mesh; }), false)[0];
  if (!hit){ hideViewTip(); return; }
  var id = hit.object.userData.flyway, f = flywayReadings()[id];
  showViewTip(px, py, "<b>Flyway "+id+"</b>"+(f ? " &nbsp;"+f.w.toFixed(1)+" W<br><i>CPU "+f.cpu.toFixed(1)+
    " · amp "+f.amp.toFixed(1)+" · motor "+f.motor.toFixed(1)+" °C</i>" : "<br><i>No telemetry yet</i>"));
}
