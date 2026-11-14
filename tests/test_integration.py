"""
Testy integracyjne — end-to-end.

Sprawdzają, że komponenty współpracują:
  * plugin .json → loader → scan → reporter → output,
  * wizard → generator → loader → scan,
  * pełny przepływ: dodaj emoji przez generator, potem skanuj.

Fixture `_make_project` zawiera **wszystkie** potrzebne `ranges`
i `codepoints` (w tym VS16), żeby testy nie zależały od wersji wcwidth
ani od prawdziwych pluginów z repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from emoji.generator import (
    add_emoji_to_plugin,
    add_replacement_to_plugin,
    create_detection_plugin,
    update_replacement_in_plugin,
)
from emoji.loader import load_plugins, load_replacements
from emoji.reporter import _verdict_of, print_report, print_summary
from emoji.scanner import scan

# ════════════════════════════════════════════════════════════════
# Fixture: minimalny projekt
# ════════════════════════════════════════════════════════════════

def _make_project(tmp_path: Path) -> dict:
    """
    Tworzy strukturę:
      tmp/
        wykrywanie/00_test.json
        zamienniki/10_test.json
        src/test.rs          ← plik do skanowania

    Zawartość:
      * ranges pokrywają: ✅ ⚡ ⚠ 🛡 🔧 🚀 🧪 🕷 (wszystkie z testów),
      * codepoints: VS16 (dla --vs16),
      * sets:
          EMOJI_DEFAULT_BMP: ✅ ⚡ (⚡ w OBU: default + risky)
          TEXT_DEFAULT_BMP:  ⚠
          ASTRAL_TEXT_DEFAULT: 🛡
          FONT_RISKY_BMP:    ⚡

    Dzięki EMOJI_DEFAULT_BMP z U+26A1:
      ⚡ ma heurystykę=2, więc (przy wcwidth=2) rozjazd=False,
      font_risky=True → werdykt FONT_RISK (nie ROZJAZD).

    Przy starszym wcwidth (wcwidth=1) rozjazd=True → werdykt ROZJAZD.
    Testy akceptują oba wyniki.
    """
    det = tmp_path / "wykrywanie"
    rep = tmp_path / "zamienniki"
    src = tmp_path / "src"
    det.mkdir()
    rep.mkdir()
    src.mkdir()

    (det / "00_test.json").write_text(json.dumps({
        "name": "test_detection",
        "description": "Test plugin (integration)",
        "version": "1.0",
        "codepoints": [
            {"cp": "U+FE0F", "kind": "VS16", "label": "Variation Selector-16"},
            {"cp": "U+FE0E", "kind": "VS15", "label": "Variation Selector-15"},
        ],
        "ranges": [
            {"start": "U+2600",  "end": "U+27BF",  "kind": "EMOJI"},  # ✅ ⚡ ⚠
            {"start": "U+1F300", "end": "U+1F5FF", "kind": "EMOJI"},  # 🔧
            {"start": "U+1F680", "end": "U+1F6FF", "kind": "EMOJI"},  # 🛡 🚀
            {"start": "U+1F900", "end": "U+1F9FF", "kind": "EMOJI"},  # 🧪
        ],
        "sets": {
            "EMOJI_DEFAULT_BMP": ["U+2705", "U+26A1"],  # ✅ ⚡
            "TEXT_DEFAULT_BMP":  ["U+26A0"],             # ⚠
            "ASTRAL_TEXT_DEFAULT": ["U+1F6E1"],          # 🛡
            "FONT_RISKY_BMP": ["U+26A1"],                # ⚡
        },
    }, ensure_ascii=False), encoding="utf-8")

    (rep / "10_test.json").write_text(json.dumps({
        "name": "test_replacements",
        "replacements": {
            "⚡": {"rec": "🔋", "alt": ["🔌"], "why": "test"},
            "⚠": {"rec": "🚨", "alt": ["❗"], "why": "test"},
            "🛡": {"rec": "🔰", "alt": [], "why": "test"},
        },
    }, ensure_ascii=False), encoding="utf-8")

    (src / "test.rs").write_text('let x = "✅⚡⚠🛡🔧";\n', encoding="utf-8")

    return {"det": det, "rep": rep, "src": src, "file": src / "test.rs"}


def _verdict_ch(result: dict) -> dict[str, str]:
    """Mapuj ch → werdykt (jeden na znalezisko)."""
    return {r["ch"]: _verdict_of(r) for r in result["results"]}


# ════════════════════════════════════════════════════════════════
# 1. Pełny przepływ: plugin → loader → scan → werdykty
# ════════════════════════════════════════════════════════════════

def test_full_pipeline_plugin_to_verdicts(tmp_path):
    p = _make_project(tmp_path)
    det_data = load_plugins(p["det"])
    rep_data = load_replacements(p["rep"])

    assert len(det_data["loaded"]) == 1
    assert len(rep_data["loaded"]) == 1
    assert det_data["warnings"] == []
    assert rep_data["warnings"] == []

    result = scan(p["file"], det_data)
    assert len(result["results"]) == 5
    assert result["errors"] == []

    v = _verdict_ch(result)

    # ✅ — EMOJI_DEFAULT_BMP, astralny nie, BMP default (Emoji_Pres=Yes)
    assert v["✅"] == "OK"

    # ⚡ — FONT_RISK (wcwidth=2) lub ROZJAZD (wcwidth=1)
    assert v["⚡"] in ("FONT_RISK", "ROZJAZD"), f"⚡ → {v['⚡']}"

    # ⚠ — TEXT_DEFAULT_BMP, bez VS16 → MAŁA
    assert v["⚠"] == "MAŁA"

    # 🛡 — ASTRAL_TEXT_DEFAULT (FRAGILE) + wcwidth=1 (ROZJAZD).
    # _verdict_of zwraca ROZJAZD (wyższy priorytet), bo wcwidth kłamie.
    # Akceptujemy oba — zależy od wersji wcwidth i priorytetu werdyktów.
    assert v["🛡"] in ("FRAGILE", "ROZJAZD"), f"🛡 → {v['🛡']}"

    # 🔧 — astralny (>U+FFFF) → OK
    assert v["🔧"] == "OK"


def test_full_pipeline_with_replacements(tmp_path):
    p = _make_project(tmp_path)
    det_data = load_plugins(p["det"])
    rep_data = load_replacements(p["rep"])
    result = scan(p["file"], det_data)
    replacements = rep_data["replacements"]

    for r in result["results"]:
        v = _verdict_of(r)
        if v in ("ROZJAZD", "MAŁA", "FRAGILE", "FONT_RISK"):
            assert r["ch"] in replacements, (
                f"brak zamiennika dla {r['ch']!r} (werdykt: {v})"
            )


# ════════════════════════════════════════════════════════════════
# 2. Print summary / print report
# ════════════════════════════════════════════════════════════════

def test_print_summary_shows_all_sections(tmp_path, capsys):
    p = _make_project(tmp_path)
    det_data = load_plugins(p["det"])
    rep_data = load_replacements(p["rep"])
    result = scan(p["file"], det_data)

    print_summary(
        result["results"],
        rep_data["replacements"],
        has_wcwidth=True,
    )
    out = capsys.readouterr().out

    # Sekcja 1: ranking
    assert "── PODSUMOWANIE ZNALEZISK ──" in out
    assert "'⚡'" in out
    assert "'⚠'" in out
    assert "'🛡'" in out

    # Sekcja 2: porównanie metod
    assert "── PORÓWNANIE METOD ──" in out
    assert "ROZJAZD:" in out
    assert "MAŁA (text):" in out
    assert ("FRAGILE:" in out) or ("ROZJAZD:" in out)
    # FONT_RISK: lub ROZJAZD: — zależnie od wcwidth
    assert ("FONT_RISK:" in out) or ("ROZJAZD:      1" in out)

    # Sekcja 3: propozycje
    assert "── PROPONOWANE ZMIANY ──" in out
    assert "🔋" in out
    assert "🚨" in out
    assert "🔰" in out


def test_print_report_full_output(tmp_path, capsys):
    p = _make_project(tmp_path)
    det_data = load_plugins(p["det"])
    rep_data = load_replacements(p["rep"])
    result = scan(p["file"], det_data)

    print_report(result["results"], rep_data["replacements"])
    out = capsys.readouterr().out

    for ch in ["✅", "⚡", "⚠", "🛡", "🔧"]:
        assert ch in out

    # Werdykty (⚡/🛡 mogą być FONT_RISK/FRAGILE lub ROZJAZD
    # — zależy od wersji wcwidth i priorytetu werdyktów)
    assert ("FONT_RISK" in out) or ("ROZJAZD" in out)
    assert "MAŁA" in out
    assert ("FRAGILE" in out) or ("ROZJAZD" in out)


# ════════════════════════════════════════════════════════════════
# 3. Wizard flow: add → load → scan
# ════════════════════════════════════════════════════════════════

def test_wizard_add_then_scan(tmp_path):
    p = _make_project(tmp_path)
    target = p["det"] / "00_test.json"

    res = add_emoji_to_plugin(target, 0x1F9EA, "EMOJI_DEFAULT_BMP")  # 🧪
    assert res["ok"] is True
    assert res["changed"] is True

    new_file = p["src"] / "with_test_tube.rs"
    new_file.write_text('let x = "🧪";\n', encoding="utf-8")

    det_data = load_plugins(p["det"])
    result = scan(new_file, det_data)

    assert len(result["results"]) == 1
    assert result["results"][0]["ch"] == "🧪"
    assert _verdict_of(result["results"][0]) == "OK"


def test_wizard_add_replacement_then_scan(tmp_path):
    p = _make_project(tmp_path)
    target = p["rep"] / "10_test.json"

    res = add_replacement_to_plugin(target, "✗", "❌", ["[x]"], "test")
    assert res["ok"] is True

    new_file = p["src"] / "with_x.rs"
    new_file.write_text('let x = "✗";\n', encoding="utf-8")

    det_data = load_plugins(p["det"])
    rep_data = load_replacements(p["rep"])
    result = scan(new_file, det_data)

    assert len(result["results"]) == 1
    assert result["results"][0]["ch"] == "✗"
    assert "✗" in rep_data["replacements"]
    assert rep_data["replacements"]["✗"]["rec"] == "❌"


# ════════════════════════════════════════════════════════════════
# 4. Create → add → scan → update → scan
# ════════════════════════════════════════════════════════════════

def test_create_update_scan_cycle(tmp_path):
    p = _make_project(tmp_path)

    res = create_detection_plugin(
        "cycle", directory=p["det"], prefix="50_",
    )
    assert res["created"] is True
    new_det = Path(res["path"])

    add_emoji_to_plugin(new_det, 0x1F680, "EMOJI_DEFAULT_BMP")  # 🚀

    f = p["src"] / "with_rocket.rs"
    f.write_text('let x = "🚀";\n', encoding="utf-8")

    det_data = load_plugins(p["det"])
    result = scan(f, det_data)

    assert len(result["results"]) == 1
    assert result["results"][0]["ch"] == "🚀"
    assert _verdict_of(result["results"][0]) == "OK"

    rep_target = p["rep"] / "10_test.json"
    upd = update_replacement_in_plugin(
        rep_target, "⚡", alt=["🔌", "🎯"], append_alt=True,
    )
    assert upd["ok"] is True
    assert upd["changed"] is True

    rep_data = load_replacements(p["rep"])
    assert rep_data["replacements"]["⚡"]["alt"] == ["🔌", "🎯"]


# ════════════════════════════════════════════════════════════════
# 5. Idempotencja + error handling
# ════════════════════════════════════════════════════════════════

def test_scan_repeated_is_stable(tmp_path):
    p = _make_project(tmp_path)
    det_data = load_plugins(p["det"])

    r1 = scan(p["file"], det_data)
    r2 = scan(p["file"], det_data)

    assert len(r1["results"]) == len(r2["results"])
    for a, b in zip(r1["results"], r2["results"], strict=False):
        assert a["ch"] == b["ch"]
        assert a["cp"] == b["cp"]
        assert _verdict_of(a) == _verdict_of(b)


def test_broken_plugin_skipped_rest_works(tmp_path):
    p = _make_project(tmp_path)
    (p["det"] / "01_broken.json").write_text("{ nie json }")

    det_data = load_plugins(p["det"])

    assert "01_broken.json" not in det_data["loaded"]
    assert "00_test.json" in det_data["loaded"]
    assert len(det_data["warnings"]) == 1

    result = scan(p["file"], det_data)
    assert len(result["results"]) == 5


# ════════════════════════════════════════════════════════════════
# 6. --vs16 filter (end-to-end) — po fixie w scanner.py
# ════════════════════════════════════════════════════════════════

def test_scan_only_vs16_end_to_end(tmp_path):
    """
    --vs16 → tylko klastry zawierające VS16 (np. ⚙️ = ⚙ + FE0F).

    Po fixie w scanner.py: filtruje po `cluster_kinds` (bazowy +
    modyfikatory), a nie tylko po kind bazowego.
    """
    p = _make_project(tmp_path)

    f = p["src"] / "with_vs16.rs"
    f.write_text('let x = "⚙️ ✅";\n', encoding="utf-8")

    det_data = load_plugins(p["det"])
    result = scan(f, det_data, only_kinds={"VS16"})

    assert len(result["results"]) == 1, (
        f"oczekiwano 1 (⚙️), jest {len(result['results'])}"
    )
    r = result["results"][0]
    assert r["ch"] == "⚙"
    assert "️" in r["cluster"]  # VS16 w klastrze


# ════════════════════════════════════════════════════════════════
# 7. Katalog z wieloma plikami
# ════════════════════════════════════════════════════════════════

def test_scan_directory_multiple_files(tmp_path):
    p = _make_project(tmp_path)

    (p["src"] / "a.rs").write_text('"✅⚡"\n', encoding="utf-8")
    (p["src"] / "b.rs").write_text('"⚠🛡"\n', encoding="utf-8")
    (p["src"] / "c.rs").write_text('"🔧"\n', encoding="utf-8")

    det_data = load_plugins(p["det"])
    result = scan(p["src"], det_data)

    assert result["files_scanned"] == 4  # 3 nowe + test.rs
    # test.rs: 5 (✅ ⚡ ⚠ 🛡 🔧)
    # a.rs: 2, b.rs: 2, c.rs: 1 → razem 10
    assert len(result["results"]) == 10

    files_with_findings = {r["file"] for r in result["results"]}
    assert len(files_with_findings) == 4
