from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    async_sessionmaker, 
    AsyncSession,
    AsyncEngine
)
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

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Database session olish"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """Database yaratish"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Database connectionni yopish"""
    await engine.dispose()