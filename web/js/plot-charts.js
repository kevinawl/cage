/* Plot data, the charts: heat map, locations table, over time and vs position, each rendered as an SVG/HTML string. */
import {CAGE, HALF} from "./config.js";
import {METRICS, clockText, durationText, locationsOf, niceScale, plot, receiversRecorded, tickText, tipFor, topOf, valueOf} from "./plot-model.js";
import {rec} from "./recorder.js";
import {pointById, state} from "./state.js";
import {theme} from "./theme.js";
import {trendTip} from "./trends.js";
import {clamp, esc, hexOf, hexToRgba, mmText, rampColor, xyzText} from "./util.js";

function rigExtent(samples, rig, bin){
  var layout = state.fly.layout, ext;
  if (rig === "cage") ext = {x:[-HALF, HALF], y:[-HALF, HALF], z:[0, CAGE]};
  else if (layout) ext = {x:[0, layout.cols*layout.tile], y:[0, layout.rows*layout.tile], z:[0, 0]};
  else ext = {x:[Infinity, -Infinity], y:[Infinity, -Infinity], z:[0, 0]};
  samples.forEach(function(s){ ["x","y","z"].forEach(function(a){
    var c = Math.round(s[a]/bin)*bin;
    ext[a][0] = Math.min(ext[a][0], c-bin/2); ext[a][1] = Math.max(ext[a][1], c+bin/2); }); });
  return ext;
}
export function renderHeat(samples, m, rig){
  var bin = plot.bin[rig], ext = rigExtent(samples, rig, bin);
  var views = rig === "cage" ? [["Top","looking down","x","y"],["Front","from the south","x","z"],["Side","from the east","y","z"]]
                             : [["Top","looking down on the stator","x","y"]];
  var span = 0;
  views.forEach(function(v){ span = Math.max(span, ext[v[2]][1]-ext[v[2]][0], ext[v[3]][1]-ext[v[3]][0]); });
  var k = (views.length === 1 ? 600 : 300)/span, panels = views.map(function(v){ return heatCells(v, samples, m, bin); });
  var top = topOf([].concat.apply([], panels.map(function(p){ return p.list.map(function(c){ return c.sum/c.n; }); })));
  return '<div class="hm-grid'+(views.length === 1 ? ' one' : '')+'">'+views.map(function(v, j){
    return heatPanel(v, panels[j], ext, k, bin, m, top, rig); }).join("")+'</div>'+
    '<div class="pl-legend"><span class="lk">'+m.label+', mean</span><span>0</span><div class="ramp" style="background:linear-gradient(90deg,'+
    theme.ramp.join(",")+')"></div><span>'+top+' '+m.unit+'</span><span class="pl-none"><i></i>Not measured</span></div>'+
    '<p class="pl-note">Each cell averages every reading taken inside it, through the full depth of the '+(rig === "cage" ? "cage" : "stator")+
    ' along the hidden axis. Hover a cell for its spread.'+(rig === "cage" ? ' Rings are the cage points as they stand now.' : '')+'</p>';
}
function heatCells(v, samples, m, bin){
  var a = v[2], b = v[3], hidden = "xyz".replace(a, "").replace(b, ""), cells = {}, list = [];
  samples.forEach(function(s){
    var ca = Math.round(s[a]/bin), cb = Math.round(s[b]/bin), key = ca+","+cb, c = cells[key], val = valueOf(s, m.key);
    if (!c){ c = cells[key] = {ca:ca, cb:cb, n:0, sum:0, min:Infinity, max:-Infinity, hlo:Infinity, hhi:-Infinity}; list.push(c); }
    c.n++; c.sum += val; c.min = Math.min(c.min, val); c.max = Math.max(c.max, val);
    c.hlo = Math.min(c.hlo, s[hidden]); c.hhi = Math.max(c.hhi, s[hidden]);
  });
  return {list:list, hidden:hidden};
}
function heatPanel(v, cells, ext, k, bin, m, top, rig){
  var a = v[2], b = v[3], A = ext[a], B = ext[b], PL = 46, PR = 12, PT = 10, PB = 34;
  var w = (A[1]-A[0])*k, h = (B[1]-B[0])*k, W = PL+w+PR, H = PT+h+PB;
  function sx(u){ return PL+(u-A[0])*k; } function sy(u){ return PT+(B[1]-u)*k; }
  var out = '<rect class="hm-bg" x="'+PL+'" y="'+PT+'" width="'+w+'" height="'+h+'" rx="3"/>';
  var gridStep = rig === "cage" ? 500 : (state.fly.layout ? state.fly.layout.tile : 120), g = "";
  for (var u = Math.ceil(A[0]/gridStep)*gridStep; u <= A[1]; u += gridStep) g += 'M'+sx(u)+' '+PT+'V'+(PT+h);
  for (u = Math.ceil(B[0]/gridStep)*gridStep; u <= B[1]; u += gridStep) g += 'M'+PL+' '+sy(u)+'H'+(PL+w);
  out += '<path class="hm-grid-l" d="'+g+'"/>';
  var gap = Math.min(1, bin*k/8), size = Math.max(1, bin*k-2*gap), H_ = cells.hidden.toUpperCase();
  cells.list.forEach(function(c){
    var mean = c.sum/c.n, a0 = c.ca*bin-bin/2, b1 = c.cb*bin+bin/2;
    out += '<rect class="hm-cell" x="'+(sx(a0)+gap).toFixed(2)+'" y="'+(sy(b1)+gap).toFixed(2)+'" width="'+size.toFixed(2)+'" height="'+size.toFixed(2)+
      '" rx="'+Math.min(2, size/4).toFixed(2)+'" fill="'+hexOf(rampColor(mean/top))+'"'+tipFor(
      '<b>'+m.fmt(mean)+' '+m.unit+'</b> &nbsp;<i>mean of '+c.n+'</i><br><i>'+m.fmt(c.min)+' – '+m.fmt(c.max)+' '+m.unit+'</i><br><i>'+
      a.toUpperCase()+' '+mmText(c.ca*bin)+', '+b.toUpperCase()+' '+mmText(c.cb*bin)+' mm ± '+bin/2+
      ' · '+H_+' '+(Math.round(c.hlo) === Math.round(c.hhi) ? mmText(c.hlo) : mmText(c.hlo)+' to '+mmText(c.hhi))+'</i>')+'/>';
  });
  if (rig === "cage"){
    out += '<rect class="hm-cage" x="'+sx(-HALF)+'" y="'+sy(b === "z" ? CAGE : HALF)+'" width="'+CAGE*k+'" height="'+CAGE*k+'"/>';
    state.cage.points.forEach(function(p){
      out += '<circle class="hm-pt" cx="'+sx(p[a]).toFixed(1)+'" cy="'+sy(p[b]).toFixed(1)+'" r="3.5"/>'+
        '<text class="hm-ptl" x="'+(sx(p[a])+6).toFixed(1)+'" y="'+(sy(p[b])-5).toFixed(1)+'">'+esc(p.name)+'</text>';
    });
  }
  var ta = niceScale(A[0], A[1], 4), tb = niceScale(B[0], B[1], 4);
  ta.ticks.forEach(function(t){ if (t >= A[0] && t <= A[1]) out += '<text class="ax" x="'+sx(t)+'" y="'+(PT+h+14)+'" text-anchor="middle">'+tickText(t, ta.step)+'</text>'; });
  tb.ticks.forEach(function(t){ if (t >= B[0] && t <= B[1]) out += '<text class="ax" x="'+(PL-6)+'" y="'+(sy(t)+3.5)+'" text-anchor="end">'+tickText(t, tb.step)+'</text>'; });
  out += '<text class="ax-t" x="'+(PL+w/2)+'" y="'+(H-4)+'" text-anchor="middle">'+a.toUpperCase()+' mm</text>'+
    '<text class="ax-t" transform="translate(11 '+(PT+h/2)+') rotate(-90)" text-anchor="middle">'+b.toUpperCase()+' mm</text>';
  return '<figure class="hm"><figcaption><b>'+v[0]+'</b> '+v[1]+'</figcaption><svg class="pl-chart" viewBox="0 0 '+W.toFixed(1)+' '+H.toFixed(1)+
    '" role="img" aria-label="'+v[0]+' view heat map of '+m.label.toLowerCase()+'">'+out+'</svg></figure>';
}

