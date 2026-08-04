#!/usr/bin/env python3
"""
Meal Planner — Weekly Price Generator
Runs Tuesday night: fetches Coles + Woolies catalogues, matches recipes, 
generates thisweek.json, pushes to GitHub.

SETUP:
1. Create a GitHub personal access token (ghp_...) with repo scope
2. Set environment variables:
   - GITHUB_TOKEN: your PAT
   - GITHUB_REPO: username/mealplanner
   - GITHUB_EMAIL: your email
3. Run with saleIds: python3 thisweek.py --coles 66019 --woolies 66046

OUTPUT: thisweek.json pushed to GitHub with this week's 12-15 meals
"""

import json
import os
import sys
import html
import subprocess
from datetime import datetime
from typing import Dict, List
import requests

# ============ CONFIG ============
COLES_SALEID = os.getenv("COLES_SALEID", "66019")
WOOLIES_SALEID = os.getenv("WOOLIES_SALEID", "66046")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "username/mealplanner")
GITHUB_EMAIL = os.getenv("GITHUB_EMAIL", "your-email@example.com")

COLES_URL = f"https://www.coles.com.au/catalogues/view#view=list&saleId={COLES_SALEID}&areaName=c-wa-met"
WOOLIES_URL = f"https://www.woolworths.com.au/shop/catalogue/view#view=list&saleId={WOOLIES_SALEID}&areaName=WA"

# ============ CATALOGUE PARSING ============
def fetch_catalogue_with_playwright(url: str, store_name: str) -> List[Dict]:
    """
    Fetch catalogue using Playwright (headless browser) to handle JavaScript rendering.
    Clicks "Load more" until all items are loaded, then extracts product + price data.
    """
    print(f"[{store_name}] Fetching catalogue with browser automation...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"  [!] Playwright not installed. Install: pip install playwright")
        print(f"  [!] Then run: playwright install")
        return []
    
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            
            # Click "Load more" buttons until all items loaded
            for attempt in range(50):
                try:
                    load_btn = page.query_selector('button:has-text("Load more")')
                    if not load_btn:
                        break
                    load_btn.click()
                    page.wait_for_timeout(800)  # Wait for items to render
                except:
                    break
            
            # Extract product info from the rendered page
            # This assumes a structure like:
            # <div class="product">
            #   <h3>Product Name</h3>
            #   <span class="price">$X.XX</span>
            #   <span class="was-price">Was $Y.YY</span>
            # </div>
            
            products = page.query_selector_all('[class*="product"], [data-product]')
            for prod in products:
                try:
                    name_el = prod.query_selector('h3, h4, [class*="name"]')
                    price_el = prod.query_selector('[class*="price"], span:has-text("$")')
                    was_el = prod.query_selector('[class*="was"], text=/Was|was/')
                    
                    name = name_el.text_content().strip() if name_el else ""
                    price_text = price_el.text_content().strip() if price_el else ""
                    was_text = was_el.text_content().strip() if was_el else ""
                    
                    # Parse price from text like "$7.50" or "$7.50/kg"
                    price = parse_price(price_text)
                    was_price = parse_price(was_text) if was_text else None
                    
                    if name and price:
                        items.append({
                            "product": name,
                            "price": price,
                            "was_price": was_price,
                            "price_text": price_text,
                            "unit": detect_unit(price_text),
                            "store": store_name.lower()
                        })
                except:
                    continue
            
            browser.close()
    except Exception as e:
        print(f"  [ERROR] Playwright failed: {e}")
        return []
    
    print(f"  Extracted {len(items)} items")
    return items

def fetch_catalogue_fallback(url: str, store_name: str) -> List[Dict]:
    """
    Fallback: fetch catalogue HTML and parse with regex/BeautifulSoup.
    Works for static HTML but won't handle JavaScript-rendered content.
    """
    print(f"[{store_name}] Fetching catalogue (static parsing)...")
    items = []
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=15)
        resp.raise_for_status()
        
        # Try to use BeautifulSoup if available
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Look for product containers (varies by site, adjust selectors)
            products = soup.select('[class*="product"], [data-product], article')
            for prod in products:
                # Extract name
                name_tag = prod.select_one('h3, h4, [class*="title"], [class*="name"]')
                name = name_tag.get_text(strip=True) if name_tag else ""
                
                # Extract price
                price_tag = prod.select_one('[class*="price"], [class*="$"], span')
                price_text = price_tag.get_text(strip=True) if price_tag else ""
                
                if name and "$" in price_text:
                    price = parse_price(price_text)
                    if price:
                        items.append({
                            "product": name,
                            "price": price,
                            "was_price": None,
                            "price_text": price_text,
                            "unit": detect_unit(price_text),
                            "store": store_name.lower()
                        })
        except ImportError:
            print(f"  [!] BeautifulSoup not installed. Install: pip install beautifulsoup4")
            return []
    except Exception as e:
        print(f"  [ERROR] Static parsing failed: {e}")
    
    print(f"  Extracted {len(items)} items")
    return items

def parse_price(price_str: str) -> float:
    """Extract price as float from strings like '$7.50', '$7.50/kg', etc."""
    import re
    match = re.search(r'\$(\d+\.?\d*)', price_str)
    return float(match.group(1)) if match else None

