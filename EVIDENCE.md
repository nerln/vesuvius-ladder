# Evidence

The release verification was run on a MacBook M4 with 16 GB and no GPU against
the anonymous public-data bucket. `data_manifest.json` records exact asset
sizes and SHA-256 digests for the two clean-checkout experiments; the committed
JSON snapshots record their inputs and results.

## 0. One command reproduces the finding

```bash
python3 check_duplicate.py ./check_data
```

Output (verbatim):

```
========================================================================
w045 grid (676, 490)  valid 109823
w046 grid (684, 498)  valid 109823
bbox identical: True
w046 meta: mode=gen_neighbor dir=out max_gen=2 copy_moved_points=13674

best mask alignment of w045 inside w046: offset (4,4), cells valid in both = 109823
mask XOR at that offset = 0  (0 means the masks are identical)

vertices compared: 109823
bit-identical in all three channels: 89503 = 81.4975%
displaced: 20320   median displacement of those: 13.724 vx   max 66.52 vx
displaced components (8-connected): 1   largest 20320   bbox rows/cols [168, 283, 37, 238]

median nearest-neighbour distance between consecutive surfaces:
  w044->w045: median   19.382 vx    fraction within 2 vx: 0.0003
  w045->w046: median    0.000 vx    fraction within 2 vx: 0.8198
  w046->w047: median   32.525 vx    fraction within 2 vx: 0.0001

published ink detections (2.399 um, model 20260417190342), correlation after alignment:
  w044/w045: shift (-23, 49)   r = +0.008   over 10.00 Mpx
  w045/w046: shift (0, 2)   r = +0.810   over 10.30 Mpx
  w046/w047: shift (-65, 83)   r = -0.051   over 9.61 Mpx
========================================================================
```

The two surfaces are `PHerc0139/segments/20260126000000-w045_2026012619` and
`PHerc0139/segments/20260325000000-w046_20260325`, tifxyz at
`mesh/intermediate/tifxyz_original/`.

## 1. The tool, on the scroll

```bash
python3 ladder.py scan --sample PHerc0139 --collection dup.json --json pairs.json
```

37 surfaces, 1332 ordered pairs, 28 s after download. Verbatim ladder:

```
surfaces: 37   nominal grid step: 20.0 vx
sheet-spacing unit (median over surfaces of the distance to their nearest companion surface): 15.22 vx

winding ladder (36 consecutive pairs)
        pair  d_med(vx)   ratio  coincid.   cover  verdict
  w023-w024      20.17   1.325     0.001   1.000  distinct
  w024-w025      20.62   1.355     0.001   1.000  distinct
  w025-w026      16.70   1.097     0.001   1.000  distinct
  w026-w027      14.67   0.964     0.002   1.000  distinct
  w027-w028      16.64   1.094     0.001   1.000  distinct
  w028-w029      16.11   1.059     0.001   1.000  distinct
  w029-w030      15.22   1.000     0.004   1.000  distinct
  w030-w031      16.71   1.098     0.001   1.000  distinct
  w031-w032      14.19   0.932     0.001   1.000  distinct
  w032-w033      14.56   0.957     0.000   1.000  distinct
  w033-w034      12.93   0.850     0.001   1.000  distinct
  w034-w035      18.67   1.227     0.000   0.788  distinct
  w035-w036      17.84   1.172     0.000   1.000  distinct
  w036-w037      17.17   1.128     0.000   1.000  distinct
  w037-w038      18.05   1.186     0.000   1.000  distinct
  w038-w039      16.56   1.088     0.000   1.000  distinct
  w039-w040      19.51   1.282     0.000   1.000  distinct
  w040-w041      18.42   1.210     0.001   1.000  distinct
  w041-w042       9.60   0.631     0.005   1.000  distinct
  w042-w043      16.67   1.096     0.000   1.000  distinct
  w043-w044      16.83   1.106     0.000   1.000  distinct
  w044-w045      19.38   1.274     0.000   1.000  distinct
  w045-w046       0.00   0.000     0.816   1.000  DUPLICATE  <<<<
  w046-w047      32.67   2.147     0.000   1.000  distinct
  w047-w048      17.39   1.143     0.000   1.000  distinct
  w048-w049      15.72   1.033     0.001   1.000  distinct
  w049-w050      16.14   1.060     0.001   0.562  distinct
  w050-w051      14.93   0.981     0.001   1.000  distinct
  w051-w052      13.41   0.881     0.001   1.000  distinct
  w052-w053      14.82   0.974     0.001   1.000  distinct
  w053-w054      14.89   0.979     0.001   1.000  distinct
  w054-w055      15.22   1.000     0.001   1.000  distinct
  w055-w056      16.11   1.058     0.001   0.996  distinct
  w056-w057      16.24   1.067     0.000   1.000  distinct
  w057-w058      14.74   0.969     0.001   1.000  distinct
  w058-w059      15.84   1.041     0.000   1.000  distinct

duplicate pairs: 1   (coincident fraction > 0.5 within 1.52 vx)
  coincident=0.818  d_med=0.00vx  ratio=0.000  cover=1.000   20260325000000-w046_20260325  ==  20260126000000-w045_2026012619

closest non-duplicate pair: coincident=0.006 d_med=9.42vx ratio=0.619   20260206000000-w042_2026020613  ==  20260108000000-w041_2026010816
```

