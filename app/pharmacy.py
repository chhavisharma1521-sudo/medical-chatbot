import sqlite3
import json
import os
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path("data/pharmacy.db")


def init_pharmacy_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS medicines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            generic_name    TEXT    DEFAULT '',
            category        TEXT    DEFAULT 'General',
            manufacturer    TEXT    DEFAULT '',
            unit            TEXT    DEFAULT 'tablets',
            stock_qty       REAL    DEFAULT 0,
            min_stock       REAL    DEFAULT 10,
            unit_price      REAL    DEFAULT 0,
            expiry_date     TEXT    DEFAULT '',
            location        TEXT    DEFAULT '',
            description     TEXT    DEFAULT '',
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT    DEFAULT (datetime('now')),
            updated_at      TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            type        TEXT    NOT NULL,
            quantity    REAL    NOT NULL,
            notes       TEXT    DEFAULT '',
            created_by  TEXT    DEFAULT 'admin',
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def add_medicine(name, generic_name='', category='General', manufacturer='',
                 unit='tablets', stock_qty=0, min_stock=10, unit_price=0,
                 expiry_date='', location='', description=''):
    con = _con()
    cur = con.execute(
        """INSERT INTO medicines
           (name, generic_name, category, manufacturer, unit, stock_qty,
            min_stock, unit_price, expiry_date, location, description)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (name, generic_name, category, manufacturer, unit, stock_qty,
         min_stock, unit_price, expiry_date, location, description),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM medicines WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_medicines(low_stock_only=False, category=None):
    con = _con()
    clauses = ["is_active=1"]
    params = []
    if low_stock_only:
        clauses.append("stock_qty <= min_stock")
    if category:
        clauses.append("category=?"); params.append(category)
    where = "WHERE " + " AND ".join(clauses)
    rows = con.execute(
        f"SELECT * FROM medicines {where} ORDER BY name ASC", params
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_stock(medicine_id, quantity_change, movement_type='adjustment',
                 notes='', created_by='admin'):
    con = _con()
    con.execute(
        "UPDATE medicines SET stock_qty = stock_qty + ?, updated_at=? WHERE id=?",
        (quantity_change, datetime.now().isoformat(), medicine_id)
    )
    con.execute(
        "INSERT INTO stock_movements (medicine_id, type, quantity, notes, created_by) VALUES (?,?,?,?,?)",
        (medicine_id, movement_type, quantity_change, notes, created_by)
    )
    con.commit()
    row = con.execute("SELECT * FROM medicines WHERE id=?", (medicine_id,)).fetchone()
    con.close()
    return dict(row)


def delete_medicine(medicine_id):
    con = _con()
    con.execute("UPDATE medicines SET is_active=0 WHERE id=?", (medicine_id,))
    con.commit()
    con.close()


def pharmacy_stats():
    con = _con()
    total = con.execute("SELECT COUNT(*) FROM medicines WHERE is_active=1").fetchone()[0]
    low   = con.execute("SELECT COUNT(*) FROM medicines WHERE is_active=1 AND stock_qty<=min_stock").fetchone()[0]
    today = date.today().isoformat()
    expiring = con.execute(
        "SELECT COUNT(*) FROM medicines WHERE is_active=1 AND expiry_date!='' AND expiry_date<=?",
        (today,)
    ).fetchone()[0]
    value = con.execute(
        "SELECT SUM(stock_qty*unit_price) FROM medicines WHERE is_active=1"
    ).fetchone()[0] or 0
    con.close()
    return {"total": total, "low_stock": low, "expired": expiring, "inventory_value": round(value, 2)}


def check_drug_interaction(drug1: str, drug2: str) -> dict:
    """Use Claude to check drug interactions."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        prompt = (
            f"You are a clinical pharmacist. Check the interaction between '{drug1}' and '{drug2}'.\n"
            "Respond ONLY with JSON:\n"
            '{"severity": "none|minor|moderate|major|contraindicated", '
            '"interaction": "brief description or None if no interaction", '
            '"mechanism": "how the interaction occurs", '
            '"recommendation": "what to do", '
            '"references": ["key point 1", "key point 2"]}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        import re, json
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"severity": "unknown", "interaction": raw, "mechanism": "", "recommendation": "", "references": []}
    except Exception as e:
        return {"severity": "unknown", "interaction": f"Check failed: {e}",
                "mechanism": "", "recommendation": "Consult a pharmacist", "references": []}
