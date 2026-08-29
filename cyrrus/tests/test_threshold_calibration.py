"""
Tests for threshold_calibration.py using synthetic score distributions
- no network, no real embeddings needed. This verifies the ALGORITHM
finds a reasonable split point given known distribution shapes. Real
embedding scores from Colab are a separate, later validation.
"""
import os
import sys

from cyrrus.threshold_calibration import otsu_threshold, calibrate_from_labeled_pairs

FAILED = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


def test_clearly_separated_clusters():
    # two obvious clusters: low ~0.1-0.2, high ~0.8-0.9
    low_cluster = [0.10, 0.12, 0.15, 0.18, 0.20]
    high_cluster = [0.80, 0.83, 0.85, 0.88, 0.90]
    threshold = otsu_threshold(low_cluster + high_cluster)
    check("threshold for clearly separated clusters lands between them",
          0.20 < threshold < 0.80)


def test_matches_manual_gap():
    # a bigger gap should be found precisely - the split should sit
    # somewhere in the empty region between the two clusters
    scores = [0.1, 0.15, 0.2, 0.9, 0.95, 1.0]
    threshold = otsu_threshold(scores)
    check("threshold sits in the actual gap between 0.2 and 0.9",
          0.2 < threshold < 0.9)


def test_single_value():
    check("a single repeated value returns that value, doesn't crash",
          otsu_threshold([0.5, 0.5, 0.5]) == 0.5)


def test_empty_raises():
    raised = False
    try:
        otsu_threshold([])
    except ValueError:
        raised = True
    check("empty input raises a clear error instead of crashing obscurely",
          raised)


def test_two_values():
    threshold = otsu_threshold([0.2, 0.8])
    check("two distinct values split at their midpoint",
          threshold == 0.5)


def test_calibrate_from_labeled_pairs_reports_accuracy():
    same_slide = [0.85, 0.88, 0.90, 0.82]       # should score high
    cross_slide = [0.15, 0.20, 0.18, 0.22]      # should score low
    result = calibrate_from_labeled_pairs(same_slide, cross_slide)

    check("threshold found sits between the two known populations",
          0.22 < result["threshold"] < 0.82)
    check("accuracy is computed and is perfect for this clean synthetic case",
          result["accuracy"] == 1.0)
    check("same-slide count is correctly reported",
          result["same_slide_total"] == 4)


def test_calibrate_handles_overlapping_populations_honestly():
    # a messier, more realistic case with some overlap - the point here
    # isn't perfection, it's that accuracy honestly reflects the mess
    # rather than being silently inflated
    same_slide = [0.85, 0.88, 0.55, 0.90]   # one ambiguous low score
    cross_slide = [0.15, 0.20, 0.60, 0.22]  # one ambiguous high score
    result = calibrate_from_labeled_pairs(same_slide, cross_slide)

    check("accuracy on a messy, overlapping case is reported honestly (not 100%)",
          result["accuracy"] < 1.0)


def main():
    test_clearly_separated_clusters()
    test_matches_manual_gap()
    test_single_value()
    test_empty_raises()
    test_two_values()
    test_calibrate_from_labeled_pairs_reports_accuracy()
    test_calibrate_handles_overlapping_populations_honestly()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    else:
        print("ALL THRESHOLD CALIBRATION TESTS PASSED")
        print("NOTE: verified against synthetic distributions. Real embedding")
        print("score distributions need Colab validation - see the notebook cell.")


if __name__ == "__main__":
    main()
