import os, re, json, hmac, hashlib, secrets, sqlite3, shutil, time, threading, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, abort, make_response
from flask_session import Session
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import bcrypt, qrcode
from io import BytesIO

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/'.env')
DATA=Path(os.environ.get('DATA_DIR', BASE/'storage')).resolve(); UPLOAD=DATA/'uploads'; BACKUP=DATA/'backups'
for p in (DATA,UPLOAD,BACKUP): p.mkdir(parents=True,exist_ok=True)
PORT=int(os.environ.get('PORT','10000')); PROD=os.environ.get('FLASK_ENV')=='production' or os.environ.get('RENDER')=='true'
SITE=(os.environ.get('PUBLIC_SITE_URL') or f'http://localhost:{PORT}').rstrip('/')
if PROD:
 for key in ('ADMIN_USERNAME','ADMIN_PASSWORD'):
  if not os.environ.get(key): raise RuntimeError(f'Missing required Render environment variable: {key}')

app=Flask(__name__,static_folder='static',static_url_path='')
app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
# Keep Render's secret-variable setup to ADMIN_USERNAME and ADMIN_PASSWORD only.
# Derive a separate session-signing key from the admin password; changing the
# password will invalidate existing admin sessions, which is expected.
_admin_password_for_key=os.environ.get('ADMIN_PASSWORD','')
app.secret_key=hashlib.sha256(('schools.co.ke-session-key:'+_admin_password_for_key).encode('utf-8')).hexdigest() if _admin_password_for_key else 'development-only-change-this-secret-before-deploying-123456789'
app.config.update(SESSION_TYPE='filesystem',SESSION_FILE_DIR=str(DATA/'flask_sessions'),SESSION_PERMANENT=True,PERMANENT_SESSION_LIFETIME=timedelta(hours=8),SESSION_COOKIE_NAME='schools.admin',SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=PROD,MAX_CONTENT_LENGTH=50*1024*1024)
Path(app.config['SESSION_FILE_DIR']).mkdir(parents=True,exist_ok=True)
Session(app)
limiter=Limiter(get_remote_address,app=app,default_limits=[])
DB=DATA/'schools.sqlite'
def conn():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=5000'); return c
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
    image_credit TEXT DEFAULT '',
    image_source_url TEXT DEFAULT '',
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

  CREATE TABLE IF NOT EXISTS portal_enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_name TEXT NOT NULL,
    institution TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT DEFAULT '',
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );
'''
with conn() as c:
 c.execute('PRAGMA journal_mode=WAL')
 c.executescript(SCHEMA)
 for table,col,definition in [('schools','photos_json',"TEXT DEFAULT '[]'"),('schools','promotion_expires_at',"TEXT DEFAULT ''"),('schools','requested_tier',"TEXT DEFAULT 'none'")]:
  cols=[r['name'] for r in c.execute(f'PRAGMA table_info({table})')]
  if col not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
 for col,definition in [('image_credit',"TEXT DEFAULT ''"),('image_source_url',"TEXT DEFAULT ''")]:
  cols=[r['name'] for r in c.execute('PRAGMA table_info(schools)')]
  if col not in cols: c.execute(f'ALTER TABLE schools ADD COLUMN {col} {definition}')
 c.executescript("CREATE INDEX IF NOT EXISTS idx_schools_status_category ON schools(status, category); CREATE INDEX IF NOT EXISTS idx_schools_county ON schools(county); CREATE INDEX IF NOT EXISTS idx_schools_promotions ON schools(promotion_tier, promotion_expires_at);")

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
def institution_initials(name):
 words=[w for w in re.split(r'\s+',str(name or '').strip()) if w]
 return ''.join(w[0] for w in words[:2]).upper() or 'ED'
app.jinja_env.globals.update(formatDate=format_date,join_nonempty=join_nonempty,filter_nonempty=filter_nonempty,institutionInitials=institution_initials,phone_digits=lambda value: re.sub(r'[^0-9]','',str(value or '')),current_year=datetime.now().year)
COUNTIES=['Baringo','Bomet','Bungoma','Busia','Elgeyo-Marakwet','Embu','Garissa','Homa Bay','Isiolo','Kajiado','Kakamega','Kericho','Kiambu','Kilifi','Kirinyaga','Kisii','Kisumu','Kitui','Kwale','Laikipia','Lamu','Machakos','Makueni','Mandera','Marsabit','Meru','Migori','Mombasa','Murang’a','Nairobi','Nakuru','Nandi','Narok','Nyamira','Nyandarua','Nyeri','Samburu','Siaya','Taita-Taveta','Tana River','Tharaka-Nithi','Trans Nzoia','Turkana','Uasin Gishu','Vihiga','Wajir','West Pokot']
def directory_seed(name, category, ownership='', county='', town='', levels='', accommodation='', gender='', curriculum='', website='', description='', source_note=''):
 slug=slugify(name)
 if not description:
  description=f"Public-information directory profile for {name}. Confirm current admissions, programmes, fees and requirements directly with the institution."
 if not source_note:
  source_note="Public-information directory profile. The institution has not yet claimed or confirmed this profile on SCHOOLS."
 return (name,slug,category,ownership,levels or ('University' if category=='university' else ('College / TVET' if category=='college' else 'Secondary')),county,town,accommodation,gender,curriculum,website,description,source_note)

SEED=[]
# Established schools: directory information only; not claimed or endorsed.
SCHOOL_ROWS=[
('Alliance High School','Public','Kiambu','Kikuyu','Boarding','Boys','https://www.alliancehighschool.ac.ke/'),
('Strathmore School','Private','Nairobi','Lavington','Day','','https://www.strathmore.ac.ke/'),
('Kenya High School','Public','Nairobi','Kileleshwa','Boarding','Girls',''),
('Nairobi School','Public','Nairobi','Nairobi','Boarding','Boys',''),
("Mang'u High School",'Public','Kiambu','Thika','Boarding','Boys','https://www.manguhigh.com/'),
('Lenana School','Public','Nairobi','Dagoretti','Boarding','Boys',''),
('Pangani Girls School','Public','Nairobi','Pangani','Boarding','Girls',''),
('Moi Girls School Nairobi','Public','Nairobi','Nairobi','Boarding','Girls',''),
('Maryhill Girls High School','Public','Kiambu','Thika','Boarding','Girls',''),
('Loreto High School Limuru','Private','Kiambu','Limuru','Boarding','Girls',''),
('Kapsabet Boys High School','Public','Nandi','Kapsabet','Boarding','Boys',''),
('Maseno School','Public','Kisumu','Maseno','Boarding','Boys',''),
('Maranda High School','Public','Siaya','Bondo','Boarding','Boys',''),
('Friends School Kamusinga','Public','Bungoma','Kimilili','Boarding','Boys',''),
('Starehe Boys Centre and School','Private','Nairobi','Nairobi','Boarding','Boys',''),
('Brookhouse School','Private','Nairobi','Karen','Day','Mixed',''),
('Braeburn School','Private','Nairobi','Garden Estate','Day','Mixed',''),
('Aga Khan Academy Nairobi','Private','Nairobi','Nairobi','Day','Mixed',''),
('Riara School','Private','Nairobi','Riara Road','Day','Mixed',''),
('Light International School','Private','Nairobi','Nairobi','Day','Mixed',''),
('Precious Blood Riruta','Private','Nairobi','Riruta','Boarding','Girls',''),
('Bishop Gatimu Ngandu Girls High School','Public','Nyeri','Nyeri','Boarding','Girls',''),
('Nakuru High School','Public','Nakuru','Nakuru','Boarding','Boys',''),
('Moi High School Kabarak','Private','Nakuru','Kabarak','Boarding','Mixed','')]
for name,own,county,town,accom,gender,web in SCHOOL_ROWS:
 SEED.append(directory_seed(name,'school',own,county,town,'Secondary',accom,gender,'Secondary education',web))
# Major public TVET and specialist colleges.
COLLEGE_ROWS=[
('Kenya Utalii College','Nairobi','Nairobi','Hospitality and tourism training','https://utalii.ac.ke/'),
('Kenya Medical Training College','Nairobi','Nairobi','Medical training','https://kmtc.ac.ke/'),
('The Nairobi National Polytechnic','Nairobi','Nairobi','Technical and vocational training',''),
('Kabete National Polytechnic','Nairobi','Kabete','Technical and vocational training',''),
('Kenya Coast National Polytechnic','Mombasa','Mombasa','Technical and vocational training',''),
('The Kisumu National Polytechnic','Kisumu','Kisumu','Technical and vocational training',''),
('The Eldoret National Polytechnic','Uasin Gishu','Eldoret','Technical and vocational training',''),
('Rift Valley Institute of Science and Technology','Nakuru','Nakuru','Technical and vocational training',''),
('Nyeri National Polytechnic','Nyeri','Nyeri','Technical and vocational training',''),
('Meru National Polytechnic','Meru','Meru','Technical and vocational training',''),
('Sigalagala National Polytechnic','Kakamega','Sigalagala','Technical and vocational training',''),
('Kisii National Polytechnic','Kisii','Kisii','Technical and vocational training',''),
('Kenya Institute of Mass Communication','Nairobi','Nairobi','Media and communication training',''),
('Kenya Institute of Special Education','Nairobi','Nairobi','Special needs education training','https://kise.ac.ke/')]
for name,county,town,focus,web in COLLEGE_ROWS:
 SEED.append(directory_seed(name,'college','Public',county,town,'College / TVET','', 'Mixed',focus,web))
# CUE approved public/private chartered universities as at 5 November 2026.
CUE_SOURCE='https://www.cue.or.ke/index.php?Itemid=511&download=294%3Aapproved-universities-15th-september-2026&id=81%3Aapproved-academic-programmes-dec-2023&option=com_phocadownload&view=category'
CUE_NOTE='Listed in the Commission for University Education approved-universities publication dated 5 November 2026. This SCHOOLS profile is independent and is not operated or endorsed by CUE; confirm current programme accreditation directly.'
PUBLIC_UNIVERSITIES=['University of Nairobi','Moi University','Kenyatta University','Egerton University','Jomo Kenyatta University of Agriculture and Technology','Maseno University','Masinde Muliro University of Science and Technology','Dedan Kimathi University of Technology','Chuka University','Technical University of Kenya','Technical University of Mombasa','Pwani University','Kisii University','University of Eldoret','Maasai Mara University','Jaramogi Oginga Odinga University of Science and Technology','Laikipia University','South Eastern Kenya University','Meru University of Science and Technology','Multimedia University of Kenya','University of Kabianga','Karatina University','Kibabii University','Rongo University','The Co-operative University of Kenya','Taita Taveta University',"Murang'a University of Technology",'University of Embu','Machakos University','Kirinyaga University','Garissa University','Alupe University','Kaimosi Friends University','Tom Mboya University','Tharaka University','Bomet University']
PRIVATE_UNIVERSITIES=['University of Eastern Africa, Baraton','Catholic University of Eastern Africa','Daystar University','Scott Christian University','United States International University','Africa Nazarene University','Kenya Methodist University',"St. Paul's University",'Pan Africa Christian University','Strathmore University','Kabarak University','Mount Kenya University','Africa International University','Kenya Highlands Evangelical University','Great Lakes University of Kisumu','KCA University','Adventist University of Africa','KAG EAST University','Umma University','Presbyterian University of East Africa','Aga Khan University',"Kiriri Women's University of Science and Technology",'The East African University','Zetech University','Lukenya University','Management University of Africa','Tangaza University','Islamic University of Kenya','Riara University','Uzima University','Gretsa University','Amref International University','International Leadership University']
for name in PUBLIC_UNIVERSITIES:
 SEED.append(directory_seed(name,'university','Public',levels='University',curriculum='Degree and postgraduate programmes',source_note=CUE_NOTE))
for name in PRIVATE_UNIVERSITIES:
 SEED.append(directory_seed(name,'university','Private',levels='University',curriculum='Degree and postgraduate programmes',source_note=CUE_NOTE))
for name,own in [('Turkana University College','Public'),('Koitaleel Samoei University College','Public'),('Mama Ngina University College','Public'),('Nyandarua University College','Public'),('Kabarnet University College','Public'),('Makueni University College','Public'),('Kerio Valley University College','Public'),('Hekima University College','Private'),('Marist International University College','Private')]:
 SEED.append(directory_seed(name,'college',own,levels='University constituent college',curriculum='University-level programmes',source_note=CUE_NOTE))

# Add only missing records. Never overwrite profiles that an institution or admin has edited.
with conn() as c:
 for r in SEED:
  name,slug,cat,own,levels,county,town,accom,gender,curr,web,desc,source_note=r
  if c.execute('SELECT 1 FROM schools WHERE slug=?',(slug,)).fetchone(): continue
  t=now()
  c.execute("""INSERT INTO schools(name,slug,category,ownership,levels,county,town,accommodation,gender,curriculum,website,description,trust_status,promotion_tier,status,source_note,is_seeded,posted_at,expires_at,last_renewed_at,created_at,updated_at)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'unverified','none','published',?,1,?,'',?,?,?)""",
  (name,slug,cat,own,levels,county,town,accom,gender,curr,web,desc,source_note,t,t,t,t))
 # Old auto-seeded "recognised" badges could be mistaken for institutional verification.
 c.execute("""UPDATE schools SET trust_status='unverified', source_note=CASE WHEN source_note='' OR source_note LIKE 'Recognised public-information%' THEN 'Public-information directory profile. The institution has not yet claimed or confirmed this profile on SCHOOLS.' ELSE source_note END WHERE is_seeded=1 AND trust_status='recognised'""")
 # Two real, directly attributed CC BY-SA 4.0 campus photographs from Wikimedia Commons.
 c.execute("""UPDATE schools SET cover_path=?,image_credit=?,image_source_url=? WHERE slug='alliance-high-school' AND is_seeded=1 AND (cover_path='' OR cover_path LIKE '%school-hero.webp')""",
 ('https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/New_Complex_at_Alliance_High_School.jpg/1280px-New_Complex_at_Alliance_High_School.jpg','Photo: Hansie453, “New Complex at Alliance High School” (2016), Wikimedia Commons, CC BY-SA 4.0.','https://commons.wikimedia.org/wiki/File:New_Complex_at_Alliance_High_School.jpg'))
 c.execute("""UPDATE schools SET cover_path=?,image_credit=?,image_source_url=? WHERE slug='kenya-high-school' AND is_seeded=1 AND (cover_path='' OR cover_path LIKE '%school-hero.webp')""",
 ('https://upload.wikimedia.org/wikipedia/commons/c/cb/The_Kenya_High_School_Main_Gate.jpg','Photo: Lilly Stein, “The Kenya High School Main Gate” (2017), Wikimedia Commons, CC BY-SA 4.0.','https://commons.wikimedia.org/wiki/File:The_Kenya_High_School_Main_Gate.jpg'))
 c.execute("""UPDATE schools SET cover_path=?,image_credit=?,image_source_url=? WHERE slug='mang-u-high-school' AND is_seeded=1 AND (cover_path='' OR cover_path LIKE '%school-hero.webp')""",
 ('https://upload.wikimedia.org/wikipedia/commons/e/e1/Mang%27u_High_School.png','Photo: Anthony Mudhoka, “Mang’u High School” (2018), Wikimedia Commons, CC BY-SA 4.0.','https://commons.wikimedia.org/wiki/File:Mang%27u_High_School.png'))
 c.execute("""UPDATE schools SET cover_path=?,image_credit=?,image_source_url=? WHERE slug='university-of-nairobi' AND is_seeded=1 AND (cover_path='' OR cover_path LIKE '%school-hero.webp')""",
 ('https://upload.wikimedia.org/wikipedia/commons/1/16/University_of_Nairobi%2C_Kenya.jpg','Photo: EstherWikipedian, “University of Nairobi, Kenya” (2023), Wikimedia Commons, CC BY-SA 4.0.','https://commons.wikimedia.org/wiki/File:University_of_Nairobi,_Kenya.jpg'))
 c.execute("""UPDATE schools SET cover_path=?,image_credit=?,image_source_url=? WHERE slug='kenyatta-university' AND is_seeded=1 AND (cover_path='' OR cover_path LIKE '%school-hero.webp')""",
 ('https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/KenyattaUnivAdmin.jpg/1280px-KenyattaUnivAdmin.jpg','Photo: Thorkild Tylleskar, “Kenyatta University Central Administration Complex” (2016), Wikimedia Commons, CC BY-SA 4.0.','https://commons.wikimedia.org/wiki/File:KenyattaUnivAdmin.jpg'))

def active_schools(where='',params=()):
 t=now()
 with conn() as c:return [dict(x) for x in c.execute(f"SELECT *, CASE WHEN promotion_tier <> 'none' AND promotion_expires_at > ? THEN promotion_tier ELSE 'none' END AS active_promotion_tier FROM schools WHERE status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?) {where} ORDER BY CASE WHEN promotion_tier='vvip' AND promotion_expires_at>? THEN 0 WHEN promotion_tier='vip' AND promotion_expires_at>? THEN 1 ELSE 2 END, COALESCE(last_featured_at,'') ASC, name COLLATE NOCASE ASC",(t,t,t,t,*params)).fetchall()]
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
 qrurl=os.environ.get('SIGNATURE_QR_URL',SITE+'/?source=toror-signature-qr')
 qr=qrcode.QRCode(box_size=3,border=1); qr.add_data(qrurl); qr.make(fit=True); im=qr.make_image(fill_color='#17324d',back_color='white'); bio=BytesIO(); im.save(bio,format='PNG')
 from base64 import b64encode
 return dict(siteName='SCHOOLS',siteUrl=SITE,companyName='Toror Technology and Innovations Limited',qrData='data:image/png;base64,'+b64encode(bio.getvalue()).decode(),metaTitle='Discover Schools, Colleges & Universities in Kenya | SCHOOLS',metaDescription='Find and compare schools, colleges and universities across Kenya. Explore institution profiles, locations, facilities, admissions and campus accommodation.',canonical=SITE+('/' if path=='/' else path),pageImage=SITE+'/images/schools-icon-512.png',isAdmin=bool(session.get('admin')),csrfToken=session.get('csrfToken',''),robots='index,follow',globalPromos=promos,structured_data={'@context':'https://schema.org','@type':'WebSite','name':'SCHOOLS','url':SITE,'description':'Find and compare schools, colleges and universities across Kenya.','potentialAction':{'@type':'SearchAction','target':SITE+'/schools?q={search_term_string}','query-input':'required name=search_term_string'}})
def page(template,**kwargs):
 ctx=base_context(); ctx.update(kwargs)
 if template=='directory':
  ctx.setdefault('metaTitle', (kwargs.get('title') or 'Explore institutions')+' | SCHOOLS')
  ctx.setdefault('metaDescription', (kwargs.get('intro') or 'Explore schools, colleges and universities across Kenya.')+' Compare institution profiles, locations, programmes and contact information.')
  ctx.setdefault('canonical', SITE+request.path)
  if request.args: ctx['robots']='noindex,follow'
  if len(kwargs.get('schools',[]))<3 and request.path.startswith('/schools-in-'): ctx['robots']='noindex,follow'
 elif template=='advertise':
  ctx.update(metaTitle='Advertise Your School | Reach Parents Across Kenya',metaDescription='Create a school listing, showcase your campus, publish admissions information and reach parents and learners searching for institutions in Kenya.')
 elif template=='portal':
  ctx.update(metaTitle='Get a School Website & Portal | SCHOOLS',metaDescription='Get a modern school website with admissions pages, galleries, announcements and an easy content dashboard.')
 elif template=='campus':
  ctx.update(metaTitle='Student Accommodation, Hostels & Rentals in Kenya | SCHOOLS',metaDescription='Explore student hostels, rental accommodation and campus-area services. Find places near colleges and universities.')
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

@app.after_request
def security_headers(resp):
 resp.headers.setdefault('X-Content-Type-Options','nosniff'); resp.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin'); resp.headers.setdefault('X-Frame-Options','SAMEORIGIN'); resp.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
 if PROD:resp.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
 return resp
@app.get('/healthz')
def health():
 try:
  with conn() as c:c.execute('SELECT 1')
  return {'ok':True,'service':'schools-ke-platform','time':now()}
 except Exception as e:return {'ok':False},503
@app.get('/')
def home():
 with conn() as c:
  counts={k:c.execute('SELECT COUNT(*) FROM schools WHERE status="published"'+(f' AND category="{cat}"' if cat else '')).fetchone()[0] for k,cat in [('allCount',''),('schoolCount','school'),('collegeCount','college'),('universityCount','university')]}
 featured=[]
 for category in ('school','college','university'):
  rows=active_schools('AND category=?',[category])
  if rows:
   # Prefer an institution with a real credited photograph when selecting the first school card.
   chosen=next((row for row in rows if row.get('cover_path') and (not row.get('is_seeded') or (row.get('image_credit') and row.get('image_source_url')))),rows[0])
   featured.append(chosen)
 if len(featured)<4:
  used={row['id'] for row in featured}
  for row in active_schools():
   if row['id'] not in used:
    featured.append(row); used.add(row['id'])
   if len(featured)>=4: break
 featured=feature_rotation(featured,4); vvip=feature_rotation(active_schools("AND promotion_tier='vvip' AND promotion_expires_at>?",[now()]),3)
 return page('home',featured=featured,vvip=vvip,counts=counts)
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
  row=c.execute("SELECT *,CASE WHEN promotion_tier<>'none' AND promotion_expires_at>? THEN promotion_tier ELSE 'none' END AS active_promotion_tier FROM schools WHERE slug=?",(t,slug)).fetchone()
  if not row or row['status']!='published' or (not row['is_seeded'] and row['expires_at'] and row['expires_at']<=t):abort(404)
  c.execute('UPDATE schools SET views=views+1 WHERE id=?',(row['id'],)); school=dict(row)
 related=active_schools('AND id<>? AND (county=? OR category=?)',[school['id'],school['county'],school['category']])[:4]
 cover=school.get('cover_path') or ''
 if school.get('is_seeded'):
  # Seeded institution profiles show only photographs with explicit source and licence attribution.
  photos=[cover] if cover and school.get('image_credit') and school.get('image_source_url') else []
 else:
  try:photos=json.loads(school.get('photos_json') or '[]')
  except:photos=[]
  photos=[photo for photo in photos if isinstance(photo,str) and photo.strip() and '/images/school-hero.webp' not in photo]
  if cover and '/images/school-hero.webp' not in cover and cover not in photos:photos.insert(0,cover)
 image_path=cover if cover and (not school.get('is_seeded') or (school.get('image_credit') and school.get('image_source_url'))) and '/images/school-hero.webp' not in cover else '/images/schools-icon-512.png'
 image_url=image_path if image_path.startswith(('http://','https://')) else SITE+image_path
 ctx=base_context(); ctx.update(metaTitle=f"{school['name']} | {school['town'] or school['county']} | SCHOOLS",metaDescription=safe(school.get('description') or f"Explore {school['name']}, including its location, school information and contact details.",160),canonical=SITE+'/school/'+slug,pageImage=image_url,school=school,related=related,photos=photos,enquirySent=request.args.get('enquiry')=='sent',structured_data={'@context':'https://schema.org','@type':'CollegeOrUniversity' if school['category']=='university' else ('EducationalOrganization' if school['category']=='college' else 'School'),'name':school['name'],'url':SITE+'/school/'+slug,'description':school.get('description'),'address':{'@type':'PostalAddress','addressLocality':school.get('town'),'addressRegion':school.get('county'),'addressCountry':'KE'},'telephone':school.get('phone'),'email':school.get('email'),'sameAs':[school['website']] if school.get('website') else [],'image':image_url})
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
@app.get('/advertise')
def advertise():return page('advertise',sent=request.args.get('sent')=='1')
@app.post('/advertise')
@limiter.limit('8 per hour')
def advertise_post():
 if safe(request.form.get('website_confirm'),150):return redirect('/advertise?sent=1')
 name=safe(request.form.get('name'),160)
 if not name:return error_page('School name required','Please enter the institution name and submit again.')
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
 slug=slugify(name)+'-'+secrets.token_hex(2); tier=request.form.get('requested_tier','none'); tier=tier if tier in ('none','vip','vvip') else 'none'; t=now()
 vals=[name,slug,safe(request.form.get('category'),30) or 'school',safe(request.form.get('ownership'),40),safe(request.form.get('levels'),150),safe(request.form.get('county'),80),safe(request.form.get('town'),80),safe(request.form.get('accommodation'),40),safe(request.form.get('gender'),40),safe(request.form.get('curriculum'),100),safe(request.form.get('fees_range'),100),safe(request.form.get('address'),250),safe(request.form.get('phone'),60),safe(request.form.get('email'),160),safe_url(request.form.get('website')),safe(request.form.get('description'),2500),photos[0] if photos else '',json.dumps(photos),safe_url(request.form.get('video_url')),tier,t,t]
 with conn() as c:c.execute("INSERT INTO schools(name,slug,category,ownership,levels,county,town,accommodation,gender,curriculum,fees_range,address,phone,email,website,description,cover_path,photos_json,video_url,trust_status,promotion_tier,requested_tier,status,source_note,is_seeded,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'unverified','none',?,'pending','Submitted by an institution representative; awaiting review.',0,?,?)",vals)
 audit('school_submitted','school',None,name); return redirect('/advertise?sent=1')
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
 vals=[title,safe(request.form.get('property_type'),80),safe(request.form.get('institution'),160),safe(request.form.get('county'),80),safe(request.form.get('town'),80),safe(request.form.get('price'),80),safe(request.form.get('contact'),80),safe(request.form.get('description'),1500),'pending',now()]
 with conn() as c:c.execute('INSERT INTO properties(title,property_type,institution,county,town,price,contact,description,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',vals)
 audit('property_submitted','property',None,title); return redirect('/campus-living?sent=1')
@app.get('/about')
def about():return page('about')
@app.get('/privacy')
def privacy():return page('privacy')
@app.get('/admin/login')
def admin_login():
 if session.get('admin'):return redirect('/admin')
 session['csrfToken']=secrets.token_hex(32); response=page('admin-login',error=''); return response
@app.post('/admin/login')
@limiter.limit('8 per 15 minutes')
def admin_login_post():
 username=safe(request.form.get('username'),120); password=request.form.get('password',''); expected=os.environ.get('ADMIN_USERNAME','admin'); configured=os.environ.get('ADMIN_PASSWORD','')
 valid_user=hmac.compare_digest(username.encode(),expected.encode())
 valid_pw=bcrypt.checkpw(password.encode(),bcrypt.hashpw(configured.encode(),bcrypt.gensalt())) if configured and password else (not PROD and password=='admin12345')
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
  stats={k:c.execute(sql).fetchone()[0] for k,sql in [('schools',"SELECT COUNT(*) FROM schools WHERE status='published'"),('pending',"SELECT COUNT(*) FROM schools WHERE status='pending'"),('expired',"SELECT COUNT(*) FROM schools WHERE status='expired'"),('properties',"SELECT COUNT(*) FROM properties WHERE status='pending'"),('enquiries','SELECT COUNT(*) FROM enquiries')]}
 ctx=base_context(); ctx.update(robots='noindex,nofollow',metaTitle='Admin Dashboard | SCHOOLS',schools=schools,properties=props,errors=errors,enquiries=enquiries,portalEnquiries=portals,stats=stats); return render_template('admin-dashboard.html',**ctx)
def admin_action(sql,args,action,typ,rid,detail=''):
 r=admin_guard()
 if r:return r
 with conn() as c:c.execute(sql,args)
 audit(action,typ,rid,detail); return redirect('/admin')
@app.post('/admin/schools/<int:rid>/approve')
def school_approve(rid):
 t=now(); exp=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(); return admin_action("UPDATE schools SET status='published',posted_at=?,expires_at=?,last_renewed_at=?,updated_at=? WHERE id=?",(t,exp,t,t,rid),'school_approved','school',rid,'Published for 30 days')
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
@app.post('/admin/errors/clear')
def clear_errors():return admin_action('DELETE FROM admin_errors',(),'admin_error_log_cleared','admin',None)
@app.get('/sitemap.xml')
def sitemap():
 with conn() as c:
  rows=c.execute("SELECT slug,updated_at FROM schools WHERE status='published' AND (expires_at='' OR expires_at IS NULL OR expires_at>?)",(now(),)).fetchall()
  counties=[r[0] for r in c.execute("SELECT county FROM schools WHERE status='published' AND county<>'' AND (expires_at='' OR expires_at IS NULL OR expires_at>?) GROUP BY county HAVING COUNT(*)>=3 ORDER BY county",(now(),)).fetchall()]
 fixed=['/','/schools','/directory/school','/directory/college','/directory/university','/advertise','/school-portal','/campus-living','/about','/privacy']+[f'/schools-in-{slugify(x)}' for x in counties]
 urls=''.join(f'<url><loc>{SITE}{u}</loc></url>' for u in fixed)+''.join(f'<url><loc>{SITE}/school/{r["slug"]}</loc><lastmod>{r["updated_at"][:10]}</lastmod></url>' for r in rows)
 return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+urls+'</urlset>',mimetype='application/xml')
@app.get('/robots.txt')
def robots():return f'User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {SITE}/sitemap.xml\n',200,{'Content-Type':'text/plain; charset=utf-8'}
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
