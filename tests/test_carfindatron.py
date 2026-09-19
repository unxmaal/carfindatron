import copy
from datetime import date
import json
import random
import re
from statistics import median
import sqlite3
import urllib.parse
from pathlib import Path

import pytest

from carfindatron import analysis, cli, report, sources, store
from carfindatron.profiles import CROWN, ES300H

FIX = Path(__file__).parent / "fixtures"
ZIP = (FIX / "ZIP").read_text().strip()
TOYOTA = json.loads((FIX / "toyota.json").read_text())


def raw_pages(prefix):
    return [l for f in sorted(FIX.glob(f"{prefix}[0-9]*.json")) for l in json.loads(f.read_text())["listings"]]


def raw_toyota(prefix="rest/uvii"):
    return {v["vin"]: v for u, d in TOYOTA.items() if prefix in u for v in d.get("vehicleSummary", [])}


def dealer_rows(api):
    out = {}
    for u, d in api.items():
        for loc in (d.get("showDealerLocatorDataArea") or {}).get("dealerLocator", []):
            for r in loc.get("dealerLocatorDetail", []):
                a = r["dealerParty"]["specifiedOrganization"]["primaryContact"][0]["postalAddress"]
                out[r["dealerParty"]["partyID"]["value"]] = (a["cityName"]["value"], a["stateOrProvinceCountrySubDivisionID"]["value"])
    return out


TCOM = json.loads((FIX / "tcom.json").read_text())


LEXUS = json.loads((FIX / "lexus.json").read_text())


def fake_get(url):
    if url.startswith(sources.CARFAX_API):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        prefix = "es_h" if q["make"][0] == "Lexus" else "hn" if q["vehicleCondition"][0] == "NEW" else "h"
        return json.loads((FIX / f"{prefix}{q['page'][0]}.json").read_text())
    if url in TOYOTA:
        return copy.deepcopy(TOYOTA[url])
    if url in LEXUS:
        return copy.deepcopy(LEXUS[url])
    if "/rest/dealers?" in url:
        return {}
    raise KeyError(url)


def fake_sources(monkeypatch):
    for name in ("carfax", "toyota", "carfax_new"):
        fn = getattr(sources, name)
        monkeypatch.setitem(sources.SOURCES, name, lambda *a, fn=fn, **kw: fn(*a, get=fake_get, **kw))
    monkeypatch.setitem(sources.SOURCES, "toyota_new", lambda *a, **kw: sources.toyota_new(
        *a, get=fake_get, fetch=lambda z: copy.deepcopy(TCOM), **kw))


