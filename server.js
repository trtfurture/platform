'use strict';

const express = require('express');
const session = require('express-session');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const multer = require('multer');
const bcrypt = require('bcryptjs');
const QRCode = require('qrcode');
const Database = require('better-sqlite3');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

// Load a local .env file for development; Render supplies environment variables directly.
if (fs.existsSync(path.join(__dirname, '.env'))) process.loadEnvFile(path.join(__dirname, '.env'));

const app = express();
const PORT = Number(process.env.PORT || 3000);
const IS_PROD = process.env.NODE_ENV === 'production';
const SITE_URL = (process.env.PUBLIC_SITE_URL || `http://localhost:${PORT}`).replace(/\/$/, '');
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, 'storage'));
const UPLOAD_DIR = path.join(DATA_DIR, 'uploads');
const BACKUP_DIR = path.join(DATA_DIR, 'backups');
const DB_PATH = path.join(DATA_DIR, 'schools.sqlite');
const COMPANY_NAME = 'Toror Technology and Innovations Limited';
const COUNTIES = ['Baringo','Bomet','Bungoma','Busia','Elgeyo-Marakwet','Embu','Garissa','Homa Bay','Isiolo','Kajiado','Kakamega','Kericho','Kiambu','Kilifi','Kirinyaga','Kisii','Kisumu','Kitui','Kwale','Laikipia','Lamu','Machakos','Makueni','Mandera','Marsabit','Meru','Migori','Mombasa','Murang’a','Nairobi','Nakuru','Nandi','Narok','Nyamira','Nyandarua','Nyeri','Samburu','Siaya','Taita-Taveta','Tana River','Tharaka-Nithi','Trans Nzoia','Turkana','Uasin Gishu','Vihiga','Wajir','West Pokot'];

for (const dir of [DATA_DIR, UPLOAD_DIR, BACKUP_DIR]) fs.mkdirSync(dir, { recursive: true });

if (IS_PROD) {
  for (const key of ['ADMIN_USERNAME', 'ADMIN_PASSWORD', 'SESSION_SECRET']) {
    if (!process.env[key]) throw new Error(`Missing required Render environment variable: ${key}`);
  }
  if ((process.env.SESSION_SECRET || '').length < 32) throw new Error('SESSION_SECRET must be at least 32 characters.');
}

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');
db.pragma('busy_timeout = 5000');
db.exec(`
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

  CREATE TABLE IF NOT EXISTS portal_enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_name TEXT NOT NULL,
    institution TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT DEFAULT '',
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
  );
`);

// Lightweight schema migrations keep existing SQLite installations compatible.
function ensureColumn(table, column, definition) {
  const columns = db.pragma(`table_info(${table})`).map((item) => item.name);
  if (!columns.includes(column)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}
ensureColumn('schools', 'photos_json', "TEXT DEFAULT '[]'");
ensureColumn('schools', 'promotion_expires_at', "TEXT DEFAULT ''");
ensureColumn('schools', 'requested_tier', "TEXT DEFAULT 'none'");
db.exec("CREATE INDEX IF NOT EXISTS idx_schools_status_category ON schools(status, category); CREATE INDEX IF NOT EXISTS idx_schools_county ON schools(county); CREATE INDEX IF NOT EXISTS idx_schools_promotions ON schools(promotion_tier, promotion_expires_at);");

class SQLiteSessionStore extends session.Store {
  constructor(database) {
    super();
    this.getStatement = database.prepare('SELECT sess, expires_at FROM sessions WHERE sid = ?');
    this.setStatement = database.prepare('INSERT INTO sessions (sid, sess, expires_at) VALUES (?, ?, ?) ON CONFLICT(sid) DO UPDATE SET sess = excluded.sess, expires_at = excluded.expires_at');
    this.destroyStatement = database.prepare('DELETE FROM sessions WHERE sid = ?');
    this.touchStatement = database.prepare('UPDATE sessions SET expires_at = ? WHERE sid = ?');
  }
  get(sid, callback) {
    try {
      const row = this.getStatement.get(sid);
      if (!row) return callback(null, null);
      if (row.expires_at <= Date.now()) { this.destroyStatement.run(sid); return callback(null, null); }
      callback(null, JSON.parse(row.sess));
    } catch (error) { callback(error); }
  }
  set(sid, sess, callback) {
    try {
      const expiry = sess.cookie?.expires ? new Date(sess.cookie.expires).getTime() : Date.now() + 8 * 60 * 60 * 1000;
      this.setStatement.run(sid, JSON.stringify(sess), expiry);
      callback?.(null);
    } catch (error) { callback?.(error); }
  }
  destroy(sid, callback) {
    try { this.destroyStatement.run(sid); callback?.(null); } catch (error) { callback?.(error); }
  }
  touch(sid, sess, callback) {
    try {
      const expiry = sess.cookie?.expires ? new Date(sess.cookie.expires).getTime() : Date.now() + 8 * 60 * 60 * 1000;
      this.touchStatement.run(expiry, sid);
      callback?.(null);
    } catch (error) { callback?.(error); }
  }
}

const nowIso = () => new Date().toISOString();
const slugify = (value) => String(value || '')
  .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 75);
