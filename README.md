# ladder — find traced surfaces that occupy the same papyrus

`ladder` reads a scroll's published `tifxyz` surfaces and reports pairs that are
not two wraps of the sheet but one wrap published twice.

Overlap between segments is normal and common: on PHerc0139, villa's own
`vc_seg_add_overlap` finds **180 overlapping pairs** among 37 surfaces. What no
tool measured is *how close* an overlap is. Two genuinely distinct wraps are
separated by roughly one sheet spacing; the same sheet published twice is
separated by nothing. `ladder` measures the separation for every pair, and
calibrates the threshold from the scroll itself rather than from a constant.

Geometry only. No volume, no model, no GPU, no credentials. A 37-surface scroll
takes under a minute on a laptop, including the download.

## The measure

For each ordered pair (A, B), every valid vertex of A is matched to its nearest
valid vertex of B.

The unit is derived per scroll: for each surface, take the distance to its
*closest companion surface* — normally the neighbouring wrap — and take the
median of those over all surfaces. That is the scroll's own sheet spacing, and
no constant in voxels appears anywhere.

A pair is a **duplicate** when more than half of one surface's vertices lie
within a tenth of that unit of the other: *over half of this sheet is sitting
on top of that one, a tenth of a sheet spacing away.* On the published corpus
this separates cleanly — the one duplicate scores 0.818 and the next-highest
pair anywhere scores 0.127. The median-distance ratio is reported alongside as
a diagnostic, but it is diluted by whatever part of the two surfaces does not
coincide, so it discriminates less sharply.

Two shortcuts are deliberately not taken. Trees are built on the **full** vertex
set and only the query side is subsampled — subsampling the tree side inflates
every distance and would bias the verdict. And trees are built one at a time, so
memory stays bounded on a scroll-scale corpus.

When segment names carry winding numbers (`…-w045_…`), `ladder` also prints the
winding ladder: the separation between consecutive windings, which should be one
unit throughout.

## Use

```bash
python3 ladder.py scan --sample PHerc0139
python3 ladder.py scan --dir /path/to/dir/of/tifxyz/dirs
python3 ladder.py scan --sample PHerc0139 --json pairs.json --collection dup.json
```

`--sample` pulls the catalog and the surfaces from the public open-data bucket
anonymously. `--collection` writes the coincident sites as a VC3D point
collection (`PointCollections` JSON version "1") so they load in VC3D like any
other point collection.

Requires numpy, scipy, and tifffile or Pillow. If the process dies while
loading a TIFF, set `LADDER_TIFF_READER=pil` — some `imagecodecs` builds
segfault on these LZW float32 files, and a segfault cannot be caught.

`check_duplicate.py` re-derives the PHerc0139 finding on its own, from the
bucket, in about a minute. `raytest.py` is the surface-prediction ray test
behind `fig_gap.png`.

## What it found

Run over every published surface in the open-data bucket — 188 `tifxyz`
surfaces across 11 scrolls, 5142 ordered pairs — `ladder` reports exactly one
duplicate (coincident fraction 0.818; the highest anywhere else in the corpus
is 0.127, two rolling debug snapshots of one growth run on PHerc0500P2):

**PHerc0139 `20260325000000-w046_20260325` is `20260126000000-w045_2026012619`.**

- identical valid-cell count (109,823) and identical valid-cell mask after a
  4-cell pad on each side;
- **81.4975 %** of its vertices (89,503 of 109,823) are bit-identical in all
  three float32 channels — and across all 666 unordered pairs of this scroll's
  37 surfaces, this is the *only* pair that shares even one;
- the remaining 18.5 % form one contiguous block that moved by a median of
  13.7 voxels;
- `w046`'s `meta.json` records `vc_gsfs_mode: gen_neighbor`, `neighbor_dir: out`,
  `max_gen: 2` — a Copy-Out that settled only its edge;
- the published ink detections agree: w045 and w046 correlate at **r = 0.810**
  over 10.3 M pixels, against |r| ≤ 0.234 for all 35 other consecutive winding
  pairs of this scroll;
- and winding 46 is missing from the published set — the bucket holds 38
  PHerc0139 segments, w023–w059 once each plus a title strip, and no other
  candidate: `w046 → w047` separates by **2.15 units** where every other
  consecutive pair separates by 0.63–1.36, and it matches the measured
  *two*-sheet distance (32.5 vx against 31.3 vx for w047→w049);
- the papyrus is physically there: sampling the published surface prediction
  along 400 rays across that gap, **98.8 %** cross a distinct untraced sheet,
  against 7.1 % for a genuine one-sheet step at the same ray length
  (`fig_gap.png`).

`vc_tifxyz_selfcross` cannot see this: it reports both surfaces
identically (165/176 and 178/173 transverse contacts), because each is a
perfectly ordinary surface on its own. The defect exists only between them.

See `EVIDENCE.md` for every command and its output, `NEGATIVE_RESULTS.md` for
the five lines that did not work, and `results/` for the pair tables of all ten
scrolls plus the VC3D point collection of the coincident sites.

## Layout

```
ladder.py             the check
check_duplicate.py    re-derives the PHerc0139 finding from the bucket, ~1 min
raytest.py            the surface-prediction ray test behind fig_gap.png
README.md             what it does and what it found
EVIDENCE.md           every command and its verbatim output
NEGATIVE_RESULTS.md   five hypotheses that died, and the measurement that killed each
results/              pair tables for all ten scrolls, and the duplicate sites
```

MIT licensed.
