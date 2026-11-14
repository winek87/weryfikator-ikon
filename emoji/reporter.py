#!/usr/bin/env python3

# emoji/reporter.py
# -*- coding: utf-8 -*-

"""
emoji.reporter — formatowanie wyników skanu na wyjście tekstowe.

Ten moduł nic nie skanuje i nie mierzy — dostaje gotowe wyniki z
`emoji.scanner.scan()` i zamienia je na tekst czytelny dla człowieka.
Dzięki temu można dopisać własny reporter (JSON, CSV, GitHub Actions
annotations) bez ruszania reszty pakietu.

Funkcje publiczne:

  * `suggest_for(ch, kind, replacements)` — sugestia zamiennika
        (rec + alt + why) dla pojedynczego znaku,
  * `print_report(results, replacements, show_suggestions=True)` —
        szczegółowy raport per-znalezisko,
  * `print_summary(results, replacements, has_wcwidth=True, bad_chars=None)`
        — podsumowanie zbiorcze: ranking znaków, porównanie metod,
        proponowane zmiany.

Werdykty (`_verdict_of`, kolejność sprawdzania ma znaczenie):

  1. `ROZJAZD`      — wcwidth != heurystyka (bug „połówki” przez VS16),
  2. `MAŁA`         — BMP text presentation bez VS16 (np. U+26A0),
  3. `FRAGILE`      — astral Emoji_Presentation=No (np. U+1F6E1),
  4. `FONT_RISK`    — BMP emoji, font może renderować mało (np. U+26A1 ⚡),
  5. `BRAK_WCWIDTH` — biblioteka niedostępna,
  6. `OK`           — żaden problem.

Trzy sekcje w `print_summary`:

  1. PODSUMOWANIE ZNALEZISK — ranking znaków wg częstości,
     z niezależnymi licznikami problemów (ROZJAZD / MAŁA / FRAGILE).
     Liczniki są **niezależne per pole**, więc znalezisko z
     `rozjazd=True` **i** `fragile=True` (np. 🕷 U+1F577) pokaże
     oba problemy naraz.

  2. PORÓWNANIE METOD — ile pomiarów zgodnych, ile ROZJAZD,
     ile MAŁA, ile FRAGILE (z rozbiciem na warianty), ile bez wcwidth.

  3. PROPONOWANE ZMIANY — dla każdego znaleziska z werdyktem
     ROZJAZD / MAŁA / FRAGILE lista propozycji zamiennika.
     **Bez limitu** (`target=None`) — pokazuje wszystko, co jest
     w pluginie (`rec` + `alt` + rodzeństwo z tym samym `rec`).

Historia zmian:

  **v3.6**

  * `suggest_for` — próg BMP z `0x2000` na `0x00A0`. Wcześniej § © ® ° €
    itd. wpadały w fallback „astralny" (`rec=ch`), co było mylące.
    Teraz dostają `rec=None` + „dodaj wpis w pluginie zamienników".
  * `suggest_for` — `alt` w fallbacku BMP: `["[?]", "dodaj wpis w pluginie"]`
    (zamiast „usuń VS16", bo to nie dotyczy VS16).

  **v3.5**

  * Nowy werdykt `FONT_RISK` — BMP emoji z `FONT_RISKY_BMP`
    (Emoji_Presentation=Yes, ale font może renderować mało).
  * `_verdict_of` — FONT_RISK sprawdzane po FRAGILE, przed
    BRAK_WCWIDTH.
  * `print_summary` — licznik `font_risky_total` w PORÓWNANIU METOD
    i badge `FONT_RISK xN` w rankingu znaków.
  * `PROPONOWANE ZMIANY` — FONT_RISK dodane do filtra werdyktów.
  * **Nie rusza** `bad_chars` (filtrowanie rodzeństwa z v3.4) —
    `FONT_RISKY_BMP` **nie jest** w `bad_chars`, bo to emoji default,
    tylko ryzykowne fontowo. Rodzeństwo z rec FONT_RISK może być
    proponowane.

  **v3.4**

  * `_proposals_for` — nowy parametr `bad_chars: set[str] | None`.
    Jeśli podany, **rodzeństwo** (`podobny`) jest filtrowane:
    znaki z `bad_chars` nie są proponowane jako podobne, ale ich
    `alt` (np. `[X]` ASCII) nadal trafia na listę — bo ASCII jest
    zawsze bezpieczne.
  * `print_summary` — nowy parametr `bad_chars`, przekazywany do
    `_proposals_for`.
  * `scan_emoji.py` buduje `bad_chars` z `TEXT_DEFAULT_BMP` ∪
    `ASTRAL_TEXT_DEFAULT` i przekazuje do `print_summary`. Efekt:
    dla `✓` (MAŁA) nie proponujemy `✔` i `☑` (oba MAŁA) — tylko
    ich ASCII `alt` (`[X]`).

  **v3.3**

  * `_proposals_for` — `target: int | None`. `print_summary` woła
    z `target=None` (bez limitu, bez pada `[?]`).

  **v3.2**

  * `_proposals_for` — 5 propozycji z `rec` + `alt` + rodzeństwo.
  * Sekcja `PROPONOWANE ZMIANY` w `print_summary`.

  **v3.1**

  * `print_summary` — niezależne liczniki problemów per pole.

  **v3.0**

  * Werdykt `FRAGILE` — astralne Emoji_Presentation=No.
  * Trzy tryby FRAGILE (`simple` / `split` / `reporter`).
"""

