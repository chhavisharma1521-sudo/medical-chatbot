import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/symptoms.db")


def init_symptom_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS symptom_checks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name    TEXT    DEFAULT 'Anonymous',
            symptoms        TEXT    NOT NULL,
            duration        TEXT    DEFAULT '',
            severity        TEXT    DEFAULT 'moderate',
            age             TEXT    DEFAULT '',
            gender          TEXT    DEFAULT '',
            ai_assessment   TEXT    DEFAULT '',
            urgency         TEXT    DEFAULT 'routine',
            suggested_spec  TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def save_symptom_check(patient_name, symptoms, duration="", severity="moderate",
                        age="", gender="", ai_assessment="", urgency="routine",
                        suggested_spec=""):
    con = _con()
    cur = con.execute(
        """INSERT INTO symptom_checks
           (patient_name, symptoms, duration, severity, age, gender, ai_assessment, urgency, suggested_spec)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (patient_name, symptoms, duration, severity, age, gender,
         ai_assessment, urgency, suggested_spec),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM symptom_checks WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def list_symptom_checks(limit=100):
    con = _con()
    rows = con.execute(
        "SELECT * FROM symptom_checks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def analyze_symptoms(symptoms: str, age="", gender="", duration="", severity="moderate") -> dict:
    """Use Claude to triage symptoms. Returns {assessment, urgency, suggested_spec, advice}."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        context = []
        if age: context.append(f"Age: {age}")
        if gender: context.append(f"Gender: {gender}")
        if duration: context.append(f"Duration: {duration}")
        if severity: context.append(f"Severity: {severity}")
        ctx_str = ", ".join(context) if context else "Not provided"

        prompt = (
            "You are a medical triage assistant. Assess the following symptoms and provide guidance.\n"
            f"Patient context: {ctx_str}\n"
            f"Symptoms: {symptoms}\n\n"
            "Respond ONLY with JSON in this exact format:\n"
            '{"assessment": "brief plain-language explanation", '
            '"urgency": "emergency|urgent|soon|routine", '
            '"suggested_spec": "specialty name", '
            '"advice": ["tip1", "tip2", "tip3"], '
            '"warning_signs": ["sign1", "sign2"]}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"assessment": raw, "urgency": "routine", "suggested_spec": "General Physician",
                "advice": [], "warning_signs": []}
    except Exception as e:
        return {"assessment": f"Unable to analyze: {e}", "urgency": "routine",
                "suggested_spec": "General Physician", "advice": [], "warning_signs": []}
