import sqlite3
import re
from datetime import datetime
from pathlib import Path

DB_PATH = Path("analytics.db")

MEDICAL_KEYWORDS = [
    "fever", "pain", "headache", "diabetes", "blood pressure", "heart", "cancer",
    "infection", "allergy", "asthma", "thyroid", "cholesterol", "anxiety", "depression",
    "cold", "flu", "cough", "vomiting", "diarrhea", "skin", "kidney", "liver",
    "pregnancy", "vaccine", "medicine", "drug", "dosage", "surgery", "diet", "vitamin",
]


def _conn():
    return sqlite3.connect(str(DB_PATH))


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS query_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                question        TEXT    NOT NULL,
                response_time_ms INTEGER NOT NULL,
                response_length INTEGER NOT NULL,
                topics          TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS upload_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                filename    TEXT NOT NULL,
                file_type   TEXT NOT NULL
            )
        """)


def _extract_topics(text: str) -> str:
    lower = text.lower()
    found = [kw for kw in MEDICAL_KEYWORDS if kw in lower]
    return ", ".join(found) if found else "general"


def log_query(question: str, response_time_ms: int, response_length: int):
    topics = _extract_topics(question)
    with _conn() as con:
        con.execute(
            "INSERT INTO query_logs (timestamp, question, response_time_ms, response_length, topics) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), question, response_time_ms, response_length, topics),
        )


def log_upload(filename: str):
    file_type = Path(filename).suffix.lower().lstrip(".")
    with _conn() as con:
        con.execute(
            "INSERT INTO upload_logs (timestamp, filename, file_type) VALUES (?,?,?)",
            (datetime.now().isoformat(), filename, file_type),
        )
