import json, secrets, io
from contextlib import asynccontextmanager
from datetime import date, timedelta
from urllib.parse import quote
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, JSONResponse
from fastapi.exceptions import RequestValidationError
import segno
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from . import db, ai, config, checkups as ck
from .schedule import dose_times
from .seed import bootstrap_admin, seed_demo, seed_providers
from .security import hash_pw, check_pw, make_token, require
from .common import family_of, can_view_patient, hidden_from_family
from . import billing, search, consult, assistant

@asynccontextmanager
async def lifespan(_):
    db.init(); bootstrap_admin()
    if config.DEMO_SEED: seed_demo(); seed_providers(); consult.ensure_sample_slots()
    yield

app = FastAPI(title="Medi-Prxn-care", lifespan=lifespan)
app.include_router(billing.router)
app.include_router(search.router)
app.include_router(consult.router)
app.include_router(assistant.router)

@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    """Readable 422s. Echoing the rejected input would crash on NaN/Infinity, so only field and message are returned."""
    parts = []
    for e in exc.errors()[:3]:
        field = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query"))
        parts.append(f"{field}: {e.get('msg', 'invalid')}" if field else str(e.get("msg", "invalid")))
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid request"})

@app.get("/healthz")
def healthz():
    db.q("SELECT 1"); return {"ok": True}
ANY = require("doctor", "patient", "admin")

# ---------- models ----------
class Signup(BaseModel):
    name: str; email: str; password: str; role: str = "patient"; age: int | None = None
class Login(BaseModel):
    email: str; password: str
class FamilyMember(BaseModel):
    name: str; age: int; relation: str; medical_history: str = ""; gender: str = ""; allergies: str = ""
class Register(BaseModel):  # reception / admin
    name: str; age: int; gender: str; family_number: str; history: str = ""; owner_user_id: int | None = None
class Med(BaseModel):
    name: str; dosage: str | None = None; timing: str | None = None; frequency_per_day: int | None = None
    duration_days: int | None = None; cause: str | None = None
class Approve(BaseModel):
    patient_id: int; medicines: list[Med]; next_followup: str | None = None; lab_tests: list[str] = []; document_id: int | None = None
class ManualEntry(BaseModel):
    patient_id: int; medicine: str; doctor: str = ""; cause: str = ""; next_followup: str | None = None
    lab_test: str = ""; lab_result: str = "NA"
class Ask(BaseModel):
    question: str; patient_id: int | None = None

# ---------- auth ----------
@app.post("/auth/signup")
def signup(s: Signup):
    if len(s.password) < 8: raise HTTPException(422, "Password must be at least 8 characters")
    if s.role == "admin": raise HTTPException(403, "Admins are created by existing admins")
    if db.q("SELECT 1 FROM users WHERE email=?", (s.email,)): raise HTTPException(409, "Email already registered")
    uid = db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", (s.name, s.email, hash_pw(s.password), s.role))
    if s.role == "patient":
        db.run("INSERT INTO patients(owner_user_id,name,age,relation,qr_token) VALUES(?,?,?,?,?)",
               (uid, s.name, s.age, "self", secrets.token_urlsafe(16)))
    return {"token": make_token(uid, s.role), "user_id": uid, "role": s.role}

@app.post("/auth/login")
def login(l: Login):
    u = db.q("SELECT * FROM users WHERE email=?", (l.email,), one=True)
    if not u or not check_pw(l.password, u["pw_hash"]): raise HTTPException(401, "Bad credentials")
    return {"token": make_token(u["id"], u["role"]), "user_id": u["id"], "role": u["role"]}

# ---------- patient: family ----------
@app.post("/family")
def add_member(m: FamilyMember, u=Depends(require("patient"))):
    pid = db.run("INSERT INTO patients(owner_user_id,name,age,gender,relation,self_reported_history,allergies,qr_token) VALUES(?,?,?,?,?,?,?,?)",
                 (u["uid"], m.name, m.age, m.gender, m.relation, m.medical_history, m.allergies, secrets.token_urlsafe(16)))
    return {"patient_id": pid}

@app.get("/family")
def list_family(u=Depends(require("patient"))):
    return family_of(u)

@app.put("/family/{pid}")
def update_member(pid: int, m: FamilyMember, u=Depends(require("patient"))):
    p = can_view_patient(u, pid)
    db.run("UPDATE patients SET name=?,age=?,gender=?,relation=?,self_reported_history=?,allergies=? WHERE id=?",
           (m.name, m.age, m.gender, p["relation"] if p["relation"] == "self" else m.relation, m.medical_history, m.allergies, pid))
    return {"ok": True}

