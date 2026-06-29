import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/lab_reports.db")
UPLOADS_DIR = Path("data/lab_uploads")


def init_lab_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS lab_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name    TEXT    NOT NULL,
            report_type     TEXT    DEFAULT 'General',
            filename        TEXT    NOT NULL,
            file_path       TEXT    NOT NULL,
            ai_summary      TEXT    DEFAULT '',
            key_findings    TEXT    DEFAULT '[]',
            status          TEXT    DEFAULT 'pending',
            notes           TEXT    DEFAULT '',
            uploaded_at     TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def save_lab_report(patient_name, report_type, filename, file_path,
                    ai_summary="", key_findings=None, notes=""):
    con = _con()
    cur = con.execute(
        """INSERT INTO lab_reports
           (patient_name, report_type, filename, file_path, ai_summary, key_findings, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (patient_name, report_type, filename, file_path,
         ai_summary, json.dumps(key_findings or []), notes),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM lab_reports WHERE id=?", (nid,)).fetchone()
    con.close()
    return _parse(dict(row))


def update_lab_analysis(report_id, ai_summary, key_findings=None, status="analyzed"):
    con = _con()
    con.execute(
        "UPDATE lab_reports SET ai_summary=?, key_findings=?, status=? WHERE id=?",
        (ai_summary, json.dumps(key_findings or []), status, report_id)
    )
    con.commit()
    con.close()


def list_lab_reports(patient_name=None):
    con = _con()
    if patient_name:
        rows = con.execute(
            "SELECT * FROM lab_reports WHERE patient_name=? ORDER BY uploaded_at DESC",
            (patient_name,)
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM lab_reports ORDER BY uploaded_at DESC").fetchall()
    con.close()
    return [_parse(dict(r)) for r in rows]


def get_lab_report(report_id):
    con = _con()
    row = con.execute("SELECT * FROM lab_reports WHERE id=?", (report_id,)).fetchone()
    con.close()
    return _parse(dict(row)) if row else None


def delete_lab_report(report_id):
    con = _con()
    row = con.execute("SELECT file_path FROM lab_reports WHERE id=?", (report_id,)).fetchone()
    if row:
        try:
            Path(row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    con.execute("DELETE FROM lab_reports WHERE id=?", (report_id,))
    con.commit()
    con.close()


def _parse(d):
    try:
        d["key_findings"] = json.loads(d.get("key_findings", "[]"))
    except Exception:
        d["key_findings"] = []
    return d


def analyze_report_text(text: str, patient_name: str, report_type: str) -> dict:
    """Use Claude to analyze lab report text. Returns {summary, key_findings}."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        prompt = (
            f"You are a medical AI assistant. Analyze this {report_type} lab report for patient '{patient_name}'.\n"
            f"Extract key findings, flag any abnormal values, and provide a brief plain-language summary.\n"
            f"Format your response as JSON: {{\"summary\": \"...\", \"key_findings\": [\"finding1\", \"finding2\", ...]}}\n\n"
            f"Lab Report Text:\n{text[:4000]}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # Extract JSON from response
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
            return result
        return {"summary": raw, "key_findings": []}
    except Exception as e:
        return {"summary": f"Analysis unavailable: {e}", "key_findings": []}
