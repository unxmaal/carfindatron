"""Re-record the test fixtures from live sources, trimmed to the fields the code reads.

Record from a neutral, public ZIP, never the home one: fixtures are committed to a public repository and dealer
distances would locate the origin.  uv run python scripts/record_fixtures.py --zip 10001
"""

import argparse
import json
import urllib.parse
from pathlib import Path

from carfindatron import sources
from carfindatron.profiles import CROWN, ES300H

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
CARFAX_KEEP = ("vin", "year", "trim", "subTrim", "listPrice", "currentPrice", "mileage", "certified", "distanceToDealer",
               "vdpUrl", "oneOwner", "noAccidents", "firstSeen", "fees", "onePrice", "followCount", "exteriorColor",
               "interiorColor", "vehicleUseHistory")
TOYOTA_KEEP = ("vin", "year", "grade", "price", "mileage", "dealerCd", "owningDealerName", "acquiredDate",
               "isPreviousRental", "extColor", "intColor")
TCOM_KEEP = ("vin", "year", "grade", "dealerCd", "dealerMarketingName", "dealerWebsite", "distance", "isPreSold",
             "inventoryStatus", "inventoryMileage", "price")


def trim_carfax(d):
    return {"totalPageCount": d["totalPageCount"], "listings": [
        {k: l.get(k) for k in CARFAX_KEEP}
        | {"dealer": {k: (l.get("dealer") or {}).get(k) for k in ("name", "city", "state", "dealerInventoryUrl")}}
        for l in d["listings"]]}


def trim_toyota(d):
    area = d.get("showDealerLocatorDataArea") or {}
    area.pop("dealerMetaData", None)
    for loc in area.get("dealerLocator", []):
        rows = []
        for r in loc.get("dealerLocatorDetail", []):
            dp = r["dealerParty"]
            org = dp["specifiedOrganization"]
            contact = org["primaryContact"][0]
            addr = contact["postalAddress"]
            uris = [{"uriid": {"value": sources.dealer_url(org)}}] if sources.dealer_url(org) else []
            rows.append({"dealerParty": {"partyID": dp["partyID"], "specifiedOrganization": {
                "companyName": org["companyName"], "primaryContact": [{
                    "postalAddress": {k: addr[k] for k in ("cityName", "stateOrProvinceCountrySubDivisionID")},
                    "uricommunication": uris}]}},
                "proximityMeasureGroup": {"proximityMeasure": r["proximityMeasureGroup"]["proximityMeasure"]}})
        loc["dealerLocatorDetail"] = rows
    if "vehicleSummary" in d:
        d["vehicleSummary"] = [{k: v.get(k) for k in TOYOTA_KEEP} | {"carFaxReport": {
            k: (v.get("carFaxReport") or {}).get(k) for k in ("ownerHistory", "accident", "useType")}}
            for v in d["vehicleSummary"]]
    return d


def recorder(prefix, api_store):
    def get(url):
        d = sources.http_get(url)
        if url.startswith(sources.CARFAX_API):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            d = trim_carfax(d)
            (FIX / f"{prefix}{q['page'][0]}.json").write_text(json.dumps(d))
            return d
        d = trim_toyota(d)
        api_store[url] = d
        return d
    return get


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zip", required=True)
    a = p.parse_args()
    for old in FIX.glob("*.json"):
        old.unlink()
    toyota_api, lexus_api = {}, {}
    print("crown carfax cpo", len(sources.carfax(a.zip, CROWN, get=recorder("h", toyota_api))))
    print("crown carfax new", len(sources.carfax_new(a.zip, CROWN, get=recorder("hn", toyota_api))))
    print("crown toyota cpo", len(sources.toyota(a.zip, CROWN, get=recorder("unused", toyota_api), dealers={})))
    vehicles = sources.tcom_inventory(a.zip)
    (FIX / "tcom.json").write_text(json.dumps([{k: v.get(k) for k in TCOM_KEEP} | {
        "extColor": {k: (v.get("extColor") or {}).get(k) for k in ("marketingName", "colorFamilies")},
        "intColor": {k: (v.get("intColor") or {}).get(k) for k in ("marketingName", "colorFamilies")},
        "options": [{k: o.get(k) for k in ("marketingName", "optionType")} for o in v.get("options") or []]}
        for v in vehicles]))
    print("crown toyota.com new", len(vehicles))
    sources.toyota_dealers(a.zip, {v["dealerCd"] for v in vehicles if v.get("dealerCd")},
                           recorder("unused", toyota_api), cache={})
    (FIX / "toyota.json").write_text(json.dumps(toyota_api))
    print("es carfax cpo", len(sources.carfax(a.zip, ES300H, get=recorder("es_h", lexus_api))))
    print("es lexus cpo", len(sources.toyota(a.zip, ES300H, get=recorder("unused", lexus_api), dealers={})))
    (FIX / "lexus.json").write_text(json.dumps(lexus_api))
    (FIX / "ZIP").write_text(a.zip + "\n")


if __name__ == "__main__":
    main()
