"""لایه صحه‌سنجی اصطلاحات پزشکی و تولید پرونده ساختاریافته JSON."""
import json
import logging
import re

from openai import OpenAI, APIError, APITimeoutError
from pydantic import ValidationError

from app.config import Settings
from app.prompts import NOTE_BUILDER_SYSTEM_PROMPT, SPELL_CHECK_SYSTEM_PROMPT
from app.schemas import VisitNote

logger = logging.getLogger("visit_note.llm")

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


class NoteGenerationError(Exception):
    """خطای مرحله اصلاح متن یا تولید JSON — پیام آن برای برگرداندن به کلاینت امن است."""


def _get_client(settings: Settings) -> OpenAI:
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )


def _strip_think_tags(text: str) -> str:
    return _THINK_TAG_RE.sub("", text).strip()


def _strip_json_fences(text: str) -> str:
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def correct_medical_terms(transcript: str, settings: Settings) -> str:
    """
    اصلاح اسامی پزشکی. اگر این مرحله fail شود، متن خام برگردانده می‌شود
    (fail-soft) چون این مرحله صرفاً یک بهبود کیفیت است، نه استخراج اطلاعات حیاتی.
    """
    client = _get_client(settings)
    try:
        response = client.chat.completions.create(
            model=settings.llm_model_name,
            messages=[
                {"role": "system", "content": SPELL_CHECK_SYSTEM_PROMPT},
                {"role": "user", "content": f"متن برای اصلاح اسامی پزشکی:\n\n{transcript}"},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
        corrected = response.choices[0].message.content or ""
        corrected = _strip_think_tags(corrected)
        return corrected or transcript
    except (APIError, APITimeoutError) as e:
        logger.warning("Term correction failed, falling back to raw transcript: %s", e)
        return transcript
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected term-correction failure, falling back to raw transcript")
        return transcript


def build_note(transcript: str, settings: Settings, *, max_retries: int = 1) -> VisitNote:
    """
    متن اصلاح‌شده را به JSON ساختاریافته تبدیل می‌کند و بلافاصله در برابر
    اسکیمای VisitNote اعتبارسنجی می‌کند. اگر مدل JSON نامعتبر برگرداند،
    حداکثر تا max_retries بار دوباره تلاش می‌شود.
    این مرحله برخلاف اصلاح اصطلاحات fail-soft نیست: پرونده پزشکی نباید
    بدون داده معتبر به پزشک نشان داده شود.
    """
    client = _get_client(settings)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=settings.llm_model_name,
                messages=[
                    {"role": "system", "content": NOTE_BUILDER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"متن خام ویزیت (اصلاح‌شده):\n\n{transcript}"},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
        except APITimeoutError as e:
            raise NoteGenerationError(
                "سرویس تولید پرونده پاسخ نداد (timeout). لطفاً دوباره تلاش کنید."
            ) from e
        except APIError as e:
            raise NoteGenerationError("خطا در سرویس تولید پرونده. لطفاً بعداً دوباره تلاش کنید.") from e

        raw_text = response.choices[0].message.content or ""
        raw_text = _strip_think_tags(raw_text)
        cleaned = _strip_json_fences(raw_text)

        try:
            parsed = json.loads(cleaned)
            return VisitNote.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning(
                "Invalid JSON from LLM on attempt %s/%s: %s",
                attempt + 1,
                max_retries + 1,
                e,
            )
            continue

    logger.error("Note generation failed after %s attempts: %s", max_retries + 1, last_error)
    raise NoteGenerationError(
        "خروجی پرونده تولیدشده معتبر نبود. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
    )
