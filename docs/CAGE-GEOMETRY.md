# Cage geometry and bar naming

Modelled from the CAD screenshot on the
[Graph Automation Feature](https://awle.atlassian.net/wiki/spaces/~712020668dad7d79b94b1991606ab1a9931a0c/pages/1625128980/Graph+Automation+Feature)
Confluence page.

## Structure

A 1500 mm cube whose every face is divided 2×2 by mid-span members. Bars exist only
where they lie **on a face** — nothing crosses the working volume, which is both what
the CAD shows and what you would want in a test cage.

That gives **24 members, every one of them 1500 mm**:

| Group | Count | Runs |
|---|---|---|
| `X-*` | 8 | west → east |
| `Y-*` | 8 | south → north |
| `Z-*` | 8 | floor → top |

Generated in `index.html` rather than listed by hand — see the `BARS` block near the
top. Changing `BAR_LEN` rescales everything.

## Coordinates

Origin at the centre of the cage floor. X and Y run −750 to +750, Z runs 0 to 1500
upward. The inspector shows each receiver's X/Y/Z as a read-only cross-check.

## Naming

Systematic, so a bar id can be read without a diagram:

```
X-TOP-S     X bar · top level      · south line
Y-MID-E     Y bar · mid height     · east line
Z-NW        Z post · north-west corner
```

Levels are `BOT` (z=0), `MID` (z=750), `TOP` (z=1500). Lines are `S`/`C`/`N` for X
bars and `W`/`C`/`E` for Y bars, where `C` is the centre line — omitted from `Z-*`
ids, so the mid-face posts are `Z-N`, `Z-S`, `Z-E`, `Z-W` and the corners are
`Z-NW`, `Z-NE`, `Z-SW`, `Z-SE`.

## Measuring along a bar

Every bar's zero end is fixed and stated in the UI, chosen so a reading matches what
a tape gives you starting from the natural corner:

- X bars — 0 at the **west end**
- Y bars — 0 at the **south end**
- Z posts — 0 at the **floor**

A receiver position is therefore `(bar id, distance in mm)`, e.g. `Z-NW @ 910 mm`.
That is also how it appears in the CSV column header, so a logged run carries its own
geometry.

## The stand

Off the **south-east corner**, centre at `(1150, −1250)` — `STAND_X` / `STAND_Y` in
`index.html`. Three shelves: PSU on top, TX electronics on the middle one.
  deliberately — if it is a rail the TX travels along rather than a fixed mount, the
  cage becomes a sweep rig and the whole cage side needs rethinking.
- The transmitter is a model parameter (position only, set in the Stand panel) and is
  not drawn. The link lines converge on it.
