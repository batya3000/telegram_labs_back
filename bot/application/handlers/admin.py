from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp
import aiohttp as aiohttp_module
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from ..states import AdminAuth, AdminPanel
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from bot_settings import Settings

router = Router()

@router.message(Command("admin"))
async def admin_start(msg: types.Message, state: FSMContext, settings: Settings):
    async with aiohttp.ClientSession() as s:
        try:
            r = await s.get(f"{settings.API_BASE}/admin/check-chat/{msg.from_user.id}")
            if r.status == 200:
                await show_admin_panel(msg, state, settings)
                return
        except:
            pass
    await msg.answer("Введите код доступа администратора:")
    await state.set_state(AdminAuth.waiting_admin_code)

@router.message(AdminAuth.waiting_admin_code)
async def check_admin_code(
    msg: types.Message,
    state: FSMContext,
    settings: Settings,
):
    code = msg.text.strip()

    async with aiohttp.ClientSession() as s:
        r = await s.post(
            f"{settings.API_BASE}/auth/admin/code/login",
            json={"chat_id": msg.from_user.id, "code": code},
        )

        if r.status != 200:
            await msg.answer("Код неверный или уже использован, попробуйте ещё раз")
            return

        data = await r.json()

    name = data.get("admin_name") or "администратор"
    await msg.answer(f"✓ Добро пожаловать, {name}!")
    
    await show_admin_panel(msg, state, settings)

async def show_admin_panel(msg: types.Message, state: FSMContext, settings: Settings):
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Управление курсами", callback_data="admin_courses")],
        [InlineKeyboardButton(text="🚪 Выход", callback_data="admin_logout")]
    ])
    
    await msg.answer("🔧 Панель администратора:", reply_markup=keyboard)
    await state.set_state(AdminPanel.viewing_courses)

@router.callback_query(F.data == "admin_courses")
async def list_admin_courses(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    
    try:
        await callback.message.delete()
    except:
        pass
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/admin/courses?chat_id={callback.from_user.id}")
        if r.status != 200:
            await callback.message.answer("❌ Не удалось получить список курсов")
            return
        
        courses = await r.json()

    if not courses:
        await callback.message.answer("📭 Нет доступных курсов")
        return

    keyboard_buttons = []
    for course in courses:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{course['name']} ({course['semester']})",
            callback_data=f"admin_course_{course['id']}"
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back_to_panel")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.answer("📚 Выберите курс для управления:", reply_markup=keyboard)

async def show_course_menu(callback: CallbackQuery, state: FSMContext, settings: Settings, course_id: str, delete_previous: bool = True):
    if delete_previous:
        try:
            await callback.message.delete()
        except:
            pass
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/{course_id}")
        if r.status != 200:
            await callback.message.answer("❌ Курс не найден")
            return
        course = await r.json()
    
    await state.update_data(selected_course_id=course_id, selected_course_name=course['name'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Посмотреть YAML", callback_data=f"admin_view_yaml_{course_id}")],
        [InlineKeyboardButton(text="📊 Результаты групп", callback_data=f"admin_view_groups_{course_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить курс", callback_data=f"admin_delete_course_{course_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к курсам", callback_data="admin_courses")]
    ])
    
    await callback.message.answer(
        f"🎓 Курс: {course['name']}\n📅 Семестр: {course['semester']}\n\nВыберите действие:",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("admin_course_"))
async def admin_course_actions(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_course_", "")
    await show_course_menu(callback, state, settings, course_id)

@router.callback_query(F.data.startswith("admin_view_yaml_"))
async def admin_view_yaml(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_view_yaml_", "")
    
    try:
        await callback.message.delete()
    except:
        pass
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/admin/courses/{course_id}/yaml?chat_id={callback.from_user.id}")
        if r.status != 200:
            await callback.message.answer("❌ Не удалось получить YAML файл")
            return
        
        yaml_data = await r.json()
        yaml_content = yaml_data.get("content", "")
    
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к курсу", callback_data=f"admin_back_to_course_{course_id}")]
    ])
    
    max_length = 4000
    yaml_formatted = f"```yaml\n{yaml_content}\n```"
    
    sent_messages = []
    
    if len(yaml_formatted) <= max_length:
        msg = await callback.message.answer(
            f"📄 YAML конфигурация курса:\n\n{yaml_formatted}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        sent_messages.append(msg)
    else:
        header_msg = await callback.message.answer("📄 YAML конфигурация курса:")
        sent_messages.append(header_msg)
        
        lines = yaml_content.split('\n')
        current_chunk = ""
        chunk_number = 1
        
        for line in lines:
            test_chunk = current_chunk + line + '\n'
            formatted_test = f"```yaml\n{test_chunk}```"
            
            if len(formatted_test) > max_length and current_chunk:
                chunk_msg = await callback.message.answer(
                    f"```yaml\n{current_chunk}```",
                    parse_mode="Markdown"
                )
                sent_messages.append(chunk_msg)
                current_chunk = line + '\n'
                chunk_number += 1
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            last_msg = await callback.message.answer(
                f"```yaml\n{current_chunk}```",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            sent_messages.append(last_msg)
    
    message_ids = [msg.message_id for msg in sent_messages]
    await state.update_data(yaml_message_ids=message_ids)

@router.callback_query(F.data.startswith("admin_view_groups_"))
async def admin_view_groups(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_view_groups_", "")
    
    try:
        await callback.message.delete()
    except:
        pass
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/admin/courses/{course_id}/groups?chat_id={callback.from_user.id}")
        if r.status != 200:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к курсу", callback_data=f"admin_back_to_course_{course_id}")]
            ])
            await callback.message.answer("❌ Не удалось получить список групп", reply_markup=keyboard)
            return
        
        groups = await r.json()

    if not groups:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к курсу", callback_data=f"admin_back_to_course_{course_id}")]
        ])
        await callback.message.answer("📭 Нет доступных групп для этого курса", reply_markup=keyboard)
        return

    keyboard_buttons = []
    for group in groups:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"Группа {group['group_id']}",
            callback_data=f"admin_view_results_{course_id}_{group['group_id']}"
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад к курсу", callback_data=f"admin_back_to_course_{course_id}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.answer("📊 Выберите группу для просмотра результатов:", reply_markup=keyboard)
    await state.set_state(AdminPanel.viewing_groups)

