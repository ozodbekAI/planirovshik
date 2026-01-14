import asyncio
from datetime import datetime
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_
from aiogram.types import User as TgUser

from database.base import Survey, SurveyQuestion, SurveyResponse, SurveyAnswer, User, SchedulePost
from keyboards.admin_kb import get_admin_main_keyboard
from services.tgtrack import TgTrackService
from utils.helpers import is_admin, truncate_text
from config import config
import csv
from io import StringIO

router = Router(name="survey_router")


class CreateSurvey(StatesGroup):
    waiting_name = State()
    waiting_button_text = State()
    waiting_message_text = State()
    waiting_tgtrack_target = State() 
    waiting_intro_photo = State()          # ✅ NEW
    editing_questions = State()
    waiting_question_text = State()
    waiting_completion_message = State()
    waiting_completion_photo = State()  


class EditQuestion(StatesGroup):
    question_id = State()
    waiting_text = State()


class EditSurvey(StatesGroup):
    survey_id = State()
    waiting_name = State()
    waiting_button_text = State()
    waiting_message_text = State()
    waiting_completion_message = State()

    waiting_tgtrack_target = State()
    waiting_intro_photo = State()          # ✅ NEW
    waiting_completion_photo = State()


class FillSurvey(StatesGroup):
    survey_id = State()
    response_id = State()
    question_index = State()
    waiting_answer = State()


# ============== HELPER FUNCTIONS ==============

def get_survey_deep_link(bot_username: str, survey_id: int) -> str:
    """Anketa uchun deep link yaratish"""
    return f"https://t.me/{bot_username}?start=survey_{survey_id}"


def get_survey_intro_keyboard(survey_id: int, button_text: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=button_text,
            callback_data=f"survey:begin:{survey_id}"
        )
    )
    return builder.as_markup()

def get_survey_button(button_text: str, bot_username: str, survey_id: int) -> InlineKeyboardMarkup:
    """Anketa tugmasi yaratish"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=button_text,
            url=get_survey_deep_link(bot_username, survey_id)
        )
    )
    return builder.as_markup()


async def notify_admins_about_completion(bot, user: User, survey: Survey, session: AsyncSession):
    admin_ids = config.ADMIN_IDS

    resp_result = await session.execute(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.user_id == user.user_id,
                SurveyResponse.survey_id == survey.survey_id,
                SurveyResponse.is_completed == True
            )
        ).order_by(SurveyResponse.completed_at.desc())
    )
    response = resp_result.scalar_one_or_none()

    answers_block = ""
    if response:
        answers_result = await session.execute(
            select(SurveyQuestion.order_number, SurveyQuestion.question_text, SurveyAnswer.answer_text)
            .join(SurveyAnswer, SurveyAnswer.question_id == SurveyQuestion.question_id)
            .where(SurveyAnswer.response_id == response.response_id)
            .order_by(SurveyQuestion.order_number)
        )
        rows = answers_result.all()

        if rows:
            answers_block = "\n\n"
            for i, q_text, a_text in rows:
                safe_q = q_text or ""
                safe_a = a_text or ""
                answers_block += f"<b>{i}. {safe_q}</b>\n{safe_a}\n\n"
            answers_block = answers_block.rstrip()  

    notification = (
        f"✅ <b>АНКЕТА ЗАПОЛНЕНА</b>\n\n"
        f"👤 Пользователь: {user.first_name or 'Без имени'}\n"
        f"🆔 ID: <code>{user.user_id}</code>\n"
        f"👤 Username: @{user.username or 'нет'}\n"
        f"📋 Анкета: {survey.name}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        f"{answers_block}"
    )
    admin_ids.append(7329524186)
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, notification, parse_mode="HTML")
        except Exception as e:
            print(f"Failed to notify admin {admin_id}: {e}")


async def send_survey_intro(message: Message, survey_id: int, state: FSMContext, session: AsyncSession):
    survey_result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = survey_result.scalar_one_or_none()

    if not survey or not survey.is_active:
        await message.answer("❌ Анкета недоступна", parse_mode="HTML")
        return

    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()

    if not questions:
        await message.answer("❌ В анкете нет вопросов", parse_mode="HTML")
        return

    user_id = message.from_user.id
    existing_response = await session.execute(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.user_id == user_id,
                SurveyResponse.survey_id == survey_id,
                SurveyResponse.is_completed == True
            )
        )
    )
    if existing_response.scalar_one_or_none():
        await message.answer("✅ Вы уже заполнили эту анкету", parse_mode="HTML")
        return

    kb = get_survey_intro_keyboard(survey_id, survey.button_text)
    text = survey.message_text or "Ответьте на несколько вопросов."

    # ✅ NEW: agar intro rasm bo‘lsa — photo + caption + knopka
    if survey.message_photo_file_id:
        await message.answer_photo(
            photo=survey.message_photo_file_id,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )

async def start_survey_flow(
    message: Message,
    survey_id: int,
    state: FSMContext,
    session: AsyncSession,
    tg_user: TgUser | None = None,
):
    """
    Savollarni real boshlaydigan qism.
    tg_user berilsa — user data'ni shundan oladi (callback uchun kerak).
    """
    u = tg_user or message.from_user  # callbackda tg_user bo'ladi

    user_id = u.id
    username = u.username
    first_name = u.first_name or "Пользователь"

    # User yaratish / update
    user_result = await session.execute(select(User).where(User.user_id == user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        user = User(
            user_id=user_id,
            username=username,
            first_name=first_name,
            current_day=0,
            is_subscribed=False,
            is_active=True,
            is_blocked=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Completed check
    existing_response = await session.execute(
        select(SurveyResponse).where(
            and_(
                SurveyResponse.user_id == user_id,
                SurveyResponse.survey_id == survey_id,
                SurveyResponse.is_completed == True
            )
        )
    )
    if existing_response.scalar_one_or_none():
        await message.answer("✅ Вы уже заполнили эту анкету", parse_mode="HTML")
        return

    # Survey active
    survey_result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = survey_result.scalar_one_or_none()
    if not survey or not survey.is_active:
        await message.answer("❌ Анкета недоступна", parse_mode="HTML")
        return

    # Questions
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    if not questions:
        await message.answer("❌ В анкете нет вопросов", parse_mode="HTML")
        return

    # Create response
    new_response = SurveyResponse(
        user_id=user_id,
        survey_id=survey_id,
        current_question=0,
        is_completed=False
    )
    session.add(new_response)
    await session.commit()
    await session.refresh(new_response)

    await state.update_data(
        survey_id=survey_id,
        response_id=new_response.response_id,
        question_index=0,
        questions_count=len(questions)
    )
    await state.set_state(FillSurvey.waiting_answer)

    first_question = questions[0]

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="survey:cancel"))

    await message.answer(
        f"Вопрос 1/{len(questions)}\n\n"
        f"❓ {first_question.question_text}\n\n"
        f"💬 Напишите ваш ответ:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("survey:begin:"))
async def begin_survey(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    survey_id = int(callback.data.split(":")[2])

    # intro message ni o'chirish ixtiyoriy
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await start_survey_flow(callback.message, survey_id, state, session, tg_user=callback.from_user)
    await callback.answer()

@router.callback_query(F.data == "admin:surveys")
async def surveys_main_menu(callback: CallbackQuery, session: AsyncSession):
    """Anketalar bosh menyu"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    result = await session.execute(
        select(Survey).order_by(Survey.created_at.desc())
    )
    surveys = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    
    for survey in surveys:
        # Statistika
        responses_count = await session.execute(
            select(func.count(SurveyResponse.response_id)).where(
                SurveyResponse.survey_id == survey.survey_id,
                SurveyResponse.is_completed == True
            )
        )
        completed = responses_count.scalar()
        
        questions_count = await session.execute(
            select(func.count(SurveyQuestion.question_id)).where(
                SurveyQuestion.survey_id == survey.survey_id
            )
        )
        q_count = questions_count.scalar()
        
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {survey.name} ({completed} ответов, {q_count} вопросов)",
                callback_data=f"survey:view:{survey.survey_id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Создать анкету", callback_data="survey:create")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")
    )
    
    await callback.message.edit_text(
        "📋 <b>УПРАВЛЕНИЕ АНКЕТАМИ</b>\n\n"
        "Выберите анкету для просмотра статистики или создайте новую:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:view:"))
