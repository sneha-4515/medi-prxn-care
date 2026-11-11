"""Bootstrap admin + optional demo data. Safe to call on every startup."""
import secrets
from datetime import date, timedelta
from . import db, config, geo
from .search import norm_key
from .security import hash_pw

def bootstrap_admin():
    if config.ADMIN_EMAIL and config.ADMIN_PASSWORD and not db.q("SELECT 1 FROM users WHERE role='admin'"):
        db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", ("Reception Admin", config.ADMIN_EMAIL, hash_pw(config.ADMIN_PASSWORD), "admin"))

def seed_demo():
    if db.q("SELECT 1 FROM users WHERE email='admin@mediprxncare.app'"): return False
    db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", ("Reception Admin", "admin@mediprxncare.app", hash_pw("admin123"), "admin"))
    did = db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", ("Dr. Meera Kapoor", "doctor@mediprxncare.app", hash_pw("doctor123"), "doctor"))
    uid = db.run("INSERT INTO users(name,email,pw_hash,role) VALUES(?,?,?,?)", ("Sneha", "patient@mediprxncare.app", hash_pw("patient123"), "patient"))
    db.run("INSERT INTO patients(owner_user_id,name,age,gender,relation,qr_token) VALUES(?,?,?,?,?,?)", (uid, "Sneha", 32, "F", "self", secrets.token_urlsafe(16)))
    mom = db.run("INSERT INTO patients(owner_user_id,name,age,gender,relation,self_reported_history,allergies,qr_token) VALUES(?,?,?,?,?,?,?,?)",
                 (uid, "Mom", 58, "F", "mother", "Type 2 diabetes, high BP", "Penicillin", secrets.token_urlsafe(16)))
    t = date.today()
    for med, dose, fr, days, ago, cause, fu in [("Metformin", "500mg", 2, 30, 24, "Diabetes", (t + timedelta(days=9)).isoformat()),
                                                ("Amlodipine", "5mg", 1, 90, 40, "Blood pressure", (t + timedelta(days=21)).isoformat()),
                                                ("Paracetamol", "650mg", 3, 3, 1, "Fever", None)]:
        db.run("INSERT INTO prescriptions(patient_id,doctor_id,medicine,dosage,timing,frequency_per_day,duration_days,cause,start_date,next_followup,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (mom, did, med, dose, "after food", fr, days, cause, (t - timedelta(days=ago)).isoformat(), fu, "doctor"))
    db.run("INSERT INTO checkups(patient_id,key,done_on) VALUES(?,?,?)", (mom, "glucose", (t - timedelta(days=200)).isoformat()))
    this_month = t.replace(day=1)
    last_month = this_month - timedelta(days=1)
    for amt, d0, cat, prov, desc, st in [(1850, last_month.replace(day=min(12, last_month.day)), "consultation", "Demo Heart Clinic", "Cardiology consultation and ECG", "paid"),
                                         (2400, last_month.replace(day=min(18, last_month.day)), "lab_test", "Demo Diagnostics", "HbA1c, lipid profile", "paid"),
                                         (640, this_month, "pharmacy", "Demo Pharmacy", "Monthly medicines", "paid"),
                                         (900, this_month, "consultation", "Dr. Demo Kapoor", "Follow-up visit", "pending")]:
        db.run("INSERT INTO bills(patient_id,amount,date,description,category,provider_name,status,created_by) VALUES(?,?,?,?,?,?,?,?)",
               (mom, amt, d0.isoformat(), desc, cat, prov, st, uid))
    return True

# Demo directory around an approximate point in Rohini, Delhi. Names are fictional. Distances are set exactly so the
# 10 km boundary can be demonstrated: some providers sit just inside (9.4 km) and just outside (10.6 km).
DEMO_CENTER = (28.7380, 77.0800)
_DOCS = [  # name, specialty, fee, rating, reviews, km, bearing
    ("Dr. Anil Verma", "General Physician", 400, 4.4, 320, 1.2, 20), ("Dr. Sunita Rao", "General Physician", 300, 3.1, 410, 2.5, 75),
    ("Dr. Rohit Mehra", "General Physician", 800, 4.8, 560, 4.0, 130), ("Dr. Kavita Singh", "General Physician", 350, 5.0, 1, 3.1, 200),
    ("Dr. Imran Qureshi", "General Physician", 500, 4.6, 210, 9.4, 310), ("Dr. Neha Bansal", "General Physician", 250, 4.5, 180, 10.6, 45),
    ("Dr. Arvind Joshi", "Cardiologist", 1200, 4.7, 480, 5.5, 90), ("Dr. Meena Iyer", "Cardiologist", 900, 4.3, 150, 7.8, 250),
    ("Dr. Sanjay Gupta", "Cardiologist", 1800, 4.9, 700, 3.3, 160), ("Dr. Priya Nair", "Cardiologist", 700, 3.2, 330, 6.1, 10),
    ("Dr. Alok Sharma", "Pediatrician", 500, 4.5, 260, 2.0, 300), ("Dr. Farah Khan", "Pediatrician", 650, 4.7, 340, 6.6, 180),
    ("Dr. Ritu Malhotra", "Dermatologist", 600, 4.4, 190, 4.7, 40), ("Dr. Vikram Sethi", "Dermatologist", 1000, 4.6, 220, 8.2, 120),
]
_LABS = [  # name, km, bearing, rating, reviews, {test: price}
    ("Demo Diagnostics Rohini", 1.8, 60, 4.5, 900, {"HbA1c": 450, "Lipid Profile": 700, "Complete Blood Count (CBC)": 300, "Thyroid Profile (TSH)": 400, "Vitamin D": 900}),
    ("Quick Path Lab", 3.4, 150, 3.2, 700, {"HbA1c": 250, "Lipid Profile": 400, "Complete Blood Count (CBC)": 150, "Thyroid Profile (TSH)": 250, "Vitamin D": 500}),
    ("City Care Pathology", 5.2, 230, 4.6, 640, {"HbA1c": 500, "Lipid Profile": 750, "Complete Blood Count (CBC)": 320, "Thyroid Profile (TSH)": 420, "Vitamin D": 950}),
    ("Metro Health Labs", 7.9, 100, 4.4, 410, {"HbA1c": 380, "Lipid Profile": 600, "Complete Blood Count (CBC)": 240, "Thyroid Profile (TSH)": 350, "Vitamin D": 800}),
    ("Prime Diagnostics", 9.6, 330, 4.7, 300, {"HbA1c": 420, "Lipid Profile": 650, "Complete Blood Count (CBC)": 280, "Thyroid Profile (TSH)": 380, "Vitamin D": 850}),
    ("Budget Scan and Lab", 10.7, 20, 4.8, 520, {"HbA1c": 200, "Lipid Profile": 300, "Complete Blood Count (CBC)": 120, "Thyroid Profile (TSH)": 200, "Vitamin D": 400}),
]

def seed_providers():
    if db.q("SELECT 1 FROM providers LIMIT 1"): return False
    c = DEMO_CENTER
    for name, spec, fee, rating, n, km, brg in _DOCS:
        lat, lon = geo.point_at(c[0], c[1], brg, km)
        db.run("INSERT INTO providers(kind,name,specialty,clinic_name,address,lat,lon,fee,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
               ("doctor", name, spec, "Demo clinic", "Demo data, Delhi", lat, lon, fee, rating * n, n))
    for name, km, brg, rating, n, tests in _LABS:
        lat, lon = geo.point_at(c[0], c[1], brg, km)
        pid = db.run("INSERT INTO providers(kind,name,clinic_name,address,lat,lon,rating_sum,rating_count) VALUES(?,?,?,?,?,?,?,?)",
                     ("lab", name, name, "Demo data, Delhi", lat, lon, rating * n, n))
        for t, price in tests.items():
            db.run("INSERT INTO lab_prices(provider_id,test_name,test_key,price) VALUES(?,?,?,?)", (pid, t, norm_key(t), price))
    return True