const addMonthsDays = (date, days) => new Date(date.getTime() + days * 86400000).toISOString();
const safeText = (value, max = 5000) => String(value || '').trim().slice(0, max);
const safeUrl = (value) => {
  const input = safeText(value, 500);
  if (!input) return '';
  try {
    const url = new URL(input.startsWith('http') ? input : `https://${input}`);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '';
  } catch { return ''; }
};

function logAdminError(err, route = '') {
  try {
    db.prepare('INSERT INTO admin_errors (level, message, route, stack, created_at) VALUES (?, ?, ?, ?, ?)')
      .run('error', safeText(err?.message || 'Unknown error', 1000), route, safeText(err?.stack || '', 6000), nowIso());
  } catch (logErr) {
    console.error('Could not persist error log:', logErr.message);
  }
  console.error(err);
}

function audit(action, recordType = '', recordId = null, detail = '') {
  db.prepare('INSERT INTO audit_events (action, record_type, record_id, detail, created_at) VALUES (?, ?, ?, ?, ?)')
    .run(action, recordType, recordId, safeText(detail, 1000), nowIso());
}

const schoolCount = db.prepare('SELECT COUNT(*) AS count FROM schools').get().count;
if (schoolCount === 0) {
  const seed = db.prepare(`INSERT INTO schools
    (name, slug, category, ownership, levels, county, town, accommodation, gender, curriculum, website, description, trust_status, promotion_tier, status, source_note, is_seeded, posted_at, expires_at, last_renewed_at, created_at, updated_at)
    VALUES (@name, @slug, @category, @ownership, @levels, @county, @town, @accommodation, @gender, @curriculum, @website, @description, 'recognised', 'none', 'published', @source_note, 1, @now, '', @now, @now, @now)`);
  const records = [
    { name: 'Alliance High School', slug: 'alliance-high-school', category: 'school', ownership: 'Public', levels: 'Secondary', county: 'Kiambu', town: 'Kikuyu', accommodation: 'Boarding', gender: 'Boys', curriculum: 'Secondary education', website: 'https://www.alliancehighschool.ac.ke/', description: 'A recognised Kenyan secondary school in Kikuyu, Kiambu County. This directory profile is an introductory listing; contact the school directly for current admissions, fees and requirements.', source_note: 'Recognised public-information listing. The school has not yet claimed or confirmed this profile on SCHOOLS.' },
    { name: 'Strathmore School', slug: 'strathmore-school', category: 'school', ownership: 'Private', levels: 'Primary, Junior, Secondary', county: 'Nairobi', town: 'Lavington', accommodation: 'Day', gender: '', curriculum: 'Contact institution for current curriculum details', website: 'https://www.strathmore.ac.ke/', description: 'A private school located in Lavington, Nairobi. Explore its official website for current school-life, admissions and transfer information.', source_note: 'Basic location and institutional information referenced from the official school website. Not yet claimed or confirmed on SCHOOLS.' },
    { name: 'University of Nairobi', slug: 'university-of-nairobi', category: 'university', ownership: 'Public', levels: 'University', county: 'Nairobi', town: 'Nairobi', accommodation: '', gender: 'Mixed', curriculum: 'Degree and postgraduate programmes', website: 'https://www.uonbi.ac.ke/', description: 'A public university based in Nairobi with multiple campuses and academic programmes. Visit the official website for current courses, admissions and campus information.', source_note: 'Recognised public-information listing. The university has not yet claimed or confirmed this profile on SCHOOLS.' },
    { name: 'Kenyatta University', slug: 'kenyatta-university', category: 'university', ownership: 'Public', levels: 'University', county: 'Nairobi', town: 'Kahawa', accommodation: '', gender: 'Mixed', curriculum: 'Degree and postgraduate programmes', website: 'https://www.ku.ac.ke/', description: 'A public university whose main campus is in Kahawa, Nairobi County. Visit the official university website for current programmes, admissions and campus details.', source_note: 'Main-campus location referenced from the official university website. Not yet claimed or confirmed on SCHOOLS.' },
    { name: 'Kenya Utalii College', slug: 'kenya-utalii-college', category: 'college', ownership: 'Public', levels: 'College / TVET', county: 'Nairobi', town: 'Off Thika Road', accommodation: '', gender: 'Mixed', curriculum: 'Hospitality and tourism training', website: 'https://utalii.ac.ke/', description: 'A hospitality and tourism training institution with its main campus off Thika Road in Nairobi. Visit the official website for current programmes, admissions and campus information.', source_note: 'Location and programme area referenced from the official college website. Not yet claimed or confirmed on SCHOOLS.' }
  ];
  for (const r of records) seed.run({ ...r, now: nowIso() });
}

const adminPasswordHash = process.env.ADMIN_PASSWORD ? bcrypt.hashSync(process.env.ADMIN_PASSWORD, 10) : '';
const sessionSecret = process.env.SESSION_SECRET || 'development-only-change-this-secret-before-deploying-123456789';

