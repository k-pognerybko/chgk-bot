from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

BASE_URL = "https://gotquestions.online"
PACK_URL_RE = re.compile(
    r"https?://(?:www\.)?gotquestions\.online/pack/(\d+)",
    re.IGNORECASE,
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

FIELD_MAP = {
    "ответ": "answer",
    "зачет": "accepted",
    "незачет": "rejected",
    "комментарий": "comment",
    "источник": "sources",
    "источники": "sources",
}
AUTHOR_LABELS = {"автор", "авторка", "авторы", "авторы вопроса"}


class PackLoadError(Exception):
    """Ошибка, которую можно показать игроку."""


@dataclass
class Question:
    id: str
    number: int
    tour_title: str
    tour_editors: list[str]
    text: str
    handout_text: str = ""
    handout_images: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    audio_urls: list[str] = field(default_factory=list)
    answer: str = ""
    accepted: str = ""
    rejected: str = ""
    comment: str = ""
    comment_images: list[str] = field(default_factory=list)
    sources: str = ""
    authors: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class Pack:
    id: str
    title: str
    editors: list[str]
    url: str
    blurb: str
    questions: list[Question]
    difficulty: str = ""


@dataclass
class PackPreview:
    id: str
    title: str
    question_count: str
    when: str
    editors: list[str]
    difficulty: str = ""

    @property
    def url(self) -> str:
        return f"{BASE_URL}/pack/{self.id}"


def parse_pack_url(text: str) -> str | None:
    match = PACK_URL_RE.search(text or "")
    if not match:
        return None
    return match.group(1)


def parse_pack_html(html: str, page_url: str) -> Pack:
    pack_id_match = PACK_URL_RE.search(page_url)
    pack_id = pack_id_match.group(1) if pack_id_match else ""
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h1")
    title = title_node.get_text(strip=True) if title_node else f"Пакет {pack_id}"
    questions = _parse_questions(soup)
    if not questions:
        raise PackLoadError(
            "На странице не нашлось вопросов. Сайт мог изменить вёрстку."
        )
    return Pack(
        id=pack_id,
        title=title,
        editors=_pack_editors(soup),
        url=page_url,
        blurb=_pack_blurb(soup),
        questions=questions,
        difficulty=_labeled_value(soup, "TrueDL"),
    )


async def fetch_pack(url: str) -> Pack:
    pack_id = parse_pack_url(url)
    if not pack_id:
        raise PackLoadError(
            "Нужна ссылка на пакет, например https://gotquestions.online/pack/5771"
        )
    page_url = f"{BASE_URL}/pack/{pack_id}"
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
        ) as client:
            response = await client.get(page_url)
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise PackLoadError(
            f"Сайт ответил ошибкой {error.response.status_code}."
        ) from error
    except httpx.HTTPError as error:
        raise PackLoadError("Сайт gotquestions.online не ответил.") from error
    return parse_pack_html(response.text, page_url)


def parse_recent_html(html: str) -> list[PackPreview]:
    soup = BeautifulSoup(html, "html.parser")
    previews: list[PackPreview] = []
    for card in soup.find_all("div"):
        if "card" not in _class_tokens(card.get("class")):
            continue
        link = card.find("a", href=re.compile(r"^/pack/\d+$"))
        if not isinstance(link, Tag):
            continue
        pack_id = str(link.get("href", "")).rsplit("/", 1)[-1]
        title = link.get_text(strip=True)
        if not pack_id or not title:
            continue
        count_node = card.find("span", class_=lambda value: "font-mitr" in _class_tokens(value))
        when_node = card.find("span", class_=lambda value: "lowercase" in _class_tokens(value))
        editors: list[str] = []
        for person in card.find_all("a", href=re.compile(r"^/person/\d+$")):
            name = person.get_text(strip=True)
            if name and name not in editors:
                editors.append(name)
        previews.append(
            PackPreview(
                id=pack_id,
                title=title,
                question_count=count_node.get_text(strip=True) if isinstance(count_node, Tag) else "",
                when=when_node.get_text(strip=True) if isinstance(when_node, Tag) else "",
                editors=editors,
                difficulty=_difficulty_value(card),
            )
        )
    if not previews:
        raise PackLoadError("На главной не нашлось свежих пакетов.")
    return previews


async def fetch_recent_packs() -> list[PackPreview]:
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
        ) as client:
            response = await client.get(BASE_URL + "/")
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise PackLoadError(
            f"Сайт ответил ошибкой {error.response.status_code}."
        ) from error
    except httpx.HTTPError as error:
        raise PackLoadError("Сайт gotquestions.online не ответил.") from error
    return parse_recent_html(response.text)


