"""Fetch listings for a vehicle profile from Carfax, Toyota/Lexus Certified and toyota.com as flat dicts."""

import json
import re
import time
import urllib.parse
import urllib.request

from .profiles import CROWN, CROWN_PLATINUM_VIN

CARFAX_API = "https://helix.carfax.com/search/v2/vehicles"
TOYOTA = "https://www.toyotacertified.com"
TCOM_SEARCH = "https://www.toyota.com/search-inventory/model/toyotacrown/?zipcode={zip}"
LEXUS_CPO_SEARCH = "https://www.lexus.com/lcertified/search-inventory?zipcode={zip}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
PLATINUM_VIN_PREFIX = CROWN_PLATINUM_VIN
UNKNOWN_DISTANCE = 9999
SWEPT = "*"  # dealer-cache marker: the whole locator was paged, so a missing code is not in it; one per brand


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read(), strict=False)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def is_platinum(vin):
    return vin.upper().startswith(PLATINUM_VIN_PREFIX)


def norm_trim(raw, vin, profile=CROWN):
    return profile.trim(vin, raw)


FAMILY_WORDS = (("white", "White"), ("inked", "Black"), ("storm cloud", "Gray"), ("heavy metal", "Gray"),
                ("gray", "Gray"), ("grey", "Gray"), ("silver", "Gray"), ("bronze", "Bronze"), ("red", "Red"),
                ("blue", "Blue"), ("black", "Black"), ("tan", "Tan"), ("saddle", "Tan"), ("brown", "Brown"))


def clean_paint(raw):
    s = re.sub(r"\[[^\]]*\]|\(\w+\)|\*", "", (raw or "").replace("\xa0", " ")).strip(" /")
    return re.sub(r"\s+", " ", s).title() or None


def family(name, hint=None):
    s = (name or "").lower()
    for word, fam in FAMILY_WORDS:
        if word in s:
            return fam
    hint = (hint or "").strip().title()
    return hint if hint and hint != "Unspecified" else None


def exterior(raw, hint=None):
    """(paint name, color family, two-tone) from a source's paint string and its own family guess.
    Two-tone Crowns carry a black roof: 'OXYGEN WHITE/BLACK', 'BLACK(227)/RED(3U5)', '... with Black bi-tone'."""
    s = clean_paint(raw)
    if not s:
        fam = family(None, hint)
        return (fam, fam, False) if fam else (None, None, False)
    two = "bi-tone" in s.lower() or "/" in s
    if two:
        parts = [p.strip() for p in re.split(r"/| with ", s, flags=re.I) if p.strip()]
        base = next((p for p in parts if p.lower() not in ("black", "black bi-tone")), parts[0])
        base = {"Red": "Finish Line Red", "Metal": "Heavy Metal"}.get(base, base)
        s = f"{base} / Black roof"
    else:
        base = s
    return s, family(base, hint), two


def interior(raw, hint=None):
    fam = family(clean_paint(raw), None) or family(None, hint)
    return fam


USE_ORDER = ("Rental", "Commercial", "Fleet/corporate", "Multiple", "Lease", "Personal")


def prior_use(labels):
    """Normalize source use labels to the most concerning one, or None when no source says."""
    found = set()
    for raw in labels:
        s = (raw or "").lower()
        if "rental" in s:
            found.add("Rental")
        elif "commercial" in s:
            found.add("Commercial")
        elif "fleet" in s or "corporate" in s:
            found.add("Fleet/corporate")
        elif "multiple" in s:
            found.add("Multiple")
        elif "lease" in s:
            found.add("Lease")
        elif "personal" in s:
            found.add("Personal")
    return next((u for u in USE_ORDER if u in found), None)


def listing(source, vin, year, trim, price, miles, distance, dealer, city, state, url,
            one_owner=False, accident=False, condition="cpo", listed_since=None, msrp=None, note=None,
            doc_fee=None, value=None, followers=None, ext=(None, None, False), int_color=None, fees=None,
            msrp_only=False, use=None, profile=CROWN, url_exact=None, dealer_url=None):
    return dict(source=source, model=profile.key, vin=vin, year=int(year), trim=norm_trim(trim, vin, profile), price=int(price),
                miles=int(miles or 0), distance=int(distance), dealer=dealer, city=city, state=state,
                url=url, one_owner=bool(one_owner), accident=bool(accident), condition=condition,
                listed_since=str(listed_since)[:10] if listed_since else None,
                msrp=int(msrp) if msrp else None, note=note or None,
                doc_fee=int(doc_fee) if doc_fee is not None else None, value=int(value) if value else None,
                followers=int(followers) if followers is not None else None,
                ext_color=ext[0], ext_family=ext[1], two_tone=bool(ext[2]), int_color=int_color,
                fees_json=json.dumps(fees) if fees else None, msrp_only=bool(msrp_only),
                prior_use="New" if condition == "new" else use,
                url_exact=bool(url_exact if url_exact is not None else "carfax.com/vehicle/" in (url or "")),
                dealer_url=dealer_url or None)


