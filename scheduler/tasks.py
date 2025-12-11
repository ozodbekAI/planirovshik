# scheduler/tasks.py
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import User, SchedulePost, UserProgress, ScheduleDay
from utils.helpers import format_moscow_time


class SchedulerTasks:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def _send_post(self, bot: Bot, user_id: int, post: SchedulePost) -> bool:
        """Bitta postni yuborish"""
        try:
            media_types = ["photo", "video", "video_note", "audio", "document", "voice"]

            if post.post_type in media_types and not post.file_id:
                print(f"⚠️ Warning: Post {post.post_id} (type: {post.post_type}) has no file_id - skipping")
                return False

            if post.post_type == "text":
                if not post.content:
                    print(f"⚠️ Warning: Post {post.post_id} (type: text) has no content - skipping")
                    return False
                await bot.send_message(user_id, post.content, parse_mode="HTML")

            elif post.post_type == "photo":
                await bot.send_photo(
                    user_id,
                    post.file_id,
                    caption=post.caption or "",
                    parse_mode="HTML",
                )

            elif post.post_type == "video":
                await bot.send_video(
                    user_id,
                    post.file_id,
                    caption=post.caption or "",
                    parse_mode="HTML",
                )

            elif post.post_type == "video_note":
                await bot.send_video_note(user_id, post.file_id)

            elif post.post_type == "audio":
                await bot.send_audio(
                    user_id,
                    post.file_id,
                    caption=post.caption or "",
                    parse_mode="HTML",
                )

            elif post.post_type == "document":
                await bot.send_document(
                    user_id,
                    post.file_id,
                    caption=post.caption or "",
                    parse_mode="HTML",
                )

            elif post.post_type == "voice":
                await bot.send_voice(
                    user_id,
                    post.file_id,
                    caption=post.caption or "",
                    parse_mode="HTML",
                )

            elif post.post_type in ("link", "subscription_check"):
                if not post.content:
                    print(f"⚠️ Warning: Post {post.post_id} (type: {post.post_type}) has no content - skipping")
                    return False

                if post.buttons and "inline" in post.buttons:
                    # buttons["inline"] = [[{"text": "...", "url": "..."}], [...]]
                    inline_rows = []
                    for row in post.buttons["inline"]:
                        inline_row = [
                            InlineKeyboardButton(text=btn["text"], url=btn["url"]) for btn in row
                        ]
                        inline_rows.append(inline_row)

                    kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)
                    await bot.send_message(user_id, post.content, reply_markup=kb, parse_mode="HTML")
                else:
                    await bot.send_message(user_id, post.content, parse_mode="HTML")

            else:
                print(f"⚠️ Unknown post type: {post.post_type} for post {post.post_id}")
                return False

            return True

        except Exception as e:
            print(f"❌ Failed to send post {post.post_id} to {user_id}: {e}")
            return False

    async def send_launch_sequence(self, bot: Bot, session: AsyncSession, user: User):
        """
        Day 0 postlarni ketma-ket yuborish.
        /start + подписка tasdiqlangandan keyin chaqiriladi.
        delay_seconds – HAR BIR post uchun, uni yuborishdan OLDIN kutish vaqti.
        """
        if user.first_message_sent:
            # Allaqachon ishga tushgan bo‘lsa – takrorlamaymiz
            return

        posts_result = await session.execute(
            select(SchedulePost)
            .where(SchedulePost.day_number == 0)
            .order_by(SchedulePost.order_number)
        )
        posts = posts_result.scalars().all()

        if not posts:
            print("⚠️ No posts found for day 0")
            return

        user.first_message_sent = True
        await session.commit()

        print(f"📤 Starting launch sequence for user {user.user_id}")

        for post in posts:
            # HAR BIR post uchun o‘z delay'ini hurmat qilamiz
            delay = post.delay_seconds or 0
            if delay > 0:
                print(f"⏳ Waiting {delay} seconds before sending post {post.post_id}")
                await asyncio.sleep(delay)

            success = await self._send_post(bot, user.user_id, post)

            if success:
                session.add(
                    UserProgress(
                        user_id=user.user_id,
                        post_id=post.post_id,
                        status="sent",
                    )
                )
                print(f"✅ Post {post.post_id} sent to user {user.user_id}")

            # subscription_check'ga yetganimizda – shu yerda to‘xtaymiz
            if post.post_type == "subscription_check":
                user.subscription_checked = True
                await session.commit()
                print(f"🛑 Stopped at subscription check for user {user.user_id}")
                break

        await session.commit()

    async def send_remaining_launch_posts(self, bot: Bot, session: AsyncSession, user: User):
        """
        Obuna tasdiqlangandan keyin Day 0 bo‘yicha qolgan postlarni yuborish.
        """
        if not user.subscription_checked:
            print(f"⚠️ User {user.user_id} subscription not checked yet")
            return

        # Userga allaqachon yuborilgan postlar
        sent_posts = await session.execute(
            select(UserProgress.post_id).where(UserProgress.user_id == user.user_id)
        )
        sent_ids = {row[0] for row in sent_posts.all()}

        # Day 0 dagi barcha postlarni olish
        posts_result = await session.execute(
            select(SchedulePost)
            .where(SchedulePost.day_number == 0)
            .order_by(SchedulePost.order_number)
        )
        posts = posts_result.scalars().all()

        # subscription_check dan KEYINGI postlarni yig‘amiz
        started = False
        remaining_posts = []

        for post in posts:
            if post.post_id in sent_ids:
                if post.post_type == "subscription_check":
                    started = True
                continue

            if started:
                remaining_posts.append(post)

        if not remaining_posts:
            print(f"ℹ️ No remaining posts for user {user.user_id}")
            return

        print(f"📤 Sending {len(remaining_posts)} remaining posts to user {user.user_id}")

        for post in remaining_posts:
            delay = post.delay_seconds or 0
            if delay > 0:
                print(f"⏳ Waiting {delay} seconds before sending post {post.post_id}")
                await asyncio.sleep(delay)

            success = await self._send_post(bot, user.user_id, post)

            if success:
                session.add(
                    UserProgress(
                        user_id=user.user_id,
                        post_id=post.post_id,
                        status="sent",
                    )
                )
                print(f"✅ Post {post.post_id} sent to user {user.user_id}")

        await session.commit()

    async def send_scheduled_posts(self, session: AsyncSession):
        """
        Oddiy kunlar (day 1+) uchun HH:MM bo‘yicha postlarni yuborish.
        Har minutda scheduler orqali chaqiriladi.
        """
        now = datetime.now().strftime("%H:%M")
        moscow_now = format_moscow_time(now)

        posts_result = await session.execute(
            select(SchedulePost)
            .join(ScheduleDay)
            .where(
                ScheduleDay.day_type > 0,  # Faqat oddiy kunlar (Day > 0)
                SchedulePost.time == moscow_now,
            )
        )
        posts = posts_result.scalars().all()

        if not posts:
            return

        print(f"📅 Found {len(posts)} scheduled posts for {moscow_now}")

        for post in posts:
            users_result = await session.execute(
                select(User).where(
                    User.current_day == post.day_number,
                    User.is_subscribed == True,
                    User.is_blocked == False,
                )
            )

            for user in users_result.scalars():
                exists = await session.execute(
                    select(UserProgress).where(
                        UserProgress.user_id == user.user_id,
                        UserProgress.post_id == post.post_id,
                    )
                )
                if exists.scalar():
                    continue

                success = await self._send_post(self.bot, user.user_id, post)

                if success:
                    session.add(
                        UserProgress(
                            user_id=user.user_id,
                            post_id=post.post_id,
                            status="sent",
                        )
                    )
                    print(f"✅ Scheduled post {post.post_id} sent to user {user.user_id}")

        await session.commit()

    async def update_user_days(self, session: AsyncSession):
        """
        Har kuni belgilangan vaqtda barcha aktiv userlarning current_day'ini oshirish.
        """
        result = await session.execute(
            select(User).where(
                User.is_subscribed == True,
                User.is_blocked == False,
            )
        )
        users = result.scalars().all()

        updated_count = 0
        for user in users:
            user.current_day += 1
            updated_count += 1

        await session.commit()
        print(f"📆 Updated {updated_count} users to next day")

    async def cleanup_old_progress(self, session: AsyncSession):
        """
        30 kundan eski progress yozuvlarini o‘chirish.
        """
        thirty_days_ago = datetime.now() - timedelta(days=30)

        result = await session.execute(
            select(UserProgress).where(UserProgress.sent_date < thirty_days_ago)
        )
        old_progress = result.scalars().all()

        for progress in old_progress:
            await session.delete(progress)

        await session.commit()
        print(f"🗑️ Cleaned up {len(old_progress)} old progress records")

    async def check_launch_users(self, session: AsyncSession):
        """
        Day 0 sequence'ni ishga tushirish uchun userlarni tekshirish.
        Endi faqat:
        - current_day == 0
        - is_subscribed == True
        - subscription_checked == True
        - first_message_sent == False
        bo‘lganlarga ishlaydi.
        """
        users_result = await session.execute(
            select(User).where(
                User.current_day == 0,
                User.is_subscribed == True,
                User.subscription_checked == True,
                User.first_message_sent == False,
                User.is_blocked == False,
            )
        )

        for user in users_result.scalars():
            print(f"🔍 Found launch user {user.user_id} without sequence – running it")
            await self.send_launch_sequence(self.bot, session, user)
