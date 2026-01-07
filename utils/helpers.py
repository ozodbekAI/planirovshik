import re
from typing import Optional
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from config import config
import pytz

async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Kanal obunasini tekshirish"""
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except (TelegramForbiddenError, TelegramBadRequest):
        return False

def is_admin(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshirish"""
    return user_id in config.ADMIN_IDS

def format_time_delta(seconds: int) -> str:
    """Vaqtni formatga keltirish"""
    minutes, seconds = divmod(seconds, 60)
    if minutes > 0:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"

def truncate_text(text: str, max_length: int = 30) -> str:
    """Textni qisqartirish"""
    if not text:
        return "Без текста"
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text or "")

def format_moscow_time(time_str: str) -> str:
    """
    Vaqtni Moscow vaqti sifatida formatlash
    Input: "14:30" (database'da UTC yoki local vaqt)
    Output: "14:30" (Moscow vaqti, UTC+3)
    """
    # Agar vaqt allaqachon Moscow vaqtida saqlangan bo'lsa, shunchaki qaytarish
    return time_str

def convert_to_moscow_time(dt: datetime) -> datetime:
    """
    DateTime'ni Moscow vaqtiga o'tkazish
    """
    moscow_tz = pytz.timezone('Europe/Moscow')
    if dt.tzinfo is None:
        # Agar timezone yo'q bo'lsa, UTC deb qabul qilamiz
        dt = pytz.utc.localize(dt)
    return dt.astimezone(moscow_tz)

def get_moscow_now() -> datetime:
    """
    Hozirgi Moscow vaqtini olish
    """
    moscow_tz = pytz.timezone('Europe/Moscow')
    return datetime.now(moscow_tz)