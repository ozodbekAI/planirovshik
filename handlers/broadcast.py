# handlers/broadcast.py
import asyncio
import time
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.base import User
from keyboards.admin_kb import (
    get_broadcast_type_keyboard,
    get_broadcast_target_keyboard,
    get_admin_main_keyboard
)
from utils.texts import Texts
from utils.helpers import is_admin, format_time_delta

router = Router(name="broadcast_router")

# FSM States
class Broadcast(StatesGroup):
    waiting_content = State()
    waiting_target = State()
    waiting_day = State()
    confirming = State()
    sending = State()

# ============== BROADCAST ==============

@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Rассылка boshlash"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    await callback.message.edit_text(
        Texts.BROADCAST_START,
        reply_markup=get_broadcast_type_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("broadcast:type:"))
async def broadcast_type_selected(callback: CallbackQuery, state: FSMContext):
    """Rассылка turini tanlash"""
    broadcast_type = callback.data.split(":")[2]
    
    await state.update_data(broadcast_type=broadcast_type)
    await state.set_state(Broadcast.waiting_content)
    
    type_instructions = {
        'text': "📝 Отправьте текст для рассылки.\n\nВы можете использовать форматирование HTML.",
        'photo': "🖼 Отправьте изображение для рассылки.\n\nМожно добавить подпись.",
        'video': "🎥 Отправьте видео для рассылки.\n\nМожно добавить подпись.",
        'document': "📄 Отправьте документ для рассылки.\n\nМожно добавить подпись."
    }
    
    instruction = type_instructions.get(broadcast_type, "Отправьте контент:")
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
    ])
    
    await callback.message.edit_text(
        instruction,
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(Broadcast.waiting_content)
async def broadcast_content_received(message: Message, state: FSMContext, session: AsyncSession):
    """Rассылка kontentini qabul qilish"""
    data = await state.get_data()
    broadcast_type = data['broadcast_type']
    
    content = None
    file_id = None
    caption = None
    
    if broadcast_type == 'text':
        if not message.text:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
            ])
            await message.answer(
                "❌ Отправьте текст сообщения.",
                reply_markup=back_kb
            )
            return
        content = message.text
    
    elif broadcast_type == 'photo':
        if not message.photo:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
            ])
            await message.answer(
                "❌ Отправьте изображение.",
                reply_markup=back_kb
            )
            return
        file_id = message.photo[-1].file_id
        caption = message.caption
    
    elif broadcast_type == 'video':
        if not message.video:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
            ])
            await message.answer(
                "❌ Отправьте видео.",
                reply_markup=back_kb
            )
            return
        file_id = message.video.file_id
        caption = message.caption
    
    elif broadcast_type == 'document':
        if not message.document:
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
            ])
            await message.answer(
                "❌ Отправьте документ.",
                reply_markup=back_kb
            )
            return
        file_id = message.document.file_id
        caption = message.caption
    
    await state.update_data(
        content=content,
        file_id=file_id,
        caption=caption
    )
    
    # Statistika olish
    total_result = await session.execute(
        select(func.count(User.user_id))
    )
    total_users = total_result.scalar()
    
    active_result = await session.execute(
        select(func.count(User.user_id)).where(
            User.is_active == True,
            User.is_blocked == False
        )
    )
    active_users = active_result.scalar()
    
    # Preview va target tanlash
    await state.set_state(Broadcast.waiting_target)
    
    # Preview ko'rsatish
    await message.answer("👁 <b>ПРЕДПРОСМОТР РАССЫЛКИ</b>", parse_mode="HTML")
    
    try:
        if broadcast_type == 'text':
            await message.answer(content, parse_mode="HTML")
        elif broadcast_type == 'photo':
            await message.answer_photo(photo=file_id, caption=caption, parse_mode="HTML")
        elif broadcast_type == 'video':
            await message.answer_video(video=file_id, caption=caption, parse_mode="HTML")
        elif broadcast_type == 'document':
            await message.answer_document(document=file_id, caption=caption, parse_mode="HTML")
    except Exception as e:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
        ])
        await message.answer(
            f"❌ Ошибка предпросмотра: {str(e)}",
            reply_markup=back_kb
        )
        await state.clear()
        return
    
    await message.answer(
        Texts.BROADCAST_PREVIEW,
        reply_markup=get_broadcast_target_keyboard(total_users, active_users),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("broadcast:target:"))
