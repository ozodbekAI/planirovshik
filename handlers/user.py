# handlers/user.py - UPDATED VERSION
import asyncio
import re
from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.base import User, Lesson, Survey
from handlers.survey import send_survey_intro
from handlers.lessons import send_lesson_by_id
from keyboards.user_kb import get_subscribe_keyboard
from services.tgtrack import TgTrackService
from utils.texts import Texts
from database.crud import get_setting
from utils.helpers import check_subscription
from scheduler.tasks import SchedulerTasks

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    """
    /start komandasi - deep link bilan anketalarni qo'llab-quvvatlaydi
    /start survey_123 - survey ID 123 ni ochadi
    """
    await TgTrackService.send_start_to_tgtrack(message)

    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Друг"

    # Deep link parametrini tekshirish
    command_args = message.text.split(maxsplit=1)

    if len(command_args) > 1:
        arg = command_args[1].strip()

        # Survey deep link
        if arg.startswith("survey_"):
            try:
                survey_id = int(arg.replace("survey_", ""))
                await send_survey_intro(message, survey_id, state, session)
                return
            except ValueError:
                await message.answer("❌ Неверная ссылка на анкету")
                return

        # Lesson/Urok deep link
        if arg.startswith("urok_"):
            try:
                lesson_id = int(arg.replace("urok_", ""))
                await send_lesson_by_id(message, lesson_id, session)
                return
            except ValueError:
                await message.answer("❌ Неверная ссылка на урок")
                return

    # Oddiy /start flow
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            user_id=user_id,
            username=username,
            first_name=first_name,
            current_day=0,
            first_message_sent=False,
            subscription_checked=False,
            is_subscribed=False,
            is_active=True,
            is_blocked=False,
        )
        session.add(user)
    else:
        user.is_active = True
        user.current_day = 0
        user.first_message_sent = False

    await session.commit()

    welcome_text = await get_setting("welcome_text", Texts.WELCOME)
    try:
        welcome_text = welcome_text.format(name=first_name)
    except Exception:
        pass

    await message.answer(welcome_text, parse_mode="HTML")

    await asyncio.sleep(2)

    if not user.is_subscribed:
        subscribe_text = await get_setting("subscribe_request", Texts.SUBSCRIBE_REQUEST)
        await message.answer(
            subscribe_text,
            reply_markup=get_subscribe_keyboard(),
            parse_mode="HTML",
        )
    else:
        scheduler = SchedulerTasks(message.bot)
        asyncio.create_task(scheduler.send_launch_sequence(message.bot, session, user))


@router.message(
    # IMPORTANT: do not intercept messages while user/admin is in any FSM flow
    # (e.g. lesson creation, adding posts, surveys, etc.).
    StateFilter(None),
    F.text.startswith("urok") | F.text.startswith("Urok") |
    F.text.startswith("Урок") | F.text.startswith("урок") |
    F.text.startswith("rok") | F.text.startswith("Rok")
)
async def open_lesson_by_text(message: Message, session: AsyncSession):
    """Urokni oddiy SMS orqali ochish.

    Misollar:
    - urok_2
    - urok 2
    - Урок 2
    - rok 2

    Telegram deep-link (/start urok_2) mavjudligicha qoladi, lekin bu handler
    foydalanuvchi qo'lda yozganda ham ushlab oladi.
    """
    if not message.text:
        return

    raw = (message.text or "").strip()
    if not raw:
        return

    # 1) Avval — urok nomi bo'yicha (case-insensitive) izlaymiz.
    #    Bu holat "Урок 3" yuborilganda ID=3 bo'lmasa ham ishlaydi.
    normalized = re.sub(r"\s+", " ", raw).strip()
    normalized2 = normalized.replace("_", " ").strip()

    candidates = {normalized, normalized2}
    low = normalized2.lower()

    # translit/variantlar: urok/rok/урок
    if low.startswith("urok"):
        candidates.add(re.sub(r"(?i)^urok", "урок", normalized2))
    if low.startswith("rok"):
        candidates.add(re.sub(r"(?i)^rok", "урок", normalized2))
    if low.startswith("урок"):
        candidates.add(re.sub(r"(?i)^урок", "urok", normalized2))
        candidates.add(re.sub(r"(?i)^урок", "rok", normalized2))

    candidates = {re.sub(r"\s+", " ", c).strip() for c in candidates if c and c.strip()}
    lower_candidates = {c.lower() for c in candidates}

    res = await session.execute(
        select(Lesson)
        .where(Lesson.is_active.is_(True))
        .where(func.lower(Lesson.name).in_(lower_candidates))
        .order_by(Lesson.created_at.desc())
    )
    lesson = res.scalars().first()
    if lesson:
        await send_lesson_by_id(message, lesson.lesson_id, session)
        return

    # 2) Fallback: raqam bo'lsa ID deb ko'ramiz.
    m = re.search(r"(\d+)", normalized2)
    if m:
        try:
            lesson_id = int(m.group(1))
            # Tekshirib olamiz (shunda xatolik matni aniqroq bo'ladi)
            res2 = await session.execute(
                select(Lesson).where(Lesson.lesson_id == lesson_id)
            )
            lesson2 = res2.scalar_one_or_none()
            if lesson2 and lesson2.is_active:
                await send_lesson_by_id(message, lesson2.lesson_id, session)
                return
        except Exception:
            pass

    # 3) Topilmasa — userga mavjud uroklar ro'yxatini ko'rsatamiz.
    res3 = await session.execute(
        select(Lesson)
        .where(Lesson.is_active.is_(True))
        .order_by(Lesson.created_at.desc())
        .limit(10)
    )
    lessons = res3.scalars().all()
    if lessons:
        lst = "\n".join([f"• {l.name}" for l in lessons])
        await message.answer(
            "❌ Урок недоступен или не найден.\n\n"
            "Доступные уроки:\n"
            f"{lst}\n\n"
            "Напишите точное название урока (например: <code>Урок 3</code>).",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "❌ Уроков пока нет.",
            parse_mode="HTML",
        )


