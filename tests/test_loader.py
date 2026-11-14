"""
Testy `emoji.loader`:
  * `_parse_cp` — parsowanie różnych formatów codepointów,
  * `_normalize_key` — normalizacja kluczy (VS16 → baza),
  * `load_plugins` — ładowanie .json/.py, pomijanie `_`/`README`,
  * `load_replacements` — normalizacja kluczy, duplikaty.
"""

from __future__ import annotations

import json

import pytest

from emoji.loader import (
    _normalize_key,
    _parse_cp,
    load_plugins,
    load_replacements,
)

# ════════════════════════════════════════════════════════════════
# _parse_cp
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    ("U+26A0", 0x26A0),
    ("u+26a0", 0x26A0),
    ("U+1F6E1", 0x1F6E1),
    ("26A0", 0x26A0),
    ("1F6E1", 0x1F6E1),
    (0x26A0, 0x26A0),
    (0x1F6E1, 0x1F6E1),
    ("  U+26A0  ", 0x26A0),  # z białymi znakami
])
def test_parse_cp_valid(value, expected):
    assert _parse_cp(value) == expected


@pytest.mark.parametrize("value", [
    "", "zle", "U+", "U+ZZZ", -1, 0x110000, None, [], {}, True, False,
])
def test_parse_cp_invalid(value):
    # True/False — bool jest podklasą int, ale _parse_cp go odrzuca
    assert _parse_cp(value) is None


# ════════════════════════════════════════════════════════════════
# _normalize_key
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("⚙", "⚙"),            # bez modyfikatora — bez zmian
    ("⚙️", "⚙"),           # z VS16 → baza
    ("✓️", "✓"),           # U+2713 + VS16 → U+2713
    ("⚠️", "⚠"),
    ("🔧", "🔧"),          # astralny — bez zmian
    ("🛡️", "🛡"),         # astralny + VS16 → baza
    ("", ""),               # puste
])
def test_normalize_key(raw, expected):
    assert _normalize_key(raw) == expected


# ════════════════════════════════════════════════════════════════
# load_plugins — pusty katalog, brak katalogu
# ════════════════════════════════════════════════════════════════

def test_load_plugins_nonexistent_dir(tmp_path):
    result = load_plugins(tmp_path / "nie_ma")
    assert result["codepoints"] == {}
    assert result["ranges"] == []
    assert result["sets"] == {}
    assert result["loaded"] == []
    assert len(result["warnings"]) == 1


def test_load_plugins_empty_dir(tmp_path):
    result = load_plugins(tmp_path)
    assert result["loaded"] == []
    assert result["warnings"] == []


# ════════════════════════════════════════════════════════════════
# load_plugins — .json
# ════════════════════════════════════════════════════════════════

def test_load_plugins_json(plugin_dir):
    result = load_plugins(plugin_dir / "wykrywanie")

    assert "00_test.json" in result["loaded"]
    assert result["sets"]["EMOJI_DEFAULT_BMP"] == {0x2705, 0x274C}
    assert result["sets"]["TEXT_DEFAULT_BMP"] == {0x26A0, 0x2699, 0x2713}
    assert result["sets"]["ASTRAL_TEXT_DEFAULT"] == {0x1F6E1}
    assert result["sets"]["FONT_RISKY_BMP"] == {0x26A1, 0x2B50}
    assert result["warnings"] == []


def test_load_plugins_skips_readme(plugin_dir):
    (plugin_dir / "wykrywanie" / "README.md").write_text("# docs")
    (plugin_dir / "wykrywanie" / "_private.json").write_text("{}")

    result = load_plugins(plugin_dir / "wykrywanie")

    assert "README.md" not in result["loaded"]
    assert "_private.json" not in result["loaded"]


# ════════════════════════════════════════════════════════════════
# load_plugins — .py
# ════════════════════════════════════════════════════════════════

def test_load_plugins_py(tmp_path):
    py_file = tmp_path / "01_test.py"
    py_file.write_text(
        'NAME = "py_test"\n'
        'CODEPOINTS = {0xFE0F: "VS16"}\n'
        'RANGES = [(0x1F300, 0x1F5FF)]\n'
        'SETS = {"EMOJI_DEFAULT_BMP": {0x2705}}\n'
    )

    result = load_plugins(tmp_path)

    assert "01_test.py" in result["loaded"]
    assert result["codepoints"] == {0xFE0F: "VS16"}
    assert result["ranges"] == [(0x1F300, 0x1F5FF)]
    assert result["sets"]["EMOJI_DEFAULT_BMP"] == {0x2705}


