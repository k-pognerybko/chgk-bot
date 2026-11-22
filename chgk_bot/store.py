from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from chgk_bot.parser import Pack, Question

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "games.sqlite"

_connection: sqlite3.Connection | None = None
_path = DEFAULT_PATH


def use_path(path: Path) -> None:
    global _connection, _path
    if _connection is not None:
        _connection.close()
        _connection = None
    _path = path


def locate_question(questions: list[Question], number: int) -> int | None:
    matches = [index for index, question in enumerate(questions) if question.number == number]
    if matches:
        return matches[0]
    position = number - 1
    if 0 <= position < len(questions):
        return position
    return None


def save_game(game: "Game") -> None:
    payload = json.dumps(_pack_to_dict(game.pack), ensure_ascii=False)
    connection = _connect()
    connection.execute(
        """
        INSERT INTO games (
            chat_id, thread_id, pack_json, question_index, revealed, started, question_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, thread_id) DO UPDATE SET
            pack_json = excluded.pack_json,
            question_index = excluded.question_index,
            revealed = excluded.revealed,
            started = excluded.started,
            question_message_id = excluded.question_message_id
        """,
        (
            game.chat_id,
            game.thread_id or 0,
            payload,
            game.index,
            int(game.revealed),
            int(game.started),
            game.question_message_id,
        ),
    )
    connection.commit()


def delete_game(chat_id: int, thread_id: int | None) -> None:
    connection = _connect()
    connection.execute(
        "DELETE FROM games WHERE chat_id = ? AND thread_id = ?",
        (chat_id, thread_id or 0),
    )
    connection.commit()


def load_games() -> dict[tuple[int, int], "Game"]:
    from chgk_bot.bot import Game

    games: dict[tuple[int, int], Game] = {}
    connection = _connect()
    rows = connection.execute(
        """
        SELECT chat_id, thread_id, pack_json, question_index, revealed, started, question_message_id
        FROM games
        """
    )
    for chat_id, thread_id, payload, index, revealed, started, message_id in rows:
        try:
            pack = _pack_from_dict(json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not pack.questions:
            continue
        thread = thread_id or None
        game = Game(pack, chat_id, thread)
        game.index = min(max(int(index), 0), len(pack.questions) - 1)
        game.revealed = bool(revealed)
        game.started = bool(started)
        game.question_message_id = message_id
        games[(chat_id, thread_id or 0)] = game
    return games


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(_path, check_same_thread=False)
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                pack_json TEXT NOT NULL,
                question_index INTEGER NOT NULL,
                revealed INTEGER NOT NULL,
                started INTEGER NOT NULL,
                question_message_id INTEGER,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        _connection.commit()
    return _connection


def _pack_to_dict(pack: Pack) -> dict:
    return {
        "id": pack.id,
        "title": pack.title,
        "editors": pack.editors,
        "url": pack.url,
        "blurb": pack.blurb,
        "difficulty": pack.difficulty,
        "questions": [
            {
                "id": question.id,
                "number": question.number,
                "tour_title": question.tour_title,
                "tour_editors": question.tour_editors,
                "text": question.text,
                "handout_text": question.handout_text,
                "handout_images": question.handout_images,
                "images": question.images,
                "audio_urls": question.audio_urls,
                "answer": question.answer,
                "accepted": question.accepted,
                "rejected": question.rejected,
                "comment": question.comment,
                "comment_images": question.comment_images,
                "sources": question.sources,
                "authors": question.authors,
                "url": question.url,
            }
            for question in pack.questions
        ],
    }


def _pack_from_dict(data: dict) -> Pack:
    questions = [Question(**item) for item in data.get("questions", [])]
    return Pack(
        id=str(data.get("id", "")),
        title=str(data.get("title", "")),
        editors=list(data.get("editors", [])),
        url=str(data.get("url", "")),
        blurb=str(data.get("blurb", "")),
        questions=questions,
        difficulty=str(data.get("difficulty", "")),
    )
