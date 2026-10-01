# Cage Power Map

Proof of concept for the *Graph Automation Feature* — delivered power shown against
position, on two separate test rigs.

Spec: [Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/~712020668dad7d79b94b1991606ab1a9931a0c/pages/1625128980/Graph+Automation+Feature)
(Confluence, page id `1625128980`).

## Running it

Open `index.html` in a browser. No build, no server, no install. Everything is in
that one file; the only external dependency is three.js from cdnjs, so the machine
needs a network connection the first time. Both views read live data from the
bridge (below); without it they draw the rig and say the bridge is offline.

A published copy lives at <https://claude.ai/artifact/NDhhLFdDeR58VcntYFEFBf>
(private — share it from the page's Share menu before sending the link on).

## The two rigs

They are separate setups and the tool keeps them separate: own geometry, own view,
own readings. Switch between them in the header. The Saguaro receivers are shared:
a board rides on an xBot or sits at a cage point, one or the other.

### Cage

A 3 m cube with a 2×2 lattice on every face: 48 bars, each exactly 1.5 m (one span
between two joints). Nothing crosses the working volume. See [docs/CAGE-GEOMETRY.md](docs/CAGE-GEOMETRY.md).
A stand off the south-east corner carries the PSU and the TX electronics.

Live only, like the flyway: nothing is simulated. The view is drawn to scale (one
scene unit is one millimetre) on a 250 mm floor grid, with rulers along X (south side),
Y (west side) and Z (north-west post), each 3 m with ticks every 250 mm, the joints
marked and every 1.5 m bar span labelled, and the X/Y/Z axes at the origin.

- **Points** are the positions receivers are measured at. Origin at the centre of the
  cage floor; X west → east, Y south → north, Z up, in mm. **Add** makes one at the
  cage centre (0, 0, 1500) with the cursor in X, ready to type. X and Y run
  −1500 to 1500 and Z 0 to 3000. Select a point to edit its name
  and X/Y/Z, or click any bar in the view to put it there (snapped to 10 mm), or drag
  it along the bars. When a point is on a bar the editor says which one and how far
  from its zero end, so it can be checked with a tape. Points are kept by the bridge
  in `bridge/cage_points.json`.
- **Receivers** are assigned to a point from the point's editor or from the board's
  *At point* select. The point turns the power-scale colour of its power reading. Its
  3D label shows W, V and A, its row and editor show power, voltage and current with a
  60 s trend each, and the readings strip totals the power and names the strongest point.

### Flyway

PMI planar motor, and live only: no receivers, no model, no simulated mover. The
view draws the stator the PMC is configured with and every xBot it reports, with a
pose readout (X, Y, Z, Rx, Ry, Rz, state) per mover. Without the bridge it says so
and waits.

## Live flyway (Python bridge)

A browser cannot load `PMCLIB.dll`, so `bridge/pmc_bridge.py` sits in between: it
polls `get_all_xbot_info()` at 20 Hz and streams every mover's pose to the page as
Server-Sent Events.

```powershell
.\.venv\Scripts\python.exe bridge\pmc_bridge.py                 # PMC at 192.168.17.150
.\.venv\Scripts\python.exe bridge\pmc_bridge.py --ip auto       # search the network
.\.venv\Scripts\python.exe bridge\pmc_bridge.py --mock          # fake movers, no hardware
```

Then open **<http://localhost:8765>**. The bridge serves `index.html` itself and opens
it on the Flyway view, so no Live Server or other web server is needed. The header
badge says whether the bridge and PMC are up; hover it for the reason.

- **Read-only.** The bridge connects and polls; it does not gain mastership, activate
  or move anything. If the PMC refuses reads from a non-master, add `--gain-mastership`.
- **Layout from the PMC.** On connect the bridge calls `save_pmc_config_xml_file` and
  reads the flyway grid from it (`flw/layout`: columns, rows, flyway id per cell). The
  bench is 4 × 1. The XML carries no size, so tiles are taken as the S3 flyway's
  240 × 240 mm and movers by type (M3-06 is 120 × 120 × 10 mm).
- **Telemetry, 2 Hz.** Per flyway: power draw, CPU, amplifier and motor temperature
  (`get_flyway_physical_status`), shown as tile colour on one shared scale, the tile's
  reading, and a 60 s sparkline per flyway. Per xBot: force (`get_xbot_status` with
  `FORCE`); Fz is shown as lift and implied mass held. An empty flyway idles near 11 W;
  the one carrying the mover draws about 80 W more.
- **Tracking error, 20 Hz.** Position minus reference (`get_all_xbot_info` with
  `REFERENCE`), in µm. The two reads are a few ms apart, so the bridge shifts the
  reference back to the position's sample time using the reference's own velocity;
  at rest the correction is zero. A couple of µm at rest is the noise floor.
- **PMC coordinates.** Positions are shown as the PMC reports them, origin at the outer
  corner of flyway 1, marked X/Y in the view. Nothing to calibrate.
- Setup: Python 3.12 venv in `.venv`, with `pmclib` installed from PMI's
  `pmclib-117.15.01-py3.zip` (brings `pythonnet` and `numpy`). Bridge itself is stdlib.

## View options

**View** in the header opens a panel of switches and colours, saved per browser
(`localStorage`; the page works the same if storage is blocked).

- **Flyway:** show or hide the readings strip and the Flyways, Movers and Receivers
  panels; in 3D, tile power colour, power labels on tiles, received power on the
  xBots, xBot numbers and the X/Y axes; mover position, lift, tracking error, and the
  flyway trends and temperatures.
- **Cage:** readings strip, Points and Receivers panels; in 3D, rulers and axes,
  point labels, drop lines from each point to the floor.
- **Colours:** accent, power scale, xBot finish, 3D background. The power scales
  are single-hue: blue is the dataviz reference ramp, teal, violet and amber keep its
  lightness and chroma step for step at another hue.

## Plot data

**Plot data** in the header records every reading, with the position it was taken at,
while a receiver streams at a cage point or on an xBot (5 Hz: time, x/y/z, W, V, A, and
stator W on the flyway). It plots them four ways, filtered by reading, time range and
receiver:

- **Heat map:** the cage from the top, front and side (the flyway from the top), each
  cell the mean of the readings inside it; *Show spots in 3D* colours every measured
  spot in the 3D view.
- **Locations:** one sortable row per spot (10 mm) per receiver: means, range, count,
  time there.
- **Over time:** a line per receiver, with a crosshair naming the point each reading
  came from.
- **vs position:** each spot's mean against distance from a chosen point (add the TX as
  a point) or against X, Y or Z.

