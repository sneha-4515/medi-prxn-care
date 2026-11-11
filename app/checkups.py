"""Preventive check-up rules. General, commonly published screening intervals, NOT medical advice:
the doctor decides each person's schedule. Rules combine age, sex and the medicines someone takes."""
from datetime import date, timedelta

DIABETES = ("metformin", "glimepiride", "gliclazide", "sitagliptin", "vildagliptin", "insulin", "glipizide", "pioglitazone")
HYPERTENSION = ("amlodipine", "telmisartan", "losartan", "olmesartan", "atenolol", "metoprolol", "ramipril", "enalapril", "hydrochlorothiazide")
CHOLESTEROL = ("atorvastatin", "rosuvastatin", "simvastatin", "fenofibrate")
THYROID = ("thyroxine", "levothyroxine", "eltroxin", "thyronorm", "carbimazole")

def tags_from(prescriptions):
    tags = set()
    for p in prescriptions:
        text = f"{p.get('medicine') or ''} {p.get('cause') or ''}".lower()
        if any(k in text for k in DIABETES) or "diabet" in text or "sugar" in text: tags.add("diabetes")
        if any(k in text for k in HYPERTENSION) or "hypertens" in text or "blood pressure" in text or " bp" in f" {text}": tags.add("hypertension")
        if any(k in text for k in CHOLESTEROL) or "cholesterol" in text: tags.add("cholesterol")
        if any(k in text for k in THYROID) or "thyroid" in text: tags.add("thyroid")
    return tags

def rules_for(age, gender, tags):
    age = age if age is not None else 0
    female = (gender or "").strip().upper().startswith("F")
    chronic = bool(tags & {"diabetes", "hypertension", "cholesterol"})
    out = []
    def add(key, name, months, why): out.append({"key": key, "name": name, "interval_months": months, "why": why})
    if age >= 18: add("bp", "Blood pressure check", 12, "Routine for adults" + ("; takes blood-pressure medicine" if "hypertension" in tags else ""))
    if "diabetes" in tags: add("glucose", "HbA1c / blood sugar", 6, "Review blood sugar control")
    elif age >= 30: add("glucose", "Blood sugar (fasting or HbA1c)", 36, "Typical screening from age 30")
    if age >= 25: add("lipid", "Lipid profile (cholesterol)", 12 if chronic else 60, "Monitored with diabetes, BP or cholesterol medicine" if chronic else "Typical routine screening")
    if "diabetes" in tags or "hypertension" in tags: add("kidney", "Kidney function (creatinine / eGFR)", 12, "Long-term diabetes and BP medicines are monitored")
    if "thyroid" in tags: add("thyroid", "Thyroid (TSH)", 12, "Monitoring for thyroid treatment")
    if "diabetes" in tags: add("eye", "Eye examination", 12, "Diabetes can affect the retina")
    elif age >= 40: add("eye", "Eye examination", 24, "Typical from 40")
    if female and 25 <= age <= 65: add("cervical", "Cervical screening (Pap / HPV)", 36, "Typical screening for ages 25 to 65")
    if female and age >= 40: add("breast", "Breast screening", 24, "Discuss mammography with the doctor from 40")
    if age >= 60: add("flu", "Flu vaccination", 12, "Recommended for older adults")
    if age <= 5: add("immunisation", "Immunisation schedule review", 6, "Keep childhood vaccines on schedule")
    if age >= 18: add("general", "Full health check-up", 12 if age >= 40 else 24, "Routine review with a doctor")
    add("dental", "Dental check-up", 12, "Routine dental review")
    return out

def _add_months(d, m):
    y, mo = divmod(d.month - 1 + m, 12)
    year, month = d.year + y, mo + 1
    import calendar
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))

def evaluate(age, gender, prescriptions, done_rows, today=None):
    today = today or date.today()
    last = {}
    for r in done_rows:
        d = date.fromisoformat(r["done_on"])
        if r["key"] not in last or d > last[r["key"]]: last[r["key"]] = d
    items = []
    for r in rules_for(age, gender, tags_from(prescriptions)):
        ld = last.get(r["key"])
        if ld is None: status, nxt = "no_record", None
        else:
            nxt = _add_months(ld, r["interval_months"])
            status = "overdue" if nxt < today else ("due_soon" if nxt <= today + timedelta(days=30) else "ok")
        items.append({**r, "last_done": ld.isoformat() if ld else None, "next_due": nxt.isoformat() if nxt else None, "status": status})
    order = {"overdue": 0, "no_record": 1, "due_soon": 2, "ok": 3}
    return sorted(items, key=lambda i: order[i["status"]])
