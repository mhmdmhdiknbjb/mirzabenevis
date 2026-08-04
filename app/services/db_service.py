"""
ذخیره و بازیابی پرونده‌های ویزیت در SQLite.
هر رکورد شامل اطلاعات بیمار، یادداشت پزشک و خلاصه مراجعه بعد است.
"""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("visit_note.db")

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "records.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """ساخت جدول‌ها در صورت عدم وجود."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visit_audio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER,
                provider_user_id TEXT,
                patient_cell TEXT,
                audio_filename TEXT,
                raw_transcript TEXT,
                corrected_transcript TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER,
                patient_name TEXT,
                patient_family TEXT,
                patient_cell TEXT,
                provider_user_id TEXT,
                yaddasht_pezeshk TEXT,
                khaleseh_bimar TEXT,
                list_daroha TEXT,
                azmayeshat TEXT,
                tarikh_moraje_baad TEXT,
                alaem_hoshdar TEXT,
                khaleseh_moraje_baad TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
    logger.info("DB initialized at %s", DB_PATH)


def save_record(
    appointment_id: int | None,
    patient_name: str,
    patient_family: str,
    patient_cell: str,
    provider_user_id: str,
    note: dict,
) -> int:
    """ذخیره پرونده و برگرداندن id رکورد."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO visit_records
            (appointment_id, patient_name, patient_family, patient_cell,
             provider_user_id, yaddasht_pezeshk, khaleseh_bimar,
             list_daroha, azmayeshat, tarikh_moraje_baad, alaem_hoshdar, khaleseh_moraje_baad)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                appointment_id,
                patient_name,
                patient_family,
                patient_cell,
                provider_user_id,
                note.get("yaddasht_pezeshk", ""),
                note.get("khaleseh_bimar", ""),
                json.dumps(note.get("list_daroha", []), ensure_ascii=False),
                json.dumps(note.get("peygiriha", {}).get("azmayeshat", []), ensure_ascii=False),
                note.get("peygiriha", {}).get("tarikh_moraje_baad", ""),
                json.dumps(note.get("peygiriha", {}).get("alaem_hoshdar", []), ensure_ascii=False),
                note.get("khaleseh_moraje_baad", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_records_by_cell(patient_cell: str, provider_user_id: str) -> list[dict]:
    """پرونده‌های قبلی یک بیمار (بر اساس موبایل) برای این پزشک."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM visit_records
            WHERE patient_cell = ? AND provider_user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (patient_cell, provider_user_id),
        ).fetchall()

    result = []
    for row in rows:
        r = dict(row)
        r["list_daroha"] = json.loads(r.get("list_daroha") or "[]")
        r["azmayeshat"] = json.loads(r.get("azmayeshat") or "[]")
        r["alaem_hoshdar"] = json.loads(r.get("alaem_hoshdar") or "[]")
        result.append(r)
    return result


def save_audio_record(
    record_id: int | None,
    provider_user_id: str,
    patient_cell: str,
    audio_filename: str,
    raw_transcript: str,
    corrected_transcript: str,
) -> int:
    """ذخیره اطلاعات صوتی و متن ویزیت."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO visit_audio
            (record_id, provider_user_id, patient_cell, audio_filename, raw_transcript, corrected_transcript)
            VALUES (?,?,?,?,?,?)
            """,
            (record_id, provider_user_id, patient_cell, audio_filename, raw_transcript, corrected_transcript),
        )
        conn.commit()
        return cur.lastrowid
