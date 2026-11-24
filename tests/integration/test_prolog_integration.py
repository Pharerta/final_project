import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from generator import PlaylistGenerator
from logic.prolog_engine import PrologEngine
from models import AudioTrack, LibraryTrack

PROLOG_READY = PrologEngine.is_available()
skip_if_no_prolog = pytest.mark.skipif(
    not PROLOG_READY,
    reason="SWI-Prolog і/або pyswip не встановлено в поточному середовищі",
)

TODAY = date(2026, 10, 20)


@skip_if_no_prolog
def test_real_prolog_similarity_chain_cycles_and_banned():
    engine = PrologEngine()
    graph = {
        "Blur": ["Gorillaz", "Blur"],  # цикл на себе
        "Gorillaz": ["Blur", "Pulp", "Banned Band"],  # зворотний цикл + заборонений
        "Banned Band": ["Suede"],  # заблоковано через забороненого посередника
        "Pulp": ["D1"],
        "D1": ["D2"],  # глибина 4 (Blur -> Gorillaz -> Pulp -> D1 -> D2) > max_steps=3
    }

    paths = engine.find_recommendations(
        favorites=["Blur"],
        similarity_graph=graph,
        banned_artists=["banned band"],
        max_steps=3,
    )

    assert paths["gorillaz"] == ("Blur", "Gorillaz")
    assert paths["pulp"] == ("Blur", "Gorillaz", "Pulp")
    assert "suede" not in paths
    assert "banned band" not in paths
    assert "d2" not in paths


@skip_if_no_prolog
def test_real_prolog_linear_adjacency_and_mood_transitions():
    engine = PrologEngine()
    tracks = [
        LibraryTrack("T1", "Blur", 180, "rock", "енергійний", 5, TODAY),
        LibraryTrack("T2", "Blur", 180, "rock", "веселий", 4, TODAY),
        AudioTrack("Common People", "Pulp", 200),
    ]

    ordered_indices, is_valid = engine.arrange_tracks(
        tracks=tracks,
        banned_artists=[],
        favorite_artists=["Blur"],
    )

    assert is_valid is True
    ordered_artists = [tracks[i].artist for i in ordered_indices]
    assert ordered_artists == ["Blur", "Pulp", "Blur"]


@skip_if_no_prolog
def test_real_prolog_end_to_end_three_paradigms():
    library = [
        LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 5, TODAY),
        LibraryTrack("Parklife", "Blur", 185, "britpop", "енергійний", 4, TODAY),
    ]
    discoveries = [
        AudioTrack("Common People", "Pulp", 240),
        AudioTrack("Trash", "Suede", 240),
    ]
    graph = {
        "Blur": ["Gorillaz", "Banned Band"],
        "Gorillaz": ["Pulp"],
        "Banned Band": ["Suede"],
    }

    gen = PlaylistGenerator(
        library,
        discoveries,
        banned_artists=["Banned Band"],
        similarity_graph=graph,
    )
    playlist = gen.generate(duration_min=10, mood="енергійний", new_percent=50, today=TODAY)

    artists = [t.artist for t in playlist.tracks]
    assert "Blur" in artists
    assert "Pulp" in artists
    assert "Suede" not in artists
    assert all(a != b for a, b in zip(artists, artists[1:]))
    assert playlist.get_explanation("Pulp") == "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp"
    assert gen.last_prolog_plan is not None
    assert gen.last_prolog_plan.is_sequence_valid is True
