"""AI-assisted consultation booking paid through PayPal Checkout (Sandbox).

Rules this module enforces:
- The price is computed on the server from the provider's fee; the browser never sends an amount.
- A booking is marked paid only after the server captured the order with PayPal and checked the captured amount,
  currency and booking reference. A frontend "success" callback alone changes nothing.
- A slot is held for HOLD_MINUTES with an atomic UPDATE, so two people cannot pay for the same time.
- Capture and refund use PayPal-Request-Id plus an atomic status claim, so double clicks and retries cannot charge twice.
- Webhooks are signature-verified with PayPal and processed once per event id.
Providers and slots here are sample data. Nothing in this module arranges a real consultation."""
import json, logging, secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from . import db, config, paypal
from .billing import to_paise, rupees
from .common import can_view_patient
from .security import require

log = logging.getLogger("mediprxn.consult")
router = APIRouter(tags=["consultations"])
IST = timezone(timedelta(hours=5, minutes=30))
CONSULT_TYPES = {"first_visit": ("First consultation", 100), "follow_up": ("Follow-up consultation", 60)}
SLOT_TIMES = ("10:00", "11:30", "15:00", "16:30")
OPEN_STATES = ("pending_payment", "payment_failed")
LABELS = {"pending_payment": "Waiting for payment", "capturing": "Processing payment", "payment_pending": "Payment pending at PayPal",
          "payment_failed": "Payment failed, you can try again", "paid": "Paid (sandbox demo)", "cancelled": "Cancelled",
          "expired": "Expired", "refunding": "Refund in progress", "refunded": "Refunded", "needs_review": "Needs review", "failed": "Could not start"}


