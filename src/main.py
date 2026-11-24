"""CLI Куратора плейлистів (demo).

Приклади (з кореня репозиторію):
    python -X utf8 src/main.py                 # інтерактивний режим (REPL) із збереженням в SQLite
    python -X utf8 src/main.py search "lady gaga"
    python -X utf8 src/main.py generate "Blur" --minutes 30 --mood енергійний --new-percent 30
    python -X utf8 src/main.py generate "Blur" --offline --minutes 15
    python -X utf8 src/main.py library
    python -X utf8 src/main.py playlists
    python -X utf8 src/main.py playlists --id 1
    python -X utf8 src/main.py recommendations
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import repl
from core.formatting import format_duration
from generator import PlaylistGenerator
from logic.prolog_engine import PrologUnavailableError
from models import LibraryTrack, Mood
from services.deezer import DeezerAPIClient
from storage import SQLiteStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="playlist_curator", description="Куратор плейлистів (Deezer + SQLite)")
    parser.add_argument("--db", default=None, help="шлях до файлу SQLite БД (за замовчуванням data/curator.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("interactive", help="інтерактивний режим (REPL); також запускається без аргументів")

    search = sub.add_parser("search", help="знайти треки за запитом")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=3)

    gen = sub.add_parser("generate", help="згенерувати плейлист і зберегти в SQLite")
    gen.add_argument("artist", help="улюблений виконавець (джерело 'бібліотеки')")
    gen.add_argument("--minutes", type=int, default=30, help="цільова тривалість, хв")
    gen.add_argument("--mood", default="енергійний", choices=list(Mood.aliases().keys()))
    gen.add_argument("--new-percent", type=int, default=30, help="частка нових виконавців, %%")
    gen.add_argument("--ban", action="append", default=[], metavar="ARTIST", help="заборонений виконавець (можна кілька)")
    gen.add_argument("--offline", action="store_true", help="генерувати з уже збереженої бази SQLite без Deezer")

    lib = sub.add_parser("library", help="показати збережену колекцію треків, виконавців та заборони з SQLite")
    lib.add_argument("--discoveries", action="store_true", help="показати також перелік треків-відкриттів")

    disc = sub.add_parser("discoveries", help="показати збережені треки-відкриття з SQLite")
    disc.add_argument("--artist", default=None, help="фільтр за виконавцем")
    disc.add_argument("--limit", type=int, default=None, help="максимум треків для виводу")

    pls = sub.add_parser("playlists", help="показати збережені плейлисти з SQLite")
    pls.add_argument("--id", type=int, default=None, help="показати детальний склад плейлиста за ID")

    sub.add_parser("recommendations", help="показати збережені рекомендації та шляхи схожості з SQLite")
    return parser


def cmd_search(query: str, limit: int) -> int:
    tracks = DeezerAPIClient.search_tracks(query, limit=limit)
    if not tracks:
        print("Не вдалося завантажити треки. Перевірте підключення до інтернету.")
        return 1
    for track in tracks:
        print(track.get_details())
    return 0


def cmd_generate(
    artist_name: str,
    minutes: int,
    mood: str,
    new_percent: int,
    banned: List[str],
    db_path: Optional[str] = None,
    offline: bool = False,
) -> int:
    parsed_mood = Mood.parse(mood).value
    storage = SQLiteStorage(db_path)

    for b in banned:
        storage.set_artist_banned(b, True)

    if offline:
        library = storage.load_library()
        discoveries = storage.load_discoveries()
        similarity_graph = storage.load_similarity_graph()
        all_banned = list(storage.load_banned_artists().values())
        if not library:
            print("Локальна база SQLite порожня. Додайте треки через REPL або запустіть без --offline.")
            return 1
        playlist_name = f"На основі {artist_name} (SQLite)"
    else:
        seed = DeezerAPIClient.search_artist(artist_name)
        if seed is None:
            print(f"Виконавця '{artist_name}' не знайдено (або немає з'єднання з інтернетом).")
            return 1

        storage.upsert_artist(seed.name, deezer_id=seed.deezer_id)
        long_ago = date.today() - timedelta(days=30)
        library = [
            LibraryTrack(
                t.title,
                t.artist,
                t.duration_sec,
                t.genre or "unknown",
                parsed_mood,
                3,
                long_ago,
                album_id=t.album_id,
            )
            for t in DeezerAPIClient.top_tracks(seed, limit=10)
        ]
        storage.add_library_tracks(library, deduplicate=True)

        discoveries = []
        related_list = DeezerAPIClient.related_artists(seed, limit=5)
        for related in related_list:
            storage.upsert_artist(related.name, deezer_id=related.deezer_id)
            discoveries.extend(DeezerAPIClient.top_tracks(related, limit=3))
        storage.add_similarities(seed.name, [r.name for r in related_list])
        storage.add_discovery_tracks(discoveries, deduplicate=True)

        similarity_graph = storage.load_similarity_graph()
        all_banned = list(storage.load_banned_artists().values())
        playlist_name = f"На основі {seed.name}"

    generator = PlaylistGenerator(
        library,
        discoveries,
        banned_artists=all_banned,
        similarity_graph=similarity_graph,
    )
    try:
        playlist = generator.generate(
            minutes,
            mood=parsed_mood,
            new_percent=new_percent,
            name=playlist_name,
        )
    except ValueError as e:
        print(f"[Помилка параметрів] {e}")
        return 2
    except PrologUnavailableError as e:
        print(f"[Помилка Prolog] {e}")
        return 3

    if generator.last_prolog_plan and generator.last_prolog_plan.discovery_paths:
        storage.save_recommendations(
            generator.last_prolog_plan.discovery_paths,
            generator.last_prolog_plan.explanations,
        )
    playlist_id = storage.save_playlist(
        playlist,
        target_minutes=minutes,
        mood=parsed_mood,
        new_percent=new_percent,
    )

    print(playlist)
    mins, secs = divmod(playlist.total_duration, 60)
    print(f"Разом: {mins}:{secs:02d} (ціль: {minutes}:00)")
    print(f"[Збережено плейлист #{playlist_id} у SQLite: {storage.db_path}]")
    return 0


def cmd_library(db_path: Optional[str] = None, show_discoveries: bool = False) -> int:
    storage = SQLiteStorage(db_path)
    library = storage.load_library()
    discoveries = storage.load_discoveries()
    banned = storage.load_banned_artists()
    graph = storage.load_similarity_graph()
    print(f"База даних: {storage.db_path}")
    print(f"Колекція ({len(library)}):")
    for i, track in enumerate(library, 1):
        print(f"  {i}. {track.get_details()}")
    if not library:
        print("  (порожньо)")
    if show_discoveries:
        for line in repl.format_discoveries_lines(discoveries):
            print(line)
    else:
        print(f"Відкриттів: {len(discoveries)}")
    print("Заборонені: " + (", ".join(banned.values()) or "немає"))
    print(f"Зв'язків схожості: {sum(len(v) for v in graph.values())}")
    return 0


def cmd_discoveries(
    artist: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> int:
    storage = SQLiteStorage(db_path)
    discoveries = storage.load_discoveries()
    try:
        lines = repl.format_discoveries_lines(discoveries, artist=artist, limit=limit)
    except ValueError as e:
        print(f"[Помилка параметрів] {e}")
        return 2
    for line in lines:
        print(line)
    return 0


def cmd_playlists(playlist_id: Optional[int], db_path: Optional[str] = None) -> int:
    storage = SQLiteStorage(db_path)
    if playlist_id is not None:
        loaded = storage.load_playlist(playlist_id)
        if loaded is None:
            print(f"Плейлист #{playlist_id} не знайдено у {storage.db_path}.")
            return 1
        summary, playlist = loaded
        print(playlist)
        print(f"Разом: {format_duration(playlist.total_duration)} (ціль: {summary.target_minutes}:00 | {summary.created_at})")
        return 0

    items = storage.list_playlists()
    if not items:
        print("Збережених плейлистів ще немає.")
        return 0
    print(f"Збережені плейлисти ({len(items)}):")
    for item in items:
        dur = format_duration(item.total_duration_sec)
        print(f"  #{item.id} | {item.name} | {item.track_count} треків ({dur}) | {item.created_at}")
    return 0


def cmd_recommendations(db_path: Optional[str] = None) -> int:
    storage = SQLiteStorage(db_path)
    recs = storage.load_recommendations()
    if not recs:
        print("Збережених рекомендацій ще немає.")
        return 0
    print(f"Збережені рекомендації ({len(recs)}):")
    for rec in recs:
        print(f"  #{rec.id} [{rec.steps} кр.] {rec.recommended_artist}: {rec.reason} ({rec.created_at})")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return repl.run()
    args = build_parser().parse_args(argv)
    if args.command == "interactive":
        return repl.run(db_path=args.db) if args.db is not None else repl.run()
    if args.command == "search":
        return cmd_search(args.query, args.limit)
    if args.command == "library":
        return cmd_library(db_path=args.db, show_discoveries=args.discoveries)
    if args.command == "discoveries":
        return cmd_discoveries(artist=args.artist, limit=args.limit, db_path=args.db)
    if args.command == "playlists":
        return cmd_playlists(args.id, db_path=args.db)
    if args.command == "recommendations":
        return cmd_recommendations(db_path=args.db)
    return cmd_generate(
        args.artist,
        args.minutes,
        args.mood,
        args.new_percent,
        args.ban,
        db_path=args.db,
        offline=args.offline,
    )


def _configure_utf8_streams() -> None:
    """Налаштовує UTF-8 для консольного виводу на Windows, навіть без прапора -X utf8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    _configure_utf8_streams()
    raise SystemExit(main())