@router.callback_query(F.data.startswith("admin_view_results_"))
async def admin_view_results(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    parts = callback.data.replace("admin_view_results_", "").split("_", 1)
    course_id = parts[0]
    group_id = parts[1]
    
    try:
        await callback.message.delete()
    except:
        pass
    
    progress_msg = await callback.message.answer("🔄 Загружаю результаты...")
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/admin/courses/{course_id}/groups/{group_id}/results?chat_id={callback.from_user.id}")
        
        try:
            await progress_msg.delete()
        except:
            pass
        
        if r.status != 200:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ К группам", callback_data=f"admin_view_groups_{course_id}")]
            ])
            await callback.message.answer("❌ Не удалось получить результаты группы", reply_markup=keyboard)
            return
        
        data = await r.json()
        
    headers = data.get("headers", [])
    rows = data.get("rows", [])
    course_name = data.get("course_name", "Курс")
    
    if not headers or not rows:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К группам", callback_data=f"admin_view_groups_{course_id}")]
        ])
        await callback.message.answer("📭 Нет данных для отображения", reply_markup=keyboard)
        return
    
    results_text = f"📊 Результаты группы {group_id}\n🎓 Курс: {course_name}\n\n"
    
    max_length = 4000
    sent_messages = []
    
    current_chunk = results_text
    student_count = 0
    
    for row in rows:
        if not row or len(row) < 2:
            continue
        
        # Проверяем, есть ли хотя бы одно непустое значение (кроме первых 3 колонок для ID, имени, GitHub)
        has_data = False
        if len(row) >= 2:
            # Проверяем есть ли имя студента (колонка 2)
            if len(row) > 1 and row[1] and str(row[1]).strip() and str(row[1]).strip() != "-":
                has_data = True
            # Проверяем есть ли хотя бы один результат лабораторной
            elif len(row) > 3:
                for cell in row[3:]:
                    if cell and str(cell).strip() and str(cell).strip() not in ["-", ""]:
                        has_data = True
                        break
        
        if not has_data:
            continue
            
        student_count += 1
        if student_count > 15:
            break
            
        student_info = f"👤 **Студент #{student_count}**\n"
        
        for i, header in enumerate(headers):
            if i >= len(row):
                break
                
            value = str(row[i]).strip() if row[i] else "-"
            if len(value) > 20:
                value = value[:20] + "..."
                
            student_info += f"• {header}: `{value}`\n"
        
        student_info += "\n"
        
        test_chunk = current_chunk + student_info
        
        if len(test_chunk) > max_length:
            if current_chunk != results_text:
                msg = await callback.message.answer(current_chunk, parse_mode="Markdown")
                sent_messages.append(msg)
                current_chunk = results_text + student_info
            else:
                current_chunk += student_info
        else:
            current_chunk = test_chunk
    
    if len(rows) > 15:
        current_chunk += f"⚠️ Показано {min(len(rows), 15)} из {len(rows)} студентов"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К группам", callback_data=f"admin_view_groups_{course_id}")]
    ])
    
    if current_chunk.strip():
        msg = await callback.message.answer(current_chunk, parse_mode="Markdown", reply_markup=keyboard)
        sent_messages.append(msg)
    
    message_ids = [msg.message_id for msg in sent_messages]
    await state.update_data(results_message_ids=message_ids)
    await state.set_state(AdminPanel.viewing_results)