def detect_unit(price_str: str):
    """
    Detect the pricing basis from the raw price text so prices can be scaled
    to a recipe's quantity. Returns 'kg', '100g', 'ea', or None (flat/pack).
    e.g. '$18.00 / kg' -> 'kg';  '$18.00kg' -> 'kg';  '$3.50 ea' -> 'ea';
         '$2.00 pkg' -> None;    '$5.00' -> None
    """
    import re
    t = (price_str or "").lower()
    if re.search(r'\b100\s*g\b', t):
        return "100g"
    if re.search(r'(?<![a-z])kg\b', t):   # lookbehind rejects 'pkg'/'package'
        return "kg"
    if re.search(r'\b(ea|each)\b', t):
        return "ea"
    return None

# ============ SALEFINDER API (primary source) ============
# Coles & Woolworths publish their weekly catalogues via SaleFinder. The
# svgData endpoint returns structured JSON: every product's name + sale price.
# Each store needs three IDs (grab them from the catalogue page's Network tab):
#   - catalogueId : changes WEEKLY (the current flyer's id), e.g. 66233
#   - retailerId  : fixed per retailer, e.g. Coles WA = 148
#   - locationId  : fixed per region,   e.g. WA Metro = 9045
# Optional token may or may not be required (test the URL without it).
SALEFINDER = {
    "coles": {
        "catalogue": os.getenv("COLES_CATALOGUE_ID", ""),
        "retailer":  os.getenv("COLES_RETAILER_ID", ""),
        "location":  os.getenv("COLES_LOCATION_ID", ""),
        "token":     os.getenv("COLES_TOKEN", ""),
    },
    "woolworths": {
        "catalogue": os.getenv("WOOLIES_CATALOGUE_ID", ""),
        "retailer":  os.getenv("WOOLIES_RETAILER_ID", ""),
        "location":  os.getenv("WOOLIES_LOCATION_ID", ""),
        "token":     os.getenv("WOOLIES_TOKEN", ""),
    },
}

def _strip_jsonp(text: str):
    """SaleFinder may wrap JSON in a JSONP callback: jQuery123({...}). Unwrap it."""
    s = text.strip()
    if not s.startswith("{"):
        i, j = s.find('('), s.rfind(')')
        if i != -1 and j != -1 and j > i:
            s = s[i + 1:j]
    return json.loads(s)

def _sf_price(v):
    if v is None:
        return None
    import re
    m = re.search(r'\d+\.?\d*', str(v).replace(',', ''))
    return float(m.group(0)) if m else None

# catalogue validity dates captured at fetch time, keyed by store
CATALOGUE_META: Dict[str, Dict] = {}

import re as _re_diet
_DATE_WORD = _re_diet.compile(r'\bdates?\b')
# 'banana' the fruit — but NOT 'banana prawns' (a prawn variety, not the fruit)
_BANANA = _re_diet.compile(r'\bbanana\b(?!\s+prawn)')

def diet_flags(recipe: Dict) -> Dict:
    """
    Derive dietary/allergen flags for a recipe from its 'fod' tag and text.
    'contains' lists trigger allergens present (banana/avocado/date).
    """
    fod = str(recipe.get("fod", "")).lower()
    text = " ".join([
        str(recipe.get("name", "")), str(recipe.get("desc", "")),
        " ".join(str(s) for s in recipe.get("recipe", [])),
        " ".join(str(it[0]) for it in recipe.get("items", []) if it),
    ]).lower()
    contains = []
    if _BANANA.search(text):
        contains.append("banana")
    if "avocado" in text:
        contains.append("avocado")
    if _DATE_WORD.search(text):
        contains.append("date")
    return {
        "low_fodmap": "low fodmap" in fod,
        "gf": "gf" in fod or "gluten" in fod,
        "lf": "lf" in fod or "lactose" in fod,
        "contains": contains,
    }

def parse_salefinder_svgdata(data: Dict, store_name: str) -> List[Dict]:
    """
    Pull products out of a SaleFinder svgData response. The 'catalogue' array
    holds pages; real products are the dict values that carry an 'itemName' and
    'lowestPrice' (category-nav links have 'itemText' instead, so they're skipped).
    """
    items = []
    for page in data.get("catalogue", []):
        if not isinstance(page, dict):
            continue
        for v in page.values():
            if isinstance(v, dict) and "itemName" in v and v.get("lowestPrice") not in (None, ""):
                name = html.unescape(str(v["itemName"])).strip()
                price = _sf_price(v["lowestPrice"])
                if name and price:
                    items.append({
                        "product": name,
                        "price": price,
                        "was_price": None,   # svgData gives sale price only
                        "price_text": "",    # no per-unit text in svgData
                        "unit": None,        # -> treated as a flat/advertised price
                        "store": store_name.lower(),
                    })
    return items

def fetch_catalogue_salefinder(store_name: str) -> List[Dict]:
    """Fetch + parse the SaleFinder catalogue for a store. Returns [] if unconfigured/failed."""
    cfg = SALEFINDER.get(store_name.lower(), {})
    cat, ret, loc = cfg.get("catalogue"), cfg.get("retailer"), cfg.get("location")
    if not (cat and ret and loc):
        print(f"  [SaleFinder] {store_name}: not configured (need catalogue/retailer/location IDs) — skipping.")
        return []
    params = {
        "format": "json",
        "pagetype": "catalogue2",
        "retailerId": ret,
        "locationId": loc,
        "saleGroup": os.getenv("SF_SALEGROUP", "0"),
        "size": "518",
    }
    if cfg.get("token"):
        params["token"] = cfg["token"]
    url = f"https://embed.salefinder.com.au/catalogue/svgData/{cat}/"
    try:
        print(f"  [SaleFinder] {store_name}: requesting catalogue {cat}...")
        resp = requests.get(url, params=params, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Referer": "https://embed.salefinder.com.au/",
        })
        resp.raise_for_status()
        data = _strip_jsonp(resp.text)
        items = parse_salefinder_svgdata(data, store_name)
        # stash the catalogue's own validity dates for the planner to show
        CATALOGUE_META[store_name.lower()] = {
            "start": data.get("startDate"), "end": data.get("endDate"),
            "publish": data.get("publishDate"), "area": data.get("areaName"),
            "name": data.get("saleName"),
        }
        print(f"  [SaleFinder] {store_name}: {len(items)} products extracted")
        return items
    except Exception as e:
        print(f"  [SaleFinder] {store_name}: failed ({e}) — falling back.")
        return []

