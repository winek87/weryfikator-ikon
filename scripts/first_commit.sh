#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# first_commit.sh — inicjalizacja repo + pierwszy commit + tag
# ════════════════════════════════════════════════════════════════
# Uruchamia:
#   1. Sprawdza, czy jesteś w katalogu projektu (scan_emoji.py)
#   2. Sprawdza git config (user.name, user.email)
#   3. git init -b main (jeśli brak .git)
#   4. git add .
#   5. Sanity check staging (co NIE powinno być w repo)
#   6. git commit z pełnym komunikatem
#   7. git tag -a v0.1.0
#   8. Weryfikacja: git log, git tag, git status
#
# Idempotentny:
#   - jeśli .git istnieje → pomija init
#   - jeśli commit istnieje → pomija commit
#   - jeśli tag istnieje → pomija tag
#
# Exit code: 0 = wszystko OK, 1 = błędy
# ════════════════════════════════════════════════════════════════

set -uo pipefail

# ── kolory ─────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'
    CYAN='\033[1;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; DIM=''; RESET=''
fi

section() {
    echo
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  $*${RESET}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
}

ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
fail() { echo -e "  ${RED}✗${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
info() { echo -e "  ${DIM}$*${RESET}"; }

# ════════════════════════════════════════════════════════════════
# 0. Sprawdź, czy jesteś w katalogu projektu
# ════════════════════════════════════════════════════════════════
section "0/7  Weryfikacja katalogu"

if [ ! -f "scan_emoji.py" ]; then
    fail "brak scan_emoji.py w $(pwd)"
    fail "uruchom z katalogu projektu (np. cd ~/weryfikator-ikon)"
    exit 1
fi
ok "scan_emoji.py znaleziony w $(pwd)"

if [ ! -f "pyproject.toml" ]; then
    fail "brak pyproject.toml"
    exit 1
fi
ok "pyproject.toml znaleziony"

# ════════════════════════════════════════════════════════════════
# 1. Sprawdź git config
# ════════════════════════════════════════════════════════════════
section "1/7  git config"

GIT_NAME=$(git config --global user.name 2>/dev/null || echo "")
GIT_EMAIL=$(git config --global user.email 2>/dev/null || echo "")

if [ -z "$GIT_NAME" ]; then
    fail "brak git user.name"
    info "ustaw: git config --global user.name \"Twoje Imię\""
    exit 1
fi
ok "user.name: $GIT_NAME"

if [ -z "$GIT_EMAIL" ]; then
    fail "brak git user.email"
    info "ustaw: git config --global user.email \"ty@example.com\""
    exit 1
fi
ok "user.email: $GIT_EMAIL"

# ════════════════════════════════════════════════════════════════
# 2. git init (jeśli brak)
# ════════════════════════════════════════════════════════════════
section "2/7  git init"

if [ -d .git ]; then
    info ".git już istnieje — pomijam init"
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
    if [ -n "$CURRENT_BRANCH" ] && [ "$CURRENT_BRANCH" != "main" ]; then
        warn "jesteś na branchu '$CURRENT_BRANCH' (nie main)"
        info "jeśli chcesz main: git branch -m main"
    fi
else
    if git init -b main 2>/dev/null; then
        ok "git init -b main"
    else
        # starsza wersja git bez -b
        git init >/dev/null
        git symbolic-ref HEAD refs/heads/main
        ok "git init (bez -b, ustawiono main ręcznie)"
    fi
fi

# ════════════════════════════════════════════════════════════════
# 3. git add .
# ════════════════════════════════════════════════════════════════
section "3/7  git add ."

git add . 2>&1
STAGED_COUNT=$(git diff --cached --name-only | wc -l)
ok "dodane pliki: $STAGED_COUNT"

if [ "$STAGED_COUNT" -eq 0 ]; then
    warn "brak plików w staging — może już po commicie?"
    info "sprawdź: git log --oneline"
    exit 0
fi

# ════════════════════════════════════════════════════════════════
# 4. Sanity check staging
# ════════════════════════════════════════════════════════════════
section "4/7  Sanity check — czego NIE ma w staging"

BAD_FOUND=0
for bad in "target/" "__pycache__/" ".pyc" ".bak" ".emoji_wizard_history" ".env" "node_modules/"; do
    if git diff --cached --name-only | grep -q "$bad"; then
        fail "$bad jest w staging (nie powinno)"
        BAD_FOUND=$((BAD_FOUND + 1))
    else
        ok "$bad: brak w staging"
    fi
done

# Sprawdź, że kluczowe pliki SĄ
echo
info "Kluczowe pliki w staging:"
for f in \
    "README.md" "pyproject.toml" "LICENSE" \
    "scan_emoji.py" "emoji/__init__.py" \
    "tools/emoji_wizard.py" "tools/gen_plugin.py" \
    ".github/workflows/emoji-check.yml" \
    "tests/test_loader.py" "tests/test_detection.py" \
    "emoji/wykrywanie/28_font_risky_bmp.json" \
    "emoji/zamienniki/40_misc.json"; do
    if git diff --cached --name-only | grep -q "^$f$"; then
        ok "$f"
    else
        fail "BRAK: $f"
        BAD_FOUND=$((BAD_FOUND + 1))
    fi
done

if [ "$BAD_FOUND" -gt 0 ]; then
    echo
    fail "sanity check nie przeszedł — popraw .gitignore lub usuń pliki z staging"
    info "git reset HEAD <plik>  # usuń pojedynczy plik ze staging"
    exit 1
fi

# ════════════════════════════════════════════════════════════════
# 5. git commit
# ════════════════════════════════════════════════════════════════
section "5/7  git commit"

if git log --oneline -1 >/dev/null 2>&1; then
    warn "repo ma już commity — pomijam commit"
    info "ostatni commit: $(git log --oneline -1)"
else
    COMMIT_MSG='feat: emoji-scanner v0.1.0 — skaner emoji z 5 werdyktami

Skaner emoji dla plików źródłowych. Wykrywa emoji, mierzy ich
szerokość dwoma metodami (wcwidth + heurystyka Unicode), porównuje
i raportuje problemy. Proponuje zamienniki z pluginów.

Werdykty:
- ROZJAZD   — wcwidth != heurystyka (bug „połówki" przez VS16)
- MAŁA      — BMP text presentation bez VS16 (np. ⚠ U+26A0)
- FRAGILE   — astral Emoji_Presentation=No (np. 🛡 U+1F6E1)
- FONT_RISK — BMP emoji, font może renderować mało (np. ⚡ U+26A1)
- OK        — brak problemów

Komponenty:
- scan_emoji.py         — CLI skanera (--strict, --fragile-mode,
                          --plugins-dir, --skip-dir, --skip-ext)
- tools/emoji_wizard.py — interaktywne menu (a/e/d/s/m/v/q)
                          z promptami T/A/N i readline
- tools/gen_plugin.py   — generator pluginów (detection/replacement/
                          list/validate/inspect)
- emoji/loader.py       — ładowanie pluginów .json/.py z normalizacją
                          kluczy (VS16 → baza)
- emoji/detection.py    — classify, measure_*, werdykty
- emoji/scanner.py      — collect_files, iter_findings, scan
- emoji/reporter.py     — print_report, print_summary, _proposals_for
- emoji/generator.py    — create_*, add_*, update_*, remove_*,
                          guess_category

Pluginy:
- 7 detekcji: 00_modifiers, 10_emoji_ranges, 20_emoji_default_bmp,
              25_astral_text_default, 28_font_risky_bmp,
              30_text_default_bmp, 35_small_symbols
- 4 zamienniki: 10_settings, 20_warnings, 30_media, 40_misc
- Razem: ~130 codepointów detekcji, ~70 zamienników

Testy:
- 132 testy jednostkowe (pytest)
- test_loader, test_detection, test_scanner, test_reporter,
  test_generator
- 100% pass, ruff clean

CI:
- .github/workflows/emoji-check.yml
- macierz Pythona 3.10, 3.11, 3.12, 3.13
- pytest + ruff + scan_emoji.py --strict

Dokumentacja:
- README.md (750 linii: instalacja, użycie, kategorie, architektura,
  troubleshooting, CI)
- emoji/wykrywanie/README.md (format pluginów detekcji)
- emoji/zamienniki/README.md (format pluginów zamienników)

Licencja: MIT (Winek87 & DeepSeek)
'

    if git commit -m "$COMMIT_MSG" >/dev/null 2>&1; then
        ok "git commit"
        info "skrót: $(git log --oneline -1)"
    else
        fail "git commit nie powiódł się"
        info "sprawdź: git status"
        exit 1
    fi
fi

# ════════════════════════════════════════════════════════════════
# 6. git tag v0.1.0
# ════════════════════════════════════════════════════════════════
section "6/7  git tag v0.1.0"

if git tag -l "v0.1.0" | grep -q "v0.1.0"; then
    warn "tag v0.1.0 już istnieje — pomijam"
else
    TAG_MSG='v0.1.0 — pierwsza wersja emoji-scanner

Skaner emoji z 5 werdyktami (ROZJAZD, MAŁA, FRAGILE, FONT_RISK, OK),
wizardem interaktywnym, generatorem pluginów i 132 testami.
'
    if git tag -a v0.1.0 -m "$TAG_MSG" 2>/dev/null; then
        ok "git tag -a v0.1.0"
    else
        fail "git tag nie powiódł się"
    fi
fi

# ════════════════════════════════════════════════════════════════
# 7. Weryfikacja
# ════════════════════════════════════════════════════════════════
section "7/7  Weryfikacja"

echo
info "git log --oneline -5:"
git log --oneline -5 | sed 's/^/    /'

echo
info "git tag -l:"
git tag -l | sed 's/^/    /'

echo
info "git status --short (powinno być pusto):"
STATUS_OUT=$(git status --short)
if [ -z "$STATUS_OUT" ]; then
    ok "working tree czysty"
else
    warn "są nieśledzone/zmienione pliki:"
    echo "$STATUS_OUT" | head -10 | sed 's/^/    /'
fi

echo
info "Podsumowanie:"
COMMITS=$(git rev-list --count HEAD 2>/dev/null || echo "?")
FILES=$(git ls-files | wc -l)
TAGS=$(git tag -l | wc -l)
echo -e "    commity:     ${CYAN}${COMMITS}${RESET}"
echo -e "    plików:      ${CYAN}${FILES}${RESET}"
echo -e "    tagi:        ${CYAN}${TAGS}${RESET}"

# ════════════════════════════════════════════════════════════════
# PODSUMOWANIE
# ════════════════════════════════════════════════════════════════
echo
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  WYNIK${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo
echo -e "  ${GREEN}${BOLD}OK — repo gotowe do push${RESET}"
echo
echo -e "  Następne kroki:"
echo -e "    ${DIM}git remote add origin <url>${RESET}"
echo -e "    ${DIM}git push -u origin main${RESET}"
echo -e "    ${DIM}git push origin v0.1.0${RESET}"
echo
echo -e "  Lub przez gh CLI (jeśli masz):"
echo -e "    ${DIM}gh repo create weryfikator-ikon --public --source=. --push${RESET}"
echo -e "    ${DIM}gh release create v0.1.0 --generate-notes${RESET}"
echo
exit 0
