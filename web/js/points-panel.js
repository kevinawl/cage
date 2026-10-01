/* The Points panel: the list of cage points, the selected point's editor, and add / move / delete. */
import {messageFor, postPoint, postReceiver} from "./bridge.js";
import {barUnder} from "./cage-geometry.js";
import {cagePowerTop, pointColor} from "./cage-view.js";
import {COORD_LIMIT_MM, HALF, SAVE_DELAY_MS} from "./config.js";
import {RX_STATE} from "./labels.js";
import {isStreaming, pointById, receiverAt, receiverByMac, receiverName, state} from "./state.js";
import {bindReadings, fillReadings, readingsHtml} from "./trends.js";
import {$, esc, fmtW, hexOf, voltsAmpsText, xyzText} from "./util.js";

/* Rebuilt only when the list or the selection changes; values are refreshed in place,
   so a field being typed in is never reset. */
let pointListKey = null;
export function renderPoints(){
  var list = $("ptlist"), cage = state.cage, up = state.bridge.up;
  $("btnAddPt").disabled = !up;
  var key = up+"|"+cage.selected+"|"+cage.points.map(function(p){ return p.id; }).join(",");
  if (key !== pointListKey){
    pointListKey = key;
    list.innerHTML = !up ? '<div class="empty"><b>Bridge offline</b>Points are kept by the bridge, in '+
        '<code>bridge/cage_points.json</code>. Start it and they appear here.</div>'
      : !cage.points.length ? '<div class="empty"><b>No points yet</b>Press Add and type the coordinates, '+
        'or click a bar in the view to put the new point on it.</div>'
      : cage.points.map(pointRowHtml).join("");
    list.querySelectorAll(".pt").forEach(bindPointRow);
  }
  var top = cagePowerTop();
  list.querySelectorAll(".pt").forEach(function(row){ fillPointRow(row, pointById(row.dataset.id), top); });
}
export function renderPointsMessage(){
  var text = messageFor("points"), el = $("ptErr");
  el.hidden = !text; el.textContent = text;
}
function pointRowHtml(point){
  var selected = point.id === state.cage.selected;
  return '<div class="pt" data-id="'+esc(point.id)+'" aria-selected="'+selected+'">'+
    '<button class="pt-hd" aria-expanded="'+selected+'"><span class="sw"></span><span class="pt-nm"></span>'+
    '<span class="pt-xyz"></span><span class="pw"></span><span class="pt-vi"></span></button>'+
    (selected ? pointEditorHtml() : '')+'</div>';
}
function bindPointRow(row){
  var id = row.dataset.id;
  row.querySelector(".pt-hd").onclick = function(){
    state.cage.selected = state.cage.selected === id ? null : id; renderPoints();
  };
  if (id === state.cage.selected) bindPointEditor(row, id);
}
function fillPointRow(row, point, top){
  if (!point) return;
  var rx = receiverAt(point.id), watts = rx ? rx.power : null;
  row.querySelector(".sw").style.background = hexOf(pointColor(rx, top));
  row.querySelector(".pt-nm").textContent = point.name;
  row.querySelector(".pt-xyz").textContent = xyzText(point);
  row.querySelector(".pw").innerHTML = watts == null ? "<em>"+(rx ? "no reading" : "no receiver")+"</em>" : fmtW(watts)+"<em> W</em>";
  row.querySelector(".pt-vi").textContent = voltsAmpsText(rx);
  var editor = row.querySelector(".pt-ed"); if (editor) fillPointEditor(editor, point, rx);
}

