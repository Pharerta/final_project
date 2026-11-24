"""Точка запуску демонстрації (CLI)

Запуск з кореня репозиторію:
    python -X utf8 src/demo.py              # офлайн-демо (ООП -> Ядро -> Prolog -> SQLite E7)
    python -X utf8 src/demo.py --online     # + пошук треків через Deezer API
    python -X utf8 src/demo.py --online --query "lady gaga"
"""
import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from generator import PlaylistGenerator
from logic.prolog_engine import PrologUnavailableError
from models import Artist, AudioTrack, LibraryTrack, Mood, Playlist
from services.deezer import DeezerAPIClient
from storage import SQLiteStorage


def demo_polymorphism() -> Playlist:
    print("\n1. Поліморфізм та наслідування (делегування в ядро)")
    playlist = Playlist("Ранкова пробіжка")
    playlist.add_track(AudioTrack("Vidchuttia", "Okean Elzy", 245))
    playlist.add_track(
        LibraryTrack("Feel Good Inc.", "Gorillaz", 222, "alternative", "енергійний", 5, date(2026, 10, 1))
    )
    playlist.show_playlist()

    long_tracks = playlist.filter_tracks(lambda t: t.duration_sec > 230)
    print(f"Відфільтровано треки > 230с (функція вищого порядку filter_by): {[t.title for t in long_tracks.tracks]}")
    return playlist


def demo_encapsulation() -> None:
    print("\n2. Інкапсуляція: валідація оцінки")
    track = LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 4, date(2026, 9, 15))
    print(f"Початкова оцінка: {track.rating}")
    try:
        track.rating = 7
    except ValueError as e:
        print(f"[Очікувана помилка] {e}")
    print(f"Оцінка після спроби: {track.rating}")


def demo_artists() -> None:
    print("\n3. Виконавці, граф схожості та рекурсія")
    blur = Artist("Blur")
    gorillaz = Artist("Gorillaz")
    blur.add_related(gorillaz)
    pulp = Artist("Pulp")
    gorillaz.add_related(pulp)
    gorillaz.add_related(Artist("Banned Band", banned=True))
    for artist in (blur, gorillaz):
        print(f"{artist.name} -> {[a.name for a in artist.related]}")
    print(f"Заборонені серед схожих на Gorillaz: {[a.name for a in gorillaz.related if a.banned]}")

    explanation = blur.explain_path_to(pulp)
    print(f"Пояснення рекомендації (чиста рекурсія ядра): {explanation}")

    print(f"Настрої: {[m.value for m in Mood]}")
    try:
        Mood.parse("нудний")
    except ValueError as e:
        print(f"[Очікувана помилка] {e}")


def demo_generator() -> None:
    print("\n4. Генератор плейлиста (наскрізний шлях: ООП -> Функціональне ядро -> Prolog)")
    library = [
        LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 4, date(2026, 9, 15)),
        LibraryTrack("Parklife", "Blur", 185, "britpop", "енергійний", 5, date(2026, 9, 20)),
        LibraryTrack("Feel Good Inc.", "Gorillaz", 222, "alternative", "енергійний", 5, date(2026, 10, 1)),
        LibraryTrack("Clint Eastwood", "Gorillaz", 340, "alternative", "спокійний", 4, date(2026, 8, 1)),
        LibraryTrack("Boombastic", "Shaggy", 245, "reggae", "енергійний", 2, date(2026, 10, 10)),
    ]
    discoveries = [
        AudioTrack("Common People", "Pulp", 350),
        AudioTrack("Bad Song", "Banned Band", 200),
        AudioTrack("Trash", "Suede", 240),  # досяжний лише через Banned Band — Prolog має відфільтрувати
    ]
    similarity_graph = {
        "Blur": ["Gorillaz", "Blur"],
        "Gorillaz": ["Pulp", "Banned Band"],
        "Banned Band": ["Suede"],
    }
    generator = PlaylistGenerator(
        library,
        discoveries,
        banned_artists=["Banned Band", "Shaggy"],
        similarity_graph=similarity_graph,
    )
    try:
        playlist = generator.generate(
            duration_min=15,
            mood="енергійний",
            new_percent=40,
            today=date(2026, 10, 20),
            name="Енергійна підбірка",
        )
    except PrologUnavailableError as e:
        print(f"[Prolog недоступний] {e}")
        return

    if generator.last_prolog_plan is not None:
        plan = generator.last_prolog_plan
        print(
            f"[Prolog] Передано фактів: {plan.facts_count} | "
            f"Шляхи відкриттів: {dict(plan.discovery_paths)} | "
            f"Валідація сусідства (valid_track_sequence): {plan.is_sequence_valid}"
        )
    playlist.show_playlist()
    mins, secs = divmod(playlist.total_duration, 60)
    print(f"Разом: {mins}:{secs:02d} (ціль: 15:00)")


