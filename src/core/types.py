"""Незмінні структури даних та протоколи типів для функціонального ядра."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class TrackProtocol(Protocol):
    """Структурний інтерфейс будь-якого треку, з яким працюють чисті функції ядра."""

    @property
    def title(self) -> str: ...

    @property
    def artist(self) -> str: ...

    @property
    def duration_sec(self) -> int: ...


@dataclass(frozen=True)
class TrackData:
    """Незмінне представлення базового аудіотреку для функціонального ядра."""

    title: str
    artist: str
    duration_sec: int
    genre: str = "unknown"
    album_id: Optional[int] = None


@dataclass(frozen=True)
class LibraryTrackData(TrackData):
    """Незмінне представлення треку з бібліотеки з метаданими вподобань."""

    mood: str = "енергійний"
    rating: int = 3
    last_played: Optional[date] = None


@dataclass(frozen=True)
class PlaylistData:
    """Незмінне представлення плейлиста як результату чистої генерації."""

    name: str
    tracks: Tuple[TrackProtocol, ...] = field(default_factory=tuple)

    @property
    def total_duration(self) -> int:
        return sum(t.duration_sec for t in self.tracks)


@dataclass(frozen=True)
class ArtistNode:
    """Незмінна вершина графа схожості виконавців."""

    name: str
    banned: bool = False
    related: Tuple[str, ...] = field(default_factory=tuple)
    deezer_id: Optional[int] = None


@dataclass(frozen=True)
class RecommendationPath:
    """Незмінний результат пошуку ланцюжка рекомендації в графі схожості."""

    source: str
    target: str
    path: Tuple[str, ...]
    length: int

    @property
    def explanation(self) -> str:
        return " -> ".join(self.path)
