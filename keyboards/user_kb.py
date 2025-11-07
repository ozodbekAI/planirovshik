# ==================== keyboards/user_kb.py ====================
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config

def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    """Obuna bo'lish klaviaturasi"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔔 Подписаться на канал", url=config.CHANNEL_URL)
    )
    builder.row(
        InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")
    )
    return builder.as_markup()