@app.delete("/family/{pid}")
def delete_member(pid: int, u=Depends(require("patient"))):
    p = can_view_patient(u, pid)
    if p["relation"] == "self": raise HTTPException(422, "You cannot remove your own profile")
    if db.q("SELECT 1 FROM bookings WHERE patient_id=? LIMIT 1", (pid,)): raise HTTPException(409, "This person has consultation bookings, so the profile is kept for your payment records.")
    for t in ("prescriptions", "documents", "bills", "checkups", "chat_history"):
        db.run(f"DELETE FROM {t} WHERE patient_id=?", (pid,))
    db.run("DELETE FROM patients WHERE id=?", (pid,)); return {"ok": True}

@app.get("/patients/{pid}/qr")
def qr_token(pid: int, u=Depends(ANY)):
    p = can_view_patient(u, pid); return {"qr_payload": f"mediprxn:{p['qr_token']}"}

# ---------- reception ----------
@app.post("/reception/register")
def register(r: Register, u=Depends(require("admin"))):
    pid = db.run("INSERT INTO patients(owner_user_id,name,age,gender,family_number,self_reported_history,qr_token) VALUES(?,?,?,?,?,?,?)",
                 (r.owner_user_id, r.name, r.age, r.gender, r.family_number, r.history, secrets.token_urlsafe(16)))
    return {"patient_id": pid}

# ---------- doctor ----------
def ends_on(m):
    return date.fromisoformat(m["start_date"]) + timedelta(days=m["duration_days"] or 0)

def active_meds(pid):
    return [m for m in db.q("SELECT * FROM prescriptions WHERE patient_id=? ORDER BY start_date", (pid,)) if ends_on(m) >= date.today()]

def upcoming_followups(pid):
    today = date.today().isoformat()
    rows = db.q("SELECT DISTINCT next_followup FROM prescriptions WHERE patient_id=? AND next_followup IS NOT NULL", (pid,))
    return sorted([r for r in rows if r["next_followup"] >= today], key=lambda r: r["next_followup"])

@app.post("/doctor/scan")
def scan(qr: str, u=Depends(require("doctor"))):
    token = qr.strip().removeprefix("mediprxn:").removeprefix("smartprxn:")
    p = db.q("SELECT * FROM patients WHERE qr_token=?", (token,), one=True)
    if not p: raise HTTPException(404, "Unknown QR")
    hist = db.q("SELECT * FROM prescriptions WHERE patient_id=? ORDER BY start_date", (p["id"],))
    family = db.q("SELECT id,name,age,relation,self_reported_history FROM patients WHERE owner_user_id=? AND id!=?", (p["owner_user_id"], p["id"])) if p["owner_user_id"] else []
    return {"patient": p, "active_medicines": active_meds(p["id"]), "history": hist, "family_history": family}

@app.post("/doctor/extract")
async def extract(patient_id: int = Form(...), kind: str = Form(...), transcript: str = Form(None),
                  file: UploadFile | None = File(None), u=Depends(require("doctor"))):
    """kind: voice_note | transcript | case_paper. Returns draft JSON + safety warnings. Nothing is saved as a prescription yet."""
    p = db.q("SELECT * FROM patients WHERE id=?", (patient_id,), one=True)
    if not p: raise HTTPException(404, "Patient not found")
    data = await file.read() if file else None
    try:
        parsed = ai.extract_prescription(text=transcript, file_bytes=data, mime=file.content_type if file else None)
        allergies = [a.strip() for a in (p["allergies"] or "").split(",") if a.strip()] + parsed.get("allergies_mentioned", [])
        warnings = ai.safety_check(active_meds(patient_id), allergies, parsed.get("medicines", []))
    except Exception:
        raise HTTPException(503, "The AI service is busy or at its usage limit. Please wait a minute and try again.")
    doc_id = db.run("INSERT INTO documents(patient_id,kind,extracted_json) VALUES(?,?,?)", (patient_id, kind, json.dumps(parsed)))
    return {"document_id": doc_id, "draft": parsed, "safety_warnings": warnings}

