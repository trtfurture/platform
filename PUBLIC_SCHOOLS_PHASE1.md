# Public senior-school directory import — Phase 1

This update includes a sourced list of **204 C1 senior schools** published by CBC Teachers Online on 29 September 2026. Source: https://cbc.co.ke/2026-c1-senior-schools-complete-list-of-national-schools-by-county/

The source states regional totals of 56 Rift Valley, 18 Western, 33 Eastern, 6 North Eastern, 31 Nyanza, 33 Central, 17 Coast and 10 Nairobi. The entries are marked as public because the source describes them as national C1 schools. This is a third-party published list, not an official Ministry of Education data dump. SCHOOLS marks the imported directory profiles `unverified` until an institution claims or confirms its own information.

The importer runs automatically on application startup and is additive/idempotent:
- Existing rows are never overwritten.
- Matching records are skipped.
- New rows are public, school-category, published directory entries with no invented images, contacts, websites, fees or boarding claims.
- Each row contains only school name, county and source-listed sub-county locality; gender is included where the source specifies it.
- Every new record keeps the source citation in `source_note`.

## About 76,000 school records

The often-quoted 76k–78k figures refer to a much broader mixed inventory (multiple school levels and institution types, public/private/unknown ownership and sources from different years), not 76,000 current public secondary schools. A SchoolRegistry Kenya source description reports 78,648 mixed education records and documents multiple source datasets; see https://schoolregistry.ke/ and https://schoolregistry.ke/methodology/. This update does **not** claim to import that mixed dataset or present it as a current official register.

## Images and display behaviour

- Homepage displays institutions with actual `cover_path` photographs first.
- Records without a real photograph are displayed only as text name and location; no initials artwork, generated images or generic stock images are used.
- Existing institution-uploaded photos are preserved.
- Existing gallery, school portal, enquiries, campus accommodation, advertising, admin moderation and promotion/payment-request workflows remain unchanged.
- Search dropdown contains all 47 counties.

## Deploy

Upload the replacement `app.py`, `templates/home.html`, `templates/partials/school-card.html`, `static/css/site.css` and the CSV to the existing GitHub project. No other files need replacing. The importer creates no duplicate when run again.
