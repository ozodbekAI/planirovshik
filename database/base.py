# database/models.py - UPDATED
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Integer, Text, JSON, ForeignKey,
    func, Index, SmallInteger
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship


Base = declarative_base()

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
    current_day: Mapped[int] = mapped_column(Integer, default=0)
    first_message_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    
    progress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_user_subscribed', 'is_subscribed'),
        Index('idx_user_active', 'is_active'),
        Index('idx_user_day', 'current_day'),
    )

class ScheduleDay(Base):
    __tablename__ = "schedule_days"
    
    day_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    day_type: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    posts = relationship("SchedulePost", back_populates="day", cascade="all, delete-orphan")

class SchedulePost(Base):
    __tablename__ = "schedule_posts"
    
    post_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_number: Mapped[int] = mapped_column(Integer, ForeignKey("schedule_days.day_number", ondelete="CASCADE"), nullable=False)
    post_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    buttons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    order_number: Mapped[int] = mapped_column(Integer, default=0)

    survey_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        ForeignKey("surveys.survey_id", ondelete="SET NULL"), 
        nullable=True
    )
    
    day = relationship("ScheduleDay", back_populates="posts")
    progress = relationship("UserProgress", back_populates="post", cascade="all, delete-orphan")
    survey = relationship("Survey")
    
    __table_args__ = (
        Index('idx_post_day', 'day_number'),
        Index('idx_post_delay', 'delay_seconds'),
    )

class UserProgress(Base):
    __tablename__ = "user_progress"
    
    progress_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("schedule_posts.post_id", ondelete="CASCADE"), nullable=False)
    sent_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(50), default="sent")
    
    user = relationship("User", back_populates="progress")
    post = relationship("SchedulePost", back_populates="progress")
    
    __table_args__ = (
        Index('idx_progress_user', 'user_id'),
        Index('idx_progress_post', 'post_id'),
    )

class Setting(Base):
    __tablename__ = "settings"
    
    setting_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    setting_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Survey(Base):
    __tablename__ = "surveys"

    survey_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    button_text: Mapped[str] = mapped_column(String(100), nullable=False)

    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_photo_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    completion_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completion_photo_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tgtrack_target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    questions = relationship("SurveyQuestion", back_populates="survey", cascade="all, delete-orphan")
    responses = relationship("SurveyResponse", back_populates="survey", cascade="all, delete-orphan")



class SurveyQuestion(Base):
    """Vopros (Question) model"""
    __tablename__ = "survey_questions"
    
    question_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    survey_id: Mapped[int] = mapped_column(Integer, ForeignKey("surveys.survey_id", ondelete="CASCADE"))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), default="text")
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    order_number: Mapped[int] = mapped_column(Integer, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    
    survey = relationship("Survey", back_populates="questions")
    answers = relationship("SurveyAnswer", back_populates="question", cascade="all, delete-orphan")


class SurveyResponse(Base):
    """User survey response tracking"""
    __tablename__ = "survey_responses"
    
    response_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    survey_id: Mapped[int] = mapped_column(Integer, ForeignKey("surveys.survey_id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    current_question: Mapped[int] = mapped_column(Integer, default=0)
    
    user = relationship("User")
    survey = relationship("Survey", back_populates="responses")
    answers = relationship("SurveyAnswer", back_populates="response", cascade="all, delete-orphan")


class SurveyAnswer(Base):
    """Individual answers to survey questions"""
    __tablename__ = "survey_answers"
    
    answer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    response_id: Mapped[int] = mapped_column(Integer, ForeignKey("survey_responses.response_id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("survey_questions.question_id", ondelete="CASCADE"))
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    response = relationship("SurveyResponse", back_populates="answers")
    question = relationship("SurveyQuestion", back_populates="answers")


# ===================== LESSONS / UROKI =====================


class Lesson(Base):
    """Uroki (lessons) uchun model.

    Admin bitta urok yaratadi (name), so'ng unga bitta kontent biriktiriladi
    (video yoki link). Userlar deep-link orqali urokni ochadi.
    """

    __tablename__ = "lessons"

    lesson_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Kontent (SchedulePost'ga o'xshash)
    post_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    buttons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Urok ichida bir nechta post bo'lishi mumkin (den/schedule postlari kabi)
    posts = relationship("LessonPost", back_populates="lesson", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_lessons_active', 'is_active'),
    )

class LessonPost(Base):
    """Urok ichidagi postlar (den/schedule postlari kabi)."""

    __tablename__ = "lesson_posts"

    post_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(Integer, ForeignKey("lessons.lesson_id", ondelete="CASCADE"), nullable=False)

    post_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    buttons: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    order_number: Mapped[int] = mapped_column(Integer, default=0)

    survey_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("surveys.survey_id", ondelete="SET NULL"),
        nullable=True,
    )

    lesson = relationship("Lesson", back_populates="posts")
    survey = relationship("Survey")

    __table_args__ = (
        Index('idx_lesson_posts_lesson', 'lesson_id'),
        Index('idx_lesson_posts_order', 'lesson_id', 'order_number'),
    )
