import asyncio
import unittest

from aiogram.exceptions import TelegramNetworkError

from chgk_bot.bot import (
    Game,
    call_telegram,
    continue_keyboard,
    move_question,
    question_keyboard,
    repeat_question,
    where_keyboard,
)
from chgk_bot.parser import Pack, Question
from chgk_bot.render import render_where


def sample_pack() -> Pack:
    questions = [
        Question(id="1", number=5, tour_title="Тур 1", tour_editors=[], text="первый", answer="а"),
        Question(id="2", number=12, tour_title="Тур 1", tour_editors=[], text="второй", answer="б"),
    ]
    return Pack(
        id="9",
        title="Пакет",
        editors=[],
        url="https://gotquestions.online/pack/9",
        blurb="",
        questions=questions,
    )


def rows(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


class BotFlowTest(unittest.TestCase):
    def test_navigation_buttons(self) -> None:
        self.assertEqual(
            rows(question_keyboard(0, last=False)),
            [["Показать ответ"], ["Стоп", "Дальше"]],
        )
        self.assertEqual(
            rows(continue_keyboard(1, last=True)),
            [["Стоп", "Закончить"]],
        )

        game = Game(sample_pack(), 7, None)
        game.started = True
        self.assertEqual(rows(where_keyboard(game)), [["Ещё раз", "Дальше"]])

    def test_where_text(self) -> None:
        question = sample_pack().questions[1]
        closed = render_where("Пакет", question, 2, 2, revealed=False, started=True)
        self.assertIn("Вопрос 12 (2/2)", closed)
        self.assertIn("Ответ ещё не открыт.", closed)
        self.assertIn("Тур 1", closed)
        waiting = render_where("Пакет", question, 1, 2, revealed=False, started=False)
        self.assertIn("Нажмите «Начать игру».", waiting)

    def test_reply_targets(self) -> None:
        game = Game(sample_pack(), 7, None)
        game.question_message_id = 5
        game.remember([8, 9], keep=False)
        self.assertTrue(game.tracks(5))
        self.assertTrue(game.tracks(9))
        self.assertFalse(game.tracks(4))
        game.remember([10], keep=True)
        self.assertTrue(game.tracks(9))
        self.assertTrue(game.tracks(10))

    def test_move_and_repeat(self) -> None:
        async def scenario() -> None:
            game = Game(sample_pack(), 7, None)
            game.index = 0
            game.started = True
            game.revealed = True
            self.assertIsNone(await move_question(game, 0))
            self.assertEqual(game.index, 1)
            self.assertFalse(game.revealed)
            game.revealed = True
            self.assertEqual(await move_question(game, 1), "")
            self.assertEqual(game.index, 1)
            self.assertTrue(game.revealed)
            self.assertEqual(await move_question(game, 0), "Это уже не тот вопрос.")
            self.assertIsNone(await repeat_question(game, 1))
            self.assertEqual(game.index, 1)
            self.assertTrue(game.revealed)

        asyncio.run(scenario())

    def test_telegram_retry_once(self) -> None:
        async def scenario() -> str:
            calls = 0

            async def action() -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise TelegramNetworkError(method=None, message="down")
                return "ok"

            result = await call_telegram(action)
            self.assertEqual(calls, 2)
            return result

        self.assertEqual(asyncio.run(scenario()), "ok")

    def test_telegram_retry_does_not_hide_second_failure(self) -> None:
        async def action() -> None:
            raise TelegramNetworkError(method=None, message="down")

        with self.assertRaises(TelegramNetworkError):
            asyncio.run(call_telegram(action))


if __name__ == "__main__":
    unittest.main()
