"""Постійне сховище даних Куратора плейлистів на базі SQLite (розширення E7).

Усі SQL-запити є статичними та виключно параметризованими (використовуються
лише плейсхолдери `?`) для захисту від SQL-ін'єкцій та коректної типізації.
Між сесіями зберігаються:
- виконавці та статус заборони (`artists`)
- граф схожості виконавців (`artist_similarity`)
- треки бібліотеки та відкриття (`tracks`)
- пояснення та ланцюжки рекомендацій (`recommendations`)
- згенеровані плейлисти та їхній склад (`playlists`, `playlist_tracks`)
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from models import Artist, AudioTrack, LibraryTrack, Mood, Playlist

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "curator.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    deezer_id INTEGER,
    banned INTEGER NOT NULL DEFAULT 0 CHECK (banned IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS artist_similarity (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id),
    FOREIGN KEY (source_id) REFERENCES artists(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES artists(id) ON DELETE CASCADE,
    CHECK (source_id <> target_id)
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    duration_sec INTEGER NOT NULL CHECK (duration_sec > 0),
    genre TEXT NOT NULL DEFAULT 'unknown',
    album_id INTEGER,
    is_library INTEGER NOT NULL DEFAULT 1 CHECK (is_library IN (0, 1)),
    mood TEXT,
    rating INTEGER CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
    last_played TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tracks_role_artist
    ON tracks (is_library, artist_id, title_key);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_artist_id INTEGER,
    recommended_artist_id INTEGER NOT NULL,
    path_text TEXT NOT NULL,
    reason TEXT NOT NULL,
    steps INTEGER NOT NULL CHECK (steps >= 1),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (seed_artist_id) REFERENCES artists(id) ON DELETE SET NULL,
    FOREIGN KEY (recommended_artist_id) REFERENCES artists(id) ON DELETE CASCADE,
    UNIQUE (recommended_artist_id, path_text)
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_minutes INTEGER NOT NULL CHECK (target_minutes > 0),
    mood TEXT,
    new_percent INTEGER NOT NULL CHECK (new_percent BETWEEN 0 AND 100),
    total_duration_sec INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    track_id INTEGER,
    title TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    duration_sec INTEGER NOT NULL CHECK (duration_sec > 0),
    genre TEXT NOT NULL DEFAULT 'unknown',
    mood TEXT,
    rating INTEGER,
    explanation TEXT,
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE SET NULL,
    UNIQUE (playlist_id, position)
);
"""


def resolve_db_path(db_path: Optional[str | Path] = None) -> str:
    """Визначає шлях до SQLite БД: явний параметр > PLAYLIST_CURATOR_DB > data/curator.db."""
    if db_path is not None:
        return str(db_path)
    env_path = os.environ.get("PLAYLIST_CURATOR_DB")
    if env_path:
        return env_path
    return str(DEFAULT_DB_PATH)


def _norm_key(value: str) -> str:
    return value.strip().casefold()


@dataclass(frozen=True)
class SavedTrackRecord:
    """Незмінний запис треку з бібліотеки разом із його первинним ключем у БД."""
    id: int
    track: LibraryTrack


@dataclass(frozen=True)
class SavedRecommendation:
    """Незмінний запис збереженої рекомендації з БД."""
    id: int
    seed_artist: str
    recommended_artist: str
    path_text: str
    reason: str
    steps: int
    created_at: str


@dataclass(frozen=True)
class SavedPlaylistSummary:
    """Незмінний підсумок збереженого плейлиста."""
    id: int
    name: str
    target_minutes: int
    mood: Optional[str]
    new_percent: int
    total_duration_sec: int
    track_count: int
    created_at: str


