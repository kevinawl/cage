/* What a receiver reading is (power, voltage, current) and the words shown for each board, controller and xBot state. */
import {fmtA, fmtV, fmtW} from "./util.js";

/* What a receiver is shown by. endpointField is what the page posts to choose the board's
   endpoint for it; endpointName is where the bridge reports that choice. */
export const READINGS = [
  {key:"power",   label:"Power",   unit:"W", format:fmtW, endpointField:"endpoint",   endpointName:"power_ep"},
  {key:"voltage", label:"Voltage", unit:"V", format:fmtV, endpointField:"v_endpoint", endpointName:"volt_ep"},
  {key:"current", label:"Current", unit:"A", format:fmtA, endpointField:"i_endpoint", endpointName:"curr_ep"}];
export const RX_STATE = {idle:["s-off","Not connected"], connecting:["s-warn","Connecting"], handshake:["s-warn","Connecting"],
  streaming:["s-good","Streaming"], error:["s-crit","Can't connect"]};
export const PMC_STATE = {PMC_FULLCTRL:"Full control", PMC_INTELLIGENTCTRL:"Intelligent control", PMC_INACTIVE:"Inactive",
  PMC_ACTIVATING:"Activating", PMC_BOOTING:"Booting", PMC_DISCOVERY:"Discovery", PMC_SERVICE:"Service mode"};
export const XBOT_STATE = {XBOT_IDLE:["s-good","Idle"], XBOT_MOTION:["s-good","Moving"], XBOT_LANDED:["s-off","Landed"],
  XBOT_DISABLED:["s-off","Disabled"], XBOT_DISCOVERING:["s-warn","Discovering"]};
