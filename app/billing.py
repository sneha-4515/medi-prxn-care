"""Billing: patient-entered bills, clinic (admin) itemised invoices, monthly summaries and CSV export.
All money maths is done in whole paise (integers) so totals never drift by a fraction of a rupee."""
import csv, io, json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from . import db
from .common import family_of, can_view_patient, hidden_from_family
from .security import require

router = APIRouter(prefix="/bills", tags=["billing"])
CATEGORIES = ("consultation", "lab_test", "pharmacy", "procedure", "other")
MAX_PAISE = 1_000_000_000          # 1 crore rupees: anything above is almost surely a typing mistake

def to_paise(x) -> int: return int((Decimal(str(x)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
def rupees(p: int) -> float: return p / 100
def paise_of(row) -> int: return to_paise(row["amount"] or 0)

class Item(BaseModel):
    description: str = Field(..., min_length=1, max_length=120)
    quantity: int = Field(1, ge=1, le=1000)
    unit_price: float = Field(..., ge=0, le=10_000_000, allow_inf_nan=False)

class BillIn(BaseModel):
    patient_id: int
    date: str
    category: Literal["consultation", "lab_test", "pharmacy", "procedure", "other"] = "other"
    provider_name: str = Field("", max_length=120)
    description: str = Field("", max_length=300)
    amount: float | None = Field(None, gt=0, le=10_000_000, allow_inf_nan=False)
    items: list[Item] | None = None
    status: Literal["paid", "pending"] = "paid"
    payment_method: str | None = Field(None, max_length=30)

def _validate(b: BillIn):
    try: d = date.fromisoformat(b.date)
    except ValueError: raise HTTPException(422, "Date must be YYYY-MM-DD.")
    if d > date.today() + timedelta(days=1): raise HTTPException(422, "A bill cannot be dated in the future.")
    if d.year < 2000: raise HTTPException(422, "Date is too far in the past.")
    if b.items:
        total = sum(it.quantity * to_paise(it.unit_price) for it in b.items)
        if b.amount is not None and to_paise(b.amount) != total:
            raise HTTPException(422, "Amount does not match the line items.")
    elif b.amount is None:
        raise HTTPException(422, "Enter an amount or add line items.")
    else:
        total = to_paise(b.amount)
    if total <= 0: raise HTTPException(422, "Bill total must be more than zero.")
    if total > MAX_PAISE: raise HTTPException(422, "Bill total is too large. Please check the amount.")
    return total

def _row_out(r, names):
    return {"id": r["id"], "patient_id": r["patient_id"], "member": names.get(r["patient_id"], ""), "date": r["date"], "category": r["category"] or "other",
            "provider_name": r["provider_name"] or "", "description": r["description"] or "", "amount": round(rupees(paise_of(r)), 2),
            "status": r["status"] or "paid", "invoice_no": r["invoice_no"], "payment_method": r["payment_method"],
            "items": json.loads(r["items"]) if r["items"] else None, "created_by_clinic": r["created_by"] is not None and bool(r["invoice_no"])}

def _scope(u):
    """Patients see their family's bills (minus members whose records the doctor marked private). Admins see every patient."""
    if u["role"] == "admin":
        rows = db.q("SELECT id,name FROM patients"); return {r["id"]: r["name"] for r in rows}
    return {m["id"]: m["name"] for m in family_of(u) if not hidden_from_family(m)}

def _fetch(u, patient_id=None, month=None, category=None, status=None):
    names = _scope(u)
    ids = [patient_id] if patient_id else list(names)
    if patient_id and patient_id not in names: raise HTTPException(403, "Not your family member")
    if not ids: return [], names
    marks = ",".join("?" * len(ids))
    rows = db.q(f"SELECT * FROM bills WHERE patient_id IN ({marks}) ORDER BY date DESC, id DESC LIMIT 2000", tuple(ids))
    if month: rows = [r for r in rows if (r["date"] or "").startswith(month)]
    if category: rows = [r for r in rows if (r["category"] or "other") == category]
    if status: rows = [r for r in rows if (r["status"] or "paid") == status]
    return rows, names

def _month(m):
    if m is None: return date.today().strftime("%Y-%m")
    try: date.fromisoformat(m + "-01")
    except ValueError: raise HTTPException(422, "Month must be YYYY-MM.")
    return m

def _prev(m):
    y, mo = int(m[:4]), int(m[5:7]); mo -= 1
    if mo == 0: y, mo = y - 1, 12
    return f"{y:04d}-{mo:02d}"

@router.post("")
def add(b: BillIn, u=Depends(require("patient", "admin"))):
    total = _validate(b); can_view_patient(u, b.patient_id)
    if u["role"] == "patient" and b.items: raise HTTPException(403, "Itemised invoices are created by the clinic.")
    bid = db.run("INSERT INTO bills(patient_id,amount,date,description,category,provider_name,status,items,created_by,payment_method) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (b.patient_id, rupees(total), b.date, b.description, b.category, b.provider_name, b.status,
                  json.dumps([it.model_dump() for it in b.items]) if b.items else None, u["uid"], b.payment_method))
    inv = None
    if u["role"] == "admin":
        inv = f"INV-{b.date.replace('-', '')}-{bid:05d}"; db.run("UPDATE bills SET invoice_no=? WHERE id=?", (inv, bid))
    return {"id": bid, "invoice_no": inv, "total": rupees(total)}

@router.get("")
def list_bills(patient_id: int | None = None, month: str | None = None, category: str | None = None, status: str | None = None,
               u=Depends(require("patient", "admin"))):
    if month: _month(month)
    rows, names = _fetch(u, patient_id, month, category, status)
    return [_row_out(r, names) for r in rows]

def summarize(rows, names, month):
    prev = _prev(month); paid = defaultdict(int); by_cat = defaultdict(int); by_member = defaultdict(int); pending = 0; trend = defaultdict(int)
    for r in rows:
        p = paise_of(r); st = r["status"] or "paid"; m = (r["date"] or "")[:7]
        if st == "paid": trend[m] += p
        if m == month:
            if st == "paid": paid["total"] += p; by_cat[r["category"] or "other"] += p; by_member[names.get(r["patient_id"], "")] += p
        if st == "pending": pending += p
    months, y, mo = [], int(month[:4]), int(month[5:7])
    for _ in range(6):
        months.append(f"{y:04d}-{mo:02d}"); mo -= 1
        if mo == 0: y, mo = y - 1, 12
    this, last = paid["total"], trend.get(prev, 0)
    return {"month": month, "spent": rupees(this), "previous_month": prev, "previous_spent": rupees(last),
            "change_percent": round((this - last) * 100 / last, 1) if last else None, "pending_total": rupees(pending),
            "by_category": {k: rupees(v) for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
            "by_member": {k: rupees(v) for k, v in sorted(by_member.items(), key=lambda kv: -kv[1])},
            "trend": [{"month": m, "spent": rupees(trend.get(m, 0))} for m in reversed(months)]}

@router.get("/summary")
def summary(month: str | None = None, patient_id: int | None = None, u=Depends(require("patient"))):
    month = _month(month); rows, names = _fetch(u, patient_id)
    return summarize(rows, names, month)

def member_spend(patient_id, today=None):
    """Exact spend figures for the chatbot, so the AI never has to add up numbers itself."""
    today = today or date.today(); this = today.strftime("%Y-%m"); last = _prev(this)
    rows = db.q("SELECT * FROM bills WHERE patient_id=?", (patient_id,))
    s = summarize(rows, {patient_id: ""}, this); l = summarize(rows, {patient_id: ""}, last)
    return {"this_month_paid": s["spent"], "last_month_paid": l["spent"], "last_month_by_category": l["by_category"], "pending_total": s["pending_total"]}

@router.put("/{bid}")
def update(bid: int, b: BillIn, u=Depends(require("patient", "admin"))):
    r = db.q("SELECT * FROM bills WHERE id=?", (bid,), one=True)
    if not r: raise HTTPException(404, "Bill not found")
    can_view_patient(u, r["patient_id"])
    if u["role"] == "patient" and (r["created_by"] != u["uid"] or r["invoice_no"]): raise HTTPException(403, "Clinic invoices cannot be edited by the patient.")
    if b.patient_id != r["patient_id"]: raise HTTPException(422, "A bill cannot be moved to another person.")
    total = _validate(b)
    db.run("UPDATE bills SET amount=?,date=?,description=?,category=?,provider_name=?,status=?,items=?,payment_method=? WHERE id=?",
           (rupees(total), b.date, b.description, b.category, b.provider_name, b.status,
            json.dumps([it.model_dump() for it in b.items]) if b.items else r["items"], b.payment_method, bid))
    return {"ok": True}

@router.post("/{bid}/paid")
def mark_paid(bid: int, u=Depends(require("patient", "admin"))):
    r = db.q("SELECT * FROM bills WHERE id=?", (bid,), one=True)
    if not r: raise HTTPException(404, "Bill not found")
    can_view_patient(u, r["patient_id"]); db.run("UPDATE bills SET status='paid' WHERE id=?", (bid,)); return {"ok": True}

@router.delete("/{bid}")
def delete(bid: int, u=Depends(require("patient", "admin"))):
    r = db.q("SELECT * FROM bills WHERE id=?", (bid,), one=True)
    if not r: raise HTTPException(404, "Bill not found")
    can_view_patient(u, r["patient_id"])
    if u["role"] == "patient" and (r["created_by"] != u["uid"] or r["invoice_no"]): raise HTTPException(403, "Clinic invoices cannot be deleted by the patient.")
    db.run("DELETE FROM bills WHERE id=?", (bid,)); return {"ok": True}

def _safe_cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s       # stops spreadsheet formula injection

@router.get("/export.csv")
def export(month: str | None = None, u=Depends(require("patient", "admin"))):
    if month: _month(month)
    rows, names = _fetch(u, None, month)
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["Date", "Member", "Category", "Provider", "Description", "Amount (INR)", "Status", "Invoice no"])
    for r in rows:
        o = _row_out(r, names)
        w.writerow([o["date"], _safe_cell(o["member"]), o["category"], _safe_cell(o["provider_name"]), _safe_cell(o["description"]), f'{o["amount"]:.2f}', o["status"], o["invoice_no"] or ""])
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="bills-{month or "all"}.csv"'})
