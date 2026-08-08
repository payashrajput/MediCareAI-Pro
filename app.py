import os, sqlite3, re, json
from datetime import datetime
from functools import wraps
import requests
import fitz
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv()
BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'medicare.db'); UP=os.path.join(BASE,'uploads'); os.makedirs(UP,exist_ok=True)
app=Flask(__name__); app.secret_key=os.getenv('SECRET_KEY','dev-secret-change-me'); app.config['MAX_CONTENT_LENGTH']=10*1024*1024

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT DEFAULT 'patient',created TEXT);
 CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY,name TEXT,specialty TEXT,hospital TEXT,city TEXT,experience INT,rating REAL,reviews INT,fee INT,availability TEXT,verified INT DEFAULT 1);
 CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY,user_id INT,doctor_id INT,rating INT,comment TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY,user_id INT,doctor_id INT,when_at TEXT,reason TEXT,mode TEXT,status TEXT DEFAULT 'Booked',meeting TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY,user_id INT,title TEXT,kind TEXT,time TEXT,notes TEXT,done INT DEFAULT 0);
 CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INT,title TEXT,body TEXT,kind TEXT,read INT DEFAULT 0,created TEXT);
 CREATE TABLE IF NOT EXISTS profiles(user_id INT PRIMARY KEY,blood TEXT,allergies TEXT,medicines TEXT,history TEXT,emergency TEXT);
 CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,user_id INT,filename TEXT,text TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS ambulances(id INTEGER PRIMARY KEY,user_id INT,location TEXT,lat TEXT,lon TEXT,urgency TEXT,note TEXT,ref TEXT,status TEXT,created TEXT);
 ''')
 if c.execute('SELECT COUNT(*) FROM doctors').fetchone()[0]==0:
  ds=[('Dr. Ananya Sharma','General Physician','CarePlus Medical Centre','New Delhi',14,4.9,324,700,'Today · 6 PM'),('Dr. Rohan Mehta','Internal Medicine','Apollo Care Hospital','New Delhi',18,4.8,412,900,'Tomorrow · 10:30 AM'),('Dr. Kavya Rao','Dermatologist','DermaWell Clinic','Noida',11,4.9,287,800,'Today · 4:30 PM'),('Dr. Arjun Verma','Orthopedic','Metro Bone & Joint','Ghaziabad',16,4.7,198,850,'Tomorrow · 12 PM'),('Dr. Neha Kapoor','Pediatrician','LittleCare Hospital','New Delhi',12,4.8,361,750,'Today · 7 PM'),('Dr. Sameer Khan','Cardiologist','HeartFirst Institute','New Delhi',20,4.9,529,1200,'Tomorrow · 9 AM')]
  c.executemany('INSERT INTO doctors(name,specialty,hospital,city,experience,rating,reviews,fee,availability) VALUES(?,?,?,?,?,?,?,?,?)',ds)
 c.commit(); c.close()
def auth(f):
 @wraps(f)
 def w(*a,**k):
  if 'uid' not in session:return redirect(url_for('login'))
  return f(*a,**k)
 return w
def admin(f):
 @wraps(f)
 def w(*a,**k):
  if session.get('role')!='admin':return ('Forbidden',403)
  return f(*a,**k)
 return w
@app.context_processor
def context():
 n=0
 if session.get('uid'):
  c=db();n=c.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0',(session['uid'],)).fetchone()[0];c.close()
 return {'user':session.get('name'),'role':session.get('role'),'unread':n}
@app.route('/')
def home():return render_template('landing.html')
@app.route('/register',methods=['GET','POST'])
def register():
 if request.method=='POST':
  n,e,p=request.form['name'].strip(),request.form['email'].lower().strip(),request.form['password']
  if len(p)<6:flash('Password must be at least 6 characters.');return redirect(url_for('register'))
  c=db()
  try:c.execute('INSERT INTO users(name,email,password,created) VALUES(?,?,?,?)',(n,e,generate_password_hash(p),datetime.now().isoformat()));c.commit();uid=c.execute('SELECT id FROM users WHERE email=?',(e,)).fetchone()[0];c.execute('INSERT INTO profiles(user_id) VALUES(?)',(uid,));c.commit()
  except sqlite3.IntegrityError:c.close();flash('Email already exists.');return redirect(url_for('register'))
  c.close();flash('Account created.');return redirect(url_for('login'))
 return render_template('auth.html',register=True)
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db();u=c.execute('SELECT * FROM users WHERE email=?',(request.form['email'].lower().strip(),)).fetchone();c.close()
  if u and check_password_hash(u['password'],request.form['password']):session.update(uid=u['id'],name=u['name'],role=u['role']);return redirect(url_for('dashboard'))
  flash('Incorrect email or password.')
 return render_template('auth.html',register=False)
@app.route('/logout')
def logout():session.clear();return redirect(url_for('home'))
# AI safety layer
FLAGS=['severe chest pain','difficulty breathing','cannot breathe','severe bleeding','unconscious','fainted','stroke','face drooping','slurred speech','seizure','suicidal','poisoning','major burn']
MAP={'skin':'Dermatologist','rash':'Dermatologist','acne':'Dermatologist','joint':'Orthopedic','bone':'Orthopedic','knee':'Orthopedic','back pain':'Orthopedic','heart':'Cardiologist','palpitation':'Cardiologist','chest':'Cardiologist','child':'Pediatrician','baby':'Pediatrician','fever':'General Physician','cough':'General Physician','cold':'General Physician','headache':'General Physician','stomach':'General Physician','vomiting':'General Physician','diarrhea':'General Physician'}
def screen(t):
 t=t.lower(); f=[x for x in FLAGS if x in t]
 if f:return {'level':'EMERGENCY','specialty':'Emergency Medicine','score':100,'message':'Potential emergency warning signs detected. Do not wait for AI; seek urgent professional care.','flags':f}
 s=25+(10 if len(t)>80 else 0)+(20 if any(x in t for x in ['severe','worsening','persistent','days','week','high fever']) else 0)-(10 if any(x in t for x in ['mild','slight','minor']) else 0);sp='General Physician'
 for k,v in MAP.items():
  if k in t:sp=v;break
 return {'level':'PRIORITY' if s>=55 else 'ROUTINE','specialty':sp,'score':max(0,min(s,95)),'message':'A clinician review soon may be appropriate.' if s>=55 else 'No emergency pattern was found by this basic screen. Monitor and seek care if symptoms persist or worsen.','flags':[]}
def ollama(t):
 u=os.getenv('OLLAMA_URL','');m=os.getenv('OLLAMA_MODEL','')
 if not u or not m:return None
 prompt='You are a cautious healthcare navigation assistant. Never diagnose, prescribe, or clear emergencies. Return JSON with urgency, specialty, reasons, safety_note. Symptoms: '+t
 try:
  r=requests.post(u.rstrip('/')+'/api/generate',json={'model':m,'prompt':prompt,'stream':False},timeout=25);x=re.search(r'\{.*\}',r.json().get('response',''),re.S);return json.loads(x.group()) if x else None
 except Exception:return None
@app.route('/api/triage',methods=['POST'])
@auth
def triage():
 t=request.json.get('symptoms','').strip()
 if len(t)<3:return jsonify(error='Please describe symptoms in more detail.'),400
 d=screen(t)
 if d['level']!='EMERGENCY':
  a=ollama(t)
  if a:d.update(level=a.get('urgency',d['level']),specialty=a.get('specialty',d['specialty']),message=a.get('safety_note',d['message']))
 return jsonify(d)
@app.route('/dashboard')
@auth
def dashboard():
 c=db();ap=c.execute('SELECT a.*,d.name doctor,d.specialty,d.hospital FROM appointments a JOIN doctors d ON d.id=a.doctor_id WHERE a.user_id=? ORDER BY when_at',(session['uid'],)).fetchall();rm=c.execute('SELECT * FROM reminders WHERE user_id=? ORDER BY done,time',(session['uid'],)).fetchall();no=c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created DESC LIMIT 6',(session['uid'],)).fetchall();c.close();return render_template('dashboard.html',appointments=ap,reminders=rm,notifications=no)
@app.route('/doctors')
@auth
def doctors():
 s=request.args.get('specialty','');c=db();q='SELECT * FROM doctors '+('WHERE specialty=? ' if s else '')+'ORDER BY rating DESC,reviews DESC';ds=c.execute(q,(s,) if s else ()).fetchall();c.close();return render_template('doctors.html',doctors=ds,specialty=s)
@app.route('/book/<int:did>',methods=['POST'])
@auth
def book(did):
 c=db();d=c.execute('SELECT * FROM doctors WHERE id=?',(did,)).fetchone();mode=request.form.get('mode','In-person');meet='https://meet.jit.si/MediCareAI-'+str(session['uid'])+'-'+str(did) if mode=='Video consultation' else ''
 c.execute('INSERT INTO appointments(user_id,doctor_id,when_at,reason,mode,meeting,created) VALUES(?,?,?,?,?,?,?)',(session['uid'],did,request.form['when_at'],request.form.get('reason',''),mode,meet,datetime.now().isoformat()));c.execute('INSERT INTO notifications(user_id,title,body,kind,created) VALUES(?,?,?,?,?)',(session['uid'],'Appointment booked',f"{d['name']} · {request.form['when_at']}",'appointment',datetime.now().isoformat()));c.commit();c.close();flash('Appointment booked successfully.');return redirect(url_for('dashboard'))
@app.route('/reviews',methods=['GET','POST'])
@auth
def reviews():
 c=db()
 if request.method=='POST':
  did=int(request.form['doctor_id']);r=int(request.form['rating']);comment=request.form['comment'].strip();c.execute('INSERT INTO reviews(user_id,doctor_id,rating,comment,created) VALUES(?,?,?,?,?)',(session['uid'],did,r,comment,datetime.now().isoformat()));s=c.execute('SELECT AVG(rating),COUNT(*) FROM reviews WHERE doctor_id=?',(did,)).fetchone();c.execute('UPDATE doctors SET rating=?,reviews=? WHERE id=?',(round(s[0],1),s[1],did));c.commit();flash('Review published.')
 ds=c.execute('SELECT * FROM doctors ORDER BY name').fetchall();rs=c.execute('SELECT r.*,d.name doctor,u.name user FROM reviews r JOIN doctors d ON d.id=r.doctor_id JOIN users u ON u.id=r.user_id ORDER BY r.created DESC').fetchall();c.close();return render_template('reviews.html',doctors=ds,reviews=rs)
@app.route('/api/reminders',methods=['POST'])
@auth
def add_reminder():
 x=request.json;c=db();c.execute('INSERT INTO reminders(user_id,title,kind,time,notes) VALUES(?,?,?,?,?)',(session['uid'],x.get('title'),x.get('kind','Medicine'),x.get('time'),x.get('notes','')));c.commit();c.close();return jsonify(ok=True)
@app.route('/api/reminders/<int:rid>/done',methods=['POST'])
@auth
def reminder_done(rid):
 c=db();c.execute('UPDATE reminders SET done=1-done WHERE id=? AND user_id=?',(rid,session['uid']));c.commit();c.close();return jsonify(ok=True)
@app.route('/notifications')
@auth
def notifications():
 c=db();ns=c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created DESC',(session['uid'],)).fetchall();c.execute('UPDATE notifications SET read=1 WHERE user_id=?',(session['uid'],));c.commit();c.close();return render_template('notifications.html',notifications=ns)
@app.route('/health',methods=['GET','POST'])
@auth
def health():
 c=db()
 if request.method=='POST':c.execute('UPDATE profiles SET blood=?,allergies=?,medicines=?,history=?,emergency=? WHERE user_id=?',(request.form.get('blood'),request.form.get('allergies'),request.form.get('medicines'),request.form.get('history'),request.form.get('emergency'),session['uid']));c.commit();flash('Profile saved.')
 p=c.execute('SELECT * FROM profiles WHERE user_id=?',(session['uid'],)).fetchone();c.close();return render_template('health.html',p=p)
@app.route('/documents',methods=['GET','POST'])
@auth
def documents():
 c=db()
 if request.method=='POST':
  f=request.files.get('document')
  if not f or not f.filename.lower().endswith('.pdf'):flash('Please upload a PDF.');return redirect(url_for('documents'))
  name=secure_filename(f.filename);path=os.path.join(UP,str(session['uid'])+'_'+name);f.save(path);text=''
  try:text='\n'.join(p.get_text() for p in fitz.open(path))[:50000]
  except Exception:text='Text extraction failed.'
  c.execute('INSERT INTO documents(user_id,filename,text,created) VALUES(?,?,?,?)',(session['uid'],name,text,datetime.now().isoformat()));c.commit();flash('PDF uploaded and text extracted.')
 ds=c.execute('SELECT * FROM documents WHERE user_id=? ORDER BY created DESC',(session['uid'],)).fetchall();c.close();return render_template('documents.html',documents=ds)
@app.route('/ambulance',methods=['GET','POST'])
@auth
def ambulance():
 if request.method=='POST':
  ref='AMB-'+datetime.now().strftime('%Y%m%d%H%M%S');loc=request.form['location'];api=os.getenv('AMBULANCE_API_URL');key=os.getenv('AMBULANCE_API_KEY')
  if api:
   try:
    z=requests.post(api,json={'location':loc,'lat':request.form.get('lat'),'lon':request.form.get('lon'),'urgency':request.form['urgency'],'note':request.form.get('note','')},headers={'Authorization':'Bearer '+key} if key else {},timeout=10);ref=z.json().get('reference',ref) if z.ok else ref
   except Exception:pass
  c=db();c.execute('INSERT INTO ambulances(user_id,location,lat,lon,urgency,note,ref,status,created) VALUES(?,?,?,?,?,?,?,?,?)',(session['uid'],loc,request.form.get('lat'),request.form.get('lon'),request.form['urgency'],request.form.get('note',''),ref,'Requested',datetime.now().isoformat()));c.execute('INSERT INTO notifications(user_id,title,body,kind,created) VALUES(?,?,?,?,?)',(session['uid'],'Ambulance request',f'Reference {ref}.','emergency',datetime.now().isoformat()));c.commit();c.close();flash('Ambulance request created: '+ref);return redirect(url_for('dashboard'))
 return render_template('ambulance.html')
@app.route('/admin')
@auth
@admin
def admin_page():
 c=db();s=[c.execute("SELECT COUNT(*) FROM users WHERE role='patient'").fetchone()[0],c.execute('SELECT COUNT(*) FROM doctors').fetchone()[0],c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],c.execute('SELECT COUNT(*) FROM ambulances').fetchone()[0]];c.close();return render_template('admin.html',stats=s)
@app.route('/seed-admin')
def seed():
 c=db()
 if not c.execute("SELECT 1 FROM users WHERE email='admin@medicare.local'").fetchone():c.execute("INSERT INTO users(name,email,password,role,created) VALUES(?,?,?,?,?)",('MediCare Admin','admin@medicare.local',generate_password_hash('Admin@12345'),'admin',datetime.now().isoformat()));c.commit()
 c.close();return 'Demo admin: admin@medicare.local / Admin@12345. Remove this route before production.'
if __name__=='__main__':init();app.run(host='0.0.0.0',port=5000,debug=True)
