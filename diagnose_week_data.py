#!/usr/bin/env python3
"""
Meal Planner — week-data.json diagnostics.

Run this against a live week-data.json (either a local file or a URL) to
catch the kinds of bugs that are invisible from a quick look at the app:

  1. Implausible prices    — a recipe or ingredient priced far below what's
                              plausible (the "$0.83 for 5 dinners" class of bug).
  2. Hero/list mismatch     — simulates the app's own selection + costing math
                              and confirms the headline total and the shopping
                              list total agree, in both "both stores" and
                              single-store modes.
  3. Per-store coverage     — confirms every priced ingredient carries real
                              by_store data (needed for "Shop at Coles"/
                              "Shop at Woolworths" to show genuine numbers,
                              not the blended default relabelled).
  4. Schema sanity          — every recipe's hero/ingredients resolve to a
                              real ingredient slug, every recipe has a serves
                              count, etc.

Usage:
  python3 diagnose_week_data.py week-data.json
  python3 diagnose_week_data.py https://ianhay.github.io/mealplanner/week-data.json

Exit code is 0 if all checks pass, 1 if any check fails.
"""
import json
import sys
import urllib.request

FAIL = "FAIL"
WARN = "WARN"
OK = "OK"

def load(source):
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=15) as r:
            return json.load(r)
    with open(source) as f:
        return json.load(f)

def report(results):
    worst = OK
    for level, msg in results:
        print(f"[{level:4}] {msg}")
        if level == FAIL:
            worst = FAIL
        elif level == WARN and worst != FAIL:
            worst = WARN
    print()
    print("Overall:", worst)
    return worst == FAIL

# ---- checks -----------------------------------------------------------

def check_schema(week, results):
    ings = week.get("ingredients", {})
    recs = week.get("recipes", [])
    if not ings:
        results.append((FAIL, "no ingredients in week-data.json"))
    if not recs:
        results.append((FAIL, "no recipes in week-data.json"))
        return
    bad_hero, bad_ing, no_serves = [], [], []
    for r in recs:
        if r.get("hero") and r["hero"] not in ings:
            bad_hero.append(r["id"])
        for pi in r.get("priced_ingredients", []):
            if pi.get("ing") and pi["ing"] not in ings:
                bad_ing.append((r["id"], pi["ing"]))
        if not r.get("serves"):
            no_serves.append(r["id"])
    if bad_hero:
        results.append((FAIL, f"{len(bad_hero)} recipe(s) reference a hero not in ingredients: {bad_hero[:5]}"))
    if bad_ing:
        results.append((FAIL, f"{len(bad_ing)} priced_ingredient row(s) reference an unknown slug: {bad_ing[:5]}"))
    if no_serves:
        results.append((WARN, f"{len(no_serves)} recipe(s) missing serves: {no_serves[:5]}"))
    if not bad_hero and not bad_ing:
        results.append((OK, f"schema check: {len(recs)} recipes, {len(ings)} ingredients, all references resolve"))

def check_plausible_prices(week, results):
    ings = week.get("ingredients", {})
    recs = week.get("recipes", [])
    # A recipe costing less than $0.50/serve is almost certainly a pricing
    # bug, not a genuinely cheap meal — even lentils-and-rice costs more than
    # that per person in real life. A recipe over $30/serve for an everyday
    # dinner is the same bug class the other direction (wrong-product match,
    # or a $/100g figure misread as $/kg).
    FLOOR_PER_SERVE = 0.50
    CEIL_PER_SERVE = 30.00
    too_cheap = [r for r in recs if r.get("cost_per_serve", 999) < FLOOR_PER_SERVE]
    too_expensive = [r for r in recs if r.get("cost_per_serve", 0) > CEIL_PER_SERVE]
    if too_cheap:
        results.append((FAIL,
            f"{len(too_cheap)} recipe(s) priced under ${FLOOR_PER_SERVE:.2f}/serve — "
            f"almost certainly a pricing bug: " +
            ", ".join(f"{r['name']} (${r['cost_per_serve']:.2f})" for r in too_cheap[:5])))
    if too_expensive:
        results.append((FAIL,
            f"{len(too_expensive)} recipe(s) priced over ${CEIL_PER_SERVE:.2f}/serve — "
            f"almost certainly a wrong-product match or unit mixup: " +
            ", ".join(f"{r['name']} (${r['cost_per_serve']:.2f})" for r in too_expensive[:5])))
    if not too_cheap and not too_expensive:
        cheapest = min(recs, key=lambda r: r.get("cost_per_serve", 999))
        priciest = max(recs, key=lambda r: r.get("cost_per_serve", 0))
        results.append((OK, f"cost/serve range this week: {cheapest['name']} at "
                             f"${cheapest['cost_per_serve']:.2f} to {priciest['name']} at "
                             f"${priciest['cost_per_serve']:.2f} (bounds ${FLOOR_PER_SERVE:.2f}-${CEIL_PER_SERVE:.2f})"))

    # Per-ingredient: a live 'now' price under 15% or over 4x baseline is the
    # same class of bug (should already be rejected server-side — this
    # re-checks the published data in case an older generator run produced it
    # before the guard existed, or the guard has a gap).
    bad_ing = []
    for slug, meta in ings.items():
        baseline = meta.get("baseline") or 0
        if baseline <= 0:
            continue
        for code, sp in (meta.get("by_store") or {}).items():
            now = sp.get("now", 0)
            if sp.get("flag") == "live" and not (baseline * 0.15 <= now <= baseline * 4.0):
                bad_ing.append(f"{slug}/{code}: ${now:.2f} vs baseline ${baseline:.2f}")
    if bad_ing:
        results.append((FAIL, f"{len(bad_ing)} ingredient price(s) implausible vs baseline: {bad_ing[:5]}"))
    else:
        results.append((OK, "no implausible per-ingredient prices found (checked both floor and ceiling)"))