app.set('trust proxy', 1);
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(helmet({ contentSecurityPolicy: false, crossOriginEmbedderPolicy: false }));
app.use(express.urlencoded({ extended: true, limit: '1mb' }));
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'public'), { maxAge: IS_PROD ? '7d' : 0 }));
app.use('/uploads', express.static(UPLOAD_DIR, { maxAge: '30d', immutable: true }));
app.use(session({
  name: 'schools.admin',
  secret: sessionSecret,
  store: new SQLiteSessionStore(db),
  resave: false,
  saveUninitialized: false,
  rolling: true,
  cookie: { httpOnly: true, sameSite: 'lax', secure: IS_PROD, maxAge: 8 * 60 * 60 * 1000 }
}));

let qrData = '';
QRCode.toDataURL(process.env.SIGNATURE_QR_URL || `${SITE_URL}/?source=toror-signature-qr`, { width: 132, margin: 1, color: { dark: '#17324d', light: '#ffffff' } })
  .then((data) => { qrData = data; })
  .catch((err) => logAdminError(err, 'qr-generation'));

app.use((req, res, next) => {
  res.locals.siteName = 'SCHOOLS';
  res.locals.siteUrl = SITE_URL;
  res.locals.companyName = COMPANY_NAME;
  res.locals.qrData = qrData;
  res.locals.metaTitle = 'Discover Schools, Colleges & Universities in Kenya | SCHOOLS';
  res.locals.metaDescription = 'Find and compare schools, colleges and universities across Kenya. Explore institution profiles, locations, facilities, admissions and campus accommodation.';
  res.locals.canonical = `${SITE_URL}${req.path === '/' ? '/' : req.path}`;
  res.locals.pageImage = `${SITE_URL}/images/school-hero.webp`;
  res.locals.isAdmin = Boolean(req.session?.admin);
  res.locals.csrfToken = req.session?.csrfToken || '';
  res.locals.robots = 'index,follow';
  res.locals.formatDate = (value) => value ? new Date(value).toLocaleDateString('en-KE', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  // VVIP placements can appear across the platform, including related college and campus pages.
  // The badge always says sponsored; payment never changes a school's verification status.
  res.locals.globalPromos = (!req.path.startsWith('/admin') && req.path !== '/')
    ? featureRotation(db.prepare("SELECT * FROM schools WHERE status = 'published' AND promotion_tier = 'vvip' AND promotion_expires_at > ? AND (expires_at = '' OR expires_at IS NULL OR expires_at > ?) ORDER BY COALESCE(last_featured_at, '') ASC LIMIT 8").all(nowIso(), nowIso()), 3)
    : [];
  next();
});

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, UPLOAD_DIR),
    filename: (_req, file, cb) => {
      const extension = ({ 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp' })[file.mimetype] || '.img';
      cb(null, `${Date.now()}-${crypto.randomBytes(5).toString('hex')}${extension}`);
    }
  }),
  limits: { fileSize: 8 * 1024 * 1024, files: 6 },
  fileFilter: (_req, file, cb) => {
    const allowed = ['image/jpeg', 'image/png', 'image/webp'];
    cb(allowed.includes(file.mimetype) ? null : new Error('Please upload JPG, PNG or WebP images only.'), allowed.includes(file.mimetype));
  }
});

const loginLimiter = rateLimit({ windowMs: 15 * 60 * 1000, limit: 8, standardHeaders: 'draft-7', legacyHeaders: false, message: 'Too many login attempts. Please wait 15 minutes and try again.' });
const submissionLimiter = rateLimit({ windowMs: 60 * 60 * 1000, limit: 8, standardHeaders: 'draft-7', legacyHeaders: false });

function requireAdmin(req, res, next) {
  if (!req.session?.admin) return res.redirect('/admin/login');
  next();
}
function requireAdminCsrf(req, res, next) {
  const submitted = String(req.body?._csrf || '');
  const expected = String(req.session?.csrfToken || '');
  if (!submitted || !expected || submitted.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(submitted), Buffer.from(expected))) {
    return res.status(403).render('error', { title: 'Session check failed', message: 'Please reload the admin page and try again.' });
  }
  next();
}
function activeSchools(where = '', params = []) {
  const now = nowIso();
  return db.prepare(`SELECT *, CASE WHEN promotion_tier <> 'none' AND promotion_expires_at > ? THEN promotion_tier ELSE 'none' END AS active_promotion_tier
    FROM schools WHERE status = 'published' AND (expires_at = '' OR expires_at IS NULL OR expires_at > ?) ${where}
    ORDER BY CASE WHEN promotion_tier = 'vvip' AND promotion_expires_at > ? THEN 0 WHEN promotion_tier = 'vip' AND promotion_expires_at > ? THEN 1 ELSE 2 END,
    COALESCE(last_featured_at, '') ASC, name COLLATE NOCASE ASC`).all(now, now, now, now, ...params);
}
function featureRotation(rows, limit = 4) {
  const picked = rows.slice(0, limit);
  const update = db.prepare('UPDATE schools SET last_featured_at = ? WHERE id = ?');
  const now = Date.now();
  // The first item receives the newest timestamp, so the next request rotates to others.
  picked.forEach((row, index) => {
    if ((row.active_promotion_tier || row.promotion_tier) !== 'none') {
      update.run(new Date(now + (picked.length - index) * 1000).toISOString(), row.id);
    }
  });
  return picked;
}
function schoolBySlug(slug) {
  const now = nowIso();
  return db.prepare(`SELECT *, CASE WHEN promotion_tier <> 'none' AND promotion_expires_at > ? THEN promotion_tier ELSE 'none' END AS active_promotion_tier
    FROM schools WHERE slug = ?`).get(now, slug);
}
function expireListings() {
  db.prepare(`UPDATE schools SET status = 'expired', updated_at = ? WHERE status = 'published' AND is_seeded = 0 AND expires_at <> '' AND expires_at < ?`).run(nowIso(), nowIso());
}
expireListings();
setInterval(expireListings, 60 * 60 * 1000).unref();
setInterval(() => db.prepare('DELETE FROM sessions WHERE expires_at <= ?').run(Date.now()), 60 * 60 * 1000).unref();

