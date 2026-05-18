"""
config.py — GradeOps Centralised Settings
Loads configuration from environment variables / .env file.

Usage:
    from config import settings

    print(settings.llm_provider)
    print(settings.jwt_secret)
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────
    app_name:    str = "GradeOps"
    app_version: str = "1.0.0"
    debug:       bool = False
    log_level:   str = "INFO"

    # ── Database ──────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://gradeops:gradeops@localhost:5432/gradeops",
        alias="DATABASE_URL",
    )

    # ── Security / JWT ────────────────────────
    jwt_secret:       str = Field(
        default="CHANGE_ME_IN_PRODUCTION_USE_LONG_RANDOM_SECRET")
    jwt_algorithm:    str = "HS256"
    jwt_expire_hours: int = 24

    # ── OCR ───────────────────────────────────
    ocr_backend:      str = "gemini"     # gemini | qwen_vl | nougat | mock
    ocr_device:       str = "cpu"        # cpu | cuda (only for qwen_vl/nougat)
    ocr_dpi:          int = 200
    ocr_crop_dir:     str = "./crops"
    gemini_ocr_model: str = "gemini-2.5-flash"   # change to gemini-1.5-pro for higher accuracy

    # ── Grading LLM ───────────────────────────
    llm_provider:  str = "gemini"     # gemini | openai | anthropic | together | mock
    llm_model:     str = "gemini-2.5-flash"
    llm_temp:      float = 0.0

    openai_api_key:    str = ""
    anthropic_api_key: str = ""
    together_api_key:  str = ""
    gemini_api_key:    str = ""       # Set GEMINI_API_KEY in .env

    # ── Plagiarism ────────────────────────────
    plagiarism_threshold:  float = 0.82
    plagiarism_embeddings: bool = False
    embedding_model:       str = "all-MiniLM-L6-v2"

    # ── Storage ───────────────────────────────
    storage_backend:  str = "local"
    storage_data_dir: str = "./gradeops_data"

    # AWS (only needed when storage_backend = "s3")
    aws_region:        str = "us-east-1"
    aws_s3_bucket:     str = ""
    aws_dynamo_table:  str = ""

    # ── CORS ──────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:3000", "http://localhost:5173"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance — call this everywhere instead of Settings()."""
    return Settings()


# Module-level alias for convenience
settings = get_settings()
