import os
import json
import urllib.request
from datetime import datetime


def push_to_powerbi(timestamp: str, question: str, response_time_ms: int,
                    response_length: int, topics: str):
    url = os.getenv("POWERBI_PUSH_URL", "")
    if not url:
        return  # silently skip if not configured

    payload = json.dumps([{
        "timestamp": timestamp,
        "question": question[:200],          # Power BI row size limit
        "response_time_ms": response_time_ms,
        "response_length": response_length,
        "topics": topics,
    }]).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass  # never block the chat response
