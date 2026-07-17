import asyncio
import logging
import time
from os import getenv
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.methods import SendMessageDraft
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message, ReplyKeyboardMarkup,
)
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
import db
import llm
import search

load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(getenv("CHANNEL_ID", "0"))

IDEA_BUTTON_TEXT = "💡 Новая идея"
RANDOM_BUTTON_TEXT = "🎲 Придумай сам"
router = Router()

class IdeaStates(StatesGroup):
    waiting_for_idea = State()


class AdminProtectFilter(Filter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        return obj.from_user.id == ADMIN_ID

router.message.filter(AdminProtectFilter())
router.callback_query.filter(AdminProtectFilter())

def get_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=IDEA_BUTTON_TEXT)
    builder.button(text=RANDOM_BUTTON_TEXT)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_moderation_keyboard(post_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"pub_{post_id}"),
            InlineKeyboardButton(text="✏️ Переписать", callback_data=f"rew_{post_id}")
        ],
        [
            InlineKeyboardButton(text="🗑 Отклонить", callback_data=f"rej_{post_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_tags_for_preview(text: str) -> str:
    return _TAG_RE.sub("", text)

async def safe_send(message: Message, text: str, post_id: int) -> None:
    try:
        await message.answer(text=text, reply_markup=get_moderation_keyboard(post_id))
    except TelegramBadRequest:
        logging.warning("LLM сгенерировала невалидный HTML, отправляю как обычный текст")
        await message.answer(
            text=text, reply_markup=get_moderation_keyboard(post_id), parse_mode=None
        )


async def process_idea(message: Message, idea_text: str, bot: Bot) -> None:
    await message.answer(f"🔍 Принял в разведку: <b>«{idea_text}»</b>")
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        try:
            results = await search.web_search(idea_text)
        except Exception:
            logging.exception("Ошибка при поиске")
            await message.answer("⚠️ Не получилось найти информацию. Попробуй ещё раз.")
            return
    draft_id = int(time.time() * 1000) % (2 ** 31) or 1
    final_text = ""
    last_update = 0.0

    try:
        async for partial in llm.generate_post_stream(idea_text, results):
            final_text = partial

            now = time.monotonic()
            if now - last_update < 0.4:  # не долбим Telegram чаще ~2 раз/сек
                continue
            last_update = now

            try:
                await bot(
                    SendMessageDraft(
                        chat_id=message.chat.id,
                        draft_id=draft_id,
                        text=_strip_tags_for_preview(partial)[:4000],
                    )
                )
            except TelegramBadRequest:
                pass  # кадр анимации не критичен, пропускаем и едем дальше
    except Exception:
        logging.exception("Ошибка при генерации поста")
        await message.answer("⚠️ Не получилось сгенерировать пост. Попробуй ещё раз чуть позже.")
        return

    if not final_text.strip():
        await message.answer("⚠️ Модель вернула пустой ответ. Попробуй переформулировать идею.")
        return

    post = await db.create_post(title=idea_text, content=final_text)
    await safe_send(message, final_text, post.id)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет, создатель! Система Vector готова к работе.\n"
        f"«{IDEA_BUTTON_TEXT}» — сам предложи тему.\n"
        f"«{RANDOM_BUTTON_TEXT}» — модель придумает тему сама.\n"
        "Либо сразу /idea [текст].",
        reply_markup=get_main_keyboard(),
    )

@router.message(Command("idea"))
async def cmd_idea(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    idea_text = (command.args or "").strip()

    if not idea_text:
        await message.answer(
            "⚠️ <b>Ошибка:</b> ты не написал идею!\n"
            "<i>Пример:</i> <code>/idea аналог wireshark для консоли</code>"
        )
        return

    await state.clear()
    await process_idea(message, idea_text, bot)


@router.message(F.text == IDEA_BUTTON_TEXT)
async def btn_idea(message: Message, state: FSMContext) -> None:
    await state.set_state(IdeaStates.waiting_for_idea)
    await message.answer("Окей! Напиши тему или название утилиты для разведки:")


@router.message(IdeaStates.waiting_for_idea)
async def process_idea_from_state(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await process_idea(message, (message.text or "").strip(), bot)


@router.message(F.text == RANDOM_BUTTON_TEXT)
async def btn_random(message: Message, bot: Bot) -> None:
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        try:
            recent_titles = await db.get_recent_titles()
            topic = await llm.brainstorm_topic(recent_titles)
        except Exception:
            logging.exception("Ошибка при подборе темы")
            await message.answer("⚠️ Не получилось придумать тему. Попробуй ещё раз.")
            return

    await process_idea(message, topic, bot)


@router.callback_query(F.data.startswith("pub_"))
async def cb_publish(callback: CallbackQuery, bot: Bot) -> None:
    post_id = int(callback.data.removeprefix("pub_"))
    post = await db.get_post(post_id)

    if post is None or post.status != "pending":
        await callback.answer("Черновик не найден или уже обработан", show_alert=True)
        return

    sent = await bot.send_message(chat_id=CHANNEL_ID, text=post.content)
    await db.set_post_status(post_id, "published")

    await callback.message.edit_text(f"✅ <b>Опубликовано в канал</b> (id поста: {sent.message_id})")
    await callback.answer("Готово!")


@router.callback_query(F.data.startswith("rew_"))
async def cb_rewrite(callback: CallbackQuery, bot: Bot) -> None:
    post_id = int(callback.data.removeprefix("rew_"))
    post = await db.get_post(post_id)

    if post is None or post.status != "pending":
        await callback.answer("Черновик не найден или уже обработан", show_alert=True)
        return

    await callback.answer("Переписываю...")

    async with ChatActionSender.typing(bot=bot, chat_id=callback.message.chat.id):
        try:
            new_text = await llm.rewrite_post(post.content)
        except Exception:
            logging.exception("Ошибка при переписывании поста")
            await callback.message.answer("⚠️ Не получилось переписать пост. Попробуй ещё раз.")
            return

    await db.update_post_content(post_id, new_text)

    try:
        await callback.message.edit_text(new_text, reply_markup=get_moderation_keyboard(post_id))
    except TelegramBadRequest:
        await callback.message.edit_text(
            new_text, reply_markup=get_moderation_keyboard(post_id), parse_mode=None
        )


@router.callback_query(F.data.startswith("rej_"))
async def cb_reject(callback: CallbackQuery) -> None:
    post_id = int(callback.data.removeprefix("rej_"))
    await db.set_post_status(post_id, "rejected")

    await callback.message.edit_text("🗑 <b>Черновик отклонён</b>")
    await callback.answer()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await db.init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

