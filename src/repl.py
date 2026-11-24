"""Інтерактивний режим (REPL) Куратора плейлистів.

Запуск: `python -X utf8 src/main.py` (без аргументів) або `python -X utf8 src/main.py interactive`.

Стан сесії (колекція, відкриття, заборонені, граф схожості, рекомендації та плейлисти)
автоматично зберігається в локальній базі SQLite (`data/curator.db` за замовчуванням)
і відновлюється між запусками програми.
"""
import argparse
import shlex
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional

from core.formatting import format_duration
from generator import PlaylistGenerator
from logic.prolog_engine import PrologUnavailableError
from models import AudioTrack, LibraryTrack, Mood
from services.deezer import DeezerAPIClient
from storage import SQLiteStorage

PROMPT = "curator> "

HELP = """Команди:
  add TITLE ARTIST [--seconds S] [--mood M] [--rating 1-5] [--genre G]   додати трек у колекцію
  list [--discoveries]                    показати колекцію, відкриття, заборонених і статистику БД
  discoveries [--artist NAME] [--limit N] показати список треків-відкриттів (з фільтром/лімітом)
  rate TARGET RATING                      змінити оцінку треку (1-5) за номером або назвою
  remove TARGET                           видалити трек з колекції за номером або назвою
  import ARTIST [--limit 10] [--mood M] [--genre G]   завантажити топ-треки з Deezer
  discover ARTIST [--artists 5] [--tracks 3]   завантажити треки схожих виконавців (відкриття)
  relate ARTIST1 ARTIST2                  додати зв'язок схожості для графа Prolog
  ban ARTIST / unban ARTIST               заборонити / дозволити виконавця
  search QUERY [--limit 3]                пошук треків у Deezer
  generate [--minutes 30] [--mood M] [--new-percent 30] [--name TITLE]   згенерувати і зберегти плейлист
  playlists                               показати збережені в SQLite плейлисти
  show ID                                 показати збережений плейлист за номером ID
  recommendations (recs)                  показати збережені ланцюжки рекомендацій
  stats (db)                              показати шлях до БД SQLite та кількість записів
  clear                                   очистити всю базу даних SQLite і поточну сесію
  help                                    ця довідка
  quit | exit                             вийти
Значення з пробілами беріть у лапки: add "Song 2" Blur
Настрої: """ + ", ".join(m.value for m in Mood) + " (або: energetic, calm, happy, sad, focused)"


