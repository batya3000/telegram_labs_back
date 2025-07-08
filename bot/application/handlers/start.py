from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.client.session import aiohttp
import redis.asyncio as redis

from ..states import Auth
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
    redis_client: redis.Redis,
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

    await redis_client.sadd("students", msg.from_user.id)
    await state.clear()

    name = data.get("student_name") or "студент"
    await msg.answer(f"✓ Добро пожаловать, {name}!")
    await msg.answer(
        "Теперь доступны команды:\n"
        "/labs — список работ"
    )

@router.message(Command("labs"))
async def list_labs(msg: types.Message, settings: Settings, redis_client: redis.Redis):
    # авторизация уже гарантирована middleware
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"{settings.API_BASE}/labs/by-chat/{msg.from_user.id}")
        if r.status != 200:
            await msg.answer("Не удалось получить список лабораторных")
            return
        data = await r.json()

    if not data["labs"]:
        await msg.answer("Для твоей группы пока нет лабораторных")
        return

    text = "\n".join(
        f"• {lab['key']} — {lab['title']}"
        + (f"  (до {lab['deadline']})" if lab.get('deadline') else "")
        for lab in data["labs"]
    )
    await msg.answer(f"Доступные лабораторные:\n{text}")