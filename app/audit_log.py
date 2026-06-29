import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/audit.db")


def init_audit_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_name  TEXT    NOT NULL,
            admin_email TEXT    DEFAULT '',
            action      TEXT    NOT NULL,
            resource    TEXT    DEFAULT '',
            resource_id TEXT    DEFAULT '',
            details     TEXT    DEFAULT '',
            ip_address  TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def log_action(admin_name, action, resource='', resource_id='', details='',
               admin_email='', ip_address=''):
    con = _con()
    con.execute(
        """INSERT INTO audit_logs
           (admin_name, admin_email, action, resource, resource_id, details, ip_address)
           VALUES (?,?,?,?,?,?,?)""",
        (admin_name, admin_email, action, resource, str(resource_id), details, ip_address),
    )
    con.commit()
    con.close()


def list_logs(limit=200, action_filter='', admin_filter=''):
    con = _con()
    clauses, params = [], []
    if action_filter:
        clauses.append("action LIKE ?"); params.append(f'%{action_filter}%')
    if admin_filter:
        clauses.append("admin_name=?"); params.append(admin_filter)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_audit_stats():
    con = _con()
    total = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    today = datetime.now().strftime('%Y-%m-%d')
    today_count = con.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE created_at LIKE ?", (f'{today}%',)
    ).fetchone()[0]
    by_action = con.execute(
        "SELECT action, COUNT(*) as cnt FROM audit_logs GROUP BY action ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    by_admin = con.execute(
        "SELECT admin_name, COUNT(*) as cnt FROM audit_logs GROUP BY admin_name ORDER BY cnt DESC"
    ).fetchall()
    con.close()
    return {
        "total": total,
        "today": today_count,
        "by_action": [dict(r) for r in by_action],
        "by_admin":  [dict(r) for r in by_admin],
    }
