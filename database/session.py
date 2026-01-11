from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    async_sessionmaker, 
    AsyncSession,
    AsyncEngine
)
import sqlalchemy as sa
from config import config
from database.base import Base

# Engine yaratish
engine: AsyncEngine = create_async_engine(
    config.DATABASE_URL,
    echo=False,  # SQL querylarni ko'rsatish (development uchun True)
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

@asynccontextmanager
async def get_session():
    """Async context manager for DB session"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """Database yaratish.

    NOTE:
    - Agar Alembic migratsiyalar ishlatilsa, start paytida `create_all()` DB'ni "oldindan"
      yaratib yuboradi va keyin `alembic upgrade head` DuplicateTable xatosiga olib kelishi mumkin.
    - Shu sababli: agar DB'da `alembic_version` jadvali mavjud bo'lsa, bu loyiha migratsiya rejimida
      deb hisoblaymiz va `create_all()` ni ishlatmaymiz.
    """

    async with engine.begin() as conn:
        def _has_alembic_version(sync_conn):
            insp = sa.inspect(sync_conn)
            return insp.has_table("alembic_version")

        has_alembic = await conn.run_sync(_has_alembic_version)
        if has_alembic:
            # Migrations should handle schema creation.
            return

        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Database connectionni yopish"""
    await engine.dispose()