async function createBackup() {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const destination = path.join(BACKUP_DIR, `schools-${stamp}.sqlite`);
  await db.backup(destination);
  const backups = fs.readdirSync(BACKUP_DIR).filter((name) => name.endsWith('.sqlite')).sort().reverse();
  for (const old of backups.slice(14)) fs.rmSync(path.join(BACKUP_DIR, old), { force: true });
  return destination;
}
// Keep a local rolling backup set. Render's disk snapshots are a separate recovery layer.
const backupTimer = setInterval(() => createBackup().catch((err) => logAdminError(err, 'scheduled-backup')), 24 * 60 * 60 * 1000);
backupTimer.unref();
setTimeout(() => createBackup().catch((err) => logAdminError(err, 'startup-backup')), 5000).unref();

app.get('/healthz', (_req, res) => res.json({ ok: true, service: 'schools-ke-platform', time: nowIso() }));

app.get('/', (req, res) => {
  const allCount = db.prepare("SELECT COUNT(*) AS count FROM schools WHERE status = 'published'").get().count;
  const schoolCount = db.prepare("SELECT COUNT(*) AS count FROM schools WHERE status = 'published' AND category = 'school'").get().count;
  const collegeCount = db.prepare("SELECT COUNT(*) AS count FROM schools WHERE status = 'published' AND category = 'college'").get().count;
  const universityCount = db.prepare("SELECT COUNT(*) AS count FROM schools WHERE status = 'published' AND category = 'university'").get().count;
  const featured = featureRotation(activeSchools(), 4);
  const vvip = featureRotation(activeSchools("AND promotion_tier = 'vvip' AND promotion_expires_at > ?", [nowIso()]), 3);
  res.render('home', { featured, vvip, counts: { allCount, schoolCount, collegeCount, universityCount } });
});

app.get('/schools', (req, res) => {
  const q = safeText(req.query.q, 120);
  const county = safeText(req.query.county, 80);
  const ownership = safeText(req.query.ownership, 40);
  const level = safeText(req.query.level, 60);
  const accommodation = safeText(req.query.accommodation, 40);
  const category = safeText(req.query.category, 30);
  const gender = safeText(req.query.gender, 40);
  const town = safeText(req.query.town, 80);
  const curriculum = safeText(req.query.curriculum, 100);
  const conditions = [];
  const params = [];
  if (q) { conditions.push('(name LIKE ? OR description LIKE ? OR town LIKE ? OR county LIKE ? OR ownership LIKE ? OR levels LIKE ? OR accommodation LIKE ? OR curriculum LIKE ?)'); params.push(...Array(8).fill(`%${q}%`)); }
  if (county) { conditions.push('county = ?'); params.push(county); }
  if (ownership) { conditions.push('ownership = ?'); params.push(ownership); }
  if (level) { conditions.push('levels LIKE ?'); params.push(`%${level}%`); }
  if (accommodation) { conditions.push('accommodation LIKE ?'); params.push(`%${accommodation}%`); }
  if (category) { conditions.push('category = ?'); params.push(category); }
  if (gender) { conditions.push('gender = ?'); params.push(gender); }
  if (town) { conditions.push('town LIKE ?'); params.push(`%${town}%`); }
  if (curriculum) { conditions.push('curriculum LIKE ?'); params.push(`%${curriculum}%`); }
  const where = conditions.length ? `AND ${conditions.join(' AND ')}` : '';
  const schools = activeSchools(where, params);
  const title = q ? `Search results for ${q} | SCHOOLS` : 'Find Schools, Colleges & Universities in Kenya | SCHOOLS';
  res.locals.metaTitle = title;
  res.locals.metaDescription = 'Search institution profiles across Kenya by county, town, ownership, educational level and boarding arrangement.';
  res.locals.canonical = `${SITE_URL}/schools`;
  if (Object.keys(req.query).length) res.locals.robots = 'noindex,follow';
  res.render('directory', { schools, filters: { q, county, ownership, level, accommodation, category, gender, town, curriculum }, title: 'Explore institutions', intro: 'Search schools, colleges and universities across Kenya.', counties: COUNTIES });
});