FEE_RULES = (
    ("optional", r"optional|benefit|protect|guard|package|appearance|nitrogen|etch|theft|warranty|maintenance|coating|tint"),
    ("suspect", r"dealer service|service (charge|fee)|pre-?delivery|\bprep\b|processing|transfer|recondition|market|"
                r"adjust|admin|handling|dealer fee|convenience"),
    ("filing", r"filing|registration|title|\btag\b|e-?file"),
    ("doc", r"\bdoc|document"),
    ("suspect", r"."),
)
ADDON_WORDS = r"guard|protect|screen protector|pre-?delivery|\bpds\b|gallons of gas|fueling|nitrogen|etch|coating|cable charge"


def fee_category(name):
    s = (name or "").lower()
    return next(cat for cat, rx in FEE_RULES if re.search(rx, s))


def parse_fees(fees):
    """Carfax lists a summary 'document_fee' (the TOTAL of every fee) followed by the itemized lines. Returns
    (what you would pay unless you refuse the optional items, [(name, amount, category)])."""
    fees = [f for f in fees or [] if f.get("fee") is not None]
    if not fees:
        return None, []
    total = next((f["fee"] for f in fees if f.get("feeType") == "document_fee"), None)
    items = [(f["feeType"], int(f["fee"]), fee_category(f["feeType"])) for f in fees if f.get("feeType") != "document_fee"]
    if total is not None and sum(a for _, a, _ in items) != total:
        items = [("Doc and other fees", int(total), "doc")]
    return sum(a for _, a, c in items if c != "optional"), items


def doc_fee(fees):
    return parse_fees(fees)[0]


def tcom_addons(v):
    """Port- and dealer-installed extras on a new car: [(name, amount or None, category)]."""
    out = []
    for o in v.get("options") or []:
        if o.get("optionType") in ("L", "D") and o.get("marketingName") and re.search(ADDON_WORDS, o["marketingName"].lower()):
            out.append((re.sub(r"<[^>]+>", "", o["marketingName"]).strip(), None, "addon"))
    dio = (v.get("price") or {}).get("dioTotalDealerSellingPrice") or 0
    if dio:
        out.append(("Dealer-installed options", int(dio), "addon"))
    return out


def carfax(zip_code, profile=CROWN, get=http_get, dealers=None, new=False):
    year_min, year_max = profile.years
    raw, page, pages = {}, 1, 1
    if new:
        year_max += 1
    while page <= pages:
        params = {
            "zip": zip_code, "radius": 3000, "sort": "PRICE_ASC", "vehicleCondition": "NEW" if new else "USED",
            "make": profile.make, "model": profile.carfax_model, "yearMin": year_min, "yearMax": year_max,
            "rows": 25, "page": page}
        if not new:
            params["certified"] = "true"
        data = get(f"{CARFAX_API}?{urllib.parse.urlencode(params)}")
        raw.update((l["vin"], l) for l in data["listings"])
        pages = data.get("totalPageCount") or 1
        page += 1
    out = []
    for l in raw.values():
        price = l.get("currentPrice") or l.get("listPrice")
        if not ((new or l.get("certified")) and price and year_min <= l["year"] <= year_max and profile.matches(l["vin"])):
            continue
        d = l.get("dealer") or {}
        out.append(listing(
            "carfax_new" if new else "carfax", l["vin"], l["year"], l.get("trim"), price, l.get("mileage"),
            round(l.get("distanceToDealer") or UNKNOWN_DISTANCE), d.get("name", ""),
            d.get("city", ""), d.get("state", ""), l.get("vdpUrl", ""), l.get("oneOwner"),
            not new and not l.get("noAccidents"), "new" if new else "cpo", l.get("firstSeen"),
            doc_fee=parse_fees(l.get("fees"))[0], fees=parse_fees(l.get("fees"))[1],
            value=l.get("onePrice"), followers=l.get("followCount"),
            ext=exterior(None, l.get("exteriorColor")), int_color=interior(None, l.get("interiorColor")),
            use=prior_use(h.get("useType") for h in (l.get("vehicleUseHistory") or {}).get("history") or []), profile=profile,
            dealer_url=d.get("dealerInventoryUrl")))
    return out


