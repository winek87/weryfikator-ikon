"""
Fixtures współdzielone przez wszystkie testy.

Zasady:
  * każdy test dostaje własny `tmp_path` (pytest), żeby nie zaśmiecać repo,
  * `plugin_dir` — katalog z minimalnym zestawem pluginów (detekcja + zamienniki),
  * `basic_detection` — dict z `codepoints`, `ranges`, `sets` — **kompletny**
    (bez tego `classify()` nie rozpozna znaków: `sets` są używane dopiero
    w `measure_both`, a `classify` patrzy tylko na `codepoints` i `ranges`),
  * `basic_replacements` — dict z `replacements` (kilka znaków).

Dzięki temu testy nie zależą od zawartości `emoji/wykrywanie/*.json`
(która może się zmieniać).

Historia zmian:

  **v1.1**

  * `basic_detection` — dodane `ranges`. Bez tego `scan()` nie znajdował
    żadnych emoji, bo `classify()` sprawdza `codepoints` i `ranges`,
    a `sets` dopiero w `measure_both`. Testy `test_scan_synthetic_file`
    i `test_scan_error_handling` padały z `0 == 1`/`0 == 3`.
  * `plugin_dir` — dodane `ranges` do `00_test.json` (ten sam powód).
  * `plugin_dir` — `zamienniki/10_test.json` bez zmian, ale z komentarzem.

  **v1.0** — wersja początkowa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── ścieżka do prawdziwych pluginów (dla testów integracyjnych) ─
REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DETECTION_DIR = REPO_ROOT / "emoji" / "wykrywanie"
REAL_REPLACEMENTS_DIR = REPO_ROOT / "emoji" / "zamienniki"


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """
    Minimalny katalog pluginów: `<tmp>/wykrywanie/` + `<tmp>/zamienniki/`.

    Zawiera:
      * `wykrywanie/00_test.json` — 4 zbiory (TEXT_DEFAULT_BMP,
        EMOJI_DEFAULT_BMP, ASTRAL_TEXT_DEFAULT, FONT_RISKY_BMP)
        + 3 zakresy Unicode,
      * `zamienniki/10_test.json` — 2 wpisy (⚡, ⚠).

    **Uwaga:** `ranges` są tu potrzebne, bo `scan()` wywołuje
    `classify()`, które sprawdza TYLKO `codepoints` i `ranges` —
    nie `sets`. Bez `ranges` skaner nie znajdzie żadnego emoji
    w pliku testowym.
    """
    det_dir = tmp_path / "wykrywanie"
    rep_dir = tmp_path / "zamienniki"
    det_dir.mkdir()
    rep_dir.mkdir()

    detection = {
        "name": "test_detection",
        "description": "Test plugin",
        "version": "1.0",
        "codepoints": [],
        "ranges": [
            {"start": "U+2600", "end": "U+27BF", "kind": "EMOJI"},
            {"start": "U+1F300", "end": "U+1F5FF", "kind": "EMOJI"},
            {"start": "U+1F600", "end": "U+1F64F", "kind": "EMOJI"},
        ],
        "sets": {
            "EMOJI_DEFAULT_BMP": ["U+2705", "U+274C"],           # ✅ ❌
            "TEXT_DEFAULT_BMP":  ["U+26A0", "U+2699", "U+2713"], # ⚠ ⚙ ✓
            "ASTRAL_TEXT_DEFAULT": ["U+1F6E1"],                  # 🛡
            "FONT_RISKY_BMP": ["U+26A1", "U+2B50"],              # ⚡ ⭐
        },
    }
    (det_dir / "00_test.json").write_text(
        json.dumps(detection, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    replacements = {
        "name": "test_replacements",
        "replacements": {
            "⚡": {"rec": "🔋", "alt": ["🔌"], "why": "test"},
            "⚠": {"rec": "🚨", "alt": ["❗"], "why": "test"},
        },
    }
    (rep_dir / "10_test.json").write_text(
        json.dumps(replacements, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return tmp_path


@pytest.fixture
def basic_detection() -> dict:
    """
    Minimalny `detection_data` — bez ładowania pluginów z dysku.

    **Kompletny** (codepoints + ranges + sets), bo:
      * `classify()` sprawdza `codepoints` i `ranges`,
      * `measure_both()` sprawdza `sets`.

    Bez `ranges` testy `scan()` padają (skaner nie znajduje emoji,
    bo `classify` zwraca `None`).

    Zakresy pokrywają:
      * U+2600–U+27BF — ✅ ❌ ⚠ ⚙ ✓ ⚡ ⭐ (Misc Symbols, Dingbats),
      * U+1F300–U+1F5FF — 🔧 (Misc Symbols and Pictographs),
      * U+1F600–U+1F64F — buźki (na wszelki wypadek).
    """
    return {
        "codepoints": {},
        "ranges": [
            (0x2600, 0x27BF),
            (0x1F300, 0x1F5FF),
            (0x1F600, 0x1F64F),
        ],
        "sets": {
            "EMOJI_DEFAULT_BMP": {0x2705, 0x274C},
            "TEXT_DEFAULT_BMP":  {0x26A0, 0x2699, 0x2713},
            "ASTRAL_TEXT_DEFAULT": {0x1F6E1},
            "FONT_RISKY_BMP": {0x26A1, 0x2B50},
        },
    }


@pytest.fixture
def basic_replacements() -> dict:
    """Minimalny `replacements` — bez ładowania pluginów z dysku."""
    return {
        "⚡": {"rec": "🔋", "alt": ["🔌"], "why": "test"},
        "⚠": {"rec": "🚨", "alt": ["❗"], "why": "test"},
    }
