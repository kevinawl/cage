/* View options: what is shown and how it is coloured, saved per browser in localStorage. */
export const VIEW_DEFAULT = {kpis:true, fwPanel:true, mvPanel:true, rxPanel:true,
  tileHeat:true, tileLabels:true, moverPower:true, moverIds:true, axes:true,
  mPos:true, mLift:true, mErr:true, fwSpark:true, fwTemps:true,
  cPoints:true, cScale:true, cLabels:true, cDrops:true,
  accent:"blue", ramp:"blue", finish:"graphite", stage:"light"};
const VIEW_KEY = "cagePowerMap.view.v1";
export const VIEW = loadView();
function loadView(){
  var view = {};
  Object.keys(VIEW_DEFAULT).forEach(function(k){ view[k] = VIEW_DEFAULT[k]; });
  try {
    var saved = JSON.parse(localStorage.getItem(VIEW_KEY) || "{}");
    Object.keys(saved).forEach(function(k){ if (k in view && typeof saved[k] === typeof view[k]) view[k] = saved[k]; });
  } catch(e){}
  return view;
}
export function saveView(){ try { localStorage.setItem(VIEW_KEY, JSON.stringify(VIEW)); } catch(e){} }
