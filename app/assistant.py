"""Medi AI Assistant: a one-question-at-a-time health questionnaire for the floating chat window.

Safety design:
1. Emergency warning signs are checked by fixed rules on the server BEFORE any AI call. A match ends the normal flow and
   returns emergency directions. This never depends on the model and is never behind a payment.
2. The assistant gives general information only: no diagnosis, no prescriptions, no medicine doses. Dose-like text in a
   model reply is removed before it reaches the user.
3. Nothing is stored unless the user presses "Save summary". Family health details are used only for the family member
   the user selects for the chat.
Works without a Gemini key through a fixed question flow, so the demo runs offline."""
import json, re, time, logging
from datetime import date
from typing import Literal
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from . import db, ai, config
from .common import can_view_patient, hidden_from_family
from .security import require

log = logging.getLogger("mediprxn.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])

DISCLAIMER = "General information only. This is not a diagnosis and not a substitute for a doctor."
EMERGENCY_NUMBERS = "Call 112 (national emergency number) or 108 (ambulance in most states) now, or go to the nearest hospital emergency department."

# (label, pattern, may be negated, e.g. "no chest pain")
_RULES = [
    ("chest pain", r"chest (pain|pressure|tightness)|pain in (my|the|his|her) chest|heart attack", True),
    ("breathing trouble", r"(can'?t|cannot|unable to|struggling to|difficulty|trouble|hard to|not) breath|short(ness)? of breath|gasping|choking", False),
    ("stroke signs", r"face (is )?droop|slurred speech|sudden (weakness|numbness|confusion)|can'?t (move|lift) (my |his |her |the )?(arm|leg)|\bstroke\b|worst headache", True),
    ("heavy bleeding", r"(severe|heavy|uncontrollable|a lot of) bleeding|bleeding (heavily|a lot|won'?t stop)|(coughing|vomiting|throwing up) (up )?blood", True),
    ("loss of consciousness or fits", r"unconscious|unresponsive|passed out|not waking|seizure|convuls|\bfitting\b|fainted", True),
    ("severe allergic reaction", r"anaphyla|throat (is )?(closing|swelling)|(tongue|lips|face|throat) (is |are )?swell", False),
    ("poisoning or overdose", r"overdose|poison|swallowed (bleach|kerosene|phenyl|pesticide|pills)|too many (pills|tablets)", False),
    ("meningitis signs", r"stiff neck.*fever|fever.*stiff neck", False),
    ("baby in danger", r"(baby|newborn|infant).*(blue|limp|not (breathing|feeding|waking))", False),
]
_SELF_HARM = re.compile(r"suicid|kill myself|end my life|want to die|self[- ]?harm|hurt myself|no reason to live", re.I)
_NEG = re.compile(r"\b(no|not|never|without|denies|don'?t have|doesn'?t have|didn'?t have|free of)\b[^.!?]{0,25}$", re.I)
_RULES = [(l, re.compile(p, re.I), neg) for l, p, neg in _RULES]
_DOSE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|µg|ml|g|iu|units?|tablets?|capsules?|pills?|drops?|teaspoons?|tsp)\b", re.I)


def emergency_check(text):
    """Return an emergency reply dict if the text contains a warning sign, else None."""
    if _SELF_HARM.search(text):
        return {"emergency": True, "kind": "mental_health", "reply":
                "I'm really sorry you're going through this. You deserve support right now. Please call Tele-MANAS on 14416 (free, 24 hours) or call 112 if you are in immediate danger. "
                "If you can, tell someone near you how you feel and stay with them. I can't help with this safely over chat, but you are not alone."}
    for label, rx, may_negate in _RULES:
        for m in rx.finditer(text):
            if may_negate and _NEG.search(text[max(0, m.start() - 30):m.start()]): continue
            return {"emergency": True, "kind": label, "reply":
                    f"What you describe may be an emergency ({label}). {EMERGENCY_NUMBERS} If someone is with you, ask them to stay with you. "
                    "Emergency help is never behind a payment, and I can't continue a routine questionnaire for this."}
    return None


