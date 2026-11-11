"""Find the best AND cheapest doctors or lab tests within a hard distance limit (max 10 km).

Distance rules (never relaxed):
  * the search radius can never exceed 10 km; a larger request is rejected, not clamped
  * the radius is reduced by the reported GPS accuracy, so a provider is only shown if it is within the radius
    even if the person is really as far away as the accuracy allows
  * providers without valid coordinates are never shown
Ranking: price is compared with the median of the providers in range; rating is a Bayesian average so a 5.0 from
one review cannot beat 4.6 from hundreds; a quality floor keeps cheap-but-poor options out of every mode."""
import re
from statistics import median
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from . import db, geo
from .security import require

router = APIRouter(prefix="/care", tags=["care search"])
PRIOR_MEAN, PRIOR_WEIGHT = 3.8, 20           # a provider with no reviews starts at 3.8
FEW_REVIEWS = 10
MODES = {"value": (0.5, 0.5), "cheapest": (0.2, 0.8), "best": (0.8, 0.2)}   # (quality weight, price weight)

def norm_key(s): return re.sub(r"\s+", " ", (s or "").strip().lower())
def bayes(rating_sum, count): return ((rating_sum or 0) + PRIOR_MEAN * PRIOR_WEIGHT) / ((count or 0) + PRIOR_WEIGHT)
def clamp(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))
def quality_score(b): return clamp((b - 3.0) / 2.0)
def price_score(price, med): return 1.0 if med <= 0 else clamp(1.5 - price / med)

class CareSearch(BaseModel):
    kind: Literal["doctor", "lab"]
    specialty: str | None = Field(None, max_length=80)
    test: str | None = Field(None, max_length=120)
    lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    radius_km: float = Field(10.0, gt=0, le=geo.MAX_RADIUS_KM, allow_inf_nan=False)
    accuracy_m: float = Field(0.0, ge=0, le=1_000_000, allow_inf_nan=False)
    mode: Literal["value", "cheapest", "best"] = "value"
    min_rating: float = Field(3.5, ge=1, le=5, allow_inf_nan=False)
    max_price: float | None = Field(None, gt=0, allow_inf_nan=False)

