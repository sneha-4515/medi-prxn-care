import os, logging
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ENV = os.getenv("ENV", "dev")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
DATABASE_URL = os.getenv("DATABASE_URL")          # postgresql://... (Cloud SQL); unset => SQLite file
DB_PATH = os.getenv("DB_PATH", "mediprxncare.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL")   # optional backup model name
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DEMO_SEED = os.getenv("DEMO_SEED") == "1"

# --- PayPal (Sandbox only). Client ID is public; the secret never leaves the server. ---
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID")             # required to accept webhooks
PAYPAL_CURRENCY = os.getenv("PAYPAL_CURRENCY", "USD")          # INR is not available to most sandbox accounts
INR_PER_UNIT = os.getenv("INR_PER_UNIT", "85")                 # fixed demo exchange rate: rupees per 1 unit of PAYPAL_CURRENCY
PLATFORM_FEE_PAISE = int(os.getenv("PLATFORM_FEE_PAISE", "4900"))   # booking fee, Rs 49
HOLD_MINUTES = int(os.getenv("HOLD_MINUTES", "15"))            # how long a slot is held while the patient pays
REFUND_WINDOW_HOURS = int(os.getenv("REFUND_WINDOW_HOURS", "24"))

log = logging.getLogger("mediprxn")
if ENV == "production":
    if SECRET_KEY == "dev-secret":
        raise RuntimeError("SECRET_KEY must be set when ENV=production")
    if not DATABASE_URL:
        log.warning("ENV=production without DATABASE_URL: SQLite on Cloud Run is ephemeral, data is lost on restart")
