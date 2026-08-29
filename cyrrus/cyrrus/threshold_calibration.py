"""
Auto-calibrates similarity_threshold for EmbeddingRouter using Otsu's
method, instead of manually sweeping values and eyeballing the result
(what Slides_Embedding_Test.ipynb's threshold sweep does today).

Precise about what's actually unsupervised here: we already know,
from slides.json's structure, which example-phrase pairs belong to
the same slide vs. different slides - that's not learned, it's given.
What IS unsupervised is finding WHERE to draw the similarity-score
line between "these match" and "these don't" - that's derived purely
from the shape of the score distribution, not a human-picked number.

Otsu's method (classically used for image binarization, adapted here
to 1D similarity scores): given a set of scores assumed to form two
natural clusters, find the split point that maximizes the variance
BETWEEN the two resulting groups. No labels are used to compute the
threshold itself - only the distribution's shape. Labels (if you have
them, as we do here) are only used afterward, to check how well the
auto-found threshold lines up with reality.
"""


def otsu_threshold(scores: list) -> float:
    """
    scores: any list of numeric similarity scores, ideally forming a
    roughly bimodal distribution (a cluster of real matches, a cluster
    of non-matches). Returns the split point between the two clusters
    that maximizes between-cluster variance.

    Returns the midpoint of the score range if given fewer than 2
    distinct values (nothing to separate).
    """
    if not scores:
        raise ValueError("otsu_threshold needs at least one score.")

    unique_sorted = sorted(set(scores))
    if len(unique_sorted) < 2:
        return unique_sorted[0]

    all_sorted = sorted(scores)
    n = len(all_sorted)

    best_threshold = unique_sorted[0]
    best_between_class_variance = -1.0

    for i in range(1, len(unique_sorted)):
        t = (unique_sorted[i - 1] + unique_sorted[i]) / 2
        below = [s for s in all_sorted if s <= t]
        above = [s for s in all_sorted if s > t]
        if not below or not above:
            continue

        w_below = len(below) / n
        w_above = len(above) / n
        mean_below = sum(below) / len(below)
        mean_above = sum(above) / len(above)

        between_class_variance = w_below * w_above * (mean_below - mean_above) ** 2
        if between_class_variance > best_between_class_variance:
            best_between_class_variance = between_class_variance
            best_threshold = t

    return best_threshold


def calibrate_from_labeled_pairs(same_slide_scores: list, cross_slide_scores: list) -> dict:
    """
    Convenience wrapper for the actual use case: you have similarity
    scores for same-slide example pairs (expected high) and cross-slide
    pairs (expected low) - typically computed in Colab against a real
    embedding model. Runs Otsu on the COMBINED, unlabeled scores (the
    threshold computation itself never sees which score came from
    which group), then reports how well that threshold actually
    separates the two known groups - so you can judge the result, not
    just trust it.
    """
    combined = same_slide_scores + cross_slide_scores
    threshold = otsu_threshold(combined)

    same_correct = sum(1 for s in same_slide_scores if s >= threshold)
    cross_correct = sum(1 for s in cross_slide_scores if s < threshold)

    return {
        "threshold": threshold,
        "same_slide_correctly_above": same_correct,
        "same_slide_total": len(same_slide_scores),
        "cross_slide_correctly_below": cross_correct,
        "cross_slide_total": len(cross_slide_scores),
        "accuracy": (same_correct + cross_correct) / (len(same_slide_scores) + len(cross_slide_scores))
                    if (same_slide_scores or cross_slide_scores) else None,
    }
