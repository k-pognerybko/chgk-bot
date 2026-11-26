import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chgk_bot.bot import Game
from chgk_bot.parser import Pack, Question
from chgk_bot.store import (
    DEFAULT_PATH,
    _pack_to_dict,
    delete_game,
    load_games,
    locate_question,
    save_game,
    use_path,
)


def sample_pack() -> Pack:
    questions = [
        Question(id="1", number=5, tour_title="Тур 1", tour_editors=[], text="первый", answer="а"),
        Question(id="2", number=12, tour_title="Тур 1", tour_editors=[], text="второй", answer="б"),
    ]
    return Pack(
        id="9",
        title="Пакет",
        editors=["Анна"],
        url="https://gotquestions.online/pack/9",
        blurb="",
        questions=questions,
        difficulty="1.4",
    )


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        use_path(Path(self.directory.name) / "games.sqlite")

    def tearDown(self) -> None:
        use_path(DEFAULT_PATH)
        self.directory.cleanup()

    def test_locate_by_number_then_position(self) -> None:
        questions = sample_pack().questions
        self.assertEqual(locate_question(questions, 12), 1)
        self.assertEqual(locate_question(questions, 1), 0)
        self.assertIsNone(locate_question(questions, 40))

    def test_progress_survives_reload(self) -> None:
        game = Game(sample_pack(), chat_id=7, thread_id=None)
        game.index = 1
        game.revealed = True
        game.started = True
        game.question_message_id = 55
        game.message_ids = [40, 55]
        save_game(game)

        restored = load_games()
        loaded = restored[(7, 0)]
        self.assertEqual(loaded.pack.title, "Пакет")
        self.assertEqual(loaded.pack.difficulty, "1.4")
        self.assertEqual(loaded.index, 1)
        self.assertTrue(loaded.revealed)
        self.assertTrue(loaded.started)
        self.assertEqual(loaded.question_message_id, 55)
        self.assertEqual(loaded.message_ids, [40, 55])
        self.assertTrue(loaded.tracks(40))
        self.assertEqual(loaded.question.answer, "б")

        delete_game(7, None)
        self.assertEqual(load_games(), {})

    def test_old_database_keeps_reply_to_question(self) -> None:
        path = Path(self.directory.name) / "old.sqlite"
        connection = sqlite3.connect(path)
        connection.execute(
            """
            CREATE TABLE games (
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
        connection.execute(
            """
            INSERT INTO games (
                chat_id, thread_id, pack_json, question_index, revealed, started, question_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (7, 0, json.dumps(_pack_to_dict(sample_pack()), ensure_ascii=False), 1, 0, 1, 55),
        )
        connection.commit()
        connection.close()

        use_path(path)
        loaded = load_games()[(7, 0)]
        self.assertEqual(loaded.question_message_id, 55)
        self.assertEqual(loaded.message_ids, [55])
        self.assertTrue(loaded.tracks(55))


if __name__ == "__main__":
    unittest.main()
