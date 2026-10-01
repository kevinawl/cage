/* three.js basics shared by both rigs: renderer, one scene and orbit camera per rig, text sprites. */
import {state} from "./state.js";
import {$} from "./util.js";

export const canvas3d = $("gl");
export const renderer = new THREE.WebGLRenderer({canvas:canvas3d, antialias:true, alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
function makeScene(){
  var scene = new THREE.Scene();
  scene.background = null;                   // the stage's gradient shows through
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc4c4cc, .95));
  var key = new THREE.DirectionalLight(0xffffff, .55); key.position.set(1400,-1800,2400); scene.add(key);
  var fill = new THREE.DirectionalLight(0xffffff, .28); fill.position.set(-1200,1400,900); scene.add(fill);
  return scene;
}
export const scenes = {cage:makeScene(), fly:makeScene()};
/* Orbit cameras: azimuth and polar angle around a target, at a distance. */
export const cameras = {
  cage:{obj:new THREE.PerspectiveCamera(40,1,10,60000), az:-1.95, pol:1.02, rad:7600, target:[250,-450,1250]},
  fly: {obj:new THREE.PerspectiveCamera(42,1,10,30000), az:-0.68, pol:1.0,  rad:1750, target:[0,0,120]}
};
export function placeCamera(){
  var c = cameras[state.sys], t = c.target, sp = Math.sin(c.pol);
  c.obj.position.set(t[0]+c.rad*sp*Math.cos(c.az), t[1]+c.rad*sp*Math.sin(c.az), t[2]+c.rad*Math.cos(c.pol));
  c.obj.up.set(0,0,1); c.obj.lookAt(t[0], t[1], t[2]);
}
/* Text in 3D: painted on a canvas, shown on a sprite that always faces the camera. */
export function textSprite(text, height, color, halo){
  var c = document.createElement("canvas"), g = c.getContext("2d"), font = '600 56px "Geist Mono", monospace';
  g.font = font;
  var w = Math.max(256, Math.ceil(g.measureText(text).width + 48));
  c.width = w; c.height = 96;
  g.font = font; g.textAlign = "center"; g.textBaseline = "middle";
  if (halo){ g.lineWidth = 14; g.lineJoin = "round"; g.strokeStyle = "rgba(255,255,255,.92)"; g.strokeText(text, w/2, 50); }
  g.fillStyle = color; g.fillText(text, w/2, 50);
  var sprite = new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c), depthTest:false, transparent:true}));
  sprite.scale.set(height*w/96, height, 1); sprite.renderOrder = 2;
  return sprite;
}