@app.post("/doctor/approve")
def approve(a: Approve, u=Depends(require("doctor"))):
    for m in a.medicines:
        if not (m.dosage and m.duration_days):
            raise HTTPException(422, f"{m.name}: dosage and duration_days required before approval")
    for m in a.medicines:
        db.run("""INSERT INTO prescriptions(patient_id,doctor_id,medicine,dosage,timing,frequency_per_day,duration_days,cause,
                  start_date,next_followup,lab_tests,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (a.patient_id, u["uid"], m.name, m.dosage, m.timing, m.frequency_per_day, m.duration_days, m.cause,
                date.today().isoformat(), a.next_followup, json.dumps(a.lab_tests), "doctor"))
    if a.document_id: db.run("UPDATE documents SET status='approved' WHERE id=?", (a.document_id,))
    return {"saved": len(a.medicines)}

@app.post("/patients/{pid}/privacy")
def privacy(pid: int, private: bool, u=Depends(require("doctor"))):
    db.run("UPDATE patients SET private_from_family=? WHERE id=?", (int(private), pid)); return {"private_from_family": private}

# ---------- patient: manual / upload entry (verify-then-save) ----------
@app.post("/records/manual")
def manual(e: ManualEntry, u=Depends(require("patient"))):
    can_view_patient(u, e.patient_id)
    db.run("INSERT INTO prescriptions(patient_id,medicine,cause,start_date,next_followup,lab_tests,source) VALUES(?,?,?,?,?,?,?)",
           (e.patient_id, e.medicine, e.cause, date.today().isoformat(), e.next_followup, json.dumps([{e.lab_test: e.lab_result}]), "patient_manual"))
    return {"ok": True}

@app.post("/records/extract")
async def patient_extract(patient_id: int = Form(...), kind: str = Form(...), transcript: str = Form(None),
                          file: UploadFile | None = File(None), u=Depends(require("patient"))):
    can_view_patient(u, patient_id)
    data = await file.read() if file else None
    try:
        parsed = ai.extract_prescription(text=transcript, file_bytes=data, mime=file.content_type if file else None)
    except Exception:
        raise HTTPException(503, "The AI service is busy or at its usage limit. Please wait a minute and try again.")
    doc_id = db.run("INSERT INTO documents(patient_id,kind,extracted_json) VALUES(?,?,?)", (patient_id, kind, json.dumps(parsed)))
    return {"document_id": doc_id, "draft": parsed, "needs_input": parsed.get("missing_fields", [])}

@app.post("/records/confirm")
def confirm(a: Approve, u=Depends(require("patient"))):
    can_view_patient(u, a.patient_id)
    for m in a.medicines:
        db.run("INSERT INTO prescriptions(patient_id,medicine,dosage,timing,frequency_per_day,duration_days,cause,start_date,next_followup,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (a.patient_id, m.name, m.dosage, m.timing, m.frequency_per_day, m.duration_days, m.cause, date.today().isoformat(), a.next_followup, "patient_upload"))
    if a.document_id: db.run("UPDATE documents SET status='confirmed' WHERE id=?", (a.document_id,))
    return {"saved": len(a.medicines)}

@app.post("/records/explain")
async def explain(text: str = Form(None), file: UploadFile | None = File(None), u=Depends(require("patient"))):
    """Plain-language explanation of a report. The file and the answer are NOT stored."""
    if not (text or file): raise HTTPException(422, "Paste the report text or choose a file")
    data = await file.read() if file else None
    if data and len(data) > 8_000_000: raise HTTPException(413, "File is too large (8 MB maximum)")
    try:
        return {"explanation": ai.explain_report(text=(text or "")[:20000], file_bytes=data, mime=file.content_type if file else None)}
    except Exception:
        raise HTTPException(503, "Report explanations need the AI service, which is not available right now.")

# ---------- patient: dashboard ----------
def one_mg_link(name): return f"https://www.1mg.com/search/all?name={quote(name)}"

def member_checkups(p):
    if hidden_from_family(p): return ck.evaluate(p["age"], p["gender"], [], db.q("SELECT key,done_on FROM checkups WHERE patient_id=?", (p["id"],)))
    rx = db.q("SELECT medicine,cause FROM prescriptions WHERE patient_id=?", (p["id"],))
    return ck.evaluate(p["age"], p["gender"], rx, db.q("SELECT key,done_on FROM checkups WHERE patient_id=?", (p["id"],)))

@app.get("/dashboard")
def dashboard(u=Depends(require("patient"))):
    out = []
    for p in family_of(u):
        hidden = hidden_from_family(p); meds = []
        for m in ([] if hidden else active_meds(p["id"])):
            end = ends_on(m)
            meds.append({**m, "ends_on": end.isoformat(), "refill_due_in_days": (end - date.today()).days - 3,
                         "dose_times": dose_times(m["frequency_per_day"], m["timing"]), "order_url": one_mg_link(m["medicine"])})
        due = [c for c in member_checkups(p) if c["status"] in ("overdue", "no_record", "due_soon")]
        out.append({"patient": p, "active_medicines": meds, "upcoming_followups": [] if hidden else upcoming_followups(p["id"]),
                    "private": hidden, "checkups_attention": len(due), "checkups_overdue": sum(c["status"] == "overdue" for c in due),
                    "timeline": [] if hidden else db.q("SELECT medicine,dosage,start_date,duration_days FROM prescriptions WHERE patient_id=? ORDER BY start_date DESC", (p["id"],))})
    return out

@app.get("/reminders")
def reminders(u=Depends(require("patient"))):
    """Today's dose schedule for every family member (drives the in-app alarms)."""
    items = []
    for p in family_of(u):
        if hidden_from_family(p): continue
        for m in active_meds(p["id"]):
            for t in dose_times(m["frequency_per_day"], m["timing"]):
                items.append({"time": t, "patient_id": p["id"], "patient": p["name"], "medicine": m["medicine"], "dosage": m["dosage"], "timing": m["timing"]})
    return sorted(items, key=lambda i: (i["time"], i["patient"]))

class CheckupDone(BaseModel):
    patient_id: int; key: str; done_on: str | None = None

@app.get("/checkups")
def checkups(u=Depends(require("patient"))):
    return [{"patient": {"id": p["id"], "name": p["name"], "relation": p["relation"], "age": p["age"]}, "items": member_checkups(p)} for p in family_of(u)]

@app.post("/checkups/done")
def checkup_done(c: CheckupDone, u=Depends(require("patient"))):
    p = can_view_patient(u, c.patient_id)
    if c.key not in {r["key"] for r in member_checkups(p)}: raise HTTPException(422, "Unknown check-up for this person")
    d = c.done_on or date.today().isoformat()
    try: date.fromisoformat(d)
    except ValueError: raise HTTPException(422, "done_on must be YYYY-MM-DD")
    db.run("INSERT INTO checkups(patient_id,key,done_on) VALUES(?,?,?)", (c.patient_id, c.key, d)); return {"ok": True}

@app.get("/order-link")
def order_link(medicine: str, u=Depends(ANY)): return {"url": one_mg_link(medicine)}

# ---------- chatbot ----------
@app.post("/chat")
def chat(a: Ask, u=Depends(ANY)):
    if u["role"] == "patient":
        members = family_of(u)
        if a.patient_id: members = [m for m in members if m["id"] == a.patient_id]
        ctx = {"today": date.today().isoformat(), "members": []}
        for m in members:
            ctx["members"].append({"name": m["name"], "relation": m["relation"], "allergies": m["allergies"],
                "active_medicines": [] if hidden_from_family(m) else active_meds(m["id"]),
                "followups": [] if hidden_from_family(m) else upcoming_followups(m["id"]),
                "checkups_needing_attention": [c["name"] for c in member_checkups(m) if c["status"] in ("overdue", "no_record", "due_soon")],
                "spending_inr": {} if hidden_from_family(m) else billing.member_spend(m["id"])})
    else:
        if not a.patient_id: raise HTTPException(422, "patient_id required for doctor chat")
        p = db.q("SELECT * FROM patients WHERE id=?", (a.patient_id,), one=True)
        ctx = {"today": date.today().isoformat(), "patient": p, "history": db.q("SELECT * FROM prescriptions WHERE patient_id=?", (a.patient_id,))}
    try:
        ans = ai.chat(a.question, ctx)
    except Exception:
        raise HTTPException(503, "The AI service is busy or at its usage limit. Please wait a minute and try again.")
    db.run("INSERT INTO chat_history(user_id,patient_id,question,answer) VALUES(?,?,?,?)", (u["uid"], a.patient_id, a.question, ans))
    return {"answer": ans}

@app.get("/chat/history")
def history(u=Depends(ANY)):
    return db.q("SELECT id,question,answer,created_at FROM chat_history WHERE user_id=? ORDER BY id DESC", (u["uid"],))


# ---------- extras for the frontend ----------
@app.get("/me")
def me(u=Depends(ANY)):
    return db.q("SELECT id,name,email,role FROM users WHERE id=?", (u["uid"],), one=True)

@app.get("/patients/{pid}/qr.svg")
def qr_svg(pid: int, u=Depends(ANY)):
    p = can_view_patient(u, pid)
    buf = io.BytesIO(); segno.make(f"mediprxn:{p['qr_token']}", error="m").save(buf, kind="svg", scale=6, border=1, dark="#1c2b6b")
    return Response(buf.getvalue(), media_type="image/svg+xml")

@app.get("/doctor/patients")
def all_patients(u=Depends(require("doctor", "admin"))):
    return db.q("SELECT id,name,age,gender,relation,family_number,qr_token FROM patients ORDER BY id DESC LIMIT 100")

@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """Always revalidate the app shell so a new version shows up without a hard refresh."""
    r = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css", ".webmanifest")): r.headers["Cache-Control"] = "no-cache"
    return r

app.mount("/", StaticFiles(directory="static", html=True), name="static")
