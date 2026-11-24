"""Міст між Python та SWI-Prolog через бібліотеку pyswip (Етап 4).

Відповідає за передачу фактів предметної області в базу знань Prolog
(`playlist_rules.pl`) та отримання логічних висновків:
1. Пошук ланцюжків схожості нових виконавців (<= 3 кроки, без циклів і заборонених).
2. Упорядкування та валідація послідовності треків (лінійне сусідство без повтору
   одного виконавця підряд і з плавними переходами настрою).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.graph import explain_recommendation_chain

RULES_FILE = Path(__file__).resolve().with_name("playlist_rules.pl")


class PrologUnavailableError(RuntimeError):
    """Помилка ініціалізації SWI-Prolog або pyswip."""


def ensure_swipl_in_path() -> Optional[str]:
    """Перевіряє наявність swipl у PATH; додає типові шляхи встановлення для Windows і macOS/Linux."""
    existing = shutil.which("swipl")
    if existing:
        return existing

    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "swipl" / "bin",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "swipl" / "bin",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "swipl" / "bin",
        ]
        exe_name = "swipl.exe"
    else:
        candidates = [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin"),
        ]
        exe_name = "swipl"

    for bin_dir in candidates:
        exe = bin_dir / exe_name
        if exe.is_file():
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            if os.name == "nt" and hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(bin_dir))
                except OSError:
                    pass
            return str(exe)
    return None


def prolog_atom(value: str) -> str:
    """Безпечно форматує рядок як Prolog-атом у одинарних лапках."""
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _decode_term(value: Any) -> str:
    """Конвертує атом або байтовий терм pyswip у Python str."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "value"):
        inner = value.value
        return inner.decode("utf-8", errors="replace") if isinstance(inner, bytes) else str(inner)
    return str(value)


def _canonical_artist_map(names: Iterable[str]) -> Dict[str, str]:
    """Будує словник {casefold_імені: канонічне_імя} для узгодженого матчингу в Prolog."""
    mapping: Dict[str, str] = {}
    for raw in names:
        clean = str(raw).strip()
        if not clean:
            continue
        key = clean.casefold()
        if key not in mapping:
            mapping[key] = clean
    return mapping


@dataclass(frozen=True)
class PrologPlaylistPlan:
    """Незмінний результат логічного виведення Prolog для плейлиста."""

    ordered_indices: Tuple[int, ...]
    is_sequence_valid: bool
    discovery_paths: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    explanations: Mapping[str, str] = field(default_factory=dict)
    facts_count: int = 0


