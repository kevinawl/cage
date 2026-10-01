# Cage Power Map

Proof of concept for the *Graph Automation Feature* — delivered power shown against
position, on two separate test rigs.

Spec: [Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/BK/pages/1658978305/Manuel+d+utilisateur+-+Internal+Data+Tool)
(Confluence, page id `1625128980`).

## Running it

Open `index.html` in a browser. No build, no server, no install. Everything is in
that one file; the only external dependency is three.js from cdnjs, so the machine
needs a network connection the first time.

A published copy lives at <https://claude.ai/artifact/NDhhLFdDeR58VcntYFEFBf>
(private — share it from the page's Share menu before sending the link on).

## The cage data is simulated

Nothing here talks to hardware. The power numbers come from a coupling model
(distance falloff × coil alignment) that behaves plausibly and makes the UI
responsive. **It is not a field solver — do not read absolute watts off it.**

The page says so in a badge. Keep that badge until real data is wired in.

## The two rigs

They are separate setups and the tool keeps them separate — own geometry, own
receivers, own log, own CSV shape. Switch between them in the header.

### Cage

24 structural members, each exactly 1500 mm, forming a 2×2 lattice on every face.
Nothing crosses the working volume. Receivers clamp **to the bars**: a position is a
bar name plus a distance from that bar's zero end, so the number in the app is the
number you get with a tape on the real frame. See [docs/CAGE-GEOMETRY.md](docs/CAGE-GEOMETRY.md).

A stand off the south-east corner carries the PSU and the TX electronics.

Four ways to set a position, all equivalent: type the exact mm, drag the slider,
click the bar ruler, or click a bar in the 3D view. Snap is selectable from 1 to 50 mm.

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
- **Cage:** readings strip, charts, bar position ruler, wiring notes.
- **Colours:** accent, power scale, xBot finish, 3D background. The power scales
  are single-hue: blue is the dataviz reference ramp, teal, violet and amber keep its
  lightness and chroma step for step at another hue.

## Receivers on the movers (Saguaro)

A Saguaro board riding on an xBot reports its own measurements over WiFi. The bridge
finds and reads them the way Fennec2 does (`bridge/saguaro.py`, protocol taken from
Fennec2 v1.7.1 `Devices/MCU/McuDevice.cs` and `Communication/protobuf/fennec2.proto`):

- **Detect.** Boards multicast `<port>-SAGUARO-<MAC>` to `224.0.0.251:4210` about once a
  second; each shows up in the Flyway view's Receivers panel, not yet connected.
- **Only what's reachable.** A board is listed while it has announced in the last 3.5 s
  or is streaming to the bridge; anything else drops out within seconds. Assignments
  are kept, so an assigned board reappears and reconnects by itself when it's back.
  (No test connections are made to check: a board may accept one client only.)
- **Connect.** TCP to the board, then Fennec2's handshake: `fennec2` → name and firmware,
  `ep-man list` → its endpoints, `print protobuf` + `s 1` → telemetry (protobuf frames
  split on `AA 55 0D 0A`), `ping` keep-alive, reconnect after 4 s of silence. The
  bridge only connects boards you connect or assign, so it won't take a board that
  Fennec2 is using by accident.
- **Assign.** *Rides on* picks the xBot; *Power from* picks the endpoint that carries
  watts (guessed from names like `P_out`; switched on with `ep-man index` if the
  board had it off). Saved in `bridge/receivers.json` by MAC, so assigned boards
  reconnect by themselves after a restart.
- **Monitor.** The mover's card leads with its received power and a 60 s trend, the
  3D view labels the mover with it, and the readings strip totals it.

No board on hand? `bridge\fake_saguaro.py` runs fake boards (MACs `02:00:00:5A:67:xx`, a
locally administered range no real board uses) that speak the same
protocol over real sockets:

```powershell
.\.venv\Scripts\python.exe bridge\fake_saguaro.py        # terminal 1: two fake boards
.\.venv\Scripts\python.exe bridge\pmc_bridge.py          # terminal 2: as usual
```

For tests, `--receivers-file PATH` keeps assignments out of the real `bridge/receivers.json`.

The protobuf decoding is hand-written (stdlib only) and was checked against the official
protobuf library compiled from Fennec2's `.proto`, both directions.

## Replacing the simulation

Two data sources, both already understood:

| What | Where it comes from |
|---|---|
| Receiver power | Flyway: Saguaro boards, live now (see below). Cage: Fennec2's VISA loads (SDL1030X-E, KEL2030) answer `:MEAS:POW?` directly; no V×I needed. |
| Mover pose | `PMCLIB.dll`, referenced directly from C#. See [docs/PMI-PMCLIB.md](docs/PMI-PMCLIB.md). |

Cage receiver positions are configuration you measure once and type in. The rig does
not report them and never will.

## Known gaps

- The grey equipment box visible inside the cage in the CAD screenshot is not
  modelled — unclear what it is.
- The CAD shows a beam passing through the cage and out the far side. If that is a
  rail the TX travels along rather than a fixed mount, the cage becomes a second
  sweep rig and this tool needs rethinking on that side.
- Cage dimensions are hard-coded at 1500 mm (`BAR_LEN` near the top of `index.html`).
  If the real frame differs, that is the one constant to change.
- Downloads are blocked inside a published artifact, so the CSV tab displays rows for
  copying rather than offering a file. Running `index.html` locally has no such limit,
  so a real export is straightforward if it is wanted.
