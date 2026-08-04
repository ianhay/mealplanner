# Meal Planner — Handoff & Orientation (v2)

A FODMAP-safe **weekly dinner planner** that builds a savings-weighted menu and
shopping list from this week's **Perth (WA) supermarket specials** (Coles +
Woolworths), then lets a household review, adjust, cost, and share it. Static
front-end + a weekly Python pricing job. No server, no accounts, no database.

This document is the single source of truth for how it works today. Read it
top to bottom before changing anything. It supersedes the v1 HANDOFF (the one
built around `recipe-bank.json` + `thisweek.json` + a server-side "pick 12").

--------------------------------------------------------------------------------
## 1. What changed from v1, and why

### v0.5.0 (this update)

- **Shopping list now shows quantities**, not just price — "700 g Chicken
  breast", "3× Free-range eggs", "1.5 L Coconut milk" — aggregated across
  every recipe in the week that uses the same ingredient, and correctly
  scaled by each recipe's people count before summing. `ea`-unit quantities
  round up (`Math.ceil`) for the *displayed* purchase quantity — you can't
  buy half an egg — while the underlying cost math still uses the exact
  scaled fraction, since that's the more honest price estimate.
- **Recipe view now shows an ingredient list**, scaled to that meal's people
  count, above the method steps — previously the "Recipe" expand only
  showed the method, never the ingredients or how much of each to use.
- Fixed a leftover **"THE DOCKET"** in the shopping-list receipt header
  (missed in the earlier rename pass because it was all-caps and the
  find/replace was case-sensitive) → **"SHOPPING LIST"**.
- Quantity formatting lives in one shared `formatQty(unit, qty)`, used by
  both the shopping list and the recipe view, so the two can't drift out of
  sync with each other.

### v0.4.3 (this update)

Traced the Woolworths 0%-live-coverage issue from the last update to its
root cause, using the Actions log plus a real live SaleFinder response the
user captured directly (proof the endpoint and retailer/location IDs were
never the problem — catalogue `66367` had simply expired).

- **Stale catalogue ID**: `WOOLIES_CATALOGUE_ID` was pinned to `66367`,
  which SaleFinder now returns 0 products for. The current one (at time of
  writing) is `66794`. This needs updating in the repo's Variables — code
  can't fix a stale external ID by itself.
- **`sf_resolve_catalogue_id` was silently useless for Woolworths**, and
  would have kept being useless every week: it requested catalogues
  `order=oldestfirst`, which is backwards for "give me the current one," and
  on finding no `saleId` in the response it returned `None` with no
  diagnostic output at all — so a real failure looked identical to "nothing
  to resolve." Fixed: `order=newestfirst`, a fallback scan of the whole
  response body (not just the `content` field) if the primary regex finds
  nothing, and — most importantly — real diagnostic output on every failure
  path (HTTP status, response length, first 200 characters) so a future
  failure is debuggable from the Actions log alone instead of a dead end
  requiring exactly this kind of manual investigation again.

### v0.4.2 (this update)

Found via the in-app diagnostics doing exactly what it's for: a real report
showed Coles at 70% live coverage and Woolworths at 0%, yet all three
shop-store totals were identical — a combination only possible if the store
split wasn't actually being applied.

- **`effectivePrice()` had a real bug.** When the chosen store had no live
  price for an ingredient, it fell back to the recipe's *blended* default
  instead of that store's own baseline. The blended default skews toward
  whichever store had more live matches — so with Woolworths at 0% live,
  "Shop at Woolworths" was silently showing Coles-flavoured numbers instead
  of Woolworths' own baseline estimate. Fixed in both `index.html` and the
  standalone `diagnose_week_data.py`, which had the identical bug in its own
  Python reimplementation of the same function — worth remembering that any
  logic duplicated between the app and the diagnostics script needs the same
  fix applied twice, since the diagnostics existing to catch the app's bugs
  doesn't help if it shares the bug.
- **Diagnostics sharpened**: the "Coles-only vs Woolworths-only" check now
  uses the live-coverage percentages (added in v0.4.1) to tell "identical
  totals because coverage happens to be similar at both stores" (fine, OK)
  apart from "identical totals despite coverage clearly differing" (a real
  bug, now FAIL rather than a vague WARN).

