import sys
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

# Дозволяє запускати файл напряму (не лише через pytest): додаємо src/ до шляху імпорту
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from core.formatting import (
    format_duration,
    format_library_track_details,
    format_track_details,
    render_playlist_lines,
)
from core.functional import (
    combine_predicates,
    compose,
    filter_by,
    make_weight_scorer,
    pipe,
    sort_by_key,
)
from core.graph import (
    collect_reachable_artists_recursive,
    explain_recommendation_chain,
    find_recommendation_chain_recursive,
)
from core.playlist import (
    avoid_adjacent_repeats,
    calculate_total_duration,
    calculate_track_weight,
    fill_budget,
    generate_playlist_data,
)
from core.types import (
    ArtistNode,
    LibraryTrackData,
    PlaylistData,
    RecommendationPath,
    TrackData,
)

TODAY = date(2026, 10, 20)


# ============================================================================
# 1. Тести незмінності даних (@dataclass(frozen=True))
# ============================================================================

def test_track_data_immutability():
    """Перевірка незмінності об'єкта TrackData: спроба мутації викликає FrozenInstanceError."""
    track = TrackData(title="Song 2", artist="Blur", duration_sec=122, genre="rock")
    with pytest.raises(FrozenInstanceError):
        track.title = "Another Title"  # type: ignore
    with pytest.raises(FrozenInstanceError):
        track.duration_sec = 200  # type: ignore


def test_library_track_data_immutability():
    """Перевірка незмінності об'єкта LibraryTrackData."""
    track = LibraryTrackData(
        title="Feel Good Inc.",
        artist="Gorillaz",
        duration_sec=222,
        genre="alternative",
        mood="енергійний",
        rating=5,
        last_played=TODAY,
    )
    with pytest.raises(FrozenInstanceError):
        track.rating = 4  # type: ignore
    with pytest.raises(FrozenInstanceError):
        track.mood = "спокійний"  # type: ignore


def test_playlist_data_immutability():
    """Перевірка незмінності об'єкта PlaylistData."""
    track = TrackData("A", "B", 180)
    pl = PlaylistData(name="Test", tracks=(track,))
    assert pl.total_duration == 180
    with pytest.raises(FrozenInstanceError):
        pl.name = "New Name"  # type: ignore


# ============================================================================
# 2. Тести чистих функцій форматування
# ============================================================================

def test_format_duration_edge_cases():
    """Форматування тривалості: нуль, від'ємні значення, вирівнювання секунд."""
    assert format_duration(0) == "0:00"
    assert format_duration(-10) == "0:00"
    assert format_duration(65) == "1:05"
    assert format_duration(600) == "10:00"


def test_format_track_and_library_details():
    """Чисті функції форматування деталей аудіотреку та треку бібліотеки."""
    track_str = format_track_details("Song 2", "Blur", 122)
    assert track_str == "'Song 2' — Blur (2:02)"

    lib_str = format_library_track_details("Song 2", "Blur", 122, "britpop", "енергійний", 4)
    assert lib_str == "'Song 2' — Blur (2:02) | Жанр: britpop, Настрій: 'енергійний', Оцінка: 4/5"


def test_render_playlist_lines_purity():
    """render_playlist_lines повертає детермінований рядок без print та побічних ефектів."""
    details = ("'A' — X (1:00)", "'B' — Y (2:00)")
    res1 = render_playlist_lines("Mix", details)
    res2 = render_playlist_lines("Mix", details)
    assert res1 == res2
    assert "=== Плейлист: Mix ===" in res1
    assert "1. 'A' — X (1:00)" in res1
    assert "2. 'B' — Y (2:00)" in res1


# ============================================================================
# 3. Тести функцій вищого порядку та композиції
# ============================================================================

def test_compose_higher_order_function():
    """compose виконує математичну композицію функцій справа наліво: f(g(h(x)))."""
    add_one = lambda x: x + 1
    double = lambda x: x * 2
    square = lambda x: x ** 2

    # square -> double -> add_one: ((3^2) * 2) + 1 = 18 + 1 = 19
    pipeline = compose(add_one, double, square)
    assert pipeline(3) == 19

    # Порожня композиція є функцією ідентичності
    identity = compose()
    assert identity(42) == 42


def test_pipe_higher_order_function():
    """pipe передає значення по ланцюжку трансформацій зліва направо."""
    increment = lambda x: x + 10
    stringify = lambda x: f"Result: {x}"
    to_upper = lambda s: s.upper()

    res = pipe(5, increment, stringify, to_upper)
    assert res == "RESULT: 15"


