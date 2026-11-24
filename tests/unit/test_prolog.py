import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from generator import PlaylistGenerator
from logic.prolog_engine import (
    RULES_FILE,
    PrologEngine,
    PrologPlaylistPlan,
    PrologUnavailableError,
    _canonical_artist_map,
    _decode_term,
    prolog_atom,
)
from models import AudioTrack, LibraryTrack, Playlist
from repl import ReplError, Session

TODAY = date(2026, 10, 20)


class _FakePrologBackend:
    """Фейковий бекенд pyswip для перевірки форматування фактів та запитів без SWI-Prolog."""

    def __init__(self, recommendation_results=None, arranged_ids=None, sequence_valid=True):
        self.asserted = []
        self.queries = []
        self._recommendation_results = recommendation_results or []
        self._arranged_ids = arranged_ids
        self._sequence_valid = sequence_valid

    def assertz(self, fact: str) -> None:
        self.asserted.append(fact)

    def query(self, goal: str, maxresult: int = -1):
        self.queries.append(goal)
        if goal.startswith("retractall"):
            return iter([])
        if goal.startswith("recommend_discovery"):
            return iter(self._recommendation_results)
        if goal.startswith("arrange_playlist"):
            ids = self._arranged_ids if self._arranged_ids is not None else []
            return iter([{"OrderedIds": ids}])
        if goal.startswith("valid_track_sequence"):
            return iter([{}] if self._sequence_valid else [])
        return iter([])


def test_rules_file_exists_and_declares_expected_predicates():
    assert RULES_FILE.is_file()
    content = RULES_FILE.read_text(encoding="utf-8")
    for pred in (
        "favorite_artist/1",
        "similar/2",
        "banned/1",
        "track_info/4",
        "recommend_discovery(",
        "arrange_playlist(",
        "valid_track_sequence(",
    ):
        assert pred in content


def test_prolog_atom_escapes_quotes_and_backslashes():
    assert prolog_atom("Blur") == "'Blur'"
    assert prolog_atom("Guns N' Roses") == "'Guns N'' Roses'"
    assert prolog_atom(r"A\B") == r"'A\\B'"
    assert prolog_atom("енергійний") == "'енергійний'"


def test_decode_term_and_canonical_map():
    assert _decode_term(b"Pulp") == "Pulp"
    assert _decode_term("енергійний") == "енергійний"
    canon = _canonical_artist_map(["Blur", "blur", "  Pulp "])
    assert canon == {"blur": "Blur", "pulp": "Pulp"}


def test_prolog_engine_raises_helpful_error_when_swipl_missing(monkeypatch):
    monkeypatch.setattr("logic.prolog_engine.ensure_swipl_in_path", lambda: None)
    engine = PrologEngine()
    assert PrologEngine.is_available() is False
    with pytest.raises(PrologUnavailableError, match="SWI-Prolog"):
        engine.find_recommendations(["Blur"], {"Blur": ["Pulp"]})


def test_prolog_engine_asserts_facts_and_extracts_shortest_path(monkeypatch):
    fake_backend = _FakePrologBackend(
        recommendation_results=[
            {"Target": "Pulp", "Path": ["Blur", "Gorillaz", "Oasis", "Pulp"]},
            {"Target": "Pulp", "Path": ["Blur", "Gorillaz", "Pulp"]},
        ]
    )
    engine = PrologEngine()
    monkeypatch.setattr(engine, "_ensure_loaded", lambda: fake_backend)

    paths = engine.find_recommendations(
        favorites=["Blur"],
        similarity_graph={"Blur": ["Gorillaz"], "Gorillaz": ["Pulp", "Bad"]},
        banned_artists=["bad"],
        max_steps=3,
    )

    assert "favorite_artist('Blur')" in fake_backend.asserted
    assert "similar('Blur', 'Gorillaz')" in fake_backend.asserted
    assert "similar('Gorillaz', 'Pulp')" in fake_backend.asserted
    assert "banned('Bad')" in fake_backend.asserted
    assert paths == {"pulp": ("Blur", "Gorillaz", "Pulp")}
    assert any(q.startswith("retractall") for q in fake_backend.queries)


def test_prolog_engine_arrange_tracks_maps_indices(monkeypatch):
    tracks = [
        LibraryTrack("T1", "Blur", 180, "rock", "енергійний", 5, TODAY),
        LibraryTrack("T2", "Blur", 180, "rock", "енергійний", 4, TODAY),
        AudioTrack("Common People", "Pulp", 200),
    ]
    fake_backend = _FakePrologBackend(arranged_ids=["t_0", "t_2", "t_1"], sequence_valid=True)
    engine = PrologEngine()
    monkeypatch.setattr(engine, "_ensure_loaded", lambda: fake_backend)

    ordered_indices, is_valid = engine.arrange_tracks(
        tracks=tracks,
        banned_artists=[],
        favorite_artists=["Blur"],
    )

    assert ordered_indices == (0, 2, 1)
    assert is_valid is True
    assert "track_info(t_0, 'Blur', 'енергійний', library)" in fake_backend.asserted
    assert "track_info(t_2, 'Pulp', 'unknown', discovery)" in fake_backend.asserted


def test_playlist_renders_prolog_explanations():
    pl = Playlist("Мікс")
    pl.add_track(LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 5, TODAY))
    pl.add_track(AudioTrack("Common People", "Pulp", 350))
    pl.set_explanation("Pulp", "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp")

    rendered = pl.render()
    assert "-> Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp" in rendered
    assert "Song 2" in rendered


def test_generator_integrates_prolog_paths_and_explanations(prolog_unit_fallback):
    library = [
        LibraryTrack("Song 2", "Blur", 180, "britpop", "енергійний", 5, TODAY),
    ]
    discoveries = [
        AudioTrack("Common People", "Pulp", 180),
        AudioTrack("Trash", "Suede", 180),  # шлях йде через Banned Band
    ]
    similarity_graph = {
        "Blur": ["Gorillaz", "Banned Band"],
        "Gorillaz": ["Pulp"],
        "Banned Band": ["Suede"],
    }
    gen = PlaylistGenerator(
        library,
        discoveries,
        banned_artists=["Banned Band"],
        similarity_graph=similarity_graph,
    )

    playlist = gen.generate(duration_min=10, mood="енергійний", new_percent=50, today=TODAY)
    artists_in_pl = [t.artist for t in playlist.tracks]

    assert "Pulp" in artists_in_pl
    assert "Suede" not in artists_in_pl
    assert playlist.get_explanation("Pulp") == "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp"
    assert isinstance(gen.last_prolog_plan, PrologPlaylistPlan)
    assert gen.last_prolog_plan.is_sequence_valid is True


def test_repl_relate_and_prolog_error_handling(monkeypatch):
    session = Session()
    res = session.execute("relate Blur Gorillaz")
    assert "Blur -> Gorillaz" in res
    assert session.similarity_graph == {"Blur": ["Gorillaz"]}

    with pytest.raises(ReplError, match="сам на себе"):
        session.execute("relate Blur blur")

    session.library.append(LibraryTrack("Song 2", "Blur", 180, "rock", "енергійний", 5, TODAY))

    def raise_missing(*args, **kwargs):
        raise PrologUnavailableError("SWI-Prolog відсутній")

    monkeypatch.setattr(PrologEngine, "find_recommendations", raise_missing)
    monkeypatch.setattr(PrologEngine, "arrange_tracks", raise_missing)
    with pytest.raises(ReplError, match="SWI-Prolog відсутній"):
        session.execute("generate --minutes 5 --new-percent 0")

    session.execute("clear")
    assert session.similarity_graph == {}
