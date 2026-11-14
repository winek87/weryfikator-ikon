#!/usr/bin/env python3

# tools/gen_plugin.py
# -*- coding: utf-8 -*-

"""
gen_plugin.py — CLI generatora pluginów dla skanera emoji.

Cienka warstwa nad `emoji.generator` — parsuje argumenty, wywołuje
funkcje biblioteczne i formatuje wynik. Cała logika (tworzenie,
walidacja, inspekcja) żyje w `emoji/generator.py`.

Użycie:

    python tools/gen_plugin.py detection  <name>   [opcje]
    python tools/gen_plugin.py replacement <name>  [opcje]
    python tools/gen_plugin.py list                [opcje]
    python tools/gen_plugin.py validate            [opcje]
    python tools/gen_plugin.py inspect <name|path> [opcje]

Przykłady:

    # nowy plugin detekcji (domyślnie .json, prefix 50_)
    python tools/gen_plugin.py detection warnings

    # plugin zamienników w Pythonie, z opisem
    python tools/gen_plugin.py replacement emoji_fix \\
        --py --description "Własne zamienniki dla emoji"

    # nadpisz istniejący plik
    python tools/gen_plugin.py detection warnings --force

    # lista pluginów detekcji
    python tools/gen_plugin.py list

    # lista pluginów zamienników
    python tools/gen_plugin.py list --kind replacements

    # walidacja wszystkich pluginów
    python tools/gen_plugin.py validate

    # inspekcja pluginu po nazwie (szuka w obu katalogach)
    python tools/gen_plugin.py inspect warnings

    # inspekcja po ścieżce (bez szukania)
    python tools/gen_plugin.py inspect emoji/wykrywanie/50_warnings.json

Kody wyjścia:

    0 — sukces (utworzono / wylistowano / walidacja OK / inspekcja OK)
    1 — błąd twardy (nie można zapisać, błąd składni, brak pliku)
    2 — konflikt (plik istnieje, brak --force) — dla `create`
    3 — walidacja wykazała błędy — dla `validate`
    4 — błąd użycia CLI (zły argument, brak wymaganego parametru)

Kod 2 dla konfliktu to celowe rozróżnienie: skrypt CI może zignorować
„już istnieje” (idempotencja), ale wywalić się na prawdziwym błędzie.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── bootstrap: dodaj katalog nadrzędny do sys.path ──────────────
# Dzięki temu `from emoji import ...` działa, gdy uruchamiamy
# `python tools/gen_plugin.py` z katalogu projektu lub spoza niego.
# Wstawiamy **na początek**, żeby lokalny `emoji/` wygrywał z ewentualnym
# `pip install emoji` (pakiet o tej samej nazwie istnieje na PyPI).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from emoji import __version__  # noqa: E402
from emoji.generator import (  # noqa: E402
    create_detection_plugin,
    create_replacement_plugin,
    inspect_plugin,
    list_plugins,
    validate_plugins,
)
from emoji.loader import (  # noqa: E402
    DEFAULT_DETECTION_DIR,
    DEFAULT_REPLACEMENTS_DIR,
)

# ── kody wyjścia ────────────────────────────────────────────────
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFLICT = 2
EXIT_VALIDATION = 3
EXIT_USAGE = 4


# ── pomocnicze wypisywanie ──────────────────────────────────────

def _print(msg: str = "") -> None:
    print(msg)


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _header(title: str) -> None:
    _print(f"── {title} ──")


# ── komenda: create (detection / replacement) ───────────────────

def _cmd_create(args: argparse.Namespace, kind: str) -> int:
    """
    Wspólna obsługa `detection` i `replacement`.

    Zwraca kod wyjścia: 0 sukces, 1 błąd, 2 konflikt.
    """
    target_dir = args.directory
    fn = create_detection_plugin if kind == "detection" else create_replacement_plugin

    result = fn(
        name=args.name,
        description=args.description,
        version=args.plugin_version,
        use_py=args.py,
        prefix=args.prefix,
        directory=target_dir,
        force=args.force,
    )

    fmt_label = "PY" if result["format"] == "py" else "JSON"
    kind_label = "detekcji" if kind == "detection" else "zamienników"

    if result["created"]:
        _print(f"OK  utworzono plugin {kind_label} [{fmt_label}]")
        _print(f"    {result['path']}")
        _print()
        _print("Następne kroki:")
        _print("  1. Otwórz plik i uzupełnij zawartość.")
        _print("  2. Uruchom walidację:  python tools/gen_plugin.py validate")
        _print(f"  3. Sprawdź inspekcję:  python tools/gen_plugin.py inspect {Path(result['path']).name}")
        return EXIT_OK

    # błąd — rozróżniamy konflikt od twardego błędu
    error = result.get("error") or "nieznany błąd"
    if "już istnieje" in error:
        _print_err(f"KONFLIKT  {error}")
        return EXIT_CONFLICT

    _print_err(f"BŁĄD  {error}")
    return EXIT_ERROR


# ── komenda: list ───────────────────────────────────────────────

def _cmd_list(args: argparse.Namespace) -> int:
    """Listuje pluginy w wybranym katalogu."""
    kind = args.kind
    directory = args.directory

    items = list_plugins(directory=directory, kind=kind)

    if directory is None:
        shown_dir = (
            DEFAULT_REPLACEMENTS_DIR if kind == "replacements" else DEFAULT_DETECTION_DIR
        )
    else:
        shown_dir = Path(directory).resolve()

    _header(f"PLUGINY ({kind}) — {shown_dir}")
    _print()

    if not items:
        _print("  (brak pluginów)")
        _print()
        return EXIT_OK

    # kolumny: FILE | FORMAT | NAME | VERSION | OPIS
    for item in items:
        if item.get("error"):
            _print(f"  [BŁĄD] {item['file']}  —  {item['error']}")
            continue
        fmt = item["format"].upper()
        name = item["name"]
        version = item["version"] or "—"
        desc = item["description"] or "—"
        _print(f"  {item['file']:<32} [{fmt:<4}] {name:<20} v{version:<6} {desc}")

    _print()
    _print(f"Razem: {len(items)}")
    _print()
    return EXIT_OK


# ── komenda: validate ───────────────────────────────────────────

def _cmd_validate(args: argparse.Namespace) -> int:
    """Waliduje wszystkie pluginy (składnia + duplikaty)."""
    report = validate_plugins(
        detection_dir=args.detection_dir,
        replacements_dir=args.replacements_dir,
    )

    _header("WALIDACJA PLUGINÓW")
    _print()

    # detekcja
    det = report["detection"]
    _print(f"Detekcja:     {det['dir']}")
    _print(f"  wczytane:   {len(det['files'])}")
    _print(f"  błędy:      {len(det['errors'])}")
    for err in det["errors"]:
        _print(f"    [BŁĄD] {err['file']}: {err['error']}")
    _print()

    # zamienniki
    rep = report["replacements"]
    _print(f"Zamienniki:   {rep['dir']}")
    _print(f"  wczytane:   {len(rep['files'])}")
    _print(f"  błędy:      {len(rep['errors'])}")
    for err in rep["errors"]:
        _print(f"    [BŁĄD] {err['file']}: {err['error']}")
    _print()

    # cross — ostrzeżenia
    cross = report["cross"]
    _print(f"Ostrzeżenia (duplikaty między pluginami): {len(cross['warnings'])}")
    for w in cross["warnings"]:
        _print(f"    [UWAGA] {w}")
    _print()

    if report["ok"]:
        _print("WYNIK: OK — wszystkie pluginy wczytane poprawnie.")
        return EXIT_OK

    _print("WYNIK: BŁĘDY — popraw pluginy i uruchom ponownie.")
    return EXIT_VALIDATION


# ── komenda: inspect ────────────────────────────────────────────

def _resolve_inspect_target(name_or_path: str) -> Path | None:
    """
    Zamienia argument `inspect` na ścieżkę.

    Kolejność:
      1. Jeśli istnieje jako plik → użyj go.
      2. Szukaj w `emoji/wykrywanie/` jako `<arg>.json` / `<arg>.py`
         i z prefixami `00_`, `10_`, `20_`, `30_`, `40_`, `50_`.
      3. To samo w `emoji/zamienniki/`.
      4. Nie znaleziono → None.

    Dzięki temu `inspect warnings` znajduje `50_warnings.json`,
    a `inspect emoji/wykrywanie/50_warnings.json` działa bezpośrednio.
    """
    p = Path(name_or_path)
    if p.is_file():
        return p

    candidates = [name_or_path]
    for prefix in ("00_", "10_", "20_", "30_", "40_", "50_"):
        candidates.append(f"{prefix}{name_or_path}")

    for base in (DEFAULT_DETECTION_DIR, DEFAULT_REPLACEMENTS_DIR):
        if not base.is_dir():
            continue
        for cand in candidates:
            for ext in (".json", ".py"):
                full = base / f"{cand}{ext}"
                if full.is_file():
                    return full

    return None


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Inspekcja pojedynczego pluginu."""
    target = _resolve_inspect_target(args.target)
    if target is None:
        _print_err(f"BŁĄD  nie znaleziono pluginu: {args.target}")
        _print_err("       spróbuj podać ścieżkę lub nazwę z katalogu emoji/")
        return EXIT_ERROR

    info = inspect_plugin(target)

    if info.get("error"):
        _print_err(f"BŁĄD  {info['error']}")
        _print_err(f"       plik: {info['path']}")
        return EXIT_ERROR

    _header(f"INSPEKCJA — {Path(info['path']).name}")
    _print()
    _print(f"  ścieżka:    {info['path']}")
    _print(f"  format:     {info['format'].upper()}")
    _print(f"  rodzaj:     {info['kind']}")

    if info["kind"] == "detection":
        _print()
        _print(f"  codepoints: {info.get('codepoints_count', 0)}")
        _print(f"  ranges:     {info.get('ranges_count', 0)}")
        sets = info.get("sets", {})
        if sets:
            _print(f"  sets:       {len(sets)}")
            for name, size in sets.items():
                _print(f"    - {name}: {size}")
        else:
            _print("  sets:       0")

    elif info["kind"] == "replacements":
        _print()
        _print(f"  replacements: {info.get('replacements_count', 0)}")
        sample = info.get("sample_keys", [])
        if sample:
            _print(f"  przykłady:  {', '.join(repr(k) for k in sample)}")

    else:
        _print()
        _print("  (nie rozpoznano rodzaju pluginu)")

    _print()
    return EXIT_OK