The coincident fraction is 0.818 for the duplicate and at most 0.006 for every
other consecutive pair of this scroll — a factor of 136. The median-distance
ratios of the 35 sound pairs span 0.63–1.36; the duplicate is 0.000 and the
pair straddling the missing wrap is 2.147.

## 2. The tool, on the whole published corpus

```bash
for S in PHerc0009B PHerc0139 PHerc0332 PHerc0343P PHerc0500P2 \
         PHerc0800 PHerc0814 PHerc1447 PHercMANBp PHercParis4; do
  python3 ladder.py scan --sample $S
done
```

| scroll | surfaces | unit (vx) | duplicates | highest coincident fraction among non-duplicates |
| --- | --- | --- | --- | --- |
| PHerc0009B  | 18 | 23.08 | 0 | 0.046 |
| PHerc0139   | 37 | 15.22 | **1** (coincident **0.818**) | 0.006 |
| PHerc0332   |  2 | 42.31 | 0 | 0.001 |
| PHerc0343P  |  8 | 15.95 | 0 | 0.001 |
| PHerc0500P2 | 39 | 11.64 | 0 | 0.127 |
| PHerc0800   |  6 | 20.22 | 0 | 0.001 |
| PHerc0814   | 12 | 13.75 | 0 | 0.032 |
| PHerc1447   | 15 | 38.62 | 0 | 0.096 |
| PHercMANBp  | 11 | 76.24 | 0 | 0.024 |
| PHercParis4 | 39 | 28.42 | 0 | 0.012 |
| PHerc0172   |  1 |  —    | — | single surface, nothing to pair |

188 surfaces, 5142 ordered pairs, one duplicate at 0.818. The highest score
anywhere else in the corpus is 0.127 — two `z_dbg_gen` snapshots of a single
growth run on PHerc0500P2, which genuinely share surface without coinciding.
The margin between the defect and the busiest legitimate overlap is 6.4x.

The full corpus sweep is `corpus_ladder.txt`.

## 3. Independent re-derivation

The finding was re-derived from scratch, in a separate working directory, by a
worker given only the bucket URL, the tifxyz layout and the question "are any
two of PHerc0139's published surfaces the same surface" — no method and no
answer. It wrote its own loader (using Pillow, because `tifffile.imread`
segfaults on these LZW float32 TIFFs under `imagecodecs 2026.6.26`), computed
all 1332 ordered pairs, and reported:

- of 1332 pairs, only 2 have median NN distance below 1.0 vx, and they are the
  two directions of w045/w046;
- the next-smallest median in the whole scroll is 9.41 vx — a gap of 9.4 voxels
  between rank 2 and rank 3;
- only 2 of 1332 pairs contain any exactly-coincident vertex at all, and they
  are the two directions of this pair;
- 89,503 / 109,823 vertices bit-identical (81.4975 %), mask XOR = 0 after the
  (+4,+4) pad;
- the displaced vertices form **one contiguous block, rows 168–283 ×
  cols 37–238**;
- median NN grows linearly with winding gap: |Δw| = 1/2/3/4/8 →
  16.4 / 29.3 / 43.6 / 58.1 / 123.5 vx. `w046→w047 = 32.5` sits on the |Δw| = 2
  line, not the |Δw| = 1 line.

It also found a discrepancy I had not: `w046`'s meta.json says
`copy_moved_points: 13674`, but 20,320 grid cells actually changed position.

## 3b. It is unique in the scroll, exactly

Bit-identical vertices are the sharpest test available, so I ran it over
everything. Reading all 37 surfaces, hashing each valid vertex as its raw
12-byte float32 triple, and intersecting all 666 unordered pairs:

