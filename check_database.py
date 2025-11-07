# check_database.py
import asyncio
from sqlalchemy import select, func
from database import async_session_maker
from database.base import User, SchedulePost, ScheduleDay, UserProgress
from datetime import datetime

async def check_db():
    async with async_session_maker() as session:
        print("=" * 60)
        print("1. USERS")
        print("=" * 60)
        users = await session.execute(select(User))
        for user in users.scalars().all():
            print(f"ID: {user.user_id}, Day: {user.current_day}, "
                  f"Active: {user.is_active}, Blocked: {user.is_blocked}, "
                  f"Subscribed: {user.is_subscribed}")
        
        print("\n" + "=" * 60)
        print("2. SCHEDULE POSTS")
        print("=" * 60)
        posts = await session.execute(
            select(SchedulePost).order_by(
                SchedulePost.day_number, 
                SchedulePost.time, 
                SchedulePost.order_number
            )
        )
        for post in posts.scalars().all():
            content = (post.content or post.caption or "")[:40]
            print(f"ID: {post.post_id}, Day: {post.day_number}, "
                  f"Time: {post.time}, Type: {post.post_type}, "
                  f"Content: {content}")
        
        print("\n" + "=" * 60)
        print("3. USER PROGRESS (Today)")
        print("=" * 60)
        today = datetime.now().date()
        progress = await session.execute(
            select(UserProgress).where(
                func.date(UserProgress.sent_date) == today
            )
        )
        for prog in progress.scalars().all():
            print(f"User: {prog.user_id}, Post: {prog.post_id}, "
                  f"Status: {prog.status}, Date: {prog.sent_date}")
        
        print("\n" + "=" * 60)
        print("4. SCHEDULE DAYS")
        print("=" * 60)
        days = await session.execute(
            select(ScheduleDay).order_by(ScheduleDay.day_number)
        )
        for day in days.scalars().all():
            print(f"Day: {day.day_number}")

if __name__ == "__main__":
    asyncio.run(check_db())