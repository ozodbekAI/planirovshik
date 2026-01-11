# keyboards/admin_kb.py - UPDATED VERSION

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Admin asosiy menyu - UPDATED"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🚀 День запуска", callback_data="launch:view")
    )
    builder.row(
        InlineKeyboardButton(text="📅 Расписание", callback_data="admin:schedule")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Анкеты", callback_data="admin:surveys")  # NEW
    )
    builder.row(
        InlineKeyboardButton(text="📚 Уроки", callback_data="admin:lessons")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")
    )
    builder.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Закрыть", callback_data="admin:close")
    )
    
    return builder.as_markup()


def get_lesson_post_type_keyboard(back_callback: str = "admin:lessons") -> InlineKeyboardMarkup:
    """Urok uchun post type tanlash klaviaturasi.

    "Den" (schedule) dagi post turlari bilan bir xil qilib kengaytirilgan.
    Callback prefix: lessonposttype:<type>
    """
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="📝 Текст", callback_data="lessonposttype:text"))
    builder.row(
        InlineKeyboardButton(text="🖼 Фото", callback_data="lessonposttype:photo"),
        InlineKeyboardButton(text="🎥 Видео", callback_data="lessonposttype:video"),
    )
    builder.row(
        InlineKeyboardButton(text="📄 Документ", callback_data="lessonposttype:document"),
        InlineKeyboardButton(text="🎵 Аудио", callback_data="lessonposttype:audio"),
    )
    builder.row(
        InlineKeyboardButton(text="🎤 Голосовое", callback_data="lessonposttype:voice"),
        InlineKeyboardButton(text="⭕ Кружок", callback_data="lessonposttype:video_note"),
    )
    builder.row(InlineKeyboardButton(text="🔗 Ссылка", callback_data="lessonposttype:link"))
    builder.row(InlineKeyboardButton(text="✅ Проверка подписки", callback_data="lessonposttype:subscription_check"))
    builder.row(InlineKeyboardButton(text="📋 Анкета", callback_data="lessonposttype:survey"))

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=back_callback))

    return builder.as_markup()


def get_post_type_keyboard() -> InlineKeyboardMarkup:
    """Post turi tanlash klaviaturasi - UPDATED"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📝 Текст", callback_data="posttype:text")
    )
    builder.row(
        InlineKeyboardButton(text="🖼 Фото", callback_data="posttype:photo"),
        InlineKeyboardButton(text="🎥 Видео", callback_data="posttype:video")
    )
    builder.row(
        InlineKeyboardButton(text="📄 Документ", callback_data="posttype:document"),
        InlineKeyboardButton(text="🎵 Аудио", callback_data="posttype:audio")
    )
    builder.row(
        InlineKeyboardButton(text="🎤 Голосовое", callback_data="posttype:voice"),
        InlineKeyboardButton(text="⭕ Кружок", callback_data="posttype:video_note")
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Ссылка", callback_data="posttype:link")
    )
    builder.row(
        InlineKeyboardButton(text="✅ Проверка подписки", callback_data="posttype:subscription_check")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Анкета", callback_data="posttype:survey")  # NEW
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin:main")
    )
    
    return builder.as_markup()


def get_survey_selection_keyboard(surveys: list, day_number: int) -> InlineKeyboardMarkup:
    """Anketa tanlash uchun klaviatura"""
    builder = InlineKeyboardBuilder()
    
    for survey in surveys:
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {survey.name}",
                callback_data=f"select_survey:{survey.survey_id}:{day_number}"
            )
        )
    
    if day_number == 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ Отмена", callback_data="launch:view")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"schedule:day:{day_number}")
        )
    
    return builder.as_markup()


# Keep all other functions from the original file...
def get_launch_day_keyboard(posts: list) -> InlineKeyboardMarkup:
    """Клавиатура для Дня запуска"""
    builder = InlineKeyboardBuilder()

    # Настройки
    builder.row(
        InlineKeyboardButton(
            text="✏️ Изменить Welcome сообщение",
            callback_data="settings:edit:welcome"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Изменить текст подписки",
            callback_data="settings:edit:subscribe"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Подтверждение подписки",
            callback_data="settings:edit:confirmed"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="👁 Просмотр текущих текстов",
            callback_data="settings:view"
        )
    )

    # Список постов
    for i, post in enumerate(posts, 1):
        delay_text = f"{post.delay_seconds}s" if post.delay_seconds else "0s"
        post_type_emoji = {
            "text": "📝",
            "photo": "🖼",
            "video": "🎥",
            "survey": "📋",  # NEW
            "subscription_check": "✅",
            "link": "🔗",
        }.get(post.post_type, "📄")
        
        builder.row(
            InlineKeyboardButton(
                text=f"{i}. {post_type_emoji} {post.post_type} ({delay_text})",
                callback_data=f"post:view:{post.post_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="➕ Добавить пост", callback_data="post:add:launch")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_schedule_keyboard(days_data: List[Dict]) -> InlineKeyboardMarkup:
    """Barcha kunlar uchun klaviatura"""
    builder = InlineKeyboardBuilder()
    
    for day in days_data:
        if day['day_number'] > 0:
            builder.row(
                InlineKeyboardButton(
                    text=f"День {day['day_number']} ({day['post_count']} постов)",
                    callback_data=f"schedule:day:{day['day_number']}"
                )
            )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить день", callback_data="schedule:add_day")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    
    return builder.as_markup()


def get_day_management_keyboard(day_number: int, posts_data: List[Dict]) -> InlineKeyboardMarkup:
    """Bitta kun uchun boshqaruv klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    for i, post in enumerate(posts_data, 1):
        post_type_emoji = {
            'text': '📝', 'photo': '🖼', 'video': '🎥',
            'video_note': '⭕', 'audio': '🎵', 'document': '📄',
            'link': '🔗', 'voice': '🎤', 'survey': '📋'  # NEW
        }.get(post['post_type'], '📄')
        
        builder.row(
            InlineKeyboardButton(
                text=f"{i}. {post_type_emoji} {post['time']}",
                callback_data=f"post:view:{post['post_id']}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить пост", callback_data=f"post:add:{day_number}")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить день", callback_data=f"day:delete:{day_number}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:schedule")
    )
    
    return builder.as_markup()


