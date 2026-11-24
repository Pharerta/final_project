import json
import urllib.parse
import urllib.request

from models import Artist, AudioTrack


class DeezerAPIClient:
    """Клас-сервіс для отримання даних з відкритого API Deezer."""
    BASE_URL = "https://api.deezer.com"
    _album_genre_cache: dict[int, str] = {}

    @classmethod
    def get_album_genre(cls, album_id: int | None) -> str | None:
        """Повертає назву жанру альбому з Deezer (/album/{id}) за album_id (з кешуванням) або None."""
        if not album_id:
            return None
        if album_id in cls._album_genre_cache:
            return cls._album_genre_cache[album_id]
        try:
            with urllib.request.urlopen(f"{cls.BASE_URL}/album/{album_id}") as response:
                data = json.loads(response.read().decode('utf-8'))
                genres = data.get('genres', {}).get('data', [])
                genre = genres[0]['name'] if genres else None
                if genre:
                    cls._album_genre_cache[album_id] = genre
                return genre
        except Exception:
            return None

    @staticmethod
    def search_tracks(query: str, limit: int = 5) -> list[AudioTrack]:
        """
        Шукає треки за запитом і конвертує JSON-відповідь 
        в об'єкти нашої ООП-моделі (AudioTrack).
        """
        encoded_query = urllib.parse.quote(query)
        url = f"{DeezerAPIClient.BASE_URL}/search?q={encoded_query}&limit={limit}"
        
        try:
            with urllib.request.urlopen(url) as response:
                raw_data = response.read().decode('utf-8')
                json_data = json.loads(raw_data)
                
                tracks = []
                for item in json_data.get('data', []):
                    title = item.get('title', 'Невідомо')
                    artist = item.get('artist', {}).get('name', 'Невідомий виконавець')
                    duration = item.get('duration', 0)
                    album_id = item.get('album', {}).get('id')
                    tracks.append(AudioTrack(title=title, artist=artist, duration_sec=duration, album_id=album_id))
                    
                return tracks
                
        except Exception as e:
            print(f"[Помилка] Не вдалося отримати дані з Deezer: {e}")
            return []

    @staticmethod
    def _get_data(path: str) -> list[dict]:
        """GET-запит до Deezer; повертає масив 'data' або [] при помилці."""
        try:
            with urllib.request.urlopen(f"{DeezerAPIClient.BASE_URL}{path}") as response:
                return json.loads(response.read().decode('utf-8')).get('data', [])
        except Exception as e:
            print(f"[Помилка] Не вдалося отримати дані з Deezer: {e}")
            return []

    @staticmethod
    def search_artist(name: str) -> Artist | None:
        """Шукає виконавця за назвою; повертає найбільш релевантного або None."""
        items = DeezerAPIClient._get_data(f"/search/artist?q={urllib.parse.quote(name)}&limit=1")
        return Artist(items[0]['name'], deezer_id=items[0]['id']) if items else None

    @staticmethod
    def top_tracks(artist: Artist, limit: int = 10, fetch_genre: bool = True) -> list[AudioTrack]:
        """Популярні треки виконавця (/artist/{id}/top) з можливістю підтягування жанру альбому."""
        items = DeezerAPIClient._get_data(f"/artist/{artist.deezer_id}/top?limit={limit}")
        tracks = []
        for i in items:
            title = i.get('title', 'Невідомо')
            duration = i.get('duration', 0)
            album_id = i.get('album', {}).get('id')
            genre = DeezerAPIClient.get_album_genre(album_id) if (fetch_genre and album_id) else None
            tracks.append(AudioTrack(title, artist.name, duration, genre=genre, album_id=album_id))
        return tracks

    @staticmethod
    def related_artists(artist: Artist, limit: int = 5) -> list[Artist]:
        """Схожі виконавці (/artist/{id}/related); додає їх у artist.related."""
        items = DeezerAPIClient._get_data(f"/artist/{artist.deezer_id}/related?limit={limit}")
        related = [Artist(i['name'], deezer_id=i['id']) for i in items]
        for other in related:
            artist.add_related(other)
        return related

    @classmethod
    def resolve_track(cls, title: str, artist: str, seconds: int | None = None) -> AudioTrack:
        """
        Знаходить трек у Deezer за назвою та виконавцем з валідацією тривалості.

        - Якщо seconds вказано: додається лише трек з реально існуючим часом у Deezer
          (як унікальний складений ключ разом з виконавцем та назвою треку).
        - Якщо seconds не вказано:
          - якщо комбінація виконавця з назвою треку унікальна для сервісу (одна тривалість) —
            секунди не мають значення і тривалість береться з сервісу;
          - якщо знайдено кілька версій з різною тривалістю — кидає ValueError
            із зазначенням доступних тривалостей та вимогою вказати --seconds.
        """
        query = f"{artist} {title}"
        tracks = cls.search_tracks(query, limit=30)
        if not tracks:
            raise ValueError(f"Трек '{title}' виконавця '{artist}' не знайдено в Deezer (або немає інтернету).")

        norm_artist = artist.strip().casefold()
        norm_title = title.strip().casefold()
        base_norm_title = norm_title.rstrip(".")

        # 1. Точний збіг за виконавцем та назвою (ігноруючи регістр та крапку в кінці)
        exact_matches = [
            t for t in tracks
            if t.artist.strip().casefold() == norm_artist
            and t.title.strip().casefold().rstrip(".") == base_norm_title
        ]

        # 2. Версії виконання: назва треку містить базову назву (Live, Acoustic, Demo, Remaster тощо)
        version_matches = [
            t for t in tracks
            if t.artist.strip().casefold() == norm_artist
            and (base_norm_title in t.title.strip().casefold() or t.title.strip().casefold().rstrip(".") == base_norm_title)
        ]

        candidates = exact_matches if exact_matches else version_matches
        if not candidates:
            artist_candidates = [t for t in tracks if norm_artist in t.artist.strip().casefold()]
            candidates = artist_candidates or tracks

        durations = sorted({t.duration_sec for t in candidates if t.duration_sec > 0})
        if not durations:
            raise ValueError(f"Для треку '{title}' виконавця '{artist}' не знайдено коректної тривалості в Deezer.")

        if seconds is not None:
            # Шукаємо точний збіг за заданою тривалістю серед кандидатів або версій виконання
            matched = next((t for t in candidates if t.duration_sec == seconds), None)
            if matched is None and version_matches:
                matched = next((t for t in version_matches if t.duration_sec == seconds), None)

            if matched is not None:
                genre = matched.genre if matched.genre != "unknown" else cls.get_album_genre(matched.album_id)
                return AudioTrack(
                    title=matched.title,
                    artist=matched.artist,
                    duration_sec=matched.duration_sec,
                    genre=genre,
                    album_id=matched.album_id,
                )

            all_durations = sorted(set(durations) | {t.duration_sec for t in version_matches if t.duration_sec > 0})
            dur_str = ", ".join(f"{d} с" for d in all_durations)
            raise ValueError(
                f"У Deezer не знайдено версію треку '{title}' ({artist}) з тривалістю {seconds} с. "
                f"Доступні версії: {dur_str}."
            )

        # Якщо seconds не вказано:
        if len(durations) == 1:
            chosen_duration = durations[0]
            matched = next(t for t in candidates if t.duration_sec == chosen_duration)
            genre = matched.genre if matched.genre != "unknown" else cls.get_album_genre(matched.album_id)
            return AudioTrack(
                title=matched.title,
                artist=matched.artist,
                duration_sec=chosen_duration,
                genre=genre,
                album_id=matched.album_id,
            )

        dur_str = ", ".join(f"{d} с" for d in durations)
        raise ValueError(
            f"Знайдено кілька версій треку '{title}' ({artist}) з різною тривалістю ({dur_str}). "
            f"Вкажіть --seconds для вибору версії."
        )

