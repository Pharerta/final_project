import sys
from pathlib import Path

# Дозволяє запускати файл напряму (не лише через pytest): додаємо src/ до шляху імпорту
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from datetime import date

import pytest

from models import Artist, AudioTrack, LibraryTrack, Mood, Playlist


def make_library_track(**overrides) -> LibraryTrack:
    params = dict(
        title="Song 2", artist="Blur", duration_sec=122,
        genre="britpop", mood="енергійний", rating=4, last_played=date(2026, 9, 15),
    )
    params.update(overrides)
    return LibraryTrack(**params)


# --- Mood ---

def test_mood_parse_from_string_is_case_insensitive():
    assert Mood.parse("  Енергійний ") is Mood.ENERGETIC


def test_mood_parse_accepts_english_aliases():
    assert Mood.parse("energetic") is Mood.ENERGETIC
    assert Mood.parse("  CALM ") is Mood.CALM
    assert Mood.parse("happy") is Mood.HAPPY
    assert Mood.parse("sad") is Mood.SAD
    assert Mood.parse("focused") is Mood.FOCUSED


def test_mood_parse_accepts_mood_instance():
    assert Mood.parse(Mood.CALM) is Mood.CALM


def test_mood_parse_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Невідомий настрій"):
        Mood.parse("нудний")


# --- AudioTrack / LibraryTrack ---

def test_audio_track_details_format_duration():
    track = AudioTrack("Vidchuttia", "Okean Elzy", 245)
    assert track.get_details() == "'Vidchuttia' — Okean Elzy (4:05)"


def test_audio_track_pads_seconds():
    assert AudioTrack("A", "B", 61).get_details().endswith("(1:01)")


def test_library_track_inherits_two_levels():
    track = make_library_track()
    assert isinstance(track, AudioTrack)
    assert track.title == "Song 2"
    assert track.artist == "Blur"


def test_library_track_converts_mood_string_to_enum():
    assert make_library_track(mood="спокійний").mood is Mood.CALM


def test_library_track_invalid_mood_raises():
    with pytest.raises(ValueError):
        make_library_track(mood="невідомий")


@pytest.mark.parametrize("rating", [1, 3, 5])
def test_rating_valid_boundaries(rating):
    assert make_library_track(rating=rating).rating == rating


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_rating_out_of_range_raises(rating):
    with pytest.raises(ValueError):
        make_library_track(rating=rating)


def test_rating_setter_rejects_invalid_and_keeps_old_value():
    track = make_library_track(rating=4)
    with pytest.raises(ValueError):
        track.rating = 7
    assert track.rating == 4


def test_library_track_details_polymorphic_extension():
    details = make_library_track().get_details()
    assert "Жанр: britpop" in details
    assert "Настрій: 'енергійний'" in details
    assert "Оцінка: 4/5" in details


# --- Playlist ---

def test_playlist_polymorphism_prints_each_track(capsys):
    playlist = Playlist("Тест")
    playlist.add_track(AudioTrack("A", "X", 60))
    playlist.add_track(make_library_track())
    playlist.show_playlist()
    out = capsys.readouterr().out
    assert "=== Плейлист: Тест ===" in out
    assert "1. 'A' — X (1:00)" in out
    assert "2. 'Song 2' — Blur" in out


def test_playlist_render_returns_string_without_printing(capsys):
    playlist = Playlist("Тест")
    playlist.add_track(AudioTrack("A", "X", 60))
    text = playlist.render()
    assert "=== Плейлист: Тест ===" in text and "1. 'A' — X (1:00)" in text
    assert str(playlist) == text
    assert capsys.readouterr().out == ""


def test_playlist_total_duration_and_tracks_view():
    playlist = Playlist("Тест")
    assert playlist.total_duration == 0
    playlist.add_track(AudioTrack("A", "X", 60))
    playlist.add_track(AudioTrack("B", "Y", 90))
    assert playlist.total_duration == 150
    assert isinstance(playlist.tracks, tuple) and len(playlist.tracks) == 2


# --- Artist ---

def test_artist_defaults():
    artist = Artist("Blur")
    assert artist.name == "Blur"
    assert artist.deezer_id is None
    assert artist.banned is False
    assert artist.related == ()


def test_artist_add_related_is_directed():
    blur, gorillaz = Artist("Blur"), Artist("Gorillaz")
    blur.add_related(gorillaz)
    assert blur.related == (gorillaz,)
    assert gorillaz.related == ()


def test_artist_add_related_ignores_duplicates():
    blur, gorillaz = Artist("Blur"), Artist("Gorillaz")
    blur.add_related(gorillaz)
    blur.add_related(gorillaz)
    assert len(blur.related) == 1


def test_artist_cannot_be_related_to_self():
    blur = Artist("Blur")
    with pytest.raises(ValueError):
        blur.add_related(blur)


def test_artist_related_is_immutable_view():
    blur = Artist("Blur")
    assert isinstance(blur.related, tuple)


def test_artist_banned_flag_can_be_toggled():
    artist = Artist("X", banned=True)
    assert artist.banned is True
    artist.banned = False
    assert artist.banned is False
