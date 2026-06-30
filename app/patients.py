import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/patients.db")


def init_patients_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age TEXT,
            gender TEXT,
            phone TEXT,
            email TEXT,
            blood_group TEXT,
            height TEXT,
            weight TEXT,
            medical_conditions TEXT,
            medications TEXT,
            allergies TEXT,
            emergency_contact TEXT,
            symptoms TEXT,
            registered_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


_FIELDS = ["age", "gender", "phone", "blood_group", "height", "weight",
           "medical_conditions", "medications", "allergies", "emergency_contact", "symptoms"]


def save_patient(data: dict) -> int:
    """Upsert by email: if a patient with this email exists, UPDATE it (only non-empty fields);
    otherwise INSERT a new record. This lets a patient fill/edit their profile without creating duplicates."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    email = (data.get("email") or "").strip()

    existing = None
    if email:
        existing = con.execute(
            "SELECT * FROM patients WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone()

    if existing:
        # Update only fields that are provided (non-empty), keep the rest
        updates, params = [], []
        if data.get("name"):
            updates.append("name=?"); params.append(data["name"])
        for f in _FIELDS:
            if data.get(f) not in (None, ""):
                updates.append(f"{f}=?"); params.append(data[f])
        pid = existing["id"]
        if updates:
            params.append(pid)
            con.execute(f"UPDATE patients SET {', '.join(updates)} WHERE id=?", params)
            con.commit()
        con.close()
        return pid

    cur = con.execute(
        """INSERT INTO patients
           (name,age,gender,phone,email,blood_group,height,weight,
            medical_conditions,medications,allergies,emergency_contact,symptoms,registered_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("name", ""),
            data.get("age", ""),
            data.get("gender", ""),
            data.get("phone", ""),
            data.get("email", ""),
            data.get("blood_group", ""),
            data.get("height", ""),
            data.get("weight", ""),
            data.get("medical_conditions", ""),
            data.get("medications", ""),
            data.get("allergies", ""),
            data.get("emergency_contact", ""),
            data.get("symptoms", ""),
            datetime.now().isoformat(),
        ),
    )
    con.commit()
    pid = cur.lastrowid
    con.close()
    return pid


def get_patient_by_email(email: str) -> dict | None:
    if not email or not DB_PATH.exists():
        return None
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM patients WHERE email=? COLLATE NOCASE", (email,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_patients() -> list[dict]:
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM patients ORDER BY registered_at DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
