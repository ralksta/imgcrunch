"""
Tests for presets.py: built-in presets and the remembered last run.

Pure module - no Pillow, no encoding - so these run in milliseconds.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import presets  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg"


class TestConfigPath:
    def test_follows_xdg_config_home(self, isolated_config):
        assert presets.config_path() == isolated_config / "imgcrunch" / "config.toml"

    def test_defaults_to_dot_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_CONFIG_HOME")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert presets.config_path() == tmp_path / ".config" / "imgcrunch" / "config.toml"


class TestLastRunRoundTrip:
    def test_saved_run_comes_back(self):
        settings = {"format": "avif", "quality": 55, "max_size": 2400,
                    "target_size": "800k", "strip": True, "lossless": False}

        presets.save_last_run(settings)

        assert presets.load_last_run() == settings

    def test_no_target_size_survives_the_round_trip(self):
        # TOML has no null, so "no budget" must not turn into something else.
        settings = {"format": "jpeg", "quality": 85, "max_size": 3000,
                    "target_size": None, "strip": False, "lossless": False}

        presets.save_last_run(settings)

        assert presets.load_last_run()["target_size"] is None

    def test_only_encoding_settings_are_stored(self):
        presets.save_last_run({"format": "jpeg", "quality": 85, "max_size": 3000,
                               "target_size": None, "strip": False, "lossless": False,
                               "replace": True, "rename": "trip"})

        loaded = presets.load_last_run()
        assert "replace" not in loaded, "a preset must never carry a destructive mode"
        assert "rename" not in loaded


class TestLoadIsForgiving:
    def test_missing_file_is_none(self):
        assert presets.load_last_run() is None

    def test_garbage_file_is_none(self):
        path = presets.config_path()
        path.parent.mkdir(parents=True)
        path.write_text("this is { not toml")

        assert presets.load_last_run() is None

    def test_unknown_format_is_rejected(self):
        path = presets.config_path()
        path.parent.mkdir(parents=True)
        path.write_text('[last]\nformat = "gif"\nquality = 80\nmax_size = 0\n'
                        'strip = false\nlossless = false\n')

        assert presets.load_last_run() is None

    def test_wrong_types_are_rejected(self):
        path = presets.config_path()
        path.parent.mkdir(parents=True)
        path.write_text('[last]\nformat = "jpeg"\nquality = "high"\nmax_size = 0\n'
                        'strip = false\nlossless = false\n')

        assert presets.load_last_run() is None


class TestBuiltins:
    def test_every_builtin_is_valid(self):
        for name, settings in presets.BUILTIN_PRESETS.items():
            assert presets.validate(settings) is not None, name

    def test_describe_is_one_readable_line(self):
        line = presets.describe({"format": "jpeg", "quality": 85, "max_size": 2000,
                                 "target_size": "500k", "strip": True, "lossless": False})

        assert "\n" not in line
        assert "JPEG" in line and "2000" in line and "500k" in line