async def broadcast_target_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Rассылка maqsadini tanlash"""
    target = callback.data.split(":")[2]
    
    await state.update_data(target=target)
    
    if target == "day":
        # Kun bo'yicha tanlash
        await state.set_state(Broadcast.waiting_day)
        
        # Har kundagi userlar sonini ko'rsatish
        funnel_result = await session.execute(
            select(
                User.current_day,
                func.count(User.user_id).label('count')
            ).where(
                User.is_subscribed == True,
                User.is_blocked == False
            ).group_by(User.current_day).order_by(User.current_day)
        )
        days_data = funnel_result.all()
        
        days_text = "🔥 <b>Выберите день прогрева:</b>\n\n"
        for day, count in days_data:
            days_text += f"День {day}: {count} пользователей\n"
        
        days_text += "\nВведите номер дня (или несколько через запятую):\n"
        days_text += "Например: <code>1,2,3</code>"
        
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
        ])
        
        await callback.message.edit_text(
            days_text,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        await callback.answer()
    else:
        # Tasdiqlovchi xabar
        await broadcast_confirm(callback, state, session)

@router.message(Broadcast.waiting_day)
async def broadcast_day_received(message: Message, state: FSMContext, session: AsyncSession):
    """Kunlarni qabul qilish"""
    try:
        days = [int(d.strip()) for d in message.text.split(",")]
        await state.update_data(days=days)
        
        # Userlar sonini hisoblash
        count_result = await session.execute(
            select(func.count(User.user_id)).where(
                User.current_day.in_(days),
                User.is_subscribed == True,
                User.is_blocked == False
            )
        )
        user_count = count_result.scalar()
        
        await state.update_data(user_count=user_count)
        
        # Tasdiqlovchi xabar
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ДА, начать рассылку", callback_data="broadcast:confirm")],
            [InlineKeyboardButton(text="❌ НЕТ, отменить", callback_data="admin:main")]
        ])
        
        data = await state.get_data()
        
        await message.answer(
            Texts.BROADCAST_CONFIRM.format(
                count=user_count,
                type=data['broadcast_type']
            ),
            reply_markup=confirm_kb,
            parse_mode="HTML"
        )
        await state.set_state(Broadcast.confirming)
        
    except ValueError:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:main")]
        ])
        await message.answer(
            "❌ Неверный формат. Введите номера дней через запятую.\nНапример: 1,2,3",
            reply_markup=back_kb
        )

async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Rассылkани tasdiqlash"""
    data = await state.get_data()
    target = data['target']
    
    # Userlar sonini hisoblash
    if target == "all":
        count_result = await session.execute(
            select(func.count(User.user_id))
        )
    elif target == "active":
        count_result = await session.execute(
            select(func.count(User.user_id)).where(
                User.is_active == True,
                User.is_blocked == False
            )
        )
    else:
        count_result = await session.execute(
            select(func.count(User.user_id)).where(
                User.current_day.in_(data.get('days', [])),
                User.is_subscribed == True,
                User.is_blocked == False
            )
        )
    
    user_count = count_result.scalar()
    await state.update_data(user_count=user_count)
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, начать рассылку", callback_data="broadcast:confirm")],
        [InlineKeyboardButton(text="❌ НЕТ, отменить", callback_data="admin:main")]
    ])
    
    await callback.message.edit_text(
        Texts.BROADCAST_CONFIRM.format(
            count=user_count,
            type=data['broadcast_type']
        ),
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )
    await state.set_state(Broadcast.confirming)
    await callback.answer()

@router.callback_query(F.data == "broadcast:confirm")
async def broadcast_execute(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Rассылkani bajarish"""
    data = await state.get_data()
    target = data['target']
    broadcast_type = data['broadcast_type']
    
    # Userlarni olish
    if target == "all":
        result = await session.execute(
            select(User.user_id)
        )
    elif target == "active":
        result = await session.execute(
            select(User.user_id).where(
                User.is_active == True,
                User.is_blocked == False
            )
        )
    else:
        result = await session.execute(
            select(User.user_id).where(
                User.current_day.in_(data.get('days', [])),
                User.is_subscribed == True,
                User.is_blocked == False
            )
        )
    
    user_ids = [row[0] for row in result.all()]
    total = len(user_ids)
    
    if total == 0:
        await callback.answer("❌ Нет пользователей для рассылки", show_alert=True)
        await state.clear()
        return
    
    # Progress xabari
    progress_msg = await callback.message.edit_text(
        Texts.BROADCAST_PROGRESS.format(
            percent=0,
            sent=0,
            total=total,
            remaining=total,
            failed=0
        ),
        parse_mode="HTML"
    )
    
    # Rассылka
    sent = 0
    failed = 0
    blocked = 0
    errors = 0
    start_time = time.time()
    
    for i, user_id in enumerate(user_ids, 1):
        try:
            if broadcast_type == 'text':
                await callback.bot.send_message(
                    chat_id=user_id,
                    text=data['content'],
                    parse_mode="HTML"
                )
            elif broadcast_type == 'photo':
                await callback.bot.send_photo(
                    chat_id=user_id,
                    photo=data['file_id'],
                    caption=data['caption'],
                    parse_mode="HTML"
                )
            elif broadcast_type == 'video':
                await callback.bot.send_video(
                    chat_id=user_id,
                    video=data['file_id'],
                    caption=data['caption'],
                    parse_mode="HTML"
                )
            elif broadcast_type == 'document':
                await callback.bot.send_document(
                    chat_id=user_id,
                    document=data['file_id'],
                    caption=data['caption'],
                    parse_mode="HTML"
                )
            
            sent += 1
            
        except TelegramForbiddenError:
            failed += 1
            blocked += 1
            # Userni bloklangan deb belgilash
            user = (await session.execute(
                select(User).where(User.user_id == user_id)
            )).scalar_one_or_none()
            if user:
                user.is_blocked = True
                await session.commit()
        
        except Exception as e:
            failed += 1
            errors += 1
        
        # Progress yangilash (har 10 userdan keyin)
        if i % 10 == 0 or i == total:
            percent = round((i / total) * 100)
            try:
                await progress_msg.edit_text(
                    Texts.BROADCAST_PROGRESS.format(
                        percent=percent,
                        sent=sent,
                        total=total,
                        remaining=total - i,
                        failed=failed
                    ),
                    parse_mode="HTML"
                )
            except:
                pass
        
        # Anti-flood: har 30 xabardan keyin 1 soniya kutish
        if i % 30 == 0:
            await asyncio.sleep(1)
    
    # Yakuniy xabar
    duration = format_time_delta(int(time.time() - start_time))
    sent_percent = round((sent / total) * 100, 1)
    failed_percent = round((failed / total) * 100, 1)
    
    await progress_msg.edit_text(
        Texts.BROADCAST_COMPLETE.format(
            sent=sent,
            sent_percent=sent_percent,
            failed=failed,
            failed_percent=failed_percent,
            blocked=blocked,
            errors=errors,
            duration=duration
        ),
        reply_markup=get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()
    await callback.answer("✅ Рассылка завершена!")