"""
تبادل session_token (که فرانت‌اند از SDK همدست می‌گیرد) با access_token.
این تبادل حتماً باید سمت سرور انجام شود چون به HAMDAST_DEVELOPER_API_KEY نیاز دارد
که هرگز نباید در فرانت‌اند/مرورگر افشا شود.

مرجع: https://developers.paziresh24.com/authorization
"""
import logging

import httpx

from app.config import Settings

logger = logging.getLogger("visit_note.hamdast_auth")


class HamdastAuthError(Exception):
    """خطای تبادل توکن — پیام آن برای برگرداندن به کلاینت امن است."""


def exchange_session_token(session_token: str, settings: Settings) -> str:
    """
    session_token گرفته‌شده در فرانت‌اند از window.hamdast.getSessionToken(...)
    را به access_token قابل استفاده برای فراخوانی APIهای پذیرش۲۴ تبدیل می‌کند.
    """
    if not settings.hamdast_app_key or not settings.hamdast_developer_api_key:
        # این یعنی سرویس هنوز کامل پیکربندی نشده — بهتر است زود و واضح خطا بدهیم
        raise HamdastAuthError(
            "سرویس هنوز برای اتصال به پذیرش۲۴ پیکربندی نشده (HAMDAST_APP_KEY یا "
            "HAMDAST_DEVELOPER_API_KEY تنظیم نشده است)."
        )

    url = f"{settings.hamdast_base_url}/api/v1/apps/{settings.hamdast_app_key}/oauth/access_token"

    try:
        response = httpx.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-api-key": settings.hamdast_developer_api_key,
            },
            json={"session_token": session_token},
            timeout=settings.hamdast_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.TimeoutException as e:
        logger.error("Hamdast auth timeout")
        raise HamdastAuthError("سرویس احراز هویت پذیرش۲۴ پاسخ نداد. دوباره تلاش کنید.") from e
    except httpx.HTTPStatusError as e:
        # 401/403 یعنی session_token نامعتبر یا منقضی شده
        logger.warning("Hamdast auth rejected: %s - %s", e.response.status_code, e.response.text)
        raise HamdastAuthError(
            "نشست ورود شما نامعتبر یا منقضی شده است. لطفاً دوباره وارد ابزارک شوید."
        ) from e
    except httpx.HTTPError as e:
        logger.exception("Unexpected Hamdast auth failure")
        raise HamdastAuthError("خطا در ارتباط با سرویس احراز هویت پذیرش۲۴.") from e

    data = response.json()
    # نکته: مستندات عمومی پذیرش۲۴ فقط درخواست curl را نشان می‌دهند، نه شکل دقیق پاسخ.
    # اسم فیلد "access_token" یک فرض منطقی/استاندارد OAuth است — قبل از استفاده در
    # پروداکشن، حتماً با یک درخواست واقعی (Postman/curl) پاسخ را بررسی کن و در صورت
    # نیاز اسم فیلد را اینجا تصحیح کن.
    access_token = data.get("access_token")
    if not access_token:
        logger.error("Hamdast auth response missing access_token: %s", data)
        raise HamdastAuthError("پاسخ نامعتبر از سرویس احراز هویت پذیرش۲۴.")

    logger.info("ACCESS_TOKEN_FIRST20: %s", access_token[:20])
    return access_token

