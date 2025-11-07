# handlers/admin.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
import re

from database.base import User, ScheduleDay, SchedulePost, UserProgress
from keyboards.admin_kb import (
    get_admin_main_keyboard,
    get_schedule_keyboard,
    get_day_management_keyboard,
    get_post_type_keyboard,
    get_post_actions_keyboard,
    get_edit_post_keyboard
)
from utils.texts import Texts
from utils.helpers import is_admin, truncate_text, format_moscow_time

router = Router(name="admin_router")

# FSM States
class AddDay(StatesGroup):
    waiting_day_number = State()

class AddPost(StatesGroup):
    day_number = State()
    waiting_time = State()
    waiting_type = State()
    waiting_content = State()
    waiting_caption = State()
    waiting_link_url = State()
    waiting_button_text = State()

class EditPost(StatesGroup):
    post_id = State()
    waiting_field = State()
    waiting_time = State()
    waiting_content = State()
    waiting_caption = State()

# ============== ADMIN PANEL ==============

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin panel"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        Texts.ADMIN_PANEL,
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin:main")
async def admin_main_callback(callback: CallbackQuery):
    """Admin asosiy menyu"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    await callback.message.edit_text(
        Texts.ADMIN_PANEL,
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin:close")
async def admin_close_callback(callback: CallbackQuery):
    """Admin menyuni yopish"""
    await callback.message.delete()
    await callback.answer()

# ============== SCHEDULE MANAGEMENT ==============

@router.callback_query(F.data == "admin:schedule")
async def schedule_management(callback: CallbackQuery, session: AsyncSession):
    """Raspisaniye boshqaruvi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    result = await session.execute(
        select(ScheduleDay).order_by(ScheduleDay.day_number)
    )
    days = result.scalars().all()
    
    days_data = []
    for day in days:
        post_result = await session.execute(
            select(func.count(SchedulePost.post_id)).where(
                SchedulePost.day_number == day.day_number
            )
        )
        post_count = post_result.scalar()
        days_data.append({
            'day_number': day.day_number,
            'post_count': post_count
        })
    
    if not days_data:
        days_list = "📭 <i>Расписание пустое. Добавьте первый день.</i>"
    else:
        days_list = ""
        for day in days_data:
            days_list += f"📆 День {day['day_number']} | {day['post_count']} постов\n"
    
    await callback.message.edit_text(
        Texts.SCHEDULE_MANAGEMENT.format(days_list=days_list),
        reply_markup=get_schedule_keyboard(days_data),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "schedule:add_day")
async def add_day_start(callback: CallbackQuery, state: FSMContext):
    """Yangi kun qo'shish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к расписанию", callback_data="admin:schedule")]
    ])
    
    await callback.message.edit_text(
        "📅 <b>Добавление нового дня</b>\n\n"
        "Введите номер дня (например: 1, 2, 3...):",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(AddDay.waiting_day_number)
    await callback.answer()

@router.message(AddDay.waiting_day_number)
async def add_day_number(message: Message, state: FSMContext, session: AsyncSession):
    """Kun raqamini qabul qilish"""
    try:
        day_number = int(message.text)
        
        if day_number < 1:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к расписанию", callback_data="admin:schedule")]
            ])
            await message.answer(
                "❌ Номер дня должен быть больше 0.",
                reply_markup=back_kb
            )
            return
        
        result = await session.execute(
            select(ScheduleDay).where(ScheduleDay.day_number == day_number)
        )
        existing_day = result.scalar_one_or_none()
        
        if existing_day:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к расписанию", callback_data="admin:schedule")]
            ])
            await message.answer(
                f"❌ День {day_number} уже существует.",
                reply_markup=back_kb
            )
            return
        
        new_day = ScheduleDay(day_number=day_number)
        session.add(new_day)
        await session.commit()
        
        await message.answer(
            f"✅ День {day_number} успешно добавлен!",
            reply_markup=get_admin_main_keyboard()
        )
        await state.clear()
        
    except ValueError:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к расписанию", callback_data="admin:schedule")]
        ])
        await message.answer(
            "❌ Введите корректный номер дня (число).",
            reply_markup=back_kb
        )

@router.callback_query(F.data.startswith("schedule:day:"))
async def view_day(callback: CallbackQuery, session: AsyncSession):
    """Kunni ko'rish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    day_number = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(SchedulePost).where(
            SchedulePost.day_number == day_number
        ).order_by(SchedulePost.time, SchedulePost.order_number)
    )
    posts = result.scalars().all()
    
    if not posts:
        posts_list = "📭 <i>Постов пока нет</i>"
    else:
        post_types = {
            'text': '📝', 'photo': '🖼', 'video': '🎥',
            'video_note': '⭕', 'audio': '🎵', 'document': '📄',
            'link': '🔗', 'voice': '🎤'
        }
        
        posts_list = ""
        for i, post in enumerate(posts, 1):
            type_name = post_types.get(post.post_type, '📄')
            content_preview = truncate_text(
                post.content or post.caption or "Без текста"
            )
            # Rossiya vaqtini ko'rsatish
            moscow_time = format_moscow_time(post.time)
            posts_list += f"{i}️⃣ {moscow_time} (МСК) | {type_name} | \"{content_preview}\"\n"
    
    posts_data = [
        {
            'post_id': post.post_id,
            'post_type': post.post_type,
            'time': post.time,
            'content': post.content,
            'caption': post.caption
        }
        for post in posts
    ]
    
    await callback.message.edit_text(
        Texts.DAY_MANAGEMENT.format(
            day_number=day_number,
            posts_list=posts_list
        ),
        reply_markup=get_day_management_keyboard(day_number, posts_data),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("day:delete:"))