def carfax_new(zip_code, profile=CROWN, get=http_get, dealers=None):
    return carfax(zip_code, profile, get, dealers, new=True)


def toyota_dealers(zip_code, wanted, get=http_get, cache=None, max_pages=40, brand=1):
    """dealerCd -> (name, city, state, miles from zip). Pages the Toyota (brand 1, TCUV) or Lexus (brand 2)
    locator only until `wanted` is covered."""
    found = cache if cache is not None else {}
    swept = SWEPT if brand == 1 else f"{SWEPT}{brand}"
    start = 0
    while wanted - found.keys() and swept not in found and start < max_pages * 50:
        params = {
            "searchMode": "proximityOnly", "searchType": "zipCode", "proximityMode": "radius",
            "zipcode": zip_code, "radiusMiles": 5000, "brandId": brand, "resultsFormat": "json",
            "attributeKey": "TCUV", "resultsMax": 50, "resultsStart": start}
        if brand != 1:
            del params["attributeKey"]
        q = urllib.parse.urlencode(params)
        area = get(f"{TOYOTA}/rest/dealers?{q}").get("showDealerLocatorDataArea") or {}
        rows = [d for loc in area.get("dealerLocator", []) for d in loc.get("dealerLocatorDetail", [])]
        if not rows:
            found[swept] = ("", "", "", 0, None)
            break
        for r in rows:
            org = r["dealerParty"]["specifiedOrganization"]
            addr = org["primaryContact"][0]["postalAddress"]
            found[r["dealerParty"]["partyID"]["value"]] = (
                org["companyName"]["value"], addr["cityName"]["value"],
                addr["stateOrProvinceCountrySubDivisionID"]["value"],
                round(float(r["proximityMeasureGroup"]["proximityMeasure"]["value"])), dealer_url(org))
        start += 50
    return found


def dealer_url(org):
    """The dealer's certified/used inventory page from the locator's web links, else its home page."""
    urls = [u.get("uriid", {}).get("value") for c in org.get("primaryContact") or []
            for u in c.get("uricommunication") or [] if u.get("uriid", {}).get("value")]
    for pattern in (r"certified", r"pre-?owned|used"):
        hit = next((u for u in urls if re.search(pattern, u, re.I)), None)
        if hit:
            return hit
    return min(urls, key=len) if urls else None


def toyota(zip_code, profile=CROWN, get=http_get, dealers=None):
    year_min, year_max = profile.years
    raw, page, pages = {}, 1, 1
    while page <= pages:
        q = urllib.parse.urlencode({
            "zipcode": zip_code, "pageNo": page, "pageSize": 50, "brand": profile.brand,
            "radius": "5000miles", "certificationStatus": "CERTIFIED", "yearMin": year_min,
            "yearMax": year_max, "seriesCode": profile.series})
        data = get(f"{TOYOTA}/rest/uvii/vehicles?{q}")
        raw.update((v["vin"], v) for v in data.get("vehicleSummary", []))
        pages = (data.get("pagination") or {}).get("totalPages") or 1
        page += 1
    raw = {vin: v for vin, v in raw.items() if profile.matches(vin)}
    dealers = toyota_dealers(zip_code, {v["dealerCd"] for v in raw.values()}, get, dealers, brand=profile.dealer_brand)
    out = []
    for v in raw.values():
        p = v.get("price") or {}
        if not (p.get("sellingPrice") and year_min <= int(v["year"]) <= year_max):
            continue
        name, city, state, dist, site = dealers.get(
            v["dealerCd"], (v.get("owningDealerName", v["dealerCd"]), "", "", UNKNOWN_DISTANCE, None))
        if profile.brand == "TOYOTA":
            url, exact = f"{TOYOTA}/content/tcuv/us/en/vdp?vin={v['vin']}", True
        else:
            url, exact = site or LEXUS_CPO_SEARCH.format(zip=zip_code), False
        cfx = v.get("carFaxReport") or {}
        out.append(listing(
            "toyota", v["vin"], v["year"], v.get("grade"), p["sellingPrice"], v.get("mileage"), dist, name,
            city, state, url,
            (cfx.get("ownerHistory") or {}).get("oneOwner"),
            (cfx.get("accident") or {}).get("hasAccidents"), "cpo", v.get("acquiredDate"), p.get("totalMsrp"),
            ext=exterior((v.get("extColor") or {}).get("marketingName"),
                         ((v.get("extColor") or {}).get("commonName") or {}).get("generic")),
            int_color=interior((v.get("intColor") or {}).get("marketingName"),
                               ((v.get("intColor") or {}).get("commonName") or {}).get("generic")),
            use=prior_use([(cfx.get("useType") or {}).get("iconText"), "rental" if v.get("isPreviousRental") else None]),
            profile=profile, url_exact=exact, dealer_url=site))
    return out


