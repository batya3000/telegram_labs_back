from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_DSN: str = "redis://redis:6379/0"
    API_BASE: str = "http://backend:8000"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"