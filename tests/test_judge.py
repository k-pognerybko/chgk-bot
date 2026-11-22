import unittest

from chgk_bot.judge import Verdict, judge
from chgk_bot.parser import Question


def question(**kwargs: str) -> Question:
    data = {
        "id": "1",
        "number": 1,
        "tour_title": "Тур 1",
        "tour_editors": [],
        "text": "Текст",
    }
    data.update(kwargs)
    return Question(**data)


class JudgeTest(unittest.TestCase):
    def test_exact_and_punctuation(self) -> None:
        item = question(answer="футбол")
        self.assertEqual(judge(item, "Футбол!"), Verdict.CORRECT)
        self.assertEqual(judge(item, "ответ: футбол"), Verdict.CORRECT)

    def test_optional_brackets_and_yo(self) -> None:
        item = question(answer="[солёный] огурец")
        self.assertEqual(judge(item, "огурец"), Verdict.CORRECT)
        self.assertEqual(judge(item, "соленый огурец"), Verdict.CORRECT)

    def test_accepted_list(self) -> None:
        item = question(answer="[солёный] огурец", accepted="шоколадина, шоколад")
        self.assertEqual(judge(item, "шоколад"), Verdict.CORRECT)

    def test_rejected_wins(self) -> None:
        item = question(answer="Зигмунд Фрейд", rejected="Юнг")
        self.assertEqual(judge(item, "Юнг"), Verdict.WRONG)
        self.assertEqual(judge(item, "фрейд зигмунд"), Verdict.CORRECT)

    def test_typo_and_unrelated(self) -> None:
        item = question(answer="футбол")
        self.assertEqual(judge(item, "фудбол"), Verdict.CORRECT)
        self.assertEqual(judge(item, "баскетбол"), Verdict.WRONG)
        self.assertEqual(judge(item, "не футбол"), Verdict.WRONG)
        cucumber = question(answer="[солёный] огурец")
        self.assertEqual(judge(cucumber, "соленые огурцы"), Verdict.CLOSE)

    def test_missing_answer(self) -> None:
        self.assertEqual(judge(question(), "что угодно"), Verdict.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
