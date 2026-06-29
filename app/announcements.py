import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/announcements.db")


def init_announcements_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS announcements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            body        TEXT    NOT NULL,
            category    TEXT    DEFAULT 'general',
            priority    TEXT    DEFAULT 'normal',
            target      TEXT    DEFAULT 'all',
            is_active   INTEGER DEFAULT 1,
            created_by  TEXT    DEFAULT 'admin',
            expires_at  TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def create_announcement(title, body, category="general", priority="normal",
                         target="all", created_by="admin", expires_at=""):
    con = _con()
    cur = con.execute(
        """INSERT INTO announcements (title, body, category, priority, target, created_by, expires_at)
           VALUES (?,?,?,?,?,?,?)""",
        (title, body, category, priority, target, created_by, expires_at),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM announcements WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_announcements(active_only=True):
    con = _con()
    if active_only:
        rows = con.execute(
            "SELECT * FROM announcements WHERE is_active=1 ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def deactivate_announcement(aid):
    con = _con()
    con.execute("UPDATE announcements SET is_active=0 WHERE id=?", (aid,))
    con.commit()
    con.close()


def delete_announcement(aid):
    con = _con()
    con.execute("DELETE FROM announcements WHERE id=?", (aid,))
    con.commit()
    con.close()


# Public endpoint — no auth required (patients can see active announcements)
def get_active_announcements():
    return list_announcements(active_only=True)
