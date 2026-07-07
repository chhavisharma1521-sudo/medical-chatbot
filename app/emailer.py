import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def is_email_configured() -> bool:
    return bool(os.getenv("SMTP_EMAIL") and os.getenv("SMTP_PASSWORD"))


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via Gmail SMTP. Returns True on success, False if not configured or failed."""
    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    if not smtp_email or not smtp_password or not to_email:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return True
    except Exception:
        return False


def appointment_reminder_html(patient_name, doctor_name, date, time, clinic="MedBot Clinic") -> str:
    return f"""
    <div style="font-family:Segoe UI,sans-serif;max-width:500px;margin:0 auto;padding:28px;border:1px solid #e2e8f0;border-radius:14px">
      <div style="text-align:center;margin-bottom:20px">
        <span style="font-size:36px">⚕️</span>
        <h2 style="color:#1565C0;margin:6px 0 2px">{clinic}</h2>
        <p style="color:#607D8B;font-size:13px">Appointment Reminder</p>
      </div>
      <p style="color:#1A1A2E;font-size:15px">Hi <strong>{patient_name}</strong>,</p>
      <p style="color:#1A1A2E;font-size:14px;line-height:1.6">
        This is a friendly reminder about your upcoming appointment:
      </p>
      <div style="background:#F0F4FF;border-radius:12px;padding:18px;margin:16px 0">
        <div style="font-size:14px;margin-bottom:8px">👨‍⚕️ <strong>Doctor:</strong> {doctor_name}</div>
        <div style="font-size:14px;margin-bottom:8px">📅 <strong>Date:</strong> {date}</div>
        <div style="font-size:14px">⏰ <strong>Time:</strong> {time}</div>
      </div>
      <p style="color:#607D8B;font-size:12.5px;line-height:1.6">
        Please arrive 10 minutes early. If you need to reschedule, contact the clinic.
      </p>
      <p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:20px">Stay healthy! — {clinic}</p>
    </div>
    """
