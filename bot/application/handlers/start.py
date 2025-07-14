from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp
import aiohttp as aiohttp_module
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import redis.asyncio as redis

from ..states import Auth
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from bot_settings import Settings

router = Router()

@router.message(Command("start"))
async def ask_code(msg: types.Message, state: FSMContext, settings: Settings):
    timeout = aiohttp_module.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        try:
            async with s.get(f"{settings.API_BASE}/student-group/{msg.from_user.id}") as r:
                if r.status == 200:
                    student_data = await r.json()
                    
                    async with s.get(f"{settings.API_BASE}/courses/by-chat/{msg.from_user.id}") as user_r:
                        if user_r.status == 200:
                            await check_github_and_proceed(msg, state, settings)
                            return
        except:
            pass
    
    await msg.answer("Введи одноразовый код, который дал преподаватель")
    await state.set_state(Auth.waiting_code)

async def check_github_and_proceed(msg: types.Message, state: FSMContext, settings: Settings):
    timeout = aiohttp_module.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(f"{settings.API_BASE}/student-group/{msg.from_user.id}") as student_r:
            if student_r.status != 200:
                await msg.answer("Введи одноразовый код, который дал преподаватель")
                await state.set_state(Auth.waiting_code)
                return
                
            student_data = await student_r.json()
            name = student_data.get("student_name", "студент")
            
            await state.clear()
            await msg.answer(f"✓ Добро пожаловать, {name}!")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 Выбрать курс", callback_data="courses")]
            ])
            
            await msg.answer("Выберите действие:", reply_markup=keyboard)

@router.message(Auth.waiting_code)
async def check_code(
    msg: types.Message,
    state: FSMContext,
    settings: Settings,
    redis: redis.Redis,
):
    code = msg.text.strip()

    timeout = aiohttp_module.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(
            f"{settings.API_BASE}/auth/code/login",
            json={"chat_id": msg.from_user.id, "code": code},
        ) as r:
            if r.status != 200:
                await msg.answer("Код неверный или уже использован, попробуй ещё раз")
                return

            data = await r.json()

    await redis.sadd("students", msg.from_user.id)
    
    name = data.get("student_name") or "студент"
    
    if data.get("is_new_chat_id", False):
        await msg.answer(f"✓ Добро пожаловать, {name}!")
        await msg.answer("Для продолжения введите ваш GitHub username:")
        await state.set_state(Auth.waiting_github)
    else:
        await state.clear()
        await msg.answer(f"✓ Добро пожаловать, {name}!")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 Выбрать курс", callback_data="courses")]
        ])
        
        await msg.answer(
            "Выберите действие:",
            reply_markup=keyboard
        )

@router.message(Auth.waiting_github)
async def check_github(
    msg: types.Message,
    state: FSMContext,
    settings: Settings,
):
    github_username = msg.text.strip()
    
    if not github_username or len(github_username) < 1:
        await msg.answer("❌ Введите корректный GitHub username")
        return
    
    await msg.answer("🔄 Проверяю GitHub аккаунт...")
    
    timeout = aiohttp_module.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(
            f"{settings.API_BASE}/auth/github/update",
            json={"chat_id": msg.from_user.id, "github": github_username},
        ) as r:
            if r.status != 200:
                error_data = await r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
                error_message = error_data.get("detail", "Ошибка сохранения GitHub аккаунта")
                await msg.answer(f"❌ {error_message}")
                await msg.answer("Попробуйте ввести GitHub username еще раз:")
                return
    
    await state.clear()
    await msg.answer(f"✅ GitHub аккаунт @{github_username} успешно сохранен!")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Выбрать курс", callback_data="courses")]
    ])
    
    await msg.answer(
        "Выберите действие:",
        reply_markup=keyboard
    )