```
segments: 37 windings 23 .. 59
unordered pairs examined: 666
  w045 & w046: 89503 shared bit-identical vertices (81.50% of the smaller surface)
pairs with ANY shared vertex: 1
```

One pair out of 666 shares a single vertex with another surface, and it shares
89,503 of them. Every other pair — including the other `gen_neighbor` outputs
w047, w048, w049 against their own predecessors — shares exactly zero. The
precise figure is 89,503 / 109,823 = **81.4975 %**.

## 3c. The gap measures like two sheets, on region-matched controls

Median nearest-neighbour distance in the original frame, one-sheet steps beside
genuine two-sheet controls over the same material:

```
  w044 -> w045  (1 sheet ):   19.38 vx
  w045 -> w046  (1 sheet ):    0.00 vx
  w046 -> w047  (1 sheet ):   32.53 vx
  w047 -> w048  (1 sheet ):   17.43 vx
  w048 -> w049  (1 sheet ):   15.67 vx
  w044 -> w046  (2 sheets):   21.54 vx
  w045 -> w047  (2 sheets):   34.84 vx
  w047 -> w049  (2 sheets):   31.34 vx
  w046 -> w048  (3 sheets):   48.78 vx
```

Two things fall out. `w046 → w047` at 32.53 sits on the two-sheet line (31.34),
not the one-sheet line (15–19). And `w044 → w046`, nominally two sheets apart,
measures 21.54 — a *one*-sheet distance, which is what it must be if w046 is
w045.

## 3d. Model-based evidence for an intervening surface

This experiment is supporting evidence from a published surface-prediction
model, not a direct physical measurement. It uses the meshes published in the
9.362 µm frame
(`mesh/<stamp>-on-20250728140407-9.362um.tifxyz/`) and the prediction volume
`PHerc0139/representations/predictions/surfaces/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr`.
No coordinate transform is estimated.

The clean-checkout command downloads the five pinned meshes and the required
Zarr chunks, validates their hashes, writes the complete JSON snapshot, and
renders the figure:

```bash
python3 raytest.py --work ./ray_data \
  --output ./results/ray_PHerc0139.reproduced.json \
  --figure ./fig_gap.reproduced.png
```

With deterministic seed 1, 400 vertices per pair are sampled in z=4000–4600.
Each ray has 65 samples between a source vertex and its nearest vertex on the
other surface. The frame check samples w047 itself: median response 255 and
55.5% above 128. Points displaced 200 voxels in deterministic random
directions have median 0 and 16.0% above 128.

A ray is classified as having a distinct **interior model response** when a
sample strictly inside the gap exceeds 128 and is separated from both endpoints
by a sample below 64.

```
        pair     n  median len  interior response     length-matched 40-55 vx
  w046->w047   400        46.2       372/400  93.00%      85/86   98.84%
  w047->w048   400        20.1       125/400  31.25%       2/28    7.14%
  w048->w049   400        16.8       123/400  30.75%       1/3    (too few)
  w047->w049   400        34.6       379/400  94.75%      94/95   98.95%
  w045->w047   400        48.8       381/400  95.25%     102/102 100.00%
```

The unmatched rates are confounded by ray length. In the predeclared 40–55
voxel band, the `w046→w047` model-response rate is close to the two-sheet
controls and far from the one-sheet control. That is consistent with an
intervening, untraced winding. It does not prove that interpretation
independently of the model. Figure: `fig_gap.png`; full inputs and outputs:
`results/ray_PHerc0139.json`.

## 4. Existing tooling does not see it