def test_combine_predicates_higher_order_function():
    """combine_predicates об'єднує декілька чистих предикатів логічним AND."""
    is_even = lambda x: x % 2 == 0
    is_positive = lambda x: x > 0
    is_under_ten = lambda x: x < 10

    valid_number = combine_predicates(is_even, is_positive, is_under_ten)
    assert valid_number(4) is True
    assert valid_number(12) is False   # not under ten
    assert valid_number(-2) is False   # not positive
    assert valid_number(5) is False    # not even


def test_make_weight_scorer_closure():
    """make_weight_scorer створює функцію оцінки з замкненими параметрами (дата, cap)."""
    scorer = make_weight_scorer(TODAY, recency_cap_days=30)
    track_played_today = LibraryTrackData("A", "X", 100, rating=4, last_played=TODAY)
    track_played_month_ago = LibraryTrackData("B", "Y", 100, rating=4, last_played=date(2026, 9, 20))

    # Трек, який давно не слухали, повинен отримати більшу вагу
    assert scorer(track_played_month_ago) > scorer(track_played_today)
    assert scorer(track_played_today) == pytest.approx(4.0)
    assert scorer(track_played_month_ago) == pytest.approx(8.0)


def test_filter_by_and_sort_by_key_higher_order():
    """filter_by та sort_by_key повертають незмінні кортежі та не мутують вхідні списки."""
    items = (5, 2, 8, 1, 9)
    get_evens = filter_by(lambda x: x % 2 == 0)
    assert get_evens(items) == (2, 8)

    sorter = sort_by_key(lambda x: x)
    assert sorter(items) == (1, 2, 5, 8, 9)
    assert items == (5, 2, 8, 1, 9)  # оригінал незмінний


# ============================================================================
# 4. Тести чистих обчислень плейлистів та граничних випадків бюджету
# ============================================================================

def test_calculate_total_duration_pure():
    """Розрахунок сумарної тривалості: порожній список дає 0, треки сумуються."""
    assert calculate_total_duration([]) == 0
    tracks = (TrackData("A", "X", 100), TrackData("B", "Y", 150))
    assert calculate_total_duration(tracks) == 250


def test_fill_budget_boundary_cases():
    """Граничні випадки бюджету часу: нульовий бюджет, від'ємний бюджет, пропуск завеликих треків."""
    tracks = (
        TrackData("Short", "A", 60),
        TrackData("Medium", "B", 120),
        TrackData("Long", "C", 300),
    )
    # Нульовий та від'ємний бюджет повертають порожній кортеж
    assert fill_budget(tracks, 0) == ()
    assert fill_budget(tracks, -50) == ()

    # Точне вміщення
    assert fill_budget(tracks, 60) == (tracks[0],)
    assert fill_budget(tracks, 180) == (tracks[0], tracks[1])

    # Якщо наступний трек не влазить, він пропускається, але загальний бюджет не перевищується
    assert fill_budget(tracks, 100) == (tracks[0],)
    total = calculate_total_duration(fill_budget(tracks, 250))
    assert total <= 250


def test_avoid_adjacent_repeats_pure():
    """Чиста перестановка треків для уникнення однакових виконавців поспіль."""
    t1 = TrackData("1", "Blur", 100)
    t2 = TrackData("2", "Blur", 100)
    t3 = TrackData("3", "Gorillaz", 100)
    res = avoid_adjacent_repeats((t1, t2, t3))
    artists = [t.artist for t in res]
    assert artists == ["Blur", "Gorillaz", "Blur"]


# ============================================================================
# 5. Тести рекурсивних алгоритмів на графі схожості та обробка циклів
# ============================================================================

def test_recursive_recommendation_chain_direct():
    """Рекурсивний пошук знаходить прямий зв'язок (глибина 1)."""
    graph = {"Blur": ("Gorillaz", "Oasis"), "Gorillaz": ("Pulp",)}
    path = find_recommendation_chain_recursive(graph, "Blur", "Gorillaz")
    assert path == ("Blur", "Gorillaz")


def test_recursive_recommendation_chain_multi_hop():
    """Рекурсивний пошук знаходить ланцюжок через проміжних виконавців."""
    graph = {
        "Blur": ("Gorillaz",),
        "Gorillaz": ("Pulp",),
        "Pulp": ("Suede",),
    }
    path = find_recommendation_chain_recursive(graph, "Blur", "Pulp")
    assert path == ("Blur", "Gorillaz", "Pulp")

    # Пояснення
    assert explain_recommendation_chain(path) == "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp"


