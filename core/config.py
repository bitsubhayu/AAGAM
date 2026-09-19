from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and environment configuration."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Supabase
    SUPABASE_URL: Optional[str] = Field(default=None)
    SUPABASE_ANON_KEY: Optional[str] = Field(default=None)
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(default=None)
    DATABASE_URL: Optional[str] = Field(default=None)

    # Groq LLM
    GROQ_API_KEY: Optional[str] = Field(default=None)
    GROQ_MODEL: str = Field(default="openai/gpt-oss-120b")
    GROQ_FALLBACK_MODEL: str = Field(default="openai/gpt-oss-20b")

    # Open-Meteo
    OPENMETEO_BASE_FORECAST: str = Field(default="https://api.open-meteo.com/v1/forecast")
    OPENMETEO_BASE_HISTORICAL: str = Field(default="https://archive-api.open-meteo.com/v1/archive")

    # Timezone & Server
    APP_TZ_DISPLAY: str = Field(default="Asia/Kolkata")
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")


settings = Settings()

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_yaml(filename: str) -> Dict[str, Any]:
    file_path = CONFIG_DIR / filename
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_locations() -> List[Dict[str, Any]]:
    data = load_yaml("locations.yaml")
    return data.get("locations", [])


def get_regions() -> Dict[str, Any]:
    return load_yaml("regions.yaml")


def get_thresholds() -> Dict[str, Any]:
    return load_yaml("thresholds.yaml")


def get_models() -> Dict[str, Any]:
    return load_yaml("models.yaml")
