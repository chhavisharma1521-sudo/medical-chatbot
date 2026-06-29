import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

DB_PATH = Path("data/health_tracking.db")

METRIC_CONFIG = {
    "blood_pressure":  {"unit": "mmHg",    "label": "Blood Pressure",  "icon": "🩸", "dual": True},
    "blood_sugar":     {"unit": "mg/dL",   "label": "Blood Sugar",     "icon": "🍬", "dual": False},
    "weight":          {"unit": "kg",      "label": "Weight",          "icon": "⚖️",  "dual": False},
    "heart_rate":      {"unit": "bpm",     "label": "Heart Rate",      "icon": "❤️",  "dual": False},
    "sleep":           {"unit": "hrs",     "label": "Sleep",           "icon": "😴", "dual": False},
    "water_intake":    {"unit": "glasses", "label": "Water Intake",    "icon": "💧", "dual": False},
}


def init_health_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS health_metrics (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name  TEXT    NOT NULL,
            metric_type   TEXT    NOT NULL,
            value_1       REAL    NOT NULL,
            value_2       REAL,
            unit          TEXT    DEFAULT '',
            notes         TEXT    DEFAULT '',
            recorded_at   TEXT    DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def add_metric(patient_name, metric_type, value_1, value_2=None,
               unit='', notes='', recorded_at=None):
    cfg = METRIC_CONFIG.get(metric_type, {})
    unit = unit or cfg.get("unit", "")
    ts = recorded_at or datetime.now().isoformat()
    con = _con()
    cur = con.execute(
        "INSERT INTO health_metrics "
        "(patient_name, metric_type, value_1, value_2, unit, notes, recorded_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (patient_name, metric_type, value_1, value_2, unit, notes, ts),
    )
    con.commit()
    nid = cur.lastrowid
    row = con.execute("SELECT * FROM health_metrics WHERE id=?", (nid,)).fetchone()
    con.close()
    return dict(row)


def get_history(patient_name, metric_type=None, days=30):
    con = _con()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    if metric_type:
        rows = con.execute(
            "SELECT * FROM health_metrics "
            "WHERE patient_name=? AND metric_type=? AND recorded_at>=? "
            "ORDER BY recorded_at ASC",
            (patient_name, metric_type, cutoff),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM health_metrics "
            "WHERE patient_name=? AND recorded_at>=? "
            "ORDER BY recorded_at ASC",
            (patient_name, cutoff),
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_latest(patient_name):
    """Return {metric_type: row_dict} for the most recent reading of each type."""
    con = _con()
    rows = con.execute(
        """SELECT m.* FROM health_metrics m
           INNER JOIN (
               SELECT metric_type, MAX(recorded_at) AS mx
               FROM health_metrics WHERE patient_name=?
               GROUP BY metric_type
           ) x ON m.metric_type=x.metric_type AND m.recorded_at=x.mx
           WHERE m.patient_name=?""",
        (patient_name, patient_name),
    ).fetchall()
    con.close()
    return {r["metric_type"]: dict(r) for r in rows}


def list_patients_with_metrics():
    con = _con()
    rows = con.execute(
        "SELECT DISTINCT patient_name FROM health_metrics ORDER BY patient_name"
    ).fetchall()
    con.close()
    return [r["patient_name"] for r in rows]


def delete_metric_entry(mid):
    con = _con()
    con.execute("DELETE FROM health_metrics WHERE id=?", (mid,))
    con.commit()
    con.close()


def compute_health_score(latest: dict) -> dict:
    """
    Score each available metric out of 20 and normalise to 100.
    Returns {score, grade, breakdown}.
    """
    breakdown = {}
    total = 0
    possible = 0

    bp = latest.get("blood_pressure")
    if bp:
        s, d = bp["value_1"], bp["value_2"] or 80
        if s <= 120 and d <= 80:                        pts = 20
        elif s <= 129 and d < 80:                       pts = 16
        elif s <= 139 or d <= 89:                       pts = 10
        else:                                            pts = 4
        breakdown["blood_pressure"] = pts; total += pts; possible += 20

    bs = latest.get("blood_sugar")
    if bs:
        v = bs["value_1"]
        if 70 <= v <= 100:   pts = 20
        elif v <= 125:        pts = 12
        else:                 pts = 4
        breakdown["blood_sugar"] = pts; total += pts; possible += 20

    hr = latest.get("heart_rate")
    if hr:
        v = hr["value_1"]
        if 60 <= v <= 100:                  pts = 20
        elif (50 <= v < 60) or (100 < v <= 110): pts = 12
        else:                               pts = 4
        breakdown["heart_rate"] = pts; total += pts; possible += 20

    sl = latest.get("sleep")
    if sl:
        v = sl["value_1"]
        if 7 <= v <= 9:   pts = 20
        elif 6 <= v <= 10: pts = 14
        else:              pts = 6
        breakdown["sleep"] = pts; total += pts; possible += 20

    wi = latest.get("water_intake")
    if wi:
        v = wi["value_1"]
        if v >= 8:    pts = 20
        elif v >= 6:  pts = 14
        else:         pts = 6
        breakdown["water_intake"] = pts; total += pts; possible += 20

    wt = latest.get("weight")
    if wt:
        breakdown["weight"] = None  # no fixed range — include but don't score

    if possible == 0:
        return {"score": None, "grade": "N/A", "breakdown": {}}

    score = round((total / possible) * 100)
    if score >= 85:    grade = "Excellent"
    elif score >= 70:  grade = "Good"
    elif score >= 50:  grade = "Fair"
    else:              grade = "Poor"

    return {"score": score, "grade": grade, "breakdown": breakdown}
