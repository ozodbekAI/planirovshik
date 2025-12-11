# handlers/user.py
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.base import User
from keyboards.user_kb import get_subscribe_keyboard
from utils.texts import Texts
from database.crud import get_setting
from utils.helpers import check_subscription
from scheduler.tasks import SchedulerTasks

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Друг"

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
        print(f"✨ New user created: {user_id}")
    else:
        # /start bosilganda funnelni noldan boshlaymiz
        user.is_active = True
        user.current_day = 0
        user.first_message_sent = False
        user.subscription_checked = False
        user.is_subscribed = False
        print(f"🔄 User reset: {user_id}")

    await session.commit()

    # 1) Welcome matni
    welcome_text = await get_setting("welcome_text", Texts.WELCOME)
    try:
        welcome_text = welcome_text.format(name=first_name)
    except Exception:
        pass

    await message.answer(welcome_text, parse_mode="HTML")

    # 2) Подписка so‘rovi
    subscribe_text = await get_setting("subscribe_request", Texts.SUBSCRIBE_REQUEST)
    await message.answer(
        subscribe_text,
        reply_markup=get_subscribe_keyboard(),
        parse_mode="HTML",
    )
    # Day 0 postlari faqat obuna tasdiqlangandan keyin yuboriladi


@router.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: CallbackQuery, session: AsyncSession):
    """
    Обновленная логика проверки подписки:
    - obunani tekshiradi,
    - OK bo‘lsa: eski xabarni o‘chiradi, tasdiqlash matni + Day 0,
    - aks holda: yana запрос подписки.
    """
    user_id = callback.from_user.id

    is_subscribed = await check_subscription(callback.bot, user_id)

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("❌ Xatolik yuz berdi. /start ni qaytadan bosing.", show_alert=True)
        return

    if is_subscribed:
        user.is_subscribed = True
        user.subscription_checked = True
        await session.commit()

        confirmed_text = await get_setting(
            "subscription_confirmed",
            Texts.SUBSCRIPTION_CONFIRMED,
        )

        # Eski "Подпишитесь" xabarini o‘chiramiz, shunda u tepada qolmaydi
        try:
            await callback.message.delete()
        except Exception:
            # Agar delete bo‘lmasa – kamida keyboardni olib tashlaymiz
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        await callback.message.answer(confirmed_text, parse_mode="HTML")

        # Day 0 launch sequence – endi bu yerda ishga tushadi
        scheduler = SchedulerTasks(callback.bot)
        await scheduler.send_launch_sequence(callback.bot, session, user)

        await callback.answer("✅ Подписка подтверждена!")
        print(f"✅ User {user_id} subscription confirmed")

    else:
        subscribe_text = await get_setting("subscribe_request", Texts.SUBSCRIBE_REQUEST)

        await callback.answer("❌ Вы еще не подписаны на канал!", show_alert=True)
        await callback.message.answer(
            subscribe_text,
            reply_markup=get_subscribe_keyboard(),
            parse_mode="HTML",
        )