app.get('/directory/:category', (req, res) => {
  const category = ['school', 'college', 'university'].includes(req.params.category) ? req.params.category : 'school';
  const label = category === 'school' ? 'Schools' : category === 'college' ? 'Colleges & TVET institutions' : 'Universities';
  const ownership = safeText(req.query.ownership, 40);
  const county = safeText(req.query.county, 80);
  const level = safeText(req.query.level, 60);
  const accommodation = safeText(req.query.accommodation, 40);
  const conditions = ['AND category = ?'];
  const params = [category];
  if (ownership) { conditions.push('AND ownership = ?'); params.push(ownership); }
  if (county) { conditions.push('AND county = ?'); params.push(county); }
  if (level) { conditions.push('AND levels LIKE ?'); params.push(`%${level}%`); }
  if (accommodation) { conditions.push('AND accommodation LIKE ?'); params.push(`%${accommodation}%`); }
  const schools = activeSchools(conditions.join(' '), params);
  res.locals.metaTitle = `${ownership ? ownership + ' ' : ''}${label} in ${county || 'Kenya'} | SCHOOLS`;
  res.locals.metaDescription = `Explore ${ownership ? ownership.toLowerCase() + ' ' : ''}${label.toLowerCase()} in ${county || 'Kenya'}. Compare institution profiles, locations, courses, facilities and contact information.`;
  if (Object.keys(req.query).length) { res.locals.robots = 'noindex,follow'; res.locals.canonical = `${SITE_URL}/directory/${category}`; }
  res.render('directory', { schools, filters: { category, q: '', county, ownership, level, accommodation, gender: '', town: '', curriculum: '' }, title: `${ownership ? ownership + ' ' : ''}${label}${county ? ' in ' + county : ''}`, intro: `Discover ${label.toLowerCase()} and explore institution profiles across ${county || 'Kenya'}.`, counties: COUNTIES });
});

app.get('/:schoolKind-schools-in-:county', (req, res) => {
  const kind = req.params.schoolKind;
  if (!['private', 'public', 'boarding'].includes(kind)) return res.status(404).render('error', { title: 'Page not found', message: 'The requested education category was not found.' });
  const county = COUNTIES.find((name) => slugify(name) === req.params.county) || req.params.county.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const conditions = ['AND category = ?'];
  const params = ['school'];
  if (kind === 'private') { conditions.push('AND ownership = ?'); params.push('Private'); }
  if (kind === 'public') { conditions.push('AND ownership = ?'); params.push('Public'); }
  if (kind === 'boarding') { conditions.push('AND accommodation LIKE ?'); params.push('%Boarding%'); }
  conditions.push('AND lower(county) = lower(?)'); params.push(county);
  const schools = activeSchools(conditions.join(' '), params);
  const label = kind === 'private' ? 'Private schools' : kind === 'public' ? 'Public schools' : 'Boarding schools';
  res.locals.metaTitle = `${label} in ${county}, Kenya | SCHOOLS`;
  res.locals.metaDescription = `Explore ${label.toLowerCase()} in ${county}, Kenya. Compare available school profiles, locations, levels and admissions information.`;
  res.locals.canonical = `${SITE_URL}/${kind}-schools-in-${slugify(county)}`;
  res.render('directory', { schools, filters: { category: 'school', q: '', county, ownership: kind === 'private' ? 'Private' : kind === 'public' ? 'Public' : '', level: '', accommodation: kind === 'boarding' ? 'Boarding' : '', gender: '', town: '', curriculum: '' }, title: `${label} in ${county}`, intro: `Explore ${label.toLowerCase()} in ${county}, Kenya.`, counties: COUNTIES });
});

app.get('/schools-in-:county', (req, res) => {
  const county = COUNTIES.find((name) => slugify(name) === req.params.county) || req.params.county.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const schools = activeSchools('AND lower(county) = lower(?)', [county]);
  res.locals.metaTitle = `Schools and Institutions in ${county}, Kenya | SCHOOLS`;
  res.locals.canonical = `${SITE_URL}/schools-in-${slugify(county)}`;
  res.locals.metaDescription = `Explore schools, colleges and universities in ${county}, Kenya. Compare location, educational level, facilities and admissions contacts.`;
  if (schools.length < 3) res.locals.robots = 'noindex,follow';
  res.render('directory', { schools, filters: { category: '', q: '', county, ownership: '', level: '', accommodation: '', gender: '', town: '', curriculum: '' }, title: `Institutions in ${county}`, intro: `Explore education options in ${county}, Kenya.`, counties: COUNTIES });
});

