# SCHOOLS Render deployment checklist

- [ ] Replace the code in the existing GitHub repository and push to the connected branch.
- [ ] Confirm the service is on a paid plan that supports its `/var/data` persistent disk; the original Render spec uses Starter + a 1 GB disk. Free Render services cannot retain SQLite/uploads across spin-down or redeploy.
- [ ] Confirm Python runtime, `pip install -r requirements.txt`, and `gunicorn app:app --workers 1 --threads 8 --timeout 120`.
- [ ] Supply only `ADMIN_USERNAME` and `ADMIN_PASSWORD` as application credentials.
- [ ] Wait for `/healthz` to report `ok: true`.
- [ ] Verify Private schools, Public schools, Colleges & TVET, and Universities separately.
- [ ] Test county and directory filters.
- [ ] Open an existing school profile and confirm its existing gallery, video link and website link.
- [ ] Confirm photo attribution appears and no generic `school-hero.webp` photo is present; see `PHOTO_SOURCES.md`.
- [ ] Test a six-photo JPG/PNG/WebP institution submission.
- [ ] Test parent enquiry, campus accommodation submission and school-portal sales enquiry.
- [ ] Sign in to `/admin/login`; test moderation, trust status, VIP/VVIP controls and renewal.
- [ ] Download an admin SQLite backup and confirm audit/error information.
- [ ] Check `/sitemap.xml`, `/robots.txt`, PWA manifest and offline fallback.
- [ ] Confirm canonical links, sitemap and QR destinations use the Render hostname; after the custom domain is connected, confirm they use that domain automatically.
