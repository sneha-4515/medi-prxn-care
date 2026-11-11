"""Gemini wrappers. Falls back to a rule-based mock when GEMINI_API_KEY is absent so the app runs offline."""
import json, re, time, logging
from . import config

log = logging.getLogger("uvicorn.error")
MODEL = config.GEMINI_MODEL
KEY = config.GEMINI_API_KEY

EXTRACT_PROMPT = """You are a clinical documentation assistant. Extract prescription data from the input
(doctor's dictation, consultation transcript, or handwritten prescription image).
Return ONLY JSON: {"medicines":[{"name":str,"dosage":str,"timing":str,"frequency_per_day":int,
"duration_days":int,"cause":str|null}],"next_followup":"YYYY-MM-DD"|null,"lab_tests":[str],
"allergies_mentioned":[str],"missing_fields":[str]}. Use null for anything not stated; list gaps in missing_fields. Never guess."""

_client_obj = None

def _client():
    """One shared client kept alive for the whole app (a discarded client closes its connection)."""
    global _client_obj
    if _client_obj is None:
        from google import genai
        _client_obj = genai.Client(api_key=KEY)
    return _client_obj

def _json(text):
    return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())

def _generate(contents, json_mode=False):
    """Call Gemini. Retries temporary errors (500/503/504), skips retries on 429, tries the fallback model if set."""
    from google.genai import types, errors as genai_errors
    cfg = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    models = [MODEL] + ([config.GEMINI_FALLBACK_MODEL] if config.GEMINI_FALLBACK_MODEL else [])
    last = None
    for model in models:
        for attempt in range(3):
            try:
                return _client().models.generate_content(model=model, contents=contents, config=cfg).text
            except genai_errors.APIError as e:
                last = e
                code = getattr(e, "code", None)
                log.warning("Gemini call failed on %s (%s), attempt %d", model, code, attempt + 1)
                if code in (500, 503, 504):
                    time.sleep(1.5 * (attempt + 1)); continue
                if code == 429:
                    break
                raise
    raise last

def extract_prescription(text=None, file_bytes=None, mime=None):
    if not KEY:
        return _mock_extract(text or "")
    from google.genai import types
    parts = [EXTRACT_PROMPT]
    if file_bytes: parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))
    if text: parts.append(text)
    return _json(_generate(parts, json_mode=True))

def _mock_extract(text):
    m = re.search(r"([A-Za-z]+)\s+(\d+\s?mg)", text)
    if not m: return {"medicines": [], "next_followup": None, "lab_tests": [], "allergies_mentioned": [], "missing_fields": ["medicines"]}
    f = re.search(r"(once|twice|thrice)", text, re.I)
    d = re.search(r"for\s+(\d+)\s+days", text, re.I)
    t = re.search(r"(after|before) food", text, re.I)
    med = {"name": m.group(1), "dosage": m.group(2), "timing": t.group(0) if t else None,
           "frequency_per_day": {"once": 1, "twice": 2, "thrice": 3}[f.group(1).lower()] if f else None,
           "duration_days": int(d.group(1)) if d else None, "cause": None}
    return {"medicines": [med], "next_followup": None, "lab_tests": [], "allergies_mentioned": [],
            "missing_fields": [k for k, v in med.items() if v is None]}

SAFETY_PROMPT = """You are a clinical safety checker. Given the patient's ACTIVE medicines, KNOWN allergies and a NEW prescription,
return ONLY JSON: {"warnings":[{"severity":"high|medium|low","type":"interaction|contraindication|allergy|duplicate_therapy|dose",
"message":str}]}. Return an empty list if nothing is concerning. These are decision-support flags for the doctor, not orders."""

def safety_check(active, allergies, new_meds):
    # deterministic duplicate / allergy checks always run; Gemini adds interaction reasoning
    warnings = []
    act = {m["medicine"].lower() for m in active}
    for m in new_meds:
        n = (m.get("name") or "").lower()
        if n in act: warnings.append({"severity": "medium", "type": "duplicate_therapy", "message": f"{m['name']} is already an active medicine."})
        for a in allergies:
            if a and a.lower() in n: warnings.append({"severity": "high", "type": "allergy", "message": f"Patient is allergic to {a}."})
    if KEY:
        payload = json.dumps({"active": active, "allergies": allergies, "new": new_meds}, default=str)
        warnings += _json(_generate([SAFETY_PROMPT, payload], json_mode=True)).get("warnings", [])
    return warnings

def chat(question, context):
    if not KEY:
        return "(Gemini key not set) Context I have:\n" + json.dumps(context, default=str)[:1500]
    prompt = ("You are a family health assistant. Answer ONLY from the context JSON. Be concise. "
              "For emergency symptoms, give general first-aid guidance, state that you are not a doctor, "
              "and advise contacting the treating doctor / emergency services. Money amounts are Indian rupees and are already totalled in the context; quote them exactly and never add them up yourself. Never invent records.\n"
              f"CONTEXT:\n{json.dumps(context, default=str)}\n\nQUESTION: {question}")
    return _generate(prompt)


EXPLAIN_PROMPT = """You explain medical reports to ordinary people in simple English. For the report below: (1) list each test or term with a one-line plain meaning,
(2) say whether a value is marked outside the printed reference range if the report shows one, without calling it a disease, (3) never diagnose, never suggest medicines or doses,
(4) end by saying which findings are worth discussing with a doctor and that this is general information only. Keep it under 300 words."""

def explain_report(text=None, file_bytes=None, mime=None):
    if not KEY:
        raise RuntimeError("no key")
    from google.genai import types
    parts = [EXPLAIN_PROMPT]
    if file_bytes: parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))
    if text: parts.append(text)
    return _generate(parts)
