#!/usr/bin/env python3

# tools/emoji_wizard.py
# -*- coding: utf-8 -*-

"""
emoji_wizard.py — interaktywne zarządzanie pluginami emoji.

Menu z listą pluginów (detekcja + zamienniki), wizard dodawania
nowych emoji z auto-klasyfikacją, edycja przez $EDITOR, usuwanie
z backupem .bak, podgląd zawartości (tabela z ikonami lub raw),
dodawanie ikon do istniejących zamienników, walidacja.

Użycie:

    python tools/emoji_wizard.py [opcje]

Opcje:

    --plugins-dir ROOT      katalog nadrzędny (oczekuje ROOT/wykrywanie,
                            ROOT/zamienniki)
    --detection-dir DIR     nadpisuje katalog detekcji
    --replacements-dir DIR  nadpisuje katalog zamienników
    --dry-run               pokazuje co by zrobił, nie zapisuje
    --no-color              bez kolorów ANSI
    --diagnose              tryb diagnostyczny terminala (readline, tty)
    --version               wersja narzędzia
    -h, --help              pomoc

Klawisze w menu:

    a — dodaj emoji (wizard z auto-klasyfikacją)
    e — edytuj plugin w $EDITOR (fallback: nano, vi)
    d — usuń plugin (domyślnie z backupem .bak)
    s — pokaż zawartość (tabela z ikonami lub raw)
    m — dodaj ikony do istniejącego zamiennika
    v — waliduj wszystkie pluginy
    q — wyjdź

Klawisze w promptach T/A/N:

    T — Tak      (akceptuję sugestię)
    A — Alternatywa (chcę inaczej / wybieram ręcznie)
    N — Nie      (pomiń / anuluj)

Puste wejście = T (sugestia) w T/A/N, puste = anuluj w listach.

Historia zmian:

  **v3.3**

  * `wizard_modify_replacement` — **radykalnie uproszczone**:
    wklej ikonę → wizard znajduje wpis → sloty → zapis.
    Zero pytania o plugin (chyba że w wielu), zero trybu
    append/replace, zero T/A/N. Zawsze append do `alt`.
    Do zmiany `rec` służy `[e]` (edytor).
  * `_prompt_alternatives_slots` — skrócony nagłówek
    (bez powtarzania „Obecne alt: …”).

  **v3.2**

  * `wizard_modify_replacement` — pierwsza wersja (plugin →
    wpis → tryb → sloty), zastąpiona w v3.3.
  * `_prompt_alternatives_slots` — dodawanie slot po slocie
    z podglądem `realnych: X/5`.

  **v3.1**

  * `wizard_show` — tryb `T` (tabela) pokazuje **ikony** obok kodów.
  * `_truncate` — helper z wielokropkiem.

  **v3.0**

  * `import readline` — bez tego backspace/strzałki nie działają.
  * `_safe_prompt()` — ANSI owinięty w `\001`...`\002`.
  * `--diagnose` — diagnostyka terminala.
  * Historia poleceń w `~/.emoji_wizard_history`.
"""

from __future__ import annotations

import argparse
import json
import os
import re as _re
import subprocess
import sys
import unicodedata
from pathlib import Path

# ── readline (krytyczne dla edycji linii) ───────────────────────
# Bez tego importu backspace, strzałki, home/end i historia nie
# działają w `input()`. Python ma readline wbudowany w standardową
# dystrybucję, ale w niektórych buildach (pyenv, embedded) trzeba
# doinstalować `gnureadline`.
try:
    import readline  # type: ignore[import-not-found]
    _READLINE_BACKEND = "readline"
    _HAS_READLINE = True
except ImportError:
    try:
        import gnureadline as readline  # type: ignore[import-not-found]
        _READLINE_BACKEND = "gnureadline"
        _HAS_READLINE = True
    except ImportError:
        readline = None  # type: ignore[assignment]
        _READLINE_BACKEND = None
        _HAS_READLINE = False


# ── bootstrap sys.path ──────────────────────────────────────────
# Wizard leży w `tools/`, pakiet `emoji/` w katalogu wyżej.
# Wstawiamy katalog projektu na początek sys.path, żeby lokalny
# `emoji/` wygrał z ewentualnym `pip install emoji`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from emoji import __version__  # noqa: E402
from emoji.generator import (  # noqa: E402
    add_emoji_to_plugin,
    add_replacement_to_plugin,
    find_emoji_entries,
    find_plugins_with_set,
    find_replacement_entries,
    guess_category,
    inspect_plugin,
    list_plugins,
    remove_plugin_file,
    update_replacement_in_plugin,
    validate_plugins,
)
from emoji.loader import (  # noqa: E402
    DEFAULT_DETECTION_DIR,
    DEFAULT_REPLACEMENTS_DIR,
    load_plugins,
)

# ── kolory ANSI ─────────────────────────────────────────────────
_COLOR_ENABLED = True


