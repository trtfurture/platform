import os, re, json, hmac, secrets, sqlite3, shutil, time, threading, zipfile, csv
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, abort, make_response, has_request_context
from flask_session import Session
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import bcrypt, qrcode
from io import BytesIO
from hashlib import sha256
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/'.env')
PROD=os.environ.get('RENDER')=='true' or bool(os.environ.get('RENDER_EXTERNAL_URL')) or os.environ.get('FLASK_ENV')=='production'
# Public launch tariff (KES). Keep this table as the single source of truth for
# the advertiser form, referral conversions, payment validation and admin views.
PROMOTION_PRICES = {
 'vip': {30: 3000, 60: 5500, 90: 7500},
 'vvip': {30: 6000, 60: 11000, 90: 15000},
}
PROMOTION_DURATIONS = (30, 60, 90)
def promotion_price(tier, duration_days):
 try: return PROMOTION_PRICES[tier][int(duration_days)]
 except (KeyError, TypeError, ValueError): return None

# Prefer Render's persistent disk when it is actually mounted and writable.
# Free Render instances do not have persistent disks; in that case use a
# project-local directory so the web process can start, while warning that
# local files are ephemeral until a persistent disk is attached.
def _writable_directory(path):
 try:
  path.mkdir(parents=True,exist_ok=True)
  probe=path/f'.schools-write-check-{os.getpid()}'
  fd=os.open(str(probe),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  os.close(fd)
  probe.unlink(missing_ok=True)
  return True
 except OSError:
  return False

configured_data=os.environ.get('DATA_DIR','').strip()
if configured_data:
 candidate=Path(configured_data).expanduser().resolve()
else:
 candidate=Path('/var/data') if PROD else (BASE/'storage')
 candidate=candidate.resolve()
if _writable_directory(candidate):
 DATA=candidate
 if PROD and DATA == Path('/var/data'):
  print('SCHOOLS storage: using Render persistent disk at /var/data.')
elif PROD and candidate == Path('/var/data'):
 DATA=(BASE/'storage').resolve()
 if not _writable_directory(DATA):
  raise RuntimeError('Render disk /var/data is not writable and project-local storage could not be created. Attach a writable persistent disk mounted at /var/data.')
 print('WARNING: /var/data is not mounted/writable. SCHOOLS is using temporary project-local storage. Database, uploads, backups and session key may be lost on restart or redeploy. Attach a persistent disk at /var/data for production.')
else:
 raise RuntimeError(f'SCHOOLS storage directory is not writable: {candidate}. Attach a writable Render persistent disk or correct DATA_DIR.')
UPLOAD=DATA/'uploads'; BACKUP=DATA/'backups'
for folder in (UPLOAD,BACKUP):
 folder.mkdir(parents=True,exist_ok=True)
PORT=int(os.environ.get('PORT','10000'))
SITE=(os.environ.get('RENDER_EXTERNAL_URL') or ('https://schoolskenya.onrender.com' if PROD else f'http://localhost:{PORT}')).rstrip('/')
ADMIN_USERNAME=os.environ.get('ADMIN_USERNAME','admin')
ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD','')
if PROD and (not ADMIN_USERNAME or not ADMIN_PASSWORD):
 raise RuntimeError('Set ADMIN_USERNAME and ADMIN_PASSWORD in Render environment variables.')
ADMIN_PASSWORD_HASH=bcrypt.hashpw(ADMIN_PASSWORD.encode(),bcrypt.gensalt()) if ADMIN_PASSWORD else None

def load_persistent_session_key(path):
 key_path=path/'.schools-session-key'
 try:
  fd=os.open(str(key_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  key=secrets.token_bytes(64)
  with os.fdopen(fd,'wb') as handle:
   handle.write(key); handle.flush(); os.fsync(handle.fileno())
  return key
 except FileExistsError:
  key=key_path.read_bytes()
  if len(key)<32:
   raise RuntimeError('The stored session key is invalid. Keep the Render persistent disk attached and restore the key file.')
  return key

app=Flask(__name__,static_folder='static',static_url_path='')
def current_site():
 return request.host_url.rstrip('/') if has_request_context() else SITE
app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
app.secret_key=load_persistent_session_key(DATA)
referral_serializer=URLSafeTimedSerializer(app.secret_key,salt='kenya-schools-referral-v1')
app.config.update(SESSION_TYPE='filesystem',SESSION_FILE_DIR=str(DATA/'flask_sessions'),SESSION_PERMANENT=True,PERMANENT_SESSION_LIFETIME=timedelta(hours=8),SESSION_COOKIE_NAME='schools.admin',SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=PROD,SESSION_USE_SIGNER=True,MAX_CONTENT_LENGTH=50*1024*1024)
Path(app.config['SESSION_FILE_DIR']).mkdir(parents=True,exist_ok=True)
Session(app)
limiter=Limiter(get_remote_address,app=app,default_limits=[])
DB=DATA/'schools.sqlite'
@contextmanager
def conn():
 c=sqlite3.connect(DB,timeout=15)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 c.execute('PRAGMA busy_timeout=5000')
 try:
  yield c
  c.commit()
 except Exception:
  c.rollback()
  raise
 finally:
  c.close()
SCHEMA=r'''
  CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'school',
    ownership TEXT DEFAULT '',
    levels TEXT DEFAULT '',
    county TEXT DEFAULT '',
    town TEXT DEFAULT '',
    accommodation TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    curriculum TEXT DEFAULT '',
    fees_range TEXT DEFAULT '',
    address TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    website TEXT DEFAULT '',
    description TEXT DEFAULT '',
    logo_path TEXT DEFAULT '',
    cover_path TEXT DEFAULT '',
    video_url TEXT DEFAULT '',
    trust_status TEXT NOT NULL DEFAULT 'unverified',
    promotion_tier TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'pending',
    source_note TEXT DEFAULT '',
    is_seeded INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    posted_at TEXT DEFAULT '',
    expires_at TEXT DEFAULT '',
    last_renewed_at TEXT DEFAULT '',
    last_featured_at TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    property_type TEXT DEFAULT 'Hostel',
    institution TEXT DEFAULT '',
    county TEXT DEFAULT '',
    town TEXT DEFAULT '',
    price TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER,
    name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (school_id) REFERENCES schools(id)
  );

  CREATE TABLE IF NOT EXISTS admin_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    route TEXT DEFAULT '',
    stack TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    record_type TEXT DEFAULT '',
    record_id INTEGER,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    sess TEXT NOT NULL,
    expires_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS visitor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    visitor_key TEXT NOT NULL,
    user_agent TEXT DEFAULT '',
    referrer TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS site_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
  );
  CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS customer_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(phone)
  );
  CREATE TABLE IF NOT EXISTS payment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    purpose TEXT NOT NULL,
    tier TEXT DEFAULT '',
    duration_days INTEGER NOT NULL DEFAULT 30,
    amount TEXT DEFAULT '',
    reference TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    paid_at TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES customer_accounts(id)
  );

  CREATE TABLE IF NOT EXISTS portal_enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_name TEXT NOT NULL,
    institution TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT DEFAULT '',
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS institution_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL,
    reviewer_name TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'Other',
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    review_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    created_at TEXT NOT NULL,
    moderated_at TEXT DEFAULT '',
    FOREIGN KEY (school_id) REFERENCES schools(id) ON DELETE CASCADE
  );
  CREATE TABLE IF NOT EXISTS referral_partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,
    email TEXT DEFAULT '',
    code TEXT NOT NULL UNIQUE,
    dashboard_token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS school_referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    school_id INTEGER NOT NULL UNIQUE,
    account_id INTEGER UNIQUE,
    referral_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'registered' CHECK(status IN ('registered','converted','disqualified')),
    created_at TEXT NOT NULL,
    converted_at TEXT DEFAULT '',
    FOREIGN KEY(referrer_id) REFERENCES referral_partners(id),
    FOREIGN KEY(school_id) REFERENCES schools(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES customer_accounts(id)
  );

  CREATE TABLE IF NOT EXISTS referral_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referral_id INTEGER NOT NULL UNIQUE,
    payment_record_id INTEGER NOT NULL UNIQUE,
    amount_kes INTEGER NOT NULL DEFAULT 1000 CHECK(amount_kes=1000),
    status TEXT NOT NULL DEFAULT 'pending_clearance' CHECK(status IN ('pending_clearance','payable','paid','void','reversal_review')),
    earned_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    paid_at TEXT DEFAULT '',
    payout_reference TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    FOREIGN KEY(referral_id) REFERENCES school_referrals(id),
    FOREIGN KEY(payment_record_id) REFERENCES payment_records(id)
  );
'''
with conn() as c:
 c.execute('PRAGMA journal_mode=WAL')
 c.executescript(SCHEMA)
 for table,col,definition in [('schools','photos_json',"TEXT DEFAULT '[]'"),('schools','promotion_expires_at',"TEXT DEFAULT ''"),('schools','requested_tier',"TEXT DEFAULT 'none'"),('schools','requested_duration_days','INTEGER NOT NULL DEFAULT 30'),('schools','owner_account_id',"INTEGER"),('properties','owner_account_id',"INTEGER"),('payment_records','school_id',"INTEGER"),('payment_records','referral_id',"INTEGER"),('payment_records','duration_days','INTEGER NOT NULL DEFAULT 30'),('payment_records','paid_at',"TEXT DEFAULT ''")]:
  cols=[r['name'] for r in c.execute(f'PRAGMA table_info({table})')]
  if col not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
 c.execute("""UPDATE payment_records
  SET amount=CASE tier
    WHEN 'vip' THEN CASE duration_days WHEN 30 THEN '3000' WHEN 60 THEN '5500' WHEN 90 THEN '7500' END
    WHEN 'vvip' THEN CASE duration_days WHEN 30 THEN '6000' WHEN 60 THEN '11000' WHEN 90 THEN '15000' END
    ELSE amount END,
   status='awaiting_payment',
   notes=COALESCE(notes,'') || ' Updated to the published fixed advertising tariff.'
  WHERE purpose='Institution promotion' AND tier IN ('vip','vvip') AND status='awaiting_quote' AND (amount IS NULL OR TRIM(amount)='')""")
 c.execute("DELETE FROM admin_errors WHERE route='/pulse_receiver' AND message LIKE '%405 Method Not Allowed%'")
 c.executescript("CREATE INDEX IF NOT EXISTS idx_visitors_created ON visitor_events(created_at); CREATE INDEX IF NOT EXISTS idx_visitors_path ON visitor_events(path); CREATE INDEX IF NOT EXISTS idx_schools_status_category ON schools(status, category); CREATE INDEX IF NOT EXISTS idx_schools_county ON schools(county); CREATE INDEX IF NOT EXISTS idx_schools_promotions ON schools(promotion_tier, promotion_expires_at); CREATE INDEX IF NOT EXISTS idx_reviews_school_status ON institution_reviews(school_id,status,created_at); CREATE INDEX IF NOT EXISTS idx_referral_code ON referral_partners(code); CREATE INDEX IF NOT EXISTS idx_school_referrals_referrer ON school_referrals(referrer_id,status); CREATE INDEX IF NOT EXISTS idx_referral_rewards_status ON referral_rewards(status,available_at);")

def now(): return datetime.now(timezone.utc).isoformat()
def safe(v,n=5000): return str(v or '').strip()[:n]
def slugify(v):
 import unicodedata
 v=''.join(ch for ch in unicodedata.normalize('NFKD',str(v or '')) if not unicodedata.combining(ch)).lower()
 return re.sub(r'-+','-',re.sub(r'[^a-z0-9]+','-',v)).strip('-')[:75]
def safe_url(v):
 v=safe(v,500)
 if not v:return ''
 if not v.startswith(('http://','https://')):v='https://'+v
 return v if urlparse(v).scheme in ('http','https') and urlparse(v).netloc else ''
def get_or_create_customer(name,phone,email=''):
 name=safe(name,160); phone=safe(phone,60); email=safe(email,160)
 if not name or not phone: raise ValueError('A contact name and phone number are required to create a customer account.')
 with conn() as c:
  row=c.execute('SELECT id FROM customer_accounts WHERE phone=?',(phone,)).fetchone()
  if row:
   c.execute('UPDATE customer_accounts SET full_name=?,email=? WHERE id=?',(name,email,row['id']))
   return row['id']
  cur=c.execute('INSERT INTO customer_accounts(full_name,email,phone,created_at) VALUES(?,?,?,?)',(name,email,phone,now()))
  return cur.lastrowid

def normalise_contact(value):
 digits=re.sub(r'\D','',str(value or ''))
 if len(digits)==12 and digits.startswith('254'):return digits[-9:]
 if len(digits)==10 and digits.startswith('0'):return digits[-9:]
 return digits

def current_referral_partner():
 raw=request.cookies.get('schools_referral','')
 if not raw:return None
 try: code=referral_serializer.loads(raw,max_age=30*24*60*60)
 except (BadSignature,SignatureExpired,ValueError,TypeError):return None
 with conn() as c:
  row=c.execute("SELECT id,full_name,phone,email,code,status FROM referral_partners WHERE code=? AND status='active'",(code,)).fetchone()
 return dict(row) if row else None

def referral_reward_summary(partner_id):
 with conn() as c:
  row=c.execute("SELECT COUNT(*) AS referrals, SUM(CASE WHEN status='converted' THEN 1 ELSE 0 END) AS converted FROM school_referrals WHERE referrer_id=?",(partner_id,)).fetchone()
  rewards=c.execute("SELECT COALESCE(SUM(amount_kes),0) AS total, COALESCE(SUM(CASE WHEN status IN ('pending_clearance','payable') THEN amount_kes ELSE 0 END),0) AS outstanding, COALESCE(SUM(CASE WHEN status='paid' THEN amount_kes ELSE 0 END),0) AS paid FROM referral_rewards r JOIN school_referrals sr ON sr.id=r.referral_id WHERE sr.referrer_id=?",(partner_id,)).fetchone()
 return {'referrals':row['referrals'] or 0,'converted':row['converted'] or 0,'total':rewards['total'] or 0,'outstanding':rewards['outstanding'] or 0,'paid':rewards['paid'] or 0}

def audit(action,typ='',rid=None,detail=''):
 with conn() as c:c.execute('INSERT INTO audit_events(action,record_type,record_id,detail,created_at) VALUES(?,?,?,?,?)',(action,typ,rid,safe(detail,1000),now()))
def log_error(err,route=''):
 try:
  with conn() as c:c.execute('INSERT INTO admin_errors(level,message,route,stack,created_at) VALUES(?,?,?,?,?)',('error',safe(err,1000),route,safe(repr(err),6000),now()))
 except Exception:pass
 app.logger.exception('Application error')
def format_date(v):
 try:return datetime.fromisoformat(v.replace('Z','+00:00')).strftime('%-d %b %Y')
 except:return ''
def join_nonempty(items,sep=', '):return sep.join(str(x) for x in items if x)
def filter_nonempty(items):return [x for x in items if x]
COUNTIES=['Baringo','Bomet','Bungoma','Busia','Elgeyo-Marakwet','Embu','Garissa','Homa Bay','Isiolo','Kajiado','Kakamega','Kericho','Kiambu','Kilifi','Kirinyaga','Kisii','Kisumu','Kitui','Kwale','Laikipia','Lamu','Machakos','Makueni','Mandera','Marsabit','Meru','Migori','Mombasa','Murang’a','Nairobi','Nakuru','Nandi','Narok','Nyamira','Nyandarua','Nyeri','Samburu','Siaya','Taita-Taveta','Tana River','Tharaka-Nithi','Trans Nzoia','Turkana','Uasin Gishu','Vihiga','Wajir','West Pokot']

# Real photographs with confirmed Creative Commons Attribution-ShareAlike licences.
# Only records with the matching institution slug are eligible; no institution is added or recategorised.
CC_BY_SA='https://creativecommons.org/licenses/by-sa/4.0/'
def commons_file(filename):
 from urllib.parse import quote
 return 'https://commons.wikimedia.org/wiki/Special:FilePath/'+quote(filename,safe='')+'?width=1280'
PHOTO_ASSETS={
 'alliance-high-school':[
  {'url':'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/New_Complex_at_Alliance_High_School.jpg/1280px-New_Complex_at_Alliance_High_School.jpg','title':'New Complex at Alliance High School','author':'Hansie453','source':'https://commons.wikimedia.org/wiki/File:New_Complex_at_Alliance_High_School.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/0/0f/Alliance_High_School_Administration_Block_-_Back_View.jpg/1280px-Alliance_High_School_Administration_Block_-_Back_View.jpg','title':'Alliance High School Administration Block, rear view','author':'NevilleOmangi','source':'https://commons.wikimedia.org/wiki/File:Alliance_High_School_Administration_Block_-_Back_View.jpg'}
 ],
 'university-of-nairobi':[
  {'url':'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/University_of_Nairobi_Entrance.jpg/1280px-University_of_Nairobi_Entrance.jpg','title':'University of Nairobi Entrance','author':'EstherWikipedian','source':'https://commons.wikimedia.org/wiki/File:University_of_Nairobi_Entrance.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b6/University_of_Nairobi_Tower.jpg/1280px-University_of_Nairobi_Tower.jpg','title':'University of Nairobi Tower','author':'EstherWikipedian','source':'https://commons.wikimedia.org/wiki/File:University_of_Nairobi_Tower.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/2/28/University_of_Nairobi_Mahatma_Gandhi_Memorial_Library.jpg/1280px-University_of_Nairobi_Mahatma_Gandhi_Memorial_Library.jpg','title':'University of Nairobi Mahatma Gandhi Memorial Library','author':'EstherWikipedian','source':'https://commons.wikimedia.org/wiki/File:University_of_Nairobi_Mahatma_Gandhi_Memorial_Library.jpg'},
  {'url':commons_file('University of Nairobi, Kenya.jpg'),'title':'University of Nairobi, outside view','author':'EstherWikipedian','source':'https://commons.wikimedia.org/wiki/File:University_of_Nairobi,_Kenya.jpg'}
 ],
 'kenyatta-university':[
  {'url':'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Kenyatta_University_Entrance.jpg/1280px-Kenyatta_University_Entrance.jpg','title':'Kenyatta University Entrance','author':'Thorkild Tylleskar','source':'https://commons.wikimedia.org/wiki/File:Kenyatta_University_Entrance.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2f/KenyattaUnivAdmin.jpg/960px-KenyattaUnivAdmin.jpg','title':'Kenyatta University Central Administration Complex','author':'Thorkild Tylleskar','source':'https://commons.wikimedia.org/wiki/File:KenyattaUnivAdmin.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2b/KenyattaUnivLibrary.jpg/960px-KenyattaUnivLibrary.jpg','title':'Kenyatta University Library','author':'Thorkild Tylleskar','source':'https://commons.wikimedia.org/wiki/File:KenyattaUnivLibrary.jpg'},
  {'url':'https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7f/KenyattaUnivCampanile.jpg/960px-KenyattaUnivCampanile.jpg','title':'Kenyatta University Campanile','author':'Thorkild Tylleskar','source':'https://commons.wikimedia.org/wiki/File:KenyattaUnivCampanile.jpg'},
  {'url':commons_file('KenyattaUnivComputerCentre.jpg'),'title':'Kenyatta University Computer Centre','author':'Thorkild Tylleskar','source':'https://commons.wikimedia.org/wiki/File:KenyattaUnivComputerCentre.jpg'}
 ],
 'strathmore-university':[
  {'url':commons_file('Strathmore-University-Management-science-building.jpg'),'title':'Strathmore University Management Science Building','author':'Strathmore University Kenya','source':'https://commons.wikimedia.org/wiki/File:Strathmore-University-Management-science-building.jpg'},
  {'url':commons_file('Strathmore University Student Centre.jpg'),'title':'Strathmore University Student Centre','author':'Strathmore University Kenya','source':'https://commons.wikimedia.org/wiki/File:Strathmore_University_Student_Centre.jpg'},
  {'url':commons_file('Strathmore University Library by night.jpg'),'title':'Strathmore University Library','author':'Strathmore University Kenya','source':'https://commons.wikimedia.org/wiki/File:Strathmore_University_Library_by_night.jpg'},
  {'url':commons_file('Strathmore-University.jpg'),'title':'Strathmore University students walking to class','author':'Strathmore University Kenya','source':'https://commons.wikimedia.org/wiki/File:Strathmore-University.jpg'}
 ],
 'mangu-high-school':[
  {'url':'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/Mang%27u_High_School.png/500px-Mang%27u_High_School.png','title':"Mang'u High School administration block",'author':'Anthony Mudhoka','source':"https://commons.wikimedia.org/wiki/File:Mang%27u_High_School.png"},
  {'url':'https://upload.wikimedia.org/wikipedia/commons/1/17/Mang%27uhigh.jpg','title':"Mang'u High School",'author':'Andygroove','source':"https://commons.wikimedia.org/wiki/File:Mang%27uhigh.jpg",'license':'Public domain','license_url':'https://commons.wikimedia.org/wiki/File:Mang%27uhigh.jpg'}
 ],
 'kenya-high-school':[
  {'url':'https://upload.wikimedia.org/wikipedia/commons/thumb/c/cb/The_Kenya_High_School_Main_Gate.jpg/1280px-The_Kenya_High_School_Main_Gate.jpg','title':'The Kenya High School Main Gate','author':'Lilly Stein','source':'https://commons.wikimedia.org/wiki/File:The_Kenya_High_School_Main_Gate.jpg'}
 ],
 'kenya-medical-training-college-karen':[
  {'url':commons_file('Kenya Medical Training College Karen Campus entrance.jpg'),'title':'Kenya Medical Training College Karen Campus entrance','author':'Sdkb','source':'https://commons.wikimedia.org/wiki/File:Kenya_Medical_Training_College_Karen_Campus_entrance.jpg'}
 ],
 'jomo-kenyatta-university-of-agriculture-and-technology':[
  {'url':commons_file('JKUAT-Main-Campus-Gate-A.jpg'),'title':'JKUAT Main Campus Gate A','author':'Onsomu','source':'https://commons.wikimedia.org/wiki/File:JKUAT-Main-Campus-Gate-A.jpg'}
 ],
 'alupe-university':[
  {'url':commons_file('Alupe University Administration Block.jpg'),'title':'Alupe University Administration Block','author':'Totibine','source':'https://commons.wikimedia.org/wiki/File:Alupe_University_Administration_Block.jpg'}
 ],
 'maseno-school':[
  {'url':commons_file('Maseno School Photo.jpg'),'title':'Maseno School group photograph beside the dining hall','author':'Ajwoga','source':'https://commons.wikimedia.org/wiki/File:Maseno_School_Photo.jpg','license':'CC BY-SA 3.0','license_url':'https://creativecommons.org/licenses/by-sa/3.0/'}
 ]
}
HERO_PHOTO=PHOTO_ASSETS['university-of-nairobi'][0]
PHOTO_CREDITS={item['url']:item for group in PHOTO_ASSETS.values() for item in group}
def apply_real_photo_defaults():
 # Remove the old generic/generated hero from every record, but keep all real user-uploaded photos.
 # Add institution-specific licensed photos only to an exact matching existing slug.
 with conn() as c:
  rows=c.execute('SELECT id,slug,cover_path,photos_json FROM schools').fetchall()
  for row in rows:
   cover=(row['cover_path'] or '').strip()
   raw=(row['photos_json'] or '').strip()
   try:
    gallery=json.loads(raw) if raw else []
    if not isinstance(gallery,list): gallery=[]
   except Exception:
    gallery=[]
   cleaned_gallery=[x for x in gallery if isinstance(x,str) and x.strip() and not (x.strip()=='/images/school-hero.webp' or x.strip().endswith('/school-hero.webp'))]
   cover_is_placeholder=(not cover or cover=='/images/school-hero.webp' or cover.endswith('/school-hero.webp'))
   assets=PHOTO_ASSETS.get(row['slug'],[])
   if cover_is_placeholder:
    cover=cleaned_gallery[0] if cleaned_gallery else (assets[0]['url'] if assets else '')
   if not cleaned_gallery and assets:
    cleaned_gallery=[item['url'] for item in assets]
   new_gallery=json.dumps(cleaned_gallery,ensure_ascii=False)
   if cover_is_placeholder or cover!=(row['cover_path'] or '').strip() or new_gallery!=(raw or '[]'):
    c.execute('UPDATE schools SET cover_path=?,photos_json=? WHERE id=?',(cover,new_gallery,row['id']))

def photo_attribution(url):
 item=PHOTO_CREDITS.get(str(url or '').strip())
 if not item:return None
 result=dict(item)
 result['licenseLabel']=item.get('license','CC BY-SA 4.0')
 result['licenseUrl']=item.get('license_url',CC_BY_SA)
 return result
def institution_initials(name):
 words=[x for x in re.split(r'\s+',str(name or '').strip()) if x]
 if not words:return 'SC'
 return ''.join(word[0] for word in words[:2]).upper()
app.jinja_env.globals.update(formatDate=format_date,join_nonempty=join_nonempty,filter_nonempty=filter_nonempty,phone_digits=lambda value: re.sub(r'[^0-9]','',str(value or '')),current_year=datetime.now().year,photoAttribution=photo_attribution,institutionInitials=institution_initials)
SEED=[('Alliance High School','alliance-high-school','school','Public','Secondary','Kiambu','Kikuyu','Boarding','Boys','Secondary education','https://www.alliancehighschool.ac.ke/','A recognised Kenyan secondary school in Kikuyu, Kiambu County. This directory profile is an introductory listing; contact the school directly for current admissions, fees and requirements.'),('Strathmore School','strathmore-school','school','Private','Primary, Junior, Secondary','Nairobi','Lavington','Day','','Contact institution for current curriculum details','https://www.strathmore.ac.ke/','A private school located in Lavington, Nairobi. Explore its official website for current school-life, admissions and transfer information.'),('University of Nairobi','university-of-nairobi','university','Public','University','Nairobi','Nairobi','','Mixed','Degree and postgraduate programmes','https://www.uonbi.ac.ke/','A public university based in Nairobi with multiple campuses and academic programmes. Visit the official website for current courses, admissions and campus information.'),('Kenyatta University','kenyatta-university','university','Public','University','Nairobi','Kahawa','','Mixed','Degree and postgraduate programmes','https://www.ku.ac.ke/','A public university whose main campus is in Kahawa, Nairobi County. Visit the official university website for current programmes, admissions and campus details.'),('Kenya Utalii College','kenya-utalii-college','college','Public','College / TVET','Nairobi','Off Thika Road','','Mixed','Hospitality and tourism training','https://utalii.ac.ke/','A hospitality and tourism training institution with its main campus off Thika Road in Nairobi. Visit the official website for current programmes, admissions and campus information.')]
with conn() as c:
 if c.execute('SELECT COUNT(*) FROM schools').fetchone()[0]==0:
  for r in SEED:
   name,slug,cat,own,levels,county,town,accom,gender,curr,web,desc=r; t=now()
   c.execute("INSERT INTO schools(name,slug,category,ownership,levels,county,town,accommodation,gender,curriculum,website,description,trust_status,promotion_tier,status,source_note,is_seeded,posted_at,expires_at,last_renewed_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'recognised','none','published',?,1,?,'',?,?,?)",(name,slug,cat,own,levels,county,town,accom,gender,curr,web,desc,'Recognised public-information listing. The institution has not yet claimed or confirmed this profile on SCHOOLS.',t,t,t,t))


# Additive Phase 1 national public senior-school directory import.
# The source list is an independently published 2026 C1 school list; entries are
# marked unverified until each institution claims or confirms its profile.
C1_SOURCE_NOTE = (
 "Directory data transcribed from CBC Teachers Online, '2026 C1 Senior Schools: "
 "Complete List of National Schools by County', published 29 September 2026. "
 "County and sub-county are reproduced from that published list. This listing "
 "has not been individually confirmed by the institution on SCHOOLS."
)
def import_public_senior_schools():
 source_file=BASE/'public_senior_schools_2026.csv'
 if not source_file.is_file():
  app.logger.warning('Public C1 school seed file missing; existing directory left unchanged.')
  return
 added=0
 with source_file.open('r',encoding='utf-8-sig',newline='') as handle:
  entries=list(csv.DictReader(handle))
 with conn() as c:
  for item in entries:
   name=safe(item.get('name'),180)
   county=safe(item.get('county'),80)
   subcounty=safe(item.get('subcounty'),100)
   gender=safe(item.get('gender'),20)
   if not name or county not in COUNTIES:
    continue
   slug=slugify(name)
   existing=c.execute('SELECT id FROM schools WHERE slug=? OR (lower(name)=lower(?) AND lower(county)=lower(?))',(slug,name,county)).fetchone()
   if existing:
    continue
   base_slug=slug
   suffix=slugify(county) or 'public'
   candidate=f'{base_slug}-{suffix}'[:75]
   counter=2
   while c.execute('SELECT 1 FROM schools WHERE slug=?',(candidate,)).fetchone():
    candidate=f'{base_slug}-{suffix}-{counter}'[:75]
    counter+=1
   slug=candidate if slug!=base_slug else base_slug
   timestamp=now()
   description=(
    f"Listed as a C1 senior secondary school in the 2026 county directory. "
    f"The published source places it in {subcounty}, {county} County. "
    "Confirm current admissions, programmes, boarding availability and requirements directly with the school."
   )
   c.execute("""INSERT INTO schools
    (name,slug,category,ownership,levels,county,town,gender,curriculum,description,
     trust_status,promotion_tier,status,source_note,is_seeded,posted_at,expires_at,
     last_renewed_at,created_at,updated_at)
    VALUES(?,?,'school','Public','C1 Senior Secondary',?,?,?,?,?,
     'unverified','none','published',?,1,?,'','',?,?)""",
    (name,slug,county,subcounty,gender,'CBC Senior School (C1)',description,C1_SOURCE_NOTE,timestamp,timestamp,timestamp))
   added+=1
 if added:
  app.logger.info('Added %s sourced C1 public senior-school profiles; existing records were not overwritten.',added)

import_public_senior_schools()

apply_real_photo_defaults()


def active_schools(where='',params=()):
 t=now()
 with conn() as c:return [dict(x) for x in c.execute(f"SELECT *, CASE WHEN promotion_tier <> 'none' AND promotion_expires_at > ? THEN promotion_tier ELSE 'none' END AS active_promotion_tier, COALESCE((SELECT ROUND(AVG(r.rating),1) FROM institution_reviews r WHERE r.school_id=schools.id AND r.status='approved'),0) AS average_rating, (SELECT COUNT(*) FROM institution_reviews r WHERE r.school_id=schools.id AND r.status='approved') AS review_count FROM schools WHERE status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?) {where} ORDER BY CASE WHEN promotion_tier='vvip' AND promotion_expires_at>? THEN 0 WHEN promotion_tier='vip' AND promotion_expires_at>? THEN 1 ELSE 2 END, CASE WHEN cover_path IS NOT NULL AND TRIM(cover_path)<>'' THEN 0 ELSE 1 END, COALESCE(last_featured_at,'') ASC, name COLLATE NOCASE ASC",(t,t,*params,t,t)).fetchall()]
def feature_rotation(rows,limit=4):
 picked=rows[:limit]; stamp=datetime.now(timezone.utc)
 with conn() as c:
  for i,row in enumerate(picked):
   if row.get('active_promotion_tier',row.get('promotion_tier'))!='none':c.execute('UPDATE schools SET last_featured_at=? WHERE id=?',((stamp+timedelta(seconds=len(picked)-i)).isoformat(),row['id']))
 return picked
def base_context():
 t=now(); path=request.path
 promos=[]
 if not path.startswith('/admin') and path!='/':
  with conn() as c: rows=[dict(x) for x in c.execute("SELECT * FROM schools WHERE status='published' AND promotion_tier='vvip' AND promotion_expires_at>? AND (expires_at='' OR expires_at IS NULL OR expires_at>?) ORDER BY COALESCE(last_featured_at,'') ASC LIMIT 8",(t,t)).fetchall()]
  promos=feature_rotation(rows,3)
 with conn() as c: public_settings={r['key']:r['value'] for r in c.execute("SELECT key,value FROM site_settings WHERE key IN ('business_name','contact_email','contact_phone','whatsapp','payment_instructions','mpesa_paybill','mpesa_till','mpesa_account','public_address')")}
 site=current_site(); qrurl=site+'/?source=toror-signature-qr'
 qr=qrcode.QRCode(box_size=3,border=1); qr.add_data(qrurl); qr.make(fit=True); im=qr.make_image(fill_color='#17324d',back_color='white'); bio=BytesIO(); im.save(bio,format='PNG')
 from base64 import b64encode
 return dict(current_year=datetime.now().year,publicSettings=public_settings,siteName='Kenya Schools',siteUrl=site,companyName='Toror Technology and Innovations Limited',qrData='data:image/png;base64,'+b64encode(bio.getvalue()).decode(),metaTitle='Kenya Schools | Find Schools, Colleges & Universities',metaDescription='Find and compare schools, colleges and universities across Kenya. Explore institution profiles, locations, facilities, admissions and campus accommodation.',canonical=site+('/' if path=='/' else path),pageImage=site+'/images/kenya-schools-profile.jpg',heroCredit=photo_attribution(HERO_PHOTO['url']),isAdmin=bool(session.get('admin')),csrfToken=session.get('csrfToken',''),robots='index,follow',globalPromos=promos,structured_data={'@context':'https://schema.org','@type':'WebSite','name':'Kenya Schools','url':site,'description':'Find and compare schools, colleges and universities across Kenya.','publisher':{'@type':'Organization','name':'Toror Technology and Innovations Limited','url':site,'logo':site+'/images/kenya-schools-profile.jpg'},'potentialAction':{'@type':'SearchAction','target':site+'/schools?q={search_term_string}','query-input':'required name=search_term_string'}})
def page(template,**kwargs):
 ctx=base_context(); ctx.update(kwargs)
 if template=='directory':
  ctx.setdefault('metaTitle', (kwargs.get('title') or 'Explore institutions')+' | Kenya Schools')
  ctx.setdefault('metaDescription', (kwargs.get('intro') or 'Explore schools, colleges and universities across Kenya.')+' Compare institution profiles, locations, programmes and contact information.')
  ctx.setdefault('canonical', current_site()+request.path)
  if request.args: ctx['robots']='noindex,follow'
  if len(kwargs.get('schools',[]))<3 and request.path.startswith('/schools-in-'): ctx['robots']='noindex,follow'
 elif template=='home':
  ctx.update(metaTitle='Kenya Schools | Find Schools, Colleges & Universities Across Kenya',
   metaDescription='Find schools in Kenya by name, county and education level. Explore primary and secondary schools, colleges, TVET institutions, universities and student accommodation.')
 elif template=='contact':
  ctx.update(metaTitle='Contact Kenya Schools',metaDescription='Contact the Kenya Schools team about institution listings, education information, school portals and campus accommodation.')
 elif template=='advertise':
  ctx.update(metaTitle='List Your Institution | Kenya Schools',metaDescription='Create a school listing, showcase your campus, publish admissions information and reach parents and learners searching for institutions in Kenya.')
 elif template=='portal':
  ctx.update(metaTitle='Get a School Website & Portal | Kenya Schools',metaDescription='Get a modern school website with admissions pages, galleries, announcements and an easy content dashboard.')
 elif template=='campus':
  ctx.update(metaTitle='Student Accommodation, Hostels & Rentals in Kenya | Kenya Schools',metaDescription='Explore student hostels, rental accommodation and campus-area services. Find places near colleges and universities.')
 return render_template(template+'.html',**ctx)
def error_page(title,message,status=400):return page('error',title=title,message=message),status
def admin_required():
 if not session.get('admin'):return redirect('/admin/login')
 return None
def csrf_ok():
 a=safe(request.form.get('_csrf')); b=safe(session.get('csrfToken'))
 return bool(a and b and hmac.compare_digest(a,b))
def admin_guard():
 r=admin_required()
 if r:return r
 if not csrf_ok():return error_page('Session check failed','Please reload the admin page and try again.',403)
 return None
def expire_listings():
 with conn() as c:c.execute("UPDATE schools SET status='expired',updated_at=? WHERE status='published' AND is_seeded=0 AND expires_at<>'' AND expires_at<?",(now(),now()))
expire_listings()

def create_backup():
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); dest=BACKUP/f'schools-{stamp}.sqlite'
 with conn() as c:
  target=sqlite3.connect(dest); c.backup(target); target.close()
 for old in sorted(BACKUP.glob('*.sqlite'),reverse=True)[14:]:old.unlink(missing_ok=True)
 return dest

def maintenance_loop():
 import time
 time.sleep(5)
 try: create_backup()
 except Exception as exc: log_error(exc, 'startup-backup')
 last_backup=time.monotonic()
 while True:
  try: expire_listings()
  except Exception as exc: log_error(exc, 'scheduled-expiry')
  if time.monotonic()-last_backup >= 86400:
   try: create_backup(); last_backup=time.monotonic()
   except Exception as exc: log_error(exc, 'scheduled-backup')
  time.sleep(3600)
threading.Thread(target=maintenance_loop,daemon=True,name='schools-maintenance').start()

@app.before_request
def record_public_visit():
 path=request.path or '/'
 if path.startswith(('/admin','/static','/css','/js','/images','/uploads','/healthz','/pulse_receiver')) or path in ('/favicon.ico','/robots.txt','/sitemap.xml'):
  return
 # Optional analytics are off until a visitor opts in through Cookie settings.
 if request.cookies.get('schools_analytics') != '1':
  return
 if request.method != 'GET' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
  return
 agent=safe(request.user_agent.string,300).lower()
 if any(token in agent for token in ('bot','crawler','spider','slurp','headless','uptime','monitoring')):
  return
 try:
  # Daily pseudonymous key; no IP address is stored.
  from hashlib import sha256
  raw=(request.cookies.get('schools_visit') or secrets.token_urlsafe(24))
  key=sha256(raw.encode()).hexdigest()
  with conn() as c:
   c.execute('INSERT INTO visitor_events(path,visitor_key,user_agent,referrer,created_at) VALUES(?,?,?,?,?)',
    (path[:300],key,safe(request.user_agent.string,300),safe(request.referrer,500),now()))
  request._visit_cookie=raw
 except Exception as exc:
  log_error(exc,'visitor-tracking')

@app.route('/pulse_receiver', methods=['GET','POST','OPTIONS'])
def pulse_receiver():
 # Compatibility endpoint for older installed PWA clients; telemetry must never block browsing.
 if request.method == 'OPTIONS':
  response=make_response('',204)
 else:
  response=make_response('',204)
 response.headers['Cache-Control']='no-store'
 return response

@app.after_request
def security_headers(resp):
 resp.headers.setdefault('X-Content-Type-Options','nosniff'); resp.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin'); resp.headers.setdefault('X-Frame-Options','SAMEORIGIN'); resp.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
 if hasattr(request,'_visit_cookie'):
  resp.set_cookie('schools_visit',request._visit_cookie,max_age=31536000,httponly=True,samesite='Lax',secure=PROD)
 if request.cookies.get('schools_analytics') != '1' and request.cookies.get('schools_visit'):
  resp.delete_cookie('schools_visit',path='/')
 if PROD:resp.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
 return resp
@app.get('/healthz')
def health():
 try:
  with conn() as c:c.execute('SELECT 1')
  return {'ok':True,'service':'kenya-schools-platform','time':now()}
 except Exception as e:return {'ok':False},503
@app.get('/')
def home():
 with conn() as c:
  counts={k:c.execute('SELECT COUNT(*) FROM schools WHERE status="published"'+(f' AND category="{cat}"' if cat else '')).fetchone()[0] for k,cat in [('allCount',''),('schoolCount','school'),('collegeCount','college'),('universityCount','university')]}
 # Real-photo profiles form the visual first phase; profiles without photos stay searchable as text entries.
 photo_rows=active_schools("AND cover_path IS NOT NULL AND TRIM(cover_path)<>''")
 photo_featured=photo_rows[:6]
 text_featured=active_schools("AND (cover_path IS NULL OR TRIM(cover_path)='')")[:12]
 vvip=feature_rotation(active_schools("AND promotion_tier='vvip' AND promotion_expires_at>?",[now()]),3)
 return page('home',photo_featured=photo_featured,text_featured=text_featured,vvip=vvip,counts=counts,counties=COUNTIES)
@app.get('/schools')
def schools():
 fields={k:safe(request.args.get(k),n) for k,n in [('q',120),('county',80),('ownership',40),('level',60),('accommodation',40),('category',30),('gender',40),('town',80),('curriculum',100)]}
 cond=[]; vals=[]; q=fields['q']
 if q:cond.append('(name LIKE ? OR description LIKE ? OR town LIKE ? OR county LIKE ? OR ownership LIKE ? OR levels LIKE ? OR accommodation LIKE ? OR curriculum LIKE ?)'); vals += [f'%{q}%']*8
 for k in ('county','ownership','category','gender'):
  if fields[k]:cond.append(k+'=?'); vals.append(fields[k])
 for k in ('level','accommodation','town','curriculum'):
  if fields[k]:cond.append(k+' LIKE ?'); vals.append('%'+fields[k]+'%')
 results=active_schools(('AND '+' AND '.join(cond)) if cond else '',vals)
 ctx={'schools':results,'filters':fields,'title':'Explore institutions','intro':'Search schools, colleges and universities across Kenya.','counties':COUNTIES}
 out=page('directory',**ctx); return out
@app.get('/directory/<category>')
def directory(category):
 category=category if category in ('school','college','university') else 'school'; label={'school':'Schools','college':'Colleges & TVET institutions','university':'Universities'}[category]
 fields={'category':category,'q':'','county':safe(request.args.get('county'),80),'ownership':safe(request.args.get('ownership'),40),'level':safe(request.args.get('level'),60),'accommodation':safe(request.args.get('accommodation'),40),'gender':'','town':'','curriculum':''}
 cond=['AND category=?']; vals=[category]
 for k in ('ownership','county'):
  if fields[k]:cond.append('AND '+k+'=?'); vals.append(fields[k])
 for k in ('level','accommodation'):
  if fields[k]:cond.append('AND '+k+' LIKE ?'); vals.append('%'+fields[k]+'%')
 return page('directory',schools=active_schools(' '.join(cond),vals),filters=fields,title=f"{fields['ownership']+' ' if fields['ownership'] else ''}{label}{' in '+fields['county'] if fields['county'] else ''}",intro=f"Discover {label.lower()} and explore institution profiles across {fields['county'] or 'Kenya'}.",counties=COUNTIES)
@app.get('/<schoolKind>-schools-in-<county>')
def county_kind(schoolKind,county):
 if schoolKind not in ('private','public','boarding'):return error_page('Page not found','The requested education category was not found.',404)
 county=next((x for x in COUNTIES if slugify(x)==county),county.replace('-',' ').title()); cond=['AND category=?','AND lower(county)=lower(?)']; vals=['school',county]
 if schoolKind in ('private','public'):cond.append('AND ownership=?'); vals.append(schoolKind.title())
 else:cond.append('AND accommodation LIKE ?'); vals.append('%Boarding%')
 label={'private':'Private schools','public':'Public schools','boarding':'Boarding schools'}[schoolKind]
 f={'category':'school','q':'','county':county,'ownership':schoolKind.title() if schoolKind!='boarding' else '', 'level':'','accommodation':'Boarding' if schoolKind=='boarding' else '','gender':'','town':'','curriculum':''}
 return page('directory',schools=active_schools(' '.join(cond),vals),filters=f,title=f'{label} in {county}',intro=f'Explore {label.lower()} in {county}, Kenya.',counties=COUNTIES)
@app.get('/schools-in-<county>')
def county_all(county):
 county=next((x for x in COUNTIES if slugify(x)==county),county.replace('-',' ').title()); results=active_schools('AND lower(county)=lower(?)',[county]); f={'category':'','q':'','county':county,'ownership':'','level':'','accommodation':'','gender':'','town':'','curriculum':''}
 return page('directory',schools=results,filters=f,title=f'Institutions in {county}',intro=f'Explore education options in {county}, Kenya.',counties=COUNTIES)
@app.get('/school/<slug>')
def school_profile(slug):
 t=now()
 with conn() as c:
  row=c.execute("SELECT *,CASE WHEN promotion_tier<>'none' AND promotion_expires_at>? THEN promotion_tier ELSE 'none' END AS active_promotion_tier, COALESCE((SELECT ROUND(AVG(r.rating),1) FROM institution_reviews r WHERE r.school_id=schools.id AND r.status='approved'),0) AS average_rating, (SELECT COUNT(*) FROM institution_reviews r WHERE r.school_id=schools.id AND r.status='approved') AS review_count FROM schools WHERE slug=?",(t,slug)).fetchone()
  if not row or row['status']!='published' or (not row['is_seeded'] and row['expires_at'] and row['expires_at']<=t):abort(404)
  c.execute('UPDATE schools SET views=views+1 WHERE id=?',(row['id'],)); school=dict(row)
  public_reviews=[dict(x) for x in c.execute("SELECT reviewer_name,relationship,rating,review_text,created_at FROM institution_reviews WHERE school_id=? AND status='approved' ORDER BY created_at DESC LIMIT 20",(row['id'],)).fetchall()]
 related=active_schools('AND id<>? AND (county=? OR category=?)',[school['id'],school['county'],school['category']])[:4]
 try:photos=json.loads(school.get('photos_json') or '[]')
 except:photos=[]
 if not photos and school.get('cover_path'):photos=[school['cover_path']]
 ctx=base_context(); ctx.update(metaTitle=f"{school['name']} | {school['town'] or school['county']} | Kenya Schools",metaDescription=safe(school.get('description') or f"Explore {school['name']}, including its location, school information and contact details.",160),canonical=current_site()+'/school/'+slug,school=school,related=related,photos=photos,publicReviews=public_reviews,enquirySent=request.args.get('enquiry')=='sent',reviewSent=request.args.get('review')=='submitted',structured_data={'@context':'https://schema.org','@type':'CollegeOrUniversity' if school['category']=='university' else ('EducationalOrganization' if school['category']=='college' else 'School'),'name':school['name'],'url':current_site()+'/school/'+slug,'description':school.get('description'),'address':{'@type':'PostalAddress','addressLocality':school.get('town'),'addressRegion':school.get('county'),'addressCountry':'KE'},'telephone':school.get('phone'),'email':school.get('email'),'sameAs':[school['website']] if school.get('website') else [],'image':(school.get('cover_path') if str(school.get('cover_path') or '').startswith(('http://','https://')) else current_site()+(school.get('cover_path') or '')) or HERO_PHOTO['url']})
 return render_template('school.html',**ctx)
@app.post('/school/<slug>/enquiry')
@limiter.limit('8 per hour')
def enquiry(slug):
 with conn() as c:school=c.execute("SELECT id,slug FROM schools WHERE slug=? AND status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?)",(slug,now())).fetchone()
 if not school:abort(404)
 name=safe(request.form.get('name'),120); msg=safe(request.form.get('message'),2000)
 if not name or len(msg)<10:return error_page('Please complete the enquiry','Enter your name and a message of at least 10 characters.')
 with conn() as c:c.execute('INSERT INTO enquiries(school_id,name,email,phone,message,created_at) VALUES(?,?,?,?,?,?)',(school['id'],name,safe(request.form.get('email'),160),safe(request.form.get('phone'),60),msg,now()))
 audit('parent_enquiry_received','school',school['id'],name); return redirect(f"/school/{slug}?enquiry=sent")
@app.post('/school/<slug>/review')
@limiter.limit('3 per hour')
def submit_review(slug):
 with conn() as c:
  school=c.execute("SELECT id,slug FROM schools WHERE slug=? AND status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?)",(slug,now())).fetchone()
 if not school:abort(404)
 # A hidden honeypot field catches basic automated spam without collecting extra personal data.
 if safe(request.form.get('website_url'),200):return redirect('/school/'+slug+'?review=submitted#reviews')
 name=safe(request.form.get('reviewer_name'),100)
 relationship=safe(request.form.get('relationship'),40)
 try: rating=int(request.form.get('rating','0'))
 except (TypeError,ValueError): rating=0
 message=safe(request.form.get('review_text'),1200)
 allowed_relationships=('Parent / guardian','Current student','Former student','Staff member','Other')
 if not name or relationship not in allowed_relationships or rating not in (1,2,3,4,5) or len(message)<20:
  return error_page('Please check your review','Enter your name, choose how you know the institution, select a 1–5 rating and write at least 20 characters.')
 with conn() as c:
  c.execute('INSERT INTO institution_reviews(school_id,reviewer_name,relationship,rating,review_text,status,created_at) VALUES(?,?,?,?,?,?,?)',(school['id'],name,relationship,rating,message,'pending',now()))
 audit('institution_review_submitted','review',None,f"Review submitted for school {school['id']}; awaiting moderation")
 return redirect('/school/'+slug+'?review=submitted#reviews')

@app.get('/r/<code>')
def referral_redirect(code):
 code=safe(code,24).upper()
 with conn() as c:partner=c.execute("SELECT code FROM referral_partners WHERE code=? AND status='active'",(code,)).fetchone()
 if not partner:return redirect('/invite-and-earn?invalid=1')
 response=redirect('/advertise')
 response.set_cookie('schools_referral',referral_serializer.dumps(code),max_age=30*24*60*60,httponly=True,samesite='Lax',secure=PROD,path='/')
 return response

@app.route('/invite-and-earn',methods=['GET','POST'])
@limiter.limit('5 per hour',methods=['POST'])
def invite_and_earn():
 if request.method=='GET':
  return page('invite',registered=False,invalid=request.args.get('invalid')=='1',metaTitle='Invite & Earn KES 1,000 | Kenya Schools',metaDescription='Refer a new school to Kenya Schools and earn a KES 1,000 reward when it completes its first eligible paid advert.')
 if safe(request.form.get('website_url'),150):return redirect('/invite-and-earn?registered=1')
 name=safe(request.form.get('full_name'),120); phone=safe(request.form.get('phone'),50); email=safe(request.form.get('email'),160)
 digits=normalise_contact(phone)
 if len(digits)==9:phone='+254'+digits
 if not name or len(digits)!=9 or digits[0] not in ('1','7'):
  return page('invite',registered=False,error='Enter your name and a valid mobile number.',metaTitle='Invite & Earn KES 1,000 | Kenya Schools',metaDescription='Join the Kenya Schools referral programme.')
 if request.form.get('accept_terms')!='1':
  return page('invite',registered=False,error='Please read and accept the referral programme terms to continue.',metaTitle='Invite & Earn KES 1,000 | Kenya Schools',metaDescription='Join the Kenya Schools referral programme.')
 code=secrets.token_hex(6).upper(); token=secrets.token_urlsafe(32); token_hash=sha256(token.encode()).hexdigest()
 try:
  with conn() as c:
   prior=c.execute('SELECT phone FROM referral_partners').fetchall()
   if any(normalise_contact(row['phone'])==digits for row in prior):raise sqlite3.IntegrityError('phone already registered')
   c.execute('INSERT INTO referral_partners(full_name,phone,email,code,dashboard_token_hash,status,created_at) VALUES(?,?,?,?,?,?,?)',(name,phone,email,code,token_hash,'active',now()))
 except sqlite3.IntegrityError:
  return page('invite',registered=False,error='A referral profile already exists for this phone number. Use its saved private dashboard link, or contact the Kenya Schools team for help recovering access.',metaTitle='Invite & Earn KES 1,000 | Kenya Schools',metaDescription='Join the Kenya Schools referral programme.')
 audit('referral_partner_registered','referrer',None,f'{name} registered a referral profile')
 dashboard_url=current_site()+'/invite/dashboard/'+token
 return page('invite',registered=True,referralLink=current_site()+'/r/'+code,dashboardUrl=dashboard_url,metaTitle='Your Kenya Schools Invite Link',metaDescription='Your referral profile is ready. Save your private dashboard link.')

@app.get('/invite/dashboard/<token>')
def invite_dashboard(token):
 token=safe(token,100)
 if len(token)<32:abort(404)
 token_hash=sha256(token.encode()).hexdigest()
 with conn() as c:
  partner=c.execute("SELECT * FROM referral_partners WHERE dashboard_token_hash=?",(token_hash,)).fetchone()
  if not partner:abort(404)
  partner=dict(partner)
  c.execute("UPDATE referral_rewards SET status='payable' WHERE status='pending_clearance' AND available_at<=?",(now(),))
  referrals=[dict(x) for x in c.execute("SELECT sr.status,sr.created_at,sr.converted_at,s.name AS school_name,COALESCE(rr.status,'not_earned') AS reward_status,COALESCE(rr.amount_kes,0) AS reward_amount,rr.available_at,rr.paid_at FROM school_referrals sr JOIN schools s ON s.id=sr.school_id LEFT JOIN referral_rewards rr ON rr.referral_id=sr.id WHERE sr.referrer_id=? ORDER BY sr.id DESC LIMIT 100",(partner['id'],)).fetchall()]
 summary=referral_reward_summary(partner['id'])
 return page('invite-dashboard',partner=partner,summary=summary,referrals=referrals,referralLink=current_site()+'/r/'+partner['code'],metaTitle='Your Referral Dashboard | Kenya Schools',metaDescription='Track your Kenya Schools referrals and rewards.',robots='noindex,nofollow',canonical=current_site()+'/invite-and-earn')

@app.get('/advertise')
def advertise():
 tier=request.args.get('tier','none')
 tier=tier if tier in ('none','vip','vvip') else 'none'
 try: days=int(request.args.get('days','30'))
 except (TypeError,ValueError): days=30
 days=days if days in PROMOTION_DURATIONS else 30
 return page('advertise',sent=request.args.get('sent')=='1',referralApplied=bool(current_referral_partner()),
  packagePrices=PROMOTION_PRICES,selectedTier=tier,selectedDuration=days,
  submittedPrice=promotion_price(tier,days) if tier!='none' and request.args.get('sent')=='1' else None)
@app.post('/advertise')
@limiter.limit('8 per hour')
def advertise_post():
 if safe(request.form.get('website_confirm'),150):return redirect('/advertise?sent=1')
 name=safe(request.form.get('name'),160)
 owner_name=safe(request.form.get('contact_name'),120); owner_phone=safe(request.form.get('phone'),60)
 if not name:return error_page('School name required','Please enter the institution name and submit again.')
 if not owner_name or not owner_phone:return error_page('Contact details required','Enter the account holder name and phone number so the submission can be linked to a customer record.')
 photos=[]; files=request.files.getlist('photos')
 if len(files)>6:return error_page('Too many photos','Please upload no more than six photos.')
 for f in files:
  if not f.filename:continue
  ext=Path(secure_filename(f.filename)).suffix.lower()
  allowed_mimes={'image/jpeg':('.jpg','.jpeg'),'image/png':('.png',),'image/webp':('.webp',)}
  if f.mimetype not in allowed_mimes or ext not in allowed_mimes.get(f.mimetype,()):return error_page('Unsupported image','Please upload JPG, PNG or WebP images only.')
  f.seek(0,2); size=f.tell(); f.seek(0)
  if size>8*1024*1024:return error_page('Image too large','Each photo must be 8MB or smaller.')
  fn=f"{int(time.time()*1000)}-{secrets.token_hex(5)}{ext}"; f.save(UPLOAD/fn); photos.append('/uploads/'+fn)
 with conn() as c:account_rows=c.execute('SELECT id,phone FROM customer_accounts').fetchall()
 existing_account=next((row for row in account_rows if normalise_contact(row['phone'])==normalise_contact(owner_phone)),None)
 account_id=existing_account['id'] if existing_account else get_or_create_customer(owner_name,owner_phone,request.form.get('email',''))
 slug=slugify(name)+'-'+secrets.token_hex(2); tier=request.form.get('requested_tier','none'); tier=tier if tier in ('none','vip','vvip') else 'none'
 try: duration_days=int(request.form.get('promotion_duration_days','30'))
 except (TypeError,ValueError): duration_days=30
 duration_days=duration_days if duration_days in PROMOTION_DURATIONS else 30
 package_amount=promotion_price(tier,duration_days) if tier!='none' else 0
 t=now()
 vals=[name,slug,safe(request.form.get('category'),30) or 'school',safe(request.form.get('ownership'),40),safe(request.form.get('levels'),150),safe(request.form.get('county'),80),safe(request.form.get('town'),80),safe(request.form.get('accommodation'),40),safe(request.form.get('gender'),40),safe(request.form.get('curriculum'),100),safe(request.form.get('fees_range'),100),safe(request.form.get('address'),250),safe(request.form.get('phone'),60),safe(request.form.get('email'),160),safe_url(request.form.get('website')),safe(request.form.get('description'),2500),photos[0] if photos else '',json.dumps(photos),safe_url(request.form.get('video_url')),tier,duration_days,t,t,account_id]
 partner=current_referral_partner(); referral_id=None
 # Only a genuinely new customer account can be attributed. Self-referrals are excluded.
 self_referral=bool(partner and (normalise_contact(partner['phone'])==normalise_contact(owner_phone) or (partner['email'] and partner['email'].lower()==safe(request.form.get('email'),160).lower())))
 with conn() as c:
  cur=c.execute("INSERT INTO schools(name,slug,category,ownership,levels,county,town,accommodation,gender,curriculum,fees_range,address,phone,email,website,description,cover_path,photos_json,video_url,trust_status,promotion_tier,requested_tier,requested_duration_days,status,source_note,is_seeded,created_at,updated_at,owner_account_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'unverified','none',?,?,'pending','',0,?,?,?)",vals)
  school_id=cur.lastrowid
  prior_same_partner_account=False
  if partner and existing_account:
   prior_same_partner_account=bool(c.execute('SELECT id FROM school_referrals WHERE account_id=? AND referrer_id=? LIMIT 1',(account_id,partner['id'])).fetchone())
  # A contact that was created by this same partner's first referral may submit
  # another distinct institution. Existing accounts from before the programme
  # are not eligible, and a contact can never be attributed to a second partner.
  if partner and (not existing_account or prior_same_partner_account) and not self_referral:
   duplicate=c.execute("SELECT id FROM schools WHERE id<>? AND lower(name)=lower(?) AND lower(county)=lower(?) AND status IN ('published','pending') LIMIT 1",(school_id,name,safe(request.form.get('county'),80))).fetchone()
   if not duplicate:
    # account_id is unique in this anti-abuse table. Link the first institution;
    # further distinct schools from the same referred customer use NULL here.
    prior_account_referral=c.execute('SELECT id FROM school_referrals WHERE account_id=? LIMIT 1',(account_id,)).fetchone()
    referral_account_id=None if prior_account_referral else account_id
    cur_ref=c.execute('INSERT INTO school_referrals(referrer_id,school_id,account_id,referral_code,status,created_at) VALUES(?,?,?,?,?,?)',(partner['id'],school_id,referral_account_id,partner['code'],'registered',now()))
    referral_id=cur_ref.lastrowid
  if tier in ('vip','vvip'):
   package_label=f'{tier.upper()} · {duration_days} days · KES {package_amount:,}'
   c.execute('INSERT INTO payment_records(account_id,school_id,referral_id,purpose,tier,duration_days,amount,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
    (account_id,school_id,referral_id,'Institution promotion',tier,duration_days,str(package_amount),'awaiting_payment',
     f'{package_label}. Confirm the exact payment and M-PESA reference. Promotion activates after payment is confirmed and the institution profile is published.',now()))
 audit('school_submitted','school',school_id,name)
 response=redirect(f'/advertise?sent=1&tier={tier}&days={duration_days}')
 response.delete_cookie('schools_referral',path='/')
 return response
@app.get('/school-portal')
def portal():return page('portal',sent=request.args.get('sent')=='1')
@app.post('/school-portal')
@limiter.limit('8 per hour')
def portal_post():
 name=safe(request.form.get('contact_name'),120); inst=safe(request.form.get('institution'),160); phone=safe(request.form.get('phone'),60)
 if not name or not inst or not phone:return error_page('Please complete the request','Enter your name, institution and phone number so we can follow up.')
 with conn() as c:c.execute('INSERT INTO portal_enquiries(contact_name,institution,phone,email,message,created_at) VALUES(?,?,?,?,?,?)',(name,inst,phone,safe(request.form.get('email'),160),safe(request.form.get('message'),1500),now()))
 audit('school_portal_enquiry_received','portal',None,inst); return redirect('/school-portal?sent=1')
@app.get('/campus-living')
def campus():
 with conn() as c:props=[dict(x) for x in c.execute("SELECT * FROM properties WHERE status='published' ORDER BY created_at DESC LIMIT 30").fetchall()]
 return page('campus',properties=props,sent=request.args.get('sent')=='1')
@app.post('/campus-living')
@limiter.limit('8 per hour')
def campus_post():
 if safe(request.form.get('website_confirm'),150):return redirect('/campus-living?sent=1')
 title=safe(request.form.get('title'),160)
 if not title:return error_page('Listing title required','Please enter a title for the accommodation listing.')
 contact_name=safe(request.form.get('contact_name'),120)
 if not contact_name or not safe(request.form.get('contact'),60):return error_page('Contact details required','Enter the advertiser name and phone number so this listing can be linked to a customer record.')
 account_id=get_or_create_customer(contact_name,request.form.get('contact'),request.form.get('email',''))
 vals=[title,safe(request.form.get('property_type'),80),safe(request.form.get('institution'),160),safe(request.form.get('county'),80),safe(request.form.get('town'),80),safe(request.form.get('price'),80),safe(request.form.get('contact'),80),safe(request.form.get('description'),1500),'pending',now(),account_id]
 with conn() as c:c.execute('INSERT INTO properties(title,property_type,institution,county,town,price,contact,description,status,created_at,owner_account_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',vals)
 audit('property_submitted','property',None,title); return redirect('/campus-living?sent=1')
@app.get('/about')
def about():return page('about')
@app.get('/help')
def help_centre():return page('help',metaTitle='Help Centre | Kenya Schools',metaDescription='Simple guidance for searching institutions, understanding profiles, submitting reviews and contacting Kenya Schools.')
@app.get('/contact')
def contact():return page('contact',sent=request.args.get('sent')=='1')
@app.post('/contact')
@limiter.limit('8 per hour')
def contact_post():
 if safe(request.form.get('website_confirm'),150):return redirect('/contact?sent=1')
 name=safe(request.form.get('name'),120); message=safe(request.form.get('message'),2500)
 if not name or len(message)<8:return error_page('Complete your message','Enter your name and a message of at least 8 characters.')
 with conn() as c:c.execute('INSERT INTO contact_messages(name,email,phone,subject,message,status,created_at) VALUES(?,?,?,?,?,?,?)',(name,safe(request.form.get('email'),160),safe(request.form.get('phone'),60),safe(request.form.get('subject'),160),message,'new',now()))
 audit('contact_message_received','contact',None,name)
 return redirect('/contact?sent=1')
@app.get('/privacy')
def privacy():return page('privacy')
@app.get('/admin/login')
def admin_login():
 if session.get('admin'):return redirect('/admin')
 session['csrfToken']=secrets.token_hex(32); response=page('admin-login',error=''); return response
@app.post('/admin/login')
@limiter.limit('8 per 15 minutes')
def admin_login_post():
 username=safe(request.form.get('username'),120); password=request.form.get('password','')
 valid_user=hmac.compare_digest(username.encode(),ADMIN_USERNAME.encode())
 valid_pw=bcrypt.checkpw(password.encode(),ADMIN_PASSWORD_HASH) if ADMIN_PASSWORD_HASH and password else (not PROD and password=='admin12345')
 if not(valid_user and valid_pw):audit('admin_login_failed','admin',None,username); return page('admin-login',error='Those login details did not match.'),401
 session.clear()
 try: app.session_interface.regenerate(session)
 except Exception: pass
 session['admin']=True; session['adminUsername']=username; session['csrfToken']=secrets.token_hex(32); session.permanent=True; audit('admin_login','admin',None,username); return redirect('/admin')
@app.post('/admin/logout')
def admin_logout():
 r=admin_guard()
 if r:return r
 session.clear(); return redirect('/admin/login')
@app.get('/admin')
def admin_dashboard():
 r=admin_required()
 if r:return r
 with conn() as c:
  schools=[dict(x) for x in c.execute("SELECT * FROM schools ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'expired' THEN 1 ELSE 2 END,created_at DESC LIMIT 100").fetchall()]
  props=[dict(x) for x in c.execute("SELECT * FROM properties ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,created_at DESC LIMIT 30").fetchall()]
  errors=[dict(x) for x in c.execute('SELECT * FROM admin_errors ORDER BY id DESC LIMIT 12').fetchall()]
  enquiries=[dict(x) for x in c.execute('SELECT e.*,s.name AS school_name FROM enquiries e LEFT JOIN schools s ON s.id=e.school_id ORDER BY e.id DESC LIMIT 20').fetchall()]
  portals=[dict(x) for x in c.execute('SELECT * FROM portal_enquiries ORDER BY id DESC LIMIT 20').fetchall()]
  messages=[dict(x) for x in c.execute('SELECT * FROM contact_messages ORDER BY id DESC LIMIT 30').fetchall()]
  reviews=[dict(x) for x in c.execute("SELECT r.*,s.name AS school_name,s.slug AS school_slug FROM institution_reviews r JOIN schools s ON s.id=r.school_id ORDER BY CASE r.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,r.created_at DESC LIMIT 80").fetchall()]
  stats={k:c.execute(sql).fetchone()[0] for k,sql in [('schools',"SELECT COUNT(*) FROM schools WHERE status='published'"),('pending',"SELECT COUNT(*) FROM schools WHERE status='pending'"),('expired',"SELECT COUNT(*) FROM schools WHERE status='expired'"),('properties',"SELECT COUNT(*) FROM properties WHERE status='pending'"),('enquiries','SELECT COUNT(*) FROM enquiries'),('reviews_pending',"SELECT COUNT(*) FROM institution_reviews WHERE status='pending'"),('reviews_approved',"SELECT COUNT(*) FROM institution_reviews WHERE status='approved'"),('reviews_total',"SELECT COUNT(*) FROM institution_reviews"),('visitors_today',"SELECT COUNT(DISTINCT visitor_key) FROM visitor_events WHERE date(created_at)=date('now')"),('visits_today',"SELECT COUNT(*) FROM visitor_events WHERE date(created_at)=date('now')"),('visitors_total',"SELECT COUNT(DISTINCT visitor_key) FROM visitor_events"),('accounts','SELECT COUNT(*) FROM customer_accounts')]}
  settings={r['key']:r['value'] for r in c.execute('SELECT key,value FROM site_settings')}
  visitor_paths=[dict(x) for x in c.execute("SELECT path,COUNT(*) AS hits,COUNT(DISTINCT visitor_key) AS visitors FROM visitor_events WHERE created_at>=? GROUP BY path ORDER BY hits DESC LIMIT 12",((datetime.now(timezone.utc)-timedelta(days=7)).isoformat(),)).fetchall()]
  visitor_days=[dict(x) for x in c.execute("SELECT date(created_at) AS day,COUNT(DISTINCT visitor_key) AS visitors,COUNT(*) AS views FROM visitor_events WHERE created_at>=? GROUP BY date(created_at) ORDER BY day DESC LIMIT 14",((datetime.now(timezone.utc)-timedelta(days=14)).isoformat(),)).fetchall()]
  accounts=[dict(x) for x in c.execute('SELECT * FROM customer_accounts ORDER BY id DESC LIMIT 30').fetchall()]
  payments=[dict(x) for x in c.execute("SELECT p.*,a.full_name,a.phone,a.email,s.name AS school_name FROM payment_records p LEFT JOIN customer_accounts a ON a.id=p.account_id LEFT JOIN schools s ON s.id=p.school_id ORDER BY p.id DESC LIMIT 40").fetchall()]
  c.execute("UPDATE referral_rewards SET status='payable' WHERE status='pending_clearance' AND available_at<=?",(now(),))
  referrers=[dict(x) for x in c.execute("SELECT rp.*,COUNT(DISTINCT sr.id) AS referral_count,COUNT(DISTINCT CASE WHEN sr.status='converted' THEN sr.id END) AS converted_count,COALESCE(SUM(CASE WHEN rr.status IN ('pending_clearance','payable') THEN rr.amount_kes ELSE 0 END),0) AS unpaid_kes,COALESCE(SUM(CASE WHEN rr.status='paid' THEN rr.amount_kes ELSE 0 END),0) AS paid_kes FROM referral_partners rp LEFT JOIN school_referrals sr ON sr.referrer_id=rp.id LEFT JOIN referral_rewards rr ON rr.referral_id=sr.id GROUP BY rp.id ORDER BY rp.id DESC LIMIT 100").fetchall()]
  referral_items=[dict(x) for x in c.execute("SELECT rr.*,rp.full_name AS referrer_name,rp.phone AS referrer_phone,s.name AS school_name,p.amount AS advert_amount,p.reference AS advert_reference FROM referral_rewards rr JOIN school_referrals sr ON sr.id=rr.referral_id JOIN referral_partners rp ON rp.id=sr.referrer_id JOIN schools s ON s.id=sr.school_id JOIN payment_records p ON p.id=rr.payment_record_id ORDER BY rr.id DESC LIMIT 100").fetchall()]
  unconverted_referrals=[dict(x) for x in c.execute("SELECT sr.id,sr.created_at,rp.full_name AS referrer_name,rp.phone AS referrer_phone,s.name AS school_name,s.county FROM school_referrals sr JOIN referral_partners rp ON rp.id=sr.referrer_id JOIN schools s ON s.id=sr.school_id WHERE sr.status='registered' AND NOT EXISTS (SELECT 1 FROM payment_records p WHERE p.referral_id=sr.id AND p.purpose='Institution promotion' AND p.status NOT IN ('rejected','refunded')) ORDER BY sr.id DESC LIMIT 100").fetchall()]
  referral_stats={'partners':c.execute('SELECT COUNT(*) FROM referral_partners').fetchone()[0],'referrals':c.execute('SELECT COUNT(*) FROM school_referrals').fetchone()[0],'converted':c.execute("SELECT COUNT(*) FROM school_referrals WHERE status='converted'").fetchone()[0],'pending_kes':c.execute("SELECT COALESCE(SUM(amount_kes),0) FROM referral_rewards WHERE status IN ('pending_clearance','payable')").fetchone()[0],'paid_kes':c.execute("SELECT COALESCE(SUM(amount_kes),0) FROM referral_rewards WHERE status='paid'").fetchone()[0]}

 ctx=base_context(); ctx.update(robots='noindex,nofollow',metaTitle='Admin Dashboard | Kenya Schools',schools=schools,properties=props,errors=errors,enquiries=enquiries,portalEnquiries=portals,contactMessages=messages,reviews=reviews,stats=stats,settings=settings,visitorPaths=visitor_paths,visitorDays=visitor_days,payments=payments,accounts=accounts,referrers=referrers,referralItems=referral_items,unconvertedReferrals=unconverted_referrals,referralStats=referral_stats); return render_template('admin-dashboard.html',**ctx)
def admin_action(sql,args,action,typ,rid,detail=''):
 r=admin_guard()
 if r:return r
 with conn() as c:c.execute(sql,args)
 audit(action,typ,rid,detail); return redirect('/admin')
@app.post('/admin/schools/<int:rid>/edit')
def school_edit(rid):
 r=admin_guard()
 if r:return r
 name=safe(request.form.get('name'),180)
 if not name:return error_page('Institution name required','Enter an institution name before saving.')
 fields={
  'name':name,'category':safe(request.form.get('category'),30) or 'school',
  'ownership':safe(request.form.get('ownership'),40),'levels':safe(request.form.get('levels'),250),
  'county':safe(request.form.get('county'),80),'town':safe(request.form.get('town'),100),
  'accommodation':safe(request.form.get('accommodation'),60),'gender':safe(request.form.get('gender'),40),
  'curriculum':safe(request.form.get('curriculum'),150),'fees_range':safe(request.form.get('fees_range'),120),
  'address':safe(request.form.get('address'),300),'phone':safe(request.form.get('phone'),60),
  'email':safe(request.form.get('email'),160),'website':safe_url(request.form.get('website')),
  'description':safe(request.form.get('description'),3000),'video_url':safe_url(request.form.get('video_url'))
 }
 media_updates={}
 for field,column in (('cover_photo','cover_path'),('logo_photo','logo_path')):
  uploaded=request.files.get(field)
  if uploaded and uploaded.filename:
   ext=Path(secure_filename(uploaded.filename)).suffix.lower()
   allowed={'image/jpeg':('.jpg','.jpeg'),'image/png':('.png',),'image/webp':('.webp',)}
   if uploaded.mimetype not in allowed or ext not in allowed[uploaded.mimetype]:
    return error_page('Unsupported image','Upload JPG, PNG or WebP images only.')
   uploaded.seek(0,2); size=uploaded.tell(); uploaded.seek(0)
   if size>8*1024*1024:return error_page('Image too large','Each image must be 8MB or smaller.')
   filename=f"{int(time.time()*1000)}-{secrets.token_hex(5)}{ext}"
   uploaded.save(UPLOAD/filename); media_updates[column]='/uploads/'+filename
 with conn() as c:
  current=c.execute('SELECT photos_json,logo_path,cover_path FROM schools WHERE id=?',(rid,)).fetchone()
  if not current:return error_page('Institution not found','This institution record no longer exists.',404)
  try:photos=json.loads(current['photos_json'] or '[]')
  except Exception:photos=[]
  if media_updates.get('cover_path') and media_updates['cover_path'] not in photos:photos.insert(0,media_updates['cover_path'])
  c.execute('UPDATE schools SET name=:name,category=:category,ownership=:ownership,levels=:levels,county=:county,town=:town,accommodation=:accommodation,gender=:gender,curriculum=:curriculum,fees_range=:fees_range,address=:address,phone=:phone,email=:email,website=:website,description=:description,video_url=:video_url,logo_path=:logo_path,cover_path=:cover_path,photos_json=:photos_json,updated_at=:updated_at WHERE id=:id',
   {**fields,'logo_path':media_updates.get('logo_path') or current['logo_path'],'cover_path':media_updates.get('cover_path') or current['cover_path'],'photos_json':json.dumps(photos),'updated_at':now(),'id':rid})
 audit('institution_profile_edited','school',rid,name)
 return redirect('/admin#institutions')

def sync_paid_promotion(c, school_id):
 school=c.execute('SELECT status FROM schools WHERE id=?',(school_id,)).fetchone()
 if not school or school['status']!='published': return
 payment=c.execute("SELECT tier,duration_days,paid_at,created_at FROM payment_records WHERE school_id=? AND purpose='Institution promotion' AND status='paid' AND tier IN ('vip','vvip') ORDER BY COALESCE(NULLIF(paid_at,''),created_at) DESC,id DESC LIMIT 1",(school_id,)).fetchone()
 if not payment:
  c.execute("UPDATE schools SET promotion_tier='none',promotion_expires_at='',updated_at=? WHERE id=?",(now(),school_id)); return
 try: days=int(payment['duration_days'] or 30)
 except (TypeError,ValueError): days=30
 if days not in PROMOTION_DURATIONS: days=30
 start_value=payment['paid_at'] or payment['created_at']
 try: start=datetime.fromisoformat(start_value)
 except (TypeError,ValueError): start=datetime.now(timezone.utc)
 if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
 expires=(start+timedelta(days=days)).astimezone(timezone.utc)
 if expires<=datetime.now(timezone.utc):
  c.execute("UPDATE schools SET promotion_tier='none',promotion_expires_at='',updated_at=? WHERE id=?",(now(),school_id)); return
 c.execute('UPDATE schools SET promotion_tier=?,promotion_expires_at=?,last_featured_at=?,updated_at=? WHERE id=?',
  (payment['tier'],expires.isoformat(),now(),now(),school_id))

@app.post('/admin/schools/<int:rid>/approve')
def school_approve(rid):
 r=admin_guard()
 if r:return r
 t=now(); exp=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
 with conn() as c:
  cur=c.execute("UPDATE schools SET status='published',posted_at=?,expires_at=?,last_renewed_at=?,updated_at=? WHERE id=?",(t,exp,t,t,rid))
  if not cur.rowcount:abort(404)
  sync_paid_promotion(c,rid)
 audit('school_approved','school',rid,'Published for 30 days; any paid promotion activated for its selected duration')
 return redirect('/admin#institutions')
@app.post('/admin/schools/<int:rid>/renew')
def school_renew(rid):
 t=now(); exp=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(); return admin_action("UPDATE schools SET status='published',expires_at=?,last_renewed_at=?,updated_at=? WHERE id=?",(exp,t,t,rid),'school_renewed','school',rid,'Renewed for 30 days')
@app.post('/admin/schools/<int:rid>/promotion')
def school_promotion(rid):
 tier=request.form.get('promotion_tier','none'); tier=tier if tier in ('none','vip','vvip') else 'none'; days=int(request.form.get('duration_days',30)); days=days if days in (30,60,90) else 30; t=now(); exp=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat() if tier!='none' else ''
 return admin_action('UPDATE schools SET promotion_tier=?,promotion_expires_at=?,last_featured_at=?,updated_at=? WHERE id=?',(tier,exp,'',t,rid),'promotion_changed','school',rid,f'{tier} for {days if tier!="none" else 0} days')
@app.post('/admin/schools/<int:rid>/trust')
def school_trust(rid):
 trust=request.form.get('trust_status','unverified'); trust=trust if trust in ('unverified','recognised','official') else 'unverified'; return admin_action('UPDATE schools SET trust_status=?,updated_at=? WHERE id=?',(trust,now(),rid),'trust_status_changed','school',rid,trust)
@app.post('/admin/reviews/<int:rid>/approve')
def review_approve(rid):
 r=admin_guard()
 if r:return r
 with conn() as c:
  cur=c.execute("UPDATE institution_reviews SET status='approved',moderated_at=? WHERE id=?",(now(),rid))
  if cur.rowcount==0:abort(404)
 audit('institution_review_approved','review',rid,'Review approved for public display')
 return redirect('/admin#reviews')

@app.post('/admin/reviews/<int:rid>/reject')
def review_reject(rid):
 r=admin_guard()
 if r:return r
 with conn() as c:
  cur=c.execute("UPDATE institution_reviews SET status='rejected',moderated_at=? WHERE id=?",(now(),rid))
  if cur.rowcount==0:abort(404)
 audit('institution_review_rejected','review',rid,'Review rejected; not shown publicly')
 return redirect('/admin#reviews')

@app.post('/admin/properties/<int:rid>/approve')
def property_approve(rid):return admin_action("UPDATE properties SET status='published' WHERE id=?",(rid,),'property_approved','property',rid)
@app.post('/admin/properties/<int:rid>/hide')
def property_hide(rid):return admin_action("UPDATE properties SET status='hidden' WHERE id=?",(rid,),'property_hidden','property',rid)
@app.post('/admin/backup')
def backup_download():
 r=admin_guard()
 if r:return r
 try:
  dest=create_backup(); audit('database_backup_created','database',None,dest.name); return send_file(dest,as_attachment=True)
 except Exception as e:log_error(e,'/admin/backup'); return error_page('Backup failed','The database backup could not be created. The error has been recorded in the admin error log.',500)
@app.post('/admin/settings')
def admin_settings_save():
 r=admin_guard()
 if r:return r
 allowed=('business_name','contact_email','contact_phone','whatsapp','mpesa_paybill','mpesa_till','mpesa_account','payment_instructions','public_address')
 with conn() as c:
  for key in allowed:
   c.execute('INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,safe(request.form.get(key),1500)))
 audit('site_settings_updated','settings',None,'Public contact and payment details updated')
 return redirect('/admin#settings')

@app.post('/admin/backup/json')
def backup_json_download():
 r=admin_guard()
 if r:return r
 try:
  from base64 import b64encode
  db=BACKUP/f'export-{secrets.token_hex(5)}.sqlite'
  with conn() as c:
   target=sqlite3.connect(db); c.backup(target); target.close()
  payload={'format':'kenya-schools-backup','version':1,'created_at':now(),'database_base64':b64encode(db.read_bytes()).decode(),'uploads':{}}
  included=0
  for f in UPLOAD.iterdir():
   if f.is_file() and f.stat().st_size<12*1024*1024 and included+f.stat().st_size<=40*1024*1024:
    payload['uploads'][f.name]=b64encode(f.read_bytes()).decode()
    included+=f.stat().st_size
  payload['uploads_note']='Media files over 12MB each or beyond the 40MB total export allowance are omitted.'
  db.unlink(missing_ok=True)
  data=json.dumps(payload,ensure_ascii=False).encode()
  audit('json_backup_created','database',None,'Database and uploaded media exported')
  return send_file(BytesIO(data),mimetype='application/json',as_attachment=True,download_name='kenya-schools-full-backup.json')
 except Exception as e:
  log_error(e,'/admin/backup/json'); return error_page('Backup failed','The JSON backup could not be created.',500)

@app.post('/admin/restore')
def admin_restore():
 r=admin_guard()
 if r:return r
 uploaded_file=request.files.get('backup_file')
 if not uploaded_file or not uploaded_file.filename:return error_page('Choose a backup','Select a SQLite or JSON backup file first.')
 tmp=DATA/f'restore-{secrets.token_hex(6)}.sqlite'
 try:
  raw=uploaded_file.read()
  if uploaded_file.filename.lower().endswith('.json'):
   from base64 import b64decode
   payload=json.loads(raw.decode('utf-8'))
   if payload.get('format')!='kenya-schools-backup' or payload.get('version')!=1:raise ValueError('Unrecognised backup format')
   tmp.write_bytes(b64decode(payload['database_base64'],validate=True))
   media=payload.get('uploads',{})
  else:
   tmp.write_bytes(raw); media={}
  test=sqlite3.connect(tmp)
  result=test.execute('PRAGMA integrity_check').fetchone()[0]
  required={r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  test.close()
  if result!='ok' or not {'schools','properties','enquiries'}.issubset(required):raise ValueError('Backup is not a valid Kenya Schools database')
  # Preserve a rollback copy before replacing the active database.
  rollback=create_backup()
  os.replace(tmp,DB)
  # Bring older valid backups forward to the current schema without discarding records.
  with conn() as c:
   c.executescript(SCHEMA)
   for table,col,definition in [('schools','photos_json',"TEXT DEFAULT '[]'"),('schools','promotion_expires_at',"TEXT DEFAULT ''"),('schools','requested_tier',"TEXT DEFAULT 'none'"),('schools','requested_duration_days','INTEGER NOT NULL DEFAULT 30'),('schools','owner_account_id',"INTEGER"),('properties','owner_account_id',"INTEGER"),('payment_records','school_id',"INTEGER"),('payment_records','referral_id',"INTEGER"),('payment_records','duration_days','INTEGER NOT NULL DEFAULT 30'),('payment_records','paid_at',"TEXT DEFAULT ''")]:
    cols=[r['name'] for r in c.execute(f'PRAGMA table_info({table})')]
    if col not in cols:c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
   c.execute("""UPDATE payment_records
    SET amount=CASE tier WHEN 'vip' THEN CASE duration_days WHEN 30 THEN '3000' WHEN 60 THEN '5500' WHEN 90 THEN '7500' END WHEN 'vvip' THEN CASE duration_days WHEN 30 THEN '6000' WHEN 60 THEN '11000' WHEN 90 THEN '15000' END ELSE amount END,
     status='awaiting_payment',notes=COALESCE(notes,'') || ' Updated to the published fixed advertising tariff.'
    WHERE purpose='Institution promotion' AND tier IN ('vip','vvip') AND status='awaiting_quote' AND (amount IS NULL OR TRIM(amount)='')""")
  for name,encoded in media.items():
   safe_name=secure_filename(name)
   if safe_name and len(safe_name)<180:
    content=b64decode(encoded,validate=True)
    if len(content)<=12*1024*1024:(UPLOAD/safe_name).write_bytes(content)
  audit('database_restored','database',None,f'Restored from {uploaded_file.filename}; pre-restore copy {rollback.name}')
  return redirect('/admin?restored=1')
 except Exception as e:
  tmp.unlink(missing_ok=True); log_error(e,'/admin/restore')
  return error_page('Restore not completed','The backup was rejected or could not be restored. Your existing database has been kept.',400)

@app.post('/admin/payments/<int:rid>/update')
def admin_payment_update(rid):
 r=admin_guard()
 if r:return r
 status=safe(request.form.get('status'),30)
 if status not in ('awaiting_quote','awaiting_payment','paid','rejected','refunded','awaiting_review'):return error_page('Invalid payment status','Choose a valid payment status.')
 amount=safe(request.form.get('amount'),80); reference=safe(request.form.get('reference'),120); notes=safe(request.form.get('notes'),500)
 if status=='paid':
  try: paid_amount=float(amount.replace(',',''))
  except (TypeError,ValueError):paid_amount=0
  if paid_amount<=0 or not reference:return error_page('Payment confirmation incomplete','To mark a payment as paid, enter the confirmed amount and the M-PESA transaction reference or other verifiable receipt number.')
 with conn() as c:
  payment=c.execute('SELECT * FROM payment_records WHERE id=?',(rid,)).fetchone()
  if not payment:abort(404)
  if status=='paid' and payment['purpose']=='Institution promotion' and payment['tier'] in ('vip','vvip'):
   expected=promotion_price(payment['tier'],payment['duration_days'] or 30)
   if expected is None:
    return error_page('Invalid advert duration','This payment record has an invalid advertising term. Recreate the payment record using 30, 60 or 90 days.')
   if round(paid_amount,2)!=float(expected):
    return error_page('Advert amount does not match the selected package',f"This {payment['tier'].upper()} advert is priced at KES {expected:,.0f} for {int(payment['duration_days'] or 30)} days. Confirm the exact amount received before marking it paid.")
  paid_at=((payment['paid_at'] or now()) if payment['status']=='paid' else now()) if status=='paid' else (payment['paid_at'] or '')
  c.execute('UPDATE payment_records SET status=?,amount=?,reference=?,notes=?,paid_at=? WHERE id=?',(status,amount,reference,notes,paid_at,rid))
  if payment['school_id'] and payment['purpose']=='Institution promotion':
   sync_paid_promotion(c,payment['school_id'])
  if status=='refunded' and payment['referral_id']:
   reward=c.execute('SELECT id,status FROM referral_rewards WHERE referral_id=?',(payment['referral_id'],)).fetchone()
   if reward:
    new_status='reversal_review' if reward['status']=='paid' else 'void'
    c.execute('UPDATE referral_rewards SET status=?,notes=? WHERE id=?',(new_status,'The qualifying advert payment was refunded; administrator review required.',reward['id']))
   c.execute("UPDATE school_referrals SET status='registered',converted_at='' WHERE id=?",(payment['referral_id'],))
  elif status=='paid' and payment['purpose']=='Institution promotion' and payment['tier'] in ('vip','vvip') and payment['referral_id']:
   existing=c.execute('SELECT id,payment_record_id,status FROM referral_rewards WHERE referral_id=?',(payment['referral_id'],)).fetchone()
   earned=now(); available=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
   if not existing:
    c.execute("INSERT INTO referral_rewards(referral_id,payment_record_id,amount_kes,status,earned_at,available_at,notes) VALUES(?,?,?,?,?,?,?)",(payment['referral_id'],rid,1000,'pending_clearance',earned,available,'Eligible after seven days, provided the advert payment is not refunded or reversed.'))
   elif existing['status']=='void' and existing['payment_record_id']!=rid:
    c.execute("UPDATE referral_rewards SET payment_record_id=?,amount_kes=1000,status='pending_clearance',earned_at=?,available_at=?,paid_at='',payout_reference='',notes=? WHERE id=?",(rid,earned,available,'A new eligible advert payment replaced a previously refunded payment; seven-day clearance restarted.',existing['id']))
   c.execute("UPDATE school_referrals SET status='converted',converted_at=? WHERE id=?",(now(),payment['referral_id']))
 audit('payment_record_updated','payment',rid,status)
 if status=='paid' and payment['referral_id']:audit('referral_reward_qualified','referral',payment['referral_id'],'KES 1,000 platform-funded reward; seven-day clearance started')
 if status=='refunded' and payment['referral_id']:audit('referral_reward_reviewed','referral',payment['referral_id'],'Qualifying advert refunded; reward voided or flagged for reversal review')
 return redirect('/admin#referrals')

@app.post('/admin/referrals/<int:rid>/advert-payment')
def referral_advert_payment_create(rid):
 r=admin_guard()
 if r:return r
 tier=request.form.get('tier','vip')
 if tier not in ('vip','vvip'):return error_page('Invalid advert package','Choose VIP or VVIP for an eligible paid promotion.')
 try: days=int(request.form.get('duration_days','30'))
 except (TypeError,ValueError):days=30
 if days not in PROMOTION_DURATIONS:days=30
 amount=promotion_price(tier,days)
 with conn() as c:
  referral=c.execute("SELECT sr.*,s.owner_account_id,s.name FROM school_referrals sr JOIN schools s ON s.id=sr.school_id WHERE sr.id=? AND sr.status='registered'",(rid,)).fetchone()
  if not referral:abort(404)
  existing=c.execute("SELECT id FROM payment_records WHERE referral_id=? AND purpose='Institution promotion' AND status NOT IN ('rejected','refunded') LIMIT 1",(rid,)).fetchone()
  if existing:return error_page('Advert payment already exists','This referred institution already has an open or confirmed advert payment record. Update that record in the Payments section instead.')
  c.execute("INSERT INTO payment_records(account_id,school_id,referral_id,purpose,tier,duration_days,amount,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(referral['owner_account_id'],referral['school_id'],rid,'Institution promotion',tier,days,str(amount),'awaiting_payment',f'{tier.upper()} · {days} days · KES {amount:,}. Confirm the exact payment reference before marking paid.',now()))
 audit('referral_advert_payment_created','referral',rid,f'{tier} advert payment record created for {referral["name"]}')
 return redirect('/admin#payments')

@app.post('/admin/referral-rewards/<int:rid>/pay')
def referral_reward_pay(rid):
 r=admin_guard()
 if r:return r
 payout_ref=safe(request.form.get('payout_reference'),120)
 if not payout_ref:return error_page('Payout reference required','Enter the M-PESA transaction code or verifiable payout reference before marking a reward paid.')
 with conn() as c:
  reward=c.execute('SELECT * FROM referral_rewards WHERE id=?',(rid,)).fetchone()
  if not reward:abort(404)
  if reward['status']=='pending_clearance' and reward['available_at']<=now():c.execute("UPDATE referral_rewards SET status='payable' WHERE id=?",(rid,))
  reward=c.execute('SELECT * FROM referral_rewards WHERE id=?',(rid,)).fetchone()
  if reward['status']!='payable':return error_page('Reward is not payable yet','Only rewards that have completed the seven-day clearance period can be paid.')
  c.execute("UPDATE referral_rewards SET status='paid',paid_at=?,payout_reference=? WHERE id=?",(now(),payout_ref,rid))
 audit('referral_reward_paid','referral_reward',rid,'KES 1,000 paid; reference '+payout_ref)
 return redirect('/admin#referrals')

@app.post('/admin/referrers/<int:rid>/status')
def referral_partner_status(rid):
 r=admin_guard()
 if r:return r
 status=request.form.get('status','paused')
 if status not in ('active','paused'):return error_page('Invalid referral status','Choose active or paused.')
 with conn() as c:c.execute('UPDATE referral_partners SET status=? WHERE id=?',(status,rid))
 audit('referral_partner_status_changed','referrer',rid,status)
 return redirect('/admin#referrals')

@app.post('/admin/errors/clear')
def clear_errors():return admin_action('DELETE FROM admin_errors',(),'admin_error_log_cleared','admin',None)
@app.get('/sitemap.xml')
def sitemap():
 with conn() as c:
  rows=c.execute("SELECT slug,updated_at FROM schools WHERE status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?)",(now(),)).fetchall()
  counties=[r[0] for r in c.execute("SELECT county FROM schools WHERE status='published' AND county<>'' AND (expires_at='' OR expires_at IS NULL OR expires_at>?) GROUP BY county HAVING COUNT(*)>=3 ORDER BY county",(now(),)).fetchall()]
 fixed=['/','/schools','/directory/school','/directory/college','/directory/university','/advertise','/school-portal','/campus-living','/invite-and-earn','/about','/privacy','/contact','/help']+[f'/schools-in-{slugify(x)}' for x in counties]
 origin=current_site(); urls=''.join(f'<url><loc>{origin}{u}</loc></url>' for u in fixed)+''.join(f'<url><loc>{origin}/school/{r["slug"]}</loc><lastmod>{r["updated_at"][:10]}</lastmod></url>' for r in rows)
 return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+urls+'</urlset>',mimetype='application/xml')
@app.get('/robots.txt')
def robots():return f'User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {current_site()}/sitemap.xml\n',200,{'Content-Type':'text/plain; charset=utf-8'}
@app.get('/uploads/<path:name>')
def uploaded(name):return send_from_directory(UPLOAD,name)
@app.errorhandler(404)
def not_found(e):return page('error',title='Page not found',message='The page may have moved, or the address may be incorrect.'),404
@app.errorhandler(413)
def too_large(e):return error_page('Upload too large','The uploaded file is too large.',413)
@app.errorhandler(Exception)
def unhandled(e):
 if isinstance(e, (KeyboardInterrupt,SystemExit)):raise e
 log_error(e,request.path); return error_page('Something went wrong','Something went wrong while processing your request. Please try again.',500)

if __name__=='__main__':app.run(host='0.0.0.0',port=PORT)
