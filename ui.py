import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

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


async def safe_send_to(bot: Bot, chat_id: int, text: str, post_id: int) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=get_moderation_keyboard(post_id))
    except TelegramBadRequest:
        logging.warning("LLM сгенерировала невалидный HTML, отправляю как обычный текст")
        await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=get_moderation_keyboard(post_id), parse_mode=None
        )


async def safe_send(message: Message, text: str, post_id: int) -> None:
    await safe_send_to(message.bot, message.chat.id, text, post_id)