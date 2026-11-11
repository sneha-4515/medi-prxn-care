"""Consultation booking and PayPal flow, tested against an in-memory fake of the PayPal Orders API."""
import itertools, json, pytest
from datetime import datetime, timedelta
from app import db, config, paypal, consult
from app.main import app
from conftest import hdr

_n = itertools.count(1)


class FakePayPal:
    def __init__(self):
        self.orders, self.seen, self.refunds = {}, {}, {}
        self.decline = self.tamper = False
    def __call__(self, method, path, body=None, request_id=None):
        if request_id and (method, path, request_id) in self.seen: return self.seen[(method, path, request_id)]
        if path == "/v2/checkout/orders" and method == "POST":
            oid = f"ORD{next(_n)}"; pu = body["purchase_units"][0]
            self.orders[oid] = {"id": oid, "status": "CREATED", "purchase_units": [{**pu, "payments": {"captures": []}}]}
            out = {"id": oid, "status": "CREATED"}
        elif path.endswith("/capture"):
            oid = path.split("/")[4]; o = self.orders[oid]
            if self.decline: raise paypal.PayPalError(422, "UNPROCESSABLE_ENTITY", "", "INSTRUMENT_DECLINED")
            if o["status"] == "COMPLETED": raise paypal.PayPalError(422, "UNPROCESSABLE_ENTITY", "", "ORDER_ALREADY_CAPTURED")
            pu = o["purchase_units"][0]; amt = dict(pu["amount"])
            if self.tamper: amt["value"] = "0.01"
            pu["payments"]["captures"] = [{"id": f"CAP{next(_n)}", "status": "COMPLETED", "amount": amt}]
            o["status"] = "COMPLETED"; out = o
        elif method == "GET" and "/v2/checkout/orders/" in path: out = self.orders[path.rsplit("/", 1)[-1]]
        elif "/refund" in path: out = {"id": f"REF{next(_n)}", "status": "COMPLETED"}
        elif path.endswith("verify-webhook-signature"): out = {"verification_status": "SUCCESS" if body["transmission_sig"] == "good" else "FAILURE"}
        else: raise AssertionError(path)
        if request_id: self.seen[(method, path, request_id)] = out
        return out