def _difficulty_value(card: Tag) -> str:
    for span in card.find_all("span"):
        if "сложность" not in span.get_text(" ", strip=True).lower():
            continue
        value_node = span.find_next("span")
        if isinstance(value_node, Tag) and card in value_node.parents:
            return value_node.get_text(strip=True)
    return ""


def _labeled_value(root: Tag, label: str) -> str:
    for node in root.find_all("div"):
        if node.get_text(strip=True) != label or node.parent is None:
            continue
        for sibling in node.parent.find_all("div", recursive=False):
            text = sibling.get_text(strip=True)
            if text and text != label:
                return text
    return ""


def _class_tokens(value: object) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return set(value.split())
    return set(value)


def _has_class(tag: Tag, token: str) -> bool:
    return token in _class_tokens(tag.get("class"))


def _clean(text: str) -> str:
    lines = [
        line.rstrip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    compact = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", compact)


def _norm_label(label: str) -> str:
    return label.strip().rstrip(":").lower().replace("ё", "е")


def _absolute(src: str) -> str:
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("//"):
        return "https:" + src
    if not src.startswith("/"):
        src = "/" + src
    return BASE_URL + src


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _pack_editors(soup: BeautifulSoup) -> list[str]:
    for span in soup.find_all("span"):
        if span.find_parent("div", id=re.compile(r"^question-\d+$")):
            continue
        if _norm_label(span.get_text(" ", strip=True)) not in {"редактор", "редакторы"}:
            continue
        parent = span.parent
        if parent is None:
            continue
        text = parent.get_text(" ", strip=True)
        if len(text) > 400:
            continue
        text = re.sub(r"^редакторы?\s*:\s*", "", text, flags=re.IGNORECASE)
        editors = [part.strip() for part in text.split(",") if part.strip()]
        if editors:
            return editors
    return []


def _pack_blurb(soup: BeautifulSoup) -> str:
    for node in soup.find_all("div"):
        if not (_has_class(node, "italic") and _has_class(node, "whitespace-pre-wrap")):
            continue
        if node.find_parent("div", id=re.compile(r"^(tour|question)-\d+$")):
            continue
        text = _clean(node.get_text())
        if text:
            return text
    return ""


def _tour_editors(tour_div: Tag) -> list[str]:
    names: list[str] = []
    for node in tour_div.descendants:
        if not isinstance(node, Tag):
            continue
        if str(node.get("id", "")).startswith("question-"):
            break
        href = str(node.get("href", ""))
        if node.name != "a" or not re.match(r"^/person/\d+$", href):
            continue
        if node.find_parent("p") is not None:
            continue
        name = node.get_text(strip=True)
        if name and name not in names:
            names.append(name)
    return names


def _person_names(root: Tag) -> list[str]:
    names: list[str] = []
    for link in root.find_all("a", href=re.compile(r"^/person/\d+")):
        name = link.get_text(strip=True)
        if name and name not in names:
            names.append(name)
    return names


def _parse_questions(soup: BeautifulSoup) -> list[Question]:
    questions: list[Question] = []
    tour_divs = soup.find_all("div", id=re.compile(r"^tour-\d+$"))
    if tour_divs:
        for tour_div in tour_divs:
            heading = tour_div.find("h2")
            title = heading.get_text(strip=True) if heading else "Тур"
            editors = _tour_editors(tour_div)
            for node in tour_div.find_all("div", id=re.compile(r"^question-\d+$")):
                if node.find_parent("div", id=re.compile(r"^question-\d+$")):
                    continue
                questions.append(_parse_question(node, title, editors, len(questions) + 1))
        return questions

    for node in soup.find_all("div", id=re.compile(r"^question-\d+$")):
        questions.append(_parse_question(node, "", [], len(questions) + 1))
    return questions


def _parse_question(
    node: Tag,
    tour_title: str,
    tour_editors: list[str],
    fallback_number: int,
) -> Question:
    question_id = str(node.get("id", "")).split("-", 1)[-1]
    number = _question_number(node, fallback_number)
    print_block = _find_print_block(node)
    handout_roots = _handout_roots(node)
    handout_text, handout_images = _handout(handout_roots)
    fields, authors = _answer_fields(print_block)
    return Question(
        id=question_id,
        number=number,
        tour_title=tour_title,
        tour_editors=tour_editors,
        text=_question_text(node, handout_roots, print_block),
        handout_text=handout_text,
        handout_images=handout_images,
        images=_body_images(node, handout_roots, print_block),
        audio_urls=_audio_urls(node, print_block),
        answer=fields.get("answer", ""),
        accepted=fields.get("accepted", ""),
        rejected=fields.get("rejected", ""),
        comment=fields.get("comment", ""),
        comment_images=_images_under(print_block) if print_block else [],
        sources=fields.get("sources", ""),
        authors=authors,
        url=f"{BASE_URL}/question/{question_id}",
    )


def _question_number(node: Tag, fallback: int) -> int:
    link = node.find("a", href=re.compile(r"^/question/\d+"))
    if link is None:
        return fallback
    match = re.search(r"\d+", link.get_text(" ", strip=True))
    if not match:
        return fallback
    return int(match.group())


def _find_print_block(node: Tag) -> Tag | None:
    for div in node.find_all("div"):
        if _has_class(div, "print:block"):
            return div
    return None


def _handout_roots(node: Tag) -> list[Tag]:
    roots: list[Tag] = []
    for span in node.find_all("span"):
        if not span.get_text(" ", strip=True).startswith("Раздаточный материал"):
            continue
        parent = span.parent
        if isinstance(parent, Tag) and parent not in roots:
            roots.append(parent)
    return roots


def _inside_any(tag: Tag, roots: list[Tag]) -> bool:
    return any(tag == root or root in tag.parents for root in roots)


def _leaf_pre_text(root: Tag) -> list[str]:
    chunks: list[str] = []
    for tag in root.find_all(True):
        if not _has_class(tag, "whitespace-pre-wrap"):
            continue
        if tag.find(class_=lambda value: _class_contains(value, "whitespace-pre-wrap")):
            continue
        text = _clean(tag.get_text())
        if text:
            chunks.append(text)
    return chunks


def _class_contains(value: object, token: str) -> bool:
    return token in _class_tokens(value)


def _handout(roots: list[Tag]) -> tuple[str, list[str]]:
    texts: list[str] = []
    images: list[str] = []
    for root in roots:
        texts.extend(_leaf_pre_text(root))
        images.extend(_images_under(root))
    return _clean("\n\n".join(texts)), _unique(images)


def _images_under(root: Tag | None) -> list[str]:
    if root is None:
        return []
    urls: list[str] = []
    for image in root.find_all("img"):
        src = image.get("src")
        if isinstance(src, str) and src:
            urls.append(_absolute(src))
    return _unique(urls)


def _question_text(node: Tag, handout_roots: list[Tag], print_block: Tag | None) -> str:
    chunks: list[str] = []
    for tag in node.find_all("div"):
        if not _has_class(tag, "whitespace-pre-wrap"):
            continue
        if _inside_any(tag, handout_roots):
            continue
        if print_block is not None and (tag == print_block or print_block in tag.parents):
            continue
        if tag.find("div", class_=lambda value: _class_contains(value, "whitespace-pre-wrap")):
            continue
        text = _clean(tag.get_text())
        if text:
            chunks.append(text)
    return _clean("\n\n".join(chunks))


def _body_images(node: Tag, handout_roots: list[Tag], print_block: Tag | None) -> list[str]:
    urls: list[str] = []
    for image in node.find_all("img"):
        if _inside_any(image, handout_roots):
            continue
        if print_block is not None and (image == print_block or print_block in image.parents):
            continue
        src = image.get("src")
        if isinstance(src, str) and src:
            urls.append(_absolute(src))
    return _unique(urls)


def _audio_urls(node: Tag, print_block: Tag | None) -> list[str]:
    urls: list[str] = []
    for audio in node.find_all("audio"):
        if print_block is not None and print_block in audio.parents:
            continue
        src = audio.get("src")
        if isinstance(src, str) and src:
            urls.append(_absolute(src))
        for source in audio.find_all("source"):
            source_src = source.get("src")
            if isinstance(source_src, str) and source_src:
                urls.append(_absolute(source_src))
    for link in node.find_all("a", href=True):
        if print_block is not None and print_block in link.parents:
            continue
        href = str(link.get("href"))
        if re.search(r"\.(mp3|ogg|wav)(?:$|\?)", href, re.IGNORECASE):
            urls.append(_absolute(href))
    return _unique(urls)


def _answer_fields(print_block: Tag | None) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    authors: list[str] = []
    if print_block is None:
        return fields, authors
    for child in print_block.find_all("div", recursive=False):
        label_span = child.find("span")
        label = _norm_label(label_span.get_text(" ", strip=True)) if label_span else ""
        if label in AUTHOR_LABELS:
            text = _field_text(child, label_span)
            authors.extend(part.strip() for part in text.split(",") if part.strip())
            continue
        mapped = FIELD_MAP.get(label)
        if mapped:
            fields[mapped] = _field_text(child, label_span)
    authors.extend(_person_names(print_block))
    return fields, _unique(authors)


def _field_text(child: Tag, label_span: Tag | None) -> str:
    if label_span is not None:
        label_span.extract()
    return _clean(child.get_text())