def test_recursive_recommendation_chain_cycle_handling():
    """Обробка циклів у графі: рекурсія не зациклюється при наявності взаємних посилань (A <-> B)."""
    cyclic_graph = {
        "A": ("B",),
        "B": ("A", "C"),  # цикл A <-> B
        "C": ("D",),
        "D": ("B",),       # цикл на B
    }
    path = find_recommendation_chain_recursive(cyclic_graph, "A", "D")
    assert path == ("A", "B", "C", "D")


def test_recursive_recommendation_chain_respects_banned():
    """Рекурсивний пошук обходить або відхиляє ланцюжки з забороненими виконавцями."""
    graph = {
        "Blur": ("Gorillaz", "Oasis"),
        "Gorillaz": ("Pulp",),
        "Oasis": ("Pulp",),
    }
    # Якщо Gorillaz заборонений, алгоритм рекурсивно знаходить альтернативний маршрут через Oasis
    path = find_recommendation_chain_recursive(graph, "Blur", "Pulp", banned=frozenset(["gorillaz"]))
    assert path == ("Blur", "Oasis", "Pulp")

    # Якщо і Gorillaz, і Oasis заборонені — шляху немає
    blocked = find_recommendation_chain_recursive(graph, "Blur", "Pulp", banned=frozenset(["gorillaz", "oasis"]))
    assert blocked is None


def test_recursive_recommendation_chain_max_depth_exceeded():
    """Якщо шлях довший за max_depth, функція чисто повертає None."""
    chain_graph = {
        "1": ("2",),
        "2": ("3",),
        "3": ("4",),
        "4": ("5",),
    }
    # Від 1 до 5 це 4 переходи (5 вершин)
    assert find_recommendation_chain_recursive(chain_graph, "1", "5", max_depth=3) is None
    assert find_recommendation_chain_recursive(chain_graph, "1", "5", max_depth=4) == ("1", "2", "3", "4", "5")


def test_collect_reachable_artists_recursive():
    """Рекурсивне накопичення досяжних вершин у графі схожості."""
    graph = {
        "Seed": ("A", "B"),
        "A": ("C",),
        "B": ("D",),
        "D": ("Seed",),  # цикл
    }
    reachable = dict(collect_reachable_artists_recursive(graph, "Seed", max_depth=2))
    assert "A" in reachable and "B" in reachable and "C" in reachable and "D" in reachable
    assert reachable["C"] == ("Seed", "A", "C")


# ============================================================================
# 6. Тест повноцінного чистого конвеєра генерації
# ============================================================================

def test_generate_playlist_data_pipeline_end_to_end():
    """Повний наскрізний тест чистого функціонального конвеєра generate_playlist_data."""
    library = [
        LibraryTrackData("Track 1", "Blur", 180, mood="енергійний", rating=5, last_played=date(2026, 9, 1)),
        LibraryTrackData("Track 2", "Blur", 200, mood="спокійний", rating=4, last_played=date(2026, 9, 10)),
        LibraryTrackData("Track 3", "Gorillaz", 240, mood="енергійний", rating=3, last_played=date(2026, 10, 15)),
        LibraryTrackData("Track 4", "Banned", 180, mood="енергійний", rating=5, last_played=date(2026, 9, 1)),
    ]
    discoveries = [
        TrackData("Disc 1", "Pulp", 180),
        TrackData("Disc 2", "Banned", 200),
        TrackData("Disc 3", "Blur", 150),  # Вже в бібліотеці (не новий)
    ]

    result = generate_playlist_data(
        library=library,
        discoveries=discoveries,
        duration_min=10,
        mood="енергійний",
        new_percent=30,
        banned_artists=["Banned"],
        today=TODAY,
        name="Чистий мікс",
    )

    assert isinstance(result, PlaylistData)
    assert result.name == "Чистий мікс"
    assert 0 < result.total_duration <= 600

    artists = [t.artist for t in result.tracks]
    assert "Banned" not in artists
    # Disc 1 (Pulp) має бути додано як відкриття
    assert "Pulp" in artists
    # Усі треки з бібліотеки мають відповідати обраному настрою
    for t in result.tracks:
        if isinstance(t, LibraryTrackData):
            assert t.mood == "енергійний"

