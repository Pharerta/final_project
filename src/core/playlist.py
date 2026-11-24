"""Чисті алгоритми обчислення та генерації плейлистів."""

from datetime import date
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, TypeVar

from .functional import combine_predicates, make_weight_scorer
from .types import PlaylistData, TrackProtocol

TTrack = TypeVar("TTrack", bound=TrackProtocol)


def _default_artist_key(track: TrackProtocol) -> str:
    return track.artist


def calculate_total_duration(tracks: Iterable[TrackProtocol]) -> int:
    """Розраховує сумарну тривалість послідовності треків у секундах."""
    return sum(int(getattr(t, "duration_sec", 0)) for t in tracks)


def calculate_track_weight(track: TrackProtocol, today: date, recency_cap_days: int = 30) -> float:
    """Чиста функція розрахунку пріоритету треку за його оцінкою та часом з останнього прослуховування."""
    scorer = make_weight_scorer(today, recency_cap_days=recency_cap_days)
    return scorer(track)


def fill_budget(candidates: Sequence[TTrack], budget_sec: int) -> Tuple[TTrack, ...]:
    """Жадібно відбирає треки, що поміщаються в заданий бюджет часу.

    Повертає новий незмінний кортеж відібраних елементів.
    """
    if budget_sec <= 0:
        return ()

    chosen: List[TTrack] = []
    used_sec = 0

    for track in candidates:
        dur = int(getattr(track, "duration_sec", 0))
        if dur > 0 and used_sec + dur <= budget_sec:
            chosen.append(track)
            used_sec += dur

    return tuple(chosen)


def avoid_adjacent_repeats(
    tracks: Sequence[TTrack],
    artist_key: Optional[Callable[[TTrack], str]] = None,
) -> Tuple[TTrack, ...]:
    """Переставляє треки так, щоб один виконавець не звучав двічі поспіль (де це можливо).

    Повертає новий кортеж треків у валідованому порядку без зміни вхідної послідовності.
    """
    key_fn: Callable[[TTrack], str] = artist_key if artist_key is not None else _default_artist_key
    pending = list(tracks)
    result: List[TTrack] = []

    while pending:
        prev_artist = key_fn(result[-1]).strip().casefold() if result else None
        idx = next(
            (i for i, t in enumerate(pending) if key_fn(t).strip().casefold() != prev_artist),
            0,
        )
        result.append(pending.pop(idx))

    return tuple(result)


def generate_playlist_data(
    library: Sequence[TrackProtocol],
    discoveries: Sequence[TrackProtocol] = (),
    duration_min: int = 30,
    mood: Optional[str] = None,
    new_percent: int = 30,
    banned_artists: Iterable[str] = (),
    today: Optional[date] = None,
    name: str = "Smart Playlist",
) -> PlaylistData:
    """Головний функціональний конвеєр генерації плейлиста.

    Поєднує:
    - перевірку параметрів
    - функціональні предикати фільтрації заборонених виконавців та настрою
    - зважування кандидатів функцією вищого порядку
    - жадібний відбір у бюджет
    - перестановку проти повторів виконавців підряд

    Повертає незмінний об'єкт PlaylistData.
    """
    if duration_min <= 0:
        raise ValueError("Тривалість має бути додатною")
    if not 0 <= new_percent <= 100:
        raise ValueError("Відсоток нових виконавців має бути від 0 до 100")

    today_date = today or date.today()
    total_sec = duration_min * 60
    new_budget = total_sec * new_percent // 100

    banned_set = frozenset(b.strip().casefold() for b in banned_artists)
    known_artists = frozenset(getattr(t, "artist", "").strip().casefold() for t in library)

    # 1. Фільтрація нових відкриттів: чистий предикат
    def is_valid_discovery(t: TrackProtocol) -> bool:
        art = getattr(t, "artist", "").strip().casefold()
        return bool(art) and (art not in banned_set) and (art not in known_artists)

    new_candidates = tuple(t for t in discoveries if is_valid_discovery(t))
    new_tracks = fill_budget(new_candidates, new_budget)

    # 2. Фільтрація та зважування треків з бібліотеки
    wanted_mood_str = mood.strip().casefold() if mood is not None else None

    def is_not_banned(t: TrackProtocol) -> bool:
        art = getattr(t, "artist", "").strip().casefold()
        return art not in banned_set

    def matches_mood(t: TrackProtocol) -> bool:
        if wanted_mood_str is None:
            return True
        track_mood = getattr(t, "mood", None)
        if track_mood is None:
            return False
        mood_value = getattr(track_mood, "value", None)
        track_mood_str = str(mood_value) if mood_value is not None else str(track_mood)
        return track_mood_str.strip().casefold() == wanted_mood_str

    library_predicate = combine_predicates(is_not_banned, matches_mood)
    scorer = make_weight_scorer(today_date, recency_cap_days=30)

    filtered_library = [t for t in library if library_predicate(t)]
    sorted_library = sorted(filtered_library, key=scorer, reverse=True)

    remaining_budget = total_sec - calculate_total_duration(new_tracks)
    library_tracks = fill_budget(sorted_library, remaining_budget)

    # 3. Компонування та усунення сусідніх повторів виконавців
    combined_tracks: Tuple[TrackProtocol, ...] = avoid_adjacent_repeats(library_tracks + new_tracks)

    return PlaylistData(name=name, tracks=combined_tracks)
