import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
import db

load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(getenv("CHANNEL_ID", "0"))

IDEA_BUTTON_TEXT = "💡 Новая идея"
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
    builder.adjust(1)
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


async def process_idea(message: Message, idea_text: str) -> None:
    await message.answer(f"🔍 Принял в разведку: <b>«{idea_text}»</b>\n<i>Генерирую черновик...</i>")

    await asyncio.sleep(1.5)

    draft_text = (
        f"🛡 <b>Новый тул по твоей идее: {idea_text}</b>\n\n"
        "Здесь скоро будет крутая выжимка от нейросети с описанием функционала, "
        "плюсами, минусами и примерами запуска в терминале.\n\n"
        "🔗 <a href='https://github.com'>Ссылка на репозиторий</a>\n\n"
        "#security #tools #linux #osint"
    )

    post = await db.create_post(title=idea_text, content=draft_text)
    await message.answer(text=draft_text, reply_markup=get_moderation_keyboard(post.id))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет, создатель! Система Vector готова к работе.\n"
        "Нажми на кнопку внизу или используй /idea [текст].",
        reply_markup=get_main_keyboard(),
    )

@router.message(Command("idea"))
async def cmd_idea(message: Message, command: CommandObject, state: FSMContext) -> None:
    idea_text = (command.args or "").strip()

    if not idea_text:
        await message.answer(
            "⚠️ <b>Ошибка:</b> ты не написал идею!\n"
            "<i>Пример:</i> <code>/idea аналог wireshark для консоли</code>"
        )
        return

    await state.clear()
    await process_idea(message, idea_text)


@router.message(F.text == IDEA_BUTTON_TEXT)
async def btn_idea(message: Message, state: FSMContext) -> None:
    await state.set_state(IdeaStates.waiting_for_idea)
    await message.answer("Окей! Напиши тему или название утилиты для разведки:")


@router.message(IdeaStates.waiting_for_idea)
async def process_idea_from_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await process_idea(message, (message.text or "").strip())


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
async def cb_rewrite(callback: CallbackQuery) -> None:
    post_id = int(callback.data.removeprefix("rew_"))
    post = await db.get_post(post_id)

    if post is None or post.status != "pending":
        await callback.answer("Черновик не найден или уже обработан", show_alert=True)
        return

    # заглушка — реальный повторный вызов LLM появится на Этапе 3
    new_text = (
        f"🛡 <b>Новый тул по твоей идее: {post.title}</b> (переписано)\n\n"
        "Здесь скоро будет крутая выжимка от нейросети с описанием функционала, "
        "плюсами, минусами и примерами запуска в терминале.\n\n"
        "🔗 <a href='https://github.com'>Ссылка на репозиторий</a>\n\n"
        "#security #tools #linux #osint"
    )
    await db.update_post_content(post_id, new_text)

    await callback.message.edit_text(new_text, reply_markup=get_moderation_keyboard(post_id))
    await callback.answer()


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

