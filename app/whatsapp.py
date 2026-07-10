import os
import sys
import base64
import urllib.request
import urllib.error
import urllib.parse

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def _clinic_name() -> str:
    return os.getenv("CLINIC_NAME", "MedBot Clinic")


def is_whatsapp_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID")
        and os.getenv("TWILIO_AUTH_TOKEN")
        and os.getenv("TWILIO_WHATSAPP_FROM")
    )


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def _normalize_phone(phone: str) -> str:
    """Return an E.164 number. Assumes India (+91) if no country code given."""
    p = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0"):
        p = p[1:]
    if len(p) == 10:            # bare Indian mobile
        return "+91" + p
    return "+" + p


def send_whatsapp(to_phone: str, body: str) -> bool:
    """Send a WhatsApp message via the Twilio API. Best-effort; returns True on success."""
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_wa = os.getenv("TWILIO_WHATSAPP_FROM", "")   # e.g. whatsapp:+14155238886
    to = _normalize_phone(to_phone)
    if not sid or not token or not from_wa or not to:
        return False
    if not from_wa.startswith("whatsapp:"):
        from_wa = "whatsapp:" + from_wa

    data = urllib.parse.urlencode({
        "From": from_wa,
        "To": "whatsapp:" + to,
        "Body": body,
    }).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(
        TWILIO_URL.format(sid=sid), data=data,
        headers={"Authorization": "Basic " + auth,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = r.status in (200, 201)
        _log(f"[WHATSAPP] sent OK to {to}")
        return ok
    except urllib.error.HTTPError as e:
        _log(f"[WHATSAPP] FAILED to {to} | HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        _log(f"[WHATSAPP] FAILED to {to} | {type(e).__name__}: {e}")
        return False


def appointment_confirmation_text(name, doctor, date, time, appt_id=None) -> str:
    clinic = _clinic_name()
    ref = f"\nRef: #{appt_id}" if appt_id else ""
    return (
        f"*{clinic}* 🏥\n\n"
        f"Hi {name}! ✅ Aapka appointment book ho gaya hai.\n"
        f"👨‍⚕️ Doctor: {doctor}\n📅 Date: {date}\n⏰ Time: {time}{ref}\n\n"
        f"Abhi status Pending hai — confirm hone par aapko message milega.\n\n— {clinic}"
    )


def appointment_status_text(name, doctor, date, time, status) -> str:
    clinic = _clinic_name()
    if status.lower() == "approved":
        head = "🎉 Aapka appointment CONFIRM ho gaya hai!"
    else:
        head = "⚠️ Aapka appointment CANCEL kar diya gaya hai."
    return (
        f"*{clinic}* 🏥\n\n"
        f"Hi {name}! {head}\n"
        f"👨‍⚕️ Doctor: {doctor}\n📅 Date: {date}\n⏰ Time: {time}\n\n— {clinic}"
    )
