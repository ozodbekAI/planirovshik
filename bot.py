# bot.py
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import config
from database import init_db, close_db
from middleware.db import DatabaseMiddleware
from handlers import user, admin, stats, broadcast
from scheduler.tasks import SchedulerTasks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Agar local Bot API server ishlatmoqchi bo'lsangiz:
# from aiogram.client.session.aiohttp import AiohttpSession
# session = AiohttpSession(api=config.BOT_API_SERVER)
# bot = Bot(token=config.BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

async def on_startup():
    try:
        config.validate()
        logger.info("✅ Configuration validated")
        logger.info(f"🌍 Timezone: {config.TIMEZONE}")
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)

    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        sys.exit(1)
    
    scheduler_tasks = SchedulerTasks(bot)
    
    scheduler.add_job(
        scheduler_tasks.send_scheduled_posts,
        trigger=IntervalTrigger(minutes=1),
        id='send_scheduled_posts',
        name='Send scheduled posts',
        replace_existing=True
    )

    scheduler.add_job(
        scheduler_tasks.update_user_days,
        trigger=CronTrigger(hour=0, minute=5, timezone=config.TIMEZONE),
        id='update_user_days',
        name='Update user days daily',
        replace_existing=True
    )

    scheduler.add_job(
        scheduler_tasks.cleanup_old_progress,
        trigger=CronTrigger(hour=3, minute=0, timezone=config.TIMEZONE),
        id='cleanup_old_progress',
        name='Cleanup old progress',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("✅ Scheduler started")
    
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🤖 <b>Бот успешно запущен!</b>\n\n"
                f"⏰ Scheduler активен\n"
                f"🗄 База данных подключена\n"
                f"🌍 Часовой пояс: {config.TIMEZONE}\n"
                f"✅ Все системы работают",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to send startup message to admin {admin_id}: {e}")
    
    logger.info("✅ Bot started successfully!")

async def on_shutdown():
    """Bot to'xtaganda"""
    logger.info("🛑 Shutting down bot...")
    
    # Scheduler to'xtatish
    scheduler.shutdown()
    logger.info("✅ Scheduler stopped")
    
    # Database yopish
    await close_db()
    logger.info("✅ Database connection closed")
    
    # Adminlarga xabar yuborish
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🛑 <b>Бот остановлен</b>",
                parse_mode="HTML"
            )
        except:
            pass
    
    logger.info("✅ Bot stopped successfully!")

async def main():
    """Asosiy funksiya"""
    
    # Middleware ulash
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    
    # Handlerlarni ro'yxatdan o'tkazish
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(stats.router)
    dp.include_router(broadcast.router)
    
    # Startup va Shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Botni ishga tushirish
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)