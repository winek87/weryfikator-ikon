# 🛠 emoji-scanner

[![emoji-check](https://github.com/winek87/weryfikator-ikon/actions/workflows/emoji-check.yml/badge.svg)](https://github.com/winek87/weryfikator-ikon/actions/workflows/emoji-check.yml)

**Skaner emoji dla plików źródłowych** — wykrywa emoji w kodzie, mierzy
ich szerokość **dwoma metodami** (wcwidth + heurystyka Unicode),
porównuje i raportuje problemy. Proponuje zamienniki z pluginów.

Zaprojektowany dla menu terminalowych, w których emoji renderują się
różnie zależnie od fontu, terminala i systemu. Rozwiązuje realne bugi:
„połówki” przez VS16, małe ikony w menu, ucięte astralne znaki, fonty
bez kolorowych emoji.

---

## Spis treści

1. [Szybki start](#szybki-start)
2. [Instalacja](#instalacja)
3. [Użycie](#użycie)
   - [scan_emoji.py — skaner](#scan_emojipy--skaner)
   - [emoji_wizard.py — interaktywne menu](#emoji_wizardpy--interaktywne-menu)
   - [gen_plugin.py — generator pluginów](#gen_pluginpy--generator-pluginów)
4. [Kategorie problemów](#kategorie-problemów)
5. [Architektura](#architektura)
6. [Pluginy](#pluginy)
7. [Własne pluginy](#własne-pluginy)
8. [Integracja z CI](#integracja-z-ci)
9. [Troubleshooting](#troubleshooting)
10. [Changelog](#changelog)
11. [Licencja](#licencja)

---

## Szybki start

```bash
# 1. Sklonuj / skopiuj projekt
cd pyt-rust

# 2. (opcjonalnie) zainstaluj wcwidth dla dokładnego pomiaru
pip install wcwidth

# 3. Uruchom skaner na swoim pliku
python scan_emoji.py src/main.rs
```

**Wynik:**

```
Pluginy: 7 detekcji, 4 zamienników

src/main.rs:107:10  [EMOJI] U+26A1  '⚡'
   ↳ wcwidth=2  |  heurystyka=2   FONT_RISK — BMP emoji, font może renderować mało
   ↳ zalecany:  🔋    (U+26A1 w niektórych fontach renderuje się mało...)
   ↳ alternatywy: 🔌, 💡, 🚀
   … "⚡  09. RPi Hardware, ZRAM & Perf Tuner  — ..."

── PODSUMOWANIE ZNALEZISK ──
  '⚡'  U+26A1 [EMOJI ] x1   →  🔋  FONT_RISK x1

── PORÓWNANIE METOD ──
  wcwidth:      23 pomiarów
  heurystyka:   23 pomiarów
  zgodne:       22
  ROZJAZD:      0
  MAŁA (text):  0
  FONT_RISK:    1

── PROPONOWANE ZMIANY ──
  src/main.rs:107:10  '⚡'  [FONT_RISK]
     1. 🔋         (zalecany)
     2. 🔌         (alternatywa)
     3. 💡         (alternatywa)
     4. 🚀         (alternatywa)
```

---

[Pełna lista zmian w v0.1.0](https://github.com/winek87/weryfikator-ikon/releases/tag/v0.1.0)

## Instalacja

### Opcja 1 — bez instalacji (najprostsza)

Projekt działa **bez instalacji** — wystarczy `python scan_emoji.py`
z katalogu projektu. Wszystkie zależności są opcjonalne.

### Opcja 2 — pip, editable (dla deweloperów)

```bash
pip install -e ".[full,dev]"
```

Daje:
- komendę `scan-emoji` (bez `python` i `.py`),
- `wcwidth` (dokładny pomiar),
- `pytest`, `ruff`, `mypy` (testy + linting).

### Opcja 3 — pip, tylko runtime

```bash
pip install ".[full]"
```

Daje `scan-emoji` + `wcwidth`, bez narzędzi deweloperskich.

### Opcja 4 — requirements.txt

```bash
pip install -r requirements.txt
```

Instaluje tylko `wcwidth` (bez pakietu). Użyj, jeśli chcesz mieć
`scan_emoji.py` bez instalacji, ale z dokładnym pomiarem.

### Zależności

| Zależność | Wymagane? | Cel |
|---|---|---|
| Python 3.10+ | **tak** | działa na 3.10, 3.11, 3.12, 3.13 |
| `wcwidth>=0.2.5` | opcjonalne | dokładny pomiar szerokości (bez tego tylko heurystyka) |
| `readline` | wbudowane | edycja linii w wizardzie (strzałki, backspace) |
| `gnureadline` | opcjonalne | tylko Windows / embedded Python (fallback) |

---

## Użycie

### scan_emoji.py — skaner

```bash
python scan_emoji.py <plik|folder> [opcje]
```

#### Opcje

| Opcja | Opis |
|---|---|
| `--vs16` | tylko VS16 (główny sprawca buga „połówki”) |
| `--no-suggestions` | bez sekcji „zalecany/alternatywy” w raporcie |
| `--quiet` | bez preambuły i raportu per-znalezisko (zostaje podsumowanie) |
| `--strict` | kod wyjścia 2, jeśli są problemy — do CI |
| `--fragile-mode MODE` | `simple` (domyślnie), `split`, `reporter` |
| `--plugins-dir ROOT` | katalog nadrzędny pluginów (oczekuje `ROOT/wykrywanie`, `ROOT/zamienniki`) |
| `--detection-dir DIR` | nadpisuje katalog pluginów detekcji |
| `--replacements-dir DIR` | nadpisuje katalog pluginów zamienników |
| `--skip-dir NAME` | dodatkowy katalog do pominięcia (można wielokrotnie) |
| `--skip-ext EXT` | dodatkowe rozszerzenie do pominięcia (można wielokrotnie) |
| `--no-default-skips` | nie używaj domyślnych list pomijania |
| `--version` | wersja narzędzia |
| `-h`, `--help` | pomoc |

#### Przykłady

```bash
# pojedynczy plik
python scan_emoji.py src/main.rs

# cały folder rekursywnie
python scan_emoji.py src/

# tylko VS16 (najszybsze)
python scan_emoji.py . --vs16

# CI: cichy, strict, własne pluginy
python scan_emoji.py src/ --quiet --strict --plugins-dir ./moje_emoji

# FRAGILE z rozbiciem bez/z VS16
python scan_emoji.py src/ --fragile-mode split

# pomiń dodatkowe katalogi
python scan_emoji.py . --skip-dir .cache --skip-dir tmp --skip-ext .log
```

#### Kody wyjścia

| Kod | Znaczenie |
|---|---|
| 0 | sukces (skan się odbył; nie zależy od liczby znalezisk) |
| 1 | błąd twardy (zła ścieżka, błąd pluginów, wyjątek) |
| 2 | `--strict` + znaleziono problemy (ROZJAZD/MAŁA/FRAGILE/FONT_RISK) |

Bez `--strict` skaner **zawsze** zwraca 0 po udanym skanie — jest
narzędziem raportującym, nie bramką. Bramką staje się z `--strict`.

---

### emoji_wizard.py — interaktywne menu

```bash
python tools/emoji_wizard.py [opcje]
```

#### Komendy menu

| Klawisz | Akcja |
|---|---|
| `a` | dodaj emoji (wizard z auto-klasyfikacją) |
| `e` | edytuj plugin w `$EDITOR` (fallback: nano, vi) |
| `d` | usuń plugin (z backupem `.bak`) |
| `s` | pokaż zawartość (tabela z ikonami lub raw) |
| `m` | dodaj ikony do istniejącego zamiennika |
| `v` | waliduj wszystkie pluginy |
| `q` | wyjdź |

#### Klawisze T/A/N

W promptach interaktywnych:

- **T** — Tak (akceptuję sugestię),
- **A** — Alternatywa (chcę inaczej / wybieram ręcznie),
- **N** — Nie (pomiń / anuluj).

Puste wejście = **T** (sugestia) w T/A/N, **anuluj** w listach.

#### Przykład — dodaj emoji

```
> a

═══ DODAWANIE EMOJI ═══

Krok 1/3: Emoji bazowe
   Wklej znak (np. ⚠ lub ⚙): ⚠

Krok 2/3: Detekcja
   [OK] U+26A0  '⚠'  WARNING SIGN
   kategoria:   TEXT_DEFAULT_BMP  (certain)
   wcwidth:     1
   powód:       jest w zbiorze TEXT_DEFAULT_BMP

   [!] Znak już istnieje w:
       - 10_emoji_ranges.json  (range)
       - 30_text_default_bmp.json  (set: TEXT_DEFAULT_BMP)

   [T] dodaj do TEXT_DEFAULT_BMP
   [A] wybierz inny zbiór
   [N] pomiń detekcję
   > t

   Już jest w TEXT_DEFAULT_BMP w 30_text_default_bmp.json — pomijam dodawanie.

Krok 3/3: Zamiennik
   [T] dodaj zamiennik
   [N] pomiń zamiennik
   > t
   Zalecany zamiennik (np. 🚨): 🚨
   Alternatywy po przecinku (puste = brak): ❗, [!]
   Uzasadnienie (krótko): text presentation, ⚠️ wymaga VS16

   Dodano '⚠' → '🚨' w 20_warnings.json

Walidacja:
   Wszystkie pluginy OK.
```

#### Przykład — dodaj ikony do istniejącego wpisu

```
> m

═══ DODAJ IKONY DO ZAMIENNIKA ═══

   Wklej ikonę (np. 🛡): ⚡

   40_misc.json:
     rec:  🔋
     alt:  🔌, 💡, 🚀
     realnych: 4/5

   Enter = koniec, Ctrl+C = anuluj

   Ikona 1 (realnych: 4/5): 🎯
   Ikona 2 (realnych: 5/5)  (+🎯): [Enter]

   Dodano do '⚡' w 40_misc.json:
     alt:  🔌, 💡, 🚀, 🎯

   realnych propozycji: 5/5 ✓
```

#### Opcje CLI

| Opcja | Opis |
|---|---|
| `--plugins-dir ROOT` | katalog nadrzędny pluginów |
| `--detection-dir DIR` | nadpisuje katalog pluginów detekcji |
| `--replacements-dir DIR` | nadpisuje katalog pluginów zamienników |
| `--dry-run` | pokazuje co by zrobił, ale nie zapisuje |
| `--no-color` | wyłącza kolory ANSI |
| `--diagnose` | tryb diagnostyczny: sprawdza readline, tty, TERM |
| `--version` | wersja narzędzia |

---

### gen_plugin.py — generator pluginów

```bash
python tools/gen_plugin.py <komenda> [opcje]
```

#### Komendy

| Komenda | Opis |
|---|---|
| `detection <name>` | utwórz nowy plugin detekcji |
| `replacement <name>` | utwórz nowy plugin zamienników |
| `list` | lista pluginów w katalogu |
| `validate` | walidacja wszystkich pluginów |
| `inspect <name|path>` | inspekcja pojedynczego pluginu |

#### Przykłady

```bash
# nowy plugin detekcji (domyślnie .json, prefix 50_)
python tools/gen_plugin.py detection warnings

# plugin zamienników w Pythonie, z opisem
python tools/gen_plugin.py replacement emoji_fix \
    --py --description "Własne zamienniki dla emoji"

# nadpisz istniejący plik
python tools/gen_plugin.py detection warnings --force

# lista pluginów detekcji
python tools/gen_plugin.py list

# walidacja wszystkich pluginów
python tools/gen_plugin.py validate

# inspekcja po nazwie (szuka w obu katalogach)
python tools/gen_plugin.py inspect warnings

# inspekcja po ścieżce
python tools/gen_plugin.py inspect emoji/wykrywanie/50_warnings.json
```

#### Kody wyjścia

| Kod | Znaczenie |
|---|---|
| 0 | sukces |
| 1 | błąd twardy (nie można zapisać, błąd składni) |
| 2 | konflikt (plik istnieje, brak `--force`) — dla `create` |
| 3 | walidacja wykazała błędy — dla `validate` |
| 4 | błąd użycia CLI (zły argument) |

---

## Kategorie problemów

Skaner rozpoznaje **5 kategorii** (pierwsza pasująca wygrywa):

### ROZJAZD — bug „połówki” przez VS16

**Przyczyna:** `wcwidth` mówi 1, terminal rysuje 2.

**Przykład:** `⚙️` (U+2699 + U+FE0F) — `wcwidth=1`, `heurystyka=2`.

**Rozwiązanie:** zamień na emoji default (`🔧`), **nie** dodawaj VS16.

### MAŁA (text) — BMP text presentation

**Przyczyna:** BMP emoji z `Emoji_Presentation=No` bez VS16. Szerokość
OK (1==1), ale glif jest mały i monochromatyczny.

**Przykład:** `⚠` (U+26A0), `⚙` (U+2699), `✓` (U+2713).

**Rozwiązanie:** zamień na emoji default (`🚨`, `🔧`, `✅`).

### FRAGILE — astralne Emoji_Presentation=No

**Przyczyna:** astralne znaki, które **powinny** być duże, ale bez VS16
renderują się małe, a z VS16 zależy od fontu — mogą być ucięte.

**Przykład:** `🛡` (U+1F6E1), `🕷` (U+1F577), `🗡` (U+1F5E1).

**Rozwiązanie:** zamień na emoji default (`🔰`, `🐛`, `🔪`).

### FONT_RISK — BMP emoji, font może renderować mało

**Przyczyna:** BMP emoji z `Emoji_Presentation=Yes`, ale w niektórych
fontach (Font Awesome, nerd-fonty, starsze fonty bez Noto Color Emoji)
renderują się mało.

**Przykład:** `⚡` (U+26A1), `☔` (U+2614), `☕` (U+2615), `⭐` (U+2B50).

**Rozwiązanie:** zamień na **astralne** emoji default (`🔋`, `🌧`, `☕`→`🍵`,
`⭐`→`🌟`). Astralne renderują się duże w każdym foncie.

### OK — brak problemów

Emoji default (astralne lub BMP z `Emoji_Presentation=Yes`), które
renderują się poprawnie w każdym terminalu.

---

## Architektura

```
pyt-rust/
├── scan_emoji.py                     ← CLI skanera (punkt wejścia)
├── pyproject.toml                    ← metadane pakietu
├── requirements.txt                  ← zależności (wcwidth)
├── README.md                         ← ten plik
├── .gitignore
│
├── emoji/                            ← pakiet Pythona (logika)
│   ├── __init__.py                   ← publiczne API pakietu
│   ├── loader.py                     ← ładowanie pluginów .json/.py
│   ├── detection.py                  ← classify(), measure_*()
│   ├── scanner.py                    ← chodzenie po plikach + scan()
│   ├── reporter.py                   ← print_report(), print_summary()
│   ├── generator.py                  ← tworzenie/modyfikacja pluginów
│   │
│   ├── wykrywanie/                   ← DANE: co wykrywać
│   │   ├── README.md
│   │   ├── 00_modifiers.json         ← VS16, VS15, ZWJ, KEYCAP
│   │   ├── 10_emoji_ranges.json      ← zakresy Unicode
│   │   ├── 20_emoji_default_bmp.json ← BMP emoji default
│   │   ├── 25_astral_text_default.json ← astralne text-default
│   │   ├── 28_font_risky_bmp.json    ← BMP font-risky (obserwacyjne)
│   │   ├── 30_text_default_bmp.json  ← BMP text-default
│   │   └── 35_small_symbols.json     ← symbole tekstowe (uzupełnienie)
│   │
│   └── zamienniki/                   ← DANE: czym zastępować
│       ├── README.md
│       ├── 10_settings.json          ← ⚙ 🗂 🗀 🗃 🗄 🛠 🗜
│       ├── 20_warnings.json          ← ⚠ ✔ ✖ ✗ ☑ ☒ ✓ ☠ ⁉ ‼
│       ├── 30_media.json             ← ▶ ⏸ ⏭ ⏮ ⏹ ⏺ ⏏ 🎬
│       └── 40_misc.json              ← ☀ ☁ ☂ ☎ ✉ ❤ ✏ ★ ✂ ⚡ 🛡 ...
│
└── tools/                            ← narzędzia deweloperskie
    ├── gen_plugin.py                 ← CLI generatora
    └── emoji_wizard.py               ← interaktywne menu
```

### Przepływ danych

```
scan_emoji.py
    │
    ├── load_plugins()          ← emoji/wykrywanie/*.json|*.py
    ├── load_replacements()     ← emoji/zamienniki/*.json|*.py
    │
    ├── scan(target, det_data)
    │     │
    │     ├── collect_files()   ← chodzenie po katalogach
    │     ├── iter_findings()   ← klastrowanie (bazowy + VS16/ZWJ/...)
    │     └── measure_both()    ← 2 metody + werdykt
    │
    ├── print_report()          ← per-znalezisko
    └── print_summary()         ← ranking + porównanie + propozycje
```

---

## Pluginy

### Format `.json` (detekcja)

```json
{
  "name": "warnings",
  "description": "Emoji ostrzeżeń",
  "version": "1.0",
  "codepoints": [
    {"cp": "U+FE0F", "kind": "VS16", "label": "Variation Selector-16"}
  ],
  "ranges": [
    {"start": "U+1F300", "end": "U+1F5FF", "kind": "EMOJI"}
  ],
  "sets": {
    "TEXT_DEFAULT_BMP": ["U+26A0", "U+2699"]
  }
}
```

### Format `.json` (zamienniki)

```json
{
  "name": "warnings",
  "replacements": {
    "⚠": {
      "rec": "🚨",
      "alt": ["❗", "[!]"],
      "why": "text presentation; ⚠️ wymaga VS16"
    }
  }
}
```

### Pełna dokumentacja formatu

- **`emoji/wykrywanie/README.md`** — format pluginów detekcji
- **`emoji/zamienniki/README.md`** — format pluginów zamienników

### Kolejność ładowania

Pliki ładowane **alfabetycznie** (prefixy `00_`, `10_`, `20_`…).
Przy duplikacie **pierwszy wygrywa** — wbudowane definicje mają niskie
numery, więc twój plugin z `50_` nie nadpisze domyślnych.

---

## Własne pluginy

### Szybki start

```bash
# 1. Utwórz plugin generatorem
python tools/gen_plugin.py detection moje_emoji --prefix 50_
# → emoji/wykrywanie/50_moje_emoji.json

# 2. Edytuj ręcznie lub wizardem
python tools/emoji_wizard.py
# > e
# [7] 50_moje_emoji.json

# 3. Waliduj
python tools/gen_plugin.py validate

# 4. Uruchom skaner
python scan_emoji.py src/
```

### Osobny katalog pluginów

```bash
# trzymaj pluginy poza repo
mkdir -p ~/moje_emoji/wykrywanie ~/moje_emoji/zamienniki
cp emoji/wykrywanie/*.json ~/moje_emoji/wykrywanie/
cp emoji/zamienniki/*.json ~/moje_emoji/zamienniki/

# edytuj co chcesz, potem:
python scan_emoji.py src/ --plugins-dir ~/moje_emoji
```

### Dodanie nowego emoji

Najszybsza droga — wizard:

```bash
python tools/emoji_wizard.py
# > a
# wklej znak → wizard rozpozna kategorię → zapisze do pluginu
```

Wizard używa `guess_category()` — dla znanego znaku (np. `⚠`) od razu
wie, że to `TEXT_DEFAULT_BMP`. Dla nieznanego (`§`) pyta o zbiór.

---

## Integracja z CI

### GitHub Actions

```yaml
# .github/workflows/emoji-check.yml
name: Emoji Check

on: [push, pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install wcwidth

      - name: Scan emoji
        run: python scan_emoji.py src/ --strict --quiet
        # --strict: exit 2 jeśli są problemy (ROZJAZD/MAŁA/FRAGILE/FONT_RISK)
        # --quiet: tylko podsumowanie, bez raportu per-znalezisko
```

### pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: scan-emoji
        name: Scan emoji
        entry: python scan_emoji.py
        language: system
        types: [rust, python, javascript]
        args: ["--strict", "--quiet"]
        pass_filenames: false
        require_serial: true
```

### GitLab CI

```yaml
# .gitlab-ci.yml
emoji-check:
  image: python:3.12
  before_script:
    - pip install wcwidth
  script:
    - python scan_emoji.py src/ --strict --quiet
  allow_failure: false
```

---

## Troubleshooting

### „Brak biblioteki wcwidth”

**Objaw:** `Uwaga: brak biblioteki 'wcwidth' — tylko heurystyka.`

**Rozwiązanie:**
```bash
pip install wcwidth
```

Bez `wcwidth` skaner działa, ale traci połowę diagnostyki —
`ROZJAZD` nigdy nie zapala się (bo nie ma porównania).

### „strzałki/backspace nie działają w wizardzie”

**Objaw:** W `emoji_wizard.py` nie możesz edytować linii (strzałki nie
przesuwają kursora, backspace nie usuwa).

**Diagnoza:**
```bash
python tools/emoji_wizard.py --diagnose
```

Sprawdź sekcję `readline:` w outputcie. Jeśli `BRAK`:

**Linux/macOS:**
```bash
sudo apt install python3-readline      # Debian/Ubuntu
brew install readline                  # macOS
```

**Windows:**
```bash
pip install gnureadline
```

**Jeśli `readline` jest OK, ale backspace dalej nie działa:**
```bash
stty -a | grep -o 'erase = .'         # sprawdź co jest
stty erase ^?                          # napraw (Ctrl+V żeby wpisać ^?)
```

**W tmux/screen:**
```
Ctrl+B :set -g xterm-keys on
```

### „Emoji renderują się jako znaki zapytania / prostokąty”

**Przyczyna:** terminal lub font nie ma glifu dla emoji.

**Rozwiązanie:**
1. Zainstaluj **Noto Color Emoji** (Linux) lub **Apple Color Emoji**
   (macOS) — większość emoji będzie działać.
2. Sprawdź, czy terminal wspiera emoji (GNOME Terminal, iTerm2,
   Windows Terminal — tak; stary `cmd.exe` — nie).
3. Ustaw `TERM=xterm-256color` (lub nowszy).

### „Emoji renderują się mało w terminalu”

**Przyczyna:** font ma własną wersję glifu (np. nerd-font, Font Awesome),
który jest mały.

**Rozwiązanie:**
1. Sprawdź `scan_emoji.py` — czy dany znak jest w `FONT_RISKY_BMP`
   lub `TEXT_DEFAULT_BMP`.
2. Użyj zamiennika z pluginu (astralne emoji default — zawsze duże).
3. Zmień font terminala na taki z pełnym wsparciem emoji.

### „Plugin ma błąd składni”

**Objaw:** `[UWAGA] nazwa.json: Expecting value: line X column Y`

**Rozwiązanie:**
```bash
python tools/gen_plugin.py validate
# pokaże, który plik i jaka linia

# lub
python -c "import json; json.load(open('emoji/zamienniki/10_settings.json'))"
```

Typowe przyczyny: brakujący przecinek, niezamknięty `}`, znak BOM na
początku pliku.

### „Duplikat zamiennika '⚠' w pluginach”

**Objaw:** `[UWAGA] 40_misc.json: duplikat zamiennika '⚠' (pomijam)`

**Przyczyna:** ten sam znak w dwóch pluginach. Loader **pierwszy
wygrywa** — plugin z niższym numerem ma priorytet.

**Rozwiązanie:** usuń duplikat z jednego z pluginów (np. `e` w wizardzie).

### „Wizard nie widzi moich pluginów”

**Objaw:** `--plugins-dir` nie działa, wizard widzi tylko domyślne.

**Sprawdzenie:**
```bash
ls ~/moje_emoji/wykrywanie/        # musi istnieć
ls ~/moje_emoji/zamienniki/        # musi istnieć

python tools/emoji_wizard.py --plugins-dir ~/moje_emoji
```

`--plugins-dir` oczekuje **dwóch** podkatalogów: `wykrywanie/` i `zamienniki/`.

---

## Changelog

### v0.1.0 (2026-11)

**Pierwsza wersja.**

- Skaner `scan_emoji.py` z 5 werdyktami: `ROZJAZD`, `MAŁA`, `FRAGILE`,
  `FONT_RISK`, `OK`.
- Dwie metody pomiaru: `wcwidth` (naiwna) + heurystyka Unicode
  (deterministyczna).
- Wizard `emoji_wizard.py` z komendami: `a`, `e`, `d`, `s`, `m`, `v`, `q`.
- Generator `gen_plugin.py` z komendami: `detection`, `replacement`,
  `list`, `validate`, `inspect`.
- 7 pluginów detekcji, 4 pluginy zamienników.
- Loader z normalizacją kluczy (VS16 w kluczach → baza).
- `--strict` dla CI, `--fragile-mode` (simple/split/reporter),
  `--plugins-dir`, `--skip-dir`, `--skip-ext`.
- Diagnostyka terminala `--diagnose` (readline, tty, TERM).
- Historia poleceń wizarda w `~/.emoji_wizard_history`.

---

## Licencja

MIT. Zobacz `LICENSE` (jeśli istnieje) lub:

```
Copyright (c) 2026 Winek87 & DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Autorzy

- **Winek87** — pomysł, wymagania, testy w realnym terminalu.
- **DeepSeek** — implementacja, dokumentacja, architektura.

Projekt powstał z realnego problemu: menu terminalowe w Rust Dashboard
miały emoji, które renderowały się małe lub ucięte zależnie od fontu.
Zamiast zgadywać, zbudowaliśmy narzędzie, które **mierzy** i **porównuje**.
