from __future__ import annotations

import pytest

from canada_funeral_intel.deduplication.review import ReviewQueueError, review_priority


@pytest.mark.parametrize(
    ("score", "expected"),
    [(1.0, 1), (0.90, 100), (0.88, 120), (0.62, 380), (0.0, 1000)],
)
def test_review_priority_is_stable(score: float, expected: int) -> None:
    assert review_priority(score) == expected


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_review_priority_rejects_invalid_score(score: float) -> None:
    with pytest.raises(ReviewQueueError, match="score"):
        review_priority(score)
