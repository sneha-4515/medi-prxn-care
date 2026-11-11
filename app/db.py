"""Tiny data layer: SQLite for local/dev, PostgreSQL (Cloud SQL) when DATABASE_URL is set.
Call sites use `?` placeholders; they are translated for Postgres."""
import sqlite3
from contextlib import closing
from . import config

PG = bool(config.DATABASE_URL)
_pool = None

PK = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users(
  id {PK}, name TEXT, email TEXT UNIQUE, pw_hash TEXT,
  role TEXT CHECK(role IN ('doctor','patient','admin')));
CREATE TABLE IF NOT EXISTS patients(
  id {PK}, owner_user_id INTEGER, name TEXT, age INTEGER, gender TEXT,
  relation TEXT DEFAULT 'self', family_number TEXT, self_reported_history TEXT,
  allergies TEXT DEFAULT '', qr_token TEXT UNIQUE, private_from_family INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS prescriptions(
  id {PK}, patient_id INTEGER, doctor_id INTEGER, medicine TEXT, dosage TEXT,
  timing TEXT, frequency_per_day INTEGER, duration_days INTEGER, cause TEXT,
  start_date TEXT, next_followup TEXT, lab_tests TEXT, source TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS documents(
  id {PK}, patient_id INTEGER, kind TEXT, extracted_json TEXT,
  status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS bills(
  id {PK}, patient_id INTEGER, amount REAL, date TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS providers(
  id {PK}, kind TEXT CHECK(kind IN ('doctor','lab')), name TEXT, specialty TEXT, clinic_name TEXT, address TEXT, phone TEXT,
  lat REAL, lon REAL, fee REAL, rating_sum REAL DEFAULT 0, rating_count INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS lab_prices(
  id {PK}, provider_id INTEGER, test_name TEXT, test_key TEXT, price REAL);
CREATE TABLE IF NOT EXISTS provider_reviews(
  id {PK}, provider_id INTEGER, user_id INTEGER, stars INTEGER, UNIQUE(provider_id, user_id));
CREATE TABLE IF NOT EXISTS chat_history(
  id {PK}, user_id INTEGER, patient_id INTEGER, question TEXT, answer TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS checkups(
  id {PK}, patient_id INTEGER, key TEXT, done_on TEXT);
CREATE TABLE IF NOT EXISTS slots(
  id {PK}, provider_id INTEGER, starts_at TEXT, status TEXT DEFAULT 'open', held_by INTEGER, held_until TEXT, UNIQUE(provider_id, starts_at));
CREATE TABLE IF NOT EXISTS bookings(
  id {PK}, ref TEXT UNIQUE, user_id INTEGER, patient_id INTEGER, provider_id INTEGER, slot_id INTEGER,
  provider_name TEXT, specialty TEXT, consult_type TEXT, starts_at TEXT,
  fee_paise INTEGER, platform_fee_paise INTEGER, total_paise INTEGER,
  charge_currency TEXT, charge_value TEXT, fx_rate TEXT,
  status TEXT, paypal_order_id TEXT UNIQUE, paypal_capture_id TEXT, summary_id INTEGER, bill_id INTEGER,
  refund_status TEXT, refund_id TEXT, created_at TEXT, expires_at TEXT, paid_at TEXT, cancelled_at TEXT);
CREATE TABLE IF NOT EXISTS paypal_events(
  id {PK}, event_id TEXT UNIQUE, event_type TEXT, booking_ref TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS assistant_summaries(
  id {PK}, user_id INTEGER, patient_id INTEGER, summary TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS ix_slots_provider ON slots(provider_id, starts_at);
CREATE INDEX IF NOT EXISTS ix_patients_owner ON patients(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_rx_patient ON prescriptions(patient_id);
CREATE INDEX IF NOT EXISTS ix_checkups_patient ON checkups(patient_id);
CREATE INDEX IF NOT EXISTS ix_providers_kind ON providers(kind, active, lat);
CREATE INDEX IF NOT EXISTS ix_labprices_provider ON lab_prices(provider_id, test_key);
"""

def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=True)
    return _pool

def _sqlite():
    c = sqlite3.connect(config.DB_PATH); c.row_factory = sqlite3.Row; return c

BILL_COLUMNS = {"category": "TEXT DEFAULT 'other'", "provider_name": "TEXT", "status": "TEXT DEFAULT 'paid'", "items": "TEXT",
                "invoice_no": "TEXT", "created_by": "INTEGER", "payment_method": "TEXT"}

def _existing_columns(table):
    if PG:
        with _get_pool().connection() as c:
            return {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,)).fetchall()}
    with closing(_sqlite()) as c:
        return {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}

def _migrate():
    """Add columns that older databases do not have (CREATE TABLE IF NOT EXISTS never alters a table)."""
    have = _existing_columns("bills")
    for col, ddl in BILL_COLUMNS.items():
        if col not in have:
            stmt = f"ALTER TABLE bills ADD COLUMN {col} {ddl}"
            if PG:
                with _get_pool().connection() as c: c.execute(stmt)
            else:
                with closing(_sqlite()) as c: c.execute(stmt); c.commit()

def init():
    stmts = [s.strip() for s in SCHEMA.split(";") if s.strip()]
    if PG:
        with _get_pool().connection() as c:
            for s in stmts: c.execute(s)
    else:
        with closing(_sqlite()) as c:
            for s in stmts: c.execute(s)
            c.commit()
    _migrate()

def q(sql, args=(), one=False):
    if PG:
        with _get_pool().connection() as c:
            rows = [dict(r) for r in c.execute(sql.replace("?", "%s"), args).fetchall()]
    else:
        with closing(_sqlite()) as c:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    """Execute a write. Returns the new row id for INSERTs."""
    insert = sql.lstrip().upper().startswith("INSERT")
    if PG:
        with _get_pool().connection() as c:
            cur = c.execute(sql.replace("?", "%s") + (" RETURNING id" if insert else ""), args)
            return cur.fetchone()["id"] if insert else None
    with closing(_sqlite()) as c:
        cur = c.execute(sql, args); c.commit()
        return cur.lastrowid

def run_count(sql, args=()):
    """Execute an UPDATE/DELETE and return how many rows it changed. Used for atomic claims such as holding a slot."""
    if PG:
        with _get_pool().connection() as c:
            return c.execute(sql.replace("?", "%s"), args).rowcount
    with closing(_sqlite()) as c:
        cur = c.execute(sql, args); c.commit()
        return cur.rowcount
