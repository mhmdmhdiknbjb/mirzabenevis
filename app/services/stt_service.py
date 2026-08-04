"""تبدیل فایل صوتی به متن — با timeout و مدیریت خطای صریح."""
import logging

from openai import OpenAI, APIError, APITimeoutError

from app.config import Settings

logger = logging.getLogger("visit_note.stt")


class TranscriptionError(Exception):
    """خطای مرحله تبدیل صدا به متن — پیام آن برای برگرداندن به کلاینت امن است."""


def transcribe_audio_bytes(audio_bytes: bytes, filename: str, settings: Settings) -> str:
    """
    فایل صوتی را به متن تبدیل می‌کند.
    ورودی به صورت bytes گرفته می‌شود (نه مسیر فایل روی دیسک) تا لایه API
    مجبور به نگه‌داشتن فایل موقت روی دیسک نباشد.
    """
    client = OpenAI(
        base_url=settings.stt_base_url,
        api_key=settings.stt_api_key,
        timeout=settings.stt_timeout_seconds,
    )

    try:
        # OpenAI SDK برای آپلود فایل، یک tuple (filename, bytes, content_type) قبول می‌کند
        transcription = client.audio.transcriptions.create(
            model=settings.stt_model_name,
            file=(filename, audio_bytes),
        )
    except APITimeoutError as e:
        logger.error("STT timeout after %ss", settings.stt_timeout_seconds)
        raise TranscriptionError(
            "سرویس تبدیل گفتار به متن پاسخ نداد (timeout). لطفاً دوباره تلاش کنید."
        ) from e
    except APIError as e:
        logger.error("STT API error: %s", e)
        raise TranscriptionError(
            "خطا در سرویس تبدیل گفتار به متن. لطفاً بعداً دوباره تلاش کنید."
        ) from e
    except Exception as e:  # noqa: BLE001 - می‌خواهیم هیچ خطای پیش‌بینی‌نشده‌ای بیرون نریزد
        logger.exception("Unexpected STT failure")
        raise TranscriptionError("خطای غیرمنتظره در تبدیل صدا به متن.") from e

    text = (transcription.text or "").strip()
    if not text:
        raise TranscriptionError(
            "متنی از فایل صوتی استخراج نشد. لطفاً کیفیت ضبط را بررسی کنید."
        )
    return text
