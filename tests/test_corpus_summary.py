import json
from pathlib import Path

import pytest

from corpus_summary import THRESHOLD, corpus_totals, scroll_rows

RESULTS = Path(__file__).resolve().parent.parent / "results"


def _write(tmp_path, sample, names, pairs, unit=10.0):
    (tmp_path / f"ladder_{sample}.json").write_text(
        json.dumps({"sample": sample, "names": names, "unit": unit, "pairs": pairs})
    )


def test_a_pair_over_the_threshold_is_a_duplicate_and_one_under_is_not(tmp_path):
    _write(
        tmp_path,
        "S",
        ["a", "b", "c"],
        [
            {"A": "a", "B": "b", "coincident": 0.9, "d_med": 0.0, "cover": 1.0},
            {"A": "b", "B": "a", "coincident": 0.9, "d_med": 0.0, "cover": 1.0},
            {"A": "a", "B": "c", "coincident": 0.4, "d_med": 3.0, "cover": 1.0},
        ],
    )
    rows = scroll_rows(str(tmp_path))
    assert rows[0]["duplicate_pairs"] == 2
    assert rows[0]["max_distinct_coincident"] == pytest.approx(0.4)


def test_the_two_orderings_of_one_pair_count_as_one_duplicate(tmp_path):
    _write(
        tmp_path,
        "S",
        ["a", "b"],
        [
            {"A": "a", "B": "b", "coincident": 0.9, "d_med": 0.0, "cover": 1.0},
            {"A": "b", "B": "a", "coincident": 0.9, "d_med": 0.0, "cover": 1.0},
        ],
    )
    tot = corpus_totals(scroll_rows(str(tmp_path)), str(tmp_path))
    assert tot["duplicate_pairs"] == 1


def test_a_pair_with_no_measurable_overlap_is_skipped_not_counted_distinct(tmp_path):
    _write(
        tmp_path,
        "S",
        ["a", "b"],
        [{"A": "a", "B": "b", "coincident": None, "d_med": None, "cover": 0.0}],
    )
    rows = scroll_rows(str(tmp_path))
    assert rows[0]["duplicate_pairs"] == 0
    assert rows[0]["max_distinct_coincident"] == 0.0


@pytest.mark.skipif(not RESULTS.exists(), reason="committed results not present")
def test_the_committed_results_reproduce_the_numbers_the_readme_quotes():
    rows = scroll_rows(str(RESULTS))
    tot = corpus_totals(rows, str(RESULTS))
    assert tot["ordered_pairs"] == 5142
    assert tot["surfaces"] == 187
    assert tot["duplicate_pairs"] == 1
    assert tot["duplicates"][0][0] == "PHerc0139"
    assert tot["highest_distinct"] == pytest.approx(0.127, abs=0.001)
    # The rule is declared, not fitted; this is the margin it happens to have.
    assert tot["lowest_duplicate"] > THRESHOLD
    assert tot["separation"] > 6.0
