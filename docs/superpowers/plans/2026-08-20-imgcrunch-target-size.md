# ImgCrunch: Target-Size, Encoder-Preflight, JobSettings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ImgCrunch bekommt `--target-size`, das jede Ausgabedatei unter eine gewünschte Bytegröße drückt; dazu einen Encoder-Preflight, der fehlende Codecs vor dem ersten Bild erkennt, und eine `JobSettings`-Dataclass, die die Worker-Parameter bündelt und den Byte-Copy-Gate an einer Stelle zusammenführt.

**Architecture:** Die gesamte Maß- und Suchlogik zieht in ein neues, Pillow-freies Modul `sizing.py` mit reinen Funktionen. Die Target-Size-Suche bekommt ihre Encode-Funktion injiziert (`probe`-Callable), sodass sie ohne echte Bilddateien getestet werden kann. `imgcrunch.py` behält CLI, Wizard, Orchestrierung und `process_image` und re-exportiert die verschobenen Helfer, damit bestehende Tests unverändert laufen.

**Tech Stack:** Python 3.11+, Pillow, pytest. Optional: pillow-heif (HEIC/AVIF), pillow-jxl-plugin (JXL), piexif, tqdm.

**Spec:** Kein separates Spec-Dokument — das Design wurde im Brainstorming festgelegt und ist unten unter „Design-Entscheidungen" vollständig festgehalten. Der Plan ist die maßgebliche Quelle.

## Global Constraints

- Alles, was an `ProcessPoolExecutor.submit` übergeben wird, muss picklebar sein — `JobSettings` enthält ausschließlich primitive Felder.
- `sizing.py` importiert **nicht** aus PIL und fasst kein Dateisystem an. Nur `math` und `typing`. Das ist die Bedingung dafür, dass seine Tests in Millisekunden laufen.
- Bestehende öffentliche Namen bleiben unter `imgcrunch.<name>` erreichbar (`calculate_new_size`, `needs_resize`) — die vorhandene Testsuite ruft sie so auf.
- Alle Codekommentare, Docstrings, CLI-Hilfetexte und Commit-Nachrichten auf Englisch (Repo-Konvention).
- Bestehende Tests laufen mit `pytest tests/ -v` aus dem Repo-Wurzelverzeichnis; `tests/test_imgcrunch.py` fügt das Wurzelverzeichnis selbst zu `sys.path` hinzu.
- Kein Bild wird bei einem Fehler geschrieben — der bestehende atomare `.tmp`-Pfad bleibt unangetastet.

## Design-Entscheidungen (Begründung, nicht Umsetzung)

1. **`--target-size` skaliert notfalls herunter.** Erst Binärsuche über die Qualität bei der aktuellen Auflösung; reicht das nicht, wird die Auflösung schrittweise reduziert. Herunterskalieren erhält das vollständige Bild und ist damit „crunchen"; Beschneiden wäre es nicht und ist bewusst nicht Teil dieses Plans.
2. **`--max-size` läuft zuerst.** Die Target-Size-Suche setzt auf dem bereits durch `--max-size` verkleinerten Bild auf. Beide Optionen sind kombinierbar; `--max-size` ist die Obergrenze, `--target-size` drückt von dort weiter herunter.
3. **Die Suche bekommt den Encoder injiziert.** `sizing.search_scale(probe, ...)` ruft ein Callable auf, statt selbst Pillow zu benutzen. Die fehleranfälligen Teile — Stagnations-Abbruch, das einmalige Wiederhochgehen, die `sqrt`-Schätzung — werden damit gegen einen simulierten Encoder getestet.
4. **`forces_reencode()` deckt nur die bildunabhängigen Gründe ab.** Ob ein Resize nötig ist, hängt an den tatsächlichen Bildmaßen und bleibt deshalb im Worker, wo die geöffnete Datei vorliegt. Der Byte-Copy-Gate ist die Konjunktion aus beidem. Das ist der Unterschied zu PixelBatchs `hasPixelChanges`, das rein aus den Settings ableitbar ist.
5. **Verfehltes Ziel ist ein Fehler, kein stiller Kompromiss.** Erreicht die Suche das Ziel auch bei der Pixel-Untergrenze nicht, wird `result.error` gesetzt und keine Datei geschrieben. Das läuft in die bestehende Fehlerbehandlung und Zusammenfassung; keine neuen Zähler in `BatchStats`.
6. **Preflight bricht ab, statt das Format zu wechseln.** Ein anderes Ausgabeformat als angefordert ist in einem CLI schlimmer als ein Fehler.

## File Structure