# ============ SALEFINDER per-ingredient SEARCH (accurate prices) ============
# The productlist/search endpoint returns, per product, the headline price
# (sf-pricedisplay), its unit (sf-optionsuffix: 'each'/blank) AND a comparative
# unit price (sf-comparativeText: '$15.26 per kg', '$0.27 per 100g'). The
# comparative price is what lets us scale to a recipe's portion correctly —
# fixing the per-kg/per-each prices that svgData collapsed into wrong flat numbers.
#
# Needs the same catalogue/location IDs plus a token + saleGroup. The token is a
# static embed key (from the catalogue's app.js), not a session value. Coles WA
# defaults are baked in; Woolies values are env-overridable and fall back to the
# shared token. If search is unavailable for a store, we degrade to svgData.
_SF_DEFAULT_TOKEN = "570f5c4a44505b5f51477f531a03180a08051c1362352b2e21363226253968717d7a767d6762656262612b"

SF_SEARCH = {
    "coles": {
        "token":     os.getenv("COLES_TOKEN", _SF_DEFAULT_TOKEN),
        "saleGroup": os.getenv("COLES_SALEGROUP", "97"),
    },
    "woolworths": {
        "token":     os.getenv("WOOLIES_TOKEN", _SF_DEFAULT_TOKEN),
        "saleGroup": os.getenv("WOOLIES_SALEGROUP", "97"),
    },
}

def _money(s):
    m = _re_sf.search(r'\$?\s*(\d+(?:\.\d+)?)', s or '')
    return float(m.group(1)) if m else None

def _parse_comparative(text):
    """'$15.26 per kg' -> (15.26, 1000.0g); '$0.27 per 100g' -> (0.27, 100.0g). Else None."""
    if not text:
        return None
    val = _money(text)
    if val is None:
        return None
    t = text.lower()
    if _re_sf.search(r'per\s*kg', t):      return (val, 1000.0)
    if _re_sf.search(r'per\s*100\s*g', t): return (val, 100.0)
    if _re_sf.search(r'per\s*g\b', t):     return (val, 1.0)
    return None

import re as _re_sf
_SF_ITEM_RE = _re_sf.compile(r'<a\b[^>]*class="[^"]*\bsf-item\b[^"]*"[^>]*>(.*?)</a>', _re_sf.I | _re_sf.S)

def parse_salefinder_search_html(content_html: str, store: str) -> List[Dict]:
    """Extract priced products from a productlist/search 'content' HTML blob."""
    out = []
    for block in _SF_ITEM_RE.findall(content_html or ""):
        nm = _re_sf.search(r'sf-item-heading[^>]*>(.*?)</h4>', block, _re_sf.I | _re_sf.S)
        if not nm:
            continue
        name = html.unescape(_re_sf.sub(r'<[^>]+>', '', nm.group(1))).strip()

        def grab(cls):
            m = _re_sf.search(r'class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</span>',
                              block, _re_sf.I | _re_sf.S)
            return html.unescape(_re_sf.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ""

        now = _money(grab("sf-pricedisplay"))
        if now is None:
            continue
        suffix = grab("sf-optionsuffix").lower()
        regdesc = grab("sf-regoptiondesc")
        was = _money(regdesc) if "was" in regdesc.lower() else None
        save = _money(grab("sf-regprice"))          # the "Save $X" amount (per unit)
        cm = _re_sf.search(r'sf-comparativeText[^>]*>(.*?)</p>', block, _re_sf.I | _re_sf.S)
        comp = _parse_comparative(html.unescape(_re_sf.sub(r'<[^>]+>', '', cm.group(1))).strip()) if cm else None
        mb = _re_sf.search(r'any\s*(\d+)\s*for', (grab("sf-saleoptiondesc") or "").lower())
        out.append({
            "product": name, "price": now, "was_price": was, "save": save,
            "unit": ("ea" if suffix in ("each", "ea") else None),
            "comp": comp, "multibuy": int(mb.group(1)) if mb else None,
            "store": store.lower(),
        })
    return out

_SF_SEARCH_CACHE = {}   # (store, query) -> [candidates]

def sf_search(store: str, query: str) -> List[Dict]:
    """Search a store's current catalogue for `query`. Cached; [] on miss/failure."""
    store = store.lower()
    key = (store, query.lower())
    if key in _SF_SEARCH_CACHE:
        return _SF_SEARCH_CACHE[key]
    cfg = SALEFINDER.get(store, {})
    scfg = SF_SEARCH.get(store, {})
    sale, loc = cfg.get("catalogue"), cfg.get("location")
    if not (sale and loc):
        _SF_SEARCH_CACHE[key] = []
        return []
    params = {
        "format": "json", "locationId": loc,
        "token": scfg.get("token", _SF_DEFAULT_TOKEN),
        "saleGroup": scfg.get("saleGroup", "97"),
        "keyword": query, "extraProducts": "1",
    }
    url = f"https://embed.salefinder.com.au/productlist/search/{sale}/"
    try:
        resp = requests.get(url, params=params, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Referer": "https://embed.salefinder.com.au/",
        })
        resp.raise_for_status()
        data = _strip_jsonp(resp.text)
        cands = parse_salefinder_search_html(data.get("content", ""), store)
    except Exception as e:
        print(f"  [SF search] {store} '{query}' failed ({e})")
        cands = []
    _SF_SEARCH_CACHE[key] = cands
    return cands

