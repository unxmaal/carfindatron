"""Ranking, a hedonic price model, and regional anomalies."""

import json
from dataclasses import asdict, dataclass
from statistics import median

MIN_MOVE = 250
MIN_FIT = 12


@dataclass(frozen=True)
class Delivery:
    """Cost of getting a car home. Inside free_radius you drive over and back. Beyond it you buy remotely:
    open-carrier shipping (a flat base plus a per-mile rate, with a minimum) and an independent pre-purchase
    inspection."""
    free_radius: float = 200
    ship_base: float = 350
    ship_per_mile: float = 0.60
    ship_min: float = 500
    inspection: float = 200

    def cost(self, distance):
        if distance <= self.free_radius:
            return 0.0
        return max(self.ship_min, self.ship_base + self.ship_per_mile * distance) + self.inspection


def dealer_key(c):
    return (c.get("dealer") or "").lower().replace("toyota", "").replace(" of ", " ").strip(" ·,")


def impute_fees(cars):
    """Doc fee per car: its own listing's, else the same dealer's on another listing, else the median."""
    by_dealer = {}
    for c in cars:
        if c.get("doc_fee") is not None:
            by_dealer.setdefault(dealer_key(c), c["doc_fee"])
    known = [c["doc_fee"] for c in cars if c.get("doc_fee") is not None]
    typical = round(median(known)) if known else 0
    for c in cars:
        if c.get("doc_fee") is not None:
            c["fee"], c["fee_source"] = c["doc_fee"], "listing"
        elif dealer_key(c) in by_dealer:
            c["fee"], c["fee_source"] = by_dealer[dealer_key(c)], "dealer"
        else:
            c["fee"], c["fee_source"] = typical, "median"


def rank(cars, per_mile, delivery=Delivery()):
    if any("fee" not in c for c in cars):
        impute_fees(cars)
    for c in cars:
        c["delivery"] = round(delivery.cost(c["distance"]))
        c["cost"] = c["price"] + per_mile * c["miles"] + c["delivery"] + c["fee"]
    for c in cars:
        key = (c["price"], c["miles"], c["distance"])
        c["pareto"] = not any(
            o is not c and o.get("trim") == c.get("trim") and o["price"] <= c["price"] and o["miles"] <= c["miles"]
            and o["distance"] <= c["distance"] and (o["price"], o["miles"], o["distance"]) != key
            for o in cars)
    return sorted(cars, key=lambda c: c["cost"])


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular design")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def features(c, trims, years, has_new):
    return [1.0] + [float(c["trim"] == t) for t in trims[1:]] + \
        [float(c["year"] == y) for y in years[1:]] + \
        ([float(c.get("condition") == "new")] if has_new else []) + [c["miles"] / 1000.0]


def fit(cars):
    """OLS of price on trim, model year, new-vs-CPO and miles. Sets c['resid'] (price minus expected)."""
    rows = [c for c in cars if c.get("trim")]
    by_trim = {}
    for c in rows:
        by_trim.setdefault(c["trim"], []).append(c["price"])
    trims = sorted(by_trim, key=lambda t: (median(by_trim[t]), t))
    years = sorted({c["year"] for c in rows})
    has_new = len({c.get("condition", "cpo") for c in rows}) > 1
    p = len(trims) + len(years) + has_new
    if len(rows) < max(MIN_FIT, 2 * p):
        return None
    xs = [features(c, trims, years, has_new) for c in rows]
    xtx = [[sum(x[i] * x[j] for x in xs) for j in range(p)] for i in range(p)]
    xty = [sum(x[i] * c["price"] for x, c in zip(xs, rows)) for i in range(p)]
    beta = solve(xtx, xty)
    for x, c in zip(xs, rows):
        c["expected"] = round(sum(b * v for b, v in zip(beta, x)))
        c["resid"] = c["price"] - c["expected"]
    resid = [c["resid"] for c in rows]
    mad = median(abs(r - median(resid)) for r in resid)
    sigma = 1.4826 * mad or 1.0
    for c in rows:
        c["z"] = round(c["resid"] / sigma, 2)
    coef = dict(zip(["base"] + [f"trim:{t}" for t in trims[1:]] + [f"year:{y}" for y in years[1:]]
                    + (["new"] if has_new else []) + ["per_1k_miles"], (round(b) for b in beta)))
    return {"n": len(rows), "sigma": round(sigma), "coef": coef}


def market_per_mile(cars, fallback=0.15):
    """$ the market knocks off a CPO Crown per odometer mile, read from a CPO-only fit of the price model."""
    model = fit([dict(c) for c in cars if c.get("condition", "cpo") == "cpo"])
    if not model or model["coef"]["per_1k_miles"] >= 0:
        return fallback
    return round(-model["coef"]["per_1k_miles"] / 1000, 3)