/* ---------- locations: one row per spot a receiver sat at ---------- */
export function renderTable(samples, m, rig){
  var locs = locationsOf(samples), many = receiversRecorded(rig).length > 1 && plot.rx === "all";
  var top = topOf(locs.map(function(L){ return L.stats[m.key].mean; }));
  var shown = METRICS.filter(function(q){ return !q.fly || rig === "fly"; });
  var cols = [["place","Place"]].concat(many ? [["rx","Receiver"]] : [], [["x","X"],["y","Y"],["z","Z"]],
    shown.map(function(q){ return [q.key, q.label+" "+q.unit]; }), [["n","Readings"],["dur","Time there"]]);
  function key(L){
    var s = plot.sort;
    if (s === "place") return L.place; if (s === "rx") return rec.nameOf[L.mac] || L.mac;
    if (s === "n") return L.n; if (s === "dur") return L.t1-L.t0;
    if (s === "x" || s === "y" || s === "z") return L[s];
    return L.stats[s] ? L.stats[s].mean : -Infinity;
  }
  locs.sort(function(p, q){
    var a = key(p), b = key(q), c = typeof a === "string" ? a.localeCompare(b, undefined, {numeric:true}) : a-b;
    return plot.desc ? -c : c;
  });
  var MAX_ROWS = 400, more = locs.length-MAX_ROWS;
  var head = cols.map(function(c){
    var on = plot.sort === c[0], num = c[0] !== "place" && c[0] !== "rx";
    return '<th'+(num ? ' class="num"' : '')+(c[0] === m.key ? ' data-on' : '')+' aria-sort="'+(on ? (plot.desc ? "descending" : "ascending") : "none")+
      '"><button data-sort="'+c[0]+'">'+c[1]+(on ? (plot.desc ? " ↓" : " ↑") : "")+'</button></th>'; }).join("");
  var rows = locs.slice(0, MAX_ROWS).map(function(L){
    var tds = '<td>'+esc(L.place)+'</td>'+(many ? '<td><span class="sw" style="background:'+rec.colorOf[L.mac]+'"></span>'+esc(rec.nameOf[L.mac] || L.mac)+'</td>' : '')+
      '<td class="num">'+mmText(L.x)+'</td><td class="num">'+mmText(L.y)+'</td><td class="num">'+mmText(L.z)+'</td>';
    shown.forEach(function(q){
      var st = L.stats[q.key];
      if (!st){ tds += '<td class="num dim">—</td>'; return; }
      if (q.key !== m.key){ tds += '<td class="num">'+q.fmt(st.mean)+'</td>'; return; }
      tds += '<td class="num lead"><div class="lead-v"><span>'+q.fmt(st.mean)+'</span><i>'+q.fmt(st.min)+' – '+q.fmt(st.max)+'</i></div>'+
        '<div class="lead-bar"><span style="width:'+clamp(st.mean/top*100, 0, 100).toFixed(1)+'%;background:'+hexOf(rampColor(st.mean/top))+'"></span></div></td>';
    });
    return '<tr>'+tds+'<td class="num">'+L.n+'</td><td class="num">'+durationText(L.t1-L.t0)+'</td></tr>';
  }).join("");
  return '<div class="pl-table"><table><thead><tr>'+head+'</tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<p class="pl-note">'+locs.length+' spot'+(locs.length === 1 ? "" : "s")+', grouped to 10 mm. Means over every reading at the spot; '+
    m.label.toLowerCase()+' also shows its range.'+(more > 0 ? ' Showing '+MAX_ROWS+'; export CSV for all of them.' : '')+'</p>';
}

