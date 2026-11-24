import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from core.graph import collect_reachable_artists_recursive
from core.playlist import avoid_adjacent_repeats
from logic.prolog_engine import PrologEngine


@pytest.fixture
def prolog_unit_fallback(monkeypatch):
    """Якщо SWI-Prolog не встановлено, підставляє детермінований стаб для ізольованих unit-тестів."""
    if PrologEngine.is_available():
        return

    def fake_find_recommendations(self, favorites, similarity_graph, banned_artists=(), max_steps=3):
        banned_set = frozenset(b.strip().casefold() for b in banned_artists)
        fav_keys = {f.strip().casefold() for f in favorites}
        best = {}
        for fav in favorites:
            for target, path in collect_reachable_artists_recursive(
                similarity_graph, fav, banned=banned_set, max_depth=max_steps
            ):
                t_key = target.strip().casefold()
                if t_key in fav_keys:
                    continue
                if t_key not in best or len(path) < len(best[t_key]):
                    best[t_key] = path
        return best

    def fake_arrange_tracks(self, tracks, banned_artists=(), favorite_artists=()):
        if not tracks:
            return (), True
        indexed = list(enumerate(tracks))
        ordered = avoid_adjacent_repeats(indexed, artist_key=lambda pair: getattr(pair[1], "artist", ""))
        indices = tuple(i for i, _ in ordered)
        artists_seq = [getattr(t, "artist", "").strip().casefold() for _, t in ordered]
        valid = all(a != b for a, b in zip(artists_seq, artists_seq[1:]))
        return indices, valid

    monkeypatch.setattr(PrologEngine, "find_recommendations", fake_find_recommendations)
    monkeypatch.setattr(PrologEngine, "arrange_tracks", fake_arrange_tracks)