- **Create `sizing.py`** — reine Funktionen: `needs_resize`, `calculate_new_size` (beide verschoben), `search_quality`, `search_scale`, `parse_size` (Parser für `500k`/`1.5m`). Keine Pillow-, keine Dateisystem-Abhängigkeit.
- **Create `tests/test_sizing.py`** — Tests für `sizing.py` gegen simulierte Encoder, ohne echte Bilddateien.
- **Modify `imgcrunch.py`** — `JobSettings`-Dataclass, `probe_encoder`, Re-Export aus `sizing`, neue Signatur von `process_image`, Target-Size-Pfad im Worker, CLI-Flag, Preflight-Aufruf in `main()`.
- **Modify `tests/test_imgcrunch.py`** — die zehn `process_image`-Aufrufe auf `JobSettings` umstellen, neue End-to-End-Tests.
- **Modify `README.md`** — Dokumentation der neuen Flag.

---

### Task 1: `sizing.py` anlegen und bestehende Helfer verschieben

Reines Verschieben ohne Verhaltensänderung. Danach existiert das Modul, in das die Suchlogik in Task 2 und 3 kommt.

**Files:**
- Create: `sizing.py`
- Modify: `imgcrunch.py:335-351` (Funktionen entfernen), `imgcrunch.py:22` (Import ergänzen)
- Test: `tests/test_sizing.py` (neu), `tests/test_imgcrunch.py` (läuft unverändert weiter)

**Interfaces:**
- Produces: `sizing.needs_resize(width: int, height: int, max_size: int) -> bool`, `sizing.calculate_new_size(width: int, height: int, target: int) -> tuple[int, int]`. Beide bleiben zusätzlich als `imgcrunch.needs_resize` / `imgcrunch.calculate_new_size` erreichbar.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_sizing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sizing.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'sizing'`

- [ ] **Step 3: Create `sizing.py` with the moved functions**

```python
#!/usr/bin/env python3
"""
Pure sizing and search arithmetic for ImgCrunch.

This module deliberately imports neither PIL nor anything that touches the
filesystem: every function here is a pure computation over numbers, so the
tricky parts (the target-size search in particular) can be tested against a
simulated encoder in milliseconds instead of against real AVIF encodes.
"""

import math
from typing import Callable, Optional


def needs_resize(width: int, height: int, max_size: int) -> bool:
    if max_size == 0:
        return False
    return width > max_size or height > max_size


def calculate_new_size(width: int, height: int, target: int) -> tuple[int, int]:
    # Clamp the short side to >=1: extreme aspect ratios (e.g. 100000x30)
    # can otherwise round to 0 and make Pillow's resize() raise.
    if width >= height:
        new_width  = target
        new_height = max(1, int(height * (target / width)))
    else:
        new_height = target
        new_width  = max(1, int(width * (target / height)))
    return new_width, new_height
```

- [ ] **Step 4: Remove the originals from `imgcrunch.py` and re-export**

Lösche `needs_resize` und `calculate_new_size` aus `imgcrunch.py` (Zeilen 335-351) und ergänze bei den Imports (nach `from typing import Optional`, imgcrunch.py:22):

```python
# Pure sizing/search arithmetic lives in its own module so it can be tested
# without images. Re-exported here because callers (and tests) use
# imgcrunch.needs_resize / imgcrunch.calculate_new_size.
from sizing import calculate_new_size, needs_resize  # noqa: F401
```

- [ ] **Step 5: Run the full suite to verify nothing regressed**

Run: `pytest tests/ -v`
Expected: PASS — alle bisherigen Tests inklusive `ic.calculate_new_size` und `ic.needs_resize`, plus die sechs neuen aus `tests/test_sizing.py`.

- [ ] **Step 6: Commit**

```bash
git add sizing.py tests/test_sizing.py imgcrunch.py
git commit -m "refactor: extract pure sizing helpers into sizing.py"
```

---

### Task 2: `search_quality` — Binärsuche über die Qualität

**Files:**
- Modify: `sizing.py`
- Test: `tests/test_sizing.py`

**Interfaces:**
- Produces: `sizing.search_quality(encode: Callable[[int], bytes], target_bytes: int, lo: int = 1, hi: int = 100) -> Optional[tuple[int, bytes]]` — gibt `(quality, data)` für die höchste Qualität zurück, deren Encode noch unter `target_bytes` liegt, oder `None`, wenn selbst `lo` nicht passt.

- [ ] **Step 1: Write the failing test**

An `tests/test_sizing.py` anhängen:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sizing.py::TestSearchQuality -v`
Expected: FAIL mit `AttributeError: module 'sizing' has no attribute 'search_quality'`

- [ ] **Step 3: Implement `search_quality` in `sizing.py`**