def strip_doses(text):
    """Remove sentences that look like a medicine dose. The assistant must never suggest doses."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    keep = [p for p in parts if not _DOSE.search(p)]
    if len(keep) != len(parts):
        keep.append("I can't suggest medicine doses. A doctor or pharmacist can tell you what is safe for you.")
    return " ".join(keep).strip()


def age_group(age):
    if age is None: return None
    if age < 2: return "infant (under 2)"
    if age < 12: return "child (2 to 11)"
    if age < 18: return "teen (12 to 17)"
    return "adult (18 to 59)" if age < 60 else "senior (60+)"


# ---------- rate limit (per user, in memory) ----------
_hits = defaultdict(deque)
def _limit(uid, n=40, window=600):
    q, now = _hits[uid], time.time()
    while q and q[0] < now - window: q.popleft()
    if len(q) >= n: raise HTTPException(429, "You are sending messages very quickly. Please wait a few minutes.")
    q.append(now)


# ---------- models ----------
class Msg(BaseModel):
    role: Literal["user", "assistant"]; content: str = Field(..., max_length=1500)
class Turn(BaseModel):
    messages: list[Msg] = Field(..., max_length=40); patient_id: int | None = None
class SaveSummary(BaseModel):
    summary: dict; patient_id: int | None = None


def _member(u, pid):
    """Only the family member the user picked for this chat; skipped when the doctor made the records private."""
    if not pid: return None
    p = can_view_patient(u, pid)
    return None if hidden_from_family(p) else p

def _context(p):
    if not p: return {}
    meds = [m["medicine"] for m in db.q("SELECT medicine,start_date,duration_days FROM prescriptions WHERE patient_id=?", (p["id"],))
            if m["start_date"] and date.fromisoformat(m["start_date"]).toordinal() + (m["duration_days"] or 0) >= date.today().toordinal()]
    return {"age_group": age_group(p["age"]), "allergies": p["allergies"] or None, "current_medicines": meds or None}


GREETING = ("Hello, I'm the Medi AI Assistant. I can help you understand a health concern and decide on a sensible next step. "
            "I'm not a doctor and I can't diagnose or prescribe. What would you like help with today?")
STARTERS = ["I have a symptom", "Question about my child", "Help for an older family member", "Understand a medical term"]

@router.get("/start")
def start(u=Depends(require("patient"))):
    return {"reply": GREETING, "quick_replies": STARTERS, "stage": "asking", "emergency": False, "suggest_consult": False, "summary": None, "mode": "gemini" if ai.KEY else "guided"}


# ---------- offline flow ----------
def _offline(users, ctx):
    n = len(users); known_age = ctx.get("age_group")
    steps = ["duration", "severity"] + ([] if known_age else ["age"]) + ["history"]
    if n <= len(steps):
        s = steps[n - 1]
        q = {"duration": ("How long has this been going on?", ["Since today", "2 to 3 days", "About a week", "More than 2 weeks"]),
             "severity": ("How strong is it right now? It's fine to pick the closest.", ["Mild", "Moderate", "Severe"]),
             "age": ("Who is this for? Please choose an age group.", ["Child (under 12)", "Teen", "Adult", "Senior (60+)"]),
             "history": ("Last question: any ongoing conditions, allergies or regular medicines I should know about? Type none if not.", ["None"])}[s]
        return {"reply": q[0], "quick_replies": q[1], "stage": "asking", "suggest_consult": False, "summary": None}
    ans = dict(zip(["concern"] + steps, users))
    sev = "severe" if "sever" in ans["severity"].lower() else "moderate" if "moder" in ans["severity"].lower() else "mild"
    dur = ans["duration"].lower(); long_ = any(k in dur for k in ("week", "month", "2 weeks", "more than"))
    age = known_age or ans.get("age", "")
    risky_age = any(k in age.lower() for k in ("child", "infant", "senior", "under 12", "60"))
    consult = sev != "mild" or long_ or risky_age
    guidance = ["Rest, drink fluids and keep track of how things change.", "Avoid starting new medicines on your own. A pharmacist or doctor can advise on what is safe."]
    seek = ["It gets worse, or new symptoms appear", "You have trouble breathing, chest pain, confusion, fainting or very high fever: seek emergency care"]
    if long_: seek.insert(0, "It has lasted more than about a week without improving")
    summary = {"concern": ans["concern"], "duration": ans["duration"], "severity": sev, "age_group": age or "not given", "history": ans["history"],
               "key_points": [f"{sev.capitalize()} problem for: {ans['duration']}"], "general_guidance": guidance, "when_to_seek_care": seek,
               "suggested_specialty": "General Physician" if consult else None, "disclaimer": DISCLAIMER}
    msg = ("Thank you. Here is a summary. " + ("Based on what you told me, speaking to a doctor soon is sensible. You can look at available consultations below." if consult
           else "This sounds manageable at home for now, but please see a doctor if it lasts or gets worse.") + " " + DISCLAIMER)
    return {"reply": msg, "quick_replies": ["Book a consultation", "Start over"] if consult else ["Start over"], "stage": "guidance", "suggest_consult": consult, "summary": summary}


# ---------- Gemini flow ----------
PROMPT = """You are Medi AI Assistant, a careful family health information assistant for users in India. You are NOT a doctor.
Rules you must always follow:
- Never diagnose, never say the user definitely has a condition, never prescribe, never suggest any medicine name or dose.
- Ask exactly ONE short question per turn, in simple language. Do not ask more than 6 questions in total.
- Gather: main concern, how long, how severe, age group (skip if known), relevant history/allergies/medicines.
- If any emergency warning sign appears, tell the user to call 112/108 or go to an emergency department, and stop asking questions.
- When you have enough information (or the user has answered about 5 questions), give: a short plain-language summary, general evidence-informed information,
  clearly say what is uncertain, practical self-care that is safe for anyone, signs that mean they should see a doctor, and whether a consultation is advisable.
