#!/usr/bin/env python3

# scan_emoji.py
# -*- coding: utf-8 -*-

#!/usr/bin/env python3
"""
scan_emoji.py — skaner emoji w plikach źródłowych.

Wykrywa emoji, mierzy ich szerokość DWOMA metodami (wcwidth + heurystyka
Unicode), porównuje i raportuje problemy. Sugeruje zamienniki z pluginów.

Użycie:

    python scan_emoji.py <plik|folder> [opcje]

Opcje:

    --vs16                  tylko VS16 (główny sprawca buga „połówki”)
    --no-suggestions        bez sekcji „zalecany/alternatywy”
    --quiet                 bez preambuły i raportu per-znalezisko
                            (zostaje podsumowanie + końcowa linia)
    --strict                kod wyjścia 2, jeśli są problemy
                            (ROZJAZD, MAŁA lub FRAGILE) — do CI

    --fragile-mode MODE     tryb obsługi FRAGILE (astral Emoji_Presentation=No):
                              simple   — jeden komunikat (domyślny),
                              split    — dwa komunikaty (bez/z VS16),
                              reporter — decyzja po stronie reportera

    --plugins-dir ROOT      katalog nadrzędny pluginów
                            (oczekuje ROOT/wykrywanie i ROOT/zamienniki)
    --detection-dir DIR     nadpisuje katalog pluginów detekcji
    --replacements-dir DIR  nadpisuje katalog pluginów zamienników

    --skip-dir NAME         dodatkowy katalog do pominięcia (można wielokrotnie)
    --skip-ext EXT          dodatkowe rozszerzenie do pominięcia (można wielokrotnie)
    --no-default-skips      nie używaj domyślnych list pomijania

    --version               wersja narzędzia
    -h, --help              pomoc

Przykłady:

    # pojedynczy plik
    python scan_emoji.py src/menu.py

    # cały folder rekursywnie
    python scan_emoji.py src/

    # tylko VS16 (najszybsze)
    python scan_emoji.py . --vs16

    # CI: cichy, strict, własne pluginy
    python scan_emoji.py src/ --quiet --strict \\
        --plugins-dir ./moje_emoji

    # FRAGILE z rozbiciem bez/z VS16
    python scan_emoji.py src/ --fragile-mode split

Kody wyjścia:

    0 — sukces (skan się odbył; nie zależy od liczby znalezisk)
    1 — błąd twardy (zła ścieżka, błąd pluginów, wyjątek)
    2 — --strict + znaleziono problemy (ROZJAZD, MAŁA lub FRAGILE)

Bez --strict skaner zawsze zwraca 0 po udanym skanie — bo jest
narzędziem raportującym, nie bramką. Bramką staje się z --strict.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── bootstrap: dodaj katalog skryptu do sys.path ────────────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from emoji import (  # noqa: E402
    HAS_WCWIDTH,
    __version__,
    load_plugins,
    load_replacements,
    print_report,
    print_summary,
    scan,
)
from emoji.detection import (  # noqa: E402
    DEFAULT_FRAGILE_MODE,
    FRAGILE_MODES,
)
from emoji.scanner import (  # noqa: E402
    DEFAULT_SKIP_DIRS,
    DEFAULT_SKIP_EXT,
)

# ── kody wyjścia ────────────────────────────────────────────────
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PROBLEMS = 2


# ── pomocnicze ──────────────────────────────────────────────────

def _resolve_plugin_dirs(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """Wyznacza katalogi pluginów na podstawie argumentów CLI."""
    detection: Path | None = None
    replacements: Path | None = None

    if args.plugins_dir:
        base = Path(args.plugins_dir).expanduser().resolve()
        detection = base / "wykrywanie"
        replacements = base / "zamienniki"

    if args.detection_dir:
        detection = Path(args.detection_dir).expanduser().resolve()
    if args.replacements_dir:
        replacements = Path(args.replacements_dir).expanduser().resolve()

    return detection, replacements


def _resolve_skips(
    args: argparse.Namespace,
) -> tuple[set[str] | None, set[str] | None]:
    """Wyznacza zbiory pomijanych katalogów i rozszerzeń."""
    user_dirs = set(args.skip_dir) if args.skip_dir else set()
    user_exts = set(args.skip_ext) if args.skip_ext else set()

    if args.no_default_skips:
        return user_dirs, user_exts

    if user_dirs or user_exts:
        return DEFAULT_SKIP_DIRS | user_dirs, DEFAULT_SKIP_EXT | user_exts

    return None, None


def _build_bad_chars(det_data: dict) -> set[str]:
    """
    Buduje zbiór znaków, które **nie powinny** być proponowane jako
    rodzeństwo w `_proposals_for`.

    Zawiera:
      * `TEXT_DEFAULT_BMP` — BMP text-default (MAŁA),
      * `ASTRAL_TEXT_DEFAULT` — astral Emoji_Presentation=No (FRAGILE).

    **Nie zawiera** `EMOJI_DEFAULT_BMP` — te znaki są bezpieczne
    i powinny być proponowane.
    """
    bad: set[str] = set()
    sets = det_data.get("sets", {}) or {}
    for cp in sets.get("TEXT_DEFAULT_BMP", set()):
        bad.add(chr(cp))
    for cp in sets.get("ASTRAL_TEXT_DEFAULT", set()):
        bad.add(chr(cp))
    return bad


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


# ── parser argumentów ───────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scan_emoji.py",
        description=(
            "Skaner emoji: wykrywa, mierzy szerokość dwoma metodami, "
            "proponuje zamienniki."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python scan_emoji.py src/main.rs\n"
            "  python scan_emoji.py src/\n"
            "  python scan_emoji.py . --vs16\n"
            "  python scan_emoji.py src/ --quiet --strict\n"
            "  python scan_emoji.py src/ --fragile-mode split\n"
            "  python scan_emoji.py . --plugins-dir ./moje_emoji\n"
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="plik lub katalog do skanowania (domyślnie: bieżący katalog)",
    )

    # ── filtrowanie znalezisk ──────────────────────────────────
    filt = parser.add_argument_group("filtrowanie")
    filt.add_argument(
        "--vs16",
        action="store_true",
        help="raportuj tylko VS16 (główny sprawca buga „połówki”)",
    )
    filt.add_argument(
        "--no-suggestions",
        action="store_true",
        help="pomiń sekcję z zalecanymi zamiennikami",
    )

    # ── wyjście ────────────────────────────────────────────────
    out = parser.add_argument_group("wyjście")
    out.add_argument(
        "--quiet",
        action="store_true",
        help="bez preambuły i raportu per-znalezisko "
        "(zostaje podsumowanie + końcowa linia)",
    )
    out.add_argument(
        "--strict",
        action="store_true",
        help="kod wyjścia 2, jeśli są problemy "
        "(ROZJAZD, MAŁA lub FRAGILE) — do CI",
    )

    # ── FRAGILE ────────────────────────────────────────────────
    frag = parser.add_argument_group("tryb FRAGILE")
    frag.add_argument(
        "--fragile-mode",
        choices=FRAGILE_MODES,
        default=DEFAULT_FRAGILE_MODE,
        metavar="MODE",
        help=(
            "tryb obsługi FRAGILE (astral Emoji_Presentation=No): "
            f"{', '.join(FRAGILE_MODES)} (domyślnie: {DEFAULT_FRAGILE_MODE})"
        ),
    )

    # ── pluginy ────────────────────────────────────────────────
    plug = parser.add_argument_group("pluginy")
    plug.add_argument(
        "--plugins-dir",
        default=None,
        metavar="ROOT",
        help="katalog nadrzędny pluginów "
        "(oczekuje ROOT/wykrywanie i ROOT/zamienniki)",
    )
    plug.add_argument(
        "--detection-dir",
        default=None,
        metavar="DIR",
        help="nadpisuje katalog pluginów detekcji",
    )
    plug.add_argument(
        "--replacements-dir",
        default=None,
        metavar="DIR",
        help="nadpisuje katalog pluginów zamienników",
    )

    # ── pomijanie ──────────────────────────────────────────────
    skip = parser.add_argument_group("pomijanie")
    skip.add_argument(
        "--skip-dir",
        action="append",
        default=None,
        metavar="NAME",
        help="dodatkowy katalog do pominięcia (można wielokrotnie)",
    )
    skip.add_argument(
        "--skip-ext",
        action="append",
        default=None,
        metavar="EXT",
        help="dodatkowe rozszerzenie do pominięcia (można wielokrotnie)",
    )
    skip.add_argument(
        "--no-default-skips",
        action="store_true",
        help="nie używaj domyślnych list pomijania",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"scan_emoji.py {__version__}",
    )
    return parser


# ── main ────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── walidacja celu ─────────────────────────────────────────
    target = Path(args.target).expanduser()
    if not target.exists():
        _print_err(f"BŁĄD  ścieżka nie istnieje: {args.target}")
        return EXIT_ERROR

    # ── wczytanie pluginów ─────────────────────────────────────
    detection_dir, replacements_dir = _resolve_plugin_dirs(args)

    try:
        det_data = load_plugins(detection_dir)
        rep_data = load_replacements(replacements_dir)
    except Exception as e:  # noqa: BLE001
        _print_err(f"BŁĄD  nie można wczytać pluginów: {e}")
        return EXIT_ERROR

    # budowa bad_chars (filtrowanie rodzeństwa w propozycjach)
    bad_chars = _build_bad_chars(det_data)

    # ── preambuła (chyba że --quiet) ───────────────────────────
    if not args.quiet:
        n_det = len(det_data.get("loaded", []))
        n_rep = len(rep_data.get("loaded", []))
        print(f"Pluginy: {n_det} detekcji, {n_rep} zamienników")

        # tryb FRAGILE — pokazujemy tylko gdy nie-simple
        if args.fragile_mode != DEFAULT_FRAGILE_MODE:
            print(f"Tryb FRAGILE: {args.fragile_mode}")

        all_warnings = (
            list(det_data.get("warnings", []))
            + list(rep_data.get("warnings", []))
        )
        if all_warnings:
            print(f"Ostrzeżenia pluginów ({len(all_warnings)}):")
            for w in all_warnings:
                print(f"  [UWAGA] {w}")

        if not HAS_WCWIDTH:
            print("Uwaga: brak biblioteki 'wcwidth' — tylko heurystyka.")
            print("       Dla porównania metod: pip install wcwidth")

        print()

    # ── skan ───────────────────────────────────────────────────
    only_kinds = {"VS16"} if args.vs16 else None
    skip_dirs, skip_ext = _resolve_skips(args)

    try:
        result = scan(
            target,
            det_data,
            only_kinds=only_kinds,
            skip_dirs=skip_dirs,
            skip_ext=skip_ext,
            fragile_mode=args.fragile_mode,
        )
    except Exception as e:  # noqa: BLE001
        _print_err(f"BŁĄD  skanowanie nie powiodło się: {e}")
        return EXIT_ERROR

    # ── błędy odczytu plików (zawsze na stderr) ────────────────
    if result["errors"]:
        _print_err(f"Błędy odczytu plików ({len(result['errors'])}):")
        for err in result["errors"]:
            _print_err(f"  [BŁĄD] {err['file']}: {err['error']}")
        _print_err("")

    # ── raport szczegółowy ─────────────────────────────────────
    results = result["results"]
    replacements = rep_data.get("replacements", {})

    if not args.quiet:
        print_report(
            results,
            replacements,
            show_suggestions=not args.no_suggestions,
        )

    # ── podsumowanie ───────────────────────────────────────────
    print_summary(
        results,
        replacements,
        has_wcwidth=HAS_WCWIDTH,
        bad_chars=bad_chars,
    )

    # ── końcowa linia ze statystykami ──────────────────────────
    files_with_findings = len({r["file"] for r in results})
    print(
        f"Razem: {len(results)} znalezisk w {files_with_findings} plikach "
        f"(skan: {result['files_scanned']}, pominięto: {result['files_skipped']})"
    )

    # ── tryb --strict ──────────────────────────────────────────
    if args.strict:
        problems = sum(
            1 for r in results
            if r.get("rozjazd")
            or r.get("text_default")
            or r.get("fragile")
            or r.get("fragile_with_vs16")  # dla fragile_mode="reporter"
        )
        if problems > 0:
            print(f"\n--strict: {problems} problemów do naprawy.")
            return EXIT_PROBLEMS

    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _print_err("\nPrzerwano.")
        sys.exit(EXIT_ERROR)
    except BrokenPipeError:
        sys.exit(EXIT_OK)
