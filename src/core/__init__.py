"""Функціональне ядро Куратора плейлистів (Playlist Curator Core).

Ядро реалізовано згідно з принципами функціонального програмування:
- Чисті функції: без побічних ефектів, без введення-виведення (print, input, файли, мережа)
  та без змінного глобального стану.
- Незмінні структури даних: @dataclass(frozen=True) та незмінні кортежі (Tuple).
- Функції вищого порядку (compose, pipe, combine_predicates, make_weight_scorer).
- Рекурсивна обробка графа схожості виконавців (find_recommendation_chain_recursive).
"""

from .formatting import (
    format_duration,
    format_library_track_details,
    format_track_details,
    render_playlist_lines,
)
from .functional import (
    SupportsLt,
    combine_predicates,
    compose,
    filter_by,
    make_weight_scorer,
    pipe,
    sort_by_key,
)
from .graph import (
    collect_reachable_artists_recursive,
    explain_recommendation_chain,
    find_recommendation_chain_recursive,
)
from .playlist import (
    avoid_adjacent_repeats,
    calculate_total_duration,
    calculate_track_weight,
    fill_budget,
    generate_playlist_data,
)
from .types import (
    ArtistNode,
    LibraryTrackData,
    PlaylistData,
    RecommendationPath,
    TrackData,
    TrackProtocol,
)

__all__ = [
    # Незмінні моделі та протоколи
    "TrackProtocol",
    "SupportsLt",
    "TrackData",
    "LibraryTrackData",
    "PlaylistData",
    "ArtistNode",
    "RecommendationPath",
    # Форматування
    "format_duration",
    "format_track_details",
    "format_library_track_details",
    "render_playlist_lines",
    # Функціональні утиліти
    "compose",
    "pipe",
    "combine_predicates",
    "filter_by",
    "sort_by_key",
    "make_weight_scorer",
    # Графові рекурсивні алгоритми
    "find_recommendation_chain_recursive",
    "collect_reachable_artists_recursive",
    "explain_recommendation_chain",
    # Обчислення плейлистів
    "calculate_total_duration",
    "calculate_track_weight",
    "fill_budget",
    "avoid_adjacent_repeats",
    "generate_playlist_data",
]
