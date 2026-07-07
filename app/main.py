import os
import shutil
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.rag import answer
from app.logger import init_db, log_query, log_upload, DB_PATH, _extract_topics
from app.powerbi import push_to_powerbi
from app.forgot_password import init_reset_table, create_reset_token, verify_and_reset_password, send_reset_email
from app.auth import (
    init_admin_db, register_user, login_user, get_user_by_id, list_users,
    delete_user, decode_token, count_admins,
)
from app.patients import init_patients_db, save_patient, list_patients, get_patient_by_email
from app.appointments import (
    init_appointments_db, book_appointment, list_appointments, DOCTORS, TIME_SLOTS,
    update_status, update_payment_status, reschedule, appt_stats,
)
from app.health_tracking import (
    init_health_db, add_metric, get_history, get_latest,
    list_patients_with_metrics, delete_metric_entry, compute_health_score,
    METRIC_CONFIG,
)
from app.notifications import (
    init_notifications_db, list_notifications, create_notification,
    mark_notification_read, dismiss_notification,
    list_medication_schedules, add_medication_schedule, deactivate_medication_schedule,
    list_vaccination_schedules, add_vaccination_schedule, complete_vaccination, delete_vaccination,
    get_upcoming_appointment_alerts, get_followup_reminders, get_health_checkup_reminders,
    get_overdue_medications, get_overdue_vaccinations, get_notification_summary,
)
from app.consultation import (
    init_consultation_db, create_or_get_consultation, update_consultation_status,
    update_participant_name, list_consultations,
    save_chat_message, get_chat_messages,
    save_secure_message, get_secure_messages, mark_message_read,
    save_prescription, get_prescription, list_prescriptions,
)
from app.billing import (
    init_billing_db, create_invoice, list_invoices, get_invoice,
    mark_paid, delete_invoice, billing_stats,
)
from app.schedule import (
    init_schedule_db, set_availability, delete_availability, get_availability,
    block_date, get_blocked_dates, delete_blocked_date, list_doctors_with_schedules,
    DAYS,
)
from app.lab_reports import (
    init_lab_db, save_lab_report, update_lab_analysis,
    list_lab_reports, get_lab_report, delete_lab_report,
    analyze_report_text, UPLOADS_DIR,
)
from app.announcements import (
    init_announcements_db, create_announcement, list_announcements,
    deactivate_announcement, delete_announcement, get_active_announcements,
)
from app.symptom_checker import (
    init_symptom_db, save_symptom_check, list_symptom_checks, analyze_symptoms,
)
from app.feedback import (
    init_feedback_db, save_feedback, list_feedback,
    get_feedback_stats, set_public, flag_feedback, delete_feedback,
)
from app.treatment_plans import (
    init_treatment_db, create_plan, list_plans, get_plan,
    update_plan_status, delete_plan, add_milestone, toggle_milestone,
)
from app.audit_log import init_audit_db, log_action, list_logs, get_audit_stats
from app.waitlist import (
    init_waitlist_db, add_to_waitlist, list_waitlist,
    update_waitlist_status, notify_patient, delete_waitlist_entry, waitlist_stats,
)
from app.referrals import (
    init_referrals_db, create_referral, list_referrals,
    update_referral_status, delete_referral, referral_stats,
)
from app.pharmacy import (
    init_pharmacy_db, add_medicine, list_medicines, update_stock,
    delete_medicine, pharmacy_stats, check_drug_interaction,
)
from app.patient_portal import (
    init_patient_portal_db, register_patient, login_patient,
    verify_patient_token, get_patient_data, list_patient_accounts,
)
from app.ai_tools import compute_patient_risk, generate_weekly_report


# ── WebSocket managers ─────────────────────────────────────────

class SignalingManager:
    """Relay WebRTC signaling messages between peers in a room."""
    def __init__(self):
        self.rooms: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, room_id: str, role: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        existing_roles = list(self.rooms[room_id].keys())
        self.rooms[room_id][role] = ws
        # Notify new peer if others are already present (they should create the offer)
        if existing_roles:
            await ws.send_json({"type": "peer-present", "peers": existing_roles})
            for er in existing_roles:
                try:
                    await self.rooms[room_id][er].send_json({"type": "peer-joined", "role": role})
                except Exception:
                    pass

    def disconnect(self, room_id: str, role: str):
        if room_id in self.rooms:
            self.rooms[room_id].pop(role, None)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def relay(self, room_id: str, sender_role: str, message: dict):
        if room_id not in self.rooms:
            return
        for role, ws in self.rooms[room_id].items():
            if role != sender_role:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    async def broadcast(self, room_id: str, message: dict):
        if room_id not in self.rooms:
            return
        for ws in self.rooms[room_id].values():
            try:
                await ws.send_json(message)
            except Exception:
                pass


class ChatManager:
    """Broadcast live chat messages to all WebSocket clients in a room."""
    def __init__(self):
        self.rooms: dict[str, list[WebSocket]] = {}

    async def connect(self, room_id: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append(ws)

    def disconnect(self, room_id: str, ws: WebSocket):
        if room_id in self.rooms:
            try:
                self.rooms[room_id].remove(ws)
            except ValueError:
                pass

    async def broadcast(self, room_id: str, message: dict):
        if room_id not in self.rooms:
            return
        dead = []
        for ws in self.rooms[room_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room_id, ws)


signaling_manager = SignalingManager()
chat_manager = ChatManager()

DATA_DIR = Path("data")
STATIC_DIR = Path("static")


bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(exist_ok=True)
    init_db()
    init_admin_db()
    init_reset_table()
    init_patients_db()
    init_appointments_db()
    init_consultation_db()
    init_notifications_db()
    init_health_db()
    init_billing_db()
    init_schedule_db()
    init_lab_db()
    init_announcements_db()
    init_symptom_db()
    init_feedback_db()
    init_treatment_db()
    init_audit_db()
    init_waitlist_db()
    init_referrals_db()
    init_pharmacy_db()
    init_patient_portal_db()
    yield


app = FastAPI(title="RAG Medical Chatbot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Routes that already log their own (richer) audit entries — middleware skips these to avoid duplicates
_MANUAL_AUDIT_PREFIXES = (
    "/admin/treatment-plans", "/admin/waitlist", "/admin/referrals", "/admin/pharmacy",
)


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """Automatically record every admin write-action (create/update/delete) in the audit log."""
    response = await call_next(request)
    try:
        path = request.url.path
        if (request.method in ("POST", "PATCH", "PUT", "DELETE")
                and path.startswith("/admin/")
                and response.status_code < 400
                and not path.startswith(_MANUAL_AUDIT_PREFIXES)):
            admin_name = "admin"
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                payload = decode_token(auth.split(" ", 1)[1])
                if payload:
                    u = get_user_by_id(int(payload["sub"]))
                    if u:
                        admin_name = u.get("name", "admin")
            action = {"POST": "CREATE", "PATCH": "UPDATE", "PUT": "UPDATE", "DELETE": "DELETE"}[request.method]
            resource = path.replace("/admin/", "").strip("/")
            log_action(admin_name, action, resource, "", f"{request.method} {path}")
    except Exception:
        pass
    return response


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    reply: str


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "portal.html"))


