"""python seed.py : load demo admin / doctor / patient + a family."""
from app import db
from app.seed import seed_demo, seed_providers
db.init()
seed_providers()
print("seeded: admin@mediprxncare.app/admin123  doctor@mediprxncare.app/doctor123  patient@mediprxncare.app/patient123" if seed_demo() else "demo data already present")
