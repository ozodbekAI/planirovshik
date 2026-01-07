# handlers/broadcast.py
import asyncio
import time

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import config
from database.base import User, Survey
from keyboards.admin_kb import (
    get_broadcast_type_keyboard,
    get_broadcast_target_keyboard,
    get_admin_main_keyboard,
)
from utils.texts import Texts
from utils.helpers import is_admin, format_time_delta

router = Router(name="broadcast_router")


# ================= FSM =================

class Broadcast(StatesGroup):
    waiting_content = State()
    waiting_target = State()
    waiting_day = State()
    confirming = State()


# ================= START =================

@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    await callback.message.edit_text(
        Texts.BROADCAST_START,
        reply_markup=get_broadcast_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ================= TYPE SELECT =================

@router.callback_query(F.data.startswith("broadcast:type:"))
async def broadcast_type_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    broadcast_type = callback.data.split(":")[2]
    await state.update_data(broadcast_type=broadcast_type)

    # ===== SURVEY FLOW =====
    if broadcast_type == "survey":
        result = await session.execute(
            select(Survey)
            .where(Survey.is_active == True)
            .order_by(Survey.created_at.desc())
        )
        surveys = result.scalars().all()

        if not surveys:
            await callback.answer(
                "❌ Нет активных анкет. Сначала создайте анкету.",
                show_alert=True,
            )
            return

        kb = InlineKeyboardBuilder()
        for s in surveys:
            kb.row(
                InlineKeyboardButton(
                    text=f"📋 {s.name}",
                    callback_data=f"broadcast:survey_select:{s.survey_id}",
                )
            )
        kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:broadcast"))

        await callback.message.edit_text(
            "📋 <b>Выберите анкету для рассылки:</b>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # ===== DEFAULT CONTENT FLOW =====
    await state.set_state(Broadcast.waiting_content)

    instructions = {
        "text": "📝 Отправьте текст для рассылки (HTML поддерживается).",
        "photo": "🖼 Отправьте изображение (можно с подписью).",
        "video": "🎥 Отправьте видео (можно с подписью).",
        "document": "📄 Отправьте документ (можно с подписью).",
    }

    await callback.message.edit_text(
        instructions.get(broadcast_type, "Отправьте контент:"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ================= SURVEY SELECT =================

@router.callback_query(F.data.startswith("broadcast:survey_select:"))
async def broadcast_survey_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    survey_id = int(callback.data.split(":")[2])

    survey = (
        await session.execute(
            select(Survey).where(
                Survey.survey_id == survey_id,
                Survey.is_active == True,
            )
        )
    ).scalar_one_or_none()

    if not survey:
        await callback.answer("❌ Анкета не найдена", show_alert=True)
        return

    await state.update_data(
        survey_id=survey_id,
        broadcast_type="survey",
    )

    total_users = (
        await session.execute(select(func.count(User.user_id)))
    ).scalar()
    active_users = (
        await session.execute(
            select(func.count(User.user_id)).where(
                User.is_active == True,
                User.is_blocked == False,
            )
        )
    ).scalar()

    deep_link = f"https://t.me/{config.BOT_USERNAME}?start=survey_{survey_id}"

    preview_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=survey.button_text or "📝 Заполнить анкету",
                    url=deep_link,
                )
            ]
        ]
    )

    await callback.message.answer(
        "👁 <b>ПРЕДПРОСМОТР РАССЫЛКИ (АНКЕТА)</b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        survey.message_text or "Пожалуйста, заполните анкету:",
        reply_markup=preview_kb,
        parse_mode="HTML",
    )

    await state.set_state(Broadcast.waiting_target)
    await callback.message.answer(
        Texts.BROADCAST_PREVIEW,
        reply_markup=get_broadcast_target_keyboard(total_users, active_users),
        parse_mode="HTML",
    )
    await callback.answer()


# ================= CONTENT =================

