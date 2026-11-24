import sys
from pathlib import Path

# Дозволяє запускати файл напряму (не лише через pytest): додаємо src/ до шляху імпорту
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from datetime import date

import pytest

from generator import PlaylistGenerator
from models import AudioTrack, LibraryTrack

pytestmark = pytest.mark.usefixtures("prolog_unit_fallback")

TODAY = date(2026, 10, 20)


def lib(title, artist, sec=180, mood="енергійний", rating=3, played=date(2026, 9, 1)):
    return LibraryTrack(title, artist, sec, "rock", mood, rating, played)


def artists(playlist):
    return [t.artist for t in playlist.tracks]


def test_total_duration_does_not_exceed_budget():
    library = [lib(f"T{i}", f"A{i}") for i in range(10)]
    playlist = PlaylistGenerator(library).generate(10, new_percent=0, today=TODAY)
    assert 0 < playlist.total_duration <= 600


def test_banned_artist_is_excluded_from_library_and_discoveries():
    library = [lib("1", "Good"), lib("2", "Bad")]
    discoveries = [AudioTrack("3", "Evil", 180), AudioTrack("4", "Nice", 180)]
    gen = PlaylistGenerator(library, discoveries, banned_artists=["bad", "EVIL"])
    result = artists(gen.generate(60, new_percent=50, today=TODAY))
    assert "Bad" not in result and "Evil" not in result
    assert "Good" in result and "Nice" in result


def test_mood_filter_applies_to_library():
    library = [lib("1", "A", mood="спокійний"), lib("2", "B", mood="енергійний")]
    result = artists(PlaylistGenerator(library).generate(60, mood="спокійний", new_percent=0, today=TODAY))
    assert result == ["A"]


def test_new_percent_limits_discoveries_budget():
    library = [lib(f"L{i}", f"A{i}") for i in range(10)]
    discoveries = [AudioTrack(f"N{i}", f"New{i}", 180) for i in range(10)]
    playlist = PlaylistGenerator(library, discoveries).generate(30, new_percent=20, today=TODAY)
    new_sec = sum(t.duration_sec for t in playlist.tracks if t.artist.startswith("New"))
    assert new_sec <= 30 * 60 * 20 // 100


def test_zero_new_percent_has_no_discoveries():
    library = [lib("1", "A")]
    discoveries = [AudioTrack("2", "New", 180)]
    assert artists(PlaylistGenerator(library, discoveries).generate(60, new_percent=0, today=TODAY)) == ["A"]


def test_discovery_of_already_known_artist_is_not_new():
    library = [lib("1", "A")]
    discoveries = [AudioTrack("2", "a", 180)]
    result = artists(PlaylistGenerator(library, discoveries).generate(60, new_percent=50, today=TODAY))
    assert result == ["A"]


def test_higher_rating_is_preferred_when_budget_is_tight():
    library = [lib("low", "L", rating=1), lib("high", "H", rating=5)]
    playlist = PlaylistGenerator(library).generate(3, new_percent=0, today=TODAY)
    assert artists(playlist) == ["H"]


def test_longer_unplayed_track_gets_higher_weight():
    gen = PlaylistGenerator([])
    old = lib("old", "A", rating=3, played=date(2026, 1, 1))
    fresh = lib("fresh", "B", rating=3, played=TODAY)
    assert gen._weight(old, TODAY) > gen._weight(fresh, TODAY)


def test_same_artist_not_played_twice_in_a_row_when_possible():
    library = [lib("1", "A", rating=5), lib("2", "A", rating=4), lib("3", "B", rating=1)]
    result = artists(PlaylistGenerator(library).generate(60, new_percent=0, today=TODAY))
    assert result == ["A", "B", "A"]


@pytest.mark.parametrize("minutes", [0, -5])
def test_invalid_duration_raises(minutes):
    with pytest.raises(ValueError):
        PlaylistGenerator([]).generate(minutes)


@pytest.mark.parametrize("percent", [-1, 101])
def test_invalid_percent_raises(percent):
    with pytest.raises(ValueError):
        PlaylistGenerator([]).generate(10, new_percent=percent)


def test_unknown_mood_raises():
    with pytest.raises(ValueError):
        PlaylistGenerator([]).generate(10, mood="нудний")