### v0.4.1

Added the live-coverage breakdown to diagnostics (structural `by_store`
presence vs an ingredient actually having a *live* price at each store),
after "100% carry by_store data" alone turned out not to distinguish "the
store split works" from "everything fell back to the same baseline at both
stores" — two very different situations that look identical from the
headline-total check alone.

### v0.4.0

- **Renamed "The Docket" → "Meal Planner"** everywhere user-facing (title,
  heading, PWA name, console log, share-sheet text). Internal-only names
  (localStorage key prefixes, the commit-bot's git identity) were left
  alone deliberately — renaming a localStorage key prefix would silently
  wipe anyone's saved plan/settings on upgrade.
- **Store totals weren't actually different** — traced to the same root
  cause as the v0.3.0 store-pricing fix not yet having taken effect: it's a
  *generator*-side fix, so it only applies once `generate-thisweek.py` runs
  again and republishes `week-data.json`. If you're still seeing identical
  Coles/Woolworths totals after this update, re-run the "Generate Weekly
  Prices" workflow — the in-app diagnostics (below) will tell you plainly if
  that's what's going on ("0% of ingredient rows carry by_store data").
- **A recipe showing $86.80 for 2 people** ("Easy night: oven-bake fish &
  steam-fresh veg") was a real gap: the plausibility guard added in v0.3.0
  only checked the *floor* (reject prices implausibly below baseline) and
  never checked the *ceiling* — so a wrong-product search match or a
  $/100g-read-as-$/kg mixup on the high side sailed straight through. Fixed:
  `_price_one_store` now rejects any live price outside baseline × 0.15–4.0,
  both directions. `diagnose_week_data.py` and the in-app diagnostics were
  updated to check both directions too — they'd have caught this on the
  published data even before the generator-side fix landed.
- **In-app diagnostics** (new): Setup tab → Diagnostics → "Run diagnostics".
  Runs the same checks as `diagnose_week_data.py`, but against the app's own
  live `weekTotals()`/`listItems()`/`effectivePrice()` — so it's checking
  exactly what's on screen, not a re-implementation that could itself drift
  out of sync. Produces a plain-text report with a "Copy result" button.
  This is the fastest path to reporting a pricing/total bug: run it, copy,
  paste.

### v0.3.0

Three real bugs, found from actual use, all fixed:

- **"Cheapest week" showing near-zero totals** turned out to be a *labelling*
  bug wearing a data-bug costume: the headline pill only ever showed money
  **saved**, never total **spend**. Cheapest-week mode deliberately doesn't
  chase discounts, so in a week where none of the 5 cheapest recipes happened
  to be on special, "$0.83 saved" was accurate — it just looked exactly like
  a broken total. Fixed by showing both figures, clearly labelled, in
  `renderHero()`.
- **Headline vs List total mismatch** was the same root cause — once the
  hero pill shows total spend (not savings), it reconciles with the List tab
  by construction, because both now go through the same `effectivePrice()`
  helper (see below). There's a standing regression test for this in
  `diagnose_week_data.py` (`check_hero_list_reconciliation`).
- **"Shop at Coles/Woolworths" not doing anything real.** `price_ingredient_catalogue`
  used to search Coles, and only checked Woolworths if Coles had zero
  matches — so nearly every ingredient's "price" was really "whatever price
  Coles happened to have," regardless of the `store_pref` label attached to
  it. Switching to "Shop at Woolworths" just relabelled the same numbers
  under a different heading. Fixed: every ingredient is now priced at
  **both** stores independently (`_price_one_store` called for `coles` and
  `woolworths`), stored as `by_store: {c:{...}, w:{...}}` alongside the
  blended default. The app's `effectivePrice()` picks the real store-specific
  price when the household has chosen one store; `diagnose_week_data.py`'s
  `check_single_store_actually_differs` guards against this regressing
  (it would show identical Coles/Woolworths totals, same as the actual bug).
- Also added a plausibility guard in the generator: any live search-derived
  price under 15% of the ingredient's bank baseline is now rejected rather
  than published (catches the parsing-glitch class of bug before it reaches
  `week-data.json` at all).
- **Visual restyle** to the Ian Hay cobalt-blue/signal-orange system: Barlow
  Condensed headings, IBM Plex Sans body, IBM Plex Mono for the version tag
  and receipt, 4px radii on components (999px reserved for chips/tags/status),
  blue for navigation and primary actions, orange reserved for "on special"
  meals and the savings figure. Added `prefers-color-scheme: dark` support.
  Fixed a day-row wrap bug (Sun dropping to its own line on narrow phones) as
  a side effect of the CSS pass.
- **`diagnose_week_data.py`** (new): run it against any `week-data.json`
  (local file or live URL) to catch all three bug classes above before they
  reach the app. See §11.

### v0.2 → v1, structural history

v1 picked twelve recipes server-side (scored by *category*-level discount —
every chicken recipe scored identically off the deepest chicken special
anywhere in the catalogue), priced only those twelve, and shipped a frozen
week. Two structural problems fell out of that:

- **Selection ran before pricing existed**, so it could only ever be as
  accurate as a category-level guess — never the recipe's own ingredients.
- **The no-repeat window ate the bank.** 48 recipes ÷ 12/week, held back 28
  days → by week four there were exactly 12 candidates for 12 slots. The
  "savings vs cheapness" dial had nothing left to choose between.

v2 inverts the order: **price the ~100-ingredient catalogue once, cost the
whole recipe bank for free, and let the app select.** Concretely:

- `recipe-bank.json` (prices baked into each recipe) → **`ingredients.json`**
  (canonical, priced) + **`recipes.json`** (recipes reference ingredient slugs
  + real quantities, no prices).
- `generate-thisweek.py` no longer picks a week. It prices every ingredient
  once (same request budget as before — a few dozen searches — because it now
  scales with the *ingredient* count, not the *selected-recipe* count) and
  publishes **`week-data.json`**: the full bank, every recipe costed and
  savings-annotated.
- `index.html` picks the week **client-side**, live, with four savings
  modes, a proper Swap sheet (ranked alternatives, not blind cycling), a
  savings hero banner, a dislikes list, and a pantry-owned checklist.
- `history.json` / server-side no-repeat is gone. The week itself already
  lives in the browser (localStorage) or a share-link; a second recency
  ledger was a moving part without a capability behind it.

Data flow:
```
catalogues (SaleFinder) ──┐
                          ├─► price every ingredient ─► cost every recipe ─► week-data.json ─► index.html
ingredients.json,          │                                                                    (picks the week,
recipes.json ──────────────┘                                                                     live, in-browser)
```

--------------------------------------------------------------------------------
## 2. Repo layout

Root (served by GitHub Pages):
- `index.html`            the entire app (UI + selection engine + PWA), single file
- `generate-thisweek.py`    the weekly pricing job (no longer a selector)
- `ingredients.json`        ~96 canonical ingredients: label, category, unit, baseline $, pantry flag, store preference, search terms
- `recipes.json`            48 recipes referencing ingredient slugs + quantities (no prices)
- `convert_bank.py`         one-off migration script (v1 `recipe-bank.json` → `ingredients.json` + `recipes.json`) — reference only, already run
- `week-data.json`          GENERATED weekly — the full priced bank
- `manifest.json`, `sw.js`  PWA manifest + service worker (cache bumped to v2)
- icons
- `set-catalogue-vars.sh`   convenience script (sets Actions Variables via gh CLI)
- `DEPLOY.md`                concise deploy map + Variable list
- `HANDOFF.md`               this file

Hidden:
- `.github/workflows/generate-prices.yml`   the scheduled + manual workflow

Retired (no longer produced or read): `recipe-bank.json`, `thisweek.json`, `history.json`.

Never hand-edit `week-data.json`; the job owns it.

--------------------------------------------------------------------------------
## 3. The ingredient catalogue (`ingredients.json`)

```
{
  "version": 1,
  "ingredients": {
    "chicken_breast": {
      "label": "Chicken breast", "category": "chicken", "unit": "kg",
      "baseline": 16.0,          // used until a live price is found; then overwritten each run
      "pantry": false,           // pantry items are excluded from hero candidacy and can be
                                  // marked "owned" in the app to drop out of the shopping total
      "store_pref": "c",         // which store's list this lands under in "Shop at Both" mode
      "search_terms": ["breast", "chicken"],
      "occurrences": 8           // how many v1 recipes used it (provenance only, not read by code)
    }, ...
  }
}
```

`unit` is one of `kg` / `L` / `ea` / `pack`. `kg`/`L` ingredients get priced
per-kilogram/per-litre and scaled by the recipe's quantity; `ea` ingredients
(eggs, limes, bok choy) are priced per-item; `pack` is a flat shelf price used
as-is (jars, bottles, whole items sold each rather than by weight).

**Known limitation:** a handful of ingredients that are recorded with a
weight in the source recipe but are actually sold "each" on special (whole
chicken, whole lettuce) inherited a `kg` unit from the conversion. Worth a
manual pass — see §8.

--------------------------------------------------------------------------------
## 4. Recipes (`recipes.json`)

```
{
  "id": "roast-chicken-root-veg", "name": "roast chicken & root veg",
  "desc": "...", "serves": 2,
  "diet": {"low_fodmap": true, "gluten_free": true, "lactose_free": true},
  "hero": "whole_chicken",              // the ingredient selection scores/labels this recipe by
  "nut": {"kj":2700,"prot":48,"fib":7,"carb":35}, "waste": "...",
  "steps": ["...", "..."],
  "ingredients": [
    {"ing":"whole_chicken","qty":1700.0,"unit":"g","role":"hero","note":"carcass → stock"},
    {"ing":"wa_white_potatoes","qty":2000.0,"unit":"g","role":"shared","note":"shared 3 meals"},
    {"ing":"thyme_fresh","qty":null,"unit":"pack","role":"pantry","note":"dries well"}
  ]
}
```

`role` drives both selection and client-side scaling:
- **`hero`** — the ingredient the recipe is selected/scored/labelled by (one
  per recipe, picked by protein priority: beef > lamb > pork > duck > chicken
  > seafood > legume > egg, skipping pantry items like beef stock so a stock
  cube can never outrank the actual protein).
- **`scales`** — ordinary ingredients; cost scales with people ÷ serves.
- **`shared`** — bag/bunch items explicitly noted as shared across meals
  (bok choy bunch, potato bag); priced once per recipe, not re-scaled per
  person, since the recipe's quantity already accounts for reuse.
- **`pantry`** — condiments, oils, pastes, stock; can be marked "owned" in
  the app to drop out of the shopping total.

--------------------------------------------------------------------------------
## 5. The generator pipeline (`generate-thisweek.py`)

1. **Load** `ingredients.json` + `recipes.json`.
2. **Fetch catalogues** (unchanged from v1 — SaleFinder svgData + per-item
   search, same two endpoints, same token/saleGroup handling).
3. **Price every ingredient once** (`price_ingredient_catalogue`): for each
   ingredient, search both stores using its `search_terms`, convert the best
   match into a genuine per-unit price ($/kg, $/L, $/ea or $/pack — not a
   price scaled to any one recipe's portion), falling back to the bulk
   svgData pool, then to the ingredient's `baseline` estimate (flagged
   `est`). This is the step that used to happen per-selected-recipe; doing it
   once per ingredient is what makes the whole bank costable for free, and
   the request budget scales with ~100 ingredients rather than with however
   many recipes get selected.
4. **Cost every recipe** (`annotate_recipes`): for each recipe, sum its
   ingredients' live prices (scaled by qty/role) into `cost`,
   `cost_per_serve`, `saving`, `saving_pct`, and `hero_on_special`. Every
   recipe in the bank gets this — not a pre-selected twelve.
5. **Write `week-data.json`**: metadata + the full priced `ingredients` +
   the full costed `recipes`. The app selects from this.

Matching notes (unchanged from v1): brand/region words are stripped and
plurals unified for catalogue matching.

--------------------------------------------------------------------------------
## 6. `week-data.json` schema (what the planner consumes)

```
{
  "schema": 2,
  "metadata": {
    "generated", "week_start", "week_end",
    "coles_saleid","coles_url","woolies_saleid","woolies_url",
    "catalogue_start","catalogue_end",
    "ingredients_matched","ingredients_total",
    "recipes_on_special","total_possible_saving", "note"
  },
  "ingredients": { ...same shape as ingredients.json, prices refreshed... },
  "recipes": [
    {
      ...same fields as recipes.json...,
      "priced_ingredients": [
        {"ing","label","qty","unit","role","note","now","was","flag"}
      ],
      "cost", "cost_per_serve", "saving", "saving_pct", "hero_on_special"
    }
  ]
}
```

--------------------------------------------------------------------------------
## 7. The planner (`index.html`)

Single file: HTML + CSS (custom-property theme, unchanged visual identity) +
vanilla JS. Three tabs — **1 Meals** (landing tab), **2 List**, **3 Setup** —
reordered so the thing people open the app for is what they see first.

- **Selection engine** (`selectWeek`): scores every recipe in the filtered
  pool on the active savings mode, greedily builds the week honouring
  protein diversity (no back-to-back category, max 3/category) and a small
  **basket bonus** — a candidate sharing a non-hero ingredient with an
  already-picked recipe this week scores ~12% higher, nudging selection
  toward genuinely shared shopping (the "2kg potato bag split three ways"
  pattern the recipe bank already documents in `waste` notes but v1 never
  modelled).
- **Four savings modes** (Setup tab, instant reshuffle on change):
  **Balanced** (0.45·%off + 0.35·$/serve + 0.20·cheapness, all pool-relative
  normalised), **Deepest discount** (maximise `saving_pct`), **Most $ saved**
  (maximise `saving`/serve), **Cheapest week** (minimise `cost_per_serve`).
- **Savings hero banner**: total $ + % saved this week, plus the single best
  deal, shown at the top of the Meals tab instead of buried in Setup.
- **Swap sheet** (tap "↻ Swap" on any meal): a ranked, filterable-by-protein
  sheet of alternatives from the *entire* pool (not a blind next-index
  cycle), sorted by the active savings mode, each row showing $/serve and
  % saved.
- **Dislikes** (Setup): protein-category chips; excluded from both
  selection and the swap sheet.
- **Pantry checklist** (Setup + List): tap a pantry ingredient to mark it
  owned; it strikes through and drops out of the shopping total everywhere,
  persisted across weeks.
- **List tab**: shopping list aggregated by ingredient within store (not
  repeated per-meal), was/now prices, per-item + total savings, Woolworths
  online-delivery threshold helper.
- **Custom recipes** ("+ Add a meal to the bank"): unchanged from v1 — type
  a recipe or paste a URL (schema.org Recipe JSON-LD via a CORS proxy).
  Custom recipes don't reference the ingredient catalogue, so they don't
  scale with the people count and aren't scored for savings the way bank
  recipes are — they're priced by whatever you type.
- **Share plan**: unchanged mechanism (recipe IDs + settings encoded in the
  URL hash), extended to carry savings mode and dislikes too.
- **PWA**: installable, network-first service worker (cache bumped to v2).

localStorage keys: `docket_settings_v2` (mode/days/people/day/store/diet/
dislikes), `docket_plan_v2`, `docket_pantry_v2`, `docket_custom_recipes_v2`,
`docket_proxy`.

If `week-data.json` fails to load, the planner shows a tiny demo dataset.

--------------------------------------------------------------------------------
## 8. Known limitations / gotchas (read before "improving")

- **Whole-item units.** A few ingredients (whole chicken, and likely a couple
  of others) were converted with a `kg` unit because the source recipe
  recorded a weight, but catalogues often advertise them "each". Worth a
  manual override pass in `ingredients.json` (change `unit` to `ea` for the
  handful that are genuinely each-priced) — low effort, meaningfully improves
  pricing accuracy for those items.
- **Savings depend on catalogue data.** Nothing shows a saving until a NEW
  `week-data.json` exists with live `was` prices; an old file has none.
- **Single-store mode estimates.** Forcing one retailer keeps the other
  store's items priced at whatever was found (flagged), not necessarily that
  store's own price.
- **Share = snapshot**, not live sync. Re-share after changes.
- **Custom recipes don't scale.** They carry flat prices you typed, so the
  people-count stepper doesn't rescale them the way it does bank recipes.
- **Basket-sharing is per-recipe, not cross-recipe.** The `shared` role
  amortises a bag/bunch *within* a recipe's own note; the List tab doesn't
  yet deduplicate, say, "ginger knob" if it's bought fresh in three different
  recipes the same week — it aggregates by ingredient+store but sums rather
  than caps at "you only need to buy this once." True unit-rounding
  (you still need to buy a whole lime even if two recipes use "half") is a
  genuinely fiddly follow-on, not attempted here.
- **Protein detection is keyword-based** (ingredient base name). An unusual
  protein name may fall into "other" and won't get a hero, though the
  converter's priority list (beef > lamb > pork > duck > chicken > seafood >
  legume > egg, pantry items excluded) now covers all 48 current recipes
  correctly — verify new recipes' `hero` field when adding them by hand.

--------------------------------------------------------------------------------
## 9. Ideas to build on (backlog)

- **Grow the bank via recipe "families"** — one base (stir-fry, traybake,
  braise, curry, pasta) with a swappable hero slot. ~40 bases × 3–4 proteins
  ≈ 140 recipes without authoring 140 from scratch, and it's the ideal shape
  for savings selection (the hero binds to whatever's actually discounted).
- **Cross-recipe basket deduplication** in the List tab — sum quantities of
  the same ingredient across the week's meals before re-pricing, rather than
  aggregating cost per (recipe, ingredient) pair.
- **Whole-item unit overrides** (§8) — quick, meaningfully improves pricing
  on the handful of each-priced bulk items.
- **Custom recipes join the ingredient catalogue** — let a typed/imported
  recipe reference existing slugs (with a "new ingredient" escape hatch) so
  it scales with people and gets scored for savings like a bank recipe.
- **Nutrition/budget targets** — weekly $ cap or protein/fibre goals as
  additional soft constraints in `selectWeek`.

--------------------------------------------------------------------------------
## 10. Diagnostics (`diagnose_week_data.py` + in-app)

Two ways to run the same checks:

- **In-app** (fastest): Setup tab → Diagnostics → **Run diagnostics** →
  **Copy result**. Runs against the app's own live functions and the
  currently-loaded week + plan, so it's checking exactly what's on screen.
- **Standalone script**, against a local file or the live URL:

```
python3 diagnose_week_data.py week-data.json
python3 diagnose_week_data.py https://ianhay.github.io/mealplanner/week-data.json

```

It re-simulates the app's own `effectivePrice` / cost / list-aggregation
logic in Python (not just spot-checking fields), so it catches the same
class of mismatch a human would only notice by comparing two numbers on
screen. Checks: schema references resolve; no recipe or ingredient priced
implausibly low; every priced ingredient carries real `by_store` data;
headline total reconciles with list total in all three shop-store modes;
Coles-only and Woolworths-only totals genuinely differ for a sample week.
Exit code is 1 if anything fails — safe to wire into the GitHub Actions
workflow as a post-generation step if you want a bad week blocked from
publishing rather than just flagged.

## 11. Where to start a review

1. Deploy as-is (see `DEPLOY.md`) and run the workflow once. Read the log —
   step `[3/4]` should report most of the ~96 ingredients priced live.
2. Open the app; it should land on **Meals** with a savings banner already
   populated. Try each savings mode in Setup and watch the week reshuffle.
   Try Swap on a meal, a dislike chip, marking a pantry item owned.
3. Open `week-data.json` and spot-check a recipe's `priced_ingredients`
   against `ingredients.json` — confirm `now`/`was` look sane for a
   known-cheap and a known-expensive recipe.
4. Then pick from §9. Recipe-family expansion is the highest-value,
   lowest-risk lever, same as it was in v1 — it's just far more valuable now
   that every recipe in the bank is actually priced and selectable, not just
   whichever twelve the server happened to pick.
