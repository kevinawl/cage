# Cage Power Map

Prototype that shows the power Saguaro receivers get against where they are, on the
3 m cage and the PMI flyway: live in 3D, recorded, and plotted. To be rebuilt in Fennec;
see [HANDOVER.md](HANDOVER.md) and the
[Confluence page](https://awle.atlassian.net/wiki/spaces/BK/pages/1658978305/Manuel+d+utilisateur+-+Internal+Data+Tool).

## Run it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt     # see the note on pmclib inside
.\.venv\Scripts\python.exe bridge\pmc_bridge.py                    # add --mock to run without a PMC
```

Open **<http://localhost:8765>**.

## Code

- `bridge/`: Python, reads the PMC and the Saguaro boards and streams to the page. Start with `pmc_bridge.py`.
- `web/`: the page (three.js, plain ES modules, no build). Start with `js/main.js`.
