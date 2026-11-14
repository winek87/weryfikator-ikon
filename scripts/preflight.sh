#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# preflight.sh — pełny test przed commitem
# ════════════════════════════════════════════════════════════════
# Uruchamia 10 testów:
#   1. Struktura plików (kluczowe pliki istnieją)
#   2. Import Pythona (emoji, scan_emoji, tools)
#   3. pytest (132 testy)
#   4. ruff (linting)
#   5. scan_emoji.py scan_emoji.py --strict (CLI jest czysty)
#   6. gen_plugin.py validate (pluginy OK)
#   7. YAML parse (.github/workflows/emoji-check.yml)
#   8. LICENSE zgodny z pyproject.toml
#   9. __version__ zgodny z pyproject.toml
#  10. .gitignore (backupy, cache, target)
#
# Exit code: 0 = wszystko OK, 1 = błędy
#
# Użycie:
#   bash scripts/preflight.sh
#   bash scripts/preflight.sh --quiet    # tylko błędy
# ════════════════════════════════════════════════════════════════

set -uo pipefail

# ── kolory (tylko jeśli stdout to terminal) ─────────────────────
if [ -t 1 ]; then
    RED='\033[1;31m'
    GREEN='\033[1;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[1;36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; DIM=''; RESET=''
fi

QUIET=0
if [ "${1:-}" = "--quiet" ] || [ "${1:-}" = "-q" ]; then
    QUIET=1
fi

# ── liczniki ────────────────────────────────────────────────────
PASS=0
FAIL=0
WARN=0

# ── pomocnicze ─────────────────────────────────────────────────
section() {
    [ "$QUIET" -eq 1 ] && return
    echo
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  $*${RESET}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
}

check_ok() {
    PASS=$((PASS + 1))
    [ "$QUIET" -eq 1 ] && return
    echo -e "  ${GREEN}✓${RESET} $*"
}

check_fail() {
    FAIL=$((FAIL + 1))
    echo -e "  ${RED}✗${RESET} $*"
}

check_warn() {
    WARN=$((WARN + 1))
    echo -e "  ${YELLOW}!${RESET} $*"
}

run_cmd() {
    # Uruchamia komendę, pokazuje output tylko przy błędzie.
    # Zwraca kod wyjścia komendy.
    local desc="$1"; shift
    local output
    if output=$("$@" 2>&1); then
        return 0
    else
        local rc=$?
        echo -e "  ${DIM}┌─ output (exit $rc) ──────────────────────${RESET}"
        echo "$output" | tail -20 | sed 's/^/  │ /'
        echo -e "  ${DIM}└──────────────────────────────────────────${RESET}"
        return $rc
    fi
}

# ── 0. Preambuła ───────────────────────────────────────────────
if [ "$QUIET" -eq 0 ]; then
    echo -e "${BOLD}emoji-scanner — preflight check${RESET}"
    echo -e "${DIM}katalog: $(pwd)${RESET}"
    echo -e "${DIM}data:    $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
fi

# ════════════════════════════════════════════════════════════════
# TEST 1: Struktura plików
# ════════════════════════════════════════════════════════════════
section "1/10  Struktura plików"

REQUIRED_FILES=(
    "scan_emoji.py"
    "pyproject.toml"
    "requirements.txt"
    "LICENSE"
    "README.md"
    ".gitignore"
    "emoji/__init__.py"
    "emoji/loader.py"
    "emoji/detection.py"
    "emoji/scanner.py"
    "emoji/reporter.py"
    "emoji/generator.py"
    "emoji/wykrywanie/00_modifiers.json"
    "emoji/wykrywanie/20_emoji_default_bmp.json"
    "emoji/wykrywanie/25_astral_text_default.json"
    "emoji/wykrywanie/28_font_risky_bmp.json"
    "emoji/wykrywanie/30_text_default_bmp.json"
    "emoji/zamienniki/10_settings.json"
    "emoji/zamienniki/20_warnings.json"
    "emoji/zamienniki/30_media.json"
    "emoji/zamienniki/40_misc.json"
    "tools/gen_plugin.py"
    "tools/emoji_wizard.py"
    ".github/workflows/emoji-check.yml"
    "tests/conftest.py"
    "tests/test_loader.py"
    "tests/test_detection.py"
    "tests/test_scanner.py"
    "tests/test_reporter.py"
    "tests/test_generator.py"
)

MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        check_fail "brak: $f"
        MISSING=$((MISSING + 1))
    fi
done

if [ "$MISSING" -eq 0 ]; then
    check_ok "wszystkie ${#REQUIRED_FILES[@]} kluczowych plików istnieją"