from __future__ import annotations

from collections import Counter, defaultdict

# ── sugestie zamienników ────────────────────────────────────────

def suggest_for(
    ch: str,
    kind: str,
    replacements: dict[str, dict] | None = None,
) -> dict | None:
    """
    Zwraca sugestię zamiennika dla znalezionego znaku.

    Parametry:
        ch:            bazowy znak (np. "⚙", "⚠", "🛡"),
        kind:          rodzaj z `classify` ("EMOJI", "VS16", ...),
        replacements:  mapa z `load_replacements()["replacements"]`.

    Zwraca dict:
        {"rec": str | None, "alt": [str], "why": str} lub None.

    Dla modyfikatorów (VS16 itd.) zwraca wpis "(usuń)" — bo same
    są niewidoczne, nie mają sensownego zamiennika graficznego.

    Dla nieznanych znaków BMP (U+00A0–U+FFFF) — fallback z komunikatem
    „dodaj wpis w pluginie zamienników". Dla astralnych (U+10000+) —
    „prawdopodobnie OK".

    Uwaga: BMP obejmuje § © ® ° € ™ itd. — wszystkie poniżej U+2000.
    Wcześniejszy próg 0x2000 pomijał je, przez co dostawały `rec=ch`
    (jak astralne). To było mylące — one nie są astralne i nie
    „prawdopodobnie OK", tylko wymagają wpisu w pluginie.
    """
    if not ch:
        return None

    if kind in ("VS16", "VS15", "ZWJ", "KEYCAP"):
        return {
            "rec": "(usuń)",
            "alt": [],
            "why": f"{kind} — modyfikator, sam jest niewidzialny",
        }

    if replacements:
        entry = replacements.get(ch)
        if entry and isinstance(entry, dict) and "rec" in entry:
            return {
                "rec": entry.get("rec"),
                "alt": list(entry.get("alt") or []),
                "why": str(entry.get("why", "")),
            }

    cp = ord(ch)
    # BMP = U+00A0..U+FFFF (po znakach kontrolnych Latin-1).
    # Wcześniej było 0x2000, co pomijało §, ©, ®, °, € itd.
    # — wpadały w fallback „astralny" z rec=ch, co było mylące.
    if 0x00A0 <= cp <= 0xFFFF:
        return {
            "rec": None,
            "alt": ["[?]", "dodaj wpis w pluginie"],
            "why": (
                "BMP — zwykle wymaga VS16 i „kurczy się” w terminalu; "
                "dodaj wpis w pluginie zamienników"
            ),
        }

    return {
        "rec": ch,
        "alt": [],
        "why": "astralny — prawdopodobnie OK (sprawdź wizualnie)",
    }


