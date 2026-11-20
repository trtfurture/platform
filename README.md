# SCHOOLS — Schools.co.ke

**A Toror Technology and Innovations Limited product.**

This release is converted to a Render-native Python/Flask backend with plain HTML (Jinja templates), CSS and vanilla JavaScript. There is no Node.js, npm, React, EJS or JavaScript build step.

## Deploy to Render using GitHub
1. Push the contents of this folder to your GitHub repository.
2. In Render choose **New → Blueprint**, connect the repository and apply `render.yaml`.
3. Supply a unique `ADMIN_USERNAME` and strong `ADMIN_PASSWORD`; Render generates `SESSION_SECRET`.
4. Keep the persistent disk mounted at `/var/data`. SQLite, uploads, rolling backups and Flask sessions live there.
5. Set `PUBLIC_SITE_URL` to the final HTTPS domain, attach `schools.co.ke` in Render and copy the exact DNS records Render displays.
6. Check `/healthz`, then test public search, submissions, admin login, approvals and backup download.

## Local run
Python 3.11+ recommended.
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate ; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env and set variables (or export them in your shell)
python app.py
```

Admin: `/admin/login`. Development fallback is `admin` / `admin12345` only outside production when no password is configured. Never use it on a public deployment.

## Preserved functionality
- Kenya-wide school, college/TVET and university discovery, county/category landing pages and all search filters.
- Institution profiles, gallery, video and external official website links; parent enquiries.
- Multi-image submissions (JPG/PNG/WebP, max six, 8MB each), portal requests and campus accommodation submissions.
- Admin authentication, rate-limited sign-in, CSRF checks, review queue, approvals, 30-day renewal, trust status, VIP/VVIP paid promotion and expiry.
- Admin dashboard, enquiries, error/audit logs, SQLite backup download and rolling backup retention.
- SEO metadata, canonical URLs, structured data, sitemap, robots, PWA manifest, service worker, offline page and supplied images/icons.

## Render storage note
A persistent disk is required for SQLite, uploads, backups and filesystem sessions. Use one web instance with this SQLite deployment. Do not remove the disk or deploy multiple app instances sharing this SQLite database. Configure off-site backups as an additional recovery layer.

## Features that were not present in the source
Live M-Pesa, automatic payment reconciliation, self-service school-owner accounts, full student/parent/teacher portal logins, video hosting/transcoding and automated email/SMS were not implemented in the source ZIP and are not claimed as completed here.