```python
def search_quality(
    encode: Callable[[int], bytes],
    target_bytes: int,
    lo: int = 1,
    hi: int = 100,
) -> Optional[tuple[int, bytes]]:
    """
    Binary search the highest quality whose encode still fits target_bytes.

    `encode(quality) -> bytes` is injected so this stays testable without a
    real encoder. Runs at most 7 encodes (log2(100) is about 6.64), which is
    what keeps --target-size affordable on a large batch.

    Returns (quality, data), or None when even `lo` overshoots the target.
    """
    best: Optional[tuple[int, bytes]] = None

    for _ in range(7):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        data = encode(mid)
        if len(data) <= target_bytes:
            best = (mid, data)
            lo = mid + 1
        else:
            hi = mid - 1

    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sizing.py -v`
Expected: PASS (10 Tests)

- [ ] **Step 5: Commit**

```bash
git add sizing.py tests/test_sizing.py
git commit -m "feat: add quality binary search for target-size encoding"
```

---

### Task 3: `search_scale` — Auflösung reduzieren, wenn Qualität nicht reicht

Das ist der Teil mit den echten Fallstricken: Stagnation bei ganzzahligen Pixelmaßen, Endlosschleifen durch Hin-und-Her-Skalieren, und verschenkte Qualität, wenn man weit unter dem Ziel landet.

**Files:**
- Modify: `sizing.py`
- Test: `tests/test_sizing.py`

**Interfaces:**
- Consumes: `sizing.search_quality` aus Task 2 (nur indirekt — der Aufrufer steckt sie in sein `probe`).
- Produces: `sizing.search_scale(probe: Callable[[int, int], tuple[Optional[bytes], int]], target_bytes: int, width: int, height: int, min_edge: int = 16, max_attempts: int = 16) -> Optional[bytes]`.
  `probe(w, h)` liefert `(fit, floor)`: `fit` sind die Bytes, die bei dieser Pixelgröße unter das Ziel passen (oder `None`), `floor` ist die Bytegröße des kleinstmöglichen Encodes bei dieser Größe. `search_scale` gibt die besten gefundenen Bytes zurück oder `None`.

- [ ] **Step 1: Write the failing test**

An `tests/test_sizing.py` anhängen:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sizing.py::TestSearchScale -v`
Expected: FAIL mit `AttributeError: module 'sizing' has no attribute 'search_scale'`

- [ ] **Step 3: Implement `search_scale` in `sizing.py`**

```python
def search_scale(
    probe: Callable[[int, int], tuple[Optional[bytes], int]],
    target_bytes: int,
    width: int,
    height: int,
    min_edge: int = 16,
    max_attempts: int = 16,
) -> Optional[bytes]:
    """
    Shrink the pixel dimensions until an encode fits target_bytes.

    `probe(w, h) -> (fit, floor)` does the quality search at one pixel size:
    `fit` is the data that fits (or None), `floor` is the size of the
    smallest possible encode there. Injecting it keeps every branch below
    testable without an encoder.

    Returns the best data found, or None if even min_edge overshoots.
    """
    fit, floor = probe(width, height)
    if fit is not None:
        return fit
    if floor <= 0:
        return None

    # Encoded size scales roughly with pixel count, so the edge scale needed
    # is about sqrt(target / current). Clamped: 0.95 because we already know
    # full size doesn't fit, 0.002 to stay off zero.
    scale = min(max(math.sqrt(target_bytes / floor), 0.002), 0.95)

    best: Optional[bytes] = None
    last: Optional[tuple[int, int]] = None
    grew = False

    for _ in range(max_attempts):
        w = max(min_edge, int(width * scale))
        h = max(min_edge, int(height * scale))

        # Integer rounding (or the min_edge floor) can produce the same pixel
        # size twice — without this the loop would spin without progress.
        if (w, h) == last:
            if scale <= 0.002:
                break
            scale = max(scale * 0.6, 0.002)
            continue
        last = (w, h)

        fit, floor_at = probe(w, h)

        if fit is not None:
            best = fit
            # Landing far under the budget means we threw away pixels we could
            # have kept. Try one size up — but only once, otherwise a borderline
            # image oscillates between two sizes until max_attempts runs out.
            if not grew and len(fit) < target_bytes * 0.85:
                new_scale = scale * 1.15
                if new_scale < 1.0:
                    grew = True
                    scale = new_scale
                    continue
            break

        # Still too big. floor_at > target_bytes here (otherwise probe would
        # have returned a fit), so the factor is always < 1 and the loop
        # strictly shrinks. The 0.6 cap stops a single wild estimate from
        # collapsing straight to min_edge.
        if floor_at > 0:
            scale = max(scale * max(math.sqrt(target_bytes / floor_at), 0.6), 0.002)
        else:
            scale = max(scale * 0.6, 0.002)

    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sizing.py -v`
Expected: PASS (16 Tests)

- [ ] **Step 5: Commit**

```bash
git add sizing.py tests/test_sizing.py
git commit -m "feat: add dimension search for unreachable target sizes"
```

---

### Task 4: `JobSettings` und der Byte-Copy-Gate

**Files:**
- Modify: `imgcrunch.py:112-127` (Dataclass ergänzen), `imgcrunch.py:353-361` (Signatur), `imgcrunch.py:435-445` (Gate), `imgcrunch.py:1443-1448` (Aufrufstelle)
- Test: `tests/test_imgcrunch.py` (zehn Aufrufstellen umstellen), `tests/test_settings.py` (neu)

**Interfaces:**
- Produces: `imgcrunch.JobSettings(format_key: str, quality: int, max_size: int, lossless: bool = False, strip_exif: bool = False, target_bytes: Optional[int] = None)` mit `forces_reencode() -> bool`. Neue Worker-Signatur: `process_image(input_path_str: str, output_path_str: str, settings: JobSettings, input_bytes: int = 0) -> ProcessResult`.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_settings.py`:

