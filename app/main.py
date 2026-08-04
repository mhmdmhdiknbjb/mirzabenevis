"""
سرویس تبدیل ویزیت پزشکی (صدا یا متن) به پرونده ساختاریافته فارسی.
این سرویس قرار است پشتِ ابزارک پذیرش۲۴ اجرا شود؛ ابزارک فایل صوتی/متن را
از فرانت‌اند می‌گیرد و به این سرویس می‌فرستد.
"""
import logging
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.schemas import (
    RecordsListResponse,
    SaveRecordRequest,
    SaveRecordResponse,
    VisitRecordItem,
    ErrorResponse,
    MedicalCenterOption,
    MedicalCentersListResponse,
    PatientListResponse,
    PatientOption,
    SendToChatRequest,
    SendToChatResponse,
    SessionExchangeRequest,
    SessionExchangeResponse,
    SmsRequest,
    SmsResponse,
    VisitNoteResponse,
)
from app.services.db_service import get_records_by_cell, init_db, save_record
from app.services.hamdast_auth import HamdastAuthError, exchange_session_token
from app.services.llm_service import NoteGenerationError, build_note, correct_medical_terms
from app.services.paziresh24_service import (
    Paziresh24APIError,
    get_appointments,
    get_medical_centers,
    send_chat_message,
)
from app.services.rasan_service import RasanError, send_sms
from app.services.stt_service import TranscriptionError, transcribe_audio_bytes

settings = get_settings()

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("visit_note.api")
init_db()

app = FastAPI(title="Visit Note Service", version="1.0.0")