@router.message(
    # IMPORTANT: do not intercept messages while user/admin is in any FSM flow.
    StateFilter(None),
    F.text.startswith("Анкета") | F.text.startswith("анкета") |
    F.text.startswith("Anketa") | F.text.startswith("anketa") |
    F.text.startswith("survey") | F.text.startswith("Survey") |
    F.text.startswith("Опрос") | F.text.startswith("опрос")
)
async def open_survey_by_text(message: Message, session: AsyncSession, state: FSMContext):
    """Open survey (anketa) by a normal text message.

    This is used by lesson survey posts via a prefilled-message link:
    https://t.me/<bot>?text=<survey name>

    Examples:
    - Анкета 3
    - anketa 3
    - survey_5
    - Опрос 2
    """
    raw = (message.text or "").strip()
    if not raw:
        return

    normalized = re.sub(r"\s+", " ", raw).strip()
    normalized2 = normalized.replace("_", " ").strip()

    # 1) Exact name match (case-insensitive)
    res = await session.execute(
        select(Survey)
        .where(Survey.is_active.is_(True))
        .where(func.lower(Survey.name) == normalized2.lower())
        .order_by(Survey.created_at.desc())
    )
    survey = res.scalar_one_or_none()
    if survey:
        await send_survey_intro(message, survey.survey_id, state, session)
        return

    # 2) Fallback: parse number and try by id
    m = re.search(r"(\d+)", normalized2)
    if m:
        try:
            survey_id = int(m.group(1))
            res2 = await session.execute(
                select(Survey).where(Survey.survey_id == survey_id, Survey.is_active.is_(True))
            )
            survey2 = res2.scalar_one_or_none()
            if survey2:
                await send_survey_intro(message, survey2.survey_id, state, session)
                return
        except Exception:
            pass

    # 3) Not found -> show a short list
    res3 = await session.execute(
        select(Survey)
        .where(Survey.is_active.is_(True))
        .order_by(Survey.created_at.desc())
        .limit(10)
    )
    surveys = res3.scalars().all()
    if surveys:
        lst = "\n".join([f"• {s.name}" for s in surveys])
        await message.answer(
            "❌ Анкета недоступна или не найдена.\n\n"
            "Доступные анкеты:\n"
            f"{lst}\n\n"
            "Напишите точное название анкеты (например: <code>Анкета 1</code>).",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Активных анкет пока нет.", parse_mode="HTML")


@router.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id

    is_subscribed = await check_subscription(callback.bot, user_id)

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("❌", show_alert=True)
        return

    if is_subscribed:
        user.is_subscribed = True
        await session.commit()

        confirmed_text = await get_setting(
            "subscription_confirmed",
            Texts.SUBSCRIPTION_CONFIRMED,
        )

        await TgTrackService.send_goal(
            user_id=user_id,
            target="subscribe_confirmed"
        )

        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        await callback.message.answer(confirmed_text, parse_mode="HTML")

        scheduler = SchedulerTasks(callback.bot)
        await scheduler.send_launch_sequence(callback.bot, session, user)

        await callback.answer("✅ Подписка подтверждена!")

    else:
        subscribe_text = await get_setting("subscribe_request", Texts.SUBSCRIBE_REQUEST)

        await callback.answer("❌ Вы еще не подписаны на канал!", show_alert=True)
        await callback.message.answer(
            subscribe_text,
            reply_markup=get_subscribe_keyboard(),
            parse_mode="HTML",
        )