import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/consultation.db")


def init_consultation_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT UNIQUE NOT NULL,
            patient_name TEXT DEFAULT '',
            patient_email TEXT DEFAULT '',
            doctor_name TEXT DEFAULT '',
            type TEXT DEFAULT 'video',
            status TEXT DEFAULT 'waiting',
            started_at TEXT,
            ended_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            sender_name TEXT NOT NULL,
            sender_role TEXT NOT NULL,
            body TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS secure_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_name TEXT NOT NULL,
            sender_role TEXT NOT NULL,
            recipient_name TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            body TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            thread_id TEXT DEFAULT '',
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT DEFAULT '',
            doctor_name TEXT NOT NULL,
            doctor_specialization TEXT DEFAULT '',
            patient_name TEXT NOT NULL,
            patient_age TEXT DEFAULT '',
            patient_gender TEXT DEFAULT '',
            diagnosis TEXT DEFAULT '',
            medications TEXT NOT NULL,
            instructions TEXT DEFAULT '',
            follow_up TEXT DEFAULT '',
            issued_at TEXT DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


# ── Consultations ─────────────────────────────────────────────

def create_or_get_consultation(room_id, patient_name='', doctor_name='', consult_type='video'):
    con = _con()
    existing = con.execute("SELECT * FROM consultations WHERE room_id=?", (room_id,)).fetchone()
    if existing:
        con.close()
        return dict(existing)
    con.execute(
        "INSERT INTO consultations (room_id, patient_name, doctor_name, type) VALUES (?,?,?,?)",
        (room_id, patient_name, doctor_name, consult_type),
    )
    con.commit()
    row = con.execute("SELECT * FROM consultations WHERE room_id=?", (room_id,)).fetchone()
    con.close()
    return dict(row)


def update_consultation_status(room_id, status):
    con = _con()
    ts = datetime.now().isoformat()
    if status == 'active':
        con.execute("UPDATE consultations SET status=?, started_at=? WHERE room_id=?", (status, ts, room_id))
    elif status == 'ended':
        con.execute("UPDATE consultations SET status=?, ended_at=? WHERE room_id=?", (status, ts, room_id))
    else:
        con.execute("UPDATE consultations SET status=? WHERE room_id=?", (status, room_id))
    con.commit()
    con.close()


def update_participant_name(room_id, role, name):
    con = _con()
    col = "patient_name" if role == "patient" else "doctor_name"
    con.execute(f"UPDATE consultations SET {col}=? WHERE room_id=?", (name, room_id))
    con.commit()
    row = con.execute("SELECT * FROM consultations WHERE room_id=?", (room_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_consultations():
    con = _con()
    rows = con.execute("SELECT * FROM consultations ORDER BY created_at DESC LIMIT 100").fetchall()
    con.close()
    return [dict(r) for r in rows]


# ── Live Chat Messages ────────────────────────────────────────

def save_chat_message(room_id, sender_name, sender_role, body):
    con = _con()
    con.execute(
        "INSERT INTO chat_messages (room_id, sender_name, sender_role, body) VALUES (?,?,?,?)",
        (room_id, sender_name, sender_role, body),
    )
    con.commit()
    con.close()


def get_chat_messages(room_id):
    con = _con()
    rows = con.execute(
        "SELECT * FROM chat_messages WHERE room_id=? ORDER BY timestamp ASC", (room_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ── Secure Messages ───────────────────────────────────────────

def save_secure_message(sender_name, sender_role, body, recipient_name='', subject='', thread_id=''):
    con = _con()
    if not thread_id:
        thread_id = f"t_{int(datetime.now().timestamp())}_{sender_name[:4]}"
    cur = con.execute(
        "INSERT INTO secure_messages (sender_name, sender_role, recipient_name, subject, body, thread_id) "
        "VALUES (?,?,?,?,?,?)",
        (sender_name, sender_role, recipient_name, subject, body, thread_id),
    )
    con.commit()
    mid = cur.lastrowid
    row = con.execute("SELECT * FROM secure_messages WHERE id=?", (mid,)).fetchone()
    con.close()
    return dict(row)


def get_secure_messages(user_name=None):
    con = _con()
    if user_name:
        rows = con.execute(
            "SELECT * FROM secure_messages WHERE recipient_name=? OR sender_name=? ORDER BY timestamp DESC",
            (user_name, user_name),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM secure_messages ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def mark_message_read(msg_id):
    con = _con()
    con.execute("UPDATE secure_messages SET is_read=1 WHERE id=?", (msg_id,))
    con.commit()
    con.close()


# ── Prescriptions ─────────────────────────────────────────────

def save_prescription(room_id, doctor_name, patient_name, medications,
                      instructions='', diagnosis='', follow_up='',
                      patient_age='', patient_gender='', doctor_specialization=''):
    con = _con()
    cur = con.execute(
        """INSERT INTO prescriptions
           (room_id, doctor_name, doctor_specialization, patient_name, patient_age, patient_gender,
            diagnosis, medications, instructions, follow_up)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (room_id, doctor_name, doctor_specialization, patient_name, patient_age, patient_gender,
         diagnosis, json.dumps(medications), instructions, follow_up),
    )
    con.commit()
    pid = cur.lastrowid
    row = con.execute("SELECT * FROM prescriptions WHERE id=?", (pid,)).fetchone()
    con.close()
    return dict(row)


def get_prescription(prescription_id):
    con = _con()
    row = con.execute("SELECT * FROM prescriptions WHERE id=?", (prescription_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_prescriptions(room_id=None):
    con = _con()
    if room_id:
        rows = con.execute(
            "SELECT * FROM prescriptions WHERE room_id=? ORDER BY issued_at DESC", (room_id,)
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM prescriptions ORDER BY issued_at DESC LIMIT 100"
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]
