import sys
from pathlib import Path

# Дозволяє запускати файл напряму (не лише через pytest): додаємо src/ до шляху імпорту
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from main import build_parser, cmd_generate, main


def test_search_parser_defaults():
    args = build_parser().parse_args(["search", "okean elzy"])
    assert (args.command, args.query, args.limit) == ("search", "okean elzy", 3)


def test_generate_parser_defaults_and_options():
    args = build_parser().parse_args(["generate", "Blur", "--ban", "A", "--ban", "B", "--minutes", "45"])
    assert args.artist == "Blur"
    assert args.minutes == 45
    assert args.new_percent == 30
    assert args.ban == ["A", "B"]


def test_generate_rejects_unknown_mood():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["generate", "Blur", "--mood", "нудний"])


def test_missing_command_exits():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_generate_returns_1_when_artist_not_found(monkeypatch, capsys):
    monkeypatch.setattr("main.DeezerAPIClient.search_artist", lambda name: None)
    assert main(["generate", "Nobody"]) == 1
    assert "не знайдено" in capsys.readouterr().out