def demo_sqlite_persistence() -> None:
    print("\n5. Постійне сховище SQLite (розширення E7 — збереження між запусками)")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "demo_curator.db"

        # Сесія 1: запис виконавців, заборон, графа, треків, рекомендацій і плейлиста
        store_s1 = SQLiteStorage(db_file)
        store_s1.add_library_track(
            LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 5, date(2026, 10, 20))
        )
        store_s1.add_discovery_tracks([AudioTrack("Common People", "Pulp", 350)])
        store_s1.add_similarities("Blur", ["Gorillaz"])
        store_s1.add_similarities("Gorillaz", ["Pulp"])
        store_s1.set_artist_banned("Banned Band", True)
        store_s1.save_recommendations(
            {"pulp": ("Blur", "Gorillaz", "Pulp")},
            {"pulp": "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp"},
        )
        pl = Playlist("Збережена добірка")
        pl.add_track(LibraryTrack("Song 2", "Blur", 122, "britpop", "енергійний", 5, date(2026, 10, 20)))
        pl.add_track(AudioTrack("Common People", "Pulp", 350))
        pl.set_explanation("Pulp", "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp")
        pl_id = store_s1.save_playlist(pl, target_minutes=15, mood="енергійний", new_percent=40)
        del store_s1

        # Сесія 2: нове підключення до того самого файлу БД (імітація перезапуску програми)
        store_s2 = SQLiteStorage(db_file)
        stats = store_s2.get_stats()
        loaded = store_s2.load_playlist(pl_id)
        recs = store_s2.load_recommendations()
        print(
            f"[Сесія 2] Відновлено з SQLite: бібліотека={stats['library_tracks']}, "
            f"відкриттів={stats['discovery_tracks']}, заборонено={stats['banned_artists']}, "
            f"рекомендацій={stats['recommendations']}, плейлистів={stats['playlists']}"
        )
        if recs:
            print(f"[Сесія 2] Збережена рекомендація: {recs[0].reason}")
        if loaded is not None:
            _, restored_playlist = loaded
            restored_playlist.show_playlist()


def demo_deezer(query: str) -> None:
    print("\n6. Інтеграція з Deezer API")
    tracks = DeezerAPIClient.search_tracks(query, limit=3)
    if not tracks:
        print("Не вдалося завантажити треки. Перевірте підключення до інтернету.")
        return
    playlist = Playlist(f"Deezer: {query}")
    for track in tracks:
        playlist.add_track(track)
    playlist.show_playlist()


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо Playlist Curator")
    parser.add_argument("--online", action="store_true", help="додати демо з Deezer API")
    parser.add_argument("--query", default="okean elzy", help="пошуковий запит для Deezer")
    args = parser.parse_args()

    demo_polymorphism()
    demo_encapsulation()
    demo_artists()
    demo_generator()
    demo_sqlite_persistence()
    if args.online:
        demo_deezer(args.query)


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
    main()
