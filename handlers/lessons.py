import asyncio
import re
from typing import Optional
from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from config import config
from database.base import Lesson, LessonPost, Survey
from keyboards.admin_kb import get_admin_main_keyboard, get_lesson_post_type_keyboard, get_survey_selection_keyboard
from utils.helpers import is_admin, truncate_text
from utils.telegram_html import repair_telegram_html, safe_answer_html

router = Router(name="lessons_router")


# ===================== FSM =====================

class CreateLesson(StatesGroup):
    waiting_name = State()


class AddLessonPost(StatesGroup):
    waiting_type = State()
    waiting_survey = State()
    waiting_content = State()
    waiting_link_url = State()
    waiting_button_text = State()


class EditLessonPost(StatesGroup):
    waiting_content = State()
    waiting_link_url = State()
    waiting_button_text = State()


# ===================== HELPERS =====================

def get_lesson_deep_link(bot_username: str, lesson_id: int) -> str:
    return f"https://t.me/{bot_username}?start=urok_{lesson_id}"


def get_bot_link(bot_username: str) -> str:
    """Oddiy bot silka (start parametrisiz)."""
    return f"https://t.me/{bot_username}"


def get_prefilled_message_link(bot_username: str, message_text: str) -> str:
    """Link that opens a chat with the bot and pre-fills the input field with text.

    Telegram may shorten/transform this link (e.g., into https://t.me/m/...) when copied from the app.
    """
    return f"https://t.me/{bot_username}?text={quote(message_text, safe='')}"



def _type_emoji(post_type: str) -> str:
    return {
        "text": "📝",
        "photo": "🖼",
        "video": "🎥",
        "video_note": "⭕",
        "audio": "🎵",
        "document": "📄",
        "voice": "🎤",
        "link": "🔗",
        "subscription_check": "✅",
        "survey": "📋",
    }.get(post_type, "📄")


