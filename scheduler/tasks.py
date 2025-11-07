import asyncio
import logging
from datetime import datetime, timedelta
from typing import List
import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text

from database import async_session_maker
from database.base import User, SchedulePost, UserProgress
from config import config
from utils.helpers import check_subscription

logger = logging.getLogger(__name__)

class SchedulerTasks:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.timezone = pytz.timezone(config.TIMEZONE)
    
    async def send_scheduled_posts(self):
        """Rejalashtirilgan postlarni yuborish"""
        logger.info("🔄 Checking for scheduled posts...")
        
        async with async_session_maker() as session:
            try:
                # Hozirgi vaqt (timezone bilan)
                now = datetime.now(self.timezone)
                current_time = now.strftime("%H:%M")
                current_date = now.date()
                
                logger.info(f"⏰ Current time: {current_time}, Date: {current_date}")
                
                # 1. Barcha aktiv userlarni olish
                users_result = await session.execute(
                    select(User).where(
                        and_(
                            User.is_blocked == False,
                            User.is_active == True
                        )
                    )
                )
                users = users_result.scalars().all()
                
                logger.info(f"👥 Found {len(users)} active users")
                
                if not users:
                    logger.info("✅ No active users")
                    return
                
                sent_count = 0
                failed_count = 0
                
                # 2. Har bir user uchun postlarni tekshirish
                for user in users:
                    # ✅ MUHIM: Aynan hozirgi daqiqadagi postlarni olish
                    # Masalan: 02:58 bo'lsa, faqat 02:58 uchun postlarni yuborish
                    posts_result = await session.execute(
                        select(SchedulePost).where(
                            and_(
                                SchedulePost.day_number == user.current_day,
                                SchedulePost.time == current_time  # ✅ Faqat aynan hozirgi vaqt
                            )
                        ).order_by(SchedulePost.order_number)
                    )
                    posts = posts_result.scalars().all()
                    
                    if not posts:
                        continue
                    
                    logger.info(f"📬 User {user.user_id}: Day {user.current_day}, Found {len(posts)} posts for {current_time}")
                    
                    for post in posts:
                        # Bugun allaqachon yuborilganligini tekshirish
                        check_result = await session.execute(
                            select(UserProgress).where(
                                and_(
                                    UserProgress.user_id == user.user_id,
                                    UserProgress.post_id == post.post_id,
                                    func.date(UserProgress.sent_date) == current_date
                                )
                            )
                        )
                        already_sent = check_result.scalar_one_or_none()
                        
                        if already_sent:
                            logger.info(f"⏭️ Post {post.post_id} already sent to user {user.user_id} today")
                            continue
                        
                        # Obunani qayta tekshirish
                        is_subscribed = await check_subscription(self.bot, user.user_id)
                        
                        if not is_subscribed:
                            logger.warning(f"⚠️ User {user.user_id} is not subscribed")
                            await self.send_unsubscribed_warning(user.user_id)
                            user.is_subscribed = False
                            await session.commit()
                            break  # Bu userga boshqa postlar yuborilmaydi
                        
                        # Postni yuborish
                        logger.info(f"📤 Sending post {post.post_id} ({post.post_type}) to user {user.user_id}")
                        success = await self.send_post(user.user_id, post)
                        
                        if success:
                            # Yuborilganini belgilash
                            progress = UserProgress(
                                user_id=user.user_id,
                                post_id=post.post_id,
                                status='sent'
                            )
                            session.add(progress)
                            await session.commit()
                            sent_count += 1
                            logger.info(f"✅ Post {post.post_id} sent successfully to user {user.user_id}")
                        else:
                            failed_count += 1
                            logger.error(f"❌ Failed to send post {post.post_id} to user {user.user_id}")
                        
                        # Anti-flood
                        await asyncio.sleep(0.05)
                
                logger.info(f"✅ Scheduler finished: Sent: {sent_count}, Failed: {failed_count}")
                
            except Exception as e:
                logger.error(f"❌ Error in send_scheduled_posts: {e}", exc_info=True)
                await session.rollback()
    
    async def send_post(self, user_id: int, post: SchedulePost) -> bool:
        """Postni yuborish"""
        try:
            if post.post_type == 'text':
                await self.bot.send_message(
                    chat_id=user_id,
                    text=post.content,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'photo':
                await self.bot.send_photo(
                    chat_id=user_id,
                    photo=post.file_id,
                    caption=post.caption,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'video':
                await self.bot.send_video(
                    chat_id=user_id,
                    video=post.file_id,
                    caption=post.caption,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'video_note':
                await self.bot.send_video_note(
                    chat_id=user_id,
                    video_note=post.file_id
                )
            
            elif post.post_type == 'audio':
                await self.bot.send_audio(
                    chat_id=user_id,
                    audio=post.file_id,
                    caption=post.caption,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'document':
                await self.bot.send_document(
                    chat_id=user_id,
                    document=post.file_id,
                    caption=post.caption,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'voice':
                await self.bot.send_voice(
                    chat_id=user_id,
                    voice=post.file_id,
                    caption=post.caption,
                    parse_mode="HTML"
                )
            
            elif post.post_type == 'link':
                buttons = post.buttons
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text=buttons['inline'][0][0]['text'],
                            url=buttons['inline'][0][0]['url']
                        )]
                    ]
                )
                await self.bot.send_message(
                    chat_id=user_id,
                    text=post.content,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            
            return True
            
        except TelegramForbiddenError:
            # User botni bloklagan
            logger.warning(f"⛔ User {user_id} blocked the bot")
            await self.mark_user_blocked(user_id)
            return False
        
        except TelegramBadRequest as e:
            logger.error(f"❌ Bad request for user {user_id}: {e}")
            return False
        
        except Exception as e:
            logger.error(f"❌ Error sending post to {user_id}: {e}", exc_info=True)
            return False
    
    async def send_unsubscribed_warning(self, user_id: int):
        """Obuna yo'q ogohlantirishi"""
        from keyboards.user_kb import get_subscribe_keyboard
        from utils.texts import Texts
        
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=Texts.UNSUBSCRIBED_WARNING,
                reply_markup=get_subscribe_keyboard(),
                parse_mode="HTML"
            )
            logger.info(f"⚠️ Sent unsubscribed warning to user {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send warning to user {user_id}: {e}")
    
    async def mark_user_blocked(self, user_id: int):
        """Userni bloklangan deb belgilash"""
        async with async_session_maker() as session:
            try:
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if user:
                    user.is_blocked = True
                    user.is_active = False
                    await session.commit()
                    logger.info(f"🚫 Marked user {user_id} as blocked")
            except Exception as e:
                logger.error(f"❌ Error marking user {user_id} as blocked: {e}")
    
    async def update_user_days(self):
        """Foydalanuvchilarning kunlarini yangilash"""
        logger.info("🔄 Updating user days...")
        
        async with async_session_maker() as session:
            try:
                now = datetime.now(self.timezone)
                current_date = now.date()
                
                # Barcha aktiv foydalanuvchilarni olish
                result = await session.execute(
                    select(User).where(
                        and_(
                            User.is_subscribed == True,
                            User.is_blocked == False,
                            User.is_active == True
                        )
                    )
                )
                users = result.scalars().all()
                
                updated_count = 0
                
                for user in users:
                    # Foydalanuvchi necha kun oldin ro'yxatdan o'tganini hisoblash
                    days_since_start = (current_date - user.start_date.date()).days + 1
                    
                    if days_since_start > user.current_day:
                        user.current_day = days_since_start
                        updated_count += 1
                        logger.info(f"📅 User {user.user_id}: Day {user.current_day - 1} → {user.current_day}")
                
                await session.commit()
                logger.info(f"✅ Updated {updated_count} users to new day")
                
            except Exception as e:
                logger.error(f"❌ Error in update_user_days: {e}", exc_info=True)
                await session.rollback()
    
    async def cleanup_old_progress(self):
        """Eski progressni tozalash (30 kundan eski)"""
        logger.info("🔄 Cleaning up old progress...")
        
        async with async_session_maker() as session:
            try:
                from sqlalchemy import delete
                
                thirty_days_ago = datetime.now(self.timezone) - timedelta(days=30)
                
                result = await session.execute(
                    delete(UserProgress).where(
                        UserProgress.sent_date < thirty_days_ago
                    )
                )
                
                await session.commit()
                deleted_count = result.rowcount
                logger.info(f"✅ Cleaned up {deleted_count} old progress records")
                
            except Exception as e:
                logger.error(f"❌ Error in cleanup_old_progress: {e}", exc_info=True)
                await session.rollback()