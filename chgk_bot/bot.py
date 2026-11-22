from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from dotenv import load_dotenv

from chgk_bot.judge import Verdict, judge
from chgk_bot.network import ApiResolver, can_connect, reachable_api_ip
from chgk_bot.parser import (
    Pack,
    PackLoadError,
    PackPreview,
    Question,
    fetch_pack,
    fetch_recent_packs,
    parse_pack_url,
)
from chgk_bot.store import delete_game, load_games, locate_question, save_game
from chgk_bot.render import (
    esc,
    esc_attr,
    render_answer,
    render_pack_card,
    render_question,
    render_recent_packs,
    render_tour,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LOG = logging.getLogger("chgk_bot")
LINK_OFF = LinkPreviewOptions(is_disabled=True)
PACK_IN_TEXT = re.compile(r"gotquestions\.online/pack/\d+", re.IGNORECASE)

HELP = (
    "Это ведущий для «Что? Где? Когда?».\n\n"
    "Пришлите ссылку на пакет с gotquestions.online — бот откроет вопросы по одному. "
    "Свою версию пришлите ответом на сообщение с вопросом. "
    "При зачёте бот сразу покажет ответ, иначе напишет «незачёт» или «похоже». "
    "Кнопка «Показать ответ» открывает его в любой момент.\n\n"
    "В группе удобнее команды, их бот видит всегда:\n"
    "/packs — свежие пакеты с сайта\n"
    "/play https://gotquestions.online/pack/5771\n"
    "/q 12 — перейти к вопросу 12\n\n"
    "Вопросы принадлежат их авторам. Бот показывает текст как на сайте, "
    "с именем автора и ссылкой на пакет. Играйте в своей компании, "
    "без коммерческого использования.\n\n"
    "/stop — остановить текущую игру"
)

router = Router()
_games: dict[tuple[int, int], "Game"] = {}


class Game:
    def __init__(self, pack: Pack, chat_id: int, thread_id: int | None) -> None:
        self.pack = pack
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.index = 0
        self.revealed = False
        self.started = False
        self.token = 0
        self.lock = asyncio.Lock()
        self.question_message_id: int | None = None

    @property
    def question(self) -> Question:
        return self.pack.questions[self.index]

    def target(self) -> dict[str, int]:
        data = {"chat_id": self.chat_id}
        if self.thread_id:
            data["message_thread_id"] = self.thread_id
        return data


def game_key(chat_id: int, thread_id: int | None) -> tuple[int, int]:
    return chat_id, thread_id or 0


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать игру", callback_data="g")]
        ]
    )


def question_keyboard(index: int, last: bool) -> InlineKeyboardMarkup:
    forward = "Закончить" if last else "Дальше"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Показать ответ", callback_data=f"a:{index}")],
            [
                InlineKeyboardButton(text="Стоп", callback_data="s"),
                InlineKeyboardButton(text=forward, callback_data=f"n:{index}"),
            ],
        ]
    )


def continue_keyboard(index: int, last: bool) -> InlineKeyboardMarkup:
    forward = "Закончить" if last else "Дальше"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Стоп", callback_data="s"),
                InlineKeyboardButton(text=forward, callback_data=f"n:{index}"),
            ]
        ]
    )


async def open_pack(message: Message, url: str) -> None:
    key = game_key(message.chat.id, message.message_thread_id)
    status = await message.answer("Открываю пакет…")
    try:
        pack = await fetch_pack(url)
    except PackLoadError as error:
        await status.edit_text(str(error))
        return
    except Exception:
        LOG.exception("failed to load pack")
        await status.edit_text("Не получилось открыть пакет. Попробуйте ещё раз.")
        return
    game = Game(pack, message.chat.id, message.message_thread_id)
    _games[key] = game
    save_game(game)
    await status.edit_text(
        render_pack_card(pack),
        reply_markup=start_keyboard(),
        link_preview_options=LINK_OFF,
    )


async def send_photos(bot: Bot, game: Game, urls: list[str]) -> list[str]:
    failed: list[str] = []
    for url in urls[:8]:
        try:
            await bot.send_photo(photo=url, **game.target())
        except Exception:
            LOG.warning("photo failed: %s", url)
            failed.append(url)
    return failed


