from __future__ import annotations

from chgk_bot.parser import Pack, PackPreview, Question


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(text: str) -> str:
    return esc(text).replace('"', "%22")


def clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _count_phrase(count: int, one: str, few: str, many: str) -> str:
    tail = count % 10
    hundred = count % 100
    if tail == 1 and hundred != 11:
        word = one
    elif tail in (2, 3, 4) and hundred not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{count} {word}"


def titled(title: str, difficulty: str) -> str:
    name = esc(title)
    if not difficulty:
        return name
    return f"{name} · сложность {esc(difficulty)}"


def render_pack_card(pack: Pack) -> str:
    lines = [f"<b>{titled(pack.title, pack.difficulty)}</b>"]
    if pack.editors:
        lines.append("Редакторы: " + esc(", ".join(pack.editors)))
    tour_count = len({question.tour_title for question in pack.questions if question.tour_title})
    count = _count_phrase(len(pack.questions), "вопрос", "вопроса", "вопросов")
    if tour_count:
        count += ", " + _count_phrase(tour_count, "тур", "тура", "туров")
    lines.append(count)
    if pack.blurb:
        lines.append("")
        lines.append(esc(clip(pack.blurb, 500)))
    lines.append("")
    lines.append(
        "Свою версию пришлите ответом на сообщение бота по этому вопросу или командой /a текст."
    )
    lines.append(f'<a href="{esc_attr(pack.url)}">Пакет на GotQuestions</a>')
    return "\n".join(lines)


def render_recent_packs(packs: list[PackPreview]) -> str:
    lines = [
        "<b>Недавно опубликованные</b>",
        "Скопируйте команду или нажмите кнопку с номером пакета.",
    ]
    for index, pack in enumerate(packs, 1):
        lines.append("")
        lines.append(f"{index}. <b>{titled(pack.title, pack.difficulty)}</b>")
        details: list[str] = []
        if pack.question_count.isdigit():
            details.append(
                _count_phrase(int(pack.question_count), "вопрос", "вопроса", "вопросов")
            )
        elif pack.question_count:
            details.append(esc(pack.question_count))
        if pack.when:
            details.append(esc(pack.when))
        if pack.editors:
            shown = pack.editors[:3]
            editors = ", ".join(shown)
            if len(pack.editors) > len(shown):
                editors += f" и ещё {len(pack.editors) - len(shown)}"
            details.append(esc(editors))
        if details:
            lines.append(" · ".join(details))
        lines.append(f"/play {pack.url}")
    return "\n".join(lines)


def render_where(
    title: str,
    question: Question,
    position: int,
    total: int,
    revealed: bool,
    started: bool,
) -> str:
    name = f"<b>{esc(title)}</b>"
    if not started:
        return f"Пакет {name} открыт. Нажмите «Начать игру»."
    where = f"Вопрос {question.number} ({position}/{total})"
    if question.tour_title:
        where = f"{esc(question.tour_title)} · {where}"
    state = "Ответ открыт." if revealed else "Ответ ещё не открыт."
    return "\n".join((name, where, state, "Другой номер: /q 12"))


def render_tour(question: Question) -> str:
    line = f"<b>{esc(question.tour_title)}</b>" if question.tour_title else "<b>Тур</b>"
    if question.tour_editors:
        label = "Редактор" if len(question.tour_editors) == 1 else "Редакторы"
        line += f"\n{label}: {esc(', '.join(question.tour_editors))}"
    return line


def render_question(question: Question, position: int, total: int) -> str:
    heading = f"<b>Вопрос {question.number}</b> ({position}/{total})"
    if question.tour_title:
        heading = f"<b>{esc(question.tour_title)} · Вопрос {question.number}</b> ({position}/{total})"
    lines = [heading]
    if question.handout_text:
        lines.extend(["", "<b>Раздатка</b>", f"<pre>{esc(clip(question.handout_text, 1000))}</pre>"])
    lines.extend(["", esc(clip(question.text, 2000)) or "Текст вопроса — на раздатке."])
    for url in question.audio_urls:
        lines.append(f'<a href="{esc_attr(url)}">Аудио</a>')
    if question.authors:
        label = "Автор" if len(question.authors) == 1 else "Авторы"
        lines.extend(["", f"{label}: {esc(', '.join(question.authors))}"])
    lines.append(f'<a href="{esc_attr(question.url)}">Вопрос на сайте</a>')
    return "\n".join(lines)


def render_answer(question: Question) -> str:
    lines = [f"<b>Ответ:</b> {esc(question.answer) or 'на странице не указан'}"]
    if question.accepted:
        lines.append(f"<b>Зачёт:</b> {esc(question.accepted)}")
    if question.rejected:
        lines.append(f"<b>Незачёт:</b> {esc(question.rejected)}")
    if question.comment:
        lines.extend(["", esc(clip(question.comment, 1800))])
    lines.append(f'<a href="{esc_attr(question.url)}">Полный вопрос на сайте</a>')
    return "\n".join(lines)
