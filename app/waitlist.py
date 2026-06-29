import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/waitlist.db")


def init_waitlist_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name    TEXT    NOT NULL,
            patient_phone   TEXT    DEFAULT '',
            patient_email   TEXT    DEFAULT '',
            doctor_name     TEXT    NOT NULL,
            specialization  TEXT    DEFAULT '',
            preferred_date  TEXT    DEFAULT '',
            preferred_time  TEXT    DEFAULT '',
            reason          TEXT    DEFAULT '',
            priority        TEXT    DEFAULT 'normal',
            status          TEXT    DEFAULT 'waiting',
            notes           TEXT    DEFAULT '',
            notified_at     TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def add_to_waitlist(patient_name, doctor_name, patient_phone='', patient_email='',
                    specialization='', preferred_date='', preferred_time='',
                    reason='', priority='normal'):
    con = _con()
    pos = con.execute(
        "SELECT COUNT(*) FROM waitlist WHERE doctor_name=? AND status='waiting'", (doctor_name,)
    ).fetchone()[0] + 1
    cur = con.execute(
        """INSERT INTO waitlist
           (patient_name, patient_phone, patient_email, doctor_name, specialization,
            preferred_date, preferred_time, reason, priority)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (patient_name, patient_phone, patient_email, doctor_name, specialization,
         preferred_date, preferred_time, reason, priority),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM waitlist WHERE id=?", (nid,)).fetchone()
    con.close()
    return {**dict(row), "position": pos}


def list_waitlist(doctor_name=None, status=None):
    con = _con()
    clauses, params = [], []
    if doctor_name:
        clauses.append("doctor_name=?"); params.append(doctor_name)
    if status:
        clauses.append("status=?"); params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM waitlist {where} ORDER BY priority DESC, created_at ASC", params
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_waitlist_status(wid, status):
    con = _con()
    con.execute("UPDATE waitlist SET status=? WHERE id=?", (status, wid))
    con.commit()
    con.close()


def notify_patient(wid):
    con = _con()
    con.execute("UPDATE waitlist SET notified_at=? WHERE id=?",
                (datetime.now().isoformat(), wid))
    con.commit()
    con.close()


def delete_waitlist_entry(wid):
    con = _con()
    con.execute("DELETE FROM waitlist WHERE id=?", (wid,))
    con.commit()
    con.close()


def waitlist_stats():
    con = _con()
    total = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='waiting'").fetchone()[0]
    by_doctor = con.execute(
        "SELECT doctor_name, COUNT(*) as cnt FROM waitlist WHERE status='waiting' GROUP BY doctor_name ORDER BY cnt DESC"
    ).fetchall()
    con.close()
    return {"total_waiting": total, "by_doctor": [dict(r) for r in by_doctor]}
