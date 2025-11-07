from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.helpers import truncate_text

# keyboards/admin_kb.py

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Admin asosiy menyusi"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Управление расписанием", callback_data="admin:schedule")
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="admin:settings")  # YANGI
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")
    )
    builder.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Закрыть меню", callback_data="admin:close")
    )
    return builder.as_markup()

def get_schedule_keyboard(days: list) -> InlineKeyboardMarkup:
    """Raspisaniye klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    for day in days:
        post_count = day.get('post_count', 0)
        builder.row(
            InlineKeyboardButton(
                text=f"📆 День {day['day_number']} | {post_count} постов",
                callback_data=f"schedule:day:{day['day_number']}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить новый день", callback_data="schedule:add_day")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    return builder.as_markup()

def get_day_management_keyboard(day_number: int, posts: list) -> InlineKeyboardMarkup:
    """Kun boshqaruvi klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    post_types = {
        'text': '📝', 'photo': '🖼', 'video': '🎥',
        'video_note': '⭕', 'audio': '🎵', 'document': '📄', 
        'link': '🔗', 'voice': '🎤'
    }
    
    for post in posts:
        icon = post_types.get(post['post_type'], '📄')
        text_preview = truncate_text(post.get('content', post.get('caption', 'Без текста')))
        
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {post['time']} | {text_preview}",
                callback_data=f"post:view:{post['post_id']}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить пост", callback_data=f"post:add:{day_number}")
    )
    if posts:
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить весь день", callback_data=f"day:delete:{day_number}")
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к расписанию", callback_data="admin:schedule")
    )
    return builder.as_markup()

def get_post_type_keyboard() -> InlineKeyboardMarkup:
    """Post turi tanlash klaviaturasi"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Текстовое сообщение", callback_data="posttype:text")
    )
    builder.row(
        InlineKeyboardButton(text="🖼 Изображение", callback_data="posttype:photo")
    )
    builder.row(
        InlineKeyboardButton(text="🎥 Видео", callback_data="posttype:video")
    )
    builder.row(
        InlineKeyboardButton(text="⭕ Видео-кружок", callback_data="posttype:video_note")
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Ссылка с кнопкой", callback_data="posttype:link")
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Аудио", callback_data="posttype:audio")
    )
    builder.row(
        InlineKeyboardButton(text="🎤 Голосовое сообщение", callback_data="posttype:voice")
    )
    builder.row(
        InlineKeyboardButton(text="📄 Документ", callback_data="posttype:document")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к дню", callback_data="admin:schedule")
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
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{day_number}")
    )
    return builder.as_markup()

def get_edit_post_keyboard(post_id: int, post_type: str, day_number: int) -> InlineKeyboardMarkup:
    """Post edit klaviaturasi"""
    builder = InlineKeyboardBuilder()
    
    # Vaqtni o'zgartirish
    builder.row(
        InlineKeyboardButton(text="⏰ Изменить время", callback_data=f"post:edit_time:{post_id}")
    )
    
    # Kontentni o'zgartirish
    if post_type in ['text', 'photo', 'video', 'document', 'audio']:
        content_label = {
            'text': '📝 Изменить текст',
            'photo': '🖼 Изменить изображение',
            'video': '🎥 Изменить видео',
            'document': '📄 Изменить документ',
            'audio': '🎵 Изменить аудио'
        }.get(post_type, '📝 Изменить контент')
        
        builder.row(
            InlineKeyboardButton(text=content_label, callback_data=f"post:edit_content:{post_id}")
        )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к посту", callback_data=f"post:view:{post_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🏠 В главное меню", callback_data="admin:main")
    )
    return builder.as_markup()

def get_broadcast_type_keyboard() -> InlineKeyboardMarkup:
    """Rассылка turi klaviaturasi"""
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
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    return builder.as_markup()

def get_broadcast_target_keyboard(total_users: int, active_users: int) -> InlineKeyboardMarkup:
    """Rассылка maqsadi klaviaturasi"""
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