# ── rozpoznanie werdyktu ────────────────────────────────────────

def _verdict_of(r: dict) -> str:
    """
    Zwraca **jeden** werdykt dla pojedynczego wyniku.

    Możliwe wartości: "ROZJAZD" | "MAŁA" | "FRAGILE" | "FONT_RISK"
                     | "BRAK_WCWIDTH" | "OK".

    Kolejność sprawdzania (ważna!):
        1. ROZJAZD  — bug szerokości, najgroźniejszy
        2. MAŁA     — bug glifu BMP text-default
        3. FRAGILE  — bug glifu astralnego
        4. FONT_RISK — BMP emoji, font może renderować mało
        5. BRAK_WCWIDTH — informacyjny
        6. OK
    """
    if r.get("rozjazd"):
        return "ROZJAZD"

    if r.get("text_default"):
        return "MAŁA"

    mode = r.get("fragile_mode", "simple")

    if mode == "simple":
        if r.get("fragile"):
            return "FRAGILE"
    elif mode == "split":
        if r.get("fragile_no_vs16") or r.get("fragile_with_vs16"):
            return "FRAGILE"
    elif mode == "reporter":
        if r.get("fragile") or r.get("fragile_with_vs16"):
            return "FRAGILE"

    if r.get("font_risky"):
        return "FONT_RISK"

    if r.get("wcwidth") is None:
        return "BRAK_WCWIDTH"

    return "OK"


def _fragile_detail(r: dict) -> str:
    """
    Zwraca komunikat dla werdyktu FRAGILE, zależny od trybu.
    """
    mode = r.get("fragile_mode", "simple")

    if mode == "simple":
        return "astral Emoji_Presentation=No — font może ciąć"

    if r.get("fragile_no_vs16"):
        return "astral bez VS16 — będzie mały/tekstowy"
    if r.get("fragile_with_vs16"):
        return "astral z VS16 — font może ciąć"
    return "astral Emoji_Presentation=No — font może ciąć"


# ── pomocnicze formatowanie ─────────────────────────────────────

def _fmt_width(value: int | None) -> str:
    """Formatuje szerokość do kolumny o stałej szerokości."""
    return "—" if value is None else str(value)


def _verdict_line(r: dict) -> str:
    """
    Zwraca pojedynczą linię z porównaniem metod + werdykt.
    """
    wc = _fmt_width(r.get("wcwidth"))
    he = _fmt_width(r.get("heurystyka"))
    verdict = _verdict_of(r)

    if verdict == "ROZJAZD":
        msg = "ROZJAZD — kurczy się przez VS16"
    elif verdict == "MAŁA":
        msg = "MAŁA — text presentation (potrzebuje zamiennika)"
    elif verdict == "FRAGILE":
        msg = f"FRAGILE — {_fragile_detail(r)}"
    elif verdict == "FONT_RISK":
        msg = "FONT_RISK — BMP emoji, font może renderować mało"
    elif verdict == "BRAK_WCWIDTH":
        msg = "(brak biblioteki wcwidth — tylko heurystyka)"
    else:
        msg = "OK — zgodne"

    return f"   ↳ wcwidth={wc}  |  heurystyka={he}   {msg}"


# ── raport szczegółowy ──────────────────────────────────────────

