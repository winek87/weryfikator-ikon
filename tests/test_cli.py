"""
Testy CLI przez `subprocess`.

Każdy test uruchamia `scan_emoji.py` jako **osobny proces** — to
testuje integrację argparse + I/O + exit codes, czego nie da się
zbadać przez import.

Struktura `_make_project`:
    tmp/
      plugins/
        wykrywanie/00_test.json
        zamienniki/10_test.json
      src/
        ok.rs          ← tylko ✅ (bez problemów)
        warn.rs        ← ⚠ (MAŁA)
        vs16.rs        ← ⚙️ (klaster z VS16)
        skip.txt       ← do testu --skip-ext
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ── ścieżka do skryptu ──────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_SCRIPT = REPO_ROOT / "scan_emoji.py"


# ── pomocnik: uruchom CLI ───────────────────────────────────────
def _run(*args: str, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """
    Uruchamia `python scan_emoji.py <args>` i zwraca CompletedProcess.

    Timeout 30s — pojedyncze uruchomienie powinno trwać < 1s.
    """
    return subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd or REPO_ROOT),
    )


# ── fixture: minimalny projekt ─────────────────────────────────
def _make_project(tmp_path: Path) -> dict:
    """
    Tworzy:
      tmp/plugins/wykrywanie/00_test.json
      tmp/plugins/zamienniki/10_test.json
      tmp/src/ok.rs       ← ✅ (OK, --strict exit 0)
      tmp/src/warn.rs     ← ⚠ (MAŁA, --strict exit 2)
      tmp/src/vs16.rs     ← ⚙️ (klaster z VS16)
      tmp/src/skip.txt    ← do testu --skip-ext
    """
    plugins = tmp_path / "plugins"
    det = plugins / "wykrywanie"
    rep = plugins / "zamienniki"
    src = tmp_path / "src"
    det.mkdir(parents=True)
    rep.mkdir()
    src.mkdir()

    (det / "00_test.json").write_text(json.dumps({
        "name": "test_detection",
        "codepoints": [
            {"cp": "U+FE0F", "kind": "VS16"},
        ],
        "ranges": [
            {"start": "U+2600", "end": "U+27BF", "kind": "EMOJI"},
        ],
        "sets": {
            "EMOJI_DEFAULT_BMP": ["U+2705"],  # ✅
            "TEXT_DEFAULT_BMP":  ["U+26A0"],  # ⚠
        },
    }, ensure_ascii=False), encoding="utf-8")

    (rep / "10_test.json").write_text(json.dumps({
        "name": "test_replacements",
        "replacements": {
            "⚠": {"rec": "🚨", "alt": ["❗"], "why": "test"},
        },
    }, ensure_ascii=False), encoding="utf-8")

    (src / "ok.rs").write_text('let x = "✅";\n', encoding="utf-8")
    (src / "warn.rs").write_text('let x = "⚠";\n', encoding="utf-8")
    (src / "vs16.rs").write_text('let x = "⚙️";\n', encoding="utf-8")
    (src / "skip.txt").write_text('let x = "⚠";\n', encoding="utf-8")

    return {
        "plugins": str(plugins),
        "src": str(src),
        "ok": str(src / "ok.rs"),
        "warn": str(src / "warn.rs"),
        "vs16": str(src / "vs16.rs"),
        "skip_txt": str(src / "skip.txt"),
    }


# ════════════════════════════════════════════════════════════════
# 1. --version / --help
# ════════════════════════════════════════════════════════════════

def test_cli_version():
    r = _run("--version")
    assert r.returncode == 0
    assert "0.1.0" in (r.stdout + r.stderr)


def test_cli_help():
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "scan_emoji.py" in out or "Skaner emoji" in out
    assert "--strict" in out
    assert "--plugins-dir" in out


# ════════════════════════════════════════════════════════════════
# 2. Exit codes: --strict
# ════════════════════════════════════════════════════════════════

def test_cli_strict_no_problems(tmp_path):
    """Plik z ✅ (bez problemów) → --strict exit 0."""
    p = _make_project(tmp_path)
    r = _run(p["ok"], "--plugins-dir", p["plugins"], "--strict", "--quiet")
    assert r.returncode == 0, f"stderr: {r.stderr}"


def test_cli_strict_with_problems(tmp_path):
    """Plik z ⚠ (MAŁA) → --strict exit 2."""
    p = _make_project(tmp_path)
    r = _run(p["warn"], "--plugins-dir", p["plugins"], "--strict", "--quiet")
    assert r.returncode == 2, f"oczekiwano 2, jest {r.returncode}; stderr: {r.stderr}"
    assert "problemów do naprawy" in (r.stdout + r.stderr)


def test_cli_without_strict_returns_zero(tmp_path):
    """Bez --strict → zawsze 0 po udanym skanie (nawet z problemami)."""
    p = _make_project(tmp_path)
    r = _run(p["warn"], "--plugins-dir", p["plugins"], "--quiet")
    assert r.returncode == 0


# ════════════════════════════════════════════════════════════════
# 3. Błędy: zła ścieżka → exit 1
# ════════════════════════════════════════════════════════════════

def test_cli_nonexistent_path(tmp_path):
    p = _make_project(tmp_path)
    r = _run("/nie/ma/takiego/pliku", "--plugins-dir", p["plugins"])
    assert r.returncode == 1
    assert "nie istnieje" in (r.stdout + r.stderr)


# ════════════════════════════════════════════════════════════════
# 4. --quiet
# ════════════════════════════════════════════════════════════════

def test_cli_quiet_no_per_finding(tmp_path):
    """
    --quiet → bez raportu per-znalezisko (print_report).

    Uwaga: --quiet NIE wyłącza `PROPONOWANE ZMIANY` (to część
    print_summary). Sprawdzamy więc brak pełnego bloku per-znalezisko
    (`↳ wcwidth=`, `↳ zalecany:`), nie brak samego `:1:10`.
    """
    p = _make_project(tmp_path)
    r = _run(p["warn"], "--plugins-dir", p["plugins"], "--quiet")
    out = r.stdout + r.stderr
    # jest podsumowanie
    assert "PODSUMOWANIE ZNALEZISK" in out
    # NIE ma bloku per-znalezisko (to print_report, pomijany przez --quiet)
    assert "↳ wcwidth=" not in out, "print_report powinien być pominięty"
    assert "↳ zalecany:" not in out, "print_report powinien być pominięty"


def test_cli_no_quiet_has_per_finding(tmp_path):
    """Bez --quiet → raport per-znalezisko."""
    p = _make_project(tmp_path)
    r = _run(p["warn"], "--plugins-dir", p["plugins"])
    out = r.stdout + r.stderr
    assert f"{p['warn']}:1:10" in out
    assert "PODSUMOWANIE ZNALEZISK" in out


# ════════════════════════════════════════════════════════════════
# 5. --no-suggestions
# ════════════════════════════════════════════════════════════════

def test_cli_no_suggestions(tmp_path):
    """--no-suggestions → bez sekcji 'zalecany/alternatywy'."""
    p = _make_project(tmp_path)
    r = _run(p["warn"], "--plugins-dir", p["plugins"], "--no-suggestions")
    out = r.stdout + r.stderr
    assert "zalecany:" not in out
    assert "alternatywy:" not in out
    # werdykt nadal jest
    assert "MAŁA" in out


# ════════════════════════════════════════════════════════════════
# 6. --vs16 (klastry z VS16, po fixie w scanner.py)
# ════════════════════════════════════════════════════════════════

def test_cli_vs16_finds_cluster(tmp_path):
    """--vs16 znajduje ⚙️ (klaster: EMOJI + VS16), mimo że kind=EMOJI."""
    p = _make_project(tmp_path)
    r = _run(p["vs16"], "--plugins-dir", p["plugins"], "--vs16", "--quiet")
    out = r.stdout + r.stderr
    # Klucz: plik jest znaleziony (Razem: 1 znalezisk), nie 0
    assert "Razem: 1 znalezisk" in out, f"oczekiwano 1, jest: {out[-200:]}"


# ════════════════════════════════════════════════════════════════
# 7. --skip-ext
# ════════════════════════════════════════════════════════════════

def test_cli_skip_ext(tmp_path):
    """--skip-ext .txt → pomija skip.txt."""
    p = _make_project(tmp_path)
    _run(p["skip_txt"], "--plugins-dir", p["plugins"], "--skip-ext", ".txt", "--quiet")
    # --skip-ext nie działa na pojedynczy plik (użytkownik go wskazał)
    # ale w katalogu — tak. Sprawdzamy katalog:
    r2 = _run(p["src"], "--plugins-dir", p["plugins"], "--skip-ext", ".txt", "--quiet")
    out2 = r2.stdout + r2.stderr
    # .txt pominięty, więc 3 pliki zamiast 4
    assert "pominięto: 1" in out2 or "skan: 3" in out2, f"out: {out2[-300:]}"


# ════════════════════════════════════════════════════════════════
# 8. --skip-dir
# ════════════════════════════════════════════════════════════════

def test_cli_skip_dir(tmp_path):
    """--skip-dir pomija katalog (np. src/vs16.rs w podkatalogu)."""
    p = _make_project(tmp_path)
    sub = tmp_path / "src" / "subdir"
    sub.mkdir()
    (sub / "x.rs").write_text('"⚠";\n', encoding="utf-8")

    r = _run(p["src"], "--plugins-dir", p["plugins"], "--skip-dir", "subdir", "--quiet")
    out = r.stdout + r.stderr
    # subdir pominięty → x.rs nie jest skanowany
    assert "pominięto" in out or "skan: 4" in out


# ════════════════════════════════════════════════════════════════
# 9. --fragile-mode
# ════════════════════════════════════════════════════════════════

def test_cli_fragile_mode_split(tmp_path):
    """
    --fragile-mode split → działa (exit 0/2 zależnie od treści).

    Uwaga: komunikat `Tryb FRAGILE: split` jest w preambule, a preambuła
    jest pomijana przez `--quiet`. Dlatego test NIE używa `--quiet`.
    """
    p = _make_project(tmp_path)
    r = _run(
        p["ok"],
        "--plugins-dir", p["plugins"],
        "--fragile-mode", "split",
    )
    # Exit code 0 lub 2 (w zależności od zawartości), ale nie crash
    assert r.returncode in (0, 2), f"crash: {r.returncode}"
    out = r.stdout + r.stderr
    assert "Tryb FRAGILE: split" in out


# ════════════════════════════════════════════════════════════════
# 10. --plugins-dir: własne pluginy
# ════════════════════════════════════════════════════════════════

def test_cli_custom_plugins_dir(tmp_path):
    """--plugins-dir → używa własnych pluginów, nie domyślnych."""
    p = _make_project(tmp_path)

    # Własne pluginy mają tylko ✅ i ⚠ — brak 🚀
    (tmp_path / "src" / "custom.rs").write_text('"🚀";\n', encoding="utf-8")
    custom = str(tmp_path / "src" / "custom.rs")

    r = _run(custom, "--plugins-dir", p["plugins"], "--quiet")
    out = r.stdout + r.stderr

    # 🚀 nie jest w custom ranges → nie znaleziony (0 znalezisk)
    assert "Razem: 0 znalezisk" in out, f"oczekiwano 0, jest: {out[-300:]}"


# ════════════════════════════════════════════════════════════════
# 11. Pełny skan katalogu
# ════════════════════════════════════════════════════════════════

def test_cli_scan_directory(tmp_path):
    """Skan katalogu src/ → 4 pliki, wiele znalezisk."""
    p = _make_project(tmp_path)
    r = _run(p["src"], "--plugins-dir", p["plugins"], "--quiet")
    out = r.stdout + r.stderr

    # 4 pliki: ok, warn, vs16, skip (wszystkie w src/)
    assert "skan: 4" in out, f"out: {out[-300:]}"
    # co najmniej 3 znaleziska: ✅ ⚠ ⚙️ (skip.txt też ma ⚠)
    assert "Razem: 4 znalezisk" in out or "Razem: 3 znalezisk" in out


# ════════════════════════════════════════════════════════════════
# 12. --version nie skanuje (krótki obwód)
# ════════════════════════════════════════════════════════════════

def test_cli_version_short_circuits():
    """--version kończy program zanim sprawdzi target."""
    r = _run("--version")
    assert r.returncode == 0
    # --version nie powinien skanować cwd
    assert "PODSUMOWANIE" not in r.stdout
    assert "Razem:" not in r.stdout
