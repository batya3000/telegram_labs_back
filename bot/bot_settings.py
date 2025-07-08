from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_DSN: str = "redis://localhost:6379/0"
    API_BASE: str = "http://127.0.0.1:8000"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"