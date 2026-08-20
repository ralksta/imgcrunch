"""
Test suite for ImgCrunch.

Covers pure helpers (fast) and a few end-to-end process_image / CLI
integration tests (generate real images with Pillow into tmp dirs).
"""

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import imgcrunch as ic  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Pure helpers ─────────────────────────────────────────────────────────────

class TestCalculateNewSize:
    def test_landscape(self):
        assert ic.calculate_new_size(4000, 2000, 2000) == (2000, 1000)

    def test_portrait(self):
        assert ic.calculate_new_size(2000, 4000, 2000) == (1000, 2000)

    def test_square(self):
        assert ic.calculate_new_size(3000, 3000, 1500) == (1500, 1500)

    def test_extreme_panorama_never_zero(self):
        # 100000x30 down to 3000 -> short side rounds to 0 without clamp
        w, h = ic.calculate_new_size(100000, 30, 3000)
        assert w == 3000
        assert h >= 1

    def test_extreme_vertical_never_zero(self):
        w, h = ic.calculate_new_size(30, 100000, 3000)
        assert h == 3000
        assert w >= 1


class TestFormatBytes:
    def test_bytes(self):
        assert ic.format_bytes(512) == "512.0 B"

    def test_kb(self):
        assert ic.format_bytes(1536) == "1.5 KB"

    def test_mb(self):
        assert ic.format_bytes(5 * 1024 * 1024) == "5.0 MB"


class TestNeedsResize:
    def test_zero_disables(self):
        assert ic.needs_resize(9999, 9999, 0) is False

    def test_over(self):
        assert ic.needs_resize(3001, 100, 3000) is True

    def test_under(self):
        assert ic.needs_resize(3000, 3000, 3000) is False


class TestDetectDominantFormat:
    def test_dominant(self, tmp_path):
        imgs = [tmp_path / f"a{i}.png" for i in range(6)] + [tmp_path / "b.jpg"]
        assert ic.detect_dominant_format(imgs) == "jpeg"  # png maps to jpeg

    def test_no_majority_falls_back(self, tmp_path):
        imgs = [tmp_path / "a.heic", tmp_path / "b.webp", tmp_path / "c.avif"]
        assert ic.detect_dominant_format(imgs) == "jpeg"

    def test_empty(self):
        assert ic.detect_dominant_format([]) == "jpeg"


# ── Duplicate detection (two-stage) ──────────────────────────────────────────

