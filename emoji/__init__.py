#!/usr/bin/env python3

# emoji/__init__.py
# -*- coding: utf-8 -*-

"""
emoji — pakiet logiki skanera emoji.

Ten plik to punkt wejścia pakietu. Definiuje:
  * metadane (`__version__`, `__author__`),
  * tematyczne listy publicznych symboli (`__all_*__`),
  * złożoną z nich listę `__all__`,
  * re-eksport najważniejszych funkcji z podmodułów, żeby wygodnie
    korzystać z pakietu bez zaglądania do środka (`from emoji import scan`).

Podfoldery `wykrywanie/` i `zamienniki/` **nie są** podpakietami Pythona —
to foldery danych (pluginów), czytane przez `emoji.loader`. Dlatego nie
mają własnego `__init__.py`; dodanie go mogłoby przypadkiem spowodować,
że `import emoji.wykrywanie` zacznie działać i mylić użytkownika.

Struktura pakietu:

    emoji/
    ├── __init__.py        ← ten plik
    ├── loader.py          ← ładowanie pluginów .json/.py
    ├── detection.py       ← classify(), measure_*()
    ├── scanner.py         ← chodzenie po plikach + scan()
    ├── reporter.py        ← print_report(), print_summary()
    ├── generator.py       ← tworzenie nowych pluginów
    ├── wykrywanie/        ← dane: CO wykrywać (pluginy)
    └── zamienniki/        ← dane: CZYM zastępować (pluginy)

Podział `__all__` na tematy (`__all_detection__`, `__all_loader__`,
`__all_scanner__`, `__all_reporter__`) ułatwia rozszerzanie: gdy dodasz
nową funkcję do jednego modułu, dopisujesz ją tylko do jednej listy.
"""

__version__ = "0.1.0"
__author__ = "Winek87 & DeepSeek"

# ── importy z podmodułów ─────────────────────────────────────────
# Kolejność importów jest istotna: `detection` nie zna nikogo,
# `loader` nie zna `scanner`, `scanner` zna `detection`, `reporter`
# zna `detection`. Dzięki temu nie ma cykli.
from .detection import (  # noqa: F401
    HAS_WCWIDTH,
    classify,
    measure_both,
    measure_heuristic,
    measure_wcwidth,
)
from .loader import (  # noqa: F401
    DEFAULT_PLUGINS_ROOT,
    load_plugins,
    load_replacements,
)
from .reporter import (  # noqa: F401
    print_report,
    print_summary,
)
from .scanner import (  # noqa: F401
    collect_files,
    scan,
)

# ── tematyczne listy publicznego API ─────────────────────────────
# Każda lista = jeden podmoduł. Rozszerzasz jedną, nie ruszasz reszty.

__all_detection__ = [
    "classify",
    "measure_heuristic",
    "measure_wcwidth",
    "measure_both",
    "HAS_WCWIDTH",
]

__all_loader__ = [
    "load_plugins",
    "load_replacements",
    "DEFAULT_PLUGINS_ROOT",
]

__all_scanner__ = [
    "scan",
    "collect_files",
]

__all_reporter__ = [
    "print_report",
    "print_summary",
]


# ── publiczne API pakietu (złożone z list tematycznych) ──────────
__all__ = [
    "__version__",
    "__author__",
    *__all_detection__,
    *__all_loader__,
    *__all_scanner__,
    *__all_reporter__,
]