@router.message(Broadcast.waiting_content)
async def broadcast_content_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    data = await state.get_data()
    btype = data["broadcast_type"]

    content = None
    file_id = None
    caption = None

    if btype == "text":
        content = message.text
    elif btype == "photo" and message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption
    elif btype == "video" and message.video:
        file_id = message.video.file_id
        caption = message.caption
    elif btype == "document" and message.document:
        file_id = message.document.file_id
        caption = message.caption
    else:
        await message.answer("❌ Неверный тип контента")
        return

    await state.update_data(content=content, file_id=file_id, caption=caption)

    total_users = (
        await session.execute(select(func.count(User.user_id)))
    ).scalar()
    active_users = (
        await session.execute(
            select(func.count(User.user_id)).where(
                User.is_active == True,
                User.is_blocked == False,
            )
        )
    ).scalar()

    await state.set_state(Broadcast.waiting_target)

    await message.answer("👁 <b>ПРЕДПРОСМОТР</b>", parse_mode="HTML")
    if btype == "text":
        await message.answer(content, parse_mode="HTML")
    elif btype == "photo":
        await message.answer_photo(file_id, caption=caption, parse_mode="HTML")
    elif btype == "video":
        await message.answer_video(file_id, caption=caption, parse_mode="HTML")
    elif btype == "document":
        await message.answer_document(file_id, caption=caption, parse_mode="HTML")

    await message.answer(
        Texts.BROADCAST_PREVIEW,
        reply_markup=get_broadcast_target_keyboard(total_users, active_users),
        parse_mode="HTML",
    )


# ================= TARGET =================

@router.callback_query(F.data.startswith("broadcast:target:"))
async def broadcast_target_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    target = callback.data.split(":")[2]
    await state.update_data(target=target)

    if target == "day":
        await state.set_state(Broadcast.waiting_day)
        await callback.message.edit_text(
            "Введите номер дня (или несколько через запятую):\n<code>1,2,3</code>",
            parse_mode="HTML",
        )
        return

    await broadcast_confirm(callback, state, session)


# ================= CONFIRM =================

async def broadcast_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    data = await state.get_data()
    target = data["target"]

    if target == "all":
        count = (await session.execute(select(func.count(User.user_id)))).scalar()
    elif target == "active":
        count = (
            await session.execute(
                select(func.count(User.user_id)).where(
                    User.is_active == True,
                    User.is_blocked == False,
                )
            )
        ).scalar()
    else:
        count = 0

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ НАЧАТЬ", callback_data="broadcast:confirm")],
            [InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="admin:main")],
        ]
    )

    await callback.message.edit_text(
        Texts.BROADCAST_CONFIRM.format(
            count=count,
            type=data["broadcast_type"],
        ),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ================= EXECUTE =================

@router.callback_query(F.data == "broadcast:confirm")
async def broadcast_execute(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    data = await state.get_data()
    btype = data["broadcast_type"]
    target = data["target"]

    if target == "all":
        users = (await session.execute(select(User.user_id))).all()
    else:
        users = (
            await session.execute(
                select(User.user_id).where(
                    User.is_active == True,
                    User.is_blocked == False,
                )
            )
        ).all()

    user_ids = [u[0] for u in users]
    total = len(user_ids)

    if total == 0:
        await callback.answer("❌ Нет пользователей", show_alert=True)
        return

    # ===== PREPARE SURVEY (ONCE) =====
    survey_text = None
    survey_kb = None
    if btype == "survey":
        survey = (
            await session.execute(
                select(Survey).where(Survey.survey_id == data["survey_id"])
            )
        ).scalar_one()
        link = f"https://t.me/{config.BOT_USERNAME}?start=survey_{survey.survey_id}"
        survey_text = survey.message_text or "Пожалуйста, заполните анкету:"
        survey_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=survey.button_text or "📝 Заполнить",
                        url=link,
                    )
                ]
            ]
        )

    progress = await callback.message.edit_text(
        Texts.BROADCAST_PROGRESS.format(
            percent=0,
            sent=0,
            total=total,
            remaining=total,
            failed=0,
        ),
        parse_mode="HTML",
    )

    sent = failed = blocked = 0
    start = time.time()

    for i, uid in enumerate(user_ids, 1):
        try:
            if btype == "survey":
                await callback.bot.send_message(
                    uid,
                    survey_text,
                    reply_markup=survey_kb,
                    parse_mode="HTML",
                )
            else:
                await callback.bot.send_message(uid, data["content"], parse_mode="HTML")
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            failed += 1
        except Exception:
            failed += 1

        if i % 10 == 0 or i == total:
            await progress.edit_text(
                Texts.BROADCAST_PROGRESS.format(
                    percent=int(i / total * 100),
                    sent=sent,
                    total=total,
                    remaining=total - i,
                    failed=failed,
                ),
                parse_mode="HTML",
            )

        if i % 30 == 0:
            await asyncio.sleep(1)

    await progress.edit_text(
        Texts.BROADCAST_COMPLETE.format(
            sent=sent,
            sent_percent=round(sent / total * 100, 1),
            failed=failed,
            failed_percent=round(failed / total * 100, 1),
            blocked=blocked,
            errors=failed,
            duration=format_time_delta(int(time.time() - start)),
        ),
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML",
    )

    await state.clear()
    await callback.answer("✅ Рассылка завершена")
