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
from database import init_db, close_db, get_session  # get_session YANGI
from middleware.db import DatabaseMiddleware
from handlers import user, admin, stats, broadcast, survey
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

dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

# SchedulerTasks instansi
scheduler_tasks = SchedulerTasks(bot)

# ============== WRAPPER FUNKSİYALAR (session yaratadi) ==============
async def check_launch_users_wrapper():
    async with get_session() as session:
        await scheduler_tasks.check_launch_users(session)

async def send_scheduled_posts_wrapper():
    async with get_session() as session:
        await scheduler_tasks.send_scheduled_posts(session)

async def update_user_days_wrapper():
    async with get_session() as session:
        await scheduler_tasks.update_user_days(session)

async def cleanup_old_progress_wrapper():
    async with get_session() as session:
        await scheduler_tasks.cleanup_old_progress(session)

# ============== ON STARTUP ==============
async def on_startup():
    try:
        config.validate()
        logger.info("Configuration validated")
        logger.info(f"Timezone: {config.TIMEZONE}")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        sys.exit(1)

    # Scheduler joblarni qo‘shish (wrapper orqali)
    scheduler.add_job(
        check_launch_users_wrapper,
        trigger=IntervalTrigger(seconds=30),
        id='check_launch_users',
        replace_existing=True
    )

    scheduler.add_job(
        send_scheduled_posts_wrapper,
        trigger=IntervalTrigger(minutes=1),
        id='send_scheduled_posts',
        replace_existing=True
    )

    scheduler.add_job(
        update_user_days_wrapper,
        trigger=CronTrigger(hour=0, minute=5, timezone=config.TIMEZONE),
        id='update_user_days',
        replace_existing=True
    )

    scheduler.add_job(
        cleanup_old_progress_wrapper,
        trigger=CronTrigger(hour=3, minute=0, timezone=config.TIMEZONE),
        id='cleanup_old_progress',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started")

    # Adminlarga xabar
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "Bot успешно запущен!\n\n"
                "Scheduler активен\n"
                "База данных подключена\n"
                f"Часовой пояс: {config.TIMEZONE}\n"
                "Все системы работают",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")

    logger.info("Bot started!")

# ============== ON SHUTDOWN ==============
async def on_shutdown():
    logger.info("Shutting down...")
    scheduler.shutdown()
    await close_db()
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "Bot остановлен", parse_mode="HTML")
        except:
            pass
    logger.info("Bot stopped!")

# ============== MAIN ==============
async def main():
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())

    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(stats.router)
    dp.include_router(broadcast.router)
    dp.include_router(survey.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

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