app.get('/school/:slug', (req, res, next) => {
  const school = schoolBySlug(req.params.slug);
  if (!school || school.status !== 'published') return next();
  if (!school.is_seeded && school.expires_at && school.expires_at <= nowIso()) return next();
  db.prepare('UPDATE schools SET views = views + 1 WHERE id = ?').run(school.id);
  const related = activeSchools('AND id <> ? AND (county = ? OR category = ?)', [school.id, school.county, school.category]).slice(0, 4);
  res.locals.metaTitle = `${school.name} | ${school.town || school.county} | SCHOOLS`;
  res.locals.metaDescription = safeText(school.description || `Explore ${school.name}, including its location, school information and contact details.`, 160);
  res.locals.canonical = `${SITE_URL}/school/${school.slug}`;
  let photos = [];
  try { photos = JSON.parse(school.photos_json || '[]'); } catch { photos = []; }
  if (!photos.length && school.cover_path) photos = [school.cover_path];
  res.render('school', { school, related, photos, enquirySent: req.query.enquiry === 'sent' });
});

app.post('/school/:slug/enquiry', submissionLimiter, (req, res, next) => {
  try {
    const school = db.prepare("SELECT id, slug FROM schools WHERE slug = ? AND status = 'published' AND (expires_at = '' OR expires_at IS NULL OR expires_at > ?)").get(req.params.slug, nowIso());
    if (!school) return next();
    const name = safeText(req.body.name, 120);
    const message = safeText(req.body.message, 2000);
    if (!name || message.length < 10) return res.status(400).render('error', { title: 'Please complete the enquiry', message: 'Enter your name and a message of at least 10 characters.' });
    db.prepare('INSERT INTO enquiries (school_id, name, email, phone, message, created_at) VALUES (?, ?, ?, ?, ?, ?)')
      .run(school.id, name, safeText(req.body.email, 160), safeText(req.body.phone, 60), message, nowIso());
    audit('parent_enquiry_received', 'school', school.id, name);
    res.redirect(`/school/${school.slug}?enquiry=sent`);
  } catch (err) { logAdminError(err, req.originalUrl); next(err); }
});

app.get('/advertise', (req, res) => {
  res.locals.metaTitle = 'Advertise Your School | Reach Parents Across Kenya';
  res.locals.metaDescription = 'Create a school listing, showcase your campus, publish admissions information and reach parents and learners searching for institutions in Kenya.';
  res.render('advertise', { sent: req.query.sent === '1' });
});

app.post('/advertise', submissionLimiter, upload.array('photos', 6), (req, res) => {
  if (safeText(req.body.website_confirm, 150)) return res.redirect('/advertise?sent=1'); // honeypot
  const name = safeText(req.body.name, 160);
  if (!name) return res.status(400).render('error', { title: 'School name required', message: 'Please enter the institution name and submit again.' });
  const slugBase = slugify(name) || `institution-${Date.now()}`;
  const slug = `${slugBase}-${crypto.randomBytes(2).toString('hex')}`;
  const photos = (req.files || []).map((file) => `/uploads/${file.filename}`);
  const requestedTier = ['none', 'vip', 'vvip'].includes(req.body.requested_tier) ? req.body.requested_tier : 'none';
  const now = nowIso();
  db.prepare(`INSERT INTO schools (name, slug, category, ownership, levels, county, town, accommodation, gender, curriculum, fees_range, address, phone, email, website, description, cover_path, photos_json, video_url, trust_status, promotion_tier, requested_tier, status, source_note, is_seeded, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unverified', 'none', ?, 'pending', 'Submitted by an institution representative; awaiting review.', 0, ?, ?)`)
    .run(name, slug, safeText(req.body.category, 30) || 'school', safeText(req.body.ownership, 40), safeText(req.body.levels, 150), safeText(req.body.county, 80), safeText(req.body.town, 80), safeText(req.body.accommodation, 40), safeText(req.body.gender, 40), safeText(req.body.curriculum, 100), safeText(req.body.fees_range, 100), safeText(req.body.address, 250), safeText(req.body.phone, 60), safeText(req.body.email, 160), safeUrl(req.body.website), safeText(req.body.description, 2500), photos[0] || '', JSON.stringify(photos), safeUrl(req.body.video_url), requestedTier, now, now);
  audit('school_submitted', 'school', null, name);
  res.redirect('/advertise?sent=1');
});

app.get('/school-portal', (req, res) => {
  res.locals.metaTitle = 'Get a School Website & Portal | SCHOOLS';
  res.locals.metaDescription = 'Get a modern school website with admissions pages, galleries, announcements and an easy content dashboard.';
  res.render('portal', { sent: req.query.sent === '1' });
});

app.post('/school-portal', submissionLimiter, (req, res) => {
  const contactName = safeText(req.body.contact_name, 120);
  const institution = safeText(req.body.institution, 160);
  const phone = safeText(req.body.phone, 60);
  if (!contactName || !institution || !phone) return res.status(400).render('error', { title: 'Please complete the request', message: 'Enter your name, institution and phone number so we can follow up.' });
  db.prepare('INSERT INTO portal_enquiries (contact_name, institution, phone, email, message, created_at) VALUES (?, ?, ?, ?, ?, ?)')
    .run(contactName, institution, phone, safeText(req.body.email, 160), safeText(req.body.message, 1500), nowIso());
  audit('school_portal_enquiry_received', 'portal', null, institution);
  res.redirect('/school-portal?sent=1');
});