/* ---------- over time: one line per receiver, 400 time buckets ---------- */
function timeTicks(t0, t1){
  var span = (t1-t0)/1000, steps = [1,2,5,10,15,30,60,120,300,600,900,1800,3600,7200,10800,21600], step = steps[steps.length-1];
  for (var j = 0; j < steps.length; j++) if (span/steps[j] <= 7){ step = steps[j]; break; }
  var out = [], ms = step*1000, offset = new Date(t0).getTimezoneOffset()*60000;
  for (var t = Math.ceil((t0-offset)/ms)*ms+offset; t <= t1; t += ms) out.push(t);
  return {ticks:out, seconds:step < 60};
}
export function renderTime(samples, m){
  var W = 1000, H = 360, L = 58, R = 130, T = 14, B = 32, NB = 400;
  var sent = m.key === "sent", t1 = Date.now(), t0 = plot.range === "all" ? samples[0].t : t1-(+plot.range)*1000;
  if (t1-t0 < 10000) t0 = t1-10000;                           // a few seconds don't stretch across the whole width
  var bw = (t1-t0)/NB, snap = Math.max(3*bw, 3000), groups = {}, order = [];
  samples.forEach(function(s){
    var id = sent ? "stator" : s.mac, g = groups[id];
    if (!g){ g = groups[id] = {name:sent ? "All flyways" : rec.nameOf[s.mac] || s.mac, color:sent ? theme.accent : rec.colorOf[s.mac], b:{}}; order.push(g); }
    var j = clamp(Math.floor((s.t-t0)/bw), 0, NB-1), c = g.b[j] || (g.b[j] = {n:0, sum:0, place:null});
    c.n++; c.sum += valueOf(s, m.key); c.place = s.place;
  });
  var lo = 0, hi = 0;
  order.forEach(function(g){
    g.pts = Object.keys(g.b).map(Number).sort(function(p, q){ return p-q; }).map(function(j){
      var c = g.b[j], v = c.sum/c.n; lo = Math.min(lo, v); hi = Math.max(hi, v);
      return {t:t0+(j+.5)*bw, v:v, place:c.place}; });
  });
  var ys = niceScale(lo, hi*1.05, 5);
  function X(t){ return L+(t-t0)/(t1-t0)*(W-L-R); } function Y(v){ return T+(ys.hi-v)/(ys.hi-ys.lo)*(H-T-B); }
  var out = "";
  ys.ticks.forEach(function(v){
    out += '<path class="'+(v === 0 ? "pl-base" : "pl-gl")+'" d="M'+L+' '+Y(v).toFixed(1)+'H'+(W-R)+'"/>'+
      '<text class="ax" x="'+(L-8)+'" y="'+(Y(v)+3.5).toFixed(1)+'" text-anchor="end">'+tickText(v, ys.step)+'</text>';
  });
  var tt = timeTicks(t0, t1);
  tt.ticks.forEach(function(t){ out += '<text class="ax" x="'+X(t).toFixed(1)+'" y="'+(H-B+16)+'" text-anchor="middle">'+clockText(t, tt.seconds)+'</text>'; });
  out += '<text class="ax-t" transform="translate(14 '+(T+(H-T-B)/2)+') rotate(-90)" text-anchor="middle">'+m.label+' '+m.unit+'</text>';
  var ends = [];
  order.forEach(function(g){
    var d = "", area = "", seg = [];
    function flush(){
      if (seg.length && order.length === 1){
        area += "M"+X(seg[0].t).toFixed(1)+" "+Y(Math.max(ys.lo, 0)).toFixed(1)+seg.map(function(p){ return "L"+X(p.t).toFixed(1)+" "+Y(p.v).toFixed(1); }).join("")+
          "L"+X(seg[seg.length-1].t).toFixed(1)+" "+Y(Math.max(ys.lo, 0)).toFixed(1)+"Z";
      }
      seg = [];
    }
    g.pts.forEach(function(p, j){
      var gap = j && p.t-g.pts[j-1].t > snap;
      if (gap) flush();
      d += (j && !gap ? "L" : "M")+X(p.t).toFixed(1)+" "+Y(p.v).toFixed(1); seg.push(p);
    });
    flush();
    if (area) out += '<path d="'+area+'" fill="'+hexToRgba(g.color, .10)+'"/>';
    out += '<path class="pl-line" d="'+d+'" stroke="'+g.color+'"/>';
    var last = g.pts[g.pts.length-1];
    if (g.pts.length === 1) out += '<circle class="pl-dot" cx="'+X(last.t).toFixed(1)+'" cy="'+Y(last.v).toFixed(1)+'" r="4" fill="'+g.color+'"/>';
    ends.push({y:Y(last.v), x:X(last.t), g:g, v:last.v});
  });
  if (order.length <= 4){                                     // direct labels, nudged apart
    ends.sort(function(p, q){ return p.y-q.y; });
    for (var j = 1; j < ends.length; j++) if (ends[j].y-ends[j-1].y < 15) ends[j].y = ends[j-1].y+15;
    ends.forEach(function(e){
      out += '<text class="pl-end" x="'+(W-R+10)+'" y="'+(e.y+4).toFixed(1)+'">'+esc(e.g.name)+' <tspan>'+m.fmt(e.v)+' '+m.unit+'</tspan></text>';
    });
  }
  out += '<g class="xh" visibility="hidden"><path class="xh-l" d=""/><g class="xh-d"></g></g>'+
    '<rect class="pl-hit" x="'+L+'" y="'+T+'" width="'+(W-L-R)+'" height="'+(H-T-B)+'"/>';
  plot.time = {t0:t0, t1:t1, W:W, H:H, L:L, R:R, T:T, B:B, X:X, Y:Y, groups:order, snap:snap, m:m};
  var legend = order.length > 1 ? '<div class="pl-keys">'+order.map(function(g){
    return '<span><i style="background:'+g.color+'"></i>'+esc(g.name)+'</span>'; }).join("")+'</div>' : '';
  return legend+'<svg class="pl-chart pl-time" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+m.label+' over time">'+out+'</svg>'+
    '<p class="pl-note">'+(order.length === 1 && !sent ? esc(order[0].name)+'. ' : '')+'Each step is the mean over '+durationText(bw)+
    '; the line breaks where nothing was recorded. Hover for the place each reading came from.</p>';
}
function nearestPoint(pts, t){
  var lo = 0, hi = pts.length-1;
  if (hi < 0) return null;
  while (hi-lo > 1){ var mid = (lo+hi) >> 1; if (pts[mid].t < t) lo = mid; else hi = mid; }
  return Math.abs(pts[lo].t-t) <= Math.abs(pts[hi].t-t) ? pts[lo] : pts[hi];
}
export function hoverTime(svg, e){
  var d = plot.time, xh = svg.querySelector(".xh"); if (!d || !xh) return;
  var r = svg.getBoundingClientRect(), x = (e.clientX-r.left)*d.W/r.width;
  if (x < d.L || x > d.W-d.R){ xh.setAttribute("visibility", "hidden"); trendTip.classList.remove("on"); return; }
  var t = d.t0+(x-d.L)/(d.W-d.L-d.R)*(d.t1-d.t0), dots = "", rows = [], at = null;
  d.groups.forEach(function(g){
    var p = nearestPoint(g.pts, t); if (!p || Math.abs(p.t-t) > d.snap) return;
    if (at == null) at = p.t;
    dots += '<circle class="pl-dot" cx="'+d.X(p.t).toFixed(1)+'" cy="'+d.Y(p.v).toFixed(1)+'" r="4.5" fill="'+g.color+'"/>';
    rows.push({v:p.v, html:(d.groups.length > 1 ? '<span class="ftsw" style="background:'+g.color+'"></span>'+esc(g.name)+' ' : '')+
      '<b>'+d.m.fmt(p.v)+' '+d.m.unit+'</b> <i>'+esc(p.place)+'</i>'});
  });
  if (at == null){ xh.setAttribute("visibility", "hidden"); trendTip.classList.remove("on"); return; }
  rows.sort(function(p, q){ return q.v-p.v; });
  var lx = d.X(at);
  xh.querySelector(".xh-l").setAttribute("d", "M"+lx.toFixed(1)+" "+d.T+"V"+(d.H-d.B));
  xh.querySelector(".xh-d").innerHTML = dots; xh.setAttribute("visibility", "visible");
  trendTip.innerHTML = '<i>'+clockText(at, true)+'</i><br>'+rows.map(function(row){ return row.html; }).join("<br>");
  trendTip.style.left = (r.left+lx*r.width/d.W)+"px"; trendTip.style.top = (r.top+d.T*r.height/d.H)+"px"; trendTip.classList.add("on");
}

