# Schools.co.ke — launch checklist

## Before Render
- [ ] Confirm and register `schools.co.ke` with the registrar.
- [ ] Confirm the registered domain owner is the business / intended legal owner.
- [ ] Check the business name and logo for trademark conflicts.
- [ ] Push this project to a private GitHub repository.
- [ ] Keep `.env`, database files, uploads and backups out of Git.

## Render
- [ ] Create the service from `render.yaml` using Render Blueprint.
- [ ] Add a unique `ADMIN_USERNAME`.
- [ ] Add a long, unique `ADMIN_PASSWORD` (not the example value).
- [ ] Confirm the persistent disk is mounted at `/var/data`.
- [ ] Confirm `PUBLIC_SITE_URL=https://schools.co.ke`.
- [ ] Confirm `SIGNATURE_QR_URL=https://schools.co.ke` (or replace with the approved signature QR destination).
- [ ] Confirm `/healthz` returns `{ "ok": true }`.

## Domain and SSL
- [ ] Add `schools.co.ke` as a custom domain in Render.
- [ ] Optionally add `www.schools.co.ke` and configure the redirect/canonical preference.
- [ ] Copy Render's currently displayed DNS records exactly into the registrar DNS panel.
- [ ] Wait for Render to confirm DNS and issue HTTPS.
- [ ] Confirm HTTP redirects to HTTPS.
- [ ] Confirm canonical URLs and the QR destination use the live domain.

## Smoke tests
- [ ] Homepage loads on mobile and desktop.
- [ ] First deployment adds the public-information directory seed profiles without duplicating or overwriting existing institution records.
- [ ] University directory lists the CUE-seeded universities; college directory filters and county filters return results.
- [ ] Seeded institution cards show only attributed real photos or a non-photographic monogram placeholder.
- [ ] No arrow glyphs remain in visible navigation, links or buttons.
- [ ] Search works for name, location, ownership, level, boarding and category.
- [ ] Private and public school filters return the expected records.
- [ ] College and university pages work.
- [ ] Seeded school profiles and official website links work.
- [ ] Advertise form accepts approved image types and creates a pending submission.
- [ ] Multiple uploaded photos appear on the profile after approval.
- [ ] External video link opens safely.
- [ ] Portal enquiry appears in admin.
- [ ] Campus accommodation submission appears as pending in admin.
- [ ] Admin login accepts only the Render-configured credentials.
- [ ] Admin approval publishes a user-submitted listing for 30 days.
- [ ] White/brown trust status is independent from green/gold paid promotion.
- [ ] VIP ranks above ordinary results; VVIP is labelled and can appear in the global placement strip.
- [ ] Promotion expiry removes the paid badge/ranking.
- [ ] SQLite backup downloads and can be opened separately.
- [ ] `/sitemap.xml`, `/robots.txt` and `/healthz` return valid responses.
- [ ] Install prompt / Add to Home Screen is available on a supported Android browser.
- [ ] Offline fallback appears when the device is offline (cached shell only).

## Before public promotion
- [ ] Replace or expand seed institution data only from appropriate public/official sources.
- [ ] Verify school ownership and authority before setting brown Institution confirmed.
- [ ] Add a real company phone/email/contact channel.
- [ ] Complete privacy notice, terms, data retention and image consent process.
- [ ] Do not upload student photos without the required lawful basis and permissions.
- [ ] Configure off-site backups and uptime monitoring.
- [ ] Connect and test M-Pesa before advertising instant payment or automatic renewal.
