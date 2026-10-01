/* Fixed numbers: cage and flyway geometry, timing, pointer feel, colour ramps. Nothing here changes at run time. */
/* Cage, mm. Every bar is one 1.5 m span between two joints and the cage is two bars a side:
   a 3 m cube. Origin at the centre of its floor; X west → east, Y south → north, Z up. */
export const BAR_LEN = 1500, BAR_SECTION = 40;
export const CAGE = 2*BAR_LEN, HALF = CAGE/2;
export const GRID_MM = 250;                          // floor grid and ruler ticks
export const SNAP_MM = 10;                           // clicking or dragging along a bar
export const ON_BAR_MM = 1;                          // a point this close to a bar is on it
export const COORD_LIMIT_MM = 10000;                 // the bridge enforces the same bound
export const STAND_X = HALF+400, STAND_Y = -HALF-500;      // the stand sits off the south-east corner

/* Flyway, mm. */
export const FLY_TILE = 240;                         // S3 flyway, 240 x 240 mm (PMI datasheet)
export const MOVER_MM = {M306:[120,120,10]};         // xBot footprint by type; unknown types draw as M3-06
export const DEG = Math.PI/180;

/* Timing. */
export const UI_REFRESH_MS = 120;                    // panels refresh at a readable pace; the 3D runs every frame
export const MESSAGE_MS = 6000;                      // how long an error message stays up
export const SAVE_DELAY_MS = 250;                    // a point edit is saved once typing pauses...
export const EDIT_HOLD_MS = 1500;                    // ...and the local copy beats the bridge's until it lands
export const POSE_STALE_MS = 1500;
export const ERR_WINDOW_MS = 500, ERR_SAMPLES = 60;  // tracking error: 0.5 s means, 30 s of trend

/* Trends: receiver readings arrive at 5 Hz, flyway power at 2 Hz; both keep 60 s. */
export const RX_SAMPLES = 300, RX_PERIOD_S = .2;
export const FLYWAY_SAMPLES = 120, FLYWAY_PERIOD_S = .5;

/* Pointer. */
export const CLICK_SLOP_PX = 6;                      // moved less than this, it's a click, not an orbit
export const ORBIT_PER_PX = .006;                    // radians
export const POLAR_MIN = .15, POLAR_MAX = 1.52;
export const ZOOM_STEP = .09;
export const ZOOM_LIMITS = {cage:[2500,22000], fly:[250,4200]};

export const START_COMMAND = ".venv\\Scripts\\python.exe bridge\\pmc_bridge.py";

/* ---------- colours ---------- */
/* Sequential ramps, light -> dark for a light surface: pale = near zero. Blue is the dataviz
   reference ramp; the others keep its OKLCH lightness and chroma step for step at another
   hue (checked monotonic, single-hue), so every choice reads the same way. */
export const RAMPS = {
  blue:  ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7","#3987e5","#2a78d6","#256abf","#1c5cab","#184f95","#104281","#0d366b"],
  teal:  ["#c1e9e8","#a4dddc","#82d2d1","#5dc6c5","#1cbaba","#16aaab","#149a9a","#0f8a8a","#0a7b7b","#086b6b","#055d5d","#044e4e","#044040"],
  violet:["#e0dbf9","#d0caf4","#c2b9f1","#b3a7eb","#a595e7","#9884e2","#8b70de","#7d62cf","#6f56b9","#614aa5","#543f90","#47347c","#3a2a67"],
  amber: ["#f4dac5","#edc9aa","#e7b78d","#dfa471","#d89250","#d0802c","#c26f02","#ad6510","#9a590c","#874d09","#754206","#633705","#532d01"]};
export const ACCENTS = {blue:["#2f6fdb","#255fc2","#ebf1fc"], teal:["#0f8a8a","#0b7373","#e5f3f3"], violet:["#6a52d6","#5842bb","#efecfb"],
  amber:["#b8620a","#9b5208","#faf0e4"], graphite:["#3b4150","#2b303b","#eceef2"]};
export const FINISH = {graphite:0x2a2d34, silver:0x9aa0aa, white:0xe9ebef};
export const POINT_IDLE = 0xd0d3d9, POINT_WAITING = 0x8f95a1;     // no receiver here / receiver here, no reading
export const TILE_BASE = 0xd5d8de;
