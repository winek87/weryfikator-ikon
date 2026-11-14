#!/usr/bin/env python3

# emoji/scanner.py
# -*- coding: utf-8 -*-

"""
emoji.scanner — chodzenie po plikach i wywołanie detekcji.

Ten moduł łączy `emoji.loader` (dane pluginów) z `emoji.detection`
(czysta logika). Nic nie wie o formatowaniu wyjścia — od tego jest
`emoji.reporter`. Dzięki temu można pisać własne reportery (JSON,
CSV, integracja z CI), nie ruszając skanera.

Funkcje publiczne:

  * `collect_files(target, skip_dirs, skip_ext)` — lista plików do skanu,
  * `iter_findings(line, codepoints, ranges)` — generator krotek
        (col0, cluster, ch, kind) dla jednej linii,
  * `scan(target, detection_data, only_kinds=None, fragile_mode="simple")`
        — pełny skan.

Kontrakt wyniku `scan()` (v3 — dodane `fragile_*` i `fragile_mode`):

    {
      "results": [
        {
          "file":              str,
          "line":              int,      # 1-based
          "col":               int,      # 1-based
          "col0":              int,      # 0-based
          "ch":                str,      # bazowy znak
          "cluster":           str,      # bazowy + modyfikatory
          "kind":              str,      # "EMOJI" | "VS16" | ...
          "cp":                str,      # "U+XXXX" bazowego znaku
          "wcwidth":           int | None,
          "heurystyka":        int,
          "rozjazd":           bool,
          "text_default":      bool,
          "fragile":           bool,     # zależne od fragile_mode
          "fragile_no_vs16":   bool,     # zawsze obliczane
          "fragile_with_vs16": bool,     # zawsze obliczane
          "fragile_mode":      str,      # znormalizowany tryb
          "font_risky":        bool,     # BMP z FONT_RISKY_BMP
          "context":           str,
        },
        ...
      ],
      "errors": [{"file": str, "error": str}, ...],
      "files_scanned": int,
      "files_skipped": int,
    }
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from .detection import (
    DEFAULT_FRAGILE_MODE,
    FRAGILE_MODES,
    classify,
    is_modifier_cp,
    measure_both,
)

# ── domyślne pomijane katalogi ───────────────────────────────────
DEFAULT_SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn",
    "node_modules",
    "__pycache__",
    ".venv", "venv", "env",
    "dist", "build", "target",
    ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox",
}

# ── domyślnie pomijane rozszerzenia ─────────────────────────────
DEFAULT_SKIP_EXT: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".ico", ".icns",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".mp3", ".wav", ".ogg", ".flac", ".webm",
    ".o", ".so", ".dll", ".dylib", ".a", ".lib",
    ".class", ".jar", ".pyc", ".pyo", ".wasm",
    ".lock", ".bak", ".min.js", ".min.css",
    ".exe", ".bin", ".dat",
}


# ── zbieranie plików ────────────────────────────────────────────

def collect_files(
    target: str | Path,
    skip_dirs: Iterable[str] | None = None,
    skip_ext: Iterable[str] | None = None,
) -> tuple[list[Path], int]:
    """
    Zwraca (lista_plików_do_skanu, liczba_pominiętych_plików).

    Obsługuje:
      * `target` to plik → zwraca [plik] (bez filtrowania po rozszerzeniu),
      * `target` to katalog → rekursywnie, z pominięciem `skip_dirs`
        i plików o rozszerzeniach z `skip_ext`,
      * `target` nie istnieje → ([], 0).

    Parametry `skip_dirs` / `skip_ext`:
        None → użyj `DEFAULT_SKIP_DIRS` / `DEFAULT_SKIP_EXT`.
        Zbiór pusty → nie pomijaj niczego.
        Zbiór własny → **zastępuje** domyślny (nie łączy).
    """
    dirs = set(DEFAULT_SKIP_DIRS if skip_dirs is None else skip_dirs)
    exts = {
        (e.lower() if e.startswith(".") else "." + e.lower())
        for e in (DEFAULT_SKIP_EXT if skip_ext is None else skip_ext)
    }

    p = Path(target)

    if p.is_file():
        return [p], 0

    if not p.is_dir():
        return [], 0

    files: list[Path] = []
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(p):
        dirnames[:] = sorted(d for d in dirnames if d not in dirs)

        for name in sorted(filenames):
            if Path(name).suffix.lower() in exts:
                skipped += 1
                continue
            files.append(Path(dirpath) / name)

    return files, skipped


# ── klastrowanie znaków w linii ─────────────────────────────────

def _cluster_at(line: str, i: int) -> tuple[str, int]:
    """Zwraca (klaster, następny_indeks) dla pozycji `i` w `line`."""
    j = i + 1
    while j < len(line) and is_modifier_cp(ord(line[j])):
        j += 1
    return line[i:j], j


def iter_findings(
    line: str,
    codepoints: dict[int, str] | None = None,
    ranges: list[tuple[int, int]] | None = None,
) -> Iterator[tuple[int, str, str, str]]:
    """
    Iteruje po znaleziskach w jednej linii.

    Yield: (col0, cluster, ch, kind).

    Osierocone modyfikatory (np. samotny VS16 bez znaku bazowego)
    też są zwracane — z `cluster == ch == ten_modyfikator`.
    """
    i = 0
    n = len(line)
    while i < n:
        cluster, j = _cluster_at(line, i)
        base = line[i]
        kind = classify(base, codepoints, ranges)

        if kind is not None:
            yield i, cluster, base, kind
        else:
            for offset, mod in enumerate(cluster[1:], 1):
                mod_kind = classify(mod, codepoints, ranges)
                if mod_kind is not None:
                    yield i + offset, mod, mod, mod_kind

        i = j


# ── pełny skan ──────────────────────────────────────────────────

def scan(
    target: str | Path,
    detection_data: dict,
    only_kinds: Iterable[str] | None = None,
    skip_dirs: Iterable[str] | None = None,
    skip_ext: Iterable[str] | None = None,
    fragile_mode: str = DEFAULT_FRAGILE_MODE,
) -> dict:
    """
    Skanuje `target` (plik lub katalog) i zwraca wyniki.

    Parametry:
        target:          ścieżka do pliku lub katalogu,
        detection_data:  wynik `emoji.loader.load_plugins()`,
        only_kinds:      opcjonalny zbiór rodzajów do raportowania
                         (np. `{"VS16"}` dla trybu `--vs16`),
        skip_dirs:       nadpisanie `DEFAULT_SKIP_DIRS`,
        skip_ext:        nadpisanie `DEFAULT_SKIP_EXT`,
        fragile_mode:    "simple" | "split" | "reporter" (domyślnie "simple").
                         Nieznany tryb → fallback do `DEFAULT_FRAGILE_MODE`.

    Zwraca dict opisany w docstringu modułu.
    """
    if fragile_mode not in FRAGILE_MODES:
        fragile_mode = DEFAULT_FRAGILE_MODE

    codepoints = detection_data.get("codepoints", {}) or {}
    ranges = detection_data.get("ranges", []) or []
    sets = detection_data.get("sets", {}) or {}

    kinds_filter: set[str] | None = set(only_kinds) if only_kinds else None

    files, files_skipped = collect_files(target, skip_dirs, skip_ext)

    results: list[dict] = []
    errors: list[dict] = []

    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append({"file": str(fp), "error": str(e)})
            continue

        for ln, line in enumerate(text.splitlines(), 1):
            context = line.strip()[:120]

            for col0, cluster, ch, kind in iter_findings(line, codepoints, ranges):
                if kinds_filter is not None and kind not in kinds_filter:
                    continue

                m = measure_both(cluster, sets, fragile_mode)
                results.append(
                    {
                        "file": str(fp),
                        "line": ln,
                        "col": col0 + 1,
                        "col0": col0,
                        "ch": ch,
                        "cluster": cluster,
                        "kind": kind,
                        "cp": f"U+{ord(ch):04X}",
                        "wcwidth": m["wcwidth"],
                        "heurystyka": m["heurystyka"],
                        "rozjazd": m["rozjazd"],
                        "text_default": m["text_default"],
                        "fragile": m["fragile"],
                        "fragile_no_vs16": m["fragile_no_vs16"],
                        "fragile_with_vs16": m["fragile_with_vs16"],
                        "fragile_mode": m["fragile_mode"],
                        "font_risky": m["font_risky"],
                        "context": context,
                    }
                )

    return {
        "results": results,
        "errors": errors,
        "files_scanned": len(files),
        "files_skipped": files_skipped,
    }


__all__ = [
    "DEFAULT_SKIP_DIRS",
    "DEFAULT_SKIP_EXT",
    "collect_files",
    "iter_findings",
    "scan",
]
