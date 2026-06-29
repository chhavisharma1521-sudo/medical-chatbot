import os
import json
import re
from datetime import datetime, date, timedelta


def compute_patient_risk(patient_name: str) -> dict:
    """Score 0-100 risk based on health metrics + appointment history."""
    from app.health_tracking import get_latest, compute_health_score
    from app.appointments import list_appointments

    latest = get_latest(patient_name)
    health_score = compute_health_score(latest)
    all_appts = list_appointments()
    my_appts = [a for a in all_appts if a.get('patient_name','').lower() == patient_name.lower()]

    risk_factors = []
    risk_score = 0

    # Health metric risks
    bp = latest.get('blood_pressure')
    if bp:
        s, d = bp['value_1'], bp.get('value_2') or 80
        if s >= 140 or d >= 90:
            risk_score += 25; risk_factors.append(f"High BP ({s}/{d} mmHg)")
        elif s >= 130:
            risk_score += 10; risk_factors.append(f"Elevated BP ({s}/{d} mmHg)")

    bs = latest.get('blood_sugar')
    if bs and bs['value_1'] > 125:
        risk_score += 20; risk_factors.append(f"High blood sugar ({bs['value_1']} mg/dL)")

    hr = latest.get('heart_rate')
    if hr and (hr['value_1'] < 50 or hr['value_1'] > 110):
        risk_score += 15; risk_factors.append(f"Abnormal heart rate ({hr['value_1']} bpm)")

    sl = latest.get('sleep')
    if sl and sl['value_1'] < 5:
        risk_score += 10; risk_factors.append(f"Poor sleep ({sl['value_1']} hrs)")

    wi = latest.get('water_intake')
    if wi and wi['value_1'] < 4:
        risk_score += 5; risk_factors.append(f"Low water intake ({wi['value_1']} glasses)")

    # Appointment history risks
    if my_appts:
        cancelled = [a for a in my_appts if a.get('status') == 'Cancelled']
        cancel_rate = len(cancelled) / len(my_appts)
        if cancel_rate > 0.5:
            risk_score += 15; risk_factors.append(f"High cancellation rate ({int(cancel_rate*100)}%)")

        # Last appointment date
        dates = [a.get('appointment_date','') for a in my_appts if a.get('appointment_date')]
        if dates:
            last = max(dates)
            days_since = (date.today() - date.fromisoformat(last)).days
            if days_since > 180:
                risk_score += 10; risk_factors.append(f"No visit in {days_since} days")
    else:
        risk_score += 5; risk_factors.append("No appointment history")

    risk_score = min(risk_score, 100)
    if risk_score >= 60:     level = "High"
    elif risk_score >= 30:   level = "Moderate"
    else:                    level = "Low"

    return {
        "patient_name": patient_name,
        "risk_score": risk_score,
        "risk_level": level,
        "risk_factors": risk_factors,
        "health_score": health_score.get('score'),
        "health_grade": health_score.get('grade', 'N/A'),
    }


def generate_weekly_report() -> dict:
    """Generate a clinic summary for the past 7 days using Claude."""
    from app.appointments import list_appointments
    from app.billing import list_invoices, billing_stats
    from app.feedback import get_feedback_stats
    from app.patients import list_patients

    # Gather stats
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    appts = list_appointments()
    week_appts = [a for a in appts if a.get('appointment_date','') >= cutoff]

    b_stats = billing_stats()
    fb_stats = get_feedback_stats()
    patients = list_patients()
    new_patients = [p for p in patients if p.get('created_at','')[:10] >= cutoff]

    summary_data = {
        "period": f"{cutoff} to {date.today().isoformat()}",
        "appointments": {
            "total": len(week_appts),
            "approved": len([a for a in week_appts if a.get('status') == 'Approved']),
            "cancelled": len([a for a in week_appts if a.get('status') == 'Cancelled']),
        },
        "new_patients": len(new_patients),
        "billing": b_stats,
        "avg_rating": fb_stats.get('avg_rating', 0),
        "total_reviews": fb_stats.get('total', 0),
    }

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        prompt = (
            "You are a clinic analytics AI. Generate a concise weekly performance report based on this data.\n"
            f"Data: {json.dumps(summary_data)}\n\n"
            "Respond with JSON:\n"
            '{"headline": "one sentence summary", '
            '"highlights": ["highlight 1", "highlight 2", "highlight 3"], '
            '"concerns": ["concern 1", "concern 2"], '
            '"recommendations": ["action 1", "action 2", "action 3"], '
            '"narrative": "2-3 sentence paragraph summary"}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        ai = json.loads(m.group()) if m else {}
    except Exception as e:
        ai = {"headline": "Report generated", "highlights": [], "concerns": [],
              "recommendations": [], "narrative": str(e)}

    return {**summary_data, "ai": ai, "generated_at": datetime.now().isoformat()}
