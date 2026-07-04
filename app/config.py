from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI 家装一键成片系统"
    app_env: str = "local"
    app_base_url: str = "http://127.0.0.1:8000"
    secret_key: str = "change-me"

    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: Optional[str] = None
    openai_tts_model: Optional[str] = None

    tbk_app_key: Optional[str] = None
    tbk_app_secret: Optional[str] = None
    tbk_adzone_id: Optional[str] = None
    tbk_pid: Optional[str] = None
    tbk_site_id: Optional[str] = None
    tbk_api_url: str = "https://eco.taobao.com/router/rest"
    tbk_min_commission_rate: int = 1000
    tbk_min_sales: int = 20
    tbk_strict_filters: bool = False

    render_provider: str = "demo"
    render_api_url: Optional[str] = None
    render_api_key: Optional[str] = None
    render_api_secret: Optional[str] = None
    render_endpoint: str = "/v1/images/generations"
    render_auth_header: str = "Authorization"
    render_auth_prefix: str = "Bearer"
    render_model: str = "kling-v1"
    render_aspect_ratio: str = "16:9"
    render_poll_seconds: int = Field(default=120, ge=10)

    video_width: int = 1080
    video_height: int = 1920
    log_retention_days: int = 180
    rate_limit_per_minute: int = Field(default=20, ge=1)

    storage_dir: Path = ROOT_DIR / "storage"
    logs_dir: Path = ROOT_DIR / "storage" / "logs"
    exports_dir: Path = ROOT_DIR / "storage" / "exports"
    videos_dir: Path = ROOT_DIR / "storage" / "videos"
    renders_dir: Path = ROOT_DIR / "storage" / "renders"
    tmp_dir: Path = ROOT_DIR / "storage" / "tmp"

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "openai_model",
        "openai_tts_model",
        "tbk_app_key",
        "tbk_app_secret",
        "tbk_adzone_id",
        "tbk_pid",
        "tbk_site_id",
        "tbk_api_url",
        "render_provider",
        "render_api_url",
        "render_api_key",
        "render_api_secret",
        "render_endpoint",
        "render_auth_header",
        "render_auth_prefix",
        "render_model",
        "render_aspect_ratio",
        mode="before",
    )
    @classmethod
    def strip_env_strings(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def is_deepseek(self) -> bool:
        return "deepseek" in self.openai_base_url.lower()

    @property
    def has_tts(self) -> bool:
        return self.has_openai and not self.is_deepseek

    @property
    def has_tbk(self) -> bool:
        return bool(self.tbk_app_key and self.tbk_app_secret and self.tbk_adzone_id)

    def ensure_dirs(self) -> None:
        for path in [self.storage_dir, self.logs_dir, self.exports_dir, self.videos_dir, self.renders_dir, self.tmp_dir]:
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
