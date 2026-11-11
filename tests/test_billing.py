import csv, io
from datetime import date, timedelta

def bill(mom, **kw):
    return {"patient_id": mom, "date": date.today().isoformat(), "category": "pharmacy", "amount": 100, **kw}
def post(c, u, who, **kw): return c.post("/bills", json=bill(u["mom"], **kw), headers=u[who])
def month_rows(c, u): return c.get("/bills", params={"month": date.today().strftime("%Y-%m"), "patient_id": u["mom"]}, headers=u["pat"]).json()

def test_add_list_and_exact_totals(client, users):
    for amt in (0.1, 0.2, 10.05):
        assert post(client, users, "pat", amount=amt, description="rounding").status_code == 200
    s = client.get("/bills/summary", headers=users["pat"]).json()
    assert s["spent"] >= 10.35
    rows = [r for r in month_rows(client, users) if r["description"] == "rounding"]
    assert round(sum(r["amount"] for r in rows), 2) == 10.35         # 0.1 + 0.2 + 10.05 with no floating-point drift

def test_validation(client, users):
    assert post(client, users, "pat", amount=-5).status_code == 422
    assert post(client, users, "pat", amount=0).status_code == 422
    assert post(client, users, "pat", amount=99_999_999).status_code == 422
    assert post(client, users, "pat", amount=None).status_code == 422
    assert post(client, users, "pat", date=(date.today() + timedelta(days=10)).isoformat()).status_code == 422
    assert post(client, users, "pat", date="31-12-2025").status_code == 422
    assert post(client, users, "pat", category="gold").status_code == 422
    assert post(client, users, "pat", status="maybe").status_code == 422

def test_clinic_itemised_invoice(client, users):
    items = [{"description": "Consultation", "quantity": 1, "unit_price": 500}, {"description": "ECG", "quantity": 2, "unit_price": 250.50}]
    r = post(client, users, "adm", amount=None, items=items, category="consultation", status="pending")
    assert r.status_code == 200 and r.json()["total"] == 1001.0 and r.json()["invoice_no"].startswith("INV-")
    assert post(client, users, "adm", amount=999, items=items).status_code == 422                       # mismatch with line items
    assert post(client, users, "pat", amount=None, items=items).status_code == 403                      # patients cannot issue invoices
    inv = [x for x in month_rows(client, users) if x["invoice_no"] == r.json()["invoice_no"]][0]
    assert inv["items"][1]["quantity"] == 2 and inv["status"] == "pending"
    assert client.put(f"/bills/{inv['id']}", json=bill(users["mom"], amount=5), headers=users["pat"]).status_code == 403
    assert client.delete(f"/bills/{inv['id']}", headers=users["pat"]).status_code == 403
    assert client.post(f"/bills/{inv['id']}/paid", headers=users["pat"]).status_code == 200            # patient can settle it
    assert [x for x in month_rows(client, users) if x["id"] == inv["id"]][0]["status"] == "paid"

def test_edit_delete_own_bill(client, users):
    bid = post(client, users, "pat", amount=250, description="edit me").json()["id"]
    assert client.put(f"/bills/{bid}", json=bill(users["mom"], amount=300, description="edited"), headers=users["pat"]).status_code == 200
    assert [x for x in month_rows(client, users) if x["id"] == bid][0]["amount"] == 300
    assert client.delete(f"/bills/{bid}", headers=users["pat"]).status_code == 200
    assert not [x for x in month_rows(client, users) if x["id"] == bid]
    assert client.delete(f"/bills/{bid}", headers=users["pat"]).status_code == 404

def test_family_isolation(client, users):
    other = client.post("/auth/signup", json={"name": "O2", "email": f"o2{date.today().toordinal()}{id(users)}@x.io", "password": "password1", "role": "patient", "age": 30}).json()
    H = {"Authorization": "Bearer " + other["token"]}
    assert client.post("/bills", json=bill(users["mom"]), headers=H).status_code == 403
    assert client.get("/bills", params={"patient_id": users["mom"]}, headers=H).status_code == 403
    assert client.get("/bills", headers=H).json() == []
    bid = post(client, users, "pat", amount=77).json()["id"]
    assert client.put(f"/bills/{bid}", json=bill(users["mom"], amount=1), headers=H).status_code == 403
    assert client.delete(f"/bills/{bid}", headers=H).status_code == 403
    assert client.post(f"/bills/{bid}/paid", headers=H).status_code == 403

def test_summary_month_and_pending(client, users):
    last = (date.today().replace(day=1) - timedelta(days=1)).replace(day=15).isoformat()
    post(client, users, "pat", amount=1000, date=last, category="lab_test")
    post(client, users, "pat", amount=400, status="pending", category="consultation")
    s = client.get("/bills/summary", headers=users["pat"]).json()
    assert s["previous_spent"] >= 1000 and s["pending_total"] >= 400 and "lab_test" not in s["by_category"]
    assert s["change_percent"] is not None
    assert len(s["trend"]) == 6 and s["trend"][-1]["month"] == date.today().strftime("%Y-%m")
    assert client.get("/bills/summary", params={"month": "2026-13"}, headers=users["pat"]).status_code == 422
    assert abs(sum(s["by_category"].values()) - s["spent"]) < 0.005
    p = client.get("/bills", params={"status": "pending"}, headers=users["pat"]).json(); assert p and all(x["status"] == "pending" for x in p)

def test_private_member_bills_hidden_from_family(client, users):
    post(client, users, "pat", amount=123, description="private bill")
    client.post(f"/patients/{users['mom']}/privacy", params={"private": "true"}, headers=users["doc"])
    assert not [x for x in client.get("/bills", headers=users["pat"]).json() if x["description"] == "private bill"]
    client.post(f"/patients/{users['mom']}/privacy", params={"private": "false"}, headers=users["doc"])
    assert [x for x in client.get("/bills", headers=users["pat"]).json() if x["description"] == "private bill"]

def test_csv_export_is_safe(client, users):
    post(client, users, "pat", amount=50, description="=HYPERLINK(\"http://evil\")", provider_name="+cmd")
    r = client.get("/bills/export.csv", headers=users["pat"]); assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    rows = list(csv.reader(io.StringIO(r.text))); assert rows[0][0] == "Date"
    bad = [row for row in rows if "evil" in row[4]][0]; assert bad[4].startswith("'=") and bad[3].startswith("'+")

def test_chat_gets_exact_spend(client, users):
    from app.billing import member_spend
    sp = member_spend(users["mom"]); assert set(sp) == {"this_month_paid", "last_month_paid", "last_month_by_category", "pending_total"}