def format_discoveries_lines(
    discoveries: list[AudioTrack] | tuple[AudioTrack, ...],
    artist: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[str]:
    """Форматує список треків-відкриттів з опційним фільтром за виконавцем і лімітом."""
    if limit is not None and limit <= 0:
        raise ValueError("Ліміт має бути додатним")

    filtered = list(discoveries)
    if artist is not None:
        needle = artist.strip().casefold()
        filtered = [t for t in filtered if needle in t.artist.strip().casefold()]

    header = f"Відкриття ({len(filtered)}" + (f", фільтр: '{artist.strip()}'" if artist else "") + "):"
    lines = [header]
    shown = filtered[:limit] if limit is not None else filtered
    for i, track in enumerate(shown, 1):
        genre_suffix = f" | Жанр: {track.genre}" if track.genre and track.genre != "unknown" else ""
        lines.append(f"  {i}. {track.get_details()}{genre_suffix}")
    if not shown:
        lines.append("  (порожньо)")
    elif limit is not None and len(filtered) > limit:
        lines.append(f"  ... показано {len(shown)} з {len(filtered)}")
    return lines


class ReplError(Exception):
    """Помилка користувацької команди (показується без аварійного завершення)."""


class _Parser(argparse.ArgumentParser):
    """ArgumentParser, що кидає ReplError замість завершення програми."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)

    def error(self, message):
        raise ReplError(message)


def _parser(name: str) -> _Parser:
    return _Parser(prog=name)


class Session:
    """Стан REPL та виконання команд із постійним збереженням у SQLite."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        storage: Optional[SQLiteStorage] = None,
    ):
        self.storage = storage or SQLiteStorage(db_path)
        self.library: list[LibraryTrack] = []
        self.discoveries: list[AudioTrack] = []
        self.banned: Dict[str, str] = {}  # нижній регістр -> оригінальна назва
        self.similarity_graph: Dict[str, list[str]] = {}
        self.running = True
        self._commands: Dict[str, Callable[[list[str]], str]] = {
            "help": self._help,
            "add": self._add,
            "list": self._list,
            "rate": self._rate,
            "remove": self._remove,
            "import": self._import,
            "discover": self._discover,
            "discoveries": self._discoveries_cmd,
            "relate": self._relate,
            "ban": self._ban,
            "unban": self._unban,
            "search": self._search,
            "generate": self._generate,
            "playlists": self._playlists,
            "show": self._show,
            "recommendations": self._recommendations,
            "recs": self._recommendations,
            "stats": self._stats,
            "db": self._stats,
            "clear": self._clear,
            "quit": self._quit,
            "exit": self._quit,
        }
        self._sync_from_storage()

    def _sync_from_storage(self) -> None:
        """Синхронізує кеш сесії в пам'яті зі станом у SQLite."""
        self.library = self.storage.load_library()
        self.discoveries = self.storage.load_discoveries()
        self.banned = self.storage.load_banned_artists()
        self.similarity_graph = self.storage.load_similarity_graph()

    def execute(self, line: str) -> str:
        try:
            parts = shlex.split(line)
        except ValueError as e:
            raise ReplError(f"Некоректні лапки: {e}")
        if not parts:
            return ""
        handler = self._commands.get(parts[0].lower())
        if handler is None:
            raise ReplError(f"Невідома команда '{parts[0]}'. Введіть help.")
        try:
            return handler(parts[1:])
        except ValueError as e:  # помилки валідації моделі та генератора
            raise ReplError(str(e))

    # --- команди ---

    def _help(self, args):
        return HELP

    def _quit(self, args):
        self.running = False
        return "До зустрічі!"

    def _add(self, args):
        p = _parser("add")
        p.add_argument("title")
        p.add_argument("artist")
        p.add_argument("pos_seconds", nargs="?", type=int, default=None)
        p.add_argument("--seconds", "-s", type=int, default=None)
        p.add_argument("--mood", default=Mood.ENERGETIC.value)
        p.add_argument("--rating", type=int, default=3)
        p.add_argument("--genre", default="unknown")
        a = p.parse_args(args)

        seconds = a.seconds if a.seconds is not None else a.pos_seconds
        if seconds is not None and seconds <= 0:
            raise ReplError("Тривалість має бути додатною")

        matched = DeezerAPIClient.resolve_track(a.title, a.artist, seconds=seconds)
        genre = a.genre if a.genre != "unknown" else (matched.genre or "unknown")
        track = LibraryTrack(
            matched.title, matched.artist, matched.duration_sec,
            genre, a.mood, a.rating, date.today(), album_id=matched.album_id
        )
        self.storage.add_library_track(track)
        self._sync_from_storage()
        return f"Додано: {track.get_details()}"

    def _list(self, args):
        p = _parser("list")
        p.add_argument("--discoveries", action="store_true")
        a = p.parse_args(args)
        stats = self.storage.get_stats()
        lines = [f"Колекція ({len(self.library)}):"]
        lines += [f"  {i}. {t.get_details()}" for i, t in enumerate(self.library, 1)] or ["  (порожньо)"]
        if a.discoveries:
            lines.extend(format_discoveries_lines(self.discoveries))
        else:
            lines.append(f"Відкриттів: {len(self.discoveries)}")
        lines.append("Заборонені: " + (", ".join(self.banned.values()) or "немає"))
        lines.append(
            f"Зв'язків схожості: {stats['similarity_edges']} | "
            f"Збережених плейлистів: {stats['playlists']} | "
            f"Рекомендацій: {stats['recommendations']}"
        )
        return "\n".join(lines)

    def _discoveries_cmd(self, args):
        p = _parser("discoveries")
        p.add_argument("--artist", default=None)
        p.add_argument("--limit", type=int, default=None)
        a = p.parse_args(args)
        return "\n".join(format_discoveries_lines(self.discoveries, artist=a.artist, limit=a.limit))

    def _rate(self, args):
        p = _parser("rate")
        p.add_argument("target")
        p.add_argument("rating", type=int)
        a = p.parse_args(args)
        updated = self.storage.update_library_track_rating(a.target, a.rating)
        if updated is None:
            raise ReplError(f"Трек '{a.target}' не знайдено в колекції.")
        self._sync_from_storage()
        return f"Оновлено оцінку: {updated.get_details()}"

    def _remove(self, args):
        p = _parser("remove")
        p.add_argument("target")
        a = p.parse_args(args)
        removed = self.storage.remove_library_track(a.target)
        if removed is None:
            raise ReplError(f"Трек '{a.target}' не знайдено в колекції.")
        self._sync_from_storage()
        return f"Видалено: {removed.get_details()}"

    def _import(self, args):
        p = _parser("import")
        p.add_argument("artist")
        p.add_argument("--limit", type=int, default=10)
        p.add_argument("--mood", default=Mood.ENERGETIC.value)
        p.add_argument("--genre", default=None)
        a = p.parse_args(args)
        mood = Mood.parse(a.mood)
        seed = DeezerAPIClient.search_artist(a.artist)
        if seed is None:
            raise ReplError(f"Виконавця '{a.artist}' не знайдено (або немає інтернету).")
        self.storage.upsert_artist(seed.name, deezer_id=seed.deezer_id)
        long_ago = date.today() - timedelta(days=30)
        tracks = DeezerAPIClient.top_tracks(seed, limit=a.limit)
        library_tracks = [
            LibraryTrack(
                t.title,
                t.artist,
                t.duration_sec,
                a.genre or t.genre or "unknown",
                mood,
                3,
                long_ago,
                album_id=t.album_id,
            )
            for t in tracks
        ]
        self.storage.add_library_tracks(library_tracks, deduplicate=True)
        self._sync_from_storage()
        return f"Імпортовано {len(tracks)} треків виконавця {seed.name}."

    def _discover(self, args):
        p = _parser("discover")
        p.add_argument("artist")
        p.add_argument("--artists", type=int, default=5)
        p.add_argument("--tracks", type=int, default=3)
        a = p.parse_args(args)
        seed = DeezerAPIClient.search_artist(a.artist)
        if seed is None:
            raise ReplError(f"Виконавця '{a.artist}' не знайдено (або немає інтернету).")
        self.storage.upsert_artist(seed.name, deezer_id=seed.deezer_id)
        related = DeezerAPIClient.related_artists(seed, limit=a.artists)
        for r in related:
            self.storage.upsert_artist(r.name, deezer_id=r.deezer_id)
        self.storage.add_similarities(seed.name, [r.name for r in related])

        fetched_tracks: list[AudioTrack] = []
        for artist in related:
            fetched_tracks.extend(DeezerAPIClient.top_tracks(artist, limit=a.tracks))
        added = self.storage.add_discovery_tracks(fetched_tracks, deduplicate=True)
        self._sync_from_storage()

        names = ", ".join(r.name for r in related) or "немає"
        return f"Схожі на {seed.name}: {names}. Додано {added} треків-відкриттів."

    def _relate(self, args):
        p = _parser("relate")
        p.add_argument("source")
        p.add_argument("target")
        a = p.parse_args(args)
        source_name = a.source.strip()
        target_name = a.target.strip()
        self.storage.add_similarity(source_name, target_name)
        self._sync_from_storage()
        return f"Додано зв'язок схожості: {source_name} -> {target_name}"

    def _ban(self, args):
        if not args:
            raise ReplError("Вкажіть виконавця: ban ARTIST")
        name = " ".join(args).strip()
        self.storage.set_artist_banned(name, True)
        self._sync_from_storage()
        return f"Заборонено: {name}"

    def _unban(self, args):
        if not args:
            raise ReplError("Вкажіть виконавця: unban ARTIST")
        name = " ".join(args).strip()
        if name.casefold() not in self.banned:
            raise ReplError(f"'{name}' немає серед заборонених")
        self.storage.set_artist_banned(name, False)
        self._sync_from_storage()
        return f"Дозволено: {name}"

    def _search(self, args):
        p = _parser("search")
        p.add_argument("query", nargs="+")
        p.add_argument("--limit", type=int, default=3)
        a = p.parse_args(args)
        tracks = DeezerAPIClient.search_tracks(" ".join(a.query), limit=a.limit)
        if not tracks:
            raise ReplError("Нічого не знайдено (або немає інтернету).")
        return "\n".join(t.get_details() for t in tracks)

    def _generate(self, args):
        p = _parser("generate")
        p.add_argument("--minutes", type=int, default=30)
        p.add_argument("--mood", default=None)
        p.add_argument("--new-percent", type=int, default=30)
        p.add_argument("--name", default="Smart Playlist")
        a = p.parse_args(args)
        if not self.library:
            raise ReplError("Колекція порожня: додайте треки (add) або імпортуйте (import).")
        generator = PlaylistGenerator(
            self.library,
            self.discoveries,
            banned_artists=self.banned.values(),
            similarity_graph=self.similarity_graph,
        )
        try:
            playlist = generator.generate(
                a.minutes,
                mood=a.mood,
                new_percent=a.new_percent,
                name=a.name,
            )
        except PrologUnavailableError as e:
            raise ReplError(str(e))

        if generator.last_prolog_plan and generator.last_prolog_plan.discovery_paths:
            self.storage.save_recommendations(
                generator.last_prolog_plan.discovery_paths,
                generator.last_prolog_plan.explanations,
            )

        mood_label = Mood.parse(a.mood).value if a.mood is not None else None
        playlist_id = self.storage.save_playlist(
            playlist,
            target_minutes=a.minutes,
            mood=mood_label,
            new_percent=a.new_percent,
        )

        mins, secs = divmod(playlist.total_duration, 60)
        return (
            f"{playlist}\n"
            f"Разом: {mins}:{secs:02d} (ціль: {a.minutes}:00)\n"
            f"[Збережено плейлист #{playlist_id} у SQLite]"
        )

    def _playlists(self, args):
        items = self.storage.list_playlists()
        if not items:
            return "Збережених плейлистів ще немає."
        lines = [f"Збережені плейлисти ({len(items)}):"]
        for item in items:
            dur = format_duration(item.total_duration_sec)
            mood_info = item.mood or "будь-який"
            lines.append(
                f"  #{item.id} | {item.name} | {item.track_count} треків ({dur}, "
                f"ціль {item.target_minutes} хв, настрій: {mood_info}, нові: {item.new_percent}%) | {item.created_at}"
            )
        return "\n".join(lines)

    def _show(self, args):
        p = _parser("show")
        p.add_argument("playlist_id", type=int)
        a = p.parse_args(args)
        loaded = self.storage.load_playlist(a.playlist_id)
        if loaded is None:
            raise ReplError(f"Плейлист #{a.playlist_id} не знайдено.")
        summary, playlist = loaded
        dur = format_duration(playlist.total_duration)
        return (
            f"{playlist}\n"
            f"Разом: {dur} (ціль: {summary.target_minutes}:00 | збережено: {summary.created_at})"
        )

    def _recommendations(self, args):
        recs = self.storage.load_recommendations()
        if not recs:
            return "Збережених рекомендацій ще немає."
        lines = [f"Збережені рекомендації ({len(recs)}):"]
        for rec in recs:
            lines.append(f"  #{rec.id} [{rec.steps} кр.] {rec.recommended_artist}: {rec.reason} ({rec.created_at})")
        return "\n".join(lines)

    def _stats(self, args):
        s = self.storage.get_stats()
        return (
            f"База даних SQLite: {s['db_path']}\n"
            f"  Виконавців: {s['artists']} (заборонено: {s['banned_artists']})\n"
            f"  Зв'язків схожості: {s['similarity_edges']}\n"
            f"  Треків у бібліотеці: {s['library_tracks']}\n"
            f"  Треків-відкриттів: {s['discovery_tracks']}\n"
            f"  Рекомендацій: {s['recommendations']}\n"
            f"  Плейлистів: {s['playlists']}"
        )

    def _clear(self, args):
        self.storage.clear_all()
        self._sync_from_storage()
        return "Сесію та базу даних SQLite очищено."


def run(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    db_path: Optional[str | Path] = None,
) -> int:
    """Основний цикл: читає команду, виконує, друкує результат, доки не буде quit/exit або Ctrl+D/Ctrl+C."""
    session = Session(db_path=db_path)
    output_fn("Куратор плейлистів. Введіть help для списку команд.")
    while session.running:
        try:
            line = input_fn(PROMPT)
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            break
        try:
            result = session.execute(line)
        except ReplError as e:
            result = f"[Помилка] {e}"
        if result:
            output_fn(result)
    return 0
