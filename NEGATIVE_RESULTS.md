# Lines that did not work

Five hypotheses that looked good enough to test and died. Each is recorded with
the measurement that killed it, because each is a plausible thing for the next
person to try.

## 1. Reading mesh-vs-sheet offset out of the published surface volumes

**Idea.** The 611 published `layers-zarr` surface volumes are stacks of slices
sampled at signed offsets along the mesh normal, mesh at the centre slice. For
each column of such a stack the 1-D intensity profile should say where the
papyrus actually is, so the offset of the profile's peak from the centre
measures how far the mesh sits off the sheet — over the whole corpus, from
published data.

**What made it look feasible, and still is.** The multiscale pyramid downsamples
only y and x and never z. In code: `downsampleTileIntoPreserveZ`
(`volume-cartographer/core/src/Zarr.cpp:212`) iterates z as a straight copy and
averages 2×2 in y/x only. In the data: I read the `.zattrs` and every level's
`.zarray` for a random 70 of the 611 published surface volumes — all 70 have six
levels and `slice_step` 1.0, in all 70 the z extent is identical at every level
and equal to `num_slices`, and in all 70 each level halves y and x exactly. So
level 5 is 1/1024 of the bytes with the normal axis untouched, which puts the
whole corpus within a laptop's reach along that axis.

The estimator survived its own consistency check too: the offset map for one
PHerc0139 winding computed at level 5 and at level 3 gives median 0.00 both
ways, r = 0.81 between them, 77 % of pixels within 2 voxels, 26 s for a whole
segment.

**Why it fails anyway.**

- **The sign is unrecoverable.** `--flip-normals` decides which way the stack
  grows: it is parsed into `g_flipNormals` (`vc_render_tifxyz.cpp:1300`),
  applied as `dirs *= -1.0f` (`:287`), logged to stdout (`:1469`) — and never
  written into the Zarr attributes. The tutorial's published-render command
  passes it; VC3D's own render path does not. Two conventions exist in the
  corpus and the artefact cannot distinguish them.
- **The mesh often does not lie on a slice.** The centre is
  `(num_slices-1)/2`, so an even depth puts it half way between two slices. Of
  the 70 volumes I sampled, depths are 116 (17), 109 (16), 28 (10), 33 (9),
  6 (8), 118 (6), 61 (2), 31 (1), 231 (1) — **41 of 70 are even**, and for
  those every "offset from centre" carries a built-in half-voxel floor.
- **Zero is overloaded five ways** — invalid mesh cell, out-of-volume sample,
  masked-out CT, padded tile edge, skipped all-fill chunk — and the render
  carries no validity channel. The renderer writes a full zero column where the
  mesh is invalid rather than skipping it, and the canvas is the full
  rectangular hull of the grid unless cropped. `argmax` of an all-zero column
  returns index 0, which lands at the extreme negative end of the range. The
  result is a convincing bimodal histogram whose second mode is bookkeeping.
  I saw exactly this in my own profiles before I understood the cause.
- **The target is wrong, and the measurement already exists.** `vc_objrefine`
  (`apps/src/ObjAlphaCompRefinement.cpp`) computes a per-vertex mesh-to-sheet
  offset along the normal and moves the vertex by it. Its `RefinementConfig`
  defaults are `start = -2.0f, stop = 30.0f, step = 2.0f, low = 118/255,
  high = 165/255, border_off = 1.0f` — an opacity-weighted expected depth over
  an asymmetric forward search. The pipeline's convention is that the mesh belongs
  at the sheet's *leading face*, not at its intensity peak. A correct peak
  measurement would therefore report a systematic offset that is correct
  behaviour.
- **Mean and argmax do not commute.** A level-5 column is the mean of 1024
  level-0 profiles; the argmax of that mixture is its mode, which is not the
  mean of the constituent offsets, and is worst exactly where the offset
  distribution is skewed — i.e. near an error.

**Status: abandoned.** The pyramid fact (only y/x are downsampled) is real and
still useful to anyone who wants cheap access to the normal direction; the
inference built on it is not.

## 2. Cross-segment agreement of ink predictions

**Idea.** Where two independently traced segments cover the same papyrus, their
ink predictions must agree. Disagreement localises an unwrapping error, with no
ground truth needed.

**What killed it.** The segments barely overlap. Screening all 5142 ordered pairs
(the 187 published surfaces that have a sibling in the same scroll), at 5 voxels only 91 pairs have even 1 % of
one surface near the other, 11 pairs exceed 10 %, and none exceeds 50 %. On
PHercParis4 — the scroll with the most published surface — no pair exceeds 10 %.
There is not enough doubly-covered papyrus with independent predictions to build
a measurement on.

## 3. Mining the spiral dataset's "verified" patches for human labels

**Idea.** The `spiral-input` dataset for PHercParis4 publishes tens of thousands
of manually verified surface patches. If the human verdict is recorded per
patch, it is a labelled set for learning what makes a patch acceptable, which is
the check the spiral fit currently depends on a person to make.

**What killed it.** It is not per-patch. I fetched the `meta.json` of 86,120 of
the 89,237 published `verified_patches`: 31,019 carry no `tags` key at all, 206
carry an empty `reviewed`, and only 3,624 carry a `reviewed` date — and those
arrive in bulk bursts (1,909 in a single second, 1,250 in the next). "Verified"
is a property of the directory, not a decision recorded against each patch.

## 4. Sheet spacing from the surface volume's own profile

**Idea.** If the normal-offset profile is periodic, its autocorrelation gives
the local inter-sheet spacing directly from the image — an independent
measurement to compare against the trace's own wrap-to-wrap distance.

**What killed it.** No periodicity. The mean profile autocorrelation over
16,384 columns decays monotonically with no secondary peak, on PHerc0139 at
2.399 µm and 9.362 µm and on PHerc1667 at 2.399 µm. 109 slices at 2.399 µm span
261 µm, which does not reliably reach the neighbouring sheet.

## 5. A radial ladder instead of a nearest-neighbour ladder

**Idea.** Cheaper than nearest neighbours: estimate the umbilicus, take each
winding's median radius, and look for a step of two units where a wrap is
missing.

**What killed it.** No discriminative power. Segments cover different angular
and z extents, so their median radii are not comparable: on PHerc0139 the naive
radial step flags ten pairs as anomalous, including w050 with a step of −96
voxels caused purely by that surface covering a different region. The genuine
defect does show up (w045→w046 steps by 2.0 voxels against a median of 18.4),
but it is indistinguishable from the nine false alarms. This is exactly why the
shipped check restricts the comparison to the region where two surfaces share
support.