# ── parser argumentów ───────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gen_plugin.py",
        description="Generator i walidator pluginów dla skanera emoji.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python tools/gen_plugin.py detection warnings\n"
            "  python tools/gen_plugin.py replacement emoji_fix --py --description '...'\n"
            "  python tools/gen_plugin.py list\n"
            "  python tools/gen_plugin.py validate\n"
            "  python tools/gen_plugin.py inspect warnings\n"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gen_plugin.py {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="<komenda>")

    # ── detection ──────────────────────────────────────────────
    p_det = sub.add_parser("detection", help="utwórz nowy plugin detekcji")
    _add_create_args(p_det)

    # ── replacement ────────────────────────────────────────────
    p_rep = sub.add_parser("replacement", help="utwórz nowy plugin zamienników")
    _add_create_args(p_rep)

    # ── list ───────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="lista pluginów w katalogu")
    p_list.add_argument(
        "--kind",
        choices=("detection", "replacements"),
        default="detection",
        help="rodzaj pluginów do wylistowania (domyślnie: detection)",
    )
    p_list.add_argument(
        "--directory",
        default=None,
        help="katalog do przeszukania (domyślnie: emoji/wykrywanie/ lub emoji/zamienniki/)",
    )

    # ── validate ───────────────────────────────────────────────
    p_val = sub.add_parser("validate", help="waliduj wszystkie pluginy")
    p_val.add_argument(
        "--detection-dir",
        default=None,
        help="katalog pluginów detekcji (domyślnie: emoji/wykrywanie/)",
    )
    p_val.add_argument(
        "--replacements-dir",
        default=None,
        help="katalog pluginów zamienników (domyślnie: emoji/zamienniki/)",
    )

    # ── inspect ────────────────────────────────────────────────
    p_ins = sub.add_parser("inspect", help="inspekcja pojedynczego pluginu")
    p_ins.add_argument(
        "target",
        help="nazwa pluginu (np. 'warnings') lub ścieżka do pliku",
    )

    return parser


