import itertools, json, pytest
from app import db, geo
from app.seed import DEMO_CENTER

LAT, LON = DEMO_CENTER
def search(c, u, **kw):
    body = {"kind": "doctor", "specialty": "General Physician", "lat": LAT, "lon": LON, "radius_km": 10, **kw}
    return c.post("/care/search", json=body, headers=u["pat"])
def names(r): return [x["name"] for x in r.json()["results"]]

# ---------- geometry ----------
def test_geodesic_boundary_points():
    for km in (9.99, 10.0, 10.01):
        lat, lon = geo.point_at(LAT, LON, 37, km)
        assert abs(geo.distance_km(LAT, LON, lat, lon) - km) < 1e-6
def test_antimeridian_and_pole_distances():
    lat, lon = geo.point_at(10, 179.999, 90, 5)                 # crosses the 180 degree line
    assert lon < 0 and abs(geo.distance_km(10, 179.999, lat, lon) - 5) < 1e-6
    assert 2.0 < geo.distance_km(89.99, 0, 89.99, 180) < 2.4    # across the pole
def test_valid_coord_rules():
    assert geo.valid_coord(28.7, 77.1)
    for bad in [(0, 0), (91, 10), (-91, 10), (10, 181), (float("nan"), 5), (5, float("inf")), (None, 5), ("x", 5)]:
        assert not geo.valid_coord(*bad)

# ---------- the 10 km rule can never be broken ----------
CENTERS = [(LAT, LON), (60.17, 24.94), (-33.87, 151.21), (10.0, 179.995), (-10.0, -179.995), (64.0, -21.9), (1.35, 103.82)]
@pytest.mark.parametrize("center", CENTERS)
def test_boundary_sweep(client, users, center):
    clat, clon = center; tag = f"ZZ-{abs(clat):.2f}-{abs(clon):.2f}"
    ids = {}
    for brg in range(0, 360, 45):
        for km, inside in ((9.99, True), (10.01, False)):
            lat, lon = geo.point_at(clat, clon, brg, km)
            pid = db.run("INSERT INTO providers(kind,name,specialty,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?)",
                         ("doctor", f"{tag}-{brg}-{km}", tag, lat, lon, 400, 4.5 * 100, 100))
            ids[pid] = inside
    r = client.post("/care/search", json={"kind": "doctor", "specialty": tag, "lat": clat, "lon": clon, "radius_km": 10}, headers=users["pat"]).json()
    got = {x["id"] for x in r["results"]}
    assert got == {i for i, ins in ids.items() if ins}, "every provider at 9.99 km is shown and none at 10.01 km"
    assert all(x["distance_km"] <= 10 for x in r["results"])

def test_gps_accuracy_shrinks_radius(client, users):
    assert "Dr. Imran Qureshi" in names(search(client, users))                       # 9.4 km away
    r = search(client, users, accuracy_m=700); assert "Dr. Imran Qureshi" not in names(r)   # 10 - 0.7 = 9.3 km
    assert r.json()["meta"]["effective_radius_km"] == 9.3
    assert search(client, users, accuracy_m=10_000).status_code == 422                # too imprecise to guarantee 10 km
def test_smaller_radius(client, users):
    r = search(client, users, radius_km=3); assert all(x["distance_km"] <= 3 for x in r.json()["results"]) and r.json()["results"]

def test_outside_everything_returns_empty(client, users):
    r = search(client, users, lat=51.5, lon=-0.12); assert r.status_code == 200 and r.json()["results"] == []

@pytest.mark.parametrize("patch", [{"radius_km": 10.01}, {"radius_km": 50}, {"radius_km": 0}, {"radius_km": -1}, {"lat": 91}, {"lon": 181},
                                   {"lat": 0, "lon": 0}, {"accuracy_m": -5}, {"mode": "nearest"}, {"min_rating": 9}])
def test_bad_input_rejected_never_clamped(client, users, patch):
    assert search(client, users, **patch).status_code == 422
def test_nan_rejected(client, users):
    raw = '{"kind":"doctor","specialty":"General Physician","lat":NaN,"lon":77.0,"radius_km":10}'
    assert client.post("/care/search", content=raw, headers={**users["pat"], "Content-Type": "application/json"}).status_code == 422
def test_missing_filters(client, users):
    assert client.post("/care/search", json={"kind": "doctor", "lat": LAT, "lon": LON}, headers=users["pat"]).status_code == 422
    assert client.post("/care/search", json={"kind": "lab", "lat": LAT, "lon": LON}, headers=users["pat"]).status_code == 422
def test_providers_without_coordinates_never_shown(client, users):
    db.run("INSERT INTO providers(kind,name,specialty,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?)", ("doctor", "NoCoords", "General Physician", None, None, 100, 450, 100))
    db.run("INSERT INTO providers(kind,name,specialty,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?)", ("doctor", "NullIsland", "General Physician", 0.0, 0.0, 100, 450, 100))
    assert "NoCoords" not in names(search(client, users)) and "NullIsland" not in names(search(client, users))

# ---------- best AND cheapest ----------
def test_cheap_but_poor_is_never_recommended(client, users):
    for mode in ("value", "cheapest", "best"):
        assert "Dr. Sunita Rao" not in names(search(client, users, mode=mode))         # cheapest of all (300) but rated 3.1