@pytest.fixture()
def pp(monkeypatch):
    f = FakePayPal()
    monkeypatch.setattr(paypal, "_request", f)
    monkeypatch.setattr(config, "PAYPAL_CLIENT_ID", "test-client"); monkeypatch.setattr(config, "PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(config, "PAYPAL_WEBHOOK_ID", "WH-1")
    return f

def _new_user(client, tag):
    email = f"{tag}{next(_n)}@x.io"
    r = client.post("/auth/signup", json={"name": tag, "email": email, "password": "password1", "role": "patient", "age": 40}).json()
    H = {"Authorization": "Bearer " + r["token"]}
    return H, client.get("/family", headers=H).json()[0]["id"]

def _doctor():
    return db.q("SELECT * FROM providers WHERE kind='doctor' AND fee=400", one=True)

def _slot(hours_ahead, provider=None):
    p = provider or _doctor(); t = (datetime.now(consult.IST).replace(tzinfo=None) + timedelta(hours=hours_ahead)).replace(second=0, microsecond=0)
    ts = t.strftime("%Y-%m-%dT%H:%M")
    while db.q("SELECT 1 FROM slots WHERE provider_id=? AND starts_at=?", (p["id"], ts)): t += timedelta(minutes=1); ts = t.strftime("%Y-%m-%dT%H:%M")
    return db.run("INSERT INTO slots(provider_id,starts_at,status) VALUES(?,?,'open')", (p["id"], ts)), p

def _book(client, H, pid, slot, prov, typ="first_visit"):
    return client.post("/consult/bookings", json={"provider_id": prov["id"], "slot_id": slot, "consult_type": typ, "patient_id": pid}, headers=H)

def test_price_is_computed_on_the_server(users, client):
    p = consult.price(400, "first_visit")
    assert (p["fee_paise"], p["platform_fee_paise"], p["total_paise"]) == (40000, 4900, 44900)
    assert p["charge_value"] == "5.29" and p["currency"] == "USD"
    assert consult.price(400, "follow_up")["fee_paise"] == 24000
    # the request model has no amount field, so the browser cannot choose a price
    assert "amount" not in consult.QuoteIn.model_fields

def test_booking_needs_paypal_keys(users, client, monkeypatch):
    monkeypatch.setattr(config, "PAYPAL_CLIENT_ID", None)
    H, pid = _new_user(client, "nokeys"); s, p = _slot(48)
    assert _book(client, H, pid, s, p).status_code == 503

def test_providers_and_quote(users, client):
    consult.ensure_sample_slots()
    H, pid = _new_user(client, "browse")
    r = client.get("/consult/providers", headers=H).json()
    assert r["sample_data"] and len(r["providers"]) >= 5 and all(x["fee"] > 0 for x in r["providers"])
    s, p = _slot(48)
    q = client.post("/consult/quote", json={"provider_id": p["id"], "slot_id": s, "consult_type": "first_visit", "patient_id": pid}, headers=H).json()
    assert q["consultation_fee"] == 400 and q["booking_fee"] == 49 and q["total_inr"] == 449 and q["charge_value"] == "5.29"

def test_full_paid_flow_verifies_on_server(users, client, pp):
    H, pid = _new_user(client, "payer"); s, p = _slot(72)
    r = _book(client, H, pid, s, p); assert r.status_code == 200, r.text
    ref, oid = r.json()["booking"]["ref"], r.json()["order_id"]
    # creating the order alone never marks anything paid
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "pending_payment"
    assert db.q("SELECT 1 FROM bills WHERE invoice_no=?", (ref,)) == []
    c = client.post(f"/consult/bookings/{ref}/capture", json={"order_id": oid}, headers=H); assert c.status_code == 200, c.text
    b = c.json()["booking"]; assert b["status"] == "paid" and b["transaction_id"].startswith("CAP") and b["total_inr"] == 449
    assert db.q("SELECT status FROM slots WHERE id=?", (s,), one=True)["status"] == "booked"
    bill = db.q("SELECT * FROM bills WHERE invoice_no=?", (ref,), one=True)
    assert bill["status"] == "paid" and bill["amount"] == 449 and bill["payment_method"] == "PayPal" and bill["category"] == "consultation"
    # duplicate capture call is harmless
    again = client.post(f"/consult/bookings/{ref}/capture", json={"order_id": oid}, headers=H).json()
    assert again["already"] and len(db.q("SELECT 1 FROM bills WHERE invoice_no=?", (ref,))) == 1
    ov = client.get("/consult/overview", headers=H).json(); assert ov["paid_count"] == 1 and ov["paid_total_inr"] == 449

def test_two_people_cannot_take_the_same_slot(users, client, pp):
    H1, p1 = _new_user(client, "a"); H2, p2 = _new_user(client, "b"); s, p = _slot(96)
    assert _book(client, H1, p1, s, p).status_code == 200
    assert _book(client, H2, p2, s, p).status_code == 409

def test_hold_expires_and_slot_returns(users, client, pp):
    H1, p1 = _new_user(client, "c"); H2, p2 = _new_user(client, "d"); s, p = _slot(100)
    ref = _book(client, H1, p1, s, p).json()["booking"]["ref"]
    db.run("UPDATE slots SET held_until='2000-01-01T00:00:00' WHERE id=?", (s,)); db.run("UPDATE bookings SET expires_at='2000-01-01T00:00:00' WHERE ref=?", (ref,))
    assert _book(client, H2, p2, s, p).status_code == 200
    late = client.post(f"/consult/bookings/{ref}/capture", json={"order_id": db.q("SELECT paypal_order_id o FROM bookings WHERE ref=?", (ref,), one=True)["o"]}, headers=H1)
    assert late.status_code == 409

def test_declined_payment_can_be_retried(users, client, pp):
    H, pid = _new_user(client, "decl"); s, p = _slot(110)
    d = _book(client, H, pid, s, p).json(); ref, oid = d["booking"]["ref"], d["order_id"]
    pp.decline = True
    r = client.post(f"/consult/bookings/{ref}/capture", json={"order_id": oid}, headers=H)
    assert r.status_code == 402 and "another" in r.json()["detail"]
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "payment_failed"
    assert db.q("SELECT 1 FROM bills WHERE invoice_no=?", (ref,)) == []
    pp.decline = False
    assert client.post(f"/consult/bookings/{ref}/capture", json={"order_id": oid}, headers=H).json()["booking"]["status"] == "paid"

def test_new_attempt_after_failure_reuses_own_slot(users, client, pp):
    H, pid = _new_user(client, "retry"); s, p = _slot(115)
    ref1 = _book(client, H, pid, s, p).json()["booking"]["ref"]
    r2 = _book(client, H, pid, s, p); assert r2.status_code == 200
    assert client.get(f"/consult/bookings/{ref1}", headers=H).json()["status"] == "cancelled"
    d = r2.json(); assert client.post(f"/consult/bookings/{d['booking']['ref']}/capture", json={"order_id": d["order_id"]}, headers=H).json()["booking"]["status"] == "paid"

def test_cancelled_checkout_frees_the_slot(users, client, pp):
    H, pid = _new_user(client, "canc"); s, p = _slot(120)
    ref = _book(client, H, pid, s, p).json()["booking"]["ref"]
    assert db.q("SELECT status FROM slots WHERE id=?", (s,), one=True)["status"] == "held"
    assert client.post(f"/consult/bookings/{ref}/abandon", headers=H).json()["booking"]["status"] == "cancelled"
    assert client.post(f"/consult/bookings/{ref}/abandon", headers=H).status_code == 200      # safe to repeat
    assert db.q("SELECT status FROM slots WHERE id=?", (s,), one=True)["status"] == "open"

def test_wrong_order_and_other_users_booking_rejected(users, client, pp):
    H, pid = _new_user(client, "own"); H2, _ = _new_user(client, "thief"); s, p = _slot(130)
    d = _book(client, H, pid, s, p).json(); ref = d["booking"]["ref"]
    assert client.post(f"/consult/bookings/{ref}/capture", json={"order_id": "ORD-OTHER"}, headers=H).status_code == 422
    assert client.post(f"/consult/bookings/{ref}/capture", json={"order_id": d["order_id"]}, headers=H2).status_code == 404

def test_amount_mismatch_is_not_confirmed(users, client, pp):
    H, pid = _new_user(client, "tamp"); s, p = _slot(140)
    d = _book(client, H, pid, s, p).json(); ref = d["booking"]["ref"]; pp.tamper = True
    r = client.post(f"/consult/bookings/{ref}/capture", json={"order_id": d["order_id"]}, headers=H)
    assert r.status_code == 422
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "needs_review"
    assert db.q("SELECT 1 FROM bills WHERE invoice_no=?", (ref,)) == []

def test_refund_inside_window_and_blocked_outside(users, client, pp):
    H, pid = _new_user(client, "ref"); far, p = _slot(24 * 3); near, _ = _slot(3)
    d = _book(client, H, pid, far, p).json(); ref = d["booking"]["ref"]
    client.post(f"/consult/bookings/{ref}/capture", json={"order_id": d["order_id"]}, headers=H)
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["refund_eligible"] is True
    r = client.post(f"/consult/bookings/{ref}/cancel", headers=H).json()["booking"]
    assert r["status"] == "refunded" and r["refund_status"] == "COMPLETED"
    assert db.q("SELECT status FROM bills WHERE invoice_no=?", (ref,), one=True)["status"] == "refunded"
    assert db.q("SELECT status FROM slots WHERE id=?", (far,), one=True)["status"] == "open"
    assert client.post(f"/consult/bookings/{ref}/cancel", headers=H).status_code == 409        # no second refund
    d2 = _book(client, H, pid, near, p).json(); ref2 = d2["booking"]["ref"]
    client.post(f"/consult/bookings/{ref2}/capture", json={"order_id": d2["order_id"]}, headers=H)
    assert client.post(f"/consult/bookings/{ref2}/cancel", headers=H).status_code == 409

def _event(ref, value="5.29", typ="PAYMENT.CAPTURE.COMPLETED", eid=None):
    return {"id": eid or f"WH-EV{next(_n)}", "event_type": typ, "resource": {"id": f"CAPW{next(_n)}", "custom_id": ref, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": value}}}

def _wh(client, ev, sig="good"):
    return client.post("/paypal/webhook", content=json.dumps(ev), headers={"content-type": "application/json", "paypal-auth-algo": "x", "paypal-cert-url": "x",
                       "paypal-transmission-id": "x", "paypal-transmission-sig": sig, "paypal-transmission-time": "x"})

def test_webhook_rules(users, client, pp, monkeypatch):
    H, pid = _new_user(client, "wh"); s, p = _slot(150)
    ref = _book(client, H, pid, s, p).json()["booking"]["ref"]
    assert _wh(client, _event(ref), sig="bad").status_code == 400                                 # unsigned events are ignored
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "pending_payment"
    ev = _event(ref); assert _wh(client, ev).json() == {"ok": True}
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "paid"           # fallback when the browser never returned
    assert _wh(client, ev).json()["duplicate"] is True                                            # same event id is processed once
    assert len(db.q("SELECT 1 FROM bills WHERE invoice_no=?", (ref,))) == 1
    monkeypatch.setattr(config, "PAYPAL_WEBHOOK_ID", None)
    assert _wh(client, _event(ref)).status_code == 503

def test_webhook_wrong_amount_is_flagged(users, client, pp):
    H, pid = _new_user(client, "whbad"); s, p = _slot(160)
    ref = _book(client, H, pid, s, p).json()["booking"]["ref"]
    _wh(client, _event(ref, value="0.10"))
    assert client.get(f"/consult/bookings/{ref}", headers=H).json()["status"] == "needs_review"

def test_family_edit_and_delete(users, client):
    H, _ = _new_user(client, "fam"); mid = client.post("/family", json={"name": "Dad", "age": 61, "relation": "father"}, headers=H).json()["patient_id"]
    assert client.put(f"/family/{mid}", json={"name": "Dad R", "age": 62, "relation": "father", "allergies": "Dust"}, headers=H).status_code == 200
    assert [m for m in client.get("/family", headers=H).json() if m["id"] == mid][0]["name"] == "Dad R"
    assert client.delete(f"/family/{mid}", headers=H).status_code == 200
    me = client.get("/family", headers=H).json()[0]["id"]
    assert client.delete(f"/family/{me}", headers=H).status_code == 422
