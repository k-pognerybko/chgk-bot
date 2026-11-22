import tempfile
import unittest
from pathlib import Path

from chgk_bot.bot import Game
from chgk_bot.parser import Pack, Question
from chgk_bot.store import DEFAULT_PATH, delete_game, load_games, locate_question, save_game, use_path


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
        save_game(game)

        restored = load_games()
        loaded = restored[(7, 0)]
        self.assertEqual(loaded.pack.title, "Пакет")
        self.assertEqual(loaded.pack.difficulty, "1.4")
        self.assertEqual(loaded.index, 1)
        self.assertTrue(loaded.revealed)
        self.assertTrue(loaded.started)
        self.assertEqual(loaded.question_message_id, 55)
        self.assertEqual(loaded.question.answer, "б")

        delete_game(7, None)
        self.assertEqual(load_games(), {})


if __name__ == "__main__":
    unittest.main()
