#!/usr/bin/env python3

# emoji/generator.py
# -*- coding: utf-8 -*-

"""
emoji.generator — tworzenie, modyfikacja i walidacja pluginów.

Ten moduł zawiera **czystą logikę** — żadnych `print`, `sys.argv`,
`sys.exit`. CLI (`tools/gen_plugin.py` i `tools/emoji_wizard.py`)
używają go jako biblioteki i same decydują, co i jak wypisać.
Dzięki temu generator jest testowalny bez mockowania `stdout`.

Funkcje publiczne — v1.0 (bez zmian):

  * `create_detection_plugin(...)` — tworzy nowy plugin detekcji,
  * `create_replacement_plugin(...)` — to samo dla zamienników,
  * `list_plugins(directory, kind)` — lista pluginów w katalogu,
  * `validate_plugins(detection_dir, replacements_dir)` — walidacja,
  * `inspect_plugin(path)` — podsumowanie pojedynczego pluginu.

Funkcje publiczne — v2.0 (bez zmian):

  * `guess_category(ch, detection_data=None)` — auto-klasyfikacja,
  * `find_emoji_entries(cp, detection_dir=None)` — gdzie jest codepoint,
  * `find_replacement_entries(ch, replacements_dir=None)` — gdzie jest zamiennik,
  * `add_emoji_to_plugin(path, cp, set_name, ...)` — dopisanie do zbioru,
  * `add_replacement_to_plugin(path, ch, rec, alt, why, ...)` — dopisanie zamiennika,
  * `remove_plugin_file(path, backup=True)` — backup + usunięcie.

Funkcje publiczne — v3.0 (nowe):

  * `find_plugins_with_set(set_name, detection_dir=None)` — lista plików
        zawierających dany zbiór (np. `TEXT_DEFAULT_BMP`). Przeniesione
        z `tools/emoji_wizard.py` (`_find_plugins_with_set`), żeby wizard
        mógł być cieńszy.

Zmiany v3.0 w `guess_category`:

  * nowa kategoria `ASTRAL_TEXT_DEFAULT` — sprawdzana **przed** ogólnym
        warunkiem `cp > 0xFFFF`. Wcześniej `🛡` (U+1F6E1) był klasyfikowany
        jako `EMOJI_DEFAULT_BMP` (bo astralny), co było błędne —
        ten znak ma `Emoji_Presentation=No` i wymaga VS16 lub zamiennika.

Konwencje v2.0/v3.0:

  * Klucze zamienników są **zawsze bazowe** (bez VS16/VS15/ZWJ/KEYCAP).
  * Sekwencje ZWJ (np. `👨‍👩‍👧`) są odrzucane — zbyt złożone.
  * Modyfikacja istniejącego `.json` **normalizuje formatowanie**.
  * Pliki `.py` **nie są modyfikowane automatycznie** — wizard otwiera
    je w `$EDITOR`. Powód: automatyczna edycja zniszczyłaby komentarze.
"""

from __future__ import annotations

import json
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

from .detection import measure_wcwidth
from .loader import (
    DEFAULT_DETECTION_DIR,
    DEFAULT_REPLACEMENTS_DIR,
    _iter_plugin_files,
    load_detection_file,
    load_plugins,
    load_replacement_file,
    load_replacements,
)

DEFAULT_PREFIX = "50_"
DEFAULT_VERSION = "1.0"
_FORMAT_JSON = "json"
_FORMAT_PY = "py"


# ── pomocnicze (v1.0, bez zmian) ────────────────────────────────

def _sanitize_name(name: str) -> str:
    """Zamienia dowolną nazwę na bezpieczną nazwę pliku."""
    cleaned = "".join(
        c if (c.isalnum() or c in "-_") else "_" for c in name
    )
    return cleaned.strip("_") or "plugin"


def _target_path(name: str, directory: Path, prefix: str, use_py: bool) -> Path:
    """Składa ścieżkę docelową: `<prefix><name>.<ext>`."""
    stem = f"{prefix}{_sanitize_name(name)}"
    ext = ".py" if use_py else ".json"
    return directory / f"{stem}{ext}"


def _unicode_name(cp: int) -> str:
    """Zwraca nazwę Unicode dla codepointu lub '<unknown>'."""
    try:
        return unicodedata.name(chr(cp), "<unknown>")
    except (ValueError, TypeError):
        return "<unknown>"


# ── szablony (v1.0, bez zmian) ──────────────────────────────────

