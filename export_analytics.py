"""
Run this script to export analytics data to CSV files for Power BI.
Usage: python export_analytics.py
Output: analytics_queries.csv, analytics_uploads.csv
"""

import sqlite3
import csv
from pathlib import Path

DB_PATH = Path("analytics.db")


def export():
    if not DB_PATH.exists():
        print("analytics.db not found. Start the server and send some queries first.")
        return

    con = sqlite3.connect(str(DB_PATH))

    # Export query logs
    queries = con.execute(
        "SELECT id, timestamp, question, response_time_ms, response_length, topics FROM query_logs ORDER BY timestamp"
    ).fetchall()

    with open("analytics_queries.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "question", "response_time_ms", "response_length", "topics"])
        writer.writerows(queries)

    print(f"Exported {len(queries)} query records → analytics_queries.csv")

    # Export upload logs
    uploads = con.execute(
        "SELECT id, timestamp, filename, file_type FROM upload_logs ORDER BY timestamp"
    ).fetchall()

    with open("analytics_uploads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "filename", "file_type"])
        writer.writerows(uploads)

    print(f"Exported {len(uploads)} upload records → analytics_uploads.csv")

    con.close()
    print("\nDone! Open Power BI Desktop → Get Data → Text/CSV → select these files.")


if __name__ == "__main__":
    export()