def get_lessons_list_keyboard(lessons: list[Lesson]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for lesson in lessons:
        builder.row(
            InlineKeyboardButton(
                text=f"📚 {lesson.name}",
                callback_data=f"lesson:open:{lesson.lesson_id}",
            )
        )

    builder.row(InlineKeyboardButton(text="➕ Добавить урок", callback_data="lesson:create"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main"))

    return builder.as_markup()


def get_lesson_manage_keyboard(lesson_id: int, posts: list[LessonPost]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for i, post in enumerate(posts, 1):
        builder.row(
            InlineKeyboardButton(
                text=f"{i}. {_type_emoji(post.post_type)} {post.post_type}",
                callback_data=f"lpost:view:{post.post_id}",
            )
        )

    builder.row(InlineKeyboardButton(text="➕ Добавить пост", callback_data=f"lpost:add:{lesson_id}"))
    builder.row(
        InlineKeyboardButton(text="👁 Предпросмотр урока", callback_data=f"lesson:preview:{lesson_id}"),
        InlineKeyboardButton(text="🗑 Удалить урок", callback_data=f"lesson:delete_confirm:{lesson_id}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ К урокам", callback_data="admin:lessons"))

    return builder.as_markup()


def get_delete_confirm_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"lesson:delete:{lesson_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"lesson:open:{lesson_id}"),
    )
    return builder.as_markup()


def get_lesson_post_actions_keyboard(post_id: int, lesson_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"lpost:edit:{post_id}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить пост", callback_data=f"lpost:delete:{post_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}"))
    return builder.as_markup()


def get_lesson_post_edit_keyboard(post_id: int, post_type: str, lesson_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if post_type == "link":
        builder.row(InlineKeyboardButton(text="🔗 Изменить ссылку", callback_data=f"lpost:edit_link:{post_id}"))
    elif post_type == "survey":
        builder.row(InlineKeyboardButton(text="📋 Изменить анкету", callback_data=f"lpost:edit_survey:{post_id}"))
    else:
        builder.row(InlineKeyboardButton(text="✏️ Изменить контент", callback_data=f"lpost:edit_content:{post_id}"))

    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lpost:view:{post_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}"))

    return builder.as_markup()


async def _get_next_lesson_order(session: AsyncSession, lesson_id: int) -> int:
    result = await session.execute(
        select(func.max(LessonPost.order_number)).where(LessonPost.lesson_id == lesson_id)
    )
    max_order = result.scalar_one_or_none() or 0
    return int(max_order) + 1


async def _send_single_post(message: Message, post: LessonPost, session: AsyncSession):
    """Send LessonPost to current chat (supports same types as schedule)."""

    # survey
    if post.post_type == "survey":
        if not post.survey_id:
            await message.answer("❌ Анкета не привязана к посту", parse_mode="HTML")
            return

        res = await session.execute(select(Survey).where(Survey.survey_id == post.survey_id))
        survey = res.scalar_one_or_none()
        if not survey or not survey.is_active:
            await message.answer("❌ Анкета недоступна", parse_mode="HTML")
            return

        # IMPORTANT:
        # We do NOT use /start survey_<id> here to keep the same UX as lessons:
        # - site link is plain bot link
        # - user opens a specific entity by sending a normal text message.
        # So we open the bot with a prefilled message (user still presses Send).
        # Use a stable prefilled message that is always understood by the bot,
        # regardless of how the survey is named.
        prefill = get_prefilled_message_link(config.BOT_USERNAME, f"Анкета {survey.survey_id}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[ 
                InlineKeyboardButton(
                    text=survey.button_text,
                    url=prefill,
                )
            ]]
        )

        # If survey has photo configured
        if getattr(survey, "message_photo_file_id", None):
            await message.answer_photo(
                photo=survey.message_photo_file_id,
                caption=repair_telegram_html(survey.start_text or ""),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await safe_answer_html(
                message,
                repair_telegram_html(survey.start_text or ""),
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        return

    # subscription_check -> just send text (buttons are usually handled elsewhere)
    if post.post_type == "subscription_check":
        await safe_answer_html(
            message,
            repair_telegram_html(post.content or ""),
            disable_web_page_preview=True,
        )
        return

    # link
    if post.post_type == "link":
        keyboard = None
        if post.buttons:
            try:
                btn = post.buttons["inline"][0][0]
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])]]
                )
            except Exception:
                keyboard = None

        await safe_answer_html(
            message,
            repair_telegram_html(post.content or ""),
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        return

    # text
    if post.post_type == "text":
        await safe_answer_html(
            message,
            repair_telegram_html(post.content or ""),
            disable_web_page_preview=True,
        )
        return

    # photo
    if post.post_type == "photo":
        await message.answer_photo(
            photo=post.file_id,
            caption=repair_telegram_html(post.caption) if post.caption else None,
            parse_mode="HTML" if post.caption else None,
        )
        return

    # video
    if post.post_type == "video":
        await message.answer_video(
            video=post.file_id,
            caption=repair_telegram_html(post.caption) if post.caption else None,
            parse_mode="HTML" if post.caption else None,
        )
        return

    # video note
    if post.post_type == "video_note":
        await message.answer_video_note(video_note=post.file_id)
        return

    # audio
    if post.post_type == "audio":
        await message.answer_audio(
            audio=post.file_id,
            caption=repair_telegram_html(post.caption) if post.caption else None,
            parse_mode="HTML" if post.caption else None,
        )
        return

    # document
    if post.post_type == "document":
        await message.answer_document(
            document=post.file_id,
            caption=repair_telegram_html(post.caption) if post.caption else None,
            parse_mode="HTML" if post.caption else None,
        )
        return

    # voice
    if post.post_type == "voice":
        await message.answer_voice(
            voice=post.file_id,
            caption=repair_telegram_html(post.caption) if post.caption else None,
            parse_mode="HTML" if post.caption else None,
        )
        return

    await message.answer("❌ Неподдерживаемый тип поста", parse_mode="HTML")


async def send_lesson_to_chat(message: Message, lesson_id: int, session: AsyncSession, *, with_delays: bool = False):
    """Send lesson to current chat. If with_delays=True, respects delay_seconds between posts."""

    res = await session.execute(select(Lesson).where(Lesson.lesson_id == lesson_id))
    lesson = res.scalar_one_or_none()

    if not lesson or not lesson.is_active:
        await message.answer("❌ Урок недоступен", parse_mode="HTML")
        return

    posts_res = await session.execute(
        select(LessonPost).where(LessonPost.lesson_id == lesson_id).order_by(LessonPost.order_number.asc())
    )
    posts = posts_res.scalars().all()

    # Backward compatibility: if no posts yet but old single-content exists
    if not posts and lesson.post_type:
        # emulate as a single post
        tmp = LessonPost(
            lesson_id=lesson.lesson_id,
            post_type=lesson.post_type,
            content=lesson.content,
            file_id=lesson.file_id,
            caption=lesson.caption,
            buttons=lesson.buttons,
            delay_seconds=0,
            order_number=1,
        )
        posts = [tmp]

    if not posts:
        await message.answer("⚠️ Урок пока пустой. Админ не добавил посты.", parse_mode="HTML")
        return

    for idx, post in enumerate(posts):
        if with_delays and idx > 0:
            delay = int(post.delay_seconds or 0)
            if delay > 0:
                await asyncio.sleep(delay)
        await _send_single_post(message, post, session)


# ===================== ADMIN: LIST =====================

@router.callback_query(F.data == "admin:lessons")
async def lessons_main_menu(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    result = await session.execute(select(Lesson).order_by(Lesson.created_at.desc()))
    lessons = result.scalars().all()

    text = (
        "📚 <b>УРОКИ</b>\n\n"
        "Уроки — это отдельные наборы постов (как 'День запуска').\n"
        "Админ создаёт урок и наполняет его постами (текст/медиа/ссылка/анкета).\n\n"
        "Для сайта даётся обычная ссылка на бота (без /start), а урок открывается сообщением с названием урока "
        "(например: <code>Урок 3</code>)."
    )

    if not lessons:
        text += "\n\n📭 Уроков пока нет. Нажмите «Добавить урок»."

    await callback.message.edit_text(
        text,
        reply_markup=get_lessons_list_keyboard(lessons),
        parse_mode="HTML",
    )
    await callback.answer()


# ===================== ADMIN: CREATE LESSON =====================

@router.callback_query(F.data == "lesson:create")
async def lesson_create_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    await state.clear()
    await state.set_state(CreateLesson.waiting_name)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin:lessons")]]
    )

    await callback.message.edit_text(
        "➕ <b>Создание урока</b>\n\nВведите название урока:\nНапример: <code>Урок 2</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CreateLesson.waiting_name)
async def lesson_create_name(message: Message, state: FSMContext, session: AsyncSession):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return

    name = (message.text or "").strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    lesson = Lesson(name=name, is_active=True)
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)

    bot_link = get_bot_link(config.BOT_USERNAME)
    prefill_link = get_prefilled_message_link(config.BOT_USERNAME, lesson.name)

    await message.answer(
        "✅ <b>Урок создан!</b>\n\n"
        f"📚 Название: {lesson.name}\n\n"
        f"🔗 Ссылка для сайта (без /start):\n<code>{bot_link}</code>\n\n"
        "📝 Ссылка с готовым сообщением (в поле ввода уже будет текст урока):\n"
        f"<code>{prefill_link}</code>\n\n"
        "📩 Текст для открытия урока (можно просто отправить в бот):\n"
        f"<code>{lesson.name}</code>\n\n"
        "(Опционально: можно использовать короткий код, если название будет меняться)\n"
        f"<code>urok {lesson.lesson_id}</code>\n"
        f"<code>urok_{lesson.lesson_id}</code>\n\n"
        "Теперь добавьте посты в урок (как в 'День запуска').",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить пост", callback_data=f"lpost:add:{lesson.lesson_id}")],
                [InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson.lesson_id}")],
            ]
        ),
        parse_mode="HTML",
    )

    await state.clear()


