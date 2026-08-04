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
    seen_slugs = set()
    live_c = live_w = 0
    for r in recs:
        for pi in r.get("priced_ingredients", []):
            if not pi.get("ing"):
                continue   # custom-recipe rows have no ingredient slug
            total_rows += 1
            if pi.get("by_store"):
                with_by_store += 1
            slug = pi["ing"]
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                bs = pi.get("by_store") or {}
                if bs.get("c", {}).get("flag") == "live":
                    live_c += 1
                if bs.get("w", {}).get("flag") == "live":
                    live_w += 1
    if total_rows == 0:
        results.append((WARN, "no bank-ingredient rows found to check store coverage"))
        return
    pct = with_by_store / total_rows * 100
    level = OK if pct > 95 else (WARN if pct > 50 else FAIL)
    results.append((level, f"{with_by_store}/{total_rows} ({pct:.0f}%) priced_ingredient rows carry by_store data "
                            f"(structure present)"))

    n = len(seen_slugs) or 1
    live_pct_c, live_pct_w = live_c / n * 100, live_w / n * 100
    if live_pct_c < 10 and live_pct_w < 10:
        results.append((FAIL,
            f"only {live_c}/{n} Coles and {live_w}/{n} Woolworths ingredients have an actual LIVE "
            f"price — nearly everything fell back to the bank baseline at BOTH stores. This is why "
            f"Coles-only/Woolworths-only totals will look identical below: same baseline number at "
            f"both, not a bug in the store split. Check the generator log for catalogue-fetch/search failures."))
    else:
        results.append((OK, f"{live_c}/{n} ({live_pct_c:.0f}%) unique ingredients have a live Coles price, "
                             f"{live_w}/{n} ({live_pct_w:.0f}%) have a live Woolworths price"))

# ---- simulate the app's own selection + costing math -------------------

def slot_factor(people, serves):
    return people / (serves or 2)

def effective_price(pi, shop_store):
    if shop_store != "both" and pi.get("by_store") and shop_store in pi["by_store"]:
        return pi["by_store"][shop_store]
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
    ings = week.get("ingredients", {})
    if len(recs) < 3:
        results.append((WARN, "too few recipes to simulate a week"))
        return
    sample = sorted(recs, key=lambda r: -r.get("saving_pct", 0))[:5]
    store_saved = {}
    for shop_store in ("both", "c", "w"):
        hero_cost = hero_saved = 0.0
        for r in sample:
            c, s = slot_cost_saving(r, 2, shop_store, set())
            hero_cost += c; hero_saved += s
        hero_cost = round(hero_cost, 2)
        store_saved[shop_store] = round(hero_saved, 2)
        list_total = simulate_list_total(sample, 2, shop_store, set())
        if abs(hero_cost - list_total) > 0.01:
            results.append((FAIL,
                f"shopStore={shop_store}: headline total ${hero_cost:.2f} != "
                f"list total ${list_total:.2f} (diff ${abs(hero_cost-list_total):.2f})"))
        else:
            results.append((OK, f"shopStore={shop_store}: headline (${hero_cost:.2f}) "
                                 f"matches list (${list_total:.2f}), saved ${hero_saved:.2f}"))

    # If a store shows $0 saved, work out whether that's because this
    # SAMPLE just doesn't include any of that store's specials, or because
    # the store has zero discounts ANYWHERE in the catalogue (implausible
    # for a real catalogue — points at a 'was' price extraction bug).
    for code in ("c", "w"):
        if store_saved.get(code, 0) > 0.01:
            continue
        live_total = live_with_discount = 0
        for meta in ings.values():
            sp = (meta.get("by_store") or {}).get(code)
            if sp and sp.get("flag") == "live":
                live_total += 1
                if sp.get("was") and sp["was"] > sp.get("now", 0):
                    live_with_discount += 1
        label = "Coles" if code == "c" else "Woolworths"
        if live_total == 0:
            continue   # already covered by check_store_coverage
        if live_with_discount == 0:
            results.append((WARN,
                f"{label} shows $0 saved AND has zero discounted items anywhere in the catalogue "
                f"(0/{live_total} live {label} prices have a 'was' > 'now') — worth double-checking "
                f"'was' price extraction for {label} specifically."))
        else:
            results.append((OK,
                f"{label} shows $0 saved for this sample, but the catalogue has "
                f"{live_with_discount}/{live_total} live {label} items genuinely on special — "
                f"this sample just doesn't happen to use any of them."))

def check_single_store_actually_differs(week, results):
    """If 'Shop at Coles' and 'Shop at Woolworths' produce identical totals
    while their live-price coverage clearly differs, the store split isn't
    being applied somewhere — a code bug, not a data one. If coverage is
    similar at both stores (both near-zero or both near-total), identical
    totals are the expected, correct outcome."""
    recs = week.get("recipes", [])
    if len(recs) < 3:
        return
    sample = sorted(recs, key=lambda r: -r.get("saving_pct", 0))[:5]
    totals = {}
    for shop_store in ("c", "w"):
        totals[shop_store] = round(sum(slot_cost_saving(r, 2, shop_store, set())[0] for r in sample), 2)

    seen, live_c, live_w = set(), 0, 0
    for r in recs:
        for pi in r.get("priced_ingredients", []):
            slug = pi.get("ing")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            bs = pi.get("by_store") or {}
            if bs.get("c", {}).get("flag") == "live":
                live_c += 1
            if bs.get("w", {}).get("flag") == "live":
                live_w += 1
    n = len(seen) or 1
    live_pct_c, live_pct_w = live_c / n * 100, live_w / n * 100
    coverage_differs = abs(live_pct_c - live_pct_w) > 15

    if totals["c"] == totals["w"] and coverage_differs:
        results.append((FAIL,
            f"Coles-only and Woolworths-only totals are IDENTICAL (${totals['c']:.2f}) despite live "
            f"coverage clearly differing (Coles {live_pct_c:.0f}% vs Woolworths {live_pct_w:.0f}%) — "
            f"the store split isn't being applied somewhere. This is a code bug, not a data one."))
    elif totals["c"] == totals["w"]:
        results.append((OK, f"Coles-only and Woolworths-only totals are identical (${totals['c']:.2f}) — "
                             f"expected, since live coverage is similar at both stores"))
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
