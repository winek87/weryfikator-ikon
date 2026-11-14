"""
emoji.detection — czyste funkcje klasyfikacji i pomiaru szerokości.

Ten moduł **nie zawiera żadnych danych**. Wszystkie zbiory codepointów,
zakresy i mapy dostaje jako argumenty od `emoji.loader`.

Funkcje publiczne:

  * `classify(ch, codepoints, ranges)` — zwraca rodzaj znaku:
        "VS16" | "VS15" | "ZWJ" | "KEYCAP" | "EMOJI" | None
  * `measure_wcwidth(cluster)` — szerokość wg `wcwidth`
        (lub None, gdy biblioteka niedostępna)
  * `measure_heuristic(cluster, sets)` — szerokość wg heurystyki Unicode
        (bez `wcwidth`, deterministyczna)
  * `measure_both(cluster, sets, fragile_mode)` — oba pomiary + werdykty
        `rozjazd`, `text_default`, `fragile`, `font_risky`
  * `is_fragile_astral(ch, sets)` — czy znak jest astralnym
        `Emoji_Presentation=No` (kategoria FRAGILE)
  * `is_font_risky(ch, sets)` — czy znak jest BMP emoji z listy
        `FONT_RISKY_BMP` (kategoria FONT_RISK)

Flaga `HAS_WCWIDTH` mówi, czy biblioteka `wcwidth` jest dostępna.

Terminologia werdyktów (5 kategorii):

  * **ROZJAZD**  — `wcwidth` != heurystyka. Klasyczny bug „połówki”:
                   VS16 zmienia szerokość 1→2, a `wcwidth` tego nie widzi.
  * **MAŁA**     — BMP text presentation bez VS16. Szerokość OK (1==1),
                   ale glif jest mały i monochromatyczny (np. U+26A0).
  * **FRAGILE**  — astralny z Emoji_Presentation=No. Szerokość OK (2==2),
                   ale renderowanie zależy od fontu — może być ucięty
                   (np. U+1F6E1 shield).
  * **FONT_RISK**— BMP emoji z Emoji_Presentation=Yes (np. U+26A1 ⚡),
                   który w niektórych fontach renderuje się mało lub
                   tekstowo. Unicode mówi „duże”, font może kłamać.
  * **OK**       — żadne z powyższych.

Tryby FRAGILE (`fragile_mode`):

  * **"simple"** (domyślny) — `fragile` = True dla obu wariantów
        (z VS16 i bez). Reporter pokazuje jedną wiadomość.
  * **"split"**  — `fragile` = True dla obu wariantów, a reporter
        używa `fragile_no_vs16` / `fragile_with_vs16` do pokazania
        **dwóch różnych** komunikatów.
  * **"reporter"** — `fragile` = True **tylko** dla wariantu bez VS16.
        Reporter musi sam sprawdzić `fragile_with_vs16`, jeśli chce
        flagować wariant z VS16.

Uwaga o VS16 w trybie `reporter`:

  Wariant `🛡️` (U+1F6E1 U+FE0F) ma `fragile=False`, ale
  `fragile_with_vs16=True`. Reporter w trybie `reporter` może
  to wykorzystać do pokazania „FRAGILE — z VS16, font może ciąć”.
"""

from __future__ import annotations

# ── opcjonalna zależność: wcwidth ───────────────────────────────
try:
    from wcwidth import wcswidth as _wcswidth_raw  # type: ignore[import-not-found]
    HAS_WCWIDTH = True
except ImportError:  # pragma: no cover
    _wcswidth_raw = None
    HAS_WCWIDTH = False


# ── tryby FRAGILE ───────────────────────────────────────────────
FRAGILE_MODES = ("simple", "split", "reporter")
DEFAULT_FRAGILE_MODE = "simple"


