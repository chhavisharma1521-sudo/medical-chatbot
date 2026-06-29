import sqlite3
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path("data/billing.db")


def init_billing_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number  TEXT    NOT NULL UNIQUE,
            patient_name    TEXT    NOT NULL,
            patient_phone   TEXT    DEFAULT '',
            patient_email   TEXT    DEFAULT '',
            doctor_name     TEXT    DEFAULT '',
            appointment_id  INTEGER DEFAULT 0,
            items           TEXT    DEFAULT '[]',
            subtotal        REAL    DEFAULT 0,
            discount        REAL    DEFAULT 0,
            tax_rate        REAL    DEFAULT 0,
            total           REAL    DEFAULT 0,
            status          TEXT    DEFAULT 'unpaid',
            notes           TEXT    DEFAULT '',
            due_date        TEXT    DEFAULT '',
            paid_at         TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _next_invoice_number():
    con = _con()
    row = con.execute("SELECT COUNT(*) as c FROM invoices").fetchone()
    n = (row["c"] or 0) + 1
    con.close()
    return f"INV-{date.today().strftime('%Y%m')}-{n:04d}"


def create_invoice(patient_name, doctor_name="", patient_phone="", patient_email="",
                   appointment_id=0, items=None, discount=0, tax_rate=0,
                   notes="", due_date=""):
    import json
    items = items or []
    subtotal = sum(float(i.get("amount", 0)) for i in items)
    after_discount = subtotal - float(discount)
    total = round(after_discount + after_discount * float(tax_rate) / 100, 2)
    inv_num = _next_invoice_number()
    con = _con()
    cur = con.execute(
        """INSERT INTO invoices
           (invoice_number, patient_name, patient_phone, patient_email, doctor_name,
            appointment_id, items, subtotal, discount, tax_rate, total, notes, due_date)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (inv_num, patient_name, patient_phone, patient_email, doctor_name,
         appointment_id, json.dumps(items), subtotal, discount, tax_rate, total,
         notes, due_date),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM invoices WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_invoices(status=None):
    import json
    con = _con()
    if status:
        rows = con.execute("SELECT * FROM invoices WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM invoices ORDER BY created_at DESC").fetchall()
    con.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["items"] = json.loads(d["items"])
        except: d["items"] = []
        result.append(d)
    return result


def get_invoice(inv_id):
    import json
    con = _con()
    row = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    con.close()
    if not row:
        return None
    d = dict(row)
    try: d["items"] = json.loads(d["items"])
    except: d["items"] = []
    return d


def mark_paid(inv_id):
    con = _con()
    con.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=?",
                (datetime.now().isoformat(), inv_id))
    con.commit()
    con.close()


def delete_invoice(inv_id):
    con = _con()
    con.execute("DELETE FROM invoices WHERE id=?", (inv_id,))
    con.commit()
    con.close()


def billing_stats():
    con = _con()
    rows = con.execute("SELECT status, SUM(total) as amt, COUNT(*) as cnt FROM invoices GROUP BY status").fetchall()
    con.close()
    stats = {"total_revenue": 0, "unpaid": 0, "paid": 0, "unpaid_count": 0, "paid_count": 0, "total_count": 0}
    for r in rows:
        r = dict(r)
        stats["total_count"] += r["cnt"]
        if r["status"] == "paid":
            stats["paid"] = round(r["amt"], 2)
            stats["paid_count"] = r["cnt"]
            stats["total_revenue"] += r["amt"]
        elif r["status"] == "unpaid":
            stats["unpaid"] = round(r["amt"], 2)
            stats["unpaid_count"] = r["cnt"]
    return stats
