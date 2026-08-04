"""
کلاینت‌های سبک برای APIهای پذیرش۲۴ مربوط به انتخاب بیمار (مراکز درمانی + نوبت‌ها)
و ارسال یادداشت ویزیت از طریق گفتگوی مربوط به همان نوبت.

نکته: در حال حاضر endpoint رسمی «ثبت در پرونده/نسخه» در مستندات عمومی پذیرش۲۴
موجود نیست؛ به‌جای آن از API چت (Chats) برای ارسال خلاصه استفاده می‌شود.
"""
import logging

import httpx

from app.config import Settings

logger = logging.getLogger("visit_note.paziresh24")


class Paziresh24APIError(Exception):
    """خطای ارتباط با APIهای پذیرش۲۴ — پیام آن برای برگرداندن به کلاینت امن است."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def get_medical_centers(access_token: str, settings: Settings) -> list[dict]:
    """لیست مراکز درمانی پزشک را برمی‌گرداند (برای فیلتر کردن نوبت‌ها لازم است)."""
    url = f"{settings.paziresh24_apigw_base_url}/open-platform/v1/booking/medical-centers"
    try:
        response = httpx.get(url, headers=_headers(access_token), timeout=settings.paziresh24_api_timeout_seconds)
    except httpx.TimeoutException as e:
        raise Paziresh24APIError("سرویس پذیرش۲۴ پاسخ نداد (timeout).") from e
    except httpx.HTTPError as e:
        raise Paziresh24APIError("خطا در ارتباط با سرویس پذیرش۲۴.") from e

    if response.status_code == 401:
        raise Paziresh24APIError("نشست ورود نامعتبر یا منقضی شده است.", status_code=401)
    if response.status_code == 403:
        raise Paziresh24APIError(
            "دسترسی لازم برای مشاهده مراکز درمانی وجود ندارد (اسکوپ view-calendar).", status_code=403
        )
    if response.status_code >= 400:
        logger.error("Medical centers error %s: %s", response.status_code, response.text)
        raise Paziresh24APIError("خطا در دریافت لیست مراکز درمانی.", status_code=response.status_code)

    data = response.json()
    return data.get("data", []) if isinstance(data, dict) else data


def get_appointments(
    access_token: str,
    center_id: str,
    settings: Settings,
    *,
    date_start: str | None = None,
    date_end: str | None = None,
) -> list[dict]:
    """لیست نوبت‌های پزشک در یک مرکز درمانی، برای انتخاب بیمار پیش از ثبت ویزیت."""
    url = f"{settings.paziresh24_openapi_base_url}/v1/booking/appointments"
    params = {"center_id": center_id}
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end

    try:
        response = httpx.get(
            url, headers=_headers(access_token), params=params, timeout=settings.paziresh24_api_timeout_seconds
        )
    except httpx.TimeoutException as e:
        raise Paziresh24APIError("سرویس پذیرش۲۴ پاسخ نداد (timeout).") from e
    except httpx.HTTPError as e:
        raise Paziresh24APIError("خطا در ارتباط با سرویس پذیرش۲۴.") from e

    if response.status_code == 401:
        raise Paziresh24APIError("نشست ورود نامعتبر یا منقضی شده است.", status_code=401)
    if response.status_code == 403:
        raise Paziresh24APIError(
            "دسترسی لازم برای مشاهده نوبت‌ها وجود ندارد (اسکوپ view-calendar).", status_code=403
        )
    if response.status_code >= 400:
        logger.error("Appointments error %s: %s", response.status_code, response.text)
        raise Paziresh24APIError("خطا در دریافت لیست نوبت‌ها.", status_code=response.status_code)

    return response.json()


def send_chat_message(access_token: str, appointment_id: int, content: str, settings: Settings) -> dict:
    """
    یادداشت/خلاصه‌ی نهایی ویزیت را به گفتگوی مربوط به همان نوبت (appointment_id) ارسال می‌کند.
    این جایگزین موقتی «ثبت در پرونده رسمی» است، چون endpoint رسمی ثبت پرونده/نسخه
    در مستندات عمومی پذیرش۲۴ موجود نیست.
    """
    url = f"{settings.paziresh24_apigw_base_url}/open-platform/v1/chats/{appointment_id}/messages"
    payload = {"content": content}

    try:
        response = httpx.post(
            url, headers=_headers(access_token), json=payload, timeout=settings.paziresh24_api_timeout_seconds
        )
    except httpx.TimeoutException as e:
        raise Paziresh24APIError("سرویس چت پذیرش۲۴ پاسخ نداد (timeout).") from e
    except httpx.HTTPError as e:
        raise Paziresh24APIError("خطا در ارتباط با سرویس چت پذیرش۲۴.") from e

    if response.status_code == 404:
        raise Paziresh24APIError("گفتگوی مربوط به این نوبت پیدا نشد.", status_code=404)
    if response.status_code == 401:
        raise Paziresh24APIError("نشست ورود نامعتبر یا منقضی شده است.", status_code=401)
    if response.status_code == 403:
        raise Paziresh24APIError("دسترسی ارسال پیام در این گفتگو تأیید نشده است.", status_code=403)
    if response.status_code >= 400:
        logger.error("Chat send error %s: %s", response.status_code, response.text)
        raise Paziresh24APIError("خطا در ارسال پیام به گفتگوی بیمار.", status_code=response.status_code)

    return response.json()