_TPL_DETECTION_JSON = """{
  "name": "__NAME__",
  "description": "__DESC__",
  "version": "__VERSION__",
  "codepoints": [],
  "ranges": [],
  "sets": {}
}
"""

_TPL_DETECTION_PY = '''"""Plugin detekcji: __NAME__.

__DESC__
"""

NAME = "__NAME__"
DESCRIPTION = "__DESC__"
VERSION = "__VERSION__"

CODEPOINTS = {}
RANGES = []
SETS = {}
'''

_TPL_REPLACEMENT_JSON = """{
  "name": "__NAME__",
  "description": "__DESC__",
  "version": "__VERSION__",
  "replacements": {}
}
"""

_TPL_REPLACEMENT_PY = '''"""Plugin zamienników: __NAME__.

__DESC__
"""

NAME = "__NAME__"
DESCRIPTION = "__DESC__"
VERSION = "__VERSION__"

REPLACEMENTS = {}
'''


def _render(template: str, name: str, description: str, version: str) -> str:
    """Podstawia placeholdery w szablonie."""
    return (
        template
        .replace("__NAME__", name)
        .replace("__DESC__", description)
        .replace("__VERSION__", version)
    )


# ── v1.0: create_detection_plugin ───────────────────────────────

def create_detection_plugin(
    name: str,
    description: str = "",
    version: str = DEFAULT_VERSION,
    use_py: bool = False,
    prefix: str = DEFAULT_PREFIX,
    directory: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Tworzy nowy plugin detekcji. Zwraca dict z path/created/error/format."""
    dir_path = Path(directory).resolve() if directory else DEFAULT_DETECTION_DIR
    target = _target_path(name, dir_path, prefix, use_py)

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {
            "path": str(target),
            "created": False,
            "error": f"nie można utworzyć katalogu {dir_path}: {e}",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    if target.exists() and not force:
        return {
            "path": str(target),
            "created": False,
            "error": f"plik już istnieje: {target} (użyj --force, aby nadpisać)",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    template = _TPL_DETECTION_PY if use_py else _TPL_DETECTION_JSON
    content = _render(template, name, description, version)

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {
            "path": str(target),
            "created": False,
            "error": f"nie można zapisać {target}: {e}",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    return {
        "path": str(target),
        "created": True,
        "error": None,
        "format": _FORMAT_PY if use_py else _FORMAT_JSON,
    }


# ── v1.0: create_replacement_plugin ─────────────────────────────

def create_replacement_plugin(
    name: str,
    description: str = "",
    version: str = DEFAULT_VERSION,
    use_py: bool = False,
    prefix: str = DEFAULT_PREFIX,
    directory: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Tworzy nowy plugin zamienników. Format wyniku jak create_detection_plugin."""
    dir_path = Path(directory).resolve() if directory else DEFAULT_REPLACEMENTS_DIR
    target = _target_path(name, dir_path, prefix, use_py)

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {
            "path": str(target),
            "created": False,
            "error": f"nie można utworzyć katalogu {dir_path}: {e}",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    if target.exists() and not force:
        return {
            "path": str(target),
            "created": False,
            "error": f"plik już istnieje: {target} (użyj --force, aby nadpisać)",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    template = _TPL_REPLACEMENT_PY if use_py else _TPL_REPLACEMENT_JSON
    content = _render(template, name, description, version)

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {
            "path": str(target),
            "created": False,
            "error": f"nie można zapisać {target}: {e}",
            "format": _FORMAT_PY if use_py else _FORMAT_JSON,
        }

    return {
        "path": str(target),
        "created": True,
        "error": None,
        "format": _FORMAT_PY if use_py else _FORMAT_JSON,
    }


# ── v1.0: list_plugins ──────────────────────────────────────────

def list_plugins(
    directory: str | Path | None = None,
    kind: str = "detection",
) -> list[dict]:
    """Zwraca listę pluginów w katalogu z metadanymi."""
    if directory is None:
        directory = (
            DEFAULT_REPLACEMENTS_DIR
            if kind == "replacements"
            else DEFAULT_DETECTION_DIR
        )
    dir_path = Path(directory).resolve()

    out: list[dict] = []
    for path in _iter_plugin_files(dir_path):
        fmt = _FORMAT_PY if path.suffix.lower() == ".py" else _FORMAT_JSON
        item = {
            "file": path.name,
            "path": str(path),
            "format": fmt,
            "name": path.stem,
            "description": "",
            "version": "",
            "error": None,
        }
        try:
            if kind == "replacements":
                load_replacement_file(path)
            else:
                load_detection_file(path)
        except Exception as e:  # noqa: BLE001
            item["error"] = str(e)
            out.append(item)
            continue

        item.update(_read_meta(path, fmt))
        out.append(item)
    return out


def _read_meta(path: Path, fmt: str) -> dict:
    """Odczytuje NAME/DESCRIPTION/VERSION z pluginu."""
    try:
        if fmt == _FORMAT_JSON:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "name": str(data.get("name", path.stem)),
                "description": str(data.get("description", "")),
                "version": str(data.get("version", "")),
            }
        from .loader import _load_py_module
        mod = _load_py_module(path)
        return {
            "name": str(getattr(mod, "NAME", path.stem)),
            "description": str(getattr(mod, "DESCRIPTION", "")),
            "version": str(getattr(mod, "VERSION", "")),
        }
    except Exception:  # noqa: BLE001
        return {"name": path.stem, "description": "", "version": ""}


# ── v1.0: validate_plugins ──────────────────────────────────────

def validate_plugins(
    detection_dir: str | Path | None = None,
    replacements_dir: str | Path | None = None,
) -> dict:
    """Ładuje wszystkie pluginy i raportuje problemy."""
    det_dir = (
        Path(detection_dir).resolve() if detection_dir else DEFAULT_DETECTION_DIR
    )
    rep_dir = (
        Path(replacements_dir).resolve()
        if replacements_dir
        else DEFAULT_REPLACEMENTS_DIR
    )

    report = {
        "detection": {"dir": str(det_dir), "files": [], "errors": []},
        "replacements": {"dir": str(rep_dir), "files": [], "errors": []},
        "cross": {"warnings": [], "loaded": []},
        "ok": True,
    }

    for path in _iter_plugin_files(det_dir):
        try:
            load_detection_file(path)
            report["detection"]["files"].append(path.name)
        except Exception as e:  # noqa: BLE001
            report["detection"]["errors"].append(
                {"file": path.name, "error": str(e)}
            )
            report["ok"] = False

    for path in _iter_plugin_files(rep_dir):
        try:
            load_replacement_file(path)
            report["replacements"]["files"].append(path.name)
        except Exception as e:  # noqa: BLE001
            report["replacements"]["errors"].append(
                {"file": path.name, "error": str(e)}
            )
            report["ok"] = False

    det_state = load_plugins(det_dir)
    rep_state = load_replacements(rep_dir)
    report["cross"]["warnings"] = (
        list(det_state.get("warnings", []))
        + list(rep_state.get("warnings", []))
    )
    report["cross"]["loaded"] = (
        list(det_state.get("loaded", []))
        + list(rep_state.get("loaded", []))
    )

    return report


# ── v1.0: inspect_plugin ────────────────────────────────────────

def inspect_plugin(path: str | Path) -> dict:
    """Ładuje pojedynczy plugin i zwraca podsumowanie."""
    p = Path(path).resolve()
    fmt = _FORMAT_PY if p.suffix.lower() == ".py" else _FORMAT_JSON

    result = {
        "path": str(p),
        "format": fmt,
        "kind": "unknown",
        "error": None,
    }

    if not p.is_file():
        result["error"] = f"plik nie istnieje: {p}"
        return result

    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as e:
        result["error"] = str(e)
        return result

    if fmt == _FORMAT_JSON:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            result["error"] = f"JSON: {e}"
            return result
        if "replacements" in data:
            result["kind"] = "replacements"
        elif any(k in data for k in ("codepoints", "ranges", "sets")):
            result["kind"] = "detection"
        else:
            return result
    else:
        from .loader import _load_py_module
        try:
            mod = _load_py_module(p)
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
            return result
        if hasattr(mod, "REPLACEMENTS"):
            result["kind"] = "replacements"
        elif any(hasattr(mod, k) for k in ("CODEPOINTS", "RANGES", "SETS")):
            result["kind"] = "detection"
        else:
            return result

    try:
        if result["kind"] == "detection":
            d = load_detection_file(p)
            result["codepoints_count"] = len(d.get("codepoints", {}))
            result["ranges_count"] = len(d.get("ranges", []))
            result["sets"] = {
                name: len(values) for name, values in d.get("sets", {}).items()
            }
        else:
            r = load_replacement_file(p)
            result["replacements_count"] = len(r)
            result["sample_keys"] = list(r.keys())[:5]
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)

    return result


# ════════════════════════════════════════════════════════════════
# v2.0 — FUNKCJE DLA WIZARDA (bez zmian w v3.0 poza guess_category)
# ════════════════════════════════════════════════════════════════


def _normalize_base_ch(ch: str) -> tuple[str | None, str | None]:
    """
    Normalizuje wklejony znak do postaci bazowej.

    Zwraca (base, error_reason):
      * base         — znak bazowy (bez VS16/VS15/ZWJ/KEYCAP),
      * error_reason — None przy sukcesie, "empty" / "zwj_not_supported".
    """
    if not ch:
        return None, "empty"

    cps = [ord(c) for c in ch]
    if 0x200D in cps:
        return None, "zwj_not_supported"

    return ch[0], None


# ── v3.0: guess_category (rozszerzone o ASTRAL_TEXT_DEFAULT) ────

def guess_category(
    ch: str,
    detection_data: dict | None = None,
) -> dict:
    """
    Auto-klasyfikuje wklejony znak na podstawie aktualnych pluginów.

    Parametry:
        ch:              wklejony znak (może być klastrem, np. "⚙️"),
        detection_data:  wynik `load_plugins()`. None → ładuje domyślne.

    Zwraca dict:
        {
          "ok":            bool,
          "error":         str | None,
          "ch":            str,
          "original_ch":   str,
          "was_modified":  bool,
          "cp":            str,
          "cp_int":        int,
          "name":          str,
          "wcwidth":       int | None,
          "kind":          "TEXT_DEFAULT_BMP" | "EMOJI_DEFAULT_BMP"
                           | "ASTRAL_TEXT_DEFAULT"
                           | "UNKNOWN_EMOJI" | "NOT_EMOJI",
          "confidence":    "certain" | "guess",
          "suggested_set": str | None,
          "reason":        str,
        }

    Kolejność sprawdzania (v3.0):
      1. `ASTRAL_TEXT_DEFAULT` — najważniejsze, bo astralne
         Emoji_Presentation=No inaczej wpadłyby w regułę `cp > 0xFFFF`,
      2. `TEXT_DEFAULT_BMP`,
      3. `EMOJI_DEFAULT_BMP`,
      4. `cp > 0xFFFF` → EMOJI_DEFAULT_BMP (tylko dla NIE-ASTRAL_TEXT_DEFAULT),
      5. w zakresach → UNKNOWN_EMOJI,
      6. poza → NOT_EMOJI.
    """
    base, error = _normalize_base_ch(ch)

    if base is None:
        return {
            "ok": False,
            "error": error,
            "ch": ch,
            "original_ch": ch,
            "was_modified": False,
            "cp": "",
            "cp_int": 0,
            "name": "",
            "wcwidth": None,
            "kind": "NOT_EMOJI",
            "confidence": "guess",
            "suggested_set": None,
            "reason": _reason_for_error(error),
        }

    cp = ord(base)
    w_wc = measure_wcwidth(base)

    if detection_data is None:
        detection_data = load_plugins()

    sets = detection_data.get("sets", {}) or {}
    ranges = detection_data.get("ranges", []) or []
    text_bmp = sets.get("TEXT_DEFAULT_BMP", set())
    emoji_bmp = sets.get("EMOJI_DEFAULT_BMP", set())
    astral_text = sets.get("ASTRAL_TEXT_DEFAULT", set())
    font_risky = sets.get("FONT_RISKY_BMP", set())

    info = {
        "ok": True,
        "error": None,
        "ch": base,
        "original_ch": ch,
        "was_modified": (ch != base),
        "cp": f"U+{cp:04X}",
        "cp_int": cp,
        "name": _unicode_name(cp),
        "wcwidth": w_wc,
        "kind": "NOT_EMOJI",
        "confidence": "guess",
        "suggested_set": None,
        "reason": "",
    }

    # 1) ASTRAL_TEXT_DEFAULT — przed ogólnym astralnym!
    if cp in astral_text:
        info.update(
            kind="ASTRAL_TEXT_DEFAULT",
            confidence="certain",
            suggested_set="ASTRAL_TEXT_DEFAULT",
            reason=(
                "astral z Emoji_Presentation=No — bez VS16 renderuje się "
                "mały/tekstowy, z VS16 zależy od fontu (FRAGILE)"
            ),
        )
        return info

    # 2) TEXT_DEFAULT_BMP
    if cp in text_bmp:
        info.update(
            kind="TEXT_DEFAULT_BMP",
            confidence="certain",
            suggested_set="TEXT_DEFAULT_BMP",
            reason="jest w zbiorze TEXT_DEFAULT_BMP",
        )
        return info

    # 3) FONT_RISKY_BMP — PRZED EMOJI_DEFAULT_BMP!
    # ⚡ (U+26A1) jest w OBU zbiorach. FONT_RISKY_BMP ma pierwszeństwo.
    if cp in font_risky:
        info.update(
            kind="FONT_RISK",
            confidence="certain",
            suggested_set="FONT_RISKY_BMP",
            reason=(
                "BMP emoji z FONT_RISKY_BMP — w niektórych fontach "
                "renderuje się mało (mimo Emoji_Presentation=Yes)"
            ),
        )
        return info

    # 4) EMOJI_DEFAULT_BMP
    if cp in emoji_bmp:
        info.update(
            kind="EMOJI_DEFAULT_BMP",
            confidence="certain",
            suggested_set="EMOJI_DEFAULT_BMP",
            reason="jest w zbiorze EMOJI_DEFAULT_BMP",
        )
        return info

    # 4) astralny nie-ASTRAL_TEXT_DEFAULT
    if cp > 0xFFFF:
        info.update(
            kind="EMOJI_DEFAULT_BMP",
            confidence="certain",
            suggested_set="EMOJI_DEFAULT_BMP",
            reason="astralny (> U+FFFF) — zawsze duże (Emoji_Presentation=Yes)",
        )
        return info

    in_range = any(lo <= cp <= hi for lo, hi in ranges)

    # 5) UNKNOWN_EMOJI
    if in_range:
        suggested = "EMOJI_DEFAULT_BMP" if w_wc == 2 else "TEXT_DEFAULT_BMP"
        info.update(
            kind="UNKNOWN_EMOJI",
            confidence="guess",
            suggested_set=suggested,
            reason=(
                f"w zakresie emoji, ale nie w zbiorze; "
                f"wcwidth={w_wc if w_wc is not None else '—'} "
                f"→ sugeruję {suggested}"
            ),
        )
        return info

    # 6) NOT_EMOJI
    suggested = "TEXT_DEFAULT_BMP" if w_wc in (1, None) else None
    info.update(
        kind="NOT_EMOJI",
        confidence="guess",
        suggested_set=suggested,
        reason=(
            f"poza zakresami emoji; "
            f"wcwidth={w_wc if w_wc is not None else '—'} "
            + (f"→ sugeruję {suggested}" if suggested else "→ brak sugestii")
        ),
    )
    return info


def _reason_for_error(error: str | None) -> str:
    """Zwraca uzasadnienie błędu normalizacji."""
    if error == "empty":
        return "pusty znak — nic nie wklejono"
    if error == "zwj_not_supported":
        return (
            "sekwencja ZWJ (np. rodzina emoji) — zbyt złożona dla wizarda; "
            "dodaj ręcznie przez edycję pluginu"
        )
    return "nieznany błąd normalizacji"


# ── v2.0: find_emoji_entries ────────────────────────────────────

def find_emoji_entries(
    cp: int,
    detection_dir: str | Path | None = None,
) -> list[dict]:
    """Szuka codepointu we wszystkich pluginach detekcji."""
    dir_path = (
        Path(detection_dir).resolve() if detection_dir else DEFAULT_DETECTION_DIR
    )
    out: list[dict] = []

    for path in _iter_plugin_files(dir_path):
        fmt = _FORMAT_PY if path.suffix.lower() == ".py" else _FORMAT_JSON
        try:
            data = load_detection_file(path)
        except Exception:  # noqa: BLE001
            continue

        if cp in data.get("codepoints", {}):
            out.append(
                {
                    "file": path.name,
                    "set_name": None,
                    "kind": "codepoint",
                    "format": fmt,
                }
            )

        for set_name, values in data.get("sets", {}).items():
            if cp in values:
                out.append(
                    {
                        "file": path.name,
                        "set_name": set_name,
                        "kind": "set",
                        "format": fmt,
                    }
                )

        for lo, hi in data.get("ranges", []):
            if lo <= cp <= hi:
                out.append(
                    {
                        "file": path.name,
                        "set_name": None,
                        "kind": "range",
                        "format": fmt,
                    }
                )
                break

    return out


# ── v3.0: find_plugins_with_set ─────────────────────────────────

def find_plugins_with_set(
    set_name: str,
    detection_dir: str | Path | None = None,
) -> list[str]:
    """
    Zwraca nazwy plików pluginów, które zawierają dany zbiór.

    Parametry:
        set_name:       nazwa zbioru (np. "TEXT_DEFAULT_BMP"),
        detection_dir:  katalog pluginów (None → domyślny).

    Zwraca listę nazw plików (posortowaną alfabetycznie).
    Pliki, których nie da się wczytać, są pomijane.
    """
    dir_path = (
        Path(detection_dir).resolve() if detection_dir else DEFAULT_DETECTION_DIR
    )
    out: list[str] = []
    for path in _iter_plugin_files(dir_path):
        try:
            data = load_detection_file(path)
        except Exception:  # noqa: BLE001
            continue
        if set_name in data.get("sets", {}):
            out.append(path.name)
    return out


# ── v2.0: find_replacement_entries ──────────────────────────────

def find_replacement_entries(
    ch: str,
    replacements_dir: str | Path | None = None,
) -> list[dict]:
    """Szuka zamiennika we wszystkich pluginach zamienników."""
    base, error = _normalize_base_ch(ch)
    if base is None:
        return []

    dir_path = (
        Path(replacements_dir).resolve()
        if replacements_dir
        else DEFAULT_REPLACEMENTS_DIR
    )
    out: list[dict] = []

    for path in _iter_plugin_files(dir_path):
        fmt = _FORMAT_PY if path.suffix.lower() == ".py" else _FORMAT_JSON
        try:
            data = load_replacement_file(path)
        except Exception:  # noqa: BLE001
            continue
        if base in data:
            entry = data[base]
            out.append(
                {
                    "file": path.name,
                    "rec": entry.get("rec", ""),
                    "alt": list(entry.get("alt") or []),
                    "why": str(entry.get("why", "")),
                    "format": fmt,
                }
            )
    return out


# ── v2.0: add_emoji_to_plugin ───────────────────────────────────

def add_emoji_to_plugin(
    path: str | Path,
    cp: int,
    set_name: str,
    *,
    create_name: str | None = None,
    create_description: str = "",
) -> dict:
    """Dopisuje codepoint do wskazanego zbioru w pluginie."""
    p = Path(path).resolve()
    fmt = _FORMAT_PY if p.suffix.lower() == ".py" else _FORMAT_JSON

    result = {
        "ok": False,
        "changed": False,
        "error": None,
        "path": str(p),
        "cp": f"U+{cp:04X}",
        "set_name": set_name,
        "created": False,
    }

    if not (0 <= cp <= 0x10FFFF):
        result["error"] = f"codepoint poza zakresem Unicode: {cp}"
        return result
    if not set_name or not isinstance(set_name, str):
        result["error"] = f"niepoprawna nazwa zbioru: {set_name!r}"
        return result

    cp_str = f"U+{cp:04X}"

    if not p.exists():
        if create_name is None:
            create_name = p.stem
        if not create_description:
            create_description = (
                f"Plugin utworzony przez wizard: {set_name}"
            )

        if fmt == _FORMAT_JSON:
            data = {
                "name": create_name,
                "description": create_description,
                "version": DEFAULT_VERSION,
                "codepoints": [],
                "ranges": [],
                "sets": {set_name: [cp_str]},
            }
            content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        else:
            created = create_detection_plugin(
                name=p.stem,
                description=create_description,
                use_py=True,
                prefix="",
                directory=p.parent,
                force=False,
            )
            if not created["created"]:
                result["error"] = created["error"]
                return result
            result.update(
                ok=True,
                error=(
                    f"utworzono pusty plugin .py: {p} — "
                    f"dodaj wpis {cp_str} ręcznie w SETS[{set_name!r}]"
                ),
                created=True,
            )
            return result

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            result["error"] = f"nie można zapisać {p}: {e}"
            return result

        result.update(ok=True, changed=True, created=True)
        return result

    if fmt == _FORMAT_PY:
        result["error"] = (
            f"{p.name} to plugin .py — otwórz w edytorze i dodaj "
            f"{cp_str} do SETS[{set_name!r}] ręcznie"
        )
        return result

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        result["error"] = f"nie można wczytać {p.name}: {e}"
        return result

    sets = raw.setdefault("sets", {})
    if not isinstance(sets, dict):
        result["error"] = f"{p.name}: pole 'sets' nie jest obiektem"
        return result

    values = sets.setdefault(set_name, [])
    if not isinstance(values, list):
        result["error"] = (
            f"{p.name}: sets[{set_name!r}] nie jest listą"
        )
        return result

    if cp_str in values:
        result["error"] = (
            f"{cp_str} już jest w sets[{set_name!r}] w {p.name}"
        )
        return result

    values.append(cp_str)

    try:
        p.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        result["error"] = f"nie można zapisać {p}: {e}"
        return result

    result.update(ok=True, changed=True)
    return result


# ── v2.0: add_replacement_to_plugin ─────────────────────────────

def add_replacement_to_plugin(
    path: str | Path,
    ch: str,
    rec: str,
    alt: list[str] | None = None,
    why: str = "",
    *,
    create_name: str | None = None,
    create_description: str = "",
) -> dict:
    """Dopisuje zamiennik do pluginu."""
    base, error = _normalize_base_ch(ch)
    result = {
        "ok": False,
        "changed": False,
        "error": None,
        "path": str(Path(path).resolve()),
        "ch": base or ch,
        "rec": rec,
        "created": False,
        "was_modified": bool(base and ch != base),
    }

    if base is None:
        result["error"] = _reason_for_error(error)
        return result

    if not rec:
        result["error"] = "brak zalecanego zamiennika (rec jest pusty)"
        return result

    p = Path(path).resolve()
    fmt = _FORMAT_PY if p.suffix.lower() == ".py" else _FORMAT_JSON
    alt = list(alt) if alt else []
    entry = {"rec": rec, "alt": alt, "why": why}

    if not p.exists():
        if create_name is None:
            create_name = p.stem
        if not create_description:
            create_description = "Plugin utworzony przez wizard"

        if fmt == _FORMAT_JSON:
            data = {
                "name": create_name,
                "description": create_description,
                "version": DEFAULT_VERSION,
                "replacements": {base: entry},
            }
            content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except OSError as e:
                result["error"] = f"nie można zapisać {p}: {e}"
                return result
            result.update(ok=True, changed=True, created=True)
            return result

        created = create_replacement_plugin(
            name=p.stem,
            description=create_description,
            use_py=True,
            prefix="",
            directory=p.parent,
            force=False,
        )
        if not created["created"]:
            result["error"] = created["error"]
            return result
        result.update(
            ok=True,
            error=(
                f"utworzono pusty plugin .py: {p} — "
                f"dodaj wpis REPLACEMENTS[{base!r}] ręcznie"
            ),
            created=True,
        )
        return result

    if fmt == _FORMAT_PY:
        result["error"] = (
            f"{p.name} to plugin .py — otwórz w edytorze i dodaj "
            f"REPLACEMENTS[{base!r}] ręcznie"
        )
        return result

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        result["error"] = f"nie można wczytać {p.name}: {e}"
        return result

    reps = raw.setdefault("replacements", {})
    if not isinstance(reps, dict):
        result["error"] = f"{p.name}: pole 'replacements' nie jest obiektem"
        return result

    if base in reps:
        result["error"] = f"{base!r} już istnieje w {p.name}"
        return result

    reps[base] = entry

    try:
        p.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        result["error"] = f"nie można zapisać {p}: {e}"
        return result

    result.update(ok=True, changed=True)
    return result


# ── v2.0: remove_plugin_file ────────────────────────────────────

def remove_plugin_file(path: str | Path, backup: bool = True) -> dict:
    """Usuwa (lub przenosi do `.bak`) plugin."""
    p = Path(path).resolve()
    result = {
        "ok": False,
        "error": None,
        "path": str(p),
        "backup_path": None,
        "removed": False,
    }

    if not p.is_file():
        result["error"] = f"plik nie istnieje: {p}"
        return result

    try:
        if backup:
            ts = datetime.now().strftime("%Y-%m-%d_%H%M")
            backup_path = p.with_name(f"{p.name}.{ts}.bak")
            shutil.move(str(p), str(backup_path))
            result["backup_path"] = str(backup_path)
        else:
            p.unlink()
    except OSError as e:
        result["error"] = f"nie można usunąć {p}: {e}"
        return result

    result.update(ok=True, removed=True)
    return result


# ── v3.1: update_replacement_in_plugin ──────────────────────────

def update_replacement_in_plugin(
    path: str | Path,
    ch: str,
    *,
    rec: str | None = None,
    alt: list[str] | None = None,
    why: str | None = None,
    append_alt: bool = False,
) -> dict:
    """
    Aktualizuje istniejący wpis zamiennika w pluginie .json.

    Parametry:
        path:        ścieżka do pliku .json,
        ch:          klucz (znak bazowy; klaster normalizowany),
        rec:         nowy rec (None → zachowaj stary),
        alt:         nowe alt (None → zachowaj stare),
                     append_alt=True  → dopisz do alt (z dedupe),
                     append_alt=False → zastąp alt,
        why:         nowy why (None → zachowaj stary).

    Zwraca dict:
        {
          "ok": bool, "changed": bool, "error": str | None,
          "path": str, "ch": str,
          "old": {"rec": str, "alt": list, "why": str},
          "new": {"rec": str, "alt": list, "why": str},
          "was_modified": bool,
        }

    Zasady:
      * tylko .json — .py odrzucane (spójne z add_*),
      * klucz MUSI istnieć; nowy wpis → `add_replacement_to_plugin`,
      * dedupe w `alt`: ten sam string nie pojawi się dwa razy,
      * wartość równa kluczowi jest odrzucana (nie ma sensu `ch → ch`),
      * `changed=False` gdy nic się nie zmieniło (te same wartości).
    """
    base, error = _normalize_base_ch(ch)
    result = {
        "ok": False,
        "changed": False,
        "error": None,
        "path": str(Path(path).resolve()),
        "ch": base or ch,
        "old": {},
        "new": {},
        "was_modified": bool(base and ch != base),
    }

    if base is None:
        result["error"] = _reason_for_error(error)
        return result

    p = Path(path).resolve()
    fmt = _FORMAT_PY if p.suffix.lower() == ".py" else _FORMAT_JSON

    if fmt == _FORMAT_PY:
        result["error"] = (
            f"{p.name} to plugin .py — otwórz w edytorze i zmień "
            f"REPLACEMENTS[{base!r}] ręcznie"
        )
        return result

    if not p.is_file():
        result["error"] = f"plik nie istnieje: {p}"
        return result

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        result["error"] = f"nie można wczytać {p.name}: {e}"
        return result

    reps = raw.get("replacements")
    if not isinstance(reps, dict):
        result["error"] = f"{p.name}: brak pola 'replacements' lub nie jest obiektem"
        return result

    if base not in reps:
        result["error"] = (
            f"{base!r} nie istnieje w {p.name} — "
            f"użyj add_replacement_to_plugin, żeby dodać nowy"
        )
        return result

    old = reps[base]
    if not isinstance(old, dict):
        result["error"] = f"{base!r} w {p.name}: wpis nie jest obiektem"
        return result

    old_rec = str(old.get("rec") or "")
    old_alt = [str(a) for a in (old.get("alt") or [])]
    old_why = str(old.get("why") or "")
    result["old"] = {"rec": old_rec, "alt": list(old_alt), "why": old_why}

    new_rec = old_rec if rec is None else str(rec).strip()
    new_why = old_why if why is None else str(why).strip()

    if not new_rec:
        result["error"] = "rec nie może być pusty"
        return result

    if alt is None:
        new_alt = list(old_alt)
    else:
        cleaned = [str(a).strip() for a in alt if str(a).strip()]
        if append_alt:
            new_alt = list(old_alt)
            for a in cleaned:
                if a and a != base and a != new_rec and a not in new_alt:
                    new_alt.append(a)
        else:
            new_alt = []
            for a in cleaned:
                if a and a != base and a != new_rec and a not in new_alt:
                    new_alt.append(a)

    changed = (
        new_rec != old_rec
        or new_why != old_why
        or new_alt != old_alt
    )

    result["new"] = {"rec": new_rec, "alt": list(new_alt), "why": new_why}

    if not changed:
        result.update(ok=True, changed=False)
        return result

    reps[base] = {"rec": new_rec, "alt": new_alt, "why": new_why}

    try:
        p.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        result["error"] = f"nie można zapisać {p}: {e}"
        return result

    result.update(ok=True, changed=True)
    return result


__all__ = [
    # v1.0
    "DEFAULT_PREFIX",
    "DEFAULT_VERSION",
    "create_detection_plugin",
    "create_replacement_plugin",
    "list_plugins",
    "validate_plugins",
    "inspect_plugin",
    # v2.0
    "guess_category",
    "find_emoji_entries",
    "find_replacement_entries",
    "add_emoji_to_plugin",
    "add_replacement_to_plugin",
    "remove_plugin_file",
    # v3.0
    "find_plugins_with_set",
    "update_replacement_in_plugin",
]