# --- تنظیم و اتصال پوشه Static برای سرو فایل widget.html ---
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)  # در صورت عدم وجود پوشه، آن را می‌سازد

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list or ["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post(
    "/api/v1/auth/session",
    response_model=SessionExchangeResponse,
    responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
async def exchange_session(payload: SessionExchangeRequest):
    """
    فرانت‌اند ابزارک، session_token گرفته‌شده از window.hamdast.getSessionToken(...)
    را اینجا می‌فرستد و در ازای آن access_token می‌گیرد.
    این تبادل باید همیشه سمت سرور انجام شود چون به HAMDAST_DEVELOPER_API_KEY نیاز دارد.
    """
    request_id = str(uuid.uuid4())
    try:
        access_token = exchange_session_token(payload.session_token, settings)
    except HamdastAuthError as e:
        logger.warning("[%s] hamdast auth failed: %s", request_id, e)
        raise HTTPException(
            status_code=401,
            detail=ErrorResponse(
                request_id=request_id, stage="hamdast_auth", message=str(e)
            ).model_dump(),
        ) from e

    return SessionExchangeResponse(access_token=access_token)


def require_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """
    یک محافظ سبک برای endpointهای پولی/حساس: فقط بررسی می‌کند که یک access_token
    همراه درخواست آمده باشد. این توکن همان چیزی است که در مرحله /api/v1/auth/session
    گرفته شده. اعتبارسنجی عمیق‌تر (مثلاً تطبیق با پروفایل پزشک از API پذیرش۲۴)
    باید بعداً، وقتی endpoint دقیق پروفایل از مستندات API مشخص شد، اضافه شود.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail=ErrorResponse(
                request_id=str(uuid.uuid4()),
                stage="authorization",
                message="هدر Authorization با فرمت 'Bearer <access_token>' لازم است.",
            ).model_dump(),
        )
    return authorization.split(" ", 1)[1]


@app.post(
    "/api/v1/visit-notes",
    response_model=VisitNoteResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
async def create_visit_note(
    audio: UploadFile | None = File(default=None, description="فایل صوتی ویزیت (m4a/mp3/wav/...)"),
    transcript: str | None = Form(default=None, description="متن خام ویزیت، اگر از قبل موجود است"),
    access_token: str = Depends(require_bearer_token),
):
    """
    یکی از این دو ورودی باید داده شود:
    - `audio`: فایل صوتی برای تبدیل به متن
    - `transcript`: متن خام از قبل آماده (اگر پزشک به‌جای ویس، تایپ کرده)

    نیازمند هدر Authorization: Bearer <access_token> است.
    """
    request_id = str(uuid.uuid4())

    if not audio and not transcript:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                request_id=request_id,
                stage="validation",
                message="باید یکی از دو فیلد audio یا transcript ارسال شود.",
            ).model_dump(),
        )

    # --- مرحله ۱: تبدیل صدا به متن (در صورت وجود فایل صوتی) ---
    if audio:
        audio_bytes = await audio.read()

        if len(audio_bytes) == 0:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    request_id=request_id, stage="validation", message="فایل صوتی خالی است."
                ).model_dump(),
            )

        if len(audio_bytes) > settings.max_audio_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    request_id=request_id,
                    stage="validation",
                    message=f"حجم فایل صوتی بیشتر از حد مجاز ({settings.max_audio_size_mb} مگابایت) است.",
                ).model_dump(),
            )

        try:
            raw_transcript = transcribe_audio_bytes(
                audio_bytes, audio.filename or "recording.m4a", settings
            )
        except TranscriptionError as e:
            logger.warning("[%s] transcription failed: %s", request_id, e)
            raise HTTPException(
                status_code=502,
                detail=ErrorResponse(
                    request_id=request_id, stage="transcription", message=str(e)
                ).model_dump(),
            ) from e
    else:
        raw_transcript = (transcript or "").strip()
        if not raw_transcript:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    request_id=request_id, stage="validation", message="متن ورودی خالی است."
                ).model_dump(),
            )

    # --- مرحله ۲: صحه‌سنجی و استانداردسازی اصطلاحات پزشکی (fail-soft) ---
    corrected_transcript = correct_medical_terms(raw_transcript, settings)

    # --- مرحله ۳: تولید JSON ساختاریافته پرونده ---
    try:
        note = build_note(corrected_transcript, settings)
    except NoteGenerationError as e:
        logger.error("[%s] note generation failed: %s", request_id, e)
        raise HTTPException(
            status_code=502,
            detail=ErrorResponse(
                request_id=request_id, stage="note_generation", message=str(e)
            ).model_dump(),
        ) from e

    logger.info("[%s] visit note generated successfully", request_id)

    return VisitNoteResponse(
        request_id=request_id,
        raw_transcript=raw_transcript,
        corrected_transcript=corrected_transcript,
        note=note,
    )


@app.post(
    "/api/v1/patient-sms",
    response_model=SmsResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        402: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def send_patient_sms(
    payload: SmsRequest,
    access_token: str = Depends(require_bearer_token),
):
    """
    خلاصه‌ی ویزیت (یا هر متن دیگر) را به شماره موبایل بیمار پیامک می‌کند.
    نیازمند هدر Authorization: Bearer <access_token> با scope فعال provider.rasan.write.
    پیش از اولین ارسال، فرانت‌اند باید window.hamdast.rasan.activate() را صدا زده باشد.
    """
    request_id = str(uuid.uuid4())
    try:
        result = send_sms(access_token, payload.receptor, payload.message, settings)
    except RasanError as e:
        logger.warning("[%s] SMS send failed (%s): %s", request_id, e.code, e)
        raise HTTPException(
            status_code=e.status_code,
            detail=ErrorResponse(request_id=request_id, stage="rasan_sms", message=str(e)).model_dump(),
        ) from e

    return SmsResponse(message_id=result.get("message_id"), status_text=result.get("status_text"))


@app.get("/api/v1/medical-centers", response_model=MedicalCentersListResponse)
async def list_medical_centers(access_token: str = Depends(require_bearer_token)):
    """لیست مراکز درمانی پزشک، برای انتخاب مرکز قبل از دیدن لیست بیماران."""
    request_id = str(uuid.uuid4())
    try:
        raw_centers = get_medical_centers(access_token, settings)
    except Paziresh24APIError as e:
        logger.warning("[%s] medical centers fetch failed: %s", request_id, e)
        raise HTTPException(
            status_code=e.status_code,
            detail=ErrorResponse(request_id=request_id, stage="medical_centers", message=str(e)).model_dump(),
        ) from e

    centers = [
        MedicalCenterOption(id=str(c.get("id", "")), name=c.get("name") or c.get("title") or "")
        for c in raw_centers
        if isinstance(c, dict)
    ]
    return MedicalCentersListResponse(centers=centers)


@app.get("/api/v1/patients", response_model=PatientListResponse)
async def list_patients(
    center_id: str,
    date_start: str | None = None,
    date_end: str | None = None,
    access_token: str = Depends(require_bearer_token),
):
    """لیست نوبت‌های پزشک در یک مرکز درمانی، برای انتخاب بیمار پیش از ثبت ویزیت."""
    request_id = str(uuid.uuid4())
    try:
        raw_appointments = get_appointments(
            access_token, center_id, settings, date_start=date_start, date_end=date_end
        )
    except Paziresh24APIError as e:
        logger.warning("[%s] appointments fetch failed: %s", request_id, e)
        raise HTTPException(
            status_code=e.status_code,
            detail=ErrorResponse(request_id=request_id, stage="appointments", message=str(e)).model_dump(),
        ) from e

    patients: list[PatientOption] = []
    items = raw_appointments if isinstance(raw_appointments, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        patient = item.get("patient") or {}
        patients.append(
            PatientOption(
                appointment_id=item.get("id"),
                name=patient.get("name", ""),
                family=patient.get("family", ""),
                cell=patient.get("cell", ""),
                national_code=patient.get("national_code", ""),
                from_iso=item.get("from_iso", ""),
                to_iso=item.get("to_iso", ""),
            )
        )
    return PatientListResponse(patients=patients)


@app.post("/api/v1/send-to-chat", response_model=SendToChatResponse)
async def send_note_to_chat(payload: SendToChatRequest, access_token: str = Depends(require_bearer_token)):
    """
    یادداشت نهایی ویزیت را به گفتگوی مربوط به نوبت انتخاب‌شده ارسال می‌کند
    (جایگزین موقت «ثبت در پرونده رسمی» تا زمانی که endpoint رسمی آن مشخص شود).
    """
    request_id = str(uuid.uuid4())
    try:
        result = send_chat_message(access_token, payload.appointment_id, payload.content, settings)
    except Paziresh24APIError as e:
        logger.warning("[%s] send-to-chat failed: %s", request_id, e)
        raise HTTPException(
            status_code=e.status_code,
            detail=ErrorResponse(request_id=request_id, stage="chat_send", message=str(e)).model_dump(),
        ) from e

    return SendToChatResponse(message=result.get("message"))


@app.post("/api/v1/records", response_model=SaveRecordResponse)
async def save_visit_record(
    payload: SaveRecordRequest,
    access_token: str = Depends(require_bearer_token),
):
    """
    پرونده ویزیت را در دیتابیس ذخیره می‌کند و
    در صورت وجود appointment_id، خلاصه را به چت نوبت هم می‌فرستد.
    """
    request_id = str(uuid.uuid4())

    # استخراج user_id پزشک از توکن JWT
    try:
        import base64 as _b64, json as _json
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        token_data = _json.loads(_b64.urlsafe_b64decode(payload_b64))
        provider_user_id = str(token_data.get("sub", "unknown"))
    except Exception:
        provider_user_id = "unknown"

    record_id = save_record(
        appointment_id=payload.appointment_id,
        patient_name=payload.patient_name,
        patient_family=payload.patient_family,
        patient_cell=payload.patient_cell,
        provider_user_id=provider_user_id,
        note=payload.note,
    )

    # ارسال خلاصه به چت نوبت
    chat_sent = False
    if payload.appointment_id:
        note = payload.note
        drugs = note.get("list_daroha", [])
        drugs_text = "\n".join(
            f"- {d.get('nam','')}: {d.get('doz','')}، {d.get('zaman_masraf','')}، {d.get('modat','')}"
            for d in drugs if d.get("nam")
        )
        peygiri = note.get("peygiriha", {})
        parts = [
            note.get("khaleseh_bimar", ""),
            f"داروها:\n{drugs_text}" if drugs_text else "",
            f"مراجعه بعد: {peygiri.get('tarikh_moraje_baad','')}" if peygiri.get("tarikh_moraje_baad") else "",
            f"علائم هشدار: {', '.join(peygiri.get('alaem_hoshdar',[]))}" if peygiri.get("alaem_hoshdar") else "",
            f"آزمایش‌ها: {', '.join(peygiri.get('azmayeshat',[]))}" if peygiri.get("azmayeshat") else "",
        ]
        content_text = "\n\n".join(p for p in parts if p)
        try:
            send_chat_message(access_token, payload.appointment_id, content_text, settings)
            chat_sent = True
        except Paziresh24APIError as e:
            logger.warning("[%s] chat send failed after save: %s", request_id, e)

    logger.info("[%s] record saved id=%s chat_sent=%s", request_id, record_id, chat_sent)
    return SaveRecordResponse(record_id=record_id, chat_sent=chat_sent)


@app.get("/api/v1/records", response_model=RecordsListResponse)
async def get_patient_records(
    patient_cell: str,
    access_token: str = Depends(require_bearer_token),
):
    """پرونده‌های قبلی یک بیمار (بر اساس موبایل) برای این پزشک."""
    try:
        import base64 as _b64, json as _json
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        token_data = _json.loads(_b64.urlsafe_b64decode(payload_b64))
        provider_user_id = str(token_data.get("sub", "unknown"))
    except Exception:
        provider_user_id = "unknown"

    rows = get_records_by_cell(patient_cell, provider_user_id)
    records = [VisitRecordItem(**r) for r in rows]
    return RecordsListResponse(records=records)


@app.get("/api/v1/debug/appointments")
async def debug_appointments(
    center_id: str,
    access_token: str = Depends(require_bearer_token),
):
    """endpoint موقت برای دیدن پاسخ خام API نوبت‌ها."""
    import httpx
    today = __import__('datetime').date.today().isoformat()
    url = f"{settings.paziresh24_openapi_base_url}/v1/booking/appointments"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"}, params={"center_id": center_id, "date_start": today, "date_end": today}, timeout=15)
    return resp.json()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # هرگز stack trace یا پیام خطای خام را به کلاینت برنگردان
    request_id = str(uuid.uuid4())
    logger.exception("[%s] unhandled exception", request_id)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            request_id=request_id,
            stage="unknown",
            message="خطای غیرمنتظره سرور. لطفاً بعداً دوباره تلاش کنید.",
        ).model_dump(),
    )