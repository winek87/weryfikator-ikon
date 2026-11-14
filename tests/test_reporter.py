"""
Testy `emoji.reporter`:
  * `suggest_for` — sugestia dla znaku,
  * `_verdict_of` — werdykt z wyniku skanu,
  * `_proposals_for` — propozycje z rec/alt/rodzeństwa/pad,
  * `print_summary` — sekcje (bez porównania pełnego outputu).
"""

from __future__ import annotations

from emoji.reporter import (
    _proposals_for,
    _verdict_of,
    print_summary,
    suggest_for,
)

# ════════════════════════════════════════════════════════════════
# suggest_for
# ════════════════════════════════════════════════════════════════

def test_suggest_for_known(basic_replacements):
    s = suggest_for("⚡", "EMOJI", basic_replacements)
    assert s["rec"] == "🔋"
    assert s["alt"] == ["🔌"]


def test_suggest_for_modifier():
    s = suggest_for("\uFE0F", "VS16")
    assert s["rec"] == "(usuń)"


def test_suggest_for_unknown_bmp():
    """
    § (U+00A7) — BMP, nie ma wpisu w pluginie.

    Oczekiwane:
      * rec=None (nie ma rekomendacji),
      * alt zawiera "[?]" i "dodaj wpis w pluginie".

    Uwaga: wcześniej sprawdzaliśmy "usuń VS16", ale to było mylące —
    § nie ma VS16, nie ma czego usuwać. Komunikat zmieniony w reporter.py v3.6.
    """
    s = suggest_for("§", "EMOJI", {})
    assert s["rec"] is None
    assert "[?]" in s["alt"]
    assert any("dodaj wpis" in a for a in s["alt"])


def test_suggest_for_unknown_bmp_various():
    """Inne BMP poniżej U+2000 — też powinny dostać rec=None."""
    for ch in ["©", "®", "°", "€", "™"]:
        s = suggest_for(ch, "EMOJI", {})
        assert s["rec"] is None, f"{ch!r} powinno mieć rec=None"
        assert "[?]" in s["alt"], f"{ch!r} powinno mieć [?] w alt"


def test_suggest_for_astral_no_entry():
    """🔧 — astralny, brak wpisu → rec=ch (prawdopodobnie OK)."""
    s = suggest_for("🔧", "EMOJI", {})
    assert s["rec"] == "🔧"
    assert s["alt"] == []


def test_suggest_for_unknown_astral():
    s = suggest_for("🧪", "EMOJI", {})
    assert s["rec"] == "🧪"
    assert s["alt"] == []


def test_suggest_for_empty():
    assert suggest_for("", "EMOJI") is None


# ════════════════════════════════════════════════════════════════
# _verdict_of
# ════════════════════════════════════════════════════════════════

def _result(**overrides):
    """Pomocnik: minimalny wynik skanu z nadpisanymi polami."""
    base = {
        "rozjazd": False,
        "text_default": False,
        "fragile": False,
        "fragile_no_vs16": False,
        "fragile_with_vs16": False,
        "font_risky": False,
        "fragile_mode": "simple",
        "wcwidth": 2,
    }
    base.update(overrides)
    return base


def test_verdict_ok():
    assert _verdict_of(_result()) == "OK"


def test_verdict_rozjazd():
    assert _verdict_of(_result(rozjazd=True)) == "ROZJAZD"


def test_verdict_mala():
    assert _verdict_of(_result(text_default=True)) == "MAŁA"


def test_verdict_fragile():
    assert _verdict_of(_result(fragile=True)) == "FRAGILE"


def test_verdict_font_risk():
    assert _verdict_of(_result(font_risky=True)) == "FONT_RISK"


def test_verdict_priority_rozjazd_over_font_risk():
    """ROZJAZD ma wyższy priorytet niż FONT_RISK."""
    r = _result(rozjazd=True, font_risky=True)
    assert _verdict_of(r) == "ROZJAZD"


def test_verdict_priority_mala_over_font_risk():
    r = _result(text_default=True, font_risky=True)
    assert _verdict_of(r) == "MAŁA"


def test_verdict_brak_wcwidth():
    assert _verdict_of(_result(wcwidth=None)) == "BRAK_WCWIDTH"


# ════════════════════════════════════════════════════════════════
# _proposals_for
# ════════════════════════════════════════════════════════════════

def test_proposals_basic(basic_replacements):
    props = _proposals_for("⚡", "EMOJI", basic_replacements)
    values = [v for v, _ in props]
    assert "🔋" in values
    assert "🔌" in values
    # pad do 5
    assert len(props) == 5
    assert props[-1][0] == "[?]"


def test_proposals_no_target(basic_replacements):
    """target=None → wszystkie, bez pada."""
    props = _proposals_for("⚡", "EMOJI", basic_replacements, target=None)
    values = [v for v, _ in props]
    assert "🔋" in values
    assert "🔌" in values
    assert "[?]" not in values


def test_proposals_dedupe(basic_replacements):
    """Ten sam znak nie pojawia się dwa razy."""
    reps = {
        "⚡": {"rec": "🔋", "alt": ["🔌", "🔌"], "why": ""},
    }
    props = _proposals_for("⚡", "EMOJI", reps, target=None)
    values = [v for v, _ in props]
    assert values.count("🔌") == 1


def test_proposals_skip_self():
    """Nie proponujemy tego samego znaku."""
    reps = {
        "⚡": {"rec": "⚡", "alt": ["🔋"], "why": ""},
    }
    props = _proposals_for("⚡", "EMOJI", reps, target=None)
    values = [v for v, _ in props]
    assert "⚡" not in values


def test_proposals_bad_chars_filters_siblings():
    """Rodzeństwo z bad_chars → pominięte, alt przechodzi."""
    reps = {
        "✓": {"rec": "✅", "alt": ["[v]"], "why": ""},
        "✔": {"rec": "✅", "alt": ["[X]"], "why": ""},
    }
    bad = {"✔"}
    props = _proposals_for("✓", "EMOJI", reps, target=None, bad_chars=bad)
    values = [v for v, _ in props]
    assert "✔" not in values
    assert "[X]" in values  # alt rodzeństwa przechodzi


def test_proposals_no_replacements():
    props = _proposals_for("⚡", "EMOJI", None)
    assert props == [("[?]", "wpisz własny")]


# ════════════════════════════════════════════════════════════════
# print_summary — smoke test (sprawdza, że nie wywala)
# ════════════════════════════════════════════════════════════════

def test_print_summary_empty(basic_replacements, capsys):
    print_summary([], basic_replacements)
    captured = capsys.readouterr()
    assert "Brak znalezisk" in captured.out


def test_print_summary_basic(basic_replacements, capsys):
    results = [{
        "file": "test.rs", "line": 1, "col": 1,
        "ch": "⚡", "cp": "U+26A1", "kind": "EMOJI",
        "rozjazd": False, "text_default": False,
        "fragile": False, "fragile_no_vs16": False,
        "fragile_with_vs16": False, "font_risky": True,
        "fragile_mode": "simple",
        "wcwidth": 2, "heurystyka": 2, "cluster": "⚡", "context": "",
    }]
    print_summary(results, basic_replacements)
    captured = capsys.readouterr()
    assert "PODSUMOWANIE ZNALEZISK" in captured.out
    assert "FONT_RISK" in captured.out
    assert "PROPONOWANE ZMIANY" in captured.out
