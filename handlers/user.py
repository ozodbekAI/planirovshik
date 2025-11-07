# handlers/user.py
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.base import User
from keyboards.user_kb import get_subscribe_keyboard
from utils.texts import Texts
from database.crud import get_setting
from utils.helpers import check_subscription

router = Router(name="user_router")

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    """Start buyrug'i"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    result = await session.execute(
        select(User).where(User.user_id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        new_user = User(
            user_id=user_id,
            username=username,
            first_name=first_name,
            is_subscribed=False,
            current_day=1
        )
        session.add(new_user)
        await session.commit()
    else:
        user.is_active = True
        await session.commit()
    
    is_subscribed = await check_subscription(message.bot, user_id)
    
    if is_subscribed:
        if user:
            user.is_subscribed = True
            await session.commit()
        
        # Dinamik textni olish
        confirmed_text = await get_setting('subscription_confirmed', Texts.SUBSCRIPTION_CONFIRMED)
        
        await message.answer(
            confirmed_text,
            parse_mode="HTML"
        )
    else:
        # Dinamik textlarni olish
        welcome_text = await get_setting('welcome_text', Texts.WELCOME)
        subscribe_text = await get_setting('subscribe_request', Texts.SUBSCRIBE_REQUEST)
        
        await message.answer(
            welcome_text.format(name=first_name),
            parse_mode="HTML"
        )
        await message.answer(
            subscribe_text,
            reply_markup=get_subscribe_keyboard(),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: CallbackQuery, session: AsyncSession):
    """Obunani tekshirish callback"""
    user_id = callback.from_user.id
    
    is_subscribed = await check_subscription(callback.bot, user_id)
    
    if is_subscribed:
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.is_subscribed = True
            await session.commit()
        
        # Dinamik textni olish
        confirmed_text = await get_setting('subscription_confirmed', Texts.SUBSCRIPTION_CONFIRMED)
        
        await callback.message.edit_text(
            confirmed_text,
            parse_mode="HTML"
        )
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
    else:
        await callback.answer(
            "❌ Вы еще не подписаны на канал. Подпишитесь и попробуйте снова.",
            show_alert=True
        )