# ── kody modyfikatorów ──────────────────────────────────────────
_CP_VS16 = 0xFE0F
_CP_VS15 = 0xFE0E
_CP_ZWJ = 0x200D
_CP_KEYCAP = 0x20E3
_MODIFIER_CPS = frozenset({_CP_VS16, _CP_VS15, _CP_ZWJ, _CP_KEYCAP})


# ── klasyfikacja znaku ──────────────────────────────────────────

def classify(
    ch: str,
    codepoints: dict[int, str] | None = None,
    ranges: list[tuple[int, int]] | None = None,
) -> str | None:
    """
    Klasyfikuje pojedynczy znak.

    Zwraca "VS16" | "VS15" | "ZWJ" | "KEYCAP" | "EMOJI" | None.
    """
    if not ch:
        return None

    cp = ord(ch[0])

    if codepoints:
        kind = codepoints.get(cp)
        if kind:
            return kind
    else:
        if cp == _CP_VS16:
            return "VS16"
        if cp == _CP_VS15:
            return "VS15"
        if cp == _CP_ZWJ:
            return "ZWJ"
        if cp == _CP_KEYCAP:
            return "KEYCAP"

    if ranges:
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return "EMOJI"

    return None


# ── metoda 1: wcwidth ──────────────────────────────────────────

def measure_wcwidth(cluster: str) -> int | None:
    """Szerokość wg `wcwidth` lub None, gdy niedostępna/błąd."""
    if not HAS_WCWIDTH or _wcswidth_raw is None:
        return None
    try:
        v = _wcswidth_raw(cluster)
    except Exception:  # noqa: BLE001
        return None
    return v if v >= 0 else None


# ── metoda 2: heurystyka ───────────────────────────────────────

def measure_heuristic(
    cluster: str,
    sets: dict[str, set[int]] | None = None,
) -> int:
    """
    Szerokość wg heurystyki Unicode (bez `wcwidth`).

    `ASTRAL_TEXT_DEFAULT`, `TEXT_DEFAULT_BMP` i `FONT_RISKY_BMP`
    **nie** wpływają na szerokość — wpływają na werdykt w `measure_both`.
    """
    if not cluster:
        return 0

    cps = [ord(c) for c in cluster]
    cps_set = set(cps)

    if _CP_VS15 in cps_set:
        return 1
    if _CP_VS16 in cps_set:
        return 2
    if _CP_ZWJ in cps_set:
        return 2

    emoji_default_bmp = (sets or {}).get("EMOJI_DEFAULT_BMP", set())

    if len(cps) == 1:
        cp = cps[0]
        if cp > 0xFFFF:
            return 2
        if cp in emoji_default_bmp:
            return 2
        return 1

    return sum(measure_heuristic(c, sets) for c in cluster)


# ── rozpoznanie astralnych FRAGILE ─────────────────────────────

def is_fragile_astral(
    ch: str,
    sets: dict[str, set[int]] | None = None,
) -> bool:
    """Czy `ch` to astralny znak z `Emoji_Presentation=No`?"""
    if not ch:
        return False
    cp = ord(ch[0])
    astral_bmp = (sets or {}).get("ASTRAL_TEXT_DEFAULT", set())
    return cp in astral_bmp


# ── rozpoznanie BMP FONT_RISK ──────────────────────────────────

def is_font_risky(
    ch: str,
    sets: dict[str, set[int]] | None = None,
) -> bool:
    """
    Czy `ch` to BMP emoji z listy `FONT_RISKY_BMP`?

    Takie znaki mają `Emoji_Presentation=Yes` (Unicode mówi „duże”),
    ale w niektórych fontach (Font Awesome, nerd-fonty, starsze fonty
    bez Noto Color Emoji) renderują się mało lub tekstowo.

    Klasyczny przykład: U+26A1 (⚡ błyskawica).

    Parametry:
        ch:    pojedynczy znak (bazowy, bez modyfikatorów),
        sets:  mapa zbiorów z loadera. Wykorzystujemy `FONT_RISKY_BMP`.

    Zwraca False dla pustego wejścia lub gdy zbiór nie jest zdefiniowany.
    """
    if not ch:
        return False
    cp = ord(ch[0])
    risky = (sets or {}).get("FONT_RISKY_BMP", set())
    return cp in risky


