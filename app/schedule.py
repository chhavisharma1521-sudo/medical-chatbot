import sqlite3
from pathlib import Path

DB_PATH = Path("data/schedule.db")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def init_schedule_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS doctor_availability (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_name TEXT    NOT NULL,
            day_of_week TEXT    NOT NULL,
            start_time  TEXT    NOT NULL,
            end_time    TEXT    NOT NULL,
            slot_mins   INTEGER DEFAULT 30,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS blocked_dates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_name TEXT    NOT NULL,
            blocked_date TEXT   NOT NULL,
            reason      TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def set_availability(doctor_name, day_of_week, start_time, end_time, slot_mins=30):
    con = _con()
    existing = con.execute(
        "SELECT id FROM doctor_availability WHERE doctor_name=? AND day_of_week=? AND is_active=1",
        (doctor_name, day_of_week)
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE doctor_availability SET start_time=?, end_time=?, slot_mins=? WHERE id=?",
            (start_time, end_time, slot_mins, existing["id"])
        )
    else:
        con.execute(
            "INSERT INTO doctor_availability (doctor_name, day_of_week, start_time, end_time, slot_mins) VALUES (?,?,?,?,?)",
            (doctor_name, day_of_week, start_time, end_time, slot_mins)
        )
    con.commit()
    con.close()


def delete_availability(avail_id):
    con = _con()
    con.execute("UPDATE doctor_availability SET is_active=0 WHERE id=?", (avail_id,))
    con.commit()
    con.close()


def get_availability(doctor_name=None):
    con = _con()
    if doctor_name:
        rows = con.execute(
            "SELECT * FROM doctor_availability WHERE doctor_name=? AND is_active=1 ORDER BY doctor_name, day_of_week",
            (doctor_name,)
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM doctor_availability WHERE is_active=1 ORDER BY doctor_name, day_of_week"
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def block_date(doctor_name, blocked_date, reason=""):
    con = _con()
    cur = con.execute(
        "INSERT INTO blocked_dates (doctor_name, blocked_date, reason) VALUES (?,?,?)",
        (doctor_name, blocked_date, reason)
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM blocked_dates WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def get_blocked_dates(doctor_name=None):
    con = _con()
    if doctor_name:
        rows = con.execute(
            "SELECT * FROM blocked_dates WHERE doctor_name=? ORDER BY blocked_date DESC",
            (doctor_name,)
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM blocked_dates ORDER BY blocked_date DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def delete_blocked_date(bid):
    con = _con()
    con.execute("DELETE FROM blocked_dates WHERE id=?", (bid,))
    con.commit()
    con.close()


def list_doctors_with_schedules():
    con = _con()
    rows = con.execute(
        "SELECT DISTINCT doctor_name FROM doctor_availability WHERE is_active=1 ORDER BY doctor_name"
    ).fetchall()
    con.close()
    return [r["doctor_name"] for r in rows]
