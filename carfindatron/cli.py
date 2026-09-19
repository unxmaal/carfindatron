"""Scan Carfax, Toyota/Lexus Certified and toyota.com for each vehicle profile, store every listing, and report."""

import argparse
import json
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path

from . import analysis, report, sources, store
from .profiles import CROWN, PROFILES

HOME = Path.home() / ".local/share/carfindatron"
CONFIG = Path.home() / ".config/carfindatron/config.json"


def configured_zip(env=None, config=None):
    """The search origin lives outside the repository: $CARFINDATRON_ZIP, else ~/.config/carfindatron/config.json."""
    env = os.environ if env is None else env
    config = CONFIG if config is None else config
    if env.get("CARFINDATRON_ZIP"):
        return env["CARFINDATRON_ZIP"]
    try:
        return json.loads(Path(config).read_text()).get("zip")
    except (OSError, ValueError):
        return None


def scan(con, zip_code, profiles, names):
    listings, errors = [], []
    dealers = store.load_dealers(con, zip_code)
    for prof in profiles:
        for name in prof.sources:
            if name not in names:
                continue
            try:
                listings += sources.SOURCES[name](zip_code, prof, dealers=dealers)
            except Exception as e:
                errors.append([f"{prof.key}:{name}", f"{type(e).__name__}: {e}"])
    store.save_dealers(con, zip_code, dealers)
    if not listings:
        return None, errors
    return store.record_run(con, zip_code, listings, errors), errors


