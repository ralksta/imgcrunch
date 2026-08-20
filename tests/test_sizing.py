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


class TestSearchScale:
    @staticmethod
    def _pixel_probe(fits_at_or_below: int, bytes_per_pixel: float = 1.0):
        """
        Simulated probe: an encode fits once the pixel count drops to
        `fits_at_or_below` or less. `floor` is proportional to pixel count,
        which is the relationship the real scale estimate assumes.
        """
        def probe(w, h):
            pixels = w * h
            floor = int(pixels * bytes_per_pixel)
            if pixels <= fits_at_or_below:
                return b"x" * floor, floor
            return None, floor
        return probe

    def test_returns_immediately_when_full_size_fits(self):
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return b"fits", 4

        result = sizing.search_scale(probe, 1000, 800, 600)
        assert result == b"fits"
        assert calls == [(800, 600)]

    def test_scales_down_until_it_fits(self):
        probe = self._pixel_probe(fits_at_or_below=10_000)
        result = sizing.search_scale(probe, 10_000, 2000, 2000)
        assert result is not None
        assert len(result) <= 10_000

    def test_returns_none_when_nothing_ever_fits(self):
        def probe(w, h):
            return None, 10_000_000

        result = sizing.search_scale(probe, 100, 2000, 2000)
        assert result is None

    def test_terminates_when_dimensions_stagnate(self):
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 10_000_000

        sizing.search_scale(probe, 100, 20, 20, min_edge=16)
        assert len(calls) <= 17  # one full-size probe + at most max_attempts

    def test_grows_back_when_far_under_target(self):
        """Landing at 10% of the budget wastes quality — try one size up."""
        sizes = []

        def probe(w, h):
            sizes.append((w, h))
            if w * h <= 100:
                return b"x" * 100, 100
            return None, 10_000

        sizing.search_scale(probe, 10_000, 1000, 1000)
        fitting = [s for s in sizes if s[0] * s[1] <= 100]
        assert len(sizes) > len(fitting), "should have probed a larger size after the fit"

    def test_never_probes_below_min_edge(self):
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 10_000_000

        sizing.search_scale(probe, 1, 4000, 4000, min_edge=16)
        assert all(w >= 16 and h >= 16 for w, h in calls)
