# SCHOOLS — Kenya education discovery and institution marketing platform

A Toror Technology and Innovations Limited product. This project is a Python/Flask conversion of the supplied original Node/Express application. It uses HTML templates, CSS and vanilla JavaScript. It does not use Node.js, npm, React or a frontend build tool.

## Original public site and business functions retained

- Private-school and public-school directories.
- Colleges, TVET institutions and university directories.
- Kenya-wide search, county/category landing pages and the original search filters: keyword, institution type, county, ownership, education level, accommodation, gender, town and curriculum/programme.
- Institution profiles with details, image galleries, external campus-video links, official website links and parent/learner enquiry forms.
- Institution listing submissions with up to six JPG, PNG or WebP photographs (8 MB each), video URL and preferred promotion tier.
- Parent/learner enquiries saved for administrator review.
- School website/portal sales enquiry form.
- Student accommodation and campus-living marketplace submissions with administrator moderation.
- Admin login, rate limiting, CSRF protection, moderation, listing approvals and 30-day renewals.
- Recognition/confirmation and paid promotion remain separate: `unverified`, `recognised`, `official` trust states; `none`, `vip`, `vvip` promotions. Promotion durations remain 30, 60 and 90 days, with expiry.
- Admin dashboard with pending listings, published listings, enquiries, portal enquiries, property submissions, errors, backups and audit events.
- SQLite backups at startup and daily, with rolling retention and admin download.
- SEO titles/descriptions, canonical metadata, structured data, XML sitemap and robots.txt.
- PWA manifest, Android icons, service worker and offline fallback.

## Important sales scope

The original `/school-portal` feature is a **portal/website sales enquiry form**. It captures institution contact details and requirements for follow-up by Toror Technology. It is preserved. The original project does not contain an online portal checkout, M-PESA payment integration, automatic payment reconciliation, automated portal provisioning, school-owner self-service accounts, or a student/parent/teacher school-management system. This conversion does not pretend those functions already exist. Paid VIP/VVIP tiers are managed by an administrator after payment is confirmed outside the platform.

## Photographs

The supplied `school-hero.webp` was removed because it did not represent an authentic institution photograph. The homepage search hero now uses a real University of Nairobi entrance photograph. Matching real photographs are loaded for exact institution records where an open-licensed Commons photograph exists, including Alliance High School, University of Nairobi, Kenyatta University, Strathmore University, Mang'u High School, Kenya High School, KMTC Karen, JKUAT, Alupe University and Maseno School when those records already exist in the database. These images retain author/source and licence attribution in the interface. Images load directly from Wikimedia Commons; the application does not store copies of those Commons photographs in the ZIP. Photo mappings only match the exact corresponding institution slug. A university photograph is never assigned to the similarly named Strathmore School. The original five seeded profiles include no open-licensed exact-match photo currently confirmed for Strathmore School or Kenya Utalii College; those profiles use their initials rather than a generated or unrelated photo. See `PHOTO_SOURCES.md` for the source and licence register.

## Run locally

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set ADMIN_USERNAME and ADMIN_PASSWORD in .env
python app.py
```

Open `http://localhost:10000`. Administrator sign-in is at `/admin/login`. The local-only development fallback is disabled on Render.

## Render plan and persistent storage warning

The supplied `render.yaml` deliberately retains the original project's `starter` compute plan and its 1 GB `schools-data` persistent disk at `/var/data`. This is a paid Render configuration. It is required for the SQLite database, institution photo uploads, backup files and internally generated session-signing key to survive restarts and deployments.

Render Free web services cannot attach persistent disks. Their local files (including SQLite databases and uploads) are lost when a service spins down, restarts or redeploys. Free services also spin down after 15 minutes without traffic. Do not treat a Free instance with a local SQLite database as production storage for school submissions. If the current `schoolskenya` service still shows the Free plan, check the service's plan and disk before deploying this production configuration; do not sync a Blueprint or change billing settings without reviewing the cost first. Render reference: https://render.com/docs/free and https://render.com/docs/disks.

## Existing Render deployment — preserve your existing data

1. Replace the repository contents with this project and push to the same GitHub repository/branch already connected to the `schoolskenya` Render service.
2. Keep the existing Render service and its persistent disk. The database path remains `/var/data/schools.sqlite`, and uploaded images/backups remain under `/var/data`. Do not delete or detach the disk, and do not create a fresh service unless you also migrate the existing disk/database.
3. Set the service start command to `gunicorn app:app --workers 1 --threads 8 --timeout 120` if it is not already set. Build command: `pip install -r requirements.txt`. Runtime: Python.
4. In Render Environment, the only two application credentials you need to supply are `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The application creates its own private session-signing key file inside the persistent disk; there is no SESSION_SECRET or other third credential to enter in Render. Keep the persistent disk attached so admin sessions remain secure across restarts.
5. Check `/healthz`, the homepage, all four directory entry points, county filters, an existing institution profile, image submissions, enquiries, campus listings, `/school-portal`, admin login, admin approval and backup download.

The application uses the active request domain for canonical links, structured data, the sitemap and QR destination. The same code therefore works on the Render address before purchase and on the custom domain after DNS is connected. No PUBLIC_SITE_URL or DATA_DIR variable is needed.

## Data safety

- The Python schema and migrations retain the original SQLite tables and data fields. Existing schools, properties, enquiries, portal enquiries, admin logs, audit events and rows are not cleared or replaced. The app keeps the same `/var/data/schools.sqlite` database path on Render.
- The photo migration removes the old generic placeholder from all institution cover/gallery fields, then fills a photo only where there is an exact, rights-cleared institution match. It fills an empty cover/gallery on that matching record only. It does not overwrite a non-placeholder cover or an existing gallery. It does not create institutions or change their category, ownership, trust status, promotion, expiry or visibility.
- Keep one Render web instance using this SQLite database. Retain the persistent disk and configure a separate off-site backup for disaster recovery.

## Main routes

- `/` homepage
- `/schools` all-institution search
- `/directory/school`, `/directory/college`, `/directory/university` category directories
- `/school/<slug>` institution profile
- `/advertise` institution listing submission
- `/school-portal` school website/portal enquiry
- `/campus-living` accommodation listings and submissions
- `/admin/login`, `/admin` administrator login and dashboard
- `/sitemap.xml`, `/robots.txt`, `/healthz` search and service endpoints

© 2026 SCHOOLS. A product of Toror Technology and Innovations Limited.
