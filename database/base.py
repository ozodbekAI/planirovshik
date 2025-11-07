from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Base class for all models"""
    pass

# ==================== database/models.py ====================
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Integer, Text, JSON, ForeignKey,
    func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import Base

class User(Base):
    __tablename__ = "users"
    
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_activity: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    current_day: Mapped[int] = mapped_column(Integer, default=1)
    
    # Relationships
    progress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_user_subscribed', 'is_subscribed'),
        Index('idx_user_active', 'is_active'),
        Index('idx_user_day', 'current_day'),
    )
    
    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username})>"


class ScheduleDay(Base):
    __tablename__ = "schedule_days"
    
    day_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    posts = relationship("SchedulePost", back_populates="day", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ScheduleDay(day_number={self.day_number})>"


class SchedulePost(Base):
    __tablename__ = "schedule_posts"
    
    post_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_number: Mapped[int] = mapped_column(Integer, ForeignKey("schedule_days.day_number", ondelete="CASCADE"), nullable=False)
    post_type: Mapped[str] = mapped_column(String(50), nullable=False)  # text, photo, video, voice, etc.
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM format
    buttons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    order_number: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    day = relationship("ScheduleDay", back_populates="posts")
    progress = relationship("UserProgress", back_populates="post", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_post_day', 'day_number'),
        Index('idx_post_time', 'time'),
    )
    
    def __repr__(self):
        return f"<SchedulePost(post_id={self.post_id}, day={self.day_number}, time={self.time})>"


class UserProgress(Base):
    __tablename__ = "user_progress"
    
    progress_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("schedule_posts.post_id", ondelete="CASCADE"), nullable=False)
    sent_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(50), default="sent")  # sent, failed, pending
    
    # Relationships
    user = relationship("User", back_populates="progress")
    post = relationship("SchedulePost", back_populates="progress")
    
    # Indexes
    __table_args__ = (
        Index('idx_progress_user', 'user_id'),
        Index('idx_progress_post', 'post_id'),
        Index('idx_progress_date', 'sent_date'),
    )
    
    def __repr__(self):
        return f"<UserProgress(user_id={self.user_id}, post_id={self.post_id})>"


class Setting(Base):
    __tablename__ = "settings"
    
    setting_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    setting_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Setting(key={self.setting_key})>"