app.get('/campus-living', (req, res) => {
  const properties = db.prepare("SELECT * FROM properties WHERE status = 'published' ORDER BY created_at DESC LIMIT 30").all();
  res.locals.metaTitle = 'Student Accommodation, Hostels & Rentals in Kenya | SCHOOLS';
  res.locals.metaDescription = 'Explore student hostels, rental accommodation and campus-area services. Find places near colleges and universities.';
  res.render('campus', { properties, sent: req.query.sent === '1' });
});

app.post('/campus-living', submissionLimiter, (req, res) => {
  if (safeText(req.body.website_confirm, 150)) return res.redirect('/campus-living?sent=1');
  const title = safeText(req.body.title, 160);
  if (!title) return res.status(400).render('error', { title: 'Listing title required', message: 'Please enter a title for the accommodation listing.' });
  db.prepare('INSERT INTO properties (title, property_type, institution, county, town, price, contact, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
    .run(title, safeText(req.body.property_type, 80), safeText(req.body.institution, 160), safeText(req.body.county, 80), safeText(req.body.town, 80), safeText(req.body.price, 80), safeText(req.body.contact, 80), safeText(req.body.description, 1500), 'pending', nowIso());
  audit('property_submitted', 'property', null, title);
  res.redirect('/campus-living?sent=1');
});

app.get('/about', (_req, res) => res.render('about'));
app.get('/privacy', (_req, res) => res.render('privacy'));

app.get('/admin/login', (req, res) => {
  if (req.session?.admin) return res.redirect('/admin');
  res.locals.robots = 'noindex,nofollow';
  res.render('admin-login', { error: '' });
});

app.post('/admin/login', loginLimiter, async (req, res) => {
  const username = safeText(req.body.username, 120);
  const password = String(req.body.password || '');
  const expectedUser = process.env.ADMIN_USERNAME || 'admin';
  const userBytes = Buffer.from(username);
  const expectedBytes = Buffer.from(expectedUser);
  const validUser = userBytes.length === expectedBytes.length && crypto.timingSafeEqual(userBytes, expectedBytes);
  let validPassword = false;
  if (adminPasswordHash && password) validPassword = await bcrypt.compare(password, adminPasswordHash);
  else if (!IS_PROD) validPassword = password === 'admin12345';
  if (!validUser || !validPassword) {
    audit('admin_login_failed', 'admin', null, username);
    return res.status(401).render('admin-login', { error: 'Those login details did not match.' });
  }
  req.session.regenerate((err) => {
    if (err) { logAdminError(err, '/admin/login'); return res.status(500).render('admin-login', { error: 'Could not start a secure session. Please try again.' }); }
    req.session.admin = true;
    req.session.adminUsername = username;
    req.session.csrfToken = crypto.randomBytes(32).toString('hex');
    audit('admin_login', 'admin', null, username);
    res.redirect('/admin');
  });
});

app.post('/admin/logout', requireAdmin, requireAdminCsrf, (req, res) => req.session.destroy(() => res.redirect('/admin/login')));

app.get('/admin', requireAdmin, (req, res) => {
  res.locals.robots = 'noindex,nofollow';
  const schools = db.prepare("SELECT * FROM schools ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'expired' THEN 1 ELSE 2 END, created_at DESC LIMIT 100").all();
  const properties = db.prepare("SELECT * FROM properties ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC LIMIT 30").all();
  const errors = db.prepare('SELECT * FROM admin_errors ORDER BY id DESC LIMIT 12').all();
  const enquiries = db.prepare('SELECT e.*, s.name AS school_name FROM enquiries e LEFT JOIN schools s ON s.id = e.school_id ORDER BY e.id DESC LIMIT 20').all();
  const portalEnquiries = db.prepare('SELECT * FROM portal_enquiries ORDER BY id DESC LIMIT 20').all();
  const stats = {
    schools: db.prepare("SELECT COUNT(*) AS n FROM schools WHERE status = 'published'").get().n,
    pending: db.prepare("SELECT COUNT(*) AS n FROM schools WHERE status = 'pending'").get().n,
    expired: db.prepare("SELECT COUNT(*) AS n FROM schools WHERE status = 'expired'").get().n,
    properties: db.prepare("SELECT COUNT(*) AS n FROM properties WHERE status = 'pending'").get().n,
    enquiries: db.prepare('SELECT COUNT(*) AS n FROM enquiries').get().n
  };
  res.locals.metaTitle = 'Admin Dashboard | SCHOOLS';
  res.render('admin-dashboard', { schools, properties, errors, enquiries, portalEnquiries, stats });
});

app.post('/admin/schools/:id/approve', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  const expires = addMonthsDays(new Date(), 30);
  db.prepare("UPDATE schools SET status = 'published', posted_at = ?, expires_at = ?, last_renewed_at = ?, updated_at = ? WHERE id = ?")
    .run(nowIso(), expires, nowIso(), nowIso(), id);
  audit('school_approved', 'school', id, 'Published for 30 days');
  res.redirect('/admin');
});