class TestBuildDuplicateSet:
    def test_detects_identical_content(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        c = tmp_path / "c.bin"
        a.write_bytes(b"hello world")
        b.write_bytes(b"hello world")   # dup of a
        c.write_bytes(b"different!!!")
        dupes = ic.build_duplicate_set([a, b, c])
        assert str(b) in dupes
        assert str(a) not in dupes      # first occurrence kept
        assert str(c) not in dupes

    def test_same_size_different_content_not_dupe(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"AAAA")
        b.write_bytes(b"BBBB")          # same size, different content
        assert ic.build_duplicate_set([a, b]) == set()

    def test_first_occurrence_kept(self, tmp_path):
        paths = []
        for name in ("1.bin", "2.bin", "3.bin"):
            p = tmp_path / name
            p.write_bytes(b"same")
            paths.append(p)
        dupes = ic.build_duplicate_set(paths)
        assert str(paths[0]) not in dupes
        assert str(paths[1]) in dupes
        assert str(paths[2]) in dupes


# ── process_image integration ────────────────────────────────────────────────

def _make_image(path: Path, size=(100, 100), color=(255, 0, 0), mode="RGB"):
    Image.new(mode, size, color).save(path)


class TestProcessImage:
    def test_resize_dimensions(self, tmp_path):
        src = tmp_path / "src.jpg"
        _make_image(src, size=(4000, 2000))
        out = tmp_path / "out.jpg"
        res = ic.process_image(str(src), str(out), "jpeg", 85, 2000)
        assert res.error is None
        assert res.resized is True
        with Image.open(out) as im:
            assert im.size == (2000, 1000)

    def test_no_resize_when_small(self, tmp_path):
        src = tmp_path / "src.png"
        _make_image(src, size=(500, 500))
        out = tmp_path / "out.jpg"
        res = ic.process_image(str(src), str(out), "jpeg", 85, 3000)
        assert res.error is None
        assert res.resized is False
        assert out.exists()

    def test_alpha_preserved_for_webp(self, tmp_path):
        src = tmp_path / "src.png"
        _make_image(src, size=(200, 200), color=(0, 255, 0, 128), mode="RGBA")
        out = tmp_path / "out.webp"
        res = ic.process_image(str(src), str(out), "webp", 82, 3000)
        assert res.error is None
        with Image.open(out) as im:
            assert im.mode in ("RGBA", "LA")

    def test_alpha_flattened_for_jpeg(self, tmp_path):
        src = tmp_path / "src.png"
        _make_image(src, size=(200, 200), color=(0, 255, 0, 0), mode="RGBA")
        out = tmp_path / "out.jpg"
        res = ic.process_image(str(src), str(out), "jpeg", 85, 3000)
        assert res.error is None
        with Image.open(out) as im:
            assert im.mode == "RGB"

    def test_skip_copies_through_to_output(self, tmp_path):
        # An already-target jpeg, no resize needed -> should be skipped BUT
        # still produced at the output location so 'converted/' is complete.
        src = tmp_path / "src.jpg"
        _make_image(src, size=(500, 500))
        out = tmp_path / "converted" / "out.jpg"
        out.parent.mkdir()
        res = ic.process_image(str(src), str(out), "jpeg", 85, 3000)
        assert res.error is None
        assert res.skipped is True
        assert out.exists(), "skipped file must still be written to output"
        assert res.output_bytes > 0

    def test_strip_removes_exif(self, tmp_path):
        # Build a jpeg carrying an EXIF orientation tag, then strip it.
        import piexif
        src = tmp_path / "src.jpg"
        _make_image(src, size=(400, 300))
        exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}
        piexif.insert(piexif.dump(exif_dict), str(src))

        out = tmp_path / "out.jpg"
        res = ic.process_image(str(src), str(out), "jpeg", 85, 3000, strip_exif=True)
        assert res.error is None
        with Image.open(out) as im:
            assert "exif" not in im.info or not im.info.get("exif")

    def test_strip_bakes_orientation(self, tmp_path):
        # Orientation 6 = rotate 90deg. A 400x300 image tagged '6' should,
        # after stripping, have its pixels physically rotated to 300x400.
        import piexif
        src = tmp_path / "src.jpg"
        _make_image(src, size=(400, 300))
        exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}
        piexif.insert(piexif.dump(exif_dict), str(src))

        out = tmp_path / "out.jpg"
        res = ic.process_image(str(src), str(out), "jpeg", 85, 3000, strip_exif=True)
        assert res.error is None
        with Image.open(out) as im:
            assert im.size == (300, 400), "orientation must be baked into pixels"


# ── CLI integration: rename numbering has no gaps around dupes ────────────────

class TestRenameNumbering:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "imgcrunch.py"), *args],
            capture_output=True, text=True, timeout=120,
        )

    def test_rename_sequential_despite_dupes(self, tmp_path):
        # Three images, two identical -> with --skip-dupes the rename numbering
        # must stay 001, 002 (no gap), not 001, 003.
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        c = tmp_path / "c.png"
        Image.new("RGB", (100, 100), (255, 0, 0)).save(a)
        # b identical to a
        Image.new("RGB", (100, 100), (255, 0, 0)).save(b)
        Image.new("RGB", (120, 120), (0, 0, 255)).save(c)
        # make a and b byte-identical
        b.write_bytes(a.read_bytes())

        r = self._run(str(tmp_path), "-f", "jpeg", "--rename", "pic",
                      "--skip-dupes", "--no-move")
        assert r.returncode == 0, r.stderr
        conv = tmp_path / "converted"
        names = sorted(p.name for p in conv.glob("pic_*.jpg"))
        assert names == ["pic_001.jpg", "pic_002.jpg"], names