fi

# ════════════════════════════════════════════════════════════════
# TEST 2: Import Pythona
# ════════════════════════════════════════════════════════════════
section "2/10  Import Pythona"

if run_cmd "import emoji" python -c "
import emoji
print(f'  emoji-scanner {emoji.__version__}')
print(f'  HAS_WCWIDTH={emoji.HAS_WCWIDTH}')
" >/dev/null 2>&1; then
    check_ok "import emoji"
else
    check_fail "import emoji"
fi

if run_cmd "import scan_emoji" python -c "import scan_emoji" >/dev/null 2>&1; then
    check_ok "import scan_emoji"
else
    check_fail "import scan_emoji"
fi

if run_cmd "import emoji.generator" python -c "
from emoji.generator import (
    create_detection_plugin, guess_category,
    add_emoji_to_plugin, add_replacement_to_plugin,
    update_replacement_in_plugin, remove_plugin_file,
)
" >/dev/null 2>&1; then
    check_ok "import emoji.generator (wszystkie 6 funkcji)"
else
    check_fail "import emoji.generator"
fi

# ════════════════════════════════════════════════════════════════
# TEST 3: pytest
# ════════════════════════════════════════════════════════════════
section "3/10  pytest (132 testy)"

if command -v pytest >/dev/null 2>&1; then
    if OUT=$(python -m pytest tests/ -q 2>&1); then
        SUMMARY=$(echo "$OUT" | grep -E "passed|failed" | tail -1)
        check_ok "pytest: $SUMMARY"
    else
        check_fail "pytest: są błędy"
        echo "$OUT" | tail -20 | sed 's/^/    /'
    fi
else
    check_warn "pytest nie zainstalowany (pip install pytest)"
fi

# ════════════════════════════════════════════════════════════════
# TEST 4: ruff
# ════════════════════════════════════════════════════════════════
section "4/10  ruff (linting)"

if command -v ruff >/dev/null 2>&1; then
    if OUT=$(ruff check . 2>&1); then
        check_ok "ruff: All checks passed"
    else
        check_fail "ruff: są błędy"
        echo "$OUT" | tail -20 | sed 's/^/    /'
    fi
else
    check_warn "ruff nie zainstalowany (pip install ruff)"
fi

# ════════════════════════════════════════════════════════════════
# TEST 5: scan_emoji.py na scan_emoji.py --strict
# ════════════════════════════════════════════════════════════════
section "5/10  scan_emoji.py --strict (CLI jest czysty)"

if OUT=$(python scan_emoji.py scan_emoji.py --strict --quiet 2>&1); then
    check_ok "scan_emoji.py: 0 problemów (exit 0)"
else
    RC=$?
    if [ "$RC" -eq 2 ]; then
        check_fail "scan_emoji.py: są problemy (--strict exit 2)"
        echo "$OUT" | grep -A3 "PROPONOWANE" | head -20 | sed 's/^/    /'
    else
        check_fail "scan_emoji.py: błąd wykonania (exit $RC)"
        echo "$OUT" | tail -10 | sed 's/^/    /'
    fi
fi

# ════════════════════════════════════════════════════════════════
# TEST 6: gen_plugin.py validate
# ════════════════════════════════════════════════════════════════
section "6/10  gen_plugin.py validate (pluginy)"

if OUT=$(python tools/gen_plugin.py validate 2>&1); then
    if echo "$OUT" | grep -q "WYNIK: OK"; then
        DET=$(echo "$OUT" | grep -oP 'wczytane:\s+\K\d+' | head -1)
        REP=$(echo "$OUT" | grep -oP 'wczytane:\s+\K\d+' | tail -1)
        WARN_COUNT=$(echo "$OUT" | grep -oP 'Ostrzeżenia:\s+\K\d+' || echo "0")
        check_ok "pluginy: detekcja=$DET, zamienniki=$REP, ostrzeżenia=$WARN_COUNT"
    else
        check_fail "pluginy: WYNIK nie OK"
        echo "$OUT" | tail -15 | sed 's/^/    /'
    fi
else
    check_fail "gen_plugin.py validate (exit $?)"
    echo "$OUT" | tail -10 | sed 's/^/    /'
fi

# ════════════════════════════════════════════════════════════════
# TEST 7: YAML (GitHub Actions)
# ════════════════════════════════════════════════════════════════
section "7/10  YAML (.github/workflows/emoji-check.yml)"

if python -c "import yaml" 2>/dev/null; then
    if python -c "
import yaml
with open('.github/workflows/emoji-check.yml') as f:
    data = yaml.safe_load(f)
