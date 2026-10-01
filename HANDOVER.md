# Handover

Kevin He built this tool and is leaving. This page is for whoever takes it over.

## What this is, and where things are

Cage Power Map shows the power Saguaro receivers get against where they are, on the
3 m cage and on the PMI flyway: live in 3D, recorded, and plotted (heat map,
per-location table, over time, against distance), with CSV export.

- [README.md](README.md): how it works, the code map, and the conventions.
- User manual (French, for people running tests):
  [Manuel d'utilisateur - Internal Data Tool](https://awle.atlassian.net/wiki/spaces/BK/pages/1658978305/Manuel+d+utilisateur+-+Internal+Data+Tool)
- [docs/CAGE-GEOMETRY.md](docs/CAGE-GEOMETRY.md): the cage's bars and their names.
  [docs/PMI-PMCLIB.md](docs/PMI-PMCLIB.md): what the PMC library is and the calls that matter.

## Run it and test it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt      # plus pmclib, see the file
.\.venv\Scripts\python.exe bridge\pmc_bridge.py                     # or --mock, without a PMC
# open http://localhost:8765

.\.venv\Scripts\python.exe -m unittest discover -s tests -v         # bridge tests, 40, no hardware
```

Without hardware, run `bridge\fake_saguaro.py` next to `pmc_bridge.py --mock`. The
page has no automated tests. README → Development says how to check it by hand.

## Branch state

The cleanup is on the local branch **`cleanup/handover`**, on top of `main`, and has
**not been pushed**:

1. A snapshot of the work that was uncommitted (Plot data, the hover ghost, receiver and point changes).
2. The bridge split into modules, a fix for unlocked shared state between threads, and the test suite.
3. The page split from one 2,400-line `index.html` into `web/` (markup, styles, 25 ES modules).
4. The README, `requirements.txt`, `.gitattributes` and this file.

Review it, push it, then merge it into `main`.

## Things only Kevin can do before leaving

- [ ] **Push `cleanup/handover`** and merge it once reviewed.
- [ ] **Move the GitHub repo** off the personal account (`kevinawl/cage`) to the team's
      organisation (GitHub → Settings → Transfer), or give a teammate admin access.
- [ ] **Move the spec into the team space.** *Graph Automation Feature* lives in Kevin's
      personal Confluence space (`~712020…`, page `1625128980`). Move it into BK, then
      update its links in `README.md` and `docs/CAGE-GEOMETRY.md`.
- [ ] **Put `pmclib-117.15.01-py3.zip` on a shared drive.** The only copy is in Kevin's
      `~/Downloads`. Write its path here and in `requirements.txt`. Better still, ask PMI
      for the proper .NET/Python distribution (see docs/PMI-PMCLIB.md).
- [ ] **Hand over anything else personal:** the claude.ai demo page that used to be
      linked from the README was private to Kevin. It has been removed and isn't
      needed. Also check for anything else under his personal accounts (bench PC
      logins, bookmarks to `localhost:8765` set up for him).

## Known gaps and next steps

- **No transmitter telemetry for the cage.** The TX doesn't report its output, so
  *Sent* and *Efficiency* exist only on the flyway (from stator power, which also
  pays for levitation and motion). Reading the TX into the bridge would add them for
  the cage.
- **Recordings live in the browser tab.** A reload loses them unless exported to CSV.
  The fix is a recorder in the bridge (append readings to a file per run) that the
  page reads back.
- **No automated tests for the page.** A headless-browser smoke test against
  `--mock` + `fake_saguaro.py` would catch most regressions.
- **Older JS style inside functions.** Function bodies in `web/js` still use ES5
  (`var`, `function`); module-level code is modern. Convert one module at a time if
  you're in there anyway.
- **Positions are typed in.** The cage doesn't measure where a receiver is: the
  point in the tool must be moved at the same time as the board (or recording paused).
- **Cage model.** The CAD's grey equipment box isn't modelled. If the beam through the
  cage is a rail the TX travels along, the cage side needs rethinking. Dimensions are
  constants in `web/js/config.js` (`BAR_LEN`).
