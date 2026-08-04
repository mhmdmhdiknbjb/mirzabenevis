"""
کلاینت API رسان پذیرش۲۴ برای ارسال پیامک به بیمار.
مرجع: مستندات OpenAPI رسان (openapi.paziresh24.com), scope های
provider.rasan.read (موجودی) و provider.rasan.write (ارسال).

نکته: پیش از اولین ارسال، باید از فرانت‌اند window.hamdast.rasan.activate()
صدا زده شده باشد (این کار در ویجت انجام می‌شود، نه اینجا).
"""
import logging

import httpx

from app.config import Settings

logger = logging.getLogger("visit_note.rasan")


class RasanError(Exception):
    """خطای ارسال پیامک — پیام آن برای برگرداندن به کلاینت امن است."""

    def __init__(self, message: str, *, code: str | None = None, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def get_sms_balance(access_token: str, settings: Settings) -> dict:
    """موجودی اعتبار پیامک پزشک را برمی‌گرداند. {"credit": ..., "unit": "IRR"}"""
    url = f"{settings.paziresh24_openapi_base_url}/v1/rasan/balance"
    try:
        response = httpx.get(url, headers=_headers(access_token), timeout=settings.paziresh24_api_timeout_seconds)
    except httpx.TimeoutException as e:
        raise RasanError("سرویس پیامک پاسخ نداد (timeout).") from e
    except httpx.HTTPError as e:
        raise RasanError("خطا در ارتباط با سرویس پیامک.") from e

    if response.status_code == 409:
        raise RasanError(
            "سرویس پیامک برای این پزشک هنوز فعال نشده است.", code="SMS_NOT_ACTIVATED", status_code=409
        )
    if response.status_code == 403:
        raise RasanError("دسترسی مشاهده موجودی پیامک تأیید نشده است.", status_code=403)
    if response.status_code == 401:
        logger.error("Rasan balance 401: %s", response.text)
        raise RasanError("نشست ورود نامعتبر یا منقضی شده است.", status_code=401)
    if response.status_code >= 400:
        logger.error("Rasan balance error %s: %s", response.status_code, response.text)
        raise RasanError("خطای نامشخص در دریافت موجودی پیامک.", status_code=response.status_code)

    return response.json()


def send_sms(access_token: str, receptor: str, message: str, settings: Settings) -> dict:
    """
    یک پیامک به شماره‌ی receptor ارسال می‌کند.
    receptor باید شماره موبایل معتبر باشد (۱۰ تا ۱۶ کاراکتر، مثل 09121234567).
    message حداکثر ۹۰۰ کاراکتر.
    """
    url = f"{settings.paziresh24_openapi_base_url}/v1/rasan/messages"
    payload = {"message": message[:900], "receptor": receptor}

    try:
        response = httpx.post(
            url, headers=_headers(access_token), json=payload, timeout=settings.paziresh24_api_timeout_seconds
        )
    except httpx.TimeoutException as e:
        raise RasanError("سرویس پیامک پاسخ نداد (timeout).") from e
    except httpx.HTTPError as e:
        raise RasanError("خطا در ارتباط با سرویس پیامک.") from e

    if response.status_code == 200:
        return response.json()
    if response.status_code == 402:
        raise RasanError("اعتبار پیامک پزشک کافی نیست.", code="INSUFFICIENT_SMS_CREDIT", status_code=402)
    if response.status_code == 409:
        logger.error("Rasan send 409: %s", response.text)
        raise RasanError(
            "سرویس پیامک برای این پزشک هنوز فعال نشده است.", code="SMS_NOT_ACTIVATED", status_code=409
        )
    if response.status_code == 403:
        logger.error("Rasan send 403: %s", response.text)
        raise RasanError("دسترسی ارسال پیامک تأیید نشده است.", status_code=403)
    if response.status_code == 401:
        logger.error("Rasan send 401: %s", response.text)
        try:
            import base64, json as _json
            payload_b64 = access_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
            logger.error("Token debug -> exp=%s scope=%s aud=%s iss=%s", payload.get("exp"), payload.get("scope"), payload.get("aud"), payload.get("iss"))
        except Exception as debug_err:
            logger.error("Token debug failed: %s", debug_err)
        raise RasanError("نشست ورود نامعتبر یا منقضی شده است.", status_code=401)
    if response.status_code == 400:
        logger.warning("Rasan send validation error: %s", response.text)
        raise RasanError("شماره موبایل یا متن پیامک نامعتبر است.", status_code=400)

    logger.error("Rasan send error %s: %s", response.status_code, response.text)
    raise RasanError("خطای نامشخص در ارسال پیامک.", status_code=response.status_code)