def run_search(s: CareSearch):
    if not geo.valid_coord(s.lat, s.lon):
        raise HTTPException(422, "Location is not valid. Allow location access or enter real coordinates.")
    effective = s.radius_km - s.accuracy_m / 1000.0
    if effective <= 0:
        raise HTTPException(422, f"Your location is only accurate to about {round(s.accuracy_m)} m, which is too imprecise to guarantee "
                                 f"results within {s.radius_km:g} km. Move to an open area, or enter coordinates manually.")
    if s.kind == "doctor" and not (s.specialty or "").strip(): raise HTTPException(422, "Choose a specialty.")
    if s.kind == "lab" and not (s.test or "").strip(): raise HTTPException(422, "Choose a lab test.")

    lo, hi = geo.lat_band(s.lat, effective)
    rows = db.q("SELECT * FROM providers WHERE kind=? AND active=1 AND lat IS NOT NULL AND lon IS NOT NULL AND lat BETWEEN ? AND ?", (s.kind, lo, hi))
    if s.kind == "doctor":
        want = norm_key(s.specialty); rows = [r for r in rows if norm_key(r["specialty"]) == want]
        for r in rows: r["price"] = r["fee"]
    else:
        key = norm_key(s.test); prices = {}
        for pr in db.q("SELECT provider_id, price, test_name FROM lab_prices WHERE test_key=?", (key,)): prices[pr["provider_id"]] = pr
        rows = [dict(r, price=prices[r["id"]]["price"], test_name=prices[r["id"]]["test_name"]) for r in rows if r["id"] in prices]

    inside, bad_coords = [], 0
    for r in rows:
        if not geo.valid_coord(r["lat"], r["lon"]) or r["price"] is None: bad_coords += 1; continue
        d = geo.distance_km(s.lat, s.lon, r["lat"], r["lon"])
        if d <= effective: inside.append(dict(r, distance_km=d))          # exact, unrounded comparison
    meta = {"requested_radius_km": s.radius_km, "effective_radius_km": round(effective, 3), "accuracy_m": s.accuracy_m,
            "in_range": len(inside), "skipped_invalid_data": bad_coords, "distance_type": "straight-line (geodesic)", "notes": []}
    if s.accuracy_m > 0:
        meta["notes"].append(f"Your location is accurate to about {round(s.accuracy_m)} m, so only providers within {effective:.2f} km are shown. This guarantees none is beyond {s.radius_km:g} km.")
    meta["notes"].append("Distances are straight-line. Travel by road can be longer.")
    if not inside: return {"results": [], "meta": meta}

    med = median(r["price"] for r in inside)
    for r in inside:
        r["rating"] = bayes(r["rating_sum"], r["rating_count"])
        r["raw_rating"] = round(r["rating_sum"] / r["rating_count"], 2) if r["rating_count"] else None
    kept = [r for r in inside if r["rating"] >= s.min_rating and (s.max_price is None or r["price"] <= s.max_price)]
    meta["after_filters"] = len(kept)
    if not kept:
        meta["notes"].append("Providers are nearby but none meets the rating floor or price limit. Try lowering them.")
        return {"results": [], "meta": meta}
    wq, wp = MODES[s.mode]
    for r in kept: r["score"] = wq * quality_score(r["rating"]) + wp * price_score(r["price"], med)
    if s.mode == "cheapest": kept.sort(key=lambda r: (r["price"], -r["rating"], r["distance_km"], r["id"]))
    elif s.mode == "best": kept.sort(key=lambda r: (-round(r["rating"], 6), r["price"], r["distance_km"], r["id"]))
    else: kept.sort(key=lambda r: (-round(r["score"], 9), r["price"], r["distance_km"], r["id"]))
    cheapest, top = min(r["price"] for r in kept), max(r["rating"] for r in kept)
    best_value = max(kept, key=lambda r: (round(r["score"], 9), -r["price"], -r["distance_km"], -r["id"]))["id"]
    out = []
    for i, r in enumerate(kept, 1):
        beaten = any(o["price"] <= r["price"] and o["rating"] >= r["rating"] and (o["price"] < r["price"] or o["rating"] > r["rating"]) for o in kept)
        badges = [b for b, on in (("Cheapest nearby", r["price"] == cheapest), ("Top rated", r["rating"] == top), ("Best value", r["id"] == best_value),
                                  ("Few reviews", r["rating_count"] < FEW_REVIEWS)) if on]
        out.append({"rank": i, "id": r["id"], "name": r["name"], "specialty": r["specialty"], "clinic_name": r["clinic_name"], "address": r["address"],
                    "phone": r["phone"], "lat": r["lat"], "lon": r["lon"], "price": round(r["price"], 2), "test_name": r.get("test_name"),
                    "rating": round(r["rating"], 2), "raw_rating": r["raw_rating"], "review_count": r["rating_count"],
                    "distance_km": round(r["distance_km"], 2), "score": round(r["score"], 3), "badges": badges, "not_beaten_on_both": not beaten,
                    "price_vs_median": round(r["price"] / med, 2) if med else None})
    meta["median_price"] = round(med, 2)
    return {"results": out, "meta": meta}

@router.post("/search")
def search(s: CareSearch, u=Depends(require("patient", "doctor", "admin"))):
    return run_search(s)

@router.get("/specialties")
def specialties(u=Depends(require("patient", "doctor", "admin"))):
    rows = db.q("SELECT DISTINCT specialty FROM providers WHERE kind='doctor' AND active=1 AND specialty IS NOT NULL")
    return sorted({r["specialty"] for r in rows})

@router.get("/tests")
def tests(u=Depends(require("patient", "doctor", "admin"))):
    seen = {}
    for r in db.q("SELECT lp.test_key, lp.test_name FROM lab_prices lp JOIN providers p ON p.id=lp.provider_id WHERE p.active=1"): seen.setdefault(r["test_key"], r["test_name"])
    return sorted(({"key": k, "name": n} for k, n in seen.items()), key=lambda x: x["name"].lower())

class Review(BaseModel):
    stars: int = Field(..., ge=1, le=5)