async def show_question(bot: Bot, game: Game) -> None:
    token = game.token
    question = game.question
    previous = game.pack.questions[game.index - 1] if game.index else None
    if game.token != token:
        return
    if previous is None or previous.tour_title != question.tour_title:
        if question.tour_title:
            await bot.send_message(
                text=render_tour(question),
                link_preview_options=LINK_OFF,
                **game.target(),
            )
    if game.token != token:
        return
    failed_images = await send_photos(bot, game, question.handout_images + question.images)
    text = render_question(question, game.index + 1, len(game.pack.questions))
    if failed_images:
        links = "\n".join(
            f'<a href="{esc_attr(url)}">Раздатка</a>' for url in failed_images
        )
        text = links + "\n\n" + text
    if game.token != token:
        return
    sent = await bot.send_message(
        text=text,
        reply_markup=question_keyboard(game.index, game.index + 1 == len(game.pack.questions)),
        link_preview_options=LINK_OFF,
        **game.target(),
    )
    if game.token != token:
        return
    game.question_message_id = sent.message_id
    game.revealed = False
    save_game(game)


async def reveal(bot: Bot, game: Game, token: int, index: int) -> bool:
    async with game.lock:
        if game.token != token or game.index != index or game.revealed:
            return False
        game.revealed = True
        question = game.question
        last = index + 1 == len(game.pack.questions)
        message_id = game.question_message_id
    if message_id is not None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=game.chat_id,
                message_id=message_id,
                reply_markup=continue_keyboard(index, last),
            )
        except Exception:
            LOG.debug("could not update question keyboard", exc_info=True)
    comment_images = [
        url for url in question.comment_images if url not in set(question.handout_images)
    ]
    await send_photos(bot, game, comment_images)
    await bot.send_message(
        text=render_answer(question),
        reply_markup=continue_keyboard(index, last),
        link_preview_options=LINK_OFF,
        **game.target(),
    )
    save_game(game)
    return True


async def go_next(bot: Bot, game: Game, index: int) -> str | None:
    async with game.lock:
        if game.index != index:
            return "Это уже не тот вопрос."
        if game.index + 1 >= len(game.pack.questions):
            return ""
        game.index += 1
        game.token += 1
        game.revealed = False
        game.started = True
    await show_question(bot, game)
    return None


def stop_game(chat_id: int, thread_id: int | None) -> bool:
    removed = _games.pop(game_key(chat_id, thread_id), None) is not None
    if removed:
        delete_game(chat_id, thread_id)
    return removed


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP, link_preview_options=LINK_OFF)


@router.message(Command("q"))
async def cmd_question(message: Message, command: CommandObject) -> None:
    game = _games.get(game_key(message.chat.id, message.message_thread_id))
    if game is None:
        await message.answer("Сейчас нет пакета. Откройте его через /play или /packs.")
        return
    raw = command.args or ""
    match = re.search(r"\d+", raw)
    if match is None:
        current = game.question.number if game.started else None
        hint = f"Сейчас вопрос {current}. " if current is not None else ""
        await message.answer(f"{hint}Переход: /q 12")
        return
    number = int(match.group())
    index = locate_question(game.pack.questions, number)
    if index is None:
        await message.answer(
            f"В пакете нет вопроса {number}. Всего вопросов: {len(game.pack.questions)}."
        )
        return
    async with game.lock:
        game.index = index
        game.token += 1
        game.revealed = False
        game.started = True
    if message.bot is None:
        await message.answer("Не получилось показать вопрос.")
        return
    await show_question(message.bot, game)


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    stopped = stop_game(message.chat.id, message.message_thread_id)
    await message.answer("Игра остановлена." if stopped else "Сейчас нет игры.")


@router.message(Command("packs"))
async def cmd_packs(message: Message) -> None:
    status = await message.answer("Смотрю свежие пакеты…")
    try:
        packs = await fetch_recent_packs()
    except PackLoadError as error:
        await status.edit_text(str(error))
        return
    except Exception:
        LOG.exception("failed to load recent packs")
        await status.edit_text("Не получилось открыть список пакетов. Попробуйте ещё раз.")
        return
    await status.edit_text(
        render_recent_packs(packs),
        reply_markup=recent_keyboard(packs),
        link_preview_options=LINK_OFF,
    )