def leverage(cars, sigma=None):
    """Signals that a dealer has room to move, as (points, reasons). A heuristic from public listing data, not a
    prediction: nothing here has been checked against what dealers actually accepted."""
    stock = {}
    for c in cars:
        stock[dealer_key(c)] = stock.get(dealer_key(c), 0) + 1
    for c in cars:
        pts, why = 0, []
        days = c.get("days")
        if days is not None and not c.get("days_from_scan"):
            if days >= 120:
                pts += 2; why.append(f"listed {days} days")
            elif days >= 60:
                pts += 1; why.append(f"listed {days} days")
        cut = c.get("cut") or 0
        if cut >= MIN_MOVE:
            pts += 1; why.append(f"cut ${cut:,} since first seen")
        quotes = sorted((c.get("prices") or {}).values())
        gap = quotes[-1] - quotes[0] if len(quotes) > 1 else 0
        if gap >= MIN_MOVE:
            why.append(f"also listed ${gap:,} higher elsewhere; the lower price is public")
            if gap != cut:
                pts += 1
        if c.get("value") and c["price"] > c["value"]:
            pts += 1; why.append(f"${c['price'] - c['value']:,} over Carfax value")
        if sigma and c.get("resid") is not None and c["resid"] > sigma:
            pts += 1; why.append(f"${c['resid']:,} over the market model")
        if c.get("condition") == "new" and c.get("msrp") and c["price"] >= c["msrp"]:
            why.append("priced at or above MSRP")
        if c.get("condition") == "new" and c.get("note"):
            pts -= 1; why.append("not on the lot yet")
        n = stock[dealer_key(c)]
        if n >= 5:
            pts += 1; why.append(f"dealer has {n} of this model listed")
        if (c.get("followers") or 0) >= 5:
            pts -= 1; why.append(f"{c['followers']} shoppers following it")
        c["leverage"], c["leverage_why"] = pts, why
    return cars


HIGH_DOC_FEE = 1000


def fee_flags(cars):
    """Itemized fees and add-ons per car, with what to refuse or question."""
    for c in cars:
        items = json.loads(c.get("fees_json") or "[]")
        flags = []
        for name, amount, cat in items:
            amt = f" ${amount:,}" if amount else ""
            if cat == "optional":
                flags.append(f"refuse: {name}{amt} (listed as optional)")
            elif cat == "suspect":
                flags.append(f"push back: {name}{amt}")
            elif cat == "doc" and amount and amount >= HIGH_DOC_FEE:
                flags.append(f"high doc fee: ${amount:,}")
            elif cat == "addon":
                flags.append(f"ask to remove: {name}{amt}")
        c["fee_items"], c["fee_flags"] = items, flags
    return cars


def new_discount(cars, focus=("Platinum",)):
    """Discount off MSRP that the more flexible quarter of dealers advertise on new focus-trim cars (75th percentile)."""
    d = sorted((c["msrp"] - c["price"]) / c["msrp"] for c in cars
               if c.get("condition") == "new" and c.get("trim") in focus and c.get("msrp") and not c.get("msrp_only"))
    return max(0.0, d[3 * len(d) // 4]) if len(d) >= 8 else 0.0


def targets(cars, discount=0.0):
    """A suggested opening offer on the vehicle price. Fair price is the median of the market model's
    expected price, Carfax's value and (new cars) MSRP less the flexible-quarter discount, never above asking.
    The offer then goes 1% under fair per leverage point, capped at 5%. A heuristic, not a quote."""
    for c in cars:
        anchors, why = [], []
        if c.get("expected"):
            anchors.append(c["expected"]); why.append(f"market model ${c['expected']:,}")
        if c.get("value"):
            anchors.append(c["value"]); why.append(f"Carfax value ${c['value']:,}")
        if c.get("condition") == "new" and c.get("msrp"):
            m = round(c["msrp"] * (1 - discount))
            anchors.append(m); why.append(f"MSRP ${c['msrp']:,} less {discount:.1%} = ${m:,}")
        fair = round(median(anchors)) if anchors else c["price"]
        dio = sum(a for _, a, cat in c.get("fee_items") or [] if cat == "addon" and a)
        if dio:
            fair -= dio; why.append(f"less ${dio:,} dealer-installed options you can decline")
        fair = min(c["price"], fair)
        cut = min(0.05, 0.01 * max(0, c.get("leverage") or 0))
        if cut:
            why.append(f"{cut:.0%} under fair for {c['leverage']} leverage point{'s' if c['leverage'] > 1 else ''}")
        c["fair"] = fair
        c["offer"] = min(c["price"], int(fair * (1 - cut)) // 100 * 100)
        c["offer_why"] = why
        paid = sum(a for _, a, cat in c.get("fee_items") or [] if cat in ("doc", "filing") and a)
        c["otd_target"] = c["offer"] + (paid or c.get("fee") or 0)
    return cars


def by_state(cars):
    """Median model residual per state, cheapest first. Needs fit() to have run."""
    groups = {}
    for c in cars:
        if "resid" in c and c.get("state"):
            groups.setdefault(c["state"], []).append(c)
    return sorted(({"state": s, "n": len(g), "median_resid": round(median(c["resid"] for c in g)),
                    "median_distance": round(median(c["distance"] for c in g))}
                   for s, g in groups.items()), key=lambda g: g["median_resid"])
