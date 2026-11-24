from abc import ABC, abstractmethod
from datetime import date
from enum import Enum
from typing import Any, Callable, Iterable, List, Optional, Tuple

from core.formatting import (
    format_library_track_details,
    format_track_details,
    render_playlist_lines,
)
from core.functional import filter_by, sort_by_key
from core.graph import explain_recommendation_chain, find_recommendation_chain_recursive
from core.playlist import calculate_total_duration
from core.types import ArtistNode, LibraryTrackData, PlaylistData, TrackData


class Mood(Enum):
    """Настрій треку або плейлиста."""
    ENERGETIC = "енергійний"
    CALM = "спокійний"
    HAPPY = "веселий"
    SAD = "сумний"
    FOCUSED = "зосереджений"

    @classmethod
    def aliases(cls) -> dict[str, "Mood"]:
        """Словник відповідностей (українські та стандартні англомовні назви)."""
        return {
            "енергійний": cls.ENERGETIC,
            "energetic": cls.ENERGETIC,
            "спокійний": cls.CALM,
            "calm": cls.CALM,
            "веселий": cls.HAPPY,
            "happy": cls.HAPPY,
            "сумний": cls.SAD,
            "sad": cls.SAD,
            "зосереджений": cls.FOCUSED,
            "focused": cls.FOCUSED,
        }

    @classmethod
    def parse(cls, value: "str | Mood") -> "Mood":
        """Перетворює рядок (українською чи англійською) на Mood; кидає ValueError для невідомого."""
        if isinstance(value, cls):
            return value
        val_str = str(value).strip().casefold()
        mapping = cls.aliases()
        if val_str in mapping:
            return mapping[val_str]
        allowed = ", ".join(m.value for m in cls)
        eng_allowed = ", ".join(k for k in mapping if k.isascii())
        raise ValueError(f"Невідомий настрій '{value}'. Доступні: {allowed} (або англійською: {eng_allowed})")


class MediaItem(ABC):
    """Базовий абстрактний клас для будь-якого медіа-елемента."""
    def __init__(self, title: str):
        self._title = title

    @property
    def title(self) -> str:
        return self._title

    @abstractmethod
    def get_details(self) -> str:
        """Абстрактний метод для поліморфізму."""
        pass


class AudioTrack(MediaItem):
    """Рівень наслідування 1: Базовий аудіотрек."""
    def __init__(
        self,
        title: str,
        artist: str,
        duration_sec: int,
        genre: Optional[str] = None,
        album_id: Optional[int] = None,
    ):
        super().__init__(title)
        self._artist = artist
        self._duration_sec = duration_sec
        self.genre = genre or "unknown"
        self.album_id = album_id

    @property
    def artist(self) -> str:
        return self._artist

    @property
    def duration_sec(self) -> int:
        return self._duration_sec

    def to_data(self) -> TrackData:
        """Конвертація в незмінну структуру даних функціонального ядра."""
        return TrackData(
            title=self._title,
            artist=self._artist,
            duration_sec=self._duration_sec,
            genre=self.genre,
            album_id=self.album_id,
        )

    def get_details(self) -> str:
        return format_track_details(self._title, self._artist, self._duration_sec)


class LibraryTrack(AudioTrack):
    """Рівень наслідування 2: Трек з користувацької бібліотеки з оцінками та метаданими."""
    def __init__(
        self,
        title: str,
        artist: str,
        duration_sec: int,
        genre: str,
        mood: str | Mood,
        rating: int,
        last_played: date,
        album_id: Optional[int] = None,
    ):
        super().__init__(title, artist, duration_sec, genre=genre, album_id=album_id)
        self.genre = genre
        self.mood = Mood.parse(mood)
        self.rating = rating  # Викличе setter для валідації
        self.last_played = last_played

    @property
    def rating(self) -> int:
        return self._rating

    @rating.setter
    def rating(self, value: int):
        # Інкапсуляція з перевіркою валідності даних
        if not 1 <= value <= 5:
            raise ValueError("Оцінка має бути від 1 до 5")
        self._rating = value

    def to_data(self) -> LibraryTrackData:
        """Конвертація в незмінну структуру даних функціонального ядра."""
        return LibraryTrackData(
            title=self._title,
            artist=self._artist,
            duration_sec=self._duration_sec,
            genre=self.genre,
            album_id=self.album_id,
            mood=self.mood.value,
            rating=self._rating,
            last_played=self.last_played,
        )

    def get_details(self) -> str:
        # Обчислення розширеного формату делеговано чистій функції ядра
        return format_library_track_details(
            title=self._title,
            artist=self._artist,
            duration_sec=self._duration_sec,
            genre=self.genre,
            mood=self.mood.value,
            rating=self._rating,
        )


