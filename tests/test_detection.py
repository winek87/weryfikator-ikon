"""
Testy `emoji.detection`:
  * `classify` — rozpoznawanie rodzaju znaku,
  * `measure_wcwidth` — pomiar wcwidth,
  * `measure_heuristic` — heurystyka Unicode,
  * `measure_both` — łączenie + werdykty (rozjazd, text_default, fragile, font_risky),
  * `is_font_risky` — pomocnicza.
"""

from __future__ import annotations

import pytest

from emoji.detection import (
    classify,
    is_font_risky,
    is_fragile_astral,
    is_modifier_cp,
    measure_both,
    measure_heuristic,
    measure_wcwidth,
)

# ════════════════════════════════════════════════════════════════
# classify
# ════════════════════════════════════════════════════════════════

def test_classify_vs16():
    assert classify("\uFE0F") == "VS16"


def test_classify_vs15():
    assert classify("\uFE0E") == "VS15"


def test_classify_zwj():
    assert classify("\u200D") == "ZWJ"


def test_classify_keycap():
    assert classify("\u20E3") == "KEYCAP"


def test_classify_emoji_in_range():
    ranges = [(0x1F300, 0x1F5FF)]
    assert classify("🔧", ranges=ranges) == "EMOJI"


def test_classify_emoji_via_codepoints():
    codepoints = {0x26A1: "EMOJI"}
    assert classify("⚡", codepoints=codepoints) == "EMOJI"


def test_classify_unknown():
    assert classify("a") is None
    assert classify("") is None


# ════════════════════════════════════════════════════════════════
# measure_wcwidth
# ════════════════════════════════════════════════════════════════

def test_measure_wcwidth_ascii():
    assert measure_wcwidth("a") == 1


def test_measure_wcwidth_astral():
    # astralne emoji default — zawsze 2 (w każdej wersji wcwidth)
    assert measure_wcwidth("🔧") == 2


# ════════════════════════════════════════════════════════════════
# measure_heuristic
# ════════════════════════════════════════════════════════════════

def test_measure_heuristic_vs16():
    """VS16 → 2 (emoji presentation)."""
    assert measure_heuristic("⚙️") == 2


def test_measure_heuristic_vs15():
    """VS15 → 1 (text presentation)."""
    assert measure_heuristic("⚙︎") == 1


def test_measure_heuristic_astral():
    """Astralne → 2."""
    assert measure_heuristic("🔧") == 2
    assert measure_heuristic("🛡") == 2


def test_measure_heuristic_emoji_default_bmp(basic_detection):
    """BMP w EMOJI_DEFAULT_BMP → 2."""
    assert measure_heuristic("✅", basic_detection["sets"]) == 2


def test_measure_heuristic_bmp_default(basic_detection):
    """BMP poza EMOJI_DEFAULT_BMP → 1."""
    assert measure_heuristic("⚙", basic_detection["sets"]) == 1


def test_measure_heuristic_empty():
    assert measure_heuristic("") == 0


# ════════════════════════════════════════════════════════════════
# measure_both — werdykty
# ════════════════════════════════════════════════════════════════

def test_measure_both_ok(basic_detection):
    """🔧 — astralne, nie w żadnym zbiorze problemowym → OK."""
    r = measure_both("🔧", basic_detection["sets"])
    assert r["rozjazd"] is False
    assert r["text_default"] is False
    assert r["fragile"] is False
    assert r["font_risky"] is False


def test_measure_both_text_default(basic_detection):
    """⚠ — BMP w TEXT_DEFAULT_BMP, bez VS16 → text_default=True."""
    r = measure_both("⚠", basic_detection["sets"])
    assert r["text_default"] is True
    assert r["rozjazd"] is False
    assert r["fragile"] is False


def test_measure_both_text_default_with_vs16(basic_detection):
    """⚠️ — z VS16 → text_default=False (bo VS16 obecny)."""
    r = measure_both("⚠️", basic_detection["sets"])
    assert r["text_default"] is False


def test_measure_both_rozjazd_relation(basic_detection):
    """
    Rozjazd = (wcwidth != heurystyka), gdy wcwidth znane.

    Nie zakładamy konkretnej wartości wcwidth — różne wersje
    biblioteki różnie obsługują VS16 (starsze: 1, nowsze: 2).
    Testujemy LOGIKĘ, nie konkretną wersję.
    """
    r = measure_both("⚙️", basic_detection["sets"])
    if r["wcwidth"] is not None:
        assert r["rozjazd"] == (r["wcwidth"] != r["heurystyka"])


def test_measure_both_fragile_astral(basic_detection):
    """🛡 — astralne w ASTRAL_TEXT_DEFAULT, bez VS16 → fragile=True."""
    r = measure_both("🛡", basic_detection["sets"])
    assert r["fragile"] is True
    assert r["fragile_no_vs16"] is True
    assert r["fragile_with_vs16"] is False


def test_measure_both_fragile_astral_with_vs16(basic_detection):
    """🛡️ — z VS16 → fragile_with_vs16=True."""
    r = measure_both("🛡️", basic_detection["sets"])
    assert r["fragile_no_vs16"] is False
    assert r["fragile_with_vs16"] is True


def test_measure_both_font_risky(basic_detection):
    """
    ⚡ — BMP w FONT_RISKY_BMP → font_risky=True.

    NIE sprawdzamy rozjazd — zależy od wersji wcwidth. U jednych
    wcwidth("⚡") zwraca 1 (rozjazd=True), u innych 2 (rozjazd=False).
    Oba przypadki są poprawne — testujemy tylko font_risky.
    """
    r = measure_both("⚡", basic_detection["sets"])
    assert r["font_risky"] is True
    assert r["text_default"] is False


def test_measure_both_font_risky_not_for_other(basic_detection):
    """🔧 — nie jest w FONT_RISKY_BMP → font_risky=False."""
    r = measure_both("🔧", basic_detection["sets"])
    assert r["font_risky"] is False


def test_measure_both_all_fields_present(basic_detection):
    """Sprawdza, że wynik ma wszystkie 9 pól (kontrakt)."""
    r = measure_both("⚡", basic_detection["sets"])
    assert set(r.keys()) == {
        "wcwidth", "heurystyka", "rozjazd", "text_default",
        "fragile", "fragile_no_vs16", "fragile_with_vs16",
        "fragile_mode", "font_risky",
    }


# ════════════════════════════════════════════════════════════════
# is_font_risky / is_fragile_astral
# ════════════════════════════════════════════════════════════════

def test_is_font_risky(basic_detection):
    assert is_font_risky("⚡", basic_detection["sets"]) is True
    assert is_font_risky("🔧", basic_detection["sets"]) is False
    assert is_font_risky("", basic_detection["sets"]) is False


def test_is_fragile_astral(basic_detection):
    assert is_fragile_astral("🛡", basic_detection["sets"]) is True
    assert is_fragile_astral("🔧", basic_detection["sets"]) is False
    assert is_fragile_astral("", basic_detection["sets"]) is False


# ════════════════════════════════════════════════════════════════
# is_modifier_cp
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cp,expected", [
    (0xFE0F, True),   # VS16
    (0xFE0E, True),   # VS15
    (0x200D, True),   # ZWJ
    (0x20E3, True),   # KEYCAP
    (0x26A1, False),  # ⚡
    (0x41, False),    # 'A'
])
def test_is_modifier_cp(cp, expected):
    assert is_modifier_cp(cp) is expected