def recent_keyboard(packs: list[PackPreview]) -> InlineKeyboardMarkup:
    rows = []
    for index, pack in enumerate(packs, 1):
        suffix = f" · {pack.difficulty}" if pack.difficulty else ""
        room = 60 - len(f"{index}. {suffix}")
        title = pack.title if len(pack.title) <= room else pack.title[: room - 1].rstrip() + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{index}. {title}{suffix}",
                    callback_data=f"p:{pack.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("play"))
async def cmd_play(message: Message, command: CommandObject) -> None:
    url = (command.args or "").strip()
    if parse_pack_url(url) is None:
        await message.answer(
            "Пришлите ссылку на пакет:\n"
            "/play https://gotquestions.online/pack/5771"
        )
        return
    await open_pack(message, url)


@router.message(F.text.regexp(PACK_IN_TEXT))
async def pack_link(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        return
    url = message.text or ""
    if parse_pack_url(url) is None:
        return
    await open_pack(message, url)


@router.message(F.reply_to_message, F.text)
async def on_guess(message: Message) -> None:
    if not message.text or message.text.startswith("/"):
        return
    if message.from_user is not None and message.from_user.is_bot:
        return
    game = _games.get(game_key(message.chat.id, message.message_thread_id))
    reply = message.reply_to_message
    if game is None or not game.started or reply is None:
        return
    if reply.from_user is not None and not reply.from_user.is_bot:
        return
    if reply.message_id != game.question_message_id:
        await message.reply("Ответьте на сообщение с текущим вопросом.")
        return
    if game.revealed:
        await message.reply("Ответ уже открыт.")
        return
    verdict = judge(game.question, message.text)
    await message.reply(verdict_text(player_name(message), verdict))
    if verdict is Verdict.CORRECT and message.bot is not None:
        await reveal(message.bot, game, game.token, game.index)


def player_name(message: Message) -> str:
    user = message.from_user
    if user is None:
        return "Игрок"
    return user.full_name or user.username or "Игрок"


def verdict_text(name: str, verdict: Verdict) -> str:
    safe = esc(name)
    if verdict is Verdict.CORRECT:
        return f"<b>Зачёт</b>, {safe}."
    if verdict is Verdict.CLOSE:
        return f"Похоже на ответ, {safe}. Сверьте кнопкой «Показать ответ»."
    if verdict is Verdict.UNKNOWN:
        return "У этого вопроса на сайте нет ответа, сверить не получилось."
    return f"<b>Незачёт</b>, {safe}."


@router.callback_query(F.data.startswith("p:"))
async def cb_recent_pack(callback: CallbackQuery) -> None:
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        await callback.answer()
        return
    pack_id = callback.data.split(":", 1)[1]
    if not pack_id.isdigit():
        await callback.answer("Не понял номер пакета.")
        return
    await callback.answer()
    await open_pack(message, f"https://gotquestions.online/pack/{pack_id}")


@router.callback_query(F.data == "g")
async def cb_start(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        await callback.answer()
        return
    game = _games.get(game_key(message.chat.id, message.message_thread_id))
    if game is None:
        await callback.answer("Пакет уже не открыт. Пришлите ссылку ещё раз.")
        return
    await callback.answer()
    async with game.lock:
        game.index = 0
        game.token += 1
        game.started = True
        game.revealed = False
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        LOG.debug("could not hide the start button", exc_info=True)
    await show_question(callback.bot, game)


@router.callback_query(F.data.startswith("a:"))
async def cb_answer(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None or callback.data is None:
        await callback.answer()
        return
    game = _games.get(game_key(message.chat.id, message.message_thread_id))
    if game is None:
        await callback.answer("Игра уже закончилась.")
        return
    index = _callback_index(callback.data)
    if index != game.index:
        await callback.answer("Это уже не тот вопрос.")
        return
    if game.revealed:
        await callback.answer("Ответ уже открыт.")
        return
    await callback.answer()
    await reveal(callback.bot, game, game.token, game.index)


@router.callback_query(F.data.startswith("n:"))
async def cb_next(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None or callback.data is None:
        await callback.answer()
        return
    game = _games.get(game_key(message.chat.id, message.message_thread_id))
    if game is None:
        await callback.answer("Игра уже закончилась.")
        return
    index = _callback_index(callback.data)
    notice = await go_next(callback.bot, game, index)
    if notice is None:
        await callback.answer()
        return
    if notice == "":
        stop_game(message.chat.id, message.message_thread_id)
        await callback.answer()
        await message.answer("Пакет сыгран.")
        return
    await callback.answer(notice)


@router.callback_query(F.data == "s")
async def cb_stop(callback: CallbackQuery) -> None:
    message = callback.message
    await callback.answer()
    if message is None:
        return
    stopped = stop_game(message.chat.id, message.message_thread_id)
    await message.answer("Игра остановлена." if stopped else "Сейчас нет игры.")


@router.error()
async def on_error(event: ErrorEvent) -> None:
    LOG.exception("handler failed", exc_info=event.exception)
    message = event.update.message or (
        event.update.callback_query.message if event.update.callback_query else None
    )
    if isinstance(message, Message):
        try:
            await message.answer("Что-то пошло не так. Попробуйте ещё раз.")
        except Exception:
            LOG.debug("could not report handler error", exc_info=True)


def _callback_index(data: str) -> int:
    try:
        return int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return -1


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token or token.startswith("123456789:"):
        raise SystemExit(
            "В файле .env нет токена бота.\n\n"
            "1. Откройте @BotFather и отправьте /newbot.\n"
            "2. Скопируйте .env.example в .env и вставьте токен в BOT_TOKEN.\n"
            "3. Запустите снова: python -m chgk_bot\n\n"
            "Для игры в группе либо вызывайте /play со ссылкой, "
            "либо в @BotFather отключите privacy: /setprivacy → Disable, "
            "и заново добавьте бота в группу."
        )
    session = await telegram_session()
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    restored = load_games()
    _games.update(restored)
    LOG.info("restored %s games", len(restored))
    try:
        await setup_commands(bot)
        LOG.info("bot started")
        await dispatcher.start_polling(bot, drop_pending_updates=True)
    except TelegramUnauthorizedError:
        raise SystemExit(
            "Telegram не принял токен. В @BotFather отправьте /revoke, "
            "вставьте новый токен в BOT_TOKEN и запустите бота снова."
        )
    except (TelegramNetworkError, OSError):
        raise SystemExit(network_help())


async def setup_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Как играть"),
        BotCommand(command="packs", description="Свежие пакеты"),
        BotCommand(command="play", description="Открыть пакет по ссылке"),
        BotCommand(command="q", description="Перейти к вопросу: /q 12"),
        BotCommand(command="stop", description="Остановить игру"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())


def network_help() -> str:
    return (
        "Нет соединения с api.telegram.org.\n"
        "С этой сети адрес, который выдаёт DNS, не отвечает.\n"
        "Включите VPN или укажите свой прокси в .env:\n"
        "TELEGRAM_PROXY=socks5://127.0.0.1:1080"
    )


def proxy_endpoint(proxy: str) -> tuple[str, int] | None:
    parsed = urlparse(proxy)
    if not parsed.hostname or not parsed.port:
        return None
    return parsed.hostname, parsed.port


async def telegram_session() -> AiohttpSession:
    proxy = os.environ.get("TELEGRAM_PROXY", "").strip()
    endpoint = proxy_endpoint(proxy) if proxy else None
    if endpoint and await can_connect(endpoint[0], endpoint[1], timeout=2):
        LOG.info("using telegram proxy %s:%s", endpoint[0], endpoint[1])
        return AiohttpSession(proxy=proxy)
    if proxy:
        where = f"{endpoint[0]}:{endpoint[1]}" if endpoint else proxy
        LOG.warning("proxy %s is not running, connecting directly", where)
    api_ip = await reachable_api_ip()
    if api_ip is None:
        raise SystemExit(network_help())
    LOG.info("telegram api address %s", api_ip)
    session = AiohttpSession()
    session._connector_init["resolver"] = ApiResolver(api_ip)
    session._connector_init["family"] = socket.AF_INET
    return session
