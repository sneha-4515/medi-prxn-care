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
| **New UI** | Redesigned dashboard, consultations, payment history, settings, family profile editing, "explain my report" (Gemini). |
| **Admin** | Reception registration of first-time patients, clinic invoices, and the doctor and lab directory with prices |
| **Preventive check-ups** | Rule-based screening reminders from age, sex and current medicines; mark done, overdue / due-soon tracking |
| **Billing**| Patients log bills (category, provider, paid or pending), see monthly spend, change vs last month, 6-month trend and per-member totals, and export CSV. The clinic (admin) issues itemised invoices with invoice numbers that patients can print and mark paid. All money maths is in whole paise |
| **Find care** | Patients find the best and cheapest doctors or lab tests within 10 km, ranked on price and rating together (see "How search works") |
## How search works (find care within 10 km)
- **Distance is exact and never exceeds 10 km.** Requests above 10 km are rejected, not clamped. Distances are WGS-84 geodesic distances, tested across the antimeridian and near the poles.
- **GPS error is subtracted.** If the browser reports a location accurate to 700 m, only providers within 9.3 km are shown, so none can really be beyond 10 km. Accuracy worse than the radius is refused.
- **Providers without valid coordinates (or at 0,0) are never shown.**
- **Distance is straight-line.** Road distance can be longer. A routing API would be needed to enforce road distance.
- **Best and cheapest together.** Rating is a Bayesian average (one 5.0 review cannot beat hundreds of 4.6s). Price is compared with the median in range. Modes: Best value (50/50), Cheapest, Best rated. A minimum rating (default 3.5) applies to every mode, so cheap but poor options never appear.
- **The data is your own directory.** Prices and ratings come from providers the admin adds (the demo seed is fictional) plus patient ratings. Nothing is scraped from the web.

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

## Initial Project: Medi-Prxn-care

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

## Run locally
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements-dev.txt
    export GEMINI_API_KEY=...          # optional: without it an offline fallback parser is used
    export DEMO_SEED=1                 # optional: demo logins below
    uvicorn app.main:app --reload      # http://localhost:8000, API docs at /docs
    python -m pytest tests -q          # 86 tests

Demo logins (only with DEMO_SEED=1 or `python seed.py`): patient@mediprxncare.app / patient123,
doctor@mediprxncare.app / doctor123, admin@mediprxncare.app / admin123.

Production-like with Postgres: `docker compose up --build`, then open http://localhost:8000.

## Deploy

### Render (used for the hackathon demo)
1. Push the repo to GitHub.
2. On [render.com](https://render.com): **New → Web Service**, pick the repo, choose the **Docker** runtime (the repo's `Dockerfile` is used) and the **Free** instance type.
3. Add these environment variables:

| Name | Value |
|---|---|
| `SECRET_KEY` | A long random string (`python -c "import secrets;print(secrets.token_urlsafe(48))"`). Required: with `ENV=production` the app refuses to start without it. |
| `DEMO_SEED` | `1` (creates the demo users, sample doctors and sample appointment times on every start) |
| `GEMINI_API_KEY` | Your key from Google AI Studio |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` (or any model your key can use) |
| `GEMINI_THINKING` | Optional, `minimal` or `low`, for faster replies |
| `ASSIST_TIMEOUT_S` | Optional, seconds the chat waits for Gemini before using the guided flow (default 8) |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | PayPal **Sandbox** app credentials |

4. Set the health check path to `/healthz`. Open `<url>/healthz` and check that `gemini_key` and `paypal_keys` are `true`.

Notes for the free plan: the server sleeps after about 15 minutes without visits (the next load can take about a minute), and the SQLite file is reset when the service restarts. That is fine for a demo because `DEMO_SEED=1` recreates the demo data. Use Postgres (`DATABASE_URL`) for anything that must persist.

### Google Cloud Run with Cloud SQL (optional, the original deployment path)
Prerequisites: `gcloud` installed and logged in (`gcloud auth login`), billing enabled, and a Gemini API key.

    PROJECT_ID=your-project GEMINI_API_KEY=your-key ADMIN_EMAIL=you@example.com ./deploy/deploy.sh

The script enables the APIs, creates a Cloud SQL Postgres instance, stores `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY` and `ADMIN_PASSWORD` in Secret Manager, builds the container and deploys to Cloud Run. It prints the URL and the admin login. To use PayPal there, also add `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` as secrets or environment variables. This route was not used for the hackathon demo.

### Environment variables
See `.env.example`. Never commit `.env`. Values in `.env` override variables left in your terminal.

## Project layout
    app/        main.py (routes) ai.py (Gemini) assistant.py (Medi AI Assistant) consult.py (booking + PayPal flow)
                paypal.py (PayPal REST client) billing.py search.py (find care) checkups.py schedule.py
                security.py seed.py config.py db.py (SQLite/Postgres)
    static/     single-page frontend: app.js (core views), care.js (dashboard, consultations, assistant),
                styles.css, logo files, service worker, PWA manifest and icons
    tests/      87 pytest tests (SQLite, or Postgres when DATABASE_URL is set). Gemini and PayPal are never called.
    deploy/     deploy.sh for Cloud Run + Cloud SQL
    Dockerfile  docker-compose.yml  LICENSE

## Running the tests
    python -m pytest tests -q

The tests use a fake PayPal API and never call Gemini, even if a key is in your `.env`.

## Testing on a phone
- Location, live camera and voice only work on an **https** link (or `localhost`). The Render link is https. For a quick https link from your own computer, run `cloudflared tunnel --url http://localhost:8000` in a second terminal.
- QR check-in has three ways: live camera (https only), **Take a photo of the QR** and **Choose QR image** from the gallery. QR images are decoded in the browser with the bundled jsQR library.
- The Find care and Consultations lists stay empty until the directory has providers and appointment times. Start with `DEMO_SEED=1`, or let the admin press **Load sample providers** and **Create sample appointment times**.

## Known limits
- **Medi AI Assistant:** gives general information only. It does not diagnose, prescribe or suggest doses. Emergency warning signs are caught by fixed server-side rules. Without a working Gemini key it uses a fixed guided question flow instead of the AI.
- **Consultation booking is a sandbox demo.** Doctors and appointment times are sample data and no real consultation is arranged. PayPal runs in **Sandbox only** (the code refuses the live PayPal host on purpose), so no real money moves.
- **Currency:** PayPal Sandbox accounts usually cannot pay in INR, so prices are shown in rupees and charged in USD at a fixed demo rate (`INR_PER_UNIT`, default 85).
- **PayPal webhooks:** the signature-verified endpoint (`/paypal/webhook`) is implemented and tested, but it is not enabled in the hosted demo. Payments are confirmed by the server capturing the order directly after approval.
- Dose alarms ring while the app is open or installed and running. Alarms with the phone locked and the app closed need Web Push (planned).
- Check-up intervals are general published guidance, not medical advice. The doctor decides each person's schedule.
- Safety checks are decision support for the doctor. Gemini extraction accuracy on real handwritten papers has not been benchmarked.
- Lab-result PDF storage is not built. The "Explain a report" tool does not store the report.
- Gemini model availability and speed vary by key and time. If a model is overloaded or retired, change `GEMINI_MODEL`.