def build(con, run_id, profile=CROWN, per_mile=None, delivery=analysis.Delivery()):
    run = dict(con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    cars = store.merged(con, run_id, profile.key)
    gone = store.status(con, run_id, cars, profile.key) if run["ok"] else []
    per_mile_source = "flag" if per_mile is not None else "market"
    if per_mile is None:
        per_mile = analysis.market_per_mile(cars)
    model = analysis.fit(cars)
    states = {k: analysis.by_state([c for c in cars if not k or c["condition"] == k]) if model else []
              for k in ("", "cpo", "new")}
    analysis.rank(cars, per_mile, delivery)
    hist = store.price_history(con)
    cuts = store.source_cuts(con, run_id)
    today = date.fromisoformat(run["ts"][:10])
    for c in cars:
        c["history"] = hist.get(c["vin"], [])
        c["cut"] = cuts.get(c["vin"], 0)
        c["days_from_scan"] = not c.get("listed_since") and bool(c["history"])
        if c["days_from_scan"]:
            c["listed_since"] = c["history"][0][0][:10]
        c["days"] = (today - date.fromisoformat(c["listed_since"])).days if c.get("listed_since") else None
    analysis.leverage(cars, model and model["sigma"])
    analysis.fee_flags(cars)
    analysis.targets(cars, analysis.new_discount(cars, profile.focus))
    home = next((c["state"] for c in sorted(cars, key=lambda c: c["distance"])), "")
    errors = [e for e in json.loads(run["errors"]) if ":" not in e[0] or e[0].startswith(profile.key + ":")]
    return {"zip": run["zip"], "run": {"ts": run["ts"], "errors": errors},
            "profile": {"key": profile.key, "title": profile.title, "focus": list(profile.focus),
                        "has_new": any(s.endswith("_new") for s in profile.sources), "miles": profile.miles,
                        "nav": [{"key": p.key, "title": p.title, "href": f"report-{p.key}.html"} for p in PROFILES.values()]},
            "cars": cars, "gone": gone, "model": model, "states": states, "trend": report.trend(con, profile),
            "home_state": home, "weights": {"per_mile": per_mile, "per_mile_source": per_mile_source, **analysis.asdict(delivery)}}


def focus_cars(payload, clean=False):
    focus = payload["profile"]["focus"]
    return [c for c in payload["cars"] if c["trim"] in focus and not (clean and c.get("accident"))]


def text(payload, top=25):
    plat = sorted(focus_cars(payload), key=lambda c: c["cost"])
    head = (f"  {'eff cost':>8} {'price':>8} {'offer':>8} {'miles':>7} {'dist':>5} {'deliver':>7} {'fee':>5} {'vs model':>9} {'days':>5} {'lev':>3}  "
            f"{'cond':4} {'yr':4} {'change':11} dealer / location")
    lines = [f"== {payload['profile']['title']} ==", head, "-" * 110]
    for c in plat[:top]:
        vs = f"{c['resid']:+,}" if "resid" in c else ""
        days = "" if c["days"] is None else str(c["days"])
        flag = " ACCIDENT" if c["accident"] else ""
        lines.append(f"{'*' if c['pareto'] else ' '} {c['cost']:>8,.0f} {c['price']:>8,} {c['offer']:>8,} {c['miles']:>7,} "
                     f"{c['distance']:>5,} {c['delivery']:>7,} {c['fee']:>5,} {vs:>9} {days:>5} {c['leverage']:>3}  {c['condition']:4} {c['year']:<4} "
                     f"{c.get('status', ''):11} {c['dealer']} / {c['city']}, {c['state']}{flag}")
    if len(plat) > top:
        lines.append(f"  ... {len(plat) - top} more in the report")
    n_new = sum(c["condition"] == "new" for c in plat)
    lines.append(f"\n{' / '.join(payload['profile']['focus'])}: {len(plat) - n_new} CPO, {n_new} new. "
                 f"{len(payload['cars'])} stored this run.")
    lines += [f"WARNING: {n} failed: {e}" for n, e in payload["run"]["errors"]]
    return "\n".join(lines)


def digest(payload):
    """One-line summary of what changed among clean focus-trim cars, or None when nothing did."""
    plat = focus_cars(payload, clean=True)
    new = [c for c in plat if c.get("status") == "NEW"]
    drops = [c for c in plat if (c.get("status") or "").startswith("DROP")]
    parts = []
    if new:
        best = min(new, key=lambda c: c["cost"])
        parts.append(f"{len(new)} new (best ${best['price']:,} {best['condition'].upper()}, "
                     f"{best['city'] or best['dealer']} {best['state']})")
    if drops:
        parts.append(f"{len(drops)} price drop{'s' if len(drops) > 1 else ''}")
    if payload["run"]["errors"]:
        parts.append("failed: " + ", ".join(n for n, _ in payload["run"]["errors"]))
    return f"{payload['profile']['title']}: " + "; ".join(parts) if parts else None


def notify(message, html):
    import subprocess
    script = f'display notification {json.dumps(message)} with title "carfindatron" subtitle {json.dumps(str(html))}'
    subprocess.run(["osascript", "-e", script], check=False, timeout=20)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zip", default=None, help="search origin; default from $CARFINDATRON_ZIP or ~/.config/carfindatron/config.json")
    p.add_argument("--save-zip", action="store_true", help="remember --zip in ~/.config/carfindatron/config.json")
    p.add_argument("--profiles", default=",".join(PROFILES), help=f"vehicles to scan: {', '.join(PROFILES)}")
    p.add_argument("--per-mile", type=float, default=None,
                   help="$ penalty per odometer mile (default: the market rate fitted from this scan's CPO prices)")
    d = analysis.Delivery()
    p.add_argument("--free-radius", type=float, default=d.free_radius, help="miles you would drive to; no cost inside it")
    p.add_argument("--ship-base", type=float, default=d.ship_base, help="$ flat part of an open-carrier quote")
    p.add_argument("--ship-per-mile", type=float, default=d.ship_per_mile, help="$ per mile of shipping distance")
    p.add_argument("--ship-min", type=float, default=d.ship_min, help="$ minimum shipping charge")
    p.add_argument("--inspection", type=float, default=d.inspection, help="$ pre-purchase inspection for a remote buy")
    p.add_argument("--sources", default=",".join(sources.SOURCES),
                   help="toyota_new drives an off-screen Chrome window; drop it to stay browser-free")
    p.add_argument("--db", type=Path, default=HOME / "carfindatron.db")
    p.add_argument("--html", type=Path, default=HOME / "report.html",
                   help="landing page; each vehicle also gets report-<profile>.html beside it")
    p.add_argument("--report-only", action="store_true", help="rebuild the pages from the last run, no fetch")
    p.add_argument("--open", action="store_true", help="open the page in a browser")
    p.add_argument("--notify", action="store_true", help="macOS notification when focus-trim cars appear or drop in price")
    a = p.parse_args(argv)
    profiles = [PROFILES[k] for k in a.profiles.split(",")]
    if a.save_zip and a.zip:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"zip": a.zip}))
    a.zip = a.zip or configured_zip()
    if not a.zip and not a.report_only:
        print("no search ZIP: pass --zip NNNNN --save-zip once, or set CARFINDATRON_ZIP", file=sys.stderr)
        return 2

    a.db.parent.mkdir(parents=True, exist_ok=True)
    con = store.connect(a.db)
    if a.report_only:
        last = con.execute("SELECT MAX(id) FROM runs").fetchone()[0]
        if last is None:
            print("no runs stored yet", file=sys.stderr)
            return 1
        run_id = last
    else:
        run_id, errors = scan(con, a.zip, profiles, a.sources.split(","))
        if run_id is None:
            print("every source failed: " + "; ".join(": ".join(e) for e in errors), file=sys.stderr)
            return 1
    delivery = analysis.Delivery(a.free_radius, a.ship_base, a.ship_per_mile, a.ship_min, a.inspection)
    a.html.parent.mkdir(parents=True, exist_ok=True)
    messages = []
    for i, prof in enumerate(profiles):
        payload = build(con, run_id, prof, a.per_mile, delivery)
        page = report.render(payload)
        (a.html.parent / f"report-{prof.key}.html").write_text(page)
        if i == 0:
            a.html.write_text(page)
        print(text(payload) + "\n")
        if a.notify and not a.report_only and (msg := digest(payload)):
            messages.append(msg)
    print(f"report: {a.html}")
    if messages:
        notify("; ".join(messages), a.html)
    if a.open:
        webbrowser.open(a.html.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