assert data['name'] == 'emoji-check'
assert 'jobs' in data
assert 'test' in data['jobs']
assert 'plugins' in data['jobs']
" 2>/dev/null; then
        check_ok "YAML: poprawny (name, jobs: test + plugins)"
    else
        check_fail "YAML: błąd parsowania"
    fi
else
    check_warn "PyYAML nie zainstalowany — pomijam test YAML"
fi

# ════════════════════════════════════════════════════════════════
# TEST 8: LICENSE vs pyproject.toml
# ════════════════════════════════════════════════════════════════
section "8/10  LICENSE vs pyproject.toml"

if python -c "
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib

data = tomllib.loads(Path('pyproject.toml').read_text())
declared = data['project'].get('license', {})
if isinstance(declared, dict):
    declared_text = declared.get('text', '')
else:
    declared_text = str(declared)

license_text = Path('LICENSE').read_text()
assert declared_text.upper() == 'MIT', f'pyproject.toml: {declared_text!r} != MIT'
assert 'MIT License' in license_text, 'LICENSE: brak MIT License'
assert 'Winek87' in license_text, 'LICENSE: brak Winek87'
assert 'DeepSeek' in license_text, 'LICENSE: brak DeepSeek'
" 2>/dev/null; then
    check_ok "LICENSE: MIT zgodne z pyproject.toml"
else
    check_fail "LICENSE: niezgodne z pyproject.toml"
fi

# ════════════════════════════════════════════════════════════════
# TEST 9: __version__ vs pyproject.toml
# ════════════════════════════════════════════════════════════════
section "9/10  __version__ vs pyproject.toml"

if python -c "
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib

import emoji

data = tomllib.loads(Path('pyproject.toml').read_text())
toml_version = data['project']['version']
py_version = emoji.__version__

assert toml_version == py_version, (
    f'rozjazd: pyproject.toml={toml_version!r}, __init__.py={py_version!r}'
)
" 2>/dev/null; then
    VER=$(python -c "import emoji; print(emoji.__version__)")
    check_ok "__version__: $VER (zgodne z pyproject.toml)"
else
    check_fail "__version__: rozjazd między pyproject.toml a __init__.py"
fi

# ════════════════════════════════════════════════════════════════
# TEST 10: .gitignore
# ════════════════════════════════════════════════════════════════
section "10/10  .gitignore (backupy, cache, target)"

if [ -d .git ]; then
    # Test: czy git check-ignore działa
    declare -a IGNORED=(
        "__pycache__/test.pyc"
        "emoji/wykrywanie/test.json.bak"
        "target/debug/binary"
        ".emoji_wizard_history"
        "tests/__pycache__/test_loader.cpython-312.pyc"
    )
    declare -a NOT_IGNORED=(
        "scan_emoji.py"
        "emoji/__init__.py"
        "emoji/wykrywanie/00_modifiers.json"
        "README.md"
        "pyproject.toml"
        "tests/test_loader.py"
    )

    BAD_IGNORE=0
    for f in "${IGNORED[@]}"; do
        if ! git check-ignore -q "$f" 2>/dev/null; then
            check_fail ".gitignore: $f POWINIEN być ignorowany"
            BAD_IGNORE=$((BAD_IGNORE + 1))
        fi
    done

    BAD_TRACK=0
    for f in "${NOT_IGNORED[@]}"; do
        if git check-ignore -q "$f" 2>/dev/null; then
            check_fail ".gitignore: $f NIE powinien być ignorowany"
            BAD_TRACK=$((BAD_TRACK + 1))
        fi
    done

    if [ "$BAD_IGNORE" -eq 0 ] && [ "$BAD_TRACK" -eq 0 ]; then
        check_ok ".gitignore: ${#IGNORED[@]} ignorowanych, ${#NOT_IGNORED[@]} śledzonych"
    fi
else
    check_warn ".gitignore: brak .git (git init jeszcze nie zrobione) — pomijam"
fi

# ════════════════════════════════════════════════════════════════
# PODSUMOWANIE
# ════════════════════════════════════════════════════════════════
echo
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  PODSUMOWANIE${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo
echo -e "  ${GREEN}✓${RESET} PASS: ${PASS}"
echo -e "  ${YELLOW}!${RESET} WARN: ${WARN}"
echo -e "  ${RED}✗${RESET} FAIL: ${FAIL}"
echo

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}WYNIK: OK — gotowe do git add . i commit${RESET}"
    echo
    exit 0
else
    echo -e "  ${RED}${BOLD}WYNIK: BŁĘDY ($FAIL) — popraw przed commitem${RESET}"
    echo
    exit 1
fi
