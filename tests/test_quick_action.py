"""
The macOS Quick Action path: install_macos_quick_action.sh, the launcher it
writes, and resize.sh.

Nothing here touches ~/Library: the installer takes its target directories
from the environment, and `osascript` is replaced by a stub that records
what it was asked to run instead of opening Terminal.
"""

import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def _executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def dirs(tmp_path):
    d = {name: tmp_path / name for name in ("services", "support", "bin", "calls")}
    for p in d.values():
        p.mkdir()
    return d


def _install(dirs, path_env):
    env = {
        "HOME": str(dirs["support"].parent),
        "PATH": path_env,
        "IMGCRUNCH_SERVICES_DIR": str(dirs["services"]),
        "IMGCRUNCH_SUPPORT_DIR": str(dirs["support"]),
        "IMGCRUNCH_SKIP_REFRESH": "1",
    }
    return subprocess.run(["bash", str(REPO_ROOT / "install_macos_quick_action.sh")],
                          env=env, capture_output=True, text=True, timeout=60)


def _command_string(dirs) -> str:
    wflow = dirs["services"] / "ImgCrunch.workflow" / "Contents" / "document.wflow"
    with open(wflow, "rb") as f:
        doc = plistlib.load(f)
    return doc["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]


class TestResizeSh:
    def test_missing_venv_explains_the_setup(self, tmp_path):
        clone = tmp_path / "clone"
        clone.mkdir()
        shutil.copy(REPO_ROOT / "resize.sh", clone / "resize.sh")

        r = subprocess.run(["bash", str(clone / "resize.sh"), "--version"],
                           capture_output=True, text=True, timeout=30)

        assert r.returncode != 0
        out = r.stdout + r.stderr
        assert "python3 -m venv venv" in out
        assert "No such file" not in out, "a bare shell error is not an explanation"


class TestInstaller:
    def test_prefers_an_installed_imgcrunch(self, dirs):
        fake = _executable(dirs["bin"] / "imgcrunch", "exit 0\n")

        r = _install(dirs, f"{dirs['bin']}:/usr/bin:/bin")

        assert r.returncode == 0, r.stdout + r.stderr
        launcher = dirs["support"] / "launch.sh"
        assert os.access(launcher, os.X_OK)
        assert str(fake) in launcher.read_text()
        assert "resize.sh" not in launcher.read_text()

    def test_falls_back_to_the_clone(self, dirs):
        r = _install(dirs, "/usr/bin:/bin")

        assert r.returncode == 0, r.stdout + r.stderr
        assert str(REPO_ROOT / "resize.sh") in (dirs["support"] / "launch.sh").read_text()

    def test_workflow_calls_the_launcher_not_a_clone_path(self, dirs):
        _executable(dirs["bin"] / "imgcrunch", "exit 0\n")
        _install(dirs, f"{dirs['bin']}:/usr/bin:/bin")

        command = _command_string(dirs)

        assert str(dirs["support"] / "launch.sh") in command
        assert str(REPO_ROOT) not in command, "moving the repo must not break the action"

    def test_bundle_plists_are_valid(self, dirs):
        _install(dirs, "/usr/bin:/bin")
        contents = dirs["services"] / "ImgCrunch.workflow" / "Contents"

        for name in ("Info.plist", "document.wflow"):
            r = subprocess.run(["plutil", "-lint", str(contents / name)],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stdout


class TestLauncher:
    def test_missing_target_says_how_to_fix_it(self, dirs):
        fake = _executable(dirs["bin"] / "imgcrunch", "exit 0\n")
        _install(dirs, f"{dirs['bin']}:/usr/bin:/bin")
        fake.unlink()

        r = subprocess.run([str(dirs["support"] / "launch.sh"), "--wizard"],
                           capture_output=True, text=True, timeout=30)

        assert r.returncode != 0
        assert "install_macos_quick_action.sh" in r.stdout + r.stderr

    def test_passes_its_arguments_through(self, dirs):
        record = dirs["calls"] / "argv"
        _executable(dirs["bin"] / "imgcrunch", f'printf "%s\\n" "$@" > "{record}"\n')
        _install(dirs, f"{dirs['bin']}:/usr/bin:/bin")

        subprocess.run([str(dirs["support"] / "launch.sh"), "--wizard", "--args-file", "x y"],
                       check=True, timeout=30)

        assert record.read_text().splitlines() == ["--wizard", "--args-file", "x y"]


class TestWorkflowCommand:
    def test_selection_reaches_terminal_through_the_launcher(self, dirs, tmp_path):
        _executable(dirs["bin"] / "imgcrunch", "exit 0\n")
        _install(dirs, f"{dirs['bin']}:/usr/bin:/bin")
        record = dirs["calls"] / "osascript"
        _executable(dirs["bin"] / "osascript", f'printf "%s\\n" "$@" > "{record}"\n')
        selection = [tmp_path / "a photo.jpg", tmp_path / "album"]

        subprocess.run(["bash", "-c", _command_string(dirs), "automator", *map(str, selection)],
                       env={"PATH": f"{dirs['bin']}:/usr/bin:/bin"}, check=True, timeout=30)

        script = record.read_text()
        assert str(dirs["support"] / "launch.sh") in script
        # macOS mktemp -t always uses the per-user temp dir (/var/folders/.../T),
        # whatever TMPDIR says - which is the point: not the shared /tmp.
        args_file = Path(re.search(r"--args-file '([^']+)'", script).group(1))
        try:
            assert not str(args_file).startswith(("/tmp/", "/private/tmp/"))
            assert args_file.read_text().splitlines() == [str(p) for p in selection]
        finally:
            args_file.unlink(missing_ok=True)


class TestInstallerIgnoresTheClonesOwnCommand:
    def test_editable_install_inside_the_clone_is_not_used(self, dirs):
        # With the clone's venv active, `imgcrunch` resolves to venv/bin inside
        # the clone. Pointing the action there would tie it to the clone's
        # location again, so the installer must fall back to resize.sh.
        clone_bin = REPO_ROOT / "venv" / "bin"
        if not (clone_bin / "imgcrunch").exists():
            pytest.skip("needs the editable install in ./venv")

        r = _install(dirs, f"{clone_bin}:/usr/bin:/bin")

        assert r.returncode == 0, r.stdout + r.stderr
        launcher = (dirs["support"] / "launch.sh").read_text()
        assert str(REPO_ROOT / "resize.sh") in launcher
        assert "venv/bin/imgcrunch" not in launcher