/* ---------- vs position: each spot's mean against distance or a coordinate, whiskers min to max ---------- */
function refPoint(rig){
  var p = rig === "cage" && plot.ref !== "centre" ? pointById(plot.ref) : null;
  return p ? {x:p.x, y:p.y, z:p.z, name:p.name} : rig === "cage" ? {x:0, y:0, z:HALF, name:"the cage centre"} : {x:0, y:0, z:0, name:"the stator origin"};
}
export function renderScatter(samples, m, rig){
  var W = 1000, H = 380, L = 64, R = 24, T = 14, B = 40;
  var locs = locationsOf(samples), ref = refPoint(rig), axis = plot.axis;
  function xOf(Lc){ return axis === "dist" ? Math.hypot(Lc.x-ref.x, Lc.y-ref.y, Lc.z-ref.z) : Lc[axis]; }
  var xs = locs.map(xOf), xlo = Math.min.apply(null, xs), xhi = Math.max.apply(null, xs);
  if (axis === "dist") xlo = 0;
  var pad = Math.max(10, (xhi-xlo)*.04), sxs = niceScale(xlo-(axis === "dist" ? 0 : pad), xhi+pad, 6);
  var vlo = 0, vhi = 0;
  locs.forEach(function(Lc){ var st = Lc.stats[m.key]; vlo = Math.min(vlo, st.min); vhi = Math.max(vhi, st.max); });
  var sys = niceScale(vlo, vhi*1.05, 5);
  function X(u){ return L+(u-sxs.lo)/(sxs.hi-sxs.lo)*(W-L-R); } function Y(v){ return T+(sys.hi-v)/(sys.hi-sys.lo)*(H-T-B); }
  var out = "";
  sys.ticks.forEach(function(v){
    out += '<path class="'+(v === 0 ? "pl-base" : "pl-gl")+'" d="M'+L+' '+Y(v).toFixed(1)+'H'+(W-R)+'"/>'+
      '<text class="ax" x="'+(L-8)+'" y="'+(Y(v)+3.5).toFixed(1)+'" text-anchor="end">'+tickText(v, sys.step)+'</text>';
  });
  sxs.ticks.forEach(function(u){ out += '<text class="ax" x="'+X(u).toFixed(1)+'" y="'+(H-B+16)+'" text-anchor="middle">'+tickText(u, sxs.step)+'</text>'; });
  out += '<text class="ax-t" x="'+(L+(W-L-R)/2)+'" y="'+(H-6)+'" text-anchor="middle">'+
    (axis === "dist" ? "Distance from "+esc(ref.name)+", mm" : axis.toUpperCase()+" mm")+'</text>'+
    '<text class="ax-t" transform="translate(14 '+(T+(H-T-B)/2)+') rotate(-90)" text-anchor="middle">'+m.label+' '+m.unit+', mean</text>';
  var marks = "";
  locs.forEach(function(Lc, j){
    var st = Lc.stats[m.key], cx = X(xs[j]).toFixed(1), color = rec.colorOf[Lc.mac];
    if (st.max > st.min) marks += '<path class="pl-whisk" d="M'+cx+' '+Y(st.min).toFixed(1)+'V'+Y(st.max).toFixed(1)+'" stroke="'+color+'"/>';
    marks += '<circle class="pl-dot" cx="'+cx+'" cy="'+Y(st.mean).toFixed(1)+'" r="5" fill="'+color+'"/>'+
      '<circle class="pl-hitdot" cx="'+cx+'" cy="'+Y(st.mean).toFixed(1)+'" r="11"'+tipFor(
        '<b>'+esc(Lc.place)+'</b> &nbsp;'+m.fmt(st.mean)+' '+m.unit+' <i>mean of '+st.n+'</i><br><i>'+m.fmt(st.min)+' – '+m.fmt(st.max)+' '+m.unit+
        ' · '+xyzText(Lc)+(axis === "dist" ? ' · '+mmText(xs[j])+' mm away' : '')+'<br>'+esc(rec.nameOf[Lc.mac] || Lc.mac)+'</i>')+'/>';
  });
  var macs = []; locs.forEach(function(Lc){ if (macs.indexOf(Lc.mac) < 0) macs.push(Lc.mac); });
  var legend = macs.length > 1 ? '<div class="pl-keys">'+macs.map(function(mac){
    return '<span><i class="dot" style="background:'+rec.colorOf[mac]+'"></i>'+esc(rec.nameOf[mac] || mac)+'</span>'; }).join("")+'</div>' : '';
  return legend+'<svg class="pl-chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+m.label+' against '+(axis === "dist" ? "distance" : axis)+'">'+out+marks+'</svg>'+
    '<p class="pl-note">One dot per spot a receiver sat at (10 mm), at its mean; the whisker spans the lowest to highest reading there.'+
    (axis === "dist" && rig === "cage" ? ' Add the transmitter as a point and measure from it to see how power falls off with distance.' : '')+'</p>';
}
