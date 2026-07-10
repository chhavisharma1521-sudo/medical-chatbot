import os
import sys
import json
import urllib.request
import urllib.error

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _sender_email() -> str:
    # sender must be a verified sender in Brevo; reuse SMTP_EMAIL which already holds it
    return os.getenv("MAIL_SENDER") or os.getenv("SMTP_EMAIL") or ""


def is_email_configured() -> bool:
    return bool(os.getenv("BREVO_API_KEY") and _sender_email())


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via the Brevo HTTP API (works on Railway, which blocks SMTP).
    Returns True on success, False if not configured or failed."""
    api_key = os.getenv("BREVO_API_KEY", "")
    sender = _sender_email()
    if not api_key or not sender or not to_email:
        return False

    body = {
        "sender": {"name": "MedBot Clinic", "email": sender},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }
    req = urllib.request.Request(
        BREVO_URL,
        data=json.dumps(body).encode(),
        headers={"api-key": api_key, "Content-Type": "application/json", "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = r.status in (200, 201)
        _log(f"[EMAIL] sent OK to {to_email} | subject={subject!r}")
        return ok
    except urllib.error.HTTPError as e:
        _log(f"[EMAIL] FAILED to {to_email} | HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        _log(f"[EMAIL] FAILED to {to_email} | {type(e).__name__}: {e}")
        return False


def invoice_html(inv: dict) -> str:
    """Professional HTML invoice for emailing to the patient."""
    clinic = os.getenv("CLINIC_NAME", "MedBot Clinic")
    items = inv.get("items") or []
    rows = "".join(
        f'<tr><td style="padding:9px 8px;border-bottom:1px solid #eee;font-size:14px">{it.get("desc") or "Service"}</td>'
        f'<td style="padding:9px 8px;border-bottom:1px solid #eee;text-align:right;font-size:14px">₹{float(it.get("amount", 0)):,.0f}</td></tr>'
        for it in items
    ) or '<tr><td style="padding:9px 8px;font-size:14px" colspan="2">—</td></tr>'
    paid = (inv.get("status") == "paid")
    status = ('<span style="background:#E8F5E9;color:#2E7D32;padding:4px 12px;border-radius:20px;font-weight:700;font-size:12px">● PAID</span>'
              if paid else
              '<span style="background:#FFEBEE;color:#C62828;padding:4px 12px;border-radius:20px;font-weight:700;font-size:12px">● UNPAID</span>')

    def money(x):
        try: return f"₹{float(x):,.0f}"
        except: return "₹0"

    tax_rate = float(inv.get("tax_rate", 0) or 0)
    return f"""
    <div style="font-family:Segoe UI,sans-serif;max-width:560px;margin:0 auto;padding:26px;border:1px solid #e2e8f0;border-radius:14px;color:#1A1A2E">
      <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #1565C0;padding-bottom:12px;margin-bottom:16px">
        <div><span style="font-size:26px">⚕️</span>
          <div style="font-size:18px;font-weight:800;color:#1565C0">{clinic}</div></div>
        <div style="text-align:right"><div style="font-weight:700;font-size:15px">INVOICE</div>
          <div style="color:#607D8B;font-size:12.5px">{inv.get('invoice_number','')}</div></div>
      </div>
      <table style="width:100%;font-size:13px;margin-bottom:14px">
        <tr><td style="color:#607D8B;padding:2px 0">Patient</td><td style="text-align:right;font-weight:600">{inv.get('patient_name','')}</td></tr>
        <tr><td style="color:#607D8B;padding:2px 0">Doctor</td><td style="text-align:right">{inv.get('doctor_name','') or '—'}</td></tr>
        <tr><td style="color:#607D8B;padding:2px 0">Date</td><td style="text-align:right">{(inv.get('created_at') or '')[:10]}</td></tr>
        <tr><td style="color:#607D8B;padding:2px 0">Status</td><td style="text-align:right">{status}</td></tr>
      </table>
      <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
        <tr style="background:#F0F4FF"><th style="padding:9px 8px;text-align:left;font-size:12px;color:#607D8B">SERVICE</th>
          <th style="padding:9px 8px;text-align:right;font-size:12px;color:#607D8B">AMOUNT</th></tr>
        {rows}
      </table>
      <table style="width:100%;font-size:13.5px">
        <tr><td style="color:#607D8B;padding:2px 0">Subtotal</td><td style="text-align:right">{money(inv.get('subtotal',0))}</td></tr>
        <tr><td style="color:#607D8B;padding:2px 0">Discount</td><td style="text-align:right">− {money(inv.get('discount',0))}</td></tr>
        <tr><td style="color:#607D8B;padding:2px 0">Tax ({tax_rate:.0f}%)</td><td style="text-align:right">included</td></tr>
        <tr><td style="font-weight:800;font-size:16px;padding-top:8px;border-top:2px solid #1565C0">Total Payable</td>
          <td style="text-align:right;font-weight:800;font-size:16px;padding-top:8px;border-top:2px solid #1565C0;color:#1565C0">{money(inv.get('total',0))}</td></tr>
      </table>
      <p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:20px">Thank you! — {clinic}</p>
    </div>
    """


def appointment_confirmation_html(patient_name, doctor_name, date, time, appt_id=None, clinic="MedBot Clinic") -> str:
    ref = f"""<div style="font-size:13px;margin-top:8px;color:#607D8B">Reference ID: <strong>#{appt_id}</strong></div>""" if appt_id else ""
    return f"""
    <div style="font-family:Segoe UI,sans-serif;max-width:500px;margin:0 auto;padding:28px;border:1px solid #e2e8f0;border-radius:14px">
      <div style="text-align:center;margin-bottom:20px">
        <span style="font-size:36px">✅</span>
        <h2 style="color:#2E7D32;margin:6px 0 2px">{clinic}</h2>
        <p style="color:#607D8B;font-size:13px">Appointment Confirmed</p>
      </div>
      <p style="color:#1A1A2E;font-size:15px">Hi <strong>{patient_name}</strong>,</p>
      <p style="color:#1A1A2E;font-size:14px;line-height:1.6">
        Aapka appointment successfully book ho gaya hai. Details neeche hain:
      </p>
      <div style="background:#E8F5E9;border-radius:12px;padding:18px;margin:16px 0">
        <div style="font-size:14px;margin-bottom:8px">👨‍⚕️ <strong>Doctor:</strong> {doctor_name}</div>
        <div style="font-size:14px;margin-bottom:8px">📅 <strong>Date:</strong> {date}</div>
        <div style="font-size:14px">⏰ <strong>Time:</strong> {time}</div>
        {ref}
      </div>
      <p style="color:#607D8B;font-size:12.5px;line-height:1.6">
        Aapka appointment abhi <strong>Pending</strong> hai — clinic confirm karega toh aapko dobara email milega.
        Please arrive 10 minutes early.
      </p>
      <p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:20px">Stay healthy! — {clinic}</p>
    </div>
    """