def _utc(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
def _utc_in(minutes): return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
def _ist(): return datetime.now(IST).replace(tzinfo=None)
def _slot_dt(s): return datetime.strptime(s, "%Y-%m-%dT%H:%M")


# ---------- pricing (server side only) ----------
def minor(paise):
    """Rupees (as paise) -> smallest unit of the PayPal currency, at the fixed demo rate. At least 1."""
    v = (Decimal(paise) / Decimal(config.INR_PER_UNIT)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return max(1, int(v))

def price(fee_rupees, consult_type):
    pct = CONSULT_TYPES[consult_type][1]
    fee_paise = to_paise(fee_rupees) * pct // 100
    plat = config.PLATFORM_FEE_PAISE
    fee_c, plat_c = minor(fee_paise), minor(plat)
    return {"fee_paise": fee_paise, "platform_fee_paise": plat, "total_paise": fee_paise + plat,
            "currency": config.PAYPAL_CURRENCY, "fee_charge": f"{Decimal(fee_c) / 100:.2f}", "platform_charge": f"{Decimal(plat_c) / 100:.2f}",
            "charge_value": f"{Decimal(fee_c + plat_c) / 100:.2f}", "rate": config.INR_PER_UNIT}

def quote_out(p):
    return {"consultation_fee": rupees(p["fee_paise"]), "booking_fee": rupees(p["platform_fee_paise"]), "total_inr": rupees(p["total_paise"]),
            "charge_value": p["charge_value"], "charge_currency": p["currency"], "fee_charge": p["fee_charge"], "booking_fee_charge": p["platform_charge"],
            "rate_note": f"Demo rate: Rs {p['rate']} = 1 {p['currency']}. PayPal Sandbox charges in {p['currency']}; no real money moves."}


# ---------- slot / booking housekeeping ----------
def _expire():
    now = _utc()
    db.run_count("UPDATE slots SET status='open', held_by=NULL, held_until=NULL WHERE status='held' AND held_until < ?", (now,))
    db.run_count("UPDATE bookings SET status='expired' WHERE status IN ('pending_payment','payment_failed') AND expires_at < ?", (now,))

def _release(b):
    db.run_count("UPDATE slots SET status='open', held_by=NULL, held_until=NULL WHERE id=? AND status IN ('held','booked')", (b["slot_id"],))

def ensure_sample_slots(days=5):
    """Create sandbox demo slots (4 a day) for every active doctor in the directory. Safe to call repeatedly."""
    docs = db.q("SELECT id FROM providers WHERE kind='doctor' AND active=1 AND fee IS NOT NULL AND fee > 0")
    have = {(r["provider_id"], r["starts_at"]) for r in db.q("SELECT provider_id, starts_at FROM slots")}
    today, n = _ist().date(), 0
    for d in range(1, days + 1):
        day = (today + timedelta(days=d)).isoformat()
        for p in docs:
            for t in SLOT_TIMES:
                if (p["id"], f"{day}T{t}") not in have:
                    db.run("INSERT INTO slots(provider_id,starts_at,status) VALUES(?,?,'open')", (p["id"], f"{day}T{t}")); n += 1
    return n


# ---------- output ----------
def booking_out(b):
    refundable = b["status"] == "paid" and _slot_dt(b["starts_at"]) - _ist() >= timedelta(hours=config.REFUND_WINDOW_HOURS)
    pat = db.q("SELECT name FROM patients WHERE id=?", (b["patient_id"],), one=True)
    return {"ref": b["ref"], "status": b["status"], "status_label": LABELS.get(b["status"], b["status"]), "patient_id": b["patient_id"],
            "patient_name": pat["name"] if pat else "", "provider_id": b["provider_id"], "provider_name": b["provider_name"], "specialty": b["specialty"],
            "consult_type": b["consult_type"], "consult_label": CONSULT_TYPES.get(b["consult_type"], ("", 0))[0], "starts_at": b["starts_at"],
            "consultation_fee": rupees(b["fee_paise"]), "booking_fee": rupees(b["platform_fee_paise"]), "total_inr": rupees(b["total_paise"]),
            "charge_value": b["charge_value"], "charge_currency": b["charge_currency"], "transaction_id": b["paypal_capture_id"],
            "paid_at": b["paid_at"], "created_at": b["created_at"], "refund_status": b["refund_status"], "summary_id": b["summary_id"],
            "refund_eligible": refundable, "can_cancel": b["status"] in OPEN_STATES or refundable, "sandbox_demo": True}

def _mine(u, ref):
    b = db.q("SELECT * FROM bookings WHERE ref=? AND user_id=?", (ref, u["uid"]), one=True)
    if not b: raise HTTPException(404, "Booking not found")
    return b


# ---------- public config / browse ----------
@router.get("/paypal/config")
def pp_config(u=Depends(require("patient", "doctor", "admin"))):
    return {"enabled": paypal.configured(), "client_id": config.PAYPAL_CLIENT_ID if paypal.configured() else None,
            "currency": config.PAYPAL_CURRENCY, "env": "sandbox"}

@router.get("/consult/providers")
def providers(specialty: str | None = None, u=Depends(require("patient"))):
    _expire(); now = _ist().strftime("%Y-%m-%dT%H:%M"); rows = []
    for p in db.q("SELECT * FROM providers WHERE kind='doctor' AND active=1 AND fee IS NOT NULL AND fee > 0 ORDER BY name"):
        if specialty and (p["specialty"] or "").lower() != specialty.lower(): continue
        sl = db.q("SELECT starts_at FROM slots WHERE provider_id=? AND status='open' AND starts_at > ? ORDER BY starts_at", (p["id"], now))
        n = p["rating_count"] or 0
        rows.append({"id": p["id"], "name": p["name"], "specialty": p["specialty"], "clinic": p["clinic_name"], "fee": p["fee"],
                     "rating": round(p["rating_sum"] / n, 1) if n else None, "reviews": n, "open_slots": len(sl), "next_slot": sl[0]["starts_at"] if sl else None})
    return {"providers": rows, "types": [{"id": k, "label": v[0], "percent": v[1]} for k, v in CONSULT_TYPES.items()],
            "specialties": sorted({r["specialty"] for r in rows if r["specialty"]}), "platform_fee": rupees(config.PLATFORM_FEE_PAISE), "sample_data": True}

@router.get("/consult/providers/{pid}/slots")
def slots(pid: int, u=Depends(require("patient"))):
    _expire(); now = (_ist() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
    return db.q("SELECT id, starts_at FROM slots WHERE provider_id=? AND status='open' AND starts_at > ? ORDER BY starts_at LIMIT 60", (pid, now))


class QuoteIn(BaseModel):
    provider_id: int; slot_id: int; consult_type: Literal["first_visit", "follow_up"] = "first_visit"; patient_id: int
    summary_id: int | None = None

def _validate_choice(u, q):
    can_view_patient(u, q.patient_id)
    pr = db.q("SELECT * FROM providers WHERE id=? AND kind='doctor' AND active=1", (q.provider_id,), one=True)
    if not pr or not pr["fee"] or pr["fee"] <= 0: raise HTTPException(404, "This doctor is not available for booking")
    sl = db.q("SELECT * FROM slots WHERE id=? AND provider_id=?", (q.slot_id, q.provider_id), one=True)
    if not sl: raise HTTPException(404, "That appointment time does not exist")
    if _slot_dt(sl["starts_at"]) < _ist() + timedelta(minutes=30): raise HTTPException(409, "That time is too soon or already passed. Please pick another.")
    if q.summary_id is not None and not db.q("SELECT 1 FROM assistant_summaries WHERE id=? AND user_id=?", (q.summary_id, u["uid"])):
        raise HTTPException(404, "Summary not found")
    return pr, sl

@router.post("/consult/quote")
def quote(q: QuoteIn, u=Depends(require("patient"))):
    _expire(); pr, sl = _validate_choice(u, q)
    return {**quote_out(price(pr["fee"], q.consult_type)), "provider": pr["name"], "specialty": pr["specialty"], "starts_at": sl["starts_at"],
            "available": sl["status"] == "open"}


# ---------- create order ----------
@router.post("/consult/bookings")
def create_booking(q: QuoteIn, u=Depends(require("patient"))):
    if not paypal.configured():
        raise HTTPException(503, "Payments are not switched on yet. The PayPal Sandbox keys are missing on the server.")
    _expire(); pr, sl = _validate_choice(u, q)
    if db.q("SELECT COUNT(*) AS n FROM bookings WHERE user_id=? AND status IN ('pending_payment','payment_failed','capturing')", (u["uid"],), one=True)["n"] >= 3:
        raise HTTPException(429, "You have several unpaid bookings. Please finish or cancel them first.")
    p = price(pr["fee"], q.consult_type)
    # a retry after a failed payment: drop this user's older unpaid booking for the same slot, then hold the slot again
    db.run_count("UPDATE bookings SET status='cancelled', cancelled_at=? WHERE user_id=? AND slot_id=? AND status IN ('pending_payment','payment_failed')", (_utc(), u["uid"], q.slot_id))
    held = db.run_count("UPDATE slots SET status='held', held_by=?, held_until=? WHERE id=? AND provider_id=? AND (status='open' OR (status='held' AND (held_until < ? OR held_by=?)))",
                        (u["uid"], _utc_in(config.HOLD_MINUTES), q.slot_id, q.provider_id, _utc(), u["uid"]))
    if held != 1: raise HTTPException(409, "Someone just took that time. Please pick another.")
    ref = "MPC-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    bid = db.run("""INSERT INTO bookings(ref,user_id,patient_id,provider_id,slot_id,provider_name,specialty,consult_type,starts_at,fee_paise,platform_fee_paise,
                    total_paise,charge_currency,charge_value,fx_rate,status,summary_id,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (ref, u["uid"], q.patient_id, pr["id"], sl["id"], pr["name"], pr["specialty"], q.consult_type, sl["starts_at"], p["fee_paise"], p["platform_fee_paise"],
                  p["total_paise"], p["currency"], p["charge_value"], p["rate"], "pending_payment", q.summary_id, _utc(), _utc_in(config.HOLD_MINUTES)))
    try:
        order = paypal.create_order(ref, p["charge_value"], p["currency"], f"Sandbox demo: {CONSULT_TYPES[q.consult_type][0]} with {pr['name']}", f"ord-{ref}")
    except paypal.PayPalError as e:
        log.error("create order failed: %s", e)
        db.run("UPDATE bookings SET status='failed' WHERE id=?", (bid,)); db.run_count("UPDATE slots SET status='open', held_by=NULL, held_until=NULL WHERE id=?", (sl["id"],))
        raise HTTPException(502, "PayPal could not start the payment. Please try again in a moment.")
    db.run("UPDATE bookings SET paypal_order_id=? WHERE id=?", (order["id"], bid))
    return {"order_id": order["id"], "booking": booking_out(db.q("SELECT * FROM bookings WHERE id=?", (bid,), one=True))}


# ---------- capture + server-side verification ----------
def _check_order(order, b):
    """Return (state, capture). state: paid | pending | failed | mismatch. Trusts only what PayPal returned to the server."""
    try:
        pu = order["purchase_units"][0]; cap = pu["payments"]["captures"][0]
    except (KeyError, IndexError, TypeError):
        return "failed", None
    if (pu.get("custom_id") or pu.get("reference_id")) != b["ref"]: return "mismatch", cap
    amt = cap.get("amount", {})
    if amt.get("currency_code") != b["charge_currency"] or Decimal(str(amt.get("value", "-1"))) != Decimal(b["charge_value"]): return "mismatch", cap
    return {"COMPLETED": "paid", "PENDING": "pending"}.get(cap.get("status"), "failed"), cap

def finalize_paid(b, capture_id):
    """Atomic: only the first caller moves the booking to paid. Books the slot and records the payment in Bills."""
    moved = db.run_count("UPDATE bookings SET status='paid', paypal_capture_id=?, paid_at=? WHERE id=? AND status IN ('pending_payment','payment_failed','capturing','payment_pending')",
                         (capture_id, _utc(), b["id"]))
    if moved != 1: return False
    db.run_count("UPDATE slots SET status='booked', held_by=?, held_until=NULL WHERE id=?", (b["user_id"], b["slot_id"]))
    bill = db.run("INSERT INTO bills(patient_id,amount,date,description,category,provider_name,status,created_by,payment_method,invoice_no) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (b["patient_id"], rupees(b["total_paise"]), _ist().date().isoformat(), f"Online consultation (sandbox demo), {b['starts_at'].replace('T', ' ')}",
                   "consultation", b["provider_name"], "paid", b["user_id"], "PayPal", b["ref"]))
    db.run("UPDATE bookings SET bill_id=? WHERE id=?", (bill, b["id"]))
    return True

class CaptureIn(BaseModel):
    order_id: str

@router.post("/consult/bookings/{ref}/capture")
def capture(ref: str, c: CaptureIn, u=Depends(require("patient"))):
    _expire(); b = _mine(u, ref)
    if b["status"] == "paid": return {"booking": booking_out(b), "already": True}
    if b["status"] in ("cancelled", "expired", "refunded", "failed"):
        raise HTTPException(409, "This booking is no longer open. If PayPal asked you to pay, nothing was charged. Please start again.")
    if c.order_id != b["paypal_order_id"]: raise HTTPException(422, "This payment does not belong to this booking")
    sl = db.q("SELECT * FROM slots WHERE id=?", (b["slot_id"],), one=True)
    if not sl or sl["status"] != "held" or sl["held_by"] != u["uid"]:
        db.run_count("UPDATE bookings SET status='expired' WHERE id=? AND status IN ('pending_payment','payment_failed')", (b["id"],))
        raise HTTPException(409, "Your hold on this time ended before payment finished. Nothing was charged. Please book again.")
    if db.run_count("UPDATE bookings SET status='capturing' WHERE id=? AND status IN ('pending_payment','payment_failed')", (b["id"],)) != 1:
        return {"booking": booking_out(db.q("SELECT * FROM bookings WHERE id=?", (b["id"],), one=True)), "processing": True}
    try:
        order = paypal.capture_order(b["paypal_order_id"], f"cap-{ref}")
    except paypal.PayPalError as e:
        if e.issue == "ORDER_ALREADY_CAPTURED":
            order = paypal.get_order(b["paypal_order_id"])
        else:
            db.run("UPDATE bookings SET status='payment_failed' WHERE id=? AND status='capturing'", (b["id"],))
            msg = {"INSTRUMENT_DECLINED": "PayPal could not use that payment method. Please choose another one.",
                   "PAYER_ACTION_REQUIRED": "PayPal needs you to confirm the payment again."}.get(e.issue, "The payment did not go through. You were not charged. Please try again.")
            raise HTTPException(402, msg)
    except Exception:
        log.exception("capture error"); db.run("UPDATE bookings SET status='payment_failed' WHERE id=? AND status='capturing'", (b["id"],))
        raise HTTPException(502, "We could not reach PayPal. If you were charged, your booking will be confirmed shortly. Please check again in a minute.")
    state, cap = _check_order(order, b)
    if state == "paid":
        finalize_paid(b, cap["id"])
    elif state == "pending":
        db.run("UPDATE bookings SET status='payment_pending', paypal_capture_id=? WHERE id=?", (cap["id"], b["id"]))
    elif state == "mismatch":
        log.error("payment mismatch for %s", ref); db.run("UPDATE bookings SET status='needs_review', paypal_capture_id=? WHERE id=?", (cap and cap.get("id"), b["id"]))
        raise HTTPException(422, "We could not verify this payment, so the booking is not confirmed. Please contact support with your reference.")
    else:
        db.run("UPDATE bookings SET status='payment_failed' WHERE id=?", (b["id"],))
        raise HTTPException(402, "The payment was not completed. You were not charged. Please try again.")
    return {"booking": booking_out(db.q("SELECT * FROM bookings WHERE id=?", (b["id"],), one=True))}

@router.post("/consult/bookings/{ref}/abandon")
def abandon(ref: str, u=Depends(require("patient"))):
    """Buyer closed or cancelled the PayPal window. Frees the slot. Safe to call twice."""
    b = _mine(u, ref)
    if b["status"] in OPEN_STATES and db.run_count("UPDATE bookings SET status='cancelled', cancelled_at=? WHERE id=? AND status IN ('pending_payment','payment_failed')", (_utc(), b["id"])):
        _release(b)
    return {"booking": booking_out(db.q("SELECT * FROM bookings WHERE id=?", (b["id"],), one=True))}

@router.post("/consult/bookings/{ref}/cancel")
def cancel(ref: str, u=Depends(require("patient"))):
    b = _mine(u, ref)
    if b["status"] in OPEN_STATES: return abandon(ref, u)
    if b["status"] != "paid": raise HTTPException(409, "This booking cannot be cancelled")
    if _slot_dt(b["starts_at"]) - _ist() < timedelta(hours=config.REFUND_WINDOW_HOURS):
        raise HTTPException(409, f"Refunds are only available up to {config.REFUND_WINDOW_HOURS} hours before the appointment.")
    if db.run_count("UPDATE bookings SET status='refunding' WHERE id=? AND status='paid'", (b["id"],)) != 1:
        raise HTTPException(409, "A refund is already being processed")
    try:
        r = paypal.refund_capture(b["paypal_capture_id"], f"ref-{ref}", "Consultation cancelled by patient")
    except Exception as e:
        log.error("refund failed: %s", e); db.run("UPDATE bookings SET status='paid' WHERE id=? AND status='refunding'", (b["id"],))
        raise HTTPException(502, "PayPal could not process the refund right now. Your booking is unchanged. Please try again.")
    db.run("UPDATE bookings SET status='refunded', refund_status=?, refund_id=?, cancelled_at=? WHERE id=?", (r.get("status", "COMPLETED"), r.get("id"), _utc(), b["id"]))
    _release(b)
    if b["bill_id"]: db.run("UPDATE bills SET status='refunded' WHERE id=?", (b["bill_id"],))
    return {"booking": booking_out(db.q("SELECT * FROM bookings WHERE id=?", (b["id"],), one=True))}


# ---------- reading ----------
@router.get("/consult/bookings")
def my_bookings(u=Depends(require("patient"))):
    _expire()
    return [booking_out(b) for b in db.q("SELECT * FROM bookings WHERE user_id=? AND status NOT IN ('failed') ORDER BY id DESC LIMIT 200", (u["uid"],))]

@router.get("/consult/bookings/{ref}")
def one_booking(ref: str, u=Depends(require("patient"))):
    b = _mine(u, ref); out = booking_out(b)
    if b["summary_id"]:
        s = db.q("SELECT summary FROM assistant_summaries WHERE id=? AND user_id=?", (b["summary_id"], u["uid"]), one=True)
        out["shared_summary"] = json.loads(s["summary"]) if s else None
    return out

@router.get("/consult/overview")
def overview(u=Depends(require("patient"))):
    _expire(); rows = [booking_out(b) for b in db.q("SELECT * FROM bookings WHERE user_id=? AND status IN ('paid','refunded') ORDER BY starts_at", (u["uid"],))]
    now = _ist().strftime("%Y-%m-%dT%H:%M")
    paid = [r for r in rows if r["status"] == "paid"]
    return {"upcoming": [r for r in paid if r["starts_at"] >= now][:5], "recent": sorted([r for r in rows if r["starts_at"] < now or r["status"] == "refunded"], key=lambda r: r["starts_at"], reverse=True)[:5],
            "paid_count": len(paid), "paid_total_inr": round(sum(r["total_inr"] for r in paid), 2)}


# ---------- admin ----------
@router.post("/consult/admin/sample-slots")
def admin_slots(u=Depends(require("admin"))):
    return {"created": ensure_sample_slots()}

@router.get("/consult/admin/bookings")
def admin_bookings(u=Depends(require("admin"))):
    return [booking_out(b) for b in db.q("SELECT * FROM bookings ORDER BY id DESC LIMIT 100")]


# ---------- webhook ----------
def _booking_for(resource):
    ref = resource.get("custom_id") or resource.get("invoice_id")
    if ref:
        b = db.q("SELECT * FROM bookings WHERE ref=?", (ref,), one=True)
        if b: return b
    cap = resource.get("id")
    for l in resource.get("links", []):
        if l.get("rel") == "up" and "/captures/" in l.get("href", ""): cap = l["href"].rsplit("/", 1)[-1]
    return db.q("SELECT * FROM bookings WHERE paypal_capture_id=?", (cap,), one=True) if cap else None

@router.post("/paypal/webhook")
async def webhook(request: Request):
    if not config.PAYPAL_WEBHOOK_ID: raise HTTPException(503, "Webhook not configured")
    try: event = await request.json()
    except ValueError: raise HTTPException(400, "Bad JSON")
    if not paypal.verify_webhook(request.headers, event): raise HTTPException(400, "Signature check failed")
    eid, etype, res = event.get("id"), event.get("event_type", ""), event.get("resource") or {}
    if not eid: raise HTTPException(400, "Missing event id")
    if db.q("SELECT 1 FROM paypal_events WHERE event_id=?", (eid,)): return {"ok": True, "duplicate": True}
    b = _booking_for(res)
    if b:
        if etype == "PAYMENT.CAPTURE.COMPLETED":
            amt = res.get("amount", {})
            good = amt.get("currency_code") == b["charge_currency"] and Decimal(str(amt.get("value", "-1"))) == Decimal(b["charge_value"])
            if not good: db.run("UPDATE bookings SET status='needs_review' WHERE id=? AND status!='paid'", (b["id"],))
            elif b["status"] in ("cancelled", "expired"): db.run("UPDATE bookings SET status='needs_review', paypal_capture_id=? WHERE id=?", (res.get("id"), b["id"]))
            else: finalize_paid(b, res.get("id"))
        elif etype in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
            db.run("UPDATE bookings SET status='payment_failed' WHERE id=? AND status IN ('capturing','payment_pending','pending_payment')", (b["id"],))
        elif etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
            if db.run_count("UPDATE bookings SET status='refunded', refund_status='COMPLETED' WHERE id=? AND status IN ('paid','refunding')", (b["id"],)):
                _release(b)
                if b["bill_id"]: db.run("UPDATE bills SET status='refunded' WHERE id=?", (b["bill_id"],))
    db.run("INSERT INTO paypal_events(event_id,event_type,booking_ref,created_at) VALUES(?,?,?,?)", (eid, etype, b["ref"] if b else None, _utc()))
    return {"ok": True}
