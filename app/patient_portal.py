import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("data/patient_accounts.db")
_OTP_STORE: dict = {}   # email -> {otp, expires}


def init_patient_portal_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS patient_accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            phone       TEXT    DEFAULT '',
            password_hash TEXT  NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS patient_tokens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id  INTEGER NOT NULL,
            token       TEXT    NOT NULL UNIQUE,
            expires_at  TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def register_patient(name, email, password, phone=''):
    con = _con()
    existing = con.execute("SELECT id FROM patient_accounts WHERE email=?", (email,)).fetchone()
    if existing:
        con.close()
        raise ValueError("Email already registered")
    con.execute(
        "INSERT INTO patient_accounts (name, email, phone, password_hash) VALUES (?,?,?,?)",
        (name, email.lower().strip(), phone, _hash(password))
    )
    con.commit()
    con.close()
    return {"message": "Registered successfully"}


def login_patient(email, password):
    con = _con()
    row = con.execute(
        "SELECT * FROM patient_accounts WHERE email=? AND password_hash=?",
        (email.lower().strip(), _hash(password))
    ).fetchone()
    if not row:
        con.close()
        raise ValueError("Invalid email or password")
    patient = dict(row)
    token = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(days=30)).isoformat()  # stay logged in for 30 days
    con.execute(
        "INSERT INTO patient_tokens (patient_id, token, expires_at) VALUES (?,?,?)",
        (patient['id'], token, expires)
    )
    con.commit()
    con.close()
    return {"token": token, "name": patient["name"], "email": patient["email"]}


def verify_patient_token(token: str):
    con = _con()
    row = con.execute(
        """SELECT pa.* FROM patient_accounts pa
           JOIN patient_tokens pt ON pa.id=pt.patient_id
           WHERE pt.token=? AND pt.expires_at > ?""",
        (token, datetime.now().isoformat())
    ).fetchone()
    con.close()
    return dict(row) if row else None


def list_patient_accounts() -> list[dict]:
    """All portal login accounts (for admin visibility)."""
    con = _con()
    rows = con.execute("SELECT name, email, phone, created_at FROM patient_accounts ORDER BY created_at DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_patient_data(patient_name: str) -> dict:
    """Aggregate all data for a patient across all DBs."""
    from app.appointments import list_appointments
    from app.health_tracking import get_latest, get_history, compute_health_score
    from app.consultation import list_prescriptions
    from app.lab_reports import list_lab_reports
    from app.billing import list_invoices
    from app.treatment_plans import list_plans
    from app.referrals import list_referrals
    from app.announcements import get_active_announcements

    all_appts = list_appointments()
    my_appts = [a for a in all_appts if a.get('patient_name','').lower() == patient_name.lower()]

    latest = get_latest(patient_name)
    score  = compute_health_score(latest)
    history = get_history(patient_name, days=30)

    prescriptions = list_prescriptions()
    my_rx = [p for p in prescriptions if p.get('patient_name','').lower() == patient_name.lower()]

    lab_reports = list_lab_reports(patient_name)
    invoices = [i for i in list_invoices() if i.get('patient_name','').lower() == patient_name.lower()]
    plans = list_plans(patient_name=patient_name)
    refs = [r for r in list_referrals() if r.get('patient_name','').lower() == patient_name.lower()]
    announcements = get_active_announcements()

    return {
        "appointments": my_appts,
        "health": {"latest": latest, "score": score, "history": history},
        "prescriptions": my_rx,
        "lab_reports": lab_reports,
        "invoices": invoices,
        "treatment_plans": plans,
        "referrals": refs,
        "announcements": announcements,
    }
