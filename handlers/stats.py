# handlers/stats.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timedelta

from database.base import User
from utils.texts import Texts
from utils.helpers import is_admin
from keyboards.admin_kb import get_admin_main_keyboard

router = Router(name="stats_router")

@router.callback_query(F.data == "admin:stats")
async def show_statistics(callback: CallbackQuery, session: AsyncSession):
    """Statistikani ko'rsatish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    # Jami userlar
    total_result = await session.execute(
        select(func.count(User.user_id))
    )
    total_users = total_result.scalar()
    
    # Aktiv userlar
    active_result = await session.execute(
        select(func.count(User.user_id)).where(
            User.is_active == True,
            User.is_blocked == False
        )
    )
    active_users = active_result.scalar()
    
    # Bloklagan userlar
    blocked_result = await session.execute(
        select(func.count(User.user_id)).where(User.is_blocked == True)
    )
    blocked_users = blocked_result.scalar()
    
    # Bugungi yangi userlar
    today_result = await session.execute(
        select(func.count(User.user_id)).where(
            func.date(User.start_date) == func.current_date()
        )
    )
    today_new = today_result.scalar()
    
    # Haftalik yangi userlar (PostgreSQL uchun to'g'ri sintaksis)
    week_result = await session.execute(
        select(func.count(User.user_id)).where(
            User.start_date >= text("CURRENT_DATE - INTERVAL '7 days'")
        )
    )
    week_new = week_result.scalar()
    
    # Oylik yangi userlar (PostgreSQL uchun to'g'ri sintaksis)
    month_result = await session.execute(
        select(func.count(User.user_id)).where(
            User.start_date >= text("CURRENT_DATE - INTERVAL '30 days'")
        )
    )
    month_new = month_result.scalar()
    
    # Foizlarni hisoblash
    active_percent = round((active_users / total_users * 100), 1) if total_users > 0 else 0
    blocked_percent = round((blocked_users / total_users * 100), 1) if total_users > 0 else 0
    
    # Voronka statistikasi
    funnel_result = await session.execute(
        select(
            User.current_day,
            func.count(User.user_id).label('count')
        ).where(
            User.is_subscribed == True,
            User.is_blocked == False
        ).group_by(User.current_day).order_by(User.current_day)
    )
    funnel_data_raw = funnel_result.all()
    
    funnel_text = ""
    if funnel_data_raw:
        prev_count = None
        for row in funnel_data_raw:
            day = row[0]
            count = row[1]
            
            if prev_count is not None:
                diff = count - prev_count
                percent = round((count / funnel_data_raw[0][1] * 100), 1)
                funnel_text += f"День {day}: {count} чел. ({percent}%) ▼ {abs(diff)}\n"
            else:
                funnel_text += f"День {day}: {count} чел. (100%)\n"
            
            prev_count = count
    else:
        funnel_text = "<i>Нет данных</i>"
    
    stats_message = Texts.STATS_MESSAGE.format(
        total_users=total_users,
        active_users=active_users,
        active_percent=active_percent,
        blocked_users=blocked_users,
        blocked_percent=blocked_percent,
        today_new=today_new,
        week_new=week_new,
        month_new=month_new,
        funnel_data=funnel_text
    )
    
    await callback.message.edit_text(
        stats_message,
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()