# ── pomiar łączony z trybem FRAGILE + FONT_RISK ────────────────

def measure_both(
    cluster: str,
    sets: dict[str, set[int]] | None = None,
    fragile_mode: str = DEFAULT_FRAGILE_MODE,
) -> dict:
    """
    Łączy obie metody i wystawia werdykty.

    Parametry:
        cluster:       klaster znaków (np. "⚙️", "🛡️", "🔧"),
        sets:          mapa zbiorów z loadera,
        fragile_mode:  "simple" | "split" | "reporter" (domyślnie "simple").

    Zwraca dict:
        {
          "wcwidth":           int | None,
          "heurystyka":        int,
          "rozjazd":           bool,
          "text_default":      bool,
          "fragile":           bool,   # zależne od fragile_mode
          "fragile_no_vs16":   bool,   # zawsze obliczane
          "fragile_with_vs16": bool,   # zawsze obliczane
          "fragile_mode":      str,
          "font_risky":        bool,   # BMP z FONT_RISKY_BMP
        }

    Przykłady (fragile_mode="simple"):
      * `🛡`   → fragile=True,  fragile_no_vs16=True,  fragile_with_vs16=False
      * `🛡️`  → fragile=True,  fragile_no_vs16=False, fragile_with_vs16=True
      * `⚡`   → font_risky=True (U+26A1 w FONT_RISKY_BMP)
      * `🔧`  → wszystkie False → OK
    """
    if fragile_mode not in FRAGILE_MODES:
        fragile_mode = DEFAULT_FRAGILE_MODE

    w_wc = measure_wcwidth(cluster)
    w_h = measure_heuristic(cluster, sets)

    rozjazd = (w_wc is not None) and (w_wc != w_h)

    cps = [ord(c) for c in cluster]
    cps_set = set(cps)

    text_default_bmp = (sets or {}).get("TEXT_DEFAULT_BMP", set())
    text_default = (
        len(cps) == 1
        and cps[0] in text_default_bmp
        and _CP_VS16 not in cps_set
    )

    astral_fragile = (sets or {}).get("ASTRAL_TEXT_DEFAULT", set())
    fragile_no_vs16 = (
        len(cps) == 1
        and cps[0] in astral_fragile
        and _CP_VS16 not in cps_set
    )
    fragile_with_vs16 = (
        len(cps) == 2
        and cps[0] in astral_fragile
        and cps[1] == _CP_VS16
    )

    if fragile_mode == "reporter":
        fragile = fragile_no_vs16
    else:  # "simple" lub "split"
        fragile = fragile_no_vs16 or fragile_with_vs16

    font_risky_bmp = (sets or {}).get("FONT_RISKY_BMP", set())
    font_risky = (
        len(cps) == 1
        and cps[0] in font_risky_bmp
    )

    return {
        "wcwidth": w_wc,
        "heurystyka": w_h,
        "rozjazd": rozjazd,
        "text_default": text_default,
        "fragile": fragile,
        "fragile_no_vs16": fragile_no_vs16,
        "fragile_with_vs16": fragile_with_vs16,
        "fragile_mode": fragile_mode,
        "font_risky": font_risky,
    }


# ── pomocnicze ─────────────────────────────────────────────────

def is_modifier_cp(cp: int) -> bool:
    """Czy codepoint jest modyfikatorem klastra (VS16/VS15/ZWJ/KEYCAP)?"""
    return cp in _MODIFIER_CPS


__all__ = [
    "HAS_WCWIDTH",
    "FRAGILE_MODES",
    "DEFAULT_FRAGILE_MODE",
    "classify",
    "measure_wcwidth",
    "measure_heuristic",
    "measure_both",
    "is_fragile_astral",
    "is_font_risky",
    "is_modifier_cp",
]
