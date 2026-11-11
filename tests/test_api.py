from datetime import date, timedelta
from app import checkups as ck, schedule

def extract(c, u, text, pid=None):
    return c.post("/doctor/extract", data={"patient_id": pid or u["mom"], "kind": "transcript", "transcript": text}, headers=u["doc"]).json()

def test_health(client): assert client.get("/healthz").json() == {"ok": True}
def test_static_index(client): assert "Medi-Prxn Care" in client.get("/").text
def test_manifest_and_sw(client):
    assert client.get("/manifest.webmanifest").status_code == 200 and client.get("/sw.js").status_code == 200

def test_signup_validation(client):
    assert client.post("/auth/signup", json={"name": "x", "email": "s@x.io", "password": "short", "role": "patient"}).status_code == 422
    assert client.post("/auth/signup", json={"name": "x", "email": "a@x.io", "password": "password1", "role": "admin"}).status_code == 403
def test_login_bad(client): assert client.post("/auth/login", json={"email": "nobody@x.io", "password": "x"}).status_code == 401
def test_requires_token(client): assert client.get("/dashboard").status_code == 401

def test_qr_scan_and_role_guard(client, users):
    qr = client.get(f"/patients/{users['mom']}/qr", headers=users["pat"]).json()["qr_payload"]
    assert qr.startswith("mediprxn:")
    r = client.post("/doctor/scan", params={"qr": qr}, headers=users["doc"]); assert r.status_code == 200 and r.json()["patient"]["name"] == "Mom"
    assert client.post("/doctor/scan", params={"qr": qr}, headers=users["pat"]).status_code == 403
    assert client.get(f"/patients/{users['mom']}/qr.svg", headers=users["pat"]).text.lstrip().startswith("<?xml")

def test_extract_gating_and_approve(client, users):
    r = extract(client, users, "Prescribe Paracetamol 650mg twice a day after food for 3 days")
    med = r["draft"]["medicines"][0]; assert (med["dosage"], med["frequency_per_day"], med["duration_days"]) == ("650mg", 2, 3)
    bad = dict(med, duration_days=None)
    assert client.post("/doctor/approve", json={"patient_id": users["mom"], "medicines": [bad]}, headers=users["doc"]).status_code == 422
    ok = client.post("/doctor/approve", json={"patient_id": users["mom"], "medicines": [med], "next_followup": (date.today() + timedelta(days=10)).isoformat(), "document_id": r["document_id"]}, headers=users["doc"])
    assert ok.json() == {"saved": 1}

def test_duplicate_and_allergy_flags(client, users):
    w = extract(client, users, "Prescribe Paracetamol 500mg once a day for 2 days")["safety_warnings"]
    assert any(x["type"] == "duplicate_therapy" for x in w)
    w = extract(client, users, "Prescribe Penicillin 250mg twice a day for 5 days")["safety_warnings"]
    assert any(x["type"] == "allergy" and x["severity"] == "high" for x in w)

def test_dashboard_reminders_orders(client, users):
    d = [x for x in client.get("/dashboard", headers=users["pat"]).json() if x["patient"]["id"] == users["mom"]][0]
    m = d["active_medicines"][0]
    assert m["order_url"].startswith("https://www.1mg.com/") and m["dose_times"] == ["09:00", "21:00"] and d["upcoming_followups"]
    rem = client.get("/reminders", headers=users["pat"]).json()
    assert [r["time"] for r in rem if r["medicine"] == "Paracetamol"] == ["09:00", "21:00"]

def test_privacy_toggle_hides_from_family(client, users):
    client.post(f"/patients/{users['mom']}/privacy", params={"private": "true"}, headers=users["doc"])
    d = [x for x in client.get("/dashboard", headers=users["pat"]).json() if x["patient"]["id"] == users["mom"]][0]
    assert d["private"] and d["active_medicines"] == []
    assert not [r for r in client.get("/reminders", headers=users["pat"]).json() if r["patient_id"] == users["mom"]]
    client.post(f"/patients/{users['mom']}/privacy", params={"private": "false"}, headers=users["doc"])

def test_family_isolation(client, users):
    other = client.post("/auth/signup", json={"name": "O", "email": f"o{date.today().toordinal()}{id(users)}@x.io", "password": "password1", "role": "patient", "age": 40}).json()
    H = {"Authorization": "Bearer " + other["token"]}
    assert client.get(f"/patients/{users['mom']}/qr", headers=H).status_code == 403
    assert client.post("/records/manual", json={"patient_id": users["mom"], "medicine": "X"}, headers=H).status_code == 403

def test_manual_record_and_chat(client, users):
    assert client.post("/records/manual", json={"patient_id": users["mom"], "medicine": "Vitamin D", "cause": "deficiency"}, headers=users["pat"]).status_code == 200
    assert "answer" in client.post("/chat", json={"question": "next follow-up?"}, headers=users["pat"]).json()
    assert client.get("/chat/history", headers=users["pat"]).json()

def test_checkups_flow(client, users):
    data = [x for x in client.get("/checkups", headers=users["pat"]).json() if x["patient"]["id"] == users["mom"]][0]
    keys = {i["key"]: i for i in data["items"]}
    assert "cervical" in keys and "breast" in keys and keys["bp"]["status"] == "no_record"
    assert client.post("/checkups/done", json={"patient_id": users["mom"], "key": "bp"}, headers=users["pat"]).status_code == 200
    again = [x for x in client.get("/checkups", headers=users["pat"]).json() if x["patient"]["id"] == users["mom"]][0]
    assert {i["key"]: i for i in again["items"]}["bp"]["status"] == "ok"
    assert client.post("/checkups/done", json={"patient_id": users["mom"], "key": "nonsense"}, headers=users["pat"]).status_code == 422

def test_rules_by_medicine_and_age():
    rx = [{"medicine": "Metformin", "cause": "diabetes"}, {"medicine": "Amlodipine", "cause": ""}]
    keys = {i["key"]: i for i in ck.evaluate(50, "M", rx, [])}
    assert keys["glucose"]["interval_months"] == 6 and "kidney" in keys and "eye" in keys and "cervical" not in keys
    assert "immunisation" in {i["key"] for i in ck.evaluate(3, "M", [], [])}
    assert "flu" in {i["key"] for i in ck.evaluate(70, "F", [], [])}

def test_checkup_status_dates():
    today = date(2026, 10, 15); rule = lambda d: {i["key"]: i["status"] for i in ck.evaluate(30, "M", [], [{"key": "bp", "done_on": d}], today)}["bp"]
    assert rule("2026-01-01") == "ok" and rule("2025-10-01") == "overdue" and rule("2025-11-01") == "due_soon"

def test_dose_times():
    assert schedule.dose_times(3) == ["08:00", "14:00", "21:00"] and schedule.dose_times(1, "at night") == ["21:30"] and schedule.dose_times(None) == ["09:00"]
