# Pluginy zamienników — CZYM zastępować

Ten folder zawiera pluginy, które mówią skanerowi, **jaki znak
zaproponować** w miejsce problematycznego emoji. Każdy plugin to plik
`.json` lub `.py`. Pliki ładowane są alfabetycznie (prefixy `10_`,
`20_`, `30_`…). Przy duplikacie **pierwszy wygrywa** — wbudowane
definicje mają niższe numery, więc twój własny plugin z prefiksem
`50_` nie nadpisze domyślnych.

---

## Format `.json`

```json
{
  "name": "warnings",
  "description": "Zamienniki dla emoji ostrzeżeń",
  "version": "1.0",
  "replacements": {
    "⚠": {
      "rec": "🚨",
      "alt": ["❗", "[!]"],
      "why": "U+1F6A8 emoji default; ⚠ mały (text), ⚠️ wymaga VS16"
    }
  }
}
```

### Pola wpisu

- **`rec`** (wymagane) — zalecany zamiennik (`str`).
  - Może być `"(usuń)"` dla modyfikatorów (VS16, VS15, ZWJ, KEYCAP),
    które nie mają sensownego zamiennika graficznego.
  - Może być `null` — wtedy skaner pokaże tylko `why` (bez rekomendacji).
- **`alt`** (opcjonalne) — lista alternatyw (`list[str]`). Domyślnie `[]`.
  - Wartości ASCII (`[v]`, `[!]`) są cenne dla kontekstów bez emoji.
  - Wartości emoji powinny być **emoji default** (astralne lub BMP
    z `Emoji_Presentation=Yes`), **nie** warianty z VS16.
- **`why`** (opcjonalne) — krótkie uzasadnienie (`str`). Wyświetlane
  w raporcie i w tabeli z ikonami.

---

## Format `.py`

```python
NAME = "warnings"
DESCRIPTION = "Zamienniki dla emoji ostrzeżeń"
VERSION = "1.0"

REPLACEMENTS = {
    "⚠": {
        "rec": "🚨",
        "alt": ["❗", "[!]"],
        "why": "U+1F6A8 emoji default; ⚠ mały (text)",
    },
}
```

**Uwaga:** `.py` **nie jest modyfikowany automatycznie** przez wizard
ani generator — tylko przez `[e]` (edytor). Powód: automatyczna edycja
zniszczyłaby komentarze i strukturę.

---

## Klucz mapy — **zawsze bazowy znak**

Kluczem jest **bazowy znak** — bez VS16 i innych modyfikatorów.

| Dobrze | Źle | Dlaczego |
|---|---|---|
| `"⚙"` (U+2699) | `"⚙️"` (U+2699+FE0F) | Skaner normalizuje do bazy |
| `"⚠"` (U+26A0) | `"⚠️"` (U+26A0+FE0F) | j.w. |
| `"✓"` (U+2713) | `"✓️"` (U+2713+FE0F) | j.w. |
| `"🔧"` (U+1F527) | `"🔧️"` (nie ma wariantu) | Astralne nie mają VS16 |

**Loader normalizuje klucze** w `_merge_replacements` — jeśli plugin
ma `"✓️"` (z VS16), zostanie zapisany jako `"✓"` i dostaniesz
ostrzeżenie w `warnings`. Ale **lepiej zapisywać od razu poprawnie** —
unikniesz ostrzeżeń i duplikatów.

**Nie dodawaj wariantu z VS16**, bo:
1. To ta sama ikona wizualnie (jeśli font nie ma glifu, VS16 nie pomoże).
2. Duplikuje pozycję w `_proposals_for` (`⚡` i `⚡️` to dwa stringi).
3. `_normalize_key` normalizuje **klucze**, ale **nie wartości w `alt`**.

---

## Hierarchia sugerowania w `suggest_for`

```
1. Wpis w pluginie       → rec + alt + why (najbardziej konkretne)
2. BMP znak (U+2000–FFFF) → fallback „dodaj wpis w pluginie"
3. Astralny (> U+FFFF)    → fallback „prawdopodobnie OK"
4. Modyfikator (VS16 itd.) → rec: "(usuń)"
```

W `PROPONOWANE ZMIANY` (`_proposals_for`) dochodzi:

```
5. Rodzeństwo z rec       → filtrowane przez `bad_chars` (TEXT_DEFAULT_BMP ∪ ASTRAL_TEXT_DEFAULT)
6. Pad [ ? ]              → tylko gdy `target=5` (interaktywny wybór)
```

---

## Standardowe kategorie zamienników

### `10_settings.json` — ustawienia, foldery, konfiguracja

Klucze: `⚙ 🗂 🗀 🗃 🗄 🛠 🗜`

### `20_warnings.json` — ostrzeżenia, błędy, potwierdzenia

Klucze: `⚠ ✔ ✖ ✗ ☑ ☒ ✓ ☠ ⁉ ‼`

