# Kenya Schools platform upgrade

## Included
- Public copy cleanup: removed internal profile-photo explanations, exposed deployment credential wording and the public-facing source-note block on institution profiles.
- New Kenya Schools square brand/profile image used for PWA app icons, browser icon and social sharing.
- Admin workspace redesign with sidebar navigation and institution editing grouped into one expandable section, including editable profile fields and logo/cover-photo uploads.
- Privacy-conscious visitor analytics: random browser identifier, page views and popular paths. IP addresses are not stored. Admin pages, assets, health checks and telemetry endpoint are excluded.
- `/pulse_receiver` now accepts GET, POST and OPTIONS to stop legacy PWA clients from generating repeated 405 errors; matching old 405 log entries are cleared at startup.
- A public contact form feeding a dedicated administrator inbox, alongside institution and portal enquiries.\n- Admin-managed business contact and M-PESA payment instructions.
- Customer contact records are created when an institution or accommodation listing is submitted. VIP/VVIP requests create an awaiting-quote payment record; administrators can update amount, M-PESA reference and payment status.
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