- Do not claim certainty. Say when something depends on an examination or tests.
Return ONLY JSON: {"reply": str, "quick_replies": [str] (max 4 short answer options, may be empty), "stage": "asking" | "guidance",
"suggest_consult": bool, "summary": null | {"concern": str, "duration": str, "severity": str, "age_group": str, "history": str, "key_points": [str],
"general_guidance": [str], "when_to_seek_care": [str], "suggested_specialty": str | null}}. Set summary only when stage is "guidance"."""

def _gemini(msgs, ctx):
    convo = "\n".join(f"{'USER' if m.role == 'user' else 'ASSISTANT'}: {m.content}" for m in msgs)
    d = ai._json(ai._generate([PROMPT, f"KNOWN CONTEXT (may be empty): {json.dumps(ctx)}", "CONVERSATION SO FAR:\n" + convo, "Reply with the next turn as JSON."], json_mode=True))
    s = d.get("summary") if isinstance(d.get("summary"), dict) else None
    if s: s["disclaimer"] = DISCLAIMER
    return {"reply": strip_doses(str(d.get("reply", "")))[:3000] or "Could you tell me a little more?", "quick_replies": [str(x)[:60] for x in (d.get("quick_replies") or [])][:4],
            "stage": "guidance" if d.get("stage") == "guidance" or s else "asking", "suggest_consult": bool(d.get("suggest_consult")), "summary": s}


@router.post("/message")
def message(t: Turn, u=Depends(require("patient"))):
    _limit(u["uid"])
    users = [m.content.strip() for m in t.messages if m.role == "user" and m.content.strip()]
    if not users or t.messages[-1].role != "user": raise HTTPException(422, "Please type a message")
    em = emergency_check(users[-1])
    if em: return {**em, "quick_replies": [], "stage": "emergency", "suggest_consult": False, "summary": None}
    ctx = _context(_member(u, t.patient_id))
    out, mode = None, "guided"
    if ai.KEY:
        try: out, mode = _gemini(t.messages, ctx), "gemini"
        except Exception as e:
            log.warning("assistant model failed, using offline flow: %s", e)
    if out is None:
        core = users[1:] if users[0] in STARTERS else users
        out = _offline(core, ctx) if core else {"reply": "Please describe the symptom or concern in a few words, for example \"sore throat\" or \"my son has a rash\".",
                                                 "quick_replies": [], "stage": "asking", "suggest_consult": False, "summary": None}
    return {"emergency": False, "mode": mode, **out}


# ---------- consented storage of summaries ----------
@router.post("/summaries")
def save_summary(s: SaveSummary, u=Depends(require("patient"))):
    """Called only when the user presses Save. Nothing from the chat is stored before this."""
    if s.patient_id: can_view_patient(u, s.patient_id)
    raw = json.dumps(s.summary)
    if len(raw) > 8000: raise HTTPException(422, "Summary is too long")
    sid = db.run("INSERT INTO assistant_summaries(user_id,patient_id,summary,created_at) VALUES(?,?,?,?)", (u["uid"], s.patient_id, raw, date.today().isoformat()))
    return {"id": sid}

@router.get("/summaries")
def list_summaries(u=Depends(require("patient"))):
    return [{"id": r["id"], "patient_id": r["patient_id"], "created_at": r["created_at"], "summary": json.loads(r["summary"])}
            for r in db.q("SELECT * FROM assistant_summaries WHERE user_id=? ORDER BY id DESC LIMIT 50", (u["uid"],))]

@router.delete("/summaries/{sid}")
def delete_summary(sid: int, u=Depends(require("patient"))):
    db.run("DELETE FROM assistant_summaries WHERE id=? AND user_id=?", (sid, u["uid"])); return {"ok": True}

@router.delete("/summaries")
def delete_all(u=Depends(require("patient"))):
    db.run("DELETE FROM assistant_summaries WHERE user_id=?", (u["uid"],)); return {"ok": True}