async def delete_day(callback: CallbackQuery, session: AsyncSession):
    """Kunni o'chirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    day_number = int(callback.data.split(":")[2])
    
    await session.execute(
        delete(SchedulePost).where(SchedulePost.day_number == day_number)
    )
    await session.execute(
        delete(ScheduleDay).where(ScheduleDay.day_number == day_number)
    )
    await session.commit()
    
    await callback.answer(f"✅ День {day_number} удален", show_alert=True)
    await schedule_management(callback, session)

# ============== POST MANAGEMENT ==============

@router.callback_query(F.data.startswith("post:add:"))
async def add_post_start(callback: CallbackQuery, state: FSMContext):
    """Post qo'shish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    day_number = int(callback.data.split(":")[2])
    
    await state.update_data(day_number=day_number)
    await state.set_state(AddPost.waiting_time)
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{day_number}")]
    ])
    
    await callback.message.edit_text(
        "⏰ <b>В какое время отправить пост?</b>\n\n"
        "Введите время по Москве в формате <code>ЧЧ:ММ</code>\n"
        "Например: <code>14:30</code> или <code>09:00</code>\n\n"
        "🕐 Часовой пояс: Москва (UTC+3)",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AddPost.waiting_time)
async def add_post_time(message: Message, state: FSMContext):
    """Vaqtni qabul qilish"""
    time_pattern = r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'
    
    if not re.match(time_pattern, message.text):
        data = await state.get_data()
        day_number = data['day_number']
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{day_number}")]
        ])
        await message.answer(
            "❌ Неверный формат времени. Используйте формат ЧЧ:ММ\n"
            "Например: 14:30",
            reply_markup=back_kb
        )
        return
    
    await state.update_data(time=message.text)
    await state.set_state(AddPost.waiting_type)
    
    await message.answer(
        "📋 <b>Выберите тип контента:</b>",
        reply_markup=get_post_type_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("posttype:"))
async def add_post_type(callback: CallbackQuery, state: FSMContext):
    """Post turini tanlash"""
    post_type = callback.data.split(":")[1]
    
    await state.update_data(post_type=post_type)
    await state.set_state(AddPost.waiting_content)
    
    type_instructions = {
        'text': "📝 Отправьте текст сообщения.\n\nВы можете использовать форматирование:\n• <b>жирный</b>\n• <i>курсив</i>\n• <code>код</code>",
        'photo': "🖼 Отправьте изображение.\n\n✅ Без ограничений по размеру (используется Bot API)",
        'video': "🎥 Отправьте видео-файл.\n\n✅ Без ограничений по размеру (используется Bot API)",
        'video_note': "⭕ Отправьте видео-кружок.\n\nЗапишите через кнопку в Telegram.",
        'audio': "🎵 Отправьте аудио-файл.\n\nФорматы: MP3, M4A, OGG",
        'document': "📄 Отправьте документ.\n\n✅ Без ограничений по размеру (используется Bot API)",
        'link': "🔗 Отправьте текст сообщения.\n\nСсылку добавим на следующем шаге.",
        'voice': "🎤 Отправьте голосовое сообщение.\n\nЗапишите через кнопку в Telegram."
    }
    
    instruction = type_instructions.get(post_type, "Отправьте контент:")
    
    data = await state.get_data()
    day_number = data['day_number']
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{day_number}")]
    ])
    
    await callback.message.edit_text(
        instruction,
        parse_mode="HTML",
        reply_markup=back_kb
    )
    await callback.answer()

