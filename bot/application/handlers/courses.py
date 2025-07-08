from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp

from ..states import CourseSelection, LabSubmission
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from bot_settings import Settings

router = Router()

@router.message(Command("courses"))
async def list_courses(msg: types.Message, state: FSMContext, settings: Settings):
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/by-chat/{msg.from_user.id}")
        if r.status != 200:
            await msg.answer("Не удалось получить список доступных курсов")
            return
        courses = await r.json()

    if not courses:
        await msg.answer("Пока нет доступных курсов")
        return

    text = "Доступные курсы:\n"
    for course in courses:
        text += f"/{course['id']} — {course['name']} ({course['semester']})\n"
    
    await msg.answer(text)
    await msg.answer("Выберите курс, отправив его номер (например: /1)")
    await state.set_state(CourseSelection.waiting_course)

@router.message(Command("labs"))
async def legacy_labs_command(msg: types.Message):
    await msg.answer("Команда /labs больше не поддерживается.\nИспользуйте /courses для выбора курса и лабораторных работ.")

@router.message(CourseSelection.waiting_course)
async def select_course(msg: types.Message, state: FSMContext, settings: Settings):
    if not msg.text.startswith("/"):
        await msg.answer("Пожалуйста, выберите курс, отправив его номер (например: /1)")
        return
    
    course_id = msg.text[1:]
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/{course_id}")
        if r.status != 200:
            await msg.answer("Курс не найден. Попробуйте еще раз.")
            return
        course = await r.json()

        r = await s.get(f"{settings.API_BASE}/courses/{course_id}/groups")
        if r.status != 200:
            await msg.answer("Не удалось получить список групп")
            return
        groups = await r.json()

    if not groups:
        await msg.answer("Для этого курса пока нет групп")
        return

    async with aiohttp.ClientSession() as s:
        user_response = await s.get(f"{settings.API_BASE}/courses/by-chat/{msg.from_user.id}")
        if user_response.status != 200:
            await msg.answer("Ошибка получения данных студента")
            return
        
        user_data = await user_response.json()
        if not user_data:
            await msg.answer("Нет доступных курсов")
            return
        
        auth_response = await s.get(f"{settings.API_BASE}/student-group/{msg.from_user.id}")
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
        
        text = f"Курс: {course['name']}\nГруппа: {student_group}\n\nВыберите лабораторную для сдачи:\n"
        for i, lab in enumerate(labs, 1):
            text += f"/{i} — {lab}\n"
        
        await msg.answer(text)
        await msg.answer("Отправьте номер лабораторной (например: /1)")
        await state.set_state(LabSubmission.waiting_lab_selection)


@router.message(LabSubmission.waiting_lab_selection)
async def submit_lab(msg: types.Message, state: FSMContext, settings: Settings):
    if not msg.text.startswith("/"):
        await msg.answer("Пожалуйста, выберите лабораторную, отправив её номер (например: /1)")
        return
    
    try:
        lab_index = int(msg.text[1:]) - 1
    except ValueError:
        await msg.answer("Некорректный номер. Попробуйте еще раз.")
        return
    
    data = await state.get_data()
    course_id = data['course_id']
    group_id = data['group_id']
    labs = data['labs']
    
    if lab_index < 0 or lab_index >= len(labs):
        await msg.answer("Номер лабораторной не найден. Попробуйте еще раз.")
        return
    
    selected_lab = labs[lab_index]
    
    await msg.answer(f"🔄 Отправляю лабораторную {selected_lab} на проверку...")
    
    async with aiohttp.ClientSession() as s:
        register_response = await s.post(
            f"{settings.API_BASE}/courses/{course_id}/groups/{group_id}/register-by-chat",
            json={"chat_id": msg.from_user.id}
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
            
            if status == "success":
                await msg.answer(f"✅ {message}")
            elif status == "pending":
                await msg.answer(f"⏳ {message}")
            else:
                await msg.answer(f"ℹ️ {message}")
        else:
            error_data = await grade_response.json() if grade_response.headers.get('content-type', '').startswith('application/json') else {}
            error_message = error_data.get("detail", "Неизвестная ошибка")
            await msg.answer(f"❌ {error_message}")
    
    await state.clear()