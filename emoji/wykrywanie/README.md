# Pluginy detekcji — CO wykrywać

Ten folder zawiera pluginy, które mówią skanerowi, **które znaki są
emoji** oraz **do jakiej kategorii należą**. Każdy plugin to plik
`.json` lub `.py` z zadeklarowanymi stałymi. Pliki ładowane są
alfabetycznie (stąd prefixy `00_`, `10_`, `20_`…). Przy duplikacie
**pierwszy wygrywa** — dlatego wbudowane definicje mają niskie numery.

---

## Format `.json`

```json
{
  "name": "warnings",
  "description": "Emoji ostrzeżeń",
  "version": "1.0",
  "codepoints": [
    {"cp": "U+FE0F", "kind": "VS16", "label": "Variation Selector-16"}
  ],
  "ranges": [
    {"start": "U+1F300", "end": "U+1F5FF", "kind": "EMOJI", "label": "Misc Symbols"}
  ],
  "sets": {
    "TEXT_DEFAULT_BMP": ["U+26A0", "U+2699"]
  }
}
```

### Pola

- **`name`** (wymagane) — nazwa pluginu. Ładuje się do `inspect` i `list`.
- **`description`** (opcjonalne) — opis dla człowieka.
- **`version`** (opcjonalne) — wersja (np. `"1.0"`).
- **`codepoints`** — lista obiektów `{cp, kind, label}`. **Najbardziej
  szczegółowe** — nadpisuje `ranges`. Używane dla modyfikatorów (VS16,
  VS15, ZWJ, KEYCAP).
- **`ranges`** — lista `{start, end, kind, label}`. Pary **domknięte**
  (`lo <= cp <= hi`). Zwracają `"EMOJI"` (lub inny `kind`).
- **`sets`** — mapa `nazwa_zbioru → [codepointy]`. Używane przez
  `measure_both` do werdyktów (`text_default`, `fragile`, `font_risky`).

### Wartości `kind`

