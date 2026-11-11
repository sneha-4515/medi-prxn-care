from app import assistant as A
from test_consult import _new_user

def U(t): return {"role": "user", "content": t}
def AI(t): return {"role": "assistant", "content": t}

def test_emergency_rules():
    for t in ["my dad has chest pain and is sweating", "she is not breathing properly", "he has slurred speech since morning", "I feel like I want to die",
              "coughing blood since last night", "my baby is limp and not feeding", "he fainted and has a seizure"]:
        assert A.emergency_check(t), t
    assert "14416" in A.emergency_check("I want to end my life")["reply"] and "112" in A.emergency_check("chest pain")["reply"]

def test_not_every_mention_is_an_emergency():
    for t in ["I have a sore throat for two days", "no chest pain, only a mild cough", "he does not have any bleeding, just a small rash"]:
        assert A.emergency_check(t) is None, t

def test_doses_never_reach_the_user():
    out = A.strip_doses("Rest well. Take 500 mg every 6 hours. Drink water.")
    assert "500" not in out and "can't suggest medicine doses" in out and "Rest well" in out

def test_age_groups():
    assert A.age_group(1).startswith("infant") and A.age_group(8).startswith("child") and A.age_group(15).startswith("teen") and A.age_group(40).startswith("adult") and A.age_group(70).startswith("senior")

def test_questionnaire_one_question_at_a_time_then_summary(client, users):
    H, pid = _new_user(client, "bot")
    r = client.get("/assistant/start", headers=H).json(); assert "not a doctor" in r["reply"] and r["quick_replies"]
    msgs = [AI(r["reply"]), U("I have a sore throat")]; seen = []
    for ans in ["2 to 3 days", "Mild", "Adult", "None"]:
        r = client.post("/assistant/message", json={"messages": msgs}, headers=H).json()
        assert r["stage"] == "asking" and r["reply"].count("?") == 1 and not r["emergency"]
        seen.append(r["reply"]); msgs += [AI(r["reply"]), U(ans)]
    r = client.post("/assistant/message", json={"messages": msgs}, headers=H).json()
    assert r["stage"] == "guidance" and r["summary"]["concern"] == "I have a sore throat" and r["summary"]["severity"] == "mild" and "not a diagnosis" in r["summary"]["disclaimer"]
    assert r["suggest_consult"] is False
    assert len(set(seen)) == 4

def test_severe_or_long_problem_suggests_consultation(client, users):
    H, pid = _new_user(client, "bot2"); msgs = [U("stomach ache")]
    for ans in ["More than 2 weeks", "Severe", "Senior (60+)", "None"]:
        r = client.post("/assistant/message", json={"messages": msgs}, headers=H).json(); msgs += [AI(r["reply"]), U(ans)]
    r = client.post("/assistant/message", json={"messages": msgs}, headers=H).json()
    assert r["suggest_consult"] is True and r["summary"]["suggested_specialty"]

def test_emergency_interrupts_the_flow(client, users):
    H, _ = _new_user(client, "bot3")
    r = client.post("/assistant/message", json={"messages": [U("I have chest pain and cannot breathe")]}, headers=H).json()
    assert r["emergency"] and r["stage"] == "emergency" and r["summary"] is None and "112" in r["reply"] and r["quick_replies"] == []

def test_summary_saved_only_on_request_and_deletable(client, users):
    H, pid = _new_user(client, "bot4")
    assert client.get("/assistant/summaries", headers=H).json() == []
    sid = client.post("/assistant/summaries", json={"summary": {"concern": "cough"}, "patient_id": pid}, headers=H).json()["id"]
    assert len(client.get("/assistant/summaries", headers=H).json()) == 1
    H2, _ = _new_user(client, "bot5"); assert client.get("/assistant/summaries", headers=H2).json() == []
    client.delete(f"/assistant/summaries/{sid}", headers=H); assert client.get("/assistant/summaries", headers=H).json() == []

def test_doctor_cannot_use_assistant(client, users):
    assert client.get("/assistant/start", headers=users["doc"]).status_code == 403