def print_report(
    results: list[dict],
    replacements: dict[str, dict] | None = None,
    show_suggestions: bool = True,
    out=None,
) -> None:
    """
    Wypisuje szczegółowy raport per-znalezisko.

    Parametry:
        results:           lista z `scan()["results"]`,
        replacements:      mapa z `load_replacements()["replacements"]`,
        show_suggestions:  False → pomiń sekcję „zalecany/alternatywy”,
        out:               strumień wyjściowy (domyślnie `sys.stdout`).
    """
    import sys

    if out is None:
        out = sys.stdout

    for r in results:
        head = (
            f"{r['file']}:{r['line']}:{r['col']}  "
            f"[{r['kind']}] {r['cp']}  {r['ch']!r}"
        )
        if r.get("cluster") and r["cluster"] != r["ch"]:
            head += f"  (klaster: {r['cluster']!r})"
        print(head, file=out)

        print(_verdict_line(r), file=out)

        if show_suggestions:
            s = suggest_for(r["ch"], r["kind"], replacements)
            if s:
                rec = s.get("rec")
                alt = s.get("alt") or []
                why = s.get("why", "")

                if rec and rec != r["ch"]:
                    print(f"   ↳ zalecany:  {rec}    ({why})", file=out)
                elif rec and rec == r["ch"] and not alt:
                    print(f"   ↳ OK — nie wymaga zmiany  ({why})", file=out)
                elif why:
                    print(f"   ↳ {why}", file=out)

                if alt:
                    print(
                        f"   ↳ alternatywy: {', '.join(map(str, alt))}",
                        file=out,
                    )

        if r.get("context"):
            print(f"   … {r['context']}", file=out)

        print(file=out)


# ── proponowane zmiany (v3.2) ───────────────────────────────────

def _proposals_for(
    ch: str,
    kind: str,
    replacements: dict[str, dict] | None,
    target: int | None = 5,
    bad_chars: set[str] | None = None,
) -> list[tuple[str, str]]:
    """
    Zwraca propozycje zamiennika jako listę (wartość, etykieta).

    Parametry:
        ch:            bazowy znak (np. "🛡"),
        kind:          rodzaj z `classify` ("EMOJI", ...),
        replacements:  mapa z `load_replacements()["replacements"]`,
        target:        limit propozycji:
                         int  → dokładnie tyle (z padem `[?]`),
                         None → **wszystkie** dostępne (bez pada),
        bad_chars:     zbiór znaków, których **nie** chcemy proponować
                       jako rodzeństwo (np. wszystkie `TEXT_DEFAULT_BMP`
                       i `ASTRAL_TEXT_DEFAULT`). Ich `alt` (ASCII) nadal
                       trafia na listę — ASCII jest bezpieczne.

    Kolejność źródeł:
      1. własny `rec`                    → "zalecany" (NIE filtrowany),
      2. własne `alt` (0–N)              → "alternatywa" (NIE filtrowany),
      3. inne znaki z tym samym `rec`    → "podobny" (FILTROWANY
                                           przez `bad_chars`),
      4. ich `alt`                        → "podobny" (NIE filtrowany,
                                           bo ASCII jest bezpieczne),
      5. pad `[?]`                       → "wpisz własny"
         (tylko gdy `target` ustawiony).

    Deduplikuje wartości — ten sam znak nie pojawi się dwa razy.
    Pomija wartość równą `ch` (nie proponujemy tego samego znaku).

    Przykłady:
        Dla `✓` (MAŁA), rec=✅, alt=[v],[Y]:
          - rec ✅                       → zalecany
          - [v], [Y]                     → alternatywa
          - rodzeństwo: ✔ (MAŁA) — pominięty, ale [X] z ✔.alt → podobny
          - rodzeństwo: ☑ (MAŁA) — pominięty, ale [X] z ☑.alt → podobny
          Wynik: ✅, [v], [Y], [X]  (bez ✔ i ☑)
    """
    # Fallback dla pustych wejść — jeden pad (nie ma czego proponować).
    if not ch or not replacements:
        return [("[?]", "wpisz własny")]

    own = replacements.get(ch)
    if not isinstance(own, dict):
        return [("[?]", "wpisz własny")]

    rec = str(own.get("rec") or "").strip()
    alts = [str(a).strip() for a in (own.get("alt") or [])]
    bad = bad_chars or set()

    proposals: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(value: str, label: str) -> None:
        value = value.strip()
        if not value or value in seen or value == ch:
            return
        if target is not None and len(proposals) >= target:
            return
        seen.add(value)
        proposals.append((value, label))

    # 1) własny rec — zawsze proponowany (jawny wybór użytkownika)
    _add(rec, "zalecany")

    # 2) własne alt — zawsze proponowane (jawny wybór użytkownika)
    for a in alts:
        _add(a, "alternatywa")

    # 3) rodzeństwo — filtrowane przez bad_chars
    if rec:
        for other_ch, other in replacements.items():
            if other_ch == ch or not isinstance(other, dict):
                continue
            if str(other.get("rec") or "").strip() != rec:
                continue

            # Sam znak rodzeństwa — pomiń jeśli w bad_chars.
            # (np. ✔ i ☑ są w TEXT_DEFAULT_BMP → pomijamy)
            if other_ch not in bad:
                _add(other_ch, "podobny")

            # alt rodzeństwa — NIE filtrujemy, bo to mogą być ASCII
            # (np. [X] z ☒.alt jest bezpieczne i przydatne).
            for a in other.get("alt") or []:
                _add(str(a), "podobny")

            if target is not None and len(proposals) >= target:
                break

    # 4) pad do target (tylko gdy target ustawiony)
    if target is not None:
        while len(proposals) < target:
            proposals.append(("[?]", "wpisz własny"))
        return proposals[:target]

    return proposals


