#!/usr/bin/env python3

#emoji/loader.py
# -*- coding: utf-8 -*-

"""
emoji.loader — ładowanie pluginów detekcji i zamienników.

System pluginów jest celowo prosty:

    emoji/wykrywanie/   ← pluginy "co wykrywać"
    emoji/zamienniki/   ← pluginy "czym zastępować"

Każdy plugin to plik `.json` lub `.py` z zadeklarowanymi stałymi.
Pliki ładowane są alfabetycznie (stąd prefixy `00_`, `10_`, `20_`).
Przy duplikacie **pierwszy wygrywa**; loader dopisuje ostrzeżenie,
ale nie przerywa pracy.

Konwencje:
  * Pliki zaczynające się od `_` (np. `_README.md`) są pomijane.
  * Rozszerzenia inne niż `.json` / `.py` są pomijane.
  * `codepoints` w pluginie detekcji to mapa int->str (JSON: `"U+XXXX"`,
    .py: int lub string akceptowany przez `_parse_cp`).
  * `ranges` to lista par (start, end) — obie strony domknięte.
  * `sets` to mapa nazwa_zbioru -> zbiór codepointów (int).

Format pluginu detekcji (.json):

    {
      "name": "warnings",
      "description": "...",
      "version": "1.0",
      "codepoints": [{"cp": "U+26A0", "kind": "EMOJI", "label": "Warning"}],
      "ranges":     [{"start": "U+1F300", "end": "U+1F5FF", "kind": "EMOJI"}],
      "sets":       {"TEXT_DEFAULT_BMP": ["U+26A0", "U+2699"]}
    }

Format pluginu detekcji (.py):

    NAME = "warnings"
    DESCRIPTION = "..."
    VERSION = "1.0"
    CODEPOINTS = {0x26A0: "EMOJI"}
    RANGES = [(0x1F300, 0x1F5FF)]
    SETS = {"TEXT_DEFAULT_BMP": {0x26A0}}

Format pluginu zamienników (.json):

    {
      "name": "warnings",
      "replacements": {
        "⚠": {"rec": "🚨", "alt": ["❗"], "why": "..."}
      }
    }

Format pluginu zamienników (.py):

    NAME = "warnings"
    REPLACEMENTS = {"⚠": {"rec": "🚨", "alt": ["❗"], "why": "..."}}

Wynik `load_plugins()`:

    {
      "codepoints": {0xFE0F: "VS16", ...},
      "ranges":     [(0x1F300, 0x1F5FF), ...],
      "sets":       {"EMOJI_DEFAULT_BMP": {0x26A1, ...}, ...},
      "warnings":   ["duplikat U+26A0 w 30_... i 40_..."],
      "loaded":     ["00_modifiers.json", "10_emoji_ranges.json", ...],
    }

Wynik `load_replacements()`:

    {
      "replacements": {"⚠": {"rec": "🚨", "alt": [...], "why": "..."}, ...},
      "warnings":     [...],
      "loaded":       [...],
    }

Historia zmian:

  **v1.1**

  * `_merge_replacements` — **normalizacja kluczy**. Klucze zamienników
    są zawsze **bazowe** (pierwszy codepoint, bez VS16/VS15/ZWJ/KEYCAP).
    Jeśli plugin ma klucz `"✓️"` (z VS16), loader zapisuje go jako `"✓"`
    i dopisuje ostrzeżenie. Zapobiega to sytuacji, w której ten sam
    znak istnieje w pluginie pod dwiema postaciami (z i bez modyfikatora)
    — co wcześniej powodowało duplikaty w propozycjach `_proposals_for`.
  * Duplikat po normalizacji (np. `"✓"` i `"✓️"` w tym samym pluginie)
    jest wykrywany i raportowany jako ostrzeżenie — pierwszy wygrywa.

  **v1.0** — wersja początkowa.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

# ── ścieżki domyślne ────────────────────────────────────────────
# `DEFAULT_PLUGINS_ROOT` wskazuje na katalog pakietu `emoji/`,
# w którym znajdują się podfoldery `wykrywanie/` i `zamienniki/`.
# Re-eksport w `emoji/__init__.py` — reszta to detale wewnętrzne.
_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_PLUGINS_ROOT = _PKG_DIR
DEFAULT_DETECTION_DIR = _PKG_DIR / "wykrywanie"
DEFAULT_REPLACEMENTS_DIR = _PKG_DIR / "zamienniki"


# ── kody modyfikatorów (do normalizacji kluczy) ─────────────────
_MODIFIER_CPS = frozenset({0xFE0F, 0xFE0E, 0x200D, 0x20E3})


# ── pomocnicze: parsowanie i normalizacja ───────────────────────

def _parse_cp(value: Any) -> int | None:
    """
    Zamienia reprezentację codepointu na int.

    Akceptuje:
      * int (0..0x10FFFF),
      * "U+26A0" / "u+26a0",
      * "26A0" / "1F300" (bez prefiksu).

    Zwraca None dla wartości niepoprawnych lub poza zakresem Unicode.
    """
    if isinstance(value, bool):
        # bool jest podklasą int — świadomie odrzucamy, żeby uniknąć
        # traktowania True jako 1.
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 0x10FFFF else None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s[:2].upper() == "U+":
        s = s[2:]
    try:
        cp = int(s, 16)
    except ValueError:
        return None
    return cp if 0 <= cp <= 0x10FFFF else None


def _normalize_key(key: str) -> str:
    """
    Normalizuje klucz zamiennika do postaci bazowej.

    Bierze **pierwszy codepoint** klucza (bazowy znak), odrzuca
    wszystkie modyfikatory (VS16, VS15, ZWJ, KEYCAP) i inne znaki
    po nim. Dzięki temu klucz `"✓️"` (z VS16) staje się `"✓"`.

    Puste wejście → `""`.
    """
    if not key:
        return ""
    return key[0]


def _iter_plugin_files(directory: Path) -> list[Path]:
    """Zwraca posortowaną listę plików pluginów w `directory`."""
    if not directory.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("_"):
            continue
        if p.suffix.lower() not in (".json", ".py"):
            continue
        out.append(p)
    return out


def _load_py_module(path: Path):
    """
    Ładuje moduł Pythona z dowolnej ścieżki (bez sys.modules).

    Nazwa modułu jest unikalna (ścieżka + mtime), więc dwa pluginy
    o tej samej nazwie w różnych folderach nie kolidują.
    """
    try:
        mtime = int(path.stat().st_mtime_ns)
    except OSError:
        mtime = 0
    mod_name = f"_emoji_plugin_{path.stem}_{mtime % 1_000_000}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nie można utworzyć spec dla {path}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 — chcemy każdy błąd zaraportować
        raise RuntimeError(f"błąd wykonania {path.name}: {e}") from e
    return mod


# ── wczytywanie pojedynczego pluginu (surowe dane) ──────────────

def _load_detection_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cps: dict[int, str] = {}
    for entry in data.get("codepoints", []):
        cp = _parse_cp(entry.get("cp"))
        if cp is None:
            continue
        cps[cp] = str(entry.get("kind", "EMOJI"))

    ranges: list[tuple[int, int]] = []
    for entry in data.get("ranges", []):
        lo = _parse_cp(entry.get("start"))
        hi = _parse_cp(entry.get("end"))
        if lo is None or hi is None or lo > hi:
            continue
        ranges.append((lo, hi))

    sets: dict[str, set[int]] = {}
    for name, values in data.get("sets", {}).items():
        s = {cp for v in values if (cp := _parse_cp(v)) is not None}
        sets[name] = s

    return {"codepoints": cps, "ranges": ranges, "sets": sets}


def _load_detection_py(path: Path) -> dict:
    mod = _load_py_module(path)

    raw_cps = getattr(mod, "CODEPOINTS", {}) or {}
    cps: dict[int, str] = {}
    for k, v in raw_cps.items():
        cp = _parse_cp(k)
        if cp is not None:
            cps[cp] = str(v)

    ranges: list[tuple[int, int]] = []
    for entry in getattr(mod, "RANGES", []) or []:
        try:
            lo, hi = tuple(entry)
        except (TypeError, ValueError):
            continue
        lo_i = _parse_cp(lo)
        hi_i = _parse_cp(hi)
        if lo_i is None or hi_i is None or lo_i > hi_i:
            continue
        ranges.append((lo_i, hi_i))

    sets: dict[str, set[int]] = {}
    for name, values in (getattr(mod, "SETS", {}) or {}).items():
        s = {cp for v in values if (cp := _parse_cp(v)) is not None}
        sets[name] = s

    return {"codepoints": cps, "ranges": ranges, "sets": sets}


def _load_replacement_json(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return dict(data.get("replacements", {}))


def _load_replacement_py(path: Path) -> dict[str, dict]:
    mod = _load_py_module(path)
    return dict(getattr(mod, "REPLACEMENTS", {}) or {})


# ── scalanie z wykrywaniem duplikatów ───────────────────────────

def _merge_detection(state: dict, new: dict, source: str, warnings: list[str]) -> None:
    for cp, kind in new["codepoints"].items():
        if cp in state["codepoints"]:
            if state["codepoints"][cp] != kind:
                warnings.append(
                    f"{source}: duplikat U+{cp:04X} "
                    f"(już {state['codepoints'][cp]!r}, pomijam {kind!r})"
                )
        else:
            state["codepoints"][cp] = kind

    for rng in new["ranges"]:
        if rng in state["ranges"]:
            warnings.append(
                f"{source}: duplikat zakresu U+{rng[0]:04X}-U+{rng[1]:04X}"
            )
        else:
            state["ranges"].append(rng)

    for set_name, values in new["sets"].items():
        target = state["sets"].setdefault(set_name, set())
        for cp in values:
            if cp in target:
                warnings.append(
                    f"{source}: duplikat U+{cp:04X} w zbiorze {set_name}"
                )
            else:
                target.add(cp)


def _merge_replacements(
    state: dict[str, dict], new: dict[str, dict], source: str, warnings: list[str]
) -> None:
    """
    Scala wpisy zamienników z normalizacją kluczy.

    Klucz jest **zawsze bazowy** (pierwszy codepoint). Jeśli plugin
    ma klucz `"✓️"` (z VS16), zapisujemy go jako `"✓"` i dopisujemy
    ostrzeżenie. To zapobiega duplikatom w `_proposals_for`, gdzie
    ten sam znak pod dwiema postaciami trafiałby na listę dwa razy.

    Duplikat po normalizacji (np. `"✓"` i `"✓️"` w jednym pluginie,
    albo w dwóch różnych pluginach) — pierwszy wygrywa, reszta
    z ostrzeżeniem.
    """
    for key, value in new.items():
        if not key:
            continue

        base = _normalize_key(key)

        # Klucz miał modyfikator (VS16/VS15/ZWJ/KEYCAP) — normalizujemy.
        if base != key:
            warnings.append(
                f"{source}: klucz {key!r} ma modyfikator, używam {base!r}"
            )

        if base in state:
            warnings.append(
                f"{source}: duplikat zamiennika {base!r} (pomijam)"
            )
            continue

        if not isinstance(value, dict) or "rec" not in value:
            warnings.append(
                f"{source}: niepoprawny wpis dla {base!r} (brak 'rec')"
            )
            continue

        state[base] = value


# ── publiczne API ───────────────────────────────────────────────

def load_plugins(directory: Path | str | None = None) -> dict:
    """
    Ładuje wszystkie pluginy detekcji z podanego katalogu.

    Parametry:
        directory: ścieżka do folderu pluginów detekcji.
                   None → `emoji/wykrywanie/`.

    Zwraca dict z kluczami: `codepoints`, `ranges`, `sets`,
    `warnings`, `loaded`.
    """
    dir_path = Path(directory).resolve() if directory else DEFAULT_DETECTION_DIR

    state: dict = {
        "codepoints": {},
        "ranges": [],
        "sets": {},
        "warnings": [],
        "loaded": [],
    }

    if not dir_path.is_dir():
        state["warnings"].append(f"katalog pluginów nie istnieje: {dir_path}")
        return state

    for path in _iter_plugin_files(dir_path):
        try:
            if path.suffix.lower() == ".json":
                new = _load_detection_json(path)
            else:
                new = _load_detection_py(path)
        except (json.JSONDecodeError, RuntimeError, OSError) as e:
            state["warnings"].append(f"{path.name}: {e}")
            continue

        _merge_detection(state, new, path.name, state["warnings"])
        state["loaded"].append(path.name)

    return state


def load_replacements(directory: Path | str | None = None) -> dict:
    """
    Ładuje wszystkie pluginy zamienników z podanego katalogu.

    Klucze zamienników są **normalizowane** do bazowych (bez VS16
    itd.) — patrz `_merge_replacements`.

    Parametry:
        directory: ścieżka do folderu pluginów zamienników.
                   None → `emoji/zamienniki/`.

    Zwraca dict z kluczami: `replacements`, `warnings`, `loaded`.
    """
    dir_path = Path(directory).resolve() if directory else DEFAULT_REPLACEMENTS_DIR

    state: dict = {
        "replacements": {},
        "warnings": [],
        "loaded": [],
    }

    if not dir_path.is_dir():
        state["warnings"].append(f"katalog pluginów nie istnieje: {dir_path}")
        return state

    for path in _iter_plugin_files(dir_path):
        try:
            if path.suffix.lower() == ".json":
                new = _load_replacement_json(path)
            else:
                new = _load_replacement_py(path)
        except (json.JSONDecodeError, RuntimeError, OSError) as e:
            state["warnings"].append(f"{path.name}: {e}")
            continue

        _merge_replacements(state["replacements"], new, path.name, state["warnings"])
        state["loaded"].append(path.name)

    return state


# ── API dla generatora i `inspect` ──────────────────────────────

def load_detection_file(path: Path | str) -> dict:
    """Ładuje pojedynczy plik detekcji, zwraca znormalizowany dict."""
    p = Path(path)
    return _load_detection_json(p) if p.suffix.lower() == ".json" else _load_detection_py(p)


def load_replacement_file(path: Path | str) -> dict[str, dict]:
    """
    Ładuje pojedynczy plik zamienników, zwraca mapę replacements.

    **Uwaga:** klucze w zwróconej mapie **nie są** normalizowane —
    normalizacja odbywa się w `load_replacements` (przy scalaniu).
    Jeśli chcesz mieć bazowe klucze, użyj `load_replacements()`.
    """
    p = Path(path)
    return (
        _load_replacement_json(p)
        if p.suffix.lower() == ".json"
        else _load_replacement_py(p)
    )
