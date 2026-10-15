from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://dean:dean@localhost:5432/dean'
    encryption_key: str
    bootstrap_username: str = 'dean'
    bootstrap_password: str
    bootstrap_email: str = 'dean@example.local'
    ollama_url: str = 'http://127.0.0.1:11434'
    vision_model: str = 'qwen3-vl:2b-instruct'
    answer_model: str = 'qwen3-vl:2b-instruct'
    data_dir: Path = ROOT / 'runtime'
    cookie_secure: bool = False
    allowed_origins: str = 'http://127.0.0.1:8000,http://localhost:8000'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    smtp_starttls: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