```python
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

    def test_target_bytes_forces_reencode(self):
        assert _settings(target_bytes=100_000).forces_reencode() is True

    def test_zero_target_bytes_does_not_force_reencode(self):
        assert _settings(target_bytes=0).forces_reencode() is False


class TestPicklable:
    def test_settings_survive_pickling(self):
        """ProcessPoolExecutor pickles every worker argument."""
        import pickle
        settings = _settings(target_bytes=50_000)
        assert pickle.loads(pickle.dumps(settings)) == settings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL mit `AttributeError: module 'imgcrunch' has no attribute 'JobSettings'`

- [ ] **Step 3: Add the dataclass to `imgcrunch.py`**

Direkt vor `@dataclass class ProcessResult` (imgcrunch.py:111) einfügen:

```python
@dataclass(frozen=True)
class JobSettings:
    """
    Everything a worker needs to process one image.

    Frozen and primitive-only: every field crosses a process boundary via
    ProcessPoolExecutor, which pickles its arguments.
    """
    format_key:   str
    quality:      int
    max_size:     int
    lossless:     bool = False
    strip_exif:   bool = False
    target_bytes: Optional[int] = None

    def forces_reencode(self) -> bool:
        """
        True when these settings alone rule out a byte-for-byte copy.

        This covers only the image-independent reasons. Whether a resize or a
        mode conversion is needed depends on the actual pixels, so those
        checks stay in the worker where the file is already open — the
        byte-copy path requires both this to be False and those checks to
        pass.
        """
        return bool(self.lossless or self.strip_exif or self.target_bytes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py -v`
Expected: PASS (6 Tests)

- [ ] **Step 5: Change the `process_image` signature**

Ersetze den Kopf (imgcrunch.py:353-361) durch:

```python
def process_image(
    input_path_str:  str,
    output_path_str: str,
    settings:        JobSettings,
    input_bytes:     int = 0,
) -> ProcessResult:
    """
    Process a single image: convert, optionally resize, verify output, atomic write.
    Runs in a subprocess worker — only uses serialisable types.
    """
    input_path  = Path(input_path_str)
    output_path = Path(output_path_str)
    input_ext   = input_path.suffix.lower()

    format_key = settings.format_key
    quality    = settings.quality
    max_size   = settings.max_size
    lossless   = settings.lossless
    strip_exif = settings.strip_exif
```

Die lokalen Aliase halten den restlichen Funktionsrumpf unverändert — das ist Absicht, damit dieser Task keine Verhaltensänderung enthält und der Diff prüfbar bleibt.

- [ ] **Step 6: Route the byte-copy gate through `forces_reencode()`**

Ersetze die Early-Bail-Out-Bedingung (imgcrunch.py:441-443) durch:

```python
            # Byte-copy gate: nothing in the settings forces a re-encode AND
            # nothing about this particular image does either. Copy straight
            # through — zero generational loss.
            if already_target and not settings.forces_reencode() \
                    and not needs_resize(width, height, max_size) \
                    and img.mode in ('RGB', 'L') and not is_animated_gif:
```

`lossless` und `strip_exif` verschwinden hier aus der Bedingung — sie stecken jetzt in `forces_reencode()`.

- [ ] **Step 7: Update the executor call site**

Ersetze imgcrunch.py:1443-1448:

```python
        job_settings = JobSettings(
            format_key=args.format,
            quality=args.quality,
            max_size=args.max_size,
            lossless=lossless,
            strip_exif=strip,
        )

        future_to_path = {}
        for img_path, output_path, file_size in tasks:
            future = executor.submit(
                process_image,
                str(img_path), str(output_path), job_settings, file_size,
            )
            future_to_path[future] = img_path
```

`job_settings` wird vor der `for`-Schleife gebaut, aber innerhalb des `with ProcessPoolExecutor(...)`-Blocks.

- [ ] **Step 8: Update the ten `process_image` calls in the existing tests**

In `tests/test_imgcrunch.py` einen Helfer oben im Modul ergänzen (nach dem `import imgcrunch as ic`):

```python
def job(format_key="jpeg", quality=85, max_size=3000, **kwargs):
    """Shorthand for building JobSettings in tests."""
    return ic.JobSettings(format_key=format_key, quality=quality,
                          max_size=max_size, **kwargs)
```

Dann jeden Aufruf umschreiben, zum Beispiel:

```python
# vorher:  res = ic.process_image(str(src), str(out), "jpeg", 85, 2000)
res = ic.process_image(str(src), str(out), job(max_size=2000))

# vorher:  res = ic.process_image(str(src), str(out), "webp", 82, 3000)
res = ic.process_image(str(src), str(out), job("webp", 82))

# vorher:  res = ic.process_image(str(src), str(out), "jpeg", 85, 3000, strip_exif=True)
res = ic.process_image(str(src), str(out), job(strip_exif=True))
```

Betroffen sind die Zeilen 126, 136, 145, 154, 166, 181, 196 sowie alle weiteren Treffer von `ic.process_image` — vor dem Umschreiben mit `grep -n "ic.process_image" tests/test_imgcrunch.py` die vollständige Liste holen, damit keiner übersehen wird.

- [ ] **Step 9: Run the full suite**

Run: `pytest tests/ -v`
Expected: PASS — alle bestehenden Tests plus `tests/test_settings.py` und `tests/test_sizing.py`.

- [ ] **Step 10: Verify the real pipeline still runs end to end**

Run:
```bash
mkdir -p /tmp/ic-check && python3 -c "
from PIL import Image
Image.new('RGB', (4000, 3000), (120, 40, 80)).save('/tmp/ic-check/a.png')
Image.new('RGB', (800, 600), (10, 200, 90)).save('/tmp/ic-check/b.png')
" && python3 imgcrunch.py /tmp/ic-check -f jpeg -m 2000 --no-move
```
Expected: beide Bilder landen in `/tmp/ic-check/converted/`, die Zusammenfassung meldet 2 verarbeitete Bilder und 0 Fehler.

- [ ] **Step 11: Commit**

```bash
git add imgcrunch.py tests/test_imgcrunch.py tests/test_settings.py
git commit -m "refactor: bundle worker parameters into JobSettings"
```

---

### Task 5: Encoder-Preflight

**Files:**
- Modify: `imgcrunch.py` (neue Funktion bei den Helfern, Aufruf in `main()` an Stelle von imgcrunch.py:1162-1168)
- Test: `tests/test_imgcrunch.py`

**Interfaces:**
- Produces: `imgcrunch.probe_encoder(format_key: str) -> Optional[str]` — gibt `None` zurück, wenn das Format encodierbar ist, sonst einen fertigen, mehrzeiligen Installationshinweis.

- [ ] **Step 1: Write the failing test**

An `tests/test_imgcrunch.py` anhängen:

```python
class TestProbeEncoder:
    def test_jpeg_is_always_encodable(self):
        assert ic.probe_encoder("jpeg") is None

    def test_original_needs_no_encoder(self):
        assert ic.probe_encoder("original") is None

    def test_unknown_format_reports_a_hint(self):
        hint = ic.probe_encoder("definitely-not-a-format")
        assert hint is not None
        assert isinstance(hint, str)

    def test_hint_names_the_install_command(self, monkeypatch):
        """A broken encoder must produce an actionable message, not a traceback."""
        def boom(*args, **kwargs):
            raise OSError("encoder not available")

        monkeypatch.setattr(ic.Image.Image, "save", boom)
        hint = ic.probe_encoder("avif")
        assert hint is not None
        assert "pip install" in hint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_imgcrunch.py::TestProbeEncoder -v`
Expected: FAIL mit `AttributeError: module 'imgcrunch' has no attribute 'probe_encoder'`

- [ ] **Step 3: Implement `probe_encoder`**

`import io` zu den Imports oben in `imgcrunch.py` ergänzen (alphabetisch nach `import hashlib`), dann die Funktion nach `format_bytes` (imgcrunch.py:150) einfügen:

```python
# Install hints per format, used when the encoder probe fails.
ENCODER_HINTS = {
    'heic': 'pip install pillow-heif',
    'avif': 'pip install pillow-heif',
    'jxl':  'pip install pillow-jxl-plugin',
}


def probe_encoder(format_key: str) -> Optional[str]:
    """
    Verify the output format can actually be *encoded* on this machine.

    Importing pillow_heif successfully does not mean AVIF encoding works —
    the plugin may be present without its encoder. Encoding a 1x1 image is
    the only honest check, and it costs microseconds once per run.

    Returns None when the format is fine, otherwise an install hint.
    """
    if format_key == 'original':
        return None

    fmt = FORMAT_CONFIG.get(format_key)
    if fmt is None:
        return f"Unknown output format: {format_key}"

    try:
        buf = io.BytesIO()
        Image.new('RGB', (1, 1)).save(buf, fmt['pillow_format'], quality=80)
    except Exception as exc:
        hint = ENCODER_HINTS.get(format_key)
        msg = f"{format_key.upper()} output is not encodable here ({exc})."
        if hint:
            msg += f"\nInstall with: {hint}"
        return msg

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_imgcrunch.py::TestProbeEncoder -v`
Expected: PASS (4 Tests)

- [ ] **Step 5: Replace the import-only checks in `main()`**

Ersetze imgcrunch.py:1162-1168 (den `HEIF_AVAILABLE` / `JXL_AVAILABLE`-Block) durch:

```python
    # Encoder preflight: fail before touching a single image, not on file 200.
    encoder_problem = probe_encoder(args.format)
    if encoder_problem:
        print(f"{C.RED}Error: {encoder_problem}{C.RESET}")
        sys.exit(1)
```

- [ ] **Step 6: Verify the preflight fires**

Run: `python3 imgcrunch.py /tmp/ic-check -f jxl --dry-run`
Expected: entweder ein sauberer Dry-Run (JXL-Encoder vorhanden) oder ein einzeiliger Fehler mit `pip install pillow-jxl-plugin` und Exit-Code 1 — in keinem Fall ein Traceback. Exit-Code prüfen mit `echo $?`.

- [ ] **Step 7: Commit**

```bash
git add imgcrunch.py tests/test_imgcrunch.py
git commit -m "feat: probe the real encoder before starting a batch"
```

---

### Task 6: `--target-size` verdrahten

**Files:**
- Modify: `sizing.py` (`parse_size`), `imgcrunch.py` (CLI-Flag, Validierung, `JobSettings`-Feld füllen, Worker-Pfad)
- Test: `tests/test_sizing.py`, `tests/test_imgcrunch.py`

**Interfaces:**
- Consumes: `sizing.search_quality`, `sizing.search_scale`, `imgcrunch.JobSettings.target_bytes`.
- Produces: `sizing.parse_size(text: str) -> int` — wandelt `"500k"`, `"1.5m"`, `"800kb"`, `"250000"` in Bytes; wirft `ValueError` bei Unsinn.

- [ ] **Step 1: Write the failing test for the parser**

An `tests/test_sizing.py` anhängen:

```python
import pytest


class TestParseSize:
    def test_plain_number_is_bytes(self):
        assert sizing.parse_size("250000") == 250_000

    def test_kilobyte_suffix(self):
        assert sizing.parse_size("500k") == 500 * 1024

    def test_kb_suffix_is_the_same(self):
        assert sizing.parse_size("500kb") == 500 * 1024

    def test_megabyte_suffix_accepts_decimals(self):
        assert sizing.parse_size("1.5m") == int(1.5 * 1024 * 1024)

    def test_case_and_whitespace_are_ignored(self):
        assert sizing.parse_size("  2M ") == 2 * 1024 * 1024

    def test_zero_is_rejected(self):
        with pytest.raises(ValueError):
            sizing.parse_size("0")

    def test_garbage_is_rejected(self):
        with pytest.raises(ValueError):
            sizing.parse_size("big")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sizing.py::TestParseSize -v`
Expected: FAIL mit `AttributeError: module 'sizing' has no attribute 'parse_size'`

- [ ] **Step 3: Implement `parse_size` in `sizing.py`**

```python
_SIZE_UNITS = {'': 1, 'b': 1, 'k': 1024, 'kb': 1024,
               'm': 1024 * 1024, 'mb': 1024 * 1024}


def parse_size(text: str) -> int:
    """
    Parse a human-written byte budget: "250000", "500k", "800kb", "1.5m".

    Raises ValueError on anything else, including zero and negatives — a
    target of zero bytes is never what someone meant.
    """
    cleaned = str(text).strip().lower()
    digits = cleaned.rstrip('abkm')
    unit = cleaned[len(digits):]

    if unit not in _SIZE_UNITS:
        raise ValueError(f"unknown size unit in {text!r}")

    try:
        value = float(digits)
    except ValueError:
        raise ValueError(f"not a size: {text!r}") from None

    size = int(value * _SIZE_UNITS[unit])
    if size <= 0:
        raise ValueError(f"size must be positive, got {text!r}")
    return size
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sizing.py -v`
Expected: PASS (23 Tests)

- [ ] **Step 5: Add the CLI flag and its validation**

Nach `--lossless` (imgcrunch.py:1134) einfügen:

```python
        parser.add_argument('--target-size', type=str, default=None, dest='target_size',
                            metavar='SIZE',
                            help='Shrink every output below SIZE (e.g. 500k, 1.5m). '
                                 'Lowers quality first, then dimensions if needed.')
```

Und in die Beispielliste des Epilogs (nach der `--lossless`-Zeile, imgcrunch.py:1104):

```
  imgcrunch /path/to/images --target-size 500k        # every output under 500 KB
```

Nach dem `--rename-only`-Validierungsblock (imgcrunch.py:1188) einfügen:

```python
    target_bytes = None
    target_size_arg = getattr(args, 'target_size', None)
    if target_size_arg is not None:
        try:
            target_bytes = sizing.parse_size(target_size_arg)
        except ValueError as exc:
            print(f"{C.RED}Error: --target-size: {exc}{C.RESET}")
            sys.exit(1)
        if lossless:
            print(f"{C.RED}Error: --target-size cannot be combined with --lossless — "
                  f"lossless encoding has no quality to trade away.{C.RESET}")
            sys.exit(1)
        if args.format == 'original':
            print(f"{C.RED}Error: --target-size needs a real output format — "
                  f"--format original copies files without re-encoding.{C.RESET}")
            sys.exit(1)
```

Dazu oben bei den Imports `import sizing` ergänzen (die bestehende `from sizing import ...`-Zeile bleibt, beide nebeneinander sind hier korrekt, weil der Code jetzt beides braucht).

- [ ] **Step 6: Pass it into `JobSettings`**

In der Aufrufstelle aus Task 4 ergänzen:

```python
        job_settings = JobSettings(
            format_key=args.format,
            quality=args.quality,
            max_size=args.max_size,
            lossless=lossless,
            strip_exif=strip,
            target_bytes=target_bytes,
        )
```

- [ ] **Step 7: Write the failing end-to-end test**

An `tests/test_imgcrunch.py` anhängen:

```python
class TestTargetSize:
    def _noisy_image(self, path, size=(1600, 1200)):
        """Random noise so JPEG can't cheat its way under the target."""
        import random
        img = Image.new("RGB", size)
        rnd = random.Random(1234)
        img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                     for _ in range(size[0] * size[1])])
        img.save(path)

    def test_output_lands_under_the_target(self, tmp_path):
        src = tmp_path / "noise.png"
        out = tmp_path / "noise.jpg"
        self._noisy_image(src)

        settings = ic.JobSettings(format_key="jpeg", quality=95, max_size=0,
                                  target_bytes=40_000)
        res = ic.process_image(str(src), str(out), settings)

        assert res.error is None
        assert out.stat().st_size <= 40_000

    def test_impossible_target_is_reported_as_an_error(self, tmp_path):
        src = tmp_path / "noise.png"
        out = tmp_path / "noise.jpg"
        self._noisy_image(src, size=(400, 300))

        settings = ic.JobSettings(format_key="jpeg", quality=95, max_size=0,
                                  target_bytes=1)
        res = ic.process_image(str(src), str(out), settings)

        assert res.error is not None
        assert not out.exists(), "no file may be written when the target is unreachable"

    def test_generous_target_keeps_full_resolution(self, tmp_path):
        src = tmp_path / "noise.png"
        out = tmp_path / "noise.jpg"
        self._noisy_image(src, size=(800, 600))

        settings = ic.JobSettings(format_key="jpeg", quality=95, max_size=0,
                                  target_bytes=5_000_000)
        res = ic.process_image(str(src), str(out), settings)

        assert res.error is None
        with Image.open(out) as img:
            assert img.size == (800, 600)
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pytest tests/test_imgcrunch.py::TestTargetSize -v`
Expected: FAIL — `test_output_lands_under_the_target` schlägt fehl, weil die Datei noch mit Qualität 95 geschrieben wird und über 40 KB liegt.

- [ ] **Step 9: Implement the target-size path in the worker**

Im statischen Zweig von `process_image`, direkt vor dem `# Build save kwargs`-Block (imgcrunch.py:551), einfügen:

```python
                # ── Target size: search quality, then dimensions ──────────
                if settings.target_bytes:
                    def probe(w, h, _img=img):
                        frame = _img if (w, h) == _img.size else \
                            _img.resize((w, h), Image.Resampling.LANCZOS)

                        def encode(q):
                            buf = io.BytesIO()
                            kwargs = {**fmt['extra_opts'], 'quality': q}
                            if exif_bytes:
                                kwargs['exif'] = exif_bytes
                            frame.save(buf, fmt['pillow_format'], **kwargs)
                            return buf.getvalue()

                        hit = sizing.search_quality(encode, settings.target_bytes)
                        if hit is not None:
                            return hit[1], len(hit[1])
                        # Only the no-fit branch needs the floor, so pay for it
                        # only there.
                        return None, len(encode(1))

                    cur_w, cur_h = img.size
                    data = sizing.search_scale(
                        probe, settings.target_bytes, cur_w, cur_h
                    )
                    if data is None:
                        raise ValueError(
                            f"cannot reach target size "
                            f"{format_bytes(settings.target_bytes)}"
                        )

                    tmp_path = output_path.with_suffix(output_path.suffix + '.tmp')
                    try:
                        tmp_path.write_bytes(data)
                        with Image.open(tmp_path) as verify_img:
                            verify_img.verify()
                        tmp_path.replace(output_path)
                    except Exception:
                        tmp_path.unlink(missing_ok=True)
                        raise
                    with Image.open(output_path) as final_img:
                        result.new_size = final_img.size
                        result.resized = final_img.size != result.original_size
                    result.output_bytes = output_path.stat().st_size
                    return result
```

