#!/usr/bin/env python3
"""
One-off converter: recipe-bank.json (v1, prices baked into recipe items)
  -> ingredients.json (canonical, per-unit baseline prices)
  -> recipes.json      (recipes reference ingredient slugs + real quantities)

Run once. After this, recipe-bank.json v1 is retired; the compiled bank is
built at CI time from ingredients.json + recipes/*.json (see build_bank.py).
"""
import json, re, collections, statistics, sys

SRC = "/home/claude/thedocket/planner/docket-planner/recipe-bank.json"

PANTRY_HINTS = (
    "olive oil", "vegetable oil", "sesame oil", "garlic-infused oil", "cooking oil",
    "canola oil", "sauce", "paste", "vinegar", "cornflour", "cornstarch", "stock",
    "thyme", "spice", "curry powder", "seasoning", "honey", "soy", "miso",
    "chilli flakes", "chili flakes", "flour", "sugar", "coriander seed",
    "cumin", "bay leaf", "bicarb",
)
PROTEIN_KEYWORDS = {
    "chicken": ["chicken", "poultry"],
    "beef": ["beef", "steak", "mince"],
    "pork": ["pork", "bacon"],
    "lamb": ["lamb"],
    "duck": ["duck"],
    "seafood": ["salmon", "prawn", "fish", "squid", "barramundi", "tuna",
                "cod", "mussel", "flathead", "bream", "seafood"],
    "egg": ["egg"],
    "legume": ["tofu", "chickpea", "lentil", "dhal", "dahl", "bean"],
}
# order matters: prefer a named meat/seafood hero over an incidental egg garnish
PROTEIN_PRIORITY = ["beef", "lamb", "pork", "duck", "chicken", "seafood", "legume", "egg"]

QTY_RE_KG  = re.compile(r'(\d+\.?\d*)\s*kg', re.I)
QTY_RE_G   = re.compile(r'(\d+\.?\d*)\s*g(?![a-z])', re.I)
QTY_RE_ML  = re.compile(r'(\d+\.?\d*)\s*m[lL]\b')
QTY_RE_L   = re.compile(r'(\d+\.?\d*)\s*[lL]\b(?!b)')
QTY_RE_CNT = re.compile(r'[\u00d7x]\s*(\d+)', re.I)

def parse_qty(name):
    s = name
    m = QTY_RE_KG.search(s)
    if m: return ("g", float(m.group(1)) * 1000)
    m = QTY_RE_G.search(s)
    if m: return ("g", float(m.group(1)))
    m = QTY_RE_ML.search(s)
    if m: return ("ml", float(m.group(1)))
    m = QTY_RE_L.search(s)
    if m: return ("ml", float(m.group(1)) * 1000)
    m = QTY_RE_CNT.search(s)
    if m: return ("ea", float(m.group(1)))
    return (None, None)

def base_name(name):
    n = re.sub(r'\s*[\(\[].*?[\)\]]', '', name)
    n = re.sub(r'[\u00d7x]\s*\d+.*$', '', n, flags=re.I)
    n = re.sub(r'~?\d+(\.\d+)?\s*(kg|g|ml|l)\b.*$', '', n, flags=re.I)
    n = re.sub(r'\d+', '', n)
    n = re.sub(r'\s{2,}', ' ', n).strip(' ,.-')
    return n.strip()