@router.message(AddPost.waiting_content)
async def add_post_content(message: Message, state: FSMContext, session: AsyncSession):
    """Kontent qabul qilish"""
    data = await state.get_data()
    post_type = data['post_type']
    
    content = None
    file_id = None
    caption = None
    
    if post_type == 'text' or post_type == 'link':
        if not message.text:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте текст сообщения.", reply_markup=back_kb)
            return
        content = message.text
        
        if post_type == 'link':
            await state.update_data(content=content)
            await state.set_state(AddPost.waiting_link_url)
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer(
                "🔗 <b>Шаг 2 из 3</b>\n\n"
                "Введите URL-адрес:\n"
                "Например: https://example.com",
                reply_markup=back_kb,
                parse_mode="HTML"
            )
            return
    
    elif post_type == 'photo':
        if not message.photo:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте изображение.", reply_markup=back_kb)
            return
        file_id = message.photo[-1].file_id
        caption = message.caption
    
    elif post_type == 'video':
        if not message.video:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте видео.", reply_markup=back_kb)
            return
        file_id = message.video.file_id
        caption = message.caption
    
    elif post_type == 'video_note':
        if not message.video_note:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте видео-кружок.", reply_markup=back_kb)
            return
        file_id = message.video_note.file_id
    
    elif post_type == 'audio':
        if not message.audio and not message.voice:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте аудио.", reply_markup=back_kb)
            return
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        caption = message.caption
    
    elif post_type == 'document':
        if not message.document:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте документ.", reply_markup=back_kb)
            return
        file_id = message.document.file_id
        caption = message.caption
    
    elif post_type == 'voice':
        if not message.voice:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
            ])
            await message.answer("❌ Отправьте голосовое сообщение.", reply_markup=back_kb)
            return
        file_id = message.voice.file_id
        caption = message.caption
    
    day_number = data['day_number']
    time = data['time']
    
    new_post = SchedulePost(
        day_number=day_number,
        post_type=post_type,
        content=content,
        file_id=file_id,
        caption=caption,
        time=time
    )
    session.add(new_post)
    await session.commit()
    
    moscow_time = format_moscow_time(time)
    await message.answer(
        f"✅ <b>Пост успешно добавлен!</b>\n\n"
        f"📆 День: {day_number}\n"
        f"⏰ Время: {moscow_time} (МСК)\n"
        f"📝 Тип: {post_type}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

@router.message(AddPost.waiting_link_url)
async def add_post_link_url(message: Message, state: FSMContext):
    """Havola URLni qabul qilish"""
    data = await state.get_data()
    url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
    
    if not re.match(url_pattern, message.text):
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
        ])
        await message.answer(
            "❌ Введите корректный URL.\nПример: https://example.com",
            reply_markup=back_kb
        )
        return
    
    await state.update_data(link_url=message.text)
    await state.set_state(AddPost.waiting_button_text)
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=f"schedule:day:{data['day_number']}")]
    ])
    
    await message.answer(
        "🔗 <b>Шаг 3 из 3</b>\n\n"
        "Введите текст кнопки:\n"
        "Например: \"Перейти к материалам\"",
        reply_markup=back_kb,
        parse_mode="HTML"
    )

