"""Чисті функції форматування текстових представлень треків та плейлистів.

Всі функції є детермінованими, не мають побічних ефектів (жодного введення-виведення,
print чи глобальних змінних) і приймають аргументи напряму.
"""
from typing import Sequence


def format_duration(duration_sec: int) -> str:
    """Форматує тривалість у секундах у вигляд 'M:SS' (або '0:00')"""
    mins, secs = divmod(max(0, duration_sec), 60)
    return f"{mins}:{secs:02d}"


def format_track_details(title: str, artist: str, duration_sec: int) -> str:
    """Форматує базовий аудіотрек: "'Назва' — Виконавець (M:SS)"."""
    dur = format_duration(duration_sec)
    return f"'{title}' — {artist} ({dur})"


def format_library_track_details(
    title: str,
    artist: str,
    duration_sec: int,
    genre: str,
    mood: str,
    rating: int,
) -> str:
    """Форматує трек бібліотеки з розширеними метаданими."""
    base = format_track_details(title, artist, duration_sec)
    return f"{base} | Жанр: {genre}, Настрій: '{mood}', Оцінка: {rating}/5"


def render_playlist_lines(name: str, track_details: Sequence[str]) -> str:
    """Формує багаторядковий текстовий звіт плейлиста без використання print/I-O."""
    lines = [f"\n=== Плейлист: {name} ==="]
    for i, detail in enumerate(track_details, 1):
        lines.append(f"{i}. {detail}")
    return "\n".join(lines)