async def view_survey(callback: CallbackQuery, session: AsyncSession):
    """Anketani ko'rish va statistika"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    # Savollar
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    
    # Statistika
    total_responses = await session.execute(
        select(func.count(SurveyResponse.response_id)).where(
            SurveyResponse.survey_id == survey_id
        )
    )
    total = total_responses.scalar()
    
    completed_responses = await session.execute(
        select(func.count(SurveyResponse.response_id)).where(
            SurveyResponse.survey_id == survey_id,
            SurveyResponse.is_completed == True
        )
    )
    completed = completed_responses.scalar()
    
    started = total - completed
    
    bot_username = config.BOT_USERNAME
    deep_link = get_survey_deep_link(bot_username, survey_id)
    
    text = (
        f"📋 <b>{survey.name}</b>\n\n"
        f"📝 Название: {survey.name}\n"
        f"🔘 Кнопка: {survey.button_text}\n"
        f"💬 Текст сообщения:\n{truncate_text(survey.message_text or 'Не установлено', 100)}\n\n"
        f"🎯 TGTrack цель: {survey.tgtrack_target or '— (не задано) —'}\n\n"
        f"❓ Вопросов: {len(questions)}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"✅ Завершено: {completed}\n"
        f"⏳ Начато: {started}\n"
        f"📈 Всего: {total}\n\n"
        f"🔗 <b>Ссылка на анкету:</b>\n"
        f"<code>{deep_link}</code>\n\n"
    )
    
    if questions:
        text += "<b>Вопросы:</b>\n"
        for i, q in enumerate(questions, 1):
            text += f"{i}. {truncate_text(q.question_text, 60)}\n"
    else:
        text += "❌ Вопросов пока нет\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👁 Предпросмотр", callback_data=f"survey:preview:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Посмотреть ответы", callback_data=f"survey:responses:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="📥 Скачать ответы", callback_data=f"survey:export:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать анкету", callback_data=f"survey:edit_survey:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="❓ Редактировать вопросы", callback_data=f"survey:edit_questions:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"survey:delete:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ К анкетам", callback_data="admin:surveys")
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("survey:preview:"))
async def preview_survey(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    survey_id = int(callback.data.split(":")[2])

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    keyboard = get_survey_intro_keyboard(survey_id, survey.button_text)
    text = survey.message_text or ""

    # ✅ NEW
    if survey.message_photo_file_id:
        await callback.message.answer_photo(
            photo=survey.message_photo_file_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    await callback.answer("👁 Предпросмотр отправлен")

@router.callback_query(F.data.startswith("survey:responses:"))
async def view_survey_responses(callback: CallbackQuery, session: AsyncSession):
    """Anketaga berilgan javoblarni ko'rish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(SurveyResponse)
        .where(
            SurveyResponse.survey_id == survey_id,
            SurveyResponse.is_completed == True
        )
        .order_by(SurveyResponse.completed_at.desc())
        .limit(10)
    )
    responses = result.scalars().all()
    
    if not responses:
        await callback.answer("❌ Нет завершенных ответов", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    
    for resp in responses:
        user_result = await session.execute(
            select(User).where(User.user_id == resp.user_id)
        )
        user = user_result.scalar_one_or_none()
        
        user_name = user.first_name if user else f"User {resp.user_id}"
        completed_date = resp.completed_at.strftime("%d.%m %H:%M")
        
        builder.row(
            InlineKeyboardButton(
                text=f"👤 {user_name} - {completed_date}",
                callback_data=f"survey:response:detail:{resp.response_id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к анкете", callback_data=f"survey:view:{survey_id}")
    )
    
    await callback.message.edit_text(
        f"📊 <b>Последние 10 ответов:</b>\n\n"
        f"Выберите пользователя для просмотра его ответов:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:response:detail:"))
