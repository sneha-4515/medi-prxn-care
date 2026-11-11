"""Access helpers shared by the route modules."""
from fastapi import HTTPException
from . import db

def family_of(user):
    return db.q("SELECT * FROM patients WHERE owner_user_id=?", (user["uid"],))

def can_view_patient(user, pid):
    p = db.q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    if not p: raise HTTPException(404, "Patient not found")
    if user["role"] in ("doctor", "admin"): return p
    if p["owner_user_id"] != user["uid"]: raise HTTPException(403, "Not your family member")
    return p

def hidden_from_family(p):
    """A doctor can mark a family member's records private; the account holder's own ("self") profile is never hidden."""
    return bool(p["private_from_family"]) and p["relation"] != "self"
