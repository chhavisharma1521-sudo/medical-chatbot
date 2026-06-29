import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/referrals.db")


def init_referrals_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS referrals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name        TEXT    NOT NULL,
            patient_phone       TEXT    DEFAULT '',
            referring_doctor    TEXT    NOT NULL,
            referred_to_doctor  TEXT    DEFAULT '',
            referred_to_spec    TEXT    NOT NULL,
            reason              TEXT    NOT NULL,
            urgency             TEXT    DEFAULT 'routine',
            notes               TEXT    DEFAULT '',
            status              TEXT    DEFAULT 'pending',
            appointment_booked  INTEGER DEFAULT 0,
            created_at          TEXT    DEFAULT (datetime('now')),
            updated_at          TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def create_referral(patient_name, referring_doctor, referred_to_spec, reason,
                    patient_phone='', referred_to_doctor='', urgency='routine', notes=''):
    con = _con()
    cur = con.execute(
        """INSERT INTO referrals
           (patient_name, patient_phone, referring_doctor, referred_to_doctor,
            referred_to_spec, reason, urgency, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (patient_name, patient_phone, referring_doctor, referred_to_doctor,
         referred_to_spec, reason, urgency, notes),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM referrals WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_referrals(status=None, doctor=None):
    con = _con()
    clauses, params = [], []
    if status:
        clauses.append("status=?"); params.append(status)
    if doctor:
        clauses.append("(referring_doctor=? OR referred_to_doctor=?)"); params.extend([doctor, doctor])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM referrals {where} ORDER BY created_at DESC", params
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_referral_status(ref_id, status):
    con = _con()
    con.execute("UPDATE referrals SET status=?, updated_at=? WHERE id=?",
                (status, datetime.now().isoformat(), ref_id))
    con.commit()
    con.close()


def delete_referral(ref_id):
    con = _con()
    con.execute("DELETE FROM referrals WHERE id=?", (ref_id,))
    con.commit()
    con.close()


def referral_stats():
    con = _con()
    total = con.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    pending = con.execute("SELECT COUNT(*) FROM referrals WHERE status='pending'").fetchone()[0]
    by_spec = con.execute(
        "SELECT referred_to_spec, COUNT(*) as cnt FROM referrals GROUP BY referred_to_spec ORDER BY cnt DESC LIMIT 8"
    ).fetchall()
    con.close()
    return {"total": total, "pending": pending, "by_spec": [dict(r) for r in by_spec]}