# ===================== ADMIN: OPEN LESSON =====================

@router.callback_query(F.data.startswith("lesson:open:"))
async def lesson_open(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    lesson_id = int(callback.data.split(":")[2])

    res = await session.execute(select(Lesson).where(Lesson.lesson_id == lesson_id))
    lesson = res.scalar_one_or_none()
    if not lesson:
        await callback.answer("❌ Урок не найден")
        return

    posts_res = await session.execute(
        select(LessonPost).where(LessonPost.lesson_id == lesson_id).order_by(LessonPost.order_number.asc())
    )
    posts = posts_res.scalars().all()

    bot_link = get_bot_link(config.BOT_USERNAME)
    prefill_link = get_prefilled_message_link(config.BOT_USERNAME, lesson.name)

    text = (
        f"📚 <b>{lesson.name}</b>\n\n"
        f"🆔 ID: <code>{lesson.lesson_id}</code>\n\n"
        f"🔗 Ссылка для сайта (без /start):\n<code>{bot_link}</code>\n\n"
        "📝 Ссылка с готовым сообщением (в поле ввода уже будет текст урока):\n"
        f"<code>{prefill_link}</code>\n\n"
        "📩 Текст для открытия урока:\n"
        f"<code>{lesson.name}</code>\n\n"
        "(Опционально: короткий код)\n"
        f"<code>urok {lesson.lesson_id}</code>\n"
        f"<code>urok_{lesson.lesson_id}</code>\n\n"
        f"📦 Постов в уроке: <b>{len(posts)}</b>\n"
    )

    if not posts and lesson.post_type:
        text += "\n⚠️ Сейчас у урока заполнен только старый 1-постовый формат. Лучше добавить посты через 'Добавить пост'."

    await callback.message.edit_text(
        text,
        reply_markup=get_lesson_manage_keyboard(lesson_id, posts),
        parse_mode="HTML",
    )
    await callback.answer()


# ===================== ADMIN: PREVIEW LESSON =====================

@router.callback_query(F.data.startswith("lesson:preview:"))
async def lesson_preview(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    lesson_id = int(callback.data.split(":")[2])

    await callback.message.answer("👁 <b>ПРЕДПРОСМОТР УРОКА:</b>", parse_mode="HTML")
    await send_lesson_to_chat(callback.message, lesson_id, session, with_delays=False)

    await callback.answer("✅ Предпросмотр отправлен")


# ===================== ADMIN: DELETE LESSON =====================

@router.callback_query(F.data.startswith("lesson:delete_confirm:"))
async def lesson_delete_confirm(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    lesson_id = int(callback.data.split(":")[2])

    res = await session.execute(select(Lesson).where(Lesson.lesson_id == lesson_id))
    lesson = res.scalar_one_or_none()
    if not lesson:
        await callback.answer("❌ Урок не найден")
        return

    await callback.message.edit_text(
        f"🗑 Удалить урок <b>{lesson.name}</b>?\n\nЭто действие необратимо.",
        reply_markup=get_delete_confirm_keyboard(lesson_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lesson:delete:"))
async def lesson_delete(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    lesson_id = int(callback.data.split(":")[2])

    await session.execute(delete(Lesson).where(Lesson.lesson_id == lesson_id))
    await session.commit()

    await callback.answer("✅ Удалено")

    # back to list
    result = await session.execute(select(Lesson).order_by(Lesson.created_at.desc()))
    lessons = result.scalars().all()

    await callback.message.edit_text(
        "📚 <b>УРОКИ</b>\n\nУрок удалён.",
        reply_markup=get_lessons_list_keyboard(lessons),
        parse_mode="HTML",
    )


# ===================== ADMIN: ADD POST TO LESSON =====================

@router.callback_query(F.data.startswith("lpost:add:"))
async def lesson_add_post_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    lesson_id = int(callback.data.split(":")[2])

    # Ensure lesson exists
    res = await session.execute(select(Lesson).where(Lesson.lesson_id == lesson_id))
    lesson = res.scalar_one_or_none()
    if not lesson:
        await callback.answer("❌ Урок не найден")
        return

    await state.clear()
    await state.update_data(lesson_id=lesson_id)
    await state.set_state(AddLessonPost.waiting_type)

    await callback.message.edit_text(
        "📋 <b>Выберите тип контента (как в Дне запуска):</b>",
        reply_markup=get_lesson_post_type_keyboard(back_callback=f"lesson:open:{lesson_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lessonposttype:"))
async def lesson_add_post_type(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_type = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lesson_id = data.get("lesson_id")

    if not lesson_id:
        await callback.answer("❌ Ошибка состояния")
        await state.clear()
        return

    # Special: survey selection
    if post_type == "survey":
        result = await session.execute(
            select(Survey).where(Survey.is_active == True).order_by(Survey.created_at.desc())
        )
        surveys = result.scalars().all()
        if not surveys:
            await callback.answer(
                "❌ Нет доступных анкет. Сначала создайте анкету в разделе 'Анкеты'",
                show_alert=True,
            )
            return

        # Move to "waiting_survey" state so a survey can be selected either
        # by tapping an inline button (callback) or by sending its name as text.
        await state.set_state(AddLessonPost.waiting_survey)

        await callback.message.edit_text(
            "📋 <b>Выберите анкету:</b>\n\nКакую анкету добавить в этот урок?",
            reply_markup=_lesson_survey_selection_keyboard(surveys, lesson_id),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(post_type=post_type)
    await state.set_state(AddLessonPost.waiting_content)

    type_instructions = {
        "text": "📝 Отправьте текст сообщения.\n\n💡 Поддерживается HTML-форматирование.",
        "photo": "🖼 Отправьте изображение. Можно добавить подпись.",
        "video": "🎥 Отправьте видео-файл. Можно добавить подпись.",
        "video_note": "⭕ Отправьте видео-кружок.",
        "audio": "🎵 Отправьте аудио-файл.",
        "document": "📄 Отправьте документ.",
        "link": "🔗 Шаг 1 из 3\n\nОтправьте текст сообщения (подпись), который будет над кнопкой.",
        "voice": "🎤 Отправьте голосовое сообщение. (Если Telegram добавит подпись, мы тоже сохраним)",
        "subscription_check": "✅ Отправьте текст для проверки подписки.",
    }

    await callback.message.edit_text(type_instructions.get(post_type, "Отправьте контент:"), parse_mode="HTML")
    await callback.answer()


def _lesson_survey_selection_keyboard(surveys: list[Survey], lesson_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in surveys:
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {s.name}",
                callback_data=f"lesson_select_survey:{s.survey_id}:{lesson_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"lpost:add:{lesson_id}"))
    return builder.as_markup()


@router.callback_query(F.data.startswith("lesson_select_survey:"))
async def lesson_select_survey(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    parts = callback.data.split(":")
    survey_id = int(parts[1])
    lesson_id = int(parts[2])

    order_number = await _get_next_lesson_order(session, lesson_id)

    new_post = LessonPost(
        lesson_id=lesson_id,
        post_type="survey",
        survey_id=survey_id,
        delay_seconds=0,
        order_number=order_number,
    )
    session.add(new_post)
    await session.commit()

    await state.clear()

    await callback.message.answer(
        "✅ <b>Анкета добавлена в урок!</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}")]]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddLessonPost.waiting_survey)
async def lesson_select_survey_by_text(message: Message, state: FSMContext, session: AsyncSession):
    """Allow selecting a survey by sending its name while in lesson survey selection step.

    This prevents 'Update is not handled' logs if the admin types the survey name instead of tapping the inline button.
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return

    data = await state.get_data()
    lesson_id = data.get("lesson_id")
    if not lesson_id:
        await message.answer("❌ Ошибка состояния")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Напишите название анкеты или выберите её кнопкой ниже.")
        return

    # 1) Try by exact name (case-insensitive)
    res = await session.execute(
        select(Survey).where(func.lower(Survey.name) == text.lower(), Survey.is_active == True)
    )
    survey = res.scalar_one_or_none()

    # 2) Fallback: parse trailing number and try by id
    if not survey:
        m = re.search(r"(\d+)$", text)
        if m:
            try:
                sid = int(m.group(1))
                res2 = await session.execute(
                    select(Survey).where(Survey.survey_id == sid, Survey.is_active == True)
                )
                survey = res2.scalar_one_or_none()
            except Exception:
                survey = None

    if not survey:
        # Show available surveys again
        result = await session.execute(
            select(Survey).where(Survey.is_active == True).order_by(Survey.created_at.desc())
        )
        surveys = result.scalars().all()
        if not surveys:
            await message.answer("❌ Нет активных анкет")
            await state.clear()
            return

        await message.answer(
            "❌ Анкета не найдена. Выберите анкету кнопкой ниже или отправьте точное название.",
            reply_markup=_lesson_survey_selection_keyboard(surveys, int(lesson_id)),
        )
        return

    order_number = await _get_next_lesson_order(session, int(lesson_id))
    new_post = LessonPost(
        lesson_id=int(lesson_id),
        post_type="survey",
        survey_id=survey.survey_id,
        delay_seconds=0,
        order_number=order_number,
    )
    session.add(new_post)
    await session.commit()

    await state.clear()
    await message.answer(
        "✅ <b>Анкета добавлена в урок!</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}")]]
        ),
        parse_mode="HTML",
    )


@router.message(AddLessonPost.waiting_content)
async def lesson_add_post_content(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    lesson_id = data.get("lesson_id")
    post_type = data.get("post_type")

    if not lesson_id or not post_type:
        await message.answer("❌ Ошибка состояния. Вернитесь в /admin")
        await state.clear()
        return

    content: Optional[str] = None
    file_id: Optional[str] = None
    caption: Optional[str] = None

    if post_type in ("text", "subscription_check"):
        if not message.text:
            await message.answer("❌ Отправьте текст сообщения.")
            return
        content = message.text

    elif post_type == "photo":
        if not message.photo:
            await message.answer("❌ Отправьте изображение.")
            return
        file_id = message.photo[-1].file_id
        caption = message.caption

    elif post_type == "video":
        if not message.video:
            await message.answer("❌ Отправьте видео.")
            return
        file_id = message.video.file_id
        caption = message.caption

    elif post_type == "video_note":
        if not message.video_note:
            await message.answer("❌ Отправьте видео-кружок.")
            return
        file_id = message.video_note.file_id

    elif post_type == "audio":
        if not message.audio and not message.voice:
            await message.answer("❌ Отправьте аудио.")
            return
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        caption = message.caption

    elif post_type == "document":
        if not message.document:
            await message.answer("❌ Отправьте документ.")
            return
        file_id = message.document.file_id
        caption = message.caption

    elif post_type == "voice":
        if not message.voice:
            await message.answer("❌ Отправьте голосовое сообщение.")
            return
        file_id = message.voice.file_id
        caption = message.caption

    elif post_type == "link":
        if not message.text:
            await message.answer("❌ Отправьте текст сообщения.")
            return
        content = message.text

        await state.update_data(content=content)
        await state.set_state(AddLessonPost.waiting_link_url)
        await message.answer(
            "🔗 <b>Шаг 2 из 3</b>\n\nВведите URL-адрес:\nНапример: https://example.com",
            parse_mode="HTML",
        )
        return



    order_number = await _get_next_lesson_order(session, lesson_id)

    new_post = LessonPost(
        lesson_id=lesson_id,
        post_type=post_type,
        content=content,
        file_id=file_id,
        caption=caption,
        delay_seconds=0,
        buttons=None,
        survey_id=None,
        order_number=order_number,
    )

    session.add(new_post)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>Пост добавлен в урок!</b>\n\n"
        f"📚 Урок ID: <code>{lesson_id}</code>\n"
        f"📝 Тип: <code>{post_type}</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}")]]
        ),
        parse_mode="HTML",
    )


@router.message(AddLessonPost.waiting_link_url)
async def lesson_add_post_link_url(message: Message, state: FSMContext):
    url_pattern = r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)"

    if not message.text or not re.match(url_pattern, message.text.strip()):
        await message.answer("❌ Введите корректное URL.\nПример: https://example.com")
        return

    await state.update_data(link_url=message.text.strip())
    await state.set_state(AddLessonPost.waiting_button_text)

    await message.answer(
        "🔘 <b>Шаг 3 из 3</b>\n\nВведите текст кнопки:\nНапример: \"Перейти к материалам\"",
        parse_mode="HTML",
    )


@router.message(AddLessonPost.waiting_button_text)
async def lesson_add_post_button_text(message: Message, state: FSMContext, session: AsyncSession):
    button_text = (message.text or "").strip()
    if not button_text:
        await message.answer("❌ Текст кнопки не может быть пустым")
        return

    data = await state.get_data()
    link_url = data.get("link_url")
    if not link_url:
        await message.answer("❌ Ошибка состояния")
        await state.clear()
        return

    buttons = {"inline": [[{"text": button_text, "url": link_url}]]}


    # Save link post immediately (no delay step for lessons)
    lesson_id = data.get("lesson_id")
    post_type = data.get("post_type") or "link"

    if not lesson_id:
        await message.answer("❌ Ошибка состояния")
        await state.clear()
        return

    order_number = await _get_next_lesson_order(session, int(lesson_id))

    new_post = LessonPost(
        lesson_id=int(lesson_id),
        post_type=post_type,
        content=data.get("content"),
        file_id=None,
        caption=None,
        delay_seconds=0,
        buttons=buttons,
        survey_id=None,
        order_number=order_number,
    )

    session.add(new_post)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>Пост добавлен в урок!</b>\n\n"
        f"📚 Урок ID: <code>{lesson_id}</code>\n"
        f"📝 Тип: <code>{post_type}</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}")]]
        ),
        parse_mode="HTML",
    )




# ===================== ADMIN: VIEW/EDIT/DELETE LESSON POSTS =====================

@router.callback_query(F.data.startswith("lpost:view:"))
async def lesson_post_view(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post:
        await callback.answer("❌ Пост не найден")
        return

    # Preview
    try:
        if post.post_type == "text":
            await safe_answer_html(
                callback.message,
                f"👁 <b>ПРЕДПРОСМОТР:</b>\n\n{repair_telegram_html(post.content or '')}",
                disable_web_page_preview=True,
            )
        elif post.post_type == "photo":
            cap = f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}"
            await callback.message.answer_photo(
                photo=post.file_id,
                caption=repair_telegram_html(cap),
                parse_mode="HTML",
            )
        elif post.post_type == "video":
            cap = f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}"
            await callback.message.answer_video(
                video=post.file_id,
                caption=repair_telegram_html(cap),
                parse_mode="HTML",
            )
        elif post.post_type == "video_note":
            await callback.message.answer_video_note(video_note=post.file_id)
        elif post.post_type == "audio":
            cap = f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}"
            await callback.message.answer_audio(
                audio=post.file_id,
                caption=repair_telegram_html(cap),
                parse_mode="HTML",
            )
        elif post.post_type == "document":
            cap = f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}"
            await callback.message.answer_document(
                document=post.file_id,
                caption=repair_telegram_html(cap),
                parse_mode="HTML",
            )
        elif post.post_type == "voice":
            cap = f"👁 <b>ПРЕДПРОСМОТР</b>\n\n{post.caption or ''}"
            await callback.message.answer_voice(
                voice=post.file_id,
                caption=repair_telegram_html(cap) if post.caption else None,
                parse_mode="HTML" if post.caption else None,
            )
        elif post.post_type == "link":
            keyboard = None
            if post.buttons:
                try:
                    btn = post.buttons["inline"][0][0]
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=btn["text"], url=btn["url"])]]
                    )
                except Exception:
                    keyboard = None
            await safe_answer_html(
                callback.message,
                f"👁 <b>ПРЕДПРОСМОТР:</b>\n\n{repair_telegram_html(post.content or '')}",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        elif post.post_type == "survey":
            if post.survey_id:
                sres = await session.execute(select(Survey).where(Survey.survey_id == post.survey_id))
                survey = sres.scalar_one_or_none()
                if survey:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[[
                            InlineKeyboardButton(
                                text=survey.button_text,
                                url=f"https://t.me/{config.BOT_USERNAME}?start=survey_{survey.survey_id}",
                            )
                        ]]
                    )
                    await callback.message.answer(
                        f"👁 <b>ПРЕДПРОСМОТР АНКЕТЫ:</b>\n\n📋 {survey.name}\n\nНажмите кнопку для заполнения:",
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                else:
                    await callback.answer("❌ Анкета не найдена", show_alert=True)
                    return
            else:
                await callback.answer("❌ Анкета не привязана", show_alert=True)
                return
        else:
            await callback.message.answer("❌ Неподдерживаемый тип", parse_mode="HTML")

        await callback.message.answer(
            "🎛 <b>Действия с постом:</b>",
            reply_markup=get_lesson_post_actions_keyboard(post.post_id, post.lesson_id),
            parse_mode="HTML",
        )
        await callback.answer("✅ Предпросмотр отправлен")

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("lpost:edit:"))
async def lesson_post_edit_menu(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post:
        await callback.answer("❌ Пост не найден")
        return

    await callback.message.edit_text(
        "✏️ <b>РЕДАКТИРОВАНИЕ ПОСТА УРОКА</b>\n\n"
        f"📚 Урок: <code>{post.lesson_id}</code>\n"
        f"📝 Тип: <code>{post.post_type}</code>\n"
        "Выберите, что хотите изменить:",
        reply_markup=get_lesson_post_edit_keyboard(post.post_id, post.post_type, post.lesson_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lpost:edit_content:"))
async def lesson_post_edit_content_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post:
        await callback.answer("❌ Пост не найден")
        return

    await state.clear()
    await state.update_data(post_id=post_id, post_type=post.post_type)
    await state.set_state(EditLessonPost.waiting_content)

    if post.post_type == "text":
        prompt = "📝 <b>Изменение текста</b>\n\nОтправьте новый текст:"
    elif post.post_type in ["photo", "video", "document", "audio", "voice", "video_note"]:
        prompt = f"📎 <b>Изменение контента</b>\n\nОтправьте новый файл ({post.post_type}).\n\n✅ Если это видео/фото/документ/аудио — подпись (caption) тоже сохранится."
    else:
        prompt = "Отправьте новый контент:"

    await callback.message.edit_text(prompt, parse_mode="HTML")
    await callback.answer()


@router.message(EditLessonPost.waiting_content)
async def lesson_post_edit_content_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post_id = data.get("post_id")
    post_type = data.get("post_type")

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post:
        await message.answer("❌ Пост не найден")
        await state.clear()
        return

    if post_type == "text":
        if not message.text:
            await message.answer("❌ Отправьте текст")
            return
        post.content = message.text

    elif post_type == "photo":
        if not message.photo:
            await message.answer("❌ Отправьте фото")
            return
        post.file_id = message.photo[-1].file_id
        post.caption = message.caption

    elif post_type == "video":
        if not message.video:
            await message.answer("❌ Отправьте видео")
            return
        post.file_id = message.video.file_id
        post.caption = message.caption

    elif post_type == "video_note":
        if not message.video_note:
            await message.answer("❌ Отправьте видео-кружок")
            return
        post.file_id = message.video_note.file_id
        post.caption = None

    elif post_type == "audio":
        if not message.audio and not message.voice:
            await message.answer("❌ Отправьте аудио")
            return
        post.file_id = message.audio.file_id if message.audio else message.voice.file_id
        post.caption = message.caption

    elif post_type == "document":
        if not message.document:
            await message.answer("❌ Отправьте документ")
            return
        post.file_id = message.document.file_id
        post.caption = message.caption

    elif post_type == "voice":
        if not message.voice:
            await message.answer("❌ Отправьте голосовое")
            return
        post.file_id = message.voice.file_id
        post.caption = message.caption

    else:
        await message.answer("❌ Этот тип нельзя редактировать через 'контент'.")
        await state.clear()
        return

    await session.commit()

    await message.answer(
        "✅ Контент изменён!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К посту", callback_data=f"lpost:view:{post_id}")]]
        ),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data.startswith("lpost:edit_link:"))
async def lesson_post_edit_link_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post or post.post_type != "link":
        await callback.answer("❌ Пост не найден или не является ссылкой")
        return

    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(EditLessonPost.waiting_content)

    await callback.message.edit_text(
        "🔗 <b>Изменение ссылки</b>\n\nШаг 1 из 3: отправьте новый текст сообщения (над кнопкой).",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(EditLessonPost.waiting_content)
async def lesson_post_edit_link_step1(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post_id = data.get("post_id")

    # If this state is used for non-link editing, handler above will clear or continue.
    # Here we detect if the post is link and we are in the link-edit flow.
    if not post_id:
        return

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post or post.post_type != "link":
        return

    if not message.text:
        await message.answer("❌ Отправьте текст сообщения.")
        return

    await state.update_data(new_content=message.text)
    await state.set_state(EditLessonPost.waiting_link_url)

    await message.answer(
        "🔗 <b>Шаг 2 из 3</b>\n\nВведите новый URL:\nНапример: https://example.com",
        parse_mode="HTML",
    )


@router.message(EditLessonPost.waiting_link_url)
async def lesson_post_edit_link_step2(message: Message, state: FSMContext):
    url_pattern = r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)"

    if not message.text or not re.match(url_pattern, message.text.strip()):
        await message.answer("❌ Введите корректный URL.\nПример: https://example.com")
        return

    await state.update_data(new_url=message.text.strip())
    await state.set_state(EditLessonPost.waiting_button_text)

    await message.answer(
        "🔘 <b>Шаг 3 из 3</b>\n\nВведите новый текст кнопки:",
        parse_mode="HTML",
    )


@router.message(EditLessonPost.waiting_button_text)
async def lesson_post_edit_link_step3(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post_id = data.get("post_id")

    button_text = (message.text or "").strip()
    if not button_text:
        await message.answer("❌ Текст кнопки не может быть пустым")
        return

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post or post.post_type != "link":
        await message.answer("❌ Пост не найден")
        await state.clear()
        return

    post.content = data.get("new_content")
    post.buttons = {"inline": [[{"text": button_text, "url": data.get("new_url")}]]}

    await session.commit()

    await message.answer(
        "✅ Ссылка изменена!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К посту", callback_data=f"lpost:view:{post_id}")]]
        ),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data.startswith("lpost:edit_survey:"))
async def lesson_post_edit_survey(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post or post.post_type != "survey":
        await callback.answer("❌ Пост не найден или не анкета")
        return

    result = await session.execute(
        select(Survey).where(Survey.is_active == True).order_by(Survey.created_at.desc())
    )
    surveys = result.scalars().all()
    if not surveys:
        await callback.answer("❌ Нет активных анкет", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for s in surveys:
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {s.name}",
                callback_data=f"lpost:set_survey:{post_id}:{s.survey_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lpost:edit:{post_id}"))

    await callback.message.edit_text(
        "📋 <b>Выберите новую анкету для поста:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lpost:set_survey:"))
async def lesson_post_set_survey(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    _, _, post_id_s, survey_id_s = callback.data.split(":")
    post_id = int(post_id_s)
    survey_id = int(survey_id_s)

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post or post.post_type != "survey":
        await callback.answer("❌ Пост не найден")
        return

    post.survey_id = survey_id
    await session.commit()

    await callback.answer("✅ Анкета изменена")
    await callback.message.edit_text(
        "✅ Анкета изменена.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К посту", callback_data=f"lpost:view:{post_id}")]]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("lpost:delete:"))
async def lesson_post_delete(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    post_id = int(callback.data.split(":")[2])

    res = await session.execute(select(LessonPost).where(LessonPost.post_id == post_id))
    post = res.scalar_one_or_none()
    if not post:
        await callback.answer("❌ Пост не найден")
        return

    lesson_id = post.lesson_id

    await session.execute(delete(LessonPost).where(LessonPost.post_id == post_id))
    await session.commit()

    await callback.answer("✅ Пост удалён", show_alert=True)
    await callback.message.edit_text(
        "✅ Пост удалён.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К уроку", callback_data=f"lesson:open:{lesson_id}")]]
        ),
        parse_mode="HTML",
    )


# ===================== USER: LESSON OPEN =====================

async def send_lesson_by_id(message: Message, lesson_id: int, session: AsyncSession):
    """User ko'radigan urokni yuborish (deep-link yoki oddiy SMS orqali)."""
    await send_lesson_to_chat(message, lesson_id, session, with_delays=False)