@router.post("/providers/{pid}/review")
def review(pid: int, r: Review, u=Depends(require("patient"))):
    p = db.q("SELECT * FROM providers WHERE id=? AND active=1", (pid,), one=True)
    if not p: raise HTTPException(404, "Provider not found")
    prev = db.q("SELECT stars FROM provider_reviews WHERE provider_id=? AND user_id=?", (pid, u["uid"]), one=True)
    if prev:
        db.run("UPDATE provider_reviews SET stars=? WHERE provider_id=? AND user_id=?", (r.stars, pid, u["uid"]))
        db.run("UPDATE providers SET rating_sum=rating_sum+? WHERE id=?", (r.stars - prev["stars"], pid))
    else:
        db.run("INSERT INTO provider_reviews(provider_id,user_id,stars) VALUES(?,?,?)", (pid, u["uid"], r.stars))
        db.run("UPDATE providers SET rating_sum=rating_sum+?, rating_count=rating_count+1 WHERE id=?", (r.stars, pid))
    return {"ok": True}

# ---------- admin: maintain the provider directory ----------
class ProviderIn(BaseModel):
    kind: Literal["doctor", "lab"]
    name: str = Field(..., min_length=2, max_length=120)
    specialty: str | None = Field(None, max_length=80)
    clinic_name: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=250)
    phone: str | None = Field(None, max_length=30)
    lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    fee: float | None = Field(None, gt=0, le=1_000_000, allow_inf_nan=False)
    rating: float | None = Field(None, ge=1, le=5, allow_inf_nan=False)
    review_count: int = Field(0, ge=0, le=1_000_000)

def _check_provider(p: ProviderIn):
    if not geo.valid_coord(p.lat, p.lon): raise HTTPException(422, "Coordinates are not valid (and 0,0 is not allowed).")
    if p.kind == "doctor" and (not p.specialty or p.fee is None): raise HTTPException(422, "A doctor needs a specialty and a consultation fee.")
    if p.rating is not None and p.review_count == 0: raise HTTPException(422, "Give the number of reviews the rating is based on.")

@router.post("/providers")
def add_provider(p: ProviderIn, u=Depends(require("admin"))):
    _check_provider(p)
    pid = db.run("INSERT INTO providers(kind,name,specialty,clinic_name,address,phone,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (p.kind, p.name.strip(), (p.specialty or "").strip() or None, p.clinic_name, p.address, p.phone, p.lat, p.lon, p.fee,
                  (p.rating or 0) * p.review_count, p.review_count))
    return {"id": pid}

@router.get("/providers")
def list_providers(u=Depends(require("admin"))):
    return db.q("SELECT id,kind,name,specialty,clinic_name,address,lat,lon,fee,rating_count,active FROM providers ORDER BY id DESC LIMIT 300")

@router.post("/providers/{pid}/active")
def set_active(pid: int, active: bool, u=Depends(require("admin"))):
    db.run("UPDATE providers SET active=? WHERE id=?", (int(active), pid)); return {"active": active}

@router.post("/load-sample")
def load_sample(u=Depends(require("admin"))):
    """Fill an EMPTY directory with fictional sample providers around Rohini, Delhi, for demos and testing."""
    from .seed import seed_providers
    if not seed_providers(): raise HTTPException(409, "The directory already has providers, so nothing was added.")
    return {"loaded": True}

class TestPrice(BaseModel):
    test_name: str = Field(..., min_length=2, max_length=120)
    price: float = Field(..., gt=0, le=1_000_000, allow_inf_nan=False)

@router.post("/providers/{pid}/tests")
def set_test_price(pid: int, t: TestPrice, u=Depends(require("admin"))):
    p = db.q("SELECT kind FROM providers WHERE id=?", (pid,), one=True)
    if not p or p["kind"] != "lab": raise HTTPException(404, "Lab not found")
    key = norm_key(t.test_name)
    if db.q("SELECT 1 FROM lab_prices WHERE provider_id=? AND test_key=?", (pid, key)):
        db.run("UPDATE lab_prices SET price=?, test_name=? WHERE provider_id=? AND test_key=?", (t.price, t.test_name.strip(), pid, key))
    else:
        db.run("INSERT INTO lab_prices(provider_id,test_name,test_key,price) VALUES(?,?,?,?)", (pid, t.test_name.strip(), key, t.price))
    return {"ok": True}
