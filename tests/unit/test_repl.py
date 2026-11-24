import sys
from pathlib import Path

# Дозволяє запускати файл напряму (не лише через pytest): додаємо src/ до шляху імпорту
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

import repl
from models import Artist, AudioTrack
from repl import ReplError, Session

pytestmark = pytest.mark.usefixtures("prolog_unit_fallback")


@pytest.fixture(autouse=True)
def mock_deezer_catalog(monkeypatch):
    """Детермінований мок Deezer для юніт-тестів."""
    catalog = {
        ("blur", "song 2"): [
            AudioTrack("Song 2", "Blur", 121, genre="Rock"),
            AudioTrack("Song 2 (Live)", "Blur", 170, genre="Rock"),
        ],
        ("queen", "bohemian rhapsody"): [
            AudioTrack("Bohemian Rhapsody", "Queen", 354, genre="Rock"),
            AudioTrack("Bohemian Rhapsody", "Queen", 334, genre="Rock"),
            AudioTrack("Bohemian Rhapsody", "Queen", 317, genre="Rock"),
        ],
    }

    def fake_search_tracks(query: str, limit: int = 30):
        q = query.lower()
        res = []
        for (artist, title), tracks in catalog.items():
            if artist in q or title in q:
                res.extend(tracks)
        # Допоміжний випадок для тестових треків
        if "good" in q:
            res.append(AudioTrack("Good Track", "Good", 180, genre="Pop"))
        if "banned" in q:
            res.append(AudioTrack("Bad", "Banned", 180, genre="Pop"))
        return res

    monkeypatch.setattr("repl.DeezerAPIClient.search_tracks", fake_search_tracks)
    return catalog


@pytest.fixture
def session():
    return Session()


def test_add_and_list(session):
    assert "Додано" in session.execute('add "Song 2" Blur --seconds 121 --mood спокійний --rating 4')
    out = session.execute("list")
    assert "Колекція (1)" in out and "'Song 2' — Blur (2:01)" in out and "спокійний" in out and "Жанр: Rock" in out


def test_add_pulls_genre_from_deezer_automatically(session):
    # Коли genre не вказано користувачем, він автоматично підтягується з Deezer
    session.execute('add "Song 2" Blur')
    out = session.execute("list")
    assert "Жанр: Rock" in out


def test_add_respects_custom_genre_override(session):
    # Користувацький жанр має пріоритет над жанром з Deezer
    session.execute('add "Song 2" Blur --genre Britpop')
    out = session.execute("list")
    assert "Жанр: Britpop" in out


def test_add_accepts_english_mood(session):
    # Підтримка стандартних англомовних настроїв (energetic, calm, happy, sad, focused)
    session.execute('add "Song 2" Blur --mood energetic')
    out = session.execute("list")
    assert "енергійний" in out


def test_add_without_seconds_when_unique(session):
    # Коли (artist, title) унікальні у сервісі, секунди не мають значення
    assert "Додано" in session.execute('add "Song 2" Blur --mood веселий')
    out = session.execute("list")
    assert "'Song 2' — Blur (2:01)" in out


def test_add_without_seconds_when_ambiguous_raises(session):
    # Коли є кілька версій виконання з різною тривалістю, обов'язково треба вказати --seconds
    with pytest.raises(ReplError, match="Знайдено кілька версій"):
        session.execute('add "Bohemian Rhapsody" Queen')


def test_add_with_seconds_disambiguation(session):
    # Вказавши --seconds, обираємо точну версію
    assert "Додано" in session.execute('add "Bohemian Rhapsody" Queen --seconds 354')
    out = session.execute("list")
    assert "'Bohemian Rhapsody' — Queen (5:54)" in out


def test_add_with_seconds_not_existing_in_deezer_raises(session):
    # Додається лише трек з реально існуючим часом у Deezer
    with pytest.raises(ReplError, match="не знайдено версію"):
        session.execute('add "Song 2" Blur --seconds 999')


def test_add_with_version_seconds(session):
    # Секунди дозволяють унікально ідентифікувати версію виконання (наприклад, Live)
    assert "Додано" in session.execute('add "Song 2" Blur --seconds 170')
    out = session.execute("list")
    assert "(2:50)" in out


