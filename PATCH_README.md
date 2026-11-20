# SCHOOLS.co.ke visual and directory update

This is a replacement-only patch for the existing Render + GitHub project. It does not replace the database, uploads, backups, Render service, custom domain, or deployment plan.

## Apply

1. Extract this patch ZIP over the root of the existing GitHub repository, preserving the folder structure.
2. Commit and push the changed files. Render should redeploy the existing service.
3. The app performs safe SQLite migrations for photo attribution fields and adds missing public-information profiles on startup. Existing records with matching slugs are not overwritten, and records are not duplicated.
4. Keep the existing Render service and persistent-storage settings. This patch intentionally does not include `render.yaml` so it cannot change your current service plan or disk configuration.
5. If your repository still has a `SESSION_SECRET` entry in `render.yaml`, remove only that environment-variable entry; keep the existing plan and disk settings unchanged. Admin credentials remain `ADMIN_USERNAME` and `ADMIN_PASSWORD` only.
6. Delete the unused `static/images/school-hero.webp` file from GitHub if it still exists. It is no longer referenced. Also delete `hero-preview.png` if it exists in the repository root.

## What changes

- Removes arrow symbols from visible text throughout the public and admin templates, with a browser-side cleanup for any legacy or dynamically inserted arrow glyphs.
- Replaces the shared generated campus/hero image with clean CSS-only visual treatments. Profiles without an approved photograph use a typographic monogram, not a fake campus photo.
- Adds five real campus photographs from Wikimedia Commons for Alliance High School, Kenya High School, Mang'u High School, University of Nairobi and Kenyatta University. Each is linked to its source page and carries photographer/title/licence attribution (CC BY-SA 4.0).
- Uses a restrained Kenyan-flag colour marker, while clearly identifying SCHOOLS as an independent directory. It does not use the official coat of arms or imply government endorsement.
- Adds 116 public-information directory profiles: 24 established schools, 14 public TVET/specialist colleges, 36 public chartered universities, 33 private chartered universities and 9 university constituent colleges.
- The university list is based on the Commission for University Education publication dated 5 November 2026. The profiles remain independent directory entries, not CUE endorsements. TVET profiles link visitors to the TVETA register for current registration/licensing checks.
- Existing user-submitted institution records, admin workflows, promotions, enquiries, uploads, backups and other data are preserved.

## Important image note

The five credited campus images are served directly from Wikimedia Commons; the application itself remains hosted on Render. All other seeded institutions intentionally show a monogram until a real, properly authorised photograph is supplied. New institution submissions now explicitly request actual campus photographs only, not AI-generated or generic stock images.