class PrologEngine:
    """Обгортка над SWI-Prolog (pyswip) для запитів генератора плейлистів."""

    _consulted: bool = False

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = Path(rules_path) if rules_path else RULES_FILE
        self._prolog_cls: Any = None

    @classmethod
    def is_available(cls) -> bool:
        """Повертає True, якщо SWI-Prolog і pyswip доступні для запуску."""
        if ensure_swipl_in_path() is None:
            return False
        try:
            from pyswip import Prolog  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_loaded(self) -> Any:
        """Ліниво ініціалізує SWI-Prolog та завантажує базу знань playlist_rules.pl."""
        if not self.rules_path.is_file():
            raise FileNotFoundError(f"Не знайдено файл правил Prolog: {self.rules_path}")

        if ensure_swipl_in_path() is None:
            raise PrologUnavailableError(
                "SWI-Prolog (swipl) не знайдено в системі. "
                "Встановіть SWI-Prolog (на Windows: winget install SWI-Prolog.SWI-Prolog) "
                "та додайте його теку bin до PATH (див. README.md)."
            )

        try:
            from pyswip import Prolog
        except Exception as exc:
            raise PrologUnavailableError(
                "Не вдалося завантажити бібліотеку pyswip або ініціалізувати SWI-Prolog. "
                "Виконайте `pip install -r requirements.txt` та переконайтесь, що swipl доступний у PATH "
                f"(деталі: {exc})."
            ) from exc

        self._prolog_cls = Prolog
        if not PrologEngine._consulted:
            Prolog.consult(self.rules_path.as_posix())
            PrologEngine._consulted = True
        return Prolog

    def _clear_dynamic_facts(self, prolog: Any) -> None:
        """Очищає динамічні факти між запитами, щоб стани не змішувались."""
        list(
            prolog.query(
                "retractall(favorite_artist(_)), "
                "retractall(similar(_, _)), "
                "retractall(banned(_)), "
                "retractall(track_info(_, _, _, _))"
            )
        )

    def find_recommendations(
        self,
        favorites: Iterable[str],
        similarity_graph: Mapping[str, Sequence[str]],
        banned_artists: Iterable[str] = (),
        max_steps: int = 3,
    ) -> Dict[str, Tuple[str, ...]]:
        """Запитує Prolog про ланцюжки схожості від улюблених до нових виконавців."""
        prolog = self._ensure_loaded()
        self._clear_dynamic_facts(prolog)

        all_names: List[str] = list(favorites)
        for src, targets in similarity_graph.items():
            all_names.append(src)
            all_names.extend(targets)
        all_names.extend(banned_artists)
        canon = _canonical_artist_map(all_names)

        for fav in favorites:
            key = str(fav).strip().casefold()
            if key in canon:
                prolog.assertz(f"favorite_artist({prolog_atom(canon[key])})")

        for src, targets in similarity_graph.items():
            src_key = str(src).strip().casefold()
            if src_key not in canon:
                continue
            for dst in targets:
                dst_key = str(dst).strip().casefold()
                if dst_key in canon:
                    prolog.assertz(
                        f"similar({prolog_atom(canon[src_key])}, {prolog_atom(canon[dst_key])})"
                    )

        for b in banned_artists:
            b_key = str(b).strip().casefold()
            if b_key in canon:
                prolog.assertz(f"banned({prolog_atom(canon[b_key])})")

        best_paths: Dict[str, Tuple[str, ...]] = {}
        for sol in list(prolog.query(f"recommend_discovery(Target, {int(max_steps)}, Path)")):
            target = _decode_term(sol["Target"])
            raw_path = sol["Path"]
            path = tuple(_decode_term(node) for node in raw_path)
            t_key = target.strip().casefold()
            if t_key not in best_paths or len(path) < len(best_paths[t_key]):
                best_paths[t_key] = path

        return best_paths

    def arrange_tracks(
        self,
        tracks: Sequence[Any],
        banned_artists: Iterable[str] = (),
        favorite_artists: Iterable[str] = (),
    ) -> Tuple[Tuple[int, ...], bool]:
        """Упорядковує треки через Prolog-предикат arrange_playlist/2 та перевіряє valid_track_sequence/1."""
        if not tracks:
            return (), True

        prolog = self._ensure_loaded()
        self._clear_dynamic_facts(prolog)

        track_artists = [getattr(t, "artist", "") for t in tracks]
        canon = _canonical_artist_map([*track_artists, *banned_artists, *favorite_artists])
        fav_keys = {str(f).strip().casefold() for f in favorite_artists}

        for b in banned_artists:
            b_key = str(b).strip().casefold()
            if b_key in canon:
                prolog.assertz(f"banned({prolog_atom(canon[b_key])})")

        track_ids: List[str] = []
        id_to_index: Dict[str, int] = {}
        for idx, track in enumerate(tracks):
            tid = f"t_{idx}"
            track_ids.append(tid)
            id_to_index[tid] = idx

            art_key = str(getattr(track, "artist", "")).strip().casefold()
            artist_name = canon.get(art_key, str(getattr(track, "artist", "")).strip())

            raw_mood = getattr(track, "mood", None)
            mood_val = raw_mood.value if hasattr(raw_mood, "value") else str(raw_mood or "unknown")
            mood_str = mood_val.strip().casefold() or "unknown"

            source = "library" if art_key in fav_keys else "discovery"
            prolog.assertz(
                f"track_info({tid}, {prolog_atom(artist_name)}, {prolog_atom(mood_str)}, {source})"
            )

        id_list_literal = "[" + ", ".join(track_ids) + "]"
        solutions = list(prolog.query(f"arrange_playlist({id_list_literal}, OrderedIds)", maxresult=1))
        if not solutions:
            return tuple(range(len(tracks))), False

        ordered_ids = [_decode_term(item) for item in solutions[0]["OrderedIds"]]
        ordered_indices = tuple(id_to_index[tid] for tid in ordered_ids if tid in id_to_index)

        ordered_literal = "[" + ", ".join(ordered_ids) + "]"
        is_valid = bool(list(prolog.query(f"valid_track_sequence({ordered_literal})", maxresult=1)))
        return ordered_indices, is_valid

    def evaluate_playlist(
        self,
        tracks: Sequence[Any],
        favorite_artists: Iterable[str],
        banned_artists: Iterable[str] = (),
        similarity_graph: Optional[Mapping[str, Sequence[str]]] = None,
        max_steps: int = 3,
    ) -> PrologPlaylistPlan:
        """Повний логічний етап для плейлиста: ланцюжки відкриттів + валідація сусідства."""
        favs = list(favorite_artists)
        banned = list(banned_artists)
        graph = similarity_graph or {}

        facts_count = (
            len(set(favs))
            + sum(len(v) for v in graph.values())
            + len(set(banned))
            + len(tracks)
        )

        discovery_paths: Dict[str, Tuple[str, ...]] = {}
        explanations: Dict[str, str] = {}
        if graph and favs:
            discovery_paths = self.find_recommendations(
                favorites=favs,
                similarity_graph=graph,
                banned_artists=banned,
                max_steps=max_steps,
            )
            explanations = {
                artist_key: explain_recommendation_chain(path)
                for artist_key, path in discovery_paths.items()
            }

        ordered_indices, is_valid = self.arrange_tracks(
            tracks=tracks,
            banned_artists=banned,
            favorite_artists=favs,
        )

        return PrologPlaylistPlan(
            ordered_indices=ordered_indices,
            is_sequence_valid=is_valid,
            discovery_paths=discovery_paths,
            explanations=explanations,
            facts_count=facts_count,
        )
