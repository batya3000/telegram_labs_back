import asyncio
import redis.asyncio as redis
from aiogram import Bot, Dispatcher

from bot_settings import Settings
from application.handlers import start, courses, admin
from application.middlewares.auth import RequireAuth


async def main() -> None:
    cfg = Settings()
    bot = Bot(cfg.BOT_TOKEN)
    dp = Dispatcher()

    redis_client = redis.from_url(cfg.REDIS_DSN, decode_responses=True)

    dp["settings"] = cfg
    dp["redis"] = redis_client

    dp.message.middleware(RequireAuth(redis_client))
    dp.callback_query.middleware(RequireAuth(redis_client))
    dp.include_router(start.router)
    dp.include_router(courses.router)
    dp.include_router(admin.router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())