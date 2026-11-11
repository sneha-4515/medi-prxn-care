import os, sys, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
if not os.getenv("DATABASE_URL"):
    os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("GEMINI_API_KEY", None)        # tests use the offline parser
from fastapi.testclient import TestClient
from app.main import app
from app import db
from app.seed import seed_providers
from app.security import hash_pw

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

def hdr(c, email, pw):
    return {"Authorization": "Bearer " + c.post("/auth/login", json={"email": email, "password": pw}).json()["token"]}

@pytest.fixture(scope="session")
def users(client):
    for e in ("tdoc@x.io", "tpat@x.io"): db.run("DELETE FROM users WHERE email=?", (e,))
    d = client.post("/auth/signup", json={"name": "Dr T", "email": "tdoc@x.io", "password": "password1", "role": "doctor"}).json()
    p = client.post("/auth/signup", json={"name": "Pat", "email": "tpat@x.io", "password": "password1", "role": "patient", "age": 35}).json()
    H = lambda t: {"Authorization": "Bearer " + t}
    seed_providers()
    db.run("DELETE FROM users WHERE email=?", ("tadmin@x.io",))
    db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", ("Admin T", "tadmin@x.io", hash_pw("password1"), "admin"))
    adm = client.post("/auth/login", json={"email": "tadmin@x.io", "password": "password1"}).json()["token"]
    mom = client.post("/family", json={"name": "Mom", "age": 58, "relation": "mother", "gender": "F", "allergies": "Penicillin"}, headers=H(p["token"])).json()["patient_id"]
    return {"doc": H(d["token"]), "pat": H(p["token"]), "adm": H(adm), "mom": mom}
