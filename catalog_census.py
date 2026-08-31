"""Count what the public catalog holds, and what this tool can actually scan.

    python3 catalog_census.py                 # fetches the catalog anonymously
    python3 catalog_census.py metadata.json   # uses a local copy

The three numbers in the README come from here, and they are easy to confuse:

  catalog segments      every segment the catalog lists, across every scroll
  with tifxyz           those publishing a tifxyz surface — the only thing
                        ladder reads, so this is the scan's population
  pairable              those in a scroll holding at least one other tifxyz.
                        A surface alone in its scroll contributes no pair, so
                        the ordered-pair count comes from this number, not the
                        one above.

Reporting the first as if it were the second, or the second as if it were the
third, is the mistake this script exists to make impossible.
"""

from __future__ import annotations

import json
import sys
import urllib.request

CATALOG = "https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json"


def load(argv: list[str]) -> dict:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as fh:
            return json.load(fh)
    req = urllib.request.Request(CATALOG, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip

            raw = gzip.decompress(raw)
    return json.loads(raw)


def main(argv: list[str]) -> int:
    cat = load(argv)
    rows = []
    for name, sample in cat.get("samples", {}).items():
        segments = sample.get("segments") or {}
        if not segments:
            continue
        with_tifxyz = sum(
            1
            for _, seg in segments.items()
            if any(item.get("type") == "tifxyz" for item in (seg.get("data") or []))
        )
        rows.append((name, len(segments), with_tifxyz))

    rows.sort(key=lambda r: -r[1])
    print(f"{'scroll':16s} {'segments':>9} {'with tifxyz':>12}  scanned")
    print("-" * 52)
    for name, n, t in rows:
        note = "yes" if t >= 2 else f"no, needs 2"
        print(f"{name:16s} {n:9d} {t:12d}  {note}")
    print("-" * 52)

    segments = sum(n for _, n, _ in rows)
    tifxyz = sum(t for _, _, t in rows)
    pairable = sum(t for _, _, t in rows if t >= 2)
    pairs = sum(t * (t - 1) for _, _, t in rows if t >= 2)

    print(f"{'catalog segments':28s} {segments:6d}   over {len(rows)} scrolls")
    print(f"{'with a tifxyz surface':28s} {tifxyz:6d}   the scan population")
    print(f"{'pairable':28s} {pairable:6d}   in a scroll with another tifxyz")
    print(f"{'ordered pairs':28s} {pairs:6d}   sum of n(n-1) over scanned scrolls")

    unpaired = [(n, t) for n, _, t in rows if t == 1]
    for name, _ in unpaired:
        print(f"\nunpaired: {name} publishes one tifxyz and cannot form a pair")
    empty = [n for n, _, t in rows if t == 0]
    for name in empty:
        print(f"absent:   {name} publishes no tifxyz at all")

    print(
        "\nThe catalog is mutable. These are today's numbers; the committed "
        "snapshot pins the digest of the one the published scan used."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
