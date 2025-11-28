
from sqlalchemy import select, func, delete, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Optional, List

from database.base import User, ScheduleDay, SchedulePost, UserProgress, Setting
from database.session import async_session_maker  # BU YERDA O'ZGARDI


async def get_setting(key: str, default: str = None) -> str:
    """Sozlamani olish"""
    async with async_session_maker() as session:  # async_session_maker ishlatiladi
        result = await session.execute(
            select(Setting).where(Setting.setting_key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            return setting.setting_value
        return default


async def update_setting(key: str, value: str):
    """Sozlamani yangilash yoki yaratish"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Setting).where(Setting.setting_key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.setting_value = value
        else:
            new_setting = Setting(setting_key=key, setting_value=value)
            session.add(new_setting)
        
        await session.commit()


# Agar boshqa CRUD funksiyalar ham bo'lsa, ularni ham shunday qiling
# Misol:

async def get_user(user_id: int) -> Optional[User]:
    """Foydalanuvchini olish"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def create_user(user_id: int, username: str = None, first_name: str = None) -> User:
    """Yangi foydalanuvchi yaratish"""
    async with async_session_maker() as session:
        new_user = User(
            user_id=user_id,
            username=username,
            first_name=first_name,
            is_subscribed=False,
            current_day=1
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        return new_user


async def update_user_subscription(user_id: int, is_subscribed: bool):
    """Foydalanuvchi obunasini yangilash"""
    async with async_session_maker() as session:
        await session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(is_subscribed=is_subscribed)
        )
        await session.commit()


async def get_all_users() -> List[User]:
    """Barcha foydalanuvchilarni olish"""
    async with async_session_maker() as session:
        result = await session.execute(select(User))
        return result.scalars().all()


async def get_active_users() -> List[User]:
    """Aktiv foydalanuvchilarni olish"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.is_active == True, User.is_blocked == False)
        )
        return result.scalars().all()


async def get_schedule_day(day_number: int) -> Optional[ScheduleDay]:
    """Kunni olish"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ScheduleDay).where(ScheduleDay.day_number == day_number)
        )
        return result.scalar_one_or_none()


async def get_day_posts(day_number: int) -> List[SchedulePost]:
    """Kun postlarini olish"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(SchedulePost)
            .where(SchedulePost.day_number == day_number)
            .order_by(SchedulePost.time, SchedulePost.order_number)
        )
        return result.scalars().all()