@router.callback_query(F.data.startswith("admin_delete_course_"))
async def admin_confirm_delete(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_delete_course_", "")
    
    data = await state.get_data()
    course_name = data.get("selected_course_name", "курс")
    
    try:
        await callback.message.delete()
    except:
        pass
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete_{course_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_course_{course_id}")]
    ])
    
    await callback.message.answer(
        f"⚠️ Вы действительно хотите удалить курс '{course_name}'?\n\n"
        "Это действие нельзя отменить!",
        reply_markup=keyboard
    )
    await state.set_state(AdminPanel.confirming_delete)

@router.callback_query(F.data.startswith("admin_confirm_delete_"))
async def admin_delete_course(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_confirm_delete_", "")
    
    data = await state.get_data()
    course_name = data.get("selected_course_name", "курс")
    
    try:
        await callback.message.delete()
    except:
        pass
    
    progress_msg = await callback.message.answer("🔄 Удаляю курс...")
    
    async with aiohttp.ClientSession() as s:
        r = await s.delete(f"{settings.API_BASE}/admin/courses/{course_id}?chat_id={callback.from_user.id}")
        
        try:
            await progress_msg.delete()
        except:
            pass
        
        if r.status == 200:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 К списку курсов", callback_data="admin_courses")]
            ])
            
            await callback.message.answer(
                f"✅ Курс '{course_name}' успешно удален!",
                reply_markup=keyboard
            )
        else:
            error_data = await r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            error_message = error_data.get("detail", "Неизвестная ошибка")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к курсу", callback_data=f"admin_back_to_course_{course_id}")]
            ])
            
            await callback.message.answer(
                f"❌ Ошибка при удалении курса: {error_message}",
                reply_markup=keyboard
            )
    
    await state.clear()
    await state.set_state(AdminPanel.viewing_courses)

@router.callback_query(F.data.startswith("admin_back_to_course_"))
async def admin_back_to_course(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("admin_back_to_course_", "")
    
    data = await state.get_data()
    yaml_message_ids = data.get("yaml_message_ids", [])
    results_message_ids = data.get("results_message_ids", [])
    
    for message_id in yaml_message_ids + results_message_ids:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=message_id)
        except:
            pass
    
    await state.update_data(yaml_message_ids=[], results_message_ids=[])
    
    await show_course_menu(callback, state, settings, course_id, delete_previous=False)

@router.callback_query(F.data == "admin_back_to_panel")
async def admin_back_to_panel(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await show_admin_panel(callback.message, state, settings)

@router.callback_query(F.data == "admin_logout")
async def admin_logout(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    
    try:
        await callback.message.delete()
    except:
        pass
    
    async with aiohttp.ClientSession() as s:
        try:
            await s.post(f"{settings.API_BASE}/auth/admin/logout", json={"chat_id": callback.from_user.id})
        except:
            pass
    
    await state.clear()
    await callback.message.answer("👋 Выход из панели администратора выполнен")