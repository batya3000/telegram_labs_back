from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp
import redis.asyncio as redis

from ..states import Auth, CourseSelection
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from bot_settings import Settings

router = Router()


# @router.message(F.text == "/start")
# async def greet(message: types.Message):
#     await message.answer("Привет, я бот")


@router.message(Command("start"))
async def ask_code(msg: types.Message, state: FSMContext):
    await msg.answer("Введи одноразовый код, который дал преподаватель")
    await state.set_state(Auth.waiting_code)


@router.message(Auth.waiting_code)
async def check_code(
    msg: types.Message,
    state: FSMContext,
    settings: Settings,
    redis: redis.Redis,
):
    
    code = msg.text.strip()

    async with aiohttp.ClientSession() as s:
        r = await s.post(
            f"{settings.API_BASE}/auth/code/login",
            json={"chat_id": msg.from_user.id, "code": code},
        )

        if r.status != 200:
            await msg.answer("Код неверный или уже использован, попробуй ещё раз")
            return

        data = await r.json()

    await redis.sadd("students", msg.from_user.id)
    await state.clear()

    name = data.get("student_name") or "студент"
    await msg.answer(f"✓ Добро пожаловать, {name}!")
    await msg.answer(
        "Теперь доступны команды:\n"
        "/courses — выбор курса и лабораторных работ"
    )

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

    await state.update_data(course_id=course_id, course_name=course['name'])
    
    text = f"Курс: {course['name']}\n\nДоступные группы:\n"
    for group in groups:
        text += f"/{group}\n"
    
    await msg.answer(text)
    await msg.answer("Выберите группу, отправив её номер (например: /К4304)")
    await state.set_state(CourseSelection.waiting_group)

@router.message(CourseSelection.waiting_group)
async def select_group(msg: types.Message, state: FSMContext, settings: Settings):
    if not msg.text.startswith("/"):
        await msg.answer("Пожалуйста, выберите группу, отправив её номер (например: /К4304)")
        return
    
    group_id = msg.text[1:]
    data = await state.get_data()
    course_id = data['course_id']
    course_name = data['course_name']
    
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/courses/{course_id}/groups/{group_id}/labs")
        if r.status != 200:
            await msg.answer("Группа не найдена или не удалось получить список лабораторных")
            return
        labs = await r.json()

    if not labs:
        await msg.answer("Для этой группы пока нет лабораторных работ")
        return

    await state.update_data(group_id=group_id)
    
    text = f"Курс: {course_name}\nГруппа: {group_id}\n\nДоступные лабораторные:\n"
    for lab in labs:
        text += f"• {lab}\n"
    
    await msg.answer(text)
    await state.clear()