REAL_CONFIG = cli.CONFIG


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Tests never read or write the real ~/.config; the fixture ZIP stands in for the home one."""
    monkeypatch.setattr(cli, "CONFIG", tmp_path / "config.json")
    monkeypatch.setenv("CARFINDATRON_ZIP", ZIP)


@pytest.fixture(scope="module")
def carfax():
    return sources.carfax(ZIP, CROWN, get=fake_get)


@pytest.fixture(scope="module")
def toyota():
    return sources.toyota(ZIP, CROWN, get=fake_get)


@pytest.fixture
def con():
    return store.connect(":memory:")


def car(vin, price, miles=0, dist=0, **kw):
    return dict(vin=vin, year=2026, trim="Platinum", price=price, miles=miles, distance=dist, **kw)


def test_carfax_follows_every_page(carfax):
    raw = raw_pages("h")
    want = {l["vin"] for l in raw if l.get("certified") and (l.get("currentPrice") or l.get("listPrice"))
            and 2025 <= l["year"] <= 2026 and CROWN.matches(l["vin"])}
    assert len(json.loads((FIX / "h1.json").read_text())["listings"]) < len(raw)
    assert {l["vin"] for l in carfax} == want and {l["source"] for l in carfax} == {"carfax"}


def test_platinum_is_decided_by_vin_not_dealer_label(carfax):
    raw = [l for p in (1, 2, 3) for l in json.loads((FIX / f"h{p}.json").read_text())["listings"]]
    assert {l["vin"] for l in raw if l["trim"] == "Unspecified"}
    assert sources.norm_trim("Unspecified", "JTDAFAAF0T3000000") == "Platinum"
    assert sources.norm_trim("Platinum", "JTDAAAAF0T3000000") is None
    assert sum(l["trim"] == "Platinum" for l in carfax) == sum(sources.is_platinum(v) for v in {l["vin"] for l in carfax})


def test_toyota_normalizes_grades_and_resolves_every_dealer(toyota):
    raw = raw_toyota()
    assert len(toyota) == sum(1 for v in raw.values() if (v.get("price") or {}).get("sellingPrice"))
    assert {l["trim"] for l in toyota} <= {"XLE", "Limited", "Nightshade", "Platinum"} and "Platinum" in {l["trim"] for l in toyota}
    assert all(l["distance"] < sources.UNKNOWN_DISTANCE and l["state"] for l in toyota)
    rows = dealer_rows(TOYOTA)
    for l in toyota:
        v = raw[l["vin"]]
        assert l["price"] == v["price"]["sellingPrice"] and (l["city"], l["state"]) == rows[v["dealerCd"]]
    plat = [l for l in toyota if l["trim"] == "Platinum"]
    assert sum(l["accident"] for l in plat) == sum(bool(((raw[l["vin"]].get("carFaxReport") or {}).get("accident") or {}).get("hasAccidents")) for l in plat)


def test_merge_keeps_lowest_price_and_every_quote(con, carfax, toyota):
    run = store.record_run(con, ZIP, carfax + toyota, [])
    cars = {c["vin"]: c for c in store.merged(con, run)}
    both = {l["vin"] for l in carfax} & {l["vin"] for l in toyota}
    assert both
    for vin in both:
        cf = next(l["price"] for l in carfax if l["vin"] == vin)
        ty = next(l["price"] for l in toyota if l["vin"] == vin)
        assert cars[vin]["prices"] == {"carfax": cf, "toyota": ty} and cars[vin]["price"] == min(cf, ty)
        assert cars[vin]["url_exact"]
    assert len(cars) == len({l["vin"] for l in carfax + toyota})


def test_merge_takes_accident_from_either_source(con):
    a = sources.listing("carfax", "V", 2026, "Platinum", 50000, 1, 1, "", "", "", "", accident=True)
    b = sources.listing("toyota", "V", 2026, "Platinum", 49000, 1, 1, "", "", "", "")
    run = store.record_run(con, ZIP, [a, b], [])
    [c] = store.merged(con, run)
    assert c["accident"] and c["price"] == 49000


def listings(*pairs):
    return [dict(sources.listing("carfax", v, 2026, "Platinum", p, 1, 1, "", "", "GA", ""), trim="Platinum")
            for v, p in pairs]


def test_status_new_drop_gone_back_across_runs(con):
    r1 = store.record_run(con, "z", listings(("a", 50000), ("b", 48000)), [], ts="2026-01-01")
    c1 = store.merged(con, r1)
    assert store.status(con, r1, c1) == [] and {c["status"] for c in c1} == {"NEW"}
    r2 = store.record_run(con, "z", listings(("a", 49000)), [], ts="2026-01-02")
    c2 = store.merged(con, r2)
    assert store.status(con, r2, c2) == ["b"] and c2[0]["status"] == "DROP -1,000"
    r3 = store.record_run(con, "z", listings(("a", 49000), ("b", 48000)), [], ts="2026-01-03")
    c3 = {c["vin"]: c for c in store.merged(con, r3)}
    store.status(con, r3, list(c3.values()))
    assert c3["b"]["status"] == "BACK" and c3["a"]["status"] == ""


def test_partial_run_is_not_a_baseline(con):
    store.record_run(con, "z", listings(("a", 50000), ("b", 48000)), [], ts="2026-01-01")
    store.record_run(con, "z", listings(("a", 50000)), [["toyota", "boom"]], ts="2026-01-02")
    r3 = store.record_run(con, "z", listings(("a", 50000), ("b", 48000)), [], ts="2026-01-03")
    c3 = store.merged(con, r3)
    assert store.status(con, r3, c3) == [] and all(c["status"] == "" for c in c3)
    assert [p for _, p in store.price_history(con)["b"]] == [48000, 48000]


def test_rank_orders_by_weighted_cost_and_marks_pareto():
    a, b, c = car("a", 50000, 1000, 10), car("b", 49000, 20000, 900), car("c", 51000, 2000, 20)
    ranked = analysis.rank([a, b, c], per_mile=0.25)
    assert [x["vin"] for x in ranked] == ["a", "c", "b"]
    assert a["pareto"] and b["pareto"] and not c["pareto"]


def synthetic(n=80, ms_discount=3000, seed=1):
    rng = random.Random(seed)
    base = {"XLE": 38000, "Limited": 43000, "Nightshade": 45000, "Platinum": 52000}
    cars = []
    for i in range(n):
        trim, year, miles = rng.choice(list(base)), rng.choice([2025, 2026]), rng.randint(0, 40000)
        state = ["GA", "MS", "TX", "FL"][i % 4]
        price = base[trim] + (2000 if year == 2026 else 0) - 0.15 * miles + rng.gauss(0, 300)
        price -= ms_discount if state == "MS" else 0
        cars.append(dict(vin=f"v{i}", trim=trim, year=year, miles=miles, price=round(price), state=state,
                         distance=100 * (i % 4)))
    return cars


def test_fit_recovers_known_trim_year_and_mileage_effects():
    model = analysis.fit(synthetic(ms_discount=0))
    coef = model["coef"]
    assert abs(coef["trim:Platinum"] - 14000) < 400
    assert abs(coef["year:2026"] - 2000) < 400
    assert abs(coef["per_1k_miles"] + 150) < 20


def test_by_state_surfaces_the_cheap_state_first():
    cars = synthetic(ms_discount=3000)
    analysis.fit(cars)
    states = analysis.by_state(cars)
    assert states[0]["state"] == "MS" and states[0]["median_resid"] < -1500
    assert all(s["median_resid"] > -1500 for s in states[1:])


def test_fit_refuses_too_few_cars():
    assert analysis.fit(synthetic(n=6)) is None


def test_report_embeds_data_without_breaking_out_of_script():
    html = report.render({"x": "</script><script>alert(1)</script>"})
    assert html.count("</script>") == 1 and "<\\/script>" in html


def test_cli_end_to_end_writes_db_and_page(tmp_path, monkeypatch, capsys):
    fake_sources(monkeypatch)
    db, page = tmp_path / "c.db", tmp_path / "r.html"
    assert cli.main(["--db", str(db), "--html", str(page), "--profiles", "crown"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"Platinum: \d+ CPO, \d+ new", out) and "WARNING" not in out
    con = sqlite3.connect(db)
    cpo = {l["vin"] for l in sources.carfax(ZIP, CROWN, get=fake_get) + sources.toyota(ZIP, CROWN, get=fake_get, dealers={})}
    assert con.execute("SELECT COUNT(DISTINCT vin) FROM listings WHERE condition='cpo'").fetchone()[0] == len(cpo)
    assert con.execute("SELECT COUNT(DISTINCT vin) FROM listings WHERE condition='new'").fetchone()[0] > 600
    assert con.execute("SELECT COUNT(*) FROM dealers").fetchone()[0] > 0
    assert next(iter(cpo)) in page.read_text()
    assert cli.main(["--db", str(db), "--html", str(page), "--report-only", "--profiles", "crown"]) == 0


def test_cli_partial_failure_is_recorded_and_warned(tmp_path, monkeypatch, capsys):
    def boom(*a, **kw):
        raise OSError("blocked")
    fake_sources(monkeypatch)
    monkeypatch.setitem(sources.SOURCES, "toyota", boom)
    db = tmp_path / "c.db"
    assert cli.main(["--db", str(db), "--html", str(tmp_path / "r.html"), "--profiles", "crown"]) == 0
    assert "WARNING: crown:toyota failed: OSError: blocked" in capsys.readouterr().out
    assert sqlite3.connect(db).execute("SELECT ok FROM runs").fetchone()[0] == 0


def test_pareto_only_compares_within_a_trim():
    plat = car("p", 50000, 1000, 10)
    xle = dict(car("x", 38000, 500, 5), trim="XLE")
    analysis.rank([plat, xle], 0.25)
    assert plat["pareto"] and xle["pareto"]


def test_carfax_new_reads_new_listings_with_first_seen():
    new = sources.carfax_new(ZIP, CROWN, get=fake_get)
    assert new and {l["condition"] for l in new} == {"new"}
    assert all(l["listed_since"] and not l["accident"] for l in new)
    assert {l["vin"] for l in new} <= {l["vin"] for l in raw_pages("hn")}


def test_toyota_cpo_carries_acquired_date_and_msrp(toyota):
    raw = raw_toyota()
    dated = [l for l in toyota if raw[l["vin"]].get("acquiredDate")]
    assert dated
    for l in dated:
        assert l["listed_since"] == raw[l["vin"]]["acquiredDate"][:10] and l["msrp"] == raw[l["vin"]]["price"].get("totalMsrp")


def test_parse_tcom_skips_presold_and_prefers_dealer_price():
    got = {l["vin"]: l for l in sources.parse_tcom(TCOM, ZIP, CROWN, {})}
    presold = {v["vin"] for v in TCOM if v["isPreSold"]}
    assert presold and not presold & got.keys()
    assert {l["condition"] for l in got.values()} == {"new"} and {l["year"] for l in got.values()} <= {2026, 2027}
    for v in TCOM:
        p = v["price"]
        if v["vin"] in got and p["advertizedPrice"]:
            assert got[v["vin"]]["price"] == int(p["advertizedPrice"]) and got[v["vin"]]["msrp"] == p["totalMsrp"]


def test_toyota_new_resolves_known_dealer_locations():
    new = sources.toyota_new(ZIP, CROWN, get=fake_get, dealers={}, fetch=lambda z: copy.deepcopy(TCOM))
    rows = dealer_rows(TOYOTA)
    by = {v["vin"]: v for v in TCOM}
    located = [l for l in new if by[l["vin"]].get("dealerCd") in rows]
    assert len(located) > len(new) / 2
    assert all((l["city"], l["state"]) == rows[by[l["vin"]]["dealerCd"]] for l in located)


def test_old_database_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    old = sqlite3.connect(db)
    old.executescript("""CREATE TABLE runs (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, zip TEXT NOT NULL,
        ok INTEGER NOT NULL, errors TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE listings (run_id INTEGER NOT NULL, source TEXT NOT NULL, vin TEXT NOT NULL, year INTEGER,
        trim TEXT, price INTEGER, miles INTEGER, distance INTEGER, dealer TEXT, city TEXT, state TEXT, url TEXT,
        one_owner INTEGER, accident INTEGER, PRIMARY KEY (run_id, source, vin));
        INSERT INTO runs VALUES (1, '2026-09-18T00:00:00+00:00', '00000', 1, '[]');
        INSERT INTO listings VALUES (1, 'carfax', 'V', 2026, 'Platinum', 50000, 1, 1, '', '', 'GA', '', 0, 0);""")
    old.commit()
    con = store.connect(db)
    [c] = store.merged(con, 1)
    assert c["condition"] == "cpo" and c["listed_since"] is None and c["msrp"] is None


def test_dealer_cache_round_trips(con):
    store.save_dealers(con, ZIP, {"10130": ("Example Toyota", "Springfield", "IL", 7, "https://dealer.example/used")})
    assert store.load_dealers(con, ZIP) == {"10130": ("Example Toyota", "Springfield", "IL", 7, "https://dealer.example/used")}
    assert store.load_dealers(con, "90210") == {}


def test_trend_splits_new_and_cpo_and_ignores_accidents(con):
    ls = listings(("a", 50000), ("b", 40000))
    ls[1]["accident"] = True
    ls.append(dict(sources.listing("carfax_new", "n", 2026, "", 58000, 0, 5, "", "", "GA", "", condition="new"),
                   trim="Platinum"))
    store.record_run(con, "z", ls, [], ts="2026-01-01")
    [t] = report.trend(con)
    assert t["cpo"] == {"median": 50000, "min": 50000, "n": 1} and t["new"]["median"] == 58000


def test_days_listed_counts_from_earliest_source_date(tmp_path, monkeypatch):
    fake_sources(monkeypatch)
    con = store.connect(tmp_path / "c.db")
    run, _ = cli.scan(con, ZIP, [CROWN], ["carfax", "toyota"])
    payload = cli.build(con, run)
    run_day = date.fromisoformat(payload["run"]["ts"][:10])
    raw = raw_toyota()
    dated = [c for c in payload["cars"] if c["vin"] in raw and raw[c["vin"]].get("acquiredDate")]
    assert dated
    for c in dated:
        assert c["days"] == (run_day - date.fromisoformat(c["listed_since"])).days
        assert c["listed_since"] <= raw[c["vin"]]["acquiredDate"][:10]


def test_dealer_lookup_stops_after_a_full_sweep():
    calls = []

    def get(url):
        calls.append(url)
        return fake_get(url)
    cache = {}
    sources.toyota_dealers(ZIP, {"no-such-dealer"}, get, cache)
    swept = len(calls)
    assert sources.SWEPT in cache and swept > 1
    sources.toyota_dealers(ZIP, {"no-such-dealer"}, get, cache)
    assert len(calls) == swept


def test_subset_run_is_not_a_baseline_for_a_full_run(con):
    full = listings(("a", 50000)) + [dict(l, source="toyota_new", condition="new") for l in listings(("n", 58000))]
    store.record_run(con, "z", full, [], ts="2026-01-01")
    r2 = store.record_run(con, "z", listings(("a", 50000)), [], ts="2026-01-02")
    c2 = store.merged(con, r2)
    assert store.status(con, r2, c2) == [] and c2[0]["status"] == ""
    r3 = store.record_run(con, "z", full, [], ts="2026-01-03")
    c3 = store.merged(con, r3)
    assert store.status(con, r3, c3) == [] and all(c["status"] == "" for c in c3)


def test_days_listed_falls_back_to_first_scan_that_saw_the_car(tmp_path):
    con = store.connect(tmp_path / "c.db")
    new = dict(sources.listing("toyota_new", "N", 2026, "", 58000, 0, 5, "", "", "GA", "", condition="new"),
               trim="Platinum")
    store.record_run(con, "z", [new], [], ts="2026-09-01T00:00:00+00:00")
    r2 = store.record_run(con, "z", [new], [], ts="2026-09-11T00:00:00+00:00")
    [c] = cli.build(con, r2, per_mile=0.25)["cars"]
    assert c["listed_since"] == "2026-09-01" and c["days"] == 10 and c["days_from_scan"]


def test_delivery_is_free_nearby_then_shipping_plus_inspection():
    d = analysis.Delivery()
    assert d.cost(0) == 0 and d.cost(200) == 0
    assert d.cost(201) == 500 + 200
    assert d.cost(777) == 350 + 0.60 * 777 + 200
    near, far = car("n", 51000, 1000, 7), car("f", 50000, 1000, 777)
    assert [x["vin"] for x in analysis.rank([far, near], 0.25, d)] == ["n", "f"]
    assert far["delivery"] == 1016 and near["delivery"] == 0



def test_market_per_mile_reads_the_cpo_mileage_slope():
    cars = [dict(c, condition="cpo") for c in synthetic(ms_discount=0)]
    assert abs(analysis.market_per_mile(cars) - 0.15) < 0.02
    assert analysis.market_per_mile(cars[:5]) == 0.15
    assert all("resid" not in c for c in cars)


def test_build_defaults_to_market_mileage_rate(tmp_path, monkeypatch):
    fake_sources(monkeypatch)
    con = store.connect(tmp_path / "c.db")
    run, _ = cli.scan(con, ZIP, [CROWN], ["carfax", "toyota"])
    w = cli.build(con, run)["weights"]
    assert w["per_mile_source"] == "market" and 0.05 < w["per_mile"] < 0.3
    assert cli.build(con, run, per_mile=0.4)["weights"] == dict(w, per_mile=0.4, per_mile_source="flag")


def test_carfax_reads_doc_fee_value_and_followers(carfax):
    assert sum(l["doc_fee"] is not None for l in carfax) > len(carfax) / 2
    assert any(l["value"] for l in carfax) and all(l["followers"] is not None for l in carfax)
    assert sources.doc_fee([{"feeType": "document_fee", "fee": 699}]) == 699
    assert sources.doc_fee(None) is None


def test_fees_come_from_listing_then_dealer_then_median():
    a = dict(car("a", 1, dist=1), dealer="Toyota of Waco", doc_fee=150)
    b = dict(car("b", 1, dist=1), dealer="Toyota Of Waco", doc_fee=None)
    c = dict(car("c", 1, dist=1), dealer="Elsewhere Toyota", doc_fee=None)
    d = dict(car("d", 1, dist=1), dealer="Third", doc_fee=850)
    analysis.impute_fees([a, b, c, d])
    assert (a["fee"], a["fee_source"]) == (150, "listing")
    assert (b["fee"], b["fee_source"]) == (150, "dealer")
    assert (c["fee"], c["fee_source"]) == (500, "median")


def test_fee_is_part_of_effective_cost():
    cheap_fee = dict(car("x", 50000), doc_fee=100)
    dear_fee = dict(car("y", 49500), doc_fee=899)
    assert [c["vin"] for c in analysis.rank([dear_fee, cheap_fee], 0.0)] == ["x", "y"]


def test_leverage_counts_each_signal_and_says_why():
    old = dict(car("o", 52000), dealer="Big", days=130, cut=1000,
               prices={"carfax": 54000, "toyota": 52000}, value=50000, resid=3000, followers=0)
    fresh = dict(car("f", 52000), dealer="Small", days=3, history=[["t2", 52000]], prices={"toyota": 52000},
                 followers=9)
    fleet = [dict(car(f"s{i}", 50000), dealer="Big") for i in range(4)]
    analysis.leverage([old, fresh] + fleet, sigma=1500)
    assert old["leverage"] == 2 + 1 + 1 + 1 + 1 + 1
    assert any("130 days" in w for w in old["leverage_why"]) and any("$2,000 higher" in w for w in old["leverage_why"])
    assert fresh["leverage"] == -1 and fresh["leverage_why"] == ["9 shoppers following it"]


def test_days_counted_from_our_own_scans_do_not_earn_leverage():
    c = dict(car("n", 58000), days=200, days_from_scan=True)
    analysis.leverage([c])
    assert c["leverage"] == 0


def test_leverage_ignores_pennies_and_counts_one_cut_once():
    tiny = dict(car("t", 50000), cut=1, prices={"carfax": 50001, "toyota": 50000})
    same = dict(car("s", 50000), cut=4000, prices={"carfax": 54000, "toyota": 50000})
    analysis.leverage([tiny, same])
    assert tiny["leverage"] == 0 and tiny["leverage_why"] == []
    assert same["leverage"] == 1 and len(same["leverage_why"]) == 2


def test_a_new_cheaper_source_is_not_a_price_cut(con):
    day1 = [dict(l, source="toyota") for l in listings(("m", 57990))]
    store.record_run(con, "z", day1, [], ts="2026-01-01")
    day2 = day1 + listings(("m", 53572))
    r2 = store.record_run(con, "z", day2, [], ts="2026-01-02")
    assert store.source_cuts(con, r2) == {"m": 0}
    day3 = [dict(day1[0], price=55000)] + listings(("m", 53572))
    r3 = store.record_run(con, "z", day3, [], ts="2026-01-03")
    assert store.source_cuts(con, r3) == {"m": 2990}


@pytest.mark.parametrize("raw,hint,want", [
    ("OXYGEN WHITE/BLACK", "White", ("Oxygen White / Black roof", "White", True)),
    ("BLACK(227)/RED(3U5)", "Red", ("Finish Line Red / Black roof", "Red", True)),
    ("BLACK(227)/METAL(1L5)", "Blue", ("Heavy Metal / Black roof", "Gray", True)),
    ("Heavy Metal with Black bi-tone [extra_cost_color]", "Gray", ("Heavy Metal / Black roof", "Gray", True)),
    ("HEAVY METAL/BLACK", "Blue", ("Heavy Metal / Black roof", "Gray", True)),
    ("Storm Cloud\xa0[illustrative]", "Gray", ("Storm Cloud", "Gray", False)),
    ("BRONZE AGE*", "Tan", ("Bronze Age", "Bronze", False)),
    ("Bronze Age [extra_cost_color]", "Brown", ("Bronze Age", "Bronze", False)),
    ("Inked", "Black", ("Inked", "Black", False)),
    (None, "Red", ("Red", "Red", False)),
    (None, "Unspecified", (None, None, False)),
])
def test_paint_names_normalize_across_sources(raw, hint, want):
    assert sources.exterior(raw, hint) == want


def test_interior_ignores_a_wrong_source_family():
    assert sources.interior("Saddle Tan leather trim", "Black") == "Tan"
    assert sources.interior("BLACK(TSUYASUMI)") == "Black"


def test_every_source_yields_colors(carfax, toyota):
    new = sources.parse_tcom(TCOM, ZIP, CROWN, {})
    for ls in (carfax, toyota, new):
        assert sum(l["ext_family"] is not None for l in ls) > 0.9 * len(ls)


def test_merge_prefers_the_named_paint_over_a_generic_color(con):
    a = sources.listing("carfax", "V", 2026, "Platinum", 50000, 1, 1, "", "", "", "", ext=("Red", "Red", False))
    b = sources.listing("toyota", "V", 2026, "Platinum", 51000, 1, 1, "", "", "", "",
                        ext=("Finish Line Red / Black roof", "Red", True))
    [c] = store.merged(con, store.record_run(con, "z", [a, b], []))
    assert (c["ext_color"], c["ext_family"], c["two_tone"], c["price"]) == ("Finish Line Red / Black roof", "Red", True, 50000)


DEALER_FEES = [{"feeType": "document_fee", "fee": 2937}, {"feeType": "DEALER BENEFITS (OPTIONAL)", "fee": 1674},
               {"feeType": "ELECTRONIC FILING FEE", "fee": 268}, {"feeType": "DOCUMENTATION FEE", "fee": 995}]


def test_carfax_fee_total_is_split_into_items_and_optional_is_not_owed():
    owed, items = sources.parse_fees(DEALER_FEES)
    assert owed == 995 + 268
    assert items == [("DEALER BENEFITS (OPTIONAL)", 1674, "optional"), ("ELECTRONIC FILING FEE", 268, "filing"),
                     ("DOCUMENTATION FEE", 995, "doc")]
    assert sources.parse_fees([{"feeType": "document_fee", "fee": 900}, {"feeType": "Doc Fee", "fee": 100}]) == \
        (900, [("Doc and other fees", 900, "doc")])
    assert sources.parse_fees(None) == (None, [])


@pytest.mark.parametrize("name,cat", [
    ("Dealer Service & E Filing Fees", "suspect"), ("Pre-Delivery Service Charge", "suspect"),
    ("Dealer Processing Charge", "suspect"), ("Electronic Registration Filing Fee", "filing"),
    ("Document & Other Fees", "doc"), ("DOC FEE", "doc"), ("Theft Deterrent Package", "optional"),
    ("Mystery Line", "suspect"),
])
def test_fee_categories(name, cat):
    assert sources.fee_category(name) == cat


def test_fee_flags_say_what_to_refuse_and_question():
    c = dict(car("b", 50000), fees_json=json.dumps(sources.parse_fees(DEALER_FEES)[1]
                                                    + [["Pre-Delivery Service Charge", 399, "suspect"]]))
    hi = dict(car("h", 50000), fees_json=json.dumps([["Doc Fee", 1494, "doc"]]))
    analysis.fee_flags([c, hi])
    assert c["fee_flags"] == ["refuse: DEALER BENEFITS (OPTIONAL) $1,674 (listed as optional)",
                              "push back: Pre-Delivery Service Charge $399"]
    assert hi["fee_flags"] == ["high doc fee: $1,494"]


def test_tcom_addons_pick_out_protection_and_dealer_extras():
    addons = [a for v in TCOM for a in sources.tcom_addons(v)]
    names = {n for n, _, _ in addons}
    assert any("TOYOGUARD" in n for n in names) and all(cat == "addon" for _, _, cat in addons)
    assert not any("Floor Mats" in n for n in names)


def test_new_discount_is_the_flexible_quarter():
    cars = [dict(car(f"n{i}", 58000 - 100 * i), condition="new", msrp=58000) for i in range(8)]
    assert analysis.new_discount(cars) == pytest.approx(600 / 58000)
    assert analysis.new_discount(cars[:3]) == 0.0


def test_offer_never_exceeds_asking_and_scales_with_leverage():
    soft = dict(car("s", 50000), expected=49000, value=48000, leverage=3, fee=500)
    hard = dict(car("h", 50000), expected=52000, value=53000, leverage=0, fee=500)
    huge = dict(car("x", 50000), expected=50000, leverage=9, fee=500)
    analysis.targets([soft, hard, huge])
    assert soft["fair"] == 48500 and soft["offer"] == 47000
    assert hard["fair"] == 50000 and hard["offer"] == 50000
    assert huge["offer"] == 47500
    assert soft["otd_target"] == 47500


def test_new_car_offer_uses_msrp_and_drops_dealer_installed_options():
    c = dict(car("n", 59000), condition="new", msrp=59000, expected=58000, leverage=0,
             fee_items=[["Dealer-installed options", 1500, "addon"]])
    analysis.targets([c], discount=0.01)
    assert c["fair"] == round(median([58000, round(59000 * 0.99)])) - 1500
    assert any("1,500 dealer-installed" in w for w in c["offer_why"])


def test_new_discount_ignores_cars_whose_price_is_only_msrp():
    real = [dict(car(f"r{i}", 57000), condition="new", msrp=58000) for i in range(8)]
    fill = [dict(car(f"f{i}", 58000), condition="new", msrp=58000, msrp_only=True) for i in range(40)]
    assert analysis.new_discount(real + fill) == pytest.approx(1000 / 58000)


def test_parse_tcom_marks_msrp_fallback_prices():
    got = sources.parse_tcom(TCOM, ZIP, CROWN, {})
    by = {v["vin"]: v for v in TCOM}
    for l in got:
        p = by[l["vin"]]["price"]
        assert l["msrp_only"] == (not (p.get("advertizedPrice") or p.get("sellingPrice") or p.get("nonSpAdvertizedPrice")))
    assert any(l["msrp_only"] for l in got) and not all(l["msrp_only"] for l in got)


def test_a_real_dealer_price_on_another_site_clears_msrp_only(con):
    tc = sources.listing("toyota_new", "N", 2026, "Platinum", 58000, 0, 5, "", "", "", "", condition="new",
                         msrp=58000, msrp_only=True)
    cf = sources.listing("carfax_new", "N", 2026, "Platinum", 56900, 0, 5, "", "", "", "", condition="new")
    [c] = store.merged(con, store.record_run(con, "z", [tc, cf], []))
    assert c["price"] == 56900 and not c["msrp_only"]


def test_digest_reports_new_platinums_drops_and_failures():
    def c(vin, status, price, **kw):
        return dict(car(vin, price), status=status, cost=price, condition="cpo", city="Waco", state="TX", dealer="D", **kw)
    base = {"run": {"errors": []}, "profile": {"focus": ["Platinum"], "title": "Crown"}}
    assert cli.digest(dict(base, cars=[c("a", "", 50000)])) is None
    msg = cli.digest(dict(base, cars=[c("a", "NEW", 50000), c("b", "NEW", 46000), c("d", "DROP -500", 49000),
                                      c("x", "NEW", 1, accident=True)]))
    assert msg == "Crown: 2 new (best $46,000 CPO, Waco TX); 1 price drop"
    assert cli.digest(dict(base, run={"errors": [["crown:toyota_new", "boom"]]}, cars=[])) == "Crown: failed: crown:toyota_new"


def test_notify_only_fires_when_something_changed(tmp_path, monkeypatch):
    fake_sources(monkeypatch)
    sent = []
    monkeypatch.setattr(cli, "notify", lambda m, h: sent.append(m))
    args = ["--db", str(tmp_path / "c.db"), "--html", str(tmp_path / "r.html"), "--notify", "--sources", "carfax,toyota", "--profiles", "crown"]
    cli.main(args)
    cli.main(args)
    assert len(sent) == 1 and re.match(r"Toyota Crown Platinum: \d+ new \(best \$[\d,]+ CPO, ", sent[0])


@pytest.mark.parametrize("labels,want", [
    (["Personal Use"], "Personal"), (["Personal Lease"], "Lease"), (["Personal Use", "Personal Lease"], "Lease"), (["Rental Use"], "Rental"),
    (["Fleet"], "Fleet/corporate"), (["Corporate Use"], "Fleet/corporate"), (["Commercial Use"], "Commercial"),
    (["Personal Use", "Rental"], "Rental"), (["Vehicle Use", None], None), (["Multiple Use"], "Multiple"),
])
def test_prior_use_normalizes_to_the_most_concerning(labels, want):
    assert sources.prior_use(labels) == want


def test_sources_carry_prior_use(carfax, toyota):
    for ls in (carfax, toyota):
        assert sum(l["prior_use"] is not None for l in ls) > len(ls) / 2
        assert any(l["prior_use"] == "Rental" for l in ls)
    assert {l["prior_use"] for l in sources.parse_tcom(TCOM, ZIP, CROWN, {})} == {"New"}


def test_merge_keeps_the_most_concerning_prior_use(con):
    a = sources.listing("carfax", "V", 2026, "Platinum", 50000, 1, 1, "", "", "", "", use="Personal")
    b = sources.listing("toyota", "V", 2026, "Platinum", 51000, 1, 1, "", "", "", "", use="Rental")
    [c] = store.merged(con, store.record_run(con, "z", [a, b], []))
    assert c["prior_use"] == "Rental"



def test_es_profile_keeps_only_the_300h_and_decodes_trim_from_the_vin():
    cf = sources.carfax(ZIP, ES300H, get=fake_get)
    assert cf and all(l["vin"][4:7] == "A1C" and l["model"] == "es300h" for l in cf)
    assert {l["trim"] for l in cf} <= {"Luxury", "Ultra Luxury", "Base / F Sport Design", "F Sport Handling", "Base"}
    assert all(l["trim"] == "Luxury" for l in cf if l["vin"].startswith("58AEA1C"))
    assert all(l["trim"] == "Ultra Luxury" for l in cf if l["vin"].startswith("58AFA1C"))
    assert any(l["prior_use"] == "Lease" for l in cf)


def test_es_certified_uses_the_lexus_series_and_lexus_dealers():
    dealers = {}
    ty = sources.toyota(ZIP, ES300H, get=fake_get, dealers=dealers)
    assert len(ty) > 50 and all(l["distance"] < sources.UNKNOWN_DISTANCE and l["state"] for l in ty)
    assert any(code.startswith("6") for code in dealers)


def test_both_profiles_write_their_own_pages(tmp_path, monkeypatch, capsys):
    fake_sources(monkeypatch)
    page = tmp_path / "report.html"
    assert cli.main(["--db", str(tmp_path / "c.db"), "--html", str(page), "--sources", "carfax,toyota"]) == 0
    out = capsys.readouterr().out
    assert "== Toyota Crown Platinum ==" in out and "== Lexus ES 300h Luxury / Ultra Luxury ==" in out
    assert "WARNING" not in out
    es = (tmp_path / "report-es300h.html").read_text()
    assert '"key":"es300h"' in es and '"miles":[10000,25000]' in es and "report-crown.html" in es
    assert page.read_text() == (tmp_path / "report-crown.html").read_text()
    con = sqlite3.connect(tmp_path / "c.db")
    assert dict(con.execute("SELECT model, COUNT(DISTINCT vin) FROM listings GROUP BY model").fetchall()).keys() == {"crown", "es300h"}


def test_profiles_do_not_see_each_others_cars_in_change_detection(tmp_path, monkeypatch):
    fake_sources(monkeypatch)
    con = store.connect(tmp_path / "c.db")
    cli.scan(con, ZIP, [CROWN], ["carfax"])
    run, _ = cli.scan(con, ZIP, [CROWN, ES300H], ["carfax"])
    crown = cli.build(con, run, CROWN)
    es = cli.build(con, run, ES300H)
    assert crown["gone"] == [] and all(c["status"] == "" for c in crown["cars"])
    assert {c["status"] for c in es["cars"]} == {"NEW"} and {c["model"] for c in es["cars"]} == {"es300h"}


def test_dealer_url_prefers_the_certified_inventory_page():
    def org(*urls):
        return {"primaryContact": [{"uricommunication": [{"uriid": {"value": u}} for u in urls]}]}
    assert sources.dealer_url(org("https://d.com", "https://d.com/new-inventory/index.htm?",
                                  "https://d.com/l-certified-inventory/index.htm?")) == "https://d.com/l-certified-inventory/index.htm?"
    assert sources.dealer_url(org("https://d.com/contact.htm", "https://d.com")) == "https://d.com"
    assert sources.dealer_url({}) is None


def test_lexus_cars_never_link_to_a_toyota_page():
    ty = sources.toyota(ZIP, ES300H, get=fake_get, dealers={})
    assert ty and not any("toyotacertified.com" in l["url"] for l in ty)
    assert all(not l["url_exact"] for l in ty)
    cr = sources.toyota(ZIP, CROWN, get=fake_get, dealers={})
    assert all(l["url_exact"] and "toyotacertified.com/content/tcuv" in l["url"] for l in cr)


def test_merge_prefers_an_exact_listing_link_over_a_dealer_page(con):
    lx = sources.listing("toyota", "V", 2025, "", 53999, 1, 30, "Example Lexus", "", "", "https://dealer.example/l-certified-inventory/",
                         url_exact=False, profile=ES300H)
    cf = sources.listing("carfax", "V", 2025, "", 54500, 1, 30, "Example Lexus", "", "", "https://www.carfax.com/vehicle/V", profile=ES300H)
    [c] = store.merged(con, store.record_run(con, "z", [lx, cf], []), "es300h")
    assert c["price"] == 53999 and c["url"] == "https://www.carfax.com/vehicle/V" and c["url_exact"]


def test_every_car_keeps_a_dealer_inventory_fallback(carfax):
    assert sum(bool(l["dealer_url"]) for l in carfax) > len(carfax) / 2
    lx = sources.listing("toyota", "V", 2025, "", 53999, 1, 30, "N", "", "", "https://d.example/l-certified/", url_exact=False,
                         dealer_url="https://d.example/l-certified/", profile=ES300H)
    cf = sources.listing("carfax", "V", 2025, "", 54500, 1, 30, "N", "", "", "https://www.carfax.com/vehicle/V", profile=ES300H)
    con = store.connect(":memory:")
    [c] = store.merged(con, store.record_run(con, "z", [lx, cf], []), "es300h")
    assert c["url"].startswith("https://www.carfax.com/") and c["dealer_url"] == "https://d.example/l-certified/"


def test_configured_zip_prefers_env_then_config_file(tmp_path):
    cfg = tmp_path / "c.json"
    assert cli.configured_zip({}, cfg) is None
    cfg.write_text(json.dumps({"zip": "11111"}))
    assert cli.configured_zip({}, cfg) == "11111"
    assert cli.configured_zip({"CARFINDATRON_ZIP": "22222"}, cfg) == "22222"


def test_scan_without_a_zip_refuses(monkeypatch, capsys):
    monkeypatch.delenv("CARFINDATRON_ZIP")
    assert cli.main(["--sources", "carfax"]) == 2
    assert "no search ZIP" in capsys.readouterr().err


def test_home_zip_is_not_in_any_tracked_file():
    """The real origin comes from the developer's own config at run time; it is never written into this test."""
    home = cli.configured_zip(config=REAL_CONFIG, env={})
    if not home:
        pytest.skip("no local config, so nothing to protect")
    import subprocess
    root = Path(__file__).resolve().parent.parent
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root,
                           capture_output=True, text=True, check=True).stdout.split()
    leaks = [f for f in files if (root / f).is_file() and home in (root / f).read_text(errors="ignore")]
    assert leaks == []
