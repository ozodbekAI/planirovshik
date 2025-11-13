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

from database.crud import get_setting
from utils.texts import Texts

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Друг"

    # Userni bazadan qidirish
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
            is_blocked=False
        )
        session.add(user)
        print(f"✨ New user created: {user_id}")
    else:
        user.is_active = True
        user.current_day = 0
        user.first_message_sent = False
        user.subscription_checked = False
        user.is_subscribed = False
        print(f"🔄 User reset: {user_id}")

    await session.commit()

    # 🔹 1. Welcome matnini olish (DB bo'lmasa – default Texts.WELCOME)
    welcome_text = await get_setting("welcome_text", Texts.WELCOME)
    welcome_text = welcome_text.format(name=first_name)

    await message.answer(welcome_text, parse_mode="HTML")

    # 🔹 2. Launch sequence boshlash (Day 0 postlar)
    scheduler = SchedulerTasks(message.bot)
    await scheduler.send_launch_sequence(message.bot, session, user)



@router.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: CallbackQuery, session: AsyncSession):
    """
    Obuna tekshirish callback - user obuna bo'lganini tasdiqlaydi
    """
    user_id = callback.from_user.id
    
    # Kanalga obuna bo'lganligini tekshirish
    is_subscribed = await check_subscription(callback.bot, user_id)

    # Userni bazadan olish
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("❌ Xatolik yuz berdi. /start ni qaytadan bosing.", show_alert=True)
        return

    if is_subscribed:
        # Obunani tasdiqlash
        user.is_subscribed = True
        await session.commit()

        # Tasdiqlash xabarini ko'rsatish
        confirmed_text = await get_setting('subscription_confirmed', Texts.SUBSCRIPTION_CONFIRMED)
        await callback.message.edit_text(confirmed_text, parse_mode="HTML")

        # Qolgan postlarni yuborish
        scheduler = SchedulerTasks(callback.bot)
        await scheduler.send_remaining_launch_posts(callback.bot, session, user)
        
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
        print(f"✅ User {user_id} subscription confirmed")
    else:
        await callback.answer("❌ Вы еще не подписаны на канал!", show_alert=True)