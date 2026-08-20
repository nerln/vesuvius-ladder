# ladder — detect duplicate traced surfaces

`ladder` is a geometry QA check for Vesuvius Challenge `tifxyz` surfaces. It
distinguishes ordinary overlap between neighbouring segments from the more
specific failure in which one papyrus wrap has effectively been published
twice.

The detector itself reads geometry only: no volume, learned model, GPU, or
credentials. The separate `raytest.py` experiment uses a named published
surface-prediction volume as supporting evidence for the PHerc0139 finding.

## Result

In the catalog snapshot dated 2026-08-19, the corpus scan covered 188 surfaces
and 5,142 ordered pairs. Under the declared heuristic, it classified one pair
as duplicate:

`PHerc0139/20260325000000-w046_20260325` is substantially the same traced
surface as `20260126000000-w045_2026012619`.

The directly reproducible observations are:

- 89,503 of 109,823 valid vertices (81.4975%) are bit-identical in all three
  float32 coordinate channels;
- after a four-cell alignment, the valid-cell masks are identical;
- the changed 20,320 vertices form one connected region and have median
  displacement 13.724 voxels;
- the aligned published ink maps correlate at `r = 0.810`, whereas the two
  adjacent controls are `+0.008` and `-0.051`;
- the geometric coincident fraction is 0.818. The largest non-duplicate score
  in that corpus snapshot is 0.127;
- multiplying the 81.4975% repeated-cell fraction by `w046`'s reported
  `area_cm2 = 36.69` gives an approximate repeated area of 29.9 cm². This is an
  estimate, not a direct area integration.

The ray experiment adds model-based evidence: among rays with lengths of
40–55 voxels, 85/86 (98.84%) across `w046→w047` contain a distinct interior
high-response island. The one-sheet control is 2/28 (7.14%); two-sheet controls
are 94/95 (98.95%) and 102/102 (100%). This means the named surface-prediction
model behaves as if an intervening surface is present. It is not direct
observation and is not physical ground truth. The released analysis's 40–55
voxel subset was not preregistered.

## How the detector works

For every ordered pair `(A, B)`, each queried vertex of A is matched to its
nearest vertex on the full vertex set of B. Only the query side may be
subsampled; subsampling the tree side would inflate distances.

For each surface, the smallest median distance to a companion surface is
computed. The median of those per-surface minima is the scroll-specific unit,
normally about one sheet spacing. A pair is classified as duplicate when more
than half of either surface lies within `0.1 × unit` of the other.

There is one explicit absolute safeguard: the coincidence radius is
`max(1 voxel, 0.1 × unit)`. The one-voxel numerical floor was omitted from the
original prose. It is inactive for the published corpus snapshot because the
smallest inferred unit is 11.64 voxels, but it can affect unusually small-scale
inputs.

This is a QA heuristic, not a general proof of physical sheet identity. A
different corpus can violate its assumptions—for example, if the closest
published companion is not a neighbouring wrap or coordinates are expressed
in incompatible frames.

## Install

Python 3.10 or later is supported by the package metadata. For an isolated
environment using compatible dependency ranges:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
```

`requirements.txt` records the exact Python 3.14 environment used for the
2026-08-20 release verification. No installation step is performed by the
repository itself.

Some `imagecodecs` builds crash while decoding these LZW float32 TIFFs. If
that occurs, use Pillow explicitly:

```bash
export LADDER_TIFF_READER=pil
```

## Reproduce from a clean checkout

The compact duplicate check downloads 8.03 MB of manifest-pinned meshes and
ink maps, verifies every size and SHA-256 digest, and recomputes the headline
result:

```bash
.venv/bin/python check_duplicate.py ./check_data
```

The end-to-end ray command downloads and validates five meshes plus the exact
Zarr chunks it uses (112,892,827 chunk bytes in the release run), recomputes
the statistics, writes JSON, and renders the figure:

```bash
.venv/bin/python raytest.py \
  --work ./ray_data \
  --output ./results/ray_PHerc0139.reproduced.json \
  --figure ./fig_gap.reproduced.png
```

The command checks the live `.zarray` metadata against `data_manifest.json`,
checks accessed chunk bytes against `results/ray_PHerc0139.json`, and checks
the derived counts/rates against the manifest. An explicit chunk 404 means the
declared Zarr fill value; timeouts, authentication failures, rate limits, 5xx
responses, corrupt cache entries, and decode errors are fatal.

After a successful online run, both commands can be repeated without network
access:

```bash
.venv/bin/python check_duplicate.py ./check_data --offline
.venv/bin/python raytest.py --work ./ray_data --offline --no-figure \
  --output /tmp/ray_PHerc0139.offline.json
```

Run the generic scanner on live public data or local surfaces with:

```bash
.venv/bin/python ladder.py scan --sample PHerc0139
.venv/bin/python ladder.py scan --dir /path/to/tifxyz/directories
.venv/bin/python ladder.py scan --sample PHerc0139 \
  --json pairs.json --collection duplicate_sites.json
```

Online catalog scans refresh `metadata.json` atomically. `--offline` requires
the catalog and surface cache from a prior run. Download failures are fatal so
an incomplete corpus cannot silently produce a clean report.

## Immutable release records

`data_manifest.json` pins the assets, Zarr schema, deterministic seed (`1`),
and expected ray statistics. `results/ray_PHerc0139.json` pins the 361 accessed
chunk digests and derived result. `results/corpus_snapshot.json` pins the
catalog digest and every committed corpus-result artifact.

The historical whole-corpus output can therefore be checked for repository
drift, but its 188 source surfaces are not vendored. Re-running it later
against the mutable public bucket is a new corpus observation, not a guaranteed
byte-for-byte reconstruction of the 2026-08-19 input snapshot. The core
PHerc0139 duplicate and ray experiments are the clean-checkout, asset-pinned
reproductions.

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q ladder.py ladder_io.py \
  check_duplicate.py raytest.py
```

CI runs the synthetic suite on Ubuntu and macOS with Python 3.11 and 3.13. It
does not download the research dataset.

See `EVIDENCE.md` for the measurements and `NEGATIVE_RESULTS.md` for rejected
approaches. This repository establishes a concrete data defect and a reusable
QA method; it does not claim eligibility for, or predict, a particular prize
tier. Prize value depends on the program rules and on whether the check is
integrated into the production validation workflow.

## Agentic-use disclosure

OpenAI Codex was used agentically to investigate, implement, test, audit, and
document this repository. The reported checks were executed in the repository
environment, and the public manifests and machine-readable outputs are provided
so the conclusions can be independently audited. Responsibility for the release
and submission remains with Eugenio Nerelli.

MIT licensed.