def test_add_track_not_found_raises(session):
    with pytest.raises(ReplError, match="не знайдено в Deezer"):
        session.execute('add "Nonexistent" "Nobody"')


@pytest.mark.parametrize("line", [
    "add Song Blur --seconds abc",   # не число
    "add Song Blur --seconds 0",     # нульова тривалість
    "add Song Blur -s -10",          # від'ємна тривалість
    "add Song Blur --seconds 100 --rating 9",  # оцінка поза діапазоном
    "add Song Blur --seconds 100 --mood нудний",
    "add Song",                      # бракує аргументів
])
def test_add_invalid_raises_repl_error(session, line):
    with pytest.raises(ReplError):
        session.execute(line)
    assert session.library == []


def test_ban_unban_case_insensitive(session):
    session.execute("ban Pulp")
    assert "Pulp" in session.execute("list")
    session.execute("unban pulp")
    assert "Заборонені: немає" in session.execute("list")


def test_unban_unknown_raises(session):
    with pytest.raises(ReplError):
        session.execute("unban Nobody")


def test_generate_requires_library(session):
    with pytest.raises(ReplError, match="порожня"):
        session.execute("generate")


def test_generate_excludes_banned_and_respects_duration(session):
    for i in range(5):
        session.execute(f"add T{i} Good --seconds 180")
    session.execute("add Bad Banned --seconds 180")
    session.execute("ban Banned")
    out = session.execute("generate --minutes 6 --new-percent 0")
    assert "Banned" not in out and "Good" in out
    assert "(ціль: 6:00)" in out


def test_generate_invalid_percent_is_repl_error(session):
    session.execute("add T Good --seconds 180")
    with pytest.raises(ReplError):
        session.execute("generate --new-percent 500")


def test_unknown_command_and_bad_quotes(session):
    with pytest.raises(ReplError, match="Невідома команда"):
        session.execute("dance")
    with pytest.raises(ReplError, match="лапки"):
        session.execute('add "unclosed')


def test_empty_line_is_noop(session):
    assert session.execute("   ") == ""


def test_clear_resets_state(session):
    session.execute("add T Good --seconds 180")
    session.execute("ban X")
    session.execute("clear")
    assert session.library == [] and session.banned == {}


def test_import_and_discover_use_deezer(session, monkeypatch):
    seed = Artist("Blur", deezer_id=1)
    other = Artist("Pulp", deezer_id=2)
    monkeypatch.setattr("repl.DeezerAPIClient.search_artist", lambda name: seed)
    monkeypatch.setattr("repl.DeezerAPIClient.related_artists", lambda a, limit=5: [other])
    monkeypatch.setattr("repl.DeezerAPIClient.top_tracks",
                        lambda a, limit=10: [AudioTrack(f"{a.name} hit", a.name, 200)])
    assert "Імпортовано 1" in session.execute("import Blur")
    assert "Додано 1 треків-відкриттів" in session.execute("discover Blur")
    assert len(session.library) == 1 and len(session.discoveries) == 1


def test_import_artist_not_found(session, monkeypatch):
    monkeypatch.setattr("repl.DeezerAPIClient.search_artist", lambda name: None)
    with pytest.raises(ReplError, match="не знайдено"):
        session.execute("import Nobody")


def test_run_loop_processes_commands_and_quits():
    inputs = iter(["add T Good --seconds 180", "dance", "list", "quit", "add AfterQuit X --seconds 100"])
    out = []
    assert repl.run(lambda prompt: next(inputs), out.append) == 0
    text = "\n".join(out)
    assert "Додано" in text and "[Помилка] Невідома команда" in text and "До зустрічі" in text
    assert "AfterQuit" not in text


def test_run_loop_exits_on_eof():
    def raise_eof(prompt):
        raise EOFError
    assert repl.run(raise_eof, lambda s: None) == 0


def test_main_without_args_starts_repl(monkeypatch):
    import main
    monkeypatch.setattr("main.repl.run", lambda: 0)
    assert main.main([]) == 0
    assert main.main(["interactive"]) == 0
