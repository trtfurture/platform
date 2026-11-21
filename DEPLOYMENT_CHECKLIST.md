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
- [ ] Open `/advertise#packages` and verify Standard is free, VIP is KES 3,000 / 5,500 / 7,500 and VVIP is KES 6,000 / 11,000 / 15,000 for 30 / 60 / 90 days.
- [ ] Test the live price preview by switching between Standard, VIP and VVIP and changing the duration.
- [ ] Test a six-photo JPG/PNG/WebP institution submission.
- [ ] Test parent enquiry, campus accommodation submission and school-portal sales enquiry.
- [ ] Sign in to `/admin/login`; test moderation, trust status, VIP/VVIP controls and renewal.
- [ ] Download an admin SQLite backup and confirm audit/error information.
- [ ] Check `/sitemap.xml`, `/robots.txt`, PWA manifest and offline fallback.
- [ ] Confirm canonical links, sitemap and QR destinations use the Render hostname; after the custom domain is connected, confirm they use that domain automatically.

- [ ] After deploying the referral update, open `/invite-and-earn`, register a test partner with a test mobile number and save the one-time private dashboard URL. Test a referral in a separate browser/device using the generated `/r/<code>` link.
- [ ] Submit a test school through `/advertise`, request VIP/VVIP, confirm that the admin payment record is linked to the correct referral, and test the manual payment status flow using a clearly identified test record. Do not pay a real reward during testing.
- [ ] In production, verify the exact package amount and advert payment in the business M-PESA account before marking it paid; the admin ledger must reject an amount that differs from the selected tariff. Once the seven-day clearance has passed, send the reward manually and record the M-PESA transaction reference in `/admin` → Invite & earn.
- [ ] The lowest paid package is KES 3,000, leaving KES 2,000 after the KES 1,000 referral reward before operating costs and applicable taxes. Confirm the final tax and margin treatment before publicly scaling partner payouts.