@app.get("/chat")
async def chat_page():
    return FileResponse(str(STATIC_DIR / "chat.html"))


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        start = time.time()
        reply = answer(req.message.strip(), req.history)
        elapsed_ms = int((time.time() - start) * 1000)

        question = req.message.strip()
        topics = _extract_topics(question)
        timestamp = datetime.now().isoformat()

        log_query(question, elapsed_ms, len(reply))

        # Push to Power BI in background — does not delay response
        background_tasks.add_task(
            push_to_powerbi, timestamp, question, elapsed_ms, len(reply), topics
        )

        return ChatResponse(reply=reply)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        error = str(e)
        if "does not exist" in error or "Collection" in error:
            raise HTTPException(
                status_code=503,
                detail="Knowledge base not ready. Please run: python ingest.py",
            )
        raise HTTPException(status_code=500, detail=error)


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".txt", ".pdf"}:
        raise HTTPException(status_code=400, detail="Only .txt and .pdf files are supported")
    dest = DATA_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    log_upload(file.filename)

    # Extract text and auto-index into the vector DB so the chatbot learns from it immediately
    text = ""
    try:
        if suffix == ".txt":
            text = dest.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            import pypdf
            reader = pypdf.PdfReader(str(dest))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        text = ""

    chunks_added = 0
    if text.strip():
        try:
            from app.rag import add_document_to_kb
            chunks_added = add_document_to_kb(text, file.filename)
        except Exception:
            chunks_added = 0

    if chunks_added:
        return {"message": f"Uploaded '{file.filename}' and added {chunks_added} knowledge points. The chatbot can now use it!"}
    return {"message": f"Uploaded '{file.filename}', but no readable text was found to index."}


