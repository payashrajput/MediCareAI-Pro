# MediCareAI Pro — Working Full-Stack Prototype

MediCareAI Pro is a Flask + SQLite healthcare-navigation application. It is designed as a **safety-first prototype**, not a medical device: the AI screen does not diagnose, prescribe, or clear emergencies.

## Included functionality

- Patient registration/login with hashed passwords
- Dashboard with appointments, reminders, notifications and AI-assisted safety screening
- Deterministic emergency red-flag layer before optional Ollama
- Optional local Ollama integration
- Triage/screening history
- Doctor search by specialty/name/hospital/city
- Appointment booking with duplicate-slot protection
- Appointment cancellation
- In-person/video consultation links
- Reviews with rating validation and one-review-per-doctor protection
- Health profile: age, blood group, allergies, medicines, history, emergency contact, height/weight, BP and glucose
- BMI calculation for context only
- PDF report upload + text extraction
- Secure randomized stored document names
- Document deletion
- Reminder creation/completion/deletion API
- Browser voice symptom input
- Browser geolocation for ambulance request
- Configurable EMS provider adapter
- Admin dashboard
- `/api/health` health check
- Basic security headers and safer session-cookie configuration

## Run locally

```bash
cd MediCareAI_Pro
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

If you use Fedora and `python3` points to a version without the required packages, install the requirements into the fresh virtual environment above rather than reusing the archived `.venv` directory.

## Optional Ollama

Install Ollama separately, pull a model, then set:

```env
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

The deterministic emergency screen always runs first. Ollama is only an optional navigation layer and its output must not be treated as a diagnosis.

## Local demo admin

For local testing only:

```env
ENABLE_DEMO_ADMIN=1
```

Then visit `/seed-admin` and sign in with the demo credentials shown there. Disable the flag afterward. In a real deployment, replace this with a secure admin provisioning flow and MFA.

## Important production work still required

Before real patient use, add clinical validation and qualified medical oversight, HTTPS, encrypted data at rest/in transit, strong CSRF protection, MFA, rate limiting, secure secrets management, audit logs, backups, verified doctor credentials, real telehealth/EMS integrations, consent/retention controls, monitoring, incident response and all applicable healthcare/privacy compliance.

Never use this prototype to delay emergency care.


## Corrected admin and appointment workflow

For local development, copy `.env.example` to `.env` and set `ENABLE_DEMO_ADMIN=1`. Start the app, open `/seed-admin`, then sign in with `admin@medicare.local` / `Admin@12345`. Disable the demo seed afterward.

Patients can now cancel booked appointments with an optional reason and reschedule them to a future time. The server checks ownership, status, future time, and doctor-slot conflicts. Admins can cancel booked appointments from the Admin Control Center.
