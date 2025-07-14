from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp
import aiohttp as aiohttp_module
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from ..states import CourseSelection, LabSubmission
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from bot_settings import Settings

router = Router()

@router.callback_query(F.data == "courses")
async def list_courses_callback(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    await list_courses_impl(callback.message, state, settings, callback.from_user.id, is_callback=True)

@router.message(Command("courses"))
async def list_courses(msg: types.Message, state: FSMContext, settings: Settings):
    await list_courses_impl(msg, state, settings, msg.from_user.id)

async def list_courses_impl(msg: types.Message, state: FSMContext, settings: Settings, user_id: int, is_callback: bool = False):
    if is_callback:
        try:
            await msg.delete()
        except:
            pass
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/by-chat/{user_id}")
        if r.status != 200:
            if is_callback:
                await msg.answer("Не удалось получить список доступных курсов")
            else:
                await msg.answer("Не удалось получить список доступных курсов")
            return
        courses = await r.json()

    if not courses:
        if is_callback:
            await msg.answer("Пока нет доступных курсов")
        else:
            await msg.answer("Пока нет доступных курсов")
        return

    keyboard_buttons = []
    for course in courses:
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{course['name']} ({course['semester']})",
            callback_data=f"course_{course['id']}"
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    if is_callback:
        await msg.answer("Выберите курс:", reply_markup=keyboard)
    else:
        await msg.answer("Выберите курс:", reply_markup=keyboard)
    
    await state.set_state(CourseSelection.waiting_course)

@router.message(Command("labs"))
async def legacy_labs_command(msg: types.Message):
    await msg.answer("Команда /labs больше не поддерживается.\nИспользуйте /courses для выбора курса и лабораторных работ.")

@router.callback_query(F.data.startswith("course_"))
async def select_course_callback(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    course_id = callback.data.replace("course_", "")
    await select_course_impl(callback.message, state, settings, callback.from_user.id, course_id)

@router.message(CourseSelection.waiting_course)
async def select_course(msg: types.Message, state: FSMContext, settings: Settings):
    if not msg.text.startswith("/"):
        await msg.answer("Пожалуйста, выберите курс, нажав на кнопку выше")
        return
    
    course_id = msg.text[1:]
    await select_course_impl(msg, state, settings, msg.from_user.id, course_id)

async def select_course_impl(msg: types.Message, state: FSMContext, settings: Settings, user_id: int, course_id: str):
    try:
        await msg.delete()
    except:
        pass
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/{course_id}")
        if r.status != 200:
            await msg.answer("Курс не найден. Попробуйте еще раз.")
            return
        course = await r.json()

        r = await s.get(f"{settings.API_BASE}/courses/{course_id}/groups")
        if r.status != 200:
            error_text = await r.text()
            await msg.answer("Не удалось получить список групп. Возможно, проблема с доступом к Google Sheets.")
            return
        groups = await r.json()

    if not groups:
        await msg.answer("Для этого курса пока нет групп")
        return

    async with aiohttp.ClientSession() as s:
        user_response = await s.get(f"{settings.API_BASE}/courses/by-chat/{user_id}")
        if user_response.status != 200:
            await msg.answer("Ошибка получения данных студента")
            return
        
        user_data = await user_response.json()
        if not user_data:
            await msg.answer("Нет доступных курсов")
            return
        
        auth_response = await s.get(f"{settings.API_BASE}/student-group/{user_id}")
        if auth_response.status != 200:
            await msg.answer("Не удалось определить группу студента")
            return
        
        auth_data = await auth_response.json()
        student_group = auth_data.get("group")
        
        if not student_group or str(student_group) not in groups:
            await msg.answer(f"Ваша группа ({student_group}) не найдена в курсе {course['name']}")
            return
        
        labs_response = await s.get(f"{settings.API_BASE}/courses/{course_id}/groups/{student_group}/labs")
        if labs_response.status != 200:
            await msg.answer("Не удалось получить список лабораторных")
            return
        
        labs = await labs_response.json()
        
        if not labs:
            await msg.answer(f"Для вашей группы ({student_group}) пока нет лабораторных работ")
            return

        await state.update_data(course_id=course_id, course_name=course['name'], group_id=str(student_group), labs=labs)
        
        keyboard_buttons = []
        for i, lab in enumerate(labs):
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"{lab}",
                callback_data=f"lab_{i}"
            )])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад к курсам", callback_data="back_to_courses")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        text = f"Курс: {course['name']}\nГруппа: {student_group}\n\nВыберите лабораторную для сдачи:"
        await msg.answer(text, reply_markup=keyboard)
        await state.set_state(LabSubmission.waiting_lab_selection)