def _c(text: str, code: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:  return _c(t, "1")
def ok(t: str) -> str:    return _c(t, "1;32")
def warn(t: str) -> str:  return _c(t, "1;33")
def err(t: str) -> str:   return _c(t, "1;31")
def info(t: str) -> str:  return _c(t, "1;36")
def dim(t: str) -> str:   return _c(t, "2")


# ── safe prompt (ANSI wrapper dla readline) ─────────────────────

_ANSI_RE = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _safe_prompt(text: str) -> str:
    """
    Oznacza sekwencje ANSI jako niewidoczne dla readline.

    readline oblicza pozycję kursora na podstawie długości promptu.
    Jeśli prompt zawiera `\\033[1m` (bold) itp., readline liczy te
    7 bajtów jako widoczne znaki → kursor się rozjeżdża, backspace
    i strzałki zachowują się dziwnie.

    Standardowe rozwiązanie: owinąć każdą sekwencję ANSI w `\\001`
    (start) i `\\002` (end). readline wtedy wie, że to nie zajmuje
    miejsca na ekranie.

    Gdy readline niedostępny — zwraca prompt bez zmian.
    """
    if not _HAS_READLINE:
        return text
    return _ANSI_RE.sub(lambda m: f"\001{m.group(0)}\002", text)


# ── input helpers ───────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    """Pyta o tekst. Puste wejście → `default`."""
    suffix = f" [{default}]" if default else ""
    raw = input(_safe_prompt(f"   {prompt}{suffix}: ")).strip()
    return raw if raw else default


def _ask_tan(
    suggestion: str,
    alternative: str | None = None,
    skip: str = "pomiń",
) -> str:
    """
    Pyta o T/A/N. Zwraca "T" | "A" | "N".

    Puste wejście = "T". Jeśli `alternative is None`, opcja [A] nie
    jest pokazywana.
    """
    print(f"   [{bold('T')}] {suggestion}")
    if alternative is not None:
        print(f"   [{bold('A')}] {alternative}")
    print(f"   [{bold('N')}] {skip}")
    while True:
        raw = input(_safe_prompt("   > ")).strip().upper()
        if raw == "":
            return "T"
        if raw == "T":
            return "T"
        if raw == "N":
            return "N"
        if raw == "A" and alternative is not None:
            return "A"
        print(f"   {dim('?')} wybierz T, A lub N")


def _pick_from_list(
    items: list[str],
    prompt: str = "Wybierz numer",
    allow_cancel: bool = True,
) -> int | None:
    """
    Pokazuje numerowaną listę, pyta o numer.

    Zwraca indeks (0-based) lub None przy anulowaniu / pustym wejściu.
    """
    if not items:
        return None
    print()
    for i, item in enumerate(items, 1):
        print(f"   [{i:2}] {item}")
    if allow_cancel:
        print(f"   [{dim(' 0')}] anuluj")
    raw = input(_safe_prompt(f"   {prompt}: ")).strip()
    if not raw or raw == "0":
        return None
    try:
        idx = int(raw) - 1
    except ValueError:
        return None
    if 0 <= idx < len(items):
        return idx
    return None


def _pause() -> None:
    """Czeka na Enter po zakończonej akcji."""
    try:
        input(_safe_prompt(f"\n{dim('Naciśnij Enter, aby wrócić do menu...')}"))
    except (EOFError, KeyboardInterrupt):
        pass


# ── readline: historia ──────────────────────────────────────────

def _setup_readline_history() -> None:
    """
    Ładuje i zapisuje historię poleceń wizarda.

    Historia dotyczy tylko menu — `input()` w T/A/N i wklejanie
    emoji też są zapisywane (readline nie odróżnia). To akceptowalne
    — użytkownik może wyczyścić historię Ctrl+L lub usuwając plik.
    """
    if not _HAS_READLINE:
        return

    import atexit

    hist_file = Path.home() / ".emoji_wizard_history"

    try:
        readline.read_history_file(hist_file)
    except (FileNotFoundError, OSError, PermissionError):
        pass

    try:
        readline.set_history_length(1000)
    except Exception:  # noqa: BLE001
        pass

    try:
        atexit.register(_write_history, hist_file)
    except Exception:  # noqa: BLE001
        pass


def _write_history(hist_file: Path) -> None:
    """Zapisuje historię na wyjściu (wołane przez atexit)."""
    if not _HAS_READLINE:
        return
    try:
        readline.write_history_file(hist_file)
    except (OSError, PermissionError):
        pass


# ── diagnostyka ────────────────────────────────────────────────

def _diagnose() -> None:
    """
    Tryb diagnostyczny: sprawdza tty, TERM, readline, backend.
    Pozwala przetestować edycję linii (strzałki, backspace, home/end).
    """
    print()
    print(bold("── DIAGNOSTYKA TERMINALA ──"))
    print()

    print(f"  Python:               {sys.version.split()[0]}")
    print(f"  platforma:            {sys.platform}")
    print(f"  sys.stdin.isatty():   {sys.stdin.isatty()}")
    print(f"  sys.stdout.isatty():  {sys.stdout.isatty()}")
    print(f"  TERM:                 {os.environ.get('TERM', '(brak)')}")
    print(f"  EDITOR:               {os.environ.get('EDITOR', '(brak)')}")
    print(f"  VISUAL:               {os.environ.get('VISUAL', '(brak)')}")
    print()

    if _HAS_READLINE:
        print(f"  readline:             {ok(_READLINE_BACKEND)}")
        try:
            doc = readline.__doc__ or "(brak)"
            print(f"  readline.__doc__:     {doc.splitlines()[0][:60]}")
        except Exception:  # noqa: BLE001
            pass
    else:
        print(f"  readline:             {err('BRAK')}")
        print(f"  {dim('→ zainstaluj:')} pip install gnureadline")
        print(f"  {dim('→ bez readline:')} strzałki/backspace NIE będą działać")

    print()
    print(bold("Test edycji linii:"))
    print(dim("  Wpisz coś. Spróbuj:"))
    print(dim("    ←/→       — przesuwanie kursora"))
    print(dim("    Home/End  — skok na początek/koniec"))
    print(dim("    Backspace — usuwanie wstecz"))
    print(dim("    Delete    — usuwanie w przód"))
    print(dim("    ↑/↓       — historia (jeśli są wpisy)"))
    print(dim("  Enter kończy test."))
    print()

    try:
        test = input(_safe_prompt("  > "))
        print()
        print(f"  Wpisałeś: {test!r}  (długość: {len(test)})")
    except (EOFError, KeyboardInterrupt):
        print()
        print(dim("  Przerwano."))

    print()
    print(bold("Jeśli edycja nie działa:"))
    print(dim("  1. Sprawdź czy 'readline' jest OK powyżej"))
    print(dim("  2. Sprawdź stty:  stty -a | grep -o 'erase = .'"))
    print(dim("  3. Jeśli erase jest złe:  stty erase ^?"))
    print(dim("  4. W tmux/screen:  Ctrl+B :set -g xterm-keys on"))
    print()


# ── rozpoznanie katalogów ───────────────────────────────────────

def _resolve_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    """
    Zwraca (detection_dir, replacements_dir) na podstawie args.

    Priorytet:
      1. `--detection-dir` / `--replacements-dir` (najwyższy),
      2. `--plugins-dir` (ROOT/wykrywanie, ROOT/zamienniki),
      3. domyślne (`emoji/wykrywanie/`, `emoji/zamienniki/`).
    """
    detection = None
    replacements = None

    if args.plugins_dir:
        base = Path(args.plugins_dir).expanduser().resolve()
        detection = base / "wykrywanie"
        replacements = base / "zamienniki"

    if args.detection_dir:
        detection = Path(args.detection_dir).expanduser().resolve()
    if args.replacements_dir:
        replacements = Path(args.replacements_dir).expanduser().resolve()

    return (
        detection or DEFAULT_DETECTION_DIR,
        replacements or DEFAULT_REPLACEMENTS_DIR,
    )


# ── menu główne ─────────────────────────────────────────────────

def _print_menu(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Wypisuje listę pluginów + komendy.

    Każdy plugin pokazuje krótkie podsumowanie zawartości:
      * detekcja — liczbę codepoints/ranges, rozmiary zbiorów,
      * zamienniki — liczbę replacements,
      * błąd — komunikat `BŁĄD: ...` (np. uszkodzony JSON).
    """
    det = list_plugins(det_dir, "detection")
    rep = list_plugins(rep_dir, "replacements")

    print()
    print(bold("═" * 66))
    print(bold("  ZARZĄDZANIE PLUGINAMI EMOJI"))
    print(bold("═" * 66))
    print(f"  detekcja:     {det_dir}")
    print(f"  zamienniki:   {rep_dir}")
    if dry_run:
        print(f"  tryb:         {warn('DRY-RUN (nic nie zapisze)')}")
    print()

    def _fmt(p: dict) -> str:
        if p.get("error"):
            return f"{p['file']:<32} {err('BŁĄD: ' + p['error'][:40])}"
        try:
            ins = inspect_plugin(p["path"])
            if ins["kind"] == "detection":
                bits = []
                if ins.get("codepoints_count"):
                    bits.append(f"{ins['codepoints_count']} cp")
                if ins.get("ranges_count"):
                    bits.append(f"{ins['ranges_count']} ranges")
                for sname, size in (ins.get("sets") or {}).items():
                    bits.append(f"{sname}={size}")
                return f"{p['file']:<32} {dim(', '.join(bits) or '(puste)')}"
            else:
                n = ins.get("replacements_count", 0)
                return f"{p['file']:<32} {dim(f'{n} replacements')}"
        except Exception:  # noqa: BLE001
            return f"{p['file']:<32} {dim('?')}"

    if det:
        print(bold(f"DETEKCJA ({len(det)}):"))
        for p in det:
            print(f"  {_fmt(p)}")
    else:
        print(dim("DETEKCJA: (brak pluginów)"))
    print()

    if rep:
        print(bold(f"ZAMIENNIKI ({len(rep)}):"))
        for p in rep:
            print(f"  {_fmt(p)}")
    else:
        print(dim("ZAMIENNIKI: (brak pluginów)"))
    print()

    print(bold("KOMENDY:"))
    print(f"  [{bold('a')}] dodaj emoji (wizard)")
    print(f"  [{bold('e')}] edytuj plugin w $EDITOR")
    print(f"  [{bold('d')}] usuń plugin")
    print(f"  [{bold('s')}] pokaż zawartość")
    print(f"  [{bold('m')}] dodaj ikony do zamiennika")
    print(f"  [{bold('v')}] waliduj wszystko")
    print(f"  [{bold('q')}] wyjdź")


def _all_plugins(det_dir: Path, rep_dir: Path) -> list[tuple[dict, str]]:
    """Zwraca listę (plugin_dict, kind) — wszystkie pluginy."""
    items: list[tuple[dict, str]] = []
    for p in list_plugins(det_dir, "detection"):
        items.append((p, "detection"))
    for p in list_plugins(rep_dir, "replacements"):
        items.append((p, "replacements"))
    return items


def _pick_plugin(det_dir: Path, rep_dir: Path) -> Path | None:
    """
    Pozwala wybrać plugin z listy. Zwraca ścieżkę lub None.

    Lista zawiera oba rodzaje: [D] dla detekcji, [Z] dla zamienników.
    """
    items = _all_plugins(det_dir, rep_dir)
    if not items:
        print(warn("   Brak pluginów."))
        return None

    labels = []
    for p, kind in items:
        prefix = "D" if kind == "detection" else "Z"
        mark = " " if not p.get("error") else err("!")
        labels.append(f"[{prefix}] {mark} {p['file']}")

    idx = _pick_from_list(labels, "Numer pluginu")
    if idx is None:
        return None
    return Path(items[idx][0]["path"])


# ── podgląd z ikonami ──────────────────────────────────────────

def _display_char(ch: str, cp: int) -> str:
    """
    Zwraca znak do wyświetlenia — placeholder dla niewidocznych.

    Modyfikatory (VS16/VS15/ZWJ/KEYCAP) są niewidoczne, więc
    pokazujemy `·`. Znaki kontrolne (< 0x20) też. Spacja jako `␣`.
    """
    if cp in (0xFE0F, 0xFE0E, 0x200D, 0x20E3):
        return "·"
    if cp < 0x20:
        return "·"
    if ch == " ":
        return "␣"
    return ch


def _uname(cp: int) -> str:
    """Nazwa Unicode codepointu (fallback: '?')."""
    try:
        return unicodedata.name(chr(cp), "?")
    except (ValueError, TypeError):
        return "?"


def _truncate(s: str, width: int = 62) -> str:
    """
    Obcina do `width` znaków, dodaje '…' jeśli obcięto.

    Uwaga: tnie po codepointach, nie po grafemach — jeśli granica
    wypadnie w środku klastra (np. `1️⃣` = `1` + VS16 + KEYCAP),
    dostaniesz sam `1` (bez ramki). To akceptowalne — `1` wygląda
    jak zwykła cyfra, nie jak zepsuty glif.
    """
    s = s or ""
    return s if len(s) <= width + 1 else s[:width].rstrip() + "…"


def _print_cps_row(cps: list[int], indent: str = "       ", per_row: int = 8) -> None:
    """Wypisuje listę codepointów jako emoji + kody, zawijając co N."""
    for i in range(0, len(cps), per_row):
        row = cps[i:i + per_row]
        pieces = [f"{chr(cp)} U+{cp:04X}" for cp in row]
        print(f"{indent}{'  '.join(pieces)}")


def _show_detection_icons(data_raw: dict) -> None:
    """
    Tabela detekcji z ikonami: codepoints, ranges, sets.

    Format:
      codepoints — każdy wiersz: `{ikona} {U+XXXX} [{kind}] {label}`
      ranges     — każdy wiersz: `{ikona_lo}…{ikona_hi} {U+XXXX–U+YYYY} {label}`
      sets       — nazwa zbioru + zawijana lista `{ikona} U+XXXX` (8/stronę)
    """
    cps = data_raw.get("codepoints", [])
    print(f"   codepoints:  {len(cps)}")
    if cps:
        print()
        for entry in cps:
            cp_str = entry.get("cp", "?")
            cp_kind = entry.get("kind", "?")
            label = entry.get("label", "")
            try:
                cp_int = int(cp_str.replace("U+", "").replace("u+", ""), 16)
            except (ValueError, AttributeError):
                cp_int = None
            if cp_int is not None:
                display = _display_char(chr(cp_int), cp_int)
                desc_src = label if label else _uname(cp_int)
                desc = _truncate(desc_src, 62)
                print(f"     {display}  {cp_str:>8}  [{cp_kind:<6}]  {desc}")
            else:
                print(f"     ?  {cp_str:>8}  [{cp_kind:<6}]  {_truncate(label, 62)}")
    print()

    ranges = data_raw.get("ranges", [])
    print(f"   ranges:      {len(ranges)}")
    if ranges:
        print()
        for entry in ranges:
            lo_str = entry.get("start", "?")
            hi_str = entry.get("end", "?")
            label = entry.get("label", "")
            try:
                lo = int(lo_str.replace("U+", ""), 16)
                hi = int(hi_str.replace("U+", ""), 16)
                lo_ch = _display_char(chr(lo), lo)
                hi_ch = _display_char(chr(hi), hi)
                print(f"     {lo_ch}…{hi_ch}  {lo_str}–{hi_str}  {_truncate(label, 55)}")
            except ValueError:
                print(f"     ?…?  {lo_str}–{hi_str}  {_truncate(label, 55)}")
    print()

    sets = data_raw.get("sets", {})
    print(f"   sets:        {len(sets)}")
    if sets:
        print()
        for sname, values in sets.items():
            cps_int = []
            for v in values:
                try:
                    cps_int.append(int(v.replace("U+", ""), 16))
                except (ValueError, AttributeError):
                    pass
            cps_int.sort()
            print(f"     {sname} ({len(cps_int)}):")
            _print_cps_row(cps_int, indent="       ", per_row=8)


def _show_replacements_icons(data_raw: dict) -> None:
    """
    Tabela zamienników z ikonami: klucz → rec.

    Format każdego wiersza:
        {klucz}  →  {rec}   alt: {alt1, alt2, ...}
    """
    reps = data_raw.get("replacements", {})
    print(f"   replacements: {len(reps)}")
    print()
    for key, entry in reps.items():
        rec = entry.get("rec", "") if isinstance(entry, dict) else "?"
        alt = entry.get("alt", []) if isinstance(entry, dict) else []
        alt_str = ""
        if alt:
            alt_str = f"   {dim('alt:')} {', '.join(str(a) for a in alt)}"
        print(f"     {key}  →  {rec}{alt_str}")


# ── wizard: dodaj emoji ─────────────────────────────────────────

def _pick_or_create_plugin(
    existing_files: list[str],
    new_prefix: str = "50_",
) -> tuple[Path | None, str | None]:
    """
    Pyta: istniejący plugin (z listy) albo nowy.

    Zwraca (target_path, new_name):
      * (path, None)    — wybrano istniejący plugin,
      * (path, "name")  — utworzyć nowy plugin,
      * (None, None)    — anulowano.
    """
    labels = [f"{f}" for f in existing_files]
    labels.append(f"{info('nowy plugin')}")

    idx = _pick_from_list(labels, "Wybierz plugin")
    if idx is None:
        return None, None

    if idx < len(existing_files):
        return Path(existing_files[idx]), None

    name = _ask("Nazwa nowego pluginu (bez prefixu, bez .json)")
    if not name:
        return None, None
    return Path(f"{new_prefix}{name}.json"), name


def wizard_add(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Wizard dodawania emoji z auto-klasyfikacją.

    Obsługuje kategorie z `guess_category`:
      * TEXT_DEFAULT_BMP / EMOJI_DEFAULT_BMP / ASTRAL_TEXT_DEFAULT
        → certain, automatyczna sugestia zbioru,
      * UNKNOWN_EMOJI / NOT_EMOJI → guess, pyta o zbiór.

    Dla ASTRAL_TEXT_DEFAULT pokazuje dodatkowe ostrzeżenie FRAGILE.

    Trzy kroki:
      1. wklejenie znaku (auto-klasyfikacja),
      2. detekcja (wybór zbioru + plugin),
      3. zamiennik (rec + alt + why + plugin).

    Jeśli zamiennik już istnieje, sugeruje użycie `m` (dodanie ikon)
    zamiast tworzenia duplikatu w innym pluginie.
    """
    print()
    print(bold("═══ DODAWANIE EMOJI ═══"))

    # ── KROK 1: znak ──────────────────────────────────────────────
    print()
    print(bold("Krok 1/3: Emoji bazowe"))
    ch_input = input(_safe_prompt("   Wklej znak (np. ⚠ lub ⚙): ")).strip()
    if not ch_input:
        print(err("   Pusto — anulowano."))
        return

    det_data = load_plugins(det_dir)
    guess = guess_category(ch_input, det_data)

    if not guess["ok"]:
        print(err(f"   Nie można rozpoznać: {guess['reason']}"))
        return

    # ── KROK 2: rozpoznanie i wybór zbioru ────────────────────────
    print()
    print(bold("Krok 2/3: Detekcja"))
    print()
    print(f"   {ok('[OK]')} {guess['cp']}  {guess['ch']!r}  {guess['name']}")
    print(f"   kategoria:   {guess['kind']}  ({dim(guess['confidence'])})")
    print(f"   wcwidth:     {guess['wcwidth']}")
    print(f"   powód:       {guess['reason']}")

    if guess["kind"] == "ASTRAL_TEXT_DEFAULT":
        print()
        print(warn("   ⚠ FRAGILE — astral Emoji_Presentation=No:"))
        print(warn("     bez VS16 renderuje się mały/tekstowy,"))
        print(warn("     z VS16 renderowanie zależy od fontu (może być ucięty)."))
        print(warn("     Sprawdź zamienniki — bezpieczniejszy wybór to emoji default."))

    if guess["was_modified"]:
        print(warn(
            f"   uwaga: wklejono z modyfikatorem — użyję bazowego {guess['ch']!r}"
        ))

    existing = find_emoji_entries(guess["cp_int"], det_dir)
    if existing:
        print()
        print(f"   {warn('[!]')} Znak już istnieje w:")
        for e in existing:
            label = e["kind"]
            if e["set_name"]:
                label += f": {e['set_name']}"
            print(f"       {dim('-')} {e['file']}  ({label})")

    suggested_set = guess["suggested_set"]

    if suggested_set is None:
        print()
        ans = _ask_tan(
            "dodaj do TEXT_DEFAULT_BMP",
            "wybierz inny zbiór",
            skip="pomiń detekcję",
        )
        if ans == "T":
            set_name = "TEXT_DEFAULT_BMP"
        elif ans == "A":
            available = sorted(det_data.get("sets", {}).keys())
            available.append(info("nowy zbiór"))
            idx = _pick_from_list(available, "Wybierz zbiór")
            if idx is None:
                print(dim("   Anulowano."))
                return
            if idx == len(available) - 1:
                set_name = _ask("Nazwa nowego zbioru")
            else:
                set_name = available[idx]
        else:
            set_name = None
    else:
        print()
        ans = _ask_tan(
            f"dodaj do {suggested_set}",
            "wybierz inny zbiór",
            skip="pomiń detekcję",
        )
        if ans == "T":
            set_name = suggested_set
        elif ans == "A":
            available = sorted(det_data.get("sets", {}).keys())
            available.append(info("nowy zbiór"))
            idx = _pick_from_list(available, "Wybierz zbiór")
            if idx is None:
                print(dim("   Anulowano."))
                return
            if idx == len(available) - 1:
                set_name = _ask("Nazwa nowego zbioru")
            else:
                set_name = available[idx]
        else:
            set_name = None

    # ── zapis do detekcji ────────────────────────────────────────
    if set_name:
        already = [
            e for e in existing
            if e["kind"] == "set" and e["set_name"] == set_name
        ]
        if already:
            print()
            print(dim(
                f"   Już jest w {set_name} w {already[0]['file']} — pomijam dodawanie."
            ))
        else:
            files_with_set = find_plugins_with_set(set_name, det_dir)
            json_files = [f for f in files_with_set if f.endswith(".json")]
            py_files = [f for f in files_with_set if f.endswith(".py")]

            print()
            if py_files:
                print(dim(
                    f"   (pliki .py wymagają ręcznej edycji: {', '.join(py_files)})"
                ))

            target_rel, new_name = _pick_or_create_plugin(json_files)
            if target_rel is None:
                print(dim("   Anulowano."))
                return

            target = target_rel if target_rel.is_absolute() else det_dir / target_rel

            if dry_run:
                print()
                print(info(
                    f"   [dry-run] add_emoji_to_plugin("
                    f"{target.name}, {guess['cp']}, {set_name!r})"
                ))
            else:
                res = add_emoji_to_plugin(
                    target,
                    guess["cp_int"],
                    set_name,
                    create_name=new_name,
                    create_description=(
                        f"Plugin utworzony przez wizard: {set_name}"
                    ),
                )
                print()
                if not res["ok"]:
                    print(err(f"   Błąd: {res['error']}"))
                elif res["changed"]:
                    print(ok(
                        f"   Dodano {guess['cp']} do {set_name} "
                        f"w {Path(res['path']).name}"
                    ))
                else:
                    print(warn(f"   Nic nie zmieniono: {res['error']}"))

    # ── KROK 3: zamiennik ────────────────────────────────────────
    print()
    print(bold("Krok 3/3: Zamiennik"))

    existing_reps = find_replacement_entries(guess["ch"], rep_dir)

    if existing_reps:
        print()
        print(f"   {info('[i]')} Zamiennik już istnieje:")
        for r in existing_reps:
            print(f"       {guess['ch']!r} → {r['rec']!r}  ({dim(r['file'])})")
        print()
        print(dim("   Aby dodać ikony do istniejącego wpisu, użyj [m] z menu."))
        print()
        ans = _ask_tan(
            "zostaw istniejący (nic nie robię)",
            alternative=None,
            skip="pomiń zamiennik",
        )
        if ans in ("T", "N"):
            print(dim("   Pominięto."))
            _finish(det_dir, rep_dir, dry_run)
            return
    else:
        print()
        ans = _ask_tan(
            "dodaj zamiennik",
            alternative=None,
            skip="pomiń zamiennik",
        )
        if ans != "T":
            print(dim("   Pominięto."))
            _finish(det_dir, rep_dir, dry_run)
            return

    print()
    rec = _ask("Zalecany zamiennik (np. 🚨)")
    if not rec:
        print(err("   Brak rec — anulowano."))
        _finish(det_dir, rep_dir, dry_run)
        return

    alt_raw = _ask("Alternatywy po przecinku (puste = brak)")
    alt = [a.strip() for a in alt_raw.split(",") if a.strip()] if alt_raw else []

    why = _ask("Uzasadnienie (krótko)")
    if not why:
        why = f"dodane przez wizard dla {guess['cp']}"

    rep_plugins = [
        p["file"] for p in list_plugins(rep_dir, "replacements")
        if not p.get("error")
    ]
    json_reps = [f for f in rep_plugins if f.endswith(".json")]
    py_reps = [f for f in rep_plugins if f.endswith(".py")]

    if py_reps:
        print(dim(
            f"   (pliki .py wymagają ręcznej edycji: {', '.join(py_reps)})"
        ))

    target_rel, new_name = _pick_or_create_plugin(json_reps)
    if target_rel is None:
        print(dim("   Anulowano."))
        _finish(det_dir, rep_dir, dry_run)
        return

    target = target_rel if target_rel.is_absolute() else rep_dir / target_rel

    if dry_run:
        print()
        print(info(
            f"   [dry-run] add_replacement_to_plugin("
            f"{target.name}, {guess['ch']!r}, {rec!r})"
        ))
    else:
        res = add_replacement_to_plugin(
            target,
            guess["ch"],
            rec,
            alt,
            why,
            create_name=new_name,
            create_description="Zamienniki utworzone przez wizard",
        )
        print()
        if not res["ok"]:
            print(err(f"   Błąd: {res['error']}"))
        else:
            print(ok(
                f"   Dodano {guess['ch']!r} → {rec!r} w {Path(res['path']).name}"
            ))

    _finish(det_dir, rep_dir, dry_run)


def _finish(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """Podsumowanie po wizardzie: walidacja lub info o dry-run."""
    print()
    if dry_run:
        print(info("Dry-run: nie zapisano nic."))
        _pause()
        return

    print(bold("Walidacja:"))
    rep = validate_plugins(det_dir, rep_dir)

    if rep["ok"] and not rep["cross"]["warnings"]:
        print(ok("   Wszystkie pluginy OK."))
    else:
        for e in rep["detection"]["errors"]:
            print(err(f"   detection/{e['file']}: {e['error']}"))
        for e in rep["replacements"]["errors"]:
            print(err(f"   zamienniki/{e['file']}: {e['error']}"))
        for w in rep["cross"]["warnings"]:
            print(warn(f"   {w}"))
    _pause()


# ── edycja ──────────────────────────────────────────────────────

def wizard_edit(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Otwiera plugin w $EDITOR (fallback: VISUAL, nano, notepad).

    Po zamknięciu edytora — walidacja przez `inspect_plugin`:
    czy plik dalej się parsuje. Nie modyfikuje pliku samodzielnie
    (zgodnie z zasadą „.py tylko przez $EDITOR”).
    """
    path = _pick_plugin(det_dir, rep_dir)
    if path is None:
        return

    if dry_run:
        print(info(f"   [dry-run] edytowałby: {path}"))
        _pause()
        return

    editor = (
        os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
        or ("notepad" if os.name == "nt" else "nano")
    )
    print()
    print(f"   Otwieram {editor} {path.name}...")
    try:
        subprocess.call([editor, str(path)])
    except FileNotFoundError:
        print(err(f"   Nie znaleziono edytora: {editor}"))
        _pause()
        return
    except Exception as e:  # noqa: BLE001
        print(err(f"   Błąd edytora: {e}"))
        _pause()
        return

    print()
    print(bold("Walidacja po edycji:"))
    info_res = inspect_plugin(path)
    if info_res.get("error"):
        print(err(f"   Błąd: {info_res['error']}"))
    else:
        print(ok(
            f"   {path.name} wczytuje się poprawnie ({info_res['kind']})."
        ))
    _pause()


# ── usuwanie ────────────────────────────────────────────────────

def wizard_delete(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Usuwa plugin.

    Domyślnie przenosi do `.bak` z timestampem (odwracalne).
    Opcja [A] — twarde `rm` (nieodwracalne).
    """
    path = _pick_plugin(det_dir, rep_dir)
    if path is None:
        return

    print()
    print(warn(f"   Zamierzasz usunąć: {path.name}"))
    ans = _ask_tan(
        "przenieś do .bak (bezpieczne)",
        "usuń trwale (nieodwracalne)",
        skip="anuluj",
    )
    if ans == "N":
        print(dim("   Anulowano."))
        return

    if dry_run:
        print(info(f"   [dry-run] usunąłbym: {path}"))
        _pause()
        return

    res = remove_plugin_file(path, backup=(ans == "T"))
    print()
    if not res["ok"]:
        print(err(f"   Błąd: {res['error']}"))
    elif ans == "T":
        print(ok(f"   Przeniesiono do: {res['backup_path']}"))
    else:
        print(ok(f"   Usunięto trwale: {path}"))
    _pause()


# ── podgląd ─────────────────────────────────────────────────────

def wizard_show(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Pokazuje zawartość pluginu.

    Tryb T (tabela z ikonami):
      * detekcja — codepoints jako `🔧 U+1F527`, ranges jako `☀…⿿`,
        sets jako zawijana lista `{ikona} U+XXXX`,
      * zamienniki — każdy wiersz `{klucz} → {rec}  alt: ...`.

    Tryb A (raw): surowa zawartość pliku.
    """
    path = _pick_plugin(det_dir, rep_dir)
    if path is None:
        return

    print()
    ans = _ask_tan(
        "tabela z ikonami",
        "raw (surowa zawartość)",
        skip="anuluj",
    )
    if ans == "N":
        return

    if ans == "A":
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            print(err(f"   Nie można odczytać: {e}"))
            _pause()
            return
        print()
        print(bold(f"── {path.name} (raw) ──"))
        print(content)
        _pause()
        return

    # tabela z ikonami
    try:
        raw_text = path.read_text(encoding="utf-8")
        data_raw = json.loads(raw_text)
    except (json.JSONDecodeError, OSError) as e:
        print(err(f"   Nie można wczytać: {e}"))
        _pause()
        return

    print()
    print(bold(f"── {path.name} (tabela z ikonami) ──"))
    print()

    if "replacements" in data_raw:
        _show_replacements_icons(data_raw)
    elif (
        "codepoints" in data_raw
        or "ranges" in data_raw
        or "sets" in data_raw
    ):
        _show_detection_icons(data_raw)
    else:
        print(dim("   (nie rozpoznano rodzaju pluginu)"))

    _pause()


# ── dodawanie ikon do zamiennika ────────────────────────────────

def _prompt_alternatives_slots(
    current: list[str],
    rec: str,
    target: int = 5,
) -> list[str]:
    """
    Prowadzi użytkownika przez dodawanie alternatyw slot po slocie.

    Parametry:
        current:  obecne `alt` (do dedupe i podglądu),
        rec:      obecny `rec` (nie można dodać go jako alt),
        target:   docelowa liczba realnych propozycji (domyślnie 5).

    Zwraca listę **nowych** alternatyw do dodania (bez obecnych).

    Zachowanie:
      * każdy slot to jedno `input()`,
      * Enter = koniec (nie dodaje pustej),
      * Ctrl+C/EOF = przerwanie, zwraca to, co już dodano,
      * duplikat (względem `current`, `to_add` lub `rec`) — pomijany
        z komunikatem, slot idzie dalej.
    """
    to_add: list[str] = []
    print()
    print(dim("   Enter = koniec, Ctrl+C = anuluj"))
    print()

    slot = 1
    while True:
        total_now = 1 + len(current) + len(to_add)
        added_hint = f"  (+{', '.join(to_add)})" if to_add else ""
        prompt = f"   Ikona {slot} (realnych: {total_now}/{target}){added_hint}: "

        try:
            raw = input(_safe_prompt(prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            break
        if raw == rec:
            print(warn(f"   {raw!r} to rec — pomijam"))
            slot += 1
            continue
        if raw in current or raw in to_add:
            print(warn(f"   {raw!r} już jest — pomijam"))
            slot += 1
            continue

        to_add.append(raw)
        slot += 1

    return to_add


def wizard_modify_replacement(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Dodaje ikony do istniejącego wpisu zamiennika.

    Flow (prosty):
      1. Wklej ikonę (np. 🛡).
      2. Wizard znajduje wpis we wszystkich pluginach zamienników.
         - 1 trafienie   → od razu przechodzi dalej,
         - >1 trafień    → pyta, w którym pluginie (rzadkie),
         - 0 trafień     → komunikat „użyj [a]”.
      3. Pokazuje obecny rec/alt i licznik realnych propozycji.
      4. Sloty: każdy `input()` = jedna nowa ikona, Enter = koniec.
      5. Zapisuje (append do alt), pokazuje wynik.

    Bez trybu replace — do zmiany `rec` służy `[e]` (edytor).
    Bez pytania „co zrobić?” — zawsze append, bo to 95% przypadków.
    Bez wyboru pluginu, jeśli ikona jest tylko w jednym.
    """
    print()
    print(bold("═══ DODAJ IKONY DO ZAMIENNIKA ═══"))
    print()

    ch_input = input(_safe_prompt("   Wklej ikonę (np. 🛡): ")).strip()
    if not ch_input:
        print(err("   Pusto — anulowano."))
        return

    entries = find_replacement_entries(ch_input, rep_dir)
    if not entries:
        print()
        print(warn(f"   {ch_input!r} nie ma zamiennika w żadnym pluginie."))
        print(dim("   Użyj [a] aby dodać nowy wpis."))
        _pause()
        return

    if len(entries) == 1:
        target_entry = entries[0]
    else:
        labels = [
            f"{e['file']}  →  {e['rec']}   ({1 + len(e['alt'])} realnych)"
            for e in entries
        ]
        idx = _pick_from_list(labels, "Znaleziono w wielu — wybierz")
        if idx is None:
            return
        target_entry = entries[idx]

    path = rep_dir / target_entry["file"]
    cur_rec = target_entry["rec"]
    cur_alt = list(target_entry["alt"])
    ch = ch_input

    print()
    print(f"   {dim(target_entry['file'])}:")
    print(f"     rec:  {cur_rec}")
    print(f"     alt:  {', '.join(cur_alt) or '(brak)'}")
    print(f"     realnych: {1 + len(cur_alt)}/5")

    new_alts = _prompt_alternatives_slots(cur_alt, cur_rec, target=5)
    if not new_alts:
        print()
        print(dim("   Nic nie dodano."))
        _pause()
        return

    if dry_run:
        print()
        print(info(
            f"   [dry-run] append do {ch!r} w {target_entry['file']}: "
            f"{', '.join(new_alts)}"
        ))
        _pause()
        return

    res = update_replacement_in_plugin(
        path, ch, alt=new_alts, append_alt=True,
    )

    print()
    if not res["ok"]:
        print(err(f"   Błąd: {res['error']}"))
    elif not res["changed"]:
        print(warn("   Nic nie zmieniono."))
    else:
        new = res["new"]
        total = 1 + len(new["alt"])
        print(ok(f"   Dodano do {ch!r} w {target_entry['file']}:"))
        print(f"     alt:  {', '.join(new['alt'])}")
        print()
        if total >= 5:
            print(ok(f"   realnych propozycji: {total}/5 ✓"))
        else:
            print(warn(f"   realnych propozycji: {total}/5 (brakuje {5 - total})"))

    _pause()


# ── walidacja ───────────────────────────────────────────────────

def wizard_validate(det_dir: Path, rep_dir: Path, dry_run: bool) -> None:
    """
    Waliduje wszystkie pluginy (składnia + duplikaty między pluginami).

    Sekcje:
      * Detekcja — katalog, wczytane, błędy,
      * Zamienniki — katalog, wczytane, błędy,
      * Ostrzeżenia (duplikaty) — osobno, żeby nie mylić z błędami,
      * WYNIK — OK / OK (ostrzeżenia) / BŁĘDY.
    """
    print()
    rep = validate_plugins(det_dir, rep_dir)

    print(bold("── WALIDACJA ──"))
    print()
    print(f"   Detekcja:     {rep['detection']['dir']}")
    print(f"     wczytane:   {len(rep['detection']['files'])}")
    print(f"     błędy:      {len(rep['detection']['errors'])}")
    for e in rep["detection"]["errors"]:
        print(err(f"       {e['file']}: {e['error']}"))

    print()
    print(f"   Zamienniki:   {rep['replacements']['dir']}")
    print(f"     wczytane:   {len(rep['replacements']['files'])}")
    print(f"     błędy:      {len(rep['replacements']['errors'])}")
    for e in rep["replacements"]["errors"]:
        print(err(f"       {e['file']}: {e['error']}"))

    print()
    warns = rep["cross"]["warnings"]
    print(f"   Ostrzeżenia:  {len(warns)}")
    for w in warns:
        print(warn(f"       {w}"))

    print()
    if rep["ok"] and not warns:
        print(ok("   WYNIK: OK"))
    elif rep["ok"]:
        print(warn("   WYNIK: OK (są ostrzeżenia, ale pluginy działają)"))
    else:
        print(err("   WYNIK: BŁĘDY"))

    _pause()


# ── main loop ───────────────────────────────────────────────────

def main_loop(det_dir: Path, rep_dir: Path, dry_run: bool) -> int:
    """
    Główna pętla menu.

    Każda komenda w `try/except KeyboardInterrupt` — Ctrl+C w środku
    wizarda przerywa tylko ten wizard, wraca do menu. Ctrl+C w menu
    kończy program. Ctrl+D (`EOFError`) też kończy.
    """
    while True:
        _print_menu(det_dir, rep_dir, dry_run)
        try:
            raw = input(_safe_prompt(f"\n   {bold('>')} ")).strip().lower()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print(f"\n{dim('Przerwano.')}")
            return 0

        if raw in ("q", "quit", "exit", ""):
            return 0
        elif raw == "a":
            try:
                wizard_add(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano wizard.')}")
        elif raw == "e":
            try:
                wizard_edit(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano.')}")
        elif raw == "d":
            try:
                wizard_delete(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano.')}")
        elif raw == "s":
            try:
                wizard_show(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano.')}")
        elif raw == "m":
            try:
                wizard_modify_replacement(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano.')}")
        elif raw == "v":
            try:
                wizard_validate(det_dir, rep_dir, dry_run)
            except KeyboardInterrupt:
                print(f"\n{dim('Przerwano.')}")
        else:
            print(err(f"   Nieznana komenda: {raw!r}"))
            print(dim("   Dostępne: a, e, d, s, m, v, q"))


# ── CLI ─────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Buduje parser argumentów CLI."""
    parser = argparse.ArgumentParser(
        prog="emoji_wizard.py",
        description="Interaktywne zarządzanie pluginami emoji.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Klawisze menu: a (dodaj), e (edytuj), d (usuń), "
            "s (pokaż), m (dodaj ikony do zamiennika), v (waliduj), q (wyjdź)\n"
            "Klawisze T/A/N: T (tak), A (alternatywa), N (nie)\n"
            "\n"
            "Diagnostyka terminala:\n"
            "  python tools/emoji_wizard.py --diagnose\n"
        ),
    )
    parser.add_argument(
        "--plugins-dir",
        default=None,
        metavar="ROOT",
        help="katalog nadrzędny pluginów",
    )
    parser.add_argument(
        "--detection-dir",
        default=None,
        metavar="DIR",
        help="nadpisuje katalog pluginów detekcji",
    )
    parser.add_argument(
        "--replacements-dir",
        default=None,
        metavar="DIR",
        help="nadpisuje katalog pluginów zamienników",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="pokazuje co by zrobił, ale nie zapisuje",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="wyłącza kolory ANSI",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="tryb diagnostyczny: sprawdza readline, tty, TERM",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"emoji_wizard.py {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Punkt wejścia CLI.

    Kolejność:
      1. parsowanie argumentów,
      2. wyłączenie kolorów (--no-color, NO_COLOR, brak tty),
      3. tryb --diagnose (jeśli podany) — kończy program,
      4. setup readline (historia),
      5. ostrzeżenie jeśli brak readline,
      6. walidacja katalogów,
      7. main_loop.
    """
    global _COLOR_ENABLED

    parser = _build_parser()
    args = parser.parse_args(argv)

    if (
        args.no_color
        or not sys.stdout.isatty()
        or os.environ.get("NO_COLOR") is not None
    ):
        _COLOR_ENABLED = False

    if args.diagnose:
        _diagnose()
        return 0

    _setup_readline_history()

    if not _HAS_READLINE:
        print(warn("Uwaga: brak modułu 'readline' — strzałki/backspace nie działają."))
        print(dim("       Spróbuj: pip install gnureadline"))
        print(dim("       Diagnostyka: python tools/emoji_wizard.py --diagnose"))
        print()

    det_dir, rep_dir = _resolve_dirs(args)

    if not det_dir.is_dir():
        print(err(f"Katalog detekcji nie istnieje: {det_dir}"))
        return 1
    if not rep_dir.is_dir():
        print(err(f"Katalog zamienników nie istnieje: {rep_dir}"))
        return 1

    try:
        return main_loop(det_dir, rep_dir, args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{dim('Przerwano.')}")
        return 0
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
