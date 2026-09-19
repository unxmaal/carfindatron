"""SQLite store: every listing from every source on every run."""

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    zip TEXT NOT NULL,
    ok INTEGER NOT NULL,
    errors TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS listings (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'crown',
    vin TEXT NOT NULL,
    year INTEGER, trim TEXT, price INTEGER, miles INTEGER, distance INTEGER,
    dealer TEXT, city TEXT, state TEXT, url TEXT, one_owner INTEGER, accident INTEGER,
    condition TEXT NOT NULL DEFAULT 'cpo', listed_since TEXT, msrp INTEGER, note TEXT,
    doc_fee INTEGER, value INTEGER, followers INTEGER,
    ext_color TEXT, ext_family TEXT, two_tone INTEGER, int_color TEXT, fees_json TEXT, msrp_only INTEGER, prior_use TEXT, url_exact INTEGER, dealer_url TEXT,
    PRIMARY KEY (run_id, source, vin)
);
CREATE TABLE IF NOT EXISTS dealers (
    code TEXT NOT NULL, zip TEXT NOT NULL, name TEXT, city TEXT, state TEXT, distance INTEGER,
    fetched TEXT NOT NULL, url TEXT, PRIMARY KEY (code, zip)
);
CREATE INDEX IF NOT EXISTS listings_vin ON listings(vin);
"""
COLS = ("source", "model", "vin", "year", "trim", "price", "miles", "distance", "dealer", "city", "state",
        "url", "one_owner", "accident", "condition", "listed_since", "msrp", "note", "doc_fee", "value", "followers",
        "ext_color", "ext_family", "two_tone", "int_color", "fees_json", "msrp_only", "prior_use", "url_exact", "dealer_url")
MIGRATIONS = {"model": "TEXT NOT NULL DEFAULT 'crown'", "condition": "TEXT NOT NULL DEFAULT 'cpo'", "listed_since": "TEXT", "msrp": "INTEGER",
              "note": "TEXT", "doc_fee": "INTEGER", "value": "INTEGER", "followers": "INTEGER",
              "ext_color": "TEXT", "ext_family": "TEXT", "two_tone": "INTEGER", "int_color": "TEXT", "fees_json": "TEXT", "msrp_only": "INTEGER", "prior_use": "TEXT", "url_exact": "INTEGER", "dealer_url": "TEXT"}
DEALER_TTL_DAYS = 30
USE_RANK = {u: i for i, u in enumerate(("Rental", "Commercial", "Fleet/corporate", "Multiple", "Lease", "Personal", "New"))}


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(listings)")}
    for col, decl in MIGRATIONS.items():
        if col not in have:
            con.execute(f"ALTER TABLE listings ADD COLUMN {col} {decl}")
    if "url" not in {r["name"] for r in con.execute("PRAGMA table_info(dealers)")}:
        con.execute("ALTER TABLE dealers ADD COLUMN url TEXT")
        con.execute("DELETE FROM dealers")
        con.commit()
    return con


def record_run(con, zip_code, listings, errors, ts=None):
    ts = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        run_id = con.execute("INSERT INTO runs(ts, zip, ok, errors) VALUES (?,?,?,?)",
                             (ts, zip_code, int(not errors), json.dumps(errors))).lastrowid
        con.executemany(
            f"INSERT OR REPLACE INTO listings(run_id, {', '.join(COLS)}) "
            f"VALUES (?, {', '.join('?' * len(COLS))})",
            [(run_id, *(l[c] for c in COLS)) for l in listings])
    return run_id


def merged(con, run_id, model="crown"):
    """One row per VIN for a run and vehicle profile: lowest price wins, every source's quote kept."""
    cars = {}
    for r in con.execute("SELECT * FROM listings WHERE run_id=? AND model=? ORDER BY price", (run_id, model)):
        c = cars.get(r["vin"])
        if c is None:
            c = cars[r["vin"]] = {k: r[k] for k in COLS if k != "source"}
            c["prices"] = {}
        c["prices"][r["source"]] = r["price"]
        c["trim"] = c["trim"] or r["trim"]
        c["one_owner"] = bool(c["one_owner"] or r["one_owner"])
        c["accident"] = bool(c["accident"] or r["accident"])
        if r["url_exact"] and not c["url_exact"]:
            c["url"], c["url_exact"] = r["url"], True
        if r["prior_use"] and (not c["prior_use"] or USE_RANK.get(r["prior_use"], 9) < USE_RANK.get(c["prior_use"], 9)):
            c["prior_use"] = r["prior_use"]
        c["msrp_only"] = bool(c["msrp_only"]) and (r["price"] > c["price"] or bool(r["msrp_only"]))
        c["msrp"] = c["msrp"] or r["msrp"]
        c["note"] = c["note"] or r["note"]
        for k in ("doc_fee", "value", "followers", "int_color", "fees_json", "dealer_url"):
            if c[k] is None:
                c[k] = r[k]
        if r["ext_color"] and len(r["ext_color"]) > len(c["ext_color"] or ""):
            c.update(ext_color=r["ext_color"], ext_family=r["ext_family"], two_tone=bool(r["two_tone"]))
        if r["listed_since"] and (not c["listed_since"] or r["listed_since"] < c["listed_since"]):
            c["listed_since"] = r["listed_since"]
        if c["distance"] >= 9999 and r["distance"] < 9999:
            c.update(distance=r["distance"], city=r["city"], state=r["state"])
    return list(cars.values())