- `"VS16"` — U+FE0F, wymusza emoji presentation (główny sprawca buga „połówki"),
- `"VS15"` — U+FE0E, wymusza text presentation,
- `"ZWJ"` — U+200D, łączy znaki w sekwencję,
- `"KEYCAP"` — U+20E3, klawisz w ramce,
- `"EMOJI"` — zwykłe emoji (z `ranges`).

---

## Format `.py`

```python
NAME = "warnings"
DESCRIPTION = "Emoji ostrzeżeń"
VERSION = "1.0"

CODEPOINTS = {0xFE0F: "VS16", 0xFE0E: "VS15"}
RANGES = [(0x1F300, 0x1F5FF), (0x2600, 0x26FF)]
SETS = {"TEXT_DEFAULT_BMP": {0x26A0, 0x2699}}
```

### Zasady `.py`

- Stałe muszą być **wielkimi literami** (`NAME`, `CODEPOINTS`, …).
- `CODEPOINTS` — `dict` (int → str).
- `RANGES` — lista par `(start, end)` lub lista tuple.
- `SETS` — `dict` (str → iterable intów lub stringów `"U+XXXX"`).
- **Nie używaj emoji w komentarzach** — skaner je znajdzie, jeśli
  uruchomisz `scan_emoji.py emoji/wykrywanie/`.
- Plik jest wykonywany przez `importlib` bez `sys.path` — nie może
  importować innych pluginów.

---

## Standardowe nazwy zbiorów

### `EMOJI_DEFAULT_BMP`

BMP-owe znaki (U+0000–U+FFFF) z **`Emoji_Presentation=Yes`**.
Terminal rysuje je od razu jako duże, kolorowe — bez VS16.
Szerokość: 2 komórki. Werdykt: **OK**.

Przykłady: `⚡` U+26A1, `⭐` U+2B50, `✅` U+2705.

### `TEXT_DEFAULT_BMP`

BMP-owe znaki z **`Emoji_Presentation=No`** lub `Emoji=No`.
Terminal rysuje je domyślnie jako **małe, monochromatyczne**.
Szerokość: 1 komórka (bez VS16). Werdykt: **MAŁA**.

Przykłady: `⚠` U+26A0, `⚙` U+2699, `✓` U+2713.

### `ASTRAL_TEXT_DEFAULT`

Astralne znaki (U+10000+) z **`Emoji_Presentation=No`**.
Powinny być duże (bo astralne), ale bez VS16 renderują się małe,
a **z** VS16 zależy od fontu — mogą być ucięte. Werdykt: **FRAGILE**.

Przykłady: `🛡` U+1F6E1, `🕷` U+1F577, `🗡` U+1F5E1.

### `FONT_RISKY_BMP`

BMP-owe znaki z **`Emoji_Presentation=Yes`**, które w niektórych
fontach (Font Awesome, nerd-fonty, starsze fonty bez Noto Color Emoji)
renderują się mało. Unicode mówi „duże", font może kłamać.
Werdykt: **FONT_RISK**.

Przykłady: `⚡` U+26A1, `☔` U+2614, `☕` U+2615, `⭐` U+2B50.

**Lista jest obserwacyjna** — zawiera tylko znaki **realnie** widziane
jako problematyczne w konkretnym środowisku. Nie ma sensu zgadywać;
trzeba patrzeć i dopisywać.

---

## Hierarchia sprawdzania w `measure_both`

```
1. ROZJAZD        — wcwidth != heurystyka (bug „połówki")
2. MAŁA           — text_default (TEXT_DEFAULT_BMP, bez VS16)
3. FRAGILE        — fragile (ASTRAL_TEXT_DEFAULT, bez/z VS16)
4. FONT_RISK      — font_risky (FONT_RISKY_BMP)
5. BRAK_WCWIDTH   — biblioteka wcwidth niedostępna
6. OK             — żadne z powyższych
```

Kategoria **pierwsza pasująca** wygrywa. Dlatego `⚡` (U+26A1) jest
`FONT_RISK`, mimo że `U+26A1` jest też w `EMOJI_DEFAULT_BMP` —
bo `FONT_RISKY_BMP` jest sprawdzane **przed** `EMOJI_DEFAULT_BMP`.

---

## Kolejność ładowania (alfabetyczna)

| Prefix | Znaczenie | Pliki |
|---|---|---|
| `00_`–`09_` | fundamenty | `00_modifiers.json` |
| `10_`–`19_` | zakresy Unicode, kategorie główne | `10_emoji_ranges.json` |
| `20_`–`29_` | zbiory BMP emoji default | `20_emoji_default_bmp.json` |
| `25_` | astralne text-default | `25_astral_text_default.json` |
| `28_` | BMP font-risky | `28_font_risky_bmp.json` |
| `30_`–`39_` | BMP text-default | `30_text_default_bmp.json`, `35_small_symbols.json` |
| `40_`+ | kategorie tematyczne | (rezerwa) |
| `50_`+ | **własne** (domyślny prefix generatora) | (twój plugin) |

Kolejność ma znaczenie tylko dla `codepoints` (pierwszy wygrywa).
Dla `ranges` i `sets` — **unia** ze wszystkich pluginów (kolejność nie
ma znaczenia, chyba że duplikat — wtedy ostrzeżenie w `warnings`).

---

## Konwencje

- **Pliki zaczynające się od `_`** (np. ten `_README.md`) są pomijane.
- **Rozszerzenia inne niż `.json` / `.py`** są pomijane (`.bak`, `.txt`).
- **Nowy plugin** → prefix `50_` lub wyższy (nie nadpisuj wbudowanych).
- **Jeden plugin = jedna tematyka** (`20_emoji_default_bmp`,
  `28_font_risky_bmp`, `30_text_default_bmp`).
- **Duplikat w obrębie jednego pliku** — cichy (pierwszy wygrywa).
- **Duplikat między plikami** — ostrzeżenie w `loader.py`, ale nie
  blokuje (pierwszy wygrywa).

---

## Dodawanie nowego pluginu

### Ręcznie

```bash
cp emoji/wykrywanie/20_emoji_default_bmp.json \
   emoji/wykrywanie/50_moje.json
# edytuj 50_moje.json
python tools/gen_plugin.py validate
```

### Generatorem

```bash
python tools/gen_plugin.py detection moje_emoji --prefix 50_
# → emoji/wykrywanie/50_moje_emoji.json (pusty szablon)

# edytuj plik, potem:
python tools/gen_plugin.py validate
python tools/gen_plugin.py inspect moje_emoji
```

### Wizardem (interaktywnie)

```bash
python tools/emoji_wizard.py
# > a
# wklej znak → wizard rozpozna kategorię → zapisze do pluginu
```

---

## Format `label` (opcjonalne)

Pole `label` w `codepoints` i `ranges` **nie jest używane** przez
logikę (loader je ignoruje), ale:
- `tools/gen_plugin.py inspect` może je pokazać,
- `tools/emoji_wizard.py` pokazuje je w `s` (tabela z ikonami),
- `_README.md` może się do nich odwoływać.

Zalecane: **krótki opis po polsku** (max 80 znaków). Dla `codepoints`
dodatkowo warto podać, **czym się różni** od podobnych (np. `⚙` vs `⚙️`).

---

## Zobacz też

- `emoji/zamienniki/_README.md` — format pluginów zamienników,
- `emoji/loader.py` — jak pluginy są ładowane (sekcja `Konwencje`),
- `emoji/detection.py` — jak werdykty są liczone (`measure_both`),
- `tools/gen_plugin.py` — CLI generatora (`create`, `list`, `validate`, `inspect`),
- `tools/emoji_wizard.py` — interaktywne menu (`a`, `e`, `d`, `s`, `m`, `v`).
