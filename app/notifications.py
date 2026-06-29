import sqlite3
import json
from datetime import datetime, date, timedelta
from pathlib import Path

DB_PATH = Path("data/notifications.db")
APPT_DB = Path("data/appointments.db")


def init_notifications_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            patient_name TEXT DEFAULT '',
            priority TEXT DEFAULT 'normal',
            is_read INTEGER DEFAULT 0,
            is_dismissed INTEGER DEFAULT 0,
            due_date TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS medication_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            medication TEXT NOT NULL,
            dosage TEXT DEFAULT '',
            frequency TEXT DEFAULT '',
            start_date TEXT NOT NULL,
            end_date TEXT DEFAULT '',
            times TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS vaccination_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            vaccine_name TEXT NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


# ── Manual notifications ──────────────────────────────────

def list_notifications(include_dismissed=False):
    con = _con()
    q = "SELECT * FROM notifications WHERE is_dismissed=0 ORDER BY created_at DESC"
    if include_dismissed:
        q = "SELECT * FROM notifications ORDER BY created_at DESC"
    rows = con.execute(q).fetchall()
    con.close()
    return [dict(r) for r in rows]


def create_notification(type_, title, message, patient_name='', priority='normal', due_date=''):
    con = _con()
    cur = con.execute(
        "INSERT INTO notifications (type, title, message, patient_name, priority, due_date) VALUES (?,?,?,?,?,?)",
        (type_, title, message, patient_name, priority, due_date),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def mark_notification_read(nid):
    con = _con()
    con.execute("UPDATE notifications SET is_read=1 WHERE id=?", (nid,))
    con.commit()
    con.close()


def dismiss_notification(nid):
    con = _con()
    con.execute("UPDATE notifications SET is_dismissed=1, is_read=1 WHERE id=?", (nid,))
    con.commit()
    con.close()


# ── Medication schedules ──────────────────────────────────

def list_medication_schedules(active_only=True):
    con = _con()
    q = "SELECT * FROM medication_schedules WHERE is_active=1 ORDER BY created_at DESC" if active_only \
        else "SELECT * FROM medication_schedules ORDER BY created_at DESC"
    rows = con.execute(q).fetchall()
    con.close()
    return [dict(r) for r in rows]


def add_medication_schedule(patient_name, medication, dosage='', frequency='',
                            start_date='', end_date='', times=None, notes=''):
    con = _con()
    cur = con.execute(
        "INSERT INTO medication_schedules (patient_name, medication, dosage, frequency, start_date, end_date, times, notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (patient_name, medication, dosage, frequency, start_date, end_date,
         json.dumps(times or []), notes),
    )
    con.commit()
    mid = cur.lastrowid
    row = con.execute("SELECT * FROM medication_schedules WHERE id=?", (mid,)).fetchone()
    con.close()
    return dict(row)


def deactivate_medication_schedule(mid):
    con = _con()
    con.execute("UPDATE medication_schedules SET is_active=0 WHERE id=?", (mid,))
    con.commit()
    con.close()


# ── Vaccination schedules ─────────────────────────────────

