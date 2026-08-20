"""Tests for sizing.py — pure geometry and search logic, no image files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sizing  # noqa: E402


class TestNeedsResize:
    def test_zero_max_size_never_resizes(self):
        assert sizing.needs_resize(9999, 9999, 0) is False

    def test_over_limit_resizes(self):
        assert sizing.needs_resize(3001, 100, 3000) is True

    def test_exactly_at_limit_does_not_resize(self):
        assert sizing.needs_resize(3000, 3000, 3000) is False


class TestCalculateNewSize:
    def test_landscape_scales_by_width(self):
        assert sizing.calculate_new_size(4000, 2000, 2000) == (2000, 1000)

    def test_portrait_scales_by_height(self):
        assert sizing.calculate_new_size(2000, 4000, 2000) == (1000, 2000)

    def test_extreme_aspect_ratio_keeps_short_side_at_least_one(self):
        w, h = sizing.calculate_new_size(100000, 30, 3000)
        assert h >= 1


class TestSearchQuality:
    @staticmethod
    def _linear_encoder(bytes_per_quality: int):
        """Simulated encoder: output size grows linearly with quality."""
        return lambda q: b"x" * (q * bytes_per_quality)

    def test_picks_highest_quality_that_fits(self):
        encode = self._linear_encoder(10)
        result = sizing.search_quality(encode, 505)
        assert result is not None
        quality, data = result
        assert quality == 50
        assert len(data) == 500

    def test_returns_none_when_even_lowest_quality_is_too_big(self):
        encode = self._linear_encoder(10)
        assert sizing.search_quality(encode, 5) is None

    def test_full_quality_when_everything_fits(self):
        encode = self._linear_encoder(10)
        result = sizing.search_quality(encode, 10_000)
        assert result is not None
        assert result[0] == 100

    def test_never_exceeds_seven_encodes(self):
        calls = []

        def encode(q):
            calls.append(q)
            return b"x" * (q * 10)

        sizing.search_quality(encode, 505)
        assert len(calls) <= 7