@app.get("/analytics")
async def analytics():
    """JSON endpoint — connect Power BI via Web connector for near-real-time refresh."""
    if not DB_PATH.exists():
        return JSONResponse({"queries": [], "uploads": []})

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    queries = [dict(r) for r in con.execute(
        "SELECT timestamp, question, response_time_ms, response_length, topics "
        "FROM query_logs ORDER BY timestamp DESC LIMIT 500"
    ).fetchall()]

    uploads = [dict(r) for r in con.execute(
        "SELECT timestamp, filename, file_type FROM upload_logs ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()]

    con.close()
    return JSONResponse({"queries": queries, "uploads": uploads})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/knowledge-base/stats")
async def knowledge_base_stats(_=Depends(require_auth)):
    """Vector DB / chatbot knowledge stats — how much data the chatbot can use."""
    from app.rag import kb_stats
    stats = kb_stats()
    # add upload count from analytics
    upload_count = 0
    if DB_PATH.exists():
        con = sqlite3.connect(str(DB_PATH))
        try:
            upload_count = con.execute("SELECT COUNT(*) FROM upload_logs").fetchone()[0]
        except Exception:
            pass
        con.close()
    stats["uploaded_files"] = upload_count
    return stats


@app.get("/payment")
async def payment_page():
    return FileResponse(str(STATIC_DIR / "payment.html"))


@app.get("/patient-info")
async def patient_info_page():
    return FileResponse(str(STATIC_DIR / "patient-info.html"))


@app.get("/intake")
async def intake_page():
    return FileResponse(str(STATIC_DIR / "intake.html"))


@app.get("/appointments")
async def appointments_page():
    return FileResponse(str(STATIC_DIR / "appointments.html"))


@app.get("/api/doctors")
async def get_doctors():
    return DOCTORS


@app.post("/api/book")
async def api_book(data: dict):
    aid = book_appointment(data)
    return {"id": aid, "message": "Appointment booked successfully"}


@app.get("/admin/appointments")
async def admin_appointments(_=Depends(require_auth)):
    return list_appointments()


@app.get("/admin/appointments/stats")
async def admin_appt_stats(_=Depends(require_auth)):
    return appt_stats()


@app.get("/api/time-slots")
async def get_time_slots():
    return TIME_SLOTS


class StatusUpdate(BaseModel):
    status: str

class PaymentUpdate(BaseModel):
    payment_status: str

class RescheduleRequest(BaseModel):
    date: str
    time: str
    notes: str = ""


@app.patch("/admin/appointments/{appt_id}/approve")
async def appt_approve(appt_id: int, _=Depends(require_auth)):
    if not update_status(appt_id, "Approved"):
        raise HTTPException(status_code=400, detail="Invalid status")
    return {"message": "Appointment approved"}


@app.patch("/admin/appointments/{appt_id}/cancel")
async def appt_cancel(appt_id: int, _=Depends(require_auth)):
    if not update_status(appt_id, "Cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    return {"message": "Appointment cancelled"}


@app.patch("/admin/appointments/{appt_id}/reschedule")
async def appt_reschedule(appt_id: int, req: RescheduleRequest, _=Depends(require_auth)):
    reschedule(appt_id, req.date, req.time, req.notes)
    return {"message": "Appointment rescheduled"}


@app.patch("/admin/appointments/{appt_id}/payment")
async def appt_payment(appt_id: int, req: PaymentUpdate, _=Depends(require_auth)):
    if not update_payment_status(appt_id, req.payment_status):
        raise HTTPException(status_code=400, detail="Invalid payment status")
    return {"message": "Payment status updated"}


@app.get("/login")
async def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.get("/admin-login")
async def admin_login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.get("/admin")
async def admin_page():
    return FileResponse(str(STATIC_DIR / "admin.html"))


# ── Auth routes ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    password: str


class LoginRequest(BaseModel):
    identifier: str   # email or phone
    password: str


@app.get("/auth/setup-status")
async def setup_status():
    """Tells the login page whether an admin already exists (signup should be locked)."""
    return {"admin_exists": count_admins() > 0}


class AdminRecoveryRequest(BaseModel):
    secret_key: str


@app.post("/auth/who-is-admin")
async def who_is_admin(req: AdminRecoveryRequest):
    """Recovery: list existing admin emails. Requires ADMIN_SECRET_KEY."""
    expected = os.getenv("ADMIN_SECRET_KEY", "")
    if not expected or req.secret_key != expected:
        raise HTTPException(status_code=403, detail="Invalid secret key")
    from app.auth import list_admin_emails
    return {"admins": list_admin_emails()}


@app.post("/auth/reset-admins")
async def reset_admins(req: AdminRecoveryRequest):
    """Recovery: wipe all admin accounts so a fresh admin can register. Requires ADMIN_SECRET_KEY."""
    expected = os.getenv("ADMIN_SECRET_KEY", "")
    if not expected or req.secret_key != expected:
        raise HTTPException(status_code=403, detail="Invalid secret key")
    from app.auth import delete_all_admins
    n = delete_all_admins()
    return {"message": f"Cleared {n} admin account(s). You can now register a new admin at /admin-login."}


@app.post("/auth/register")
async def auth_register(req: RegisterRequest):
    # First-admin pattern: once one admin exists, public signup is closed.
    if count_admins() > 0:
        raise HTTPException(
            status_code=403,
            detail="Admin registration is closed. Please contact the administrator.",
        )
    try:
        result = register_user(
            name=req.name,
            email=req.email.strip() or None,
            phone=req.phone.strip() or None,
            password=req.password,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    try:
        result = login_user(req.identifier.strip(), req.password)
        try:
            log_action(result.get("name", "admin"), "LOGIN", "auth", "", "Admin logged in")
        except Exception:
            pass
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/auth/me")
async def auth_me(user=Depends(require_auth)):
    return user


class ForgotPasswordRequest(BaseModel):
    identifier: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@app.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request):
    try:
        result = create_reset_token(req.identifier.strip())
        base_url = str(request.base_url).rstrip("/")
        email_sent = send_reset_email(result["email"], result["name"], result["token"], base_url)
        reset_url = f"{base_url}/login?token={result['token']}"
        if email_sent:
            return {"message": f"Reset link sent to {result['email']}"}
        else:
            return {"message": "Reset link generated", "reset_url": reset_url}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    try:
        return verify_and_reset_password(req.token, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Admin-only routes ─────────────────────────────────────────

@app.get("/admin/users")
async def admin_users(_=Depends(require_auth)):
    return list_users()


@app.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, current_user=Depends(require_auth)):
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    delete_user(user_id)
    return {"message": "User deleted"}


@app.post("/patient/register")
async def patient_register(data: dict):
    pid = save_patient(data)
    return {"id": pid, "message": "Registered successfully"}


@app.get("/admin/patients")
async def admin_patients(_=Depends(require_auth)):
    patients = list_patients()
    existing_emails = {(p.get("email") or "").lower() for p in patients if p.get("email")}
    # Merge in portal accounts that aren't already in the patients table
    for acc in list_patient_accounts():
        email = (acc.get("email") or "").lower()
        if email and email in existing_emails:
            continue
        patients.append({
            "name": acc.get("name", ""),
            "email": acc.get("email", ""),
            "phone": acc.get("phone", ""),
            "registered_at": acc.get("created_at", ""),
            "source": "portal",
        })
    return patients


@app.get("/consultation")
async def consultation_page():
    return FileResponse(str(STATIC_DIR / "consultation.html"))


@app.get("/messages")
async def messages_page():
    return FileResponse(str(STATIC_DIR / "messages.html"))


@app.get("/prescription-view")
async def prescription_view_page():
    return FileResponse(str(STATIC_DIR / "prescription_view.html"))


# ── WebSocket: WebRTC signaling ───────────────────────────────

@app.websocket("/ws/signal/{room_id}/{role}")
async def ws_signal(websocket: WebSocket, room_id: str, role: str):
    await signaling_manager.connect(room_id, role, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            data["from_role"] = role
            await signaling_manager.relay(room_id, role, data)
    except WebSocketDisconnect:
        signaling_manager.disconnect(room_id, role)
        await signaling_manager.broadcast(room_id, {"type": "peer-disconnected", "role": role})


# ── WebSocket: live chat ──────────────────────────────────────

@app.websocket("/ws/chat/{room_id}")
async def ws_chat(websocket: WebSocket, room_id: str):
    await chat_manager.connect(room_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                save_chat_message(room_id, data.get("sender", ""), data.get("role", ""), data.get("text", ""))
            await chat_manager.broadcast(room_id, data)
    except WebSocketDisconnect:
        chat_manager.disconnect(room_id, websocket)


# ── REST: consultations ───────────────────────────────────────

class JoinRequest(BaseModel):
    room_id: str
    name: str
    role: str
    type: str = "video"


@app.post("/api/consultation/join")
async def consultation_join(req: JoinRequest):
    patient_name = req.name if req.role == "patient" else ""
    doctor_name = req.name if req.role == "doctor" else ""
    c = create_or_get_consultation(req.room_id, patient_name, doctor_name, req.type)
    # Fill in participant name if room already existed and slot was empty
    name_key = "patient_name" if req.role == "patient" else "doctor_name"
    if not c[name_key]:
        c = update_participant_name(req.room_id, req.role, req.name) or c
    return c


@app.get("/api/consultation/{room_id}")
async def get_consultation_api(room_id: str):
    from app.consultation import _con
    con = _con()
    row = con.execute("SELECT * FROM consultations WHERE room_id=?", (room_id,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Room not found")
    return dict(row)


@app.patch("/api/consultation/{room_id}/status")
async def update_consult_status(room_id: str, data: dict):
    update_consultation_status(room_id, data.get("status", ""))
    return {"message": "Updated"}


@app.get("/admin/consultations")
async def admin_consultations(_=Depends(require_auth)):
    return list_consultations()


# ── REST: chat history ────────────────────────────────────────

@app.get("/api/chat-history/{room_id}")
async def chat_history(room_id: str):
    return get_chat_messages(room_id)


# ── REST: secure messages ─────────────────────────────────────

class SecureMessageRequest(BaseModel):
    sender_name: str
    sender_role: str
    recipient_name: str
    subject: str = ""
    body: str
    thread_id: str = ""


@app.post("/api/messages")
async def api_send_message(req: SecureMessageRequest):
    msg = save_secure_message(req.sender_name, req.sender_role, req.body,
                              req.recipient_name, req.subject, req.thread_id)
    return msg


@app.get("/api/messages")
async def api_get_messages(user: str = ""):
    return get_secure_messages(user or None)


@app.patch("/api/messages/{msg_id}/read")
async def api_mark_read(msg_id: int):
    mark_message_read(msg_id)
    return {"message": "Marked as read"}


# ── REST: prescriptions ───────────────────────────────────────

class PrescriptionRequest(BaseModel):
    room_id: str = ""
    doctor_name: str
    doctor_specialization: str = ""
    patient_name: str
    patient_age: str = ""
    patient_gender: str = ""
    diagnosis: str = ""
    medications: list
    instructions: str = ""
    follow_up: str = ""


@app.post("/api/prescriptions")
async def api_issue_prescription(req: PrescriptionRequest):
    p = save_prescription(
        room_id=req.room_id,
        doctor_name=req.doctor_name,
        patient_name=req.patient_name,
        medications=req.medications,
        instructions=req.instructions,
        diagnosis=req.diagnosis,
        follow_up=req.follow_up,
        patient_age=req.patient_age,
        patient_gender=req.patient_gender,
        doctor_specialization=req.doctor_specialization,
    )
    return p


@app.get("/api/prescriptions/{prescription_id}")
async def api_get_prescription(prescription_id: int):
    p = get_prescription(prescription_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return p


@app.get("/api/prescriptions")
async def api_list_prescriptions(room_id: str = ""):
    return list_prescriptions(room_id or None)


# ── Health Tracking ───────────────────────────────────────────

class MetricRequest(BaseModel):
    patient_name: str
    metric_type: str
    value_1: float
    value_2: float | None = None
    unit: str = ""
    notes: str = ""
    recorded_at: str = ""


@app.get("/admin/health/config")
async def health_config(_=Depends(require_auth)):
    return METRIC_CONFIG


@app.get("/admin/health/patients")
async def health_patients(_=Depends(require_auth)):
    return list_patients_with_metrics()


@app.get("/admin/health/latest/{patient_name}")
async def health_latest(patient_name: str, _=Depends(require_auth)):
    latest = get_latest(patient_name)
    score = compute_health_score(latest)
    return {"latest": latest, "score": score}


@app.get("/admin/health/history/{patient_name}")
async def health_history(patient_name: str, days: int = 30, _=Depends(require_auth)):
    return get_history(patient_name, days=days)


@app.post("/admin/health/metric")
async def health_add_metric(req: MetricRequest, _=Depends(require_auth)):
    return add_metric(
        req.patient_name, req.metric_type, req.value_1,
        req.value_2, req.unit, req.notes,
        req.recorded_at or None,
    )


@app.delete("/admin/health/metric/{mid}")
async def health_delete_metric(mid: int, _=Depends(require_auth)):
    delete_metric_entry(mid)
    return {"message": "Deleted"}


# ── Notifications ─────────────────────────────────────────────

@app.get("/admin/notifications/summary")
async def notif_summary(_=Depends(require_auth)):
    return get_notification_summary()


@app.get("/admin/notifications/smart")
async def smart_notifications(_=Depends(require_auth)):
    return {
        "upcoming_appointments": get_upcoming_appointment_alerts(days_ahead=3),
        "followup_reminders":    get_followup_reminders(),
        "checkup_reminders":     get_health_checkup_reminders(),
        "overdue_medications":   get_overdue_medications(),
        "overdue_vaccinations":  get_overdue_vaccinations(),
        "manual":                list_notifications(),
    }


class NotifRequest(BaseModel):
    type: str
    title: str
    message: str
    patient_name: str = ""
    priority: str = "normal"
    due_date: str = ""


@app.post("/admin/notifications")
async def create_notif(req: NotifRequest, _=Depends(require_auth)):
    return create_notification(req.type, req.title, req.message, req.patient_name, req.priority, req.due_date)


@app.patch("/admin/notifications/{nid}/read")
async def read_notif(nid: int, _=Depends(require_auth)):
    mark_notification_read(nid)
    return {"message": "Marked as read"}


@app.patch("/admin/notifications/{nid}/dismiss")
async def dismiss_notif(nid: int, _=Depends(require_auth)):
    dismiss_notification(nid)
    return {"message": "Dismissed"}


# ── Medication schedules ──────────────────────────────────────

class MedScheduleRequest(BaseModel):
    patient_name: str
    medication: str
    dosage: str = ""
    frequency: str = ""
    start_date: str
    end_date: str = ""
    times: list = []
    notes: str = ""


@app.get("/admin/medication-schedules")
async def get_med_schedules(_=Depends(require_auth)):
    return list_medication_schedules()


@app.post("/admin/medication-schedules")
async def add_med_schedule(req: MedScheduleRequest, _=Depends(require_auth)):
    return add_medication_schedule(req.patient_name, req.medication, req.dosage,
                                   req.frequency, req.start_date, req.end_date,
                                   req.times, req.notes)


@app.delete("/admin/medication-schedules/{mid}")
async def delete_med_schedule(mid: int, _=Depends(require_auth)):
    deactivate_medication_schedule(mid)
    return {"message": "Deactivated"}


# ── Vaccination schedules ─────────────────────────────────────

class VaccineRequest(BaseModel):
    patient_name: str
    vaccine_name: str
    due_date: str
    notes: str = ""


@app.get("/admin/vaccination-schedules")
async def get_vacc_schedules(_=Depends(require_auth)):
    return list_vaccination_schedules()


@app.post("/admin/vaccination-schedules")
async def add_vacc_schedule(req: VaccineRequest, _=Depends(require_auth)):
    return add_vaccination_schedule(req.patient_name, req.vaccine_name, req.due_date, req.notes)


@app.patch("/admin/vaccination-schedules/{vid}/complete")
async def complete_vacc(vid: int, _=Depends(require_auth)):
    complete_vaccination(vid)
    return {"message": "Marked as completed"}


@app.delete("/admin/vaccination-schedules/{vid}")
async def delete_vacc(vid: int, _=Depends(require_auth)):
    delete_vaccination(vid)
    return {"message": "Deleted"}


@app.get("/admin/analytics")
async def admin_analytics(_=Depends(require_auth)):
    """Protected analytics endpoint for admin panel."""
    if not DB_PATH.exists():
        return {"queries": [], "uploads": []}

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    queries = [dict(r) for r in con.execute(
        "SELECT timestamp, question, response_time_ms, response_length, topics "
        "FROM query_logs ORDER BY timestamp DESC LIMIT 500"
    ).fetchall()]

    uploads = [dict(r) for r in con.execute(
        "SELECT timestamp, filename, file_type FROM upload_logs ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()]

    total = con.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
    avg_ms = con.execute("SELECT AVG(response_time_ms) FROM query_logs").fetchone()[0] or 0

    con.close()
    return {
        "queries": queries,
        "uploads": uploads,
        "stats": {
            "total_queries": total,
            "avg_response_ms": round(avg_ms),
            "total_uploads": len(uploads),
        },
    }


# ── Billing ───────────────────────────────────────────────────

class InvoiceRequest(BaseModel):
    patient_name: str
    doctor_name: str = ""
    patient_phone: str = ""
    patient_email: str = ""
    appointment_id: int = 0
    items: list = []
    discount: float = 0
    tax_rate: float = 0
    notes: str = ""
    due_date: str = ""


@app.get("/admin/billing/stats")
async def get_billing_stats(_=Depends(require_auth)):
    return billing_stats()


@app.get("/admin/billing/invoices")
async def get_invoices(status: str = "", _=Depends(require_auth)):
    return list_invoices(status or None)


@app.post("/admin/billing/invoices")
async def create_inv(req: InvoiceRequest, _=Depends(require_auth)):
    return create_invoice(
        req.patient_name, req.doctor_name, req.patient_phone,
        req.patient_email, req.appointment_id, req.items,
        req.discount, req.tax_rate, req.notes, req.due_date,
    )


@app.get("/admin/billing/invoices/{inv_id}")
async def get_inv(inv_id: int, _=Depends(require_auth)):
    inv = get_invoice(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@app.patch("/admin/billing/invoices/{inv_id}/paid")
async def pay_invoice(inv_id: int, _=Depends(require_auth)):
    mark_paid(inv_id)
    return {"message": "Marked as paid"}


@app.delete("/admin/billing/invoices/{inv_id}")
async def del_invoice(inv_id: int, _=Depends(require_auth)):
    delete_invoice(inv_id)
    return {"message": "Deleted"}


# ── Doctor Schedule ───────────────────────────────────────────

class AvailabilityRequest(BaseModel):
    doctor_name: str
    day_of_week: str
    start_time: str
    end_time: str
    slot_mins: int = 30


class BlockRequest(BaseModel):
    doctor_name: str
    blocked_date: str
    reason: str = ""


@app.get("/admin/schedule/doctors")
async def sched_doctors(_=Depends(require_auth)):
    from app.appointments import DOCTORS
    names = [d["name"] for d in DOCTORS]
    extra = list_doctors_with_schedules()
    all_names = sorted(set(names + extra))
    return all_names


@app.get("/admin/schedule/days")
async def sched_days(_=Depends(require_auth)):
    return DAYS


@app.get("/admin/schedule/availability")
async def sched_availability(doctor: str = "", _=Depends(require_auth)):
    return get_availability(doctor or None)


@app.post("/admin/schedule/availability")
async def sched_set(req: AvailabilityRequest, _=Depends(require_auth)):
    set_availability(req.doctor_name, req.day_of_week, req.start_time, req.end_time, req.slot_mins)
    return {"message": "Availability saved"}


@app.delete("/admin/schedule/availability/{avail_id}")
async def sched_del(avail_id: int, _=Depends(require_auth)):
    delete_availability(avail_id)
    return {"message": "Deleted"}


@app.get("/admin/schedule/blocked")
async def sched_blocked(doctor: str = "", _=Depends(require_auth)):
    return get_blocked_dates(doctor or None)


@app.post("/admin/schedule/blocked")
async def sched_block(req: BlockRequest, _=Depends(require_auth)):
    return block_date(req.doctor_name, req.blocked_date, req.reason)


@app.delete("/admin/schedule/blocked/{bid}")
async def sched_unblock(bid: int, _=Depends(require_auth)):
    delete_blocked_date(bid)
    return {"message": "Unblocked"}


# ── Lab Reports ───────────────────────────────────────────────

@app.get("/admin/lab-reports")
async def get_lab_reports(patient: str = "", _=Depends(require_auth)):
    return list_lab_reports(patient or None)


@app.get("/admin/lab-reports/{report_id}")
async def get_lab_report_detail(report_id: int, _=Depends(require_auth)):
    r = get_lab_report(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return r


@app.post("/admin/lab-reports/upload")
async def upload_lab_report(
    patient_name: str,
    report_type: str = "General",
    notes: str = "",
    file: UploadFile = File(...),
    _=Depends(require_auth),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    dest = UPLOADS_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    with open(dest, "wb") as f:
        import shutil as _sh
        _sh.copyfileobj(file.file, f)

    # Extract text for analysis
    text = ""
    if suffix == ".txt":
        text = dest.read_text(errors="ignore")
    elif suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(dest))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            text = ""

    ai_result = {}
    if text.strip():
        ai_result = analyze_report_text(text, patient_name, report_type)

    report = save_lab_report(
        patient_name=patient_name,
        report_type=report_type,
        filename=file.filename,
        file_path=str(dest),
        ai_summary=ai_result.get("summary", ""),
        key_findings=ai_result.get("key_findings", []),
        notes=notes,
    )
    if ai_result:
        update_lab_analysis(report["id"], ai_result.get("summary", ""),
                            ai_result.get("key_findings", []), "analyzed")
        report = get_lab_report(report["id"])
    return report


@app.delete("/admin/lab-reports/{report_id}")
async def del_lab_report(report_id: int, _=Depends(require_auth)):
    delete_lab_report(report_id)
    return {"message": "Deleted"}


# ── Announcements ─────────────────────────────────────────────

class AnnouncementRequest(BaseModel):
    title: str
    body: str
    category: str = "general"
    priority: str = "normal"
    target: str = "all"
    expires_at: str = ""


@app.get("/api/announcements")
async def public_announcements():
    return get_active_announcements()


@app.get("/admin/announcements")
async def admin_get_announcements(_=Depends(require_auth)):
    return list_announcements(active_only=False)


@app.post("/admin/announcements")
async def admin_create_announcement(req: AnnouncementRequest, user=Depends(require_auth)):
    return create_announcement(
        req.title, req.body, req.category, req.priority,
        req.target, user.get("name", "admin"), req.expires_at,
    )


@app.patch("/admin/announcements/{aid}/deactivate")
async def admin_deactivate_announcement(aid: int, _=Depends(require_auth)):
    deactivate_announcement(aid)
    return {"message": "Deactivated"}


@app.delete("/admin/announcements/{aid}")
async def admin_delete_announcement(aid: int, _=Depends(require_auth)):
    delete_announcement(aid)
    return {"message": "Deleted"}


# ── Symptom Checker ───────────────────────────────────────────

class SymptomRequest(BaseModel):
    patient_name: str = "Anonymous"
    symptoms: str
    duration: str = ""
    severity: str = "moderate"
    age: str = ""
    gender: str = ""


@app.post("/api/symptom-check")
async def public_symptom_check(req: SymptomRequest):
    result = analyze_symptoms(req.symptoms, req.age, req.gender, req.duration, req.severity)
    record = save_symptom_check(
        patient_name=req.patient_name,
        symptoms=req.symptoms,
        duration=req.duration,
        severity=req.severity,
        age=req.age,
        gender=req.gender,
        ai_assessment=result.get("assessment", ""),
        urgency=result.get("urgency", "routine"),
        suggested_spec=result.get("suggested_spec", ""),
    )
    return {**record, "advice": result.get("advice", []), "warning_signs": result.get("warning_signs", [])}


@app.get("/admin/symptom-checks")
async def admin_symptom_checks(_=Depends(require_auth)):
    return list_symptom_checks()


# ── Bulk Export ───────────────────────────────────────────────

@app.get("/admin/export/patients")
async def export_patients(_=Depends(require_auth)):
    from fastapi.responses import StreamingResponse
    import csv, io
    patients = list_patients()
    output = io.StringIO()
    if patients:
        w = csv.DictWriter(output, fieldnames=patients[0].keys())
        w.writeheader()
        w.writerows(patients)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=patients.csv"},
    )


@app.get("/admin/export/appointments")
async def export_appointments(_=Depends(require_auth)):
    from fastapi.responses import StreamingResponse
    import csv, io
    appts = list_appointments()
    output = io.StringIO()
    if appts:
        w = csv.DictWriter(output, fieldnames=appts[0].keys())
        w.writeheader()
        w.writerows(appts)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=appointments.csv"},
    )


@app.get("/admin/export/invoices")
async def export_invoices(_=Depends(require_auth)):
    from fastapi.responses import StreamingResponse
    import csv, io
    invoices = list_invoices()
    output = io.StringIO()
    if invoices:
        flat = [{**{k: v for k, v in inv.items() if k != "items"},
                 "items_count": len(inv.get("items", []))} for inv in invoices]
        w = csv.DictWriter(output, fieldnames=flat[0].keys())
        w.writeheader()
        w.writerows(flat)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"},
    )


# ── Feedback ──────────────────────────────────────────────────

@app.get("/feedback")
async def feedback_page():
    return FileResponse(str(STATIC_DIR / "feedback.html"))


class FeedbackRequest(BaseModel):
    patient_name: str
    rating: int
    comment: str = ""
    doctor_name: str = ""
    appointment_id: int = 0
    category: str = "general"


@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be 1–5")
    return save_feedback(
        req.patient_name, req.rating, req.comment,
        req.doctor_name, req.appointment_id, req.category,
    )


@app.get("/api/feedback/public")
async def public_feedback():
    return list_feedback(public_only=True)


@app.get("/admin/feedback")
async def admin_list_feedback(
    rating: int = 0,
    doctor: str = "",
    _=Depends(require_auth),
):
    return list_feedback(rating or None, doctor or None)


@app.get("/admin/feedback/stats")
async def admin_feedback_stats(_=Depends(require_auth)):
    return get_feedback_stats()


@app.patch("/admin/feedback/{fid}/public")
async def feedback_set_public(fid: int, data: dict, _=Depends(require_auth)):
    set_public(fid, bool(data.get("is_public", True)))
    return {"message": "Updated"}


@app.patch("/admin/feedback/{fid}/flag")
async def feedback_flag(fid: int, data: dict, _=Depends(require_auth)):
    flag_feedback(fid, bool(data.get("is_flagged", True)))
    return {"message": "Updated"}


@app.delete("/admin/feedback/{fid}")
async def admin_delete_feedback(fid: int, _=Depends(require_auth)):
    delete_feedback(fid)
    return {"message": "Deleted"}


# ── Treatment Plans ───────────────────────────────────────────

class PlanRequest(BaseModel):
    patient_name: str
    title: str
    doctor_name: str = ""
    diagnosis: str = ""
    goals: list = []
    medications: list = []
    instructions: str = ""
    start_date: str = ""
    end_date: str = ""
    notes: str = ""

class MilestoneRequest(BaseModel):
    title: str
    due_date: str = ""
    notes: str = ""

@app.get("/admin/treatment-plans")
async def get_plans(patient: str = "", status: str = "", _=Depends(require_auth)):
    return list_plans(patient or None, status or None)

@app.get("/admin/treatment-plans/{plan_id}")
async def get_plan_detail(plan_id: int, _=Depends(require_auth)):
    p = get_plan(plan_id)
    if not p: raise HTTPException(status_code=404, detail="Not found")
    return p

@app.post("/admin/treatment-plans")
async def create_treatment_plan(req: PlanRequest, user=Depends(require_auth)):
    plan = create_plan(req.patient_name, req.title, req.doctor_name, req.diagnosis,
                       req.goals, req.medications, req.instructions,
                       req.start_date, req.end_date, req.notes)
    log_action(user.get("name","admin"), "CREATE_PLAN", "treatment_plan", plan["id"],
               f"Plan '{req.title}' for {req.patient_name}")
    return plan

@app.patch("/admin/treatment-plans/{plan_id}/status")
async def update_plan(plan_id: int, data: dict, user=Depends(require_auth)):
    update_plan_status(plan_id, data.get("status",""))
    log_action(user.get("name","admin"), "UPDATE_PLAN_STATUS", "treatment_plan", plan_id)
    return {"message": "Updated"}

@app.delete("/admin/treatment-plans/{plan_id}")
async def del_plan(plan_id: int, user=Depends(require_auth)):
    delete_plan(plan_id)
    log_action(user.get("name","admin"), "DELETE_PLAN", "treatment_plan", plan_id)
    return {"message": "Deleted"}

@app.post("/admin/treatment-plans/{plan_id}/milestones")
async def add_plan_milestone(plan_id: int, req: MilestoneRequest, _=Depends(require_auth)):
    return add_milestone(plan_id, req.title, req.due_date, req.notes)

@app.patch("/admin/treatment-plans/milestones/{mid}/toggle")
async def toggle_plan_milestone(mid: int, _=Depends(require_auth)):
    toggle_milestone(mid)
    return {"message": "Toggled"}


# ── Audit Log ─────────────────────────────────────────────────

@app.get("/admin/audit/logs")
async def get_audit_logs(action: str = "", admin: str = "", _=Depends(require_auth)):
    return list_logs(action_filter=action, admin_filter=admin)

@app.get("/admin/audit/stats")
async def get_audit_stats_route(_=Depends(require_auth)):
    return get_audit_stats()


# ── Waitlist ──────────────────────────────────────────────────

class WaitlistRequest(BaseModel):
    patient_name: str
    doctor_name: str
    patient_phone: str = ""
    patient_email: str = ""
    specialization: str = ""
    preferred_date: str = ""
    preferred_time: str = ""
    reason: str = ""
    priority: str = "normal"

@app.get("/admin/waitlist")
async def get_waitlist(doctor: str = "", status: str = "waiting", _=Depends(require_auth)):
    return list_waitlist(doctor or None, status or None)

@app.get("/admin/waitlist/stats")
async def get_waitlist_stats(_=Depends(require_auth)):
    return waitlist_stats()

@app.post("/admin/waitlist")
async def add_waitlist(req: WaitlistRequest, user=Depends(require_auth)):
    entry = add_to_waitlist(req.patient_name, req.doctor_name, req.patient_phone,
                            req.patient_email, req.specialization, req.preferred_date,
                            req.preferred_time, req.reason, req.priority)
    log_action(user.get("name","admin"), "ADD_WAITLIST", "waitlist", entry["id"],
               f"{req.patient_name} → {req.doctor_name}")
    return entry

@app.patch("/admin/waitlist/{wid}/status")
async def update_wl_status(wid: int, data: dict, user=Depends(require_auth)):
    update_waitlist_status(wid, data.get("status",""))
    log_action(user.get("name","admin"), "UPDATE_WAITLIST", "waitlist", wid)
    return {"message": "Updated"}

@app.patch("/admin/waitlist/{wid}/notify")
async def notify_wl_patient(wid: int, _=Depends(require_auth)):
    notify_patient(wid)
    return {"message": "Notified"}

@app.delete("/admin/waitlist/{wid}")
async def del_waitlist(wid: int, user=Depends(require_auth)):
    delete_waitlist_entry(wid)
    log_action(user.get("name","admin"), "DELETE_WAITLIST", "waitlist", wid)
    return {"message": "Deleted"}


# ── Referrals ─────────────────────────────────────────────────

class ReferralRequest(BaseModel):
    patient_name: str
    referring_doctor: str
    referred_to_spec: str
    reason: str
    patient_phone: str = ""
    referred_to_doctor: str = ""
    urgency: str = "routine"
    notes: str = ""

@app.get("/admin/referrals")
async def get_referrals(status: str = "", doctor: str = "", _=Depends(require_auth)):
    return list_referrals(status or None, doctor or None)

@app.get("/admin/referrals/stats")
async def get_referral_stats(_=Depends(require_auth)):
    return referral_stats()

@app.post("/admin/referrals")
async def create_ref(req: ReferralRequest, user=Depends(require_auth)):
    ref = create_referral(req.patient_name, req.referring_doctor, req.referred_to_spec,
                          req.reason, req.patient_phone, req.referred_to_doctor,
                          req.urgency, req.notes)
    log_action(user.get("name","admin"), "CREATE_REFERRAL", "referral", ref["id"],
               f"{req.patient_name} → {req.referred_to_spec}")
    return ref

@app.patch("/admin/referrals/{ref_id}/status")
async def update_ref_status(ref_id: int, data: dict, user=Depends(require_auth)):
    update_referral_status(ref_id, data.get("status",""))
    log_action(user.get("name","admin"), "UPDATE_REFERRAL", "referral", ref_id)
    return {"message": "Updated"}

@app.delete("/admin/referrals/{ref_id}")
async def del_referral(ref_id: int, user=Depends(require_auth)):
    delete_referral(ref_id)
    log_action(user.get("name","admin"), "DELETE_REFERRAL", "referral", ref_id)
    return {"message": "Deleted"}


# ── Pharmacy / Medicine ───────────────────────────────────────

class MedicineRequest(BaseModel):
    name: str
    generic_name: str = ""
    category: str = "General"
    manufacturer: str = ""
    unit: str = "tablets"
    stock_qty: float = 0
    min_stock: float = 10
    unit_price: float = 0
    expiry_date: str = ""
    location: str = ""
    description: str = ""

class StockRequest(BaseModel):
    quantity_change: float
    movement_type: str = "adjustment"
    notes: str = ""

class DrugCheckRequest(BaseModel):
    drug1: str
    drug2: str

@app.get("/admin/pharmacy/stats")
async def get_pharmacy_stats(_=Depends(require_auth)):
    return pharmacy_stats()

@app.get("/admin/pharmacy/medicines")
async def get_medicines(low_stock: bool = False, category: str = "", _=Depends(require_auth)):
    return list_medicines(low_stock, category or None)

@app.post("/admin/pharmacy/medicines")
async def add_med(req: MedicineRequest, user=Depends(require_auth)):
    med = add_medicine(req.name, req.generic_name, req.category, req.manufacturer,
                       req.unit, req.stock_qty, req.min_stock, req.unit_price,
                       req.expiry_date, req.location, req.description)
    log_action(user.get("name","admin"), "ADD_MEDICINE", "pharmacy", med["id"], req.name)
    return med

@app.patch("/admin/pharmacy/medicines/{med_id}/stock")
async def update_med_stock(med_id: int, req: StockRequest, user=Depends(require_auth)):
    med = update_stock(med_id, req.quantity_change, req.movement_type, req.notes,
                       user.get("name","admin"))
    log_action(user.get("name","admin"), "UPDATE_STOCK", "pharmacy", med_id,
               f"{req.movement_type}: {req.quantity_change}")
    return med

@app.delete("/admin/pharmacy/medicines/{med_id}")
async def del_med(med_id: int, user=Depends(require_auth)):
    delete_medicine(med_id)
    log_action(user.get("name","admin"), "DELETE_MEDICINE", "pharmacy", med_id)
    return {"message": "Deleted"}

@app.post("/admin/pharmacy/drug-check")
async def drug_check(req: DrugCheckRequest, _=Depends(require_auth)):
    return check_drug_interaction(req.drug1, req.drug2)


# ── Patient Portal ────────────────────────────────────────────

@app.get("/portal")
async def portal_page():
    return FileResponse(str(STATIC_DIR / "portal.html"))

class PatientRegRequest(BaseModel):
    name: str
    email: str
    password: str
    phone: str = ""

class PatientLoginRequest(BaseModel):
    email: str
    password: str

@app.post("/portal/register")
async def portal_register(req: PatientRegRequest):
    try:
        result = register_patient(req.name, req.email, req.password, req.phone)
        # Also create a patient record so the admin Patients list shows this person
        try:
            if not get_patient_by_email(req.email):
                save_patient({"name": req.name, "email": req.email, "phone": req.phone})
        except Exception:
            pass
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/portal/login")
async def portal_login(req: PatientLoginRequest):
    try:
        return login_patient(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

portal_bearer = HTTPBearer(auto_error=False)

def require_patient(creds: HTTPAuthorizationCredentials = Depends(portal_bearer)):
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    patient = verify_patient_token(creds.credentials)
    if not patient:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return patient

@app.get("/portal/me")
async def portal_me(patient=Depends(require_patient)):
    return {"name": patient["name"], "email": patient["email"]}

@app.get("/portal/data")
async def portal_data(patient=Depends(require_patient)):
    return get_patient_data(patient["name"])


@app.get("/portal/profile")
async def portal_get_profile(patient=Depends(require_patient)):
    """Patient's full profile from patients.db (or basics from their account)."""
    rec = get_patient_by_email(patient["email"]) or {}
    rec.setdefault("name", patient.get("name", ""))
    rec.setdefault("email", patient.get("email", ""))
    return rec


class PortalProfileRequest(BaseModel):
    name: str = ""
    age: str = ""
    gender: str = ""
    phone: str = ""
    blood_group: str = ""
    height: str = ""
    weight: str = ""
    medical_conditions: str = ""
    medications: str = ""
    allergies: str = ""
    emergency_contact: str = ""
    symptoms: str = ""


@app.post("/portal/profile")
async def portal_save_profile(req: PortalProfileRequest, patient=Depends(require_patient)):
    """Patient updates their own full profile — saved to patients.db so admin sees full details."""
    data = req.dict()
    data["email"] = patient["email"]          # force their own email (security)
    if not data.get("name"):
        data["name"] = patient["name"]
    pid = save_patient(data)
    return {"message": "Profile saved", "id": pid}


@app.post("/portal/lab-reports/upload")
async def portal_upload_lab(
    report_type: str = "General",
    notes: str = "",
    file: UploadFile = File(...),
    patient=Depends(require_patient),
):
    """Patient uploads their own lab report / document — appears in their portal AND in admin under their name."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Only TXT, PDF, PNG or JPG files allowed")
    patient_name = patient["name"]
    dest = UPLOADS_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    text = ""
    if suffix == ".txt":
        text = dest.read_text(errors="ignore")
    elif suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(dest))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            text = ""

    ai_result = analyze_report_text(text, patient_name, report_type) if text.strip() else {}

    report = save_lab_report(
        patient_name=patient_name,
        report_type=report_type,
        filename=file.filename,
        file_path=str(dest),
        ai_summary=ai_result.get("summary", ""),
        key_findings=ai_result.get("key_findings", []),
        notes="[Patient uploaded] " + notes,
    )
    if ai_result:
        update_lab_analysis(report["id"], ai_result.get("summary", ""),
                            ai_result.get("key_findings", []), "analyzed")
    return {"message": "Report uploaded successfully", "id": report["id"]}


# ── AI Tools ──────────────────────────────────────────────────

@app.get("/admin/ai/risk-scores")
async def get_risk_scores(_=Depends(require_auth)):
    from app.patients import list_patients
    from app.health_tracking import list_patients_with_metrics
    patients = list_patients()
    tracked  = list_patients_with_metrics()
    all_names = list({p["name"] for p in patients} | set(tracked))
    scores = [compute_patient_risk(n) for n in all_names[:50]]
    scores.sort(key=lambda x: x["risk_score"], reverse=True)
    return scores

@app.get("/admin/ai/risk/{patient_name}")
async def get_patient_risk(patient_name: str, _=Depends(require_auth)):
    return compute_patient_risk(patient_name)

@app.get("/admin/ai/weekly-report")
async def get_weekly_report(_=Depends(require_auth)):
    return generate_weekly_report()

@app.get("/admin/analytics/revenue")
async def revenue_analytics(_=Depends(require_auth)):
    from app.billing import _con as billing_con
    con = billing_con()
    monthly = con.execute(
        """SELECT strftime('%Y-%m', created_at) as month,
                  SUM(CASE WHEN status='paid' THEN total ELSE 0 END) as paid,
                  SUM(CASE WHEN status='unpaid' THEN total ELSE 0 END) as unpaid,
                  COUNT(*) as count
           FROM invoices
           GROUP BY month ORDER BY month DESC LIMIT 12"""
    ).fetchall()
    con.close()
    return [dict(r) for r in reversed(monthly)]

@app.get("/admin/analytics/patient-growth")
async def patient_growth(_=Depends(require_auth)):
    from app.patients import _con as pat_con
    con = pat_con()
    monthly = con.execute(
        """SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count
           FROM patients GROUP BY month ORDER BY month DESC LIMIT 12"""
    ).fetchall()
    con.close()
    return [dict(r) for r in reversed(monthly)]

@app.get("/admin/analytics/appointment-heatmap")
async def appt_heatmap(_=Depends(require_auth)):
    import sqlite3 as _sq
    from app.appointments import DB_PATH as APPT_DB
    con = _sq.connect(str(APPT_DB)); con.row_factory = _sq.Row
    rows = con.execute(
        """SELECT strftime('%w', appointment_date) as dow,
                  appointment_time, COUNT(*) as count
           FROM appointments GROUP BY dow, appointment_time"""
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