class Playlist:
    """Клас для агрегації треків та генерації плейлистів."""
    def __init__(self, name: str):
        self.name = name
        self._tracks: List[MediaItem] = []
        self._explanations: dict[str, str] = {}

    def add_track(self, track: MediaItem):
        self._tracks.append(track)

    def set_explanation(self, artist: str, reason: str) -> None:
        """Зберігає пояснення (Explainability) для рекомендованого виконавця."""
        key = artist.strip().casefold()
        if key and reason:
            self._explanations[key] = reason

    def get_explanation(self, artist: str) -> Optional[str]:
        """Повертає пояснення рекомендації для виконавця або None."""
        return self._explanations.get(artist.strip().casefold())

    @property
    def explanations(self) -> dict[str, str]:
        """Копія словника пояснень для рекомендованих виконавців."""
        return dict(self._explanations)

    @property
    def tracks(self) -> Tuple[MediaItem, ...]:
        """Незмінний перегляд треків плейлиста."""
        return tuple(self._tracks)

    @property
    def total_duration(self) -> int:
        """Сумарна тривалість у секундах"""
        return calculate_total_duration(self._tracks)

    def filter_tracks(self, predicate: Callable[[MediaItem], bool]) -> "Playlist":
        """Фільтрує треки плейлиста через функцію вищого порядку filter_by з ядра."""
        filter_func = filter_by(predicate)
        filtered_playlist = Playlist(f"{self.name} (filtered)")
        for track in filter_func(self._tracks):
            filtered_playlist.add_track(track)
        return filtered_playlist

    def sort_tracks(self, key_fn: Callable[[MediaItem], Any], reverse: bool = False) -> "Playlist":
        """Сортує треки плейлиста через функцію вищого порядку sort_by_key з ядра."""
        sorter = sort_by_key(key_fn, reverse=reverse)
        sorted_playlist = Playlist(f"{self.name} (sorted)")
        for track in sorter(self._tracks):
            sorted_playlist.add_track(track)
        return sorted_playlist

    def to_data(self) -> PlaylistData:
        """Конвертація в незмінну структуру даних PlaylistData ядра."""
        data_tracks = tuple(
            t.to_data() if hasattr(t, "to_data") else TrackData(
                title=getattr(t, "title", ""),
                artist=getattr(t, "artist", ""),
                duration_sec=getattr(t, "duration_sec", 0),
            )
            for t in self._tracks
        )
        return PlaylistData(name=self.name, tracks=data_tracks)

    def render(self) -> str:
        """Повертає текстове представлення плейлиста"""
        lines = []
        for track in self._tracks:
            details = track.get_details()
            artist = getattr(track, "artist", "")
            reason = self.get_explanation(artist) if artist else None
            lines.append(f"{details}\n     -> {reason}" if reason else details)
        return render_playlist_lines(self.name, tuple(lines))

    def __str__(self) -> str:
        return self.render()

    def show_playlist(self):
        print(self.render())


class Artist:
    """Виконавець — вершина графа схожості (зв'язки спрямовані, як у Deezer /related)."""
    def __init__(self, name: str, deezer_id: Optional[int] = None, banned: bool = False):
        self._name = name
        self._deezer_id = deezer_id
        self.banned = banned  # "заборонений" — не потрапляє в плейлисти
        self._related: List["Artist"] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def deezer_id(self) -> Optional[int]:
        return self._deezer_id

    @property
    def banned(self) -> bool:
        return self._banned

    @banned.setter
    def banned(self, value: bool):
        self._banned = bool(value)

    @property
    def related(self) -> Tuple["Artist", ...]:
        """Незмінний перегляд схожих виконавців."""
        return tuple(self._related)

    def add_related(self, other: "Artist"):
        if other is self:
            raise ValueError("Виконавець не може бути схожим сам на себе")
        if other not in self._related:
            self._related.append(other)

    def to_graph_dict(self) -> dict[str, tuple[str, ...]]:
        """Побудова графа схожості для передачі у функціональне ядро."""
        graph: dict[str, tuple[str, ...]] = {}
        queue = [self]
        visited = set()
        while queue:
            curr = queue.pop(0)
            if curr.name in visited:
                continue
            visited.add(curr.name)
            graph[curr.name] = tuple(r.name for r in curr.related)
            for r in curr.related:
                if r.name not in visited:
                    queue.append(r)
        return graph

    def to_node(self) -> ArtistNode:
        """Конвертація у незмінну вершину ядра ArtistNode."""
        return ArtistNode(
            name=self._name,
            banned=self._banned,
            related=tuple(r.name for r in self._related),
            deezer_id=self._deezer_id,
        )

    def find_path_to(
        self,
        target: "Artist | str",
        banned_names: Iterable[str] = (),
        max_depth: int = 3,
    ) -> Optional[Tuple[str, ...]]:
        """Знаходить шлях схожості через чисту рекурсивну функцію ядра."""
        target_name = target.name if isinstance(target, Artist) else str(target)
        graph = self.to_graph_dict()
        banned_set = frozenset(b.strip().casefold() for b in banned_names)
        return find_recommendation_chain_recursive(
            graph=graph,
            current=self.name,
            target=target_name,
            banned=banned_set,
            max_depth=max_depth,
        )

    def explain_path_to(
        self,
        target: "Artist | str",
        banned_names: Iterable[str] = (),
        max_depth: int = 3,
    ) -> str:
        """Повертає текстове пояснення рекомендації через чисту функцію ядра."""
        path = self.find_path_to(target, banned_names=banned_names, max_depth=max_depth)
        return explain_recommendation_chain(path) if path else ""

    def __repr__(self) -> str:
        flag = ", banned" if self._banned else ""
        return f"Artist({self._name!r}{flag}, related={len(self._related)})"
