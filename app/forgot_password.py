import sqlite3
import secrets
import smtplib
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

DB_PATH = Path("data/admin_users.db")
RESET_EXPIRY_MINUTES = 30


def init_reset_table():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            token      TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()


def _con():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def create_reset_token(identifier: str) -> dict:
    """Find user by email or phone, create a reset token."""
    con = _con()
    user = con.execute(
        "SELECT * FROM admin_users WHERE email=? OR phone=?",
        (identifier, identifier)
    ).fetchone()

    if not user:
        con.close()
        raise ValueError("No account found with that email or phone number")

    email = user["email"] or identifier
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(minutes=RESET_EXPIRY_MINUTES)).isoformat()

    con.execute("DELETE FROM password_resets WHERE email=?", (email,))
    con.execute(
        "INSERT INTO password_resets (email, token, expires_at) VALUES (?,?,?)",
        (email, token, expires)
    )
    con.commit()
    con.close()
    return {"email": email, "token": token, "name": user["name"]}


def verify_and_reset_password(token: str, new_password: str):
    """Verify token and update password."""
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters")

    con = _con()
    row = con.execute(
        "SELECT * FROM password_resets WHERE token=? AND used=0 AND expires_at > ?",
        (token, datetime.now().isoformat())
    ).fetchone()

    if not row:
        con.close()
        raise ValueError("Reset link is invalid or has expired")

    from app.auth import hash_password
    new_hash = hash_password(new_password)
    con.execute(
        "UPDATE admin_users SET password_hash=? WHERE email=?",
        (new_hash, row["email"])
    )
    con.execute("UPDATE password_resets SET used=1 WHERE token=?", (token,))
    con.commit()
    con.close()
    return {"message": "Password reset successfully"}


def send_reset_email(to_email: str, name: str, token: str, base_url: str) -> bool:
    """Send reset email via Gmail SMTP. Returns True if sent, False if SMTP not configured."""
    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_email or not smtp_password:
        return False

    reset_url = f"{base_url}/login?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset Your MedBot Admin Password"
    msg["From"] = smtp_email
    msg["To"] = to_email

    html = f"""
    <div style="font-family:Segoe UI,sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <div style="text-align:center;margin-bottom:24px">
        <span style="font-size:40px">⚕️</span>
        <h2 style="color:#1565C0;margin:8px 0 4px">MedBot Admin</h2>
        <p style="color:#607D8B;font-size:13px">Password Reset Request</p>
      </div>
      <p style="color:#1A1A2E">Hi <strong>{name}</strong>,</p>
      <p style="color:#1A1A2E;margin:12px 0">
        We received a request to reset your password. Click the button below to set a new password.
        This link expires in <strong>30 minutes</strong>.
      </p>
      <div style="text-align:center;margin:28px 0">
        <a href="{reset_url}" style="background:#1565C0;color:#fff;padding:13px 32px;border-radius:10px;
           text-decoration:none;font-weight:600;font-size:15px;display:inline-block">
          Reset Password
        </a>
      </div>
      <p style="color:#607D8B;font-size:12px">
        If you didn't request this, ignore this email — your password won't change.<br>
        Link expires at {(datetime.now() + timedelta(minutes=30)).strftime('%I:%M %p')}.
      </p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return True
    except Exception:
        return False