def tcom_inventory(zip_code, timeout_s=90):
    """New-car inventory from toyota.com. Its GraphQL call only fires in a headed browser, so an
    off-screen Chrome window loads the search page and the page's own query is widened to nationwide."""
    from playwright.sync_api import sync_playwright

    pages, done = [], []

    def handler(route):
        body = route.request.post_data or ""
        if "locateVehiclesByZip" not in body or done:
            return route.continue_()
        q = json.loads(body)
        base = re.sub(r"distance: \d+", "distance: 5000", q["query"]).replace("interiorMedia: true", "interiorMedia: false")
        page_no, resp = 1, None
        while True:
            q["query"] = re.sub(r"pageNo: \d+", f"pageNo: {page_no}", base)
            resp = route.fetch(post_data=json.dumps(q))
            data = resp.json()["data"]["locateVehiclesByZip"]
            pages.append(data)
            if page_no >= (data["pagination"]["totalPages"] or 1):
                break
            page_no += 1
        done.append(True)
        route.fulfill(response=resp)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False, args=[
            "--disable-blink-features=AutomationControlled", "--window-position=-2400,-2400", "--window-size=900,700"])
        try:
            pg = browser.new_page()
            pg.route("**/graphql", handler)
            pg.goto(TCOM_SEARCH.format(zip=zip_code), wait_until="domcontentloaded", timeout=timeout_s * 1000)
            deadline = time.time() + timeout_s
            while not done and time.time() < deadline:
                pg.wait_for_timeout(250)
        finally:
            browser.close()
    if not done:
        raise TimeoutError("toyota.com never issued its inventory query")
    return [v for d in pages for v in d["vehicleSummary"]]


def parse_tcom(vehicles, zip_code, profile, dealers):
    year_min, year_max = profile.years
    out = []
    for v in {v["vin"]: v for v in vehicles}.values():
        p = v.get("price") or {}
        dealer_price = p.get("advertizedPrice") or p.get("sellingPrice") or p.get("nonSpAdvertizedPrice")
        price = dealer_price or p.get("totalMsrp")
        if v.get("isPreSold") or not price or not (year_min <= int(v["year"]) <= year_max + 1):
            continue
        _, city, state, _, _ = dealers.get(v.get("dealerCd"), ("", "", "", 0, None))
        out.append(listing(
            "toyota_new", v["vin"], v["year"], v.get("grade"), price, v.get("inventoryMileage"),
            v.get("distance") if v.get("distance") is not None else UNKNOWN_DISTANCE,
            v.get("dealerMarketingName") or "", city, state,
            v.get("dealerWebsite") or TCOM_SEARCH.format(zip=zip_code), condition="new",
            msrp=p.get("totalMsrp"), note=v.get("inventoryStatus"), fees=tcom_addons(v), msrp_only=not dealer_price,
            ext=exterior((v.get("extColor") or {}).get("marketingName"), ((v.get("extColor") or {}).get("colorFamilies") or [None])[0]),
            int_color=interior((v.get("intColor") or {}).get("marketingName"), ((v.get("intColor") or {}).get("colorFamilies") or [None])[0])))
    return out


def toyota_new(zip_code, profile=CROWN, get=http_get, dealers=None, fetch=tcom_inventory):
    vehicles = fetch(zip_code)
    dealers = toyota_dealers(zip_code, {v["dealerCd"] for v in vehicles if v.get("dealerCd")}, get, dealers)
    return parse_tcom(vehicles, zip_code, profile, dealers)


SOURCES = {"carfax": carfax, "toyota": toyota, "carfax_new": carfax_new, "toyota_new": toyota_new}