`import sizing` muss dafür oben im Modul stehen (in Task 6, Step 5 bereits ergänzt). Der Pfad kehrt bewusst früh zurück: die normale `img.save`-Strecke darunter würde die gefundenen Bytes sonst erneut encodieren.

- [ ] **Step 10: Run the tests**

Run: `pytest tests/ -v`
Expected: PASS — alle Tests inklusive der drei neuen aus `TestTargetSize`.

- [ ] **Step 11: Verify on the CLI**

Run:
```bash
python3 imgcrunch.py /tmp/ic-check -f jpeg --target-size 60k --no-move -o /tmp/ic-out
ls -l /tmp/ic-out
```
Expected: jede Ausgabedatei ist 60 KB oder kleiner; die Zusammenfassung meldet 0 Fehler.

- [ ] **Step 12: Commit**

```bash
git add sizing.py imgcrunch.py tests/test_sizing.py tests/test_imgcrunch.py
git commit -m "feat: add --target-size to crunch outputs below a byte budget"
```

---

### Task 7: Dokumentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: die fertige `--target-size`-Flag aus Task 6 und den Preflight aus Task 5.

- [ ] **Step 1: Document `--target-size` under Core Features**

Im Abschnitt „📦 Multi-Format Power" nach der `Smart Quality`-Zeile einfügen:

```markdown
- **Target Size (`--target-size`)**: Force every output below a byte budget (`500k`, `1.5m`). Quality is lowered first; if that isn't enough, the image is scaled down until it fits. Files that can't reach the target are reported as errors instead of being written oversized.
```

- [ ] **Step 2: Document the preflight under Privacy & Safety**

Nach der `Preflight Disk Check`-Zeile einfügen:

```markdown
- **Encoder Preflight**: Verifies the output format can actually be encoded on this machine before the batch starts — a missing AVIF or JXL encoder fails immediately with an install hint instead of on image 200.
```

- [ ] **Step 3: Add a usage example**

Im Abschnitt mit den Kommandozeilenbeispielen ergänzen:

```bash
imgcrunch ~/Pictures --target-size 500k        # every output under 500 KB
imgcrunch ~/Pictures -f webp --target-size 200k -m 2000
```

- [ ] **Step 4: Verify the documented behaviour matches reality**

Run: `python3 imgcrunch.py --help | grep -A2 target-size`
Expected: der Hilfetext stimmt mit der README-Beschreibung überein.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document --target-size and the encoder preflight"
```

---

## Offene Punkte für später

- **Presets.** Im Brainstorming bewusst gestrichen: Plattform-Presets brauchen Center-Crop, und blinder Mittenbeschnitt ohne Vorschau beschädigt Batch-Ergebnisse. Falls das Thema wiederkommt, wäre die tragfähige Variante keine Plattform-Liste, sondern „Crunch-Profile" (Format + Qualität + `--max-size` + `--target-size` unter einem Namen) — kein Beschnitt, kein neues Bildmodell.
- **Fit-Modus** (in eine W×H-Box skalieren, Seitenverhältnis erhalten). Fiel mit den Presets weg, weil `--max-size` den Bedarf abdeckt. Wäre eine reine Ergänzung in `sizing.py`, falls jemand danach fragt.
- **Animierte GIFs und `--target-size`.** Der Target-Size-Pfad sitzt bewusst nur im statischen Zweig von `process_image`. Ein animiertes GIF nach WebP/AVIF wird bei gesetztem `--target-size` also mit der normalen Qualität geschrieben und kann das Budget überschreiten. Eine Suche über alle Frames wäre um den Faktor Framezahl teurer; falls das je gebraucht wird, gehört es in einen eigenen Task mit eigener Entscheidung, ob die Frames einzeln oder gemeinsam skaliert werden.
