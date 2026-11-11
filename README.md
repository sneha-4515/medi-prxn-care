# Medi-Prxn Care

> **Built for the Devpost "Build What's Next with PayPal and AI" hackathon.** AI helps a family decide what to do about a health concern, then lets them book and pay for a consultation with **PayPal Checkout (Sandbox)**.
> Providers and appointment times are sample data and PayPal runs in Sandbox mode: **no real money moves and no real consultation is arranged.**

## What was added for the hackathon
| | |
|---|---|
| **Medi AI Assistant** | Floating chat (bottom right of every patient page). Asks one question at a time (concern, duration, severity, age group, history), then gives a plain-language summary, general guidance, warning signs and whether a consultation is advisable. Uses Gemini; falls back to a fixed question flow with no API key. |
| **Safety rules** | Emergency warning signs (chest pain, trouble breathing, stroke signs, heavy bleeding, fits, self-harm and more) are caught by **server-side rules before any AI call** and show 112 / 108 / Tele-MANAS 14416 directions. No diagnosis, no prescriptions, and dose-like text is stripped from replies. Nothing is stored unless the user presses Save. |
| **PayPal booking** | Choose a doctor, pick a slot (held 15 minutes), review the price, pay with PayPal Buttons. The server creates the order, captures it, and **verifies amount, currency and booking reference** before confirming. Webhooks (signature-verified, idempotent) confirm payments if the browser never returns. |
| **Refunds and receipts** | Full refund through the PayPal Refunds API up to 24 hours before the visit; printable receipts; payments also appear in the existing Bills tracker. |
| **New UI** | Redesigned dashboard, consultations, payment history, settings, family profile editing, "explain my report" (Gemini). Login and sign-up are unchanged. |

### How PayPal is used
`POST /consult/bookings` -> server computes the price and calls **Orders v2 create** (`PayPal-Request-Id` for idempotency) -> PayPal JS SDK Buttons approve -> `POST /consult/bookings/{ref}/capture` -> server calls **Orders v2 capture**, checks the captured amount / currency / `custom_id`, then marks the booking paid. Cancel within the window calls **Payments v2 refund**. `POST /paypal/webhook` verifies signatures with **Notifications v1 verify-webhook-signature**. The browser never sends an amount.

### How AI is used
Gemini runs the triage conversation (JSON mode, strict safety prompt, one question per turn), extracts prescriptions from dictation or photos, runs interaction checks, and explains lab reports. See `app/assistant.py` and `app/ai.py`.

## PayPal Sandbox setup (5 minutes)
1. Create a free app at developer.paypal.com (Sandbox) and copy the **Client ID** and **Secret**.
2. `export PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=...` (plus `GEMINI_API_KEY` for the full AI chat).
3. Optional webhook: add a sandbox webhook for `https://YOUR-HTTPS-HOST/paypal/webhook` with events `PAYMENT.CAPTURE.COMPLETED`, `DENIED`, `REFUNDED`; export its ID as `PAYPAL_WEBHOOK_ID`. (For local testing the normal flow works without it.)
4. `DEMO_SEED=1 uvicorn app.main:app --reload`, log in as `patient@mediprxncare.app / patient123`, open **Consultations**, and pay with a **sandbox buyer account** from the PayPal developer dashboard.
Sandbox accounts usually cannot pay in INR, so prices are shown in rupees and charged in USD at a fixed demo rate (`INR_PER_UNIT`).

## Judge quick start
`pip install -r requirements-dev.txt && DEMO_SEED=1 PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=... uvicorn app.main:app` then open http://localhost:8000. `python -m pytest tests -q` runs 86 tests, including the full PayPal flow against a fake PayPal API (double clicks, declines, amount tampering, expiry, refunds, webhooks).

---

## Original project: Medi-Prxn-care

AI prescription and medication tracker for families. Doctors dictate or scan a prescription, Gemini turns it into
structured data, a safety check runs against the patient's history, and the family sees refills, follow-ups,
dose alarms and preventive check-ups for every member.

Stack: FastAPI, vanilla JS (served by FastAPI), SQLite for local dev / PostgreSQL (Cloud SQL) in production, Gemini.

