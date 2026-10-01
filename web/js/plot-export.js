/* Plot data, saving the graph on screen as a PNG: the dialog's SVG charts and their legends, redrawn on a canvas. */
import {theme} from "./theme.js";

const SCALE = 2;                       // pixels per CSS pixel: sharp in slides and reports
const PAD = 24, TITLE_H = 34;
/* What an SVG needs inline to render the same outside the page's stylesheet. */
const SVG_STYLES = ["fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "opacity", "fill-opacity",
  "stroke-opacity", "font-family", "font-size", "font-weight", "paint-order", "visibility", "text-anchor"];
/* Short, single-line HTML labels drawn as text; swatches drawn as boxes. */
const LABELS = ".hm figcaption, .pl-keys span, .pl-legend > span";
const SWATCHES = ".pl-keys i, .pl-none i, .pl-legend .ramp";

export function hasImage(body){ return !!body.querySelector("svg.pl-chart"); }

/* Draws what `body` shows and downloads it as <name>.png. Resolves when the download has started. */
export function saveImage(body, title, name){
  var charts = [].slice.call(body.querySelectorAll("svg.pl-chart"));
  var labels = [].slice.call(body.querySelectorAll(LABELS)), swatches = [].slice.call(body.querySelectorAll(SWATCHES));
  var all = charts.concat(labels, swatches).map(function(el){ return el.getBoundingClientRect(); });
  var x0 = Math.min.apply(null, all.map(function(r){ return r.left; })), y0 = Math.min.apply(null, all.map(function(r){ return r.top; }));
  var x1 = Math.max.apply(null, all.map(function(r){ return r.right; })), y1 = Math.max.apply(null, all.map(function(r){ return r.bottom; }));
  var canvas = document.createElement("canvas"), g = canvas.getContext("2d");
  canvas.width = Math.ceil((x1-x0+2*PAD)*SCALE); canvas.height = Math.ceil((y1-y0+2*PAD+TITLE_H)*SCALE);
  g.scale(SCALE, SCALE);
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = "#15171c"; g.font = '600 15px "Geist", sans-serif'; g.textBaseline = "middle";
  g.fillText(title, PAD, PAD+TITLE_H/2-6);
  function at(r){ return {x:r.left-x0+PAD, y:r.top-y0+PAD+TITLE_H, w:r.width, h:r.height}; }
  swatches.forEach(function(el){ drawSwatch(g, el, at(el.getBoundingClientRect())); });
  labels.forEach(function(el){ drawLabel(g, el, at(el.getBoundingClientRect())); });
  return Promise.all(charts.map(function(svg){
    var box = at(svg.getBoundingClientRect());
    return loadImage(standalone(svg, box)).then(function(img){ g.drawImage(img, box.x, box.y, box.w, box.h); });
  })).then(function(){
    return new Promise(function(done){ canvas.toBlob(function(blob){ download(blob, name+".png"); done(); }, "image/png"); });
  });
}

/* A copy of the SVG with every computed style written inline. */
function standalone(svg, box){
  var copy = svg.cloneNode(true), from = svg.querySelectorAll("*"), to = copy.querySelectorAll("*");
  function inline(source, target){
    var cs = getComputedStyle(source);
    target.setAttribute("style", SVG_STYLES.map(function(p){ return p+":"+cs.getPropertyValue(p); }).join(";"));
  }
  inline(svg, copy);
  for (var i = 0; i < from.length; i++) inline(from[i], to[i]);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", box.w); copy.setAttribute("height", box.h);
  return new XMLSerializer().serializeToString(copy);
}
function loadImage(svgText){
  return new Promise(function(ok, fail){
    var img = new Image();
    img.onload = function(){ ok(img); }; img.onerror = fail;
    img.src = "data:image/svg+xml;charset=utf-8,"+encodeURIComponent(svgText);
  });
}
function drawSwatch(g, el, box){
  if (el.classList.contains("ramp")){
    var grad = g.createLinearGradient(box.x, 0, box.x+box.w, 0);
    theme.ramp.forEach(function(c, i){ grad.addColorStop(i/(theme.ramp.length-1), c); });
    g.fillStyle = grad;
  } else g.fillStyle = getComputedStyle(el).backgroundColor;
  g.beginPath();
  if (g.roundRect) g.roundRect(box.x, box.y, box.w, box.h, Math.min(3, box.h/2)); else g.rect(box.x, box.y, box.w, box.h);
  g.fill();
}
/* The element's own text (not its children's), at its left edge; children are drawn in their own right. */
function drawLabel(g, el, box){
  var cs = getComputedStyle(el);
  g.fillStyle = cs.color; g.textBaseline = "middle";
  el.childNodes.forEach(function(node){
    if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()){
      var range = document.createRange(); range.selectNodeContents(node);
      var r = range.getBoundingClientRect(), left = box.x + (r.left - el.getBoundingClientRect().left);
      g.font = cs.fontWeight+" "+cs.fontSize+" "+cs.fontFamily;
      g.fillText(node.textContent, left, box.y+box.h/2);
    } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "B"){
      var bs = getComputedStyle(node), br = node.getBoundingClientRect();
      g.fillStyle = bs.color; g.font = bs.fontWeight+" "+bs.fontSize+" "+bs.fontFamily;
      g.fillText(node.textContent, box.x + (br.left - el.getBoundingClientRect().left), box.y+box.h/2);
      g.fillStyle = cs.color;
    }
  });
}
function download(blob, filename){
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
}
