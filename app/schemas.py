from typing import Literal
from pydantic import BaseModel, Field


class DrugItem(BaseModel):
    nam: str
    doz: str
    zaman_masraf: str
    modat: str


class FollowUp(BaseModel):
    azmayeshat: list[str] = Field(default_factory=list)
    tarikh_moraje_baad: str = ""
    alaem_hoshdar: list[str] = Field(default_factory=list)


class VisitNote(BaseModel):
    """ساختار خروجی پرونده ویزیت — دقیقاً منطبق با قرارداد پرامپت."""
    yaddasht_pezeshk: str
    khaleseh_bimar: str
    list_daroha: list[DrugItem] = Field(default_factory=list)
    peygiriha: FollowUp
    khaleseh_moraje_baad: str


class VisitNoteResponse(BaseModel):
    status: Literal["ok"] = "ok"
    request_id: str
    raw_transcript: str
    corrected_transcript: str
    note: VisitNote


class SessionExchangeRequest(BaseModel):
    session_token: str


class SessionExchangeResponse(BaseModel):
    status: Literal["ok"] = "ok"
    access_token: str


class SmsRequest(BaseModel):
    receptor: str = Field(..., min_length=10, max_length=16, description="شماره موبایل بیمار، مثل 09121234567")
    message: str = Field(..., min_length=1, max_length=900)


class SmsResponse(BaseModel):
    status: Literal["ok"] = "ok"
    message_id: int | None = None
    status_text: str | None = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    request_id: str
    stage: str  # "transcription" | "term_correction" | "note_generation" | "validation"
    message: str


class MedicalCenterOption(BaseModel):
    id: str
    name: str = ""


class MedicalCentersListResponse(BaseModel):
    status: Literal["ok"] = "ok"
    centers: list[MedicalCenterOption] = Field(default_factory=list)


class PatientOption(BaseModel):
    appointment_id: int
    name: str = ""
    family: str = ""
    cell: str = ""
    national_code: str = ""
    from_iso: str = ""
    to_iso: str = ""


class PatientListResponse(BaseModel):
    status: Literal["ok"] = "ok"
    patients: list[PatientOption] = Field(default_factory=list)


class SendToChatRequest(BaseModel):
    appointment_id: int
    content: str = Field(..., min_length=1, max_length=4000)


class SendToChatResponse(BaseModel):
    status: Literal["ok"] = "ok"
    message: str | None = None


class SaveRecordRequest(BaseModel):
    appointment_id: int | None = None
    patient_name: str = ""
    patient_family: str = ""
    patient_cell: str = ""
    note: dict

class VisitRecordItem(BaseModel):
    id: int
    appointment_id: int | None = None
    patient_name: str = ""
    patient_family: str = ""
    patient_cell: str = ""
    yaddasht_pezeshk: str = ""
    khaleseh_bimar: str = ""
    list_daroha: list = []
    azmayeshat: list = []
    tarikh_moraje_baad: str = ""
    alaem_hoshdar: list = []
    khaleseh_moraje_baad: str = ""
    created_at: str = ""

class RecordsListResponse(BaseModel):
    status: Literal["ok"] = "ok"
    records: list[VisitRecordItem] = Field(default_factory=list)

class SaveRecordResponse(BaseModel):
    status: Literal["ok"] = "ok"
    record_id: int
    chat_sent: bool = False
