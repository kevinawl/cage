# Cage geometry and bar naming

Modelled from the CAD screenshot on the
[Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/~712020668dad7d79b94b1991606ab1a9931a0c/pages/1625128980/Graph+Automation+Feature)
Confluence page.

## Structure

A **3 m cube** whose every face is divided 2×2 by mid-span members. Lines exist only
where they lie **on a face**, so nothing crosses the working volume. That is what the
CAD shows, and it's what you'd want in a test cage.

Every **bar is 1.5 m**: one span between two joints. Each of the 24 lattice lines is
two bars joined at its middle, giving **48 bars**:

| Group | Count | Runs |
|---|---|---|
| `X-*` | 16 | west → east |
| `Y-*` | 16 | south → north |
| `Z-*` | 16 | floor → top |

The bars are generated in `index.html` rather than listed by hand: see the `BARS`
block near the top. `BAR_LEN` is one bar, and the cage is two bars a side (`CAGE`).

## Coordinates

Origin at the centre of the cage floor. X runs west → east and Y south → north, both
−1500 to +1500. Z runs 0 to 3000 upward. All values are in mm. Cage points (where
receivers sit) are typed in these coordinates. The 3D view draws a ruler for each axis,
with ticks every 250 mm, numbers every 500 mm, long ticks at the joints and each bar's
span labelled `1.5 m`.

## Naming

Systematic, so a bar id can be read without a diagram:

```
X-TOP-S-W     X bar · top level  · south line · west bar of the two
Y-MID-E-N     Y bar · mid level  · east line  · north bar of the two
Z-NW-LO       Z bar · north-west post · lower bar (floor to mid joint)
```

Levels are `BOT` (z=0), `MID` (z=1500) and `TOP` (z=3000). Lines are `S`/`C`/`N` for X
bars and `W`/`C`/`E` for Y bars, where `C` is the centre line. `C` is left out of `Z-*`
ids, so the mid-face posts are `Z-N`, `Z-S`, `Z-E` and `Z-W`, and the corner posts are
`Z-NW`, `Z-NE`, `Z-SW` and `Z-SE`. The last part says which of the two bars on that line
is meant: `W`/`E`, `S`/`N`, or `LO`/`HI`.

## Measuring along a bar

Every bar has a fixed zero end, chosen so the reading matches a tape laid from that end:

- X bars: 0 at the bar's **west end**
- Y bars: 0 at the bar's **south end**
- Z bars: 0 at the **floor** (`LO`) or at the **mid joint** (`HI`)

Each reading is 0 to 1500 mm. When a point lies on a bar (within 1 mm), the point
editor shows it as the bar id and a distance, e.g. `Z-NW-HI, 600 mm from the mid joint`.
Clicking a bar in the view puts the selected point there, snapped to 10 mm.

## The stand

Off the **south-east corner**, centre at `(1900, −2000)`: `STAND_X` / `STAND_Y` in
`index.html`. Three shelves: PSU on top, TX electronics on the middle one.

## What is not modelled

- The grey box inside the cage in the CAD. Unclear what it is.
- The beam passing through the cage and out the far side in the CAD. Left out
  deliberately — if it is a rail the TX travels along rather than a fixed mount, the
  cage becomes a sweep rig and the whole cage side needs rethinking.
- The transmitter's position in the cage. Nothing uses it yet; add it as a point if it
  helps to see it.