# ════════════════════════════════════════════════════════════════
# load_plugins — duplikaty (pierwszy wygrywa)
# ════════════════════════════════════════════════════════════════

def test_load_plugins_duplicate_first_wins(tmp_path):
    (tmp_path / "00_a.json").write_text(json.dumps({
        "name": "a",
        "sets": {"TEXT_DEFAULT_BMP": ["U+26A0"]},
    }))
    (tmp_path / "01_b.json").write_text(json.dumps({
        "name": "b",
        "sets": {"TEXT_DEFAULT_BMP": ["U+26A0", "U+2699"]},
    }))

    result = load_plugins(tmp_path)

    # U+26A0 z a (pierwszy), U+2699 z b (nowy)
    assert result["sets"]["TEXT_DEFAULT_BMP"] == {0x26A0, 0x2699}
    assert any("duplikat U+26A0" in w for w in result["warnings"])


# ════════════════════════════════════════════════════════════════
# load_plugins — zepsuty JSON
# ════════════════════════════════════════════════════════════════

def test_load_plugins_broken_json(tmp_path):
    (tmp_path / "00_bad.json").write_text("{nie json")
    (tmp_path / "01_ok.json").write_text(json.dumps({
        "name": "ok",
        "sets": {"EMOJI_DEFAULT_BMP": ["U+2705"]},
    }))

    result = load_plugins(tmp_path)

    assert "01_ok.json" in result["loaded"]
    assert "00_bad.json" not in result["loaded"]
    assert result["sets"]["EMOJI_DEFAULT_BMP"] == {0x2705}
    assert any("00_bad.json" in w for w in result["warnings"])


# ════════════════════════════════════════════════════════════════
# load_replacements — normalizacja kluczy
# ════════════════════════════════════════════════════════════════

def test_load_replacements_normalizes_keys(tmp_path):
    """Klucz z VS16 → baza. Bez tego _proposals_for duplikuje."""
    (tmp_path / "10_test.json").write_text(json.dumps({
        "name": "test",
        "replacements": {
            "✓️": {"rec": "✅", "alt": [], "why": "test"},  # z VS16
        },
    }, ensure_ascii=False))

    result = load_replacements(tmp_path)

    assert "✓" in result["replacements"]
    assert "✓️" not in result["replacements"]
    assert any("modyfikator" in w for w in result["warnings"])


def test_load_replacements_duplicate_first_wins(tmp_path):
    """Dwa pluginy z tym samym kluczem → pierwszy wygrywa."""
    (tmp_path / "10_a.json").write_text(json.dumps({
        "name": "a",
        "replacements": {"⚡": {"rec": "🔋", "alt": [], "why": "a"}},
    }, ensure_ascii=False))
    (tmp_path / "20_b.json").write_text(json.dumps({
        "name": "b",
        "replacements": {"⚡": {"rec": "🚀", "alt": [], "why": "b"}},
    }, ensure_ascii=False))

    result = load_replacements(tmp_path)

    assert result["replacements"]["⚡"]["rec"] == "🔋"  # z a
    assert any("duplikat" in w for w in result["warnings"])


def test_load_replacements_preserves_alt_and_why(tmp_path):
    (tmp_path / "10_test.json").write_text(json.dumps({
        "name": "test",
        "replacements": {
            "⚡": {"rec": "🔋", "alt": ["🔌", "💡"], "why": "test"},
        },
    }, ensure_ascii=False))

    result = load_replacements(tmp_path)

    entry = result["replacements"]["⚡"]
    assert entry["rec"] == "🔋"
    assert entry["alt"] == ["🔌", "💡"]
    assert entry["why"] == "test"


# ════════════════════════════════════════════════════════════════
# load_replacements — pusty katalog, brak katalogu
# ════════════════════════════════════════════════════════════════

def test_load_replacements_nonexistent_dir(tmp_path):
    result = load_replacements(tmp_path / "nie_ma")
    assert result["replacements"] == {}
    assert len(result["warnings"]) == 1


def test_load_replacements_empty_dir(tmp_path):
    result = load_replacements(tmp_path)
    assert result["replacements"] == {}
    assert result["warnings"] == []