def slugify(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')

def is_pantry(base):
    b = base.lower()
    return any(h in b for h in PANTRY_HINTS)

def primary_protein_word(base):
    b = base.lower()
    for cat, kws in PROTEIN_KEYWORDS.items():
        if any(k in b for k in kws):
            return cat
    return None

def main():
    data = json.load(open(SRC))
    recipes_in = data["recipes"]

    # ---- pass 1: group occurrences by base ingredient name ----
    groups = collections.defaultdict(list)  # base -> [(unit, qty, portion_price, raw_name)]
    for r in recipes_in:
        for it in r.get("items", []):
            raw_name, store, price, was, note = (it + [None]*5)[:5]
            base = base_name(raw_name)
            unit, qty = parse_qty(raw_name)
            groups[base].append({
                "unit": unit, "qty": qty, "price": price, "raw": raw_name,
                "store": store,
            })

    # ---- pass 2: build ingredient catalogue with per-unit baseline prices ----
    ingredients = {}
    base_to_slug = {}
    for base, occs in groups.items():
        slug = slugify(base)
        base_to_slug[base] = slug
        pantry = is_pantry(base)

        # derive per-unit price for each occurrence where we have qty+unit
        per_kg, per_l, per_ea, flat = [], [], [], []
        for o in occs:
            if o["price"] is None:
                continue
            if o["unit"] == "g" and o["qty"]:
                per_kg.append(o["price"] / (o["qty"] / 1000))
            elif o["unit"] == "ml" and o["qty"]:
                per_l.append(o["price"] / (o["qty"] / 1000))
            elif o["unit"] == "ea" and o["qty"]:
                per_ea.append(o["price"] / o["qty"])
            else:
                flat.append(o["price"])

        if per_kg:
            unit, baseline = "kg", round(statistics.median(per_kg), 2)
        elif per_l:
            unit, baseline = "L", round(statistics.median(per_l), 2)
        elif per_ea:
            unit, baseline = "ea", round(statistics.median(per_ea), 2)
        else:
            unit, baseline = "pack", round(statistics.median(flat), 2) if flat else 0.0

        stores = collections.Counter(o["store"] for o in occs if o["store"])
        store_pref = stores.most_common(1)[0][0] if stores else "e"

        category = primary_protein_word(base) or ("pantry" if pantry else "produce")

        ingredients[slug] = {
            "label": base.strip().capitalize(),
            "category": category,
            "unit": unit,
            "baseline": baseline,
            "pantry": pantry,
            "store_pref": store_pref,
            "search_terms": sorted({w for w in re.findall(r'[a-z]+', base.lower())
                                     if len(w) > 2}),
            "occurrences": len(occs),
        }

    # ---- pass 3: rewrite recipes against ingredient slugs ----
    recipes_out = []
    for r in recipes_in:
        candidates = []
        for it in r.get("items", []):
            raw_name = it[0]
            base = base_name(raw_name)
            slug = base_to_slug[base]
            if ingredients[slug]["pantry"]:
                continue   # e.g. "beef stock", "chicken stock cube" can't be the hero
            protein = primary_protein_word(base)
            if protein:
                candidates.append((protein, slug))
        hero = None
        if candidates:
            for cat in PROTEIN_PRIORITY:
                match = next((slug for p, slug in candidates if p == cat), None)
                if match:
                    hero = match
                    break

        ing_list = []
        for it in r.get("items", []):
            raw_name, store, price, was, note = (it + [None]*5)[:5]
            base = base_name(raw_name)
            slug = base_to_slug[base]
            unit, qty = parse_qty(raw_name)
            ing_meta = ingredients[slug]
            note_l = (note or "").lower()
            if slug == hero:
                role = "hero"
            elif ing_meta["pantry"]:
                role = "pantry"
            elif "shared" in note_l or "half" in note_l:
                role = "shared"
            else:
                role = "scales"
            ing_list.append({
                "ing": slug,
                "qty": qty,
                "unit": unit or ing_meta["unit"],
                "role": role,
                "note": note or None,
            })
        fod = r.get("fod", "")
        diet = {
            "low_fodmap": "low fodmap" in fod.lower(),
            "gluten_free": " gf" in f" {fod.lower()}" or "gluten free" in fod.lower(),
            "lactose_free": "lf" in fod.lower() or "lactose" in fod.lower(),
        }
        recipes_out.append({
            "id": r["id"],
            "name": re.sub(r'^\d+%-off\s+', '', r["name"], flags=re.I),  # strip transient discount framing
            "desc": r.get("desc", ""),
            "serves": r.get("serves", 2),
            "diet": diet,
            "diet_raw": fod,
            "hero": hero,
            "nut": r.get("nut", {}),
            "waste": r.get("waste", ""),
            "steps": r.get("recipe", []),
            "ingredients": ing_list,
        })

    out_ing = {"version": 1, "ingredients": ingredients}
    out_rec = {"version": 1, "recipes": recipes_out}

    json.dump(out_ing, open("ingredients.json", "w"), indent=1)
    json.dump(out_rec, open("recipes.json", "w"), indent=1)

    print(f"ingredients: {len(ingredients)}  (from {sum(len(v) for v in groups.values())} item occurrences)")
    print(f"recipes: {len(recipes_out)}")
    no_hero = [r["id"] for r in recipes_out if not r["hero"]]
    print(f"recipes with no detected hero protein ({len(no_hero)}): {no_hero}")

if __name__ == "__main__":
    main()