# ── podsumowanie zbiorcze ───────────────────────────────────────

def print_summary(
    results: list[dict],
    replacements: dict[str, dict] | None = None,
    has_wcwidth: bool = True,
    bad_chars: set[str] | None = None,
    out=None,
) -> None:
    """
    Wypisuje podsumowanie zbiorcze.

    Parametry:
        results:      lista z `scan()["results"]`,
        replacements: mapa z `load_replacements()["replacements"]`,
        has_wcwidth:  czy biblioteka wcwidth była dostępna,
        bad_chars:    zbiór znaków do filtrowania rodzeństwa w sekcji
                      PROPONOWANE ZMIANY. Zazwyczaj
                      `TEXT_DEFAULT_BMP ∪ ASTRAL_TEXT_DEFAULT`
                      (buduje `scan_emoji.py`).
        out:          strumień wyjściowy.

    Trzy sekcje:

      1. PODSUMOWANIE ZNALEZISK — ranking znaków wg częstości,
         z niezależnymi licznikami problemów (ROZJAZD, MAŁA, FRAGILE).

      2. PORÓWNANIE METOD — ile pomiarów zgodnych, ile ROZJAZD,
         ile MAŁA, ile FRAGILE (z rozbiciem na warianty), ile bez wcwidth.

      3. PROPONOWANE ZMIANY — dla każdego znaleziska z werdyktem
         ROZJAZD / MAŁA / FRAGILE lista propozycji zamiennika.
         Bez limitu (`target=None`). Rodzeństwo filtrowane przez
         `bad_chars`.
    """
    import sys

    if out is None:
        out = sys.stdout

    if not results:
        print("Brak znalezisk.", file=out)
        return

    # ── sekcja 1: ranking znaków ────────────────────────────────
    counter = Counter((r["cp"], r["ch"], r["kind"]) for r in results)

    rozjazd_per: dict[tuple[str, str], int] = defaultdict(int)
    mala_per: dict[tuple[str, str], int] = defaultdict(int)
    fragile_per: dict[tuple[str, str], int] = defaultdict(int)
    font_risky_per: dict[tuple[str, str], int] = defaultdict(int)

    for r in results:
        key = (r["cp"], r["kind"])
        if r.get("rozjazd"):
            rozjazd_per[key] += 1
        if r.get("text_default"):
            mala_per[key] += 1
        if r.get("fragile") or r.get("fragile_with_vs16"):
            fragile_per[key] += 1
        if r.get("font_risky"):
            font_risky_per[key] += 1

    print("── PODSUMOWANIE ZNALEZISK ──", file=out)
    for (cp, ch, kind), count in counter.most_common():
        s = suggest_for(ch, kind, replacements) or {}
        rec = s.get("rec") or "—"

        badges: list[str] = []
        if rozjazd_per.get((cp, kind)):
            badges.append(f"ROZJAZD x{rozjazd_per[(cp, kind)]}")
        if mala_per.get((cp, kind)):
            badges.append(f"MAŁA x{mala_per[(cp, kind)]}")
        if fragile_per.get((cp, kind)):
            badges.append(f"FRAGILE x{fragile_per[(cp, kind)]}")
        if font_risky_per.get((cp, kind)):
            badges.append(f"FONT_RISK x{font_risky_per[(cp, kind)]}")
        badge_str = ("  " + "  ".join(badges)) if badges else ""

        print(
            f"  {ch!r} {cp:>8} [{kind:<6}] x{count:<3}  →  {rec}{badge_str}",
            file=out,
        )
    print(file=out)

    # ── sekcja 2: porównanie metod ──────────────────────────────
    total = len(results)
    rozjazd_total = 0
    mala_total = 0
    fragile_total = 0
    fragile_no_total = 0
    fragile_with_total = 0
    font_risky_total = 0
    bez_wc = 0

    for r in results:
        v = _verdict_of(r)
        if v == "ROZJAZD":
            rozjazd_total += 1
        elif v == "MAŁA":
            mala_total += 1
        elif v == "FRAGILE":
            fragile_total += 1
            if r.get("fragile_no_vs16"):
                fragile_no_total += 1
            if r.get("fragile_with_vs16"):
                fragile_with_total += 1
        elif v == "FONT_RISK":
            font_risky_total += 1
        if r.get("wcwidth") is None:
            bez_wc += 1

    zgodne = (
        total
        - rozjazd_total
        - mala_total
        - fragile_total
        - font_risky_total
        - bez_wc
    )
    if zgodne < 0:
        zgodne = 0

    print("── PORÓWNANIE METOD ──", file=out)
    if not has_wcwidth:
        print(
            "  wcwidth:      BRAK (zainstaluj: pip install wcwidth)",
            file=out,
        )
        print(f"  heurystyka:   {total} pomiarów", file=out)
    else:
        print(f"  wcwidth:      {total - bez_wc} pomiarów", file=out)
        print(f"  heurystyka:   {total} pomiarów", file=out)
        print(f"  zgodne:       {zgodne}", file=out)
        print(
            f"  ROZJAZD:      {rozjazd_total}   "
            f"— znaki, które „kurczą się” przez VS16",
            file=out,
        )
        print(
            f"  MAŁA (text):  {mala_total}   "
            f"— text presentation, wizualnie mniejsze od emoji",
            file=out,
        )
        if fragile_total:
            print(
                f"  FRAGILE:      {fragile_total}   "
                f"— astral Emoji_Presentation=No, zależne od fontu",
                file=out,
            )
            if fragile_no_total or fragile_with_total:
                print(
                    f"    bez VS16:   {fragile_no_total}   "
                    f"— będzie mały/tekstowy",
                    file=out,
                )
                print(
                    f"    z VS16:     {fragile_with_total}   "
                    f"— font może ciąć",
                    file=out,
                )
        if font_risky_total:
            print(
                f"  FONT_RISK:    {font_risky_total}   "
                f"— BMP emoji, font może renderować mało",
                file=out,
            )
    print(file=out)

    # ── sekcja 3: proponowane zmiany (v3.2, bez limitu w v3.3,
    #     filtr rodzeństwa w v3.4) ──────────────────────────────
    proposed = [
        r for r in results
        if _verdict_of(r) in ("ROZJAZD", "MAŁA", "FRAGILE", "FONT_RISK")
    ]
    if proposed:
        print("── PROPONOWANE ZMIANY ──", file=out)
        for r in proposed:
            verdict = _verdict_of(r)
            print(
                f"  {r['file']}:{r['line']}:{r['col']}  "
                f"{r['ch']!r}  [{verdict}]",
                file=out,
            )
            props = _proposals_for(
                r["ch"], r["kind"], replacements,
                target=None, bad_chars=bad_chars,
            )
            for i, (val, label) in enumerate(props, 1):
                print(f"     {i}. {val:<10} ({label})", file=out)
            print(file=out)


__all__ = [
    "suggest_for",
    "print_report",
    "print_summary",
]