def appointment_status_html(patient_name, doctor_name, date, time, status, clinic="MedBot Clinic") -> str:
    approved = status.lower() == "approved"
    color = "#2E7D32" if approved else "#C62828"
    bg = "#E8F5E9" if approved else "#FFEBEE"
    icon = "🎉" if approved else "⚠️"
    heading = "Appointment Approved" if approved else "Appointment Cancelled"
    if approved:
        msg = "Good news! Aapka appointment confirm ho gaya hai. Details neeche hain:"
        footer = "Please arrive 10 minutes early. Reschedule ke liye clinic se contact karein."
    else:
        msg = "Aapka appointment cancel kar diya gaya hai. Details neeche hain:"
        footer = "Agar yeh galti se hua hai ya aap dobara book karna chahte hain, toh clinic se contact karein."
    return f"""
    <div style="font-family:Segoe UI,sans-serif;max-width:500px;margin:0 auto;padding:28px;border:1px solid #e2e8f0;border-radius:14px">
      <div style="text-align:center;margin-bottom:20px">
        <span style="font-size:36px">{icon}</span>
        <h2 style="color:{color};margin:6px 0 2px">{clinic}</h2>
        <p style="color:#607D8B;font-size:13px">{heading}</p>
      </div>
      <p style="color:#1A1A2E;font-size:15px">Hi <strong>{patient_name}</strong>,</p>
      <p style="color:#1A1A2E;font-size:14px;line-height:1.6">{msg}</p>
      <div style="background:{bg};border-radius:12px;padding:18px;margin:16px 0">
        <div style="font-size:14px;margin-bottom:8px">👨‍⚕️ <strong>Doctor:</strong> {doctor_name}</div>
        <div style="font-size:14px;margin-bottom:8px">📅 <strong>Date:</strong> {date}</div>
        <div style="font-size:14px">⏰ <strong>Time:</strong> {time}</div>
      </div>
      <p style="color:#607D8B;font-size:12.5px;line-height:1.6">{footer}</p>
      <p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:20px">Stay healthy! — {clinic}</p>
    </div>
    """


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
