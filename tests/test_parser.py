import unittest
from pathlib import Path

from chgk_bot.network import candidate_ips
from chgk_bot.parser import parse_pack_html, parse_pack_url, parse_recent_html
from chgk_bot.render import esc, render_answer, render_question, render_recent_packs

FIXTURE = Path(__file__).parent / "fixture_pack.html"


class ParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = parse_pack_html(
            FIXTURE.read_text(encoding="utf-8"),
            "https://gotquestions.online/pack/1",
        )

    def test_api_candidates_include_fallback(self) -> None:
        ips = candidate_ips(["149.154.166.110"])
        self.assertEqual(ips[0], "149.154.167.220")
        self.assertIn("149.154.166.110", ips)
        self.assertEqual(len(ips), len(set(ips)))

    def test_recent_packs(self) -> None:
        html = """
        <div class="card card--default">
          <a class="font-semibold" href="/pack/15">Перо!</a>
          <span class="font-mitr">36</span>
          <span class="lowercase">ноябрь 2026</span>
          <a href="/person/1">Эмиль Шалмиев</a>
        </div>
        """
        packs = parse_recent_html(html)
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0].title, "Перо!")
        self.assertEqual(packs[0].url, "https://gotquestions.online/pack/15")
        text = render_recent_packs(packs)
        self.assertIn("/play https://gotquestions.online/pack/15", text)
        self.assertIn("36 вопросов", text)
        self.assertNotIn("сложность", text)
        with_difficulty = """
        <div class="card">
          <a href="/pack/16">Борщ</a>
          <span class="font-mitr">36</span>
          <span>· сложность</span>
          <span class="font-mitr">1.4</span>
        </div>
        """
        rated = parse_recent_html(with_difficulty)[0]
        self.assertEqual(rated.difficulty, "1.4")
        self.assertIn("Борщ · сложность 1.4", render_recent_packs([rated]))

    def test_pack_url(self) -> None:
        self.assertEqual(
            parse_pack_url("смотрите https://gotquestions.online/pack/5771 пожалуйста"),
            "5771",
        )
        self.assertIsNone(parse_pack_url("https://gotquestions.online/search?q=1"))

    def test_pack_meta(self) -> None:
        self.assertEqual(self.pack.title, "Тестовый пакет")
        self.assertEqual(self.pack.difficulty, "2.5")
        self.assertEqual(self.pack.editors, ["Анна Редактор", "Борис Редактор"])
        self.assertEqual(self.pack.blurb, "Короткое предисловие пакета.")
        self.assertEqual(len(self.pack.questions), 3)

    def test_handout_and_answer(self) -> None:
        question = self.pack.questions[0]
        self.assertEqual(question.number, 1)
        self.assertEqual(question.tour_title, "Тур 1")
        self.assertEqual(question.tour_editors, ["Анна Редактор"])
        self.assertEqual(question.text, "Назовите ИКС.")
        self.assertEqual(question.handout_text, "строка один\nстрока два")
        self.assertEqual(question.answer, "футбол")
        self.assertEqual(question.comment, "Потому что сул.")
        self.assertEqual(question.authors, ["Иван Автор"])
        self.assertEqual(question.url, "https://gotquestions.online/question/10")

    def test_image_zachet(self) -> None:
        question = self.pack.questions[1]
        self.assertEqual(
            question.handout_images,
            ["https://gotquestions.online/pics/1/11_razdatka.png"],
        )
        self.assertEqual(question.accepted, "Зигмунд Фрейд")
        self.assertEqual(question.rejected, "Юнг")
        self.assertIn("<важно>", question.text)

    def test_second_tour_audio_and_authors(self) -> None:
        question = self.pack.questions[2]
        self.assertEqual(question.tour_title, "Тур 2")
        self.assertEqual(question.tour_editors, ["Борис Редактор"])
        self.assertEqual(question.audio_urls, ["https://gotquestions.online/sounds/12.mp3"])
        self.assertEqual(question.authors, ["Мария", "Пётр"])

    def test_render_escapes_html(self) -> None:
        question = self.pack.questions[1]
        text = render_question(question, 2, 3)
        self.assertIn("&lt;важно&gt;", text)
        self.assertNotIn("Минута", text)
        answer = render_answer(question)
        self.assertIn("<b>Зачёт:</b> Зигмунд Фрейд", answer)
        self.assertNotIn("Время вышло.", answer)
        self.assertEqual(esc("a < b & c"), "a &lt; b &amp; c")


if __name__ == "__main__":
    unittest.main()
