"""
تنظیمات سرویس — همه مقادیر حساس از Environment Variables خوانده می‌شوند.
هیچ کلید API نباید در کد hardcode شود.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Speech-to-Text ---
    stt_base_url: str = "https://api.abrha.ai/v1/"
    stt_api_key: str
    stt_model_name: str = "openai/gpt-4-o-transcribe"

    # --- LLM ---
    llm_base_url: str = "https://my.parspack.com/api/aistudio/api/v1"
    llm_api_key: str
    llm_model_name: str = "qwen/qwen3-32b"

    # --- احراز هویت پذیرش24 / همدست ---
    # app_key همان چیزی است که در کنسول همدست، هنگام ساخت ابزارک می‌گیری
    # و در فرانت‌اند به window.hamdast.initialize({app_key}) می‌دهی.
    hamdast_app_key: str = ""
    # این کلید توسعه‌دهنده (x-api-key) است — هرگز نباید در فرانت‌اند/ابزارک قرار بگیرد،
    # فقط سرور به سرور بین بک‌اند ما و hamdast.paziresh24.com استفاده می‌شود.
    hamdast_developer_api_key: str = ""
    hamdast_base_url: str = "https://hamdast.paziresh24.com"
    hamdast_timeout_seconds: int = 15

    paziresh24_openapi_base_url: str = "https://openapi.paziresh24.com"
    paziresh24_apigw_base_url: str = "https://apigw.paziresh24.com"
    paziresh24_api_timeout_seconds: int = 15

    # --- عمومی ---
    allowed_origins: str = ""
    max_audio_size_mb: int = 25
    stt_timeout_seconds: int = 60
    llm_timeout_seconds: int = 45
    delete_temp_files: bool = True
    log_level: str = "INFO"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def max_audio_size_bytes(self) -> int:
        return self.max_audio_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    # اگر یکی از کلیدهای الزامی ست نشده باشد، همین‌جا با خطای واضح متوقف می‌شویم
    # به‌جای اینکه بعداً وسط یک درخواست کاربر fail کنیم.
    return Settings()