def get_post_actions_keyboard(post_id: int, day_number: int) -> InlineKeyboardMarkup:
    """Post harakatlari klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"post:edit:{post_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить пост", callback_data=f"post:delete:{post_id}")
    )
    
    if day_number == 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ К дню запуска", callback_data="launch:view")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="⬅️ К дню", callback_data=f"schedule:day:{day_number}")
        )
    
    return builder.as_markup()


def get_edit_post_keyboard(post_id: int, post_type: str, day_number: int) -> InlineKeyboardMarkup:
    """Post tahrirlash klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    if day_number == 0:
        builder.row(
            InlineKeyboardButton(text="⏱ Изменить задержку", callback_data=f"post:edit_delay:{post_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="⏰ Изменить время", callback_data=f"post:edit_time:{post_id}")
        )
    
    # Survey uchun content o'zgartirish kerак emas
    if post_type != "survey":
        builder.row(
            InlineKeyboardButton(text="📝 Изменить контент", callback_data=f"post:edit_content:{post_id}")
        )
    
    if day_number == 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ К дню запуска", callback_data="launch:view")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="⬅️ К дню", callback_data=f"schedule:day:{day_number}")
        )
    
    return builder.as_markup()


def get_stats_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Общая статистика", callback_data="stats:general")
    )
    builder.row(
        InlineKeyboardButton(text="📈 По дням", callback_data="stats:by_days")
    )
    builder.row(
        InlineKeyboardButton(text="👥 Активные пользователи", callback_data="stats:active")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")
    )
    return builder.as_markup()


def get_broadcast_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Текст", callback_data="broadcast:type:text")
    )
    builder.row(
        InlineKeyboardButton(text="🖼 Изображение", callback_data="broadcast:type:photo")
    )
    builder.row(
        InlineKeyboardButton(text="🎥 Видео", callback_data="broadcast:type:video")
    )
    builder.row(
        InlineKeyboardButton(text="📄 Документ", callback_data="broadcast:type:document")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Анкета", callback_data="broadcast:type:survey")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    return builder.as_markup()


def get_broadcast_target_keyboard(total_users: int, active_users: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"👥 Всем пользователям ({total_users} чел.)",
            callback_data="broadcast:target:all"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"✅ Только активным ({active_users} чел.)",
            callback_data="broadcast:target:active"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔥 На определенном дне прогрева",
            callback_data="broadcast:target:day"
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    return builder.as_markup()