"""Re-derive the corpus headline numbers from the committed per-scroll results.

`ladder.py` produces one `results/ladder_<sample>.json` per scroll. Those files are
the evidence; the numbers quoted in the README and in the upstream report are
summaries of them. This script recomputes those summaries from the committed files,
so a reader can check the headline without re-running the scan against a bucket that
has moved on.

It also reports the quantity that decides whether the rule is safe to apply
unattended: the gap between the lowest score called duplicate and the highest score
called distinct, across every pair in the corpus.

    python corpus_summary.py                  # table to stdout
    python corpus_summary.py --csv results/corpus_summary.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os

THRESHOLD = 0.5
"""Coincident fraction above which a pair is called a duplicate (declared, not fitted)."""


def scroll_rows(results_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(results_dir, "ladder_*.json"))):
        doc = json.load(open(path))
        pairs = doc["pairs"]
        scored = [p for p in pairs if p.get("coincident") is not None]
        dup = [p for p in scored if p["coincident"] > THRESHOLD]
        distinct = [p for p in scored if p["coincident"] <= THRESHOLD]
        rows.append(
            {
                "sample": doc["sample"],
                "surfaces": len(doc["names"]),
                "ordered_pairs": len(pairs),
                "unit_vx": round(doc["unit"], 4),
                "coincidence_radius_vx": round(doc["unit"] / 10.0, 4),
                "duplicate_pairs": len(dup),
                "max_distinct_coincident": round(max((p["coincident"] for p in distinct), default=0.0), 6),
                "min_duplicate_coincident": round(min((p["coincident"] for p in dup), default=float("nan")), 6)
                if dup
                else "",
            }
        )
    return rows


def corpus_totals(rows: list[dict], results_dir: str) -> dict:
    scored_dupes = []
    for path in sorted(glob.glob(os.path.join(results_dir, "ladder_*.json"))):
        doc = json.load(open(path))
        for p in doc["pairs"]:
            c = p.get("coincident")
            if c is not None and c > THRESHOLD:
                scored_dupes.append((doc["sample"], c, p["A"], p["B"], p.get("d_med"), p.get("cover")))
    unordered = {}
    for sample, c, a, b, d, cov in scored_dupes:
        unordered[tuple(sorted((a, b)))] = (sample, c, a, b, d, cov)
    highest_distinct = max(r["max_distinct_coincident"] for r in rows)
    lowest_duplicate = min((v[1] for v in unordered.values()), default=None)
    return {
        "surfaces": sum(r["surfaces"] for r in rows),
        "ordered_pairs": sum(r["ordered_pairs"] for r in rows),
        "scrolls": len(rows),
        "duplicate_pairs": len(unordered),
        "duplicates": sorted(unordered.values()),
        "highest_distinct": highest_distinct,
        "lowest_duplicate": lowest_duplicate,
        "separation": (lowest_duplicate / highest_distinct) if lowest_duplicate and highest_distinct else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default="results", help="directory holding ladder_*.json")
    ap.add_argument("--csv", help="also write the per-scroll table here")
    args = ap.parse_args()

    rows = scroll_rows(args.results)
    if not rows:
        print(f"no ladder_*.json under {args.results}")
        return 1
    tot = corpus_totals(rows, args.results)

    w = max(len(r["sample"]) for r in rows)
    print(f"{'sample':{w}}  surfaces  pairs  unit_vx  radius_vx  dup  max_distinct")
    for r in rows:
        print(
            f"{r['sample']:{w}}  {r['surfaces']:8d}  {r['ordered_pairs']:5d}  "
            f"{r['unit_vx']:7.2f}  {r['coincidence_radius_vx']:9.2f}  {r['duplicate_pairs']:3d}  "
            f"{r['max_distinct_coincident']:12.4f}"
        )
    print()
    print(f"{tot['scrolls']} scrolls, {tot['surfaces']} surfaces, {tot['ordered_pairs']} ordered pairs")
    print(f"duplicate pairs: {tot['duplicate_pairs']}")
    for sample, c, a, b, d, cov in tot["duplicates"]:
        print(f"  {sample}  coincident={c:.4f}  d_med={d:.2f}vx  cover={cov:.3f}")
        print(f"    {a}\n    {b}")
    if tot["separation"]:
        print()
        print(f"highest coincident called distinct : {tot['highest_distinct']:.4f}")
        print(f"lowest coincident called duplicate : {tot['lowest_duplicate']:.4f}")
        print(f"separation                         : {tot['separation']:.1f}x")
        print(f"the {THRESHOLD} threshold has no pair within it on either side")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