**Export CSV** writes `time, receiver, mac, rig, place, x_mm, y_mm, z_mm, power_W,
voltage_V, current_A, stator_W`, one row per reading.

## Receivers (Saguaro)

A Saguaro board, riding on an xBot or clamped at a cage point, reports its own measurements over WiFi. The bridge
finds and reads them the way Fennec2 does (`bridge/saguaro.py`, protocol taken from
Fennec2 v1.7.1 `Devices/MCU/McuDevice.cs` and `Communication/protobuf/fennec2.proto`):

- **Detect.** Boards multicast `<port>-SAGUARO-<MAC>` to `224.0.0.251:4210` about once a
  second; each shows up in the Receivers panel, not yet connected.
- **Only what's reachable.** A board is listed while it has announced in the last 3.5 s
  or is streaming to the bridge; anything else drops out within seconds. Assignments
  are kept, so an assigned board reappears and reconnects by itself when it's back.
  (No test connections are made to check: a board may accept one client only.)
- **Connect.** TCP to the board, then Fennec2's handshake: `fennec2` → name and firmware,
  `ep-man list` → its endpoints, `print protobuf` + `s 1` → telemetry (protobuf frames
  split on `AA 55 0D 0A`), `ping` keep-alive, reconnect after 4 s of silence. The
  bridge only connects boards you connect or assign, so it won't take a board that
  Fennec2 is using by accident.
- **Assign.** *Rides on* (Flyway view) picks the xBot, *At point* (Cage view) the cage
  point; setting one clears the other. *Power from*, *Voltage from* and *Current from*
  pick the endpoints that carry W, V and A. They're guessed on first contact from the
  unit the board reports for each endpoint, or else from names like `P_out`, `V_out`
  and `I_out`, and switched on with `ep-man index` if the board had them off. Saved in `bridge/receivers.json` by MAC, so assigned boards
  reconnect by themselves after a restart.
- **Monitor.** The receiver's card, and the mover's or point's, show power, voltage and
  current side by side, each with a 60 s trend. The 3D view labels the mover with its
  power and the point with all three, and the readings strip totals the power.

No board on hand? `bridge\fake_saguaro.py` runs fake boards (MACs `02:00:00:5A:67:xx`, a
locally administered range no real board uses) that speak the same
protocol over real sockets:

```powershell
.\.venv\Scripts\python.exe bridge\fake_saguaro.py        # terminal 1: two fake boards
.\.venv\Scripts\python.exe bridge\pmc_bridge.py          # terminal 2: as usual
```

For tests, `--receivers-file PATH` keeps assignments out of the real `bridge/receivers.json`;
cage points then go to `cage_points.json` in the same folder. If a bridge is already
running, give the test one its own `--port`: on Windows a second bridge can bind 8765
too, and requests may reach the old one.

The protobuf decoding is hand-written (stdlib only) and was checked against the official
protobuf library compiled from Fennec2's `.proto`, both directions.

## Tests

The bridge has a stdlib `unittest` suite in `tests/`. It covers the protobuf codec,
endpoint guessing, points and assignments, snapshot readings, request validation, and
the HTTP routes against a real server on a random port. It never binds 8765, never
listens for or connects to real boards, and keeps its stores in a temp folder.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Data sources

| What | Where it comes from |
|---|---|
| Receiver power | Saguaro boards, on the flyway and in the cage (above). Fennec2's VISA loads (SDL1030X-E, KEL2030) answer `:MEAS:POW?` directly if the cage ever needs them. |
| Mover pose | `PMCLIB.dll`, referenced directly from C#. See [docs/PMI-PMCLIB.md](docs/PMI-PMCLIB.md). |

Cage positions are configuration you measure once and type in. The rig does not
report them and never will.

## Known gaps

- The grey equipment box visible inside the cage in the CAD screenshot is not
  modelled — unclear what it is.
- The CAD shows a beam passing through the cage and out the far side. If that is a
  rail the TX travels along rather than a fixed mount, the cage becomes a second
  sweep rig and this tool needs rethinking on that side.
- Cage dimensions are hard-coded: `BAR_LEN` (1500 mm, one bar) near the top of
  `index.html`, with the cage two bars a side. If the real frame differs, that is the
  constant to change.
- Recorded readings (**Plot data**) live in the browser tab only; a reload clears them.
  Export CSV to keep a run.
- The cage's TX doesn't report its output, so *Sent* and *Efficiency* plots are Flyway
  only (from stator power, which also includes levitation and motion).