def sf_resolve_catalogue_id(store: str):
    """
    Best-effort: ask SaleFinder for the retailer's current catalogue id so the
    weekly id never has to be set by hand. Returns a string id or None. The env
    Variable still wins as an explicit override; this is only used to fill a gap.
    """
    cfg = SALEFINDER.get(store.lower(), {})
    scfg = SF_SEARCH.get(store.lower(), {})
    ret, loc = cfg.get("retailer"), cfg.get("location")
    if not (ret and loc):
        print(f"  [SF resolve] {store}: no retailer/location configured, skipping")
        return None
    params = {
        "format": "json", "token": scfg.get("token", _SF_DEFAULT_TOKEN),
        "saleGroup": scfg.get("saleGroup", "97"), "locationId": loc,
        "order": "newestfirst",   # was 'oldestfirst' — that asked for the WRONG end of the list
    }
    url = f"https://embed.salefinder.com.au/catalogues/view/{ret}/"
    try:
        resp = requests.get(url, params=params, timeout=15, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://embed.salefinder.com.au/"})
        resp.raise_for_status()
        data = _strip_jsonp(resp.text)
        content = data.get("content", "")
        ids = _re_sf.findall(r'saleId=(\d+)', content)
        if not ids:
            # fall back to scanning the whole payload, not just 'content' —
            # some responses carry the id elsewhere (e.g. top-level fields)
            ids = _re_sf.findall(r'saleId["\']?\s*[:=]\s*["\']?(\d+)', resp.text)
        if not ids:
            print(f"  [SF resolve] {store}: request succeeded (HTTP {resp.status_code}, "
                  f"{len(resp.text)} bytes) but found no saleId in the response — "
                  f"SaleFinder's response shape may have changed, or retailer={ret}/"
                  f"location={loc} isn't returning a current catalogue. "
                  f"First 200 chars: {resp.text[:200]!r}")
            return None
        return max(ids, key=lambda x: int(x))
    except Exception as e:
        print(f"  [SF resolve] {store}: request failed ({type(e).__name__}: {e})")
        return None

def fetch_catalogue(url: str, store_name: str) -> List[Dict]:
    """
    Fetch this week's catalogue specials.

    Primary path: SaleFinder JSON API (Coles & Woolworths both use SaleFinder).
    This returns clean structured data — every product's name + sale price — in
    one request, with no HTML scraping or browser automation. Falls back to the
    old Playwright/static scrapers only if SaleFinder isn't configured or fails.
    """
    sf = fetch_catalogue_salefinder(store_name)
    if sf:
        return sf

    # Fallbacks (legacy scrapers) — only reached if SaleFinder returns nothing.
    items = fetch_catalogue_with_playwright(url, store_name)
    if items:
        return items

    print(f"  [!] Playwright unavailable, trying static parsing...")
    items = fetch_catalogue_fallback(url, store_name)
    if items:
        return items

    print(f"  [!] Unable to fetch {store_name} catalogue automatically.")
    print(f"  [!] Falling back to recipe bank matching on generic protein types.")
    return []

def extract_specials(items: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group items by broad protein/ingredient category.
    Returns: {"chicken": [...], "beef": [...], "seafood": [...], etc.}
    """
    specials = {
        "chicken": [],
        "beef": [],
        "pork": [],
        "lamb": [],
        "seafood": [],
        "vegetables": [],
        "pantry": []
    }
    
    for item in items:
        product = item.get("product", "").lower()
        if "chicken" in product or "poultry" in product:
            specials["chicken"].append(item)
        elif "beef" in product:
            specials["beef"].append(item)
        elif "pork" in product:
            specials["pork"].append(item)
        elif "lamb" in product:
            specials["lamb"].append(item)
        elif any(x in product for x in ["salmon", "prawn", "fish", "squid", "barramundi"]):
            specials["seafood"].append(item)
        elif any(x in product for x in ["vegetable", "broccoli", "carrot", "potato"]):
            specials["vegetables"].append(item)
        else:
            specials["pantry"].append(item)
    
    return specials
# ============ LIVE PRICE MERGE ============
import re as _re

# words that aren't useful for matching an ingredient to a catalogue product
_STOP = set("""the a an of and or with in on for to fresh light free onion drained
weight half can pack bag bags bunch bunches head heads jar bottle tin tinned canned
roast diced minced fillet fillets piece pieces approx each whole
coles woolworths woolies australian aussie grown proudly classic raw skin knob
rspca approved hormones added quick cook value smart finest""".split())

def _norm(w: str) -> str:
    """Light singular/plural unifier so 'lemon' matches 'lemons', 'carrot'~'carrots'."""
    return w[:-1] if (len(w) > 3 and w.endswith("s") and not w.endswith("ss")) else w

_QTY_TOKEN = _re.compile(r'(\d+\.?\d*\s*(kg|g|ml|l)\b|[\u00d7x]\s*\d+|\(.*?\))', _re.I)

def _content_tokens(name: str):
    """Significant words from an item/product name (drops sizes, units, fillers)."""
    s = _QTY_TOKEN.sub(' ', (name or '').lower())
    s = _re.sub(r"[^a-z ]", ' ', s)
    return {_norm(w) for w in s.split() if len(w) > 2 and w not in _STOP}

def parse_item_quantity(name: str):
    """
    Pull the quantity a recipe item calls for.
    Returns {'grams': float|None, 'count': int|None, 'ml': float|None}.
    'Pork belly 500g' -> grams 500;  'Chicken drumsticks 2kg pack' -> grams 2000;
    'Carrots x4' -> count 4;  'Coconut milk 200mL' -> ml 200.
    """
    s = (name or '').lower()
    kg = _re.search(r'(\d+\.?\d*)\s*kg', s)
    g  = _re.search(r'(\d+\.?\d*)\s*g(?![a-z])', s)
    ml = _re.search(r'(\d+\.?\d*)\s*ml', s)
    cnt = _re.search(r'[\u00d7x]\s*(\d+)', s)
    grams = float(kg.group(1)) * 1000 if kg else (float(g.group(1)) if g else None)
    return {
        "grams": grams,
        "count": int(cnt.group(1)) if cnt else None,
        "ml": float(ml.group(1)) if ml else None,
    }

def _store_code(scraped_store: str) -> str:
    s = (scraped_store or '').lower()
    if s.startswith('col'): return 'c'
    if s.startswith('wool'): return 'w'
    return 'e'

def compute_scaled_price(qty: Dict, scraped: Dict):
    """
    Scale a catalogue price to the recipe's quantity.
    Returns (price, was, basis) or None if it can't be done reliably.
    """
    unit = scraped.get("unit")
    price = scraped.get("price")
    was = scraped.get("was_price")
    if price is None:
        return None
    grams = qty["grams"]

    if unit in ("kg", "100g") and grams:
        factor = grams / (1000.0 if unit == "kg" else 100.0)
        return (round(price * factor, 2),
                round(was * factor, 2) if was else None,
                f"{unit} x {grams:g}g")

    # flat price (pack) or per-each with no weight info: use as-is, best effort
    if unit in (None, "ea"):
        return (round(price, 2), round(was, 2) if was else None, unit or "pack")

    # per-kg price but the recipe is a count/volume we can't convert -> don't guess
    return None

def _set_status(item: list, status: str):
    """Append a 6th element ('live'|'est') without disturbing the 5-field shape the planner reads."""
    if len(item) >= 6:
        item[5] = status
    else:
        item.append(status)

def _ordered_food_tokens(name: str):
    """Significant words in order (for building search queries)."""
    s = _QTY_TOKEN.sub(' ', (name or '').lower())
    s = _re.sub(r"[^a-z ]", ' ', s)
    return [w for w in s.split() if len(w) > 2 and w not in _STOP]

# core protein/produce nouns worth a broad fallback search when the specific
# phrase misses (Coles' own search returns 0 for 'chuck' but works for 'beef')
_BROAD = {"beef","chicken","pork","lamb","salmon","prawns","prawn","fish","squid",
          "potatoes","carrots","broccolini","orange","oranges","lemon","apple",
          "apples","banana","tuna","bok","mince"}

def _search_queries(name: str):
    """Ordered, de-duped queries to try for one recipe item (capped at 4)."""
    toks = _ordered_food_tokens(name)
    if not toks:
        return []
    q = []
    if len(toks) >= 2:
        q.append(" ".join(toks[:2]))      # 'chicken breast', 'banana prawns'
    q.append(toks[-1])                     # food noun is often the last word
    for t in toks:                         # every broad noun, as fallbacks
        if t in _BROAD:
            q.append(t)
    q.append(toks[0])                      # first token as last resort
    seen, out = set(), []
    for x in q:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out[:4]

def _best_search_candidate(item_name: str, cands: List[Dict]):
    """Pick the candidate whose name best overlaps the recipe item (token-based)."""
    rtok = _content_tokens(item_name)
    if not rtok:
        return None
    best, best_shared = None, 0
    for c in cands:
        shared = len(rtok & _content_tokens(c.get("product", "")))
        if shared > best_shared:
            best, best_shared = c, shared
    return best if best_shared >= 1 else None

def _price_from_search(qty: Dict, cand: Dict):
    """
    Turn a search candidate into a portion price using real unit info.
    Returns (price, was, basis) or None if it can't be done sensibly.
    Priority: comparative per-kg/100g (most reliable) -> per-each*count -> flat.
    Multibuy ('Any 2 for $15') is treated as a single-unit price (price/n).

    A regular ("was") price is derived once as a discount RATIO and applied to
    whatever scaled 'now' we compute, so per-kg/per-each items scaled by the
    comparative price still show a saving. reg = explicit "Was $X" when present,
    else now + "Save $Y". Only kept when it's genuinely above the sale price.
    """
    price, was, comp = cand.get("price"), cand.get("was_price"), cand.get("comp")
    save = cand.get("save")
    unit, mb = cand.get("unit"), cand.get("multibuy")
    grams, count = qty.get("grams"), qty.get("count")

    # regular (pre-discount) unit price, and the discount ratio reg/price
    reg = None
    if was and price and was > price:
        reg = was                                   # explicit "Was $X"
    elif save and price:
        if 0 < save < price:
            reg = round(price + save, 2)            # regprice is the amount saved
        elif save > price:
            reg = save                              # regprice is the regular price itself
    ratio = (reg / price) if (reg and price and reg > price) else None
    def _with_was(now):
        return (now, round(now * ratio, 2) if ratio else None)

    if comp and grams:                      # $/kg or $/100g scaled to the portion
        val, basis = comp
        now = round(val * grams / basis, 2)
        p, w = _with_was(now)
        return (p, w, f"comp {val}/{int(basis)}g x {grams:g}g")

    if mb and mb > 1:                        # multibuy -> per-single price
        each = round(price / mb, 2)
        now = round(each * (count or 1), 2)
        p, w = _with_was(now)
        return (p, w, f"multibuy {mb}")

    if unit == "ea":                         # advertised per-each
        n = count or 1
        now = round(price * n, 2)
        p, w = _with_was(now)
        return (p, w, f"each x{n}")

    # flat/pack/bottle shelf price. In the SEARCH path the unit fields are known,
    # so the absence of a per-kg/each basis means this *is* the item's price —
    # use it even when the recipe lists a weight/volume (e.g. a 500mL soy bottle).
    p, w = _with_was(round(price, 2))
    return (p, w, "shelf")

def _price_from_svgdata(qty: Dict, sc: Dict, est_price):
    """
    Fallback when search has no unit info (svgData pool). svgData carries no unit,
    so a per-kg figure would otherwise be inserted as a flat price (the $42 lemon).
    Guardrail: only accept it when it's within a sane band of the bank estimate.
    """
    price = sc.get("price")
    if price is None:
        return None
    if est_price and est_price > 0:
        ratio = price / est_price
        if ratio < 0.25 or ratio > 4.0:     # implausible vs estimate -> reject
            return None
    return (round(price, 2), None, "svgData~est")
# ============ INGREDIENT CATALOGUE (pricing-first architecture) ============
# v2 pipeline: price the ~100-ingredient catalogue ONCE (not per selected
# recipe), publish every recipe's cost/saving fully computed. Selection
# (which recipes, how many, which savings mode) happens client-side in
# index.html against this priced data — the generator no longer picks
# the week, it just makes accurate pricing available for every recipe.

def load_ingredients(filepath: str) -> Dict:
    with open(filepath) as f:
        return json.load(f).get("ingredients", {})

def load_recipes(filepath: str) -> List[Dict]:
    with open(filepath) as f:
        return json.load(f).get("recipes", [])

def _unit_probe_qty(unit: str) -> Dict:
    """A qty dict representing exactly 1 of an ingredient's baseline unit,
    so _price_from_search returns a genuine per-unit price."""
    if unit == "kg":
        return {"grams": 1000.0, "count": None, "ml": None}
    if unit == "L":
        return {"grams": None, "count": None, "ml": 1000.0}
    if unit == "ea":
        return {"grams": None, "count": 1, "ml": None}
    return {"grams": None, "count": None, "ml": None}   # "pack": shelf price as-is

def _price_one_store(store: str, meta: Dict, qty: Dict, pool: List[Dict]) -> tuple:
    """Returns (now, was, basis, flag, source) for a single store, or None."""
    label = meta["label"]
    for term in ([label] + meta.get("search_terms", []))[:4]:
        cands = sf_search(store, term)
        if not cands:
            continue
        cand = _best_search_candidate(label, cands)
        if not cand:
            continue
        res = _price_from_search(qty, cand)
        if not res or not res[0] or res[0] <= 0:
            continue
        now, was, basis = res
        # Plausibility guard, both directions. A per-unit price under 15% of
        # the bank baseline is far more likely a parsing glitch (e.g. a
        # multi-pack unit price misread) than a genuine 85%+ discount. A
        # price over 4x baseline is far more likely a wrong-product match or
        # a per-100g/per-kg mixup (e.g. matching "oven bake fish" to an
        # unrelated premium item, or reading a $/100g figure as $/kg) than a
        # genuine price — reject either rather than publish a number that
        # makes one recipe look absurdly cheap or absurdly expensive.
        baseline = meta.get("baseline") or 0
        if baseline > 0 and not (baseline * 0.15 <= now <= baseline * 4.0):
            continue
        return (now, was, basis, "live", "search")

    rtok = _content_tokens(label)
    need = 2 if len(rtok) >= 2 else 1
    best, best_shared = None, 0
    for sc in pool:
        if sc["code"] != store[0]:   # 'c' or 'w' — svgData pool is store-tagged
            continue
        shared = len(rtok & sc["toks"])
        if shared >= need and shared > best_shared:
            best, best_shared = sc, shared
    if best:
        res = _price_from_svgdata(qty, best, meta["baseline"])
        if res:
            now, was, basis = res
            baseline = meta.get("baseline") or 0
            if baseline <= 0 or (baseline * 0.15 <= now <= baseline * 4.0):
                return (now, was, basis, "live", "svgdata")
    return None

def price_ingredient_catalogue(ingredients: Dict, all_items: List[Dict]) -> Dict:
    """
    Search-price every ingredient at EACH store independently (not "stop at
    the first match, usually Coles") so single-store mode has genuine
    per-store prices rather than one blended price relabelled. Produces a
    genuine PER-UNIT price ($/kg, $/L, $/ea or $/pack) rather than a price
    scaled to any one recipe's portion — the step that used to happen
    per-selected-recipe; doing it once per ingredient is what lets the whole
    bank be costed for free.
    """
    pool = [{
        "price": it.get("price"), "code": _store_code(it.get("store", "")),
        "toks": _content_tokens(it.get("product", "")),
    } for it in all_items]

    priced = {}
    stats = {"matched": 0, "total": len(ingredients), "scraped": len(all_items),
              "via_search": 0, "via_svgdata": 0, "via_baseline": 0}

    for slug, meta in ingredients.items():
        qty = _unit_probe_qty(meta["unit"])
        by_store = {}
        any_live = False
        for store, code in (("coles", "c"), ("woolworths", "w")):
            got = _price_one_store(store, meta, qty, pool)
            if got:
                now, was, basis, flag, src = got
                by_store[code] = {"now": now, "was": was, "basis": basis, "flag": flag}
                any_live = True
                stats["via_search" if src == "search" else "via_svgdata"] += 1
            else:
                by_store[code] = {"now": meta["baseline"], "was": None,
                                   "basis": "bank baseline", "flag": "est"}

        if any_live:
            stats["matched"] += 1
        else:
            stats["via_baseline"] += 1

        pref = meta.get("store_pref", "e")
        default = by_store.get(pref) if pref in ("c", "w") else None
        if not default or default["flag"] != "live":
            # fall back to whichever store found a live price; else baseline
            default = next((v for v in by_store.values() if v["flag"] == "live"), by_store["c"])

        priced[slug] = {
            "now": default["now"], "was": default["was"],
            "basis": default["basis"], "flag": default["flag"],
            "by_store": by_store,
        }

    return priced, stats

def annotate_recipes(recipes: List[Dict], ingredients: Dict, priced: Dict) -> List[Dict]:
    """
    Compute each recipe's cost/was/saving at its own base `serves`, using the
    priced ingredient catalogue. Every recipe in the bank gets this — not just
    a pre-selected twelve — so the planner can select on real numbers.
    """
    out = []
    for r in recipes:
        cost = was_cost = 0.0
        any_was = False
        priced_items = []
        for ing in r.get("ingredients", []):
            slug = ing["ing"]
            meta = ingredients.get(slug, {})
            p = priced.get(slug, {"now": 0, "was": None, "flag": "est"})

            unit = meta.get("unit", "pack")
            qty = ing.get("qty")

            if unit == "kg" and qty:
                factor = qty / 1000.0
            elif unit == "L" and qty:
                factor = qty / 1000.0
            elif unit == "ea" and qty:
                factor = qty
            else:
                factor = 1.0   # pack / shared / pantry: one unit regardless of qty text

            now = round((p["now"] or 0) * factor, 2)
            item_was = round((p["was"] or 0) * factor, 2) if p.get("was") else None

            by_store_scaled = {}
            for code, sp in p.get("by_store", {}).items():
                sc_now = round((sp["now"] or 0) * factor, 2)
                sc_was = round((sp["was"] or 0) * factor, 2) if sp.get("was") else None
                by_store_scaled[code] = {"now": sc_now, "was": sc_was, "flag": sp.get("flag", "est")}

            # pantry items are assumed already-owned by default in the app (the
            # planner lets a household mark them owned); still priced here so
            # the app can add them back in for a "first shop" total.
            cost += now
            if item_was and item_was > now:
                was_cost += item_was
                any_was = True
            else:
                was_cost += now

            priced_items.append({
                "ing": slug, "label": meta.get("label", slug), "qty": qty,
                "unit": unit, "role": ing.get("role", "scales"),
                "note": ing.get("note"),
                "now": now, "was": item_was, "flag": p.get("flag", "est"),
                "by_store": by_store_scaled,
            })

        saving = round(was_cost - cost, 2) if any_was else 0.0
        pct = round(saving / was_cost * 100, 1) if any_was and was_cost > 0 else 0.0

        rec = dict(r)
        rec["priced_ingredients"] = priced_items
        rec["cost"] = round(cost, 2)
        rec["cost_per_serve"] = round(cost / max(r.get("serves", 1), 1), 2)
        rec["saving"] = saving
        rec["saving_pct"] = pct
        rec["hero_on_special"] = any(
            pi["flag"] == "live" and pi["was"] and pi["was"] > pi["now"]
            for pi in priced_items if pi["role"] == "hero"
        )
        out.append(rec)
    return out

# ============ JSON GENERATION ============
def generate_week_data(recipes: List[Dict], ingredients: Dict, coles_saleid: str,
                        woolies_saleid: str, ing_stats: Dict) -> Dict:
    """
    Publish the WHOLE priced bank. The app selects from this — the generator's
    job is accurate pricing, not picking favourites.
    """
    now = datetime.now()

    def _cat_date(s):
        if not s:
            return None
        return str(s).replace("/", "-").split(" ")[0]

    cm_c = CATALOGUE_META.get("coles", {})
    cm_w = CATALOGUE_META.get("woolworths", {})
    cat_start = _cat_date(cm_c.get("start") or cm_w.get("start"))
    cat_end = _cat_date(cm_c.get("end") or cm_w.get("end"))

    total_possible_saving = round(sum(r["saving"] for r in recipes), 2)
    on_special = sum(1 for r in recipes if r["hero_on_special"])

    if ing_stats["scraped"] == 0:
        note = ("Catalogue scrape returned no items this week — all prices are "
                "bank baselines. Check the run log / selectors.")
    else:
        note = (f"Priced {ing_stats['matched']} of {ing_stats['total']} ingredients "
                f"from this week's catalogue ({ing_stats['via_search']} by search, "
                f"{ing_stats['via_svgdata']} by catalogue pool, "
                f"{ing_stats['via_baseline']} on bank baseline).")

    return {
        "schema": 2,
        "metadata": {
            "generated": now.isoformat(),
            "week_start": cat_start or "this week",
            "week_end": cat_end or "next week",
            "coles_saleid": coles_saleid,
            "coles_url": f"https://www.coles.com.au/catalogues/view#view=list&saleId={coles_saleid}&areaName=c-wa-met",
            "woolies_saleid": woolies_saleid,
            "woolies_url": f"https://www.woolworths.com.au/shop/catalogue/view#view=list&saleId={woolies_saleid}&areaName=WA",
            "note": note,
            "catalogue_start": cat_start,
            "catalogue_end": cat_end,
            "ingredients_matched": ing_stats["matched"],
            "ingredients_total": ing_stats["total"],
            "recipes_on_special": on_special,
            "total_possible_saving": total_possible_saving,
        },
        "ingredients": ingredients,
        "recipes": recipes,
    }

# ============ GITHUB COMMIT & PUSH ============
def push_to_github(week_data: Dict, github_token: str, github_repo: str, github_email: str) -> bool:
    try:
        repo_path = os.getenv("REPO_PATH", os.path.expanduser("~/mealplanner"))
        if not os.path.exists(repo_path):
            print(f"[ERROR] Repo not found at {repo_path}")
            print(f"  Clone it first: git clone https://{github_token}@github.com/{github_repo}.git {repo_path}")
            return False

        os.chdir(repo_path)
        with open("week-data.json", "w") as f:
            json.dump(week_data, f, indent=2)

        subprocess.run(["git", "config", "user.email", github_email], check=True)
        subprocess.run(["git", "config", "user.name", "Meal Planner Bot"], check=True)
        subprocess.run(["git", "add", "week-data.json"], check=True)
        subprocess.run(["git", "commit", "-m",
                         f"Weekly price update: {week_data['metadata']['week_start']} – "
                         f"{week_data['metadata']['week_end']}"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("[\u2713] Pushed to GitHub")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Git operation failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to push: {e}")
        return False

# ============ MAIN ============
def main():
    print("=" * 60)
    print("Meal Planner — Weekly Price Generator (pricing-first, v2)")
    print("=" * 60)

    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "--coles" and i + 1 < len(sys.argv):
                globals()["COLES_SALEID"] = sys.argv[i + 2]
            if arg == "--woolies" and i + 1 < len(sys.argv):
                globals()["WOOLIES_SALEID"] = sys.argv[i + 2]

    print(f"\n[1/4] Loading ingredient catalogue + recipe bank...")
    ingredients = load_ingredients("ingredients.json")
    recipes = load_recipes("recipes.json")
    print(f"  {len(ingredients)} ingredients, {len(recipes)} recipes")

    if os.getenv("SF_AUTO_RESOLVE") == "1":
        print("  [SF] Auto-resolving current catalogue ids...")
        for st in ("coles", "woolworths"):
            rid = sf_resolve_catalogue_id(st)
            if rid:
                old = SALEFINDER[st]["catalogue"]
                SALEFINDER[st]["catalogue"] = rid
                print(f"    {st}: {old or '(unset)'} -> {rid}")
            else:
                print(f"    {st}: could not resolve, keeping {SALEFINDER[st]['catalogue'] or '(unset)'}")

    print(f"\n[2/4] Fetching Coles catalogue (saleId {COLES_SALEID})...")
    coles_items = fetch_catalogue(COLES_URL, "Coles")
    print(f"\n[2b/4] Fetching Woolworths catalogue (saleId {WOOLIES_SALEID})...")
    woolies_items = fetch_catalogue(WOOLIES_URL, "Woolworths")
    all_items = coles_items + woolies_items

    print(f"\n[3/4] Pricing the ingredient catalogue ({len(ingredients)} ingredients)...")
    priced, ing_stats = price_ingredient_catalogue(ingredients, all_items)
    print(f"  Priced {ing_stats['matched']}/{ing_stats['total']} live "
          f"({ing_stats['via_search']} search, {ing_stats['via_svgdata']} catalogue pool), "
          f"{ing_stats['via_baseline']} on bank baseline")

    print(f"\n[4/4] Costing every recipe against the priced catalogue...")
    recipes = annotate_recipes(recipes, ingredients, priced)
    on_special = sum(1 for r in recipes if r["hero_on_special"])
    best = sorted(recipes, key=lambda r: -r["saving_pct"])[:5]
    print(f"  {on_special}/{len(recipes)} recipes have their hero ingredient on special")
    print(f"  Best savings this week:")
    for r in best:
        print(f"    {r['saving_pct']:5.1f}%  ${r['saving']:5.2f} off  {r['name']}")

    week_data = generate_week_data(recipes, ingredients, COLES_SALEID, WOOLIES_SALEID, ing_stats)

    print(f"\nWriting week-data.json...")
    repo_path = os.getenv("REPO_PATH", ".")
    out_path = os.path.join(repo_path, "week-data.json")
    with open(out_path, "w") as f:
        json.dump(week_data, f, indent=2)
    print(f"  Wrote {out_path}")

    if os.getenv("DOCKET_PUSH") == "1":
        print("  DOCKET_PUSH=1 set — pushing from the script...")
        push_to_github(week_data, GITHUB_TOKEN, GITHUB_REPO, GITHUB_EMAIL)
    else:
        print("  Skipping git push (handled by CI; set DOCKET_PUSH=1 to push from the script).")

    print(f"\n[\u2713] Done! {ing_stats['matched']}/{ing_stats['total']} ingredients priced live; "
          f"{len(recipes)} recipes costed.")

if __name__ == "__main__":
    main()
