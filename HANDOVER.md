# Handover

Kevin He built this prototype and is leaving. The next step is to rebuild its main
features in Fennec; this repo is the reference for that.

## What this is, and where things are

Cage Power Map shows the power Saguaro receivers get against where they are, on the
3 m cage and on the PMI flyway: live in 3D, recorded, and plotted (heat map,
per-location table, over time, against distance), saved as PNG or CSV.

- [README.md](README.md): how it works, the code map, the conventions.
- Features to keep in Fennec, with screenshots (French):
  [Manuel d'utilisateur - Internal Data Tool](https://awle.atlassian.net/wiki/spaces/BK/pages/1658978305/Manuel+d+utilisateur+-+Internal+Data+Tool)
- [docs/CAGE-GEOMETRY.md](docs/CAGE-GEOMETRY.md): the cage's bars and their names.
- [docs/PMI-PMCLIB.md](docs/PMI-PMCLIB.md): what the PMC library is, and why Fennec can reference it directly.

## Run it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt      # plus pmclib, see the file
.\.venv\Scripts\python.exe bridge\pmc_bridge.py                     # or --mock, without a PMC
# open http://localhost:8765
```

`--mock` simulates the PMC; the receivers need real Saguaro boards. This is a prototype
with no tests; README → Development says how to check a change.

## Branch state

The cleanup is on the local branch **`cleanup/handover`**, on top of `main`, and has
**not been pushed**:

1. A snapshot of the work that was uncommitted (Plot data, the hover ghost, receiver and point changes).
2. The bridge split into modules, and a fix for unlocked shared state between threads.
3. The page split from one 2,400-line `index.html` into `web/` (markup, styles, ES modules).
4. The README, `requirements.txt`, `.gitattributes` and this file.
5. Fixes from a review of the refactor (stricter request origins and file paths).
6. Save image in Plot data.
7. Test code removed (unit tests, fake boards, screenshot tool): this is a prototype.

Review it, push it, then merge it into `main`.

## Things only Kevin can do before leaving

- [ ] **Push `cleanup/handover`** and merge it once reviewed.
- [ ] **Move the GitHub repo** off the personal account (`kevinawl/cage`) to the team's
      organisation (GitHub → Settings → Transfer), or give a teammate admin access.
- [ ] **Move the spec into the team space.** *Graph Automation Feature* lives in Kevin's
      personal Confluence space (`~712020…`, page `1625128980`). Move it into BK, then
      update its links in `README.md` and `docs/CAGE-GEOMETRY.md`.
- [ ] **Put `pmclib-117.15.01-py3.zip` on a shared drive.** The only copy is in Kevin's
      `~/Downloads`. Write its path here and in `requirements.txt`.
- [ ] **Add the screenshots to the Confluence page,** in their marked slots.

## Known gaps, for the Fennec version

- **No transmitter telemetry for the cage.** The TX doesn't report its output, so
  *Sent* and *Efficiency* exist only on the flyway (from stator power, which also
  pays for levitation and motion).
- **Recordings live in the browser tab.** A reload loses them unless exported. Fennec
  should store them in the application.
- **Positions are typed in.** The cage doesn't measure where a receiver is: the point
  in the tool must be moved at the same time as the board (or recording paused).
- **Cage model.** The CAD's grey equipment box isn't modelled. If the beam through the
  cage is a rail the TX travels along, the cage side needs rethinking. Dimensions are
  constants in `web/js/config.js` (`BAR_LEN`).