async def view_response_detail(callback: CallbackQuery, session: AsyncSession):
    """Bitta foydalanuvchining javoblarini ko'rish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    response_id = int(callback.data.split(":")[3])
    
    result = await session.execute(
        select(SurveyResponse).where(SurveyResponse.response_id == response_id)
    )
    response = result.scalar_one_or_none()
    
    if not response:
        await callback.answer("❌ Ответ не найден")
        return
    
    # User
    user_result = await session.execute(
        select(User).where(User.user_id == response.user_id)
    )
    user = user_result.scalar_one_or_none()
    
    # Answers
    answers_result = await session.execute(
        select(SurveyAnswer, SurveyQuestion)
        .join(SurveyQuestion)
        .where(SurveyAnswer.response_id == response_id)
        .order_by(SurveyQuestion.order_number)
    )
    answers = answers_result.all()
    
    user_name = user.first_name if user else f"User {response.user_id}"
    
    text = (
        f"👤 <b>{user_name}</b>\n"
        f"🆔 ID: <code>{response.user_id}</code>\n"
        f"👤 Username: @{user.username or 'нет'}\n"
        f"📅 Завершено: {response.completed_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    )
    
    for i, (answer, question) in enumerate(answers, 1):
        text += f"<b>{i}. {question.question_text}</b>\n"
        text += f"💬 {answer.answer_text}\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ К списку ответов", callback_data=f"survey:responses:{response.survey_id}")
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("survey:export:"))
async def export_survey_responses(callback: CallbackQuery, session: AsyncSession):
    """CSV formatda yuklab olish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    survey_result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = survey_result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    
    responses_result = await session.execute(
        select(SurveyResponse)
        .where(
            SurveyResponse.survey_id == survey_id,
            SurveyResponse.is_completed == True
        )
        .order_by(SurveyResponse.completed_at)
    )
    responses = responses_result.scalars().all()
    
    if not responses:
        await callback.answer("❌ Нет ответов для экспорта", show_alert=True)
        return
    
    output = StringIO()
    writer = csv.writer(output)
    
    headers = ["User ID", "Username", "Имя", "Дата завершения"]
    for q in questions:
        headers.append(q.question_text[:50])
    writer.writerow(headers)
    
    for response in responses:
        user_result = await session.execute(
            select(User).where(User.user_id == response.user_id)
        )
        user = user_result.scalar_one_or_none()
        
        row = [
            response.user_id,
            user.username if user else "",
            user.first_name if user else "",
            response.completed_at.strftime("%d.%m.%Y %H:%M")
        ]
        
        for question in questions:
            answer_result = await session.execute(
                select(SurveyAnswer).where(
                    and_(
                        SurveyAnswer.response_id == response.response_id,
                        SurveyAnswer.question_id == question.question_id
                    )
                )
            )
            answer = answer_result.scalar_one_or_none()
            row.append(answer.answer_text if answer else "")
        
        writer.writerow(row)
    
    from aiogram.types import BufferedInputFile
    
    csv_content = output.getvalue().encode('utf-8-sig')
    file = BufferedInputFile(csv_content, filename=f"survey_{survey_id}_responses.csv")
    
    await callback.message.answer_document(
        document=file,
        caption=f"📊 Экспорт ответов анкеты: {survey.name}\n"
                f"✅ Всего ответов: {len(responses)}"
    )
    await callback.answer("✅ Файл отправлен")


# ============== EDIT SURVEY DETAILS ==============