class SQLiteStorage:
    """Репозиторій SQLite для збереження колекції, виконавців, рекомендацій і плейлистів."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = resolve_db_path(db_path)
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None

        if not self._is_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.execute("PRAGMA foreign_keys = ON")

        self.init_schema()

    def close(self) -> None:
        """Закриває in-memory з'єднання (для файлових БД з'єднання закриваються автоматично)."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            conn = self._memory_conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Створює таблиці та індекси, якщо вони ще не існують."""
        with self._connection() as conn:
            conn.executescript(SCHEMA_SQL)

    # --- Допоміжні внутрішні методи (працюють у межах відкритої транзакції) ---

    def _ensure_artist(
        self,
        conn: sqlite3.Connection,
        name: str,
        deezer_id: Optional[int] = None,
        banned: Optional[bool] = None,
    ) -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Ім'я виконавця не може бути порожнім")
        name_key = _norm_key(clean_name)

        existing = conn.execute(
            "SELECT id, deezer_id, banned FROM artists WHERE name_key = ?",
            (name_key,),
        ).fetchone()

        if existing is None:
            banned_flag = 1 if banned else 0
            cursor = conn.execute(
                "INSERT INTO artists (name, name_key, deezer_id, banned) VALUES (?, ?, ?, ?)",
                (clean_name, name_key, deezer_id, banned_flag),
            )
            return int(cursor.lastrowid)

        new_deezer_id = deezer_id if deezer_id is not None else existing["deezer_id"]
        new_banned = existing["banned"] if banned is None else (1 if banned else 0)
        conn.execute(
            "UPDATE artists SET name = ?, deezer_id = ?, banned = ? WHERE id = ?",
            (clean_name, new_deezer_id, new_banned, existing["id"]),
        )
        return int(existing["id"])

    def _find_matching_track_id(
        self,
        conn: sqlite3.Connection,
        artist_name: str,
        title: str,
        duration_sec: int,
    ) -> Optional[int]:
        row = conn.execute(
            """
            SELECT t.id
            FROM tracks t
            JOIN artists a ON a.id = t.artist_id
            WHERE a.name_key = ? AND t.title_key = ? AND t.duration_sec = ?
            ORDER BY t.is_library DESC, t.id ASC
            LIMIT 1
            """,
            (_norm_key(artist_name), _norm_key(title), duration_sec),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    # --- Операції над виконавцями та заборонами ---

    def upsert_artist(
        self,
        name: str,
        deezer_id: Optional[int] = None,
        banned: Optional[bool] = None,
    ) -> int:
        """Додає або оновлює виконавця у таблиці `artists`."""
        with self._connection() as conn:
            return self._ensure_artist(conn, name, deezer_id=deezer_id, banned=banned)

    def set_artist_banned(self, name: str, banned: bool) -> int:
        """Встановлює статус заборони виконавця (`banned = 1` або `0`)."""
        with self._connection() as conn:
            return self._ensure_artist(conn, name, banned=banned)

    def is_artist_banned(self, name: str) -> bool:
        """Перевіряє, чи перебуває виконавець у списку заборонених."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT banned FROM artists WHERE name_key = ?",
                (_norm_key(name),),
            ).fetchone()
            return bool(row and row["banned"] == 1)

    def load_banned_artists(self) -> Dict[str, str]:
        """Повертає словник {name_key: name} усіх заборонених виконавців."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT name_key, name FROM artists WHERE banned = 1 ORDER BY id ASC"
            ).fetchall()
            return {row["name_key"]: row["name"] for row in rows}

    def load_artists(self) -> List[Artist]:
        """Відновлює всіх виконавців і граф схожості як ООП-об'єкти `Artist`."""
        with self._connection() as conn:
            artist_rows = conn.execute(
                "SELECT id, name, deezer_id, banned FROM artists ORDER BY id ASC"
            ).fetchall()
            by_id: Dict[int, Artist] = {}
            for row in artist_rows:
                by_id[int(row["id"])] = Artist(
                    name=row["name"],
                    deezer_id=row["deezer_id"],
                    banned=bool(row["banned"]),
                )

            edge_rows = conn.execute(
                "SELECT source_id, target_id FROM artist_similarity ORDER BY rowid ASC"
            ).fetchall()
            for edge in edge_rows:
                src = by_id.get(int(edge["source_id"]))
                dst = by_id.get(int(edge["target_id"]))
                if src is not None and dst is not None and src is not dst:
                    src.add_related(dst)

            return list(by_id.values())

    # --- Операції над графом схожості ---

    def add_similarity(self, source_name: str, target_name: str) -> None:
        """Зберігає спрямований зв'язок схожості `source -> target`."""
        if _norm_key(source_name) == _norm_key(target_name):
            raise ValueError("Виконавець не може бути схожим сам на себе")
        with self._connection() as conn:
            src_id = self._ensure_artist(conn, source_name)
            dst_id = self._ensure_artist(conn, target_name)
            conn.execute(
                "INSERT OR IGNORE INTO artist_similarity (source_id, target_id) VALUES (?, ?)",
                (src_id, dst_id),
            )

    def add_similarities(self, source_name: str, targets: Iterable[str]) -> None:
        """Пакетно зберігає зв'язки схожості від одного виконавця через `executemany`."""
        src_key = _norm_key(source_name)
        clean_targets = [t.strip() for t in targets if t.strip() and _norm_key(t) != src_key]
        if not clean_targets:
            return
        with self._connection() as conn:
            src_id = self._ensure_artist(conn, source_name)
            pairs = [(src_id, self._ensure_artist(conn, target)) for target in clean_targets]
            conn.executemany(
                "INSERT OR IGNORE INTO artist_similarity (source_id, target_id) VALUES (?, ?)",
                pairs,
            )

    def load_similarity_graph(self) -> Dict[str, List[str]]:
        """Завантажує граф схожості у вигляді словника `{source: [target, ...]}`."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a1.name AS source_name, a2.name AS target_name
                FROM artist_similarity s
                JOIN artists a1 ON a1.id = s.source_id
                JOIN artists a2 ON a2.id = s.target_id
                ORDER BY s.rowid ASC
                """
            ).fetchall()
            graph: Dict[str, List[str]] = {}
            for row in rows:
                targets = graph.setdefault(row["source_name"], [])
                if row["target_name"] not in targets:
                    targets.append(row["target_name"])
            return graph

    # --- Операції над треками (бібліотека та відкриття) ---

    def add_library_track(self, track: LibraryTrack, deduplicate: bool = False) -> int:
        """Зберігає трек у бібліотеці (`is_library = 1`) і повертає його `id`."""
        with self._connection() as conn:
            artist_id = self._ensure_artist(conn, track.artist)
            title_key = _norm_key(track.title)

            if deduplicate:
                existing = conn.execute(
                    """
                    SELECT id FROM tracks
                    WHERE artist_id = ? AND title_key = ? AND duration_sec = ? AND is_library = 1
                    LIMIT 1
                    """,
                    (artist_id, title_key, track.duration_sec),
                ).fetchone()
                if existing is not None:
                    conn.execute(
                        """
                        UPDATE tracks
                        SET title = ?, genre = ?, album_id = COALESCE(?, album_id),
                            mood = ?, rating = ?, last_played = ?
                        WHERE id = ?
                        """,
                        (
                            track.title,
                            track.genre,
                            track.album_id,
                            track.mood.value,
                            track.rating,
                            track.last_played.isoformat(),
                            existing["id"],
                        ),
                    )
                    return int(existing["id"])

            cursor = conn.execute(
                """
                INSERT INTO tracks (
                    artist_id, title, title_key, duration_sec, genre,
                    album_id, is_library, mood, rating, last_played
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    artist_id,
                    track.title,
                    title_key,
                    track.duration_sec,
                    track.genre,
                    track.album_id,
                    track.mood.value,
                    track.rating,
                    track.last_played.isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def add_library_tracks(self, tracks: Iterable[LibraryTrack], deduplicate: bool = True) -> List[int]:
        """Пакетне додавання треків до бібліотеки в одній транзакції."""
        ids: List[int] = []
        with self._connection() as conn:
            for track in tracks:
                artist_id = self._ensure_artist(conn, track.artist)
                title_key = _norm_key(track.title)
                if deduplicate:
                    existing = conn.execute(
                        """
                        SELECT id FROM tracks
                        WHERE artist_id = ? AND title_key = ? AND duration_sec = ? AND is_library = 1
                        LIMIT 1
                        """,
                        (artist_id, title_key, track.duration_sec),
                    ).fetchone()
                    if existing is not None:
                        ids.append(int(existing["id"]))
                        continue

                cursor = conn.execute(
                    """
                    INSERT INTO tracks (
                        artist_id, title, title_key, duration_sec, genre,
                        album_id, is_library, mood, rating, last_played
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        artist_id,
                        track.title,
                        title_key,
                        track.duration_sec,
                        track.genre,
                        track.album_id,
                        track.mood.value,
                        track.rating,
                        track.last_played.isoformat(),
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def add_discovery_tracks(self, tracks: Iterable[AudioTrack], deduplicate: bool = True) -> int:
        """Зберігає треки-відкриття (`is_library = 0`), повертає кількість нових записів."""
        added = 0
        with self._connection() as conn:
            for track in tracks:
                artist_id = self._ensure_artist(conn, track.artist)
                title_key = _norm_key(track.title)
                if deduplicate:
                    existing = conn.execute(
                        """
                        SELECT id FROM tracks
                        WHERE artist_id = ? AND title_key = ? AND duration_sec = ? AND is_library = 0
                        LIMIT 1
                        """,
                        (artist_id, title_key, track.duration_sec),
                    ).fetchone()
                    if existing is not None:
                        continue

                conn.execute(
                    """
                    INSERT INTO tracks (
                        artist_id, title, title_key, duration_sec, genre,
                        album_id, is_library, mood, rating, last_played
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL)
                    """,
                    (
                        artist_id,
                        track.title,
                        title_key,
                        track.duration_sec,
                        track.genre or "unknown",
                        track.album_id,
                    ),
                )
                added += 1
        return added

    def load_library_records(self) -> List[SavedTrackRecord]:
        """Завантажує треки бібліотеки разом з їхніми `id` у БД."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.title, a.name AS artist_name, t.duration_sec,
                       t.genre, t.mood, t.rating, t.last_played, t.album_id
                FROM tracks t
                JOIN artists a ON a.id = t.artist_id
                WHERE t.is_library = 1
                ORDER BY t.id ASC
                """
            ).fetchall()
            records: List[SavedTrackRecord] = []
            for row in rows:
                played = date.fromisoformat(row["last_played"]) if row["last_played"] else date.today()
                track = LibraryTrack(
                    title=row["title"],
                    artist=row["artist_name"],
                    duration_sec=int(row["duration_sec"]),
                    genre=row["genre"] or "unknown",
                    mood=row["mood"] or Mood.ENERGETIC.value,
                    rating=int(row["rating"] if row["rating"] is not None else 3),
                    last_played=played,
                    album_id=row["album_id"],
                )
                records.append(SavedTrackRecord(id=int(row["id"]), track=track))
            return records

    def load_library(self) -> List[LibraryTrack]:
        """Завантажує всі треки бібліотеки користувача."""
        return [record.track for record in self.load_library_records()]

    def load_discoveries(self) -> List[AudioTrack]:
        """Завантажує всі збережені треки-відкриття."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT t.title, a.name AS artist_name, t.duration_sec, t.genre, t.album_id
                FROM tracks t
                JOIN artists a ON a.id = t.artist_id
                WHERE t.is_library = 0
                ORDER BY t.id ASC
                """
            ).fetchall()
            return [
                AudioTrack(
                    title=row["title"],
                    artist=row["artist_name"],
                    duration_sec=int(row["duration_sec"]),
                    genre=row["genre"] or "unknown",
                    album_id=row["album_id"],
                )
                for row in rows
            ]

    def update_library_track_rating(self, identifier: int | str, rating: int) -> Optional[LibraryTrack]:
        """Оновлює оцінку треку (1..5) за 1-based номером у списку або за назвою."""
        if not 1 <= rating <= 5:
            raise ValueError("Оцінка має бути від 1 до 5")

        records = self.load_library_records()
        target_id: Optional[int] = None

        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            index = int(identifier)
            if 1 <= index <= len(records):
                target_id = records[index - 1].id
        else:
            needle = _norm_key(str(identifier))
            for rec in records:
                if _norm_key(rec.track.title) == needle:
                    target_id = rec.id
                    break

        if target_id is None:
            return None

        with self._connection() as conn:
            conn.execute(
                "UPDATE tracks SET rating = ? WHERE id = ? AND is_library = 1",
                (rating, target_id),
            )

        for rec in self.load_library_records():
            if rec.id == target_id:
                return rec.track
        return None

    def remove_library_track(self, identifier: int | str) -> Optional[LibraryTrack]:
        """Видаляє трек з бібліотеки за 1-based номером у списку або за назвою."""
        records = self.load_library_records()
        target: Optional[SavedTrackRecord] = None

        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            index = int(identifier)
            if 1 <= index <= len(records):
                target = records[index - 1]
        else:
            needle = _norm_key(str(identifier))
            for rec in records:
                if _norm_key(rec.track.title) == needle:
                    target = rec
                    break

        if target is None:
            return None

        with self._connection() as conn:
            conn.execute(
                "DELETE FROM tracks WHERE id = ? AND is_library = 1",
                (target.id,),
            )
        return target.track

    # --- Операції над рекомендаціями ---

    def save_recommendations(
        self,
        discovery_paths: Mapping[str, Tuple[str, ...]],
        explanations: Mapping[str, str],
    ) -> int:
        """Зберігає знайдені ланцюжки рекомендацій та їхні пояснення у таблицю `recommendations`."""
        if not discovery_paths:
            return 0
        saved = 0
        with self._connection() as conn:
            for artist_key, path in discovery_paths.items():
                if not path:
                    continue
                seed_id = self._ensure_artist(conn, path[0]) if len(path) >= 2 else None
                target_id = self._ensure_artist(conn, path[-1])
                path_text = " -> ".join(path)
                reason = explanations.get(artist_key, f"Рекомендовано: {path_text}")
                steps = max(1, len(path) - 1)
                conn.execute(
                    """
                    INSERT INTO recommendations (
                        seed_artist_id, recommended_artist_id, path_text, reason, steps
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(recommended_artist_id, path_text) DO UPDATE SET
                        seed_artist_id = excluded.seed_artist_id,
                        reason = excluded.reason,
                        steps = excluded.steps,
                        created_at = datetime('now')
                    """,
                    (seed_id, target_id, path_text, reason, steps),
                )
                saved += 1
        return saved

    def load_recommendations(self) -> List[SavedRecommendation]:
        """Повертає збережені рекомендації (від найновіших до старіших)."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT r.id, COALESCE(sa.name, '') AS seed_artist,
                       ra.name AS recommended_artist, r.path_text,
                       r.reason, r.steps, r.created_at
                FROM recommendations r
                LEFT JOIN artists sa ON sa.id = r.seed_artist_id
                JOIN artists ra ON ra.id = r.recommended_artist_id
                ORDER BY r.id DESC
                """
            ).fetchall()
            return [
                SavedRecommendation(
                    id=int(row["id"]),
                    seed_artist=row["seed_artist"],
                    recommended_artist=row["recommended_artist"],
                    path_text=row["path_text"],
                    reason=row["reason"],
                    steps=int(row["steps"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    # --- Операції над плейлистами ---

    def save_playlist(
        self,
        playlist: Playlist,
        target_minutes: int,
        mood: Optional[str],
        new_percent: int,
    ) -> int:
        """Зберігає згенерований плейлист і всі його треки з поясненнями у БД."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO playlists (
                    name, target_minutes, mood, new_percent, total_duration_sec
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    playlist.name,
                    target_minutes,
                    mood,
                    new_percent,
                    playlist.total_duration,
                ),
            )
            playlist_id = int(cursor.lastrowid)

            rows_to_insert: List[Tuple[object, ...]] = []
            for pos, track in enumerate(playlist.tracks, 1):
                title = getattr(track, "title", "")
                artist_name = getattr(track, "artist", "")
                duration_sec = int(getattr(track, "duration_sec", 0))
                genre = getattr(track, "genre", "unknown") or "unknown"
                track_mood = track.mood.value if isinstance(track, LibraryTrack) else None
                rating = track.rating if isinstance(track, LibraryTrack) else None
                explanation = playlist.get_explanation(artist_name) if artist_name else None
                track_id = (
                    self._find_matching_track_id(conn, artist_name, title, duration_sec)
                    if artist_name and duration_sec > 0
                    else None
                )
                rows_to_insert.append(
                    (
                        playlist_id,
                        pos,
                        track_id,
                        title,
                        artist_name,
                        duration_sec,
                        genre,
                        track_mood,
                        rating,
                        explanation,
                    )
                )

            if rows_to_insert:
                conn.executemany(
                    """
                    INSERT INTO playlist_tracks (
                        playlist_id, position, track_id, title, artist_name,
                        duration_sec, genre, mood, rating, explanation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )

            return playlist_id

    def list_playlists(self) -> List[SavedPlaylistSummary]:
        """Повертає перелік збережених плейлистів (від найновіших до старіших)."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.target_minutes, p.mood, p.new_percent,
                       p.total_duration_sec, p.created_at,
                       COUNT(pt.id) AS track_count
                FROM playlists p
                LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
                GROUP BY p.id
                ORDER BY p.id DESC
                """
            ).fetchall()
            return [
                SavedPlaylistSummary(
                    id=int(row["id"]),
                    name=row["name"],
                    target_minutes=int(row["target_minutes"]),
                    mood=row["mood"],
                    new_percent=int(row["new_percent"]),
                    total_duration_sec=int(row["total_duration_sec"]),
                    track_count=int(row["track_count"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def load_playlist(self, playlist_id: int) -> Optional[Tuple[SavedPlaylistSummary, Playlist]]:
        """Відновлює збережений плейлист разом із треками та поясненнями рекомендацій."""
        with self._connection() as conn:
            header = conn.execute(
                """
                SELECT p.id, p.name, p.target_minutes, p.mood, p.new_percent,
                       p.total_duration_sec, p.created_at,
                       COUNT(pt.id) AS track_count
                FROM playlists p
                LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
                WHERE p.id = ?
                GROUP BY p.id
                """,
                (playlist_id,),
            ).fetchone()
            if header is None:
                return None

            summary = SavedPlaylistSummary(
                id=int(header["id"]),
                name=header["name"],
                target_minutes=int(header["target_minutes"]),
                mood=header["mood"],
                new_percent=int(header["new_percent"]),
                total_duration_sec=int(header["total_duration_sec"]),
                track_count=int(header["track_count"]),
                created_at=header["created_at"],
            )

            track_rows = conn.execute(
                """
                SELECT title, artist_name, duration_sec, genre, mood, rating, explanation
                FROM playlist_tracks
                WHERE playlist_id = ?
                ORDER BY position ASC
                """,
                (playlist_id,),
            ).fetchall()

            playlist = Playlist(summary.name)
            for row in track_rows:
                if row["mood"] is not None and row["rating"] is not None:
                    track: AudioTrack = LibraryTrack(
                        title=row["title"],
                        artist=row["artist_name"],
                        duration_sec=int(row["duration_sec"]),
                        genre=row["genre"] or "unknown",
                        mood=row["mood"],
                        rating=int(row["rating"]),
                        last_played=date.today(),
                    )
                else:
                    track = AudioTrack(
                        title=row["title"],
                        artist=row["artist_name"],
                        duration_sec=int(row["duration_sec"]),
                        genre=row["genre"] or "unknown",
                    )
                playlist.add_track(track)
                if row["explanation"]:
                    playlist.set_explanation(row["artist_name"], row["explanation"])

            return summary, playlist

    # --- Службові методи ---

    def clear_all(self) -> None:
        """Повністю очищує всі таблиці бази даних (в межах однієї транзакції)."""
        with self._connection() as conn:
            conn.execute("DELETE FROM playlist_tracks")
            conn.execute("DELETE FROM playlists")
            conn.execute("DELETE FROM recommendations")
            conn.execute("DELETE FROM tracks")
            conn.execute("DELETE FROM artist_similarity")
            conn.execute("DELETE FROM artists")

    def get_stats(self) -> Dict[str, int | str]:
        """Повертає зведену статистику по всіх таблицях бази даних."""
        with self._connection() as conn:
            artists = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
            banned = conn.execute("SELECT COUNT(*) FROM artists WHERE banned = 1").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM artist_similarity").fetchone()[0]
            lib_tracks = conn.execute("SELECT COUNT(*) FROM tracks WHERE is_library = 1").fetchone()[0]
            disc_tracks = conn.execute("SELECT COUNT(*) FROM tracks WHERE is_library = 0").fetchone()[0]
            recs = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            playlists = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
            return {
                "db_path": self.db_path,
                "artists": int(artists),
                "banned_artists": int(banned),
                "similarity_edges": int(edges),
                "library_tracks": int(lib_tracks),
                "discovery_tracks": int(disc_tracks),
                "recommendations": int(recs),
                "playlists": int(playlists),
            }