def load_dealers(con, zip_code):
    return {r["code"]: (r["name"], r["city"], r["state"], r["distance"], r["url"]) for r in con.execute(
        "SELECT * FROM dealers WHERE zip=? AND fetched > datetime('now', ?)", (zip_code, f"-{DEALER_TTL_DAYS} days"))}


def save_dealers(con, zip_code, dealers):
    with con:
        con.executemany("INSERT OR REPLACE INTO dealers (code, zip, name, city, state, distance, url, fetched) "
                        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
                        [(code, zip_code, *d[:4], d[4] if len(d) > 4 else None) for code, d in dealers.items()])


def runs(con, ok_only=False):
    q = "SELECT * FROM runs" + (" WHERE ok=1" if ok_only else "") + " ORDER BY id"
    return [dict(r) for r in con.execute(q)]


def price_history(con):
    """vin -> [[ts, lowest price that run], ...] over successful runs."""
    hist = {}
    for r in con.execute("""SELECT l.vin, r.ts, MIN(l.price) p FROM listings l JOIN runs r ON r.id=l.run_id
                            WHERE r.ok=1 GROUP BY l.run_id, l.vin ORDER BY r.id"""):
        hist.setdefault(r["vin"], []).append([r["ts"], r["p"]])
    return hist


def run_sources(con, run_id, model="crown"):
    return {r[0] for r in con.execute("SELECT DISTINCT source FROM listings WHERE run_id=? AND model=?", (run_id, model))}


def source_cuts(con, run_id):
    """vin -> largest drop any single source made in its own price for that car, over successful runs up to
    run_id. A car first appearing on a second site at a lower price is not a cut."""
    cuts = {}
    for r in con.execute("""
            SELECT l.vin, l.source,
                   (SELECT e.price FROM listings e JOIN runs er ON er.id=e.run_id
                    WHERE e.vin=l.vin AND e.source=l.source AND er.ok=1 AND e.run_id<=? ORDER BY e.run_id LIMIT 1) first,
                   l.price now
            FROM listings l WHERE l.run_id=?""", (run_id, run_id)):
        cuts[r["vin"]] = max(cuts.get(r["vin"], 0), (r["first"] or r["now"]) - r["now"])
    return cuts


def status(con, run_id, cars, model="crown"):
    """Label each car NEW / DROP / UP / BACK against the latest earlier successful run that covered the same
    sources, comparing only those sources' listings; return VINs gone."""
    srcs = run_sources(con, run_id, model)
    prev = next((r[0] for r in con.execute("SELECT id FROM runs WHERE ok=1 AND id<? ORDER BY id DESC", (run_id,))
                 if srcs and srcs <= run_sources(con, r[0], model)), None)
    if prev is None:
        for c in cars:
            c["status"] = "NEW"
        return []
    marks = ",".join("?" * len(srcs))
    before = {r["vin"]: r["p"] for r in con.execute(
        f"SELECT vin, MIN(price) p FROM listings WHERE run_id=? AND model=? AND source IN ({marks}) GROUP BY vin",
        (prev, model, *srcs))}
    ever = {r["vin"] for r in con.execute(
        f"SELECT DISTINCT vin FROM listings l JOIN runs r ON r.id=l.run_id WHERE r.ok=1 AND l.run_id<? "
        f"AND l.model=? AND l.source IN ({marks})", (run_id, model, *srcs))}
    for c in cars:
        old = before.get(c["vin"])
        if old is None:
            c["status"] = "BACK" if c["vin"] in ever else "NEW"
        elif c["price"] != old:
            c["status"] = f"{'DROP' if c['price'] < old else 'UP'} {c['price'] - old:+,}"
        else:
            c["status"] = ""
    live = {c["vin"] for c in cars}
    return sorted(v for v in before if v not in live)