# ── CLI integration: dry-run writes nothing ──────────────────────────────────

class TestReplaceMode:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "imgcrunch.py"), *args],
            capture_output=True, text=True, timeout=120,
        )

    def test_replace_leaves_no_converted_dir(self, tmp_path):
        big = tmp_path / "big.jpg"
        keep = tmp_path / "keep.jpg"          # already optimal -> skip/copy-through
        Image.new("RGB", (4000, 1000), (9, 9, 9)).save(big)
        Image.new("RGB", (500, 500), (1, 2, 3)).save(keep)
        r = self._run(str(tmp_path), "-f", "jpeg", "-m", "2000", "--replace")
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "converted").exists()
        assert not (tmp_path / "originals").exists()
        # originals replaced in place, both still present
        assert big.exists() and keep.exists()
        with Image.open(big) as im:
            assert im.size == (2000, 500)


class TestDryRun:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "imgcrunch.py"), *args],
            capture_output=True, text=True, timeout=120,
        )

    def test_dry_run_writes_nothing(self, tmp_path):
        src = tmp_path / "a.png"
        Image.new("RGB", (4000, 2000), (255, 0, 0)).save(src)
        r = self._run(str(tmp_path), "-f", "jpeg", "-m", "2000", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "converted").exists()
        assert not (tmp_path / "originals").exists()
        assert "dry" in r.stdout.lower() or "would" in r.stdout.lower()


# ── rename_in_place: pure-ish unit tests ─────────────────────────────────────

class TestRenameInPlace:
    def _imgs(self, tmp_path, names):
        out = []
        for i, n in enumerate(names):
            p = tmp_path / n
            Image.new("RGB", (10 + i, 10), (i, i, i)).save(p)
            out.append(p)
        return out

    def test_numbering_follows_name_order_not_size(self, tmp_path):
        # b.png is deliberately the largest file; it must still become _002.
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        c = tmp_path / "c.png"
        Image.new("RGB", (10, 10), (1, 1, 1)).save(a)
        Image.new("RGB", (900, 900), (7, 90, 200)).save(b)
        Image.new("RGB", (10, 10), (2, 2, 2)).save(c)
        assert b.stat().st_size > a.stat().st_size

        n = ic.rename_in_place([b, c, a], "pic", dry_run=False)
        assert n == 3
        assert sorted(p.name for p in tmp_path.glob("pic_*")) == [
            "pic_001.png", "pic_002.png", "pic_003.png"
        ]
        # a (first alphabetically) -> pic_001
        with Image.open(tmp_path / "pic_001.png") as im:
            assert im.size == (10, 10)
        with Image.open(tmp_path / "pic_002.png") as im:
            assert im.size == (900, 900)

    def test_extensions_preserved(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.jpg"
        Image.new("RGB", (10, 10), (1, 1, 1)).save(a)
        Image.new("RGB", (10, 10), (2, 2, 2)).save(b)
        ic.rename_in_place([a, b], "x", dry_run=False)
        assert (tmp_path / "x_001.png").exists()
        assert (tmp_path / "x_002.jpg").exists()

    def test_padding_scales_past_999(self, tmp_path):
        imgs = self._imgs(tmp_path, [f"src_{i:04d}.png" for i in range(1001)])
        ic.rename_in_place(imgs, "p", dry_run=False)
        assert (tmp_path / "p_0001.png").exists()
        assert (tmp_path / "p_1001.png").exists()

    def test_collision_with_existing_target_names(self, tmp_path):
        # Renaming to a base that already matches existing filenames must not
        # destroy data: two-phase rename keeps every file.
        a = tmp_path / "urlaub_002.png"
        b = tmp_path / "urlaub_001.png"
        c = tmp_path / "zzz.png"
        Image.new("RGB", (11, 11), (1, 1, 1)).save(a)
        Image.new("RGB", (12, 12), (2, 2, 2)).save(b)
        Image.new("RGB", (13, 13), (3, 3, 3)).save(c)

        n = ic.rename_in_place([a, b, c], "urlaub", dry_run=False)
        assert n == 3
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "urlaub_001.png", "urlaub_002.png", "urlaub_003.png"
        ]
        # urlaub_001.png (alphabetically first) keeps its 11x11... no:
        # order is urlaub_001, urlaub_002, zzz -> sizes 12, 11, 13
        with Image.open(tmp_path / "urlaub_001.png") as im:
            assert im.size == (12, 12)
        with Image.open(tmp_path / "urlaub_002.png") as im:
            assert im.size == (11, 11)
        with Image.open(tmp_path / "urlaub_003.png") as im:
            assert im.size == (13, 13)

    def test_files_stay_in_their_own_folder(self, tmp_path):
        d1 = tmp_path / "one"
        d2 = tmp_path / "two"
        d1.mkdir()
        d2.mkdir()
        a = d1 / "a.png"
        b = d2 / "b.png"
        Image.new("RGB", (10, 10), (1, 1, 1)).save(a)
        Image.new("RGB", (10, 10), (2, 2, 2)).save(b)
        ic.rename_in_place([a, b], "f", dry_run=False)
        assert (d1 / "f_001.png").exists()
        assert (d2 / "f_002.png").exists()

    def test_dry_run_changes_nothing(self, tmp_path):
        a = tmp_path / "a.png"
        Image.new("RGB", (10, 10), (1, 1, 1)).save(a)
        ic.rename_in_place([a], "p", dry_run=True)
        assert a.exists()
        assert not (tmp_path / "p_001.png").exists()

    def test_no_leftover_temp_files(self, tmp_path):
        imgs = self._imgs(tmp_path, ["a.png", "b.png", "c.png"])
        ic.rename_in_place(imgs, "q", dry_run=False)
        assert not list(tmp_path.glob("*imgcrunch_rn*"))


