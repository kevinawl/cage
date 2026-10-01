/* Plot data in 3D: a coloured sphere at every measured spot, like the heat map. */
import {locationsOf, metricNow, plot, plotSamples, topOf} from "./plot-model.js";
import {scenes} from "./scene.js";
import {rampColor} from "./util.js";

const SPOT_GEO = new THREE.SphereGeometry(42, 14, 10), spotColor = new THREE.Color(), spotMatrix = new THREE.Matrix4();
/* One instanced mesh for every spot, regrown (twice the size) when it runs out of room. */
let spots = null;

export function hideSpots(){ if (spots) spots.visible = false; }
export function syncSpots(){
  if (!plot.spots){ hideSpots(); return; }
  var m = metricNow(), locs = locationsOf(plotSamples("cage"));
  if (!spots || spots.userData.cap < locs.length){
    if (spots){ scenes.cage.remove(spots); spots.material.dispose(); if (spots.dispose) spots.dispose(); }
    var cap = Math.max(256, locs.length*2);
    spots = new THREE.InstancedMesh(SPOT_GEO, new THREE.MeshStandardMaterial({roughness:.45, metalness:.1}), cap);
    spots.userData.cap = cap; spots.setColorAt(0, spotColor); scenes.cage.add(spots);
  }
  var top = topOf(locs.map(function(L){ return L.stats[m.key].mean; }));
  locs.forEach(function(L, j){
    spots.setMatrixAt(j, spotMatrix.makeTranslation(L.x, L.y, L.z));
    spots.setColorAt(j, spotColor.setHex(rampColor(L.stats[m.key].mean/top)));
  });
  spots.count = locs.length; spots.visible = locs.length > 0;
  spots.instanceMatrix.needsUpdate = true; spots.instanceColor.needsUpdate = true;
}
