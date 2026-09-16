"""Shared test setup. The repo root is on sys.path via pytest's `pythonpath`."""

import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """
    Every run remembers its settings in ~/.config/imgcrunch. Point that at a
    temp dir so the suite never reads or overwrites the real one - including
    from the CLI subprocesses, which inherit this environment.
    """
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return xdg
