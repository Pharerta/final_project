"""Логічна парадигма (Prolog) для Куратора плейлистів."""

from logic.prolog_engine import (
    PrologEngine,
    PrologPlaylistPlan,
    PrologUnavailableError,
    prolog_atom,
)

__all__ = [
    "PrologEngine",
    "PrologPlaylistPlan",
    "PrologUnavailableError",
    "prolog_atom",
]
