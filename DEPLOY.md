# The Docket — deploy guide (fresh repo: `mealplanner`)

This is a from-scratch setup for a brand new repo. Everything in this folder
is the whole app — copy the contents into the repo root and commit.

## Why you were getting a 404 / missing Action

Two separate issues from the old deploy, both fixed in this package:

- **404 at the site root.** GitHub Pages serves `index.html` automatically
  at `https://<user>.github.io/<repo>/`. The app was called `planner.html`,
  which only works if you type that exact filename — visiting the bare repo
  URL 404s. It's renamed to **`index.html`** now, so the root URL just works.
- **"Generate Weekly Prices" not showing up.** GitHub only lists workflows
  that exist in `.github/workflows/` **on the default branch**. If that
  folder/file wasn't committed and pushed to `main` yet, the Actions tab has
  nothing to show — it's not a naming issue, the workflow simply wasn't on
  the branch GitHub reads. Follow the steps below in order and it'll appear
  as **"Generate Weekly Prices"** (`.github/workflows/generate-prices.yml`).

## 1. Create the repo

- GitHub → New repository → name it exactly **`mealplanner`** → Public →
  create it empty (no README/license/gitignore, to avoid a merge step).

## 2. Push everything in this folder

```
cd mealplanner              # your local clone of the new repo
# copy every file/folder from this package in here, including the
# hidden .github folder, then:
git add -A
git commit -m "Initial deploy"
git push origin main
```

Double-check `.github/workflows/generate-prices.yml` actually made it into
the commit — `git status` should show it as tracked, and `git ls-files
.github` should list it. This is the step that was likely missed before.

## 3. Turn on GitHub Pages

Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch:
**main**, folder **/(root)** → Save. Wait ~1 minute, then the URL shown
there (`https://<user>.github.io/mealplanner/`) should load the app —
no `/index.html` needed.

## 4. Set the SaleFinder catalogue Variables (one-time)

These are fixed per store/region; only the two catalogue IDs change weekly
(and `SF_AUTO_RESOLVE=1`, set below, handles that automatically after one
good run).

```
gh variable set COLES_RETAILER_ID    --repo <you>/mealplanner --body "148"
gh variable set COLES_LOCATION_ID    --repo <you>/mealplanner --body "9045"
gh variable set WOOLIES_RETAILER_ID  --repo <you>/mealplanner --body "126"
gh variable set WOOLIES_LOCATION_ID  --repo <you>/mealplanner --body "22287"
gh variable set COLES_CATALOGUE_ID   --repo <you>/mealplanner --body "66233"
gh variable set WOOLIES_CATALOGUE_ID --repo <you>/mealplanner --body "66367"
gh variable set SF_AUTO_RESOLVE      --repo <you>/mealplanner --body "1"
```

Or just run `set-catalogue-vars.sh` (edit the `REPO=` line at the top first
if your GitHub username isn't `ianhay`).

## 5. Run the workflow once

Repo → **Actions** tab → you should now see **"Generate Weekly Prices"** in
the left sidebar (if it's not there, go back to step 2 — the workflow file
isn't on `main` yet) → **Run workflow** → Run.

Watch the log for:
```
[SaleFinder] Coles: N products / Woolworths: N products
[3/4] Pricing the ingredient catalogue (96 ingredients)...
[4/4] Costing every recipe against the priced catalogue...
```
On success it commits `week-data.json` to the repo, which Pages then serves.

## 6. Open the app

Visit `https://<user>.github.io/mealplanner/`, hard-refresh once (installs
the service worker), then Add to Home Screen / Install app on your phone.

--------------------------------------------------------------------------------

## File map

Repo root:
```
index.html                 the whole app (UI + selection engine + PWA)
generate-thisweek.py       weekly pricing job (prices ingredients, costs every recipe)
ingredients.json           canonical ingredient catalogue (~96 items, baseline prices)
recipes.json               48 recipes referencing ingredient slugs + quantities
convert_bank.py            one-off migration script — reference only, no need to run again
diagnose_week_data.py      sanity-checks a live week-data.json — run after any generator change
manifest.json, sw.js       PWA manifest + service worker
icon-*.png, apple-touch-icon.png
set-catalogue-vars.sh      convenience script for step 4
DEPLOY.md                  this file
HANDOFF.md                 full architecture writeup — read this before changing selection/pricing logic
```

Hidden:
```
.github/workflows/generate-prices.yml    the scheduled (Tue 22:00 UTC) + manual workflow
```

Created automatically by the workflow — don't add or edit by hand:
```
week-data.json              the full priced bank, regenerated every run
```

## Weekly Variables reference (all optional, sensible defaults)

```
SF_AUTO_RESOLVE=1   auto-detect the weekly catalogue id instead of the two
                    *_CATALOGUE_ID Variables above (recommended, set in step 4)
```

Dietary filtering, savings mode, dislikes and pantry-owned all live in the
app itself (Setup tab) — there's nothing else to configure server-side.

## Growing the recipe bank

Add entries to `recipes.json` referencing existing or new slugs in
`ingredients.json`. A new ingredient needs: `label`, `category`, `unit`
(`kg`/`L`/`ea`/`pack`), `baseline` (a sane $ estimate — the generator
overwrites this with a live search price when it can), `pantry` (true/false),
`store_pref` (`c`/`w`/`e`), and a few `search_terms`. No code changes needed —
the generator prices whatever's in the catalogue and the app costs whatever's
in the recipes.
