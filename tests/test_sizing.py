"""Tests for sizing.py — pure geometry and search logic, no image files."""

import math
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
        calls = []
        inner = self._pixel_probe(fits_at_or_below=10_000)

        def probe(w, h):
            calls.append((w, h))
            return inner(w, h)

        result = sizing.search_scale(probe, 10_000, 2000, 2000)

        assert result is not None
        assert len(result) <= 10_000
        # the 4,000,000-pixel source cannot fit a 10,000-byte budget, so
        # scaling down must actually have happened
        assert any(w * h < 2000 * 2000 for w, h in calls)
        # the returned bytes must be exactly what the probe reported for the
        # pixel size that produced them (bytes_per_pixel=1.0 means
        # length == pixel count) — not merely "some length <= target"
        assert any(w * h == len(result) for w, h in calls)

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
        # The upper bound (range(max_attempts) with one probe each) holds
        # structurally no matter what the loop body does, so it alone does
        # not pin the stagnation guard: what the guard actually buys us is
        # that a repeated (w, h) is never re-probed.
        assert len(set(calls)) == len(calls)
        assert len(calls) <= 17  # one full-size probe + at most max_attempts

    def test_grows_back_when_far_under_target(self):
        """
        Landing at 10% of the budget wastes quality — try one size up.

        Concrete numbers below were traced against the real implementation:
        source 1000x1000, target 1000 bytes, floor = pixels * 0.001, fit
        once pixels <= 800_000. The full-size probe misses, the first
        shrink lands on (857, 857) fitting at 734 bytes (well under 85% of
        the 1000-byte target), which triggers one grow-back attempt; that
        overshoots to (985, 985) (no fit), shrinks to (936, 936) (no fit),
        and lands on (889, 889), fitting at 790 bytes — larger than the
        first fit and still under target. Verified by temporarily deleting
        the grow-back block: without it, only (857, 857) is ever probed and
        the result is 734 bytes, so this test fails as intended (see the
        task-3-report.md fix report for the removal-experiment output).
        """
        calls = []

        def probe(w, h):
            calls.append((w, h))
            pixels = w * h
            floor = int(pixels * 0.001)
            if pixels <= 800_000:
                return b"x" * floor, floor
            return None, floor

        result = sizing.search_scale(probe, 1000, 1000, 1000)

        fitting = [(w, h) for w, h in calls if w * h <= 800_000]
        assert len(fitting) >= 2, "grow-back should have re-probed after the first fit"
        first_fit = fitting[0]
        larger_fits = [wh for wh in fitting[1:] if wh[0] * wh[1] > first_fit[0] * first_fit[1]]
        assert larger_fits, "should have probed a larger fitting size after the first fit"

        largest = max(larger_fits, key=lambda wh: wh[0] * wh[1])
        expected = b"x" * int(largest[0] * largest[1] * 0.001)
        assert result == expected, "result should be the bytes from the larger, grown-back size"

    def test_never_probes_below_min_edge(self):
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 10_000_000

        sizing.search_scale(probe, 1, 4000, 4000, min_edge=16)
        assert all(w >= 16 and h >= 16 for w, h in calls)

    def test_shrink_factor_is_clamped_even_when_probe_violates_contract(self):
        """
        The probe contract says floor_at > target_bytes whenever fit is
        None, which is what keeps the shrink factor below 1. A probe that
        violates the contract (here: always reporting a tiny floor far
        below the target) must not be able to grow the scale — and by
        extension the probed dimensions — without bound.
        """
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 1  # floor is absurdly small relative to target

        sizing.search_scale(probe, 10_000_000, 800, 600)
        assert all(w <= 800 and h <= 600 for w, h in calls)

    def test_preserves_aspect_ratio_when_min_edge_applies(self):
        """
        Clamping each edge to min_edge independently (as the original brief
        code did) can squash a wide image's short edge relative to its long
        edge. The shared floor_scale must keep both edges scaled by the
        same factor.
        """
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 10_000_000

        sizing.search_scale(probe, 1, 4000, 100, min_edge=16)

        ratio = 4000 / 100
        for w, h in calls:
            assert math.isclose(w / h, ratio, rel_tol=0.1)

    def test_never_upscales_past_source_smaller_than_min_edge(self):
        """A source smaller than min_edge must not be stretched up to it."""
        calls = []

        def probe(w, h):
            calls.append((w, h))
            return None, 10_000_000

        sizing.search_scale(probe, 1, 10, 10, min_edge=16)
        assert all(w <= 10 and h <= 10 for w, h in calls)
