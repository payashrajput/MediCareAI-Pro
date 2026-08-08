# MediCareAI Pro

Premium Flask + SQLite + HTML/CSS/JavaScript healthcare navigation prototype.

## Features
- Patient signup/login with password hashing
- Safety-first AI symptom screening + optional local Ollama LLM
- Emergency red-flag escalation
- Doctor recommendation by specialty, rating, review count and experience
- Appointment booking with in-person/video mode
- Patient review/rating system
- Medicine, hydration, yoga/exercise, sleep and follow-up reminders
- Browser voice symptom input
- Browser geolocation for ambulance request
- Configurable ambulance provider adapter
- PDF medical report/prescription upload and text extraction
- Health profile
- Notification center
- Admin dashboard

## Run
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py

Open http://127.0.0.1:5000

Optional local AI: install Ollama and set OLLAMA_URL/OLLAMA_MODEL.

Demo admin: open /seed-admin once, then admin@medicare.local / Admin@12345. Remove that route before production.

## Production requirements
This prototype is not a medical device and must not diagnose, prescribe or delay emergency care. Before real patient use add clinical validation, qualified medical oversight, encryption, consent, audit logs, MFA, doctor credential verification, secure notification/telehealth/EMS integrations, rate limiting, backups and applicable healthcare/privacy compliance.