@router.message(AddPost.waiting_button_text)
async def add_post_button_text(message: Message, state: FSMContext, session: AsyncSession):
    """Tugma textini qabul qilish va saqlash"""
    button_text = message.text
    data = await state.get_data()
    
    buttons = {
        'inline': [
            [{'text': button_text, 'url': data['link_url']}]
        ]
    }
    
    new_post = SchedulePost(
        day_number=data['day_number'],
        post_type='link',
        content=data['content'],
        time=data['time'],
        buttons=buttons
    )
    session.add(new_post)
    await session.commit()
    
    moscow_time = format_moscow_time(data['time'])
    await message.answer(
        f"✅ <b>Пост со ссылкой успешно добавлен!</b>\n\n"
        f"📆 День: {data['day_number']}\n"
        f"⏰ Время: {moscow_time} (МСК)\n"
        f"🔗 Ссылка: {data['link_url']}\n"
        f"🔘 Кнопка: {button_text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

# ============== POST ACTIONS ==============

@router.callback_query(F.data.startswith("post:view:"))
async def view_post(callback: CallbackQuery, session: AsyncSession):
    """Postni ko'rish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    post_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        await callback.answer("❌ Пост не найден")
        return
    
    # Postni ko'rsatish
    try:
        if post.post_type == 'text':
            await callback.message.answer(
                f"👁 <b>ПРЕДПРОСМОТР:</b>\n\n{post.content}",
                parse_mode="HTML"
            )
        elif post.post_type == 'photo':
            await callback.message.answer_photo(
                photo=post.file_id,
                caption=f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}",
                parse_mode="HTML"
            )
        elif post.post_type == 'video':
            await callback.message.answer_video(
                video=post.file_id,
                caption=f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}",
                parse_mode="HTML"
            )
        elif post.post_type == 'video_note':
            await callback.message.answer_video_note(video_note=post.file_id)
        elif post.post_type == 'audio':
            await callback.message.answer_audio(
                audio=post.file_id,
                caption=f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}",
                parse_mode="HTML"
            )
        elif post.post_type == 'document':
            await callback.message.answer_document(
                document=post.file_id,
                caption=f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}",
                parse_mode="HTML"
            )
        elif post.post_type == 'voice':
            await callback.message.answer_voice(
                voice=post.file_id,
                caption=f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}",
                parse_mode="HTML"
            )
        elif post.post_type == 'link':
            buttons = post.buttons
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=buttons['inline'][0][0]['text'],
                        url=buttons['inline'][0][0]['url']
                    )]
                ]
            )
            await callback.message.answer(
                f"👁 <b>ПРЕДПРОСМОТР:</b>\n\n{post.content}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        # Harakatlar menyusini ko'rsatish
        await callback.message.answer(
            "🎛 <b>Действия с постом:</b>",
            reply_markup=get_post_actions_keyboard(post_id, post.day_number),
            parse_mode="HTML"
        )
        await callback.answer("✅ Предпросмотр отправлен")
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("post:edit:"))
async def edit_post_menu(callback: CallbackQuery, session: AsyncSession):
    """Post edit menyusi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    post_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        await callback.answer("❌ Пост не найден")
        return
    
    moscow_time = format_moscow_time(post.time)
    await callback.message.edit_text(
        f"✏️ <b>РЕДАКТИРОВАНИЕ ПОСТА</b>\n\n"
        f"📆 День: {post.day_number}\n"
        f"⏰ Время: {moscow_time} (МСК)\n"
        f"📝 Тип: {post.post_type}\n\n"
        f"Выберите, что хотите изменить:",
        reply_markup=get_edit_post_keyboard(post_id, post.post_type, post.day_number),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("post:edit_time:"))
async def edit_post_time_start(callback: CallbackQuery, state: FSMContext):
    """Vaqtni o'zgartirish"""
    post_id = int(callback.data.split(":")[2])
    
    await state.update_data(post_id=post_id, edit_field='time')
    await state.set_state(EditPost.waiting_time)
    
    await callback.message.edit_text(
        "⏰ <b>Изменение времени</b>\n\n"
        "Введите новое время по Москве в формате <code>ЧЧ:ММ</code>\n"
        "Например: <code>14:30</code>\n\n"
        "🕐 Часовой пояс: Москва (UTC+3)",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(EditPost.waiting_time)
async def edit_post_time_save(message: Message, state: FSMContext, session: AsyncSession):
    """Vaqtni saqlash"""
    time_pattern = r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'

    if not re.match(time_pattern, message.text):
        await message.answer("❌ Неверный формат времени. Используйте ЧЧ:ММ")
        return
    
    data = await state.get_data()
    post_id = data['post_id']
    
    result = await session.execute(
        select(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if post:
        post.time = message.text
        await session.commit()
        
        moscow_time = format_moscow_time(message.text)
        await message.answer(
            f"✅ Время изменено на {moscow_time} (МСК)",
            reply_markup=get_admin_main_keyboard()
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("post:edit_content:"))
async def edit_post_content_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Kontentni o'zgartirish"""
    post_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        await callback.answer("❌ Пост не найден")
        return
    
    await state.update_data(post_id=post_id, edit_field='content', post_type=post.post_type)
    await state.set_state(EditPost.waiting_content)
    
    if post.post_type == 'text':
        await callback.message.edit_text(
            "📝 <b>Изменение текста</b>\n\n"
            "Отправьте новый текст:",
            parse_mode="HTML"
        )
    elif post.post_type in ['photo', 'video', 'document', 'audio']:
        await callback.message.edit_text(
            f"🖼 <b>Изменение {post.post_type}</b>\n\n"
            f"Отправьте новый файл:",
            parse_mode="HTML"
        )
    
    await callback.answer()

@router.message(EditPost.waiting_content)
async def edit_post_content_save(message: Message, state: FSMContext, session: AsyncSession):
    """Kontentni saqlash"""
    data = await state.get_data()
    post_id = data['post_id']
    post_type = data['post_type']
    
    result = await session.execute(
        select(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        await message.answer("❌ Пост не найден")
        await state.clear()
        return
    
    if post_type == 'text':
        if message.text:
            post.content = message.text
            await session.commit()
            await message.answer("✅ Текст изменен!", reply_markup=get_admin_main_keyboard())
    elif post_type == 'photo':
        if message.photo:
            post.file_id = message.photo[-1].file_id
            post.caption = message.caption
            await session.commit()
            await message.answer("✅ Изображение изменено!", reply_markup=get_admin_main_keyboard())
    elif post_type == 'video':
        if message.video:
            post.file_id = message.video.file_id
            post.caption = message.caption
            await session.commit()
            await message.answer("✅ Видео изменено!", reply_markup=get_admin_main_keyboard())
    elif post_type == 'document':
        if message.document:
            post.file_id = message.document.file_id
            post.caption = message.caption
            await session.commit()
            await message.answer("✅ Документ изменен!", reply_markup=get_admin_main_keyboard())
    elif post_type == 'audio':
        if message.audio:
            post.file_id = message.audio.file_id
            post.caption = message.caption
            await session.commit()
            await message.answer("✅ Аудио изменено!", reply_markup=get_admin_main_keyboard())
    
    await state.clear()

@router.callback_query(F.data.startswith("post:delete:"))
async def delete_post(callback: CallbackQuery, session: AsyncSession):
    """Postni o'chirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    post_id = int(callback.data.split(":")[2])
    
    await session.execute(
        delete(SchedulePost).where(SchedulePost.post_id == post_id)
    )
    await session.commit()
    
    await callback.answer("✅ Пост удален", show_alert=True)
    await callback.message.delete()

# handlers/admin.py (qo'shimcha)

from database.crud import get_setting, update_setting

class EditSettings(StatesGroup):
    waiting_welcome = State()
    waiting_subscribe_request = State()
    waiting_subscription_confirmed = State()


@router.callback_query(F.data == "admin:settings")
async def admin_settings(callback: CallbackQuery):
    """Admin sozlamalari"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Изменить Welcome сообщение", callback_data="settings:edit:welcome")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Изменить текст подписки", callback_data="settings:edit:subscribe")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Подтверждение подписки", callback_data="settings:edit:confirmed")
    )
    builder.row(
        InlineKeyboardButton(text="👁 Просмотр текущих текстов", callback_data="settings:view")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    
    await callback.message.edit_text(
        "⚙️ <b>НАСТРОЙКИ БОТА</b>\n\n"
        "Выберите, что хотите изменить:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "settings:view")
async def view_settings(callback: CallbackQuery):
    """Joriy sozlamalarni ko'rish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    welcome_text = await get_setting('welcome_text', Texts.WELCOME)
    subscribe_text = await get_setting('subscribe_request', Texts.SUBSCRIBE_REQUEST)
    confirmed_text = await get_setting('subscription_confirmed', Texts.SUBSCRIPTION_CONFIRMED)
    
    preview = (
        "👁 <b>ТЕКУЩИЕ ТЕКСТЫ</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>Welcome сообщение:</b>\n\n"
        f"{welcome_text[:200]}...\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "2️⃣ <b>Запрос подписки:</b>\n\n"
        f"{subscribe_text[:200]}...\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "3️⃣ <b>Подтверждение:</b>\n\n"
        f"{confirmed_text[:200]}..."
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:settings")
    )
    
    await callback.message.edit_text(
        preview,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "settings:edit:welcome")
async def edit_welcome_start(callback: CallbackQuery, state: FSMContext):
    """Welcome textni o'zgartirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    current_text = await get_setting('welcome_text', Texts.WELCOME)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin:settings")
    )
    
    await callback.message.edit_text(
        "✏️ <b>ИЗМЕНЕНИЕ WELCOME СООБЩЕНИЯ</b>\n\n"
        "📝 <b>Текущий текст:</b>\n\n"
        f"{current_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Отправьте новый текст сообщения.\n\n"
        "💡 <b>Доступные переменные:</b>\n"
        "• <code>{name}</code> - имя пользователя\n\n"
        "📌 Поддерживается HTML-форматирование:\n"
        "• <code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
        "• <code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
        "• <code>&lt;code&gt;код&lt;/code&gt;</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await state.set_state(EditSettings.waiting_welcome)
    await callback.answer()


@router.message(EditSettings.waiting_welcome)
async def save_welcome_text(message: Message, state: FSMContext):
    """Welcome textni saqlash"""
    new_text = message.html_text
    
    await update_setting('welcome_text', new_text)
    
    await message.answer(
        "✅ <b>Welcome сообщение успешно обновлено!</b>\n\n"
        "📝 <b>Новый текст:</b>\n\n"
        f"{new_text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()


@router.callback_query(F.data == "settings:edit:subscribe")
async def edit_subscribe_start(callback: CallbackQuery, state: FSMContext):
    """Obuna textini o'zgartirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    current_text = await get_setting('subscribe_request', Texts.SUBSCRIBE_REQUEST)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin:settings")
    )
    
    await callback.message.edit_text(
        "✏️ <b>ИЗМЕНЕНИЕ ТЕКСТА ПОДПИСКИ</b>\n\n"
        "📝 <b>Текущий текст:</b>\n\n"
        f"{current_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Отправьте новый текст сообщения.\n\n"
        "📌 Поддерживается HTML-форматирование.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await state.set_state(EditSettings.waiting_subscribe_request)
    await callback.answer()


@router.message(EditSettings.waiting_subscribe_request)
async def save_subscribe_text(message: Message, state: FSMContext):
    """Obuna textini saqlash"""
    new_text = message.html_text
    
    await update_setting('subscribe_request', new_text)
    
    await message.answer(
        "✅ <b>Текст подписки успешно обновлен!</b>",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()


@router.callback_query(F.data == "settings:edit:confirmed")
async def edit_confirmed_start(callback: CallbackQuery, state: FSMContext):
    """Tasdiqlash textini o'zgartirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    current_text = await get_setting('subscription_confirmed', Texts.SUBSCRIPTION_CONFIRMED)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin:settings")
    )
    
    await callback.message.edit_text(
        "✏️ <b>ИЗМЕНЕНИЕ ТЕКСТА ПОДТВЕРЖДЕНИЯ</b>\n\n"
        "📝 <b>Текущий текст:</b>\n\n"
        f"{current_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Отправьте новый текст сообщения.\n\n"
        "📌 Поддерживается HTML-форматирование.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    await state.set_state(EditSettings.waiting_subscription_confirmed)
    await callback.answer()


@router.message(EditSettings.waiting_subscription_confirmed)
async def save_confirmed_text(message: Message, state: FSMContext):
    """Tasdiqlash textini saqlash"""
    new_text = message.html_text
    
    await update_setting('subscription_confirmed', new_text)
    
    await message.answer(
        "✅ <b>Текст подтверждения успешно обновлен!</b>",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()