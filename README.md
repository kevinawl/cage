# Cage Power Map

Prototype that shows the power Saguaro receivers get against where they are, on the
3 m **cage** and the PMI **flyway**: live in 3D, recorded, and plotted. The next step is
to rebuild it in Fennec, so read [HANDOVER.md](HANDOVER.md) first.

- Features to keep, with screenshots (French): [Manuel d'utilisateur - Internal Data Tool](https://awle.atlassian.net/wiki/spaces/BK/pages/1658978305/Manuel+d+utilisateur+-+Internal+Data+Tool)
- Spec: [Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/~712020668dad7d79b94b1991606ab1a9931a0c/pages/1625128980/Graph+Automation+Feature)

## Run it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt     # see the note on pmclib inside
.\.venv\Scripts\python.exe bridge\pmc_bridge.py                    # PMC at 192.168.17.150
.\.venv\Scripts\python.exe bridge\pmc_bridge.py --mock             # or: simulated movers, no PMC
```

Open **<http://localhost:8765>**. Run one bridge at a time.

## How it works

```
 Saguaro boards ──TCP/protobuf──┐
 PMC (pmclib) ──────────────► bridge/ (Python) ──events──► web/ (browser)
                              read-only          ◄──POST──  points, assignments
```

- **The bridge** reads the PMC (poses at 20 Hz, flyway power and temperatures at 2 Hz)
  and the Saguaro boards it's told to (power, voltage, current at 5 Hz), and streams it
  all to the page as Server-Sent Events. It never moves anything. Standard library only,
  plus `pmclib` for a real PMC.
- **The page** draws the rigs with three.js, shows the panels, and records and plots
  the readings. Plain ES modules: no build, no framework.

| Path | What |
|---|---|
| `bridge/pmc_bridge.py` | Entry point. Its docstring documents the event format. |
| `bridge/pmc_sources.py` | The PMC (and `--mock`): poses, layout, telemetry. |
| `bridge/saguaro.py`, `saguaro_protocol.py` | Saguaro boards: discovery, sessions, protobuf decoding. |
| `bridge/http_api.py`, `events.py` | HTTP routes (listed in its docstring) and the event stream. |
| `web/js/` | The page, one concern per module; `main.js` is the entry point. |
| `docs/` | Cage geometry and bar names; PMC library notes. |

Config is saved next to the bridge: `receivers.json` (which board is where) and
`cage_points.json` (measured positions).

## Features

- **Cage:** the 48 bars to scale, in the axes marked on the cage (origin at the floor
  centre, mm). Points mark where receivers sit; place one by clicking a bar.
- **Flyway:** tiles and xBots as the PMC reports them, coloured by power draw, with
  pose, lift and tracking error.
- **Receivers:** found on the network, assigned to a cage point (*At point*) or an xBot
  (*Rides on*); their power, voltage and current are shown where they are.
- **View:** toggles to show or hide each panel and 3D detail.
- **Plot data:** every reading is recorded with its position, then shown as a heat
  map, a table per location, over time, or against distance (e.g. from the TX). Save
  as PNG or CSV. Recordings live in the browser tab, so export before reloading.

Known gaps are listed in [HANDOVER.md](HANDOVER.md).