# ── CLI integration: --rename-only ───────────────────────────────────────────

class TestRenameOnlyCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "imgcrunch.py"), *args],
            capture_output=True, text=True, timeout=120,
        )

    def test_renames_in_place_without_recompressing(self, tmp_path):
        a = tmp_path / "a.jpg"
        b = tmp_path / "b.jpg"
        Image.new("RGB", (4000, 2000), (255, 0, 0)).save(a)
        Image.new("RGB", (300, 300), (0, 0, 255)).save(b)
        before_a = a.read_bytes()

        r = self._run(str(tmp_path), "--rename-only", "--rename", "urlaub")
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "converted").exists()
        assert not (tmp_path / "originals").exists()
        assert not a.exists() and not b.exists()
        out_a = tmp_path / "urlaub_001.jpg"
        assert out_a.exists()
        assert (tmp_path / "urlaub_002.jpg").exists()
        # byte-identical: no recompression, no resize despite 4000px source
        assert out_a.read_bytes() == before_a

    def test_requires_rename_base(self, tmp_path):
        Image.new("RGB", (10, 10), (1, 1, 1)).save(tmp_path / "a.png")
        r = self._run(str(tmp_path), "--rename-only")
        assert r.returncode != 0
        assert "--rename" in (r.stdout + r.stderr)

    def test_dry_run_writes_nothing(self, tmp_path):
        a = tmp_path / "a.png"
        Image.new("RGB", (10, 10), (1, 1, 1)).save(a)
        r = self._run(str(tmp_path), "--rename-only", "--rename", "p", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert a.exists()
        assert not (tmp_path / "p_001.png").exists()

    def test_replace_with_rename_is_rejected(self, tmp_path):
        Image.new("RGB", (10, 10), (1, 1, 1)).save(tmp_path / "a.png")
        r = self._run(str(tmp_path), "-f", "jpeg", "--replace", "--rename", "x")
        assert r.returncode != 0
        assert "--rename-only" in (r.stdout + r.stderr)