def _add_create_args(p: argparse.ArgumentParser) -> None:
    """Wspólne argumenty dla `detection` i `replacement`."""
    p.add_argument("name", help="nazwa pluginu (bez rozszerzenia)")
    p.add_argument(
        "--description",
        default="",
        help="opis pluginu (trafi do DESCRIPTION)",
    )
    p.add_argument(
        "--version",
        default="1.0",
        dest="plugin_version",
        help="wersja pluginu (domyślnie: 1.0)",
    )
    p.add_argument(
        "--py",
        action="store_true",
        help="utwórz plugin w Pythonie (.py) zamiast JSON (.json)",
    )
    p.add_argument(
        "--prefix",
        default="50_",
        help="prefix nazwy pliku (domyślnie: 50_)",
    )
    p.add_argument(
        "--directory",
        default=None,
        help="katalog docelowy (domyślnie: emoji/wykrywanie/ lub emoji/zamienniki/)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="nadpisz istniejący plik",
    )


# ── main ────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    # sanityzacja: dla create musi być plugin_version
    if args.command in ("detection", "replacement"):
        if not hasattr(args, "plugin_version"):
            _print_err("BŁĄD  wewnętrzny: brak atrybutu plugin_version")
            return EXIT_ERROR

    # argparse używa `args.version` na dwa sposoby — dla `--version`
    # na poziomie parsera i dla `--version` w create. Rozróżniamy:
    # komenda `create` ma `plugin_version`, top-level ma `version`.
    # Tu nic nie robimy — to tylko komentarz wyjaśniający.

    try:
        if args.command == "detection":
            return _cmd_create(args, "detection")
        if args.command == "replacement":
            return _cmd_create(args, "replacement")
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "inspect":
            return _cmd_inspect(args)
    except KeyboardInterrupt:
        _print_err("\nPrzerwano.")
        return EXIT_ERROR
    except BrokenPipeError:
        # np. `gen_plugin.py list | head -1` — wyjście zamknięte.
        return EXIT_OK

    _print_err(f"BŁĄD  nieznana komenda: {args.command}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