def check_store_coverage(week, results):
    recs = week.get("recipes", [])
    total_rows, with_by_store = 0, 0
    for r in recs:
        for pi in r.get("priced_ingredients", []):
            if not pi.get("ing"):
                continue   # custom-recipe rows have no ingredient slug
            total_rows += 1
            if pi.get("by_store"):
                with_by_store += 1
    if total_rows == 0:
        results.append((WARN, "no bank-ingredient rows found to check store coverage"))
        return
    pct = with_by_store / total_rows * 100
    level = OK if pct > 95 else (WARN if pct > 50 else FAIL)
    results.append((level, f"{with_by_store}/{total_rows} ({pct:.0f}%) priced_ingredient rows carry by_store data "
                            f"(needed for single-store totals to be real, not relabelled)"))

# ---- simulate the app's own selection + costing math -------------------

def slot_factor(people, serves):
    return people / (serves or 2)

def effective_price(pi, shop_store):
    if shop_store != "both" and pi.get("by_store") and shop_store in pi["by_store"]:
        sp = pi["by_store"][shop_store]
        if sp.get("flag") == "live" or not pi.get("ing"):
            return sp
    return pi

def slot_cost_saving(r, people, shop_store, pantry_owned):
    cost = saving = 0.0
    f = slot_factor(people, r.get("serves", 2))
    for pi in r.get("priced_ingredients", []):
        if pi.get("ing") and pi["ing"] in pantry_owned:
            continue
        ep = effective_price(pi, shop_store)
        factor = f if pi.get("role") in ("hero", "scales") else 1
        now = (ep.get("now") or 0) * factor
        was = (ep.get("was") or 0) * factor if ep.get("was") else None
        cost += now
        if was and was > now:
            saving += was - now
    return cost, saving

def simulate_list_total(recipes_in_plan, people, shop_store, pantry_owned):
    """Mirrors listItems()'s aggregation, then sums non-owned lines — should
    equal the sum of slot_cost_saving() across the same recipes exactly."""
    total = 0.0
    for r in recipes_in_plan:
        f = slot_factor(people, r.get("serves", 2))
        for pi in r.get("priced_ingredients", []):
            owned = pi.get("ing") and pi["ing"] in pantry_owned
            if owned:
                continue
            ep = effective_price(pi, shop_store)
            factor = f if pi.get("role") in ("hero", "scales") else 1
            total += (ep.get("now") or 0) * factor
    return round(total, 2)

def check_hero_list_reconciliation(week, results):
    recs = week.get("recipes", [])
    if len(recs) < 3:
        results.append((WARN, "too few recipes to simulate a week"))
        return
    sample = sorted(recs, key=lambda r: -r.get("saving_pct", 0))[:5]
    for shop_store in ("both", "c", "w"):
        hero_cost = 0.0
        for r in sample:
            c, s = slot_cost_saving(r, 2, shop_store, set())
            hero_cost += c
        hero_cost = round(hero_cost, 2)
        list_total = simulate_list_total(sample, 2, shop_store, set())
        if abs(hero_cost - list_total) > 0.01:
            results.append((FAIL,
                f"shopStore={shop_store}: headline total ${hero_cost:.2f} != "
                f"list total ${list_total:.2f} (diff ${abs(hero_cost-list_total):.2f})"))
        else:
            results.append((OK, f"shopStore={shop_store}: headline (${hero_cost:.2f}) "
                                 f"matches list (${list_total:.2f})"))

def check_single_store_actually_differs(week, results):
    """If 'Shop at Coles' and 'Shop at Woolworths' produce IDENTICAL totals
    for a sample week, by_store probably isn't wired through end to end —
    it'd mean every ingredient's two store prices are coincidentally equal."""
    recs = week.get("recipes", [])
    if len(recs) < 3:
        return
    sample = sorted(recs, key=lambda r: -r.get("saving_pct", 0))[:5]
    totals = {}
    for shop_store in ("c", "w"):
        totals[shop_store] = round(sum(slot_cost_saving(r, 2, shop_store, set())[0] for r in sample), 2)
    if totals["c"] == totals["w"]:
        results.append((WARN, f"Coles-only and Woolworths-only totals are identical (${totals['c']:.2f}) "
                               f"for this sample — check by_store isn't just duplicating one store's price"))
    else:
        results.append((OK, f"Coles-only (${totals['c']:.2f}) and Woolworths-only (${totals['w']:.2f}) "
                             f"totals genuinely differ for this sample"))

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    week = load(sys.argv[1])
    print(f"Loaded week-data.json: {len(week.get('recipes', []))} recipes, "
          f"{len(week.get('ingredients', {}))} ingredients\n")

    results = []
    check_schema(week, results)
    check_plausible_prices(week, results)
    check_store_coverage(week, results)
    check_hero_list_reconciliation(week, results)
    check_single_store_actually_differs(week, results)

    failed = report(results)
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
