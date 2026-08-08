# MediCareAI Pro — Updated UI

The shared application stylesheet has been rebuilt so the Login, Register, Dashboard, Doctors, Reports, Reviews, Profile, Notifications, Ambulance and Admin pages all have the same MediCareAI visual system.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000/`.

If an older stylesheet is still cached, use **Ctrl + Shift + R** once.
