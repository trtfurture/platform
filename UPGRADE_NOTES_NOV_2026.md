# Kenya Schools platform upgrade

## Included
- Public copy cleanup: removed internal profile-photo explanations, exposed deployment credential wording and the public-facing source-note block on institution profiles.
- New Kenya Schools square brand/profile image used for PWA app icons, browser icon and social sharing.
- Admin workspace redesign with sidebar navigation and institution editing grouped into one expandable section, including editable profile fields and logo/cover-photo uploads.
- Privacy-conscious visitor analytics: random browser identifier, page views and popular paths. IP addresses are not stored. Admin pages, assets, health checks and telemetry endpoint are excluded.
- `/pulse_receiver` now accepts GET, POST and OPTIONS to stop legacy PWA clients from generating repeated 405 errors; matching old 405 log entries are cleared at startup.
- A public contact form feeding a dedicated administrator inbox, alongside institution and portal enquiries.\n- Admin-managed business contact and M-PESA payment instructions.
- Customer contact records are created when an institution or accommodation listing is submitted. VIP/VVIP requests create a fixed-price awaiting-payment record with selected duration; admins verify amount, M-PESA reference and status.
- SQLite backup, full JSON backup including uploaded media, and validated SQLite/JSON restore. Restore creates a safety backup before replacing the live database.
- Database migrations add new tables and owner references without dropping existing records.

## Deploy
1. Keep the existing Render persistent disk mounted at `/var/data` (or retain the existing `DATA_DIR` setting).
2. Replace the project files with this package and deploy using the existing Render service settings.
3. Do not delete `schools.sqlite`, `/var/data/uploads`, or `/var/data/backups`.
4. After deployment, sign in to `/admin`, check Visitors & traffic, then set business contact and M-PESA instructions under Contact & payment settings.
5. Download a JSON backup and store it off the Render disk.

## Important boundaries
- Customer records currently identify the person submitting a listing by phone number and connect their submissions and promotion requests. They are not yet password/OTP-protected self-service login accounts.
- M-PESA instructions are configurable and payment references/statuses can be recorded by the administrator. No automatic M-PESA STK Push or callback verification is included in this upgrade.
- The admin payment record is an operations ledger, not a payment gateway.
- Visitor counts are approximate: one browser cookie represents a visitor; clearing cookies or using another device can count as another visitor.
- Google ranking cannot be guaranteed. Technical SEO, metadata, schema, sitemap and internal linking support discovery, but rankings depend on relevance, quality, competition and reputation.


## November 20 experience and trust update
- Institution ratings and written reviews are available on public institution profiles. New submissions enter a pending moderation queue; only administrator-approved reviews affect the public average and become visible. Administrators can approve, reject or hide a previously approved review in `/admin` under Ratings & reviews.
- The homepage search now explains what visitors can search for, treats county as optional, labels nationwide search as “All counties”, and presents popular searches as noticeable shortcut chips.
- Directory filters include quick-discovery links and a help-centre path. A public `/help` page explains search, profile labels, reviews and cookie choices.
- A cookie banner offers Essential only, Accept all and Customize. Optional visitor analytics are not recorded unless the visitor opts in; IP addresses are still not stored in the analytics table. Cookie settings can be reopened from the page footer or the floating control.
- The new review table is created with a safe `CREATE TABLE IF NOT EXISTS` migration and is included automatically in SQLite and JSON backups. Existing institution, enquiry, payment and upload data are not intentionally removed.


## November 21 referral growth update
- Added a public KES 1,000 Invite & Earn programme for first eligible paid VIP/VVIP promotions by genuinely new referred institutions.
- Referral links use signed 30-day first-party attribution. Referral records attach to a new customer/institution submission; a click by itself does not earn a reward.
- Added a private partner dashboard with invite link, referred-school progress, pending/cleared rewards and payout totals. The private dashboard URL is a one-time bearer access link; partners must save it securely.
- Added admin controls for partner pause/reactivation, creating an advert payment record for a referred school that initially submitted a standard listing, conversion tracking, seven-day reward clearance, and manual M-PESA payout reference recording.
- Requires a verified advert payment reference before marking a paid promotion as paid. Refunded advert payments void unpaid rewards; refunds after a partner has been paid are flagged for review.
- Referral cookies, personal-data use and reward funding are disclosed in the programme and privacy notices. The school is not charged an extra referral fee.
- Existing SQLite databases are migrated additively with referral tables and payment linkage columns. No existing tables are intentionally dropped.
- Refined attribution for a newly referred administrator submitting more than one distinct institution through the same partner: later distinct schools remain eligible without duplicating the unique customer-account link. Pre-existing customer accounts and duplicate school name/county entries remain excluded.
- Added a copyable private dashboard URL to the post-registration success screen so partners can save their access link before leaving the page.


## November 21 fixed advertising prices
- Standard school/institution directory listing: free, subject to moderation and approval.
- VIP: KES 3,000 (30 days), KES 5,500 (60 days), KES 7,500 (90 days).
- VVIP: KES 6,000 (30 days), KES 11,000 (60 days), KES 15,000 (90 days).
- `/advertise#packages` displays package inclusions, duration prices and a live price preview in the institution submission form. `/help` includes the tariff.
- New promotion requests write the selected tier, duration and fixed amount to the payment ledger. Admin payment confirmation rejects amounts that do not match the tariff and requires a payment reference.
- When the payment is confirmed, the advert automatically activates if the institution is already published; if the listing is still pending, approval activates its paid advert. Existing promotion dates are not reset when a paid payment record is merely saved a second time.
- The same fixed tariff is used for administrator-created payment records for referred schools. KES 1,000 referral reward rules are unchanged. No online checkout or automatic M-PESA verification was added.