/* ---------- the selected point's editor ---------- */
function pointEditorHtml(){
  return '<div class="pt-ed">'+
    '<div class="field"><label>Name</label><input class="in" data-f="name" maxlength="64" aria-label="Point name"></div>'+
    '<div class="field"><label>Position <span>mm</span></label><div class="xyz">'+
      ["x","y","z"].map(function(k){ return '<label class="ax"><b>'+k.toUpperCase()+'</b><input type="number" step="1" data-f="'+k+
        '" aria-label="'+k.toUpperCase()+' in mm"></label>'; }).join("")+'</div>'+
      '<div class="pt-dir">From the floor centre: X west → east, Y south → north, Z up</div>'+
      '<div class="pt-bar"></div></div>'+
    '<div class="field"><label>Receiver <span class="pt-rxst"></span></label>'+
      '<select class="pt-rx" aria-label="Receiver at this point"></select></div>'+
    '<div class="mrx pt-live" hidden><div class="k">Received at this point</div>'+readingsHtml()+'</div>'+
    '<div class="pt-act"><button class="btn sm pt-del">Delete point</button></div></div>';
}
function bindPointEditor(row, id){
  row.querySelectorAll("[data-f]").forEach(function(input){
    input.oninput = function(){ editPointField(id, input); };
    input.onkeydown = function(e){ if (e.key === "Enter") input.blur(); };
  });
  row.querySelector(".pt-rx").onchange = function(){ placeReceiverAt(id, this.value); };
  row.querySelector(".pt-del").onclick = function(){ deletePoint(id); };
  bindReadings(row);
}
function editPointField(id, input){
  var point = pointById(id); if (!point) return;
  var field = input.dataset.f;
  if (field === "name") point.name = input.value.trim() || point.id;
  else {
    var v = parseFloat(input.value), valid = isFinite(v) && Math.abs(v) <= COORD_LIMIT_MM;
    if (!valid){ input.setAttribute("aria-invalid", "true"); return; }
    input.removeAttribute("aria-invalid");
    point[field] = v;
  }
  savePoint(point);
}
function fillPointEditor(editor, point, rx){
  editor.querySelectorAll("[data-f]").forEach(function(input){
    if (input === document.activeElement) return;                  // never under the cursor
    var v = input.dataset.f === "name" ? point.name : String(Math.round(point[input.dataset.f]*10)/10);
    if (input.value !== v){ input.value = v; input.removeAttribute("aria-invalid"); }
  });
  var on = barUnder(point);
  editor.querySelector(".pt-bar").innerHTML = on ? "On <b>"+on.bar.id+"</b>, "+Math.round(on.s)+" mm from the "+on.bar.from
    : "Not on a bar. Click a bar in the view to put it on one.";
  fillReceiverChoice(editor.querySelector(".pt-rx"), point, rx);
  var st = rx ? (RX_STATE[rx.state] || ["", rx.state]) : null;
  editor.querySelector(".pt-rxst").textContent = st ? st[1] : "";
  var live = editor.querySelector(".pt-live");
  live.hidden = !rx || !isStreaming(rx);
  if (!live.hidden) fillReadings(live, rx);
}
/* Options rebuilt only when they change, so an open dropdown isn't reset. */
function fillReceiverChoice(select, point, rx){
  var boards = state.bridge.receivers;
  var key = boards.map(function(b){ return b.mac+":"+b.point+":"+b.xbot+":"+receiverName(b); }).join(",")+"|"+
    state.cage.points.map(function(p){ return p.id+":"+p.name; }).join(",");
  if (select._key === key || select === document.activeElement) return;
  select._key = key;
  select.innerHTML = '<option value="">'+(boards.length ? "None" : "No receiver reachable")+'</option>'+boards.map(function(b){
    var elsewhere = b.point && b.point !== point.id && pointById(b.point);
    var where = elsewhere ? " (at "+elsewhere.name+")" : b.xbot != null ? " (on xBot "+b.xbot+")" : "";
    return '<option value="'+esc(b.mac)+'">'+esc(receiverName(b)+where)+'</option>'; }).join("");
  select.value = rx ? rx.mac : "";
}

/* ---------- point actions ---------- */
const saveTimers = {};
function savePoint(point){
  state.cage.editedAt[point.id] = performance.now();
  clearTimeout(saveTimers[point.id]);
  saveTimers[point.id] = setTimeout(function(){
    postPoint("/"+encodeURIComponent(point.id), {name:point.name, x:point.x, y:point.y, z:point.z}).catch(function(){});
  }, SAVE_DELAY_MS);
}
export function movePoint(point, pos){
  point.x = Math.round(pos.x); point.y = Math.round(pos.y); point.z = Math.round(pos.z);
  savePoint(point); renderPoints();
}
/* One receiver per point: whichever was here is unplaced first. */
function placeReceiverAt(pointId, mac){
  var previous = receiverAt(pointId), rx = receiverByMac(mac);
  if (previous && previous.mac !== mac){ previous.point = null; postReceiver(previous.mac, null, {point:null}); }
  if (rx){ rx.point = pointId; rx.xbot = null; postReceiver(mac, null, {point:pointId}); }
}
function deletePoint(id){
  var point = pointById(id); if (!point || !confirm("Delete point "+point.name+"?")) return;
  postPoint("/"+encodeURIComponent(id)+"/delete").then(function(){
    state.cage.points = state.cage.points.filter(function(p){ return p.id !== id; });
    if (state.cage.selected === id) state.cage.selected = null;
    renderPoints();
  }).catch(function(){});
}
/* A new point starts at the centre of the cage, ready for its measured X to be typed. */
function addPoint(){
  var at = {x:0, y:0, z:HALF};
  postPoint("", {name:"", x:at.x, y:at.y, z:at.z}).then(function(reply){
    if (!pointById(reply.id)) state.cage.points.push({id:reply.id, name:reply.id, x:at.x, y:at.y, z:at.z});
    state.cage.selected = reply.id; renderPoints();
    var x = document.querySelector('.pt-ed [data-f="x"]'); if (x){ x.focus(); x.select(); }
  }).catch(function(){});
}
$("btnAddPt").onclick = addPoint;