app.post('/admin/schools/:id/renew', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  const expires = addMonthsDays(new Date(), 30);
  db.prepare("UPDATE schools SET status = 'published', expires_at = ?, last_renewed_at = ?, updated_at = ? WHERE id = ?")
    .run(expires, nowIso(), nowIso(), id);
  audit('school_renewed', 'school', id, 'Renewed for 30 days');
  res.redirect('/admin');
});

app.post('/admin/schools/:id/promotion', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  const tier = ['none', 'vip', 'vvip'].includes(req.body.promotion_tier) ? req.body.promotion_tier : 'none';
  const duration = [30, 60, 90].includes(Number(req.body.duration_days)) ? Number(req.body.duration_days) : 30;
  const promotionExpires = tier === 'none' ? '' : addMonthsDays(new Date(), duration);
  db.prepare('UPDATE schools SET promotion_tier = ?, promotion_expires_at = ?, last_featured_at = ?, updated_at = ? WHERE id = ?').run(tier, promotionExpires, '', nowIso(), id);
  audit('promotion_changed', 'school', id, `${tier} for ${tier === 'none' ? 0 : duration} days`);
  res.redirect('/admin');
});

app.post('/admin/schools/:id/trust', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  const trust = ['unverified', 'recognised', 'official'].includes(req.body.trust_status) ? req.body.trust_status : 'unverified';
  db.prepare('UPDATE schools SET trust_status = ?, updated_at = ? WHERE id = ?').run(trust, nowIso(), id);
  audit('trust_status_changed', 'school', id, trust);
  res.redirect('/admin');
});

app.post('/admin/properties/:id/approve', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  db.prepare("UPDATE properties SET status = 'published' WHERE id = ?").run(id);
  audit('property_approved', 'property', id);
  res.redirect('/admin');
});

app.post('/admin/properties/:id/hide', requireAdmin, requireAdminCsrf, (req, res) => {
  const id = Number(req.params.id);
  db.prepare("UPDATE properties SET status = 'hidden' WHERE id = ?").run(id);
  audit('property_hidden', 'property', id);
  res.redirect('/admin');
});

app.post('/admin/backup', requireAdmin, requireAdminCsrf, async (req, res) => {
  try {
    const file = await createBackup();
    audit('database_backup_created', 'database', null, path.basename(file));
    res.download(file);
  } catch (err) {
    logAdminError(err, '/admin/backup');
    res.status(500).render('error', { title: 'Backup failed', message: 'The database backup could not be created. The error has been recorded in the admin error log.' });
  }
});

app.post('/admin/errors/clear', requireAdmin, requireAdminCsrf, (req, res) => {
  db.prepare('DELETE FROM admin_errors').run();
  audit('admin_error_log_cleared', 'admin');
  res.redirect('/admin#errors');
});

app.get('/sitemap.xml', (req, res) => {
  const schools = db.prepare("SELECT slug, updated_at FROM schools WHERE status = 'published' AND (expires_at = '' OR expires_at IS NULL OR expires_at > ?)").all(nowIso());
  const fixed = ['/', '/schools', '/directory/school', '/directory/college', '/directory/university', '/advertise', '/school-portal', '/campus-living', '/about', '/privacy'];
  const countyPages = db.prepare("SELECT county FROM schools WHERE status = 'published' AND county <> '' AND (expires_at = '' OR expires_at IS NULL OR expires_at > ?) GROUP BY county HAVING COUNT(*) >= 3 ORDER BY county").all(nowIso()).map((r) => `/schools-in-${slugify(r.county)}`);
  fixed.push(...countyPages);
  const entries = fixed.map((url) => `<url><loc>${SITE_URL}${url}</loc></url>`).join('');
  const schoolEntries = schools.map((s) => `<url><loc>${SITE_URL}/school/${encodeURIComponent(s.slug)}</loc><lastmod>${new Date(s.updated_at).toISOString().slice(0, 10)}</lastmod></url>`).join('');
  res.type('application/xml').send(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${entries}${schoolEntries}</urlset>`);
});

app.get('/robots.txt', (_req, res) => res.type('text/plain').send(`User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: ${SITE_URL}/sitemap.xml\n`));

app.use((req, res) => res.status(404).render('error', { title: 'Page not found', message: 'The page may have moved, or the address may be incorrect.' }));
app.use((err, req, res, _next) => {
  logAdminError(err, req.originalUrl);
  const message = IS_PROD ? 'Something went wrong while processing your request. Please try again.' : safeText(err.message, 500);
  if (res.headersSent) return;
  res.status(500).render('error', { title: 'Something went wrong', message });
});

const server = app.listen(PORT, () => console.log(`SCHOOLS platform running on port ${PORT}; data directory: ${DATA_DIR}`));
function shutdown() {
  clearInterval(backupTimer);
  server.close(() => {
    try { db.pragma('wal_checkpoint(TRUNCATE)'); db.close(); } catch (err) { console.error(err); }
    process.exit(0);
  });
}
process.once('SIGTERM', shutdown);
process.once('SIGINT', shutdown);
