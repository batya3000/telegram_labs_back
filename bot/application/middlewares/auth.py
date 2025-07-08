from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiogram.fsm.context import FSMContext
from typing import Callable, Awaitable, Any
import redis.asyncio as redis

from application.states import Auth


class RequireAuth(BaseMiddleware):
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ):
        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            state: FSMContext | None = data.get("state")
            if state:
                current_state = await state.get_state()
                if current_state == Auth.waiting_code.state:
                    return await handler(event, data)

        if await self.redis.sismember("students", event.from_user.id):
            return await handler(event, data)

        return