def test_one_perfect_review_does_not_win(client, users):
    r = search(client, users, mode="best").json()["results"]
    assert r[0]["name"] == "Dr. Rohit Mehra"                                            # 4.8 from 560 reviews, not 5.0 from 1
    kav = [x for x in r if x["name"] == "Dr. Kavita Singh"][0]; assert "Few reviews" in kav["badges"] and kav["rating"] < 4.0
def test_modes(client, users):
    value = search(client, users, mode="value").json()["results"]; cheap = search(client, users, mode="cheapest").json()["results"]
    assert value[0]["name"] == "Dr. Anil Verma" and "Best value" in value[0]["badges"]
    assert [x["price"] for x in cheap] == sorted(x["price"] for x in cheap) and "Cheapest nearby" in cheap[0]["badges"]
    assert all(x["rating"] >= 3.5 for x in value + cheap)
def test_distance_breaks_ties(client, users):
    for i, km in enumerate((6.0, 2.0)):
        lat, lon = geo.point_at(LAT, LON, 270, km)
        db.run("INSERT INTO providers(kind,name,specialty,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?)", ("doctor", f"Tie{i}", "TieSpec", lat, lon, 500, 450, 100))
    r = client.post("/care/search", json={"kind": "doctor", "specialty": "TieSpec", "lat": LAT, "lon": LON}, headers=users["pat"]).json()["results"]
    assert [x["name"] for x in r] == ["Tie1", "Tie0"]
def test_max_price_and_floor(client, users):
    assert all(x["price"] <= 450 for x in search(client, users, max_price=450).json()["results"])
    r = search(client, users, min_rating=5); assert r.json()["results"] == [] and r.json()["meta"]["notes"]
def test_lab_tests(client, users):
    body = {"kind": "lab", "test": "hba1c", "lat": LAT, "lon": LON}
    r = client.post("/care/search", json=body, headers=users["pat"]).json()["results"]; n = [x["name"] for x in r]
    assert "Budget Scan and Lab" not in n          # cheapest and top rated, but 10.7 km away
    assert "Quick Path Lab" not in n               # cheap but rated 3.2
    assert min(x["price"] for x in r) == 380 and all(x["distance_km"] <= 10 for x in r)
def test_catalogs(client, users):
    assert "General Physician" in client.get("/care/specialties", headers=users["pat"]).json()
    assert any(t["key"] == "hba1c" for t in client.get("/care/tests", headers=users["pat"]).json())

# ---------- reviews and the directory ----------
def test_review_changes_rating(client, users):
    pid = db.q("SELECT id FROM providers WHERE name='Dr. Alok Sharma'", one=True)["id"]
    before = db.q("SELECT rating_sum,rating_count FROM providers WHERE id=?", (pid,), one=True)
    assert client.post(f"/care/providers/{pid}/review", json={"stars": 1}, headers=users["pat"]).status_code == 200
    mid = db.q("SELECT rating_sum,rating_count FROM providers WHERE id=?", (pid,), one=True); assert mid["rating_count"] == before["rating_count"] + 1
    client.post(f"/care/providers/{pid}/review", json={"stars": 5}, headers=users["pat"])        # changing a review does not add a second one
    after = db.q("SELECT rating_sum,rating_count FROM providers WHERE id=?", (pid,), one=True)
    assert after["rating_count"] == mid["rating_count"] and abs(after["rating_sum"] - (before["rating_sum"] + 5)) < 1e-6
    assert client.post(f"/care/providers/{pid}/review", json={"stars": 6}, headers=users["pat"]).status_code == 422
def test_directory_admin_only_and_validated(client, users):
    good = {"kind": "doctor", "name": "Dr. New Doc", "specialty": "ENT", "lat": LAT, "lon": LON, "fee": 500}
    assert client.post("/care/providers", json=good, headers=users["pat"]).status_code == 403
    assert client.post("/care/providers", json=good, headers=users["adm"]).status_code == 200
    assert client.post("/care/providers", json={**good, "lat": 0, "lon": 0}, headers=users["adm"]).status_code == 422
    assert client.post("/care/providers", json={**good, "fee": None}, headers=users["adm"]).status_code == 422
    assert client.post("/care/providers", json={**good, "fee": -5}, headers=users["adm"]).status_code == 422
    lab = client.post("/care/providers", json={"kind": "lab", "name": "Lab Z", "lat": LAT, "lon": LON}, headers=users["adm"]).json()["id"]
    assert client.post(f"/care/providers/{lab}/tests", json={"test_name": "Vitamin B12", "price": 600}, headers=users["adm"]).status_code == 200
    assert client.post(f"/care/providers/{lab}/tests", json={"test_name": "vitamin b12 ", "price": 550}, headers=users["adm"]).status_code == 200   # same test, price updated
    assert db.q("SELECT COUNT(*) AS n FROM lab_prices WHERE provider_id=?", (lab,), one=True)["n"] == 1

def test_load_sample_only_into_empty_directory(client, users):
    assert client.post("/care/load-sample", headers=users["pat"]).status_code == 403
    assert client.post("/care/load-sample", headers=users["adm"]).status_code == 409          # already has providers
    for tbl in ("lab_prices", "provider_reviews", "providers"): db.run(f"DELETE FROM {tbl}")
    assert client.get("/care/specialties", headers=users["pat"]).json() == []
    assert client.post("/care/load-sample", headers=users["adm"]).json() == {"loaded": True}
    assert "General Physician" in client.get("/care/specialties", headers=users["pat"]).json()