@router.callback_query(F.data.startswith("lab_"))
async def submit_lab_callback(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    try:
        lab_index = int(callback.data.replace("lab_", ""))
    except ValueError:
        await callback.message.answer("Некорректный номер лабораторной")
        return
    
    await submit_lab_impl(callback.message, state, settings, callback.from_user.id, lab_index)

@router.message(LabSubmission.waiting_lab_selection)
async def submit_lab(msg: types.Message, state: FSMContext, settings: Settings):
    if not msg.text.startswith("/"):
        await msg.answer("Пожалуйста, выберите лабораторную, нажав на кнопку выше")
        return
    
    try:
        lab_index = int(msg.text[1:]) - 1
    except ValueError:
        await msg.answer("Некорректный номер. Попробуйте еще раз.")
        return
    
    await submit_lab_impl(msg, state, settings, msg.from_user.id, lab_index)

async def submit_lab_impl(msg: types.Message, state: FSMContext, settings: Settings, user_id: int, lab_index: int):
    try:
        await msg.delete()
    except:
        pass
    
    data = await state.get_data()
    course_id = data['course_id']
    group_id = data['group_id']
    labs = data['labs']
    
    if lab_index < 0 or lab_index >= len(labs):
        await msg.answer("Номер лабораторной не найден. Попробуйте еще раз.")
        return
    
    selected_lab = labs[lab_index]
    
    progress_msg = await msg.answer(f"🔄 Отправляю лабораторную {selected_lab} на проверку...")
    
    async with aiohttp.ClientSession() as s:
        register_response = await s.post(
            f"{settings.API_BASE}/courses/{course_id}/groups/{group_id}/register-by-chat",
            json={"chat_id": user_id}
        )
        
        if register_response.status != 200:
            await msg.answer("❌ Ошибка при регистрации. Попробуйте позже.")
            await state.clear()
            return
        
        register_data = await register_response.json()
        github_username = register_data.get("github")
        
        if not github_username:
            await msg.answer("❌ GitHub аккаунт не найден. Обратитесь к преподавателю.")
            await state.clear()
            return
        
        grade_response = await s.post(
            f"{settings.API_BASE}/courses/{course_id}/groups/{group_id}/labs/{selected_lab}/grade",
            json={"github": github_username}
        )
        
        if grade_response.status == 200:
            grade_data = await grade_response.json()
            status = grade_data.get("status", "unknown")
            message = grade_data.get("message", "Проверка завершена")
            passed = grade_data.get("passed", "")
            checks = grade_data.get("checks", [])
            
            response_text = f"📊 **Результат проверки {selected_lab}**\n\n"
            
            if status == "updated":
                response_text += f"{message}\n"
                if passed:
                    response_text += f"{passed}\n\n"
                
                if checks:
                    response_text += "**Детали:**\n"
                    for check in checks:
                        response_text += f"{check}\n"
                else:
                    response_text += "ℹ️ Детальная информация о тестах недоступна"
            elif status == "pending":
                response_text += f"⏳ {message}"
                if checks:
                    response_text += "\n\n**Текущий статус тестов:**\n"
                    for check in checks:
                        response_text += f"{check}\n"
            else:
                response_text += f"ℹ️ {message}"
            
            try:
                await progress_msg.delete()
            except:
                pass
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 К курсам", callback_data="back_to_courses")]
            ])
            
            await msg.answer(response_text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            try:
                await progress_msg.delete()
            except:
                pass
            
            error_data = await grade_response.json() if grade_response.headers.get('content-type', '').startswith('application/json') else {}
            error_message = error_data.get("detail", "Неизвестная ошибка")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 К курсам", callback_data="back_to_courses")]
            ])
            
            await msg.answer(f"❌ {error_message}", reply_markup=keyboard)
    
    await state.clear()

@router.callback_query(F.data == "back_to_courses")
async def back_to_courses_callback(callback: CallbackQuery, state: FSMContext, settings: Settings):
    await callback.answer()
    await state.clear()

    try:
        await callback.message.delete()
    except:
        pass
    await list_courses_impl(callback.message, state, settings, callback.from_user.id, is_callback=True)

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    
    try:
        await callback.message.delete()
    except:
        pass
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Выбрать курс", callback_data="courses")]
    ])
    
    await callback.message.answer("Выберите действие:", reply_markup=keyboard)