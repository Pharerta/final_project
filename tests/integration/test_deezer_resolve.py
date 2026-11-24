import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from services.deezer import DeezerAPIClient


def has_deezer_connection() -> bool:
    try:
        res = DeezerAPIClient.search_tracks("Blur", limit=1)
        return len(res) > 0
    except Exception:
        return False


ONLINE = has_deezer_connection()
skip_if_offline = pytest.mark.skipif(not ONLINE, reason="Немає підключення до Deezer API")


@skip_if_offline
def test_online_deezer_resolve_without_seconds_when_unique():
    # 'Song 2' у Blur має унікальну студійну тривалість 121 сек у Deezer та жанр Rock
    track = DeezerAPIClient.resolve_track("Song 2", "Blur")
    assert track.artist == "Blur"
    assert track.duration_sec == 121
    assert track.genre == "Rock"


@skip_if_offline
def test_online_deezer_album_genre():
    # Перевірка отримання та кешування жанру альбому
    genre = DeezerAPIClient.get_album_genre(300062)
    assert genre == "Rock"


@skip_if_offline
def test_online_deezer_resolve_with_matching_seconds():
    track = DeezerAPIClient.resolve_track("Song 2", "Blur", seconds=121)
    assert track.duration_sec == 121


@skip_if_offline
def test_online_deezer_resolve_with_invalid_seconds_raises():
    with pytest.raises(ValueError, match="не знайдено версію"):
        DeezerAPIClient.resolve_track("Song 2", "Blur", seconds=999)


@skip_if_offline
def test_online_deezer_resolve_ambiguous_requires_seconds():
    # 'Bohemian Rhapsody' у Queen має кілька версій з різною тривалістю (317, 334, 354)
    with pytest.raises(ValueError, match="Знайдено кілька версій"):
        DeezerAPIClient.resolve_track("Bohemian Rhapsody", "Queen")

    # З вказанням --seconds успішно обирається
    track = DeezerAPIClient.resolve_track("Bohemian Rhapsody", "Queen", seconds=354)
    assert track.duration_sec == 354
