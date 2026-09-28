# Cage Power Map

Proof of concept for the *Graph Automation Feature* — delivered power shown against
position, on two separate test rigs.

Spec: [Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/~712020668dad7d79b94b1991606ab1a9931a0c/pages/1625128980/Graph+Automation+Feature)
(Confluence, page id `1625128980`).

## Running it

Open `index.html` in a browser. No build, no server, no install. Everything is in
that one file; the only external dependency is three.js from cdnjs, so the machine
needs a network connection the first time.

A published copy lives at <https://claude.ai/artifact/NDhhLFdDeR58VcntYFEFBf>
(private — share it from the page's Share menu before sending the link on).

## All the data is simulated

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

PMI planar motor. The mover's pose drives the display; "Run sweep" rasters it over
the stator in a serpentine path and builds a coverage heatmap of delivered power per
position.

## Replacing the simulation

Two data sources, both already understood:

| What | Where it comes from |
|---|---|
| Receiver power | The path Fennec already uses — two `DataEndpoint`s off the VISA load, multiplied into a custom endpoint. No new measurement code. |
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
