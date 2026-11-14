"""
Testy `emoji.scanner`:
  * `collect_files` — plik vs katalog, skip_dirs, skip_ext,
  * `iter_findings` — klastrowanie (bazowy + VS16/ZWJ),
  * `scan` — end-to-end z syntetycznym plikiem.
"""

from __future__ import annotations

from emoji.scanner import collect_files, iter_findings, scan

# ════════════════════════════════════════════════════════════════
# collect_files
# ════════════════════════════════════════════════════════════════

def test_collect_files_single_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    files, skipped = collect_files(f)
    assert files == [f]
    assert skipped == 0


def test_collect_files_directory(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("y")
    (tmp_path / "c.png").write_text("z")  # binarny, pomijany

    files, skipped = collect_files(tmp_path)

    names = {p.name for p in files}
    assert names == {"a.py", "b.py"}
    assert skipped == 1


def test_collect_files_skip_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "b.py").write_text("y")

    files, _ = collect_files(tmp_path)

    names = {p.name for p in files}
    assert names == {"a.py"}
    assert ".git" not in {p.parent.name for p in files}


def test_collect_files_custom_skip_ext(tmp_path):
    (tmp_path / "a.log").write_text("x")
    (tmp_path / "b.txt").write_text("y")

    files, skipped = collect_files(tmp_path, skip_ext={".log"})

    assert {p.name for p in files} == {"b.txt"}
    assert skipped == 1


def test_collect_files_nonexistent(tmp_path):
    files, skipped = collect_files(tmp_path / "nie_ma")
    assert files == []
    assert skipped == 0


# ════════════════════════════════════════════════════════════════
# iter_findings
# ════════════════════════════════════════════════════════════════

def test_iter_findings_single_emoji():
    codepoints = {0x2705: "EMOJI"}
    findings = list(iter_findings("x✅y", codepoints))
    assert len(findings) == 1
    col0, cluster, ch, kind = findings[0]
    assert col0 == 1
    assert cluster == "✅"
    assert ch == "✅"
    assert kind == "EMOJI"


def test_iter_findings_cluster_with_vs16():
    """⚙️ = U+2699 + U+FE0F — klaster."""
    codepoints = {0x2699: "EMOJI"}
    ranges = []
    findings = list(iter_findings("⚙️", codepoints, ranges))
    assert len(findings) == 1
    _, cluster, ch, kind = findings[0]
    assert cluster == "⚙️"
    assert ch == "⚙"
    assert kind == "EMOJI"


def test_iter_findings_two_emoji():
    codepoints = {0x2705: "EMOJI", 0x274C: "EMOJI"}
    findings = list(iter_findings("✅x❌", codepoints))
    assert len(findings) == 2


def test_iter_findings_no_emoji():
    findings = list(iter_findings("hello world", {}))
    assert findings == []


def test_iter_findings_orphan_vs16():
    """Samotny VS16 (bez bazowego) — powinien być znaleziony."""
    findings = list(iter_findings("a\uFE0F", {}))
    assert len(findings) == 1
    _, _, _, kind = findings[0]
    assert kind == "VS16"


# ════════════════════════════════════════════════════════════════
# scan — end-to-end
# ════════════════════════════════════════════════════════════════

def test_scan_synthetic_file(tmp_path, basic_detection):
    """Syntetyczny plik z 3 emoji: ✅ ⚠ 🔧."""
    f = tmp_path / "test.rs"
    f.write_text('let x = "✅";\nlet y = "⚠";\nlet z = "🔧";\n')

    result = scan(f, basic_detection)

    assert result["files_scanned"] == 1
    assert result["files_skipped"] == 0
    assert len(result["results"]) == 3

    # sprawdź, że każdy ma wszystkie pola
    for r in result["results"]:
        assert "font_risky" in r
        assert "fragile" in r
        assert "text_default" in r
        assert "rozjazd" in r


def test_scan_only_kinds_filter(tmp_path, basic_detection):
    """
    --vs16 → tylko klastry zawierające VS16.

    Po fixie w scanner.py (cluster_kinds): filtr sprawdza WSZYSTKIE
    kind w klastrze, nie tylko bazowego. Dla ⚙️ (U+2699+FE0F):
    kind = {"EMOJI", "VS16"} → łapie się na --vs16.

    Uwaga: `kind` w wyniku to kind BAZOWEGO znaku ("EMOJI" dla ⚙️),
    nie "VS16". Więc sprawdzamy po klastrze, nie po kind.
    """
    f = tmp_path / "test.rs"
    f.write_text("⚙️ ✅")  # klaster z VS16 + EMOJI bez VS16

    result = scan(f, basic_detection, only_kinds={"VS16"})

    # Powinien znaleźć dokładnie 1 (⚙️), bo ✅ nie ma VS16
    assert len(result["results"]) == 1, (
        f"oczekiwano 1 (⚙️), jest {len(result['results'])}"
    )

    r = result["results"][0]
    assert r["ch"] == "⚙"
    assert "\uFE0F" in r["cluster"]  # VS16 obecny w klastrze


def test_scan_error_handling(tmp_path, basic_detection):
    """Plik nieczytelny → wpis w errors, reszta działa."""
    good = tmp_path / "good.rs"
    good.write_text("✅")

    result = scan(good, basic_detection)
    assert result["errors"] == []
    assert len(result["results"]) == 1


def test_scan_empty_file(tmp_path, basic_detection):
    f = tmp_path / "empty.rs"
    f.write_text("")

    result = scan(f, basic_detection)
    assert result["results"] == []
    assert result["files_scanned"] == 1
