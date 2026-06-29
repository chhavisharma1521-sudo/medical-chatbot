import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/appointments.db")

DOCTORS = [
    {"id": 1,  "name": "Dr. Priya Sharma",   "specialization": "Cardiologist",       "experience": 15, "rating": 4.9, "fee": 800,  "color": "#E53935", "patients": 3200},
    {"id": 2,  "name": "Dr. Rahul Mehta",    "specialization": "Neurologist",        "experience": 12, "rating": 4.7, "fee": 700,  "color": "#8E24AA", "patients": 2800},
    {"id": 3,  "name": "Dr. Anjali Singh",   "specialization": "Dermatologist",      "experience": 8,  "rating": 4.8, "fee": 500,  "color": "#F57C00", "patients": 2100},
    {"id": 4,  "name": "Dr. Vikram Patel",   "specialization": "Orthopedic Surgeon", "experience": 20, "rating": 4.9, "fee": 900,  "color": "#1565C0", "patients": 4100},
    {"id": 5,  "name": "Dr. Neha Gupta",     "specialization": "Gynecologist",       "experience": 10, "rating": 4.6, "fee": 550,  "color": "#E91E63", "patients": 1900},
    {"id": 6,  "name": "Dr. Arjun Kumar",    "specialization": "General Physician",  "experience": 6,  "rating": 4.5, "fee": 300,  "color": "#00897B", "patients": 1500},
    {"id": 7,  "name": "Dr. Sunita Reddy",   "specialization": "Pediatrician",       "experience": 14, "rating": 4.8, "fee": 450,  "color": "#F4511E", "patients": 2600},
    {"id": 8,  "name": "Dr. Anil Verma",     "specialization": "ENT Specialist",     "experience": 18, "rating": 4.7, "fee": 550,  "color": "#0277BD", "patients": 3000},
    {"id": 9,  "name": "Dr. Kavya Nair",     "specialization": "Psychiatrist",       "experience": 9,  "rating": 4.6, "fee": 700,  "color": "#6A1B9A", "patients": 1700},
    {"id": 10, "name": "Dr. Rohan Bose",     "specialization": "Ophthalmologist",    "experience": 11, "rating": 4.8, "fee": 500,  "color": "#00695C", "patients": 2200},
    {"id": 11, "name": "Dr. Meera Iyer",     "specialization": "Endocrinologist",    "experience": 13, "rating": 4.7, "fee": 650,  "color": "#AD1457", "patients": 2400},
    {"id": 12, "name": "Dr. Sameer Khan",    "specialization": "Gastroenterologist", "experience": 16, "rating": 4.9, "fee": 750,  "color": "#2E7D32", "patients": 2900},
]

TIME_SLOTS = [
    "09:00 AM","09:30 AM","10:00 AM","10:30 AM","11:00 AM","11:30 AM",
    "02:00 PM","02:30 PM","03:00 PM","03:30 PM","04:00 PM","04:30 PM",
]


def init_appointments_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            patient_phone TEXT,
            patient_email TEXT,
            doctor_id INTEGER NOT NULL,
            doctor_name TEXT NOT NULL,
            specialization TEXT,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'Pending',
            payment_status TEXT DEFAULT 'Unpaid',
            notes TEXT DEFAULT '',
            booked_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    # Migrate existing DB — add new columns if missing
    for col, default in [("payment_status", "'Unpaid'"), ("notes", "''"), ("updated_at", "NULL")]:
        try:
            con.execute(f"ALTER TABLE appointments ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def book_appointment(data: dict) -> int:
    doctor = next((d for d in DOCTORS if d["id"] == int(data.get("doctor_id", 0))), None)
    con = _con()
    cur = con.execute(
        """INSERT INTO appointments
           (patient_name,patient_phone,patient_email,doctor_id,doctor_name,specialization,
            appointment_date,appointment_time,reason,status,payment_status,booked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("patient_name", ""),
            data.get("patient_phone", ""),
            data.get("patient_email", ""),
            data.get("doctor_id", 0),
            doctor["name"] if doctor else data.get("doctor_name", ""),
            doctor["specialization"] if doctor else "",
            data.get("appointment_date", ""),
            data.get("appointment_time", ""),
            data.get("reason", ""),
            "Pending",
            "Unpaid",
            datetime.now().isoformat(),
        ),
    )
    con.commit()
    aid = cur.lastrowid
    con.close()
    return aid


def list_appointments() -> list[dict]:
    if not DB_PATH.exists():
        return []
    con = _con()
    rows = con.execute("SELECT * FROM appointments ORDER BY booked_at DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_appointment(appt_id: int) -> dict | None:
    con = _con()
    row = con.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def update_status(appt_id: int, status: str) -> bool:
    allowed = {"Pending", "Approved", "Cancelled"}
    if status not in allowed:
        return False
    con = _con()
    con.execute(
        "UPDATE appointments SET status=?, updated_at=? WHERE id=?",
        (status, datetime.now().isoformat(), appt_id),
    )
    con.commit()
    con.close()
    return True


def update_payment_status(appt_id: int, payment_status: str) -> bool:
    allowed = {"Unpaid", "Paid", "Refunded"}
    if payment_status not in allowed:
        return False
    con = _con()
    con.execute(
        "UPDATE appointments SET payment_status=?, updated_at=? WHERE id=?",
        (payment_status, datetime.now().isoformat(), appt_id),
    )
    con.commit()
    con.close()
    return True


def reschedule(appt_id: int, new_date: str, new_time: str, notes: str = "") -> bool:
    con = _con()
    con.execute(
        "UPDATE appointments SET appointment_date=?, appointment_time=?, status='Pending', notes=?, updated_at=? WHERE id=?",
        (new_date, new_time, notes, datetime.now().isoformat(), appt_id),
    )
    con.commit()
    con.close()
    return True


def appt_stats() -> dict:
    if not DB_PATH.exists():
        return {"total": 0, "pending": 0, "approved": 0, "cancelled": 0, "paid": 0}
    con = _con()
    total     = con.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    pending   = con.execute("SELECT COUNT(*) FROM appointments WHERE status='Pending'").fetchone()[0]
    approved  = con.execute("SELECT COUNT(*) FROM appointments WHERE status='Approved'").fetchone()[0]
    cancelled = con.execute("SELECT COUNT(*) FROM appointments WHERE status='Cancelled'").fetchone()[0]
    paid      = con.execute("SELECT COUNT(*) FROM appointments WHERE payment_status='Paid'").fetchone()[0]
    con.close()
    return {"total": total, "pending": pending, "approved": approved, "cancelled": cancelled, "paid": paid}