def list_vaccination_schedules():
    con = _con()
    rows = con.execute("SELECT * FROM vaccination_schedules ORDER BY due_date ASC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def add_vaccination_schedule(patient_name, vaccine_name, due_date, notes=''):
    today = date.today().isoformat()
    status = 'overdue' if due_date < today else 'pending'
    con = _con()
    cur = con.execute(
        "INSERT INTO vaccination_schedules (patient_name, vaccine_name, due_date, status, notes) VALUES (?,?,?,?,?)",
        (patient_name, vaccine_name, due_date, status, notes),
    )
    con.commit()
    vid = cur.lastrowid
    row = con.execute("SELECT * FROM vaccination_schedules WHERE id=?", (vid,)).fetchone()
    con.close()
    return dict(row)


def complete_vaccination(vid):
    con = _con()
    con.execute("UPDATE vaccination_schedules SET status='completed' WHERE id=?", (vid,))
    con.commit()
    con.close()


def delete_vaccination(vid):
    con = _con()
    con.execute("DELETE FROM vaccination_schedules WHERE id=?", (vid,))
    con.commit()
    con.close()


# ── Smart auto-generated notifications from appointments ──

def _appt_con():
    if not APPT_DB.exists():
        return None
    c = sqlite3.connect(str(APPT_DB))
    c.row_factory = sqlite3.Row
    return c


def get_upcoming_appointment_alerts(days_ahead=3):
    """Appointments in the next `days_ahead` days."""
    con = _appt_con()
    if not con:
        return []
    today = date.today()
    cutoff = (today + timedelta(days=days_ahead)).isoformat()
    rows = con.execute(
        "SELECT * FROM appointments WHERE appointment_date BETWEEN ? AND ? AND status != 'Cancelled' ORDER BY appointment_date, appointment_time",
        (today.isoformat(), cutoff),
    ).fetchall()
    con.close()
    alerts = []
    for r in rows:
        r = dict(r)
        appt_date = r.get('appointment_date', '')
        delta_days = (date.fromisoformat(appt_date) - today).days if appt_date else 99
        if delta_days == 0:
            when, priority = 'Today', 'urgent'
        elif delta_days == 1:
            when, priority = 'Tomorrow', 'high'
        else:
            when, priority = f'In {delta_days} days', 'normal'
        alerts.append({
            'id': f"appt-{r['id']}",
            'type': 'appointment',
            'priority': priority,
            'title': f"Upcoming: {r['patient_name']} → {r['doctor_name']}",
            'message': f"{when} ({appt_date}) at {r.get('appointment_time','')} · {r.get('specialization','')}",
            'patient_name': r['patient_name'],
            'due_date': appt_date,
            'status': r['status'],
            'payment_status': r['payment_status'],
            'appt_id': r['id'],
        })
    return alerts


def get_followup_reminders():
    """Appointments whose date has passed (status Approved) — possible follow-up needed."""
    con = _appt_con()
    if not con:
        return []
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    thirty_ago = (date.today() - timedelta(days=30)).isoformat()
    rows = con.execute(
        "SELECT * FROM appointments WHERE appointment_date BETWEEN ? AND ? AND status='Approved' ORDER BY appointment_date DESC",
        (thirty_ago, yesterday),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_health_checkup_reminders():
    """Patients who have no appointment in the last 90 days."""
    con = _appt_con()
    if not con:
        return []
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    # Patients with last appointment older than cutoff
    rows = con.execute(
        """SELECT patient_name, patient_phone, MAX(appointment_date) as last_appt
           FROM appointments
           GROUP BY patient_name
           HAVING last_appt < ?
           ORDER BY last_appt ASC
           LIMIT 30""",
        (cutoff,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_overdue_medications():
    """Medication schedules that are past their end_date and still active."""
    schedules = list_medication_schedules(active_only=True)
    today = date.today().isoformat()
    overdue = []
    for s in schedules:
        end = s.get('end_date', '')
        if end and end < today:
            overdue.append({**s, 'overdue': True})
    return overdue


def get_overdue_vaccinations():
    con = _con()
    today = date.today().isoformat()
    # Update status for overdue ones
    con.execute("UPDATE vaccination_schedules SET status='overdue' WHERE due_date < ? AND status='pending'", (today,))
    con.commit()
    rows = con.execute(
        "SELECT * FROM vaccination_schedules WHERE status='overdue' ORDER BY due_date ASC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_notification_summary():
    upcoming   = get_upcoming_appointment_alerts(days_ahead=3)
    followups  = get_followup_reminders()
    checkups   = get_health_checkup_reminders()
    overdue_v  = get_overdue_vaccinations()
    overdue_m  = get_overdue_medications()
    manual     = list_notifications()
    unread_manual = sum(1 for n in manual if not n['is_read'])

    urgent = sum(1 for a in upcoming if a['priority'] == 'urgent')
    urgent += len(overdue_v)
    urgent += len(overdue_m)

    return {
        'total': len(upcoming) + len(followups) + len(checkups) + len(overdue_v) + len(overdue_m) + len(manual),
        'urgent': urgent,
        'unread': unread_manual + len(upcoming) + len(overdue_v) + len(overdue_m),
        'upcoming_appointments': len(upcoming),
        'followup_reminders': len(followups),
        'checkup_reminders': len(checkups),
        'overdue_vaccinations': len(overdue_v),
        'overdue_medications': len(overdue_m),
    }
