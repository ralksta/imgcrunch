"""Truth table for JobSettings.forces_reencode()."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import imgcrunch as ic  # noqa: E402


def _settings(**kwargs):
    base = dict(format_key="jpeg", quality=85, max_size=3000)
    base.update(kwargs)
    return ic.JobSettings(**base)


class TestForcesReencode:
    def test_plain_settings_allow_byte_copy(self):
        assert _settings().forces_reencode() is False

    def test_lossless_forces_reencode(self):
        assert _settings(lossless=True).forces_reencode() is True

    def test_strip_exif_forces_reencode(self):
        assert _settings(strip_exif=True).forces_reencode() is True

    def test_target_bytes_alone_does_not_force_reencode(self):
        """
        Whether a target size forces a re-encode depends on the input file's
        size, which forces_reencode() cannot see (design decision 4: it only
        covers settings-intrinsic reasons). That image-dependent decision is
        made in the worker's byte-copy gate via a separate `target_ok` check,
        not here — see imgcrunch.process_image.
        """
        assert _settings(target_bytes=100_000).forces_reencode() is False

    def test_zero_target_bytes_does_not_force_reencode(self):
        assert _settings(target_bytes=0).forces_reencode() is False


class TestPicklable:
    def test_settings_survive_pickling(self):
        """ProcessPoolExecutor pickles every worker argument."""
        import pickle
        settings = _settings(target_bytes=50_000)
        assert pickle.loads(pickle.dumps(settings)) == settings