## Features
| Area | What it does |
|---|---|
| Doctor | QR check-in with full history, live transcript (Chrome speech API) or case-paper upload, Gemini extraction, interaction / allergy / duplicate alerts, Approve & dispatch, privacy-from-family toggle, patient chatbot |
| Patient and family | Family dashboard with medicine progress, refill and follow-up tracking, add records 3 ways (table, case paper, transcript) with verify-then-save, Tata 1mg order link, family chatbot with history, personal QR |
| Dose alarms | Dose times derived from times-per-day; browser notifications through a service worker, in-app alerts, "mark taken" |
| Preventive check-ups | Rule-based screening reminders from age, sex and current medicines; mark done, overdue / due-soon tracking |
| Billing | Patients log bills (category, provider, paid or pending), see monthly spend, change vs last month, 6-month trend and per-member totals, and export CSV. The clinic (admin) issues itemised invoices with invoice numbers that patients can print and mark paid. All money maths is in whole paise |
| Find care | Patients find the best and cheapest doctors or lab tests within 10 km, ranked on price and rating together (see "How search works") |
| Admin | Reception registration of first-time patients, clinic invoices, and the doctor and lab directory with prices |

## How search works (find care within 10 km)
- **Distance is exact and never exceeds 10 km.** Requests above 10 km are rejected, not clamped. Distances are WGS-84 geodesic distances, tested across the antimeridian and near the poles.
- **GPS error is subtracted.** If the browser reports a location accurate to 700 m, only providers within 9.3 km are shown, so none can really be beyond 10 km. Accuracy worse than the radius is refused.
- **Providers without valid coordinates (or at 0,0) are never shown.**
- **Distance is straight-line.** Road distance can be longer. A routing API would be needed to enforce road distance.
- **Best and cheapest together.** Rating is a Bayesian average (one 5.0 review cannot beat hundreds of 4.6s). Price is compared with the median in range. Modes: Best value (50/50), Cheapest, Best rated. A minimum rating (default 3.5) applies to every mode, so cheap but poor options never appear.
- **The data is your own directory.** Prices and ratings come from providers the admin adds (the demo seed is fictional) plus patient ratings. Nothing is scraped from the web.

## Run locally
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements-dev.txt
    export GEMINI_API_KEY=...          # optional: without it an offline fallback parser is used
    export DEMO_SEED=1                 # optional: demo logins below
    uvicorn app.main:app --reload      # http://localhost:8000, API docs at /docs
    python -m pytest tests -q          # 86 tests

Demo logins (only with DEMO_SEED=1 or `python seed.py`): patient@mediprxncare.app / patient123,
doctor@mediprxncare.app / doctor123, admin@mediprxncare.app / admin123.

Production-like with Postgres: `docker compose up --build`, then open http://localhost:8080.

## Deploy to Google Cloud Run (with Cloud SQL Postgres)
Prerequisites: `gcloud` installed and logged in (`gcloud auth login`), billing enabled on the project, a Gemini API key from Google AI Studio.

    PROJECT_ID=your-project GEMINI_API_KEY=your-key ADMIN_EMAIL=you@example.com ./deploy/deploy.sh

The script enables the APIs, creates a Cloud SQL Postgres instance, stores SECRET_KEY / DATABASE_URL / GEMINI_API_KEY / ADMIN_PASSWORD in
Secret Manager, builds the container from the Dockerfile and deploys to Cloud Run (HTTPS, which the camera and microphone need).
It prints the URL and the admin login. Check `<url>/healthz`.

Environment variables: see `.env.example`. With `ENV=production` the app refuses to start without `SECRET_KEY`.

## Project layout
    app/        main.py (routes) ai.py (Gemini) db.py (SQLite/Postgres) checkups.py schedule.py security.py seed.py config.py
    static/     single-page frontend, service worker, PWA manifest and icons
    tests/      pytest suite (runs on SQLite, or Postgres when DATABASE_URL is set)
    deploy/     deploy.sh for Cloud Run + Cloud SQL
    Dockerfile  docker-compose.yml

## Testing on a phone
- Location, live camera and voice only work on an **https** link (or `localhost`). A plain `http://192.168.x.x:8000` address blocks them and the app says so. For a quick https link without deploying, run `cloudflared tunnel --url http://localhost:8000` in a second terminal.
- QR check-in has three ways: live camera (https only), **Take a photo of the QR** (works on any link) and **Choose QR image** from the gallery. QR images are decoded in the browser with the bundled jsQR library, so this also works on iPhone Safari and Firefox.
- The Find care lists stay empty until the directory has providers: start with `DEMO_SEED=1` once, run `python seed.py`, or let the admin press **Load sample providers** on the Providers page.

## Known limits
- Dose alarms ring while the app is open or installed and running. Alarms with the phone locked and the app closed need Web Push (planned).
- Check-up intervals are general published guidance, not medical advice. The doctor decides each person's schedule.
- Safety checks are decision support for the doctor. Gemini extraction accuracy on real handwritten papers has not been benchmarked.
- Consultation booking is a sandbox demo on sample providers; it does not connect to real clinic calendars. Lab-result PDF storage is not built.
- Payments are Sandbox only (the code refuses the live PayPal host on purpose).
