import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/treatment_plans.db")


def init_treatment_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS treatment_plans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name    TEXT    NOT NULL,
            doctor_name     TEXT    DEFAULT '',
            title           TEXT    NOT NULL,
            diagnosis       TEXT    DEFAULT '',
            goals           TEXT    DEFAULT '[]',
            medications     TEXT    DEFAULT '[]',
            instructions    TEXT    DEFAULT '',
            start_date      TEXT    DEFAULT '',
            end_date        TEXT    DEFAULT '',
            status          TEXT    DEFAULT 'active',
            notes           TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now')),
            updated_at      TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS plan_milestones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id     INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            due_date    TEXT    DEFAULT '',
            is_done     INTEGER DEFAULT 0,
            notes       TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _parse(d):
    for k in ('goals', 'medications'):
        try:
            d[k] = json.loads(d.get(k) or '[]')
        except Exception:
            d[k] = []
    return d


def create_plan(patient_name, title, doctor_name='', diagnosis='', goals=None,
                medications=None, instructions='', start_date='', end_date='', notes=''):
    con = _con()
    cur = con.execute(
        """INSERT INTO treatment_plans
           (patient_name, doctor_name, title, diagnosis, goals, medications,
            instructions, start_date, end_date, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (patient_name, doctor_name, title, diagnosis,
         json.dumps(goals or []), json.dumps(medications or []),
         instructions, start_date, end_date, notes),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM treatment_plans WHERE id=?", (nid,)).fetchone()
    con.close()
    return _parse(dict(row))


def list_plans(patient_name=None, status=None):
    con = _con()
    clauses, params = [], []
    if patient_name:
        clauses.append("patient_name=?"); params.append(patient_name)
    if status:
        clauses.append("status=?"); params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM treatment_plans {where} ORDER BY created_at DESC", params
    ).fetchall()
    con.close()
    return [_parse(dict(r)) for r in rows]


def get_plan(plan_id):
    con = _con()
    row = con.execute("SELECT * FROM treatment_plans WHERE id=?", (plan_id,)).fetchone()
    milestones = con.execute(
        "SELECT * FROM plan_milestones WHERE plan_id=? ORDER BY due_date ASC", (plan_id,)
    ).fetchall()
    con.close()
    if not row:
        return None
    d = _parse(dict(row))
    d['milestones'] = [dict(m) for m in milestones]
    return d


def update_plan_status(plan_id, status):
    con = _con()
    con.execute("UPDATE treatment_plans SET status=?, updated_at=? WHERE id=?",
                (status, datetime.now().isoformat(), plan_id))
    con.commit()
    con.close()


def delete_plan(plan_id):
    con = _con()
    con.execute("DELETE FROM plan_milestones WHERE plan_id=?", (plan_id,))
    con.execute("DELETE FROM treatment_plans WHERE id=?", (plan_id,))
    con.commit()
    con.close()


def add_milestone(plan_id, title, due_date='', notes=''):
    con = _con()
    cur = con.execute(
        "INSERT INTO plan_milestones (plan_id, title, due_date, notes) VALUES (?,?,?,?)",
        (plan_id, title, due_date, notes)
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM plan_milestones WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def toggle_milestone(milestone_id):
    con = _con()
    con.execute("UPDATE plan_milestones SET is_done = 1 - is_done WHERE id=?", (milestone_id,))
    con.commit()
    con.close()
