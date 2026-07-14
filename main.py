import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, Filter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
ADMIN_ID = int(getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(getenv("CHANNEL_ID", "0"))

router = Router()

pending_posts = {}

class AdminProtectFilter(Filter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        return obj.from_user.id == ADMIN_ID

router.message.filter(AdminProtectFilter())
router.callback_query.filter(AdminProtectFilter())

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

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 Привет, создатель! Система Recon готова к работе.\nИспользуй `/idea [текст]` для создания поста.")


@router.message(Command("idea"))
async def cmd_idea(message: Message):
    idea_text = message.text.replace("/idea", "").strip()

    if not idea_text:
        return await message.answer(
            "⚠️ <b>Ошибка:</b> Ты не написал идею!\n<i>Пример:</i> <code>/idea аналог wireshark для консоли</code>")

    await message.answer(f"🔍 Принял в разведку: <b>«{idea_text}»</b>\n<i>Генерирую черновик...</i>")

    await asyncio.sleep(1.5)
    post_id = str(len(pending_posts) + 1)
    draft_text = (
        f"🛡 <b>Новый тул по твоей идее: {idea_text}</b>\n\n"
        f"Здесь скоро будет крутая выжимка от нейросети с описанием функционала, "
        f"плюсами, минусами и примерами запуска в терминале.\n\n"
        f"🔗 <a href='https://github.com'>Ссылка на репозиторий</a>\n\n"
        f"#security #tools #linux #osint"
    )

    pending_posts[post_id] = draft_text
    await message.answer(text=draft_text, reply_markup=get_moderation_keyboard(post_id))


@router.callback_query(F.data.startswith("pub_"))
async def cmd_pub_(callback: CallbackQuery, bot: Bot):
    post_id = callback.data.removeprefix("pub_")
    draft_text = pending_posts.get(post_id)
    if draft_text is None:
        await callback.answer("Черновик не найден (уже обработан?)", show_alert=True)
        return
    sent = await bot.send_message(chat_id=CHANNEL_ID, text=draft_text)

    await callback.message.edit_text(
        f"✅ <b>Опубликовано в канал</b> (id поста: {sent.message_id})"
    )
    await callback.answer("Готово!")
    pending_posts.pop(post_id, None)


@router.callback_query(F.data.startswith("rew_"))
async def cmd_rew_(callback: CallbackQuery, bot: Bot):
    post_id = callback.data.removeprefix("rew_")

    if post_id not in pending_posts:
        await callback.answer("Черновик не найден или уже обработан", show_alert=True)
        return

    draft_text = (
        f"🛡 <b>Новый тул по твоей идее: gthtgbcsdftv</b>\n\n"
        f"Здесь скоро будет крутая выжимка от нейросети с описанием функционала, "
        f"плюсами, минусами и примерами запуска в терминале.\n\n"
        f"🔗 <a href='https://github.com'>Ссылка на репозиторий</a>\n\n"
        f"#security #tools #linux #osint"
    )

    pending_posts[post_id] = draft_text

    await callback.message.edit_text(draft_text, reply_markup=get_moderation_keyboard(post_id))
    await callback.answer()


@router.callback_query(F.data.startswith("rej_"))
async def cb_reject(callback: CallbackQuery) -> None:
    post_id = callback.data.removeprefix("rej_")

    await callback.message.edit_text("🗑 <b>Черновик отклонён</b>")
    await callback.answer()
    pending_posts.pop(post_id, None)

async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)  # <-- без этой строки хендлеры никогда не сработают

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

