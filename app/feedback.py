import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/feedback.db")


def init_feedback_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS feedback (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name    TEXT    NOT NULL,
            doctor_name     TEXT    DEFAULT '',
            appointment_id  INTEGER DEFAULT 0,
            rating          INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment         TEXT    DEFAULT '',
            category        TEXT    DEFAULT 'general',
            is_public       INTEGER DEFAULT 0,
            is_flagged      INTEGER DEFAULT 0,
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def save_feedback(patient_name, rating, comment="", doctor_name="",
                  appointment_id=0, category="general"):
    con = _con()
    cur = con.execute(
        """INSERT INTO feedback
           (patient_name, doctor_name, appointment_id, rating, comment, category)
           VALUES (?,?,?,?,?,?)""",
        (patient_name, doctor_name, appointment_id, int(rating), comment, category),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM feedback WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_feedback(rating=None, doctor=None, public_only=False):
    con = _con()
    clauses, params = [], []
    if rating:
        clauses.append("rating=?"); params.append(int(rating))
    if doctor:
        clauses.append("doctor_name=?"); params.append(doctor)
    if public_only:
        clauses.append("is_public=1")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM feedback {where} ORDER BY created_at DESC", params
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_feedback_stats():
    con = _con()
    total = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    if total == 0:
        con.close()
        return {"total": 0, "avg_rating": 0, "by_rating": {}, "by_doctor": [], "public_count": 0}
    avg = con.execute("SELECT AVG(rating) FROM feedback").fetchone()[0] or 0
    by_rating_rows = con.execute(
        "SELECT rating, COUNT(*) as cnt FROM feedback GROUP BY rating ORDER BY rating DESC"
    ).fetchall()
    by_doctor_rows = con.execute(
        """SELECT doctor_name, AVG(rating) as avg_r, COUNT(*) as cnt
           FROM feedback WHERE doctor_name != ''
           GROUP BY doctor_name ORDER BY avg_r DESC"""
    ).fetchall()
    public_count = con.execute("SELECT COUNT(*) FROM feedback WHERE is_public=1").fetchone()[0]
    con.close()
    return {
        "total": total,
        "avg_rating": round(avg, 1),
        "by_rating": {str(r["rating"]): r["cnt"] for r in by_rating_rows},
        "by_doctor": [dict(r) for r in by_doctor_rows],
        "public_count": public_count,
    }


def set_public(fid, is_public: bool):
    con = _con()
    con.execute("UPDATE feedback SET is_public=? WHERE id=?", (1 if is_public else 0, fid))
    con.commit()
    con.close()


def flag_feedback(fid, is_flagged: bool):
    con = _con()
    con.execute("UPDATE feedback SET is_flagged=? WHERE id=?", (1 if is_flagged else 0, fid))
    con.commit()
    con.close()


def delete_feedback(fid):
    con = _con()
    con.execute("DELETE FROM feedback WHERE id=?", (fid,))
    con.commit()
    con.close()