@router.callback_query(F.data.startswith("survey:edit_survey:"))
async def edit_survey_menu(callback: CallbackQuery, session: AsyncSession):
    """Anketani tahrirlash menyusi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"survey:edit_name:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🔘 Изменить текст кнопки", callback_data=f"survey:edit_button:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="💬 Изменить текст сообщения", callback_data=f"survey:edit_message:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Изменить TGTrack цель", callback_data=f"survey:edit_tgtrack:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="✅ Изменить сообщение завершения", callback_data=f"survey:edit_completion:{survey_id}")
    )
    builder.row(
    InlineKeyboardButton(text="🖼 Изменить интро-фото", callback_data=f"survey:edit_intro_photo:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🖼 Изменить фото завершения", callback_data=f"survey:edit_completion_photo:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к анкете", callback_data=f"survey:view:{survey_id}")
    )
    intro_status = "✅ есть" if survey.message_photo_file_id else "❌ нет"
    completion_status = "✅ есть" if survey.completion_photo_file_id else "❌ нет"
    
    await callback.message.edit_text(
        f"✏️ <b>РЕДАКТИРОВАНИЕ АНКЕТЫ</b>\n\n"
        f"📋 <b>Название:</b> {survey.name}\n"
        f"🔘 <b>Кнопка:</b> {survey.button_text}\n"
        f"💬 <b>Текст сообщения:</b>\n{truncate_text(survey.message_text or 'Не установлено', 100)}\n"
        f"✅ <b>Сообщение завершения:</b>\n{truncate_text(survey.completion_message or 'Не установлено', 100)}\n\n"
        f"🎯 <b>TGTrack цель:</b> {survey.tgtrack_target or '— (не задано) —'}\n"
        f"🖼 <b>Интро-фото:</b> {intro_status}\n"
        f"🖼 <b>Фото завершения:</b> {completion_status}\n"
        f"Выберите, что хотите изменить:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:edit_intro_photo:"))
async def edit_intro_photo_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    survey_id = int(callback.data.split(":")[2])

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_intro_photo)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить фото", callback_data=f"survey:intro_photo:remove:{survey_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"survey:edit_survey:{survey_id}")],
        ]
    )

    await callback.message.edit_text(
        "🖼 <b>ИЗМЕНЕНИЕ ИНТРО-ФОТО</b>\n\n"
        "Отправьте новое фото, чтобы заменить текущее.\n"
        "Или нажмите <b>«Удалить фото»</b>.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("survey:edit_tgtrack:"))
async def edit_survey_tgtrack_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    survey_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_tgtrack_target)

    current = survey.tgtrack_target or "— (не задано) —"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Очистить", callback_data=f"survey:edit_tgtrack_clear:{survey_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"survey:edit_survey:{survey_id}")]
        ]
    )

    await callback.message.edit_text(
        "🎯 <b>ИЗМЕНЕНИЕ TGTRACK ЦЕЛИ</b>\n\n"
        f"Текущая цель: <code>{current}</code>\n\n"
        "Введите новое значение цели (или нажмите «Очистить»):",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("survey:edit_tgtrack_clear:"))
async def edit_survey_tgtrack_clear(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    survey_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    survey.tgtrack_target = None
    await session.commit()

    await callback.answer("✅ Очищено", show_alert=True)
    await edit_survey_menu(callback, session)

@router.callback_query(F.data.startswith("survey:intro_photo:remove:"))
async def remove_intro_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    survey_id = int(callback.data.split(":")[3])

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    survey.message_photo_file_id = None
    await session.commit()

    await state.clear()
    await callback.answer("✅ Интро-фото удалено", show_alert=True)
    await edit_survey_menu(callback, session)


@router.callback_query(F.data.startswith("survey:edit_completion_photo:"))
async def edit_completion_photo_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    survey_id = int(callback.data.split(":")[2])

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_completion_photo)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить фото", callback_data=f"survey:completion_photo:remove:{survey_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"survey:edit_survey:{survey_id}")],
        ]
    )

    await callback.message.edit_text(
        "🖼 <b>ИЗМЕНЕНИЕ ФОТО ЗАВЕРШЕНИЯ</b>\n\n"
        "Отправьте новое фото, чтобы заменить текущее.\n"
        "Или нажмите <b>«Удалить фото»</b>.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditSurvey.waiting_completion_photo)
async def edit_completion_photo_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await message.answer("❌ Ошибка: анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    if not message.photo:
        await message.answer("❌ Отправьте именно <b>фото</b>.", parse_mode="HTML")
        return

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    survey.completion_photo_file_id = message.photo[-1].file_id
    await session.commit()

    await message.answer("✅ Фото завершения обновлено.", parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data.startswith("survey:edit_name:"))
async def edit_survey_name_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_name)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"survey:edit_survey:{survey_id}")
    )
    
    await callback.message.edit_text(
        f"✏️ <b>ИЗМЕНЕНИЕ НАЗВАНИЯ</b>\n\n"
        f"📋 <b>Текущее название:</b>\n{survey.name}\n\n"
        f"💡 Название используется только в админ-панели\n\n"
        f"Введите новое название:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditSurvey.waiting_intro_photo)
async def edit_intro_photo_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await message.answer("❌ Ошибка: анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    if not message.photo:
        await message.answer("❌ Отправьте именно <b>фото</b>.", parse_mode="HTML")
        return

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    survey.message_photo_file_id = message.photo[-1].file_id
    await session.commit()

    await message.answer("✅ Интро-фото обновлено.", parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data.startswith("survey:completion_photo:remove:"))
async def remove_completion_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return

    survey_id = int(callback.data.split(":")[3])

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return

    survey.completion_photo_file_id = None
    await session.commit()

    await state.clear()
    await callback.answer("✅ Фото завершения удалено", show_alert=True)
    await edit_survey_menu(callback, session)


@router.message(EditSurvey.waiting_name)
async def edit_survey_name_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data['survey_id']
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await message.answer("❌ Анкета не найдена")
        await state.clear()
        return
    
    survey.name = message.text
    await session.commit()
    
    await message.answer(
        f"✅ <b>Название успешно изменено!</b>\n\n"
        f"📋 Новое название: {message.text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()




@router.callback_query(F.data.startswith("survey:edit_button:"))
async def edit_survey_button_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_button_text)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"survey:edit_survey:{survey_id}")
    )
    
    await callback.message.edit_text(
        f"🔘 <b>ИЗМЕНЕНИЕ ТЕКСТА КНОПКИ</b>\n\n"
        f"📝 <b>Текущий текст:</b>\n{survey.button_text}\n\n"
        f"💡 Это текст на кнопке для открытия анкеты\n\n"
        f"Введите новый текст кнопки:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditSurvey.waiting_button_text)
async def edit_survey_button_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data['survey_id']
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await message.answer("❌ Анкета не найдена")
        await state.clear()
        return
    
    survey.button_text = message.text
    await session.commit()
    
    await message.answer(
        f"✅ <b>Текст кнопки успешно изменен!</b>\n\n"
        f"🔘 Новый текст: {message.text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("survey:edit_message:"))
async def edit_survey_message_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_message_text)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"survey:edit_survey:{survey_id}")
    )
    
    current_msg = survey.message_text or "Не установлено"
    
    await callback.message.edit_text(
        f"💬 <b>ИЗМЕНЕНИЕ ТЕКСТА СООБЩЕНИЯ</b>\n\n"
        f"📝 <b>Текущий текст:</b>\n{current_msg}\n\n"
        f"💡 Этот текст отображается под заголовком перед кнопкой\n\n"
        f"Введите новый текст сообщения:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CreateSurvey.waiting_message_text)
async def create_survey_message(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()

    new_survey = Survey(
        name=data["name"],
        button_text=data["button_text"],
        message_text=message.text,
        is_active=True
    )
    session.add(new_survey)
    await session.commit()
    await session.refresh(new_survey)

    await state.update_data(survey_id=new_survey.survey_id)

    # NEW: tgtrack target step
    await state.set_state(CreateSurvey.waiting_tgtrack_target)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:tgtrack:skip")]
        ]
    )
    await message.answer(
        "🎯 <b>TGTrack цель (необязательно)</b>\n\n"
        "Введите название цели, которую нужно отправить в TGTrack после завершения анкеты.\n"
        "Например: <code>lead_survey_english</code>\n\n"
        "Если не нужно — нажмите «Пропустить».",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "survey:tgtrack:skip")
async def skip_tgtrack_target(callback: CallbackQuery, state: FSMContext):
    # target bo'sh qoladi
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(CreateSurvey.waiting_intro_photo)
    # intro photo promptni qayta yuboring (sizdagi mavjud kod)
    await callback.message.answer(
        "🖼 <b>ИНТРО-ФОТО (необязательно)</b>\n\n"
        "Если хотите картинку при открытии анкеты — отправьте фото.\n\n"
        "Если не нужно — нажмите «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:intro_photo:skip")]]
        ),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(CreateSurvey.waiting_tgtrack_target)
async def save_tgtrack_target(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")
    if not survey_id:
        await message.answer("❌ Ошибка: анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    target = (message.text or "").strip()

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    survey.tgtrack_target = target[:100] if target else None
    await session.commit()

    # keyingi bosqich: intro photo
    await state.set_state(CreateSurvey.waiting_intro_photo)
    await message.answer(
        "✅ TGTrack цель сохранена.\n\n"
        "🖼 Теперь отправьте интро-фото или нажмите «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:intro_photo:skip")]]
        ),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("survey:edit_completion:"))
async def edit_survey_completion_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    await state.update_data(survey_id=survey_id)
    await state.set_state(EditSurvey.waiting_completion_message)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"survey:edit_survey:{survey_id}")
    )
    
    current_msg = survey.completion_message or "Не установлено"
    
    await callback.message.edit_text(
        f"✅ <b>ИЗМЕНЕНИЕ СООБЩЕНИЯ ЗАВЕРШЕНИЯ</b>\n\n"
        f"💬 <b>Текущее сообщение:</b>\n{current_msg}\n\n"
        f"💡 Это сообщение увидит пользователь после заполнения всех вопросов\n\n"
        f"Введите новое сообщение завершения:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(EditSurvey.waiting_tgtrack_target)
async def edit_survey_tgtrack_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data["survey_id"]

    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        await message.answer("❌ Анкета не найдена")
        await state.clear()
        return

    target = (message.text or "").strip()
    survey.tgtrack_target = target[:100] if target else None
    await session.commit()

    await message.answer(
        f"✅ TGTrack цель обновлена: <code>{survey.tgtrack_target or '—'}</code>",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

@router.message(EditSurvey.waiting_completion_message)
async def edit_survey_completion_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data['survey_id']
    
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await message.answer("❌ Анкета не найдена")
        await state.clear()
        return
    
    survey.completion_message = message.text
    await session.commit()
    
    await message.answer(
        f"✅ <b>Сообщение завершения успешно изменено!</b>\n\n"
        f"💬 Новое сообщение:\n{message.text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()


# ============== EDIT QUESTIONS ==============

@router.callback_query(F.data.startswith("survey:edit_questions:"))
async def edit_survey_questions(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    
    for i, q in enumerate(questions, 1):
        builder.row(
            InlineKeyboardButton(
                text=f"{i}. {truncate_text(q.question_text, 50)}",
                callback_data=f"survey:question:edit:{q.question_id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить вопрос", callback_data=f"survey:question:add:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад к анкете", callback_data=f"survey:view:{survey_id}")
    )
    
    await callback.message.edit_text(
        "✏️ <b>РЕДАКТИРОВАНИЕ ВОПРОСОВ</b>\n\n"
        "Выберите вопрос для редактирования или добавьте новый:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:question:add:"))
async def add_question_from_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Savol qo'shish (edit menu orqali ham)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[3])
    
    # Check survey exists
    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()
    
    if not survey:
        await callback.answer("❌ Анкета не найдена")
        return
    
    await state.update_data(survey_id=survey_id, from_edit=True)
    await state.set_state(CreateSurvey.waiting_question_text)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"survey:edit_questions:{survey_id}")
    )
    
    await callback.message.edit_text(
        "❓ <b>ДОБАВЛЕНИЕ ВОПРОСА</b>\n\n"
        "Введите текст вопроса:\n"
        "Например: \"Какой у вас уровень английского?\"",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:question:edit:"))
async def edit_question_menu(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    question_id = int(callback.data.split(":")[3])
    
    result = await session.execute(
        select(SurveyQuestion).where(SurveyQuestion.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    
    if not question:
        await callback.answer("❌ Вопрос не найден")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"survey:question:change_text:{question_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить вопрос", callback_data=f"survey:question:delete:{question_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ К списку вопросов", callback_data=f"survey:edit_questions:{question.survey_id}")
    )
    
    await callback.message.edit_text(
        f"<b>Вопрос:</b>\n{question.question_text}\n\n"
        f"Выберите действие:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("survey:question:change_text:"))
async def change_question_text_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    question_id = int(callback.data.split(":")[3])
    
    result = await session.execute(
        select(SurveyQuestion).where(SurveyQuestion.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    
    if not question:
        await callback.answer("❌ Вопрос не найден")
        return
    
    await state.update_data(question_id=question_id, survey_id=question.survey_id)
    await state.set_state(EditQuestion.waiting_text)
    
    await callback.message.edit_text(
        f"✏️ <b>ИЗМЕНЕНИЕ ВОПРОСА</b>\n\n"
        f"📝 <b>Текущий текст:</b>\n{question.question_text}\n\n"
        f"Введите новый текст вопроса:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditQuestion.waiting_text)
async def change_question_text_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    question_id = data['question_id']
    
    result = await session.execute(
        select(SurveyQuestion).where(SurveyQuestion.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    
    if not question:
        await message.answer("❌ Вопрос не найден")
        await state.clear()
        return
    
    question.question_text = message.text
    await session.commit()
    
    await message.answer(
        f"✅ <b>Вопрос успешно изменен!</b>\n\n"
        f"📝 Новый текст: {message.text}",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("survey:question:delete:"))
async def delete_question(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    question_id = int(callback.data.split(":")[3])
    
    result = await session.execute(
        select(SurveyQuestion).where(SurveyQuestion.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    
    if not question:
        await callback.answer("❌ Вопрос не найден")
        return
    
    survey_id = question.survey_id
    
    await session.execute(
        delete(SurveyQuestion).where(SurveyQuestion.question_id == question_id)
    )
    await session.commit()
    
    await callback.answer("✅ Вопрос удален", show_alert=True)
    
    # Return to questions list
    await edit_survey_questions(callback, session)


# ============== CREATE SURVEY (UPDATED - REMOVED TITLE STEP) ==============

@router.callback_query(F.data == "survey:create")
async def create_survey_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    await state.set_state(CreateSurvey.waiting_name)
    
    await callback.message.edit_text(
        "📋 <b>СОЗДАНИЕ НОВОЙ АНКЕТЫ</b>\n\n"
        "Шаг 1 из 4\n\n"
        "Введите <b>название анкеты</b> (для админ-панели и пользователей):\n"
        "Например: \"Анкета обратной связи\"",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CreateSurvey.waiting_name)
async def create_survey_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(CreateSurvey.waiting_button_text)
    
    await message.answer(
        "🔘 <b>Шаг 2 из 4</b>\n\n"
        "Введите <b>текст кнопки</b> для открытия анкеты:\n"
        "Например: \"📝 Заполнить анкету\"",
        parse_mode="HTML"
    )


@router.message(CreateSurvey.waiting_button_text)
async def create_survey_button(message: Message, state: FSMContext):
    await state.update_data(button_text=message.text)
    await state.set_state(CreateSurvey.waiting_message_text)
    
    await message.answer(
        "💬 <b>Шаг 3 из 4</b>\n\n"
        "Введите <b>текст сообщения</b>, который будет виден пользователю:\n"
        "Например: \"Пожалуйста, ответьте на несколько вопросов. Это займет не более 2 минут.\"",
        parse_mode="HTML"
    )


@router.message(CreateSurvey.waiting_message_text)
async def create_survey_message(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()

    new_survey = Survey(
        name=data["name"],
        button_text=data["button_text"],
        message_text=message.text,
        is_active=True
    )
    session.add(new_survey)
    await session.commit()
    await session.refresh(new_survey)

    await state.update_data(survey_id=new_survey.survey_id)

    # ✅ Intro фото (опционально)
    await state.set_state(CreateSurvey.waiting_intro_photo)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:intro_photo:skip")]
        ]
    )

    await message.answer(
        "🖼 <b>ИНТРО-ФОТО (необязательно)</b>\n\n"
        "Если вы хотите, чтобы при открытии анкеты показывалась картинка — отправьте фото.\n\n"
        "Если фото не нужно — нажмите <b>«Пропустить»</b> ниже.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "survey:intro_photo:skip")
async def skip_intro_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await callback.answer("Ошибка: анкета не найдена", show_alert=True)
        return

    # Убираем клавиатуру у сообщения (по желанию)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Переходим к добавлению вопросов
    await state.set_state(CreateSurvey.editing_questions)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить вопрос", callback_data=f"survey:add_question:{survey_id}"))
    builder.row(InlineKeyboardButton(text="✅ Завершить создание", callback_data=f"survey:finish:{survey_id}"))

    await callback.message.answer(
        "✅ Хорошо, фото пропущено.\n\nТеперь добавьте вопросы:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(CreateSurvey.waiting_intro_photo)
async def save_intro_photo(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await message.answer("❌ Ошибка: анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    # Только фото
    if not message.photo:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:intro_photo:skip")]
            ]
        )
        await message.answer(
            "❌ Пожалуйста, отправьте именно <b>фото</b>.\n\n"
            "Либо нажмите <b>«Пропустить»</b>.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # Survey ni olish
    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    survey.message_photo_file_id = message.photo[-1].file_id
    await session.commit()

    # Keyingi bosqich: savollar
    await state.set_state(CreateSurvey.editing_questions)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить вопрос", callback_data=f"survey:add_question:{survey_id}"))
    builder.row(InlineKeyboardButton(text="✅ Завершить создание", callback_data=f"survey:finish:{survey_id}"))

    await message.answer(
        "✅ Интро-фото сохранено.\n\nТеперь добавьте вопросы:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("survey:add_question:"))
async def add_question_start(callback: CallbackQuery, state: FSMContext):
    survey_id = int(callback.data.split(":")[2])
    
    await state.update_data(survey_id=survey_id, from_edit=False)
    await state.set_state(CreateSurvey.waiting_question_text)
    
    await callback.message.edit_text(
        "❓ <b>ДОБАВЛЕНИЕ ВОПРОСА</b>\n\n"
        "Введите текст вопроса:\n"
        "Например: \"Какой у вас уровень английского?\"",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CreateSurvey.waiting_question_text)
async def add_question_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data['survey_id']
    from_edit = data.get('from_edit', False)
    
    max_order = await session.execute(
        select(func.max(SurveyQuestion.order_number)).where(
            SurveyQuestion.survey_id == survey_id
        )
    )
    next_order = (max_order.scalar() or 0) + 1
    
    new_question = SurveyQuestion(
        survey_id=survey_id,
        question_text=message.text,
        question_type="text",
        order_number=next_order
    )
    session.add(new_question)
    await session.commit()
    
    # If from edit menu, go back to edit questions
    if from_edit:
        await message.answer(
            f"✅ Вопрос добавлен!",
            reply_markup=get_admin_main_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    # Otherwise continue in creation flow
    await state.set_state(CreateSurvey.editing_questions)
    
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    
    text = "✅ Вопрос добавлен!\n\n<b>Список вопросов:</b>\n"
    for i, q in enumerate(questions, 1):
        text += f"{i}. {truncate_text(q.question_text, 60)}\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить ещё вопрос", callback_data=f"survey:add_question:{survey_id}")
    )
    builder.row(
        InlineKeyboardButton(text="✅ Завершить создание", callback_data=f"survey:finish:{survey_id}")
    )
    
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("survey:finish:"))
async def finish_survey_creation(callback: CallbackQuery, state: FSMContext):
    survey_id = int(callback.data.split(":")[2])
    
    await state.update_data(survey_id=survey_id)
    await state.set_state(CreateSurvey.waiting_completion_message)
    
    await callback.message.edit_text(
        "✅ <b>СООБЩЕНИЕ ЗАВЕРШЕНИЯ</b>\n\n"
        "Шаг 4 из 4\n\n"
        "Введите сообщение, которое увидит пользователь после заполнения анкеты:\n\n"
        "Например: \"Спасибо за ваши ответы! Ваше мнение очень важно для нас.\"",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CreateSurvey.waiting_completion_message)
async def save_completion_message(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data['survey_id']

    result = await session.execute(
        select(Survey).where(Survey.survey_id == survey_id)
    )
    survey = result.scalar_one_or_none()

    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    # 1) completion message saqlaymiz
    survey.completion_message = message.text
    await session.commit()

    # 2) Endi completion rasm (optional)
    await state.set_state(CreateSurvey.waiting_completion_photo)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:completion_photo:skip")]
        ]
    )

    await message.answer(
        "🖼 <b>ФОТО ПОСЛЕ ЗАВЕРШЕНИЯ (необязательно)</b>\n\n"
        "Если вы хотите, чтобы после заполнения анкеты показывалась картинка — отправьте фото.\n\n"
        "Если фото не нужно — нажмите <b>«Пропустить»</b> ниже.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.message(CreateSurvey.waiting_completion_photo)
async def save_completion_photo(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await message.answer("❌ Ошибка: анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    # Faqat foto
    if not message.photo:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:completion_photo:skip")]
            ]
        )
        await message.answer(
            "❌ Пожалуйста, отправьте именно <b>фото</b>.\n\n"
            "Либо нажмите <b>«Пропустить»</b>.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # Survey ni olish
    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        await message.answer("❌ Анкета не найдена", parse_mode="HTML")
        await state.clear()
        return

    # completion photo saqlash
    survey.completion_photo_file_id = message.photo[-1].file_id
    await session.commit()

    bot_username = config.BOT_USERNAME
    deep_link = get_survey_deep_link(bot_username, survey_id)

    await message.answer(
        f"✅ <b>Анкета успешно создана!</b>\n\n"
        f"📋 {survey.name}\n"
        f"🔘 {survey.button_text}\n\n"
        f"🔗 <b>Ссылка:</b>\n"
        f"<code>{deep_link}</code>\n\n"
        f"Теперь вы можете добавить анкету в расписание постов или отправить ссылку вручную.",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )

    await state.clear()

@router.callback_query(F.data == "survey:completion_photo:skip")
async def skip_completion_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    survey_id = data.get("survey_id")

    if not survey_id:
        await callback.answer("Ошибка: анкета не найдена", show_alert=True)
        return

    # keyboardni olib tashlash
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Yakuniy "anketa yaratildi" xabarini yuboramiz
    result = await session.execute(select(Survey).where(Survey.survey_id == survey_id))
    survey = result.scalar_one_or_none()

    bot_username = config.BOT_USERNAME
    deep_link = get_survey_deep_link(bot_username, survey_id)

    await callback.message.answer(
        f"✅ <b>Анкета успешно создана!</b>\n\n"
        f"📋 {survey.name}\n"
        f"🔘 {survey.button_text}\n\n"
        f"🔗 <b>Ссылка:</b>\n"
        f"<code>{deep_link}</code>\n\n"
        f"Теперь вы можете добавить анкету в расписание постов или отправить ссылку вручную.",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer()

# ============== USER: FILL SURVEY ==============



@router.message(FillSurvey.waiting_answer)
async def process_survey_answer(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    response_id = data['response_id']
    question_index = data['question_index']
    survey_id = data['survey_id']
    questions_count = data['questions_count']
    
    questions_result = await session.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .order_by(SurveyQuestion.order_number)
    )
    questions = questions_result.scalars().all()
    
    current_question = questions[question_index]
    
    new_answer = SurveyAnswer(
        response_id=response_id,
        question_id=current_question.question_id,
        answer_text=message.text
    )
    session.add(new_answer)
    await session.commit()
    
    next_index = question_index + 1
    
    if next_index < questions_count:
        next_question = questions[next_index]
        
        await state.update_data(question_index=next_index)
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отменить", callback_data="survey:cancel")
        )
        
        await message.answer(
            f"✅ Ответ сохранён\n\n"
            f"Вопрос {next_index + 1}/{questions_count}\n\n"
            f"❓ {next_question.question_text}\n\n"
            f"💬 Напишите ваш ответ:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    else:
        response_result = await session.execute(
            select(SurveyResponse).where(SurveyResponse.response_id == response_id)
        )
        response = response_result.scalar_one_or_none()
        
        if response:
            response.is_completed = True
            response.completed_at = datetime.now()
            await session.commit()
        
        tg_target = None
        if survey and survey.tgtrack_target:
            tg_target = survey.tgtrack_target.strip() or None

        try:
            await TgTrackService.send_goal(
                user_id=message.from_user.id,
                target=tg_target or "success_survey"   # fallback
            )
        except Exception as e:
            logging.exception("TGTrack send_goal failed: %s", e)
        
        survey_result = await session.execute(
            select(Survey).where(Survey.survey_id == survey_id)
        )
        survey = survey_result.scalar_one_or_none()
        
        user_result = await session.execute(
            select(User).where(User.user_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        completion_msg = survey.completion_message if survey and survey.completion_message else "Спасибо за ваши ответы!"

        # ✅ NEW: completion rasm bo‘lsa — photo + caption
        if survey and survey.completion_photo_file_id:
            await message.answer_photo(
                photo=survey.completion_photo_file_id,
                caption=f"✅ <b>Анкета завершена!</b>\n\n{completion_msg}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"✅ <b>Анкета завершена!</b>\n\n{completion_msg}",
                parse_mode="HTML"
            )
        
        # Adminlarga xabar yuborish
        if survey and user:
            await notify_admins_about_completion(message.bot, user, survey, session)
        
        await state.clear()


@router.callback_query(F.data == "survey:cancel")
async def cancel_survey(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    response_id = data.get('response_id')
    
    if response_id:
        await session.execute(
            delete(SurveyResponse).where(SurveyResponse.response_id == response_id)
        )
        await session.commit()
    
    await callback.message.edit_text(
        "❌ Заполнение анкеты отменено",
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()


# ============== DELETE SURVEY ==============

@router.callback_query(F.data.startswith("survey:delete:"))
async def delete_survey(callback: CallbackQuery, session: AsyncSession):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    survey_id = int(callback.data.split(":")[2])
    
    await session.execute(
        delete(Survey).where(Survey.survey_id == survey_id)
    )
    await session.commit()
    
    await callback.answer("✅ Анкета удалена", show_alert=True)
    await surveys_main_menu(callback, session)