`vc_tifxyz_selfcross` (villa's only purpose-built surface defect detector,
merged as #1303) on both surfaces:

```bash
vc_tifxyz_selfcross ladder_data/PHerc0139/20260126000000-w045_2026012619 -o sc45.json
vc_tifxyz_selfcross ladder_data/PHerc0139/20260325000000-w046_20260325     -o sc46.json
```

```
w045: 218174 triangles, 165 transverse (diag 0), 176 transverse (diag 1)
w046: 218174 triangles, 178 transverse (diag 0), 173 transverse (diag 1)
```

Both are reported the same way. Each surface is unremarkable on its own; the
defect exists only between them, and a single-surface census cannot express it.

`vc_seg_add_overlap`, which does compare segments, reports overlap as a boolean
list at a 2.0 vx tolerance:

```bash
vc_seg_add_overlap --target segs --source segs
```

```
Queried source points: 4224134
Overlap pairs found: 180
```

180 overlapping pairs among these 37 surfaces, w045/w046 among them and
indistinguishable from the other 179. Overlap between traced segments is
normal. Coincidence is not. Nothing measured the difference.

## 5. Winding 46 is not published anywhere else

```bash
curl -s "https://vesuvius-challenge-open-data.s3.amazonaws.com/?list-type=2&prefix=PHerc0139/segments/&delimiter=/&max-keys=500"
```

38 segment prefixes, `IsTruncated` false: w023-w059 exactly once each, plus
`20260422000000-title_2026042222_zmid_flatboi`. There is no second w046 and no
unnumbered segment that could be it.

## 6. Coordinate frames — the objection that would sink this

Consecutive windings of PHerc0139 were traced against three different surface
volumes (`2um_srf_ds2`, `4.681um_113keV_1.2m_binmean_2_PHerc_0139_110_surf`,
`.vc3d_rasterize_20260313123342`), which raises the question of whether the
ladder is comparing like with like. It is:

- all 37 declare `scale = 0.05` and `scroll_source = PHerc0139`;
- pairs that cross a volume change behave normally — `w039→w040` crosses one
  and measures 19.5 vx, `w044→w045` measures 19.4 vx;
- `w045` (volume `4.681um…`) and `w046` (volume `2um_srf_ds2`) carry
  **bit-identical bboxes to 16 significant digits** and 81.5 % bit-identical
  vertex coordinates, which is only possible in a shared frame.

## 7. Where it came from, and how often

Seven published PHerc0139 surfaces were produced by VC3D's neighbour-copy
(`vc_gsfs_mode: gen_neighbor`) — the "Copy Out / Copy In" acceleration that
copies a finished winding onto the next wrap and re-settles it. Checked against
the ladder:

| w | dir | copy_moved_points | separation from w-1 | coincident with w-1 | separation to w+1 |
| --- | --- | --- | --- | --- | --- |
| 36 | in  | —      | 1.172 | 0.000 | 1.128 |
| 37 | in  | —      | 1.128 | 0.000 | 1.186 |
| 38 | in  | —      | 1.186 | 0.000 | 1.088 |
| 46 | out | 13674  | **0.000** | **0.816** | **2.147** |
| 47 | out | 14124  | 2.147 | 0.000 | 1.143 |
| 48 | out | 2099   | 1.143 | 0.000 | 1.033 |
| 49 | out | 6107   | 1.033 | 0.001 | 1.060 |

Six of seven landed on the next wrap. One did not, and nothing downstream
noticed: it was flattened, rendered to a surface volume, and run through ink
detection at two resolutions.

`copy_moved_points` does not predict the failure — w046 reports more moved
points than w048 or w049, both of which are fine. The villa docs already warn
that "Copy Out/In is useful as an acceleration tool, not as an unchecked
replacement for validation"
(`scrollprize.org/docs/37_2026_open_problems.md:314`); this is what the missing
check costs.

## 8. What the duplication costs

`w046`'s own meta.json gives `area_cm2 = 36.69`. Multiplying that value by the
81.4975% repeated-cell fraction gives **29.9 cm²**. This is an approximate
impact estimate, not a direct integration of the repeated region's physical
area. The geometric ladder and the model-based ray evidence are consistent
with one untraced wrap of comparable scale; that missing-area interpretation
is an inference, not another measured quantity.

## 9. Figure

`fig_ladder.png` — the geometric ladder, the independent ink ladder, and four
consecutive ink maps.

`fig_gap.png` — deterministic ray-length distributions and length-matched
interior-response rates. The title and axis explicitly identify these as
surface-model evidence.

## 10. Release reproducibility and limits

- `data_manifest.json` pins the duplicate-check assets, the five ray meshes,
  the Zarr schema, seed, thresholds, and expected counts.
- `results/ray_PHerc0139.json` pins all 361 accessed chunk digests (112,892,827
  bytes) as well as the derived result. A second offline run produced an
  identical 143,000-byte JSON file with SHA-256
  `13733677d4901e9c33277e7e8ab2c84aba1e4af4de6a8efd0eefc799fee470ea`.
- `results/corpus_snapshot.json` pins the 2026-08-19 catalog digest and every
  committed corpus-result artifact. The source surfaces for the full 188-item
  sweep are not vendored, so a future run against the mutable bucket is a new
  observation rather than a guaranteed byte reconstruction of that historical
  corpus input.
- Only an explicit Zarr-chunk 404 is treated as fill data. Every other HTTP,
  transport, cache-integrity, and decode failure aborts the run.
- The generic detector uses a documented one-voxel floor on its otherwise
  scroll-relative coincidence radius. The floor was inactive in this corpus
  snapshot (minimum unit 11.64 voxels).
