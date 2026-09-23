import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def sanitize_db_url(url: Optional[str]) -> Optional[str]:
    """Sanitizes DATABASE_URL by percent-encoding credentials with special characters (like '@')."""
    if not url:
        return url
    if url.count("@") > 1 and "://" in url:
        prefix, remainder = url.split("://", 1)
        user_pass, host_db = remainder.rsplit("@", 1)
        if ":" in user_pass:
            user, password = user_pass.split(":", 1)
            encoded_password = urllib.parse.quote(urllib.parse.unquote(password), safe="")
            return f"{prefix}://{user}:{encoded_password}@{host_db}"
    return url


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
    SUPABASE_PUBLISHABLE_KEY: Optional[str] = Field(default=None)
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(default=None)
    SUPABASE_JWT_SECRET: Optional[str] = Field(default=None)
    EXPORT_SIGNING_SECRET: Optional[str] = Field(default=None)
    SUPABASE_JWKS_URL: Optional[str] = Field(default=None)
    DATABASE_URL: Optional[str] = Field(default=None)

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def validate_database_url(cls, v: Optional[str]) -> Optional[str]:
        return sanitize_db_url(v)
    DB_POOL_MIN_SIZE: int = Field(default=1)
    DB_POOL_MAX_SIZE: int = Field(default=10)
    API_V1_STR: str = Field(default="/api/v1")

    # Groq LLM
    GROQ_API_KEY: Optional[str] = Field(default=None)
    GROQ_MODEL: str = Field(default="openai/gpt-oss-120b")
    GROQ_FALLBACK_MODEL: str = Field(default="openai/gpt-oss-20b")

    # Open-Meteo
    OPENMETEO_BASE_FORECAST: str = Field(default="https://api.open-meteo.com/v1/forecast")
    OPENMETEO_BASE_HISTORICAL: str = Field(default="https://archive-api.open-meteo.com/v1/archive")

    # Brevo Email
    BREVO_API_KEY: Optional[str] = Field(default=None)
    BREVO_SENDER_EMAIL: str = Field(default="alerts@aagam.org")
    BREVO_SENDER_NAME: str = Field(default="AAGAM Weather Alerts")

    # Timezone & Server
    APP_TZ_DISPLAY: str = Field(default="Asia/Kolkata")
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")

    # CORS Configuration (environment-driven, comma-separated)
    CORS_ALLOWED_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://localhost:3001,http://127.0.0.1:5173,http://127.0.0.1:3000,http://127.0.0.1:3001"
    )

    # Local evaluation and testing demo authentication
    ENABLE_LOCAL_DEMO_AUTH: bool = Field(default=True)

    @property
    def cors_origins(self) -> List[str]:
        if not self.CORS_ALLOWED_ORIGINS:
            return ["http://localhost:5173", "http://localhost:3000", "http://localhost:3001"]
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def jwks_url(self) -> Optional[str]:
        if self.SUPABASE_JWKS_URL:
            return self.SUPABASE_JWKS_URL
        if self.SUPABASE_URL:
            return f"{self.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return None


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