**Uwaga:** `✓` i `✗` są w `35_small_symbols.json` (detekcja), ale
zamienniki są tutaj. To celowe rozdzielenie: **detekcja osobno,
zamiana osobno**. Ten sam znak może być wykryty przez jeden plugin,
a zamiennik zdefiniowany w innym.

### `30_media.json` — media, odtwarzanie, przyciski

Klucze: `▶ ⏸ ⏭ ⏮ ⏹ ⏺ ⏏ 🎬`

Dla `⏸ ⏹ ⏏` zalecany zamiennik to **ASCII** (`[||]`, `[#]`, `[^]`) —
brak dobrego emoji default. Dla `⏭ ⏮` — `⏩`/`⏪` (fast forward/reverse,
U+23E9/U+23EA, emoji default).

### `40_misc.json` — pogoda, komunikacja, symbole, narzędzia

Klucze: `☀ ☁ ☂ ☎ ✉ ❤ ♥ ✏ ✎ ★ ☆ ✂ ⌚ ⌛ ⏰ 🔧 ⚡ ⭐ ⭕ ✅ ❌ ❓ ❗`
+ `FRAGILE`: `🛡 🗡 🕯 🕰 🕵 🕶 🕹 🖥 🖨 🖱 🖼 🗑 🗒 🗓 🗝 🗞 🗣 🗺 🛋 🛍 🛎 🛏 🛢 🛤 🛥 🛰 🛳 🕷`
+ `FONT_RISK`: `⚡`

---

## Zasady `rec` — bezpieczne cele

**`rec` powinno być emoji default** — najlepiej **astralne**
(U+10000+), bo renderują się duże w **każdym** terminalu i foncie.

| Bezpieczne (astralne) | Ryzykowne (BMP) |
|---|---|
| 🔋 U+1F50B | ⚡ U+26A1 (FONT_RISK) |
| 🚨 U+1F6A8 | ⚠ U+26A0 (MAŁA) |
| 🔧 U+1F527 | ⚙ U+2699 (MAŁA) |
| ✅ U+2705 | ✔ U+2714 (MAŁA) |
| ❌ U+274C | ✖ U+2716 (MAŁA) |

**Nigdy nie używaj `⚠️` (z VS16) jako `rec`** — to leczy jeden bug
i wprowadza drugi (ROZJAZD). Zamiast tego użyj `🚨` (astralny).

---

## Dodawanie nowego zamiennika

### Ręcznie

```bash
# edytuj emoji/zamienniki/40_misc.json
python tools/gen_plugin.py validate
```

### Generatorem

```bash
python tools/gen_plugin.py replacement moje_emoji --prefix 50_
# → emoji/zamienniki/50_moje_emoji.json (pusty szablon)
```

### Wizardem — nowy wpis

```bash
python tools/emoji_wizard.py
# > a
# wklej znak → wizard rozpozna kategorię → zapisze do pluginu
```

### Wizardem — dopisz ikony do istniejącego wpisu

```bash
python tools/emoji_wizard.py
# > m
# wklej znak → wizard znajdzie wpis → slot po slocie dodasz ikony
```

### Wizardem — modyfikacja istniejącego wpisu

```bash
python tools/emoji_wizard.py
# > e
# wybierz plugin → edytuj w $EDITOR
```

---

## Konwencje

- **Pliki zaczynające się od `_`** (np. ten `_README.md`) są pomijane.
- **Nowy plugin** → prefix `50_` lub wyższy (nie nadpisuj wbudowanych).
- **Jeden plik = jedna tematyka** (`10_settings`, `20_warnings`, `30_media`).
- **Duplikat między plikami** — ostrzeżenie w `loader.py` (pierwszy wygrywa).
- **Klucz bazowy** — bez VS16 (loader normalizuje, ale lepiej zapisywać od razu poprawnie).
- **`rec` emoji default** — astralne lub BMP z `Emoji_Presentation=Yes`.
- **Nigdy nie używaj `⚠️` (z VS16)** jako `rec` — to leczy jeden bug i wprowadza drugi.

---

## Format `label` (opcjonalne)

Pole `label` **nie istnieje** w pluginach zamienników — to tylko
detekcja. W zamiennikach liczy się `rec`, `alt`, `why`.

---

## Zobacz też

- `emoji/wykrywanie/_README.md` — format pluginów detekcji,
- `emoji/loader.py` — jak pluginy są ładowane (sekcja `Konwencje`),
- `emoji/reporter.py` — jak werdykty są liczone (`_verdict_of`, `suggest_for`),
- `emoji/generator.py` — funkcje `add_replacement_to_plugin`, `update_replacement_in_plugin`,
- `tools/gen_plugin.py` — CLI generatora (`create`, `list`, `validate`, `inspect`),
- `tools/emoji_wizard.py` — interaktywne menu (`a`, `e`, `d`, `s`, `m`, `v`).
