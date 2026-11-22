from __future__ import annotations

import re
from enum import Enum

from chgk_bot.parser import Question

_BRACKET = re.compile(r"\[([^\[\]]*)]")
_LABEL = re.compile(r"^(ответ|answer)\s+")


class Verdict(Enum):
    CORRECT = "correct"
    CLOSE = "close"
    WRONG = "wrong"
    UNKNOWN = "unknown"


def normalize(text: str) -> str:
    cleaned = text.lower().replace("ё", "е")
    cleaned = re.sub(r"[^\w\s]+", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _LABEL.sub("", cleaned)


def judge(question: Question, guess: str) -> Verdict:
    accepted = _variants(question.answer) + _variants(question.accepted)
    rejected = _variants(question.rejected)
    if not accepted:
        return Verdict.UNKNOWN
    prepared = normalize(guess)
    if not prepared:
        return Verdict.WRONG
    accepted_score = _best(prepared, accepted)
    rejected_score = _best(prepared, rejected)
    if rejected_score >= 88 and rejected_score >= accepted_score:
        return Verdict.WRONG
    if _is_correct(prepared, accepted, accepted_score) and accepted_score >= rejected_score + 8:
        return Verdict.CORRECT
    if accepted_score >= 75 and accepted_score >= rejected_score + 8:
        return Verdict.CLOSE
    return Verdict.WRONG


def _variants(field: str) -> list[str]:
    found: list[str] = []
    for chunk in _chunks(field):
        for expanded in _expand(chunk):
            prepared = normalize(expanded)
            if prepared and prepared not in found:
                found.append(prepared)
    return found


def _chunks(field: str) -> list[str]:
    text = field.strip()
    if not text:
        return []
    chunks = [text]
    for piece in re.split(r"[\n;]+| / ", text):
        piece = piece.strip()
        if piece and piece not in chunks:
            chunks.append(piece)
    for piece in list(chunks):
        parts = [part.strip() for part in re.split(r",|\s+или\s+", piece) if part.strip()]
        if len(parts) < 2 or any(len(part) > 48 for part in parts):
            continue
        for part in parts:
            if part not in chunks:
                chunks.append(part)
    return chunks


def _expand(text: str, depth: int = 0) -> list[str]:
    if depth > 6:
        return [text]
    match = _BRACKET.search(text)
    if match is None:
        return [text]
    kept = text[: match.start()] + match.group(1) + text[match.end() :]
    dropped = text[: match.start()] + text[match.end() :]
    return _expand(kept, depth + 1) + _expand(dropped, depth + 1)


def _best(guess: str, variants: list[str]) -> float:
    if not variants:
        return 0
    return max(_similarity(guess, variant) for variant in variants)


def _is_correct(guess: str, variants: list[str], score: float) -> bool:
    if score >= 99.5:
        return True
    shortest = min(len(variant) for variant in variants)
    if min(len(guess), shortest) < 5:
        return False
    if _distance(guess, _closest(guess, variants)) == 1 and min(len(guess), shortest) >= 5:
        return True
    return score >= 88 and min(len(guess), shortest) >= 8


def _closest(guess: str, variants: list[str]) -> str:
    return min(variants, key=lambda variant: (_distance(guess, variant), abs(len(variant) - len(guess))))


def _similarity(left: str, right: str) -> float:
    direct = _ratio(left, right)
    sorted_words = _ratio(_sorted_words(left), _sorted_words(right))
    return max(direct, sorted_words)


def _sorted_words(text: str) -> str:
    return " ".join(sorted(text.split()))


def _ratio(left: str, right: str) -> float:
    if left == right:
        return 100
    longest = max(len(left), len(right))
    if longest == 0:
        return 100
    return 100 * (1 - _distance(left, right) / longest)


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
