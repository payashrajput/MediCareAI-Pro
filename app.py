import os, sqlite3, re, json, secrets
from datetime import datetime, timezone
from functools import wraps

import requests
import fitz
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "medicare.db")
UP = os.path.join(BASE, "uploads")
os.makedirs(UP, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
)
ALLOWED_EXTENSIONS = {"pdf"}

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL, role TEXT DEFAULT 'patient', created TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS doctors(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL,
        hospital TEXT, city TEXT, experience INT DEFAULT 0, rating REAL DEFAULT 0,
        reviews INT DEFAULT 0, fee INT DEFAULT 0, availability TEXT, verified INT DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, doctor_id INT NOT NULL,
        rating INT NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS appointments(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, doctor_id INT NOT NULL,
        when_at TEXT NOT NULL, reason TEXT, mode TEXT NOT NULL,
        status TEXT DEFAULT 'Booked', meeting TEXT, cancel_reason TEXT, cancelled_at TEXT, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, title TEXT NOT NULL,
        kind TEXT NOT NULL, time TEXT, notes TEXT, done INT DEFAULT 0,
        created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, title TEXT NOT NULL,
        body TEXT, kind TEXT, read INT DEFAULT 0, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS profiles(
        user_id INT PRIMARY KEY, blood TEXT, allergies TEXT, medicines TEXT,
        history TEXT, emergency TEXT, age INT, height_cm REAL, weight_kg REAL,
        blood_pressure TEXT, glucose REAL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS documents(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, filename TEXT NOT NULL,
        stored_name TEXT, text TEXT, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS ambulances(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, location TEXT, lat TEXT, lon TEXT,
        urgency TEXT, note TEXT, ref TEXT UNIQUE, status TEXT, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS triage_history(
        id INTEGER PRIMARY KEY, user_id INT NOT NULL, symptoms TEXT NOT NULL,
        level TEXT, specialty TEXT, score INT, flags TEXT, created TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    if c.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
        doctors = [
            ("Dr. Ananya Sharma","General Physician","CarePlus Medical Centre","New Delhi",14,4.9,324,700,"Today · 6 PM"),
            ("Dr. Rohan Mehta","Internal Medicine","Apollo Care Hospital","New Delhi",18,4.8,412,900,"Tomorrow · 10:30 AM"),
            ("Dr. Kavya Rao","Dermatologist","DermaWell Clinic","Noida",11,4.9,287,800,"Today · 4:30 PM"),
            ("Dr. Arjun Verma","Orthopedic","Metro Bone & Joint","Ghaziabad",16,4.7,198,850,"Tomorrow · 12 PM"),
            ("Dr. Neha Kapoor","Pediatrician","LittleCare Hospital","New Delhi",12,4.8,361,750,"Today · 7 PM"),
            ("Dr. Sameer Khan","Cardiologist","HeartFirst Institute","New Delhi",20,4.9,529,1200,"Tomorrow · 9 AM"),
        ]
        c.executemany("""INSERT INTO doctors
            (name,specialty,hospital,city,experience,rating,reviews,fee,availability)
            VALUES(?,?,?,?,?,?,?,?,?)""", doctors)
    # Lightweight schema upgrades for databases created by earlier versions.
    cols = {row[1] for row in c.execute("PRAGMA table_info(appointments)").fetchall()}
    if "cancel_reason" not in cols:
        c.execute("ALTER TABLE appointments ADD COLUMN cancel_reason TEXT")
    if "cancelled_at" not in cols:
        c.execute("ALTER TABLE appointments ADD COLUMN cancelled_at TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_appointments_doctor_slot ON appointments(doctor_id, when_at, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_appointments_user_status ON appointments(user_id, status)")
    c.commit()
    c.close()

def auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

def admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return ("Forbidden", 403)
        return f(*args, **kwargs)
    return wrapper

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.context_processor
def context():
    unread = 0
    if session.get("uid"):
        c = db()
        unread = c.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0",
            (session["uid"],)
        ).fetchone()[0]
        c.close()
    return {"user": session.get("name"), "role": session.get("role"), "unread": unread}

@app.route("/")
def home():
    return render_template("landing.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        n = request.form.get("name","").strip()
        e = request.form.get("email","").lower().strip()
        p = request.form.get("password","")
        if len(n) < 2 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
            flash("Enter a valid name and email.")
            return redirect(url_for("register"))
        if len(p) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))
        c = db()
        try:
            cur = c.execute(
                "INSERT INTO users(name,email,password,created) VALUES(?,?,?,?)",
                (n,e,generate_password_hash(p),now())
            )
            uid = cur.lastrowid
            c.execute("INSERT INTO profiles(user_id) VALUES(?)",(uid,))
            c.commit()
        except sqlite3.IntegrityError:
            c.close()
            flash("Email already exists.")
            return redirect(url_for("register"))
        c.close()
        flash("Account created. Please sign in.")
        return redirect(url_for("login"))
    return render_template("auth.html", register=True)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        e = request.form.get("email","").lower().strip()
        c = db()
        u = c.execute("SELECT * FROM users WHERE email=?", (e,)).fetchone()
        c.close()
        if u and check_password_hash(u["password"], request.form.get("password","")):
            session.clear()
            session.update(uid=u["id"], name=u["name"], role=u["role"])
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Incorrect email or password.")
    return render_template("auth.html", register=False)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# Safety-first navigation layer. This is intentionally not a diagnostic model.
FLAGS = [
    "severe chest pain","difficulty breathing","cannot breathe","severe bleeding",
    "unconscious","fainted","stroke","face drooping","slurred speech","seizure",
    "suicidal","poisoning","major burn","blue lips","coughing blood"
]
MAP = {
    "skin":"Dermatologist","rash":"Dermatologist","acne":"Dermatologist",
    "joint":"Orthopedic","bone":"Orthopedic","knee":"Orthopedic","back pain":"Orthopedic",
    "heart":"Cardiologist","palpitation":"Cardiologist","chest":"Cardiologist",
    "child":"Pediatrician","baby":"Pediatrician",
    "fever":"General Physician","cough":"General Physician","cold":"General Physician",
    "headache":"General Physician","stomach":"General Physician","vomiting":"General Physician",
    "diarrhea":"General Physician"
}

def screen(text):
    t = text.lower()
    flags = [x for x in FLAGS if x in t]
    if flags:
        return {
            "level":"EMERGENCY","specialty":"Emergency Medicine","score":100,
            "message":"Potential emergency warning signs were detected. Do not wait for AI; seek urgent professional care.",
            "flags":flags
        }
    score = 25
    if len(t) > 80: score += 10
    if any(x in t for x in ["severe","worsening","persistent","days","week","high fever"]): score += 20
    if any(x in t for x in ["mild","slight","minor"]): score -= 10
    specialty = next((v for k,v in MAP.items() if k in t), "General Physician")
    return {
        "level":"PRIORITY" if score >= 55 else "ROUTINE",
        "specialty":specialty,"score":max(0,min(score,95)),
        "message":(
            "A clinician review soon may be appropriate." if score >= 55 else
            "No emergency pattern was found by this basic screen. Monitor symptoms and seek care if they persist or worsen."
        ),"flags":[]
    }

def ollama(text):
    base = os.getenv("OLLAMA_URL","").strip()
    model = os.getenv("OLLAMA_MODEL","").strip()
    if not base or not model:
        return None
    prompt = """You are a cautious healthcare navigation assistant.
Never diagnose, prescribe, recommend medication doses, or tell a user that an emergency is safe.
Return ONLY JSON with keys urgency, specialty, reasons, safety_note.
Use urgency values ROUTINE or PRIORITY only.
Symptoms: """ + text
    try:
        r = requests.post(
            base.rstrip("/") + "/api/generate",
            json={"model":model,"prompt":prompt,"stream":False},
            timeout=25
        )
        r.raise_for_status()
        raw = r.json().get("response","")
        match = re.search(r"\{.*\}", raw, re.S)
        return json.loads(match.group()) if match else None
    except Exception:
        return None

@app.route("/api/triage", methods=["POST"])
@auth
def triage():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("symptoms","")).strip()
    if len(text) < 3:
        return jsonify(error="Please describe symptoms in more detail."), 400
    result = screen(text)
    if result["level"] != "EMERGENCY":
        ai = ollama(text)
        if ai:
            result["level"] = ai.get("urgency", result["level"])
            result["specialty"] = ai.get("specialty", result["specialty"])
            result["message"] = ai.get("safety_note", result["message"])
            result["reasons"] = ai.get("reasons", [])
    c = db()
    c.execute("""INSERT INTO triage_history
        (user_id,symptoms,level,specialty,score,flags,created)
        VALUES(?,?,?,?,?,?,?)""",
        (session["uid"],text,result["level"],result["specialty"],
         result["score"],json.dumps(result.get("flags",[])),now()))
    c.commit()
    c.close()
    return jsonify(result)

@app.route("/dashboard")
@auth
def dashboard():
    c = db()
    appointments = c.execute("""SELECT a.*,d.name doctor,d.specialty,d.hospital
        FROM appointments a JOIN doctors d ON d.id=a.doctor_id
        WHERE a.user_id=? ORDER BY when_at""",(session["uid"],)).fetchall()
    reminders = c.execute("""SELECT * FROM reminders WHERE user_id=?
        ORDER BY done,time""",(session["uid"],)).fetchall()
    notifications = c.execute("""SELECT * FROM notifications WHERE user_id=?
        ORDER BY created DESC LIMIT 6""",(session["uid"],)).fetchall()
    triage = c.execute("""SELECT * FROM triage_history WHERE user_id=?
        ORDER BY created DESC LIMIT 5""",(session["uid"],)).fetchall()
    c.close()
    return render_template("dashboard.html",appointments=appointments,
                           reminders=reminders,notifications=notifications,triage=triage)

@app.route("/doctors")
@auth
def doctors():
    specialty = request.args.get("specialty","").strip()
    search = request.args.get("q","").strip()
    c = db()
    conditions, params = [], []
    if specialty:
        conditions.append("specialty=?"); params.append(specialty)
    if search:
        conditions.append("(name LIKE ? OR hospital LIKE ? OR specialty LIKE ? OR city LIKE ?)")
        params += [f"%{search}%"]*4
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    ds = c.execute(f"""SELECT * FROM doctors {where}
        ORDER BY rating DESC,reviews DESC,name""", params).fetchall()
    c.close()
    return render_template("doctors.html",doctors=ds,specialty=specialty,search=search)

@app.route("/book/<int:did>", methods=["POST"])
@auth
def book(did):
    when_at = request.form.get("when_at","").strip()
    mode = request.form.get("mode","In-person")
    reason = request.form.get("reason","").strip()
    if not when_at:
        flash("Please select a date and time.")
        return redirect(url_for("doctors"))
    try:
        requested = datetime.fromisoformat(when_at)
        if requested <= datetime.now():
            flash("Appointment time must be in the future.")
            return redirect(url_for("doctors"))
    except ValueError:
        flash("Invalid appointment date.")
        return redirect(url_for("doctors"))
    if mode not in {"In-person","Video consultation"}:
        mode = "In-person"
    c = db()
    doctor = c.execute("SELECT * FROM doctors WHERE id=?",(did,)).fetchone()
    if not doctor:
        c.close(); abort(404)
    clash = c.execute("""SELECT 1 FROM appointments
        WHERE doctor_id=? AND when_at=? AND status='Booked'""",(did,when_at)).fetchone()
    if clash:
        c.close(); flash("That time is already booked. Please choose another time.")
        return redirect(url_for("doctors", specialty=doctor["specialty"]))
    meeting = f"https://meet.jit.si/MediCareAI-{session['uid']}-{did}-{secrets.token_hex(3)}" if mode=="Video consultation" else ""
    c.execute("""INSERT INTO appointments
        (user_id,doctor_id,when_at,reason,mode,meeting,created)
        VALUES(?,?,?,?,?,?,?)""",
        (session["uid"],did,when_at,reason,mode,meeting,now()))
    c.execute("""INSERT INTO notifications(user_id,title,body,kind,created)
        VALUES(?,?,?,?,?)""",(session["uid"],"Appointment booked",
        f"{doctor['name']} · {when_at}","appointment",now()))
    c.commit(); c.close()
    flash("Appointment booked successfully.")
    return redirect(url_for("dashboard"))

@app.route("/appointment/<int:aid>/cancel", methods=["POST"])
@auth
def cancel_appointment(aid):
    reason = request.form.get("reason", "Cancelled by patient").strip()[:300] or "Cancelled by patient"
    c = db()
    ap = c.execute("SELECT * FROM appointments WHERE id=? AND user_id=?", (aid, session["uid"])).fetchone()
    if not ap:
        c.close(); abort(404)
    if ap["status"] != "Booked":
        c.close(); flash("Only booked appointments can be cancelled."); return redirect(url_for("dashboard"))
    cancelled = now()
    c.execute("UPDATE appointments SET status='Cancelled', cancel_reason=?, cancelled_at=? WHERE id=?", (reason, cancelled, aid))
    c.execute("""INSERT INTO notifications(user_id,title,body,kind,created)
        VALUES(?,?,?,?,?)""", (session["uid"], "Appointment cancelled",
        f"Appointment #{aid} has been cancelled. Reason: {reason}", "appointment", cancelled))
    c.commit(); c.close()
    flash("Appointment cancelled successfully.")
    return redirect(url_for("dashboard"))

@app.route("/appointment/<int:aid>/reschedule", methods=["POST"])
@auth
def reschedule_appointment(aid):
    when_at = request.form.get("when_at", "").strip()
    if not when_at:
        flash("Please choose a new date and time."); return redirect(url_for("dashboard"))
    try:
        requested = datetime.fromisoformat(when_at)
        if requested <= datetime.now():
            flash("New appointment time must be in the future."); return redirect(url_for("dashboard"))
    except ValueError:
        flash("Invalid appointment date and time."); return redirect(url_for("dashboard"))
    c = db()
    ap = c.execute("SELECT * FROM appointments WHERE id=? AND user_id=?", (aid, session["uid"])).fetchone()
    if not ap:
        c.close(); abort(404)
    if ap["status"] != "Booked":
        c.close(); flash("Only booked appointments can be rescheduled."); return redirect(url_for("dashboard"))
    clash = c.execute("""SELECT 1 FROM appointments WHERE doctor_id=? AND when_at=? AND status='Booked' AND id<>?""", (ap["doctor_id"], when_at, aid)).fetchone()
    if clash:
        c.close(); flash("That time is already booked. Please choose another time."); return redirect(url_for("dashboard"))
    c.execute("UPDATE appointments SET when_at=? WHERE id=?", (when_at, aid))
    c.execute("""INSERT INTO notifications(user_id,title,body,kind,created) VALUES(?,?,?,?,?)""",
              (session["uid"], "Appointment rescheduled", f"Appointment #{aid} moved to {when_at}.", "appointment", now()))
    c.commit(); c.close()
    flash("Appointment rescheduled successfully.")
    return redirect(url_for("dashboard"))

@app.route("/admin/appointment/<int:aid>/cancel", methods=["POST"])
@auth
@admin
def admin_cancel_appointment(aid):
    reason = request.form.get("reason", "Cancelled by admin").strip()[:300] or "Cancelled by admin"
    c = db()
    ap = c.execute("SELECT * FROM appointments WHERE id=?", (aid,)).fetchone()
    if not ap:
        c.close(); abort(404)
    if ap["status"] != "Booked":
        c.close(); flash("Only booked appointments can be cancelled."); return redirect(url_for("admin_page"))
    cancelled = now()
    c.execute("UPDATE appointments SET status='Cancelled', cancel_reason=?, cancelled_at=? WHERE id=?", (reason, cancelled, aid))
    c.execute("""INSERT INTO notifications(user_id,title,body,kind,created) VALUES(?,?,?,?,?)""",
              (ap["user_id"], "Appointment cancelled by admin", f"Appointment #{aid} was cancelled. Reason: {reason}", "appointment", cancelled))
    c.commit(); c.close()
    flash("Appointment cancelled.")
    return redirect(url_for("admin_page"))

@app.route("/reviews", methods=["GET","POST"])
@auth
def reviews():
    c = db()
    if request.method == "POST":
        try:
            did, rating = int(request.form["doctor_id"]), int(request.form["rating"])
        except (KeyError,ValueError):
            c.close(); flash("Invalid review."); return redirect(url_for("reviews"))
        comment = request.form.get("comment","").strip()[:1000]
        if not 1 <= rating <= 5:
            c.close(); flash("Rating must be between 1 and 5."); return redirect(url_for("reviews"))
        existing = c.execute("SELECT 1 FROM reviews WHERE user_id=? AND doctor_id=?",
                             (session["uid"],did)).fetchone()
        if existing:
            c.close(); flash("You have already reviewed this doctor."); return redirect(url_for("reviews"))
        c.execute("""INSERT INTO reviews(user_id,doctor_id,rating,comment,created)
            VALUES(?,?,?,?,?)""",(session["uid"],did,rating,comment,now()))
        stats = c.execute("SELECT AVG(rating),COUNT(*) FROM reviews WHERE doctor_id=?",(did,)).fetchone()
        c.execute("UPDATE doctors SET rating=?,reviews=? WHERE id=?",
                  (round(stats[0],1),stats[1],did))
        c.commit(); flash("Review published.")
    ds = c.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    rs = c.execute("""SELECT r.*,d.name doctor,u.name user FROM reviews r
        JOIN doctors d ON d.id=r.doctor_id JOIN users u ON u.id=r.user_id
        ORDER BY r.created DESC""").fetchall()
    c.close()
    return render_template("reviews.html",doctors=ds,reviews=rs)

@app.route("/api/reminders", methods=["POST"])
@auth
def add_reminder():
    x = request.get_json(silent=True) or {}
    title = str(x.get("title","")).strip()[:120]
    kind = str(x.get("kind","Medicine")).strip()
    tm = str(x.get("time","")).strip()
    notes = str(x.get("notes","")).strip()[:500]
    if not title:
        return jsonify(error="Reminder title is required."),400
    allowed = {"Medicine","Hydration","Yoga / Exercise","Follow-up","Sleep"}
    if kind not in allowed: kind = "Follow-up"
    if tm and not re.match(r"^\d{2}:\d{2}$",tm): tm=""
    c=db()
    c.execute("""INSERT INTO reminders(user_id,title,kind,time,notes,created)
        VALUES(?,?,?,?,?,?)""",(session["uid"],title,kind,tm,notes,now()))
    c.commit(); c.close()
    return jsonify(ok=True)

@app.route("/api/reminders/<int:rid>/done", methods=["POST"])
@auth
def reminder_done(rid):
    c=db()
    c.execute("UPDATE reminders SET done=1-done WHERE id=? AND user_id=?",(rid,session["uid"]))
    changed=c.total_changes
    c.commit(); c.close()
    return jsonify(ok=bool(changed))

@app.route("/api/reminders/<int:rid>", methods=["DELETE"])
@auth
def reminder_delete(rid):
    c=db(); c.execute("DELETE FROM reminders WHERE id=? AND user_id=?",(rid,session["uid"]))
    ok=bool(c.total_changes); c.commit(); c.close()
    return jsonify(ok=ok)

@app.route("/notifications")
@auth
def notifications():
    c=db()
    ns=c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created DESC",(session["uid"],)).fetchall()
    c.execute("UPDATE notifications SET read=1 WHERE user_id=?",(session["uid"],))
    c.commit(); c.close()
    return render_template("notifications.html",notifications=ns)

@app.route("/health", methods=["GET","POST"])
@auth
def health():
    c=db()
    if request.method=="POST":
        def num(name, default=None):
            try: return float(request.form.get(name,"")) if request.form.get(name,"").strip() else default
            except ValueError: return default
        age_raw=request.form.get("age","").strip()
        try: age=int(age_raw) if age_raw else None
        except ValueError: age=None
        c.execute("""UPDATE profiles SET blood=?,allergies=?,medicines=?,history=?,
            emergency=?,age=?,height_cm=?,weight_kg=?,blood_pressure=?,glucose=?
            WHERE user_id=?""",(
            request.form.get("blood","").strip()[:30],
            request.form.get("allergies","").strip()[:1000],
            request.form.get("medicines","").strip()[:2000],
            request.form.get("history","").strip()[:2000],
            request.form.get("emergency","").strip()[:100],
            age,num("height_cm"),num("weight_kg"),
            request.form.get("blood_pressure","").strip()[:30],num("glucose"),
            session["uid"]))
        c.commit(); flash("Health profile saved.")
    p=c.execute("SELECT * FROM profiles WHERE user_id=?",(session["uid"],)).fetchone()
    c.close()
    bmi=None
    if p and p["height_cm"] and p["weight_kg"] and p["height_cm"]>0:
        bmi=round(p["weight_kg"]/((p["height_cm"]/100)**2),1)
    return render_template("health.html",p=p,bmi=bmi)

@app.route("/triage-history")
@auth
def triage_history():
    c=db()
    rows=c.execute("""SELECT * FROM triage_history WHERE user_id=? ORDER BY created DESC""",
                   (session["uid"],)).fetchall()
    c.close()
    return render_template("triage_history.html",rows=rows)

@app.route("/documents", methods=["GET","POST"])
@auth
def documents():
    c=db()
    if request.method=="POST":
        f=request.files.get("document")
        if not f or not f.filename or not f.filename.lower().endswith(".pdf"):
            c.close(); flash("Please upload a PDF."); return redirect(url_for("documents"))
        original=secure_filename(f.filename)
        stored=f"{session['uid']}_{secrets.token_hex(8)}_{original}"
        path=os.path.join(UP,stored)
        f.save(path)
        text=""
        try:
            with fitz.open(path) as pdf:
                text="\n".join(page.get_text() for page in pdf)[:50000]
        except Exception:
            text="Text extraction failed for this PDF."
        c.execute("""INSERT INTO documents(user_id,filename,stored_name,text,created)
            VALUES(?,?,?,?,?)""",(session["uid"],original,stored,text,now()))
        c.commit(); flash("PDF uploaded and text extracted.")
    docs=c.execute("SELECT * FROM documents WHERE user_id=? ORDER BY created DESC",(session["uid"],)).fetchall()
    c.close()
    return render_template("documents.html",documents=docs)

@app.route("/documents/<int:doc_id>", methods=["DELETE"])
@auth
def delete_document(doc_id):
    c=db()
    doc=c.execute("SELECT * FROM documents WHERE id=? AND user_id=?",(doc_id,session["uid"])).fetchone()
    if not doc:
        c.close(); return jsonify(error="Not found"),404
    if doc["stored_name"]:
        path=os.path.join(UP,doc["stored_name"])
        if os.path.isfile(path): os.remove(path)
    c.execute("DELETE FROM documents WHERE id=?",(doc_id,))
    c.commit(); c.close()
    return jsonify(ok=True)

@app.route("/ambulance", methods=["GET","POST"])
@auth
def ambulance():
    if request.method=="POST":
        urgency=request.form.get("urgency","Urgent")
        if urgency not in {"Critical — immediate","Urgent","Non-emergency transport"}:
            urgency="Urgent"
        location=request.form.get("location","").strip()
        if not location:
            flash("Pickup location is required."); return redirect(url_for("ambulance"))
        ref="AMB-"+datetime.now().strftime("%Y%m%d%H%M%S")+"-"+secrets.token_hex(2).upper()
        api=os.getenv("AMBULANCE_API_URL","").strip()
        key=os.getenv("AMBULANCE_API_KEY","").strip()
        provider_ok=False
        if api:
            try:
                r=requests.post(api,json={
                    "location":location,"lat":request.form.get("lat"),
                    "lon":request.form.get("lon"),"urgency":urgency,
                    "note":request.form.get("note","").strip()
                },headers={"Authorization":"Bearer "+key} if key else {},timeout=10)
                if r.ok:
                    ref=r.json().get("reference",ref); provider_ok=True
            except Exception:
                pass
        c=db()
        status="Provider requested" if provider_ok else "Demo request"
        c.execute("""INSERT INTO ambulances
            (user_id,location,lat,lon,urgency,note,ref,status,created)
            VALUES(?,?,?,?,?,?,?,?,?)""",(
            session["uid"],location,request.form.get("lat"),request.form.get("lon"),
            urgency,request.form.get("note","").strip()[:1000],ref,status,now()))
        c.execute("""INSERT INTO notifications(user_id,title,body,kind,created)
            VALUES(?,?,?,?,?)""",(session["uid"],"Ambulance request",
            f"Reference {ref} · {status}","emergency",now()))
        c.commit(); c.close()
        flash("Ambulance request created: "+ref)
        return redirect(url_for("dashboard"))
    return render_template("ambulance.html")

@app.route("/admin")
@auth
@admin
def admin_page():
    c=db()
    stats=[
        c.execute("SELECT COUNT(*) FROM users WHERE role='patient'").fetchone()[0],
        c.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
        c.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
        c.execute("SELECT COUNT(*) FROM ambulances").fetchone()[0],
    ]
    recent=c.execute("""SELECT a.*,u.name patient,d.name doctor
        FROM appointments a JOIN users u ON u.id=a.user_id
        JOIN doctors d ON d.id=a.doctor_id ORDER BY a.created DESC LIMIT 10""").fetchall()
    c.close()
    return render_template("admin.html",stats=stats,recent=recent)

@app.route("/api/health")
def health_api():
    return jsonify(status="ok",service="MediCareAI Pro",time=now())

@app.route("/seed-admin")
def seed():
    if os.getenv("ENABLE_DEMO_ADMIN","0")!="1":
        return "Disabled. Set ENABLE_DEMO_ADMIN=1 only for local development.",404
    c=db()
    exists=c.execute("SELECT 1 FROM users WHERE email='admin@medicare.local'").fetchone()
    if not exists:
        c.execute("""INSERT INTO users(name,email,password,role,created)
            VALUES(?,?,?,?,?)""",("MediCare Admin","admin@medicare.local",
            generate_password_hash("Admin@12345"),"admin",now()))
        c.commit()
    c.close()
    return "Demo admin created. Change the password and disable ENABLE_DEMO_ADMIN after testing."
init()
if __name__=="__main__":

    app.run(host=os.getenv("HOST","127.0.0.1"),port=int(os.getenv("PORT","5000")),
            debug=os.getenv("FLASK_DEBUG","0")=="1")
